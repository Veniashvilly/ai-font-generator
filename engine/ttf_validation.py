"""Structural and render checks, not a proof of typographic quality."""
from pathlib import Path
from fontTools.ttLib import TTFont
from PIL import ImageFont
from engine.language import coverage


def validate_ttf(path, source=None):
    path = Path(path)
    with TTFont(path, checkChecksums=2) as font:
        required = {'head','maxp','hmtx','hhea','cmap','glyf','loca','name','OS/2','post'}
        if required - set(font.keys()):
            raise ValueError(f'Отсутствуют таблицы: {sorted(required-set(font.keys()))}')
        font.ensureDecompiled()
        cmap = font.getBestCmap() or {}
        names = font.getGlyphOrder()
        if not cmap or not set(cmap.values()) <= set(names):
            raise ValueError('Некорректная карта Unicode')
        if len(names) != font['maxp'].numGlyphs or set(font['hmtx'].metrics) != set(names):
            raise ValueError('Несогласованное число глифов/метрик')
        glyf = font['glyf']
        for name in names:
            coords, ends, flags = glyf[name].getCoordinates(glyf)
            if len(coords) != len(flags) or (ends and ends[-1] != len(coords)-1):
                raise ValueError(f'Неверные координаты: {name}')
        family = font['name'].getDebugName(1)
    before = None
    if source:
        with TTFont(source) as original:
            original_cmap = original.getBestCmap() or {}
        before = len(original_cmap)
        if set(cmap) != set(original_cmap):
            raise ValueError('Карта Unicode отличается от исходного шрифта')
    samples = ''.join(ch for ch in 'ABOeH8 abcxyz0123456789 АБВОеёНЯ' if ord(ch) in cmap)
    if not samples.strip():
        samples = ''.join(chr(cp) for cp in sorted(cmap) if chr(cp).isprintable())[:32]
    if not samples:
        raise ValueError('Нет символов для проверки рендера')
    for size in (16, 48, 96):
        raster = ImageFont.truetype(str(path), size)
        raster.getmask(samples)
    return {'status':'ok', 'family_name':family, 'glyphs_total':len(names),
            'unicode_mappings_before':before, 'unicode_mappings_after':len(cmap),
            'lost_unicode_mappings':0 if source else None, 'coverage':coverage(cmap),
            'render_test_text':samples, 'render_sizes':[16,48,96],
            'warnings':['Структура и пробный рендер проверены; визуальное качество, кернинг и самопересечения требуют отдельной проверки.']}
