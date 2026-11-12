"""One bounded P2 repair: first-qualification facts and directly affected projections only."""
from pathlib import Path
import importlib.util,json,hashlib,datetime
import pandas as pd,numpy as np
ROOT=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/monthly_top200_events_20261012_20261111')
sp=importlib.util.spec_from_file_location('monthly_p2',ROOT/'scripts/monthly_analysis.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
a=ROOT/'analysis';events=pd.read_csv(a/'EVENTS.csv',low_memory=False);attacks=pd.read_csv(a/'ATTACK_MANAGEMENT_K.csv',low_memory=False);before=events.copy(deep=True)
failed=pd.read_csv(a/'P2_FAILED_14_COUNTEREXAMPLES.csv');ids=set(failed.event_id)
hist=pd.read_parquet(a/'HISTORY_TARGET_PROJECTION.parquet');early=a/'SPARSE_EARLIER_HISTORY.parquet'
if early.exists():hist=pd.concat([pd.read_parquet(early),hist],ignore_index=True).drop_duplicates(['ts_code','trade_date'])
changed=[]
for sym,eg in events[events.event_id.isin(ids)].groupby('symbol'):
 g=hist[hist.ts_code==sym].sort_values('trade_date').copy();g['vol']=g.volume;g['bbi']=g.BBI;g=g[g.trade_date<=eg.feature_asof.max()]
 facts=m.first_qualifications(g,eg.to_dict('records'),attacks[attacks.symbol==sym].to_dict('records'))
 for ix,e in eg.iterrows():
  for k,v in facts[e.origin_date].items():
   old=e[k]
   if not ((pd.isna(old) and v is None) or old==v):changed.append(dict(event_id=e.event_id,field=k,old=None if pd.isna(old) else int(old),new=v))
   events.at[ix,k]=v;events.at[ix,k+'_known_at']=f'{int(v)}T15:00:00+08:00' if v is not None else None
# Confirm the repair cannot rewrite original anchors or any other stored event fields.
protected=[c for c in events if not c.startswith(('first_origin_qualification','first_attack_qualification','first_any_qualification','first_pullback_recovered_attack'))]
pd.testing.assert_frame_equal(before[protected],events[protected])
m.csvout('EVENTS.csv',events)
look=events.set_index('event_id').first_any_qualification.to_dict();projection_changes=[]
for n in ['EVENT_OBSERVATIONS.csv','FEATURES_ASOF_D.csv','TOP200_STOCK_DAYS.csv','ALL_CANDIDATE_PATHS.csv','SIMILAR_STRUCTURE_CONTROLS.csv','EVENT_LEVEL_PATHS.csv','REPRESENTATIVE_CASES.csv']:
 x=pd.read_csv(a/n,dtype={'O':str,'D':str},low_memory=False)
 if 'first_qualification_date' not in x or 'current_event_id' not in x:continue
 old=x.first_qualification_date.copy();new=[]
 for r in x.itertuples():
  v=look.get(r.current_event_id);new.append(v if v is not None and pd.notna(v) and v<=int(r.D) else np.nan)
 ns=pd.Series(new,index=x.index);mask=~(old.eq(ns)|(old.isna()&ns.isna()))
 for ix in x.index[mask]:projection_changes.append(dict(file=n,O=x.at[ix,'O'],D=x.at[ix,'D'],symbol=x.at[ix,'symbol'],event_id=x.at[ix,'current_event_id'],field='first_qualification_date',old=None if pd.isna(old[ix]) else int(old[ix]),new=None if pd.isna(ns[ix]) else int(ns[ix])))
 if mask.any():x['first_qualification_date']=ns;m.csvout(n,x)
report=ROOT/'reports/近一个月Top200战法与事件研究.md';text=report.read_text();old='未用后续涨跌选对照。';new='“同O非Top200”身份本身使用O收盘后才知道的排名，因此对照是事后分层；“未用后续涨跌”仅指没有再按1/3/5/10日路径二次挑选，不是完全事前对照。';assert old in text;text=text.replace(old,new);report.write_text(text)
# Keep regenerating the report consistent with this clarification.
p=ROOT/'scripts/monthly_analysis.py';src=p.read_text();assert old in src;src=src.replace(old,new);p.write_text(src)
summary={'status':'P2_FACTS_REPAIRED_PENDING_INCREMENTAL_TEST_AND_REVIEW','failed_source_path':'scripts/monthly_analysis.P2_FAILED.py','failed_source_sha256':m.sha(ROOT/'scripts/monthly_analysis.P2_FAILED.py'),'source_after_sha256':m.sha(p),'counterexample_count':len(ids),'event_field_changes':changed,'event_field_change_count':len(changed),'affected_event_count':len({z['event_id'] for z in changed}),'projection_field_changes':projection_changes,'projection_field_change_count':len(projection_changes),'original_anchor_fields_unchanged':True,'unaffected_price_paths_reused':True,'new_fit':0}
m.save('P2_REPAIR_CHANGESET.json',summary);print(json.dumps(summary,ensure_ascii=False))
