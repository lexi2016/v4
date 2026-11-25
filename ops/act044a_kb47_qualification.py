"""Bounded, D-only ACT044A method qualification and early/late V1.1 reconciliation."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
from math import isfinite
from pathlib import Path
import re
from time import perf_counter
from types import ModuleType
import zipfile

import pyarrow as pa
import pyarrow.dataset as ds

ARTIFACTS = Path('/Users/lexi/Desktop/学习/v4_app/artifacts')
A41 = 'pft_act041a_kb47_full_history_20261125'
A43 = 'pft_act043a_kb47_v11_batch1_20261125'
A44 = 'tactic_act044a_20261125'
CANON = 'pft_act040a_panel_kb_audit_20261125/source_inputs/PFT_V4_CANONICAL_20261122_V1.json'
AUTHORITY = (
    Path.home() / '.codex/worktrees/pft-act039a-top200-20261125/upstreams'
    / 'v3_shared_data/shared_data/a_formula_authority.py'
)
METHODS = (5, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 19, 20, 21, 22,
           24, 25, 26, 28, 29, 30, 31, 32)
SCOPE = (5, 17, 21, 22, 25)
REPLAY = (5, 16, 17, 21, 22, 25)
MASTER = 'TACTIC_ACT044_MASTER_WORKING_181_20261125.csv'
BLIND = 'ACT043A_BATCH1_LATE_BLIND.zip'
OUTPUTS = (
    'ACT044A_BATCH1_181_BEFORE_AFTER_20261125.csv',
    'ACT044A_BATCH0_TARGETED_REGRESSION_20261125.csv',
    'ACT044A_RUN_RECEIPT_20261125.json',
)
HASHES = {
    MASTER: '8740a6f6da09889cd146cf7a64a6e70518f8e9ee7d263393064c0f5fd0fd4e09',
    BLIND: '3e449a51d85703747fa576681dad5d2857a94ab6b567792d9aff8e68b5de31d1',
    'lateMap.csv': '5833cc99fe3215c88979bb5f6a3002066c6f433f0dd3d22bf2a3613c4a71ec10',
    'lateCtx.csv': '3a6fb9ce7e40c1686e98dca978326b85ec601add9e174fdd59c57271360f5e63',
    'lateB0.csv': 'a76b4e317850c090e699da4bed202b772ab3d4f177b45feb7701f00327cbb566',
    'lateMetrics.csv': '4d27c80a15da2a0d3e62f4192bcfd4adac55244799a8f651bf70adc8cae4f4a0',
    'lateSeal.json': '8bd195db9fbd9817a4017e8b0ff0dc30363f52ec35c06fc8079c308ae30d0e63',
    'lateAudit.json': '13c4897bfd8dc1f32a1943f487dd5598dd364d0ae87f31d7c9942139bc38d540',
    'formula.txt': '924ab78f0adb0ee0705e41d7824282f40ec275a97da532ffee5b61e29d2925e6',
    'ACT041A_D_SIGNAL_SEAL.json': 'e9adeb6db7582f2612a1c229762e515775033fc34b64632c20183e7b76853765',
    'ACT043A_RUN_RECEIPT.json': '870a1be75558dadc94e08a54a116df7842edae94f2820b208da7be4bbc125588',
    'ACT043A_V11_RULE_FREEZE.json': 'dd06f041676991d5b14a06dccc2aff9d4bd40e74350d296d243989113219214d',
    'act043_rules.py': '81d5870bccf2b4dba541e31082d766325704938f027b8266f2e62c1a399c937d',
    CANON: '5e301260209565d65a37188f6b1fbdedf2c197e83ac47b3b8292e43477bead23',
    'a_formula_authority.py': 'da7458ab3bebf72275254478eed909c99c5f1fcd69fa31b9f739e61b570ef4d8',
}
ADJUSTMENT_SHA = '0252b68d13667ca49b7b1b6c06d3cc575cae3fda6bb26df232aac37ed492223a'
KEYS = ('ts_code', 'trade_date')
D_COLUMNS = (*KEYS, *(f'kb_{method:02}' for method in METHODS),
    'D_bar_state', 'D_ratio_hfq_segment', 'ratio_formula_bars_in_segment', 'factor_known',
    'D_open', 'D_high', 'D_low', 'D_close', 'D_pre_close', 'D_return',
    'D_zge_white_line', 'D_zge_yellow_line', 'D_macd_dif', 'D_macd_dea', 'D_macd_hist',
    'D_raw_volume', 'atr14', 'signed_body_over_atr14', 'upper_wick_fraction',
    'close_position_fraction', 'vdu20_volume_ratio', 'user_v1_B1', 'user_v1_B2', 'user_v1_B3',
    'user_v1_breakout', 'user_v1_single_needle_under20',
    'prior_active_anchor_low', 'prior_active_anchor_date', 'prior_active_anchor_age_sessions',
    'prior_active_anchor_close_broken', 'repair_anchor_date', 'repair_anchor_low',
)
BASIS_FIELDS = (*KEYS, 'D_bar_state', 'D_ratio_hfq_segment', 'factor_known',
                'D_close', 'D_high', 'D_low', 'D_pre_close')
STATUS_VALUES = {'TRUE': True, 'FALSE': False, 'UNKNOWN': None}
ARROW_THREADS = 4
MAX_BYTES = 9_500_000


def require(test, detail):
    if not test:
        raise ValueError(detail)


def tri(value):
    return 'TRUE' if value is True else 'FALSE' if value is False else 'UNKNOWN'


def tri_and(*values):
    if any(value is False for value in values):
        return False
    return None if any(value is None for value in values) else True


def tri_or(*values):
    if any(value is True for value in values):
        return True
    return None if any(value is None for value in values) else False


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0


def row_key(row):
    return row['ts_code'], int(str(row['trade_date']).replace('-', ''))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def bound_bytes(path, expected):
    data = path.read_bytes()
    require(digest(data) == expected, f'SOURCE_SHA_DRIFT {path}')
    return data


def bound_csv(path):
    reader = csv.DictReader(io.StringIO(bound_bytes(path, HASHES[path.name]).decode('utf-8-sig'), newline=''))
    require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), f'CSV_HEADER {path.name}')
    rows = list(reader)
    require(all(None not in row and None not in row.values() for row in rows), f'CSV_SHAPE {path.name}')
    return rows


def index(rows, key):
    result = {key(row): row for row in rows}
    require(len(result) == len(rows), 'DUPLICATE_INPUT_KEY')
    return result


def bound_parquet_refs(refs, parent, early=False):
    prefix = 'ACT043A_V11_SIGNAL_PROJECTION_' if early else 'ACT041A_D_SIGNALS_'
    files = []
    for ref in refs:
        path = Path(ref['path'])
        require(path.parent.resolve() == parent.resolve() and path.name.startswith(prefix)
                and path.suffix == '.parquet', 'UNAPPROVED_PARQUET_SOURCE')
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        require(actual == ref['sha256'] and path.stat().st_size == ref['bytes'],
                f'PARQUET_IDENTITY_DRIFT {path.name}')
        files.append(path)
    require(len(set(files)) == (5 if early else 9), 'PARQUET_COUNT_DRIFT')
    return ds.dataset(files, format='parquet')


def exact_filter(day_keys):
    return ds.field('trade_date').isin(day_keys)


def code_windows(dataset, projection, target_days):
    """Read only requested D keys and selected preceding 20 chronological stock rows.

    First discover calendar keys with no feature columns. Feature scans then use
    explicit same-stock key sets so suspension rows keep the unchanged early clock.
    """
    by_key = {}
    windows = {}
    formula_windows = {}
    total_rows = 0
    extra_formula_rows = 0
    for code, targets in sorted(target_days.items()):
        code_filter = ds.field('ts_code') == code
        intervals = []
        for day in sorted(targets):
            first = datetime.strptime(str(day), '%Y%m%d') - timedelta(days=90)
            lower = int(first.strftime('%Y%m%d'))
            if intervals and lower <= intervals[-1][1]:
                intervals[-1] = intervals[-1][0], day
            else:
                intervals.append((lower, day))
        date_filter = None
        for first, last in intervals:
            interval = (ds.field('trade_date') >= first) & (ds.field('trade_date') <= last)
            date_filter = interval if date_filter is None else date_filter | interval
        key_rows = dataset.to_table(
            columns=['trade_date', 'D_bar_state', 'D_ratio_hfq_segment'], filter=code_filter & date_filter
        ).to_pylist()
        calendar = index(key_rows, lambda row: row['trade_date'])
        days = sorted(calendar)
        positions = {day: i for i, day in enumerate(days)}
        require(len(positions) == len(days), 'D_AUTHORITY_DUPLICATE')
        day_windows = {
            day: sorted(d for d in days[max(0, positions[day] - 20):positions[day] + 1]
                        if (datetime.strptime(str(day), '%Y%m%d') - datetime.strptime(str(d), '%Y%m%d')).days <= 90)
            for day in sorted(targets) if day in positions
        }
        fetch_days = sorted({d for window in day_windows.values() for d in window})
        require(not (set(targets) - set(day_windows)), 'SEALED_D_TARGET_KEY_MISSING')
        source_rows = dataset.to_table(columns=list(D_COLUMNS), filter=code_filter & exact_filter(fetch_days)).to_pylist()
        total_rows += len(source_rows)
        by_day = index(source_rows, lambda row: row['trade_date'])
        require(set(by_day) == set(fetch_days), 'D_FEATURE_KEY_DRIFT')
        formula_days = {}
        for day in day_windows:
            segment = by_day[day]['D_ratio_hfq_segment']
            if segment is None or calendar[day]['D_bar_state'] != 'VALID_TDX_DAILY':
                formula_days[day] = []
                continue
            cutoff = int((datetime.strptime(str(day), '%Y%m%d') - timedelta(days=90)).strftime('%Y%m%d'))
            formula_days[day] = [
                prior for prior in days[:positions[day] + 1]
                if prior >= cutoff and calendar[prior]['D_ratio_hfq_segment'] == segment
                and calendar[prior]['D_bar_state'] == 'VALID_TDX_DAILY'
            ][-21:]
        extra_days = sorted({d for window in formula_days.values() for d in window} - set(by_day))
        formula_by_day = by_day.copy()
        if extra_days:
            extra = dataset.to_table(
                columns=list(BASIS_FIELDS), filter=code_filter & exact_filter(extra_days)
            ).to_pylist()
            extra_formula_rows += len(extra)
            require(len(extra) == len(extra_days), 'D_FORMULA_FEATURE_KEY_DRIFT')
            formula_by_day.update(index(extra, lambda row: row['trade_date']))
        projected = projection.to_table(
            columns=[*KEYS, *(f'{prefix}_{m:02}' for m in METHODS for prefix in ('kb', 'v11')),
                     'v11_16_evidence', 'v11_21_evidence'],
            filter=code_filter & exact_filter(sorted(targets)),
        ).to_pylist()
        for row in projected:
            key = row_key(row)
            by_key[key] = row
            windows[key] = [by_day[d] for d in day_windows[key[1]]]
            formula_windows[key] = [formula_by_day[d] for d in formula_days[key[1]]]
    require(len(windows) == sum(map(len, target_days.values())), 'EARLY_PROJECTION_TARGET_KEY_DRIFT')
    return windows, formula_windows, by_key, total_rows, extra_formula_rows


def local_basis(window, snapshot):
    """Map 21 sequential positive bars of one sealed formula segment into the D basis."""
    if len(window) != 21 or not snapshot or snapshot.get('event_coverage_complete') is not True:
        return None, 'SAME_SEGMENT_21_BAR_WINDOW_UNAVAILABLE'
    segment = window[-1]['D_ratio_hfq_segment']
    if segment is None or any(row['D_bar_state'] != 'VALID_TDX_DAILY'
                              or row['D_ratio_hfq_segment'] != segment or row['factor_known'] is not True
                              for row in window):
        return None, 'SAME_SEGMENT_21_BAR_WINDOW_UNAVAILABLE'
    if int(snapshot['history_start_date']) > window[0]['trade_date']:
        return None, 'ACTION_WINDOW_START_UNBOUND'
    eligible_events = sorted(
        (event for event in snapshot['events'] if window[0]['trade_date'] < int(event['ex_date']) <= window[-1]['trade_date']),
        key=lambda event: int(event['ex_date']),
    )
    if any(not all(positive(row[key]) for key in ('D_close', 'D_high', 'D_low')) for row in window):
        return None, 'POSITIVE_PRICE_WINDOW_UNAVAILABLE'
    price_factors = [1.0] * len(window)
    for i in range(len(window) - 1, 0, -1):
        before, current = window[i - 1], window[i]
        expected = before['D_close']
        for event in eligible_events:
            if before['trade_date'] < int(event['ex_date']) <= current['trade_date']:
                expected = float(event['a']) * expected + float(event['b'])
        if (not positive(expected) or not positive(current['D_pre_close'])
                or abs(current['D_pre_close'] - expected) > .00500001):
            return None, 'EFFECTIVE_PRE_CLOSE_LINK_UNVERIFIED'
        price_factors[i-1] = price_factors[i] * expected / before['D_close']
    return [{key: row['D_' + key] * factor for key in ('high', 'low', 'close')}
            for row, factor in zip(window, price_factors)], 'ACT041A_EX_ACTION_D_BASIS_VERIFIED'


def f08_atom(bars):
    """F08 L39--41 uses highest CLOSE, two nonzero denominators and inclusive gates."""
    if bars is None or len(bars) != 21:
        return None, None, None
    def oscillator(window):
        if not all(positive(bar.get('close')) and positive(bar.get('low')) for bar in window):
            return None
        floor = min(bar['low'] for bar in window)
        denominator = max(bar['close'] for bar in window) - floor
        return 100 * (window[-1]['close'] - floor) / denominator if denominator > 0 else None

    long21, short3 = oscillator(bars), oscillator(bars[-3:])
    decision = None if long21 is None or short3 is None else long21 >= 75 and short3 <= 25
    return decision, long21, short3


def qualify_b3(raw_f04, course_b3, bull_regime):
    """Both canonical branches must obey known common R3. Restarts remain observations."""
    return tri_and(tri_or(raw_f04, course_b3), bull_regime)


def qualify_changan(prior_b1_geometry, canonical_sequence, bull_regime):
    """A geometry proxy never substitutes for a canonical Chang'an sequence."""
    decision = tri_and(canonical_sequence, bull_regime)
    return decision, 'CANDIDATE_ONLY' if prior_b1_geometry is True and decision is not True else 'NO_PROXY_PROMOTION'


def happened_in_order(dated_events, same_identity, final_d):
    """Check a supplied drop/break/confirm clock. Missing source fields stay unknown."""
    if dated_events is None or same_identity is None:
        return None
    drop, break_day, confirm = dated_events
    if any(day is None for day in dated_events):
        return None
    return same_identity and drop < break_day < confirm <= final_d


def state_record(decision, source, reasons, branch='NONE', **facts):
    return {'eligible_state': tri(decision), 'source_status': source, 'reason_codes': reasons,
            'fired_branch': branch, **facts}


def qualify_case(row, history, basis, basis_status, restart):
    w, y = row['D_zge_white_line'], row['D_zge_yellow_line']
    r3 = w > y if positive(w) and positive(y) else None
    f08, long21, short3 = f08_atom(basis)
    full_f08 = tri_and(f08, r3, None)  # Main-advance background lacks a bound D-only definition.
    raw_f04 = row['user_v1_B3']
    exact_f05 = row['user_v1_breakout']
    qualified_b3 = qualify_b3(raw_f04, None, r3)
    prior_b1 = [i - len(history) for i, bar in enumerate(history[-10:], start=max(0, len(history) - 10))
                if bar['user_v1_B1'] is True]
    changan, role = qualify_changan(row['kb_22'], None, r3)
    repair_clock = happened_in_order(None, None, row['trade_date'])
    past_macd = [bar['D_macd_hist'] for bar in history[-2:]]
    return {
        5: state_record(full_f08, 'F08_SOURCE_BOUND_MAIN_ADVANCE_SOURCE_PENDING',
            'MAIN_ADVANCE_CONTEXT_UNBOUND|R3_STRICT_W_GT_Y|F08_21_3_INCLUSIVE',
            'F08_RAW' if f08 is True else 'NONE', raw_f08=tri(f08),
            long21=long21, short3=short3, r3=tri(r3), main_advance='UNKNOWN', formula_basis=basis_status),
        17: state_record(tri_and(exact_f05, None), 'F05_PRICE_SOURCE_BOUND_MACD_TURN_SOURCE_PENDING',
            'F05_20_HIGH_8_COUNT|MACD_TURN_ATOM_UNBOUND',
            'F05_PRICE_BREAKOUT' if exact_f05 is True else 'NONE',
            raw_f05=tri(exact_f05), prior20_pivot=max(bar['high'] for bar in basis[:-1]) if basis else None,
            price_pivot_basis=basis_status, macd_turn='UNKNOWN', macd_slope_breakout_proxy=tri(row['kb_17']),
            macd_hist_D=row['D_macd_hist'], macd_hist_D_minus_1=past_macd[-1] if past_macd else None,
            macd_hist_D_minus_2=past_macd[-2] if len(past_macd) == 2 else None),
        21: state_record(qualified_b3, 'F04_RAW_BOUND_COURSE_B3_SOURCE_PENDING',
            'F04_HAS_NO_B2_DEPENDENCY|COURSE_SAME_WAVE_CLOCK_UNBOUND|RESTART_OBSERVATION_ONLY|R3_STRICT_W_GT_Y',
            'F04_RAW' if qualified_b3 is True else 'NONE',
            raw_f04=tri(raw_f04), course_b3='UNKNOWN', restart_variant=tri(restart), r3=tri(r3)),
        22: state_record(changan, 'CHANGAN_CANONICAL_SEQUENCE_SOURCE_PENDING',
            'PRIOR_B1_AND_D_B2_OR_B3_PROXY|SAME_WAVE_METHOD_SEQUENCE_UNBOUND|AUTO_L1_DISABLED',
            'NONE', candidate_role=role, raw_changan_proxy=tri(row['kb_22']), canonical_sequence='UNKNOWN',
            observed_prior_b1_offsets='|'.join(map(str, prior_b1)), D_B2=tri(row['user_v1_B2']),
            D_F04_B3=tri(raw_f04), r3=tri(r3)),
        25: state_record(repair_clock, 'SAME_ID_REPAIR_CLOCK_SOURCE_PENDING',
            'D_REPAIR_ANCHOR_PROXY|ORDERED_DROP_BREAK_CONFIRM_AND_SAME_REPAIR_ID_UNBOUND',
            'NONE', repair_on_D_proxy=tri(row['kb_25']),
            anchor_recorded_on_D=tri(row['repair_anchor_date'] == row['trade_date']
                                     if row['repair_anchor_date'] is not None else None),
            repair_clock='UNKNOWN', verified_repair_id='UNKNOWN'),
    }


def read_bound_inputs(artifacts):
    target = artifacts / A44
    batch1, mapping, context, batch0, later_metrics = (
        bound_csv(target / name) for name in (MASTER, 'lateMap.csv', 'lateCtx.csv', 'lateB0.csv', 'lateMetrics.csv')
    )
    blind = bound_bytes(target / BLIND, HASHES[BLIND])
    seal = json.loads(bound_bytes(target / 'lateSeal.json', HASHES['lateSeal.json']))
    bound_bytes(target / 'lateAudit.json', HASHES['lateAudit.json'])
    bound_bytes(target / 'formula.txt', HASHES['formula.txt'])
    bound_bytes(artifacts / CANON, HASHES[CANON])
    bound_bytes(AUTHORITY, HASHES[AUTHORITY.name])
    blind_ref = next(ref for ref in seal['files'] if ref['filename'] == 'ACT043A_BATCH1_BLIND.zip')
    context_ref = next(ref for ref in seal['files'] if ref['filename'] == 'candidate_context.csv')
    require(blind_ref['sha256'] == HASHES[BLIND] and blind_ref['size_bytes'] == len(blind),
            'LATE_BLIND_SEAL_DRIFT')
    maps = index(mapping, lambda row: row['anon_id'])
    contexts = index(context, lambda row: row['anon_id'])
    masters = index(batch1, lambda row: row['anon_id'])
    index(mapping, row_key)
    index(batch0, row_key)
    index(batch0, lambda row: row['anon_id'])
    require(len(batch1) == 181 and set(masters) == set(maps) == set(contexts)
            and [int(row['record_index']) for row in batch1] == list(range(1, 182))
            and all(row['input_blind_sha256'] == HASHES[BLIND] for row in batch1), 'LATE_BLIND_KEY_CONTRACT')
    require(len(batch0) == 72 and Counter(row['gold_verdict'] for row in batch0) == {
        'GOLD_CONFIRMED': 26, 'REJECTED_FAKE': 24, 'BORDERLINE_WATCH': 21, 'DATA_UNAVAILABLE_ISOLATED': 1},
        'BATCH0_FROZEN_LABEL_COUNTS')
    require(list(context[0]) == ['anon_id'] + [
        f'{prefix}_candidate_{method:02}' for prefix in ('v10', 'v11') for method in METHODS
    ] and all(value in STATUS_VALUES for row in context for key, value in row.items() if key != 'anon_id'),
            'LATE_FROZEN_23_FLAG_SCHEMA_DRIFT')
    require(not set(batch1[0]).intersection(set(context[0]) - {'anon_id'}), 'BEFORE_AFTER_COLUMN_COLLISION')
    numeric = {}
    with zipfile.ZipFile(io.BytesIO(blind)) as archive:
        records = list(csv.DictReader(io.TextIOWrapper(archive.open('records.csv'), encoding='utf-8-sig')))
        require(len(records) == 181 and {row['anon_id'] for row in records} == set(masters), 'LATE_ZIP_ROSTER_DRIFT')
        bars = defaultdict(list)
        fields = {'low', 'high', 'close', 'white_line', 'yellow_line'}
        with io.TextIOWrapper(archive.open('trailing_bars.csv'), encoding='utf-8-sig') as stream:
            for row in csv.DictReader(stream):
                bars[row['anon_id']].append({
                    'session': int(row['relative_session']),
                    **{field: float(row[field]) if row[field] else None for field in fields},
                })
        require(set(bars) == set(masters), 'LATE_ZIP_BAR_ROSTER_DRIFT')
        for anon, window in bars.items():
            window.sort(key=lambda row: row['session'])
            require(len(window) == 60 and len({row['session'] for row in window}) == 60 and window[-1]['session'] == 0,
                    'LATE_ZIP_BAR_WINDOW_DRIFT')
            atom, long21, short3 = f08_atom(window[-21:])
            require(tri(atom) == contexts[anon]['v10_candidate_05'], 'LATE_ZIP_F08_FLAG_DRIFT')
            numeric[anon] = (atom, long21, short3, window[-1])
    return batch1, maps, contexts, batch0, later_metrics, numeric, context_ref


