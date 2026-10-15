"""
Конфигурация парсера тендеров
"""

# URL для парсинга
TARGET_URL = "https://www.rts-tender.ru/poisk/search?id=eae6b56e-55f8-43a0-b9f1-b9ad04cc1a66"

# Настройки браузера
HEADLESS_MODE = True
WAIT_TIME = 10000  # мс
TIMEOUT = 90000    # мс
KEEP_BROWSER_OPEN = False

# Telegram Bot
import os as _os
from pathlib import Path as _Path
BOT_TOKEN = (
    _Path(_os.getenv("TELEGRAM_TOKEN_FILE", "/run/secrets/telegram_token")).read_text().strip()
    if _os.getenv("TELEGRAM_ENABLED", "true").strip().lower() in ("true", "1", "yes")
    else ""
)
CHAT_ID = ["-1003613651457"]

# База данных
DATABASE_PATH = "tenders.db"

# Настройки дедупликации
STOP_ON_DUPLICATES = 5

# Настройки планировщика
CHECK_INTERVAL_MINUTES = 30  # Интервал проверки в минутах
RUN_CONTINUOUS = True  # Запускать постоянно в цикле

# User-Agent ротация
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]

# Настройки парсинга
SCROLL_DURATION = 7  # секунды для плавного скролла
PAGE_WAIT_TIME = 10  # секунды ожидания перед переходом на след. страницу


# Прокси в формате "IP:PORT:ЛОГИН:ПАРОЛЬ", несколько — через пробел
PROXIES = ""

# URL для проверки прокси (корень сайта легче, чем страница поиска)
PROXY_CHECK_URL = TARGET_URL

# Таймаут проверки одной прокси, секунды
PROXY_CHECK_TIMEOUT = 15
