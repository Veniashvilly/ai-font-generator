"""Тесты без GigaChat и без обязательных внешних шрифтов.

Запуск: python -m unittest discover -s tests -p test_advanced_effects.py -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from engine.advanced_effects import SerifSettings, _contours, add_serifs, change_counter_size
from engine.stroke_effects import change_weight, round_corners
from engine.advanced_generator import AdvancedConfig, generate_advanced


def make_ring():
    """Внешний квадрат с квадратной дыркой (противоположные направления)."""
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((0, 400))
    pen.lineTo((400, 400))
    pen.lineTo((400, 0))
    pen.closePath()
    pen.moveTo((100, 100))
    pen.lineTo((300, 100))
    pen.lineTo((300, 300))
    pen.lineTo((100, 300))
    pen.closePath()
    return pen.glyph()


class GeometryTests(unittest.TestCase):
    def test_counter_size_expands_hole(self):
        glyph = make_ring()
        before = _contours(glyph)[1][3]
        self.assertEqual(change_counter_size(glyph, 1.15), 1)
        after = _contours(glyph)[1][3]
        self.assertGreater(after[2] - after[0], before[2] - before[0])
        self.assertGreater(after[3] - after[1], before[3] - before[1])

    def test_counter_size_reduces_hole(self):
        glyph = make_ring()
        before = _contours(glyph)[1][3]
        self.assertEqual(change_counter_size(glyph, 0.85), 1)
        after = _contours(glyph)[1][3]
        self.assertLess(after[2] - after[0], before[2] - before[0])

    def test_no_counter_no_change(self):
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0))
        pen.lineTo((400, 0))
        pen.lineTo((400, 400))
        pen.closePath()
        self.assertEqual(change_counter_size(pen.glyph(), 1.1), 0)

    def test_serifs_add_ink_to_h(self):
        # Две вертикали с перекладиной — реальная схема буквы H.
        pen = TTGlyphPen(None)
        vertices = [(0, 0), (60, 0), (60, 220), (260, 220),
                    (260, 0), (320, 0), (320, 600), (260, 600),
                    (260, 280), (60, 280), (60, 600), (0, 600)]
        pen.moveTo(vertices[0])
        for point in vertices[1:]:
            pen.lineTo(point)
        pen.closePath()
        glyph = pen.glyph()
        before = glyph.numberOfContours
        count = add_serifs(glyph, "H", 1000, SerifSettings(style="bracket"))
        self.assertEqual(count, 4)
        self.assertEqual(glyph.numberOfContours, before + 4)

    def test_thin_ring_is_protected(self):
        # В исходнике толщина обводки всего 12 единиц.
        # Увеличение просвета не должно уничтожить эту обводку.
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0)); pen.lineTo((0, 400))
        pen.lineTo((400, 400)); pen.lineTo((400, 0)); pen.closePath()
        pen.moveTo((12, 12)); pen.lineTo((388, 12))
        pen.lineTo((388, 388)); pen.lineTo((12, 388)); pen.closePath()
        glyph = pen.glyph()
        original = glyph.coordinates[:]
        stats = {}
        count = change_counter_size(glyph, 1.2, em=1000, stats=stats)
        self.assertEqual(count, 0)
        self.assertEqual(list(glyph.coordinates), list(original))
        self.assertGreater(stats.get("limited", 0), 0)

    def test_serif_is_scaled_to_actual_stem(self):
        # Засечка тонкого штриха не должна быть огромной.
        from engine.advanced_effects import _serif_shape
        settings = SerifSettings(style="slab", length=.12, thickness=.09)
        points, flags = _serif_shape(100, 0, +1, 1000, 12, settings)
        width = max(x for x, y in points) - min(x for x, y in points)
        thickness = max(y for x, y in points) - min(y for x, y in points)
        self.assertLess(width, 90)
        self.assertLess(thickness, 20)

    def test_serifs_not_automatically_on_o(self):
        self.assertEqual(add_serifs(make_ring(), "O", 1000, SerifSettings(style="slab")), 0)


    def test_weight_changes_outer_and_inner_contours(self):
        glyph = make_ring()
        outer_before = _contours(glyph)[0][3]
        hole_before = _contours(glyph)[1][3]
        self.assertGreater(change_weight(glyph, 1.20), 0)
        outer_after = _contours(glyph)[0][3]
        hole_after = _contours(glyph)[1][3]
        self.assertGreater(outer_after[2] - outer_after[0], outer_before[2] - outer_before[0])
        self.assertLess(hole_after[2] - hole_after[0], hole_before[2] - hole_before[0])

    def test_corner_roundness_moves_points(self):
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0))
        pen.lineTo((0, 300))
        pen.lineTo((140, 500))
        pen.lineTo((280, 300))
        pen.lineTo((280, 0))
        pen.closePath()
        glyph = pen.glyph()
        before = list(glyph.coordinates)
        changed = round_corners(glyph, 0.30)
        self.assertGreater(changed, 0)
        self.assertNotEqual(list(glyph.coordinates), before)

    def test_invalid_params_rejected(self):
        with self.assertRaises(ValueError):
            AdvancedConfig.from_dict({"counter_scale": 900})
        with self.assertRaises(ValueError):
            AdvancedConfig.from_dict({"unknown_param": 123})
        with self.assertRaises(ValueError):
            SerifSettings(style="cursive").validate()


class RealFontSmokeTests(unittest.TestCase):
    def test_real_ttf(self):
        # По возможности берём один шрифт из проекта или системный DejaVu.
        root = Path(__file__).resolve().parent.parent
        fonts = list((root / "fonts" / "base").rglob("*.ttf"))
        for system_font in (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("C:/Windows/Fonts/arial.ttf"),
        ):
            if system_font.exists():
                fonts.append(system_font)
        source = None
        for path in fonts:
            try:
                with TTFont(path) as check:
                    if "glyf" in check and "fvar" not in check and all(ord(c) in (check.getBestCmap() or {}) for c in "АОHI"):
                        source = path
                        break
            except Exception:
                pass
        if source is None:
            self.skipTest("Нет статического TTF с кириллицей; пропуск интеграционного теста")

        with tempfile.TemporaryDirectory() as folder:
            result = generate_advanced(
                source,
                output_root=folder,
                config=AdvancedConfig(counter_scale=1.12, weight_scale=1.12, corner_roundness=0.12, serif_style="slab"),
            )
            self.assertTrue(result.is_file())
            report = json.loads((result.parent / "advanced_report.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(report["counter_contours_changed"], 0)
            self.assertGreater(report["weight_changed_contours"], 0)
            self.assertGreater(report["rounded_points"], 0)
            self.assertGreater(report["serifs_added"], 0)
            with TTFont(source) as original, TTFont(result) as generated:
                self.assertEqual(set(original.getBestCmap()), set(generated.getBestCmap()))


if __name__ == "__main__":
    unittest.main()
