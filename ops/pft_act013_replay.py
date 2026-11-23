"""ACT-013 frozen ACT010 FULL_B_S050 four-scene overlays; zero model fitting."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:sys.path.insert(0,str(APP_ROOT))
import numpy as np
import pandas as pd
from ops import pft_act010_replay as base
from ops import pft_s_full_ashare as old
from ops.pft_act008_b import verify_source,write_json
from ops.pft_act008_b_score import scheduled_calendar
from ops.pft_act010_scan import START,ASOF,verified_file
from ops.pft_act013_market import FACTOR_NAME
BUY_FEE,SELL_FEE=base.BUY_FEE,base.SELL_FEE
SCENARIOS=('NONE','MACRO','RISK','MACRO_RISK')
HORIZONS=(5,10)
POLICY='FULL_B_S050'
number=base.number


def open_sell_status(row):
    if row is None:return base.fill_status(None,'SELL')
    return base.fill_status({**row,'close':number(row,'open')},'SELL')


def valid_mark(row):
    return (row is not None and math.isfinite(number(row,'close')) and number(row,'close')>0
            and number(row,'tradeable_basic')==1 and number(row,'vol')>0)


def anchor_price(case,bars):
    day=str(case.get('prior_anchor_date') or '')
    pct=number(case,'S_c_vs_recent_anchor_low_pct');c=number(bars.get(case['D'],{}),'close')
    denom=1+pct/100
    if not day or day>=case['D'] or not math.isfinite(pct) or not math.isfinite(c) or c<=0 or denom<=0:
        return math.nan
    return c/denom


def close_decision(lot,row,day,scenario,gate):
    """Only current observed close updates peak and queues tomorrow's sale."""
    reasons=[]
    if 'MACRO' in scenario and gate.get(day,'UNKNOWN')=='RISK_OFF':reasons.append('MACRO')
    if 'RISK' in scenario:
        if not valid_mark(row):
            lot['missing_yellow_days']+=1;lot['missing_anchor_days']+=int(not math.isfinite(lot['anchor']))
        else:
            c=number(row,'close');y=number(row,'zge_yellow_line')
            lot['peak_close']=max(lot['peak_close'],c)
            lot['trail_active']=lot['trail_active'] or c>=lot['entry_open']*1.08
            if math.isfinite(y) and y>0:
                if c<y:reasons.append('YELLOW')
            else:lot['missing_yellow_days']+=1
            if math.isfinite(lot['anchor']) and lot['anchor']>0:
                if c<lot['anchor']:reasons.append('ANCHOR')
            else:lot['missing_anchor_days']+=1
            if lot['trail_active'] and c<=lot['peak_close']*.95:reasons.append('TRAIL')
    if reasons and not lot.get('pending_reason'):
        lot.update(pending_reason=reasons[0],trigger_reasons='|'.join(reasons),trigger_date=day)
    return reasons


def init_risk(lot,case,bars):
    lot.update(anchor=anchor_price(case,bars),peak_close=lot['entry_open'],trail_active=False,
               pending_reason='',trigger_reasons='',trigger_date='',exit_reason='',exit_at='',
               missing_yellow_days=0,missing_anchor_days=0,open_exit_failed_attempts=0,
               active_position_days=0,running_peak_net=1.,running_close_mdd_pct=0.)


