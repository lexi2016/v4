"""ACT017 fit-free 940-session 2x2 timing/router ablation on ACT015 STRICT/H3.

All four arms call the unchanged original portfolio engine with STRICT/ALL/3.
Signals and causal risk inputs are sealed before selected-symbol OHLC reads.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
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
from ops.pft_act016_inputs import annual_thresholds, hybrid_picks, validate_seals
from ops.pft_act017_diagnostics import router_decomposition, portfolio_attribution
pd, np = c.pd, c.np
CONFIGS = [('BASELINE_STRICT', False, False), ('TIMING_ONLY', True, False),
           ('ROUTING_ONLY', False, True), ('TIMING_ROUTING', True, True)]
AUDIT_COLUMNS = ['episode_id', *c.IDENTITY, 'lane', 'model_year', 'held_outer', 'rank_score',
                 'prior_anchor_date', 'prior_anchor_low', 'rank_position', 'S_prob_gated',
                 'B_probability', 'act015_rank_score', 'hybrid_score', 'q80_threshold']


def timing_risk(expanded):
    """Exact ACT016 annual terciles, original STRICT weak-close protection."""
    f = expanded.copy()
    known = f.graded_state.isin(['STRONG', 'NEUTRAL', 'MID', 'WEAK'])
    f['strict_state'] = np.where(~known, 'UNKNOWN', np.where(f.graded_state.eq('WEAK'), 'RISK_OFF', 'RISK_ON'))
    f['strict_cap'] = np.where(known, f.graded_cap, 0.).astype(float)
    f['daily_K'] = 3  # Rank is invariant to timing, including weak dates.
    if not set(f.strict_cap.unique()) <= {0., .5, 1.}:
        raise ValueError('UNEXPECTED_TIMING_CAP')
    return f


def freeze_picks(baseline, predictions, thresholds, risk):
    fixed_k = risk[['D']].assign(daily_K=3)
    route = hybrid_picks(predictions, thresholds, fixed_k)
    frames = []
    for config_id, (scenario, timing, routing) in enumerate(CONFIGS):
        source = route if routing else baseline
        f = source[[x for x in AUDIT_COLUMNS if x in source]].copy()
        if f.duplicated(c.IDENTITY).any() or f.groupby('D').size().gt(3).any():
            raise ValueError('TOP3_OR_DEDUP_DRIFT')
        f['config_id'], f['scenario'], f['horizon'] = config_id, scenario, 3
        frames.append(f)
    # Exact row/value identity across timing pair, excluding config labels only.
    for a, b in [(0, 1), (2, 3)]:
        columns = [x for x in frames[a] if x not in ('config_id', 'scenario')]
        pd.testing.assert_frame_equal(frames[a][columns].reset_index(drop=True),
                                      frames[b][columns].reset_index(drop=True), check_exact=True)
    return pd.concat(frames, ignore_index=True), route


def validate_act016(directory, fit_dir, rank_dir, starter_path, starter_manifest_path, source, thresholds, expanded):
    """ACT016's own manifest uses ACT-016, not the ACT015-only read_manifest validator."""
    manifest = c.old._read_json(directory/'replay_manifest.json')
    if (manifest.get('batch') != 'ACT-016' or manifest.get('mode') != 'FULL'
        or manifest.get('flags') != c.old.FLAGS or manifest.get('fits_this_stage') != 0
        or manifest.get('schema') != 'ACT016_EXACT_CARD_REPLAY_V1'):
        raise ValueError('ACT016_MANIFEST_IDENTITY_DRIFT')
    for rel, sha in manifest['outputs_sha256'].items():
        c.verified_file(directory/rel, sha)
    if (manifest['source']['identity'] != source['identity']
        or manifest['source']['backtest']['panel_sha256'] != source['backtest']['panel_sha256']):
        raise ValueError('ACT016_SOURCE_DRIFT')
    expected = {'fit_manifest_sha256': fit_dir/'fit_manifest.json', 'rank_manifest_sha256': rank_dir/'rank_manifest.json',
                'starter_sha256': starter_path, 'starter_manifest_sha256': starter_manifest_path}
    for key, path in expected.items():
        if manifest['input_seals'][key] != c.old._sha_file(path):
            raise ValueError('ACT016_INPUT_SEAL_DRIFT:'+key)
    sealed = pd.read_csv(directory/'annual_thresholds.csv', float_precision='round_trip',
                         dtype={'calibration_max_D': str, 'B1_max_D': str, 'B2_max_D': str})
    pd.testing.assert_frame_equal(thresholds, sealed, check_exact=True, check_dtype=False)
    sealed_risk = pd.read_csv(directory/'observed_regimes.csv', dtype={'D': str}, float_precision='round_trip')
    cols = ['D', 'B_comp', 'graded_state', 'graded_cap', 'daily_K']
    pd.testing.assert_frame_equal(expanded[cols].reset_index(drop=True), sealed_risk[cols].reset_index(drop=True),
                                  check_exact=True, check_dtype=False)
    # Engine/annual calibration and router implementation are part of this causal identity.
    for path, sha in manifest['code_sha256'].items():
        name = Path(path).name
        if name in ['pft_act015_replay.py', 'pft_act016_inputs.py', 'pft_act016_replay.py']:
            c.verified_file(ROOT/'ops'/name, sha)
    return manifest