def history_sources(artifacts, target_days):
    source = artifacts / A41
    early = artifacts / A43
    d_seal = json.loads(bound_bytes(source / 'ACT041A_D_SIGNAL_SEAL.json', HASHES['ACT041A_D_SIGNAL_SEAL.json']))
    e_seal = json.loads(bound_bytes(early / 'ACT043A_RUN_RECEIPT.json', HASHES['ACT043A_RUN_RECEIPT.json']))
    require(d_seal['phase'] == 'D_SIGNAL_SEALED' and d_seal['outcomes_opened'] is False
            and e_seal['phase'] == 'D_ONLY_RUN_COMPLETE' and e_seal['panel_outcomes_opened'] == 0, 'D_SOURCE_PHASE_DRIFT')
    rules = json.loads(bound_bytes(early / 'ACT043A_V11_RULE_FREEZE.json', HASHES['ACT043A_V11_RULE_FREEZE.json']))
    rule_source = early / 'act043_rules.py'
    known_module = ModuleType('act043a_immutable_early_rules')
    exec(compile(bound_bytes(rule_source, HASHES[rule_source.name]), str(rule_source), 'exec'), known_module.__dict__)
    d_sources = [ref for ref in d_seal['files'] if ref['kind'] == 'D_SIGNALS']
    e_sources = e_seal['overlay']['files']
    d_dataset = bound_parquet_refs(d_sources, source)
    e_dataset = bound_parquet_refs(e_sources, early, early=True)
    windows, formula_windows, projections, fetched, extra_formula = code_windows(d_dataset, e_dataset, target_days)
    adjustment_ref = d_seal['sources']['adjustment']
    require(adjustment_ref['sha256'] == ADJUSTMENT_SHA, 'ACT041A_ADJUSTMENT_BINDING_DRIFT')
    symbols = json.loads(bound_bytes(Path(adjustment_ref['path']), ADJUSTMENT_SHA))['symbols']
    adjustment = {code: symbols.get(code) for code in target_days}
    identity = {'early_projection_refs': e_sources, 'D_signals_refs': d_sources,
                'ACT041A_adjustment_ref': adjustment_ref}
    return windows, formula_windows, projections, fetched, extra_formula, rules, known_module, adjustment, identity


