import unittest

from text_utils import normalize_whitespace


class NormalizeWhitespaceTests(unittest.TestCase):
    def test_collapse_internal_spaces(self):
        self.assertEqual(normalize_whitespace("  Жим   гири  "), "Жим гири")

    def test_empty_string_returns_empty(self):
        self.assertEqual(normalize_whitespace("   \t  "), "")


if __name__ == "__main__":
    unittest.main()