def event(case,bars,sessions,horizon,scenario,gate,asof=ASOF):
    if scenario=='NONE':
        r=base.standalone(case,bars,sessions,horizon,asof)
        i=sessions.index(case['D'])
        held=sum(d<=asof for d in sessions[i+1:i+horizon+1]) if r['entry_status']=='FILLED' else 0
        return {**r,'scenario':scenario,'exit_reason':'BASELINE','active_position_days':held,
                'missing_yellow_days':0,'missing_anchor_days':0,'open_exit_failed_attempts':0}
    # Start from the immutable baseline schema; none of its outcomes affect selection.
    result=base.standalone(case,{},sessions,horizon,asof);result['scenario']=scenario
    result.update(exit_reason='',exit_date='',exit_at='',trigger_date='',trigger_reasons='',
                  missing_yellow_days=0,missing_anchor_days=0,open_exit_failed_attempts=0,active_position_days=0)
    if 'MACRO' in scenario and gate.get(case['D'],'UNKNOWN')!='RISK_ON':
        result.update(status='NO_ENTRY',entry_status='MACRO_'+gate.get(case['D'],'UNKNOWN'),exit_status='NOT_ENTERED');return result
    day=result['entry_date'];status=base.fill_status(bars.get(day),'BUY')
    result['entry_status']=status
    if not day or day>asof:return result
    if status!='FILLED':result.update(status='NO_ENTRY',exit_status='NOT_ENTERED');return result
    entry=number(bars[day],'open');result['entry_open']=entry
    result['exit_status']='RIGHT_CENSORED' if not result['terminal_date'] or result['terminal_date']>asof else 'PENDING_SCHEDULED_EXIT'
    lot=dict(entry_open=entry,last_close=entry);init_risk(lot,case,bars)
    i=sessions.index(case['D']);target=result['terminal_date'];sold=False
    # Strict time-close endpoint for event study. Pending open retry is preserved
    # inside that window; unavailable scheduled close remains unavailable/censored.
    for day in sessions[i+1:i+horizon+1]:
        if day>asof:break
        row=bars.get(day);lot['active_position_days']+=1
        if lot['pending_reason'] and day>lot['trigger_date']:
            status=open_sell_status(row)
            if status=='FILLED':
                price=number(row,'open');sold=True;result.update(exit_status=status,exit_reason=lot['pending_reason'],exit_at='OPEN',exit_date=day);break
            lot['open_exit_failed_attempts']+=1
        mark=valid_mark(row)
        if mark:lot['last_close']=number(row,'close')
        result['stale_marks']+=int(not mark)
        result['missing_close_marks']+=int(not math.isfinite(number(row or {},'close')) or number(row or {},'close')<=0)
        result['halted_marks']+=int(row is not None and (number(row,'tradeable_basic')==0 or number(row,'vol')<=0))
        for side in ['up','down']:result['limit_'+side+'_unknown']+=int(not math.isfinite(number(row or {},'limit_'+side+'_approx')))
        net=lot['last_close']*(1-SELL_FEE)/(entry*(1+BUY_FEE));lot['running_peak_net']=max(lot['running_peak_net'],net)
        lot['running_close_mdd_pct']=min(lot['running_close_mdd_pct'],(net/lot['running_peak_net']-1)*100)
        if day==target:
            status=base.fill_status(row,'SELL');result['exit_status']=status
            if status=='FILLED':
                price=number(row,'close');sold=True;result.update(exit_reason='BASELINE',exit_at='CLOSE',exit_date=day)
            break
        close_decision(lot,row,day,scenario,gate)
    if sold and result['exit_at']=='OPEN':
        net=price*(1-SELL_FEE)/(entry*(1+BUY_FEE));lot['running_peak_net']=max(lot['running_peak_net'],net)
        lot['running_close_mdd_pct']=min(lot['running_close_mdd_pct'],(net/lot['running_peak_net']-1)*100)
    for key in ['missing_yellow_days','missing_anchor_days','open_exit_failed_attempts','active_position_days','trigger_date','trigger_reasons','running_close_mdd_pct']:result[key]=lot[key]
    if sold:
        gross=price/entry-1;net=price*(1-SELL_FEE)/(entry*(1+BUY_FEE))-1
        result.update(status='VALID',terminal_close=price,gross_return_pct=gross*100,net_return_pct=net*100,
                      fees_per_share=entry*BUY_FEE+price*SELL_FEE,fee_drag_pct=(gross-net)*100)
    else:result.update(status='RIGHT_CENSORED' if not target or target>asof else 'PLANNED_EXIT_UNAVAILABLE')
    return result


