"""Автоматически исследуем TTF и создаём каталог для будущей LLM."""

import json
from pathlib import Path

from fontTools.ttLib import TTFont

from engine.catalog import FONTS_DIR, ROOT, list_fonts
from engine.language import coverage, missing_chars

TAGS_FILE = ROOT / "font_tags.json"


def _font_name(font: TTFont, name_id: int) -> str:
    """Читаем имя семейства или начертания из таблицы name."""
    value = font["name"].getDebugName(name_id) if "name" in font else None
    return value or "Не указано"


def build_catalog() -> list[dict]:
    """Сканируем реальные TTF: кириллицу не угадываем по названию."""
    tags = json.loads(TAGS_FILE.read_text(encoding="utf-8")) if TAGS_FILE.exists() else {}
    result = []
    for path in list_fonts():
        font_id = path.relative_to(FONTS_DIR).as_posix()
        try:
            with TTFont(path, lazy=False) as font:
                cmap = font.getBestCmap() or {}
                # Поддерживаем пока только статические TrueType с glyf.
                supported = "glyf" in font and "fvar" not in font and "gvar" not in font
                family = _font_name(font, 1)
                style = _font_name(font, 2)
                weight = font["OS/2"].usWeightClass if "OS/2" in font else None
                scripts = coverage(cmap)
                info = {
                    "id": font_id,
                    "family": family,
                    "style": style,
                    "weight_class": weight,
                    "latin": scripts["latin"],
                    "cyrillic": scripts["cyrillic"],
                    "latin_missing_count": len(missing_chars(cmap, "latin")),
                    "cyrillic_missing_count": len(missing_chars(cmap, "cyrillic")),
                    "can_generate": supported,
                    "tags": tags.get(path.parent.name, []),
                }
                result.append(info)
        except Exception as exc:
            print(f"Пропускаем повреждённый/неподдерживаемый файл {font_id}: {exc}")
    return result


def save_catalog(destination: Path | None = None) -> Path:
    """Создаём JSON, который позднее будем давать нейросети."""
    destination = destination or (ROOT / "font_catalog.json")
    destination.write_text(
        json.dumps(build_catalog(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination
