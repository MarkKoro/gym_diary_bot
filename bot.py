import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest
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
    MG_NAMES,
    day_kb,
    day_add_group_kb,
    day_add_exercises_kb,
    del_exercises_kb,
    exercise_view_kb,
    settings_kb,
    rename_day_kb,
    days_count_kb,
    weight_step_kb,
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
    list_active_days,
    get_day_label,
    remove_user_exercise,
    get_exercise_info,
    get_baseline,
    get_last_session_summary,
    fetch_exercise_sets,
    toggle_last_set_warmup,
    remove_last_set,
    rename_day,
    get_weight_step,
    set_weight_step,
    add_user_muscle_group,
    list_user_muscle_groups,
)

user_locks = defaultdict(asyncio.Lock)

async def safe_edit_message(q, text, reply_markup):
    try:
        await q.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        if "not modified" not in e.message.lower():
            raise

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
        await update.callback_query.edit_message_text(
            "Прежде чем получить помощника, подпишись на наш канал, чтобы поддержать нас и быть в курсе новостей.",
            reply_markup=kb,
        )
    else:
        await update.message.reply_text(
            "Прежде чем получить помощника, подпишись на наш канал, чтобы поддержать нас и быть в курсе новостей.",
            reply_markup=kb,
        )
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
    ex_rows: list[tuple[int, str, str]],
    custom: dict[str, str] | None = None,
) -> str:
    groups: dict[str, list[str]] = {}
    for _, name, group in ex_rows:
        groups.setdefault(group, []).append(name)
    lines = [f"День {i} — {label}", "Упражнения:"]
    for code, names in groups.items():
        gname = MG_NAMES.get(code)
        if not gname and custom:
            gname = custom.get(code, code)
        if not gname:
            gname = code
        lines.append(f"{gname}:")
        for n in names:
            lines.append(f"• {n}")
    return "\n".join(lines)

def baseline_text(name: str, sets: int, reps: int, weight: float) -> str:
    return f"{name} — {sets}x{reps} @ {weight:.1f} кг"

def render_baseline_progress(done: list[str], name: str, sets: int, reps: int, weight: float) -> str:
    lines = list(done)
    if name:
        if lines:
            lines.append("────────")
        lines.append(baseline_text(name, sets, reps, weight))
    return "\n".join(lines)

