from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ui_texts import t
from kb_catalog import get_kb_catalog_page, KB_MISC_CATEGORY


def dual(compact: str, detailed: str | None = None) -> str:
    return compact


BACK_BTN = dual("‹ Назад", "Назад")
DONE_BTN = dual("✅ Готово", "Готово")
CANCEL_BTN = dual("↩︎ Отмена", "Отмена")
HISTORY_BTN = dual("📈 История", "Посмотреть историю")
CUSTOM_OPTION_BTN = dual("📝 Свой вариант", "Добавить свой вариант")
RUNNING_GROUP = "run"

if TYPE_CHECKING:
    from bot import UiPreferences


def _is_editing_allowed(context) -> bool:
    if context is None:
        return True
    return not (
        context.user_data.get("acting_user_id")
        and not context.user_data.get("acting_can_edit")
    )


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

def main_menu_kb(
    days: list[tuple[int, str]],
    support_url: str,
    completed_days: set[int] | None = None,
    *,
    show_trainer: bool = False,
    show_support: bool = True,
    include_settings: bool = True,
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
):
    completed_days = completed_days or set()
    rows = []
    for idx, label in days:
        display_label = label or f"{t('DAY')} {idx}"
        mark = "✅ " if idx in completed_days else ""
        rows.append(
            [
                InlineKeyboardButton(
                    dual(f"{mark}{display_label}", f"Открыть {display_label}"),
                    callback_data=f"day:open:{idx}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                dual(
                    "📘 Мои упражнения",
                    "Мои упражнения — личная библиотека",
                ),
                callback_data="menu:library",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                dual(
                    t("MEAS_TITLE"),
                    f"Перейти в раздел «{t('MEAS_TITLE')}»",
                ),
                callback_data="menu:metrics",
            )
        ]
    )
    if show_trainer:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("👥 Мои подопечные", "Открыть список подопечных"),
                    callback_data="trainer:list",
                )
            ]
        )
    if include_settings:
        rows.append(
            [
                InlineKeyboardButton(
                    dual(
                        "⚙︎ Настройки",
                        "Открыть настройки интерфейса и расписания",
                    ),
                    callback_data="menu:settings",
                )
            ]
        )
    if extra_rows:
        rows.extend(extra_rows)
    if show_support:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("📩 Техподдержка", "Связаться с техподдержкой"),
                    url=support_url,
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def week_count_kb() -> InlineKeyboardMarkup:
    rows = []
    for i in range(1, 8):
        rows.append(
            [
                InlineKeyboardButton(
                    dual(str(i), f"Выбрать {i} тренировок в неделю"),
                    callback_data=f"wiz:week:set:{i}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)

def subscription_kb(join_url: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(dual("📢 Подписаться", "Оформить подписку"), url=join_url)],
        [InlineKeyboardButton(DONE_BTN, callback_data="wiz:sub:verify")],
    ])


def subscribe_channel_prompt_kb(join_url: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    dual("📢 Подписаться на канал", "Подписаться на канал"),
                    url=join_url,
                )
            ],
            [
                InlineKeyboardButton(
                    dual("Нет, спасибо", "Нет, спасибо"),
                    callback_data="promo:channel:no",
                )
            ],
        ]
    )


def settings_kb(
    *,
    include_notifications: bool = True,
    include_subscription: bool = True,
    trainer_link_active: bool = False,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        dual(
                            "✏️ Переименовать дни",
                            "Переименовать дни и задать названия",
                        ),
                        callback_data="set:rename_day",
                    )
                ],
                [
                    InlineKeyboardButton(
                        dual("🔁 Изменить день", "Настроить программу дня"),
                        callback_data="set:edit_day",
                    )
                ],
                [
                    InlineKeyboardButton(
                        dual(
                            "📅 Количество тренировок",
                            "Выбрать количество тренировочных дней",
                        ),
                        callback_data="set:days_count",
                    )
                ],
                [
                    InlineKeyboardButton(
                        dual(
                            "🗑 Удаление моих групп мышц",
                            "Удалить созданные группы мышц",
                        ),
                        callback_data="set:groups",
                    )
                ],
            ]
        )
        if include_notifications:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual("⏰ Уведомления", "Настроить напоминания"),
                        callback_data="set:reminders",
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    dual(
                        "🧑‍🏫 Тренер / подопечный",
                        "Связать дневник с тренером или вести своих подопечных",
                    ),
                    callback_data="set:trainer_mode",
                )
            ]
        )
        if include_subscription:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual("💳 Подписка", "Управление подпиской"),
                        callback_data="menu:subscription",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:root")])
    return InlineKeyboardMarkup(rows)


def trainee_become_kb(can_edit: bool) -> InlineKeyboardMarkup:
    toggle_state = "off" if can_edit else "on"
    rows = [
        [
            InlineKeyboardButton(
                dual(
                    "🔑 Ввести код тренера",
                    "Ввести код, который тренер отправил тебе",
                ),
                callback_data="set:trainer_link",
            )
        ],
        [
            InlineKeyboardButton(
                dual(
                    f"Разрешить тренеру менять план: {'Вкл' if can_edit else 'Выкл'}",
                    "Переключить право тренера управлять твоим планом",
                ),
                callback_data=f"trainer:allow:{toggle_state}",
            )
        ],
        [
            InlineKeyboardButton(
                dual(
                    "⬅️ Назад в режим тренера",
                    "Вернуться к настройкам режима тренера",
                ),
                callback_data="set:trainer_mode",
            )
        ],
    ]
    return InlineKeyboardMarkup(rows)


