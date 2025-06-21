import asyncio
import os
import uuid
import tempfile
import pathlib

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ContentType,
    FSInputFile,
    InputMediaPhoto
)
from dotenv import load_dotenv

from state import pending_ege_screenshot, pending_external_screenshot


# ─── 1. Настройка токена и списка ID ─────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN") or ""
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не найден в .env")

# Подготовьте в .env строку вида
# STUDENT_IDS=12345,23456,34567
# и замените на реальные ID ваших учеников
raw_ids = os.getenv("STUDENT_IDS", "")
ALLOWED_STUDENT_IDS = { i.strip() for i in raw_ids.split(",") if i.strip() }

# ─── 2. Папка для временных скринов ───────────────────────────
TMP_DIR = pathlib.Path(tempfile.gettempdir()) / "ege_screens"
TMP_DIR.mkdir(exist_ok=True)

# ─── 3. Инициализация бота и диспетчера ───────────────────────
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
queue: asyncio.Queue = asyncio.Queue()

# ─── 4. Импорт воркера и листа Feedback ────────────────────────
from worker import run_worker, feedback_sheet

# ─── 5. Словари для состояний ─────────────────────────────────
# временный контейнер «ждут ID» после отправки контакта
pending_id: set[int] = set()
# окончательно верифицированные пользователи
verified_ids: set[int] = set()
# Telegram-ID → платформенный ID
user_student: dict[int,str] = {}