def as_picks(frame):
    return {str(d): f.to_dict('records') for d, f in frame.groupby('D', sort=True)}


def run_arm(picks, bars, sessions, risk, scenario, asof=c.ASOF):
    nav, ledger = base.portfolio(picks, bars, sessions, risk, 'STRICT', 'ALL', 3, asof=asof)
    nav['scenario'], ledger['scenario'] = scenario, scenario
    return nav, ledger


_WORK = None


def initialize(payload):
    global _WORK
    _WORK = payload


def execute(spec):
    config_id, scenario, timing, routing = spec
    bars, sessions, original_risk, annual_risk, picks = _WORK
    start, cpu = time.perf_counter(), time.process_time()
    n, l = run_arm(picks[config_id], bars, sessions, annual_risk if timing else original_risk, scenario)
    n['config_id'], l['config_id'] = config_id, config_id
    telemetry = dict(config_id=config_id, scenario=scenario, seconds=time.perf_counter()-start,
                     cpu_seconds=time.process_time()-cpu, peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(json.dumps({'stage': 'ACT017_PORTFOLIO', **telemetry, 'daily_rows': len(n), 'ledger_rows': len(l)}), flush=True)
    return n, l, telemetry


def baseline_parity(nav, ledger, directory):
    results = {}
    for name, actual in [('daily_nav.parquet', nav), ('portfolio_ledger.parquet', ledger)]:
        old = pd.read_parquet(directory/name)
        expected = old.loc[old.scenario.eq('STRICT') & old.pool.eq('ALL') & old.horizon.eq(3)].copy()
        found = actual.loc[actual.scenario.eq('BASELINE_STRICT')].copy()
        columns = [x for x in expected if x not in ('scenario', 'config_id')]
        keys = ['D'] if name.startswith('daily') else ['D', 'canonical_security_id', 'lane']
        pd.testing.assert_frame_equal(found.sort_values(keys)[columns].reset_index(drop=True),
                                      expected.sort_values(keys)[columns].reset_index(drop=True), check_exact=True, check_dtype=False)
        if name.startswith('daily') and len(expected) != 940:
            raise ValueError('ACT015_940_DAY_BASELINE_REQUIRED')
        results[name] = dict(status='PASS_EXACT', rows=len(found), columns=columns)
    return results


def replay(*, fit_dir, rank_dir, act015_replay_dir, act016_replay_dir, data_root, act005_root,
           market_dir, starter_path, starter_manifest_path, output_dir, workers=1):
    if workers not in (1, 2, 3, 4):
        raise ValueError('WORKERS_MUST_BE_1_TO_4')
    m, predictions, market, sessions, calendar_info, starter = validate_seals(
        fit_dir, rank_dir, act015_replay_dir, market_dir, starter_path, starter_manifest_path)
    thresholds, expanded = annual_thresholds(market, predictions, starter)
    validate_act016(act016_replay_dir, fit_dir, rank_dir, starter_path, starter_manifest_path,
                    m['source'], thresholds, expanded)
    if len([d for d in sessions if '20230101' <= d <= c.ASOF]) != 940:
        raise ValueError('EXACT_940_SESSIONS_REQUIRED')
    original = pd.read_csv(rank_dir/'causal_regimes.csv', dtype={'D': str}, float_precision='round_trip')
    annual = timing_risk(expanded)
    ranked = pd.read_parquet(rank_dir/'ranked_signals.parquet')
    baseline = ranked.loc[ranked.pool.eq('ALL')].sort_values(['D', 'rank_position']).reset_index(drop=True)
    picked, routed = freeze_picks(baseline, predictions, thresholds, annual)
    router_summary, router_audit = router_decomposition(predictions, thresholds, baseline, routed, sessions)
    stage = c.new_stage(output_dir)
    picked.to_parquet(stage/'picked_signals.parquet', index=False, compression='zstd')
    thresholds.to_csv(stage/'annual_thresholds.csv', index=False, float_format='%.17g')
    annual.to_csv(stage/'annual_timing_risk.csv', index=False, float_format='%.17g')
    original.to_csv(stage/'baseline_risk.csv', index=False, float_format='%.17g')
    router_summary.to_csv(stage/'router_decomposition.csv', index=False)
    router_audit.to_csv(stage/'router_top3_audit.csv', index=False, float_format='%.17g')
    configs = [dict(config_id=i, scenario=s, timing=t, routing=r, engine_scenario='STRICT', pool='ALL', horizon=3, K=3)
               for i, (s, t, r) in enumerate(CONFIGS)]
    c.write_json(stage/'configs.json', configs)
    seal = dict(batch='ACT-017', fits_this_stage=0, execution_ohlc_read=False,
                fit_manifest_sha256=c.old._sha_file(fit_dir/'fit_manifest.json'),
                rank_manifest_sha256=c.old._sha_file(rank_dir/'rank_manifest.json'),
                act015_replay_manifest_sha256=c.old._sha_file(act015_replay_dir/'replay_manifest.json'),
                act016_replay_manifest_sha256=c.old._sha_file(act016_replay_dir/'replay_manifest.json'),
                market_manifest_sha256=c.old._sha_file(market_dir/'market_manifest.json'),
                starter_sha256=c.old._sha_file(starter_path), starter_manifest_sha256=c.old._sha_file(starter_manifest_path),
                source=m['source'], outputs_sha256={p.name: c.old._sha_file(p) for p in stage.iterdir() if p.is_file()})
    c.write_json(stage/'pre_execution_seal.json', seal)
    codes = set(picked.canonical_security_id)
    bars, source, read_counts = base.read_bars(data_root=data_root, act005_root=act005_root, fit_manifest=m, codes=codes)
    picks = {i: as_picks(picked.loc[picked.config_id.eq(i)]) for i in range(4)}
    shared = (bars, sessions, original.set_index('D').to_dict('index'), annual.set_index('D').to_dict('index'), picks)
    specs = [(i, *config) for i, config in enumerate(CONFIGS)]
    global _WORK
    if workers == 1:
        initialize(shared)
        results = [execute(spec) for spec in specs]
        _WORK = None
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn'),
                                 initializer=initialize, initargs=(shared,)) as executor:
            results = list(executor.map(execute, specs, chunksize=1))
    nav = pd.concat([r[0] for r in results], ignore_index=True)
    ledger = pd.concat([r[1] for r in results], ignore_index=True)
    parity = baseline_parity(nav, ledger, act015_replay_dir)
    summary = base.metrics(nav, ledger)
    if len(summary) != 20:
        raise ValueError('FOUR_CONFIG_FIVE_PERIOD_METRICS_REQUIRED')
    nav.to_parquet(stage/'daily_nav.parquet', index=False, compression='zstd')
    ledger.to_parquet(stage/'portfolio_ledger.parquet', index=False, compression='zstd')
    summary.to_csv(stage/'metrics.csv', index=False, float_format='%.17g')
    for name, frame in portfolio_attribution(nav, ledger, bars, sessions, picked, annual).items():
        frame.to_csv(stage/name, index=False, float_format='%.17g')
    del shared, bars
    c.write_json(stage/'baseline_parity.json', parity)
    c.write_json(stage/'worker_telemetry.json', [r[2] for r in results])
    outputs = {p.name: c.old._sha_file(p) for p in stage.iterdir() if p.is_file()}
    return c.finish_manifest(stage, output_dir, 'replay_manifest.json', dict(
        batch='ACT-017', schema='ACT017_940D_STRICT_H3_ABLATION_V1', mode='FULL', source=source,
        outputs_sha256=outputs, fits_this_stage=0, horizon=3, K=3, engine='pft_act015_replay.portfolio STRICT/ALL/3 defaults',
        configs=configs, input_seals=seal, calendar=calendar_info, read_counts=read_counts, workers=workers,
        baseline_parity=parity, fees={'buy': base.BUY_FEE, 'sell': base.SELL_FEE},
        sessions_by_year=nav.loc[nav.config_id.eq(0)].D.str[:4].value_counts().sort_index().to_dict(),
        execution_marks_storage='selected symbols/columns read once via original read_bars; memory only; no OHLC file',
        source_PIT='CANNOT_CONFIRM frozen QFQ replay; 2022 starter issuer-held-out, not chronological 2022 OOS',
        semantics={'timing': 'ACT016 expanding annual terciles => strict_cap 1/.5/0; weak RISK_OFF, neutral+strong RISK_ON; prior D opening cap; original weak-close exit',
                   'router': 'ACT016 hybrid_picks with daily_K=3 on every signal date, independent of timing',
                   'protection': 'all four arms original STRICT protection and exposure room; no custom stop or trim',
                   'attribution': 'closed cumulative realized PnL; live net close mark less allocation; delta endpoints exactly reconcile NAV change atol1e-10; carryover included',
                   'MDD_ties': 'earliest minimum drawdown trough, earliest preceding maximum NAV peak, annual previous close included'},
        code_sha256={str(p): c.old._sha_file(p) for p in [Path(__file__), ROOT/'ops/pft_act017_diagnostics.py',
                         ROOT/'ops/pft_act015_replay.py', ROOT/'ops/pft_act016_inputs.py']}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['fit-dir', 'rank-dir', 'act015-replay-dir', 'act016-replay-dir', 'data-root', 'act005-root',
                 'market-dir', 'starter-path', 'starter-manifest-path', 'output-dir']:
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--workers', type=int, default=1)
    try:
        result = replay(**vars(parser.parse_args(argv)))
    except Exception as exc:
        return c.cli_failure(exc)
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