def trainee_trainer_settings_kb(can_edit: bool):
    toggle_state = "off" if can_edit else "on"
    toggle_label = dual(
        f"Разрешить тренеру менять план: {'Вкл' if can_edit else 'Выкл'}",
        "Отключить право тренеру менять план"
        if can_edit
        else "Включить право тренеру менять план",
    )
    rows = [
        [
            InlineKeyboardButton(
                toggle_label,
                callback_data=f"trainer:allow:{toggle_state}",
            )
        ],
        [
            InlineKeyboardButton(
                dual("Переименовать тренера", "Изменить отображаемое имя тренера"),
                callback_data="trainer:label:set",
            )
        ],
        [
            InlineKeyboardButton(
                dual("Отвязаться от тренера", "Отключить связь с тренером"),
                callback_data="trainer:detach",
            )
        ],
        [
            InlineKeyboardButton(
                dual("⬅️ Назад в настройки", "Вернуться в настройки"),
                callback_data="menu:settings",
            )
        ],
    ]
    return InlineKeyboardMarkup(rows)


def trainer_manage_trainee_kb(
    can_edit: bool, trainee_user_id: int
) -> InlineKeyboardMarkup:
    toggle_state = "off" if can_edit else "on"
    rows = [
        [
            InlineKeyboardButton(
                dual(
                    f"Право менять план: {'Вкл' if can_edit else 'Выкл'}",
                    "Переключить доступ к редактированию плана",
                ),
                callback_data=f"trainer:allow:{toggle_state}",
            )
        ],
        [
            InlineKeyboardButton(
                dual(
                    "Переименовать подопечного",
                    "Задать своё имя для подопечного",
                ),
                callback_data=f"trainer:trainee:label:set:{trainee_user_id}",
            )
        ],
        [
            InlineKeyboardButton(
                dual(
                    "Открепить подопечного",
                    "Завершить совместную работу",
                ),
                callback_data="trainer:detach",
            )
        ],
        [
            InlineKeyboardButton(
                dual(
                    "⬅️ В дневник подопечного",
                    "Вернуться к меню подопечного",
                ),
                callback_data="trainer:trainee:menu",
            )
        ],
    ]
    return InlineKeyboardMarkup(rows)

def rename_day_kb(days: list[tuple[int, str]], context=None):
    editing_allowed = _is_editing_allowed(context)
    rows = []
    if editing_allowed:
        for idx, label in days:
            display_label = (label or "").strip() or f"{t('DAY')} {idx}"
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(display_label, f"Переименовать {display_label}"),
                        callback_data=f"set:rename_day:{idx}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)


def settings_groups_kb(groups: list[tuple[str, str]], context=None):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        for code, name in groups:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(f"− {name}", f"Удалить группу «{name}»"),
                        callback_data=f"set:groups:del:{code}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)


def edit_day_select_kb(days: list[tuple[int, str]], context=None):
    editing_allowed = _is_editing_allowed(context)
    rows = []
    if editing_allowed:
        for idx, label in days:
            display_label = (label or "").strip() or f"{t('DAY')} {idx}"
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(display_label, f"Настроить {display_label}"),
                        callback_data=f"set:edit_day:{idx}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)


def edit_day_mode_kb(day_index: int, *, context=None):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        "🏋️ Силовая",
                        callback_data=f"set:edit_day:{day_index}:strength",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏋️‍♀️ Гири", callback_data=f"set:edit_day:{day_index}:kb"
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
            ]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="set:edit_day")])
    return InlineKeyboardMarkup(rows)


def edit_day_strength_kb(day_index: int, *, context=None):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("🗂 Группы", "Выбрать группы упражнений"),
                    callback_data=f"day:add_ex:{day_index}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                dual("📋 Открыть день", "Открыть выбранный день"),
                callback_data=f"day:open:{day_index}",
            )
        ]
    )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=f"set:edit_day:{day_index}")])
    return InlineKeyboardMarkup(rows)


def edit_day_special_kb(day_index: int, group: str, label: str):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label, callback_data=f"day:add:{day_index}:mg:{group}"
                )
            ],
            [
                InlineKeyboardButton(
                    dual("📋 Открыть день", "Открыть выбранный день"),
                    callback_data=f"day:open:{day_index}",
                )
            ],
            [InlineKeyboardButton(BACK_BTN, callback_data=f"set:edit_day:{day_index}")],
        ]
    )

def days_count_kb(context=None):
    editing_allowed = _is_editing_allowed(context)
    rows = []
    if editing_allowed:
        for i in range(1, 8):
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(str(i), f"Установить {i} тренировок"),
                        callback_data=f"set:days_count:{i}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")])
    return InlineKeyboardMarkup(rows)

def _option_marker(active: bool) -> str:
    return "◉" if active else "○"


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
    "run": "Бег",
    "other": "Другое",
}

