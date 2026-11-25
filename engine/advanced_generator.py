"""Генерация экспериментальных TTF с дополнительными параметрами.

Совместим с обычным Windows + Python + fontTools; без FontForge.
Не зависит от модулей GigaChat и уже имеющегося Tkinter-редактора.
"""

from __future__ import annotations

import json
import math
import uuid
from time import perf_counter
from dataclasses import asdict, dataclass
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from engine.advanced_effects import SerifSettings, change_counter_size, add_serifs
from engine.stroke_effects import change_weight, round_corners

ROOT = Path(__file__).resolve().parent.parent

# Порог для эффектов, потенциально портящих декоративные штрихи.
# Простое изменение ширины/наклона продолжит работать для таких глифов.
MAX_EFFECT_COORDS = 360
MAX_EFFECT_CONTOURS = 18


@dataclass(frozen=True)
class AdvancedConfig:
    """Все параметры, которые можно задавать вручную (и позже из ИИ)."""

    width: float = 1.0
    slant: float = 0.0
    spacing: int = 0
    counter_scale: float = 1.0     # 0.7 -> меньше дырки, 1.3 -> больше
    weight_scale: float = 1.0      # 0.8 -> тоньше, 1.25 -> жирнее
    corner_roundness: float = 0.0  # 0.0 -> без эффекта, 0.45 -> заметно мягче
    serif_style: str = "none"     # none | slab | wedge | bracket
    serif_length: float = 0.045   # доля em
    serif_thickness: float = 0.035
    serif_bracket: float = 0.025
    serif_angle: float = 0.0      # градусы

    @classmethod
    def from_dict(cls, values: dict):
        """Запрещаем произвольные ключи, особенно если конфиг создал ИИ."""
        if not isinstance(values, dict):
            raise ValueError("Параметры должны быть JSON-объектом")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(values) - allowed
        if unknown:
            raise ValueError("Неизвестные параметры: " + ", ".join(sorted(unknown)))
        config = cls(**values)
        config.validate()
        return config

    def validate(self):
        for name, value, minimum, maximum in (
            ("width", self.width, 0.55, 1.4),
            ("slant", self.slant, -20, 20),
            ("counter_scale", self.counter_scale, 0.7, 1.3),
            ("weight_scale", self.weight_scale, 0.75, 1.35),
            ("corner_roundness", self.corner_roundness, 0.0, 0.45),
        ):
            if type(value) not in (int, float) or not minimum <= value <= maximum or not math.isfinite(value):
                raise ValueError(f"{name}: диапазон {minimum}..{maximum}")
        if type(self.spacing) is not int or not -20 <= self.spacing <= 100:
            raise ValueError("spacing: целое число от -20 до 100")
        SerifSettings(
            style=self.serif_style,
            length=self.serif_length,
            thickness=self.serif_thickness,
            bracket=self.serif_bracket,
            angle=self.serif_angle,
        ).validate()


def _rename_font(font: TTFont, code: str, slant: float):
    """Изменяем имя, чтобы новый файл не конфликтовал с оригиналом."""
    family = f"AIFont Advanced {code}"
    names = {
        1: family,
        2: "Regular",
        3: f"AIFontAdvanced-{code}; demo-1",
        4: family + " Regular",
        6: f"AIFontAdvanced{code}-Regular",
        16: family,
        17: "Regular",
    }
    table = font["name"]
    for rec in list(table.names):
        if rec.nameID in names:
            try:
                table.setName(names[rec.nameID], rec.nameID, rec.platformID, rec.platEncID, rec.langID)
            except UnicodeEncodeError:
                pass
    for name_id, text in names.items():
        table.setName(text, name_id, 3, 1, 0x409)
    if "post" in font:
        font["post"].italicAngle = -slant


def _apply_global_transform(glyph, width: float, slant: float):
    tangent = math.tan(math.radians(slant))
    for i, (x, y) in enumerate(glyph.coordinates):
        glyph.coordinates[i] = (round(x * width + y * tangent), round(y))


