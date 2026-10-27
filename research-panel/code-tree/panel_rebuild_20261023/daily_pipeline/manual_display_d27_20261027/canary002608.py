"""One-symbol full-prefix display candidate; original process_symbol unchanged; not release."""
from pathlib import Path
import json,importlib.util,hashlib,gzip,datetime
O=Path(__file__).resolve().parent;B=O.parent;PROJECT=B.parent;D=B/'daily_runs/staging/20261026_cbc6d4b2475d9793a1bf';S='002608.SZ'
spec=importlib.util.spec_from_file_location('manual_canary_pipeline',B/'pipeline_v4.py');P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
log={'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'purpose':'new manual webpage display request; exactly one stock candidate','symbol':S,'status':'CANDIDATE_PENDING','production':False,'publish':False,'fit_calls':0,'formula_calls':0,'source_bars':'D26 complete admitted prefix plus D27 official G4 single bar','allowed_scope_count':1}
try:
 plan=P.load(D/'PLAN.json');code=P.code_identity();assert code==plan['identity']['code'],'ORIGINAL_CODE_IDENTITY_CHANGED'
 manifest=P.load(D/'PARTITION_MANIFEST.json');sidecar=P.load(D/'PARTITION_AUDIT_SIDECAR.json');assert sidecar['manifest_sha256']==P.sha(D/'PARTITION_MANIFEST.json')
 rec=next(x for x in manifest['securities'] if x['symbol']==S);risk=next(x for x in sidecar['securities'] if x['symbol']==S);assert rec['last']==20261026 and rec['rows']==1327;P.validate_risk(risk,set())
 policy=P.load(PROJECT/'cache/READ_INVALIDATIONS.json');assert S not in policy['securities']
 ev=P.load(O/'EVENTS_SOURCE_PREPARATION.json');assert ev['status']=='EVENT_SOURCE_CANDIDATE_NOT_ADMITTED';events_path=O/ev['events']['path'];assert P.sha(events_path)==ev['events']['sha256'];old_path=P.pinned(ev['D26_events'])
 old=P.event_lists(old_path);new=P.event_lists(events_path);old_eff=P.relevant_events(old.get(S,[]),rec['first'],20261026);new_eff=P.relevant_events(new.get(S,[]),rec['first'],20261027);assert old_eff==new_eff,'EVENT_CHANGED_STOP_SINGLE_STOCK'
 source=P.load(B/'source_only_20261027/SOURCE_RECORD.json');assert source['sha256']=='08b7bb6ebf40252c58300995df84b6e6a725b76363871d95ec85502de250145d';g4path=P.pinned(source)
 en=P.engines();bars=P.g4_snapshot(g4path,'20261027',[S],en[2]);assert S in bars and 'error' not in bars[S]
 calendar=P.load(B/'CALENDAR_20261023_1231_VERIFIED_V2.json');assert P.calendar_gate(calendar,'20261027')['status']=='VERIFIED_OPEN_DATE'
 r=dict(rec,_volume_encoding=manifest['volume_contract']['volume_encoding'],_volume_decoder_sha256=manifest['volume_contract']['decoder_sha256'])
 stage=O/'canary002608_output';assert not stage.exists(),'CANARY_ALREADY_EXISTS_DO_NOT_REPEAT'
 pre=P.process_symbol(S,{S:r},D,bars,old,new,policy,{},calendar,'20261027',[],en,stage,True,allowed_categories=[])
 P.save(O/'CANARY002608_INPUT_BINDING.json',{'code_identity':code,'baseline_manifest':{'path':str(D/'PARTITION_MANIFEST.json'),'sha256':P.sha(D/'PARTITION_MANIFEST.json')},'baseline_sidecar':{'path':str(D/'PARTITION_AUDIT_SIDECAR.json'),'sha256':P.sha(D/'PARTITION_AUDIT_SIDECAR.json')},'baseline_record':rec,'risk':risk,'D26_events':ev['D26_events'],'D27_events':ev['events'],'effective_events_unchanged':True,'D26_effective_events_sha256':P.run_key(old_eff),'D27_effective_events_sha256':P.run_key(new_eff),'D27_raw_G4':bars[S],'G4_source':source,'live_policy_sha256':P.sha(PROJECT/'cache/READ_INVALIDATIONS.json'),'preflight':pre,'qualification':'NONPIT_DISPLAY_RESEARCH_CANDIDATE_ONLY_NOT_RELEASED'})
 result=P.process_symbol(S,{S:r},D,bars,old,new,policy,{},calendar,'20261027',[],en,stage,False,allowed_categories=[]);log['formula_calls']=1
 data=json.loads(gzip.decompress((stage/'stocks'/S/'formula.json.gz').read_bytes()));assert len(data['rows'])==1328 and data['rows'][-1]['trade_date']==20261027
 assert all(len(x['values'])==51 and len(x['drawings'])==22 for x in data['rows'])
 P.save(O/'CANARY002608_LASTBAR.json',data['rows'][-1]);P.save(O/'CANARY002608_PROCESS_RECEIPT.json',result)
 assert P.code_identity()==code and P.sha(PROJECT/'cache/READ_INVALIDATIONS.json')==plan['source_bindings']['live_read_policy']['sha256'],'CODE_OR_POLICY_CHANGED'
 log.update(status='ONE_STOCK_CANDIDATE_COMPUTED_PENDING_INDEPENDENT_REVIEW',rows=1328,first=data['rows'][0]['trade_date'],last=data['rows'][-1]['trade_date'],fields=51,drawings=22,event_changed=False,original_code_hashes_unchanged=True,process=result,source_amount_precision_note='original merge_daily retains float32 .day amount equivalence; G4 original amount preserved in INPUT_BINDING',limits=['NONPIT not original192 certification','inferred volume numeric validation not official vendor unit certification','single symbol, not 126 or full-market admission','no self-signed root release; no UI publication before independent review'])
except Exception as e:log.update(status='CANARY_BLOCKED',error=type(e).__name__+': '+str(e))
log['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();P.save(O/'CANARY002608_RUN.json',log);print(json.dumps(log,ensure_ascii=False,indent=2));raise SystemExit(0 if log['status'].startswith('ONE_STOCK') else 2)