def portfolio(frame,bars,sessions,rail,horizon,scenario,gate,asof=ASOF):
    """Same opening allocations as ACT010; opening exit proceeds never fund buys."""
    days=[d for d in sessions if START<=d<=asof];index={d:i for i,d in enumerate(sessions)}
    picks=base.picks_by_day(frame,POLICY,rail,3)
    entries={sessions[index[d]+1]:r for d,r in picks.items() if index[d]+1<len(sessions) and sessions[index[d]+1]<=asof}
    config=dict(policy=POLICY,rail=rail,K=3,horizon=horizon,scenario=scenario)
    cash,previous_nav,peak,dd=1.,1.,1.,0.;active=[];ledger=[];navs=[]
    for day in days:
        planned=entries.get(day,[]);budget=min(previous_nav/horizon,max(cash,0.)) if planned else 0.
        allocation=budget/len(planned) if planned else 0.
        buy_fees=sell_fees=0.;entered=failed=exits=stale=0
        for case in planned:
            code=case['canonical_security_id'];row=bars.get(code,{}).get(day);status=base.fill_status(row,'BUY')
            if 'MACRO' in scenario and gate.get(case['D'],'UNKNOWN')!='RISK_ON':status='MACRO_'+gate.get(case['D'],'UNKNOWN')
            target_i=index[case['D']]+horizon;target=sessions[target_i] if target_i<len(sessions) else ''
            lot={**config,**{n:case[n] for n in ['episode_id','canonical_security_id','D','lane']},
                 'policy_score':case['policy_score'],'entry_date':day,'planned_exit_date':target,
                 'allocation':allocation,'entry_status':status,'status':'FAILED_ENTRY','quantity':0.,'buy_fee':0.,'sell_fee':0.,
                 'exit_date':'','exit_status':'','stale_marks':0,'delayed_exit_days':0,
                 'limit_up_unknown_days':0,'limit_down_unknown_days':0,'near_limit_up_days':0,'near_limit_down_days':0,
                 'entry_open':np.nan,'exit_close':np.nan}
            if status=='FILLED' and allocation>0:
                price=number(row,'open');qty=allocation/(price*(1+BUY_FEE));cost=qty*price*(1+BUY_FEE)
                cash-=cost;fee=qty*price*BUY_FEE;buy_fees+=fee
                lot.update(status='OPEN',quantity=qty,buy_fee=fee,entry_open=price,last_close=price)
                init_risk(lot,case,bars.get(code,{}));active.append(lot);entered+=1
            else:
                if status=='FILLED':lot['entry_status']='NO_OPENING_CASH'
                failed+=1
            ledger.append(lot)
        remaining=[]
        for lot in active:
            row=bars.get(lot['canonical_security_id'],{}).get(day);lot['active_position_days']+=1
            # This opening sale uses only a decision queued at an earlier close.
            if lot['pending_reason'] and day>lot['trigger_date']:
                status=open_sell_status(row);lot['exit_status']=status
                if status=='FILLED':
                    price=number(row,'open');notional=lot['quantity']*price;fee=notional*SELL_FEE
                    cash+=notional-fee;sell_fees+=fee;exits+=1
                    net=price*(1-SELL_FEE)/(lot['entry_open']*(1+BUY_FEE))
                    lot['running_peak_net']=max(lot['running_peak_net'],net)
                    lot['running_close_mdd_pct']=min(lot['running_close_mdd_pct'],(net/lot['running_peak_net']-1)*100)
                    lot.update(status='CLOSED',exit_date=day,exit_close=price,sell_fee=fee,exit_reason=lot['pending_reason'],exit_at='OPEN');continue
                lot['open_exit_failed_attempts']+=1
            close=number(row or {},'close');mark_stale=(not math.isfinite(close) or close<=0 or number(row or {},'tradeable_basic')==0 or number(row or {},'vol')<=0)
            if not mark_stale:lot['last_close']=close
            else:lot['stale_marks']+=1;stale+=1
            net=lot['last_close']*(1-SELL_FEE)/(lot['entry_open']*(1+BUY_FEE))
            lot['running_peak_net']=max(lot['running_peak_net'],net)
            lot['running_close_mdd_pct']=min(lot['running_close_mdd_pct'],(net/lot['running_peak_net']-1)*100)
            for side in ['up','down']:
                flag=number(row or {},'limit_'+side+'_approx');lot['limit_'+side+'_unknown_days']+=int(not math.isfinite(flag));lot['near_limit_'+side+'_days']+=int(flag==1)
            due=bool(lot['planned_exit_date'] and day>=lot['planned_exit_date'])
            if due:
                status=base.fill_status(row,'SELL');lot['exit_status']=status
                if status=='FILLED':
                    notional=lot['quantity']*close;fee=notional*SELL_FEE;cash+=notional-fee;sell_fees+=fee;exits+=1
                    lot.update(status='CLOSED',exit_date=day,exit_close=close,sell_fee=fee,exit_reason='BASELINE',exit_at='CLOSE');continue
                lot['delayed_exit_days']+=1
            close_decision(lot,row,day,scenario,gate);remaining.append(lot)
        active=remaining;value=sum(l['quantity']*l['last_close']*(1-SELL_FEE) for l in active);nav=cash+value
        peak=max(peak,nav);dd=min(dd,nav/peak-1)
        navs.append({**config,'date':day,'NAV':nav,'cash':cash,'positions_value_after_exit_cost':value,'open_lots':len(active),
                     'no_position':int(not active),'daily_return':nav/previous_nav-1,'buy_fees':buy_fees,'sell_fees':sell_fees,
                     'entries':entered,'failed_entries':failed,'closed_lots':exits,'stale_marks':stale,'opening_budget':budget})
        if cash< -1e-10:raise ValueError('NEGATIVE_CASH_LEDGER')
        previous_nav=nav
    entered_ids={r['episode_id'] for r in ledger}
    for rows in picks.values():
        for case in rows:
            if case['episode_id'] not in entered_ids:ledger.append({**config,**{n:case[n] for n in ['episode_id','canonical_security_id','D','lane']},'status':'ENTRY_AFTER_ASOF','entry_status':'ENTRY_AFTER_ASOF','quantity':0.,'allocation':0.,'buy_fee':0.,'sell_fee':0.})
    for lot in active:
        lot['residual_value_after_exit_cost']=lot['quantity']*lot['last_close']*(1-SELL_FEE)
        lot['residual_exit_fee_reserve']=lot['quantity']*lot['last_close']*SELL_FEE
    returns=np.array([r['daily_return'] for r in navs]);vol=np.std(returns,ddof=1) if len(returns)>1 else np.nan
    cagr=previous_nav**(252/len(days))-1 if days and previous_nav>0 else np.nan
    summary={**config,'selected':sum(map(len,picks.values())),'executed':sum(l['status'] in ['OPEN','CLOSED'] for l in ledger),
        'failed':sum(l['status']=='FAILED_ENTRY' for l in ledger),'entry_after_asof':sum(l['status']=='ENTRY_AFTER_ASOF' for l in ledger),
        'open':len(active),'closed':sum(l['status']=='CLOSED' for l in ledger),'final_NAV':previous_nav,'net_return_pct':(previous_nav-1)*100,
        'MDD_pct':dd*100,'CAGR':cagr,'Sharpe_252_RF0':np.mean(returns)/vol*np.sqrt(252) if vol>0 else np.nan,
        'Calmar':cagr/abs(dd) if dd<0 else np.nan,'no_position_fraction':sum(n['no_position'] for n in navs)/len(navs) if navs else np.nan,
        'buy_fees':sum(l['buy_fee'] for l in ledger),'sell_fees':sum(l['sell_fee'] for l in ledger),
        'residual_exit_fee_reserve':sum(l['residual_exit_fee_reserve'] for l in active),'session_count':len(days),'start_NAV':1.,'annualization_sessions':252,
        'near_limit_up_cumulative_holding_days':sum(l.get('near_limit_up_days',0) for l in ledger),
        'near_limit_down_cumulative_holding_days':sum(l.get('near_limit_down_days',0) for l in ledger),'stale_marks':sum(l.get('stale_marks',0) for l in ledger),
        'exit_reason_counts_json':json.dumps(dict(Counter(l.get('exit_reason','') for l in ledger if l['status']=='CLOSED')),sort_keys=True),
        'blocked_macro_entries':sum(str(l['entry_status']).startswith('MACRO_') for l in ledger),
        'missing_yellow_days':sum(l.get('missing_yellow_days',0) for l in ledger),'missing_anchor_days':sum(l.get('missing_anchor_days',0) for l in ledger),
        'active_position_days':sum(l.get('active_position_days',0) for l in ledger),'open_exit_failed_attempts':sum(l.get('open_exit_failed_attempts',0) for l in ledger)}
    return navs,ledger,summary


