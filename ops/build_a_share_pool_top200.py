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
    if ((ap['selected_count'] is None and union) or (ap['hit_count'] is None and union & top_symbols)
            or (ap['selected_count'] is not None and len(union) != ap['selected_count'])
            or (ap['hit_count'] is not None and len(union & top_symbols) != ap['hit_count'])):
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

# The same read-only 9A projection, requested by date instead of a build-time
# date list. Stored Top200 ranking and authoritative sources are never changed.
A_POOL_IDS = ('a_d1_premarket_pool','a_d1_fupan_watchlist_pool','a_d1_stage7_fenshi_review_pool','a_share_research_recommendation_pool','a_share_baimao_research_map','wechat_public_account_v3_preselect')
STAGES = ('STAGE_0925','STAGE_0930_0935','STAGE_0935_0940','STAGE_0940_0945','STAGE_0945_1030','STAGE_1300_1315','STAGE_1445_1500')
FLAGS = dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)


def _complete_pages(date, read_page):
    pages=[];first=None
    for offset in range(0, 30000, 300):
        page=read_page(date,300,offset=offset)
        if (not page.get('ok') or page.get('trade_date')!=date or page.get('recommendation_status')!='WATCH_ONLY_BACKTEST_GATED' or page.get('write_policy')!='read_only'
                or any(page.get(key) is not False for key in ('production_allowed','buy_gate_updated','orders_sent'))):raise ValueError('POOL_DATE_OR_SAFETY_CONFLICT')
        if first is None:first=page
        if page.get('input_fingerprint')!=first.get('input_fingerprint') or not first.get('input_fingerprint'):raise ValueError('POOL_SNAPSHOT_FINGERPRINT_MISMATCH')
        meta={p['pool_id']:p for p in first.get('pools',[]) if p['pool_id']in A_POOL_IDS}
        if any(p.get('source_sha256')!=meta.get(p['pool_id'],{}).get('source_sha256') for p in page.get('pools',[])if p['pool_id']in A_POOL_IDS):raise ValueError('POOL_SOURCE_SHA_MISMATCH')
        pages.append(page);sets={key:set() for key in A_POOL_IDS};union=set()
        for saved in pages:
            union.update(filter(None,(canonical_symbol(row.get('symbol'))for row in saved.get('a_all_pool_rows',[]))))
            for pool in saved.get('pools',[]):
                if pool['pool_id']in sets:sets[pool['pool_id']].update(filter(None,(canonical_symbol(row.get('symbol'))for row in pool.get('rows',[]))))
        expected=first.get('a_all_pool_row_count')
        if not isinstance(expected,int) or expected<0:raise ValueError('POOL_COUNT_UNCONFIRMED')
        if len(union)==expected and all(len(sets[key])==int(value.get('pool_size')or 0) for key,value in meta.items()):return pages,sets,union
        if len(union)>expected:raise ValueError('POOL_COUNT_CONFLICT')
    raise ValueError('POOL_PAGINATION_INCOMPLETE')


def _ratios(hits,selected,total):
    return dict(top200_coverage_pct=round(hits/total*100,2)if hits is not None and total else None,
                selection_hit_rate_pct=round(hits/selected*100,2)if hits is not None and selected else None)


def _pool_projection(pages,sets,union,top):
    first=pages[0];meta={p['pool_id']:p for p in first.get('pools',[])};rows=[]
    for key in A_POOL_IDS:
        source=meta.get(key,{});members=sets[key];status=source.get('status','CANNOT_CONFIRM');partial=bool(members)and('PARTIAL'in status or not(status in {'READY','MATERIALIZED','AVAILABLE'}or status.endswith('_READY')))
        materialized = bool(members) or (status in {'READY','MATERIALIZED','AVAILABLE'} and source.get('pool_size') == 0 and bool(source.get('source_sha256')))
        hits=len(members&top)if materialized else None
        rows.append(dict(pool_id=key,display_name=source.get('display_name',key),status=status,signal_date=source.get('signal_date'),target_date=source.get('target_date'),row_count=source.get('pool_size',0),materialized=materialized,partial=partial,selected_count=len(members)if materialized else None,hit_count=hits,source_sha256=source.get('source_sha256'),source_path=source.get('source_path'),**_ratios(hits,len(members),len(top))))
    missing=[r['pool_id']for r in rows if not r['materialized']];partial=[r['pool_id']for r in rows if r['partial']];hits=len(union&top)if any(r['materialized'] for r in rows) else None
    return dict(status='PARTIAL_POOL_COVERAGE'if missing or partial else 'READY',materialized=any(r['materialized'] for r in rows),selected_count=len(union)if hits is not None else None,hit_count=hits,top_count=len(top),pool_count=len(rows),materialized_pool_count=sum(r['materialized']for r in rows),missing_pool_ids=missing,partial_pool_ids=partial,api_input_fingerprint=first['input_fingerprint'],api_data_status=first.get('data_status'),pools=rows,**_ratios(hits,len(union),len(top)))


