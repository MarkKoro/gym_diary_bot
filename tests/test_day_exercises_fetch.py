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
        now = (datetime.now(UTC)-timedelta(days=1)).replace(hour=18, minute=0, second=0)
        await db.mark_day_completed(self.uid, 1, now.isoformat(), 0)
        await db.mark_day_completed(self.uid, 1, (now+timedelta(seconds=10)).isoformat(), 0)
        self.assertEqual((await ach._fetch_team_metrics(team['team_id']))['night_sessions_28'], 1)
        await db.set_user_timezone(self.uid, 'UTC')
        self.assertEqual((await ach._fetch_team_metrics(team['team_id']))['night_sessions_28'], 0)

    async def test_team_counts_match_local_session_date_near_midnight(self):
        import achievements_engine as ach
        team = await db.create_team(self.uid, 'Night crew')
        await db.set_user_timezone(self.uid, 'Asia/Bangkok')
        utc_time = (datetime.now(UTC)-timedelta(days=1)).replace(hour=18, minute=0, second=0)
        local_date = (utc_time+timedelta(hours=7)).date().isoformat()
        await db.get_or_create_today_session(self.uid, local_date, 1, 0)
        await db.mark_day_completed(self.uid, 1, utc_time.isoformat(), 0)
        metrics = await ach._fetch_team_metrics(team['team_id'])
        self.assertEqual(metrics['sessions_28'], 1)
        self.assertEqual(metrics['active_members_7d'], 1)
        teams, _, _ = await db.fetch_team_leaderboard()
        self.assertEqual(next(t for t in teams if t['team_id'] == team['team_id'])['sessions_28'], 1)
        self.assertIsNotNone(await db.fetch_team_profile(team['team_id'], self.uid))

    async def test_team_profile_uses_the_same_completed_training_score_as_ranking(self):
        await db.set_user_timezone(self.uid,'UTC')
        team = await db.create_team(self.uid,'Consistent member score')
        ex = await db.get_or_create_exercise('Profile score press','chest',self.uid)
        await db.add_user_exercise(self.uid,1,ex)
        today = datetime.now(UTC).date().isoformat()
        session = await db.get_or_create_today_session(self.uid,today,1,0)
        async with db.connect_db() as conn:
            ue = (await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=?',(self.uid,ex))).fetchone())[0]
            await conn.executemany('INSERT INTO sets(session_id,user_exercise_id,set_no,reps,weight_kg) VALUES(?,?,?,?,?)',[(session,ue,i+1,10,100) for i in range(10)])
            await conn.commit()
        profile = await db.fetch_team_profile(team['team_id'],self.uid)
        self.assertEqual(profile['members'][0]['score'],profile['team']['avg_member_score'])
        await db.mark_day_completed(self.uid,1,datetime.now(UTC).isoformat(),0)
        completed = await db.fetch_team_profile(team['team_id'],self.uid)
        self.assertEqual(completed['members'][0]['score'],completed['team']['avg_member_score'])
        self.assertGreater(completed['members'][0]['score'],profile['members'][0]['score'])

    async def test_join_request_statistics_use_unique_history_not_latest_day_state(self):
        from zoneinfo import ZoneInfo
        applicant = await db.get_or_create_user(92901,'HistoryApplicant')
        await db.set_user_timezone(applicant,'Etc/GMT-14')
        team = await db.create_team(self.uid,'Request history')
        await db.create_or_get_join_request(team['team_id'],applicant)
        local_now = datetime.now(UTC).astimezone(ZoneInfo('Etc/GMT-14')).replace(hour=0,minute=0,second=0,microsecond=0)
        for offset in (0,27,28,0):
            await db.mark_day_completed(applicant,1,(local_now-timedelta(days=offset)).astimezone(UTC).isoformat(),0)
        items,total = await db.list_team_requests(team['team_id'])
        self.assertEqual(total,1)
        self.assertEqual((items[0]['sessions_total'],items[0]['sessions_28']),(3,2))

    async def test_join_request_search_accepts_username_with_at_sign(self):
        applicant = await db.get_or_create_user(92902,'SearchApplicant')
        team = await db.create_team(self.uid,'Request search')
        await db.create_or_get_join_request(team['team_id'],applicant)
        for query in ('SearchApp',' @searchapp '):
            with self.subTest(query=query):
                items,total = await db.list_team_requests(team['team_id'],q=query)
                self.assertEqual(total,1)
                self.assertEqual(items[0]['user_id'],applicant)

    async def test_captain_cannot_read_or_decide_another_teams_requests(self):
        import webapp_backend as api
        from fastapi import HTTPException
        other = await db.get_or_create_user(92903,'OtherCaptain')
        applicant = await db.get_or_create_user(92904,'PrivateApplicant')
        await db.create_team(self.uid,'Own team')
        team = await db.create_team(other,'Other team')
        request = await db.create_or_get_join_request(team['team_id'],applicant)
        self.assertEqual((await api.teams_requests(ctx=SimpleNamespace(user_id=self.uid)))['items'],[])
        for user in (self.uid,applicant):
            for handler in (api.teams_requests_accept,api.teams_requests_reject):
                with self.subTest(user=user,action=handler.__name__),self.assertRaises(HTTPException) as caught:
                    await handler(request['request_id'],SimpleNamespace(user_id=user))
                self.assertEqual(caught.exception.status_code,403)
        self.assertEqual(await db.count_team_pending_requests(team['team_id']),1)
        self.assertIsNone(await db.get_user_team(applicant))

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


class AiPlanAtomicityTests(unittest.IsolatedAsyncioTestCase):
    sequence = 0

    async def asyncSetUp(self):
        import webapp_backend as backend
        self.backend = backend
        await db.init_db()
        type(self).sequence += 1
        self.uid = await db.get_or_create_user(95000+self.sequence, 'ai_plan_test')
        await db.set_workouts_per_week(self.uid, 3)
        self.sid = await db.ensure_training_system_defaults(self.uid)
        await db.grant_subscription_days(self.uid, 30)
        self.ctx = SimpleNamespace(user_id=self.uid)

    def new_plan(self, request_id='test-ai-create-request-1'):
        return {'request_id': request_id, 'system_id': self.sid, 'expected_days': 2, 'actions': [{
            'type': 'create_system', 'system_name': 'AI regression plan', 'days': [
                {'day_index': 2, 'title': 'Strength', 'exercises': [{'exercise_name': 'AI squat', 'sets': 3, 'reps': 8, 'weight_kg': 40}]},
                {'day_index': 5, 'title': 'Core', 'exercises': [{'exercise_name': 'AI plank', 'sets': 2, 'reps': 0, 'seconds': 60}]},
            ]}]}

    async def test_concurrent_retry_creates_one_complete_system_and_preserves_duration(self):
        import copy
        existing = await db.create_training_system(self.uid, 'AI regression plan')
        payload = self.new_plan()
        results = await asyncio.gather(*(self.backend.ai_coach_apply(copy.deepcopy(payload), self.ctx) for _ in range(3)))
        self.assertEqual(len({r['system_id'] for r in results}), 1)
        self.assertEqual(sum(not r['already_applied'] for r in results), 1)
        created = results[0]['system_id']
        self.assertNotEqual(created, existing)
        async with db.connect_db() as conn:
            days = await (await conn.execute('SELECT day_index FROM user_days WHERE user_id=? AND is_active=1 ORDER BY day_index', (self.uid,))).fetchall()
            self.assertEqual(days, [(2,), (5,)])
            row = await (await conn.execute('SELECT b.reps,b.seconds FROM exercise_baseline b JOIN exercises e ON e.id=b.exercise_id WHERE b.user_id=? AND e.name=? AND b.day_index=5', (self.uid, 'AI plank'))).fetchone()
            self.assertEqual(row, (0, 60))
            saved = await (await conn.execute('SELECT COUNT(*) FROM training_system_exercises WHERE system_id=? AND day_index>0', (created,))).fetchone()
            self.assertEqual(saved[0], 2)
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM training_system_exercise_sources WHERE system_id=?', (created,))).fetchone())[0], 2)
        # A receipt remains safe to retry even after switching away from the new plan.
        await db.apply_system_to_current_plan(self.uid, self.sid)
        self.assertTrue((await self.backend.ai_coach_apply(payload, self.ctx))['already_applied'])
        self.assertEqual(await db.get_active_training_system_id(self.uid), self.sid)

    async def test_mid_apply_failure_rolls_back_every_write_and_can_retry(self):
        async with db.connect_db() as conn:
            await conn.execute("CREATE TRIGGER reject_ai_source BEFORE INSERT ON training_system_exercise_sources BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            await conn.commit()
        try:
            with self.assertRaises(Exception):
                await self.backend.ai_coach_apply(self.new_plan(), self.ctx)
        finally:
            async with db.connect_db() as conn:
                await conn.execute('DROP TRIGGER reject_ai_source')
                await conn.commit()
        self.assertEqual(await db.get_active_training_system_id(self.uid), self.sid)
        async with db.connect_db() as conn:
            for sql in ('SELECT COUNT(*) FROM training_systems WHERE user_id=?', 'SELECT COUNT(*) FROM exercise_baseline WHERE user_id=?', 'SELECT COUNT(*) FROM exercises WHERE created_by_user_id=?'):
                count = (await (await conn.execute(sql, (self.uid,))).fetchone())[0]
                self.assertEqual(count, 1 if 'training_systems' in sql else 0)
            self.assertIsNone(await (await conn.execute('SELECT 1 FROM app_meta WHERE key=?', (f'ai_apply:{self.uid}:test-ai-create-request-1',))).fetchone())
        self.assertTrue((await self.backend.ai_coach_apply(self.new_plan(), self.ctx))['ok'])

    async def test_changed_or_foreign_system_and_conflicting_retry_are_rejected(self):
        from fastapi import HTTPException
        other = await db.get_or_create_user(95999, 'other_ai_owner')
        foreign = await db.ensure_training_system_defaults(other)
        payload = self.new_plan()
        payload['system_id'] = foreign
        with self.assertRaises(HTTPException) as err:
            await self.backend.ai_coach_apply(payload, self.ctx)
        self.assertEqual(err.exception.status_code, 409)
        payload = self.new_plan()
        await self.backend.ai_coach_apply(payload, self.ctx)
        payload['actions'][0]['system_name'] = 'Changed'
        with self.assertRaises(HTTPException):
            await self.backend.ai_coach_apply(payload, self.ctx)
        payload['request_id'] = 'test-ai-new-request-2'
        with self.assertRaises(HTTPException):
            await self.backend.ai_coach_apply(payload, self.ctx)

    async def test_replacement_retry_does_not_toggle_back_or_delete_history(self):
        old = await db.get_or_create_exercise('AI old exercise', 'other', self.uid)
        await db.add_user_exercise(self.uid, 1, old)
        async with db.connect_db() as conn:
            ue = (await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND day_index=1 AND exercise_id=?', (self.uid, old))).fetchone())[0]
        session = await db.get_or_create_today_session(self.uid, '2026-09-25', 1, self.sid)
        await db.add_set(session, ue, 8, 0, 40)
        payload = {'request_id': 'ai-replace-regression-1', 'system_id': self.sid, 'actions': [{'type': 'replace_exercise', 'day_index': 1, 'old_exercise_name': 'AI old exercise', 'new_exercise_name': 'AI new exercise', 'sets': 4, 'reps': 10}]}
        await self.backend.ai_coach_apply(payload, self.ctx)
        await self.backend.ai_coach_apply(payload, self.ctx)
        async with db.connect_db() as conn:
            self.assertEqual((await (await conn.execute('SELECT is_archived FROM user_exercises WHERE id=?', (ue,))).fetchone())[0], 1)
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM sets WHERE user_exercise_id=?', (ue,))).fetchone())[0], 1)
            self.assertIsNone(await (await conn.execute('SELECT 1 FROM training_system_exercises WHERE system_id=? AND day_index=1 AND exercise_id=?', (self.sid, old))).fetchone())
        # Invalid later actions must undo earlier additions too.
        bad = {'request_id': 'ai-invalid-regression-2', 'system_id': self.sid, 'actions': [
            {'type': 'add_exercise', 'day_index': 1, 'exercise_name': 'Must roll back'},
            {'type': 'remove_exercise', 'day_index': 1, 'old_exercise_name': 'Missing'},
        ]}
        with self.assertRaises(Exception):
            await self.backend.ai_coach_apply(bad, self.ctx)
        async with db.connect_db() as conn:
            self.assertIsNone(await (await conn.execute('SELECT 1 FROM exercises WHERE created_by_user_id=? AND name=?', (self.uid, 'Must roll back'))).fetchone())

    async def test_apply_works_with_one_database_connection(self):
        with patch.object(db, '_db_semaphore', asyncio.BoundedSemaphore(1)):
            result = await asyncio.wait_for(self.backend.ai_coach_apply(self.new_plan(), self.ctx), 5)
        self.assertTrue(result['ok'])
        await db.wipe_user(self.uid)
        async with db.connect_db() as conn:
            self.assertIsNone(await (await conn.execute('SELECT 1 FROM app_meta WHERE key LIKE ?', (f'ai_apply:{self.uid}:%',))).fetchone())

    async def test_baseline_api_keeps_zero_reps_for_timed_exercise(self):
        exercise = await db.get_or_create_exercise('Timed regression', 'core', self.uid)
        await self.backend.set_day_exercise_baseline(1, exercise, {'sets': 2, 'reps': 0, 'seconds': 60, 'weight_kg': 0}, self.ctx)
        self.assertEqual(await db.get_baseline(self.uid, 1, exercise), (2, 0, 60, 0.0))

    async def test_malformed_and_duplicate_plan_days_are_rejected_without_writes(self):
        from fastapi import HTTPException
        import copy
        base = self.new_plan()
        cases = []
        for days in ([], [None], [base['actions'][0]['days'][0]]*2):
            item = copy.deepcopy(base)
            item['actions'][0]['days'] = days
            cases.append(item)
        item = copy.deepcopy(base)
        item['actions'][0]['days'][0]['exercises'] *= 2
        cases.append(item)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(HTTPException):
                await self.backend.ai_coach_apply(payload, self.ctx)
        self.assertEqual(await db.get_active_training_system_id(self.uid), self.sid)





class FreeWorkoutCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx
        import webapp_backend as api
        from unittest.mock import AsyncMock
        self.api = api
        await db.init_db()
        self.uid = await db.get_or_create_user(98400, 'split-regression')
        await db.wipe_user(self.uid)
        await db.ensure_training_system_defaults(self.uid)
        self.ctx = api.AuthCtx(user_id=self.uid, tg_id=98400, actor_user_id=self.uid, username='split-regression', first_name=None, last_name=None, auth_date=1)
        api.app.dependency_overrides[api.get_auth_ctx] = lambda: self.ctx
        self.addCleanup(api.app.dependency_overrides.clear)
        awards = patch.object(api, '_evaluate_achievements', AsyncMock())
        awards.start()
        self.addCleanup(awards.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app, raise_app_exceptions=False), base_url='http://test')
        self.addAsyncCleanup(self.client.aclose)
        self.date = datetime.now(UTC).date().isoformat()
        self.ids = [await db.get_or_create_exercise(f'Split exercise {i}', 'chest', self.uid) for i in range(3)]
        for exercise in self.ids:
            response = await self.client.post(f'/all_exercises/exercise/{exercise}/set/add', params={'date':self.date}, json={'weight_kg':40,'reps':8})
            self.assertEqual(response.status_code, 200, response.text)

    async def assert_only_first_done(self):
        groups = (await self.client.get('/all_exercises/groups', params={'date':self.date})).json()
        self.assertEqual([item['exercise_id'] for item in groups['done_today']], self.ids[:1])
        self.assertEqual(groups['unfinished_count'], 2)
        unfinished = (await self.client.get('/all_exercises/unfinished', params={'date':self.date})).json()
        self.assertEqual({item['exercise_id'] for item in unfinished['items']}, set(self.ids[1:]))
        items = (await self.client.get('/all_exercises/group/chest', params={'date':self.date})).json()['items']
        self.assertEqual({item['exercise_id'] for item in items if item['is_done_today']}, set(self.ids[:1]))
        for exercise in self.ids:
            session = (await self.client.get(f'/all_exercises/exercise/{exercise}/session', params={'date':self.date})).json()
            self.assertEqual(session['is_done'], exercise == self.ids[0])
            self.assertEqual(len(session['sets']), 1)

    async def test_split_workout_completion_and_retry_only_finish_selected_exercise(self):
        for _ in range(2):
            response = await self.client.post(f'/all_exercises/exercise/{self.ids[0]}/done', params={'date':self.date})
            self.assertEqual(response.status_code, 200, response.text)
            await self.assert_only_first_done()

    async def test_legacy_finish_day_does_not_complete_other_split_exercises(self):
        response = await self.client.post(f'/all_exercises/exercise/{self.ids[0]}/done', params={'date':self.date})
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.client.post('/all_exercises/finish_day', params={'date':self.date})
        self.assertEqual(response.status_code, 200, response.text)
        await self.assert_only_first_done()

    async def test_empty_sessions_and_notes_are_not_training_activity(self):
        exercise = await db.get_or_create_exercise('Not started', 'chest', self.uid)
        session = (await self.client.get(f'/all_exercises/exercise/{exercise}/session', params={'date':self.date})).json()
        await db.set_exercise_note(session['session_id'], session['user_exercise_id'], 'Plan for later')
        items = await db.build_effective_exercise_index_for_user(self.uid, self.date)
        item = next(item for item in items if item['exercise_id'] == exercise)
        self.assertFalse(item['has_history'])
        self.assertFalse(item['unfinished_today'])
        self.assertIsNone(item['last_activity_at'])
        self.assertIsNone(item['last_done_at'])

    async def test_free_running_save_and_done_leave_strength_exercises_unfinished(self):
        exercise = await db.get_or_create_exercise('Split running', 'run', self.uid)
        url = f'/all_exercises/exercise/{exercise}/running'
        response = await self.client.post(url, params={'date':self.date}, json={'distance_km':3,'duration_ms':900000})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse((await self.client.get(f'/all_exercises/exercise/{exercise}/session', params={'date':self.date})).json()['is_done'])
        groups = (await self.client.get('/all_exercises/groups', params={'date':self.date})).json()
        self.assertEqual(groups['unfinished_count'], 4)
        unfinished = (await self.client.get('/all_exercises/unfinished', params={'date':self.date})).json()
        self.assertEqual({item['exercise_id'] for item in unfinished['items']}, {*self.ids, exercise})
        response = await self.client.post(url+'/done', params={'date':self.date}, json={'distance_km':0})
        self.assertEqual(response.status_code, 400, response.text)
        response = await self.client.post(url+'/done', params={'date':self.date}, json={})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data['unfinished_count'], 3)
        self.assertEqual([item['exercise_id'] for item in data['done_today']], [exercise])
        self.assertEqual(data['running']['distance_km'], 3)
        self.assertEqual(data['running']['duration_ms'], 900000)
        self.assertFalse(data['running']['is_draft'])
        items = (await self.client.get('/all_exercises/group/run', params={'date':self.date})).json()['items']
        self.assertEqual([item['exercise_id'] for item in items if item['is_done_today']], [exercise])


class ApiInputMatrixTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import webapp_backend as api
        self.api = api
        await db.init_db()
        uid = await db.get_or_create_user(98200, 'api-matrix')
        self.ctx = api.AuthCtx(user_id=uid, tg_id=98200, actor_user_id=uid, username='api-matrix', first_name=None, last_name=None, auth_date=1)
        api.app.dependency_overrides[api.get_auth_ctx] = lambda: self.ctx
        self.addCleanup(api.app.dependency_overrides.clear)

    async def test_all_protected_routes_reject_missing_auth(self):
        import httpx
        import re
        self.api.app.dependency_overrides.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app, raise_app_exceptions=False), base_url='http://test') as client:
            checked = 0
            for route in self.api.app.routes:
                if not any(p.call in (self.api.get_auth_ctx, self.api.get_tg_init_data) for p in getattr(getattr(route, 'dependant', None), 'dependencies', [])):
                    continue
                path = re.sub(r'{[^}]+}', '1', route.path)
                for method in route.methods - {'HEAD', 'OPTIONS'}:
                    response = await client.request(method, path, json={})
                    with self.subTest(method=method, path=path):
                        self.assertIn(response.status_code, (401,403), response.text)
                    checked += 1
            self.assertGreaterEqual(checked, 119)

    async def test_all_routes_handle_empty_input_without_unhandled_errors(self):
        import httpx
        import re
        import socket
        from unittest.mock import AsyncMock
        external = {'/subscription/payment/start','/api/payments/redirect/create','/subscription/payment/notify-bot-success','/ai/coach/query'}
        failures = []
        checked = 0
        with patch.object(socket.socket,'connect',side_effect=AssertionError('unexpected network')),patch.object(self.api.Bot,'send_message',AsyncMock()):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app,raise_app_exceptions=False),base_url='http://test') as client:
                for route in self.api.app.routes:
                    if route.path in external or not any(p.call==self.api.get_auth_ctx for p in getattr(getattr(route,'dependant',None),'dependencies',[])):
                        continue
                    path = re.sub(r'{([^}]+)}',lambda m:'99999999' if m[1].endswith('_id') or m[1]=='day_index' else 'audit-missing',route.path)
                    for method in route.methods-{'HEAD','OPTIONS'}:
                        response = await client.request(method,path,json={})
                        if response.status_code>=500:failures.append(f'{method} {path}: {response.text}')
                        checked += 1
        self.maxDiff=None
        self.assertGreaterEqual(checked,110)
        self.assertEqual(failures,[])

    async def test_payload_routes_reject_malformed_scalar_fields_before_side_effects(self):
        import ast
        import httpx
        import inspect
        import re
        import socket
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app, raise_app_exceptions=False), base_url='http://test') as client:
            checked = 0
            with patch.object(socket.socket, 'connect', side_effect=AssertionError('unexpected network')):
                for route in self.api.app.routes:
                    endpoint = getattr(route, 'endpoint', None)
                    if endpoint is None or 'payload' not in inspect.signature(endpoint).parameters:
                        continue
                    node = ast.parse(inspect.getsource(inspect.unwrap(endpoint)))
                    keys = {n.args[0].value for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id=='payload' and n.func.attr=='get' and n.args and isinstance(n.args[0],ast.Constant)}
                    if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == '_save_running_payload' for n in ast.walk(node)):
                        helper = ast.parse(inspect.getsource(self.api._save_running_payload))
                        keys.update(n.args[0].value for n in ast.walk(helper) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == 'payload' and n.func.attr == 'get' and n.args and isinstance(n.args[0], ast.Constant))
                    if not keys:
                        continue
                    path = re.sub(r'{[^}]+}', '9999999', route.path)
                    response = await client.request(next(iter(route.methods)), path, json={k:{'bad':'shape'} for k in keys})
                    with self.subTest(path=path):
                        self.assertLess(response.status_code, 500, response.text)
                    checked += 1
            self.assertGreaterEqual(checked, 36)

    async def test_numeric_path_ids_never_overflow_database_bindings(self):
        import httpx
        import re
        import socket
        checked = 0
        failures = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app,raise_app_exceptions=False),base_url='http://test') as client:
            with patch.object(socket.socket,'connect',side_effect=AssertionError('unexpected network')):
                for route in self.api.app.routes:
                    parameters = getattr(getattr(route,'dependant',None),'path_params',[])
                    numeric = {p.name for p in parameters if p.field_info.annotation is int or getattr(p.field_info.annotation, '__origin__', None) is int}
                    if not numeric:
                        continue
                    for value in (-1,99999999,2**100):
                        path = re.sub(r'{([^}]+)}',lambda m:str(value) if m[1] in numeric else 'audit-missing',route.path)
                        for method in route.methods-{'HEAD','OPTIONS'}:
                            response = await client.request(method,path,json={})
                            if response.status_code >= 500:
                                failures.append(f'{method} {path}: {response.status_code}')
                            checked += 1
        self.assertGreaterEqual(checked,100)
        self.maxDiff = None
        self.assertEqual(failures,[])

    async def test_all_exercise_routes_reject_another_users_private_exercise(self):
        import httpx
        import re
        other = await db.get_or_create_user(98201,'private-api-owner')
        ex = await db.get_or_create_exercise('Private API sentinel','chest',other)
        await db.add_user_exercise(other,1,ex)
        async with db.connect_db() as conn:
            ue = (await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=? AND day_index=1',(other,ex))).fetchone())[0]
        payload = {'name':'Attempted rename','muscle_group':'back','sets':3,'reps':10,'seconds':0,'weight_kg':20,'field':'reps','delta':1,'note':'Attempted note','text':'Attempted note','is_warmup':False,'distance_km':5}
        checked = 0
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app,raise_app_exceptions=False),base_url='http://test') as client:
            for route in self.api.app.routes:
                if not any('{'+key+'}' in route.path for key in ('exercise_id','ue_id','user_exercise_id')):
                    continue
                path = re.sub(r'{([^}]+)}',lambda m:str(ex if m[1]=='exercise_id' else ue if m[1] in ('ue_id','user_exercise_id') else 1),route.path)
                for method in route.methods-{'HEAD','OPTIONS'}:
                    response = await client.request(method,path,json=payload)
                    with self.subTest(method=method,path=path):
                        self.assertIn(response.status_code,(400,403,404,422),response.text)
                        self.assertNotIn('Private API sentinel',response.text)
                    checked += 1
        self.assertGreaterEqual(checked,25)
        self.assertEqual(await db.get_exercise_details(ex),('Private API sentinel','chest',other))
        self.assertEqual(await db.get_user_exercise_info(ue),(other,1))

    async def test_trainer_access_is_limited_to_diary_routes_and_edit_permission(self):
        from starlette.requests import Request
        from fastapi import HTTPException
        from unittest.mock import AsyncMock
        tg = SimpleNamespace(user=SimpleNamespace(id=98200,username='trainer',first_name=None,last_name=None),auth_date=1)
        personal_prefixes = ('/teams','/achievements','/subscription','/api/payments','/all_exercises','/leaderboard')
        with patch.object(self.api.db,'get_or_create_user',AsyncMock(return_value=1)),patch.object(self.api,'ensure_training_system_defaults',AsyncMock()),patch.object(self.api,'get_trainer_link',AsyncMock(return_value=(1,'accepted',1))) as link:
            for route in self.api.app.routes:
                path = route.path
                if not path.startswith(personal_prefixes) and path != '/settings/leaderboard_visibility':
                    continue
                for method in route.methods-{'OPTIONS','HEAD'}:
                    with self.subTest(path=path,method=method),self.assertRaises(HTTPException) as caught:
                        await self.api.get_auth_ctx(Request({'type':'http','path':path,'method':method,'headers':[]}),tg,2)
                    self.assertEqual(caught.exception.status_code,403)
            for editable in (False,True):
                link.return_value=(1,'accepted',int(editable))
                request=Request({'type':'http','path':'/day/1/exercise/1/done','method':'POST','headers':[]})
                if editable:
                    self.assertEqual((await self.api.get_auth_ctx(request,tg,2)).user_id,2)
                else:
                    with self.assertRaises(HTTPException):await self.api.get_auth_ctx(request,tg,2)
                request=Request({'type':'http','path':'/day/1/sheet','method':'GET','headers':[]})
                self.assertEqual((await self.api.get_auth_ctx(request,tg,2)).user_id,2)
            actor_request=Request({'type':'http','path':'/settings/trainer','method':'GET','headers':[]})
            self.assertEqual((await self.api.get_auth_ctx(actor_request,tg,2)).user_id,1)

    async def test_ai_receipt_status_is_owner_scoped_and_read_only(self):
        import json
        token = 'test_receipt_1234567890'
        result = {'ok':True,'system_id':999}
        await db.set_app_meta(f'ai_apply:{self.ctx.user_id}:{token}',json.dumps({'result':result}))
        self.assertEqual(await self.api.ai_coach_apply_status(token,self.ctx),{'found':True,'result':result})
        other = SimpleNamespace(user_id=self.ctx.user_id+999)
        self.assertEqual(await self.api.ai_coach_apply_status(token,other),{'found':False})

    async def test_invalid_numbers_are_rejected_without_writes(self):
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app, raise_app_exceptions=False), base_url='http://test') as client:
            for value in ('NaN','Infinity','1e999',{},[],True,'1.5'):
                response = await client.post('/systems', json={'name':'Bad number','workouts_per_week':value})
                with self.subTest(value=value):
                    self.assertEqual(response.status_code,400,response.text)


class ProgramBaselineIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()
        index = sorted(n for n in dir(self) if n.startswith('test_')).index(self._testMethodName)
        self.uid = await db.get_or_create_user(98300+index,'program-baselines')
        self.a = await db.ensure_training_system_defaults(self.uid)
        self.b = await db.create_training_system(self.uid,'Other baseline program')
        self.ex = await db.get_or_create_exercise('Shared exercise','chest',self.uid)

    async def test_program_switch_restores_each_baseline_and_preserves_source_note(self):
        await db.apply_system_to_current_plan(self.uid,self.a)
        await db.add_user_exercise(self.uid,1,self.ex)
        await db.set_baseline(self.uid,1,self.ex,3,10,0,20)
        await db.upsert_training_system_exercise_source(self.a,1,self.ex,{'note':'Imported note','source_user_id':999})
        await db.sync_current_plan_to_system(self.uid,self.a)
        await db.apply_system_to_current_plan(self.uid,self.b)
        await db.add_user_exercise(self.uid,1,self.ex)
        await db.set_baseline(self.uid,1,self.ex,5,6,0,50)
        await db.sync_current_plan_to_system(self.uid,self.b)
        await db.apply_system_to_current_plan(self.uid,self.a)
        self.assertEqual(await db.get_baseline(self.uid,1,self.ex),(3,10,0,20))
        await db.apply_system_to_current_plan(self.uid,self.b)
        self.assertEqual(await db.get_baseline(self.uid,1,self.ex),(5,6,0,50))
        source = await db.fetch_training_system_exercise_sources(self.a,1)
        self.assertEqual(source[self.ex]['note'],'Imported note')

    async def test_foreign_keep_cannot_delete_programs_and_prune_keeps_history_labels(self):
        other = await db.get_or_create_user(98401,'other-program-owner')
        foreign = await db.ensure_training_system_defaults(other)
        before = await db.list_user_training_system_ids(self.uid)
        with self.assertRaisesRegex(ValueError,'system_not_found'):
            await db.prune_user_training_systems(self.uid,foreign)
        self.assertEqual(await db.list_user_training_system_ids(self.uid),before)
        await db.prune_user_training_systems(self.uid,self.a)
        async with db.connect_db() as conn:
            archived = await (await conn.execute('SELECT name FROM training_systems_archive WHERE system_id=?',(self.b,))).fetchone()
        self.assertEqual(archived,('Other baseline program',))

    async def test_foreign_rename_and_color_report_missing_without_award(self):
        from unittest.mock import AsyncMock
        from fastapi import HTTPException
        import webapp_backend as api
        ctx = SimpleNamespace(user_id=self.uid)
        with patch.object(api,'log_user_event',new_callable=AsyncMock) as event:
            for handler,payload in ((api.systems_rename,{'name':'Foreign'}),(api.systems_color,{'color':'#ffffff'})):
                with self.assertRaises(HTTPException) as caught:
                    await handler(99999999,payload,ctx)
                self.assertEqual(caught.exception.status_code,404)
            event.assert_not_awaited()


class AchievementCatalogIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()
        self.uid = await db.get_or_create_user(98500+sorted(n for n in dir(self) if n.startswith('test_')).index(self._testMethodName),'achievement-catalog')
        self.sid = await db.ensure_training_system_defaults(self.uid)
        async with db.connect_db() as conn:
            await conn.execute('UPDATE users SET leaderboard_visible=0,tz=? WHERE id=?',('UTC',self.uid))
            await conn.commit()

    async def test_empty_diary_has_no_training_or_team_awards(self):
        import achievements_engine as ach
        self.assertEqual((await ach.evaluate(self.uid))['earned_codes'],[])

    async def test_every_catalog_award_can_be_earned_from_stored_training_data_once(self):
        import achievements_engine as ach
        now = datetime.now(UTC).replace(hour=4,minute=0,second=0,microsecond=0)
        others = [await db.get_or_create_user(98600+i,f'achievement-member-{i}') for i in range(15)]
        team = await db.create_team(self.uid,'Achievement catalog team',True)
        tid = team['team_id']
        await db.create_training_system(self.uid,'Catalog program 2')
        await db.create_training_system(self.uid,'Catalog program 3')
        exs = [await db.get_or_create_exercise(f'Catalog exercise {i}','chest',self.uid) for i in range(20)]
        async with db.connect_db() as conn:
            await conn.execute('UPDATE users SET leaderboard_visible=1 WHERE id=?',(self.uid,))
            await conn.execute('UPDATE team_members SET joined_at=? WHERE user_id=?',((now-timedelta(days=31)).isoformat(),self.uid))
            await conn.executemany('INSERT INTO team_members(team_id,user_id,role,joined_at) VALUES(?,?,?,?)',[(tid,u,'private',now.isoformat()) for u in others[:8]])
            await conn.executemany('INSERT INTO team_daily_scores VALUES(?,?,?,?,?,?,?,?)',[(tid,(now-timedelta(days=i)).date().isoformat(),100,1,9,20,120,now.isoformat()) for i in range(30)])
            session = None
            for user in [self.uid,*others[:8]]:
                offsets = [*range(49),63] if user==self.uid else range(12)
                system = self.sid if user==self.uid else 0
                for offset in offsets:
                    stamp=now-timedelta(days=offset)
                    cur=await conn.execute('INSERT INTO sessions(user_id,date,day_index,system_id) VALUES(?,?,?,?)',(user,stamp.date().isoformat(),1,system))
                    if user==self.uid and offset==0: session=cur.lastrowid
                    await conn.execute('INSERT INTO day_completion_history(user_id,system_id,day_index,completed_at) VALUES(?,?,1,?)',(user,system,stamp.isoformat()))
            for ex in exs:
                cur=await conn.execute('INSERT INTO user_exercises(user_id,exercise_id,day_index) VALUES(?,?,1)',(self.uid,ex))
                await conn.execute('INSERT INTO session_exercises(session_id,user_exercise_id,is_done) VALUES(?,?,1)',(session,cur.lastrowid))
                if ex==exs[0]: ue=cur.lastrowid
            await conn.executemany('INSERT INTO sets(session_id,user_exercise_id,set_no,reps,weight_kg,is_warmup) VALUES(?,?,?,?,?,0)',[(session,ue,i+1,5,200) for i in range(500)])
            await conn.execute('INSERT INTO running_entries(user_id,distance_km,is_draft) VALUES(?,42,0)',(self.uid,))
            await conn.executemany('INSERT INTO user_events(user_id,event_type,created_at) VALUES(?,?,?)',[(self.uid,'rename',now.isoformat())]*5)
            await conn.executemany("INSERT INTO trainer_links(trainer_user_id,trainee_user_id,status,created_at) VALUES(?,?,'accepted',?)",[(self.uid,others[0],now.isoformat()),(others[1],self.uid,now.isoformat())])
            copies=[(self.uid,self.sid,u,10000+i,now.isoformat(),now.isoformat()) for i,u in enumerate(others)]
            copies.append((others[0],10000,self.uid,self.sid,now.isoformat(),now.isoformat()))
            await conn.executemany('INSERT INTO training_system_copy_events(source_user_id,source_system_id,target_user_id,target_system_id,copied_at,first_trained_at) VALUES(?,?,?,?,?,?)',copies)
            await conn.commit()
        result = await ach.evaluate(self.uid)
        self.assertEqual(set(result['earned_codes']),set(ach.ACHIEVEMENTS_BY_CODE))
        self.assertEqual(set(await db.list_team_achievements(tid)),set(ach.TEAM_ACHIEVEMENTS_BY_CODE))
        again = await ach.evaluate(self.uid)
        self.assertEqual(again['newly_unlocked_codes'],[])
        self.assertEqual((await ach.evaluate_team(tid))['newly_unlocked_team_codes'],[])

    async def test_copied_program_requires_three_local_dates(self):
        import achievements_engine as ach
        await db.set_user_timezone(self.uid,'Asia/Vladivostok')
        async with db.connect_db() as conn:
            await conn.execute('INSERT INTO training_system_copy_events(source_user_id,source_system_id,target_user_id,target_system_id,copied_at,first_trained_at) VALUES(1,1,?,?,?,?)',(self.uid,self.sid,'2026-01-01','2026-01-01'))
            for stamp in ('2026-01-01T18:00:00+00:00','2026-01-02T01:00:00+00:00','2026-01-03T01:00:00+00:00'):
                await conn.execute('INSERT INTO day_completion_history(user_id,system_id,day_index,completed_at) VALUES(?,?,1,?)',(self.uid,self.sid,stamp))
            await conn.commit()
        self.assertEqual((await ach._fetch_metrics(self.uid))['copied_plan_3days'],0)
        await db.mark_day_completed(self.uid,1,'2026-01-04T01:00:00+00:00',self.sid)
        self.assertEqual((await ach._fetch_metrics(self.uid))['copied_plan_3days'],1)

    async def test_weekly_variety_excludes_eighth_day_and_future_sessions(self):
        import achievements_engine as ach
        today = datetime.now(UTC).date()
        exercises = [await db.get_or_create_exercise(f'Boundary variety {i}', 'chest', self.uid) for i in range(13)]
        async with db.connect_db() as conn:
            for ex, offset in zip(exercises,[0]*10+[6,7,-1]):
                cur = await conn.execute('INSERT INTO user_exercises(user_id,exercise_id,day_index) VALUES(?,?,1)', (self.uid,ex))
                ue = cur.lastrowid
                stamp = (today-timedelta(days=offset)).isoformat()
                await conn.execute('INSERT OR IGNORE INTO sessions(user_id,date,day_index,system_id) VALUES(?,?,1,?)',(self.uid,stamp,self.sid))
                session = (await (await conn.execute('SELECT id FROM sessions WHERE user_id=? AND date=? AND system_id=?',(self.uid,stamp,self.sid))).fetchone())[0]
                await conn.execute('INSERT INTO session_exercises(session_id,user_exercise_id,is_done) VALUES(?,?,1)',(session,ue))
            await conn.commit()
        self.assertEqual((await ach._fetch_metrics(self.uid))['variety_week'],11)
        self.assertNotIn('variety_12_week',(await ach.evaluate(self.uid))['earned_codes'])

    async def test_every_achievement_has_a_negative_and_exact_boundary(self):
        import achievements_engine as ach
        from unittest.mock import AsyncMock
        base = await ach._fetch_metrics(self.uid)
        now = datetime.now(UTC).replace(microsecond=0)
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls,tz=None):return now if tz else now.replace(tzinfo=None)
        cases = {}
        for code,field,threshold in (
            ('first_set','sets_non_warmup',1),('first_day_done','day_done_total',1),
            ('variety_12_week','variety_week',12),('variety_20_week','variety_week',20),
            ('volume_100k','volume',100000),('volume_500k','volume',500000),
            ('sets_500','sets_non_warmup',500),('run_10km','run_km',10),('run_42km','run_km',42),
            ('rename_master','rename_count',5),('copied_plan_3days','copied_plan_3days',1),
            ('inspired_3','inspired',3),('arnold_15','inspired',15),('coach_1','accepted_trainees',1),
            ('day_done_50','day_done_total',50),('team_month_top1','team_top1_streak_days',30),
            ('team_consistency','team_sessions_per_member_28',12),('team_night_ops','team_night_sessions_28',6)):
            cases[code]=[({field:threshold-1},False),({field:threshold},True),({field:threshold+1},True)]
        for code,days in (('streak_7',7),('streak_21',21)):
            cases[code]=[({'local_completions':[now-timedelta(days=i) for i in range(n)]},n>=days) for n in (days-1,days,days+1)]
        cases['plan_architect']=[({'systems_count':2,'active_user_exercises':29},False),({'systems_count':3},True),({'active_user_exercises':30},True)]
        cases['leaderboard_on']=[({'leaderboard_visible':False},False),({'leaderboard_visible':True},True)]
        cases['team_joined']=[({'team_id':None},False),({'team_id':1},True)]
        cases['team_founder']=[({'team_is_founder':False},False),({'team_is_founder':True},True)]
        cases['apprentice_10']=[({'accepted_trainer_links':1,'day_done_total':9},False),({'accepted_trainer_links':0,'day_done_total':10},False),({'accepted_trainer_links':1,'day_done_total':10},True)]
        cases['comeback_14']=[({'local_completions':[now,now-timedelta(days=n)]},n>=14) for n in (13,14,15)]
        cases['night_shift']=[({'local_completions':[now.replace(hour=h,minute=m)]},ok) for h,m,ok in ((4,59,True),(5,0,False),(22,59,False),(23,0,True))]
        cases['team_full_roster']=[({'team_id':1,'team_members_count':7},False),({'team_id':None,'team_members_count':8},False),({'team_id':1,'team_members_count':8},True)]
        for code,rank in (('team_top10_week',10),('team_top3_week',3),('team_top1_week',1)):
            cases[code]=[({'team_best_rank_7':n},ok) for n,ok in ((None,False),(0,False),(rank+1,False),(rank,True))]
        for code,count in (('team_recruit_3',3),('team_recruit_8',8)):
            cases[code]=[({'team_role':'captain','captain_recruits_count':count-1},False),({'team_role':'private','captain_recruits_count':count},False),({'team_role':'captain','captain_recruits_count':count},True)]
        cases['team_loyal_30']=[({'team_id':1,'team_joined_at':(now-timedelta(days=30)+timedelta(seconds=offset)).isoformat()},offset<=0) for offset in (1,0,-1)]
        self.assertEqual(set(cases),set(ach.ACHIEVEMENTS_BY_CODE))
        with patch.object(ach,'datetime',FrozenDateTime),patch.object(ach.db,'list_user_achievements',AsyncMock(return_value=[])),patch.object(ach.db,'grant_achievement',AsyncMock(return_value=True)),patch.object(ach,'evaluate_team',AsyncMock()):
            for code,checks in cases.items():
                for changes,expected in checks:
                    with self.subTest(code=code,changes=changes),patch.object(ach,'_fetch_metrics',AsyncMock(return_value={**base,**changes})):
                        self.assertEqual(code in (await ach.evaluate(self.uid))['earned_codes'],expected)
        team_base = {'members_count':0,'active_members_7d':0,'sessions_28':0,'night_sessions_28':0,'best_rank_7':None,'top1_streak_days':0,'top3_days_28':0}
        team_cases = {
            't_foundation':[({'members_count':0},False),({'members_count':1},True)],
            't_full_roster':[({'members_count':7},False),({'members_count':8},True)],
            't_active_core':[({'members_count':5,'active_members_7d':5},False),({'members_count':6,'active_members_7d':4},False),({'members_count':6,'active_members_7d':5},True)],
            't_top1_month':[({'top1_streak_days':29},False),({'top1_streak_days':30},True)],
            't_consistency_28':[({'members_count':3,'sessions_28':35},False),({'members_count':3,'sessions_28':36},True)],
            't_night_ops':[({'members_count':2,'night_sessions_28':12},False),({'members_count':3,'night_sessions_28':11},False),({'members_count':3,'night_sessions_28':12},True)],
            't_web_of_power':[({'members_count':7,'top3_days_28':21},False),({'members_count':8,'top3_days_28':20},False),({'members_count':8,'top3_days_28':21},True)],
        }
        for code,rank in (('t_top10_week',10),('t_top3_week',3),('t_top1_week',1)):
            team_cases[code]=[({'best_rank_7':n},ok) for n,ok in ((None,False),(0,False),(rank+1,False),(rank,True))]
        self.assertEqual(set(team_cases),set(ach.TEAM_ACHIEVEMENTS_BY_CODE))
        with patch.object(ach.db,'list_team_achievements',AsyncMock(return_value=[])),patch.object(ach.db,'grant_team_achievement',AsyncMock(return_value=True)):
            for code,checks in team_cases.items():
                for changes,expected in checks:
                    with self.subTest(code=code,changes=changes):
                        self.assertEqual(code in (await ach.evaluate_team(1,metrics={**team_base,**changes}))['earned_team_codes'],expected)

    async def test_daily_ranking_snapshot_removes_teams_that_left_the_top(self):
        import achievements_engine as ach
        team = await db.create_team(self.uid,'Snapshot team')
        tid = team['team_id']
        today = datetime.now(UTC).date()
        for offset in range(30):
            await db.upsert_team_daily_scores((today-timedelta(days=offset)).isoformat(),[{'team_id':tid,'rank':1}])
        self.assertEqual((await ach._fetch_team_metrics(tid))['top1_streak_days'],30)
        await db.upsert_team_daily_scores(today.isoformat(),[{'team_id':tid+1,'rank':1}])
        self.assertEqual((await ach._fetch_team_metrics(tid))['top1_streak_days'],0)
        await db.upsert_team_daily_scores(today.isoformat(),[])
        async with db.connect_db() as conn:
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM team_daily_scores WHERE day_utc=?',(today.isoformat(),))).fetchone())[0],0)
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM team_daily_scores WHERE team_id=?',(tid,))).fetchone())[0],29)

    async def test_calendar_boundaries_match_across_awards_and_rankings(self):
        import achievements_engine as ach
        from zoneinfo import ZoneInfo
        team = await db.create_team(self.uid,'Calendar boundary team')
        tid = team['team_id']
        ex = await db.get_or_create_exercise('Boundary press','chest',self.uid)
        await db.add_user_exercise(self.uid,1,ex)
        async with db.connect_db() as conn:
            ue = (await (await conn.execute('SELECT id FROM user_exercises WHERE user_id=? AND exercise_id=?',(self.uid,ex))).fetchone())[0]
            await conn.execute('UPDATE users SET leaderboard_visible=1 WHERE id=?',(self.uid,))
            await conn.commit()
        for tz_name in ('Etc/GMT+12','Etc/GMT-14'):
            with self.subTest(timezone=tz_name):
                await db.set_user_timezone(self.uid,tz_name)
                today = datetime.now(UTC).astimezone(ZoneInfo(tz_name)).date()
                async with db.connect_db() as conn:
                    await conn.execute('DELETE FROM sets WHERE session_id IN (SELECT id FROM sessions WHERE user_id=?)',(self.uid,))
                    await conn.execute('DELETE FROM session_exercises WHERE session_id IN (SELECT id FROM sessions WHERE user_id=?)',(self.uid,))
                    await conn.execute('DELETE FROM sessions WHERE user_id=?',(self.uid,))
                    await conn.execute('DELETE FROM day_completion_history WHERE user_id=?',(self.uid,))
                    for offset in (0,6,7,27,28,55,56,-1):
                        day = today-timedelta(days=offset)
                        stamp = datetime.combine(day,datetime.min.time(),ZoneInfo(tz_name)).astimezone(UTC).isoformat()
                        cur = await conn.execute('INSERT INTO sessions(user_id,date,day_index,system_id) VALUES(?,?,1,?)',(self.uid,day.isoformat(),self.sid))
                        session = cur.lastrowid
                        await conn.execute('INSERT INTO day_completion_history(user_id,system_id,day_index,completed_at) VALUES(?,?,1,?)',(self.uid,self.sid,stamp))
                        await conn.execute('INSERT INTO session_exercises(session_id,user_exercise_id,is_done) VALUES(?,?,1)',(session,ue))
                        await conn.execute('INSERT INTO sets(session_id,user_exercise_id,set_no,reps,weight_kg) VALUES(?,?,1,5,20)',(session,ue))
                    await conn.commit()
                metrics = await ach._fetch_team_metrics(tid)
                self.assertEqual((metrics['sessions_7'],metrics['sessions_28'],metrics['night_sessions_28']),(2,4,4))
                _,_,teams = await db.fetch_team_leaderboard()
                row = next(r for r in teams if r['team_id']==tid)
                self.assertEqual((row['sessions_7'],row['sessions_28']),(2,4))
                _,_,people = await db.fetch_productivity_leaderboard()
                row = next(r for r in people if r['user_id']==self.uid)
                self.assertEqual((row['sessions_28'],row['training_days_28'],row['sets_28'],row['volume_28']),(4,4,4,400))
                profile = await db.fetch_team_profile(tid,self.uid)
                member = next(r for r in profile['members'] if r['user_id']==self.uid)
                self.assertEqual(member['sessions_28'],4)
                self.assertEqual(row['training_weeks_8'],5)

    async def test_expired_and_future_rankings_do_not_unlock_weekly_awards(self):
        import achievements_engine as ach
        team = await db.create_team(self.uid,'Expired rank team')
        tid = team['team_id']
        now = datetime.now(UTC)
        async with db.connect_db() as conn:
            for offset in (7,28,-1):
                await conn.execute('INSERT INTO team_daily_scores VALUES(?,?,?,?,?,?,?,?)',(tid,(now-timedelta(days=offset)).date().isoformat(),100,1,1,1,1,now.isoformat()))
            await conn.commit()
        metrics = await ach._fetch_team_metrics(tid)
        self.assertIsNone(metrics['best_rank_7'])
        self.assertEqual(metrics['top3_days_28'],1)
        self.assertNotIn('t_top1_week',(await ach.evaluate_team(tid))['earned_team_codes'])
        self.assertNotIn('team_top1_week',(await ach.evaluate(self.uid))['earned_codes'])


class ProductivityWindowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()
        self.uid=await db.get_or_create_user(98900+sorted(n for n in dir(self) if n.startswith('test_')).index(self._testMethodName),'ranking-window')

    async def test_opening_an_empty_workout_does_not_count_as_training(self):
        await db.get_or_create_today_session(self.uid,datetime.now(UTC).date().isoformat(),1,0)
        _,_,full=await db.fetch_productivity_leaderboard()
        row=next(x for x in full if x['user_id']==self.uid)
        self.assertEqual((row['sessions_28'],row['training_days_28'],row['training_weeks_8']),(0,0,0))

    async def test_old_activity_counts_in_eight_weeks_but_not_twenty_eight_days(self):
        old=(datetime.now(UTC)-timedelta(days=45)).date().isoformat()
        session=await db.get_or_create_today_session(self.uid,old,1,0)
        async with db.connect_db() as conn:
            await conn.execute('INSERT INTO session_exercises(session_id,user_exercise_id,is_done) VALUES(?,999999,1)',(session,))
            await conn.commit()
        _,_,full=await db.fetch_productivity_leaderboard()
        row=next(x for x in full if x['user_id']==self.uid)
        self.assertEqual((row['sessions_28'],row['training_days_28'],row['training_weeks_8']),(0,0,1))


if __name__ == "__main__":
    unittest.main()