def read_bars(data_root,act005_root,manifest,identities,batch_size=384):
    from ops.pft_s_first_baseline import bind_current_panels
    from ops import research_panel_logical as reader
    frozen=old._validate_inputs(act005_root);needed=sorted(set(identities.canonical_security_id));codes={c:[] for c in needed}
    for raw,c in frozen['aliases'].items():
        if c in codes:codes[c].append(raw)
    if any(not x for x in codes.values()):raise ValueError('OUTCOME_UNMAPPED_CANONICAL')
    result={};rows_read=0
    with bind_current_panels(data_root) as (path,source,recheck):
        verify_source(source,frozen)
        if source['identity']!=manifest['source']['identity'] or source['backtest']['panel_sha256']!=manifest['source']['backtest']['panel_sha256']:raise ValueError('POST_SEAL_SOURCE_DRIFT')
        schema=reader.parquet.read_schema(path);actual=old._schema_names(schema)
        fields=['ts_code','trade_date','open','high','low','close','tradeable_basic','limit_up_approx','limit_down_approx','zge_yellow_line']
        mapping={n:actual[n] for n in fields};mapping['vol']=actual.get('vol',actual.get('volume'))
        if not mapping['vol']:raise ValueError('OUTCOME_VOLUME_MISSING')
        for batch in old._code_cohorts(codes,batch_size):
            filters=[[(mapping['ts_code'],'in',batch),(mapping['trade_date'],'>=',old._date_value(schema,mapping['trade_date'],START)),
                      (mapping['trade_date'],'<=',old._date_value(schema,mapping['trade_date'],ASOF))]]
            t=reader.parquet.read_table(path,columns=list(mapping.values()),filters=filters,use_threads=True)
            grouped=old._normalize_panel_rows(t,mapping,frozen['aliases']);rows_read+=t.num_rows
            for c,by_code in grouped.items():result[c]={r['trade_date']:r for r in old._deduplicate_alias_history(by_code,frozen['crosswalk_aliases'])}
            print(json.dumps({'outcome_codes':len(result),'needed':len(needed)}),flush=True)
        recheck()
    return result,dict(rows_read=rows_read,canonical_securities=len(needed),source=source,range=[START,ASOF],projected_columns=mapping)