def muscle_groups_kb(day_index: int, selected: set[str], custom: dict[str, str] | None = None):
    rows = []
    for code, name in MG_NAMES.items():
        if code == "other":
            continue
        mark = "✅" if code in selected else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    dual(
                        f"{mark} {name}",
                        f"{'Выбрана ' if code in selected else ''}группа «{name}»",
                    ),
                    callback_data=f"wiz:day:{day_index}:mg:{code}",
                )
            ]
        )
    if custom:
        for code, name in custom.items():
            mark = "✅" if code in selected else "⬜"
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(
                            f"{mark} {name}",
                            f"{'Выбрана ' if code in selected else ''}группа «{name}»",
                        ),
                        callback_data=f"wiz:day:{day_index}:mg:{code}",
                    )
                ]
            )
    rows.append(
        [
            InlineKeyboardButton(
                dual(
                    f"⬜ {MG_NAMES['other']}",
                    f"Добавить свою группу ({MG_NAMES['other']})",
                ),
                callback_data=f"wiz:day:{day_index}:mg:other",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                dual("▶︎ Далее", "Перейти к выбору упражнений"),
                callback_data=f"wiz:day:{day_index}:groups:next",
            ),
            InlineKeyboardButton(
                dual("⏭ Пропустить", "Пропустить этот день"),
                callback_data=f"wiz:day:{day_index}:skip",
            ),
        ]
    )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=f"wiz:day:{day_index}:back")])
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
                            dual(
                                f"{mark} {name}",
                                (
                                    f"Выбрано упражнение «{name}»"
                                    if ex_id in selected
                                    else f"Добавить упражнение «{name}»"
                                ),
                            ),
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
                        dual(
                            f"{mark} {name}",
                            (
                                f"Выбрано упражнение «{name}»"
                                if ex_id in selected
                                else f"Добавить упражнение «{name}»"
                            ),
                        ),
                        callback_data=f"wiz:day:{day_index}:ex:add:{ex_id}",
                    )
                ]
            )
    if group == "kb" and total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    dual("◀︎ Назад", "Предыдущая страница"),
                    callback_data=f"wiz:day:{day_index}:ex:page:{group}:{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    dual("Далее ▶︎", "Следующая страница"),
                    callback_data=f"wiz:day:{day_index}:ex:page:{group}:{page + 1}",
                )
            )
        if nav_row:
            rows.append(nav_row)
    rows.append(
        [
            InlineKeyboardButton(
                CUSTOM_OPTION_BTN, callback_data=f"wiz:day:{day_index}:ex:custom:{group}"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(BACK_BTN, callback_data=f"wiz:day:{day_index}:ex:back"),
            InlineKeyboardButton(DONE_BTN, callback_data=f"wiz:day:{day_index}:ex:done"),
        ]
    )
    return InlineKeyboardMarkup(rows), page, total_pages

def baseline_kb(
    day_index: int,
    sets: int,
    reps: int,
    seconds: int,
    weight: float,
    prefix: str = "wiz:base",
    include_skip_all: bool = True,
    *,
    with_weight: bool = True,
    kind: str = "reps",
):
    def btn(label: str, cb: str):
        return InlineKeyboardButton(label, callback_data=cb)

    def cb(*parts: str) -> str:
        return ":".join((prefix, *parts))

    rows = [
        [
            btn(dual("＋1 сет", "Добавить 1 сет"), cb("inc", "sets", "1")),
            btn(dual("−1 сет", "Убрать 1 сет"), cb("inc", "sets", "-1")),
        ],
        [
            btn(dual("＋5 повт", "Добавить 5 повторов"), cb("inc", "reps", "5")),
            btn(dual("−5 повт", "Убрать 5 повторов"), cb("inc", "reps", "-5")),
        ],
        [
            btn(dual("＋1 повт", "Добавить 1 повтор"), cb("inc", "reps", "1")),
            btn(dual("−1 повт", "Убрать 1 повтор"), cb("inc", "reps", "-1")),
        ],
    ]
    if kind == "duration":
        rows.extend(
            [
                [
                    btn(dual("＋30 сек", "Добавить 30 секунд"), cb("inc", "sec", "30")),
                    btn(dual("＋5 сек", "Добавить 5 секунд"), cb("inc", "sec", "5")),
                    btn(dual("＋1 сек", "Добавить 1 секунду"), cb("inc", "sec", "1")),
                ],
                [
                    btn(dual("−30 сек", "Убрать 30 секунд"), cb("inc", "sec", "-30")),
                    btn(dual("−5 сек", "Убрать 5 секунд"), cb("inc", "sec", "-5")),
                    btn(dual("−1 сек", "Убрать 1 секунду"), cb("inc", "sec", "-1")),
                ],
            ]
        )
    if with_weight:
        rows.extend(
            [
                [
                    btn(dual("＋0.5 кг", "Добавить 0.5 кг"), cb("inc", "kg", "0.5")),
                    btn(dual("＋1 кг", "Добавить 1 кг"), cb("inc", "kg", "1")),
                    btn(dual("＋5 кг", "Добавить 5 кг"), cb("inc", "kg", "5")),
                    btn(dual("＋10 кг", "Добавить 10 кг"), cb("inc", "kg", "10")),
                    btn(dual("＋25 кг", "Добавить 25 кг"), cb("inc", "kg", "25")),
                    btn(dual("＋50 кг", "Добавить 50 кг"), cb("inc", "kg", "50")),
                ],
                [
                    btn(dual("−0.5 кг", "Убрать 0.5 кг"), cb("inc", "kg", "-0.5")),
                    btn(dual("−1 кг", "Убрать 1 кг"), cb("inc", "kg", "-1")),
                    btn(dual("−5 кг", "Убрать 5 кг"), cb("inc", "kg", "-5")),
                    btn(dual("−10 кг", "Убрать 10 кг"), cb("inc", "kg", "-10")),
                    btn(dual("−25 кг", "Убрать 25 кг"), cb("inc", "kg", "-25")),
                    btn(dual("−50 кг", "Убрать 50 кг"), cb("inc", "kg", "-50")),
                ],
            ]
        )
    rows.extend(
        [
            [btn(DONE_BTN, cb("ready")), btn(BACK_BTN, cb("back"))],
            [btn(dual("⏭ Пропустить", "Пропустить это упражнение"), cb("skip"))],
        ]
    )
    if include_skip_all:
        rows.append(
            [
                btn(
                    dual("⏭ Пропустить настройку", "Пропустить настройку веса"),
                    f"wiz:day:{day_index}:baseline:skip_all",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)

def day_done_kb(day_index: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                dual(
                    f"▶︎ {t('DAY')} {day_index+1}",
                    f"Перейти к {t('DAY')} {day_index+1}",
                ),
                callback_data=f"wiz:day:{day_index}:next",
            )
        ],
        [
            InlineKeyboardButton(
                dual("⏹ Завершить", "Завершить онбординг"),
                callback_data="wiz:finish_early",
            )
        ],
        [InlineKeyboardButton(BACK_BTN, callback_data=f"wiz:day:{day_index}:redo")],
    ])

def reminders_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                dual("Да", "Включить напоминания"), callback_data="wiz:reminders:yes"
            ),
            InlineKeyboardButton(
                dual("Нет", "Отключить напоминания"), callback_data="wiz:reminders:no"
            ),
        ],
        [InlineKeyboardButton(BACK_BTN, callback_data="wiz:reminders:back")],
    ])


def reminder_prompt_kb():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    dual("Да", "Включить напоминания"), callback_data="wiz:reminders:yes"
                ),
                InlineKeyboardButton(
                    dual("Нет", "Отключить напоминания"), callback_data="wiz:reminders:no"
                ),
            ]
        ]
    )


def reminders_edit_kb(enabled: bool):
    toggle_state = "off" if enabled else "on"
    toggle_label = dual(
        f"Уведомления: {'Вкл' if enabled else 'Выкл'}",
        "Отключить все напоминания, не изменяя расписание"
        if enabled
        else "Включить напоминания по сохранённому расписанию",
    )
    rows = [
        [
            InlineKeyboardButton(
                toggle_label,
                callback_data=f"set:reminders:toggle:{toggle_state}",
            )
        ],
        [
            InlineKeyboardButton(
                dual("Изменить часовой пояс", "Настроить часовой пояс напоминаний"),
                callback_data="set:reminders:tz",
            )
        ],
        [
            InlineKeyboardButton(
                dual("Изменить дни и время", "Настроить расписание напоминаний"),
                callback_data="set:reminders:time",
            )
        ],
        [InlineKeyboardButton(BACK_BTN, callback_data="menu:settings")],
    ]
    return InlineKeyboardMarkup(rows)


def reminders_schedule_kb(entries: list[tuple[int, str]]):
    rows = []
    for position, label in entries:
        rows.append(
            [
                InlineKeyboardButton(
                    dual(label, f"Настроить уведомление для {label}"),
                    callback_data=f"remedit:day:{position}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="remedit:back")])
    return InlineKeyboardMarkup(rows)

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
        rows.append(
            [
                InlineKeyboardButton(
                    dual(label, f"Выбрать часовой пояс {label}"),
                    callback_data=f"wiz:tzsel:set:{zone}",
                )
            ]
        )
    nav = []
    if start > 0:
        nav.append(
            InlineKeyboardButton(
                dual("◀︎ Назад", "Предыдущая страница"),
                callback_data=f"wiz:tzsel:page:{page-1}",
            )
        )
    if end < len(TIMEZONES):
        nav.append(
            InlineKeyboardButton(
                dual("Далее ▶︎", "Следующая страница"),
                callback_data=f"wiz:tzsel:page:{page+1}",
            )
        )
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="wiz:tzsel:back")])
    return InlineKeyboardMarkup(rows)

def reminder_time_kb(
    prefix: str = "wiz:remind",
    selected: tuple[int, int] | None = None,
    page: int = 0,
):
    slots = [(h, m) for h in range(6, 23) for m in (0, 30)]
    page_size = 16
    total_pages = (len(slots) + page_size - 1) // page_size or 1
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    end = start + page_size
    page_slots = slots[start:end]
    rows: list[list[InlineKeyboardButton]] = []
    buttons: list[InlineKeyboardButton] = []
    for hour, minute in page_slots:
        time_label = f"{hour:02d}:{minute:02d}"
        display = time_label
        if selected and selected == (hour, minute):
            display = f"✅ {time_label}"
        buttons.append(
            InlineKeyboardButton(
                dual(display, f"Выбрать время {time_label}"),
                callback_data=f"{prefix}:{time_label}",
            )
        )
    for idx in range(0, len(buttons), 2):
        rows.append(buttons[idx : idx + 2])
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    dual("◀︎ Раньше", "Предыдущие варианты"),
                    callback_data=f"{prefix}:page:{page-1}",
                )
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    dual("Позже ▶︎", "Следующие варианты"),
                    callback_data=f"{prefix}:page:{page+1}",
                )
            )
        if nav_row:
            rows.append(nav_row)
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=f"{prefix}:back")])
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


def reminder_day_kb(prefix: str = "wiz:rday", selected: int | None = None):
    rows = []
    for dow, label in WEEKDAYS:
        display = label
        if selected is not None and selected == dow:
            display = f"✅ {label}"
        rows.append(
            [
                InlineKeyboardButton(
                    dual(display, f"Добавить день {label}"),
                    callback_data=f"{prefix}:{dow + 1}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=f"{prefix}:back")])
    return InlineKeyboardMarkup(rows)

def day_kb(day_index: int, ex_rows: list[tuple[int, str, str, int, int]], *, context=None):
    editing_allowed = _is_editing_allowed(context)
    groups: dict[str, list[tuple[int, str]]] = {}
    for ue_id, name, group, _, _ in ex_rows:
        groups.setdefault(group, []).append((ue_id, name))
    rows = []
    for group in groups.keys():
        gname = MG_NAMES.get(group, group)
        rows.append(
            [
                InlineKeyboardButton(
                    dual(f"{gname} ▸", f"Открыть группу «{gname}»"),
                    callback_data=f"day:group:{day_index}:{group}",
                )
            ]
        )
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("➕ Добавить", "Добавить группу мышц"),
                    callback_data=f"day:manage:{day_index}:all:add",
                ),
                InlineKeyboardButton(
                    dual("🗑 Удалить", "Удалить группу мышц"),
                    callback_data=f"day:manage:{day_index}:all:del",
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    dual(t("CLOSE_DAY"), "Отметить тренировку завершённой"),
                    callback_data=f"day:complete:{day_index}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:root")])
    return InlineKeyboardMarkup(rows)


def day_group_kb(
    day_index: int,
    group: str,
    items: list[tuple[int, str, int]],
    *,
    group_name: str | None = None,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    rows = []
    for ue_id, name, done in items:
        mark = "✅" if done else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    dual(
                        f"{mark} {name} ▸",
                        f"Открыть упражнение «{name}»",
                    ),
                    callback_data=f"ex:view:{day_index}:{ue_id}",
                )
            ]
        )
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("➕ Добавить", "Добавить упражнения"),
                    callback_data=f"day:manage:{day_index}:{group}:add",
                ),
                InlineKeyboardButton(
                    dual("🗑 Удалить", "Удалить упражнения"),
                    callback_data=f"day:manage:{day_index}:{group}:del",
                ),
            ]
        )
        if group.startswith("u"):
            label = group_name or "Группа"
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(
                            f"− {label}",
                            (
                                f"Удалить группу «{label}»"
                                if group_name
                                else "Удалить группу упражнений"
                            ),
                        ),
                        callback_data=f"day:groupdel:{day_index}:{group}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=f"day:open:{day_index}")])
    return InlineKeyboardMarkup(rows)


