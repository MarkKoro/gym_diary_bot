import asyncio,os,sqlite3,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import AsyncMock,Mock,patch
import aiosqlite
import progressor_free_workout as free
from progressor_reminder import reserve

class FreeWorkout(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'gym.db');self.now=datetime(2026,10,9,12,tzinfo=timezone.utc).timestamp()
        with sqlite3.connect(self.path) as db:
            db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,tz TEXT);CREATE TABLE sessions(id INTEGER PRIMARY KEY,user_id INTEGER,date TEXT,day_index INTEGER);CREATE TABLE sets(id INTEGER PRIMARY KEY,session_id INTEGER,user_exercise_id INTEGER,is_warmup INTEGER,reps INTEGER,seconds INTEGER);CREATE TABLE running_entries(session_id INTEGER,user_exercise_id INTEGER,is_draft INTEGER,duration_sec INTEGER,duration_ms INTEGER);CREATE TABLE session_exercises(session_id INTEGER,user_exercise_id INTEGER,is_done INTEGER,done_at TEXT,PRIMARY KEY(session_id,user_exercise_id));')
            db.execute("INSERT INTO users VALUES(7,1001,'Europe/Moscow')");db.execute("INSERT INTO sessions VALUES(20,7,'2026-10-09',0)")
            db.executemany('INSERT INTO sets VALUES(?,?,?,?,?,?)',[(1,20,3,0,10,0),(2,20,3,0,10,0),(3,20,4,1,10,0),(4,20,5,0,0,0)])
    async def asyncTearDown(self):self.tmp.cleanup()
    async def touch(self,stamp):
        async with aiosqlite.connect(self.path) as db:await free.touch(db,20,stamp);await db.commit()
    async def test_no_screen_read_finish_exact_idle_threshold_and_idempotent(self):
        self.assertEqual(free.expire(self.path,self.now+10000),[])
        await self.touch(self.now);self.assertEqual(free.expire(self.path,self.now+5399),[])
        r=free.expire(self.path,self.now+5400)[0];self.assertTrue(r['finished']);self.assertIsNone(r['duration_seconds'])
        self.assertEqual(datetime.fromisoformat(r['completed_at']).timestamp(),self.now)
        self.assertEqual(free.expire(self.path,self.now+9999),[])
        self.assertTrue(free.finish(self.path,7,20,self.now+9999)['already_finished'])
        with sqlite3.connect(self.path) as db:self.assertEqual(list(db.execute('SELECT user_exercise_id FROM session_exercises')),[(3,)])
    async def test_new_actual_write_reopens_same_session_and_resets_idle(self):
        await self.touch(self.now);free.finish(self.path,7,20,self.now+100)
        await self.touch(self.now+300);self.assertEqual(free.expire(self.path,self.now+5400),[])
        self.assertTrue(free.expire(self.path,self.now+5700)[0]['finished'])
        with sqlite3.connect(self.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM progressor_free_sessions').fetchone()[0],1)
    async def test_wrong_owner_empty_draft_and_historical_do_not_notify(self):
        with self.assertRaises(ValueError):free.finish(self.path,8,20,self.now)
        with sqlite3.connect(self.path) as db:db.execute('DELETE FROM sets');db.execute('INSERT INTO running_entries VALUES(20,6,1,600,0)')
        await self.touch(self.now);self.assertFalse(free.expire(self.path,self.now+5400)[0]['finished'])
        with sqlite3.connect(self.path) as db:db.execute('UPDATE running_entries SET is_draft=0')
        self.assertTrue(free.finish(self.path,7,20,self.now)['finished'])
    async def test_reminder_reservation_is_restart_safe_and_owner_scoped(self):
        self.assertTrue(reserve(self.path,1001,'slot'));self.assertFalse(reserve(self.path,1001,'slot'))
        self.assertTrue(reserve(self.path,1002,'slot'));self.assertTrue(reserve(self.path,1001,'next-week'))

class ReminderJourney(unittest.IsolatedAsyncioTestCase):
    async def test_failed_delivery_still_schedules_next_week_once_no_second_send(self):
        from types import SimpleNamespace
        import bot
        context=SimpleNamespace(job=SimpleNamespace(name='test',data={'chat_id':1001,'user_id':7,'tz':'UTC','dow':2,'hh':10,'mm':0}),job_queue=Mock(),application=SimpleNamespace(bot_data={}),bot=Mock())
        with patch.object(bot,'build_workout_reminder',AsyncMock(return_value=('test',None))),patch('progressor_bot.notification_preflight'),patch('progressor_reminder.reserve',return_value=True),patch.object(bot,'send_main_message',AsyncMock(side_effect=TimeoutError)) as send:
            await bot._rem_fire(context)
        self.assertEqual(send.await_count,1);self.assertEqual(context.job_queue.run_once.call_count,1)
        delay=context.job_queue.run_once.call_args.kwargs['when'];self.assertGreater(delay,0);self.assertLessEqual(delay,7*86400)
    async def test_rest_keeps_next_slot_and_does_not_touch_menu(self):
        from types import SimpleNamespace
        import bot
        from progressor_bot import NotificationDeferred
        context=SimpleNamespace(job=SimpleNamespace(name='test',data={'chat_id':1001,'user_id':7,'tz':'UTC','dow':2,'hh':10,'mm':0}),job_queue=Mock(),application=SimpleNamespace(bot_data={}),bot=Mock())
        with patch('progressor_bot.notification_preflight',side_effect=NotificationDeferred),patch.object(bot,'send_main_message',AsyncMock()) as send:await bot._rem_fire(context)
        self.assertEqual(context.job_queue.run_once.call_count,1);send.assert_not_awaited()
