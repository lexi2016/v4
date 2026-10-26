"""Only R2 standard inventory count gates and layered legacy rollback proof."""
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from ops import api_release_integration as a

R=Path('/Users/lexi/Desktop/学习/因子工厂/research/futu_qfq76_mac_integration_20261026_r1/r2_entry_count_repair')


@pytest.fixture
def standard(tmp_path):
    root=tmp_path/'standard-count';app=root/'app';app.mkdir(parents=True)
    (app/'one.py').write_text('x=1\n');inventory=a.inventory_tree(app)
    manifest=dict(schema_version='v4.release_candidate.v1',candidate=dict(release_id=root.name,root=str(root),app_root=str(app)),
        application_inventory=dict(entry_count=1,entries=inventory,aggregate_sha256=a.inventory_digest(inventory)))
    return root,manifest


def invoke(standard,kind):
    root,manifest=standard;p=root/'release-manifest.json';p.write_text(json.dumps(manifest));sha=a.sha256_bytes(p.read_bytes())
    if kind=='release':
        return a._release_identity(release_root=root,app_root=root/'app',release_id=root.name,manifest_path=p,manifest_sha256=sha)
    return a._candidate_identity(manifest,root,sha)


@pytest.mark.parametrize('kind',['release','candidate'])
@pytest.mark.parametrize('count',[None,0,2,True,'1'])
def test_both_standard_paths_reject_missing_or_wrong_counts(standard,kind,count):
    if count is None:standard[1]['application_inventory'].pop('entry_count')
    else:standard[1]['application_inventory']['entry_count']=count
    with pytest.raises(ValueError,match='ENTRY_COUNT_MISMATCH'):invoke(standard,kind)


@pytest.mark.parametrize('kind',['release','candidate'])
def test_both_standard_paths_accept_exact_count(standard,kind):
    assert invoke(standard,kind)['application_inventory_entry_count']==1


@pytest.fixture
def rollback_proof(monkeypatch):
    s=importlib.util.spec_from_file_location('r2_rollback_proof',R/'root_cutover.py')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    expected={'V35_APP_ROOT':str(m.OLD/'app'),'V35_RELEASE_ID':m.OLD.name,'V35_RELEASE_MANIFEST_SHA256':m.BASE_MANIFEST_SHA}
    identity=dict(pid=86578,cwd=str(m.OLD/'app'),serving_app_root=str(m.OLD/'app'),declared_app_root=str(m.OLD/'app'),
        app_root_status='VERIFIED',release_id=m.OLD.name,release_manifest_sha256=m.BASE_MANIFEST_SHA,
        release_manifest_sha_status='VERIFIED',plist_sha256=m.BASE_PLIST_SHA,status='CANNOT_CONFIRM',
        plist_bindings={k:dict(status='MATCH',environment=v,plist=v) for k,v in expected.items()})
    monkeypatch.setattr(m,'pin',lambda *args:None)
    monkeypatch.setattr(m.a,'read_active_release',lambda *args:dict(release_id=m.OLD.name,release_manifest_sha256=m.BASE_MANIFEST_SHA,
        application_inventory_sha256='f'*64,application_inventory_entry_count=1315))
    class Response(io.BytesIO):pass
    monkeypatch.setattr(m,'urlopen',lambda *args,**kw:Response(json.dumps(dict(status='EVIDENCE_GAP',runtime_identity=identity)).encode()))
    def run(args,**kwargs):
        return SimpleNamespace(returncode=0,stdout='86578\n' if '-iTCP:8873' in args else 'p86578\nfcwd\nn'+str(m.OLD/'app')+'\n')
    monkeypatch.setattr(m.subprocess,'run',run)
    return m,identity


def test_rollback_proof_keeps_identity_gaps(rollback_proof):
    m,identity=rollback_proof;got=m.old_baseline_runtime_proof()
    assert got['runtime_identity_overall_status']=='CANNOT_CONFIRM'
    assert got['graph_status']=='EVIDENCE_GAP'
    assert got['original_standard_validator']=='CANNOT_CONFIRM_LEGACY_CUSTOM_SCHEMA'
    assert got['pid']==86578 and got['typed_application_inventory_entry_count']==1315


@pytest.mark.parametrize('failure',['pid','cwd','manifest_hash_status','plist_binding'])
def test_rollback_proof_rejects_inconsistent_observations(rollback_proof,failure):
    m,identity=rollback_proof
    if failure=='pid':identity['pid']=999
    if failure=='cwd':identity['serving_app_root']='/wrong/app'
    if failure=='manifest_hash_status':identity['release_manifest_sha_status']='DRIFT'
    if failure=='plist_binding':identity['plist_bindings']['V35_RELEASE_ID']['status']='DRIFT'
    with pytest.raises(AssertionError):m.old_baseline_runtime_proof()