def _natural_receipt(date, stage, stage_root):
    """Explain the existing natural run; never authorize or recreate selection."""
    path = stage_root.parent / 'receipts' / date / stage / 'receipt.json'
    ref = dict(path=str(path))
    try:
        receipt_root = stage_root.parent.resolve() / 'receipts'
        if path.is_symlink() or not path.resolve().is_relative_to(receipt_root):
            raise ValueError('NATURAL_RECEIPT_SOURCE_PATH_ESCAPE')
        if not path.exists():
            return dict(receipt_status='NOT_FOUND', execution_status='NOT_RUN', errors=[])
        ref['sha256'] = sha(path)
        receipt = checked(ref)
        if not isinstance(receipt, dict) or not isinstance(receipt.get('markets'), dict):
            raise ValueError('NATURAL_RECEIPT_STRUCTURE_INVALID')
        market = receipt['markets'].get('A_SHARE', {})
        if not isinstance(market, dict):
            raise ValueError('NATURAL_RECEIPT_MARKET_INVALID')
        if (receipt.get('trade_date') != date or receipt.get('stage_id') != stage
                or receipt.get('dispatch_mode') != 'NATURAL'
                or market.get('market') != 'A_SHARE'
                or any(receipt.get(k) != v for k, v in FLAGS.items())
                or any(k in market and market[k] != v for k, v in FLAGS.items())
                or any(market.get(k, expected) != expected for k, expected in
                       [('trade_date', date), ('stage_id', stage)])):
            raise ValueError('NATURAL_RECEIPT_DATE_STAGE_MARKET_OR_SAFETY_CONFLICT')
        errors = market.get('cannot_confirm', [])
        if not isinstance(errors, list) or any(not isinstance(e, str) for e in errors):
            raise ValueError('NATURAL_RECEIPT_ERRORS_INVALID')
        # Keep categories and their counts, not thousands of per-stock messages.
        counts = {}
        for error in errors:
            category = error.split(':A.')[0]
            counts[category] = counts.get(category, 0) + 1
        failed = any(e.startswith('SELECTION_ERROR:') for e in errors)
        return dict(receipt_status='BOUND_NATURAL_RECEIPT', receipt_source=ref,
                    dispatch_mode='NATURAL', recorded_at=receipt.get('recorded_at'),
                    source_status=market.get('source_status'),
                    selection_status=market.get('selection_status', market.get('status')),
                    reported_selected_rows=market.get('selected_rows'),
                    execution_status='EXECUTION_FAILED' if failed else 'CANNOT_CONFIRM',
                    research_evidence_status='CANNOT_CONFIRM' if errors or market.get('source_status') == 'CANNOT_CONFIRM' else 'READY',
                    errors=list(counts), error_counts=counts)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return dict(receipt_status='CANNOT_CONFIRM', receipt_source=ref,
                    execution_status='CANNOT_CONFIRM', errors=[str(error)])


