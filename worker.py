import asyncio
import os
import re
import cv2
import pytesseract
import gspread

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from gspread.exceptions import WorksheetNotFound, SpreadsheetNotFound

# Импортим состояние из state.py
from state import pending_external_screenshot

# ─── 1. Загрузка конфигурации ────────────────────────────────
load_dotenv()
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID") or ""
if not SPREADSHEET_ID:
    raise RuntimeError("❌ SPREADSHEET_ID не найден в .env")

# ─── 2. Подключение к Google Sheets ─────────────────────────
gc = gspread.service_account(
    filename="google_key.json",
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ],
)
try:
    ss = gc.open_by_key(SPREADSHEET_ID)
except SpreadsheetNotFound:
    raise RuntimeError("❌ Таблица не найдена или нет доступа.")

# ─── 3. Основная таблица баллов (EGE) ────────────────────────
try:
    sheet = ss.worksheet("EGE")
except WorksheetNotFound:
    sheet = ss.add_worksheet("EGE", rows=200, cols=30)
    # Заголовки предметов должны быть добавлены администратором вручную.

# ─── 4. Лист с отзывами ───────────────────────────────────────
try:
    feedback_sheet = ss.worksheet("Feedback")
except WorksheetNotFound:
    feedback_sheet = ss.add_worksheet("Feedback", rows=100, cols=3)
    feedback_sheet.append_row(["tg_id", "feedback_type", "content"])

# ─── 5. Конфигурация Tesseract (для Windows) ─────────────────
TESS_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESS_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESS_PATH

# ─── 6. Регулярка и словарь предметов ─────────────────────────
PAIR_RE = re.compile(r"([А-ЯЁа-яё() ]+)[\s\n]+(\d{1,3})")
ALIASES = {
    "математика профильная": "math",
    "математика профиль":    "math",
    "физика":                "phys",
    "русский язык":          "rus",
    "информатика":           "inf",
    "информатика кегэ":      "inf",
    "информатика (кегэ)":    "inf",
}


def extract_scores(path: str) -> dict[str, int]:
    """Оцифровывает картинку, извлекает пары «предмет — балл»."""
    img = cv2.imread(path)

    # 1) upscale ×3
    img = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    # 2) CLAHE контраст
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    img = cv2.merge((cl, a, b))

    # 3) в серый + Otsu threshold
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 4) OCR (oem 3 = LSTM, psm 6 = блок текста)
    cfg = "--oem 3 --psm 6"
    text = pytesseract.image_to_string(thr, lang="rus", config="--oem 3 --psm 6")
    print("RAW OCR:\n", text)

    result: dict[str, int] = {}
    for subj_raw, val in PAIR_RE.findall(text):
        subj = re.sub(r"[()]", "", subj_raw).strip().lower()
        for alias, code in ALIASES.items():
            if alias in subj:
                result[code] = int(val)
                break
    return result


def matches_sheet(tg_id: int, scores: dict[str, int], student_id: str) -> bool:
    """
    Сверяет/дописывает баллы в таблицу EGE:
    - Если пользователя нет — добавляет новую строку.
    - Иначе обновляет отличающиеся баллы.
    Всегда возвращает True (считаем проверку пройденной).
    """
    header = sheet.row_values(1)
    # Найдём индекс колонки student_id (должен быть 2)
    try:
        idx_sid = header.index("student_id")  # 0-based
    except ValueError:
        idx_sid = None

    cell = sheet.find(str(tg_id))
    if cell is None:
        new_row = [""] * len(header)
        new_row[0] = str(tg_id)
        if idx_sid is not None:
            new_row[idx_sid] = student_id
        for subj, val in scores.items():
            if subj in header:
                new_row[header.index(subj)] = str(val)
        sheet.append_row(new_row)
        return True

    # Если уже есть строка — при необходимости пишем student_id и обновляем баллы
    row_idx = cell.row
    if idx_sid is not None:
        existing = sheet.cell(row_idx, idx_sid + 1).value  # +1, потому что API 1-based
        if not existing:
            sheet.update_cell(row_idx, idx_sid + 1, student_id)

    for subj, val in scores.items():
        if subj in header:
            col = header.index(subj) + 1
            sheet.update_cell(row_idx, col, str(val))
    return True


