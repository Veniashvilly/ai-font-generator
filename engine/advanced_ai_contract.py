"""Контракт расширенных параметров для будущего подключения GigaChat.

ЭТО НЕ клиент API. Модуль нужен, чтобы фронтенд и ИИ использовали
ОДНИ и ТЕ ЖЕ названия, диапазоны и проверки настроек.

После подключения GigaChat он должен возвращать только частичные изменения
в JSON. Мы объединяем их с текущим состоянием и передаём генератору.
"""
from dataclasses import asdict

from engine.advanced_generator import AdvancedConfig


PARAMETER_HELP = {
    "width": "Ширина глифов: 0.55..1.4; 1.0 — исходная",
    "slant": "Наклон в градусах: -20..20",
    "spacing": "Интервал между буквами: целое число от -20 до 100",
    "counter_scale": "Единый размер внутренних просветов всех букв: 0.7..1.3, 1.0 — без изменения",
    "weight_scale": "Толщина штрихов: 0.75..1.35, 1.0 — оригинал",
    "corner_roundness": "Скругление острых углов: 0..0.45, 0 — оригинал",
    "serif_style": "Засечки: none, slab, wedge, bracket (пока ограниченный набор букв)",
    "serif_length": "Длина засечек, доля em: 0.005..0.12",
    "serif_thickness": "Толщина засечек, доля em: 0.005..0.09",
    "serif_bracket": "Сопряжение засечек: 0..0.09",
    "serif_angle": "Угол торца засечек, градусы: -25..25",
}


def merge_ai_patch(current: dict, patch: dict) -> dict:
    """Безопасно объединяет текущие значения и JSON с правками GigaChat.

    Не позволяет модели выдумывать новые поля или выходить за диапазоны.
    Существующие значения сохраняются, если ИИ их не изменил.
    """
    if not isinstance(patch,dict) or not patch:
        raise ValueError("Правка ИИ должна быть непустым JSON-объектом")
    base = asdict(AdvancedConfig.from_dict(current))
    updated = {**base, **patch}
    return asdict(AdvancedConfig.from_dict(updated))
