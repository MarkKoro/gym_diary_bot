import atexit
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


class OnboardingResetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()
        self.user_id = await db.get_or_create_user(123456789, "tester")

    async def test_wipe_user_clears_onboarding_flags_and_messages(self):
        await db.set_onboarding_video_message(self.user_id, 1001, 2002)
        await db.set_onboarding_intro_message(self.user_id, 3003, 4004)
        await db.set_onboarding_completed(self.user_id, True)

        await db.wipe_user(self.user_id)

        video_chat_id, video_message_id = await db.get_onboarding_video_message(self.user_id)
        intro_chat_id, intro_message_id = await db.get_onboarding_intro_message(self.user_id)
        completed = await db.is_onboarding_completed(self.user_id)
        settings_row = await db.fetch_user_settings(self.user_id)

        self.assertIsNone(video_chat_id)
        self.assertIsNone(video_message_id)
        self.assertIsNone(intro_chat_id)
        self.assertIsNone(intro_message_id)
        self.assertFalse(completed)
        self.assertIsNotNone(settings_row)
        self.assertIsNone(settings_row[1])

    async def test_wipe_does_not_restore_old_program_or_keep_completion_history(self):
        other = await db.get_or_create_user(123456780, 'other')
        exercise = await db.get_or_create_exercise('Reset program exercise', 'chest')
        systems = {}
        for user in (self.user_id, other):
            systems[user] = await db.get_active_training_system_id(user)
            await db.add_user_exercise(user, 1, exercise)
            async with db.connect_db() as conn:
                await conn.execute('INSERT OR REPLACE INTO training_system_exercises(system_id,day_index,exercise_id) VALUES(?,1,?)', (systems[user], exercise))
                await conn.execute('INSERT INTO day_completion_history(user_id,system_id,day_index,completed_at) VALUES(?,?,1,?)', (user, systems[user], '2026-09-24T12:00:00+00:00'))
                await conn.execute('INSERT INTO exercise_notes(user_id,exercise_id,note) VALUES(?,?,?)', (user, exercise, 'Personal note'))
                await conn.commit()
        await db.wipe_user(self.user_id)
        new_system = await db.get_active_training_system_id(self.user_id)
        self.assertNotEqual(new_system, systems[self.user_id])
        async with db.connect_db() as conn:
            for table in ('day_completion_history', 'exercise_notes'):
                self.assertIsNone(await (await conn.execute(f'SELECT 1 FROM {table} WHERE user_id=?', (self.user_id,))).fetchone())
                self.assertIsNotNone(await (await conn.execute(f'SELECT 1 FROM {table} WHERE user_id=?', (other,))).fetchone())
            self.assertIsNone(await (await conn.execute('SELECT 1 FROM training_system_exercises WHERE system_id=?', (systems[self.user_id],))).fetchone())
            self.assertIsNotNone(await (await conn.execute('SELECT 1 FROM training_system_exercises WHERE system_id=?', (systems[other],))).fetchone())
            self.assertIsNone(await (await conn.execute('SELECT 1 FROM user_exercises WHERE user_id=? AND is_archived=0', (self.user_id,))).fetchone())


if __name__ == "__main__":
    unittest.main()
