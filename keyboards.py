from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def main_menu_kb(support_url: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏋️ Сегодня", callback_data="menu:today")],
        [InlineKeyboardButton("🛠 Настроить план", callback_data="menu:setup")],
        [InlineKeyboardButton("📩 Техподдержка", url=support_url)]
    ])

def exercise_row_kb(user_ex_id: int):
    # одна строка кнопок для конкретного упражнения
    return [
        InlineKeyboardButton("＋ сет", callback_data=f"ex:addset:{user_ex_id}"),
        InlineKeyboardButton("＋1 реп", callback_data=f"ex:inc:{user_ex_id}:reps:1"),
        InlineKeyboardButton("＋0.5 кг", callback_data=f"ex:inc:{user_ex_id}:kg:0.5"),
    ]

def today_kb(ex_ids: list[int]):
    rows = []
    for ue_id in ex_ids:
        rows.append(exercise_row_kb(ue_id))
    rows.append([InlineKeyboardButton("⬅︎ Меню", callback_data="menu:root")])
    return InlineKeyboardMarkup(rows)
