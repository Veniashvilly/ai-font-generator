"""Командная генерация, если нужно тестировать без графического окна."""

import argparse
import json
from pathlib import Path

from engine.advanced_generator import AdvancedConfig, generate_advanced
from engine.advanced_preview import make_comparison


def main():
    parser = argparse.ArgumentParser(description="TTF: внутренние просветы и засечки")
    parser.add_argument("font", type=Path, help="Путь к исходному .ttf")
    parser.add_argument("--config", type=Path, default=Path("advanced_config.json"))
    args = parser.parse_args()

    config = AdvancedConfig.from_dict(json.loads(args.config.read_text(encoding="utf-8")))
    result = generate_advanced(args.font, config=config)
    preview = make_comparison(args.font, result, result.parent / "comparison.png")
    print("Новый шрифт:", result)
    print("Сравнение:", preview)
    print("Отчёт:", result.parent / "advanced_report.json")


if __name__ == "__main__":
    main()
