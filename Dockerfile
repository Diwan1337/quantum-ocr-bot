# ---------- базовый образ ------------
FROM python:3.11-slim

# Чтобы логи вашего бота не задерживались в буфере
ENV PYTHONUNBUFFERED=1

# ---------- системные зависимости -----
RUN apt-get update && \
    apt-get install -y \
      tesseract-ocr \
      tesseract-ocr-rus \
      libgl1 \
      libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# ---------- рабочая директория -------
WORKDIR /app

# ---------- зависимости Python --------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------- копируем код --------------
COPY . .

# ---------- точка входа ---------------
CMD ["python", "bot.py"]
