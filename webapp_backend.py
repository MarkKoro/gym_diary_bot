import os
from dataclasses import dataclass
from datetime import UTC, datetime, date, time, timedelta
from math import sqrt
from typing import Optional
from zoneinfo import ZoneInfo
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
from keyboards import MG_NAMES
from db import (
    clear_day_completions,
    get_user_timezone,
    list_day_completions,
    list_user_reminders,
    mark_exercise_done,
    mark_day_completed,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "webapp")

MUSCLE_CODES = tuple(MG_NAMES.keys())

MUSCLE_NAME_MAP = {
    "chest": "Грудь",
    "back": "Спина",
    "legs": "Ноги",
    "shoulders": "Плечи",
    "core": "Кор / пресс",
    "biceps": "Бицепс",
    "triceps": "Трицепс",
    "cardio": "Кардио",
    "other": "Другое",
    "kb": "Гиря",
    "metcon": "Кроссфит",
    "workout": "Воркаут",
    "run": "Бег",
    "none": "Не указано",
}

MAIN_MUSCLES = ("chest", "back", "legs", "shoulders", "core", "biceps", "triceps", "cardio", "other")
LIBRARY_GROUP_ORDER = (
    "chest",
    "back",
    "legs",
    "shoulders",
    "core",
    "biceps",
    "triceps",
    "kb",
    "metcon",
    "workout",
    "run",
    "other",
    "none",
)
ANATOMY_MUSCLE_CODES = {
    "chest",
    "back",
    "legs",
    "shoulders",
    "core",
    "biceps",
    "triceps",
    "other",
    "cardio",
}

app = FastAPI(title="GymDiary WebApp backend")

MAX_INITDATA_AGE_SEC = 24 * 60 * 60

UNSCHEDULED_COMPLETION_EXPIRY_DAYS = 5
SCHEDULED_COMPLETION_EXPIRY_DAYS = 5

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


@dataclass(frozen=True)
class AuthCtx:
    tg_id: int
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    auth_date: int


async def get_auth_ctx(tg: TelegramInitData = Depends(get_tg_init_data)) -> AuthCtx:
    internal_user_id = await db.get_or_create_user(tg.user.id, tg.user.username)

    return AuthCtx(
        tg_id=tg.user.id,
        user_id=internal_user_id,
        username=tg.user.username,
        first_name=tg.user.first_name,
        last_name=tg.user.last_name,
        auth_date=tg.auth_date,
    )


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


def _calc_base_work(reps: int | float, seconds: int | float, weight: float | None) -> float:
    reps_val = float(reps or 0)
    seconds_val = float(seconds or 0)
    weight_val = float(weight or 0)
    if seconds_val > 0 and (weight_val == 0):
        return seconds_val
    if weight_val > 0 and reps_val > 0:
        return weight_val * reps_val
    return max(reps_val, seconds_val, 0.0)


def resolve_user_zone(tz_name: str | None) -> ZoneInfo:
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def _training_week_start(local_dt: datetime, first_dow: int):
    offset = (local_dt.weekday() - first_dow) % 7
    return local_dt.date() - timedelta(days=offset)


def _parse_completion_rows(rows: list[tuple[int, str | None]]):
    parsed = []
    latest = None
    for day, value in rows:
        if not value:
            continue
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        parsed.append((day, dt))
        if latest is None or dt > latest:
            latest = dt
    return parsed, latest


async def _get_primary_training_weekday(user_id: int) -> int | None:
    reminders = await list_user_reminders(user_id)
    first_configured = None
    for day_no, dow, _, _ in reminders:
        if dow is None:
            continue
        dow_value = int(dow)
        if day_no == 1:
            return dow_value
        if first_configured is None:
            first_configured = dow_value
    return first_configured


async def _should_clear_day_completions(user_id: int, latest: datetime | None) -> bool:
    if latest is None:
        return False
    now = datetime.now(UTC)
    tz_name = await get_user_timezone(user_id)
    zone = resolve_user_zone(tz_name)
    latest_local = latest.astimezone(zone)
    now_local = now.astimezone(zone)

    first_dow = await _get_primary_training_weekday(user_id)
    if first_dow is not None:
        latest_week_start = _training_week_start(latest_local, first_dow)
        current_week_start = _training_week_start(now_local, first_dow)
        if current_week_start > latest_week_start:
            return True
        return False

    expiration_date = latest_local.date() + timedelta(days=UNSCHEDULED_COMPLETION_EXPIRY_DAYS)
    expiration_local = datetime.combine(expiration_date, time(12, tzinfo=zone))
    return now_local >= expiration_local


