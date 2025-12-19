import os
from datetime import UTC, datetime, date
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from settings import TG_TOKEN
from telegram_webapp_auth import (
    InitDataError,
    TelegramInitData,
    verify_and_parse_init_data,
)

import db

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


def _today_date() -> date:
    return datetime.now(UTC).date()


def _iso_date(d: date | None) -> str:
    return (d or _today_date()).strftime("%Y-%m-%d")


def _human_date(d: date | None) -> str:
    return (d or _today_date()).strftime("%d-%m-%Y")


def _parse_date_param(date_str: str | None) -> date:
    if not date_str:
        return _today_date()
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты, используйте YYYY-MM-DD")


async def _load_user_settings(user_id: int):
    settings = await db.fetch_user_settings(user_id)
    if not settings:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    system, workouts_per_week = settings
    wpw = int(workouts_per_week) if workouts_per_week is not None else 0
    if wpw <= 0:
        raise HTTPException(status_code=400, detail="Число тренировок в неделю не настроено")
    active_days = await db.list_active_days(user_id)
    if not active_days:
        raise HTTPException(status_code=400, detail="Активные дни не найдены")
    return wpw, active_days


async def _validate_day(user_id: int, day_index: int) -> tuple[int, list[tuple[int, str]]]:
    wpw, active_days = await _load_user_settings(user_id)
    if not 1 <= day_index <= wpw:
        raise HTTPException(status_code=404, detail="День вне диапазона плана")
    active_map = {d: label for d, label in active_days}
    if day_index not in active_map:
        raise HTTPException(status_code=404, detail="День не активен")
    return wpw, active_days


async def _ensure_user_exercise(user_id: int, ue_id: int, day_index: int) -> None:
    info = await db.get_user_exercise_info(ue_id)
    if not info:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")
    owner_id, ue_day_index = info
    if owner_id != user_id or ue_day_index != day_index:
        raise HTTPException(status_code=404, detail="Упражнение не принадлежит пользователю или дню")


def _serialize_sets(rows: list[tuple]) -> list[dict]:
    return [
        {
            "set_no": int(r[0]),
            "reps": int(r[1]),
            "seconds": int(r[2]),
            "weight_kg": float(r[3]),
            "is_warmup": bool(r[4]),
        }
        for r in rows
    ]


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


@app.get("/day/today")
async def day_today(tg: TelegramInitData = Depends(get_tg_init_data)):
    user_id = tg.user.id
    wpw, active_days = await _load_user_settings(user_id)
    completions = await db.list_day_completions(user_id)
    today = _today_date()
    completed_today = {
        int(d)
        for d, completed_at in completions
        if datetime.fromisoformat(completed_at).date() == today
    }
    suggested = 1
    for d, _ in active_days:
        if d not in completed_today:
            suggested = int(d)
            break

    return {
        "date": _human_date(today),
        "suggested_day_index": suggested,
        "workouts_per_week": wpw,
        "active_days": [{"day_index": int(d), "label": label} for d, label in active_days],
    }


@app.get("/day/{day_index}/sheet")
async def day_sheet(
    day_index: int,
    date: str | None = None,
    tg: TelegramInitData = Depends(get_tg_init_data),
):
    user_id = tg.user.id
    await _validate_day(user_id, day_index)
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index)
    day_label = await db.get_day_label(user_id, day_index)
    exercises_rows = await db.fetch_day_exercises(user_id, day_index, iso_date)
    exercises: list[dict] = []
    for ue_id, name, muscle_group, is_done, exercise_id in exercises_rows:
        sets_rows = await db.fetch_exercise_sets(session_id, ue_id)
        exercises.append(
            {
                "user_exercise_id": int(ue_id),
                "exercise_id": int(exercise_id),
                "name": name,
                "muscle_group": muscle_group,
                "is_done": bool(is_done),
                "sets": _serialize_sets(sets_rows),
            }
        )

    return {
        "date": _human_date(target_date),
        "day_index": day_index,
        "day_label": day_label,
        "session_id": session_id,
        "exercises": exercises,
    }


@app.post("/day/{day_index}/exercise/{user_exercise_id}/set/add")
async def add_set_fast(
    day_index: int,
    user_exercise_id: int,
    payload: dict | None = Body(default=None),
    date: str | None = None,
    tg: TelegramInitData = Depends(get_tg_init_data),
):
    user_id = tg.user.id
    await _validate_day(user_id, day_index)
    await _ensure_user_exercise(user_id, user_exercise_id, day_index)
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index)
    sets_rows = await db.fetch_exercise_sets(session_id, user_exercise_id)
    last = sets_rows[-1] if sets_rows else None
    reps = (payload or {}).get("reps") if payload else None
    seconds = (payload or {}).get("seconds") if payload else None
    weight = (payload or {}).get("weight_kg") if payload else None
    is_warmup = (payload or {}).get("is_warmup") if payload else None
    if reps is None:
        reps = int(last[1]) if last else 0
    if seconds is None:
        seconds = int(last[2]) if last else 0
    if weight is None:
        weight = float(last[3]) if last else 0.0
    warmup_flag = bool(is_warmup if is_warmup is not None else (last[4] if last else False))
    await db.add_set(session_id, user_exercise_id, int(reps), int(seconds), float(weight), warmup_flag)
    new_sets = await db.fetch_exercise_sets(session_id, user_exercise_id)
    return {"ok": True, "sets": _serialize_sets(new_sets)}


@app.post("/day/{day_index}/exercise/{user_exercise_id}/set/remove_last")
async def remove_last_set_fast(
    day_index: int,
    user_exercise_id: int,
    date: str | None = None,
    tg: TelegramInitData = Depends(get_tg_init_data),
):
    user_id = tg.user.id
    await _validate_day(user_id, day_index)
    await _ensure_user_exercise(user_id, user_exercise_id, day_index)
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index)
    await db.remove_last_set(user_exercise_id, session_id)
    new_sets = await db.fetch_exercise_sets(session_id, user_exercise_id)
    return {"ok": True, "sets": _serialize_sets(new_sets)}


@app.post("/day/{day_index}/exercise/{user_exercise_id}/set/inc_last")
async def inc_last_set_fast(
    day_index: int,
    user_exercise_id: int,
    payload: dict = Body(...),
    date: str | None = None,
    tg: TelegramInitData = Depends(get_tg_init_data),
):
    user_id = tg.user.id
    await _validate_day(user_id, day_index)
    await _ensure_user_exercise(user_id, user_exercise_id, day_index)
    field = payload.get("field") if payload else None
    delta = payload.get("delta") if payload else None
    if field not in {"reps", "seconds", "weight_kg"}:
        raise HTTPException(status_code=400, detail="Поле должно быть reps/seconds/weight_kg")
    if delta is None:
        raise HTTPException(status_code=400, detail="Нужно передать delta")
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index)
    await db.inc_last_set(user_exercise_id, session_id, field, float(delta))
    new_sets = await db.fetch_exercise_sets(session_id, user_exercise_id)
    return {"ok": True, "sets": _serialize_sets(new_sets)}
