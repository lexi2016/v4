from pathlib import Path
from copy import deepcopy
import hashlib,importlib.util,json,plistlib,sys
import pytest
N=Path(__file__).resolve().parents[1];C=N/'control_r1';sys.path.insert(0,str(C))
import four_role_control as M
P=json.loads((C/'PLAN.json').read_bytes())
def test_exact_scope_metadata_four_roles_main_readonly_and_cli_body():
 assert M.scope(P) is True
 M.Live(P).main_unchanged() # Same read-only LC_ALL=C policy; no guard/lock/action.
 for role in ('main','other'):
  with pytest.raises(M.Stop):M.require_role(role)
 for role in ('stage','api'):
  p=deepcopy(P);next(r for r in p['releases'] if r['role']==role)['delta']['unapproved.py']='0'*64
  with pytest.raises(M.Stop):M.scope(p)
 op=M.row(P,'api');before=plistlib.loads(Path(op['before_file']).read_bytes());after=plistlib.loads(Path(op['after_file']).read_bytes())
 for k in ('V4_RESEARCH_PANEL_ROOT','V4_RESEARCH_PANEL_ASSET_MANIFEST'):assert before['EnvironmentVariables'][k]==after['EnvironmentVariables'][k]
 old=N.parent/'native_window_r1/control_r2';body=lambda p:p.read_text().split('static volatile sig_atomic_t',1)[1]
 assert body(C/'bounded_launchctl.c')==body(old/'bounded_launchctl.c')
 source=(C/'bounded_launchctl.c').read_text();assert 'com.lexi.v4.scheduler' not in source and source.count('static char *const ')==22
 for name in ('abort_guardian.py','recovery_support.py','plist_metadata.py','reviewed_r7.py'):assert (C/name).read_bytes()==(old/name).read_bytes()
 ref,contract=M.api_module_contract_binding(P);assert contract['roles']['gateway']['lock_name']=='.com.lexi.v4.api.release.lock'
 mod=M.load_api_integration(P);assert mod.module_role_contract()==contract # Original lock parser; never acquires a real lock here.

def test_api_reverse_health_uses_original_release_identity(monkeypatch):
 import urllib.request
 oldid=P['api_release_id'];newid=M.row(P,'api')['new_release_id'];current=[oldid]
 class Response:
  def __init__(self,p):self.p=p
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self):return json.dumps(self.p).encode()
 def get(url,**kw):
  if url.endswith('/healthz'):return Response({'status':'ok'})
  if url.endswith('/date-list'):return Response({'runtime_identity':{'status':'MANIFEST_EXECUTION_FILES_VERIFIED','release_id':current[0]}})
  return Response({'status':'VERIFIED','api_release_id':current[0]})
 monkeypatch.setattr(urllib.request,'urlopen',get)
 assert M.Live(P,True).health() is True and M.Live(P).health() is False
 current[0]=newid
 assert M.Live(P).health() is True and M.Live(P,True).health() is False
