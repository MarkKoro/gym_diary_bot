"""The start hint reads which kind of workout the owner actually records; it writes nothing."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import webapp_backend as api


class StartHint(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.path = str(Path(self.temp.name) / 'gym.sqlite3')
        self.patch = patch.object(db, 'DB_PATH', self.path)
        self.patch.start()
        await db.init_db()
        self.owner = await db.get_or_create_user(900000002031, 'hint-owner')
        self.other = await db.get_or_create_user(900000002032, 'hint-other')
        self.ctx = api.AuthCtx(900000002031, self.owner, 'hint-owner', None, None, int(time.time()))

    async def asyncTearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    async def session(self, user, date, day_index, sets=1):
        async with db.connect_db() as conn:
            cursor = await conn.execute('INSERT INTO sessions(user_id,date,day_index,system_id) VALUES(?,?,?,0)', (user, date, day_index))
            for number in range(sets):
                await conn.execute('INSERT INTO sets(session_id,user_exercise_id,set_no,reps,weight_kg) VALUES(?,?,?,?,?)', (cursor.lastrowid, 1, number + 1, 8, 50))
            await conn.commit()

    async def test_no_history_gives_no_preference(self):
        self.assertEqual(await api.day_start_hint(self.ctx), {'preferred': None, 'free_sessions': 0, 'plan_sessions': 0, 'sample': 0})

    async def test_mostly_free_sessions_prefer_free_and_empty_sessions_do_not_count(self):
        for day in range(1, 4):
            await self.session(self.owner, f'2026-11-0{day}', 0)
        await self.session(self.owner, '2026-11-04', 2)
        for day in range(5, 9):
            await self.session(self.owner, f'2026-11-0{day}', 1, sets=0)
        hint = await api.day_start_hint(self.ctx)
        self.assertEqual((hint['preferred'], hint['free_sessions'], hint['plan_sessions'], hint['sample']), ('free', 3, 1, 4))

    async def test_a_tie_and_plan_majority_prefer_the_plan(self):
        await self.session(self.owner, '2026-11-01', 0)
        await self.session(self.owner, '2026-11-02', 3)
        self.assertEqual((await api.day_start_hint(self.ctx))['preferred'], 'plan')

    async def test_only_the_recent_twelve_and_only_the_owner_count(self):
        for day in range(1, 11):
            await self.session(self.owner, f'2026-10-{day:02d}', 0)
        for day in range(1, 13):
            await self.session(self.owner, f'2026-11-{day:02d}', 1)
        for day in range(1, 20):
            await self.session(self.other, f'2026-11-{day:02d}', 0)
        hint = await api.day_start_hint(self.ctx)
        self.assertEqual((hint['preferred'], hint['free_sessions'], hint['plan_sessions']), ('plan', 0, 12))


if __name__ == '__main__':
    unittest.main()
