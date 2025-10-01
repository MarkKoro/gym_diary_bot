import asyncio
import logging
import math
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
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
    rename_day_kb,
    days_count_kb,
    weight_step_kb,
    recording_mode_kb,
    day_view_mode_kb,
    flex_exercise_view_kb,
    TIMEZONES,
    library_menu_kb,
    library_group_kb,
    library_add_group_kb,
    library_add_exercises_kb,
    library_delete_kb,
    library_exercise_kb,
    library_day_select_kb,
    flex_library_exercise_kb,
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
    get_day_view_mode,
    set_day_view_mode,
    fetch_last_session_sets,
    inc_specific_set,
    add_user_muscle_group,
    list_user_muscle_groups,
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
    get_exercise_scheme,
    set_exercise_scheme,
    detach_user_exercise,
    user_has_library_exercise,
    METCON_EXERCISE_NAMES,
)

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


def resolve_group(name: str, group: str) -> str:
    if name in METCON_EXERCISE_NAMES:
        return "metcon"
    return group


def format_weight_value(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.1f}"


def filter_work_sets(sets: list[tuple[int, int, float, int]]) -> list[tuple[int, int, float]]:
    return [(no, reps, weight) for no, reps, weight, warm in sets if not warm]


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
    best_text = f"{best[1]}×{format_weight_value(best[2])} кг"
    if total_reps:
        return f"Всего {total_reps} повт., лучший {best_text}"
    return f"Лучший {best_text}"


def format_kb_plan(baseline: tuple[int, int, float] | None) -> str:
    if not baseline:
        return "—"
    sets, reps, weight = baseline
    return f"{sets}×{reps}@{format_weight_value(weight)} кг"


def format_kb_done(sets: list[tuple[int, int, float]]) -> str:
    if not sets:
        return "0 сетов"
    count = len(sets)
    reps = sets[-1][1]
    weight = sets[-1][2]
    return (
        f"{count} {pluralize_sets(count)} (последний {reps}×{format_weight_value(weight)} кг)"
    )


def format_kb_summary(
    current_sets: list[tuple[int, int, float]],
    last_sets: list[tuple[int, int, float]],
) -> str:
    if current_sets:
        return f"Сделано {format_kb_done(current_sets)}"
    if last_sets:
        return f"Прошлый раз: {format_kb_previous(last_sets)}"
    return "Сделано 0 сетов"


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
        return f"Сделано: {format_amrap_done(current_rounds, current_extra)}"
    if last_rounds or last_extra:
        return f"Прошлый раз: {format_amrap_done(last_rounds, last_extra)}"
    return "Сделано: 0 раундов"


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
    try:
        await q.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        if "not modified" not in e.message.lower():
            raise
    finally:
        remember_message(getattr(q.message, "chat_id", None), getattr(q.message, "message_id", None))

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
    now = datetime.utcnow()
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

def day_groups_text(i: int) -> str:
    return f"День {i}. Что тренируешь в этот день? Выбери группы, затем «Далее»."

def day_exercises_text(i: int, group: str, custom: dict[str, str] | None = None) -> str:
    name = MG_NAMES.get(group)
    if not name and custom:
        name = custom.get(group, group)
    if not name:
        name = group
    return f"День {i} — {name}. Выбери упражнения или добавь своё. Потом жми «Готово»."

def render_day_text(
    i: int,
    label: str,
    ex_rows: list[tuple[int, str, str, int, int]],
    custom: dict[str, str] | None = None,
    summaries: dict[int, str] | None = None,
    last_done: dict[int, str] | None = None,
) -> str:
    summaries = summaries or {}
    last_done = last_done or {}
    groups: dict[str, list[tuple[int, str, int, int]]] = {}
    for ue_id, name, group, done, ex_id in ex_rows:
        resolved = resolve_group(name, group)
        groups.setdefault(resolved, []).append((ue_id, name, done, ex_id))
    if not groups:
        return (
            f"День {i} — {label}\n"
            "Пока нет упражнений. Добавь их, чтобы запланировать тренировку."
        )
    lines = [
        f"День {i} — {label}",
        "Выбирай группу мышц, чтобы открыть упражнения и отметить выполненные подходы.",
    ]
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
            mark = "✅" if d else "•"
            extra = summaries.get(ue_id)
            last = last_done.get(ex_id)
            lines.append(compose_exercise_line(mark, n, extra, last))
        if idx < total - 1:
            lines.append("────────")
    return "\n".join(lines)

def baseline_text(name: str, sets: int, reps: int, weight: float) -> str:
    return f"{name} — {sets}×{reps} @ {weight:.1f} кг"

def render_baseline_progress(done: list[str], name: str, sets: int, reps: int, weight: float) -> str:
    lines = list(done)
    if name:
        if lines:
            lines.append("────────")
        lines.append(baseline_text(name, sets, reps, weight))
    return "\n".join(lines)

INSTANT_BASE_KEY = "instant_baseline"
FLEX_SELECTED_KEY = "flex_selected"


def render_instant_baseline(name: str, sets: int, reps: int, weight: float) -> str:
    lines = [
        name,
        "",
        "Настрой количество сетов, повторений и рабочий вес для этого упражнения.",
        "Используй кнопки с крупным шагом, чтобы быстрее указать значения.",
        "",
        f"Сейчас: {sets}×{reps} @ {weight:.1f} кг",
    ]
    return "\n".join(lines)


