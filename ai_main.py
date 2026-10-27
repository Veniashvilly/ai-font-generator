"""Текстовый интерфейс ИИ-дизайнера. Не веб-сервер и не фронтенд.

Запуск: python ai_main.py
       python ai_main.py --prompt "узкий технологичный шрифт"
       python ai_main.py --revise output/ID/params.json --prompt "уменьши наклон"
"""

import argparse
import os
import sys
from pathlib import Path

from ai.designer import create_patch, create_spec
from engine.workflow import generate_from_spec, load_json, revise
from engine.preview import create_preview


def show_preview(result_ttf: Path) -> None:
    """Создаём PNG и открываем его в стандартном просмотрщике Windows."""
    try:
        picture = create_preview(result_ttf)
        print("Предпросмотр:", picture)
        if sys.platform == "win32":
            os.startfile(str(picture))  # Откроет приложение Windows для PNG.
    except Exception as exc:
        # Ошибка предпросмотра не должна удалять уже созданный TTF.
        print("Не удалось создать предпросмотр:", exc)


def start_new(request: str) -> Path:
    """Пользовательский текст -> запрос модели -> JSON -> TTF."""
    spec, message = create_spec(request)
    print("\nДизайнер:", message)
    print("Параметры:", spec)
    path = generate_from_spec(spec)
    print("Готовый TTF:", path)
    show_preview(path)
    return path.parent / "params.json"


def apply_revision(previous_file: Path, request: str) -> Path:
    """Читаем параметры версии, спрашиваем агента и создаём новую версию."""
    previous = load_json(previous_file)
    patch, message = create_patch(request, previous)
    print("\nДизайнер:", message)
    print("Изменения:", patch)
    result = revise(previous_file, patch)
    print("Новая версия:", result)
    show_preview(result)
    return result.parent / "params.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="ИИ-дизайнер шрифтов на GigaChat")
    parser.add_argument("--prompt", help="Текст пожелания")
    parser.add_argument("--revise", type=Path, help="params.json предыдущей версии")
    args = parser.parse_args()

    previous = args.revise
    if previous and not previous.is_file():
        raise ValueError("Не найден params.json предыдущей версии")

    if args.prompt:
        previous = apply_revision(previous, args.prompt) if previous else start_new(args.prompt)
    else:
        request = input("Опиши шрифт (или exit): ").strip()
        if not request or request.lower() == "exit":
            return
        previous = apply_revision(previous, request) if previous else start_new(request)

    # В интерактивном режиме можно делать сколько угодно последовательных правок.
    if args.prompt:
        return
    while True:
        request = input("\nЧто изменить? (exit — завершить): ").strip()
        if request.lower() in {"exit", "выход", "quit"} or not request:
            break
        try:
            previous = apply_revision(previous, request)
        except ValueError as error:
            print("Не получилось изменить шрифт:", error)
            print("Предыдущая версия сохранена. Попробуй уточнить запрос.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print("Ошибка:", error)
        raise SystemExit(1)
