"""Post-lock ACT-008 weak agreement and independent scheduled outcomes."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from datetime import date, timedelta
import json
import math
from pathlib import Path
import sys

APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:sys.path.insert(0,str(APP_ROOT))
from ops import pft_s_full_ashare as old
from ops import pft_s_full_ashare_fit as oldfit
from ops.pft_act008_b import BATCH,FLAGS,write_json,_write_rows,verify_source
from ops.pft_act008_b_fit import check_file,read_prepared,verify_lock
from ops.pft_act008_b_features import LANES


def scheduled_calendar():
    from contracts.trading_calendar import CALENDAR_PATH,load_market_calendar,resolve_market_states,TradingDayState
    calendar=load_market_calendar()
    cursor=date(calendar.year,1,1);days=[]
    while cursor.year==calendar.year:
        day=cursor.strftime('%Y%m%d')
        if resolve_market_states(calendar,day)['a_share'] in {TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}: days.append(day)
        cursor+=timedelta(days=1)
    return days,{'path':str(CALENDAR_PATH),'sha256':old._sha_file(CALENDAR_PATH),'year':calendar.year,'session_count':len(days)}


def outcome(case,bars,sessions,horizon,asof=old.ASOF_DATE):
    """D+h counts exchange sessions; never seek a later stock bar/fill."""
    d=case['D']
    if d not in sessions:raise oldfit.FitError('JUDGMENT_D_NOT_SCHEDULED_SESSION:'+d)
    i=sessions.index(d)
    base={**case,'horizon':horizon,'entry_date':sessions[i+1] if i+1<len(sessions) else '',
          'terminal_date':sessions[i+horizon] if i+horizon<len(sessions) else '',
          'return_pct':None,'running_close_drawdown_pct':None}
    if i+horizon>=len(sessions) or sessions[i+horizon]>asof:
        return {**base,'status':'RIGHT_CENSORED'}
    dates=sessions[i+1:i+horizon+1]
    if any(day not in bars for day in dates):return {**base,'status':'MISSING_SCHEDULED_BAR'}
    path=[bars[day] for day in dates]
    def num(row,name):
        try:return float(row[name])
        except (TypeError,ValueError,KeyError):return math.nan
    if any((math.isfinite(num(row,'vol')) and num(row,'vol')<=0) or num(row,'tradeable_basic')==0 for row in path):
        return {**base,'status':'HALTED_OR_UNTRADEABLE'}
    entry=num(path[0],'open');closes=[num(row,'close') for row in path]
    if not math.isfinite(entry) or entry<=0 or any(not math.isfinite(c) or c<=0 for c in closes) or any(not math.isfinite(num(row,'vol')) for row in path):
        return {**base,'status':'MISSING_PRICE_OR_VOLUME'}
    peak=entry;dd=0.
    for close in closes:
        peak=max(peak,close);dd=min(dd,(close/peak-1)*100)
    return {**base,'status':'VALID','entry_open':entry,'terminal_close':closes[-1],
            'return_pct':(closes[-1]/entry-1)*100,'running_close_drawdown_pct':dd}


def _distribution(values):
    import numpy as np
    if not values:return {'N':0,'mean':None,'median':None,'p10':None,'p25':None,'p75':None,'p90':None}
    return {'N':len(values),'mean':float(np.mean(values)),'median':float(np.median(values)),
            **{f'p{q}':float(np.percentile(values,q)) for q in (10,25,75,90)}}


def outcome_summary(rows):
    valid=[r for r in rows if r['status']=='VALID']
    returns=[r['return_pct'] for r in valid]
    return {'selected_N':len(rows),'status_counts':dict(Counter(r['status'] for r in rows)),
            'returns_pct':_distribution(returns),
            'win_rate':sum(v>0 for v in returns)/len(returns) if returns else None,
            'running_close_drawdown_pct':_distribution([r['running_close_drawdown_pct'] for r in valid])}


def weak_metrics(rows):
    result=oldfit._metrics([r['truth'] for r in rows],[r['probability'] for r in rows],[r['decision'] for r in rows])
    orig_fp=[r for r in rows if r['original']==1 and r['truth']==0]
    orig_tp=[r for r in rows if r['original']==1 and r['truth']==1]
    result['original_FP_filtering']={'original_FP':len(orig_fp),'filtered_FP':sum(r['decision']==0 for r in orig_fp),
                                    'retained_FP':sum(r['decision']==1 for r in orig_fp),
                                    'filter_rate':sum(r['decision']==0 for r in orig_fp)/len(orig_fp) if orig_fp else None,
                                    'original_TP':len(orig_tp),'collateral_TP_removed':sum(r['decision']==0 for r in orig_tp)}
    return result


def _read_outcome_bars(data_root,manifest,identities,act005_root):
    from ops import pft_s_first_baseline as baseline
    from ops import research_panel_logical as reader
    frozen=old._validate_inputs(act005_root)
    needed={r['canonical_security_id'] for r in identities}
    codes={c:[] for c in needed}
    for raw,canonical in frozen['raw_to_canonical'].items():
        if canonical in needed:codes[canonical].append(raw)
    if any(not values for values in codes.values()):raise oldfit.FitError('OUTCOME_ALIAS_MAPPING_MISSING')
    result={};rows_read=0
    with baseline.bind_current_panels(data_root) as (panel_path,source,recheck):
        verify_source(source,frozen)
        if source['identity']!=manifest['source']['identity'] or source['backtest']['panel_sha256']!=manifest['source']['backtest']['panel_sha256']:
            raise oldfit.FitError('POST_LOCK_OUTCOME_SOURCE_DRIFT')
        schema=reader.parquet.read_schema(panel_path)
        actual=old._schema_names(schema)
        names=('ts_code','trade_date','open','high','low','close','tradeable_basic')
        mapping={n:actual[n] for n in names}
        mapping['vol']=actual.get('vol',actual.get('volume'))
        if mapping['vol'] is None:raise oldfit.FitError('OUTCOME_VOLUME_COLUMN_MISSING')
        first=min(r['D'] for r in identities)
        for code_batch in old._code_cohorts(codes,384):
            filters=[[(mapping['ts_code'],'in',code_batch),(mapping['trade_date'],'>',old._date_value(schema,mapping['trade_date'],first)),
                      (mapping['trade_date'],'<=',old._date_value(schema,mapping['trade_date'],old.ASOF_DATE))]]
            table=reader.parquet.read_table(panel_path,columns=list(mapping.values()),filters=filters,use_threads=True)
            grouped=old._normalize_panel_rows(table,mapping,frozen['raw_to_canonical']);rows_read+=table.num_rows
            for canonical,by_code in grouped.items():
                result[canonical]={r['trade_date']:r for r in old._deduplicate_alias_history(by_code,frozen['crosswalk_aliases'])}
        recheck()
    return result,{'rows_read':rows_read,'canonical_securities':len(needed),'range_exclusive_inclusive':[first,old.ASOF_DATE],
                   'source_generation':source['identity']['generation_id'],'projected_columns':mapping}


def score(*,prepared_dir:Path,fit_dir:Path,data_root:Path,act005_root:Path,output_dir:Path):
    prepared_dir,fit_dir,data_root,act005_root=(p.expanduser().resolve(strict=True) for p in (prepared_dir,fit_dir,data_root,act005_root))
    output_dir=output_dir.expanduser().absolute();stage=output_dir.with_name(output_dir.name+'.partial')
    if output_dir.exists() or stage.exists() or output_dir.is_symlink() or stage.is_symlink():raise oldfit.FitError('SCORE_OUTPUT_EXISTS')
    if output_dir.parent.resolve(strict=True)!=prepared_dir.parent:raise oldfit.FitError('SCORE_OUTPUT_MUST_BE_PREPARED_SIBLING')
    lock=verify_lock(prepared_dir,fit_dir) # All model/prediction seals BEFORE truth or future bars.
    manifest=read_prepared(prepared_dir)
    predictions=oldfit._read_csv(fit_dir/'predictions.csv')
    truth={};identities=[];original_rows=[]
    for lane in LANES:
        name=f'{lane}_oos_labels.csv';check_file(prepared_dir,name,manifest['outputs_sha256'].get(name))
        rows=oldfit._read_csv(prepared_dir/name)
        for r in rows:
            key=(lane,r['episode_id'])
            if key in truth or r['label'] not in {'0','1'} or r['original'] not in {'0','1'}:
                raise oldfit.FitError('OOS_TRUTH_SCHEMA_OR_DUPLICATE')
            identity={n:r[n] for n in ('episode_id','canonical_security_id','D','lane','split')}
            identities.append(identity);truth[key]=r
            original_rows.append({**identity,'exam':'OOS','arm':'ORIGINAL_FORMULA','estimator':'F03' if lane=='B2' else ('F02' if lane=='B1' else 'F04'),
                                  'probability':float(r['original']),'decision':int(r['original']),
                                  'truth':int(r['label']),'original':int(r['original']),'stratum':r['stratum'],'reason':r['reason']})
    oos=[];kb=[];seen=set()
    kb_diag_name='kb_diagnostics.csv';check_file(prepared_dir,kb_diag_name,manifest['outputs_sha256'].get(kb_diag_name))
    kb_ids=oldfit._read_csv(prepared_dir/'kb_identity.csv');kb_diags=oldfit._read_csv(prepared_dir/kb_diag_name)
    kb_lookup={r['case_id']:(r,d) for r,d in zip(kb_ids,kb_diags)}
    for p in predictions:
        lane=p['lane'];prob=float(p['probability']);decision=int(p['decision'])
        if lane not in LANES or not math.isfinite(prob) or not 0<=prob<=1 or decision!=int(prob>=.5):
            raise oldfit.FitError('LOCKED_PREDICTION_INVALID')
        if p['arm'] not in {'BASELINE_B','FULL_B'} or p['estimator'] not in oldfit.MODEL_CONFIGS:
            raise oldfit.FitError('LOCKED_MODEL_KEY_INVALID')
        if p['exam']=='OOS':
            r=truth.get((lane,p['episode_id']))
            if r is None or any(r[n]!=p[n] for n in ('canonical_security_id','D','split')):
                raise oldfit.FitError('LOCKED_PREDICTION_TRUTH_IDENTITY_MISMATCH')
            key=(lane,p['arm'],p['estimator'],p['episode_id'])
            if key in seen:raise oldfit.FitError('DUPLICATE_LOCKED_PREDICTION')
            seen.add(key)
            oos.append({**p,'probability':prob,'decision':decision,'truth':int(r['label']),'original':int(r['original']),
                        'stratum':r['stratum'],'reason':r['reason'],'weak_error':int(decision!=int(r['label']))})
        elif p['exam']=='EXPOSED_KB25':
            identity,d=kb_lookup[p['case_id']]
            if any(identity[n]!=p[n] for n in ('canonical_security_id','D')):raise oldfit.FitError('KB_EXACT_IDENTITY_MISMATCH')
            kb.append({**p,'probability':prob,'decision':decision,'human_B_gold':'UNKNOWN',
                       'operational_weak_label':d[f'{lane}_label'],'operational_reason':d[f'{lane}_reason'],
                       'original':d[f'{lane}_original'],'exposure':'EXPOSED_DIAGNOSTIC_ONLY'})
        else:raise oldfit.FitError('LOCKED_EXAM_UNKNOWN')
    if len(oos)!=len(truth)*4 or len(kb)!=25*3*4:raise oldfit.FitError('LOCKED_CASE_COVERAGE_MISMATCH')
    sessions,calendar=scheduled_calendar()
    bars,reader_receipt=_read_outcome_bars(data_root,manifest,identities,act005_root)
    outcomes=[outcome(case,bars.get(case['canonical_security_id'],{}),sessions,h) for case in identities for h in (5,10,20)]
    by_outcome={(r['lane'],r['episode_id'],r['horizon']):r for r in outcomes}
    metrics={};policies=oos+original_rows
    for lane in LANES:
        metrics[lane]={}
        for arm,est in sorted({(r['arm'],r['estimator']) for r in policies if r['lane']==lane}):
            rows=[r for r in policies if r['lane']==lane and r['arm']==arm and r['estimator']==est]
            metrics[lane][arm+'__'+est]={'weak_agreement':weak_metrics(rows),
                'hypothetical_gross_outcomes':{str(h):outcome_summary([by_outcome[(lane,r['episode_id'],h)] for r in rows if r['decision']==1]) for h in (5,10,20)}}
    stage.mkdir()
    _write_rows(stage/'oos_casewise_weak_agreement.csv',oos+original_rows)
    _write_rows(stage/'kb25_exposed_diagnostics.csv',kb)
    _write_rows(stage/'oos_independent_outcomes.csv',outcomes)
    report={'schema':'pft_act008_evaluation.v1','batch':BATCH,'flags':FLAGS,'metrics':metrics,
            'prediction_lock_sha256':old._sha_file(fit_dir/'prediction_lock.json'),'actual_fit_counts':lock['actual_fit_counts'],
            'calendar':calendar,'post_lock_reader':reader_receipt,'overall_outcome_status':dict(Counter(r['status'] for r in outcomes)),
            'limits':['Operational weak-label agreement is not independent human B gold or realized trading performance.',
                      'KB25 views are exposed diagnostics; all human B labels remain UNKNOWN.',
                      'Case-control sample precision is sample-specific; not population prevalence.',
                      'Outcomes are hypothetical gross entry at next scheduled session open; no fills, fees or execution claim.',
                      'Unavailable, halted/untradeable and right-censored paths are excluded from valid horizon distributions, never compressed.']}
    write_json(stage/'evaluation.json',report)
    write_json(stage/'score_receipt.json',{'status':'SCORED','prediction_lock_sha256':report['prediction_lock_sha256'],'OOS_labels_opened_after_lock_verification':True,
        'post_D_outcomes_read_after_lock_verification':True,'outputs_sha256':{p.name:old._sha_file(p) for p in stage.iterdir() if p.is_file()},'flags':FLAGS})
    stage.replace(output_dir)
    return {'status':'SCORED','output_dir':str(output_dir),'OOS_prediction_rows':len(oos),'KB_prediction_rows':len(kb),'outcome_rows':len(outcomes),'outcome_status':report['overall_outcome_status']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['score','eval'])
    for name in ('prepared-dir','fit-dir','data-root','act005-root','output-dir'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(argv)
    try:result=score(prepared_dir=args.prepared_dir,fit_dir=args.fit_dir,data_root=args.data_root,act005_root=args.act005_root,output_dir=args.output_dir)
    except Exception as exc:
        print(json.dumps({'status':'FAILED','error':str(exc)}),file=sys.stderr);return 2
    print(json.dumps(result,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
