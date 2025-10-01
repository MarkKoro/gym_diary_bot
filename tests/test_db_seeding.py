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
from text_utils import normalize_whitespace  # noqa: E402


class DbSeedingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await db.init_db()

    async def test_kettlebell_seed_is_idempotent(self):
        await db.init_db()
        async with db.connect_db() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM exercises WHERE name=?",
                ("Махи гирей (русские)",),
            )
            count = (await cur.fetchone())[0]
        self.assertEqual(count, 1)

    async def test_normalized_name_reuses_existing_entry(self):
        base_name = normalize_whitespace("  Своя   гиря  ")
        first_id = await db.get_or_create_exercise(base_name, "kb")
        second_id = await db.get_or_create_exercise(
            normalize_whitespace("Своя гиря"), "kb"
        )
        self.assertEqual(first_id, second_id)


if __name__ == "__main__":
    unittest.main()