def _formula_comparison(date, product_root, index, top, pools):
    """Intersect frozen D-1 labels with stored D Top200, outside pool scope."""
    result = dict(status='CANNOT_CONFIRM', target_date=date,
                  scope='D1_FROZEN_FORMULA_LABELS_VS_STORED_TOP200',
                  included_in_source_pool_union=False, rows=[], **FLAGS)
    try:
        from contracts.trading_calendar import (CALENDAR_PATH, load_market_calendar,
                                                previous_session, resolve_market_states, TradingDayState)
        calendar = load_market_calendar()
        if resolve_market_states(calendar, date)['a_share'] != TradingDayState.FULL_TRADING_DAY:
            raise ValueError('TARGET_A_TRADING_DAY_UNCONFIRMED')
        signal = previous_session(calendar, date, market='a_share')
        result.update(signal_date=signal, calendar_source=dict(path=str(CALENDAR_PATH), sha256=sha(CALENDAR_PATH)))
        ref = index.get('dates', {}).get(signal)
        if not ref:
            raise ValueError('EXACT_D1_FORMULA_MANIFEST_MISSING')
        result['manifest_source'] = ref
        manifest = checked(ref)
        product_ref = manifest['artifact']
        result['product_source'] = product_ref
        product = checked(product_ref)
        if (manifest.get('data_date') != signal or product.get('data_date') != signal
                or manifest.get('source_generation') != product.get('source_generation')
                or manifest.get('input_sha256') != product.get('source_identity', {}).get('input_sha256')
                or any(item.get(k) != v for item in (manifest, product) for k, v in FLAGS.items())):
            raise ValueError('FORMULA_DATE_GENERATION_OR_SAFETY_CONFLICT')
        groups = {key: set() for key in ('original', 'nav_smallk', 'nav_pullback', 'nav_breakout')}
        for row in product['rows']:
            if row.get('data_date') != signal:
                raise ValueError('FORMULA_ROW_DATE_CONFLICT')
            symbol = canonical_symbol(row.get('symbol'))
            if not symbol:
                raise ValueError('FORMULA_ROW_MARKET_IDENTITY_CONFLICT')
            for group in str(row.get('groups', '')).split('|'):
                if group in groups:
                    groups[group].add(symbol)
        if any(len(members) != product.get('group_counts', {}).get(key) for key, members in groups.items()):
            raise ValueError('FORMULA_GROUP_COUNT_CONFLICT')
        def summary(key, members):
            hits = len(members & top)
            return dict(group_id=key, signal_date=signal, target_date=date,
                        selected_count=len(members), hit_count=hits,
                        **_ratios(hits, len(members), len(top)))
        rows = [summary('four_group_union', set().union(*groups.values()))]
        rows += [summary(key, members) for key, members in groups.items()]
        v192 = next((p for p in pools['pools'] if p['pool_id'] == 'a_d1_premarket_pool'), {})
        v192_valid = v192.get('signal_date') == signal and v192.get('target_date') == date and v192.get('materialized')
        rows.append(dict(group_id='v192', signal_date=v192.get('signal_date'), target_date=date,
                         status='READY' if v192_valid else 'CANNOT_CONFIRM',
                         **{key: v192.get(key) if v192_valid else None for key in
                            ('selected_count','hit_count','top200_coverage_pct','selection_hit_rate_pct')}))
        result.update(status='READY', rows=rows, manifest_source=ref, product_source=product_ref,
                      historical_PIT=product.get('source_identity', {}).get('historical_PIT'),
                      prediction_claim='NOT_CERTIFIED', history_status=product.get('history_status'))
    except (OSError, ValueError, KeyError, TypeError) as error:
        result['error'] = str(error)
    return result


