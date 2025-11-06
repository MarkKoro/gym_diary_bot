import asyncio
import logging
import math
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, UTC
from zoneinfo import ZoneInfo
from collections import defaultdict
from types import SimpleNamespace
import httpx
import re
from telegram import (
    Update,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    LabeledPrice,
)
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
)
from keyboards import (
    main_menu_kb,
    muscle_groups_kb,
    exercises_kb,
    baseline_kb,
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
    edit_day_select_kb,
    edit_day_mode_kb,
    edit_day_strength_kb,
    edit_day_special_kb,
    rename_day_kb,
    days_count_kb,
    confirm_day_group_delete_kb,
    confirm_settings_group_delete_kb,
    confirm_day_reset_kb,
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
    subscribe_channel_prompt_kb,
    trainee_trainer_settings_kb,
    week_count_kb,
    reminder_prompt_kb,
    trainer_manage_trainee_kb,
)
from settings import (
    TG_TOKEN,
    SUPPORT_DEEPLINK,
    TG_POOL_SIZE,
    JOIN_URL,
    ADMIN_IDS,
    YK_TOKEN,
    SUBSCRIPTION_CHAT,
)
from db import (
    init_db,
    connect_db,
    get_or_create_user,
    get_or_create_today_session,
    get_session_for_day,
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
    add_user_reminder,
    normalize_dow,
    get_user_timezone,
    list_user_reminders,
    clear_user_reminders,
    list_active_days,
    list_day_completions,
    get_last_completion_for_user,
    get_day_label,
    remove_user_exercise,
    clear_day_plan,
    get_exercise_info,
    get_baseline,
    fetch_exercise_sets,
    get_session_last_values,
    remove_last_set,
    mark_exercise_done,
    set_exercise_note,
    get_exercise_note,
    get_latest_completed_note,
    list_recent_progress,
    count_exercise_progress_entries,
    list_last_done_dates,
    rename_day,
    get_ui_preferences,
    set_ui_mode,
    set_ui_emoji_enabled,
    set_ui_verbose_level,
    fetch_last_session_sets,
    inc_specific_set,
    add_user_muscle_group,
    list_user_muscle_groups,
    remove_user_muscle_group,
    list_users_with_reminders,
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
    list_all_user_tg_ids,
    METCON_EXERCISE_NAMES,
    get_running_entry,
    update_running_entry,
    list_running_history,
    mark_running_entry_done,
    get_running_entry_by_id,
    add_custom_measurement,
    list_custom_measurements,
    cleanup_expired_subscriptions,
    get_custom_measurement,
    get_active_subscription,
    grant_subscription_days,
    create_payment_record,
    update_payment_status,
    get_payment_by_external_id,
    get_latest_pending_payment,
    list_broadcast_targets,
    find_user_by_tg_id,
    find_user_by_id,
    find_user_by_trainer_code,
    get_trainer_link,
    get_active_trainer_link_for_trainee,
    create_trainer_request,
    list_trainer_requests,
    list_trainer_trainees,
    update_trainer_link_status,
    update_trainer_link_permissions,
    update_trainer_label,
    increment_day_finish_total,
    get_subscription_prompt_total,
    set_subscription_prompt_total,
    get_latest_subscription,
)
from text_utils import normalize_whitespace
from ui_texts import t, e

user_locks = defaultdict(asyncio.Lock)
logger = logging.getLogger(__name__)
last_messages: dict[int, int] = {}
MAIL_RETURN_CALLBACK = "promo:return_menu"
PROGRESS_PAGE_SIZE = 5
DAY_SHEET_PAGE_SIZE = 6
SHEET_VIEWS_KEY = "day_sheet_views"
BROADCAST_STATE_KEY = "broadcast_state"
SUBSCRIPTION_PAYMENT_KEY = "subscription_payment"
EXERCISE_NOTE_INPUT_KEY = "awaiting_exercise_note"
YK_PROVIDER = "yookassa"

SUBSCRIPTION_PLANS = {
    "1m": {
        "title": "Подписка на 1 месяц",
        "months": 1,
        "days": 30,
        "amount_rub": 100,
    },
    "6m": {
        "title": "Подписка на 6 месяцев",
        "months": 6,
        "days": 180,
        "amount_rub": 600,
    },
    "12m": {
        "title": "Подписка на 12 месяцев",
        "months": 12,
        "days": 365,
        "amount_rub": 1000,
    },
}

DAY_COMPLETION_TTL = timedelta(hours=6)
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
TRAINER_LABEL_INPUT_KEY = "awaiting_trainer_label"
TRAINER_TRAINEE_LABEL_INPUT_KEY = "awaiting_trainee_label"
TRAINER_PENDING_OFFSET_KEY = "trainer_pending_offset"
TRAINER_ACCEPTED_OFFSET_KEY = "trainer_accepted_offset"
TRAINER_SETTINGS_MESSAGE_KEY = "trainer_settings_message"
TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY = "trainer_trainee_settings_message"
TRAINER_LIST_LIMIT = 8
TRAINER_MAX_TRAINEES = 10
RUNNING_GROUP = "run"
RUNNING_INPUT_KEY = "running_input"
RUNNING_HISTORY_PAGE_SIZE = 1

REMINDER_EDIT_POSITION_KEY = "reminder_edit_position"
REMINDER_EDIT_LABEL_KEY = "reminder_edit_label"
REMINDER_SELECTED_DOW_KEY = "reminder_selected_dow"
REMINDER_EDIT_DAY_INDEX_KEY = "reminder_edit_day_index"
REMINDER_TIME_PAGE_KEY = "reminder_time_page"

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


def _training_week_start(local_dt: datetime, first_dow: int):
    offset = (local_dt.weekday() - first_dow) % 7
    return local_dt.date() - timedelta(days=offset)


async def _get_primary_training_weekday(user_id: int) -> int | None:
    reminders = await list_user_reminders(user_id)
    first_configured: int | None = None
    for day_no, dow, _, _ in reminders:
        if dow is None:
            continue
        dow_value = int(dow)
        if day_no == 1:
            return dow_value
        if first_configured is None:
            first_configured = dow_value
    return first_configured


async def _should_clear_day_completions(
    user_id: int, latest: datetime | None
) -> bool:
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
    if now - latest >= DAY_COMPLETION_TTL:
        return True
    return now_local.date() != latest_local.date()


async def get_active_day_completions(user_id: int) -> set[int]:
    rows = await list_day_completions(user_id)
    parsed, latest = _parse_completion_rows(rows)
    if await _should_clear_day_completions(user_id, latest):
        await clear_day_completions(user_id)
        return set()
    return {day for day, _ in parsed}


async def record_day_completion(user_id: int, day_index: int) -> tuple[set[int], bool]:
    rows = await list_day_completions(user_id)
    parsed, latest = _parse_completion_rows(rows)
    now = datetime.now(UTC)
    if await _should_clear_day_completions(user_id, latest):
        await clear_day_completions(user_id)
        parsed = []
        already_tracked = False
    else:
        already_tracked = any(day == day_index for day, _ in parsed)
    await mark_day_completed(user_id, day_index, now.isoformat())
    current = {day for day, _ in parsed}
    current.add(day_index)
    return current, not already_tracked


def _resolve_subscription_chat() -> str | int | None:
    raw = (SUBSCRIPTION_CHAT or "").strip()
    if not raw:
        return None
    if raw.startswith("https://t.me/"):
        slug = raw.split("/")[-1].split("?", 1)[0]
        if slug:
            return slug if slug.startswith("@") else f"@{slug}"
    if raw.startswith("@"):
        return raw
    try:
        message = getattr(q, "message", None)
        chat = getattr(message, "chat", None) if message else None
        chat_id = getattr(chat, "id", None) if chat else getattr(message, "chat_id", None)
        onboarding = bool(context.user_data.get("wizard_onboarding"))
        return int(raw)
    except ValueError:
        return raw


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
    chat_id = _resolve_subscription_chat()
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