async def get_active_day_completions(user_id: int) -> set[int]:
    rows = await list_day_completions(user_id)
    parsed, latest = _parse_completion_rows(rows)
    if await _should_clear_day_completions(user_id, latest):
        await clear_day_completions(user_id)
        return set()
    return {day for day, _ in parsed}


async def _load_user_settings(user_id: int):
    settings = await db.fetch_user_settings(user_id)
    if not settings:
        raise HTTPException(
            status_code=400,
            detail="Пожалуйста, открой бота и настрой количество тренировок в неделю, затем вернись в WebApp.",
        )
    system, workouts_per_week = settings
    wpw = int(workouts_per_week) if workouts_per_week is not None else 0
    if wpw <= 0:
        raise HTTPException(
            status_code=400,
            detail="Пожалуйста, открой бота и настрой количество тренировок в неделю, затем вернись в WebApp.",
        )
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


async def _resolve_user_exercise_id(user_id: int, ue_id: int, day_index: int) -> int:
    async with db.connect_db() as conn:
        cur = await conn.execute(
            "SELECT exercise_id FROM user_exercises WHERE id=? AND user_id=? AND day_index=?",
            (ue_id, user_id, day_index),
        )
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")
    return int(row[0])


async def _require_catalog_exercise(exercise_id: int) -> tuple[str, str | None]:
    info = await db.get_exercise_details(exercise_id)
    if not info:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")
    return info


def _compute_muscle_load(
    sets: list[dict],
    mapping: dict[int, list[dict[str, float]]],
    *,
    include_zero_main: bool = False,
):
    muscle_work: dict[str, float] = {}
    muscle_exercises: dict[str, dict[int, float]] = {}
    exercise_names: dict[int, str] = {}

    for item in sets:
        ex_id = int(item.get("exercise_id"))
        ex_name = item.get("exercise_name") or ""
        exercise_names[ex_id] = ex_name
        base = _calc_base_work(item.get("reps", 0), item.get("seconds", 0), item.get("weight_kg"))
        if base <= 0:
            continue
        muscles = mapping.get(ex_id) or []
        for m in muscles:
            code = m.get("muscle_code") or "other"
            pct = float(m.get("weight_pct", 0))
            portion = base * pct / 100.0
            muscle_work[code] = muscle_work.get(code, 0.0) + portion
            muscle_exercises.setdefault(code, {})[ex_id] = muscle_exercises.get(code, {}).get(ex_id, 0.0) + portion

    # add zeros for main muscles
    if include_zero_main:
        for code in MAIN_MUSCLES:
            muscle_work.setdefault(code, 0.0)

    stabilized = {code: sqrt(max(val, 0.0)) for code, val in muscle_work.items()}
    total_stab = sum(stabilized.values())

    muscles = []
    for code, value in stabilized.items():
        percent = (value / total_stab * 100.0) if total_stab > 0 else 0.0
        muscles.append({
            "code": code,
            "name": MUSCLE_NAME_MAP.get(code, code),
            "percent": percent,
        })

    muscles.sort(key=lambda x: x["percent"], reverse=True)

    by_muscle: dict[str, list[dict]] = {}
    for code, ex_values in muscle_exercises.items():
        stabilized_ex = {ex_id: sqrt(max(val, 0.0)) for ex_id, val in ex_values.items()}
        total_in_muscle = sum(stabilized_ex.values())
        parts = []
        for ex_id, val in stabilized_ex.items():
            percent = (val / total_in_muscle * 100.0) if total_in_muscle > 0 else 0.0
            parts.append(
                {
                    "exercise_id": ex_id,
                    "exercise_name": exercise_names.get(ex_id, ""),
                    "percent_in_muscle": percent,
                }
            )
        parts.sort(key=lambda x: x["percent_in_muscle"], reverse=True)
        by_muscle[code] = parts

    return muscles, by_muscle