def day_add_group_kb(
    day_index: int,
    custom: dict[str, str] | None = None,
    selected: set[str] | None = None,
    *,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    rows = []
    selected = selected or set()
    if editing_allowed:
        for code, name in MG_NAMES.items():
            if code == "other":
                continue
            mark = "✅" if code in selected else "⬜"
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(
                            f"{mark} {name}",
                            f"{'Выбрана ' if code in selected else ''}группа «{name}»",
                        ),
                        callback_data=f"day:add:{day_index}:mg:{code}",
                    )
                ]
            )
        if custom:
            for code, name in custom.items():
                mark = "✅" if code in selected else "⬜"
                rows.append(
                    [
                        InlineKeyboardButton(
                            dual(
                                f"{mark} {name}",
                                f"{'Выбрана ' if code in selected else ''}группа «{name}»",
                            ),
                            callback_data=f"day:add:{day_index}:mg:{code}",
                        )
                    ]
                )
        rows.append(
            [
                InlineKeyboardButton(
                    dual("➕ Добавить группу", "Создать свою группу мышц"),
                    callback_data=f"day:add:{day_index}:custom_group",
                )
            ]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=f"day:open:{day_index}")])
    return InlineKeyboardMarkup(rows)


def day_remove_group_kb(
    day_index: int, groups: list[tuple[str, str]], *, context=None
) -> InlineKeyboardMarkup:
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        for code, name in groups:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(f"− {name}", f"Удалить группу «{name}»"),
                        callback_data=f"day:remove_group:{day_index}:{code}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=f"day:open:{day_index}")])
    return InlineKeyboardMarkup(rows)

def day_add_exercises_kb(
    day_index: int,
    group: str,
    ex_rows: list[tuple[int, str]],
    selected: set[int] | None = None,
    page: int = 0,
    *,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    if not editing_allowed:
        return (
            InlineKeyboardMarkup(
                [[InlineKeyboardButton(BACK_BTN, callback_data=f"day:open:{day_index}")]]
            ),
            0,
            1,
        )
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
                            dual(
                                f"{mark} {name}",
                                (
                                    f"Выбрано упражнение «{name}»"
                                    if ex_id in selected
                                    else f"Добавить упражнение «{name}»"
                                ),
                            ),
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
                        dual(
                            f"{mark} {name}",
                            (
                                f"Выбрано упражнение «{name}»"
                                if ex_id in selected
                                else f"Добавить упражнение «{name}»"
                            ),
                        ),
                        callback_data=f"day:add:{day_index}:ex:{ex_id}",
                    )
                ]
            )
    if group == "kb" and total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    dual("◀︎ Назад", "Предыдущая страница"),
                    callback_data=f"day:add:{day_index}:page:{group}:{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    dual("Далее ▶︎", "Следующая страница"),
                    callback_data=f"day:add:{day_index}:page:{group}:{page + 1}",
                )
            )
        if nav_row:
            rows.append(nav_row)
    if group != RUNNING_GROUP:
        rows.append(
            [
                InlineKeyboardButton(
                    CUSTOM_OPTION_BTN,
                    callback_data=f"day:add:{day_index}:custom:{group}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(DONE_BTN, callback_data=f"day:add:{day_index}:done")])
    return InlineKeyboardMarkup(rows), page, total_pages

def del_exercises_kb(
    day_index: int,
    ex_rows: list[tuple[int, str, str, int, int]],
    *,
    group: str | None = None,
    back_callback: str | None = None,
    add_callback: str | None = None,
    group_delete_callback: str | None = None,
    group_delete_label: str | None = None,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    rows = []
    if editing_allowed:
        for ue_id, name, raw_group, *_ in ex_rows:
            if group is not None and raw_group != group:
                continue
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(f"− {name}", f"Удалить упражнение «{name}»"),
                        callback_data=f"day:del:{day_index}:{ue_id}",
                    )
                ]
            )
        if add_callback:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual("➕ Добавить", "Вернуться к добавлению упражнений"),
                        callback_data=add_callback,
                    )
                ]
            )
        if group_delete_callback:
            label = group_delete_label or "Группа"
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(
                            f"− {label}",
                            (
                                f"Удалить группу «{label}»"
                                if group_delete_label
                                else "Удалить группу упражнений"
                            ),
                        ),
                        callback_data=group_delete_callback,
                    )
                ]
            )
    back_cb = back_callback if back_callback is not None else f"day:open:{day_index}"
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)

def _format_step_label(step: float) -> str:
    text = f"{step:g}"
    return text.replace(".0", "") if text.endswith(".0") else text


def _rep_control_labels(kind: str) -> tuple[tuple[str, str], tuple[str, str]]:
    if kind == "duration":
        return ("＋1 сек", "Добавить 1 секунду"), ("−1 сек", "Убрать 1 секунду")
    return ("＋ повтор", "Добавить 1 повтор"), ("− повтор", "Убрать 1 повтор")


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


def _format_major_rep_label(kind: str, value: int, positive: bool) -> tuple[str, str]:
    sign = "＋" if positive else "−"
    verb = "Добавить" if positive else "Убрать"
    if kind == "duration":
        return f"{sign}{value} сек", f"{verb} {value} секунд"
    unit = _pluralize_reps(value)
    return f"{sign}{value} {unit}", f"{verb} {value} {unit}"


