"""Тесты новой геометрии v6. Не требуют GigaChat или пользовательских TTF."""
import unittest
from fontTools.pens.ttGlyphPen import TTGlyphPen
from engine.advanced_effects import _flatten, _horizontal_intervals
from engine.stroke_effects import change_weight, round_corners
from engine.counter_geometry import change_counter_size_uniform


def make_H():
    pen = TTGlyphPen(None)
    vertices = [(0, 0), (60, 0), (60, 220), (260, 220),
                (260, 0), (320, 0), (320, 600), (260, 600),
                (260, 280), (60, 280), (60, 600), (0, 600)]
    pen.moveTo(vertices[0])
    for point in vertices[1:]:
        pen.lineTo(point)
    pen.closePath()
    return pen.glyph()


def make_O():
    pen = TTGlyphPen(None)
    # Внешний контур по часовой стрелке, внутренний — против.
    pen.moveTo((0, 0)); pen.lineTo((0, 400)); pen.lineTo((400, 400))
    pen.lineTo((400, 0)); pen.closePath()
    pen.moveTo((100, 100)); pen.lineTo((300, 100))
    pen.lineTo((300, 300)); pen.lineTo((100, 300)); pen.closePath()
    return pen.glyph()


class StrokeQualityV6Tests(unittest.TestCase):
    def test_weight_thickens_stems_of_H_without_holes(self):
        glyph = make_H()
        before = _horizontal_intervals(_flatten(glyph), 360)
        count = change_weight(glyph, 1.30)
        after = _horizontal_intervals(_flatten(glyph), 360)
        self.assertEqual(count, 1)
        self.assertGreater(after[0][1] - after[0][0], before[0][1] - before[0][0])
        self.assertGreater(after[1][1] - after[1][0], before[1][1] - before[1][0])

    def test_weight_hole_is_reduced_not_expanded(self):
        glyph = make_O()
        original = glyph.coordinates[4:8]
        count = change_weight(glyph, 1.30)
        updated = glyph.coordinates[4:8]
        self.assertEqual(count, 2)
        self.assertLess(max(x for x,y in updated)-min(x for x,y in updated),
                        max(x for x,y in original)-min(x for x,y in original))

    def test_rounding_adds_true_qcurve_controls(self):
        glyph = make_H()
        count_before = len(glyph.coordinates)
        curves_before = sum((flag & 1) == 0 for flag in glyph.flags)
        rounded = round_corners(glyph, .35)
        self.assertGreater(rounded, 0)
        self.assertGreater(len(glyph.coordinates), count_before)
        self.assertGreater(sum((flag & 1) == 0 for flag in glyph.flags), curves_before)

    def test_shrinking_hole_has_visible_effect(self):
        glyph = make_O()
        original = glyph.coordinates[4:8]
        stats = {}
        changed = change_counter_size_uniform(glyph, .80, stats=stats)
        updated = glyph.coordinates[4:8]
        self.assertEqual(changed, 1)
        self.assertLess(max(x for x,y in updated)-min(x for x,y in updated),
                        max(x for x,y in original)-min(x for x,y in original))
        self.assertLessEqual(stats["effective_scale"], .85)


if __name__ == '__main__':
    unittest.main()
