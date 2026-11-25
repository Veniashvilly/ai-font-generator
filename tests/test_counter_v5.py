"""Проверки универсального алгоритма: никаких отдельных настроек для A/e/q/я."""
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import sys

from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.recordingPen import DecomposingRecordingPen

from engine.advanced_effects import change_counter_size, _contours
from engine.counter_geometry import _classify_holes, _flatten, _possible_overlap


def make_glyph(outline, holes=()):
    pen = TTGlyphPen(None)
    for polygon in (outline, *holes):
        pen.moveTo(polygon[0])
        for pt in polygon[1:]:
            pen.lineTo(pt)
        pen.closePath()
    return pen.glyph()


class UniversalCounterV5Tests(unittest.TestCase):
    def test_separate_shapes_are_not_falsely_holes(self):
        glyph = make_glyph([(0, 0), (0, 300), (100, 300), (100, 0)],
                           [[(300, 0), (300, 100), (400, 100), (400, 0)]])
        self.assertFalse(_possible_overlap(_flatten(glyph)))
        s = {}
        self.assertEqual(change_counter_size(glyph, 1.2, 1000, s), 0)
        self.assertIn('skip_reason', s)

    def test_overlapping_contours_fallback_contract(self):
        # В исходнике два пересекающихся прямоугольника (вложенных дырок нет).
        # Подменяем только библиотеку булевых операций тестовой реализацией,
        # которая отдаёт нормализованный глиф с отверстием.
        raw = make_glyph([(0, 0), (0, 800), (400, 800), (400, 0)],
                         [[(200, 0), (200, 800), (600, 800), (600, 0)]])
        ring = make_glyph([(0, 0), (0, 900), (700, 900), (700, 0)],
                          [[(110, 100), (590, 100), (590, 800), (110, 800)]])

        class FakePath:
            def getPen(self):
                return TTGlyphPen(None)
            def simplify(self):
                pass
            def draw(self, pen):
                ring.draw(pen, None)

        with patch.dict(sys.modules, {'pathops': SimpleNamespace(Path=FakePath)}):
            stats = {}
            changed = change_counter_size(raw, 1.1, 1000, stats)
        self.assertEqual(changed, 1)
        self.assertTrue(stats['recovery_used'])
        self.assertEqual(len(_classify_holes(_flatten(raw))), 1)

    def test_real_fonts_cover_closed_counters(self):
        path = Path('/usr/share/fonts/truetype/lato/Lato-Regular.ttf')
        if not path.exists():
            self.skipTest('Lato отсутствует — тест локального системного шрифта')
        with TTFont(path) as font:
            cmap = font.getBestCmap()
            gs = font.getGlyphSet()
            for ch in 'ABOeqя':
                with self.subTest(letter=ch):
                    glyph_name = cmap.get(ord(ch))
                    self.assertIsNotNone(glyph_name)
                    rec = DecomposingRecordingPen(gs)
                    gs[glyph_name].draw(rec)
                    pen = TTGlyphPen(None)
                    rec.replay(pen)
                    glyph = pen.glyph()
                    before = list(glyph.coordinates)
                    stats = {}
                    changed = change_counter_size(glyph, 1.15, font['head'].unitsPerEm, stats)
                    self.assertGreater(changed, 0)
                    self.assertNotEqual(before, list(glyph.coordinates))
                    self.assertGreater(stats['effective_scale'], 1)


if __name__ == '__main__':
    unittest.main()
