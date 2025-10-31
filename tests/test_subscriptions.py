import atexit
import importlib
import os
import tempfile
import unittest


tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db.close()
atexit.register(lambda: os.path.exists(tmp_db.name) and os.remove(tmp_db.name))

os.environ["DB_PATH"] = tmp_db.name

import settings  # noqa: E402
importlib.reload(settings)
import db  # noqa: E402
importlib.reload(db)


class SubscriptionDbTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()

    async def asyncTearDown(self):
        async with db.connect_db() as conn:
            for table in ("subscriptions", "payments", "users"):
                await conn.execute(f"DELETE FROM {table}")
            await conn.commit()

    async def test_grant_subscription_extends_current(self):
        user_id = await db.get_or_create_user(7001, "active_user")
        first_expiry = await db.grant_subscription_days(user_id, 30, plan="month")
        second_expiry = await db.grant_subscription_days(user_id, 30, plan="month")
        self.assertGreater(second_expiry, first_expiry)
        info = await db.get_active_subscription(user_id)
        self.assertIsNotNone(info)
        self.assertIsNotNone(info["expires_at"])
        self.assertAlmostEqual(
            info["expires_at"].timestamp(), second_expiry.timestamp(), delta=1
        )

    async def test_list_broadcast_targets_filters_admins_and_subscription(self):
        active_user = await db.get_or_create_user(7100, "with_sub")
        free_user = await db.get_or_create_user(7200, "without_sub")
        await db.grant_subscription_days(active_user, 30, plan="month")
        targets = await db.list_broadcast_targets(set())
        tg_ids = {tg for tg, _ in targets}
        self.assertIn(7200, tg_ids)
        self.assertIn(7100, tg_ids)
        free_only = await db.list_broadcast_targets(set(), only_without_subscription=True)
        free_ids = {tg for tg, _ in free_only}
        self.assertIn(7200, free_ids)
        self.assertNotIn(7100, free_ids)
        admin_filtered = await db.list_broadcast_targets({7200})
        admin_tg_ids = {tg for tg, _ in admin_filtered}
        self.assertNotIn(7200, admin_tg_ids)
        self.assertIn(7100, admin_tg_ids)


if __name__ == "__main__":
    unittest.main()
