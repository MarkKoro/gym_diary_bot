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
    TIMEZONES,
    library_menu_kb,
    library_group_kb,
    library_add_group_kb,
    library_add_exercises_kb,
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
    get_last_session_summary,
    fetch_exercise_sets,
    remove_last_set,
    mark_exercise_done,
    list_recent_progress,
    rename_day,
    get_weight_step,
    set_weight_step,
    add_user_muscle_group,
    list_user_muscle_groups,
    list_users_with_reminders,
    copy_day_plan_to_other_days,
    list_library_groups,
    list_library_exercises,
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
    ex_rows: list[tuple[int, str, str, int]],
    custom: dict[str, str] | None = None,
) -> str:
    groups: dict[str, list[tuple[str, int]]] = {}
    for _, name, group, done in ex_rows:
        groups.setdefault(group, []).append((name, done))
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
        for n, d in names:
            mark = "✅" if d else "•"
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

async def render_exercise_view(user_id: int, day: int, ue_id: int):
    ex_id, name, group = await get_exercise_info(ue_id)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    baseline = await get_baseline(user_id, day, ex_id)
    if baseline:
        prev = f"{baseline[0]}×{baseline[1]} @ {baseline[2]:.1f}"
    else:
        last = await get_last_session_summary(user_id, day, ue_id, today)
        prev = f"{last[0]}×{last[1]} @ {last[2]:.1f}" if last else "—"
    session_id = await get_or_create_today_session(user_id, today, day)
    sets = await fetch_exercise_sets(session_id, ue_id)
    if not sets and baseline:
        for _ in range(baseline[0]):
            await add_set(session_id, ue_id, baseline[1], baseline[2])
        sets = await fetch_exercise_sets(session_id, ue_id)
    lines = [
        f"{name} — День {day}",
        f"Прошлый раз: {prev}",
        "",
    ]
    if sets:
        reps = sets[0][1]
        weight = sets[0][2]
        lines.append(f"Текущая тренировка: {len(sets)}×{reps} @ {weight:.1f} кг")
        lines.append("")
    lines.append(
        "Записывай каждый выполненный подход: добавляй сеты, меняй повторения и вес — прогресс сохранится автоматически."
    )
    return "\n".join(lines), session_id, ex_id, group

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
        groups = await list_library_groups(user_id)
        custom = await get_custom_groups(user_id, context)
        await safe_edit_message(q, "Мои упражнения:", reply_markup=library_menu_kb(groups, custom))
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
            f"⏰ Уведомления — {tz_label}, {rem_text}. Настрой время напоминаний.\n"
            "⭐ Подписка — информация о подписке."
        )
        await safe_edit_message(q, text, reply_markup=settings_kb())
        return

    parts = data.split(":")
    if parts[0] == "lib":
        action = parts[1]
        if action == "group":
            group = parts[2]
            items = await list_library_exercises(user_id, group)
            await safe_edit_message(q, "Упражнения:", reply_markup=library_group_kb(group, items))
            return
        if action == "del":
            group = parts[2]
            ue_id = int(parts[3])
            await remove_user_exercise(user_id, 0, ue_id)
            items = await list_library_exercises(user_id, group)
            await safe_edit_message(q, "Упражнения:", reply_markup=library_group_kb(group, items))
            return
        if action == "add":
            sub = parts[2]
            if sub == "start":
                custom = await get_custom_groups(user_id, context)
                await safe_edit_message(q, "Выбери группу:", reply_markup=library_add_group_kb(custom))
                return
            if sub == "mg":
                group = parts[3]
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
            if sub == "back":
                custom = await get_custom_groups(user_id, context)
                await safe_edit_message(q, "Выбери группу:", reply_markup=library_add_group_kb(custom))
                return
            if sub == "done":
                groups = await list_library_groups(user_id)
                custom = await get_custom_groups(user_id, context)
                await safe_edit_message(q, "Мои упражнения:", reply_markup=library_menu_kb(groups, custom))
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
            await safe_edit_message(
                q,
                render_day_text(day, label, ex_rows, custom),
                reply_markup=day_kb(day, ex_rows),
            )
            return
        if action == "group":
            day = int(parts[2])
            group = parts[3]
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            ex_rows = await fetch_day_exercises(user_id, day, today_str)
            items = [(ue_id, name, done) for ue_id, name, g, done in ex_rows if g == group]
            custom = await get_custom_groups(user_id, context)
            gname = MG_NAMES.get(group, custom.get(group, group))
            lines = [
                f"День {day} — {gname}",
                "Выбери упражнение, чтобы добавить подходы или отметить выполнение.",
                "",
            ]
            for _, n, d in items:
                mark = "✅" if d else "•"
                lines.append(f"{mark} {n}")
            if items:
                lines.append("────────")
            await safe_edit_message(q, "\n".join(lines), reply_markup=day_group_kb(day, group, items))
            return
        if action == "add_ex":
            day = int(parts[2])
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            ex_rows = await fetch_day_exercises(user_id, day, today_str)
            existing_groups = {g for _, _, g, _ in ex_rows}
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
                await safe_edit_message(
                    q,
                    render_day_text(day, label, ex_rows, custom),
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
        if action == "view":
            text, _, _, group = await render_exercise_view(user_id, day, ue_id)
            await safe_edit_message(q, text, exercise_view_kb(day, ue_id, group))
            return
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        async with user_locks[user_id]:
            session_id = await get_or_create_today_session(user_id, today_str, day)
            if action == "addset":
                ex_id, _, _ = await get_exercise_info(ue_id)
                base = await get_baseline(user_id, day, ex_id)
                reps = base[1] if base else 0
                weight = base[2] if base else 0.0
                await add_set(session_id, ue_id, reps, weight)
            elif action == "delset":
                await remove_last_set(ue_id, session_id)
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
                await inc_last_set(ue_id, session_id, "reps" if field == "reps" else "weight_kg", delta)
            elif action == "done":
                await mark_exercise_done(session_id, ue_id)
                ex_rows = await fetch_day_exercises(user_id, day, today_str)
                label = await get_day_label(user_id, day)
                custom = await get_custom_groups(user_id, context)
                await safe_edit_message(
                    q,
                    render_day_text(day, label, ex_rows, custom),
                    reply_markup=day_kb(day, ex_rows),
                )
                return
            elif action == "progress":
                rows = await list_recent_progress(user_id, day, ue_id)
                text, _, ex_id, group = await render_exercise_view(user_id, day, ue_id)
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
                await safe_edit_message(q, text, exercise_view_kb(day, ue_id, group))
                return
        text, _, _, group = await render_exercise_view(user_id, day, ue_id)
        await safe_edit_message(q, text, exercise_view_kb(day, ue_id, group))
        return

    if parts[0] == "lib":
        action = parts[1]
        if action == "group":
            group = parts[2]
            items = await list_library_exercises(user_id, group)
            await safe_edit_message(q, "Упражнения:", reply_markup=library_group_kb(group, items))
            return
        if action == "del":
            group = parts[2]
            ue_id = int(parts[3])
            await remove_user_exercise(user_id, 0, ue_id)
            items = await list_library_exercises(user_id, group)
            await safe_edit_message(q, "Упражнения:", reply_markup=library_group_kb(group, items))
            return
        if action == "add":
            sub = parts[2]
            if sub == "start":
                custom = await get_custom_groups(user_id, context)
                await safe_edit_message(q, "Выбери группу:", reply_markup=library_add_group_kb(custom))
                return
            if sub == "mg":
                group = parts[3]
                context.user_data["lib_group"] = group
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
            if sub == "back":
                custom = await get_custom_groups(user_id, context)
                await safe_edit_message(q, "Выбери группу:", reply_markup=library_add_group_kb(custom))
                return
            if sub == "done":
                groups = await list_library_groups(user_id)
                custom = await get_custom_groups(user_id, context)
                await safe_edit_message(q, "Мои упражнения:", reply_markup=library_menu_kb(groups, custom))
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
