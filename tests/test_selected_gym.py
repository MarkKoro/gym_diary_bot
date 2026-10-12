import os,tempfile,unittest,sqlite3
from pathlib import Path
from unittest.mock import patch
import db
from progressor_timezone import change
from progressor_timezone_history import at,preview

class SelectedGym(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'gym.db')
        with sqlite3.connect(self.path) as conn:
            conn.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,tz TEXT);INSERT INTO users VALUES(7,123,'UTC');CREATE TABLE user_reminders(user_id INTEGER,dow INTEGER,hour INTEGER,minute INTEGER);INSERT INTO user_reminders VALUES(7,1,10,0);CREATE TABLE app_meta(key TEXT PRIMARY KEY,value TEXT);")
        self.mock=patch.object(db,'DB_PATH',self.path);self.mock.start()
    async def asyncTearDown(self):self.mock.stop();self.tmp.cleanup()
    async def test_preview_apply_history_cas_and_no_reminder_rewrite(self):
        before=await change(7,123,{'action':'preview','timezone':'Asia/Bangkok'});self.assertFalse(before['applied']);self.assertIn('Вт 10:00',before['slots'])
        with sqlite3.connect(self.path) as conn:self.assertEqual(conn.execute('SELECT tz FROM users').fetchone()[0],'UTC')
        await change(7,123,{'action':'apply','timezone':'Asia/Bangkok','expected_timezone':'UTC'})
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(at(conn,123,'2026-01-01T23:30:00Z','Asia/Bangkok'),'UTC')
            self.assertEqual(conn.execute('SELECT hour,minute FROM user_reminders').fetchone(),(10,0))
            self.assertEqual(conn.execute('SELECT tz FROM users').fetchone()[0],'Asia/Bangkok')
        with self.assertRaises(ValueError):await change(7,123,{'action':'apply','timezone':'Europe/Moscow','expected_timezone':'UTC'})
        with self.assertRaises(ValueError):await change(7,456,{'action':'apply','timezone':'UTC','expected_timezone':'Asia/Bangkok'})
    async def test_acting_user_cannot_change_other_timezone(self):
        import webapp_backend as web
        from fastapi import HTTPException
        from types import SimpleNamespace
        with self.assertRaises(HTTPException) as error:await web.integration_timezone({'action':'preview','timezone':'UTC'},SimpleNamespace(is_acting=True))
        self.assertEqual(error.exception.status_code,403)
    async def test_invalid_timezone_and_date_crossing_preview(self):
        from datetime import datetime,timezone
        value=preview('UTC','Asia/Bangkok',now=datetime(2026,10,9,23,30,tzinfo=timezone.utc))
        self.assertTrue(value['clock_after'].startswith('2026-10-10'))
        for value in ('bad','UTC+14:30','UTC+09:99'):
            with self.assertRaises(ValueError):await change(7,123,{'action':'preview','timezone':value})
