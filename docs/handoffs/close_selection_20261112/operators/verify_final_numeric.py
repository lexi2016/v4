"""Mechanical coverage/hash/zero-fit and actual-output invariants, no rerun."""
import json,pathlib,hashlib,math,collections,time
import numpy as np,pandas as pd
N=pathlib.Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def main():
 f=json.loads((N/'RUN_FREEZE.json').read_text());scope=set(f['scope']);proofs=list((N/'engine_proofs').glob('*.json'));assert {p.stem for p in proofs}==scope
 calls=0;accepted=0;cpu=0;kernel=0;candidate=set();pending=0;qualification=collections.Counter()
 for p in proofs:
  x=json.loads(p.read_text());assert x['symbol']==p.stem and x['target_date']==20261112 and x['generation']==f['source_identity']['generation']and x['new_fit_count']==0 and x['fresh_namespace']
  assert sha(x['row']['path'])==x['row']['sha256'];row=json.loads(pathlib.Path(x['row']['path']).read_text());assert row['symbol']==p.stem and row['data_date']=='20261112';assert all(row[k]==v for k,v in {'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}.items())
  assert 'same_day_formula_reuse'not in row
  if row['qualification']['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':assert x['engine_compute_calls']==1;accepted+=1
  if row['groups']:candidate.add(p.stem)
  pending+=bool(row['pending_groups']);qualification[row['qualification']['status']]+=1;calls+=x['engine_compute_calls'];cpu+=x['cpu_seconds'];kernel+=x['original_kernel_called']
 assert kernel==len(scope)==5809 and calls==5536 and accepted==5536 and pending==930
 ledger=pd.read_csv(N/'data/FULL_UNIVERSE_FRESH_LEDGER.csv',dtype={'security_code':str});features=pd.read_csv(N/'data/D12_ALL_CANDIDATE_FEATURES_32.csv',dtype={'security_code':str},float_precision='round_trip');scores=pd.read_csv(N/'outputs/D12_ALL_ROLE_SCORES_LONG.csv',dtype={'security_code':str},float_precision='round_trip');facts=pd.read_csv(N/'outputs/ALL_CANDIDATE_STRUCTURE_FACTS.csv',dtype={'security_code':str},float_precision='round_trip')
 assert len(ledger)==len(scope)and set(ledger.security_code)==scope and not ledger.security_code.duplicated().any()
 assert set(features.security_code)==set(facts.security_code)==set(scores.security_code)==candidate and len(features)==len(facts)==len(candidate)==341
 assert set(features.trade_date)==set(scores.trade_date)=={'2026-11-12'} and len(scores)==341*4 and not scores.duplicated(['security_code','role']).any()
 assert set(scores.role)=={'activity','reversal_key','buy_point','risk'}and np.isfinite(scores[['fold_1','fold_2','fold_3','mean','min','max']].to_numpy(dtype=float)).all()
 delta=[]
 for r in scores.itertuples():
  v=[r.fold_1,r.fold_2,r.fold_3];delta.append(abs(r.mean-sum(v)/3));assert r.min==min(v)and r.max==max(v)and bool(r.threshold_0_5_disagreement)==(min(v)<.5<=max(v))
 assert max(delta)<=2.3e-16
 old=json.loads((N/'MODEL_ENTRY_INSPECTION.json').read_text())
 for r in old['sources'].values():assert sha(r['path'])==r['sha256']
 for phase in ('CANARY','REMAINING'):
  r=json.loads((N/'validation'/(phase+'_FEATURE_AND_SCORE_PASS.json')).read_text());assert r['fit_attempts']==r['inference']['fit_attempts']==0
  for key,h in r['inference']['model_sha256'].items():assert h==old['sources'][key]['sha256']
 assert json.loads((N/'FIVE_OPPORTUNITY_COVERAGE.json').read_text())['type_rows']==341*5
 risk=json.loads((N/'SHORTLIST_IDENTITY_RISK_CHECK.json').read_text());assert risk['count']==20 and risk['matching_names']==19 and risk['ST_marked']==1
 assert json.loads((N/'REVIEW_QUEUE_CURRENT.json').read_text())['counts']['A_PRIORITY_REVIEW_PENDING']==0
 charts=json.loads((N/'outputs/review_charts/MANIFEST.json').read_text());assert not charts['errors']and not charts['gaps']and len(charts['items'])==16
 for x in charts['items']:
  assert sha(x['html'])==x['html_sha256']and sha(x['png'])==x['png_sha256']and x['formula_compute_calls_added']==0
 result=dict(status='PASS_MECHANICAL_FINAL_SCOPE',processed=5809,fresh_kernel_invocations=kernel,actual_formula_engine_calls=calls,qualification_unknown=5809-accepted,pending_at_least_one_group_UNKNOWN=pending,candidates=341,eligible_scored=341,role_rows=len(scores),head_outputs=341*12,canary_head_outputs_total=3*12,additional_canary_heads_outside_candidate=(3-len(candidate&{'601689.SH','002371.SZ','920001.BJ'}))*12,canary_candidate_overlap=len(candidate&{'601689.SH','002371.SZ','920001.BJ'}),fit_attempts=0,model_weights_preprocessors_unchanged=True,model_mean_max_numeric_difference=max(delta),scope_rows_and_hashes_checked='5809/5809',source_generation=f['source_identity']['generation'],identity_shortlist_checked=20,identity_name_conflict_ST=1,effective_A_count=0,original_charts_checked=16,first_public_anchor='CANNOT_CONFIRM',historical_PIT='CANNOT_CONFIRM',model_generalization_or_calibration='CANNOT_CONFIRM',task_cpu_seconds=cpu)
 (N/'FINAL_NUMERIC_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':main()