def _stage_projection(date,stage_root,top):
    stages={};members={};source=None;index_error=None
    try:
        path=stage_root/'selection_latest.json';source=dict(path=str(path),sha256=sha(path));entries=checked(source)['entries']
    except (OSError,ValueError,KeyError) as error:entries={};index_error=str(error)
    for stage in STAGES:
        entry=entries.get(date+'/'+stage+'/A_SHARE');codes=set()
        try:
            if entry is None:raise KeyError('STAGE_NOT_MATERIALIZED')
            role='A_SHARE_SELECTION_'+stage
            if (not isinstance(entry,dict)or entry.get('market')!='A_SHARE'or entry.get('stage_id')!=stage
                    or entry.get('trade_date')!=date or entry.get('role')!=role):raise ValueError('STAGE_ENTRY_MARKET_DATE_STAGE_ROLE_CONFLICT')
            run=entry.get('run_id')
            if (not isinstance(run,str)or not run.startswith('run-')or '/'in run or '\\'in run
                    or entry.get('artifact_relative')!='/'.join(('selection_runs',date,role,run,'artifact.csv'))):raise ValueError('STAGE_ENTRY_RUN_PATH_CONFLICT')
            path=stage_root/entry['artifact_relative']
            if not path.resolve().is_relative_to(stage_root.resolve())or path.is_symlink()or sha(path)!=entry['artifact_sha256']:raise ValueError('STAGE_SOURCE_SHA_MISMATCH')
            with path.open(encoding='utf-8-sig',newline='')as stream:rows=list(csv.DictReader(stream))
            mapped=[canonical_symbol(row.get('code'))for row in rows]
            if any(code is None for code in mapped):raise ValueError('STAGE_ROW_MARKET_IDENTITY_CONFLICT')
            codes=set(mapped)
            stages[stage]=dict(status='READY',row_count=len(rows),unique_codes=len(codes),artifact_relative=entry['artifact_relative'],artifact_sha256=entry['artifact_sha256'],run_id=entry.get('run_id'),hit_count=len(codes&top))
        except (OSError,ValueError,KeyError)as error:stages[stage]=dict(status='NOT_MATERIALIZED'if entry is None else 'CANNOT_CONFIRM',hit_count=None,error=str(error))
        receipt = _natural_receipt(date, stage, stage_root)
        meta = stages[stage]
        meta.update(receipt)
        if index_error and receipt['receipt_status'] == 'NOT_FOUND':
            meta.update(execution_status='CANNOT_CONFIRM', error='STAGE_INDEX_UNCONFIRMED:'+index_error)
        if meta['status'] == 'READY':
            receipt_conflict = (receipt['receipt_status'] == 'CANNOT_CONFIRM' or
                (receipt['receipt_status'] == 'BOUND_NATURAL_RECEIPT' and
                 (receipt.get('reported_selected_rows') != meta['row_count'] or
                  receipt.get('execution_status') == 'EXECUTION_FAILED')))
            if receipt_conflict:
                meta.update(status='CANNOT_CONFIRM', execution_status='CANNOT_CONFIRM',
                            hit_count=None, error='NATURAL_RECEIPT_ARTIFACT_CONFLICT')
                codes = set()
            else:
                partial = receipt.get('research_evidence_status') == 'CANNOT_CONFIRM' or receipt.get('selection_status') in {'PARTIAL_WITH_ROWS', 'CANNOT_CONFIRM'}
                if not codes and partial:
                    meta.update(status='CANNOT_CONFIRM', hit_count=None, execution_status='CANNOT_CONFIRM',
                                error='EMPTY_SELECTION_WITH_UNCONFIRMED_EVIDENCE')
                    members[stage] = set()
                    continue
                meta['execution_status'] = 'PARTIAL_ROWS' if codes and partial else 'MATERIALIZED_ROWS' if codes else 'VALID_EMPTY'
        elif entry is not None:
            meta['execution_status'] = 'CANNOT_CONFIRM'
        members[stage]=codes
    union=set().union(*members.values());available=sum(s['status']=='READY'for s in stages.values());hits=len(union&top)if available else None
    return dict(status='READY'if available==7 else 'PARTIAL_STAGE_COVERAGE',selected_count=len(union)if available else None,hit_count=hits,top_count=len(top),stages=stages,**_ratios(hits,len(union),len(top))),dict(available=available,total=7,missing_stages=[k for k,v in stages.items()if v['status']!='READY']),source


