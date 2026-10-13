"""Targeted exact-base compatibility and immutable binding regression."""
from pathlib import Path
import importlib.util,json,copy
import pytest
H=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('v11test',H/'remaining-gaps-prepare-v11.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)

def fixture(root):
 (root/'source.py').write_text('original business bytes\n')
 p=root/'__pycache__/source.cpython-314.pyc';p.parent.mkdir();p.write_bytes(b'fixed generated cache')
 entries=[v.generic._entry_for_path(root,r) for r in ['__pycache__/source.cpython-314.pyc','source.py']]
 return p,dict(application_inventory=dict(entries=entries,aggregate_sha256=v.inventory_digest(entries)))

def test_only_exact_declared_cache_is_compatible(tmp_path):
 p,m=fixture(tmp_path);actual,excluded=v.declared_cache_proof(tmp_path,m)
 assert actual==v.inventory_tree(tmp_path) and [e['path'] for e in excluded]==['__pycache__/source.cpython-314.pyc']
 p.write_bytes(b'changed cache')
 with pytest.raises(ValueError,match='STAGE_DECLARED_CACHE_BYTES_DRIFT'):v.declared_cache_proof(tmp_path,m)

@pytest.mark.parametrize('change',['source','added_source','missing_source','digest'])
def test_noncache_or_digest_difference_never_compatible(tmp_path,change):
 p,m=fixture(tmp_path)
 if change=='source':(tmp_path/'source.py').write_text('parallel mutation')
 if change=='added_source':(tmp_path/'parallel.py').write_text('new independent source')
 if change=='missing_source':(tmp_path/'source.py').unlink()
 if change=='digest':m['application_inventory']['aggregate_sha256']='0'*64
 with pytest.raises(ValueError):v.declared_cache_proof(tmp_path,m)

def test_exact_stage_compat_does_not_extend_to_another_release(monkeypatch):
 def reject(**args):raise ValueError('API_RELEASE_ACTIVE_APPLICATION_INVENTORY_DRIFT')
 monkeypatch.setattr(v,'ORIGINAL_IDENTITY',reject)
 with pytest.raises(ValueError,match='EXACT_STAGE_COMPAT_IDENTITY_REQUIRED'):
  v.exact_stage_identity(app_root=Path('/tmp/unapproved/app'),release_root=Path('/tmp/unapproved'),manifest_path=Path('/tmp/unapproved/release-manifest.json'),release_id='unapproved',manifest_sha256='0'*64)

def test_actual_config_adds_only94_preserves00001_tdx_state():
 raw=(v.FORMAL/'config/manager-workbench-v7.json').read_bytes();old=json.loads(raw)
 new,summary=v.prepare_config(raw,v.FUTU_PRODUCT,v.FUTU_PRODUCT_SHA,'2026-10-13T12:00:00+00:00')
 a=old['source_bindings']['hk_panel']['20261012'];b=new['source_bindings']['hk_panel']['20261012']
 assert b['futu_history'][0]==a['futu_history'][0] and len(b['futu_history'])==95
 assert b['tdxpy_history']==a['tdxpy_history'] and new['state_root']==old['state_root']
 restored=copy.deepcopy(new);restored['source_bindings']['hk_panel']['20261012']['futu_history']=a['futu_history'];assert restored==old
 assert summary['expected_assessed_count']==662
 with pytest.raises(ValueError,match='FUTU94_PRODUCT_DRIFT'):v.prepare_config(raw,v.FUTU_PRODUCT,'0'*64,'2026-10-13T12:00:00+00:00')
 with pytest.raises(ValueError,match='FUTU94_PRODUCT_AFTER_CUTOFF'):v.prepare_config(raw,v.FUTU_PRODUCT,v.FUTU_PRODUCT_SHA,'2026-10-13T10:00:00+00:00')
