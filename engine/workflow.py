"""Единая точка входа для параметров от человека или ИИ (пока без API)."""

import json
import math
from pathlib import Path

from engine.catalog import FONTS_DIR, OUTPUT_DIR, list_fonts
from engine.generator import generate_font
from engine.language import SCRIPTS

FIELDS = {"base_font", "width", "slant", "spacing", "script"}
DEFAULTS = {"width": 1.0, "slant": 0.0, "spacing": 0, "script": "auto"}


def load_json(path: Path) -> dict:
    """Читаем объект JSON и выдаём понятную ошибку при неверном формате."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Ожидался JSON-объект с параметрами")
    return data


def normalize_spec(data: dict) -> dict:
    """Проверяем JSON. Значения, которые может вернуть ИИ, не доверяем без проверки."""
    unknown = set(data) - FIELDS
    if unknown:
        raise ValueError(f"Неизвестные параметры: {', '.join(sorted(unknown))}")

    base_font = data.get("base_font")
    if not isinstance(base_font, str):
        raise ValueError("base_font должен быть строкой с id шрифта из каталога")

    existing = {p.relative_to(FONTS_DIR).as_posix(): p for p in list_fonts()}
    if base_font not in existing:
        raise ValueError(f"Шрифт {base_font!r} не найден в fonts/base")

    spec = {**DEFAULTS, **data}
    if not isinstance(spec["script"], str) or spec["script"] not in SCRIPTS:
        raise ValueError("script должен быть latin, cyrillic, both или auto")
    for field, minimum, maximum in (
        ("width", 0.55, 1.4),
        ("slant", -20, 20),
    ):
        value = spec[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{field}: требуется конечное число")
        if not minimum <= value <= maximum:
            raise ValueError(f"{field}: диапазон от {minimum} до {maximum}")

    spacing = spec["spacing"]
    if type(spacing) is not int or not 0 <= spacing <= 100:
        raise ValueError("spacing: требуется целое число от 0 до 100")
    return spec


def generate_from_spec(data: dict, parent_version: str | None = None) -> Path:
    """Генерируем TTF из JSON. Сохраняем связь с предыдущей версией."""
    spec = normalize_spec(data)
    source = FONTS_DIR / spec["base_font"]
    result = generate_font(
        source, float(spec["width"]), float(spec["slant"]), spec["spacing"], script=spec["script"]
    )
    # generator.py уже создал params.json, добавляем связь версий.
    params_path = result.parent / "params.json"
    params = load_json(params_path)
    params["parent_version"] = parent_version
    params_path.write_text(
        json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def revise(previous_params_path: Path, changes: dict) -> Path:
    """Правки применяем к ИСХОДНОМУ TTF, а не к уже деформированному файлу."""
    previous_params_path = previous_params_path.resolve()
    if (
        previous_params_path.name != "params.json"
        or not previous_params_path.is_relative_to(OUTPUT_DIR.resolve())
    ):
        raise ValueError("Для правок нужен params.json из папки output")

    previous = load_json(previous_params_path)
    unknown = set(changes) - FIELDS
    if unknown:
        raise ValueError(f"Недопустимые поля правок: {sorted(unknown)}")

    current = {key: previous[key] for key in FIELDS if key in previous}
    # Версии со старой схемой не имеют script: считаем, что язык не уточнялся.
    current.setdefault("script", "auto")
    current.update(changes)
    return generate_from_spec(current, parent_version=previous_params_path.parent.name)
