"""Регрессии защиты сложных/декоративных TTF; без запросов к GigaChat."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from engine.advanced_generator import AdvancedConfig, generate_advanced
from engine.counter_geometry import change_counter_size_uniform


def heavy_glyph():
    """Десятки раздельных штрихов — как в кистевом шрифте с крапинками."""
    pen = TTGlyphPen(None)
    for k in range(40):
        x = 16 * k
        pen.moveTo((x, 0))
        pen.lineTo((x + 12, 0))
        pen.lineTo((x + 12, 180))
        pen.lineTo((x, 180))
        pen.closePath()
    return pen.glyph()


class OrnateSafetyTests(unittest.TestCase):
    def test_complex_counter_is_skipped_quickly(self):
        glyph = heavy_glyph()
        before = list(glyph.coordinates)
        stats = {}
        start = time.monotonic()
        self.assertEqual(change_counter_size_uniform(glyph, 1.3, stats=stats), 0)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertEqual(before, list(glyph.coordinates))
        self.assertTrue(stats.get("complexity_skipped"))

    def test_normal_glyph_still_changes(self):
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0)); pen.lineTo((0, 400))
        pen.lineTo((400, 400)); pen.lineTo((400, 0)); pen.closePath()
        pen.moveTo((100, 100)); pen.lineTo((300, 100))
        pen.lineTo((300, 300)); pen.lineTo((100, 300)); pen.closePath()
        glyph = pen.glyph()
        self.assertEqual(change_counter_size_uniform(glyph, .8), 1)

    def test_limits_keep_json_contract(self):
        spec = AdvancedConfig.from_dict({"counter_scale": 1.3, "weight_scale": 1.2, "corner_roundness": .2})
        self.assertEqual(spec.counter_scale, 1.3)
        with self.assertRaises(ValueError):
            AdvancedConfig.from_dict({"counter_scale": 1.31})

    def test_gui_uses_terminable_process(self):
        from advanced_gui import AdvancedEditor
        with patch("advanced_gui.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 40)):
            with self.assertRaisesRegex(RuntimeError, "остановлена"):
                AdvancedEditor._work(Path("dummy.ttf"), AdvancedConfig())

    def test_worker_real_ttf(self):
        source = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        if not source.is_file():
            self.skipTest("Системный DejaVu отсутствует")
        with tempfile.TemporaryDirectory() as folder:
            destination = generate_advanced(source, output_root=folder,
                                            config=AdvancedConfig(counter_scale=1.18, weight_scale=1.1, serif_style="none"))
            with TTFont(destination) as font:
                self.assertIn(ord("О"), font.getBestCmap())
            report = json.loads((destination.parent / "advanced_report.json").read_text(encoding="utf-8"))
            self.assertIn("counter_complexity_skipped", report)
            self.assertIn("effect_complexity_skipped", report)


if __name__ == "__main__":
    unittest.main()
