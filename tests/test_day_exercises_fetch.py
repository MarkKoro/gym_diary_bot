import atexit
import importlib
import os
import tempfile
import unittest
from datetime import UTC, datetime


tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db.close()
atexit.register(lambda: os.path.exists(tmp_db.name) and os.remove(tmp_db.name))

os.environ["DB_PATH"] = tmp_db.name

import settings  # noqa: E402
importlib.reload(settings)
import db  # noqa: E402
importlib.reload(db)


class FetchDayExercisesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()

    async def test_fetch_day_exercises_not_duplicated_by_other_system_sessions(self):
        user_id = await db.get_or_create_user(9100, "dupcheck")
        ex_id = await db.get_or_create_exercise("Тест упражнение", "chest")
        await db.add_user_exercise(user_id, 1, ex_id)

        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        primary_session = await db.get_or_create_today_session(user_id, date_str, 1, system_id=0)

        async with db.connect_db() as conn:
            await conn.execute(
                "INSERT INTO sessions(user_id, date, day_index, system_id) VALUES(?,?,?,?)",
                (user_id, date_str, 1, 999),
            )
            cur = await conn.execute("SELECT id FROM user_exercises WHERE user_id=? AND day_index=?", (user_id, 1))
            ue_id = (await cur.fetchone())[0]
            await conn.execute(
                "INSERT INTO session_exercises(session_id, user_exercise_id, is_done) VALUES(?,?,1)",
                (primary_session, ue_id),
            )
            await conn.commit()

        rows = await db.fetch_day_exercises(user_id, 1, date_str)
        self.assertEqual(1, len(rows))


if __name__ == "__main__":
    unittest.main()
