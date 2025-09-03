import os
from dotenv import load_dotenv
load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
DB_PATH = os.getenv("DB_PATH", "./gymdiary.db")
SUPPORT_DEEPLINK = os.getenv("SUPPORT_DEEPLINK", "https://t.me/ObotizactiaSuppBot?start")
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "60"))
