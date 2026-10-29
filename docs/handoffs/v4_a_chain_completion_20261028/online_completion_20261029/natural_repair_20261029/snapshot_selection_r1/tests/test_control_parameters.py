from pathlib import Path
from copy import deepcopy
import json,plistlib,sys
import pytest
N=Path(__file__).resolve().parents[1];C=N/'control_r1';sys.path.insert(0,str(C));import four_role_control as M
P=json.loads((C/'PLAN.json').read_bytes())
def test_new_exact_parameters_and_unchanged_recovery_scope():
 assert M.scope(P)
 old=N.parent/'snapshot_recovery_r1/control_r1'
 for name in ('reviewed_r7.py','plist_metadata.py','recovery_support.py','abort_guardian.py'):assert (C/name).read_bytes()==(old/name).read_bytes()
 source=(C/'bounded_launchctl.c').read_text();previous=(old/'bounded_launchctl.c').read_text();assert source.split('static volatile sig_atomic_t',1)[1]==previous.split('static volatile sig_atomic_t',1)[1]
 assert source.count('static char *const ')==22 and 'com.lexi.v4.scheduler' not in source
 assert P['api_release_id']=='v4-daily-numeric283-chart-20261029-r3-api'
 with pytest.raises(M.Stop):M.require_role('main')
 bad=deepcopy(P);bad['releases'][0]['delta']['unapproved.py']='0'*64
 with pytest.raises(M.Stop):M.scope(bad)
 canary=json.loads((N/'disable_canary/ACTUAL_RESULT.json').read_bytes());assert canary['status']=='FAIL_DISABLE_DOES_NOT_SUPPRESS_LOADED_KEEPALIVE_RESPAWN' and canary['cleanup_absent'] is True
 # No new bootout-only or disable/signal controller is substituted.
 assert 'recovery.start_guardian' in (C/'four_role_control.py').read_text()


def test_health_failure_reverse_identity_and_normal_graceful_drain_contract(monkeypatch):
 import urllib.request
 old=P['api_release_id'];new=M.row(P,'api')['new_release_id'];current=[old]
 class Response:
  def __init__(self,v):self.v=v
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self):return json.dumps(self.v).encode()
 def get(url,**kw):
  if url.endswith('/healthz'):return Response({'status':'ok'})
  if url.endswith('/date-list'):return Response({'runtime_identity':{'status':'MANIFEST_EXECUTION_FILES_VERIFIED','release_id':current[0]}})
  return Response({'status':'VERIFIED','api_release_id':current[0]})
 monkeypatch.setattr(urllib.request,'urlopen',get)
 assert M.Live(P,True).health() and not M.Live(P).health();current[0]=new;assert M.Live(P).health() and not M.Live(P,True).health()
 app=Path(P['api_app_root']);binding=(app/'v4/manager_workbench/binding.py').read_text();jobs=(app/'v4/manager_workbench/jobs.py').read_text()
 assert 'finally:\n            service.stop()' in binding and 'self.pool.shutdown(wait=True)' in jobs
 # Reuse the reviewed recipe: no bootout of original healthy API process.
 original=(C/'four_role_control.py').read_text()
 assert "self.identity(old['pid']) is not None" in original and "self.guard(role,old)!=guard" in original
