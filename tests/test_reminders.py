import atexit
import importlib
import os
import tempfile
import unittest
from types import SimpleNamespace

from zoneinfo import ZoneInfo


class FakeJob:
    def __init__(self, name: str):
        self.name = name
        self.removed = False

    def schedule_removal(self):
        self.removed = True


class FakeScheduledJob(FakeJob):
    def __init__(self, name, callback, time_obj, days, chat_id, data):
        super().__init__(name)
        self.callback = callback
        self.time = time_obj
        self.days = days
        self.chat_id = chat_id
        self.data = data


class FakeJobQueue:
    def __init__(self):
        self.jobs_by_name: dict[str, list[FakeJob]] = {}
        self.created_jobs: list[FakeScheduledJob] = []

    def get_jobs_by_name(self, name: str):
        return self.jobs_by_name.get(name, [])

    def run_daily(self, callback, time_obj, days, chat_id, name, data):
        job = FakeScheduledJob(name, callback, time_obj, days, chat_id, data)
        self.jobs_by_name.setdefault(name, []).append(job)
        self.created_jobs.append(job)

    def jobs(self):
        all_jobs: list[FakeJob] = []
        for items in self.jobs_by_name.values():
            all_jobs.extend(items)
        return all_jobs


_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
atexit.register(lambda: os.path.exists(_tmp_db.name) and os.remove(_tmp_db.name))

os.environ["DB_PATH"] = _tmp_db.name

import settings  # noqa: E402
importlib.reload(settings)
import db  # noqa: E402
importlib.reload(db)
import bot  # noqa: E402
importlib.reload(bot)


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
                dow=dow + 1,
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

    async def test_schedule_all_reminders_respects_timezone_and_days(self):
        user_id = await db.get_or_create_user(9300, "schedule-user")
        await db.set_user_timezone(user_id, "Asia/Irkutsk")
        await db.add_user_reminder(
            user_id,
            dow=5,
            hour=7,
            minute=45,
            day_no=2,
        )

        queue = FakeJobQueue()
        job_name = f"rem_{user_id}_2_4"
        queue.jobs_by_name[job_name] = [FakeJob(job_name)]
        app = SimpleNamespace(job_queue=queue)

        await bot.schedule_all_reminders(app)

        stored_jobs = queue.jobs_by_name[job_name]
        self.assertGreaterEqual(len(stored_jobs), 2)
        old_job, new_job = stored_jobs[0], stored_jobs[-1]
        self.assertTrue(old_job.removed)
        self.assertIsInstance(new_job, FakeScheduledJob)
        self.assertEqual(new_job.days, (4,))
        self.assertEqual(new_job.chat_id, 9300)
        self.assertEqual(new_job.time.hour, 7)
        self.assertEqual(new_job.time.minute, 45)
        self.assertIsInstance(new_job.time.tzinfo, ZoneInfo)
        self.assertEqual(new_job.time.tzinfo.key, "Asia/Irkutsk")
        self.assertEqual(new_job.data, {"user_id": user_id, "day_no": 2, "dow": 4})

    async def test_schedule_all_reminders_removes_orphan_jobs(self):
        user_id = await db.get_or_create_user(9400, "cleanup-user")
        queue = FakeJobQueue()
        orphan_job_name = f"rem_{user_id}_3_1"
        queue.jobs_by_name[orphan_job_name] = [FakeJob(orphan_job_name)]
        app = SimpleNamespace(job_queue=queue)

        await bot.schedule_all_reminders(app)

        stored_jobs = queue.jobs_by_name.get(orphan_job_name, [])
        self.assertTrue(stored_jobs)
        for job in stored_jobs:
            self.assertTrue(job.removed)


if __name__ == "__main__":
    unittest.main()