def read_daily_projection(date,read_page,product_root,stage_root,legacy_path):
    """Original saved ranking + pool membership; no producer, I/O writes or latest fallback."""
    from datetime import datetime
    datetime.strptime(date,'%Y%m%d')
    product_root=Path(product_root);stage_root=Path(stage_root);legacy_path=Path(legacy_path)
    legacy=json.loads(legacy_path.read_bytes());result=copy.deepcopy(legacy)
    if legacy.get('schema_version')!='v4.research.a_share_pool_top200.v1':raise ValueError('LEGACY_SCHEMA_CONFLICT')
    legacy_ref=dict(path=str(legacy_path),sha256=sha(legacy_path));index_ref=dict(path=str(product_root/'index.json'),sha256=sha(product_root/'index.json'));index=checked(index_ref);top_ref=index.get('top200',{}).get(date)
    archived=next((row for row in legacy['dates']if row['date']==date),None)
    result.update(requested_date=date,view_policy='EXACT_DATE_SAVED_SOURCE_PROJECTION',archive_source=legacy_ref)
    available=set(legacy.get('available_dates',[]))|set(index.get('top200',{}));result['latest_available_date']=max(available,default=None)
    if not top_ref:
        result['selected_source_status']='ARCHIVED_EXACT_DATE'if archived else 'NOT_MATERIALIZED'
        return result
    top=checked(top_ref);numeric=index.get('dates',{}).get(date);manifest=checked(numeric)if numeric else {};product=checked(manifest['artifact'])if manifest.get('artifact')else {}
    if (top.get('schema')!='V4_A_SHARE_TOP200_V1'or top.get('data_date')!=date or top.get('numeric_manifest')!=numeric
            or top.get('source_generation')!=product.get('source_generation')or top.get('input_sha256')!=product.get('source_identity',{}).get('input_sha256')
            or any(top.get(key)!=value for key,value in FLAGS.items())):raise ValueError('TOP200_NUMERIC_IDENTITY_CONFLICT')
    ranks=top.get('top200',[])
    if len(ranks)!=top.get('top200_count')or not ranks or [r['rank']for r in ranks]!=list(range(1,len(ranks)+1))or len({r['symbol']for r in ranks})!=len(ranks):raise ValueError('TOP200_RANK_OR_SYMBOL_MISMATCH')
    pages,sets,union=_complete_pages(date,read_page)
    if archived:
        # Accepted historical stage references remain frozen; do not mix later reruns.
        entry=project_date(archived,top_ref,pages,stage_root);entry['view_source']='ARCHIVED_EXACT_SNAPSHOT_RECONCILED'
    else:
        symbols={r['symbol']for r in ranks};ap=_pool_projection(pages,sets,union,symbols);seven,coverage,stage_source=_stage_projection(date,stage_root,symbols)
        entry=dict(date=date,status='PARTIAL'if ap['status']!='READY'or seven['status']!='READY'else 'READY',reason='PARTIAL_POOL_OR_STAGE_COVERAGE',a_pool=ap,seven_stage=seven,stage_coverage=coverage,
            top200=dict(top_count=len(ranks),min_change_pct=round(ranks[-1]['change_pct'],4),source='STORED_TOP200_ARTIFACT',source_sha256=top_ref['sha256'],official_input_sha256=top.get('official_input',{}).get('sha256')))
        entry=project_date(entry,top_ref,pages,stage_root);entry['view_source']='CURRENT_EXACT_DATE_SAVED_SOURCES';entry['stage_index_source']=stage_source
    entry['formula_comparison'] = _formula_comparison(date, product_root, index, {canonical_symbol(r['symbol']) for r in ranks}, entry['a_pool'])
    entry['formula_comparison']['index_source'] = index_ref
    after=json.loads((product_root/'index.json').read_bytes())
    if (after.get('top200',{}).get(date)!=top_ref or after.get('dates',{}).get(date)!=numeric
            or after.get('dates',{}).get(entry['formula_comparison'].get('signal_date')) != index.get('dates',{}).get(entry['formula_comparison'].get('signal_date'))):raise ValueError('TOP200_SOURCE_MOVED_DURING_READ')
    result['dates']=[row for row in result['dates']if row['date']!=date]+[entry];result['dates'].sort(key=lambda row:row['date']);result['selected_source_status']='SAME_SNAPSHOT_RECONCILED';result['generated_at']=datetime.now().astimezone().isoformat();result['detail_projection']=dict(policy='NO_RANKING_OR_FORMULA_RECOMPUTATION',top200_artifact=top_ref,numeric_manifest=numeric,source_generation=top['source_generation'],pool_fingerprint=pages[0]['input_fingerprint'],archive_source=legacy_ref)
    return result
