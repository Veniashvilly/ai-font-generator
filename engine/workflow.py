"""Единая точка входа для параметров от человека или ИИ (пока без API)."""

import json
from dataclasses import asdict
from engine.advanced_generator import AdvancedConfig
from engine.advanced_ai_contract import PARAMETER_HELP
from pathlib import Path

from engine.catalog import FONTS_DIR, OUTPUT_DIR, list_fonts
from engine.integrated_generation import generate_integrated
from engine.language import SCRIPTS

EFFECT_FIELDS = frozenset(PARAMETER_HELP)
FIELDS = EFFECT_FIELDS | {"base_font", "script"}
DEFAULTS = {**asdict(AdvancedConfig()), "script": "auto"}


def load_json(path: Path) -> dict:
    """Читаем объект JSON и выдаём понятную ошибку при неверном формате."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Ожидался JSON-объект с параметрами")
    return data


def normalize_spec(data: dict) -> dict:
    """Проверяем JSON. Значения, которые может вернуть ИИ, не доверяем без проверки."""
    if not isinstance(data, dict):
        raise ValueError("Ожидался JSON-объект")
    unknown = set(data) - FIELDS
    if unknown:
        raise ValueError(f"Неизвестные параметры: {', '.join(sorted(unknown))}")

    base_font = data.get("base_font")
    if not isinstance(base_font, str):
        raise ValueError("base_font должен быть строкой с id шрифта из каталога")

    existing = {p.relative_to(FONTS_DIR).as_posix(): p for p in list_fonts()}
    if base_font not in existing:
        raise ValueError(f"Шрифт {base_font!r} не найден в fonts/base")

    if not existing[base_font].resolve().is_relative_to(FONTS_DIR.resolve()):
        raise ValueError("Недопустимый путь к шрифту")
    spec = {**DEFAULTS, **data}
    if not isinstance(spec["script"], str) or spec["script"] not in SCRIPTS:
        raise ValueError("script должен быть latin, cyrillic, both или auto")
    AdvancedConfig.from_dict({key: spec[key] for key in EFFECT_FIELDS})
    return spec


def generate_from_spec(data: dict, parent_version: str | None = None) -> Path:
    """Генерируем TTF из JSON. Сохраняем связь с предыдущей версией."""
    spec = normalize_spec(data)
    return generate_integrated(spec, OUTPUT_DIR, parent_version)


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