async def run_worker(bot, q: asyncio.Queue):
    while True:
        task = await q.get()
        tg_id      = task["tg_id"]
        student_id = task.get("student_id", "")

        try:
            # 1) OCR
            scores = extract_scores(task["file"])
            await bot.send_message(tg_id, f"🔍 Распознано: {scores}")

            # 2) Запись баллов
            ok = matches_sheet(tg_id, scores, student_id)
            result_msg = "✅ Баллы подтверждены!" if ok else "⚠️ Не совпало, куратор проверит вручную."
            await bot.send_message(tg_id, result_msg)

            if ok:
                # сразу предлагаем кнопки "Редактировать баллы" и "Редактировать отзыв"
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✏️ Редактировать баллы", callback_data="edit_scores")],
                    [InlineKeyboardButton(text="✏️ Редактировать отзыв", callback_data="edit_review")],
                ])
                await bot.send_message(tg_id, "Если нужно что-то поменять, выберите опцию:", reply_markup=kb)

            # 3) Инструкция по отзыву на внешних площадках
            if ok:
                fcell = feedback_sheet.find(str(tg_id))
                if fcell is None:
                    await bot.send_message(
                        tg_id,
                        "🟢ТЗ К ОТЗЫВАМ НА ВП (внешние площадки) 🟢\n\n"
                        "Почему ты выбрала «99 баллов»?\n"
                        "Поделись своими впечатлениями об уроках, конспектах, домашних заданиях. Может, запомнились какие-то лайфхаки или что-то на уроках оказалось для тебя наиболее ценным и эффективным?\n"
                        "Расскажи, в чем улучшились твои знания во время обучения в «99 баллов» и какой результат ты получила.\n"
                        "Кому бы ты порекомендовала нашу школу и почему?\n\n"
                        "👆 Если оставишь отзыв на ВП, то пришли скрин\n\n"
                        "Озывы ты можешь оставить на одной из этих площадок:\n"
                        "- ОТЗОВИК (в поисковике набери «отзовик 99 баллов»)\n"
                        "- Яндекс: https://yandex.ru/maps/org/99_ballov/59607351472/?ll=49.143410%2C55.787270&z=13.85\n"
                        "- Сравни: https://www.sravni.ru/shkola/99-ballov/otzyvy/\n"
                        "- 2ГИС: https://2gis.ru/kazan/firm/70000001044938528\n\n"
                        "Отзыв можно оставить в нескольких местах.\n\n"
                        "Если не хочешь оставлять отзыв, отправь просто «-».\n\n"
                        "📹 Видео-отзыв:\n"
                        "1. Держите телефон горизонтально.\n"
                        "2. Проверьте качество звука — без громких шумов.\n\n"
                        "Что рассказать:\n"
                        "- Ваше имя;\n"
                        "- Из какого города вы;\n"
                        "- На каком предмете(ах) и в каком году вы занимались;\n"
                        "- Сколько баллов вы написали на экзамене;\n"
                        "- Почему вы выбрали «99 баллов»;\n"
                        "- Ваши впечатления об уроках, конспектах и домашних заданиях;\n"
                        "- Какие лайфхаки вы вынесли;\n"
                        "- В чём улучшились ваши знания;\n"
                        "- Кому бы вы порекомендовали нашу школу и почему;\n"
                        "- Небольшое заключение и напутствие.\n"
                        "Обратная связь: @diwan1337",
                    )
                    # теперь мы ждём от этого пользователя именно скриншот площадки
                    await bot.send_message(tg_id,
                                           "🙏 Спасибо за баллы! Теперь, пожалуйста, оставьте отзыв на внешней площадке…")
                    pending_external_screenshot.add(tg_id)
                else:
                    await bot.send_message(
                        tg_id,
                        "🙂 Ваш отзыв уже сохранён. Чтобы обновить, отправьте новый текст или видео или скриншот площадки."
                    )


        except Exception as exc:

            await bot.send_message(tg_id, f"⚠️ Ошибка проверки: {exc}")


        finally:

            if os.path.exists(task["file"]):
                os.remove(task["file"])
