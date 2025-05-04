import asyncio, os, re, cv2, pytesseract, gspread
from gspread.exceptions import WorksheetNotFound, SpreadsheetNotFound

# ─────────────────── OCR binary (Windows) ────────────────────
TESS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESS):
    pytesseract.pytesseract.tesseract_cmd = TESS

# ─────────────────── Gspread auth ────────────────────────────
gc = gspread.service_account(
    filename="google_key.json",
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ],
)

SPREADSHEET_ID = ""   # ← ваш ID
try:
    ss = gc.open_by_key(SPREADSHEET_ID)
except SpreadsheetNotFound:
    raise RuntimeError("❌ Таблица не найдена или нет доступа.")

try:
    sheet = ss.worksheet("EGE")
except WorksheetNotFound:
    sheet = ss.add_worksheet("EGE", rows=200, cols=30)

# ─────────────────── Настройки OCR ───────────────────────────
PAIR_RE = re.compile(r"([А-ЯЁа-яё ]+)[\s\n]+(\d{1,3})")
ALIASES = {
    "математика профильная": "math",
    "математика профиль":    "math",
    "физика":                "phys",
    "русский язык":          "rus",
}

def extract_scores(path: str) -> dict[str, int]:
    img = cv2.imread(path)

    # 1) upscale ×3
    img = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    # 2) CLAHE контраст
    lab   = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    cl    = clahe.apply(l)
    img   = cv2.merge((cl, a, b))
    img   = cv2.cvtColor(img, cv2.COLOR_LAB2BGR)

    # 3) в серый + Otsu threshold
    gray  = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 4) OCR (oem 3 = LSTM, psm 6 = "block of text")
    cfg = "--oem 3 --psm 6"
    text = pytesseract.image_to_string(thr, lang="rus", config=cfg)
    print("RAW OCR:\n", text)

    pairs = re.findall(r"([А-ЯЁа-яё ]+)[\s\n]+(\d{1,3})", text)
    return {
        ALIASES.get(s.strip().lower(), s.strip().lower()): int(v)
        for s, v in pairs
    }



def matches_sheet(tg_id: int, scores: dict[str, int]) -> bool:
    cell = sheet.find(str(tg_id))
    header = sheet.row_values(1)

    # Если ученика нет — добавляем новую строку
    if cell is None:
        new_row = [""] * len(header)
        new_row[0] = str(tg_id)
        for subj, val in scores.items():
            if subj in header:
                new_row[header.index(subj)] = str(val)
        sheet.append_row(new_row)
        return True   # считаем, что проверка пройдена

    # --- ученик есть, сверяем ---
    row    = sheet.row_values(cell.row)
    gdata  = {header[i].lower(): int(row[i])
              for i in range(1, len(row)) if row[i]}

    for subj, val in scores.items():
        if subj not in gdata or abs(gdata[subj] - val) > 1:
            # обновляем ячейку, если отличается
            col = header.index(subj) + 1
            sheet.update_cell(cell.row, col, str(val))
    return True


# ────────────── Асинхронный воркер ───────────────────────────
async def run_worker(bot, q: asyncio.Queue):
    while True:
        task = await q.get()

        try:
            scores = extract_scores(task["file"])
            #DEBUG: отправить распознанное
            await bot.send_message(task["tg_id"], f"🔍 Распознано: {scores}")

            ok = matches_sheet(task["tg_id"], scores)
            msg = "✅ Баллы подтверждены!" if ok else "⚠️ Не совпало, куратор проверит вручную."
            await bot.send_message(task["tg_id"], msg)

        except Exception as exc:
            await bot.send_message(task["tg_id"], f"⚠️ Ошибка проверки: {exc}")

        finally:
            if os.path.exists(task["file"]):
                os.remove(task["file"])
