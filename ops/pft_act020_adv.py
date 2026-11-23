"""ACT020 bounded causal ADV20 projection through the bound canonical V4 reader.

Only sealed ACT018 hard-candidate code/D keys are written. Original amount rows
remain in memory; no panel, outcome, model or source data is written.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops import pft_act015_common as c
from ops.pft_act016_inputs import hard_mask

pd, np = c.pd, c.np
DEFAULT_AMOUNT_RECEIPT = Path('/Users/lexi/Desktop/学习/v4_app/artifacts/'
                              'pft_act016_exact_replay_20261123/amount_unit_receipt.json')
OUTPUT_COLUMNS = [*c.IDENTITY, 'adv20_cny', 'adv20_valid_count']


def key_sha256(keys):
    payload = keys[c.IDENTITY].sort_values(c.IDENTITY).to_csv(index=False).encode()
    return hashlib.sha256(payload).hexdigest()


def same_source(left, right):
    return (left['identity'] == right['identity'] and
            left['backtest']['panel_sha256'] == right['backtest']['panel_sha256'])


def validate_amount_receipt(path, source):
    """Reuse ACT016's raw-CNY attestation only for the identical V4 source."""
    m = c.old._read_json(path)
    if (m.get('status') != 'PASS' or m.get('amount_unit') != 'CNY_RAW' or
        m.get('factor') != 1 or m.get('producer_basis') != 'RAW_TURNOVER' or
        m.get('generation') != source['identity']['generation_id'] or
        m.get('backtest_panel_sha256') != source['backtest']['panel_sha256'] or
        source['identity']['a_market_basis'].get('amount_basis') != 'RAW_TURNOVER'):
        raise ValueError('RAW_CNY_RECEIPT_SOURCE_DRIFT')
    samples = m.get('samples', [])
    exchanges = {s.get('code', '').split('.')[-1] for s in samples}
    if len(samples) < 5 or not {'SH', 'SZ', 'BJ'} <= exchanges:
        raise ValueError('RAW_CNY_RECEIPT_SAMPLE_COVERAGE')
    errors = []
    for sample in samples:
        original, official = float(sample['v4_raw_amount']), float(sample['official_amount_cny'])
        if not np.isfinite([original, official]).all() or original < 0 or official <= 0:
            raise ValueError('RAW_CNY_RECEIPT_INVALID_SAMPLE')
        errors.append(abs(original / official - 1))
    if max(errors) > 1e-6:
        raise ValueError('RAW_CNY_RECEIPT_VALUE_MISMATCH')
    return {'path': str(path), 'sha256': c.old._sha_file(path),
            'samples': len(samples), 'max_relative_error': max(errors), 'factor': 1}


def candidate_keys(fit_dir, act018_replay_dir, market_dir, canary_codes=None):
    """Verify only consumed seals/projections; never read execution outcomes."""
    fit = c.old._read_json(fit_dir / 'fit_manifest.json')
    replay = c.old._read_json(act018_replay_dir / 'replay_manifest.json')
    if (fit.get('batch') != 'ACT-015' or fit.get('schema') != 'ACT015_FIT_PREDICTION_V1' or
        fit.get('mode') != 'FULL' or fit.get('flags') != c.old.FLAGS or
        fit.get('actual_successful_fit_calls') != 80 or fit.get('prediction_outcomes_read') is not False):
        raise ValueError('ACT015_FIT_MANIFEST_DRIFT')
    fit_sha = c.old._sha_file(fit_dir / 'fit_manifest.json')
    c.verified_file(fit_dir / 'pre_replay_seal.json', fit['outputs_sha256']['pre_replay_seal.json'])
    fit_seal = c.old._read_json(fit_dir / 'pre_replay_seal.json')
    if (fit_seal.get('batch') != 'ACT-015' or fit_seal.get('fit_calls') != 80 or
        fit_seal.get('flags') != c.old.FLAGS or fit_seal.get('prediction_outcomes_read') is not False):
        raise ValueError('ACT015_PRE_REPLAY_SEAL_DRIFT')
    if (replay.get('batch') != 'ACT-018' or replay.get('mode') != 'FULL' or
        replay.get('flags') != c.old.FLAGS or replay.get('fits_this_stage') != 0 or
        replay.get('schema') != 'ACT018_940D_PRIOR_LANE_PERCENTILE_V1' or
        not same_source(replay['source'], fit['source'])):
        raise ValueError('ACT018_MANIFEST_DRIFT')
    c.verified_file(act018_replay_dir / 'pre_execution_seal.json',
                    replay['outputs_sha256']['pre_execution_seal.json'])
    seal = c.old._read_json(act018_replay_dir / 'pre_execution_seal.json')
    if (seal != replay['input_seals'] or seal.get('execution_ohlc_read') is not False or
        seal.get('fit_manifest_sha256') != fit_sha or
        seal.get('market_manifest_sha256') != c.old._sha_file(market_dir / 'market_manifest.json') or
        not same_source(seal['source'], fit['source'])):
        raise ValueError('ACT018_INPUT_SEAL_DRIFT')
    rel = 'candidate_score_audit.parquet'
    sha = replay['outputs_sha256'][rel]
    if seal['outputs_sha256'][rel] != sha:
        raise ValueError('CANDIDATE_PRE_EXECUTION_SHA_DRIFT')
    c.verified_file(act018_replay_dir / rel, sha)
    cols = [*c.IDENTITY, 'lane', 'hard_eligible', 'S_prob_gated', 'B_probability', 'rank_score']
    candidates = pd.read_parquet(act018_replay_dir / rel, columns=cols)
    if (candidates.empty or candidates.duplicated([*c.IDENTITY, 'lane']).any() or
        not candidates.lane.isin(c.LANES).all() or not hard_mask(candidates).all() or
        not candidates.D.str.fullmatch(r'\d{8}').all() or
        not candidates.D.between('20230101', c.ASOF).all()):
        raise ValueError('ACT018_HARD_CANDIDATE_KEY_DRIFT')
    keys = candidates[c.IDENTITY].drop_duplicates().sort_values(c.IDENTITY).reset_index(drop=True)
    full_keys = len(keys)
    if canary_codes:
        if not set(canary_codes) <= set(keys.canonical_security_id):
            raise ValueError('CANARY_WITHOUT_CANDIDATE_KEY')
        keys = keys[keys.canonical_security_id.isin(canary_codes)].reset_index(drop=True)
    _, sessions, market_manifest, calendar_info = c.calendar(market_dir, fit['source'])
    c.verified_file(c.old.CROSSWALK_FILE, market_manifest['crosswalk_sha256'])
    if sessions != fit['sessions'] or sessions != sorted(set(sessions)):
        raise ValueError('FIT_MARKET_CALENDAR_DRIFT')
    index = {day: i for i, day in enumerate(sessions)}
    if any(day not in index or index[day] < 19 for day in keys.D):
        raise ValueError('TWENTY_SESSION_LOOKBACK_UNAVAILABLE')
    return fit, keys, sessions, calendar_info, full_keys


