from bot import (
    SHARE_RESULTS_COPY_TEXT_MAX_LENGTH,
    ShareExerciseProgress,
    _render_share_results_copy_text,
)


def test_share_results_copy_text_contains_full_results_within_limit():
    header = "Я тренируюсь с ботом уже много недель и хочу поделиться успехами!"
    measurements = [
        "Вес: −2 кг",
        "Талия: −4 см",
    ]
    exercises = [
        ShareExerciseProgress(name="Жим лёжа", start_weight=50, end_weight=70, delta=20),
        ShareExerciseProgress(name="Присед", start_weight=60, end_weight=85, delta=25),
    ]
    link = "https://example.com/join"

    copy_text = _render_share_results_copy_text(header, measurements, exercises, link)

    assert "Вес: −2 кг" in copy_text
    assert "Талия: −4 см" in copy_text
    assert "• Жим лёжа: +20 кг" in copy_text
    assert "• Присед: +25 кг" in copy_text
    assert len(copy_text) <= SHARE_RESULTS_COPY_TEXT_MAX_LENGTH


def test_share_results_copy_text_is_shortened_when_too_long():
    header = "Я тренируюсь с ботом уже много недель и хочу поделиться успехами!"
    measurements = [
        f"Показатель {i}: {value}"
        for i, value in enumerate(
            [
                "значение, которое делает текст очень длинным",
                "ещё одно длинное значение показателя",
                "и так далее, пока текст не станет слишком большим",
                "добавим больше данных для проверки обрезки",
                "и ещё немного, чтобы превысить лимит",
                "вот ещё одна запись показателя",
            ]
        )
    ] * 20
    exercises = [
        ShareExerciseProgress(name=f"Упражнение {i}", start_weight=50, end_weight=70, delta=20)
        for i in range(30)
    ]
    link = "https://example.com/join"

    copy_text = _render_share_results_copy_text(header, measurements, exercises, link)

    assert len(copy_text) <= SHARE_RESULTS_COPY_TEXT_MAX_LENGTH
    assert copy_text.endswith(f"Подключайся 👉 {link}")
