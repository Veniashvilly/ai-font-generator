"""Тесты оптимизированного безопасного масштаба просветов v4."""
import unittest

from fontTools.pens.ttGlyphPen import TTGlyphPen

from engine.advanced_effects import change_counter_size, _contours
from engine.counter_geometry import _polyline_clearance


def ring(border=10):
    pen = TTGlyphPen(None)
    def contour(points):
        pen.moveTo(points[0])
        for p in points[1:]:
            pen.lineTo(p)
        pen.closePath()
    contour([(0, 0), (0, 500), (500, 500), (500, 0)])
    contour([(border, border), (500-border, border),
             (500-border, 500-border), (border, 500-border)])
    return pen.glyph()


class OptimizedCounterTests(unittest.TestCase):
    def test_very_thin_shrink_is_limited(self):
        glyph = ring(10)
        original = _contours(glyph)[1][3]
        stats = {}
        change_counter_size(glyph, 0.8, 1000, stats)
        changed = _contours(glyph)[1][3]
        ratio = (changed[2]-changed[0]) / (original[2]-original[0])
        # Грубо сохранить тонкий штрих, не превращать Hairline в Black.
        self.assertGreater(ratio, 0.97)
        self.assertGreater(stats.get("limited", 0), 0)

    def test_standard_hole_expands(self):
        glyph = ring(100)
        original = _contours(glyph)[1][3]
        count = change_counter_size(glyph, 1.2, 1000)
        changed = _contours(glyph)[1][3]
        self.assertEqual(count, 1)
        self.assertGreater(changed[2]-changed[0], original[2]-original[0])

    def test_point_segment_distance(self):
        a = [(0, 0), (0, 100), (100, 100), (100, 0)]
        b = [(120, 0), (120, 100), (220, 100), (220, 0)]
        self.assertAlmostEqual(_polyline_clearance(a, b), 20.0)

    def test_unmodified_counter_is_fast_path(self):
        glyph = ring(100)
        before = list(glyph.coordinates)
        self.assertEqual(change_counter_size(glyph, 1.0, 1000), 0)
        self.assertEqual(before, list(glyph.coordinates))


if __name__ == "__main__":
    unittest.main()
