from telegram_webapp_auth import TelegramWebAppUser
from progressor_bridge import current_claims, install_auth_bridge
import functools
import inspect
import os
import json
import random
import logging
import re
import copy
import httpx
import uuid
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from dataclasses import dataclass
from datetime import UTC, datetime, date, timedelta
from math import sqrt, isfinite
from typing import Annotated, Optional
from pydantic import Field
from zoneinfo import ZoneInfo
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from settings import (
    ADMIN_IDS,
    BOT_USERNAME,
    BOT_PUBLIC_LINK,
    PROJECT_KEY,
    TG_TOKEN,
    YOOKASSA_SECRET_KEY,
    YOOKASSA_SHOP_ID,
    resolve_yookassa_return_url,
    get_openai_api_key,
    get_openai_model,
)
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram_webapp_auth import (
    InitDataError,
    TelegramInitData,
    verify_and_parse_init_data,
)

import db
import achievements_engine as achievements
from achievements_engine import (
    TEAM_ACHIEVEMENTS,
    evaluate_team,
    is_team_style_allowed,
    team_style_options_for_codes,
)
from keyboards import MG_NAMES
from db import (
    clear_day_completions,
    create_trainer_request,
    deactivate_trainer_links,
    find_user_by_id,
    find_user_by_trainer_code,
    get_running_entry,
    get_user_timezone,
    get_user_notifications_enabled,
    get_user_leaderboard_visible,
    get_active_trainer_link_for_trainee,
    get_latest_trainer_link_for_trainee,
    get_trainer_link,
    get_onboarding_video_message,
    get_onboarding_intro_message,
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
    delete_custom_measurement,
    delete_measurement_category,
    add_measurement_category,
    add_measurement_entry,
    fetch_measurement_history,
    get_measurements_last_update,
    list_custom_measurements,
    list_measurement_categories,
    reactivate_trainer_links,
    remove_user_muscle_group,
    rename_day,
    reorder_user_days,
    set_trainer_accepting_requests,
    set_user_leaderboard_visible,
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
    hard_delete_user_owned_exercise,
    delete_training_system,
    sync_current_plan_to_system,
    sync_reminders_to_system,
    apply_system_to_current_plan,
    consume_ai_coach_quota,
    get_cosmetics,
    set_title_frame,
    set_badge,
    set_badge_hidden,
    clone_system_cosmetics,
    log_user_event,
    record_system_copy,
    mark_copy_trained,
    list_user_achievements,
    create_team,
    get_user_team,
    get_team_by_code,
    join_team_direct,
    create_or_get_join_request,
    list_team_requests,
    accept_team_request,
    reject_team_request,
    leave_team,
    delete_team,
    remove_team_member,
    set_team_member_role,
    set_team_style,
    fetch_team_leaderboard,
    fetch_team_profile,
    upsert_team_daily_scores,
    list_team_achievements,
    count_team_pending_requests,
    has_pending_join_request,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "webapp")

MUSCLE_CODES = tuple(MG_NAMES.keys())

MUSCLE_NAME_MAP = {
    "neck": "Шея",
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

MAIN_MUSCLES = ("neck", "chest", "back", "legs", "shoulders", "core", "biceps", "triceps", "cardio", "other")
LIBRARY_GROUP_ORDER = (
    "neck",
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
    "neck",
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

# SQLite integer bindings are signed 64-bit; reject overflow before route execution.
ApiInt = Annotated[int, Field(ge=-(2**63), le=2**63-1)]

app = FastAPI(title="GymDiary WebApp backend")
install_auth_bridge(app, "gym")
from progressor_client import install_cache_worker
install_cache_worker(app, "gym", db.DB_PATH)
logger = logging.getLogger(__name__)

MAX_INITDATA_AGE_SEC = 24 * 60 * 60

SYSTEMS_LIMIT_GRACE_DAYS = 7
STAR_RUB_RATE = 1.79
STAR_MARKUP = 1.10

SUBSCRIPTION_PLANS = {
    '1m': {'title': '1 месяц', 'days': 30, 'amount_rub': 100},
    '6m': {'title': '6 месяцев', 'days': 180, 'amount_rub': 600},
    '12m': {'title': '12 месяцев', 'days': 365, 'amount_rub': 1000},
}


@app.on_event("startup")
async def _startup_http_clients() -> None:
    app.state.http_client_openai = httpx.AsyncClient(timeout=120.0)
    app.state.http_client_telegram = httpx.AsyncClient(timeout=15.0)


@app.on_event("shutdown")
async def _shutdown_http_clients() -> None:
    for name in ("http_client_openai", "http_client_telegram"):
        client = getattr(app.state, name, None)
        if client:
            await client.aclose()


def _get_http_client(name: str) -> httpx.AsyncClient:
    client = getattr(app.state, name, None)
    if client:
        return client
    raise HTTPException(status_code=503, detail='HTTP client pool недоступен')




def _plan_amount_stars(amount_rub: int | float) -> int:
    raw = (float(amount_rub) * STAR_MARKUP) / STAR_RUB_RATE
    # Округляем вверх до шага 5, чтобы цена выглядела аккуратно
    # и не была ниже расчётной.
    return int(max(1, ((int(raw + 4.9999)) // 5) * 5))


def _resolve_payment_method(raw: str | None) -> str:
    value = str(raw or '').strip().lower()
    return 'stars' if value == 'stars' else 'rub'

def _subscription_features() -> list[str]:
    return [
        'AI Coach поможет собрать систему / изменить упражнение / проанализировать ошибки.',
        'Расширенный список достижений: больше рамок, бейджей и наград за прогресс.',
        'Командные зачёты: можно создать свою великолепную команду, приглашать участников и расти в рейтинге.',
        'Неограниченное количество систем тренировок: сохраняй разные сплиты и переключайся между ними в любой момент.',
        'Отключение рекламы внутри бота и WebApp.',
        'Поддержка проекта: ты напрямую помогаешь развивать продукт и выпускать новые инструменты.',
    ]


def _has_yookassa_redirect_config() -> bool:
    return bool(str(YOOKASSA_SHOP_ID or '').strip() and str(YOOKASSA_SECRET_KEY or '').strip())


def _resolve_payment_return_url() -> str:
    base = str(resolve_yookassa_return_url() or '').strip()
    if not base:
        return base
    bot_link = str(BOT_PUBLIC_LINK or '').strip()
    if not bot_link and BOT_USERNAME:
        bot_link = f"https://t.me/{BOT_USERNAME}"
    if not bot_link:
        return base
    parsed = urlparse(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault('bot_link', bot_link)
    return urlunparse(parsed._replace(query=urlencode(query)))


async def _create_subscription_redirect_payment(user_id: int, plan_code: str, return_url: str | None = None) -> tuple[str, str, dict]:
    if not _has_yookassa_redirect_config():
        raise HTTPException(status_code=503, detail='Оплата временно недоступна')
    plan = SUBSCRIPTION_PLANS.get(plan_code)
    if not plan:
        raise HTTPException(status_code=400, detail='Неизвестный тариф')
    amount = float(plan['amount_rub'])
    metadata = {
        'project_key': PROJECT_KEY,
        'bot_username': BOT_USERNAME,
        'user_id': str(user_id),
        'kind': 'subscription',
        'plan_id': plan_code,
        'source': 'telegram_webapp',
    }
    body = {
        'amount': {'value': f'{amount:.2f}', 'currency': 'RUB'},
        'capture': True,
        'confirmation': {'type': 'redirect', 'return_url': return_url or _resolve_payment_return_url()},
        'description': f"Подписка Progressor на {plan['title']}",
        'metadata': metadata,
    }
    headers = {
        'Idempotence-Key': str(uuid.uuid4()),
        'Content-Type': 'application/json',
    }
    async with httpx.AsyncClient(timeout=20.0, auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)) as client:
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
        status=str(data.get('status') or 'pending'),
        payload={
            'kind': 'subscription',
            'plan_id': plan_code,
            'plan': plan_code,
            'title': plan['title'],
            'confirmation_url': confirmation_url,
            'metadata': metadata,
        },
        external_id=payment_id,
        provider_charge_id=payment_id,
        project_key=PROJECT_KEY,
    )
    return payment_id, confirmation_url, plan


async def _yookassa_get_payment(payment_id: str) -> dict:
    if not _has_yookassa_redirect_config():
        raise HTTPException(status_code=503, detail='Оплата временно недоступна')
    async with httpx.AsyncClient(timeout=15.0, auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)) as client:
        resp = await client.get(f'https://api.yookassa.ru/v3/payments/{payment_id}')
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail='Не удалось проверить платёж')
    return resp.json()


async def _create_telegram_subscription_invoice_link(
    user_id: int,
    plan_code: str,
    *,
    payment_method: str = 'rub',
) -> tuple[str, str, dict]:
    method = _resolve_payment_method(payment_method)
    if not TG_TOKEN:
        raise HTTPException(status_code=503, detail='Оплата временно недоступна')
    if method != 'stars':
        raise HTTPException(status_code=400, detail='Telegram invoice доступен только для Stars')
    plan = SUBSCRIPTION_PLANS.get(plan_code)
    if not plan:
        raise HTTPException(status_code=400, detail='Неизвестный тариф')

    payload = f'websub:{user_id}:{plan_code}:{method}:{uuid.uuid4().hex}'
    body = {
        'title': f"Подписка — {plan['title']}",
        'description': 'Подписка на умный дневник тренировок Progressor.',
        'payload': payload,
    }
    body['currency'] = 'XTR'
    body['prices'] = [
        {
            'label': f"{plan['title']} · Telegram Stars",
            'amount': _plan_amount_stars(plan['amount_rub']),
        }
    ]

    client = _get_http_client("http_client_telegram")
    resp = await client.post(
        f'https://api.telegram.org/bot{TG_TOKEN}/createInvoiceLink', json=body
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail='Не удалось создать ссылку на оплату')
    data = resp.json()
    if not data.get('ok'):
        raise HTTPException(status_code=502, detail='Платёжный сервис вернул ошибку')
    confirmation_url = str(data.get('result') or '').strip()
    if not confirmation_url:
        raise HTTPException(status_code=502, detail='Платёжный сервис вернул неполный ответ')

    amount_minor = _plan_amount_stars(plan['amount_rub']) if method == 'stars' else int(plan['amount_rub']) * 100
    currency = 'XTR' if method == 'stars' else 'RUB'

    await db.create_payment_record(
        user_id=user_id,
        provider='telegram',
        amount=amount_minor,
        currency=currency,
        status='pending',
        payload={'plan': plan_code, 'title': plan['title'], 'confirmation_url': confirmation_url, 'payment_method': method},
        external_id=payload,
    )
    return payload, confirmation_url, plan


DAY_COMPLETION_RETENTION_DAYS = 2
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
    shared = current_claims()
    if shared:
        return TelegramInitData(user=TelegramWebAppUser(**shared["user"]), auth_date=shared["auth_date"])

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
    x_acting_user: ApiInt | None = Header(default=None, alias="X-Acting-User"),
) -> AuthCtx:
    internal_user_id = await db.get_or_create_user(tg.user.id, tg.user.username)
    actor_user_id = internal_user_id
    acting_user_id = None
    acting_can_edit = True
    is_acting = False
    route_path = getattr(request.scope.get('route'), 'path', request.url.path)
    if x_acting_user and x_acting_user != internal_user_id:
        acting_user_id = int(x_acting_user)
        if route_path.startswith("/settings/trainer"):
            acting_user_id = None
        else:
            # Match the personal sections hidden by the WebApp in trainer mode.
            personal_prefixes = ('/teams', '/achievements', '/subscription', '/api/payments', '/all_exercises', '/leaderboard')
            if route_path.startswith(personal_prefixes) or route_path == '/settings/leaderboard_visibility':
                raise HTTPException(status_code=403, detail='Раздел доступен только для личного дневника')
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
    except (TypeError, ValueError, OverflowError):
        return default


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _team_join_policy(team_like: dict | None) -> str:
    return 'open' if bool((team_like or {}).get('is_open')) else 'closed'


def _team_join_action_for_viewer(*, team_like: dict | None, me_team: dict | None, has_pending_request: bool) -> str:
    if me_team:
        return 'none'
    if has_pending_request and not bool((team_like or {}).get('is_open')):
        return 'pending'
    return 'join' if bool((team_like or {}).get('is_open')) else 'request'


def _clip_text(text: str, limit: int) -> str:
    src = (text or '').strip()
    if len(src) <= limit:
        return src
    return src[: max(0, limit - 1)].rstrip() + '…'


def _normalize_name(value: object) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip()).lower()


async def _build_ai_catalog_lookup(user_id: int, day_snapshots: list[dict], *, per_group_limit: int = 30) -> tuple[list[dict], dict[int, dict], dict[str, dict], list[dict]]:
    groups: set[str] = set()
    direct_exercises: dict[int, dict] = {}

    groups.update(MG_NAMES.keys())
    custom_groups = await list_user_muscle_groups(int(user_id))
    custom_group_map = {str(code): str(name or '').strip() for code, name in custom_groups}
    groups.update(custom_group_map.keys())

    for day in day_snapshots:
        for ex in day.get('exercises') or []:
            ex_id = _to_int(ex.get('exercise_id'), 0)
            group = str(ex.get('group') or 'other').strip() or 'other'
            groups.add(group)
            if ex_id <= 0:
                continue
            direct_exercises[ex_id] = {
                'exercise_id': ex_id,
                'exercise_ref': f'ex_{ex_id}',
                'name': str(ex.get('name') or '').strip(),
                'group': group,
                'source': 'current_plan',
            }

    by_id: dict[int, dict] = dict(direct_exercises)
    for group in sorted(groups):
        rows = await db.list_exercises_by_group(group, user_id)
        for row in rows[:per_group_limit]:
            if not row:
                continue
            ex_id = row[0]
            name = row[1] if len(row) > 1 else ''
            muscle_group = row[2] if len(row) > 2 else group
            ex_id_int = _to_int(ex_id, 0)
            if ex_id_int <= 0:
                continue
            if ex_id_int not in by_id:
                by_id[ex_id_int] = {
                    'exercise_id': ex_id_int,
                    'exercise_ref': f'ex_{ex_id_int}',
                    'name': str(name or '').strip(),
                    'group': str(muscle_group or group or 'other').strip() or 'other',
                    'source': 'catalog',
                }

    ordered = sorted(by_id.values(), key=lambda item: (0 if item.get('source') == 'current_plan' else 1, item.get('group') or '', item.get('name') or ''))
    groups_payload = [
        {
            'code': code,
            'name': custom_group_map.get(code) or MG_NAMES.get(code) or code,
            'is_custom': code in custom_group_map,
        }
        for code in sorted(groups)
    ]
    by_name = {
        _normalize_name(item.get('name')): item
        for item in ordered
        if _normalize_name(item.get('name'))
    }
    return ordered, by_id, by_name, groups_payload




def _parse_exercise_ref(value: object) -> int | None:
    raw = str(value or '').strip().lower()
    if not raw.startswith('ex_'):
        return None
    try:
        ex_id = int(raw[3:])
    except ValueError:
        return None
    return ex_id if ex_id > 0 else None


