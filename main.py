"""Запуск: обычное меню, каталог, генерация из JSON или правка версии."""

import argparse
from pathlib import Path

from engine.catalog import FONTS_DIR, list_fonts
from engine.font_info import save_catalog
from engine.workflow import generate_from_spec, load_json, revise


def manual_mode() -> None:
    """Старый способ запуска тоже сохраняем — выбор через консоль."""
    fonts = list_fonts()
    if not fonts:
        print("Нет TTF в fonts/base")
        return
    print("\nДоступные шрифты:")
    for index, font in enumerate(fonts, 1):
        print(f"{index}. {font.relative_to(FONTS_DIR).as_posix()}")
    index = int(input("Номер: "))
    if not 1 <= index <= len(fonts):
        raise ValueError("Неверный номер")
    font_id = fonts[index - 1].relative_to(FONTS_DIR).as_posix()

    def ask(text: str, default: str) -> str:
        return input(f"{text} [{default}]: ").strip().replace(",", ".") or default

    spec = {
        "base_font": font_id,
        "width": float(ask("Ширина", "0.85")),
        "slant": float(ask("Наклон", "10")),
        "spacing": int(ask("Интервал", "20")),
    }
    print("Готово:", generate_from_spec(spec))


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальный AI Font Generator")
    parser.add_argument("--catalog", action="store_true", help="Создать font_catalog.json")
    parser.add_argument("--config", type=Path, help="Сгенерировать шрифт из JSON")
    parser.add_argument("--revise", type=Path, help="Путь к params.json прошлой версии")
    parser.add_argument("--changes", type=Path, help="JSON с изменениями прошлой версии")
    args = parser.parse_args()

    if args.catalog:
        print("Каталог создан:", save_catalog())
    elif args.config:
        print("Готово:", generate_from_spec(load_json(args.config)))
    elif args.revise and args.changes:
        print("Новая версия:", revise(args.revise, load_json(args.changes)))
    elif args.revise or args.changes:
        parser.error("Для правок нужны оба флага: --revise и --changes")
    else:
        manual_mode()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        print("Ошибка:", error)
