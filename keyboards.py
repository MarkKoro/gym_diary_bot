from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def main_menu_kb(days: list[tuple[int, str]], support_url: str):
    rows = []
    for idx, label in days:
        rows.append([InlineKeyboardButton(f"День {idx} — {label}", callback_data=f"day:open:{idx}")])
    rows.append([InlineKeyboardButton("⚙︎ Настройки", callback_data="menu:settings")])
    rows.append([InlineKeyboardButton("📩 Техподдержка", url=support_url)])
    return InlineKeyboardMarkup(rows)

def subscription_kb(join_url: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Подписаться", url=join_url)],
        [InlineKeyboardButton("✅ Продолжить", callback_data="wiz:sub:verify")],
    ])

def settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Переименовать дни", callback_data="set:rename_day")],
        [InlineKeyboardButton("Изменить количество тренировок в неделю", callback_data="set:days_count")],
        [InlineKeyboardButton("Шаг веса", callback_data="set:step")],
        [InlineKeyboardButton("Уведомления", callback_data="set:reminders")],
        [InlineKeyboardButton("Подписка", callback_data="set:subscription")],
        [InlineKeyboardButton("⬅︎ Назад", callback_data="menu:root")],
    ])

def rename_day_kb(days: list[tuple[int, str]]):
    rows = []
    for idx, label in days:
        rows.append([InlineKeyboardButton(f"День {idx} — {label}", callback_data=f"set:rename_day:{idx}")])
    rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)

def days_count_kb():
    rows = []
    for i in range(1, 8):
        rows.append([InlineKeyboardButton(str(i), callback_data=f"set:days_count:{i}")])
    rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)

def weight_step_kb(current: float):
    rows = []
    for val in (0.5, 1.0, 2.5):
        mark = "✅ " if abs(current - val) < 1e-6 else ""
        label = f"{val:.1f}" if val % 1 else f"{int(val)}"
        rows.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"set:step:{val}")])
    rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)

def system_kb():
    rows = [
        [InlineKeyboardButton("Фулбоди", callback_data="wiz:sys:fullbody")],
        [InlineKeyboardButton("Сплит", callback_data="wiz:sys:split")],
        [InlineKeyboardButton("Другое", callback_data="wiz:sys:other")],
        [InlineKeyboardButton("❓Не знаю", callback_data="wiz:sys:help")],
    ]
    return InlineKeyboardMarkup(rows)

def days_kb():
    rows = []
    for i in range(1, 8):
        rows.append([InlineKeyboardButton(str(i), callback_data=f"wiz:days:{i}")])
    rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data="wiz:days:back")])
    return InlineKeyboardMarkup(rows)

MG_NAMES = {
    "chest": "Грудь",
    "back": "Спина",
    "legs": "Ноги",
    "shoulders": "Плечи",
    "biceps": "Бицепс",
    "triceps": "Трицепс",
    "other": "Другое",
}

def muscle_groups_kb(day_index: int, selected: set[str], custom: dict[str, str] | None = None):
    rows = []
    for code, name in MG_NAMES.items():
        if code == "other":
            continue
        mark = "✅" if code in selected else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {name}", callback_data=f"wiz:day:{day_index}:mg:{code}")])
    if custom:
        for code, name in custom.items():
            mark = "✅" if code in selected else "⬜"
            rows.append([InlineKeyboardButton(f"{mark} {name}", callback_data=f"wiz:day:{day_index}:mg:{code}")])
    rows.append([InlineKeyboardButton(f"⬜ {MG_NAMES['other']}", callback_data=f"wiz:day:{day_index}:mg:other")])
    rows.append([
        InlineKeyboardButton("▶︎ Далее", callback_data=f"wiz:day:{day_index}:groups:next"),
        InlineKeyboardButton("⏭ Пропустить день", callback_data=f"wiz:day:{day_index}:skip"),
    ])
    rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data=f"wiz:day:{day_index}:back")])
    return InlineKeyboardMarkup(rows)