def _sanitize_ai_action(action: dict, *, max_day_index: int) -> dict | None:
    """
    Нормализует одиночное действие AI.
    Возвращает чистый dict либо None.
    Поддержка: add_exercise, remove_exercise, update_sets, create_system.
    (replace_exercise можно оставить совместимо, но лучше его больше не использовать)
    """
    if not isinstance(action, dict):
        return None

    action_type = str(action.get("type") or "").strip()
    allowed = {"add_exercise", "remove_exercise", "update_sets", "create_system", "replace_exercise"}
    if action_type not in allowed:
        return None

    def _clamp_int(v, lo, hi, default):
        try:
            x = int(v)
        except Exception:
            x = int(default)
        return max(lo, min(hi, x))

    def _clamp_float(v, lo, hi, default):
        x = _to_float(v, float(default))
        return max(lo, min(hi, x))

    def _norm_name(v, max_len=120):
        s = str(v or "").strip()
        if not s:
            return ""
        return _clip_text(s, max_len)

    def _norm_group(v):
        s = str(v or "").strip().lower()
        s = re.sub(r"[^a-z0-9а-яё_\-\s]", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s+", " ", s).strip()

        # allow user custom codes like u123
        if re.fullmatch(r"u\d+", s):
            return s

        # direct known codes
        if s in MG_NAMES:
            return s

        # ru/en synonyms -> known codes
        alias = {
            "шея": "neck", "neck": "neck", "трапеции": "neck", "грудь": "chest", "грудные": "chest",
            "спина": "back",
            "плечи": "shoulders", "дельты": "shoulders",
            "бицепс": "biceps", "бицепсы": "biceps", "biceps": "biceps",
            "трицепс": "triceps", "triceps": "triceps",
            "руки": "biceps", "arms": "biceps",
            "ноги": "legs", "legs": "legs", "квадрицепс": "legs", "бедра": "legs", "икры": "legs",
            "пресс": "abs", "живот": "abs", "abs": "abs",
            "другое": "other", "other": "other",
        }
        if s in alias:
            return alias[s]

        return "other"

    # общий reason
    reason = _clip_text(str(action.get("reason") or "").strip(), 220)

    # create_system (для new_system)
    if action_type == "create_system":
        system_name = _clip_text(str(action.get("system_name") or "Система от ИИ").strip() or "Система от ИИ", 80)

        raw_days = action.get("days") if isinstance(action.get("days"), list) else []
        clean_days: list[dict] = []
        used_day_idx: set[int] = set()

        for d in raw_days:
            if not isinstance(d, dict):
                continue
            day_idx = _clamp_int(d.get("day_index"), 1, 7, 1)
            if day_idx in used_day_idx:
                continue
            used_day_idx.add(day_idx)

            ex_list = d.get("exercises") if isinstance(d.get("exercises"), list) else []
            clean_ex: list[dict] = []
            for ex in ex_list:
                if not isinstance(ex, dict):
                    continue
                ex_name = _norm_name(ex.get("exercise_name") or ex.get("name"))
                if not ex_name:
                    continue

                mg = _norm_group(ex.get("muscle_group") or ex.get("group"))
                sets = _clamp_int(ex.get("sets"), 1, 12, 3)
                reps = _clamp_int(ex.get("reps"), 0, 50, 10)
                seconds = _clamp_int(ex.get("seconds"), 0, 600, 0)
                weight = _clamp_float(ex.get("weight_kg"), 0.0, 500.0, 0.0)

                # согласование reps/seconds
                if reps > 0 and seconds > 0:
                    seconds = 0
                if reps == 0 and seconds == 0:
                    reps = 10

                clean_ex.append({
                    "exercise_name": ex_name,
                    "muscle_group": mg,
                    "sets": sets,
                    "reps": reps,
                    "seconds": seconds,
                    "weight_kg": weight,
                    "note": _clip_text(str(ex.get("note") or "").strip(), 120),
                    "how_to": _clip_text(str(ex.get("how_to") or "").strip(), 280),
                })

            if clean_ex:
                clean_days.append({
                    "day_index": day_idx,
                    "title": _clip_text(str(d.get("title") or "").strip(), 40),
                    "exercises": clean_ex,
                })

        if not clean_days:
            return None

        clean_days.sort(key=lambda x: int(x.get("day_index") or 0))
        return {
            "type": "create_system",
            "system_name": system_name,
            "days": clean_days[:7],
            "reason": reason,
            "rationale": action.get("rationale") if isinstance(action.get("rationale"), list) else [],
        }

    # остальные (дневные) action
    day_idx = _clamp_int(action.get("day_index"), 1, max(1, min(7, max_day_index)), 1)

    if action_type == "remove_exercise":
        old_name = _norm_name(action.get("old_exercise_name"))
        if not old_name:
            return None
        return {
            "type": "remove_exercise",
            "day_index": day_idx,
            "old_exercise_name": old_name,
            "reason": reason,
        }

    if action_type in {"add_exercise", "update_sets"}:
        ex_name = _norm_name(action.get("exercise_name"))
        if not ex_name:
            return None

        mg = _norm_group(action.get("muscle_group") or action.get("group"))
        sets = _clamp_int(action.get("sets"), 1, 12, 3)
        reps = _clamp_int(action.get("reps"), 0, 50, 10)
        seconds = _clamp_int(action.get("seconds"), 0, 600, 0)
        weight = _clamp_float(action.get("weight_kg"), 0.0, 500.0, 0.0)
        how_to = _clip_text(str(action.get("how_to") or "").strip(), 280)

        if reps > 0 and seconds > 0:
            seconds = 0
        if reps == 0 and seconds == 0:
            reps = 10

        return {
            "type": action_type,
            "day_index": day_idx,
            "exercise_name": ex_name,
            "muscle_group": mg,
            "sets": sets,
            "reps": reps,
            "seconds": seconds,
            "weight_kg": weight,
            "reason": reason,
            "how_to": how_to,
        }

    # legacy: replace_exercise (на всякий случай)
    if action_type == "replace_exercise":
        old_name = _norm_name(action.get("old_exercise_name"))
        new_name = _norm_name(action.get("new_exercise_name"))
        if not old_name or not new_name:
            return None
        sets = _clamp_int(action.get("sets"), 1, 12, 3)
        reps = _clamp_int(action.get("reps"), 0, 50, 10)
        seconds = _clamp_int(action.get("seconds"), 0, 600, 0)
        weight = _clamp_float(action.get("weight_kg"), 0.0, 500.0, 0.0)
        how_to = _clip_text(str(action.get("how_to") or "").strip(), 280)
        if reps > 0 and seconds > 0:
            seconds = 0
        if reps == 0 and seconds == 0:
            reps = 10
        return {
            "type": "replace_exercise",
            "day_index": day_idx,
            "old_exercise_name": old_name,
            "new_exercise_name": new_name,
            "sets": sets,
            "reps": reps,
            "seconds": seconds,
            "weight_kg": weight,
            "reason": reason,
            "how_to": how_to,
        }

    return None


def _sanitize_ai_action_plan(plan: dict | None, mode: str, *, workouts_per_week: int, active_day_count: int, requested_days: int | None = None) -> tuple[dict, list[dict]]:
    warnings: list[dict] = []
    if not isinstance(plan, dict):
        return {"actions": []}, [{"code": "invalid_action_plan", "detail": "Пустой или невалидный JSON action_plan от AI."}]

    raw_actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
    # Day indices need not be contiguous (for example, only days 2 and 5 are active).
    max_day_index = 7

    clean_actions: list[dict] = []
    for a in raw_actions:
        clean = _sanitize_ai_action(a, max_day_index=max_day_index)
        if not clean:
            warnings.append({"code": "invalid_action", "detail": "Одно из действий AI было отброшено как невалидное."})
            continue
        clean_actions.append(clean)

    # режимные фильтры
    if mode == "mistakes_analysis":
        return {"actions": []}, []

    if mode == "new_system":
        create_actions = [a for a in clean_actions if a.get("type") == "create_system"]
        if not create_actions:
            return {"actions": []}, [{"code": "missing_create_system", "detail": "Для режима new_system не найдено валидного create_system действия."}]
        picked = create_actions[0]

        # доп. нормализация количества дней
        requested_days = int(requested_days or 0) if int(requested_days or 0) > 0 else 0
        expected_days = requested_days if requested_days > 0 else (int(workouts_per_week or 0) if int(workouts_per_week or 0) > 0 else max(1, int(active_day_count or 3)))
        days = picked.get("days") if isinstance(picked.get("days"), list) else []
        days = [d for d in days if isinstance(d, dict) and isinstance(d.get("exercises"), list) and d.get("exercises")]
        days.sort(key=lambda x: int(x.get("day_index") or 0))
        if len(days) > 7:
            warnings.append({"code": "days_truncated", "detail": f"AI вернул {len(days)} дней, ограничено до 7.", "actual": len(days), "max": 7})
            days = days[:7]
        if len(days) < 2:
            warnings.append({"code": "too_few_days", "detail": "AI вернул слишком мало дней новой системы; рекомендуется минимум 2."})
        if expected_days > 0 and len(days) != expected_days:
            return {"actions": []}, [{"code": "days_count_mismatch", "detail": f"ИИ вернул {len(days)} день(дней) вместо {expected_days}.", "expected": expected_days, "actual": len(days)}]
        picked["days"] = days
        return {"actions": [picked]}, warnings

    if mode == "adjust_sets":
        upd = [a for a in clean_actions if a.get("type") == "update_sets"]
        if not upd:
            return {"actions": []}, [{"code": "missing_update_sets", "detail": "Для режима adjust_sets не найдено валидных update_sets действий."}]
        # ограничим размер
        return {"actions": upd[:40]}, warnings

    # replace_exercises
    allowed = {"add_exercise", "remove_exercise", "update_sets", "replace_exercise"}
    filtered = [a for a in clean_actions if a.get("type") in allowed]
    return {"actions": filtered[:60]}, warnings


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


async def _bulk_fetch_baselines(user_id: int, day_indices: list[int], exercise_ids: list[int]) -> tuple[dict[tuple[int, int], tuple], dict[int, tuple]]:
    """
    Returns:
      exact[(day_index, exercise_id)] = (sets, reps, seconds, weight_kg)
      fallback[exercise_id]           = (sets, reps, seconds, weight_kg)   # earliest baseline by day_index
    """
    day_indices = [int(x) for x in day_indices if int(x) > 0]
    exercise_ids = [int(x) for x in exercise_ids if int(x) > 0]
    if not day_indices or not exercise_ids:
        return {}, {}

    day_ph = ','.join('?' for _ in day_indices)
    ex_ph = ','.join('?' for _ in exercise_ids)

    exact: dict[tuple[int, int], tuple] = {}
    fallback: dict[int, tuple] = {}

    async with db.connect_db() as conn:
        params1: list[object] = [user_id, *day_indices, *exercise_ids]
        cur = await conn.execute(
            f"""
            SELECT day_index, exercise_id, sets, reps, seconds, weight_kg
            FROM exercise_baseline
            WHERE user_id=?
              AND day_index IN ({day_ph})
              AND exercise_id IN ({ex_ph})
              AND COALESCE(sets, 0) >= 0
            """,
            tuple(params1),
        )
        for d, ex_id, sets, reps, secs, w in await cur.fetchall():
            exact[(int(d), int(ex_id))] = (sets, reps, secs, w)

        params2: list[object] = [user_id, *exercise_ids, user_id]
        cur = await conn.execute(
            f"""
            SELECT b.exercise_id, b.sets, b.reps, b.seconds, b.weight_kg
            FROM exercise_baseline b
            JOIN (
                SELECT exercise_id, MIN(day_index) AS min_day
                FROM exercise_baseline
                WHERE user_id=?
                  AND exercise_id IN ({ex_ph})
                  AND COALESCE(sets, 0) >= 0
                GROUP BY exercise_id
            ) m ON m.exercise_id=b.exercise_id AND m.min_day=b.day_index
            WHERE b.user_id=?
              AND COALESCE(b.sets, 0) >= 0
            """,
            tuple(params2),
        )
        for ex_id, sets, reps, secs, w in await cur.fetchall():
            fallback[int(ex_id)] = (sets, reps, secs, w)

    return exact, fallback


async def _build_ai_context_payload(user_id: int) -> dict:
    active_system_id = await get_active_training_system_id(user_id)
    systems = await list_training_systems(user_id)
    settings = await db.fetch_user_settings(user_id)
    workouts_per_week = 0
    if isinstance(settings, dict):
        workouts_per_week = _to_int(settings.get('workouts_per_week'), 0)
    elif isinstance(settings, tuple):
        # db.fetch_user_settings() returns (system, workouts_per_week)
        workouts_per_week = _to_int(settings[1] if len(settings) > 1 else 0, 0)
    timezone = await get_user_timezone(user_id)
    active_days = await db.list_active_days(user_id)

    day_snapshots: list[dict] = []
    today_iso = datetime.now(UTC).strftime('%Y-%m-%d')
    pending: list[tuple[int, int, dict]] = []
    all_ex_ids: set[int] = set()
    all_day_ids: list[int] = []
    for day_index, day_label in active_days:
        day_i = int(day_index)
        all_day_ids.append(day_i)

        rows = await db.fetch_day_exercises(user_id, day_i, today_iso, active_system_id)
        ex_list: list[dict] = []
        for ue_id, ex_name, muscle_group, _is_done, exercise_id, _note in rows:
            ex_id = int(exercise_id)
            item = {
                'user_exercise_id': int(ue_id),
                'exercise_id': ex_id,
                'name': ex_name,
                'group': muscle_group or 'other',
                'sets': 0,
                'reps': 0,
                'seconds': 0,
                'weight_kg': 0.0,
            }
            ex_list.append(item)
            pending.append((day_i, ex_id, item))
            all_ex_ids.add(ex_id)

        day_snapshots.append({
            'day_index': day_i,
            'day_label': day_label,
            'exercises': ex_list,
        })

    exact_map, fallback_map = await _bulk_fetch_baselines(user_id, all_day_ids, sorted(all_ex_ids))

    for day_i, ex_id, item in pending:
        base = exact_map.get((day_i, ex_id)) or fallback_map.get(ex_id)
        if not base:
            continue
        sets, reps, secs, w = base
        item['sets'] = _to_int(sets, 0)
        item['reps'] = _to_int(reps, 0)
        item['seconds'] = _to_int(secs, 0)
        item['weight_kg'] = _to_float(w, 0.0)

    catalog_items, catalog_by_id, catalog_by_name, catalog_groups = await _build_ai_catalog_lookup(user_id, day_snapshots)

    measurement_codes = ['body_weight', 'waist_navel', 'chest', 'hips', 'bicep_flexed', 'thigh_upper', 'run_5k', 'resting_hr']
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
            'workouts_per_week': workouts_per_week,
            'timezone': timezone or 'UTC',
        },
        'active_system_id': int(active_system_id),
        'systems': systems,
        'day_snapshots': day_snapshots,
        'measurement_trends': measurement_trends,
        'catalog_context': {
            'items': catalog_items,
            'groups': catalog_groups,
            'by_id': catalog_by_id,
            'by_name': catalog_by_name,
        },
    }




def _build_mistakes_analysis_fallback(context_payload: dict, user_message: str) -> tuple[str, list[str]]:
    day_snapshots = context_payload.get('day_snapshots') if isinstance(context_payload, dict) else []
    measurement_trends = context_payload.get('measurement_trends') if isinstance(context_payload, dict) else []
    workouts_per_week = _to_int(((context_payload.get('user_profile') or {}) if isinstance(context_payload, dict) else {}).get('workouts_per_week'), 0)

    days = day_snapshots if isinstance(day_snapshots, list) else []
    total_days = len(days)
    total_exercises = 0
    group_counts: dict[str, int] = {}
    low_volume_exercises = 0
    sparse_days = 0

    for day in days:
        exs = day.get('exercises') if isinstance(day, dict) else []
        exs = exs if isinstance(exs, list) else []
        if len(exs) < 4:
            sparse_days += 1
        total_exercises += len(exs)
        for ex in exs:
            group = str((ex or {}).get('group') or 'other').strip() or 'other'
            group_counts[group] = group_counts.get(group, 0) + 1
            sets = _to_int((ex or {}).get('sets'), 0)
            reps = _to_int((ex or {}).get('reps'), 0)
            seconds = _to_int((ex or {}).get('seconds'), 0)
            if sets <= 0 or (reps <= 0 and seconds <= 0):
                low_volume_exercises += 1

    sorted_groups = sorted(group_counts.items(), key=lambda it: it[1], reverse=True)
    dominant_group = sorted_groups[0][0] if sorted_groups else ''
    low_groups = [name for name, count in sorted_groups if count == 1][:3]

    if total_exercises == 0:
        summary = (
            'Пока данных по выполненным упражнениям мало, поэтому точную диагностику прогресса сделать нельзя. '
            'Но уже по текущей структуре можно повысить качество тренировок: сделать план более сбалансированным, '
            'задать понятные объёмы и убрать случайность в нагрузке.'
        )
        rationale = [
            'Сначала зафиксируй базу на 1–2 недели: 2–4 тренировки в неделю и 4–6 упражнений на тренировку, чтобы появилось с чем сравнивать прогресс.',
            'Для каждого упражнения задай рабочий формат (подходы и повторы или время под нагрузкой), иначе невозможно объективно понять, растёт нагрузка или нет.',
            'Собери минимальный баланс по телу: добавь движения на ноги, спину, плечевой пояс и кор, чтобы развитие шло равномерно, а не только по любимым упражнениям.',
            'Отслеживай восстановление: оставляй 1 лёгкий или выходной день между тяжёлыми сессиями, чтобы не упираться в усталость с первых недель.',
            'Раз в неделю делай короткий аудит: что удалось выполнить, где были пропуски, какие упражнения нужно упростить или заменить.'
        ]
        return summary, rationale

    summary_parts = [
        f'В текущем плане видно {total_exercises} упражнений на {total_days} тренировочных дней, и уже можно выделить основные точки роста.'
    ]
    if dominant_group:
        summary_parts.append(f'Нагрузка заметно концентрируется на группе «{dominant_group}», поэтому часть тела может получать непропорционально меньше работы.')
    if low_volume_exercises > 0:
        summary_parts.append('У части упражнений объём пока задан неполно, из-за этого сложно управлять прогрессией и отслеживать реальный рост.')
    if sparse_days > 0:
        summary_parts.append('Некоторые дни выглядят слишком короткими по набору упражнений, поэтому недельный объём набирается неравномерно.')
    summary_parts.append('Оптимально выровнять структуру плана и на 1–2 недели зафиксировать простые правила прогрессии.')
    summary = ' '.join(summary_parts)

    rationale: list[str] = []
    if dominant_group:
        rationale.append(
            f'Сейчас акцент смещён в сторону «{dominant_group}», из-за чего другие группы получают меньше стимула и прогресс может тормозиться. '
            'Снизь долю похожих движений и добавь 2–3 упражнения на отстающие зоны в неделю.'
        )
    if low_groups:
        rationale.append(
            f'Редко встречаются или почти не покрыты группы: {", ".join(low_groups)}. '
            'Добавь для них хотя бы по одному базовому упражнению в сплит, чтобы убрать перекосы.'
        )
    if low_volume_exercises > 0:
        rationale.append(
            f'У {low_volume_exercises} упражнений не хватает чёткой рабочей схемы (подходы/повторы или время), поэтому трудно держать системную нагрузку. '
            'Пропиши конкретные диапазоны и повышай объём постепенно: +1 подход или +2–5% веса раз в 1–2 недели при хорошем самочувствии.'
        )
    if sparse_days > 0:
        rationale.append(
            f'В {sparse_days} дн. недели программа получается слишком короткой, поэтому общий тренировочный стимул проседает. '
            'Добавь недостающие многосуставные движения и распредели объём равномернее между днями.'
        )
    if workouts_per_week > 0:
        rationale.append(
            f'Текущая частота — около {workouts_per_week} тренировок в неделю; чтобы прогресс был устойчивым, зафиксируй один формат сплита минимум на 4 недели. '
            'Например, push/pull/legs или верх/низ с постепенным ростом рабочих весов.'
        )
    if not measurement_trends:
        rationale.append(
            'Нет динамики по замерам, поэтому сложно понять, как меняется форма и восстановление. '
            'Добавь 2–3 контрольных метрики (вес, окружности, силовые ориентиры) и обновляй их еженедельно.'
        )

    if user_message:
        rationale.append(
            'Ориентируй изменения на свой запрос: выбери 1–2 приоритета на ближайшие недели и убери второстепенные задачи, чтобы не распыляться.'
        )

    return summary, rationale[:6]

def _extract_requested_workout_days(user_message: str) -> int | None:
    text = str(user_message or '').lower().replace('ё', 'е')
    if not text:
        return None

    words = {
        'один': 1, 'одну': 1, 'одна': 1,
        'два': 2, 'две': 2,
        'три': 3,
        'четыре': 4,
        'пять': 5,
        'шесть': 6,
        'семь': 7,
    }
    for word, value in words.items():
        if re.search(rf"\b{word}\b\s*(трен|дн|дня|дней)", text):
            return value

    patterns = (
        r"(?:на|по|под)\s*(\d)\s*(?:трен|дн|дня|дней)",
        r"(\d)\s*(?:трениров(?:к[аиу])?|дн(?:я|ей)?)\s*(?:в\s*неделю|на\s*неделю)?",
        r"(?:система|программа|план)\s*на\s*(\d)\b",
    )
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            try:
                val = int(m.group(1))
            except Exception:
                continue
            if 1 <= val <= 7:
                return val

    return None


