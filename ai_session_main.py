"""Консольное демо совместной работы ИИ и ползунков без фронтенда.

    python ai_session_main.py
    python ai_session_main.py --resume ID_СЕССИИ

Команды после первой генерации:
    width 1.1      — симуляция ползунка ширины
    slant 3        — симуляция ползунка наклона
    spacing 20     — симуляция ползунка интервала
    state          — текущие значения (включая ползунки)
    history        — история версий
    exit           — выход с сохранением состояния
Любой другой текст — запрос правки в GigaChat.
"""

import argparse
import os
import sys

from ai.designer import create_patch, create_spec
from engine.preview import create_preview
from engine.session_state import FontSession
from engine.workflow import generate_from_spec


def show_preview(ttf_path):
    """Предпросмотр всегда относится к последнему сгенерированному TTF."""
    try:
        image = create_preview(ttf_path)
        print("PNG:", image)
        if sys.platform == "win32":
            os.startfile(str(image))
    except Exception as error:
        print("TTF готов, но предпросмотр не открылся:", error)


def print_state(session: FontSession):
    print("\nСессия:", session.data["session_id"])
    print("ТЕКУЩИЕ параметры:", session.params)
    print("Последний готовый TTF:", session.latest_ttf)
    if session.is_dirty:
        print("Есть изменения ползунков: текущий TTF ещё НЕ пересоздан.")
    print("Последняя версия в истории:", session.history[-1]["id"])


def interactive(session: FontSession):
    print("\nКоманды: width 1.1 | slant 3 | spacing 20 | state | history | exit")
    print("Любая другая фраза отправится в GigaChat как правка.")
    print("ID сессии для продолжения позже:", session.data["session_id"])
    print_state(session)

    while True:
        request = input("\nПолзунок / правка / exit: ").strip()
        if not request:
            continue
        if request.casefold() in {"exit", "выход", "quit"}:
            print("Черновик и история сохранены в:", session.path)
            return
        if request.casefold() == "state":
            print_state(session)
            continue
        if request.casefold() == "history":
            for version in session.history:
                print(version["id"], version["kind"], version["params"])
            continue

        parts = request.replace(",", ".").split()
        if len(parts) == 2 and parts[0] in {"width", "slant", "spacing"}:
            try:
                value = int(parts[1]) if parts[0] == "spacing" else float(parts[1])
                changed = session.set_slider(parts[0], value)
                print("Ползунок:", parts[0], "=", value)
                print("Черновик сохранён." if changed else "Значение не изменилось.")
                print("Новый TTF будет создан после следующей правки через ИИ.")
            except (ValueError, TypeError) as error:
                print("Некорректное значение:", error)
            continue

        try:
            # Если пользователь менял ползунки, появится версия-snapshot.
            current, expected_rev = session.prepare_ai_request()
            print("Отправляем ИИ актуальное состояние:", current)
            patch, message = create_patch(request, current)
            print("Ответ дизайнера:", message)
            print("Патч:", patch)

            # Ответ применяется к current, НЕ к параметрам первого TTF.
            ttf, generated = session.apply_ai_patch(patch, expected_rev, message)
            if generated:
                print("Создан новый TTF:", ttf)
                show_preview(ttf)
            else:
                print("Параметры не поменялись, используем последний TTF:", ttf)
            print_state(session)
        except (ValueError, OSError, RuntimeError) as error:
            print("Правка не применена:", error)
            print("Ручные настройки сохранены; предыдущий TTF остался доступным.")


def main():
    parser = argparse.ArgumentParser(description="ИИ + ползунки + сохранение версий")
    parser.add_argument("--resume", help="ID существующей сессии")
    args = parser.parse_args()

    if args.resume:
        session = FontSession.load(args.resume)
        print("Сессия восстановлена.")
        interactive(session)
        return

    request = input("Опиши первый шрифт (или exit): ").strip()
    if not request or request.casefold() in {"exit", "выход"}:
        return
    # Первая успешная генерация создаёт v1.
    spec, message = create_spec(request)
    print("Выбор ИИ:", message)
    ttf = generate_from_spec(spec)
    session = FontSession.start(spec, ttf, message)
    print("Создан первый TTF:", ttf)
    show_preview(ttf)
    interactive(session)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print("Ошибка:", error)
        raise SystemExit(1)