def exercises_kb(day_index: int, group: str, ex_rows: list[tuple[int,str]], selected: set[int]):
    rows = []
    for ex_id, name in ex_rows:
        mark = "✅" if ex_id in selected else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {name}", callback_data=f"wiz:day:{day_index}:ex:add:{ex_id}")])
    rows.append([InlineKeyboardButton("📝 Свой вариант", callback_data=f"wiz:day:{day_index}:ex:custom:{group}")])
    rows.append([
        InlineKeyboardButton("⬅︎ Назад", callback_data=f"wiz:day:{day_index}:ex:back"),
        InlineKeyboardButton("✅ Готово", callback_data=f"wiz:day:{day_index}:ex:done"),
    ])
    return InlineKeyboardMarkup(rows)

def baseline_kb(day_index: int, sets: int, reps: int, weight: float):
    def btn(label: str, cb: str):
        return InlineKeyboardButton(label, callback_data=cb)
    rows = [
        [btn("＋1 сет", "wiz:base:inc:sets:1"), btn("−1 сет", "wiz:base:inc:sets:-1")],
        [btn("＋1 повт", "wiz:base:inc:reps:1"), btn("−1 повт", "wiz:base:inc:reps:-1")],
        [
            btn("＋1 кг", "wiz:base:inc:kg:1"),
            btn("＋5 кг", "wiz:base:inc:kg:5"),
            btn("＋10 кг", "wiz:base:inc:kg:10"),
            btn("−1 кг", "wiz:base:inc:kg:-1"),
            btn("−5 кг", "wiz:base:inc:kg:-5"),
            btn("−10 кг", "wiz:base:inc:kg:-10"),
        ],
        [btn("✅ Готово", "wiz:base:ready"), btn("⬅︎ Назад", "wiz:base:back")],
        [btn("⏭ Пропустить это упражнение", "wiz:base:skip")],
        [btn("⏭ Пропустить настройку веса", f"wiz:day:{day_index}:baseline:skip_all")],
    ]
    return InlineKeyboardMarkup(rows)

def day_done_kb(day_index: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"▶︎ День {day_index+1}", callback_data=f"wiz:day:{day_index}:next")],
        [InlineKeyboardButton("⏹ Завершить онбординг", callback_data="wiz:finish_early")],
        [InlineKeyboardButton("⬅︎ Назад", callback_data=f"wiz:day:{day_index}:redo")],
    ])

def reminders_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Да", callback_data="wiz:reminders:yes"),
            InlineKeyboardButton("Нет", callback_data="wiz:reminders:no"),
        ],
        [InlineKeyboardButton("⬅︎ Назад", callback_data="wiz:reminders:back")],
    ])

TIMEZONES = [
    ("Europe/Kaliningrad", "GMT+2 (Калининград)"),
    ("Europe/Moscow", "GMT+3 (Москва)"),
    ("Europe/Samara", "GMT+4 (Самара)"),
    ("Asia/Yekaterinburg", "GMT+5 (Екатеринбург)"),
    ("Asia/Omsk", "GMT+6 (Омск)"),
    ("Asia/Krasnoyarsk", "GMT+7 (Красноярск)"),
    ("Asia/Irkutsk", "GMT+8 (Иркутск)"),
    ("Asia/Yakutsk", "GMT+9 (Якутск)"),
    ("Asia/Vladivostok", "GMT+10 (Владивосток)"),
    ("Asia/Magadan", "GMT+11 (Магадан)"),
    ("Asia/Kamchatka", "GMT+12 (Камчатка)"),
    ("Europe/Paris", "GMT+1 (Париж)"),
    ("UTC", "GMT"),
    ("Atlantic/Azores", "GMT-1"),
    ("America/Noronha", "GMT-2"),
    ("America/Montevideo", "GMT-3"),
    ("America/Barbados", "GMT-4"),
    ("America/New_York", "GMT-5"),
    ("America/Chicago", "GMT-6"),
    ("America/Denver", "GMT-7"),
    ("America/Los_Angeles", "GMT-8"),
    ("America/Anchorage", "GMT-9"),
    ("Pacific/Honolulu", "GMT-10"),
]

