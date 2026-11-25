"""Отдельный процесс генерации TTF для Tkinter.

GUI запускает этот скрипт через subprocess. Если декоративный шрифт
зависнет при сложной обработке, родительский процесс сможет завершить
задачу по тайм-ауту, не закрывая редактор.
"""
from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from time import perf_counter

from engine.advanced_generator import AdvancedConfig, generate_advanced
from engine.advanced_preview import make_comparison


def main() -> int:
    if len(sys.argv) != 3:
        print("Использование: python advanced_worker.py FONT.ttf CONFIG_JSON", file=sys.stderr)
        return 2
    source = Path(sys.argv[1]).resolve()
    config = AdvancedConfig.from_dict(json.loads(sys.argv[2]))
    # Даже если сторонняя библиотека напечатает сообщение, stdout остаётся
    # чистым JSON для интерфейса. Диагностика уходит в stderr.
    with redirect_stdout(sys.stderr):
        result = generate_advanced(source, config=config)
        started = perf_counter()
        preview = make_comparison(source, result, result.parent / "comparison.png")
    report_file = result.parent / "advanced_report.json"
    report = json.loads(report_file.read_text(encoding="utf-8"))
    report["preview_seconds"] = round(perf_counter() - started, 3)
    # Одна JSON-строка. Пользовательские ошибки уходят в stderr.
    print(json.dumps({"ttf": str(result), "preview": str(preview), "report": report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