# ─── 6. /start — просим контакт ───────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: Message):
    if msg.from_user.id in verified_ids:
        await msg.answer("✅ Вы уже верифицированы и можете отправлять скриншоты баллов.")
        return

    btn = KeyboardButton(text="📱 Поделиться контактом", request_contact=True)
    kb = ReplyKeyboardMarkup(
        keyboard=[[btn]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await msg.answer(
        "Здравствуйте! Чтобы войти в систему, сначала поделитесь контактом через кнопку ниже.",
        reply_markup=kb,
    )


# ─── 7. Обработка контакта — просим ID ───────────────────────
@dp.message(F.contact)
async def handle_contact(msg: Message):
    # Проверяем, что это именно контакт пользователя
    if not msg.contact or msg.contact.user_id != msg.from_user.id:
        await msg.answer("❌ Пожалуйста, нажмите кнопку, чтобы поделиться своим контактом.")
        return

    # Сначала отправляем гайд по тому, где найти ID на платформе
    media = [
        InputMediaPhoto(media=FSInputFile("assets/id1.png")),
        InputMediaPhoto(media=FSInputFile("assets/id2.png")),
        InputMediaPhoto(media=FSInputFile("assets/id3.png")),
    ]
    await bot.send_media_group(msg.chat.id, media)
    # Затем просим пользователя прислать свой ID
    pending_id.add(msg.from_user.id)
    await msg.answer("✅ Контакт получен! Пожалуйста, отправьте свой ID ученика (см. инструкции выше).")


# ─── 8. Обработка текстового сообщения — или ID, или отзыв ─────
@dp.message(F.text)
async def handle_text(msg: Message):
    user = msg.from_user.id
    if user in pending_id:
        txt = msg.text.strip()
        if txt in ALLOWED_STUDENT_IDS:
            verified_ids.add(user)
            pending_id.remove(user)
            user_student[user] = txt

            # 1) подтверждаем верификацию
            await msg.answer("✅ Верификация пройдена! Сейчас покажу, как сделать скрин результатов ЕГЭ.")

            # 2) отправляем EGE-инструкцию
            media = [
                InputMediaPhoto(media=FSInputFile("assets/ege1.png"),
                                caption="📸 **Как сделать скриншот результатов ЕГЭ**"),
                InputMediaPhoto(media=FSInputFile("assets/ege2.png"))
            ]
            await bot.send_media_group(msg.chat.id, media)

            # 3) включаем флаг, что ждём именно EGE-скриншот
            pending_ege_screenshot.add(user)
        else:
            await msg.answer("❌ Неверный ID — попробуйте ещё раз.")
        return

    # если не верифицирован, игнорим; иначе — это отзыв и т.д.
    if user not in verified_ids:
        return

    # Тут вашим уже оставшимся текстом будет отзыв
    cell = feedback_sheet.find(str(user))
    if cell:
        feedback_sheet.update_cell(cell.row, 2, "text")
        feedback_sheet.update_cell(cell.row, 3, txt)
        await msg.answer("✅ Спасибо, ваш отзыв обновлён!")
    else:
        feedback_sheet.append_row([str(user), "text", txt])
        await msg.answer("✅ Спасибо, ваш отзыв сохранён!")


# ─── 9. Обработка фото/документов ────────────────────────────
@dp.message(F.photo | F.document)
async def handle_media(msg: Message):
    user = msg.from_user.id

    # 1) если ждём ЕГЭ-скрин — уходим в OCR
    if user in pending_ege_screenshot:
        pending_ege_screenshot.remove(user)
        tmp_path = TMP_DIR / f"{uuid.uuid4()}.jpg"
        file_id = msg.photo[-1].file_id if msg.photo else msg.document.file_id
        await bot.download(file=file_id, destination=tmp_path)
        await msg.answer("🔍 Получили скрин! Проверяем…")
        await queue.put({
            "tg_id": user,
            "file": str(tmp_path),
            "student_id": user_student.get(user, "")
        })
        return

    # 2) если ждём скрин площадки — сохраняем его в Feedback
    if user in pending_external_screenshot:
        pending_external_screenshot.remove(user)
        file_id = msg.photo[-1].file_id if msg.photo else msg.document.file_id
        file = await bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        cell = feedback_sheet.find(str(user))
        if cell:
            feedback_sheet.update_cell(cell.row, 2, "platform_screenshot")
            feedback_sheet.update_cell(cell.row, 3, url)
        else:
            feedback_sheet.append_row([str(user), "platform_screenshot", url])
        await msg.answer("✅ Скриншот с площадки сохранён!")
        return

    # 3) всё остальное — или не верифицирован, или просто дубль
    if user not in verified_ids:
        return


# ─── 10. Обработка видео-отзыва ──────────────────────────────
@dp.message(F.video | F.video_note)
async def handle_video_feedback(msg: Message):
    user = msg.from_user.id
    if user not in verified_ids:
        return

    fid = msg.video.file_id if msg.video else msg.video_note.file_id
    file = await bot.get_file(fid)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    cell = feedback_sheet.find(str(user))
    if cell:
        feedback_sheet.update_cell(cell.row, 2, "video")
        feedback_sheet.update_cell(cell.row, 3, url)
        await msg.answer("✅ Спасибо, ваш видео-отзыв обновлён!")
    else:
        feedback_sheet.append_row([str(user), "video", url])
        await msg.answer("✅ Спасибо, ваш видео-отзыв сохранён!")

# ─── 11. Запуск воркера и polling ─────────────────────────────
async def main():
    asyncio.create_task(run_worker(bot, queue))
    await dp.start_polling(bot)

# ─── 12. Обработка нажатий на кнопки ───────────────────────────────────────────────
@dp.callback_query(lambda c: c.data == "edit_scores")
async def on_edit_scores(cb: CallbackQuery):
    user = cb.from_user.id
    await cb.answer()  # снимаем «часики»
    pending_ege_screenshot.add(user)
    # Удалим клавиатуру (чтобы предыдущие кнопки пропали)
    await bot.edit_message_reply_markup(user, cb.message.message_id, reply_markup=None)
    await bot.send_message(user, "✏️ Окей, пришлите новый скриншот результатов ЕГЭ.")

@dp.callback_query(lambda c: c.data == "edit_review")
async def on_edit_review(cb: CallbackQuery):
    user = cb.from_user.id
    await cb.answer()
    pending_external_screenshot.add(user)
    await bot.edit_message_reply_markup(user, cb.message.message_id, reply_markup=None)
    await bot.send_message(user, "✏️ Окей, пришлите новый скриншот отзыва на внешней площадке.")


if __name__ == "__main__":
    asyncio.run(main())
