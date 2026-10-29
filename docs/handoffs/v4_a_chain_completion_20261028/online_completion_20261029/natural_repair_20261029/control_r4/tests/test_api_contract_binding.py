"""Only actual missing guard-contract dependency and BASE-only lock fixtures."""
from copy import deepcopy
import importlib.util,json,sys,threading
from pathlib import Path
import pytest
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('r4_contract_control',HERE/'five_label_control.py')
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)
PLAN=json.loads((HERE/'PLAN.json').read_bytes())
def unbound():
 spec=importlib.util.spec_from_file_location('actual_unbound_api_guard',PLAN['api_integration']['path'])
 m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m

def test_actual_missing_default_reproduced_and_manifest_bound_same_lock():
 original=unbound();missing=Path(PLAN['api_app_root'])/'deployment/api_module_contracts.json'
 assert not missing.exists()
 with pytest.raises(FileNotFoundError):original.api_release_lock_path(Path(C.row(PLAN,'api')['plist']))
 bound=C.load_api_integration(PLAN)
 assert bound.MODULE_CONTRACT_PATH==Path(PLAN['api_module_contract']['path'])
 assert bound.api_release_lock_path(Path(C.row(PLAN,'api')['plist']))==Path('/Users/lexi/Library/LaunchAgents/.com.lexi.v4.api.release.lock')
 # All actual locking/parsing functions remain the imported API implementation.
 for name in ['shared_api_release_lock','assert_api_release_lock','api_release_lock_path','_read_json']:
  f=getattr(original,name);g=getattr(bound,name)
  if hasattr(f,'__wrapped__'):f=f.__wrapped__;g=g.__wrapped__
  assert f.__code__.co_code==g.__code__.co_code
  assert f.__code__.co_filename==g.__code__.co_filename==PLAN['api_integration']['path']


def test_original_lock_lease_and_contention_only_inside_case(tmp_path):
 m=C.load_api_integration(PLAN);plist=tmp_path/'com.lexi.v4.api.plist';expected=tmp_path/'.com.lexi.v4.api.release.lock'
 assert m.api_release_lock_path(plist)==expected
 failures=[]
 def contender():
  try:
   with m.shared_api_release_lock(plist,timeout_seconds=.05,role='gateway'):failures.append('UNEXPECTED_ACQUIRE')
  except ValueError as exc:failures.append(str(exc))
 with m.shared_api_release_lock(plist,timeout_seconds=.2,role='gateway') as lease:
  m.assert_api_release_lock(lease,plist,role='gateway')
  assert lease.path==expected and lease.pid==__import__('os').getpid()
  thread=threading.Thread(target=contender);thread.start();thread.join(timeout=1)
  assert not thread.is_alive() and failures==['API_RELEASE_SHARED_LOCK_BUSY']
 assert not expected.exists()
 with pytest.raises(ValueError):m.assert_api_release_lock(lease,plist,role='gateway')


@pytest.mark.parametrize('field,value',[('path','/unknown/api_contract.json'),('sha256','0'*64)])
def test_unknown_contract_path_or_sha_not_accepted(field,value):
 p=deepcopy(PLAN);p['api_module_contract'][field]=value
 with pytest.raises(C.Stop,match='API_MODULE_CONTRACT_MANIFEST_BINDING'):C.load_api_integration(p)


def local_contract_fixture(tmp_path):
 p=deepcopy(PLAN);raw=Path(p['api_module_contract']['path']).read_bytes();contract=tmp_path/'contract.json';contract.write_bytes(raw)
 # A synthetic manifest is confined to the fixture; production pins stay untouched.
 root=tmp_path/'fixture_release';root.mkdir();p['api_app_root']=str(root/'app')
 p['api_module_contract']={'path':str(contract),'sha256':C.sha(raw)}
 manifest={'external_module_contract':p['api_module_contract']};raw_manifest=C.canonical(manifest);(root/'release-manifest.json').write_bytes(raw_manifest)
 p['api_manifest_sha256']=C.sha(raw_manifest)
 return p,contract


@pytest.mark.parametrize('change',['bytes','module_path'])
def test_contract_drift_after_import_fails_before_original_lock(tmp_path,change):
 p,contract=local_contract_fixture(tmp_path);m=C.load_api_integration(p)
 if change=='bytes':contract.write_bytes(contract.read_bytes()+b'\n')
 else:m.MODULE_CONTRACT_PATH=tmp_path/'unknown.json'
 with pytest.raises(C.Stop,match='SHA_DRIFT|API_MODULE_CONTRACT_PATH_DRIFT'):
  with m.shared_api_release_lock(tmp_path/'com.lexi.v4.api.plist',timeout_seconds=.1):pytest.fail('drift acquired lock')
 assert not (tmp_path/'.com.lexi.v4.api.release.lock.mutex').exists()