def read_features(scan_dir,manifest,candidates):
    cols=['canonical_security_id','D','S_c_vs_recent_anchor_low_pct']
    frames=[pd.read_parquet(scan_dir/n,columns=cols) for n in sorted(manifest['outputs_sha256']) if n.endswith('_features.parquet')]
    f=pd.concat(frames,ignore_index=True)
    if f.duplicated(['canonical_security_id','D']).any():raise ValueError('DUPLICATE_SEALED_FEATURE_KEY')
    return candidates.merge(f,on=['canonical_security_id','D'],validate='many_to_one')


def read_gate(market_dir,source):
    m=old._read_json(market_dir/'market_manifest.json');p=verified_file(market_dir/FACTOR_NAME,m['factor_sha256'])
    if m['mode']!='FULL' or m['range']!=['20220101',ASOF] or m['flags']!=old.FLAGS:raise ValueError('MACRO_NOT_FROZEN_FULL')
    if m['source']['identity']!=source['identity'] or m['source']['backtest']['panel_sha256']!=source['backtest']['panel_sha256']:raise ValueError('MACRO_SOURCE_DRIFT')
    f=pd.read_csv(p,dtype={'D':str})
    if f.D.duplicated().any() or not set(f.gate).issubset({'RISK_ON','RISK_OFF','UNKNOWN'}):raise ValueError('INVALID_MACRO_GATES')
    known=f[['cw_n','cy_n','wy_n']].gt(0).all(axis=1)
    on=(f[['cw_above','cy_above','wy_above']].to_numpy()/f[['cw_n','cy_n','wy_n']].replace(0,np.nan).to_numpy()>.5).all(axis=1)
    expected=np.where(~known,'UNKNOWN',np.where(on,'RISK_ON','RISK_OFF'))
    if not np.array_equal(expected,f.gate.to_numpy()):raise ValueError('MACRO_GATE_COUNT_MISMATCH')
    return dict(zip(f.D,f.gate)),m


