from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ui_texts import t
from kb_catalog import get_kb_catalog_page, KB_MISC_CATEGORY

if TYPE_CHECKING:
    from bot import UiPreferences


def ui_header_row(back_cb: str, menu_cb: str | None) -> list[list[InlineKeyboardButton]]:
    buttons = [InlineKeyboardButton("‹ Назад", callback_data=back_cb)]
    if menu_cb and menu_cb != back_cb:
        buttons.append(InlineKeyboardButton("⋯ Меню", callback_data=menu_cb))
    return [buttons]


def ui_footer_rows(
    primary: list[tuple[str, str]],
    secondary: list[tuple[str, str]] | None,
) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    if primary:
        rows.append(
            [InlineKeyboardButton(label, callback_data=cb) for label, cb in primary]
        )
    if secondary:
        rows.append(
            [InlineKeyboardButton(label, callback_data=cb) for label, cb in secondary]
        )
    return rows

def main_menu_kb(days: list[tuple[int, str]], support_url: str):
    rows = []
    for idx, label in days:
        rows.append(
            [InlineKeyboardButton(f"{t('DAY')} {idx} — {label}", callback_data=f"day:open:{idx}")]
        )
    rows.append([InlineKeyboardButton("📘 Мои упражнения", callback_data="menu:library")])
    rows.append([InlineKeyboardButton(t("MEAS_TITLE"), callback_data="menu:metrics")])
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
        [InlineKeyboardButton("✏️ Переименовать дни", callback_data="set:rename_day")],
        [InlineKeyboardButton("🔁 Изменить день", callback_data="set:edit_day")],
        [InlineKeyboardButton("📅 Количество тренировок", callback_data="set:days_count")],
        [InlineKeyboardButton("🎨 Оформление интерфейса", callback_data="set:ui")],
        [InlineKeyboardButton("🏋️ Шаг веса", callback_data="set:step")],
        [InlineKeyboardButton("📝 Выбор записи", callback_data="set:recording")],
        [InlineKeyboardButton("⏰ Уведомления", callback_data="set:reminders")],
        [InlineKeyboardButton("⭐ Подписка", callback_data="set:subscription")],
        [InlineKeyboardButton(t("BACK"), callback_data="menu:root")],
    ])

def rename_day_kb(days: list[tuple[int, str]]):
    rows = []
    for idx, label in days:
        rows.append(
            [InlineKeyboardButton(f"{t('DAY')} {idx} — {label}", callback_data=f"set:rename_day:{idx}")]
        )
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)


def edit_day_select_kb(days: list[tuple[int, str]]):
    rows = []
    for idx, label in days:
        rows.append(
            [InlineKeyboardButton(f"{t('DAY')} {idx} — {label}", callback_data=f"set:edit_day:{idx}")]
        )
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)


def edit_day_mode_kb(day_index: int):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🏋️ Силовая", callback_data=f"set:edit_day:{day_index}:strength"
                )
            ],
            [
                InlineKeyboardButton(
                    "🕋 Гири", callback_data=f"set:edit_day:{day_index}:kb"
                )
            ],
            [
                InlineKeyboardButton(
                    "🤸 Воркаут", callback_data=f"set:edit_day:{day_index}:workout"
                )
            ],
            [
                InlineKeyboardButton(
                    "⏱️ Меткон", callback_data=f"set:edit_day:{day_index}:metcon"
                )
            ],
            [InlineKeyboardButton(t("BACK"), callback_data="set:edit_day")],
        ]
    )


def edit_day_strength_kb(day_index: int):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗂 Выбрать группы", callback_data=f"day:add_ex:{day_index}"
                )
            ],
            [InlineKeyboardButton("📋 Открыть день", callback_data=f"day:open:{day_index}")],
            [InlineKeyboardButton(t("BACK"), callback_data=f"set:edit_day:{day_index}")],
        ]
    )


