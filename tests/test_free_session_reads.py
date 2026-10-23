"""Native free-card GET must not create a workout session or running draft.

The existing numeric owner exercise alias/bootstrap contract is kept separate.
Explicit set/run writers still create their parent session and existing receipts.
"""
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import db
import webapp_backend as api


class FreeSessionReads(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.path = str(Path(self.temp.name) / 'gym.sqlite3')
        self.patch = patch.object(db, 'DB_PATH', self.path)
        self.patch.start()
        await db.init_db()
        self.owner = await db.get_or_create_user(900000002027, 'free-reader')
        await db.ensure_training_system_defaults(self.owner)
        self.ctx = api.AuthCtx(900000002027, self.owner, 'free-reader', None, None, int(time.time()))
        self.day = datetime.now(timezone.utc).date().isoformat()
        self.next_day = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        self.strength = await db.get_or_create_exercise('Read-boundary squat', 'legs', self.owner)
        self.running = await db.get_or_create_exercise('Read-boundary running', 'run', self.owner)
        api.app.dependency_overrides[api.get_auth_ctx] = lambda: self.ctx
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://synthetic')

    async def asyncTearDown(self):
        await self.client.aclose()
        api.app.dependency_overrides.pop(api.get_auth_ctx, None)
        self.patch.stop()
        self.temp.cleanup()

    async def activity(self):
        # Alias identity is deliberately not included in this workout boundary.
        async with db.connect_db() as conn:
            tables = {row[0] for row in await (await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
            return {table: await (await conn.execute('SELECT * FROM ' + table)).fetchall()
                    for table in ('sessions', 'sets', 'running_entries', 'session_exercises',
                                  'day_completions', 'day_completion_history', 'set_add_operations',
                                  'progressor_free_sessions') if table in tables}

    async def read(self, exercise, day=None):
        response = await self.client.get(f'/all_exercises/exercise/{exercise}/session', params={'date': day or self.day})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_fresh_strength_and_running_cards_two_dates_create_no_workout_parents(self):
        before = await self.activity()
        for exercise in (self.strength, self.running):
            alias = None
            for day in (self.day, self.next_day, self.day):
                body = await self.read(exercise, day)
                self.assertEqual(body['session_id'], 0)
                self.assertIsInstance(body['user_exercise_id'], int)
                self.assertGreater(body['user_exercise_id'], 0)
                alias = alias or body['user_exercise_id']
                self.assertEqual(alias, body['user_exercise_id'])
                self.assertFalse(body['is_done'])
                self.assertEqual(body['sets'], [])
                if exercise == self.running:
                    self.assertIsNone(body['running']['entry_id'])
                self.assertEqual(await self.activity(), before)
        self.assertEqual(await db.recorded_training_summary(self.owner), (0, None, None))
        self.assertEqual(await db.count_all_exercises_unfinished(self.owner, self.day), 0)

    async def test_first_explicit_set_then_same_intent_retry_creates_one_session_receipt_and_set(self):
        empty = await self.read(self.strength)
        self.assertEqual(empty['session_id'], 0)
        payload = dict(operation_id='a' * 32, reps=10, seconds=0, weight_kg=30, is_warmup=False)
        url = f'/all_exercises/exercise/{self.strength}/set/add_once'
        first = await self.client.post(url, params={'date': self.day}, json=payload)
        second = await self.client.post(url, params={'date': self.day}, json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()['operation']['replayed'])
        self.assertEqual(first.json()['user_exercise_id'], empty['user_exercise_id'])
        before = await self.activity()
        self.assertEqual(len(before['sessions']), 1)
        self.assertEqual(len(before['sets']), 1)
        self.assertEqual(len(before['set_add_operations']), 1)
        current = await self.read(self.strength)
        self.assertEqual(current['session_id'], first.json()['operation']['session_id'])
        self.assertEqual(len(current['sets']), 1)
        future = await self.read(self.strength, self.next_day)
        self.assertEqual(future['session_id'], 0)
        self.assertEqual(future['sets'], [])
        self.assertTrue(future['previous_sets'])
        self.assertEqual(await self.activity(), before)

    async def test_first_running_input_creates_one_draft_and_later_get_does_not_create_another(self):
        empty = await self.read(self.running)
        self.assertIsNone(empty['running']['entry_id'])
        response = await self.client.post(f'/all_exercises/exercise/{self.running}/running', params={'date': self.day},
                                          json={'distance_km': 1, 'duration_ms': 120000})
        self.assertEqual(response.status_code, 200, response.text)
        before = await self.activity()
        self.assertEqual(len(before['sessions']), 1)
        self.assertEqual(len(before['running_entries']), 1)
        body = await self.read(self.running)
        self.assertEqual(body['running']['entry_id'], response.json()['running']['entry_id'])
        future = await self.read(self.running, self.next_day)
        self.assertEqual(future['session_id'], 0)
        self.assertIsNone(future['running']['entry_id'])
        self.assertEqual(await self.activity(), before)

    async def test_explicit_persistent_note_does_not_need_a_workout_parent(self):
        before = await self.activity()
        response = await self.client.put(f'/all_exercises/exercise/{self.strength}/note', json={'note':'Plan for later'})
        self.assertEqual(response.status_code, 200, response.text)
        body = await self.read(self.strength)
        self.assertEqual(body['current_note'], 'Plan for later')
        self.assertEqual(body['session_id'], 0)
        self.assertEqual(body['sets'], [])
        self.assertEqual(await self.activity(), before)

    async def test_invalid_and_acting_reads_cannot_create_a_free_session(self):
        before = await self.activity()
        response = await self.client.get('/all_exercises/exercise/999999999/session')
        self.assertEqual(response.status_code, 404)
        self.ctx = api.AuthCtx(900000002028, self.owner, 'trainer', None, None, int(time.time()),
                              actor_user_id=987654, acting_can_edit=True, is_acting=True)
        response = await self.client.get(f'/all_exercises/exercise/{self.strength}/session')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(await self.activity(), before)


if __name__ == '__main__':
    unittest.main()
