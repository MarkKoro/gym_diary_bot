from __future__ import annotations

from types import MappingProxyType

STRINGS_RU = MappingProxyType(
    {
        "MAIN_TITLE": "Главное меню",
        "BACK": "↩ Назад",
        "DONE": "✅ Готово",
        "CLOSE_DAY": "✅ Завершить день",
        "HISTORY": "История",
        "NEXT": "➡️",
        "PREV": "⬅️",
        "DAY": "День",
        "PLAN": "План",
        "LAST_TIME": "Прошлый раз",
        "MADE": "Сделано",
        "NOTE": "Заметка",
        "LAST_NOTE": "Заметка прошлого раза",
        "ADD_NOTE": "✏️ Добавить заметку",
        "NOTE_PROMPT": "Добавь заметку для этой тренировки.",
        "NOTE_EXAMPLE": "Например: «Делал тягу в нижнем блоке с узким хватом».",
        "NOTE_HINT": "Отправь заметку одним сообщением — она сохранится к этой тренировке.",
        "NOTE_EMPTY": "Заметка не должна быть пустой.",
        "NOT_SET": "не задан",
        "NOT_FIXED": "не зафиксирован",
        "ONBOARDING_INTRO": (
            "Привет! 👋\n"
            "Ознакомься с этим коротким обучающим видео.\n"
            "А дальше под тебя настроим тренировки, чтобы бот помогал, а не мешал.\n"
            "Сейчас будет пара коротких вопросов: сколько раз в неделю тренируешься и нужны ли напоминания.\n"
            "Всё это можно будет потом изменить в настройках."
        ),
        "METCON_TITLE": "Меткон",
        "AMRAP_TITLE": "AMRAP",
        "FOR_TIME_TITLE": "For Time",
        "ADD_SET": "＋ сет",
        "ADD_REP": "＋1",
        "AMRAP_LINE": "Сделано: {rounds} раундов + {extra} повт.",
        "AMRAP_RESULT": "{rounds} раундов + {extra} повт.",
        "FTIME_LINE": "Результат: {time}",
        "FTIME_RESULT": "{time}",
        "MEAS_TITLE": "📏 Мои замеры",
        "EMPTY_MEAS": "Замеров пока нет",
        "KB_CAT_BALLISTICS": "Балистика (динамика)",
        "KB_CAT_GRINDS": "Силовые (Grinds)",
        "KB_CAT_SQUATS": "Приседания с гирями",
        "KB_CAT_CARRIES": "Переносы (Carries)",
        "KB_CAT_CORE": "Кор/стабилизация",
        "KB_CAT_COMPLEXES": "Комплексы (упрощённые)",
        "KB_CAT_MISC": "Прочие упражнения",
    }
)

# Короткая подсказка после онбординга (перед входом в главное меню)
ONBOARDING_TIPS = (
    "✅ Всё готово!\n\n"
    "Как пользоваться:\n"
    "• Вес и повторы вводишь один раз — бот запоминает и подставляет в следующий раз. Обычно меняешь только число сетов. История — под карточкой упражнения.\n"
    "• День закрывай кнопкой «Завершить день» — стрик и «следующая тренировка» увидишь в главном меню.\n"
    "• «Тренер/Подопечный»: тренер создаёт код, подопечный вводит. Можно выдать тренеру право редактировать план. Без подписки — до 5 подопечных.\n"
    "• Уведомления по дням/времени привязаны к твоему часовому поясу. Включить/выключить — в «Настройках».\n\n"
    "Хочешь подробнее — открой «Инструкцию»."
)

EMOJI_THEME_DEFAULT = MappingProxyType(
    {
        "kb": "🥇",
        "metcon": "⚡️",
        "strength": "🏋️",
        "generic": "•",
        "done": "✅",
    }
)


def t(key: str, **fmt: object) -> str:
    """Return localized text for a key with optional formatting."""

    template = STRINGS_RU[key]
    return template.format(**fmt) if fmt else template


def e(key: str) -> str:
    """Return emoji for the provided key."""

    return EMOJI_THEME_DEFAULT.get(key, "")
