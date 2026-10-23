"""Read-only signal metadata join: official observed names, no price or signal recalculation."""
import argparse,csv,hashlib,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rows(p):
 with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def main(cp):
 from network_execution_guard import require_registered_start
 gate=require_registered_start(cp);c=json.loads(Path(cp).read_text());b=c['input_identity'];out=Path(c['output_directory']);source=Path(b['selection_directory']);matrix={r['source_key']:r for r in rows(b['matrix'])};evidence={}
 for r in rows(b['identity_projection']):
  key=r['ts_code'];m=matrix[key];new=m['observed_official_new_code'];canonical=(new+'.BJ') if m['observed_official_old_code']==key.split('.')[0] and new else key;name=r['source_short_name'];ref={'path':r['evidence_path'],'sha256':r['evidence_sha256'],'source_key':key,'source_name_field':'source_short_name'}
  if name in ('','null'):
   x=json.loads(r['source_evidence_json'])
   if isinstance(x,dict):name=x.get('source_short_name');ref={'path':x.get('source_path'),'sha256':x.get('source_sha256'),'source_key':key,'source_name_field':'source_evidence_json.source_short_name'}
  if name and name!='null':
   assert sha(ref['path'])==ref['sha256'];evidence.setdefault(canonical,[]).append({'name':name,'source':ref})
 updates=[];outputs={}
 for p in sorted(source.glob('*.csv')):
  data=rows(p)
  if not data:continue
  for r in data:
   if 'name' not in r or r['name']:continue
   code=r.get('canonical_code') or r.get('code');ev=evidence.get(code,[]);names={x['name'] for x in ev}
   if len(names)==1:r['name']=next(iter(names));updates.append({'file':p.name,'code':code,'name':r['name'],'evidence':ev,'name_scope':'OFFICIAL_OBSERVED_NAME_NOT_HISTORICAL_RENAME_CERTIFICATION'})
  q=out/p.name
  with q.open('x',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
  outputs[str(q)]=sha(q)
 summary=json.loads((source/'RESULT_RECEIPT.json').read_text());summary.update(status='D23_TEN_ENTRY_RESEARCH_RESULT_PENDING_INDEPENDENT_FINAL_REVIEW',signal_execution_id=summary['execution_id'],metadata_execution_id=c['execution_id'],metadata_only_no_signal_recalculation=True,names_annotation_count=len(updates),source_unknown_gap_details={'301139.SZ':'Original selector20260831/20260901/20260902 absent officialsame-codearchive; knownstock/delisting-consolidation; retainedUNKNOWN, no fakebars','603007.SH':'20241224close15.39→20241226close8.69; observedTDX送1.5534600019454956/10 givesnormalizedratio.652368859109203 <2/3; unresolvedevent; UNKNOWN','original318':'230mapped-source reuse+38recoveredcodes+11nonstock+4knowninactive+1identityunknown+34unavailable sourcekeys (includes301139); notall318recovered'},cash_parameter_vendor_difference='301087 fivecash-event B differs Futu effective B; use exactTDX eventsource researchnorm, no fitting; notliveFutuparity');(out/'RESULT_SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');receipt={'execution_id':c['execution_id'],'verified_start':gate,'source_execution':summary['signal_execution_id'],'updated_names':updates,'files':outputs,'signal_recalculations':0,'data_writes':0,'native_or_pointer_writes':0,'network_calls':0,'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False};(out/'DELIVERY_RECEIPT.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':'DELIVERY_METADATA_ASSEMBLED','name_updates':len(updates),'unique_name_codes':len({r['code'] for r in updates}),'union_count':summary['unique_selected']},ensure_ascii=False));return 0
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--contract',required=True);raise SystemExit(main(p.parse_args().contract))
