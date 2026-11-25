import asyncio
import contextlib
import logging
import json
import math
import random
import secrets
import os
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from datetime import datetime as _dt, timedelta as _td
from html import escape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfo as _Z
from collections import defaultdict
from types import SimpleNamespace
from typing import Any, Sequence, TYPE_CHECKING
import re
from telegram import (
    Update,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    LabeledPrice,
    CopyTextButton,
    WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.error import (
    BadRequest,
    Forbidden,
    RetryAfter,
    TimedOut,
    NetworkError,
    TelegramError,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    AIORateLimiter,
    MessageHandler,
    filters,
    PreCheckoutQueryHandler,
    Defaults,
)
try:
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
except ModuleNotFoundError as exc:  # pragma: no cover - defensive dependency check
    raise SystemExit(
        "APScheduler is required for reminder notifications. "
        "Install project dependencies with `pip install -r requirements.txt` "
        "or `pip install \"python-telegram-bot[job-queue]\" APScheduler`"
    ) from exc
from keyboards import (
    dual,
    main_menu_kb,
    muscle_groups_kb,
    exercises_kb,
    baseline_kb,
    baseline_scope,
    day_done_kb,
    reminders_kb,
    reminder_time_kb,
    tz_select_kb,
    reminders_edit_kb,
    reminders_schedule_kb,
    reminder_day_kb,
    WEEKDAYS,
    MG_NAMES,
    BACK_BTN,
    day_kb,
    day_group_kb,
    day_add_group_kb,
    day_remove_group_kb,
    day_add_exercises_kb,
    del_exercises_kb,
    exercise_actions_kb,
    settings_kb,
    settings_groups_kb,
    rename_day_kb,
    days_count_kb,
    confirm_settings_group_delete_kb,
    TIMEZONES,
    library_menu_kb,
    library_group_kb,
    library_manage_kb,
    library_add_group_kb,
    library_add_exercises_kb,
    library_delete_kb,
    confirm_library_group_delete_kb,
    measurements_main_kb,
    measurements_manage_overview_kb,
    measurements_category_kb,
    measurements_metric_kb,
    measurements_existing_kb,
    measurements_remove_kb,
    ui_footer_rows,
    HISTORY_BTN,
    channel_support_prompt_kb,
    trainee_trainer_settings_kb,
    trainee_become_kb,
    week_count_kb,
    reminder_prompt_kb,
    trainer_manage_trainee_kb,
    onboarding_tips_kb,
)
from settings import (
    TG_TOKEN,
    SUPPORT_DEEPLINK,
    TG_POOL_SIZE,
    JOIN_URL,
    ADMIN_IDS,
    PUBLIC_BASE_URL,
    WEBAPP_PUBLIC_PATH,
    SUBSCRIPTION_CHAT,
    BOT_PUBLIC_LINK,
    INSTRUCTION_URL,
)
from db import expire_stale_pending_payments as db_expire_stale_pending_payments
from db import (
    get_user_exercise_info,
    init_db,
    connect_db,
    get_or_create_user,
    get_or_create_today_session,
    get_session_for_day,
    get_active_training_system_id,
    peek_active_training_system_id,
    fetch_day_exercises,
    add_set,
    inc_last_set,
    fetch_user_settings,
    set_workouts_per_week,
    list_exercises_by_group,
    list_user_exercise_ids,
    add_user_exercise,
    toggle_user_exercise,
    get_or_create_exercise,
    list_day_exercises,
    set_baseline,
    set_user_timezone,
    get_user_notifications_enabled,
    set_user_notifications_enabled,
    add_user_reminder,
    normalize_dow,
    get_user_timezone,
    list_user_reminders,
    wipe_user,
    list_active_days,
    list_day_completions,
    get_last_completion_for_user,
    get_day_label,
    remove_user_exercise,
    get_exercise_info,
    get_baseline,
    fetch_exercise_sets,
    get_session_last_values,
    remove_last_set,
    mark_exercise_done,
    set_exercise_persistent_note,
    get_exercise_persistent_note,
    list_recent_progress,
    count_exercise_progress_entries,
    list_last_done_dates,
    rename_day,
    get_ui_preferences,
    set_ui_mode,
    set_ui_emoji_enabled,
    set_ui_verbose_level,
    get_webapp_prompt_suppressed,
    set_webapp_prompt_suppressed,
    fetch_last_session_sets,
    inc_specific_set,
    add_user_muscle_group,
    list_user_muscle_groups,
    remove_user_muscle_group,
    list_users_with_reminders,
    get_app_meta,
    copy_day_plan_to_other_days,
    ensure_library_history,
    list_library_groups,
    list_library_exercises,
    list_exercise_day_links,
    add_measurement_entry,
    update_last_measurement,
    delete_last_measurement,
    delete_custom_measurement,
    list_measurement_metrics,
    fetch_measurement_history,
    get_measurements_last_update,
    add_measurement_category,
    delete_measurement_category,
    list_measurement_categories,
    get_exercise_details,
    apply_sets_template,
    set_exercise_scheme,
    user_has_library_exercise,
    mark_day_completed,
    clear_day_completions,
    METCON_EXERCISE_NAMES,
    get_running_entry,
    update_running_entry,
    list_running_history,
    mark_running_entry_done,
    get_running_entry_by_id,
    add_custom_measurement,
    list_custom_measurements,
    cleanup_expired_subscriptions,
    get_active_subscription,
    grant_subscription_days,
    degrant_subscription_days,
    create_payment_record,
    get_payment_by_external_id,
    finalize_payment_subscription_idempotent,
    update_payment_status,
    list_exercise_weight_progress,
    clear_trainer_requests,
    count_trainer_requests,
    count_trainer_trainees,
    list_broadcast_targets,
    find_user_by_tg_id,
    find_user_by_id,
    find_user_by_trainer_code,
    get_latest_trainer_link_for_trainee,
    deactivate_trainer_links,
    reactivate_trainer_links,
    get_trainer_link,
    get_active_trainer_link_for_trainee,
    create_trainer_request,
    list_trainer_requests,
    list_trainer_trainees,
    update_trainer_link_status,
    update_trainer_link_permissions,
    update_trainer_label,
    update_trainee_label,
    set_trainer_accepting_requests,
    increment_day_finish_total,
    get_subscription_prompt_total,
    set_subscription_prompt_total,
    get_latest_subscription,
    fetch_global_stats,
    get_intro_video,
    set_intro_video,
    set_onboarding_video_message,
    get_onboarding_intro_message,
    set_onboarding_intro_message,
    clear_onboarding_intro_message,
    clear_onboarding_video_message,
    set_onboarding_completed,
    count_active_subscriptions,
    reset_ai_coach_quota,
    list_all_teams,
    delete_team,
    create_or_update_referral_profile,
    gift_code_stats,
    list_active_gift_codes,
    delete_gift_code,
    create_gift_code,
    redeem_gift_code_with_status,
    get_referral_profile,
    get_referrer_by_slug,
    assign_referral_attribution,
    mark_referral_first_seen,
    get_referral_stats,
    list_referral_profiles,
)
from text_utils import normalize_whitespace
from ui_texts import t, e, ONBOARDING_TIPS

# Последний message_id напоминания по chat_id (для удаления перед новым)
_REM_LAST_MSG: dict[int, int] = {}

if TYPE_CHECKING:
    from aiosqlite import Connection as Database
else:
    Database = Any

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://telegrambotsforeveryone.duckdns.org/gymapp/")


def build_webapp_payment_url(plan_code: str) -> str:
    base = str(PUBLIC_BASE_URL or "https://telegrambotsforeveryone.duckdns.org").rstrip("/")
    path = str(WEBAPP_PUBLIC_PATH or "/gymapp_prod").strip()
    if not path.startswith('/'):
        path = '/' + path
    app_url = f"{base}{path.rstrip('/')}/"
    parsed = urlparse(app_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({
        "screen": "payment",
        "kind": "subscription",
        "plan_id": str(plan_code),
        "payment_method": "rub",
        "source": "bot",
    })
    return urlunparse(parsed._replace(query=urlencode(query)))


def build_webapp_day_url(day_index: int | None) -> str:
    if not day_index:
        return WEBAPP_URL
    try:
        day_value = int(day_index)
    except (TypeError, ValueError):
        return WEBAPP_URL
    if day_value <= 0:
        return WEBAPP_URL
    try:
        parsed = urlparse(WEBAPP_URL)
    except Exception:
        return WEBAPP_URL
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["day_index"] = str(day_value)
    return urlunparse(parsed._replace(query=urlencode(query)))

user_locks = defaultdict(asyncio.Lock)
logger = logging.getLogger(__name__)
last_messages: dict[int, int] = {}
message_history: dict[int, list[int]] = defaultdict(list)
MAIL_RETURN_CALLBACK = "promo:return_menu"
PROGRESS_PAGE_SIZE = 5
DAY_SHEET_PAGE_SIZE = 6
SHEET_VIEWS_KEY = "day_sheet_views"
BROADCAST_STATE_KEY = "broadcast_state"
UTC = timezone.utc
SUBSCRIPTION_PAYMENT_KEY = "subscription_payment"
EXERCISE_NOTE_INPUT_KEY = "awaiting_exercise_note"
INTRO_AWAIT_KEY = "await_intro_video"
YK_PROVIDER = "yookassa"
STAR_RUB_RATE = 1.79
STAR_MARKUP = 1.10


RESOLVE_TARGET_USER_KEY = "resolved_target_user"

def plan_amount_stars(amount_rub: int | float) -> int:
    raw = (float(amount_rub) * STAR_MARKUP) / STAR_RUB_RATE
    return int(max(1, ((int(raw + 4.9999)) // 5) * 5))


SUBSCRIPTION_PLANS = {
    "1m": {
        "title": "Подписка на 1 месяц",
        "months": 1,
        "days": 30,
        "amount_rub": 199,
    },
    "6m": {
        "title": "Подписка на 6 месяцев",
        "months": 6,
        "days": 180,
        "amount_rub": 1190,
    },
    "12m": {
        "title": "Подписка на 12 месяцев",
        "months": 12,
        "days": 365,
        "amount_rub": 1990,
    },
}

DAY_COMPLETION_RETENTION_DAYS = 5
ORDINAL_WORDS = {
    1: "первая",
    2: "вторая",
    3: "третья",
    4: "четвёртая",
    5: "пятая",
    6: "шестая",
    7: "седьмая",
    8: "восьмая",
    9: "девятая",
    10: "десятая",
}
WEEKDAY_FULL_NAMES = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}
WEIGHT_ROUND_STEP = 0.5

AMRAP_EXERCISE_NAME = "Меткон — AMRAP (кастом)"
FOR_TIME_EXERCISE_NAME = "Меткон — For Time (кастом)"
FOR_TIME_METRIC = "wod_time_sec"
AMRAP_SCHEME_KEY = "awaiting_amrap_scheme"
FOR_TIME_INPUT_KEY = "awaiting_for_time_result"
TRAINER_CODE_INPUT_KEY = "awaiting_trainer_code"
TRAINER_CODE_PROMPT_KEY = "trainer_code_prompt"
TRAINER_PENDING_CAN_EDIT_KEY = "pending_trainer_can_edit"
TRAINER_LABEL_INPUT_KEY = "awaiting_trainer_label"
TRAINER_TRAINEE_LABEL_INPUT_KEY = "awaiting_trainee_label"
TRAINER_PENDING_OFFSET_KEY = "trainer_pending_offset"
TRAINER_ACCEPTED_OFFSET_KEY = "trainer_accepted_offset"
TRAINER_REQUESTS_VIEW_KEY = "trainer_requests_view"
TRAINER_SETTINGS_MESSAGE_KEY = "trainer_settings_message"
TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY = "trainer_trainee_settings_message"
TRAINER_LIST_LIMIT = 5
TRAINER_MAX_TRAINEES_FREE = 5
TRAINER_MAX_TRAINEES_SUB: int | None = None
REFERRAL_NAME_INPUT_KEY = "awaiting_referral_name"
REFERRAL_ADMIN_SEARCH_KEY = "awaiting_referral_admin_search"
GIFT_CODE_DAYS_INPUT_KEY = "awaiting_gift_code_days"
GIFT_CODE_INPUT_KEY = "awaiting_gift_code"
REFERRAL_ADMIN_PAGE_SIZE = 8


async def get_trainer_max_trainees(
    trainer_user_id: int, db: "Database | None" = None
) -> int | None:
    _ = db
    sub = await get_active_subscription(trainer_user_id)
    if sub:
        return TRAINER_MAX_TRAINEES_SUB
    return TRAINER_MAX_TRAINEES_FREE
RUNNING_GROUP = "run"
RUNNING_INPUT_KEY = "running_input"
RUNNING_HISTORY_PAGE_SIZE = 1

REMINDER_EDIT_POSITION_KEY = "reminder_edit_position"
REMINDER_EDIT_LABEL_KEY = "reminder_edit_label"
REMINDER_SELECTED_DOW_KEY = "reminder_selected_dow"
REMINDER_EDIT_DAY_INDEX_KEY = "reminder_edit_day_index"
REMINDER_TIME_PAGE_KEY = "reminder_time_page"
REMINDER_META_KEY = "reminders_updated_at"
_last_reminders_meta: str | None = None

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "\u23F0-\u23FA"
    "\u24C2"
    "\u25A0-\u25FF"
    "\u2B00-\u2BFF"
    "]"
)


@dataclass(frozen=True)
class UiPreferences:
    mode: str = "detailed"
    emoji_enabled: bool = True
    verbose_level: int = 0


@dataclass
class ExerciseView:
    text: str
    session_id: int
    exercise_id: int
    name: str
    group: str
    sets: list[tuple[int, int, float, int]]
    selected_set: int | None
    with_weight: bool
    kind: str
    is_amrap: bool
    is_for_time: bool
    has_history: bool
    running: dict | None = None


async def load_ui_preferences(user_id: int) -> UiPreferences:
    mode, emoji, verbose = await get_ui_preferences(user_id)
    if mode != "detailed":
        await set_ui_mode(user_id, "detailed")
        mode = "detailed"
    if not emoji:
        await set_ui_emoji_enabled(user_id, True)
        emoji = 1
    if verbose:
        await set_ui_verbose_level(user_id, 0)
        verbose = 0
    return UiPreferences(mode=mode, emoji_enabled=True, verbose_level=0)


def _parse_completion_rows(
    rows: list[tuple[int, str | None]]
) -> tuple[list[tuple[int, datetime]], datetime | None]:
    parsed: list[tuple[int, datetime]] = []
    latest: datetime | None = None
    for day, value in rows:
        if not value:
            continue
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        parsed.append((day, dt))
        if latest is None or dt > latest:
            latest = dt
    return parsed, latest


async def _active_system_id(user_id: int) -> int:
    try:
        sid = await peek_active_training_system_id(user_id)
        return int(sid or 0)
    except Exception:
        return 0


async def _prune_expired_day_completions(
    user_id: int, system_id: int, parsed: list[tuple[int, datetime]]
) -> list[tuple[int, datetime]]:
    if not parsed:
        return parsed
    tz_name = await get_user_timezone(user_id)
    zone = resolve_user_zone(tz_name)
    now_local_date = datetime.now(UTC).astimezone(zone).date()

    fresh: list[tuple[int, datetime]] = []
    for day, completed_at in parsed:
        completed_local_date = completed_at.astimezone(zone).date()
        age_days = (now_local_date - completed_local_date).days
        if age_days >= DAY_COMPLETION_RETENTION_DAYS:
            continue
        fresh.append((int(day), completed_at))

    # A read hides elapsed cycle marks without changing the saved diary.
    return fresh


async def _active_completion_rows(user_id: int, system_id: int) -> list[tuple[int, datetime]]:
    rows = await list_day_completions(user_id, system_id=system_id)
    parsed, _ = _parse_completion_rows(rows)
    parsed = await _prune_expired_day_completions(user_id, system_id, parsed)

    # Legacy completions were stored with system_id=0 before training systems were
    # introduced. Keep reading them as a fallback so restart/migration does not
    # immediately hide a recently completed day for existing users.
    if system_id != 0:
        legacy_rows = await list_day_completions(user_id, system_id=0)
        legacy_parsed, _ = _parse_completion_rows(legacy_rows)
        legacy_parsed = await _prune_expired_day_completions(user_id, 0, legacy_parsed)
        known_days = {day for day, _ in parsed}
        parsed.extend((day, completed_at) for day, completed_at in legacy_parsed if day not in known_days)
    return parsed


async def get_active_day_completions(user_id: int) -> set[int]:
    system_id = await _active_system_id(user_id)
    parsed = await _active_completion_rows(user_id, system_id)
    return {day for day, _ in parsed}


async def record_day_completion(user_id: int, day_index: int) -> tuple[set[int], bool]:
    if day_index not in {day for day, _ in await list_active_days(user_id)}:
        raise ValueError('day_not_available')
    system_id = await _active_system_id(user_id)
    parsed = await _active_completion_rows(user_id, system_id)
    now = datetime.now(UTC)
    already_tracked = any(day == day_index for day, _ in parsed)
    await mark_day_completed(user_id, day_index, now.isoformat(), system_id=system_id)
    current = {day for day, _ in parsed}
    current.add(day_index)
    return current, not already_tracked


def _resolve_subscription_chat(raw: str | int | None, default: int | str) -> int | str:
    if raw is None:
        return default
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return raw
    return default


def _is_active_channel_status(status) -> bool:
    if status is None:
        return False
    name = getattr(status, "value", status)
    return str(name) in {
        "administrator",
        "member",
        "creator",
        "owner",
        "restricted",
    }


async def _is_user_subscribed_to_channel(
    context: ContextTypes.DEFAULT_TYPE, tg_user_id: int
) -> bool:
    chat_id = _resolve_subscription_chat(SUBSCRIPTION_CHAT, "")
    if not chat_id:
        return False
    try:
        member = await context.bot.get_chat_member(chat_id, tg_user_id)
    except (BadRequest, Forbidden):
        return False
    except TelegramError:
        logger.exception("Failed to fetch chat member for subscription check")
        return False
    return _is_active_channel_status(getattr(member, "status", None))


def _channel_support_prompt_text(total: int) -> str:
    return (
        "Мы видим, что дневник помогает — вы завершили уже {total} тренировочных дней!\n"
        "Не хотите посмотреть наши другие проекты и поддержать авторов подпиской на канал?"
    ).format(total=total)


SUBSCRIPTION_PROMPT_DISABLED = -1


async def maybe_prompt_channel_support(
    q, context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> bool:
    total = await increment_day_finish_total(user_id)
    prompt_total = await get_subscription_prompt_total(user_id)
    if prompt_total == SUBSCRIPTION_PROMPT_DISABLED:
        return False
    if total - prompt_total < 5:
        return False
    active = await get_active_subscription(user_id)
    if active:
        await set_subscription_prompt_total(user_id, SUBSCRIPTION_PROMPT_DISABLED)
        return False
    tg_user = getattr(q, "from_user", None)
    tg_user_id = getattr(tg_user, "id", None)
    if tg_user_id is not None and await _is_user_subscribed_to_channel(context, tg_user_id):
        await set_subscription_prompt_total(user_id, SUBSCRIPTION_PROMPT_DISABLED)
        return False
    if not JOIN_URL:
        await set_subscription_prompt_total(user_id, total)
        return False
    message = getattr(q, "message", None)
    chat = getattr(message, "chat", None) if message else None
    chat_id = getattr(chat, "id", None) if chat else getattr(message, "chat_id", None)
    if chat_id is None:
        await set_subscription_prompt_total(user_id, total)
        return False
    markup = channel_support_prompt_kb(JOIN_URL)
    await set_subscription_prompt_total(user_id, total)
    await show_screen(
        q,
        context,
        _channel_support_prompt_text(total),
        markup,
        user_id,
        disable_web_page_preview=True,
    )
    return True


def format_reminder_cheer(done_count: int) -> str:
    if done_count <= 0:
        return "Самое время открыть первую тренировку недели!"
    next_no = done_count + 1
    if next_no == 2:
        return "Молодец, одна уже позади!"
    word = ORDINAL_WORDS.get(next_no, f"{next_no}-я")
    return f"Молодец, уже {word} тренировка на неделе!"


def emoji_for(prefs: UiPreferences, key: str) -> str:
    if not prefs.emoji_enabled:
        return ""
    return e(key)


def status_icon(prefs: UiPreferences, done: bool) -> str:
    if done:
        return emoji_for(prefs, "done")
    return ""


def maybe_hint(lines: list[str], prefs: UiPreferences, text: str | tuple[str, str]):
    """Append a hint respecting the chosen verbosity level."""

    short_text = ""
    full_text = ""
    if isinstance(text, tuple):
        short_text, full_text = text
    else:
        full_text = text
    if prefs.verbose_level:
        if full_text:
            lines.append(full_text)
    elif short_text:
        lines.append(short_text)


def build_main_menu_text(prefs: dict[str, Any] | UiPreferences | None = None) -> str:
    _ = prefs
    lines = [
        "Главное меню 💪",
        "",
        "Выбери тренировочный день ниже, чтобы отметить сегодняшнюю тренировку.",
    ]
    return "\n".join(lines)


def _format_days_ago(delta_days: int) -> str:
    if delta_days <= 0:
        return "сегодня"
    if delta_days == 1:
        return "1 день назад"
    if 2 <= delta_days <= 4:
        return f"{delta_days} дня назад"
    return f"{delta_days} дней назад"


def _find_next_reminder_time(
    reminders: list[tuple[int, object, object, object]],
    now_local: datetime,
    zone: ZoneInfo,
) -> datetime | None:
    next_dt: datetime | None = None
    for _, dow, hour, minute in reminders:
        if dow is None:
            continue
        try:
            dow_int = int(dow)
        except (TypeError, ValueError):
            continue
        try:
            hour_int = int(hour)
        except (TypeError, ValueError):
            hour_int = 0
        try:
            minute_int = int(minute)
        except (TypeError, ValueError):
            minute_int = 0
        offset = (dow_int - now_local.weekday()) % 7
        candidate_date = now_local.date() + timedelta(days=offset)
        candidate_time = time(hour_int, minute_int, tzinfo=zone)
        candidate_dt = datetime.combine(candidate_date, candidate_time)
        if candidate_dt <= now_local:
            candidate_dt += timedelta(days=7)
        if next_dt is None or candidate_dt < next_dt:
            next_dt = candidate_dt
    return next_dt


async def build_subscription_notice(user_id: int) -> list[str]:
    tz_code = await get_user_timezone(user_id)
    zone = resolve_user_zone(tz_code)
    now_local = datetime.now(UTC).astimezone(zone)
    active = await get_active_subscription(user_id)
    if active and active.get("expires_at"):
        expires_local = active["expires_at"].astimezone(zone)
        days_left = (expires_local.date() - now_local.date()).days
        if days_left == 0:
            return ["⚠️ Подписка заканчивается сегодня."]
        if days_left == 1:
            return ["⚠️ Через 1 день подписка закончится."]
        return [f"⭐ Подписка активна до {expires_local.strftime('%d.%m.%Y')}."]
    latest = await get_latest_subscription(user_id)
    if latest and latest.get("status") == "expired" and latest.get("expires_at"):
        expires_local = latest["expires_at"].astimezone(zone)
        if now_local.date() == expires_local.date():
            return ["⚠️ Ваша подписка закончилась."]
    return []


def _format_day_label(day_index: int, raw_label: str | None, weekday_label: str | None) -> str:
    base = (raw_label or "").strip() or f"{t('DAY')} {day_index}"
    if weekday_label:
        if base.casefold() == weekday_label.casefold():
            base = f"{t('DAY')} {day_index}"
        return f"{base} — {weekday_label}"
    return base


def _sort_reminders(
    reminders: list[tuple[int, int, int, int]]
) -> list[tuple[int, int, int, int]]:
    """Return reminders sorted by day number and weekday."""

    def _key(item: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        day_no, dow, hour, minute = item
        try:
            day_idx = int(day_no)
        except (TypeError, ValueError):
            day_idx = 10**6
        try:
            dow_idx = normalize_dow(dow)
        except Exception:
            dow_idx = 10**6
        try:
            hour_val = int(hour)
        except (TypeError, ValueError):
            hour_val = 0
        try:
            minute_val = int(minute)
        except (TypeError, ValueError):
            minute_val = 0
        return (day_idx, dow_idx, hour_val, minute_val)

    return sorted(reminders, key=_key)


def _build_day_weekday_map(
    days: list[tuple[int, str]], reminders: list[tuple[int, int, int, int]]
) -> dict[int, str]:
    mapping: dict[int, str] = {}
    reminder_map = {
        day_no: (
            int(dow) if dow is not None else None,
            int(hour),
            int(minute),
        )
        for day_no, dow, hour, minute in _sort_reminders(reminders)
    }
    has_any_reminders = bool(reminder_map)
    for day_index, _label in days:
        info = reminder_map.get(day_index)
        if info:
            dow, _hour, _minute = info
            mapping[day_index] = WEEKDAY_FULL_NAMES.get(
                dow, t("NOT_SET").capitalize()
            )
        elif has_any_reminders:
            mapping[day_index] = t("NOT_SET").capitalize()
    return mapping


def get_timezone_label(tz_code: str) -> str:
    return next((label for code, label in TIMEZONES if code == tz_code), tz_code)


def format_reminder_status(
    label: str, info: tuple[int, int, int] | None
) -> str:
    if info:
        dow, hour, minute = info
        weekday = WEEKDAY_FULL_NAMES.get(dow, t("NOT_SET").capitalize())
        return f"{label} — {weekday}, {hour:02d}:{minute:02d}"
    return f"{label} — напоминание не настроено"


def build_reminders_settings_text(
    tz_label: str, enabled: bool, reminders: list[tuple[int, int, int, int]]
) -> str:
    status = "включены" if enabled else "выключены"
    weekday_labels = dict(WEEKDAYS)
    if reminders:
        parts: list[str] = []
        for _day_no, dow, hour, minute in _sort_reminders(reminders):
            try:
                dow_int = int(dow)
            except (TypeError, ValueError):
                weekday = "—"
            else:
                weekday = weekday_labels.get(dow_int, str(dow_int + 1))
            try:
                hour_int = int(hour)
            except (TypeError, ValueError):
                hour_int = 0
            try:
                minute_int = int(minute)
            except (TypeError, ValueError):
                minute_int = 0
            parts.append(f"{weekday} {hour_int:02d}:{minute_int:02d}")
        reminders_line = f"Сейчас выбраны напоминания: {', '.join(parts)}."
    else:
        reminders_line = "Сейчас выбраны напоминания: «напоминания пока не настроены»."
    lines = [
        f"Напоминания (время по {tz_label}).",
        "",
        f"Текущий статус: уведомления {status}.",
        "",
        reminders_line,
        "",
        "Ниже можно изменить часовой пояс, расписание или полностью включить/выключить напоминания без удаления расписания.",
    ]
    return "\n".join(lines)


async def compose_main_menu(
    user_id: int,
    prefs: UiPreferences | None = None,
    *,
    show_support: bool = True,
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
    include_subscription_notice: bool = True,
    include_settings: bool = True,
) -> tuple[str, InlineKeyboardMarkup, UiPreferences]:
    prefs = prefs or await load_ui_preferences(user_id)
    raw_days = await list_active_days(user_id)
    settings = await fetch_user_settings(user_id)
    max_days: int | None = None
    if settings and len(settings) > 1 and settings[1] is not None:
        try:
            max_days = int(settings[1])
        except (TypeError, ValueError):
            max_days = None
    reminders = await list_user_reminders(user_id)
    if max_days is not None:
        filtered_days = [
            (idx, label) for idx, label in raw_days if idx <= max_days
        ]
    else:
        filtered_days = list(raw_days)
    weekday_map = (
        _build_day_weekday_map(filtered_days, reminders) if filtered_days else {}
    )
    days = [
        (
            day_index,
            _format_day_label(day_index, label, weekday_map.get(day_index)),
        )
        for day_index, label in filtered_days
    ]
    day_label_map = {idx: label for idx, label in days}
    completions = await get_active_day_completions(user_id)
    text = build_main_menu_text(prefs)
    stats_lines: list[str] = []
    tz_code = await get_user_timezone(user_id)
    zone = resolve_user_zone(tz_code)
    now_local = datetime.now(UTC).astimezone(zone)
    system_id = await _active_system_id(user_id)
    last_completion = await get_last_completion_for_user(user_id, system_id=system_id)
    if last_completion:
        day_idx, completed_at = last_completion
        if completed_at:
            try:
                last_dt = datetime.fromisoformat(completed_at)
            except ValueError:
                last_dt = None
            if last_dt is not None:
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                last_local = last_dt.astimezone(zone)
                delta_days = (now_local.date() - last_local.date()).days
                ago_text = _format_days_ago(max(delta_days, 0))
                day_label = day_label_map.get(
                    int(day_idx),
                    f"{t('DAY')} {day_idx}",
                )
                stats_lines.append(
                    f"Последний завершённый день: {day_label} — {last_local.strftime('%d.%m.%Y')} ({ago_text})."
                )
    notifications_enabled = await get_user_notifications_enabled(user_id)
    if notifications_enabled:
        next_reminder_dt = _find_next_reminder_time(reminders, now_local, zone)
        if next_reminder_dt:
            weekday_label = WEEKDAY_FULL_NAMES.get(
                next_reminder_dt.weekday(),
                next_reminder_dt.strftime("%A"),
            )
            stats_lines.append(
                f"Следующая тренировка по напоминаниям: {weekday_label} {next_reminder_dt.strftime('%H:%M')}"
            )
    active_subscription = await get_active_subscription(user_id)
    if active_subscription and active_subscription.get("expires_at"):
        expires_at = active_subscription["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        expires_local = expires_at.astimezone(zone)
        stats_lines.append(
            f"Подписка активна до {expires_local.strftime('%d.%m.%Y')}."
        )
    else:
        stats_lines.append("Подписка не активна.")
    if stats_lines:
        text = text + "\n\n" + "\n".join(stats_lines)
    if include_subscription_notice:
        notice_lines = await build_subscription_notice(user_id)
        if notice_lines:
            text = "\n".join([text, "", *notice_lines])
    profile = await _fetch_trainer_profile(user_id)
    is_trainer = bool(profile and profile[0])
    menu_extra_rows = list(extra_rows) if extra_rows else None
    kb = main_menu_kb(
        days,
        SUPPORT_DEEPLINK,
        completions,
        show_trainer=is_trainer,
        show_support=show_support,
        include_settings=include_settings,
        extra_rows=menu_extra_rows,
    )
    return text, kb, prefs


async def start_reminder_day_edit(
    q,
    context,
    user_id: int,
    position: int,
    day_index: int,
    raw_label: str,
):
    display_label = (raw_label or "").strip() or f"{t('DAY')} {day_index}"
    context.user_data[REMINDER_EDIT_POSITION_KEY] = position
    context.user_data[REMINDER_EDIT_LABEL_KEY] = display_label
    context.user_data[REMINDER_EDIT_DAY_INDEX_KEY] = day_index
    context.user_data['reminder_edit_owner'] = user_id
    context.user_data['reminder_edit_system'] = await _active_system_id(user_id)
    reminders = await list_user_reminders(user_id)
    reminder_map = {
        day_no: (
            int(dow) if dow is not None else None,
            int(hour),
            int(minute),
        )
        for day_no, dow, hour, minute in reminders
    }
    selected = reminder_map.get(day_index)
    selected_dow = selected[0] if selected and selected[0] is not None else None
    context.user_data[REMINDER_SELECTED_DOW_KEY] = (
        str(selected_dow + 1) if selected_dow is not None else None
    )
    text = f"{display_label}. В какой день недели тренировка?"
    kb = reminder_day_kb(prefix=f"remedit:dow:{position}", selected=selected_dow)
    await show_screen(q, context, text, kb, user_id)


async def show_reminders_overview(q, context, user_id: int):
    days = await list_active_days(user_id)
    reminders = await list_user_reminders(user_id)
    tz_code = await get_user_timezone(user_id)
    tz_label = get_timezone_label(tz_code)
    reminder_map = {
        day_no: (
            int(dow) if dow is not None else None,
            int(hour),
            int(minute),
        )
        for day_no, dow, hour, minute in reminders
    }
    lines: list[str] = [f"Напоминания (время по {tz_label}):", ""]
    entries: list[tuple[int, str]] = []
    if days:
        if len(days) == 1:
            day_index, raw_label = days[0]
            await start_reminder_day_edit(q, context, user_id, 1, day_index, raw_label)
            return
        for position, (day_index, raw_label) in enumerate(days, start=1):
            display_label = (raw_label or "").strip() or f"{t('DAY')} {day_index}"
            info = reminder_map.get(day_index)
            line = format_reminder_status(display_label, info)
            lines.append(line)
            entries.append((position, line))
        lines.append("")
        lines.append("Выбери день, чтобы изменить время напоминаний.")
        kb = reminders_schedule_kb(entries)
    else:
        lines.append("Сначала добавь тренировочные дни, чтобы настроить напоминания.")
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(BACK_BTN, callback_data="remedit:back")]]
        )
    await show_screen(q, context, "\n".join(lines), kb, user_id)


def strip_emoji(text: str) -> str:
    cleaned = EMOJI_RE.sub("", text)
    cleaned = cleaned.replace("\uFE0F", "").replace("\u200D", "")
    return cleaned


def apply_text_preferences(text: str, prefs: UiPreferences) -> str:
    if prefs.emoji_enabled or not text:
        return text
    processed: list[str] = []
    for line in text.splitlines():
        cleaned = strip_emoji(line)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        if cleaned.strip():
            if line.startswith(" "):
                leading = len(line) - len(line.lstrip(" "))
                cleaned = (" " * leading) + cleaned.strip()
            else:
                cleaned = cleaned.strip()
        else:
            cleaned = ""
        processed.append(cleaned)
    return "\n".join(processed)


def apply_markup_preferences(
    markup: InlineKeyboardMarkup | None, prefs: UiPreferences
) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None

    def split_variants(text: str) -> tuple[str, str]:
        if not text:
            return "", ""
        if "||" in text:
            compact, detailed = text.split("||", 1)
            return compact.strip(), detailed.strip()
        if "\n" in text:
            first_line, _rest = text.split("\n", 1)
            return first_line.strip(), text
        return text, text

    new_rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        new_row: list[InlineKeyboardButton] = []
        for button in row:
            compact_text, detailed_text = split_variants(button.text)
            selected_text = detailed_text if prefs.verbose_level else compact_text
            if not selected_text:
                selected_text = detailed_text or compact_text or button.text
            if not prefs.emoji_enabled:
                cleaned = strip_emoji(selected_text)
                cleaned = re.sub(r"\s{2,}", " ", cleaned)
                selected_text = cleaned.strip() or selected_text.strip() or selected_text
            new_row.append(
                InlineKeyboardButton(
                    text=selected_text,
                    callback_data=button.callback_data,
                    url=button.url,
                    switch_inline_query=button.switch_inline_query,
                    switch_inline_query_current_chat=button.switch_inline_query_current_chat,
                    login_url=button.login_url,
                    callback_game=button.callback_game,
                    pay=button.pay,
                    web_app=button.web_app,
                    copy_text=button.copy_text,
                )
            )
        new_rows.append(new_row)

    return InlineKeyboardMarkup(new_rows)


def _select_text_variant(line: str, prefs: UiPreferences) -> str:
    if "||" not in line:
        return line
    compact, detailed = line.split("||", 1)
    compact = compact.strip()
    detailed = detailed.strip()
    selected = detailed if prefs.verbose_level else compact
    if not selected:
        selected = detailed or compact
    if line.startswith(" ") and not selected.startswith(" "):
        leading = len(line) - len(line.lstrip(" "))
        selected = (" " * leading) + selected
    return selected


def prepare_ui_output(
    text: str,
    markup: InlineKeyboardMarkup | None,
    prefs: UiPreferences,
) -> tuple[str, InlineKeyboardMarkup | None]:
    processed_text = text or ""
    if processed_text:
        processed_lines = [
            _select_text_variant(line, prefs) for line in processed_text.splitlines()
        ]
        processed_text = "\n".join(processed_lines)
    processed_text = apply_text_preferences(processed_text, prefs)
    processed_markup = apply_markup_preferences(markup, prefs)
    return processed_text, processed_markup


def apply_ui_preferences(
    text: str,
    markup: InlineKeyboardMarkup | None,
    prefs: UiPreferences,
) -> tuple[str, InlineKeyboardMarkup | None]:
    return prepare_ui_output(text, markup, prefs)


def resolve_group(name: str, group: str) -> str:
    if name in METCON_EXERCISE_NAMES:
        return "metcon"
    if group == RUNNING_GROUP:
        return RUNNING_GROUP
    return group


def _is_duration_name(name: str) -> bool:
    lower = name.lower()
    return (
        "(сек" in lower
        or "удержание" in lower
        or "стойка" in lower
        or "планк" in lower
    )


def get_display_flags(group: str, name: str) -> tuple[bool, str]:
    if group == RUNNING_GROUP:
        return False, "running"
    if group in {"workout", "core", "kb", "metcon"}:
        return True, "duration"
    with_weight = True
    kind = "duration" if _is_duration_name(name) else "reps"
    return with_weight, kind


def _safe_int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _safe_float(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(int(value))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def format_weight_value(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.1f}"


def format_metric_value(reps: int, seconds: int, kind: str) -> str:
    reps = max(_safe_int(reps), 0)
    seconds = max(_safe_int(seconds), 0)
    if kind != "duration":
        return f"{reps} повт."
    parts: list[str] = []
    if reps > 0:
        parts.append(f"{reps} повт.")
    if seconds > 0:
        parts.append(f"{seconds} сек")
    if not parts:
        parts.append("0 сек")
    return " · ".join(parts)


def format_sets_value(
    sets: int, reps: int, seconds: int, weight: float, with_weight: bool, kind: str = "reps"
) -> str:
    safe_sets = max(_safe_int(sets), 0)
    metric_text = format_metric_value(reps, seconds, kind)
    base = f"{safe_sets}×{metric_text}"
    if not with_weight:
        return base
    weight_value = _safe_float(weight)
    return f"{base} при {format_weight_value(weight_value)} кг"


def _number_emoji(value: int) -> str:
    mapping = {
        0: "0️⃣",
        1: "1️⃣",
        2: "2️⃣",
        3: "3️⃣",
        4: "4️⃣",
        5: "5️⃣",
        6: "6️⃣",
        7: "7️⃣",
        8: "8️⃣",
        9: "9️⃣",
        10: "🔟",
    }
    return mapping.get(value, f"{value}️⃣")


def format_progress_sets_details(
    details: list[tuple[int, int, float]], with_weight: bool, kind: str
) -> str:
    if not details:
        return "—"
    parts: list[str] = []
    for index, (reps, seconds, weight) in enumerate(details, start=1):
        reps_value = int(reps)
        seconds_value = int(seconds)
        weight_value = float(weight)
        text = format_metric_value(reps_value, seconds_value, kind)
        if with_weight and weight_value > 0:
            text = f"{text} при {format_weight_value(weight_value)} кг"
        parts.append(f"{_number_emoji(index)} {text}")
    return " ".join(parts)


def format_sets_history(
    sets: list[tuple], *, with_weight: bool, kind: str = "reps"
) -> str:
    details: list[tuple[int, int, float]] = []
    for entry in sets:
        if len(entry) >= 5:
            _no, reps, seconds, weight, warm = entry[:5]
            if warm:
                continue
        elif len(entry) >= 4:
            _no, reps, seconds, weight = entry[:4]
        elif len(entry) >= 3:
            _no, reps, weight = entry[:3]
            seconds = 0
        else:
            continue
        details.append(
            (
                max(_safe_int(reps), 0),
                max(_safe_int(seconds), 0),
                _safe_float(weight),
            )
        )
    if not details:
        return ""
    return format_progress_sets_details(details, with_weight, kind)


def format_compact_sets_value(
    sets: int, reps: int, seconds: int, weight: float, with_weight: bool, kind: str = "reps"
) -> str:
    safe_sets = max(_safe_int(sets), 0)
    safe_reps = max(_safe_int(reps), 0)
    safe_seconds = max(_safe_int(seconds), 0)
    if kind == "duration":
        metrics: list[str] = []
        if safe_reps > 0:
            metrics.append(f"{safe_reps} повт.")
        if safe_seconds > 0:
            metrics.append(f"{safe_seconds} сек")
        metric_text = " · ".join(metrics) if metrics else "0 сек"
        base = f"{safe_sets}×{metric_text}"
    else:
        base = f"{safe_sets}×{safe_reps}"
    if with_weight:
        safe_weight = max(_safe_float(weight), 0.0)
        if safe_weight > 0:
            connector = "×" if kind != "duration" else " · "
            return f"{base}{connector}{format_weight_value(safe_weight)} кг"
    return base


def format_flex_value(
    reps: int, seconds: int, weight: float, with_weight: bool, kind: str = "reps"
) -> str:
    reps = max(_safe_int(reps), 0)
    seconds = max(_safe_int(seconds), 0)
    weight_value = max(_safe_float(weight), 0.0)
    if kind == "duration":
        entry = format_metric_value(reps, seconds, kind)
        if with_weight:
            if weight_value > 0:
                entry = f"{entry} · {format_weight_value(weight_value)} кг"
        return entry
    parts = [f"{reps} повт."]
    if seconds > 0:
        parts.append(format_duration_value(seconds))
    if with_weight:
        parts.append(f"{format_weight_value(weight_value)} кг")
    return " · ".join(parts)


def _compress_flex_entries(
    entries: list[tuple[int, int, int, float, int]],
    *,
    with_weight: bool,
    kind: str,
) -> list[dict[str, int | float]]:
    runs: list[dict[str, int | float]] = []
    for no, reps, seconds, weight, warm in entries:
        reps_value = _safe_int(reps)
        seconds_value = _safe_int(seconds)
        weight_value = _safe_float(weight)
        warm_flag = _safe_int(warm)
        if runs:
            prev = runs[-1]
            same_reps = int(prev["reps"]) == reps_value
            same_seconds = int(prev.get("seconds", 0)) == seconds_value
            same_warm = int(prev["warm"]) == warm_flag
            same_weight = (
                kind == "duration"
                or not with_weight
                or math.isclose(float(prev["weight"]), weight_value, abs_tol=1e-6)
            )
            if same_reps and same_seconds and same_warm and same_weight:
                prev["end"] = no
                prev["count"] = int(prev["count"]) + 1
                continue
        runs.append(
            {
                "start": no,
                "end": no,
                "count": 1,
                "reps": reps_value,
                "seconds": seconds_value,
                "weight": weight_value,
                "warm": warm_flag,
            }
        )
    return runs


def _compress_flex_triplets(
    entries: list[tuple[int, int, int, float]],
    *,
    with_weight: bool,
    kind: str,
) -> list[dict[str, int | float]]:
    extended = [(no, reps, seconds, weight, 0) for no, reps, seconds, weight in entries]
    return _compress_flex_entries(extended, with_weight=with_weight, kind=kind)


def _format_flex_span(start: int, end: int) -> str:
    if start == end:
        return str(start)
    return f"{start}–{end}"


def filter_work_sets(
    sets: list[tuple[int, int, int, float, int]]
) -> list[tuple[int, int, int, float]]:
    return [(no, reps, seconds, weight) for no, reps, seconds, weight, warm in sets if not warm]


def build_strength_summary_from_sets(
    sets: list[tuple[int, int, int, float, int]]
) -> dict[str, int | float | list]:
    work_sets = filter_work_sets(sets)
    if not work_sets:
        return {
            "sets": [],
            "sets_count": 0,
            "last_reps": 0,
            "last_seconds": 0,
            "last_weight": 0.0,
        }
    last_reps = int(work_sets[-1][1] or 0)
    last_seconds = int(work_sets[-1][2] or 0)
    last_weight = float(work_sets[-1][3] or 0.0)
    return {
        "sets": work_sets,
        "sets_count": len(work_sets),
        "last_reps": last_reps,
        "last_seconds": last_seconds,
        "last_weight": last_weight,
    }


def pluralize_sets(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "сет"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "сета"
    return "сетов"


def format_kb_previous(
    last_sets: list[tuple], *, kind: str = "reps"
) -> str:
    if not last_sets:
        return "—"
    if kind == "duration":
        normalized: list[tuple[int, int, int, float]] = []
        for entry in last_sets:
            if len(entry) >= 4:
                no = entry[0]
                reps = entry[1]
                seconds = entry[2]
                weight = entry[3]
            else:
                no = entry[0]
                reps = entry[1]
                seconds = 0
                weight = entry[2]
            normalized.append(
                (
                    _safe_int(no),
                    max(_safe_int(reps), 0),
                    max(_safe_int(seconds), 0),
                    _safe_float(weight),
                )
            )
        summary = summarize_previous_sets(normalized, with_weight=True, kind=kind)
        return summary or "—"
    total_reps = 0
    best_weight = -1.0
    best_reps = 0
    for entry in last_sets:
        if len(entry) >= 4:
            reps = entry[1]
            weight = entry[3]
        else:
            reps = entry[1]
            weight = entry[2]
        safe_reps = max(_safe_int(reps), 0)
        safe_weight = max(_safe_float(weight), 0.0)
        total_reps += safe_reps
        if safe_weight > best_weight or (
            math.isclose(safe_weight, best_weight, abs_tol=1e-6) and safe_reps > best_reps
        ):
            best_weight = safe_weight
            best_reps = safe_reps
    best_text = f"{best_reps} повт. при {format_weight_value(best_weight)} кг"
    if total_reps:
        return f"Всего {total_reps} повт., лучший {best_text}"
    return f"Лучший {best_text}"


def format_kb_plan(
    baseline: tuple[int, int, int, float] | None, *, kind: str = "reps"
) -> str:
    if not baseline:
        return "—"
    sets, reps, seconds, weight = baseline
    return format_compact_sets_value(sets, reps, seconds, weight, True, kind)


def format_kb_done(
    sets: list[tuple[int, int, int, float]], *, kind: str = "reps"
) -> str:
    if not sets:
        return "0 сетов"
    count = len(sets)
    _, reps, seconds, weight = sets[-1]
    metric = format_metric_value(reps, seconds, kind)
    last_weight = float(weight or 0.0)
    if last_weight > 0:
        metric = f"{metric} при {format_weight_value(last_weight)} кг"
    return f"{count} {pluralize_sets(count)} (последний {metric})"


def format_kb_summary(
    current_sets: list[tuple[int, int, int, float]],
    last_sets: list[tuple[int, int, int, float]],
    *,
    kind: str = "reps",
) -> str:
    if current_sets:
        detailed = format_sets_history(
            current_sets, with_weight=True, kind=kind
        )
        if detailed:
            return f"{t('MADE')} {detailed}"
        return f"{t('MADE')} {format_kb_done(current_sets, kind=kind)}"
    if last_sets:
        return f"{t('LAST_TIME')}: {format_sets_history(last_sets, with_weight=True, kind=kind)}"
    return f"{t('MADE')} 0 сетов"


def parse_amrap_sets(sets: list[tuple[int, int, float, int]]) -> tuple[int, int]:
    for _, reps, weight, warm in sets:
        if warm:
            continue
        rounds = max(int(reps or 0), 0)
        extra = max(int(round(weight or 0.0)), 0)
        return rounds, extra
    return 0, 0


def parse_amrap_history(last_sets: list[tuple[int, int, float]]) -> tuple[int, int]:
    if not last_sets:
        return 0, 0
    rounds = max(int(last_sets[0][1] or 0), 0)
    extra = max(int(round(last_sets[0][2] or 0.0)), 0)
    return rounds, extra


def format_amrap_done(rounds: int, extra: int) -> str:
    return f"{rounds} раундов + {extra} повт."


def format_amrap_summary(
    current_rounds: int,
    current_extra: int,
    last_rounds: int,
    last_extra: int,
) -> str:
    if current_rounds or current_extra:
        return t("AMRAP_LINE", rounds=current_rounds, extra=current_extra)
    if last_rounds or last_extra:
        return f"{t('LAST_TIME')}: {format_amrap_done(last_rounds, last_extra)}"
    return t("AMRAP_LINE", rounds=0, extra=0)


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
        total = minutes * 60 + seconds
    else:
        hours, minutes, seconds = values
        if minutes >= 60 or seconds >= 60:
            raise ValueError("time range")
        total = hours * 3600 + minutes * 60 + seconds
    if total > 1_000_000_000_000:
        raise ValueError("duration range")
    return total


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


def format_pace_value(seconds: float) -> str:
    total = max(int(round(seconds)), 0)
    minutes, sec = divmod(total, 60)
    return f"{minutes}:{sec:02d}"


def format_running_pace(duration_sec: int, distance_km: float) -> str:
    if distance_km <= 0 or duration_sec <= 0:
        return "—"
    pace = duration_sec / distance_km
    return format_pace_value(pace)


def format_running_entry(distance_km: float, duration_sec: int, calories: int) -> tuple[str, str]:
    distance_text = f"{max(distance_km, 0.0):.2f} км"
    time_text = format_duration_value(duration_sec)
    pace_text = format_running_pace(duration_sec, distance_km)
    if pace_text == "—":
        pace_display = "— мин/км"
    else:
        pace_display = f"{pace_text} мин/км"
    summary = f"{distance_text} · {time_text} · {pace_display}"
    calories_text = f"{max(int(calories), 0)} ккал" if calories > 0 else ""
    return summary, calories_text


def format_running_line(distance_km: float, duration_sec: int, calories: int) -> str:
    summary, calories_text = format_running_entry(distance_km, duration_sec, calories)
    if calories_text:
        return f"{summary} · {calories_text}"
    return summary


def _finite_input_number(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid number") from exc
    if not math.isfinite(number) or abs(number) > 1_000_000_000_000:
        raise ValueError("number out of range")
    return number


def clamp_running_distance(value: float) -> float:
    return max(round(_finite_input_number(value), 2), 0.0)


def clamp_running_duration(value: int) -> int:
    return max(int(_finite_input_number(value)), 0)


def clamp_running_calories(value: int) -> int:
    return max(int(_finite_input_number(value)), 0)


def parse_distance_input(text: str) -> float:
    raw = text.strip().replace(",", ".")
    value = float(raw)
    return clamp_running_distance(value)


def parse_calories_input(text: str) -> int:
    raw = text.strip()
    value = int(_finite_input_number(raw.replace(",", ".")))
    return clamp_running_calories(value)


def apply_pace_to_entry(distance_km: float, pace_seconds: int) -> tuple[float, int]:
    safe_distance = clamp_running_distance(distance_km)
    if safe_distance <= 0:
        safe_distance = 1.0
    duration = clamp_running_duration(int(round(pace_seconds * safe_distance)))
    return safe_distance, duration


def format_measurement_timestamp(value: str, tz: ZoneInfo) -> str:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt = dt.astimezone(tz)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return value.split("T")[0]


def format_measurement_date(value: str, tz: ZoneInfo) -> str:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt = dt.astimezone(tz)
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return value.split("T")[0]


def format_progress_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        try:
            dt = datetime.fromisoformat(value)
            return dt.strftime("%d.%m.%Y")
        except Exception:
            return value


def remember_message(chat_id: int | None, message_id: int | None):
    if chat_id is None or message_id is None:
        return
    last_messages[chat_id] = message_id
    from progressor_native_subscription import menu_anchor
    from settings import DB_PATH
    menu_anchor(DB_PATH,chat_id,message_id)
    history = message_history[chat_id]
    if message_id not in history:
        history.append(message_id)
        if len(history) > 100:
            history.pop(0)


def _remove_message_from_history(chat_id: int, message_id: int):
    history = message_history.get(chat_id)
    if not history:
        return
    try:
        history.remove(message_id)
    except ValueError:
        pass
    if not history:
        message_history.pop(chat_id, None)


async def purge_chat_history(bot, chat_id: int) -> None:
    history = list(message_history.get(chat_id, []))
    if not history:
        return
    for msg_id in sorted(history, reverse=True):
        try:
            await bot.delete_message(chat_id, msg_id)
        except BadRequest as delete_error:
            error_text = (delete_error.message or "").lower()
            if "message to delete not found" in error_text:
                pass
            elif "can't be deleted" in error_text:
                logger.debug(
                    "Message %s in chat %s cannot be deleted during purge",
                    msg_id,
                    chat_id,
                )
            else:
                logger.warning(
                    "Failed to delete message %s in chat %s during purge", msg_id, chat_id
                )
        except Forbidden:
            logger.debug(
                "Bot is not allowed to delete message %s in chat %s during purge",
                msg_id,
                chat_id,
            )
        except TelegramError:
            logger.warning(
                "Unexpected error when deleting message %s in chat %s during purge",
                msg_id,
                chat_id,
                exc_info=True,
            )
        else:
            _remove_message_from_history(chat_id, msg_id)


async def _generate_trainer_code():
    return "TR-" + secrets.token_hex(3).upper()


async def _generate_unique_trainer_code() -> str:
    while True:
        candidate = await _generate_trainer_code()
        existing = await find_user_by_trainer_code(candidate)
        if not existing:
            return candidate


def is_edit_allowed(user_data: dict) -> bool:
    acting_id = user_data.get("acting_user_id")
    if not acting_id:
        return True
    return bool(user_data.get("acting_can_edit"))


def get_acting_context_line(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    subject: str,
) -> str | None:
    user_data = getattr(context, "user_data", None)
    if not isinstance(user_data, dict):
        return None
    acting_id = user_data.get("acting_user_id")
    if acting_id is None:
        return None
    try:
        acting_id_int = int(acting_id)
    except (TypeError, ValueError):
        return None
    if acting_id_int != user_id:
        return None
    label = user_data.get("acting_label")
    if label:
        return f"Сейчас вы смотрите {subject} подопечного: {label}."
    return f"Сейчас вы смотрите {subject} подопечного."


async def _owns_active_exercise(user_id: int, day: int, ue_id: int) -> bool:
    return await get_user_exercise_info(ue_id) == (int(user_id), int(day))


async def _require_available_catalog_exercise(user_id: int, exercise_id: int) -> None:
    info = await get_exercise_details(exercise_id)
    if not info or int(info[2] or 0) not in (0, int(user_id)):
        raise ValueError('exercise_not_available')


async def require_edit_allowed(q: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_edit_allowed(context.user_data):
        await q.answer("Подопечный не дал доступ на изменение плана.", show_alert=True)
        return False
    return True


async def ensure_can_edit_from_callback(
    context: ContextTypes.DEFAULT_TYPE, q: CallbackQuery
) -> bool:
    return await require_edit_allowed(q, context)


async def ensure_can_edit_from_message(
    context: ContextTypes.DEFAULT_TYPE, update: Update
) -> bool:
    if not is_edit_allowed(context.user_data):
        if update.message:
            await update.message.reply_text(
                "Подопечный не дал доступ на изменение плана."
            )
        return False
    return True


async def resolve_target_user_id(
    context: ContextTypes.DEFAULT_TYPE, actor_user_id: int
) -> int:
    acting_id = context.user_data.get("acting_user_id")
    if acting_id is None:
        context.user_data.pop("acting_can_edit", None)
        context.user_data.pop(RESOLVE_TARGET_USER_KEY, None)
        context.user_data.pop("acting_label", None)
        return actor_user_id
    try:
        acting_id_int = int(acting_id)
    except (TypeError, ValueError):
        context.user_data.pop("acting_user_id", None)
        context.user_data.pop("acting_can_edit", None)
        context.user_data.pop(RESOLVE_TARGET_USER_KEY, None)
        context.user_data.pop("acting_label", None)
        return actor_user_id
    link = await get_trainer_link(actor_user_id, acting_id_int)
    if link and str(link[1]) == "accepted":
        can_edit = bool(link[2])
        context.user_data["acting_user_id"] = acting_id_int
        context.user_data["acting_can_edit"] = can_edit
        raw_label = None
        if len(link) > 4:
            raw_label = link[4]
        label = str(raw_label).strip() if raw_label else None
        if label:
            context.user_data["acting_label"] = label
        else:
            context.user_data.pop("acting_label", None)
        context.user_data[RESOLVE_TARGET_USER_KEY] = {
            "actor_user_id": actor_user_id,
            "target_user_id": acting_id_int,
            "can_edit": can_edit,
        }
        return acting_id_int
    context.user_data.pop("acting_user_id", None)
    context.user_data.pop("acting_can_edit", None)
    context.user_data.pop(RESOLVE_TARGET_USER_KEY, None)
    context.user_data.pop("acting_label", None)
    return actor_user_id


async def _fetch_trainer_profile(
    user_id: int,
) -> tuple[int, str | None, int] | None:
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT is_trainer, trainer_code, trainer_accepts_requests
            FROM users
            WHERE id=?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    is_trainer = int(row[0] or 0)
    accepts = 1
    try:
        accepts = int(row[2]) if row[2] is not None else 1
    except (IndexError, ValueError, TypeError):
        accepts = 1
    return is_trainer, row[1], accepts


async def _ensure_trainer_mode(
    user_id: int,
    profile: tuple[int, str | None] | None = None,
) -> str:
    if profile is None:
        profile = await _fetch_trainer_profile(user_id)
    if profile and profile[0] and profile[1]:
        return profile[1]
    existing_code = profile[1] if profile else None
    if existing_code:
        owner = await find_user_by_trainer_code(existing_code)
        if owner and int(owner[0]) != user_id:
            existing_code = None
    if not existing_code:
        existing_code = await _generate_unique_trainer_code()
    async with connect_db() as db:
        await db.execute(
            """
            UPDATE users
            SET is_trainer = 1,
                trainer_code = ?,
                trainer_accepts_requests = 1
            WHERE id=?
            """,
            (existing_code, user_id),
        )
        await db.commit()
    return existing_code


async def show_trainer_root_settings(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    status_message: str | None = None,
):
    profile = await _fetch_trainer_profile(user_id)
    is_trainer = int(profile[0]) if profile and profile[0] else 0
    trainer_code = profile[1] if profile else None
    accepts_requests = bool(profile and len(profile) > 2 and profile[2])
    link = await get_latest_trainer_link_for_trainee(user_id)
    link_status_value = str(link[2]) if link and len(link) > 2 else ""
    if not link:
        link_status = "нет"
    else:
        if link_status_value == "pending":
            link_status = "заявка отправлена"
        elif link_status_value == "accepted":
            link_status = "есть"
        elif link_status_value in {"trainer_disabled", "inactive"}:
            link_status = "тренер отключил режим тренера"
        else:
            link_status = link_status_value or "нет"
    lines = [
        "Режим тренера / подопечного",
        "",
        "В режиме тренера ты ведёшь подопечных: видишь их план и, если они разрешат, меняешь тренировки.",
        "Подопечный вводит твой код в настройках, чтобы связать дневник.",
        "",
        "Если у тебя есть тренер, управляй связью в этом разделе.",
        "",
        f"Режим тренера: {'включён' if is_trainer else 'выключен'}.",
    ]
    if is_trainer and trainer_code:
        lines.extend(
            [
                "",
                f"Ваш код тренера: {trainer_code}",
                "Нажми на кнопку, чтобы скопировать код в буфер обмена и сразу переслать его подопечному.",
            ]
        )
    lines.extend(["", f"Связь с тренером: {link_status}."])
    if is_trainer:
        request_status = "включен" if accepts_requests else "выключен"
        lines.append("")
        lines.append(f"Прием заявок: {request_status}.")
    if status_message:
        lines.append("")
        lines.append(status_message)
    text = "\n".join(lines)
    toggle_target = "off" if is_trainer else "on"
    toggle_button = InlineKeyboardButton(
        dual(
            f"Стать тренером: {'Вкл' if is_trainer else 'Выкл'}",
            "Переключить режим тренера",
        ),
        callback_data=f"set:trainer_mode:toggle:{toggle_target}",
    )
    trainee_cta = "🤝 Стать подопечным"
    if link_status_value == "accepted":
        trainee_cta = "🏠 Хаб подопечного"
    trainee_button = InlineKeyboardButton(
        trainee_cta,
        callback_data="set:trainer_mode:trainee",
    )
    back_button = InlineKeyboardButton(
        BACK_BTN,
        callback_data="menu:settings",
    )
    rows: list[list[InlineKeyboardButton]] = [[toggle_button]]
    if is_trainer and trainer_code:
        rows.append(
            [
                InlineKeyboardButton(
                    dual(
                        "📋 Скопировать код тренера",
                        "Скопировать код тренера в буфер обмена",
                    ),
                    copy_text=CopyTextButton(trainer_code),
                )
            ]
        )
    if is_trainer:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("👥 Мои подопечные", "Открыть список подопечных"),
                    callback_data="trainer:list",
                )
            ]
        )
        toggle_state = "off" if accepts_requests else "on"
        toggle_label = dual(
            "🚫 Отключить прием заявок"
            if accepts_requests
            else "✅ Включить прием заявок",
            "Отключить прием заявок"
            if accepts_requests
            else "Включить прием заявок",
        )
        rows.append(
            [
                InlineKeyboardButton(
                    toggle_label,
                    callback_data=f"trainer:requests:{toggle_state}",
                )
            ]
        )
    rows.append([trainee_button])
    rows.append([back_button])
    kb = InlineKeyboardMarkup(rows)
    await show_screen(q, context, text, kb, user_id)


async def _build_become_trainee_view(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    link,
    *,
    status_message: str | None = None,
    prompt_for_code: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    pending_can_edit = bool(
        context.user_data.get(TRAINER_PENDING_CAN_EDIT_KEY, False)
    )
    status_lines: list[str] = []
    status_value = str(link[2]) if link and len(link) > 2 else ""
    if status_value == "pending":
        trainer_user_id = int(link[1])
        trainer_label = (link[4] or "").strip()
        if not trainer_label:
            trainer_label = await _format_trainer_user_display(trainer_user_id)
        pending_can_edit = bool(link[3])
        context.user_data[TRAINER_PENDING_CAN_EDIT_KEY] = pending_can_edit
        status_lines.append(
            f"Статус: заявка отправлена тренеру {trainer_label}. Ждём подтверждения."
        )
    elif status_value in {"trainer_disabled", "inactive"}:
        status_lines.append(
            "Статус: тренер отключил режим тренера. Связь временно приостановлена до его возвращения."
        )
    elif status_value == "rejected":
        status_lines.append("Статус: заявка отклонена тренером.")
    elif status_value:
        status_lines.append(f"Статус: {status_value}.")
    else:
        if prompt_for_code:
            status_lines.append(
                "Пришли код тренера одним сообщением ниже (формат TR-XXXXX)."
            )
        else:
            status_lines.append(
                "Статус: пока нет активной связи. Попроси тренера поделиться кодом и введи его через кнопку ниже."
            )
        context.user_data.setdefault(
            TRAINER_PENDING_CAN_EDIT_KEY, pending_can_edit
        )
    if status_message:
        status_lines.append(status_message)
    lines = [
        "Стать подопечным тренера.",
        "",
        "Здесь ты можешь ввести код тренера.",
        "Тренер сможет смотреть твои тренировки и замеры.",
        "Дополнительно ты можешь разрешить ему менять твой план тренировок.",
        "",
        "По умолчанию тренер видит только твой план. Если дать разрешение ниже, тренер сможет менять упражнения и завершать дни за тебя.",
        "",
    ]
    lines.extend(status_lines)
    text = "\n".join(lines)
    kb = trainee_become_kb(pending_can_edit)
    return text, kb


async def show_become_trainee_screen(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    status_message: str | None = None,
    prompt_for_code: bool | None = None,
):
    link = await get_latest_trainer_link_for_trainee(user_id)
    if link and str(link[2]) == "accepted":
        await show_trainee_trainer_settings(q, context, user_id)
        return link
    if prompt_for_code is None:
        prompt_flag = bool(context.user_data.get(TRAINER_CODE_INPUT_KEY))
    else:
        prompt_flag = prompt_for_code
    text, kb = await _build_become_trainee_view(
        context,
        user_id,
        link,
        status_message=status_message,
        prompt_for_code=prompt_flag,
    )
    message = await show_screen(q, context, text, kb, user_id)
    target_message = message or getattr(q, "message", None)
    if target_message:
        context.user_data[TRAINER_CODE_PROMPT_KEY] = (
            getattr(target_message, "chat_id", None),
            getattr(target_message, "message_id", None),
        )
    if prompt_flag:
        context.user_data[TRAINER_CODE_INPUT_KEY] = True
    else:
        context.user_data.pop(TRAINER_CODE_INPUT_KEY, None)
    return link


async def _render_trainer_link_message(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    target: tuple[int, int] | None,
    status_message: str | None,
    *,
    prompt_for_code: bool = False,
    chat_id: int | None = None,
) -> tuple[int, int] | None:
    link = await get_latest_trainer_link_for_trainee(user_id)
    if link and str(link[2]) == "accepted":
        text, kb, _ = await build_trainee_trainer_settings_view(user_id)
        if text is None or kb is None:
            return None
        if status_message:
            text = f"{status_message}\n\n{text}"
        keep_prompt = False
    else:
        text, kb = await _build_become_trainee_view(
            context,
            user_id,
            link,
            status_message=status_message,
            prompt_for_code=prompt_for_code,
        )
        keep_prompt = prompt_for_code
    prefs = await load_ui_preferences(user_id)
    prepared_text, prepared_markup = prepare_ui_output(text, kb, prefs)
    message_chat_id: int | None
    message_id: int | None
    if target:
        message_chat_id, message_id = target
        try:
            await context.bot.edit_message_text(
                prepared_text,
                chat_id=message_chat_id,
                message_id=message_id,
                reply_markup=prepared_markup,
            )
        except TelegramError:
            new_message = await send_main_message(
                context.bot,
                message_chat_id,
                prepared_text,
                reply_markup=prepared_markup,
            )
            message_chat_id = new_message.chat_id
            message_id = new_message.message_id
    else:
        message_chat_id = chat_id
        if message_chat_id is None:
            return None
        new_message = await send_main_message(
            context.bot,
            message_chat_id,
            prepared_text,
            reply_markup=prepared_markup,
        )
        message_id = new_message.message_id
    if message_chat_id is None or message_id is None:
        return None
    remember_message(message_chat_id, message_id)
    context.user_data[TRAINER_CODE_PROMPT_KEY] = (message_chat_id, message_id)
    if keep_prompt:
        context.user_data[TRAINER_CODE_INPUT_KEY] = True
    else:
        context.user_data.pop(TRAINER_CODE_INPUT_KEY, None)
    return message_chat_id, message_id


async def build_trainee_trainer_settings_view(
    trainee_user_id: int,
):
    link = await get_latest_trainer_link_for_trainee(trainee_user_id)
    if not link:
        lines = [
            "Статус: пока нет активной связи.",
            "",
            "Чтобы подключиться к тренеру, вернись в настройки и введи его код.",
        ]
        text = "\n".join(lines)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🤝 Стать подопечным",
                        callback_data="set:trainer_mode:trainee",
                    )
                ],
                [InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")],
            ]
        )
        return text, kb, None
    link_id, trainer_user_id, status, can_edit_plan, trainer_label, _ = link
    status_value = str(status)
    if status_value in {"removed"}:
        lines = [
            "Статус: пока нет активной связи.",
            "",
            "Чтобы подключиться к тренеру, вернись в настройки и введи его код.",
        ]
        text = "\n".join(lines)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🤝 Стать подопечным",
                        callback_data="set:trainer_mode:trainee",
                    )
                ],
                [InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")],
            ]
        )
        return text, kb, None
    if status_value in {"trainer_disabled", "inactive"}:
        lines = [
            "Статус: тренер отключил режим тренера. Связь временно приостановлена.",
            "",
            "Как только тренер вернётся в режим тренера, доступ восстановится автоматически.",
        ]
        text = "\n".join(lines)
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔑 Ввести код тренера",
                        callback_data="set:trainer_link",
                    )
                ],
                [InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")],
            ]
        )
        return text, kb, None
    trainer_name = (trainer_label or "").strip()
    if not trainer_name:
        trainer_name = await _format_trainer_user_display(trainer_user_id)
    trainer_record = await find_user_by_id(trainer_user_id)
    tg_id = None
    username = None
    if trainer_record:
        _internal_id, tg_id, username = trainer_record
    status_map = {
        "pending": "Статус: заявка отправлена тренеру — ждём подтверждения.",
        "accepted": "Статус: связь активна. Тренер уже может видеть твой дневник.",
    }
    status_text = status_map.get(status_value, f"Статус: {status_value}.")
    can_edit = bool(can_edit_plan)
    permission_text = (
        "Разрешение: тренер может менять план тренировок."
        if can_edit
        else "Разрешение: тренеру запрещено менять план."
    )
    if status_value == "pending":
        body_hint = "Когда тренер подтвердит заявку, он появится в списке подопечных."
        header_line = f"Заявка тренеру {trainer_name} успешно отправлена."
    else:
        body_hint = "Используй кнопки ниже, чтобы управлять правами или отключить связь."
        header_line = f"Тренер: {trainer_name}"
    username_line = (
        f"Имя пользователя: @{username}"
        if username
        else "Имя пользователя: не указано"
    )
    tg_line = (
        f"Telegram ID: {tg_id}"
        if tg_id
        else "Telegram ID: недоступен"
    )
    internal_line = f"Внутренний ID: {trainer_user_id}"
    lines = [
        header_line,
        "",
        username_line,
        tg_line,
        internal_line,
        "",
        status_text,
        "",
        permission_text,
        "",
        body_hint,
    ]
    text = "\n".join(lines)
    kb = trainee_trainer_settings_kb(can_edit)
    return text, kb, link


async def show_trainee_trainer_settings(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    trainee_user_id: int,
):
    text, kb, link = await build_trainee_trainer_settings_view(trainee_user_id)
    if text is None or kb is None:
        message = await show_screen(
            q,
            context,
            "Связь с тренером не найдена. Вернись и введи код тренера заново.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")]]
            ),
            trainee_user_id,
        )
        if message:
            context.user_data[TRAINER_SETTINGS_MESSAGE_KEY] = (
                getattr(message, "chat_id", None),
                getattr(message, "message_id", None),
            )
        return None
    message = await show_screen(q, context, text, kb, trainee_user_id)
    if message:
        context.user_data[TRAINER_SETTINGS_MESSAGE_KEY] = (
            getattr(message, "chat_id", None),
            getattr(message, "message_id", None),
        )
    return link


async def refresh_trainee_trainer_settings_message(
    context: ContextTypes.DEFAULT_TYPE,
    trainee_user_id: int,
    target: tuple[int, int] | None,
):
    if not target:
        return
    text, kb, _ = await build_trainee_trainer_settings_view(trainee_user_id)
    if text is None or kb is None:
        return
    chat_id, message_id = target
    if chat_id is None or message_id is None:
        return
    prefs = await load_ui_preferences(trainee_user_id)
    prepared_text, prepared_markup = prepare_ui_output(text, kb, prefs)
    try:
        await context.bot.edit_message_text(
            prepared_text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=prepared_markup,
        )
    except TelegramError as exc:
        logger.debug("Failed to refresh trainer settings message: %s", exc)
        return
    remember_message(chat_id, message_id)


async def build_trainer_manage_trainee_view(
    trainer_user_id: int,
    trainee_user_id: int,
):
    link = await get_trainer_link(trainer_user_id, trainee_user_id)
    if not link or str(link[1]) != "accepted":
        return None, None, None
    link_id, _status, can_edit_plan, trainer_label, _trainee_label = link
    display_name = (trainer_label or "").strip()
    if not display_name:
        display_name = await _format_trainer_user_display(trainee_user_id)
    permission_text = (
        "Разрешение: тренер может менять план тренировок."
        if can_edit_plan
        else "Разрешение: тренеру запрещено менять план."
    )
    lines = [
        f"Подопечный: {display_name}",
        "Статус: связь активна.",
        "",
        permission_text,
        "",
        "Переименуй подопечного или отключи связь с помощью кнопок ниже.",
        "Разрешение менять план можно обновить только в настройках подопечного.",
    ]
    text = "\n".join(lines)
    kb = trainer_manage_trainee_kb(trainee_user_id)
    return text, kb, int(link_id)


async def show_trainer_manage_trainee(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    trainer_user_id: int,
    trainee_user_id: int,
):
    text, kb, link_id = await build_trainer_manage_trainee_view(
        trainer_user_id, trainee_user_id
    )
    if text is None or kb is None or link_id is None:
        await q.answer("Настройки недоступны.", show_alert=True)
        return None
    message = await show_screen(q, context, text, kb, trainee_user_id)
    if message:
        context.user_data[TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY] = (
            getattr(message, "chat_id", None),
            getattr(message, "message_id", None),
        )
    return link_id


async def refresh_trainer_manage_trainee_message(
    context: ContextTypes.DEFAULT_TYPE,
    trainer_user_id: int,
    trainee_user_id: int,
    target: tuple[int | None, int | None] | None,
):
    if not target:
        return
    text, kb, _ = await build_trainer_manage_trainee_view(
        trainer_user_id, trainee_user_id
    )
    if text is None or kb is None:
        return
    chat_id, message_id = target
    if chat_id is None or message_id is None:
        return
    prefs = await load_ui_preferences(trainer_user_id)
    prepared_text, prepared_markup = prepare_ui_output(text, kb, prefs)
    try:
        await context.bot.edit_message_text(
            prepared_text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=prepared_markup,
        )
    except TelegramError as exc:
        logger.debug("Failed to refresh trainer manage view: %s", exc)
        return
    remember_message(chat_id, message_id)


async def show_trainer_acting_menu(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    trainer_user_id: int,
    trainee_user_id: int,
):
    link = await get_trainer_link(trainer_user_id, trainee_user_id)
    trainee_label: str | None = None
    if link:
        raw_label = link[4]
        if raw_label:
            trainee_label = str(raw_label).strip() or None
        acting_can_edit = bool(link[2])
        context.user_data["acting_can_edit"] = acting_can_edit
    else:
        acting_can_edit = bool(context.user_data.get("acting_can_edit"))
    if not trainee_label:
        trainee_label = await _format_trainer_user_display(trainee_user_id)
    context.user_data["acting_label"] = trainee_label
    extra_rows = [
        [
            InlineKeyboardButton(
                "⚙ Настройки подопечного",
                callback_data="trainer:trainee_settings",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ К подопечным",
                callback_data="trainer:list",
            )
        ],
    ]
    text, kb, _ = await compose_main_menu(
        trainee_user_id,
        show_support=False,
        extra_rows=extra_rows,
        include_subscription_notice=False,
        include_settings=False,
    )
    context_line = get_acting_context_line(
        context, trainee_user_id, subject="план"
    ) or f"Сейчас вы смотрите план подопечного: {trainee_label}."
    if acting_can_edit:
        context_line += (
            " Изменения в этом меню будут сохраняться для подопечного, а не для вас."
        )
    text = f"{context_line}\n\n{text}"
    await show_screen(q, context, text, kb, trainee_user_id)


async def build_settings_keyboard_for_user(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    link_active: bool | None = None,
) -> InlineKeyboardMarkup:
    acting_mode = bool(context.user_data.get("acting_user_id"))
    if link_active is None:
        link_active = bool(await get_active_trainer_link_for_trainee(user_id))
    return settings_kb(
        include_notifications=not acting_mode,
        include_subscription=not acting_mode,
        trainer_link_active=link_active,
        show_referral=not acting_mode,
        show_referral_admin=(not acting_mode and bool(context.user_data.get("is_admin_actor"))),
        support_url=SUPPORT_DEEPLINK,
        instruction_url=INSTRUCTION_URL,
        context=context,
    )


def _build_referral_link(slug: str) -> str:
    payload = f"ref_{slug}"
    bot_link = (BOT_PUBLIC_LINK or "").strip()
    candidate = bot_link or "https://t.me/progresor_bot"
    username = ""
    if candidate.startswith("http://") or candidate.startswith("https://"):
        parsed = urlparse(candidate)
        username = (parsed.path or "").strip("/").split("/", 1)[0]
    else:
        username = candidate.strip("/").split("/", 1)[0]
    username = username.lstrip("@")
    if not username:
        username = "progresor_bot"
    return f"https://t.me/{username}?start={payload}"


def _referral_rate_for_invites(invited_total: int) -> float:
    if invited_total >= 10000:
        return 0.30
    if invited_total >= 1000:
        return 0.25
    if invited_total >= 100:
        return 0.20
    return 0.15


def _format_referral_payout(stats: dict) -> tuple[str, float, float, int, int]:
    invited_total = int(stats.get("invited_total", 0) or 0)
    rate = _referral_rate_for_invites(invited_total)
    percent = int(round(rate * 100))
    month_rub = float(stats.get("revenue_rub_month", 0.0) or 0.0)
    month_stars = int(stats.get("revenue_stars_month", 0) or 0)
    payout_rub = month_rub * rate
    payout_stars = int(round(month_stars * rate))
    summary = (
        f"🏷 Текущий процент: {percent}%\n"
        f"💰 Оборот за месяц: {month_rub:.2f} ₽ + {month_stars} ⭐\n"
        f"🧾 К выплате за месяц: {payout_rub:.2f} ₽ + {payout_stars} ⭐"
    )
    return summary, rate, payout_rub, payout_stars, percent


async def build_referral_screen(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    profile = await get_referral_profile(user_id)
    rows: list[list[InlineKeyboardButton]] = []
    if not profile:
        text = (
            "Реферальная программа\n\n"
            "Приглашайте людей в бота и смотрите статистику оплат.\n"
            "Напишите ваш псевдоним/имя — по нему создадим персональную ссылку."
        )
        rows.append([InlineKeyboardButton("✍️ Указать имя", callback_data="settings:referral:create")])
        rows.append([InlineKeyboardButton("ℹ️ Информация", callback_data="settings:referral:info")])
    else:
        stats = await get_referral_stats(user_id)
        link = _build_referral_link(profile["slug"])
        payout_text, _rate, _rub, _stars, percent = _format_referral_payout(stats)
        month_start = stats.get("month_start") or "—"
        month_end = stats.get("month_end") or "—"
        text = (
            "Реферальная программа\n\n"
            f"Имя в ссылке: {escape(profile['display_name'])}\n"
            "Скопируйте ссылку ниже и отправьте её другу в Telegram.\n"
            f"<code>{escape(link)}</code>\n\n"
            f"👥 Пришло пользователей: всего {stats['invited_total']}, за месяц {stats['invited_month']}\n"
            f"💳 Оплатили: всего {stats['paid_users_total']}, за месяц {stats['paid_users_month']}\n"
            f"📆 Куплено дней подписки: всего {stats['paid_days_total']}, за месяц {stats['paid_days_month']}\n\n"
            f"Период расчёта выплат: {month_start} — {month_end}\n"
            f"{payout_text}"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    "📋 Скопировать ссылку",
                    copy_text=CopyTextButton(link),
                )
            ]
        )
        rows.append([InlineKeyboardButton("ℹ️ Информация", callback_data="settings:referral:info")])
        rows.append([InlineKeyboardButton("✏️ Изменить имя", callback_data="settings:referral:create")])
    rows.append([InlineKeyboardButton("Progressor · 3 продукта", callback_data="pg:menu")])
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")])
    return text, InlineKeyboardMarkup(rows)


def build_referral_info_screen() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "ℹ️ Как работает реферальная программа\n\n"
        "1) Создаёте персональную ссылку и отправляете её людям.\n"
        "2) Мы фиксируем переход, когда человек заходит по ссылке и нажимает /start.\n"
        "   Привязка к рефереру одноразовая и закрепляется за Telegram ID пользователя.\n"
        "3) В статистику оплат попадают только успешные платежи (не pending/не отменённые).\n"
        "4) Расчёт выплаты идёт за текущий месяц: с 1-го по последнее число.\n\n"
        "Проценты:\n"
        "• до 100 приглашённых — 15%\n"
        "• от 100 до 1000 — 20%\n"
        "• от 1000 до 10000 — 25%\n"
        "• более 10000 — 30%\n\n"
        "Выплата считается отдельно по ₽ и ⭐ исходя из успешных оплат по вашей реферальной базе."
    )
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(BACK_BTN, callback_data="settings:referral")]]
    )
    return text, kb


async def build_referral_admin_screen(page: int = 0, search: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    total, rows = await list_referral_profiles(search=search, limit=REFERRAL_ADMIN_PAGE_SIZE, offset=page * REFERRAL_ADMIN_PAGE_SIZE)
    caption = f"Управление рефералками\n\nВсего ссылок: {total}."
    if search:
        caption += f"\nФильтр: {search}"
    buttons: list[list[InlineKeyboardButton]] = []
    for row in rows:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"👤 {row['display_name']} · {row.get('invited_total', 0)}",
                    callback_data=f"settings:refadmin:user:{row['user_id']}",
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"settings:refadmin:page:{page-1}"))
    if (page + 1) * REFERRAL_ADMIN_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"settings:refadmin:page:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔎 Поиск", callback_data="settings:refadmin:search")])
    buttons.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")])
    return caption, InlineKeyboardMarkup(buttons)


async def _get_trainer_link_by_id(link_id: int):
    async with connect_db() as db:
        cur = await db.execute(
            """
            SELECT id, trainer_user_id, trainee_user_id, status
            FROM trainer_links
            WHERE id = ?
            """,
            (link_id,),
        )
        return await cur.fetchone()


async def _format_trainer_user_display(user_id: int) -> str:
    info = await find_user_by_id(user_id)
    if info:
        _, tg_id, username = info
        if username:
            return f"@{username}"
        if tg_id:
            return f"ID {tg_id}"
    return f"ID {user_id}"


async def _load_trainer_lists(
    user_id: int, pending_offset: int, accepted_offset: int
) -> tuple[int, list, int, int, list, int]:
    safe_pending = max(0, pending_offset)
    safe_accepted = max(0, accepted_offset)
    pending_total = await count_trainer_requests(user_id)
    accepted_total = await count_trainer_trainees(user_id)
    requests: list
    while True:
        requests = await list_trainer_requests(
            user_id, limit=TRAINER_LIST_LIMIT, offset=safe_pending
        )
        if requests or safe_pending == 0:
            break
        safe_pending = max(0, safe_pending - TRAINER_LIST_LIMIT)
    trainees: list
    while True:
        trainees = await list_trainer_trainees(
            user_id, limit=TRAINER_LIST_LIMIT, offset=safe_accepted
        )
        if trainees or safe_accepted == 0:
            break
        safe_accepted = max(0, safe_accepted - TRAINER_LIST_LIMIT)
    return (
        safe_pending,
        requests,
        pending_total,
        safe_accepted,
        trainees,
        accepted_total,
    )


async def _render_trainer_overview(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    message: str | None = None,
    pending_offset: int | None = None,
    accepted_offset: int | None = None,
) -> None:
    context.user_data.pop(TRAINER_REQUESTS_VIEW_KEY, None)
    current_pending = (
        pending_offset
        if pending_offset is not None
        else context.user_data.get(TRAINER_PENDING_OFFSET_KEY, 0)
    )
    current_accepted = (
        accepted_offset
        if accepted_offset is not None
        else context.user_data.get(TRAINER_ACCEPTED_OFFSET_KEY, 0)
    )
    (
        pending_offset,
        requests,
        pending_total,
        accepted_offset,
        trainees,
        accepted_total,
    ) = await _load_trainer_lists(user_id, current_pending, current_accepted)
    profile = await _fetch_trainer_profile(user_id)
    is_trainer = bool(profile and profile[0])
    accepts_requests = bool(profile and len(profile) > 2 and profile[2])
    context.user_data[TRAINER_PENDING_OFFSET_KEY] = pending_offset
    context.user_data[TRAINER_ACCEPTED_OFFSET_KEY] = accepted_offset
    accepted_has_prev = accepted_offset > 0
    accepted_has_next = accepted_offset + TRAINER_LIST_LIMIT < accepted_total
    accepted_last_offset = max(
        0,
        math.floor(max(accepted_total - 1, 0) / TRAINER_LIST_LIMIT)
        * TRAINER_LIST_LIMIT,
    )
    active_sub = await get_active_subscription(user_id)
    limit = await get_trainer_max_trainees(user_id)
    user_ids: set[int] = set()
    for entry in requests:
        user_ids.add(int(entry[1]))
    for entry in trainees:
        user_ids.add(int(entry[1]))
    labels: dict[int, str] = {}
    if user_ids:
        ordered_ids = list(user_ids)
        resolved = await asyncio.gather(
            *(_format_trainer_user_display(uid) for uid in ordered_ids)
        )
        labels = dict(zip(ordered_ids, resolved))
    last_completion_map: dict[int, tuple] = {}
    next_training_map: dict[int, datetime | None] = {}
    if trainees:
        trainee_ids = [int(entry[1]) for entry in trainees]
        trainee_system_ids = await asyncio.gather(
            *(_active_system_id(uid) for uid in trainee_ids)
        )
        completion_rows = await asyncio.gather(
            *(
                get_last_completion_for_user(uid, system_id=int(sid or 0))
                for uid, sid in zip(trainee_ids, trainee_system_ids)
            )
        )
        last_completion_map = dict(zip(trainee_ids, completion_rows))

        async def _next_training_dt(trainee_id: int) -> datetime | None:
            reminders = await list_user_reminders(trainee_id)
            if not reminders:
                return None
            tz_code = await get_user_timezone(trainee_id)
            zone = resolve_user_zone(tz_code)
            now_local = datetime.now(UTC).astimezone(zone)
            return _find_next_reminder_time(reminders, now_local, zone)

        next_training_rows = await asyncio.gather(
            *(_next_training_dt(uid) for uid in trainee_ids)
        )
        next_training_map = dict(zip(trainee_ids, next_training_rows))

    def _format_last_completion(entry) -> str:
        if not entry:
            return "нет данных"
        completed_at = None
        try:
            completed_at = entry[1]
        except (IndexError, TypeError):
            try:
                completed_at = entry["completed_at"]  # type: ignore[index]
            except (KeyError, TypeError):
                completed_at = None
        if not completed_at:
            return "нет данных"
        try:
            completed_dt = datetime.fromisoformat(str(completed_at))
        except ValueError:
            return str(completed_at).split("T")[0] or "нет данных"
        return completed_dt.date().strftime("%d.%m.%Y")

    def _format_next_training(entry: datetime | None) -> str:
        if not entry:
            return "не запланирована"
        try:
            return entry.strftime("%d.%m.%Y %H:%M")
        except Exception:
            return str(entry)

    lines: list[str] = []
    if message:
        lines.extend([message, ""])
    lines.append("Подопечные:")
    if trainees:
        for entry in trainees:
            trainee_id = int(entry[1])
            label = labels.get(trainee_id, f"ID {trainee_id}")
            lines.append(f"• {label}")
            last_completion = last_completion_map.get(trainee_id)
            last_label = _format_last_completion(last_completion)
            lines.append(f"  последняя тренировка: {last_label}")
            next_training = next_training_map.get(trainee_id)
            next_label = _format_next_training(next_training)
            lines.append(f"  следующая тренировка: {next_label}")
    else:
        lines.append("• Пока нет подопечных.")
    lines.append("")
    if active_sub:
        lines.append("С активной подпиской вам доступно неограниченное количество подопечных.")
    else:
        lines.append(
            f"Без подписки вам доступно до {limit} подопечных одновременно."
        )
    if is_trainer:
        lines.append("")
        lines.append(
            "Прием заявок: "
            + ("включен" if accepts_requests else "отключен")
            + "."
        )
        lines.append(f"Активных заявок: {pending_total}.")
    rows: list[list[InlineKeyboardButton]] = []
    for entry in trainees:
        trainee_id = int(entry[1])
        label = labels.get(trainee_id, f"ID {trainee_id}")
        rows.append(
            [
                InlineKeyboardButton(
                    label, callback_data=f"trainer:view:{trainee_id}"
                )
            ]
        )
    if accepted_has_prev or accepted_has_next:
        nav_row = []
        if accepted_offset > 0:
            nav_row.append(
                InlineKeyboardButton(
                    "⏮️ К первым",
                    callback_data="trainer:list:accepted:first",
                )
            )
        if accepted_has_prev:
            nav_row.append(
                InlineKeyboardButton(
                    "⬅️ Предыдущие подопечные",
                    callback_data="trainer:list:accepted:prev",
                )
            )
        if accepted_has_next:
            nav_row.append(
                InlineKeyboardButton(
                    "Следующие подопечные ➡️",
                    callback_data="trainer:list:accepted:next",
                )
            )
        if accepted_has_next:
            nav_row.append(
                InlineKeyboardButton(
                    "К последним ⏭️",
                    callback_data=f"trainer:list:accepted:last:{accepted_last_offset}",
                )
            )
        if nav_row:
            rows.append(nav_row)
    rows.append(
        [InlineKeyboardButton("📨 Мои заявки", callback_data="trainer:list:pending")]
    )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:root")])
    kb = InlineKeyboardMarkup(rows)
    await show_screen(q, context, "\n".join(lines), kb, user_id)


async def _render_trainer_requests_view(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    message: str | None = None,
    pending_offset: int | None = None,
) -> None:
    profile = await _fetch_trainer_profile(user_id)
    accepts_requests = bool(profile and profile[0] and len(profile) > 2 and profile[2])
    if not accepts_requests:
        context.user_data.pop(TRAINER_REQUESTS_VIEW_KEY, None)
        await _render_trainer_overview(
            q, context, user_id, message="Прием заявок отключен."
        )
        return
    current_pending = (
        pending_offset
        if pending_offset is not None
        else context.user_data.get(TRAINER_PENDING_OFFSET_KEY, 0)
    )
    (
        safe_pending,
        requests,
        pending_total,
        _,
        _,
        _,
    ) = await _load_trainer_lists(user_id, current_pending, 0)
    context.user_data[TRAINER_PENDING_OFFSET_KEY] = safe_pending
    context.user_data[TRAINER_REQUESTS_VIEW_KEY] = True
    pending_has_prev = safe_pending > 0
    pending_has_next = safe_pending + TRAINER_LIST_LIMIT < pending_total
    pending_last_offset = max(
        0,
        math.floor(max(pending_total - 1, 0) / TRAINER_LIST_LIMIT)
        * TRAINER_LIST_LIMIT,
    )
    user_ids: set[int] = set()
    for entry in requests:
        user_ids.add(int(entry[1]))
    labels: dict[int, str] = {}
    if user_ids:
        ordered_ids = list(user_ids)
        resolved = await asyncio.gather(
            *(_format_trainer_user_display(uid) for uid in ordered_ids)
        )
        labels = dict(zip(ordered_ids, resolved))
    lines: list[str] = []
    if message:
        lines.extend([message, ""])
    lines.append("Мои заявки:")
    if requests:
        for entry in requests:
            trainee_id = int(entry[1])
            label = labels.get(trainee_id, f"ID {trainee_id}")
            lines.append(f"• {label}")
    else:
        lines.append("• Нет заявок.")
    kb_rows: list[list[InlineKeyboardButton]] = []
    for entry in requests:
        link_id = int(entry[0])
        kb_rows.append(
            [
                InlineKeyboardButton(
                    labels.get(int(entry[1]), f"ID {entry[1]}") or "—",
                    callback_data="noop",
                ),
                InlineKeyboardButton(
                    "❌", callback_data=f"trainer:req:decline:{link_id}"
                ),
                InlineKeyboardButton(
                    "✅", callback_data=f"trainer:req:accept:{link_id}"
                ),
            ]
        )
    if pending_has_prev or pending_has_next:
        nav_row: list[InlineKeyboardButton] = []
        if safe_pending > 0:
            nav_row.append(
                InlineKeyboardButton(
                    "⏮️ В начало", callback_data="trainer:list:pending:first"
                )
            )
        if pending_has_prev:
            nav_row.append(
                InlineKeyboardButton(
                    "⬅️ Предыдущие", callback_data="trainer:list:pending:prev"
                )
            )
        if pending_has_next:
            nav_row.append(
                InlineKeyboardButton(
                    "Следующие ➡️", callback_data="trainer:list:pending:next"
                )
            )
        if pending_has_next:
            nav_row.append(
                InlineKeyboardButton(
                    "В конец ⏭️",
                    callback_data=f"trainer:list:pending:last:{pending_last_offset}",
                )
            )
        if nav_row:
            kb_rows.append(nav_row)
    kb_rows.append(
        [
            InlineKeyboardButton(
                "🚫 Отключить прием заявок", callback_data="trainer:requests:off"
            )
        ]
    )
    kb_rows.append(
        [
            InlineKeyboardButton(
                "⬅️ К подопечным", callback_data="trainer:list"
            )
        ]
    )
    kb_rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:root")])
    kb = InlineKeyboardMarkup(kb_rows)
    await show_screen(q, context, "\n".join(lines), kb, user_id)


def clear_linear_state(
    user_data: dict,
    preserve_keys: set[str] | None = None,
) -> None:
    preserved = preserve_keys or set()
    for key in list(user_data.keys()):
        if key.startswith("awaiting_") and key not in preserved:
            user_data.pop(key, None)
    linear_keys = {
        "add_group", BROADCAST_STATE_KEY, RUNNING_INPUT_KEY, MEASUREMENT_INPUT_KEY,
        MEASUREMENT_CUSTOM_KEY, MEASUREMENT_CATEGORY_INPUT_KEY, LIBRARY_CUSTOM_KEY,
    }
    for key in linear_keys:
        if key in preserved:
            continue
        user_data.pop(key, None)


_main_menu_locks: dict[int,asyncio.Lock] = {}

async def send_main_message(bot,chat_id,text,reply_markup=None,**kwargs):
    async with _main_menu_locks.setdefault(chat_id,asyncio.Lock()):
        return await _send_main_unlocked(bot,chat_id,text,reply_markup,**kwargs)

async def _progressor_render(update,context,text,markup):
    query=update.callback_query
    if query and query.message and update.effective_chat.id not in last_messages:
        from progressor_native_subscription import menu_anchor
        from settings import DB_PATH
        previous=menu_anchor(DB_PATH,update.effective_chat.id)
        remember_message(update.effective_chat.id,previous or query.message.message_id)
    return await send_main_message(context.bot,update.effective_chat.id,text,markup,parse_mode=None)

async def _progressor_scheduled_send(application,user_id,text,markup):
    from progressor_bot import notification_preflight
    notification_preflight(application,user_id,'gym')
    return await send_main_message(application.bot,user_id,text,markup,parse_mode=None,force_new=True)

async def _send_main_unlocked(
    bot,
    chat_id: int | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    **kwargs,
) -> Message:
    if chat_id is None:
        raise ValueError("chat_id is required to send a message")
    previous_id = last_messages.get(chat_id)
    if previous_id is None:
        from progressor_native_subscription import menu_anchor
        from settings import DB_PATH
        previous_id=menu_anchor(DB_PATH,chat_id)
        if previous_id:last_messages[chat_id]=previous_id
    if kwargs.pop('force_new',False):
        msg=await bot.send_message(chat_id=chat_id,text=text,reply_markup=reply_markup,**kwargs)
        remember_message(chat_id,msg.message_id)
        if previous_id and previous_id!=msg.message_id:
            from progressor_bot import retire_owned_menu
            await retire_owned_menu(bot,chat_id,previous_id)
        return msg
    editable_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key
        in {
            "parse_mode",
            "disable_web_page_preview",
            "entities",
            "link_preview_options",
        }
    }
    if previous_id is not None:
        try:
            msg = await bot.edit_message_text(
                chat_id=chat_id,
                message_id=previous_id,
                text=text,
                reply_markup=reply_markup,
                **editable_kwargs,
            )
        except BadRequest as edit_error:
            error_text = (edit_error.message or "").lower()
            if "message is not modified" in error_text or "not modified" in error_text:
                remember_message(chat_id, previous_id)
                return SimpleNamespace(chat_id=chat_id, message_id=previous_id)
            if "message to edit not found" in error_text:
                last_messages.pop(chat_id, None)
            else:
                try:
                    await bot.delete_message(chat_id, previous_id)
                except BadRequest as delete_error:
                    delete_text = (delete_error.message or "").lower()
                    if "message to delete not found" in delete_text:
                        last_messages.pop(chat_id, None)
                    elif "can't be deleted" in delete_text:
                        logger.debug(
                            "Previous message %s in chat %s cannot be deleted",
                            previous_id,
                            chat_id,
                        )
                        last_messages.pop(chat_id, None)
                    else:
                        remember_message(chat_id, previous_id)
                        logger.warning(
                            "Failed to delete previous message", exc_info=True
                        )
                        raise
                except Forbidden:
                    logger.debug(
                        "Bot is not allowed to delete message %s in chat %s",
                        previous_id,
                        chat_id,
                    )
                    last_messages.pop(chat_id, None)
                else:
                    last_messages.pop(chat_id, None)
        except TelegramError:
            try:
                await bot.delete_message(chat_id, previous_id)
            except BadRequest as delete_error:
                delete_text = (delete_error.message or "").lower()
                if "message to delete not found" in delete_text:
                    last_messages.pop(chat_id, None)
                else:
                    remember_message(chat_id, previous_id)
                    logger.warning(
                        "Failed to delete previous message", exc_info=True
                    )
                    raise
            except Forbidden:
                remember_message(chat_id, previous_id)
                raise
            else:
                last_messages.pop(chat_id, None)
        else:
            remember_message(chat_id, msg.message_id)
            return msg
    last_messages.pop(chat_id, None)
    msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        **kwargs,
    )
    remember_message(msg.chat_id, msg.message_id)
    return msg


async def reset_main_message(bot, chat_id: int | None) -> None:
    if chat_id is None:
        return
    previous_id = last_messages.get(chat_id)
    if previous_id is None:
        return
    try:
        await bot.delete_message(chat_id, previous_id)
    except BadRequest as delete_error:
        error_text = (delete_error.message or "").lower()
        if "message to delete not found" in error_text:
            last_messages.pop(chat_id, None)
            return
        if "can't be deleted" in error_text:
            logger.debug(
                "Previous message %s in chat %s cannot be deleted during reset",
                previous_id,
                chat_id,
            )
        else:
            logger.warning("Failed to delete main message", exc_info=True)
        last_messages.pop(chat_id, None)
        _remove_message_from_history(chat_id, previous_id)
        return
    except Forbidden:
        logger.debug(
            "Bot is not allowed to delete message %s in chat %s during reset",
            previous_id,
            chat_id,
        )
    except TelegramError:
        logger.warning("Unexpected error when deleting main message", exc_info=True)
    last_messages.pop(chat_id, None)
    _remove_message_from_history(chat_id, previous_id)


async def send_main_message_fresh(
    bot,
    chat_id: int | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    **kwargs,
):
    if chat_id is None:
        raise ValueError("chat_id is required to send a message")
    await reset_main_message(bot, chat_id)
    return await send_main_message(
        bot,
        chat_id,
        text,
        reply_markup=reply_markup,
        **kwargs,
    )

async def safe_update_screen(
    q,
    context,
    text,
    reply_markup=None,
    *,
    remember: bool = True,
    **kwargs,
):
    message = getattr(q, "message", None)
    chat = getattr(message, "chat", None) if message else None
    chat_id = getattr(chat, "id", None) if chat else getattr(message, "chat_id", None)
    message_id = getattr(message, "message_id", None)
    edit_func = getattr(q, "edit_message_text", None)
    if edit_func is None:
        if chat_id is None:
            return
        sent = await context.bot.send_message(
            chat_id, text, reply_markup=reply_markup, **kwargs
        )
        if remember:
            remember_message(chat_id, getattr(sent, "message_id", None))
        return
    try:
        await edit_func(text, reply_markup=reply_markup, **kwargs)
    except BadRequest as e:
        error_text = (e.message or "").lower()
        if "not modified" in error_text:
            if remember:
                remember_message(chat_id, message_id)
            return
        if "message can't be edited" in error_text or "message can't be modified" in error_text:
            if chat_id is None or message_id is None:
                raise
            if remember:
                try:
                    await context.bot.delete_message(chat_id, message_id)
                except BadRequest as delete_error:
                    delete_text = (delete_error.message or "").lower()
                    if "message to delete not found" in delete_text:
                        last_messages.pop(chat_id, None)
                    elif "can't be deleted" in delete_text:
                        logger.debug(
                            "Message %s in chat %s cannot be deleted during update",
                            message_id,
                            chat_id,
                        )
                        last_messages.pop(chat_id, None)
                    else:
                        remember_message(chat_id, message_id)
                        raise
                except Forbidden:
                    remember_message(chat_id, message_id)
                    raise
                else:
                    last_messages.pop(chat_id, None)
                new_message = await send_main_message(
                    context.bot,
                    chat_id,
                    text,
                    reply_markup=reply_markup,
                    **kwargs,
                )
            else:
                new_message = await context.bot.send_message(
                    chat_id,
                    text,
                    reply_markup=reply_markup,
                    **kwargs,
                )
            return new_message
        if "message to edit not found" in error_text:
            if chat_id is None:
                raise
            if remember:
                new_message = await send_main_message(
                    context.bot,
                    chat_id,
                    text,
                    reply_markup=reply_markup,
                    **kwargs,
                )
            else:
                new_message = await context.bot.send_message(
                    chat_id,
                    text,
                    reply_markup=reply_markup,
                    **kwargs,
                )
            return new_message
        raise
    if remember:
        remember_message(chat_id, message_id)
    return getattr(q, "message", None)


async def show_screen(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    user_id: int,
    **kwargs,
) -> None:
    async def _update_wizard_screen(
        q,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
        reply_markup: InlineKeyboardMarkup | None,
        **kwargs,
    ):
        message = getattr(q, "message", None)
        chat = getattr(message, "chat", None) if message else None
        chat_id = (
            getattr(chat, "id", None) if chat else getattr(message, "chat_id", None)
        )
        message_id = getattr(message, "message_id", None)
        stored_chat_id = context.user_data.get("wizard_chat_id")
        stored_message_id = context.user_data.get("wizard_msg_id")
        if chat_id is None:
            chat_id = stored_chat_id
        if message_id is None:
            message_id = stored_message_id

        def _needs_new_message(error_text: str) -> bool:
            return any(
                phrase in error_text
                for phrase in (
                    "message can't be edited",
                    "message can't be modified",
                    "message to edit not found",
                )
            )

        if message is not None and message_id is not None:
            try:
                edited = await message.edit_text(
                    text, reply_markup=reply_markup, **kwargs
                )
            except BadRequest as e:
                error_text = (e.message or "").lower()
                if "not modified" in error_text:
                    context.user_data["wizard_chat_id"] = chat_id
                    context.user_data["wizard_msg_id"] = message_id
                    return message
                if _needs_new_message(error_text):
                    if chat_id is None:
                        raise
                    new_message = await context.bot.send_message(
                        chat_id,
                        text,
                        reply_markup=reply_markup,
                        **kwargs,
                    )
                    context.user_data["wizard_chat_id"] = new_message.chat_id
                    context.user_data["wizard_msg_id"] = new_message.message_id
                    return new_message
                raise
            else:
                context.user_data["wizard_chat_id"] = chat_id
                context.user_data["wizard_msg_id"] = edited.message_id
                return edited

        if message_id is not None and chat_id is not None:
            try:
                edited = await context.bot.edit_message_text(
                    text=text,
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                    **kwargs,
                )
            except BadRequest as e:
                error_text = (e.message or "").lower()
                if "not modified" in error_text:
                    return None
                if _needs_new_message(error_text):
                    new_message = await context.bot.send_message(
                        chat_id,
                        text,
                        reply_markup=reply_markup,
                        **kwargs,
                    )
                    context.user_data["wizard_chat_id"] = new_message.chat_id
                    context.user_data["wizard_msg_id"] = new_message.message_id
                    return new_message
                raise
            else:
                context.user_data["wizard_chat_id"] = chat_id
                context.user_data["wizard_msg_id"] = edited.message_id
                return edited

        if chat_id is None:
            raise RuntimeError("Cannot determine chat for wizard screen")

        new_message = await context.bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            **kwargs,
        )
        context.user_data["wizard_chat_id"] = new_message.chat_id
        context.user_data["wizard_msg_id"] = new_message.message_id
        return new_message

    prefs = await load_ui_preferences(user_id)
    prepared_text, prepared_markup = prepare_ui_output(text, reply_markup, prefs)
    if context.user_data.get("wizard_onboarding"):
        return await _update_wizard_screen(
            q,
            context,
            prepared_text,
            prepared_markup,
            **kwargs,
        )
    remember = True
    return await safe_update_screen(
        q,
        context,
        prepared_text,
        prepared_markup,
        remember=remember,
        **kwargs,
    )


def wizard_apply_text(prefs: UiPreferences) -> str:
    text = (
        "Применить настройки Дня 1 ко всем остальным дням? Это можно менять позже в настройках."
    )
    if prefs.verbose_level:
        return (
            f"{text}\nЕсли хочешь настроить дни по-разному, выбери вариант с отдельной"
            " настройкой и добавь упражнения вручную."
        )
    return text


def wizard_apply_kb(total_days: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("Ко всем дням", callback_data="wiz:apply:all")]
    ]
    if total_days > 1:
        rows.append(
            [InlineKeyboardButton("Настроить День 2", callback_data="wiz:apply:next:2")]
        )
    return InlineKeyboardMarkup(rows)

async def try_delete(msg):
    try:
        await msg.delete()
    except BadRequest:
        pass

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    exc = context.error
    logger.warning("Unhandled error: %s", exc)
    try:
        raise exc
    except Forbidden:
        pass
    except RetryAfter as e:
        await asyncio.sleep(int(getattr(e, "retry_after", 3)))
    except (TimedOut, NetworkError, BadRequest):
        pass


async def require_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return True

async def get_custom_groups(user_id: int, context) -> dict[str, str]:
    groups = context.user_data.get("custom_groups")
    if groups is None:
        rows = await list_user_muscle_groups(user_id)
        groups = {code: name for code, name in rows}
        context.user_data["custom_groups"] = groups
    return groups


KB_PAGE_STATE = "kb_catalog_pages"


def get_kb_page(context, scope: str, group: str, day: int | None = None) -> int:
    store = context.user_data.get(KB_PAGE_STATE)
    if not store:
        return 0
    return store.get((scope, day, group), 0)


def set_kb_page(context, scope: str, group: str, page: int, day: int | None = None):
    store = context.user_data.setdefault(KB_PAGE_STATE, {})
    store[(scope, day, group)] = page

def day_groups_text(i: int) -> str:
    return f"{t('DAY')} {i}. Что тренируешь в этот день? Выбери группы, затем «Далее»."

def day_exercises_text(i: int, group: str, custom: dict[str, str] | None = None) -> str:
    name = MG_NAMES.get(group)
    if not name and custom:
        name = custom.get(group, group)
    if not name:
        name = group
    return f"{t('DAY')} {i} — {name}. Выбери упражнения или добавь своё. Потом жми «{t('DONE')}»."

def render_day_text(
    i: int,
    label: str,
    ex_rows: list[tuple[int, str, str, int, int]],
    custom: dict[str, str] | None = None,
    summaries: dict[int, str] | None = None,
    last_done: dict[int, str] | None = None,
    prefs: UiPreferences | None = None,
) -> str:
    summaries = summaries or {}
    last_done = last_done or {}
    prefs = prefs or UiPreferences()
    groups: dict[str, list[tuple[int, str, int, int]]] = {}
    for ue_id, name, group, done, ex_id, _note in ex_rows:
        resolved = resolve_group(name, group)
        groups.setdefault(resolved, []).append((ue_id, name, done, ex_id))
    if not groups:
        return (
            f"{t('DAY')} {i} — {label}\n"
            "Пока нет упражнений. Добавь упражнения, чтобы запланировать тренировку."
        )
    lines = [
        f"{t('DAY')} {i} — {label}",
    ]
    maybe_hint(
        lines,
        prefs,
        (
            "Открой нужную группу, чтобы отметить подходы.",
            "Открой нужную группу, чтобы отметить подходы и настроить упражнение. В карточке можно добавить или удалить подходы, скорректировать вес и сразу сохранить результат в расписании.",
        ),
    )
    total = len(groups)
    for idx, (code, names) in enumerate(groups.items()):
        gname = MG_NAMES.get(code)
        if not gname and custom:
            gname = custom.get(code, code)
        if not gname:
            gname = code
        lines.append("")
        lines.append(gname)
        for ue_id, n, d, ex_id in names:
            mark = status_icon(prefs, bool(d))
            extra = summaries.get(ue_id)
            last = last_done.get(ex_id)
            lines.append(compose_exercise_line(mark, n, extra, last))
        if idx < total - 1:
            lines.append("────────")
    return "\n".join(lines)

def baseline_text(
    name: str,
    sets: int,
    reps: int,
    seconds: int,
    weight: float,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> str:
    return f"{name} — {format_sets_value(sets, reps, seconds, weight, with_weight, kind)}"


def render_baseline_progress(
    done: list[str],
    name: str,
    sets: int,
    reps: int,
    seconds: int,
    weight: float,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> str:
    lines = list(done)
    if name:
        if lines:
            lines.append("────────")
        lines.append(
            baseline_text(
                name,
                sets,
                reps,
                seconds,
                weight,
                with_weight=with_weight,
                kind=kind,
            )
        )
    return "\n".join(lines)

INSTANT_BASE_KEY = "instant_baseline"
FLEX_SELECTED_KEY = "flex_selected"
FILL_EDITOR_KEY = "fill_editor"


@dataclass
class FillEditorState:
    day: int
    ue_id: int
    is_library: bool
    with_weight: bool
    kind: str
    name: str
    group: str
    sheet_day: int | None
    sheet_page: int
    selected_before: int | None
    sets: list[dict[str, int | float | None]] = field(default_factory=list)
    pointer: int = 0
    default_reps: int = 0
    default_seconds: int = 0
    default_weight: float = 0.0
    first_time: bool = False
    can_set_seconds: bool = False
    can_set_weight: bool = False


def _coerce_fill_reps(value: object) -> int:
    return max(_safe_int(value), 0)


def _coerce_optional_seconds(value: object | None) -> int | None:
    if value is None:
        return None
    return max(_safe_int(value), 0)


def _coerce_optional_weight(value: object | None) -> float | None:
    if value is None:
        return None
    return max(_safe_float(value), 0.0)


def _build_fill_set_entry(
    reps: object,
    *,
    include_seconds: bool,
    seconds: object | None = None,
    include_weight: bool,
    weight: object | None = None,
) -> dict[str, int | float | None]:
    return {
        "reps": _coerce_fill_reps(reps),
        "seconds": None
        if not include_seconds
        else _coerce_optional_seconds(seconds),
        "weight": None
        if not include_weight
        else _coerce_optional_weight(weight),
    }


def _default_optional_seconds(state: FillEditorState) -> int | None:
    if not state.can_set_seconds:
        return None
    if state.default_seconds <= 0:
        return None
    return max(_safe_int(state.default_seconds), 0)


def _default_optional_weight(state: FillEditorState) -> float | None:
    if not state.can_set_weight:
        return None
    if state.default_weight <= 0:
        return None
    return max(_safe_float(state.default_weight), 0.0)


def _create_fill_set_entry(
    state: FillEditorState,
    *,
    reps: object,
    seconds: object | None = None,
    weight: object | None = None,
) -> dict[str, int | float | None]:
    return _build_fill_set_entry(
        reps,
        include_seconds=state.can_set_seconds,
        seconds=seconds,
        include_weight=state.can_set_weight,
        weight=weight,
    )


def render_instant_baseline(
    name: str,
    sets: int,
    reps: int,
    seconds: int,
    weight: float,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> str:
    lines = [name, ""]
    if with_weight:
        lines.extend(
            [
                "Настрой количество сетов, повторений и рабочий вес для этого упражнения.",
                "Используй кнопки с крупным шагом, чтобы быстрее указать значения.",
            ]
        )
    elif kind == "duration":
        lines.extend(
            [
                "Настрой количество подходов и длительность удержания.",
                "Используй кнопки, чтобы быстро изменить время в секундах.",
            ]
        )
    else:
        lines.extend(
            [
                "Настрой количество сетов и повторений для этого упражнения.",
                "Используй кнопки, чтобы быстро скорректировать повторения.",
            ]
        )
    lines.append("")
    lines.append(
        f"Сейчас: {format_sets_value(sets, reps, seconds, weight, with_weight, kind)}"
    )
    return "\n".join(lines)


def instant_baseline_view(info: dict) -> tuple[str, InlineKeyboardMarkup]:
    sets, reps, seconds, weight = info["values"]
    with_weight = info.get("with_weight", True)
    kind = info.get("kind", "reps")
    text = render_instant_baseline(
        info["name"], sets, reps, seconds, weight, with_weight=with_weight, kind=kind
    )
    kb = baseline_kb(
        info["day"],
        sets,
        reps,
        seconds,
        weight,
        prefix=f"ib:{info['source']}",
        user_id=info["user_id"],
        exercise_id=info["exercise_id"],
        include_skip_all=False,
        with_weight=with_weight,
        kind=kind,
    )
    return text, kb


async def start_instant_baseline(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    day: int,
    exercise_id: int,
    source: str,
    group: str,
    edit_func,
) -> bool:
    row = await get_exercise_details(exercise_id)
    if not row:
        return False
    name, default_group, _owner_user_id = row
    if not group:
        group = default_group
    resolved_group = resolve_group(name, group)
    existing = await get_baseline(user_id, day, exercise_id)
    if existing:
        values = list(existing)
    else:
        values = [0, 0, 0, 0.0]
    while len(values) < 4:
        values.append(0 if len(values) < 3 else 0.0)
    with_weight, kind = get_display_flags(resolved_group, name)
    if not with_weight:
        values[3] = 0.0
    info = {
        "source": source,
        "user_id": user_id,
        "day": day,
        "group": group,
        "exercise_id": exercise_id,
        "name": name,
        "values": values,
        "with_weight": with_weight,
        "resolved_group": resolved_group,
        "kind": kind,
    }
    context.user_data.pop(INSTANT_BASE_KEY, None)
    context.user_data[INSTANT_BASE_KEY] = info
    text, kb = instant_baseline_view(info)
    await edit_func(text, kb)
    return True


async def finish_instant_baseline(q, context, user_id: int, info: dict):
    source = info.get("source")
    day = info.get("day")
    group = info.get("group")
    context.user_data.pop(INSTANT_BASE_KEY, None)
    if source == "wiz":
        await show_exercises(q, user_id, day, group, context)
    elif source == "day":
        await show_day_add_exercises_view(q, user_id, day, group, context)
    else:
        await show_day_group_view(q, user_id, day, group, context)


def _flex_key(day: int, ue_id: int) -> str:
    return f"{day}:{ue_id}"


def get_flex_selected(context, day: int, ue_id: int) -> int | None:
    store = context.user_data.get(FLEX_SELECTED_KEY, {})
    return store.get(_flex_key(day, ue_id))


def set_flex_selected(context, day: int, ue_id: int, set_no: int | None):
    store = context.user_data.setdefault(FLEX_SELECTED_KEY, {})
    key = _flex_key(day, ue_id)
    if set_no is None:
        store.pop(key, None)
    else:
        store[key] = set_no


def get_fill_state(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int
) -> FillEditorState | None:
    store = context.user_data.get(FILL_EDITOR_KEY)
    if not store:
        return None
    return store.get((chat_id, message_id))


def set_fill_state(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    state: FillEditorState,
):
    store = context.user_data.setdefault(FILL_EDITOR_KEY, {})
    store[(chat_id, message_id)] = state


def clear_fill_state(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    store = context.user_data.get(FILL_EDITOR_KEY)
    if not store:
        return
    store.pop((chat_id, message_id), None)
    if not store:
        context.user_data.pop(FILL_EDITOR_KEY, None)


def _fill_icon_key(group: str) -> str:
    if group == "kb":
        return "kb"
    if group == "metcon":
        return "metcon"
    return "strength"




def render_fill_editor(state: FillEditorState, prefs: UiPreferences) -> str:
    icon = emoji_for(prefs, _fill_icon_key(state.group)) if prefs.emoji_enabled else ""
    title = f"{icon} {state.name}".strip() if icon else state.name
    lines = [title, ""]
    if state.kind == "duration":
        lines.append(
            "Редактируй каждый сет отдельно: переключайся между ними стрелками и меняй показатели кнопками ниже."
        )
        lines.append(
            "Так можно переписать весь результат тренировки, не переходя в другие экраны."
        )
        lines.append("Текущий сет помечен стрелкой ▶︎ слева от строки.")
        lines.append("")
        if not state.sets:
            lines.append("Сетов пока нет. Добавь первый, чтобы записать подход.")
        else:
            for idx, item in enumerate(state.sets, start=1):
                prefix = "▶︎ " if idx - 1 == state.pointer else ""
                reps = max(_safe_int(item.get("reps")), 0)
                seconds = max(_safe_int(item.get("seconds")), 0)
                weight = _safe_float(item.get("weight")) if state.with_weight else 0.0
                value = format_flex_value(
                    reps, seconds, weight, state.with_weight, "duration"
                )
                lines.append(f"{prefix}{idx}. {value}")
        return "\n".join(lines)

    if not state.sets:
        lines.append(
            "Задай пример: сколько сетов, повторов и килограммов у тебя было в прошлый раз или планируется сегодня."
        )
        lines.append(
            "Введи точные числа — кнопки ниже помогут быстро выставить повторы и вес."
        )
        lines.append("")
        lines.append("Когда будешь готов, нажми «＋ сет» и начни фиксировать подходы один за другим.")
        return "\n".join(lines)

        lines.append("Теперь запиши каждый сет своим чередом.")
        lines.append(
            "Заполни количество повторений и килограмм в текущей строке: стрелки листают сеты, кнопки снизу меняют значения."
        )
        lines.append(
        "Нажимай «＋ сет», чтобы добавить следующий — новые строки копируют предыдущие значения для быстрой правки."
    )
    lines.append("Текущий сет помечен стрелкой ▶︎ слева от строки.")
    lines.append("")
    for idx, item in enumerate(state.sets, start=1):
        prefix = "▶︎ " if idx - 1 == state.pointer else ""
        reps = max(_safe_int(item.get("reps")), 0)
        seconds = max(_safe_int(item.get("seconds")), 0)
        weight = max(_safe_float(item.get("weight")), 0.0) if state.with_weight else 0.0
        value = format_flex_value(reps, seconds, weight, state.with_weight, state.kind)
        lines.append(f"{prefix}{idx}. {value}")
    return "\n".join(lines)


def _rep_unit(kind: str) -> str:
    return "повт."


def _major_rep_step(kind: str) -> int:
    return 5



def _build_flex_fill_keyboard(state: FillEditorState) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if state.sets:
        rows.append(
            [
                InlineKeyboardButton("◀︎ Сет", callback_data="fill:flex:nav:-1"),
                InlineKeyboardButton(
                    f"Сет {state.pointer + 1}/{len(state.sets)}",
                    callback_data="noop",
                ),
                InlineKeyboardButton("Сет ▶︎", callback_data="fill:flex:nav:1"),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("＋ сет", callback_data="fill:flex:add"),
            InlineKeyboardButton("− сет", callback_data="fill:flex:del"),
        ]
    )
    unit = _rep_unit(state.kind)
    rep_steps = [10, 5, 1] if state.first_time else [_major_rep_step(state.kind), 1]
    seen_rep_steps: set[int] = set()
    for step in rep_steps:
        if step <= 0 or step in seen_rep_steps:
            continue
        seen_rep_steps.add(step)
        rows.append(
            [
                InlineKeyboardButton(
                    f"＋{step} {unit}", callback_data=f"fill:flex:inc:reps:{step}"
                ),
                InlineKeyboardButton(
                    f"−{step} {unit}", callback_data=f"fill:flex:inc:reps:-{step}"
                ),
            ]
        )
    if state.can_set_seconds:
        sec_steps = [60, 30, 10, 5, 1] if state.first_time else [30, 5, 1]
        rows.append(
            [
                InlineKeyboardButton(
                    f"＋{step} сек", callback_data=f"fill:flex:inc:sec:{step}"
                )
                for step in sec_steps
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    f"−{step} сек", callback_data=f"fill:flex:inc:sec:-{step}"
                )
                for step in sec_steps
            ]
        )
    if state.can_set_weight:
        weight_steps = (
            [0.5, 1, 3, 5, 10, 25, 50]
            if state.first_time
            else [0.5, 3, 10, 25]
        )
        weight_labels = [format_weight_value(step) for step in weight_steps]
        rows.append(
            [
                InlineKeyboardButton(
                    f"＋{label} кг", callback_data=f"fill:flex:inc:kg:{label}"
                )
                for label in weight_labels
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    f"−{label} кг", callback_data=f"fill:flex:inc:kg:-{label}"
                )
                for label in weight_labels
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("Сохранить", callback_data="fill:flex:apply"),
            InlineKeyboardButton("Отмена", callback_data="fill:flex:cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def build_fill_keyboard(state: FillEditorState) -> InlineKeyboardMarkup:
    return _build_flex_fill_keyboard(state)


async def finish_fill_editor(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    state: FillEditorState,
    prefs: UiPreferences,
):
    clear_fill_state(context, q.message.chat_id, q.message.message_id)
    if state.is_library:
        await show_library_exercise_view(q, user_id, state.group, state.ue_id, context)
        return
    selected = get_flex_selected(context, state.day, state.ue_id)
    view = await render_exercise_view(
        user_id, state.day, state.ue_id, selected, prefs=prefs
    )
    set_flex_selected(context, state.day, state.ue_id, view.selected_set)
    kb = build_exercise_actions_markup(
        view,
        day=state.day,
        ue_id=state.ue_id,
        group=view.group,
        prefs=prefs,
        context=context,
    )
    await show_screen(q, context, view.text, kb, user_id)


async def apply_fill_changes(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    state: FillEditorState,
    prefs: UiPreferences,
):
    if not await _owns_active_exercise(user_id, state.day, state.ue_id):
        await q.answer('Упражнение больше недоступно. Откройте дневник заново.', show_alert=True)
        return
    today_str = await get_user_local_date(user_id)
    system_id = await _active_system_id(user_id)
    session_id = await get_or_create_today_session(user_id, today_str, state.day, system_id=system_id)
    template: list[tuple[int, int | None, float | None]] = []
    for item in state.sets:
        reps_value = _coerce_fill_reps(item.get("reps"))
        seconds_value = (
            _coerce_optional_seconds(item.get("seconds"))
            if state.can_set_seconds
            else None
        )
        weight_value = (
            _coerce_optional_weight(item.get("weight"))
            if state.can_set_weight
            else None
        )
        has_payload = (
            reps_value > 0
            or (seconds_value is not None and seconds_value > 0)
            or (weight_value is not None and weight_value > 0)
        )
        if not has_payload:
            continue
        template.append((reps_value, seconds_value, weight_value))
    await apply_sets_template(session_id, state.ue_id, template)
    if template:
        sets = await fetch_exercise_sets(session_id, state.ue_id)
        if sets:
            target_index = min(state.pointer, len(sets) - 1)
            set_flex_selected(context, state.day, state.ue_id, sets[target_index][0])
        else:
            set_flex_selected(context, state.day, state.ue_id, None)
        suppress_completed_day_warning(context, user_id, state.day)
    else:
        set_flex_selected(context, state.day, state.ue_id, None)
    await finish_fill_editor(q, context, user_id, state, prefs)

async def open_fill_editor(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    day: int,
    ue_id: int,
    session_id: int,
    is_library: bool,
    sheet_day: int | None,
    sheet_page: int,
    selected_before: int | None,
    prefs: UiPreferences,
):
    ex_id, name, raw_group = await get_exercise_info(ue_id)
    group = resolve_group(name, raw_group)
    base_with_weight, kind = get_display_flags(group, name)
    weight_enabled = base_with_weight or group in {"workout", "core"}
    baseline = await get_baseline(user_id, day, ex_id)
    last_values = await get_session_last_values(session_id, ue_id)
    sets_rows = await fetch_exercise_sets(session_id, ue_id)
    first_time = len(sets_rows) == 0
    work_sets = filter_work_sets(sets_rows)
    default_reps = 0
    default_seconds = 0
    default_weight = 0.0
    can_set_seconds = kind == "duration"
    can_set_weight = weight_enabled
    if baseline:
        default_reps = max(_safe_int(baseline[1]), 0)
        default_seconds = max(_safe_int(baseline[2]), 0)
        if weight_enabled:
            default_weight = max(_safe_float(baseline[3]), 0.0)
    elif last_values:
        default_reps = max(_safe_int(last_values[0]), 0)
        default_seconds = max(_safe_int(last_values[1]), 0)
        if weight_enabled:
            default_weight = max(_safe_float(last_values[2]), 0.0)

    sets_payload: list[dict[str, int | float | None]] = [
        _build_fill_set_entry(
            reps,
            include_seconds=can_set_seconds,
            seconds=seconds if can_set_seconds else None,
            include_weight=can_set_weight,
            weight=weight if can_set_weight else None,
        )
        for _, reps, seconds, weight in work_sets
    ]
    if not sets_payload:
        if baseline and baseline[0] > 0:
            sets_payload = [
                _build_fill_set_entry(
                    baseline[1],
                    include_seconds=can_set_seconds,
                    seconds=
                    baseline[2]
                    if can_set_seconds and max(_safe_int(baseline[2]), 0) > 0
                    else None,
                    include_weight=can_set_weight,
                    weight=
                    baseline[3]
                    if can_set_weight and max(_safe_float(baseline[3]), 0.0) > 0
                    else None,
                )
                for _ in range(baseline[0])
            ]
        elif (
            default_reps
            or (can_set_seconds and default_seconds > 0)
            or (can_set_weight and default_weight > 0)
        ):
            sets_payload = [
                _build_fill_set_entry(
                    default_reps,
                    include_seconds=can_set_seconds,
                    seconds=
                    default_seconds
                    if can_set_seconds and default_seconds > 0
                    else None,
                    include_weight=can_set_weight,
                    weight=
                    default_weight
                    if can_set_weight and default_weight > 0
                    else None,
                )
            ]
    pointer = 0
    if sets_payload and selected_before:
        pointer = min(max(selected_before - 1, 0), len(sets_payload) - 1)
    state = FillEditorState(
        day=day,
        ue_id=ue_id,
        is_library=is_library,
        with_weight=weight_enabled,
        kind=kind,
        name=name,
        group=group,
        sheet_day=sheet_day,
        sheet_page=sheet_page,
        selected_before=selected_before,
        sets=sets_payload,
        pointer=pointer,
        default_reps=default_reps,
        default_seconds=default_seconds,
        default_weight=default_weight if weight_enabled else 0.0,
        first_time=first_time,
        can_set_seconds=can_set_seconds,
        can_set_weight=can_set_weight,
    )
    clear_fill_state(context, q.message.chat_id, q.message.message_id)
    set_fill_state(context, q.message.chat_id, q.message.message_id, state)
    text = render_fill_editor(state, prefs)
    kb = build_fill_keyboard(state)
    await show_screen(q, context, text, kb, user_id)

async def handle_fill_callback(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    data: str,
    prefs: UiPreferences,
):
    state = get_fill_state(context, q.message.chat_id, q.message.message_id)
    parts = data.split(":")
    if not state or len(parts) < 3:
        await q.answer()
        return
    if not await _owns_active_exercise(user_id, state.day, state.ue_id):
        await q.answer('Упражнение больше недоступно.', show_alert=True)
        return
    mode = parts[1]
    if mode != "flex":
        await q.answer()
        return
    action = parts[2]
    if action == "nav" and len(parts) >= 4 and state.sets:
        delta = int(parts[3])
        state.pointer = max(0, min(state.pointer + delta, len(state.sets) - 1))
    elif action == "add":
        if state.sets:
            current_item = state.sets[state.pointer]
            base_reps = current_item.get("reps")
            base_seconds = current_item.get("seconds")
            base_weight = current_item.get("weight")
        else:
            base_reps = state.default_reps
            base_seconds = _default_optional_seconds(state)
            base_weight = _default_optional_weight(state)
        insert_at = state.pointer + 1 if state.sets else 0
        state.sets.insert(
            insert_at,
            _create_fill_set_entry(
                state,
                reps=base_reps,
                seconds=base_seconds,
                weight=base_weight,
            ),
        )
        state.pointer = insert_at
    elif action == "del" and state.sets:
        state.sets.pop(state.pointer)
        if state.pointer >= len(state.sets):
            state.pointer = max(0, len(state.sets) - 1)
    elif action == "inc" and len(parts) >= 5:
        target = parts[3]
        delta = float(parts[4])
        if not state.sets:
            state.sets.append(
                _create_fill_set_entry(
                    state,
                    reps=state.default_reps,
                    seconds=_default_optional_seconds(state),
                    weight=_default_optional_weight(state),
                )
            )
            state.pointer = 0
        current = state.sets[state.pointer]
        if target == "reps":
            current_reps = _safe_int(current.get("reps"))
            current["reps"] = max(0, current_reps + int(delta))
        elif target == "sec" and state.can_set_seconds:
            current_seconds = _safe_int(current.get("seconds"))
            new_seconds = max(0, current_seconds + int(delta))
            current["seconds"] = new_seconds if new_seconds > 0 else None
        elif target == "kg" and state.can_set_weight:
            current_weight = _safe_float(current.get("weight"))
            new_weight = max(0.0, current_weight + delta)
            current["weight"] = new_weight if new_weight > 0 else None
    elif action == "apply":
        await apply_fill_changes(q, context, user_id, state, prefs)
        return
    elif action == "cancel":
        await finish_fill_editor(q, context, user_id, state, prefs)
        return
    text = render_fill_editor(state, prefs)
    kb = build_fill_keyboard(state)
    await show_screen(q, context, text, kb, user_id)
    await q.answer()

MEASUREMENTS_SHOW_ALL_KEY = "measurements_show_all"
MEASUREMENT_INPUT_KEY = "measurement_input"
MEASUREMENT_EXISTING_KEY = "measurement_existing"
MEASUREMENT_CUSTOM_KEY = "measurement_custom_input"
MEASUREMENT_CUSTOM_CACHE_KEY = "measurement_custom_items"
MEASUREMENT_CATEGORY_CACHE_KEY = "measurement_categories"
MEASUREMENT_CATEGORY_INPUT_KEY = "measurement_category_input"
MEASUREMENT_CATEGORY_BACK_KEY = "measurement_category_back_target"
LIBRARY_CUSTOM_KEY = "library_custom_input"
DAY_DELETE_SCOPE_KEY = "day_delete_scope"
COMPLETED_DAY_WARNING_SUPPRESS_KEY = "completed_day_warning_suppress"

MEASUREMENT_CUSTOM_CATEGORY = {
    "code": "custom",
    "letter": "E",
    "name": "Свои замеры",
}

SHARE_RESULTS_STATE_KEY = "settings_share_results_state"
SHARE_RESULTS_PRIMARY_MSG_ID_KEY = "settings_share_results_primary_message_id"
SHARE_RESULTS_EXERCISE_LIMIT = 5
SHARE_RESULTS_WINDOW_DAYS = 90
SHARE_RESULTS_COPY_TEXT_MAX_LENGTH = 4096


@dataclass(frozen=True)
class ShareExerciseProgress:
    name: str
    start_weight: float
    end_weight: float
    delta: float


@dataclass
class ShareResultsView:
    text_html: str
    copy_text: str
    all_exercises: list[ShareExerciseProgress]
    displayed_exercises: list[ShareExerciseProgress]


MEASUREMENT_CATEGORIES = [
    {"code": "body", "letter": "A", "name": "Масса/состав тела"},
    {"code": "circumference", "letter": "B", "name": "Окружности"},
    {"code": "records", "letter": "C", "name": "Производные/силовые контрольные"},
    {"code": "vitals", "letter": "D", "name": "Витальные показатели"},
]

FEATURED_MEASUREMENTS = {"body_weight", "body_fat", "chest", "hips"}
FEATURED_MEASUREMENTS_ORDER = ["body_weight", "body_fat", "chest", "hips"]


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


async def _load_training_summary(user_id: int) -> tuple[int, datetime | None, datetime | None]:
    from db import recorded_training_summary
    count, first, last = await recorded_training_summary(user_id)
    return count, _parse_iso_datetime(first), _parse_iso_datetime(last)


async def _load_featured_measurement_changes(
    user_id: int,
) -> list[tuple[str, float, dict]]:
    entries: list[tuple[str, float, dict]] = []
    async with connect_db() as db:
        for metric in FEATURED_MEASUREMENTS_ORDER:
            cur = await db.execute(
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
            cur = await db.execute(
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
            item = get_measurement_item(metric) or {
                "name": metric,
                "unit": "",
                "precision": 1,
            }
            precision = int(item.get("precision", 1) or 1)
            threshold = 0.5 * 10 ** (-precision)
            if abs(delta) < threshold:
                continue
            entries.append((metric, delta, item))
    entries.sort(key=lambda entry: abs(entry[1]), reverse=True)
    return entries[:4]


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


def _format_weight_value(value: float) -> str:
    text = f"{value:.1f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if not text:
        return "0"
    return text


def _convert_progress_entries(
    entries: Sequence[dict],
) -> list[ShareExerciseProgress]:
    results: list[ShareExerciseProgress] = []
    for entry in entries:
        try:
            delta = float(entry.get("delta", 0.0) or 0.0)
            start = float(entry.get("start_weight", 0.0) or 0.0)
            end = float(entry.get("end_weight", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        name = str(entry.get("name") or "").strip()
        if not name or delta <= 0 or end <= 0 or end <= start:
            continue
        results.append(
            ShareExerciseProgress(
                name=name,
                start_weight=start,
                end_weight=end,
                delta=end - start,
            )
        )
    results.sort(key=lambda item: item.delta, reverse=True)
    return results


def _select_share_exercises(
    all_exercises: Sequence[ShareExerciseProgress],
    *,
    randomize: bool = False,
) -> list[ShareExerciseProgress]:
    items = list(all_exercises)
    if not items:
        return []
    limit = min(SHARE_RESULTS_EXERCISE_LIMIT, len(items))
    if randomize and len(items) > limit:
        selected = random.sample(items, k=limit)
    else:
        selected = items[:limit]
    return sorted(selected, key=lambda entry: entry.delta, reverse=True)


def _render_share_results_text(
    header: str,
    measurements: Sequence[str],
    exercises: Sequence[ShareExerciseProgress],
    link: str,
) -> str:
    lines: list[str] = [escape(header)]
    body_lines: list[str] = []
    if measurements:
        body_lines.append("Вот мои результаты:")
        body_lines.append("Изменения в теле:")
        for line in measurements:
            body_lines.append(escape(line))
    if exercises:
        if not body_lines:
            body_lines.append("Вот мои результаты:")
        body_lines.append("Силовой прогресс за последние три месяца:")
        for progress in exercises:
            delta_text = _format_weight_value(progress.delta)
            start_text = _format_weight_value(progress.start_weight)
            end_text = _format_weight_value(progress.end_weight)
            body_lines.append(
                "• {name}: +{delta} кг (с {start} до {end} кг)".format(
                    name=escape(progress.name),
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
        f"<a href=\"{escape(link)}\">Подключайся</a>."
    )
    return "\n".join(lines)


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


def _copy_text_length(text: str) -> int:
    return len(text.encode("utf-8"))


def _render_share_results_copy_text(
    header: str,
    measurements: Sequence[str],
    exercises: Sequence[ShareExerciseProgress],
    link: str,
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
            delta_text = _format_weight_value(progress.delta)
            start_text = _format_weight_value(progress.start_weight)
            end_text = _format_weight_value(progress.end_weight)
            body_lines.append(
                "• {name}: +{delta} кг (с {start} до {end} кг)".format(
                    name=progress.name,
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

    def _join(parts: Sequence[str]) -> str:
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


async def build_share_results_view(
    user_id: int,
    *,
    all_exercises: Sequence[ShareExerciseProgress] | None = None,
    sample: Sequence[ShareExerciseProgress] | None = None,
) -> ShareResultsView:
    trainings_count, first, last = await _load_training_summary(user_id)
    measurement_entries = await _load_featured_measurement_changes(user_id)
    link = _get_public_link()
    has_training_data = trainings_count > 0 and first is not None and last is not None
    measurements = [
        _format_share_measurement_line(item, delta)
        for _metric, delta, item in measurement_entries
    ]
    if all_exercises is None:
        progress_entries = await list_exercise_weight_progress(
            user_id, days=SHARE_RESULTS_WINDOW_DAYS
        )
        all_exercises = _convert_progress_entries(progress_entries)
    else:
        all_exercises = list(all_exercises)
    if sample is None:
        displayed = _select_share_exercises(all_exercises)
    else:
        displayed = _select_share_exercises(sample, randomize=False)
        if not displayed and all_exercises:
            displayed = _select_share_exercises(all_exercises)

    if not has_training_data and not measurements and not displayed:
        lines = [
            "Я только начинаю тренироваться с этим ботом 💪",
            "Скоро здесь будет мой прогресс.",
            "",
            (
                "Если хочешь начать вместе со мной, то "
                f"<a href=\"{escape(link)}\">Подключайся</a>."
            ),
        ]
        fallback_text = "\n".join(lines)
        fallback_copy = "\n".join(
            [
                "Я только начинаю тренироваться с этим ботом 💪",
                "Скоро здесь будет мой прогресс.",
                "",
                f"Если хочешь начать вместе со мной, то Подключайся 👉 {link}",
            ]
        )
        return ShareResultsView(
            text_html=fallback_text,
            copy_text=fallback_copy,
            all_exercises=list(all_exercises),
            displayed_exercises=list(displayed),
        )

    weeks = _calculate_training_weeks(first, last)
    week_label = _plural_ru(weeks, ("неделю", "недели", "недель"))
    training_label = _plural_ru(
        trainings_count, ("тренировку", "тренировки", "тренировок")
    )
    header = (
        f"Я тренируюсь с ботом уже {weeks} {week_label} "
        f"({trainings_count} {training_label}) 💪"
    )
    text_html = _render_share_results_text(header, measurements, displayed, link)
    copy_text = _render_share_results_copy_text(header, measurements, displayed, link)
    return ShareResultsView(
        text_html=text_html,
        copy_text=copy_text,
        all_exercises=list(all_exercises),
        displayed_exercises=list(displayed),
    )


def build_share_results_keyboard(*, enable_shuffle: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if enable_shuffle:
        rows.append(
            [
                InlineKeyboardButton(
                    "🎲 Сменить упражнения",
                    callback_data="settings:share_results:shuffle",
                )
            ]
        )

    rows.append(
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu:settings")]
    )

    return InlineKeyboardMarkup(rows)


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
        "Время комплекса (сек)",
        "records",
        "",
        prompt="Укажи время комплекса в формате ММ:СС или ЧЧ:ММ:СС.",
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


def _custom_measurement_item(code, name, category_code):
    return {'code': code, 'name': name,
            'category': (category_code or '').strip() or MEASUREMENT_CUSTOM_CATEGORY['code'],
            'unit': '', 'precision': 1, 'optional': False,
            'prompt': f'Введи значение для «{name}» (например: 10).'}


async def load_custom_measurements(
    user_id: int, context: ContextTypes.DEFAULT_TYPE
) -> list[dict]:
    rows = await list_custom_measurements(user_id)
    items: list[dict] = []
    for code, name, category_code in rows:
        items.append(_custom_measurement_item(code, name, category_code))
    context.user_data[MEASUREMENT_CUSTOM_CACHE_KEY] = items
    context.user_data['measurement_custom_cache_owner'] = user_id
    return items


def get_cached_custom_measurements(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    owner = context.user_data.get('measurement_custom_cache_owner')
    if owner != context.user_data.get('_input_owner', owner): return []
    return context.user_data.get(MEASUREMENT_CUSTOM_CACHE_KEY, [])


async def load_measurement_categories(
    user_id: int, context: ContextTypes.DEFAULT_TYPE
) -> list[dict]:
    rows = await list_measurement_categories(user_id)
    categories = [
        {"code": code, "letter": letter.upper(), "name": name}
        for code, letter, name in rows
    ]
    context.user_data[MEASUREMENT_CATEGORY_CACHE_KEY] = categories
    return categories


def get_cached_measurement_categories(
    context: ContextTypes.DEFAULT_TYPE,
) -> list[dict]:
    return context.user_data.get(MEASUREMENT_CATEGORY_CACHE_KEY, [])


def format_category_label(category: dict) -> str:
    letter = (category.get("letter") or "").strip()
    name = category.get("name", "")
    if letter:
        return f"{letter}) {name}"
    return name


def measurement_categories_list(
    user_categories: list[dict],
    *,
    include_custom_fallback: bool = False,
    custom_items: list[dict] | None = None,
) -> list[tuple[str, str]]:
    categories: list[dict] = []
    categories.extend(MEASUREMENT_CATEGORIES)
    extra = sorted(
        (cat for cat in user_categories if cat.get("letter")),
        key=lambda cat: cat["letter"],
    )
    categories.extend(extra)
    if include_custom_fallback and custom_items:
        if any(
            item.get("category") == MEASUREMENT_CUSTOM_CATEGORY["code"]
            for item in custom_items
        ):
            categories.append(MEASUREMENT_CUSTOM_CATEGORY)
    return [(cat["code"], format_category_label(cat)) for cat in categories]


def collect_existing_category_letters(
    user_categories: list[dict], custom_items: list[dict] | None = None
) -> set[str]:
    letters = {cat["letter"] for cat in MEASUREMENT_CATEGORIES if cat.get("letter")}
    letters.update(
        cat["letter"] for cat in user_categories if cat.get("letter")
    )
    if custom_items and any(
        item.get("category") == MEASUREMENT_CUSTOM_CATEGORY["code"]
        for item in custom_items
    ):
        if MEASUREMENT_CUSTOM_CATEGORY.get("letter"):
            letters.add(MEASUREMENT_CUSTOM_CATEGORY["letter"])
    return letters


def next_category_letter(
    user_categories: list[dict], custom_items: list[dict] | None = None
) -> str:
    letters = collect_existing_category_letters(user_categories, custom_items)
    max_letter = max(letters) if letters else "@"
    start_ord = ord(max_letter) + 1 if max_letter else ord("A")
    current = max(start_ord, ord("A"))
    while current <= ord("Z"):
        candidate = chr(current)
        if candidate not in letters:
            return candidate
        current += 1
    return "Z"


async def delete_measurement_category_with_contents(
    user_id: int, category_code: str, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    custom_items = await load_custom_measurements(user_id, context)
    affected = [
        item for item in custom_items if item.get("category") == category_code
    ]
    for item in affected:
        await delete_custom_measurement(user_id, item["code"])
    removed = await delete_measurement_category(user_id, category_code)
    await load_custom_measurements(user_id, context)
    await load_measurement_categories(user_id, context)
    return removed


async def prompt_custom_measurement_value(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int | None,
    message_id: int | None,
    back_callback: str,
    name: str,
    category_code: str,
) -> str | None:
    if chat_id is None or message_id is None:
        context.user_data.pop(MEASUREMENT_CUSTOM_KEY, None)
        return None
    code = await add_custom_measurement(user_id, name, category_code)
    await load_custom_measurements(user_id, context)
    context.user_data.pop(MEASUREMENT_CUSTOM_KEY, None)
    context.user_data[MEASUREMENT_INPUT_KEY] = {
        "action": "add",
        "metric": code,
        "chat_id": chat_id,
        "message_id": message_id,
        "category": category_code,
        "target_user_id": user_id,
    }
    prompt = f"Введи значение для «{name}» (например: 10)."
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(BACK_BTN, callback_data=back_callback)]]
    )
    prefs = await load_ui_preferences(user_id)
    text, kb = prepare_ui_output(prompt, kb, prefs)
    await context.bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=kb,
    )
    remember_message(chat_id, message_id)
    return code


async def show_measurements_manage_overview(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    category_back_target: str,
    back_callback: str = "measure:back",
    prompt: str = "Выбери категорию:",
):
    custom_items = await load_custom_measurements(user_id, context)
    user_categories = await load_measurement_categories(user_id, context)
    categories = measurement_categories_list(
        user_categories,
        include_custom_fallback=True,
        custom_items=custom_items,
    )
    kb = measurements_manage_overview_kb(
        categories,
        include_delete=bool(custom_items or user_categories),
        back_callback=back_callback,
        context=context,
    )
    context.user_data[MEASUREMENT_CATEGORY_BACK_KEY] = category_back_target
    await show_screen(q, context, prompt, kb, user_id)


async def show_measure_edit_menu(q, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    custom_items = await load_custom_measurements(user_id, context)
    user_categories = await load_measurement_categories(user_id, context)
    has_custom = bool(custom_items)
    rows = await list_measurement_metrics(user_id)
    metrics_by_category: dict[str, list[tuple[str, str]]] = {}
    for code, _ in rows:
        item = await get_owned_measurement_item(user_id, code)
        if item and not item.get("derived"):
            metrics_by_category.setdefault(item["category"], []).append(
                (code, item["name"])
            )
    if not metrics_by_category and not has_custom:
        await q.answer("Пока нечего изменять.", show_alert=True)
        return False
    context.user_data[MEASUREMENT_EXISTING_KEY] = metrics_by_category
    available = [
        (code, title)
        for code, title in measurement_categories_list(
            user_categories,
            include_custom_fallback=True,
            custom_items=custom_items,
        )
        if code in metrics_by_category
    ]
    if not available and not has_custom:
        await q.answer("Пока нечего изменять.", show_alert=True)
        return False
    rows_markup: list[list[InlineKeyboardButton]] = []
    for code, title in available:
        rows_markup.append(
            [
                InlineKeyboardButton(
                    title,
                    callback_data=f"measure:edit:cat:{code}",
                )
            ]
        )
    if has_custom:
        rows_markup.append(
            [
                InlineKeyboardButton(
                    "Удалить свои замеры",
                    callback_data="measure:edit:customrm",
                )
            ]
        )
    rows_markup.append([InlineKeyboardButton(BACK_BTN, callback_data="measure:back")])
    await show_screen(
        q,
        context,
        "Какую группу изменить?",
        InlineKeyboardMarkup(rows_markup),
        user_id,
    )
    return True


async def show_custom_measurements_delete_menu(
    q, context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> bool:
    items = await load_custom_measurements(user_id, context)
    if not items:
        await q.answer("Собственных замеров больше нет.", show_alert=True)
        await show_measure_edit_menu(q, context, user_id)
        return False
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(
                    f"− {item['name']}",
                    callback_data=f"measure:edit:customrm:{item['code']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="measure:edit")])
    await show_screen(
        q,
        context,
        "Какой замер удалить?",
        InlineKeyboardMarkup(rows),
        user_id,
    )
    return True


def get_measurement_items(category: str) -> list[dict]:
    return [item for item in MEASUREMENT_ITEMS if item["category"] == category]


def get_measurement_item(code: str) -> dict | None:
    """Only the public built-in catalog is process-global."""
    return MEASUREMENT_MAP.get(code)


async def get_owned_measurement_item(user_id: int, code: str) -> dict | None:
    built_in = get_measurement_item(code)
    if built_in: return built_in
    for owned_code, name, category in await list_custom_measurements(user_id):
        if owned_code == code: return _custom_measurement_item(code, name, category)
    return None


def format_measurements_header(last_update: str | None) -> str:
    if not last_update:
        return f"{t('MEAS_TITLE')} — {t('EMPTY_MEAS')}"
    try:
        dt = datetime.fromisoformat(last_update)
        label = dt.strftime("%d.%m.%Y")
    except Exception:
        label = last_update.split("T")[0]
    return f"{t('MEAS_TITLE')} — {label}"


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


async def get_measurement_history(
    user_id: int,
    code: str,
    cache: dict[str, list[tuple[float, str | None, str]]],
    limit: int = 5,
) -> list[tuple[float, str | None, str]]:
    cache_key = f"{user_id}:{code}:{limit}"
    if cache_key in cache:
        return cache[cache_key]
    item = await get_owned_measurement_item(user_id, code)
    if not item:
        cache[cache_key] = []
        return []
    if item.get("derived") == "lean_mass":
        weight_history = await get_measurement_history(
            user_id, "body_weight", cache, limit
        )
        fat_history = await get_measurement_history(user_id, "body_fat", cache, limit)
        history = compute_lean_mass_history(weight_history, fat_history)[:limit]
    else:
        rows = await fetch_measurement_history(user_id, code, limit=limit)
        history = rows or []
    cache[cache_key] = history
    return history


def format_measurement_line(
    item: dict,
    history: list[tuple[float, str | None, str]],
) -> str | None:
    if not history:
        note = item.get("note")
        if note:
            return f"{item['name']} — нет данных ({note})"
        return f"{item['name']} — нет данных"
    value_text = format_measurement_value(item, history[0])
    delta_text = ""
    if len(history) > 1:
        delta_text = format_measurement_delta(item, history[0], history[1])
    if delta_text:
        return f"{item['name']} — {value_text} ({delta_text})"
    return f"{item['name']} — {value_text}"


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
        syst = int(round(_finite_input_number(parts[0])))
        diast = int(round(_finite_input_number(parts[1])))
        return float(syst), str(diast)
    value = _finite_input_number(raw)
    return value, None


async def build_measurements_view(
    user_id: int, context: ContextTypes.DEFAULT_TYPE
) -> tuple[str, InlineKeyboardMarkup]:
    show_all = context.user_data.get(MEASUREMENTS_SHOW_ALL_KEY, False)
    custom_items = await load_custom_measurements(user_id, context)
    user_categories = await load_measurement_categories(user_id, context)
    last_update = await get_measurements_last_update(user_id)
    header = format_measurements_header(last_update)
    cache: dict[str, list[tuple[float, str | None, str]]] = {}
    lines: list[str] = []
    categories = measurement_categories_list(
        user_categories,
        include_custom_fallback=True,
        custom_items=custom_items,
    )
    custom_by_category: dict[str, list[dict]] = defaultdict(list)
    for item in custom_items:
        custom_by_category[item.get("category")].append(item)
    custom_codes = {item["code"] for item in custom_items}
    for code, title in categories:
        base_items = [item for item in MEASUREMENT_ITEMS if item["category"] == code]
        items = list(base_items)
        items.extend(custom_by_category.get(code, []))
        category_lines: list[str] = []
        for item in items:
            history = await get_measurement_history(user_id, item["code"], cache)
            has_data = bool(history)
            is_custom = item["code"] in custom_codes
            if not (
                show_all or has_data or item["code"] in FEATURED_MEASUREMENTS or is_custom
            ):
                continue
            line = format_measurement_line(item, history)
            if line:
                category_lines.append(line)
        if category_lines:
            if lines:
                lines.append("────────")
            lines.append(title)
            lines.extend(category_lines)
    if not lines:
        lines.append("Пока нет замеров. Добавь показатели, чтобы отслеживать прогресс.")
    text = header + "\n\n" + "\n".join(lines)
    context_line = get_acting_context_line(context, user_id, subject="замеры")
    if context_line:
        text = f"{context_line}\n\n{text}"
    return text, measurements_main_kb(show_all, context=context)


def _format_measurement_history_entries(
    item: dict, history: list[tuple[float, str | None, str]], zone: ZoneInfo
) -> list[str]:
    lines: list[str] = []
    for idx, entry in enumerate(history):
        value_text = format_measurement_value(item, entry)
        date_text = format_measurement_date(entry[2], zone)
        delta_text = ""
        if idx + 1 < len(history):
            delta = format_measurement_delta(item, entry, history[idx + 1])
            if delta:
                delta_text = f" ({delta})"
        lines.append(f"{date_text} — {value_text}{delta_text}")
    return lines


async def build_measurements_history_view(
    user_id: int, context: ContextTypes.DEFAULT_TYPE
) -> tuple[str, InlineKeyboardMarkup]:
    tz_name = await get_user_timezone(user_id)
    zone = resolve_user_zone(tz_name)
    cache: dict[str, list[tuple[float, str | None, str]]] = {}
    lines: list[str] = []
    custom_items = await load_custom_measurements(user_id, context)
    user_categories = await load_measurement_categories(user_id, context)
    categories = measurement_categories_list(
        user_categories,
        include_custom_fallback=True,
        custom_items=custom_items,
    )
    custom_by_category: dict[str, list[dict]] = defaultdict(list)
    for item in custom_items:
        custom_by_category[item.get("category")].append(item)
    for code, title in categories:
        base_items = [item for item in MEASUREMENT_ITEMS if item["category"] == code]
        items = list(base_items)
        items.extend(custom_by_category.get(code, []))
        category_lines: list[str] = []
        for item in items:
            history = await get_measurement_history(
                user_id, item["code"], cache, limit=10
            )
            if len(history) < 2:
                continue
            category_lines.append(item["name"])
            category_lines.extend(
                _format_measurement_history_entries(item, history, zone)
            )
        if category_lines:
            if lines:
                lines.append("────────")
            lines.append(title)
            lines.extend(category_lines)
    if not lines:
        lines.append(
            "История пока пуста. Добавь как минимум два значения для показателя, чтобы увидеть изменения."
        )
    text = "История замеров:\n\n" + "\n".join(lines)
    context_line = get_acting_context_line(
        context, user_id, subject="историю замеров"
    )
    if context_line:
        text = f"{context_line}\n\n{text}"
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(BACK_BTN, callback_data="measure:back")]]
    )
    return text, kb


def summarize_previous_sets(
    sets: list[tuple[int, int, int, float]],
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> str:
    if not sets:
        return ""
    grouped = _compress_flex_triplets(sets, with_weight=with_weight, kind=kind)
    parts: list[str] = []
    for entry in grouped:
        value = format_flex_value(
            int(entry["reps"]), int(entry.get("seconds", 0)), float(entry["weight"]), with_weight, kind
        )
        count = int(entry["count"])
        if count > 1:
            parts.append(f"{count}× {value}")
        else:
            parts.append(value)
    return " · ".join(parts)


def summarize_baseline(
    values: tuple[int, int, int, float] | None,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> str:
    if not values:
        return ""
    sets, reps, seconds, weight = values
    formatted = format_flex_value(reps, seconds, weight, with_weight, kind)
    return f"{sets}× {formatted}"


def format_last_done_label(date_str: str, reference: datetime | None = None) -> str:
    if not date_str:
        return ""
    reference = reference or datetime.now()
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return date_str
    fmt = "%d.%m" if parsed.year == reference.year else "%d.%m.%Y"
    return parsed.strftime(fmt)


def build_last_done_dict(rows: list[tuple[int, str]]) -> dict[int, str]:
    reference = datetime.now()
    result: dict[int, str] = {}
    for ex_id, date_str in rows:
        if not date_str:
            continue
        result[ex_id] = format_last_done_label(date_str, reference)
    return result


def compose_exercise_line(mark: str, name: str, summary: str | None, last_done: str | None) -> str:
    details: list[str] = []
    if last_done:
        details.append(last_done)
    if summary:
        summary_lines = str(summary).splitlines()
        if summary_lines:
            details.append(summary_lines[0])
    prefix = f"{mark} " if mark else ""
    base = f"{prefix}{name}".strip()
    if details:
        base = f"{base} — {' — '.join(details)}"
    return base.strip()


def build_prev_label(prev_summary: str | None, prev_date: str | None) -> str:
    summary = (prev_summary or "").strip()
    date = (prev_date or "").strip()
    if summary and date:
        return f"{date} — {summary}"
    if summary:
        return summary
    if date:
        return date
    return t("NOT_FIXED")


def build_note_lines(
    current_note: str | None, previous_note: str | None
) -> list[str]:
    if current_note:
        return [f"{t('NOTE')}: {current_note}"]
    if previous_note:
        return [f"{t('LAST_NOTE')}: {previous_note}"]
    return []


def format_plan_value(
    baseline: tuple[int, int, int, float] | None,
    group_key: str,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> str:
    if not baseline:
        return t("NOT_SET")
    if group_key == "kb":
        value = format_kb_plan(baseline, kind=kind)
        return value if value != "—" else t("NOT_SET")
    sets, reps, seconds, weight = baseline
    return format_compact_sets_value(sets, reps, seconds, weight, with_weight, kind)


def format_strength_done_value(
    summary: dict[str, int | float] | None, *, with_weight: bool = True
) -> str:
    if not summary:
        return "0 сетов"
    sets = summary.get("sets") if isinstance(summary, dict) else None
    if isinstance(sets, list):
        work_sets: list[tuple[int, int, int, float]] = list(sets)
        count = len(work_sets)
        if count == 0:
            return "0 сетов"
        kind = str(summary.get("kind", "reps"))
        details = summarize_previous_sets(
            work_sets, with_weight=with_weight, kind=kind
        )
        label = f"{count} {pluralize_sets(count)}"
        return f"{label} — {details}" if details else label
    count = int(summary.get("sets_count") or 0)
    reps = int(summary.get("last_reps") or 0)
    seconds = int(summary.get("last_seconds") or 0)
    weight = float(summary.get("last_weight") or 0.0)
    if count <= 0:
        return "0 сетов"
    kind = str(summary.get("kind", "reps"))
    if kind == "duration":
        detail = format_metric_value(reps, seconds, kind)
        if with_weight and weight > 0:
            detail = f"{detail} при {format_weight_value(weight)} кг"
    else:
        if with_weight:
            detail = f"{reps} повт. при {format_weight_value(weight)} кг"
        else:
            detail = f"{reps} повт."
    return f"{count} (последний {detail})"


def resolve_user_zone(tz_name: str | None) -> ZoneInfo:
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


async def get_user_local_date(user_id: int) -> str:
    tz_name = await get_user_timezone(user_id)
    zone = resolve_user_zone(tz_name)
    return datetime.now(zone).strftime("%Y-%m-%d")


async def fetch_day_sheet_data(
    user_id: int,
    day_index: int,
    date_str: str,
) -> list[dict]:
    system_id = await _active_system_id(user_id)
    ex_rows = await fetch_day_exercises(user_id, day_index, date_str, system_id=system_id)
    session_id = await get_session_for_day(user_id, date_str, day_index, system_id=system_id)
    last_done_map = build_last_done_dict(await list_last_done_dates(user_id))
    data: list[dict] = []
    for_time_loaded = False
    last_for_time: int | None = None
    for ue_id, name, group, done_flag, ex_id, _note in ex_rows:
        resolved_group = resolve_group(name, group)
        with_weight, kind = get_display_flags(resolved_group, name)
        weight_enabled = with_weight or resolved_group in {"workout", "core"}
        baseline = await get_baseline(user_id, day_index, ex_id)
        today_sets_full = []
        if session_id:
            today_sets_full = await fetch_exercise_sets(session_id, ue_id)
        current_note = await get_exercise_persistent_note(user_id, ex_id)
        previous_note = None
        last_sets = await fetch_last_session_sets(user_id, day_index, ue_id, date_str)
        entry: dict[str, object] = {
            "ue_id": ue_id,
            "exercise_id": ex_id,
            "name": name,
            "group_key": resolved_group,
            "is_done_today": bool(done_flag),
            "baseline": baseline,
            "prev_summary": "",
            "prev_date": last_done_map.get(ex_id),
            "today_summary": None,
            "amrap_summary": None,
            "fortime_summary": None,
            "with_weight": weight_enabled,
            "kind": kind,
            "note": current_note,
            "last_note": previous_note,
        }
        if resolved_group == "metcon" and name == AMRAP_EXERCISE_NAME:
            rounds, extra = parse_amrap_sets(today_sets_full)
            entry["amrap_summary"] = {"rounds": rounds, "extra": extra}
            last_rounds, last_extra = parse_amrap_history(last_sets)
            if last_rounds or last_extra:
                entry["prev_summary"] = format_amrap_done(last_rounds, last_extra)
        elif resolved_group == "metcon" and name == FOR_TIME_EXERCISE_NAME:
            if not for_time_loaded:
                rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=1)
                if rows and rows[0][0] is not None:
                    last_for_time = int(round(rows[0][0]))
                else:
                    last_for_time = None
                for_time_loaded = True
            entry["fortime_summary"] = {"last_time_sec": last_for_time}
        elif resolved_group == RUNNING_GROUP:
            running_entry = None
            duration_ms_value = 0
            if session_id is not None:
                running_entry = await get_running_entry(
                    user_id,
                    ue_id,
                    session_id=session_id,
                    day_index=day_index,
                    create=False,
                )
            if running_entry:
                (
                    _,
                    dist,
                    duration_sec,
                    duration_ms,
                    calories,
                    heart_rate,
                    is_draft,
                    created_at,
                ) = running_entry
                distance_value = float(dist or 0.0)
                duration_ms_value = int(duration_ms or 0)
                if not duration_ms_value and duration_sec:
                    duration_ms_value = int(duration_sec) * 1000
                duration_value = max(int(round(duration_ms_value / 1000)), 0)
                calories_value = int(calories or 0)
            else:
                distance_value = 0.0
                duration_value = 0
                calories_value = 0
            entry["running_summary"] = {
                "distance": distance_value,
                "duration": duration_value,
                "duration_ms": duration_ms_value if running_entry else 0,
                "calories": calories_value,
            }
            history_rows = await list_running_history(
                user_id, ue_id, exercise_id=ex_id, limit=2
            )
            prev_entry = None
            if history_rows:
                if running_entry and history_rows[0][0] == running_entry[0]:
                    if len(history_rows) > 1:
                        prev_entry = history_rows[1]
                else:
                    prev_entry = history_rows[0]
            if prev_entry:
                (
                    _,
                    prev_distance,
                    prev_duration,
                    prev_duration_ms,
                    prev_calories,
                    prev_heart_rate,
                    prev_created,
                    _,
                ) = prev_entry
                prev_duration_ms_val = int(prev_duration_ms or 0)
                if not prev_duration_ms_val and prev_duration:
                    prev_duration_ms_val = int(prev_duration) * 1000
                prev_duration_val = max(int(round(prev_duration_ms_val / 1000)), 0)
                entry["prev_summary"] = format_running_line(
                    float(prev_distance or 0.0),
                    prev_duration_val,
                    int(prev_calories or 0),
                )
                entry["prev_date"] = prev_created
            entry["has_history"] = bool(history_rows)
        else:
            summary = build_strength_summary_from_sets(today_sets_full)
            summary["kind"] = kind
            entry["today_summary"] = summary
            if resolved_group == "kb":
                entry["prev_summary"] = format_sets_history(
                    last_sets, with_weight=weight_enabled, kind=kind
                )
            else:
                entry["prev_summary"] = format_sets_history(
                    last_sets, with_weight=weight_enabled, kind=kind
                )
        data.append(entry)
    return data


def set_sheet_context(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    day: int,
    page: int,
):
    views = context.user_data.setdefault(SHEET_VIEWS_KEY, {})
    views[(chat_id, message_id)] = {"day": day, "page": page}


def get_sheet_context(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
) -> dict | None:
    views = context.user_data.get(SHEET_VIEWS_KEY)
    if not views:
        return None
    return views.get((chat_id, message_id))


def clear_sheet_context(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    views = context.user_data.get(SHEET_VIEWS_KEY)
    if not views:
        return
    views.pop((chat_id, message_id), None)
    if not views:
        context.user_data.pop(SHEET_VIEWS_KEY, None)


async def build_day_sheet_message(
    user_id: int,
    day_index: int,
    page: int,
    prefs: UiPreferences,
) -> tuple[str, InlineKeyboardMarkup, int, int]:
    date_str = await get_user_local_date(user_id)
    items = await fetch_day_sheet_data(user_id, day_index, date_str)
    label = await get_day_label(user_id, day_index)
    total = len(items)
    total_pages = max(1, math.ceil(total / DAY_SHEET_PAGE_SIZE)) if total else 1
    page = max(0, min(page, total_pages - 1))
    start = page * DAY_SHEET_PAGE_SIZE
    end = start + DAY_SHEET_PAGE_SIZE
    visible = items[start:end]
    any_with_weight = any(bool(item.get("with_weight", True)) for item in items)
    header = f"{t('DAY')} {day_index}"
    if label:
        header += f" — {label}"
    lines = [header]
    weight_hint = (
        "Фиксируй подходы кнопками «{add_set}» и «{add_rep}». Кнопки «＋0.5 кг», «＋3 кг» и «＋10 кг» меняют рабочий вес во всех карточках.".format(
            add_set=t('ADD_SET'), add_rep=t('ADD_REP')
        ),
        "Фиксируй подходы кнопками «{add_set}» и «{add_rep}». Кнопки «＋0.5 кг», «＋3 кг» и «＋10 кг» меняют рабочий вес во всех карточках, «−0.5 кг», «−3 кг» и «−10 кг» убирают вес — учёт ведётся без переходов по меню.".format(
            add_set=t('ADD_SET'), add_rep=t('ADD_REP')
        ),
    )
    simple_hint = (
        f"Фиксируй подходы кнопками «{t('ADD_SET')}» и «{t('ADD_REP')}».",
        "Фиксируй подходы кнопками «{add_set}» и «{add_rep}». Для упражнений на время используй кнопку «{done}» внутри карточки, чтобы сохранить результат за секунды.".format(
            add_set=t('ADD_SET'), add_rep=t('ADD_REP'), done=t('DONE')
        ),
    )
    maybe_hint(lines, prefs, weight_hint if any_with_weight else simple_hint)
    if not visible:
        lines.append("")
        lines.append(
            "Добавь упражнения к дню через меню — после этого они появятся здесь для быстрого учёта.",
        )
    kb_rows: list[list[InlineKeyboardButton]] = []
    first_entry = True
    for item in visible:
        if not first_entry:
            lines.append("")
        first_entry = False
        name = str(item["name"])
        group_key = str(item["group_key"])
        with_weight = bool(item.get("with_weight", True))
        kind = str(item.get("kind", "reps"))
        mark = status_icon(prefs, bool(item.get("is_done_today")))
        prefix = f"{mark} " if mark else ""
        ue_id = int(item["ue_id"])
        prev_label = build_prev_label(
            item.get("prev_summary"),
            item.get("prev_date"),
        )
        note_lines = build_note_lines(
            item.get("note"), item.get("last_note")
        )
        if group_key == "metcon" and name == AMRAP_EXERCISE_NAME:
            summary = item.get("amrap_summary") or {"rounds": 0, "extra": 0}
            rounds = int(summary.get("rounds") or 0)
            extra = int(summary.get("extra") or 0)
            prev_text = item.get("prev_summary") or t("NOT_FIXED")
            current_text = t("AMRAP_LINE", rounds=rounds, extra=extra)
            lines.append(f"{prefix}{t('METCON_TITLE')} — {t('AMRAP_TITLE')}")
            lines.append(f"• Прошлый раз: {prev_text}")
            for note_line in note_lines:
                lines.append(f"• {note_line}")
            lines.append(f"• Сегодня: {current_text}")
            kb_rows.append(
                [
                    InlineKeyboardButton(t("ADD_SET"), callback_data=f"ex:addset:{day_index}:{ue_id}"),
                    InlineKeyboardButton("− сет", callback_data=f"ex:delset:{day_index}:{ue_id}"),
                    InlineKeyboardButton(t("ADD_REP"), callback_data=f"ex:inc:{day_index}:{ue_id}:reps:1"),
                    InlineKeyboardButton("−1", callback_data=f"ex:inc:{day_index}:{ue_id}:reps:-1"),
                    InlineKeyboardButton(t("DONE"), callback_data=f"ex:done:{day_index}:{ue_id}"),
                ]
            )
            continue
        elif group_key == "metcon" and name == FOR_TIME_EXERCISE_NAME:
            fortime = item.get("fortime_summary") or {}
            seconds_raw = fortime.get("last_time_sec")
            if seconds_raw is not None:
                seconds_value = _safe_int(seconds_raw)
                result = format_duration_value(seconds_value)
            else:
                result = t("NOT_FIXED")
            result_line = t("FTIME_LINE", time=result)
            lines.append(f"{prefix}{t('METCON_TITLE')} — {t('FOR_TIME_TITLE')}")
            lines.append(f"• Прошлый раз: {result_line}")
            for note_line in note_lines:
                lines.append(f"• {note_line}")
            lines.append(f"• Сегодня: {result_line}")
            kb_rows.append(
                [
                    InlineKeyboardButton(t("DONE"), callback_data=f"ex:done:{day_index}:{ue_id}"),
                    InlineKeyboardButton(t("HISTORY"), callback_data=f"ex:progress:{day_index}:{ue_id}"),
                ]
            )
        elif group_key == RUNNING_GROUP:
            summary = item.get("running_summary") or {}
            distance_value = float(summary.get("distance") or 0.0)
            duration_value = int(summary.get("duration") or 0)
            calories_value = int(summary.get("calories") or 0)
            current_text = format_running_line(distance_value, duration_value, calories_value)
            prev_text = item.get("prev_summary") or t("NOT_FIXED")
            lines.append(f"{prefix}{name}")
            lines.append(f"• Сегодня: {current_text}")
            lines.append(f"• Прошлый раз: {prev_text}")
            for note_line in note_lines:
                lines.append(f"• {note_line}")
            action_row: list[InlineKeyboardButton] = [
                InlineKeyboardButton("Открыть", callback_data=f"ex:view:{day_index}:{ue_id}"),
                InlineKeyboardButton(t("DONE"), callback_data=f"run:done:{day_index}:{ue_id}"),
            ]
            action_row.append(
                InlineKeyboardButton(
                    HISTORY_BTN, callback_data=f"run:history:{day_index}:{ue_id}:0"
                )
            )
            kb_rows.append(action_row)
        else:
            done_text = format_strength_done_value(
                item.get("today_summary"), with_weight=with_weight
            )
            last_text = prev_label
            if not last_text:
                baseline = item.get("baseline")
                baseline_summary = summarize_baseline(
                    baseline, with_weight=with_weight, kind=kind
                ) if baseline else ""
                if baseline_summary:
                    last_text = baseline_summary
            if not last_text:
                last_text = t("NOT_FIXED")
            lines.append(f"{prefix}{name}")
            lines.append(f"• Прошлый раз: {last_text}")
            for note_line in note_lines:
                lines.append(f"• {note_line}")
            lines.append(f"• Сегодня: {done_text}")
            base_cb = f"ex:inc:{day_index}:{ue_id}"
            controls_row: list[InlineKeyboardButton] = [
                InlineKeyboardButton(t("ADD_SET"), callback_data=f"ex:addset:{day_index}:{ue_id}"),
                InlineKeyboardButton("− сет", callback_data=f"ex:delset:{day_index}:{ue_id}"),
                InlineKeyboardButton(
                    t("ADD_REP"),
                    callback_data=f"{base_cb}:reps:1",
                ),
                InlineKeyboardButton(
                    "−1",
                    callback_data=f"{base_cb}:reps:-1",
                ),
            ]
            kb_rows.append(controls_row)
            if group_key == "workout" and kind != "duration":
                kb_rows.append(
                    [
                        InlineKeyboardButton("＋5", callback_data=f"{base_cb}:reps:5"),
                        InlineKeyboardButton("−5", callback_data=f"{base_cb}:reps:-5"),
                    ]
                )
                kb_rows.append(
                    [
                        InlineKeyboardButton("＋15", callback_data=f"{base_cb}:reps:15"),
                        InlineKeyboardButton("−15", callback_data=f"{base_cb}:reps:-15"),
                    ]
                )
            if kind == "duration":
                if group_key in {"workout", "core", "kb", "metcon"}:
                    kb_rows.append(
                        [
                            InlineKeyboardButton("＋1 сек", callback_data=f"{base_cb}:sec:1"),
                            InlineKeyboardButton("＋5 сек", callback_data=f"{base_cb}:sec:5"),
                            InlineKeyboardButton("＋25 сек", callback_data=f"{base_cb}:sec:25"),
                            InlineKeyboardButton("＋30 сек", callback_data=f"{base_cb}:sec:30"),
                        ]
                    )
                    kb_rows.append(
                        [
                            InlineKeyboardButton("−1 сек", callback_data=f"{base_cb}:sec:-1"),
                            InlineKeyboardButton("−5 сек", callback_data=f"{base_cb}:sec:-5"),
                            InlineKeyboardButton("−25 сек", callback_data=f"{base_cb}:sec:-25"),
                            InlineKeyboardButton("−30 сек", callback_data=f"{base_cb}:sec:-30"),
                        ]
                    )
                    kb_rows.append(
                        [
                            InlineKeyboardButton("＋1 мин", callback_data=f"{base_cb}:sec:60"),
                            InlineKeyboardButton("−1 мин", callback_data=f"{base_cb}:sec:-60"),
                        ]
                    )
                else:
                    kb_rows.append(
                        [
                            InlineKeyboardButton("＋5 сек", callback_data=f"{base_cb}:sec:5"),
                            InlineKeyboardButton("＋15 сек", callback_data=f"{base_cb}:sec:15"),
                        ]
                    )
                    kb_rows.append(
                        [
                            InlineKeyboardButton("＋30 сек", callback_data=f"{base_cb}:sec:30"),
                            InlineKeyboardButton("＋1 мин", callback_data=f"{base_cb}:sec:60"),
                        ]
                    )
                    kb_rows.append(
                        [
                            InlineKeyboardButton("−5 сек", callback_data=f"{base_cb}:sec:-5"),
                            InlineKeyboardButton("−15 сек", callback_data=f"{base_cb}:sec:-15"),
                        ]
                    )
                    kb_rows.append(
                        [
                            InlineKeyboardButton("−30 сек", callback_data=f"{base_cb}:sec:-30"),
                            InlineKeyboardButton("−1 мин", callback_data=f"{base_cb}:sec:-60"),
                        ]
                    )
                kb_rows.append(
                    [
                        InlineKeyboardButton("＋1 повтор", callback_data=f"{base_cb}:reps:1"),
                        InlineKeyboardButton("−1 повтор", callback_data=f"{base_cb}:reps:-1"),
                    ]
                )
                kb_rows.append(
                    [
                        InlineKeyboardButton("＋5 повторов", callback_data=f"{base_cb}:reps:5"),
                        InlineKeyboardButton("−5 повторов", callback_data=f"{base_cb}:reps:-5"),
                    ]
                )
                kb_rows.append(
                    [InlineKeyboardButton(t("DONE"), callback_data=f"ex:done:{day_index}:{ue_id}")]
                )
                continue
            if with_weight:
                plus_row: list[InlineKeyboardButton] = []
                minus_row: list[InlineKeyboardButton] = []
                for step in (0.5, 3.0, 10.0, 25.0):
                    label = format_weight_value(step)
                    plus_row.append(
                        InlineKeyboardButton(
                            f"＋{label} кг",
                            callback_data=f"{base_cb}:kg:{step:g}",
                        )
                    )
                    minus_row.append(
                        InlineKeyboardButton(
                            f"−{label} кг",
                            callback_data=f"{base_cb}:kg:{-step:g}",
                        )
                    )
                kb_rows.append(plus_row)
                kb_rows.append(minus_row)
            kb_rows.append(
                [InlineKeyboardButton(t("DONE"), callback_data=f"ex:done:{day_index}:{ue_id}")]
            )
            continue
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(t("PREV"), callback_data=f"day:sheet:{day_index}:p:{page - 1}")
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(t("NEXT"), callback_data=f"day:sheet:{day_index}:p:{page + 1}")
            )
        if nav_row:
            kb_rows.append(nav_row)
    if items:
        kb_rows.append(
            [
                InlineKeyboardButton(
                    t("CLOSE_DAY"),
                    callback_data=f"day:sheetdone:{day_index}:{page}",
                )
            ]
        )
    kb_rows.append([InlineKeyboardButton(t("BACK"), callback_data="menu:root")])
    text = "\n".join(lines)
    return text, InlineKeyboardMarkup(kb_rows), page, total_pages


async def _build_completed_day_warning(
    user_id: int, day: int, current_label: str
) -> tuple[str, int, str] | None:
    days = await list_active_days(user_id)
    if len(days) <= 1:
        return None
    completions = await get_active_day_completions(user_id)
    if day not in completions:
        return None
    pending_days = [idx for idx, _ in days if idx not in completions and idx != day]
    if not pending_days:
        return None
    next_day = pending_days[0]
    next_label = next((label for idx, label in days if idx == next_day), None)
    next_title = next_label or f"{t('DAY')} {next_day}"
    current_title = current_label or f"{t('DAY')} {day}"
    warning_text = (
        "⚠️ ВНИМАНИЕ\n"
        f"Вы снова открыли {current_title}. Этот день уже отмечен выполненным, а на очереди — {next_title}.\n"
        "Вы уверены, что хотите продолжить этот день или перейти к следующей тренировке?"
    )
    return warning_text, next_day, next_title


def _is_completed_day_warning_suppressed(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, day: int
) -> bool:
    store = getattr(context, "user_data", None)
    if not isinstance(store, dict):
        return False
    suppressed: dict[int, list[int]] = store.get(
        COMPLETED_DAY_WARNING_SUPPRESS_KEY, {}
    )
    days = suppressed.get(user_id) or []
    return day in days


def suppress_completed_day_warning(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, day: int
) -> None:
    store = getattr(context, "user_data", None)
    if not isinstance(store, dict):
        return
    suppressed: dict[int, list[int]] = store.setdefault(
        COMPLETED_DAY_WARNING_SUPPRESS_KEY, {}
    )
    days = suppressed.setdefault(user_id, [])
    if day not in days:
        days.append(day)


async def render_day_sheet_from_callback(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    day_index: int,
    page: int,
    prefs: UiPreferences | None = None,
) -> int:
    prefs = prefs or await load_ui_preferences(user_id)
    text, kb, page, _ = await build_day_sheet_message(user_id, day_index, page, prefs)
    old_chat_id = q.message.chat_id
    old_message_id = q.message.message_id
    await show_screen(q, context, text, kb, user_id)
    new_chat_id = q.message.chat_id
    new_message_id = q.message.message_id
    if (new_chat_id, new_message_id) != (old_chat_id, old_message_id):
        clear_sheet_context(context, old_chat_id, old_message_id)
    set_sheet_context(context, new_chat_id, new_message_id, day_index, page)
    return page


async def render_day_sheet_by_id(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
    day_index: int,
    page: int,
    prefs: UiPreferences | None = None,
):
    prefs = prefs or await load_ui_preferences(user_id)
    text, kb, page, _ = await build_day_sheet_message(user_id, day_index, page, prefs)
    text, kb = prepare_ui_output(text, kb, prefs)
    try:
        await context.bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=kb,
        )
        remember_message(chat_id, message_id)
        set_sheet_context(context, chat_id, message_id, day_index, page)
    except BadRequest as exc:
        if "not modified" in exc.message.lower():
            set_sheet_context(context, chat_id, message_id, day_index, page)
            return
        clear_sheet_context(context, chat_id, message_id)
        new_msg = await send_main_message(
            context.bot,
            chat_id,
            text,
            reply_markup=kb,
        )
        set_sheet_context(context, new_msg.chat_id, new_msg.message_id, day_index, page)


async def send_day_cards_view(
    q,
    user_id: int,
    day: int,
    context: ContextTypes.DEFAULT_TYPE,
    prefs: UiPreferences,
): 
    clear_sheet_context(context, q.message.chat_id, q.message.message_id)
    context.user_data.pop(DAY_DELETE_SCOPE_KEY, None)
    label = await get_day_label(user_id, day)
    today_str = await get_user_local_date(user_id)
    system_id = await _active_system_id(user_id)
    ex_rows = await fetch_day_exercises(user_id, day, today_str, system_id=system_id)
    custom = await get_custom_groups(user_id, context)
    summaries = await build_summary_map(user_id, day, ex_rows, today_str)
    last_done_rows = await list_last_done_dates(user_id)
    last_done_map = build_last_done_dict(last_done_rows)
    warning = await _build_completed_day_warning(user_id, day, label)
    if warning and _is_completed_day_warning_suppressed(context, user_id, day):
        warning = None
    text = render_day_text(
        day,
        label,
        ex_rows,
        custom,
        summaries,
        last_done_map,
        prefs,
    )
    warning_button = None
    if warning:
        warning_text, next_day, next_title = warning
        text = f"{warning_text}\n\n{text}"
        warning_button = InlineKeyboardButton(
            dual(f"➡️ Перейти к {next_title}", f"Открыть {next_title}"),
            callback_data=f"day:open:{next_day}",
        )
    base_markup = day_kb(day, ex_rows, context=context)
    back_cb = "menu:root"
    content_rows: list[list[InlineKeyboardButton]] = []
    primary_actions: list[tuple[str, str]] = []
    completion_action: tuple[str, str] | None = None
    for row in base_markup.inline_keyboard:
        if not row:
            continue
        button = row[0]
        callback = button.callback_data or ""
        if callback == "menu:root":
            back_cb = callback
            continue
        callbacks = [btn.callback_data or "" for btn in row]
        if f"day:complete:{day}" in callbacks:
            for btn in row:
                cb = btn.callback_data or ""
                if cb == back_cb:
                    continue
                if cb == f"day:complete:{day}":
                    completion_action = (btn.text, cb)
                elif cb:
                    primary_actions.append((btn.text, cb))
            continue
        if any(
            cb.startswith(f"day:add_ex:{day}")
            or cb.startswith(f"day:del_ex:{day}")
            or cb in {
                f"day:manage:{day}:all:add",
                f"day:manage:{day}:all:del",
            }
            or cb == f"day:complete:{day}"
            for cb in callbacks
        ):
            for btn in row:
                cb = btn.callback_data
                if cb:
                    primary_actions.append((btn.text, cb))
            continue
        content_rows.append(row)
    rows: list[list[InlineKeyboardButton]] = []
    if warning_button is not None:
        rows.append([warning_button])
    rows += content_rows
    rows += ui_footer_rows(primary_actions, None)
    if completion_action:
        rows.append(
            [InlineKeyboardButton(completion_action[0], callback_data=completion_action[1])]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=back_cb)])
    kb = InlineKeyboardMarkup(rows)
    await show_screen(q, context, text, kb, user_id)


def format_current_training(
    sets: list[tuple[int, int, int, float, int]],
    selected: int | None,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> list[str]:
    if not sets:
        empty = format_sets_value(0, 0, 0, 0.0, with_weight, kind)
        return [f"Текущая тренировка: {empty}"]
    lines = ["Текущая тренировка:"]
    entries = [
        {
            "start": int(no),
            "end": int(no),
            "count": 1,
            "reps": _safe_int(reps),
            "seconds": _safe_int(seconds),
            "weight": _safe_float(weight),
            "warm": _safe_int(warm),
        }
        for no, reps, seconds, weight, warm in sets
    ]
    for entry in entries:
        start = int(entry["start"])
        end = int(entry["end"])
        count = int(entry["count"])
        marker = ""
        if selected is not None:
            if end < selected:
                marker = "✅ "
            elif start <= selected <= end:
                marker = "▶︎ "
        value = format_flex_value(
            int(entry["reps"]),
            int(entry.get("seconds", 0)),
            float(entry["weight"]),
            with_weight,
            kind,
        )
        if count > 1:
            label = _format_flex_span(start, end)
            lines.append(f"{marker}{label}. {count}× {value}")
        else:
            lines.append(f"{marker}{start}. {value}")
    return lines


def build_flex_session_lines(
    sets: list[tuple[int, int, int, float, int]],
    selected: int | None,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> list[str]:
    work_sets = [
        (no, reps, seconds, weight) for no, reps, seconds, weight, warm in sets if not warm
    ]
    lines: list[str] = []
    if not work_sets:
        lines.append("Сегодня пока нет рабочих сетов.")
        lines.append("Нажми «+ сет», чтобы добавить первый.")
        lines.append(
            "Добавь столько, сколько делал в прошлый раз или примерно столько, сколько планируешь."
        )
        lines.append("Когда закончишь, нажми «Готово».")
        return lines
    lines.append("Сегодняшние подходы:")
    entries = [
        {
            "start": int(no),
            "end": int(no),
            "count": 1,
            "reps": _safe_int(reps),
            "seconds": _safe_int(seconds),
            "weight": _safe_float(weight),
        }
        for no, reps, seconds, weight in work_sets
    ]
    for entry in entries:
        start = int(entry["start"])
        end = int(entry["end"])
        count = int(entry["count"])
        marker = ""
        if selected is not None:
            if end < selected:
                marker = "✅ "
            elif start <= selected <= end:
                marker = "▶︎ "
        value = format_flex_value(
            int(entry["reps"]),
            int(entry.get("seconds", 0)),
            float(entry["weight"]),
            with_weight,
            kind,
        )
        if count > 1:
            label = _format_flex_span(start, end)
            lines.append(f"{marker}{label}) {count}× {value}")
        else:
            lines.append(f"{marker}{start}) {value}")
    if selected is not None:
        lines.append("")
        lines.append(
            f"Напиши, сколько ты сделал в сете {selected}. Используй кнопки ниже, чтобы скорректировать значения."
        )
    lines.append("Когда закончишь с подходами, нажми «Готово».")
    return lines


async def build_summary_map(
    user_id: int,
    day: int,
    ex_rows: list[tuple[int, str, str, int, int]],
    today: str,
) -> dict[int, str]:
    summary: dict[int, str] = {}
    system_id = await _active_system_id(user_id)
    session_id = await get_session_for_day(user_id, today, day, system_id=system_id)
    for ue_id, name, group, _, ex_id, _note in ex_rows:
        resolved = resolve_group(name, group)
        with_weight, kind = get_display_flags(resolved, name)
        weight_enabled = with_weight or resolved in {"workout", "core"}
        current_sets_full: list[tuple[int, int, int, float, int]] = []
        if session_id:
            current_sets_full = await fetch_exercise_sets(session_id, ue_id)
        current_note = await get_exercise_persistent_note(user_id, ex_id)
        previous_note = None
        baseline = await get_baseline(user_id, day, ex_id)
        last_label = ""
        if resolved == "kb":
            work_sets = filter_work_sets(current_sets_full)
            if work_sets:
                last_label = format_sets_history(
                    work_sets, with_weight=weight_enabled, kind=kind
                )
            else:
                last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
                if last_sets:
                    last_label = format_sets_history(
                        last_sets, with_weight=weight_enabled, kind=kind
                    )
            if (not last_label or last_label == "—") and baseline:
                plan_value = format_kb_plan(baseline, kind=kind)
                if plan_value and plan_value != "—":
                    last_label = plan_value
        elif resolved == "metcon" and name == AMRAP_EXERCISE_NAME:
            rounds, extra = parse_amrap_sets(current_sets_full)
            if rounds or extra:
                last_label = format_amrap_done(rounds, extra)
            else:
                last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
                last_rounds, last_extra = parse_amrap_history(last_sets)
                if last_rounds or last_extra:
                    last_label = format_amrap_done(last_rounds, last_extra)
        elif resolved == "metcon" and name == FOR_TIME_EXERCISE_NAME:
            rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=1)
            if rows:
                value = rows[0][0]
                if value is not None:
                    last_label = format_duration_value(int(round(value)))
        elif resolved == RUNNING_GROUP:
            running_entry = None
            if session_id is not None:
                running_entry = await get_running_entry(
                    user_id,
                    ue_id,
                    session_id=session_id,
                    day_index=day,
                    create=False,
                )
            if running_entry:
                (
                    _,
                    dist,
                    duration_sec,
                    duration_ms,
                    calories_val,
                    heart_rate_val,
                    is_draft,
                    _created_at,
                ) = running_entry
                distance_value = float(dist or 0.0)
                duration_ms_val = int(duration_ms or 0)
                if not duration_ms_val and duration_sec:
                    duration_ms_val = int(duration_sec) * 1000
                duration_value = max(int(round(duration_ms_val / 1000)), 0)
                calories_value = int(calories_val or 0)
                if not int(is_draft or 0) and (
                    distance_value or duration_value or calories_value
                ):
                    last_label = format_running_line(
                        distance_value, duration_value, calories_value
                    )
            if not last_label:
                history_rows = await list_running_history(
                    user_id, ue_id, exercise_id=ex_id, limit=1
                )
                if history_rows:
                    _, dist, dur, dur_ms, cal, _hr, _created_at, _ = history_rows[0]
                    duration_ms_val = int(dur_ms or 0)
                    if not duration_ms_val and dur:
                        duration_ms_val = int(dur) * 1000
                    duration_val = max(int(round(duration_ms_val / 1000)), 0)
                    last_label = format_running_line(
                        float(dist or 0.0), duration_val, int(cal or 0)
                    )
        else:
            work_sets = filter_work_sets(current_sets_full)
            if work_sets:
                last_label = format_sets_history(
                    work_sets, with_weight=weight_enabled, kind=kind
                )
            if not last_label:
                last_sets = await fetch_last_session_sets(
                    user_id, day, ue_id, today
                )
                last_label = format_sets_history(
                    last_sets, with_weight=weight_enabled, kind=kind
                )
            if not last_label and baseline:
                last_label = summarize_baseline(
                    baseline, with_weight=weight_enabled, kind=kind
                )
        if not last_label:
            last_label = t("NOT_FIXED")
        note_lines = build_note_lines(current_note, previous_note)
        summary_text = f"{t('LAST_TIME')}: {last_label}"
        if note_lines:
            summary_text = summary_text + "\n" + "\n".join(note_lines)
        summary[ue_id] = summary_text
    return summary



async def show_day_group_view(
    q,
    user_id: int,
    day: int,
    group: str,
    context,
    prefs: UiPreferences | None = None,
):
    today_str = await get_user_local_date(user_id)
    system_id = await _active_system_id(user_id)
    ex_rows = await fetch_day_exercises(user_id, day, today_str, system_id=system_id)
    context.user_data.pop(DAY_DELETE_SCOPE_KEY, None)
    summaries = await build_summary_map(user_id, day, ex_rows, today_str)
    last_done_rows = await list_last_done_dates(user_id)
    last_done_map = build_last_done_dict(last_done_rows)
    custom = await get_custom_groups(user_id, context)
    gname = MG_NAMES.get(group, custom.get(group, group))
    prefs = prefs or await load_ui_preferences(user_id)
    lines = [f"{t('DAY')} {day} — {gname}"]
    maybe_hint(
        lines,
        prefs,
        (
            "Отмечай подходы прямо в списке упражнений.",
            "Отмечай подходы прямо в списке упражнений. Используй кнопки «＋ сет», «＋1» и настройки веса, чтобы собрать фактический комплект, — после сохранения строка обновится и покажет актуальный объём и последний рабочий сет.",
        ),
    )
    lines.append("")
    items: list[tuple[int, str, int]] = []
    for ue_id, name, g, done, ex_id, _note in ex_rows:
        resolved = resolve_group(name, g)
        if resolved != group:
            continue
        mark = status_icon(prefs, bool(done))
        info = summaries.get(ue_id)
        last = last_done_map.get(ex_id)
        lines.append(compose_exercise_line(mark, name, info, last))
        items.append((ue_id, name, done))
    if items:
        lines.append("────────")
    else:
        lines.append("Пока нет упражнений. Добавь упражнения, чтобы заполнить этот раздел.")
    text = "\n".join(lines)
    kb = day_group_kb(day, group, items, group_name=gname, context=context)
    await show_screen(q, context, text, kb, user_id)

async def render_library_group_text(
    user_id: int,
    group: str,
    items: list[tuple[int, str]],
    context: ContextTypes.DEFAULT_TYPE,
    prefs: UiPreferences | None = None,
) -> str:
    prefs = prefs or await load_ui_preferences(user_id)
    custom = await get_custom_groups(user_id, context)
    gname = MG_NAMES.get(group, custom.get(group, group))
    if not items:
        return (
            f"{gname}\n"
            "Пока нет упражнений. Нажми «Добавить», чтобы сохранить упражнения и вести учёт."
        )
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    last_done_rows = await list_last_done_dates(user_id)
    last_done_map = build_last_done_dict(last_done_rows)
    lines = [f"{gname}"]
    maybe_hint(
        lines,
        prefs,
        (
            "Открой упражнение, чтобы посмотреть детали.",
            "Открой упражнение, чтобы посмотреть детали. Там можно изучить историю и через кнопки сразу записать новые подходы или скорректировать их.",
        ),
    )
    lines.append("")
    first_entry = True
    system_id = await _active_system_id(user_id)
    await get_session_for_day(user_id, today, 0, system_id=system_id)
    for ue_id, name in items:
        ex_id, _, ex_group = await get_exercise_info(ue_id)
        resolved_group = resolve_group(name, ex_group)
        if resolved_group == "metcon" and name == FOR_TIME_EXERCISE_NAME:
            rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=1)
            seconds = None
            if rows and rows[0][0] is not None:
                seconds = int(round(rows[0][0]))
            summary = (
                t("FTIME_LINE", time=format_duration_value(seconds))
                if seconds is not None
                else t("FTIME_LINE", time=t("NOT_FIXED"))
            )
        else:
            last_sets = await fetch_last_session_sets(user_id, 0, ue_id, today)
            with_weight, kind = get_display_flags(resolved_group, name)
            weight_enabled = with_weight or resolved_group in {"workout", "core"}
            summary = summarize_previous_sets(
                last_sets, with_weight=weight_enabled, kind=kind
            )
            base = await get_baseline(user_id, 0, ex_id)
            if not summary and base:
                summary = summarize_baseline(
                    base, with_weight=weight_enabled, kind=kind
                )
        last = last_done_map.get(ex_id)
        if not first_entry:
            lines.append("")
        first_entry = False
        prefix = ""
        result_text = summary
        if not result_text:
            result_text = t("NOT_FIXED")
        current_note = await get_exercise_persistent_note(user_id, ex_id)
        note_lines = build_note_lines(current_note, None)
        lines.append(f"{prefix}{name}")
        lines.append(f"• Последний результат: {result_text}")
        for note_line in note_lines:
            lines.append(f"• {note_line}")
        if last:
            lines.append(f"• Тренировка: {last}")
    lines.append("")
    lines.append("────────")
    maybe_hint(
        lines,
        prefs,
        (
            "Добавь новые упражнения через «Добавить».",
            "Добавь новые упражнения через «Добавить». После сохранения их можно прикрепить к тренировочным дням и сразу настроить базовый план или фактические подходы.",
        ),
    )
    return "\n".join(lines)


async def show_library_exercise_view(
    q,
    user_id: int,
    group: str,
    ue_id: int,
    context: ContextTypes.DEFAULT_TYPE,
):
    prefs = await load_ui_preferences(user_id)
    selected = get_flex_selected(context, 0, ue_id)
    view = await render_exercise_view(user_id, 0, ue_id, selected, prefs=prefs)
    attachments = await list_exercise_day_links(user_id, view.exercise_id)
    if attachments:
        attach_lines = ["Прикреплено к дням:"]
        for day_idx, label in attachments:
            title = f"{t('DAY')} {day_idx}"
            if label:
                title = f"{title} — {label}"
            attach_lines.append(f"• {title}")
        attach_lines.append(
            "Чтобы изменить список дней, открой нужный день и редактируй упражнения прямо в расписании."
        )
    else:
        attach_lines = [
            "Пока не прикреплено ни к одному дню. Добавь упражнение через нужный день тренировок, чтобы видеть его в расписании.",
        ]
    full_text = view.text + "\n\n" + "\n".join(attach_lines)
    set_flex_selected(context, 0, ue_id, view.selected_set)
    kb = build_exercise_actions_markup(
        view,
        day=0,
        ue_id=ue_id,
        group=group,
        prefs=prefs,
        is_library=True,
        context=context,
    )
    await show_screen(q, context, full_text, kb, user_id)
    return view.exercise_id, view.group


async def render_exercise_view(
    user_id: int,
    day: int,
    ue_id: int,
    selected_set: int | None = None,
    prefs: UiPreferences | None = None,
) -> ExerciseView:
    owner = await get_user_exercise_info(ue_id)
    if not owner or owner[0] != user_id or owner[1] != day:
        raise ValueError('exercise_unavailable')
    ex_id, name, raw_group = await get_exercise_info(ue_id)
    group = resolve_group(name, raw_group)
    today = await get_user_local_date(user_id)
    system_id = await _active_system_id(user_id)
    session_id = await get_session_for_day(user_id, today, day, system_id=system_id)
    sets = await fetch_exercise_sets(session_id, ue_id) if session_id is not None else []
    baseline = await get_baseline(user_id, day, ex_id)
    last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
    prefs = prefs or await load_ui_preferences(user_id)
    with_weight, kind = get_display_flags(group, name)
    weight_enabled = with_weight or group in {"workout", "core"}
    current_note = await get_exercise_persistent_note(user_id, ex_id)
    previous_note = None
    is_amrap = group == "metcon" and name == AMRAP_EXERCISE_NAME
    is_for_time = group == "metcon" and name == FOR_TIME_EXERCISE_NAME

    work_sets = filter_work_sets(sets)
    if work_sets:
        if selected_set is None or all(no != selected_set for no, *_ in work_sets):
            selected_set = work_sets[-1][0]
    else:
        selected_set = None

    type_labels = {
        "kb": "Гири",
        "metcon": "Меткон",
        "workout": "Воркаут",
        RUNNING_GROUP: "Бег",
    }
    type_label = type_labels.get(group, "Силовая")
    title = f"{name} · {type_label}"

    if group == "kb":
        prev_text = format_sets_history(
            last_sets, with_weight=weight_enabled, kind=kind
        )
        if (not prev_text or prev_text == "—") and work_sets:
            prev_text = format_sets_history(
                work_sets, with_weight=weight_enabled, kind=kind
            )
        if not prev_text or prev_text == "—":
            prev_text = t("NOT_FIXED")
        summary = build_strength_summary_from_sets(sets)
        summary["kind"] = kind
        done_text = format_strength_done_value(summary, with_weight=weight_enabled)
    elif group == RUNNING_GROUP:
        running_entry = await get_running_entry(
            user_id,
            ue_id,
            session_id=session_id,
            day_index=day,
            create=False,
        ) if session_id is not None else None
        running_entry = running_entry or (None, 0, 0, 0, 0, 0, 1, None)
        (
            entry_id,
            dist,
            duration_sec,
            duration_ms,
            calories,
            heart_rate,
            draft_flag,
            created_at,
        ) = running_entry
        distance_value = float(dist or 0.0)
        duration_ms_value = int(duration_ms or 0)
        if not duration_ms_value and duration_sec:
            duration_ms_value = int(duration_sec) * 1000
        duration_value = max(int(round(duration_ms_value / 1000)), 0)
        calories_value = int(calories or 0)
        current_line = format_running_line(distance_value, duration_value, calories_value)
        history_rows = await list_running_history(
            user_id, ue_id, exercise_id=ex_id, limit=2
        )
        prev_text = t("NOT_FIXED")
        prev_created_at = None
        if history_rows:
            candidate = history_rows[0]
            if candidate[0] == entry_id and len(history_rows) > 1:
                candidate = history_rows[1]
            if candidate[0] != entry_id:
                (
                    _,
                    prev_distance,
                    prev_duration,
                    prev_duration_ms,
                    prev_calories,
                    prev_hr,
                    prev_created,
                    _,
                ) = candidate
                prev_duration_ms_val = int(prev_duration_ms or 0)
                if not prev_duration_ms_val and prev_duration:
                    prev_duration_ms_val = int(prev_duration) * 1000
                prev_duration_val = max(int(round(prev_duration_ms_val / 1000)), 0)
                prev_text = format_running_line(
                    float(prev_distance or 0.0),
                    prev_duration_val,
                    int(prev_calories or 0),
                )
                prev_created_at = prev_created
        done_text = current_line
        lines = [title, ""]
        lines.append("Сегодня:")
        lines.append(f"• {current_line}")
        if prev_created_at:
            lines.append("")
            lines.append("Прошлый раз:")
            lines.append(f"• {prev_text}")
        note_lines = build_note_lines(current_note, previous_note)
        if note_lines:
            lines.append("")
            lines.extend(note_lines)
        lines.append("")
        maybe_hint(
            lines,
            prefs,
            (
                "Используй кнопки, чтобы добавить километры и время.",
                "Используй кнопки ниже, чтобы добавить километры, время, темп и калории. Все изменения сохраняются сразу, а «Готово» завершает забег.",
            ),
        )
        running_data = {
            "entry_id": entry_id,
            "distance": distance_value,
            "duration": duration_value,
            "calories": calories_value,
            "is_draft": bool(draft_flag),
            "created_at": created_at,
            "last_created_at": prev_created_at,
        }
        return ExerciseView(
            text="\n".join(lines),
            session_id=session_id,
            exercise_id=ex_id,
            name=name,
            group=group,
            sets=[],
            selected_set=None,
            with_weight=False,
            kind="running",
            is_amrap=False,
            is_for_time=False,
            has_history=bool(history_rows),
            running=running_data,
        )
    elif is_amrap:
        rounds, extra = parse_amrap_sets(sets)
        last_rounds, last_extra = parse_amrap_history(last_sets)
        prev_text = (
            t("AMRAP_RESULT", rounds=last_rounds, extra=last_extra)
            if last_rounds or last_extra
            else t("NOT_FIXED")
        )
        if (not last_rounds and not last_extra) and (rounds or extra):
            prev_text = t("AMRAP_RESULT", rounds=rounds, extra=extra)
        done_text = t("AMRAP_RESULT", rounds=rounds, extra=extra)
    elif is_for_time:
        rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=1)
        seconds = None
        if rows:
            value = rows[0][0]
            if value is not None:
                seconds = int(round(value))
        if seconds is not None:
            value_text = format_duration_value(seconds)
        else:
            value_text = t("NOT_FIXED")
        prev_text = value_text
        done_text = value_text
    else:
        prev_text = format_sets_history(
            last_sets, with_weight=weight_enabled, kind=kind
        )
        if not prev_text and work_sets:
            prev_text = format_sets_history(
                work_sets, with_weight=weight_enabled, kind=kind
            )
        if not prev_text:
            prev_text = summarize_baseline(
                baseline, with_weight=weight_enabled, kind=kind
            )
        prev_text = prev_text or t("NOT_FIXED")
        summary = build_strength_summary_from_sets(sets)
        summary["kind"] = kind
        done_text = format_strength_done_value(
            summary, with_weight=weight_enabled
        )

    lines = [
        title,
        f"{t('LAST_TIME')}: {prev_text}",
    ]
    note_lines = build_note_lines(current_note, previous_note)
    lines.extend(note_lines)
    lines.append(f"{t('MADE')}: {done_text}")
    extra_lines = format_current_training(
        sets,
        selected_set,
        with_weight=weight_enabled,
        kind=kind,
    )
    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)

    text = "\n".join(lines)
    return ExerciseView(
        text=text,
        session_id=session_id,
        exercise_id=ex_id,
        name=name,
        group=group,
        sets=sets,
        selected_set=selected_set,
        with_weight=weight_enabled,
        kind=kind,
        is_amrap=is_amrap,
        is_for_time=is_for_time,
        has_history=True,
    )


def build_exercise_actions_markup(
    view: ExerciseView,
    *,
    day: int,
    ue_id: int,
    group: str,
    prefs: UiPreferences,
    is_library: bool = False,
    back_callback: str | None = None,
    context: ContextTypes.DEFAULT_TYPE | None = None,
):
    target_day = 0 if is_library else day
    callback_back = back_callback
    if callback_back is None:
        callback_back = (
            f"lib:group:{group}" if is_library else f"day:group:{day}:{group}"
        )
    if view.group == RUNNING_GROUP:
        return build_running_actions_markup(
            day=target_day,
            ue_id=ue_id,
            back_callback=callback_back,
        )
    context_mode = "library" if is_library else "flex"
    markup = exercise_actions_kb(
        context_mode,
        view.with_weight,
        view.kind,
        view.has_history,
        prefs,
        day=target_day,
        ue_id=ue_id,
        group=group,
        is_amrap=view.is_amrap,
        is_for_time=view.is_for_time,
        back_callback=callback_back,
        context=context,
    )
    content_rows: list[list[InlineKeyboardButton]] = []
    primary_actions: list[tuple[str, str]] = []
    secondary_actions: list[tuple[str, str]] | None = None
    for row in markup.inline_keyboard:
        if not row:
            continue
        callbacks = [btn.callback_data or "" for btn in row]
        if callback_back in callbacks:
            for btn in row:
                if (btn.callback_data or "") == callback_back:
                    continue
                primary_actions.append((btn.text, btn.callback_data or ""))
            continue
        if callbacks and all(cb.startswith("ex:progress:") for cb in callbacks):
            secondary_actions = [(btn.text, btn.callback_data or "") for btn in row]
            continue
        content_rows.append(row)
    rows: list[list[InlineKeyboardButton]] = []
    rows += content_rows
    rows += ui_footer_rows(primary_actions, secondary_actions)
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=callback_back)])
    return InlineKeyboardMarkup(rows)


async def build_running_history_view(
    user_id: int,
    day: int,
    ue_id: int,
    index: int = 0,
    *,
    back_callback: str | None = None,
    prefs: UiPreferences | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    ex_id, name, _ = await get_exercise_info(ue_id)
    entries = await list_running_history(user_id, ue_id, exercise_id=ex_id, limit=20)
    prefs_local = prefs or await load_ui_preferences(user_id)
    tz_name = await get_user_timezone(user_id)
    zone = resolve_user_zone(tz_name)
    lines = [name, ""]
    if not entries:
        lines.append("История забегов пока пуста. Добавь результат через «Готово».")
        back_cb = back_callback or f"ex:view:{day}:{ue_id}"
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("BACK"), callback_data=back_cb)]]
        )
        return "\n".join(lines), kb
    total = len(entries)
    safe_index = max(0, min(index, total - 1))
    _, distance, duration_sec, duration_ms, calories, heart_rate, created_at, entry_day = entries[
        safe_index
    ]
    duration_ms_val = int(duration_ms or 0)
    if not duration_ms_val and duration_sec:
        duration_ms_val = int(duration_sec) * 1000
    duration_val = max(int(round(duration_ms_val / 1000)), 0)
    timestamp = format_measurement_timestamp(created_at, zone)
    summary = format_running_line(
        float(distance or 0.0), duration_val, int(calories or 0)
    )
    lines.append(f"Запись {safe_index + 1} из {total}")
    lines.append(timestamp)
    lines.append(f"• {summary}")
    if entry_day:
        lines.append(f"• {t('DAY')} {entry_day}")
    lines.append("")
    maybe_hint(
        lines,
        prefs_local,
        (
            "Листай стрелками, чтобы посмотреть предыдущие забеги.",
            "Листай стрелками, чтобы посмотреть предыдущие забеги. Возвращайся назад, чтобы продолжить вести текущую тренировку.",
        ),
    )
    nav_row: list[InlineKeyboardButton] = []
    if safe_index + 1 < total:
        nav_row.append(
            InlineKeyboardButton(
                "◀︎ Раньше",
                callback_data=f"run:history:{day}:{ue_id}:{safe_index + 1}",
            )
        )
    if safe_index > 0:
        nav_row.append(
            InlineKeyboardButton(
                "Позже ▶︎",
                callback_data=f"run:history:{day}:{ue_id}:{safe_index - 1}",
            )
        )
    rows: list[list[InlineKeyboardButton]] = []
    if nav_row:
        rows.append(nav_row)
    back_cb = back_callback or f"ex:view:{day}:{ue_id}"
    rows.append([InlineKeyboardButton(t("BACK"), callback_data=back_cb)])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def build_running_actions_markup(
    *, day: int, ue_id: int, back_callback: str
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append(
        [
            InlineKeyboardButton(
                "＋0.5 км", callback_data=f"run:inc:{day}:{ue_id}:dist:0.5"
            ),
            InlineKeyboardButton(
                "＋1 км", callback_data=f"run:inc:{day}:{ue_id}:dist:1"
            ),
            InlineKeyboardButton(
                "−0.5 км", callback_data=f"run:inc:{day}:{ue_id}:dist:-0.5"
            ),
            InlineKeyboardButton(
                "−1 км", callback_data=f"run:inc:{day}:{ue_id}:dist:-1"
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "＋1 мин", callback_data=f"run:inc:{day}:{ue_id}:time:60"
            ),
            InlineKeyboardButton(
                "＋5 мин", callback_data=f"run:inc:{day}:{ue_id}:time:300"
            ),
            InlineKeyboardButton(
                "＋30 мин", callback_data=f"run:inc:{day}:{ue_id}:time:1800"
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "−1 мин", callback_data=f"run:inc:{day}:{ue_id}:time:-60"
            ),
            InlineKeyboardButton(
                "−5 мин", callback_data=f"run:inc:{day}:{ue_id}:time:-300"
            ),
            InlineKeyboardButton(
                "−30 мин", callback_data=f"run:inc:{day}:{ue_id}:time:-1800"
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "✏️ Дистанция", callback_data=f"run:input:{day}:{ue_id}:distance"
            ),
            InlineKeyboardButton(
                "✏️ Время", callback_data=f"run:input:{day}:{ue_id}:time"
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "✏️ Темп", callback_data=f"run:input:{day}:{ue_id}:pace"
            ),
            InlineKeyboardButton(
                "✏️ Калории", callback_data=f"run:input:{day}:{ue_id}:calories"
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                t("ADD_NOTE"), callback_data=f"ex:note:{day}:{ue_id}"
            )
        ]
    )
    primary_actions: list[tuple[str, str]] = [
        (t("DONE"), f"run:done:{day}:{ue_id}"),
    ]
    history_callback = f"run:history:{day}:{ue_id}:0"
    secondary_actions: list[tuple[str, str]] | None = [(HISTORY_BTN, history_callback)]
    rows += ui_footer_rows(primary_actions, secondary_actions)
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


async def build_for_time_history_view(
    user_id: int,
    day: int,
    ue_id: int,
    back_callback: str | None = None,
    prefs: UiPreferences | None = None,
):
    ex_id, name, raw_group = await get_exercise_info(ue_id)
    rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=10)
    tz_name = await get_user_timezone(user_id)
    tz = resolve_user_zone(tz_name)
    prefs = prefs or await load_ui_preferences(user_id)
    lines = [name, "", f"{t('HISTORY')} результатов:"]
    has_entries = False
    for value, _, created_at in rows:
        if value is None:
            continue
        has_entries = True
        seconds = int(round(value))
        lines.append(f"{format_measurement_timestamp(created_at, tz)} — {format_duration_value(seconds)}")
    if has_entries:
        lines.append("")
        maybe_hint(
            lines,
            prefs,
            (
                "Используй «Изменить», если нужно скорректировать последнее время.",
                "Используй «Изменить», если нужно скорректировать последнее время. Так можно поправить результат, не создавая новую запись.",
            ),
        )
    else:
        maybe_hint(
            lines,
            prefs,
            (
                f"Добавь время через «{t('DONE')}».",
                f"Добавь время через «{t('DONE')}». Значение сразу появится в списке и сохранится в истории тренировки.",
            ),
        )
    back_cb = back_callback or f"ex:view:{day}:{ue_id}"
    kb_rows = []
    if has_entries:
        kb_rows.append(
            [InlineKeyboardButton("✏️ Изменить", callback_data=f"ex:timeedit:{day}:{ue_id}")]
        )
        kb_rows.append(
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"ex:timedel:{day}:{ue_id}")]
        )
    kb_rows.append([InlineKeyboardButton(t("BACK"), callback_data=back_cb)])
    return "\n".join(lines), InlineKeyboardMarkup(kb_rows)


async def build_workout_reminder(
    bot, user_id: int | None, *, day_index: int | None = None, tz_name: str | None = None
):
    cheer = ""
    text_lines = ["🔔 Пришло время тренировки!", ""]
    keyboard_rows: list[list[InlineKeyboardButton]] = []

    if user_id:
        tz_name = tz_name or await get_user_timezone(user_id)
        zone = resolve_user_zone(tz_name)
        now_local = datetime.now(zone)
        logger.info("REMINDER FIRE user=%s local_now=%s", user_id, now_local.isoformat())

        weekday_label = WEEKDAY_FULL_NAMES.get(now_local.weekday())
        date_str = now_local.strftime("%d.%m.%Y")
        time_str = now_local.strftime("%H:%M")
        if weekday_label:
            text_lines.append(f"Сегодня {weekday_label}, {date_str} в {time_str}.")
        else:
            text_lines.append(f"Сегодня {date_str} в {time_str}.")

        day_label = await get_day_label(user_id, day_index) if day_index else None
        if day_label:
            text_lines.append(f"Сегодняшний день: {day_label}.")
        elif day_index:
            text_lines.append(f"Сегодняшний день: День {day_index}.")

        completions = await get_active_day_completions(user_id)
        cheer = format_reminder_cheer(len(completions))
        if day_index:
            keyboard_rows.append(
                [InlineKeyboardButton("Открыть день", web_app=WebAppInfo(build_webapp_day_url(day_index)))]
            )
            keyboard_rows.append(
                [InlineKeyboardButton("Перейти ко дню", callback_data=f"day:open:{day_index}")]
            )

    keyboard_rows.append([InlineKeyboardButton("В главное меню", callback_data="menu:root")])
    if cheer:
        text_lines.extend(["", cheer])

    text = "\n".join(text_lines)
    reply_markup = InlineKeyboardMarkup(keyboard_rows)
    return text, reply_markup


async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    # оставляем единую реализацию в _rem_fire
    await _rem_fire(context)


async def _schedule_user_reminders(
    app: Application | None, user_id: int, *, chat_id: int | None = None
) -> set[str]:
    if app is None:
        return set()

    if not await get_user_notifications_enabled(user_id):
        _sweep_user_reminder_jobs(app.job_queue, user_id)
        logger.info("Skipping reminders for user %s: notifications disabled", user_id)
        return set()

    reminders = _sort_reminders(await list_user_reminders(user_id))
    _sweep_user_reminder_jobs(app.job_queue, user_id)
    if not reminders:
        logger.info("Scheduled 0 reminders for user %d", user_id)
        return set()

    tz_code = await get_user_timezone(user_id)
    # A trainer can edit a pupil's timetable from another chat. The receiver is
    # always resolved from the timetable owner, never the editing chat.
    record = await find_user_by_id(user_id)
    try: chat_id = int(record[1]) if record and record[1] is not None else None
    except (TypeError, ValueError): chat_id = None
    if chat_id is None:
        logger.warning("SKIP REMINDER: chat_id is None for user %s", user_id)
        return set()

    scheduled: set[str] = set()
    for day_no, dow, hour, minute in reminders:
        name = _schedule_reminder_job(
            app.job_queue,
            chat_id=chat_id,
            user_id=user_id,
            day_no=day_no,
            dow=dow,
            hour=hour,
            minute=minute,
            tz_name=tz_code,
        )
        if name:
            scheduled.add(name)
    return scheduled


def _build_reminder_job_name(user_id: int, day_no: int, dow: int, hour: int, minute: int) -> str:
    return f"rem_{user_id}_{day_no}_{dow}"


def _build_reminder_job_tag(user_id: int, day_no: int, dow: int, hour: int, minute: int) -> str:
    return f"u:{user_id}:rem:{day_no}:{dow}:{hour:02d}{minute:02d}"


def _schedule_reminder_job(
    job_queue,
    *,
    chat_id: int | None,
    user_id: int,
    day_no: int,
    dow: int,
    hour: int,
    minute: int,
    tz_name: str,
    remove_existing: bool = True,
):
    """
    ВЕРСИЯ LITE: больше НЕ использует run_daily/days. Ставит ОДНОРАЗОВОЕ срабатывание на ближайший момент,
    колбэк сам перепланирует себя на +7 дней.
    """
    if chat_id is None or job_queue is None:
        return None
    try:
        dow_int = int(dow)
        hh = int(hour)
        mm = int(minute)
    except Exception:
        return None

    app = getattr(job_queue, "application", None) or SimpleNamespace(job_queue=job_queue)
    job_id = _rem_job_id(int(user_id), dow_int, hh, mm)

    if remove_existing:
        # удалить старую одноимённую джобу, если была
        scheduler = getattr(job_queue, "scheduler", None)
        if scheduler:
            with contextlib.suppress(Exception):
                for j in scheduler.get_jobs():
                    if j.id == job_id:
                        j.remove()

    # поставить одноразовое срабатывание
    _rem_schedule_once(
        app,
        chat_id=int(chat_id),
        user_id=int(user_id),
        tz_name=str(tz_name),
        dow=dow_int,
        hh=hh,
        mm=mm,
        day_no=day_no,
    )
    legacy_name = _build_reminder_job_name(user_id, day_no, dow_int, hh, mm)
    if legacy_name and hasattr(job_queue, "jobs_by_name"):
        try:
            created = getattr(job_queue, "created_jobs", None)
            last_job = created[-1] if created else None
        except Exception:
            last_job = None
        if last_job:
            job_queue.jobs_by_name.setdefault(legacy_name, []).append(last_job)
    return job_id


def _get_job_tag(job):
    data = getattr(job, "data", None)
    if isinstance(data, dict):
        tag = data.get("tag")
        if isinstance(tag, str):
            return tag
    name = getattr(job, "name", None)
    if isinstance(name, str) and name.startswith("u:"):
        return name
    return None


def _safe_remove_job(job) -> None:
    try:
        job.schedule_removal()
    except Exception:
        pass


def _remove_jobs_with_tag_prefix(job_queue, tag_prefix: str) -> None:
    if job_queue is None:
        return
    try:
        jobs = job_queue.jobs()
    except AttributeError:
        jobs = []
    for job in jobs:
        tag = _get_job_tag(job)
        if isinstance(tag, str) and tag.startswith(tag_prefix):
            _safe_remove_job(job)


def _remove_reminder_jobs(job_queue, user_id: int, day_no: int, dow: int | None = None) -> None:
    if job_queue is None:
        return
    tag_prefix = f"u:{user_id}:rem:{day_no}:"
    if dow is None:
        _remove_jobs_with_tag_prefix(job_queue, tag_prefix)
        job_name_prefix = f"rem_{user_id}_{day_no}_"
        try:
            jobs = job_queue.jobs()
        except AttributeError:
            jobs = []
        for job in jobs:
            name = getattr(job, "name", None)
            if isinstance(name, str) and name.startswith(job_name_prefix.rstrip("_")):
                _safe_remove_job(job)
        return

    dow_int = int(dow)
    _remove_jobs_with_tag_prefix(job_queue, f"{tag_prefix}{dow_int}")
    job_name_prefix = f"rem_{user_id}_{day_no}_{dow_int}"
    try:
        jobs = job_queue.jobs()
    except AttributeError:
        jobs = []
    for job in jobs:
        name = getattr(job, "name", None)
        if isinstance(name, str) and (
            name == job_name_prefix or name.startswith(f"{job_name_prefix}_")
        ):
            _safe_remove_job(job)


def _remove_jobs_for_removed_reminders(
    job_queue, user_id: int, removed: Sequence[tuple[int, int, int, int]]
) -> None:
    for day_no, dow, _hour, _minute in removed:
        _remove_reminder_jobs(job_queue, user_id, int(day_no), int(dow))


def _sweep_user_reminder_jobs(job_queue, user_id: int) -> None:
    if job_queue is None:
        return
    _remove_jobs_with_tag_prefix(job_queue, f"u:{user_id}:rem:")
    try:
        jobs = job_queue.jobs()
    except AttributeError:
        jobs = []
    prefix = f"rem_{user_id}_"
    for job in jobs:
        name = getattr(job, "name", None)
        if isinstance(name, str) and name.startswith(prefix):
            _safe_remove_job(job)


async def schedule_all_reminders(app: Application):
    raw_rows = await list_users_with_reminders()
    users: set[int] = {int(user_id) for user_id, *_ in raw_rows}
    desired_jobs: set[str] = set()
    total_scheduled = 0
    for user_id in users:
        scheduled = await _schedule_user_reminders(app, user_id)
        desired_jobs.update(scheduled)
        total_scheduled += len(scheduled)
    logger.info("Scheduled %d reminder jobs in total", total_scheduled)

    try:
        jobs = app.job_queue.jobs()
    except AttributeError:
        jobs = []
    for job in jobs:
        name = getattr(job, "name", None)
        if name and name.startswith("rem_") and name not in desired_jobs:
            _safe_remove_job(job)


def _on_job_event(e):
    logger.info(
        "JOB EVENT code=%s job_id=%s scheduled=%s exception=%s",
        getattr(e, "code", None),
        getattr(e, "job_id", None),
        getattr(e, "scheduled_run_time", None),
        getattr(e, "exception", None),
    )


# ========================= REMINDERS_LITE — BEGIN =========================
def _rem_next_occurrence(tz_name: str, dow: int, hh: int, mm: int, *, after: _dt | None = None) -> _dt:
    """
    Вернёт ближайшую ЛОКАЛЬНУЮ дату-время для (dow, hh:mm).
    dow: Mon=0..Sun=6 (как datetime.weekday()).
    """
    tz = _Z(tz_name)
    now = (after.astimezone(tz) if after else _dt.now(tz))
    add = (dow - now.weekday()) % 7
    target = _dt(now.year, now.month, now.day, hh, mm, tzinfo=tz) + _td(days=add)
    if target <= now:
        target += _td(days=7)
    return target


def _rem_job_id(user_id: int, dow: int, hh: int, mm: int) -> str:
    return f"rem_{user_id}_{dow}_{hh:02d}{mm:02d}"


def _rem_try_db_get_last_msg(user_id: int, kind: str = "workout_reminder") -> int | None:
    """Опционально: если в db.py есть get_notification_msg(conn, user, kind) — использовать его."""
    try:
        import db as _DB
        with contextlib.suppress(Exception):
            conn = _DB.conn() if hasattr(_DB, "conn") else None
            return _DB.get_notification_msg(conn, user_id, kind)  # type: ignore
    except Exception:
        return None


def _rem_try_db_set_last_msg(user_id: int, msg_id: int, kind: str = "workout_reminder") -> None:
    """Опционально: если в db.py есть set_notification_msg(conn, user, kind, msg_id) — использовать его."""
    try:
        import db as _DB
        with contextlib.suppress(Exception):
            conn = _DB.conn() if hasattr(_DB, "conn") else None
            _DB.set_notification_msg(conn, user_id, kind, msg_id)  # type: ignore
    except Exception:
        pass


async def _rem_fire(context):
    """
    Колбэк напоминания:
    1) удаляет прошлое сообщение (если было),
    2) отправляет новое уведомление (текст/кнопки — из текущей логики бота),
    3) перепланирует себя на следующий такой же слот (+7 дней).
    """
    data = context.job.data or {}
    try: user_id = int(data['user_id'])
    except (KeyError, ValueError, TypeError): return
    record = await find_user_by_id(user_id)
    if not record or record[1] is None: return
    try: chat_id = int(record[1])
    except (ValueError, TypeError): return
    if chat_id <= 0: return
    data = {**data, 'chat_id':chat_id}
    tz_name: str = data["tz"]
    dow: int = int(data["dow"])
    hh: int = int(data["hh"])
    mm: int = int(data["mm"])
    day_no: int | None
    try:
        day_no = int(data.get("day_no")) if data.get("day_no") is not None else None
    except (TypeError, ValueError):
        day_no = None
    kind: str = data.get("kind", "workout_reminder")

    # Queue the next normal slot even on rest, an unmarked workout, or a failed
    # delivery. _rem_next_occurrence already returns the following week.
    nxt_local = _rem_next_occurrence(tz_name, dow, hh, mm)
    delay = max(1,(nxt_local - _dt.now(_Z(tz_name))).total_seconds())
    context.job_queue.run_once(_rem_fire,when=delay,name=context.job.name,data=data,chat_id=chat_id,
        job_kwargs={"misfire_grace_time":600,"coalesce":True,"max_instances":1})
    from progressor_bot import notification_preflight,NotificationDeferred
    from progressor_reminder import reserve
    from settings import DB_PATH
    try:notification_preflight(context.application,chat_id,'gym')
    except NotificationDeferred:return

    # A formatter error can use the minimal copy before any provider request.
    # A send error cannot: Telegram may have already accepted that message.
    try:
        # если в проекте есть готовая функция, формирующая текст/kb напоминания — используй её.
        text, kb = await build_workout_reminder(
            context.bot,
            user_id,
            day_index=day_no or dow,
            tz_name=tz_name,
        )
    except Exception:
        # Фолбэк: минимальное уведомление (на случай, если Codex не нашёл сборку)
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть дневник", callback_data="menu:root")]])
        text="⏰ Время тренировки!"

    slot=f'{kind}:{_dt.now(_Z(tz_name)).date().isoformat()}:{dow}:{hh}:{mm}'
    if not await asyncio.to_thread(reserve,DB_PATH,chat_id,slot):return
    try:msg=await send_main_message(context.bot,chat_id,text,kb,parse_mode=None,force_new=True)
    except Exception:
        logger.warning('gym_reminder_delivery_uncertain')
        return

    _REM_LAST_MSG[chat_id] = msg.message_id
    remember_message(msg.chat_id, msg.message_id)
    _rem_try_db_set_last_msg(user_id, msg.message_id, kind)



def _rem_clear_user_jobs(app, user_id: int):
    """Удалить все джобы вида rem_{user}_*"""
    sch = app.job_queue.scheduler
    for job in list(sch.get_jobs()):
        if job.id.startswith(f"rem_{user_id}_"):
            with contextlib.suppress(Exception):
                job.remove()


def _rem_schedule_once(
    app,
    *,
    chat_id: int,
    user_id: int,
    tz_name: str,
    dow: int,
    hh: int,
    mm: int,
    day_no: int | None = None,
):
    """Поставить одноразовую джобу на ближайший слот по локальному времени пользователя."""
    now_local = _dt.now(_Z(tz_name))
    fire_at = _rem_next_occurrence(tz_name, dow, hh, mm, after=now_local)
    app.job_queue.run_once(
        _rem_fire,
        when=fire_at,
        name=_rem_job_id(user_id, dow, hh, mm),
        data={
            "chat_id": chat_id,
            "user_id": user_id,
            "tz": tz_name,
            "dow": dow,
            "hh": hh,
            "mm": mm,
            "kind": "workout_reminder",
            "day_no": day_no,
            "tag": _build_reminder_job_tag(user_id, day_no or 0, dow, hh, mm),
        },
        chat_id=chat_id,
        job_kwargs={"misfire_grace_time": 600, "coalesce": True, "max_instances": 1},
    )
    try:
        created_jobs = getattr(app.job_queue, "created_jobs", None)
        if created_jobs:
            created_jobs[-1].days = (dow,)
    except Exception:
        pass
# ========================= REMINDERS_LITE — END =========================

async def post_init(app: Application):
    await schedule_all_reminders(app)
    global _last_reminders_meta
    try:
        _last_reminders_meta = await get_app_meta(REMINDER_META_KEY)
    except Exception:
        _last_reminders_meta = None
    app.job_queue.run_repeating(
        _refresh_reminders_if_needed,
        interval=60,
        first=30,
        name="refresh_reminders_meta",
    )
    app.job_queue.run_repeating(
        _expire_stale_payments_job,
        interval=300,
        first=60,
        name="expire_stale_pending_payments",
    )


async def _expire_stale_payments_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        expired = await db_expire_stale_pending_payments()
    except Exception as exc:
        logger.warning("Failed to expire stale payments: %s", exc)
        return
    if expired:
        logger.info("Expired %s unpaid payments older than 30 minutes", expired)


async def _refresh_reminders_if_needed(context: ContextTypes.DEFAULT_TYPE):
    global _last_reminders_meta
    try:
        meta = await get_app_meta(REMINDER_META_KEY)
    except Exception as exc:
        logger.warning("Failed to read reminders meta: %s", exc)
        return
    if not meta or meta == _last_reminders_meta:
        return
    _last_reminders_meta = meta
    try:
        await schedule_all_reminders(context.application)
    except Exception as exc:
        logger.warning("Failed to refresh reminders: %s", exc)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    u = update.effective_user
    user_id = await get_or_create_user(u.id, u.username)
    start_payload = ""
    if getattr(context, "args", None):
        start_payload = " ".join(context.args).strip()
    elif update.message and update.message.text:
        parts = (update.message.text or "").split(maxsplit=1)
        if len(parts) > 1:
            start_payload = parts[1].strip()
    if start_payload.startswith("ref_"):
        slug = start_payload[4:].strip().lower()
        referrer = await get_referrer_by_slug(slug)
        if referrer:
            await assign_referral_attribution(user_id, int(referrer["user_id"]), slug)
    await mark_referral_first_seen(user_id)
    settings = await fetch_user_settings(user_id)
    prefs = await load_ui_preferences(user_id)
    if not settings or not settings[1]:
        chat = update.effective_chat
        context.user_data["wizard_onboarding"] = True

        prefs = await load_ui_preferences(user_id)
        intro_text, _ = prepare_ui_output(t("ONBOARDING_INTRO"), None, prefs)
        prompt = "Сколько тренировок в неделю?"
        kb = week_count_kb()
        prompt_text, prompt_kb = prepare_ui_output(prompt, kb, prefs)

        intro_msg = None
        if chat is not None:
            intro_msg = await context.bot.send_message(chat.id, intro_text)
        elif update.message:
            intro_msg = await update.message.reply_text(intro_text)

        if intro_msg is not None:
            context.user_data["wizard_intro_message"] = (
                intro_msg.chat_id,
                intro_msg.message_id,
            )
            try:
                await set_onboarding_intro_message(
                    user_id,
                    intro_msg.chat_id,
                    intro_msg.message_id,
                )
            except Exception as exc:
                logger.warning("Failed to store onboarding intro message: %s", exc)

        video_id = await get_intro_video()
        if video_id:
            if chat is not None:
                video_msg = await context.bot.send_video(
                    chat.id, video_id, reply_markup=intro_video_ack_kb()
                )
            else:
                video_msg = await update.message.reply_video(
                    video_id, reply_markup=intro_video_ack_kb()
                )
            if video_msg is not None:
                try:
                    await set_onboarding_video_message(
                        user_id, video_msg.chat_id, video_msg.message_id
                    )
                except Exception as exc:
                    logger.warning("Failed to store onboarding video message: %s", exc)
            return

        if chat is not None:
            await context.bot.send_message(chat.id, prompt_text, reply_markup=prompt_kb)
        else:
            await update.message.reply_text(prompt_text, reply_markup=prompt_kb)
        return
    text, kb, prefs = await compose_main_menu(user_id, prefs)
    text, kb = prepare_ui_output(text, kb, prefs)
    chat = update.effective_chat
    if chat is not None:
        await send_main_message_fresh(context.bot, chat.id, text, reply_markup=kb)
    elif update.message:
        msg = await update.message.reply_text(text, reply_markup=kb)
        remember_message(msg.chat_id, msg.message_id)


def get_broadcast_state(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    state = context.user_data.get(BROADCAST_STATE_KEY)
    if isinstance(state, dict):
        return state
    return None


def reset_broadcast_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(BROADCAST_STATE_KEY, None)


def broadcast_photo_choice_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Да", callback_data="broadcast:photo:yes"),
                InlineKeyboardButton("Нет", callback_data="broadcast:photo:no"),
            ]
        ]
    )


def broadcast_photo_manage_markup(has_photo: bool) -> InlineKeyboardMarkup:
    if has_photo:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Удалить фото", callback_data="broadcast:photo:remove")],
                [InlineKeyboardButton(BACK_BTN, callback_data="broadcast:preview")],
            ]
        )
    return InlineKeyboardMarkup([[InlineKeyboardButton(BACK_BTN, callback_data="broadcast:preview")]])


def broadcast_return_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Ясно, вернуть меню", callback_data=MAIL_RETURN_CALLBACK)]]
    )


def intro_video_ack_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Продолжаем", callback_data="wiz:intro:ok")],
            [InlineKeyboardButton("Поехали 🚀", web_app=WebAppInfo(WEBAPP_URL))],
        ]
    )


def build_broadcast_preview_text(state: dict) -> str:
    payload = (state.get("text") or "").strip()
    lines = ["Сообщение для рассылки:", ""]
    lines.append(payload or "— Текст не задан —")
    lines.append("")
    if state.get("photo"):
        lines.append("📷 Фото будет отправлено вместе с текстом.")
    else:
        lines.append("Фото не прикреплено.")
    lines.append("")
    lines.append("Проверь сообщение и используй кнопки ниже, чтобы его скорректировать или отправить.")
    return "\n".join(lines)


def build_broadcast_preview_markup(state: dict) -> InlineKeyboardMarkup:
    photo_label = "🖼 Изменить фото" if state.get("photo") else "🖼 Добавить фото"
    rows = [
        [
            InlineKeyboardButton("✏️ Изменить текст", callback_data="broadcast:edit:text"),
            InlineKeyboardButton(photo_label, callback_data="broadcast:edit:photo"),
        ],
        [
            InlineKeyboardButton("🚀 Отправить", callback_data="broadcast:send"),
            InlineKeyboardButton("✖️ Отмена", callback_data="broadcast:cancel"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


async def send_broadcast_preview(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    state: dict,
) -> None:
    text = build_broadcast_preview_text(state)
    markup = build_broadcast_preview_markup(state)
    await send_main_message(context.bot, chat_id, text, reply_markup=markup)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        if update.message:
            await update.message.reply_text("Команда доступна только администратору.")
        return
    state = {
        "step": "await_text",
        "text": None,
        "photo": None,
        "skip_photo_prompt": False,
    }
    context.user_data[BROADCAST_STATE_KEY] = state
    if update.message:
        await try_delete(update.message)
        await send_main_message(
            context.bot,
            update.message.chat_id,
            "Пришли текст сообщения для рассылки. После текста можно добавить фотографию. Отправь /cancel, чтобы отменить рассылку.",
        )


async def cmd_set_intro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        return
    context.user_data[INTRO_AWAIT_KEY] = True
    await update.message.reply_text(
        "Пришли видео-гайд одним сообщением (файл/видео). Я сохраню file_id и буду показывать новым пользователям в начале начальной настройки."
    )


async def capture_intro_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ловит видео от админа, если он ранее вызвал команду и мы ждём ролик."""

    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        return
    if not context.user_data.get(INTRO_AWAIT_KEY):
        return

    file_id = None
    msg = update.message
    if msg and msg.video:
        file_id = msg.video.file_id
    elif msg and msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/"):
        file_id = msg.document.file_id

    if not file_id:
        await msg.reply_text("Не вижу видео. Пришли ролик обычным сообщением (как видео или видео-документ).")
        return

    await set_intro_video(file_id)
    context.user_data.pop(INTRO_AWAIT_KEY, None)
    await msg.reply_text(
        "✅ Видео сохранено. Теперь оно будет показано всем новым пользователям перед началом начальной настройки."
    )


async def check_prems_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        if update.message:
            await update.message.reply_text("Команда доступна только администратору.")
        return
    try:
        total = await count_active_subscriptions()
    except Exception:
        logger.exception("Failed to count active subscriptions")
        if update.message:
            await update.message.reply_text("Не удалось получить количество подписок. Попробуй позже.")
        return
    if update.message:
        await update.message.reply_text(f"Сейчас активных подписок: {total}.")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    if int(user_id) not in ADMIN_IDS:
        return
    try:
        data = await fetch_global_stats(None)
        text = "<b>Stats</b>\n<code>" + json.dumps(data, ensure_ascii=False, indent=2) + "</code>"
        await update.effective_message.reply_html(text)
    except Exception as exc:
        await update.effective_message.reply_text(f"Ошибка статистики: {exc!s}")


async def splash_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    db_user_id = await get_or_create_user(user.id, user.username)
    tag_prefix = f"u:{db_user_id}:rem:"
    _remove_jobs_with_tag_prefix(context.job_queue, tag_prefix)
    _sweep_user_reminder_jobs(context.job_queue, db_user_id)
    await wipe_user(db_user_id)
    context.user_data.clear()
    await chat.send_message("Данные очищены. Нажми /start, чтобы начать заново.")


async def ai_pass_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    if user.id not in ADMIN_IDS:
        await message.reply_text("Команда доступна только администратору.")
        return
    user_id = await get_or_create_user(user.id, user.username)
    removed = await reset_ai_coach_quota(user_id)
    await message.reply_text(
        f"Лимит ИИ сброшен. Удалено записей: {removed}. Теперь можно снова делать запросы в приложении."
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message:
        return
    state = get_broadcast_state(context)
    if user and user.id in ADMIN_IDS and state:
        reset_broadcast_state(context)
        await update.message.reply_text("Рассылка отменена.")
        return
    await update.message.reply_text("Нет активных действий, которые можно отменить.")


async def grant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        if update.message:
            await update.message.reply_text("Команда доступна только администратору.")
        return
    if not update.message or not update.message.text:
        return
    parts = update.message.text.split()
    if len(parts) < 3:
        await update.message.reply_text("Использование: /grant <tg_id|user_id> <дней>.")
        return
    try:
        target_raw = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await update.message.reply_text("Укажи числовые значения: идентификатор и количество дней.")
        return
    if days <= 0:
        await update.message.reply_text("Количество дней должно быть больше нуля.")
        return
    found = await find_user_by_tg_id(target_raw)
    user_id: int | None = None
    tg_id: int | None = None
    username: str | None = None
    if found:
        user_id, username = found
        tg_id = target_raw
    else:
        entry = await find_user_by_id(target_raw)
        if not entry:
            await update.message.reply_text("Пользователь с таким ID не найден.")
            return
        user_id, tg_id, username = entry
    try:
        expires_at = await grant_subscription_days(user_id, days, plan="manual")
    except Exception:
        logger.exception("Failed to grant subscription")
        await update.message.reply_text("Не удалось обновить подписку. Попробуй позже.")
        return
    await cleanup_expired_subscriptions(user_id)
    label_parts: list[str] = []
    if tg_id:
        label_parts.append(str(tg_id))
    if username:
        label_parts.append(f"@{username}")
    label = " ".join(label_parts) or f"user_id={user_id}"
    expires_label = expires_at.astimezone(ZoneInfo("UTC")).strftime("%d.%m.%Y")
    await update.message.reply_text(
        f"Подписка для {label} активна до {expires_label}. Добавлено {days} дн."
    )


async def degrant_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        if update.message:
            await update.message.reply_text("Команда доступна только администратору.")
        return
    if not update.message or not update.message.text:
        return
    parts = update.message.text.split()
    if len(parts) < 3:
        await update.message.reply_text("Использование: /degrant <tg_id|user_id> <дней>.")
        return
    try:
        target_raw = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await update.message.reply_text("Укажи числовые значения: идентификатор и количество дней.")
        return
    if days <= 0:
        await update.message.reply_text("Количество дней должно быть больше нуля.")
        return
    found = await find_user_by_tg_id(target_raw)
    user_id: int | None = None
    tg_id: int | None = None
    username: str | None = None
    if found:
        user_id, username = found
        tg_id = target_raw
    else:
        entry = await find_user_by_id(target_raw)
        if not entry:
            await update.message.reply_text("Пользователь с таким ID не найден.")
            return
        user_id, tg_id, username = entry
    try:
        expires_at = await degrant_subscription_days(user_id, days)
    except Exception:
        logger.exception("Failed to degrant subscription")
        await update.message.reply_text("Не удалось обновить подписку. Попробуй позже.")
        return
    await cleanup_expired_subscriptions(user_id)
    label_parts: list[str] = []
    if tg_id:
        label_parts.append(str(tg_id))
    if username:
        label_parts.append(f"@{username}")
    label = " ".join(label_parts) or f"user_id={user_id}"
    if expires_at is None:
        await update.message.reply_text(
            f"Подписка для {label} аннулирована. Списано {days} дн."
        )
        return
    expires_label = expires_at.astimezone(ZoneInfo("UTC")).strftime("%d.%m.%Y")
    await update.message.reply_text(
        f"Подписка для {label} активна до {expires_label}. Списано {days} дн."
    )


async def teams_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or user.id not in ADMIN_IDS:
        if message:
            await message.reply_text("Команда доступна только администратору.")
        return
    if not message:
        return
    text = (message.text or "").strip()
    parts = text.split(maxsplit=2)
    sub = parts[1].lower() if len(parts) > 1 else ""

    if sub in {"", "help"}:
        await message.reply_text(
            "Управление командами:\n"
            "/teams_admin list [limit] [offset] — список команд\n"
            "/teams_admin delete <team_id> — удалить команду"
        )
        return

    if sub == "list":
        extra = (parts[2] if len(parts) > 2 else "").split()
        limit = 20
        offset = 0
        try:
            if len(extra) >= 1:
                limit = max(1, min(int(extra[0]), 100))
            if len(extra) >= 2:
                offset = max(0, int(extra[1]))
        except ValueError:
            await message.reply_text("Формат: /teams_admin list [limit] [offset]")
            return
        items, total = await list_all_teams(limit=limit, offset=offset)
        if not items:
            await message.reply_text("Команды не найдены.")
            return
        lines = [f"Всего команд: {total}. Показаны {offset + 1}-{offset + len(items)}:"]
        for item in items:
            lines.append(
                f"#{item['team_id']} · {item['name']} · участников: {item['members_count']} · код: {item['join_code']}"
            )
        await message.reply_text("\n".join(lines[:80]))
        return

    if sub == "delete":
        if len(parts) < 3:
            await message.reply_text("Формат: /teams_admin delete <team_id>")
            return
        try:
            team_id = int(parts[2].split()[0])
        except ValueError:
            await message.reply_text("team_id должен быть числом.")
            return
        ok = await delete_team(team_id)
        if not ok:
            await message.reply_text("Команда не найдена.")
            return
        await message.reply_text(f"✅ Команда #{team_id} удалена.")
        return

    await message.reply_text("Неизвестное действие. Используй /teams_admin help")


async def handle_broadcast_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state: dict,
) -> bool:
    message = update.message
    if not message or message.text is None:
        return False
    text = message.text.strip()
    step = state.get("step")
    chat_id = message.chat_id
    if step == "await_text":
        if not text:
            await send_main_message(
                context.bot,
                chat_id,
                "Текст не должен быть пустым.",
            )
            await try_delete(message)
            return True
        state["text"] = text
        skip_prompt = bool(state.pop("skip_photo_prompt", False))
        if skip_prompt:
            state["step"] = "await_confirm"
            await send_main_message(context.bot, chat_id, "Текст обновлён.")
            await send_broadcast_preview(chat_id, context, state)
        else:
            state["step"] = "await_photo_choice"
            await send_main_message(
                context.bot,
                chat_id,
                "Хочешь добавить фотографию к рассылке? Ответь «да» или «нет».",
                reply_markup=broadcast_photo_choice_markup(),
            )
        await try_delete(message)
        return True
    if step == "await_photo_choice":
        lowered = text.lower()
        if lowered in {"да", "yes", "y"}:
            state["step"] = "await_photo"
            await send_main_message(
                context.bot,
                chat_id,
                "Пришли фотографию для рассылки.",
                reply_markup=broadcast_photo_manage_markup(bool(state.get("photo"))),
            )
            await try_delete(message)
            return True
        if lowered in {"нет", "no", "n"}:
            state["step"] = "await_confirm"
            await send_broadcast_preview(chat_id, context, state)
            await try_delete(message)
            return True
        await send_main_message(
            context.bot,
            chat_id,
            "Ответь «да» или «нет», чтобы продолжить.",
        )
        await try_delete(message)
        return True
    if step == "await_photo":
        lowered = text.lower()
        if lowered in {"назад", "отмена", "back"}:
            state["step"] = "await_confirm"
            await send_broadcast_preview(chat_id, context, state)
            await try_delete(message)
            return True
        if lowered in {"удалить", "remove"}:
            state["photo"] = None
            state["step"] = "await_confirm"
            await send_main_message(context.bot, chat_id, "Фото удалено.")
            await send_broadcast_preview(chat_id, context, state)
            await try_delete(message)
            return True
        await send_main_message(
            context.bot,
            chat_id,
            "Пришли фотографию или напиши «назад», чтобы вернуться.",
        )
        await try_delete(message)
        return True
    if step == "await_confirm":
        if not text:
            await send_main_message(
                context.bot,
                chat_id,
                "Текст не должен быть пустым.",
            )
            await try_delete(message)
            return True
        state["text"] = text
        await send_main_message(context.bot, chat_id, "Текст обновлён.")
        await send_broadcast_preview(chat_id, context, state)
        await try_delete(message)
        return True
    return False


async def handle_broadcast_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state: dict,
) -> bool:
    message = update.message
    if not message or not message.photo:
        return False
    photo = message.photo[-1]
    state["photo"] = photo.file_id
    state["step"] = "await_confirm"
    await send_main_message(context.bot, message.chat_id, "Фото добавлено.")
    await send_broadcast_preview(message.chat_id, context, state)
    await try_delete(message)
    return True


async def execute_broadcast(q, context: ContextTypes.DEFAULT_TYPE, state: dict) -> None:
    text = (state.get("text") or "").strip()
    if not text:
        await q.answer("Добавь текст для рассылки.", show_alert=True)
        return
    try:
        unsubscribed_targets = await list_broadcast_targets(
            ADMIN_IDS, only_without_subscription=True
        )
        targets = await list_broadcast_targets(ADMIN_IDS)
    except Exception:
        logger.exception("Failed to prepare broadcast targets")
        await send_main_message(
            context.bot,
            q.message.chat_id,
            "Не удалось подготовить рассылку. Попробуй позже.",
        )
        return
    photo_id = state.get("photo")
    total = len(targets)
    if total == 0:
        reset_broadcast_state(context)
        await send_main_message(
            context.bot,
            q.message.chat_id,
            "Нет пользователей для рассылки.",
        )
        return
    unsubscribed_ids = {user_id for _, user_id in unsubscribed_targets}
    delivered = 0
    skipped = 0
    for tg_id, _ in targets:
        try:
            if photo_id:
                await context.bot.send_photo(
                    tg_id,
                    photo=photo_id,
                    caption=text,
                    reply_markup=broadcast_return_markup(),
                )
            else:
                await context.bot.send_message(
                    tg_id,
                    text,
                    reply_markup=broadcast_return_markup(),
                )
            delivered += 1
            await asyncio.sleep(0.05)
        except Forbidden:
            skipped += 1
        except RetryAfter as exc:
            await asyncio.sleep(int(getattr(exc, "retry_after", 1)))
            try:
                if photo_id:
                    await context.bot.send_photo(
                        tg_id,
                        photo=photo_id,
                        caption=text,
                        reply_markup=broadcast_return_markup(),
                    )
                else:
                    await context.bot.send_message(
                        tg_id,
                        text,
                        reply_markup=broadcast_return_markup(),
                    )
                delivered += 1
            except Forbidden:
                skipped += 1
            except TelegramError as err:
                skipped += 1
                logger.warning("Broadcast failed after retry for %s: %s", tg_id, err)
        except TelegramError as err:
            skipped += 1
            logger.warning("Broadcast failed for %s: %s", tg_id, err)
    reset_broadcast_state(context)
    unsubscribed_count = sum(1 for _, user_id in targets if user_id in unsubscribed_ids)
    summary = (
        f"Рассылка завершена. Получатели: {total}. "
        f"Доставлено: {delivered}. Недоступно: {skipped}. "
        f"Без активной подписки: {unsubscribed_count}."
    )
    await send_main_message(context.bot, q.message.chat_id, summary)


async def handle_broadcast_callback(q, context: ContextTypes.DEFAULT_TYPE):
    state = get_broadcast_state(context)
    if not state:
        await q.answer("Нет активной рассылки.", show_alert=True)
        return
    data = q.data or ""
    chat_id = q.message.chat_id
    await q.answer()
    if data == "broadcast:photo:yes":
        state["step"] = "await_photo"
        await safe_update_screen(
            q,
            context,
            "Пришли фотографию для рассылки.",
            reply_markup=broadcast_photo_manage_markup(bool(state.get("photo"))),
        )
        return
    if data == "broadcast:photo:no":
        state["step"] = "await_confirm"
        await send_broadcast_preview(chat_id, context, state)
        return
    if data == "broadcast:edit:text":
        state["step"] = "await_text"
        state["skip_photo_prompt"] = True
        await safe_update_screen(q, context, "Пришли новый текст для рассылки.")
        return
    if data == "broadcast:edit:photo":
        state["step"] = "await_photo"
        has_photo = bool(state.get("photo"))
        prompt = (
            "Пришли новую фотографию или удали текущую кнопкой ниже."
            if has_photo
            else "Пришли фотографию для рассылки."
        )
        await safe_update_screen(
            q,
            context,
            prompt,
            reply_markup=broadcast_photo_manage_markup(has_photo),
        )
        return
    if data == "broadcast:photo:remove":
        state["photo"] = None
        state["step"] = "await_confirm"
        await safe_update_screen(q, context, "Фото удалено.")
        await send_broadcast_preview(chat_id, context, state)
        return
    if data == "broadcast:preview":
        state["step"] = "await_confirm"
        await send_broadcast_preview(chat_id, context, state)
        return
    if data == "broadcast:cancel":
        reset_broadcast_state(context)
        await safe_update_screen(q, context, "Рассылка отменена.")
        return
    if data == "broadcast:send":
        if state.get('sending'):
            await q.answer('Рассылка уже выполняется.', show_alert=True)
            return
        state['sending'] = True
        try:
            await execute_broadcast(q, context, state)
        finally:
            state.pop('sending', None)
        return


def build_subscription_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code in ("1m", "6m", "12m"):
        plan = SUBSCRIPTION_PLANS.get(code)
        if not plan:
            continue
        months_label = plan["title"].replace("Подписка на ", "")
        rows.append(
            [
                InlineKeyboardButton(f"{months_label} · {plan['amount_rub']} ₽", web_app=WebAppInfo(build_webapp_payment_url(code))),
                InlineKeyboardButton(
                    f"{months_label} — {plan_amount_stars(plan['amount_rub'])} ⭐",
                    callback_data=f"sub:stars:{code}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Общая подписка · доплатить",callback_data="pg:menu")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back:main")])
    return InlineKeyboardMarkup(rows)


async def on_subscription_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать пользователю варианты подписки."""

    query = update.callback_query
    await query.answer()
    user = update.effective_user
    user_id = await get_or_create_user(user.id, user.username)
    await show_screen(
        query,
        context,
        "Выбери вариант подписки:",
        build_subscription_keyboard(),
        user_id,
    )


async def on_subscription_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь выбрал конкретный план."""

    query = update.callback_query
    await query.answer()

    data = query.data
    parts = data.split(":")
    payment_method = "rub"
    if len(parts) == 2:
        _, plan_code = parts
    elif len(parts) == 3 and parts[1] == "stars":
        plan_code = parts[2]
        payment_method = "stars"
    else:
        await query.edit_message_text("Неизвестный тариф. Попробуйте ещё раз.")
        return

    plan = SUBSCRIPTION_PLANS.get(plan_code)
    if not plan:
        await query.edit_message_text("Неизвестный тариф. Попробуйте ещё раз.")
        return

    user = update.effective_user
    db_user_id = await get_or_create_user(user.id, user.username)
    title = plan["title"]
    if payment_method != "stars":
        payment_url = build_webapp_payment_url(plan_code)
        await show_screen(
            query,
            context,
            (
                f"Оплата тарифа «{title}» в рублях откроется на защищённой странице ЮKassa.\n"
                "Это основной сценарий оплаты рублями.\n"
                "Оплата звёздами остаётся внутри Telegram."
            ),
            InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Открыть оплату в рублях", web_app=WebAppInfo(payment_url))],
                [InlineKeyboardButton("⬅️ Назад", callback_data="back:main")],
            ]),
            db_user_id,
        )
        return

    if payment_method == "stars":
        payload = f"setsubstars:{db_user_id}:{plan_code}:{secrets.token_hex(8)}"
        currency = "XTR"
        amount = plan_amount_stars(plan["amount_rub"])
        prices = [LabeledPrice(label=f"{title} · звёзды", amount=amount)]
        provider_token = ""
        description = "Оплата подписки звёздами Telegram"
        payment_payload = {"plan": plan_code, "payment_method": "stars"}

    await create_payment_record(
        user_id=db_user_id,
        provider="telegram",
        amount=amount,
        currency=currency,
        status="pending",
        payload=payment_payload,
        external_id=payload,
    )

    try:
        await query.message.delete()
    except BadRequest:
        logger.debug("Failed to delete subscription menu message")
    else:
        last_messages.pop(query.message.chat_id, None)

    pay_button = InlineKeyboardButton("💳 Оплатить", pay=True)
    back_button = InlineKeyboardButton("⬅️ Назад", callback_data="back:main")
    back_markup = InlineKeyboardMarkup([[pay_button], [back_button]])

    await query.message.reply_invoice(
        title=title,
        description=description,
        provider_token=provider_token,
        currency=currency,
        prices=prices,
        payload=payload,
        need_name=False,
        need_phone_number=False,
        need_email=False,
        need_shipping_address=False,
        is_flexible=False,
        reply_markup=back_markup,
    )


async def on_subscription_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вернуться в главное меню из списка подписок."""

    query = update.callback_query
    await query.answer()

    user = update.effective_user
    user_id = await get_or_create_user(user.id, user.username)
    text, kb, _ = await compose_main_menu(user_id)
    await show_screen(query, context, text, kb, user_id)


async def _require_personal_subscription(q, user_id):
    row = await find_user_by_id(user_id)
    actor = getattr(q, 'from_user', None)
    if not row or actor is None or int(row[1]) != actor.id:
        await q.answer('Подпиской управляет владелец аккаунта. Откройте свой дневник.', show_alert=True)
        return False
    return True


async def show_subscription_overview(
    q, context: ContextTypes.DEFAULT_TYPE, user_id: int
):
    if not await _require_personal_subscription(q, user_id): return
    active = await get_active_subscription(user_id)
    tz_code = await get_user_timezone(user_id)
    zone = resolve_user_zone(tz_code)
    lines = [
        "Подписка — поддержка проекта и расширенный функционал (ИИ-функции, своя команда, больше подопечных и систем).",
        "▸ Бот остаётся бесплатным для всех.",
        "Спасибо за поддержку! ❤️",
        "",
    ]
    if active and active.get("expires_at"):
        expires_at = active["expires_at"]
        expires_label = expires_at.astimezone(zone).strftime("%d.%m.%Y")
        lines.append(f"Активна до {expires_label}.")
    else:
        lines.append("Подписка не оформлена.")
    lines.append("")
    lines.append("Оплата в рублях проходит на защищённой внешней странице ЮKassa через приложение.")
    lines.append("Оплата звёздами Telegram тоже доступна — прямо в Telegram.")
    rows: list[list[InlineKeyboardButton]] = []
    if TG_TOKEN:
        for code, plan in SUBSCRIPTION_PLANS.items():
            rub_label = f"{plan['title']} — {plan['amount_rub']} ₽"
            stars_price = plan_amount_stars(plan['amount_rub'])
            stars_label = f"{plan['title']} — {stars_price} ⭐"
            rows.append([
                InlineKeyboardButton(rub_label, web_app=WebAppInfo(build_webapp_payment_url(code))),
                InlineKeyboardButton(stars_label, callback_data=f"set:subscription:planstars:{code}"),
            ])
    rows.append([InlineKeyboardButton('Общая подписка · доплатить', callback_data='pg:menu')])
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")])
    kb = InlineKeyboardMarkup(rows)
    await show_screen(q, context, "\n".join(lines), kb, user_id)


async def start_subscription_payment(
    q, context: ContextTypes.DEFAULT_TYPE, user_id: int, plan_code: str
):
    if not await _require_personal_subscription(q, user_id): return
    plan = SUBSCRIPTION_PLANS.get(plan_code)
    if not plan:
        await q.answer("Тариф не найден.", show_alert=True)
        return

    payment_url = build_webapp_payment_url(plan_code)
    text = (
        f"Оплата тарифа «{plan['title']}» в рублях откроется во внешнем защищённом окне ЮKassa.\n"
        "Это основной способ оплаты в рублях.\n"
        "Оплата звёздами остаётся внутри Telegram."
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💳 Перейти к оплате в рублях", web_app=WebAppInfo(payment_url))],
            [InlineKeyboardButton(BACK_BTN, callback_data="set:subscription")],
        ]
    )
    await show_screen(q, context, text, kb, user_id)



async def start_subscription_payment_stars(
    q, context: ContextTypes.DEFAULT_TYPE, user_id: int, plan_code: str
):
    if not await _require_personal_subscription(q, user_id): return
    plan = SUBSCRIPTION_PLANS.get(plan_code)
    if not plan:
        await q.answer("Тариф не найден.", show_alert=True)
        return
    stars_amount = plan_amount_stars(plan['amount_rub'])
    payload = f"setsubstars:{user_id}:{plan_code}:{secrets.token_hex(8)}"
    try:
        user_info = await find_user_by_id(user_id)
        if not user_info:
            await q.answer("Пользователь не найден.", show_alert=True)
            return
        tg_user_id = int(user_info[1])
    except Exception:
        await q.answer("Не удалось создать счёт.", show_alert=True)
        return

    await create_payment_record(
        user_id=user_id,
        provider="telegram",
        amount=stars_amount,
        currency="XTR",
        status="pending",
        payload={"plan": plan_code, "payment_method": "stars"},
        external_id=payload,
    )

    try:
        await context.bot.send_invoice(
            chat_id=tg_user_id,
            title=f"Подписка — {plan['title']}",
            description="Оплата подписки звёздами Telegram",
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label=f"{plan['title']} · звёзды", amount=stars_amount)],
            provider_token="",
        )
    except Exception:
        await q.answer("Не удалось создать счёт в звёздах.", show_alert=True)
        return

    await q.answer("Счёт в звёздах отправлен.", show_alert=False)
    await show_subscription_overview(q, context, user_id)

def wizard_catalog_text(day: int, group: str, prefs: UiPreferences) -> str:
    templates = {
        "kb": (
            "День {day}. Каталог гирь.",
            "День {day}: гири.",
            "Отметь упражнения с гирями на этот день.",
        ),
        "workout": (
            "День {day}. Каталог воркаута.",
            "День {day}: воркаут.",
            "Выбери упражнения с турниками и брусьями.",
        ),
        "metcon": (
            "День {day}. Выбери формат меткона.",
            "День {day}: меткон.",
            "«На раунды» — максимум раундов за отведённое время, «На время» — комплекс на скорость.",
        ),
    }
    detailed, _compact, hint = templates.get(group, ("", "", ""))
    base = detailed.format(day=day) if detailed else ""
    if prefs.verbose_level and hint:
        return f"{base or day_exercises_text(day, group, None)}\n{hint}"
    return base or day_exercises_text(day, group, None)


def enrich_metcon_keyboard(
    day: int,
    markup: InlineKeyboardMarkup,
    selected: set[int],
    ex_rows: list[tuple[int, str]],
) -> InlineKeyboardMarkup:
    quick_map = [
        (AMRAP_EXERCISE_NAME, "На раунды"),
        (FOR_TIME_EXERCISE_NAME, "На время"),
    ]
    option_rows: list[list[InlineKeyboardButton]] = []
    nav_rows: list[list[InlineKeyboardButton]] = []
    custom_row: list[InlineKeyboardButton] | None = None
    control_row: list[InlineKeyboardButton] | None = None
    for row in markup.inline_keyboard:
        if not row:
            continue
        first_cb = row[0].callback_data or ""
        if first_cb.startswith(f"wiz:day:{day}:ex:custom:"):
            custom_row = row
        elif ":page:" in first_cb:
            nav_rows.append(row)
        elif first_cb.startswith(f"wiz:day:{day}:ex:back"):
            control_row = row
        elif first_cb.startswith(f"wiz:day:{day}:ex:done"):
            control_row = row if control_row is None else control_row
        else:
            option_rows.append(row)

    quick_rows: list[list[InlineKeyboardButton]] = []
    for name, short in quick_map:
        ex_id = next((eid for eid, title in ex_rows if title == name), None)
        if ex_id is None:
            continue
        target_cb = f"wiz:day:{day}:ex:add:{ex_id}"
        option_rows = [
            row
            for row in option_rows
            if not any(button.callback_data == target_cb for button in row)
        ]
        mark = "✅" if ex_id in selected else "⬜"
        quick_rows.append([InlineKeyboardButton(f"{mark} {short}", callback_data=target_cb)])

    new_rows = quick_rows + option_rows + nav_rows
    if custom_row:
        new_rows.append(custom_row)
    if control_row:
        new_rows.append(control_row)
    return InlineKeyboardMarkup(new_rows)


async def show_exercises(
    q,
    user_id: int,
    day: int,
    group: str,
    context,
    page: int | None = None,
):
    ex_rows = await list_exercises_by_group(group, user_id)
    selected_ids = set(await list_user_exercise_ids(user_id, day, group))
    custom = context.user_data.get("custom_groups", {})
    requested_page = page if page is not None else get_kb_page(context, "wiz", group, day)
    kb, actual_page, _ = exercises_kb(day, group, ex_rows, selected_ids, page=requested_page)
    set_kb_page(context, "wiz", group, actual_page, day)
    prefs = await load_ui_preferences(user_id)
    if group in {"kb", "metcon", "workout"}:
        text = wizard_catalog_text(day, group, prefs)
    else:
        text = day_exercises_text(day, group, custom)
    if group == "metcon":
        kb = enrich_metcon_keyboard(day, kb, selected_ids, ex_rows)
    await show_screen(q, context, text, kb, user_id)


async def show_day_add_exercises_view(
    q,
    user_id: int,
    day: int,
    group: str,
    context,
    page: int | None = None,
):
    ex_rows = await list_exercises_by_group(group, user_id)
    selected_ids = set(await list_user_exercise_ids(user_id, day, group))
    custom = context.user_data.get("custom_groups", {})
    requested_page = page if page is not None else get_kb_page(context, "day", group, day)
    kb, actual_page, _ = day_add_exercises_kb(
        day, group, ex_rows, selected_ids, page=requested_page, context=context
    )
    set_kb_page(context, "day", group, actual_page, day)
    await show_screen(q, context, day_exercises_text(day, group, custom), kb, user_id)


def library_exercises_text(group: str, custom: dict[str, str]) -> str:
    name = MG_NAMES.get(group, custom.get(group, group))
    return f"{name}. Отметь упражнения или добавь своё. Потом жми «{t('DONE')}»."


def library_manage_text(
    group: str,
    custom: dict[str, str],
    *,
    has_items: bool,
    can_delete_group: bool,
    mode: str = "manage",
) -> str:
    name = MG_NAMES.get(group, custom.get(group, group))
    lines = [name]
    if has_items:
        lines.append("Нажми на упражнение, чтобы удалить его из библиотеки.")
        if mode == "manage":
            lines.append("«Добавить» откроет каталог этой группы.")
        else:
            lines.append("Когда закончишь, вернись назад.")
    else:
        lines.append("Пока нет упражнений.")
        if mode == "manage":
            lines.append("Нажми «Добавить», чтобы пополнить эту группу.")
        else:
            lines.append("Удалять пока нечего — вернись назад, чтобы добавить упражнения.")
    if can_delete_group:
        lines.append(f"Можно удалить всю группу через «− {name}».")
    return "\n".join(lines)


async def show_library_add_exercises_view(
    q,
    user_id: int,
    group: str,
    context,
    *,
    page: int | None = None,
):
    context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
    ex_rows = await list_exercises_by_group(group, user_id)
    selected = set(await list_user_exercise_ids(user_id, 0, group))
    requested_page = page if page is not None else get_kb_page(context, "lib", group)
    kb, actual_page, _ = library_add_exercises_kb(
        group, ex_rows, selected, page=requested_page, context=context
    )
    set_kb_page(context, "lib", group, actual_page)
    custom = await get_custom_groups(user_id, context)
    await show_screen(
        q,
        context,
        library_exercises_text(group, custom),
        kb,
        user_id,
    )

async def finish_day(q, context, user_id: int, day: int, summary: str | None = None):
    n = context.user_data.get("workouts_per_week", 0)
    if day == 1:
        prefs = await load_ui_preferences(user_id)
        text = wizard_apply_text(prefs)
        if summary:
            text = summary + "\n────────\n" + text
        kb = wizard_apply_kb(n)
        await show_screen(q, context, text, kb, user_id)
        return
    if day >= n:
        text = "Отлично, супер! Мы сохранили все ваши данные. Теперь можете с удовольствием пользоваться."
        if summary:
            text = summary + "\n────────\n" + text
        _, menu_kb, _ = await compose_main_menu(user_id)
        await show_screen(q, context, text, menu_kb, user_id)
    else:
        context.user_data["current_day"] = day
        text = f"{t('DAY')} {day} сохранён. Перейти к {t('DAY')} {day + 1}?"
        if summary:
            text = summary + "\n────────\n" + text
        await show_screen(q, context, text, day_done_kb(day), user_id)

async def advance_day(q, context, user_id: int, next_day: int):
    n = context.user_data.get("workouts_per_week", 0)
    if next_day <= n:
        context.user_data["current_day"] = next_day
        context.user_data.setdefault("day_groups", {}).setdefault(next_day, set())
        context.user_data.pop("group_list", None)
        context.user_data.pop("group_idx", None)
        await prompt_day_mode(q, context, user_id, next_day)
    else:
        await show_screen(q, context, "Присылать напоминания перед тренировками?", reminders_kb(), user_id)


async def _wizard_finish_show_tips(q, context, user_id: int):
    await show_screen(
        q,
        context,
        ONBOARDING_TIPS,
        onboarding_tips_kb("wiz:tips:ok", INSTRUCTION_URL),
        user_id,
    )


async def finalize_wizard(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int | None = None,
) -> None:
    stored_chat_id = context.user_data.pop("wizard_chat_id", None)
    context.user_data.pop("wizard_msg_id", None)
    context.user_data.pop("wizard_onboarding", None)
    context.user_data.pop("wizard_onboarding_tz", None)
    intro_info = context.user_data.pop("wizard_intro_message", None)
    if chat_id is None:
        chat_id = stored_chat_id
    if chat_id is None:
        message = getattr(q, "message", None)
        chat = getattr(message, "chat", None) if message else None
        chat_id = getattr(chat, "id", None) if chat else getattr(message, "chat_id", None)
    intro_chat_id = intro_message_id = None
    if intro_info:
        intro_chat_id, intro_message_id = intro_info
    if not intro_chat_id or not intro_message_id:
        intro_chat_id, intro_message_id = await get_onboarding_intro_message(user_id)
    if intro_chat_id and intro_message_id:
        try:
            await context.bot.delete_message(intro_chat_id, intro_message_id)
        except (BadRequest, Forbidden):
            pass
    try:
        await clear_onboarding_intro_message(user_id)
    except Exception as exc:
        logger.warning("Failed to clear onboarding intro message: %s", exc)
    if chat_id is None:
        return
    await set_onboarding_completed(user_id, True)
    menu_text, menu_kb, prefs = await compose_main_menu(user_id)
    prepared_text, prepared_markup = prepare_ui_output(menu_text, menu_kb, prefs)
    await send_main_message_fresh(
        context.bot,
        chat_id,
        prepared_text,
        reply_markup=prepared_markup,
    )


async def prompt_day_mode(q, context, user_id: int, day: int):
    prefs = await load_ui_preferences(user_id)
    groups_store = context.user_data.setdefault("day_groups", {})
    selected_groups = groups_store.get(day)
    if selected_groups is None:
        selected_groups = set()
        groups_store[day] = selected_groups
    custom = await get_custom_groups(user_id, context)
    text = day_groups_text(day)
    if prefs.verbose_level:
        text += (
            "\nВыбирай все направления, которые подходят под цели тренировки. "
            "После выбора добавь упражнения и при необходимости дополни день позже."
        )
    kb = muscle_groups_kb(day, selected_groups, custom)
    await show_screen(q, context, text, kb, user_id)

async def wizard_router(
    update: Update, q, data: str, user_id: int, context: ContextTypes.DEFAULT_TYPE
):
    lock = user_locks[user_id]
    if lock.locked():
        await q.answer("Предыдущее действие ещё сохраняется.")
        return
    async with lock:
        await _wizard_router_unlocked(update, q, data, user_id, context)


async def _wizard_router_unlocked(
    update: Update, q, data: str, user_id: int, context: ContextTypes.DEFAULT_TYPE
):
    if not await require_edit_allowed(q, context):
        return
    message = getattr(q, "message", None)
    chat = getattr(message, "chat", None) if message else None
    chat_id = getattr(chat, "id", None) if chat else getattr(message, "chat_id", None)
    if isinstance(q, CallbackQuery) and data.startswith("wiz:"):
        try:
            await q.answer(cache_time=1)
        except TelegramError:
            pass
    try:
        if data == "wiz:intro:ok":
            # 1) Снимаем клавиатуру под видео (чтобы не спамили повторы)
            try:
                if q and q.message:
                    await q.answer()
                    await q.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            try:
                await clear_onboarding_video_message(user_id)
            except Exception as exc:
                logger.warning("Failed to clear onboarding video message: %s", exc)

            chat_id = q.message.chat_id if (q and q.message) else update.effective_chat.id

            # 2) Удаляем старое «привет»-сообщение (ищем и в context, и в БД)
            tup = context.user_data.get("wizard_intro_message")
            old_chat_id = old_msg_id = None
            if tup and isinstance(tup, tuple) and len(tup) == 2:
                old_chat_id, old_msg_id = tup
            if not old_chat_id or not old_msg_id:
                old_chat_id, old_msg_id = await get_onboarding_intro_message(user_id)
            if old_chat_id and old_msg_id:
                try:
                    await context.bot.delete_message(old_chat_id, old_msg_id)
                except Exception:
                    pass
            context.user_data.pop("wizard_intro_message", None)
            try:
                await clear_onboarding_intro_message(user_id)
            except Exception as exc:
                logger.warning("Failed to clear onboarding intro message: %s", exc)

            # 3) Пересылаем «привет» и первый вопрос визарда как два новых сообщения
            #    (поведение становится идентичным старой начальной настройке, только после видео)
            try:
                prefs = await load_ui_preferences(user_id)
                intro_text, _ = prepare_ui_output(t("ONBOARDING_INTRO"), None, prefs)
                intro_msg = await context.bot.send_message(chat_id, intro_text)
                context.user_data["wizard_intro_message"] = (
                    intro_msg.chat_id,
                    intro_msg.message_id,
                )
                try:
                    await set_onboarding_intro_message(
                        user_id,
                        intro_msg.chat_id,
                        intro_msg.message_id,
                    )
                except Exception as exc:
                    logger.warning("Failed to store onboarding intro message: %s", exc)

                prompt = "Сколько тренировок в неделю?"
                kb = week_count_kb()
                prompt_text, prompt_kb = prepare_ui_output(prompt, kb, prefs)
                await context.bot.send_message(chat_id, prompt_text, reply_markup=prompt_kb)

                # отметим, что дальше мы в мастер-режиме «одно сообщение»
                context.user_data["wizard_onboarding"] = True
            except Exception:
                # Фолбэк: хотя бы не уронить поток
                await context.bot.send_message(chat_id, "Давай продолжим: сколько тренировок в неделю?", reply_markup=week_count_kb())

            return
        if data == "wiz:sub:verify":
            context.user_data["wizard_onboarding"] = True
            await show_screen(
                q,
                context,
                "Сколько тренировок в неделю?",
                week_count_kb(),
                user_id,
            )
            return
        if data.startswith("wiz:week:set:"):
            try:
                n = int(data.split(":")[3])
            except (IndexError, ValueError):
                return
            n = max(1, min(7, n))
            removed = await set_workouts_per_week(user_id, n)
            if removed:
                _remove_jobs_for_removed_reminders(context.job_queue, user_id, removed)
            app = context.application
            if app is not None:
                await _schedule_user_reminders(app, user_id)
            context.user_data["workouts_per_week"] = n
            context.user_data.pop("reminder_day", None)
            context.user_data.pop("reminder_skip_tz", None)
            await show_screen(
                q,
                context,
                "Хочешь получать напоминания?",
                reminder_prompt_kb(),
                user_id,
            )
            return
        if data.startswith("wiz:base:"):
            parts = data.split(":")
            action = parts[2]
            day = context.user_data.get("baseline_day")
            idx = context.user_data.get("baseline_idx", 0)
            baseline_list: list[tuple[int, str, str]] = context.user_data.get(
                "baseline_list", []
            )
            if not baseline_list:
                return
            if context.user_data.get("baseline_user_id") != user_id:
                for key in ("baseline_day", "baseline_user_id", "baseline_list", "baseline_idx", "baseline_values", "baseline_done"):
                    context.user_data.pop(key, None)
                await q.answer("Дневник изменился. Откройте настройку упражнения заново.")
                return
            ex_id, name, ex_group = baseline_list[idx]
            vals_map = context.user_data.setdefault("baseline_values", {})
            if ex_id not in vals_map:
                existing = await get_baseline(user_id, day, ex_id)
                if existing:
                    vals_map[ex_id] = list(existing)
                else:
                    vals_map[ex_id] = [0, 0, 0, 0.0]
                while len(vals_map[ex_id]) < 4:
                    if len(vals_map[ex_id]) == 3:
                        vals_map[ex_id].append(0.0)
                    else:
                        vals_map[ex_id].append(0)
            values = vals_map[ex_id]
            with_weight, kind = get_display_flags(ex_group, name)
            if not with_weight:
                values[3] = 0.0
            done = context.user_data.setdefault("baseline_done", [])
            if not data.endswith(f":at:{baseline_scope(user_id, day, ex_id)}"):
                await show_screen(
                    q, context,
                    render_baseline_progress(done, name, *values, with_weight=with_weight, kind=kind),
                    baseline_kb(day, *values, with_weight=with_weight, kind=kind, user_id=user_id, exercise_id=ex_id),
                    user_id,
                )
                await q.answer("Кнопки обновлены для текущего упражнения.")
                return
            if action == "inc":
                field = parts[3]
                delta = float(parts[4])
                if field == "sets":
                    values[0] = max(0, values[0] + int(delta))
                elif field == "reps":
                    values[1] = max(0, values[1] + int(delta))
                elif field == "sec":
                    values[2] = max(0, values[2] + int(delta))
                elif field == "kg" and with_weight:
                    values[3] = max(0.0, values[3] + delta)
                await show_screen(
                    q,
                    context,
                    render_baseline_progress(
                        done, name, *values, with_weight=with_weight, kind=kind
                    ),
                    baseline_kb(day, *values, with_weight=with_weight, kind=kind, user_id=user_id, exercise_id=ex_id),
                    user_id,
                )
                return
            if action == "ready":
                await set_baseline(
                    user_id,
                    day,
                    ex_id,
                    values[0],
                    values[1],
                    values[2],
                    values[3] if with_weight else 0.0,
                )
                done.append(
                    f"{baseline_text(name, *values, with_weight=with_weight, kind=kind)} ✅"
                )
                idx += 1
                if idx < len(baseline_list):
                    context.user_data["baseline_idx"] = idx
                    ex_id, name, ex_group = baseline_list[idx]
                    if ex_id not in vals_map:
                        existing = await get_baseline(user_id, day, ex_id)
                        if existing:
                            vals_map[ex_id] = list(existing)
                        else:
                            vals_map[ex_id] = [0, 0, 0, 0.0]
                        while len(vals_map[ex_id]) < 4:
                            if len(vals_map[ex_id]) == 3:
                                vals_map[ex_id].append(0.0)
                            else:
                                vals_map[ex_id].append(0)
                    values = vals_map[ex_id]
                    next_with_weight, next_kind = get_display_flags(ex_group, name)
                    if not next_with_weight:
                        values[3] = 0.0
                    await show_screen(
                        q,
                        context,
                        render_baseline_progress(
                            done,
                            name,
                            *values,
                            with_weight=next_with_weight,
                            kind=next_kind,
                        ),
                        baseline_kb(
                            day,
                            *values,
                            user_id=user_id,
                            exercise_id=ex_id,
                            with_weight=next_with_weight,
                            kind=next_kind,
                        ),
                        user_id,
                    )
                else:
                    summary = "\n".join(done)
                    context.user_data.pop("baseline_day", None)
                    context.user_data.pop("baseline_list", None)
                    context.user_data.pop("baseline_idx", None)
                    context.user_data.pop("baseline_values", None)
                    context.user_data.pop("baseline_done", None)
                    await finish_day(q, context, user_id, day, summary)
                return
            if action == "skip":
                idx += 1
                if idx < len(baseline_list):
                    context.user_data["baseline_idx"] = idx
                    ex_id, name, ex_group = baseline_list[idx]
                    if ex_id not in vals_map:
                        existing = await get_baseline(user_id, day, ex_id)
                        if existing:
                            vals_map[ex_id] = list(existing)
                        else:
                            vals_map[ex_id] = [0, 0, 0, 0.0]
                        while len(vals_map[ex_id]) < 4:
                            if len(vals_map[ex_id]) == 3:
                                vals_map[ex_id].append(0.0)
                            else:
                                vals_map[ex_id].append(0)
                    values = vals_map[ex_id]
                    next_with_weight, next_kind = get_display_flags(ex_group, name)
                    if not next_with_weight:
                        values[3] = 0.0
                    await show_screen(
                        q,
                        context,
                        render_baseline_progress(
                            done,
                            name,
                            *values,
                            with_weight=next_with_weight,
                            kind=next_kind,
                        ),
                        baseline_kb(
                            day,
                            *values,
                            user_id=user_id,
                            exercise_id=ex_id,
                            with_weight=next_with_weight,
                            kind=next_kind,
                        ),
                        user_id,
                    )
                else:
                    summary = "\n".join(done)
                    context.user_data.pop("baseline_day", None)
                    context.user_data.pop("baseline_list", None)
                    context.user_data.pop("baseline_idx", None)
                    context.user_data.pop("baseline_values", None)
                    context.user_data.pop("baseline_done", None)
                    await finish_day(q, context, user_id, day, summary)
                return
            if action == "back":
                if idx > 0:
                    idx -= 1
                    context.user_data["baseline_idx"] = idx
                    if done:
                        done.pop()
                    ex_id, name, ex_group = baseline_list[idx]
                    values = vals_map[ex_id]
                    prev_with_weight, prev_kind = get_display_flags(ex_group, name)
                    if not prev_with_weight:
                        values[3] = 0.0
                    await show_screen(
                        q,
                        context,
                        render_baseline_progress(
                            done,
                            name,
                            *values,
                            with_weight=prev_with_weight,
                            kind=prev_kind,
                        ),
                        baseline_kb(
                            day,
                            *values,
                            user_id=user_id,
                            exercise_id=ex_id,
                            with_weight=prev_with_weight,
                            kind=prev_kind,
                        ),
                        user_id,
                    )
                else:
                    context.user_data.pop("baseline_day", None)
                    context.user_data.pop("baseline_list", None)
                    context.user_data.pop("baseline_idx", None)
                    context.user_data.pop("baseline_values", None)
                    context.user_data.pop("baseline_done", None)
                    selected = context.user_data.setdefault("day_groups", {}).get(day, set())
                    custom = await get_custom_groups(user_id, context)
                    await show_screen(q, context, day_groups_text(day), muscle_groups_kb(day, selected, custom), user_id)
                return
        if data.startswith("wiz:day:"):
            parts = data.split(":")
            day = int(parts[2])
            if parts[3] == "back":
                context.user_data.pop("group_list", None)
                context.user_data.pop("group_idx", None)
                await prompt_day_mode(q, context, user_id, day)
                return
            if parts[3] == "redo":
                selected = context.user_data.setdefault("day_groups", {}).get(day, set())
                custom = await get_custom_groups(user_id, context)
                await show_screen(q, context, day_groups_text(day), muscle_groups_kb(day, selected, custom), user_id)
                return
            if parts[3] == "mg":
                group = parts[4]
                if group == "other":
                    context.user_data["awaiting_group_name"] = (
                        day,
                        q.message.chat_id,
                        q.message.message_id,
                        "wizard",
                        user_id,
                    )
                    await show_screen(q, context, f'Укажи группу мышц для дня {day}, которой нет в списке.', None, user_id)
                    return
                selected = context.user_data.setdefault("day_groups", {}).setdefault(day, set())
                if group in selected:
                    selected.remove(group)
                else:
                    selected.add(group)
                custom = await get_custom_groups(user_id, context)
                await show_screen(q, context, day_groups_text(day), muscle_groups_kb(day, selected, custom), user_id)
                return
            if parts[3] == "groups" and parts[4] == "next":
                groups = list(context.user_data.setdefault("day_groups", {}).get(day, set()))
                if not groups:
                    await advance_day(q, context, user_id, day + 1)
                else:
                    context.user_data["group_list"] = groups
                    context.user_data["group_idx"] = 0
                    await show_exercises(q, user_id, day, groups[0], context)
                return
            if parts[3] == "skip":
                await advance_day(q, context, user_id, day + 1)
                return
            if parts[3] == "ex":
                action = parts[4]
                if action == "page":
                    group = parts[5]
                    requested_page = int(parts[6]) if len(parts) > 6 else 0
                    await show_exercises(q, user_id, day, group, context, page=requested_page)
                    return
                if action == "add":
                    ex_id = int(parts[5])
                    groups = context.user_data.get('group_list') or []
                    group_index = int(context.user_data.get('group_idx', 0))
                    if not 0 <= group_index < len(groups):
                        await q.answer('Выбор упражнений устарел. Выберите группу заново.', show_alert=True)
                        return
                    await _require_available_catalog_exercise(user_id, ex_id)
                    group = groups[group_index]
                    added = await toggle_user_exercise(user_id, day, ex_id)
                    if added:
                        async def edit_instant(text, kb):
                            await show_screen(q, context, text, kb, user_id)

                        started = await start_instant_baseline(
                            context,
                            user_id,
                            day,
                            ex_id,
                            "wiz",
                            group,
                            edit_instant,
                        )
                        if started:
                            return
                    await show_exercises(q, user_id, day, group, context)
                    return
                if action == "custom":
                    group = parts[5]
                    context.user_data["awaiting_custom"] = (
                        day,
                        group,
                        q.message.chat_id,
                        q.message.message_id,
                    )
                    kb = InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    t("BACK"),
                                    callback_data=f"wiz:day:{day}:ex:custom_back:{group}",
                                )
                            ]
                        ]
                    )
                    await show_screen(q, context, 'Напиши название упражнения:', kb, user_id)
                    return
                if action == "custom_back":
                    group = parts[5]
                    await show_exercises(q, user_id, day, group, context)
                    return
                if action == "back":
                    selected = context.user_data.setdefault("day_groups", {}).get(day, set())
                    custom = await get_custom_groups(user_id, context)
                    await show_screen(q, context, day_groups_text(day), muscle_groups_kb(day, selected, custom), user_id)
                    return
                if action == "done":
                    groups = context.user_data.get("group_list", [])
                    idx = context.user_data.get("group_idx", 0) + 1
                    if idx < len(groups):
                        context.user_data["group_idx"] = idx
                        await show_exercises(q, user_id, day, groups[idx], context)
                    else:
                        ex_rows = await list_day_exercises(user_id, day)
                        if ex_rows:
                            exs = [
                                (ex_id, name, resolve_group(name, group_code))
                                for ex_id, name, group_code in ex_rows
                            ]
                            context.user_data["baseline_day"] = day
                            context.user_data["baseline_user_id"] = user_id
                            context.user_data["baseline_list"] = exs
                            context.user_data["baseline_idx"] = 0
                            context.user_data["baseline_values"] = {}
                            context.user_data["baseline_done"] = []
                            ex_id, name, ex_group = exs[0]
                            vals_map = context.user_data["baseline_values"]
                            existing = await get_baseline(user_id, day, ex_id)
                            if existing:
                                vals_map[ex_id] = list(existing)
                            else:
                                vals_map[ex_id] = [0, 0, 0, 0.0]
                            while len(vals_map[ex_id]) < 4:
                                if len(vals_map[ex_id]) == 3:
                                    vals_map[ex_id].append(0.0)
                                else:
                                    vals_map[ex_id].append(0)
                            vals = vals_map[ex_id]
                            first_with_weight, first_kind = get_display_flags(ex_group, name)
                            if not first_with_weight:
                                vals[3] = 0.0
                            await show_screen(
                                q,
                                context,
                                render_baseline_progress(
                                    [],
                                    name,
                                    *vals,
                                    with_weight=first_with_weight,
                                    kind=first_kind,
                                ),
                                baseline_kb(
                                    day,
                                    *vals,
                                    user_id=user_id,
                                    exercise_id=ex_id,
                                    with_weight=first_with_weight,
                                    kind=first_kind,
                                ),
                                user_id,
                            )
                        else:
                            await finish_day(q, context, user_id, day)
                    return
            if parts[3] == "baseline" and parts[4] == "skip_all":
                baseline_list = context.user_data.get("baseline_list", [])
                idx = context.user_data.get("baseline_idx", 0)
                if (
                    not 0 <= idx < len(baseline_list)
                    or context.user_data.get("baseline_user_id") != user_id
                    or context.user_data.get("baseline_day") != day
                    or not data.endswith(f":at:{baseline_scope(user_id, day, baseline_list[idx][0])}")
                ):
                    await q.answer("Откройте актуальную настройку упражнения.")
                    return
                context.user_data.pop("baseline_list", None)
                context.user_data.pop("baseline_idx", None)
                context.user_data.pop("baseline_day", None)
                context.user_data.pop("baseline_values", None)
                context.user_data.pop("baseline_done", None)
                await finish_day(q, context, user_id, day)
                return
            if parts[3] == "next":
                await advance_day(q, context, user_id, day + 1)
                return
        if data.startswith("wiz:apply:"):
            parts = data.split(":")
            action = parts[2] if len(parts) > 2 else ""
            total_days = context.user_data.get("workouts_per_week", 0)
            if action == "all":
                if total_days > 1 and not context.user_data.get("wizard_copied_all_days"):
                    await copy_day_plan_to_other_days(user_id, 1, total_days)
                    context.user_data["wizard_copied_all_days"] = True
                prefs = await load_ui_preferences(user_id)
                text, kb, prefs = await compose_main_menu(user_id, prefs)
                await show_screen(q, context, text, kb, user_id)
                return
            if action == "next" and len(parts) > 3:
                next_day = int(parts[3])
                await advance_day(q, context, user_id, next_day)
                return
            if action == "menu":
                prefs = await load_ui_preferences(user_id)
                text, kb, prefs = await compose_main_menu(user_id, prefs)
                await show_screen(q, context, text, kb, user_id)
                return
        if data == "wiz:finish_early":
            day = context.user_data.get("current_day", 0)
            n = context.user_data.get("workouts_per_week", 0)
            if day < n:
                context.user_data["confirm_finish_day"] = day
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("Да", callback_data="wiz:finish_yes"), InlineKeyboardButton("Нет", callback_data="wiz:finish_no")]]
                )
                await show_screen(q, context, f'У тебя было заявлено {n} тренировок. Завершить на {day}?', kb, user_id)
            else:
                await _wizard_finish_show_tips(q, context, user_id)
            return
        if data == "wiz:finish_yes":
            await _wizard_finish_show_tips(q, context, user_id)
            return
        if data == "wiz:tips:ok":
            await finalize_wizard(q, context, user_id, chat_id)
            return
        if data == "wiz:finish_no":
            day = context.user_data.get("confirm_finish_day", 1)
            await show_screen(q, context, f"{t('DAY')} {day} сохранён. Перейти к {t('DAY')} {day + 1}?", day_done_kb(day), user_id)
            return
        if data == "wiz:reminders:yes":
            await set_user_notifications_enabled(user_id, True)
            app = context.application
            if app is not None:
                await _schedule_user_reminders(app, user_id, chat_id=chat_id)
            from_settings = context.user_data.get("from_settings")
            skip_tz = context.user_data.pop("reminder_skip_tz", None)
            tz_code = context.user_data.get("tz")
            if not tz_code:
                tz_code = await get_user_timezone(user_id)
                context.user_data["tz"] = tz_code
            if not skip_tz and tz_code and tz_code != "UTC":
                skip_tz = True
            if skip_tz:
                context.user_data[REMINDER_TIME_PAGE_KEY] = 0
                day_no = context.user_data.get("reminder_day") or 1
                context.user_data["reminder_day"] = day_no
                await show_screen(
                    q,
                    context,
                    f"{t('DAY')} {day_no}. В какой день недели тренировка?",
                    reminder_day_kb(),
                    user_id,
                )
                return
            context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
            context.user_data["tz_page"] = 0
            context.user_data["reminder_day"] = 1
            if not from_settings:
                context.user_data["wizard_onboarding_tz"] = "reminders"
            if "workouts_per_week" not in context.user_data:
                settings = await fetch_user_settings(user_id)
                context.user_data["workouts_per_week"] = settings[1] if settings else 0
            await show_screen(
                q,
                context,
                "Выбери свой часовой пояс:",
                tz_select_kb(0),
                user_id,
            )
            return
        if data == "wiz:reminders:no":
            await set_user_notifications_enabled(user_id, False)
            app = context.application
            if app is not None:
                await _schedule_user_reminders(app, user_id, chat_id=chat_id)
            if context.user_data.get("from_settings"):
                context.user_data.pop("from_settings", None)
                context.user_data.pop("reminder_skip_tz", None)
                context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
                kb = await build_settings_keyboard_for_user(context, user_id)
                await show_screen(q, context, 'Настройки:', kb, user_id)
                return
            context.user_data.pop("reminder_skip_tz", None)
            context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
            tz_code = context.user_data.get("tz")
            if not tz_code:
                tz_code = await get_user_timezone(user_id)
                context.user_data["tz"] = tz_code
            needs_tz = not tz_code or tz_code == "UTC"
            if needs_tz:
                context.user_data["tz_page"] = 0
                context.user_data["wizard_onboarding_tz"] = "final"
                await show_screen(
                    q,
                    context,
                    "Выбери свой часовой пояс:",
                    tz_select_kb(0),
                    user_id,
                )
            else:
                await _wizard_finish_show_tips(q, context, user_id)
            return
        if data == "wiz:reminders:back":
            context.user_data.pop("reminder_skip_tz", None)
            context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
            if context.user_data.get("from_settings"):
                context.user_data.pop("from_settings", None)
                kb = await build_settings_keyboard_for_user(context, user_id)
                await show_screen(q, context, 'Настройки:', kb, user_id)
            else:
                day = context.user_data.get("current_day", 1)
                await show_screen(q, context, f"{t('DAY')} {day} сохранён. Перейти к {t('DAY')} {day + 1}?", day_done_kb(day), user_id)
            return
        if data.startswith("wiz:tzsel:"):
            parts = data.split(":")
            action = parts[2]
            if action == "page":
                page = int(parts[3])
                context.user_data["tz_page"] = page
                await show_screen(q, context, 'Выбери свой часовой пояс:', tz_select_kb(page), user_id)
            elif action == "set":
                tz = parts[3]
                context.user_data["tz"] = tz
                await set_user_timezone(user_id, tz)
                app = context.application
                if app is not None:
                    await _schedule_user_reminders(app, user_id, chat_id=chat_id)
                mode = context.user_data.pop("wizard_onboarding_tz", None)
                day_no = context.user_data.get("reminder_day", 1)
                tz_only_change = context.user_data.pop("tz_only_change", None)
                if tz_only_change:
                    tz_label = get_timezone_label(tz)
                    rems = await list_user_reminders(user_id)
                    enabled = await get_user_notifications_enabled(user_id)
                    overview = build_reminders_settings_text(tz_label, enabled, rems)
                    text = f"Часовой пояс обновлён: {tz_label}.\n\n{overview}"
                    await show_screen(q, context, text, reminders_edit_kb(enabled), user_id)
                elif mode == "final":
                    await _wizard_finish_show_tips(q, context, user_id)
                else:
                    context.user_data["reminder_day"] = day_no
                    await show_screen(
                        q,
                        context,
                        f"{t('DAY')} {day_no}. В какой день недели тренировка?",
                        reminder_day_kb(),
                        user_id,
                    )
            elif action == "back":
                if context.user_data.get("from_settings"):
                    context.user_data.pop("from_settings", None)
                    kb = await build_settings_keyboard_for_user(context, user_id)
                    await show_screen(q, context, 'Настройки:', kb, user_id)
                else:
                    await show_screen(q, context, 'Присылать напоминания перед тренировками?', reminders_kb(), user_id)
            return
        if data.startswith("wiz:rday:"):
            action = data.split(":")[2]
            if action == "back":
                page = context.user_data.get("tz_page", 0)
                await show_screen(q, context, 'Выбери свой часовой пояс:', tz_select_kb(page), user_id)
            else:
                try:
                    selected_dow = int(action) - 1
                except ValueError:
                    await q.answer()
                    return
                if not 0 <= selected_dow <= 6:
                    await q.answer()
                    return
                context.user_data["selected_dow"] = selected_dow
                context.user_data[REMINDER_TIME_PAGE_KEY] = 0
                tz_code = context.user_data.get("tz")
                if not tz_code:
                    tz_code = await get_user_timezone(user_id)
                    context.user_data["tz"] = tz_code
                tz_label = get_timezone_label(tz_code)
                await show_screen(
                    q,
                    context,
                    f"Во сколько напоминать в этот день? Выбери время (по {tz_label}).",
                    reminder_time_kb(page=0),
                    user_id,
                )
            return
        if data == "wiz:remind:back":
            day_no = context.user_data.get("reminder_day", 1)
            context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
            await show_screen(q, context, f"{t('DAY')} {day_no}. В какой день недели тренировка?", reminder_day_kb(), user_id)
            return
        if data.startswith("wiz:remind:"):
            parts = data.split(":")
            if len(parts) >= 4 and parts[2] == "page":
                try:
                    page = max(int(parts[3]), 0)
                except ValueError:
                    page = 0
                context.user_data[REMINDER_TIME_PAGE_KEY] = page
                tz_code = context.user_data.get("tz")
                if not tz_code:
                    tz_code = await get_user_timezone(user_id)
                    context.user_data["tz"] = tz_code
                tz_label = get_timezone_label(tz_code)
                await show_screen(
                    q,
                    context,
                    f"Во сколько напоминать в этот день? Выбери время (по {tz_label}).",
                    reminder_time_kb(page=page),
                    user_id,
                )
                return
            if len(parts) < 4:
                return
            _, _, hh, mm = parts[:4]
            hour, minute = int(hh), int(mm)
            dow_value = context.user_data.get("selected_dow")
            if dow_value is None:
                await q.answer("Сначала выбери день недели.", show_alert=True)
                return
            try:
                dow = int(dow_value)
            except (TypeError, ValueError):
                await q.answer("Не удалось определить день недели.", show_alert=True)
                return
            if not 0 <= dow <= 6:
                await q.answer("Не удалось определить день недели.", show_alert=True)
                return
            day_no = context.user_data.get("reminder_day", 1)
            if not await add_user_reminder(user_id, dow, hour, minute, day_no=day_no):
                await q.answer("Не удалось сохранить напоминание.", show_alert=True)
                return
            context.user_data.pop("selected_dow", None)
            message = getattr(q, "message", None)
            chat_id = getattr(message, "chat_id", None)
            if chat_id is None and message is not None:
                chat = getattr(message, "chat", None)
                chat_id = getattr(chat, "id", None)
            tz_code = context.user_data.get("tz")
            if not tz_code:
                tz_code = await get_user_timezone(user_id)
                context.user_data["tz"] = tz_code
            await _schedule_user_reminders(context.application, user_id, chat_id=chat_id)
            day_no = context.user_data.get("reminder_day", 1)
            total = context.user_data.get("workouts_per_week", 0)
            context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
            if day_no < total:
                context.user_data["reminder_day"] = day_no + 1
                await show_screen(q, context, f"{t('DAY')} {day_no + 1}. В какой день недели тренировка?", reminder_day_kb(), user_id)
                return
            if context.user_data.get("from_settings"):
                context.user_data.pop("from_settings", None)
                kb = await build_settings_keyboard_for_user(context, user_id)
                await show_screen(q, context, 'Настройки:', kb, user_id)
            else:
                _, menu_kb, _ = await compose_main_menu(user_id)
                await _wizard_finish_show_tips(q, context, user_id)
            return
    finally:
        message = getattr(q, "message", None)
        if message and not context.user_data.get("wizard_onboarding"):
            chat = getattr(message, "chat", None)
            chat_id = getattr(chat, "id", None) if chat else getattr(message, "chat_id", None)
            remember_message(chat_id, getattr(message, "message_id", None))


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and user.id in ADMIN_IDS:
        state = get_broadcast_state(context)
        if state and await handle_broadcast_text(update, context, state):
            return
    if not await require_subscription(update, context):
        return
    u = update.effective_user
    if not u:
        return
    actor_user_id = await get_or_create_user(u.id, u.username)
    acting_user_id = context.user_data.get("acting_user_id")
    user_id = await resolve_target_user_id(context, actor_user_id)
    if acting_user_id and user_id == actor_user_id:
        clear_linear_state(context.user_data)
        if update.message:
            await update.message.reply_text("Доступ к дневнику подопечного закрыт. Откройте нужный дневник заново.")
        return
    editing_trainee_alias = bool(context.user_data.get(TRAINER_TRAINEE_LABEL_INPUT_KEY))
    if not editing_trainee_alias and not await ensure_can_edit_from_message(context, update):
        return
    if context.user_data.get('_input_owner', user_id) != user_id:
        clear_linear_state(context.user_data)
        await update.message.reply_text('Дневник изменился. Откройте нужное поле заново.')
        return
    for input_key in (RUNNING_INPUT_KEY, MEASUREMENT_INPUT_KEY, MEASUREMENT_CUSTOM_KEY, MEASUREMENT_CATEGORY_INPUT_KEY):
        pending = context.user_data.get(input_key)
        if isinstance(pending, dict):
            try:
                matches_owner = int(pending.get('target_user_id', user_id)) == user_id
            except (TypeError, ValueError):
                matches_owner = False
            if not matches_owner:
                clear_linear_state(context.user_data)
                await update.message.reply_text('Дневник изменился. Откройте нужное поле заново.')
                return
    for input_key in (FOR_TIME_INPUT_KEY, EXERCISE_NOTE_INPUT_KEY, RUNNING_INPUT_KEY):
        pending = context.user_data.get(input_key)
        if isinstance(pending, dict) and not await _owns_active_exercise(user_id, int(pending.get('day') or 0), int(pending.get('ue_id') or 0)):
            context.user_data.pop(input_key, None)
            await update.message.reply_text('Упражнение больше недоступно. Откройте дневник заново.')
            return
    for input_key in (AMRAP_SCHEME_KEY, LIBRARY_CUSTOM_KEY, 'awaiting_group_name'):
        pending = context.user_data.get(input_key)
        if isinstance(pending, tuple) and pending[-1] != user_id:
            context.user_data.pop(input_key, None)
            await update.message.reply_text('Дневник изменился. Откройте нужное поле заново.')
            return
    if context.user_data.get(TRAINER_CODE_INPUT_KEY):
        if not update.message or update.message.text is None:
            return
        context.user_data.pop(TRAINER_CODE_INPUT_KEY, None)
        code_input = (update.message.text or "").strip()
        target = context.user_data.get(TRAINER_CODE_PROMPT_KEY)
        if not code_input:
            await try_delete(update.message)
            await _render_trainer_link_message(
                context,
                user_id,
                target if isinstance(target, tuple) else None,
                "Отправь код тренера в формате TR-XXXXX.",
                prompt_for_code=True,
                chat_id=update.effective_chat.id if update.effective_chat else None,
            )
            return
        trainer = await find_user_by_trainer_code(code_input)
        if not trainer:
            await try_delete(update.message)
            await _render_trainer_link_message(
                context,
                user_id,
                target if isinstance(target, tuple) else None,
                "Код тренера не найден.",
                prompt_for_code=True,
                chat_id=update.effective_chat.id if update.effective_chat else None,
            )
            return
        trainer_accepts = True
        if len(trainer) > 2:
            try:
                trainer_accepts = bool(int(trainer[2]))
            except (ValueError, TypeError):
                trainer_accepts = bool(trainer[2])
        if not trainer_accepts:
            await try_delete(update.message)
            await _render_trainer_link_message(
                context,
                user_id,
                target if isinstance(target, tuple) else None,
                "На данный момент этот тренер отключил прием заявок.",
                prompt_for_code=True,
                chat_id=update.effective_chat.id if update.effective_chat else None,
            )
            return
        trainer_id = int(trainer[0])
        link1 = await get_trainer_link(trainer_id, user_id)
        link2 = await get_trainer_link(user_id, trainer_id)
        active_statuses = {"pending", "accepted"}
        has_direct_link = bool(link1 and str(link1[1]) in active_statuses)
        has_reverse_link = bool(link2 and str(link2[1]) in active_statuses)
        if has_direct_link or has_reverse_link or trainer_id == user_id:
            await try_delete(update.message)
            await _render_trainer_link_message(
                context,
                user_id,
                target if isinstance(target, tuple) else None,
                "Этот пользователь уже связан с вами.",
                prompt_for_code=True,
                chat_id=update.effective_chat.id if update.effective_chat else None,
            )
            return
        can_edit_request = bool(
            context.user_data.get(TRAINER_PENDING_CAN_EDIT_KEY, False)
        )
        try:
            await create_trainer_request(trainer_id, user_id, can_edit_plan=can_edit_request)
        except ValueError as exc:
            await _render_trainer_link_message(
                context, user_id, target if isinstance(target, tuple) else None,
                str(exc), prompt_for_code=True,
                chat_id=update.effective_chat.id if update.effective_chat else None,
            )
            return
        context.user_data.pop(TRAINER_PENDING_CAN_EDIT_KEY, None)
        await try_delete(update.message)
        trainer_record = await find_user_by_id(trainer_id)
        trainer_username = trainer_record[2] if trainer_record else None
        trainer_tg_id = trainer_record[1] if trainer_record else None
        trainer_display = await _format_trainer_user_display(trainer_id)
        info_parts = [
            f"Имя пользователя: @{trainer_username}" if trainer_username else "Имя пользователя: не указано",
            f"Telegram ID: {trainer_tg_id}" if trainer_tg_id else "Telegram ID: недоступен",
            f"Внутренний ID: {trainer_id}",
        ]
        success_message = (
            f"Заявка отправлена тренеру {trainer_display}. Ждём подтверждения."
            f"\n{info_parts[0]}\n{info_parts[1]}\n{info_parts[2]}"
        )
        await _render_trainer_link_message(
            context,
            user_id,
            target if isinstance(target, tuple) else None,
            success_message,
            chat_id=update.effective_chat.id if update.effective_chat else None,
        )
        context.user_data.pop(TRAINER_CODE_PROMPT_KEY, None)
        return
    awaiting_trainer_label = context.user_data.get(TRAINER_LABEL_INPUT_KEY)
    if awaiting_trainer_label:
        if not update.message or update.message.text is None:
            return
        try:
            link_id = int(awaiting_trainer_label)
        except (TypeError, ValueError):
            context.user_data.pop(TRAINER_LABEL_INPUT_KEY, None)
            return
        link = await get_active_trainer_link_for_trainee(user_id)
        if not link or int(link[0]) != link_id:
            context.user_data.pop(TRAINER_LABEL_INPUT_KEY, None)
            await update.message.reply_text('Связь с тренером изменилась. Откройте настройки заново.')
            return
        new_label = normalize_whitespace(update.message.text)
        if not new_label:
            new_label = None
        context.user_data.pop(TRAINER_LABEL_INPUT_KEY, None)
        await try_delete(update.message)
        await update_trainer_label(link_id, new_label)
        target = context.user_data.get(TRAINER_SETTINGS_MESSAGE_KEY)
        await refresh_trainee_trainer_settings_message(
            context, user_id, target if isinstance(target, tuple) else None
        )
        return
    trainee_label_input = context.user_data.get(TRAINER_TRAINEE_LABEL_INPUT_KEY)
    if trainee_label_input:
        if not update.message or update.message.text is None:
            return
        try:
            link_id = int(trainee_label_input)
        except (TypeError, ValueError):
            context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
            return
        link = await get_trainer_link(actor_user_id, user_id)
        if not link or int(link[0]) != link_id or str(link[1]) != 'accepted':
            context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
            await update.message.reply_text('Связь с подопечным изменилась. Откройте настройки заново.')
            return
        new_label = normalize_whitespace(update.message.text)
        if not new_label:
            new_label = None
        context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
        await try_delete(update.message)
        await update_trainee_label(link_id, new_label)
        acting_id = context.user_data.get("acting_user_id")
        if not isinstance(acting_id, int):
            return
        target = context.user_data.get(TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY)
        await refresh_trainer_manage_trainee_message(
            context,
            actor_user_id,
            acting_id,
            target if isinstance(target, tuple) else None,
        )
        return
    referral_name_state = context.user_data.get(REFERRAL_NAME_INPUT_KEY)
    if referral_name_state:
        if not update.message or update.message.text is None:
            return
        name = normalize_whitespace(update.message.text or "")
        if not name:
            await update.message.reply_text("Имя не должно быть пустым.")
            return
        target_user_id = referral_name_state.get("target_user_id")
        try:
            target_user_id = int(target_user_id)
        except (TypeError, ValueError):
            target_user_id = user_id
        if target_user_id != user_id or target_user_id != actor_user_id:
            context.user_data.pop(REFERRAL_NAME_INPUT_KEY, None)
            return
        await create_or_update_referral_profile(target_user_id, name)
        await try_delete(update.message)
        chat_id = referral_name_state.get("chat_id")
        msg_id = referral_name_state.get("message_id")
        context.user_data.pop(REFERRAL_NAME_INPUT_KEY, None)
        if chat_id and msg_id:
            text, kb = await build_referral_screen(target_user_id)
            await context.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            remember_message(chat_id, msg_id)
        return
    referral_search_state = context.user_data.get(REFERRAL_ADMIN_SEARCH_KEY)
    if referral_search_state:
        if not update.message or update.message.text is None:
            return
        if update.effective_user.id not in ADMIN_IDS:
            context.user_data.pop(REFERRAL_ADMIN_SEARCH_KEY, None)
            return
        query = normalize_whitespace(update.message.text or "")
        await try_delete(update.message)
        context.user_data.pop(REFERRAL_ADMIN_SEARCH_KEY, None)
        context.user_data["refadmin_query"] = query or None
        context.user_data["refadmin_page"] = 0
        chat_id = referral_search_state.get("chat_id")
        msg_id = referral_search_state.get("message_id")
        if chat_id and msg_id:
            text, kb = await build_referral_admin_screen(page=0, search=query or None)
            await context.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
            )
            remember_message(chat_id, msg_id)
        return
    gift_days_state = context.user_data.get(GIFT_CODE_DAYS_INPUT_KEY)
    if gift_days_state:
        if not update.message or update.message.text is None:
            return
        if update.effective_user.id not in ADMIN_IDS:
            context.user_data.pop(GIFT_CODE_DAYS_INPUT_KEY, None)
            return
        target_user_id = gift_days_state.get("target_user_id")
        try:
            target_user_id = int(target_user_id)
        except (TypeError, ValueError):
            target_user_id = user_id
        if target_user_id != user_id:
            context.user_data.pop(GIFT_CODE_DAYS_INPUT_KEY, None)
            return
        text_input = normalize_whitespace(update.message.text or "")
        if not text_input.isdigit():
            await update.message.reply_text("Введи число дней, например: 30")
            return
        days = int(text_input)
        if days <= 0 or days > 3650:
            await update.message.reply_text("Укажи количество дней от 1 до 3650.")
            return
        code = f"GIFT-{''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))}"
        await create_gift_code(code, days, update.effective_user.id)
        await try_delete(update.message)
        chat_id = gift_days_state.get("chat_id")
        msg_id = gift_days_state.get("message_id")
        context.user_data.pop(GIFT_CODE_DAYS_INPUT_KEY, None)
        if chat_id and msg_id:
            result_text = (
                "✅ Подарочный код создан\n\n"
                f"Код: <code>{code}</code>\n"
                f"Срок: {days} дн.\n\n"
                "Передай его пользователю для активации в подписке."
            )
            kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("➕ Создать код", callback_data="settings:gift_code:create")],
                    [InlineKeyboardButton("📊 Коды", callback_data="settings:gift_code:codes")],
                    [InlineKeyboardButton(BACK_BTN, callback_data="settings:gift_code")],
                ]
            )
            await context.bot.edit_message_text(
                result_text,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            remember_message(chat_id, msg_id)
        return
    gift_code_state = context.user_data.get(GIFT_CODE_INPUT_KEY)
    if gift_code_state:
        if not update.message or update.message.text is None:
            return
        target_user_id = gift_code_state.get("target_user_id")
        try:
            target_user_id = int(target_user_id)
        except (TypeError, ValueError):
            target_user_id = user_id
        if target_user_id != user_id:
            context.user_data.pop(GIFT_CODE_INPUT_KEY, None)
            return
        code_input = normalize_whitespace(update.message.text or "").upper()
        await try_delete(update.message)
        chat_id = gift_code_state.get("chat_id")
        msg_id = gift_code_state.get("message_id")
        if not code_input:
            if chat_id and msg_id:
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(BACK_BTN, callback_data="settings:gift_code")]]
                )
                await context.bot.edit_message_text(
                    "🎟 Активация подарочного кода\n\n"
                    "Код не должен быть пустым.\n"
                    "Отправь код одним сообщением.\n"
                    "Пример: <code>GIFT-ABCD2345</code>",
                    chat_id=chat_id,
                    message_id=msg_id,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
                remember_message(chat_id, msg_id)
            return
        redeem_status, days = await redeem_gift_code_with_status(code_input, user_id)
        if redeem_status != "ok":
            if chat_id and msg_id:
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(BACK_BTN, callback_data="settings:gift_code")]]
                )
                if redeem_status == "already_used":
                    error_text = "❌ Этот подарочный код уже был использован."
                else:
                    error_text = "❌ Такого подарочного кода не существует."
                await context.bot.edit_message_text(
                    f"{error_text}\n\n"
                    "Проверь код и отправь снова одним сообщением.\n"
                    "Пример: <code>GIFT-ABCD2345</code>",
                    chat_id=chat_id,
                    message_id=msg_id,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
                remember_message(chat_id, msg_id)
            return
        context.user_data.pop(GIFT_CODE_INPUT_KEY, None)
        if chat_id and msg_id:
            menu_text, menu_kb, _ = await compose_main_menu(user_id)
            await context.bot.edit_message_text(
                "🎉 Поздравляем! Подарочный код активирован.\n"
                f"Вам начислено {days} дн. подписки.\n\n"
                f"{menu_text}",
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=menu_kb,
            )
            remember_message(chat_id, msg_id)
        return
    for_time_state = context.user_data.get(FOR_TIME_INPUT_KEY)
    if for_time_state:
        if not await ensure_can_edit_from_message(context, update):
            return
        if not update.message or not update.message.text:
            return
        try:
            seconds = parse_duration_input(update.message.text)
        except ValueError:
            await update.message.reply_text(
                "Не удалось распознать время. Используй формат ММ:СС или ЧЧ:ММ:СС."
            )
            return
        await try_delete(update.message)
        context.user_data.pop(FOR_TIME_INPUT_KEY, None)
        mode = for_time_state.get("mode", "add")
        is_library = bool(for_time_state.get("is_library"))
        day = int(for_time_state.get("day", 0))
        ue_id = int(for_time_state.get("ue_id", 0))
        value = float(seconds)
        if mode == "edit":
            updated = await update_last_measurement(user_id, FOR_TIME_METRIC, value, "")
            if not updated:
                await add_measurement_entry(user_id, FOR_TIME_METRIC, value, "")
        else:
            await add_measurement_entry(user_id, FOR_TIME_METRIC, value, "")
            if not is_library:
                today = await get_user_local_date(user_id)
                system_id = await _active_system_id(user_id)
                session_id = await get_or_create_today_session(user_id, today, day, system_id=system_id)
                await mark_exercise_done(session_id, ue_id)
        chat_id = for_time_state.get("chat_id")
        msg_id = for_time_state.get("message_id")
        sheet_info = for_time_state.get("sheet")
        if chat_id and msg_id:
            prefs = await load_ui_preferences(user_id)
            if sheet_info:
                target_day = int(sheet_info.get("day", day))
                target_page = int(sheet_info.get("page", 0))
                await render_day_sheet_by_id(
                    context, chat_id, msg_id, user_id, target_day, target_page
                )
                return
            elif mode == "edit":
                text, kb = await build_for_time_history_view(user_id, day, ue_id, prefs=prefs)
            else:
                selected = get_flex_selected(context, day, ue_id)
                view = await render_exercise_view(
                    user_id, day, ue_id, selected, prefs=prefs
                )
                set_flex_selected(context, day, ue_id, view.selected_set)
                kb = build_exercise_actions_markup(
                    view,
                    day=day,
                    ue_id=ue_id,
                    group=view.group,
                    prefs=prefs,
                    is_library=is_library,
                    context=context,
                )
            output_text = view.text if mode != "edit" else text
            text, kb = prepare_ui_output(output_text, kb, prefs)
            await context.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
            )
            remember_message(chat_id, msg_id)
        return
    note_state = context.user_data.get(EXERCISE_NOTE_INPUT_KEY)
    if note_state:
        if not await ensure_can_edit_from_message(context, update):
            return
        if not update.message or update.message.text is None:
            return
        note_text = normalize_whitespace(update.message.text)
        if not note_text:
            await update.message.reply_text(t("NOTE_EMPTY"))
            return
        await try_delete(update.message)
        context.user_data.pop(EXERCISE_NOTE_INPUT_KEY, None)
        day = int(note_state.get("day", 0))
        ue_id = int(note_state.get("ue_id", 0))
        ex_id, _name, _group = await get_exercise_info(ue_id)
        await set_exercise_persistent_note(user_id, ex_id, note_text)
        chat_id = note_state.get("chat_id")
        msg_id = note_state.get("message_id")
        if chat_id and msg_id:
            prefs = await load_ui_preferences(user_id)
            selected = get_flex_selected(context, day, ue_id)
            view = await render_exercise_view(
                user_id, day, ue_id, selected, prefs=prefs
            )
            set_flex_selected(context, day, ue_id, view.selected_set)
            kb = build_exercise_actions_markup(
                view,
                day=day,
                ue_id=ue_id,
                group=view.group,
                prefs=prefs,
                is_library=bool(note_state.get("is_library")),
                context=context,
            )
            text_out, kb_out = prepare_ui_output(view.text, kb, prefs)
            await context.bot.edit_message_text(
                text_out,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb_out,
            )
            remember_message(chat_id, msg_id)
        return
    running_state = context.user_data.get(RUNNING_INPUT_KEY)
    if running_state:
        if not await ensure_can_edit_from_message(context, update):
            return
        if not update.message or not update.message.text:
            return
        field = running_state.get("field")
        entry_id = int(running_state.get("entry_id") or 0)
        if not entry_id:
            context.user_data.pop(RUNNING_INPUT_KEY, None)
            return
        entry_row = await get_running_entry_by_id(entry_id)
        if not entry_row or (entry_row[1], entry_row[2], entry_row[4]) != (user_id, int(running_state.get("ue_id", 0)), int(running_state.get("day", 0))):
            context.user_data.pop(RUNNING_INPUT_KEY, None)
            await update.message.reply_text('Запись бега изменилась. Откройте упражнение заново.')
            return
        text_value = update.message.text
        try:
            if field == "distance":
                new_distance = parse_distance_input(text_value)
                update_kwargs = {"distance_km": new_distance, "is_draft": 1}
            elif field == "time":
                duration = clamp_running_duration(parse_duration_input(text_value))
                update_kwargs = {
                    "duration_sec": duration,
                    "duration_ms": duration * 1000,
                    "is_draft": 1,
                }
            elif field == "pace":
                pace_seconds = clamp_running_duration(parse_duration_input(text_value))
                distance_value = float(entry_row[5] or 0.0)
                safe_distance, new_duration = apply_pace_to_entry(
                    distance_value, pace_seconds
                )
                update_kwargs = {
                    "distance_km": safe_distance,
                    "duration_sec": new_duration,
                    "duration_ms": new_duration * 1000,
                    "is_draft": 1,
                }
            elif field == "calories":
                calories = parse_calories_input(text_value)
                update_kwargs = {"calories": calories, "is_draft": 1}
            else:
                update_kwargs = {}
        except Exception:
            await update.message.reply_text(
                "Не удалось распознать значение. Используй подсказку и попробуй ещё раз."
            )
            return
        await try_delete(update.message)
        context.user_data.pop(RUNNING_INPUT_KEY, None)
        target_user_id = running_state.get("target_user_id")
        try:
            target_user_id = int(target_user_id)
        except (TypeError, ValueError):
            target_user_id = user_id
        if update_kwargs:
            await update_running_entry(entry_id, **update_kwargs)
        chat_id = running_state.get("chat_id")
        msg_id = running_state.get("message_id")
        if not chat_id or not msg_id:
            return
        sheet_info = running_state.get("sheet")
        is_library = bool(running_state.get("is_library"))
        prefs = await load_ui_preferences(target_user_id)
        if sheet_info and not is_library:
            target_day = int(sheet_info.get("day", running_state.get("day", 0)))
            target_page = int(sheet_info.get("page", 0))
            await render_day_sheet_by_id(
                context,
                chat_id,
                msg_id,
                target_user_id,
                target_day,
                target_page,
                prefs=prefs,
            )
            return
        day = int(running_state.get("day", 0))
        ue_id = int(running_state.get("ue_id", 0))
        selected = get_flex_selected(context, day, ue_id)
        view = await render_exercise_view(
            target_user_id, day, ue_id, selected, prefs=prefs
        )
        set_flex_selected(context, day, ue_id, view.selected_set)
        kb = build_exercise_actions_markup(
            view,
            day=day,
            ue_id=ue_id,
            group=view.group,
            prefs=prefs,
            is_library=is_library,
            context=context,
        )
        text, kb = prepare_ui_output(view.text, kb, prefs)
        await context.bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=kb,
        )
        remember_message(chat_id, msg_id)
        return
    category_state = context.user_data.get(MEASUREMENT_CATEGORY_INPUT_KEY)
    if category_state:
        if not await ensure_can_edit_from_message(context, update):
            return
        name = normalize_whitespace(update.message.text or "")
        if not name:
            await update.message.reply_text("Название не должно быть пустым.")
            return
        await try_delete(update.message)
        target_user_id = category_state.get("target_user_id")
        try:
            target_user_id = int(target_user_id)
        except (TypeError, ValueError):
            target_user_id = user_id
        custom_items = await load_custom_measurements(target_user_id, context)
        user_categories = await load_measurement_categories(target_user_id, context)
        letter = next_category_letter(user_categories, custom_items)
        await add_measurement_category(target_user_id, letter, name)
        user_categories = await load_measurement_categories(target_user_id, context)
        chat_id = category_state.get("chat_id")
        msg_id = category_state.get("message_id")
        back_callback = category_state.get("back", "measure:add")
        mode = category_state.get("mode", "add")
        pending_name = category_state.get("pending_name")
        context.user_data.pop(MEASUREMENT_CATEGORY_INPUT_KEY, None)
        if not chat_id or not msg_id:
            return
        prefs = await load_ui_preferences(target_user_id)
        custom_items = await load_custom_measurements(target_user_id, context)
        categories = measurement_categories_list(
            user_categories,
            include_custom_fallback=True,
            custom_items=custom_items,
        )
        if mode == "customplace":
            custom_state = context.user_data.get(MEASUREMENT_CUSTOM_KEY)
            if custom_state:
                updated_state = dict(custom_state)
                updated_state["step"] = "category"
                if pending_name:
                    updated_state["pending_name"] = pending_name
                context.user_data[MEASUREMENT_CUSTOM_KEY] = updated_state
            prompt = (
                f"В какую категорию добавить «{pending_name}»?"
                if pending_name
                else "Выбери категорию:"
            )
            kb = measurements_category_kb(
                'customplace',
                categories,
                back_callback=back_callback,
                context=context,
            )
        else:
            prompt = 'Выбери категорию:'
            kb = measurements_manage_overview_kb(
                categories,
                include_delete=bool(custom_items or user_categories),
                back_callback=back_callback,
                context=context,
            )
        context.user_data[MEASUREMENT_CATEGORY_BACK_KEY] = back_callback
        text, kb = prepare_ui_output(prompt, kb, prefs)
        await context.bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=kb,
        )
        remember_message(chat_id, msg_id)
        return
    custom_state = context.user_data.get(MEASUREMENT_CUSTOM_KEY)
    if custom_state:
        if not await ensure_can_edit_from_message(context, update):
            return
        step = custom_state.get("step", "name")
        if step == "name":
            name = normalize_whitespace(update.message.text or "")
            if not name:
                await update.message.reply_text("Название не должно быть пустым.")
                return
            await try_delete(update.message)
            target_user_id = custom_state.get("target_user_id")
            try:
                target_user_id = int(target_user_id)
            except (TypeError, ValueError):
                target_user_id = user_id
            chat_id = custom_state.get("chat_id")
            msg_id = custom_state.get("message_id")
            back_callback = custom_state.get("back", "measure:add")
            if not chat_id or not msg_id:
                context.user_data.pop(MEASUREMENT_CUSTOM_KEY, None)
                return
            custom_items = await load_custom_measurements(target_user_id, context)
            user_categories = await load_measurement_categories(target_user_id, context)
            categories = measurement_categories_list(
                user_categories,
                include_custom_fallback=True,
                custom_items=custom_items,
            )
            origin = (custom_state.get("origin") or "").strip()
            if origin and any(code == origin for code, _ in categories):
                await prompt_custom_measurement_value(
                    context,
                    target_user_id,
                    chat_id,
                    msg_id,
                    back_callback,
                    name,
                    origin,
                )
                return
            updated_state = dict(custom_state)
            updated_state["pending_name"] = name
            updated_state["step"] = "category"
            context.user_data[MEASUREMENT_CUSTOM_KEY] = updated_state
            prompt = f"В какую категорию добавить «{name}»?"
            kb = measurements_category_kb(
                'customplace',
                categories,
                back_callback=back_callback,
                context=context,
            )
            prefs = await load_ui_preferences(target_user_id)
            text, kb = prepare_ui_output(prompt, kb, prefs)
            await context.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
            )
            remember_message(chat_id, msg_id)
            return
        return
    input_state = context.user_data.get(MEASUREMENT_INPUT_KEY)
    if input_state:
        if not await ensure_can_edit_from_message(context, update):
            return
        item = await get_owned_measurement_item(user_id, input_state.get("metric"))
        if not item:
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            return
        try:
            value, extra = parse_measurement_input(item, update.message.text)
        except Exception:
            await update.message.reply_text(
                "Не удалось распознать значение. Используй пример на экране и попробуй ещё раз."
            )
            return
        u = update.effective_user
        actor_user_id = await get_or_create_user(u.id, u.username)
        target_user_id = input_state.get("target_user_id")
        try:
            target_user_id = int(target_user_id)
        except (TypeError, ValueError):
            target_user_id = await resolve_target_user_id(context, actor_user_id)
        action = input_state.get("action")
        if action == "add":
            await add_measurement_entry(target_user_id, item["code"], value, extra)
        else:
            updated = await update_last_measurement(
                target_user_id, item["code"], value, extra
            )
            if not updated:
                await add_measurement_entry(target_user_id, item["code"], value, extra)
        await try_delete(update.message)
        chat_id = input_state.get("chat_id")
        msg_id = input_state.get("message_id")
        context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
        if chat_id and msg_id:
            text, kb = await build_measurements_view(target_user_id, context)
            prefs = await load_ui_preferences(target_user_id)
            text, kb = prepare_ui_output(text, kb, prefs)
            await context.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
            )
            remember_message(chat_id, msg_id)
        return
    amrap_state = context.user_data.get(AMRAP_SCHEME_KEY)
    if amrap_state:
        if not await ensure_can_edit_from_message(context, update):
            return
        day, ue_id, chat_id, msg_id, target_user_id = context.user_data.pop(AMRAP_SCHEME_KEY)
        new_scheme = update.message.text.strip() if update.message and update.message.text else ""
        await try_delete(update.message)
        ex_id, name, raw_group = await get_exercise_info(ue_id)
        if resolve_group(name, raw_group) != "metcon" or name != AMRAP_EXERCISE_NAME:
            if chat_id and msg_id:
                await context.bot.edit_message_text(
                    "Не удалось изменить схему. Попробуй ещё раз.",
                    chat_id=chat_id,
                    message_id=msg_id,
                )
                remember_message(chat_id, msg_id)
            return
        await set_exercise_scheme(target_user_id, day, ex_id, new_scheme or None)
        selected = get_flex_selected(context, day, ue_id)
        prefs = await load_ui_preferences(target_user_id)
        view = await render_exercise_view(
            target_user_id, day, ue_id, selected, prefs=prefs
        )
        is_library = day == 0
        set_flex_selected(context, day, ue_id, view.selected_set)
        kb = build_exercise_actions_markup(
            view,
            day=day,
            ue_id=ue_id,
            group=view.group,
            prefs=prefs,
            is_library=is_library,
            context=context,
        )
        if chat_id and msg_id:
            text_view, kb = prepare_ui_output(view.text, kb, prefs)
            await context.bot.edit_message_text(
                text_view,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
            )
            remember_message(chat_id, msg_id)
        return
    lib_custom = context.user_data.get(LIBRARY_CUSTOM_KEY)
    if lib_custom:
        if not await ensure_can_edit_from_message(context, update):
            return
        group, chat_id, msg_id, target_user_id = lib_custom
        name = normalize_whitespace(update.message.text or "")
        if not name:
            await update.message.reply_text("Название не должно быть пустым. Попробуй ещё раз.")
            return
        context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
        await try_delete(update.message)
        exists = await user_has_library_exercise(target_user_id, name)
        if not exists:
            ex_id = await get_or_create_exercise(name, group, target_user_id)
            await add_user_exercise(target_user_id, 0, ex_id)
        ex_rows = await list_exercises_by_group(group, target_user_id)
        selected = set(await list_user_exercise_ids(target_user_id, 0, group))
        requested_page = get_kb_page(context, "lib", group)
        kb, page_value, _ = library_add_exercises_kb(
            group, ex_rows, selected, page=requested_page, context=context
        )
        set_kb_page(context, "lib", group, page_value)
        custom = await get_custom_groups(target_user_id, context)
        await context.bot.edit_message_text(
            library_exercises_text(group, custom),
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=kb,
        )
        remember_message(chat_id, msg_id)
        return
    if context.user_data.get("awaiting_group_name"):
        if not await ensure_can_edit_from_message(context, update):
            return
        day, chat_id, msg_id, mode, target_user_id = context.user_data.pop("awaiting_group_name")
        name = normalize_whitespace(update.message.text or "")
        if not name:
            context.user_data["awaiting_group_name"] = (day, chat_id, msg_id, mode, target_user_id)
            await update.message.reply_text("Название не должно быть пустым.")
            return
        code = await add_user_muscle_group(target_user_id, name)
        custom = await get_custom_groups(target_user_id, context)
        custom[code] = name
        await try_delete(update.message)
        if mode == "wizard":
            selected = context.user_data.setdefault("day_groups", {}).setdefault(day, set())
            selected.add(code)
            await context.bot.edit_message_text(
                day_groups_text(day),
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=muscle_groups_kb(day, selected, custom),
            )
            remember_message(chat_id, msg_id)
        elif mode == "library":
            context.user_data["lib_return"] = ("group", code)
            ex_rows = await list_exercises_by_group(code, target_user_id)
            selected_ids = set(await list_user_exercise_ids(target_user_id, 0, code))
            requested_page = get_kb_page(context, "lib", code)
            kb, page_value, _ = library_add_exercises_kb(
                code, ex_rows, selected_ids, page=requested_page, context=context
            )
            set_kb_page(context, "lib", code, page_value)
            await context.bot.edit_message_text(
                library_exercises_text(code, custom),
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
            )
            remember_message(chat_id, msg_id)
        else:
            context.user_data["add_group"] = (day, code)
            ex_rows = await list_exercises_by_group(code, target_user_id)
            selected_ids = set(await list_user_exercise_ids(target_user_id, day, code))
            requested_page = get_kb_page(context, "day", code, day)
            kb, page_value, _ = day_add_exercises_kb(
                day, code, ex_rows, selected_ids, page=requested_page, context=context
            )
            set_kb_page(context, "day", code, page_value, day)
            await context.bot.edit_message_text(
                day_exercises_text(day, code, custom),
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
            )
            remember_message(chat_id, msg_id)
        return
    if context.user_data.get("awaiting_rename"):
        if not await ensure_can_edit_from_message(context, update):
            return
        day, chat_id, msg_id = context.user_data.pop("awaiting_rename")
        label = update.message.text.strip()
        await rename_day(user_id, day, label)
        await try_delete(update.message)
        kb = await build_settings_keyboard_for_user(context, user_id)
        await send_main_message(
            context.bot,
            chat_id,
            "Настройки:",
            reply_markup=kb,
        )
        return
    if context.user_data.get("awaiting_custom"):
        if not await ensure_can_edit_from_message(context, update):
            return
        day, group, chat_id, msg_id = context.user_data.pop("awaiting_custom")
        name = normalize_whitespace(update.message.text or "")
        if not name:
            context.user_data["awaiting_custom"] = (day, group, chat_id, msg_id)
            await update.message.reply_text("Название не должно быть пустым.")
            return
        await try_delete(update.message)
        ex_id = await get_or_create_exercise(name, group, user_id)
        selected_ids = set(await list_user_exercise_ids(user_id, day, group))
        existed = ex_id in selected_ids
        await add_user_exercise(user_id, day, ex_id)
        source = "day" if context.user_data.get("add_group") == (day, group) else "wiz"

        async def edit_instant(text, kb):
            await context.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
            )
            remember_message(chat_id, msg_id)

        if not existed:
            started = await start_instant_baseline(
                context,
                user_id,
                day,
                ex_id,
                source,
                group,
                edit_instant,
            )
            if started:
                return

        ex_rows = await list_exercises_by_group(group, user_id)
        custom = context.user_data.get("custom_groups", {})
        if source == "day":
            requested_page = get_kb_page(context, "day", group, day)
            kb, page_value, _ = day_add_exercises_kb(
                day, group, ex_rows, selected_ids, page=requested_page, context=context
            )
            set_kb_page(context, "day", group, page_value, day)
        else:
            requested_page = get_kb_page(context, "wiz", group, day)
            kb, page_value, _ = exercises_kb(
                day, group, ex_rows, selected_ids, page=requested_page
            )
            set_kb_page(context, "wiz", group, page_value, day)
        await edit_instant(day_exercises_text(day, group, custom), kb)
        return

async def photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and user.id in ADMIN_IDS:
        state = get_broadcast_state(context)
        if state and state.get("step") == "await_photo":
            if await handle_broadcast_photo(update, context, state):
                return
    if not await require_subscription(update, context):
        return


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q: CallbackQuery | None = None
    target_user_id: int | None = None
    try:
        q = update.callback_query
        if q is None or getattr(q, 'message', None) is None:
            return
        with contextlib.suppress(TelegramError):
            await q.answer()
        data = q.data or ""
        preserve_keys: set[str] = set()
        if data.startswith("broadcast:"):
            preserve_keys.add(BROADCAST_STATE_KEY)
        if data.startswith('day:add:') or data.startswith('ib:day:'):
            preserve_keys.add('add_group')
        if data == 'measure:add:category' or data.startswith('measure:add:custom:cat:'):
            preserve_keys.add(MEASUREMENT_CUSTOM_KEY)
        clear_linear_state(context.user_data, preserve_keys)
        user = update.effective_user
        if user is None:
            return
        actor_user_id = await get_or_create_user(user.id, user.username)
        context.user_data["is_admin_actor"] = bool(user.id in ADMIN_IDS)
        previous_acting = context.user_data.get('acting_user_id')
        target_user_id = await resolve_target_user_id(context, actor_user_id)
        if target_user_id != actor_user_id and data.startswith(('set:subscription', 'settings:referral', 'settings:notifications')):
            await q.answer('Этот раздел личный. Откройте свой дневник для подписки и настроек аккаунта.', show_alert=True)
            return
        if previous_acting and target_user_id == actor_user_id:
            await q.answer('Доступ к дневнику подопечного закрыт. Откройте дневник заново.', show_alert=True)
            return
        custom_input = context.user_data.get(MEASUREMENT_CUSTOM_KEY)
        if isinstance(custom_input, dict) and custom_input.get('target_user_id') != target_user_id:
            clear_linear_state(context.user_data)
            await q.answer('Дневник изменился. Откройте нужное поле заново.', show_alert=True)
            return
        context.user_data['_input_owner'] = target_user_id
        if data == MAIL_RETURN_CALLBACK:
            chat = getattr(q, "message", None)
            chat_id = getattr(chat, "chat_id", None)
            if chat_id is None:
                return
            text, kb, _ = await compose_main_menu(target_user_id)
            await send_main_message_fresh(
                context.bot,
                chat_id,
                text,
                reply_markup=kb,
            )
            return
        if data.startswith("broadcast:"):
            if user and user.id in ADMIN_IDS:
                await handle_broadcast_callback(q, context)
            else:
                await q.answer("Недоступно.", show_alert=True)
            return
        if not await require_subscription(update, context):
            return
        if data == "noop":
            return
        remember_message(q.message.chat_id, q.message.message_id)

        if data.startswith("trainer:"):
            parts = data.split(":")
            if len(parts) < 2:
                return
            action = parts[1]
            trainee_actions = {"settings", "allow", "label", "detach"}
            if action in trainee_actions:
                acting_id = context.user_data.get("acting_user_id")
                if action == "settings":
                    context.user_data.pop(TRAINER_LABEL_INPUT_KEY, None)
                    link = await get_active_trainer_link_for_trainee(target_user_id)
                    if not link or str(link[2]) != "accepted":
                        await show_become_trainee_screen(q, context, target_user_id)
                        return
                    await show_trainee_trainer_settings(q, context, target_user_id)
                    return
                if action == "allow" and len(parts) >= 3:
                    desired = parts[2]
                    allow_on = desired == "on"
                    if acting_id:
                        await q.answer(
                            "Подопечный сам управляет этим в своих настройках.",
                            show_alert=True,
                        )
                        return
                    link = await get_active_trainer_link_for_trainee(target_user_id)
                    new_value = 1 if allow_on else 0
                    if link and str(link[2]) == "accepted":
                        link_id = int(link[0])
                        await update_trainer_link_permissions(link_id, new_value)
                        await show_trainee_trainer_settings(
                            q, context, target_user_id
                        )
                        return
                    if link and str(link[2]) == "pending":
                        await update_trainer_link_permissions(int(link[0]), new_value)
                        context.user_data[TRAINER_PENDING_CAN_EDIT_KEY] = allow_on
                    else:
                        context.user_data[TRAINER_PENDING_CAN_EDIT_KEY] = allow_on
                    await show_become_trainee_screen(q, context, target_user_id)
                    return
                if action == "label" and len(parts) >= 3:
                    sub_action = parts[2]
                    if sub_action == "set":
                        if acting_id:
                            link = await get_trainer_link(actor_user_id, acting_id)
                            if not link or str(link[1]) != "accepted":
                                await q.answer("Связь недоступна.", show_alert=True)
                                return
                            link_id = int(link[0])
                            context.user_data[TRAINER_TRAINEE_LABEL_INPUT_KEY] = link_id
                            message = await show_screen(
                                q,
                                context,
                                "Отправь подпись для подопечного одним сообщением.",
                                InlineKeyboardMarkup(
                                    [
                                        [
                                            InlineKeyboardButton(
                                                "⬅️ Назад",
                                                callback_data="trainer:trainee_settings",
                                            )
                                        ]
                                    ]
                                ),
                                acting_id,
                            )
                            if message:
                                context.user_data[
                                    TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY
                                ] = (
                                    getattr(message, "chat_id", None),
                                    getattr(message, "message_id", None),
                                )
                            return
                        link = await get_active_trainer_link_for_trainee(target_user_id)
                        if not link:
                            await show_trainee_trainer_settings(q, context, target_user_id)
                            return
                        link_id = int(link[0])
                        context.user_data[TRAINER_LABEL_INPUT_KEY] = link_id
                        message = await show_screen(
                            q,
                            context,
                            "Отправь новое имя тренера одним сообщением.",
                            InlineKeyboardMarkup(
                                [
                                    [
                                        InlineKeyboardButton(
                                            "⬅️ Отмена",
                                            callback_data="trainer:settings",
                                        )
                                    ]
                                ]
                            ),
                            target_user_id,
                        )
                        if message:
                            context.user_data[TRAINER_SETTINGS_MESSAGE_KEY] = (
                                getattr(message, "chat_id", None),
                                getattr(message, "message_id", None),
                            )
                    return
                if action == "detach":
                    sub_action = parts[2] if len(parts) >= 3 else "start"
                    if sub_action == "cancel":
                        if acting_id:
                            await show_trainer_manage_trainee(
                                q, context, actor_user_id, acting_id
                            )
                        else:
                            await show_trainee_trainer_settings(
                                q, context, target_user_id
                            )
                        return
                    if sub_action != "confirm":
                        if acting_id:
                            link = await get_trainer_link(actor_user_id, acting_id)
                            if not link or str(link[1]) != "accepted":
                                await q.answer("Связь недоступна.", show_alert=True)
                                return
                            trainee_display = await _format_trainer_user_display(
                                acting_id
                            )
                            confirm_text = (
                                f"Открепить подопечного {trainee_display}?\n"
                                "Тренер потеряет доступ к дневнику и плану."
                            )
                            kb = InlineKeyboardMarkup(
                                [
                                    [
                                        InlineKeyboardButton(
                                            "✅ Да, открепить",
                                            callback_data="trainer:detach:confirm",
                                        )
                                    ],
                                    [
                                        InlineKeyboardButton(
                                            "⬅️ Назад",
                                            callback_data="trainer:trainee_settings",
                                        )
                                    ],
                                ]
                            )
                            await show_screen(
                                q,
                                context,
                                confirm_text,
                                kb,
                                actor_user_id,
                            )
                            return
                        link = await get_active_trainer_link_for_trainee(
                            target_user_id
                        )
                        if not link:
                            await show_trainee_trainer_settings(
                                q, context, target_user_id
                            )
                            return
                        trainer_user_id = int(link[1])
                        trainer_display = await _format_trainer_user_display(
                            trainer_user_id
                        )
                        confirm_text = (
                            f"Вы уверены, что хотите отвязаться от {trainer_display}?\n"
                            "Связь будет удалена, и тренер не увидит ваш дневник."
                        )
                        kb = InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "✅ Да, отвязаться",
                                        callback_data="trainer:detach:confirm",
                                    )
                                ],
                                [
                                    InlineKeyboardButton(
                                        "⬅️ Отмена",
                                        callback_data="trainer:detach:cancel",
                                    )
                                ],
                            ]
                        )
                        await show_screen(
                            q,
                            context,
                            confirm_text,
                            kb,
                            target_user_id,
                        )
                        return
                    if acting_id:
                        link = await get_trainer_link(actor_user_id, acting_id)
                        if not link or str(link[1]) != "accepted":
                            await q.answer("Связь недоступна.", show_alert=True)
                            return
                        await update_trainer_link_status(int(link[0]), "removed")
                        context.user_data.pop("acting_user_id", None)
                        context.user_data.pop("acting_can_edit", None)
                        context.user_data.pop(RESOLVE_TARGET_USER_KEY, None)
                        context.user_data.pop(KB_PAGE_STATE, None)
                        context.user_data.pop(SHEET_VIEWS_KEY, None)
                        context.user_data.pop(TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY, None)
                        context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
                        await _render_trainer_overview(
                            q,
                            context,
                            actor_user_id,
                            message="Подопечный удалён.",
                        )
                        return
                    link = await get_active_trainer_link_for_trainee(target_user_id)
                    if not link:
                        await show_trainee_trainer_settings(q, context, target_user_id)
                        return
                    link_id = int(link[0])
                    await update_trainer_link_status(link_id, "removed")
                    context.user_data.pop(TRAINER_LABEL_INPUT_KEY, None)
                    context.user_data.pop(TRAINER_SETTINGS_MESSAGE_KEY, None)
                    kb = await build_settings_keyboard_for_user(
                        context, target_user_id, link_active=False
                    )
                    await show_screen(q, context, "Настройки:", kb, target_user_id)
                    return
                return
            profile = await _fetch_trainer_profile(actor_user_id)
            if not profile or not profile[0]:
                await q.answer("Недоступно.", show_alert=True)
                return
            if action == "trainee" and len(parts) >= 3:
                sub_action = parts[2]
                acting_id = context.user_data.get("acting_user_id")
                if (
                    sub_action == "label"
                    and len(parts) >= 5
                    and parts[3] == "set"
                ):
                    try:
                        trainee_id = int(parts[4])
                    except ValueError:
                        return
                    if acting_id is not None and acting_id != trainee_id:
                        await q.answer("Недоступно.", show_alert=True)
                        return
                    link = await get_trainer_link(actor_user_id, trainee_id)
                    if not link or str(link[1]) != "accepted":
                        await q.answer("Связь недоступна.", show_alert=True)
                        return
                    context.user_data["acting_user_id"] = trainee_id
                    context.user_data["acting_can_edit"] = bool(link[2])
                    context.user_data['_input_owner'] = trainee_id
                    link_id = int(link[0])
                    context.user_data[TRAINER_TRAINEE_LABEL_INPUT_KEY] = link_id
                    message = await show_screen(
                        q,
                        context,
                        "Отправь новое имя подопечного одним сообщением.",
                        InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "⬅️ Назад",
                                        callback_data="trainer:trainee_settings",
                                    )
                                ]
                            ]
                        ),
                        trainee_id,
                    )
                    if message:
                        context.user_data[
                            TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY
                        ] = (
                            getattr(message, "chat_id", None),
                            getattr(message, "message_id", None),
                        )
                    return
                if sub_action == "menu" and acting_id:
                    context.user_data.pop(TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY, None)
                    context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
                    await show_trainer_acting_menu(q, context, actor_user_id, acting_id)
                return
            if action == "trainee_settings":
                acting_id = context.user_data.get("acting_user_id")
                if not acting_id:
                    await q.answer("Недоступно.", show_alert=True)
                    return
                context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
                await show_trainer_manage_trainee(q, context, actor_user_id, acting_id)
                return
            if action == "list":
                if context.user_data.get("acting_user_id"):
                    context.user_data.pop("acting_user_id", None)
                    context.user_data.pop("acting_can_edit", None)
                    context.user_data.pop(RESOLVE_TARGET_USER_KEY, None)
                    context.user_data.pop(KB_PAGE_STATE, None)
                    context.user_data.pop(SHEET_VIEWS_KEY, None)
                    context.user_data.pop(TRAINER_SETTINGS_MESSAGE_KEY, None)
                    context.user_data.pop(TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY, None)
                    context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
                    context.user_data.pop("acting_label", None)
                if len(parts) == 2:
                    await _render_trainer_overview(q, context, actor_user_id)
                    return
                if len(parts) == 3 and parts[2] == "pending":
                    await _render_trainer_requests_view(q, context, actor_user_id)
                    return
                if len(parts) >= 4:
                    section = parts[2]
                    direction = parts[3]
                    pending_offset = context.user_data.get(
                        TRAINER_PENDING_OFFSET_KEY, 0
                    )
                    accepted_offset = context.user_data.get(
                        TRAINER_ACCEPTED_OFFSET_KEY, 0
                    )
                    if section == "pending":
                        if direction == "next":
                            pending_offset += TRAINER_LIST_LIMIT
                        elif direction == "prev":
                            pending_offset = max(0, pending_offset - TRAINER_LIST_LIMIT)
                        elif direction == "first":
                            pending_offset = 0
                        elif direction == "last" and len(parts) >= 5:
                            try:
                                pending_offset = max(0, int(parts[4]))
                            except ValueError:
                                pending_offset = 0
                        await _render_trainer_requests_view(
                            q,
                            context,
                            actor_user_id,
                            pending_offset=pending_offset,
                        )
                        return
                    if section == "accepted":
                        if direction == "next":
                            accepted_offset += TRAINER_LIST_LIMIT
                        elif direction == "prev":
                            accepted_offset = max(
                                0, accepted_offset - TRAINER_LIST_LIMIT
                            )
                        elif direction == "first":
                            accepted_offset = 0
                        elif direction == "last":
                            total = await count_trainer_trainees(actor_user_id)
                            accepted_offset = max(
                                0,
                                math.floor(max(total - 1, 0) / TRAINER_LIST_LIMIT)
                                * TRAINER_LIST_LIMIT,
                            )
                        await _render_trainer_overview(
                            q,
                            context,
                            actor_user_id,
                            pending_offset=pending_offset,
                            accepted_offset=accepted_offset,
                        )
                        return
                return
            if action == "requests" and len(parts) >= 3:
                desired_state = parts[2]
                enable = desired_state == "on"
                profile = await _fetch_trainer_profile(actor_user_id)
                if not profile or not int(profile[0]):
                    await q.answer("Сначала включите режим тренера.", show_alert=True)
                    return
                if enable:
                    pending_count = await count_trainer_requests(actor_user_id)
                    if pending_count and (len(parts) < 4):
                        text = (
                            "Включить прием заявок?\n"
                            f"У вас {pending_count} ожидающих заявок. Очистить список перед включением?"
                        )
                        kb = InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "✅ Да, очистить",
                                        callback_data="trainer:requests:on:clear",
                                    ),
                                    InlineKeyboardButton(
                                        "❌ Нет, оставить",
                                        callback_data="trainer:requests:on:keep",
                                    ),
                                ],
                                [
                                    InlineKeyboardButton(
                                        BACK_BTN, callback_data="trainer:list"
                                    )
                                ],
                            ]
                        )
                        await show_screen(q, context, text, kb, actor_user_id)
                        return
                    if len(parts) >= 4 and parts[3] == "clear":
                        await clear_trainer_requests(actor_user_id)
                    await set_trainer_accepting_requests(actor_user_id, True)
                    message = "Прием заявок включен"
                    if len(parts) >= 4 and parts[3] == "clear":
                        message = "Прием заявок включен, список очищен"
                    context.user_data.pop(TRAINER_PENDING_OFFSET_KEY, None)
                    await _render_trainer_requests_view(
                        q, context, actor_user_id, message=message
                    )
                    await q.answer(message)
                    return
                context.user_data.pop(TRAINER_REQUESTS_VIEW_KEY, None)
                await set_trainer_accepting_requests(actor_user_id, False)
                message = "Прием заявок отключен"
                await _render_trainer_overview(
                    q, context, actor_user_id, message=message
                )
                await q.answer(message)
                return
            if action == "req" and len(parts) >= 4:
                req_action = parts[2]
                try:
                    link_id = int(parts[3])
                except ValueError:
                    return
                link = await _get_trainer_link_by_id(link_id)
                if not link or int(link[1]) != actor_user_id:
                    await _render_trainer_overview(
                        q, context, actor_user_id, message="Заявка не найдена."
                    )
                    return
                status = str(link[3]) if link[3] is not None else ""
                if status != "pending":
                    await _render_trainer_overview(
                        q, context, actor_user_id, message="Заявка уже обработана."
                    )
                    return
                trainee_user_id = int(link[2])
                if req_action == "accept":
                    limit = await get_trainer_max_trainees(actor_user_id)
                    if limit is not None:
                        accepted = await list_trainer_trainees(
                            actor_user_id, limit=limit + 1, offset=0
                        )
                        if len(accepted) >= limit:
                            await _render_trainer_overview(
                                q,
                                context,
                                actor_user_id,
                                message=(
                                    f"Лимит подопечных достигнут ({limit}). "
                                    "Оформите подписку, чтобы расширить лимит."
                                ),
                            )
                            return
                    reverse = await get_trainer_link(trainee_user_id, actor_user_id)
                    if reverse and str(reverse[1]) in {"accepted", "pending"}:
                        await _render_trainer_overview(
                            q,
                            context,
                            actor_user_id,
                            message="Нельзя: пользователь уже с вами в обратной связи",
                        )
                        return
                    try:
                        changed = await update_trainer_link_status(link_id, "accepted")
                    except ValueError as exc:
                        await _render_trainer_overview(q, context, actor_user_id, message=str(exc))
                        return
                    if not changed:
                        await _render_trainer_overview(q, context, actor_user_id, message="Заявка уже обработана")
                        return
                    if context.user_data.get(TRAINER_REQUESTS_VIEW_KEY):
                        await _render_trainer_requests_view(
                            q, context, actor_user_id, message="Заявка принята"
                        )
                    else:
                        await _render_trainer_overview(
                            q, context, actor_user_id, message="Заявка принята"
                        )
                    return
                if req_action == "decline":
                    if not await update_trainer_link_status(link_id, "rejected"):
                        await _render_trainer_overview(q, context, actor_user_id, message="Заявка уже обработана")
                        return
                    if context.user_data.get(TRAINER_REQUESTS_VIEW_KEY):
                        await _render_trainer_requests_view(
                            q, context, actor_user_id, message="Заявка отклонена"
                        )
                    else:
                        await _render_trainer_overview(
                            q, context, actor_user_id, message="Заявка отклонена"
                        )
                    return
                return
            if action == "view" and len(parts) >= 3:
                try:
                    trainee_id = int(parts[2])
                except ValueError:
                    return
                link = await get_trainer_link(actor_user_id, trainee_id)
                if not link or str(link[1]) != "accepted":
                    await q.answer("Нет доступа к профилю подопечного.", show_alert=True)
                    return
                context.user_data["acting_user_id"] = trainee_id
                context.user_data["acting_can_edit"] = bool(link[2])
                context.user_data.pop(RESOLVE_TARGET_USER_KEY, None)
                context.user_data.pop(KB_PAGE_STATE, None)
                context.user_data.pop(SHEET_VIEWS_KEY, None)
                context.user_data.pop(TRAINER_SETTINGS_MESSAGE_KEY, None)
                context.user_data.pop(TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY, None)
                context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
                await show_trainer_acting_menu(q, context, actor_user_id, trainee_id)
                return

        if data.startswith("ib:"):
            if not await require_edit_allowed(q, context):
                return
            parts = data.split(":")
            if len(parts) < 3:
                return
            info = context.user_data.get(INSTANT_BASE_KEY)
            if not info or info.get("source") != parts[1] or info.get('user_id', target_user_id) != target_user_id:
                context.user_data.pop(INSTANT_BASE_KEY, None)
                await q.answer()
                return
            if not data.endswith(f":at:{baseline_scope(target_user_id, info['day'], info['exercise_id'])}"):
                text, kb = instant_baseline_view(info)
                await show_screen(q, context, text, kb, target_user_id)
                await q.answer("Кнопки обновлены для текущего упражнения.")
                return
            action = parts[2]
            values = info["values"]
            with_weight = info.get("with_weight", True)
            if action == "inc" and len(parts) >= 5:
                field = parts[3]
                delta = float(parts[4])
                if field == "sets":
                    values[0] = max(0, values[0] + int(delta))
                elif field == "reps":
                    values[1] = max(0, values[1] + int(delta))
                elif field == "sec":
                    values[2] = max(0, values[2] + int(delta))
                elif field == "kg" and with_weight:
                    values[3] = max(0.0, values[3] + delta)
                text, kb = instant_baseline_view(info)
                await show_screen(q, context, text, kb, target_user_id)
                return
            if action == "ready":
                await set_baseline(
                    target_user_id,
                    info["day"],
                    info["exercise_id"],
                    values[0],
                    values[1],
                    values[2],
                    values[3] if with_weight else 0.0,
                )
                await finish_instant_baseline(q, context, target_user_id, info)
                return
            if action in ("skip", "back"):
                await finish_instant_baseline(q, context, target_user_id, info)
                return
            return

        if data.startswith("wiz:"):
            await wizard_router(update, q, data, target_user_id, context)
            return

        if data.startswith("promo:channel:"):
            parts = data.split(":")
            action = parts[2] if len(parts) > 2 else ""
            if action == "subscribed":
                tg_user = getattr(q, "from_user", None)
                tg_user_id = getattr(tg_user, "id", None)
                if tg_user_id is None or not await _is_user_subscribed_to_channel(
                    context, tg_user_id
                ):
                    await q.answer(
                        "Не удалось подтвердить подписку. Проверь, подписан ли ты на канал, и попробуй ещё раз.",
                        show_alert=True,
                    )
                    return
                prefs = await load_ui_preferences(target_user_id)
                text, kb, prefs = await compose_main_menu(target_user_id, prefs)
                thank_you_text = "Спасибо ❤️\n\n" + text
                await show_screen(q, context, thank_you_text, kb, target_user_id)
                return
            if action in {"skip", "no"}:
                await q.answer("Спасибо! Напомним позже.")
                prefs = await load_ui_preferences(target_user_id)
                text, kb, prefs = await compose_main_menu(target_user_id, prefs)
                await show_screen(q, context, text, kb, target_user_id)
                return
            return

        if data == "menu:root":
            acting_id = context.user_data.get("acting_user_id")
            if acting_id is not None:
                try:
                    acting_id_int = int(acting_id)
                except (TypeError, ValueError):
                    context.user_data.pop("acting_user_id", None)
                    context.user_data.pop("acting_can_edit", None)
                    context.user_data.pop(RESOLVE_TARGET_USER_KEY, None)
                    context.user_data.pop("acting_label", None)
                else:
                    if (
                        acting_id_int == target_user_id
                        and actor_user_id != target_user_id
                    ):
                        await show_trainer_acting_menu(
                            q, context, actor_user_id, acting_id_int
                        )
                        return
            prefs = await load_ui_preferences(target_user_id)
            text, kb, prefs = await compose_main_menu(target_user_id, prefs)
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data in ("menu:library", "lib:root"):
            context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
            if actor_user_id == target_user_id or bool(context.user_data.get('acting_can_edit')):
                await ensure_library_history(target_user_id)
            groups = await list_library_groups(target_user_id)
            custom = await get_custom_groups(target_user_id, context)
            prefs = await load_ui_preferences(target_user_id)
            text = "Статистика упражнений:"
            kb = library_menu_kb(groups, custom, context=context)
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data == "menu:metrics":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            prefs = await load_ui_preferences(target_user_id)
            text, kb = await build_measurements_view(target_user_id, context)
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data == "menu:settings":
            st = context.user_data.get(SHARE_RESULTS_STATE_KEY)
            if st and st.get(SHARE_RESULTS_PRIMARY_MSG_ID_KEY):
                try:
                    await context.bot.delete_message(
                        chat_id=q.message.chat_id,
                        message_id=st[SHARE_RESULTS_PRIMARY_MSG_ID_KEY],
                    )
                except BadRequest:
                    pass
            context.user_data.pop(SHARE_RESULTS_STATE_KEY, None)
            settings = await fetch_user_settings(target_user_id)
            n = settings[1] if settings else 0
            tz = await get_user_timezone(target_user_id)
            rems = await list_user_reminders(target_user_id)
            tz_label = get_timezone_label(tz)
            if rems:
                parts = [
                    f"{dict(WEEKDAYS)[d]} {h:02d}:{m:02d}"
                    for _day, d, h, m in rems
                ]
                rem_text = ", ".join(parts)
            else:
                rem_text = t("NOT_SET")
            prefs = await load_ui_preferences(target_user_id)
            text_lines = [
                "Настройки:",
                "",
                "Выбирай пункт ниже, чтобы обновить дневник под себя.",
                "",
                "────────",
                "",
                "✏️ Переименовать дни — поменять названия тренировочных дней.",
                "",
                "🔁 Изменить день — переключи тип тренировки (силовая, гири, кроссфит, воркаут) и открой подходящие упражнения. После переключения можно добавлять упражнения из любых групп.",
                "",
                f"📅 Количество тренировок — сейчас {n}. Укажи, сколько раз планируешь тренироваться.",
                "",
                "🗑 Удаление моих групп мышц — удаляй созданные группы мышц. Все упражнения из удалённых групп исчезнут из расписания и библиотеки.",
                "",
                f"⏰ Уведомления — {tz_label}, {rem_text}. Настрой время напоминаний.",
                "",
                "🧑‍🏫 Тренер / подопечный — подключи тренера по коду или веди своих подопечных.",
                "",
                "💳 Подписка — поддержка проекта и расширенный функционал (ИИ-функции, своя команда, больше подопечных и систем).",
                "",
                "✅ Убрать галочки — сбросить отметки выполненных дней, не затрагивая записанные подходы.",
                "",
                "📤 Поделиться результатом — сгенерировать короткий текст с вашим прогрессом, чтобы отправить его друзьям.",
                "",
                "🎁 Реферальная программа — создайте свою ссылку, приглашайте людей и смотрите оплаты по вашей рекомендации.",
            ]
            if update.effective_user and update.effective_user.id in ADMIN_IDS:
                text_lines.extend(
                    [
                        "",
                        "🛠 Управление рефералками — админ-панель со списком и поиском всех рефералов.",
                    ]
                )
            active_sub = await get_active_subscription(target_user_id)
            if active_sub and active_sub.get("expires_at"):
                zone = resolve_user_zone(tz)
                expires_local = active_sub["expires_at"].astimezone(zone)
                support_line = (
                    "Спасибо за поддержку! Подписка активна до "
                    f"{expires_local.strftime('%d.%m.%Y')}."
                )
            else:
                support_line = "Подписка остаётся добровольной: бот бесплатный для всех."
            text_lines.extend(["", support_line])
            text = "\n".join(text_lines)
            kb = await build_settings_keyboard_for_user(context, target_user_id)
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data == "settings:share_results":
            state = context.user_data.get(SHARE_RESULTS_STATE_KEY) or {}
            primary_msg_id = state.get(SHARE_RESULTS_PRIMARY_MSG_ID_KEY)
            if primary_msg_id:
                try:
                    await context.bot.delete_message(
                        chat_id=q.message.chat_id,
                        message_id=primary_msg_id,
                    )
                except TelegramError as e:
                    message_text = (e.message or "").lower()
                    if "message to delete not found" not in message_text:
                        raise

            view = await build_share_results_view(target_user_id)
            primary = await context.bot.send_message(
                chat_id=q.message.chat_id,
                text=view.text_html,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
            )
            context.user_data[SHARE_RESULTS_STATE_KEY] = {
                "all_exercises": list(view.all_exercises),
                SHARE_RESULTS_PRIMARY_MSG_ID_KEY: primary.message_id,
            }
            enable_shuffle = len(view.all_exercises) > SHARE_RESULTS_EXERCISE_LIMIT
            kb = build_share_results_keyboard(enable_shuffle=enable_shuffle)
            helper_text = (
                "Сверху — ваш текст для пересылки/копирования.\n"
                "• Нажмите и удерживайте верхнее сообщение, затем «Переслать» или «Копировать».\n\n"
                "Можно сменить набор упражнений кнопкой ниже."
            )
            prefs = await load_ui_preferences(target_user_id)
            prepared_text, prepared_markup = prepare_ui_output(
                helper_text,
                kb,
                prefs,
            )
            await send_main_message_fresh(
                context.bot,
                q.message.chat_id,
                prepared_text,
                reply_markup=prepared_markup,
            )
            await q.answer()
            return

        if data == "settings:share_results:shuffle":
            state = context.user_data.get(SHARE_RESULTS_STATE_KEY) or {}
            stored_all = state.get("all_exercises")
            if stored_all:
                sample = _select_share_exercises(stored_all, randomize=True)
                view = await build_share_results_view(
                    target_user_id,
                    all_exercises=stored_all,
                    sample=sample,
                )
            else:
                view = await build_share_results_view(target_user_id)

            primary_msg_id = state.get(SHARE_RESULTS_PRIMARY_MSG_ID_KEY)
            if primary_msg_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=q.message.chat_id,
                        message_id=primary_msg_id,
                        text=view.text_html,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=False,
                    )
                except BadRequest:
                    new_primary = await context.bot.send_message(
                        chat_id=q.message.chat_id,
                        text=view.text_html,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=False,
                    )
                    primary_msg_id = new_primary.message_id
            else:
                new_primary = await context.bot.send_message(
                    chat_id=q.message.chat_id,
                    text=view.text_html,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False,
                )
                primary_msg_id = new_primary.message_id

            context.user_data[SHARE_RESULTS_STATE_KEY] = {
                "all_exercises": list(view.all_exercises),
                SHARE_RESULTS_PRIMARY_MSG_ID_KEY: primary_msg_id,
            }
            await q.answer("Обновил упражнения")
            return

        if data == "settings:referral":
            text, kb = await build_referral_screen(target_user_id)
            await show_screen(q, context, text, kb, target_user_id, parse_mode=ParseMode.HTML)
            return

        if data == "settings:referral:info":
            text, kb = build_referral_info_screen()
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data == "settings:referral:create":
            context.user_data[REFERRAL_NAME_INPUT_KEY] = {
                "chat_id": q.message.chat_id,
                "message_id": q.message.message_id,
                "target_user_id": target_user_id,
            }
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(BACK_BTN, callback_data="settings:referral")]]
            )
            await show_screen(
                q,
                context,
                "Напиши имя/псевдоним для реферальной ссылки.",
                kb,
                target_user_id,
            )
            return

        if data == "settings:refadmin":
            if update.effective_user.id not in ADMIN_IDS:
                await q.answer("Доступно только администратору.", show_alert=True)
                return
            context.user_data.pop(REFERRAL_ADMIN_SEARCH_KEY, None)
            context.user_data["refadmin_page"] = 0
            context.user_data["refadmin_query"] = None
            text, kb = await build_referral_admin_screen(page=0)
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data == "settings:gift_code" or data == "settings:gift_code:activate":
            is_admin = bool(update.effective_user and update.effective_user.id in ADMIN_IDS)
            context.user_data[GIFT_CODE_INPUT_KEY] = {
                "chat_id": q.message.chat_id,
                "message_id": q.message.message_id,
                "target_user_id": target_user_id,
            }
            rows = []
            if is_admin:
                rows.append([InlineKeyboardButton("➕ Создать код", callback_data="settings:gift_code:create")])
                rows.append([InlineKeyboardButton("📊 Коды", callback_data="settings:gift_code:codes")])
            rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")])
            await show_screen(
                q,
                context,
                "🎟 Активация подарочного кода\n\n"
                "Отправь код одним сообщением.\n"
                "Пример: <code>GIFT-ABCD2345</code>\n\n"
                "Ниже просто вставь код — я проверю и активирую подписку.",
                InlineKeyboardMarkup(rows),
                target_user_id,
                parse_mode=ParseMode.HTML,
            )
            return

        if data == "settings:gift_code:create":
            if update.effective_user.id not in ADMIN_IDS:
                await q.answer("Только для админа", show_alert=True)
                return
            context.user_data[GIFT_CODE_DAYS_INPUT_KEY] = {
                "chat_id": q.message.chat_id,
                "message_id": q.message.message_id,
                "target_user_id": target_user_id,
            }
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(BACK_BTN, callback_data="settings:gift_code")]]
            )
            await show_screen(
                q,
                context,
                "Введи количеством дней одним сообщением.\n\nНапример: 30",
                kb,
                target_user_id,
            )
            return

        if data.startswith("settings:gift_code:new:"):
            if update.effective_user.id not in ADMIN_IDS:
                await q.answer("Только для админа", show_alert=True)
                return
            try:
                days = max(1, int(data.rsplit(":", 1)[-1]))
            except ValueError:
                await q.answer("Некорректное количество дней", show_alert=True)
                return
            code = f"GIFT-{''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))}"
            await create_gift_code(code, days, update.effective_user.id)
            await q.answer("Код создан")
            text = (
                "✅ Подарочный код создан\n\n"
                f"Код: <code>{code}</code>\n"
                f"Срок: {days} дн.\n\n"
                "Передай его пользователю для активации в подписке."
            )
            kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("➕ Создать код", callback_data="settings:gift_code:create")],
                    [InlineKeyboardButton("📊 Коды", callback_data="settings:gift_code:codes")],
                    [InlineKeyboardButton(BACK_BTN, callback_data="settings:gift_code")],
                ]
            )
            await show_screen(q, context, text, kb, target_user_id, parse_mode=ParseMode.HTML)
            return

        if data.startswith("settings:refadmin:page:"):
            if update.effective_user.id not in ADMIN_IDS:
                await q.answer("Доступно только администратору.", show_alert=True)
                return
            try:
                page = max(0, int(data.rsplit(":", 1)[-1]))
            except ValueError:
                page = 0
            context.user_data["refadmin_page"] = page
            query = context.user_data.get("refadmin_query")
            text, kb = await build_referral_admin_screen(page=page, search=query)
            await show_screen(q, context, text, kb, target_user_id)
            return
        if data == "settings:gift_code:codes":
            if update.effective_user.id not in ADMIN_IDS:
                await q.answer("Только для админа", show_alert=True)
                return
            stats = await gift_code_stats()
            text = (
                "📊 Статистика подарочных кодов\n\n"
                f"Всего создано: {stats['total']}\n"
                f"Активные (не использованы): {stats['active']}\n"
                f"Использованные: {stats['used']}"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🟢 Неиспользованные", callback_data="settings:gift_code:active:0")],
                [InlineKeyboardButton(BACK_BTN, callback_data="settings:gift_code")],
            ])
            await show_screen(q, context, text, kb, target_user_id)
            return
        if data.startswith("settings:gift_code:active:"):
            if update.effective_user.id not in ADMIN_IDS:
                await q.answer("Только для админа", show_alert=True)
                return
            try:
                page = max(0, int(data.rsplit(":", 1)[-1]))
            except ValueError:
                page = 0
            limit = 8
            items = await list_active_gift_codes(limit=limit, offset=page * limit)
            lines = ["🟢 Неиспользованные коды", "", "Нажми на код ниже, чтобы быстро скопировать:", ""]
            if not items:
                lines.append("Список пуст.")
            else:
                for it in items:
                    lines.append(f"<code>{it['code']}</code>")
                    lines.append(f"Срок: {it['days']} дн.")
                    lines.append("")
            rows = []
            for it in items[:8]:
                rows.append([InlineKeyboardButton(f"🗑 Удалить {it['code']}", callback_data=f"settings:gift_code:del:{it['id']}:{page}")])
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("◀️", callback_data=f"settings:gift_code:active:{page-1}"))
            if len(items) == limit:
                nav.append(InlineKeyboardButton("▶️", callback_data=f"settings:gift_code:active:{page+1}"))
            if nav:
                rows.append(nav)
            rows.append([InlineKeyboardButton(BACK_BTN, callback_data="settings:gift_code:codes")])
            await show_screen(
                q,
                context,
                "\n".join(lines).rstrip(),
                InlineKeyboardMarkup(rows),
                target_user_id,
                parse_mode=ParseMode.HTML,
            )
            return
        if data.startswith("settings:gift_code:del:"):
            if update.effective_user.id not in ADMIN_IDS:
                await q.answer("Только для админа", show_alert=True)
                return
            parts = data.split(":")
            if len(parts) != 5:
                await q.answer("Некорректные данные")
                return
            try:
                code_id = int(parts[3])
                page = max(0, int(parts[4]))
            except ValueError:
                await q.answer("Некорректные данные")
                return
            deleted = await delete_gift_code(code_id)
            await q.answer("Код удалён" if deleted else "Код уже использован или не найден")
            items = await list_active_gift_codes(limit=8, offset=page * 8)
            if not items and page > 0:
                page -= 1
                items = await list_active_gift_codes(limit=8, offset=page * 8)
            lines = ["🟢 Неиспользованные коды", "", "Нажми на код ниже, чтобы быстро скопировать:", ""]
            if not items:
                lines.append("Список пуст.")
            else:
                for it in items:
                    lines.append(f"<code>{it['code']}</code>")
                    lines.append(f"Срок: {it['days']} дн.")
                    lines.append("")
            rows = [[InlineKeyboardButton(f"🗑 Удалить {it['code']}", callback_data=f"settings:gift_code:del:{it['id']}:{page}")] for it in items]
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("◀️", callback_data=f"settings:gift_code:active:{page-1}"))
            if len(items) == 8:
                nav.append(InlineKeyboardButton("▶️", callback_data=f"settings:gift_code:active:{page+1}"))
            if nav:
                rows.append(nav)
            rows.append([InlineKeyboardButton(BACK_BTN, callback_data="settings:gift_code:codes")])
            await show_screen(
                q,
                context,
                "\n".join(lines).rstrip(),
                InlineKeyboardMarkup(rows),
                target_user_id,
                parse_mode=ParseMode.HTML,
            )
            return

        if data == "settings:refadmin:search":
            if update.effective_user.id not in ADMIN_IDS:
                await q.answer("Доступно только администратору.", show_alert=True)
                return
            context.user_data[REFERRAL_ADMIN_SEARCH_KEY] = {
                "chat_id": q.message.chat_id,
                "message_id": q.message.message_id,
            }
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(BACK_BTN, callback_data="settings:refadmin")]]
            )
            await show_screen(
                q,
                context,
                "Введите имя/часть имени для поиска реферала.",
                kb,
                target_user_id,
            )
            return

        if data.startswith("settings:refadmin:user:"):
            if update.effective_user.id not in ADMIN_IDS:
                await q.answer("Доступно только администратору.", show_alert=True)
                return
            try:
                ref_user_id = int(data.rsplit(":", 1)[-1])
            except ValueError:
                await q.answer()
                return
            profile = await get_referral_profile(ref_user_id)
            if not profile:
                await q.answer("Профиль не найден.", show_alert=True)
                return
            stats = await get_referral_stats(ref_user_id)
            payout_text, _rate, _payout_rub, _payout_stars, _percent = _format_referral_payout(stats)
            text = (
                f"Реферал: {profile['display_name']}\n"
                f"Slug: {profile['slug']}\n\n"
                f"👥 Пришло пользователей: всего {stats['invited_total']}, за месяц {stats['invited_month']}\n"
                f"💳 Оплатили: всего {stats['paid_users_total']}, за месяц {stats['paid_users_month']}\n"
                f"📆 Куплено дней подписки: всего {stats['paid_days_total']}, за месяц {stats['paid_days_month']}\n\n"
                f"{payout_text}"
            )
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Открыть ссылку",
                            url=_build_referral_link(profile["slug"]),
                        )
                    ],
                    [InlineKeyboardButton(BACK_BTN, callback_data="settings:refadmin")],
                ]
            )
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data.startswith("measure:"):
            read_only_measure_prefixes = {"measure:back", "measure:toggle", "measure:history"}
            if not any(
                data == prefix or data.startswith(f"{prefix}:")
                for prefix in read_only_measure_prefixes
            ):
                if not await require_edit_allowed(q, context):
                    return
        if data == "measure:back":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_EXISTING_KEY, None)
            context.user_data.pop(MEASUREMENT_CATEGORY_BACK_KEY, None)
            text, kb = await build_measurements_view(target_user_id, context)
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data == "measure:toggle":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_EXISTING_KEY, None)
            current = context.user_data.get(MEASUREMENTS_SHOW_ALL_KEY, False)
            context.user_data[MEASUREMENTS_SHOW_ALL_KEY] = not current
            text, kb = await build_measurements_view(target_user_id, context)
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data == "measure:history":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_EXISTING_KEY, None)
            text, kb = await build_measurements_history_view(target_user_id, context)
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data == "measure:manage":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_EXISTING_KEY, None)
            context.user_data.pop(MEASUREMENT_CUSTOM_KEY, None)
            context.user_data.pop(MEASUREMENT_CATEGORY_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_CATEGORY_BACK_KEY, None)
            await show_measurements_manage_overview(
                q,
                context,
                target_user_id,
                category_back_target="measure:manage",
            )
            return

        if data == "measure:add":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_EXISTING_KEY, None)
            context.user_data.pop(MEASUREMENT_CUSTOM_KEY, None)
            context.user_data.pop(MEASUREMENT_CATEGORY_INPUT_KEY, None)
            await show_measurements_manage_overview(
                q,
                context,
                target_user_id,
                category_back_target="measure:add",
            )
            return

        if data == "measure:manage:addcat":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_EXISTING_KEY, None)
            context.user_data.pop(MEASUREMENT_CUSTOM_KEY, None)
            context.user_data.pop(MEASUREMENT_CATEGORY_INPUT_KEY, None)
            context.user_data[MEASUREMENT_CATEGORY_BACK_KEY] = "measure:manage"
            context.user_data[MEASUREMENT_CATEGORY_INPUT_KEY] = {
                "chat_id": q.message.chat_id,
                "message_id": q.message.message_id,
                "back": "measure:manage",
                "mode": "add",
                "target_user_id": target_user_id,
            }
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(BACK_BTN, callback_data="measure:manage")]]
            )
            await show_screen(
                q,
                context,
                "Как назвать категорию? Напиши короткое и понятное название.",
                kb,
                target_user_id,
            )
            return

        if data == "measure:manage:delete":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_CATEGORY_INPUT_KEY, None)
            context.user_data[MEASUREMENT_CATEGORY_BACK_KEY] = "measure:manage"
            custom_items = await load_custom_measurements(target_user_id, context)
            user_categories = await load_measurement_categories(target_user_id, context)
            categories = [
                (cat["code"], format_category_label(cat)) for cat in user_categories
            ]
            metrics = [(item["code"], item["name"]) for item in custom_items]
            if not categories and not metrics:
                await q.answer("Пока нечего удалять.", show_alert=True)
                return
            kb = measurements_remove_kb(categories, metrics, context=context)
            await show_screen(
                q,
                context,
                "Что удалить? Выбери категорию или замер.",
                kb,
                target_user_id,
            )
            return

        if data.startswith("measure:manage:delete:cat:"):
            parts = data.split(":")
            if len(parts) < 5:
                await q.answer()
                return
            code = parts[4]
            if parts[-1] != "ok":
                categories = get_cached_measurement_categories(context)
                cat = next((c for c in categories if c.get("code") == code), None)
                if not cat:
                    categories = await load_measurement_categories(target_user_id, context)
                    cat = next((c for c in categories if c.get("code") == code), None)
                title = (cat or {}).get("name") or code
                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "✅ Удалить",
                                callback_data=f"measure:manage:delete:cat:{code}:ok",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                BACK_BTN, callback_data="measure:manage:delete"
                            )
                        ],
                    ]
                )
                await show_screen(
                    q,
                    context,
                    f"Удалить категорию «{title}»? Все замеры из неё будут удалены.",
                    kb,
                    target_user_id,
                )
                return
            removed = await delete_measurement_category_with_contents(
                target_user_id, code, context
            )
            if not removed:
                await q.answer("Не удалось удалить категорию.", show_alert=True)
                return
            await q.answer("Категория удалена.")
            custom_items = await load_custom_measurements(target_user_id, context)
            user_categories = await load_measurement_categories(target_user_id, context)
            categories = [
                (cat["code"], format_category_label(cat)) for cat in user_categories
            ]
            metrics = [(item["code"], item["name"]) for item in custom_items]
            if categories or metrics:
                kb = measurements_remove_kb(categories, metrics, context=context)
                await show_screen(
                    q,
                    context,
                    "Что удалить? Выбери категорию или замер.",
                    kb,
                    target_user_id,
                )
            else:
                await show_measurements_manage_overview(
                    q,
                    context,
                    target_user_id,
                    category_back_target="measure:manage",
                )
            return

        if data.startswith("measure:manage:delete:item:"):
            parts = data.split(":")
            if len(parts) < 5:
                await q.answer()
                return
            code = parts[4]
            if parts[-1] != "ok":
                custom_items = get_cached_custom_measurements(context)
                item = next((c for c in custom_items if c.get("code") == code), None)
                if not item:
                    custom_items = await load_custom_measurements(target_user_id, context)
                    item = next(
                        (c for c in custom_items if c.get("code") == code), None
                    )
                if not item:
                    await q.answer("Замер не найден.", show_alert=True)
                    return
                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "✅ Удалить",
                                callback_data=f"measure:manage:delete:item:{code}:ok",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                BACK_BTN, callback_data="measure:manage:delete"
                            )
                        ],
                    ]
                )
                await show_screen(
                    q,
                    context,
                    f"Удалить замер «{item['name']}»? Все сохранённые значения будут стерты.",
                    kb,
                    target_user_id,
                )
                return
            removed = await delete_custom_measurement(target_user_id, code)
            if not removed:
                await q.answer("Не удалось удалить замер.", show_alert=True)
                return
            await q.answer("Замер удалён.")
            custom_items = await load_custom_measurements(target_user_id, context)
            user_categories = await load_measurement_categories(target_user_id, context)
            categories = [
                (cat["code"], format_category_label(cat)) for cat in user_categories
            ]
            metrics = [(item["code"], item["name"]) for item in custom_items]
            if categories or metrics:
                kb = measurements_remove_kb(categories, metrics, context=context)
                await show_screen(
                    q,
                    context,
                    "Что удалить? Выбери категорию или замер.",
                    kb,
                    target_user_id,
                )
            else:
                await show_measurements_manage_overview(
                    q,
                    context,
                    target_user_id,
                    category_back_target="measure:manage",
                )
            return

        if data.startswith("measure:add:cat:"):
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_EXISTING_KEY, None)
            context.user_data.pop(MEASUREMENT_CATEGORY_INPUT_KEY, None)
            parts = data.split(":")
            category = parts[3]
            custom_items = await load_custom_measurements(target_user_id, context)
            metrics = [
                (item["code"], item["name"])
                for item in get_measurement_items(category)
                if not item.get("derived")
            ]
            metrics.extend(
                (item["code"], item["name"])
                for item in custom_items
                if item.get("category") == category
            )
            if not metrics:
                # Покажем кнопку для создания собственного замера в этой категории
                kb = measurements_metric_kb(
                    'add',
                    category,
                    [],
                    include_custom_button=True,
                    context=context,
                )
                await show_screen(
                    q,
                    context,
                    "Собственных замеров пока нет. Добавим?",
                    kb,
                    target_user_id,
                )
                return
            await show_screen(
                q,
                context,
                'Выбери показатель:',
                measurements_metric_kb(
                    'add', category, metrics, include_custom_button=True, context=context
                ),
                target_user_id,
            )
            return

        if data == "measure:add:category":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_CATEGORY_INPUT_KEY, None)
            custom_state = context.user_data.get(MEASUREMENT_CUSTOM_KEY)
            mode = "add"
            back_callback = context.user_data.get(
                MEASUREMENT_CATEGORY_BACK_KEY, "measure:add"
            )
            pending_name = None
            if custom_state and custom_state.get("step") == "category":
                mode = "customplace"
                back_callback = custom_state.get("back", "measure:add")
                pending_name = custom_state.get("pending_name")
            context.user_data[MEASUREMENT_CATEGORY_INPUT_KEY] = {
                "chat_id": q.message.chat_id,
                "message_id": q.message.message_id,
                "back": back_callback,
                "mode": mode,
                "pending_name": pending_name,
                "target_user_id": target_user_id,
            }
            context.user_data[MEASUREMENT_CATEGORY_BACK_KEY] = back_callback
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(BACK_BTN, callback_data=back_callback)]]
            )
            await show_screen(
                q,
                context,
                "Как назвать категорию? Напиши короткое и понятное название.",
                kb,
                target_user_id,
            )
            return

        if data.startswith("measure:add:item:"):
            parts = data.split(":")
            category = parts[3]
            code = parts[4]
            item = await get_owned_measurement_item(target_user_id, code)
            if not item or item.get("derived"):
                await q.answer()
                return
            context.user_data[MEASUREMENT_INPUT_KEY] = {
                "action": "add",
                "metric": code,
                "chat_id": q.message.chat_id,
                "message_id": q.message.message_id,
                "category": category,
                "target_user_id": target_user_id,
            }
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("BACK"), callback_data=f"measure:add:cat:{category}")]]
            )
            await show_screen(q, context, item['prompt'], kb, target_user_id)
            return

        if data.startswith("measure:add:custom:new"):
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_EXISTING_KEY, None)
            parts = data.split(":")
            category = parts[4] if len(parts) >= 5 else None
            back_target = f"measure:add:cat:{category}" if category else "measure:add"
            context.user_data[MEASUREMENT_CUSTOM_KEY] = {
                "chat_id": q.message.chat_id,
                "message_id": q.message.message_id,
                "back": back_target,
                "origin": category,
                "step": "name",
                "target_user_id": target_user_id,
            }
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(BACK_BTN, callback_data=back_target)]]
            )
            await show_screen(
                q,
                context,
                "Как назвать замер? Напиши понятное название, например «Гибкость» или «Шагов в день».",
                kb,
                target_user_id,
            )
            return

        if data.startswith("measure:add:custom:cat:"):
            parts = data.split(":")
            if len(parts) < 5:
                await q.answer()
                return
            category_code = parts[4]
            custom_state = context.user_data.get(MEASUREMENT_CUSTOM_KEY)
            if not custom_state or custom_state.get("step") != "category":
                await q.answer()
                return
            name = custom_state.get("pending_name")
            chat_id = custom_state.get("chat_id")
            msg_id = custom_state.get("message_id")
            back_callback = custom_state.get("back", "measure:add")
            if not name or not chat_id or not msg_id:
                context.user_data.pop(MEASUREMENT_CUSTOM_KEY, None)
                await q.answer()
                return
            u = q.from_user
            await get_or_create_user(u.id, u.username)
            await prompt_custom_measurement_value(
                context,
                target_user_id,
                chat_id,
                msg_id,
                back_callback,
                name,
                category_code,
            )
            return

        if data == "measure:edit":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_CUSTOM_KEY, None)
            await show_measure_edit_menu(q, context, target_user_id)
            return

        if data == "measure:edit:customrm":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            context.user_data.pop(MEASUREMENT_CUSTOM_KEY, None)
            await show_custom_measurements_delete_menu(q, context, target_user_id)
            return

        if data.startswith("measure:edit:cat:"):
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            parts = data.split(":")
            category = parts[3]
            stored = context.user_data.get(MEASUREMENT_EXISTING_KEY)
            metrics = None
            if isinstance(stored, dict):
                metrics = stored.get(category)
            if metrics is None:
                await load_custom_measurements(target_user_id, context)
                rows = await list_measurement_metrics(target_user_id)
                metrics = []
                for code, _ in rows:
                    item = await get_owned_measurement_item(target_user_id, code)
                    if (
                        item
                        and not item.get("derived")
                        and item.get("category") == category
                    ):
                        metrics.append((code, item["name"]))
                if metrics:
                    updated = dict(stored or {})
                    updated[category] = metrics
                    context.user_data[MEASUREMENT_EXISTING_KEY] = updated
            if not metrics:
                await q.answer("Нет данных для этой группы.", show_alert=True)
                return
            cached_categories = get_cached_measurement_categories(context)
            cached_custom = get_cached_custom_measurements(context)
            title = next(
                (
                    label
                    for code, label in measurement_categories_list(
                        cached_categories,
                        include_custom_fallback=True,
                        custom_items=cached_custom,
                    )
                    if code == category
                ),
                "Эта группа",
            )
            await show_screen(
                q,
                context,
                f"{title} — что изменить?",
        measurements_existing_kb(
            'edit', metrics, back_callback="measure:edit", context=context
        ),
                target_user_id,
            )
            return

        if data.startswith("measure:edit:metric:"):
            parts = data.split(":")
            code = parts[3]
            item = await get_owned_measurement_item(target_user_id, code)
            if not item:
                await q.answer()
                return
            history = await fetch_measurement_history(target_user_id, code, limit=1)
            prefix = ""
            if history:
                prefix = f"Текущее значение — {format_measurement_value(item, history[0])}.\n\n"
            context.user_data[MEASUREMENT_INPUT_KEY] = {
                "action": "edit",
                "metric": code,
                "chat_id": q.message.chat_id,
                "message_id": q.message.message_id,
                "target_user_id": target_user_id,
            }
            back_target = (
                f"measure:edit:cat:{item.get('category')}"
                if item.get("category")
                else "measure:edit"
            )
            rows = []
            if item.get("category") == MEASUREMENT_CUSTOM_CATEGORY["code"]:
                rows.append(
                    [
                        InlineKeyboardButton(
                            "Удалить замер",
                            callback_data=f"measure:edit:customdel:{code}",
                        )
                    ]
                )
                prefix = (
                    "Чтобы удалить замер вместе со всей историей, воспользуйся кнопкой ниже.\n\n"
                    + prefix
                )
            rows.append([InlineKeyboardButton(t("BACK"), callback_data=back_target)])
            kb = InlineKeyboardMarkup(rows)
            await show_screen(q, context, prefix + item['prompt'], kb, target_user_id)
            return

        if data.startswith("measure:edit:customdel:"):
            parts = data.split(":")
            if len(parts) >= 4 and parts[-1] != "ok":
                code = parts[3]
                item = await get_owned_measurement_item(target_user_id, code)
                if not item or item.get("category") != MEASUREMENT_CUSTOM_CATEGORY["code"]:
                    await q.answer()
                    return
                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "✅ Удалить",
                                callback_data=f"measure:edit:customdel:{code}:ok",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                BACK_BTN,
                                callback_data=f"measure:edit:metric:{code}",
                            )
                        ],
                    ]
                )
                await show_screen(
                    q,
                    context,
                    f"Удалить замер «{item['name']}»? Все сохранённые значения будут стерты.",
                    kb,
                    target_user_id,
                )
                return
            if len(parts) >= 5 and parts[-1] == "ok":
                code = parts[3]
                removed = await delete_custom_measurement(target_user_id, code)
                if not removed:
                    await q.answer("Не удалось удалить замер.", show_alert=True)
                    return
                await load_custom_measurements(target_user_id, context)
                context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
                await show_measure_edit_menu(q, context, target_user_id)
                return

        if data.startswith("measure:edit:customrm:"):
            parts = data.split(":")
            if len(parts) >= 4 and parts[-1] != "ok":
                code = parts[3]
                item = await get_owned_measurement_item(target_user_id, code)
                if not item or item.get("category") != MEASUREMENT_CUSTOM_CATEGORY["code"]:
                    await q.answer()
                    return
                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "✅ Удалить",
                                callback_data=f"measure:edit:customrm:{code}:ok",
                            )
                        ],
                        [InlineKeyboardButton(BACK_BTN, callback_data="measure:edit:customrm")],
                    ]
                )
                await show_screen(
                    q,
                    context,
                    f"Удалить замер «{item['name']}»? Все сохранённые значения будут стерты.",
                    kb,
                    target_user_id,
                )
                return
            if len(parts) >= 5 and parts[-1] == "ok":
                code = parts[3]
                removed = await delete_custom_measurement(target_user_id, code)
                if not removed:
                    await q.answer("Не удалось удалить замер.", show_alert=True)
                    return
                await load_custom_measurements(target_user_id, context)
                await show_custom_measurements_delete_menu(q, context, target_user_id)
                return

        if data == "measure:delete":
            context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
            await load_custom_measurements(target_user_id, context)
            rows = await list_measurement_metrics(target_user_id)
            metrics = []
            for code, _ in rows:
                item = await get_owned_measurement_item(target_user_id, code)
                if item:
                    metrics.append((code, item["name"]))
            if not metrics:
                await q.answer("Пока нечего удалять.", show_alert=True)
                return
            await show_screen(
                q,
                context,
                'Что удалить? Удалим только последнее значение.',
                measurements_existing_kb('delete', metrics, context=context),
                target_user_id,
            )
            return

        if data.startswith("measure:delete:metric:"):
            parts = data.split(":")
            code = parts[3]
            removed = await delete_last_measurement(target_user_id, code)
            if not removed:
                await q.answer("Нет данных для удаления.", show_alert=True)
                return
            text, kb = await build_measurements_view(target_user_id, context)
            await show_screen(q, context, text, kb, target_user_id)
            return

        parts = data.split(":")
        if parts[0] == "fill":
            if not await require_edit_allowed(q, context):
                return
            prefs = await load_ui_preferences(target_user_id)
            await handle_fill_callback(q, context, target_user_id, data, prefs)
            return
        if parts[0] == "lib":
            action = parts[1]
            mutating_lib_actions = {"groupdel", "manage", "delmenu", "del", "add"}
            if action in mutating_lib_actions:
                if not await require_edit_allowed(q, context):
                    return
            prefs = await load_ui_preferences(target_user_id)
            if action == "group":
                group = parts[2]
                items = await list_library_exercises(target_user_id, group)
                custom = await get_custom_groups(target_user_id, context)
                gname = MG_NAMES.get(group, custom.get(group, group))
                text = await render_library_group_text(
                    target_user_id, group, items, context, prefs=prefs
                )
                kb = library_group_kb(group, items, group_name=gname, context=context)
                await show_screen(q, context, text, kb, target_user_id)
                return
            if action == "groupdel":
                group = parts[2]
                if not group.startswith("u"):
                    await q.answer("Эту группу нельзя удалить.", show_alert=True)
                    return
                custom = await get_custom_groups(target_user_id, context)
                gname = MG_NAMES.get(group, custom.get(group, group))
                if len(parts) == 3:
                    text = (
                        f"Удалить группу «{gname}»?\n"
                        "Все упражнения из неё исчезнут из библиотеки и расписания."
                    )
                    kb = confirm_library_group_delete_kb(group, context=context)
                    await show_screen(q, context, text, kb, target_user_id)
                    return
                if len(parts) >= 4 and parts[3] == "ok":
                    removed = await remove_user_muscle_group(target_user_id, group)
                    if not removed:
                        await q.answer("Не удалось удалить группу.", show_alert=True)
                        items = await list_library_exercises(target_user_id, group)
                        text = await render_library_group_text(
                            target_user_id, group, items, context, prefs=prefs
                        )
                        kb = library_group_kb(group, items, group_name=gname, context=context)
                        await show_screen(q, context, text, kb, target_user_id)
                        return
                    custom.pop(group, None)
                    groups = await list_library_groups(target_user_id)
                    menu = library_menu_kb(groups, custom, context=context)
                    text = "Статистика упражнений:"
                    await q.answer("Группа удалена.")
                    await show_screen(q, context, text, menu, target_user_id)
                    return
                return
            if action == "manage":
                group = parts[2]
                items = await list_library_exercises(target_user_id, group)
                custom = await get_custom_groups(target_user_id, context)
                gname = MG_NAMES.get(group, custom.get(group, group))
                can_delete_group = group.startswith("u")
                sub = parts[3] if len(parts) > 3 else None
                if sub is None:
                    text = library_manage_text(
                        group,
                        custom,
                        has_items=bool(items),
                        can_delete_group=can_delete_group,
                        mode="manage",
                    )
                    kb = library_manage_kb(
                        group,
                        items,
                        can_delete_group=can_delete_group,
                        back_callback=f"lib:group:{group}",
                        add_callback=f"lib:manage:{group}:add",
                        group_name=gname if can_delete_group else None,
                        context=context,
                    )
                    await show_screen(q, context, text, kb, target_user_id)
                    return
                if sub == "del":
                    text = library_manage_text(
                        group,
                        custom,
                        has_items=bool(items),
                        can_delete_group=can_delete_group,
                        mode="delete",
                    )
                    kb = library_delete_kb(
                        group,
                        items,
                        back_callback=f"lib:group:{group}",
                        can_delete_group=can_delete_group,
                        group_name=gname if can_delete_group else None,
                        context=context,
                    )
                    await show_screen(q, context, text, kb, target_user_id)
                    return
                if sub == "del":
                    text = library_manage_text(
                        group,
                        custom,
                        has_items=bool(items),
                        can_delete_group=can_delete_group,
                        mode="delete",
                    )
                    kb = library_delete_kb(
                        group,
                        items,
                        back_callback=f"lib:group:{group}",
                        can_delete_group=can_delete_group,
                    )
                    await show_screen(q, context, text, kb, target_user_id)
                    return
                if sub == "add":
                    context.user_data["lib_return"] = ("group", group)
                    await show_library_add_exercises_view(q, target_user_id, group, context)
                    return
                return
            if action == "ex":
                group = parts[2]
                ue_id = int(parts[3])
                if not await _owns_active_exercise(target_user_id, 0, ue_id):
                    raise ValueError('stale_exercise')
                await show_library_exercise_view(q, target_user_id, group, ue_id, context)
                return
            if action == "delmenu":
                group = parts[2]
                items = await list_library_exercises(target_user_id, group)
                custom = await get_custom_groups(target_user_id, context)
                gname = MG_NAMES.get(group, custom.get(group, group))
                text = library_manage_text(
                    group,
                    custom,
                    has_items=bool(items),
                    can_delete_group=group.startswith("u"),
                    mode="delete",
                )
                kb = library_delete_kb(
                    group,
                    items,
                    back_callback=f"lib:group:{group}",
                    can_delete_group=group.startswith("u"),
                    group_name=gname if group.startswith("u") else None,
                )
                await show_screen(q, context, text, kb, target_user_id)
                return
            if action == "del":
                group = parts[2]
                ue_id = int(parts[3])
                await remove_user_exercise(target_user_id, 0, ue_id)
                items = await list_library_exercises(target_user_id, group)
                custom = await get_custom_groups(target_user_id, context)
                gname = MG_NAMES.get(group, custom.get(group, group))
                text = library_manage_text(
                    group,
                    custom,
                    has_items=bool(items),
                    can_delete_group=group.startswith("u"),
                    mode="delete",
                )
                kb = library_delete_kb(
                    group,
                    items,
                    back_callback=f"lib:group:{group}",
                    can_delete_group=group.startswith("u"),
                    group_name=gname if group.startswith("u") else None,
                )
                await show_screen(q, context, text, kb, target_user_id)
                return
            if action == "add":
                sub = parts[2]
                if sub == "start":
                    target = None
                    if len(parts) > 3:
                        target = ("group", parts[3])
                    context.user_data["lib_return"] = target
                    custom = await get_custom_groups(target_user_id, context)
                    kb = library_add_group_kb(custom, context=context)
                    await show_screen(q, context, "Выбери группу:", kb, target_user_id)
                    return
                if sub == "mg":
                    group = parts[3]
                    await show_library_add_exercises_view(q, target_user_id, group, context)
                    return
                if sub == "mg_back":
                    pending = context.user_data.get("awaiting_group_name")
                    if pending and pending[3] == "library":
                        context.user_data.pop("awaiting_group_name", None)
                    custom = await get_custom_groups(target_user_id, context)
                    kb = library_add_group_kb(custom, context=context)
                    await show_screen(q, context, "Выбери группу:", kb, target_user_id)
                    return
                if sub == "custom_group":
                    context.user_data["awaiting_group_name"] = (
                        0,
                        q.message.chat.id,
                        q.message.message_id,
                        "library",
                        target_user_id,
                    )
                    kb = InlineKeyboardMarkup(
                        [[InlineKeyboardButton(BACK_BTN, callback_data="lib:add:mg_back")]]
                    )
                    await show_screen(
                        q,
                        context,
                        "Как назвать новую группу мышц? Напиши название сообщением.",
                        kb,
                        target_user_id,
                    )
                    remember_message(q.message.chat.id, q.message.message_id)
                    return
                if sub == "page":
                    group = parts[3]
                    requested_page = int(parts[4]) if len(parts) > 4 else 0
                    await show_library_add_exercises_view(
                        q, target_user_id, group, context, page=requested_page
                    )
                    return
                if sub == "ex":
                    group = parts[3]
                    ex_id = int(parts[4])
                    await _require_available_catalog_exercise(target_user_id, ex_id)
                    await toggle_user_exercise(target_user_id, 0, ex_id)
                    requested_page = get_kb_page(context, "lib", group)
                    await show_library_add_exercises_view(
                        q, target_user_id, group, context, page=requested_page
                    )
                    return
                if sub == "custom":
                    group = parts[3]
                    context.user_data[LIBRARY_CUSTOM_KEY] = (
                        group,
                        q.message.chat.id,
                        q.message.message_id,
                        target_user_id,
                    )
                    kb = InlineKeyboardMarkup(
                        [[InlineKeyboardButton(t("BACK"), callback_data=f"lib:add:mg:{group}")]]
                    )
                    await show_screen(q, context, 'Как назвать упражнение?', kb, target_user_id)
                    remember_message(q.message.chat.id, q.message.message_id)
                    return
                if sub == "back":
                    context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
                    custom = await get_custom_groups(target_user_id, context)
                    target = context.user_data.get("lib_return")
                    if target and target[0] == "group":
                        group = target[1]
                        items = await list_library_exercises(target_user_id, group)
                        text = await render_library_group_text(
                            target_user_id, group, items, context, prefs=prefs
                        )
                        gname = MG_NAMES.get(group, custom.get(group, group))
                        kb = library_group_kb(group, items, group_name=gname, context=context)
                        await show_screen(q, context, text, kb, target_user_id)
                    else:
                        kb = library_add_group_kb(custom, context=context)
                        await show_screen(q, context, "Выбери группу:", kb, target_user_id)
                    return
                if sub == "done":
                    context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
                    target = context.user_data.pop("lib_return", None)
                    if target and target[0] == "group":
                        group = target[1]
                        items = await list_library_exercises(target_user_id, group)
                        text = await render_library_group_text(
                            target_user_id, group, items, context, prefs=prefs
                        )
                        custom = await get_custom_groups(target_user_id, context)
                        gname = MG_NAMES.get(group, custom.get(group, group))
                        kb = library_group_kb(group, items, group_name=gname, context=context)
                        await show_screen(q, context, text, kb, target_user_id)
                    else:
                        groups = await list_library_groups(target_user_id)
                        custom = await get_custom_groups(target_user_id, context)
                        kb = library_menu_kb(groups, custom, context=context)
                        await show_screen(q, context, "Статистика упражнений:", kb, target_user_id)
                    return

        if parts[0] == "run":
            action = parts[1] if len(parts) > 1 else ""
            day = int(parts[2]) if len(parts) > 2 else 0
            ue_id = int(parts[3]) if len(parts) > 3 else 0
            if not await _owns_active_exercise(target_user_id, day, ue_id):
                raise ValueError('stale_exercise')
            if action != "history":
                if not await require_edit_allowed(q, context):
                    return
            is_library = day == 0
            sheet_context = get_sheet_context(
                context, q.message.chat_id, q.message.message_id
            )
            sheet_day = (
                int(sheet_context.get("day")) if sheet_context and "day" in sheet_context else None
            )
            sheet_page = (
                int(sheet_context.get("page")) if sheet_context and "page" in sheet_context else 0
            )
            prefs = await load_ui_preferences(target_user_id)
            if action == "history":
                index = int(parts[4]) if len(parts) > 4 else 0
                back_cb = None
                if sheet_context and not is_library:
                    target_day = sheet_day if sheet_day is not None else day
                    back_cb = f"day:open:{target_day}"
                text, kb = await build_running_history_view(
                    target_user_id,
                    day,
                    ue_id,
                    index,
                    back_callback=back_cb,
                    prefs=prefs,
                    )
                if sheet_context and not is_library and sheet_day is not None:
                    set_sheet_context(
                        context,
                        q.message.chat_id,
                        q.message.message_id,
                        sheet_day,
                        sheet_page,
                    )
                await show_screen(q, context, text, kb, target_user_id)
                return
            if not is_library:
                suppress_completed_day_warning(context, target_user_id, day)
            async with user_locks[target_user_id]:
                if action in {'inc', 'input'}:
                    today = await get_user_local_date(target_user_id)
                    session = await get_or_create_today_session(target_user_id, today, day,
                                                                system_id=await _active_system_id(target_user_id))
                    await get_running_entry(target_user_id, ue_id, session_id=session,
                                             day_index=day, create=True)
                selected = get_flex_selected(context, day, ue_id)
                view = await render_exercise_view(
                    target_user_id, day, ue_id, selected, prefs=prefs
                )
                set_flex_selected(context, day, ue_id, view.selected_set)
                running = view.running or {}
                entry_id = int(running.get("entry_id") or 0)
                distance_value = float(running.get("distance") or 0.0)
                duration_value = int(running.get("duration") or 0)
                duration_ms_value = int(running.get("duration_ms") or 0)
                if not duration_ms_value and duration_value:
                    duration_ms_value = duration_value * 1000
                if not entry_id:
                    await q.answer("Не удалось загрузить забег.", show_alert=True)
                    return
                if action == "inc":
                    if len(parts) < 5:
                        return
                    field = parts[4]
                    delta_raw = parts[5] if len(parts) > 5 else "0"
                    try:
                        delta_value = float(delta_raw)
                    except ValueError:
                        await q.answer("Не удалось изменить значение.", show_alert=True)
                        return
                    update_kwargs: dict = {"is_draft": 1}
                    if field == "dist":
                        new_distance = clamp_running_distance(
                            distance_value + delta_value
                        )
                        update_kwargs["distance_km"] = new_distance
                    elif field == "time":
                        new_duration = clamp_running_duration(
                            duration_value + int(round(delta_value))
                        )
                        update_kwargs["duration_sec"] = new_duration
                        update_kwargs["duration_ms"] = new_duration * 1000
                    else:
                        return
                    await update_running_entry(entry_id, **update_kwargs)
                elif action == "input":
                    target = parts[4] if len(parts) > 4 else ""
                    prompts = {
                        "distance": "Сколько километров пробежал? Напиши число, например 5.2.",
                        "time": "Сколько заняло времени? Используй формат ММ:СС или ЧЧ:ММ:СС.",
                        "pace": "Какой средний темп? Укажи ММ:СС на километр.",
                        "calories": "Сколько калорий сжёг? Например 320.",
                    }
                    prompt = prompts.get(target)
                    if not prompt:
                        await q.answer()
                        return
                    state = {
                        "field": target,
                        "day": day,
                        "ue_id": ue_id,
                        "target_user_id": target_user_id,
                        "chat_id": q.message.chat_id,
                        "message_id": q.message.message_id,
                        "is_library": is_library,
                        "entry_id": entry_id,
                    }
                    if sheet_context and not is_library:
                        state["sheet"] = {
                            "day": sheet_day if sheet_day is not None else day,
                            "page": sheet_page,
                        }
                        clear_sheet_context(
                            context, q.message.chat_id, q.message.message_id
                        )
                    context.user_data[RUNNING_INPUT_KEY] = state
                    kb = InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    BACK_BTN, callback_data=f"run:cancel:{day}:{ue_id}"
                                )
                            ]
                        ]
                    )
                    await show_screen(q, context, prompt, kb, target_user_id)
                    return
                elif action == "cancel":
                    context.user_data.pop(RUNNING_INPUT_KEY, None)
                elif action == "done":
                    if distance_value <= 0 or duration_value <= 0:
                        await q.answer(
                            "Добавь дистанцию и время перед сохранением.",
                            show_alert=True,
                        )
                        return
                    await mark_running_entry_done(entry_id)
                    if view.session_id:
                        await mark_exercise_done(view.session_id, ue_id)
                    if sheet_context and not is_library:
                        target_day = sheet_day if sheet_day is not None else day
                        await render_day_sheet_from_callback(
                            q,
                            context,
                            target_user_id,
                            target_day,
                            sheet_page,
                            prefs=prefs,
                        )
                        await q.answer("Забег сохранён!")
                        return
                else:
                    return
                if sheet_context and action == "cancel" and not is_library:
                    target_day = sheet_day if sheet_day is not None else day
                    await render_day_sheet_from_callback(
                        q,
                        context,
                        target_user_id,
                        target_day,
                        sheet_page,
                        prefs=prefs,
                    )
                    return
                refreshed = await render_exercise_view(
                    target_user_id, day, ue_id, get_flex_selected(context, day, ue_id), prefs=prefs
                )
                set_flex_selected(context, day, ue_id, refreshed.selected_set)
                kb = build_exercise_actions_markup(
                    refreshed,
                    day=day,
                    ue_id=ue_id,
                    group=refreshed.group,
                    prefs=prefs,
                    is_library=is_library,
                    context=context,
                )
                await show_screen(q, context, refreshed.text, kb, target_user_id)
                return

        if parts[0] == "set":
            action = parts[1]
            mutating_set_actions = {
                "rename_day",
                "edit_day",
                "groups",
                "reminders",
                "clear_completions",
            }
            if action in mutating_set_actions:
                if not await require_edit_allowed(q, context):
                    return
            if action == "trainer_mode":
                if len(parts) == 2:
                    await show_trainer_root_settings(q, context, actor_user_id)
                    return
                if len(parts) >= 3 and parts[2] == "toggle":
                    desired_state = parts[3] if len(parts) > 3 else None
                    profile = await _fetch_trainer_profile(actor_user_id)
                    if desired_state == "on":
                        await _ensure_trainer_mode(actor_user_id, profile)
                        reactivated_trainees = await reactivate_trainer_links(
                            actor_user_id
                        )
                        if reactivated_trainees:
                            app_user_data = getattr(
                                context.application, "user_data", None
                            )
                            if isinstance(app_user_data, dict):
                                for trainee_user_id in reactivated_trainees:
                                    trainee_record = await find_user_by_id(
                                        trainee_user_id
                                    )
                                    if not trainee_record:
                                        continue
                                    _db_id, trainee_tg_id, _username = trainee_record
                                    if trainee_tg_id is None:
                                        continue
                                    trainee_context = app_user_data.get(trainee_tg_id)
                                    if not isinstance(trainee_context, dict):
                                        continue
                                    target_message = trainee_context.get(
                                        TRAINER_SETTINGS_MESSAGE_KEY
                                    )
                                    if isinstance(target_message, tuple):
                                        await refresh_trainee_trainer_settings_message(
                                            context,
                                            trainee_user_id,
                                            target_message,
                                        )
                    elif desired_state == "off":
                        async with connect_db() as db:
                            await db.execute(
                                "UPDATE users SET is_trainer = 0 WHERE id=?",
                                (actor_user_id,),
                            )
                            await db.commit()
                        affected_trainees = await deactivate_trainer_links(actor_user_id)
                        context.user_data.pop("acting_user_id", None)
                        context.user_data.pop("acting_can_edit", None)
                        context.user_data.pop(RESOLVE_TARGET_USER_KEY, None)
                        context.user_data.pop("acting_label", None)
                        if affected_trainees:
                            app_user_data = getattr(context.application, "user_data", None)
                            if isinstance(app_user_data, dict):
                                for trainee_user_id in affected_trainees:
                                    trainee_record = await find_user_by_id(trainee_user_id)
                                    if not trainee_record:
                                        continue
                                    _db_id, trainee_tg_id, _username = trainee_record
                                    if trainee_tg_id is None:
                                        continue
                                    trainee_context = app_user_data.get(trainee_tg_id)
                                    if not isinstance(trainee_context, dict):
                                        continue
                                    target_message = trainee_context.get(
                                        TRAINER_SETTINGS_MESSAGE_KEY
                                    )
                                    if isinstance(target_message, tuple):
                                        await refresh_trainee_trainer_settings_message(
                                            context,
                                            trainee_user_id,
                                            target_message,
                                        )
                    await show_trainer_root_settings(q, context, actor_user_id)
                    return
                if len(parts) >= 3 and parts[2] == "trainee":
                    await show_become_trainee_screen(
                        q, context, actor_user_id, prompt_for_code=False
                    )
                    return
            if action == "trainer_link":
                await show_become_trainee_screen(
                    q, context, actor_user_id, prompt_for_code=True
                )
                return
            if action == "rename_day":
                if len(parts) == 2:
                    days = await list_active_days(target_user_id)
                    await show_screen(
                        q,
                        context,
                        'Выбери день:',
                        rename_day_kb(days, context=context),
                        target_user_id,
                    )
                else:
                    day = int(parts[2])
                    message = await show_screen(
                        q, context, f'Новое название для Дня {day}:', None, target_user_id
                    )
                    target_message = message or q.message
                    context.user_data["awaiting_rename"] = (
                        day,
                        getattr(target_message, "chat_id", q.message.chat_id),
                        getattr(target_message, "message_id", q.message.message_id),
                    )
                return
            if action == "days_count":
                if context.user_data.get("acting_user_id"):
                    await q.answer(
                        "Количество тренировочных дней может менять только сам спортсмен.",
                        show_alert=True,
                    )
                    return
                if not is_edit_allowed(context.user_data):
                    await q.answer(
                        "Подопечный не дал вам права менять его график тренировок.",
                        show_alert=True,
                    )
                    return
                if len(parts) == 2:
                    await show_screen(
                        q,
                        context,
                        'Сколько тренировок планируешь в неделю?',
                        days_count_kb(context=context),
                        target_user_id,
                    )
                else:
                    n = int(parts[2])
                    removed = await set_workouts_per_week(target_user_id, n)
                    if removed:
                        _remove_jobs_for_removed_reminders(
                            context.job_queue, target_user_id, removed
                        )
                    app = context.application
                    if app is not None:
                        await _schedule_user_reminders(app, target_user_id)
                    rems = await list_user_reminders(target_user_id)
                    if len(rems) < n:
                        context.user_data["from_settings"] = True
                        context.user_data["tz_page"] = 0
                        context.user_data["workouts_per_week"] = n
                        context.user_data["reminder_day"] = len(rems) + 1
                        if rems:
                            tz_code = await get_user_timezone(target_user_id)
                            if tz_code:
                                context.user_data["tz"] = tz_code
                                context.user_data["reminder_skip_tz"] = True
                        await show_screen(q, context, 'Хотите настроить уведомления для новых дней?', reminders_kb(), target_user_id)
                    else:
                        kb = await build_settings_keyboard_for_user(context, target_user_id)
                        await show_screen(
                            q,
                            context,
                            'Количество тренировок обновлено.',
                            kb,
                            target_user_id,
                        )
                return
            if action == "groups":
                if len(parts) == 2:
                    rows = await list_user_muscle_groups(target_user_id)
                    context.user_data["custom_groups"] = {code: name for code, name in rows}
                    if not rows:
                        text = (
                            "Собственных групп пока нет. Добавь их через настройку дней — здесь появится список для удаления."
                        )
                    else:
                        text = (
                            "Выбери группу, которую хочешь удалить.\n"
                            "Все упражнения из неё исчезнут из расписания и библиотеки."
                        )
                    await show_screen(
                        q,
                        context,
                        text,
                        settings_groups_kb(rows, context=context),
                        target_user_id,
                    )
                    return
                if len(parts) >= 4 and parts[2] == "del":
                    code = parts[3]
                    if not code.startswith("u"):
                        await q.answer("Эту группу нельзя удалить.", show_alert=True)
                        return
                    custom = await get_custom_groups(target_user_id, context)
                    name = custom.get(code, MG_NAMES.get(code, code))
                    if len(parts) == 4:
                        text = (
                            f"Удалить группу «{name}»?\n"
                            "Все упражнения из неё исчезнут из расписания и библиотеки."
                        )
                        kb = confirm_settings_group_delete_kb(code, context=context)
                        await show_screen(q, context, text, kb, target_user_id)
                        return
                    if len(parts) >= 5 and parts[4] == "ok":
                        removed = await remove_user_muscle_group(target_user_id, code)
                        if not removed:
                            await q.answer("Не удалось удалить группу.", show_alert=True)
                            rows = await list_user_muscle_groups(target_user_id)
                            message = (
                                "Собственных групп пока нет. Добавь их через настройку дней — здесь появится список для удаления."
                                if not rows
                                else "Выбери группу, которую хочешь удалить.\nВсе упражнения из неё исчезнут из расписания и библиотеки."
                            )
                            await show_screen(
                                q,
                                context,
                                message,
                                settings_groups_kb(rows, context=context),
                                target_user_id,
                            )
                            return
                        custom.pop(code, None)
                        rows = await list_user_muscle_groups(target_user_id)
                        context.user_data["custom_groups"] = {c: n for c, n in rows}
                        if rows:
                            text = (
                                "Группа удалена. Все связанные упражнения убраны из расписания и библиотеки."
                            )
                        else:
                            text = (
                                "Группа удалена. Все связанные упражнения убраны из расписания и библиотеки."
                                "\nСобственных групп больше нет."
                            )
                        await q.answer("Группа удалена.")
                        await show_screen(
                            q,
                            context,
                            text,
                            settings_groups_kb(rows, context=context),
                            target_user_id,
                        )
                        return
                return
            if action == "clear_completions":
                target_system_id = await _active_system_id(target_user_id)
                await clear_day_completions(target_user_id, system_id=target_system_id)
                kb = await build_settings_keyboard_for_user(context, target_user_id)
                await show_screen(
                    q,
                    context,
                    "Галочки сброшены. Записи по упражнениям остаются.",
                    kb,
                    target_user_id,
                )
                return
            if action == "reminders":
                if len(parts) == 2:
                    context.user_data.pop("tz_only_change", None)
                    context.user_data["from_settings"] = True
                    tz_code = await get_user_timezone(target_user_id)
                    tz_label = get_timezone_label(tz_code)
                    rems = await list_user_reminders(target_user_id)
                    enabled = await get_user_notifications_enabled(target_user_id)
                    text = build_reminders_settings_text(tz_label, enabled, rems)
                    await show_screen(
                        q,
                        context,
                        text,
                        reminders_edit_kb(enabled),
                        target_user_id,
                    )
                    return
                sub = parts[2]
                if sub == "toggle" and len(parts) >= 4:
                    desired = parts[3]
                    enabled = desired == "on"
                    await set_user_notifications_enabled(target_user_id, enabled)
                    app = context.application
                    if app is not None:
                        await _schedule_user_reminders(app, target_user_id)
                    await q.answer(
                        "Уведомления включены." if enabled else "Уведомления отключены."
                    )
                    tz_code = await get_user_timezone(target_user_id)
                    tz_label = get_timezone_label(tz_code)
                    rems = await list_user_reminders(target_user_id)
                    text = build_reminders_settings_text(tz_label, enabled, rems)
                    await show_screen(
                        q,
                        context,
                        text,
                        reminders_edit_kb(enabled),
                        target_user_id,
                    )
                    return
                if sub == "tz":
                    context.user_data["from_settings"] = True
                    context.user_data["tz_page"] = 0
                    context.user_data["tz_only_change"] = True
                    await show_screen(q, context, 'Выбери свой часовой пояс:', tz_select_kb(0), target_user_id)
                    return
                if sub == "time":
                    context.user_data["from_settings"] = True
                    context.user_data.pop("tz_only_change", None)
                    context.user_data.pop(REMINDER_EDIT_POSITION_KEY, None)
                    context.user_data.pop(REMINDER_EDIT_LABEL_KEY, None)
                    context.user_data.pop(REMINDER_SELECTED_DOW_KEY, None)
                    await show_reminders_overview(q, context, target_user_id)
                    return
            if action == "subscription":
                if len(parts) == 2:
                    await show_subscription_overview(q, context, target_user_id)
                    return
                sub_action = parts[2]
                if sub_action == "plan" and len(parts) >= 4:
                    await start_subscription_payment(q, context, target_user_id, parts[3])
                    return
                if sub_action == "planstars" and len(parts) >= 4:
                    await start_subscription_payment_stars(q, context, target_user_id, parts[3])
                    return
                await show_subscription_overview(q, context, target_user_id)
                return

        if parts[0] == "remedit":
            if not await require_edit_allowed(q, context):
                return
            action = parts[1] if len(parts) > 1 else ""
            if action in {'dow', 'time'}:
                position = int(parts[2]) if len(parts) > 2 else 0
                days = await list_active_days(target_user_id)
                state = context.user_data
                valid_scope = (
                    state.get('reminder_edit_owner') == target_user_id
                    and state.get('reminder_edit_system') == await _active_system_id(target_user_id)
                    and state.get(REMINDER_EDIT_POSITION_KEY) == position
                    and 1 <= position <= len(days)
                    and state.get(REMINDER_EDIT_DAY_INDEX_KEY) == days[position - 1][0]
                )
                if not valid_scope:
                    await q.answer('Настройки изменились. Выберите день заново.', show_alert=True)
                    await show_reminders_overview(q, context, target_user_id)
                    return
            if action == "back":
                context.user_data.pop(REMINDER_EDIT_POSITION_KEY, None)
                context.user_data.pop(REMINDER_EDIT_LABEL_KEY, None)
                context.user_data.pop(REMINDER_EDIT_DAY_INDEX_KEY, None)
                context.user_data.pop(REMINDER_SELECTED_DOW_KEY, None)
                context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
                tz_code = await get_user_timezone(target_user_id)
                tz_label = get_timezone_label(tz_code)
                reminders = await list_user_reminders(target_user_id)
                enabled = await get_user_notifications_enabled(target_user_id)
                text = build_reminders_settings_text(tz_label, enabled, reminders)
                await show_screen(
                    q,
                    context,
                    text,
                    reminders_edit_kb(enabled),
                    target_user_id,
                )
                return
            if action == "day":
                if len(parts) < 3:
                    await show_reminders_overview(q, context, target_user_id)
                    return
                try:
                    position = int(parts[2])
                except ValueError:
                    await show_reminders_overview(q, context, target_user_id)
                    return
                days = await list_active_days(target_user_id)
                if position < 1 or position > len(days):
                    await q.answer("День не найден.", show_alert=True)
                    await show_reminders_overview(q, context, target_user_id)
                    return
                day_index, raw_label = days[position - 1]
                await start_reminder_day_edit(q, context, target_user_id, position, day_index, raw_label)
                return
            if action == "dow":
                if len(parts) >= 4 and parts[3] == "back":
                    await show_reminders_overview(q, context, target_user_id)
                    return
                if len(parts) < 4:
                    await show_reminders_overview(q, context, target_user_id)
                    return
                try:
                    position = int(parts[2])
                    dow_iso = parts[3]
                except ValueError:
                    await show_reminders_overview(q, context, target_user_id)
                    return
                day_index = context.user_data.get(REMINDER_EDIT_DAY_INDEX_KEY, position)
                context.user_data[REMINDER_EDIT_POSITION_KEY] = position
                context.user_data[REMINDER_SELECTED_DOW_KEY] = dow_iso
                label = context.user_data.get(REMINDER_EDIT_LABEL_KEY)
                if not label:
                    days = await list_active_days(target_user_id)
                    if 1 <= position <= len(days):
                        _, raw_label = days[position - 1]
                        label = (raw_label or "").strip() or f"{t('DAY')} {day_index}"
                        context.user_data[REMINDER_EDIT_LABEL_KEY] = label
                    else:
                        label = f"{t('DAY')} {day_index}"
                reminders = await list_user_reminders(target_user_id)
                reminder_map = {
                    day_no: (
                        int(d) if d is not None else None,
                        int(h),
                        int(m),
                    )
                    for day_no, d, h, m in reminders
                }
                current = reminder_map.get(day_index)
                selected_time = (current[1], current[2]) if current else None
                tz_code = await get_user_timezone(target_user_id)
                tz_label = get_timezone_label(tz_code)
                text = (
                    f"{label}. Во сколько напоминать? Выбери время (по {tz_label})."
                )
                context.user_data[REMINDER_TIME_PAGE_KEY] = 0
                kb = reminder_time_kb(
                    prefix=f"remedit:time:{position}:{dow_iso}",
                    selected=selected_time,
                    page=0,
                )
                await show_screen(q, context, text, kb, target_user_id)
                return
            if action == "time":
                if len(parts) < 4:
                    await show_reminders_overview(q, context, target_user_id)
                    return
                try:
                    position = int(parts[2])
                except ValueError:
                    await show_reminders_overview(q, context, target_user_id)
                    return
                if len(parts) >= 5 and parts[-1] == "back":
                    dow_iso = parts[3] if len(parts) > 3 else None
                    if dow_iso is None:
                        dow_iso = context.user_data.get(REMINDER_SELECTED_DOW_KEY)
                    context.user_data[REMINDER_SELECTED_DOW_KEY] = dow_iso
                    context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
                    label = context.user_data.get(
                        REMINDER_EDIT_LABEL_KEY,
                        f"{t('DAY')} {position}",
                    )
                    tz_code = await get_user_timezone(target_user_id)
                    tz_label = get_timezone_label(tz_code)
                    selected_dow = None
                    try:
                        iso_value = int(dow_iso) if dow_iso is not None else None
                    except (TypeError, ValueError):
                        iso_value = None
                    if iso_value is not None and 1 <= iso_value <= 7:
                        selected_dow = iso_value - 1
                    kb = reminder_day_kb(
                        prefix=f"remedit:dow:{position}",
                        selected=selected_dow,
                    )
                    await show_screen(
                        q,
                        context,
                        f"{label}. В какой день недели тренировка?",
                        kb,
                        target_user_id,
                    )
                    return
                if len(parts) >= 6 and parts[4] == "page":
                    try:
                        page = max(int(parts[5]), 0)
                    except ValueError:
                        page = 0
                    try:
                        dow_iso = parts[3]
                    except ValueError:
                        dow_iso = context.user_data.get(REMINDER_SELECTED_DOW_KEY)
                    context.user_data[REMINDER_SELECTED_DOW_KEY] = dow_iso
                    position = context.user_data.get(REMINDER_EDIT_POSITION_KEY, position)
                    label = context.user_data.get(
                        REMINDER_EDIT_LABEL_KEY,
                        f"{t('DAY')} {position}",
                    )
                    reminders = await list_user_reminders(target_user_id)
                    reminder_map = {
                        day_no: (
                            int(d) if d is not None else None,
                            int(h),
                            int(m),
                        )
                        for day_no, d, h, m in reminders
                    }
                    day_index = context.user_data.get(REMINDER_EDIT_DAY_INDEX_KEY, position)
                    current = reminder_map.get(day_index)
                    selected_time = (current[1], current[2]) if current else None
                    tz_code = await get_user_timezone(target_user_id)
                    tz_label = get_timezone_label(tz_code)
                    context.user_data[REMINDER_TIME_PAGE_KEY] = page
                    kb = reminder_time_kb(
                        prefix=f"remedit:time:{position}:{dow_iso}",
                        selected=selected_time,
                        page=page,
                    )
                    await show_screen(
                        q,
                        context,
                        f"{label}. Во сколько напоминать? Выбери время (по {tz_label}).",
                        kb,
                        target_user_id,
                    )
                    return
                if len(parts) < 6:
                    await show_reminders_overview(q, context, target_user_id)
                    return
                try:
                    dow_iso_raw = parts[3]
                    hour = int(parts[4])
                    minute = int(parts[5])
                except ValueError:
                    await show_reminders_overview(q, context, target_user_id)
                    return
                try:
                    dow_iso = int(dow_iso_raw)
                except (TypeError, ValueError):
                    await show_reminders_overview(q, context, target_user_id)
                    return
                if not 1 <= dow_iso <= 7:
                    await show_reminders_overview(q, context, target_user_id)
                    return
                dow = dow_iso - 1
                day_index = context.user_data.get(REMINDER_EDIT_DAY_INDEX_KEY, position)
                label = context.user_data.get(
                    REMINDER_EDIT_LABEL_KEY,
                    f"{t('DAY')} {day_index}",
                )
                reminders = await list_user_reminders(target_user_id)
                reminder_map = {
                    day_no: (
                        int(d) if d is not None else None,
                        int(h),
                        int(m),
                    )
                    for day_no, d, h, m in reminders
                }
                previous = reminder_map.get(day_index)
                if not await add_user_reminder(
                    target_user_id, dow, hour, minute, day_no=day_index
                ):
                    await q.answer("Не удалось сохранить напоминание.", show_alert=True)
                    return
                if previous and previous[0] is not None and previous[0] >= 0:
                    _remove_reminder_jobs(
                        context.job_queue, target_user_id, day_index, int(previous[0])
                    )
                tz_code = await get_user_timezone(target_user_id)
                message = getattr(q, "message", None)
                chat_id = getattr(message, "chat_id", None)
                if chat_id is None:
                    chat = getattr(message, "chat", None)
                    chat_id = getattr(chat, "id", None)
                await _schedule_user_reminders(
                    context.application, target_user_id, chat_id=chat_id
                )
                context.user_data[REMINDER_SELECTED_DOW_KEY] = str(dow_iso)
                confirmation = format_reminder_status(label, (dow, hour, minute))
                context.user_data.pop('reminder_edit_owner', None)
                context.user_data.pop('reminder_edit_system', None)
                await q.answer(confirmation)
                context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
                await show_reminders_overview(q, context, target_user_id)
                return
            return

        if parts[0] == "day":
            action = parts[1]
            if int(parts[2]) not in {day for day, _ in await list_active_days(target_user_id)}:
                raise ValueError('day_not_available')
            mutating_day_actions = {
                "sheetdone",
                "groupdel",
                "add_group",
                "manage",
                "add",
                "del",
                "remove_group",
            }
            if action in mutating_day_actions:
                if not await require_edit_allowed(q, context):
                    return
            if action == "open":
                day = int(parts[2])
                prefs = await load_ui_preferences(target_user_id)
                await send_day_cards_view(q, target_user_id, day, context, prefs)
                return
            if action == "complete":
                if not await require_edit_allowed(q, context):
                    return
                day = int(parts[2])
                _, added_new = await record_day_completion(target_user_id, day)
                prefs = await load_ui_preferences(target_user_id)
                text, kb, prefs = await compose_main_menu(target_user_id, prefs)
                label = await get_day_label(target_user_id, day)
                title = label or f"{t('DAY')} {day}"
                await q.answer(f"{title} завершён. Отличная работа!")
                should_show_support = False
                if added_new:
                    should_show_support = await maybe_prompt_channel_support(
                        q, context, target_user_id
                    )
                if should_show_support:
                    return
                await show_screen(q, context, text, kb, target_user_id)
                return
            if action == "sheet":
                day = int(parts[2])
                await q.answer("Компактный режим больше недоступен. Открываю карточки дня.")
                prefs = await load_ui_preferences(target_user_id)
                await send_day_cards_view(q, target_user_id, day, context, prefs)
                return
            if action == "sheetdone":
                day = int(parts[2])
                today_local = await get_user_local_date(target_user_id)
                target_system_id = await _active_system_id(target_user_id)
                ex_rows = await fetch_day_exercises(target_user_id, day, today_local, system_id=target_system_id)
                if ex_rows:
                    session_id = await get_or_create_today_session(target_user_id, today_local, day, system_id=target_system_id)
                    for ue_id, *_ in ex_rows:
                        await mark_exercise_done(session_id, ue_id)
                _, added_new = await record_day_completion(target_user_id, day)
                await q.answer(f"{t('DAY')} отмечен выполненным.")
                prefs = await load_ui_preferences(target_user_id)
                if added_new and await maybe_prompt_channel_support(
                    q, context, target_user_id
                ):
                    return
                await send_day_cards_view(q, target_user_id, day, context, prefs)
                return
            if action == "group":
                day = int(parts[2])
                group = parts[3]
                clear_sheet_context(context, q.message.chat_id, q.message.message_id)
                await show_day_group_view(q, target_user_id, day, group, context)
                return
            if action == "groupdel":
                day = int(parts[2])
                group = parts[3]
                if not group.startswith("u"):
                    await q.answer("Эту группу нельзя удалить.", show_alert=True)
                    return
                custom = await get_custom_groups(target_user_id, context)
                gname = MG_NAMES.get(group, custom.get(group, group))
                if len(parts) == 4:
                    text = (
                        f"Удалить группу «{gname}»?\n"
                        "Все упражнения из неё будут убраны из твоих тренировочных дней."
                    )
                    prefs = await load_ui_preferences(target_user_id)
                    await show_screen(q, context, text, kb, target_user_id)
                    return
                if len(parts) >= 5 and parts[4] == "ok":
                    removed = await remove_user_muscle_group(target_user_id, group)
                    if not removed:
                        await q.answer("Не удалось удалить группу.", show_alert=True)
                        await show_day_group_view(q, target_user_id, day, group, context)
                        return
                    custom.pop(group, None)
                    day_groups = context.user_data.get("day_groups")
                    if isinstance(day_groups, dict):
                        for selected in day_groups.values():
                            if isinstance(selected, set) and group in selected:
                                selected.discard(group)
                    context.user_data.pop("add_group", None)
                    await q.answer("Группа удалена.")
                    prefs = await load_ui_preferences(target_user_id)
                    await send_day_cards_view(q, target_user_id, day, context, prefs)
                    return
                return
            if action == "add_group":
                day = int(parts[2])
                clear_sheet_context(context, q.message.chat_id, q.message.message_id)
                context.user_data["awaiting_group_name"] = (
                    day,
                    q.message.chat_id,
                    q.message.message_id,
                    "day",
                    target_user_id,
                )
                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                BACK_BTN,
                                callback_data=f"day:manage:{day}:all:add",
                            )
                        ]
                    ]
                )
                await show_screen(
                    q,
                    context,
                    "Как назвать новую группу мышц? Напиши название сообщением.",
                    kb,
                    target_user_id,
                )
                return
            if action == "manage":
                day = int(parts[2])
                scope = parts[3] if len(parts) > 3 else "all"
                sub = parts[4] if len(parts) > 4 else None
                clear_sheet_context(context, q.message.chat_id, q.message.message_id)
                today_str = await get_user_local_date(target_user_id)
                target_system_id = await _active_system_id(target_user_id)
                ex_rows = await fetch_day_exercises(target_user_id, day, today_str, system_id=target_system_id)
                custom = await get_custom_groups(target_user_id, context)
                target_group = None if scope == "all" else scope
                if sub is None:
                    if target_group is None:
                        prefs = await load_ui_preferences(target_user_id)
                        await send_day_cards_view(q, target_user_id, day, context, prefs)
                    else:
                        await show_day_group_view(q, target_user_id, day, target_group, context)
                    return
                if sub == "add":
                    if target_group is None:
                        existing_groups = {row[2] for row in ex_rows}
                        kb = day_add_group_kb(
                            day, custom, existing_groups, context=context
                        )
                        await show_screen(q, context, "Выбери группу:", kb, target_user_id)
                        return
                    context.user_data["add_group"] = (day, target_group)
                    await show_day_add_exercises_view(
                        q, target_user_id, day, target_group, context
                    )
                    return
                if sub == "del":
                    if target_group is None:
                        order: list[str] = []
                        for _, _, raw_group, *_ in ex_rows:
                            if raw_group not in order:
                                order.append(raw_group)
                        if not order:
                            await q.answer("Пока нечего удалять.", show_alert=True)
                            prefs = await load_ui_preferences(target_user_id)
                            await send_day_cards_view(q, target_user_id, day, context, prefs)
                            return
                        groups_for_kb = []
                        for code in order:
                            name = MG_NAMES.get(code, custom.get(code, code))
                            groups_for_kb.append((code, name))
                        kb = day_remove_group_kb(day, groups_for_kb, context=context)
                        context.user_data.pop(DAY_DELETE_SCOPE_KEY, None)
                        await show_screen(
                            q, context, "Удалить группу мышц:", kb, target_user_id
                        )
                        return
                    filtered = [row for row in ex_rows if row[2] == target_group]
                    if not filtered:
                        await q.answer("Пока нечего удалять.", show_alert=True)
                        await show_day_group_view(q, target_user_id, day, target_group, context)
                        return
                    gname = MG_NAMES.get(
                        target_group, custom.get(target_group, target_group)
                    )
                    text = (
                        f"{t('DAY')} {day} — {gname}\n"
                        "Нажми на упражнение, чтобы удалить его из дня.\n"
                        "Если захочешь добавить другие упражнения, вернись назад."
                    )
                    if target_group.startswith("u"):
                        text += "\nМожно удалить всю группу через «− Группа»."
                    context.user_data[DAY_DELETE_SCOPE_KEY] = {
                        "day": day,
                        "group": target_group,
                    }
                    kb = del_exercises_kb(
                        day,
                        ex_rows,
                        group=target_group,
                        back_callback=f"day:group:{day}:{target_group}",
                        group_delete_callback=(
                            f"day:groupdel:{day}:{target_group}"
                            if target_group.startswith("u")
                            else None
                        ),
                        group_delete_label=gname if target_group.startswith("u") else None,
                        context=context,
                    )
                    await show_screen(q, context, text, kb, target_user_id)
                    return
                return
            if action == "remove_group":
                day = int(parts[2])
                group = parts[3]
                clear_sheet_context(context, q.message.chat_id, q.message.message_id)
                today_str = await get_user_local_date(target_user_id)
                target_system_id = await _active_system_id(target_user_id)
                ex_rows = await fetch_day_exercises(target_user_id, day, today_str, system_id=target_system_id)
                filtered = [row for row in ex_rows if row[2] == group]
                if not filtered:
                    await q.answer("Эта группа уже отсутствует в дне.", show_alert=True)
                else:
                    for ue_id, *_ in filtered:
                        await remove_user_exercise(target_user_id, day, ue_id)
                    if context.user_data.get("add_group") == (day, group):
                        context.user_data.pop("add_group", None)
                    await q.answer("Группа удалена из дня.")
                target_system_id = await _active_system_id(target_user_id)
                ex_rows = await fetch_day_exercises(target_user_id, day, today_str, system_id=target_system_id)
                order: list[str] = []
                for _, _, raw_group, *_ in ex_rows:
                    if raw_group not in order:
                        order.append(raw_group)
                if order:
                    custom = await get_custom_groups(target_user_id, context)
                    groups_for_kb = []
                    for code in order:
                        name = MG_NAMES.get(code, custom.get(code, code))
                        groups_for_kb.append((code, name))
                    kb = day_remove_group_kb(day, groups_for_kb, context=context)
                    await show_screen(q, context, "Удалить группу мышц:", kb, target_user_id)
                else:
                    prefs = await load_ui_preferences(target_user_id)
                    await send_day_cards_view(q, target_user_id, day, context, prefs)
                return
            if action == "add_ex":
                day = int(parts[2])
                clear_sheet_context(context, q.message.chat_id, q.message.message_id)
                today_str = await get_user_local_date(target_user_id)
                target_system_id = await _active_system_id(target_user_id)
                ex_rows = await fetch_day_exercises(target_user_id, day, today_str, system_id=target_system_id)
                existing_groups = {row[2] for row in ex_rows}
                custom = await get_custom_groups(target_user_id, context)
                await show_screen(
                    q,
                    context,
                    'Выбери группу:',
                    day_add_group_kb(day, custom, existing_groups, context=context),
                    target_user_id,
                )
                return
            if action == "del_ex":
                day = int(parts[2])
                clear_sheet_context(context, q.message.chat_id, q.message.message_id)
                today_str = await get_user_local_date(target_user_id)
                target_system_id = await _active_system_id(target_user_id)
                ex_rows = await fetch_day_exercises(target_user_id, day, today_str, system_id=target_system_id)
                context.user_data[DAY_DELETE_SCOPE_KEY] = {"day": day, "group": None}
                await show_screen(
                    q,
                    context,
                    'Удалить упражнение:',
                    del_exercises_kb(day, ex_rows, context=context),
                    target_user_id,
                )
                return
            if action == "add":
                day = int(parts[2])
                sub = parts[3]
                clear_sheet_context(context, q.message.chat_id, q.message.message_id)
                if sub == "mg":
                    group = parts[4]
                    context.user_data["add_group"] = (day, group)
                    await show_day_add_exercises_view(q, target_user_id, day, group, context)
                    return
                if sub == "custom_group":
                    context.user_data["awaiting_group_name"] = (
                        day,
                        q.message.chat_id,
                        q.message.message_id,
                        "day",
                        target_user_id,
                    )
                    kb = InlineKeyboardMarkup(
                        [[InlineKeyboardButton(BACK_BTN, callback_data=f"day:add:{day}:mg_back")]]
                    )
                    await show_screen(
                        q,
                        context,
                        "Как назвать новую группу мышц? Напиши название сообщением.",
                        kb,
                        target_user_id,
                    )
                    return
                if sub == "mg_back":
                    pending = context.user_data.get("awaiting_group_name")
                    if pending and pending[0] == day:
                        context.user_data.pop("awaiting_group_name", None)
                    today_str = await get_user_local_date(target_user_id)
                    target_system_id = await _active_system_id(target_user_id)
                    ex_rows = await fetch_day_exercises(target_user_id, day, today_str, system_id=target_system_id)
                    existing_groups = {row[2] for row in ex_rows}
                    custom = await get_custom_groups(target_user_id, context)
                    kb = day_add_group_kb(
                        day, custom, existing_groups, context=context
                    )
                    await show_screen(q, context, "Выбери группу:", kb, target_user_id)
                    return
                if sub == "page":
                    group = parts[4]
                    requested_page = int(parts[5]) if len(parts) > 5 else 0
                    context.user_data["add_group"] = (day, group)
                    await show_day_add_exercises_view(
                        q, target_user_id, day, group, context, page=requested_page
                    )
                    return
                if sub == "ex":
                    ex_id = int(parts[4])
                    stored_day, group = context.user_data.get("add_group", (day, None))
                    if stored_day != day:
                        group = None
                    selected_ids: set[int] = set()
                    if group:
                        selected_ids = set(await list_user_exercise_ids(target_user_id, day, group))
                    existed = bool(group and ex_id in selected_ids)
                    await _require_available_catalog_exercise(target_user_id, ex_id)
                    await add_user_exercise(target_user_id, day, ex_id)
                    suppress_completed_day_warning(context, target_user_id, day)
                    if not existed:
                        if not group:
                            details = await get_exercise_details(ex_id)
                            if details:
                                _, detected_group, _owner_user_id = details
                                group = detected_group
                                context.user_data["add_group"] = (day, group)

                    if group:
                        prefs = await load_ui_preferences(target_user_id)
                        await show_day_group_view(
                            q, target_user_id, day, group, context, prefs=prefs
                        )
                    else:
                        prefs = await load_ui_preferences(target_user_id)
                        await send_day_cards_view(q, target_user_id, day, context, prefs)
                    return
                if sub == "custom":
                    group = parts[4]
                    context.user_data["awaiting_custom"] = (
                        day,
                        group,
                        q.message.chat_id,
                        q.message.message_id,
                    )
                    kb = InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    t("BACK"),
                                    callback_data=f"day:add:{day}:custom_back:{group}",
                                )
                            ]
                        ]
                    )
                    await show_screen(q, context, 'Напиши название упражнения:', kb, target_user_id)
                    return
                if sub == "custom_back":
                    group = parts[4]
                    await show_day_add_exercises_view(q, target_user_id, day, group, context)
                    return
                if sub == "done":
                    context.user_data.pop("add_group", None)
                    prefs = await load_ui_preferences(target_user_id)
                    await send_day_cards_view(q, target_user_id, day, context, prefs)
                    return
            if action == "del":
                day = int(parts[2])
                if len(parts) == 4:
                    ue_id = int(parts[3])
                    await remove_user_exercise(target_user_id, day, ue_id)
                    suppress_completed_day_warning(context, target_user_id, day)
                    today_str = await get_user_local_date(target_user_id)
                    target_system_id = await _active_system_id(target_user_id)
                    ex_rows = await fetch_day_exercises(target_user_id, day, today_str, system_id=target_system_id)
                    await q.answer("Упражнение удалено.")
                    scope = context.user_data.get(DAY_DELETE_SCOPE_KEY)
                    target_group = None
                    if isinstance(scope, dict) and scope.get("day") == day:
                        target_group = scope.get("group")
                    if target_group:
                        filtered = [row for row in ex_rows if row[2] == target_group]
                        if filtered:
                            custom = await get_custom_groups(target_user_id, context)
                            gname = MG_NAMES.get(
                                target_group, custom.get(target_group, target_group)
                            )
                            text = (
                                f"{t('DAY')} {day} — {gname}\n"
                                "Нажми на упражнение, чтобы удалить его из дня.\n"
                                "Если захочешь добавить другие упражнения, вернись назад."
                            )
                            if target_group.startswith("u"):
                                text += "\nМожно удалить всю группу через «− Группа»."
                            context.user_data[DAY_DELETE_SCOPE_KEY] = {
                                "day": day,
                                "group": target_group,
                            }
                            kb = del_exercises_kb(
                                day,
                                ex_rows,
                                group=target_group,
                                back_callback=f"day:group:{day}:{target_group}",
                                group_delete_callback=(
                                    f"day:groupdel:{day}:{target_group}"
                                    if target_group.startswith("u")
                                    else None
                                ),
                                context=context,
                            )
                            await show_screen(q, context, text, kb, target_user_id)
                        else:
                            context.user_data.pop(DAY_DELETE_SCOPE_KEY, None)
                            await show_day_group_view(
                                q, target_user_id, day, target_group, context
                            )
                    else:
                        if ex_rows:
                            context.user_data[DAY_DELETE_SCOPE_KEY] = {
                                "day": day,
                                "group": None,
                            }
                            await show_screen(
                                q,
                                context,
                                'Удалить упражнение:',
                                del_exercises_kb(day, ex_rows, context=context),
                                target_user_id,
                            )
                        else:
                            context.user_data.pop(DAY_DELETE_SCOPE_KEY, None)
                            prefs = await load_ui_preferences(target_user_id)
                            await send_day_cards_view(q, target_user_id, day, context, prefs)
                return

        if parts[0] == "ex":
            action = parts[1]
            day = int(parts[2])
            ue_id = int(parts[3])
            if not await _owns_active_exercise(target_user_id, day, ue_id):
                raise ValueError('stale_exercise')
            is_library = day == 0
            mutating_ex_actions = {
                "note",
                "amrapscheme",
                "fill",
                "addset",
                "delset",
                "amrapextra",
                "inc",
                "done",
                "timeedit",
                "timedel",
            }
            if action in mutating_ex_actions:
                if not await require_edit_allowed(q, context):
                    return
                if not is_library:
                    suppress_completed_day_warning(context, target_user_id, day)
            selected = get_flex_selected(context, day, ue_id)
            sheet_context = get_sheet_context(context, q.message.chat_id, q.message.message_id)
            sheet_day = int(sheet_context.get("day")) if sheet_context else None
            sheet_page = int(sheet_context.get("page")) if sheet_context else 0
            prefs = await load_ui_preferences(target_user_id)
            if action in {"view", "select", "progress"}:
                context.user_data.pop(FOR_TIME_INPUT_KEY, None)
                context.user_data.pop(EXERCISE_NOTE_INPUT_KEY, None)
            if action == "amrapscheme":
                ex_id, name, raw_group = await get_exercise_info(ue_id)
                if resolve_group(name, raw_group) != "metcon" or name != AMRAP_EXERCISE_NAME:
                    await q.answer()
                    return
                context.user_data[AMRAP_SCHEME_KEY] = (
                    day,
                    ue_id,
                    q.message.chat_id,
                    q.message.message_id,
                    target_user_id,
                )
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t("BACK"), callback_data=f"ex:view:{day}:{ue_id}")]]
                )
                await show_screen(q, context, 'Напиши схему комплекса. Оставь пусто, чтобы очистить.', kb, target_user_id)
                return
            if action == "webappoff":
                await set_webapp_prompt_suppressed(target_user_id, True)
                view = await render_exercise_view(
                    target_user_id, day, ue_id, selected, prefs=prefs
                )
                set_flex_selected(context, day, ue_id, view.selected_set)
                kb = build_exercise_actions_markup(
                    view,
                    day=day,
                    ue_id=ue_id,
                    group=view.group,
                    prefs=prefs,
                    is_library=is_library,
                    context=context,
                )
                await show_screen(q, context, view.text, kb, target_user_id)
                return
            if action == "select":
                set_no = int(parts[4])
                view = await render_exercise_view(
                    target_user_id, day, ue_id, set_no, prefs=prefs
                )
                set_flex_selected(context, day, ue_id, view.selected_set)
                kb = build_exercise_actions_markup(
                    view,
                    day=day,
                    ue_id=ue_id,
                    group=view.group,
                    prefs=prefs,
                    is_library=is_library,
                    context=context,
                )
                await show_screen(q, context, view.text, kb, target_user_id)
                return
            if action == "view":
                show_prompt = not is_library and (len(parts) < 5 or parts[4] != "bot")
                if show_prompt and await get_webapp_prompt_suppressed(target_user_id):
                    show_prompt = False
                if show_prompt:
                    ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                    resolved_group = resolve_group(ex_name, ex_group)
                    prompt_text = (
                        "Внимание! Записывать свою тренировку в приложении намного удобнее, "
                        "поэтому мы предлагаем вам делать это там."
                    )
                    kb = InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "Открыть приложение", web_app=WebAppInfo(WEBAPP_URL)
                                )
                            ],
                            [InlineKeyboardButton("Открыть в боте", callback_data=f"ex:view:{day}:{ue_id}:bot")],
                            [
                                InlineKeyboardButton(
                                    "Больше не показывать",
                                    callback_data=f"ex:webappoff:{day}:{ue_id}",
                                )
                            ],
                            [InlineKeyboardButton("Назад", callback_data=f"day:group:{day}:{resolved_group}")],
                        ]
                    )
                    await show_screen(q, context, prompt_text, kb, target_user_id)
                    return
                view = await render_exercise_view(
                    target_user_id, day, ue_id, selected, prefs=prefs
                )
                set_flex_selected(context, day, ue_id, view.selected_set)
                kb = build_exercise_actions_markup(
                    view,
                    day=day,
                    ue_id=ue_id,
                    group=view.group,
                    prefs=prefs,
                    is_library=is_library,
                    context=context,
                )
                await show_screen(q, context, view.text, kb, target_user_id)
                return
            if action == "note":
                state = {
                    "day": day,
                    "ue_id": ue_id,
                    "chat_id": q.message.chat_id,
                    "message_id": q.message.message_id,
                    "is_library": is_library,
                }
                if sheet_context and not is_library:
                    state["sheet"] = {
                        "day": sheet_day if sheet_day is not None else day,
                        "page": sheet_page,
                    }
                    clear_sheet_context(
                        context, q.message.chat_id, q.message.message_id
                    )
                context.user_data[EXERCISE_NOTE_INPUT_KEY] = state
                prompt_lines = [
                    t("NOTE_PROMPT"),
                    t("NOTE_EXAMPLE"),
                    t("NOTE_HINT"),
                ]
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t("BACK"), callback_data=f"ex:view:{day}:{ue_id}")]]
                )
                await show_screen(
                    q,
                    context,
                    "\n".join(prompt_lines),
                    kb,
                    target_user_id,
                )
                return
            today_str = await get_user_local_date(target_user_id)
            async with user_locks[target_user_id]:
                target_system_id = await _active_system_id(target_user_id)
                if action in mutating_ex_actions:
                    session_id = await get_or_create_today_session(target_user_id, today_str, day, system_id=target_system_id)
                else:
                    session_id = await get_session_for_day(target_user_id, today_str, day, system_id=target_system_id) or 0
                if action == "fill":
                    await open_fill_editor(
                        q,
                        context,
                        target_user_id,
                        day,
                        ue_id,
                        session_id,
                        is_library,
                        sheet_day,
                        sheet_page,
                        selected,
                        prefs,
                    )
                    return
                elif action == "addset":
                    ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                    resolved_group = resolve_group(ex_name, ex_group)
                    sets = await fetch_exercise_sets(session_id, ue_id)
                    if resolved_group == "metcon" and ex_name == AMRAP_EXERCISE_NAME:
                        if not sets:
                            await add_set(session_id, ue_id, 1, 0.0)
                        else:
                            await inc_last_set(ue_id, session_id, "reps", 1)
                        sets = await fetch_exercise_sets(session_id, ue_id)
                        if sets:
                            set_flex_selected(context, day, ue_id, sets[-1][0])
                        else:
                            set_flex_selected(context, day, ue_id, None)
                    else:
                        if sets:
                            reps = max(int(sets[-1][1] or 0), 0)
                            seconds = max(int(sets[-1][2] or 0), 0)
                            weight = float(max(sets[-1][3] or 0.0, 0.0))
                        else:
                            with_weight, _ = get_display_flags(resolved_group, ex_name)
                            reps = 0
                            seconds = 0
                            weight = 0.0
                            last_session_sets = await fetch_last_session_sets(target_user_id, day, ue_id, today_str)
                            if last_session_sets:
                                rep_values = [max(int(r or 0), 0) for _, r, _seconds, _weight in last_session_sets]
                                if rep_values:
                                    reps = int(round(sum(rep_values) / len(rep_values)))
                                sec_values = [max(int(s or 0), 0) for _, _r, s, _w in last_session_sets]
                                if sec_values:
                                    seconds = int(round(sum(sec_values) / len(sec_values)))
                                if with_weight:
                                    weight_values = [float(w or 0.0) for _, _r, _s, w in last_session_sets]
                                    if weight_values:
                                        weight = max(sum(weight_values) / len(weight_values), 0.0)
                            base = await get_baseline(target_user_id, day, ex_id)
                            if reps == 0 and base:
                                reps = max(int(base[1] or 0), 0)
                            if seconds == 0 and base:
                                seconds = max(int(base[2] or 0), 0)
                            if with_weight:
                                if weight <= 0.0 and base:
                                    weight = float(max(base[3] or 0.0, 0.0))
                                if weight > 0.0:
                                    weight = round(weight / WEIGHT_ROUND_STEP) * WEIGHT_ROUND_STEP
                            else:
                                weight = 0.0
                        await add_set(session_id, ue_id, reps, seconds, weight)
                        sets = await fetch_exercise_sets(session_id, ue_id)
                        if sets:
                            set_flex_selected(context, day, ue_id, sets[-1][0])
                        else:
                            set_flex_selected(context, day, ue_id, None)
                    if sheet_context and not is_library:
                        target_day = sheet_day if sheet_day is not None else day
                        await render_day_sheet_from_callback(
                            q, context, target_user_id, target_day, sheet_page
                        )
                        return
                elif action == "delset":
                    ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                    resolved_group = resolve_group(ex_name, ex_group)
                    if resolved_group == "metcon" and ex_name == AMRAP_EXERCISE_NAME:
                        sets = await fetch_exercise_sets(session_id, ue_id)
                        if not sets:
                            pass
                        else:
                            rounds, _ = parse_amrap_sets(sets)
                            if rounds <= 1:
                                await remove_last_set(ue_id, session_id)
                            else:
                                await inc_last_set(ue_id, session_id, "reps", -1)
                        sets = await fetch_exercise_sets(session_id, ue_id)
                        if sets:
                            set_flex_selected(context, day, ue_id, sets[-1][0])
                        else:
                            set_flex_selected(context, day, ue_id, None)
                    else:
                        await remove_last_set(ue_id, session_id)
                        sets = await fetch_exercise_sets(session_id, ue_id)
                        if sets:
                            set_flex_selected(context, day, ue_id, sets[-1][0])
                        else:
                            set_flex_selected(context, day, ue_id, None)
                    if sheet_context and not is_library:
                        target_day = sheet_day if sheet_day is not None else day
                        await render_day_sheet_from_callback(
                            q, context, target_user_id, target_day, sheet_page
                        )
                        return
                elif action == "amrapextra":
                    delta = int(parts[4]) if len(parts) > 4 else 0
                    ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                    if resolve_group(ex_name, ex_group) != "metcon" or ex_name != AMRAP_EXERCISE_NAME:
                        await q.answer()
                        return
                    sets = await fetch_exercise_sets(session_id, ue_id)
                    if not sets:
                        await add_set(session_id, ue_id, 0, 0.0)
                    await inc_last_set(ue_id, session_id, "weight_kg", delta)
                    sets = await fetch_exercise_sets(session_id, ue_id)
                    if sets:
                        set_flex_selected(context, day, ue_id, sets[-1][0])
                    else:
                        set_flex_selected(context, day, ue_id, None)
                    if sheet_context and not is_library:
                        target_day = sheet_day if sheet_day is not None else day
                        await render_day_sheet_from_callback(
                            q, context, target_user_id, target_day, sheet_page
                        )
                        return
                elif action == "inc":
                    field = parts[4] if len(parts) > 4 else ""
                    delta_value: float | None = None
                    explicit_delta = len(parts) > 5
                    if explicit_delta and parts[5]:
                        try:
                            delta_value = float(parts[5])
                        except ValueError:
                            delta_value = None
                        if delta_value is None:
                            explicit_delta = True
                    else:
                        explicit_delta = False
                    if field == "kg" and delta_value is None and not explicit_delta:
                        delta_value = WEIGHT_ROUND_STEP
                    target = None
                    if field == "reps":
                        target = "reps"
                    elif field == "sec":
                        target = "seconds"
                    elif field == "kg":
                        target = "weight_kg"
                    if target and delta_value is not None:
                        if target in {"reps", "seconds"}:
                            delta_value = int(round(delta_value))
                        sets = await fetch_exercise_sets(session_id, ue_id)
                        ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                        resolved_group = resolve_group(ex_name, ex_group)
                        with_weight, _ = get_display_flags(resolved_group, ex_name)
                        if not sets:
                            stored = await get_session_last_values(session_id, ue_id)
                            reps = 0
                            seconds = 0
                            weight = 0.0
                            if stored and resolved_group != "kb":
                                reps = max(int(stored[0] or 0), 0)
                                seconds = max(int(stored[1] or 0), 0)
                                weight = float(stored[2] or 0.0)
                            else:
                                base = await get_baseline(target_user_id, day, ex_id)
                                if base:
                                    reps = max(int(base[1] or 0), 0)
                                    seconds = max(int(base[2] or 0), 0)
                                    weight = float(base[3] or 0.0)
                            if not with_weight:
                                weight = 0.0
                            await add_set(session_id, ue_id, reps, seconds, weight)
                            sets = await fetch_exercise_sets(session_id, ue_id)
                        if target == "weight_kg" and not with_weight:
                            await q.answer()
                            return
                        selected = get_flex_selected(context, day, ue_id)
                        if selected is None and sets:
                            selected = sets[-1][0]
                            set_flex_selected(context, day, ue_id, selected)
                        if selected is not None:
                            await inc_specific_set(
                                ue_id, session_id, selected, target, delta_value
                            )
                        else:
                            await inc_last_set(ue_id, session_id, target, delta_value)
                        if sheet_context and not is_library:
                            target_day = sheet_day if sheet_day is not None else day
                            await render_day_sheet_from_callback(
                                q, context, target_user_id, target_day, sheet_page
                            )
                            return
                elif action == "done":
                    ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                    resolved = resolve_group(ex_name, ex_group)
                    if resolved == "metcon" and ex_name == FOR_TIME_EXERCISE_NAME:
                        state = {
                            "day": day,
                            "ue_id": ue_id,
                            "chat_id": q.message.chat_id,
                            "message_id": q.message.message_id,
                            "mode": "add",
                            "is_library": is_library,
                        }
                        if sheet_context and not is_library:
                            state["sheet"] = {
                                "day": sheet_day if sheet_day is not None else day,
                                "page": sheet_page,
                            }
                            clear_sheet_context(context, q.message.chat_id, q.message.message_id)
                        context.user_data[FOR_TIME_INPUT_KEY] = state
                        kb = InlineKeyboardMarkup(
                            [[InlineKeyboardButton(t("BACK"), callback_data=f"ex:view:{day}:{ue_id}")]]
                        )
                        await show_screen(q, context, 'Укажи время в формате ММ:СС или ЧЧ:ММ:СС.', kb, target_user_id)
                        return
                    await mark_exercise_done(session_id, ue_id)
                    group = resolve_group(ex_name, ex_group)
                    if sheet_context and not is_library:
                        target_day = sheet_day if sheet_day is not None else day
                        prefs = await load_ui_preferences(target_user_id)
                        await send_day_cards_view(q, target_user_id, target_day, context, prefs)
                        return
                    if is_library:
                        items = await list_library_exercises(target_user_id, group)
                        text = await render_library_group_text(
                            target_user_id, group, items, context, prefs=prefs
                        )
                        custom = await get_custom_groups(target_user_id, context)
                        gname = MG_NAMES.get(group, custom.get(group, group))
                        kb = library_group_kb(group, items, group_name=gname, context=context)
                        await show_screen(q, context, text, kb, target_user_id)
                    else:
                        await show_day_group_view(q, target_user_id, day, group, context)
                    return
                elif action == "progress":
                    ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                    if resolve_group(ex_name, ex_group) == "metcon" and ex_name == FOR_TIME_EXERCISE_NAME:
                        back_cb = None
                        if sheet_context and not is_library:
                            back_cb = f"day:open:{sheet_day if sheet_day is not None else day}"
                        text, kb = await build_for_time_history_view(target_user_id, day, ue_id, back_cb, prefs=prefs)
                        if sheet_context and not is_library and back_cb:
                            set_sheet_context(
                                context,
                                q.message.chat_id,
                                q.message.message_id,
                                sheet_day if sheet_day is not None else day,
                                sheet_page,
                            )
                        await show_screen(q, context, text, kb, target_user_id)
                        return
                    page = 0
                    if len(parts) > 4:
                        try:
                            page = max(int(parts[4]), 0)
                        except ValueError:
                            page = 0
                    total_entries = await count_exercise_progress_entries(target_user_id, day, ue_id)
                    total_pages = max(1, math.ceil(total_entries / PROGRESS_PAGE_SIZE)) if total_entries else 1
                    if total_entries:
                        page = min(page, total_pages - 1)
                    else:
                        page = 0
                    offset = page * PROGRESS_PAGE_SIZE
                    rows = await list_recent_progress(
                        target_user_id,
                        day,
                        ue_id,
                        PROGRESS_PAGE_SIZE,
                        offset,
                    )
                    view = await render_exercise_view(
                        target_user_id, day, ue_id, get_flex_selected(context, day, ue_id), prefs=prefs
                    )
                    set_flex_selected(context, day, ue_id, view.selected_set)
                    base = await get_baseline(target_user_id, day, view.exercise_id)
                    prog_lines = []
                    if base:
                        prog_lines.append(
                            f"Базовое: {format_sets_value(base[0], base[1], base[2], base[3], view.with_weight, view.kind)}"
                        )
                    for date_text, s, r, sec, w, details in rows:
                        sets_cnt = s or 0
                        reps_cnt = r or 0
                        seconds_cnt = sec or 0
                        weight_val = w or 0.0
                        label = format_progress_date(date_text)
                        if details:
                            detail_text = format_progress_sets_details(
                                details, view.with_weight, view.kind
                            )
                        else:
                            detail_text = format_sets_value(
                                sets_cnt,
                                reps_cnt,
                                seconds_cnt,
                                weight_val,
                                view.with_weight,
                                view.kind,
                            )
                        prog_lines.append(f"{label}: {detail_text}")
                    if prog_lines:
                        header = "Прогресс"
                        if total_pages > 1:
                            header += f" (страница {page + 1}/{total_pages})"
                        text = view.text + "\n\n" + header + ":\n" + "\n".join(prog_lines)
                    else:
                        text = view.text + "\n\nПрогресс: нет данных"
                    base_markup = build_exercise_actions_markup(
                        view,
                        day=day,
                        ue_id=ue_id,
                        group=view.group,
                        prefs=prefs,
                        is_library=is_library,
                        context=context,
                    )
                    base_rows = [row[:] for row in base_markup.inline_keyboard]
                    nav_rows: list[list[InlineKeyboardButton]] = []
                    if total_entries > PROGRESS_PAGE_SIZE:
                        nav_row: list[InlineKeyboardButton] = []
                        if page > 0:
                            nav_row.append(
                                InlineKeyboardButton(
                                    "⬅︎ Раньше",
                                    callback_data=f"ex:progress:{day}:{ue_id}:{page - 1}",
                                )
                            )
                        if (page + 1) * PROGRESS_PAGE_SIZE < total_entries:
                            nav_row.append(
                                InlineKeyboardButton(
                                    "Позже ➡︎",
                                    callback_data=f"ex:progress:{day}:{ue_id}:{page + 1}",
                                )
                            )
                        if nav_row:
                            nav_rows.append(nav_row)
                    if nav_rows:
                        kb = InlineKeyboardMarkup(nav_rows + base_rows)
                    else:
                        kb = InlineKeyboardMarkup(base_rows)
                    await show_screen(q, context, text, kb, target_user_id)
                    return
                elif action == "timeedit":
                    ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                    if resolve_group(ex_name, ex_group) != "metcon" or ex_name != FOR_TIME_EXERCISE_NAME:
                        await q.answer()
                        return
                    rows = await fetch_measurement_history(target_user_id, FOR_TIME_METRIC, limit=1)
                    if not rows:
                        await q.answer("Нет данных для изменения.", show_alert=True)
                        return
                    state = {
                        "day": day,
                        "ue_id": ue_id,
                        "chat_id": q.message.chat_id,
                        "message_id": q.message.message_id,
                        "mode": "edit",
                        "is_library": is_library,
                    }
                    back_target = f"ex:progress:{day}:{ue_id}"
                    if sheet_context and not is_library:
                        state["sheet"] = {
                            "day": sheet_day if sheet_day is not None else day,
                            "page": sheet_page,
                        }
                        back_target = f"day:open:{sheet_day if sheet_day is not None else day}"
                        clear_sheet_context(context, q.message.chat_id, q.message.message_id)
                    context.user_data[FOR_TIME_INPUT_KEY] = state
                    kb = InlineKeyboardMarkup(
                        [[InlineKeyboardButton(t("BACK"), callback_data=back_target)]]
                    )
                    await show_screen(q, context, 'Укажи новое время в формате ММ:СС или ЧЧ:ММ:СС.', kb, target_user_id)
                    return
                elif action == "timedel":
                    ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                    if resolve_group(ex_name, ex_group) != "metcon" or ex_name != FOR_TIME_EXERCISE_NAME:
                        await q.answer()
                        return
                    removed = await delete_last_measurement(target_user_id, FOR_TIME_METRIC)
                    if not removed:
                        await q.answer("Нет данных для удаления.", show_alert=True)
                        return
                    back_cb = None
                    if sheet_context and not is_library:
                        back_cb = f"day:open:{sheet_day if sheet_day is not None else day}"
                    text, kb = await build_for_time_history_view(target_user_id, day, ue_id, back_cb, prefs=prefs)
                    if sheet_context and not is_library and back_cb:
                        set_sheet_context(
                            context,
                            q.message.chat_id,
                            q.message.message_id,
                            sheet_day if sheet_day is not None else day,
                            sheet_page,
                        )
                    await show_screen(q, context, text, kb, target_user_id)
                    return
        if parts[0] != 'ex':
            await q.answer('Эта кнопка устарела. Откройте меню заново.', show_alert=True)
            return
        view = await render_exercise_view(
            target_user_id, day, ue_id, get_flex_selected(context, day, ue_id), prefs=prefs
        )
        set_flex_selected(context, day, ue_id, view.selected_set)
        kb = build_exercise_actions_markup(
            view,
            day=day,
            ue_id=ue_id,
            group=view.group,
            prefs=prefs,
            is_library=is_library,
            context=context,
        )
        await show_screen(q, context, view.text, kb, target_user_id)
        return
    except (IndexError, ValueError, KeyError, OverflowError) as exc:
        logger.warning("Malformed callback payload in menu_router: %s", exc)
        if q is not None and target_user_id is not None:
            with contextlib.suppress(TelegramError):
                text, kb, _ = await compose_main_menu(target_user_id)
                await show_screen(q, context, text, kb, target_user_id)
        return
    finally:
        message = getattr(q, "message", None) if q is not None else None
        if message:
            chat = getattr(message, "chat", None)
            chat_id = getattr(chat, "id", None) if chat else getattr(message, "chat_id", None)
            remember_message(chat_id, getattr(message, "message_id", None))


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтвердить только сохранённый неоплаченный счёт с той же суммой."""
    query = update.pre_checkout_query
    if not query:
        return
    valid = False
    try:
        payload = str(query.invoice_payload or '')
        parts = payload.split(':')
        if len(parts) >= 3 and parts[0] in {'sub', 'setsubstars', 'websub'} and parts[2] in SUBSCRIPTION_PLANS:
            owner = int(parts[1])
            if parts[0] == 'sub':
                user_info = await find_user_by_tg_id(owner)
                owner = user_info[0] if user_info else None
            invoice = await get_payment_by_external_id(payload)
            if invoice:
                metadata = invoice.get('payload') or {}
                valid = (
                    owner == invoice['user_id']
                    and invoice['provider'] == 'telegram'
                    and invoice['status'] == 'pending'
                    and not invoice.get('finalized_at')
                    and isinstance(metadata, dict)
                    and metadata.get('plan', metadata.get('plan_code')) == parts[2]
                    and invoice['currency'] == query.currency
                    and int(invoice['amount']) == query.total_amount
                    and query.total_amount > 0
                )
    except (TypeError, ValueError, KeyError):
        valid = False
    except Exception:
        logger.exception('Failed to validate Telegram pre-checkout')
    if valid:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message='Не удалось подтвердить счёт. Откройте подписку и создайте новый счёт.')


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь оплатил — активируем подписку и помечаем платёж как paid."""

    payment = update.message.successful_payment
    payload = payment.invoice_payload

    parts = payload.split(":")
    if len(parts) < 3:
        return

    prefix = parts[0]
    if prefix not in {"sub", "setsubstars", "websub"}:
        return

    user_id_str = parts[1]
    plan_code = parts[2]

    try:
        parsed_user_id = int(user_id_str)
    except (TypeError, ValueError):
        return
    if prefix == "sub":
        tg_user_id = parsed_user_id
        user_info = await find_user_by_tg_id(tg_user_id)
        if not user_info:
            return
        user_id = user_info[0]
    else:
        user_id = parsed_user_id

    plan = SUBSCRIPTION_PLANS.get(plan_code)
    if not plan:
        return

    charge_id = str(payment.telegram_payment_charge_id or '').strip()
    if not charge_id:
        logger.error("Successful Telegram payment has no charge id")
        return
    external_id = f"telegram:{charge_id}"
    await create_payment_record(
        user_id=user_id, provider="telegram", amount=payment.total_amount,
        currency=payment.currency, status="paid", external_id=external_id,
        provider_charge_id=charge_id, project_key="telegram", deduplicate=True,
        payload={"invoice_payload": payload, "plan_code": plan_code},
    )
    result = await finalize_payment_subscription_idempotent(
        external_id=external_id, user_id=user_id, expected_project_key="telegram",
        days=plan["days"], plan_code=plan_code, source="telegram_successful_payment",
    )
    if not result.get("ok"):
        logger.error("Telegram payment finalization failed: %s", result.get("reason"))
        return
    await update_payment_status(
        payload,
        "paid_invoice",
        {"plan": plan_code, "charge_external_id": external_id, "paid_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "currency": payment.currency, "total_amount": payment.total_amount},
    )

    if result.get("already_finalized"):
        return

    await update.message.reply_text(
        f"✅ Оплата получена. Подписка активна на {plan['days']} дней."
    )


def main():
    logger.info("Starting Gym Diary bot")
    asyncio.run(init_db())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    defaults = Defaults(tzinfo=timezone.utc)
    app = (
        Application.builder()
        .token(TG_TOKEN)
        .concurrent_updates(True)
        .connection_pool_size(TG_POOL_SIZE)
        .rate_limiter(AIORateLimiter())
        .post_init(post_init)
        .defaults(defaults)
        .build()
    )
    app.job_queue.scheduler.add_listener(
        _on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_MISSED | EVENT_JOB_ERROR
    )
    from progressor_bot import install as install_progressor
    from settings import DB_PATH
    install_progressor(app, "gym", DB_PATH,render=_progressor_render,back_callback='back:main',notify=lambda uid,text,kb:_progressor_scheduled_send(app,uid,text,kb))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set_intro", cmd_set_intro))
    app.add_handler(CommandHandler("splash_reset", splash_reset))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler(("checkprems", "check_prems", "prems"), check_prems_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("admin_ai_pass", ai_pass_command))
    app.add_handler(CommandHandler(("grant", "grunt"), grant_command))
    app.add_handler(CommandHandler("degrant", degrant_command))
    app.add_handler(CommandHandler("teams_admin", teams_admin_command))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, capture_intro_video))
    app.add_handler(CallbackQueryHandler(on_subscription_menu, pattern="^menu:subscription$"))
    app.add_handler(CallbackQueryHandler(on_subscription_choose, pattern="^sub:"))
    app.add_handler(CallbackQueryHandler(on_subscription_back, pattern="^back:main$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(CallbackQueryHandler(menu_router))
    app.add_handler(MessageHandler(filters.PHOTO, photo_router))
    app.add_handler(MessageHandler(filters.Regex(re.compile(r"^\s*admin\s+ai\s+pass\s*$", re.IGNORECASE)) & (~filters.COMMAND), ai_pass_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_router))
    app.add_error_handler(on_error)
    app.run_polling()


if __name__ == "__main__":
    main()