def replay_prefixes(history, formula_history, projections, rules, early, snapshots):
    results = {}
    for key, window in history.items():
        target = window[-1]
        require(row_key(target) == key and all(row['trade_date'] < key[1] for row in window[:-1]),
                'D_PREFIX_INTEGRITY')
        updates, reasons = early.candidates(window, len(window) - 1, rules)
        projection = projections[key]
        for method in METHODS:
            old = target[f'kb_{method:02}']
            updated = updates.get(method, old)
            require(old is projection[f'kb_{method:02}'] and updated is projection[f'v11_{method:02}'],
                    f'EARLY_REPLAY_PROJECTION_DRIFT b{method:02}')
        for method in (16, 21):
            require(reasons[method] == projection[f'v11_{method:02}_evidence'], 'EARLY_BRANCH_REASON_DRIFT')
        restart = next((piece[-1] for piece in reasons[21].split('|') if piece.startswith('restart_')), 'U')
        restart = {'Y': True, 'N': False, 'U': None}[restart]
        basis, basis_status = local_basis(formula_history[key], snapshots[key[0]])
        qualifications = qualify_case(target, window[:-1], basis, basis_status, restart)
        f08_value = qualifications[5]['raw_f08']
        if f08_value != 'UNKNOWN':
            require(f08_value == tri(target['user_v1_single_needle_under20']) == tri(target['kb_05']),
                    'EARLY_F08_CALCULATION_DRIFT')
        results[key] = (target, projection, reasons, qualifications)
    return results


