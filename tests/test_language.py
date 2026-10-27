"""Быстрые автоматические тесты без ключа GigaChat (запуск: python -m unittest discover -s tests)."""

import unittest
from engine.language import LATIN, CYRILLIC, detect_script, missing_chars, coverage


class LanguageTests(unittest.TestCase):
    def test_requests(self):
        self.assertEqual(detect_script("Только английский текст"), "latin")
        self.assertEqual(detect_script("Нужен русский язык"), "cyrillic")
        self.assertEqual(detect_script("Русский и английский"), "both")
        self.assertEqual(detect_script("Узкий футуристичный шрифт"), "auto")

    def test_full_language_coverage(self):
        english = {ord(ch): ch for ch in LATIN}
        both = {ord(ch): ch for ch in LATIN + CYRILLIC}
        self.assertTrue(coverage(english)["latin"])
        self.assertFalse(coverage(english)["cyrillic"])
        self.assertFalse(missing_chars(both, "both"))
        self.assertIn("ё", missing_chars(english, "cyrillic"))


if __name__ == "__main__":
    unittest.main()
