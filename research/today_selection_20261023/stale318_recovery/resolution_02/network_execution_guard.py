"""Local fail-closed registration gate used before a canary imports its client."""
import hashlib,json,sys
from pathlib import Path

ROOT=Path('/Users/lexi/Desktop/学习/因子工厂')
REGISTRY=ROOT/'contracts/EXPERIMENT_REGISTRY.jsonl'
class RegistrationGateError(RuntimeError):pass
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require_registered_start(contract_path):
 cp=Path(contract_path).resolve()
 try:
  c=json.loads(cp.read_text());rp=cp.parent/'RUN_STARTED_RECEIPT.json'
  r=json.loads(rp.read_text())
  if r.get('event_type')!='RUN_STARTED':raise RegistrationGateError('RECEIPT_NOT_RUN_STARTED')
  for field in ('execution_id','route_id','input_sha256','code_sha256'):
   if r.get(field)!=c.get(field) or not c.get(field):raise RegistrationGateError('RECEIPT_BINDING_MISMATCH:'+field)
  if r.get('contract_sha256')!=sha(cp):raise RegistrationGateError('RECEIPT_CONTRACT_SHA_MISMATCH')
  if Path(r.get('contract_path','')).resolve()!=cp:raise RegistrationGateError('RECEIPT_CONTRACT_PATH_MISMATCH')
  if Path(r.get('registry_path','')).resolve()!=REGISTRY:raise RegistrationGateError('NOT_OFFICIAL_REGISTRY')
  if not r.get('event_sha256'):raise RegistrationGateError('MISSING_OFFICIAL_EVENT_SHA')
  command=c.get('command')
  if not isinstance(command,list) or len(command)<3 or sha(command[2])!=c['code_sha256']:raise RegistrationGateError('ACTUAL_ENTRYPOINT_CODE_SHA_MISMATCH')
  for p,h in c.get('frozen_source_bindings',{}).items():
   if sha(p)!=h:raise RegistrationGateError('FROZEN_BINDING_DRIFT:'+p)
  sys.path.insert(0,str(ROOT/'workspace/hkconnect_price_semantics_v2_20260919/zero_label_parity'))
  from registry_adapter import OfficialRegistryAdapter
  ad=OfficialRegistryAdapter()
  with ad._locked():
   _,events=ad._read_validated()
   exact=[e for e in events if e['event_sha256']==r['event_sha256']]
   if len(exact)!=1:raise RegistrationGateError('RUN_STARTED_EVENT_NOT_IN_OFFICIAL_REGISTRY')
   e=exact[0]
   for field in ('event_type','execution_id','route_id','input_sha256','code_sha256','contract_sha256'):
    if e.get(field)!=r.get(field):raise RegistrationGateError('OFFICIAL_EVENT_BINDING_MISMATCH:'+field)
   same=[x for x in events if x['execution_id']==c['execution_id']]
   if any(x['event_type']=='TERMINAL' for x in same):raise RegistrationGateError('EXECUTION_ALREADY_TERMINAL')
  return {'execution_id':c['execution_id'],'event_sha256':e['event_sha256'],'contract_sha256':sha(cp),'gate':'VERIFIED_OFFICIAL_START_BEFORE_CLIENT_IMPORT'}
 except RegistrationGateError:raise
 except Exception as e:raise RegistrationGateError('START_GATE_UNAVAILABLE:'+type(e).__name__+':'+str(e)) from e
