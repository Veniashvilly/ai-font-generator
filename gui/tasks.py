"""Задачи без Tkinter: вызываются в фоновых потоках окна.

Никакой бэкенд или фронтенд сервиса здесь не создаётся.
Для предпросмотра черновика делаем временный TTF из ОРИГИНАЛЬНОГО
шрифта, не создавая лишнюю версию в output/ или sessions/.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from engine.catalog import FONTS_DIR
from engine.preview import create_preview
from engine.session_state import FontSession
from engine.transform import transform_ttf
from engine.workflow import generate_from_spec, normalize_spec


def read_preview(ttf_path: Path) -> Image.Image:
    """Рендерим настоящий TTF и загружаем PNG в память для Tkinter."""
    preview_path = create_preview(ttf_path)
    with Image.open(preview_path) as picture:
        return picture.convert("RGB").copy()


def start_from_prompt(prompt: str) -> tuple[FontSession, Image.Image, str]:
    """Первый запрос: GigaChat -> спецификация -> TTF -> сессия v1."""
    from ai.designer import create_spec

    spec, message = create_spec(prompt)
    ttf_path = generate_from_spec(spec)
    session = FontSession.start(spec, ttf_path, message)
    return session, read_preview(ttf_path), message


def revise_from_prompt(
    session: FontSession, prompt: str, snapshot: dict, revision: int
) -> tuple[Image.Image, str, bool]:
    """Правка: LLM читает снимок С ПОЛЗУНКАМИ; создаём новую версию."""
    from ai.designer import create_patch

    patch, message = create_patch(prompt, snapshot)
    ttf_path, generated = session.apply_ai_patch(patch, revision, message)
    return read_preview(ttf_path), message, generated


def make_draft_preview(current: dict) -> Image.Image:
    """Показать ползунки точно, но НЕ сохранять новую постоянную версию.

    Временный TTF живёт только во время рисования картинки.
    На диске остаётся JSON рабочего состояния из FontSession.set_slider().
    """
    spec = normalize_spec(current)
    source = FONTS_DIR / spec["base_font"]

    # TemporaryDirectory сам удалит временные файлы при завершении.
    with TemporaryDirectory(prefix="ai_font_draft_") as tmp:
        folder = Path(tmp)
        temp_ttf = folder / "draft.ttf"
        transform_ttf(
            source=source,
            destination=temp_ttf,
            width=float(spec["width"]),
            slant=float(spec["slant"]),
            spacing=int(spec["spacing"]),
            family_name="AIFont Draft Preview",
        )
        # create_preview читает script из params.json по соседству с TTF.
        (folder / "params.json").write_text(
            json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return read_preview(temp_ttf)
