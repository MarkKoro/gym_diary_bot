import os
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from settings import TG_TOKEN
from telegram_webapp_auth import (
    InitDataError,
    TelegramInitData,
    verify_and_parse_init_data,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static", "webapp")

app = FastAPI(title="GymDiary WebApp backend")

MAX_INITDATA_AGE_SEC = 24 * 60 * 60

# Статика (пока заглушка)
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_tg_init_data(
    request: Request,
    x_telegram_initdata: str | None = Header(default=None, alias="X-Telegram-InitData"),
) -> TelegramInitData:
    """
    Берём initData либо из заголовка X-Telegram-InitData (предпочтительно),
    либо из query param ?initData=...
    """
    init_data = x_telegram_initdata
    if not init_data:
        init_data = request.query_params.get("initData")

    if not init_data:
        raise HTTPException(status_code=401, detail="Missing initData")

    try:
        return verify_and_parse_init_data(
            init_data=init_data,
            bot_token=TG_TOKEN,
            max_age_sec=MAX_INITDATA_AGE_SEC,
        )
    except InitDataError as e:
        raise HTTPException(status_code=401, detail=f"Invalid initData: {e}")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_path):
        return JSONResponse({"ok": True, "note": "index.html not found yet"})
    return FileResponse(index_path)


@app.get("/api/me")
def api_me(tg: TelegramInitData = Depends(get_tg_init_data)):
    # user лежит строкой JSON в поле "user"
    # тут просто вернём сырьё (позже распарсим и подтянем БД)
    return {"ok": True, "auth": tg.raw}


@app.get("/whoami")
def whoami(tg: TelegramInitData = Depends(get_tg_init_data)):
    return {
        "ok": True,
        "user_id": tg.user.id,
        "username": tg.user.username,
        "first_name": tg.user.first_name,
        "last_name": tg.user.last_name,
        "auth_date": tg.auth_date,
    }
