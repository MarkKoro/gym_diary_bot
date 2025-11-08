from bot import (
    SHARE_RESULTS_COPY_TEXT_MAX_LENGTH,
    ShareExerciseProgress,
    _render_share_results_copy_text,
)


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
    ]
    exercises = [
        ShareExerciseProgress(name=f"Упражнение {i}", start_weight=50, end_weight=70, delta=20)
        for i in range(6)
    ]
    link = "https://example.com/join"

    copy_text = _render_share_results_copy_text(header, measurements, exercises, link)

    assert len(copy_text) <= SHARE_RESULTS_COPY_TEXT_MAX_LENGTH
    assert copy_text.endswith(f"Подключайся 👉 {link}")
