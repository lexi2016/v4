from pathlib import Path
from types import SimpleNamespace
import hashlib,importlib.util,json,pytest
H=Path(__file__).resolve().parent

def module():
 spec=importlib.util.spec_from_file_location('remaining_futu_batch',H/'remaining-gaps-futu-batch-r1.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_fixed94_plan_reuses_single_and_rejects_plan_drift(tmp_path):
 m=module();p,s=m.load_plan(H/'remaining-gaps-futu-plan-r1.json');assert len(p['ordered_codes'])==94 and p['ordered_codes'][0]=='HK.00068' and len(p['remaining_codes'])==30 and len(s)==61
 bad=tmp_path/'plan.json';bad.write_bytes((H/'remaining-gaps-futu-plan-r1.json').read_bytes()+b' ')
 with pytest.raises(ValueError,match='PLAN_DRIFT'):m.load_plan(bad)

def test_quota_stop_sends_zero_history_requests(tmp_path):
 m=module();calls=[]
 ctx=SimpleNamespace(get_history_kl_quota=lambda _: (0,[6,0,[]]),request_history_kline=lambda *a,**kw:calls.append(kw))
 plan,s=m.load_plan(H/'remaining-gaps-futu-plan-r1.json');binding,result=m.fetch_one(ctx,'HK.00123',plan['request'],tmp_path/'single',s,'K_DAY','NONE')
 assert calls==[] and binding is None and result['error']=='FUTU_QUOTA_STOP_ZERO_REQUESTS'
 assert (tmp_path/'single/receipt.json').exists()

def test_exact61_fetch_preserves_profile_and_bad_price_is_unknown(tmp_path):
 m=module();plan,s=m.load_plan(H/'remaining-gaps-futu-plan-r1.json');original=json.loads((H/'remaining-gaps-futu-single-r1/raw.json').read_bytes())
 rows=[dict(v,code='HK.00123') for v in original];calls=[]
 def history(*args,**kw):calls.append((args,kw));return 0,SimpleNamespace(to_dict=lambda **kw:rows),None
 ctx=SimpleNamespace(get_history_kl_quota=lambda _:(0,[6,94,[]]),request_history_kline=history)
 binding,result=m.fetch_one(ctx,'HK.00123',plan['request'],tmp_path/'valid',s,'K_DAY','NONE')
 assert binding and result['status']=='READY' and len(calls)==1
 assert calls[0][1]['autype']=='NONE' and calls[0][1]['start']=='2026-07-17'
 assert m.validate_cached(binding,'HK.00123',plan['request'],s)==binding
 rows[0]['high']=rows[0]['low']-1
 binding,result=m.fetch_one(ctx,'HK.00123',plan['request'],tmp_path/'bad',s,'K_DAY','NONE')
 assert binding is None and result['status']=='UNASSESSED' and (tmp_path/'bad/raw.json').exists()
 assert not (tmp_path/'bad/binding.json').exists()

def test_cached_identity_mutation_is_rejected(tmp_path):
 m=module();plan,s=m.load_plan(H/'remaining-gaps-futu-plan-r1.json');binding=dict(plan['canary_binding']);root=tmp_path/'cache';root.mkdir()
 source=Path(binding['source_local_path'])
 for rel in ['raw.json','receipt.json']:(root/rel).write_bytes((source/rel).read_bytes())
 binding['source_local_path']=str(root);m.validate_cached(binding,'HK.00068',plan['request'],s)
 (root/'raw.json').write_bytes((root/'raw.json').read_bytes()+b' ')
 with pytest.raises(ValueError,match='IMMUTABLE_SOURCE_DRIFT'):m.validate_cached(binding,'HK.00068',plan['request'],s)

def test_only_exact_rate_limit_after_window_recovers_once(tmp_path):
 from datetime import datetime,timezone,timedelta
 m=module();plan,s=m.load_plan(H/'remaining-gaps-futu-plan-r1.json');root=tmp_path/'HK.02837';root.mkdir();finished=datetime.now(timezone.utc)
 prior=dict(source='FUTU',code='HK.02837',request=plan['request'],status='UNASSESSED',error=m.RATE_LIMIT_ERROR,finished_at=finished.isoformat());m.save(root/'receipt.json',prior);before=(root/'receipt.json').read_bytes()
 assert m.rate_limit_recovery(root,'HK.02837',plan['request'],at=finished+timedelta(seconds=29))[0] is None
 attempt,ref,status=m.rate_limit_recovery(root,'HK.02837',plan['request'],at=finished+timedelta(seconds=31));assert status=='RATE_LIMIT_RECOVERY_ALLOWED' and ref['sha256']==m.sha(before)
 attempt.mkdir(parents=True)
 assert m.rate_limit_recovery(root,'HK.02837',plan['request'],at=finished+timedelta(seconds=31))[0] is None
 assert (root/'receipt.json').read_bytes()==before
 other=tmp_path/'other';other.mkdir();m.save(other/'receipt.json',{**prior,'error':'FUTU_HISTORY_SOURCE_REJECTED:unknown security'})
 assert m.rate_limit_recovery(other,'HK.02837',plan['request'],at=finished+timedelta(seconds=31))[0] is None

def test_history_throttle_never_exceeds60_in30_seconds():
 m=module();clock=[0.0];times=[]
 def sleep(delay):clock[0]+=delay
 throttle=m.HistoryThrottle(clock=lambda:clock[0],sleep=sleep)
 for _ in range(94):throttle.wait();times.append(clock[0])
 assert all(sum(t>=start and t<start+30 for t in times)<=60 for start in times)
 assert all(b-a>=0.51-1e-10 for a,b in zip(times,times[1:]))

def test_rate_recovery_uses61_caches_only_fetches33_and_preserves_old_failures(tmp_path,monkeypatch):
 import sys
 from datetime import datetime,timezone,timedelta
 m=module();plan,sessions=m.load_plan(H/'remaining-gaps-futu-plan-r1.json');out=tmp_path/'remaining-gaps-test-batch';out.mkdir();product=json.loads((H/'remaining-gaps-futu-batch-r1/binding-product-cb38a4cda932456ae618b9af.json').read_bytes())
 for binding in product['bindings']:
  if binding['symbol']=='HK.00068':continue
  root=out/binding['symbol'];root.mkdir();source=Path(binding['source_local_path'])
  for rel in ['raw.json','receipt.json']:(root/rel).write_bytes((source/rel).read_bytes())
  m.save(root/'binding.json',{**binding,'source_local_path':str(root)})
 originals={}
 for result in product['results']:
  if result['status']=='READY':continue
  root=out/result['code'];root.mkdir();prior=json.loads(Path(result['receipt']).read_bytes());prior['finished_at']=(datetime.now(timezone.utc)-timedelta(seconds=31)).isoformat();m.save(root/'receipt.json',prior);originals[result['code']]=(root/'receipt.json').read_bytes()
 rows=json.loads((H/'remaining-gaps-futu-single-r1/raw.json').read_bytes());calls=[]
 def history(code,**kw):calls.append(code);return 0,SimpleNamespace(to_dict=lambda **_:[dict(r,code=code) for r in rows]),None
 ctx=SimpleNamespace(get_history_kl_quota=lambda _:(0,[63,37,[]]),request_history_kline=history,close=lambda:None)
 monkeypatch.setitem(sys.modules,'futu',SimpleNamespace(OpenQuoteContext=lambda **kw:ctx,KLType=SimpleNamespace(K_DAY='K_DAY'),AuType=SimpleNamespace(NONE='NONE')))
 monkeypatch.setattr(m,'HERE',tmp_path);monkeypatch.setattr(m,'load_plan',lambda p:(plan,sessions));monkeypatch.setattr(m,'HistoryThrottle',lambda:SimpleNamespace(wait=lambda:None));monkeypatch.setattr(sys,'argv',['batch','--output',str(out),'--execute'])
 m.main();assert set(calls)==set(originals) and len(calls)==33
 for code,raw in originals.items():assert (out/code/'receipt.json').read_bytes()==raw
 report=json.loads(next(out.glob('binding-product-*.json')).read_bytes());assert len(report['bindings'])==94 and len([r for r in report['results'] if r.get('cache_hit')])==61
 # Next invocation reuses all94, including successful recovery attempt refs.
 calls.clear();m.main();assert calls==[]
