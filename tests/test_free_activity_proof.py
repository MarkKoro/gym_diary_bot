"""Native SQLite witness/rollback tests; no Core, provider or delivery calls."""
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import db
import progressor_free_workout as free


NOW = datetime(2026, 10, 23, 23, 50, 0, 125000, tzinfo=timezone.utc).timestamp()
DAY = '2026-10-23'
PROOF = 'progressor_free_activity_proof'


class SourceWitness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'))
        self.path = str(Path(self.temp.name) / 'native.sqlite3')
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript('''
                CREATE TABLE users(id INTEGER PRIMARY KEY,tg_id INTEGER,tz TEXT);
                CREATE TABLE sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,date TEXT,day_index INTEGER,system_id INTEGER DEFAULT 0,
                    UNIQUE(user_id,date,day_index));
                CREATE TABLE sets(id INTEGER PRIMARY KEY,session_id INTEGER,
                    user_exercise_id INTEGER,is_warmup INTEGER,reps INTEGER,seconds INTEGER);
                CREATE TABLE running_entries(session_id INTEGER,user_exercise_id INTEGER,
                    is_draft INTEGER,duration_sec INTEGER,duration_ms INTEGER);
                CREATE TABLE session_exercises(session_id INTEGER,user_exercise_id INTEGER,
                    is_done INTEGER,done_at TEXT,PRIMARY KEY(session_id,user_exercise_id));
                CREATE TABLE subscriptions(user_id INTEGER,paid_until TEXT);
                INSERT INTO users VALUES(7,900000003001,'UTC');
                INSERT INTO users VALUES(8,900000003002,'UTC');
                INSERT INTO sessions VALUES(20,7,'2026-10-23',0,0);
                INSERT INTO sessions VALUES(21,7,'2026-10-22',0,0);
                INSERT INTO sessions VALUES(22,7,'2026-10-23',1,0);
                INSERT INTO sessions VALUES(23,8,'2026-10-23',0,0);
                INSERT INTO sets VALUES(1,20,3,0,10,0);
                INSERT INTO sets VALUES(2,21,3,0,10,0);
                INSERT INTO sets VALUES(3,22,3,0,10,0);
                INSERT INTO sets VALUES(4,23,3,0,10,0);
                INSERT INTO subscriptions VALUES(7,'2030-01-01');
                INSERT INTO subscriptions VALUES(8,'2030-02-01');
            ''')
        async with aiosqlite.connect(self.path) as conn:
            await free.ensure_schema(conn)
            await conn.commit()

    async def asyncTearDown(self):
        self.temp.cleanup()

    def rows(self, table):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()

    async def touch(self, stamp=NOW, session=20):
        async with aiosqlite.connect(self.path) as conn:
            await free.touch(conn, session, stamp)
            await conn.commit()

    def write(self, sql, args=()):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(sql, args)

    async def test_schema_keeps_six_columns_and_migration_backfills_no_witness(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual([r[1] for r in conn.execute('PRAGMA table_info(progressor_free_sessions)')],
                ['session_id', 'last_activity', 'status', 'completed_at', 'completion_basis', 'last_finished_at'])
            conn.execute("INSERT INTO progressor_free_sessions VALUES(20,?,'active',NULL,NULL,NULL)", (NOW,))
        async with aiosqlite.connect(self.path) as conn:
            await free.ensure_schema(conn)
            await free.ensure_schema(conn)
            await conn.commit()
        self.assertEqual(self.rows(PROOF), [])
        self.assertEqual(self.rows('progressor_free_sessions')[0][1], NOW)

    async def test_touch_stores_exact_source_clock_day_zone_and_kind_without_changing_paid_or_sets(self):
        before = {name: self.rows(name) for name in ('sets', 'sessions', 'subscriptions')}
        await self.touch()
        self.assertEqual(self.rows(PROOF), [(20, NOW, DAY, 'UTC', 1, 'native_touch')])
        self.assertEqual(self.rows('progressor_free_sessions'), [(20, NOW, 'active', None, None, None)])
        self.assertEqual(before, {name: self.rows(name) for name in before})

    async def test_old_equal_clock_update_clears_witness_even_when_scalar_unchanged(self):
        await self.touch()
        self.write("INSERT INTO progressor_free_sessions VALUES(?,?,'active',NULL,NULL,NULL) ON CONFLICT(session_id) DO UPDATE SET last_activity=excluded.last_activity,status='active',completed_at=NULL,completion_basis=NULL", (20, NOW))
        self.assertEqual(self.rows(PROOF), [])
        self.assertEqual(self.rows('progressor_free_sessions')[0][1], NOW)

    async def test_same_clock_new_touch_reinstalls_validated_zone_and_rollback_restores_old_pair(self):
        stamp = NOW - 12 * 3600
        await self.touch(stamp)
        self.write("UPDATE users SET tz='Europe/Moscow' WHERE id=7")
        await self.touch(stamp)
        self.assertEqual(self.rows(PROOF), [(20, stamp, DAY, 'Europe/Moscow', 1, 'native_touch')])
        state, proof = self.rows('progressor_free_sessions'), self.rows(PROOF)
        async with aiosqlite.connect(self.path) as conn:
            await conn.execute('BEGIN IMMEDIATE')
            await free.touch(conn, 20, stamp + 1)
            await conn.rollback()
        self.assertEqual(self.rows('progressor_free_sessions'), state)
        self.assertEqual(self.rows(PROOF), proof)

    async def test_failure_between_state_and_proof_rolls_back_prior_state_and_working_set(self):
        await self.touch()
        before = {name: self.rows(name) for name in ('sets', 'progressor_free_sessions', PROOF)}
        self.write("CREATE TRIGGER reject_new_proof BEFORE INSERT ON progressor_free_activity_proof BEGIN SELECT RAISE(ABORT,'synthetic proof failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'synthetic proof failure'):
            async with aiosqlite.connect(self.path) as conn:
                await conn.execute('BEGIN IMMEDIATE')
                await conn.execute('INSERT INTO sets VALUES(5,20,3,0,11,0)')
                await free.touch(conn, 20, NOW + 1)
                await conn.commit()
        self.assertEqual(before, {name: self.rows(name) for name in before})

    async def test_explicit_finish_after_travel_preserves_witness_and_activity_utc(self):
        await self.touch()
        proof, paid, sets = self.rows(PROOF), self.rows('subscriptions'), self.rows('sets')
        self.write("UPDATE users SET tz='Asia/Bangkok' WHERE id=7")
        result = free.finish(self.path, 7, 20, NOW + 600)
        self.assertTrue(result['finished'])
        self.assertEqual(result['completed_at'], datetime.fromtimestamp(NOW, timezone.utc).isoformat())
        self.assertEqual(self.rows(PROOF), proof)
        self.assertEqual(self.rows('progressor_free_sessions')[0][-1], NOW + 600)
        self.assertEqual(self.rows('subscriptions'), paid)
        self.assertEqual(self.rows('sets'), sets)
        self.assertTrue(free.finish(self.path, 7, 20, NOW + 700)['already_finished'])
        self.assertEqual(self.rows(PROOF), proof)

    async def test_idle_finish_after_travel_keeps_5399_5400_boundary_and_unknown_duration(self):
        await self.touch()
        proof = self.rows(PROOF)
        self.write("UPDATE users SET tz='Asia/Bangkok' WHERE id=7")
        self.assertEqual(free.expire(self.path, NOW + 5399), [])
        result = free.expire(self.path, NOW + 5400)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['completion_basis'], 'inactivity_90_minutes')
        self.assertIsNone(result[0]['duration_seconds'])
        self.assertEqual(datetime.fromisoformat(result[0]['completed_at']).timestamp(), NOW)
        self.assertEqual(self.rows(PROOF), proof)
        self.assertEqual(free.expire(self.path, NOW + 9999), [])

    async def test_no_state_explicit_finish_today_and_yesterday_never_fabricates_touch_witness(self):
        for session in (20, 21):
            result = free.finish(self.path, 7, session, NOW)
            self.assertTrue(result['finished'])
            self.assertEqual(datetime.fromisoformat(result['completed_at']).timestamp(), NOW)
        self.assertEqual(self.rows(PROOF), [])

    async def test_historical_touch_and_reads_do_not_replace_old_witness_or_start_state(self):
        await self.touch()
        before = {name: self.rows(name) for name in ('progressor_free_sessions', PROOF)}
        self.write("UPDATE users SET tz='Asia/Bangkok' WHERE id=7")
        await self.touch(NOW + 1)
        await self.touch(NOW + 1, 21)
        free.current(self.path, 900000003001)
        self.assertEqual(before, {name: self.rows(name) for name in before})

    async def test_programmed_invalid_zone_and_absent_session_have_no_witness(self):
        await self.touch(NOW, 22)
        await self.touch(NOW, 9999)
        self.write("UPDATE users SET tz='Not/A_Zone' WHERE id=7")
        await self.touch()
        self.assertEqual(self.rows('progressor_free_sessions'), [])
        self.assertEqual(self.rows(PROOF), [])

    async def test_state_insert_replace_delete_and_session_delete_cleanup_without_foreign_keys(self):
        await self.touch()
        self.write("INSERT OR REPLACE INTO progressor_free_sessions VALUES(20,?,'active',NULL,NULL,NULL)", (NOW,))
        self.assertEqual(self.rows(PROOF), [])
        await self.touch()
        self.write('DELETE FROM progressor_free_sessions WHERE session_id=20')
        self.assertEqual(self.rows(PROOF), [])
        await self.touch()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute('PRAGMA foreign_keys').fetchone()[0], 0)
            conn.execute('DELETE FROM sessions WHERE id=20')
        self.assertEqual(self.rows(PROOF), [])

    async def test_legacy_sessions_rebuild_preserves_history_pair_and_reinstalls_delete_trigger(self):
        await self.touch()
        before = {name: self.rows(name) for name in ('users', 'sessions', 'sets', 'subscriptions', 'progressor_free_sessions', PROOF)}
        async with aiosqlite.connect(self.path) as conn:
            await db._ensure_sessions_unique_by_day_and_system(conn)
            await conn.commit()
        self.assertEqual(before, {name: self.rows(name) for name in before})
        self.write('DELETE FROM sessions WHERE id=20')
        self.assertEqual(self.rows(PROOF), [])


    async def test_fixed_offset_touch_uses_native_zone_and_exact_local_day(self):
        from progressor_timezone_history import zone
        for name in ('UTC+14:00', 'UTC-03:30'):
            with self.subTest(timezone=name):
                day = datetime.fromtimestamp(NOW, zone(name)).date().isoformat()
                self.write('UPDATE users SET tz=? WHERE id=7', (name,))
                self.write('UPDATE sessions SET date=? WHERE id=20', (day,))
                before = {table:self.rows(table) for table in ('sets','sessions','subscriptions')}
                prior = self.rows('progressor_free_sessions')
                last_finished = prior[0][-1] if prior else None
                await self.touch()
                self.assertEqual(self.rows(PROOF), [(20,NOW,day,name,1,'native_touch')])
                self.assertEqual(self.rows('progressor_free_sessions'), [(20,NOW,'active',None,None,last_finished)])
                self.assertEqual(before, {table:self.rows(table) for table in before})
                result = free.finish(self.path,7,20,NOW+600)
                self.assertEqual(result['completed_at'],datetime.fromtimestamp(NOW,timezone.utc).isoformat())
                self.assertEqual(self.rows(PROOF), [(20,NOW,day,name,1,'native_touch')])

    async def test_fixed_offset_current_read_uses_same_day_and_changes_no_native_rows(self):
        from progressor_timezone_history import zone
        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                value = datetime.fromtimestamp(NOW,timezone.utc)
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)
        for name in ('UTC+14:00','UTC-03:30'):
            with self.subTest(timezone=name):
                day=datetime.fromtimestamp(NOW,zone(name)).date().isoformat()
                self.write('UPDATE users SET tz=? WHERE id=7',(name,))
                self.write('UPDATE sessions SET date=? WHERE id=20',(day,))
                await self.touch()
                before={table:self.rows(table) for table in ('sets','sessions','subscriptions','progressor_free_sessions',PROOF)}
                with patch.object(free,'datetime',Frozen):
                    self.assertEqual(free.current(self.path,900000003001),{'id':20,'user_id':7})
                self.assertEqual(before,{table:self.rows(table) for table in before})

    async def test_invalid_offset_alias_touch_does_not_create_or_replace_activity(self):
        await self.touch()
        for name in ('UTC+14:01','UTC-14:01','GMT+03:00','+03:00','Not/A_Zone'):
            with self.subTest(timezone=name):
                self.write('UPDATE users SET tz=? WHERE id=7',(name,))
                before={table:self.rows(table) for table in ('sets','sessions','subscriptions','progressor_free_sessions',PROOF)}
                await self.touch(NOW+1)
                self.assertEqual(before,{table:self.rows(table) for table in before})