def _format_major_weight_label(value: float, positive: bool) -> tuple[str, str]:
    sign = "＋" if positive else "−"
    verb = "Добавить" if positive else "Убрать"
    step = _format_step_label(value)
    return f"{sign}{step} кг", f"{verb} {step} кг"


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
    is_amrap: bool = False,
    is_for_time: bool = False,
    back_callback: str,
    context=None,
) -> InlineKeyboardMarkup:
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    addset_cb = f"ex:addset:{day}:{ue_id}"
    delset_cb = f"ex:delset:{day}:{ue_id}"
    inc_base = f"ex:inc:{day}:{ue_id}"
    progress_cb = f"ex:progress:{day}:{ue_id}"
    done_cb = f"ex:done:{day}:{ue_id}"

    if is_for_time:
        row: list[InlineKeyboardButton] = [
            InlineKeyboardButton(BACK_BTN, callback_data=back_callback)
        ]
        if editing_allowed:
            row.insert(
                0,
                InlineKeyboardButton(
                    dual("⏱️ Ввести время", "Сохранить и ввести время"),
                    callback_data=done_cb,
                ),
            )
        if has_history:
            history_button = InlineKeyboardButton(HISTORY_BTN, callback_data=progress_cb)
            row.insert(-1 if editing_allowed else len(row), history_button)
        return InlineKeyboardMarkup([row])

    if is_amrap:
        if editing_allowed:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual("＋ Круг", "Добавить круг"), callback_data=addset_cb
                    ),
                    InlineKeyboardButton(
                        dual("− Круг", "Убрать круг"), callback_data=delset_cb
                    ),
                ]
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        dual("＋ Повтор", "Добавить повтор"),
                        callback_data=f"ex:amrapextra:{day}:{ue_id}:1",
                    ),
                    InlineKeyboardButton(
                        dual("− Повтор", "Убрать повтор"),
                        callback_data=f"ex:amrapextra:{day}:{ue_id}:-1",
                    ),
                ]
            )
            if prefs.mode == "detailed":
                rows.append(
                    [
                        InlineKeyboardButton(
                            dual("＋5 повторов", "Добавить 5 повторов"),
                            callback_data=f"ex:amrapextra:{day}:{ue_id}:5",
                        ),
                        InlineKeyboardButton(
                            dual("−5 повторов", "Убрать 5 повторов"),
                            callback_data=f"ex:amrapextra:{day}:{ue_id}:-5",
                        ),
                    ]
                )
        final_row: list[InlineKeyboardButton] = []
        if editing_allowed:
            final_row.append(InlineKeyboardButton(DONE_BTN, callback_data=done_cb))
        if has_history:
            final_row.append(InlineKeyboardButton(HISTORY_BTN, callback_data=progress_cb))
        final_row.append(InlineKeyboardButton(BACK_BTN, callback_data=back_callback))
        rows.append(final_row)
        return InlineKeyboardMarkup(rows)

    rep_field = "sec" if kind == "duration" else "reps"
    (plus_compact, plus_detailed), (minus_compact, minus_detailed) = _rep_control_labels(kind)
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(dual("＋ Сет", "Добавить сет"), callback_data=addset_cb),
                InlineKeyboardButton(dual("− Сет", "Убрать сет"), callback_data=delset_cb),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    dual(plus_compact, plus_detailed),
                    callback_data=f"{inc_base}:{rep_field}:1",
                ),
                InlineKeyboardButton(
                    dual(minus_compact, minus_detailed),
                    callback_data=f"{inc_base}:{rep_field}:-1",
                ),
            ]
        )
        if prefs.mode == "detailed":
            if kind == "duration":
                major_row: list[InlineKeyboardButton] = []
                for step in (5, 25):
                    compact, detailed = _format_major_rep_label(kind, step, True)
                    major_row.append(
                        InlineKeyboardButton(
                            dual(compact, detailed),
                            callback_data=f"{inc_base}:{rep_field}:{_format_signed_delta(step)}",
                        )
                    )
                    compact, detailed = _format_major_rep_label(kind, step, False)
                    major_row.append(
                        InlineKeyboardButton(
                            dual(compact, detailed),
                            callback_data=f"{inc_base}:{rep_field}:{_format_signed_delta(-step)}",
                        )
                    )
                rows.append(major_row)
            else:
                rep_major_row: list[InlineKeyboardButton] = []
                steps = [5]
                if group == "workout":
                    steps.append(15)
                for step in steps:
                    compact, detailed = _format_major_rep_label(kind, step, True)
                    rep_major_row.append(
                        InlineKeyboardButton(
                            dual(compact, detailed),
                            callback_data=f"{inc_base}:{rep_field}:{_format_signed_delta(step)}",
                        )
                    )
                    compact, detailed = _format_major_rep_label(kind, step, False)
                    rep_major_row.append(
                        InlineKeyboardButton(
                            dual(compact, detailed),
                            callback_data=f"{inc_base}:{rep_field}:{_format_signed_delta(-step)}",
                        )
                    )
                rows.append(rep_major_row)
    if kind == "duration" and editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("＋1 повтор", "Добавить 1 повтор"),
                    callback_data=f"{inc_base}:reps:1",
                ),
                InlineKeyboardButton(
                    dual("−1 повтор", "Убрать 1 повтор"),
                    callback_data=f"{inc_base}:reps:-1",
                ),
            ]
        )
        if prefs.mode == "detailed":
            rep_major_row: list[InlineKeyboardButton] = []
            for step in (5,):
                compact, detailed = _format_major_rep_label("reps", step, True)
                rep_major_row.append(
                    InlineKeyboardButton(
                        dual(compact, detailed),
                        callback_data=f"{inc_base}:reps:{_format_signed_delta(step)}",
                    )
                )
                compact, detailed = _format_major_rep_label("reps", step, False)
                rep_major_row.append(
                    InlineKeyboardButton(
                        dual(compact, detailed),
                        callback_data=f"{inc_base}:reps:{_format_signed_delta(-step)}",
                    )
                )
            if rep_major_row:
                rows.append(rep_major_row)
    if with_weight and editing_allowed:
        positive_row: list[InlineKeyboardButton] = []
        negative_row: list[InlineKeyboardButton] = []
        for step in (0.5, 3.0, 10.0):
            compact, detailed = _format_major_weight_label(step, True)
            positive_row.append(
                InlineKeyboardButton(
                    dual(compact, detailed),
                    callback_data=f"{inc_base}:kg:{_format_weight_delta(step)}",
                )
            )
            compact, detailed = _format_major_weight_label(step, False)
            negative_row.append(
                InlineKeyboardButton(
                    dual(compact, detailed),
                    callback_data=f"{inc_base}:kg:{_format_weight_delta(-step)}",
                )
            )
        rows.append(positive_row)
        rows.append(negative_row)
    if has_history:
        rows.append([InlineKeyboardButton(HISTORY_BTN, callback_data=progress_cb)])
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    t("ADD_NOTE"), callback_data=f"ex:note:{day}:{ue_id}"
                )
            ]
        )
    final_row: list[InlineKeyboardButton] = []
    if editing_allowed:
        final_row.append(InlineKeyboardButton(DONE_BTN, callback_data=done_cb))
    final_row.append(InlineKeyboardButton(BACK_BTN, callback_data=back_callback))
    rows.append(final_row)
    return InlineKeyboardMarkup(rows)


