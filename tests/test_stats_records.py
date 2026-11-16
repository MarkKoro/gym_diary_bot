"""Personal records are read-only and count only working sets above all earlier ones."""
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import db
import webapp_backend as api


class Records(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.path = str(Path(self.temp.name) / 'gym.sqlite3')
        self.patch = patch.object(db, 'DB_PATH', self.path)
        self.patch.start()
        await db.init_db()
        self.owner = await db.get_or_create_user(900000002041, 'rec-owner')
        self.other = await db.get_or_create_user(900000002042, 'rec-other')
        self.ctx = api.AuthCtx(900000002041, self.owner, 'rec-owner', None, None, int(time.time()))
        async with db.connect_db() as conn:
            self.ex = [r[0] for r in await (await conn.execute('SELECT id FROM exercises ORDER BY id LIMIT 3')).fetchall()]
            self.ue = {}
            for user in (self.owner, self.other):
                for ex in self.ex:
                    cur = await conn.execute('INSERT INTO user_exercises(user_id,exercise_id,day_index,is_archived) VALUES(?,?,1,0)', (user, ex))
                    self.ue[(user, ex)] = cur.lastrowid
            await conn.commit()

    async def asyncTearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    async def lift(self, user, ex, days_ago, kg, reps=5, warmup=0):
        date = (datetime.now() - timedelta(days=days_ago)).date().isoformat()
        async with db.connect_db() as conn:
            await conn.execute('INSERT OR IGNORE INTO sessions(user_id,date,day_index,system_id) VALUES(?,?,1,0)', (user, date))
            sid = (await (await conn.execute('SELECT id FROM sessions WHERE user_id=? AND date=?', (user, date))).fetchone())[0]
            await conn.execute('INSERT INTO sets(session_id,user_exercise_id,set_no,reps,weight_kg,is_warmup) VALUES(?,?,1,?,?,?)', (sid, self.ue[(user, ex)], reps, kg, warmup))
            await conn.commit()

    async def test_only_a_working_weight_above_all_earlier_ones_is_a_record(self):
        a, b, c = self.ex
        await self.lift(self.owner, a, 60, 80); await self.lift(self.owner, a, 3, 85)      # record
        await self.lift(self.owner, b, 60, 100); await self.lift(self.owner, b, 3, 100)    # equal: no
        await self.lift(self.owner, b, 2, 140, warmup=1); await self.lift(self.owner, b, 1, 150, reps=0)
        await self.lift(self.owner, c, 3, 50)                                               # first ever: no
        await self.lift(self.other, c, 60, 10); await self.lift(self.other, c, 3, 90)      # another owner
        result = await api.stats_records(self.ctx)
        self.assertEqual([(r['weight_kg'], r['previous_kg']) for r in result['records']], [(85.0, 80.0)])

    async def test_empty_history_has_no_records(self):
        self.assertEqual((await api.stats_records(self.ctx))['records'], [])


if __name__ == '__main__':
    unittest.main()
