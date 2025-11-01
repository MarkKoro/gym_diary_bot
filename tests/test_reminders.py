import atexit
import importlib
import os
import tempfile
import unittest


_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
atexit.register(lambda: os.path.exists(_tmp_db.name) and os.remove(_tmp_db.name))

os.environ["DB_PATH"] = _tmp_db.name

import settings  # noqa: E402
importlib.reload(settings)
import db  # noqa: E402
importlib.reload(db)


class ReminderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()

    async def asyncTearDown(self):
        async with db.connect_db() as conn:
            for table in ("user_reminders", "user_days", "users"):
                await conn.execute(f"DELETE FROM {table}")
            await conn.commit()

    async def test_reminders_trimmed_when_days_reduced(self):
        user_id = await db.get_or_create_user(9100, "reminder-user")
        await db.set_workouts_per_week(user_id, 4)
        for day_no, dow in enumerate((0, 1, 2, 3), start=1):
            await db.add_user_reminder(
                user_id,
                dow=dow,
                hour=9 + day_no,
                minute=15,
                day_no=day_no,
            )
        reminders = await db.list_user_reminders(user_id)
        self.assertEqual(4, len(reminders))
        removed = await db.set_workouts_per_week(user_id, 2)
        self.assertEqual({3, 4}, {day for day, *_ in removed})
        current = await db.list_user_reminders(user_id)
        self.assertEqual([1, 2], [day for day, *_ in current])


if __name__ == "__main__":
    unittest.main()
