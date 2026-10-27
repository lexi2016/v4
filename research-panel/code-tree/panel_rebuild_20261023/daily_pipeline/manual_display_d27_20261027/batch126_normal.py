"""Fixed webpage126: preserve all identities, compute only qualified normal rows. No network or publication."""
from pathlib import Path
import json,importlib.util,hashlib,gzip,datetime,shutil,traceback
O=Path(__file__).resolve().parent;B=O.parent;R=B.parent.parent;PROJECT=B.parent;D=B/'daily_runs/staging/20261026_cbc6d4b2475d9793a1bf';OUT=O/'normal126_20261027T094950Z'
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
s=importlib.util.spec_from_file_location('normal126_pipeline',B/'pipeline_v4.py');P=importlib.util.module_from_spec(s);s.loader.exec_module(P)
assert not OUT.exists(),'NO_OVERWRITE';OUT.mkdir()
plan=P.load(D/'PLAN.json');code=P.code_identity();assert code==plan['identity']['code'],'CODE_CHANGED';assert shutil.disk_usage(R).free-400*1024**2>=3*1024**3
indexpath=R/'sites/stock18-workflow/dist/research-2026-10-27-r2.json';index=P.load(indexpath);symbols=sorted({x['symbol'] for x in index['stocks'] if any(y.get('chart_path') for y in x.get('details',[]))});assert len(symbols)==126
specialpath=R/'research_outputs/d26_pullback_selection_20261026/SPECIAL43_SCOPE.json';special={s:r for r in P.load(specialpath) for s in r['symbols']};manifest=P.load(D/'PARTITION_MANIFEST.json');sidecar=P.load(D/'PARTITION_AUDIT_SIDECAR.json');assert sidecar['manifest_sha256']==P.sha(D/'PARTITION_MANIFEST.json');recs={x['symbol']:x for x in manifest['securities']};risks={x['symbol']:x for x in sidecar['securities']};policy=P.load(PROJECT/'cache/READ_INVALIDATIONS.json');policy_sha=P.sha(PROJECT/'cache/READ_INVALIDATIONS.json');cal=P.load(B/'CALENDAR_20261023_1231_VERIFIED_V2.json')
ev=P.load(O/'EVENTS_SOURCE_PREPARATION.json');assert ev['status']=='EVENT_SOURCE_CANDIDATE_NOT_ADMITTED';events_path=O/ev['events']['path'];assert P.sha(events_path)==ev['events']['sha256'];oldpath=P.pinned(ev['D26_events']);old=P.event_lists(oldpath);new=P.event_lists(events_path);g4=P.load(B/'source_only_20261027/SOURCE_RECORD.json');g4path=P.pinned(g4);assert g4['sha256']=='08b7bb6ebf40252c58300995df84b6e6a725b76363871d95ec85502de250145d';en=P.engines();bars=P.g4_snapshot(g4path,'20261027',symbols,en[2]);allowed=plan['identity']['allowed_categories'];assert allowed==[2,3,5,9]
review=R/'research_outputs/independent_d27_display_canary_20261027/CHECK.json';assert P.sha(review)=='5f6148a009adef0799b1da7ceef843a67ba8db5ed52919a62a4ef09a695f0572'
P.save(OUT/'INPUT_BINDINGS.json',{'started_utc':now(),'scope':symbols,'scope_sha256':P.run_key(symbols),'original_index':{'path':str(indexpath),'sha256':P.sha(indexpath)},'special_scope':{'path':str(specialpath),'sha256':P.sha(specialpath)},'D26_manifest':{'path':str(D/'PARTITION_MANIFEST.json'),'sha256':P.sha(D/'PARTITION_MANIFEST.json')},'D26_sidecar':{'path':str(D/'PARTITION_AUDIT_SIDECAR.json'),'sha256':P.sha(D/'PARTITION_AUDIT_SIDECAR.json')},'D26_events':ev['D26_events'],'D27_events':{'path':str(events_path),'sha256':P.sha(events_path)},'G4_source':g4,'code_identity':code,'live_policy_sha256':policy_sha,'allowed_categories_preserved_not_upgraded':allowed,'canary_independent_check':{'path':str(review),'sha256':P.sha(review)},'authorization':'root approved fixed126 normal continuation only; special retained UNKNOWN; no publication; no source refetch'})
ledger=[];eligible=[]
for symbol in symbols:
 a={'symbol':symbol,'target_date':20261027,'indicator_date':20261026,'status':'PREFLIGHT_PENDING','qualification':'NONPIT_RESEARCH_DISPLAY_ONLY','buy_confirmed':False,'ui_amount_must_use':'exact G4 source or independently checked qt; not float32 pipeline amount'}
 if symbol in bars and 'error'not in bars[symbol]:a['D27_source_bar']=bars[symbol]
 if symbol in special:
  a.update(status='UNKNOWN_SPECIAL_CONTINUATION_NOT_ADMITTED',reader_root=special[symbol]['path'],root_sha256=special[symbol]['root_sha256'],reader_sha256=special[symbol]['reader_sha256'],reason='Dedicated D26 reader qualification does not transfer to generic normal continuation; retain D26 chart.');ledger.append(a);continue
 try:
  rec=recs[symbol];risk=risks[symbol];assert rec['last']==20261026 and rec['rows']>0;assert symbol not in policy['securities'];P.validate_risk(risk,set(allowed))
  oe=P.relevant_events(old.get(symbol,[]),rec['first'],20261026);ne=P.relevant_events(new.get(symbol,[]),rec['first'],20261027);assert oe==ne,'EVENT_CHANGED_REQUIRES_REVIEW'
  assert symbol in bars and 'error' not in bars[symbol],'G4_INVALID'
  rec=dict(rec,_volume_encoding=manifest['volume_contract']['volume_encoding'],_volume_decoder_sha256=manifest['volume_contract']['decoder_sha256'])
  pre=P.process_symbol(symbol,{symbol:rec},D,bars,old,new,policy,{},cal,'20261027',[],en,OUT/'output',True,allowed_categories=allowed)
  a.update(status='PREFLIGHT_PASS_PENDING_COMPUTE',baseline_record=recs[symbol],baseline_risk=risk,effective_event_sha256=P.run_key(oe),event_changed=False,preflight=pre);eligible.append((symbol,rec,a))
 except Exception as e:a.update(status='UNKNOWN_PREFLIGHT_FAILED',reason=type(e).__name__+': '+str(e))
 ledger.append(a)
