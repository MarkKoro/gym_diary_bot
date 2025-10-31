import os
import tempfile
import unittest
import importlib
import atexit


_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
atexit.register(lambda: os.path.exists(_tmp.name) and os.remove(_tmp.name))
os.environ["DB_PATH"] = _tmp.name

import settings  # noqa: E402
importlib.reload(settings)
import db  # noqa: E402
importlib.reload(db)


class ExerciseNotesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()

    async def asyncTearDown(self):
        async with db.connect_db() as conn:
            for table in (
                "sets",
                "session_exercises",
                "sessions",
                "user_exercises",
                "exercises",
                "users",
            ):
                await conn.execute(f"DELETE FROM {table}")
            await conn.commit()

    async def test_latest_note_respects_recent_session(self):
        user_id = await db.get_or_create_user(2001, "notes")
        exercise_id = await db.get_or_create_exercise("Тяга тест", "back")
        await db.add_user_exercise(user_id, 1, exercise_id)
        async with db.connect_db() as conn:
            cur = await conn.execute(
                "SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=? AND day_index=1",
                (user_id, exercise_id),
            )
            ue_id = (await cur.fetchone())[0]
        session1 = await db.get_or_create_today_session(user_id, "2024-01-01", 1)
        await db.set_exercise_note(session1, ue_id, "Первый подход")
        await db.mark_exercise_done(session1, ue_id)
        note_session, note_value = await db.get_latest_completed_note(user_id, exercise_id)
        self.assertEqual(session1, note_session)
        self.assertEqual("Первый подход", note_value)

        session2 = await db.get_or_create_today_session(user_id, "2024-01-02", 1)
        await db.mark_exercise_done(session2, ue_id)
        note_session2, note_value2 = await db.get_latest_completed_note(user_id, exercise_id)
        self.assertEqual(session2, note_session2)
        self.assertIsNone(note_value2)

        await db.set_exercise_note(session2, ue_id, "Второй подход")
        note_session3, note_value3 = await db.get_latest_completed_note(user_id, exercise_id)
        self.assertEqual(session2, note_session3)
        self.assertEqual("Второй подход", note_value3)
        self.assertEqual("Второй подход", await db.get_exercise_note(session2, ue_id))


if __name__ == "__main__":
    unittest.main()
