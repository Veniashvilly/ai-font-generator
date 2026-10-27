"""Язык запроса и проверка покрытия символов исходным шрифтом."""

from __future__ import annotations

import re

# Проверяем весь русский и английский алфавиты, включая Ё/ё.
LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CYRILLIC = (
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
)
SCRIPTS = {"latin", "cyrillic", "both", "auto"}


def detect_script(request: str) -> str:
    """Явно указанный язык или auto, если пользователь не уточнил."""
    text = request.casefold()
    # Не угадываем язык по тому, что сам запрос написан по-русски.
    want_ru = bool(re.search(r"русск|кириллиц|russian|cyrillic", text))
    want_en = bool(re.search(r"английск|латиниц|латинск|english|latin", text))
    if want_ru and want_en:
        return "both"
    if want_ru:
        return "cyrillic"
    if want_en:
        return "latin"
    return "auto"


def missing_chars(cmap: dict, script: str) -> list[str]:
    """Список отсутствующих символов для заданного режима."""
    if script not in SCRIPTS:
        raise ValueError(f"Неизвестный режим алфавита: {script}")
    required = {
        "latin": LATIN,
        "cyrillic": CYRILLIC,
        "both": LATIN + CYRILLIC,
        "auto": "",
    }[script]
    return [char for char in required if ord(char) not in cmap]


def coverage(cmap: dict) -> dict[str, bool]:
    """Полная поддержка латиницы и/или русского алфавита."""
    return {
        "latin": not missing_chars(cmap, "latin"),
        "cyrillic": not missing_chars(cmap, "cyrillic"),
    }