async def maybe_prompt_channel_support(
    q, context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> None:
    total = await increment_day_finish_total(user_id)
    prompt_total = await get_subscription_prompt_total(user_id)
    if total - prompt_total < 5:
        return
    active = await get_active_subscription(user_id)
    if active:
        await set_subscription_prompt_total(user_id, total)
        return
    tg_user = getattr(q, "from_user", None)
    tg_user_id = getattr(tg_user, "id", None)
    if tg_user_id is not None and await _is_user_subscribed_to_channel(context, tg_user_id):
        await set_subscription_prompt_total(user_id, total)
        return
    if not JOIN_URL:
        await set_subscription_prompt_total(user_id, total)
        return
    message = getattr(q, "message", None)
    chat_id = getattr(message, "chat_id", None)
    if chat_id is None:
        await set_subscription_prompt_total(user_id, total)
        return
    text = (
        "Мы видим, что дневник помогает — вы завершили уже {total} тренировочных дней!\n"
        "Пожалуйста, поддержите авторов: подпишитесь на наш канал. Там мы делимся новостями и другими нашими ботами — будем рады вашей поддержке!"
    ).format(total=total)
    markup = subscribe_channel_prompt_kb(JOIN_URL)
    try:
        sent = await context.bot.send_message(
            chat_id,
            text,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except TelegramError:
        await set_subscription_prompt_total(user_id, total)
        return
    remember_message(sent.chat_id, sent.message_id)
    await set_subscription_prompt_total(user_id, total)


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


def build_main_menu_text(prefs: UiPreferences) -> str:
    lines = [f"{t('MAIN_TITLE')}:", ""]
    lines.append("Выбирай тренировочный день или другой раздел, чтобы вести дневник.")
    if prefs.verbose_level:
        lines.append(
            "Ниже — подробное описание разделов с подсказками, как работать с упражнениями."
        )
    else:
        lines.append("Ниже — краткое напоминание о назначении каждого раздела.")
    lines.append("")
    lines.append("────────")
    lines.append("")
    if prefs.verbose_level:
        lines.append(
            "Дни тренировок — открой нужный день, чтобы отмечать подходы, настраивать упражнения и тут же видеть актуальный результат. Добавлять и убирать упражнения можно прямо из карточек."
        )
        lines.append("")
        lines.append(
            "Мои упражнения — личная библиотека с описаниями и историей. Здесь удобно уточнять технику, обновлять план и возвращаться к сохранённым схемам."
        )
        lines.append("")
        lines.append(
            "Мои замеры — сохраняй динамику тела и контрольных показателей. Последние записи отображаются списком, чтобы видеть прогресс без лишних переходов."
        )
        lines.append("")
        lines.append(
            "Настройки — измени расписание, управление напоминаниями и выбери уровень пояснений. Все подсказки в интерфейсе синхронизируются с выбранным режимом."
        )
        lines.append("")
        lines.append(
            "Техподдержка — напиши, если что-то не работает или есть вопросы. Мы ответим прямо в чате и поможем настроить дневник."
        )
    else:
        lines.append("Дни тренировок — открой нужный, чтобы отметить подходы и увидеть прогресс.")
        lines.append("")
        lines.append("Мои упражнения — личная библиотека с описаниями и историей.")
        lines.append("")
        lines.append("Мои замеры — записывай изменения тела и контрольных показателей.")
        lines.append("")
        lines.append("Настройки — меняй расписание, напоминания и оформление.")
        lines.append("")
        lines.append("Техподдержка — быстро связаться с нами, если нужна помощь.")
    return "\n".join(lines)


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
        for day_no, dow, hour, minute in reminders
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
    reminders = await list_user_reminders(user_id)
    weekday_map = _build_day_weekday_map(raw_days, reminders) if raw_days else {}
    days = [
        (day_index, _format_day_label(day_index, label, weekday_map.get(day_index)))
        for day_index, label in raw_days
    ]
    completions = await get_active_day_completions(user_id)
    text = build_main_menu_text(prefs)
    if include_subscription_notice:
        notice_lines = await build_subscription_notice(user_id)
        if notice_lines:
            text = "\n".join([text, "", *notice_lines])
    profile = await _fetch_trainer_profile(user_id)
    is_trainer = bool(profile and profile[0])
    kb = main_menu_kb(
        days,
        SUPPORT_DEEPLINK,
        completions,
        show_trainer=is_trainer,
        show_support=show_support,
        include_settings=include_settings,
        extra_rows=extra_rows,
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


def format_progress_sets_details(
    details: list[tuple[int, int, float]], with_weight: bool, kind: str
) -> str:
    if not details:
        return "—"
    enumerated = [
        (index + 1, reps, seconds, weight)
        for index, (reps, seconds, weight) in enumerate(details)
    ]
    grouped = _compress_flex_triplets(enumerated, with_weight=with_weight, kind=kind)
    parts: list[str] = []
    for entry in grouped:
        reps_value = int(entry["reps"])
        seconds_value = int(entry.get("seconds", 0))
        weight_value = float(entry["weight"])
        text = format_metric_value(reps_value, seconds_value, kind)
        if with_weight and weight_value > 0:
            text = f"{text} при {format_weight_value(weight_value)} кг"
        count = int(entry["count"])
        if count > 1:
            text = f"{count}× {text}"
        parts.append(text)
    return "; ".join(parts) if parts else "—"


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
        detailed = summarize_previous_sets(
            current_sets, with_weight=True, kind=kind
        )
        if detailed:
            return f"{t('MADE')} {detailed}"
        return f"{t('MADE')} {format_kb_done(current_sets, kind=kind)}"
    if last_sets:
        return f"{t('LAST_TIME')}: {format_kb_previous(last_sets, kind=kind)}"
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


def clamp_running_distance(value: float) -> float:
    return max(round(float(value), 2), 0.0)


def clamp_running_duration(value: int) -> int:
    return max(int(value), 0)


def clamp_running_calories(value: int) -> int:
    return max(int(value), 0)


def parse_distance_input(text: str) -> float:
    raw = text.strip().replace(",", ".")
    value = float(raw)
    return clamp_running_distance(value)


def parse_calories_input(text: str) -> int:
    raw = text.strip()
    value = int(float(raw.replace(",", ".")))
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
        return actor_user_id
    try:
        acting_id_int = int(acting_id)
    except (TypeError, ValueError):
        context.user_data.pop("acting_user_id", None)
        context.user_data.pop("acting_can_edit", None)
        return actor_user_id
    link = await get_trainer_link(actor_user_id, acting_id_int)
    if link and str(link[3]) == "accepted":
        context.user_data["acting_user_id"] = acting_id_int
        context.user_data["acting_can_edit"] = bool(link[4])
        return acting_id_int
    context.user_data.pop("acting_user_id", None)
    context.user_data.pop("acting_can_edit", None)
    return actor_user_id


async def _fetch_trainer_profile(user_id: int) -> tuple[int, str | None] | None:
    async with connect_db() as db:
        cur = await db.execute(
            "SELECT is_trainer, trainer_code FROM users WHERE id=?",
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    is_trainer = int(row[0] or 0)
    return is_trainer, row[1]


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
            "UPDATE users SET is_trainer = 1, trainer_code = ? WHERE id=?",
            (existing_code, user_id),
        )
        await db.commit()
    return existing_code


async def _render_trainer_link_message(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    target: tuple[int, int] | None,
    text: str,
    *,
    chat_id: int | None = None,
) -> tuple[int, int] | None:
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")]]
    )
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
    return message_chat_id, message_id


async def build_trainee_trainer_settings_view(
    trainee_user_id: int,
):
    link = await get_active_trainer_link_for_trainee(trainee_user_id)
    if not link:
        return None, None, None
    _link_id, trainer_user_id, status, can_edit_plan, trainer_label, _ = link
    trainer_name = (trainer_label or "").strip()
    if not trainer_name:
        trainer_name = await _format_trainer_user_display(trainer_user_id)
    status_map = {
        "pending": "Статус: заявка отправлена тренеру — ждём подтверждения.",
        "accepted": "Статус: связь активна. Тренер уже может видеть твой дневник.",
    }
    status_text = status_map.get(status, f"Статус: {status}.")
    can_edit = bool(can_edit_plan)
    permission_text = (
        "Разрешение: тренер может менять план тренировок."
        if can_edit
        else "Разрешение: тренеру запрещено менять план."
    )
    if status == "pending":
        body_hint = "Когда тренер подтвердит заявку, он появится в списке подопечных."
    else:
        body_hint = "Используй кнопки ниже, чтобы управлять правами или отключить связь."
    lines = [
        f"Тренер: {trainer_name}",
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
        "Используй кнопки ниже, чтобы управлять доступом и заметкой.",
    ]
    text = "\n".join(lines)
    kb = trainer_manage_trainee_kb(bool(can_edit_plan))
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
        context=context,
    )


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
) -> tuple[int, list, int, list]:
    safe_pending = max(0, pending_offset)
    safe_accepted = max(0, accepted_offset)
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
    return safe_pending, requests, safe_accepted, trainees


async def _render_trainer_overview(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    message: str | None = None,
    pending_offset: int | None = None,
    accepted_offset: int | None = None,
) -> None:
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
    pending_offset, requests, accepted_offset, trainees = await _load_trainer_lists(
        user_id, current_pending, current_accepted
    )
    context.user_data[TRAINER_PENDING_OFFSET_KEY] = pending_offset
    context.user_data[TRAINER_ACCEPTED_OFFSET_KEY] = accepted_offset
    pending_has_prev = pending_offset > 0
    accepted_has_prev = accepted_offset > 0
    pending_has_next = False
    accepted_has_next = False
    if len(requests) == TRAINER_LIST_LIMIT:
        more = await list_trainer_requests(
            user_id,
            limit=1,
            offset=pending_offset + TRAINER_LIST_LIMIT,
        )
        pending_has_next = bool(more)
    if len(trainees) == TRAINER_LIST_LIMIT:
        more = await list_trainer_trainees(
            user_id,
            limit=1,
            offset=accepted_offset + TRAINER_LIST_LIMIT,
        )
        accepted_has_next = bool(more)
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
    if trainees:
        trainee_ids = [int(entry[1]) for entry in trainees]
        completion_rows = await asyncio.gather(
            *(get_last_completion_for_user(uid) for uid in trainee_ids)
        )
        last_completion_map = dict(zip(trainee_ids, completion_rows))

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

    lines: list[str] = []
    if message:
        lines.extend([message, ""])
    lines.append("Заявки:")
    if requests:
        for entry in requests:
            trainee_id = int(entry[1])
            label = labels.get(trainee_id, f"ID {trainee_id}")
            lines.append(f"• {label}")
    else:
        lines.append("• Нет заявок.")
    lines.append("")
    lines.append("Подопечные:")
    if trainees:
        for entry in trainees:
            trainee_id = int(entry[1])
            label = labels.get(trainee_id, f"ID {trainee_id}")
            lines.append(f"• {label}")
            last_completion = last_completion_map.get(trainee_id)
            last_label = _format_last_completion(last_completion)
            lines.append(f"  последняя тренировка: {last_label}")
    else:
        lines.append("• Пока нет подопечных.")
    rows: list[list[InlineKeyboardButton]] = []
    for entry in requests:
        link_id = int(entry[0])
        rows.append(
            [
                InlineKeyboardButton(
                    "✅ Принять", callback_data=f"trainer:req:accept:{link_id}"
                ),
                InlineKeyboardButton(
                    "❌ Отклонить", callback_data=f"trainer:req:decline:{link_id}"
                ),
            ]
        )
    if pending_has_prev or pending_has_next:
        nav_row: list[InlineKeyboardButton] = []
        if pending_has_prev:
            nav_row.append(
                InlineKeyboardButton(
                    "⬅️ Предыдущие заявки", callback_data="trainer:list:pending:prev"
                )
            )
        if pending_has_next:
            nav_row.append(
                InlineKeyboardButton(
                    "Следующие заявки ➡️", callback_data="trainer:list:pending:next"
                )
            )
        if nav_row:
            rows.append(nav_row)
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
        if nav_row:
            rows.append(nav_row)
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:root")])
    kb = InlineKeyboardMarkup(rows)
    await show_screen(q, context, "\n".join(lines), kb, user_id)


def clear_linear_state(
    user_data: dict,
    preserve_keys: set[str] | None = None,
) -> None:
    preserved = preserve_keys or set()
    for key in list(user_data.keys()):
        if key.startswith("awaiting_") and key not in preserved:
            user_data.pop(key, None)
    linear_keys = {"add_group", BROADCAST_STATE_KEY}
    for key in linear_keys:
        if key in preserved:
            continue
        user_data.pop(key, None)


async def send_main_message(
    bot,
    chat_id: int | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    **kwargs,
) -> Message:
    if chat_id is None:
        raise ValueError("chat_id is required to send a message")
    previous_id = last_messages.get(chat_id)
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
):
    message = getattr(q, "message", None)
    chat = getattr(message, "chat", None) if message else None
    chat_id = getattr(chat, "id", None) if chat else getattr(message, "chat_id", None)
    message_id = getattr(message, "message_id", None)
    try:
        await q.edit_message_text(text, reply_markup=reply_markup)
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
                )
            else:
                new_message = await context.bot.send_message(
                    chat_id,
                    text,
                    reply_markup=reply_markup,
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
                )
            else:
                new_message = await context.bot.send_message(
                    chat_id,
                    text,
                    reply_markup=reply_markup,
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
) -> None:
    prefs = await load_ui_preferences(user_id)
    prepared_text, prepared_markup = prepare_ui_output(text, reply_markup, prefs)
    remember = not context.user_data.get("wizard_onboarding")
    return await safe_update_screen(
        q, context, prepared_text, prepared_markup, remember=remember
    )


def wizard_day_mode_text(day: int, prefs: UiPreferences) -> str:
    base = f"День {day}. Выбери тип тренировки."
    if prefs.verbose_level:
        return (
            f"{base}\nОриентируйся на цели дня: выбери направление, затем подберёшь упражнения"
            " с подходящими подсказками."
        )
    return base


