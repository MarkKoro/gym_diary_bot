import asyncio
import logging
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
    flex_exercise_view_kb,
    TIMEZONES,
    library_menu_kb,
    library_group_kb,
    library_add_group_kb,
    library_add_exercises_kb,
    library_delete_kb,
    library_exercise_kb,
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
    remove_last_set,
    mark_exercise_done,
    list_recent_progress,
    rename_day,
    get_weight_step,
    set_weight_step,
    get_recording_mode,
    set_recording_mode,
    fetch_last_session_sets,
    inc_specific_set,
    add_user_muscle_group,
    list_user_muscle_groups,
    list_users_with_reminders,
    copy_day_plan_to_other_days,
    list_library_groups,
    list_library_exercises,
    add_measurement_entry,
    update_last_measurement,
    delete_last_measurement,
    list_measurement_metrics,
    fetch_measurement_history,
    get_measurements_last_update,
)

user_locks = defaultdict(asyncio.Lock)
logger = logging.getLogger(__name__)
last_messages: dict[int, int] = {}


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
) -> str:
    summaries = summaries or {}
    groups: dict[str, list[tuple[int, str, int]]] = {}
    for ue_id, name, group, done, _ in ex_rows:
        groups.setdefault(group, []).append((ue_id, name, done))
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
        for ue_id, n, d in names:
            mark = "✅" if d else "•"
            extra = summaries.get(ue_id)
            if extra:
                lines.append(f"{mark} {n} — {extra}")
            else:
                lines.append(f"{mark} {n}")
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

FLEX_SELECTED_KEY = "flex_selected"


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
    raw = text.strip().replace(",", ".")
    if not raw:
        raise ValueError("empty")
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
    for ue_id, _, _, _, ex_id in ex_rows:
        last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
        text = summarize_previous_sets(last_sets, mode)
        if not text:
            base = await get_baseline(user_id, day, ex_id)
            text = summarize_baseline(base, mode)
        if text:
            summary[ue_id] = text
    return summary


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
    lines = [
        f"{gname}",
        "Выбери упражнение, чтобы посмотреть историю и вести отдельные записи.",
        "",
    ]
    for ue_id, name in items:
        last_sets = await fetch_last_session_sets(user_id, 0, ue_id, today)
        summary = summarize_previous_sets(last_sets, mode)
        if not summary:
            ex_id, _, _ = await get_exercise_info(ue_id)
            base = await get_baseline(user_id, 0, ex_id)
            summary = summarize_baseline(base, mode)
        if summary:
            lines.append(f"• {name} — {summary}")
        else:
            lines.append(f"• {name}")
    lines.append("────────")
    lines.append("Используй «Добавить упражнение», чтобы пополнить библиотеку.")
    return "\n".join(lines)