def batch1_rows(master, maps, contexts, numeric, replay, rules):
    rows = []
    for original in master:
        anon = original['anon_id']
        context = contexts[anon]
        row, early, reasons, qualifications = replay[row_key(maps[anon])]
        late_f08, late_long, late_short, late_D = numeric[anon]
        require(all(positive(late_D[field]) and positive(row[early_field])
                    and abs(late_D[field] - row[early_field]) <= .00500001
                    for field, early_field in (('close', 'D_close'), ('high', 'D_high'), ('low', 'D_low'))),
                'LATE_BLIND_TARGET_D_QUOTE_DRIFT')
        output = {**original, **context}
        for method in METHODS:
            output[f'early_raw_{method:02}'] = tri(early[f'kb_{method:02}'])
            output[f'early_before_{method:02}'] = tri(early[f'v11_{method:02}'])
        for method, decision in qualifications.items():
            output.update({f'm{method:02}_{key}': value for key, value in decision.items()})
        output.update(
            m05_late_raw_f08=tri(late_f08), m05_late_long21=late_long, m05_late_short3=late_short,
            m16_early_rule_evidence=reasons[16], m16_early_white_distance_cap_atr=rules['method_16']['D_above_white_atr_cap'],
            m16_late_white_distance_cap_atr_reported=3.5,
            m21_early_OR_evidence=reasons[21],
        )
        rows.append(output)
    return rows


def label_codes(row):
    text = '|'.join(row[key] for key in ('primary_L1_method', 'secondary_L1_methods'))
    return {int(value) for value in re.findall(r'\b\d{1,2}\b', text) if value != '0'}


def batch0_rows(batch0, replay, rules):
    rows = []
    for original in batch0:
        _, early, reasons, qualifications = replay[row_key(original)]
        for method in REPLAY:
            code = f'{method:02}'
            row = {
                'anon_id': original['anon_id'],
                'method_id': code,
                'gold_verdict': original['gold_verdict'],
                'primary_L1_method': original['primary_L1_method'],
                'secondary_L1_methods': original['secondary_L1_methods'],
                'reference_method_positive': tri(method in label_codes(original)
                    if original['gold_verdict'] == 'GOLD_CONFIRMED'
                    else False if original['gold_verdict'] == 'REJECTED_FAKE' else None),
                'early_raw': tri(early[f'kb_{code}']),
                'early_before': tri(early[f'v11_{code}']),
                'after_eligible_state': qualifications[method]['eligible_state'] if method in qualifications else '',
                'after_source_status': qualifications[method]['source_status'] if method in qualifications else 'VERSION_CHECK_ONLY',
                'after_reason_codes': qualifications[method]['reason_codes'] if method in qualifications else '',
                'early_rule_evidence': reasons.get(method, ''),
                'numeric_white_cap_early_atr_reported': rules['method_16']['D_above_white_atr_cap'] if method == 16 else None,
                'numeric_white_cap_late_atr_reported': 3.5 if method == 16 else None,
                'facts_json': json.dumps(qualifications[method], ensure_ascii=False, allow_nan=False, sort_keys=True)
                              if method in qualifications else '{}',
            }
            rows.append(row)
    return rows


def transitions(rows, before, after):
    return dict(sorted(Counter(f'{row[before]}->{row[after]}' for row in rows).items()))


def matrix(rows, key):
    counts = Counter()
    for row in rows:
        if row['gold_verdict'] not in {'GOLD_CONFIRMED', 'REJECTED_FAKE'}:
            counts['reference_excluded'] += 1
            continue
        positive_ref = row['reference_method_positive'] == 'TRUE'
        decision = row[key]
        if decision == 'UNKNOWN':
            status = 'positive_unknown' if positive_ref else 'negative_unknown'
        elif decision == 'TRUE':
            status = 'TP' if positive_ref else 'FP'
        else:
            status = 'FN' if positive_ref else 'TN'
        counts[status] += 1
        if decision == 'TRUE' and row['gold_verdict'] == 'REJECTED_FAKE':
            counts['FP_in_REJECTED'] += 1
    names = ('TP', 'FP', 'FN', 'TN', 'FP_in_REJECTED', 'positive_unknown', 'negative_unknown', 'reference_excluded')
    return {name: counts[name] for name in names}