def edit_day_special_kb(day_index: int, group: str, label: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label, callback_data=f"day:add:{day_index}:mg:{group}"
                )
            ],
            [InlineKeyboardButton("📋 Открыть день", callback_data=f"day:open:{day_index}")],
            [InlineKeyboardButton(t("BACK"), callback_data=f"set:edit_day:{day_index}")],
        ]
    )

def days_count_kb():
    rows = []
    for i in range(1, 8):
        rows.append([InlineKeyboardButton(str(i), callback_data=f"set:days_count:{i}")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)

def weight_step_kb(current: float):
    rows = []
    for val in (0.5, 1.0, 2.0, 5.0):
        mark = "✅ " if abs(current - val) < 1e-6 else ""
        label = f"{val:.1f}" if val % 1 else f"{int(val)}"
        rows.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"set:step:{val}")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)


def _option_marker(active: bool) -> str:
    return "◉" if active else "○"


def ui_preferences_kb(mode: str, emoji_enabled: bool, verbose_level: int):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{_option_marker(mode == 'compact')} Компактный",
                    callback_data="set:ui:mode:compact",
                ),
                InlineKeyboardButton(
                    f"{_option_marker(mode == 'detailed')} Подробный",
                    callback_data="set:ui:mode:detailed",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{_option_marker(bool(emoji_enabled))} Включить",
                    callback_data="set:ui:emoji:1",
                ),
                InlineKeyboardButton(
                    f"{_option_marker(not bool(emoji_enabled))} Выключить",
                    callback_data="set:ui:emoji:0",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{_option_marker(verbose_level == 0)} Краткие",
                    callback_data="set:ui:verbose:0",
                ),
                InlineKeyboardButton(
                    f"{_option_marker(verbose_level == 1)} Обычные",
                    callback_data="set:ui:verbose:1",
                ),
            ],
            [InlineKeyboardButton(t("BACK"), callback_data="menu:settings")],
        ]
    )

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
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="wiz:days:back")])
    return InlineKeyboardMarkup(rows)

