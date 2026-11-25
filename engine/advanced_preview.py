"""Создание сравнительной картинки из оригинального и нового TTF."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def make_comparison(source: str | Path, result: str | Path, target: str | Path):
    """Рисует сопоставимые образцы с заголовками и одинаковым размером шрифта."""
    source, result, target = Path(source), Path(result), Path(target)
    image = Image.new("RGB", (1600, 710), "#F9FAFB")
    pen = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        title_font = ImageFont.truetype(str(source), 30)

    text_cases = [
        "ААО ОО ВВ НП Т",    # A/О — проверяем просветы; Н/П/Т — засечки
        "H I L E F T O A",
        "Съешь ещё этих мягких булок",
        "The quick brown fox",
        "0123456789",
    ]
    for col, (font_path, label) in enumerate(
        ((source, "ИCХОДНЫЙ TTF"), (result, "НОВЫЙ TTF"))
    ):
        x = 36 + col * 800
        pen.text((x, 27), label, font=title_font, fill="#6B7280")
        font_big = ImageFont.truetype(str(font_path), 63)
        font_med = ImageFont.truetype(str(font_path), 47)
        for i, line in enumerate(text_cases):
            size_font = font_big if i < 2 else font_med
            pen.text((x, 106 + i * 120), line, font=size_font, fill="#101827")
    pen.line((800, 0, 800, 710), fill="#E5E7EB", width=2)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return target
