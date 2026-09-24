import atexit
import asyncio
import importlib
import os
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
