"""Простой самостоятельный тест структуры GUI без реального GigaChat.

Запускать в корне проекта:
    python tests_gui.py
Для настоящего TTF нужны исходные файлы в fonts/base.
"""
import unittest
from unittest.mock import patch

from gui.controls import SLIDER_CONFIG
from gui.tasks import make_draft_preview


class GUIConfigTests(unittest.TestCase):
    def test_fields_match_existing_engine(self):
        self.assertEqual(set(SLIDER_CONFIG), {"width", "slant", "spacing"})

    def test_temp_preview_does_not_call_generate_from_spec(self):
        # Действительно важный контракт: движение ползунка НЕ добавляет
        # новую постоянную генерацию output/.
        with patch("gui.tasks.normalize_spec", return_value={
            "base_font": "Example/Test.ttf", "width": 0.8,
            "slant": 1, "spacing": 4, "script": "latin"
        }), patch("gui.tasks.transform_ttf", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError):
                make_draft_preview({"width": 0.8})


if __name__ == "__main__":
    unittest.main()
