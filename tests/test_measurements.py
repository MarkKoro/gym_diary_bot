import atexit
import os
import sys
import tempfile
import importlib
import unittest
from types import SimpleNamespace


tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db.close()
atexit.register(lambda: os.path.exists(tmp_db.name) and os.remove(tmp_db.name))

os.environ["DB_PATH"] = tmp_db.name
os.environ.setdefault("TG_TOKEN", "test-token")
os.environ.setdefault("ADMIN_IDS", "")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import settings  # noqa: E402
importlib.reload(settings)
import db  # noqa: E402
importlib.reload(db)
import bot  # noqa: E402
importlib.reload(bot)


class _FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.deleted = False

    async def delete(self):
        self.deleted = True


class _FakeBot:
    def __init__(self):
        self.edits: list[dict] = []

    async def edit_message_text(
        self, text, chat_id, message_id, reply_markup=None, **kwargs
    ):
        self.edits.append(
            {
                "text": text,
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup,
            }
        )


class MeasurementDbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()

    async def asyncTearDown(self):
        async with db.connect_db() as conn:
            for table in (
                "user_measurements",
                "user_measurement_custom",
                "user_measurement_categories",
                "sets",
                "session_exercises",
                "sessions",
                "user_exercises",
                "exercises",
                "users",
            ):
                await conn.execute(f"DELETE FROM {table}")
            await conn.commit()

    async def test_list_recent_progress_returns_all_sets(self):
        user_id = await db.get_or_create_user(101, "tester")
        exercise_id = await db.get_or_create_exercise("Тестовое упражнение", "chest")
        await db.add_user_exercise(user_id, 1, exercise_id)
        async with db.connect_db() as conn:
            cur = await conn.execute(
                """
                SELECT id FROM user_exercises
                WHERE user_id=? AND exercise_id=? AND day_index=?
                LIMIT 1
                """,
                (user_id, exercise_id, 1),
            )
            ue_id = (await cur.fetchone())[0]
        session_id = await db.get_or_create_today_session(user_id, "2023-01-01", day_index=1)
        await db.add_set(session_id, ue_id, reps=10, weight=50)
        await db.add_set(session_id, ue_id, reps=8, weight=55)
        await db.mark_exercise_done(session_id, ue_id)

        rows = await db.list_recent_progress(user_id, 1, ue_id, limit=5, offset=0)
        self.assertEqual(len(rows), 1)
        date, sets_cnt, reps_cnt, seconds_cnt, weight_val, details = rows[0]
        self.assertEqual(date, "2023-01-01")
        self.assertEqual(sets_cnt, 2)
        self.assertEqual(reps_cnt, 10)
        self.assertEqual(seconds_cnt, 0)
        self.assertAlmostEqual(weight_val, 55.0)
        self.assertEqual(details, [(10, 0, 50.0), (8, 0, 55.0)])

    async def test_list_recent_progress_uses_session_specific_exercise(self):
        user_id = await db.get_or_create_user(202, "tester")
        exercise_id = await db.get_or_create_exercise("Тяга", "back")
        await db.add_user_exercise(user_id, 1, exercise_id)
        await db.add_user_exercise(user_id, 2, exercise_id)
        async with db.connect_db() as conn:
            cur = await conn.execute(
                "SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=? AND day_index=?",
                (user_id, exercise_id, 1),
            )
            ue_day1 = (await cur.fetchone())[0]
            cur = await conn.execute(
                "SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=? AND day_index=?",
                (user_id, exercise_id, 2),
            )
            ue_day2 = (await cur.fetchone())[0]
        session_id = await db.get_or_create_today_session(user_id, "2023-01-05", day_index=1)
        await db.add_set(session_id, ue_day1, reps=12, weight=40)
        await db.add_set(session_id, ue_day1, reps=12, weight=40)
        await db.mark_exercise_done(session_id, ue_day1)

        rows = await db.list_recent_progress(user_id, 2, ue_day2, limit=5, offset=0)
        self.assertEqual(len(rows), 1)
        _, sets_cnt, reps_cnt, seconds_cnt, weight_val, details = rows[0]
        self.assertEqual(sets_cnt, 2)
        self.assertEqual(reps_cnt, 12)
        self.assertEqual(seconds_cnt, 0)
        self.assertAlmostEqual(weight_val, 40.0)
        self.assertEqual(details, [(12, 0, 40.0), (12, 0, 40.0)])

    async def test_delete_custom_measurement_removes_entries(self):
        user_id = await db.get_or_create_user(202, "measure")
        code = await db.add_custom_measurement(user_id, "Гибкость")
        await db.add_measurement_entry(user_id, code, 12.5, None)

        removed = await db.delete_custom_measurement(user_id, code)
        self.assertTrue(removed)
        custom = await db.list_custom_measurements(user_id)
        self.assertEqual(custom, [])
        history = await db.fetch_measurement_history(user_id, code)
        self.assertEqual(history, [])

    async def test_delete_measurement_category_removes_record(self):
        user_id = await db.get_or_create_user(303, "category-user")
        code = await db.add_measurement_category(user_id, "K", "Категория")

        removed = await db.delete_measurement_category(user_id, code)
        self.assertTrue(removed)
        categories = await db.list_measurement_categories(user_id)
        self.assertEqual(categories, [])

    async def test_custom_measurement_shown_without_values(self):
        user_id = await db.get_or_create_user(404, "viewer")
        await db.add_custom_measurement(user_id, "Гибкость")
        context = SimpleNamespace(user_data={})

        text, _ = await bot.build_measurements_view(user_id, context)

        self.assertIn("Гибкость — нет данных", text)

    async def test_custom_measurement_uses_origin_category(self):
        tg_id = 5050
        user_id = await db.get_or_create_user(tg_id, "category-flow")
        category_code = await db.add_measurement_category(user_id, "K", "Категория")
        bot.last_messages.clear()
        fake_bot = _FakeBot()
        chat_id = 4321
        message_id = 9876
        custom_state = {
            "chat_id": chat_id,
            "message_id": message_id,
            "back": f"measure:add:cat:{category_code}",
            "origin": category_code,
            "step": "name",
        }
        context = SimpleNamespace(user_data={bot.MEASUREMENT_CUSTOM_KEY: custom_state}, bot=fake_bot)
        update = SimpleNamespace(
            message=_FakeMessage("Новый показатель"),
            effective_user=SimpleNamespace(id=tg_id, username="category-flow"),
        )

        await bot.text_router(update, context)

        self.assertTrue(update.message.deleted)
        self.assertIsNone(context.user_data.get(bot.MEASUREMENT_CUSTOM_KEY))
        input_state = context.user_data.get(bot.MEASUREMENT_INPUT_KEY)
        self.assertIsNotNone(input_state)
        self.assertEqual(input_state["category"], category_code)
        custom_rows = await db.list_custom_measurements(user_id)
        self.assertEqual(len(custom_rows), 1)
        stored_code, stored_name, stored_category = custom_rows[0]
        self.assertEqual(stored_category, category_code)
        self.assertEqual(stored_code, input_state["metric"])
        self.assertEqual(stored_name, "Новый показатель")
        self.assertTrue(fake_bot.edits)
        edit = fake_bot.edits[-1]
        self.assertEqual(edit["chat_id"], chat_id)
        self.assertEqual(edit["message_id"], message_id)
        self.assertIn("Введи значение", edit["text"])
        markup = edit["reply_markup"]
        self.assertIsNotNone(markup)
        back_button = markup.inline_keyboard[-1][0]
        self.assertEqual(back_button.callback_data, f"measure:add:cat:{category_code}")


class ProgressFormattingTests(unittest.TestCase):
    def test_format_progress_sets_details_groups_identical_sets(self):
        from bot import format_progress_sets_details

        details = [(10, 0, 40.0), (10, 0, 40.0), (8, 0, 45.0)]
        text = format_progress_sets_details(details, with_weight=True, kind="reps")
        self.assertEqual(text, "2× 10 повт. при 40 кг; 8 повт. при 45 кг")

    def test_format_progress_sets_details_without_weight(self):
        from bot import format_progress_sets_details

        details = [(30, 45, 0.0), (30, 45, 0.0), (20, 30, 0.0)]
        text = format_progress_sets_details(details, with_weight=False, kind="duration")
        self.assertEqual(text, "2× 30 повт. · 45 сек; 20 повт. · 30 сек")


if __name__ == "__main__":
    unittest.main()
