"""Геометрические тесты единого ползунка, без GigaChat."""
import unittest
from fontTools.pens.ttGlyphPen import TTGlyphPen

from engine.advanced_effects import change_counter_size, _contours
from engine.advanced_ai_contract import merge_ai_patch


def make_glyph(outline, holes):
    pen=TTGlyphPen(None)
    # Противоположный обход: внешний — clockwise, отверстия — ccw.
    def add(poly):
        pen.moveTo(poly[0])
        for pt in poly[1:]: pen.lineTo(pt)
        pen.closePath()
    add(outline)
    for hole in holes: add(hole)
    return pen.glyph()


class CounterTests(unittest.TestCase):
    def test_all_holes_of_b_scale_together(self):
        # Глиф с двумя внутренними отверстиями (как у B).
        glyph=make_glyph(
            [(0,0),(0,900),(600,900),(600,0)],
            [[(100,500),(480,500),(480,810),(100,810)],
             [(100,100),(480,100),(480,400),(100,400)]],
        )
        before=[c[3] for c in _contours(glyph)]
        stats={}
        count=change_counter_size(glyph,1.2,em=1000,stats=stats)
        after=[c[3] for c in _contours(glyph)]
        self.assertEqual(count,2)
        self.assertEqual(stats["holes_found"],2)
        # Равный коэффициент для верхнего и нижнего отверстия.
        factors=[(after[i][2]-after[i][0])/(before[i][2]-before[i][0]) for i in (1,2)]
        self.assertAlmostEqual(factors[0],factors[1],places=2)

    def test_triangle_hole_uses_same_slider(self):
        # А с треугольным просветом.
        glyph=make_glyph(
            [(0,0),(300,850),(600,0)],
            [[(230,240),(370,240),(300,460)]],
        )
        stats={}
        count=change_counter_size(glyph,0.8,em=1000,stats=stats)
        self.assertEqual(count,1)
        self.assertLess(stats["effective_scale"],1)

    def test_extra_thin_is_protected(self):
        glyph=make_glyph(
            [(0,0),(0,700),(500,700),(500,0)],
            [[(12,12),(488,12),(488,688),(12,688)]],
        )
        stats={}
        self.assertEqual(change_counter_size(glyph,1.2,1000,stats),0)
        self.assertEqual(stats["skipped"],1)

    def test_future_ai_uses_one_counter_parameter(self):
        base={"width":0.9,"slant":5,"counter_scale":1.0,"spacing":15}
        out=merge_ai_patch(base,{"counter_scale":1.16})
        self.assertEqual(out["width"],0.9)
        self.assertEqual(out["counter_scale"],1.16)
        self.assertEqual(out["serif_style"],"none")
        with self.assertRaises(ValueError):
            merge_ai_patch(base,{"A_counter":1.2})
        with self.assertRaises(ValueError):
            merge_ai_patch(base,{"counter_scale":500})

if __name__=='__main__':
    unittest.main()
