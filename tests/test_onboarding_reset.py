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


if __name__ == "__main__":
    unittest.main()
