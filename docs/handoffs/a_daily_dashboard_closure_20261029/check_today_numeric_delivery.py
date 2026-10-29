"""Mechanical final coverage, immutable-byte audit and fifth ledger projection.

Consumes completed rows only. No formula, history, provider, Futu or service call.
"""
from pathlib import Path
import hashlib,json,sys
FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
GROUPS=('original','nav_smallk','nav_pullback','nav_breakout')
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def ref(p):p=Path(p);return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
def read(r):
 p=Path(r['path']);raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==r['sha256'],str(p);return json.loads(raw)
def save(p,v):
 p=Path(p);raw=canonical(v)+b'\n'
 if p.exists():assert p.read_bytes()==raw,'MECHANICAL_OUTPUT_ALREADY_EXISTS_DIFFERENT:'+str(p)
 else:p.write_bytes(raw)
 return ref(p)
if __name__=='__main__':
 base=Path(sys.argv[1]);out=base/'today_full_r1';pins=json.loads((base/'TODAY_FULL_INPUTS.json').read_text());result=json.loads((out/'RESULT.json').read_text());manifest=read(result['result']['manifest']);product=read(manifest['artifact']);universe=set(pins['universe']);assert len(universe)==5808
 assert json.loads((out/'RUN_BINDING.json').read_text())==pins
 for r in pins['code']:read_bytes=Path(r['path']).read_bytes();assert hashlib.sha256(read_bytes).hexdigest()==r['sha256']
 assert product['data_date']=='20261029' and product['source_generation']==pins['generation'] and product['source_identity']['input_sha256']==pins['input_sha256'] and product['sample_only'] is False
 assert set(product['processed_universe'])==universe==set(product['row_refs']) and product['processed_count']==5808==product['source_universe_count']
 cut=json.loads((out/'INTERRUPTED_CHECKPOINT_CUT.json').read_text())
 for r in cut['checkpoints']:assert ref(r['path'])['sha256']==r['sha256'],'REUSED_CHECKPOINT_CHANGED:'+r['symbol']
 counts={g:{'TRUE':0,'FALSE':0,'UNKNOWN':0} for g in GROUPS};true_symbols=set();unknown_symbols=set();q_counts={};isolated=[];fifth=[];main_rows=[];candidate_pending=[]
 gate_fields=('baseline','after_redgreen','redgreen_gate','anchor_applicability','risk_clear_gate','status','after_risk','reasons')
 for symbol in sorted(universe):
  rowref=product['row_refs'][symbol];row=read(rowref);assert row['symbol']==symbol and row['data_date']=='20261029'
  assert row['RESEARCH_ONLY'] is True and all(row[k] is False for k in ('production_allowed','buy_gate_updated','orders_sent'))
  e=row['evaluation'];states={g:e['groups'][g]['status'] for g in GROUPS};true={g for g,s in states.items() if s=='TRUE'};unknown={g for g,s in states.items() if s=='UNKNOWN'}
  assert set(filter(None,row['groups'].split('|')))==true and set(filter(None,row['pending_groups'].split('|')))==unknown
  for g,s in states.items():assert s in counts[g];counts[g][s]+=1
  qualification=row['qualification']['status'];q_counts[qualification]=q_counts.get(qualification,0)+1
  if row.get('reasons','').startswith('SOURCE_ISOLATED:'):isolated.append(dict(symbol=symbol,reason=row['reasons'],row_ref=rowref))
  if unknown:unknown_symbols.add(symbol)
  if true:
   assert qualification=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH' and e['risk']['status']=='TRUE','CANDIDATE_SOURCE_OR_RISK_GATE_FAILED:'+symbol
   assert all(e['groups'][g]['after_risk']=='TRUE' and e['groups'][g]['risk_clear_gate']=='TRUE' for g in true)
   true_symbols.add(symbol)
   if unknown:candidate_pending.append(dict(symbol=symbol,pending_groups=sorted(unknown),row_ref=rowref))
  risk=e.get('risk',{});risk_state=risk.get('status','UNKNOWN')
  if risk_state=='FALSE':category='RISK';label='数值风险门否决'
  elif unknown or qualification!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':category='PENDING';label='待核'
  elif true:category='CANDIDATE';label='候选'
  elif any(e['groups'][g].get('baseline')=='TRUE' for g in GROUPS):category='NOT_PASSED';label='未通过'
  else:category='NO_HIT';label='未命中'
  entry=dict(symbol=symbol,display_name=row['display_name'],data_date='20261029',category=category,category_zh=label,qualification=row['qualification'],final_status_by_group=states,pending_groups=sorted(unknown),groups={g:{k:v for k,v in e['groups'][g].items() if k in gate_fields} for g in GROUPS},numeric_risk_proxy_status=risk_state,risk_reason=risk.get('reason'),risk_proxy_status=risk.get('proxy_status'),risk_event_count=len(risk.get('events',[])),reasons=row['reasons'],full_row_ref=rowref,full_risk_field_path='evaluation.risk',full_risk_scan_field_path='evaluation.risk_scan',eligible_candidate=bool(true),candidate_groups=sorted(true),numeric_risk_proxy_only=True)
  main_rows.append(entry)
  if not true or unknown:fifth.append(entry)
 candidate_symbols=[r['symbol'] for r in product['rows']];assert len(candidate_symbols)==len(set(candidate_symbols))==product['unique_count'] and set(candidate_symbols)==true_symbols
 assert all(sum(v.values())==5808 for v in counts.values());assert {g:counts[g]['TRUE'] for g in GROUPS}==product['group_counts'];assert len(unknown_symbols)==product['unknown_count']
 noncandidate=universe-true_symbols
 assert noncandidate<=set(r['symbol'] for r in fifth) and len(noncandidate)+len(true_symbols)==5808
 assert all(r['eligible_candidate']==(r['symbol'] in true_symbols) for r in main_rows)
 category_counts={key:sum(r['category']==key for r in fifth) for key in ('RISK','PENDING','NOT_PASSED','NO_HIT')}
 main_ledger=save(out/'ALL_5808_STATE_RISK_PENDING_LEDGER.json',dict(schema_version='a_share_r5_all_state_ledger.v1',data_date='20261029',source_generation=pins['generation'],manifest=result['result']['manifest'],artifact=manifest['artifact'],processed_count=5808,rows=main_rows,**FLAGS))
 ledger=save(out/'FIFTH_RISK_PENDING_DISCLOSURE.json',dict(schema_version='a_share_r5_fifth_disclosure.v1',data_date='20261029',observation_group='1030',manifest=result['result']['manifest'],artifact=manifest['artifact'],processed_count=5808,candidate_count=len(true_symbols),fifth_count=len(fifth),category_counts=category_counts,rows=fifth,candidate_overlap_count=sum(r['eligible_candidate'] for r in fifth),noncandidate_exclusion_set=sorted(noncandidate),noncandidate_exclusion_count=len(noncandidate),candidate_other_group_pending=candidate_pending,main_all_5808_ledger=main_ledger,scope_note='Fifth disclosure can overlap TRUE-union candidates through other-group UNKNOWN; eligible_candidate remains true and these stocks are never globally vetoed. Only noncandidate_exclusion_set lacks any TRUE group.',no_history_recalculation=True,**FLAGS))
 check=save(out/'MECHANICAL_FINAL_CHECK.json',dict(status='PASS_MECHANICAL_COVERAGE_AND_BINDINGS' if not isolated else 'SOURCE_ISOLATED_REQUIRES_REVIEW',data_date='20261029',source_generation=pins['generation'],universe_count=5808,processed_count=5808,all_row_hashes_checked=5808,reused_checkpoint_hashes_unchanged=len(cut['checkpoints']),unique_count=len(true_symbols),three_value_counts=counts,unknown_stocks=len(unknown_symbols),qualification_counts=q_counts,source_isolated=isolated,main_all_5808_ledger=main_ledger,fifth_ledger=ledger,fifth_category_counts=category_counts,candidate_other_group_pending_count=len(candidate_pending),math_recomputed=False,independent_review='PENDING',**FLAGS))
 print(json.dumps(dict(mechanical_check=check,fifth_ledger=ledger,group_counts=product['group_counts'],unique_count=len(true_symbols),unknown_stocks=len(unknown_symbols),fifth_count=len(fifth),fifth_category_counts=category_counts,source_isolated=len(isolated)),ensure_ascii=False))
