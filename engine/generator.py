"""Генератор TTF с проверкой символов и отчётом о результате."""

import json
import math
from pathlib import Path
from uuid import uuid4

from fontTools.ttLib import TTFont

from engine.catalog import FONTS_DIR, OUTPUT_DIR
from engine.language import SCRIPTS, coverage, missing_chars
from engine.transform import transform_ttf


# Шире предыдущего диапазона 0.7..1.3, но экстремальная деформация
# по-прежнему ограничена, чтобы сохранить читаемость шрифта.
MIN_WIDTH, MAX_WIDTH = 0.55, 1.4


def _get_cmap(path: Path) -> tuple[dict, set]:
    """Читаем карту Unicode и убеждаемся, что структура TTF пригодна."""
    with TTFont(path) as font:
        mandatory = {"head", "maxp", "hmtx", "hhea", "cmap", "glyf", "name"}
        absent = mandatory - set(font.keys())
        if absent:
            raise ValueError(f"В TTF отсутствуют таблицы: {sorted(absent)}")
        if "fvar" in font or "gvar" in font:
            raise ValueError("Переменные TTF пока не поддерживаются")
        cmap = font.getBestCmap() or {}
        if not cmap:
            raise ValueError("В TTF нет карты Unicode")
        glyphs = set(font.getGlyphOrder())
        if any(name not in glyphs for name in cmap.values()):
            raise ValueError("Карта Unicode содержит ссылки на отсутствующие глифы")
        return cmap, glyphs


def generate_font(
    source: Path, width: float, slant: float, spacing: int, script: str = "auto"
) -> Path:
    """Проверяем вход, создаём result.ttf, params.json и quality_report.json."""
    if isinstance(width, bool) or not isinstance(width, (float, int)) or not math.isfinite(width) or not MIN_WIDTH <= width <= MAX_WIDTH:
        raise ValueError(f"Ширина должна быть от {MIN_WIDTH} до {MAX_WIDTH}")
    if isinstance(slant, bool) or not isinstance(slant, (float, int)) or not math.isfinite(slant) or not -20 <= slant <= 20:
        raise ValueError("Наклон должен быть от -20 до 20 градусов")
    if type(spacing) is not int or not 0 <= spacing <= 100:
        raise ValueError("Интервал должен быть целым числом от 0 до 100")
    if not isinstance(script, str) or script not in SCRIPTS:
        raise ValueError("script: допустимы latin, cyrillic, both, auto")

    source = Path(source).resolve()
    if not source.is_file() or source.suffix.lower() != ".ttf":
        raise ValueError("Исходный TTF не найден")
    if not source.is_relative_to(FONTS_DIR.resolve()):
        raise ValueError("Шрифт должен лежать в fonts/base")

    source_cmap, _ = _get_cmap(source)
    missing = missing_chars(source_cmap, script)
    if missing:
        sample = "".join(missing[:15])
        raise ValueError(
            f"Исходный TTF не подходит для режима {script}: "
            f"отсутствует {len(missing)} символов (например, {sample!r}). "
            "Выбери другой шрифт."
        )

    version_id = uuid4().hex[:10]
    target_dir = OUTPUT_DIR / version_id
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / "result.ttf"
    family_name = f"AIFont {version_id}"

    try:
        transform_ttf(source, destination, width, slant, spacing, family_name)
        new_cmap, _ = _get_cmap(destination)

        # Любые Unicode-символы, которые были в исходнике, должны остаться.
        vanished = sorted(set(source_cmap) - set(new_cmap))
        if vanished:
            raise RuntimeError(
                "После преобразования потерялись Unicode-символы: "
                + ", ".join(f"U+{code:04X}" for code in vanished[:12])
            )
        if missing_chars(new_cmap, script):
            raise RuntimeError("Новый TTF не прошёл проверку запрошенного алфавита")

        warnings = []
        if width < 0.65 or width > 1.3:
            warnings.append("Сильное изменение ширины может ухудшить пропорции букв.")
        warnings.append(
            "Это MVP: сложное OpenType-позиционирование/кернинг пока не пересчитывается "
            "(существующий движок удаляет kern/GPOS)."
        )
        covered = coverage(new_cmap)
        report = {
            "version": version_id,
            "requested_script": script,
            "latin_complete": covered["latin"],
            "cyrillic_complete": covered["cyrillic"],
            "unicode_mappings_before": len(source_cmap),
            "unicode_mappings_after": len(new_cmap),
            "lost_unicode_mappings": len(vanished),
            "warnings": warnings,
        }
        (target_dir / "quality_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        params = {
            "base_font": source.relative_to(FONTS_DIR).as_posix(),
            "width": width,
            "slant": slant,
            "spacing": spacing,
            "script": script,
            "family_name": family_name,
            "has_basic_cyrillic": covered["cyrillic"],
        }
        (target_dir / "params.json").write_text(
            json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("Проверка TTF: Unicode-символы сохранены.")
        print("Полная латиница:", covered["latin"], "| полная кириллица:", covered["cyrillic"])
        if warnings and (width < 0.65 or width > 1.3):
            print("Предупреждение:", warnings[0])
        return destination
    except Exception:
        # Не оставляем некорректный TTF как будто он успешно создан.
        destination.unlink(missing_ok=True)
        raise