MG_NAMES = {
    "chest": "Грудь",
    "back": "Спина",
    "legs": "Ноги",
    "shoulders": "Плечи",
    "core": "Кор / пресс",
    "biceps": "Бицепс",
    "triceps": "Трицепс",
    "kb": "Гиря",
    "metcon": "Кроссфит",
    "workout": "Воркаут (турники/брусья)",
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
    rows.append([InlineKeyboardButton(t("BACK"), callback_data=f"wiz:day:{day_index}:back")])
    return InlineKeyboardMarkup(rows)

def exercises_kb(
    day_index: int,
    group: str,
    ex_rows: list[tuple[int, str]],
    selected: set[int],
    page: int = 0,
):
    rows: list[list[InlineKeyboardButton]] = []
    selected = selected or set()
    total_pages = 1
    if group == "kb":
        blocks, page, total_pages = get_kb_catalog_page(ex_rows, page)
        for cat_key, items in blocks:
            header = t(cat_key if cat_key != KB_MISC_CATEGORY else KB_MISC_CATEGORY)
            rows.append([InlineKeyboardButton(header, callback_data="noop")])
            for ex_id, name in items:
                mark = "✅" if ex_id in selected else "⬜"
                rows.append(
                    [
                        InlineKeyboardButton(
                            f"{mark} {name}",
                            callback_data=f"wiz:day:{day_index}:ex:add:{ex_id}",
                        )
                    ]
                )
    else:
        for ex_id, name in ex_rows:
            mark = "✅" if ex_id in selected else "⬜"
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{mark} {name}", callback_data=f"wiz:day:{day_index}:ex:add:{ex_id}"
                    )
                ]
            )
    if group == "kb" and total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    t("PREV"), callback_data=f"wiz:day:{day_index}:ex:page:{group}:{page - 1}"
                )
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    t("NEXT"), callback_data=f"wiz:day:{day_index}:ex:page:{group}:{page + 1}"
                )
            )
        if nav_row:
            rows.append(nav_row)
    rows.append(
        [
            InlineKeyboardButton(
                "📝 Свой вариант", callback_data=f"wiz:day:{day_index}:ex:custom:{group}"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(t("BACK"), callback_data=f"wiz:day:{day_index}:ex:back"),
            InlineKeyboardButton(t("DONE"), callback_data=f"wiz:day:{day_index}:ex:done"),
        ]
    )
    return InlineKeyboardMarkup(rows), page, total_pages

def baseline_kb(
    day_index: int,
    sets: int,
    reps: int,
    weight: float,
    prefix: str = "wiz:base",
    include_skip_all: bool = True,
    *,
    with_weight: bool = True,
):
    def btn(label: str, cb: str):
        return InlineKeyboardButton(label, callback_data=cb)

    def cb(*parts: str) -> str:
        return ":".join((prefix, *parts))

    rows = [
        [btn("＋1 сет", cb("inc", "sets", "1")), btn("−1 сет", cb("inc", "sets", "-1"))],
        [btn("＋5 повт", cb("inc", "reps", "5")), btn("−5 повт", cb("inc", "reps", "-5"))],
        [btn("＋1 повт", cb("inc", "reps", "1")), btn("−1 повт", cb("inc", "reps", "-1"))],
    ]
    if with_weight:
        rows.extend(
            [
                [
                    btn("＋0.5 кг", cb("inc", "kg", "0.5")),
                    btn("＋1 кг", cb("inc", "kg", "1")),
                    btn("＋5 кг", cb("inc", "kg", "5")),
                    btn("＋10 кг", cb("inc", "kg", "10")),
                    btn("＋25 кг", cb("inc", "kg", "25")),
                    btn("＋50 кг", cb("inc", "kg", "50")),
                ],
                [
                    btn("−0.5 кг", cb("inc", "kg", "-0.5")),
                    btn("−1 кг", cb("inc", "kg", "-1")),
                    btn("−5 кг", cb("inc", "kg", "-5")),
                    btn("−10 кг", cb("inc", "kg", "-10")),
                    btn("−25 кг", cb("inc", "kg", "-25")),
                    btn("−50 кг", cb("inc", "kg", "-50")),
                ],
            ]
        )
    rows.extend(
        [
            [btn(t("DONE"), cb("ready")), btn(t("BACK"), cb("back"))],
            [btn("⏭ Пропустить это упражнение", cb("skip"))],
        ]
    )
    if include_skip_all:
        rows.append([btn("⏭ Пропустить настройку веса", f"wiz:day:{day_index}:baseline:skip_all")])
    return InlineKeyboardMarkup(rows)

def day_done_kb(day_index: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"▶︎ {t('DAY')} {day_index+1}", callback_data=f"wiz:day:{day_index}:next")],
        [InlineKeyboardButton("⏹ Завершить онбординг", callback_data="wiz:finish_early")],
        [InlineKeyboardButton(t("BACK"), callback_data=f"wiz:day:{day_index}:redo")],
    ])

def reminders_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Да", callback_data="wiz:reminders:yes"),
            InlineKeyboardButton("Нет", callback_data="wiz:reminders:no"),
        ],
        [InlineKeyboardButton(t("BACK"), callback_data="wiz:reminders:back")],
    ])


def reminders_edit_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Изменить часовой пояс", callback_data="set:reminders:tz")],
        [InlineKeyboardButton("Изменить дни и время", callback_data="set:reminders:time")],
        [InlineKeyboardButton(t("BACK"), callback_data="menu:settings")],
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
    ("Atlantic/Azores", "GMT-1 (Азорские острова)"),
    ("America/Noronha", "GMT-2 (Фернанду-ди-Норонья)"),
    ("America/Montevideo", "GMT-3 (Уругвай)"),
    ("America/Barbados", "GMT-4 (Барбадос)"),
    ("America/New_York", "GMT-5 (Нью-Йорк, США)"),
    ("America/Chicago", "GMT-6 (Чикаго, США)"),
    ("America/Denver", "GMT-7 (Денвер, США)"),
    ("America/Los_Angeles", "GMT-8 (Лос-Анджелес, США)"),
    ("America/Anchorage", "GMT-9 (Анкоридж, США)"),
    ("Pacific/Honolulu", "GMT-10 (Гавайи)"),
]

def tz_select_kb(page: int = 0, per_page: int = 6):
    start = page * per_page
    end = start + per_page
    rows = []
    for zone, label in TIMEZONES[start:end]:
        rows.append([InlineKeyboardButton(label, callback_data=f"wiz:tzsel:set:{zone}")])
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton(t("PREV"), callback_data=f"wiz:tzsel:page:{page-1}"))
    if end < len(TIMEZONES):
        nav.append(InlineKeyboardButton(t("NEXT"), callback_data=f"wiz:tzsel:page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="wiz:tzsel:back")])
    return InlineKeyboardMarkup(rows)

def reminder_time_kb():
    rows = []
    for h in range(6, 23):
        time_label = f"{h:02d}:00"
        rows.append(
            [InlineKeyboardButton(time_label, callback_data=f"wiz:remind:{time_label}")]
        )
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="wiz:remind:back")])
    return InlineKeyboardMarkup(rows)


WEEKDAYS = [
    (0, "Пн"),
    (1, "Вт"),
    (2, "Ср"),
    (3, "Чт"),
    (4, "Пт"),
    (5, "Сб"),
    (6, "Вс"),
]


def reminder_day_kb():
    rows = []
    for dow, label in WEEKDAYS:
        rows.append([InlineKeyboardButton(label, callback_data=f"wiz:rday:{dow}")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="wiz:rday:back")])
    return InlineKeyboardMarkup(rows)

def day_kb(day_index: int, ex_rows: list[tuple[int, str, str, int, int]]):
    groups: dict[str, list[tuple[int, str]]] = {}
    for ue_id, name, group, _, _ in ex_rows:
        groups.setdefault(group, []).append((ue_id, name))
    rows = []
    for group in groups.keys():
        gname = MG_NAMES.get(group, group)
        rows.append([InlineKeyboardButton(f"{gname} ▸", callback_data=f"day:group:{day_index}:{group}")])
    rows.append([InlineKeyboardButton("➕ Добавить упражнение", callback_data=f"day:add_ex:{day_index}")])
    rows.append([InlineKeyboardButton("🗑 Удалить упражнение", callback_data=f"day:del_ex:{day_index}")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="menu:root")])
    return InlineKeyboardMarkup(rows)


def day_group_kb(day_index: int, group: str, items: list[tuple[int, str, int]]):
    rows = []
    for ue_id, name, done in items:
        mark = "✅" if done else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {name} ▸", callback_data=f"ex:view:{day_index}:{ue_id}")])
    if group.startswith("u"):
        rows.append(
            [
                InlineKeyboardButton(
                    "🗑 Удалить группу", callback_data=f"day:groupdel:{day_index}:{group}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(t("BACK"), callback_data=f"day:open:{day_index}")])
    return InlineKeyboardMarkup(rows)

def day_add_group_kb(day_index: int, custom: dict[str, str] | None = None, selected: set[str] | None = None):
    rows = []
    selected = selected or set()
    for code, name in MG_NAMES.items():
        if code == "other":
            continue
        mark = "✅" if code in selected else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {name}", callback_data=f"day:add:{day_index}:mg:{code}")])
    if custom:
        for code, name in custom.items():
            mark = "✅" if code in selected else "⬜"
            rows.append([InlineKeyboardButton(f"{mark} {name}", callback_data=f"day:add:{day_index}:mg:{code}")])
    rows.append([InlineKeyboardButton(f"⬜ {MG_NAMES['other']}", callback_data=f"day:add:{day_index}:mg:other")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data=f"day:open:{day_index}")])
    return InlineKeyboardMarkup(rows)

def day_add_exercises_kb(
    day_index: int,
    group: str,
    ex_rows: list[tuple[int, str]],
    selected: set[int] | None = None,
    page: int = 0,
):
    rows: list[list[InlineKeyboardButton]] = []
    selected = selected or set()
    total_pages = 1
    if group == "kb":
        blocks, page, total_pages = get_kb_catalog_page(ex_rows, page)
        for cat_key, items in blocks:
            header = t(cat_key if cat_key != KB_MISC_CATEGORY else KB_MISC_CATEGORY)
            rows.append([InlineKeyboardButton(header, callback_data="noop")])
            for ex_id, name in items:
                mark = "✅" if ex_id in selected else "⬜"
                rows.append(
                    [
                        InlineKeyboardButton(
                            f"{mark} {name}",
                            callback_data=f"day:add:{day_index}:ex:{ex_id}",
                        )
                    ]
                )
    else:
        for ex_id, name in ex_rows:
            mark = "✅" if ex_id in selected else "⬜"
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{mark} {name}", callback_data=f"day:add:{day_index}:ex:{ex_id}"
                    )
                ]
            )
    if group == "kb" and total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    t("PREV"), callback_data=f"day:add:{day_index}:page:{group}:{page - 1}"
                )
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    t("NEXT"), callback_data=f"day:add:{day_index}:page:{group}:{page + 1}"
                )
            )
        if nav_row:
            rows.append(nav_row)
    rows.append(
        [
            InlineKeyboardButton(
                "📝 Свой вариант", callback_data=f"day:add:{day_index}:custom:{group}"
            )
        ]
    )
    rows.append([InlineKeyboardButton(t("DONE"), callback_data=f"day:add:{day_index}:done")])
    return InlineKeyboardMarkup(rows), page, total_pages

def del_exercises_kb(day_index: int, ex_rows: list[tuple[int, str, str, int, int]]):
    rows = []
    for ue_id, name, *_ in ex_rows:
        rows.append([InlineKeyboardButton(f"Удалить {name}", callback_data=f"day:del:{day_index}:{ue_id}")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data=f"day:open:{day_index}")])
    return InlineKeyboardMarkup(rows)

def _format_step_label(step: float) -> str:
    text = f"{step:g}"
    return text.replace(".0", "") if text.endswith(".0") else text


def _rep_control_labels(kind: str) -> tuple[str, str]:
    if kind == "duration":
        return "＋ сек", "− сек"
    return "＋ повтор", "− повтор"


def _format_weight_delta(value: float) -> str:
    formatted = f"{value:g}"
    if formatted.endswith(".0"):
        return formatted[:-2]
    return formatted


def _format_signed_delta(value: float) -> str:
    formatted = f"{value:+g}"
    if formatted.endswith(".0"):
        return formatted[:-2]
    return formatted


def _pluralize_reps(count: int) -> str:
    rem10 = count % 10
    rem100 = count % 100
    if rem10 == 1 and rem100 != 11:
        return "повтор"
    if 2 <= rem10 <= 4 and not (12 <= rem100 <= 14):
        return "повтора"
    return "повторов"


def _format_major_rep_label(kind: str, value: int, positive: bool) -> str:
    sign = "＋" if positive else "−"
    if kind == "duration":
        return f"{sign}{value} сек"
    return f"{sign}{value} {_pluralize_reps(value)}"


def _format_major_weight_label(value: float, positive: bool) -> str:
    sign = "＋" if positive else "−"
    return f"{sign}{_format_step_label(value)} кг"


