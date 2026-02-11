import os
import json
import random
import logging
import httpx
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, date, time, timedelta
from math import sqrt
from typing import Optional
from zoneinfo import ZoneInfo
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from settings import ADMIN_IDS, BOT_PUBLIC_LINK, OPENAI_API_KEY, OPENAI_MODEL, TG_TOKEN, YK_TOKEN
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram_webapp_auth import (
    InitDataError,
    TelegramInitData,
    verify_and_parse_init_data,
)

import db
from keyboards import MG_NAMES
from db import (
    clear_day_completions,
    create_trainer_request,
    deactivate_trainer_links,
    find_user_by_id,
    find_user_by_trainer_code,
    get_running_entry,
    get_day_completion,
    get_user_timezone,
    get_user_notifications_enabled,
    get_user_leaderboard_visible,
    get_active_trainer_link_for_trainee,
    get_latest_trainer_link_for_trainee,
    get_trainer_link,
    get_onboarding_video_message,
    get_onboarding_intro_message,
    add_user_reminder,
    clear_user_reminders,
    list_day_completions,
    list_trainer_requests,
    list_exercise_weight_progress,
    list_running_history,
    list_user_muscle_groups,
    list_user_reminders,
    mark_day_completed,
    mark_exercise_done,
    mark_running_entry_done,
    add_custom_measurement,
    add_measurement_category,
    add_measurement_entry,
    fetch_measurement_history,
    get_measurements_last_update,
    list_custom_measurements,
    list_measurement_categories,
    reactivate_trainer_links,
    remove_user_muscle_group,
    rename_day,
    set_trainer_accepting_requests,
    set_app_meta,
    set_user_notifications_enabled,
    set_user_leaderboard_visible,
    set_user_timezone,
    set_workouts_per_week,
    update_last_measurement,
    update_trainer_label,
    update_trainer_link_permissions,
    update_trainer_link_status,
    update_trainee_label,
    update_running_entry,
    clear_onboarding_video_message,
    clear_onboarding_intro_message,
    is_onboarding_completed,
    set_onboarding_completed,
    fetch_productivity_leaderboard,
    fetch_public_training_plan,
    fetch_public_training_systems,
    fetch_training_system_exercise_sources,
    copy_training_system_from_user,
    ensure_training_system_defaults,
    list_training_systems,
    create_training_system,
    rename_training_system,
    set_training_system_color,
    delete_training_system,
    sync_current_plan_to_system,
    sync_reminders_to_system,
    apply_system_to_current_plan,
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
logger = logging.getLogger(__name__)

MAX_INITDATA_AGE_SEC = 24 * 60 * 60

SYSTEMS_LIMIT_GRACE_DAYS = 7
SUBSCRIPTION_PLANS = {
    '1m': {'title': '1 месяц', 'days': 30, 'amount_rub': 100},
    '6m': {'title': '6 месяцев', 'days': 180, 'amount_rub': 600},
    '12m': {'title': '12 месяцев', 'days': 365, 'amount_rub': 1000},
}


def _subscription_features() -> list[str]:
    return [
        'AI-коуч: анализ прогресса, корректировка подходов, предложения новых упражнений и систем.',
        'Несколько систем тренировок без ограничений.',
        'Приоритетная логика обновления плана без потери истории выполненных тренировок.',
        'Быстрое копирование системы лидеров в отдельную систему.',
    ]


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
    actor_user_id: Optional[int] = None
    acting_can_edit: bool = True
    is_acting: bool = False


async def get_auth_ctx(
    request: Request,
    tg: TelegramInitData = Depends(get_tg_init_data),
    x_acting_user: int | None = Header(default=None, alias="X-Acting-User"),
) -> AuthCtx:
    internal_user_id = await db.get_or_create_user(tg.user.id, tg.user.username)
    actor_user_id = internal_user_id
    acting_user_id = None
    acting_can_edit = True
    is_acting = False
    if x_acting_user and x_acting_user != internal_user_id:
        acting_user_id = int(x_acting_user)
        if request.url.path.startswith("/settings/trainer"):
            acting_user_id = None
        else:
            link = await get_trainer_link(internal_user_id, acting_user_id)
            if not link or str(link[1]) != "accepted":
                raise HTTPException(status_code=403, detail="Trainer link not available")
            acting_can_edit = bool(link[2])
            is_acting = True
            if request.method != "GET" and not acting_can_edit:
                raise HTTPException(status_code=403, detail="No edit permission for trainee")
            internal_user_id = acting_user_id

    await ensure_training_system_defaults(internal_user_id)

    return AuthCtx(
        tg_id=tg.user.id,
        user_id=internal_user_id,
        username=tg.user.username,
        first_name=tg.user.first_name,
        last_name=tg.user.last_name,
        auth_date=tg.auth_date,
        actor_user_id=actor_user_id if is_acting else None,
        acting_can_edit=acting_can_edit,
        is_acting=is_acting,
    )




def _format_num(value: float | int | None) -> str:
    if value is None:
        return '0'
    n = float(value)
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip('0').rstrip('.')


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip_text(text: str, limit: int) -> str:
    src = (text or '').strip()
    if len(src) <= limit:
        return src
    return src[: max(0, limit - 1)].rstrip() + '…'


def _build_user_context_summary(user_profile: dict, active_system_id: int, systems: list[dict], day_snapshots: list[dict], measurement_trends: list[dict]) -> str:
    lines: list[str] = []
    lines.append(f"Профиль: user_id={user_profile.get('user_id')} workouts_per_week={user_profile.get('workouts_per_week', 0)} timezone={user_profile.get('timezone') or 'UTC'}")
    if systems:
        systems_line = ', '.join([f"{it.get('id')}:{it.get('name')}{'*' if int(it.get('id', 0)) == int(active_system_id) else ''}" for it in systems])
        lines.append(f"Системы: {systems_line}")
    else:
        lines.append('Системы: нет')

    lines.append('Текущие тренировки (по дням):')
    if not day_snapshots:
        lines.append('- нет упражнений')
    else:
        for day in day_snapshots:
            header = f"- День {day.get('day_index')}: {day.get('day_label') or f'День {day.get('day_index')}'}"
            lines.append(header)
            for ex in day.get('exercises', [])[:18]:
                lines.append(
                    f"  • {ex.get('name')} [{ex.get('group')}] sets={ex.get('sets')} reps={ex.get('reps')} sec={ex.get('seconds')} weight={_format_num(ex.get('weight_kg'))}kg"
                )

    lines.append('Тренды замеров (последние изменения):')
    if measurement_trends:
        for row in measurement_trends[:10]:
            lines.append(f"- {row.get('metric')}: {row.get('delta_text')} (было {row.get('from')}, стало {row.get('to')})")
    else:
        lines.append('- нет данных')

    return _clip_text('\n'.join(lines), 8200)


async def _build_ai_context_payload(user_id: int) -> dict:
    active_system_id = await get_active_training_system_id(user_id)
    systems = await list_training_systems(user_id)
    settings = await db.fetch_user_settings(user_id)
    timezone = await get_user_timezone(user_id)
    active_days = await db.list_active_days(user_id)

    day_snapshots: list[dict] = []
    today_iso = datetime.now(UTC).strftime('%Y-%m-%d')
    for day_index, day_label in active_days:
        rows = await db.fetch_day_exercises(user_id, int(day_index), today_iso, active_system_id)
        ex_list: list[dict] = []
        for ue_id, ex_name, muscle_group, _is_done, exercise_id in rows:
            baseline = await db.get_baseline(user_id, int(day_index), int(exercise_id))
            sets = _to_int(baseline[0], 0) if baseline else 0
            reps = _to_int(baseline[1], 0) if baseline else 0
            seconds = _to_int(baseline[2], 0) if baseline else 0
            weight_kg = _to_float(baseline[3], 0.0) if baseline else 0.0
            ex_list.append({
                'user_exercise_id': int(ue_id),
                'exercise_id': int(exercise_id),
                'name': ex_name,
                'group': muscle_group or 'other',
                'sets': sets,
                'reps': reps,
                'seconds': seconds,
                'weight_kg': weight_kg,
            })
        day_snapshots.append({
            'day_index': int(day_index),
            'day_label': day_label,
            'exercises': ex_list,
        })

    measurement_codes = ['weight', 'waist', 'chest', 'hips', 'biceps', 'thigh', 'run_5k', 'resting_pulse']
    measurement_trends: list[dict] = []
    for code in measurement_codes:
        hist = await fetch_measurement_history(user_id, code, limit=2)
        if len(hist) < 2:
            continue
        old = _to_float(hist[-1][0], 0.0)
        new = _to_float(hist[0][0], 0.0)
        delta = new - old
        sign = '+' if delta >= 0 else ''
        measurement_trends.append({
            'metric': code,
            'from': _format_num(old),
            'to': _format_num(new),
            'delta': delta,
            'delta_text': f"{sign}{_format_num(delta)}",
        })

    return {
        'user_profile': {
            'user_id': int(user_id),
            'workouts_per_week': int(settings.get('workouts_per_week') or 0),
            'timezone': timezone or 'UTC',
        },
        'active_system_id': int(active_system_id),
        'systems': systems,
        'day_snapshots': day_snapshots,
        'measurement_trends': measurement_trends,
    }


def _build_ai_system_prompt(mode: str) -> str:
    base = (
        'Ты — спортивный ИИ-ассистент внутри фитнес-бота. Анализируй план и прогресс пользователя. '
        'Отвечай по-русски. Сначала дай краткий анализ (3-6 пунктов), затем предложи actionable изменения. '
        'ОБЯЗАТЕЛЬНО заверши ответ JSON-блоком в markdown fenced code block с языком json и ключом action_plan. '
        'JSON должен быть валидным и содержать массив actions. '
        'Разрешённые типы actions: update_sets, replace_exercise, add_exercise, create_system. '
        'Каждый action должен включать day_index и необходимые поля: '
        'для update_sets: exercise_name, sets, reps, seconds, weight_kg; '
        'для replace_exercise: old_exercise_name, new_exercise_name, sets, reps, seconds, weight_kg; '
        'для add_exercise: exercise_name, sets, reps, seconds, weight_kg; '
        'для create_system: system_name и days (массив дней с упражнениями). '
        'Используй только упражнения, которые уже есть в контексте пользователя, кроме случая create_system — там можно предложить новые. '
    )
    mode_guidance = {
        'adjust_sets': 'Сфокусируйся на корректировке объёма/интенсивности без полной смены упражнений.',
        'replace_exercises': 'Сфокусируйся на замене отдельных упражнений с сохранением структуры дня.',
        'new_system': 'Сфокусируйся на создании новой системы целиком на 3-7 дней.',
        'mistakes_analysis': 'Сфокусируйся на ошибках, узких местах и точечных правках.',
        'free_request': 'Сфокусируйся на запросе пользователя и предложи минимум 2 рабочих варианта.',
    }.get(mode, 'Сфокусируйся на практической пользе и безопасности.')
    return base + ' ' + mode_guidance


async def _call_openai_chat(system_prompt: str, user_prompt: str) -> dict:
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail='OPENAI_API_KEY не задан')
    payload = {
        'model': (OPENAI_MODEL or 'gpt-4o-mini'),
        'temperature': 0.6,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
    }
    headers = {
        'Authorization': f'Bearer {OPENAI_API_KEY}',
        'Content-Type': 'application/json',
    }
    async with httpx.AsyncClient(timeout=55.0) as client:
        resp = await client.post('https://api.openai.com/v1/chat/completions', headers=headers, json=payload)
    if resp.status_code >= 400:
        detail = resp.text[:700]
        raise HTTPException(status_code=502, detail=f'OpenAI error: {detail}')
    data = resp.json()
    text = ''
    try:
        text = data['choices'][0]['message']['content'] or ''
    except Exception:
        text = ''
    return {'raw': data, 'text': text}


