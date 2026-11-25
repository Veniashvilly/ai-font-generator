"""Проверка распознавания внутренних просветов конкретного TTF.

Не меняет шрифт, не обращается к GigaChat, не требует GUI.
Пример:
  python diagnose_counters.py "fonts/base/Inter/static/Inter_28pt-SemiBoldItalic.ttf"
"""
from __future__ import annotations

import argparse
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

from engine.advanced_effects import change_counter_size


def main() -> None:
    parser = argparse.ArgumentParser(description="Диагностика просветов конкретного шрифта")
    parser.add_argument("ttf", type=Path, help="Путь к исходному статическому TTF")
    parser.add_argument("--scale", type=float, default=1.2, help="Параметр counter_scale")
    args = parser.parse_args()

    source = args.ttf.expanduser().resolve()
    if not source.is_file():
        parser.error(f"Шрифт не найден: {source}")

    with TTFont(source) as font:
        if 'glyf' not in font:
            parser.error('Нужен TrueType TTF с таблицей glyf')
        cmap = font.getBestCmap() or {}
        glyphs = font.getGlyphSet()
        em = font['head'].unitsPerEm
        print(f"Шрифт: {source.name}; em={em}; counter_scale={args.scale}")
        for letter in 'ABOАВОeqя8':
            glyph_name = cmap.get(ord(letter))
            if not glyph_name:
                print(f"{letter}: символ отсутствует в cmap")
                continue
            recorder = DecomposingRecordingPen(glyphs)
            glyphs[glyph_name].draw(recorder)
            pen = TTGlyphPen(None)
            recorder.replay(pen)
            glyph = pen.glyph()
            stats = {}
            changed = change_counter_size(glyph, args.scale, em, stats=stats)
            print(
                f"{letter}: контуров={stats.get('contours_total', 0)}, "
                f"отверстий={stats.get('holes_found', 0)}, "
                f"изменено={changed}, "
                f"масштаб={stats.get('effective_scale', 1.0):.3f}, "
                f"восстановление={stats.get('recovery_used', False)}"
            )
            if stats.get('skip_reason'):
                print('    причина:', stats['skip_reason'])


if __name__ == '__main__':
    main()
