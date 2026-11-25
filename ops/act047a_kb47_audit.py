"""Read-only KB47 audit. History and outcomes are separate commands and receipts."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import io
from itertools import zip_longest
import json
import math
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile

L1 = (5, 11, 13, 14, 16, 17, 19, 20, 21, 22, 24, 25, 26, 29)
METHODS = (*L1[:10], 23, *L1[10:])
ORIG_BUY = (5, 13, 19, 20, 22, 25, 26, 29)
HORIZONS = (2, 5, 10)
GOLD, WATCH, REJECT = 'GOLD_CONFIRMED', 'BORDERLINE_WATCH', 'REJECTED_FAKE'
LABELS = (GOLD, WATCH, REJECT)
COHORTS = ('OVERLAP', 'SINGLE', 'ALL')
EXPECTED = dict(zip(COHORTS, [(10, 12, 8), (31, 53, 67), (41, 65, 75)]))
KEYS = ('ts_code', 'trade_date')
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False,
             orders_sent=False, S_FIT=0, B_FIT=0, preprocess_fit=0, parameter_search=0,
             training_gold_approved=False)
A41 = 'pft_act041a_kb47_full_history_20261125'
A42 = 'pft_act042a_kb47_batch0_20261125'
A43 = 'pft_act043a_kb47_v11_batch1_20261125'
A44 = 'tactic_act044a_20261125'
A46 = 'tactic_act046a_20261125'
CLOSEOUT_SHA = 'f46b6a873b0aa3ca2627b3e4d8771bc8a021d8f14d1245c1b1f4f045f9f188dd'
SKELETON_SHA = 'd99a8d02353c5db63316f08c8d889ea2342e68da4c7393d04f805a8136b6f766'
BLIND_SHA = '3e449a51d85703747fa576681dad5d2857a94ab6b567792d9aff8e68b5de31d1'
LATE_MAP_SHA = '5833cc99fe3215c88979bb5f6a3002066c6f433f0dd3d22bf2a3613c4a71ec10'
NATIVE_EXPORT_SHA = '5000e452869c874b498d9653c43b67f69edb8ea6ab925ce226fda4f94fa483e5'
B0_MAP_SHA = '6011bb90132f32cd1cb826f3d5d443160630f3ab3964d1b05997d09d3670283f'
SIGNALS = (
    *[(f'V11_{m:02}', m, f'v11_candidate_{m:02}', 'mechanical') for m in L1],
    *[(f'044A_{m:02}_eligible', m, f'm{m:02}_eligible_state', 'eligibility') for m in (5, 17, 21, 22, 25)],
    ('044A_05_F08', 5, 'm05_raw_f08', 'raw'),
    ('044A_17_F05', 17, 'm17_raw_f05', 'raw'),
    ('044A_21_F04', 21, 'm21_raw_f04', 'raw'),
    ('044A_21_course', 21, 'm21_course_b3', 'observation'),
    ('044A_21_restart', 21, 'm21_restart_variant', 'observation'),
    ('044A_22_geometry', 22, 'm22_raw_changan_proxy', 'observation'),
    ('044A_25_D_proxy', 25, 'm25_repair_on_D_proxy', 'observation'),
    ('046A_05_human_fact_review', 5, 'act046a_m05_needs_human_fact_review', 'observation'),
    ('046A_17_F09', 17, 'act046a_m17_USER_F09_SIGNAL_CROSS', 'observation'),
    ('046A_17_axis', 17, 'act046a_m17_COURSE_260422_DIF_AXIS_CROSS', 'observation'),
    ('046A_17_F09_and_F05', 17, 'act046a_m17_USER_F09_SIGNAL_CROSS_same_day_confirmed_with_f05', 'observation'),
    ('046A_17_gap_up_yin', 17, 'act046a_r3_is_gap_up_yin_bar', 'refutation'),
    ('046A_17_axis_and_F05', 17, 'act046a_m17_COURSE_260422_DIF_AXIS_CROSS_same_day_confirmed_with_f05', 'observation'),
    ('046A_25_price_clock', 25, 'act046a_m25_observed_price_clock', 'observation'),
    ('046A_25_strict_clock', 25, 'act046a_m25_repair_clock', 'observation'),
    ('23_frozen_signal', 23, None, 'unavailable'),
    ('046C_23_candidate_note', 23, 'm23_candidate_note_present', 'review_note'),
)
ENTRY = ('D1_entry_status', 'D1_fillability_proxy')
OUTCOMES = (*ENTRY, *(f'T{h}_{field}' for h in HORIZONS for field in
    ('status', 'return_from_D_close', 'net_from_D_close_mark', 'net_from_D1_open_fill_proxy')))
HARD_FEATURES = ('D_open', 'D_close', 'D_pre_close', 'D_zge_white_line', 'D_zge_yellow_line',
                 'prior_active_anchor_date', 'prior_active_anchor_low')
HARD_NAMES = ('GAP_UP_YIN', 'REPAIR_PROXY_OLD_ANCHOR_BELOW', 'W_LE_Y_ANCHOR_BELOW')


def require(ok, error):
    if not ok:
        raise ValueError(error)


def index(rows, key):
    result = {key(r): r for r in rows}
    require(len(rows) == len(result), 'DUPLICATE_KEYS')
    return result


def security_day(r):
    return r['ts_code'], int(r['trade_date'])


def read_csv(data):
    with io.StringIO(data.decode('utf-8-sig'), newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        require(len(set(reader.fieldnames or [])) == len(reader.fieldnames or [])
                and all(None not in r and all(v is not None for v in r.values()) for r in rows),
                'CSV_SCHEMA_OR_RAGGED_ROWS')
        return rows


def csv_bytes(rows):
    stream = io.StringIO(newline='')
    w = csv.DictWriter(stream, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return stream.getvalue().encode('utf-8')


class Reads:
    def __init__(self):
        self.refs = {}

    def bytes(self, path, digest=None):
        data = path.read_bytes()
        match = sha256(data).hexdigest()
        require(digest is None or match == digest, f'SHA_MISMATCH:{path.name}')
        self.refs[str(path)] = {'bytes': len(data), 'sha256': match}
        return data

    def info(self, path, files, prefix):
        shards = [f for f in files if Path(f.get('path', f.get('name', ''))).name.startswith(prefix)]
        require(bool(shards), f'NO_SHARDS:{prefix}')
        paths = []
        for item in shards:
            p = path / Path(item.get('path', item.get('name', ''))).name
            self.bytes(p, item['sha256'])
            paths.append(p)
        return sorted(paths)


def parquet_rows(paths, cols, filters=None):
    import pyarrow.dataset as ds

    for p in paths:
        scanner = ds.dataset(p, format='parquet').scanner(
            columns=list(cols), filter=filters, batch_size=8192, use_threads=False,
        )
        for batch in scanner.to_batches():
            yield from batch.to_pylist()


def custodian(reads, root):
    b0 = read_csv(reads.bytes(root / A42 / 'ACT042A_CUSTODIAN_MAPPING_01.csv', B0_MAP_SHA))
    b1 = read_csv(reads.bytes(root / A44 / 'lateMap.csv', LATE_MAP_SHA))
    require(len(b0) == len(index(b0, security_day)) == 72 and
            len(b1) == len(index(b1, security_day)) == len(index(b1, lambda r: r['anon_id'])) == 181,
            'CUSTODIAN_COUNT_DRIFT')
    return b0, b1


def positive(value):
    return value is not None and math.isfinite(value) and value > 0


def tri_and(a, b):
    return False if a is False or b is False else True if a is True and b is True else None


def hard_negatives(row, repair_proxy):
    op, close, prev = (row[k] for k in ('D_open', 'D_close', 'D_pre_close'))
    w, y = (row[k] for k in ('D_zge_white_line', 'D_zge_yellow_line'))
    d, lo = (row[k] for k in ('prior_active_anchor_date', 'prior_active_anchor_low'))
    old = close < lo if d is not None and d < row['trade_date'] and positive(lo) and positive(close) else None
    return dict(zip(HARD_NAMES, (
        op > prev and close < op if all(map(positive, (op, prev, close))) else None,
        tri_and(repair_proxy, old),
        tri_and(w <= y if positive(w) and positive(y) else None, old),
    )))


def history(root):
    reads = Reads()
    old = json.loads(reads.bytes(root / A41 / 'ACT041A_D_SIGNAL_SEAL.json'))
    v11 = json.loads(reads.bytes(root / A43 / 'ACT043A_RUN_RECEIPT.json'))
    require(old['phase'] == 'D_SIGNAL_SEALED' and old['outcomes_opened'] is False and
            v11['phase'] == 'D_ONLY_RUN_COMPLETE' and v11['panel_outcomes_opened'] == 0,
            'HISTORY_SOURCE_PHASE_DRIFT')
    old_paths = reads.info(root / A41, old['files'], 'ACT041A_D_SIGNALS_')
    new_paths = reads.info(root / A43, v11['overlay']['files'], 'ACT043A_V11_SIGNAL_PROJECTION_')
    b0, b1 = custodian(reads, root)
    exclude = {security_day(r) for r in b0 + b1}
    base_cols = (*KEYS, 'D_bar_state', 'D_high', 'D_low', 'ratio_formula_bars_in_segment',
                 *HARD_FEATURES, *(f'kb_{m:02}' for m in ORIG_BUY))
    new_cols = (*KEYS, *(f'v11_{m:02}' for m in L1))
    counters = Counter()
    keys_seen = set()
    stocks = defaultdict(set)
    n = Counter()
    unknown = Counter()
    for row, amended in zip_longest(parquet_rows(old_paths, base_cols), parquet_rows(new_paths, new_cols)):
        require(row is not None and amended is not None and security_day(row) == security_day(amended),
                'D_HISTORY_KEY_DRIFT')
        key = security_day(row)
        require(key not in keys_seen, 'D_HISTORY_DUPLICATE')
        keys_seen.add(key)
        old_hit = any(row[f'kb_{m:02}'] is True for m in ORIG_BUY)
        new_hit = any(amended[f'v11_{m:02}'] is True for m in L1)
        counters['old_buy'] += old_hit
        counters['v11_buy'] += new_hit
        if not (old_hit or new_hit):
            continue
        counters['union'] += 1
        if key in exclude:
            counters['excluded_in_union'] += 1
            continue
        counters['remaining'] += 1
        ready = (row['D_bar_state'] == 'VALID_TDX_DAILY' and
                 all(positive(row[name]) for name in ('D_open', 'D_high', 'D_low', 'D_close')) and
                 row['D_high'] > row['D_low'] and (row['ratio_formula_bars_in_segment'] or 0) >= 114)
        counters['ready'] += ready
        if ready:
            stocks['POOL'].add(key[0])
        states = {f'{m:02}': amended[f'v11_{m:02}'] for m in L1}
        states.update(hard_negatives(row, amended['v11_25']))
        for label, state in states.items():
            if state is True:
                n[label, 'raw'] += 1
                if ready:
                    n[label, 'ready'] += 1
                    stocks[label].add(key[0])
            elif state is None and ready:
                unknown[label] += 1
    require(len(keys_seen) == 162897 and counters['old_buy'] == 21448 and exclude <= keys_seen,
            'HISTORICAL_SCOPE_NOT_RECONCILED')
    counters.update(total_keys=len(keys_seen), batch0=len(b0), batch1=len(b1),
                    excluded_distinct=len(exclude), ready_stocks=len(stocks['POOL']))
    return dict(**FLAGS, history=dict(counters), methods=[
        dict(bucket=label, raw_keys=n[label, 'raw'], ready_keys=n[label, 'ready'],
             ready_stocks=len(stocks[label]), unknown_ready=unknown[label])
        for label in [*(f'{m:02}' for m in L1), *HARD_NAMES]
    ], source_refs=reads.refs, table_b_opened=0)


def restore_closeout(native, skeleton):
    published = read_csv(native)
    reference = index(read_csv(skeleton), lambda r: r['anon_id'])
    immutable = tuple(list(next(iter(reference.values())))[:171])
    require(len(published) == len(reference) == 181 and len(published[0]) == 177 and
            tuple(list(published[0])[:171]) == immutable, 'NATIVE_CLOSEOUT_SCHEMA_DRIFT')
    for row in published:
        frozen = reference[row['anon_id']]
        require(row['record_index'] == frozen['record_index'], 'NATIVE_CLOSEOUT_ORDER_DRIFT')
        require(row['training_gold_approved'].upper() == 'FALSE', 'NATIVE_GOLD_APPROVAL_DRIFT')
        for k in immutable:
            if k != 'master_verdict':
                row[k] = frozen[k]
    restored = csv_bytes(published)
    require(sha256(restored).hexdigest() == CLOSEOUT_SHA, 'SIGNED_CLOSEOUT_SHA_MISMATCH')
    return published


def flag(value):
    value = str(value).upper()
    return value if value in ('TRUE', 'FALSE') else 'UNKNOWN'


def cohort(row):
    return {'2': 'OVERLAP', '1': 'SINGLE'}[row['reviewer_count']]


def m23_candidate_note(row):
    tokens = row['master_partial_or_candidate_notes'].split('|')
    return any(t.startswith(('M23_L1_PARTIAL_', 'R4_23_PARTIAL_')) for t in tokens)


def labels(row):
    primary = int(row['master_primary_L1'])
    secondary = json.loads(row['master_secondary_L1'])
    require(isinstance(secondary, list) and set(secondary) <= set(METHODS)
            and primary in (0, *METHODS), 'SIGNED_METHOD_DOMAIN_DRIFT')
    return primary, secondary


def coverage(joined):
    result = {}
    for scope in COHORTS:
        selected = [r for r in joined if scope == 'ALL' or cohort(r) == scope]
        gold = [r for r in selected if r['master_verdict'] == GOLD]
        assign = [(r, *labels(r)) for r in gold]
        frequencies = {f'{method:02}': {
            'primary': sum(p == method for _, p, _ in assign),
            'secondary': sum(method in s for _, _, s in assign),
            'either': sum(method == p or method in s for _, p, s in assign),
        } for method in METHODS}
        branches = []
        for name, method, col, kind in SIGNALS:
            groups = {label: Counter(flag(r.get(col)) for r in selected if r['master_verdict'] == label)
                      for label in LABELS}
            reference = Counter(flag(r.get(col)) for r, p, s in assign if method == p or method in s)
            branches.append(dict(name=name, method=method, column=col, kind=kind,
                hits={label: groups[label]['TRUE'] for label in LABELS},
                unknown={label: groups[label]['UNKNOWN'] for label in LABELS},
                gold_ref=dict((state, reference[state]) for state in ('TRUE', 'FALSE', 'UNKNOWN'))))
        any_v11 = {label: sum(any(flag(r[f'v11_candidate_{m:02}']) == 'TRUE' for m in L1)
                              for r in selected if r['master_verdict'] == label) for label in LABELS}
        result[scope] = dict(frequencies=frequencies, branches=branches, any_v11=any_v11)
    return result


def quadrant(rows, field, horizon=None):
    counts = {label: dict(up=0, down=0, flat=0, missing=0, rally=0) for label in LABELS}
    representatives = defaultdict(list)
    for row in rows:
        label = row['master_verdict']
        value = row.get(field)
        if value is None:
            counts[label]['missing'] += 1
            continue
        require(math.isfinite(value), 'NONFINITE_OUTCOME')
        counts[label]['up' if value > 0 else 'down' if value < 0 else 'flat'] += 1
        counts[label]['rally'] += value >= .10
        if (label == GOLD and value < 0) or (label == REJECT and value >= .10):
            representatives[label].append(dict(record_index=int(row['record_index']),
                                                value=value, anon_id=row['anon_id'], horizon=horizon))
    examples = {label: sorted(v, key=lambda r: (r['value'] if label == GOLD else -r['value'],
                                                r['record_index']))[:2] for label, v in representatives.items()}
    return dict(counts=counts, examples=examples)


def diagnose(root, native):
    reads = Reads()
    skeleton = reads.bytes(root / A46 / 'ACT046A_BATCH1_181_EVENT_SKELETON_20261125.csv', SKELETON_SHA)
    chosen = restore_closeout(reads.bytes(native, NATIVE_EXPORT_SHA), skeleton)
    b1 = read_csv(reads.bytes(root / A44 / 'lateMap.csv', LATE_MAP_SHA))
    with ZipFile(io.BytesIO(reads.bytes(root / A44 / 'ACT043A_BATCH1_LATE_BLIND.zip', BLIND_SHA))) as archive:
        roster = read_csv(archive.read('records.csv'))
    b1map = index(b1, lambda r: r['anon_id'])
    observed = index(read_csv(skeleton), lambda r: r['anon_id'])
    ids = [r['anon_id'] for r in chosen]
    require(len(ids) == len(set(ids)) == 181 and set(ids) == set(b1map) == set(observed) and
            ids == [r['anon_id'] for r in roster] and len(index(b1, security_day)) == 181 and
            all(r['training_gold_approved'].upper() == 'FALSE' and r['input_blind_sha256'] == BLIND_SHA and
                int(r['record_index']) == i for i, r in enumerate(chosen, 1)), 'BATCH1_ROSTER_DRIFT')
    for scope, expected in EXPECTED.items():
        c = Counter(r['master_verdict'] for r in chosen if scope == 'ALL' or cohort(r) == scope)
        require(tuple(c[k] for k in LABELS) == expected, f'LABEL_COUNT_DRIFT:{scope}')

    manifest = json.loads(reads.bytes(root / A41 / 'CODEX_MAC_ACT-041A_MANIFEST_20261125.json'))
    paths = reads.info(root / A41, manifest['files_excluding_self'], 'ACT041A_OUTCOMES_')
    kept_keys = {security_day(r) for r in b1}
    import pyarrow.dataset as ds

    where = (ds.field('ts_code').isin(sorted({k[0] for k in kept_keys})) &
             ds.field('trade_date').isin(sorted({k[1] for k in kept_keys})))
    outcomes = index([r for r in parquet_rows(paths, (*KEYS, *OUTCOMES), where)
                      if security_day(r) in kept_keys], security_day)
    joined = []
    detail = []
    for r in chosen:
        oid = r['anon_id']
        outcome = outcomes.get(security_day(b1map[oid]), {})
        require(not outcome or all((outcome[f'T{h}_status'] == 'D_CLOSE_MARK_KNOWN') ==
                    (outcome[f'T{h}_return_from_D_close'] is not None) for h in HORIZONS),
                'OUTCOME_ENDPOINT_STATUS_MISMATCH')
        rule_values = {col: observed[oid][col] for _, _, col, _ in SIGNALS
                       if col and col != 'm23_candidate_note_present'}
        rule_values['m23_candidate_note_present'] = str(m23_candidate_note(r)).upper()
        entry = (outcome['D1_fillability_proxy'] if outcome else None)
        require(entry is True or all(outcome.get(f'T{h}_net_from_D1_open_fill_proxy') is None
                                     for h in HORIZONS), 'NONFILLABLE_WITH_EXECUTABLE_RETURN')
        vals = {k: outcome.get(k) for k in OUTCOMES}
        combined = {**r, **rule_values, **vals}
        joined.append(combined)
        detail.append({**{k: r[k] for k in ('record_index', 'anon_id', 'reviewer_count', 'master_verdict',
                                             'master_primary_L1', 'master_secondary_L1', 'training_gold_approved')},
                       'review_cohort': cohort(r), 'table_b_key_joined': bool(outcome), **vals,
                       **rule_values,
                       'm25_clock_reason': observed[oid]['act046a_m25_repair_clock_reason'],
                       'm05_main_advance_source': observed[oid]['act046a_m05_main_advance']})
    quads = {}
    for scope in COHORTS:
        rows = [r for r in joined if scope == 'ALL' or cohort(r) == scope]
        quads[scope] = dict(n=len(rows), entry_status=Counter(r['D1_entry_status'] or 'UNJOINED' for r in rows),
            by_horizon={f'T{h}': {
                'status': Counter(r[f'T{h}_status'] or 'UNJOINED' for r in rows),
                'gross': quadrant(rows, f'T{h}_return_from_D_close', h),
                'fillable_net': quadrant(rows, f'T{h}_net_from_D1_open_fill_proxy', h),
            } for h in HORIZONS})
    return detail, dict(**FLAGS, joined_keys=len(outcomes), expected_keys=181,
                        closeout_sha256=CLOSEOUT_SHA, coverage=coverage(joined),
                        quadrants=quads, source_refs=reads.refs)


def write_once(path, data):
    with path.open('xb') as stream:
        stream.write(data)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('history', 'diagnose'))
    p.add_argument('--artifacts', type=Path, required=True)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--native-closeout', type=Path)
    p.add_argument('--detail', type=Path)
    args = p.parse_args()
    start = perf_counter()
    if args.phase == 'history':
        require(args.native_closeout is None and args.detail is None, 'HISTORY_INPUT_SEPARATION')
        receipt = history(args.artifacts.resolve())
    else:
        require(args.native_closeout and args.detail, 'DIAGNOSE_ARGUMENTS_MISSING')
        require(not args.detail.exists(), 'DETAIL_ALREADY_EXISTS')
        rows, receipt = diagnose(args.artifacts.resolve(), args.native_closeout)
        payload = csv_bytes(rows)
        require(len(rows) == 181 and len(payload) <= 8_500_000, 'DETAIL_SIZE_OR_COUNT')
        write_once(args.detail, payload)
        receipt['detail'] = dict(bytes=len(payload), sha256=sha256(payload).hexdigest(), fields=len(rows[0]))
    receipt['wall_process_seconds'] = perf_counter() - start
    receipt['verified_input_bytes'] = sum(x['bytes'] for x in receipt['source_refs'].values())
    write_once(args.receipt, (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode())


if __name__ == '__main__':
    main()
