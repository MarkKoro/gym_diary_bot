import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Явно загружаем .env рядом с кодом проекта.
# Это стабильно работает даже если процесс запущен не из корня репозитория.
load_dotenv(os.path.join(BASE_DIR, ".env"))

TG_TOKEN = os.getenv("TG_TOKEN")
YK_TOKEN = os.getenv("YK_TOKEN")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
PROJECT_KEY = os.getenv("PROJECT_KEY", "")
WEBAPP_PUBLIC_PATH = os.getenv("WEBAPP_PUBLIC_PATH", "/gymapp")
YOOKASSA_RETURN_URL = os.getenv("YOOKASSA_RETURN_URL", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
PAYMENTS_EXTERNAL_ONLY = str(os.getenv("PAYMENTS_EXTERNAL_ONLY", "1")).strip().lower() in {"1", "true", "yes", "on"}
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
DB_PATH = os.getenv("DB_PATH", "./gymdiary.db")
SUPPORT_DEEPLINK = os.getenv("SUPPORT_DEEPLINK", "https://t.me/ObotizactiaSuppBot?start")
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "0"))
# Публичная ссылка на бота для шеринга прогресса
BOT_PUBLIC_LINK = os.getenv("BOT_PUBLIC_LINK", "")
# Канал, на который надо подписаться перед использованием бота
SUBSCRIPTION_CHAT = os.getenv("SUBSCRIPTION_CHAT")
# Ссылка для подписки
JOIN_URL = os.getenv("JOIN_URL", "https://t.me/obotization")
# Размера пула HTTP-соединений к Telegram API
TG_POOL_SIZE = int(os.getenv("TG_POOL_SIZE", "10"))
# Количество одновременных операций с SQLite
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")


def get_openai_api_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY") or OPENAI_API_KEY


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL") or OPENAI_MODEL or ""


def resolve_yookassa_return_url() -> str:
    explicit = str(YOOKASSA_RETURN_URL or "").strip()
    if explicit:
        return explicit
    base = str(PUBLIC_BASE_URL or "").rstrip("/")
    path = str(WEBAPP_PUBLIC_PATH or "").rstrip("/")
    return f"{base}{path}/payment-return.html"
# Список администраторов (tg_id), которые могут выполнять административные команды
ADMIN_IDS = {
    int(x) for x in (os.getenv("ADMINS") or os.getenv("ADMIN_IDS") or "").replace(",", " ").split()
    if x.strip().isdigit()
}
# Кнопка «Инструкция» (Telegraph)
INSTRUCTION_URL = os.getenv(
    "INSTRUCTION_URL",
    "https://telegra.ph/Instrukciya-k-Progressoru-12-03"
)
