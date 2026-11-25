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
from engine.integrated_generation import generate_integrated
from engine.workflow import generate_from_spec, normalize_spec


def read_preview(ttf_path: Path) -> Image.Image:
    """Рендерим настоящий TTF и загружаем PNG в память для Tkinter."""
    preview_path = create_preview(ttf_path)
    with Image.open(preview_path) as picture:
        return picture.convert("RGB").copy()


def _effect_summary(ttf_path):
    path = ttf_path.with_name("advanced_report.json")
    if not path.is_file():
        return ""
    r = json.loads(path.read_text(encoding="utf-8"))
    return (f" Изменения геометрии: просветы {r['counter_contours_changed']}, "
            f"жирность (контуры) {r['weight_changed_contours']}, "
            f"скруглённые узлы {r['rounded_points']}, засечки {r['serifs_added']}. "
            "Подробности: advanced_report.json.")


def start_from_prompt(prompt: str) -> tuple[FontSession, Image.Image, str]:
    """Первый запрос: GigaChat -> спецификация -> TTF -> сессия v1."""
    from ai.designer import create_spec

    spec, message = create_spec(prompt)
    ttf_path = generate_from_spec(spec)
    session = FontSession.start(spec, ttf_path, message)
    return session, read_preview(ttf_path), message + _effect_summary(ttf_path)


def revise_from_prompt(
    session: FontSession, prompt: str, snapshot: dict, revision: int
) -> tuple[Image.Image, str, bool]:
    """Правка: LLM читает снимок С ПОЛЗУНКАМИ; создаём новую версию."""
    from ai.designer import create_patch

    patch, message = create_patch(prompt, snapshot)
    ttf_path, generated = session.apply_ai_patch(patch, revision, message)
    return read_preview(ttf_path), message + _effect_summary(ttf_path), generated


def make_draft_preview(current: dict) -> Image.Image:
    """Показать ползунки точно, но НЕ сохранять новую постоянную версию.

    Временный TTF живёт только во время рисования картинки.
    На диске остаётся JSON рабочего состояния из FontSession.set_slider().
    """
    spec = normalize_spec(current)
    with TemporaryDirectory(prefix="ai_font_draft_") as tmp:
        result = generate_integrated(spec, Path(tmp))
        return read_preview(result)


def export_current(session):
    ttf, generated = session.save_current()
    return read_preview(ttf), "Ручное сохранение." + _effect_summary(ttf), generated
