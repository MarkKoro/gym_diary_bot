import atexit
import importlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta, UTC
from zoneinfo import ZoneInfo


tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db.close()
atexit.register(lambda: os.path.exists(tmp_db.name) and os.remove(tmp_db.name))

os.environ["DB_PATH"] = tmp_db.name

import settings  # noqa: E402
importlib.reload(settings)
import db  # noqa: E402
importlib.reload(db)
import bot  # noqa: E402
importlib.reload(bot)


class DayCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()

    async def asyncTearDown(self):
        async with db.connect_db() as conn:
            for table in ("day_completions", "user_reminders", "user_days", "users"):
                await conn.execute(f"DELETE FROM {table}")
            await conn.commit()

    async def test_completions_persist_within_training_week(self):
        user_id = await db.get_or_create_user(8000, "weekuser")
        await db.set_user_timezone(user_id, "Europe/Moscow")
        now = datetime.now(UTC)
        local_now = now.astimezone(ZoneInfo("Europe/Moscow"))
        dow = local_now.weekday()
        await db.add_user_reminder(
            user_id,
            dow=dow + 1,
            hour=local_now.hour,
            minute=local_now.minute,
            day_no=1,
        )
        past = now - timedelta(hours=7)
        await db.mark_day_completed(user_id, 1, past.isoformat())
        completions = await bot.get_active_day_completions(user_id)
        self.assertEqual({1}, completions)

    async def test_completions_reset_on_new_training_week(self):
        user_id = await db.get_or_create_user(8001, "resetuser")
        await db.set_user_timezone(user_id, "UTC")
        now = datetime.now(UTC)
        dow = now.weekday()
        await db.add_user_reminder(
            user_id,
            dow=dow + 1,
            hour=9,
            minute=0,
            day_no=1,
        )
        past = now - timedelta(days=7, hours=1)
        await db.mark_day_completed(user_id, 1, past.isoformat())
        completions = await bot.get_active_day_completions(user_id)
        self.assertEqual(set(), completions)


if __name__ == "__main__":
    unittest.main()