def parity_frame(actual,expected,keys,columns):
    a=actual.sort_values(keys).reset_index(drop=True);e=expected.sort_values(keys).reset_index(drop=True)
    if len(a)!=len(e):raise ValueError('BASELINE_ROW_COUNT_MISMATCH')
    # Exact rowwise values, including all existing numeric accounting outputs.
    pd.testing.assert_frame_equal(a[keys+columns],e[keys+columns],check_dtype=False,check_exact=True)
    return {'status':'PASS_EXACT','rows':len(a),'keys':keys,'columns':columns}


def monthly_nav(navs):
    records=[]
    for key,g in navs.groupby(['scenario','rail','horizon'],sort=True):
        previous=1.
        for month,m in g.sort_values('date').groupby(g.sort_values('date').date.str[:6],sort=True):
            values=m.NAV.to_numpy();peak=previous;mdd=0.
            for v in values:peak=max(peak,v);mdd=min(mdd,v/peak-1)
            records.append(dict(zip(['scenario','rail','horizon'],key),month=month,start_NAV=previous,final_NAV=values[-1],
                                net_return_pct=(values[-1]/previous-1)*100,MDD_pct=mdd*100,
                                no_position_fraction=m.no_position.mean(),session_count=len(m)))
            previous=values[-1]
    return pd.DataFrame(records)


def metric_extra(f):
    valid=f[f.status.eq('VALID')]
    return {'exit_reason_counts_json':json.dumps(dict(Counter(valid.exit_reason)),sort_keys=True),
            'blocked_macro_entries':int(f.entry_status.str.startswith('MACRO_',na=False).sum()),
            'realized_net_equity_sum_equal_unit':float((1+valid.net_return_pct/100).sum()),
            'active_position_days':int(pd.to_numeric(f.get('active_position_days',pd.Series(dtype=float)),errors='coerce').sum()),
            'missing_yellow_days':int(pd.to_numeric(f.get('missing_yellow_days',pd.Series(dtype=float)),errors='coerce').sum()),
            'missing_anchor_days':int(pd.to_numeric(f.get('missing_anchor_days',pd.Series(dtype=float)),errors='coerce').sum()),
            'open_exit_failed_attempts':int(pd.to_numeric(f.get('open_exit_failed_attempts',pd.Series(dtype=float)),errors='coerce').sum())}


