"""Геометрическое преобразование статического TrueType-шрифта."""

import math
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont


def transform_ttf(
    source: Path,
    destination: Path,
    width: float,
    slant: float,
    spacing: int,
    family_name: str,
) -> None:
    """Изменяем контуры и создаём новый TTF, не трогая исходный файл.

    width=1.0 — исходная ширина; slant — угол наклона в градусах;
    spacing — добавка к ширине символа в единицах шрифта.
    """
    font = TTFont(source)
    try:
        # Пока поддерживаем только обычные, не вариативные TTF с таблицей glyf.
        if "glyf" not in font or "fvar" in font or "gvar" in font:
            raise ValueError(
                "Выбранный файл не является поддерживаемым статическим TTF. "
                "Попробуй другой .ttf (например, Regular)."
            )

        glyph_set = font.getGlyphSet()
        # В матрице x' = width*x + tan(slant)*y, y' = y.
        matrix = (width, 0, math.tan(math.radians(slant)), 1, 0, 0)
        new_glyphs = {}

        # Получаем контуры каждого глифа, включая составные символы.
        for glyph_name in font.getGlyphOrder():
            original = DecomposingRecordingPen(glyph_set)
            glyph_set[glyph_name].draw(original)

            pen = TTGlyphPen(None)
            original.replay(TransformPen(pen, matrix))
            new_glyphs[glyph_name] = pen.glyph()

        # Заменяем контуры и пересчитываем горизонтальные метрики.
        glyf = font["glyf"]
        for glyph_name, new_glyph in new_glyphs.items():
            old_advance, _ = font["hmtx"][glyph_name]
            glyf[glyph_name] = new_glyph
            # xMin используется как левый боковой отступ в координатах TTF.
            new_glyph.recalcBounds(glyf)
            left_bearing = getattr(new_glyph, "xMin", 0)
            new_advance = max(1, round(old_advance * width + spacing))
            font["hmtx"][glyph_name] = (new_advance, left_bearing)

        # Старый кернинг/позиционирование не согласованы с новыми контурами.
        # В демонстрационной версии отключаем их; позднее пересчитаем отдельно.
        # Также удаляем старые TrueType-инструкции хинтинга.
        for tag in ("kern", "GPOS", "fpgm", "prep", "cvt "):
            if tag in font:
                del font[tag]

        # Задаём новое имя, чтобы не конфликтовать с исходным шрифтом.
        names = {
            1: family_name,
            2: "Regular",
            3: family_name + "; Demo Version 1",
            4: family_name + " Regular",
            6: family_name.replace(" ", "") + "-Regular",
            16: family_name,
            17: "Regular",
        }
        name_table = font["name"]
        # Изменяем записи на имеющихся платформах (Windows / macOS).
        for record in list(name_table.names):
            if record.nameID in names:
                name_table.setName(
                    names[record.nameID], record.nameID,
                    record.platformID, record.platEncID, record.langID,
                )
        # Добавляем стандартные англоязычные записи Windows.
        for name_id, value in names.items():
            name_table.setName(value, name_id, 3, 1, 0x409)

        if "post" in font:
            font["post"].italicAngle = -slant
        font.recalcBBoxes = True
        destination.parent.mkdir(parents=True, exist_ok=True)
        font.save(destination)
    finally:
        font.close()