def instant_baseline_view(info: dict) -> tuple[str, InlineKeyboardMarkup]:
    sets, reps, weight = info["values"]
    text = render_instant_baseline(info["name"], sets, reps, weight)
    kb = baseline_kb(
        info["day"],
        sets,
        reps,
        weight,
        prefix=f"ib:{info['source']}",
        include_skip_all=False,
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
    existing = await get_baseline(user_id, day, exercise_id)
    values = list(existing) if existing else [0, 0, 0.0]
    info = {
        "source": source,
        "day": day,
        "group": group,
        "exercise_id": exercise_id,
        "name": name,
        "values": values,
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
        return "📏 Мои замеры — нет данных"
    try:
        dt = datetime.fromisoformat(last_update)
        label = dt.strftime("%d.%m.%Y")
    except Exception:
        label = last_update.split("T")[0]
    return f"📏 Мои замеры — {label}"


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


def summarize_previous_sets(sets: list[tuple[int, int, float]], mode: str) -> str:
    if not sets:
        return ""
    if mode == "flex":
        return "; ".join(f"{no}) {reps}×{weight:.1f} кг" for no, reps, weight in sets)
    reps = sets[-1][1]
    weight = sets[-1][2]
    return f"{len(sets)}×{reps} @ {weight:.1f} кг"


def summarize_baseline(values: tuple[int, int, float] | None, mode: str) -> str:
    if not values:
        return ""
    sets, reps, weight = values
    if mode == "flex":
        return "; ".join(f"{i}) {reps}×{weight:.1f} кг" for i in range(1, sets + 1))
    return f"{sets}×{reps} @ {weight:.1f} кг"


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
    if details:
        return f"{mark} {name} — {' — '.join(details)}"
    return f"{mark} {name}"


def build_prev_label(prev_summary: str | None, prev_date: str | None) -> str:
    summary = (prev_summary or "").strip()
    date = (prev_date or "").strip()
    if summary and date:
        return f"{date} — {summary}"
    if summary:
        return summary
    if date:
        return date
    return "—"


def format_plan_value(
    baseline: tuple[int, int, float] | None,
    group_key: str,
) -> str:
    if not baseline:
        return "не задан"
    if group_key == "kb":
        value = format_kb_plan(baseline)
        return value if value != "—" else "не задан"
    sets, reps, weight = baseline
    return f"{sets}×{reps}@{format_weight_value(weight)} кг"


def format_strength_done(summary: dict[str, int | float] | None) -> str:
    if not summary or not summary.get("sets_count"):
        return "Сделано 0 сетов"
    count = int(summary["sets_count"] or 0)
    reps = int(summary.get("last_reps") or 0)
    weight = float(summary.get("last_weight") or 0.0)
    return (
        f"Сделано {count} {pluralize_sets(count)} (последний {reps}×{format_weight_value(weight)} кг)"
    )


async def get_user_local_date(user_id: int) -> str:
    tz_name = await get_user_timezone(user_id)
    tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
    return datetime.now(tz).strftime("%Y-%m-%d")


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
                entry["prev_summary"] = summarize_previous_sets(last_sets, mode)
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
    header = f"День {day_index}"
    if label:
        header += f" — {label}"
    lines = [header]
    lines.append(
        "Компактный лист дня: фиксируй подходы, раунды и замеры прямо отсюда без переходов.",
    )
    lines.append(
        f"«＋ сет» добавляет рабочий подход, «＋1» меняет повторения, «＋{step_label}кг» и «−{step_label}кг» сдвигают вес на твой шаг.",
    )
    lines.append(
        "Кнопка «Готово» отмечает упражнение выполненным, ничего не создаётся автоматически.",
    )
    if not visible:
        lines.append("")
        lines.append(
            "Добавь упражнения к дню через меню — после этого они появятся здесь для быстрого учёта.",
        )
    kb_rows: list[list[InlineKeyboardButton]] = []
    for item in visible:
        name = str(item["name"])
        group_key = str(item["group_key"])
        ue_id = int(item["ue_id"])
        prev_label = build_prev_label(
            item.get("prev_summary"),
            item.get("prev_date"),
        )
        if group_key == "metcon" and name == AMRAP_EXERCISE_NAME:
            summary = item.get("amrap_summary") or {"rounds": 0, "extra": 0}
            rounds = int(summary.get("rounds") or 0)
            extra = int(summary.get("extra") or 0)
            lines.append(
                f"• {name} — Сделано: {rounds} раундов + {extra} повт."
            )
            kb_rows.append(
                [
                    InlineKeyboardButton("＋ сет", callback_data=f"ex:addset:{day_index}:{ue_id}"),
                    InlineKeyboardButton("＋1", callback_data=f"ex:inc:{day_index}:{ue_id}:reps:1"),
                    InlineKeyboardButton("−1", callback_data=f"ex:inc:{day_index}:{ue_id}:reps:-1"),
                    InlineKeyboardButton("Готово", callback_data=f"ex:done:{day_index}:{ue_id}"),
                ]
            )
        elif group_key == "metcon" and name == FOR_TIME_EXERCISE_NAME:
            fortime = item.get("fortime_summary") or {}
            seconds = fortime.get("last_time_sec")
            if seconds is not None:
                result = format_duration_value(int(seconds))
            else:
                result = "не зафиксирован"
            lines.append(f"• {name} — Результат: {result}")
            kb_rows.append(
                [
                    InlineKeyboardButton("Готово", callback_data=f"ex:done:{day_index}:{ue_id}"),
                    InlineKeyboardButton("История", callback_data=f"ex:progress:{day_index}:{ue_id}"),
                ]
            )
        else:
            plan_text = format_plan_value(item.get("baseline"), group_key)
            done_text = format_strength_done(item.get("today_summary"))
            lines.append(
                f"• {name} — Прошлый раз: {prev_label} | План: {plan_text} | {done_text}"
            )
            step_cb = f"{step_value:g}"
            kb_rows.append(
                [
                    InlineKeyboardButton("＋ сет", callback_data=f"ex:addset:{day_index}:{ue_id}"),
                    InlineKeyboardButton("＋1", callback_data=f"ex:inc:{day_index}:{ue_id}:reps:1"),
                    InlineKeyboardButton(
                        f"＋{step_label}кг",
                        callback_data=f"ex:inc:{day_index}:{ue_id}:kg:{step_cb}",
                    ),
                    InlineKeyboardButton(
                        f"−{step_label}кг",
                        callback_data=f"ex:inc:{day_index}:{ue_id}:kg:{-step_value}",
                    ),
                    InlineKeyboardButton("Готово", callback_data=f"ex:done:{day_index}:{ue_id}"),
                ]
            )
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton("⬅️", callback_data=f"day:sheet:{day_index}:p:{page - 1}")
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton("➡️", callback_data=f"day:sheet:{day_index}:p:{page + 1}")
            )
        if nav_row:
            kb_rows.append(nav_row)
    if items:
        kb_rows.append(
            [
                InlineKeyboardButton(
                    "✅ Завершить день",
                    callback_data=f"day:sheetdone:{day_index}:{page}",
                )
            ]
        )
    kb_rows.append([InlineKeyboardButton("↩ Главное меню", callback_data="menu:root")])
    text = "\n".join(lines)
    return text, InlineKeyboardMarkup(kb_rows), page, total_pages


async def render_day_sheet_from_callback(
    q,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    day_index: int,
    page: int,
) -> int:
    text, kb, page, _ = await build_day_sheet_message(user_id, day_index, page)
    chat_id = q.message.chat_id
    message_id = q.message.message_id
    try:
        await q.edit_message_text(text, reply_markup=kb)
        remember_message(chat_id, message_id)
        set_sheet_context(context, chat_id, message_id, day_index, page)
    except BadRequest as exc:
        if "not modified" in exc.message.lower():
            set_sheet_context(context, chat_id, message_id, day_index, page)
            return page
        clear_sheet_context(context, chat_id, message_id)
        new_msg = await context.bot.send_message(chat_id, text, reply_markup=kb)
        remember_message(chat_id, new_msg.message_id)
        set_sheet_context(context, chat_id, new_msg.message_id, day_index, page)
    return page


async def render_day_sheet_by_id(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
    day_index: int,
    page: int,
):
    text, kb, page, _ = await build_day_sheet_message(user_id, day_index, page)
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

def format_current_training(
    sets: list[tuple[int, int, float, int]],
    mode: str,
    selected: int | None,
) -> list[str]:
    if mode == "flex":
        if not sets:
            return ["Текущая тренировка: 0×0 @ 0.0 кг"]
        lines = ["Текущая тренировка:"]
        for set_no, reps, weight, _ in sets:
            prefix = "▶︎ " if selected == set_no else ""
            lines.append(f"{prefix}Сет {set_no}: {reps}×{weight:.1f} кг")
        return lines
    reps = sets[-1][1] if sets else 0
    weight = sets[-1][2] if sets else 0.0
    return [f"Текущая тренировка: {len(sets)}×{reps} @ {weight:.1f} кг"]


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
        text = ""
        current_sets_full: list[tuple[int, int, float, int]] = []
        if session_id:
            current_sets_full = await fetch_exercise_sets(session_id, ue_id)
        if resolved == "kb":
            work_sets = filter_work_sets(current_sets_full)
            last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
            base = await get_baseline(user_id, day, ex_id)
            plan = format_kb_plan(base)
            plan_part = f"План {plan}" if plan != "—" else "План —"
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
                text = f"Результат: {format_duration_value(seconds)}"
            else:
                text = "Результат: не зафиксирован"
        else:
            filtered = [
                (no, reps, weight)
                for no, reps, weight, warm in current_sets_full
                if not warm
            ]
            if filtered:
                text = summarize_previous_sets(filtered, mode)
            if not text:
                last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
                text = summarize_previous_sets(last_sets, mode)
                if not text:
                    base = await get_baseline(user_id, day, ex_id)
                    text = summarize_baseline(base, mode)
        if text:
            summary[ue_id] = text
    return summary



async def show_day_group_view(q, user_id: int, day: int, group: str, context):
    today_str = await get_user_local_date(user_id)
    ex_rows = await fetch_day_exercises(user_id, day, today_str)
    mode = await get_recording_mode(user_id)
    summaries = await build_summary_map(user_id, day, ex_rows, today_str, mode)
    last_done_rows = await list_last_done_dates(user_id)
    last_done_map = build_last_done_dict(last_done_rows)
    custom = await get_custom_groups(user_id, context)
    gname = MG_NAMES.get(group, custom.get(group, group))
    lines = [
        f"День {day} — {gname}",
        "Выбери упражнение, чтобы добавить подходы или отметить выполнение.",
        "",
    ]
    items: list[tuple[int, str, int]] = []
    for ue_id, name, g, done, ex_id in ex_rows:
        resolved = resolve_group(name, g)
        if resolved != group:
            continue
        mark = "✅" if done else "•"
        info = summaries.get(ue_id)
        last = last_done_map.get(ex_id)
        lines.append(compose_exercise_line(mark, name, info, last))
        items.append((ue_id, name, done))
    if items:
        lines.append("────────")
    else:
        lines.append("Пока нет упражнений. Добавь их, чтобы заполнить этот раздел.")
    await safe_edit_message(
        q,
        "\n".join(lines),
        reply_markup=day_group_kb(day, group, items),
    )

async def render_library_group_text(
    user_id: int,
    group: str,
    items: list[tuple[int, str]],
    context: ContextTypes.DEFAULT_TYPE,
) -> str:
    custom = await get_custom_groups(user_id, context)
    gname = MG_NAMES.get(group, custom.get(group, group))
    if not items:
        return (
            f"{gname}\n"
            "Пока нет упражнений. Нажми «Добавить упражнение», чтобы сохранить их и вести учёт."
        )
    mode = await get_recording_mode(user_id)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    last_done_rows = await list_last_done_dates(user_id)
    last_done_map = build_last_done_dict(last_done_rows)
    lines = [
        f"{gname}",
        "Выбери упражнение, чтобы посмотреть историю и вести отдельные записи.",
        "",
    ]
    for ue_id, name in items:
        ex_id, _, ex_group = await get_exercise_info(ue_id)
        resolved_group = resolve_group(name, ex_group)
        if resolved_group == "metcon" and name == FOR_TIME_EXERCISE_NAME:
            rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=1)
            seconds = None
            if rows and rows[0][0] is not None:
                seconds = int(round(rows[0][0]))
            summary = (
                f"Результат: {format_duration_value(seconds)}"
                if seconds is not None
                else "Результат: не зафиксирован"
            )
        else:
            last_sets = await fetch_last_session_sets(user_id, 0, ue_id, today)
            summary = summarize_previous_sets(last_sets, mode)
            if not summary:
                base = await get_baseline(user_id, 0, ex_id)
                summary = summarize_baseline(base, mode)
        last = last_done_map.get(ex_id)
        lines.append(compose_exercise_line("•", name, summary, last))
    lines.append("────────")
    lines.append("Используй «Добавить упражнение», чтобы пополнить библиотеку.")
    return "\n".join(lines)


