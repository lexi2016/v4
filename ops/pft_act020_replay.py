"""ACT020: sealed 940-day V2 timing / raw-CNY ADV20 replay; actual new FIT=0."""
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
    sys.path.insert(0,str(ROOT))
from ops import pft_act015_common as c, pft_act015_replay as base
from ops import pft_act016_replay as a16, pft_act019_b3_cap as a19
from ops.pft_act016_inputs import hard_mask
from ops.pft_act020_timing import timing_daily
pd,np=c.pd,c.np
SCENARIOS=('BASELINE_STRICT','V2_RF','V2_PERCENTILE','V2_RF_SL5')
TIERS=(('ALL',None),('ADV1E8',1e8),('ADV3E8',3e8),('ADV5E8',5e8))
CARD_SHA='f5ca36f58ec7e39c7d948fdd1c5b826be31d1f9e9205ef425cc1f581d4926a15'
MARKET_SHA='343c31cf59f97a39ee4a4649e8d91976c44516735e379a604f07d8f6f0d6f390'


def validate_audit(audit):
    if (audit.empty or not hard_mask(audit).all() or not audit.D.between('20230101',c.ASOF).all()
        or not audit.lane.isin(c.LANES).all() or audit.episode_id.duplicated().any()
        or audit.duplicated([*c.IDENTITY,'lane']).any()):
        raise ValueError('ACT018_AUDIT_ENVELOPE_DRIFT')
    if not np.isfinite(audit.percentile_score).all() or not audit.percentile_score.between(0,1).all():
        raise ValueError('ACT018_PERCENTILE_DRIFT')


def select_ready(audit, mechanism, threshold=None, adv=None, daily_k=None):
    """D eligibility and ADV before sort/dedup/TopK. No failed-fill backfill."""
    f=audit.copy()
    if mechanism == 'PERCENTILE':
        f=f.loc[f.pass_raw_q80.eq(True)].copy()
        score='percentile_score'
    elif mechanism == 'RF':
        score='rank_score'
    else:
        raise ValueError('UNKNOWN_MECHANISM')
    if adv is not None:
        if adv.duplicated(c.IDENTITY).any():
            raise ValueError('DUPLICATE_ADV_KEY')
        f=f.merge(adv[c.IDENTITY+['adv20_cny']],on=c.IDENTITY,how='left',validate='many_to_one')
    if threshold is not None:
        if adv is None:
            raise ValueError('ADV_REQUIRED')
        f=f.loc[np.isfinite(f.adv20_cny) & f.adv20_cny.ge(threshold)].copy()
    f=f.sort_values(['D',score,'canonical_security_id','lane'],ascending=[True,False,True,True],kind='mergesort')
    f=f.drop_duplicates(c.IDENTITY,keep='first')
    f['rank_position']=f.groupby('D').cumcount()+1
    k=3 if daily_k is None else f.D.map(daily_k).fillna(0)
    return f.loc[f.rank_position.le(k)].reset_index(drop=True)


def verify_selection_parity(audit, rank_dir, act018_replay_dir):
    rank=pd.read_parquet(rank_dir/'ranked_signals.parquet')
    pct=pd.read_parquet(act018_replay_dir/'picked_signals.parquet')
    expected={'RF':rank.loc[rank.pool.eq('ALL')], 'PERCENTILE':pct.loc[pct.config_id.eq(2)]}
    keys=['episode_id',*c.IDENTITY,'lane','rank_score','rank_position']
    for mechanism in expected:
        actual=select_ready(audit,mechanism)
        pd.testing.assert_frame_equal(actual.sort_values(['D','rank_position'])[keys].reset_index(drop=True),
            expected[mechanism].sort_values(['D','rank_position'])[keys].reset_index(drop=True),
            check_exact=True,check_dtype=False)
    return dict(status='PASS_EXACT',mechanisms=['RF','PERCENTILE'],scope='unfiltered original Top3 before V2/ADV')


def combined_protection(lot,row,day,scenario,regime):
    """Original protections retain priority; ACT016 LOW touch adds one queue reason."""
    original=base.protection(lot,row,day,scenario,regime)
    fixed=a16.card_protection(lot,row,day,scenario,regime,fixed_stop=.05)
    return [*original,*fixed]


def run_portfolio(picks,bars,sessions,risk,scenario,pool,horizon,asof=c.ASOF):
    n,l=base.portfolio(picks,bars,sessions,risk,'STRICT',pool,horizon,asof=asof,
        protection_policy=combined_protection if scenario == 'V2_RF_SL5' else None)
    n['scenario'],l['scenario']=scenario,scenario
    if scenario == 'V2_RF_SL5':
        l['fixed_stop_pct']=.05
        l['fixed_stop_threshold']=l.get('entry_open',pd.Series(np.nan,index=l.index))*.95
    return n,l