def _extract_json_block(answer_text: str) -> dict | None:
    src = answer_text or ''
    start = src.find('```json')
    if start == -1:
        return None
    start += len('```json')
    end = src.find('```', start)
    if end == -1:
        return None
    block = src[start:end].strip()
    if not block:
        return None
    try:
        payload = json.loads(block)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload
def _today_date() -> date:
    return datetime.now(UTC).date()


async def get_active_training_system_id(user_id: int) -> int:
    """Возвращает id активной системы тренировок пользователя."""
    return await db.get_active_training_system_id(user_id)


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


ALLOWED_REMINDER_TIMEZONES = {
    "Europe/Kaliningrad",
    "Europe/Moscow",
    "Europe/Samara",
    "Asia/Yekaterinburg",
    "Asia/Omsk",
    "Asia/Krasnoyarsk",
    "Asia/Irkutsk",
    "Asia/Yakutsk",
    "Asia/Vladivostok",
    "Asia/Magadan",
    "Asia/Kamchatka",
    "Europe/Paris",
    "UTC",
    "Atlantic/Azores",
    "America/Noronha",
    "America/Montevideo",
    "America/Barbados",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
}


def normalize_reminder_time(hour: int, minute: int) -> tuple[int, int]:
    hour = max(0, min(23, int(hour)))
    minute = max(0, min(59, int(minute)))
    return hour, minute


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


def _normalize_group(value: str | None) -> str:
    return (value or "").strip().lower()