async def show_library_exercise_view(
    q,
    user_id: int,
    group: str,
    ue_id: int,
    context: ContextTypes.DEFAULT_TYPE,
):
    selected = get_flex_selected(context, 0, ue_id)
    text, _, ex_id, name, resolved_group, sets, mode_view, new_selected = await render_exercise_view(
        user_id, 0, ue_id, selected
    )
    attachments = await list_exercise_day_links(user_id, ex_id)
    if attachments:
        attach_lines = ["Прикреплено к дням:"]
        for day_idx, label in attachments:
            title = f"День {day_idx}"
            if label:
                title = f"{title} — {label}"
            attach_lines.append(f"• {title}")
    else:
        attach_lines = ["Прикреплено к дням: не прикреплено"]
    full_text = text + "\n\n" + "\n".join(attach_lines)
    if mode_view == "flex":
        set_flex_selected(context, 0, ue_id, new_selected)
        kb = flex_library_exercise_kb(
            ue_id,
            group,
            sets,
            new_selected,
            can_detach=bool(attachments),
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
            can_detach=bool(attachments),
        )
    await safe_edit_message(q, full_text, reply_markup=kb)
    return ex_id, resolved_group


async def render_exercise_view(
    user_id: int,
    day: int,
    ue_id: int,
    selected_set: int | None = None,
):
    ex_id, name, raw_group = await get_exercise_info(ue_id)
    group = resolve_group(name, raw_group)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    mode = await get_recording_mode(user_id)
    session_id = await get_or_create_today_session(user_id, today, day)
    sets = await fetch_exercise_sets(session_id, ue_id)
    baseline = await get_baseline(user_id, day, ex_id)
    last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
    auto_fill_allowed = (
        mode == "flex"
        and not sets
        and group != "kb"
        and not (group == "metcon" and name == AMRAP_EXERCISE_NAME)
        and not (group == "metcon" and name == FOR_TIME_EXERCISE_NAME)
    )
    if auto_fill_allowed:
        if last_sets:
            for _, reps, weight in last_sets:
                await add_set(session_id, ue_id, reps, weight)
        elif baseline:
            for _ in range(baseline[0]):
                await add_set(session_id, ue_id, baseline[1], baseline[2])
        sets = await fetch_exercise_sets(session_id, ue_id)
    if mode == "flex" and sets:
        if selected_set is None or all(set_no != selected_set for set_no, *_ in sets):
            selected_set = sets[0][0]
    if group == "kb":
        work_sets = filter_work_sets(sets)
        prev_text = format_kb_previous(last_sets)
        plan_text = format_kb_plan(baseline)
        done_text = format_kb_done(work_sets)
        step = await get_weight_step(user_id)
        lines = [
            name,
            "",
            f"Прошлый раз: {prev_text}",
            f"План на сегодня: {plan_text}",
            f"Сделано: {done_text}",
        ]
        lines.append("")
        lines.append(
            f"шаг: {format_weight_value(step)} кг — кнопки «＋/−шаг кг» прибавляют и убавляют именно его."
        )
        lines.append(
            "Каждый сет фиксирует один рабочий подход. Для левой/правой стороны или связки 2× добавь сеты отдельно."
        )
        return "\n".join(lines), session_id, ex_id, name, group, sets, mode, selected_set
    if group == "metcon" and name == AMRAP_EXERCISE_NAME:
        rounds, extra = parse_amrap_sets(sets)
        last_rounds, last_extra = parse_amrap_history(last_sets)
        scheme = await get_exercise_scheme(user_id, day, ex_id)
        scheme_text = scheme if scheme else "—"
        lines = [
            name,
            "",
            f"Схема: {scheme_text}",
            "Формат: AMRAP",
            f"Сделано: {format_amrap_done(rounds, extra)}",
        ]
        if last_rounds or last_extra:
            lines.append(f"Прошлый раз: {format_amrap_done(last_rounds, last_extra)}")
        lines.append("")
        lines.append("Подсказка: «＋ сет» = раунд, «＋1 повтор» = доп.повтор")
        return "\n".join(lines), session_id, ex_id, name, group, sets, mode, selected_set
    if group == "metcon" and name == FOR_TIME_EXERCISE_NAME:
        rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=1)
        seconds = None
        timestamp = None
        if rows:
            value, _, created_at = rows[0]
            if value is not None:
                seconds = int(round(value))
            timestamp = created_at
        tz_name = await get_user_timezone(user_id)
        tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
        lines = [
            name,
            "",
            "Формат: For Time",
        ]
        if seconds is not None:
            lines.append(f"Результат: {format_duration_value(seconds)}")
            if timestamp:
                lines.append(f"Дата: {format_measurement_timestamp(timestamp, tz)}")
        else:
            lines.append("Результат: не зафиксирован")
        lines.append("")
        lines.append("Нажми «✅ Готово», чтобы ввести время.")
        return "\n".join(lines), session_id, ex_id, name, group, sets, mode, selected_set
    prev_text = summarize_previous_sets(last_sets, mode)
    if not prev_text:
        prev_text = summarize_baseline(baseline, mode) or "—"
    lines = [
        name,
        "",
        f"В прошлый раз: {prev_text}",
        "",
    ]
    current_lines = format_current_training(sets, mode, selected_set)
    lines.extend(current_lines)
    lines.append("")
    lines.append(
        "Каждый сет фиксирует рабочий подход: «＋ сет» добавляет новый, «＋1» меняет повторы, кнопки веса используют выбранный шаг."
    )
    lines.append(
        "Если работаешь парами (левая/правая, разные грифы и т.п.), добавь отдельные сеты — бот свяжет их в журнале."
    )
    return "\n".join(lines), session_id, ex_id, name, group, sets, mode, selected_set


