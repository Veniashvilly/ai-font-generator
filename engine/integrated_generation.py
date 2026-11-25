"""Unified generation in an isolated subprocess, with transactional publication."""
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from engine.catalog import ROOT, FONTS_DIR
from engine.advanced_generator import AdvancedConfig
from engine.language import coverage, missing_chars
from engine.generator import _get_cmap
from engine.ttf_validation import validate_ttf

TIMEOUT = 90


def generate_integrated(spec, output_root, parent_version=None):
    source = (FONTS_DIR / spec['base_font']).resolve()
    if not source.is_relative_to(FONTS_DIR.resolve()):
        raise ValueError('Недопустимый путь исходника')
    cmap, _ = _get_cmap(source)
    if missing_chars(cmap, spec['script']):
        raise ValueError('Исходный шрифт не покрывает запрошенный алфавит')
    config = {k: spec[k] for k in asdict(AdvancedConfig())}
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    # Staging on the same filesystem; a failed or timed-out worker cannot publish a result.
    with TemporaryDirectory(prefix='.font_work_', dir=output_root) as tmp:
        staging = Path(tmp)
        try:
            proc = subprocess.run([sys.executable, str(ROOT / 'integrated_worker.py'),
                str(source), str(staging), json.dumps(config)], cwd=ROOT,
                capture_output=True, encoding='utf-8', errors='replace', timeout=TIMEOUT,
                **({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f'Генерация превысила {TIMEOUT} секунд; предыдущий TTF сохранён') from exc
        if proc.returncode:
            raise RuntimeError('Ошибка движка: ' + (proc.stderr or proc.stdout)[-1800:])
        folders = list(staging.glob('advanced_*/result.ttf'))
        if len(folders) != 1:
            raise RuntimeError('Движок не создал единственный результат TTF')
        result = folders[0]
        report = validate_ttf(result, source)
        advanced = json.loads((result.parent / 'advanced_report.json').read_text(encoding='utf-8'))
        report['warnings'].extend(advanced['warnings'])
        covered = coverage(cmap)
        report.update(version=result.parent.name, requested_script=spec['script'],
                      latin_complete=covered['latin'], cyrillic_complete=covered['cyrillic'])
        params = {**spec, 'source': str(source), 'parent_version': parent_version,
                  'family_name': report['family_name'], 'has_basic_cyrillic': covered['cyrillic']}
        for name, data in [('params.json', params), ('quality_report.json', report)]:
            (result.parent / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        target = output_root / result.parent.name
        result.parent.rename(target)
        return target / 'result.ttf'
