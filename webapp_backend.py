import os
import hmac
import hashlib
from urllib.parse import parse_qsl
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static", "webapp")

app = FastAPI(title="GymDiary WebApp Backend")

# Статика (пока заглушка)
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def verify_init_data(init_data: str, bot_token: str, max_age_sec: int = 24 * 3600) -> dict:
    """
    Telegram WebApp initData verification.
    Returns parsed dict if OK, else raises.
    """
    if not init_data:
        raise HTTPException(status_code=401, detail="Missing initData")

    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Missing hash")

    # optional freshness check
    auth_date = int(data.get("auth_date", "0") or "0")
    if auth_date <= 0:
        raise HTTPException(status_code=401, detail="Missing/invalid auth_date")

    # If you want strict expiration, uncomment:
    # import time
    # if time.time() - auth_date > max_age_sec:
    #     raise HTTPException(status_code=401, detail="initData expired")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if calculated_hash != received_hash:
        raise HTTPException(status_code=401, detail="Bad initData signature")

    return data


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
def api_me(x_tg_init_data: str | None = Header(default=None)):
    # Telegram initData будем передавать заголовком X-Tg-Init-Data (так удобнее)
    bot_token = os.getenv("TG_TOKEN", "")
    payload = verify_init_data(x_tg_init_data or "", bot_token)

    # user лежит строкой JSON в поле "user"
    # тут просто вернём сырьё (позже распарсим и подтянем БД)
    return {"ok": True, "auth": payload}