def natural_counts(fit_dir,fit,days):
    rows=[]
    for rel,sha in sorted(fit['outputs_sha256'].items()):
        if rel.startswith('predictions/'):
            c.verified_file(fit_dir/rel,sha)
            d=pd.read_parquet(fit_dir/rel,columns=['D'])
            if not d.D.between('20230101',c.ASOF).all():
                raise ValueError('PREDICTION_DATE_DRIFT')
            rows.append(d)
    if not rows:
        raise ValueError('NO_PREDICTION_SHARDS')
    dates=pd.concat(rows,ignore_index=True).D
    if len(dates) != 1034259 or not set(dates) <= set(days):
        raise ValueError('EXACT_1034259_NATURAL_ROWS_REQUIRED')
    return dates.value_counts().reindex(days,fill_value=0).sort_index()


def validate_adv(adv_dir,fit,hashes,audit,fit_dir,act018_replay_dir,market_dir):
    m=c.old._read_json(adv_dir/'adv_manifest.json')
    a19.same_source(m['source'],fit['source'])
    if (m.get('batch') != 'ACT-020' or m.get('schema') != 'ACT020_ADV20_CNY_V1'
        or m.get('mode') != 'FULL' or m.get('flags') != c.old.FLAGS):
        raise ValueError('ADV_MANIFEST_DRIFT')
    required={'fit_manifest_sha256':fit_dir/'fit_manifest.json',
        'act018_replay_manifest_sha256':act018_replay_dir/'replay_manifest.json',
        'market_manifest_sha256':market_dir/'market_manifest.json',
        'candidate_score_audit_sha256':act018_replay_dir/'candidate_score_audit.parquet',
        'pre_replay_seal_sha256':fit_dir/'pre_replay_seal.json'}
    for key,path in required.items():
        if m.get(key) != c.old._sha_file(path):
            raise ValueError('ADV_INPUT_SEAL_DRIFT:'+key)
    c.verified_file(adv_dir/'adv20.parquet',m['outputs_sha256']['adv20.parquet'])
    adv=pd.read_parquet(adv_dir/'adv20.parquet')
    if adv.duplicated(c.IDENTITY).any() or len(adv) != m['rows']:
        raise ValueError('ADV_KEY_DRIFT')
    pd.testing.assert_frame_equal(adv[c.IDENTITY].sort_values(c.IDENTITY).reset_index(drop=True),
        audit[c.IDENTITY].drop_duplicates().sort_values(c.IDENTITY).reset_index(drop=True),check_dtype=False)
    if (adv.adv20_cny.dropna().lt(0).any() or np.isinf(adv.adv20_cny.to_numpy(float)).any()):
        raise ValueError('ADV_VALUE_DRIFT')
    hashes['adv_manifest_sha256']=c.old._sha_file(adv_dir/'adv_manifest.json')
    hashes['adv20_sha256']=m['outputs_sha256']['adv20.parquet']
    return adv


_WORK=None

def _initialize_worker(payload):
    global _WORK
    _WORK=payload


