"""CLI: python check_ttf.py result.ttf [--source original.ttf]."""
import argparse
import json
from pathlib import Path
from engine.catalog import FONTS_DIR
from engine.ttf_validation import validate_ttf

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Проверка структуры TTF и пробный рендер')
    p.add_argument('ttf', type=Path)
    p.add_argument('--source', type=Path)
    args = p.parse_args()
    try:
        source = args.source
        params = args.ttf.with_name('params.json')
        if source is None and params.is_file():
            data = json.loads(params.read_text(encoding='utf-8'))
            if data.get('base_font'):
                candidate = FONTS_DIR / data['base_font']
                if candidate.is_file():
                    source = candidate
            elif data.get('source') and Path(data['source']).is_file():
                source = Path(data['source'])
        report = validate_ttf(args.ttf, source)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not source:
            print('Исходник не указан: сохранность Unicode относительно исходника не проверена.')
    except Exception as exc:
        print('FAIL:', exc)
        raise SystemExit(1)
