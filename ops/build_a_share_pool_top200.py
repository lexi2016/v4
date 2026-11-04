"""Add stock detail to the existing read-only A_SHARE_POOL_TOP200 snapshot.

Continuation of reviewed_r1/build_a_share_pool_top200.py, not a producer:
no ranking, formulas, history recomputation, pointer or authoritative writes.
Reads only stored Top200 rows, hash-bound snapshot stages and the existing
localhost preselection projection. Unmatched dates retain explicit gaps.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked(ref: dict) -> dict:
    path = Path(ref['path'])
    if sha(path) != ref['sha256']:
        raise ValueError('SOURCE_SHA_MISMATCH')
    return json.loads(path.read_bytes())


def canonical_symbol(value: str) -> str | None:
    value = str(value or '').upper().strip()
    if value.startswith('A.'):
        code = value[2:]
        market = 'SZ' if code.startswith(('00', '30')) else 'SH' if code.startswith(('60', '68')) else 'BJ'
        return f'{code}.{market}' if len(code) == 6 and code.isdigit() else None
    if len(value) == 9 and value[:3] in {'SZ.', 'SH.', 'BJ.'} and value[3:].isdigit():
        value = value[3:] + '.' + value[:2]
    if len(value) == 9 and value[:6].isdigit() and value[6:] in {'.SZ', '.SH', '.BJ'}:
        return value
    return None


def fetch_pool_pages(date: str, api_base: str, cache: Path) -> list[dict]:
    """Reuse the existing owner projection; complete all pools, not just union."""
    pages = []
    for offset in range(0, 2400, 300):
        query = urllib.parse.urlencode(dict(date=date, limit=300, offset=offset))
        request = urllib.request.Request(f'{api_base}/api/v4/preselection-pools?{query}', headers={'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=120) as response:
            page = json.load(response)
        (cache / f'{date}-{offset}.json').write_text(json.dumps(page, ensure_ascii=False))
        if not page.get('ok') or page.get('trade_date') != date:
            raise ValueError('POOL_DATE_MISMATCH')
        pages.append(page)
        union = {r.get('symbol') for p in pages for r in p.get('a_all_pool_rows', [])}
        pools = {p['pool_id']: {r.get('symbol') for page in pages for group in page.get('pools', []) if group['pool_id'] == p['pool_id'] for r in group.get('rows', [])} for p in pages[0].get('pools', []) if p.get('market') == 'A' or p['pool_id'].startswith('a_') or p['pool_id'] == 'wechat_public_account_v3_preselect'}
        if len(union) >= pages[0].get('a_all_pool_row_count', 0) and all(len(pools.get(p['pool_id'], set())) >= p.get('pool_size', 0) for p in pages[0].get('pools', []) if p['pool_id'] in pools):
            return pages
    raise ValueError('POOL_PAGINATION_INCOMPLETE')


def project_date(entry: dict, top_ref: dict, pages: list[dict], stage_root: Path) -> dict:
    """Pure membership mapping; validate the frozen statistics before publishing."""
    result = copy.deepcopy(entry)
    top = checked(top_ref)
    definition = entry['top200']
    if top.get('data_date') != entry['date']:
        raise ValueError('TOP200_DATE_MISMATCH')
    source_sha = definition['source_sha256']
    if definition['source'] == 'STORED_TOP200_ARTIFACT':
        if top_ref['sha256'] != source_sha:
            raise ValueError('TOP200_SNAPSHOT_SHA_MISMATCH')
    elif top.get('official_package', {}).get('sha256') != source_sha or top.get('official_input', {}).get('sha256') != definition.get('official_input_sha256'):
        raise ValueError('TOP200_OFFICIAL_SOURCE_MISMATCH')
    rows = top['top200']
    if len(rows) != definition['top_count'] or round(rows[-1]['change_pct'], 4) != definition['min_change_pct']:
        raise ValueError('TOP200_SNAPSHOT_COUNT_OR_BOUNDARY_MISMATCH')
    ranks = [r['rank'] for r in rows]
    if ranks != list(range(1, len(rows) + 1)) or len({r['symbol'] for r in rows}) != len(rows):
        raise ValueError('TOP200_RANK_OR_SYMBOL_MISMATCH')
    ap = entry['a_pool']
    pool_sets = {p['pool_id']: set() for p in ap['pools']}
    union = set()
    for page in pages:
        if page.get('trade_date') != entry['date'] or page.get('input_fingerprint') != ap['api_input_fingerprint']:
            raise ValueError('POOL_SNAPSHOT_FINGERPRINT_MISMATCH')
        for pool in page.get('pools', []):
            pool_id = pool['pool_id']
            if pool_id not in pool_sets:
                continue
            frozen = next(p for p in ap['pools'] if p['pool_id'] == pool_id)
            if pool.get('source_sha256') != frozen.get('source_sha256'):
                raise ValueError('POOL_SOURCE_SHA_MISMATCH')
            pool_sets[pool_id].update(filter(None, (canonical_symbol(r.get('symbol')) for r in pool.get('rows', []))))
        union.update(filter(None, (canonical_symbol(r.get('symbol')) for r in page.get('a_all_pool_rows', []))))
    top_symbols = {r['symbol'] for r in rows}
    if len(union) != ap['selected_count'] or len(union & top_symbols) != ap['hit_count']:
        raise ValueError('POOL_UNION_RECONCILIATION_FAILED')
    for pool in ap['pools']:
        members = pool_sets[pool['pool_id']]
        if pool['materialized'] and (len(members) != pool['selected_count'] or len(members & top_symbols) != pool['hit_count']):
            raise ValueError('POOL_RECONCILIATION_FAILED')
    stage_sets = {}
    for stage, meta in entry['seven_stage']['stages'].items():
        # Never consult latest: missing snapshot stages remain missing after reruns.
        if meta.get('status') != 'READY':
            continue
        path = stage_root / meta['artifact_relative']
        if not path.resolve().is_relative_to(stage_root.resolve()) or sha(path) != meta['artifact_sha256']:
            raise ValueError('STAGE_SOURCE_SHA_MISMATCH')
        with path.open(encoding='utf-8-sig', newline='') as stream:
            stage_rows = list(csv.DictReader(stream))
        members = set(filter(None, (canonical_symbol(row.get('code')) for row in stage_rows)))
        if len(stage_rows) != meta['row_count'] or len(members) != meta['unique_codes'] or len(members & top_symbols) != meta['hit_count']:
            raise ValueError('STAGE_RECONCILIATION_FAILED')
        stage_sets[stage] = members
    seven_union = set().union(*stage_sets.values()) if stage_sets else set()
    if stage_sets and (len(seven_union) != entry['seven_stage']['selected_count'] or len(seven_union & top_symbols) != entry['seven_stage']['hit_count']):
        raise ValueError('SEVEN_STAGE_UNION_RECONCILIATION_FAILED')
    result['stocks'] = [dict(rank=r['rank'], code=r['symbol'], name=r.get('name'), change_pct=r.get('change_pct'), pool_hit=r['symbol'] in union, pool_memberships=[p for p, members in pool_sets.items() if r['symbol'] in members], stage_memberships=[stage for stage, members in stage_sets.items() if r['symbol'] in members]) for r in rows]
    result['detail_status'] = 'SAME_SNAPSHOT_RECONCILED'
    result['detail_evidence'] = dict(top200_artifact=top_ref, top200_source_sha256=source_sha, api_input_fingerprint=ap['api_input_fingerprint'], stage_policy='FROZEN_SNAPSHOT_REFERENCES_ONLY', counts=dict(rows=len(rows), pool_hits=sum(r['pool_hit'] for r in result['stocks']), stage_hits=sum(bool(r['stage_memberships']) for r in result['stocks'])))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--product-index', type=Path, required=True)
    parser.add_argument('--stage-root', type=Path, required=True)
    parser.add_argument('--api-base', default='http://127.0.0.1:8873')
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if urllib.parse.urlsplit(args.api_base).hostname not in {'127.0.0.1', 'localhost', '::1'}:
        parser.error('localhost read-only projection only')
    snapshot = json.loads(args.snapshot.read_bytes())
    if snapshot.get('schema_version') != 'v4.research.a_share_pool_top200.v1':
        parser.error('unsupported frozen snapshot')
    index = json.loads(args.product_index.read_bytes())
    args.cache.mkdir(parents=True, exist_ok=True)
    result = copy.deepcopy(snapshot)
    for pos, entry in enumerate(snapshot['dates']):
        ref = index.get('top200', {}).get(entry['date'])
        if not entry.get('top200') or not ref:
            result['dates'][pos]['detail_status'] = 'CANNOT_CONFIRM'
            result['dates'][pos]['detail_gap'] = '缺少同日同来源的已保存榜单明细；保留原有统计，不使用其他日期。'
            continue
        try:
            pages = fetch_pool_pages(entry['date'], args.api_base.rstrip('/'), args.cache)
            result['dates'][pos] = project_date(entry, ref, pages, args.stage_root)
        except (ValueError, OSError, KeyError) as error:
            result['dates'][pos]['detail_status'] = 'CANNOT_CONFIRM'
            result['dates'][pos]['detail_gap'] = '明细来源与原统计无法完成同快照核对；保留原统计，明细不可确认。'
            result['dates'][pos]['detail_error'] = str(error)
    result['detail_projection'] = dict(snapshot_sha256=sha(args.snapshot), snapshot_generated_at=snapshot['generated_at'], script_sha256=sha(Path(__file__)), policy='NO_RANKING_OR_FORMULA_RECOMPUTATION')
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({e['date']: dict(status=e['detail_status'], rows=len(e.get('stocks', [])), error=e.get('detail_error')) for e in result['dates']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
