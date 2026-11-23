"""ACT018 fit-free lane percentiles; reuse ACT017 arms and replay only the new arm."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops import pft_act015_common as c, pft_act015_replay as base
from ops.pft_act016_inputs import hard_mask, annual_thresholds, hybrid_picks, validate_seals
from ops.pft_act017_ablation import validate_act016, as_picks
from ops.pft_act017_diagnostics import portfolio_attribution
pd, np = c.pd, c.np
CONFIGS = [(0, 'BASELINE_RF'), (1, 'ORIGINAL_HYBRID'), (2, 'PERCENTILE_HYBRID')]
REUSE = {'BASELINE_STRICT': (0, 'BASELINE_RF'), 'ROUTING_ONLY': (1, 'ORIGINAL_HYBRID')}
CASES = [('20231107', '603985.SH'), ('20231109', '002855.SZ'), ('20230301', '688787.SH'),
         ('20250611', '603332.SH'), ('20250630', '002951.SZ'), ('20250320', '920418.BJ')]


def midrank_percentile(sorted_scores, values):
    """Empirical (count less + .5 * count equal) / N, with exact numeric ties."""
    scores, values = np.asarray(sorted_scores, dtype=float), np.asarray(values, dtype=float)
    if not len(scores) or not np.isfinite(scores).all() or (np.diff(scores) < 0).any():
        raise ValueError('INVALID_SORTED_CALIBRATION_SCORES')
    if not np.isfinite(values).all():
        raise ValueError('NONFINITE_QUERY_SCORE')
    return (np.searchsorted(scores, values, side='left') +
            np.searchsorted(scores, values, side='right')) / (2. * len(scores))


def raw_score(frame):
    return np.where(frame.lane.eq('B3'), frame.S_prob_gated*frame.B_probability, frame.rank_score)


def annual_calibrators(predictions, starter, b3_starter, years=range(2023, 2027)):
    """All hard eligible lane rows strictly before Jan 1; no outcome fields used."""
    cols = ['episode_id', 'D', 'canonical_security_id', 'lane', 'S_prob_gated',
            'B_probability', 'rank_score', 'hard_eligible']
    if not starter.lane.isin(['B1', 'B2']).all() or not b3_starter.lane.eq('B3').all():
        raise ValueError('SEED_LANE_DRIFT')
    for seed in [starter, b3_starter]:
        if seed.empty or not seed.D.between('20220101', '20221231').all():
            raise ValueError('SEED_DATE_DRIFT')
    f = pd.concat([starter[cols], b3_starter[cols], predictions[cols]], ignore_index=True)
    if f.episode_id.duplicated().any() or f.duplicated([*c.IDENTITY, 'lane']).any():
        raise ValueError('CALIBRATION_EPISODE_OVERLAP')
    if not f.lane.isin(c.LANES).all():
        raise ValueError('UNKNOWN_LANE')
    f = f.loc[hard_mask(f)].copy()
    f['raw_score'] = raw_score(f)
    calibrators, summary, uniques = {}, [], []
    for year in years:
        for lane in c.LANES:
            train = f.loc[f.D.ge('20220101') & f.D.lt(f'{year}0101') & f.lane.eq(lane)]
            scores = np.sort(train.raw_score.to_numpy(float), kind='mergesort')
            if not len(scores) or not np.isfinite(scores).all():
                raise ValueError(f'EMPTY_OR_INVALID_CALIBRATOR:{year}:{lane}')
            unique, counts = np.unique(scores, return_counts=True)
            max_d = str(train.D.max())
            if max_d >= f'{year}0101':
                raise ValueError('FORWARD_CALIBRATION')
            identity = train[['episode_id', 'D', 'raw_score']].sort_values(['D', 'episode_id']).to_csv(index=False, float_format='%.17g').encode()
            summary.append(dict(year=year, lane=lane, n=len(scores), max_D=max_d, min_D=str(train.D.min()),
                score_min=float(scores[0]), score_max=float(scores[-1]),
                **{f'score_q{int(q*100):02}': float(np.quantile(scores, q)) for q in [0.01, .25, .5, .75, .8, .95, .99]},
                unique_scores=len(unique), scores_sha256=hashlib.sha256(scores.astype('<f8').tobytes()).hexdigest(),
                membership_sha256=hashlib.sha256(identity).hexdigest()))
            uniques.append(pd.DataFrame(dict(year=year, lane=lane, raw_score=unique, count=counts)))
            calibrators[year, lane] = scores
    return calibrators, pd.DataFrame(summary), pd.concat(uniques, ignore_index=True)


def percentile_picks(predictions, thresholds, calibrators):
    """Identical ACT016 ready pool/Q80, percentile sort, code/lane ties, then dedup Top3."""
    f = predictions.loc[hard_mask(predictions) & predictions.D.between('20230101', c.ASOF)].copy()
    if not f.lane.isin(c.LANES).all():
        raise ValueError('UNKNOWN_LANE')
    t = thresholds.set_index('year')
    f['act015_rank_score'] = f.rank_score
    f['hybrid_score'] = raw_score(f)
    f['raw_score'] = f.hybrid_score
    f['q80_threshold'] = [t.loc[int(d[:4]), lane+'_q80'] if lane in ('B1', 'B2') else np.nan
                          for d, lane in zip(f.D, f.lane)]
    f['pass_raw_q80'] = f.lane.eq('B3') | f.rank_score.ge(f.q80_threshold)
    f['percentile_score'] = np.nan
    f['calibrator_year'] = f.D.str[:4].astype(int)
    for (year, lane), indexes in f.groupby(['calibrator_year', 'lane']).groups.items():
        f.loc[indexes, 'percentile_score'] = midrank_percentile(calibrators[year, lane], f.loc[indexes, 'raw_score'])
    ready = f.loc[f.pass_raw_q80].sort_values(['D', 'percentile_score', 'canonical_security_id', 'lane'],
                    ascending=[True, False, True, True], kind='mergesort').copy()
    ready['ready_lane_rank'] = ready.groupby('D').cumcount()+1
    dedup = ready.drop_duplicates(c.IDENTITY, keep='first').copy()
    dedup['rank_position'] = dedup.groupby('D').cumcount()+1
    picked = dedup.loc[dedup.rank_position.le(3)].copy()
    # A mechanical ready-pool check against the unchanged original route, before Top3.
    original_all = hybrid_picks(predictions, thresholds, pd.DataFrame({'D': sorted(f.D.unique()), 'daily_K': len(f)+1}))
    expected = ready.sort_values(['D', 'hybrid_score', 'canonical_security_id', 'lane'],
                    ascending=[True, False, True, True], kind='mergesort').drop_duplicates(c.IDENTITY)
    keys = [*c.IDENTITY, 'lane', 'rank_score', 'q80_threshold', 'hybrid_score']
    pd.testing.assert_frame_equal(expected.sort_values(c.IDENTITY)[keys].reset_index(drop=True),
                                  original_all.sort_values(c.IDENTITY)[keys].reset_index(drop=True), check_exact=True)
    f = f.merge(ready[['episode_id', 'ready_lane_rank']], on='episode_id', how='left', validate='one_to_one')
    return picked.reset_index(drop=True), f.reset_index(drop=True)


def rename_reused(frame):
    f = frame.loc[frame.scenario.isin(REUSE)].copy()
    f['config_id'] = f.scenario.map(lambda s: REUSE[s][0])
    f['scenario'] = f.scenario.map(lambda s: REUSE[s][1])
    rename = {}
    for column in f:
        for old, (_, new) in REUSE.items():
            if column.startswith(old+'_'):
                rename[column] = new+column[len(old):]
    return f.rename(columns=rename)


def validate_act017(directory, source, paths):
    m = c.old._read_json(directory/'replay_manifest.json')
    if (m.get('batch') != 'ACT-017' or m.get('flags') != c.old.FLAGS or m.get('mode') != 'FULL'
        or m.get('schema') != 'ACT017_940D_STRICT_H3_ABLATION_V1' or m.get('fits_this_stage') != 0):
        raise ValueError('ACT017_MANIFEST_DRIFT')
    if (m['source']['identity'] != source['identity'] or
        m['source']['backtest']['panel_sha256'] != source['backtest']['panel_sha256']):
        raise ValueError('ACT017_SOURCE_DRIFT')
    for rel, sha in m['outputs_sha256'].items():
        c.verified_file(directory/rel, sha)
    for key, path in paths.items():
        if m['input_seals'][key] != c.old._sha_file(path):
            raise ValueError('ACT017_INPUT_SEAL_DRIFT:'+key)
    for path, sha in m['code_sha256'].items():
        c.verified_file(ROOT/'ops'/Path(path).name, sha)
    return m


def validate_b3(path, manifest_path, fit_dir, fit_manifest):
    m = c.old._read_json(manifest_path)
    expected = {r: sha for r, sha in fit_manifest['outputs_sha256'].items()
                if r.startswith('models/2023_') and Path(r).name in ('S_MAIN.joblib', 'B3_B.joblib', 'B3_RANK_H5.joblib')}
    if (m.get('batch') != 'ACT-018' or m.get('mode') != 'FULL' or m.get('fit_calls') != 0
        or m.get('calibration_model_year') != 2023
        or m.get('issuer_held_excluded_from_all_scoring_weights') is not True
        or m.get('chronological_2022_oos') is not False or m.get('date_scope') != ['20220101', '20221231']
        or m.get('fit_models_sha256') != expected or len(expected) != 6
        or m.get('fit_manifest_sha256') != c.old._sha_file(fit_dir/'fit_manifest.json')
        or m['source']['identity'] != fit_manifest['source']['identity']
        or m['source']['backtest']['panel_sha256'] != fit_manifest['source']['backtest']['panel_sha256']):
        raise ValueError('B3_STARTER_MANIFEST_DRIFT')
    c.verified_file(path, m['sha256'])
    f = pd.read_parquet(path)
    if (len(f) != m['rows'] or f.empty or not f.lane.eq('B3').all() or not hard_mask(f).all()
        or not f.D.between('20220101', '20221231').all() or not f.outer.eq(f.held_outer).all()
        or not f.model_year.eq(2023).all() or f.episode_id.duplicated().any()
        or f.D.min() != m['date_min'] or f.D.max() != m['date_max']
        or not f.outer.eq(f.canonical_security_id.map(c.bucket)).all()):
        raise ValueError('B3_STARTER_ROWS_DRIFT')
    np.testing.assert_array_equal(f.hybrid_score.to_numpy(), (f.S_prob_gated*f.B_probability).to_numpy())
    return f


def score_distributions(audit, picked):
    records = []
    for label, frame in [('HARD', audit), ('READY', audit.loc[audit.pass_raw_q80]), ('SELECTED', picked)]:
        for (year, lane), f in frame.groupby([frame.D.str[:4], 'lane']):
            record = dict(stage=label, year=year, lane=lane, n=len(f), dates=f.D.nunique())
            for name in ['rank_score', 'raw_score', 'percentile_score']:
                values = f[name].to_numpy(float)
                record.update({name+'_'+q: float(v) for q, v in zip(['min', 'q01', 'q25', 'q50', 'q75', 'q95', 'q99', 'max'],
                    np.quantile(values, [0, .01, .25, .5, .75, .95, .99, 1]))})
            records.append(record)
    return pd.DataFrame(records)


def hotspot_comparisons(picked, ledger, audit):
    rows, traces = [], []
    for day, code in CASES:
        hard = audit.loc[audit.D.eq(day) & audit.canonical_security_id.eq(code)]
        for config_id, scenario in CONFIGS:
            chosen = picked.loc[picked.config_id.eq(config_id) & picked.D.eq(day)]
            target = chosen.loc[chosen.canonical_security_id.eq(code)]
            trades = ledger.loc[ledger.config_id.eq(config_id) & ledger.D.eq(day)]
            lots = trades.loc[trades.canonical_security_id.eq(code)]
            filled = lots.loc[lots.status.isin(['OPEN', 'CLOSED'])]
            closed = lots.loc[lots.status.eq('CLOSED')]
            item = target.iloc[0].to_dict() if len(target) else (hard.sort_values('percentile_score', ascending=False).iloc[0].to_dict() if len(hard) else {})
            rows.append(dict(case_D=day, canonical_security_id=code, config_id=config_id, scenario=scenario,
                prediction_present=bool(len(hard)), selected=bool(len(target)), filled=bool(len(filled)), closed=bool(len(closed)),
                lane=item.get('lane'), selected_rank=item.get('rank_position') if len(target) else None,
                ready_lane_rank=item.get('ready_lane_rank'), rank_score=item.get('rank_score'), raw_score=item.get('raw_score', item.get('hybrid_score')),
                percentile_score=item.get('percentile_score'), q80_threshold=item.get('q80_threshold'),
                entry_status='|'.join(lots.entry_status.astype(str)) if len(lots) else 'NOT_SELECTED',
                entry_date='|'.join(lots.entry_date.fillna('').astype(str)) if len(lots) and 'entry_date' in lots else '',
                exit_date='|'.join(lots.exit_date.fillna('').astype(str)) if len(lots) else '',
                exit_reason='|'.join(lots.exit_reason.fillna('').astype(str)) if len(lots) else '',
                buy_fee=float(lots.buy_fee.sum()), sell_fee=float(lots.sell_fee.sum()),
                realized_pnl=float(closed.realized_pnl.sum()) if len(closed) else np.nan,
                interpretation='selection replacement only; no timing-off loss-rescue claim'))
            for signal in chosen.to_dict('records'):
                lot = trades.loc[trades.episode_id.eq(signal['episode_id'])]
                traces.append(dict(case_D=day, case_security_id=code, **{k: signal.get(k) for k in
                    ['config_id', 'scenario', 'episode_id', 'canonical_security_id', 'lane', 'rank_position', 'rank_score', 'raw_score', 'percentile_score']},
                    entry_status=lot.iloc[0].get('entry_status') if len(lot) else 'NO_LEDGER_ROW',
                    status=lot.iloc[0].get('status') if len(lot) else 'NO_LEDGER_ROW',
                    allocation=lot.iloc[0].get('allocation') if len(lot) else np.nan,
                    buy_fee=lot.iloc[0].get('buy_fee') if len(lot) else np.nan,
                    sell_fee=lot.iloc[0].get('sell_fee') if len(lot) else np.nan,
                    realized_pnl=lot.iloc[0].get('realized_pnl') if len(lot) else np.nan))
    return pd.DataFrame(rows), pd.DataFrame(traces)


def replay(*, fit_dir, rank_dir, act015_replay_dir, act016_replay_dir, act017_replay_dir,
           data_root, act005_root, market_dir, starter_path, starter_manifest_path,
           b3_starter_path, b3_starter_manifest_path, output_dir):
    m, predictions, market, sessions, calendar_info, starter = validate_seals(
        fit_dir, rank_dir, act015_replay_dir, market_dir, starter_path, starter_manifest_path)
    thresholds, expanded = annual_thresholds(market, predictions, starter)
    validate_act016(act016_replay_dir, fit_dir, rank_dir, starter_path, starter_manifest_path, m['source'], thresholds, expanded)
    paths = {'fit_manifest_sha256': fit_dir/'fit_manifest.json', 'rank_manifest_sha256': rank_dir/'rank_manifest.json',
             'act015_replay_manifest_sha256': act015_replay_dir/'replay_manifest.json',
             'act016_replay_manifest_sha256': act016_replay_dir/'replay_manifest.json',
             'market_manifest_sha256': market_dir/'market_manifest.json',
             'starter_sha256': starter_path, 'starter_manifest_sha256': starter_manifest_path}
    validate_act017(act017_replay_dir, m['source'], paths)
    days = [d for d in sessions if '20230101' <= d <= c.ASOF]
    if len(days) != 940:
        raise ValueError('EXACT_940_SESSIONS_REQUIRED')
    b3 = validate_b3(b3_starter_path, b3_starter_manifest_path, fit_dir, m)
    calibrators, calibration, uniques = annual_calibrators(predictions, starter, b3)
    new, audit = percentile_picks(predictions, thresholds, calibrators)
    new['config_id'], new['scenario'], new['horizon'] = 2, 'PERCENTILE_HYBRID', 3
    original_risk = pd.read_csv(rank_dir/'causal_regimes.csv', dtype={'D': str}, float_precision='round_trip')
    old_picked = rename_reused(pd.read_parquet(act017_replay_dir/'picked_signals.parquet'))
    route = hybrid_picks(predictions, thresholds, pd.DataFrame({'D': days, 'daily_K': 3}))
    original_pick = old_picked.loc[old_picked.config_id.eq(1)]
    keys = ['episode_id', *c.IDENTITY, 'lane', 'rank_score', 'rank_position', 'hybrid_score', 'q80_threshold']
    pd.testing.assert_frame_equal(original_pick.sort_values(['D','rank_position'])[keys].reset_index(drop=True),
                                  route.sort_values(['D','rank_position'])[keys].reset_index(drop=True), check_exact=True)
    enrich = audit[['episode_id', 'raw_score', 'percentile_score', 'calibrator_year', 'pass_raw_q80', 'ready_lane_rank']]
    old_picked = old_picked.merge(enrich, on='episode_id', how='left', validate='many_to_one')
    picked = pd.concat([old_picked, new], ignore_index=True)
    stage = c.new_stage(output_dir)
    picked.to_parquet(stage/'picked_signals.parquet', index=False, compression='zstd')
    audit.to_parquet(stage/'candidate_score_audit.parquet', index=False, compression='zstd')
    uniques.to_parquet(stage/'calibrator_unique_scores.parquet', index=False, compression='zstd')
    calibration.to_csv(stage/'calibrator_summary.csv', index=False, float_format='%.17g')
    score_distributions(audit, new).to_csv(stage/'score_distributions.csv', index=False, float_format='%.17g')
    thresholds.to_csv(stage/'annual_thresholds.csv', index=False, float_format='%.17g')
    configs = [dict(config_id=i, scenario=s, engine_scenario='STRICT', pool='ALL', horizon=3, K=3,
                    reused_from=next((old for old, pair in REUSE.items() if pair == (i,s)), None)) for i,s in CONFIGS]
    c.write_json(stage/'configs.json', configs)
    seal = dict(batch='ACT-018', fits_this_stage=0, execution_ohlc_read=False, source=m['source'],
        **{k:c.old._sha_file(v) for k,v in paths.items()},
        act017_replay_manifest_sha256=c.old._sha_file(act017_replay_dir/'replay_manifest.json'),
        b3_starter_sha256=c.old._sha_file(b3_starter_path),
        b3_starter_manifest_sha256=c.old._sha_file(b3_starter_manifest_path),
        outputs_sha256={p.name:c.old._sha_file(p) for p in stage.iterdir() if p.is_file()})
    c.write_json(stage/'pre_execution_seal.json', seal)
    # One canonical in-memory read, strictly limited to the newly selected symbols.
    bars, source, read_counts = base.read_bars(data_root=data_root, act005_root=act005_root, fit_manifest=m,
                                             codes=set(new.canonical_security_id))
    n, l = base.portfolio(as_picks(new), bars, sessions, original_risk.set_index('D').to_dict('index'), 'STRICT', 'ALL', 3)
    n['scenario'], l['scenario'], n['config_id'], l['config_id'] = 'PERCENTILE_HYBRID', 'PERCENTILE_HYBRID', 2, 2
    reused_n = rename_reused(pd.read_parquet(act017_replay_dir/'daily_nav.parquet'))
    reused_l = rename_reused(pd.read_parquet(act017_replay_dir/'portfolio_ledger.parquet'))
    for _, frame in reused_n.groupby('config_id'):
        if frame.D.tolist() != days:
            raise ValueError('REUSED_940_SESSION_DRIFT')
    nav, ledger = pd.concat([reused_n, n], ignore_index=True), pd.concat([reused_l, l], ignore_index=True)
    nav.to_parquet(stage/'daily_nav.parquet', index=False, compression='zstd')
    ledger.to_parquet(stage/'portfolio_ledger.parquet', index=False, compression='zstd')
    metrics = base.metrics(nav, ledger)
    metrics['config_id'] = metrics.scenario.map({s:i for i,s in CONFIGS})
    if len(metrics) != 15:
        raise ValueError('THREE_ARMS_FIVE_PERIOD_METRICS_REQUIRED')
    metrics.to_csv(stage/'metrics.csv', index=False, float_format='%.17g')
    for name, result in portfolio_attribution(n, l, bars, sessions, picked, original_risk).items():
        old = rename_reused(pd.read_csv(act017_replay_dir/name, float_precision='round_trip',
                                       dtype={'D':str, 'start_D':str, 'end_D':str, 'entry_date':str, 'exit_date':str}))
        pd.concat([old, result], ignore_index=True).to_csv(stage/name, index=False, float_format='%.17g')
    cases, traces = hotspot_comparisons(picked, ledger, audit)
    cases.to_csv(stage/'hotspot_cases.csv', index=False, float_format='%.17g')
    traces.to_csv(stage/'hotspot_date_selection_trace.csv', index=False, float_format='%.17g')
    del bars
    parity = dict(status='PASS_REUSED_EXACT_VALUES', arms={old:dict(config_id=i, scenario=s) for old,(i,s) in REUSE.items()},
                  reused_artifact_sha256={name:c.old._sha_file(act017_replay_dir/name) for name in
                      ['daily_nav.parquet','portfolio_ledger.parquet','picked_signals.parquet']},
                  original_hybrid_picks='PASS_EXACT_RECOMPUTED_DECISION_INPUTS_ONLY')
    c.write_json(stage/'reused_arm_parity.json', parity)
    return c.finish_manifest(stage, output_dir, 'replay_manifest.json', dict(batch='ACT-018',
        schema='ACT018_940D_PRIOR_LANE_PERCENTILE_V1', mode='FULL', source=source,
        fits_this_stage=0, configs=configs, horizon=3, K=3, input_seals=seal, calendar=calendar_info,
        outputs_sha256={p.name:c.old._sha_file(p) for p in stage.iterdir() if p.is_file()},
        read_counts=read_counts, reused_arm_parity=parity, fees={'buy':base.BUY_FEE,'sell':base.SELL_FEE},
        sessions_by_year=n.D.str[:4].value_counts().sort_index().to_dict(),
        source_PIT='CANNOT_CONFIRM frozen QFQ; 2022 seeds issuer-held-out, not chronological 2022 OOS',
        semantics={'calibration':'same-lane hard eligible 2022 seed plus sealed chronological OOS rows strictly before Jan01',
                   'percentile':'(count_less + 0.5*count_equal)/N; exact ties; code then lane; gate before Top3',
                   'B1_B2':'unchanged raw RF annual Q80 inclusive; B3 no extra cutoff',
                   'engine':'one new STRICT/ALL/3 call; original risk, protection, slots, fees, cash and fills',
                   'storage':'no OHLC written; new selected-symbol marks read once in memory',
                   'hotspots':'same D/canonical id selection/execution comparisons; timing-off is not a rescued loss'},
        code_sha256={str(p):c.old._sha_file(p) for p in [Path(__file__), ROOT/'ops/pft_act018_b3_calibrate.py',
             ROOT/'ops/pft_act015_replay.py', ROOT/'ops/pft_act016_inputs.py', ROOT/'ops/pft_act017_diagnostics.py']}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['fit-dir','rank-dir','act015-replay-dir','act016-replay-dir','act017-replay-dir','data-root',
                 'act005-root','market-dir','starter-path','starter-manifest-path','b3-starter-path',
                 'b3-starter-manifest-path','output-dir']:
        parser.add_argument('--'+name, type=Path, required=True)
    try:
        result = replay(**vars(parser.parse_args(argv)))
    except Exception as exc:
        return c.cli_failure(exc)
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