async def build_for_time_history_view(
    user_id: int,
    day: int,
    ue_id: int,
    back_callback: str | None = None,
):
    ex_id, name, raw_group = await get_exercise_info(ue_id)
    rows = await fetch_measurement_history(user_id, FOR_TIME_METRIC, limit=10)
    tz_name = await get_user_timezone(user_id)
    tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
    lines = [name, "", "История результатов:"]
    has_entries = False
    for value, _, created_at in rows:
        if value is None:
            continue
        has_entries = True
        seconds = int(round(value))
        lines.append(f"{format_measurement_timestamp(created_at, tz)} — {format_duration_value(seconds)}")
    if has_entries:
        lines.append("")
        lines.append("Используй «Изменить», чтобы скорректировать последнее значение.")
    else:
        lines.append("История пуста. Добавь время через «✅ Готово».")
    back_cb = back_callback or f"ex:view:{day}:{ue_id}"
    kb_rows = []
    if has_entries:
        kb_rows.append(
            [InlineKeyboardButton("✏️ Изменить", callback_data=f"ex:timeedit:{day}:{ue_id}")]
        )
        kb_rows.append(
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"ex:timedel:{day}:{ue_id}")]
        )
    kb_rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data=back_cb)])
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
        tz = await get_user_timezone(user_id)
        tm = time(hour=hour, minute=minute, tzinfo=ZoneInfo(tz))
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
    msg = await update.message.reply_text(
        "Главное меню:",
        reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK)
    )
    remember_message(msg.chat_id, msg.message_id)

async def show_exercises(q, user_id: int, day: int, group: str, context):
    ex_rows = await list_exercises_by_group(group)
    selected_ids = set(await list_user_exercise_ids(user_id, day, group))
    custom = context.user_data.get("custom_groups", {})
    await safe_edit_message(
        q,
        day_exercises_text(day, group, custom),
        exercises_kb(day, group, ex_rows, selected_ids),
    )

async def show_day_add_exercises_view(q, user_id: int, day: int, group: str, context):
    ex_rows = await list_exercises_by_group(group)
    selected_ids = set(await list_user_exercise_ids(user_id, day, group))
    custom = context.user_data.get("custom_groups", {})
    await safe_edit_message(
        q,
        day_exercises_text(day, group, custom),
        reply_markup=day_add_exercises_kb(day, group, ex_rows, selected_ids),
    )

async def finish_day(q, context, user_id: int, day: int, summary: str | None = None):
    n = context.user_data.get("workouts_per_week", 0)
    system = context.user_data.get("system")
    if system == "fullbody":
        await copy_day_plan_to_other_days(user_id, 1, n)
        text = "Присылать напоминания перед тренировками?"
        if summary:
            text = summary + "\n────────\n" + text
        await q.edit_message_text(text, reply_markup=reminders_kb())
        return
    if day >= n:
        days = await list_active_days(user_id)
        text = "Отлично, супер! Мы сохранили все ваши данные. Теперь можете с удовольствием пользоваться."
        if summary:
            text = summary + "\n────────\n" + text
        await q.edit_message_text(
            text,
            reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK),
        )
    else:
        context.user_data["current_day"] = day
        text = f"День {day} сохранён. Перейти к Дню {day + 1}?"
        if summary:
            text = summary + "\n────────\n" + text
        await q.edit_message_text(
            text,
            reply_markup=day_done_kb(day),
        )

async def advance_day(q, context, user_id: int, next_day: int):
    n = context.user_data.get("workouts_per_week", 0)
    if next_day <= n:
        selected = context.user_data.setdefault("day_groups", {}).get(next_day, set())
        custom = await get_custom_groups(user_id, context)
        await q.edit_message_text(
            day_groups_text(next_day),
            reply_markup=muscle_groups_kb(next_day, selected or set(), custom),
        )
    else:
        await q.edit_message_text(
            "Присылать напоминания перед тренировками?",
            reply_markup=reminders_kb(),
        )