def _format_prev_summary(data: tuple[int, int, int, float] | None) -> str | None:
    if not data:
        return None
    count, reps, seconds, weight = data
    if seconds and seconds > 0:
        value = f"{int(seconds)} сек"
    else:
        weight_part = f"{weight:g} кг" if weight else None
        if weight_part:
            value = f"{weight_part} × {int(reps)}"
        else:
            value = f"{int(reps)} повт."
    return f"{int(count)}× {value}"


async def _get_previous_done_date(user_id: int, ue_id: int, exclude_session_id: int | None) -> str | None:
    async with db.connect_db() as conn:
        cur = await conn.execute(
            """
            SELECT s.date
            FROM session_exercises se
            JOIN sessions s ON s.id = se.session_id
            WHERE se.user_exercise_id=?
              AND s.user_id=?
              AND se.is_done=1
              AND se.session_id<>?
            ORDER BY s.date DESC, COALESCE(se.done_at, s.date || 'T00:00:00') DESC
            LIMIT 1
            """,
            (ue_id, user_id, exclude_session_id or -1),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return row[0]


def _serialize_sets(rows: list[tuple]) -> list[dict]:
    return [
        {
            "set_no": int(r[0]),
            "reps": int(r[1]),
            "seconds": int(r[2]),
            "weight_kg": float(r[3]),
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
async def whoami(ctx: AuthCtx = Depends(get_auth_ctx)):
    return {
        "ok": True,
        "tg_id": ctx.tg_id,
        "user_id": ctx.user_id,
        "username": ctx.username,
        "first_name": ctx.first_name,
        "last_name": ctx.last_name,
        "auth_date": ctx.auth_date,
    }


@app.get("/day/today")
async def day_today(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    wpw, active_days = await _load_user_settings(user_id)
    completed = await get_active_day_completions(user_id)
    today = _today_date()
    suggested = 1
    for d, _ in active_days:
        if d not in completed:
            suggested = int(d)
            break

    return {
        "date": _human_date(today),
        "suggested_day_index": suggested,
        "workouts_per_week": wpw,
        "active_days": [{"day_index": int(d), "label": label} for d, label in active_days],
        "completed_days": sorted(int(d) for d in completed),
    }


@app.get("/day/{day_index}/sheet")
async def day_sheet(
    day_index: int,
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    completed_days = await get_active_day_completions(user_id)
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
        "is_completed": day_index in completed_days,
        "completed_days": sorted(int(d) for d in completed_days),
    }


@app.get("/catalog/search")
async def search_catalog(query: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    _ = ctx.user_id  # auth only
    rows = await db.search_catalog_exercises(query, limit=50)
    return {
        "ok": True,
        "items": [
            {"id": ex_id, "name": name, "muscle_group": muscle}
            for ex_id, name, muscle in rows
        ],
    }


@app.post("/day/{day_index}/exercise")
async def add_day_exercise(
    day_index: int,
    payload: dict = Body(...),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    ex_id_raw = payload.get("exercise_id") if isinstance(payload, dict) else None
    try:
        ex_id = int(ex_id_raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Некорректный идентификатор упражнения")
    await _require_catalog_exercise(ex_id)
    await db.add_user_exercise(user_id, day_index, ex_id)
    return {"ok": True}


@app.post("/catalog/exercise")
async def create_catalog_exercise(
    payload: dict = Body(...),
    day_index: int | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    name_raw = (payload or {}).get("name") if isinstance(payload, dict) else None
    muscle_raw = (payload or {}).get("muscle_group") if isinstance(payload, dict) else None
    if not name_raw or not str(name_raw).strip():
        raise HTTPException(status_code=400, detail="Название обязательно")
    if day_index is None:
        raise HTTPException(status_code=400, detail="День обязателен")
    await _validate_day(user_id, int(day_index))
    exercise_id = await db.create_catalog_exercise(str(name_raw).strip(), muscle_raw if isinstance(muscle_raw, str) else None)
    await db.add_user_exercise(user_id, int(day_index), exercise_id)
    return {"ok": True, "exercise_id": exercise_id}


@app.post("/day/{day_index}/exercise/{exercise_id}/toggle")
async def toggle_day_exercise(
    day_index: int,
    exercise_id: int,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _require_catalog_exercise(exercise_id)
    enabled = await db.toggle_user_exercise(user_id, day_index, exercise_id)
    return {"ok": True, "enabled": bool(enabled)}


@app.post("/day/{day_index}/complete")
async def complete_day(
    day_index: int,
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    target_date = _parse_date_param(date)
    completed_at = datetime.combine(target_date, time.min, tzinfo=UTC).isoformat()
    await mark_day_completed(user_id, day_index, completed_at)
    completed = await get_active_day_completions(user_id)
    return {
        "ok": True,
        "day_index": day_index,
        "completed_days": sorted(int(d) for d in completed),
    }


@app.post("/day/{day_index}/exercise/{user_exercise_id}/set/add")
async def add_set_fast(
    day_index: int,
    user_exercise_id: int,
    payload: dict | None = Body(default=None),
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
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
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
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
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _ensure_user_exercise(user_id, user_exercise_id, day_index)
    field = payload.get("field") if payload else None
    delta = payload.get("delta") if payload else None
    set_no = payload.get("set_no") if payload else None

    field_map = {"kg": "weight_kg", "reps": "reps", "sec": "seconds"}
    db_field = field_map.get(field)
    if db_field is None:
        raise HTTPException(status_code=400, detail="Поле должно быть reps/sec/kg")
    if delta is None:
        raise HTTPException(status_code=400, detail="Нужно передать delta")

    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index)

    if set_no is not None:
        await db.inc_specific_set(user_exercise_id, session_id, int(set_no), db_field, float(delta))
    else:
        await db.inc_last_set(user_exercise_id, session_id, db_field, float(delta))

    new_sets = await db.fetch_exercise_sets(session_id, user_exercise_id)
    return {"ok": True, "sets": _serialize_sets(new_sets)}


@app.post("/day/{day_index}/exercise/{user_exercise_id}/done")
async def mark_exercise_done_fast(
    day_index: int,
    user_exercise_id: int,
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _ensure_user_exercise(user_id, user_exercise_id, day_index)
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index)
    await mark_exercise_done(session_id, user_exercise_id)

    exercises_rows = await db.fetch_day_exercises(user_id, day_index, iso_date)
    all_done = bool(exercises_rows) and all(bool(row[3]) for row in exercises_rows)

    completed_days = await get_active_day_completions(user_id)
    day_completed = False
    if all_done and day_index not in completed_days:
        await mark_day_completed(user_id, day_index, datetime.now(UTC).isoformat())
        completed_days = await get_active_day_completions(user_id)
        day_completed = True

    return {
        "ok": True,
        "user_exercise_id": user_exercise_id,
        "day_completed": day_completed,
        "completed_days": sorted(int(d) for d in completed_days),
    }


@app.get("/day/{day_index}/exercise/{ue_id}/context")
async def exercise_context(
    day_index: int,
    ue_id: int,
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    exercise_id = await _resolve_user_exercise_id(user_id, ue_id, day_index)
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index)

    current_note = await db.get_exercise_note(session_id, ue_id)
    _prev_note_session_id, previous_note = await db.get_latest_completed_note(
        user_id, exercise_id, exclude_session_id=session_id
    )
    previous_date = await _get_previous_done_date(user_id, ue_id, session_id)
    previous_summary = _format_prev_summary(
        await db.get_last_session_summary(user_id, day_index, ue_id, iso_date)
    )
    previous_sets_rows = await db.fetch_last_session_sets(user_id, day_index, ue_id, iso_date)

    return {
        "ok": True,
        "day_index": day_index,
        "date": iso_date,
        "ue_id": ue_id,
        "exercise_id": exercise_id,
        "current_note": current_note,
        "previous_note": previous_note,
        "previous_date": previous_date,
        "previous_summary": previous_summary,
        "previous_sets": _serialize_sets(previous_sets_rows),
    }


@app.put("/day/{day_index}/exercise/{ue_id}/note")
async def update_exercise_note(
    day_index: int,
    ue_id: int,
    payload: dict = Body(...),
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _resolve_user_exercise_id(user_id, ue_id, day_index)

    note_raw = (payload or {}).get("note", "")
    note_clean = note_raw.strip() if isinstance(note_raw, str) else ""
    note_value = note_clean if note_clean else None

    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index)
    await db.set_exercise_note(session_id, ue_id, note_value)

    return {"ok": True, "current_note": note_value}


@app.get("/muscles")
async def list_muscles(ctx: AuthCtx = Depends(get_auth_ctx)):
    _ = ctx
    muscles = [{"code": code, "name": name} for code, name in MG_NAMES.items()]
    return {"ok": True, "muscles": muscles}


def _sort_groups(items: dict[str, int]):
    def key_fn(code: str):
        try:
            return LIBRARY_GROUP_ORDER.index(code)
        except ValueError:
            return len(LIBRARY_GROUP_ORDER)

    return sorted(items.items(), key=lambda kv: key_fn(kv[0]))


@app.get("/library/groups")
async def list_library_groups(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    counters = await db.list_user_library_groups(user_id)
    groups = []
    for code, count in _sort_groups(counters):
        groups.append({"code": code, "name": MUSCLE_NAME_MAP.get(code, "Не указано"), "count": int(count)})
    return {"ok": True, "groups": groups}


@app.get("/library/group/{code}/exercises")
async def list_group_exercises(
    code: str,
    query: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    normalized_code = (code or "").strip().lower()
    counters = await db.list_user_library_groups(user_id)
    if normalized_code not in counters and normalized_code != "none":
        raise HTTPException(status_code=404, detail="Группа не найдена")

    rows = await db.list_user_group_exercises(user_id, normalized_code, query)
    return {
        "ok": True,
        "items": [
            {
                "id": int(row[0]),
                "name": row[1],
                "muscle_group": row[2],
                "has_override": bool(row[3]),
            }
            for row in rows
        ],
    }


@app.get("/library/group/{code}/anatomy_summaries")
async def list_group_anatomy_summaries(
    code: str,
    query: str | None = None,
    mode: str = "default",
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    normalized_code = (code or "").strip().lower()
    normalized_mode = (mode or "default").strip().lower()

    if normalized_mode not in {"default", "user"}:
        raise HTTPException(status_code=400, detail="Некорректный режим")

    counters = await db.list_user_library_groups(user_id)
    if normalized_code not in counters and normalized_code != "none":
        raise HTTPException(status_code=404, detail="Группа не найдена")

    rows = await db.list_user_group_exercises(user_id, normalized_code, query)
    items: list[dict] = []
    for ex_id, name, muscle_group, has_override in rows:
        source, resolved_items = await _resolve_anatomy(user_id, int(ex_id), muscle_group)
        if normalized_mode == "user" and source != "user":
            continue
        items.append(
            {
                "id": int(ex_id),
                "name": name,
                "has_override": bool(has_override),
                "source": source,
                "summary": _format_anatomy_summary(resolved_items),
            }
        )

    return {"ok": True, "items": items}


@app.get("/library/exercises")
async def list_library_exercises(
    query: str | None = None,
    muscle: str | None = None,
    only_used: int | None = 1,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    if only_used not in (None, 1):
        raise HTTPException(status_code=400, detail="Параметр only_used поддерживает только значение 1")

    user_id = ctx.user_id
    muscle_filter = (muscle or "").strip().lower() or None
    rows = await db.list_user_exercises_for_mapping(user_id, query, muscle_filter)
    return {
        "ok": True,
        "items": [
            {
                "id": int(row[0]),
                "name": row[1],
                "muscle_group": row[2],
                "has_user_anatomy_override": bool(row[3]) if len(row) > 3 else False,
            }
            for row in rows
            if row
        ],
    }


@app.put("/library/exercise/{exercise_id}/muscle")
async def update_exercise_muscle_group(
    exercise_id: int,
    payload: dict = Body(...),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    mg_raw = (payload or {}).get("muscle_group") if isinstance(payload, dict) else None

    if mg_raw is None:
        mg_value: str | None = None
    elif isinstance(mg_raw, str):
        mg_value = mg_raw.strip()
        if mg_value == "":
            mg_value = None
    else:
        raise HTTPException(status_code=400, detail="Некорректная группа")

    if mg_value is not None and mg_value not in MUSCLE_CODES:
        raise HTTPException(status_code=400, detail="Некорректная группа")

    async with db.connect_db() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM user_exercises WHERE user_id=? AND exercise_id=? AND is_archived=0 LIMIT 1",
            (user_id, exercise_id),
        )
        exists_row = await cur.fetchone()
    if not exists_row:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")

    await db.set_exercise_muscle_group(exercise_id, mg_value)
    return {"ok": True, "id": exercise_id, "muscle_group": mg_value}


async def _require_user_exercise(user_id: int, exercise_id: int) -> tuple[str, str | None]:
    async with db.connect_db() as conn:
        cur = await conn.execute(
            """
            SELECT e.name, e.muscle_group
            FROM exercises e
            JOIN user_exercises ue ON ue.exercise_id = e.id
            WHERE ue.user_id=? AND ue.exercise_id=? AND ue.is_archived=0
            LIMIT 1
            """,
            (user_id, exercise_id),
        )
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")
    return row[0], row[1]


def _fallback_anatomy(muscle_group: str | None):
    mg = (muscle_group or "").strip().lower()
    if mg in db.ANATOMICAL_GROUPS:
        return "fallback", [(mg, 100.0)]
    if mg in {"run", "metcon", "cardio"}:
        return "fallback", [("cardio", 100.0)]
    return "fallback", [("other", 100.0)]


async def _resolve_anatomy(user_id: int, exercise_id: int, muscle_group: str | None):
    user_rows = await db.get_user_anatomy(user_id, exercise_id)
    if user_rows:
        return "user", [(row[0], float(row[1])) for row in user_rows]

    default_rows = await db.get_default_anatomy(exercise_id)
    if default_rows:
        return "default", [(row[0], float(row[1])) for row in default_rows]

    return _fallback_anatomy(muscle_group)


def _format_anatomy_items(items):
    return [
        {
            "muscle_code": code,
            "name": MUSCLE_NAME_MAP.get(code, "Другое"),
            "weight_pct": float(pct),
        }
        for code, pct in items
    ]


def _format_anatomy_summary(items):
    sorted_items = sorted(items, key=lambda pair: float(pair[1]), reverse=True)
    return _format_anatomy_items(sorted_items[:4])


@app.get("/library/exercise/{exercise_id}/anatomy")
async def get_exercise_anatomy(
    exercise_id: int,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    name, muscle_group = await _require_user_exercise(user_id, exercise_id)

    source, items = await _resolve_anatomy(user_id, exercise_id, muscle_group)

    return {
        "ok": True,
        "exercise_id": exercise_id,
        "exercise_name": name,
        "source": source,
        "items": _format_anatomy_items(items),
    }


@app.put("/library/exercise/{exercise_id}/anatomy")
async def update_exercise_anatomy(
    exercise_id: int,
    payload: dict = Body(...),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    name, muscle_group = await _require_user_exercise(user_id, exercise_id)

    items = []
    if isinstance(payload, dict):
        items = payload.get("items") or []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="Некорректные данные")
    if not 1 <= len(items) <= 4:
        raise HTTPException(status_code=400, detail="Укажите от 1 до 4 мышц")

    seen_codes: set[str] = set()
    total = 0.0
    normalized_items: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Некорректные данные")
        code = (item.get("muscle_code") or "").strip().lower()
        pct_raw = item.get("weight_pct")
        try:
            pct = float(pct_raw)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Некорректный процент")
        if code not in ANATOMY_MUSCLE_CODES:
            raise HTTPException(status_code=400, detail="Некорректная группа")
        if pct <= 0:
            raise HTTPException(status_code=400, detail="Процент должен быть больше нуля")
        if code in seen_codes:
            raise HTTPException(status_code=400, detail="Дубликаты не допускаются")
        seen_codes.add(code)
        total += pct
        normalized_items.append({"muscle_code": code, "weight_pct": pct})

    if abs(total - 100.0) > 0.5:
        raise HTTPException(status_code=400, detail="Сумма процентов должна быть равна 100")

    await db.set_user_anatomy(user_id, exercise_id, normalized_items)

    return {
        "ok": True,
        "exercise_id": exercise_id,
        "exercise_name": name,
        "source": "user",
        "items": _format_anatomy_items([(i["muscle_code"], i["weight_pct"]) for i in normalized_items]),
    }


@app.delete("/library/exercise/{exercise_id}/anatomy")
async def delete_exercise_anatomy(
    exercise_id: int,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _require_user_exercise(user_id, exercise_id)
    await db.clear_user_anatomy(user_id, exercise_id)
    return {"ok": True}


def _resolve_range(range_code: str | None, end_date: date) -> tuple[str, date]:
    code = (range_code or "30d").lower()
    mapping = {"7d": 6, "30d": 29, "90d": 89}
    if code == "all":
        return "all", date(1970, 1, 1)
    days = mapping.get(code, 29)
    return code if code in mapping else "30d", end_date - timedelta(days=days)


@app.get("/exercise/{exercise_id}/history")
async def exercise_history(
    exercise_id: int,
    range: str | None = None,  # noqa: A002
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    name, _ = await _require_user_exercise(user_id, exercise_id)

    end_date = _today_date()
    normalized_range, start_date = _resolve_range(range, end_date)
    start_iso = None if normalized_range == "all" else _iso_date(start_date)
    end_iso = _iso_date(end_date)

    rows = await db.fetch_exercise_history_points(user_id, exercise_id, start_iso, end_iso)
    timeline: dict[str, dict] = {}
    for session_date, reps, seconds, weight in rows:
        iso_date = session_date
        if iso_date not in timeline:
            timeline[iso_date] = {
                "date": iso_date,
                "top_weight": 0.0,
                "top_reps": 0,
                "top_seconds": 0,
                "volume": 0.0,
                "set_count": 0,
            }
        item = timeline[iso_date]
        reps_val = int(reps or 0)
        sec_val = int(seconds or 0)
        weight_val = float(weight or 0.0)
        if reps_val > 0 and weight_val > 0:
            item["top_weight"] = max(item["top_weight"], weight_val)
            item["volume"] += weight_val * reps_val
        if reps_val > 0:
            item["top_reps"] = max(item["top_reps"], reps_val)
        if sec_val > 0:
            item["top_seconds"] = max(item["top_seconds"], sec_val)
        item["set_count"] += 1

    points = sorted(timeline.values(), key=lambda x: x["date"])
    last_date, last_sets = await db.fetch_last_exercise_session(user_id, exercise_id)
    last_session = None
    if last_date and last_sets:
        last_session = {
            "date": last_date,
            "sets": [
                {
                    "set_no": int(row[0]),
                    "reps": int(row[1]),
                    "seconds": int(row[2]),
                    "weight_kg": float(row[3] or 0.0),
                }
                for row in last_sets
            ],
        }

    return {
        "ok": True,
        "exercise_id": exercise_id,
        "exercise_name": name,
        "range": normalized_range,
        "points": points,
        "last_session": last_session,
    }


@app.get("/body/day/{day_index}")
async def body_day_load(
    day_index: int,
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)

    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index)
    sets = await db.fetch_session_sets_with_exercises(user_id, session_id)
    exercise_ids = [row["exercise_id"] for row in sets]
    mapping = await db.resolve_exercise_muscles(user_id, exercise_ids)
    muscles, by_muscle = _compute_muscle_load(sets, mapping)

    return {
        "ok": True,
        "date": iso_date,
        "day_index": day_index,
        "muscles": [m for m in muscles if m.get("percent", 0) > 0],
        "by_muscle": by_muscle,
    }


@app.get("/body/overall")
async def body_overall(
    range: str | None = None,  # noqa: A002
    end: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    end_date = _parse_date_param(end)
    normalized_range, start_date = _resolve_range(range, end_date)
    start_iso = _iso_date(start_date)
    end_iso = _iso_date(end_date)

    sets = await db.fetch_sets_in_date_range(user_id, start_iso, end_iso)
    exercise_ids = [row["exercise_id"] for row in sets]
    mapping = await db.resolve_exercise_muscles(user_id, exercise_ids)
    muscles, _ = _compute_muscle_load(sets, mapping, include_zero_main=True)

    actual_start = start_iso if normalized_range != "all" else end_iso
    if sets:
        dates = [row.get("session_date") for row in sets if row.get("session_date")]
        if dates:
            actual_start = min(dates)

    return {
        "ok": True,
        "range": normalized_range,
        "start": actual_start,
        "end": end_iso,
        "muscles": muscles,
    }
