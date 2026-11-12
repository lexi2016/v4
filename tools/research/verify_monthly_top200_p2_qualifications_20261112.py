"""Incremental P2-only verification. Reuse unchanged 37 checks, 85 refs and reviewer checks."""
from pathlib import Path
import importlib.util,json,hashlib,sys
import pandas as pd,numpy as np
ROOT=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/monthly_top200_events_20261012_20261111');A=ROOT/'analysis'
sp=importlib.util.spec_from_file_location('monthly_p2',ROOT/'scripts/monthly_analysis.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
checks=[]
synthetic_only='--synthetic-only' in sys.argv
def ck(name,ok,detail=None):
 checks.append(dict(check=name,pass_=bool(ok),detail=detail));print(name,'PASS' if ok else 'FAIL')
def same(x,y):return (pd.isna(x) and (y is None or pd.isna(y))) or x==y
h=pd.read_parquet(A/'HISTORY_TARGET_PROJECTION.parquet');early=A/'SPARSE_EARLIER_HISTORY.parquet'
if early.exists():h=pd.concat([pd.read_parquet(early),h],ignore_index=True).drop_duplicates(['ts_code','trade_date'])
old=pd.read_csv(A/'P2_FAILED_14_COUNTEREXAMPLES.csv');ev=pd.read_csv(A/'EVENTS.csv',low_memory=False);new=ev[ev.event_id.isin(set(old.event_id))];eng=m.engine();oracles=[]
for e in ([] if synthetic_only else new.itertuples()):
 g=h[(h.ts_code==e.symbol)&(h.trade_date<=e.feature_asof)].sort_values('trade_date').copy();g['vol']=g.volume;g['bbi']=g.BBI;first_origin=None;first_attack=None;first_any=None;first_recovery=None;touch=None
 for D in g[g.trade_date>e.origin_date].trade_date:
  result=eng.evaluate(g,int(D),m.R3CFG);event=next((z for z in result['events'] if z['origin_date']==e.origin_date),None)
  if not event:continue
  if event['origin_retest_status']=='TRUE' and first_origin is None:first_origin=int(D)
  if event['attack_retest_status']=='TRUE' and first_attack is None:first_attack=int(D)
  if event['origin_retest_status']=='TRUE' or event['attack_retest_status']=='TRUE':
   if first_any is None:first_any=int(D)
   if touch is None:touch=int(D)
  if touch and D>touch and any(a['origin_date']==e.origin_date and a['attack_date']==D for a in result['attacks']) and event['first_close_breach_date'] is None:
   if first_recovery is None:first_recovery=int(D)
 oracles.append(dict(event_id=e.event_id,oracle_first_origin=first_origin,oracle_first_attack=first_attack,oracle_first_any=first_any,oracle_first_recovery=first_recovery))
 ck('real_prefix_oracle_'+e.event_id,all(same(x,y) for x,y in [(e.first_origin_qualification,first_origin),(e.first_attack_qualification,first_attack),(e.first_any_qualification,first_any),(e.first_pullback_recovered_attack,first_recovery)]),oracles[-1])
if not synthetic_only:
 e=new[new.event_id=='000669.SZ|UP_REVERSAL_PROXY|20260812'].iloc[0];ck('000669_first_attack_and_any_20260831',e.first_attack_qualification==20260831 and e.first_any_qualification==20260831)
 g=h[h.ts_code=='000669.SZ'].copy();g['vol']=g.volume;g['bbi']=g.BBI;r=eng.evaluate(g,20260828,m.R3CFG);v=next(e for e in r['events'] if e['origin_date']==20260812);ck('000669_20260828_engine_rejects_attack_today',v['attack_retest_reason']=='ATTACK_TODAY_NO_POST_ATTACK_BAR' and v['origin_retest_status']=='FALSE')
# Synthetic helper fixture isolates management timing and UNKNOWN without changing the engine rules.
dates=[20260803,20260804,20260805,20260806,20260807,20260810,20260811,20260812,20260813]
base=[(10,15,5,12,100),(12,21,11,20,200),(19,20,16,17,240),(17,18,16,16,240),(16,18,16,17,240),(17,20,16,18,150),(18,19,16,17,100),(17,21,16,19,160),(18,20,16,18,90)]
def fixture(unknown=False,origin_eligible=False):
 bars=[dict(trade_date=d,open=o,high=hi,low=lo,close=c,vol=v) for d,(o,hi,lo,c,v) in zip(dates,base)];origin=dict(origin_date=dates[0],origin_volume=100,origin_low=5,origin_high=15,first_close_breach_date=None,unknown_attack_dates=str(dates[5]) if unknown else '')
 if origin_eligible:
  bars[0].update(high=23,close=22,vol=1000);origin.update(origin_volume=1000,origin_high=23)
  for j in range(1,5):bars[j]['vol']=2000
 attacks=[]
 for ix in ([1,7] if unknown else [1,5,7]):
  b=bars[ix];attacks.append(dict(origin_date=dates[0],attack_date=dates[ix],attack_volume=b['vol'],attack_high=b['high'],attack_low=b['low']))
 return pd.DataFrame(bars),origin,attacks
bars,origin,ats=fixture();fq=m.first_qualifications(bars.iloc[:6], [origin],ats)[dates[0]];ck('new_attack_today_never_retests_old_management',fq['first_attack_qualification'] is None and fq['first_any_qualification'] is None)
fq=m.first_qualifications(bars.iloc[:7],[origin],ats)[dates[0]];ck('first_post_new_attack_bar_can_qualify',fq['first_attack_qualification']==dates[6])
bars,origin,ats=fixture(unknown=True);fq=m.first_qualifications(bars.iloc[:7],[origin],ats)[dates[0]];ck('unknown_attack_today_and_later_blocks_old_management',fq['first_attack_qualification'] is None and fq['first_any_qualification'] is None)
fq=m.first_qualifications(bars,[origin],ats)[dates[0]];ck('unknown_persists_until_confirmed_attack_and_following_bar',fq['first_attack_qualification']==dates[8])
bars,origin,ats=fixture(origin_eligible=True);fq=m.first_qualifications(bars.iloc[:6],[origin],ats)[dates[0]];ck('attack_today_does_not_veto_independent_origin_retest',fq['first_origin_qualification']==dates[5] and fq['first_any_qualification']==dates[5] and fq['first_attack_qualification'] is None)
if not synthetic_only:
 # Mechanical full origin ledger check is directly implicated by the P2 bug.
 att=pd.read_csv(A/'ATTACK_MANAGEMENT_K.csv',low_memory=False);joined=ev.merge(att[['symbol','origin_date','attack_date']],on=['symbol','origin_date']);ck('no_first_attack_qualification_on_same_origin_attack_day',not (joined.first_attack_qualification==joined.attack_date).any())
 change=m.read(A/'P2_REPAIR_CHANGESET.json');ck('14_events_17_date_fields_changed',change['affected_event_count']==14 and change['event_field_change_count']==17);ck('recovery_dates_actually_rechecked_unchanged',all(z['field']!='first_pullback_recovered_attack' for z in change['event_field_changes']))
 ck('all_projected_monthly_first_qualification_fields_unchanged',change['projection_field_change_count']==0)
 pre={z['path']:z for z in m.read(A/'P2_PRE_REPAIR_ARTIFACT_HASHES.json')};unchanged=['analysis/OUTCOMES_AFTER_D.csv','analysis/ATTACK_MANAGEMENT_K.csv','analysis/HISTORY_TARGET_PROJECTION.parquet','analysis/PAIR_BINDING.json','analysis/FROZEN_ANALYSIS_CONFIG.json','analysis/TARGETED_CHECKS.json','analysis/SOURCE_REFERENCE_CHECKS.json','analysis/TOP200_STOCK_DAYS.csv','analysis/ALL_CANDIDATE_PATHS.csv','analysis/EVENT_OBSERVATIONS.csv','analysis/FEATURES_ASOF_D.csv','analysis/SIMILAR_STRUCTURE_CONTROLS.csv','analysis/EVENT_LEVEL_PATHS.csv','analysis/REPRESENTATIVE_CASES.csv']
 ck('all_unaffected_paths_source_anchors_and_projections_byte_identical',all(m.sha(ROOT/p)==pre[p]['sha256'] for p in unchanged),unchanged)
 # Check date facts and known_at move together on the 14 affected rows.
 ck('updated_date_known_at_consistent',all(pd.isna(r[k]) and pd.isna(r[k+'_known_at']) or pd.notna(r[k]) and r[k+'_known_at']==f'{int(r[k])}T15:00:00+08:00' for r in new.to_dict('records') for k in ['first_attack_qualification','first_any_qualification']))
if synthetic_only:
 prior=m.read(A/'P2_INCREMENTAL_CHECKS_FIRST_ATTEMPT.json');names={z['check'] for z in checks};checks=[z for z in prior['checks'] if z['check'] not in names]+checks;oracles=prior['real_oracles']
result={'status':'PASS' if all(x['pass_'] for x in checks) else 'FAIL','checks':checks,'real_oracles':oracles,'scope':'P2_ONLY;REUSE_37_TARGETED_85_SOURCE_AND_OTHER_REVIEWER_PASS','new_fit':0,'source_sha256':m.sha(ROOT/'scripts/monthly_analysis.py'),'reused_prior_real_oracles':synthetic_only};m.save('P2_INCREMENTAL_CHECKS.json',result);raise SystemExit(0 if result['status']=='PASS' else 1)
