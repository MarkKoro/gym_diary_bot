import atexit
import asyncio
import importlib
import os
import tempfile
import unittest
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch


tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db.close()
atexit.register(lambda: os.path.exists(tmp_db.name) and os.remove(tmp_db.name))

os.environ["DB_PATH"] = tmp_db.name

import settings  # noqa: E402
importlib.reload(settings)
import db  # noqa: E402
importlib.reload(db)


class FetchDayExercisesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()

    async def test_fetch_day_exercises_not_duplicated_by_other_system_sessions(self):
        user_id = await db.get_or_create_user(9100, "dupcheck")
        ex_id = await db.get_or_create_exercise("Тест упражнение", "chest")
        await db.add_user_exercise(user_id, 1, ex_id)

        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        primary_session = await db.get_or_create_today_session(user_id, date_str, 1, system_id=0)

        async with db.connect_db() as conn:
            await conn.execute(
                "INSERT INTO sessions(user_id, date, day_index, system_id) VALUES(?,?,?,?)",
                (user_id, date_str, 1, 999),
            )
            cur = await conn.execute("SELECT id FROM user_exercises WHERE user_id=? AND day_index=?", (user_id, 1))
            ue_id = (await cur.fetchone())[0]
            await conn.execute(
                "INSERT INTO session_exercises(session_id, user_exercise_id, is_done) VALUES(?,?,1)",
                (primary_session, ue_id),
            )
            await conn.commit()

        rows = await db.fetch_day_exercises(user_id, 1, date_str)
        self.assertEqual(1, len(rows))


class TeamAchievementRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()
        async with db.connect_db() as conn:
            for table in ('team_members', 'team_join_requests', 'team_achievements', 'team_daily_scores', 'teams', 'user_achievements', 'day_completion_history', 'sessions'):
                await conn.execute(f'DELETE FROM {table}')
            await conn.commit()
        self.uid = await db.get_or_create_user(9200, 'captain')

    async def test_concurrent_create_has_one_team_and_predictable_error(self):
        results = await asyncio.gather(db.create_team(self.uid, 'Alpha'), db.create_team(self.uid, 'Beta'), return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in results), 1)
        self.assertEqual([str(x) for x in results if isinstance(x, Exception)], ['already_in_team'])
        async with db.connect_db() as conn:
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM teams')).fetchone())[0], 1)

    async def test_join_code_collision_retries_without_orphans(self):
        with patch.object(db, '_generate_team_join_code', return_value='TAKEN1'):
            await db.create_team(self.uid, 'Alpha')
        other = await db.get_or_create_user(9201, 'other')
        with patch.object(db, '_generate_team_join_code', side_effect=['TAKEN1', 'FRESH2']):
            team = await db.create_team(other, 'Beta')
        self.assertEqual(team['join_code'], 'FRESH2')

    async def test_parallel_joins_cannot_exceed_25_members(self):
        team = await db.create_team(self.uid, 'Alpha', True)
        tid = team['team_id']
        async with db.connect_db() as conn:
            await conn.executemany('INSERT INTO team_members(team_id,user_id,role,joined_at) VALUES(?,?,?,?)', [(tid, 10000+i, 'private', datetime.now(UTC).isoformat()) for i in range(23)])
            await conn.commit()
        results = await asyncio.gather(db.join_team_direct(tid, 20001), db.join_team_direct(tid, 20002), return_exceptions=True)
        self.assertEqual(sum(x is None for x in results), 1)
        self.assertEqual([str(x) for x in results if isinstance(x, Exception)], ['team_full'])

    async def test_duplicate_requests_share_one_pending_request(self):
        team = await db.create_team(self.uid, 'Alpha')
        results = await asyncio.gather(*(db.create_or_get_join_request(team['team_id'], 20003) for _ in range(3)))
        self.assertEqual(len({x['request_id'] for x in results}), 1)
        accepted = await asyncio.gather(*(db.accept_team_request(results[0]['request_id'], self.uid) for _ in range(2)), return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in accepted), 1)
        self.assertEqual([str(x) for x in accepted if isinstance(x, Exception)], ['request_not_pending'])

    async def test_cannot_join_missing_team_or_demote_captain(self):
        with self.assertRaisesRegex(ValueError, 'team_not_found'):
            await db.join_team_direct(9999999, self.uid)
        team = await db.create_team(self.uid, 'Alpha')
        with self.assertRaisesRegex(ValueError, 'captain_role_locked'):
            await db.set_team_member_role(team['team_id'], self.uid, self.uid, 'private')
        self.assertEqual((await db.get_user_team(self.uid))['role'], 'captain')

    async def test_hidden_leaderboard_does_not_unlock_visibility_achievement(self):
        import achievements_engine as ach
        async with db.connect_db() as conn:
            await conn.execute('UPDATE users SET leaderboard_visible=0 WHERE id=?', (self.uid,))
            await conn.commit()
        self.assertFalse((await ach._fetch_metrics(self.uid))['leaderboard_visible'])
        self.assertNotIn('leaderboard_on', (await ach.evaluate(self.uid))['earned_codes'])

    async def test_repeated_day_completion_does_not_inflate_awards(self):
        import achievements_engine as ach
        await db.set_user_timezone(self.uid, 'UTC')
        now = datetime.now(UTC).replace(hour=12, minute=0, second=0)
        for i in range(50):
            await db.mark_day_completed(self.uid, 1, (now+timedelta(seconds=i)).isoformat(), 0)
        metrics = await ach._fetch_metrics(self.uid)
        self.assertEqual(metrics['day_done_total'], 1)
        result = await ach.evaluate(self.uid)
        self.assertIn('first_day_done', result['earned_codes'])
        self.assertNotIn('day_done_50', result['earned_codes'])
        self.assertEqual((await ach.evaluate(self.uid))['newly_unlocked_codes'], [])

    async def test_empty_sessions_do_not_count_as_team_activity(self):
        import achievements_engine as ach
        team = await db.create_team(self.uid, 'Alpha')
        today = datetime.now(UTC).date()
        for i in range(12):
            await db.get_or_create_today_session(self.uid, (today-timedelta(days=i)).isoformat(), 1, 0)
        metrics = await ach._fetch_team_metrics(team['team_id'])
        self.assertEqual(metrics['sessions_28'], 0)
        self.assertEqual(metrics['active_members_7d'], 0)
        self.assertNotIn('t_consistency_28', (await ach.evaluate_team(team['team_id']))['earned_team_codes'])
        await db.mark_day_completed(self.uid, 1, datetime.now(UTC).isoformat(), 0)
        self.assertEqual((await ach._fetch_team_metrics(team['team_id']))['sessions_28'], 1)

    async def test_team_night_awards_use_member_timezone_and_unique_days(self):
        import achievements_engine as ach
        team = await db.create_team(self.uid, 'Alpha')
        await db.set_user_timezone(self.uid, 'Asia/Bangkok')
        now = datetime.now(UTC).replace(hour=18, minute=0, second=0)
        await db.mark_day_completed(self.uid, 1, now.isoformat(), 0)
        await db.mark_day_completed(self.uid, 1, (now+timedelta(seconds=10)).isoformat(), 0)
        self.assertEqual((await ach._fetch_team_metrics(team['team_id']))['night_sessions_28'], 1)
        await db.set_user_timezone(self.uid, 'UTC')
        self.assertEqual((await ach._fetch_team_metrics(team['team_id']))['night_sessions_28'], 0)

    async def test_team_counts_match_local_session_date_near_midnight(self):
        import achievements_engine as ach
        team = await db.create_team(self.uid, 'Night crew')
        await db.set_user_timezone(self.uid, 'Asia/Bangkok')
        utc_time = datetime.now(UTC).replace(hour=18, minute=0, second=0)
        local_date = (utc_time+timedelta(hours=7)).date().isoformat()
        await db.get_or_create_today_session(self.uid, local_date, 1, 0)
        await db.mark_day_completed(self.uid, 1, utc_time.isoformat(), 0)
        metrics = await ach._fetch_team_metrics(team['team_id'])
        self.assertEqual(metrics['sessions_28'], 1)
        self.assertEqual(metrics['active_members_7d'], 1)
        teams, _, _ = await db.fetch_team_leaderboard()
        self.assertEqual(next(t for t in teams if t['team_id'] == team['team_id'])['sessions_28'], 1)
        self.assertIsNotNone(await db.fetch_team_profile(team['team_id'], self.uid))

    async def test_system_operations_reject_other_users_system_without_changes(self):
        other = await db.get_or_create_user(9300, 'private')
        own_system = await db.get_active_training_system_id(self.uid)
        other_system = await db.get_active_training_system_id(other)
        await db.create_training_system(self.uid, 'Spare')
        async with db.connect_db() as conn:
            await conn.execute('INSERT OR REPLACE INTO training_system_days(system_id,day_index,label,is_active) VALUES(?,1,?,1)', (other_system, 'Private day'))
            await conn.commit()
        for method in (db.apply_system_to_current_plan, db.sync_current_plan_to_system, db.sync_reminders_to_system):
            with self.assertRaisesRegex(ValueError, 'system_not_found'):
                await method(self.uid, other_system)
        self.assertFalse(await db.delete_training_system(self.uid, other_system))
        self.assertEqual(await db.get_active_training_system_id(self.uid), own_system)
        async with db.connect_db() as conn:
            row = await (await conn.execute('SELECT label FROM training_system_days WHERE system_id=? AND day_index=1', (other_system,))).fetchone()
            self.assertEqual(row[0], 'Private day')

    async def test_invalid_active_system_is_repaired_to_own_system(self):
        other = await db.get_or_create_user(9301, 'private2')
        other_system = await db.get_active_training_system_id(other)
        async with db.connect_db() as conn:
            await conn.execute('UPDATE users SET active_system_id=? WHERE id=?', (other_system, self.uid))
            await conn.commit()
        actual = await db.get_active_training_system_id(self.uid)
        self.assertNotEqual(actual, other_system)
        self.assertIn(actual, [row['id'] for row in await db.list_training_systems(self.uid)])

    async def test_fewer_workout_days_preserve_historical_exercise_completions(self):
        await db.set_workouts_per_week(self.uid, 4)
        ex = await db.get_or_create_exercise('History exercise', 'chest', self.uid)
        await db.add_user_exercise(self.uid, 4, ex)
        session = await db.get_or_create_today_session(self.uid, datetime.now(UTC).date().isoformat(), 4, 0)
        async with db.connect_db() as conn:
            ue = (await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=? AND day_index=4', (self.uid, ex))).fetchone())[0]
            await conn.execute('INSERT INTO session_exercises(session_id,user_exercise_id,is_done) VALUES(?,?,1)', (session, ue))
            await conn.commit()
        await db.set_workouts_per_week(self.uid, 2)
        async with db.connect_db() as conn:
            row = await (await conn.execute('SELECT is_done FROM session_exercises WHERE session_id=? AND user_exercise_id=?', (session, ue))).fetchone()
            self.assertEqual(row, (1,))

    async def test_reminders_validate_before_writing_and_roll_back_on_failure(self):
        import webapp_backend as backend
        await db.set_workouts_per_week(self.uid, 3)
        ctx = SimpleNamespace(user_id=self.uid)
        original = {'enabled': True, 'timezone': 'UTC', 'reminders': [{'day_no': 1, 'dow': 1, 'hour': 9, 'minute': 0}]}
        await backend.settings_update_reminders(original, ctx)
        with self.assertRaises(backend.HTTPException):
            await backend.settings_update_reminders({'enabled': False, 'timezone': 'Europe/Moscow', 'reminders': ['bad']}, ctx)
        self.assertEqual(await db.list_user_reminders(self.uid), [(1, 1, 9, 0)])
        self.assertTrue(await db.get_user_notifications_enabled(self.uid))
        async with db.connect_db() as conn:
            await conn.execute("CREATE TRIGGER fail_reminder_insert BEFORE INSERT ON training_system_reminders BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            await conn.commit()
        try:
            with self.assertRaises(Exception):
                await backend.settings_update_reminders({**original, 'enabled': False, 'reminders': [{'day_no': 2, 'dow': 2, 'hour': 10, 'minute': 0}]}, ctx)
            self.assertEqual(await db.list_user_reminders(self.uid), [(1, 1, 9, 0)])
            self.assertTrue(await db.get_user_notifications_enabled(self.uid))
        finally:
            async with db.connect_db() as conn:
                await conn.execute('DROP TRIGGER fail_reminder_insert')
                await conn.commit()


class TrainerAndCaptainRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()
        async with db.connect_db() as conn:
            for table in ('trainer_links', 'team_members', 'team_join_requests', 'team_achievements', 'teams', 'subscriptions'):
                await conn.execute(f'DELETE FROM {table}')
            await conn.commit()
        self.trainer = await db.get_or_create_user(9400, 'trainer')
        self.other = await db.get_or_create_user(9401, 'other_trainer')
        self.trainee = await db.get_or_create_user(9402, 'trainee')
        async with db.connect_db() as conn:
            await conn.execute('UPDATE users SET is_trainer=1, trainer_accepts_requests=1 WHERE id IN (?,?)', (self.trainer, self.other))
            await conn.commit()

    async def test_duplicate_trainer_requests_and_competing_decisions(self):
        ids = await asyncio.gather(*(db.create_trainer_request(self.trainer, self.trainee) for _ in range(3)))
        self.assertEqual(len(set(ids)), 1)
        with self.assertRaises(ValueError):
            await db.create_trainer_request(self.other, self.trainee)
        results = await asyncio.gather(db.update_trainer_link_status(ids[0], 'accepted'), db.update_trainer_link_status(ids[0], 'declined'))
        self.assertEqual(sum(results), 1)
        self.assertFalse(await db.update_trainer_link_status(ids[0], 'accepted'))

    async def test_concurrent_accept_respects_trainer_limit(self):
        ids = []
        for i in range(6):
            trainee = await db.get_or_create_user(9500+i, f'trainee{i}')
            ids.append(await db.create_trainer_request(self.trainer, trainee))
        results = await asyncio.gather(*(db.update_trainer_link_status(link, 'accepted') for link in ids), return_exceptions=True)
        self.assertEqual(sum(x is True for x in results), 5)
        self.assertEqual(sum(isinstance(x, ValueError) for x in results), 1)
        self.assertEqual(await db.count_trainer_trainees(self.trainer), 5)

    async def test_pending_trainer_request_can_be_cancelled_and_replaced(self):
        import webapp_backend as backend
        first = await db.create_trainer_request(self.trainer, self.trainee)
        result = await backend.settings_trainer_detach(SimpleNamespace(user_id=self.trainee))
        self.assertTrue(result['removed'])
        self.assertFalse(await db.update_trainer_link_status(first, 'accepted'))
        second = await db.create_trainer_request(self.other, self.trainee)
        self.assertNotEqual(first, second)
        self.assertEqual((await db.get_latest_trainer_link_for_trainee(self.trainee))[0], second)

    async def test_reactivation_does_not_reclaim_trainee_with_another_trainer(self):
        link = await db.create_trainer_request(self.trainer, self.trainee)
        await db.update_trainer_link_status(link, 'accepted')
        await db.deactivate_trainer_links(self.trainer)
        other = await db.create_trainer_request(self.other, self.trainee)
        await db.update_trainer_link_status(other, 'accepted')
        self.assertEqual(await db.reactivate_trainer_links(self.trainer), [])
        self.assertEqual((await db.get_active_trainer_link_for_trainee(self.trainee))[1], self.other)

    async def test_leaving_captain_hands_over_control_without_founder_award(self):
        import achievements_engine as ach
        team = await db.create_team(self.trainer, 'Succession', True)
        await db.join_team_direct(team['team_id'], self.other)
        await db.join_team_direct(team['team_id'], self.trainee)
        await db.set_team_member_role(team['team_id'], self.trainer, self.trainee, 'colonel')
        await db.leave_team(self.trainer)
        successor = await db.get_user_team(self.trainee)
        self.assertEqual(successor['role'], 'captain')
        self.assertEqual(successor['owner_user_id'], self.trainer)
        self.assertFalse((await ach._fetch_metrics(self.trainee))['team_is_founder'])
        request = await db.create_or_get_join_request(team['team_id'], 9800)
        await db.accept_team_request(request['request_id'], self.trainee)
        self.assertEqual((await db.get_user_team(9800))['team_id'], team['team_id'])
        await db.leave_team(self.trainee)
        self.assertEqual((await db.get_user_team(self.other))['role'], 'captain')

    async def test_moving_shared_exercise_preserves_history_and_saved_systems(self):
        shared = await db.get_or_create_exercise('Move collision', 'chest')
        personal = await db.set_exercise_muscle_group_for_user(self.trainee, shared, 'legs')
        for owner, exercise in ((self.trainee, shared), (self.trainee, personal), (self.other, shared)):
            await db.add_user_exercise(owner, 1, exercise)
        system = await db.get_active_training_system_id(self.trainee)
        session = await db.get_or_create_today_session(self.trainee, datetime.now(UTC).date().isoformat(), 1, system)
        async with db.connect_db() as conn:
            original = (await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=? AND day_index=1', (self.trainee, shared))).fetchone())[0]
            duplicate = (await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=? AND day_index=1', (self.trainee, personal))).fetchone())[0]
            await conn.executemany('INSERT INTO sets(session_id,user_exercise_id,set_no,reps,weight_kg) VALUES(?,?,1,5,?)', [(session, original, 20), (session, duplicate, 30)])
            await conn.executemany('INSERT OR REPLACE INTO session_exercises(session_id,user_exercise_id,is_done,note) VALUES(?,?,?,?)', [(session, original, 0, 'First note'), (session, duplicate, 1, 'Second note')])
            await conn.executemany('INSERT INTO exercise_notes(user_id,exercise_id,note) VALUES(?,?,?)', [(self.trainee, shared, 'Shared note'), (self.trainee, personal, 'Personal note')])
            await conn.execute('INSERT OR IGNORE INTO training_system_exercises(system_id,day_index,exercise_id) VALUES(?,1,?)', (system, shared))
            await conn.execute('INSERT OR IGNORE INTO training_system_exercise_sources(system_id,day_index,exercise_id,source_payload) VALUES(?,1,?,?)', (system, shared, '{"source":"test"}'))
            await conn.commit()
        self.assertEqual(await db.set_exercise_muscle_group_for_user(self.trainee, shared, 'back'), personal)
        async with db.connect_db() as conn:
            self.assertEqual((await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=? AND day_index=1', (self.trainee, personal))).fetchone())[0], original)
            self.assertEqual(await (await conn.execute('SELECT set_no,weight_kg FROM sets WHERE session_id=? AND user_exercise_id=? ORDER BY set_no', (session, original))).fetchall(), [(1, 20), (2, 30)])
            completion = await (await conn.execute('SELECT is_done,note FROM session_exercises WHERE session_id=? AND user_exercise_id=?', (session, original))).fetchone()
            self.assertEqual(completion, (1, 'First note\nSecond note'))
            note = (await (await conn.execute('SELECT note FROM exercise_notes WHERE user_id=? AND exercise_id=?', (self.trainee, personal))).fetchone())[0]
            self.assertIn('Shared note', note); self.assertIn('Personal note', note)
            for table in ('training_system_exercises', 'training_system_exercise_sources'):
                self.assertIsNone(await (await conn.execute(f'SELECT 1 FROM {table} WHERE system_id=? AND exercise_id=?', (system, shared))).fetchone())
                self.assertIsNotNone(await (await conn.execute(f'SELECT 1 FROM {table} WHERE system_id=? AND exercise_id=?', (system, personal))).fetchone())
            self.assertEqual((await (await conn.execute('SELECT muscle_group FROM exercises WHERE id=?', (shared,))).fetchone())[0], 'chest')
            self.assertIsNotNone(await (await conn.execute('SELECT 1 FROM user_exercises WHERE user_id=? AND exercise_id=?', (self.other, shared))).fetchone())


class ProgramCopyRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()
        offset = sorted(name for name in dir(self) if name.startswith('test_')).index(self._testMethodName) * 10
        self.source = await db.get_or_create_user(9910 + offset, 'copy_source')
        self.target = await db.get_or_create_user(9911 + offset, 'copy_target')
        self.source_system = await db.get_active_training_system_id(self.source)
        self.target_system = await db.get_active_training_system_id(self.target)
        self.source_ex = await db.get_or_create_exercise('Copy source exercise', 'chest', self.source)
        self.target_ex = await db.get_or_create_exercise('Keep personal exercise', 'legs', self.target)
        async with db.connect_db() as conn:
            for user in (self.source, self.target):
                await conn.execute('DELETE FROM training_system_exercises WHERE system_id IN (SELECT id FROM training_systems WHERE user_id=?)', (user,))
            await conn.execute("UPDATE training_systems SET name='Matching name' WHERE id IN (?,?)", (self.source_system, self.target_system))
            await conn.executemany('INSERT INTO training_system_exercises(system_id,day_index,exercise_id) VALUES(?,1,?)', [(self.source_system, self.source_ex), (self.target_system, self.target_ex)])
            await conn.commit()

    async def test_copy_preserves_same_named_personal_program_and_reports_source(self):
        results = await asyncio.gather(*(db.copy_training_system_from_user(self.source, self.target) for _ in range(2)))
        self.assertEqual(len({r['system_id'] for r in results}), 2)
        for result in results:
            self.assertNotEqual(result['system_id'], self.target_system)
            self.assertEqual(result['source_system_id'], self.source_system)
        async with db.connect_db() as conn:
            self.assertEqual(await (await conn.execute('SELECT exercise_id FROM training_system_exercises WHERE system_id=?', (self.target_system,))).fetchall(), [(self.target_ex,)])
            names = await (await conn.execute('SELECT name FROM training_systems WHERE user_id=?', (self.target,))).fetchall()
            self.assertEqual(len(names), len(set(names)))

    async def test_invalid_or_empty_source_does_not_replace_current_program(self):
        with self.assertRaisesRegex(ValueError, 'system_not_found'):
            await db.copy_training_system_from_user(self.source, self.target, self.target_system)
        async with db.connect_db() as conn:
            await conn.execute('DELETE FROM training_system_exercises WHERE system_id=?', (self.source_system,))
            await conn.commit()
        result = await db.copy_training_system_from_user(self.source, self.target, self.source_system)
        self.assertIsNone(result['system_id'])
        self.assertEqual(await db.get_active_training_system_id(self.target), self.target_system)

    async def test_legacy_copy_works_with_single_connection_and_leaves_no_empty_system(self):
        legacy = await db.get_or_create_user(9912, 'legacy_copy')
        await db.set_workouts_per_week(legacy, 1)
        await db.add_user_exercise(legacy, 1, self.source_ex)
        async with db.connect_db() as conn:
            await conn.execute('DELETE FROM training_systems WHERE user_id=?', (legacy,))
            await conn.commit()
        with patch.object(db, '_db_semaphore', asyncio.BoundedSemaphore(1)):
            result = await asyncio.wait_for(db.copy_training_system_from_user(legacy, self.target), 3)
        self.assertIsNotNone(result['system_id'])
        self.assertGreater(result['exercises'], 0)
        async with db.connect_db() as conn:
            await conn.execute('DELETE FROM user_exercises WHERE user_id=?', (legacy,))
            before = (await (await conn.execute('SELECT COUNT(*) FROM training_system_days')).fetchone())[0]
            await conn.commit()
        self.assertIsNone((await db.copy_training_system_from_user(legacy, self.target))['system_id'])
        async with db.connect_db() as conn:
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM training_system_days')).fetchone())[0], before)


class ExerciseDeletionRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()
        self.owner = await db.get_or_create_user(9900, 'deletion_owner')
        self.other = await db.get_or_create_user(9901, 'deletion_recipient')

    async def seed_shared_exercise(self, name, *, saved_only=False):
        exercise = await db.get_or_create_exercise(name, 'other', self.owner)
        systems = {}
        for user in (self.owner, self.other):
            systems[user] = await db.get_active_training_system_id(user)
            if user == self.owner or not saved_only:
                await db.add_user_exercise(user, 1, exercise)
            async with db.connect_db() as conn:
                await conn.execute('INSERT OR IGNORE INTO training_system_exercises(system_id,day_index,exercise_id) VALUES(?,1,?)', (systems[user], exercise))
                await conn.execute('INSERT OR IGNORE INTO training_system_exercise_sources(system_id,day_index,exercise_id,source_payload) VALUES(?,1,?,?)', (systems[user], exercise, '{}'))
                await conn.execute('INSERT INTO exercise_baseline(user_id,day_index,exercise_id,sets,reps) VALUES(?,1,?,1,10)', (user, exercise))
                await conn.execute('INSERT INTO exercise_notes(user_id,exercise_id,note) VALUES(?,?,?)', (user, exercise, f'note {user}'))
                await conn.execute('INSERT INTO user_exercise_muscles(user_id,exercise_id,muscle_code,weight_pct) VALUES(?,?,?,100)', (user, exercise, 'chest'))
                if user == self.owner or not saved_only:
                    ue = (await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=? AND day_index=1', (user, exercise))).fetchone())[0]
                    await conn.execute('INSERT INTO sets(session_id,user_exercise_id,set_no,reps) VALUES(0,?,1,10)', (ue,))
                    await conn.execute('INSERT INTO session_exercises(session_id,user_exercise_id,is_done) VALUES(0,?,1)', (ue,))
                    await conn.execute('INSERT INTO running_entries(user_id,user_exercise_id,exercise_id) VALUES(?,?,?)', (user, ue, exercise))
                await conn.commit()
        return exercise, systems

    async def assert_only_owner_removed(self, exercise, systems, *, saved_only=False):
        async with db.connect_db() as conn:
            self.assertIsNotNone(await (await conn.execute('SELECT id FROM exercises WHERE id=?', (exercise,))).fetchone())
            for table in ('user_exercises', 'exercise_notes', 'user_exercise_muscles', 'exercise_baseline', 'running_entries'):
                self.assertEqual((await (await conn.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=? AND exercise_id=?', (self.owner, exercise))).fetchone())[0], 0, table)
                expected = 0 if saved_only and table in ('user_exercises', 'running_entries') else (2 if table == 'user_exercises' else 1)
                self.assertEqual((await (await conn.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=? AND exercise_id=?', (self.other, exercise))).fetchone())[0], expected, table)
            for table in ('training_system_exercises', 'training_system_exercise_sources'):
                self.assertIsNone(await (await conn.execute(f'SELECT 1 FROM {table} WHERE system_id=? AND exercise_id=?', (systems[self.owner], exercise))).fetchone(), table)
                self.assertIsNotNone(await (await conn.execute(f'SELECT 1 FROM {table} WHERE system_id=? AND exercise_id=?', (systems[self.other], exercise))).fetchone(), table)
            if not saved_only:
                for table in ('sets', 'session_exercises'):
                    self.assertEqual((await (await conn.execute(f'SELECT COUNT(*) FROM {table} t JOIN user_exercises ue ON ue.id=t.user_exercise_id WHERE ue.user_id=? AND ue.exercise_id=?', (self.other, exercise))).fetchone())[0], 1, table)
        self.assertNotIn(exercise, [r[0] for r in await db.list_visible_catalog_exercises_for_user(self.owner)])

    async def test_bulk_delete_preserves_other_users_history(self):
        exercise, systems = await self.seed_shared_exercise('Bulk shared deletion')
        await db.clear_non_base_group_exercises_for_user(self.owner)
        await self.assert_only_owner_removed(exercise, systems)

    async def test_individual_delete_preserves_other_saved_program(self):
        exercise, systems = await self.seed_shared_exercise('Saved-only deletion', saved_only=True)
        await db.remove_exercise_for_user(self.owner, exercise)
        await self.assert_only_owner_removed(exercise, systems, saved_only=True)

    async def test_hard_delete_cannot_restore_from_saved_system(self):
        exercise, systems = await self.seed_shared_exercise('Hard shared deletion')
        self.assertTrue(await db.hard_delete_user_owned_exercise(self.owner, exercise))
        await self.assert_only_owner_removed(exercise, systems)
        await db.apply_system_to_current_plan(self.owner, systems[self.owner])
        async with db.connect_db() as conn:
            self.assertIsNone(await (await conn.execute('SELECT 1 FROM user_exercises WHERE user_id=? AND exercise_id=? AND is_archived=0', (self.owner, exercise))).fetchone())

    async def test_group_clear_preserves_other_users_and_clears_saved_links(self):
        exercise, systems = await self.seed_shared_exercise('Group shared deletion')
        await db.clear_group_exercises_for_user(self.owner, 'other')
        await self.assert_only_owner_removed(exercise, systems)

    async def test_bulk_clear_works_for_shared_exercises_without_own_catalog(self):
        viewer = await db.get_or_create_user(9902, 'shared_only')
        exercise = await db.get_or_create_exercise('Shared only bulk deletion', 'other', self.other)
        await db.add_user_exercise(viewer, 1, exercise)
        await db.clear_non_base_group_exercises_for_user(viewer)
        async with db.connect_db() as conn:
            self.assertIsNone(await (await conn.execute('SELECT 1 FROM user_exercises WHERE user_id=? AND exercise_id=?', (viewer, exercise))).fetchone())
            self.assertIsNotNone(await (await conn.execute('SELECT 1 FROM exercises WHERE id=?', (exercise,))).fetchone())


if __name__ == "__main__":
    unittest.main()