def aggregate(output1, output0, later_metrics):
    scoped = {}
    for method in SCOPE:
        code = f'{method:02}'
        before, after = f'early_before_{code}', f'm{code}_eligible_state'
        scoped[code] = {
            'early_to_after': transitions(output1, before, after),
            'late_to_after': transitions(output1, f'v11_candidate_{code}', after),
            'substantive_changes': sum((row[before] == 'TRUE') != (row[after] == 'TRUE') for row in output1),
            'fired_branches': dict(Counter(row[f'm{code}_fired_branch'] for row in output1)),
        }
    def changed_cases(methods):
        return sum(any((row[f'early_before_{m:02}'] == 'TRUE') != (row[f'm{m:02}_eligible_state'] == 'TRUE')
                       for m in methods) for row in output1)
    restart_only = [row['anon_id'] for row in output1 if row['early_before_21'] == 'TRUE'
                    and row['m21_raw_f04'] != 'TRUE' and row['m21_restart_variant'] == 'TRUE']
    r3_bypass = [row['anon_id'] for row in output1 if row['early_before_21'] == 'TRUE' and row['m21_r3'] != 'TRUE']
    by_method0 = {}
    for method in REPLAY:
        code = f'{method:02}'
        subset = [row for row in output0 if row['method_id'] == code]
        by_method0[code] = {'early_before': matrix(subset, 'early_before')}
        if method in SCOPE:
            by_method0[code]['after_qualification'] = matrix(subset, 'after_eligible_state')
            by_method0[code]['early_to_after'] = transitions(subset, 'early_before', 'after_eligible_state')
    return {
        'Batch1': {
            'per_method': scoped,
            'unique_substantive_changes': changed_cases((5, 21, 22)),
            'unique_substantive_changes_method_scope': [5, 21, 22],
            'unique_substantive_changes_including_source_isolation': changed_cases(SCOPE),
            'unique_substantive_changes_including_source_isolation_scope': list(SCOPE),
            'm21_restart_only_witness_anon_ids': restart_only,
            'm21_observed_early_r3_bypass_anon_ids': r3_bypass,
            'm22_legacy_candidate_only': sum(row['m22_candidate_role'] == 'CANDIDATE_ONLY' for row in output1),
            'm16_early_to_late': transitions(output1, 'early_before_16', 'v11_candidate_16'),
            'm21_early_to_late': transitions(output1, 'early_before_21', 'v11_candidate_21'),
            'F08_D_replay_available': sum(row['m05_raw_f08'] != 'UNKNOWN' for row in output1),
            'F08_D_replay_late_agree': sum(row['m05_raw_f08'] != 'UNKNOWN'
                                        and row['m05_raw_f08'] == row['m05_late_raw_f08'] for row in output1),
            'F08_late_ZIP_readback': len(output1),
        },
        'Batch0': {
            'denominators': {'gold': 26, 'rejected': 24, 'watch': 21, 'isolated': 1},
            'per_method': by_method0,
            'late_reported_native_aggregate': {row['method_id']: row for row in later_metrics
                                               if row['method_id'] in {'#16', '#21'}},
            'later_casewise_rule_replay': 'CANNOT_CONFIRM_LATE_EXECUTABLE_AND_BATCH0_CASEWISE_FLAGS_UNAVAILABLE',
        },
    }