def library_menu_kb(
    groups: list[tuple[str, int]],
    custom: dict[str, str] | None = None,
    *,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    custom = custom or {}
    rows = []
    for code, cnt in groups:
        name = MG_NAMES.get(code, custom.get(code, code))
        rows.append([
            InlineKeyboardButton(
                dual(
                    f"{name} ({cnt})",
                    f"Открыть группу «{name}» ({cnt})",
                ),
                callback_data=f"lib:group:{code}",
            )
        ])
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("➕ Добавить", "Добавить упражнения в библиотеку"),
                    callback_data="lib:add:start",
                )
            ]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:root")])
    return InlineKeyboardMarkup(rows)


def library_group_kb(
    group: str,
    items: list[tuple[int, str]],
    *,
    group_name: str | None = None,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    for ue_id, name in items:
        rows.append(
            [
                InlineKeyboardButton(
                    dual(name, f"Открыть упражнение «{name}»"),
                    callback_data=f"lib:ex:{group}:{ue_id}",
                )
            ]
        )
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("➕ Добавить", "Добавить упражнения"),
                    callback_data=f"lib:manage:{group}:add",
                ),
                InlineKeyboardButton(
                    dual("🗑 Удалить", "Удалить упражнения"),
                    callback_data=f"lib:manage:{group}:del",
                ),
            ]
        )
        if group.startswith("u"):
            label = group_name or "Группа"
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(
                            f"− {label}",
                            (
                                f"Удалить группу «{label}»"
                                if group_name
                                else "Удалить группу упражнений"
                            ),
                        ),
                        callback_data=f"lib:groupdel:{group}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="lib:root")])
    return InlineKeyboardMarkup(rows)


def library_manage_kb(
    group: str,
    items: list[tuple[int, str]],
    *,
    can_delete_group: bool,
    back_callback: str | None = None,
    add_callback: str | None = None,
    show_add_button: bool = True,
    context=None,
) -> InlineKeyboardMarkup:
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        for ue_id, name in items:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(f"− {name}", f"Удалить «{name}»"),
                        callback_data=f"lib:del:{group}:{ue_id}",
                    )
                ]
            )
        if not items:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual("Пока нет упражнений", "Добавь упражнения через «Добавить»"),
                        callback_data="noop",
                    )
                ]
            )
        if show_add_button:
            add_cb = add_callback or f"lib:manage:{group}:add"
            rows.append(
                [
                    InlineKeyboardButton(
                        dual("➕ Добавить", "Добавить упражнения"),
                        callback_data=add_cb,
                    )
                ]
            )
        if can_delete_group:
            label = group_name or "Группа"
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(
                            f"− {label}",
                            (
                                f"Удалить группу «{label}»"
                                if group_name
                                else "Удалить группу упражнений"
                            ),
                        ),
                        callback_data=f"lib:groupdel:{group}",
                    )
                ]
            )
    back_cb = back_callback or f"lib:group:{group}"
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)


def library_delete_kb(
    group: str,
    items: list[tuple[int, str]],
    *,
    back_callback: str | None = None,
    add_callback: str | None = None,
    can_delete_group: bool = False,
    group_name: str | None = None,
    context=None,
):
    return library_manage_kb(
        group,
        items,
        can_delete_group=can_delete_group,
        back_callback=back_callback,
        add_callback=add_callback,
        show_add_button=False,
        context=context,
    )


def library_add_group_kb(custom: dict[str, str] | None = None, *, context=None):
    editing_allowed = _is_editing_allowed(context)
    rows = []
    if editing_allowed:
        for code, name in MG_NAMES.items():
            if code == "other":
                continue
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(name, f"Выбрать группу «{name}»"),
                        callback_data=f"lib:add:mg:{code}",
                    )
                ]
            )
        if custom:
            for code, name in custom.items():
                rows.append(
                    [
                        InlineKeyboardButton(
                            dual(name, f"Выбрать группу «{name}»"),
                            callback_data=f"lib:add:mg:{code}",
                        )
                    ]
                )
        rows.append(
            [
                InlineKeyboardButton(
                    dual("➕ Добавить группу", "Создать свою группу мышц"),
                    callback_data="lib:add:custom_group",
                )
            ]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="lib:root")])
    return InlineKeyboardMarkup(rows)


def library_add_exercises_kb(
    group: str,
    ex_rows: list[tuple[int, str]],
    selected: set[int],
    page: int = 0,
    *,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    if not editing_allowed:
        return (
            InlineKeyboardMarkup(
                [[InlineKeyboardButton(BACK_BTN, callback_data="lib:add:back")]]
            ),
            0,
            1,
        )
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
                            dual(
                                f"{mark} {name}",
                                (
                                    f"Выбрано упражнение «{name}»"
                                    if ex_id in selected
                                    else f"Добавить упражнение «{name}»"
                                ),
                            ),
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
                        dual(
                            f"{mark} {name}",
                            (
                                f"Выбрано упражнение «{name}»"
                                if ex_id in selected
                                else f"Добавить упражнение «{name}»"
                            ),
                        ),
                        callback_data=f"lib:add:ex:{group}:{ex_id}",
                    )
                ]
            )
    if group == "kb" and total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    dual("◀︎ Назад", "Предыдущая страница"),
                    callback_data=f"lib:add:page:{group}:{page - 1}",
                )
            )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    dual("Далее ▶︎", "Следующая страница"),
                    callback_data=f"lib:add:page:{group}:{page + 1}",
                )
            )
        if nav_row:
            rows.append(nav_row)
    if group != RUNNING_GROUP:
        rows.append(
            [
                InlineKeyboardButton(
                    CUSTOM_OPTION_BTN, callback_data=f"lib:add:custom:{group}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(DONE_BTN, callback_data="lib:add:done"),
            InlineKeyboardButton(BACK_BTN, callback_data="lib:add:back"),
        ]
    )
    return InlineKeyboardMarkup(rows), page, total_pages


def confirm_day_group_delete_kb(day_index: int, group: str, *, context=None):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("✅ Готово", "Удалить группу"),
                    callback_data=f"day:groupdel:{day_index}:{group}:ok",
                )
            ]
        )
    rows.append([InlineKeyboardButton(CANCEL_BTN, callback_data=f"day:group:{day_index}:{group}")])
    return InlineKeyboardMarkup(rows)