async def render_exercise_view(
    user_id: int,
    day: int,
    ue_id: int,
    selected_set: int | None = None,
):
    ex_id, name, group = await get_exercise_info(ue_id)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    mode = await get_recording_mode(user_id)
    session_id = await get_or_create_today_session(user_id, today, day)
    sets = await fetch_exercise_sets(session_id, ue_id)
    baseline = await get_baseline(user_id, day, ex_id)
    last_sets = await fetch_last_session_sets(user_id, day, ue_id, today)
    if mode == "flex" and not sets:
        if last_sets:
            for _, reps, weight in last_sets:
                await add_set(session_id, ue_id, reps, weight)
        elif baseline:
            for _ in range(baseline[0]):
                await add_set(session_id, ue_id, baseline[1], baseline[2])
        sets = await fetch_exercise_sets(session_id, ue_id)
    prev_text = summarize_previous_sets(last_sets, mode)
    if not prev_text:
        prev_text = summarize_baseline(baseline, mode) or "—"
    if mode == "flex" and sets:
        if selected_set is None or all(set_no != selected_set for set_no, *_ in sets):
            selected_set = sets[0][0]
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
        "«Отметь количество сделанных сетов и повторений. Если меняешь вес, укажи изменения.»"
    )
    return "\n".join(lines), session_id, ex_id, group, sets, mode, selected_set

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
                await toggle_user_exercise(user_id, day, ex_id)
                group = context.user_data["group_list"][context.user_data["group_idx"]]
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
    lib_custom = context.user_data.get(LIBRARY_CUSTOM_KEY)
    if lib_custom:
        group, chat_id, msg_id = lib_custom
        name = update.message.text.strip()
        if not name:
            await update.message.reply_text("Название не должно быть пустым. Попробуй ещё раз.")
            return
        context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
        await try_delete(update.message)
        ex_id = await get_or_create_exercise(name, group)
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
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
        await add_user_exercise(user_id, day, ex_id)
        ex_rows = await list_exercises_by_group(group)
        custom = context.user_data.get("custom_groups", {})
        selected_ids = set(await list_user_exercise_ids(user_id, day, group))
        kb = (
            day_add_exercises_kb(day, group, ex_rows, selected_ids)
            if context.user_data.get("add_group") == (day, group)
            else exercises_kb(day, group, ex_rows, selected_ids)
        )
        await context.bot.edit_message_text(
            day_exercises_text(day, group, custom),
            chat_id=chat_id,
            message_id=msg_id,
            reply_markup=kb,
        )
        remember_message(chat_id, msg_id)
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

    if data.startswith("wiz:"):
        await wizard_router(q, data, user_id, context)
        return

    if data == "menu:root":
        days = await list_active_days(user_id)
        await safe_edit_message(q, "Главное меню:", reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK))
        return

    if data in ("menu:library", "lib:root"):
        context.user_data.pop(LIBRARY_CUSTOM_KEY, None)
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
            "🏋️ Шаг веса — настрой шаг изменения веса для подходов.\n"
            "📝 Выбор записи — выбери между единым и гибким учётом подходов.\n"
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
            selected = get_flex_selected(context, 0, ue_id)
            text, _, _, _, sets, mode_view, new_selected = await render_exercise_view(
                user_id, 0, ue_id, selected
            )
            if mode_view == "flex":
                set_flex_selected(context, 0, ue_id, new_selected)
                kb = flex_library_exercise_kb(ue_id, group, sets, new_selected)
            else:
                set_flex_selected(context, 0, ue_id, None)
                kb = library_exercise_kb(ue_id, group)
            await safe_edit_message(q, text, kb)
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
                await safe_edit_message(q, "Шаг веса:", reply_markup=weight_step_kb(step))
            else:
                step = float(parts[2])
                await set_weight_step(user_id, step)
                await safe_edit_message(q, "Шаг веса обновлён.", reply_markup=settings_kb())
            return
        if action == "recording":
            if len(parts) == 2:
                mode = await get_recording_mode(user_id)
                await safe_edit_message(
                    q,
                    "Выбери, как фиксировать подходы:",
                    reply_markup=recording_mode_kb(mode),
                )
            else:
                mode = parts[2]
                if mode not in ("single", "flex"):
                    return
                await set_recording_mode(user_id, mode)
                label = "Гибкая запись" if mode == "flex" else "Одинаковый вес"
                await safe_edit_message(
                    q,
                    f"Режим записи обновлён: {label}.",
                    reply_markup=recording_mode_kb(mode),
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
            label = await get_day_label(user_id, day)
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            ex_rows = await fetch_day_exercises(user_id, day, today_str)
            custom = await get_custom_groups(user_id, context)
            mode = await get_recording_mode(user_id)
            summaries = await build_summary_map(user_id, day, ex_rows, today_str, mode)
            await safe_edit_message(
                q,
                render_day_text(day, label, ex_rows, custom, summaries),
                reply_markup=day_kb(day, ex_rows),
            )
            return
        if action == "group":
            day = int(parts[2])
            group = parts[3]
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            ex_rows = await fetch_day_exercises(user_id, day, today_str)
            mode = await get_recording_mode(user_id)
            summaries = await build_summary_map(user_id, day, ex_rows, today_str, mode)
            items = [
                (ue_id, name, done, summaries.get(ue_id))
                for ue_id, name, g, done, _ in ex_rows
                if g == group
            ]
            custom = await get_custom_groups(user_id, context)
            gname = MG_NAMES.get(group, custom.get(group, group))
            lines = [
                f"День {day} — {gname}",
                "Выбери упражнение, чтобы добавить подходы или отметить выполнение.",
                "",
            ]
            for _, n, d, info in items:
                mark = "✅" if d else "•"
                if info:
                    lines.append(f"{mark} {n} — {info}")
                else:
                    lines.append(f"{mark} {n}")
            if items:
                lines.append("────────")
            await safe_edit_message(
                q,
                "\n".join(lines),
                reply_markup=day_group_kb(day, group, [(i, n, d) for i, n, d, _ in items]),
            )
            return
        if action == "add_ex":
            day = int(parts[2])
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            ex_rows = await fetch_day_exercises(user_id, day, today_str)
            existing_groups = {g for _, _, g, _, _ in ex_rows}
            custom = await get_custom_groups(user_id, context)
            await safe_edit_message(q, "Выбери группу:", reply_markup=day_add_group_kb(day, custom, existing_groups))
            return
        if action == "del_ex":
            day = int(parts[2])
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            ex_rows = await fetch_day_exercises(user_id, day, today_str)
            await safe_edit_message(q, "Удалить упражнение:", reply_markup=del_exercises_kb(day, ex_rows))
            return
        if action == "add":
            day = int(parts[2])
            sub = parts[3]
            if sub == "mg":
                group = parts[4]
                if group == "other":
                    context.user_data["awaiting_group_name"] = (day, q.message.chat_id, q.message.message_id, "settings")
                    await q.edit_message_text("Укажи группу мышц, которой хочешь заниматься.")
                    return
                context.user_data["add_group"] = (day, group)
                ex_rows = await list_exercises_by_group(group)
                selected_ids = set(await list_user_exercise_ids(user_id, day, group))
                custom = context.user_data.get("custom_groups", {})
                await safe_edit_message(
                    q,
                    day_exercises_text(day, group, custom),
                    reply_markup=day_add_exercises_kb(day, group, ex_rows, selected_ids),
                )
                return
            if sub == "ex":
                ex_id = int(parts[4])
                await add_user_exercise(user_id, day, ex_id)
                _, group = context.user_data.get("add_group", (day, None))
                if group:
                    ex_rows = await list_exercises_by_group(group)
                    selected_ids = set(await list_user_exercise_ids(user_id, day, group))
                    custom = context.user_data.get("custom_groups", {})
                    await safe_edit_message(
                        q,
                        day_exercises_text(day, group, custom),
                        reply_markup=day_add_exercises_kb(day, group, ex_rows, selected_ids),
                    )
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
                ex_rows = await list_exercises_by_group(group)
                selected_ids = set(await list_user_exercise_ids(user_id, day, group))
                custom = context.user_data.get("custom_groups", {})
                await safe_edit_message(
                    q,
                    day_exercises_text(day, group, custom),
                    reply_markup=day_add_exercises_kb(day, group, ex_rows, selected_ids),
                )
                return
            if sub == "done":
                context.user_data.pop("add_group", None)
                label = await get_day_label(user_id, day)
                today_str = datetime.utcnow().strftime("%Y-%m-%d")
                ex_rows = await fetch_day_exercises(user_id, day, today_str)
                custom = await get_custom_groups(user_id, context)
                mode = await get_recording_mode(user_id)
                summaries = await build_summary_map(user_id, day, ex_rows, today_str, mode)
                await safe_edit_message(
                    q,
                    render_day_text(day, label, ex_rows, custom, summaries),
                    reply_markup=day_kb(day, ex_rows),
                )
                return
        if action == "del":
            day = int(parts[2])
            if len(parts) == 4:
                ue_id = int(parts[3])
                await remove_user_exercise(user_id, day, ue_id)
                today_str = datetime.utcnow().strftime("%Y-%m-%d")
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
        if action == "select":
            set_no = int(parts[4])
            text, _, _, group, sets, mode, new_selected = await render_exercise_view(
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
                kb = (
                    library_exercise_kb(ue_id, group)
                    if is_library
                    else exercise_view_kb(day, ue_id, group)
                )
            await safe_edit_message(q, text, kb)
            return
        if action == "view":
            text, _, _, group, sets, mode, new_selected = await render_exercise_view(
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
                kb = (
                    library_exercise_kb(ue_id, group)
                    if is_library
                    else exercise_view_kb(day, ue_id, group)
                )
            await safe_edit_message(q, text, kb)
            return
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        mode = await get_recording_mode(user_id)
        async with user_locks[user_id]:
            session_id = await get_or_create_today_session(user_id, today_str, day)
            if action == "addset":
                ex_id, _, _ = await get_exercise_info(ue_id)
                base = await get_baseline(user_id, day, ex_id)
                reps = base[1] if base else 0
                weight = base[2] if base else 0.0
                if mode == "flex":
                    sets = await fetch_exercise_sets(session_id, ue_id)
                    if sets:
                        reps = sets[-1][1]
                        weight = sets[-1][2]
                await add_set(session_id, ue_id, reps, weight)
                if mode == "flex":
                    sets = await fetch_exercise_sets(session_id, ue_id)
                    if sets:
                        set_flex_selected(context, day, ue_id, sets[-1][0])
            elif action == "delset":
                await remove_last_set(ue_id, session_id)
                if mode == "flex":
                    sets = await fetch_exercise_sets(session_id, ue_id)
                    if sets:
                        set_flex_selected(context, day, ue_id, sets[-1][0])
                    else:
                        set_flex_selected(context, day, ue_id, None)
            elif action == "inc":
                field = parts[4]
                delta = float(parts[5])
                sets = await fetch_exercise_sets(session_id, ue_id)
                if not sets:
                    ex_id, _, _ = await get_exercise_info(ue_id)
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
            elif action == "done":
                await mark_exercise_done(session_id, ue_id)
                if is_library:
                    _, _, group = await get_exercise_info(ue_id)
                    items = await list_library_exercises(user_id, group)
                    text = await render_library_group_text(user_id, group, items, context)
                    await safe_edit_message(q, text, reply_markup=library_group_kb(group, items))
                else:
                    ex_rows = await fetch_day_exercises(user_id, day, today_str)
                    custom = await get_custom_groups(user_id, context)
                    label = await get_day_label(user_id, day)
                    mode_view = await get_recording_mode(user_id)
                    summaries = await build_summary_map(user_id, day, ex_rows, today_str, mode_view)
                    await safe_edit_message(
                        q,
                        render_day_text(day, label, ex_rows, custom, summaries),
                        reply_markup=day_kb(day, ex_rows),
                    )
                return
            elif action == "progress":
                rows = await list_recent_progress(user_id, day, ue_id)
                text, _, ex_id, group, sets, mode_view, new_selected = await render_exercise_view(
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
                    text += "\n\nПрогресс:\n" + "\n".join(prog_lines)
                else:
                    text += "\n\nПрогресс: нет данных"
                kb = (
                    flex_library_exercise_kb(ue_id, group, sets, new_selected)
                    if mode_view == "flex" and is_library
                    else flex_exercise_view_kb(day, ue_id, group, sets, new_selected)
                    if mode_view == "flex"
                    else library_exercise_kb(ue_id, group)
                    if is_library
                    else exercise_view_kb(day, ue_id, group)
                )
                await safe_edit_message(q, text, kb)
                return
        text, _, _, group, sets, mode_view, new_selected = await render_exercise_view(
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
            kb = (
                library_exercise_kb(ue_id, group)
                if is_library
                else exercise_view_kb(day, ue_id, group)
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
