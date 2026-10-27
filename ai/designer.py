"""ИИ-дизайнер: преобразует текстовые ответы GigaChat в безопасные параметры.

Почему нужен этот модуль:
- модель может вернуть JSON внутри ```json ... ``` или добавить пояснение;
- модель иногда отвечает обычным текстом;
- любые параметры модели нужно проверить перед генерацией TTF.
"""

import json
from typing import Callable

from engine.workflow import normalize_spec
from ai.client import ask_gigachat
from ai.prompts import initial_prompt, load_candidates, revision_prompt
from engine.language import detect_script

LLM = Callable[[str], str]
REQUIRED_FIELDS = {"action", "parameters", "message"}


def _validate_answer(value: object) -> dict:
    """Проверяем структуру ответа модели перед работой с параметрами."""
    if not isinstance(value, dict) or set(value) != REQUIRED_FIELDS:
        raise ValueError("У JSON неверный набор полей: action, parameters, message")
    if value["action"] not in {"generate", "cannot"}:
        raise ValueError("Недопустимое значение action")
    if not isinstance(value["parameters"], dict) or not isinstance(value["message"], str):
        raise ValueError("Неверные типы полей parameters/message")
    return value


def read_answer(text: str) -> dict:
    """Извлекаем JSON из ответа, даже если вокруг него есть пояснение или Markdown."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Пустой ответ GigaChat")

    cleaned = text.lstrip("\ufeff").strip()

    # Обычный случай: модель вернула ровно JSON-объект.
    try:
        return _validate_answer(json.loads(cleaned))
    except (json.JSONDecodeError, ValueError):
        pass

    # Частый случай: «Вот ваши параметры: ```json { ... } ```».
    # Ищем корректный JSON-объект внутри текста, не выполняя никакого кода.
    decoder = json.JSONDecoder()
    for index, symbol in enumerate(cleaned):
        if symbol != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(cleaned[index:])
            return _validate_answer(candidate)
        except (json.JSONDecodeError, ValueError):
            continue

    raise ValueError("GigaChat не вернул JSON нужного формата")


def _ask_json(prompt: str, ask: LLM) -> dict:
    """Один запрос; если формат неверный, просим модель исправить его (один раз)."""
    text = ask(prompt)

    try:
        answer = read_answer(text)
    except ValueError:
        print("GigaChat ответил не JSON. Запрашиваю исправленный формат...")

        repair_prompt = (
            "В прошлый раз ответ не прошёл проверку JSON. "
            "Верни ТОЛЬКО один корректный JSON-объект без пояснений и Markdown. "
            "Ровно три поля: action, parameters, message. "
            "action должен быть generate или cannot. "
            "Не выдумывай шрифты и не выходи за разрешённые диапазоны.\n\n"
            "ИСХОДНОЕ ЗАДАНИЕ:\n" + prompt + "\n\n"
            "ПРЕДЫДУЩИЙ ОТВЕТ (может содержать ошибки):\n" + text[:4000]
        )
        repaired = ask(repair_prompt)
        try:
            answer = read_answer(repaired)
        except ValueError as error:
            # Не выводим авторизационные данные; только небольшой фрагмент ответа модели.
            print("Начало ответа модели:", repr(repaired[:250]))
            raise ValueError(
                "GigaChat дважды вернул ответ не в формате JSON. "
                "Скопируй строку «Начало ответа модели» для диагностики."
            ) from error

    if answer["action"] == "cannot":
        raise ValueError("Запрос пока не поддерживается: " + answer["message"])
    return answer


def create_spec(request: str, ask: LLM = ask_gigachat) -> tuple[dict, str]:
    """Первая генерация: выбор шрифта и безопасная обработка параметров.

    Не отправляем новый запрос в GigaChat только ради исправления имени
    файла: Python может сопоставить его с существующим каталогом сам.
    Это предотвращает дополнительные ошибки JSON и лишние API-вызовы.
    """
    import math

    candidates = load_candidates(request)
    if not candidates:
        raise ValueError("Нет подходящих шрифтов для выбранного языка")

    answer = _ask_json(initial_prompt(request, candidates), ask)
    params = answer["parameters"]
    required = {"base_font", "width", "slant", "spacing"}

    if set(params) != required:
        raise ValueError("Ожидались base_font, width, slant, spacing")

    ids = [candidate["id"] for candidate in candidates]
    chosen = params["base_font"]
    notes = []

    if not isinstance(chosen, str) or chosen not in ids:
        # Модель иногда пишет одно имя файла вместо полного каталожного ID.
        # Исправляем автоматически, но ТОЛЬКО при единственном совпадении.
        basename = (chosen if isinstance(chosen, str) else "").replace("\\", "/").split("/")[-1]
        matches = [
            item for item in ids
            if item.split("/")[-1].casefold() == basename.casefold()
        ]

        if len(matches) == 1:
            chosen = matches[0]
            print("Полный путь шрифта восстановлен по каталогу:", chosen)
        else:
            # Кандидаты уже отфильтрованы по требуемому алфавиту.
            # Поэтому не берём произвольный TTF из папки fonts/base.
            chosen = ids[0]
            reason = "не найден" if not matches else "неоднозначен"
            print(f"Выбор ИИ {reason}. Взят первый допустимый кандидат:", chosen)
            notes.append("Исходный шрифт выбран программно из допустимого каталога")

    clean = {"base_font": chosen}

    # Числа от модели не считаем заведомо корректными. Не округляем и
    # не зажимаем произвольные значения: заменяем ошибочные значениями,
    # которые безопасны для текущего движка.
    for field, minimum, maximum, default in (
        ("width", 0.55, 1.4, 1.0),
        ("slant", -20, 20, 0.0),
        ("spacing", 0, 100, 0),
    ):
        value = params[field]
        valid_type = type(value) is int if field == "spacing" else type(value) in (int, float)
        valid = (
            valid_type
            and math.isfinite(value)
            and minimum <= value <= maximum
        )
        if valid:
            clean[field] = value
        else:
            clean[field] = default
            print(f"Параметр {field}={value!r} недопустим, использую {default}")
            notes.append(f"{field} заменён безопасным значением {default}")

    # Последняя строгая проверка существования TTF и диапазонов.
    spec = normalize_spec({**clean, "script": detect_script(request)})
    explanation = answer["message"]
    if notes:
        explanation += " Внимание: " + "; ".join(notes) + "."
    return spec, explanation


def create_patch(request: str, previous: dict, ask: LLM = ask_gigachat) -> tuple[dict, str]:
    """Для правок разрешены только указанные моделью изменённые параметры."""
    answer = _ask_json(revision_prompt(request, previous), ask)
    patch = answer["parameters"]

    if not patch or not set(patch).issubset({"width", "slant", "spacing"}):
        raise ValueError("ИИ не указал допустимые изменения")

    current = {
        field: previous[field]
        for field in ("base_font", "width", "slant", "spacing")
    }
    normalize_spec({**current, "script": previous.get("script", "auto"), **patch})
    return patch, answer["message"]