def confirm_settings_group_delete_kb(group: str, *, context=None):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("✅ Готово", "Удалить группу"),
                    callback_data=f"set:groups:del:{group}:ok",
                )
            ]
        )
    rows.append([InlineKeyboardButton(CANCEL_BTN, callback_data="set:groups")])
    return InlineKeyboardMarkup(rows)


def confirm_library_group_delete_kb(group: str, *, context=None):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("✅ Готово", "Удалить группу"),
                    callback_data=f"lib:groupdel:{group}:ok",
                )
            ]
        )
    rows.append([InlineKeyboardButton(CANCEL_BTN, callback_data=f"lib:group:{group}")])
    return InlineKeyboardMarkup(rows)
def measurements_main_kb(show_all: bool, *, context=None):
    editing_allowed = _is_editing_allowed(context)
    toggle = "Скрыть пустые" if show_all else "Показ скрытых"
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual(
                        "＋ Добавить и редактировать",
                        "Добавить или отредактировать замеры",
                    ),
                    callback_data="measure:manage",
                ),
                InlineKeyboardButton(
                    dual("− Удалить", "Удалить замер"),
                    callback_data="measure:delete",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                dual(toggle, "Переключить отображение замеров"),
                callback_data="measure:toggle",
            ),
            InlineKeyboardButton(
                dual("🗂 История", "Показать историю замеров"),
                callback_data="measure:history",
            ),
        ]
    )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="menu:root")])
    return InlineKeyboardMarkup(rows)


def measurements_manage_overview_kb(
    categories: list[tuple[str, str]],
    include_delete: bool,
    back_callback: str = "measure:back",
    *,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    for code, title in categories:
        rows.append(
            [
                InlineKeyboardButton(
                    dual(title, f"Открыть категорию «{title}»"),
                    callback_data=f"measure:add:cat:{code}",
                )
            ]
        )
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual("＋ Добавить категорию", "Добавить новую категорию"),
                    callback_data="measure:manage:addcat",
                )
            ]
        )
        if include_delete:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(
                            "🗑 Удалить категорию или замер",
                            "Удалить пользовательскую категорию или замер",
                        ),
                        callback_data="measure:manage:delete",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


def measurements_category_kb(
    action: str,
    categories: list[tuple[str, str]],
    back_callback: str = "measure:back",
    *,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    rows = []
    if editing_allowed:
        for code, title in categories:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(title, f"Выбрать категорию «{title}»"),
                        callback_data=f"measure:{action}:cat:{code}",
                    )
                ]
            )
        if action in {"add", "customplace"}:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual("＋ Добавить категорию", "Создать новую категорию"),
                        callback_data="measure:add:category",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


def confirm_day_reset_kb(day_index: int, mode: str, *, context=None):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    dual(
                        "✅ Начать сначала",
                        "Очистить упражнения и начать настройку заново",
                    ),
                    callback_data=f"set:edit_day:{day_index}:{mode}:reset",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    dual(
                        "↩️ Оставить упражнения",
                        "Сохранить текущий план и продолжить настройку",
                    ),
                    callback_data=f"set:edit_day:{day_index}:{mode}:keep",
                )
            ]
        )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=f"set:edit_day:{day_index}")])
    return InlineKeyboardMarkup(rows)


def measurements_metric_kb(
    action: str,
    category: str,
    metrics: list[tuple[str, str]],
    include_custom_button: bool = False,
    *,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    rows = []
    if editing_allowed:
        for code, title in metrics:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(title, f"Выбрать метрику «{title}»"),
                        callback_data=f"measure:{action}:item:{category}:{code}",
                    )
                ]
            )
        if include_custom_button and action == "add":
            rows.append(
                [
                    InlineKeyboardButton(
                        dual("＋ Свой замер", "Добавить собственный замер"),
                        callback_data=f"measure:add:custom:new:{category}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=f"measure:{action}")])
    return InlineKeyboardMarkup(rows)


def measurements_existing_kb(
    action: str,
    metrics: list[tuple[str, str]],
    back_callback: str = "measure:back",
    *,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    rows = []
    if editing_allowed:
        for code, title in metrics:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(title, f"Выбрать «{title}»"),
                        callback_data=f"measure:{action}:metric:{code}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


def measurements_remove_kb(
    categories: list[tuple[str, str]],
    metrics: list[tuple[str, str]],
    *,
    context=None,
):
    editing_allowed = _is_editing_allowed(context)
    rows: list[list[InlineKeyboardButton]] = []
    if editing_allowed:
        for code, title in categories:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(
                            f"📁 {title}",
                            f"Удалить категорию «{title}»",  # pragma: no cover - format only
                        ),
                        callback_data=f"measure:manage:delete:cat:{code}",
                    )
                ]
            )
        for code, title in metrics:
            rows.append(
                [
                    InlineKeyboardButton(
                        dual(
                            f"📝 {title}",
                            f"Удалить замер «{title}»",  # pragma: no cover - format only
                        ),
                        callback_data=f"measure:manage:delete:item:{code}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(BACK_BTN, callback_data="measure:manage")])
    return InlineKeyboardMarkup(rows)