def _build_ai_system_prompt(mode: str, requested_days: int | None = None) -> str:
    # Важно: schema уже зафиксирована через response_format.
    # Здесь даём правила качества и то, КАК ИМЕННО трактовать поля.
    common = """
Ты — AI Coach в дневнике тренировок. Отвечай строго по схеме Structured Outputs.
Никакого markdown, никаких пояснений вне JSON.

Правила полей упражнений:
- Если упражнение на повторения: reps > 0, seconds = 0.
- Если упражнение на время: reps = 0, seconds > 0.
- weight_kg = 0 если вес неизвестен/не задан.
- Названия упражнений: коротко, по-русски, без кавычек.
- old_exercise_name и exercise_name для существующих упражнений должны совпадать с тем, что в current_plan.
- Будь консервативен по нагрузке и технике (без травмоопасных рекомендаций).
""".strip()

    if mode == 'replace_exercises':
        return (common + """
Ты — AI Coach для дневника тренировок. Твоя задача: улучшить текущий план (current_plan) на основе запроса пользователя и контекста. Ты НЕ пишешь эссе — ты выдаёшь краткое summary + rationale + action_plan.actions.

Жёсткие правила:
muscle_group:
- Старайся возвращать КОД группы: chest/back/shoulders/biceps/triceps/legs/abs/other (или u123 для пользовательских).
- Если не уверен в коде — верни русское слово ("бицепс", "спина" и т.д.), система нормализует.(точно убедиться что система сможет эта нормализовать, абсолютно каждую группу мышц)
- Работай ТОЛЬКО с днями, которые реально существуют в current_plan (day_index 1..N).
- Если запрос = "разгрузить/делоад/чуть меньше/уменьшить нагрузку" — НЕ удаляй упражнения полностью.
  Используй update_sets и уменьши объём на 20–40% (sets/reps/weight), сохраняя упражнение.
- remove_exercise используем только если пользователь явно просит "убрать/исключить/удалить полностью/не делать вообще".
- Не концентрируй все изменения в Day 1. Если N>=2 — внеси изменения минимум в 2 разных днях. Если N>=3 — постарайся коснуться каждого дня хотя бы 1 действием.
- Сохраняй здравый баланс и восстановление: не превращай план в хаос и не убирай базовые группы без прямого запроса.

Цель "сделать больше, чем просили" (но в разумных рамках):
- Если пользователь просит "больше групп мышц" и в плане мало упражнений — добавь 1–2 упражнения в разные дни (add_exercise), а не просто "замени одно на одно".
- Если просит "больше акцента на руки" — усили руки в 2–3 днях (в зависимости от N): где-то add_exercise, где-то update_sets, но не перегружай.
- Если просит "разгрузить ноги" — оставь минимум 1 упражнение на ноги в неделю (если не было явного запроса удалить полностью), просто облегчи его (update_sets) и перераспредели объём на верх.

Стратегия по умолчанию:
1) Сначала найди 1–3 узких места (слишком много одной группы, дисбаланс, перегруз).
2) Затем предложи небольшие точечные изменения: обычно 4–8 действий (actions).
3) При необходимости используй пары действий "remove + add" внутри одного дня, если именно нужна замена упражнения, а не просто настройка.

Формат действий:
- actions — массив объектов.
- type может быть только: add_exercise | remove_exercise | update_sets.
- Для type="remove_exercise": заполни old_exercise_name, а поля exercise_name/muscle_group/sets/reps/seconds/weight_kg оставь пустыми/нулевыми:
  exercise_name="", muscle_group="", sets=0, reps=0, seconds=0, weight_kg=0, reason может быть "".
- Для type="add_exercise" и "update_sets": заполни exercise_name, muscle_group (код или русское слово — OK), sets/reps/seconds/weight_kg.
  old_exercise_name="".
- Если reps>0 и seconds>0 — ставь seconds=0.
- Если reps==0 и seconds==0 — ставь reps=10.
- reason — коротко, 1 строка, можно пусто.
- - how_to — ОБЯЗАТЕЛЬНО: 1–2 короткие фразы "как делать" (ключевая техника/ошибка/дыхание), без воды, до 180 символов.
  Если упражнение неоднозначно — уточни мышцу в названии и всё равно дай базовую технику.

Важно: exercise_name формулируй так, чтобы было понятно что это за упражнение и на что (например: "Сгибание рук с гантелями стоя (бицепс)").
""").strip()

    if mode == 'new_system':
        requested_days_hint = f"\n- Пользователь явно запросил {requested_days} тренировочных дней. Верни РОВНО {requested_days} объектов в create_system.days с day_index 1..{requested_days}. Меньше или больше запрещено." if requested_days else ""
        return (common + """
Ты — AI Coach. Твоя задача: создать НОВУЮ тренировочную систему (create_system) под запрос пользователя и под контекст (user_profile + history_summary). Ты должен выдать одну структуру create_system с днями и упражнениями.

Жёсткие правила:
- Верни ровно ОДНО действие create_system в action_plan.actions (один объект).
- Если пользователь явно указал в запросе количество дней — используй это число как приоритет (1..7).
- Если в запросе число дней не указано — используй workouts_per_week из профиля. Если и его нет — столько, сколько дней в current_plan (или 3 по умолчанию).
- Каждый день должен быть самодостаточным: 5–8 упражнений (если full-body) или 4–7 (если сплит), без дублирования одного и того же упражнения дважды в один день.
- Не делай “всё на руки” при запросе массы: масса = база + прогрессия + умеренный объём.
- Для массы: приоритет базовым движениям, но с понятной нагрузкой; избегай экстремальных объёмов.

Поведение "чуть больше, чем просили":
- Если запрос очень короткий, добавь 1–2 аксессуара на слабые группы (например, задняя дельта/кор) — но не перегружай.
- Учитывай ограничения: если есть признаки усталости/перегруза из history_summary — объём ниже.

Технически важно (schema):
- Всегда возвращай rationale как список строк (может быть []).
- В каждом дне всегда возвращай title (может быть "").
- В каждом упражнении всегда возвращай note (может быть "").

Формат create_system:
- type="create_system"
- system_name — коротко.
- days: массив объектов day:
  - day_index: 1..7
  - title: ""
  - exercises: массив объектов:
     - exercise_name: понятное название (при необходимости с уточнением целевой мышцы в скобках)
     - muscle_group: код или русское слово
     - sets, reps или seconds, weight_kg
     - note: ""

- how_to — ОБЯЗАТЕЛЬНО: 1–2 коротких предложения (без воды) с техникой/дыханием/ключевым акцентом именно для этого упражнения.
""" + requested_days_hint).strip()

    if mode == 'adjust_sets':
        return (common + """
Ты — AI Coach. Твоя задача: изменить параметры нагрузки (sets/reps/seconds/weight_kg) у текущих упражнений без перестройки плана. Никаких remove/add. Только update_sets.

Жёсткие правила:
muscle_group:
- Старайся возвращать КОД группы: chest/back/shoulders/biceps/triceps/legs/abs/other (или u123 для пользовательских).
- Если не уверен в коде — верни русское слово ("бицепс", "спина" и т.д.), система нормализует.(точно убедиться что система сможет эта нормализовать, абсолютно каждую группу мышц)
- actions содержит только type="update_sets".
- Работай по всем дням, которые существуют (day_index 1..N).
- Если пользователь просит "чуть сложнее/чуть легче" — меняй объём умеренно:
  - легче: -15%..-30% по объёму (sets/reps/weight)
  - сложнее: +10%..+20%
- Если просит "масса" — предпочтение 6–12 повторений, если "сила" — 3–6 повторений (но не всегда).

Формат update_sets:
- day_index обязателен
- exercise_name — возьми из текущего плана, не придумывай новое
- sets/reps/seconds/weight_kg — заполни
- old_exercise_name="" (пусто)
- reason можно пусто
- how_to можно пусто
""").strip()

    return (common + """
Ты — AI Coach. Режим mistakes_analysis: дай короткий, практичный разбор ошибок/рисков и что улучшить. Никаких действий, не меняй план.

Жёсткие правила:
- action_plan.actions должен быть пустым массивом [].
- summary: 3–6 предложений.
- rationale: 4–8 пунктов в виде коротких строк (без воды).
- Упор на причины и последствия (почему это проблема и к чему ведёт).
""").strip()


async def _call_openai_chat(system_prompt: str, user_prompt: str, *, mode: str, requested_days: int | None = None) -> dict:
    openai_api_key = get_openai_api_key()
    if not openai_api_key:
        raise HTTPException(status_code=503, detail='OPENAI_API_KEY не задан')
    openai_model = get_openai_model().strip()
    if not openai_model:
        raise HTTPException(status_code=503, detail='OPENAI_MODEL не задан')

    limits = _ai_limits_for_mode(mode)
    response_format = _ai_response_format_for_mode(mode, requested_days=requested_days)

    payload = {
        'model': openai_model,
        'temperature': float(limits['temperature']),
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'response_format': response_format,
        'max_tokens': int(limits['max_tokens']),
    }
    headers = {
        'Authorization': f'Bearer {openai_api_key}',
        'Content-Type': 'application/json',
    }

    resp = await _get_http_client("http_client_openai").post(
        'https://api.openai.com/v1/chat/completions',
        headers=headers,
        json=payload,
    )

    if resp.status_code >= 400:
        detail = resp.text[:900]
        raise HTTPException(status_code=502, detail=f'OpenAI error: {detail}')

    data = resp.json()
    text = ''
    try:
        text = data['choices'][0]['message']['content'] or ''
    except Exception:
        text = ''

    # text ДОЛЖЕН быть валидным JSON согласно schema
    parsed = None
    try:
        parsed = json.loads(text) if isinstance(text, str) and text.strip() else None
    except Exception:
        parsed = None

    return {'raw': data, 'text': text, 'parsed': parsed}


def _ai_limits_for_mode(mode: str) -> dict:
    if mode == 'new_system':
        return {'max_tokens': 2200, 'temperature': 0.35}
    if mode == 'replace_exercises':
        return {'max_tokens': 1600, 'temperature': 0.35}
    if mode == 'adjust_sets':
        return {'max_tokens': 1200, 'temperature': 0.30}
    return {'max_tokens': 900, 'temperature': 0.45}


def _ai_schema_base() -> dict:
    day_index = {'type': 'integer', 'minimum': 1, 'maximum': 7}
    sets = {'type': 'integer', 'minimum': 1, 'maximum': 12}
    reps = {'type': 'integer', 'minimum': 0, 'maximum': 50}
    seconds = {'type': 'integer', 'minimum': 0, 'maximum': 600}
    weight = {'type': 'number', 'minimum': 0, 'maximum': 500}

    add_exercise = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'type': {'type': 'string', 'const': 'add_exercise'},
            'day_index': day_index,
            'exercise_name': {'type': 'string', 'minLength': 2, 'maxLength': 120},
            'muscle_group': {'type': 'string', 'minLength': 1, 'maxLength': 40},
            'sets': sets,
            'reps': reps,
            'seconds': seconds,
            'weight_kg': weight,
            'reason': {'type': 'string', 'maxLength': 200},
        },
        'required': ['type', 'day_index', 'exercise_name', 'muscle_group', 'sets', 'reps', 'seconds', 'weight_kg', 'reason'],
    }

    remove_exercise = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'type': {'type': 'string', 'const': 'remove_exercise'},
            'day_index': day_index,
            'old_exercise_name': {'type': 'string', 'minLength': 2, 'maxLength': 120},
            'reason': {'type': 'string', 'maxLength': 200},
        },
        'required': ['type', 'day_index', 'old_exercise_name', 'reason'],
    }

    update_sets = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'type': {'type': 'string', 'const': 'update_sets'},
            'day_index': day_index,
            'exercise_name': {'type': 'string', 'minLength': 2, 'maxLength': 120},
            'sets': sets,
            'reps': reps,
            'seconds': seconds,
            'weight_kg': weight,
            'reason': {'type': 'string', 'maxLength': 200},
        },
        'required': ['type', 'day_index', 'exercise_name', 'sets', 'reps', 'seconds', 'weight_kg', 'reason'],
    }

    system_exercise = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'exercise_name': {'type': 'string', 'minLength': 2, 'maxLength': 120},
            'muscle_group': {'type': 'string', 'minLength': 1, 'maxLength': 40},
            'sets': sets,
            'reps': reps,
            'seconds': seconds,
            'weight_kg': weight,
            'note': {'type': 'string', 'maxLength': 120},
            'how_to': {'type': 'string', 'maxLength': 280},
        },
        'required': ['exercise_name', 'muscle_group', 'sets', 'reps', 'seconds', 'weight_kg', 'note', 'how_to'],
    }

    system_day = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'day_index': day_index,
            'title': {'type': 'string', 'maxLength': 40},
            'exercises': {'type': 'array', 'minItems': 3, 'maxItems': 12, 'items': system_exercise},
        },
        'required': ['day_index', 'title', 'exercises'],
    }

    create_system = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'type': {'type': 'string', 'const': 'create_system'},
            'system_name': {'type': 'string', 'minLength': 2, 'maxLength': 60},
            'days': {'type': 'array', 'minItems': 1, 'maxItems': 7, 'items': system_day},
            'rationale': {'type': 'array', 'maxItems': 8, 'items': {'type': 'string'}},
        },
        'required': ['type', 'system_name', 'days', 'rationale'],
    }

    root = {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'summary': {'type': 'string', 'minLength': 10, 'maxLength': 600},
            'rationale': {'type': 'array', 'maxItems': 8, 'items': {'type': 'string', 'maxLength': 220}},
            'action_plan': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'actions': {'type': 'array'},
                },
                'required': ['actions'],
            },
        },
        'required': ['summary', 'rationale', 'action_plan'],
    }

    return {
        'defs': {
            'add_exercise': add_exercise,
            'remove_exercise': remove_exercise,
            'update_sets': update_sets,
            'create_system': create_system,
            'root': root,
        }
    }


def _ai_response_format_for_mode(mode: str, requested_days: int | None = None) -> dict:
    base = _ai_schema_base()
    defs = copy.deepcopy(base['defs'])
    root = defs['root']

    if mode == 'mistakes_analysis':
        root = copy.deepcopy(root)
        root['properties']['action_plan']['properties']['actions'] = {'type': 'array', 'maxItems': 0}
    elif mode == 'new_system':
        root = copy.deepcopy(root)
        rd = int(requested_days or 0)
        min_days = rd if 1 <= rd <= 7 else 1
        max_days = rd if 1 <= rd <= 7 else 7
        defs['create_system']['properties']['days']['minItems'] = min_days
        defs['create_system']['properties']['days']['maxItems'] = max_days
        root['properties']['action_plan']['properties']['actions'] = {
            'type': 'array',
            'minItems': 1,
            'maxItems': 1,
            'items': defs['create_system'],
        }
    elif mode == 'adjust_sets':
        root = copy.deepcopy(root)
        root['properties']['action_plan']['properties']['actions'] = {
            'type': 'array',
            'minItems': 1,
            'maxItems': 40,
            'items': defs['update_sets'],
        }
    else:
        root = copy.deepcopy(root)

        action_item_props = {
            'type': {'type': 'string', 'enum': ['add_exercise', 'remove_exercise', 'update_sets']},
            'day_index': {'type': 'integer', 'minimum': 1, 'maximum': 7},
            'exercise_name': {'type': 'string', 'maxLength': 120},
            'muscle_group': {'type': 'string', 'maxLength': 40},
            'sets': {'type': 'integer', 'minimum': 0, 'maximum': 12},
            'reps': {'type': 'integer', 'minimum': 0, 'maximum': 50},
            'seconds': {'type': 'integer', 'minimum': 0, 'maximum': 600},
            'weight_kg': {'type': 'number', 'minimum': 0, 'maximum': 500},
            'old_exercise_name': {'type': 'string', 'maxLength': 120},
            'reason': {'type': 'string', 'maxLength': 220},
            'how_to': {'type': 'string', 'maxLength': 280},
        }

        action_item = {
            'type': 'object',
            'additionalProperties': False,
            'properties': action_item_props,
            'required': list(action_item_props.keys()),
        }

        root['properties']['action_plan']['properties']['actions'] = {
            'type': 'array',
            'minItems': 1,
            'maxItems': 60,
            'items': action_item,
        }

    return {
        'type': 'json_schema',
        'json_schema': {
            'name': f'ai_coach_{mode}',
            'strict': True,
            'schema': root,
        },
    }


def _extract_json_block(answer_text: str) -> dict | None:
    src = (answer_text or '').strip()
    if not src:
        return None

    candidates: list[str] = [src]
    for marker in ('```json', '```'):
        start = src.find(marker)
        if start != -1:
            tail = src[start + len(marker):]
            end = tail.find('```')
            if end != -1:
                candidates.append(tail[:end].strip())

    obj_matches = re.findall(r'\{[\s\S]*\}', src)
    candidates.extend(obj_matches)

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None
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


