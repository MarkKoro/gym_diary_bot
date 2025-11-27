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
    def __init__(self, name, callback, when_obj, chat_id, data, days=None):
        super().__init__(name)
        self.callback = callback
        self.when = when_obj
        self.chat_id = chat_id
        self.data = data
        self.days = tuple(days or [])


class FakeJobQueue:
    def __init__(self):
        self.jobs_by_name: dict[str, list[FakeJob]] = {}
        self.created_jobs: list[FakeScheduledJob] = []

    def get_jobs_by_name(self, name: str):
        return self.jobs_by_name.get(name, [])

    def run_daily(self, callback, time=None, days=None, chat_id=None, name=None, data=None, job_kwargs=None):
        _ = (callback, job_kwargs)
        job = FakeScheduledJob(name, callback, time, chat_id, data, days=days or [])
        self.jobs_by_name.setdefault(name, []).append(job)
        self.created_jobs.append(job)

    def run_once(self, callback, when, chat_id=None, name=None, data=None, job_kwargs=None):
        _ = job_kwargs
        job = FakeScheduledJob(name, callback, when, chat_id, data)
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
        self.assertEqual(new_job.chat_id, 9300)
        self.assertIsNotNone(new_job.when)
        self.assertEqual(new_job.when.tzinfo, ZoneInfo("Asia/Irkutsk"))
        local_time = new_job.when
        self.assertEqual(local_time.hour, 7)
        self.assertEqual(local_time.minute, 45)
        expected_weekday = db.normalize_dow(5)
        self.assertEqual(new_job.days, (expected_weekday,))
        self.assertEqual(
            {
                "user_id": new_job.data["user_id"],
                "day_no": new_job.data["day_no"],
                "dow": new_job.data["dow"],
            },
            {"user_id": user_id, "day_no": 2, "dow": 4},
        )
        self.assertIn("tag", new_job.data)
        self.assertIn("tz", new_job.data)

    async def test_reminder_status_sorted_by_day(self):
        text = bot.build_reminders_settings_text(
            "МСК",
            enabled=True,
            reminders=[
                (3, 5, 9, 0),
                (1, 2, 8, 30),
                (2, 3, 7, 45),
            ],
        )

        expected_line = "Сейчас выбраны напоминания: Ср 08:30, Чт 07:45, Сб 09:00."
        self.assertIn(expected_line, text)

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

    async def test_schedule_all_reminders_skips_disabled_users(self):
        user_id = await db.get_or_create_user(9500, "disabled-user")
        await db.add_user_reminder(
            user_id,
            dow=5,
            hour=9,
            minute=0,
            day_no=1,
        )
        await db.set_user_notifications_enabled(user_id, False)

        queue = FakeJobQueue()
        job_name = f"rem_{user_id}_1_5"
        queue.jobs_by_name[job_name] = [FakeJob(job_name)]
        app = SimpleNamespace(job_queue=queue)

        await bot.schedule_all_reminders(app)

        self.assertFalse(queue.created_jobs)
        stored_jobs = queue.jobs_by_name.get(job_name, [])
        self.assertTrue(stored_jobs)
        for job in stored_jobs:
            self.assertTrue(job.removed)


if __name__ == "__main__":
    unittest.main()