def _format_duration_value(seconds: int) -> str:
    total = max(int(seconds or 0), 0)
    hours, remainder = divmod(total, 3600)
    minutes, sec = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def _format_pace_value(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = max(int(round(seconds)), 0)
    minutes, sec = divmod(total, 60)
    return f"{minutes}:{sec:02d}"


def _serialize_running_entry(entry: tuple | None) -> dict:
    if not entry:
        return {
            "entry_id": None,
            "distance_km": 0.0,
            "duration_sec": 0,
            "duration_ms": 0,
            "calories": 0,
            "heart_rate": 0,
            "pace_sec": None,
            "pace_text": "—",
            "is_draft": True,
            "created_at": None,
            "day_index": None,
        }
    entry_id, dist, duration, duration_ms, calories, heart_rate, is_draft, created_at = entry
    distance_val = float(dist or 0.0)
    duration_ms_val = int(duration_ms or 0)
    duration_val = int(duration or 0)
    if duration_ms_val <= 0 and duration_val > 0:
        duration_ms_val = duration_val * 1000
    duration_val = max(duration_val, int(round(duration_ms_val / 1000)))
    pace_sec = None
    if distance_val > 0 and duration_ms_val > 0:
        pace_sec = (duration_ms_val / 1000) / distance_val
    return {
        "entry_id": int(entry_id),
        "distance_km": round(distance_val, 3),
        "duration_sec": duration_val,
        "duration_ms": duration_ms_val,
        "calories": int(calories or 0),
        "heart_rate": int(heart_rate or 0),
        "pace_sec": pace_sec,
        "pace_text": _format_pace_value(pace_sec),
        "is_draft": bool(is_draft),
        "created_at": created_at,
        "day_index": None,
    }


def _serialize_running_history_row(row: tuple | None) -> dict | None:
    if not row:
        return None
    entry_id, dist, duration, duration_ms, calories, heart_rate, created_at, day_idx = row
    distance_val = float(dist or 0.0)
    duration_ms_val = int(duration_ms or 0)
    duration_val = int(duration or 0)
    if duration_ms_val <= 0 and duration_val > 0:
        duration_ms_val = duration_val * 1000
    duration_val = max(duration_val, int(round(duration_ms_val / 1000)))
    pace_sec = None
    if distance_val > 0 and duration_ms_val > 0:
        pace_sec = (duration_ms_val / 1000) / distance_val
    return {
        "entry_id": int(entry_id),
        "distance_km": round(distance_val, 3),
        "duration_sec": duration_val,
        "duration_ms": duration_ms_val,
        "calories": int(calories or 0),
        "heart_rate": int(heart_rate or 0),
        "pace_sec": pace_sec,
        "pace_text": _format_pace_value(pace_sec),
        "created_at": created_at,
        "date": (created_at or "").split("T")[0],
        "day_index": int(day_idx) if day_idx is not None else None,
    }


def _clamp_running_distance(value: float | int | str) -> float:
    try:
        return max(round(float(value), 3), 0.0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректная дистанция")


def _clamp_running_duration(value: float | int | str) -> int:
    try:
        return max(int(round(float(value))), 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректное время")


def _clamp_running_duration_ms(value: float | int | str) -> int:
    try:
        return max(int(round(float(value))), 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректное время")


def _clamp_running_calories(value: float | int | str) -> int:
    try:
        return max(int(round(float(value))), 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректные калории")


def _clamp_running_heart_rate(value: float | int | str) -> int:
    try:
        return max(min(int(round(float(value))), 260), 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректный пульс")


async def _build_running_state(
    user_id: int,
    day_index: int,
    ue_id: int,
    target_date: date,
    *,
    exercise_id: int | None = None,
    history_limit: int = 12,
):
    ex_id = exercise_id
    if ex_id is None:
        info = await db.get_exercise_info(ue_id)
        ex_id = int(info[0]) if info else None
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, await get_active_training_system_id(user_id))
    entry = await get_running_entry(
        user_id,
        ue_id,
        session_id=session_id,
        day_index=day_index,
        create=True,
    )
    running_summary = _serialize_running_entry(entry)
    history_rows = await list_running_history(
        user_id,
        ue_id,
        exercise_id=ex_id,
        limit=history_limit,
    )
    history = [_serialize_running_history_row(row) for row in history_rows if row]
    prev_running = None
    if history_rows:
        prev_row = history_rows[0]
        if entry and history_rows[0][0] == entry[0] and len(history_rows) > 1:
            prev_row = history_rows[1]
        prev_running = _serialize_running_history_row(prev_row)
    return {
        "running": running_summary,
        "running_history": history,
        "previous_running": prev_running,
        "session_id": session_id,
    }


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
    active_system_id = await get_active_training_system_id(user_id)
    rows = await list_day_completions(user_id, active_system_id)
    parsed, latest = _parse_completion_rows(rows)
    if await _should_clear_day_completions(user_id, latest):
        await clear_day_completions(user_id, active_system_id)
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
    active_days = await db.list_active_days(user_id)
    if not active_days:
        raise HTTPException(status_code=400, detail="Активные дни не найдены")
    wpw = int(workouts_per_week) if workouts_per_week is not None else len(active_days)
    if wpw <= 0:
        wpw = len(active_days)
    return wpw, active_days


async def _validate_day(user_id: int, day_index: int) -> tuple[int, list[tuple[int, str]]]:
    wpw, active_days = await _load_user_settings(user_id)
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

@app.head("/health")
def health_head():
    return Response(status_code=200)


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
        "is_admin": int(ctx.tg_id) in ADMIN_IDS,
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
    active_system_id = await get_active_training_system_id(user_id)
    last_completed_at = await db.get_day_completion(user_id, day_index, active_system_id)
    last_completed_volume_kg = await db.get_day_completion_volume_kg(
        user_id,
        day_index,
        active_system_id,
        completed_at=last_completed_at,
    )
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, active_system_id)
    day_label = await db.get_day_label(user_id, day_index)
    exercises_rows = await db.fetch_day_exercises(user_id, day_index, iso_date, active_system_id)
    exercise_sources = await fetch_training_system_exercise_sources(active_system_id, day_index)
    exercises: list[dict] = []
    for ue_id, name, muscle_group, is_done, exercise_id in exercises_rows:
        normalized_group = _normalize_group(muscle_group)
        exercise_payload: dict[str, object] = {
            "user_exercise_id": int(ue_id),
            "exercise_id": int(exercise_id),
            "name": name,
            "muscle_group": muscle_group,
            "is_done": bool(is_done),
        }
        source_meta = exercise_sources.get(int(exercise_id), {}) if exercise_sources else {}
        if source_meta:
            exercise_payload["source_meta"] = {
                "source_user_id": int(source_meta.get("source_user_id") or 0),
                "source_system_id": int(source_meta.get("source_system_id") or 0),
                "source_exercise_id": int(source_meta.get("source_exercise_id") or 0),
                "source_exercise_name": (source_meta.get("source_exercise_name") or name or "").strip(),
                "sets_count": int(source_meta.get("sets_count") or 0),
                "reps": int(source_meta.get("reps") or 0),
                "weight_kg": float(source_meta.get("weight_kg") or 0.0),
            }
        if normalized_group == "run":
            running_state = await _build_running_state(
                user_id,
                day_index,
                ue_id,
                target_date,
                exercise_id=int(exercise_id),
                history_limit=20,
            )
            exercise_payload.update(
                {
                    "running": running_state.get("running"),
                    "running_history": running_state.get("running_history"),
                    "previous_running": running_state.get("previous_running"),
                    "session_id": running_state.get("session_id"),
                    "sets": [],
                }
            )
        else:
            sets_rows = await db.fetch_exercise_sets(session_id, ue_id)
            exercise_payload["sets"] = _serialize_sets(sets_rows)
        exercises.append(exercise_payload)

    return {
        "date": _human_date(target_date),
        "day_index": day_index,
        "day_label": day_label,
        "session_id": session_id,
        "exercises": exercises,
        "is_completed": day_index in completed_days,
        "completed_days": sorted(int(d) for d in completed_days),
        "last_completed_at": last_completed_at,
        "last_completed_volume_kg": int(last_completed_volume_kg or 0),
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


@app.get("/catalog/groups")
async def list_catalog_groups(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    custom = await db.list_user_muscle_groups(user_id)
    groups = [
        {"code": code, "name": name, "is_custom": False}
        for code, name in MG_NAMES.items()
    ]
    groups.extend(
        {"code": code, "name": name, "is_custom": True}
        for code, name in custom
    )
    return {"ok": True, "groups": groups}


@app.get("/catalog/group/{code}")
async def list_catalog_group_exercises(
    code: str,
    day_index: int | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    normalized_code = (code or "").strip().lower()
    if not normalized_code:
        raise HTTPException(status_code=400, detail="Группа не указана")
    if day_index is not None:
        await _validate_day(user_id, int(day_index))
    rows = await db.list_exercises_by_group(normalized_code)
    added = set()
    if day_index is not None:
        added = set(await db.list_user_exercise_ids(user_id, int(day_index), normalized_code))
    return {
        "ok": True,
        "items": [
            {
                "id": int(ex_id),
                "name": name,
                "muscle_group": normalized_code,
                "is_added": int(ex_id) in added,
            }
            for ex_id, name in rows
        ],
    }


@app.post("/catalog/group")
async def create_catalog_group(
    payload: dict = Body(...),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    name_raw = (payload or {}).get("name") if isinstance(payload, dict) else None
    if not name_raw or not str(name_raw).strip():
        raise HTTPException(status_code=400, detail="Название обязательно")
    code = await db.add_user_muscle_group(user_id, str(name_raw).strip())
    return {"ok": True, "code": code, "name": str(name_raw).strip()}


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
    await sync_current_plan_to_system(user_id, await get_active_training_system_id(user_id))
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
    active_system_id = await get_active_training_system_id(user_id)
    await mark_day_completed(user_id, day_index, completed_at, active_system_id)
    completed = await get_active_day_completions(user_id)
    last_completed_at = await db.get_day_completion(user_id, day_index, active_system_id)
    last_completed_volume_kg = await db.get_day_completion_volume_kg(
        user_id,
        day_index,
        active_system_id,
        completed_at=last_completed_at,
    )
    return {
        "ok": True,
        "day_index": day_index,
        "completed_days": sorted(int(d) for d in completed),
        "last_completed_at": last_completed_at,
        "last_completed_volume_kg": int(last_completed_volume_kg or 0),
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
    active_system_id = await get_active_training_system_id(user_id)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, active_system_id)
    sets_rows = await db.fetch_exercise_sets(session_id, user_exercise_id)
    last = sets_rows[-1] if sets_rows else None
    if not last:
        latest_any = await db.get_latest_set_values_for_exercise(
            user_id,
            user_exercise_id,
            exclude_session_id=session_id,
        )
        if latest_any:
            last = (0, int(latest_any[0]), int(latest_any[1]), float(latest_any[2]), 0)
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
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, await get_active_training_system_id(user_id))
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
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, await get_active_training_system_id(user_id))

    if set_no is not None:
        await db.inc_specific_set(user_exercise_id, session_id, int(set_no), db_field, float(delta))
    else:
        await db.inc_last_set(user_exercise_id, session_id, db_field, float(delta))

    new_sets = await db.fetch_exercise_sets(session_id, user_exercise_id)
    return {"ok": True, "sets": _serialize_sets(new_sets)}


@app.get("/day/{day_index}/exercise/{ue_id}/running")
async def get_running_state(
    day_index: int,
    ue_id: int,
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _ensure_user_exercise(user_id, ue_id, day_index)
    target_date = _parse_date_param(date)
    state = await _build_running_state(user_id, day_index, ue_id, target_date, history_limit=30)
    return {"ok": True, **state}


@app.post("/day/{day_index}/exercise/{ue_id}/running")
async def update_running_state(
    day_index: int,
    ue_id: int,
    payload: dict = Body(...),
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _ensure_user_exercise(user_id, ue_id, day_index)
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, await get_active_training_system_id(user_id))
    entry = await get_running_entry(
        user_id,
        ue_id,
        session_id=session_id,
        day_index=day_index,
        create=True,
    )
    entry_id = entry[0]
    distance_raw = payload.get("distance_km") if isinstance(payload, dict) else None
    duration_sec_raw = payload.get("duration_sec") if isinstance(payload, dict) else None
    duration_ms_raw = payload.get("duration_ms") if isinstance(payload, dict) else None
    calories_raw = payload.get("calories") if isinstance(payload, dict) else None
    heart_rate_raw = payload.get("heart_rate") if isinstance(payload, dict) else None

    distance_val = _clamp_running_distance(distance_raw if distance_raw is not None else entry[1])
    base_duration_ms = entry[3] if len(entry) > 3 else 0
    if not base_duration_ms and entry[2]:
        base_duration_ms = int(entry[2]) * 1000
    if duration_ms_raw is not None:
        duration_ms_val = _clamp_running_duration_ms(duration_ms_raw)
    elif duration_sec_raw is not None:
        duration_ms_val = _clamp_running_duration_ms(float(duration_sec_raw) * 1000)
    else:
        duration_ms_val = base_duration_ms
    duration_sec_val = max(int(round(duration_ms_val / 1000)), 0)
    calories_val = _clamp_running_calories(calories_raw if calories_raw is not None else entry[4])
    heart_rate_val = _clamp_running_heart_rate(heart_rate_raw if heart_rate_raw is not None else entry[5])

    await update_running_entry(
        entry_id,
        distance_km=distance_val,
        duration_sec=duration_sec_val,
        duration_ms=duration_ms_val,
        calories=calories_val,
        heart_rate=heart_rate_val,
        is_draft=1,
    )
    state = await _build_running_state(user_id, day_index, ue_id, target_date, history_limit=30)
    return {"ok": True, **state}


@app.post("/day/{day_index}/exercise/{ue_id}/running/done")
async def complete_running_state(
    day_index: int,
    ue_id: int,
    payload: dict = Body(default={}),
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _ensure_user_exercise(user_id, ue_id, day_index)
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, await get_active_training_system_id(user_id))
    entry = await get_running_entry(
        user_id,
        ue_id,
        session_id=session_id,
        day_index=day_index,
        create=True,
    )
    entry_id = entry[0]
    distance_raw = payload.get("distance_km") if isinstance(payload, dict) else None
    duration_sec_raw = payload.get("duration_sec") if isinstance(payload, dict) else None
    duration_ms_raw = payload.get("duration_ms") if isinstance(payload, dict) else None
    calories_raw = payload.get("calories") if isinstance(payload, dict) else None
    heart_rate_raw = payload.get("heart_rate") if isinstance(payload, dict) else None

    distance_val = _clamp_running_distance(distance_raw if distance_raw is not None else entry[1])
    base_duration_ms = entry[3] if len(entry) > 3 else 0
    if not base_duration_ms and entry[2]:
        base_duration_ms = int(entry[2]) * 1000
    if duration_ms_raw is not None:
        duration_ms_val = _clamp_running_duration_ms(duration_ms_raw)
    elif duration_sec_raw is not None:
        duration_ms_val = _clamp_running_duration_ms(float(duration_sec_raw) * 1000)
    else:
        duration_ms_val = base_duration_ms
    duration_sec_val = max(int(round(duration_ms_val / 1000)), 0)
    calories_val = _clamp_running_calories(calories_raw if calories_raw is not None else entry[4])
    heart_rate_val = _clamp_running_heart_rate(heart_rate_raw if heart_rate_raw is not None else entry[5])

    await update_running_entry(
        entry_id,
        distance_km=distance_val,
        duration_sec=duration_sec_val,
        duration_ms=duration_ms_val,
        calories=calories_val,
        heart_rate=heart_rate_val,
        is_draft=1,
    )
    if distance_val <= 0 or duration_ms_val <= 0:
        raise HTTPException(status_code=400, detail='Добавь дистанцию и время перед сохранением.')
    await mark_running_entry_done(entry_id)
    if session_id:
        await mark_exercise_done(session_id, ue_id)
    active_system_id = await get_active_training_system_id(user_id)
    exercises_rows = await db.fetch_day_exercises(user_id, day_index, iso_date, active_system_id)
    all_done = bool(exercises_rows) and all(bool(row[3]) for row in exercises_rows)
    completed_days = await get_active_day_completions(user_id)
    day_completed = False
    if all_done and day_index not in completed_days:
        await mark_day_completed(user_id, day_index, datetime.now(UTC).isoformat(), active_system_id)
        completed_days = await get_active_day_completions(user_id)
        day_completed = True
    last_completed_at = await db.get_day_completion(user_id, day_index, active_system_id)
    last_completed_volume_kg = await db.get_day_completion_volume_kg(
        user_id,
        day_index,
        active_system_id,
        completed_at=last_completed_at,
    )
    state = await _build_running_state(user_id, day_index, ue_id, target_date, history_limit=30)
    return {
        "ok": True,
        **state,
        "day_completed": day_completed,
        "completed_days": sorted(int(d) for d in completed_days),
        "last_completed_at": last_completed_at,
        "last_completed_volume_kg": int(last_completed_volume_kg or 0),
    }


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
    active_system_id = await get_active_training_system_id(user_id)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, active_system_id)

    sets_rows = await db.fetch_exercise_sets(session_id, user_exercise_id)
    work_sets = [row for row in (sets_rows or []) if int(row[4] or 0) == 0]
    if not work_sets:
        defaults = await db.get_session_last_values(session_id, user_exercise_id)
        if defaults is None:
            defaults = await db.get_latest_set_values_for_exercise(
                user_id,
                user_exercise_id,
                exclude_session_id=session_id,
            )
        reps_v = int(defaults[0]) if defaults else 0
        sec_v = int(defaults[1]) if defaults else 0
        weight_v = float(defaults[2]) if defaults else 0.0
        if reps_v > 0 or sec_v > 0 or weight_v > 0:
            await db.add_set(
                session_id,
                user_exercise_id,
                reps=max(reps_v, 0),
                seconds=max(sec_v, 0),
                weight=max(weight_v, 0.0),
                is_warmup=False,
            )

    await mark_exercise_done(session_id, user_exercise_id)

    exercises_rows = await db.fetch_day_exercises(user_id, day_index, iso_date, active_system_id)
    all_done = bool(exercises_rows) and all(bool(row[3]) for row in exercises_rows)

    completed_days = await get_active_day_completions(user_id)
    day_completed = False
    if all_done and day_index not in completed_days:
        await mark_day_completed(user_id, day_index, datetime.now(UTC).isoformat(), active_system_id)
        completed_days = await get_active_day_completions(user_id)
        day_completed = True

    last_completed_at = await db.get_day_completion(user_id, day_index, active_system_id)
    last_completed_volume_kg = await db.get_day_completion_volume_kg(
        user_id,
        day_index,
        active_system_id,
        completed_at=last_completed_at,
    )
    return {
        "ok": True,
        "user_exercise_id": user_exercise_id,
        "day_completed": day_completed,
        "completed_days": sorted(int(d) for d in completed_days),
        "last_completed_at": last_completed_at,
        "last_completed_volume_kg": int(last_completed_volume_kg or 0),
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
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, await get_active_training_system_id(user_id))

    current_note = await db.get_exercise_note(session_id, ue_id)
    _prev_note_session_id, previous_note = await db.get_latest_completed_note(
        user_id, exercise_id, exclude_session_id=session_id
    )
    previous_date = await _get_previous_done_date(user_id, ue_id, session_id)
    previous_summary = _format_prev_summary(
        await db.get_last_session_summary(user_id, day_index, ue_id, iso_date, await get_active_training_system_id(user_id))
    )
    previous_sets_rows = await db.fetch_last_session_sets(user_id, day_index, ue_id, iso_date, await get_active_training_system_id(user_id))

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
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, await get_active_training_system_id(user_id))
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
    custom_groups = await list_user_muscle_groups(user_id)
    custom_map = {code: name for code, name in custom_groups}
    groups = []
    for code, count in _sort_groups(counters):
        groups.append(
            {
                "code": code,
                "name": custom_map.get(code, MUSCLE_NAME_MAP.get(code, "Не указано")),
                "count": int(count),
            }
        )
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
    name, muscle_group = await _require_user_exercise(user_id, exercise_id)

    end_date = _today_date()
    normalized_range, start_date = _resolve_range(range, end_date)
    start_iso = None if normalized_range == "all" else _iso_date(start_date)
    end_iso = _iso_date(end_date)

    normalized_group = _normalize_group(muscle_group)
    is_running = normalized_group == "run"

    if is_running:
        history_rows = await db.list_running_history(
            user_id,
            exercise_id=exercise_id,
            start_date=start_iso,
            end_date=end_iso,
            limit=500,
            offset=0,
        )
        entries = [_serialize_running_history_row(row) for row in history_rows if row]
        return {
            "ok": True,
            "exercise_id": exercise_id,
            "exercise_name": name,
            "range": normalized_range,
            "is_running": True,
            "running_entries": entries,
        }

    rows = await db.fetch_exercise_history_points(user_id, exercise_id, start_iso, end_iso)
    timeline: dict[str, dict] = {}
    sessions: dict[str, dict] = {}
    for session_date, set_no, reps, seconds, weight in rows:
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
        if iso_date not in sessions:
            sessions[iso_date] = {"date": iso_date, "sets": []}
        item = timeline[iso_date]
        reps_val = int(reps or 0)
        sec_val = int(seconds or 0)
        weight_val = float(weight or 0.0)
        sessions[iso_date]["sets"].append(
            {
                "set_no": int(set_no or 0),
                "reps": reps_val,
                "seconds": sec_val,
                "weight_kg": weight_val,
            }
        )
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
        "sessions": sorted(sessions.values(), key=lambda x: x["date"]),
        "last_session": last_session,
        "is_running": False,
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

    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, await get_active_training_system_id(user_id))
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


@app.get("/measurements/overview")
async def measurements_overview(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    custom_items = await load_custom_measurements(user_id)
    user_categories = [
        {"code": code, "letter": (letter or "").upper(), "name": name}
        for code, letter, name in await list_measurement_categories(user_id)
    ]
    categories = measurement_categories_list(
        user_categories,
        include_custom_fallback=True,
        custom_items=custom_items,
    )
    custom_by_category: dict[str, list[dict]] = {}
    for item in custom_items:
        custom_by_category.setdefault(item["category"], []).append(item)
    items_map = {**MEASUREMENT_MAP, **{item["code"]: item for item in custom_items}}
    cache: dict[str, list[tuple[float, str | None, str]]] = {}
    rendered_categories: list[dict] = []
    for category in categories:
        code = category["code"]
        base_items = [item for item in MEASUREMENT_ITEMS if item["category"] == code]
        items = list(base_items)
        items.extend(custom_by_category.get(code, []))
        if not items:
            continue
        category_items: list[dict] = []
        for item in items:
            history = await get_measurement_history(user_id, item["code"], cache, items_map, limit=2)
            latest_entry = history[0] if history else None
            previous_entry = history[1] if len(history) > 1 else None
            display_value = format_measurement_value(item, latest_entry) if latest_entry else "—"
            delta = None
            if latest_entry and previous_entry:
                delta = format_measurement_delta(item, latest_entry, previous_entry)
            category_items.append(
                {
                    "code": item["code"],
                    "name": item["name"],
                    "unit": item.get("unit", ""),
                    "precision": item.get("precision", 1),
                    "optional": item.get("optional", False),
                    "type": item.get("type"),
                    "note": item.get("note"),
                    "derived": item.get("derived"),
                    "prompt": item.get("prompt"),
                    "latest": {
                        "value": latest_entry[0],
                        "extra": latest_entry[1],
                        "created_at": latest_entry[2],
                        "display": display_value,
                    }
                    if latest_entry
                    else None,
                    "delta": delta,
                }
            )
        rendered_categories.append(
            {
                "code": code,
                "name": category["name"],
                "letter": category.get("letter"),
                "items": category_items,
            }
        )
    last_update = await get_measurements_last_update(user_id)
    return {
        "ok": True,
        "last_update": last_update,
        "categories": rendered_categories,
    }


@app.get("/measurements/history/{code}")
async def measurements_history(
    code: str,
    limit: int = 10,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    custom_items = await load_custom_measurements(user_id)
    items_map = {**MEASUREMENT_MAP, **{item["code"]: item for item in custom_items}}
    item = items_map.get(code)
    if not item:
        raise HTTPException(status_code=404, detail="Measurement not found")
    cache: dict[str, list[tuple[float, str | None, str]]] = {}
    history = await get_measurement_history(user_id, code, cache, items_map, limit=limit)
    timezone = await get_user_timezone(user_id)
    tz = ZoneInfo(timezone or "UTC")
    entries = []
    for idx, entry in enumerate(history):
        prev = history[idx + 1] if idx + 1 < len(history) else None
        entries.append(
            {
                "value": entry[0],
                "extra": entry[1],
                "created_at": entry[2],
                "date_label": format_measurement_date(entry[2], tz),
                "display": format_measurement_value(item, entry),
                "delta": format_measurement_delta(item, entry, prev) if prev else None,
            }
        )
    return {
        "ok": True,
        "item": {
            "code": item["code"],
            "name": item["name"],
            "unit": item.get("unit", ""),
            "type": item.get("type"),
            "precision": item.get("precision", 1),
            "note": item.get("note"),
            "prompt": item.get("prompt"),
        },
        "entries": entries,
    }


@app.post("/measurements/entry")
async def measurements_add_entry(
    payload: dict = Body(default={}),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    metric = (payload.get("metric") or "").strip()
    value_text = (payload.get("value") or payload.get("text") or "").strip()
    if not metric or not value_text:
        raise HTTPException(status_code=400, detail="Metric/value required")
    custom_items = await load_custom_measurements(user_id)
    items_map = {**MEASUREMENT_MAP, **{item["code"]: item for item in custom_items}}
    item = items_map.get(metric)
    if not item or item.get("derived"):
        raise HTTPException(status_code=404, detail="Measurement not found")
    try:
        value, extra = parse_measurement_input(item, value_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    overwrite = bool(payload.get("overwrite"))
    if overwrite:
        updated = await update_last_measurement(user_id, metric, value, extra)
        if not updated:
            await add_measurement_entry(user_id, metric, value, extra)
    else:
        await add_measurement_entry(user_id, metric, value, extra)
    return {"ok": True}


@app.post("/measurements/custom")
async def measurements_add_custom(
    payload: dict = Body(default={}),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    category_code = (payload.get("category_code") or "").strip() or None
    code = await add_custom_measurement(user_id, name, category_code)
    return {
        "ok": True,
        "code": code,
        "name": name,
        "category_code": category_code or MEASUREMENT_CUSTOM_CATEGORY["code"],
    }


@app.post("/measurements/category")
async def measurements_add_category(
    payload: dict = Body(default={}),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    name = (payload.get("name") or "").strip()
    letter = (payload.get("letter") or "").strip().upper()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    if not letter:
        letter = name[:1].upper()
    if not letter:
        raise HTTPException(status_code=400, detail="Letter required")
    code = await add_measurement_category(user_id, letter[:1], name)
    return {"ok": True, "code": code, "letter": letter[:1], "name": name}


FEATURED_MEASUREMENTS_ORDER = ["body_weight", "body_fat", "chest", "hips"]
FEATURED_MEASUREMENTS_MAP = {
    "body_weight": {"name": "Вес", "unit": "кг", "precision": 1},
    "body_fat": {"name": "Жир", "unit": "%", "precision": 1},
    "chest": {"name": "Грудь", "unit": "см", "precision": 1},
    "hips": {"name": "Бёдра", "unit": "см", "precision": 1},
}
SHARE_RESULTS_EXERCISE_LIMIT = 5
SHARE_RESULTS_WINDOW_DAYS = 90
SHARE_RESULTS_COPY_TEXT_MAX_LENGTH = 4096


MEASUREMENT_CUSTOM_CATEGORY = {
    "code": "custom",
    "letter": "E",
    "name": "Свои замеры",
}

MEASUREMENT_CATEGORIES = [
    {"code": "body", "letter": "A", "name": "Масса/состав тела"},
    {"code": "circumference", "letter": "B", "name": "Окружности"},
    {"code": "records", "letter": "C", "name": "Производные/силовые контрольные"},
    {"code": "vitals", "letter": "D", "name": "Витальные показатели"},
]


def _measurement_item(
    code: str,
    name: str,
    category: str,
    unit: str,
    precision: int = 1,
    optional: bool = False,
    prompt: str | None = None,
    derived: str | None = None,
    note: str | None = None,
    item_type: str | None = None,
):
    if prompt is None:
        lower = name.lower()
        if unit == "см":
            prompt = f"Введи обхват {lower} в сантиметрах (например: 32.5)."
        elif unit == "кг":
            prompt = f"Введи значение в килограммах (например: 50.0)."
        elif unit == "%":
            prompt = f"Введи значение в процентах (например: 15.0)."
        elif unit == "повт.":
            prompt = f"Укажи количество повторений (например: 12)."
        elif unit == "уд/мин":
            prompt = f"Введи значение в ударах в минуту (например: 60)."
        elif unit == "ч":
            prompt = f"Укажи количество часов (например: 7.5)."
        else:
            prompt = "Введи значение (например: 10)."
    item = {
        "code": code,
        "name": name,
        "category": category,
        "unit": unit,
        "precision": precision,
        "optional": optional,
        "prompt": prompt,
    }
    if derived:
        item["derived"] = derived
    if note:
        item["note"] = note
    if item_type:
        item["type"] = item_type
    return item


MEASUREMENT_ITEMS = [
    _measurement_item(
        "body_weight",
        "Вес тела",
        "body",
        "кг",
        prompt="Введи вес в килограммах (например: 72.5).",
    ),
    _measurement_item(
        "body_fat",
        "Процент жира",
        "body",
        "%",
        prompt="Введи процент жира (например: 15.8).",
    ),
    _measurement_item(
        "lean_mass",
        "Безжировая масса",
        "body",
        "кг",
        derived="lean_mass",
        note="нужны вес и % жира",
    ),
    _measurement_item(
        "water_pct",
        "Вода",
        "body",
        "%",
        optional=True,
        prompt="Введи процент воды (например: 52.3).",
    ),
    _measurement_item(
        "bmi",
        "ИМТ",
        "body",
        "",
        optional=True,
        prompt="Введи индекс массы тела (например: 22.4).",
    ),
    _measurement_item("neck", "Шея", "circumference", "см"),
    _measurement_item("shoulders", "Плечи", "circumference", "см"),
    _measurement_item("chest", "Грудь", "circumference", "см"),
    _measurement_item(
        "underbust",
        "Под грудью",
        "circumference",
        "см",
        optional=True,
    ),
    _measurement_item("waist_narrow", "Талия (узкая)", "circumference", "см"),
    _measurement_item("waist_navel", "Талия (пупок)", "circumference", "см"),
    _measurement_item(
        "abdomen",
        "Живот",
        "circumference",
        "см",
        optional=True,
    ),
    _measurement_item("hips", "Бёдра/таз", "circumference", "см"),
    _measurement_item("thigh_upper", "Бедро верхнее", "circumference", "см"),
    _measurement_item(
        "thigh_mid",
        "Бедро среднее",
        "circumference",
        "см",
        optional=True,
    ),
    _measurement_item("hamstring", "Бицепс бедра", "circumference", "см"),
    _measurement_item("calf", "Икроножная", "circumference", "см"),
    _measurement_item("ankle", "Лодыжка", "circumference", "см", optional=True),
    _measurement_item(
        "bicep_relaxed",
        "Бицепс (расслабл.)",
        "circumference",
        "см",
    ),
    _measurement_item(
        "bicep_flexed",
        "Бицепс (напряж.)",
        "circumference",
        "см",
    ),
    _measurement_item("forearm", "Предплечье", "circumference", "см"),
    _measurement_item("wrist", "Запястье", "circumference", "см", optional=True),
    _measurement_item(
        "bench_1rm",
        "1RM Жим лёжа",
        "records",
        "кг",
        optional=True,
        prompt="Введи одноповторный максимум в жиме лёжа (например: 95).",
    ),
    _measurement_item(
        "squat_1rm",
        "1RM Присед",
        "records",
        "кг",
        optional=True,
        prompt="Введи одноповторный максимум в приседе (например: 130).",
    ),
    _measurement_item(
        "deadlift_1rm",
        "1RM Становая",
        "records",
        "кг",
        optional=True,
        prompt="Введи одноповторный максимум в становой тяге (например: 160).",
    ),
    _measurement_item(
        "pullups_max",
        "Подтягивания",
        "records",
        "повт.",
        optional=True,
        prompt="Укажи максимум подтягиваний (например: 12).",
    ),
    _measurement_item(
        "pushups_2min",
        "Отжимания за 2 мин",
        "records",
        "повт.",
        optional=True,
        prompt="Укажи количество отжиманий за 2 минуты (например: 45).",
    ),
    _measurement_item(
        "wod_time_sec",
        "Время WOD (сек)",
        "records",
        "",
        prompt="Укажи время WOD в формате ММ:СС или ЧЧ:ММ:СС.",
        item_type="duration",
    ),
    _measurement_item(
        "resting_hr",
        "Пульс в покое",
        "vitals",
        "уд/мин",
        prompt="Введи пульс в покое (например: 60).",
    ),
    _measurement_item(
        "blood_pressure",
        "Артериальное давление",
        "vitals",
        "мм рт. ст.",
        precision=0,
        prompt="Введи давление в формате 120/80.",
        item_type="blood_pressure",
    ),
    _measurement_item(
        "sleep_hours",
        "Сон",
        "vitals",
        "ч",
        prompt="Укажи продолжительность сна в часах (например: 7.5).",
    ),
]

MEASUREMENT_MAP = {item["code"]: item for item in MEASUREMENT_ITEMS}


def parse_duration_input(text: str) -> int:
    raw = text.strip()
    if not raw or any(ch not in "0123456789:" for ch in raw):
        raise ValueError("invalid characters")
    parts = raw.split(":")
    if len(parts) not in (2, 3):
        raise ValueError("invalid format")
    try:
        values = [int(part) for part in parts]
    except ValueError as exc:
        raise ValueError("invalid number") from exc
    if any(val < 0 for val in values):
        raise ValueError("negative value")
    if len(values) == 2:
        minutes, seconds = values
        if seconds >= 60:
            raise ValueError("seconds range")
        return minutes * 60 + seconds
    hours, minutes, seconds = values
    if minutes >= 60 or seconds >= 60:
        raise ValueError("time range")
    return hours * 3600 + minutes * 60 + seconds


def format_duration_value(seconds: int) -> str:
    seconds = max(int(round(seconds)), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, sec = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    total_minutes = seconds // 60
    return f"{total_minutes}:{sec:02d}"


def format_duration_delta(delta_seconds: int) -> str:
    sign = "+" if delta_seconds >= 0 else "-"
    formatted = format_duration_value(abs(delta_seconds))
    return f"{sign}{formatted}"


def format_measurement_value(item: dict, entry: tuple[float, str | None, str]) -> str:
    value, extra, _ = entry
    if value is None:
        return "—"
    if item.get("type") == "duration":
        seconds = int(round(value))
        unit = item.get("unit", "")
        return f"{format_duration_value(seconds)} {unit}".strip()
    if item.get("type") == "blood_pressure":
        diast = 0.0
        if extra:
            try:
                diast = float(extra)
            except (TypeError, ValueError):
                diast = 0.0
        value_text = f"{value:.0f}/{diast:.0f}" if extra else f"{value:.0f}"
        unit = item.get("unit", "")
        return f"{value_text} {unit}".strip()
    precision = max(int(item.get("precision", 1)), 0)
    fmt = f"{{:.{precision}f}}" if precision > 0 else "{:.0f}"
    value_text = fmt.format(value)
    unit = item.get("unit", "")
    return f"{value_text} {unit}".strip()


def format_measurement_delta(
    item: dict,
    current: tuple[float, str | None, str],
    previous: tuple[float, str | None, str],
) -> str:
    if item.get("type") == "blood_pressure":
        syst = current[0] - previous[0]
        try:
            cur_extra = float(current[1]) if current[1] is not None else 0.0
        except (TypeError, ValueError):
            cur_extra = 0.0
        try:
            prev_extra = float(previous[1]) if previous[1] is not None else 0.0
        except (TypeError, ValueError):
            prev_extra = 0.0
        diast = cur_extra - prev_extra
        unit = item.get("unit", "")
        return f"Δ {syst:+.0f}/{diast:+.0f} {unit}".strip()
    if item.get("type") == "duration":
        diff = current[0] - previous[0]
        diff_seconds = int(round(diff))
        return f"Δ {format_duration_delta(diff_seconds)}"
    diff = current[0] - previous[0]
    precision = max(int(item.get("precision", 1)), 0)
    fmt = f"{{:+.{precision}f}}" if precision > 0 else "{:+.0f}"
    unit = item.get("unit", "")
    return f"Δ {fmt.format(diff)} {unit}".strip()


def format_measurement_date(value: str, tz: ZoneInfo) -> str:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt = dt.astimezone(tz)
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return value.split("T")[0]


def parse_measurement_input(item: dict, text: str) -> tuple[float, str | None]:
    raw = text.strip()
    if not raw:
        raise ValueError("empty")
    if item.get("type") == "duration":
        seconds = parse_duration_input(raw)
        return float(seconds), ""
    raw = raw.replace(",", ".")
    if item.get("type") == "blood_pressure":
        parts = raw.replace("/", " ").split()
        if len(parts) != 2:
            raise ValueError("bp format")
        syst = int(round(float(parts[0])))
        diast = int(round(float(parts[1])))
        return float(syst), str(diast)
    value = float(raw)
    return value, None


def compute_lean_mass_history(
    weight_history: list[tuple[float, str | None, str]],
    fat_history: list[tuple[float, str | None, str]],
) -> list[tuple[float, None, str]]:
    if not weight_history or not fat_history:
        return []
    result: list[tuple[float, None, str]] = []
    for (w_val, _, w_ts), (f_val, _, f_ts) in zip(weight_history, fat_history):
        if w_val is None or f_val is None:
            continue
        ts = w_ts if w_ts >= f_ts else f_ts
        result.append((w_val * (1 - f_val / 100.0), None, ts))
    return result


async def load_custom_measurements(user_id: int) -> list[dict]:
    rows = await list_custom_measurements(user_id)
    items: list[dict] = []
    for code, name, category_code in rows:
        category = (category_code or "").strip() or MEASUREMENT_CUSTOM_CATEGORY["code"]
        items.append(
            {
                "code": code,
                "name": name,
                "category": category,
                "unit": "",
                "precision": 1,
                "optional": False,
                "prompt": f"Введи значение для «{name}» (например: 10).",
            }
        )
    return items


def measurement_categories_list(
    user_categories: list[dict],
    *,
    include_custom_fallback: bool,
    custom_items: list[dict],
) -> list[dict]:
    categories: list[dict] = []
    categories.extend(MEASUREMENT_CATEGORIES)
    categories.extend(user_categories)
    custom_codes = {category.get("code") for category in user_categories}
    if include_custom_fallback and custom_items and MEASUREMENT_CUSTOM_CATEGORY["code"] not in custom_codes:
        categories.append(MEASUREMENT_CUSTOM_CATEGORY)
    return categories


async def get_measurement_history(
    user_id: int,
    code: str,
    cache: dict[str, list[tuple[float, str | None, str]]],
    items_map: dict[str, dict],
    limit: int = 5,
) -> list[tuple[float, str | None, str]]:
    cache_key = f"{code}:{limit}"
    if cache_key in cache:
        return cache[cache_key]
    item = items_map.get(code)
    if not item:
        cache[cache_key] = []
        return []
    if item.get("derived") == "lean_mass":
        weight_history = await get_measurement_history(user_id, "body_weight", cache, items_map, limit)
        fat_history = await get_measurement_history(user_id, "body_fat", cache, items_map, limit)
        history = compute_lean_mass_history(weight_history, fat_history)[:limit]
    else:
        rows = await fetch_measurement_history(user_id, code, limit=limit)
        history = rows or []
    cache[cache_key] = history
    return history


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        if text.endswith("Z"):
            try:
                dt = datetime.fromisoformat(text[:-1] + "+00:00")
            except ValueError:
                dt = None
        else:
            try:
                base = text.split(".")[0]
                dt = datetime.fromisoformat(base)
            except ValueError:
                try:
                    dt = datetime.strptime(text.split("T")[0], "%Y-%m-%d")
                except ValueError:
                    dt = None
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _plural_ru(value: int, forms: tuple[str, str, str]) -> str:
    num = abs(value) % 100
    if 10 <= num <= 20:
        return forms[2]
    num %= 10
    if num == 1:
        return forms[0]
    if 2 <= num <= 4:
        return forms[1]
    return forms[2]


def _calculate_training_weeks(first: datetime | None, last: datetime | None) -> int:
    if first is None or last is None:
        return 1
    if last < first:
        first, last = last, first
    span_days = max(0, (last.date() - first.date()).days)
    if span_days <= 0:
        return 1
    weeks = round(span_days / 7)
    return max(1, weeks)


def _format_weight_value(value: float) -> str:
    text = f"{value:.1f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if not text:
        return "0"
    return text


def _format_share_measurement_line(item: dict, delta: float) -> str:
    precision = int(item.get("precision", 1) or 1)
    formatted = f"{delta:+.{precision}f}"
    unit = (item.get("unit") or "").strip()
    unit_part = f" {unit}" if unit else ""
    name = item.get("short_name") or item.get("name") or item.get("code") or ""
    return f"{name}: {formatted}{unit_part}".strip()


def _get_public_link() -> str:
    link = (BOT_PUBLIC_LINK or "").strip()
    if link:
        return link
    return "https://t.me/progresor_bot"


def _select_share_exercises(items: list[dict], *, randomize: bool = False) -> list[dict]:
    if not items:
        return []
    limit = min(SHARE_RESULTS_EXERCISE_LIMIT, len(items))
    if randomize and len(items) > limit:
        selected = random.sample(items, k=limit)
    else:
        selected = items[:limit]
    return sorted(selected, key=lambda entry: entry["delta"], reverse=True)


def _copy_text_length(text: str) -> int:
    return len(text.encode("utf-8"))


def _truncate_with_ellipsis(text: str, max_length_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_length_bytes:
        return text
    if max_length_bytes <= 0:
        return ""
    ellipsis = "…"
    ellipsis_bytes = ellipsis.encode("utf-8")
    if max_length_bytes <= len(ellipsis_bytes):
        truncated = encoded[:max_length_bytes]
        return truncated.decode("utf-8", "ignore")
    trimmed_bytes = encoded[: max_length_bytes - len(ellipsis_bytes)]
    trimmed_text = trimmed_bytes.decode("utf-8", "ignore").rstrip()
    if not trimmed_text:
        return trimmed_bytes.decode("utf-8", "ignore")
    candidate = f"{trimmed_text}{ellipsis}"
    if len(candidate.encode("utf-8")) <= max_length_bytes:
        return candidate
    return trimmed_text


def _render_share_results_copy_text(
    header: str, measurements: list[str], exercises: list[dict], link: str
) -> str:
    lines: list[str] = [header]
    body_lines: list[str] = []
    if measurements:
        body_lines.append("Вот мои результаты:")
        body_lines.append("Изменения в теле:")
        body_lines.extend(measurements)
    if exercises:
        if not body_lines:
            body_lines.append("Вот мои результаты:")
        body_lines.append("Силовой прогресс за последние три месяца:")
        for progress in exercises:
            delta_text = _format_weight_value(progress["delta"])
            start_text = _format_weight_value(progress["start_weight"])
            end_text = _format_weight_value(progress["end_weight"])
            body_lines.append(
                "• {name}: +{delta} кг (с {start} до {end} кг)".format(
                    name=progress["name"],
                    delta=delta_text,
                    start=start_text,
                    end=end_text,
                )
            )
    if body_lines:
        lines.append("")
        lines.extend(body_lines)
    lines.append("")
    call_to_action = (
        "Это мой результат. Если ты хочешь так же прогрессировать со мной, то "
        f"Подключайся 👉 {link}"
    )
    lines.append(call_to_action)

    def _join(parts: list[str]) -> str:
        return "\n".join(parts)

    text = _join(lines)
    if _copy_text_length(text) <= SHARE_RESULTS_COPY_TEXT_MAX_LENGTH:
        return text

    header_line = lines[0]
    tail_lines = lines[-2:]
    middle_lines = lines[1:-2]

    trimmed_middle = list(middle_lines)
    while trimmed_middle and _copy_text_length(
        _join([header_line, *trimmed_middle, *tail_lines])
    ) > SHARE_RESULTS_COPY_TEXT_MAX_LENGTH:
        trimmed_middle.pop()
    candidate = _join([header_line, *trimmed_middle, *tail_lines])
    if _copy_text_length(candidate) <= SHARE_RESULTS_COPY_TEXT_MAX_LENGTH:
        return candidate

    trimmed_middle = [line for line in trimmed_middle if line.strip()]
    candidate = _join([header_line, *trimmed_middle, *tail_lines])
    if _copy_text_length(candidate) <= SHARE_RESULTS_COPY_TEXT_MAX_LENGTH:
        return candidate

    fallback_lines: list[str] = []
    if header_line:
        fallback_lines.append(header_line)
        fallback_lines.append("")
    fallback_lines.append(call_to_action)
    candidate = _join(fallback_lines)
    if _copy_text_length(candidate) <= SHARE_RESULTS_COPY_TEXT_MAX_LENGTH:
        return candidate

    if header_line:
        suffix = f"\n\n{call_to_action}"
        available = SHARE_RESULTS_COPY_TEXT_MAX_LENGTH - _copy_text_length(suffix)
        if available > 0:
            shortened_header = _truncate_with_ellipsis(header_line, available)
            shortened_header = shortened_header.strip()
            if shortened_header:
                candidate = f"{shortened_header}{suffix}"
                if _copy_text_length(candidate) <= SHARE_RESULTS_COPY_TEXT_MAX_LENGTH:
                    return candidate

    return _truncate_with_ellipsis(call_to_action, SHARE_RESULTS_COPY_TEXT_MAX_LENGTH)


def _render_share_results_text(
    header: str, measurements: list[str], exercises: list[dict], link: str
) -> str:
    lines: list[str] = [header]
    body_lines: list[str] = []
    if measurements:
        body_lines.append("Вот мои результаты:")
        body_lines.append("Изменения в теле:")
        body_lines.extend(measurements)
    if exercises:
        if not body_lines:
            body_lines.append("Вот мои результаты:")
        body_lines.append("Силовой прогресс за последние три месяца:")
        for progress in exercises:
            delta_text = _format_weight_value(progress["delta"])
            start_text = _format_weight_value(progress["start_weight"])
            end_text = _format_weight_value(progress["end_weight"])
            body_lines.append(
                "• {name}: +{delta} кг (с {start} до {end} кг)".format(
                    name=progress["name"],
                    delta=delta_text,
                    start=start_text,
                    end=end_text,
                )
            )
    if body_lines:
        lines.append("")
        lines.extend(body_lines)
    lines.append("")
    lines.append(
        "Это мой результат. Если ты хочешь так же прогрессировать со мной, то "
        f"Подключайся 👉 {link}."
    )
    return "\n".join(lines)


async def _load_training_summary(user_id: int) -> tuple[int, datetime | None, datetime | None]:
    async with db.connect_db() as conn:
        cur = await conn.execute(
            """
            SELECT COUNT(*), MIN(date), MAX(date)
            FROM sessions
            WHERE user_id=? AND day_index>0
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return 0, None, None
    count = int(row[0] or 0)
    first = _parse_iso_datetime(row[1])
    last = _parse_iso_datetime(row[2])
    return count, first, last


async def _load_featured_measurement_changes(
    user_id: int,
) -> list[tuple[str, float, dict]]:
    entries: list[tuple[str, float, dict]] = []
    async with db.connect_db() as conn:
        for metric in FEATURED_MEASUREMENTS_ORDER:
            cur = await conn.execute(
                """
                SELECT value, created_at
                FROM user_measurements
                WHERE user_id=? AND metric=?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (user_id, metric),
            )
            first_row = await cur.fetchone()
            cur = await conn.execute(
                """
                SELECT value, created_at
                FROM user_measurements
                WHERE user_id=? AND metric=?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, metric),
            )
            last_row = await cur.fetchone()
            if not first_row or not last_row:
                continue
            try:
                first_value = float(first_row[0])
                last_value = float(last_row[0])
            except (TypeError, ValueError):
                continue
            delta = last_value - first_value
            if abs(delta) <= 0:
                continue
            item = FEATURED_MEASUREMENTS_MAP.get(metric, {"name": metric, "unit": "", "precision": 1})
            precision = int(item.get("precision", 1) or 1)
            threshold = 0.5 * 10 ** (-precision)
            if abs(delta) < threshold:
                continue
            entries.append((metric, delta, item))
    entries.sort(key=lambda entry: abs(entry[1]), reverse=True)
    return entries[:4]


async def build_share_results_view(user_id: int, *, randomize: bool = False) -> dict:
    trainings_count, first, last = await _load_training_summary(user_id)
    measurement_entries = await _load_featured_measurement_changes(user_id)
    link = _get_public_link()
    measurements = [
        _format_share_measurement_line(item, delta)
        for _metric, delta, item in measurement_entries
    ]
    progress_entries = await list_exercise_weight_progress(
        user_id, days=SHARE_RESULTS_WINDOW_DAYS
    )
    exercises = [
        {
            "name": str(entry.get("name") or "").strip(),
            "start_weight": float(entry.get("start_weight", 0.0) or 0.0),
            "end_weight": float(entry.get("end_weight", 0.0) or 0.0),
            "delta": float(entry.get("delta", 0.0) or 0.0),
        }
        for entry in progress_entries
        if entry.get("name")
    ]
    exercises = [
        entry
        for entry in exercises
        if entry["delta"] > 0 and entry["end_weight"] > entry["start_weight"]
    ]
    exercises.sort(key=lambda item: item["delta"], reverse=True)
    displayed = _select_share_exercises(exercises, randomize=randomize)

    has_training_data = trainings_count > 0 and first is not None and last is not None
    if not has_training_data and not measurements and not displayed:
        fallback_text = "\n".join(
            [
                "Я только начинаю тренироваться с этим ботом 💪",
                "Скоро здесь будет мой прогресс.",
                "",
                f"Если хочешь начать вместе со мной, то Подключайся 👉 {link}",
            ]
        )
        return {
            "text": fallback_text,
            "copy_text": fallback_text,
            "exercises": displayed,
            "measurements": measurements,
        }

    weeks = _calculate_training_weeks(first, last)
    week_label = _plural_ru(weeks, ("неделю", "недели", "недель"))
    training_label = _plural_ru(
        trainings_count, ("тренировку", "тренировки", "тренировок")
    )
    header = (
        f"Я тренируюсь с ботом уже {weeks} {week_label} "
        f"({trainings_count} {training_label}) 💪"
    )
    text = _render_share_results_text(header, measurements, displayed, link)
    copy_text = _render_share_results_copy_text(header, measurements, displayed, link)
    return {
        "text": text,
        "copy_text": copy_text,
        "exercises": displayed,
        "measurements": measurements,
    }


async def _fetch_trainer_profile(user_id: int) -> dict:
    async with db.connect_db() as conn:
        cur = await conn.execute(
            """
            SELECT is_trainer, trainer_code, trainer_accepts_requests
            FROM users
            WHERE id=?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return {"is_trainer": False, "trainer_code": None, "accepts_requests": True}
    is_trainer = bool(int(row[0] or 0))
    accepts = True
    try:
        accepts = bool(int(row[2] or 0))
    except (TypeError, ValueError):
        accepts = True
    return {
        "is_trainer": is_trainer,
        "trainer_code": row[1],
        "accepts_requests": accepts,
    }


async def _ensure_trainer_mode(user_id: int) -> str | None:
    async with db.connect_db() as conn:
        code = await db._ensure_user_trainer_code(conn, user_id)
        await conn.execute(
            """
            UPDATE users
            SET is_trainer=1, trainer_accepts_requests=1
            WHERE id=?
            """,
            (user_id,),
        )
        await conn.commit()
    return code


async def _user_display_name(user_id: int) -> str:
    record = await find_user_by_id(user_id)
    username = record[2] if record else None
    if username:
        return f"@{username}"
    return f"ID {user_id}"


async def _get_trainer_link_by_id(link_id: int):
    async with db.connect_db() as conn:
        cur = await conn.execute(
            """
            SELECT id, trainer_user_id, trainee_user_id, status, can_edit_plan, trainer_label, trainee_label
            FROM trainer_links
            WHERE id=?
            """,
            (link_id,),
        )
        return await cur.fetchone()


@app.get("/settings/overview")
async def settings_overview(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    wpw, active_days = await _load_user_settings(user_id)
    custom_groups = await list_user_muscle_groups(user_id)
    reminders = await list_user_reminders(user_id)
    notifications_enabled = await get_user_notifications_enabled(user_id)
    leaderboard_visible = await get_user_leaderboard_visible(user_id)
    timezone = await get_user_timezone(user_id)
    return {
        "ok": True,
        "workouts_per_week": wpw,
        "days": [{"day_index": int(d), "label": label} for d, label in active_days],
        "custom_groups": [{"code": code, "name": name} for code, name in custom_groups],
        "reminders": [
            {"day_no": int(day_no), "dow": int(dow), "hour": int(hour), "minute": int(minute)}
            for day_no, dow, hour, minute in reminders
        ],
        "notifications_enabled": bool(notifications_enabled),
        "leaderboard_visible": bool(leaderboard_visible),
        "timezone": timezone,
    }


async def _has_onboarding_activity(user_id: int) -> bool:
    async with db.connect_db() as conn:
        checks = (
            "SELECT 1 FROM sessions WHERE user_id=? LIMIT 1",
            "SELECT 1 FROM user_exercises WHERE user_id=? AND COALESCE(is_archived,0)=0 LIMIT 1",
            "SELECT 1 FROM day_completions WHERE user_id=? LIMIT 1",
        )
        for query in checks:
            cur = await conn.execute(query, (user_id,))
            row = await cur.fetchone()
            if row:
                return True
    return False


async def _resolve_onboarding_completed(user_id: int, workouts_per_week: int) -> bool:
    completed = await is_onboarding_completed(user_id)
    if completed:
        return True
    if workouts_per_week <= 0:
        return False
    return await _has_onboarding_activity(user_id)


@app.get("/onboarding/status")
async def onboarding_status(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    settings = await db.fetch_user_settings(user_id)
    workouts_per_week = 0
    if settings and settings[1] is not None:
        try:
            workouts_per_week = int(settings[1])
        except (TypeError, ValueError):
            workouts_per_week = 0
    reminders = await list_user_reminders(user_id)
    notifications_enabled = await get_user_notifications_enabled(user_id)
    leaderboard_visible = await get_user_leaderboard_visible(user_id)
    timezone = await get_user_timezone(user_id)
    active_days: list[tuple[int, str]] = []
    if workouts_per_week > 0:
        active_days = await db.list_active_days(user_id)
    onboarding_completed = await _resolve_onboarding_completed(user_id, workouts_per_week)
    return {
        "ok": True,
        "workouts_per_week": workouts_per_week,
        "days": [{"day_index": int(d), "label": label} for d, label in active_days],
        "reminders": [
            {"day_no": int(day_no), "dow": int(dow), "hour": int(hour), "minute": int(minute)}
            for day_no, dow, hour, minute in reminders
        ],
        "notifications_enabled": bool(notifications_enabled),
        "leaderboard_visible": bool(leaderboard_visible),
        "timezone": timezone,
        "onboarding_completed": onboarding_completed,
    }


@app.post("/onboarding/finish")
async def onboarding_finish(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    await set_onboarding_completed(user_id, True)
    bot = Bot(TG_TOKEN)

    chat_id, message_id = await get_onboarding_video_message(user_id)
    if chat_id and message_id:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=message_id, reply_markup=None
            )
        except Exception as exc:
            logger.warning(
                "Failed to remove onboarding video keyboard for user %s: %s",
                user_id,
                exc,
            )
    await clear_onboarding_video_message(user_id)

    intro_chat_id, intro_message_id = await get_onboarding_intro_message(user_id)
    if intro_chat_id and intro_message_id:
        try:
            await bot.delete_message(chat_id=intro_chat_id, message_id=intro_message_id)
        except Exception as exc:
            logger.warning(
                "Failed to remove onboarding intro message for user %s: %s",
                user_id,
                exc,
            )
    await clear_onboarding_intro_message(user_id)

    sent = False
    menu_chat_id = chat_id or intro_chat_id
    if menu_chat_id:
        try:
            await bot.send_message(
                chat_id=menu_chat_id,
                text="✅ Онбординг завершён. Открываю главное меню.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Открыть главное меню", callback_data="menu:root")]]
                ),
            )
            sent = True
        except Exception as exc:
            logger.warning("Failed to send main menu prompt for user %s: %s", user_id, exc)
    return {"ok": True, "sent": sent}


@app.post("/settings/days/{day_index}/rename")
async def settings_rename_day(
    day_index: int,
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    label = str(payload.get("label") or "").strip()
    if not label:
        label = f"День {day_index}"
    await rename_day(user_id, day_index, label)
    await sync_current_plan_to_system(user_id, await get_active_training_system_id(user_id))
    wpw, active_days = await _load_user_settings(user_id)
    return {
        "ok": True,
        "workouts_per_week": wpw,
        "days": [{"day_index": int(d), "label": lbl} for d, lbl in active_days],
    }


@app.post("/settings/workouts_per_week")
async def settings_workouts_per_week(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    try:
        value = int(payload.get("value") or 0)
    except (TypeError, ValueError):
        value = 0
    value = max(1, min(7, value))
    await set_workouts_per_week(user_id, value)
    wpw, active_days = await _load_user_settings(user_id)
    return {
        "ok": True,
        "workouts_per_week": wpw,
        "days": [{"day_index": int(d), "label": lbl} for d, lbl in active_days],
    }


@app.delete("/settings/custom_groups/{code}")
async def settings_custom_group_delete(
    code: str,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    removed = await remove_user_muscle_group(user_id, code)
    return {"ok": True, "removed": removed}


@app.post("/settings/reminders")
async def settings_update_reminders(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    enabled = payload.get("enabled", True)
    await set_user_notifications_enabled(user_id, bool(enabled))
    timezone = str(payload.get("timezone") or "").strip()
    if timezone and timezone not in ALLOWED_REMINDER_TIMEZONES:
        timezone = "UTC"
    if not timezone:
        timezone = "UTC"
    await set_user_timezone(user_id, timezone)
    reminders = payload.get("reminders") or []
    await clear_user_reminders(user_id)
    for reminder in reminders:
        if not isinstance(reminder, dict):
            continue
        try:
            day_no = int(reminder.get("day_no", 0))
            dow = int(reminder.get("dow", 0))
            hour = int(reminder.get("hour", 0))
            minute = int(reminder.get("minute", 0))
        except (TypeError, ValueError):
            continue
        if day_no <= 0:
            continue
        if not 0 <= dow <= 6:
            continue
        hour, minute = normalize_reminder_time(hour, minute)
        await add_user_reminder(user_id, dow, hour, minute, day_no=day_no)
    await set_app_meta("reminders_updated_at", datetime.now(UTC).isoformat())
    await sync_reminders_to_system(user_id, await get_active_training_system_id(user_id))
    return {"ok": True}


@app.post("/settings/leaderboard_visibility")
async def settings_leaderboard_visibility(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    visible = payload.get("visible", True)
    await set_user_leaderboard_visible(user_id, bool(visible))
    return {"ok": True, "leaderboard_visible": bool(visible)}


@app.post("/settings/clear_completions")
async def settings_clear_completions(
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await clear_day_completions(user_id)
    return {"ok": True}


@app.get("/settings/share")
async def settings_share_results(
    randomize: int | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    view = await build_share_results_view(user_id, randomize=bool(randomize))
    return {"ok": True, **view}


@app.get("/settings/trainer")
async def settings_trainer_overview(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    profile = await _fetch_trainer_profile(user_id)
    link = await get_latest_trainer_link_for_trainee(user_id)
    link_payload = None
    if link:
        link_id, trainer_user_id, status, can_edit_plan, trainer_label, _ = link
        display_name = (trainer_label or "").strip() or await _user_display_name(trainer_user_id)
        link_payload = {
            "link_id": int(link_id),
            "trainer_user_id": int(trainer_user_id),
            "status": str(status),
            "can_edit_plan": bool(can_edit_plan),
            "display_name": display_name,
        }

    requests_payload = []
    trainees_payload = []
    if profile["is_trainer"]:
        requests = await list_trainer_requests(user_id, limit=50, offset=0)
        for link_id, trainee_user_id, _status, _created_at in requests:
            display_name = await _user_display_name(int(trainee_user_id))
            requests_payload.append(
                {
                    "link_id": int(link_id),
                    "trainee_user_id": int(trainee_user_id),
                    "display_name": display_name,
                }
            )
        async with db.connect_db() as conn:
            cur = await conn.execute(
                """
                SELECT id, trainee_user_id, trainee_label, can_edit_plan, created_at
                FROM trainer_links
                WHERE trainer_user_id = ? AND status = 'accepted'
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (user_id,),
            )
            trainees = await cur.fetchall()
        for link_id, trainee_user_id, trainee_label, can_edit_plan, _created_at in trainees:
            label = str(trainee_label or "").strip()
            display_name = label or await _user_display_name(int(trainee_user_id))
            trainees_payload.append(
                {
                    "link_id": int(link_id),
                    "trainee_user_id": int(trainee_user_id),
                    "display_name": display_name,
                    "can_edit_plan": bool(can_edit_plan),
                }
            )

    return {
        "ok": True,
        "is_trainer": profile["is_trainer"],
        "trainer_code": profile["trainer_code"],
        "accepts_requests": profile["accepts_requests"],
        "link": link_payload,
        "requests": requests_payload,
        "trainees": trainees_payload,
    }


@app.post("/settings/trainer/toggle")
async def settings_trainer_toggle(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    enabled = bool(payload.get("enabled"))
    if enabled:
        await _ensure_trainer_mode(user_id)
        await reactivate_trainer_links(user_id)
    else:
        async with db.connect_db() as conn:
            await conn.execute("UPDATE users SET is_trainer=0 WHERE id=?", (user_id,))
            await conn.execute(
                "UPDATE users SET trainer_accepts_requests=0 WHERE id=?", (user_id,)
            )
            await conn.commit()
        await deactivate_trainer_links(user_id)
    return {"ok": True}


@app.post("/settings/trainer/requests")
async def settings_trainer_requests(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    enabled = bool(payload.get("enabled"))
    await set_trainer_accepting_requests(user_id, enabled)
    return {"ok": True}


@app.post("/settings/trainer/request/{link_id}/{decision}")
async def settings_trainer_request_decision(
    link_id: int,
    decision: str,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    link = await _get_trainer_link_by_id(link_id)
    if not link or int(link[1]) != user_id:
        raise HTTPException(status_code=404, detail="Request not found")
    status = str(link[3] or "")
    if status != "pending":
        raise HTTPException(status_code=400, detail="Request already processed")
    if decision == "accept":
        await update_trainer_link_status(int(link[0]), "accepted")
    elif decision == "decline":
        await update_trainer_link_status(int(link[0]), "declined")
    else:
        raise HTTPException(status_code=400, detail="Unsupported decision")
    return {"ok": True}


@app.post("/settings/trainer/link")
async def settings_trainer_link(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    trainer = await find_user_by_trainer_code(code)
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    trainer_id, _username, accepts_requests = trainer
    if int(trainer_id) == user_id:
        raise HTTPException(status_code=400, detail="Нельзя использовать свой код")
    if not accepts_requests:
        raise HTTPException(status_code=400, detail="Trainer is not accepting requests")
    existing = await get_latest_trainer_link_for_trainee(user_id)
    if existing and str(existing[2]) in {"pending", "accepted"}:
        raise HTTPException(status_code=400, detail="Link already exists")
    await create_trainer_request(int(trainer_id), user_id, can_edit_plan=False)
    return {"ok": True}


@app.post("/settings/trainer/detach")
async def settings_trainer_detach(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    link = await get_active_trainer_link_for_trainee(user_id)
    if not link:
        return {"ok": True, "removed": False}
    await update_trainer_link_status(int(link[0]), "removed")
    return {"ok": True, "removed": True}


@app.post("/settings/trainer/allow_edit")
async def settings_trainer_allow_edit(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    enabled = bool(payload.get("enabled"))
    link = await get_active_trainer_link_for_trainee(user_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    await update_trainer_link_permissions(int(link[0]), 1 if enabled else 0)
    return {"ok": True}


@app.post("/settings/trainer/label")
async def settings_trainer_label(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    link = await get_active_trainer_link_for_trainee(user_id)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    label = str(payload.get("label") or "").strip() or None
    await update_trainer_label(int(link[0]), label)
    return {"ok": True}


@app.post("/settings/trainer/trainee/{link_id}/label")
async def settings_trainer_trainee_label(
    link_id: int,
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    link = await _get_trainer_link_by_id(link_id)
    if not link or int(link[1]) != user_id:
        raise HTTPException(status_code=404, detail="Link not found")
    label = str(payload.get("label") or "").strip() or None
    await update_trainee_label(int(link_id), label)
    return {"ok": True}


@app.post("/settings/trainer/trainee/{trainee_user_id}/detach")
async def settings_trainer_trainee_detach(
    trainee_user_id: int,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    link = await get_trainer_link(user_id, int(trainee_user_id))
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    await update_trainer_link_status(int(link[0]), "removed")
    return {"ok": True}



async def _has_active_subscription(user_id: int) -> bool:
    return bool(await db.get_active_subscription(user_id))


async def _enforce_system_limit_if_needed(user_id: int) -> dict:
    has_sub = await _has_active_subscription(user_id)
    systems = await list_training_systems(user_id)
    if has_sub or len(systems) <= 1:
        await db.set_systems_limit_prompted_at(user_id, None)
        return {
            'requires_resolution': False,
            'auto_pruned': False,
            'first_prompt_at': None,
            'grace_deadline': None,
            'systems': systems,
        }

    now = datetime.now(UTC)
    first_prompt_at = await db.get_systems_limit_prompted_at(user_id)
    if first_prompt_at is None:
        first_prompt_at = now
        await db.set_systems_limit_prompted_at(user_id, first_prompt_at)

    deadline = first_prompt_at + timedelta(days=SYSTEMS_LIMIT_GRACE_DAYS)
    if now >= deadline:
        keep_system_id = int(sorted(systems, key=lambda x: int(x.get('id') or 0))[0]['id'])
        await db.prune_user_training_systems(user_id, keep_system_id)
        systems = await list_training_systems(user_id)
        return {
            'requires_resolution': False,
            'auto_pruned': True,
            'first_prompt_at': first_prompt_at.isoformat(),
            'grace_deadline': deadline.isoformat(),
            'systems': systems,
        }

    return {
        'requires_resolution': True,
        'auto_pruned': False,
        'first_prompt_at': first_prompt_at.isoformat(),
        'grace_deadline': deadline.isoformat(),
        'systems': systems,
    }


def _subscription_payload(active: dict | None, latest: dict | None) -> dict:
    return {
        'active': bool(active),
        'active_plan': (active or {}).get('plan') if active else None,
        'active_expires_at': active.get('expires_at').isoformat() if active and active.get('expires_at') else None,
        'latest_status': latest.get('status') if latest else None,
        'features': _subscription_features(),
        'plans': [
            {
                'code': code,
                'title': cfg['title'],
                'days': cfg['days'],
                'amount_rub': cfg['amount_rub'],
            }
            for code, cfg in SUBSCRIPTION_PLANS.items()
        ],
    }


@app.get('/systems')
async def systems_overview(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    await get_active_training_system_id(user_id)
    limit_info = await _enforce_system_limit_if_needed(user_id)
    systems = limit_info.get('systems') or await list_training_systems(user_id)
    active_id = await get_active_training_system_id(user_id)
    sub = await db.get_active_subscription(user_id)
    return {
        'active_system_id': int(active_id),
        'systems': systems,
        'has_subscription': bool(sub),
        'systems_limit': {
            'max_without_subscription': 1,
            'requires_resolution': bool(limit_info.get('requires_resolution')),
            'auto_pruned': bool(limit_info.get('auto_pruned')),
            'first_prompt_at': limit_info.get('first_prompt_at'),
            'grace_deadline': limit_info.get('grace_deadline'),
        },
    }


@app.post('/systems')
async def systems_create(payload: dict = Body(default={}), ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    name = (payload.get('name') or '').strip() or 'Новая система'
    color = (payload.get('color') or '#2ea6ff').strip()
    replace_existing = bool(payload.get('replace_existing'))
    try:
        workouts_per_week = int(payload.get('workouts_per_week') or 0)
    except (TypeError, ValueError):
        workouts_per_week = 0
    workouts_per_week = max(1, min(7, workouts_per_week)) if workouts_per_week else None

    has_sub = await _has_active_subscription(user_id)
    systems_count = await db.count_user_training_systems(user_id)
    if not has_sub and systems_count >= 1 and not replace_existing:
        raise HTTPException(status_code=402, detail='Без подписки доступна только одна система. Новая система может только перезаписать текущую.')

    system_id = await create_training_system(user_id, name, color, workouts_per_week=workouts_per_week)
    if workouts_per_week:
        await apply_system_to_current_plan(user_id, int(system_id))
        await set_workouts_per_week(user_id, workouts_per_week)
        await sync_current_plan_to_system(user_id, int(system_id))

    if not has_sub:
        await db.prune_user_training_systems(user_id, int(system_id))

    return {'ok': True, 'system_id': int(system_id), 'replaced': bool(not has_sub and systems_count >= 1)}


@app.post('/systems/{system_id}/select')
async def systems_select(system_id: int, ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    await sync_current_plan_to_system(user_id, await get_active_training_system_id(user_id))
    await sync_reminders_to_system(user_id, await get_active_training_system_id(user_id))
    await apply_system_to_current_plan(user_id, int(system_id))
    return {'ok': True}


@app.post('/systems/{system_id}/rename')
async def systems_rename(system_id: int, payload: dict = Body(default={}), ctx: AuthCtx = Depends(get_auth_ctx)):
    await rename_training_system(ctx.user_id, int(system_id), (payload.get('name') or '').strip())
    return {'ok': True}


@app.post('/systems/{system_id}/color')
async def systems_color(system_id: int, payload: dict = Body(default={}), ctx: AuthCtx = Depends(get_auth_ctx)):
    await set_training_system_color(ctx.user_id, int(system_id), (payload.get('color') or '#2ea6ff').strip())
    return {'ok': True}


@app.delete('/systems/{system_id}')
async def systems_delete(system_id: int, ctx: AuthCtx = Depends(get_auth_ctx)):
    ok = await delete_training_system(ctx.user_id, int(system_id))
    if not ok:
        raise HTTPException(status_code=400, detail='Нельзя удалить единственную систему')
    await apply_system_to_current_plan(ctx.user_id, await get_active_training_system_id(ctx.user_id))
    return {'ok': True}


@app.get('/leaderboard/productivity')
async def leaderboard_productivity(
    limit: int = 10,
    offset: int = 0,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    _ = ctx.user_id
    safe_limit = max(1, min(int(limit or 10), 25))
    safe_offset = max(0, int(offset or 0))
    page, total, full = await fetch_productivity_leaderboard(limit=safe_limit, offset=safe_offset)
    my_item = next((item for item in full if int(item['user_id']) == int(ctx.user_id)), None)
    return {
        'items': [
            {
                'rank': int(item['rank']),
                'user_id': int(item['user_id']),
                'username': item['username'],
                'score': int(item['score']),
                'top_percent': int(item['top_percent']),
            }
            for item in page
        ],
        'total': int(total),
        'limit': safe_limit,
        'offset': safe_offset,
        'my_rank': int(my_item['rank']) if my_item else None,
        'my_score': int(my_item['score']) if my_item else None,
        'my_top_percent': int(my_item['top_percent']) if my_item else None,
    }


@app.get('/leaderboard/productivity/{leader_user_id}/plan')
async def leaderboard_productivity_plan(
    leader_user_id: int,
    system_id: int | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    _ = ctx.user_id
    if leader_user_id <= 0:
        raise HTTPException(status_code=400, detail='Некорректный пользователь')
    if int(leader_user_id) != int(ctx.user_id):
        visible = await get_user_leaderboard_visible(int(leader_user_id))
        if not visible:
            raise HTTPException(status_code=404, detail='Профиль недоступен')
    systems = await fetch_public_training_systems(int(leader_user_id))
    selected = None
    if system_id is not None:
        selected = next((it for it in systems if int(it.get('system_id') or 0) == int(system_id)), None)
    if selected is None and systems:
        selected = systems[0]
    plan_days = selected.get('days') if selected else await fetch_public_training_plan(int(leader_user_id))
    return {
        'leader_user_id': int(leader_user_id),
        'system_id': int(selected.get('system_id')) if selected else None,
        'days': plan_days,
        'systems': systems,
    }


@app.post('/leaderboard/productivity/{leader_user_id}/copy')
async def leaderboard_productivity_copy(
    leader_user_id: int,
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    if leader_user_id <= 0:
        raise HTTPException(status_code=400, detail='Некорректный пользователь')
    if int(leader_user_id) == int(user_id):
        raise HTTPException(status_code=400, detail='Нельзя копировать план у себя')
    visible = await get_user_leaderboard_visible(int(leader_user_id))
    if not visible:
        raise HTTPException(status_code=404, detail='Профиль недоступен')
    source_system_id = None
    if isinstance(payload, dict) and payload.get('system_id') is not None:
        try:
            source_system_id = int(payload.get('system_id'))
        except (TypeError, ValueError):
            source_system_id = None
    leader_row = await find_user_by_id(int(leader_user_id))
    fallback_name = None
    if leader_row:
        fallback_name = ((leader_row[2] or '').strip() if len(leader_row) > 2 else '') or f'athlete_{int(leader_user_id)}'
    had_sub = await _has_active_subscription(int(user_id))
    result = await copy_training_system_from_user(
        int(leader_user_id),
        int(user_id),
        source_system_id,
        fallback_system_name=fallback_name,
    )
    if not result.get('system_id'):
        raise HTTPException(status_code=400, detail='У лидера нет системы для копирования')
    if not had_sub:
        await db.prune_user_training_systems(int(user_id), int(result.get('system_id')))
        result['overwritten'] = True
    return {'ok': True, **result}



@app.get('/subscription/overview')
async def subscription_overview(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    await db.cleanup_expired_subscriptions(user_id)
    active = await db.get_active_subscription(user_id)
    latest = await db.get_latest_subscription(user_id)
    return {
        'ok': True,
        **_subscription_payload(active, latest),
        'supports_web_payment': bool(YK_TOKEN),
    }


@app.post('/subscription/payment/start')
async def subscription_payment_start(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    if not YK_TOKEN:
        raise HTTPException(status_code=503, detail='Оплата временно недоступна')
    user_id = int(ctx.user_id)
    plan_code = str(payload.get('plan_code') or '').strip()
    plan = SUBSCRIPTION_PLANS.get(plan_code)
    if not plan:
        raise HTTPException(status_code=400, detail='Неизвестный тариф')
    idem = str(uuid.uuid4())
    amount = plan['amount_rub']
    body = {
        'amount': {'value': f'{amount:.2f}', 'currency': 'RUB'},
        'capture': True,
        'confirmation': {'type': 'redirect', 'return_url': 'https://t.me'},
        'description': f"Подписка Progressor ({plan['title']})",
        'metadata': {'user_id': user_id, 'plan': plan_code},
    }
    headers = {
        'Authorization': f'Basic {YK_TOKEN}',
        'Idempotence-Key': idem,
        'Content-Type': 'application/json',
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post('https://api.yookassa.ru/v3/payments', json=body, headers=headers)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail='Не удалось создать платёж')
    data = resp.json()
    payment_id = data.get('id')
    confirmation_url = (data.get('confirmation') or {}).get('confirmation_url')
    if not payment_id or not confirmation_url:
        raise HTTPException(status_code=502, detail='Платёжный сервис вернул неполный ответ')

    await db.create_payment_record(
        user_id=user_id,
        provider='yookassa',
        amount=int(amount * 100),
        currency='RUB',
        status='pending',
        payload={'plan': plan_code, 'title': plan['title'], 'confirmation_url': confirmation_url},
        external_id=payment_id,
    )
    return {'ok': True, 'payment_id': payment_id, 'confirmation_url': confirmation_url}


@app.get('/subscription/payment/{payment_id}/status')
async def subscription_payment_status(payment_id: str, ctx: AuthCtx = Depends(get_auth_ctx)):
    if not YK_TOKEN:
        raise HTTPException(status_code=503, detail='Оплата временно недоступна')
    user_id = int(ctx.user_id)
    record = await db.get_payment_by_external_id(payment_id)
    if not record or int(record.get('user_id') or 0) != user_id:
        raise HTTPException(status_code=404, detail='Платёж не найден')

    headers = {'Authorization': f'Basic {YK_TOKEN}'}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f'https://api.yookassa.ru/v3/payments/{payment_id}', headers=headers)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail='Не удалось проверить платёж')
    data = resp.json()
    status = str(data.get('status') or '')
    await db.update_payment_status(payment_id, status, data)

    activated = False
    expires_at_iso = None
    if status == 'succeeded':
        payload_data = record.get('payload') or {}
        plan_code = str(payload_data.get('plan') or '1m')
        plan = SUBSCRIPTION_PLANS.get(plan_code) or SUBSCRIPTION_PLANS['1m']
        active = await db.get_active_subscription(user_id)
        if not active:
            expires = await db.grant_subscription_days(user_id, int(plan['days']), plan=plan_code)
            expires_at_iso = expires.isoformat()
            activated = True
        else:
            expires_at_iso = active.get('expires_at').isoformat() if active.get('expires_at') else None

    return {'ok': True, 'status': status, 'activated': activated, 'expires_at': expires_at_iso}


@app.post('/systems/resolve_limit')
async def systems_resolve_limit(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    keep_system_id = int(payload.get('keep_system_id') or 0)
    if keep_system_id <= 0:
        raise HTTPException(status_code=400, detail='Укажите систему для сохранения')
    systems = await db.list_user_training_system_ids(user_id)
    if keep_system_id not in systems:
        raise HTTPException(status_code=404, detail='Система не найдена')
    await db.prune_user_training_systems(user_id, keep_system_id)
    await apply_system_to_current_plan(user_id, keep_system_id)
    return {'ok': True, 'keep_system_id': keep_system_id}


@app.post('/ai/coach/query')
async def ai_coach_query(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    sub = await db.get_active_subscription(user_id)
    if not sub:
        raise HTTPException(status_code=403, detail='AI доступен только при активной подписке')

    mode = str(payload.get('mode') or 'free_request').strip()
    user_message = _clip_text(str(payload.get('message') or '').strip(), 1800)
    if mode == 'free_request' and not user_message:
        raise HTTPException(status_code=400, detail='Введите запрос для ИИ')

    context_payload = await _build_ai_context_payload(user_id)
    context_text = _build_user_context_summary(
        user_profile=context_payload['user_profile'],
        active_system_id=context_payload['active_system_id'],
        systems=context_payload['systems'],
        day_snapshots=context_payload['day_snapshots'],
        measurement_trends=context_payload['measurement_trends'],
    )

    user_prompt = (
        f"Режим запроса: {mode}\n"
        f"Запрос пользователя: {user_message or '—'}\n\n"
        "Контекст пользователя:\n"
        f"{context_text}\n"
    )

    result = await _call_openai_chat(_build_ai_system_prompt(mode), user_prompt)
    parsed = _extract_json_block(result['text'])

    return {
        'ok': True,
        'mode': mode,
        'answer_text': result['text'],
        'parsed_action_plan': parsed,
        'context_preview': context_text,
        'model': (OPENAI_MODEL or 'gpt-4o-mini'),
    }