def normalize_exercise_group_for_ui(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw or raw == "none":
        return "other"
    return raw


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


async def _prune_expired_day_completions(
    user_id: int, active_system_id: int, parsed: list[tuple[int, datetime]]
) -> list[tuple[int, datetime]]:
    if not parsed:
        return parsed
    tz_name = await get_user_timezone(user_id)
    zone = resolve_user_zone(tz_name)
    now_local_date = datetime.now(UTC).astimezone(zone).date()

    fresh: list[tuple[int, datetime]] = []
    stale_days: list[int] = []
    for day, completed_at in parsed:
        completed_local_date = completed_at.astimezone(zone).date()
        age_days = (now_local_date - completed_local_date).days
        if age_days >= DAY_COMPLETION_RETENTION_DAYS:
            stale_days.append(int(day))
            continue
        fresh.append((int(day), completed_at))

    if stale_days:
        async with db.connect_db() as conn:
            await conn.executemany(
                "DELETE FROM day_completions WHERE user_id=? AND system_id=? AND day_index=?",
                [(user_id, active_system_id, day) for day in stale_days],
            )
            await conn.commit()
    return fresh


async def get_active_day_completions(user_id: int) -> set[int]:
    active_system_id = await get_active_training_system_id(user_id)
    rows = await list_day_completions(user_id, active_system_id)
    parsed, _ = _parse_completion_rows(rows)
    parsed = await _prune_expired_day_completions(user_id, active_system_id, parsed)
    return {day for day, _ in parsed}


async def _normalize_day_completion_cycle(user_id: int, day_index: int, active_days: list[tuple[int, str]]) -> set[int]:
    """
    Нормализует завершённые дни так, чтобы цикл не застревал в состоянии,
    когда отмечены все дни, и чтобы при переходе на новый круг сбрасывались
    отметки будущих дней из предыдущего круга.
    """
    active_system_id = await get_active_training_system_id(user_id)
    active_day_indexes = [int(d) for d, _ in (active_days or [])]
    if not active_day_indexes:
        return set()

    completed = await get_active_day_completions(user_id)
    if not completed:
        return completed

    day_pos = {day: idx for idx, day in enumerate(active_day_indexes)}
    current_pos = day_pos.get(int(day_index))

    # Пользователь начал новый круг (например, после дня 3 отметил день 1):
    # убираем отметки "будущих" дней прошлого круга.
    if current_pos is not None:
        future_days = {
            day for day in completed
            if day in day_pos and day_pos[day] > current_pos
        }
        if future_days:
            async with db.connect_db() as conn:
                await conn.executemany(
                    "DELETE FROM day_completions WHERE user_id=? AND system_id=? AND day_index=?",
                    [(user_id, active_system_id, int(day)) for day in future_days],
                )
                await conn.commit()
            completed = await get_active_day_completions(user_id)

    # Если отмечены все активные дни, оставляем только текущий завершённый день,
    # чтобы следующий запуск открывался на первом незавершённом дне нового круга.
    if all(day in completed for day in active_day_indexes):
        await clear_day_completions(user_id, active_system_id)
        await mark_day_completed(user_id, int(day_index), datetime.now(UTC).isoformat(), active_system_id)
        completed = await get_active_day_completions(user_id)

    return completed


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


async def _ensure_user_exercise(user_id: int, ue_id: int, day_index: int, *, request_path: str | None = None) -> None:
    info = await db.get_user_exercise_info(ue_id)
    if not info:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")
    owner_id, ue_day_index = info
    if owner_id != user_id or ue_day_index != day_index:
        logger.warning(
            "user_exercise_day_mismatch user_id=%s day_index=%s user_exercise_id=%s owner_id=%s ue_day_index=%s path=%s",
            int(user_id), int(day_index), int(ue_id), int(owner_id or 0), int(ue_day_index or 0), str(request_path or ""),
        )
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


async def _require_catalog_exercise(user_id: int, exercise_id: int) -> tuple[str, str | None]:
    info = await db.get_exercise_details(exercise_id)
    if not info:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")
    name, muscle_group, owner_user_id = info
    owner = int(owner_user_id or 0)
    if owner not in (0, int(user_id)):
        raise HTTPException(status_code=404, detail="Упражнение не найдено")
    return name, muscle_group


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


async def _get_previous_done_date(user_id: int, exercise_id: int, exclude_session_id: int | None) -> str | None:
    async with db.connect_db() as conn:
        cur = await conn.execute(
            """
            SELECT s.date
            FROM session_exercises se
            JOIN user_exercises ue ON ue.id = se.user_exercise_id
            JOIN sessions s ON s.id = se.session_id
            WHERE ue.exercise_id=?
              AND s.user_id=?
              AND se.is_done=1
              AND se.session_id<>?
            ORDER BY s.date DESC, COALESCE(se.done_at, s.date || 'T00:00:00') DESC
            LIMIT 1
            """,
            (exercise_id, user_id, exclude_session_id or -1),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return row[0]


def _sets_summary_tuple(rows: list[tuple]) -> tuple[int, int, int, float] | None:
    if not rows:
        return None
    last = rows[-1]
    return (len(rows), int(last[1] or 0), int(last[2] or 0), float(last[3] or 0))


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


def _validate_payload_input(handler):
    """Reject malformed public input before any state-changing operation."""
    signature = inspect.signature(handler)
    numeric_fields = {'sets', 'reps', 'seconds', 'weight_kg', 'delta', 'set_no', 'exercise_id', 'day_index', 'system_id', 'keep_system_id', 'workouts_per_week', 'expected_days', 'distance_km', 'duration_sec', 'duration_ms', 'calories', 'heart_rate', 'weight_pct', 'day_no', 'dow', 'hour', 'minute'}
    integer_fields = numeric_fields - {'weight_kg', 'delta', 'distance_km', 'weight_pct', 'duration_sec'}
    text_fields = {'name', 'color', 'category_code', 'letter', 'metric', 'text', 'how_to', 'muscle_group', 'label', 'timezone', 'code', 'role', 'frame_code', 'badge_code', 'plan_code', 'plan_id', 'payment_method', 'kind', 'mode', 'message', 'field', 'note', 'request_id', 'exercise_name', 'new_exercise_name', 'old_exercise_name', 'system_name', 'title'}
    boolean_fields = {'enabled', 'overwrite', 'replace_existing', 'is_warmup', 'is_open', 'visible', 'allow_edit'}

    def check(item):
        if isinstance(item, list):
            for child in item:
                check(child)
        elif isinstance(item, dict):
            for key, value in item.items():
                if value is None:
                    continue
                valid = True
                if key in numeric_fields:
                    try:
                        number = float(value)
                        valid = not isinstance(value, bool) and isfinite(number) and abs(number) <= 1e12
                        if key in integer_fields:
                            valid = valid and number.is_integer()
                            if isinstance(value, str):
                                int(value)
                    except (ValueError, TypeError, OverflowError):
                        valid = False
                elif key in text_fields:
                    valid = isinstance(value, str)
                elif key in boolean_fields:
                    valid = isinstance(value, bool) or (type(value) is int and value in (0, 1))
                elif key == 'value':
                    valid = isinstance(value, (str, int, float)) and not isinstance(value, bool)
                    if isinstance(value, (int, float)):
                        valid = valid and isfinite(value) and abs(value) <= 1e12
                if not valid:
                    raise HTTPException(status_code=400, detail=f'Некорректное значение поля {key}')
                check(value)

    @functools.wraps(handler)
    async def validated(*args, **kwargs):
        payload = signature.bind_partial(*args, **kwargs).arguments.get('payload')
        if payload is not None:
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail='Ожидается объект параметров')
            check(payload)
        return await handler(*args, **kwargs)
    return validated


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
    return FileResponse(
        index_path,
        headers={
            "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
        },
    )


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
    active_day_indexes = [int(d) for d, _ in active_days]

    suggested = active_day_indexes[0] if active_day_indexes else 1

    # Всегда открываем первый незавершённый активный день текущего цикла.
    # Расписание не должно принудительно переводить на уже завершённый день.
    if active_day_indexes:
        for day_index in active_day_indexes:
            if day_index not in completed:
                suggested = int(day_index)
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
    day_index: ApiInt,
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
    strength_exercise_keys = [
        (int(ue_id), int(exercise_id))
        for ue_id, _name, muscle_group, _is_done, exercise_id, _session_note in exercises_rows
        if _normalize_group(muscle_group) != "run"
    ]
    sheet_exercise_data = await db.fetch_day_sheet_exercise_data(
        user_id,
        session_id,
        strength_exercise_keys,
        iso_date,
        active_system_id,
    )
    exercises: list[dict] = []
    for ue_id, name, muscle_group, is_done, exercise_id, session_note in exercises_rows:
        normalized_group = _normalize_group(muscle_group)
        exercise_payload: dict[str, object] = {
            "user_exercise_id": int(ue_id),
            "exercise_id": int(exercise_id),
            "name": name,
            "muscle_group": muscle_group,
            "is_done": bool(is_done),
            "current_note": (session_note or "").strip(),
        }
        source_meta = exercise_sources.get(int(exercise_id), {}) if exercise_sources else {}
        if source_meta:
            exercise_payload["source_meta"] = {
                "source_kind": str(source_meta.get("source_kind") or ""),
                "source_user_id": int(source_meta.get("source_user_id") or 0),
                "source_system_id": int(source_meta.get("source_system_id") or 0),
                "source_exercise_id": int(source_meta.get("source_exercise_id") or 0),
                "source_exercise_name": (source_meta.get("source_exercise_name") or name or "").strip(),
                "how_to": _clip_text(str(source_meta.get("how_to") or "").strip(), 280),
                "sets_count": int(source_meta.get("sets_count") or 0),
                "reps": int(source_meta.get("reps") or 0),
                "seconds": int(source_meta.get("seconds") or 0),
                "weight_kg": float(source_meta.get("weight_kg") or 0.0),
                "muscle_group": _clip_text(str(source_meta.get("muscle_group") or "").strip(), 40),
                "note": _clip_text(str(source_meta.get("note") or "").strip(), 1200),
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
            exercise_data = sheet_exercise_data.get(
                int(ue_id),
                {
                    "sets": [],
                    "previous_sets": [],
                    "previous_summary": None,
                    "previous_date": None,
                },
            )
            exercise_payload["sets"] = _serialize_sets(exercise_data.get("sets") or [])
            exercise_payload["previous_sets"] = _serialize_sets(
                exercise_data.get("previous_sets") or []
            )
            exercise_payload["previous_summary"] = _format_prev_summary(
                exercise_data.get("previous_summary")
            )
            exercise_payload["previous_date"] = exercise_data.get("previous_date")
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
    user_id = ctx.user_id
    rows = await db.search_catalog_exercises(user_id, query, limit=50)
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
    day_index: ApiInt | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    normalized_code = (code or "").strip().lower()
    if not normalized_code:
        raise HTTPException(status_code=400, detail="Группа не указана")
    if day_index is not None:
        await _validate_day(user_id, int(day_index))
    rows = await db.list_visible_catalog_exercises_for_user_in_group(user_id, normalized_code)
    added = set()
    if day_index is not None:
        added = set(await db.list_user_exercise_ids(user_id, int(day_index), normalized_code))
    return {
        "ok": True,
        "items": [
            {
                "id": int(ex_id),
                "name": name,
                "muscle_group": normalize_exercise_group_for_ui(muscle_group),
                "is_added": int(ex_id) in added,
            }
            for ex_id, name, muscle_group in rows
        ],
    }


@app.post("/catalog/group")
@_validate_payload_input
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
@_validate_payload_input
async def add_day_exercise(
    day_index: ApiInt,
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
    await _require_catalog_exercise(user_id, ex_id)
    await db.add_user_exercise(user_id, day_index, ex_id)
    return {"ok": True}


@app.post("/catalog/exercise")
@_validate_payload_input
async def create_catalog_exercise(
    payload: dict = Body(...),
    day_index: ApiInt | None = None,
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
    exercise_id = await db.create_catalog_exercise(
        user_id,
        str(name_raw).strip(),
        muscle_raw if isinstance(muscle_raw, str) else None,
    )
    await db.add_user_exercise(user_id, int(day_index), exercise_id)
    await sync_current_plan_to_system(user_id, await get_active_training_system_id(user_id))
    return {"ok": True, "exercise_id": exercise_id}


@app.post("/day/{day_index}/exercise/{exercise_id}/toggle")
async def toggle_day_exercise(
    day_index: ApiInt,
    exercise_id: ApiInt,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _require_catalog_exercise(user_id, exercise_id)
    enabled = await db.toggle_user_exercise(user_id, day_index, exercise_id)
    return {"ok": True, "enabled": bool(enabled)}


@app.post("/day/{day_index}/exercise/{exercise_id}/baseline")
@_validate_payload_input
async def set_day_exercise_baseline(
    day_index: ApiInt,
    exercise_id: ApiInt,
    payload: dict = Body(...),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _require_catalog_exercise(user_id, exercise_id)

    sets = max(1, min(100, _to_int(payload.get("sets"), 3)))
    reps = max(0, min(10000, _to_int(payload.get("reps"), 10)))
    seconds = max(0, min(86400, _to_int(payload.get("seconds"), 0)))
    weight_kg = max(0.0, min(10000.0, _to_float(payload.get("weight_kg"))))

    # normalize: reps XOR seconds
    if reps > 0 and seconds > 0:
        seconds = 0
    if reps == 0 and seconds == 0:
        reps = 10

    await db.set_baseline(user_id, day_index, exercise_id, sets, reps, seconds, weight_kg)
    return {"ok": True}


@app.post("/day/{day_index}/exercise/{exercise_id}/ai_meta")
@_validate_payload_input
async def set_ai_meta_for_exercise(
    day_index: ApiInt,
    exercise_id: ApiInt,
    payload: dict = Body(...),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _require_catalog_exercise(user_id, exercise_id)
    system_id = await get_active_training_system_id(user_id)

    sp = {
        "source_kind": "ai",
        "how_to": str(payload.get("how_to") or "")[:280],
        "sets_count": int(payload.get("sets") or 0),
        "reps": int(payload.get("reps") or 0),
        "seconds": int(payload.get("seconds") or 0),
        "weight_kg": float(payload.get("weight_kg") or 0),
        "muscle_group": str(payload.get("muscle_group") or "other")[:40],
    }

    await db.upsert_training_system_exercise_source(system_id, day_index, exercise_id, sp)
    return {"ok": True}


@app.post("/day/{day_index}/complete")
async def complete_day(
    day_index: ApiInt,
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    target_date = _parse_date_param(date)
    zone = resolve_user_zone(await get_user_timezone(user_id))
    local_now = datetime.now(zone)
    completed_at = datetime.combine(target_date, local_now.timetz()).astimezone(UTC).isoformat()
    active_system_id = await get_active_training_system_id(user_id)
    await mark_day_completed(user_id, day_index, completed_at, active_system_id)
    await mark_copy_trained(user_id, active_system_id, completed_at)
    await _evaluate_achievements(user_id)
    _, active_days = await _validate_day(user_id, day_index)
    completed = await _normalize_day_completion_cycle(user_id, day_index, active_days)
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
@_validate_payload_input
async def add_set_fast(
    day_index: ApiInt,
    user_exercise_id: ApiInt,
    payload: dict | None = Body(default=None),
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
    request: Request = None,
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _ensure_user_exercise(user_id, user_exercise_id, day_index, request_path=str(request.url.path) if request else None)
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
    day_index: ApiInt,
    user_exercise_id: ApiInt,
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
@_validate_payload_input
async def inc_last_set_fast(
    day_index: ApiInt,
    user_exercise_id: ApiInt,
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
    day_index: ApiInt,
    ue_id: ApiInt,
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    await _ensure_user_exercise(user_id, ue_id, day_index)
    target_date = _parse_date_param(date)
    state = await _build_running_state(user_id, day_index, ue_id, target_date, history_limit=30)
    return {"ok": True, **state}


async def _save_running_payload(user_id: int, day_index: int, ue_id: int, session_id: int, payload: dict, *, complete: bool = False):
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

    if complete and (distance_val <= 0 or duration_ms_val <= 0):
        raise HTTPException(status_code=400, detail="Добавь дистанцию и время перед сохранением.")
    await update_running_entry(
        entry_id,
        distance_km=distance_val,
        duration_sec=duration_sec_val,
        duration_ms=duration_ms_val,
        calories=calories_val,
        heart_rate=heart_rate_val,
        is_draft=0 if complete else int(entry[6]),
    )
    if complete:
        await mark_running_entry_done(entry_id)
        await mark_exercise_done(session_id, ue_id)


@app.post("/day/{day_index}/exercise/{ue_id}/running")
@_validate_payload_input
async def update_running_state(
    day_index: ApiInt,
    ue_id: ApiInt,
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
    await _save_running_payload(user_id, day_index, ue_id, session_id, payload)
    state = await _build_running_state(user_id, day_index, ue_id, target_date, history_limit=30)
    return {"ok": True, **state}


@app.post("/day/{day_index}/exercise/{ue_id}/running/done")
@_validate_payload_input
async def complete_running_state(
    day_index: ApiInt,
    ue_id: ApiInt,
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
    await _save_running_payload(user_id, day_index, ue_id, session_id, payload, complete=True)
    active_system_id = await get_active_training_system_id(user_id)
    exercises_rows = await db.fetch_day_exercises(user_id, day_index, iso_date, active_system_id)
    all_done = bool(exercises_rows) and all(bool(row[3]) for row in exercises_rows)
    completed_days = await get_active_day_completions(user_id)
    day_completed = False
    if all_done and day_index not in completed_days:
        completed_at = datetime.now(UTC).isoformat()
        await mark_day_completed(user_id, day_index, completed_at, active_system_id)
        await mark_copy_trained(user_id, active_system_id, completed_at)
        await _evaluate_achievements(user_id)
        _, active_days = await _validate_day(user_id, day_index)
        completed_days = await _normalize_day_completion_cycle(user_id, day_index, active_days)
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
    day_index: ApiInt,
    user_exercise_id: ApiInt,
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
        completed_at = datetime.now(UTC).isoformat()
        await mark_day_completed(user_id, day_index, completed_at, active_system_id)
        await mark_copy_trained(user_id, active_system_id, completed_at)
        await _evaluate_achievements(user_id)
        _, active_days = await _validate_day(user_id, day_index)
        completed_days = await _normalize_day_completion_cycle(user_id, day_index, active_days)
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
    day_index: ApiInt,
    ue_id: ApiInt,
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    exercise_id = await _resolve_user_exercise_id(user_id, ue_id, day_index)
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, day_index, await get_active_training_system_id(user_id))

    current_note = await db.get_exercise_persistent_note(user_id, exercise_id)
    previous_note = None
    previous_date = await _get_previous_done_date(user_id, exercise_id, session_id)
    previous_summary = _format_prev_summary(
        await db.get_last_session_summary(user_id, day_index, ue_id, iso_date, await get_active_training_system_id(user_id))
    )
    active_system_id = await get_active_training_system_id(user_id)
    previous_sets_rows = await db.fetch_last_session_sets(user_id, day_index, ue_id, iso_date, active_system_id)
    previous_sessions_rows = await db.fetch_previous_exercise_sessions(user_id, ue_id, iso_date, active_system_id, limit=20)
    previous_sessions = [
        {
            "session_id": int(item["session_id"]),
            "date": item.get("date"),
            "sets": _serialize_sets(item.get("sets") or []),
            "summary": _format_prev_summary(_sets_summary_tuple(item.get("sets") or [])),
        }
        for item in previous_sessions_rows
    ]
    async with db.connect_db() as conn:
        completed_count = await db.count_completed_sessions_for_exercise(conn, user_id, exercise_id)

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
        "previous_sessions": previous_sessions,
        "completed_count": completed_count,
    }


@app.put("/day/{day_index}/exercise/{ue_id}/note")
@_validate_payload_input
async def update_exercise_note(
    day_index: ApiInt,
    ue_id: ApiInt,
    payload: dict = Body(...),
    date: str | None = None,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    exercise_id = await _resolve_user_exercise_id(user_id, ue_id, day_index)

    note_raw = (payload or {}).get("note", "")
    note_clean = note_raw.strip() if isinstance(note_raw, str) else ""
    note_value = note_clean if note_clean else None

    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    await db.get_or_create_today_session(user_id, iso_date, day_index, await get_active_training_system_id(user_id))
    await db.set_exercise_persistent_note(user_id, exercise_id, note_value)

    return {"ok": True, "current_note": note_value}




async def _get_or_create_free_user_exercise(user_id: int, exercise_id: int) -> int:
    await _require_catalog_exercise(user_id, exercise_id)
    await db.add_user_exercise(user_id, 0, exercise_id)
    async with db.connect_db() as conn:
        cur = await conn.execute(
            """
            SELECT id
            FROM user_exercises
            WHERE user_id=? AND exercise_id=? AND day_index=0 AND is_archived=0
            LIMIT 1
            """,
            (int(user_id), int(exercise_id)),
        )
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")
    return int(row[0])


def _all_exercise_display_flags(name: str | None, muscle_group: str | None) -> dict:
    raw_name = str(name or "").strip().lower()
    mg = normalize_exercise_group_for_ui(muscle_group)

    is_running = mg == "run"
    special_duration_group = mg in {"workout", "core", "kb", "metcon"}
    is_duration_name = any(token in raw_name for token in ("(сек", "удержание", "стойка", "планк"))

    # Повторяем логику отображения как в разделе "Сегодня":
    # run -> running, workout/core/kb/metcon -> duration c весом,
    # остальные -> reps (или duration по имени упражнения).
    if is_running:
        kind = "running"
        with_weight = False
    elif special_duration_group:
        kind = "duration"
        with_weight = True
    else:
        kind = "duration" if is_duration_name else "reps"
        with_weight = True

    show_weight = with_weight and kind != "running"
    show_reps = kind == "reps"
    show_seconds = kind == "duration"

    return {
        "kind": kind,
        "with_weight": with_weight,
        "show_weight": show_weight,
        "show_reps": show_reps,
        "show_seconds": show_seconds,
        "is_running": is_running,
        "is_duration": kind == "duration",
        "is_amrap": False,
        "is_for_time": False,
    }



async def _all_exercises_groups_payload(user_id: int, iso_date: str) -> dict:
    custom = await db.list_user_muscle_groups(user_id)
    group_names = {code: name for code, name in MG_NAMES.items()}
    group_names.update({code: name for code, name in custom})
    stats, _items = await db.list_all_exercise_groups_for_user(user_id, iso_date)
    groups = []
    seen_codes = set()
    for code, st in stats.items():
        seen_codes.add(code)
        groups.append({
            "code": code,
            "name": group_names.get(code) or MUSCLE_NAME_MAP.get(code) or code,
            "count": int(st.get("count") or 0),
            "done_count": int(st.get("done_count") or 0),
            "is_custom": code not in MG_NAMES,
        })
    for code, name in custom:
        if code in seen_codes:
            continue
        groups.append({
            "code": code,
            "name": name,
            "count": 0,
            "done_count": 0,
            "is_custom": True,
        })
    groups.sort(key=lambda item: (LIBRARY_GROUP_ORDER.index(item["code"]) if item["code"] in LIBRARY_GROUP_ORDER else len(LIBRARY_GROUP_ORDER), str(item.get("name") or "").lower()))
    done_today = await db.list_all_exercises_done_today(user_id, iso_date)
    return {"ok": True, "date": iso_date, "groups": groups, "done_today": done_today, "unfinished_count": await db.count_all_exercises_unfinished(user_id, iso_date)}


async def _all_exercises_group_items(user_id: int, code: str, iso_date: str) -> list[dict]:
    items = await db.list_all_exercises_in_group_for_user_with_last_sets(user_id, code, iso_date)
    out = []
    for it in items:
        last_set = None
        last_summary = None
        last_date = it.get("last_done_at")
        if it.get("last_set_no") is not None:
            last_set = {
                "set_no": int(it.get("last_set_no") or 0),
                "reps": int(it.get("last_reps") or 0),
                "seconds": int(it.get("last_seconds") or 0),
                "weight_kg": float(it.get("last_weight_kg") or 0),
            }
            parts = []
            if last_set["weight_kg"] > 0:
                parts.append(f"{_format_num(last_set['weight_kg'])} кг")
            if last_set["reps"] > 0:
                parts.append(f"{last_set['reps']} повт")
            if last_set["seconds"] > 0:
                parts.append(f"{last_set['seconds']} сек")
            last_summary = " · ".join(parts) if parts else None
        out.append({
            "exercise_id": int(it["exercise_id"]),
            "user_exercise_id": None,
            "name": it["name"],
            "muscle_group": it["effective_group"],
            "is_done_today": bool(it.get("last_done_at") == iso_date and not it.get("unfinished_today")),
            "last_date": last_date,
            "last_set": last_set,
            "last_summary": last_summary,
            "has_history": bool(it.get("has_history")),
            "unfinished_today": bool(it.get("unfinished_today")),
            "can_hard_delete": bool(it.get("can_hard_delete")),
            "can_unlink": bool(it.get("can_unlink")),
        })
    return out


@app.post("/settings/system_groups/{code}/clear")
async def settings_system_group_clear(
    code: str,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    normalized = str(code or "").strip().lower()
    normalized = normalize_exercise_group_for_ui(normalized)
    if normalized != "other":
        raise HTTPException(status_code=400, detail="unsupported_group")
    removed_links, removed_owned_exercises = await db.clear_group_exercises_for_user(ctx.user_id, normalized)
    groups_stats, _ = await db.list_all_exercise_groups_for_user(ctx.user_id, _iso_date(_parse_date_param(None)))
    remaining_catalog_items = int((groups_stats.get("other") or {}).get("count", 0))
    return {"ok": True, "removed_links": int(removed_links), "removed_owned_exercises": int(removed_owned_exercises), "remaining_catalog_items": remaining_catalog_items}


@app.post("/settings/exercises/{exercise_id}/move")
@_validate_payload_input
async def settings_move_exercise(exercise_id: ApiInt, payload: dict = Body(...), ctx: AuthCtx = Depends(get_auth_ctx)):
    muscle_group = normalize_exercise_group_for_ui((payload or {}).get("muscle_group"))
    try:
        updated_exercise_id = await db.set_exercise_muscle_group_for_user(ctx.user_id, int(exercise_id), muscle_group)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail='Упражнение не найдено') from exc
    return {"ok": True, "exercise_id": int(updated_exercise_id), "muscle_group": muscle_group}


@app.delete("/settings/exercises/{exercise_id}/remove_for_user")
async def settings_remove_for_user(exercise_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    await _require_catalog_exercise(ctx.user_id, exercise_id)
    return await db.remove_exercise_for_user(ctx.user_id, int(exercise_id))


@app.delete("/settings/exercises/{exercise_id}/unlink")
async def settings_unlink_exercise(exercise_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    await _require_catalog_exercise(ctx.user_id, exercise_id)
    return await db.remove_exercise_for_user(ctx.user_id, int(exercise_id))


@app.post("/settings/clear_non_base_exercises")
async def settings_clear_non_base_exercises(ctx: AuthCtx = Depends(get_auth_ctx)):
    return await db.clear_non_base_group_exercises_for_user(ctx.user_id)


@app.get("/all_exercises/groups")
async def all_exercises_groups(date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    iso_date = _iso_date(_parse_date_param(date))
    return await _all_exercises_groups_payload(ctx.user_id, iso_date)


@app.get("/all_exercises/group/{code}")
async def all_exercises_group(code: str, date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    iso_date = _iso_date(_parse_date_param(date))
    return {"ok": True, "date": iso_date, "items": await _all_exercises_group_items(ctx.user_id, code, iso_date)}


@app.get("/all_exercises/unfinished")
async def all_exercises_unfinished(date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    iso_date = _iso_date(_parse_date_param(date))
    async with db.connect_db() as conn:
        cur = await conn.execute(
            """
            SELECT e.id, ue.id, e.name, COALESCE(NULLIF(TRIM(e.muscle_group), ''), 'none') AS muscle_group,
                   COUNT(st.id) AS sets_count
            FROM sessions s
            JOIN user_exercises ue ON ue.user_id=s.user_id AND ue.day_index=0 AND ue.is_archived=0
            JOIN exercises e ON e.id=ue.exercise_id
            LEFT JOIN session_exercises se ON se.session_id=s.id AND se.user_exercise_id=ue.id
            LEFT JOIN sets st ON st.session_id=s.id AND st.user_exercise_id=ue.id
            WHERE s.user_id=? AND s.date=? AND s.day_index=0 AND IFNULL(se.is_done,0) != 1
              AND (st.id IS NOT NULL OR EXISTS (
                  SELECT 1 FROM running_entries re WHERE re.session_id=s.id AND re.user_exercise_id=ue.id
                    AND (re.distance_km>0 OR re.duration_ms>0 OR re.duration_sec>0)))
            GROUP BY e.id, ue.id, e.name, muscle_group
            ORDER BY sets_count DESC, e.name COLLATE NOCASE
            """,
            (int(ctx.user_id), iso_date),
        )
        rows = await cur.fetchall()
    return {"ok": True, "date": iso_date, "items": [{
        "exercise_id": int(r[0]), "user_exercise_id": int(r[1]), "name": str(r[2] or ""),
        "muscle_group": normalize_exercise_group_for_ui(r[3]), "sets_count": int(r[4] or 0)
    } for r in (rows or [])]}


@app.post("/all_exercises/catalog/exercise")
@_validate_payload_input
async def create_all_exercises_catalog_exercise(payload: dict = Body(...), ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    name_raw = (payload or {}).get("name") if isinstance(payload, dict) else None
    muscle_raw = (payload or {}).get("muscle_group") if isinstance(payload, dict) else None
    if not name_raw or not str(name_raw).strip():
        raise HTTPException(status_code=400, detail="Название обязательно")
    exercise_id = await db.create_catalog_exercise(
        ctx.user_id,
        str(name_raw).strip(),
        muscle_raw if isinstance(muscle_raw, str) else None,
    )
    ue_id = await _get_or_create_free_user_exercise(ctx.user_id, exercise_id)
    return {"ok": True, "exercise_id": exercise_id, "user_exercise_id": ue_id}


@app.get("/all_exercises/exercise/{exercise_id}/session")
async def all_exercise_session(exercise_id: ApiInt, date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    user_id = ctx.user_id
    name, muscle_group = await _require_catalog_exercise(user_id, exercise_id)
    ue_id = await _get_or_create_free_user_exercise(user_id, exercise_id)
    target_date = _parse_date_param(date)
    iso_date = _iso_date(target_date)
    session_id = await db.get_or_create_today_session(user_id, iso_date, 0, await get_active_training_system_id(user_id))
    sets_rows = await db.fetch_exercise_sets(session_id, ue_id)
    current_note = await db.get_exercise_persistent_note(user_id, exercise_id)
    previous_sets_rows = await db.fetch_last_session_sets(user_id, 0, ue_id, iso_date, None)
    previous_summary = _format_prev_summary(await db.get_last_session_summary(user_id, 0, ue_id, iso_date, None))
    previous_date = await _get_previous_done_date(user_id, exercise_id, session_id)
    normalized_group = _normalize_group(muscle_group)
    running_state: dict[str, object] = {}
    if normalized_group == "run":
        running_state = await _build_running_state(
            user_id,
            0,
            ue_id,
            target_date,
            exercise_id=exercise_id,
            history_limit=20,
        )
    async with db.connect_db() as conn:
        completed_count = await db.count_completed_sessions_for_exercise(conn, user_id, exercise_id)
        cur = await conn.execute(
            "SELECT IFNULL(is_done,0) FROM session_exercises WHERE session_id=? AND user_exercise_id=?",
            (session_id, ue_id),
        )
        done_row = await cur.fetchone()
    return {
        "ok": True,
        "date": iso_date,
        "session_id": session_id,
        "day_index": 0,
        "user_exercise_id": ue_id,
        "exercise_id": exercise_id,
        "name": name,
        "muscle_group": muscle_group,
        "is_done": bool(done_row and done_row[0]),
        "sets": _serialize_sets(sets_rows),
        "previous_sets": _serialize_sets(previous_sets_rows),
        "previous_summary": previous_summary,
        "previous_date": previous_date,
        "current_note": current_note,
        "completed_count": completed_count,
        "display": _all_exercise_display_flags(name, muscle_group),
        "effective_group": normalize_exercise_group_for_ui(muscle_group),
        "source": "all_exercises",
        "running": running_state.get("running"),
        "running_history": running_state.get("running_history"),
        "previous_running": running_state.get("previous_running"),
    }


@app.post("/all_exercises/exercise/{exercise_id}/set/add")
@_validate_payload_input
async def all_exercise_add_set(exercise_id: ApiInt, payload: dict | None = Body(default=None), date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    user_id = ctx.user_id
    ue_id = await _get_or_create_free_user_exercise(user_id, exercise_id)
    iso_date = _iso_date(_parse_date_param(date))
    session_id = await db.get_or_create_today_session(user_id, iso_date, 0, await get_active_training_system_id(user_id))
    sets_rows = await db.fetch_exercise_sets(session_id, ue_id)
    last = sets_rows[-1] if sets_rows else None
    if not last:
        latest_any = await db.get_latest_set_values_for_exercise(user_id, ue_id, exclude_session_id=session_id)
        if latest_any:
            last = (0, int(latest_any[0]), int(latest_any[1]), float(latest_any[2]), 0)
    reps = (payload or {}).get("reps") if payload else None
    seconds = (payload or {}).get("seconds") if payload else None
    weight = (payload or {}).get("weight_kg") if payload else None
    if reps is None:
        reps = int(last[1]) if last else 0
    if seconds is None:
        seconds = int(last[2]) if last else 0
    if weight is None:
        weight = float(last[3]) if last else 0.0
    await db.add_set(session_id, ue_id, int(reps), int(seconds), float(weight), False)
    return {"ok": True, "sets": _serialize_sets(await db.fetch_exercise_sets(session_id, ue_id)), "user_exercise_id": ue_id}


@app.post("/all_exercises/exercise/{exercise_id}/set/remove_last")
async def all_exercise_remove_last(exercise_id: ApiInt, date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    user_id = ctx.user_id
    ue_id = await _get_or_create_free_user_exercise(user_id, exercise_id)
    iso_date = _iso_date(_parse_date_param(date))
    session_id = await db.get_or_create_today_session(user_id, iso_date, 0, await get_active_training_system_id(user_id))
    await db.remove_last_set(ue_id, session_id)
    return {"ok": True, "sets": _serialize_sets(await db.fetch_exercise_sets(session_id, ue_id)), "user_exercise_id": ue_id}


@app.post("/all_exercises/exercise/{exercise_id}/set/inc_last")
@_validate_payload_input
async def all_exercise_inc_set(exercise_id: ApiInt, payload: dict = Body(...), date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    user_id = ctx.user_id
    ue_id = await _get_or_create_free_user_exercise(user_id, exercise_id)
    field = (payload or {}).get("field")
    delta = (payload or {}).get("delta")
    set_no = (payload or {}).get("set_no")
    field_map = {"kg": "weight_kg", "reps": "reps", "sec": "seconds"}
    db_field = field_map.get(field)
    if db_field is None or delta is None:
        raise HTTPException(status_code=400, detail="Нужно передать поле и изменение")
    iso_date = _iso_date(_parse_date_param(date))
    session_id = await db.get_or_create_today_session(user_id, iso_date, 0, await get_active_training_system_id(user_id))
    if set_no is not None:
        await db.inc_specific_set(ue_id, session_id, int(set_no), db_field, float(delta))
    else:
        await db.inc_last_set(ue_id, session_id, db_field, float(delta))
    return {"ok": True, "sets": _serialize_sets(await db.fetch_exercise_sets(session_id, ue_id)), "user_exercise_id": ue_id}


@app.put("/all_exercises/exercise/{exercise_id}/note")
@_validate_payload_input
async def all_exercise_note(exercise_id: ApiInt, payload: dict = Body(...), ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    await _require_catalog_exercise(ctx.user_id, exercise_id)
    note_raw = (payload or {}).get("note", "")
    note_clean = note_raw.strip() if isinstance(note_raw, str) else ""
    note_value = note_clean if note_clean else None
    await db.set_exercise_persistent_note(ctx.user_id, exercise_id, note_value)
    return {"ok": True, "current_note": note_value}


@app.post("/all_exercises/exercise/{exercise_id}/done")
async def all_exercise_done(exercise_id: ApiInt, date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    user_id = ctx.user_id
    ue_id = await _get_or_create_free_user_exercise(user_id, exercise_id)
    iso_date = _iso_date(_parse_date_param(date))
    session_id = await db.get_or_create_today_session(user_id, iso_date, 0, await get_active_training_system_id(user_id))
    sets_rows = await db.fetch_exercise_sets(session_id, ue_id)
    if not sets_rows:
        defaults = await db.get_latest_set_values_for_exercise(user_id, ue_id, exclude_session_id=session_id)
        if defaults:
            await db.add_set(session_id, ue_id, int(defaults[0] or 0), int(defaults[1] or 0), float(defaults[2] or 0.0), False)
    await mark_exercise_done(session_id, ue_id)
    await _evaluate_achievements(user_id)
    payload = await _all_exercises_groups_payload(user_id, iso_date)
    return payload | {"ok": True, "user_exercise_id": ue_id, "exercise_id": exercise_id}


@app.post("/all_exercises/exercise/{exercise_id}/running")
@_validate_payload_input
async def all_exercise_running_save(exercise_id: ApiInt, payload: dict = Body(...), date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    user_id = ctx.user_id
    ue_id = await _get_or_create_free_user_exercise(user_id, exercise_id)
    iso_date = _iso_date(_parse_date_param(date))
    session_id = await db.get_or_create_today_session(user_id, iso_date, 0, await get_active_training_system_id(user_id))
    await _save_running_payload(user_id, 0, ue_id, session_id, payload or {})
    state = await _build_running_state(user_id, 0, ue_id, _parse_date_param(date), exercise_id=exercise_id, history_limit=20)
    payload = await _all_exercises_groups_payload(user_id, iso_date)
    return payload | {"ok": True, "exercise_id": int(exercise_id), "user_exercise_id": int(ue_id), "running": state.get("running"), "running_history": state.get("running_history"), "previous_running": state.get("previous_running")}


@app.post("/all_exercises/exercise/{exercise_id}/running/done")
@_validate_payload_input
async def all_exercise_running_done(exercise_id: ApiInt, payload: dict = Body(default_factory=dict), date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    user_id = ctx.user_id
    ue_id = await _get_or_create_free_user_exercise(user_id, exercise_id)
    iso_date = _iso_date(_parse_date_param(date))
    session_id = await db.get_or_create_today_session(user_id, iso_date, 0, await get_active_training_system_id(user_id))
    await _save_running_payload(user_id, 0, ue_id, session_id, payload or {}, complete=True)
    state = await _build_running_state(user_id, 0, ue_id, _parse_date_param(date), exercise_id=exercise_id, history_limit=20)
    payload = await _all_exercises_groups_payload(user_id, iso_date)
    return payload | {"ok": True, "exercise_id": int(exercise_id), "user_exercise_id": int(ue_id), "running": state.get("running"), "running_history": state.get("running_history"), "previous_running": state.get("previous_running")}


@app.post("/all_exercises/finish_day")
async def all_exercises_finish_day(date: str | None = None, ctx: AuthCtx = Depends(get_auth_ctx)):
    if ctx.is_acting:
        raise HTTPException(status_code=403, detail="Раздел доступен только для личного дневника")
    user_id = ctx.user_id
    iso_date = _iso_date(_parse_date_param(date))
    # Kept for older clients: closing a free workout must not finish exercises.
    # Only the explicit per-exercise /done endpoints may set completion flags.
    groups_payload = await _all_exercises_groups_payload(user_id, iso_date)
    return groups_payload | {"ok": True}

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
    only_used: ApiInt | None = 1,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    if only_used not in (None, 1):
        raise HTTPException(status_code=400, detail="Параметр only_used поддерживает только значение 1")

    user_id = ctx.user_id
    muscle_filter = (muscle or "").strip().lower() or None
    rows = await db.list_visible_catalog_exercises_for_user_in_group(user_id, muscle_filter or "other", query) if muscle_filter else await db.list_visible_catalog_exercises_for_user(user_id)
    return {
        "ok": True,
        "items": [
            {
                "id": int(row[0]),
                "name": row[1],
                "muscle_group": row[2],
                "has_user_anatomy_override": False,
            }
            for row in rows
            if row
        ],
    }


@app.put("/library/exercise/{exercise_id}/muscle")
@_validate_payload_input
async def update_exercise_muscle_group(
    exercise_id: ApiInt,
    payload: dict = Body(...),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    mg_raw = (payload or {}).get("muscle_group") if isinstance(payload, dict) else None

    if mg_raw is None:
        mg_value: str | None = None
    elif isinstance(mg_raw, str):
        mg_value = mg_raw.strip().lower()
        if mg_value == "":
            mg_value = None
    else:
        raise HTTPException(status_code=400, detail="Некорректная группа")

    if mg_value is not None:
        custom_groups = await list_user_muscle_groups(user_id)
        allowed_groups = set(MUSCLE_CODES) | {str(code).strip().lower() for code, _name in custom_groups if str(code).strip()}
        if mg_value not in allowed_groups:
            raise HTTPException(status_code=400, detail="Некорректная группа")

    async with db.connect_db() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM user_exercises WHERE user_id=? AND exercise_id=? AND is_archived=0 LIMIT 1",
            (user_id, exercise_id),
        )
        exists_row = await cur.fetchone()
    if not exists_row:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")

    updated_exercise_id = await db.set_exercise_muscle_group_for_user(user_id, exercise_id, mg_value)
    return {"ok": True, "id": int(updated_exercise_id), "muscle_group": mg_value}


async def _require_user_exercise(user_id: int, exercise_id: int, include_archived: bool = False) -> tuple[str, str | None]:
    archived_clause = "" if include_archived else "AND ue.is_archived=0"
    async with db.connect_db() as conn:
        cur = await conn.execute(
            f"""
            SELECT e.name, e.muscle_group
            FROM exercises e
            JOIN user_exercises ue ON ue.exercise_id = e.id
            WHERE ue.user_id=? AND ue.exercise_id=? {archived_clause}
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
    exercise_id: ApiInt,
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
@_validate_payload_input
async def update_exercise_anatomy(
    exercise_id: ApiInt,
    payload: dict = Body(...),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    name, muscle_group = await _require_user_exercise(user_id, exercise_id, include_archived=True)

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
        if not isfinite(pct) or pct <= 0:
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
    exercise_id: ApiInt,
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
    exercise_id: ApiInt,
    range: str | None = None,  # noqa: A002
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    name, muscle_group = await _require_user_exercise(user_id, exercise_id, include_archived=True)

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
    sessions_map: dict[int, dict] = {}
    for row in rows:
        (
            session_id,
            session_date,
            system_id,
            system_name,
            system_color,
            day_index,
            day_label,
            set_no,
            reps,
            seconds,
            weight,
        ) = row
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
        if session_id not in sessions_map:
            sessions_map[session_id] = {
                "session_id": int(session_id),
                "date": iso_date,
                "system_id": int(system_id or 0),
                "system_name": system_name,
                "system_color": system_color,
                "day_index": int(day_index or 0),
                "day_label": day_label,
                "sets": [],
            }

        item = timeline[iso_date]
        reps_val = int(reps or 0)
        sec_val = int(seconds or 0)
        weight_val = float(weight or 0.0)
        sessions_map[session_id]["sets"].append(
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
    sessions_list = sorted(sessions_map.values(), key=lambda x: (x["date"], x["session_id"]))

    (
        last_session_id,
        last_date,
        last_system_id,
        last_system_name,
        last_system_color,
        last_day_index,
        last_day_label,
        last_sets,
    ) = await db.fetch_last_exercise_session(user_id, exercise_id)
    last_session = None
    if last_session_id and last_date and last_sets:
        last_session = {
            "session_id": int(last_session_id),
            "date": last_date,
            "system_id": int(last_system_id or 0),
            "system_name": last_system_name,
            "system_color": last_system_color,
            "day_index": int(last_day_index or 0),
            "day_label": last_day_label,
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
        "sessions": sessions_list,
        "last_session": last_session,
        "is_running": False,
    }


@app.get("/body/day/{day_index}")
async def body_day_load(
    day_index: ApiInt,
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
        category_items.sort(key=lambda item: 0 if item.get("latest") else 1)
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
    limit: ApiInt = 10,
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
@_validate_payload_input
async def measurements_add_entry(
    payload: dict = Body(default={}),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    metric = (payload.get("metric") or "").strip()
    raw_value = payload.get("value")
    value_text = str(raw_value if raw_value is not None else payload.get("text") or "").strip()
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
@_validate_payload_input
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


@app.delete("/measurements/custom/{code}")
async def measurements_delete_custom(
    code: str,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    measurement_code = (code or "").strip()
    if not measurement_code:
        raise HTTPException(status_code=400, detail="Code required")
    removed = await delete_custom_measurement(user_id, measurement_code)
    return {"ok": True, "removed": removed}


@app.post("/measurements/category")
@_validate_payload_input
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


@app.delete("/measurements/category/{code}")
async def measurements_delete_category(
    code: str,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    category_code = (code or "").strip()
    if not category_code:
        raise HTTPException(status_code=400, detail="Code required")
    custom_items = await load_custom_measurements(user_id)
    removed_items = 0
    for item in custom_items:
        if item.get("category") != category_code:
            continue
        if await delete_custom_measurement(user_id, item.get("code") or ""):
            removed_items += 1
    removed_category = await delete_measurement_category(user_id, category_code)
    return {"ok": True, "removed": removed_category, "removed_items": removed_items}


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
            prompt = "Введи значение в килограммах (например: 50.0)."
        elif unit == "%":
            prompt = "Введи значение в процентах (например: 15.0)."
        elif unit == "повт.":
            prompt = "Укажи количество повторений (например: 12)."
        elif unit == "уд/мин":
            prompt = "Введи значение в ударах в минуту (например: 60)."
        elif unit == "ч":
            prompt = "Укажи количество часов (например: 7.5)."
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
    def number(value):
        try:
            parsed = float(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Некорректное число") from exc
        if not isfinite(parsed) or abs(parsed) > 1_000_000_000_000:
            raise ValueError("Значение выходит за допустимый диапазон")
        return parsed

    raw = text.strip()
    if not raw:
        raise ValueError("empty")
    if item.get("type") == "duration":
        seconds = parse_duration_input(raw)
        return number(seconds), ""
    raw = raw.replace(",", ".")
    if item.get("type") == "blood_pressure":
        parts = raw.replace("/", " ").split()
        if len(parts) != 2:
            raise ValueError("bp format")
        syst = int(round(number(parts[0])))
        diast = int(round(number(parts[1])))
        return float(syst), str(diast)
    value = number(raw)
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
    has_uncategorized_custom_items = any(
        (item.get("category") or "").strip() == MEASUREMENT_CUSTOM_CATEGORY["code"]
        for item in custom_items
    )
    if include_custom_fallback and has_uncategorized_custom_items and MEASUREMENT_CUSTOM_CATEGORY["code"] not in custom_codes:
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
    iso_date = _iso_date(_parse_date_param(None))
    group_stats, effective_items = await db.list_all_exercise_groups_for_user(user_id, iso_date)
    manageable = [it for it in effective_items if it.get("created_by_user") or it.get("can_unlink")]
    return {
        "ok": True,
        "workouts_per_week": wpw,
        "days": [{"day_index": int(d), "label": label} for d, label in active_days],
        "custom_groups": [{"code": code, "name": name} for code, name in custom_groups],
        "reminders": [{"day_no": int(day_no), "dow": int(dow), "hour": int(hour), "minute": int(minute)} for day_no, dow, hour, minute in reminders],
        "notifications_enabled": bool(notifications_enabled),
        "leaderboard_visible": bool(leaderboard_visible),
        "timezone": timezone,
        "all_exercises_group_stats": [{"code": code, "count": int(st.get("count") or 0)} for code, st in group_stats.items()],
        "settings_manageable_groups": [{"code": code, "name": (dict(custom_groups).get(code) or MUSCLE_NAME_MAP.get(code) or code)} for code, st in group_stats.items() if int(st.get("count") or 0) > 0],
        "settings_manageable_exercises": [{"exercise_id": int(it["exercise_id"]), "name": it["name"], "muscle_group": it["effective_group"], "is_base": bool(it["is_base"]), "can_hard_delete": bool(it["can_hard_delete"]), "can_unlink": bool(it["can_unlink"])} for it in manageable],
        "custom_exercises": [{"exercise_id": int(it["exercise_id"]), "name": it["name"], "muscle_group": it["effective_group"]} for it in effective_items if it.get("created_by_user")],
        "manageable_exercises": [{"exercise_id": int(it["exercise_id"]), "name": it["name"], "muscle_group": it["effective_group"], "is_base": bool(it["is_base"]), "can_hard_delete": bool(it["can_hard_delete"]), "can_unlink": bool(it["can_unlink"])} for it in manageable],
    }


@app.delete("/settings/custom_exercises/{exercise_id}")
async def delete_custom_exercise(exercise_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    removed = await hard_delete_user_owned_exercise(ctx.user_id, int(exercise_id))
    if not removed:
        raise HTTPException(status_code=404, detail="exercise_not_found_or_base")
    return {"ok": True, "removed": True}




async def _list_user_orphan_group_codes(user_id: int) -> list[str]:
    async with db.connect_db() as conn:
        cur = await conn.execute(
            """
            SELECT DISTINCT LOWER(TRIM(e.muscle_group)) AS code
            FROM exercises e
            WHERE (e.created_by_user_id=0 OR e.created_by_user_id=?)
              AND EXISTS (
                  SELECT 1 FROM user_exercises ue
                  WHERE ue.user_id=? AND ue.exercise_id=e.id AND COALESCE(ue.is_archived,0)=0
              )
              AND LOWER(TRIM(e.muscle_group)) LIKE 'u%'
            """,
            (int(user_id), int(user_id)),
        )
        rows = await cur.fetchall()
    return [str(r[0]).strip().lower() for r in rows if r and str(r[0]).strip()]

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
    chat_id, message_id = await get_onboarding_video_message(user_id)
    intro_chat_id, intro_message_id = await get_onboarding_intro_message(user_id)
    if not (chat_id or intro_chat_id):
        return {"ok": True, "sent": False}
    bot = Bot(TG_TOKEN)

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
@_validate_payload_input
async def settings_rename_day(
    day_index: ApiInt,
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    await _validate_day(user_id, day_index)
    label = str(payload.get("label") or "").strip()
    if not label:
        label = f"День {day_index}"
    await rename_day(user_id, day_index, label)
    await log_user_event(user_id, "rename")
    await _evaluate_achievements(user_id)
    await sync_current_plan_to_system(user_id, await get_active_training_system_id(user_id))
    wpw, active_days = await _load_user_settings(user_id)
    return {
        "ok": True,
        "workouts_per_week": wpw,
        "days": [{"day_index": int(d), "label": lbl} for d, lbl in active_days],
    }


@app.post("/settings/days/reorder")
@_validate_payload_input
async def settings_reorder_days(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    wpw, active_days = await _load_user_settings(user_id)
    active_indexes = [int(day_index) for day_index, _ in active_days]
    order_raw = payload.get("order") or []
    if not isinstance(order_raw, list):
        raise HTTPException(status_code=400, detail="Некорректный порядок дней")
    try:
        order = [int(day) for day in order_raw]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректный порядок дней")
    if sorted(order) != sorted(active_indexes):
        raise HTTPException(status_code=400, detail="Порядок не соответствует активным дням")
    mapping = await reorder_user_days(user_id, order)
    active_system_id = await get_active_training_system_id(user_id)
    await sync_current_plan_to_system(user_id, active_system_id)
    await sync_reminders_to_system(user_id, active_system_id)
    wpw, active_days = await _load_user_settings(user_id)
    return {
        "ok": True,
        "workouts_per_week": wpw,
        "days": [{"day_index": int(d), "label": lbl} for d, lbl in active_days],
        "day_mapping": {str(int(k)): int(v) for k, v in mapping.items()},
    }


@app.post("/settings/workouts_per_week")
@_validate_payload_input
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
    active_system_id = await get_active_training_system_id(user_id)
    await sync_current_plan_to_system(user_id, active_system_id)
    await sync_reminders_to_system(user_id, active_system_id)
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
    normalized = str(code or "").strip().lower()
    removed = await remove_user_muscle_group(user_id, normalized)
    affected_exercises = 0
    if removed and normalized:
        async with db.connect_db() as conn:
            cur = await conn.execute(
                """
                UPDATE exercises
                SET muscle_group='none'
                WHERE LOWER(COALESCE(muscle_group, ''))=?
                  AND created_by_user_id=?
                """,
                (normalized, int(user_id)),
            )
            affected_exercises = int(cur.rowcount or 0)
            await conn.commit()
    return {"ok": True, "removed": removed, "affected_exercises": affected_exercises}


@app.post("/settings/reminders")
@_validate_payload_input
async def settings_update_reminders(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="Некорректное состояние уведомлений")
    timezone = str(payload.get("timezone") or "").strip()
    if timezone and timezone not in ALLOWED_REMINDER_TIMEZONES:
        timezone = "UTC"
    if not timezone:
        timezone = "UTC"
    reminders = payload.get("reminders") or []
    if not isinstance(reminders, list):
        raise HTTPException(status_code=400, detail="Некорректное расписание")
    clean_reminders = []
    seen_days = set()
    for reminder in reminders:
        if not isinstance(reminder, dict):
            raise HTTPException(status_code=400, detail="Некорректное напоминание")
        try:
            day_no = int(reminder.get("day_no", 0))
            dow = int(reminder.get("dow", 0))
            hour = int(reminder.get("hour", 0))
            minute = int(reminder.get("minute", 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Некорректное напоминание")
        if not 1 <= day_no <= 7 or not 0 <= dow <= 6 or day_no in seen_days:
            raise HTTPException(status_code=400, detail="Некорректный день напоминания")
        seen_days.add(day_no)
        hour, minute = normalize_reminder_time(hour, minute)
        clean_reminders.append((day_no, dow, hour, minute))
    await ensure_training_system_defaults(user_id)
    async with db.connect_db() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        row = await (await conn.execute(
            "SELECT s.id FROM users u JOIN training_systems s ON s.id=u.active_system_id AND s.user_id=u.id WHERE u.id=?",
            (user_id,),
        )).fetchone()
        if not row:
            raise HTTPException(status_code=409, detail="Система тренировок изменилась. Повтори сохранение.")
        system_id = int(row[0])
        await conn.execute("UPDATE users SET notifications_enabled=?, tz=? WHERE id=?", (int(enabled), timezone, user_id))
        await conn.execute("DELETE FROM user_reminders WHERE user_id=?", (user_id,))
        await conn.execute("DELETE FROM training_system_reminders WHERE system_id=?", (system_id,))
        await conn.executemany(
            "INSERT INTO user_reminders(user_id, day_no, dow, hour, minute) VALUES(?,?,?,?,?)",
            [(user_id, *item) for item in clean_reminders],
        )
        await conn.executemany(
            "INSERT INTO training_system_reminders(system_id, day_no, dow, hour, minute) VALUES(?,?,?,?,?)",
            [(system_id, *item) for item in clean_reminders],
        )
        await conn.execute(
            "INSERT INTO app_meta(key,value) VALUES('reminders_updated_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (datetime.now(UTC).isoformat(),),
        )
        await conn.commit()
    return {"ok": True}


@app.post("/settings/leaderboard_visibility")
@_validate_payload_input
async def settings_leaderboard_visibility(
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    user_id = ctx.user_id
    visible = payload.get("visible", True)
    await set_user_leaderboard_visible(user_id, bool(visible))
    await _evaluate_achievements(user_id)
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
    randomize: ApiInt | None = None,
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
@_validate_payload_input
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
@_validate_payload_input
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
    link_id: ApiInt,
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
    if decision not in {"accept", "decline"}:
        raise HTTPException(status_code=400, detail="Unsupported decision")
    try:
        changed = await update_trainer_link_status(int(link[0]), "accepted" if decision == "accept" else "declined")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(status_code=409, detail="Request already processed")
    if decision == "accept":
        await _evaluate_achievements(int(link[1]))
        await _evaluate_achievements(int(link[2]))
    return {"ok": True}


@app.post("/settings/trainer/link")
@_validate_payload_input
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
    try:
        await create_trainer_request(int(trainer_id), user_id, can_edit_plan=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/settings/trainer/detach")
async def settings_trainer_detach(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    link = await get_latest_trainer_link_for_trainee(user_id)
    if not link or str(link[2]) not in {"pending", "accepted", "trainer_disabled"}:
        return {"ok": True, "removed": False}
    await update_trainer_link_status(int(link[0]), "removed")
    return {"ok": True, "removed": True}


@app.post("/settings/trainer/allow_edit")
@_validate_payload_input
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
@_validate_payload_input
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
@_validate_payload_input
async def settings_trainer_trainee_label(
    link_id: ApiInt,
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
    trainee_user_id: ApiInt,
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


async def _evaluate_achievements(user_id: int) -> dict:
    return await achievements.evaluate(user_id)


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
                'amount_stars': _plan_amount_stars(cfg['amount_rub']),
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
@_validate_payload_input
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

    previous_system_id = await get_active_training_system_id(user_id)
    try:
        system_id = await create_training_system(user_id, name, color, workouts_per_week=workouts_per_week)
    except db.aiosqlite.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="system_name_exists") from exc
    await clone_system_cosmetics(user_id, previous_system_id, int(system_id))
    if workouts_per_week:
        await db.select_training_system(user_id, int(system_id))
        await set_workouts_per_week(user_id, workouts_per_week)
        await sync_current_plan_to_system(user_id, int(system_id))

    if not has_sub:
        await db.prune_user_training_systems(user_id, int(system_id))

    return {'ok': True, 'system_id': int(system_id), 'replaced': bool(not has_sub and systems_count >= 1)}


@app.post('/systems/{system_id}/select')
async def systems_select(system_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    try:
        await db.select_training_system(user_id, int(system_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail='system_not_found') from exc
    return {'ok': True}


@app.post('/systems/{system_id}/rename')
@_validate_payload_input
async def systems_rename(system_id: ApiInt, payload: dict = Body(default={}), ctx: AuthCtx = Depends(get_auth_ctx)):
    try:
        changed = await rename_training_system(ctx.user_id, int(system_id), (payload.get('name') or '').strip())
    except db.aiosqlite.IntegrityError as exc:
        raise HTTPException(status_code=409, detail='system_name_exists') from exc
    if not changed:
        raise HTTPException(status_code=404, detail='system_not_found')
    await log_user_event(ctx.user_id, "rename")
    await _evaluate_achievements(ctx.user_id)
    return {'ok': True}


@app.post('/systems/{system_id}/color')
@_validate_payload_input
async def systems_color(system_id: ApiInt, payload: dict = Body(default={}), ctx: AuthCtx = Depends(get_auth_ctx)):
    if not await set_training_system_color(ctx.user_id, int(system_id), (payload.get('color') or '#2ea6ff').strip()):
        raise HTTPException(status_code=404, detail='system_not_found')
    return {'ok': True}


@app.delete('/systems/{system_id}')
async def systems_delete(system_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    ok = await delete_training_system(ctx.user_id, int(system_id))
    if not ok:
        raise HTTPException(status_code=400, detail='Нельзя удалить единственную систему')
    await apply_system_to_current_plan(ctx.user_id, await get_active_training_system_id(ctx.user_id))
    return {'ok': True}


@app.get('/achievements/overview')
async def achievements_overview(ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    has_sub = await _has_active_subscription(user_id)
    is_admin = int(ctx.tg_id) in ADMIN_IDS
    payload = await achievements.achievements_overview_payload(user_id, has_sub, is_admin=is_admin)
    return payload


@app.post('/achievements/select_frame')
@_validate_payload_input
async def achievements_select_frame(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    frame_code = payload.get('frame_code')
    system_id = payload.get('system_id')
    if frame_code is None:
        await set_title_frame(user_id, None, int(system_id) if system_id is not None else None)
        return {'ok': True, 'title_frame_code': None}
    frame_code = str(frame_code).strip()
    ach_code = achievements.FRAME_TO_CODE.get(frame_code)
    if not ach_code:
        raise HTTPException(status_code=400, detail='Unknown frame code')
    is_admin = int(ctx.tg_id) in ADMIN_IDS
    unlocked_codes = {code for code, _ in await list_user_achievements(user_id)}
    if ach_code not in unlocked_codes and not is_admin:
        raise HTTPException(status_code=403, detail='Frame is locked')
    await set_title_frame(user_id, frame_code, int(system_id) if system_id is not None else None)
    return {'ok': True, 'title_frame_code': frame_code}


@app.post('/achievements/select_badge')
@_validate_payload_input
async def achievements_select_badge(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    if not await _has_active_subscription(user_id):
        raise HTTPException(status_code=403, detail='Subscription required')
    badge_code = payload.get('badge_code')
    system_id = payload.get('system_id')
    hidden = payload.get('hidden')
    unlocked_codes = {code for code, _ in await list_user_achievements(user_id)}
    if badge_code is not None:
        badge_code = str(badge_code).strip()
        if badge_code and badge_code not in unlocked_codes:
            raise HTTPException(status_code=403, detail='Badge is locked')
    await set_badge(user_id, badge_code if badge_code else None, int(system_id) if system_id is not None else None)
    if hidden is not None:
        await set_badge_hidden(user_id, bool(hidden), int(system_id) if system_id is not None else None)
    cosmetics = await get_cosmetics(user_id, int(system_id) if system_id is not None else None)
    return {'ok': True, 'cosmetics': cosmetics}



@app.get('/leaderboard/productivity')
async def leaderboard_productivity(
    limit: ApiInt = 10,
    offset: ApiInt = 0,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    _ = ctx.user_id
    safe_limit = max(1, min(int(limit or 10), 25))
    safe_offset = max(0, int(offset or 0))
    page, total, full = await fetch_productivity_leaderboard(limit=safe_limit, offset=safe_offset)
    my_item = next((item for item in full if int(item['user_id']) == int(ctx.user_id)), None)
    items = []
    for item in page:
        uid = int(item['user_id'])
        is_premium = await _has_active_subscription(uid)
        cosmetics = await get_cosmetics(uid)
        selected_badge_icon = None
        badge_code = cosmetics.get('badge_code')
        badge_hidden = bool(cosmetics.get('badge_hidden'))
        if is_premium and badge_code and not badge_hidden:
            ach = achievements.ACHIEVEMENTS_BY_CODE.get(str(badge_code))
            selected_badge_icon = ach.icon if ach else None
        items.append(
            {
                'rank': int(item['rank']),
                'user_id': uid,
                'username': item['username'],
                'score': int(item['score']),
                'top_percent': int(item['top_percent']),
                'is_premium': bool(is_premium),
                'badge_icon': selected_badge_icon,
                'display_mark': selected_badge_icon if selected_badge_icon else ('⭐' if is_premium else None),
            }
        )
    return {
        'items': items,
        'total': int(total),
        'limit': safe_limit,
        'offset': safe_offset,
        'my_rank': int(my_item['rank']) if my_item else None,
        'my_score': int(my_item['score']) if my_item else None,
        'my_top_percent': int(my_item['top_percent']) if my_item else None,
    }


@app.get('/teams/me')
async def teams_me(ctx: AuthCtx = Depends(get_auth_ctx)):
    team = await get_user_team(int(ctx.user_id))
    if not team:
        return {"team": None}
    return {
        "team": {
            "team_id": int(team["team_id"]),
            "name": team["team_name"],
            "join_code": team["join_code"],
            "is_open": bool(team["is_open"]),
            "join_policy": _team_join_policy(team),
            "frame_code": team.get("frame_code"),
            "bg_code": team.get("bg_code"),
            "emblem_code": team.get("emblem_code"),
            "role": team["role"],
            "owner_user_id": int(team["owner_user_id"]),
        }
    }


@app.post('/teams/create')
@_validate_payload_input
async def teams_create(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    if not await _has_active_subscription(user_id):
        raise HTTPException(status_code=403, detail='Premium required')
    current_team = await get_user_team(user_id)
    if current_team:
        raise HTTPException(status_code=400, detail='already_in_team')
    raw_name = str(payload.get('name') or '').strip()
    if len(raw_name) < 2 or len(raw_name) > 32:
        raise HTTPException(status_code=400, detail='name_length_2_32')
    def _parse_bool_flag(raw_value) -> bool:
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, (int, float)):
            return raw_value != 0
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if not normalized:
                return False
            if normalized in {'1', 'true', 'yes', 'y', 'on', 'open', 'public'}:
                return True
            if normalized in {'0', 'false', 'no', 'n', 'off', 'closed', 'private'}:
                return False
        return False

    is_open = _parse_bool_flag(payload.get('is_open', False))
    try:
        team = await create_team(user_id, raw_name, is_open=is_open)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _evaluate_achievements(user_id)
    return {'ok': True, 'team': team}


@app.post('/teams/join_by_code')
@_validate_payload_input
async def teams_join_by_code(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    if await get_user_team(user_id):
        raise HTTPException(status_code=400, detail='already_in_team')
    if not await get_user_leaderboard_visible(user_id):
        raise HTTPException(status_code=400, detail='Включи публичность, чтобы участвовать в командах')

    code = str(payload.get('code') or '').strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail='code_required')

    team = await get_team_by_code(code)
    if not team:
        raise HTTPException(status_code=404, detail='team_not_found')

    if bool(team.get('is_open')):
        try:
            await join_team_direct(int(team['team_id']), user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {'ok': True, 'status': 'joined'}

    try:
        await create_or_get_join_request(int(team['team_id']), user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'ok': True, 'status': 'requested'}


@app.post('/teams/{team_id}/join')
async def teams_join_open(team_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    if await get_user_team(user_id):
        raise HTTPException(status_code=400, detail='already_in_team')
    if not await get_user_leaderboard_visible(user_id):
        raise HTTPException(status_code=400, detail='Включи публичность, чтобы участвовать в командах')
    profile = await fetch_team_profile(int(team_id), user_id)
    if not profile:
        raise HTTPException(status_code=404, detail='team_not_found')
    if not bool(profile.get('team', {}).get('is_open')):
        raise HTTPException(status_code=400, detail='team_closed')
    try:
        await join_team_direct(int(team_id), user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'ok': True, 'status': 'joined'}


@app.post('/teams/{team_id}/request')
async def teams_request_join(team_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    if await get_user_team(user_id):
        raise HTTPException(status_code=400, detail='already_in_team')
    if not await get_user_leaderboard_visible(user_id):
        raise HTTPException(status_code=400, detail='Включи публичность, чтобы участвовать в командах')
    profile = await fetch_team_profile(int(team_id), user_id)
    if not profile:
        raise HTTPException(status_code=404, detail='team_not_found')
    if bool(profile.get('team', {}).get('is_open')):
        raise HTTPException(status_code=400, detail='team_open_use_direct_join')
    try:
        await create_or_get_join_request(int(team_id), user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'ok': True, 'status': 'requested'}



@app.post('/teams/leave')
async def teams_leave(ctx: AuthCtx = Depends(get_auth_ctx)):
    await leave_team(int(ctx.user_id))
    return {'ok': True}


@app.post('/teams/{team_id}/delete')
async def teams_delete(team_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    me_team = await get_user_team(int(ctx.user_id))
    if not me_team or int(me_team.get('team_id') or 0) != int(team_id):
        raise HTTPException(status_code=403, detail='founder_only')
    if int(me_team.get('owner_user_id') or 0) != int(ctx.user_id):
        raise HTTPException(status_code=403, detail='founder_only')
    deleted = await delete_team(int(team_id))
    if not deleted:
        raise HTTPException(status_code=404, detail='team_not_found')
    return {'ok': True}


@app.post('/teams/{team_id}/members/{member_user_id}/remove')
async def teams_remove_member(team_id: ApiInt, member_user_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    is_admin = int(ctx.tg_id) in ADMIN_IDS
    try:
        await remove_team_member(int(team_id), int(ctx.user_id), int(member_user_id), actor_is_admin=is_admin)
    except ValueError as exc:
        detail = str(exc)
        if detail == 'not_team_captain':
            raise HTTPException(status_code=403, detail=detail) from exc
        if detail in {'member_not_found', 'cannot_remove_self'}:
            raise HTTPException(status_code=400, detail=detail) from exc
        raise HTTPException(status_code=400, detail='remove_member_failed') from exc
    return {'ok': True}


@app.post('/teams/{team_id}/members/{member_user_id}/role')
@_validate_payload_input
async def teams_set_member_role(
    team_id: ApiInt,
    member_user_id: ApiInt,
    payload: dict = Body(default_factory=dict),
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    is_admin = int(ctx.tg_id) in ADMIN_IDS
    role = str(payload.get('role') or '').strip().lower()
    try:
        await set_team_member_role(int(team_id), int(ctx.user_id), int(member_user_id), role, actor_is_admin=is_admin)
    except ValueError as exc:
        detail = str(exc)
        if detail == 'not_team_captain':
            raise HTTPException(status_code=403, detail=detail) from exc
        if detail in {'member_not_found', 'invalid_role', 'captain_role_locked'}:
            raise HTTPException(status_code=400, detail=detail) from exc
        raise HTTPException(status_code=400, detail='set_member_role_failed') from exc
    return {'ok': True}


@app.get('/teams/requests')
async def teams_requests(
    q: str | None = None,
    limit: ApiInt = 50,
    offset: ApiInt = 0,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    me_team = await get_user_team(int(ctx.user_id))
    if not me_team or me_team.get('role') != 'captain':
        raise HTTPException(status_code=403, detail='captain_only')
    safe_limit = max(1, min(int(limit or 50), 100))
    safe_offset = max(0, int(offset or 0))
    items, total = await list_team_requests(
        int(me_team['team_id']),
        status='pending',
        q=q,
        limit=safe_limit,
        offset=safe_offset,
    )
    return {'items': items, 'total': int(total), 'limit': safe_limit, 'offset': safe_offset}


@app.get('/teams/requests/count')
async def teams_requests_count(ctx: AuthCtx = Depends(get_auth_ctx)):
    me_team = await get_user_team(int(ctx.user_id))
    if not me_team or me_team.get('role') != 'captain':
        return {'count': 0}
    count = await count_team_pending_requests(int(me_team['team_id']))
    return {'count': int(count)}


@app.post('/teams/requests/{request_id}/accept')
async def teams_requests_accept(request_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    me_team = await get_user_team(int(ctx.user_id))
    if not me_team or me_team.get('role') != 'captain':
        raise HTTPException(status_code=403, detail='captain_only')
    try:
        await accept_team_request(int(request_id), int(ctx.user_id))
    except ValueError as exc:
        detail = str(exc)
        if detail == 'not_team_captain':
            raise HTTPException(status_code=403, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return {'ok': True}


@app.post('/teams/requests/{request_id}/reject')
async def teams_requests_reject(request_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    me_team = await get_user_team(int(ctx.user_id))
    if not me_team or me_team.get('role') != 'captain':
        raise HTTPException(status_code=403, detail='captain_only')
    try:
        await reject_team_request(int(request_id), int(ctx.user_id))
    except ValueError as exc:
        detail = str(exc)
        if detail == 'not_team_captain':
            raise HTTPException(status_code=403, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    return {'ok': True}


@app.get('/teams/leaderboard')
async def teams_leaderboard(
    limit: ApiInt = 10,
    offset: ApiInt = 0,
    ctx: AuthCtx = Depends(get_auth_ctx),
):
    safe_limit = max(1, min(int(limit or 10), 50))
    safe_offset = max(0, int(offset or 0))
    page, total, full = await fetch_team_leaderboard(limit=safe_limit, offset=safe_offset)

    day_utc = datetime.now(UTC).date().isoformat()
    top_for_snapshot = full[:50]
    await upsert_team_daily_scores(day_utc, top_for_snapshot)

    newly_unlocked_map: dict[int, list[str]] = {}
    me_team = await get_user_team(int(ctx.user_id))
    my_team_id = int(me_team['team_id']) if me_team else None
    # Only evaluate teams needed by this response; keep ranking history for the full top.
    evaluation_ids = {int(item['team_id']) for item in page}
    if my_team_id:
        evaluation_ids.add(my_team_id)
    for team_id in sorted(evaluation_ids):
        eval_payload = await evaluate_team(team_id)
        newly = [str(c) for c in eval_payload.get('newly_unlocked_team_codes', [])]
        if newly:
            newly_unlocked_map[team_id] = newly

    my_item = next((item for item in full if my_team_id and int(item['team_id']) == my_team_id), None)

    my_allowed = None
    if my_team_id:
        earned = set(await list_team_achievements(my_team_id))
        my_allowed = team_style_options_for_codes(earned)

    pending_request_team_ids: set[int] = set()
    if not my_team_id:
        for item in page:
            team_id = int(item['team_id'])
            if await has_pending_join_request(team_id, int(ctx.user_id)):
                pending_request_team_ids.add(team_id)

    items = []
    for item in page:
        team_id = int(item['team_id'])
        frame_code = item.get('frame_code')
        bg_code = item.get('bg_code')
        emblem_code = item.get('emblem_code')
        if my_team_id and team_id == my_team_id and my_allowed is not None:
            if frame_code not in my_allowed['allowed_frames']:
                frame_code = None
            if bg_code not in my_allowed['allowed_bgs']:
                bg_code = None
            if emblem_code not in my_allowed['allowed_emblems']:
                emblem_code = None

        items.append(
            {
                'rank': int(item['rank']),
                'team_id': team_id,
                'name': item['name'],
                'score': int(item['score']),
                'members_count': int(item['members_count']),
                'active_members_7d': int(item['active_members_7d']),
                'sessions_7': int(item['sessions_7']),
                'sessions_28': int(item['sessions_28']),
                'avg_member_score': int(item['avg_member_score']),
                'consistency_score': int(item['consistency_score']),
                'engagement_score': int(item['engagement_score']),
                'completion_score': int(item['completion_score']),
                'variety_score': int(item['variety_score']),
                'progression_score': int(item['progression_score']),
                'frame_code': frame_code,
                'bg_code': bg_code,
                'emblem_code': emblem_code,
                'is_open': bool(item.get('is_open')),
                'join_policy': _team_join_policy(item),
                'join_action': _team_join_action_for_viewer(
                    team_like=item,
                    me_team=me_team,
                    has_pending_request=(team_id in pending_request_team_ids),
                ),
                'has_pending_request': team_id in pending_request_team_ids,
            }
        )

    response = {
        'items': items,
        'total': int(total),
        'limit': safe_limit,
        'offset': safe_offset,
        'my_team_rank': int(my_item['rank']) if my_item else None,
        'my_team_score': int(my_item['score']) if my_item else None,
        'my_team_id': my_team_id,
    }
    if newly_unlocked_map:
        response['teams_newly_unlocked'] = newly_unlocked_map
    return response


@app.get('/teams/style/options')
async def teams_style_options(ctx: AuthCtx = Depends(get_auth_ctx)):
    me_team = await get_user_team(int(ctx.user_id))
    if not me_team or me_team.get('role') != 'captain':
        raise HTTPException(status_code=403, detail='captain_only')

    team_id = int(me_team['team_id'])
    await evaluate_team(team_id)
    earned = set(await list_team_achievements(team_id))
    allowed_raw = team_style_options_for_codes(earned)
    allowed = {
        'frames': allowed_raw['allowed_frames'],
        'bgs': allowed_raw['allowed_bgs'],
        'emblems': allowed_raw['allowed_emblems'],
    }

    frame_code = me_team.get('frame_code') if me_team.get('frame_code') in allowed['frames'] else None
    bg_code = me_team.get('bg_code') if me_team.get('bg_code') in allowed['bgs'] else None
    emblem_code = me_team.get('emblem_code') if me_team.get('emblem_code') in allowed['emblems'] else None

    return {
        'team_id': team_id,
        'current': {
            'frame_code': frame_code,
            'bg_code': bg_code,
            'emblem_code': emblem_code,
        },
        'allowed': allowed,
        'team_achievements': [
            {
                'code': item.code,
                'title': item.title,
                'icon': item.icon,
                'rarity': item.rarity,
                'unlocked': item.code in earned,
                'unlocked_at': None,
                'secret': bool(item.secret),
                'team_frame_code': item.team_frame_code,
                'team_bg_code': item.team_bg_code,
                'team_emblem_code': item.team_emblem_code,
            }
            for item in TEAM_ACHIEVEMENTS
        ],
    }


@app.post('/teams/style')
@_validate_payload_input
async def teams_style(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    me_team = await get_user_team(int(ctx.user_id))
    if not me_team or me_team.get('role') != 'captain':
        raise HTTPException(status_code=403, detail='captain_only')

    def _normalize_style(v):
        if v is None:
            return None
        sv = str(v).strip()
        return sv if sv else None

    team_id = int(me_team['team_id'])
    frame_code = _normalize_style(payload.get('frame_code'))
    bg_code = _normalize_style(payload.get('bg_code'))
    emblem_code = _normalize_style(payload.get('emblem_code'))

    earned = set(await list_team_achievements(team_id))
    if not is_team_style_allowed(earned, frame_code, bg_code, emblem_code):
        raise HTTPException(status_code=403, detail='style_not_unlocked')

    await set_team_style(
        team_id,
        int(ctx.user_id),
        frame_code,
        bg_code,
        emblem_code,
    )
    return {
        'ok': True,
        'current': {
            'frame_code': frame_code,
            'bg_code': bg_code,
            'emblem_code': emblem_code,
        },
    }


@app.get('/teams/{team_id}')
async def teams_profile(team_id: ApiInt, ctx: AuthCtx = Depends(get_auth_ctx)):
    is_admin = int(ctx.tg_id) in ADMIN_IDS
    profile = await fetch_team_profile(int(team_id), int(ctx.user_id), include_members_for_admin=is_admin)
    if not profile:
        raise HTTPException(status_code=404, detail='team_not_found')

    team = profile['team']
    members = profile.get('members')

    earned = set(await list_team_achievements(int(team['team_id'])))
    allowed = team_style_options_for_codes(earned)
    frame_code = team.get('frame_code') if team.get('frame_code') in allowed['allowed_frames'] else None
    bg_code = team.get('bg_code') if team.get('bg_code') in allowed['allowed_bgs'] else None
    emblem_code = team.get('emblem_code') if team.get('emblem_code') in allowed['allowed_emblems'] else None

    has_pending_request = False
    me_team = await get_user_team(int(ctx.user_id))
    if not me_team:
        has_pending_request = await has_pending_join_request(int(team['team_id']), int(ctx.user_id))

    return {
        'viewer_has_team': bool(me_team),
        'team': {
            'rank': int(team['rank']),
            'team_id': int(team['team_id']),
            'name': team['name'],
            'score': int(team['score']),
            'members_count': int(team['members_count']),
            'active_members_7d': int(team['active_members_7d']),
            'sessions_7': int(team['sessions_7']),
            'sessions_28': int(team['sessions_28']),
            'avg_member_score': int(team['avg_member_score']),
            'frame_code': frame_code,
            'bg_code': bg_code,
            'emblem_code': emblem_code,
            'is_open': bool(team.get('is_open')),
            'join_policy': _team_join_policy(team),
            'join_action': _team_join_action_for_viewer(
                team_like=team,
                me_team=me_team,
                has_pending_request=bool(has_pending_request),
            ),
            'has_pending_request': bool(has_pending_request),
        },
        'members': members,
    }


@app.get('/leaderboard/productivity/{leader_user_id}/plan')
async def leaderboard_productivity_plan(
    leader_user_id: ApiInt,
    system_id: ApiInt | None = None,
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
    is_premium = await _has_active_subscription(int(leader_user_id))
    unlocked_rows = await list_user_achievements(int(leader_user_id))
    unlocked = [code for code, _ in unlocked_rows]
    unlocked_icons = [
        {
            'code': code,
            'icon': achievements.ACHIEVEMENTS_BY_CODE[code].icon,
            'title': achievements.ACHIEVEMENTS_BY_CODE[code].title,
            'unlocked_at': ts,
        }
        for code, ts in unlocked_rows
        if code in achievements.ACHIEVEMENTS_BY_CODE
    ][:8]
    cosmetics = await get_cosmetics(int(leader_user_id))
    selected_badge_icon = None
    if is_premium and cosmetics.get('badge_code') and not bool(cosmetics.get('badge_hidden')):
        ach = achievements.ACHIEVEMENTS_BY_CODE.get(str(cosmetics.get('badge_code')))
        selected_badge_icon = ach.icon if ach else None
    return {
        'leader_user_id': int(leader_user_id),
        'system_id': int(selected.get('system_id')) if selected else None,
        'days': plan_days,
        'systems': systems,
        'is_premium': bool(is_premium),
        'selected_badge_icon': selected_badge_icon,
        'unlocked_icons': unlocked_icons,
        'unlocked_codes': unlocked,
    }


@app.post('/leaderboard/productivity/{leader_user_id}/copy')
@_validate_payload_input
async def leaderboard_productivity_copy(
    leader_user_id: ApiInt,
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
    previous_system_id = await get_active_training_system_id(int(user_id))
    try:
        result = await copy_training_system_from_user(
            int(leader_user_id),
            int(user_id),
            source_system_id,
            fallback_system_name=fallback_name,
        )
    except ValueError as exc:
        if str(exc) == 'system_not_found':
            raise HTTPException(status_code=404, detail='Система для копирования не найдена') from exc
        raise
    if not result.get('system_id'):
        raise HTTPException(status_code=400, detail='У лидера нет системы для копирования')
    await clone_system_cosmetics(int(user_id), previous_system_id, int(result.get('system_id')))
    await record_system_copy(int(leader_user_id), int(result.get('source_system_id') or source_system_id or 0), int(user_id), int(result.get('system_id')) )
    await _evaluate_achievements(int(leader_user_id))
    await _evaluate_achievements(int(user_id))
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
        'supports_web_payment': _has_yookassa_redirect_config(),
        'project_key': PROJECT_KEY,
    }


@app.post('/subscription/payment/start')
@_validate_payload_input
async def subscription_payment_start(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    plan_code = str(payload.get('plan_code') or '').strip()
    if plan_code not in SUBSCRIPTION_PLANS:
        raise HTTPException(status_code=400, detail='Неизвестный тариф')
    payment_method = _resolve_payment_method(payload.get('payment_method'))

    if payment_method == 'stars':
        payment_id, confirmation_url, _plan = await _create_telegram_subscription_invoice_link(
            user_id, plan_code, payment_method='stars'
        )
    else:
        payment_id, confirmation_url, _plan = await _create_subscription_redirect_payment(
            user_id,
            plan_code,
            return_url=_resolve_payment_return_url(),
        )
    return {
        'ok': True,
        'payment_id': payment_id,
        'confirmation_url': confirmation_url,
    }


def _purchased_subscription_plan(record: dict) -> tuple[str, dict]:
    payload = record.get('payload') or {}
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    code = str(payload.get('plan_id') or payload.get('plan') or payload.get('plan_code') or metadata.get('plan_id') or metadata.get('plan') or '')
    plan = SUBSCRIPTION_PLANS.get(code)
    if not plan:
        raise HTTPException(status_code=409, detail='Не удалось определить оплаченный тариф')
    return code, plan


@app.get('/subscription/payment/{payment_id}/status')
async def subscription_payment_status(payment_id: str, ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    record = await db.get_payment_by_external_id(payment_id)
    if not record or int(record.get('user_id') or 0) != user_id:
        raise HTTPException(status_code=404, detail='Платёж не найден')

    provider = str(record.get('provider') or '')
    if provider == 'telegram':
        status = str(record.get('status') or '')
        if status in {'paid', 'paid_invoice'}:
            status = 'succeeded'
        # Telegram's successful_payment handler grants the subscription once per charge.
        # Polling an invoice must never grant those days again.
        subscription = await db.get_active_subscription(user_id) if status == 'succeeded' else None
        expires = subscription.get('expires_at') if subscription else None
        return {'ok': True, 'status': status, 'activated': False, 'expires_at': expires.isoformat() if expires else None}
    else:
        data = await _yookassa_get_payment(payment_id)
        status = str(data.get('status') or '')
        await db.update_payment_status(payment_id, status, data)

    activated = False
    expires_at_iso = None
    if status == 'succeeded':
        plan_code, plan = _purchased_subscription_plan(record)
        result = await db.finalize_payment_subscription_idempotent(
            external_id=payment_id,
            user_id=user_id,
            expected_project_key=PROJECT_KEY,
            days=int(plan['days']),
            plan_code=plan_code,
            source='subscription_payment_status',
        )
        if not result.get('ok'):
            raise HTTPException(status_code=409, detail='Не удалось финализировать платёж')
        expires = result.get('expires_at')
        expires_at_iso = expires.isoformat() if expires else None
        activated = not bool(result.get('already_finalized'))

    return {'ok': True, 'status': status, 'activated': activated, 'expires_at': expires_at_iso}


@app.post('/api/payments/redirect/create')
@_validate_payload_input
async def payment_redirect_create(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    kind = str(payload.get('kind') or '').strip().lower()
    plan_id = str(payload.get('plan_id') or '').strip()
    if kind != 'subscription':
        raise HTTPException(status_code=400, detail='Поддерживается только kind=subscription')
    payment_id, confirmation_url, plan = await _create_subscription_redirect_payment(
        int(ctx.user_id),
        plan_id,
        return_url=_resolve_payment_return_url(),
    )
    return {
        'ok': True,
        'payment_id': payment_id,
        'confirmation_url': confirmation_url,
        'amount_rub': int(plan['amount_rub']),
        'title': plan['title'],
        'project_key': PROJECT_KEY,
    }


@app.get('/api/payments/yookassa/status')
async def payment_yookassa_status(payment_id: str, ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = int(ctx.user_id)
    record = await db.get_payment_by_external_id(payment_id)
    if not record or int(record.get('user_id') or 0) != user_id:
        raise HTTPException(status_code=404, detail='Платёж не найден')

    status = str(record.get('status') or '')
    provider = str(record.get('provider') or '')
    if provider != 'yookassa':
        raise HTTPException(status_code=400, detail='Неверный провайдер платежа')

    data = await _yookassa_get_payment(payment_id)
    status = str(data.get('status') or status)
    await db.update_payment_status(payment_id, status, data)

    result = {
        'ok': True,
        'status': status,
        'project_key': str(record.get('project_key') or ''),
        'activated': False,
        'already_finalized': False,
        'expires_at': None,
    }
    if status != 'succeeded':
        return result

    plan_code, plan = _purchased_subscription_plan(record)
    finalize = await db.finalize_payment_subscription_idempotent(
        external_id=payment_id,
        user_id=user_id,
        expected_project_key=PROJECT_KEY,
        days=int(plan['days']),
        plan_code=plan_code,
        source='api_payments_yookassa_status',
    )
    if not finalize.get('ok'):
        raise HTTPException(status_code=409, detail='Не удалось финализировать платёж')
    expires = finalize.get('expires_at')
    result['activated'] = not bool(finalize.get('already_finalized'))
    result['already_finalized'] = bool(finalize.get('already_finalized'))
    result['expires_at'] = expires.isoformat() if expires else None
    return result


@app.post('/subscription/payment/notify-bot-success')
async def subscription_payment_notify_bot_success(ctx: AuthCtx = Depends(get_auth_ctx)):
    if not TG_TOKEN:
        return {'ok': False, 'sent': False}
    user_info = await find_user_by_id(int(ctx.user_id))
    if not user_info:
        return {'ok': False, 'sent': False}
    try:
        tg_user_id = int(user_info[1])
    except Exception:
        return {'ok': False, 'sent': False}

    text = (
        '🎉 Подписка успешно активирована!\n\n'
        'Теперь у вас доступны:\n'
        '• AI-функции для прогресса и корректировок;\n'
        '• Создание собственной команды;\n'
        '• Неограниченное количество тренировочных систем;\n'
        '• Отключение рекламных рассылок.\n\n'
        'Откройте главное меню и продолжайте тренировку 💪'
    )
    try:
        bot = Bot(token=TG_TOKEN)
        await bot.send_message(
            chat_id=tg_user_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton('Открыть главное меню', callback_data='menu:root')]]
            ),
        )
    except Exception:
        logger.exception('Failed to send post-payment bot message for user_id=%s', ctx.user_id)
        return {'ok': False, 'sent': False}
    return {'ok': True, 'sent': True}


@app.post('/systems/resolve_limit')
@_validate_payload_input
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


def _build_fallback_new_system_plan(parsed_root: dict | None) -> dict | None:
    if not isinstance(parsed_root, dict):
        return None
    raw_days = parsed_root.get('days')
    if not isinstance(raw_days, list):
        return None
    clean_days: list[dict] = []
    for item in raw_days:
        if not isinstance(item, dict):
            continue
        exercises = item.get('exercises')
        if not isinstance(exercises, list) or not exercises:
            continue
        clean_days.append({
            'day_index': int(item.get('day_index') or 0),
            'title': str(item.get('title') or '').strip(),
            'exercises': exercises,
        })
    if not clean_days:
        return None
    return {
        'actions': [{
            'type': 'create_system',
            'system_name': str(parsed_root.get('system_name') or 'Система от ИИ').strip() or 'Система от ИИ',
            'days': clean_days,
            'reason': str(parsed_root.get('reason') or '').strip(),
        }]
    }


def _format_ai_quota_reset_at(reset_at: str | None, tz_name: str | None) -> str:
    dt = _parse_iso_datetime(reset_at)
    if dt is None:
        return ''
    zone_name = tz_name or 'UTC'
    try:
        zone = ZoneInfo(zone_name)
    except Exception:
        zone = ZoneInfo('UTC')
    local_dt = dt.astimezone(zone)
    return local_dt.strftime('%d.%m.%Y %H:%M')


@app.get('/ai/coach/apply/{request_id}')
async def ai_coach_apply_status(request_id: str, ctx: AuthCtx = Depends(get_auth_ctx)):
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id):
        raise HTTPException(status_code=400, detail='invalid_request_id')
    raw = await db.get_app_meta(f'ai_apply:{ctx.user_id}:{request_id}')
    if not raw:
        return {'found': False}
    saved = json.loads(raw)
    return {'found': True, 'result': saved['result']}


@app.post('/ai/coach/apply')
@_validate_payload_input
async def ai_coach_apply(payload: dict = Body(...), ctx: AuthCtx = Depends(get_auth_ctx)):
    if not await db.get_active_subscription(ctx.user_id):
        raise HTTPException(status_code=403, detail='AI доступен только при активной подписке')
    request_id = str(payload.get('request_id') or '')
    system_id = _to_int(payload.get('system_id'))
    raw_actions = payload.get('actions')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id) or system_id <= 0:
        raise HTTPException(status_code=400, detail='Неверный идентификатор операции или системы')
    if not isinstance(raw_actions, list) or not 1 <= len(raw_actions) <= 60:
        raise HTTPException(status_code=400, detail='Пустой или слишком большой план')
    actions = []
    for raw in raw_actions:
        clean = _sanitize_ai_action(raw, max_day_index=7)
        if clean is None:
            raise HTTPException(status_code=400, detail='Некорректное действие плана')
        if clean['type'] == 'create_system':
            days = raw.get('days')
            if len(raw_actions) != 1 or not isinstance(days, list) or not 1 <= len(days) <= 7 or len(days) != len(clean['days']):
                raise HTTPException(status_code=400, detail='Некорректные дни программы')
            expected = _to_int(payload.get('expected_days'))
            if expected and expected != len(days):
                raise HTTPException(status_code=400, detail='Количество дней не совпадает с запросом')
            by_day = {d['day_index']: d for d in clean['days']}
            for day in days:
                normalized = by_day.get(_to_int(day.get('day_index')))
                exercises = day.get('exercises')
                if normalized is None or not isinstance(exercises, list) or not 1 <= len(exercises) <= 40 or len(exercises) != len(normalized['exercises']):
                    raise HTTPException(status_code=400, detail='Некорректные упражнения программы')
                names = [e['exercise_name'].casefold() for e in normalized['exercises']]
                if len(names) != len(set(names)):
                    raise HTTPException(status_code=400, detail='Упражнение повторяется в одном дне')
        elif _to_int(raw.get('day_index')) != clean['day_index']:
            raise HTTPException(status_code=400, detail='Некорректный день программы')
        actions.append(clean)
    try:
        return await db.apply_ai_training_plan(ctx.user_id, system_id, request_id, actions)
    except ValueError as exc:
        details = {
            'system_changed': 'Система изменилась. Запросите новое предложение ИИ.',
            'request_conflict': 'Этот запрос уже использован для другого плана.',
            'exercise_not_found': 'Упражнение изменилось или удалено. Обновите предложение ИИ.',
            'day_not_active': 'День тренировки больше не активен. Обновите предложение ИИ.',
        }
        raise HTTPException(status_code=409, detail=details.get(str(exc), 'Некорректный план')) from exc


@app.post('/ai/coach/query')
@_validate_payload_input
async def ai_coach_query(payload: dict = Body(default_factory=dict), ctx: AuthCtx = Depends(get_auth_ctx)):
    user_id = ctx.user_id
    sub = await db.get_active_subscription(user_id)
    if not sub:
        raise HTTPException(status_code=403, detail='AI доступен только при активной подписке')

    mode = str(payload.get('mode') or 'mistakes_analysis').strip()
    user_message = _clip_text(str(payload.get('message') or '').strip(), 1800)
    if mode not in {'replace_exercises', 'new_system', 'mistakes_analysis'}:
        raise HTTPException(status_code=400, detail='Неподдерживаемый AI-режим')
    if mode in {'replace_exercises', 'new_system'} and not user_message:
        raise HTTPException(status_code=400, detail='Опиши, что хочешь улучшить')

    timezone = await get_user_timezone(user_id)
    quota_state = await consume_ai_coach_quota(user_id, mode, reserve=True)
    if not quota_state.get('ok'):
        blocked_scope = str(quota_state.get('blocked_scope') or 'day')
        detail = 'Извините, вы превысили количество допустимых запросов за сегодня.'
        if blocked_scope == 'week':
            detail = 'Извините, вы превысили количество допустимых запросов в неделю.'
        elif blocked_scope == 'month':
            reset_text = _format_ai_quota_reset_at(quota_state.get('reset_at'), timezone)
            detail = 'Извините, вы превысили количество допустимых запросов в месяц.'
            if reset_text:
                detail += f' Следующий доступ: {reset_text}.'
        raise HTTPException(status_code=429, detail=detail)

    completed = False
    try:
        result = await _run_ai_coach_query(user_id, mode, user_message, payload, quota_state, include_progressor=not ctx.is_acting)
        if result.get('ok'):
            await db.complete_ai_coach_quota(user_id, quota_state['request_id'])
            completed = True
        return result
    finally:
        if not completed:
            await db.release_ai_coach_quota(user_id, quota_state['request_id'])


async def _run_ai_coach_query(user_id: int, mode: str, user_message: str, payload: dict, quota_state: dict, *, include_progressor: bool = False):
    rejected_variants = payload.get('rejected_variants')
    rejected_list: list[str] = []
    if isinstance(rejected_variants, list):
        for item in rejected_variants[:3]:
            text = _clip_text(str(item or '').strip(), 350)
            if text:
                rejected_list.append(text)

    requested_days = _extract_requested_workout_days(user_message) if mode == "new_system" else None

    context_payload = await _build_ai_context_payload(user_id)
    catalog_context = context_payload.get('catalog_context') or {}

    # компактный контекст: без каталога, без простыней
    ctx = {
        'mode': mode,
        'user_message': user_message or '',
        'rejected_variants': rejected_list,
        'user_profile': context_payload.get('user_profile') or {},
        'active_system_id': context_payload.get('active_system_id'),
        'active_system_name': context_payload.get('active_system_name'),
        'measurement_trends': (context_payload.get('measurement_trends') or [])[-3:],
        'current_plan': context_payload.get('day_snapshots') or [],
        'muscle_groups': (catalog_context.get('groups') or []),
    }

    from progressor_client import ai_context
    shared_context = None
    if include_progressor:
        # A native Gym trainer link covers Gym only; it grants no Food/Supply data access.
        async with db.connect_db() as connection:
            identity = await (await connection.execute("SELECT tg_id FROM users WHERE id=?", (user_id,))).fetchone()
        shared_context = await ai_context("gym", identity[0]) if identity else None
    if shared_context: ctx["progressor_context"] = shared_context
    context_text = json.dumps(ctx, ensure_ascii=False)
    user_prompt = (
        'Используй этот контекст (JSON) и сформируй ответ по схеме:\\n'
        + context_text
    )

    # --- OpenAI call (mode-aware) ---
    system_prompt = _build_ai_system_prompt(mode, requested_days=requested_days)
    result = await _call_openai_chat(system_prompt, user_prompt, mode=mode, requested_days=requested_days)

    # --- Parse structured root ---
    parsed_root = None
    if isinstance(result, dict):
        parsed_root = result.get("parsed")

    if not isinstance(parsed_root, dict):
        # fallback на старый путь
        raw_text = (result.get("text") if isinstance(result, dict) else "") or ""
        parsed_root = _extract_json_block(raw_text) or {}

    if not parsed_root:
        raise HTTPException(status_code=502, detail='ИИ вернул пустой ответ. Попытка не списана.')

    parsed_action_plan = parsed_root.get("action_plan") if isinstance(parsed_root.get("action_plan"), dict) else {"actions": []}
    if mode == "new_system" and not (parsed_action_plan.get("actions") if isinstance(parsed_action_plan, dict) else None):
        fallback_plan = _build_fallback_new_system_plan(parsed_root)
        if fallback_plan:
            parsed_action_plan = fallback_plan

    sanitized_plan, plan_warnings = _sanitize_ai_action_plan(
        parsed_action_plan,
        mode,
        workouts_per_week=_to_int((context_payload.get("user_profile") or {}).get("workouts_per_week"), 0),
        active_day_count=len(context_payload.get("day_snapshots") or []),
        requested_days=requested_days,
    )
    if mode == "new_system" and requested_days and not (sanitized_plan.get("actions") if isinstance(sanitized_plan, dict) else []):
        if any(isinstance(w, dict) and w.get("code") == "days_count_mismatch" for w in plan_warnings):
            retry_prompt = user_prompt + f"\n\nВНИМАНИЕ: Ты вернул неверное число дней. Верни строго {requested_days} дней в create_system.days."
            retry_result = await _call_openai_chat(system_prompt, retry_prompt, mode=mode, requested_days=requested_days)
            retry_root = retry_result.get("parsed") if isinstance(retry_result, dict) else {}
            retry_plan = retry_root.get("action_plan") if isinstance(retry_root, dict) and isinstance(retry_root.get("action_plan"), dict) else {"actions": []}
            sanitized_plan, plan_warnings = _sanitize_ai_action_plan(
                retry_plan, mode,
                workouts_per_week=_to_int((context_payload.get("user_profile") or {}).get("workouts_per_week"), 0),
                active_day_count=len(context_payload.get("day_snapshots") or []),
                requested_days=requested_days,
            )
            if (sanitized_plan.get("actions") if isinstance(sanitized_plan, dict) else []):
                parsed_root = retry_root if isinstance(retry_root, dict) else parsed_root

    summary = str(parsed_root.get("summary") or "").strip()
    rationale = parsed_root.get("rationale")
    if not isinstance(rationale, list):
        rationale = []
    rationale = [str(x).strip() for x in rationale if str(x).strip()][:6]

    if mode == "mistakes_analysis":
        # гарантируем нулевые actions
        sanitized_plan = {"actions": []}
        plan_warnings = []
        fallback_summary, fallback_rationale = _build_mistakes_analysis_fallback(context_payload, user_message)
        if len(summary) < 120:
            summary = fallback_summary
        if len(rationale) < 3:
            rationale = fallback_rationale

    answer_text = ""
    if isinstance(result, dict):
        answer_text = str(result.get("text") or "").strip()
    if mode == "new_system" and requested_days and not (sanitized_plan.get("actions") if isinstance(sanitized_plan, dict) else []):
        mismatch = next((w for w in (plan_warnings or []) if isinstance(w, dict) and w.get("code") == "days_count_mismatch"), None)
        if mismatch:
            return {
                "ok": False,
                "code": "AI_DAYS_COUNT_MISMATCH",
                "detail": f"ИИ вернул {mismatch.get('actual')} день(дней) вместо {mismatch.get('expected')}. Система не применена.",
                "expected_days": requested_days,
                "action_plan_warnings": plan_warnings,
            }

    if mode != 'mistakes_analysis' and not sanitized_plan.get('actions'):
        raise HTTPException(status_code=502, detail='ИИ не вернул применимый план. Попытка не списана.')

    return {
        "ok": True,
        "mode": mode,
        "quota": {
            "daily_remaining": int(((quota_state.get("remaining") or {}).get("day") or 0)),
            "daily_limit": int(((quota_state.get("limits") or {}).get("day") or 3)),
        },
        "answer_text": answer_text,
        "summary": summary,
        "rationale": rationale,
        "parsed_action_plan": sanitized_plan,
        "action_plan_warnings": plan_warnings,
        "context_preview": context_text,
        "context_sources": shared_context["sources"] if shared_context else [],
        "model": get_openai_model(),
        "requested_days": requested_days,
        "expected_days": requested_days,
    }
