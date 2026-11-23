"""Post-seal ACT-010 scheduled outcomes and cash-constrained research ledger.

Selection is derived solely from sealed D scores. Same-day bars are used only
for fill/mark accounting. No model loading, fitting, broker, or panel writes.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:sys.path.insert(0,str(APP_ROOT))
import numpy as np
import pandas as pd
from ops import pft_s_full_ashare as old
from ops.pft_act008_b import write_json, verify_source
from ops.pft_act008_b_score import scheduled_calendar
from ops.pft_act010_scan import START, ASOF, verified_file

BUY_FEE, SELL_FEE = .00075, .00125
HORIZONS = (3,5,10,20)
POLICIES = ('ORIGINAL','BASELINE_B','FULL_B','FULL_B_S030','FULL_B_S050')
RAILS = ('B1','B2','B3','ALL')


def number(row,name):
    try:return float(row[name])
    except (TypeError,ValueError,KeyError):return math.nan


def fill_status(row,side):
    if row is None:return 'MISSING_SCHEDULED_BAR'
    price = number(row,'open' if side=='BUY' else 'close')
    if not math.isfinite(price) or price<=0:return 'MISSING_PRICE'
    volume, tradable = number(row,'vol'), number(row,'tradeable_basic')
    if tradable==0 or (math.isfinite(volume) and volume<=0):return 'HALTED_OR_UNTRADEABLE'
    if tradable!=1 or not math.isfinite(volume):return 'TRADEABILITY_UNKNOWN'
    hi,lo = number(row,'high'),number(row,'low')
    if not math.isfinite(hi) or not math.isfinite(lo) or min(hi,lo)<=0:return 'RANGE_UNKNOWN'
    if hi<lo or not lo-1e-8<=price<=hi+1e-8:return 'INVALID_OHLC'
    flag = number(row,'limit_up_approx' if side=='BUY' else 'limit_down_approx')
    if math.isclose(hi,lo,rel_tol=1e-7,abs_tol=1e-8):
        if flag==1:return 'ONE_PRICE_UP_LOCK' if side=='BUY' else 'ONE_PRICE_DOWN_LOCK'
        if flag!=0:return 'ONE_PRICE_LIMIT_UNKNOWN'
    return 'FILLED'


def standalone(case,bars,sessions,horizon,asof=ASOF):
    """Strict D+h close. Intervening absent/halted marks carry the last close."""
    i = sessions.index(case['D'])
    entry_day = sessions[i+1] if i+1<len(sessions) else ''
    target = sessions[i+horizon] if i+horizon<len(sessions) else ''
    base = {n:case[n] for n in ('episode_id','canonical_security_id','D','lane')}
    base.update(horizon=horizon,entry_date=entry_day,terminal_date=target,status='',entry_status='',exit_status='',
                entry_open=np.nan,terminal_close=np.nan,gross_return_pct=np.nan,net_return_pct=np.nan,
                running_close_mdd_pct=np.nan,fees_per_share=np.nan,fee_drag_pct=np.nan,
                stale_marks=0,missing_close_marks=0,halted_marks=0,limit_up_unknown=0,limit_down_unknown=0)
    if not entry_day or entry_day>asof:
        return {**base,'status':'RIGHT_CENSORED','entry_status':'ENTRY_AFTER_ASOF','exit_status':'RIGHT_CENSORED'}
    e = bars.get(entry_day); entry_status = fill_status(e,'BUY');base['entry_status'] = entry_status
    if entry_status!='FILLED':return {**base,'status':'NO_ENTRY','exit_status':'NOT_ENTERED'}
    entry = number(e,'open');base['entry_open'] = entry
    terminal_known = bool(target and target<=asof)
    path = [d for d in sessions[i+1:i+horizon+1] if d<=asof]
    last,peak,dd = entry,1.,0.
    for day in path:
        row = bars.get(day);close = number(row or {},'close')
        halted = row is not None and (number(row,'tradeable_basic')==0 or number(row,'vol')<=0)
        missing = not math.isfinite(close) or close<=0
        stale = missing or halted
        if not stale:last = close
        base['stale_marks'] += int(stale);base['missing_close_marks'] += int(missing);base['halted_marks'] += int(halted)
        base['limit_up_unknown'] += int(not math.isfinite(number(row or {},'limit_up_approx')))
        base['limit_down_unknown'] += int(not math.isfinite(number(row or {},'limit_down_approx')))
        equity = last*(1-SELL_FEE)/(entry*(1+BUY_FEE))
        peak = max(peak,equity);dd = min(dd,equity/peak-1)
    base['running_close_mdd_pct'] = dd*100
    if not terminal_known:return {**base,'status':'RIGHT_CENSORED','exit_status':'RIGHT_CENSORED'}
    exit_status = fill_status(bars.get(target),'SELL');base['exit_status'] = exit_status
    if exit_status!='FILLED':return {**base,'status':'PLANNED_EXIT_UNAVAILABLE'}
    terminal = number(bars[target],'close')
    gross = terminal/entry-1
    net = terminal*(1-SELL_FEE)/(entry*(1+BUY_FEE))-1
    return {**base,'status':'VALID','terminal_close':terminal,'gross_return_pct':gross*100,
            'net_return_pct':net*100,'fees_per_share':entry*BUY_FEE+terminal*SELL_FEE,
            'fee_drag_pct':(gross-net)*100}


def policy_score(frame,policy):
    """Unknown S never passes hard gate. No outcomes, price, or later eligibility."""
    if policy=='ORIGINAL':return pd.Series(np.where(frame.raw_trigger,1.,np.nan),index=frame.index)
    score = pd.to_numeric(frame['BASELINE_B_prob' if policy=='BASELINE_B' else 'FULL_B_prob'],errors='coerce')
    keep = frame.eligible & score.ge(.5)
    if policy in ('FULL_B_S030','FULL_B_S050'):
        keep &= pd.to_numeric(frame.S_prob_gated,errors='coerce').ge(.3 if policy.endswith('030') else .5)
    return score.where(keep)


def picks_by_day(frame,policy,rail,k=None):
    f = frame if rail=='ALL' else frame[frame.lane.eq(rail)]
    f = f.copy();f['policy_score'] = policy_score(f,policy)
    f = f[f.policy_score.notna()]
    f = f.sort_values(['D','policy_score','canonical_security_id','lane'],ascending=[True,False,True,True],kind='mergesort')
    if rail=='ALL':f = f.drop_duplicates(['D','canonical_security_id'],keep='first')
    if k is not None:f = f.groupby('D',sort=False).head(k)
    return {day:g.to_dict('records') for day,g in f.groupby('D',sort=True)}


def distribution_metrics(frame,sessions):
    valid = frame[frame.status.eq('VALID')]
    r = pd.to_numeric(valid.net_return_pct,errors='coerce').dropna()
    dd = pd.to_numeric(valid.running_close_mdd_pct,errors='coerce').dropna()
    wins,losses = r[r>0],r[r<0]
    counts = Counter(frame.status)
    return {'signals':len(frame),'signal_days':int(frame.D.nunique()),
        'daily_mean_signals_all_sessions':len(frame)/len(sessions) if sessions else np.nan,
        'valid_closed_trades':len(valid),'distinct_codes':int(frame.canonical_security_id.nunique()),
        'coverage':len(valid)/len(frame) if len(frame) else np.nan,
        'no_entry':counts['NO_ENTRY'],'right_censored':counts['RIGHT_CENSORED'],
        'planned_exit_unavailable':counts['PLANNED_EXIT_UNAVAILABLE'],
        'status_counts_json':json.dumps(dict(counts),sort_keys=True),
        'entry_status_counts_json':json.dumps(dict(Counter(frame.entry_status)),sort_keys=True),
        'exit_status_counts_json':json.dumps(dict(Counter(frame.exit_status)),sort_keys=True),
        'mean_net_return_pct':r.mean(),'median_net_return_pct':r.median(),'win_rate':len(wins)/len(r) if len(r) else np.nan,
        'payoff_avg_win_abs_avg_loss':wins.mean()/abs(losses.mean()) if len(wins) and len(losses) else np.nan,
        'mean_gross_return_pct':valid.gross_return_pct.mean(),'mean_fee_drag_pct':valid.fee_drag_pct.mean(),
        'mean_mdd_pct':dd.mean(),'deepest_mdd_pct':dd.min(),
        'return_tail_gt_minus20_le_minus10_N':int(((r> -20)&(r<= -10)).sum()),
        'return_tail_le_minus20_N':int((r<= -20).sum()),
        'return_tail_gt_minus20_le_minus10_rate':float(((r> -20)&(r<= -10)).mean()) if len(r) else np.nan,
        'return_tail_le_minus20_rate':float((r<= -20).mean()) if len(r) else np.nan,
        'mdd_tail_gt_minus20_le_minus10_N':int(((dd> -20)&(dd<= -10)).sum()),
        'mdd_tail_le_minus20_N':int((dd<= -20).sum()),
        'mdd_tail_gt_minus20_le_minus10_rate':float(((dd> -20)&(dd<= -10)).mean()) if len(dd) else np.nan,
        'mdd_tail_le_minus20_rate':float((dd<= -20).mean()) if len(dd) else np.nan,
        'tail_denominator_valid_closed_trades':len(valid),'stale_marks':int(frame.stale_marks.sum())}


def excluded_episode_ids(candidates,rail,hard_policy):
    """Pooled gate removes a stock-day only if no eligible alternate lane remains."""
    soft = [r for rows in picks_by_day(candidates,'FULL_B',rail).values() for r in rows]
    hard = [r for rows in picks_by_day(candidates,hard_policy,rail).values() for r in rows]
    retained = {(r['canonical_security_id'],r['D']) for r in hard}
    return {r['episode_id'] for r in soft if (r['canonical_security_id'],r['D']) not in retained}


def portfolio(frame,bars,sessions,policy,rail,k,horizon):
    """Daily open buys precede close exits; independent overlapping cohort lots."""
    days = [d for d in sessions if START<=d<=ASOF]
    index = {d:i for i,d in enumerate(sessions)}
    picks = picks_by_day(frame,policy,rail,k)
    entries = {sessions[index[d]+1]:rows for d,rows in picks.items() if index[d]+1<len(sessions) and sessions[index[d]+1]<=ASOF}
    config = {'policy':policy,'rail':rail,'K':k,'horizon':horizon}
    cash,previous_nav,peak,dd = 1.,1.,1.,0.
    active,ledger,navs = [],[],[]
    selected = sum(map(len,picks.values()))
    for day in days:
        planned = entries.get(day,[])
        # A cohort receives previous-close NAV/H, with cash available before
        # any closing exits. Failed planned slots remain cash, no replacement.
        budget = min(previous_nav/horizon,max(cash,0.)) if planned else 0.
        allocation = budget/len(planned) if planned else 0.
        buy_fees = sell_fees = 0.;entered = failed = exits = stale = 0
        for case in planned:
            code = case['canonical_security_id'];row = bars.get(code,{}).get(day)
            status = fill_status(row,'BUY')
            target_i = index[case['D']]+horizon
            target = sessions[target_i] if target_i<len(sessions) else ''
            lot = {**config,**{n:case[n] for n in ('episode_id','canonical_security_id','D','lane')},
                   'policy_score':case['policy_score'],'entry_date':day,'planned_exit_date':target,
                   'allocation':allocation,'entry_status':status,'status':'FAILED_ENTRY','quantity':0.,'buy_fee':0.,
                   'sell_fee':0.,'exit_date':'','exit_status':'','stale_marks':0,'delayed_exit_days':0,
                   'limit_up_unknown_days':0,'limit_down_unknown_days':0,
                   'near_limit_up_days':0,'near_limit_down_days':0,'entry_open':np.nan,'exit_close':np.nan}
            if status=='FILLED' and allocation>0:
                price = number(row,'open');quantity = allocation/(price*(1+BUY_FEE))
                cost = quantity*price*(1+BUY_FEE)
                cash -= cost;fee = quantity*price*BUY_FEE;buy_fees += fee
                lot.update(status='OPEN',quantity=quantity,buy_fee=fee,entry_open=price,last_close=price)
                active.append(lot);entered += 1
            else:
                if status=='FILLED':lot['entry_status'] = 'NO_OPENING_CASH'
                failed += 1
            ledger.append(lot)
        remaining = []
        for lot in active:
            row = bars.get(lot['canonical_security_id'],{}).get(day)
            close = number(row or {},'close')
            mark_stale = (not math.isfinite(close) or close<=0 or number(row or {},'tradeable_basic')==0 or number(row or {},'vol')<=0)
            if not mark_stale:lot['last_close'] = close
            else:lot['stale_marks'] += 1;stale += 1
            for side in ('up','down'):
                flag = number(row or {},f'limit_{side}_approx')
                lot[f'limit_{side}_unknown_days'] += int(not math.isfinite(flag))
                lot[f'near_limit_{side}_days'] += int(flag==1)
            due = bool(lot['planned_exit_date'] and day>=lot['planned_exit_date'])
            if due:
                exit_status = fill_status(row,'SELL');lot['exit_status'] = exit_status
                if exit_status=='FILLED':
                    notional = lot['quantity']*close;fee = notional*SELL_FEE
                    cash += notional-fee;sell_fees += fee;exits += 1
                    lot.update(status='CLOSED',exit_date=day,exit_close=close,sell_fee=fee)
                    continue
                lot['delayed_exit_days'] += 1
            remaining.append(lot)
        active = remaining
        position_value = sum(l['quantity']*l['last_close']*(1-SELL_FEE) for l in active)
        nav = cash+position_value
        peak = max(peak,nav);dd = min(dd,nav/peak-1)
        navs.append({**config,'date':day,'NAV':nav,'cash':cash,'positions_value_after_exit_cost':position_value,
                     'open_lots':len(active),'no_position':int(not active),'daily_return':nav/previous_nav-1,
                     'buy_fees':buy_fees,'sell_fees':sell_fees,'entries':entered,'failed_entries':failed,
                     'closed_lots':exits,'stale_marks':stale,'opening_budget':budget})
        if cash< -1e-10:raise ValueError('NEGATIVE_CASH_LEDGER')
        previous_nav = nav
    # Preserve selected final-D slots even when no entry session exists by asof.
    entered_ids = {r['episode_id'] for r in ledger}
    for d,rows in picks.items():
        for case in rows:
            if case['episode_id'] not in entered_ids:
                ledger.append({**config,**{n:case[n] for n in ('episode_id','canonical_security_id','D','lane')},
                               'policy_score':case['policy_score'],'status':'ENTRY_AFTER_ASOF','entry_status':'ENTRY_AFTER_ASOF',
                               'quantity':0.,'allocation':0.,'buy_fee':0.,'sell_fee':0.})
    for lot in active:
        lot['residual_value_after_exit_cost'] = lot['quantity']*lot['last_close']*(1-SELL_FEE)
        lot['residual_exit_fee_reserve'] = lot['quantity']*lot['last_close']*SELL_FEE
    returns = np.array([r['daily_return'] for r in navs],dtype=float)
    volatility = np.std(returns,ddof=1) if len(returns)>1 else np.nan
    cagr = previous_nav**(252/len(days))-1 if days and previous_nav>0 else np.nan
    summary = {**config,'selected':selected,'executed':sum(l['status'] in ('OPEN','CLOSED') for l in ledger),
        'failed':sum(l['status']=='FAILED_ENTRY' for l in ledger),'entry_after_asof':sum(l['status']=='ENTRY_AFTER_ASOF' for l in ledger),
        'open':len(active),'closed':sum(l['status']=='CLOSED' for l in ledger),'final_NAV':previous_nav,
        'net_return_pct':(previous_nav-1)*100,'MDD_pct':dd*100,'CAGR':cagr,
        'Sharpe_252_RF0':np.mean(returns)/volatility*np.sqrt(252) if volatility>0 else np.nan,
        'Calmar':cagr/abs(dd) if dd<0 else np.nan,
        'no_position_fraction':sum(r['no_position'] for r in navs)/len(navs) if navs else np.nan,
        'buy_fees':sum(r['buy_fee'] for r in ledger),'sell_fees':sum(r['sell_fee'] for r in ledger),
        'residual_exit_fee_reserve':sum(l['residual_exit_fee_reserve'] for l in active),
        'session_count':len(days),'start_NAV':1.,'annualization_sessions':252,
        'near_limit_up_cumulative_holding_days':sum(r.get('near_limit_up_days',0) for r in ledger),
        'near_limit_down_cumulative_holding_days':sum(r.get('near_limit_down_days',0) for r in ledger),
        'stale_marks':sum(r.get('stale_marks',0) for r in ledger)}
    return navs,ledger,summary


def read_sealed(scan_dir):
    seal = old._read_json(scan_dir/'pre_outcome_seal.json')
    verified_file(scan_dir/'scan_manifest.json',seal['manifest_sha256'])
    manifest = old._read_json(scan_dir/'scan_manifest.json')
    if seal.get('schema')!='ACT010_PRE_OUTCOME_V1' or seal.get('flags')!=old.FLAGS or seal.get('outcomes_read') is not False:
        raise ValueError('INVALID_PRE_OUTCOME_SEAL')
    if manifest['outputs_sha256']!=seal['outputs_sha256'] or manifest['mode']!=seal['mode']:
        raise ValueError('SEAL_MANIFEST_MISMATCH')
    for name,sha in seal['outputs_sha256'].items():verified_file(scan_dir/name,sha)
    for path,sha in seal['models_and_training_sha256'].items():verified_file(Path(path),sha)
    for path,sha in manifest['code_sha256'].items():verified_file(Path(path),sha)
    frames = [pd.read_parquet(scan_dir/name) for name in sorted(seal['outputs_sha256']) if name.endswith('_candidates.parquet')]
    c = pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()
    if not c.empty and c.episode_id.duplicated().any():raise ValueError('DUPLICATE_SEALED_EPISODE')
    return manifest,c,seal


def read_outcome_bars(data_root,act005_root,manifest,identities,batch_size=384):
    from ops import pft_s_first_baseline as baseline
    from ops import research_panel_logical as reader
    frozen = old._validate_inputs(act005_root)
    needed = sorted(set(identities.canonical_security_id))
    codes = {c:[] for c in needed}
    for raw,c in frozen['aliases'].items():
        if c in codes:codes[c].append(raw)
    if any(not r for r in codes.values()):raise ValueError('OUTCOME_UNMAPPED_CANONICAL')
    result,rows_read = {},0
    with baseline.bind_current_panels(data_root) as (panel_path,source,recheck):
        verify_source(source,frozen)
        if source['identity']!=manifest['source']['identity'] or source['backtest']['panel_sha256']!=manifest['source']['backtest']['panel_sha256']:
            raise ValueError('POST_SEAL_SOURCE_DRIFT')
        schema = reader.parquet.read_schema(panel_path);actual = old._schema_names(schema)
        fields = ['ts_code','trade_date','open','high','low','close','tradeable_basic','limit_up_approx','limit_down_approx']
        mapping = {n:actual[n] for n in fields};mapping['vol'] = actual.get('vol',actual.get('volume'))
        if not mapping['vol']:raise ValueError('OUTCOME_VOLUME_MISSING')
        for batch in old._code_cohorts(codes,batch_size):
            filters = [[(mapping['ts_code'],'in',batch),
                        (mapping['trade_date'],'>=',old._date_value(schema,mapping['trade_date'],START)),
                        (mapping['trade_date'],'<=',old._date_value(schema,mapping['trade_date'],ASOF))]]
            table = reader.parquet.read_table(panel_path,columns=list(mapping.values()),filters=filters,use_threads=True)
            grouped = old._normalize_panel_rows(table,mapping,frozen['aliases']);rows_read += table.num_rows
            for c,by_code in grouped.items():
                result[c] = {r['trade_date']:r for r in old._deduplicate_alias_history(by_code,frozen['crosswalk_aliases'])}
        recheck()
    return result,{'rows_read':rows_read,'canonical_securities':len(needed),'source':source,
                   'range':[START,ASOF],'projected_columns':mapping,
                   'limit_up_null_rows':sum(not math.isfinite(number(r,'limit_up_approx')) for ds in result.values() for r in ds.values()),
                   'limit_down_null_rows':sum(not math.isfinite(number(r,'limit_down_approx')) for ds in result.values() for r in ds.values())}


def replay(*,scan_dir,act005_root,data_root,output_dir):
    if output_dir.exists() or output_dir.with_name(output_dir.name+'.partial').exists():raise ValueError('OUTPUT_EXISTS')
    manifest,candidates,seal = read_sealed(scan_dir) # BEFORE all future-bar reads.
    sessions,calendar = scheduled_calendar()
    if calendar['year']!=2026:raise ValueError('CALENDAR_YEAR_MISMATCH')
    if not set(candidates.D).issubset(sessions):raise ValueError('SIGNAL_NOT_SCHEDULED_SESSION')
    bars,receipt = read_outcome_bars(data_root,act005_root,manifest,candidates)
    stage = output_dir.with_name(output_dir.name+'.partial');stage.mkdir(parents=True)
    write_json(stage/'outcome_read_receipt.json',receipt)
    outcomes = []
    for case in candidates.to_dict('records'):
        for h in HORIZONS:outcomes.append(standalone(case,bars.get(case['canonical_security_id'],{}),sessions,h))
    if outcomes:
        o = pd.DataFrame(outcomes)
    else:
        # Retain schema for a legitimate zero-trigger canary; no synthetic row
        # is persisted or counted as a signal.
        template = standalone({'episode_id':'','canonical_security_id':'','D':sessions[0],'lane':''},
                              {},sessions,3)
        o = pd.DataFrame({n:pd.Series(dtype='float64' if isinstance(v,(float,int)) else 'object')
                          for n,v in template.items()})
    o.to_parquet(stage/'outcomes.parquet',index=False)
    overall,monthly,tail_removed = [],[],[]
    for policy in POLICIES:
        for rail in RAILS:
            picks = picks_by_day(candidates,policy,rail)
            ids = {r['episode_id'] for rows in picks.values() for r in rows}
            for h in HORIZONS:
                sub = o[o.horizon.eq(h)&o.episode_id.isin(ids)]
                overall.append({'policy':policy,'rail':rail,'horizon':h,**distribution_metrics(sub,[d for d in sessions if START<=d<=ASOF])})
                for month in range(1,12):
                    prefix = f'2026{month:02d}'
                    monthly.append({'policy':policy,'rail':rail,'horizon':h,'month':prefix,
                        **distribution_metrics(sub[sub.D.str.startswith(prefix)],[d for d in sessions if START<=d<=ASOF and d.startswith(prefix)])})
    pd.DataFrame(overall).to_csv(stage/'signal_metrics.csv',index=False)
    pd.DataFrame(monthly).to_csv(stage/'monthly_metrics.csv',index=False)
    for rail in RAILS:
        for policy in ('FULL_B_S030','FULL_B_S050'):
            removed_ids = excluded_episode_ids(candidates,rail,policy)
            removed = o[o.episode_id.isin(removed_ids)&o.status.eq('VALID')]
            removed = removed[removed.net_return_pct.le(-10)|removed.running_close_mdd_pct.le(-10)].copy()
            removed['hard_policy'] = policy;removed['rail'] = rail;tail_removed.append(removed)
    pd.concat(tail_removed,ignore_index=True).to_parquet(stage/'hard_gate_removed_tail_cases.parquet',index=False)
    # Small deterministic examples support review without reopening source bars.
    errors = o[o.status.ne('VALID')].sort_values(['status','D','canonical_security_id','lane','horizon'])
    errors.groupby('status',sort=True).head(3).to_parquet(stage/'representative_unavailable_cases.parquet',index=False)
    navs,lots,summaries = [],[],[]
    for policy in POLICIES:
        for rail in RAILS:
            for h in HORIZONS:
                for k in (3,5):
                    n,l,s = portfolio(candidates,bars,sessions,policy,rail,k,h)
                    navs.extend(n);lots.extend(l);summaries.append(s)
        print(json.dumps({'completed_policy':policy,'strategies':len(summaries)}),flush=True)
    pd.DataFrame(navs).to_parquet(stage/'portfolio_nav.parquet',index=False)
    pd.DataFrame(lots).to_parquet(stage/'portfolio_lots.parquet',index=False)
    pd.DataFrame(summaries).to_csv(stage/'portfolio_summary.csv',index=False)
    # Catch any accidental changed seal/input while outcomes were processing.
    read_sealed(scan_dir)
    outputs = {p.name:old._sha_file(p) for p in stage.iterdir() if p.is_file()}
    report = {'batch':'ACT-010','mode':manifest['mode'],'flags':old.FLAGS,'status':'REPLAY_COMPUTED_PENDING_REVIEW',
              'scan_seal_sha256':old._sha_file(scan_dir/'pre_outcome_seal.json'),'calendar':calendar,
              'code_sha256':{str(Path(__file__)):old._sha_file(Path(__file__))},
              'costs':{'buy':BUY_FEE,'sell':SELL_FEE},'outcome_status_counts':dict(Counter(o.status)),
              'strategies':len(summaries),'monthly_rows':len(monthly),'outputs_sha256':outputs,
              'fits_this_round':{'B':0,'S':0},'inherited_B_fits':12,
              'tail_bins':'net returns and net close MDD: (-20,-10] and <=-20, denominator VALID closed trades',
              'source_PIT':'CANNOT_CONFIRM; frozen source replay, no historical vintage assertion',
              'execution':'RESEARCH_ONLY approximate limits, continuous quantities, no broker fills or capacity certification'}
    write_json(stage/'replay_manifest.json',report);stage.rename(output_dir)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['scan-dir','act005-root','data-root','output-dir']:p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args(argv)
    try:result=replay(**vars(a))
    except Exception as exc:
        print(json.dumps({'status':'FAILED','error':str(exc)}),file=sys.stderr);return 2
    print(json.dumps(result,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
