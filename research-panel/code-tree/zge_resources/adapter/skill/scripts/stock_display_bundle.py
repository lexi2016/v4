#!/usr/bin/env python3
"""Select one hash-bound frozen chart; no network, formula computation or fallback."""
import argparse, datetime, hashlib, json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parents[4]
DEFAULT = ROOT / 'zge_resources/adapter/skill/references/STOCK_DISPLAY_TEMPLATE_MANIFEST.json'

class BundleError(ValueError):
    pass

def read_bound(root, spec):
    p = (root / spec['path']).resolve()
    if not p.is_relative_to(root.resolve()):
        raise BundleError('UNSAFE_PATH')
    if not p.is_file():
        raise BundleError('PACKAGE_MISSING')
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec['sha256']:
        raise BundleError('HASH_MISMATCH')
    return json.loads(raw)

def select(symbol, asof, manifest=DEFAULT, root=ROOT):
    m = json.loads(pathlib.Path(manifest).read_text())
    if not re.fullmatch(r'\d{8}', str(asof)):
        raise BundleError('INVALID_DATE')
    try:
        datetime.datetime.strptime(str(asof), '%Y%m%d')
    except ValueError:
        raise BundleError('INVALID_DATE')
    # Exact analysis date, not nearest available date. Historical requests need a
    # separately frozen package; current commentary must never leak backwards.
    if str(asof) != m['analysis_date']:
        raise BundleError('DATE_NOT_PACKAGED')
    source = read_bound(root, m['chart_manifest'])
    records = source['records']
    ids = [r['symbol'] for r in records]
    if len(set(ids)) != len(ids):
        raise BundleError('DUPLICATE_IDENTITY')
    if re.fullmatch(r'\d{6}', symbol):
        matches = [s for s in ids if s.split('.')[0] == symbol]
        if len(matches) != 1:
            raise BundleError('UNKNOWN_OR_AMBIGUOUS_SYMBOL')
        symbol = matches[0]
    if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', symbol) or symbol not in ids:
        raise BundleError('UNKNOWN_SYMBOL')
    record = records[ids.index(symbol)]
    data = read_bound(root, record)
    if data.get('symbol') != symbol:
        raise BundleError('IDENTITY_MISMATCH')
    rows = data.get('chartRows', [])
    dates = [int(r['date']) for r in rows]
    if not dates or dates != sorted(set(dates)):
        raise BundleError('INVALID_BAR_SEQUENCE')
    cutoff = int(data['source']['dailyCutoff'])
    if dates[-1] != cutoff or cutoff > int(asof):
        raise BundleError('DATE_MISMATCH')
    if len(rows) != record['bars'] or dates[-1] != record['last']:
        raise BundleError('COVERAGE_MISMATCH')
    return {'status': 'FROZEN_CHART_ONLY', 'template_id': m['template_id'],
            'symbol': symbol, 'analysis_date': str(asof), 'daily_cutoff': cutoff,
            'quote': None, 'research_report': None,
            'missing': ['This selector does not load quote, history statistics or commentary'],
            'chart': data}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--symbol', required=True)
    p.add_argument('--asof', required=True, help='analysis date YYYYMMDD; exact package only')
    p.add_argument('--manifest', type=pathlib.Path, default=DEFAULT)
    a = p.parse_args()
    try:
        result = select(a.symbol, a.asof, a.manifest)
    except (BundleError, OSError, KeyError, TypeError, ValueError) as e:
        print(json.dumps({'status': 'UNKNOWN', 'reason': str(e), 'symbol': a.symbol,
                          'analysis_date': a.asof, 'chart': None}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
