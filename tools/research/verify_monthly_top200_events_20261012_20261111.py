"""Frozen-scope mechanical and three-symbol causal verification; no source writes."""
from pathlib import Path
import sys,json,hashlib,importlib.util,ast
import pandas as pd,numpy as np
ROOT=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/monthly_top200_events_20261012_20261111')
sp=importlib.util.spec_from_file_location('monthly_analysis',ROOT/'scripts/monthly_analysis.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
def readcsv(n):return pd.read_csv(ROOT/'analysis'/n,dtype={'D':str,'O':str},low_memory=False)
checks=[]
def ck(n,ok,detail=None):
    checks.append(dict(check=n,pass_=bool(ok),detail=detail));print(n,'PASS' if ok else 'FAIL')
cal=readcsv('../coordination/OBSERVATION_CALENDAR.csv');top=readcsv('TOP200_STOCK_DAYS.csv');cand=readcsv('ALL_CANDIDATE_PATHS.csv');mem=readcsv('CANDIDATE_MEMBERSHIPS.csv');ctrl=readcsv('SIMILAR_STRUCTURE_CONTROLS.csv');f=readcsv('FEATURES_ASOF_D.csv');o=readcsv('OUTCOMES_AFTER_D.csv');obs=readcsv('EVENT_OBSERVATIONS.csv');ev=readcsv('EVENTS.csv');methods=readcsv('34_METHOD_CONTEXTS.csv');ep=readcsv('EVENT_LEVEL_PATHS.csv');daily=readcsv('MONTHLY_DAILY_SUMMARY.csv')
ck('23_sessions_and_exact_O_D_binding',len(cal)==23 and set(zip(top.O,top.D))==set(zip(cal.observation_date_O.astype(str),cal.judgement_date_D.astype(str))))
ck('4600_top200_unique_day_ranks',len(top)==4600 and not top.duplicated(['O','symbol']).any() and all(sorted(g['rank'])==list(range(1,201)) for _,g in top.groupby('O')))
ck('7_published_16_reconstructed_separate',top[top.top200_identity=='PUBLISHED_TOP200'].O.nunique()==7 and top[top.top200_identity=='RECONSTRUCTED_CURRENT_FIXED_RULE_NONPIT'].O.nunique()==16)
ck('ALL_available_candidates_preserved_deduplicated',set(map(tuple,cand[['O','D','symbol']].values))==set(map(tuple,mem[['O','D','symbol']].values)) and not cand.duplicated(['O','D','symbol']).any())
ck('candidate_nonwinners_included',int((~cand.future_in_O_Top200).sum())>0,{'non_O_top200':int((~cand.future_in_O_Top200).sum())})
ck('daily_candidates_reconcile',daily.candidate_stock_days.sum()==len(cand) and all(int(g.candidate_stock_days.iloc[0])==len(cand[cand.O==O]) for O,g in daily.groupby('O')))
ck('feature_dates_and_known_at_le_D',(pd.to_numeric(f.feature_max_date,errors='coerce').dropna()<=f.loc[f.feature_max_date.notna(),'D'].astype(int)).all() and all(pd.isna(x.first_qualification_date) or x.first_qualification_date<=int(x.D) for x in f.itertuples()) and all(pd.isna(x.known_at) or str(x.known_at)[:8]<=x.D for x in f.itertuples()))
ck('no_future_columns_in_FEATURES',not any(x.startswith('future_') for x in f.columns))
ck('event_key_unique_and_attacks_not_new_ids',not ev.event_id.duplicated().any() and all(str(x.event_id)==f'{x.symbol}|UP_REVERSAL_PROXY|{int(x.origin_date)}' for x in ev.itertuples()))
ck('unresolved_current_origin_never_forced',f.loc[f.current_event_state=='CURRENT_EVENT_UNKNOWN','current_event_id'].isna().all())
ck('resolved_current_requires_single_latest',f.loc[f.current_event_id.notna(),'live_origin_count'].eq(1).all() and f.loc[f.current_event_id.notna(),'current_event_state'].eq('SINGLE_LATEST_LIVE_PROXY_ORIGIN').all())
breach=ev.set_index('event_id').first_close_breach_date.to_dict();ck('permanent_breach_not_reactivated',all(pd.isna(breach.get(x.current_event_id)) or breach[x.current_event_id]>int(x.D) for x in f[f.current_event_id.notna()].itertuples()))
ck('event_level_paths_one_per_resolved_event',not ep.current_event_id.duplicated().any() and len(ep)==f.current_event_id.nunique())
ck('event_and_management_dates_causal',all(pd.isna(x.origin_date) or x.origin_date<=int(x.D) for x in obs.itertuples()) and all(pd.isna(x.management_date) or x.management_date<=int(x.D) for x in obs.itertuples()))
keys=set(map(tuple,top[['O','D','symbol']].values))|set(map(tuple,cand[['O','D','symbol']].values));groups=methods.groupby(['O','D','symbol']).method_id.agg(list)
ck('34_contexts_all_Top200_and_candidates',set(groups.index)==keys and all(sorted(z)==list(range(1,35)) for z in groups))
ck('34_methods_never_human_or_success_truth',methods.full_method_verdict.eq('UNKNOWN_NOT_CERTIFIED').all() and methods.human_label.eq('NOT_ASSIGNED').all() and o.success_label.eq('NOT_ASSIGNED').all())
ck('opening_ratio_not_daily_substitution',methods.loc[methods.method_id==18,'context_state'].isin(['SOURCE_GAP','UNKNOWN_OPENING_MINUTE_INPUT_NOT_READ']).all())
ck('controls_exclude_same_O_winners',not (set(map(tuple,ctrl[['O','symbol']].values))&set(map(tuple,top[['O','symbol']].values))))
ck('controls_max3_per_frozen_signature',ctrl.groupby(['O','control_signature']).size().max()<=3)
sessions=m.trading_sessions();loc={d:i for i,d in enumerate(sessions)}
for h in [1,3,5,10]:
    st=f'future_{h}s_status';vals=[f'future_{h}s_close_change',f'future_{h}s_MFE',f'future_{h}s_MAE'];targets=o[f'future_{h}s_target_date'].astype(str).str.replace('.0','',regex=False)
    pending=o[st].str.startswith('PENDING');ck(f'{h}s_maturity_exact_calendar_and_pending_null',all(str(int(x[f'future_{h}s_target_date']))==sessions[loc[x['D']]+h] for x in o.to_dict('records')) and (targets[pending]>'20261111').all() and o.loc[pending,vals].isna().all().all() and o.loc[o[st]=='OBSERVED',vals].notna().all().all())
    ck(f'{h}s_MFE_ge_MAE_and_close_within_range',((o.loc[o[st]=='OBSERVED',vals[1]]>=o.loc[o[st]=='OBSERVED',vals[0]])&(o.loc[o[st]=='OBSERVED',vals[0]]>=o.loc[o[st]=='OBSERVED',vals[2]])).all())
ck('terminal_D_1s_observed_or_gap_others_pending',o.loc[o.D=='20261110','future_1s_status'].isin(['OBSERVED','UNKNOWN_BASE_PRICE','UNKNOWN_MISSING_EXACT_SESSION']).all() and all(o.loc[o.D=='20261110',f'future_{h}s_status'].eq('PENDING_RIGHT_CENSORED').all() for h in [3,5,10]))
# Small, fixed causal sample covers SH/SZ/BJ; append destructive future bars and compare prefix output.
h=pd.read_parquet(ROOT/'analysis/HISTORY_TARGET_PROJECTION.parquet');samples=[]
for suffix in ['.SH','.SZ','.BJ']:
    r=f[(f.symbol.str.endswith(suffix))&(f.source_state=='QUALIFIED_EXACT_D')].sort_values(['D','symbol']).iloc[0];g=h[h.ts_code==r.symbol].copy();D=int(r.D);gg=g.copy();future=gg.trade_date>D
    for col in ['open','high','low','close','volume']:gg.loc[future,col]=gg.loc[future,col]*1234
    a=m.analyze_symbol((r.symbol,g,[D]));b=m.analyze_symbol((r.symbol,gg,[D]));ck('causal_future_perturbation_'+suffix,m.json.dumps(a,sort_keys=True,default=str)==m.json.dumps(b,sort_keys=True,default=str));samples.append(dict(symbol=r.symbol,D=D))
    rr=o[(o.symbol==r.symbol)&(o.D==r.D)].iloc[0];base=h[(h.ts_code==r.symbol)&(h.trade_date==D)].iloc[0];td=sessions[loc[r.D]+1];nextbar=h[(h.ts_code==r.symbol)&(h.trade_date==int(td))]
    if rr.future_1s_status=='OBSERVED':ck('exact_next_close_path_'+suffix,np.isclose(rr.future_1s_close_change,nextbar.iloc[0].close/base.close-1))
# Reject fitting and network/subprocess mutation calls in the one-time analysis source.
tree=ast.parse((ROOT/'scripts/monthly_analysis.py').read_text());bad=[]
for node in ast.walk(tree):
    if isinstance(node,ast.Call):
        name=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
        if name in {'fit','fit_transform','partial_fit','urlopen','request','post','Popen','system'}:bad.append(name)
ck('zero_fit_and_no_new_market_collection_calls',not bad,bad)
ck('frozen_config_hash_unchanged',m.sha(ROOT/'analysis/FROZEN_ANALYSIS_CONFIG.json')==m.read(ROOT/'analysis/CONFIG_HASH.json')['sha256'])
identity=m.read(ROOT/'analysis/SOURCE_READ_IDENTITY.json');st=Path(identity['panel_path']).stat();ck('fixed_panel_stat_unchanged',st.st_size==identity['stat']['size'] and st.st_mtime_ns==identity['stat']['mtime_ns'])
result={'status':'PASS' if all(x['pass_'] for x in checks) else 'FAIL','checks':checks,'sample_scope':samples,'new_fit':0,'scope':'MECHANICAL_ALL_REQUESTED_COVERAGE_AND_THREE_SYMBOL_CAUSAL_PATH_SAMPLE; NOT_INDEPENDENT_REVIEW'}
(ROOT/'analysis/TARGETED_CHECKS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(0 if result['status']=='PASS' else 1)
