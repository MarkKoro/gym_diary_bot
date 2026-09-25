import atexit
import asyncio
import sqlite3
from contextlib import closing
from unittest.mock import patch
import os
import tempfile
import importlib
import unittest


tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db.close()
atexit.register(lambda: os.path.exists(tmp_db.name) and os.remove(tmp_db.name))

os.environ["DB_PATH"] = tmp_db.name

import settings  # noqa: E402
importlib.reload(settings)
import db  # noqa: E402
importlib.reload(db)
from text_utils import normalize_whitespace  # noqa: E402


class DbSeedingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()

    async def test_kettlebell_seed_is_idempotent(self):
        await db.init_db()
        async with db.connect_db() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM exercises WHERE name=?",
                ("Махи гирей (русские)",),
            )
            count = (await cur.fetchone())[0]
        self.assertEqual(count, 1)

    async def test_normalized_name_reuses_existing_entry(self):
        base_name = normalize_whitespace("  Своя   гиря  ")
        first_id = await db.get_or_create_exercise(base_name, "kb")
        second_id = await db.get_or_create_exercise(
            normalize_whitespace("Своя гиря"), "kb"
        )
        self.assertEqual(first_id, second_id)



class DatabaseIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        pool = patch.object(db, "_db_semaphore", asyncio.BoundedSemaphore(5))
        pool.start()
        self.addCleanup(pool.stop)
        await db.init_db()
        self.uid = await db.get_or_create_user(98100, 'integrity')
        self.ex = await db.get_or_create_exercise('Integrity exercise', 'chest', self.uid)
        await db.add_user_exercise(self.uid, 1, self.ex)
        async with db.connect_db() as conn:
            self.ue = (await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=?', (self.uid, self.ex))).fetchone())[0]
            await conn.execute('DELETE FROM sets')
            await conn.execute('DELETE FROM session_exercises')
            await conn.execute('DELETE FROM sessions')
            await conn.commit()

    async def test_concurrent_sessions_and_sets_keep_one_session_and_unique_numbers(self):
        sessions = await asyncio.gather(*(db.get_or_create_today_session(self.uid, '2026-01-01', 1, 0) for _ in range(20)))
        self.assertEqual(len(set(sessions)), 1)
        await asyncio.gather(*(db.add_set(sessions[0], self.ue, 10, weight=20) for _ in range(20)))
        async with db.connect_db() as conn:
            rows = await (await conn.execute('SELECT set_no FROM sets ORDER BY set_no')).fetchall()
        self.assertEqual(rows, [(i,) for i in range(1, 21)])

    async def test_increment_changes_only_last_set_and_serializes_updates(self):
        session = await db.get_or_create_today_session(self.uid, '2026-01-01', 1, 0)
        await db.add_set(session, self.ue, 10, weight=20)
        await db.add_set(session, self.ue, 12, weight=30)
        await asyncio.gather(*(db.inc_last_set(self.ue, session, 'reps', 1) for _ in range(20)))
        async with db.connect_db() as conn:
            rows = await (await conn.execute('SELECT reps,weight_kg FROM sets ORDER BY set_no')).fetchall()
        self.assertEqual(rows, [(10, 20), (32, 30)])

    async def test_empty_increment_works_with_single_connection(self):
        session = await db.get_or_create_today_session(self.uid, '2026-01-01', 1, 0)
        with patch.object(db, '_db_semaphore', asyncio.Semaphore(1)):
            await asyncio.wait_for(db.inc_last_set(self.ue, session, 'weight_kg', 2.5), 5)
        for value in (float('nan'), float('inf'), -1):
            with self.assertRaises(ValueError):
                await db.add_set(session, self.ue, weight=value)
        async with db.connect_db() as conn:
            rows = await (await conn.execute('SELECT weight_kg FROM sets')).fetchall()
        self.assertEqual(rows, [(2.5,)])

    async def test_legacy_migration_preserves_data_foreign_keys_indexes_and_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'legacy.db')
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript("""
                    CREATE TABLE exercises(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, muscle_group TEXT);
                    INSERT INTO exercises VALUES(7001,'Legacy exercise','chest');
                    CREATE TABLE user_exercises(id INTEGER PRIMARY KEY, user_id INTEGER, exercise_id INTEGER, day_index INTEGER, UNIQUE(user_id,exercise_id,day_index));
                    INSERT INTO user_exercises VALUES(7002,7,7001,1);
                    CREATE TABLE sessions(id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, day_index INTEGER, UNIQUE(user_id,date));
                    INSERT INTO sessions VALUES(7003,7,'2020-01-01',1);
                    CREATE TABLE sets(id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES sessions(id), user_exercise_id INTEGER, set_no INTEGER, reps INTEGER, weight_kg REAL);
                    INSERT INTO sets VALUES(7004,7003,7002,1,8,60);
                    CREATE TABLE exercise_muscles(exercise_id INTEGER REFERENCES exercises(id), muscle_code TEXT, weight_pct REAL, PRIMARY KEY(exercise_id,muscle_code));
                    INSERT INTO exercise_muscles VALUES(7001,'chest',1);
                """)
            with patch.object(db, 'DB_PATH', path):
                await db.init_db()
                await db.init_db()
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(conn.execute('SELECT reps,weight_kg,seconds,is_warmup FROM sets WHERE id=7004').fetchone(), (8,60,0,0))
                self.assertEqual(conn.execute('SELECT name,created_by_user_id FROM exercises WHERE id=7001').fetchone(), ('Legacy exercise',0))
                indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
                self.assertTrue({'idx_sessions_user_date_day','idx_exercises_owner_group_name','idx_sets_session_user_warmup_setno'} <= indexes)
                with closing(sqlite3.connect(':memory:')) as restored:
                    conn.backup(restored)
                    self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                    self.assertEqual(restored.execute('SELECT * FROM sets').fetchall(), conn.execute('SELECT * FROM sets').fetchall())


class SettingsValidationTests(unittest.TestCase):
    def test_invalid_pool_configuration_uses_safe_defaults(self):
        try:
            for values in ({'DB_POOL_SIZE':'0','TG_POOL_SIZE':'-1','TRIAL_DAYS':'oops'}, {'DB_POOL_SIZE':'100000','TG_POOL_SIZE':'nan','TRIAL_DAYS':'-3'}):
                with patch.dict(os.environ, values):
                    importlib.reload(settings)
                    self.assertEqual((settings.DB_POOL_SIZE,settings.TG_POOL_SIZE,settings.TRIAL_DAYS), (5,10,0))
            with patch.dict(os.environ, {'DB_POOL_SIZE':'1','TG_POOL_SIZE':'20','TRIAL_DAYS':'7'}):
                importlib.reload(settings)
                self.assertEqual((settings.DB_POOL_SIZE,settings.TG_POOL_SIZE,settings.TRIAL_DAYS), (1,20,7))
        finally:
            importlib.reload(settings)


if __name__ == "__main__":
    unittest.main()
