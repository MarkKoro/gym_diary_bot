from __future__ import annotations

from typing import Sequence, Tuple

# Category keys reference localized labels from ui_texts.t
KB_CATEGORY_DEFINITION: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "KB_CAT_BALLISTICS",
        (
            "Махи гирей (русские)",
            "Махи гирей (американские)",
            "Подъём гири на грудь (Clean) левая",
            "Подъём гири на грудь (Clean) правая",
            "Рывок гири (Snatch) левая",
            "Рывок гири (Snatch) правая",
            "Толчок гирь (2×)",
            "Толчок гири одной рукой левая",
            "Толчок гири одной рукой правая",
            "Толчок гири (Push Press) левая",
            "Толчок гири (Push Press) правая",
        ),
    ),
    (
        "KB_CAT_GRINDS",
        (
            "Жим гири стоя левая",
            "Жим гири стоя правая",
            "Жим гири сидя левая",
            "Жим гири сидя правая",
            "Тяга гири в наклоне левая",
            "Тяга гири в наклоне правая",
            "Тяга гири из пола (Deadlift)",
        ),
    ),
    (
        "KB_CAT_SQUATS",
        (
            "Присед с гирей у груди (Goblet)",
            "Фронтальный присед с двумя гирями (2×)",
            "Оверхед-присед с гирей левая",
            "Оверхед-присед с гирей правая",
        ),
    ),
    (
        "KB_CAT_CARRIES",
        (
            "Фермерская прогулка (2×)",
            "Чемоданная прогулка левая",
            "Чемоданная прогулка правая",
            "Прогулка в стойке над головой левая",
            "Прогулка в стойке над головой правая",
            "Прогулка в позиции на груди (Rack) (2×)",
        ),
    ),
    (
        "KB_CAT_CORE",
        (
            "Турецкий подъём левая",
            "Турецкий подъём правая",
            "Ветряная мельница левая",
            "Ветряная мельница правая",
        ),
    ),
    (
        "KB_CAT_COMPLEXES",
        (
            "Длинный цикл (Clean & Jerk) (2×)",
            "Clean → Press левая",
            "Clean → Press правая",
            "Swing → Goblet Squat (2×)",
        ),
    ),
)

KB_EXERCISE_NAMES: Tuple[str, ...] = tuple(
    name for _, names in KB_CATEGORY_DEFINITION for name in names
)

KB_CATEGORY_LOOKUP = {name: key for key, names in KB_CATEGORY_DEFINITION for name in names}

KB_MISC_CATEGORY = "KB_CAT_MISC"


def categorize_kb_exercises(
    exercises: Sequence[tuple[int, str]]
) -> list[tuple[str, list[tuple[int, str]]]]:
    buckets: dict[str, list[tuple[int, str]]] = {
        key: [] for key, _ in KB_CATEGORY_DEFINITION
    }
    extras: list[tuple[int, str]] = []
    for ex_id, name in exercises:
        key = KB_CATEGORY_LOOKUP.get(name)
        if key:
            buckets[key].append((ex_id, name))
        else:
            extras.append((ex_id, name))
    extras.sort(key=lambda item: item[1].lower())
    ordered: list[tuple[str, list[tuple[int, str]]]] = []
    for key, _ in KB_CATEGORY_DEFINITION:
        block = buckets[key]
        if block:
            ordered.append((key, block))
    if extras:
        ordered.append((KB_MISC_CATEGORY, extras))
    return ordered


def get_kb_catalog_page(
    exercises: Sequence[tuple[int, str]],
    page: int = 0,
    per_page: int = 18,
) -> tuple[list[tuple[str, list[tuple[int, str]]]], int, int]:
    blocks = categorize_kb_exercises(exercises)
    if not blocks:
        return [], 0, 1
    pages: list[list[tuple[str, list[tuple[int, str]]]]] = []
    current: list[tuple[str, list[tuple[int, str]]]] = []
    count = 0
    for block in blocks:
        block_size = len(block[1])
        if current and count + block_size > per_page:
            pages.append(current)
            current = []
            count = 0
        current.append(block)
        count += block_size
    if current:
        pages.append(current)
    total_pages = len(pages) or 1
    page = max(0, min(page, total_pages - 1))
    return (pages[page] if pages else []), page, total_pages
