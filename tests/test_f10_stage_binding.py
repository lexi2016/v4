"""F10 binding regression: exact releases, original evidence, unchanged cutoff.

Integration cases require F10_BINDING_CANDIDATE and F10_BINDING_REPLAY, and only
copy source bytes for SHA negative cases and an isolated dispatch ledger.
Full-chain cases read the original absolute source root without writing it.
The modified F10 dispatch receipt is explicitly a fixture, never natural proof.
"""
from __future__ import annotations
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import pytest

from infrastructure import manager_input_attestation as m
from ops.api_release_integration import inventory_tree, inventory_digest


def test_same_code_selects_only_successful_pinned_release(tmp_path, monkeypatch):
    stage=tmp_path/'stage'; stage.mkdir(); data=tmp_path/'data'; data.mkdir()
    roots=[tmp_path/name/'app' for name in ('f10','r6','name-zoom','sop')]
    for root in roots:
        (root/'ops').mkdir(parents=True); (root/'ops/run_hourly_research.py').write_bytes(b'identical-materializer')
    config={'research_historical_owner_bindings':[{'app_root':str(root),'release_id':root.parent.name,'manifest_sha256':'a'*64} for root in roots[1:]]}
    (stage/'stage_center_tick_config.json').write_text(json.dumps(config))
    pub=data/'research/hourly/publication/live/20261101/2300.json';pub.parent.mkdir(parents=True)
    pub.write_text(json.dumps({'materializer_sha256':m.digest(b'identical-materializer')}))
    monkeypatch.setattr(m,'trusted_research_owner',lambda *a:(roots[0],tmp_path/'ledger',('fixed-main-pin',)))
    validated=[]; monkeypatch.setattr(m,'_release_manifest',lambda app,*a:validated.append(app))
    calls=[]
    def read(**kw):
        calls.append(kw)
        if kw['owner_root']!=roots[3]:raise m.PublicationError('HOURLY_COMPLETION_WITNESS_MISSING')
        return {'fixture_only':True}
    monkeypatch.setattr(m,'read_hourly_attestation',read)
    cutoff=datetime.fromisoformat('2026-11-01T23:30:00+08:00')
    value,evidence=m.read_stage_hourly_attestation(stage_app=stage,data_root=data,date='20261101',slot='2300',mode='LIVE',as_of=cutoff)
    assert value['fixture_only'] and validated==roots[1:]
    assert [r['owner_root'] for r in calls]==roots
    assert all(r['as_of']==cutoff for r in calls)
    assert 'v4_research_historical_owner_release_id=sop' in evidence
    for error in ('HOURLY_COMPLETION_AFTER_AS_OF','HOURLY_COMPLETION_LEDGER_INVALID','HOURLY_PUBLICATION_SOURCE_SHA_MISMATCH'):
        monkeypatch.setattr(m,'read_hourly_attestation',lambda **kw:(_ for _ in ()).throw(m.PublicationError(error)))
        with pytest.raises(m.PublicationError,match=error):m.read_stage_hourly_attestation(stage_app=stage,data_root=data,date='20261101',slot='2300',mode='LIVE',as_of=cutoff)
    config['research_historical_owner_bindings'].append(config['research_historical_owner_bindings'][0])
    (stage/'stage_center_tick_config.json').write_text(json.dumps(config))
    with pytest.raises(m.PublicationError,match='ALLOWLIST_INVALID'):m.read_stage_hourly_attestation(stage_app=stage,data_root=data,date='20261101',slot='2300',mode='LIVE',as_of=cutoff)


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    candidate=os.environ.get('F10_BINDING_CANDIDATE'); replay=os.environ.get('F10_BINDING_REPLAY')
    if not candidate or not replay:pytest.skip('Explicit prepared candidate/replay paths required')
    receipt=json.loads((Path(candidate)/'candidate_receipt.json').read_bytes())
    app=Path(receipt['roles']['stage']['app_root']); original=json.loads((app/'stage_center_tick_config.json').read_bytes())
    data=tmp_path/'data';ledger=tmp_path/'ledger';data.mkdir();ledger.mkdir()
    sample=json.loads(Path(replay).read_bytes())['samples'][0]
    assert sample['status']=='PASS_READ_ONLY_HISTORICAL_REPLAY'
    for name,digest in sample['reads'].items():
        source=Path(name);relative=source.relative_to(original['v4_research_data_root']);target=data/relative
        raw=source.read_bytes();assert m.digest(raw)==digest
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    shutil.copy2(Path(original['v4_research_data_root'])/'manifest.json',data/'manifest.json')
    folder=Path('receipts/live/20261101/2300')
    shutil.copytree(Path(original['research_scheduler_ledger_root'])/folder,ledger/folder)
    stage=tmp_path/'fixture-stage'/'app';stage.mkdir(parents=True)
    for relative in m._STAGE_RESEARCH_FILES:
        target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(app/relative,target)
    # Original source evidence includes absolute owned-root paths: retain that exact
    # read-only root for full-chain cases, and mutate only the separate ledger copy.
    config=copy.deepcopy(original);config.update(research_scheduler_ledger_root=str(ledger),release_id=stage.parent.name)
    manifest=json.loads((app.parent/'release-manifest.json').read_bytes())
    def seal():
        (stage/'stage_center_tick_config.json').write_bytes(m.encoded(config))
        entries=inventory_tree(stage);manifest.update(app_root=str(stage),release_id=stage.parent.name)
        if 'candidate' in manifest:manifest['candidate'].update(app_root=str(stage),root=str(stage.parent),release_id=stage.parent.name)
        manifest['application_inventory']={'entries':entries,'entry_count':len(entries),'aggregate_sha256':inventory_digest(entries)}
        (stage.parent/'release-manifest.json').write_bytes(m.encoded(manifest))
        for k,v in {'V4_APP_ROOT':str(stage),'V4_RELEASE_ID':stage.parent.name,'STAGE_CENTER_CONFIG':str(stage/'stage_center_tick_config.json'),'V4_RELEASE_MANIFEST_PATH':str(stage.parent/'release-manifest.json'),'V4_RELEASE_MANIFEST_SHA256':m.digest(m.encoded(manifest))}.items():monkeypatch.setenv(k,v)
    seal()
    def read(cutoff='2026-11-01T23:59:59+08:00'):
        return m.read_stage_hourly_attestation(stage_app=stage,data_root=Path(config['v4_research_data_root']),date='20261101',slot='2300',mode='LIVE',as_of=m.aware(cutoff))
    def dispatch(release):
        files=list((ledger/folder).glob('*.dispatch-receipt.json'));assert len(files)==1
        value=json.loads(files[0].read_bytes());value['release_id']=release
        value['ledger_sha256']=m.digest(m.encoded({k:v for k,v in value.items() if k!='ledger_sha256'})[:-1])
        files[0].write_bytes(m.encoded(value))
    return {'read':read,'seal':seal,'dispatch':dispatch,'config':config,'data':data,'stage':stage,'receipt':receipt}


