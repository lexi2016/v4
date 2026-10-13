"""Only the pinned malformed aggregate is compatible; source changes still stop."""
import copy,importlib.util,json
from pathlib import Path
import pytest
HERE=Path(__file__).resolve().parent

def module():
 s=importlib.util.spec_from_file_location('us14pack',HERE/'us29-closure-prepare-v14.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def args(m):
 return dict(release_root=m.API_COMPAT_ROOT.parent,app_root=m.API_COMPAT_ROOT,release_id=m.API_COMPAT_ROOT.parent.name,
  manifest_path=m.API_COMPAT_ROOT.parent/'release-manifest.json',manifest_sha256=m.API_COMPAT_MANIFEST_SHA)

def test_exact_declared_entries_are_actual_and_only_aggregate_is_repaired_in_memory():
 m=module();v=m.exact_api_identity(**args(m));manifest=v['manifest']
 assert v['inventory']==manifest['application_inventory']['entries']
 assert v['application_inventory_sha256']==m.API_COMPAT_ACTUAL_DIGEST
 assert v['fixed_declared_aggregate']!=v['application_inventory_sha256']
 assert manifest['application_inventory']['aggregate_sha256']==v['fixed_declared_aggregate']
 assert m.sha(Path(v['release_manifest_path']).read_bytes())==m.API_COMPAT_MANIFEST_SHA

@pytest.mark.parametrize('bad',['source','plist','manifest','digestbinding'])
def test_any_other_identity_or_source_drift_fails(tmp_path,monkeypatch,bad):
 m=module();a=args(m)
 if bad=='source':
  inv,cache=m.generic._inventory_tree_with_generated_cache(m.API_COMPAT_ROOT);new=copy.deepcopy(inv);new[0]['sha256']='0'*64
  monkeypatch.setattr(m.generic,'_inventory_tree_with_generated_cache',lambda root:(new,cache))
 elif bad=='plist':
  p=tmp_path/'plist';p.write_text('Unapproved identity');m.API=p
 elif bad=='manifest':a['manifest_sha256']='0'*64
 else:a['application_inventory_sha256']='0'*64
 with pytest.raises(ValueError):m.exact_api_identity(**a)

def test_other_release_uses_original_strict_identity(monkeypatch):
 m=module();seen=[];m.ORIGINAL_IDENTITY=lambda **a:seen.append(a) or {'strict':True};a=args(m);a['app_root']=Path('/another/app')
 assert m.exact_api_identity(**a)=={'strict':True} and seen==[a]

def test_only_reviewed_us_sources_and_new_exact_datasets_are_in_delta():
 m=module();entries=m.sources();assert {e['path'] for e in entries}==m.SOURCES and len(entries)==6
 assert not any('oversold' in e['path'] or 'capture' in e['path'] or e['path'].endswith('config.py') for e in entries)
 for e in entries:
  if 'research_data/' in e['path']:assert e['before_sha256'] is None

def test_inherited_data_copies_only_missing_exact_readonly_files(tmp_path):
 m=module();api=tmp_path/'api';scheduler=tmp_path/'scheduler';canonical=tmp_path/'canonical';m.CANONICAL=canonical
 for rel in m.INHERITED_DATA:
  for root in [api,canonical]:
   p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(rel)
 m.INHERITED_DATA={r:m.sha((canonical/r).read_bytes()) for r in m.INHERITED_DATA}
 pending=m.inherited_data(api,scheduler);assert set(pending)==set(m.INHERITED_DATA)
 for rel,raw in pending.items():p=scheduler/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
 assert m.inherited_data(api,scheduler)=={}
 (scheduler/next(iter(pending))).write_text('Modified source')
 with pytest.raises(ValueError,match='INHERITED_SCHEDULER_DATA_DRIFT'):m.inherited_data(api,scheduler)
