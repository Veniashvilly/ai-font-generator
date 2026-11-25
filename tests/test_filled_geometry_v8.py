"""V8 regressions: overlapping ink, meaningful holes and offset direction."""
import unittest
from fontTools.pens.ttGlyphPen import TTGlyphPen
from engine.filled_geometry import filled_region, change_filled_counters, change_filled_weight, polygons
from shapely.geometry import Polygon


def ring_from_overlaps():
    pen = TTGlyphPen(None)
    # Four same-winding rectangles overlap at corners; no explicit hole contour.
    for x0,y0,x1,y1 in [(0,0,500,90),(0,410,500,500),(0,0,90,500),(410,0,500,500)]:
        pen.moveTo((x0,y0)); pen.lineTo((x0,y1)); pen.lineTo((x1,y1)); pen.lineTo((x1,y0)); pen.closePath()
    return pen.glyph()


def hole_area(g):
    return sum(Polygon(r).area for p in polygons(filled_region(g,1000)) for r in p.interiors)


class FilledTests(unittest.TestCase):
    def test_nonzero_overlaps(self):
        g = ring_from_overlaps()
        self.assertAlmostEqual(filled_region(g,1000).area, 500**2-320**2)
        self.assertAlmostEqual(hole_area(g),320**2)

    def test_counter_both_directions(self):
        before = hole_area(ring_from_overlaps())
        for scale in (.7,1.3):
            g = ring_from_overlaps(); stats = {}
            self.assertEqual(change_filled_counters(g, scale,1000,stats),1)
            self.assertGreater((hole_area(g)-before)*(scale-1),0)
            self.assertTrue(stats['filled_geometry'])

    def test_weight_both_directions(self):
        before = filled_region(ring_from_overlaps(),1000).area
        for scale in (.75,1.35):
            g = ring_from_overlaps(); stats = {}
            self.assertGreater(change_filled_weight(g,scale,1000,stats),0)
            self.assertGreater((filled_region(g,1000).area-before)*(scale-1),0)
            self.assertGreater(hole_area(g),0)

    def test_separate_stripes_no_false_counter(self):
        pen = TTGlyphPen(None)
        for x in range(0,400,20):
            pen.moveTo((x,0));pen.lineTo((x,200));pen.lineTo((x+10,200));pen.lineTo((x+10,0));pen.closePath()
        g=pen.glyph(); before=list(g.coordinates)
        self.assertEqual(change_filled_counters(g,1.3,1000,{}),0)
        self.assertEqual(before,list(g.coordinates))

if __name__ == '__main__': unittest.main()
