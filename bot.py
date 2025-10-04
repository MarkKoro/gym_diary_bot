import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, UTC
from zoneinfo import ZoneInfo
from collections import defaultdict
import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import (
    BadRequest,
    Forbidden,
    RetryAfter,
    TimedOut,
    NetworkError,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    AIORateLimiter,
    MessageHandler,
    filters,
)
from keyboards import (
    main_menu_kb,
    subscription_kb,
    system_kb,
    days_kb,
    muscle_groups_kb,
    exercises_kb,
    baseline_kb,
    day_done_kb,
    reminders_kb,
    reminder_time_kb,
    tz_select_kb,
    reminders_edit_kb,
    reminder_day_kb,
    WEEKDAYS,
    MG_NAMES,
    day_kb,
    day_group_kb,
    day_add_group_kb,
    day_add_exercises_kb,
    del_exercises_kb,
    exercise_view_kb,
    settings_kb,
    edit_day_select_kb,
    edit_day_mode_kb,
    edit_day_strength_kb,
    edit_day_special_kb,
    rename_day_kb,
    days_count_kb,
    weight_step_kb,
    recording_mode_kb,
    ui_preferences_kb,
    flex_exercise_view_kb,
    confirm_day_group_delete_kb,
    TIMEZONES,
    library_menu_kb,
    library_group_kb,
    library_add_group_kb,
    library_add_exercises_kb,
    library_delete_kb,
    library_exercise_kb,
    flex_library_exercise_kb,
    confirm_library_group_delete_kb,
    measurements_main_kb,
    measurements_category_kb,
    measurements_metric_kb,
    measurements_existing_kb,
)
from settings import TG_TOKEN, SUPPORT_DEEPLINK, TG_POOL_SIZE, SUBSCRIPTION_CHAT, JOIN_URL
from db import (
    init_db,
    get_or_create_user,
    get_or_create_today_session,
    get_session_for_day,
    fetch_day_exercises,
    add_set,
    inc_last_set,
    fetch_user_settings,
    update_user_system,
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
    get_user_timezone,
    list_user_reminders,
    clear_user_reminders,
    list_active_days,
    get_day_label,
    remove_user_exercise,
    get_exercise_info,
    get_baseline,
    fetch_exercise_sets,
    get_session_last_values,
    remove_last_set,
    mark_exercise_done,
    list_recent_progress,
    count_exercise_progress_entries,
    list_last_done_dates,
    rename_day,
    get_weight_step,
    set_weight_step,
    get_recording_mode,
    set_recording_mode,
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
    list_measurement_metrics,
    fetch_measurement_history,
    get_measurements_last_update,
    get_exercise_details,
    apply_sets_template,
    set_exercise_scheme,
    user_has_library_exercise,
    METCON_EXERCISE_NAMES,
)
from text_utils import normalize_whitespace
from ui_texts import t, e

user_locks = defaultdict(asyncio.Lock)
logger = logging.getLogger(__name__)
last_messages: dict[int, int] = {}
PROGRESS_PAGE_SIZE = 5
DAY_SHEET_PAGE_SIZE = 6
SHEET_VIEWS_KEY = "day_sheet_views"

AMRAP_EXERCISE_NAME = "Меткон — AMRAP (кастом)"
FOR_TIME_EXERCISE_NAME = "Меткон — For Time (кастом)"
FOR_TIME_METRIC = "wod_time_sec"
AMRAP_SCHEME_KEY = "awaiting_amrap_scheme"
FOR_TIME_INPUT_KEY = "awaiting_for_time_result"

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


async def load_ui_preferences(user_id: int) -> UiPreferences:
    mode, emoji, verbose = await get_ui_preferences(user_id)
    return UiPreferences(mode=mode, emoji_enabled=bool(emoji), verbose_level=1 if verbose else 0)


def emoji_for(prefs: UiPreferences, key: str) -> str:
    if not prefs.emoji_enabled:
        return ""
    return e(key)


def status_icon(prefs: UiPreferences, done: bool) -> str:
    return emoji_for(prefs, "done" if done else "generic")


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
        lines.append("Ниже — подробное описание разделов, чтобы быстро сориентироваться.")
    else:
        lines.append("Ниже — краткое напоминание о назначении каждого раздела.")
    lines.append("────────")
    if prefs.verbose_level:
        lines.append(
            "Дни тренировок — открой нужный, чтобы отмечать подходы и просматривать прошлые результаты. Здесь же можно добавлять упражнения из любых групп мышц."
        )
        lines.append(
            "Мои упражнения — личная библиотека с описаниями и историей. Добавляй упражнения через день тренировки, чтобы они появлялись здесь для быстрого доступа."
        )
        lines.append(
            "Мои замеры — сохраняй динамику тела и контрольных показателей. Последние записи отображаются списком, чтобы видеть прогресс без лишних переходов."
        )
        lines.append(
            "Настройки — настрой расписание, напоминания и внешний вид интерфейса. Здесь же выбираются краткие или обычные пояснения и отключаются эмодзи."
        )
        lines.append(
            "Техподдержка — напиши, если что-то не работает или есть вопросы. Мы ответим прямо в чате и поможем настроить дневник."
        )
    else:
        lines.append("Дни тренировок — открой нужный, чтобы отметить подходы и увидеть прогресс.")
        lines.append("Мои упражнения — личная библиотека с описаниями и историей.")
        lines.append("Мои замеры — записывай изменения тела и контрольных показателей.")
        lines.append("Настройки — меняй расписание, напоминания и оформление.")
        lines.append("Техподдержка — быстро связаться с нами, если нужна помощь.")
    return "\n".join(lines)


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


def prepare_ui_output(
    text: str,
    markup: InlineKeyboardMarkup | None,
    prefs: UiPreferences,
) -> tuple[str, InlineKeyboardMarkup | None]:
    return apply_text_preferences(text, prefs), apply_markup_preferences(markup, prefs)


def resolve_group(name: str, group: str) -> str:
    if name in METCON_EXERCISE_NAMES:
        return "metcon"
    return group


def _is_duration_name(name: str) -> bool:
    lower = name.lower()
    return "(сек" in lower or "удержание" in lower or "стойка" in lower


def get_display_flags(group: str, name: str) -> tuple[bool, str]:
    with_weight = group != "workout"
    kind = "duration" if not with_weight and _is_duration_name(name) else "reps"
    return with_weight, kind


def format_weight_value(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.1f}"


def format_sets_value(sets: int, reps: int, weight: float, with_weight: bool) -> str:
    base = f"{sets}×{reps} повт."
    if not with_weight:
        return base
    return f"{base} при {format_weight_value(weight)} кг"


def format_flex_value(
    reps: int, weight: float, with_weight: bool, kind: str = "reps"
) -> str:
    reps = max(int(reps), 0)
    if kind == "duration":
        return f"{reps} сек"
    if with_weight:
        formatted = format_weight_value(max(weight, 0.0))
        return f"{reps}×{formatted} кг"
    return f"{reps} повт."


def filter_work_sets(sets: list[tuple[int, int, float, int]]) -> list[tuple[int, int, float]]:
    return [(no, reps, weight) for no, reps, weight, warm in sets if not warm]


def build_strength_summary_from_sets(
    sets: list[tuple[int, int, float, int]]
) -> dict[str, int | float]:
    work_sets = filter_work_sets(sets)
    if not work_sets:
        return {"sets_count": 0, "last_reps": 0, "last_weight": 0.0}
    last_reps = int(work_sets[-1][1] or 0)
    last_weight = float(work_sets[-1][2] or 0.0)
    return {
        "sets_count": len(work_sets),
        "last_reps": last_reps,
        "last_weight": last_weight,
    }