class NativeProofWriters(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import webapp_backend as api
        self.api = api
        self.temp = tempfile.TemporaryDirectory(dir=os.getenv('PROGRESSOR_TEST_TMP_DIR'))
        self.path = str(Path(self.temp.name) / 'gym.sqlite3')
        self.path_patch = patch.object(db, 'DB_PATH', self.path)
        self.path_patch.start()
        await db.init_db()
        self.owner = await db.get_or_create_user(900000003011, 'proof-owner')
        self.other = await db.get_or_create_user(900000003012, 'proof-other')
        await db.ensure_training_system_defaults(self.owner)
        await db.set_workouts_per_week(self.owner, 1)
        self.exercise = await db.get_or_create_exercise('Proof squat', 'legs', self.owner)
        await db.add_user_exercise(self.owner, 1, self.exercise)
        async with db.connect_db() as conn:
            self.ue = (await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=? AND day_index=1', (self.owner, self.exercise))).fetchone())[0]
        self.ctx = api.AuthCtx(900000003011, self.owner, 'proof-owner', None, None, int(time.time()))
        self.clock_patch = patch('progressor_free_workout.time.time', return_value=NOW)
        self.clock_patch.start()

    async def asyncTearDown(self):
        self.clock_patch.stop()
        self.path_patch.stop()
        self.temp.cleanup()

    async def rows(self, table):
        async with db.connect_db() as conn:
            return await (await conn.execute('SELECT * FROM ' + table + ' ORDER BY 1')).fetchall()

    async def add_free(self, key='a' * 32):
        return await self.api.all_exercise_add_set(self.exercise,
            payload={'operation_id': key, 'reps': 10, 'seconds': 0, 'weight_kg': 30}, date=DAY, ctx=self.ctx)

    async def test_actual_both_exercise_surfaces_keep_distinct_sessions_and_only_free_gets_witness(self):
        programmed = await self.api.add_set_fast(1, self.ue,
            payload={'operation_id': 'b' * 32, 'reps': 10, 'seconds': 0, 'weight_kg': 30}, date=DAY, ctx=self.ctx)
        self.assertEqual(await self.rows(PROOF), [])
        result = await self.add_free()
        session = result['operation']['session_id']
        self.assertNotEqual(programmed['operation']['session_id'], session)
        self.assertEqual(await self.rows(PROOF), [(session, NOW, DAY, 'UTC', 1, 'native_touch')])
        self.assertEqual(len(await self.rows('sets')), 2)
        self.assertEqual(len(await self.rows('set_add_operations')), 2)

    async def test_actual_add_once_replay_preserves_finished_witness_after_timezone_cas(self):
        import progressor_timezone
        first = await self.add_free()
        session = first['operation']['session_id']
        proof = await self.rows(PROOF)
        free.finish(self.path, self.owner, session, NOW + 10)
        await progressor_timezone.change(self.owner, 900000003011,
            {'timezone': 'Asia/Bangkok', 'action': 'apply', 'expected_timezone': 'UTC'})
        state = await self.rows('progressor_free_sessions')
        replay = await self.add_free()
        self.assertTrue(replay['operation']['replayed'])
        self.assertEqual(await self.rows(PROOF), proof)
        self.assertEqual(await self.rows('progressor_free_sessions'), state)
        self.assertEqual(len(await self.rows('sets')), 1)
        self.assertEqual(len(await self.rows('set_add_operations')), 1)

    async def test_actual_add_once_proof_failure_rolls_back_set_receipt_and_state(self):
        async with db.connect_db() as conn:
            await conn.execute("CREATE TRIGGER reject_native_proof BEFORE INSERT ON progressor_free_activity_proof BEGIN SELECT RAISE(ABORT,'native proof fault'); END")
            await conn.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'native proof fault'):
            await self.add_free()
        for table in ('sets', 'set_add_operations', 'progressor_free_sessions', PROOF):
            self.assertEqual(await self.rows(table), [])

    async def test_actual_running_draft_has_no_proof_and_done_then_actual_edit_has_atomic_witness(self):
        running = await db.get_or_create_exercise('Proof running', 'run', self.owner)
        result = await self.api.all_exercise_running_save(running,
            payload={'distance_km': 1, 'duration_ms': 120000}, date=DAY, ctx=self.ctx)
        self.assertEqual(await self.rows(PROOF), [])
        entry = result['running']['entry_id']
        await self.api.all_exercise_running_done(running,
            payload={'distance_km': 1, 'duration_ms': 120000}, date=DAY, ctx=self.ctx)
        first = await self.rows(PROOF)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0][1:], (NOW, DAY, 'UTC', 1, 'native_touch'))
        with patch('progressor_free_workout.time.time', return_value=NOW + 1):
            await db.update_running_entry(entry, duration_ms=130000)
        self.assertEqual((await self.rows(PROOF))[0][1:], (NOW + 1, DAY, 'UTC', 1, 'native_touch'))
        self.assertEqual(len(await self.rows('running_entries')), 1)

    async def test_actual_explicit_finish_endpoint_retains_proof_and_acting_permission(self):
        result = await self.add_free()
        session = result['operation']['session_id']
        before = await self.rows(PROOF)
        acting = self.api.AuthCtx(900000003012, self.owner, 'trainer', None, None,
            int(NOW), actor_user_id=self.other, acting_can_edit=True, is_acting=True)
        with self.assertRaises(self.api.HTTPException) as caught:
            await self.api.free_workout_finish({'session_id': session}, ctx=acting)
        self.assertEqual(caught.exception.status_code, 403)
        finished = await self.api.free_workout_finish({'session_id': session}, ctx=self.ctx)
        self.assertTrue(finished['finished'])
        self.assertEqual(datetime.fromisoformat(finished['completed_at']).timestamp(), NOW)
        self.assertEqual(await self.rows(PROOF), before)

    async def test_owner_wipe_explicit_cleanup_is_scoped_even_without_session_trigger(self):
        first = await self.add_free()
        other_session = await db.get_or_create_today_session(self.other, DAY, 0, 0)
        async with db.connect_db() as conn:
            await free.touch(conn, other_session, NOW)
            await conn.execute('DROP TRIGGER progressor_free_proof_session_delete_v1')
            await conn.commit()
        other_proof = [r for r in await self.rows(PROOF) if r[0] == other_session]
        self.assertEqual(len(other_proof), 1)
        await db.wipe_user(self.owner)
        self.assertEqual(await self.rows(PROOF), other_proof)
        self.assertEqual(await self.rows('sets'), [])
        self.assertEqual(await self.rows('set_add_operations'), [])
        self.assertNotEqual(first['operation']['session_id'], other_session)


    async def test_native_fixed_offset_setter_and_api_touch_keep_operation_replay(self):
        from progressor_timezone_history import zone
        for index,(name,key) in enumerate((('UTC+14:00','c'*32),('UTC-03:30','d'*32))):
            with self.subTest(timezone=name):
                stamp=NOW+index*20
                with patch('progressor_timezone_history.time.time',return_value=stamp-1):
                    await db.set_user_timezone(self.owner,name)
                day=datetime.fromtimestamp(stamp,zone(name)).date().isoformat()
                body={'operation_id':key,'reps':10,'seconds':0,'weight_kg':30}
                with patch('progressor_free_workout.time.time',return_value=stamp):
                    first=await self.api.all_exercise_add_set(self.exercise,payload=body,date=day,ctx=self.ctx)
                    session=first['operation']['session_id']
                    expected=(session,stamp,day,name,1,'native_touch')
                    self.assertIn(expected,await self.rows(PROOF))
                    before={table:await self.rows(table) for table in ('sets','set_add_operations','progressor_free_sessions',PROOF)}
                    replay=await self.api.all_exercise_add_set(self.exercise,payload=body,date=day,ctx=self.ctx)
                    self.assertTrue(replay['operation']['replayed'])
                    self.assertEqual(before,{table:await self.rows(table) for table in before})


if __name__ == '__main__':
    unittest.main()
