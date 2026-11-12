"""Reuse exact D11 structure facts/attribution semantics on actual fresh D12 inputs.
Queue letters below are research dispositions. Original support-type A/B/C/D
columns remain independent and are never reinterpreted as buy eligibility.
"""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import gzip,hashlib,importlib.util,json,pathlib,sys,time
import numpy as np,pandas as pd
N=pathlib.Path(__file__).resolve().parents[1];ADAPTER=pathlib.Path('/Users/lexi/Desktop/学习/Z哥方法论/SELECTION_D20261112_WORKTREE/05_EXPERIMENTS/SELECTION_D20261112')
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def save(p,x):pathlib.Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def module(p,name):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def truth(x):return str(x)=='True'
def correct(r):
 relation=r['owner_anchor_relation_to_current_episode'];old=r['preliminary_disposition']
 if relation.endswith('_OVERLAPPING_ORIGIN'):state='UNKNOWN_OVERLAPPING_ORIGINS';why='同日两代理重合；既有活动原锚并存，当前轮起点归属未证实'
 elif relation.endswith('_NEW_AFTER_CLOSE_BREACH'):state='BOUNDED_NEW_TRIGGER_AFTER_OBSERVED_OLD_BREACH';why='120根窗内旧锚均有收盘破低后出现新价格触发；左截断，独立事件仍待逐日复核'
 elif relation.endswith('_FIRST_DISCOVERED'):state='UNKNOWN_FIRST_DISCOVERED_LEFT_CENSORED';why='仅为120根窗内首次发现，窗前关系未知'
 else:state='UNKNOWN_OR_NOT_CONCORDANT';why='当前轮归属未由两种代理一致给出；不得以任一旧锚存活补齐'
 r['current_episode_attribution_v2']=state;r['current_episode_attribution_reason_v2']=why;current=old
 if old=='PRIORITY_REVIEW' and state!='BOUNDED_NEW_TRIGGER_AFTER_OBSERVED_OLD_BREACH':current='UNKNOWN_CURRENT_EVENT_ATTRIBUTION'
 if old=='EXCLUDED_OWNER_CLOSE_BREACH':current='OWNER_ANCHOR_INVALID_NEW_EPISODE_UNRESOLVED'
 r['preliminary_disposition_v2']=current;r['root_review_state']='NOT_HUMAN_REVIEWED';r['first_public_original_anchor']='UNKNOWN';r['confirmed_buy_point']=False
 return r

