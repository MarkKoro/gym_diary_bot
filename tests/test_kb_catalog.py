import unittest

from kb_catalog import (
    KB_CATEGORY_DEFINITION,
    KB_CATEGORY_LOOKUP,
    KB_MISC_CATEGORY,
    KB_EXERCISE_NAMES,
    categorize_kb_exercises,
    get_kb_catalog_page,
)


class KettlebellCatalogTests(unittest.TestCase):
    def test_known_exercises_follow_defined_order(self):
        indexed = list(enumerate(KB_EXERCISE_NAMES, start=1))
        blocks, page, total = get_kb_catalog_page(indexed, per_page=200)
        expected_keys = [key for key, _ in KB_CATEGORY_DEFINITION]
        actual_keys = [key for key, _ in blocks]
        self.assertEqual(page, 0)
        self.assertEqual(total, 1)
        self.assertEqual(actual_keys, expected_keys)

    def test_unknown_exercises_go_to_misc_sorted(self):
        items = [(1, "Зарядка Б"), (2, "зарядка А")]
        blocks = categorize_kb_exercises(items)
        self.assertEqual(len(blocks), 1)
        key, rows = blocks[0]
        self.assertEqual(key, KB_MISC_CATEGORY)
        self.assertEqual([name for _, name in rows], ["зарядка А", "Зарядка Б"])

    def test_lookup_has_all_seeded_exercises(self):
        for name in KB_EXERCISE_NAMES:
            self.assertIn(name, KB_CATEGORY_LOOKUP)


if __name__ == "__main__":
    unittest.main()
