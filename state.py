# после успешной верификации и показа гайдa EGE-скриншота бот ждёт фото ЕГЭ
pending_ege_screenshot: set[int] = set()

# после того как бот отправил инструкцию по отзывам, ждём именно скрина площадки
pending_external_screenshot: set[int] = set()