def replay(*,scan_dir,baseline_dir,act005_root,data_root,market_dir,output_dir):
    if output_dir.exists() or output_dir.with_name(output_dir.name+'.partial').exists():raise ValueError('OUTPUT_EXISTS')
    manifest,candidates,seal=base.read_sealed(scan_dir)
    if manifest['mode']!='NATURAL_FULL' or len(candidates)!=47931:raise ValueError('ACT010_SEALED_COUNT_OR_MODE_DRIFT')
    bmanifest=old._read_json(baseline_dir/'replay_manifest.json')
    seal_sha=old._sha_file(scan_dir/'pre_outcome_seal.json')
    if bmanifest['scan_seal_sha256']!=seal_sha or bmanifest['flags']!=old.FLAGS:raise ValueError('BASELINE_SEAL_DRIFT')
    for n,sha in bmanifest['outputs_sha256'].items():verified_file(baseline_dir/n,sha)
    candidates=read_features(scan_dir,manifest,candidates)
    sessions,calendar=scheduled_calendar()
    if calendar['year']!=2026 or not set(candidates.D).issubset(sessions):raise ValueError('CALENDAR_DRIFT')
    gate,macro=read_gate(market_dir,manifest['source'])
    if not set(d for d in sessions if START<=d<=ASOF).issubset(gate):raise ValueError('MACRO_SESSION_MISSING')
    # Freeze policy selections BEFORE opening any future/execution source bars.
    all_picks={rail:base.picks_by_day(candidates,POLICY,rail) for rail in base.RAILS}
    ids={r['episode_id'] for x in all_picks.values() for rs in x.values() for r in rs}
    selected=candidates[candidates.episode_id.isin(ids)]
    bars,receipt=read_bars(data_root,act005_root,manifest,selected)
    stage=output_dir.with_name(output_dir.name+'.partial');stage.mkdir(parents=True)
    write_json(stage/'outcome_read_receipt.json',receipt)
    navs=[];lots=[];summaries=[];events=[]
    event_ids={}
    for rail,picks in all_picks.items():event_ids[rail]={r['episode_id'] for rows in picks.values() for r in rows}
    for scenario in SCENARIOS:
        for case in selected.to_dict('records'):
            for h in HORIZONS:events.append(event(case,bars.get(case['canonical_security_id'],{}),sessions,h,scenario,gate))
        for rail in base.RAILS:
            for h in HORIZONS:
                n,l,s=portfolio(candidates,bars,sessions,rail,h,scenario,gate);navs.extend(n);lots.extend(l);summaries.append(s)
        print(json.dumps({'completed_scenario':scenario,'strategies':len(summaries)}),flush=True)
    n=pd.DataFrame(navs);l=pd.DataFrame(lots);s=pd.DataFrame(summaries);e=pd.DataFrame(events)
    oldn=pd.read_parquet(baseline_dir/'portfolio_nav.parquet');olds=pd.read_csv(baseline_dir/'portfolio_summary.csv')
    keep=lambda f:f.policy.eq(POLICY)&f.K.eq(3)&f.horizon.isin(HORIZONS)
    oldn=oldn[keep(oldn)];olds=olds[keep(olds)]
    nav_cols=[c for c in oldn.columns if c not in ['policy','rail','K','horizon','date']]
    summary_cols=[c for c in olds.columns if c not in ['policy','rail','K','horizon']]
    # CSV decimal reparse cannot be exact at binary rounding; compare summary to
    # original kernel in memory, then stored CSV with stated 1e-12 tolerance.
    pn=parity_frame(n[n.scenario.eq('NONE')],oldn,['policy','rail','K','horizon','date'],nav_cols)
    for rail in base.RAILS:
        for h in HORIZONS:
            _,_,ref=base.portfolio(candidates,bars,sessions,POLICY,rail,3,h)
            candidate=s[s.scenario.eq('NONE')&s.rail.eq(rail)&s.horizon.eq(h)].iloc[0]
            for c in summary_cols:
                a,b=candidate[c],ref[c]
                if pd.isna(a) and pd.isna(b):continue
                if a!=b:raise ValueError('BASELINE_KERNEL_SUMMARY_MISMATCH:'+c)
    a=s[s.scenario.eq('NONE')].sort_values(['rail','horizon']).reset_index(drop=True)
    z=olds.sort_values(['rail','horizon']).reset_index(drop=True)
    pd.testing.assert_frame_equal(a[summary_cols],z[summary_cols],check_dtype=False,check_exact=False,rtol=1e-12,atol=1e-12)
    olde=pd.read_parquet(baseline_dir/'outcomes.parquet');olde=olde[olde.episode_id.isin(ids)&olde.horizon.isin(HORIZONS)]
    pe=parity_frame(e[e.scenario.eq('NONE')],olde,['episode_id','horizon'],[c for c in olde.columns if c not in ['episode_id','horizon']])
    parity={'daily':pn,'summary_kernel':'PASS_EXACT','summary_stored_csv':'PASS_1E-12','events':pe,
            'baseline_manifest_sha256':old._sha_file(baseline_dir/'replay_manifest.json'),'scan_seal_sha256':seal_sha}
    write_json(stage/'baseline_parity.json',parity)
    overall=[];monthly=[];observed=[d for d in sessions if START<=d<=ASOF]
    for scenario in SCENARIOS:
        for rail in base.RAILS:
            for h in HORIZONS:
                sub=e[e.scenario.eq(scenario)&e.horizon.eq(h)&e.episode_id.isin(event_ids[rail])]
                cfg=dict(scenario=scenario,rail=rail,horizon=h,policy=POLICY)
                overall.append({**cfg,**base.distribution_metrics(sub,observed),**metric_extra(sub)})
                for month in sorted({d[:6] for d in observed}):
                    m=sub[sub.D.str.startswith(month)]
                    monthly.append({**cfg,'month':month,**base.distribution_metrics(m,[d for d in observed if d.startswith(month)]),**metric_extra(m)})
    n.to_parquet(stage/'portfolio_nav.parquet',index=False);l.to_parquet(stage/'portfolio_lots.parquet',index=False)
    s.to_csv(stage/'portfolio_summary.csv',index=False);e.to_parquet(stage/'event_outcomes.parquet',index=False)
    pd.DataFrame(overall).to_csv(stage/'event_metrics.csv',index=False)
    pd.DataFrame(monthly).to_csv(stage/'monthly_event_metrics.csv',index=False)
    monthly_nav(n).to_csv(stage/'monthly_portfolio_metrics.csv',index=False)
    base.read_sealed(scan_dir)
    read_gate(market_dir,manifest['source'])
    outputs={p.name:old._sha_file(p) for p in stage.iterdir() if p.is_file()}
    report={'batch':'ACT-013','status':'COMPUTED_PENDING_INDEPENDENT_REVIEW','flags':old.FLAGS,
        'scan_seal_sha256':seal_sha,'market_factor_sha256':macro['factor_sha256'],'source':receipt['source'],'calendar':calendar,
        'scenarios':list(SCENARIOS),'horizons':list(HORIZONS),'policy':POLICY,'TopK':3,'baseline_parity':parity,
        'selected_count_by_rail':{r:sum(map(len,p.values())) for r,p in all_picks.items()},
        'top3_selected_count_by_rail':{r:sum(map(len,base.picks_by_day(candidates,POLICY,r,3).values())) for r in base.RAILS},
        'thresholds':{'breadth_all_gt':.5,'trail_activation':1.08,'trail_peak_fraction':.95},
        'costs':{'buy':BUY_FEE,'sell':SELL_FEE},'fits_this_round':{'B':0,'S':0},
        'code_sha256':{str(Path(__file__)):old._sha_file(Path(__file__))},'outputs_sha256':outputs,
        'semantics':{'macro':'D close gate blocks D+1 entry; risk-off queues held lot open sale; UNKNOWN only blocks entry',
          'priority':'MACRO, YELLOW, ANCHOR, TRAIL; all initial trigger reasons recorded; first pending reason retained',
          'scheduled_close':'Prescheduled close may fill if pending opening exit failed; exit_reason BASELINE, initial pending_reason/trigger retained',
          'event_exit':'Strict D+H endpoint; pending opening retry within window, unavailable scheduled close not realized',
          'cash':'All equal opening allocations fixed before any opening sale proceeds; no replacements',
          'valuation':'All open lots marked net of estimated sell fee; unavailable exits remain unrealized',
          'monthly':'NAV actual dates, return vs prior EOM NAV; month drawdown starts prior EOM NAV. Events grouped by signal D'},
        'source_PIT':'CANNOT_CONFIRM; frozen generation replay only','execution':'RESEARCH_ONLY approximate fill/limits, no broker or capacity certification'}
    write_json(stage/'replay_manifest.json',report);stage.rename(output_dir)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['scan-dir','baseline-dir','act005-root','data-root','market-dir','output-dir']:p.add_argument('--'+name,type=Path,required=True)
    try:r=replay(**vars(p.parse_args(argv)))
    except Exception as e:print(json.dumps({'status':'FAILED','error':str(e)}),file=sys.stderr);return 2
    print(json.dumps(r,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
