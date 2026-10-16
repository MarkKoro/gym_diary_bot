"""Real SQLite regressions for viewing, expiry and explicit plan replacement."""
import os
import json
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.requests import Request
import db
import webapp_backend as api


class QualityDiaryReads(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('PROGRESSOR_TEST_TMP_DIR'))
        self.db_patch = patch.object(db, 'DB_PATH', str(Path(self.temp.name) / 'gym.db'))
        self.db_patch.start()
        await db.init_db()
        self.owner = await db.get_or_create_user(900000000011, 'pupil')
        self.viewer = await db.get_or_create_user(900000000012, 'trainer')
        self.a = await db.ensure_training_system_defaults(self.owner)
        self.b = await db.create_training_system(self.owner, 'Saved second', workouts_per_week=2)
        self.c = await db.create_training_system(self.owner, 'Saved third', workouts_per_week=4)
        await db.set_workouts_per_week(self.owner, 3)
        await db.add_user_reminder(self.owner, dow=1, hour=10, minute=0, day_no=1)
        self.exercise_links = []
        for name, group in (('Quality strength', 'legs'), ('Quality run', 'run')):
            async with db.connect_db() as conn:
                row = await (await conn.execute(
                    'INSERT INTO exercises(name,muscle_group,created_by_user_id) VALUES(?,?,?) RETURNING id',
                    (name, group, self.owner),
                )).fetchone()
                await conn.commit()
            await db.add_user_exercise(self.owner, 1, row[0])
            async with db.connect_db() as conn:
                ue = await (await conn.execute(
                    'SELECT id FROM user_exercises WHERE user_id=? AND day_index=1 AND exercise_id=?',
                    (self.owner, row[0]),
                )).fetchone()
            self.exercise_links.append(ue[0])
        await db.sync_current_plan_to_system(self.owner, self.a)
        await db.sync_reminders_to_system(self.owner, self.a)
        await db.set_systems_limit_prompted_at(self.owner, datetime.now(UTC) - timedelta(days=30))
        self.ctx = api.AuthCtx(900000000012, self.owner, 'trainer', None, None, int(time.time()),
                               actor_user_id=self.viewer, acting_can_edit=False, is_acting=True)

    async def asyncTearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    async def state(self):
        tables = ('users', 'training_systems', 'training_system_days', 'training_system_exercises',
                  'training_system_exercise_sources', 'training_system_reminders', 'user_days',
                  'user_exercises', 'user_reminders', 'sessions', 'running_entries', 'day_completions',
                  'day_completion_history')
        async with db.connect_db() as conn:
            return {table: sorted(await (await conn.execute(f'SELECT * FROM {table}')).fetchall(), key=repr)
                    for table in tables}

    async def test_expired_subscription_view_preserves_all_program_data_and_old_timer(self):
        before = await self.state()
        result = await api.systems_overview(self.ctx)
        self.assertEqual({self.a, self.b, self.c}, {row['id'] for row in result['systems']})
        self.assertFalse(result['systems_limit']['requires_resolution'])
        self.assertFalse(result['systems_limit']['auto_pruned'])
        self.assertTrue(result['systems_limit']['saved_systems_preserved'])
        self.assertEqual(before, await self.state())

    async def test_frequency_requires_valid_value_and_initializes_only_on_explicit_write(self):
        fresh = await db.get_or_create_user(900000000099, 'fresh')
        ctx = SimpleNamespace(user_id=fresh)
        before = await self.state()
        for payload in ({}, {'value': None}, {'value': True}, {'value': 0}, {'value': 8}, {'value': 2.5}):
            with self.assertRaises(api.HTTPException) as caught:
                await api.settings_workouts_per_week(payload=payload, ctx=ctx)
            self.assertIn(caught.exception.status_code, (400, 422))
            self.assertEqual(before, await self.state())
        value = await api.settings_workouts_per_week(payload={'value': 3}, ctx=ctx)
        self.assertEqual(value['workouts_per_week'], 3)
        self.assertEqual(len(value['days']), 3)

    async def test_viewing_dates_strength_and_run_does_not_create_sessions_or_drafts(self):
        before = await self.state()
        for day in ('2030-01-10', '2030-01-11'):
            sheet = await api.day_sheet(1, date=day, ctx=self.ctx)
            self.assertEqual(0, sheet['session_id'])
            await api.exercise_context(1, self.exercise_links[0], date=day, ctx=self.ctx)
            running = await api.get_running_state(1, self.exercise_links[1], date=day, ctx=self.ctx)
            self.assertIsNone(running['running']['entry_id'])
            await api.body_day_load(1, date=day, ctx=self.ctx)
        self.assertEqual(before, await self.state())

    async def test_sharing_counts_actual_planned_free_and_running_activity_without_empty_views(self):
        import bot
        empty = await db.get_or_create_today_session(self.owner, '2030-01-09', 1, self.a)
        self.assertEqual(await db.recorded_training_summary(self.owner), (0, None, None))
        planned = await db.get_or_create_today_session(self.owner, '2030-01-10', 1, self.a)
        await db.add_set(planned, self.exercise_links[0], reps=10, weight=30)
        free = await db.get_or_create_today_session(self.owner, '2030-01-11', 0, self.a)
        await db.add_set(free, self.exercise_links[0], reps=10, weight=30)
        running = await db.get_or_create_today_session(self.owner, '2030-01-12', 1, self.a)
        run = await db.get_running_entry(self.owner, self.exercise_links[1], session_id=running, day_index=1)
        await db.update_running_entry(run[0], distance_km=2, duration_sec=600, is_draft=1)
        self.assertEqual(await db.recorded_training_summary(self.owner), (2, '2030-01-10', '2030-01-11'))
        await db.update_running_entry(run[0], distance_km=2, duration_sec=600, is_draft=0)
        self.assertEqual(await db.recorded_training_summary(self.owner), (3, '2030-01-10', '2030-01-12'))
        self.assertEqual(await bot._load_training_summary(self.owner), await api._load_training_summary(self.owner))
        self.assertEqual(await db.recorded_training_summary(self.viewer), (0, None, None))

    async def test_shared_plan_keeps_instructions_but_excludes_private_session_note(self):
        sid=await db.get_or_create_today_session(self.owner,'2030-01-10',1,self.a)
        await db.add_set(sid,self.exercise_links[0],reps=10,weight=30)
        await db.set_exercise_note(sid,self.exercise_links[0],'Личная запись о самочувствии')
        async with db.connect_db() as conn:
            run_ex=(await (await conn.execute('SELECT exercise_id FROM user_exercises WHERE id=?',(self.exercise_links[1],))).fetchone())[0]
            await conn.execute('DELETE FROM training_system_exercise_sources WHERE system_id=? AND exercise_id<>?',(self.a,run_ex))
            await conn.execute('UPDATE training_system_exercise_sources SET source_payload=? WHERE system_id=? AND exercise_id=?',
                               (json.dumps({'note':'Инструкция опубликованной программы'}),self.a,run_ex))
            await conn.commit()
        copied=await db.copy_training_system_from_user(self.owner,self.viewer,self.a)
        own_copy=await db.copy_training_system_from_user(self.owner,self.owner,self.a)
        async with db.connect_db() as conn:
            async def notes(system):
                rows=await (await conn.execute('SELECT source_payload FROM training_system_exercise_sources WHERE system_id=?',(system,))).fetchall()
                return [json.loads(r[0]).get('note') for r in rows]
            shared=await notes(copied['system_id'])
            own=await notes(own_copy['system_id'])
        self.assertNotIn('Личная запись о самочувствии',shared)
        self.assertIn('Инструкция опубликованной программы',shared)
        self.assertIn('Личная запись о самочувствии',own)
        self.assertEqual(await db.get_exercise_note(sid,self.exercise_links[0]),'Личная запись о самочувствии')

    async def test_previous_sets_use_latest_matching_program_and_skip_warmup_only(self):
        old=await db.get_or_create_today_session(self.owner,'2030-01-01',1,self.a)
        await db.add_set(old,self.exercise_links[0],reps=8,weight=25)
        await db.add_set(old,self.exercise_links[0],reps=10,weight=30)
        warmup=await db.get_or_create_today_session(self.owner,'2030-01-02',1,self.a)
        await db.add_set(warmup,self.exercise_links[0],reps=20,weight=10,is_warmup=True)
        other_program=await db.get_or_create_today_session(self.owner,'2030-01-03',1,self.b)
        await db.add_set(other_program,self.exercise_links[0],reps=99,weight=99)
        current=await db.get_or_create_today_session(self.owner,'2030-01-04',1,self.a)
        async with db.connect_db() as conn:
            exercise=(await (await conn.execute('SELECT exercise_id FROM user_exercises WHERE id=?',(self.exercise_links[0],))).fetchone())[0]
        result=await db.fetch_day_sheet_exercise_data(self.owner,current,[(self.exercise_links[0],exercise)],'2030-01-04',self.a)
        self.assertEqual(result[self.exercise_links[0]]['previous_sets'],[(1,8,0,25.0),(2,10,0,30.0)])
        self.assertEqual(result[self.exercise_links[0]]['previous_summary'],(2,10,0,30.0))
        self.assertEqual(result[self.exercise_links[0]]['sets'],[])

    async def test_viewer_reads_existing_strength_sets_and_completed_run(self):
        sid = await db.get_or_create_today_session(self.owner, '2030-01-10', 1, self.a)
        await db.add_set(sid, self.exercise_links[0], reps=10, weight=30)
        run = await db.get_running_entry(self.owner, self.exercise_links[1], session_id=sid, day_index=1)
        await db.update_running_entry(run[0], distance_km=2, duration_sec=600, is_draft=0)
        before = await self.state()
        sheet = await api.day_sheet(1, date='2030-01-10', ctx=self.ctx)
        self.assertEqual(sid, sheet['session_id'])
        self.assertEqual(1, len(next(ex['sets'] for ex in sheet['exercises'] if ex['user_exercise_id'] == self.exercise_links[0])))
        running = await api.get_running_state(1, self.exercise_links[1], date='2030-01-10', ctx=self.ctx)
        self.assertEqual(run[0], running['running']['entry_id'])
        self.assertEqual(2, running['running']['distance_km'])
        self.assertEqual(before, await self.state())

    async def test_read_auth_does_not_seed_missing_pupil_program_and_write_still_denied(self):
        await db.ensure_training_system_defaults(self.viewer)
        async with db.connect_db() as conn:
            await conn.execute('UPDATE users SET active_system_id=NULL WHERE id=?', (self.owner,))
            await conn.commit()
        proof = SimpleNamespace(user=SimpleNamespace(id=900000000012, username='trainer', first_name=None, last_name=None), auth_date=int(time.time()))
        before = await self.state()
        with patch.object(api, 'get_trainer_link', AsyncMock(return_value=(1, 'accepted', 0, None, None))):
            result = await api.get_auth_ctx(Request({'type': 'http', 'method': 'GET', 'path': '/systems', 'headers': []}), proof, self.owner)
            self.assertTrue(result.is_acting)
            self.assertFalse(result.acting_can_edit)
            with self.assertRaises(api.HTTPException) as denied:
                await api.get_auth_ctx(Request({'type': 'http', 'method': 'POST', 'path': '/systems', 'headers': []}), proof, self.owner)
            self.assertEqual(403, denied.exception.status_code)
        await api.systems_overview(result)
        self.assertEqual(before, await self.state())

    async def test_old_resolution_dialog_selects_without_deleting_other_programs(self):
        owner_ctx = api.AuthCtx(900000000011, self.owner, 'pupil', None, None, int(time.time()))
        async with db.connect_db() as conn:
            before = await (await conn.execute('SELECT day_index,exercise_id FROM training_system_exercises WHERE system_id=? ORDER BY day_index,exercise_id', (self.a,))).fetchall()
        result = await api.systems_resolve_limit({'keep_system_id': self.b}, owner_ctx)
        self.assertTrue(result['ok'])
        self.assertEqual(self.b, await db.peek_active_training_system_id(self.owner))
        self.assertEqual([self.a, self.b, self.c], await db.list_user_training_system_ids(self.owner))
        async with db.connect_db() as conn:
            self.assertEqual(before, await (await conn.execute('SELECT day_index,exercise_id FROM training_system_exercises WHERE system_id=? ORDER BY day_index,exercise_id', (self.a,))).fetchall())

    async def test_free_explicit_replacement_changes_only_current_program(self):
        owner_ctx = api.AuthCtx(900000000011, self.owner, 'pupil', None, None, int(time.time()))
        result = await api.systems_create({'name': 'Replacement', 'replace_existing': True, 'workouts_per_week': 2}, owner_ctx)
        self.assertTrue(result['replaced'])
        self.assertEqual([self.b, self.c, result['system_id']], await db.list_user_training_system_ids(self.owner))
        self.assertEqual(result['system_id'], await db.peek_active_training_system_id(self.owner))

    async def test_expired_cycle_mark_is_filtered_without_deleting_saved_rows(self):
        old = datetime.now(UTC) - timedelta(days=10)
        await db.mark_day_completed(self.owner, 1, old.isoformat(), self.a)
        before = await self.state()
        self.assertEqual(set(), await api.get_active_day_completions(self.owner))
        self.assertEqual(before, await self.state())
