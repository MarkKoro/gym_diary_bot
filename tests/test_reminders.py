import atexit
import asyncio
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))


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

    async def test_trainer_editing_chat_never_becomes_reminder_destination(self):
        user_id = await db.get_or_create_user(9620, 'owner')
        await db.add_user_reminder(user_id, 1, 2, 10, 30)
        queue = FakeJobQueue()
        await bot._schedule_user_reminders(SimpleNamespace(job_queue=queue), user_id, chat_id=999999)
        self.assertTrue(queue.created_jobs)
        self.assertTrue(all(j.chat_id == 9620 and j.data['chat_id'] == 9620 for j in queue.created_jobs))

    async def test_legacy_job_rechecks_owner_destination_before_delivery_and_rescheduling(self):
        user_id = await db.get_or_create_user(9621, 'owner')
        queue = FakeJobQueue()
        data = dict(chat_id=999999, user_id=user_id, tz='UTC', dow=1, hh=10, mm=30, day_no=1)
        context = SimpleNamespace(job=SimpleNamespace(data=data,name='owned-reminder'), job_queue=queue,
                                  application=SimpleNamespace(),bot=SimpleNamespace())
        with patch('progressor_bot.notification_preflight'), patch('progressor_reminder.reserve', return_value=True), \
             patch.object(bot, 'build_workout_reminder', AsyncMock(return_value=('Workout', None))), \
             patch.object(bot, 'send_main_message', AsyncMock(return_value=SimpleNamespace(chat_id=9621,message_id=77))) as send, \
             patch.object(bot, 'remember_message'), patch.object(bot, '_rem_try_db_set_last_msg'):
            await bot._rem_fire(context)
        self.assertEqual(send.call_args.args[1], 9621)
        self.assertEqual(queue.created_jobs[0].chat_id, 9621)
        self.assertEqual(queue.created_jobs[0].data['chat_id'], 9621)

    async def test_repeated_wizard_time_does_not_fill_the_next_day(self):
        user_id = await db.get_or_create_user(9600, 'wizard-repeat')
        await db.set_workouts_per_week(user_id, 2)
        context = SimpleNamespace(user_data={'workouts_per_week': 2, 'reminder_day': 1, 'selected_dow': 0, 'tz': 'UTC'}, application=None)
        query = SimpleNamespace(message=None, answer=AsyncMock())
        with patch.object(bot, 'show_screen', new=AsyncMock()), patch.object(bot, '_schedule_user_reminders', new=AsyncMock()), patch.object(bot, '_wizard_finish_show_tips', new=AsyncMock()), patch.object(bot, 'compose_main_menu', new=AsyncMock(return_value=('', None, None))):
            await bot.wizard_router(None, query, 'wiz:remind:9:30', user_id, context)
            self.assertEqual(context.user_data['reminder_day'], 2)
            await bot.wizard_router(None, query, 'wiz:remind:9:30', user_id, context)
            self.assertEqual(await db.list_user_reminders(user_id), [(1, 0, 9, 30)])
            await bot.wizard_router(None, query, 'wiz:rday:3', user_id, context)
            await bot.wizard_router(None, query, 'wiz:remind:18:45', user_id, context)
            self.assertEqual(await db.list_user_reminders(user_id), [(1, 0, 9, 30), (2, 2, 18, 45)])

    async def test_concurrent_wizard_callbacks_do_not_skip_a_reminder_day(self):
        user_id = await db.get_or_create_user(9601, 'wizard-concurrent')
        await db.set_workouts_per_week(user_id, 3)
        context = SimpleNamespace(user_data={'workouts_per_week': 3, 'reminder_day': 1, 'selected_dow': 0, 'tz': 'UTC'}, application=None)
        query = SimpleNamespace(message=None, answer=AsyncMock())
        async def delayed_schedule(*args, **kwargs):
            await asyncio.sleep(0.05)
        with patch.object(bot, 'show_screen', new=AsyncMock()), patch.object(bot, '_schedule_user_reminders', new=AsyncMock(side_effect=delayed_schedule)), patch.object(bot, '_wizard_finish_show_tips', new=AsyncMock()), patch.object(bot, 'compose_main_menu', new=AsyncMock(return_value=('', None, None))):
            await asyncio.gather(*(bot.wizard_router(None, query, 'wiz:remind:9:30', user_id, context) for _ in range(3)))
        self.assertEqual(context.user_data['reminder_day'], 2)
        self.assertEqual(await db.list_user_reminders(user_id), [(1, 0, 9, 30)])

    async def test_old_reminder_time_cannot_write_a_different_day_or_diary(self):
        user_id = await db.get_or_create_user(9610,'reminder-scope')
        await db.set_workouts_per_week(user_id,2)
        system = await db.get_active_training_system_id(user_id)
        for owner, position, old_system in ((user_id,2,system),(user_id+1,1,system),(user_id,1,system+1)):
            state = {bot.REMINDER_EDIT_POSITION_KEY:position,bot.REMINDER_EDIT_DAY_INDEX_KEY:position,
                     'reminder_edit_owner':owner,'reminder_edit_system':old_system}
            context = SimpleNamespace(user_data=state,job_queue=None,application=None)
            user = SimpleNamespace(id=9610,username='reminder-scope')
            q = SimpleNamespace(data='remedit:time:1:1:9:30',answer=AsyncMock(),message=SimpleNamespace(chat_id=9610,message_id=1))
            update = SimpleNamespace(callback_query=q,effective_user=user)
            with patch.object(bot,'require_subscription',AsyncMock(return_value=True)),patch.object(bot,'show_reminders_overview',AsyncMock()),patch.object(bot,'_schedule_user_reminders',AsyncMock()),patch.object(bot,'add_user_reminder',AsyncMock(return_value=True)) as write:
                await bot.menu_router(update,context)
                write.assert_not_awaited()

    async def test_current_reminder_flow_still_saves_the_selected_day(self):
        user_id = await db.get_or_create_user(9611,'reminder-current')
        await db.set_workouts_per_week(user_id,2)
        context = SimpleNamespace(user_data={},job_queue=None,application=None)
        user = SimpleNamespace(id=9611,username='reminder-current')
        q = SimpleNamespace(data='remedit:day:2',answer=AsyncMock(),message=SimpleNamespace(chat_id=9611,message_id=1))
        update = SimpleNamespace(callback_query=q,effective_user=user)
        with patch.object(bot,'require_subscription',AsyncMock(return_value=True)),patch.object(bot,'show_screen',AsyncMock()),patch.object(bot,'show_reminders_overview',AsyncMock()),patch.object(bot,'_schedule_user_reminders',AsyncMock()):
            for data in ('remedit:day:2','remedit:dow:2:4','remedit:time:2:4:18:45'):
                q.data = data
                await bot.menu_router(update,context)
        self.assertEqual(await db.list_user_reminders(user_id),[(2,3,18,45)])

    async def test_normalize_dow_preserves_zero_based_values(self):
        self.assertEqual(db.normalize_dow(0), 0)
        self.assertEqual(db.normalize_dow(3), 3)
        self.assertEqual(db.normalize_dow(6), 6)

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
        job_name = f"rem_{user_id}_2_5"
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
            {"user_id": user_id, "day_no": 2, "dow": 5},
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