def wizard_day_mode_kb(day: int) -> InlineKeyboardMarkup:
    base = edit_day_mode_kb(day)
    rows: list[list[InlineKeyboardButton]] = []
    prefix = f"set:edit_day:{day}:"
    for row in base.inline_keyboard:
        new_row: list[InlineKeyboardButton] = []
        for button in row:
            data = button.callback_data or ""
            if data.startswith(prefix):
                mode = data.split(":")[-1]
                new_row.append(
                    InlineKeyboardButton(
                        text=button.text, callback_data=f"wiz:daymode:{day}:{mode}"
                    )
                )
            elif data == "set:edit_day":
                continue
            else:
                new_row.append(
                    InlineKeyboardButton(
                        text=button.text,
                        callback_data=button.callback_data,
                        url=button.url,
                        switch_inline_query=button.switch_inline_query,
                        switch_inline_query_current_chat=button.switch_inline_query_current_chat,
                        login_url=button.login_url,
                        callback_game=button.callback_game,
                        pay=button.pay,
                        web_app=button.web_app,
                    )
                )
        if new_row:
            rows.append(new_row)
    return InlineKeyboardMarkup(rows)


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
    for ue_id, name, group, done, ex_id in ex_rows:
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
    sets: list[dict[str, float]] = field(default_factory=list)
    pointer: int = 0
    default_reps: int = 0
    default_seconds: int = 0
    default_weight: float = 0.0
    first_time: bool = False


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
    name, default_group = row
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
    if state.with_weight:
        weight_steps = (
            [0.5, 1, 3, 5, 10, 25, 50]
            if state.first_time
            else [0.5, 3, 10]
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
    )
    await show_screen(q, context, view.text, kb, user_id)


