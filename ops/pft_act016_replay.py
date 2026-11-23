"""ACT016 sealed, fit-free replay of annual expanding HYBRID parameter card.

Uses the ACT015 cash/fill engine. New sleeve timing never trims old lots;
card variants exit only at scheduled close or fixed low trigger -> next open.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import json
import math
import multiprocessing as mp
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops import pft_act015_common as c
from ops import pft_act015_replay as base
from ops.pft_act016_inputs import (SCENARIOS, annual_thresholds, hybrid_picks,
                                   read_amounts, validate_seals)
np, pd = c.np, c.pd


def card_protection(lot, row, day, scenario, regime, *, fixed_stop):
    """Touch uses tradable positive LOW; actual execution remains directional OPEN."""
    if fixed_stop is None:
        return []
    threshold = lot['entry_open']*(1-fixed_stop)
    lot['fixed_stop_pct'] = fixed_stop
    lot['fixed_stop_threshold'] = threshold
    low = base.number(row or {}, 'low')
    if not base.valid_mark(row) or not math.isfinite(low) or low <= 0:
        return []
    if low <= threshold and not lot['pending_reason']:
        lot.update(pending_reason='FIXED_STOP', trigger_reasons='FIXED_STOP_LOW_TOUCH',
                   trigger_date=day, fixed_stop_trigger_low=low)
        return ['FIXED_STOP_LOW_TOUCH']
    return []


def run_portfolio(picks, bars, sessions, risk, scenario, horizon, fixed_stop=None, asof=c.ASOF):
    if scenario == 'BASELINE_STRICT':
        n, l = base.portfolio(picks, bars, sessions, risk, 'STRICT', 'ALL', horizon, asof=asof)
    else:
        n, l = base.portfolio(picks, bars, sessions, risk, 'GRADED', 'ALL', horizon, asof=asof,
            protection_policy=partial(card_protection, fixed_stop=fixed_stop), tier_as_exposure_ceiling=False)
        if fixed_stop is not None:
            l['fixed_stop_pct'] = fixed_stop
            l['fixed_stop_threshold'] = l.get('entry_open', pd.Series(np.nan, index=l.index))*(1-fixed_stop)
    n['scenario'], l['scenario'] = scenario, scenario
    return n, l


def as_picks(frame):
    return {str(day): rows.to_dict('records') for day, rows in frame.groupby('D', sort=True)}


# Spawn receives one bounded in-memory selected-symbol projection per worker.
# No inherited Arrow threads, persisted marks or per-task repeated full payload.
_WORK = None


def _initialize_worker(payload):
    global _WORK
    _WORK = payload


def _execute(spec):
    config_id, scenario, stop, liquid, horizon = spec
    bars, sessions, baseline_risk, expanded_risk, baseline_picks, plain_picks, liquid_picks = _WORK
    start, cpu = time.perf_counter(), time.process_time()
    picks = baseline_picks if scenario == 'BASELINE_STRICT' else (liquid_picks if liquid else plain_picks)
    risk = baseline_risk if scenario == 'BASELINE_STRICT' else expanded_risk
    n, l = run_portfolio(picks, bars, sessions, risk, scenario, horizon, stop)
    n['config_id'], l['config_id'] = config_id, config_id
    telemetry = dict(config_id=config_id, elapsed_seconds=time.perf_counter()-start,
                     cpu_seconds=time.process_time()-cpu, peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(json.dumps({'stage': 'ACT016_PORTFOLIO', **telemetry, 'scenario': scenario, 'horizon': horizon}), flush=True)
    return n, l, telemetry


def baseline_parity(nav, act015_replay_dir):
    expected = pd.read_parquet(act015_replay_dir/'daily_nav.parquet')
    expected = expected.loc[expected.scenario.eq('STRICT') & expected.pool.eq('ALL')].copy()
    actual = nav.loc[nav.scenario.eq('BASELINE_STRICT')].copy()
    columns = [name for name in expected.columns if name not in ('scenario', 'config_id')]
    pd.testing.assert_frame_equal(actual.sort_values(['horizon', 'D'])[columns].reset_index(drop=True),
        expected.sort_values(['horizon', 'D'])[columns].reset_index(drop=True), check_exact=True, check_dtype=False)
    return {'status': 'PASS_EXACT', 'rows': len(actual), 'columns': columns}


def replay(*, fit_dir, rank_dir, act015_replay_dir, data_root, act005_root, market_dir,
           starter_path, starter_manifest_path, output_dir, turnover_unit, workers=1):
    if not 1 <= workers <= 14:
        raise ValueError('WORKERS_OUT_OF_BOUNDS')
    m, predictions, market, sessions, calendar_info, starter = validate_seals(
        fit_dir, rank_dir, act015_replay_dir, market_dir, starter_path, starter_manifest_path)
    thresholds, expanded = annual_thresholds(market, predictions, starter)
    baseline_risk = pd.read_csv(rank_dir/'causal_regimes.csv', dtype={'D': str}).set_index('D').to_dict('index')
    ranked = pd.read_parquet(rank_dir/'ranked_signals.parquet')
    if ranked.duplicated(['pool', *c.IDENTITY]).any():
        raise ValueError('DUPLICATE_BASELINE_RANK_KEY')
    baseline_frame = ranked.loc[ranked.pool.eq('ALL')].sort_values(['D', 'rank_position'])
    plain = hybrid_picks(predictions, thresholds, expanded)
    amounts = read_amounts(data_root=data_root, act005_root=act005_root, fit_manifest=m,
                          predictions=predictions, turnover_unit=turnover_unit)
    liquid = hybrid_picks(predictions, thresholds, expanded, amounts)
    # Freeze only signal/result columns, never forward labels or execution bars.
    columns = ['episode_id', *c.IDENTITY, 'lane', 'model_year', 'held_outer', 'rank_score',
               'prior_anchor_date', 'prior_anchor_low', 'rank_position', 'S_prob_gated', 'B_probability',
               'act015_rank_score', 'hybrid_score', 'q80_threshold', 'amount_cny']
    stage = c.new_stage(output_dir)
    picked, configs = [], []
    specs = []
    for scenario, stop, liquidity in SCENARIOS:
        selected = baseline_frame if scenario == 'BASELINE_STRICT' else liquid if liquidity else plain
        for horizon in (3, 5):
            cfg = len(configs)
            configs.append(dict(config_id=cfg, scenario=scenario, fixed_stop=stop,
                                liquidity_min_cny=100_000_000 if liquidity else None, horizon=horizon, pool='ALL'))
            audit = selected[[x for x in columns if x in selected]].copy()
            audit['config_id'], audit['scenario'], audit['horizon'] = cfg, scenario, horizon
            picked.append(audit)
            specs.append((cfg, scenario, stop, liquidity, horizon))
    pd.concat(picked, ignore_index=True).to_parquet(stage/'picked_signals.parquet', index=False, compression='zstd')
    thresholds.to_csv(stage/'annual_thresholds.csv', index=False, float_format='%.17g')
    expanded.to_csv(stage/'observed_regimes.csv', index=False, float_format='%.17g')
    c.write_json(stage/'configs.json', configs)
    seal = dict(batch='ACT-016', fits_this_stage=0, execution_ohlc_read=False,
                fit_manifest_sha256=c.old._sha_file(fit_dir/'fit_manifest.json'),
                rank_manifest_sha256=c.old._sha_file(rank_dir/'rank_manifest.json'),
                starter_sha256=c.old._sha_file(starter_path), starter_manifest_sha256=c.old._sha_file(starter_manifest_path),
                outputs_sha256={p.name: c.old._sha_file(p) for p in stage.iterdir() if p.is_file()})
    c.write_json(stage/'pre_execution_seal.json', seal)
    codes = set(pd.concat([baseline_frame, plain, liquid], ignore_index=True).canonical_security_id)
    bars, source, counts = base.read_bars(data_root=data_root, act005_root=act005_root, fit_manifest=m, codes=codes)
    shared = (bars, sessions, baseline_risk, expanded.set_index('D').to_dict('index'),
              as_picks(baseline_frame), as_picks(plain), as_picks(liquid))
    if workers == 1:
        _initialize_worker(shared)
        results = [_execute(spec) for spec in specs]
        global _WORK
        _WORK = None
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn'),
                                 initializer=_initialize_worker, initargs=(shared,)) as executor:
            results = list(executor.map(_execute, specs, chunksize=1))
    del shared, bars
    nav = pd.concat([r[0] for r in results], ignore_index=True)
    ledger = pd.concat([r[1] for r in results], ignore_index=True)
    parity = baseline_parity(nav, act015_replay_dir)
    summary = base.metrics(nav, ledger)
    nav.to_parquet(stage/'daily_nav.parquet', index=False, compression='zstd')
    ledger.to_parquet(stage/'portfolio_ledger.parquet', index=False, compression='zstd')
    summary.to_csv(stage/'metrics.csv', index=False, float_format='%.12g')
    c.write_json(stage/'worker_telemetry.json', [r[2] for r in results])
    c.write_json(stage/'baseline_parity.json', parity)
    (stage/'changelog.md').write_text('ACT016: exact prior-year expanding tertiles; issuer-held-out RF q80 B1/B2, S*B B3; '
        'new sleeve timing only; no old-lot trims or inherited protection in card scenarios; '
        'low-touch fixed stops queue actual next eligible open; scheduled close precedes a NEW same-day touch. '
        'ACT015 strict path unchanged and exact daily accounting parity required. No model fit.\n', encoding='utf-8')
    outputs = {p.name: c.old._sha_file(p) for p in stage.iterdir() if p.is_file()}
    return c.finish_manifest(stage, output_dir, 'replay_manifest.json', dict(
        batch='ACT-016', schema='ACT016_EXACT_CARD_REPLAY_V1', mode='FULL', source=source,
        outputs_sha256=outputs, configs=configs, fits_this_stage=0, fees={'buy': base.BUY_FEE, 'sell': base.SELL_FEE},
        input_seals=seal, calendar=calendar_info, read_counts=counts, workers=workers,
        baseline_parity=parity, execution_marks_storage='transient process memory only; released after workers exit',
        ranker='ACT015 issuer-held-out RandomForest return-risk scalar, different from GEMINI GBDT',
        turnover_unit=turnover_unit, turnover_multiplier=1, source_PIT='CANNOT_CONFIRM frozen QFQ replay',
        semantics={'q33_equality': 'NEUTRAL', 'q67_equality': 'STRONG; wins if equal q33',
                   'tier': 'NEW sleeve only; no trim or exposure ceiling on existing lots',
                   'liquidity': 'D RAW_TURNOVER >=1e8 CNY before TopK; UNKNOWN excluded',
                   'stops': 'tradable positive LOW <= entry OPEN*(1-stop); T+1 next directional eligible OPEN, actual gap price',
                   'scheduled': 'D+H tradable CLOSE before NEW same-day stop touch; earlier pending stops retain next-open priority'},
        code_sha256={str(p): c.old._sha_file(p) for p in [Path(__file__), ROOT/'ops/pft_act016_inputs.py', ROOT/'ops/pft_act015_replay.py']}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['fit-dir', 'rank-dir', 'act015-replay-dir', 'data-root', 'act005-root', 'market-dir',
                 'starter-path', 'starter-manifest-path', 'output-dir']:
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--turnover-unit', required=True, choices=['CNY_RAW'])
    parser.add_argument('--workers', type=int, default=1)
    try:
        result = replay(**vars(parser.parse_args(argv)))
    except Exception as exc:
        return c.cli_failure(exc)
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