def exercise_actions_kb(
    mode: str,
    with_weight: bool,
    kind: str,
    has_history: bool,
    prefs: "UiPreferences",
    *,
    day: int,
    ue_id: int,
    group: str,
    weight_step: float | None = None,
    is_amrap: bool = False,
    is_for_time: bool = False,
    back_callback: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    addset_cb = f"ex:addset:{day}:{ue_id}"
    delset_cb = f"ex:delset:{day}:{ue_id}"
    inc_base = f"ex:inc:{day}:{ue_id}"
    progress_cb = f"ex:progress:{day}:{ue_id}"
    done_cb = f"ex:done:{day}:{ue_id}"

    if is_for_time:
        row: list[InlineKeyboardButton] = [
            InlineKeyboardButton("⏱️ Ввести время", callback_data=done_cb)
        ]
        if has_history:
            row.append(InlineKeyboardButton("📈 История", callback_data=progress_cb))
        row.append(InlineKeyboardButton("◀️ Назад", callback_data=back_callback))
        return InlineKeyboardMarkup([row])

    if is_amrap:
        rows.append(
            [
                InlineKeyboardButton("＋ круг", callback_data=addset_cb),
                InlineKeyboardButton("− круг", callback_data=delset_cb),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    "＋ повтор", callback_data=f"ex:amrapextra:{day}:{ue_id}:1"
                ),
                InlineKeyboardButton(
                    "− повтор", callback_data=f"ex:amrapextra:{day}:{ue_id}:-1"
                ),
            ]
        )
        if prefs.mode == "detailed":
            rows.append(
                [
                    InlineKeyboardButton(
                        "＋5 повторов", callback_data=f"ex:amrapextra:{day}:{ue_id}:5"
                    ),
                    InlineKeyboardButton(
                        "−5 повторов",
                        callback_data=f"ex:amrapextra:{day}:{ue_id}:-5",
                    ),
                ]
            )
        final_row: list[InlineKeyboardButton] = [
            InlineKeyboardButton("✅ Готово", callback_data=done_cb)
        ]
        if has_history:
            final_row.append(InlineKeyboardButton("📈 История", callback_data=progress_cb))
        final_row.append(InlineKeyboardButton("◀️ Назад", callback_data=back_callback))
        rows.append(final_row)
        return InlineKeyboardMarkup(rows)

    rep_field = "sec" if kind == "duration" else "reps"
    plus_one, minus_one = _rep_control_labels(kind)
    rows.append(
        [
            InlineKeyboardButton("＋ сет", callback_data=addset_cb),
            InlineKeyboardButton("− сет", callback_data=delset_cb),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(plus_one, callback_data=f"{inc_base}:{rep_field}:1"),
            InlineKeyboardButton(minus_one, callback_data=f"{inc_base}:{rep_field}:-1"),
        ]
    )
    if prefs.mode == "detailed":
        if kind == "duration":
            major_row: list[InlineKeyboardButton] = []
            for step in (5, 10):
                major_row.append(
                    InlineKeyboardButton(
                        _format_major_rep_label(kind, step, True),
                        callback_data=f"{inc_base}:{rep_field}:{_format_signed_delta(step)}",
                    )
                )
                major_row.append(
                    InlineKeyboardButton(
                        _format_major_rep_label(kind, step, False),
                        callback_data=f"{inc_base}:{rep_field}:{_format_signed_delta(-step)}",
                    )
                )
            rows.append(major_row)
        else:
            rep_major_row: list[InlineKeyboardButton] = []
            for step in (2, 5, 10):
                rep_major_row.append(
                    InlineKeyboardButton(
                        _format_major_rep_label(kind, step, True),
                        callback_data=f"{inc_base}:{rep_field}:{_format_signed_delta(step)}",
                    )
                )
                rep_major_row.append(
                    InlineKeyboardButton(
                        _format_major_rep_label(kind, step, False),
                        callback_data=f"{inc_base}:{rep_field}:{_format_signed_delta(-step)}",
                    )
                )
            rows.append(rep_major_row)
            if with_weight:
                weight_row: list[InlineKeyboardButton] = []
                for step in (5.0, 10.0):
                    weight_row.append(
                        InlineKeyboardButton(
                            _format_major_weight_label(step, True),
                            callback_data=f"{inc_base}:kg:{_format_signed_delta(step)}",
                        )
                    )
                    weight_row.append(
                        InlineKeyboardButton(
                            _format_major_weight_label(step, False),
                            callback_data=f"{inc_base}:kg:{_format_signed_delta(-step)}",
                        )
                    )
                rows.append(weight_row)
    if with_weight:
        step_value = weight_step if weight_step is not None else 1.0
        step_label = _format_step_label(step_value)
        delta = _format_weight_delta(step_value)
        rows.append(
            [
                InlineKeyboardButton(
                    f"＋ шаг кг||＋ {step_label} кг",
                    callback_data=f"{inc_base}:kg:{delta}",
                ),
                InlineKeyboardButton(
                    f"− шаг кг||− {step_label} кг",
                    callback_data=f"{inc_base}:kg:{_format_weight_delta(-step_value)}",
                ),
            ]
        )
    if has_history:
        rows.append([InlineKeyboardButton("📈 История", callback_data=progress_cb)])
    rows.append(
        [
            InlineKeyboardButton("✅ Готово", callback_data=done_cb),
            InlineKeyboardButton("◀️ Назад", callback_data=back_callback),
        ]
    )
    return InlineKeyboardMarkup(rows)