def csv_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def run(artifacts):
    pa.set_cpu_count(ARROW_THREADS)
    pa.set_io_thread_count(ARROW_THREADS)
    start = perf_counter()
    batch1, maps, contexts, batch0, later_metrics, numeric, ctx_ref = read_bound_inputs(artifacts)
    target_days = defaultdict(set)
    for row in [*maps.values(), *batch0]:
        code, when = row_key(row)
        target_days[code].add(when)
    windows, formula_windows, projections, fetched, extra_formula, rules, early, adjustment, identities = history_sources(artifacts, target_days)
    checked = replay_prefixes(windows, formula_windows, projections, rules, early, adjustment)
    output1 = batch1_rows(batch1, maps, contexts, numeric, checked, rules)
    output0 = batch0_rows(batch0, checked, rules)
    require(len(output1) == 181 and len(output0) == 72 * len(REPLAY)
            and all(all(out[key] == val for key, val in inp.items()) for out, inp in zip(output1, batch1))
            and all(all(out[key] == val for key, val in contexts[inp['anon_id']].items())
                    for out, inp in zip(output1, batch1)), 'FROZEN_SOURCE_STRING_READBACK')
    require(all({'ts_code', 'trade_date', 'name', 'source_rows'}.isdisjoint(row) for row in (*output1, *output0)),
            'PRIVATE_D_IDENTITY_COLUMN_FORBIDDEN')
    table_bytes = [csv_bytes(rows) for rows in (output1, output0)]
    for blob in table_bytes:
        require(not re.search(rb'(?<![0-9])[03689][0-9]{5}\.(?:SH|SZ|BJ)\b', blob),
                'PRIVATE_D_SECURITY_ID_LEAK')
        require(len(blob) <= MAX_BYTES, 'OUTPUT_SIZE_CAP')
    for provided, rows in zip(table_bytes, (output1, output0)):
        reread = list(csv.DictReader(io.StringIO(provided.decode('utf-8'), newline='')))
        require(len(reread) == len(rows) and all(
            val == (str(rows[i][key]) if rows[i][key] is not None else '')
            for i, row in enumerate(reread) for key, val in row.items()), 'OUTPUT_CSV_READBACK')
    receipt = aggregate(output1, output0, later_metrics)
    receipt.update({
        'phase': 'ACT044A_BOUNDED_D_ONLY_METHOD_QUALIFICATION_COMPLETE',
        'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False,
        'orders_sent': False, 'S_FIT': 0, 'B_FIT': 0, 'model_load_count': 0, 'predict_count': 0,
        'tuning_count': 0, 'outcomes_opened': False, 'full_history_recompute': False,
        'source_hashes': HASHES, 'source_identity': identities,
        'later_context_identity': {
            'native_export_sha256': HASHES['lateCtx.csv'],
            'sealed_original_bytes_sha256': ctx_ref['sha256'],
            'checks': '181 exact anon keys|23 x 2 typed flags|independent historical bytes unavailable',
        },
        'd_replay': {
            'unique_case_keys': len(checked), 'max_previous_same_stock_rows_per_D': 20,
            'targeted_D_rows_fetched_including_overlap': fetched, 'supplemental_positive_formula_rows_fetched': extra_formula,
            'sealed_projection_case_parity': len(checked),
            'sealed_projection_method_flag_pairs_per_case': 23,
            'sealed_early_reason_parity_methods': [16, 21],
        },
        'source_notes': {
            'MACD_turn': 'Canonical F05 binds the price leg alone. ACT041A MACD slope is a diagnostic proxy.',
            'm16': 'Early source and cap exact from frozen executable; late 3.5 ATR from report only.',
            'm21': 'Legacy original-or-restart evidence is compared with canonical F04/course OR gated by R3.',
            'm22': 'Earlier B1 and current B2/B3 retained as candidate-only geometry.',
            'm25': 'No ordered drop/break/confirm and same-repair identity source.',
            'F08': 'ACT041A 21 local positive ratio-HFQ bars, verified exact as-of corporate actions and previous close references.',
        },
        'outputs': [
            {'path': name, 'bytes': len(blob), 'sha256': digest(blob), 'rows': len(rows)}
            for name, blob, rows in zip(OUTPUTS, table_bytes, (output1, output0))
        ],
        'arrow_cpu_threads': ARROW_THREADS,
        'arrow_io_threads': ARROW_THREADS,
        'elapsed_seconds': perf_counter() - start,
    })
    return table_bytes, receipt


def write_outputs(directory, inputs, receipt):
    paths = [directory / name for name in OUTPUTS]
    pending = [path.with_suffix(path.suffix + '.pending') for path in paths]
    require(all(not path.exists() for path in (*paths, *pending)), 'OUTPUT_EXISTS')
    payloads = [*inputs, (json.dumps(receipt, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + '\n').encode()]
    written = []
    try:
        for path, content in zip(pending, payloads):
            require(len(content) <= MAX_BYTES, 'OUTPUT_SIZE_CAP')
            with path.open('xb') as stream:
                written.append(path)
                stream.write(content)
            require(digest(path.read_bytes()) == digest(content), 'POST_WRITE_READBACK_DRIFT')
        for tmp, target in zip(pending, paths):
            # Commit the receipt last so it witnesses both completed CSV files.
            tmp.rename(target)
    finally:
        for path in written:
            path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, default=ARTIFACTS, help='Absolute V4 artifacts root')
    parser.add_argument('--output-dir', type=Path, help='Existing absolute directory for fresh output names')
    parser.add_argument('--check-only', action='store_true', help='Verify all source and output contracts in memory')
    args = parser.parse_args()
    destination = args.output_dir or args.artifacts / A44
    require(args.artifacts.is_absolute() and args.artifacts.is_dir(), 'ABSOLUTE_ARTIFACTS_ROOT_REQUIRED')
    if not args.check_only:
        require(destination.is_absolute() and destination.is_dir(), 'EXISTING_ABSOLUTE_OUTPUT_DIR_REQUIRED')
        require(all(not (destination / name).exists() for name in OUTPUTS), 'OUTPUT_EXISTS')
    output, receipt = run(args.artifacts)
    if not args.check_only:
        write_outputs(destination, output, receipt)
    print(json.dumps({
        'mode': 'CHECK_ONLY' if args.check_only else 'WRITE',
        'case_keys': receipt['d_replay']['unique_case_keys'],
        'outputs': receipt['outputs'],
        'substantive_changes': receipt['Batch1']['unique_substantive_changes'],
        'elapsed_seconds': receipt['elapsed_seconds'],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