P.save(OUT/'PREFLIGHT126.json',ledger)
computed=reused=0
for symbol,rec,a in eligible:
 try:
  assert P.code_identity()==code and P.sha(PROJECT/'cache/READ_INVALIDATIONS.json')==policy_sha,'CODE_POLICY_CHANGED'
  if symbol=='002608.SZ':
   stage=O/'canary002608_output';result=P.load(O/'CANARY002608_PROCESS_RECEIPT.json');reused+=1
   for f in result['files']:assert P.sha(stage/f['path'])==f['sha256']
  else:
   assert shutil.disk_usage(R).free-8*1024**2>=3*1024**3
   stage=OUT/'output';result=P.process_symbol(symbol,{symbol:rec},D,bars,old,new,policy,{},cal,'20261027',[],en,stage,False,allowed_categories=allowed);computed+=1
  f=stage/'stocks'/symbol/'formula.json.gz';data=json.loads(gzip.decompress(f.read_bytes()));assert len(data['rows'])==rec['rows']+1 and data['rows'][-1]['trade_date']==20261027;assert all(len(x['values'])==51 and len(x['drawings'])==22 for x in data['rows'])
  a.update(status='CANDIDATE_D27_COMPUTED_PENDING_INDEPENDENT_REVIEW',indicator_date=20261027,output_root=str(stage),process_receipt=result,formula_path=str(f),formula_sha256=P.sha(f),actual_first=data['rows'][0]['trade_date'],actual_last=data['rows'][-1]['trade_date'],actual_rows=len(data['rows']),reuse_canary=symbol=='002608.SZ')
  P.save(OUT/'lastbars'/(symbol+'.json'),{'symbol':symbol,'source_bar_exact':bars[symbol],'formula_lastbar':data['rows'][-1],'amount_contract':'source_bar_exact amount is exact G4 double; formula pipeline amount is float32 contract; do not use float32 for 1e8 gate','formula_sha256':P.sha(f),'status':'CANDIDATE_PENDING_INDEPENDENT_REVIEW'})
 except Exception as e:a.update(status='UNKNOWN_COMPUTE_FAILED',reason=type(e).__name__+': '+str(e));P.save(OUT/'errors'/(symbol+'.json'),{'error':a['reason'],'traceback':traceback.format_exc()})
 P.save(OUT/'MANIFEST126.json',ledger)
 print(symbol,a['status'],flush=True)
from collections import Counter
summary={'finished_utc':now(),'status':'FIXED126_DISPLAY_CANDIDATES_PENDING_INDEPENDENT_REVIEW','scope':126,'status_counts':dict(Counter(x['status'] for x in ledger)),'formula_calls':computed,'reused_canary':reused,'fit_calls':0,'network_calls':0,'published':False,'original_code_unchanged':P.code_identity()==code,'policy_unchanged':P.sha(PROJECT/'cache/READ_INVALIDATIONS.json')==policy_sha,'free_bytes':shutil.disk_usage(R).free,'amount_contract':'exact G4/qt only for UI/gates; pipeline amount float32 retained','remaining_special':[x['symbol'] for x in ledger if x['status']=='UNKNOWN_SPECIAL_CONTINUATION_NOT_ADMITTED']}
P.save(OUT/'SUMMARY.json',summary);print(json.dumps(summary,ensure_ascii=False));print('OUTPUT',OUT)