def recording_mode_kb(current: str):
    mark_single = "✅ " if current == "single" else ""
    mark_flex = "✅ " if current == "flex" else ""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{mark_single}Одинаковый вес", callback_data="set:recording:single")],
        [InlineKeyboardButton(f"{mark_flex}Гибкая запись", callback_data="set:recording:flex")],
        [InlineKeyboardButton(t("BACK"), callback_data="menu:settings")],
    ])


def library_menu_kb(groups: list[tuple[str, int]], custom: dict[str, str] | None = None):
    custom = custom or {}
    rows = []
    for code, cnt in groups:
        name = MG_NAMES.get(code, custom.get(code, code))
        rows.append([
            InlineKeyboardButton(f"{name} ({cnt})", callback_data=f"lib:group:{code}")
        ])
    rows.append([InlineKeyboardButton("➕ Добавить упражнение", callback_data="lib:add:start")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="menu:root")])
    return InlineKeyboardMarkup(rows)


def library_group_kb(group: str, items: list[tuple[int, str]]):
    rows: list[list[InlineKeyboardButton]] = []
    for ue_id, name in items:
        rows.append([InlineKeyboardButton(name, callback_data=f"lib:ex:{group}:{ue_id}")])
    rows.append([
        InlineKeyboardButton("➕ Добавить упражнение", callback_data=f"lib:add:start:{group}")
    ])
    if items:
        rows.append([
            InlineKeyboardButton("🗑 Удалить упражнение", callback_data=f"lib:delmenu:{group}")
        ])
    if group.startswith("u"):
        rows.append(
            [
                InlineKeyboardButton(
                    "🗑 Удалить группу", callback_data=f"lib:groupdel:{group}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="lib:root")])
    return InlineKeyboardMarkup(rows)


def library_delete_kb(group: str, items: list[tuple[int, str]]):
    rows = []
    for ue_id, name in items:
        rows.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"lib:del:{group}:{ue_id}")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data=f"lib:group:{group}")])
    return InlineKeyboardMarkup(rows)


def library_add_group_kb(custom: dict[str, str] | None = None):
    rows = []
    for code, name in MG_NAMES.items():
        if code == "other":
            continue
        rows.append([InlineKeyboardButton(name, callback_data=f"lib:add:mg:{code}")])
    if custom:
        for code, name in custom.items():
            rows.append([InlineKeyboardButton(name, callback_data=f"lib:add:mg:{code}")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="lib:root")])
    return InlineKeyboardMarkup(rows)