def main():
 t=time.perf_counter();assert json.loads((N/'NUMERIC_COMPLETION.json').read_text())['NEW_FIT_COUNT']==0
 b=json.loads((N/'SOURCE_ADAPTER_BINDING.json').read_text());assert sha(b['files']['structure_d12.py']['path'])==b['files']['structure_d12.py']['sha256']
 old=json.loads(pathlib.Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/selection_d20261111_20261112_111724/plan/INPUT_AND_IDENTITY_FREEZE.json').read_text());src=old['source_files']
 for key in ('R3_1_source','R3_1_config'):assert sha(src[key]['path'])==src[key]['sha256']
 facts=module(ADAPTER/'structure_d12.py','original_structure_date_adapter');facts.RUN=N;facts.SOURCE=N/'data';facts.ASOF=20261112
 r3=module(src['R3_1_source']['path'],'unchanged_r3_1');cfg=json.loads(pathlib.Path(src['R3_1_config']['path']).read_text());contexts={x['symbol']:x for x in json.load(gzip.open(N/'data/STRUCTURE_CONTEXT.json.gz','rt'))['rows']}
 cand=pd.read_csv(N/'data/CANDIDATES.csv',dtype=str).fillna('');scores=pd.read_csv(N/'outputs/D12_ALL_ROLE_SCORES_WIDE.csv',dtype={'security_code':str},float_precision='round_trip').set_index('security_code');keys=set(cand.symbol);cands={r['symbol']:r for r in cand.to_dict('records')};assert set(contexts)==keys==set(scores.index)
 frame=pd.concat([pd.read_parquet(N/'data/CANARY_PREFIX.parquet'),pd.read_parquet(N/'data/REMAINING_PREFIX.parquet')],ignore_index=True);frame=frame[frame.ts_code.isin(keys)].copy();assert not frame.duplicated(['ts_code','trade_date']).any();frame.trade_date=frame.trade_date.astype(str)
 results=[];collections={'EVENTS':[],'ATTACKS':[],'MANAGEMENT':[],'OBSERVATIONS':[]};bars=[]
 for symbol,g in frame.groupby('ts_code',sort=True):
  c=cands[symbol];ctx=contexts[symbol];assert c['computation_row_sha256']==ctx['computation_row_sha256']
  row,ev,at,ch,ob=facts.make_one(c,ctx,g,scores.loc[symbol].to_dict(),r3,cfg);correct(row)
  prev=g.sort_values('trade_date');prev=prev[prev.trade_date<'20261112'].tail(20);dates=prev.trade_date.tolist();row.update(prev20_volume_window_start=dates[0]if dates else None,prev20_volume_window_end=dates[-1]if dates else None,prev20_volume_window_count=len(prev),prev20_valid_volume_count=int(prev.volume.notna().sum()),volume_unit_qualification='QFQ_EVENT_VOLUME; native share/lot unit not certified',source_generation=json.loads((N/'RUN_FREEZE.json').read_text())['source_identity']['generation'])
  results.append(row)
  for name,data in zip(collections,(ev,at,ch,ob)):collections[name].extend(data)
  bars.append(g.sort_values('trade_date').tail(120))
 result=pd.DataFrame(results);assert len(result)==len(keys);result.to_csv(N/'outputs/ALL_CANDIDATE_STRUCTURE_FACTS.csv',index=False,float_format='%.17g');pd.concat(bars).to_csv(N/'data/ALL_CANDIDATES_LAST120_BARS.csv',index=False,float_format='%.17g')
 for name,data in collections.items():pd.DataFrame(data).to_csv(N/'outputs'/('R3_'+name+'_120.csv'),index=False,float_format='%.17g')
 # Same fixed hierarchy as yesterday: structural/episode evidence first,
 # activation/data completeness then display-only old buy-role mean; no blend.
 rank=result.copy();rank['bounded_episode_and_nonweak']=rank.current_episode_attribution_v2.eq('BOUNDED_NEW_TRIGGER_AFTER_OBSERVED_OLD_BREACH')&rank.engineering_direction_nonweak;rank['has_support_clue']=rank[['A_candidate_key_retest','B_prior_touch_current_recovered','C_later_attack_retest']].any(axis=1)
 rank=rank.sort_values(['bounded_episode_and_nonweak','has_support_clue','key_data_volume_complete','buy_point_mean','security_code'],ascending=[False,False,False,False,True],na_position='last');rank['research_review_order']=range(1,len(rank)+1)
 queues={
 'A_PRIORITY_REVIEW_PENDING':rank[rank.preliminary_disposition_v2.eq('PRIORITY_REVIEW')&~rank.is_ST_name].head(5),
 'B_WAIT_CONFIRMATION':rank[rank.has_support_clue&~rank.is_ST_name&rank.owner_support_state.isin(['UNBROKEN_OBSERVED','INTRADAY_BREACH_RECLAIM'])&~rank.preliminary_disposition_v2.eq('PRIORITY_REVIEW')].head(10),
 'C_SPECIAL_STRUCTURE_OBSERVATION':rank[rank.D_any_turn_proxy&~rank.is_ST_name&~rank.has_support_clue],
 'EXCLUSIONS_OR_INVALID_ANCHOR':rank[rank.is_ST_name|rank.preliminary_disposition_v2.eq('OWNER_ANCHOR_INVALID_NEW_EPISODE_UNRESOLVED')],
 'UNKNOWN':rank[rank.preliminary_disposition_v2.str.startswith('UNKNOWN')],
 }
 for name,rows in queues.items():rows.to_csv(N/'outputs'/('QUEUE_'+name+'.csv'),index=False,float_format='%.17g')
 rank.to_csv(N/'outputs/ALL_CANDIDATES_RANKED_WITH_UNKNOWN.csv',index=False,float_format='%.17g')
 selected=[]
 for label,table in list(queues.items())[:3]:
  for row in table.to_dict('records'):
   if row['security_code']not in {x['security_code']for x in selected}:
    selected.append(dict(security_code=row['security_code'],name=row['name'],queue=label,actual_human_review='PENDING',structure_context_csv=str(N/'outputs/ALL_CANDIDATE_STRUCTURE_FACTS.csv')))
 # C is not capped by invented rule; chart priority is bounded initial A/B
 # queue plus first 5 C for human selection; complete C facts remain available.
 chart=[]
 for row in selected:
  if row['queue'].startswith(('A_','B_'))or sum(x['queue'].startswith('C_')for x in chart)<5:chart.append(row)
 save(N/'REVIEW_QUEUE.json',dict(status='MACHINE_FACTS_READY_HUMAN_REVIEW_PENDING',counts={k:len(v)for k,v in queues.items()},queue_definitions='Research dispositions, separate from original A/B/C/D support types; old score is display/tie-break only, never win rate',chart_priority=chart,candidates=len(result),disposition_counts=result.preliminary_disposition_v2.value_counts().to_dict(),attribution_counts=result.current_episode_attribution_v2.value_counts().to_dict(),fit_count=0,wall_seconds=time.perf_counter()-t));print(json.dumps(dict(status='STRUCTURE_AND_QUEUES_READY',candidates=len(result),queues={k:len(v)for k,v in queues.items()})),flush=True)
if __name__=='__main__':main()