def tz_select_kb(page: int = 0, per_page: int = 6):
    start = page * per_page
    end = start + per_page
    rows = []
    for zone, label in TIMEZONES[start:end]:
        rows.append([InlineKeyboardButton(label, callback_data=f"wiz:tzsel:set:{zone}")])
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅︎", callback_data=f"wiz:tzsel:page:{page-1}"))
    if end < len(TIMEZONES):
        nav.append(InlineKeyboardButton("➡︎", callback_data=f"wiz:tzsel:page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data="wiz:tzsel:back")])
    return InlineKeyboardMarkup(rows)

def reminder_time_kb():
    rows = []
    for h in range(6, 23):
        t = f"{h:02d}:00"
        rows.append([InlineKeyboardButton(t, callback_data=f"wiz:remind:{t}")])
    rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data="wiz:remind:back")])
    return InlineKeyboardMarkup(rows)

def day_kb(day_index: int, ex_rows: list[tuple[int, str]]):
    rows = []
    for ue_id, name in ex_rows:
        rows.append([InlineKeyboardButton(f"• {name} ▸", callback_data=f"ex:view:{day_index}:{ue_id}")])
    rows.append([InlineKeyboardButton("➕ Добавить упражнение", callback_data=f"day:add_ex:{day_index}")])
    rows.append([InlineKeyboardButton("🗑 Удалить упражнение", callback_data=f"day:del_ex:{day_index}")])
    rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data="menu:root")])
    return InlineKeyboardMarkup(rows)

def day_add_group_kb(day_index: int, custom: dict[str, str] | None = None):
    rows = []
    for code, name in MG_NAMES.items():
        if code == "other":
            continue
        rows.append([InlineKeyboardButton(name, callback_data=f"day:add:{day_index}:mg:{code}")])
    if custom:
        for code, name in custom.items():
            rows.append([InlineKeyboardButton(name, callback_data=f"day:add:{day_index}:mg:{code}")])
    rows.append([InlineKeyboardButton(MG_NAMES["other"], callback_data=f"day:add:{day_index}:mg:other")])
    rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data=f"day:open:{day_index}")])
    return InlineKeyboardMarkup(rows)

def day_add_exercises_kb(day_index: int, group: str, ex_rows: list[tuple[int, str]]):
    rows = []
    for ex_id, name in ex_rows:
        rows.append([InlineKeyboardButton(name, callback_data=f"day:add:{day_index}:ex:{ex_id}")])
    rows.append([InlineKeyboardButton("📝 Свой вариант", callback_data=f"day:add:{day_index}:custom:{group}")])
    rows.append([InlineKeyboardButton("✅ Готово", callback_data=f"day:add:{day_index}:done")])
    return InlineKeyboardMarkup(rows)

def del_exercises_kb(day_index: int, ex_rows: list[tuple[int, str]]):
    rows = []
    for ue_id, name in ex_rows:
        rows.append([InlineKeyboardButton(f"Удалить {name}", callback_data=f"day:del:{day_index}:{ue_id}")])
    rows.append([InlineKeyboardButton("⬅︎ Назад", callback_data=f"day:open:{day_index}")])
    return InlineKeyboardMarkup(rows)

def exercise_view_kb(day_index: int, ue_id: int, step: float = 0.5):
    def fmt(v: float) -> str:
        return f"{v:.1f}" if v % 1 else f"{int(v)}"
    double = step * 2
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("＋ сет", callback_data=f"ex:addset:{day_index}:{ue_id}")],
        [
            InlineKeyboardButton("＋1 реп", callback_data=f"ex:inc:{day_index}:{ue_id}:reps:1"),
            InlineKeyboardButton("−1 реп", callback_data=f"ex:inc:{day_index}:{ue_id}:reps:-1"),
        ],
        [
            InlineKeyboardButton(f"＋{fmt(step)} кг", callback_data=f"ex:inc:{day_index}:{ue_id}:kg:{step}"),
            InlineKeyboardButton(f"＋{fmt(double)} кг", callback_data=f"ex:inc:{day_index}:{ue_id}:kg:{double}"),
            InlineKeyboardButton(f"−{fmt(step)} кг", callback_data=f"ex:inc:{day_index}:{ue_id}:kg:-{step}"),
        ],
        [InlineKeyboardButton("🔥 Разминка/Рабочий", callback_data=f"ex:toggle:{day_index}:{ue_id}")],
        [InlineKeyboardButton("↩︎ Отменить", callback_data=f"ex:undo:{day_index}:{ue_id}")],
        [InlineKeyboardButton("⬅︎ Назад", callback_data=f"day:open:{day_index}")],
    ])