async def apply_fill_changes(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    state: FillEditorState,
    prefs: UiPreferences,
):
    today_str = await get_user_local_date(user_id)
    session_id = await get_or_create_today_session(user_id, today_str, state.day)
    template = [
        (
            max(_safe_int(item.get("reps")), 0),
            max(_safe_int(item.get("seconds")), 0),
            max(_safe_float(item.get("weight")), 0.0) if state.with_weight else 0.0,
        )
        for item in state.sets
    ]
    await apply_sets_template(session_id, state.ue_id, template)
    if template:
        sets = await fetch_exercise_sets(session_id, state.ue_id)
        if sets:
            target_index = min(state.pointer, len(sets) - 1)
            set_flex_selected(context, state.day, state.ue_id, sets[target_index][0])
        else:
            set_flex_selected(context, state.day, state.ue_id, None)
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

    sets_payload: list[dict[str, float]] = [
        {
            "reps": max(_safe_int(reps), 0),
            "seconds": max(_safe_int(seconds), 0),
            "weight": max(_safe_float(weight), 0.0) if weight_enabled else 0.0,
        }
        for _, reps, seconds, weight in work_sets
    ]
    if not sets_payload:
        if baseline and baseline[0] > 0:
            sets_payload = [
                {
                    "reps": max(_safe_int(baseline[1]), 0),
                    "seconds": max(_safe_int(baseline[2]), 0),
                    "weight": max(_safe_float(baseline[3]), 0.0)
                    if weight_enabled
                    else 0.0,
                }
                for _ in range(baseline[0])
            ]
        elif default_reps or default_weight:
            sets_payload = [
                {
                    "reps": default_reps,
                    "seconds": default_seconds,
                    "weight": default_weight if weight_enabled else 0.0,
                }
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
    mode = parts[1]
    if mode != "flex":
        await q.answer()
        return
    action = parts[2]
    if action == "nav" and len(parts) >= 4 and state.sets:
        delta = int(parts[3])
        state.pointer = max(0, min(state.pointer + delta, len(state.sets) - 1))
    elif action == "add":
        base_reps = (
            _safe_int(state.sets[state.pointer]["reps"])
            if state.sets
            else state.default_reps
        )
        base_seconds = (
            _safe_int(state.sets[state.pointer].get("seconds", state.default_seconds))
            if state.sets
            else state.default_seconds
        )
        base_weight = (
            _safe_float(state.sets[state.pointer]["weight"])
            if state.sets
            else state.default_weight
        )
        insert_at = state.pointer + 1 if state.sets else 0
        state.sets.insert(
            insert_at,
            {
                "reps": max(_safe_int(base_reps), 0),
                "seconds": max(_safe_int(base_seconds), 0),
                "weight": max(_safe_float(base_weight), 0.0)
                if state.with_weight
                else 0.0,
            },
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
                {
                    "reps": max(_safe_int(state.default_reps), 0),
                    "seconds": max(_safe_int(state.default_seconds), 0),
                    "weight": max(_safe_float(state.default_weight), 0.0)
                    if state.with_weight
                    else 0.0,
                }
            )
            state.pointer = 0
        current = state.sets[state.pointer]
        if target == "reps":
            current_reps = _safe_int(current.get("reps"))
            current["reps"] = max(0, current_reps + int(delta))
        elif target == "sec":
            current_seconds = _safe_int(current.get("seconds"))
            current["seconds"] = max(0, current_seconds + int(delta))
        elif target == "kg" and state.with_weight:
            current_weight = _safe_float(current.get("weight"))
            current["weight"] = max(0.0, current_weight + delta)
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

MEASUREMENT_CUSTOM_CATEGORY = {
    "code": "custom",
    "letter": "E",
    "name": "Свои замеры",
}
CUSTOM_MEASUREMENT_REGISTRY: dict[str, dict] = {}

MEASUREMENT_CATEGORIES = [
    {"code": "body", "letter": "A", "name": "Масса/состав тела"},
    {"code": "circumference", "letter": "B", "name": "Окружности"},
    {"code": "records", "letter": "C", "name": "Производные/силовые контрольные"},
    {"code": "vitals", "letter": "D", "name": "Витальные показатели"},
]

FEATURED_MEASUREMENTS = {"body_weight", "body_fat", "chest", "hips"}


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
            prompt = f"Введи значение (например: 10)."
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


def clear_custom_measurement_registry(user_id: int):
    prefix = f"uc{user_id}_"
    to_remove = [code for code in CUSTOM_MEASUREMENT_REGISTRY.keys() if code.startswith(prefix)]
    for code in to_remove:
        CUSTOM_MEASUREMENT_REGISTRY.pop(code, None)
        MEASUREMENT_MAP.pop(code, None)


async def load_custom_measurements(
    user_id: int, context: ContextTypes.DEFAULT_TYPE
) -> list[dict]:
    rows = await list_custom_measurements(user_id)
    clear_custom_measurement_registry(user_id)
    items: list[dict] = []
    for code, name, category_code in rows:
        category = (category_code or "").strip() or MEASUREMENT_CUSTOM_CATEGORY["code"]
        item = {
            "code": code,
            "name": name,
            "category": category,
            "unit": "",
            "precision": 1,
            "optional": False,
            "prompt": f"Введи значение для «{name}» (например: 10).",
        }
        items.append(item)
        CUSTOM_MEASUREMENT_REGISTRY[code] = item
        MEASUREMENT_MAP[code] = item
    context.user_data[MEASUREMENT_CUSTOM_CACHE_KEY] = items
    return items


def get_cached_custom_measurements(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
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
        item = get_measurement_item(code)
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
    item = MEASUREMENT_MAP.get(code)
    if item:
        return item
    return CUSTOM_MEASUREMENT_REGISTRY.get(code)


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
    cache_key = f"{code}:{limit}"
    if cache_key in cache:
        return cache[cache_key]
    item = get_measurement_item(code)
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
        syst = int(round(float(parts[0])))
        diast = int(round(float(parts[1])))
        return float(syst), str(diast)
    value = float(raw)
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
    extra_lines: list[str] = []
    if last_done:
        details.append(last_done)
    if summary:
        summary_lines = str(summary).splitlines()
        if summary_lines:
            details.append(summary_lines[0])
            if len(summary_lines) > 1:
                extra_lines.extend(summary_lines[1:])
    prefix = f"{mark} " if mark else ""
    base = f"{prefix}{name}".strip()
    if details:
        base = f"{base} — {' — '.join(details)}"
    lines = [base.strip()]
    for line in extra_lines:
        lines.append(f"   {line}")
    return "\n".join(lines)


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
    ex_rows = await fetch_day_exercises(user_id, day_index, date_str)
    session_id = await get_session_for_day(user_id, date_str, day_index)
    last_done_map = build_last_done_dict(await list_last_done_dates(user_id))
    data: list[dict] = []
    for_time_loaded = False
    last_for_time: int | None = None
    for ue_id, name, group, done_flag, ex_id in ex_rows:
        resolved_group = resolve_group(name, group)
        with_weight, kind = get_display_flags(resolved_group, name)
        weight_enabled = with_weight or resolved_group in {"workout", "core"}
        baseline = await get_baseline(user_id, day_index, ex_id)
        today_sets_full = []
        if session_id:
            today_sets_full = await fetch_exercise_sets(session_id, ue_id)
        current_note = await get_exercise_note(session_id, ue_id) if session_id else None
        _, prev_note_val = await get_latest_completed_note(
            user_id, ex_id, exclude_session_id=session_id
        )
        previous_note = prev_note_val if prev_note_val else None
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
            if session_id is not None:
                running_entry = await get_running_entry(
                    user_id,
                    ue_id,
                    session_id=session_id,
                    day_index=day_index,
                    create=False,
                )
            if running_entry:
                _, dist, duration, calories, is_draft, created_at = running_entry
                distance_value = float(dist or 0.0)
                duration_value = int(duration or 0)
                calories_value = int(calories or 0)
            else:
                distance_value = 0.0
                duration_value = 0
                calories_value = 0
            entry["running_summary"] = {
                "distance": distance_value,
                "duration": duration_value,
                "calories": calories_value,
            }
            history_rows = await list_running_history(user_id, ue_id, limit=2)
            prev_entry = None
            if history_rows:
                if running_entry and history_rows[0][0] == running_entry[0]:
                    if len(history_rows) > 1:
                        prev_entry = history_rows[1]
                else:
                    prev_entry = history_rows[0]
            if prev_entry:
                _, prev_distance, prev_duration, prev_calories, prev_created, _ = prev_entry
                entry["prev_summary"] = format_running_line(
                    float(prev_distance or 0.0),
                    int(prev_duration or 0),
                    int(prev_calories or 0),
                )
                entry["prev_date"] = prev_created
            entry["has_history"] = bool(history_rows)
        else:
            summary = build_strength_summary_from_sets(today_sets_full)
            summary["kind"] = kind
            entry["today_summary"] = summary
            if resolved_group == "kb":
                entry["prev_summary"] = format_kb_previous(last_sets, kind=kind)
            else:
                entry["prev_summary"] = summarize_previous_sets(
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
                for step in (0.5, 3.0, 10.0):
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
    ex_rows = await fetch_day_exercises(user_id, day, today_str)
    custom = await get_custom_groups(user_id, context)
    summaries = await build_summary_map(user_id, day, ex_rows, today_str)
    last_done_rows = await list_last_done_dates(user_id)
    last_done_map = build_last_done_dict(last_done_rows)
    text = render_day_text(
        day,
        label,
        ex_rows,
        custom,
        summaries,
        last_done_map,
        prefs,
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
    grouped = _compress_flex_entries(sets, with_weight=with_weight, kind=kind)
    for entry in grouped:
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
    grouped = _compress_flex_triplets(work_sets, with_weight=with_weight, kind=kind)
    for entry in grouped:
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
    session_id = await get_session_for_day(user_id, today, day)
    for ue_id, name, group, _, ex_id in ex_rows:
        resolved = resolve_group(name, group)
        with_weight, kind = get_display_flags(resolved, name)
        weight_enabled = with_weight or resolved in {"workout", "core"}
        current_sets_full: list[tuple[int, int, int, float, int]] = []
        if session_id:
            current_sets_full = await fetch_exercise_sets(session_id, ue_id)
        current_note = await get_exercise_note(session_id, ue_id) if session_id else None
        _, prev_note_val = await get_latest_completed_note(
            user_id, ex_id, exclude_session_id=session_id
        )
        previous_note = prev_note_val if prev_note_val else None
        baseline = await get_baseline(user_id, day, ex_id)
        last_label = ""
        if resolved == "kb":
            work_sets = filter_work_sets(current_sets_full)
            if work_sets:
                last_label = format_kb_previous(work_sets, kind=kind)
            else:
                last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
                if last_sets:
                    last_label = format_kb_previous(last_sets, kind=kind)
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
            if running_entry and not int(running_entry[4] or 0):
                distance_value = float(running_entry[1] or 0.0)
                duration_value = int(running_entry[2] or 0)
                calories_value = int(running_entry[3] or 0)
                if distance_value or duration_value or calories_value:
                    last_label = format_running_line(
                        distance_value, duration_value, calories_value
                    )
            if not last_label:
                history_rows = await list_running_history(user_id, ue_id, limit=1)
                if history_rows:
                    _, dist, dur, cal, _created_at, _ = history_rows[0]
                    last_label = format_running_line(
                        float(dist or 0.0), int(dur or 0), int(cal or 0)
                    )
        else:
            work_sets = filter_work_sets(current_sets_full)
            if work_sets:
                last_label = summarize_previous_sets(
                    work_sets, with_weight=weight_enabled, kind=kind
                )
            if not last_label:
                last_sets = await fetch_last_session_sets(
                    user_id, day, ue_id, today
                )
                last_label = summarize_previous_sets(
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
    ex_rows = await fetch_day_exercises(user_id, day, today_str)
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
    for ue_id, name, g, done, ex_id in ex_rows:
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
    session_id = await get_session_for_day(user_id, today, 0)
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
        current_note = await get_exercise_note(session_id, ue_id) if session_id else None
        _, prev_note_val = await get_latest_completed_note(
            user_id, ex_id, exclude_session_id=session_id
        )
        note_lines = build_note_lines(current_note, prev_note_val)
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
    ex_id, name, raw_group = await get_exercise_info(ue_id)
    group = resolve_group(name, raw_group)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    session_id = await get_or_create_today_session(user_id, today, day)
    sets = await fetch_exercise_sets(session_id, ue_id)
    baseline = await get_baseline(user_id, day, ex_id)
    last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
    prefs = prefs or await load_ui_preferences(user_id)
    with_weight, kind = get_display_flags(group, name)
    weight_enabled = with_weight or group in {"workout", "core"}
    current_note = await get_exercise_note(session_id, ue_id)
    prev_session_id, prev_note_value = await get_latest_completed_note(
        user_id, ex_id, exclude_session_id=session_id
    )
    previous_note = prev_note_value if prev_note_value else None
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
        prev_text = format_kb_previous(last_sets, kind=kind) or t("NOT_FIXED")
        if prev_text == "—":
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
            create=True,
        )
        entry_id, dist, duration, calories, draft_flag, created_at = running_entry
        distance_value = float(dist or 0.0)
        duration_value = int(duration or 0)
        calories_value = int(calories or 0)
        current_line = format_running_line(distance_value, duration_value, calories_value)
        history_rows = await list_running_history(user_id, ue_id, limit=2)
        prev_text = t("NOT_FIXED")
        prev_created_at = None
        if history_rows:
            candidate = history_rows[0]
            if candidate[0] == entry_id and len(history_rows) > 1:
                candidate = history_rows[1]
            if candidate[0] != entry_id:
                _, prev_distance, prev_duration, prev_calories, prev_created, _ = candidate
                prev_text = format_running_line(
                    float(prev_distance or 0.0),
                    int(prev_duration or 0),
                    int(prev_calories or 0),
                )
                prev_created_at = prev_created
        plan_text = t("NOT_SET")
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
        prev_text = summarize_previous_sets(
            last_sets, with_weight=weight_enabled, kind=kind
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
    _, name, _ = await get_exercise_info(ue_id)
    entries = await list_running_history(user_id, ue_id, limit=20)
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
    _, distance, duration, calories, created_at, entry_day = entries[safe_index]
    timestamp = format_measurement_timestamp(created_at, zone)
    summary = format_running_line(
        float(distance or 0.0), int(duration or 0), int(calories or 0)
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

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    user_id = None
    if context.job.data and isinstance(context.job.data, dict):
        user_id = context.job.data.get("user_id")
    try:
        reply_markup = None
        cheer = ""
        if user_id:
            completions = await get_active_day_completions(user_id)
            _text, reply_markup, _ = await compose_main_menu(user_id)
            cheer = format_reminder_cheer(len(completions))
        text = (
            "Напоминание о тренировке!\n"
            "Открой нужный день и отметь новые подходы, чтобы сохранить прогресс."
        )
        if cheer:
            text = f"{text}\n{cheer}"
        await send_main_message_fresh(
            context.bot,
            chat_id,
            text,
            reply_markup=reply_markup,
        )
    except Forbidden:
        try:
            context.job.schedule_removal()
        except Exception:
            pass
    except Exception:
        logger.exception("Reminder job failed")


def _remove_reminder_jobs(job_queue, user_id: int, day_no: int, dow: int | None = None) -> None:
    def _safe_remove(job) -> None:
        try:
            job.schedule_removal()
        except Exception:
            pass

    job_prefix = f"rem_{user_id}_{day_no}_"
    try:
        jobs = job_queue.jobs()
    except AttributeError:
        jobs = []
    for job in jobs:
        name = getattr(job, "name", None)
        if name and name.startswith(job_prefix):
            _safe_remove(job)
    if dow is not None:
        job_name = f"rem_{user_id}_{day_no}_{dow}"
        for job in job_queue.get_jobs_by_name(job_name):
            _safe_remove(job)
    legacy_names = [f"rem_{user_id}_{day_no}"]
    if dow is not None:
        legacy_names.append(f"rem_{user_id}_{dow}")
    for legacy_name in legacy_names:
        for job in job_queue.get_jobs_by_name(legacy_name):
            _safe_remove(job)


async def schedule_all_reminders(app: Application):
    raw_rows = await list_users_with_reminders()
    users: dict[int, dict[str, int | None]] = {}
    for user_id, tg_id, _day_no, _dow, _hour, _minute in raw_rows:
        info = users.setdefault(int(user_id), {"tg_id": None})
        if tg_id is not None:
            try:
                info["tg_id"] = int(tg_id)
            except (TypeError, ValueError):
                info["tg_id"] = None
    desired_jobs: set[str] = set()
    total_scheduled = 0
    for user_id, info in users.items():
        reminders = await list_user_reminders(user_id)
        if not reminders:
            logger.info("Scheduled 0 reminders for user %d", user_id)
            continue
        tz_code = await get_user_timezone(user_id)
        zone = resolve_user_zone(tz_code)
        tg_id = info.get("tg_id")
        user_scheduled = 0
        for day_no, dow, hour, minute in reminders:
            if dow is None:
                continue
            try:
                day_int = int(day_no)
                hour_int = int(hour)
                minute_int = int(minute)
            except (TypeError, ValueError):
                continue
            dow_int = normalize_dow(dow)
            job_name = f"rem_{user_id}_{day_int}_{dow_int}"
            _remove_reminder_jobs(app.job_queue, user_id, day_int, dow_int)
            if tg_id is None:
                continue
            desired_jobs.add(job_name)
            tm = time(hour=hour_int, minute=minute_int, tzinfo=zone)
            app.job_queue.run_daily(
                reminder_job,
                tm,
                days=(dow_int,),
                chat_id=tg_id,
                name=job_name,
                data={"user_id": user_id, "day_no": day_int, "dow": dow_int},
            )
            user_scheduled += 1
            total_scheduled += 1
        logger.info("Scheduled %d reminders for user %d", user_scheduled, user_id)
    logger.info("Scheduled %d reminder jobs in total", total_scheduled)
    # remove orphaned reminder jobs that are no longer present in the database
    try:
        jobs = app.job_queue.jobs()
    except AttributeError:
        jobs = []
    for job in jobs:
        name = getattr(job, "name", None)
        if not name:
            continue
        if name.startswith("rem_") and name not in desired_jobs:
            try:
                job.schedule_removal()
            except Exception:
                continue


async def post_init(app: Application):
    await schedule_all_reminders(app)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    u = update.effective_user
    user_id = await get_or_create_user(u.id, u.username)
    settings = await fetch_user_settings(user_id)
    prefs = await load_ui_preferences(user_id)
    if not settings or not settings[1]:
        prompt = "Сколько тренировок в неделю?"
        kb = week_count_kb()
        prompt_text, prompt_kb = prepare_ui_output(prompt, kb, prefs)
        chat = update.effective_chat
        context.user_data["wizard_onboarding"] = True
        if chat is not None:
            await context.bot.send_message(chat.id, prompt_text, reply_markup=prompt_kb)
        elif update.message:
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
        await execute_broadcast(q, context, state)
        return


def build_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("1 месяц — 100 ₽", callback_data="sub:1m")],
            [InlineKeyboardButton("6 месяцев — 600 ₽", callback_data="sub:6m")],
            [InlineKeyboardButton("12 месяцев — 1000 ₽", callback_data="sub:12m")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back:main")],
        ]
    )


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
    """Пользователь выбрал конкретный план — шлём инвойс через Telegram."""

    query = update.callback_query
    await query.answer()

    data = query.data
    _, plan_code = data.split(":", 1)
    plan = SUBSCRIPTION_PLANS.get(plan_code)
    if not plan:
        await query.edit_message_text("Неизвестный тариф. Попробуйте ещё раз.")
        return

    user = update.effective_user
    db_user_id = await get_or_create_user(user.id, user.username)
    title = plan["title"]
    payload = f"sub:{user.id}:{plan_code}"
    currency = "RUB"
    price_rub = plan["amount_rub"]
    prices = [LabeledPrice(label=title, amount=price_rub * 100)]

    await create_payment_record(
        user_id=db_user_id,
        provider="telegram",
        amount=price_rub * 100,
        currency=currency,
        status="pending",
        payload={"plan": plan_code},
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
        description="Оплата подписки в gym_diary_bot",
        provider_token=YK_TOKEN,
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


async def show_subscription_overview(
    q, context: ContextTypes.DEFAULT_TYPE, user_id: int
):
    await cleanup_expired_subscriptions(user_id)
    active = await get_active_subscription(user_id)
    pending = await get_latest_pending_payment(user_id)
    tz_code = await get_user_timezone(user_id)
    zone = resolve_user_zone(tz_code)
    lines = [
        "Подписка донат отключает рекламные рассылки и помогает развивать бота.",
        "",
    ]
    if active and active.get("expires_at"):
        expires_at = active["expires_at"]
        expires_label = expires_at.astimezone(zone).strftime("%d.%m.%Y")
        lines.append(f"Активна до {expires_label}.")
    else:
        lines.append("Подписка не оформлена.")
    if pending:
        payload = pending.get("payload") or {}
        plan_code = payload.get("plan")
        plan_label = SUBSCRIPTION_PLANS.get(plan_code, {}).get("title")
        amount_val = pending.get("amount") or 0
        amount_rub = amount_val / 100 if amount_val else 0
        lines.append("")
        if plan_label and amount_rub:
            lines.append(
                f"Есть неоплаченный счёт: {plan_label} за {int(amount_rub)} ₽."
            )
        else:
            lines.append("Есть неоплаченный счёт — можно проверить оплату ниже.")
    if YK_TOKEN:
        lines.append("")
        lines.append(
            "После оплаты вернись и нажми «Проверить оплату», чтобы активировать подписку."
        )
    else:
        lines.append("")
        lines.append("Приём платежей временно недоступен.")
    rows: list[list[InlineKeyboardButton]] = []
    if YK_TOKEN:
        for code, plan in SUBSCRIPTION_PLANS.items():
            label = f"{plan['title']} — {plan['amount_rub']} ₽"
            rows.append(
                [InlineKeyboardButton(label, callback_data=f"set:subscription:plan:{code}")]
            )
    if pending:
        rows.append(
            [
                InlineKeyboardButton(
                    "🔄 Проверить оплату",
                    callback_data=f"set:subscription:check:{pending['external_id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")])
    kb = InlineKeyboardMarkup(rows)
    await show_screen(q, context, "\n".join(lines), kb, user_id)


async def start_subscription_payment(
    q, context: ContextTypes.DEFAULT_TYPE, user_id: int, plan_code: str
):
    plan = SUBSCRIPTION_PLANS.get(plan_code)
    if not plan:
        await q.answer("Тариф не найден.", show_alert=True)
        return
    if not YK_TOKEN:
        await q.answer("Оплата временно недоступна.", show_alert=True)
        return
    amount = plan["amount_rub"]
    description = f"Подписка донат — {plan['title']}"
    try:
        bot_username = context.bot.username
        if not bot_username:
            me = await context.bot.get_me()
            bot_username = me.username or ""
    except TelegramError:
        bot_username = ""
    return_url = SUPPORT_DEEPLINK or (JOIN_URL if JOIN_URL else None)
    if not return_url:
        return_url = f"https://t.me/{bot_username}" if bot_username else "https://t.me"
    payload = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description,
        "metadata": {"user_id": user_id, "plan": plan_code},
    }
    headers = {
        "Authorization": f"Basic {YK_TOKEN}",
        "Idempotence-Key": uuid.uuid4().hex,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Yookassa payment creation failed: %s %s",
            exc.response.status_code,
            exc.response.text,
        )
        await context.bot.send_message(
            q.message.chat_id,
            "Не удалось создать платёж. Попробуй позже.",
        )
        return
    except httpx.RequestError:
        logger.exception("Yookassa payment creation error")
        await context.bot.send_message(
            q.message.chat_id,
            "Не удалось связаться с платёжным сервисом. Попробуй позже.",
        )
        return
    data = response.json()
    payment_id = data.get("id")
    confirmation = data.get("confirmation") or {}
    confirmation_url = confirmation.get("confirmation_url")
    if not payment_id or not confirmation_url:
        logger.warning("Yookassa response missing payment data: %s", data)
        await context.bot.send_message(
            q.message.chat_id, "Не удалось получить ссылку на оплату."
        )
        return
    payload_data = {
        "plan": plan_code,
        "amount": amount,
        "title": plan["title"],
        "confirmation_url": confirmation_url,
    }
    amount_kopecks = int(amount * 100)
    await create_payment_record(
        user_id,
        YK_PROVIDER,
        amount_kopecks,
        "RUB",
        "pending",
        payload_data,
        payment_id,
    )
    context.user_data[SUBSCRIPTION_PAYMENT_KEY] = {
        "payment_id": payment_id,
        "plan": plan_code,
    }
    text = (
        f"{plan['title']} — {amount} ₽.\n"
        "Оплата пройдёт через ЮKassa.\n"
        "После оплаты вернись и нажми «Проверить оплату», чтобы активировать подписку."
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💳 Оплатить", url=confirmation_url)],
            [
                InlineKeyboardButton(
                    "🔄 Проверить оплату",
                    callback_data=f"set:subscription:check:{payment_id}",
                )
            ],
            [InlineKeyboardButton(BACK_BTN, callback_data="set:subscription")],
        ]
    )
    await show_screen(q, context, text, kb, user_id)


async def check_subscription_payment(
    q, context: ContextTypes.DEFAULT_TYPE, user_id: int, payment_id: str
):
    if not YK_TOKEN:
        await q.answer("Проверка недоступна.", show_alert=True)
        return
    record = await get_payment_by_external_id(payment_id)
    if not record:
        await q.answer("Платёж не найден.", show_alert=True)
        return
    headers = {
        "Authorization": f"Basic {YK_TOKEN}",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.yookassa.ru/v3/payments/{payment_id}",
                headers=headers,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Yookassa payment status failed: %s %s",
            exc.response.status_code,
            exc.response.text,
        )
        await context.bot.send_message(
            q.message.chat_id,
            "Не удалось проверить оплату. Попробуй позже.",
        )
        return
    except httpx.RequestError:
        logger.exception("Yookassa status request error")
        await context.bot.send_message(
            q.message.chat_id,
            "Не удалось проверить оплату. Попробуй позже.",
        )
        return
    data = response.json()
    status = data.get("status", "")
    await update_payment_status(payment_id, status, data)
    if status == "succeeded":
        payload = record.get("payload") or {}
        plan_code = payload.get("plan") or "manual"
        plan = SUBSCRIPTION_PLANS.get(plan_code)
        days = plan["days"] if plan else 30
        expires_at = await grant_subscription_days(user_id, days, plan=plan_code)
        await cleanup_expired_subscriptions(user_id)
        tz_code = await get_user_timezone(user_id)
        zone = resolve_user_zone(tz_code)
        expires_label = expires_at.astimezone(zone).strftime("%d.%m.%Y")
        context.user_data.pop(SUBSCRIPTION_PAYMENT_KEY, None)
        await context.bot.send_message(
            q.message.chat_id,
            f"Оплата получена. Подписка активна до {expires_label}.",
        )
        await show_subscription_overview(q, context, user_id)
        return
    if status in {"pending", "waiting_for_capture"}:
        await context.bot.send_message(
            q.message.chat_id,
            "Платёж ещё обрабатывается. Проверь его чуть позже.",
        )
        return
    if status == "canceled":
        context.user_data.pop(SUBSCRIPTION_PAYMENT_KEY, None)
        await context.bot.send_message(
            q.message.chat_id,
            "Платёж отменён. Если нужна помощь, напиши в поддержку.",
        )
        await show_subscription_overview(q, context, user_id)
        return
    await context.bot.send_message(
        q.message.chat_id,
        f"Текущий статус платежа: {status}.",
    )
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
            "AMRAP — на раунды, For Time — на время.",
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
        (AMRAP_EXERCISE_NAME, "AMRAP"),
        (FOR_TIME_EXERCISE_NAME, "For Time"),
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
    ex_rows = await list_exercises_by_group(group)
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
    ex_rows = await list_exercises_by_group(group)
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
    ex_rows = await list_exercises_by_group(group)
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


async def prompt_day_mode(q, context, user_id: int, day: int):
    prefs = await load_ui_preferences(user_id)
    text = wizard_day_mode_text(day, prefs)
    kb = wizard_day_mode_kb(day)
    await show_screen(q, context, text, kb, user_id)

async def wizard_router(q, data: str, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
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
            await set_workouts_per_week(user_id, n)
            context.user_data["workouts_per_week"] = n
            context.user_data.pop("reminder_day", None)
            context.user_data.pop("reminder_skip_tz", None)
            if chat_id is not None:
                menu_text, menu_kb, prefs = await compose_main_menu(user_id)
                prepared_text, prepared_markup = prepare_ui_output(
                    menu_text, menu_kb, prefs
                )
                await send_main_message_fresh(
                    context.bot,
                    chat_id,
                    prepared_text,
                    reply_markup=prepared_markup,
                )
            await show_screen(
                q,
                context,
                "Хочешь получать напоминания?",
                reminder_prompt_kb(),
                user_id,
            )
            return
        if data.startswith("wiz:daymode:"):
            parts = data.split(":")
            if len(parts) < 4:
                return
            day = int(parts[2])
            mode = parts[3]
            context.user_data.setdefault("day_modes", {})[day] = mode
            context.user_data["current_day"] = day
            context.user_data.pop("group_list", None)
            context.user_data.pop("group_idx", None)
            groups_store = context.user_data.setdefault("day_groups", {})
            if mode == "strength":
                selected = groups_store.setdefault(day, set())
                custom = await get_custom_groups(user_id, context)
                await show_screen(
                    q,
                    context,
                    day_groups_text(day),
                    muscle_groups_kb(day, selected or set(), custom),
                    user_id,
                )
            elif mode in {"kb", "metcon", "workout"}:
                selected = groups_store.setdefault(day, set())
                selected.add(mode)
                context.user_data["group_list"] = [mode]
                context.user_data["group_idx"] = 0
                await show_exercises(q, user_id, day, mode, context)
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
                    baseline_kb(day, *values, with_weight=with_weight, kind=kind),
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
                    context.user_data["awaiting_group_name"] = (day, q.message.chat_id, q.message.message_id, "wizard")
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
                    added = await toggle_user_exercise(user_id, day, ex_id)
                    group = context.user_data["group_list"][context.user_data["group_idx"]]
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
                                    with_weight=first_with_weight,
                                    kind=first_kind,
                                ),
                                user_id,
                            )
                        else:
                            await finish_day(q, context, user_id, day)
                    return
            if parts[3] == "baseline" and parts[4] == "skip_all":
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
                _, menu_kb, _ = await compose_main_menu(user_id)
                await show_screen(q, context, 'Настройка завершена.', menu_kb, user_id)
            return
        if data == "wiz:finish_yes":
            _, menu_kb, _ = await compose_main_menu(user_id)
            await show_screen(q, context, 'Настройка завершена.', menu_kb, user_id)
            return
        if data == "wiz:finish_no":
            day = context.user_data.get("confirm_finish_day", 1)
            await show_screen(q, context, f"{t('DAY')} {day} сохранён. Перейти к {t('DAY')} {day + 1}?", day_done_kb(day), user_id)
            return
        if data == "wiz:reminders:yes":
            from_settings = context.user_data.get("from_settings")
            if not from_settings and chat_id is not None:
                menu_text, menu_kb, prefs = await compose_main_menu(user_id)
                prepared_text, prepared_markup = prepare_ui_output(
                    menu_text, menu_kb, prefs
                )
                await send_main_message_fresh(
                    context.bot,
                    chat_id,
                    prepared_text,
                    reply_markup=prepared_markup,
                )
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
            if context.user_data.get("from_settings"):
                context.user_data.pop("from_settings", None)
                context.user_data.pop("reminder_skip_tz", None)
                context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
                kb = await build_settings_keyboard_for_user(context, user_id)
                await show_screen(q, context, 'Настройки:', kb, user_id)
                return
            if chat_id is not None:
                menu_text, menu_kb, prefs = await compose_main_menu(user_id)
                prepared_text, prepared_markup = prepare_ui_output(
                    menu_text, menu_kb, prefs
                )
                await send_main_message_fresh(
                    context.bot,
                    chat_id,
                    prepared_text,
                    reply_markup=prepared_markup,
                )
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
                context.user_data.pop("wizard_onboarding", None)
                await show_screen(
                    q,
                    context,
                    "Настройка завершена. Напоминания можно включить позже в настройках.",
                    None,
                    user_id,
                )
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
                mode = context.user_data.pop("wizard_onboarding_tz", None)
                if mode and chat_id is not None:
                    menu_text, menu_kb, prefs = await compose_main_menu(user_id)
                    prepared_text, prepared_markup = prepare_ui_output(
                        menu_text, menu_kb, prefs
                    )
                    await send_main_message_fresh(
                        context.bot,
                        chat_id,
                        prepared_text,
                        reply_markup=prepared_markup,
                    )
                day_no = context.user_data.get("reminder_day", 1)
                tz_only_change = context.user_data.pop("tz_only_change", None)
                if tz_only_change:
                    tz_label = get_timezone_label(tz)
                    rems = await list_user_reminders(user_id)
                    if rems:
                        parts = [
                            f"{dict(WEEKDAYS)[d]} {h:02d}:{m:02d}"
                            for _day, d, h, m in rems
                        ]
                        rem_text = ", ".join(parts)
                        text = f"Часовой пояс обновлён: {tz_label}. Напоминания: {rem_text}."
                    else:
                        text = f"Часовой пояс обновлён: {tz_label}. Напоминания пока не настроены."
                    await show_screen(q, context, text, reminders_edit_kb(), user_id)
                elif mode == "final":
                    context.user_data.pop("wizard_onboarding", None)
                    await show_screen(
                        q,
                        context,
                        "Часовой пояс сохранён. Основные настройки завершены.",
                        None,
                        user_id,
                    )
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
            tz = context.user_data.get("tz", "UTC")
            zone = resolve_user_zone(tz)
            reminder_time = time(hour, minute, tzinfo=zone)
            job_name = f"rem_{user_id}_{day_no}_{dow}"
            _remove_reminder_jobs(context.job_queue, user_id, day_no, dow)
            message = getattr(q, "message", None)
            chat_id = getattr(message, "chat_id", None)
            if chat_id is None and message is not None:
                chat = getattr(message, "chat", None)
                chat_id = getattr(chat, "id", None)
            if chat_id is not None:
                context.job_queue.run_daily(
                    reminder_job,
                    reminder_time,
                    days=(dow,),
                    chat_id=chat_id,
                    name=job_name,
                    data={"user_id": user_id, "day_no": day_no, "dow": dow},
                )
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
                menu_text, menu_kb, prefs = await compose_main_menu(user_id)
                prepared_text, prepared_markup = prepare_ui_output(
                    menu_text, menu_kb, prefs
                )
                if chat_id is not None:
                    await send_main_message_fresh(
                        context.bot,
                        chat_id,
                        prepared_text,
                        reply_markup=prepared_markup,
                    )
                context.user_data.pop("wizard_onboarding", None)
                await show_screen(
                    q,
                    context,
                    'Настройка завершена.',
                    menu_kb,
                    user_id,
                )
            return
    finally:
        message = getattr(q, "message", None)
        if message and not onboarding:
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
    if acting_user_id:
        user_id = int(acting_user_id)
    else:
        user_id = actor_user_id
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
                "Код тренера не найден.",
                chat_id=update.effective_chat.id if update.effective_chat else None,
            )
            context.user_data[TRAINER_CODE_INPUT_KEY] = True
            return
        trainer = await find_user_by_trainer_code(code_input)
        if not trainer:
            await try_delete(update.message)
            await _render_trainer_link_message(
                context,
                user_id,
                target if isinstance(target, tuple) else None,
                "Код тренера не найден.",
                chat_id=update.effective_chat.id if update.effective_chat else None,
            )
            context.user_data[TRAINER_CODE_INPUT_KEY] = True
            return
        trainer_id = int(trainer[0])
        link1 = await get_trainer_link(trainer_id, user_id)
        link2 = await get_trainer_link(user_id, trainer_id)
        if link1 or link2 or trainer_id == user_id:
            await try_delete(update.message)
            await _render_trainer_link_message(
                context,
                user_id,
                target if isinstance(target, tuple) else None,
                "Этот пользователь уже связан с вами.",
                chat_id=update.effective_chat.id if update.effective_chat else None,
            )
            context.user_data[TRAINER_CODE_INPUT_KEY] = True
            return
        await create_trainer_request(trainer_id, user_id)
        await try_delete(update.message)
        await _render_trainer_link_message(
            context,
            user_id,
            target if isinstance(target, tuple) else None,
            "Заявка отправлена тренеру.",
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
        new_label = normalize_whitespace(update.message.text)
        if not new_label:
            new_label = None
        context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
        await try_delete(update.message)
        await update_trainer_label(link_id, new_label)
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
                session_id = await get_or_create_today_session(user_id, today, day)
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
        today = await get_user_local_date(user_id)
        session_id = await get_or_create_today_session(user_id, today, day)
        await set_exercise_note(session_id, ue_id, note_text)
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
        text_value = update.message.text
        try:
            if field == "distance":
                new_distance = parse_distance_input(text_value)
                update_kwargs = {"distance_km": new_distance, "is_draft": 1}
            elif field == "time":
                duration = clamp_running_duration(parse_duration_input(text_value))
                update_kwargs = {"duration_sec": duration, "is_draft": 1}
            elif field == "pace":
                pace_seconds = clamp_running_duration(parse_duration_input(text_value))
                entry_row = await get_running_entry_by_id(entry_id)
                if not entry_row:
                    raise ValueError
                distance_value = float(entry_row[5] or 0.0)
                safe_distance, new_duration = apply_pace_to_entry(
                    distance_value, pace_seconds
                )
                update_kwargs = {
                    "distance_km": safe_distance,
                    "duration_sec": new_duration,
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
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
        if update_kwargs:
            await update_running_entry(entry_id, **update_kwargs)
        chat_id = running_state.get("chat_id")
        msg_id = running_state.get("message_id")
        if not chat_id or not msg_id:
            return
        sheet_info = running_state.get("sheet")
        is_library = bool(running_state.get("is_library"))
        prefs = await load_ui_preferences(user_id)
        if sheet_info and not is_library:
            target_day = int(sheet_info.get("day", running_state.get("day", 0)))
            target_page = int(sheet_info.get("page", 0))
            await render_day_sheet_by_id(
                context,
                chat_id,
                msg_id,
                user_id,
                target_day,
                target_page,
                prefs=prefs,
            )
            return
        day = int(running_state.get("day", 0))
        ue_id = int(running_state.get("ue_id", 0))
        selected = get_flex_selected(context, day, ue_id)
        view = await render_exercise_view(user_id, day, ue_id, selected, prefs=prefs)
        set_flex_selected(context, day, ue_id, view.selected_set)
        kb = build_exercise_actions_markup(
            view,
            day=day,
            ue_id=ue_id,
            group=view.group,
            prefs=prefs,
            is_library=is_library,
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
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
        custom_items = await load_custom_measurements(user_id, context)
        user_categories = await load_measurement_categories(user_id, context)
        letter = next_category_letter(user_categories, custom_items)
        await add_measurement_category(user_id, letter, name)
        user_categories = await load_measurement_categories(user_id, context)
        chat_id = category_state.get("chat_id")
        msg_id = category_state.get("message_id")
        back_callback = category_state.get("back", "measure:add")
        mode = category_state.get("mode", "add")
        pending_name = category_state.get("pending_name")
        context.user_data.pop(MEASUREMENT_CATEGORY_INPUT_KEY, None)
        if not chat_id or not msg_id:
            return
        prefs = await load_ui_preferences(user_id)
        custom_items = await load_custom_measurements(user_id, context)
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
            u = update.effective_user
            user_id = await get_or_create_user(u.id, u.username)
            chat_id = custom_state.get("chat_id")
            msg_id = custom_state.get("message_id")
            back_callback = custom_state.get("back", "measure:add")
            if not chat_id or not msg_id:
                context.user_data.pop(MEASUREMENT_CUSTOM_KEY, None)
                return
            custom_items = await load_custom_measurements(user_id, context)
            user_categories = await load_measurement_categories(user_id, context)
            categories = measurement_categories_list(
                user_categories,
                include_custom_fallback=True,
                custom_items=custom_items,
            )
            origin = (custom_state.get("origin") or "").strip()
            if origin and any(code == origin for code, _ in categories):
                await prompt_custom_measurement_value(
                    context,
                    user_id,
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
            prefs = await load_ui_preferences(user_id)
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
        item = get_measurement_item(input_state.get("metric"))
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
        user_id = await get_or_create_user(u.id, u.username)
        action = input_state.get("action")
        if action == "add":
            await add_measurement_entry(user_id, item["code"], value, extra)
        else:
            updated = await update_last_measurement(user_id, item["code"], value, extra)
            if not updated:
                await add_measurement_entry(user_id, item["code"], value, extra)
        await try_delete(update.message)
        chat_id = input_state.get("chat_id")
        msg_id = input_state.get("message_id")
        context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
        if chat_id and msg_id:
            text, kb = await build_measurements_view(user_id, context)
            prefs = await load_ui_preferences(user_id)
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
        day, ue_id, chat_id, msg_id = context.user_data.pop(AMRAP_SCHEME_KEY)
        new_scheme = update.message.text.strip() if update.message and update.message.text else ""
        await try_delete(update.message)
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
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
        await set_exercise_scheme(user_id, day, ex_id, new_scheme or None)
        selected = get_flex_selected(context, day, ue_id)
        prefs = await load_ui_preferences(user_id)
        view = await render_exercise_view(user_id, day, ue_id, selected, prefs=prefs)
        is_library = day == 0
        set_flex_selected(context, day, ue_id, view.selected_set)
        kb = build_exercise_actions_markup(
            view,
            day=day,
            ue_id=ue_id,
            group=view.group,
            prefs=prefs,
            is_library=is_library,
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
        group, chat_id, msg_id = lib_custom
        name = normalize_whitespace(update.message.text or "")
        if not name:
            await update.message.reply_text("Название не должно быть пустым. Попробуй ещё раз.")
            return
        context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
        await try_delete(update.message)
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
        exists = await user_has_library_exercise(user_id, name)
        if not exists:
            ex_id = await get_or_create_exercise(name, group)
            await add_user_exercise(user_id, 0, ex_id)
        ex_rows = await list_exercises_by_group(group)
        selected = set(await list_user_exercise_ids(user_id, 0, group))
        requested_page = get_kb_page(context, "lib", group)
        kb, page_value, _ = library_add_exercises_kb(
            group, ex_rows, selected, page=requested_page, context=context
        )
        set_kb_page(context, "lib", group, page_value)
        custom = await get_custom_groups(user_id, context)
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
        day, chat_id, msg_id, mode = context.user_data.pop("awaiting_group_name")
        name = normalize_whitespace(update.message.text or "")
        if not name:
            context.user_data["awaiting_group_name"] = (day, chat_id, msg_id, mode)
            await update.message.reply_text("Название не должно быть пустым.")
            return
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
        code = await add_user_muscle_group(user_id, name)
        custom = await get_custom_groups(user_id, context)
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
            ex_rows = await list_exercises_by_group(code)
            selected_ids = set(await list_user_exercise_ids(user_id, 0, code))
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
            ex_rows = await list_exercises_by_group(code)
            selected_ids = set(await list_user_exercise_ids(user_id, day, code))
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
        ex_id = await get_or_create_exercise(name, group)
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

        ex_rows = await list_exercises_by_group(group)
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
    try:
        q = update.callback_query
        await q.answer()
        data = q.data or ""
        preserve_keys: set[str] | None = None
        if data.startswith("broadcast:"):
            preserve_keys = {BROADCAST_STATE_KEY}
        clear_linear_state(context.user_data, preserve_keys)
        user = update.effective_user
        if user is None:
            return
        actor_user_id = await get_or_create_user(user.id, user.username)
        target_user_id = await resolve_target_user_id(context, actor_user_id)
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
                    await show_trainee_trainer_settings(q, context, target_user_id)
                    return
                if action == "allow" and len(parts) >= 3:
                    desired = parts[2]
                    if acting_id:
                        link = await get_trainer_link(actor_user_id, acting_id)
                        if not link or str(link[1]) != "accepted":
                            await q.answer("Связь недоступна.", show_alert=True)
                            return
                        link_id = int(link[0])
                        new_value = 1 if desired == "on" else 0
                        await update_trainer_link_permissions(link_id, new_value)
                        context.user_data["acting_can_edit"] = bool(new_value)
                        target_key = context.user_data.get(
                            TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY
                        )
                        await refresh_trainer_manage_trainee_message(
                            context,
                            actor_user_id,
                            acting_id,
                            target_key if isinstance(target_key, tuple) else None,
                        )
                        return
                    link = await get_active_trainer_link_for_trainee(target_user_id)
                    if not link:
                        await show_trainee_trainer_settings(q, context, target_user_id)
                        return
                    link_id = int(link[0])
                    new_value = 1 if desired == "on" else 0
                    await update_trainer_link_permissions(link_id, new_value)
                    await show_trainee_trainer_settings(q, context, target_user_id)
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
                    if acting_id:
                        link = await get_trainer_link(actor_user_id, acting_id)
                        if not link or str(link[1]) != "accepted":
                            await q.answer("Связь недоступна.", show_alert=True)
                            return
                        await update_trainer_link_status(int(link[0]), "removed")
                        context.user_data.pop("acting_user_id", None)
                        context.user_data.pop("acting_can_edit", None)
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
                    context.user_data.pop(TRAINER_SETTINGS_MESSAGE_KEY, None)
                    context.user_data.pop(TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY, None)
                    context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
                if len(parts) == 2:
                    await _render_trainer_overview(q, context, actor_user_id)
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
                        await _render_trainer_overview(
                            q,
                            context,
                            actor_user_id,
                            pending_offset=pending_offset,
                            accepted_offset=accepted_offset,
                        )
                        return
                    if section == "accepted":
                        if direction == "next":
                            accepted_offset += TRAINER_LIST_LIMIT
                        elif direction == "prev":
                            accepted_offset = max(
                                0, accepted_offset - TRAINER_LIST_LIMIT
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
                    accepted = await list_trainer_trainees(
                        actor_user_id, limit=1000, offset=0
                    )
                    if len(accepted) >= TRAINER_MAX_TRAINEES:
                        await _render_trainer_overview(
                            q,
                            context,
                            actor_user_id,
                            message="Лимит подопечных достигнут (10)",
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
                    await update_trainer_link_status(link_id, "accepted")
                    await _render_trainer_overview(
                        q, context, actor_user_id, message="Заявка принята"
                    )
                    return
                if req_action == "decline":
                    await update_trainer_link_status(link_id, "rejected")
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
                context.user_data.pop(TRAINER_SETTINGS_MESSAGE_KEY, None)
                context.user_data.pop(TRAINER_TRAINEE_SETTINGS_MESSAGE_KEY, None)
                context.user_data.pop(TRAINER_TRAINEE_LABEL_INPUT_KEY, None)
                await show_trainer_acting_menu(q, context, actor_user_id, trainee_id)
                return

        if data.startswith("ib:"):
            parts = data.split(":")
            if len(parts) < 3:
                return
            info = context.user_data.get(INSTANT_BASE_KEY)
            if not info or info.get("source") != parts[1]:
                context.user_data.pop(INSTANT_BASE_KEY, None)
                await q.answer()
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
            await wizard_router(q, data, target_user_id, context)
            return

        if data == "promo:channel:no":
            await q.answer("Спасибо! Напомним позже.")
            return

        if data == "menu:root":
            prefs = await load_ui_preferences(target_user_id)
            text, kb, prefs = await compose_main_menu(target_user_id, prefs)
            await show_screen(q, context, text, kb, target_user_id)
            return

        if data in ("menu:library", "lib:root"):
            context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
            await ensure_library_history(target_user_id)
            groups = await list_library_groups(target_user_id)
            custom = await get_custom_groups(target_user_id, context)
            prefs = await load_ui_preferences(target_user_id)
            text = "Мои упражнения:"
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
            ]
            active_sub = await get_active_subscription(target_user_id)
            if active_sub and active_sub.get("expires_at"):
                zone = resolve_user_zone(tz)
                expires_local = active_sub["expires_at"].astimezone(zone)
                support_line = (
                    f"Спасибо за поддержку! Рекламных рассылок нет до {expires_local.strftime('%d.%m.%Y')}."
                )
            else:
                support_line = "⭐ Подписка донат — отключи рекламные рассылки и поддержи разработчиков."
            text_lines.append(support_line)
            text = "\n".join(text_lines)
            kb = await build_settings_keyboard_for_user(context, target_user_id)
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
            item = get_measurement_item(code)
            if not item or item.get("derived"):
                await q.answer()
                return
            context.user_data[MEASUREMENT_INPUT_KEY] = {
                "action": "add",
                "metric": code,
                "chat_id": q.message.chat_id,
                "message_id": q.message.message_id,
                "category": category,
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
                    item = get_measurement_item(code)
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
            item = get_measurement_item(code)
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
                item = get_measurement_item(code)
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
                item = get_measurement_item(code)
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
                item = get_measurement_item(code)
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
                    text = "Мои упражнения:"
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
                        await show_screen(q, context, "Мои упражнения:", kb, target_user_id)
                    return

        if parts[0] == "run":
            action = parts[1] if len(parts) > 1 else ""
            day = int(parts[2]) if len(parts) > 2 else 0
            ue_id = int(parts[3]) if len(parts) > 3 else 0
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
            async with user_locks[target_user_id]:
                selected = get_flex_selected(context, day, ue_id)
                view = await render_exercise_view(
                    target_user_id, day, ue_id, selected, prefs=prefs
                )
                set_flex_selected(context, day, ue_id, view.selected_set)
                running = view.running or {}
                entry_id = int(running.get("entry_id") or 0)
                distance_value = float(running.get("distance") or 0.0)
                duration_value = int(running.get("duration") or 0)
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
                )
                await show_screen(q, context, refreshed.text, kb, target_user_id)
                return

        if parts[0] == "set":
            action = parts[1]
            mutating_set_actions = {
                "rename_day",
                "edit_day",
                "days_count",
                "groups",
                "reminders",
            }
            if action in mutating_set_actions:
                if not await require_edit_allowed(q, context):
                    return
            if action == "trainer_mode":
                profile = await _fetch_trainer_profile(target_user_id)
                code = await _ensure_trainer_mode(target_user_id, profile)
                text = f"Режим тренера включён.\n\nКод: {code}"
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")]]
                )
                await show_screen(q, context, text, kb, target_user_id)
                return
            if action == "trainer_link":
                link = await get_active_trainer_link_for_trainee(target_user_id)
                if link:
                    await show_trainee_trainer_settings(q, context, target_user_id)
                    return
                message = await show_screen(
                    q,
                    context,
                    "Введи код тренера (формат TR-XXXXX).",
                    InlineKeyboardMarkup(
                        [[InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")]]
                    ),
                    target_user_id,
                )
                target_message = message or q.message
                context.user_data[TRAINER_CODE_INPUT_KEY] = True
                context.user_data[TRAINER_CODE_PROMPT_KEY] = (
                    getattr(target_message, "chat_id", q.message.chat_id),
                    getattr(target_message, "message_id", q.message.message_id),
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
            if action == "edit_day":
                prefs = await load_ui_preferences(target_user_id)
                if len(parts) == 2:
                    days = await list_active_days(target_user_id)
                    text = "Какой день изменить?"
                    kb = edit_day_select_kb(days, context=context)
                    await show_screen(q, context, text, kb, target_user_id)
                else:
                    day = int(parts[2])
                    label = await get_day_label(target_user_id, day) or f"{t('DAY')} {day}"
                    if len(parts) == 3:
                        text = (
                            f"{t('DAY')} {day} — {label}.\n"
                            "Выбери основной тип тренировки. Силовая откроет группы мышц, остальные режимы сразу ведут в свой каталог. После выбора можно добавлять упражнения из любых групп через меню дня."
                        )
                        kb = edit_day_mode_kb(day, context=context)
                    else:
                        mode = parts[3]
                        followup = parts[4] if len(parts) > 4 else None
                        if mode in {"strength", "kb", "metcon", "workout"}:
                            today_str = await get_user_local_date(target_user_id)
                            ex_rows = await fetch_day_exercises(target_user_id, day, today_str)
                            has_exercises = bool(ex_rows)
                            if followup is None and has_exercises:
                                confirm_text = (
                                    f"{t('DAY')} {day} — {label}.\n"
                                    "Начать настройку с нуля? Удалим все упражнения и планы этого дня, чтобы собрать его заново."
                                )
                                kb = confirm_day_reset_kb(day, mode, context=context)
                                await show_screen(q, context, confirm_text, kb, target_user_id)
                                return
                            if followup == "reset" and has_exercises:
                                await clear_day_plan(target_user_id, day)
                                pending_add = context.user_data.get("add_group")
                                if pending_add and pending_add[0] == day:
                                    context.user_data.pop("add_group", None)
                                context.user_data.pop(DAY_DELETE_SCOPE_KEY, None)
                                await q.answer("День очищен. Начнём заново.")
                                has_exercises = False
                        if mode == "strength":
                            text = (
                                f"{t('DAY')} {day} — {label}.\n"
                                "Открой список групп мышц, выбери нужные и добавь упражнения. В любой момент можешь расширить тренировку другими направлениями через кнопки «Добавить» и «Удалить»."
                            )
                            kb = edit_day_strength_kb(day, context=context)
                        elif mode in {"kb", "metcon", "workout"}:
                            labels = {
                                "kb": "Каталог гиревых упражнений",
                                "metcon": "Каталог кроссфита",
                                "workout": "Каталог воркаута",
                            }
                            descriptions = {
                                "kb": "Подбери упражнения с гирями. После добавления можно дополнять день силовыми или другими упражнениями.",
                                "metcon": "Открой подборку кроссфит-упражнений и собери тренировку. Другие группы всегда доступны через меню дня.",
                                "workout": "Выбери упражнения для воркаута. При желании добавляй силовые или гиревые упражнения через кнопки «Добавить» и «Удалить».",
                            }
                            text = (
                                f"{t('DAY')} {day} — {label}.\n"
                                f"{descriptions[mode]}"
                            )
                            kb = edit_day_special_kb(day, mode, labels[mode])
                        else:
                            return
                    await show_screen(q, context, text, kb, target_user_id)
                return
            if action == "days_count":
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
                        for day_no, dow, _hour, _minute in removed:
                            normalized = dow if dow >= 0 else None
                            _remove_reminder_jobs(
                                context.job_queue,
                                target_user_id,
                                day_no,
                                normalized,
                            )
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
            if action == "reminders":
                if len(parts) == 2:
                    context.user_data.pop("tz_only_change", None)
                    tz = await get_user_timezone(target_user_id)
                    rems = await list_user_reminders(target_user_id)
                    if tz and rems:
                        tz_label = get_timezone_label(tz)
                        parts = [
                            f"{dict(WEEKDAYS)[d]} {h:02d}:{m:02d}"
                            for _day, d, h, m in rems
                        ]
                        rem_text = ", ".join(parts)
                        text = f"Сейчас выбран {tz_label}, напоминания: {rem_text}."
                        await show_screen(q, context, text, reminders_edit_kb(), target_user_id)
                        return
                    context.user_data["from_settings"] = True
                    context.user_data["tz_page"] = 0
                    await show_screen(q, context, 'Выбери свой часовой пояс:', tz_select_kb(0), target_user_id)
                    return
                sub = parts[2]
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
                if sub_action == "check" and len(parts) >= 4:
                    await check_subscription_payment(q, context, target_user_id, parts[3])
                    return
                await show_subscription_overview(q, context, target_user_id)
                return

        if parts[0] == "remedit":
            if not await require_edit_allowed(q, context):
                return
            action = parts[1] if len(parts) > 1 else ""
            if action == "back":
                context.user_data.pop(REMINDER_EDIT_POSITION_KEY, None)
                context.user_data.pop(REMINDER_EDIT_LABEL_KEY, None)
                context.user_data.pop(REMINDER_EDIT_DAY_INDEX_KEY, None)
                context.user_data.pop(REMINDER_SELECTED_DOW_KEY, None)
                context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
                await show_screen(
                    q,
                    context,
                    'Настройки уведомлений:',
                    reminders_edit_kb(),
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
                _remove_reminder_jobs(context.job_queue, target_user_id, day_index, dow)
                tz_code = await get_user_timezone(target_user_id)
                zone = resolve_user_zone(tz_code)
                reminder_time = time(hour, minute, tzinfo=zone)
                message = getattr(q, "message", None)
                chat_id = getattr(message, "chat_id", None)
                if chat_id is None:
                    chat = getattr(message, "chat", None)
                    chat_id = getattr(chat, "id", None)
                if chat_id is not None:
                    context.job_queue.run_daily(
                        reminder_job,
                        reminder_time,
                        days=(dow,),
                        chat_id=chat_id,
                        name=f"rem_{target_user_id}_{day_index}_{dow}",
                        data={
                            "target_user_id": target_user_id,
                            "day_no": day_index,
                            "dow": dow,
                        },
                    )
                context.user_data[REMINDER_SELECTED_DOW_KEY] = str(dow_iso)
                confirmation = format_reminder_status(label, (dow, hour, minute))
                await q.answer(confirmation)
                context.user_data.pop(REMINDER_TIME_PAGE_KEY, None)
                await show_reminders_overview(q, context, target_user_id)
                return
            return

        if parts[0] == "day":
            action = parts[1]
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
                await show_screen(q, context, text, kb, target_user_id)
                if added_new:
                    await maybe_prompt_channel_support(q, context, target_user_id)
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
                ex_rows = await fetch_day_exercises(target_user_id, day, today_local)
                if ex_rows:
                    session_id = await get_or_create_today_session(target_user_id, today_local, day)
                    for ue_id, *_ in ex_rows:
                        await mark_exercise_done(session_id, ue_id)
                _, added_new = await record_day_completion(target_user_id, day)
                await q.answer(f"{t('DAY')} отмечен выполненным.")
                prefs = await load_ui_preferences(target_user_id)
                await send_day_cards_view(q, target_user_id, day, context, prefs)
                if added_new:
                    await maybe_prompt_channel_support(q, context, target_user_id)
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
                ex_rows = await fetch_day_exercises(target_user_id, day, today_str)
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
                        existing_groups = {g for _, _, g, _, _ in ex_rows}
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
                ex_rows = await fetch_day_exercises(target_user_id, day, today_str)
                filtered = [row for row in ex_rows if row[2] == group]
                if not filtered:
                    await q.answer("Эта группа уже отсутствует в дне.", show_alert=True)
                else:
                    for ue_id, *_ in filtered:
                        await remove_user_exercise(target_user_id, day, ue_id)
                    if context.user_data.get("add_group") == (day, group):
                        context.user_data.pop("add_group", None)
                    await q.answer("Группа удалена из дня.")
                ex_rows = await fetch_day_exercises(target_user_id, day, today_str)
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
                ex_rows = await fetch_day_exercises(target_user_id, day, today_str)
                existing_groups = {g for _, _, g, _, _ in ex_rows}
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
                ex_rows = await fetch_day_exercises(target_user_id, day, today_str)
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
                    ex_rows = await fetch_day_exercises(target_user_id, day, today_str)
                    existing_groups = {g for _, _, g, _, _ in ex_rows}
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
                    await add_user_exercise(target_user_id, day, ex_id)
                    if not existed:
                        if not group:
                            details = await get_exercise_details(ex_id)
                            if details:
                                _, detected_group = details
                                group = detected_group
                                context.user_data["add_group"] = (day, group)

                        async def edit_instant(text, kb):
                            await show_screen(q, context, text, kb, target_user_id)

                        started = await start_instant_baseline(
                            context,
                            target_user_id,
                            day,
                            ex_id,
                            "day",
                            group,
                            edit_instant,
                        )
                        if started:
                            return
                    if group:
                        await show_day_add_exercises_view(q, target_user_id, day, group, context)
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
                    today_str = await get_user_local_date(target_user_id)
                    ex_rows = await fetch_day_exercises(target_user_id, day, today_str)
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
            mutating_ex_actions = {
                "note",
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
            selected = get_flex_selected(context, day, ue_id)
            is_library = day == 0
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
                )
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t("BACK"), callback_data=f"ex:view:{day}:{ue_id}")]]
                )
                await show_screen(q, context, 'Напиши схему WOD. Оставь пусто, чтобы очистить.', kb, target_user_id)
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
                )
                await show_screen(q, context, view.text, kb, target_user_id)
                return
            if action == "view":
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
                session_id = await get_or_create_today_session(target_user_id, today_str, day)
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
        )
        await show_screen(q, context, view.text, kb, target_user_id)
        return
    finally:
        message = getattr(q, "message", None)
        if message:
            chat = getattr(message, "chat", None)
            chat_id = getattr(chat, "id", None) if chat else getattr(message, "chat_id", None)
            remember_message(chat_id, getattr(message, "message_id", None))


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Телеграм прислал pre-checkout — нужно подтвердить."""

    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь оплатил — активируем подписку и помечаем платёж как paid."""

    payment = update.message.successful_payment
    payload = payment.invoice_payload

    parts = payload.split(":")
    if len(parts) != 3:
        return

    _, user_id_str, plan_code = parts
    tg_user_id = int(user_id_str)

    user_info = await find_user_by_tg_id(tg_user_id)
    if not user_info:
        return
    user_id = user_info[0]

    plan = SUBSCRIPTION_PLANS.get(plan_code)
    if not plan:
        return

    await update_payment_status(
        payload,
        "paid",
        {"paid_at": datetime.utcnow().isoformat(timespec="seconds")},
    )

    await grant_subscription_days(
        user_id=user_id,
        days=plan["days"],
        plan=plan_code,
    )

    await update.message.reply_text(
        f"✅ Оплата получена. Подписка активна на {plan['days']} дней."
    )


def main():
    asyncio.run(init_db())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = (
        Application.builder()
        .token(TG_TOKEN)
        .concurrent_updates(True)
        .connection_pool_size(TG_POOL_SIZE)
        .rate_limiter(AIORateLimiter())
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler(("grant", "grunt"), grant_command))
    app.add_handler(CallbackQueryHandler(on_subscription_menu, pattern="^menu:subscription$"))
    app.add_handler(CallbackQueryHandler(on_subscription_choose, pattern="^sub:"))
    app.add_handler(CallbackQueryHandler(on_subscription_back, pattern="^back:main$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(CallbackQueryHandler(menu_router))
    app.add_handler(MessageHandler(filters.PHOTO, photo_router))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_router))
    app.add_error_handler(on_error)
    app.run_polling()


if __name__ == "__main__":
    main()