async def wizard_router(q, data: str, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    if data == "wiz:sub:verify":
        if await check_subscription(q.from_user.id, context.bot):
            context.user_data["sub_expiry"] = datetime.utcnow() + timedelta(days=1)
            text = (
                "В этом боте ты ведёшь дневник тренировок: сохраняешь упражнения, "
                "отслеживаешь прогресс и получаешь напоминания. "
                "Всё в одном удобном месте — больше не нужно записывать данные где попало.\n\n"
                "Нажми кнопку ниже, чтобы продолжить."
            )
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Ясно, спасибо", callback_data="wiz:intro:ok")]]
            )
            await q.edit_message_text(text, reply_markup=kb)
        else:
            await q.edit_message_text(
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
        await q.edit_message_text(text, reply_markup=system_kb())
        return
    if data == "wiz:sys:back":
        text = (
            "Как ты тренируешься?\n\n"
            "Если выбираешь Full Body, мы автоматически применим выбранные упражнения ко всем дням твоих тренировок. "
            "Если выбираешь Split, сможешь настроить упражнения для каждого дня отдельно. "
            "В любом случае ты всегда сможешь добавить или убрать упражнения в любой день."
        )
        await q.edit_message_text(text, reply_markup=system_kb())
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
                [[InlineKeyboardButton("⬅︎ Назад", callback_data="wiz:sys:back")]]
            )
            await q.edit_message_text(hint, reply_markup=kb)
            return
        context.user_data["system"] = code
        await update_user_system(user_id, code)
        await q.edit_message_text(
            "Сколько тренировок планируешь в неделю?",
            reply_markup=days_kb(),
        )
        return
    if data == "wiz:days:back":
        await q.edit_message_text("Как ты тренируешься?", reply_markup=system_kb())
        return
    if data.startswith("wiz:days:"):
        n = int(data.split(":")[2])
        await set_workouts_per_week(user_id, n)
        context.user_data["workouts_per_week"] = n
        context.user_data["day_groups"] = {}
        custom = await get_custom_groups(user_id, context)
        await q.edit_message_text(
            day_groups_text(1),
            reply_markup=muscle_groups_kb(1, set(), custom),
        )
        return
    if data.startswith("wiz:base:"):
        parts = data.split(":")
        action = parts[2]
        day = context.user_data.get("baseline_day")
        idx = context.user_data.get("baseline_idx", 0)
        ex_id, name = context.user_data["baseline_list"][idx]
        vals_map = context.user_data.setdefault("baseline_values", {})
        if ex_id not in vals_map:
            existing = await get_baseline(user_id, day, ex_id)
            vals_map[ex_id] = list(existing) if existing else [0, 0, 0.0]
        values = vals_map[ex_id]
        done = context.user_data.setdefault("baseline_done", [])
        if action == "inc":
            field = parts[3]
            delta = float(parts[4])
            if field == "sets":
                values[0] = max(0, values[0] + int(delta))
            elif field == "reps":
                values[1] = max(0, values[1] + int(delta))
            elif field == "kg":
                values[2] = max(0.0, values[2] + delta)
            await safe_edit_message(q, render_baseline_progress(done, name, *values), baseline_kb(day, *values))
            return
        if action == "ready":
            await set_baseline(user_id, day, ex_id, values[0], values[1], values[2])
            done.append(f"{baseline_text(name, *values)} ✅")
            idx += 1
            if idx < len(context.user_data["baseline_list"]):
                context.user_data["baseline_idx"] = idx
                ex_id, name = context.user_data["baseline_list"][idx]
                if ex_id not in vals_map:
                    existing = await get_baseline(user_id, day, ex_id)
                    vals_map[ex_id] = list(existing) if existing else [0, 0, 0.0]
                values = vals_map[ex_id]
                await safe_edit_message(q, render_baseline_progress(done, name, *values), baseline_kb(day, *values))
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
            if idx < len(context.user_data["baseline_list"]):
                context.user_data["baseline_idx"] = idx
                ex_id, name = context.user_data["baseline_list"][idx]
                if ex_id not in vals_map:
                    existing = await get_baseline(user_id, day, ex_id)
                    vals_map[ex_id] = list(existing) if existing else [0, 0, 0.0]
                values = vals_map[ex_id]
                await safe_edit_message(q, render_baseline_progress(done, name, *values), baseline_kb(day, *values))
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
                ex_id, name = context.user_data["baseline_list"][idx]
                values = vals_map[ex_id]
                await safe_edit_message(q, render_baseline_progress(done, name, *values), baseline_kb(day, *values))
            else:
                context.user_data.pop("baseline_day", None)
                context.user_data.pop("baseline_list", None)
                context.user_data.pop("baseline_idx", None)
                context.user_data.pop("baseline_values", None)
                context.user_data.pop("baseline_done", None)
                selected = context.user_data.setdefault("day_groups", {}).get(day, set())
                custom = await get_custom_groups(user_id, context)
                await q.edit_message_text(
                    day_groups_text(day),
                    reply_markup=muscle_groups_kb(day, selected, custom),
                )
            return
    if data.startswith("wiz:day:"):
        parts = data.split(":")
        day = int(parts[2])
        if parts[3] == "back":
            await q.edit_message_text(
                "Сколько тренировок планируешь в неделю?",
                reply_markup=days_kb(),
            )
            return
        if parts[3] == "redo":
            selected = context.user_data.setdefault("day_groups", {}).get(day, set())
            custom = await get_custom_groups(user_id, context)
            await q.edit_message_text(
                day_groups_text(day),
                reply_markup=muscle_groups_kb(day, selected, custom),
            )
            return
        if parts[3] == "mg":
            group = parts[4]
            if group == "other":
                context.user_data["awaiting_group_name"] = (day, q.message.chat_id, q.message.message_id, "wizard")
                await q.edit_message_text(
                    f"Укажи группу мышц для дня {day}, которой нет в списке."
                )
                return
            selected = context.user_data.setdefault("day_groups", {}).setdefault(day, set())
            if group in selected:
                selected.remove(group)
            else:
                selected.add(group)
            custom = await get_custom_groups(user_id, context)
            await q.edit_message_text(
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
                                "⬅︎ Назад",
                                callback_data=f"wiz:day:{day}:ex:custom_back:{group}",
                            )
                        ]
                    ]
                )
                await q.edit_message_text("Напиши название упражнения:", reply_markup=kb)
                return
            if action == "custom_back":
                group = parts[5]
                ex_rows = await list_exercises_by_group(group)
                selected_ids = set(await list_user_exercise_ids(user_id, day, group))
                custom = context.user_data.get("custom_groups", {})
                await q.edit_message_text(
                    day_exercises_text(day, group, custom),
                    reply_markup=exercises_kb(day, group, ex_rows, selected_ids),
                )
                return
            if action == "back":
                selected = context.user_data.setdefault("day_groups", {}).get(day, set())
                custom = await get_custom_groups(user_id, context)
                await q.edit_message_text(
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
                    exs = await list_day_exercises(user_id, day)
                    if exs:
                        context.user_data["baseline_day"] = day
                        context.user_data["baseline_list"] = exs
                        context.user_data["baseline_idx"] = 0
                        context.user_data["baseline_values"] = {}
                        context.user_data["baseline_done"] = []
                        ex_id, name = exs[0]
                        vals_map = context.user_data["baseline_values"]
                        existing = await get_baseline(user_id, day, ex_id)
                        vals_map[ex_id] = list(existing) if existing else [0, 0, 0.0]
                        vals = vals_map[ex_id]
                        await q.edit_message_text(
                            render_baseline_progress([], name, *vals),
                            reply_markup=baseline_kb(day, *vals),
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
            await q.edit_message_text(
                f"У тебя было заявлено {n} тренировок. Завершить на {day}?",
                reply_markup=kb,
            )
        else:
            days = await list_active_days(user_id)
            await q.edit_message_text(
                "Настройка завершена.",
                reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK),
            )
        return
    if data == "wiz:finish_yes":
        days = await list_active_days(user_id)
        await q.edit_message_text(
            "Настройка завершена.",
            reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK),
        )
        return
    if data == "wiz:finish_no":
        day = context.user_data.get("confirm_finish_day", 1)
        await q.edit_message_text(
            f"День {day} сохранён. Перейти к Дню {day + 1}?",
            reply_markup=day_done_kb(day),
        )
        return
    if data == "wiz:reminders:yes":
        context.user_data["tz_page"] = 0
        if "workouts_per_week" not in context.user_data:
            settings = await fetch_user_settings(user_id)
            context.user_data["workouts_per_week"] = settings[1] if settings else 0
        await q.edit_message_text("Выбери свой часовой пояс:", reply_markup=tz_select_kb(0))
        return
    if data == "wiz:reminders:no":
        if context.user_data.get("from_settings"):
            context.user_data.pop("from_settings", None)
            await q.edit_message_text("Настройки:", reply_markup=settings_kb())
        else:
            days = await list_active_days(user_id)
            await q.edit_message_text(
                "Настройка завершена.",
                reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK),
            )
        return
    if data == "wiz:reminders:back":
        if context.user_data.get("from_settings"):
            context.user_data.pop("from_settings", None)
            await q.edit_message_text("Настройки:", reply_markup=settings_kb())
        else:
            day = context.user_data.get("current_day", 1)
            await q.edit_message_text(
                f"День {day} сохранён. Перейти к Дню {day + 1}?",
                reply_markup=day_done_kb(day),
            )
        return
    if data.startswith("wiz:tzsel:"):
        parts = data.split(":")
        action = parts[2]
        if action == "page":
            page = int(parts[3])
            context.user_data["tz_page"] = page
            await q.edit_message_text("Выбери свой часовой пояс:", reply_markup=tz_select_kb(page))
        elif action == "set":
            tz = parts[3]
            context.user_data["tz"] = tz
            await set_user_timezone(user_id, tz)
            if context.user_data.pop("edit_reminders", None):
                await clear_user_reminders(user_id)
                for job in context.job_queue.jobs():
                    if job.name and job.name.startswith(f"rem_{user_id}_"):
                        job.schedule_removal()
            day_no = context.user_data.get("reminder_day", 1)
            context.user_data["reminder_day"] = day_no
            await q.edit_message_text(
                f"День {day_no}. В какой день недели тренировка?",
                reply_markup=reminder_day_kb(),
            )
        elif action == "back":
            if context.user_data.get("from_settings"):
                context.user_data.pop("from_settings", None)
                await q.edit_message_text("Настройки:", reply_markup=settings_kb())
            else:
                await q.edit_message_text(
                    "Присылать напоминания перед тренировками?",
                    reply_markup=reminders_kb(),
                )
        return
    if data.startswith("wiz:rday:"):
        action = data.split(":")[2]
        if action == "back":
            page = context.user_data.get("tz_page", 0)
            await q.edit_message_text("Выбери свой часовой пояс:", reply_markup=tz_select_kb(page))
        else:
            context.user_data["selected_dow"] = int(action)
            await q.edit_message_text(
                "Во сколько напоминать в этот день? Выбери время (по твоему часовому поясу)",
                reply_markup=reminder_time_kb(),
            )
        return
    if data == "wiz:remind:back":
        day_no = context.user_data.get("reminder_day", 1)
        await q.edit_message_text(
            f"День {day_no}. В какой день недели тренировка?",
            reply_markup=reminder_day_kb(),
        )
        return
    if data.startswith("wiz:remind:"):
        _, _, hh, mm = data.split(":")
        hour, minute = int(hh), int(mm)
        dow = context.user_data.get("selected_dow")
        await add_user_reminder(user_id, dow, hour, minute)
        tz = context.user_data.get("tz", "UTC")
        reminder_time = time(hour, minute, tzinfo=ZoneInfo(tz))
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
            await q.edit_message_text(
                f"День {day_no + 1}. В какой день недели тренировка?",
                reply_markup=reminder_day_kb(),
            )
            return
        if context.user_data.get("from_settings"):
            context.user_data.pop("from_settings", None)
            await q.edit_message_text("Настройки:", reply_markup=settings_kb())
        else:
            days = await list_active_days(user_id)
            await q.edit_message_text(
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
            if sheet_info:
                target_day = int(sheet_info.get("day", day))
                target_page = int(sheet_info.get("page", 0))
                await render_day_sheet_by_id(
                    context, chat_id, msg_id, user_id, target_day, target_page
                )
                return
            elif mode == "edit":
                text, kb = await build_for_time_history_view(user_id, day, ue_id)
            else:
                selected = get_flex_selected(context, day, ue_id)
                text, _, _, name, group, sets, mode_view, new_selected = await render_exercise_view(
                    user_id, day, ue_id, selected
                )
                if mode_view == "flex":
                    set_flex_selected(context, day, ue_id, new_selected)
                    kb = (
                        flex_library_exercise_kb(ue_id, group, sets, new_selected)
                        if is_library
                        else flex_exercise_view_kb(day, ue_id, group, sets, new_selected)
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
                        )
                    else:
                        kb = exercise_view_kb(
                            day,
                            ue_id,
                            group,
                            step_value,
                            amrap_mode,
                            for_time_mode,
                        )
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
        text_view, _, _, name, group, sets, mode_view, new_selected = await render_exercise_view(
            user_id, day, ue_id, selected
        )
        is_library = day == 0
        if mode_view == "flex":
            set_flex_selected(context, day, ue_id, new_selected)
            kb = (
                flex_library_exercise_kb(ue_id, group, sets, new_selected)
                if is_library
                else flex_exercise_view_kb(day, ue_id, group, sets, new_selected)
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
                )
        if chat_id and msg_id:
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
        raw_name = update.message.text or ""
        name = " ".join(raw_name.split())
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
        await context.bot.edit_message_text(
            "Выбери упражнения:",
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=library_add_exercises_kb(group, ex_rows, selected),
        )
        remember_message(chat_id, msg_id)
        return
    if context.user_data.get("awaiting_group_name"):
        day, chat_id, msg_id, mode = context.user_data.pop("awaiting_group_name")
        name = update.message.text.strip()
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
            await context.bot.edit_message_text(
                day_exercises_text(day, code, custom),
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=day_add_exercises_kb(day, code, ex_rows, selected_ids),
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
        name = update.message.text.strip()
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
        kb = (
            day_add_exercises_kb(day, group, ex_rows, selected_ids)
            if source == "day"
            else exercises_kb(day, group, ex_rows, selected_ids)
        )
        await edit_instant(day_exercises_text(day, group, custom), kb)
        return

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await require_subscription(update, context):
        return
    data = q.data
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
        if action == "inc" and len(parts) >= 5:
            field = parts[3]
            delta = float(parts[4])
            if field == "sets":
                values[0] = max(0, values[0] + int(delta))
            elif field == "reps":
                values[1] = max(0, values[1] + int(delta))
            elif field == "kg":
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
                values[2],
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
        await safe_edit_message(q, "Главное меню:", reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK))
        return

    if data in ("menu:library", "lib:root"):
        context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
        await ensure_library_history(user_id)
        groups = await list_library_groups(user_id)
        custom = await get_custom_groups(user_id, context)
        await safe_edit_message(q, "Мои упражнения:", reply_markup=library_menu_kb(groups, custom))
        return

    if data == "menu:metrics":
        context.user_data.pop(MEASUREMENT_INPUT_KEY, None)
        text, kb = await build_measurements_view(user_id, context)
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
            rem_text = "не задано"
        text = (
            "Настройки:\n"
            "Выбирай пункт ниже, чтобы обновить дневник под себя.\n"
            "────────\n"
            "✏️ Переименовать дни — поменять названия тренировочных дней.\n"
            f"📅 Количество тренировок — сейчас {n}. Укажи, сколько раз планируешь тренироваться.\n"
            "🗂 Режим дня — переключай компактный лист или подробный классический вид.\n"
            "🏋️ Шаг веса — задай шаг изменения (0.5/1/2/5 кг). Кнопки «＋/−шаг кг» используют это значение во всех упражнениях для прибавки и убавки веса.\n"
            "📝 Выбор записи — расскажи боту, как фиксировать подходы. Бот хранит каждый рабочий сет, в том числе парные (левая/правая, две гири подряд).\n"
            "   • Одинаковый вес — каждый сет с одной схемой повторов и веса.\n"
            "   • Гибкая запись — настраивай вес и повторы отдельно для каждого подхода.\n"
            f"⏰ Уведомления — {tz_label}, {rem_text}. Настрой время напоминаний.\n"
            "⭐ Подписка — информация о подписке."
        )
        await safe_edit_message(q, text, reply_markup=settings_kb())
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
            [[InlineKeyboardButton("⬅︎ Назад", callback_data=f"measure:add:cat:{category}")]]
        )
        await q.edit_message_text(item["prompt"], reply_markup=kb)
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
            [[InlineKeyboardButton("⬅︎ Назад", callback_data="measure:edit")]]
        )
        await q.edit_message_text(prefix + item["prompt"], reply_markup=kb)
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
    if parts[0] == "lib":
        action = parts[1]
        if action == "group":
            group = parts[2]
            items = await list_library_exercises(user_id, group)
            text = await render_library_group_text(user_id, group, items, context)
            await safe_edit_message(q, text, reply_markup=library_group_kb(group, items))
            return
        if action == "ex":
            group = parts[2]
            ue_id = int(parts[3])
            await show_library_exercise_view(q, user_id, group, ue_id, context)
            return
        if action == "attachmenu":
            group = parts[2]
            ue_id = int(parts[3])
            ex_id, name, _ = await get_exercise_info(ue_id)
            days = await list_active_days(user_id)
            if not days:
                await q.answer("Нет активных дней для прикрепления.", show_alert=True)
                return
            text = f"К какому дню прикрепить «{name}»?"
            await safe_edit_message(
                q,
                text,
                reply_markup=library_day_select_kb("attach", group, ue_id, days),
            )
            return
        if action == "attach":
            group = parts[2]
            ue_id = int(parts[3])
            day_idx = int(parts[4])
            ex_id, _, _ = await get_exercise_info(ue_id)
            await add_user_exercise(user_id, day_idx, ex_id)
            await q.answer(f"Добавлено в день {day_idx}.")
            await show_library_exercise_view(q, user_id, group, ue_id, context)
            return
        if action == "detachmenu":
            group = parts[2]
            ue_id = int(parts[3])
            ex_id, name, _ = await get_exercise_info(ue_id)
            links = await list_exercise_day_links(user_id, ex_id)
            if not links:
                await q.answer("Ещё не прикреплено ни к одному дню.", show_alert=True)
                return
            text = f"От какого дня открепить «{name}»?"
            await safe_edit_message(
                q,
                text,
                reply_markup=library_day_select_kb("detach", group, ue_id, links),
            )
            return
        if action == "detach":
            group = parts[2]
            ue_id = int(parts[3])
            day_idx = int(parts[4])
            ex_id, _, _ = await get_exercise_info(ue_id)
            await detach_user_exercise(user_id, day_idx, ex_id)
            await q.answer(f"Откреплено от дня {day_idx}.")
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
                await safe_edit_message(q, "Выбери группу:", reply_markup=library_add_group_kb(custom))
                return
            if sub == "mg":
                group = parts[3]
                context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
                ex_rows = await list_exercises_by_group(group)
                selected = set(await list_user_exercise_ids(user_id, 0, group))
                await safe_edit_message(
                    q,
                    "Выбери упражнения:",
                    reply_markup=library_add_exercises_kb(group, ex_rows, selected),
                )
                return
            if sub == "ex":
                group = parts[3]
                context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
                ex_id = int(parts[4])
                await toggle_user_exercise(user_id, 0, ex_id)
                ex_rows = await list_exercises_by_group(group)
                selected = set(await list_user_exercise_ids(user_id, 0, group))
                await safe_edit_message(
                    q,
                    "Выбери упражнения:",
                    reply_markup=library_add_exercises_kb(group, ex_rows, selected),
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
                    [[InlineKeyboardButton("⬅︎ Назад", callback_data=f"lib:add:mg:{group}")]]
                )
                await q.edit_message_text("Как назвать упражнение?", reply_markup=kb)
                remember_message(q.message.chat.id, q.message.message_id)
                return
            if sub == "back":
                context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
                custom = await get_custom_groups(user_id, context)
                target = context.user_data.get("lib_return")
                if target and target[0] == "group":
                    group = target[1]
                    items = await list_library_exercises(user_id, group)
                    text = await render_library_group_text(user_id, group, items, context)
                    await safe_edit_message(q, text, reply_markup=library_group_kb(group, items))
                else:
                    await safe_edit_message(
                        q, "Выбери группу:", reply_markup=library_add_group_kb(custom)
                    )
                return
            if sub == "done":
                context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
                target = context.user_data.pop("lib_return", None)
                if target and target[0] == "group":
                    group = target[1]
                    items = await list_library_exercises(user_id, group)
                    text = await render_library_group_text(user_id, group, items, context)
                    await safe_edit_message(q, text, reply_markup=library_group_kb(group, items))
                else:
                    groups = await list_library_groups(user_id)
                    custom = await get_custom_groups(user_id, context)
                    await safe_edit_message(
                        q, "Мои упражнения:", reply_markup=library_menu_kb(groups, custom)
                    )
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
                await q.edit_message_text(f"Новое название для Дня {day}:")
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
        if action == "dayview":
            if len(parts) == 2:
                mode = await get_day_view_mode(user_id)
                text = (
                    "Выбери режим показа тренировочного дня:\n"
                    "Компактный — один экран с мини-панелями действий без переходов.\n"
                    "Подробный — классические карточки упражнений с полной информацией."
                )
                await safe_edit_message(q, text, reply_markup=day_view_mode_kb(mode))
            else:
                mode = parts[2]
                if mode not in ("compact", "detailed"):
                    return
                await set_day_view_mode(user_id, mode)
                label = "Компактный" if mode == "compact" else "Подробный"
                hint = (
                    "Теперь дни будут открываться в виде компактного списка с быстрыми действиями."
                    if mode == "compact"
                    else "Возвращается подробный режим с карточками упражнений."
                )
                await safe_edit_message(
                    q,
                    f"Режим показа дня обновлён: {label}. {hint}",
                    reply_markup=day_view_mode_kb(mode),
                )
            return
        if action == "reminders":
            if len(parts) == 2:
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
                await safe_edit_message(q, "Выбери свой часовой пояс:", reply_markup=tz_select_kb(0))
                return
            if sub == "time":
                context.user_data["from_settings"] = True
                context.user_data["tz_page"] = 0
                context.user_data["edit_reminders"] = True
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
            view_mode = await get_day_view_mode(user_id)
            if view_mode == "compact":
                await render_day_sheet_from_callback(q, context, user_id, day, 0)
                return
            clear_sheet_context(context, q.message.chat_id, q.message.message_id)
            label = await get_day_label(user_id, day)
            today_str = await get_user_local_date(user_id)
            ex_rows = await fetch_day_exercises(user_id, day, today_str)
            custom = await get_custom_groups(user_id, context)
            mode = await get_recording_mode(user_id)
            summaries = await build_summary_map(user_id, day, ex_rows, today_str, mode)
            last_done_rows = await list_last_done_dates(user_id)
            last_done_map = build_last_done_dict(last_done_rows)
            await safe_edit_message(
                q,
                render_day_text(day, label, ex_rows, custom, summaries, last_done_map),
                reply_markup=day_kb(day, ex_rows),
            )
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
            await q.answer("День отмечен выполненным.")
            await render_day_sheet_from_callback(q, context, user_id, day, page)
            return
        if action == "group":
            day = int(parts[2])
            group = parts[3]
            clear_sheet_context(context, q.message.chat_id, q.message.message_id)
            await show_day_group_view(q, user_id, day, group, context)
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
                    await q.edit_message_text("Укажи группу мышц, которой хочешь заниматься.")
                    return
                context.user_data["add_group"] = (day, group)
                await show_day_add_exercises_view(q, user_id, day, group, context)
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
                                "⬅︎ Назад",
                                callback_data=f"day:add:{day}:custom_back:{group}",
                            )
                        ]
                    ]
                )
                await q.edit_message_text("Напиши название упражнения:", reply_markup=kb)
                return
            if sub == "custom_back":
                group = parts[4]
                await show_day_add_exercises_view(q, user_id, day, group, context)
                return
            if sub == "done":
                context.user_data.pop("add_group", None)
                label = await get_day_label(user_id, day)
                today_str = await get_user_local_date(user_id)
                ex_rows = await fetch_day_exercises(user_id, day, today_str)
                custom = await get_custom_groups(user_id, context)
                mode = await get_recording_mode(user_id)
                summaries = await build_summary_map(user_id, day, ex_rows, today_str, mode)
                last_done_rows = await list_last_done_dates(user_id)
                last_done_map = build_last_done_dict(last_done_rows)
                await safe_edit_message(
                    q,
                    render_day_text(day, label, ex_rows, custom, summaries, last_done_map),
                    reply_markup=day_kb(day, ex_rows),
                )
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
                [[InlineKeyboardButton("⬅︎ Назад", callback_data=f"ex:view:{day}:{ue_id}")]]
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
                user_id, day, ue_id, set_no
            )
            if mode == "flex":
                set_flex_selected(context, day, ue_id, new_selected)
                kb = (
                    flex_library_exercise_kb(ue_id, group, sets, new_selected)
                    if is_library
                    else flex_exercise_view_kb(day, ue_id, group, sets, new_selected)
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
                    )
            await safe_edit_message(q, text, kb)
            return
        if action == "view":
            text, _, _, name, group, sets, mode, new_selected = await render_exercise_view(
                user_id, day, ue_id, selected
            )
            if mode == "flex":
                set_flex_selected(context, day, ue_id, new_selected)
                kb = (
                    flex_library_exercise_kb(ue_id, group, sets, new_selected)
                    if is_library
                    else flex_exercise_view_kb(day, ue_id, group, sets, new_selected)
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
                    )
            await safe_edit_message(q, text, kb)
            return
        today_str = await get_user_local_date(user_id)
        mode = await get_recording_mode(user_id)
        async with user_locks[user_id]:
            session_id = await get_or_create_today_session(user_id, today_str, day)
            if action == "fill":
                ex_id, _, _ = await get_exercise_info(ue_id)
                template_sets = await fetch_last_session_sets(user_id, day, ue_id, today_str)
                template: list[tuple[int | float | None, int | float | None]] = []
                if template_sets:
                    template = [(reps, weight) for _, reps, weight in template_sets]
                else:
                    base = await get_baseline(user_id, day, ex_id)
                    if base:
                        template = [(base[1], base[2]) for _ in range(base[0])]
                if template:
                    await apply_sets_template(session_id, ue_id, template)
                    if mode == "flex":
                        sets = await fetch_exercise_sets(session_id, ue_id)
                        if sets:
                            set_flex_selected(context, day, ue_id, sets[0][0])
                        else:
                            set_flex_selected(context, day, ue_id, None)
                elif mode == "flex":
                    set_flex_selected(context, day, ue_id, None)
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
                        reps = sets[-1][1]
                        weight = sets[-1][2]
                    else:
                        stored = await get_session_last_values(session_id, ue_id)
                        if stored and resolved_group != "kb":
                            reps, weight = stored
                        else:
                            base = await get_baseline(user_id, day, ex_id)
                            reps = base[1] if base else 0
                            weight = base[2] if base else 0.0
                        await add_set(session_id, ue_id, reps, weight)
                        sets = await fetch_exercise_sets(session_id, ue_id)
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
                        [[InlineKeyboardButton("⬅︎ Назад", callback_data=f"ex:view:{day}:{ue_id}")]]
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
                    text = await render_library_group_text(user_id, group, items, context)
                    await safe_edit_message(q, text, reply_markup=library_group_kb(group, items))
                else:
                    await show_day_group_view(q, user_id, day, group, context)
                return
            elif action == "progress":
                ex_id, ex_name, ex_group = await get_exercise_info(ue_id)
                if resolve_group(ex_name, ex_group) == "metcon" and ex_name == FOR_TIME_EXERCISE_NAME:
                    back_cb = None
                    if sheet_context and not is_library:
                        back_cb = f"day:sheet:{sheet_day if sheet_day is not None else day}:p:{sheet_page}"
                    text, kb = await build_for_time_history_view(user_id, day, ue_id, back_cb)
                    if sheet_context and not is_library and back_cb:
                        set_sheet_context(
                            context,
                            q.message.chat_id,
                            q.message.message_id,
                            sheet_day if sheet_day is not None else day,
                            sheet_page,
                        )
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
                    user_id, day, ue_id, get_flex_selected(context, day, ue_id)
                )
                if mode_view == "flex":
                    set_flex_selected(context, day, ue_id, new_selected)
                else:
                    set_flex_selected(context, day, ue_id, None)
                base = await get_baseline(user_id, day, ex_id)
                prog_lines = []
                if base:
                    prog_lines.append(
                        f"Базовое: {base[0]}×{base[1]} @ {base[2]:.1f} кг"
                    )
                for d, s, r, w in rows:
                    sets_cnt = s or 0
                    reps_cnt = r or 0
                    weight_val = w or 0.0
                    prog_lines.append(f"{d}: {sets_cnt}×{reps_cnt} @ {weight_val:.1f} кг")
                if prog_lines:
                    header = "Прогресс"
                    if total_pages > 1:
                        header += f" (страница {page + 1}/{total_pages})"
                    text += "\n\n" + header + ":\n" + "\n".join(prog_lines)
                else:
                    text += "\n\nПрогресс: нет данных"
                if mode_view == "flex" and is_library:
                    kb = flex_library_exercise_kb(ue_id, group, sets, new_selected)
                elif mode_view == "flex":
                    kb = flex_exercise_view_kb(day, ue_id, group, sets, new_selected)
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
                    [[InlineKeyboardButton("⬅︎ Назад", callback_data=back_target)]]
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
                text, kb = await build_for_time_history_view(user_id, day, ue_id, back_cb)
                if sheet_context and not is_library and back_cb:
                    set_sheet_context(
                        context,
                        q.message.chat_id,
                        q.message.message_id,
                        sheet_day if sheet_day is not None else day,
                        sheet_page,
                    )
                await safe_edit_message(q, text, kb)
                return
        text, _, _, name, group, sets, mode_view, new_selected = await render_exercise_view(
            user_id, day, ue_id, get_flex_selected(context, day, ue_id)
        )
        if mode_view == "flex":
            set_flex_selected(context, day, ue_id, new_selected)
            kb = (
                flex_library_exercise_kb(ue_id, group, sets, new_selected)
                if is_library
                else flex_exercise_view_kb(day, ue_id, group, sets, new_selected)
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
                )
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
