"""Focused checks for the HK-only API release adapter."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'ops/hk_window_api_release.py'
spec = importlib.util.spec_from_file_location('hk_window_api_release_test', PATH)
hk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hk)


def test_reviewed_worktree_and_live_before_match():
    # The original resolver remains bound to its existing proof.
    hk.verify_sources()


def test_frozen_stage_rejects_replaced_allowlist(tmp_path, monkeypatch):
    old = tmp_path / 'old.json'
    old.write_text(json.dumps({'stocks': {'example': {'rows': 3}}}))
    stage_path = tmp_path / 'stage.json'
    monkeypatch.setattr(hk, 'STAGE', stage_path)
    monkeypatch.setattr(hk, 'EDAN_STAGE', old)
    monkeypatch.setattr(hk, 'reference', lambda path, digest: {'path': str(path), 'sha256': digest})
    monkeypatch.setattr(hk, 'verify_sources', lambda: None)
    stage = {'schema':'v4.hk_window_api.stage.v1','target':str(hk.TARGET),
             'source_commit':hk.REVIEWED_COMMIT,'operator_sha256':hk.sha(PATH.read_bytes()),
             'changes':hk.changes(),'review':hk.reference(hk.REVIEW,hk.REVIEW_SHA),
             'owner':hk.reference(hk.OWNER,hk.OWNER_SHA),
             'old_stage':hk.reference(old,hk.EDAN_STAGE_SHA),
             'stocks':{'example':{'rows':3}},
             'new_binding':hk.reference(hk.BASE/'config/workbench-binding.json',hk.BINDING_SHA),
             'asset_manifest':hk.reference(hk.BASE/'research-panel-assets.json',hk.ASSET_SHA),
             'resolver_sha256':hk.RESOLVER_SHA,
             'base':{'root':str(hk.BASE),'plist_sha256':hk.PLIST_SHA,'manifest_sha256':hk.BASE_MANIFEST_SHA,
                     'app_inventory_sha256':hk.BASE_APP_INVENTORY_SHA,'site_inventory_sha256':hk.BASE_SITE_INVENTORY_SHA,
                     'process':{'pid':49683}},
             'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    def write(value):
        stage_path.write_text(json.dumps(value))
        return hashlib.sha256(stage_path.read_bytes()).hexdigest()
    assert hk.load_stage(write(stage))['changes'] == hk.changes()
    altered = copy.deepcopy(stage)
    altered['changes'].append({'kind':'api','path':'other.py'})
    with pytest.raises(ValueError,match='STAGE_IDENTITY_CHANGED'):
        hk.load_stage(write(altered))


def test_http_wrapper_rejects_f10_drift(monkeypatch):
    state={'version':'old'}
    owner=SimpleNamespace(verify_http=lambda *a,**kw:{'pool_rows':172,'single_research':{'x':'PASS'}})
    monkeypatch.setattr(hk,'f10',lambda owner,port:{'sample':state['version']})
    expected={'pool_rows':172,'single_research':{'x':'PASS'},'canonical_f10':{'sample':'old'}}
    hk.install_http(owner,expected)
    assert owner.verify_http(1,release_id='x',manifest_sha='y',single=False)==expected
    state['version']='new'
    with pytest.raises(ValueError,match='LIVE_CONTENT_CHANGED'):
        owner.verify_http(1,release_id='x',manifest_sha='y',single=True)


def test_existing_delta_guard_rejects_unlisted_changes(tmp_path):
    owner=hk.load_owner()
    tools=owner.official_tools()
    before=tmp_path/'base';after=tmp_path/'candidate';before.mkdir();after.mkdir()
    (before/'changed.py').write_text('old\n');(after/'changed.py').write_text('new\n')
    (before/'held.py').write_text('keep\n');(after/'held.py').write_text('keep\n')
    raw_before=(before/'changed.py').read_bytes();raw_after=(after/'changed.py').read_bytes()
    digest,count=tools._diff_proof(raw_before,raw_after)
    entries=[{'path':'changed.py','before_sha256':hk.sha(raw_before),'after_sha256':hk.sha(raw_after),
              'unified_diff_sha256':digest,'unified_diff_hunk_count':count}]
    records,preserved=tools._verify_delta_files(base_app=before,candidate_app=after,entries=entries)
    assert len(records)==1 and [x['path'] for x in preserved]==['held.py']
    (after/'held.py').write_text('silently modified\n')
    with pytest.raises(ValueError,match='UNLISTED_FILE_CHANGED'):
        tools._verify_delta_files(base_app=before,candidate_app=after,entries=entries)


def test_candidate_manifest_keeps_prior_provenance():
    base={'research_panel':{'root':'old','asset_manifest':'old','asset_count':7},
          'source_commit':'prior-commit','source_provenance':{'base':'original'},
          'junda_single_integration':{'retained':'yes'},'other':{'preserved':True}}
    tools=SimpleNamespace(inventory_digest=lambda entries:'inventory-sha')
    result=hk.candidate_manifest(base,[{'path':'one'}],{'api':'proof'},'delta-sha','stage-sha',tools)
    assert result['source_commit']=='prior-commit'
    assert result['source_provenance']==base['source_provenance']
    assert result['junda_single_integration']==base['junda_single_integration']
    assert result['other']==base['other']
    assert result['hk_window_integration']['reviewed_commit']==hk.REVIEWED_COMMIT
    assert base['research_panel']['root']=='old'