def rollup_security(task):
    """20 exchange sessions ending at D, never 20 last observed stock rows."""
    code, history, days, sessions, crosswalk = task
    h = c.canonical_history(history, crosswalk)
    positions = {day: i for i, day in enumerate(sessions)}
    indexes = [positions[day] for day in days]
    first, last = max(0, min(indexes) - 19), max(indexes)
    calendar = sessions[first:last + 1]
    original = pd.to_numeric(h.set_index('trade_date').amount, errors='coerce')
    amounts = original.reindex(calendar).astype(float)
    valid = np.isfinite(amounts) & amounts.ge(0)
    counts = valid.astype('int16').rolling(20, min_periods=1).sum()
    # Nonnegative original values, including recorded zero; never fill a gap.
    average = amounts.where(valid).rolling(20, min_periods=20).sum() / 20.
    average = average.where(np.isfinite(average))
    out = pd.DataFrame({'canonical_security_id': code, 'D': days,
                        'adv20_cny': average.reindex(days).to_numpy(),
                        'adv20_valid_count': counts.reindex(days).to_numpy(dtype='int16')})
    return out[OUTPUT_COLUMNS]


def worker_init():
    from threadpoolctl import threadpool_limits
    threadpool_limits(1)


def derive(*, fit_dir, act018_replay_dir, market_dir, data_root, act005_root,
           output_dir, amount_receipt=DEFAULT_AMOUNT_RECEIPT, workers=16, canary_codes=None):
    from ops.pft_s_first_baseline import bind_current_panels
    from ops import research_panel_logical as reader
    if not 1 <= workers <= 18:
        raise ValueError('WORKERS_1_TO_18')
    fit, keys, sessions, calendar_info, full_keys = candidate_keys(
        fit_dir, act018_replay_dir, market_dir, canary_codes)
    amount_proof = validate_amount_receipt(amount_receipt, fit['source'])
    frozen = c.old._validate_inputs(act005_root)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output_dir.parent).free < 256 * 1024**2:
        raise ValueError('ADV_OUTPUT_SPACE_BUDGET_UNAVAILABLE')
    stage = c.new_stage(output_dir)
    started = time.monotonic()
    results, rows_read = [], 0
    dates = keys.groupby('canonical_security_id', sort=True).D.agg(list).to_dict()
    positions = {d: i for i, d in enumerate(sessions)}
    worker_init()
    with bind_current_panels(data_root) as (path, source, recheck):
        c.assert_source(source, frozen)
        if not same_source(source, fit['source']):
            raise ValueError('ADV_CURRENT_V4_SOURCE_DRIFT')
        validate_amount_receipt(amount_receipt, source)
        aliases, groups, crosswalk = c.observed_universe(path, reader)
        if not set(dates) <= set(groups):
            raise ValueError('ADV_CANONICAL_MISSING')
        groups = {code: groups[code] for code in dates}
        schema = reader.parquet.read_schema(path)
        names = c.old._schema_names(schema)
        mapping = {n: names[n] for n in ['ts_code', 'trade_date', 'amount', 'market_type', 'exchange']}
        executor = ProcessPoolExecutor(max_workers=workers, initializer=worker_init) if workers > 1 else None
        try:
            for cohort_no, raw_codes in enumerate(c.cohorts(groups, 128)):
                codes = sorted({aliases[raw] for raw in raw_codes})
                lo = min(sessions[positions[min(dates[code])] - 19] for code in codes)
                hi = max(max(dates[code]) for code in codes)
                f = c.read_cohort(path, schema, mapping, raw_codes, reader, lo=lo, hi=hi)
                rows_read += len(f)
                f['canonical_security_id'] = f.ts_code.map(aliases)
                histories = {code: part.drop(columns='canonical_security_id')
                             for code, part in f.groupby('canonical_security_id', sort=True)}
                empty = f.drop(columns='canonical_security_id').iloc[:0]
                tasks = ((code, histories.get(code, empty), dates[code], sessions, crosswalk) for code in codes)
                results.extend(executor.map(rollup_security, tasks, chunksize=1) if executor else map(rollup_security, tasks))
                print(json.dumps({'stage': 'ADV20', 'cohort': cohort_no, 'codes': sum(len(r.canonical_security_id.unique()) for r in results),
                                  'candidate_keys': sum(len(r) for r in results), 'source_rows_read': rows_read,
                                  'elapsed_seconds': time.monotonic() - started}), flush=True)
                del f, histories
        finally:
            if executor:
                executor.shutdown(wait=True)
        recheck()
    result = pd.concat(results, ignore_index=True).sort_values(c.IDENTITY).reset_index(drop=True)
    pd.testing.assert_frame_equal(result[c.IDENTITY], keys[c.IDENTITY], check_exact=True)
    result.to_parquet(stage / 'adv20.parquet', index=False, compression='zstd')
    counts = {'known': int(result.adv20_cny.notna().sum()), 'UNKNOWN': int(result.adv20_cny.isna().sum()),
              **{'ge_' + str(v): int(result.adv20_cny.ge(v).sum()) for v in [100_000_000, 300_000_000, 500_000_000]}}
    return c.finish_manifest(stage, output_dir, 'adv_manifest.json', {
        'batch': 'ACT-020', 'schema': 'ACT020_ADV20_CNY_V1', 'mode': 'CANARY' if canary_codes else 'FULL',
        'source': source, 'rows': len(result), 'full_candidate_keys': full_keys, 'key_sha256': key_sha256(keys),
        'range': [str(keys.D.min()), str(keys.D.max())], 'counts': counts,
        'fit_manifest_sha256': c.old._sha_file(fit_dir / 'fit_manifest.json'),
        'pre_replay_seal_sha256': c.old._sha_file(fit_dir / 'pre_replay_seal.json'),
        'act018_replay_manifest_sha256': c.old._sha_file(act018_replay_dir / 'replay_manifest.json'),
        'candidate_score_audit_sha256': c.old._sha_file(act018_replay_dir / 'candidate_score_audit.parquet'),
        'market_manifest_sha256': c.old._sha_file(market_dir / 'market_manifest.json'),
        'amount_receipt_sha256': amount_proof['sha256'], 'amount_proof': amount_proof,
        'outputs_sha256': {'adv20.parquet': c.old._sha_file(stage / 'adv20.parquet')},
        'sessions_sha256': hashlib.sha256(json.dumps(sessions).encode()).hexdigest(), 'calendar': calendar_info,
        'crosswalk_sha256': c.old._sha_file(c.old.CROSSWALK_FILE), 'workers': workers, 'source_rows_read': rows_read,
        'code_sha256': {str(p): c.old._sha_file(p) for p in [Path(__file__), ROOT / 'ops/pft_act015_common.py']},
        'semantics': 'sum(original RAW_TURNOVER CNY on D and prior 19 exchange sessions)/20; recorded zero valid; any missing/negative/nonfinite UNKNOWN; no stale fill or conversion',
        'fits_this_stage': 0, 'outcomes_read': False, 'raw_rows_written': 0,
        'source_PIT': 'CANNOT_CONFIRM frozen QFQ; ADV uses raw turnover only'})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['fit-dir', 'act018-replay-dir', 'market-dir', 'data-root', 'act005-root', 'output-dir']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--amount-receipt', type=Path, default=DEFAULT_AMOUNT_RECEIPT)
    parser.add_argument('--workers', type=int, default=16)
    parser.add_argument('--canary-codes', nargs='+')
    try:
        result = derive(**vars(parser.parse_args(argv)))
    except Exception as exc:
        return c.cli_failure(exc)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
