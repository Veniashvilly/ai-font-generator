"""Поиск исходных TTF-шрифтов в каталоге проекта."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "fonts" / "base"
OUTPUT_DIR = ROOT / "output"


def list_fonts() -> list[Path]:
    """Находим файлы TTF даже во вложенных папках, например Roboto/."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(
        (path for path in FONTS_DIR.rglob("*") if path.is_file() and path.suffix.lower() == ".ttf"),
        key=lambda path: str(path).lower(),
    )
