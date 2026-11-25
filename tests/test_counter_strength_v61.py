"""Проверки диапазона просветов v6.1 без API и без интерфейса."""
import unittest

from fontTools.pens.ttGlyphPen import TTGlyphPen

from engine.advanced_generator import AdvancedConfig
from engine.counter_geometry import change_counter_size_uniform


def ring(stroke=100):
    """Синтетическая O с настраиваемой толщиной обводки."""
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((0, 500))
    pen.lineTo((500, 500))
    pen.lineTo((500, 0))
    pen.closePath()
    pen.moveTo((stroke, stroke))
    pen.lineTo((500 - stroke, stroke))
    pen.lineTo((500 - stroke, 500 - stroke))
    pen.lineTo((stroke, 500 - stroke))
    pen.closePath()
    return pen.glyph()


class CounterStrengthTests(unittest.TestCase):
    def test_range_and_rejections(self):
        for value in (0.7, 1.0, 1.3):
            self.assertEqual(AdvancedConfig.from_dict({"counter_scale": value}).counter_scale, value)
        for value in (0.69, 1.31, float("nan"), "1.25"):
            with self.assertRaises(ValueError):
                AdvancedConfig.from_dict({"counter_scale": value})

    def test_0_70_shrinks_hole_more_than_0_80(self):
        results = []
        for factor in (0.7, 0.8):
            glyph = ring(100)
            stats = {}
            self.assertEqual(change_counter_size_uniform(glyph, factor, stats=stats), 1)
            self.assertGreaterEqual(stats["effective_scale"], factor)
            hole = glyph.coordinates[4:8]
            results.append(max(x for x, y in hole) - min(x for x, y in hole))
        self.assertLess(results[0], results[1])

    def test_1_30_expands_hole_more_than_1_20(self):
        results = []
        for factor in (1.2, 1.3):
            glyph = ring(150)
            stats = {}
            self.assertEqual(change_counter_size_uniform(glyph, factor, stats=stats), 1)
            self.assertLessEqual(stats["effective_scale"], factor)
            hole = glyph.coordinates[4:8]
            results.append(max(x for x, y in hole) - min(x for x, y in hole))
        self.assertGreaterEqual(results[1], results[0])

    def test_hairline_still_protected(self):
        glyph = ring(10)
        before = list(glyph.coordinates)
        stats = {}
        change_counter_size_uniform(glyph, 1.3, stats=stats)
        self.assertLessEqual(stats.get("effective_scale", 1), 1.05)
        self.assertTrue(stats.get("limited", 0))
        self.assertEqual(glyph.coordinates[:4], before[:4])


if __name__ == "__main__":
    unittest.main()
