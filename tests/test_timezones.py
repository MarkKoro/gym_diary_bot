import atexit
import importlib
import os
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo


if "DB_PATH" not in os.environ:
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    atexit.register(lambda: os.path.exists(tmp_db.name) and os.remove(tmp_db.name))
    os.environ["DB_PATH"] = tmp_db.name
    import settings  # noqa: E402

    importlib.reload(settings)

import db  # noqa: E402
import bot  # noqa: E402


class TimezoneBehaviourTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()
        self.user_id = await db.get_or_create_user(99999, "tz_test")

    async def test_local_date_uses_selected_timezone(self):
        await db.set_user_timezone(self.user_id, "Europe/Moscow")
        expected = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")
        actual = await bot.get_user_local_date(self.user_id)
        self.assertEqual(actual, expected)

    async def test_local_date_falls_back_to_utc_when_invalid(self):
        await db.set_user_timezone(self.user_id, "Mars/Phobos")
        expected = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d")
        actual = await bot.get_user_local_date(self.user_id)
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
