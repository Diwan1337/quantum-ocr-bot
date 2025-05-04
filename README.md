````
<h1 align="center">Quantum‑OCR Bot 🤖🔬</h1>
<p align="center">
  Телеграм‑бот, который принимает скрины баллов ЕГЭ/ОГЭ, 
  распознаёт их с помощью Tesseract OCR и автоматически
  сверяет с Google Sheets.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python">
  <img src="https://img.shields.io/badge/aiogram-3.x-blueviolet">
  <img src="https://img.shields.io/badge/Tesseract-5.x-brightgreen">
  <img src="https://img.shields.io/badge/License-MIT-yellow">
</p>

---

## 📑 Содержание
1. [Что умеет бот](#-что-умеет-бот)
2. [Быстрый старт](#-быстрый-старт)
3. [Настройка `.env`](#️-настройка-env)
4. [Подготовка Google Sheets](#️-подготовка-google-sheets)
5. [Подготовка Tesseract‑OCR](#️-подготовка-tesseract-ocr)
6. [Архитектура проекта](#️-архитектура-проекта)
7. [Словарь предметов (`ALIASES`)](#️-словарь-предметов-aliases)
8. [Развёртывание в Docker](#🐳-развёртывание-в-docker)
9. [FAQ / Troubleshooting](#-faq--troubleshooting)
10. [Contributing](#️-contributing)
11. [License](#-license)

---

## 🚀 Что умеет бот

| Шаг | Действие |
|-----|----------|
| 1.  | Пользователь отправляет изображение (фото / скрин) в бот. |
| 2.  | Бот сохраняет файл и ставит задачу в асинхронную очередь. |
| 3.  | Воркер → <br>• препроцессит картинку (resize ×3, CLAHE, threshold) <br>• Tesseract OCR (`rus`) → чистый текст <br>• regex выдёргивает пары «предмет — балл». |
| 4.  | Предметы нормализуются через `ALIASES` → `math`, `phys`, `rus` и т.д. |
| 5.  | В Google Sheet: <br>• если `tg_id` отсутствует → создаётся новая строка; <br>• если есть → сверка баллов, обновление отличающихся (+ допуск ±1). |
| 6.  | Бот отвечает: **✅ Баллы подтверждены!** или **⚠️ Ошибка**. |

---

## ⚡ Быстрый старт

```bash
# 1. Клонируем репо и заходим
git clone https://github.com/<username>/quantum-ocr-bot.git
cd quantum-ocr-bot

# 2. Создаём виртуальное окружение
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Ставим зависимости
pip install -r requirements.txt

# 4. Копируем конфиг и заполняем
cp .env.example .env          # открой .env и впиши свои значения

# 5. Запуск
python bot.py
````

> ⚠️ **Важно:** `.env` и `google_key.json` не публикуем, они игнорируются `.gitignore`.

---

## ⚙️ Настройка `.env`

| Ключ                | Описание                                                                           |
| ------------------- | ---------------------------------------------------------------------------------- |
| **BOT\_TOKEN**      | Токен вашего Telegram‑бота от `@BotFather`.                                        |
| **SPREADSHEET\_ID** | ID Google‑таблицы (строка между `/d/` и `/edit`).                                  |
| **SHEET\_NAME**     | Имя листа (по умолчанию `EGE`).                                                    |
| **SERVICE\_KEY**    | Путь к JSON‑ключу сервис‑аккаунта (по умолчанию `google_key.json`).                |
| **TESSERACT\_PATH** | (Win) Полный путь до `tesseract.exe`. На Linux/WSL не нужен, если бинарь в `PATH`. |

---

## 🗂️ Подготовка Google Sheets

1. Создай таблицу → назови лист `EGE` (или любое имя → укажи в `.env`).
2. В **первой строке** заголовки:

   ```
   tg_id | math | rus | phys | ...
   ```
3. В Google Cloud Console:

   * **IAM & Admin → Service accounts → + Create** → JSON key.
   * Шарим таблицу на e‑mail сервис‑аккаунта (роль *Editor*).
4. Положи JSON‑файл в корень проекта → назови `google_key.json` (или настрой `SERVICE_KEY`).

---

## 🛠️ Подготовка Tesseract‑OCR

| ОС              | Действие                                                                                                                                              |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Windows**     | Скачай `tesseract-ocr-w64-setup-5.x.exe` (репо Mannheim). При установке — галочка **“Add to PATH”** и выбери язык **Russian**. Пропиши путь в `.env`. |
| **Linux / WSL** | `sudo apt install tesseract-ocr tesseract-ocr-rus`                                                                                                    |
| **macOS**       | `brew install tesseract-lang` (Homebrew уже ставит `rus`).                                                                                            |

Проверь:  `tesseract --version`  → версия ≥ 5.x.

---

## 🗺️ Архитектура проекта

```text
bot.py           # Telegram side (aiogram): принимает медиа, ставит задачу.
worker.py        # OCR + Google Sheets + логика верификации.
requirements.txt
.env.example
.gitignore
README.md
```

![flow](https://user-images.githubusercontent.com/placeholder/flow.png)

---

## 📝 Словарь предметов (`ALIASES`)

```python
ALIASES = {
    "математика профильная": "math",
    "математика профиль":    "math",
    "русский язык":          "rus",
    "физика":                "phys",
}
```

*Добавь свои пары «как на скрине» → «как в колонке».
OCR мечет строчные, так что `.lower()` уже включён.*

---

## 🐳 Развёртывание в Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim

# 1. Tesseract
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-rus libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# .env и google_key.json передаём как volumes / secrets
CMD ["python", "bot.py"]
```

Сборка и запуск:

```bash
docker build -t quantum-ocr-bot .
docker run --env-file .env -v $(pwd)/google_key.json:/app/google_key.json quantum-ocr-bot
```

---

## ❓ FAQ / Troubleshooting

| Ошибка / Симптом                                 | Причина и решение                                                            |
| ------------------------------------------------ | ---------------------------------------------------------------------------- |
| `TokenValidationError: NoneType`                 | BOT\_TOKEN не задан в `.env`.                                                |
| `SpreadsheetNotFound 404`                        | Неверный `SPREADSHEET_ID` **или** сервис‑аккаунт не имеет доступа к таблице. |
| `pytesseract.pytesseract.TesseractNotFoundError` | Tesseract не установлен или `TESSERACT_PATH` неправильный.                   |
| Пустой `RAW OCR`                                 | Скрин слишком мелкий → включи upscale ×3, CLAHE (уже по умолч.).             |
| Бот пишет «Не совпало…»                          | В таблице нет строки с `tg_id`. Бот её создаст, если включён `upsert_row`.   |

---

## 🤝 Contributing

Pull‑requests и issues приветствуются!
Формат коммита — Conventional Commits (`feat:`, `fix:`, `docs:` …).
Перед PR запусти `black .` и `flake8`.

---

## 📄 License

MIT.  Используй, форкай, звездуй ⭐ — только не храни секретные токены в публичном репо 😉.

```