def test_fixture_f10_full_publication_and_original_witness_contract(isolated):
    f=isolated; f['dispatch'](f['config']['research_owner_binding']['release_id'])
    # Paired reproduction: the same F10 fixture cannot pass the old r6 binding.
    original=copy.deepcopy(f['config'])
    f['config']['research_owner_binding']=f['config']['research_historical_owner_bindings'].pop(0)
    f['seal']()
    with pytest.raises(m.PublicationError,match='HOURLY_COMPLETION_WITNESS_MISSING'):f['read']()
    f['config'].clear();f['config'].update(original);f['seal']()
    value,evidence=f['read']()
    assert value['completion_witness']['release_id']==f['config']['research_owner_binding']['release_id']
    assert not any('historical_owner_release_id' in s for s in evidence)
    assert value['completion_witness']['whole_ledger_malicious_rewrite_authenticated'] is False


def test_fixture_r6_historical_full_chain_still_readable(isolated):
    value,evidence=isolated['read']()
    assert value['completion_witness']['release_id']=='workbench-daily-chain-20261031-r6-main'
    assert 'v4_research_historical_owner_release_id=workbench-daily-chain-20261031-r6-main' in evidence


@pytest.mark.parametrize('mutation,expected',[
    ('unknown_release','HOURLY_COMPLETION_WITNESS_MISSING'),
    ('fourth_history','HOURLY_PROVENANCE_ALLOWLIST_INVALID'),
    ('duplicate_history','HOURLY_PROVENANCE_ALLOWLIST_INVALID'),
    ('bad_owner_manifest','RESEARCH_RELEASE_MANIFEST_SHA_MISMATCH'),
    ('bad_stage_config','RESEARCH_RELEASE_CODE_OR_CONFIG_DRIFT'),
    ('bad_input_sha','HOURLY_PUBLICATION_INPUT_SHA_MISMATCH'),
    ('late_publication','HOURLY_PUBLICATION_AFTER_AS_OF'),
    ('late_completion','HOURLY_COMPLETION_AFTER_AS_OF'),
])
def test_fixture_strict_rejections(isolated,mutation,expected):
    f=isolated;cutoff='2026-11-01T23:59:59+08:00'
    if mutation=='unknown_release':f['dispatch']('unapproved-fixture-release')
    elif mutation=='fourth_history':f['config']['research_historical_owner_bindings'].append(copy.deepcopy(f['config']['research_historical_owner_bindings'][0]));f['seal']()
    elif mutation=='duplicate_history':f['config']['research_historical_owner_bindings'][1]=copy.deepcopy(f['config']['research_historical_owner_bindings'][0]);f['seal']()
    elif mutation=='bad_owner_manifest':f['config']['research_owner_binding']['manifest_sha256']='0'*64;f['seal']()
    elif mutation=='bad_stage_config':
        p=f['stage']/'stage_center_tick_config.json';p.write_bytes(p.read_bytes()+b' ')
    elif mutation=='bad_input_sha':
        f['config']['v4_research_data_root']=str(f['data']);f['seal']()
        p=f['data']/'research/incoming/20261101/2300.json';p.write_bytes(p.read_bytes()+b' ')
    elif mutation=='late_publication':cutoff='2026-11-01T23:00:12.100000+08:00'
    elif mutation=='late_completion':cutoff='2026-11-01T23:00:12.160000+08:00'
    with pytest.raises(m.PublicationError,match=expected):f['read'](cutoff)
