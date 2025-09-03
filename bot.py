import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from keyboards import main_menu_kb, today_kb
from settings import TG_TOKEN, SUPPORT_DEEPLINK
from db import init_db, get_or_create_user, ensure_default_plan, get_or_create_today_session, fetch_day_exercises, fetch_sets_table, add_set, inc_last_set

def render_today_text(ex_rows, set_rows):
    # ex_rows: [(ue_id, name), ...]
    # set_rows: [(set_id, user_ex_id, set_no, reps, weight, name), ...]
    # Собираем таблицу типа:
    # Жим лёжа
    #   1) 6 x 60.0
    #   2) 6 x 60.0
    lines = ["🏋️ Тренировка — Сегодня\n"]
    by_ex = {}
    for set_id, ue_id, set_no, reps, weight, name in set_rows:
        by_ex.setdefault((ue_id, name), []).append((set_no, reps, weight))
    for ue_id, name in ex_rows:
        lines.append(f"• {name}")
        sets = sorted(by_ex.get((ue_id, name), []))
        if not sets:
            lines.append("   — нет сетов")
        else:
            for set_no, reps, weight in sets:
                lines.append(f"   {set_no}) {reps} x {weight:.1f}")
    lines.append("\nПодсказка: жми «＋ сет», «＋1 реп», «＋0.5 кг» под нужным упражнением.")
    return "\n".join(lines)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user_id = await get_or_create_user(u.id, u.username)
    await ensure_default_plan(user_id)
    await update.message.reply_text(
        "Привет! Это дневник тренировок. Всё быстро и в один клик.",
        reply_markup=main_menu_kb(SUPPORT_DEEPLINK)
    )

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    u = update.effective_user
    user_id = await get_or_create_user(u.id, u.username)

    if data == "menu:root":
        await q.edit_message_text("Главное меню:", reply_markup=main_menu_kb(SUPPORT_DEEPLINK))
        return

    if data == "menu:today":
        # сессия «сегодня» (демо: day_index=1)
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        session_id = await get_or_create_today_session(user_id, date_str, day_index=1)
        ex_rows = await fetch_day_exercises(user_id, day_index=1)
        set_rows = await fetch_sets_table(session_id)
        text = render_today_text(ex_rows, set_rows)
        kb = today_kb([r[0] for r in ex_rows])
        await q.edit_message_text(text, reply_markup=kb)
        return

    if data == "menu:setup":
        await q.edit_message_text("Мастер настройки появится в следующем блоке. Пока используем базовый День 1 (3 упражнения).", reply_markup=main_menu_kb(SUPPORT_DEEPLINK))
        return

    # действия с упражнениями
    parts = data.split(":")
    if parts[0] == "ex":
        action = parts[1]
        if action == "addset":
            ue_id = int(parts[2])
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            session_id = await get_or_create_today_session(user_id, date_str, day_index=1)
            await add_set(session_id, ue_id)
        elif action == "inc":
            ue_id = int(parts[2])
            field = parts[3]     # reps | kg
            delta = float(parts[4])
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            session_id = await get_or_create_today_session(user_id, date_str, day_index=1)
            await inc_last_set(ue_id, session_id, "reps" if field=="reps" else "weight_kg", delta)

        # перерисуем «Сегодня»
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        session_id = await get_or_create_today_session(user_id, date_str, day_index=1)
        ex_rows = await fetch_day_exercises(user_id, day_index=1)
        set_rows = await fetch_sets_table(session_id)
        await q.edit_message_text(render_today_text(ex_rows, set_rows), reply_markup=today_kb([r[0] for r in ex_rows]))
        return

async def main():
    await init_db()
    app = Application.builder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_router))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()

if __name__ == "__main__":
    asyncio.run(main())