def _execute(spec):
    bars,sessions,baseline_risk,v2risk,selected=_WORK
    start,cpu=time.perf_counter(),time.process_time()
    picks=selected[(spec['mechanism'],spec['pool'],spec['is_v2'])]
    n,l=run_portfolio(picks,bars,sessions,v2risk if spec['is_v2'] else baseline_risk,
        spec['scenario'],spec['pool'],spec['horizon'])
    n['config_id'],l['config_id']=spec['config_id'],spec['config_id']
    tel=dict(config_id=spec['config_id'],elapsed_seconds=time.perf_counter()-start,
        cpu_seconds=time.process_time()-cpu,peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(json.dumps(dict(stage='ACT020_PORTFOLIO',**tel)),flush=True)
    return n,l,tel


def baseline_parity(nav,ledger,act015_replay_dir):
    result={}
    for name,frame in [('daily_nav.parquet',nav),('portfolio_ledger.parquet',ledger)]:
        expected=pd.read_parquet(act015_replay_dir/name)
        expected=expected.loc[expected.scenario.eq('STRICT') & expected.pool.eq('ALL')]
        actual=frame.loc[frame.scenario.eq('BASELINE_STRICT') & frame.pool.eq('ALL')]
        columns=[n for n in expected if n not in ('scenario','config_id')]
        sort=['horizon','D']+(['canonical_security_id','lane','episode_id'] if name.startswith('portfolio') else [])
        pd.testing.assert_frame_equal(actual.sort_values(sort)[columns].reset_index(drop=True),
            expected.sort_values(sort)[columns].reset_index(drop=True),check_exact=True,check_dtype=False)
        result[name]=dict(status='PASS_EXACT',rows=len(actual),horizons=[3,5])
    return result


def replay(*, fit_dir,rank_dir,act015_replay_dir,act016_replay_dir,act017_replay_dir,
           act018_replay_dir,data_root,act005_root,market_dir,starter_path,starter_manifest_path,
           b3_starter_path,b3_starter_manifest_path,adv_dir,timing_card_path,output_dir,workers=10):
    if not 1 <= workers <= 12:
        raise ValueError('WORKERS_OUT_OF_BOUNDS')
    c.verified_file(timing_card_path,CARD_SHA)
    c.verified_file(market_dir/c.FACTOR_NAME,MARKET_SHA)
    fit,prior,sessions,days,calendar_info,hashes=a19.validate_chain(fit_dir=fit_dir,rank_dir=rank_dir,
        act015_replay_dir=act015_replay_dir,act016_replay_dir=act016_replay_dir,
        act017_replay_dir=act017_replay_dir,act018_replay_dir=act018_replay_dir,market_dir=market_dir,
        starter_path=starter_path,starter_manifest_path=starter_manifest_path,
        b3_starter_path=b3_starter_path,b3_starter_manifest_path=b3_starter_manifest_path)
    hashes.update(timing_card_sha256=CARD_SHA,market_csv_sha256=MARKET_SHA)
    audit=pd.read_parquet(act018_replay_dir/'candidate_score_audit.parquet')
    validate_audit(audit)
    selection_parity=verify_selection_parity(audit,rank_dir,act018_replay_dir)
    adv=validate_adv(adv_dir,fit,hashes,audit,fit_dir,act018_replay_dir,market_dir)
    counts=natural_counts(fit_dir,fit,days)
    market=pd.read_csv(market_dir/c.FACTOR_NAME,dtype={'D':str},float_precision='round_trip')
    timing,cutoffs=timing_daily(market,counts)
    baseline_risk=pd.read_csv(rank_dir/'causal_regimes.csv',dtype={'D':str},float_precision='round_trip').set_index('D').to_dict('index')
    v2risk=timing.set_index('D').to_dict('index')
    daily_k=timing.set_index('D').daily_K
    selected,frames={},{}
    for mechanism in ('RF','PERCENTILE'):
        for pool,threshold in TIERS:
            for is_v2 in ([False,True] if mechanism == 'RF' else [True]):
                key=(mechanism,pool,is_v2)
                f=select_ready(audit,mechanism,threshold,adv,daily_k if is_v2 else None)
                columns=['episode_id',*c.IDENTITY,'lane','model_year','held_outer','rank_score',
                    'prior_anchor_date','prior_anchor_low','rank_position','S_prob_gated','B_probability',
                    'pass_raw_q80','percentile_score','q80_threshold','adv20_cny']
                f=f[[name for name in columns if name in f]].copy()
                frames[key]=f
                selected[key]=a16.as_picks(f)
    specs=[]
    for scenario in SCENARIOS:
        for horizon in (3,5):
            for pool,threshold in TIERS:
                specs.append(dict(config_id=len(specs),scenario=scenario,horizon=horizon,pool=pool,
                    mechanism='PERCENTILE' if scenario == 'V2_PERCENTILE' else 'RF',
                    is_v2=scenario != 'BASELINE_STRICT',min_adv20_cny=threshold,
                    fixed_stop_pct=.05 if scenario == 'V2_RF_SL5' else None,engine_scenario='STRICT'))
    stage=c.new_stage(output_dir)
    picked=[]
    for spec in specs:
        f=frames[(spec['mechanism'],spec['pool'],spec['is_v2'])].copy()
        for name in ['config_id','scenario','horizon','pool']:
            f[name]=spec[name]
        picked.append(f)
    pd.concat(picked,ignore_index=True).to_parquet(stage/'picked_signals.parquet',index=False,compression='zstd')
    timing.to_csv(stage/'timing_daily.csv',index=False,float_format='%.17g')
    cutoffs.to_csv(stage/'annual_cutoffs.csv',index=False,float_format='%.17g')
    c.write_json(stage/'configs.json',specs)
    c.write_json(stage/'selection_parity.json',selection_parity)
    codepaths=[Path(__file__),ROOT/'ops/pft_act020_timing.py',ROOT/'ops/pft_act015_replay.py',ROOT/'ops/pft_act016_replay.py',ROOT/'ops/pft_act019_b3_cap.py']
    code_seals={str(p):c.old._sha_file(p) for p in codepaths}
    prereg=dict(batch='ACT-020',fits_this_stage=0,execution_ohlc_read=False,source=fit['source'],**hashes,
        code_sha256=code_seals,
        rules=dict(base='prior EOY expanding exact 1/3,2/3; slope Q20; liquidity Q25',
            crowd='all 1034259 unscreened OOS lane rows counted by D; inclusive CDF current+39; first9=.50',
            engine='STRICT V2 cap 1/.5/0, K3/2/0; prior-D entry cap; original exposure/cash and protection; no mid trims',
            stop='ARM4 adds ACT016 low-touch -5% actual-entry-open; original pending reason priority; original scheduled close precedence',
            eligibility='sealed hard candidate RF (no Q80) / sealed pass_raw_q80 percentile; ADV before sort/dedup; no added price/BSE gate',
            winner='descriptive ex post per H, unfiltered V2 only: Calmar desc, net return desc, scenario asc; no tuning'),
        configs=specs,outputs_sha256={p.name:c.old._sha_file(p) for p in stage.iterdir() if p.is_file()})
    c.write_json(stage/'pre_execution_seal.json',prereg)
    codes=set().union(*(set(f.canonical_security_id) for f in frames.values()))
    bars,source,read_counts=base.read_bars(data_root=data_root,act005_root=act005_root,fit_manifest=fit,codes=codes)
    payload=(bars,sessions,baseline_risk,v2risk,selected)
    if workers == 1:
        _initialize_worker(payload)
        results=[_execute(spec) for spec in specs]
        global _WORK
        _WORK=None
    else:
        with ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),initializer=_initialize_worker,initargs=(payload,)) as executor:
            results=list(executor.map(_execute,specs,chunksize=1))
    del payload,bars
    nav=pd.concat([r[0] for r in results],ignore_index=True)
    ledger=pd.concat([r[1] for r in results],ignore_index=True)
    for cfg,group in nav.groupby('config_id'):
        if group.D.tolist() != days:
            raise ValueError('EXACT_940_SESSION_DRIFT:'+str(cfg))
    parity=baseline_parity(nav,ledger,act015_replay_dir)
    metrics=base.metrics(nav,ledger)
    lookup={(s['scenario'],s['pool'],s['horizon']):s['config_id'] for s in specs}
    metrics['config_id']=[lookup[(r.scenario,r.pool,r.horizon)] for r in metrics.itertuples()]
    if len(metrics) != 160:
        raise ValueError('EXACT_160_METRICS_REQUIRED')
    eligible=metrics.loc[metrics.period.eq('FULL') & metrics.pool.eq('ALL') & metrics.scenario.ne('BASELINE_STRICT')]
    winners=eligible.sort_values(['horizon','Calmar','net_return_pct','scenario'],ascending=[True,False,False,True],kind='mergesort',na_position='last').groupby('horizon').head(1)
    nav.to_parquet(stage/'daily_nav.parquet',index=False,compression='zstd')
    ledger.to_parquet(stage/'portfolio_ledger.parquet',index=False,compression='zstd')
    metrics.to_csv(stage/'metrics.csv',index=False,float_format='%.17g')
    winners.to_csv(stage/'descriptive_winners.csv',index=False,float_format='%.17g')
    c.write_json(stage/'baseline_parity.json',parity)
    c.write_json(stage/'worker_telemetry.json',[r[2] for r in results])
    for path,sha in code_seals.items():
        c.verified_file(Path(path),sha)
    return c.finish_manifest(stage,output_dir,'replay_manifest.json',dict(batch='ACT-020',
        schema='ACT020_940D_V2_ADV20_REPLAY_V1',mode='FULL',fits_this_stage=0,source=source,
        input_seals=prereg,configs=specs,workers=workers,calendar=calendar_info,read_counts=read_counts,
        baseline_parity=parity,selection_parity=selection_parity,natural_signal_rows=int(counts.sum()),
        sessions_by_year=nav.loc[nav.config_id.eq(0)].D.str[:4].value_counts().sort_index().to_dict(),
        fees={'buy':base.BUY_FEE,'sell':base.SELL_FEE},source_PIT=prior['source_PIT'],
        execution_counts={'portfolio_calls':len(specs),'new_fit_calls':0,'selected_code_union':len(codes)},
        execution_marks_storage='transient worker memory only; no raw OHLC snapshot',
        outputs_sha256={p.name:c.old._sha_file(p) for p in stage.iterdir() if p.is_file()},
        code_sha256=code_seals))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['fit-dir','rank-dir','act015-replay-dir','act016-replay-dir','act017-replay-dir',
        'act018-replay-dir','data-root','act005-root','market-dir','starter-path','starter-manifest-path',
        'b3-starter-path','b3-starter-manifest-path','adv-dir','timing-card-path','output-dir']:
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--workers',type=int,default=10)
    try:
        result=replay(**vars(p.parse_args(argv)))
    except Exception as exc:
        return c.cli_failure(exc)
    print(json.dumps(result,sort_keys=True));return 0


if __name__ == '__main__':
    raise SystemExit(main())