async def render_exercise_view(user_id: int, day: int, ue_id: int):
    ex_id, name = await get_exercise_info(ue_id)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    baseline = await get_baseline(user_id, day, ex_id)
    if baseline:
        prev = f"{baseline[0]}x{baseline[1]} @ {baseline[2]:.1f}"
    else:
        last = await get_last_session_summary(user_id, day, ue_id, today)
        prev = f"{last[0]}x{last[1]} @ {last[2]:.1f}" if last else "—"
    session_id = await get_or_create_today_session(user_id, today, day)
    sets = await fetch_exercise_sets(session_id, ue_id)
    lines = [f"{name} — День {day}", f"Прошлый раз: {prev}", ""]
    for set_no, reps, weight, warm in sets:
        prefix = "🔥 " if warm else ""
        lines.append(f"{prefix}{set_no}) {reps} x {weight:.1f}")
    if sets:
        lines.append("")
    lines.append("Нажимай кнопки — всё сохраняется автоматически.")
    return "\n".join(lines), session_id

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(context.job.chat_id, "Напоминание о тренировке!")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    u = update.effective_user
    user_id = await get_or_create_user(u.id, u.username)
    settings = await fetch_user_settings(user_id)
    if not settings or not settings[0] or not settings[1]:
        await update.message.reply_text("Как ты тренируешься?", reply_markup=system_kb())
        return
    days = await list_active_days(user_id)
    await update.message.reply_text(
        "Главное меню:",
        reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK)
    )

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
            await q.edit_message_text("Как ты тренируешься?", reply_markup=system_kb())
        else:
            await q.edit_message_text(
                "Прежде чем получить помощника, подпишись на наш канал, чтобы поддержать нас и быть в курсе новостей.",
                reply_markup=subscription_kb(JOIN_URL),
            )
        return
    if data == "wiz:sys:back":
        await q.edit_message_text("Как ты тренируешься?", reply_markup=system_kb())
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
                context.user_data["awaiting_custom"] = (day, group)
                await q.edit_message_text("Напиши название упражнения:")
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
            await q.edit_message_text(
                "Во сколько напоминать в дни тренировок? Выбери время (по твоему часовому поясу)",
                reply_markup=reminder_time_kb(),
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
    if data == "wiz:remind:back":
        page = context.user_data.get("tz_page", 0)
        await q.edit_message_text("Выбери свой часовой пояс:", reply_markup=tz_select_kb(page))
        return
    if data.startswith("wiz:remind:"):
        _, _, hh, mm = data.split(":")
        hour, minute = int(hh), int(mm)
        await add_user_reminder(user_id, hour, minute)
        tz = context.user_data.get("tz", "UTC")
        reminder_time = time(hour, minute, tzinfo=ZoneInfo(tz))
        context.job_queue.run_daily(reminder_job, reminder_time, chat_id=q.message.chat_id)
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
        await update.message.delete()
        if mode == "wizard":
            selected = context.user_data.setdefault("day_groups", {}).setdefault(day, set())
            selected.add(code)
            await context.bot.edit_message_text(
                day_groups_text(day),
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=muscle_groups_kb(day, selected, custom),
            )
        else:
            context.user_data["add_group"] = (day, code)
            ex_rows = await list_exercises_by_group(code)
            await context.bot.edit_message_text(
                day_exercises_text(day, code, custom),
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=day_add_exercises_kb(day, code, ex_rows),
            )
        return
    if context.user_data.get("awaiting_rename"):
        day, chat_id, msg_id = context.user_data.pop("awaiting_rename")
        label = update.message.text.strip()
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
        await rename_day(user_id, day, label)
        await context.bot.edit_message_text("Настройки:", chat_id=chat_id, message_id=msg_id, reply_markup=settings_kb())
        return
    if context.user_data.get("awaiting_custom"):
        day, group = context.user_data.pop("awaiting_custom")
        name = update.message.text.strip()
        ex_id = await get_or_create_exercise(name, group)
        u = update.effective_user
        user_id = await get_or_create_user(u.id, u.username)
        await add_user_exercise(user_id, day, ex_id)
        ex_rows = await list_exercises_by_group(group)
        custom = context.user_data.get("custom_groups", {})
        if context.user_data.get("add_group") == (day, group):
            await update.message.reply_text(
                day_exercises_text(day, group, custom),
                reply_markup=day_add_exercises_kb(day, group, ex_rows),
            )
        else:
            selected_ids = set(await list_user_exercise_ids(user_id, day, group))
            await update.message.reply_text(
                day_exercises_text(day, group, custom),
                reply_markup=exercises_kb(day, group, ex_rows, selected_ids),
            )
        return

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await require_subscription(update, context):
        return
    data = q.data
    u = update.effective_user
    user_id = await get_or_create_user(u.id, u.username)

    if data.startswith("wiz:"):
        await wizard_router(q, data, user_id, context)
        return

    if data == "menu:root":
        days = await list_active_days(user_id)
        await safe_edit_message(q, "Главное меню:", reply_markup=main_menu_kb(days, SUPPORT_DEEPLINK))
        return

    if data == "menu:settings":
        await safe_edit_message(q, "Настройки:", reply_markup=settings_kb())
        return

    parts = data.split(":")
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
            context.user_data["from_settings"] = True
            context.user_data["tz_page"] = 0
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
            ex_rows = await fetch_day_exercises(user_id, day)
            custom = await get_custom_groups(user_id, context)
            await safe_edit_message(q, render_day_text(day, label, ex_rows, custom), reply_markup=day_kb(day, ex_rows))
            return
        if action == "add_ex":
            day = int(parts[2])
            custom = await get_custom_groups(user_id, context)
            await safe_edit_message(q, "Выбери группу:", reply_markup=day_add_group_kb(day, custom))
            return
        if action == "del_ex":
            day = int(parts[2])
            ex_rows = await fetch_day_exercises(user_id, day)
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
                custom = context.user_data.get("custom_groups", {})
                await safe_edit_message(q, day_exercises_text(day, group, custom), reply_markup=day_add_exercises_kb(day, group, ex_rows))
                return
            if sub == "ex":
                ex_id = int(parts[4])
                await add_user_exercise(user_id, day, ex_id)
                _, group = context.user_data.get("add_group", (day, None))
                if group:
                    ex_rows = await list_exercises_by_group(group)
                    custom = context.user_data.get("custom_groups", {})
                    await safe_edit_message(q, day_exercises_text(day, group, custom), reply_markup=day_add_exercises_kb(day, group, ex_rows))
                return
            if sub == "custom":
                group = parts[4]
                context.user_data["awaiting_custom"] = (day, group)
                await q.edit_message_text("Напиши название упражнения:")
                return
            if sub == "done":
                context.user_data.pop("add_group", None)
                label = await get_day_label(user_id, day)
                ex_rows = await fetch_day_exercises(user_id, day)
                custom = await get_custom_groups(user_id, context)
                await safe_edit_message(q, render_day_text(day, label, ex_rows, custom), reply_markup=day_kb(day, ex_rows))
                return
        if action == "del":
            day = int(parts[2])
            if len(parts) == 4:
                ue_id = int(parts[3])
                await remove_user_exercise(user_id, day, ue_id)
                ex_rows = await fetch_day_exercises(user_id, day)
                await safe_edit_message(q, "Удалить упражнение:", reply_markup=del_exercises_kb(day, ex_rows))
            return

    if parts[0] == "ex":
        action = parts[1]
        day = int(parts[2])
        ue_id = int(parts[3])
        if action == "view":
            step = await get_weight_step(user_id)
            text, _ = await render_exercise_view(user_id, day, ue_id)
            await safe_edit_message(q, text, exercise_view_kb(day, ue_id, step))
            return
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        async with user_locks[user_id]:
            session_id = await get_or_create_today_session(user_id, today_str, day)
            if action == "addset":
                ex_id, _ = await get_exercise_info(ue_id)
                base = await get_baseline(user_id, day, ex_id)
                reps = base[1] if base else 0
                weight = base[2] if base else 0.0
                await add_set(session_id, ue_id, reps, weight)
                context.user_data["last_action"] = {
                    "type": "addset", "ue_id": ue_id, "session_id": session_id, "time": asyncio.get_running_loop().time(), "day": day
                }
            elif action == "inc":
                field = parts[4]
                delta = float(parts[5])
                sets = await fetch_exercise_sets(session_id, ue_id)
                if not sets:
                    ex_id, _ = await get_exercise_info(ue_id)
                    base = await get_baseline(user_id, day, ex_id)
                    reps = base[1] if base else 0
                    weight = base[2] if base else 0.0
                    await add_set(session_id, ue_id, reps, weight)
                await inc_last_set(ue_id, session_id, "reps" if field == "reps" else "weight_kg", delta)
                context.user_data["last_action"] = {
                    "type": "inc", "ue_id": ue_id, "field": field, "delta": delta, "session_id": session_id, "time": asyncio.get_running_loop().time(), "day": day
                }
            elif action == "toggle":
                sets = await fetch_exercise_sets(session_id, ue_id)
                if not sets:
                    ex_id, _ = await get_exercise_info(ue_id)
                    base = await get_baseline(user_id, day, ex_id)
                    reps = base[1] if base else 0
                    weight = base[2] if base else 0.0
                    await add_set(session_id, ue_id, reps, weight)
                await toggle_last_set_warmup(ue_id, session_id)
                context.user_data["last_action"] = {
                    "type": "toggle", "ue_id": ue_id, "session_id": session_id, "time": asyncio.get_running_loop().time(), "day": day
                }
            elif action == "undo":
                act = context.user_data.get("last_action")
                if act and act.get("ue_id") == ue_id and asyncio.get_running_loop().time() - act.get("time", 0) < 60:
                    if act["type"] == "addset":
                        await remove_last_set(ue_id, session_id)
                    elif act["type"] == "inc":
                        field = act["field"]
                        delta = -act["delta"]
                        await inc_last_set(ue_id, session_id, "reps" if field == "reps" else "weight_kg", delta)
                    elif act["type"] == "toggle":
                        await toggle_last_set_warmup(ue_id, session_id)
                    context.user_data.pop("last_action", None)
        text, _ = await render_exercise_view(user_id, day, ue_id)
        step = await get_weight_step(user_id)
        await safe_edit_message(q, text, exercise_view_kb(day, ue_id, step))
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
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_router))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_router))
    app.run_polling()


if __name__ == "__main__":
    main()