def generate_advanced(source: str | Path, output_root: str | Path | None = None,
                      config: AdvancedConfig | None = None) -> Path:
    """Создаёт result.ttf и параметры/отчёт рядом; исходный TTF не изменяет."""
    start_total = perf_counter()
    config = config or AdvancedConfig()
    config.validate()
    source = Path(source).resolve()
    if not source.is_file() or source.suffix.lower() != ".ttf":
        raise FileNotFoundError(f"Не найден исходный статический .ttf: {source}")
    output_root = Path(output_root or (ROOT / "output")).resolve()

    font = TTFont(source)
    try:
        if "glyf" not in font or "fvar" in font or "gvar" in font:
            raise ValueError("Поддерживаются только статические TrueType TTF с таблицей glyf")
        if not font.getBestCmap():
            raise ValueError("В шрифте отсутствует Unicode cmap")
        cmap = font.getBestCmap()
        glyphset = font.getGlyphSet()
        em = font["head"].unitsPerEm
        serif = SerifSettings(
            style=config.serif_style, length=config.serif_length,
            thickness=config.serif_thickness, bracket=config.serif_bracket,
            angle=config.serif_angle,
        )
        # Unicode-код не обязан совпадать с именем глифа.
        from engine.advanced_effects import _STEMS
        glyph_to_char = {}
        for char in _STEMS:
            glyph_name = cmap.get(ord(char))
            if glyph_name:
                glyph_to_char.setdefault(glyph_name, char)
        # Кривые измеряем только в глифах пользовательских алфавитов,
        # иначе многотысячные шрифты с CJK/иероглифами считались бы слишком долго.
        counter_glyph_names = {
            glyph for cp, glyph in cmap.items()
            if (0x0021 <= cp <= 0x024F or 0x0400 <= cp <= 0x052F)
        }
        sample_names = {cmap[ord(ch)] for ch in "ABOeH8АВОеН" if ord(ch) in cmap}
        sample_complex = 0
        for sample_name in sample_names:
            points, ends, _ = font["glyf"][sample_name].getCoordinates(font["glyf"])
            if len(points) > 140 or len(ends) >= 4:
                sample_complex += 1
        decorative = bool(sample_names and sample_complex * 3 >= len(sample_names))
        if config.weight_scale != 1.0 or config.counter_scale != 1.0:
            try:
                import shapely
                from engine.filled_geometry import change_filled_weight, change_filled_counters
            except ImportError as exc:
                raise RuntimeError("Для v8 установи shapely: python -m pip install shapely") from exc
        filled_stats = {"weight_glyphs": 0, "counter_glyphs": 0, "errors": 0}
        counter_stats = {"limited": 0, "skipped": 0, "complexity_skipped": 0}
        effect_skipped = {"weight": 0, "roundness": 0, "serifs": 0}
        counter_examples = {}  # Для диагностики: одна настройка — разные безопасные масштабы
        interesting = {ch: cmap.get(ord(ch)) for ch in "ABOАВОeqя8"}
        serif_stats = {"ambiguous_stems": 0}
        weight_stats = {"changed_contours": 0}
        round_stats = {"rounded_points": 0}
        serif_modified_glyphs = set()

        start_glyphs = perf_counter()
        changed_counters = 0
        added_serifs = 0
        new_glyphs = {}
        new_metrics = {}
        for name in font.getGlyphOrder():
            # Разлагаем составные символы: 'Ё' может ссылаться на 'Е' + две точки.
            recorder = DecomposingRecordingPen(glyphset)
            glyphset[name].draw(recorder)
            pen = TTGlyphPen(None)
            recorder.replay(pen)
            glyph = pen.glyph()

            if glyph.numberOfContours > 0:
                # Режим повышенной безопасности для декоративных шрифтов.
                complex_glyph = (glyph.numberOfContours > MAX_EFFECT_CONTOURS
                                 or len(glyph.coordinates) > MAX_EFFECT_COORDS)
                if config.corner_roundness > 0 and complex_glyph:
                    effect_skipped["roundness"] += 1
                if config.serif_style != "none" and name in glyph_to_char and complex_glyph:
                    effect_skipped["serifs"] += 1
                if config.weight_scale != 1.0:
                    per_weight_stats = {}
                    if decorative or complex_glyph:
                        count = change_filled_weight(glyph, config.weight_scale, em, per_weight_stats)
                        filled_stats["weight_glyphs"] += bool(count)
                        filled_stats["errors"] += bool(per_weight_stats.get("fallback_error"))
                        if not count:
                            effect_skipped["weight"] += 1
                    else:
                        count = change_weight(glyph, config.weight_scale, em, stats=per_weight_stats)
                    weight_stats["changed_contours"] += count
                if name in counter_glyph_names and config.counter_scale != 1.0:
                    # У каждого глифа общий коэффициент для ВСЕХ его отверстий.
                    # Запоминаем, где он ограничен, но не создаём новые ползунки.
                    per_glyph_stats = {}
                    if decorative or complex_glyph:
                        counter_count = change_filled_counters(glyph, config.counter_scale, em, per_glyph_stats)
                    else:
                        counter_count = change_counter_size(glyph, config.counter_scale, em, stats=per_glyph_stats)
                        if not counter_count and (per_glyph_stats.get("complexity_skipped") or not per_glyph_stats.get("holes_found")):
                            old_stats = per_glyph_stats
                            per_glyph_stats = {}
                            counter_count = change_filled_counters(glyph, config.counter_scale, em, per_glyph_stats)
                            if per_glyph_stats.get("fallback_error"):
                                per_glyph_stats["complexity_skipped"] = old_stats.get("complexity_skipped", False)
                    filled_stats["counter_glyphs"] += bool(per_glyph_stats.get("filled_geometry"))
                    filled_stats["errors"] += bool(per_glyph_stats.get("fallback_error"))
                    changed_counters += counter_count
                    for stat_key in ("limited", "skipped"):
                        counter_stats[stat_key] += per_glyph_stats.get(stat_key, 0)
                    if per_glyph_stats.get("complexity_skipped"):
                        counter_stats["complexity_skipped"] += 1
                    for symbol, glyph_id in interesting.items():
                        if glyph_id == name and per_glyph_stats:
                            counter_examples[symbol] = {
                                "holes": per_glyph_stats.get("holes_found", 0),
                                "effective_scale": per_glyph_stats.get("effective_scale", 1.0),
                                "changed": counter_count,
                                "contours_total": per_glyph_stats.get("contours_total", 0),
                                "skip_reason": per_glyph_stats.get("skip_reason", ""),
                                "recovery_used": per_glyph_stats.get("recovery_used", False),
                                "filled_geometry": per_glyph_stats.get("filled_geometry", False),
                            }
                if not complex_glyph and name in glyph_to_char:
                    count = add_serifs(
                        glyph, glyph_to_char[name], em, serif, stats=serif_stats
                    )
                    added_serifs += count
                    if count:
                        serif_modified_glyphs.add(name)
                if config.corner_roundness > 0 and not complex_glyph:
                    per_round_stats = {}
                    round_stats["rounded_points"] += round_corners(
                        glyph, config.corner_roundness, em=em, stats=per_round_stats
                    )
                _apply_global_transform(glyph, config.width, config.slant)

            new_glyphs[name] = glyph
            original_advance, _ = font["hmtx"][name]
            proposed = round(original_advance * config.width + config.spacing)
            new_metrics[name] = max(1, proposed)

        glyf_table = font["glyf"]
        for name, glyph in new_glyphs.items():
            glyf_table[name] = glyph

        for name, glyph in new_glyphs.items():
            if glyph.numberOfContours > 0:
                glyph.recalcBounds(glyf_table)
                x_min = glyph.xMin
                # Предохраняем крайний правый контур от обрезания боковым размером.
                right_margin = round(max(12, em * 0.015))
                advance = max(new_metrics[name], glyph.xMax + right_margin)
            else:
                x_min = 0
                advance = new_metrics[name]
            font["hmtx"][name] = (max(1, round(advance)), x_min)

        glyphs_seconds = perf_counter() - start_glyphs
        start_overlaps = perf_counter()
        # Если установлен skia-pathops, объединяем пересекающиеся засечки
        # с исходными контурами. Это важнее, чем просто добавить отдельные
        # многоугольники: перекрытия могут рисоваться некорректно.
        overlaps_merged = False
        if serif_modified_glyphs:
            try:
                import pathops  # noqa: F401 (проверка необязательной зависимости)
            except ImportError:
                pass
            else:
                from fontTools.ttLib.removeOverlaps import removeOverlaps
                # Не скрываем ошибки: если объединение не удалось, генерация
                # сообщит об этом, а не выдаст испорченный файл как исправный.
                removeOverlaps(font, glyphNames=sorted(serif_modified_glyphs),
                               removeHinting=True, ignoreErrors=False)
                overlaps_merged = True

        overlaps_seconds = perf_counter() - start_overlaps
        # При изменении геометрии старый GPOS/кернинг/хинтинг уже не соответствует
        # новым контурам: в MVP отключаем, в дальнейшем потребуется пересчёт.
        for tag in ("kern", "GPOS", "fpgm", "prep", "cvt "):
            if tag in font:
                del font[tag]

        version_id = uuid.uuid4().hex[:10]
        folder = output_root / f"advanced_{version_id}"
        folder.mkdir(parents=True, exist_ok=False)
        destination = folder / "result.ttf"
        _rename_font(font, version_id, config.slant)
        font.recalcBBoxes = True
        start_save = perf_counter()
        font.save(destination)
        save_seconds = perf_counter() - start_save
    finally:
        font.close()

    warnings = [
        "Экспериментальные алгоритмы: качество засечек зависит от формы исходного шрифта.",
        "Точность контуров, кернинг и пригодность для печати требуют проверки в FontForge.",
    ]
    if config.serif_style != "none":
        warnings.append("Засечки работают для ограниченного набора букв с распознаваемыми штрихами.")
        if serif_modified_glyphs and not overlaps_merged:
            warnings.append("Для объединения пересечений засечек установи: pip install skia-pathops")
    if counter_stats["limited"]:
        warnings.append(
            f"На {counter_stats['limited']} отверстиях изменение было безопасно ограничено "
            "из-за малой толщины исходных штрихов."
        )
    if counter_stats["complexity_skipped"]:
        warnings.append(
            f"У {counter_stats['complexity_skipped']} сложных глифов просветы оставлены без изменений "
            "во избежание зависания и разрушения декоративных контуров."
        )
    if any(effect_skipped.values()):
        warnings.append("На самых сложных глифах жирность/углы/засечки частично пропущены.")
    if config.counter_scale != 1.0 and changed_counters == 0:
        warnings.append("Не найдены подходящие внутренние контуры либо они слишком сложны для безопасной обработки.")
    if filled_stats["errors"]:
        warnings.append(f"Векторная обработка не удалась у {filled_stats['errors']} операций; исходная форма сохранена.")
    if filled_stats["weight_glyphs"] or filled_stats["counter_glyphs"]:
        warnings.append("Сложные глифы обработаны по залитой области; кривые в них приближены отрезками.")
    if config.weight_scale != 1.0 and weight_stats["changed_contours"] == 0:
        warnings.append("Жирность не изменила контуры: вероятно, шрифт слишком простой или повреждён.")
    if config.corner_roundness > 0 and round_stats["rounded_points"] == 0:
        warnings.append("Скругление не нашло подходящих острых узлов в текущем шрифте.")

    # После сохранения отдельно проверяем новый файл.
    start_validate = perf_counter()
    with TTFont(destination) as result:
        if "glyf" not in result or not result.getBestCmap():
            raise RuntimeError("Результат не прошёл проверку структуры TTF")
        if set(result.getBestCmap()) != set(cmap):
            raise RuntimeError("После генерации изменилась карта Unicode")
        tested_glyphs = len(result.getGlyphOrder())

    validate_seconds = perf_counter() - start_validate
    total_seconds = perf_counter() - start_total
    (folder / "params.json").write_text(json.dumps({
        "source": str(source),
        **asdict(config),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "advanced_report.json").write_text(json.dumps({
        "source": source.name,
        "timing_seconds": {
            "glyph_processing": round(glyphs_seconds, 3),
            "overlap_removal": round(overlaps_seconds, 3),
            "ttf_save": round(save_seconds, 3),
            "verification": round(validate_seconds, 3),
            "total": round(total_seconds, 3),
        },
        "glyphs_total": tested_glyphs,
        "counter_contours_changed": changed_counters,
        "weight_changed_contours": weight_stats["changed_contours"],
        "rounded_points": round_stats["rounded_points"],
        "serifs_added": added_serifs,
        "counter_safety_limited": counter_stats["limited"],
        "counter_safety_skipped": counter_stats["skipped"],
        "counter_complexity_skipped": counter_stats["complexity_skipped"],
        "effect_complexity_skipped": effect_skipped,
        "counter_examples": counter_examples,
        "filled_geometry_v8": filled_stats,
        "decorative_geometry": decorative,
        "serif_ambiguous_stems": serif_stats["ambiguous_stems"],
        "serif_overlaps_merged": overlaps_merged,
        "warnings": warnings,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return destination
