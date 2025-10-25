import os
from dotenv import load_dotenv
load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
DB_PATH = os.getenv("DB_PATH", "./gymdiary.db")
SUPPORT_DEEPLINK = os.getenv("SUPPORT_DEEPLINK", "https://t.me/ObotizactiaSuppBot?start")
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "60"))
# Канал, на который надо подписаться перед использованием бота
SUBSCRIPTION_CHAT = os.getenv("SUBSCRIPTION_CHAT")
# Ссылка для подписки
JOIN_URL = os.getenv("JOIN_URL", "https://t.me/obotization")
# Размера пула HTTP-соединений к Telegram API
TG_POOL_SIZE = int(os.getenv("TG_POOL_SIZE", "10"))
# Количество одновременных операций с SQLite
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
# Список администраторов (tg_id), которые могут выполнять административные команды
ADMIN_IDS = {
    int(value)
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip()
}
