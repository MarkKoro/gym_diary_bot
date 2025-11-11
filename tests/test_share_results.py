from telegram import CopyTextButton

from bot import (
    SHARE_RESULTS_COPY_TEXT_MAX_LENGTH,
    ShareExerciseProgress,
    _render_share_results_copy_text,
    build_share_results_keyboard,
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
    assert len(copy_text.encode("utf-8")) <= SHARE_RESULTS_COPY_TEXT_MAX_LENGTH


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

    assert len(copy_text.encode("utf-8")) <= SHARE_RESULTS_COPY_TEXT_MAX_LENGTH
    assert copy_text.endswith(f"Подключайся 👉 {link}")


def test_build_share_results_keyboard_uses_copy_text_button_without_callback():
    copy_text = "copy this text"

    kb = build_share_results_keyboard(enable_shuffle=False, copy_text=copy_text)

    button = kb.inline_keyboard[0][0]
    assert button.text == "📋 Скопировать"
    assert button.callback_data is None
    assert isinstance(button.copy_text, CopyTextButton)
    assert button.copy_text.text == copy_text
    assert len(kb.inline_keyboard) == 2
    assert kb.inline_keyboard[1][0].callback_data == "menu:settings"


def test_build_share_results_keyboard_includes_shuffle_when_enabled():
    kb = build_share_results_keyboard(enable_shuffle=True, copy_text="")

    assert len(kb.inline_keyboard) == 3
    shuffle_button = kb.inline_keyboard[1][0]
    assert shuffle_button.text == "🎲 Рандом"
    assert shuffle_button.callback_data == "settings:share_results:shuffle"
