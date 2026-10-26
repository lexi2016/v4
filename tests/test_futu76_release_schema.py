"""Only the new typed schedule-remediation base-schema acceptance boundary."""
import json
from pathlib import Path

import pytest

from ops import api_release_integration as a


@pytest.fixture
def legacy(tmp_path):
    root=tmp_path/'schedule-remediation-test';app=root/'app';app.mkdir(parents=True)
    (app/'one.py').write_text('x=1\n')
    (app/'two.txt').write_bytes(b'preserved')
    manifest=dict(schema_version='v4.schedule_remediation_release.v1',release_id=root.name,
        candidate_app_root='/old/build/app',app_files=[dict(path=r['path'],sha256=r['sha256'],bytes=r['size'])
            for r in a.inventory_tree(app)])
    return root,app,manifest


def identify(legacy,**kw):
    root,app,manifest=legacy;p=root/'release-manifest.json'
    p.write_text(json.dumps(manifest))
    return a._release_identity(release_root=root,app_root=app,release_id=root.name,manifest_path=p,
        manifest_sha256=kw.pop('sha',a.sha256_bytes(p.read_bytes())),**kw)


def test_typed_base_authenticates_complete_inventory(legacy):
    got=identify(legacy)
    assert got['inventory']==a.inventory_tree(legacy[1])
    assert got['application_inventory_entry_count']==2
    assert got['base_manifest_schema']=='v4.schedule_remediation_release.v1'
    assert got['module_role']=='gateway'
    assert identify(legacy,application_inventory_sha256=got['application_inventory_sha256'])['inventory']==got['inventory']


@pytest.mark.parametrize('kind',['unknown_schema','release_id','app_root','missing_list','duplicate','unsafe_path',
    'wrong_sha','wrong_size','missing_file','extra_file','symlink','false_size','inventory_pin','manifest_sha'])
def test_typed_base_rejects_incomplete_unsafe_or_drifted_identity(legacy,kind):
    root,app,m=legacy;kwargs={}
    if kind=='unknown_schema':m['schema_version']='unrecognized'
    if kind=='release_id':m['release_id']='wrong'
    if kind=='app_root':m['app_root']='/wrong/app'
    if kind=='missing_list':m.pop('app_files')
    if kind=='duplicate':m['app_files'].append(dict(m['app_files'][0]))
    if kind=='unsafe_path':m['app_files'][0]['path']='../escape'
    if kind=='wrong_sha':m['app_files'][0]['sha256']='0'*64
    if kind=='wrong_size':m['app_files'][0]['bytes']+=1
    if kind=='missing_file':m['app_files'].pop()
    if kind=='extra_file':(app/'unlisted.py').write_text('x=2\n')
    if kind=='symlink':
        (app/'one.py').unlink();(app/'one.py').symlink_to(app/'two.txt')
    if kind=='false_size':m['app_files'][0]['bytes']=True
    if kind=='inventory_pin':kwargs['application_inventory_sha256']='0'*64
    if kind=='manifest_sha':kwargs['sha']='0'*64
    with pytest.raises((ValueError,FileNotFoundError)):
        identify(legacy,**kwargs)


def test_existing_standard_schema_unchanged(legacy):
    root,app,_=legacy
    inventory=a.inventory_tree(app)
    manifest=dict(schema_version='v4.release_candidate.v1',candidate=dict(release_id=root.name,app_root=str(app)),
        application_inventory=dict(entry_count=len(inventory),entries=inventory,aggregate_sha256=a.inventory_digest(inventory)))
    got=identify((root,app,manifest))
    assert got['inventory']==inventory
    assert 'base_manifest_schema' not in got
