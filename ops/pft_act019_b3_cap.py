"""ACT019: one B3 seat per signal date on sealed ACT018 raw HYBRID order."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops import pft_act015_common as c, pft_act015_replay as base
from ops.pft_act016_inputs import hard_mask
from ops.pft_act017_ablation import as_picks
from ops.pft_act017_diagnostics import portfolio_attribution
from ops import pft_act018_percentile as a18
pd, np = c.pd, c.np
CONFIGS = [*a18.CONFIGS, (3, 'B3_CAP1_HYBRID')]
SCHEMAS = {'ACT-016': 'ACT016_EXACT_CARD_REPLAY_V1',
           'ACT-017': 'ACT017_940D_STRICT_H3_ABLATION_V1',
           'ACT-018': 'ACT018_940D_PRIOR_LANE_PERCENTILE_V1'}


def sealed_manifest(directory, name, batch):
    m = c.old._read_json(directory/name)
    if (m.get('batch') != batch or m.get('flags') != c.old.FLAGS
        or (batch in SCHEMAS and (m.get('schema') != SCHEMAS[batch]
            or m.get('mode') != 'FULL' or m.get('fits_this_stage') != 0))):
        raise ValueError('SEALED_MANIFEST_DRIFT:'+batch)
    for rel, sha in m['outputs_sha256'].items():
        c.verified_file(directory/rel, sha)
    return m


def same_source(a, b):
    if (a['identity'] != b['identity'] or
        a['backtest']['panel_sha256'] != b['backtest']['panel_sha256']):
        raise ValueError('SEALED_SOURCE_DRIFT')


def validate_chain(*, fit_dir, rank_dir, act015_replay_dir, act016_replay_dir,
                   act017_replay_dir, act018_replay_dir, market_dir, starter_path,
                   starter_manifest_path, b3_starter_path, b3_starter_manifest_path):
    """Hash the sealed chain without reading/reprojecting all fitted predictions."""
    dirs = [(fit_dir, 'fit_manifest.json', 'ACT-015'),
            (rank_dir, 'rank_manifest.json', 'ACT-015'),
            (act015_replay_dir, 'replay_manifest.json', 'ACT-015'),
            (act016_replay_dir, 'replay_manifest.json', 'ACT-016'),
            (act017_replay_dir, 'replay_manifest.json', 'ACT-017'),
            (act018_replay_dir, 'replay_manifest.json', 'ACT-018')]
    manifests = [sealed_manifest(*spec) for spec in dirs]
    fit, rank, replay15, replay16, replay17, replay18 = manifests
    for m in manifests[1:]:
        same_source(m['source'], fit['source'])
    paths = dict(fit_manifest_sha256=fit_dir/'fit_manifest.json',
        rank_manifest_sha256=rank_dir/'rank_manifest.json',
        act015_replay_manifest_sha256=act015_replay_dir/'replay_manifest.json',
        act016_replay_manifest_sha256=act016_replay_dir/'replay_manifest.json',
        act017_replay_manifest_sha256=act017_replay_dir/'replay_manifest.json',
        market_manifest_sha256=market_dir/'market_manifest.json',
        starter_sha256=starter_path, starter_manifest_sha256=starter_manifest_path,
        b3_starter_sha256=b3_starter_path, b3_starter_manifest_sha256=b3_starter_manifest_path)
    hashes = {k:c.old._sha_file(p) for k,p in paths.items()}
    for key, sha in hashes.items():
        if replay18['input_seals'].get(key) != sha:
            raise ValueError('ACT018_INPUT_SEAL_DRIFT:'+key)
    pre = c.old._read_json(act018_replay_dir/'pre_execution_seal.json')
    if pre != replay18['input_seals']:
        raise ValueError('ACT018_PRE_EXECUTION_SEAL_DRIFT')
    for rel, sha in pre['outputs_sha256'].items():
        c.verified_file(act018_replay_dir/rel, sha)
    for m in [replay16, replay17]:
        for key, sha in m['input_seals'].items():
            if key in hashes and sha != hashes[key]:
                raise ValueError('PRIOR_INPUT_SEAL_DRIFT:'+key)
    for m in [rank, replay15]:
        for key in ['fit_manifest_sha256','rank_manifest_sha256','market_manifest_sha256']:
            if key in m and m[key] != hashes[key]:
                raise ValueError('ACT015_INPUT_SEAL_DRIFT:'+key)
        if m['pre_replay_seal_sha256'] != c.old._sha_file(fit_dir/'pre_replay_seal.json'):
            raise ValueError('ACT015_PRE_REPLAY_SEAL_DRIFT')
    for path, sha in replay18['code_sha256'].items():
        c.verified_file(ROOT/'ops'/Path(path).name, sha)
    market, sessions, mm, calendar_info = c.calendar(market_dir, fit['source'])
    c.verified_file(c.old.CROSSWALK_FILE, mm['crosswalk_sha256'])
    if sessions != fit['sessions'] or rank['sessions'] != fit['sessions']:
        raise ValueError('CALENDAR_DRIFT')
    days = [d for d in sessions if '20230101' <= d <= c.ASOF]
    if len(days) != 940:
        raise ValueError('EXACT_940_SESSIONS_REQUIRED')
    hashes['act018_replay_manifest_sha256'] = c.old._sha_file(act018_replay_dir/'replay_manifest.json')
    return fit, replay18, sessions, days, calendar_info, hashes


def cap_picks(audit, thresholds):
    """Dedup original raw order first, then skip B3 after its first seat; never reroute."""
    f = audit.copy()
    if (f.empty or not f.D.between('20230101', c.ASOF).all() or
        not hard_mask(f).all() or not f.lane.isin(c.LANES).all() or
        f.episode_id.duplicated().any() or f.duplicated([*c.IDENTITY, 'lane']).any()):
        raise ValueError('ACT018_HARD_ENVELOPE_DRIFT')
    for name, values in [('act015_rank_score', f.rank_score.to_numpy()),
                         ('hybrid_score', a18.raw_score(f)), ('raw_score', a18.raw_score(f))]:
        np.testing.assert_array_equal(f[name].to_numpy(), values, err_msg=name+'_DRIFT')
    t = thresholds.set_index('year')
    q80 = np.array([t.loc[int(d[:4]), lane+'_q80'] if lane in ('B1','B2') else np.nan
                     for d,lane in zip(f.D,f.lane)])
    np.testing.assert_array_equal(f.q80_threshold.to_numpy(), q80, err_msg='Q80_THRESHOLD_DRIFT')
    passed = f.lane.eq('B3') | f.rank_score.ge(q80)
    np.testing.assert_array_equal(f.pass_raw_q80.to_numpy(), passed.to_numpy(), err_msg='Q80_GATE_DRIFT')
    ready = f.loc[passed].sort_values(['D','hybrid_score','canonical_security_id','lane'],
                                     ascending=[True,False,True,True], kind='mergesort')
    order = ready.drop_duplicates(c.IDENTITY, keep='first').copy()
    order['original_order_rank'] = order.groupby('D').cumcount()+1
    order['B3_order'] = order.lane.eq('B3').groupby(order.D).cumsum()
    allowed = order.loc[order.lane.ne('B3') | order.B3_order.le(1)].copy()
    allowed['rank_position'] = allowed.groupby('D').cumcount()+1
    new = allowed.loc[allowed.rank_position.le(3)].drop(columns='B3_order').copy()
    original = order.loc[order.original_order_rank.le(3)].copy()
    original['rank_position'] = original.original_order_rank
    diagnostic = order[[*c.IDENTITY,'episode_id','lane','hybrid_score','rank_score',
                        'q80_threshold','original_order_rank','B3_order']].copy()
    diagnostic['quota_skipped'] = diagnostic.lane.eq('B3') & diagnostic.B3_order.gt(1)
    selected = new.set_index('episode_id').rank_position
    diagnostic['capped_rank_position'] = diagnostic.episode_id.map(selected)
    diagnostic['selected'] = diagnostic.capped_rank_position.notna()
    return new.reset_index(drop=True), original.reset_index(drop=True), diagnostic.reset_index(drop=True)


def verify_original(original, old_picked):
    keys = ['episode_id',*c.IDENTITY,'lane','rank_score','rank_position','hybrid_score','q80_threshold']
    expected = old_picked.loc[old_picked.config_id.eq(1)]
    pd.testing.assert_frame_equal(original.sort_values(['D','rank_position'])[keys].reset_index(drop=True),
        expected.sort_values(['D','rank_position'])[keys].reset_index(drop=True), check_exact=True)


def verify_reused_sessions(nav, days):
    if set(nav.config_id) != {0,1,2}:
        raise ValueError('REUSED_ARMS_DRIFT')
    for i, scenario in a18.CONFIGS:
        f = nav.loc[nav.config_id.eq(i)]
        if f.D.tolist() != days or not f.scenario.eq(scenario).all():
            raise ValueError('REUSED_940_SESSION_DRIFT')


def hotspot_comparisons(picked, ledger, audit, risk):
    """Trace the six fixed cases explicitly across all four sealed configurations."""
    rows, traces = [], []
    strict = risk.set_index('D').strict_state
    for day, code in a18.CASES:
        hard = audit.loc[audit.D.eq(day) & audit.canonical_security_id.eq(code)]
        for config_id, scenario in CONFIGS:
            chosen = picked.loc[picked.config_id.eq(config_id) & picked.D.eq(day)]
            target = chosen.loc[chosen.canonical_security_id.eq(code)]
            trades = ledger.loc[ledger.config_id.eq(config_id) & ledger.D.eq(day)]
            lots = trades.loc[trades.canonical_security_id.eq(code)]
            filled = lots.loc[lots.status.isin(['OPEN','CLOSED']) & lots.allocation.gt(0)]
            closed = filled.loc[filled.status.eq('CLOSED')]
            item = target.iloc[0].to_dict() if len(target) else (
                hard.sort_values(['hybrid_score','lane'], ascending=[False,True]).iloc[0].to_dict()
                if len(hard) else {})
            state = strict.get(day, 'UNKNOWN')
            rows.append(dict(case_D=day, canonical_security_id=code, config_id=config_id, scenario=scenario,
                prediction_present=bool(len(hard)), selected=bool(len(target)), filled=bool(len(filled)), closed=bool(len(closed)),
                lane=item.get('lane'), selected_rank=item.get('rank_position') if len(target) else None,
                original_order_rank=item.get('original_order_rank'), ready_lane_rank=item.get('ready_lane_rank'),
                rank_score=item.get('rank_score'), raw_score=item.get('raw_score', item.get('hybrid_score')),
                percentile_score=item.get('percentile_score'), q80_threshold=item.get('q80_threshold'),
                entry_status='|'.join(lots.entry_status.astype(str)) if len(lots) else 'NOT_SELECTED',
                entry_date='|'.join(lots.entry_date.fillna('').astype(str)) if len(lots) else '',
                exit_date='|'.join(lots.exit_date.fillna('').astype(str)) if len(lots) else '',
                exit_reason='|'.join(lots.exit_reason.fillna('').astype(str)) if len(lots) else '',
                buy_fee=float(lots.buy_fee.sum()), sell_fee=float(lots.sell_fee.sum()),
                realized_pnl=float(closed.realized_pnl.sum()) if len(closed) else np.nan,
                original_signal_D_strict_state=state,
                interpretation='original STRICT RISK_OFF; no saved-loss claim' if state == 'RISK_OFF'
                    else 'same-date selection and actual fill comparison; no causal rescue claim'))
            for signal in chosen.to_dict('records'):
                lot = trades.loc[trades.episode_id.eq(signal['episode_id'])]
                execution = lot.iloc[0].to_dict() if len(lot) else {}
                traces.append(dict(case_D=day, case_security_id=code, **{k:signal.get(k) for k in
                    ['config_id','scenario','episode_id','canonical_security_id','lane','rank_position',
                     'original_order_rank','rank_score','raw_score','percentile_score']},
                    entry_status=execution.get('entry_status','NO_LEDGER_ROW'),
                    status=execution.get('status','NO_LEDGER_ROW'),
                    **{k:execution.get(k) for k in ['entry_date','allocation','buy_fee','sell_fee','realized_pnl']}))
    return pd.DataFrame(rows), pd.DataFrame(traces)


def selection_fill_counts(picked, ledger):
    """Selections use signal D year; positive-allocation actual fills use entry year."""
    counts = []
    for i,scenario in CONFIGS:
        for period in ['2023','2024','2025','2026','FULL']:
            sel = picked.loc[picked.config_id.eq(i)]
            filled = ledger.loc[ledger.config_id.eq(i) & ledger.status.isin(['OPEN','CLOSED'])
                                & ledger.allocation.gt(0)]
            if period != 'FULL':
                sel = sel.loc[sel.D.str[:4].eq(period)]
                filled = filled.loc[filled.entry_date.str[:4].eq(period)]
            counts.append(dict(config_id=i,scenario=scenario,period=period,selected=len(sel),
                B3_selected=int(sel.lane.eq('B3').sum()),filled=len(filled),
                B3_actual_filled=int(filled.lane.eq('B3').sum())))
    return pd.DataFrame(counts)


def replay(*, fit_dir, rank_dir, act015_replay_dir, act016_replay_dir, act017_replay_dir,
           act018_replay_dir, data_root, act005_root, market_dir, starter_path,
           starter_manifest_path, b3_starter_path, b3_starter_manifest_path, output_dir):
    fit, prior, sessions, days, calendar_info, hashes = validate_chain(
        fit_dir=fit_dir, rank_dir=rank_dir, act015_replay_dir=act015_replay_dir,
        act016_replay_dir=act016_replay_dir, act017_replay_dir=act017_replay_dir,
        act018_replay_dir=act018_replay_dir, market_dir=market_dir, starter_path=starter_path,
        starter_manifest_path=starter_manifest_path, b3_starter_path=b3_starter_path,
        b3_starter_manifest_path=b3_starter_manifest_path)
    audit = pd.read_parquet(act018_replay_dir/'candidate_score_audit.parquet')
    thresholds = pd.read_csv(act018_replay_dir/'annual_thresholds.csv', float_precision='round_trip')
    new, original, diagnostic = cap_picks(audit, thresholds)
    old_picked = pd.read_parquet(act018_replay_dir/'picked_signals.parquet')
    verify_original(original, old_picked)
    new['config_id'], new['scenario'], new['horizon'] = 3, 'B3_CAP1_HYBRID', 3
    picked = pd.concat([old_picked,new], ignore_index=True)
    risk = pd.read_csv(rank_dir/'causal_regimes.csv', dtype={'D':str}, float_precision='round_trip')
    old_nav = pd.read_parquet(act018_replay_dir/'daily_nav.parquet')
    old_ledger = pd.read_parquet(act018_replay_dir/'portfolio_ledger.parquet')
    verify_reused_sessions(old_nav, days)
    stage = c.new_stage(output_dir)
    picked.to_parquet(stage/'picked_signals.parquet', index=False, compression='zstd')
    diagnostic.to_parquet(stage/'cap_order_audit.parquet', index=False, compression='zstd')
    configs = [*prior['configs'], dict(config_id=3, scenario='B3_CAP1_HYBRID', engine_scenario='STRICT',
        pool='ALL',horizon=3,K=3,B3_daily_selection_cap=1,reused_from=None)]
    c.write_json(stage/'configs.json',configs)
    seal = dict(batch='ACT-019', fits_this_stage=0, execution_ohlc_read=False,
        source=fit['source'], **hashes, reused_outputs_sha256=prior['outputs_sha256'],
        outputs_sha256={p.name:c.old._sha_file(p) for p in stage.iterdir() if p.is_file()})
    c.write_json(stage/'pre_execution_seal.json',seal)
    bars, source, read_counts = base.read_bars(data_root=data_root,act005_root=act005_root,
        fit_manifest=fit,codes=set(new.canonical_security_id))
    n,l = base.portfolio(as_picks(new),bars,sessions,risk.set_index('D').to_dict('index'),'STRICT','ALL',3)
    n['config_id'],l['config_id'],n['scenario'],l['scenario'] = 3,3,'B3_CAP1_HYBRID','B3_CAP1_HYBRID'
    if n.D.tolist() != days:
        raise ValueError('NEW_940_SESSION_DRIFT')
    nav,ledger = pd.concat([old_nav,n],ignore_index=True),pd.concat([old_ledger,l],ignore_index=True)
    nav.to_parquet(stage/'daily_nav.parquet',index=False,compression='zstd')
    ledger.to_parquet(stage/'portfolio_ledger.parquet',index=False,compression='zstd')
    new_metrics = base.metrics(n,l); new_metrics['config_id'] = 3
    old_metrics = pd.read_csv(act018_replay_dir/'metrics.csv', float_precision='round_trip')
    metrics = pd.concat([old_metrics,new_metrics],ignore_index=True)
    if len(metrics) != 20 or not metrics.groupby('config_id').size().eq(5).all():
        raise ValueError('FOUR_ARMS_FIVE_PERIOD_METRICS_REQUIRED')
    metrics.to_csv(stage/'metrics.csv',index=False,float_format='%.17g')
    for name,result in portfolio_attribution(n,l,bars,sessions,picked,risk).items():
        old = pd.read_csv(act018_replay_dir/name,float_precision='round_trip',
            dtype={'D':str,'start_D':str,'end_D':str,'entry_date':str,'exit_date':str})
        pd.concat([old,result],ignore_index=True).to_csv(stage/name,index=False,float_format='%.17g')
    cases,traces = hotspot_comparisons(picked,ledger,audit,risk)
    cases.to_csv(stage/'hotspot_cases.csv',index=False,float_format='%.17g')
    traces.to_csv(stage/'hotspot_date_selection_trace.csv',index=False,float_format='%.17g')
    del bars
    selection_fill_counts(picked,ledger).to_csv(stage/'selection_fill_counts.csv',index=False)
    parity = dict(status='PASS_REUSED_EXACT_VALUES',arms=a18.CONFIGS,
        original_hybrid='PASS_EXACT_RAW_ORDER_DEDUP_TOP3',
        reused_artifact_sha256={name:prior['outputs_sha256'][name] for name in
            ['daily_nav.parquet','portfolio_ledger.parquet','picked_signals.parquet','metrics.csv']})
    c.write_json(stage/'reused_arm_parity.json',parity)
    return c.finish_manifest(stage,output_dir,'replay_manifest.json',dict(batch='ACT-019',
        schema='ACT019_940D_B3_CAP1_HYBRID_V1',mode='FULL',fits_this_stage=0,source=source,
        configs=configs,horizon=3,K=3,input_seals=seal,calendar=calendar_info,read_counts=read_counts,
        reused_arm_parity=parity,fees={'buy':base.BUY_FEE,'sell':base.SELL_FEE},
        sessions_by_year=n.D.str[:4].value_counts().sort_index().to_dict(),source_PIT=prior['source_PIT'],
        semantics={'selection':'raw hybrid desc, code asc, lane asc; same-D canonical dedup BEFORE quota; skip B3 after first; continue ready B1/B2 up to 3',
                   'gates':'unchanged hard eligibility, B1/B2 raw annual inclusive Q80; no B3 cutoff or refit',
                   'engine':'one new original STRICT ALL H3 call; default risk budget, fills, stop, no failed-entry backfill',
                   'storage':'sealed ACT018 candidate audit reused; no prediction reprojection; new selected-symbol OHLC once in memory',
                   'fills':'OPEN or CLOSED with positive allocation, grouped by entry_date year; selections by signal D year'},
        outputs_sha256={p.name:c.old._sha_file(p) for p in stage.iterdir() if p.is_file()},
        code_sha256={str(p):c.old._sha_file(p) for p in [Path(__file__),ROOT/'ops/pft_act015_replay.py',
            ROOT/'ops/pft_act016_inputs.py',ROOT/'ops/pft_act017_diagnostics.py',ROOT/'ops/pft_act018_percentile.py']}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['fit-dir','rank-dir','act015-replay-dir','act016-replay-dir','act017-replay-dir',
                 'act018-replay-dir','data-root','act005-root','market-dir','starter-path',
                 'starter-manifest-path','b3-starter-path','b3-starter-manifest-path','output-dir']:
        parser.add_argument('--'+name,type=Path,required=True)
    try:
        result = replay(**vars(parser.parse_args(argv)))
    except Exception as exc:
        return c.cli_failure(exc)
    print(json.dumps(result,sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