def library_add_exercises_kb(
    group: str,
    ex_rows: list[tuple[int, str]],
    selected: set[int],
    page: int = 0,
):
    rows: list[list[InlineKeyboardButton]] = []
    total_pages = 1
    if group == "kb":
        blocks, page, total_pages = get_kb_catalog_page(ex_rows, page)
        for cat_key, items in blocks:
            header = t(cat_key if cat_key != KB_MISC_CATEGORY else KB_MISC_CATEGORY)
            rows.append([InlineKeyboardButton(header, callback_data="noop")])
            for ex_id, name in items:
                mark = "✅" if ex_id in selected else "⬜"
                rows.append(
                    [
                        InlineKeyboardButton(
                            f"{mark} {name}",
                            callback_data=f"lib:add:ex:{group}:{ex_id}",
                        )
                    ]
                )
    else:
        for ex_id, name in ex_rows:
            mark = "✅" if ex_id in selected else "⬜"
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{mark} {name}", callback_data=f"lib:add:ex:{group}:{ex_id}"
                    )
                ]
            )
    if group == "kb" and total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    t("PREV"), callback_data=f"lib:add:page:{group}:{page - 1}"
                )
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    t("NEXT"), callback_data=f"lib:add:page:{group}:{page + 1}"
                )
            )
        if nav_row:
            rows.append(nav_row)
    rows.append([InlineKeyboardButton("📝 Свой вариант", callback_data=f"lib:add:custom:{group}")])
    rows.append(
        [
            InlineKeyboardButton(t("DONE"), callback_data="lib:add:done"),
            InlineKeyboardButton(t("BACK"), callback_data="lib:add:back"),
        ]
    )
    return InlineKeyboardMarkup(rows), page, total_pages


def confirm_day_group_delete_kb(day_index: int, group: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Да, удалить",
                    callback_data=f"day:groupdel:{day_index}:{group}:ok",
                )
            ],
            [InlineKeyboardButton("↩️ Отмена", callback_data=f"day:group:{day_index}:{group}")],
        ]
    )


def confirm_library_group_delete_kb(group: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Да, удалить",
                    callback_data=f"lib:groupdel:{group}:ok",
                )
            ],
            [InlineKeyboardButton("↩️ Отмена", callback_data=f"lib:group:{group}")],
        ]
    )
def measurements_main_kb(show_all: bool):
    toggle = "Скрыть редкие" if show_all else "Показать ещё"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Добавить", callback_data="measure:add"),
            InlineKeyboardButton("✏️ Изменить", callback_data="measure:edit"),
        ],
        [
            InlineKeyboardButton("🗑 Удалить", callback_data="measure:delete"),
            InlineKeyboardButton(toggle, callback_data="measure:toggle"),
        ],
        [
            InlineKeyboardButton("📊 График", callback_data="measure:graph"),
            InlineKeyboardButton(t("BACK"), callback_data="menu:root"),
        ],
    ])


def measurements_category_kb(action: str, categories: list[tuple[str, str]]):
    rows = []
    for code, title in categories:
        rows.append([InlineKeyboardButton(title, callback_data=f"measure:{action}:cat:{code}")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="measure:back")])
    return InlineKeyboardMarkup(rows)


def measurements_metric_kb(action: str, category: str, metrics: list[tuple[str, str]]):
    rows = []
    for code, title in metrics:
        rows.append(
            [InlineKeyboardButton(title, callback_data=f"measure:{action}:item:{category}:{code}")]
        )
    rows.append([InlineKeyboardButton(t("BACK"), callback_data=f"measure:{action}")])
    return InlineKeyboardMarkup(rows)


def measurements_existing_kb(action: str, metrics: list[tuple[str, str]]):
    rows = []
    for code, title in metrics:
        rows.append([InlineKeyboardButton(title, callback_data=f"measure:{action}:metric:{code}")])
    rows.append([InlineKeyboardButton(t("BACK"), callback_data="measure:back")])
    return InlineKeyboardMarkup(rows)