def pluralize_sets(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "сет"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "сета"
    return "сетов"


def format_kb_previous(last_sets: list[tuple[int, int, float]]) -> str:
    if not last_sets:
        return "—"
    total_reps = sum(max(reps, 0) for _, reps, _ in last_sets)
    best = max(last_sets, key=lambda item: (item[2], item[1]))
    best_text = f"{best[1]} повт. при {format_weight_value(best[2])} кг"
    if total_reps:
        return f"Всего {total_reps} повт., лучший {best_text}"
    return f"Лучший {best_text}"


def format_kb_plan(baseline: tuple[int, int, float] | None) -> str:
    if not baseline:
        return "—"
    sets, reps, weight = baseline
    return f"{sets}×{reps} повт. при {format_weight_value(weight)} кг"


def format_kb_done(sets: list[tuple[int, int, float]]) -> str:
    if not sets:
        return "0 сетов"
    count = len(sets)
    reps = sets[-1][1]
    weight = sets[-1][2]
    return (
        f"{count} {pluralize_sets(count)} (последний {reps} повт. при {format_weight_value(weight)} кг)"
    )


def format_kb_summary(
    current_sets: list[tuple[int, int, float]],
    last_sets: list[tuple[int, int, float]],
) -> str:
    if current_sets:
        return f"{t('MADE')} {format_kb_done(current_sets)}"
    if last_sets:
        return f"{t('LAST_TIME')}: {format_kb_previous(last_sets)}"
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


def format_measurement_timestamp(value: str, tz: ZoneInfo) -> str:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt = dt.astimezone(tz)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return value.split("T")[0]


def remember_message(chat_id: int | None, message_id: int | None):
    if chat_id is None or message_id is None:
        return
    last_messages[chat_id] = message_id

async def safe_edit_message(q, text, reply_markup=None):
    chat_id = getattr(q.message, "chat_id", None)
    message_id = getattr(q.message, "message_id", None)
    try:
        await q.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        message = (e.message or "").lower()
        if "not modified" in message:
            remember_message(chat_id, message_id)
            return
        if (
            "message to edit not found" in message
            or "message identifier is not valid" in message
            or "chat not found" in message
        ):
            if chat_id is None:
                raise
            bot = getattr(q, "bot", None) or getattr(q.message, "bot", None)
            if bot is None:
                raise
            new_msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
            remember_message(chat_id, new_msg.message_id)
            q.message = new_msg
            return
        raise
    remember_message(chat_id, message_id)

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

async def check_subscription(tg_id: int, bot) -> bool:
    try:
        member = await bot.get_chat_member(SUBSCRIPTION_CHAT, tg_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False

async def require_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    now = datetime.now(UTC)
    exp = context.user_data.get("sub_expiry")
    if exp and exp > now:
        return True
    u = update.effective_user
    if await check_subscription(u.id, context.bot):
        context.user_data["sub_expiry"] = now + timedelta(days=1)
        return True
    kb = subscription_kb(JOIN_URL)
    if update.callback_query:
        await safe_edit_message(
            update.callback_query,
            "Прежде чем получить помощника, подпишись на наш канал, чтобы поддержать нас и быть в курсе новостей.",
            reply_markup=kb,
        )
    else:
        msg = await update.message.reply_text(
            "Прежде чем получить помощника, подпишись на наш канал, чтобы поддержать нас и быть в курсе новостей.",
            reply_markup=kb,
        )
        remember_message(msg.chat_id, msg.message_id)
    return False

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
            "Пока нет упражнений. Добавь их, чтобы запланировать тренировку."
        )
    lines = [
        f"{t('DAY')} {i} — {label}",
    ]
    maybe_hint(
        lines,
        prefs,
        (
            "Открой нужную группу, чтобы отметить подходы.",
            "Открой нужную группу, чтобы отметить подходы. После отметки показатели обновятся прямо в списке и покажут актуальный результат.",
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
    name: str, sets: int, reps: int, weight: float, *, with_weight: bool = True
) -> str:
    return f"{name} — {format_sets_value(sets, reps, weight, with_weight)}"

def render_baseline_progress(
    done: list[str],
    name: str,
    sets: int,
    reps: int,
    weight: float,
    *,
    with_weight: bool = True,
) -> str:
    lines = list(done)
    if name:
        if lines:
            lines.append("────────")
        lines.append(baseline_text(name, sets, reps, weight, with_weight=with_weight))
    return "\n".join(lines)

INSTANT_BASE_KEY = "instant_baseline"
FLEX_SELECTED_KEY = "flex_selected"
FILL_EDITOR_KEY = "fill_editor"


@dataclass
class FillEditorState:
    mode: str
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
    summary_sets: int = 0
    summary_reps: int = 0
    summary_weight: float = 0.0
    sets: list[dict[str, float]] = field(default_factory=list)
    pointer: int = 0
    default_reps: int = 0
    default_weight: float = 0.0


def render_instant_baseline(
    name: str,
    sets: int,
    reps: int,
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
    lines.append(f"Сейчас: {format_sets_value(sets, reps, weight, with_weight)}")
    return "\n".join(lines)


def instant_baseline_view(info: dict) -> tuple[str, InlineKeyboardMarkup]:
    sets, reps, weight = info["values"]
    with_weight = info.get("with_weight", True)
    kind = info.get("kind", "reps")
    text = render_instant_baseline(
        info["name"], sets, reps, weight, with_weight=with_weight, kind=kind
    )
    kb = baseline_kb(
        info["day"],
        sets,
        reps,
        weight,
        prefix=f"ib:{info['source']}",
        include_skip_all=False,
        with_weight=with_weight,
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
    values = list(existing) if existing else [0, 0, 0.0]
    with_weight, kind = get_display_flags(resolved_group, name)
    if not with_weight:
        values[2] = 0.0
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


def _format_single_value(state: FillEditorState) -> str:
    sets = max(state.summary_sets, 0)
    reps = max(state.summary_reps, 0)
    if state.kind == "duration":
        return f"{sets}×{reps} сек"
    if state.with_weight:
        weight = format_weight_value(max(state.summary_weight, 0.0))
        return f"{sets}×{reps} повт. при {weight} кг"
    return f"{sets}×{reps} повт."


def render_fill_editor(state: FillEditorState, prefs: UiPreferences) -> str:
    icon = emoji_for(prefs, _fill_icon_key(state.group)) if prefs.emoji_enabled else ""
    title = f"{icon} {state.name}".strip() if icon else state.name
    lines = [title, ""]
    if state.mode == "single":
        if state.with_weight:
            lines.append(
                "Укажи количество рабочих сетов, повторения последнего и рабочий вес."
            )
            lines.append(
                "Кнопки ниже помогут быстро записать итоговую нагрузку за тренировку."
            )
            lines.append(
                "Каждый сет сохранится с одинаковыми значениями — удобно, когда весь воркаут выполнен в одном темпе."
            )
        elif state.kind == "duration":
            lines.append(
                "Укажи, сколько подходов выполнил и сколько секунд держалась позиция в последнем."
            )
            lines.append(
                "Используй кнопки, чтобы мгновенно выставить суммарное время."
            )
            lines.append(
                "Сохранится указанное количество подходов, и каждый получит последнюю длительность."
            )
        else:
            lines.append(
                "Укажи, сколько рабочих сетов сделал и сколько повторений было в последнем."
            )
            lines.append(
                "Кнопки позволяют за пару нажатий обновить запись без лишнего набора текста."
            )
            lines.append(
                "Сохранится указанное количество подходов с одинаковым числом повторений."
            )
        lines.append("")
        lines.append(f"Текущее значение: {_format_single_value(state)}")
        return "\n".join(lines)

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
                reps = int(max(item.get("reps", 0), 0))
                value = format_flex_value(reps, 0.0, False, "duration")
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
        reps = int(max(item.get("reps", 0), 0))
        weight = float(max(item.get("weight", 0.0), 0.0)) if state.with_weight else 0.0
        value = format_flex_value(reps, weight, state.with_weight, state.kind)
        lines.append(f"{prefix}{idx}. {value}")
    return "\n".join(lines)


def _single_unit(kind: str) -> str:
    return "сек" if kind == "duration" else "повт"


def _single_major_step(kind: str) -> int:
    return 10 if kind == "duration" else 5


def _build_single_fill_keyboard(state: FillEditorState) -> InlineKeyboardMarkup:
    unit = _single_unit(state.kind)
    major = _single_major_step(state.kind)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("＋1 сет", callback_data="fill:single:inc:sets:1"),
            InlineKeyboardButton("−1 сет", callback_data="fill:single:inc:sets:-1"),
        ],
        [
            InlineKeyboardButton(
                f"＋{major} {unit}", callback_data=f"fill:single:inc:reps:{major}"
            ),
            InlineKeyboardButton(
                f"−{major} {unit}", callback_data=f"fill:single:inc:reps:-{major}"
            ),
        ],
        [
            InlineKeyboardButton(
                f"＋1 {unit}", callback_data="fill:single:inc:reps:1"
            ),
            InlineKeyboardButton(
                f"−1 {unit}", callback_data="fill:single:inc:reps:-1"
            ),
        ],
    ]
    if state.with_weight:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        "＋0.5 кг", callback_data="fill:single:inc:kg:0.5"
                    ),
                    InlineKeyboardButton(
                        "＋1 кг", callback_data="fill:single:inc:kg:1"
                    ),
                    InlineKeyboardButton(
                        "＋5 кг", callback_data="fill:single:inc:kg:5"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "−0.5 кг", callback_data="fill:single:inc:kg:-0.5"
                    ),
                    InlineKeyboardButton(
                        "−1 кг", callback_data="fill:single:inc:kg:-1"
                    ),
                    InlineKeyboardButton(
                        "−5 кг", callback_data="fill:single:inc:kg:-5"
                    ),
                ],
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("Сохранить", callback_data="fill:single:apply"),
            InlineKeyboardButton("Отмена", callback_data="fill:single:cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)


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
    unit = _single_unit(state.kind)
    major = _single_major_step(state.kind)
    rows.append(
        [
            InlineKeyboardButton(
                f"＋{major} {unit}", callback_data=f"fill:flex:inc:reps:{major}"
            ),
            InlineKeyboardButton(
                f"−{major} {unit}", callback_data=f"fill:flex:inc:reps:-{major}"
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                f"＋1 {unit}", callback_data="fill:flex:inc:reps:1"
            ),
            InlineKeyboardButton(
                f"−1 {unit}", callback_data="fill:flex:inc:reps:-1"
            ),
        ]
    )
    if state.with_weight:
        rows.append(
            [
                InlineKeyboardButton(
                    "＋0.5 кг", callback_data="fill:flex:inc:kg:0.5"
                ),
                InlineKeyboardButton(
                    "＋1 кг", callback_data="fill:flex:inc:kg:1"
                ),
                InlineKeyboardButton(
                    "＋5 кг", callback_data="fill:flex:inc:kg:5"
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    "−0.5 кг", callback_data="fill:flex:inc:kg:-0.5"
                ),
                InlineKeyboardButton(
                    "−1 кг", callback_data="fill:flex:inc:kg:-1"
                ),
                InlineKeyboardButton(
                    "−5 кг", callback_data="fill:flex:inc:kg:-5"
                ),
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
    return (
        _build_single_fill_keyboard(state)
        if state.mode == "single"
        else _build_flex_fill_keyboard(state)
    )


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
    text, _, _, name, group, sets, mode_view, new_selected = await render_exercise_view(
        user_id, state.day, state.ue_id, selected, prefs=prefs
    )
    with_weight, kind = get_display_flags(group, name)
    if mode_view == "flex":
        set_flex_selected(context, state.day, state.ue_id, new_selected)
        kb = flex_exercise_view_kb(
            state.day,
            state.ue_id,
            group,
            sets,
            new_selected,
            with_weight=with_weight,
            kind=kind,
        )
    else:
        set_flex_selected(context, state.day, state.ue_id, None)
        step_value = await get_weight_step(user_id) if group == "kb" else None
        amrap_mode = group == "metcon" and name == AMRAP_EXERCISE_NAME
        for_time_mode = group == "metcon" and name == FOR_TIME_EXERCISE_NAME
        kb = exercise_view_kb(
            state.day,
            state.ue_id,
            group,
            step_value,
            amrap_mode,
            for_time_mode,
            with_weight=with_weight,
            kind=kind,
        )
    text, kb = prepare_ui_output(text, kb, prefs)
    await safe_edit_message(q, text, kb)


async def apply_fill_changes(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    state: FillEditorState,
    prefs: UiPreferences,
):
    today_str = await get_user_local_date(user_id)
    session_id = await get_or_create_today_session(user_id, today_str, state.day)
    if state.mode == "single":
        reps = max(state.summary_reps, 0)
        weight = max(state.summary_weight, 0.0) if state.with_weight else 0.0
        template = [(reps, weight) for _ in range(max(state.summary_sets, 0))]
    else:
        template = [
            (
                int(max(item.get("reps", 0), 0)),
                float(max(item.get("weight", 0.0), 0.0)) if state.with_weight else 0.0,
            )
            for item in state.sets
        ]
    await apply_sets_template(session_id, state.ue_id, template)
    if state.mode == "flex":
        if template:
            sets = await fetch_exercise_sets(session_id, state.ue_id)
            if sets:
                target_index = min(state.pointer, len(sets) - 1)
                set_flex_selected(context, state.day, state.ue_id, sets[target_index][0])
            else:
                set_flex_selected(context, state.day, state.ue_id, None)
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
    mode: str,
    is_library: bool,
    sheet_day: int | None,
    sheet_page: int,
    selected_before: int | None,
    prefs: UiPreferences,
):
    ex_id, name, raw_group = await get_exercise_info(ue_id)
    group = resolve_group(name, raw_group)
    with_weight, kind = get_display_flags(group, name)
    baseline = await get_baseline(user_id, day, ex_id)
    last_values = await get_session_last_values(session_id, ue_id)
    sets_rows = await fetch_exercise_sets(session_id, ue_id)
    work_sets = filter_work_sets(sets_rows)
    default_reps = 0
    default_weight = 0.0
    if baseline:
        default_reps = max(baseline[1], 0)
        if with_weight:
            default_weight = max(baseline[2], 0.0)
    elif last_values:
        default_reps = max(last_values[0], 0)
        if with_weight:
            default_weight = max(last_values[1], 0.0)

    if mode == "flex":
        sets_payload: list[dict[str, float]] = [
            {
                "reps": int(max(reps, 0)),
                "weight": float(max(weight, 0.0)) if with_weight else 0.0,
            }
            for _, reps, weight in work_sets
        ]
        if not sets_payload:
            if baseline and baseline[0] > 0:
                sets_payload = [
                    {
                        "reps": max(baseline[1], 0),
                        "weight": baseline[2] if with_weight else 0.0,
                    }
                    for _ in range(baseline[0])
                ]
            elif default_reps or default_weight:
                sets_payload = [
                    {
                        "reps": default_reps,
                        "weight": default_weight if with_weight else 0.0,
                    }
                ]
        pointer = 0
        if sets_payload and selected_before:
            pointer = min(max(selected_before - 1, 0), len(sets_payload) - 1)
        state = FillEditorState(
            mode="flex",
            day=day,
            ue_id=ue_id,
            is_library=is_library,
            with_weight=with_weight,
            kind=kind,
            name=name,
            group=group,
            sheet_day=sheet_day,
            sheet_page=sheet_page,
            selected_before=selected_before,
            sets=sets_payload,
            pointer=pointer,
            default_reps=default_reps,
            default_weight=default_weight if with_weight else 0.0,
        )
    else:
        summary_sets = len(work_sets)
        summary_reps = int(work_sets[-1][1]) if work_sets else default_reps
        summary_weight = (
            float(work_sets[-1][2]) if work_sets and with_weight else default_weight
        )
        if summary_sets == 0 and baseline:
            summary_sets = max(baseline[0], 0)
            summary_reps = max(baseline[1], 0)
            summary_weight = baseline[2] if with_weight else 0.0
        if not with_weight:
            summary_weight = 0.0
        state = FillEditorState(
            mode="single",
            day=day,
            ue_id=ue_id,
            is_library=is_library,
            with_weight=with_weight,
            kind=kind,
            name=name,
            group=group,
            sheet_day=sheet_day,
            sheet_page=sheet_page,
            selected_before=selected_before,
            summary_sets=max(summary_sets, 0),
            summary_reps=max(summary_reps, 0),
            summary_weight=max(summary_weight, 0.0),
            default_reps=default_reps,
            default_weight=default_weight if with_weight else 0.0,
        )
    clear_fill_state(context, q.message.chat_id, q.message.message_id)
    set_fill_state(context, q.message.chat_id, q.message.message_id, state)
    text = render_fill_editor(state, prefs)
    kb = build_fill_keyboard(state)
    text, kb = prepare_ui_output(text, kb, prefs)
    await safe_edit_message(q, text, kb)

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
    action = parts[2]
    if state.mode != mode:
        await q.answer()
        return
    if mode == "single":
        if action == "inc" and len(parts) >= 5:
            field = parts[3]
            delta = float(parts[4])
            if field == "sets":
                state.summary_sets = max(0, state.summary_sets + int(delta))
            elif field == "reps":
                state.summary_reps = max(0, state.summary_reps + int(delta))
            elif field == "kg" and state.with_weight:
                state.summary_weight = max(0.0, state.summary_weight + delta)
        elif action == "apply":
            await apply_fill_changes(q, context, user_id, state, prefs)
            return
        elif action == "cancel":
            await finish_fill_editor(q, context, user_id, state, prefs)
            return
        text = render_fill_editor(state, prefs)
        kb = build_fill_keyboard(state)
        text, kb = prepare_ui_output(text, kb, prefs)
        await safe_edit_message(q, text, kb)
        await q.answer()
        return

    if action == "nav" and len(parts) >= 4 and state.sets:
        delta = int(parts[3])
        state.pointer = max(0, min(state.pointer + delta, len(state.sets) - 1))
    elif action == "add":
        base_reps = state.sets[state.pointer]["reps"] if state.sets else state.default_reps
        base_weight = (
            state.sets[state.pointer]["weight"] if state.sets else state.default_weight
        )
        insert_at = state.pointer + 1 if state.sets else 0
        state.sets.insert(
            insert_at,
            {
                "reps": int(max(base_reps, 0)),
                "weight": float(max(base_weight, 0.0)) if state.with_weight else 0.0,
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
                    "reps": int(max(state.default_reps, 0)),
                    "weight": float(max(state.default_weight, 0.0)) if state.with_weight else 0.0,
                }
            )
            state.pointer = 0
        current = state.sets[state.pointer]
        if target == "reps":
            current["reps"] = max(0, int(current.get("reps", 0) + delta))
        elif target == "kg" and state.with_weight:
            current["weight"] = max(0.0, float(current.get("weight", 0.0) + delta))
    elif action == "apply":
        await apply_fill_changes(q, context, user_id, state, prefs)
        return
    elif action == "cancel":
        await finish_fill_editor(q, context, user_id, state, prefs)
        return
    text = render_fill_editor(state, prefs)
    kb = build_fill_keyboard(state)
    text, kb = prepare_ui_output(text, kb, prefs)
    await safe_edit_message(q, text, kb)
    await q.answer()

MEASUREMENTS_SHOW_ALL_KEY = "measurements_show_all"
MEASUREMENT_INPUT_KEY = "measurement_input"
LIBRARY_CUSTOM_KEY = "library_custom_input"

MEASUREMENT_CATEGORIES = [
    ("body", "A) Масса/состав тела"),
    ("circumference", "B) Окружности"),
    ("records", "C) Производные/силовые контрольные"),
    ("vitals", "D) Витальные показатели"),
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
    _measurement_item("calf", "Икроножная", "circumference", "см"),
    _measurement_item("ankle", "Лодыжка", "circumference", "см", optional=True),
    _measurement_item(
        "bicep_relaxed",
        "Плечо (расслабл.)",
        "circumference",
        "см",
    ),
    _measurement_item(
        "bicep_flexed",
        "Плечо (напряж.)",
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


def measurement_categories_list() -> list[tuple[str, str]]:
    return MEASUREMENT_CATEGORIES


def get_measurement_items(category: str) -> list[dict]:
    return [item for item in MEASUREMENT_ITEMS if item["category"] == category]


def get_measurement_item(code: str) -> dict | None:
    return MEASUREMENT_MAP.get(code)


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
) -> list[tuple[float, str | None, str]]:
    if code in cache:
        return cache[code]
    item = get_measurement_item(code)
    if not item:
        cache[code] = []
        return []
    if item.get("derived") == "lean_mass":
        weight_history = await get_measurement_history(user_id, "body_weight", cache)
        fat_history = await get_measurement_history(user_id, "body_fat", cache)
        history = compute_lean_mass_history(weight_history, fat_history)
    else:
        rows = await fetch_measurement_history(user_id, code, limit=5)
        history = rows or []
    cache[code] = history
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
    last_update = await get_measurements_last_update(user_id)
    header = format_measurements_header(last_update)
    cache: dict[str, list[tuple[float, str | None, str]]] = {}
    lines: list[str] = []
    for code, title in measurement_categories_list():
        items = get_measurement_items(code)
        category_lines: list[str] = []
        for item in items:
            history = await get_measurement_history(user_id, item["code"], cache)
            has_data = bool(history)
            if not has_data and item.get("optional") and not show_all:
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
    return text, measurements_main_kb(show_all)


def summarize_previous_sets(
    sets: list[tuple[int, int, float]],
    mode: str,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> str:
    if not sets:
        return ""
    if mode == "flex":
        return " · ".join(
            f"{no}. {format_flex_value(reps, weight, with_weight, kind)}"
            for no, reps, weight in sets
        )
    reps = sets[-1][1]
    weight = sets[-1][2]
    return format_sets_value(len(sets), reps, weight, with_weight)


def summarize_baseline(
    values: tuple[int, int, float] | None,
    mode: str,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> str:
    if not values:
        return ""
    sets, reps, weight = values
    if mode == "flex":
        return " · ".join(
            f"{i}. {format_flex_value(reps, weight, with_weight, kind)}"
            for i in range(1, sets + 1)
        )
    return format_sets_value(sets, reps, weight, with_weight)


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
    details = []
    if last_done:
        details.append(last_done)
    if summary:
        details.append(summary)
    prefix = f"{mark} " if mark else ""
    if details:
        return f"{prefix}{name} — {' — '.join(details)}".strip()
    return f"{prefix}{name}".strip()


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


def format_plan_value(
    baseline: tuple[int, int, float] | None,
    group_key: str,
    *,
    with_weight: bool = True,
) -> str:
    if not baseline:
        return t("NOT_SET")
    if group_key == "kb":
        value = format_kb_plan(baseline)
        return value if value != "—" else t("NOT_SET")
    sets, reps, weight = baseline
    return format_sets_value(sets, reps, weight, with_weight)


def format_strength_done_value(
    summary: dict[str, int | float] | None, *, with_weight: bool = True
) -> str:
    if not summary:
        detail = "0 повт." if not with_weight else "0 повт. при 0 кг"
        return f"0 (последний {detail})"
    count = int(summary.get("sets_count") or 0)
    reps = int(summary.get("last_reps") or 0)
    weight = float(summary.get("last_weight") or 0.0)
    if with_weight:
        detail = f"{reps} повт. при {format_weight_value(weight)} кг"
    else:
        detail = f"{reps} повт."
    if count <= 0:
        return f"0 (последний {detail})"
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
    mode = await get_recording_mode(user_id)
    last_done_map = build_last_done_dict(await list_last_done_dates(user_id))
    data: list[dict] = []
    for_time_loaded = False
    last_for_time: int | None = None
    for ue_id, name, group, done_flag, ex_id in ex_rows:
        resolved_group = resolve_group(name, group)
        with_weight, kind = get_display_flags(resolved_group, name)
        baseline = await get_baseline(user_id, day_index, ex_id)
        today_sets_full = []
        if session_id:
            today_sets_full = await fetch_exercise_sets(session_id, ue_id)
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
            "with_weight": with_weight,
            "kind": kind,
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
        else:
            work_sets = filter_work_sets(today_sets_full)
            sets_count = len(work_sets)
            last_reps = work_sets[-1][1] if work_sets else 0
            last_weight = work_sets[-1][2] if work_sets else 0.0
            entry["today_summary"] = {
                "sets_count": sets_count,
                "last_reps": last_reps,
                "last_weight": last_weight,
            }
            if resolved_group == "kb":
                entry["prev_summary"] = format_kb_previous(last_sets)
            else:
                entry["prev_summary"] = summarize_previous_sets(
                    last_sets, mode, with_weight=with_weight, kind=kind
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
    step_value = await get_weight_step(user_id)
    step_label = format_weight_value(step_value)
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
        f"Фиксируй подходы кнопками «{t('ADD_SET')}» и «{t('ADD_REP')}».",
        f"Фиксируй подходы кнопками «{t('ADD_SET')}» и «{t('ADD_REP')}». Кнопки «{t('ADD_W', step=step_label)}» меняют рабочий вес во всех карточках, так что учёт ведётся без переходов по меню.",
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
        if group_key == "metcon" and name == AMRAP_EXERCISE_NAME:
            summary = item.get("amrap_summary") or {"rounds": 0, "extra": 0}
            rounds = int(summary.get("rounds") or 0)
            extra = int(summary.get("extra") or 0)
            prev_text = item.get("prev_summary") or t("NOT_FIXED")
            current_text = t("AMRAP_LINE", rounds=rounds, extra=extra)
            lines.append(f"{prefix}{t('METCON_TITLE')} — {t('AMRAP_TITLE')}")
            lines.append(f"• Прошлый раз: {prev_text}")
            lines.append(f"• План: {t('NOT_SET')}")
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
            seconds = fortime.get("last_time_sec")
            if seconds is not None:
                result = format_duration_value(int(seconds))
            else:
                result = t("NOT_FIXED")
            result_line = t("FTIME_LINE", time=result)
            lines.append(f"{prefix}{t('METCON_TITLE')} — {t('FOR_TIME_TITLE')}")
            lines.append(f"• Прошлый раз: {result_line}")
            lines.append(f"• План: {t('NOT_SET')}")
            lines.append(f"• Сегодня: {result_line}")
            kb_rows.append(
                [
                    InlineKeyboardButton(t("DONE"), callback_data=f"ex:done:{day_index}:{ue_id}"),
                    InlineKeyboardButton(t("HISTORY"), callback_data=f"ex:progress:{day_index}:{ue_id}"),
                ]
            )
        else:
            plan_text = format_plan_value(
                item.get("baseline"), group_key, with_weight=with_weight
            )
            done_text = format_strength_done_value(
                item.get("today_summary"), with_weight=with_weight
            )
            last_text = prev_label or t("NOT_FIXED")
            lines.append(f"{prefix}{name}")
            lines.append(f"• Прошлый раз: {last_text}")
            lines.append(f"• План: {plan_text}")
            lines.append(f"• Сегодня: {done_text}")
            step_cb = f"{step_value:g}"
            base_cb = f"ex:inc:{day_index}:{ue_id}"
            add_label = t("ADD_REP") if kind != "duration" else f"{t('ADD_REP')} сек"
            sub_label = "−1" if kind != "duration" else "−1 сек"
            row: list[InlineKeyboardButton] = [
                InlineKeyboardButton(t("ADD_SET"), callback_data=f"ex:addset:{day_index}:{ue_id}"),
                InlineKeyboardButton("− сет", callback_data=f"ex:delset:{day_index}:{ue_id}"),
                InlineKeyboardButton(
                    add_label,
                    callback_data=f"{base_cb}:reps:1",
                ),
            ]
            row.append(
                InlineKeyboardButton(sub_label, callback_data=f"{base_cb}:reps:-1")
            )
            if kind == "duration":
                row.append(
                    InlineKeyboardButton(t("DONE"), callback_data=f"ex:done:{day_index}:{ue_id}")
                )
                kb_rows.append(row)
                kb_rows.append(
                    [
                        InlineKeyboardButton("＋5 сек", callback_data=f"{base_cb}:reps:5"),
                        InlineKeyboardButton("＋10 сек", callback_data=f"{base_cb}:reps:10"),
                    ]
                )
                kb_rows.append(
                    [
                        InlineKeyboardButton("−5 сек", callback_data=f"{base_cb}:reps:-5"),
                        InlineKeyboardButton("−10 сек", callback_data=f"{base_cb}:reps:-10"),
                    ]
                )
                continue
            else:
                if with_weight:
                    row.extend(
                        [
                            InlineKeyboardButton(
                                t("ADD_W", step=step_label),
                                callback_data=f"{base_cb}:kg:{step_cb}",
                            ),
                            InlineKeyboardButton(
                                t("SUB_W", step=step_label),
                                callback_data=f"{base_cb}:kg:{-step_value}",
                            ),
                        ]
                    )
                row.append(
                    InlineKeyboardButton(t("DONE"), callback_data=f"ex:done:{day_index}:{ue_id}")
                )
                kb_rows.append(row)
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
    text, kb = prepare_ui_output(text, kb, prefs)
    old_chat_id = q.message.chat_id
    old_message_id = q.message.message_id
    await safe_edit_message(q, text, reply_markup=kb)
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
        new_msg = await context.bot.send_message(chat_id, text, reply_markup=kb)
        remember_message(chat_id, new_msg.message_id)
        set_sheet_context(context, new_msg.chat_id, new_msg.message_id, day_index, page)


async def send_day_cards_view(
    q,
    user_id: int,
    day: int,
    context: ContextTypes.DEFAULT_TYPE,
    prefs: UiPreferences,
):
    clear_sheet_context(context, q.message.chat_id, q.message.message_id)
    label = await get_day_label(user_id, day)
    today_str = await get_user_local_date(user_id)
    ex_rows = await fetch_day_exercises(user_id, day, today_str)
    custom = await get_custom_groups(user_id, context)
    mode = await get_recording_mode(user_id)
    summaries = await build_summary_map(user_id, day, ex_rows, today_str, mode)
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
    kb = day_kb(day, ex_rows)
    text, kb = prepare_ui_output(text, kb, prefs)
    await safe_edit_message(q, text, reply_markup=kb)


def format_current_training(
    sets: list[tuple[int, int, float, int]],
    mode: str,
    selected: int | None,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> list[str]:
    if mode == "flex":
        if not sets:
            empty = format_sets_value(0, 0, 0.0, with_weight)
            return [f"Текущая тренировка: {empty}"]
        lines = ["Текущая тренировка:"]
        for set_no, reps, weight, _ in sets:
            prefix = "▶︎ " if selected == set_no else ""
            value = format_flex_value(reps, weight, with_weight, kind)
            lines.append(f"{prefix}{set_no}. {value}")
        return lines
    reps = sets[-1][1] if sets else 0
    weight = sets[-1][2] if sets else 0.0
    return [
        f"Текущая тренировка: {format_sets_value(len(sets), reps, weight, with_weight)}"
    ]


def build_flex_session_lines(
    sets: list[tuple[int, int, float, int]],
    selected: int | None,
    *,
    with_weight: bool = True,
    kind: str = "reps",
) -> list[str]:
    work_sets = [(no, reps, weight) for no, reps, weight, warm in sets if not warm]
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
    for no, reps, weight in work_sets:
        marker = ""
        if selected is not None:
            if no < selected:
                marker = "✅ "
            elif no == selected:
                marker = "▶︎ "
        value = format_flex_value(reps, weight, with_weight, kind)
        lines.append(f"{marker}{no}) {value}")
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
    mode: str,
) -> dict[int, str]:
    summary: dict[int, str] = {}
    session_id = await get_session_for_day(user_id, today, day)
    for ue_id, name, group, _, ex_id in ex_rows:
        resolved = resolve_group(name, group)
        with_weight, kind = get_display_flags(resolved, name)
        text = ""
        current_sets_full: list[tuple[int, int, float, int]] = []
        if session_id:
            current_sets_full = await fetch_exercise_sets(session_id, ue_id)
        if resolved == "kb":
            work_sets = filter_work_sets(current_sets_full)
            last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
            base = await get_baseline(user_id, day, ex_id)
            plan = format_kb_plan(base)
            plan_part = f"{t('PLAN')} {plan}" if plan != "—" else f"{t('PLAN')} —"
            done_part = format_kb_summary(work_sets, last_sets)
            text = f"{plan_part} | {done_part}"
        elif resolved == "metcon" and name == AMRAP_EXERCISE_NAME:
            rounds, extra = parse_amrap_sets(current_sets_full)
            last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
            last_rounds, last_extra = parse_amrap_history(last_sets)
            text = format_amrap_summary(rounds, extra, last_rounds, last_extra)
        elif resolved == "metcon" and name == FOR_TIME_EXERCISE_NAME:
            rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=1)
            seconds = None
            if rows:
                value = rows[0][0]
                if value is not None:
                    seconds = int(round(value))
            if seconds is not None:
                text = t("FTIME_LINE", time=format_duration_value(seconds))
            else:
                text = t("FTIME_LINE", time=t("NOT_FIXED"))
        else:
            filtered = [
                (no, reps, weight)
                for no, reps, weight, warm in current_sets_full
                if not warm
            ]
            if filtered:
                text = summarize_previous_sets(
                    filtered, mode, with_weight=with_weight, kind=kind
                )
            if not text:
                last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
                text = summarize_previous_sets(
                    last_sets, mode, with_weight=with_weight, kind=kind
                )
                if not text:
                    base = await get_baseline(user_id, day, ex_id)
                    text = summarize_baseline(
                        base, mode, with_weight=with_weight, kind=kind
                    )
        if text:
            summary[ue_id] = text
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
    mode = await get_recording_mode(user_id)
    summaries = await build_summary_map(user_id, day, ex_rows, today_str, mode)
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
            "Отмечай подходы прямо в списке упражнений. После сохранения строка обновится и покажет актуальный объём и последний рабочий сет.",
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
        lines.append("Пока нет упражнений. Добавь их, чтобы заполнить этот раздел.")
    text = "\n".join(lines)
    kb = day_group_kb(day, group, items)
    text, kb = prepare_ui_output(text, kb, prefs)
    await safe_edit_message(q, text, reply_markup=kb)

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
            "Пока нет упражнений. Нажми «Добавить упражнение», чтобы сохранить их и вести учёт."
        )
    mode = await get_recording_mode(user_id)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    last_done_rows = await list_last_done_dates(user_id)
    last_done_map = build_last_done_dict(last_done_rows)
    lines = [f"{gname}"]
    maybe_hint(
        lines,
        prefs,
        (
            "Открой упражнение, чтобы посмотреть детали.",
            "Открой упражнение, чтобы посмотреть детали. Там доступна история и быстрые кнопки для записи новых подходов.",
        ),
    )
    lines.append("")
    first_entry = True
    for ue_id, name in items:
        ex_id, _, ex_group = await get_exercise_info(ue_id)
        resolved_group = resolve_group(name, ex_group)
        plan_text = t("NOT_SET")
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
            summary = summarize_previous_sets(
                last_sets, mode, with_weight=with_weight, kind=kind
            )
            base = await get_baseline(user_id, 0, ex_id)
            plan_text = format_plan_value(
                base, resolved_group, with_weight=with_weight
            )
            if not summary:
                summary = summarize_baseline(
                    base, mode, with_weight=with_weight, kind=kind
                )
        last = last_done_map.get(ex_id)
        if not first_entry:
            lines.append("")
        first_entry = False
        mark = e("generic")
        prefix = f"{mark} " if mark else ""
        result_text = summary or t("NOT_FIXED")
        lines.append(f"{prefix}{name}")
        lines.append(f"• Последний результат: {result_text}")
        lines.append(f"• План: {plan_text}")
        if last:
            lines.append(f"• Тренировка: {last}")
    lines.append("")
    lines.append("────────")
    maybe_hint(
        lines,
        prefs,
        (
            "Добавь новые упражнения через «Добавить упражнение».",
            "Добавь новые упражнения через «Добавить упражнение». После сохранения их можно прикрепить к тренировочным дням прямо из расписания.",
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
    text, _, ex_id, name, resolved_group, sets, mode_view, new_selected = await render_exercise_view(
        user_id, 0, ue_id, selected, prefs=prefs
    )
    with_weight, kind = get_display_flags(resolved_group, name)
    attachments = await list_exercise_day_links(user_id, ex_id)
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
            "Пока не прикреплено ни к одному дню.",
            "Добавь упражнение через нужный день тренировок, чтобы видеть его в расписании.",
        ]
    full_text = text + "\n\n" + "\n".join(attach_lines)
    if mode_view == "flex":
        set_flex_selected(context, 0, ue_id, new_selected)
        kb = flex_library_exercise_kb(
            ue_id,
            group,
            sets,
            new_selected,
            with_weight=with_weight,
            kind=kind,
        )
    else:
        set_flex_selected(context, 0, ue_id, None)
        step_value = await get_weight_step(user_id) if resolved_group == "kb" else None
        amrap_mode = resolved_group == "metcon" and name == AMRAP_EXERCISE_NAME
        for_time_mode = resolved_group == "metcon" and name == FOR_TIME_EXERCISE_NAME
        kb = library_exercise_kb(
            ue_id,
            group,
            name,
            step_value,
            amrap_mode,
            for_time_mode,
            with_weight=with_weight,
            kind=kind,
        )
    full_text, kb = prepare_ui_output(full_text, kb, prefs)
    await safe_edit_message(q, full_text, reply_markup=kb)
    return ex_id, resolved_group


async def render_exercise_view(
    user_id: int,
    day: int,
    ue_id: int,
    selected_set: int | None = None,
    prefs: UiPreferences | None = None,
):
    ex_id, name, raw_group = await get_exercise_info(ue_id)
    group = resolve_group(name, raw_group)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    mode = await get_recording_mode(user_id)
    session_id = await get_or_create_today_session(user_id, today, day)
    sets = await fetch_exercise_sets(session_id, ue_id)
    baseline = await get_baseline(user_id, day, ex_id)
    last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
    prefs = prefs or await load_ui_preferences(user_id)
    with_weight, kind = get_display_flags(group, name)
    work_sets = [(no, reps, weight) for no, reps, weight, warm in sets if not warm]
    if mode == "flex":
        if work_sets:
            if selected_set is None or all(no != selected_set for no, *_ in work_sets):
                selected_set = work_sets[-1][0]
        else:
            selected_set = None
    icon_key = "strength"
    if group == "kb":
        icon_key = "kb"
    elif group == "metcon":
        icon_key = "metcon"
    icon = emoji_for(prefs, icon_key)
    title = f"{icon} {name}" if icon else name
    if group == "kb":
        summary = build_strength_summary_from_sets(sets)
        prev_text = format_kb_previous(last_sets)
        if not prev_text or prev_text == "—":
            prev_text = t("NOT_FIXED")
        plan_text = format_plan_value(baseline, "kb")
        done_text = format_strength_done_value(summary)
        lines = [
            title,
            "",
            f"{t('LAST_TIME')}: {prev_text}",
            f"{t('PLAN')}: {plan_text}",
            f"{t('MADE')}: {done_text}",
        ]
        return "\n".join(lines), session_id, ex_id, name, group, sets, mode, selected_set
    if group == "metcon" and name == AMRAP_EXERCISE_NAME:
        rounds, extra = parse_amrap_sets(sets)
        last_rounds, last_extra = parse_amrap_history(last_sets)
        last_text = (
            t("AMRAP_RESULT", rounds=last_rounds, extra=last_extra)
            if last_rounds or last_extra
            else t("NOT_FIXED")
        )
        current_text = t("AMRAP_RESULT", rounds=rounds, extra=extra)
        lines = [
            title,
            "",
            f"{t('LAST_TIME')}: {last_text}",
            f"{t('PLAN')}: {t('NOT_SET')}",
            f"{t('MADE')}: {current_text}",
        ]
        return "\n".join(lines), session_id, ex_id, name, group, sets, mode, selected_set
    if group == "metcon" and name == FOR_TIME_EXERCISE_NAME:
        rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=1)
        seconds = None
        if rows:
            value = rows[0][0]
            if value is not None:
                seconds = int(round(value))
        if seconds is not None:
            result_text = t("FTIME_RESULT", time=format_duration_value(seconds))
        else:
            result_text = t("NOT_FIXED")
        lines = [
            title,
            "",
            f"{t('LAST_TIME')}: {result_text}",
            f"{t('PLAN')}: {t('NOT_SET')}",
            f"{t('MADE')}: {result_text}",
        ]
        return "\n".join(lines), session_id, ex_id, name, group, sets, mode, selected_set
    prev_text = summarize_previous_sets(
        last_sets, mode, with_weight=with_weight, kind=kind
    )
    if not prev_text:
        prev_text = summarize_baseline(
            baseline, mode, with_weight=with_weight, kind=kind
        )
    prev_text = prev_text or t("NOT_FIXED")
    plan_text = format_plan_value(baseline, group, with_weight=with_weight)
    summary = build_strength_summary_from_sets(sets)
    done_text = format_strength_done_value(summary, with_weight=with_weight)
    lines = [
        title,
        "",
        f"{t('LAST_TIME')}: {prev_text}",
        f"{t('PLAN')}: {plan_text}",
        f"{t('MADE')}: {done_text}",
    ]
    if mode == "flex":
        lines.append("")
        lines.extend(
            build_flex_session_lines(
                sets,
                selected_set,
                with_weight=with_weight,
                kind=kind,
            )
        )
    return "\n".join(lines), session_id, ex_id, name, group, sets, mode, selected_set


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
        last_id = last_messages.pop(chat_id, None)
        if last_id:
            try:
                await context.bot.delete_message(chat_id, last_id)
            except BadRequest:
                pass
        reply_markup = None
        if user_id:
            days = await list_active_days(user_id)
            reply_markup = main_menu_kb(days, SUPPORT_DEEPLINK)
        text = (
            "Напоминание о тренировке!\n"
            "Открой нужный день и отметь новые подходы, чтобы сохранить прогресс."
        )
        msg = await context.bot.send_message(chat_id, text, reply_markup=reply_markup)
        remember_message(msg.chat_id, msg.message_id)
    except Forbidden:
        try:
            context.job.schedule_removal()
        except Exception:
            pass
    except Exception:
        logger.exception("Reminder job failed")


async def schedule_all_reminders(app: Application):
    for user_id, tg_id, dow, hour, minute in await list_users_with_reminders():
        tz_code = await get_user_timezone(user_id)
        zone = resolve_user_zone(tz_code)
        tm = time(hour=hour, minute=minute, tzinfo=zone)
        app.job_queue.run_daily(
            reminder_job,
            tm,
            days=(dow,),
            chat_id=tg_id,
            name=f"rem_{user_id}_{dow}",
            data={"user_id": user_id},
        )


async def post_init(app: Application):
    await schedule_all_reminders(app)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    u = update.effective_user
    user_id = await get_or_create_user(u.id, u.username)
    settings = await fetch_user_settings(user_id)
    if not settings or not settings[0] or not settings[1]:
        text = (
            "В этом боте ты ведёшь дневник тренировок: сохраняешь упражнения, "
            "отслеживаешь прогресс и получаешь напоминания. "
            "Всё в одном удобном месте — больше не нужно записывать данные где попало.\n\n"
            "Нажми кнопку ниже, чтобы продолжить."
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Ясно, спасибо", callback_data="wiz:intro:ok")]])
        msg = await update.message.reply_text(text, reply_markup=kb)
        remember_message(msg.chat_id, msg.message_id)
        return
    days = await list_active_days(user_id)
    prefs = await load_ui_preferences(user_id)
    text = build_main_menu_text(prefs)
    kb = main_menu_kb(days, SUPPORT_DEEPLINK)
    text, kb = prepare_ui_output(text, kb, prefs)
    msg = await update.message.reply_text(text, reply_markup=kb)
    remember_message(msg.chat_id, msg.message_id)

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
    await safe_edit_message(
        q,
        day_exercises_text(day, group, custom),
        kb,
    )


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
        day, group, ex_rows, selected_ids, page=requested_page
    )
    set_kb_page(context, "day", group, actual_page, day)
    await safe_edit_message(
        q,
        day_exercises_text(day, group, custom),
        reply_markup=kb,
    )

async def finish_day(q, context, user_id: int, day: int, summary: str | None = None):
    n = context.user_data.get("workouts_per_week", 0)
    system = context.user_data.get("system")
    if system == "fullbody":
        await copy_day_plan_to_other_days(user_id, 1, n)
        text = "Присылать напоминания перед тренировками?"
        if summary:
            text = summary + "\n────────\n" + text
        await safe_edit_message(q, text, reply_markup=reminders_kb())
        return
    if day >= n:
        days = await list_active_days(user_id)
        text = "Отлично, супер! Мы сохранили все ваши данные. Теперь можете с удовольствием пользоваться."
        if summary:
            text = summary + "\n────────\n" + text
        await safe_edit_message(
            q,
            text,
            reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK),
        )
    else:
        context.user_data["current_day"] = day
        text = f"{t('DAY')} {day} сохранён. Перейти к {t('DAY')} {day + 1}?"
        if summary:
            text = summary + "\n────────\n" + text
        await safe_edit_message(
            q,
            text,
            reply_markup=day_done_kb(day),
        )

async def advance_day(q, context, user_id: int, next_day: int):
    n = context.user_data.get("workouts_per_week", 0)
    if next_day <= n:
        selected = context.user_data.setdefault("day_groups", {}).get(next_day, set())
        custom = await get_custom_groups(user_id, context)
        await safe_edit_message(
            q,
            day_groups_text(next_day),
            reply_markup=muscle_groups_kb(next_day, selected or set(), custom),
        )
    else:
        await safe_edit_message(
            q,
            "Присылать напоминания перед тренировками?",
            reply_markup=reminders_kb(),
        )

async def wizard_router(q, data: str, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    if data == "wiz:sub:verify":
        if await check_subscription(q.from_user.id, context.bot):
            context.user_data["sub_expiry"] = datetime.now(UTC) + timedelta(days=1)
            text = (
                "В этом боте ты ведёшь дневник тренировок: сохраняешь упражнения, "
                "отслеживаешь прогресс и получаешь напоминания. "
                "Всё в одном удобном месте — больше не нужно записывать данные где попало.\n\n"
                "Нажми кнопку ниже, чтобы продолжить."
            )
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Ясно, спасибо", callback_data="wiz:intro:ok")]]
            )
            await safe_edit_message(q, text, reply_markup=kb)
        else:
            await safe_edit_message(
                q,
                "Прежде чем получить помощника, подпишись на наш канал, чтобы поддержать нас и быть в курсе новостей.",
                reply_markup=subscription_kb(JOIN_URL),
            )
        return
    if data == "wiz:intro:ok":
        text = (
            "Как ты тренируешься?\n\n"
            "Если выбираешь Full Body, мы автоматически применим выбранные упражнения ко всем дням твоих тренировок. "
            "Если выбираешь Split, сможешь настроить упражнения для каждого дня отдельно. "
            "В любом случае ты всегда сможешь добавить или убрать упражнения в любой день."
        )
        await safe_edit_message(q, text, reply_markup=system_kb())
        return
    if data == "wiz:sys:back":
        text = (
            "Как ты тренируешься?\n\n"
            "Если выбираешь Full Body, мы автоматически применим выбранные упражнения ко всем дням твоих тренировок. "
            "Если выбираешь Split, сможешь настроить упражнения для каждого дня отдельно. "
            "В любом случае ты всегда сможешь добавить или убрать упражнения в любой день."
        )
        await safe_edit_message(q, text, reply_markup=system_kb())
        return
    if data.startswith("wiz:sys:"):
        code = data.split(":")[2]
        if code == "help":
            hint = (
                "Фулбоди — за одну тренировку тренируешь всё тело.\n"
                "Сплит — разные группы мышц в разные дни.\n"
                "Если не уверен, выбери «Другое»."
            )
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(t("BACK"), callback_data="wiz:sys:back")]]
            )
            await safe_edit_message(q, hint, reply_markup=kb)
            return
        context.user_data["system"] = code
        await update_user_system(user_id, code)
        await safe_edit_message(
            q,
            "Сколько тренировок планируешь в неделю?",
            reply_markup=days_kb(),
        )
        return
    if data == "wiz:days:back":
        await safe_edit_message(q, "Как ты тренируешься?", reply_markup=system_kb())
        return
    if data.startswith("wiz:days:"):
        n = int(data.split(":")[2])
        await set_workouts_per_week(user_id, n)
        context.user_data["workouts_per_week"] = n
        context.user_data["day_groups"] = {}
        custom = await get_custom_groups(user_id, context)
        await safe_edit_message(
            q,
            day_groups_text(1),
            reply_markup=muscle_groups_kb(1, set(), custom),
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
        ex_id, name, ex_group = baseline_list[idx]
        vals_map = context.user_data.setdefault("baseline_values", {})
        if ex_id not in vals_map:
            existing = await get_baseline(user_id, day, ex_id)
            vals_map[ex_id] = list(existing) if existing else [0, 0, 0.0]
        values = vals_map[ex_id]
        with_weight, _ = get_display_flags(ex_group, name)
        if not with_weight:
            values[2] = 0.0
        done = context.user_data.setdefault("baseline_done", [])
        if action == "inc":
            field = parts[3]
            delta = float(parts[4])
            if field == "sets":
                values[0] = max(0, values[0] + int(delta))
            elif field == "reps":
                values[1] = max(0, values[1] + int(delta))
            elif field == "kg" and with_weight:
                values[2] = max(0.0, values[2] + delta)
            await safe_edit_message(
                q,
                render_baseline_progress(
                    done, name, *values, with_weight=with_weight
                ),
                baseline_kb(day, *values, with_weight=with_weight),
            )
            return
        if action == "ready":
            await set_baseline(
                user_id,
                day,
                ex_id,
                values[0],
                values[1],
                values[2] if with_weight else 0.0,
            )
            done.append(f"{baseline_text(name, *values, with_weight=with_weight)} ✅")
            idx += 1
            if idx < len(baseline_list):
                context.user_data["baseline_idx"] = idx
                ex_id, name, ex_group = baseline_list[idx]
                if ex_id not in vals_map:
                    existing = await get_baseline(user_id, day, ex_id)
                    vals_map[ex_id] = list(existing) if existing else [0, 0, 0.0]
                values = vals_map[ex_id]
                next_with_weight, _ = get_display_flags(ex_group, name)
                if not next_with_weight:
                    values[2] = 0.0
                await safe_edit_message(
                    q,
                    render_baseline_progress(
                        done, name, *values, with_weight=next_with_weight
                    ),
                    baseline_kb(day, *values, with_weight=next_with_weight),
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
                    vals_map[ex_id] = list(existing) if existing else [0, 0, 0.0]
                values = vals_map[ex_id]
                next_with_weight, _ = get_display_flags(ex_group, name)
                if not next_with_weight:
                    values[2] = 0.0
                await safe_edit_message(
                    q,
                    render_baseline_progress(
                        done, name, *values, with_weight=next_with_weight
                    ),
                    baseline_kb(day, *values, with_weight=next_with_weight),
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
                prev_with_weight, _ = get_display_flags(ex_group, name)
                if not prev_with_weight:
                    values[2] = 0.0
                await safe_edit_message(
                    q,
                    render_baseline_progress(
                        done, name, *values, with_weight=prev_with_weight
                    ),
                    baseline_kb(day, *values, with_weight=prev_with_weight),
                )
            else:
                context.user_data.pop("baseline_day", None)
                context.user_data.pop("baseline_list", None)
                context.user_data.pop("baseline_idx", None)
                context.user_data.pop("baseline_values", None)
                context.user_data.pop("baseline_done", None)
                selected = context.user_data.setdefault("day_groups", {}).get(day, set())
                custom = await get_custom_groups(user_id, context)
                await safe_edit_message(
                    q,
                    day_groups_text(day),
                    reply_markup=muscle_groups_kb(day, selected, custom),
                )
            return
    if data.startswith("wiz:day:"):
        parts = data.split(":")
        day = int(parts[2])
        if parts[3] == "back":
            await safe_edit_message(
                q,
                "Сколько тренировок планируешь в неделю?",
                reply_markup=days_kb(),
            )
            return
        if parts[3] == "redo":
            selected = context.user_data.setdefault("day_groups", {}).get(day, set())
            custom = await get_custom_groups(user_id, context)
            await safe_edit_message(
                q,
                day_groups_text(day),
                reply_markup=muscle_groups_kb(day, selected, custom),
            )
            return
        if parts[3] == "mg":
            group = parts[4]
            if group == "other":
                context.user_data["awaiting_group_name"] = (day, q.message.chat_id, q.message.message_id, "wizard")
                await safe_edit_message(
                    q,
                    f"Укажи группу мышц для дня {day}, которой нет в списке.",
                )
                return
            selected = context.user_data.setdefault("day_groups", {}).setdefault(day, set())
            if group in selected:
                selected.remove(group)
            else:
                selected.add(group)
            custom = await get_custom_groups(user_id, context)
            await safe_edit_message(
                q,
                day_groups_text(day),
                reply_markup=muscle_groups_kb(day, selected, custom),
            )
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
                        await safe_edit_message(q, text, kb)

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
                await safe_edit_message(q, "Напиши название упражнения:", reply_markup=kb)
                return
            if action == "custom_back":
                group = parts[5]
                await show_exercises(q, user_id, day, group, context)
                return
            if action == "back":
                selected = context.user_data.setdefault("day_groups", {}).get(day, set())
                custom = await get_custom_groups(user_id, context)
                await safe_edit_message(
                    q,
                    day_groups_text(day),
                    reply_markup=muscle_groups_kb(day, selected, custom),
                )
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
                        vals_map[ex_id] = list(existing) if existing else [0, 0, 0.0]
                        vals = vals_map[ex_id]
                        first_with_weight, _ = get_display_flags(ex_group, name)
                        if not first_with_weight:
                            vals[2] = 0.0
                        await safe_edit_message(
                            q,
                            render_baseline_progress(
                                [], name, *vals, with_weight=first_with_weight
                            ),
                            reply_markup=baseline_kb(
                                day, *vals, with_weight=first_with_weight
                            ),
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
    if data == "wiz:finish_early":
        day = context.user_data.get("current_day", 0)
        n = context.user_data.get("workouts_per_week", 0)
        if day < n:
            context.user_data["confirm_finish_day"] = day
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Да", callback_data="wiz:finish_yes"), InlineKeyboardButton("Нет", callback_data="wiz:finish_no")]]
            )
            await safe_edit_message(
                q,
                f"У тебя было заявлено {n} тренировок. Завершить на {day}?",
                reply_markup=kb,
            )
        else:
            days = await list_active_days(user_id)
            await safe_edit_message(
                q,
                "Настройка завершена.",
                reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK),
            )
        return
    if data == "wiz:finish_yes":
        days = await list_active_days(user_id)
        await safe_edit_message(
            q,
            "Настройка завершена.",
            reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK),
        )
        return
    if data == "wiz:finish_no":
        day = context.user_data.get("confirm_finish_day", 1)
        await safe_edit_message(
            q,
            f"{t('DAY')} {day} сохранён. Перейти к {t('DAY')} {day + 1}?",
            reply_markup=day_done_kb(day),
        )
        return
    if data == "wiz:reminders:yes":
        context.user_data["tz_page"] = 0
        if "workouts_per_week" not in context.user_data:
            settings = await fetch_user_settings(user_id)
            context.user_data["workouts_per_week"] = settings[1] if settings else 0
        await safe_edit_message(q, "Выбери свой часовой пояс:", reply_markup=tz_select_kb(0))
        return
    if data == "wiz:reminders:no":
        if context.user_data.get("from_settings"):
            context.user_data.pop("from_settings", None)
            await safe_edit_message(q, "Настройки:", reply_markup=settings_kb())
        else:
            days = await list_active_days(user_id)
            await safe_edit_message(
                q,
                "Настройка завершена.",
                reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK),
            )
        return
    if data == "wiz:reminders:back":
        if context.user_data.get("from_settings"):
            context.user_data.pop("from_settings", None)
            await safe_edit_message(q, "Настройки:", reply_markup=settings_kb())
        else:
            day = context.user_data.get("current_day", 1)
            await safe_edit_message(
                q,
                f"{t('DAY')} {day} сохранён. Перейти к {t('DAY')} {day + 1}?",
                reply_markup=day_done_kb(day),
            )
        return
    if data.startswith("wiz:tzsel:"):
        parts = data.split(":")
        action = parts[2]
        if action == "page":
            page = int(parts[3])
            context.user_data["tz_page"] = page
            await safe_edit_message(q, "Выбери свой часовой пояс:", reply_markup=tz_select_kb(page))
        elif action == "set":
            tz = parts[3]
            context.user_data["tz"] = tz
            await set_user_timezone(user_id, tz)
            tz_only_change = context.user_data.pop("tz_only_change", None)
            editing_times = context.user_data.pop("edit_reminders", None)
            if editing_times:
                await clear_user_reminders(user_id)
                for job in context.job_queue.jobs():
                    if job.name and job.name.startswith(f"rem_{user_id}_"):
                        job.schedule_removal()
            day_no = context.user_data.get("reminder_day", 1)
            if editing_times:
                context.user_data["reminder_day"] = day_no
                await safe_edit_message(
                    q,
                    f"{t('DAY')} {day_no}. В какой день недели тренировка?",
                    reply_markup=reminder_day_kb(),
                )
            elif tz_only_change:
                tz_label = next((label for code, label in TIMEZONES if code == tz), tz)
                rems = await list_user_reminders(user_id)
                if rems:
                    parts = [f"{dict(WEEKDAYS)[d]} {h:02d}:{m:02d}" for d, h, m in rems]
                    rem_text = ", ".join(parts)
                    text = f"Часовой пояс обновлён: {tz_label}. Напоминания: {rem_text}."
                else:
                    text = f"Часовой пояс обновлён: {tz_label}. Напоминания пока не настроены."
                await safe_edit_message(q, text, reply_markup=reminders_edit_kb())
            else:
                context.user_data["reminder_day"] = day_no
                await safe_edit_message(
                    q,
                    f"{t('DAY')} {day_no}. В какой день недели тренировка?",
                    reply_markup=reminder_day_kb(),
                )
        elif action == "back":
            if context.user_data.get("from_settings"):
                context.user_data.pop("from_settings", None)
                await safe_edit_message(q, "Настройки:", reply_markup=settings_kb())
            else:
                await safe_edit_message(
                    q,
                    "Присылать напоминания перед тренировками?",
                    reply_markup=reminders_kb(),
                )
        return
    if data.startswith("wiz:rday:"):
        action = data.split(":")[2]
        if action == "back":
            page = context.user_data.get("tz_page", 0)
            await safe_edit_message(q, "Выбери свой часовой пояс:", reply_markup=tz_select_kb(page))
        else:
            context.user_data["selected_dow"] = int(action)
            await safe_edit_message(
                q,
                "Во сколько напоминать в этот день? Выбери время (по твоему часовому поясу)",
                reply_markup=reminder_time_kb(),
            )
        return
    if data == "wiz:remind:back":
        day_no = context.user_data.get("reminder_day", 1)
        await safe_edit_message(
            q,
            f"{t('DAY')} {day_no}. В какой день недели тренировка?",
            reply_markup=reminder_day_kb(),
        )
        return
    if data.startswith("wiz:remind:"):
        _, _, hh, mm = data.split(":")
        hour, minute = int(hh), int(mm)
        dow = context.user_data.get("selected_dow")
        await add_user_reminder(user_id, dow, hour, minute)
        tz = context.user_data.get("tz", "UTC")
        zone = resolve_user_zone(tz)
        reminder_time = time(hour, minute, tzinfo=zone)
        job_name = f"rem_{user_id}_{dow}"
        for job in context.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()
        context.job_queue.run_daily(
            reminder_job,
            reminder_time,
            days=(dow,),
            chat_id=q.message.chat_id,
            name=job_name,
            data={"user_id": user_id},
        )
        day_no = context.user_data.get("reminder_day", 1)
        total = context.user_data.get("workouts_per_week", 0)
        if day_no < total:
            context.user_data["reminder_day"] = day_no + 1
            await safe_edit_message(
                q,
                f"{t('DAY')} {day_no + 1}. В какой день недели тренировка?",
                reply_markup=reminder_day_kb(),
            )
            return
        if context.user_data.get("from_settings"):
            context.user_data.pop("from_settings", None)
            await safe_edit_message(q, "Настройки:", reply_markup=settings_kb())
        else:
            days = await list_active_days(user_id)
            await safe_edit_message(
                q,
                "Настройка завершена.",
                reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK),
            )
        return

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    for_time_state = context.user_data.get(FOR_TIME_INPUT_KEY)
    if for_time_state:
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
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
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
                text, _, _, name, group, sets, mode_view, new_selected = await render_exercise_view(
                    user_id, day, ue_id, selected, prefs=prefs
                )
                with_weight, kind = get_display_flags(group, name)
                if mode_view == "flex":
                    set_flex_selected(context, day, ue_id, new_selected)
                    kb = (
                        flex_library_exercise_kb(
                            ue_id,
                            group,
                            sets,
                            new_selected,
                            with_weight=with_weight,
                            kind=kind,
                        )
                        if is_library
                        else flex_exercise_view_kb(
                            day,
                            ue_id,
                            group,
                            sets,
                            new_selected,
                            with_weight=with_weight,
                            kind=kind,
                        )
                    )
                else:
                    set_flex_selected(context, day, ue_id, None)
                    step_value = await get_weight_step(user_id) if group == "kb" else None
                    amrap_mode = group == "metcon" and name == AMRAP_EXERCISE_NAME
                    for_time_mode = group == "metcon" and name == FOR_TIME_EXERCISE_NAME
                    if is_library:
                        kb = library_exercise_kb(
                            ue_id,
                            group,
                            name,
                            step_value,
                            amrap_mode,
                            for_time_mode,
                            with_weight=with_weight,
                            kind=kind,
                        )
                    else:
                        kb = exercise_view_kb(
                            day,
                            ue_id,
                            group,
                            step_value,
                            amrap_mode,
                            for_time_mode,
                            with_weight=with_weight,
                            kind=kind,
                        )
            text, kb = prepare_ui_output(text, kb, prefs)
            await context.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=kb,
            )
            remember_message(chat_id, msg_id)
        return
    input_state = context.user_data.get(MEASUREMENT_INPUT_KEY)
    if input_state:
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
        text_view, _, _, name, group, sets, mode_view, new_selected = await render_exercise_view(
            user_id, day, ue_id, selected, prefs=prefs
        )
        is_library = day == 0
        with_weight, kind = get_display_flags(group, name)
        if mode_view == "flex":
            set_flex_selected(context, day, ue_id, new_selected)
            kb = (
                flex_library_exercise_kb(
                    ue_id,
                    group,
                    sets,
                    new_selected,
                    with_weight=with_weight,
                    kind=kind,
                )
                if is_library
                else flex_exercise_view_kb(
                    day,
                    ue_id,
                    group,
                    sets,
                    new_selected,
                    with_weight=with_weight,
                    kind=kind,
                )
            )
        else:
            set_flex_selected(context, day, ue_id, None)
            if is_library:
                step_value = await get_weight_step(user_id) if group == "kb" else None
                amrap_mode = group == "metcon" and name == AMRAP_EXERCISE_NAME
                for_time_mode = group == "metcon" and name == FOR_TIME_EXERCISE_NAME
                kb = library_exercise_kb(
                    ue_id,
                    group,
                    name,
                    step_value,
                    amrap_mode,
                    for_time_mode,
                    with_weight=with_weight,
                    kind=kind,
                )
            else:
                step_value = await get_weight_step(user_id) if group == "kb" else None
                kb = exercise_view_kb(
                    day,
                    ue_id,
                    group,
                    step_value,
                    group == "metcon" and name == AMRAP_EXERCISE_NAME,
                    group == "metcon" and name == FOR_TIME_EXERCISE_NAME,
                    with_weight=with_weight,
                    kind=kind,
                )
        if chat_id and msg_id:
            text_view, kb = prepare_ui_output(text_view, kb, prefs)
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
            group, ex_rows, selected, page=requested_page
        )
        set_kb_page(context, "lib", group, page_value)
        await context.bot.edit_message_text(
            "Выбери упражнения:",
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=kb,
        )
        remember_message(chat_id, msg_id)
        return
    if context.user_data.get("awaiting_group_name"):
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
        else:
            context.user_data["add_group"] = (day, code)
            ex_rows = await list_exercises_by_group(code)
            selected_ids = set(await list_user_exercise_ids(user_id, day, code))
            requested_page = get_kb_page(context, "day", code, day)
            kb, page_value, _ = day_add_exercises_kb(
                day, code, ex_rows, selected_ids, page=requested_page
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
        day, chat_id, msg_id = context.user_data.pop("awaiting_rename")
        label = update.message.text.strip()
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
        await rename_day(user_id, day, label)
        await try_delete(update.message)
        await context.bot.edit_message_text("Настройки:", chat_id=chat_id, message_id=msg_id, reply_markup=settings_kb())
        remember_message(chat_id, msg_id)
        return
    if context.user_data.get("awaiting_custom"):
        day, group, chat_id, msg_id = context.user_data.pop("awaiting_custom")
        name = normalize_whitespace(update.message.text or "")
        if not name:
            context.user_data["awaiting_custom"] = (day, group, chat_id, msg_id)
            await update.message.reply_text("Название не должно быть пустым.")
            return
        await try_delete(update.message)
        ex_id = await get_or_create_exercise(name, group)
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
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
                day, group, ex_rows, selected_ids, page=requested_page
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

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await require_subscription(update, context):
        return
    data = q.data
    if data == "noop":
        return
    u = update.effective_user
    user_id = await get_or_create_user(u.id, u.username)
    remember_message(q.message.chat_id, q.message.message_id)

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
            elif field == "kg" and with_weight:
                values[2] = max(0.0, values[2] + delta)
            text, kb = instant_baseline_view(info)
            await safe_edit_message(q, text, kb)
            return
        if action == "ready":
            await set_baseline(
                user_id,
                info["day"],
                info["exercise_id"],
                values[0],
                values[1],
                values[2] if with_weight else 0.0,
            )
            await finish_instant_baseline(q, context, user_id, info)
            return
        if action in ("skip", "back"):
            await finish_instant_baseline(q, context, user_id, info)
            return
        return

    if data.startswith("wiz:"):
        await wizard_router(q, data, user_id, context)
        return

    if data == "menu:root":
        days = await list_active_days(user_id)
        prefs = await load_ui_preferences(user_id)
        text = build_main_menu_text(prefs)
        kb = main_menu_kb(days, SUPPORT_DEEPLINK)
        text, kb = prepare_ui_output(text, kb, prefs)
        await safe_edit_message(q, text, reply_markup=kb)
        return

    if data in ("menu:library", "lib:root"):
        context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
        await ensure_library_history(user_id)
        groups = await list_library_groups(user_id)
        custom = await get_custom_groups(user_id, context)
        prefs = await load_ui_preferences(user_id)
        text = "Мои упражнения:"
        kb = library_menu_kb(groups, custom)
        text, kb = prepare_ui_output(text, kb, prefs)
        await safe_edit_message(q, text, reply_markup=kb)
        return

    if data == "menu:metrics":
        context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
        prefs = await load_ui_preferences(user_id)
        text, kb = await build_measurements_view(user_id, context)
        text, kb = prepare_ui_output(text, kb, prefs)
        await safe_edit_message(q, text, kb)
        return

    if data == "menu:settings":
        settings = await fetch_user_settings(user_id)
        n = settings[1] if settings else 0
        tz = await get_user_timezone(user_id)
        rems = await list_user_reminders(user_id)
        tz_label = next((label for code, label in TIMEZONES if code == tz), tz)
        if rems:
            parts = [f"{dict(WEEKDAYS)[d]} {h:02d}:{m:02d}" for d, h, m in rems]
            rem_text = ", ".join(parts)
        else:
            rem_text = t("NOT_SET")
        prefs = await load_ui_preferences(user_id)
        mode_label = "Компактный" if prefs.mode == "compact" else "Подробный"
        emoji_label = "включены" if prefs.emoji_enabled else "выключены"
        verbose_label = "обычные пояснения" if prefs.verbose_level else "краткие пояснения"
        text = (
            "Настройки:\n"
            "Выбирай пункт ниже, чтобы обновить дневник под себя.\n"
            "────────\n"
            "✏️ Переименовать дни — поменять названия тренировочных дней.\n"
            "🔁 Изменить день — переключи тип тренировки (силовая, гири, кроссфит, воркаут) и открой подходящие упражнения. После переключения можно добавлять упражнения из любых групп.\n"
            f"📅 Количество тренировок — сейчас {n}. Укажи, сколько раз планируешь тренироваться.\n"
            f"🎨 Оформление интерфейса — режим {mode_label.lower()}, эмодзи {emoji_label}, пояснения: {verbose_label}.\n"
            f"🏋️ Шаг веса — задай шаг изменения (0.5/1/2/5 кг). Кнопки «{t('ADD_W', step='шаг ')}» и «{t('SUB_W', step='шаг ')}» используют это значение во всех упражнениях для прибавки и убавки веса.\n"
            "📝 Выбор записи — расскажи боту, как фиксировать подходы. Бот хранит каждый рабочий сет, в том числе парные (левая/правая, две гири подряд).\n"
            "   • Одинаковый вес — каждый сет с одной схемой повторов и веса.\n"
            "   • Гибкая запись — настраивай вес и повторы отдельно для каждого подхода.\n"
            f"⏰ Уведомления — {tz_label}, {rem_text}. Настрой время напоминаний.\n"
            "⭐ Подписка — информация о подписке."
        )
        kb = settings_kb()
        text, kb = prepare_ui_output(text, kb, prefs)
        await safe_edit_message(q, text, reply_markup=kb)
        return

    if data == "measure:back":
        context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
        text, kb = await build_measurements_view(user_id, context)
        await safe_edit_message(q, text, kb)
        return

    if data == "measure:toggle":
        context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
        current = context.user_data.get(MEASUREMENTS_SHOW_ALL_KEY, False)
        context.user_data[MEASUREMENTS_SHOW_ALL_KEY] = not current
        text, kb = await build_measurements_view(user_id, context)
        await safe_edit_message(q, text, kb)
        return

    if data == "measure:graph":
        await q.answer("Графики появятся позже.", show_alert=True)
        return

    if data == "measure:add":
        context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
        categories = measurement_categories_list()
        await safe_edit_message(
            q,
            "Выбери категорию:",
            reply_markup=measurements_category_kb("add", categories),
        )
        return

    if data.startswith("measure:add:cat:"):
        context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
        parts = data.split(":")
        category = parts[3]
        metrics = [
            (item["code"], item["name"])
            for item in get_measurement_items(category)
            if not item.get("derived")
        ]
        if not metrics:
            await q.answer("Нет показателей для ввода.", show_alert=True)
            return
        await safe_edit_message(
            q,
            "Выбери показатель:",
            reply_markup=measurements_metric_kb("add", category, metrics),
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
        await safe_edit_message(q, item["prompt"], reply_markup=kb)
        return

    if data == "measure:edit":
        context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
        rows = await list_measurement_metrics(user_id)
        metrics = []
        for code, _ in rows:
            item = get_measurement_item(code)
            if item and not item.get("derived"):
                metrics.append((code, item["name"]))
        if not metrics:
            await q.answer("Пока нечего изменять.", show_alert=True)
            return
        await safe_edit_message(
            q,
            "Что изменить?",
            reply_markup=measurements_existing_kb("edit", metrics),
        )
        return

    if data.startswith("measure:edit:metric:"):
        parts = data.split(":")
        code = parts[3]
        item = get_measurement_item(code)
        if not item:
            await q.answer()
            return
        history = await fetch_measurement_history(user_id, code, limit=1)
        prefix = ""
        if history:
            prefix = f"Текущее значение — {format_measurement_value(item, history[0])}.\n\n"
        context.user_data[MEASUREMENT_INPUT_KEY] = {
            "action": "edit",
            "metric": code,
            "chat_id": q.message.chat_id,
            "message_id": q.message.message_id,
        }
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(t("BACK"), callback_data="measure:edit")]]
        )
        await safe_edit_message(q, prefix + item["prompt"], reply_markup=kb)
        return

    if data == "measure:delete":
        context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
        rows = await list_measurement_metrics(user_id)
        metrics = []
        for code, _ in rows:
            item = get_measurement_item(code)
            if item:
                metrics.append((code, item["name"]))
        if not metrics:
            await q.answer("Пока нечего удалять.", show_alert=True)
            return
        await safe_edit_message(
            q,
            "Что удалить? Удалим только последнее значение.",
            reply_markup=measurements_existing_kb("delete", metrics),
        )
        return

    if data.startswith("measure:delete:metric:"):
        parts = data.split(":")
        code = parts[3]
        removed = await delete_last_measurement(user_id, code)
        if not removed:
            await q.answer("Нет данных для удаления.", show_alert=True)
            return
        text, kb = await build_measurements_view(user_id, context)
        await safe_edit_message(q, text, kb)
        return

    parts = data.split(":")
    if parts[0] == "fill":
        prefs = await load_ui_preferences(user_id)
        await handle_fill_callback(q, context, user_id, data, prefs)
        return
    if parts[0] == "lib":
        action = parts[1]
        prefs = await load_ui_preferences(user_id)
        if action == "group":
            group = parts[2]
            items = await list_library_exercises(user_id, group)
            text = await render_library_group_text(user_id, group, items, context, prefs=prefs)
            kb = library_group_kb(group, items)
            text, kb = prepare_ui_output(text, kb, prefs)
            await safe_edit_message(q, text, reply_markup=kb)
            return
        if action == "groupdel":
            group = parts[2]
            if not group.startswith("u"):
                await q.answer("Эту группу нельзя удалить.", show_alert=True)
                return
            custom = await get_custom_groups(user_id, context)
            gname = MG_NAMES.get(group, custom.get(group, group))
            if len(parts) == 3:
                text = (
                    f"Удалить группу «{gname}»?\n"
                    "Все упражнения из неё исчезнут из библиотеки и расписания."
                )
                text, kb = prepare_ui_output(text, confirm_library_group_delete_kb(group), prefs)
                await safe_edit_message(q, text, reply_markup=kb)
                return
            if len(parts) >= 4 and parts[3] == "ok":
                removed = await remove_user_muscle_group(user_id, group)
                if not removed:
                    await q.answer("Не удалось удалить группу.", show_alert=True)
                    items = await list_library_exercises(user_id, group)
                    text = await render_library_group_text(user_id, group, items, context, prefs=prefs)
                    kb = library_group_kb(group, items)
                    text, kb = prepare_ui_output(text, kb, prefs)
                    await safe_edit_message(q, text, reply_markup=kb)
                    return
                custom.pop(group, None)
                groups = await list_library_groups(user_id)
                menu = library_menu_kb(groups, custom)
                text = "Мои упражнения:"
                text, menu = prepare_ui_output(text, menu, prefs)
                await q.answer("Группа удалена.")
                await safe_edit_message(q, text, reply_markup=menu)
                return
            return
        if action == "ex":
            group = parts[2]
            ue_id = int(parts[3])
            await show_library_exercise_view(q, user_id, group, ue_id, context)
            return
        if action == "delmenu":
            group = parts[2]
            items = await list_library_exercises(user_id, group)
            await safe_edit_message(
                q,
                "Удалить упражнение:",
                reply_markup=library_delete_kb(group, items),
            )
            return
        if action == "del":
            group = parts[2]
            ue_id = int(parts[3])
            await remove_user_exercise(user_id, 0, ue_id)
            items = await list_library_exercises(user_id, group)
            await safe_edit_message(
                q,
                "Удалить упражнение:",
                reply_markup=library_delete_kb(group, items),
            )
            return
        if action == "add":
            sub = parts[2]
            if sub == "start":
                target = None
                if len(parts) > 3:
                    target = ("group", parts[3])
                context.user_data["lib_return"] = target
                custom = await get_custom_groups(user_id, context)
                kb = library_add_group_kb(custom)
                text, kb = prepare_ui_output("Выбери группу:", kb, prefs)
                await safe_edit_message(q, text, reply_markup=kb)
                return
            if sub == "mg":
                group = parts[3]
                context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
                ex_rows = await list_exercises_by_group(group)
                selected = set(await list_user_exercise_ids(user_id, 0, group))
                requested_page = get_kb_page(context, "lib", group)
                kb, page_value, _ = library_add_exercises_kb(
                    group, ex_rows, selected, page=requested_page
                )
                set_kb_page(context, "lib", group, page_value)
                text, kb = prepare_ui_output("Выбери упражнения:", kb, prefs)
                await safe_edit_message(q, text, reply_markup=kb)
                return
            if sub == "page":
                group = parts[3]
                requested_page = int(parts[4]) if len(parts) > 4 else 0
                ex_rows = await list_exercises_by_group(group)
                selected = set(await list_user_exercise_ids(user_id, 0, group))
                kb, page_value, _ = library_add_exercises_kb(
                    group, ex_rows, selected, page=requested_page
                )
                set_kb_page(context, "lib", group, page_value)
                text, kb = prepare_ui_output("Выбери упражнения:", kb, prefs)
                await safe_edit_message(q, text, reply_markup=kb)
                return
            if sub == "ex":
                group = parts[3]
                context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
                ex_id = int(parts[4])
                await toggle_user_exercise(user_id, 0, ex_id)
                ex_rows = await list_exercises_by_group(group)
                selected = set(await list_user_exercise_ids(user_id, 0, group))
                requested_page = get_kb_page(context, "lib", group)
                kb, page_value, _ = library_add_exercises_kb(
                    group, ex_rows, selected, page=requested_page
                )
                set_kb_page(context, "lib", group, page_value)
                text, kb = prepare_ui_output("Выбери упражнения:", kb, prefs)
                await safe_edit_message(q, text, reply_markup=kb)
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
                await safe_edit_message(q, "Как назвать упражнение?", reply_markup=kb)
                remember_message(q.message.chat.id, q.message.message_id)
                return
            if sub == "back":
                context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
                custom = await get_custom_groups(user_id, context)
                target = context.user_data.get("lib_return")
                if target and target[0] == "group":
                    group = target[1]
                    items = await list_library_exercises(user_id, group)
                    text = await render_library_group_text(user_id, group, items, context, prefs=prefs)
                    kb = library_group_kb(group, items)
                    text, kb = prepare_ui_output(text, kb, prefs)
                    await safe_edit_message(q, text, reply_markup=kb)
                else:
                    kb = library_add_group_kb(custom)
                    text, kb = prepare_ui_output("Выбери группу:", kb, prefs)
                    await safe_edit_message(q, text, reply_markup=kb)
                return
            if sub == "done":
                context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
                target = context.user_data.pop("lib_return", None)
                if target and target[0] == "group":
                    group = target[1]
                    items = await list_library_exercises(user_id, group)
                    text = await render_library_group_text(user_id, group, items, context, prefs=prefs)
                    kb = library_group_kb(group, items)
                    text, kb = prepare_ui_output(text, kb, prefs)
                    await safe_edit_message(q, text, reply_markup=kb)
                else:
                    groups = await list_library_groups(user_id)
                    custom = await get_custom_groups(user_id, context)
                    kb = library_menu_kb(groups, custom)
                    text, kb = prepare_ui_output("Мои упражнения:", kb, prefs)
                    await safe_edit_message(q, text, reply_markup=kb)
                return

    if parts[0] == "set":
        action = parts[1]
        if action == "rename_day":
            if len(parts) == 2:
                days = await list_active_days(user_id)
                await safe_edit_message(q, "Выбери день:", reply_markup=rename_day_kb(days))
            else:
                day = int(parts[2])
                context.user_data["awaiting_rename"] = (day, q.message.chat.id, q.message.message_id)
                await safe_edit_message(q, f"Новое название для Дня {day}:")
            return
        if action == "edit_day":
            prefs = await load_ui_preferences(user_id)
            if len(parts) == 2:
                days = await list_active_days(user_id)
                text = "Какой день изменить?"
                kb = edit_day_select_kb(days)
                text, kb = prepare_ui_output(text, kb, prefs)
                await safe_edit_message(q, text, reply_markup=kb)
            else:
                day = int(parts[2])
                label = await get_day_label(user_id, day) or f"{t('DAY')} {day}"
                if len(parts) == 3:
                    text = (
                        f"{t('DAY')} {day} — {label}.\n"
                        "Выбери основной тип тренировки. Силовая откроет группы мышц, остальные режимы сразу ведут в свой каталог. После выбора можно добавлять упражнения из любых групп через меню дня."
                    )
                    kb = edit_day_mode_kb(day)
                else:
                    mode = parts[3]
                    if mode == "strength":
                        text = (
                            f"{t('DAY')} {day} — {label}.\n"
                            "Открой список групп мышц, выбери нужные и добавь упражнения. В любой момент можешь расширить тренировку другими направлениями через «Добавить упражнение»."
                        )
                        kb = edit_day_strength_kb(day)
                    elif mode in {"kb", "metcon", "workout"}:
                        labels = {
                            "kb": "Каталог гиревых упражнений",
                            "metcon": "Каталог кроссфита",
                            "workout": "Каталог воркаута",
                        }
                        descriptions = {
                            "kb": "Подбери упражнения с гирями. После добавления можно дополнять день силовыми или другими упражнениями.",
                            "metcon": "Открой подборку кроссфит-упражнений и собери тренировку. Другие группы всегда доступны через меню дня.",
                            "workout": "Выбери упражнения для воркаута. При желании добавляй силовые или гиревые упражнения через «Добавить упражнение».",
                        }
                        text = (
                            f"{t('DAY')} {day} — {label}.\n"
                            f"{descriptions[mode]}"
                        )
                        kb = edit_day_special_kb(day, mode, labels[mode])
                    else:
                        return
                text, kb = prepare_ui_output(text, kb, prefs)
                await safe_edit_message(q, text, reply_markup=kb)
            return
        if action == "days_count":
            if len(parts) == 2:
                await safe_edit_message(q, "Сколько тренировок планируешь в неделю?", reply_markup=days_count_kb())
            else:
                n = int(parts[2])
                await set_workouts_per_week(user_id, n)
                rems = await list_user_reminders(user_id)
                if len(rems) < n:
                    context.user_data["from_settings"] = True
                    context.user_data["tz_page"] = 0
                    context.user_data["workouts_per_week"] = n
                    context.user_data["reminder_day"] = len(rems) + 1
                    await safe_edit_message(q, "Хотите настроить уведомления для новых дней?", reply_markup=reminders_kb())
                else:
                    await safe_edit_message(q, "Количество тренировок обновлено.", reply_markup=settings_kb())
            return
        if action == "step":
            if len(parts) == 2:
                step = await get_weight_step(user_id)
                text = (
                    "Какой шаг изменения веса использовать?\n"
                    "Кнопки «＋/−шаг кг» в карточках и компактном листе будут прибавлять или убавлять именно это значение.\n"
                    "Можно добавлять и убирать вес маленькими шагами: 0.5, 1, 2 или 5 кг — выбери, что удобнее."
                )
                await safe_edit_message(q, text, reply_markup=weight_step_kb(step))
            else:
                step = float(parts[2])
                await set_weight_step(user_id, step)
                formatted = format_weight_value(step)
                await safe_edit_message(
                    q,
                    f"Шаг веса обновлён: {formatted} кг. Кнопки веса теперь работают с этим шагом.",
                    reply_markup=settings_kb(),
                )
            return
        if action == "recording":
            if len(parts) == 2:
                mode = await get_recording_mode(user_id)
                await safe_edit_message(
                    q,
                    (
                        "Как фиксировать подходы?\n"
                        "Фиксация подходов помогает сохранять каждую пару рабочих сетов — бот запомнит и левую, и правую сторону, если добавишь их отдельными сетами.\n"
                        "Одинаковый вес — один шаблон для всех сетов. Удобно для классических тренировок.\n"
                        "Гибкая запись — индивидуальные вес и повторы для каждого подхода, подходит для пирамид, суперсетов и парных подходов с разными весами."
                    ),
                    reply_markup=recording_mode_kb(mode),
                )
            else:
                mode = parts[2]
                if mode not in ("single", "flex"):
                    return
                await set_recording_mode(user_id, mode)
                label = "Гибкая запись" if mode == "flex" else "Одинаковый вес"
                hint = (
                    "Теперь можно задавать вес и повторы отдельно для каждого сета, фиксируя любые парные комбинации."
                    if mode == "flex"
                    else "Каждый новый сет наследует повторы и вес из предыдущего — удобно для одинаковых пар подходов."
                )
                await safe_edit_message(
                    q,
                    f"Режим записи обновлён: {label}. {hint}",
                    reply_markup=recording_mode_kb(mode),
                )
            return
        if action == "ui":
            prefs = await load_ui_preferences(user_id)
            if len(parts) == 2:
                current_mode = "Компактный" if prefs.mode == "compact" else "Подробный"
                emoji_state = "Эмодзи включены" if prefs.emoji_enabled else "Эмодзи выключены"
                verbose_state = (
                    "Обычные пояснения" if prefs.verbose_level else "Краткие пояснения"
                )
                text = (
                    "Оформление интерфейса:\n"
                    "Выбери варианты ниже, чтобы настроить внешний вид сообщений.\n"
                    "────────\n"
                    f"Режим показа: {current_mode}.\n"
                    f"Эмодзи: {emoji_state}.\n"
                    f"Пояснения: {verbose_state}."
                )
                kb = ui_preferences_kb(prefs.mode, prefs.emoji_enabled, prefs.verbose_level)
                text, kb = prepare_ui_output(text, kb, prefs)
                await safe_edit_message(q, text, reply_markup=kb)
                return
            if len(parts) >= 4:
                sub = parts[2]
                value = parts[3]
                if sub == "mode" and value in {"compact", "detailed"}:
                    await set_ui_mode(user_id, value)
                    prefs = await load_ui_preferences(user_id)
                    label = "Компактный лист" if value == "compact" else "Подробный режим"
                    hint = (
                        "Дни будут открываться в виде списка с быстрыми действиями."
                        if value == "compact"
                        else "Возвращаются подробные карточки упражнений."
                    )
                    msg = f"Режим интерфейса обновлён: {label}. {hint}"
                elif sub == "emoji" and value in {"0", "1"}:
                    await set_ui_emoji_enabled(user_id, value == "1")
                    prefs = await load_ui_preferences(user_id)
                    state = "Эмодзи включены" if prefs.emoji_enabled else "Эмодзи отключены"
                    msg = f"Настройка эмодзи обновлена: {state}."
                elif sub == "verbose" and value in {"0", "1"}:
                    await set_ui_verbose_level(user_id, int(value))
                    prefs = await load_ui_preferences(user_id)
                    state = (
                        "Теперь включены обычные пояснения."
                        if prefs.verbose_level
                        else "Выбраны краткие пояснения."
                    )
                    msg = f"Настройка пояснений обновлена. {state}"
                else:
                    return
                kb = ui_preferences_kb(prefs.mode, prefs.emoji_enabled, prefs.verbose_level)
                msg, kb = prepare_ui_output(msg, kb, prefs)
                await safe_edit_message(q, msg, reply_markup=kb)
            return
        if action == "reminders":
            if len(parts) == 2:
                context.user_data.pop("tz_only_change", None)
                tz = await get_user_timezone(user_id)
                rems = await list_user_reminders(user_id)
                if tz and rems:
                    tz_label = next((label for code, label in TIMEZONES if code == tz), tz)
                    parts = [f"{dict(WEEKDAYS)[d]} {h:02d}:{m:02d}" for d, h, m in rems]
                    rem_text = ", ".join(parts)
                    text = f"Сейчас выбран {tz_label}, напоминания: {rem_text}."
                    await safe_edit_message(q, text, reply_markup=reminders_edit_kb())
                    return
                context.user_data["from_settings"] = True
                context.user_data["tz_page"] = 0
                await safe_edit_message(q, "Выбери свой часовой пояс:", reply_markup=tz_select_kb(0))
                return
            sub = parts[2]
            if sub == "tz":
                context.user_data["from_settings"] = True
                context.user_data["tz_page"] = 0
                context.user_data["tz_only_change"] = True
                await safe_edit_message(q, "Выбери свой часовой пояс:", reply_markup=tz_select_kb(0))
                return
            if sub == "time":
                context.user_data["from_settings"] = True
                context.user_data["tz_page"] = 0
                context.user_data["edit_reminders"] = True
                context.user_data.pop("tz_only_change", None)
                if "workouts_per_week" not in context.user_data:
                    settings = await fetch_user_settings(user_id)
                    context.user_data["workouts_per_week"] = settings[1] if settings else 0
                await safe_edit_message(q, "Выбери свой часовой пояс:", reply_markup=tz_select_kb(0))
                return
        if action == "subscription":
            await safe_edit_message(q, "Подписка пока в разработке.", reply_markup=settings_kb())
            return

    if parts[0] == "day":
        action = parts[1]
        if action == "open":
            day = int(parts[2])
            prefs = await load_ui_preferences(user_id)
            if prefs.mode == "compact":
                await render_day_sheet_from_callback(q, context, user_id, day, 0, prefs=prefs)
                return
            await send_day_cards_view(q, user_id, day, context, prefs)
            return
        if action == "sheet":
            day = int(parts[2])
            page = 0
            if len(parts) > 4 and parts[3] == "p":
                try:
                    page = max(int(parts[4]), 0)
                except ValueError:
                    page = 0
            await render_day_sheet_from_callback(q, context, user_id, day, page)
            return
        if action == "sheetdone":
            day = int(parts[2])
            page = int(parts[3]) if len(parts) > 3 else 0
            today_local = await get_user_local_date(user_id)
            ex_rows = await fetch_day_exercises(user_id, day, today_local)
            if ex_rows:
                session_id = await get_or_create_today_session(user_id, today_local, day)
                for ue_id, *_ in ex_rows:
                    await mark_exercise_done(session_id, ue_id)
            await q.answer(f"{t('DAY')} отмечен выполненным.")
            await render_day_sheet_from_callback(q, context, user_id, day, page)
            return
        if action == "group":
            day = int(parts[2])
            group = parts[3]
            clear_sheet_context(context, q.message.chat_id, q.message.message_id)
            await show_day_group_view(q, user_id, day, group, context)
            return
        if action == "groupdel":
            day = int(parts[2])
            group = parts[3]
            if not group.startswith("u"):
                await q.answer("Эту группу нельзя удалить.", show_alert=True)
                return
            custom = await get_custom_groups(user_id, context)
            gname = MG_NAMES.get(group, custom.get(group, group))
            if len(parts) == 4:
                text = (
                    f"Удалить группу «{gname}»?\n"
                    "Все упражнения из неё будут убраны из твоих тренировочных дней."
                )
                prefs = await load_ui_preferences(user_id)
                text, kb = prepare_ui_output(text, confirm_day_group_delete_kb(day, group), prefs)
                await safe_edit_message(q, text, reply_markup=kb)
                return
            if len(parts) >= 5 and parts[4] == "ok":
                removed = await remove_user_muscle_group(user_id, group)
                if not removed:
                    await q.answer("Не удалось удалить группу.", show_alert=True)
                    await show_day_group_view(q, user_id, day, group, context)
                    return
                custom.pop(group, None)
                day_groups = context.user_data.get("day_groups")
                if isinstance(day_groups, dict):
                    for selected in day_groups.values():
                        if isinstance(selected, set) and group in selected:
                            selected.discard(group)
                context.user_data.pop("add_group", None)
                await q.answer("Группа удалена.")
                prefs = await load_ui_preferences(user_id)
                await send_day_cards_view(q, user_id, day, context, prefs)
                return
            return
        if action == "add_ex":
            day = int(parts[2])
            clear_sheet_context(context, q.message.chat_id, q.message.message_id)
            today_str = await get_user_local_date(user_id)
            ex_rows = await fetch_day_exercises(user_id, day, today_str)
            existing_groups = {g for _, _, g, _, _ in ex_rows}
            custom = await get_custom_groups(user_id, context)
            await safe_edit_message(q, "Выбери группу:", reply_markup=day_add_group_kb(day, custom, existing_groups))
            return
        if action == "del_ex":
            day = int(parts[2])
            clear_sheet_context(context, q.message.chat_id, q.message.message_id)
            today_str = await get_user_local_date(user_id)
            ex_rows = await fetch_day_exercises(user_id, day, today_str)
            await safe_edit_message(q, "Удалить упражнение:", reply_markup=del_exercises_kb(day, ex_rows))
            return
        if action == "add":
            day = int(parts[2])
            sub = parts[3]
            clear_sheet_context(context, q.message.chat_id, q.message.message_id)
            if sub == "mg":
                group = parts[4]
                if group == "other":
                    context.user_data["awaiting_group_name"] = (day, q.message.chat_id, q.message.message_id, "settings")
                    await safe_edit_message(q, "Укажи группу мышц, которой хочешь заниматься.")
                    return
                context.user_data["add_group"] = (day, group)
                await show_day_add_exercises_view(q, user_id, day, group, context)
                return
            if sub == "page":
                group = parts[4]
                requested_page = int(parts[5]) if len(parts) > 5 else 0
                context.user_data["add_group"] = (day, group)
                await show_day_add_exercises_view(
                    q, user_id, day, group, context, page=requested_page
                )
                return
            if sub == "ex":
                ex_id = int(parts[4])
                stored_day, group = context.user_data.get("add_group", (day, None))
                if stored_day != day:
                    group = None
                selected_ids: set[int] = set()
                if group:
                    selected_ids = set(await list_user_exercise_ids(user_id, day, group))
                existed = bool(group and ex_id in selected_ids)
                await add_user_exercise(user_id, day, ex_id)
                if not existed:
                    if not group:
                        details = await get_exercise_details(ex_id)
                        if details:
                            _, detected_group = details
                            group = detected_group
                            context.user_data["add_group"] = (day, group)

                    async def edit_instant(text, kb):
                        await safe_edit_message(q, text, kb)

                    started = await start_instant_baseline(
                        context,
                        user_id,
                        day,
                        ex_id,
                        "day",
                        group,
                        edit_instant,
                    )
                    if started:
                        return
                if group:
                    await show_day_add_exercises_view(q, user_id, day, group, context)
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
                await safe_edit_message(q, "Напиши название упражнения:", reply_markup=kb)
                return
            if sub == "custom_back":
                group = parts[4]
                await show_day_add_exercises_view(q, user_id, day, group, context)
                return
            if sub == "done":
                context.user_data.pop("add_group", None)
                prefs = await load_ui_preferences(user_id)
                if prefs.mode == "compact":
                    await render_day_sheet_from_callback(q, context, user_id, day, 0, prefs=prefs)
                else:
                    await send_day_cards_view(q, user_id, day, context, prefs)
                return
        if action == "del":
            day = int(parts[2])
            if len(parts) == 4:
                ue_id = int(parts[3])
                await remove_user_exercise(user_id, day, ue_id)
                today_str = await get_user_local_date(user_id)
                ex_rows = await fetch_day_exercises(user_id, day, today_str)
                await safe_edit_message(
                    q, "Удалить упражнение:", reply_markup=del_exercises_kb(day, ex_rows)
                )
            return

    if parts[0] == "ex":
        action = parts[1]
        day = int(parts[2])
        ue_id = int(parts[3])
        selected = get_flex_selected(context, day, ue_id)
        is_library = day == 0
        sheet_context = get_sheet_context(context, q.message.chat_id, q.message.message_id)
        sheet_day = int(sheet_context.get("day")) if sheet_context else None
        sheet_page = int(sheet_context.get("page")) if sheet_context else 0
        prefs = await load_ui_preferences(user_id)
        if action in {"view", "select", "progress"}:
            context.user_data.pop(FOR_TIME_INPUT_KEY, None)
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
            await safe_edit_message(
                q,
                "Напиши схему WOD. Оставь пусто, чтобы очистить.",
                kb,
            )
            return
        if action == "select":
            set_no = int(parts[4])
            text, _, _, name, group, sets, mode, new_selected = await render_exercise_view(
                user_id, day, ue_id, set_no, prefs=prefs
            )
            with_weight, kind = get_display_flags(group, name)
            if mode == "flex":
                set_flex_selected(context, day, ue_id, new_selected)
                kb = (
                    flex_library_exercise_kb(
                        ue_id,
                        group,
                        sets,
                        new_selected,
                        with_weight=with_weight,
                        kind=kind,
                    )
                    if is_library
                    else flex_exercise_view_kb(
                        day,
                        ue_id,
                        group,
                        sets,
                        new_selected,
                        with_weight=with_weight,
                        kind=kind,
                    )
                )
            else:
                set_flex_selected(context, day, ue_id, None)
                amrap_mode = group == "metcon" and name == AMRAP_EXERCISE_NAME
                for_time_mode = group == "metcon" and name == FOR_TIME_EXERCISE_NAME
                if is_library:
                    step_value = await get_weight_step(user_id) if group == "kb" else None
                    kb = library_exercise_kb(
                        ue_id,
                        group,
                        name,
                        step_value,
                        amrap_mode,
                        for_time_mode,
                        with_weight=with_weight,
                        kind=kind,
                    )
                else:
                    step_value = await get_weight_step(user_id) if group == "kb" else None
                    kb = exercise_view_kb(
                        day,
                        ue_id,
                        group,
                        step_value,
                        amrap_mode,
                        for_time_mode,
                        with_weight=with_weight,
                        kind=kind,
                    )
            text, kb = prepare_ui_output(text, kb, prefs)
            await safe_edit_message(q, text, kb)
            return
        if action == "view":
            text, _, _, name, group, sets, mode, new_selected = await render_exercise_view(
                user_id, day, ue_id, selected, prefs=prefs
            )
            with_weight, kind = get_display_flags(group, name)
            if mode == "flex":
                set_flex_selected(context, day, ue_id, new_selected)
                kb = (
                    flex_library_exercise_kb(
                        ue_id,
                        group,
                        sets,
                        new_selected,
                        with_weight=with_weight,
                        kind=kind,
                    )
                    if is_library
                    else flex_exercise_view_kb(
                        day,
                        ue_id,
                        group,
                        sets,
                        new_selected,
                        with_weight=with_weight,
                        kind=kind,
                    )
                )
            else:
                set_flex_selected(context, day, ue_id, None)
                amrap_mode = group == "metcon" and name == AMRAP_EXERCISE_NAME
                for_time_mode = group == "metcon" and name == FOR_TIME_EXERCISE_NAME
                if is_library:
                    step_value = await get_weight_step(user_id) if group == "kb" else None
                    kb = library_exercise_kb(
                        ue_id,
                        group,
                        name,
                        step_value,
                        amrap_mode,
                        for_time_mode,
                        with_weight=with_weight,
                        kind=kind,
                    )
                else:
                    step_value = await get_weight_step(user_id) if group == "kb" else None
                    kb = exercise_view_kb(
                        day,
                        ue_id,
                        group,
                        step_value,
                        amrap_mode,
                        for_time_mode,
                        with_weight=with_weight,
                        kind=kind,
                    )
            text, kb = prepare_ui_output(text, kb, prefs)
            await safe_edit_message(q, text, kb)
            return
        today_str = await get_user_local_date(user_id)
        mode = await get_recording_mode(user_id)
        async with user_locks[user_id]:
            session_id = await get_or_create_today_session(user_id, today_str, day)
            if action == "fill":
                await open_fill_editor(
                    q,
                    context,
                    user_id,
                    day,
                    ue_id,
                    session_id,
                    mode,
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
                    if mode == "flex":
                        sets = await fetch_exercise_sets(session_id, ue_id)
                        if sets:
                            set_flex_selected(context, day, ue_id, sets[-1][0])
                else:
                    if sets:
                        reps = max(int(sets[-1][1] or 0), 0)
                        weight = float(max(sets[-1][2] or 0.0, 0.0))
                    else:
                        with_weight, _ = get_display_flags(resolved_group, ex_name)
                        reps = 0
                        weight = 0.0
                        last_session_sets = await fetch_last_session_sets(user_id, day, ue_id, today_str)
                        if last_session_sets:
                            rep_values = [max(int(r or 0), 0) for _, r, _ in last_session_sets]
                            if rep_values:
                                reps = int(round(sum(rep_values) / len(rep_values)))
                            if with_weight:
                                weight_values = [float(w or 0.0) for _, _, w in last_session_sets]
                                if weight_values:
                                    weight = max(sum(weight_values) / len(weight_values), 0.0)
                        base = await get_baseline(user_id, day, ex_id)
                        if reps == 0 and base:
                            reps = max(int(base[1] or 0), 0)
                        if with_weight:
                            if weight <= 0.0 and base:
                                weight = float(max(base[2] or 0.0, 0.0))
                            step = await get_weight_step(user_id)
                            if step and weight > 0.0:
                                weight = round(weight / step) * step
                        else:
                            weight = 0.0
                    await add_set(session_id, ue_id, reps, weight)
                    sets = await fetch_exercise_sets(session_id, ue_id)
                    if mode == "flex" and sets:
                        set_flex_selected(context, day, ue_id, sets[-1][0])
                if sheet_context and not is_library:
                    target_day = sheet_day if sheet_day is not None else day
                    await render_day_sheet_from_callback(
                        q, context, user_id, target_day, sheet_page
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
                    if mode == "flex":
                        sets = await fetch_exercise_sets(session_id, ue_id)
                        if sets:
                            set_flex_selected(context, day, ue_id, sets[-1][0])
                        else:
                            set_flex_selected(context, day, ue_id, None)
                else:
                    await remove_last_set(ue_id, session_id)
                    if mode == "flex":
                        sets = await fetch_exercise_sets(session_id, ue_id)
                        if sets:
                            set_flex_selected(context, day, ue_id, sets[-1][0])
                        else:
                            set_flex_selected(context, day, ue_id, None)
                if sheet_context and not is_library:
                    target_day = sheet_day if sheet_day is not None else day
                    await render_day_sheet_from_callback(
                        q, context, user_id, target_day, sheet_page
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
                if mode == "flex":
                    sets = await fetch_exercise_sets(session_id, ue_id)
                    if sets:
                        set_flex_selected(context, day, ue_id, sets[-1][0])
                if sheet_context and not is_library:
                    target_day = sheet_day if sheet_day is not None else day
                    await render_day_sheet_from_callback(
                        q, context, user_id, target_day, sheet_page
                    )
                    return
            elif action == "inc":
                field = parts[4]
                delta = float(parts[5])
                sets = await fetch_exercise_sets(session_id, ue_id)
                ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                resolved_group = resolve_group(ex_name, ex_group)
                with_weight, _ = get_display_flags(resolved_group, ex_name)
                if not sets:
                    stored = await get_session_last_values(session_id, ue_id)
                    if stored and resolved_group != "kb":
                        reps, weight = stored
                    else:
                        base = await get_baseline(user_id, day, ex_id)
                        reps = base[1] if base else 0
                        weight = base[2] if base else 0.0
                    await add_set(session_id, ue_id, reps, weight)
                    sets = await fetch_exercise_sets(session_id, ue_id)
                target = "reps" if field == "reps" else "weight_kg"
                if target == "weight_kg" and not with_weight:
                    await q.answer()
                    return
                if mode == "flex":
                    selected = get_flex_selected(context, day, ue_id)
                    if selected is None and sets:
                        selected = sets[-1][0]
                        set_flex_selected(context, day, ue_id, selected)
                    if selected is not None:
                        await inc_specific_set(ue_id, session_id, selected, target, delta)
                else:
                    await inc_last_set(ue_id, session_id, target, delta)
                if sheet_context and not is_library:
                    target_day = sheet_day if sheet_day is not None else day
                    await render_day_sheet_from_callback(
                        q, context, user_id, target_day, sheet_page
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
                    await safe_edit_message(
                        q,
                        "Укажи время в формате ММ:СС или ЧЧ:ММ:СС.",
                        kb,
                    )
                    return
                await mark_exercise_done(session_id, ue_id)
                group = resolve_group(ex_name, ex_group)
                if sheet_context and not is_library:
                    target_day = sheet_day if sheet_day is not None else day
                    await render_day_sheet_from_callback(
                        q, context, user_id, target_day, sheet_page
                    )
                    return
                if is_library:
                    items = await list_library_exercises(user_id, group)
                    text = await render_library_group_text(user_id, group, items, context, prefs=prefs)
                    kb = library_group_kb(group, items)
                    text, kb = prepare_ui_output(text, kb, prefs)
                    await safe_edit_message(q, text, reply_markup=kb)
                else:
                    await show_day_group_view(q, user_id, day, group, context)
                return
            elif action == "progress":
                ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                if resolve_group(ex_name, ex_group) == "metcon" and ex_name == FOR_TIME_EXERCISE_NAME:
                    back_cb = None
                    if sheet_context and not is_library:
                        back_cb = f"day:sheet:{sheet_day if sheet_day is not None else day}:p:{sheet_page}"
                    text, kb = await build_for_time_history_view(user_id, day, ue_id, back_cb, prefs=prefs)
                    if sheet_context and not is_library and back_cb:
                        set_sheet_context(
                            context,
                            q.message.chat_id,
                            q.message.message_id,
                            sheet_day if sheet_day is not None else day,
                            sheet_page,
                        )
                    text, kb = prepare_ui_output(text, kb, prefs)
                    await safe_edit_message(q, text, kb)
                    return
                page = 0
                if len(parts) > 4:
                    try:
                        page = max(int(parts[4]), 0)
                    except ValueError:
                        page = 0
                total_entries = await count_exercise_progress_entries(user_id, day, ue_id)
                total_pages = max(1, math.ceil(total_entries / PROGRESS_PAGE_SIZE)) if total_entries else 1
                if total_entries:
                    page = min(page, total_pages - 1)
                else:
                    page = 0
                offset = page * PROGRESS_PAGE_SIZE
                rows = await list_recent_progress(
                    user_id,
                    day,
                    ue_id,
                    PROGRESS_PAGE_SIZE,
                    offset,
                )
                text, _, ex_id, name, group, sets, mode_view, new_selected = await render_exercise_view(
                    user_id, day, ue_id, get_flex_selected(context, day, ue_id), prefs=prefs
                )
                with_weight, kind = get_display_flags(group, name)
                if mode_view == "flex":
                    set_flex_selected(context, day, ue_id, new_selected)
                else:
                    set_flex_selected(context, day, ue_id, None)
                base = await get_baseline(user_id, day, ex_id)
                prog_lines = []
                if base:
                    prog_lines.append(
                        f"Базовое: {format_sets_value(base[0], base[1], base[2], with_weight)}"
                    )
                for d, s, r, w in rows:
                    sets_cnt = s or 0
                    reps_cnt = r or 0
                    weight_val = w or 0.0
                    prog_lines.append(
                        f"{d}: {format_sets_value(sets_cnt, reps_cnt, weight_val, with_weight)}"
                    )
                if prog_lines:
                    header = "Прогресс"
                    if total_pages > 1:
                        header += f" (страница {page + 1}/{total_pages})"
                    text += "\n\n" + header + ":\n" + "\n".join(prog_lines)
                else:
                    text += "\n\nПрогресс: нет данных"
                if mode_view == "flex" and is_library:
                    kb = flex_library_exercise_kb(
                        ue_id,
                        group,
                        sets,
                        new_selected,
                        with_weight=with_weight,
                        kind=kind,
                    )
                elif mode_view == "flex":
                    kb = flex_exercise_view_kb(
                        day,
                        ue_id,
                        group,
                        sets,
                        new_selected,
                        with_weight=with_weight,
                        kind=kind,
                    )
                elif is_library:
                    step_value = await get_weight_step(user_id) if group == "kb" else None
                    amrap_mode = group == "metcon" and name == AMRAP_EXERCISE_NAME
                    for_time_mode = group == "metcon" and name == FOR_TIME_EXERCISE_NAME
                    kb = library_exercise_kb(
                        ue_id,
                        group,
                        name,
                        step_value,
                        amrap_mode,
                        for_time_mode,
                        with_weight=with_weight,
                        kind=kind,
                    )
                else:
                    step_value = await get_weight_step(user_id) if group == "kb" else None
                    amrap_mode = group == "metcon" and name == AMRAP_EXERCISE_NAME
                    kb = exercise_view_kb(
                        day,
                        ue_id,
                        group,
                        step_value,
                        amrap_mode,
                        group == "metcon" and name == FOR_TIME_EXERCISE_NAME,
                        with_weight=with_weight,
                        kind=kind,
                    )
                base_rows = [row[:] for row in kb.inline_keyboard]
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
                text, kb = prepare_ui_output(text, kb, prefs)
                await safe_edit_message(q, text, kb)
                return
            elif action == "timeedit":
                ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                if resolve_group(ex_name, ex_group) != "metcon" or ex_name != FOR_TIME_EXERCISE_NAME:
                    await q.answer()
                    return
                rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=1)
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
                    back_target = f"day:sheet:{sheet_day if sheet_day is not None else day}:p:{sheet_page}"
                    clear_sheet_context(context, q.message.chat_id, q.message.message_id)
                context.user_data[FOR_TIME_INPUT_KEY] = state
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(t("BACK"), callback_data=back_target)]]
                )
                await safe_edit_message(
                    q,
                    "Укажи новое время в формате ММ:СС или ЧЧ:ММ:СС.",
                    kb,
                )
                return
            elif action == "timedel":
                ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                if resolve_group(ex_name, ex_group) != "metcon" or ex_name != FOR_TIME_EXERCISE_NAME:
                    await q.answer()
                    return
                removed = await delete_last_measurement(user_id, FOR_TIME_METRIC)
                if not removed:
                    await q.answer("Нет данных для удаления.", show_alert=True)
                    return
                back_cb = None
                if sheet_context and not is_library:
                    back_cb = f"day:sheet:{sheet_day if sheet_day is not None else day}:p:{sheet_page}"
                text, kb = await build_for_time_history_view(user_id, day, ue_id, back_cb, prefs=prefs)
                if sheet_context and not is_library and back_cb:
                    set_sheet_context(
                        context,
                        q.message.chat_id,
                        q.message.message_id,
                        sheet_day if sheet_day is not None else day,
                        sheet_page,
                    )
                text, kb = prepare_ui_output(text, kb, prefs)
                await safe_edit_message(q, text, kb)
                return
    text, _, _, name, group, sets, mode_view, new_selected = await render_exercise_view(
        user_id, day, ue_id, get_flex_selected(context, day, ue_id), prefs=prefs
    )
    with_weight, kind = get_display_flags(group, name)
    if mode_view == "flex":
        set_flex_selected(context, day, ue_id, new_selected)
        kb = (
            flex_library_exercise_kb(
                ue_id,
                group,
                sets,
                new_selected,
                with_weight=with_weight,
                kind=kind,
            )
            if is_library
            else flex_exercise_view_kb(
                day,
                ue_id,
                group,
                sets,
                new_selected,
                with_weight=with_weight,
                kind=kind,
            )
        )
    else:
        set_flex_selected(context, day, ue_id, None)
        if is_library:
            step_value = await get_weight_step(user_id) if group == "kb" else None
            amrap_mode = group == "metcon" and name == AMRAP_EXERCISE_NAME
            for_time_mode = group == "metcon" and name == FOR_TIME_EXERCISE_NAME
            kb = library_exercise_kb(
                ue_id,
                group,
                name,
                step_value,
                amrap_mode,
                for_time_mode,
                with_weight=with_weight,
                kind=kind,
            )
        else:
            step_value = await get_weight_step(user_id) if group == "kb" else None
            amrap_mode = group == "metcon" and name == AMRAP_EXERCISE_NAME
            kb = exercise_view_kb(
                day,
                ue_id,
                group,
                step_value,
                amrap_mode,
                group == "metcon" and name == FOR_TIME_EXERCISE_NAME,
                with_weight=with_weight,
                kind=kind,
            )
        text, kb = prepare_ui_output(text, kb, prefs)
        await safe_edit_message(q, text, kb)
        return

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
    app.add_handler(CallbackQueryHandler(menu_router))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_router))
    app.add_error_handler(on_error)
    app.run_polling()


if __name__ == "__main__":
    main()
