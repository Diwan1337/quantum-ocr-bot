# bot.py
import asyncio, os, uuid, tempfile, pathlib
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from dotenv import load_dotenv

# ─── 1. Токен ────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN") or ""
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не найден (ни в .env, ни в коде)!")

# ─── 2. Каталог для временных картинок ──────────────────────
TMP_DIR = pathlib.Path(tempfile.gettempdir()) / "ege_screens"
TMP_DIR.mkdir(exist_ok=True)

queue: asyncio.Queue = asyncio.Queue()
bot, dp = Bot(BOT_TOKEN), Dispatcher()

# ─── 3. Хэндлер фото / документов ───────────────────────────
@dp.message(F.photo | F.document)
async def handle_media(msg: Message):
    file_id = msg.photo[-1].file_id if msg.photo else msg.document.file_id
    tmp_path = TMP_DIR / f"{uuid.uuid4()}.jpg"

    # aiogram‑3: параметр file=
    await bot.download(file=file_id, destination=tmp_path)
    await queue.put({"tg_id": msg.from_user.id, "file": str(tmp_path)})
    await msg.answer("🔍 Получили скрин! Проверяем…")

# ─── 4. Запуск воркера и polling ────────────────────────────
async def main():
    from worker import run_worker           # импорт здесь, чтобы очередь была готова
    asyncio.create_task(run_worker(bot, queue))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
