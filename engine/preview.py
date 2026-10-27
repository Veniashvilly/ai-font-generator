"""PNG-предпросмотр с учётом выбранного языка текста."""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

from engine.language import coverage

LATIN_LINES = ["THE QUICK BROWN FOX", "The quick brown fox jumps over the lazy dog"]
CYRILLIC_LINES = ["СЪЕШЬ ЕЩЁ ЭТИХ МЯГКИХ", "Съешь ещё этих мягких булок"]


def create_preview(ttf_path: Path) -> Path:
    """Создаёт preview.png, не подменяя отсутствующие символы чужим шрифтом."""
    ttf_path = Path(ttf_path).resolve()
    settings_path = ttf_path.with_name("params.json")
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    script = settings.get("script", "auto")

    with TTFont(ttf_path) as font:
        supported = coverage(font.getBestCmap() or {})

    # При неуказанном языке показываем оба, если есть оба;
    # иначе только реально поддерживаемый алфавит.
    show_en = (script in ("auto", "both", "latin")) and supported["latin"]
    show_ru = (script in ("auto", "both", "cyrillic")) and supported["cyrillic"]
    lines = []
    if show_en:
        lines.extend(LATIN_LINES)
    if show_ru:
        lines.extend(CYRILLIC_LINES)
    lines.append("0123456789")

    width, height = 1450, 650
    image = Image.new("RGB", (width, height), "#f6f7f9")
    canvas = ImageDraw.Draw(image)
    canvas.text((70, 35), "AI FONT - PREVIEW", font=ImageFont.load_default(), fill="#525966")

    step = 490 // len(lines)
    for index, line in enumerate(lines):
        size = 96 if index == 0 else 74
        while size >= 16:
            font = ImageFont.truetype(str(ttf_path), size)
            rect = canvas.textbbox((0, 0), line, font=font)
            if rect[2] - rect[0] <= width - 140:
                break
            size -= 2
        x = 70 - rect[0]
        y = 94 + index * step - rect[1]
        canvas.text((x, y), line, font=font, fill="#101820")

    output_path = ttf_path.with_name("preview.png")
    image.save(output_path)
    return output_path
