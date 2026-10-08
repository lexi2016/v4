"""SIMULATED local fixtures; no real market store or live Mac/API evidence."""
from datetime import datetime
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import time
import pytest
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research import workspace, workspace_plan

DATE='20260922'
NOW=datetime.fromisoformat('2026-09-23T10:20:00+08:00')
CUTOFF=datetime.fromisoformat('2026-09-22T08:40:00+08:00')

@pytest.fixture
def service(tmp_path):
    s=ManagerResearchJobService(ManagerResearchStore(tmp_path/'manager'),None,None)
    yield s
    s.close()


def test_history_missing_does_not_scan_live_owners(service,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('history missing must not recompute live inputs')
    monkeypatch.setattr(service,'get_catalyst_observations',forbidden)
    before=sorted(p for p in service.store.root.rglob('*') if p.is_file())
    result=service.get_workspace(DATE,view='historical',now=NOW)
    assert result['read_context']['mode']=='HISTORICAL_AS_OF'
    assert result['read_context']['status']=='NOT_MATERIALIZED'
    assert result['read_context']['candidate_count_known'] is False
    assert result['stocks']==[] and result['plan_product']['consumed'] is False
    assert result['plan_context']['research_cutoff'].startswith('2026-09-22T')
    assert sorted(p for p in service.store.root.rglob('*') if p.is_file())==before


def test_history_corrupted_saved_plan_rejected_before_owner_scan(service,monkeypatch):
    p=service.store.root/'workspace_plans'/DATE/'latest.json'
    service.store._write_atomic(p,{'sha256':'0'*64})
    monkeypatch.setattr(service,'get_catalyst_observations',lambda *a:pytest.fail('must stop before owner reads'))
    result=service.get_workspace(DATE,view='historical',now=NOW)
    assert result['read_context']['status']=='SOURCE_FAILED'
    assert result['stocks']==[]


def test_auto_history_and_explicit_dynamic_are_distinct(service):
    history=service.get_workspace(DATE,view='auto',now=NOW)
    current=service.get_workspace(DATE,view='dynamic',now=NOW)
    assert history['read_context']['mode']=='HISTORICAL_AS_OF'
    assert current['read_context']['mode']=='CURRENT_DYNAMIC_PREVIEW'
    assert current['plan_context']['research_cutoff']=='2026-09-23T10:20:00+08:00'


def test_exact_panel_selected_without_latest_substitution(tmp_path):
    asset=tmp_path/'assets/hk_0_2'
    raw=b'SIMULATED PANEL BYTES, not a parquet'
    sha=hashlib.sha256(raw).hexdigest()
    directory=asset/'panels'/f'20260921-{sha[:12]}'
    directory.mkdir(parents=True)
    (directory/'hkconnect_vipdoc_daily_panel.parquet').write_bytes(raw)
    manifest=dict(asset_schema_version='v3_shared_data.hk_0_2_panel_asset.v2',
        source_contract='tdx_vipdoc_71_day+verified_zero_trade_repairs',panel_max_date='20260921',
        panel_relative=f'panels/{directory.name}/hkconnect_vipdoc_daily_panel.parquet',panel_sha256=sha,
        research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    (directory/'manifest.json').write_text(json.dumps(manifest))
    (asset/'panel_latest.json').write_text(json.dumps({'manifest_relative':'panels/20260922-invalid/manifest.json'}))
    witness,gaps=workspace_plan._read_hk02_panel_witness(tmp_path,'20260921')
    assert witness and witness['panel_max_date']=='20260921',gaps
    assert witness['resolution']=='EXACT_DATE_IMMUTABLE_OWNER_ASSET'
    missing,gaps=workspace_plan._read_hk02_panel_witness(tmp_path,'20260918')
    assert missing is None and 'PLAN_HK_02_EXACT_DATE_PANEL_MISSING' in gaps


def save_legacy_plan(service, monkeypatch):
    """Exercise the actual original POST writer with a SIMULATED fixed clock."""
    original=workspace.plan_context
    with monkeypatch.context() as m:
        m.setattr(workspace,'plan_context',lambda date,**kw:original(date,now=CUTOFF))
        m.setattr(workspace,'_now',lambda:CUTOFF.isoformat())
        result=service.refresh_workspace_plan(DATE)
    return result


def test_saved_history_uses_frozen_cutoff_not_next_day_now(service,monkeypatch):
    save_legacy_plan(service,monkeypatch)
    result=service.get_workspace(DATE,view='historical',now=NOW)
    assert result['plan_product']['consumed'] is True
    assert result['plan_context']['research_cutoff']==CUTOFF.isoformat()
    assert result['read_context']['candidate_count_known'] is False # missing owners are not successful zero
    assert 'historical_owner_revalidation' in result['read_metrics']['stages']


def test_saved_resealed_business_mutation_does_not_bypass_source_replay(service,monkeypatch):
    save_legacy_plan(service,monkeypatch)
    p=service.store.root/'workspace_plans'/DATE/'latest.json'
    row=service.store._read(p)
    row['workspace']['briefing']['headline']='tampered but resealed opinion'
    row['sha256']=workspace.digest({k:v for k,v in row.items() if k!='sha256'})
    service.store._write_atomic(p,row)
    result=service.get_workspace(DATE,view='historical',now=NOW)
    assert result['read_context']['status']=='SOURCE_FAILED'
    assert result['read_context']['reason']=='HISTORY_FROZEN_PROJECTION_CHANGED'


def test_later_dynamic_saved_plan_does_not_mask_prior_run(service,monkeypatch):
    first=save_legacy_plan(service,monkeypatch)
    service.refresh_workspace_plan(DATE) # intentionally a current retrospective snapshot
    result=service.get_workspace(DATE,view='historical',now=NOW)
    assert result['plan_product']['consumed'] is True
    assert result['plan_product']['run_id']==first['plan_product']['run_id']


def test_reader_version_change_without_saved_contract_rejects_before_replay(service,monkeypatch):
    save_legacy_plan(service,monkeypatch)
    p=service.store.root/'workspace_plans'/DATE/'latest.json'
    row=service.store._read(p)
    row['workspace'].pop('read_context')
    row['sha256']=workspace.digest({k:v for k,v in row.items() if k!='sha256'})
    service.store._write_atomic(p,row)
    from v4.manager_research import workspace_history
    monkeypatch.setattr(workspace_history,'contract_identity',lambda:'0'*64)
    monkeypatch.setattr(workspace,'_compute_workspace',lambda *a,**k:pytest.fail('unproven contract must not replay'))
    result=service.get_workspace(DATE,view='historical',now=NOW)
    assert result['plan_product']['consumed'] is False
    assert result['read_context']['reason']=='HISTORY_READ_CONTRACT_UNPROVEN'


def test_announcement_invalid_store_cannot_hide_behind_saved_plan(service,monkeypatch):
    save_legacy_plan(service,monkeypatch)
    first=service.get_workspace(DATE,view='historical',now=NOW)
    assert first['plan_product']['consumed']
    service.store._write_atomic(service.store.root/'workspace_announcements'/DATE/'latest.json',
        {'sha256':'e'*64,'risk_alerts':[]})
    second=service.get_workspace(DATE,view='historical',now=NOW)
    assert second['read_context']['status']=='SOURCE_FAILED' and second['stocks']==[]


def test_pit_missing_availability_is_not_historical_known_fact(service,monkeypatch):
    save_legacy_plan(service,monkeypatch)
    p=service.store.root/'workspace_plans'/DATE/'latest.json'
    row=service.store._read(p)
    row['workspace']['materials']=[dict(published_at='2026-09-21T20:00:00+08:00',available_at=None,retrieved_at=None)]
    row['sha256']=workspace.digest({k:v for k,v in row.items() if k!='sha256'})
    service.store._write_atomic(p,row)
    result=service.get_workspace(DATE,view='historical',now=NOW)
    assert result['read_context']['reason']=='HISTORY_MATERIAL_PIT_UNVERIFIED'


def test_api_default_is_auto_history_not_dynamic(service):
    import asyncio,httpx
    from fastapi import FastAPI
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    app=FastAPI();app.include_router(create_manager_research_router(service))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            r=await c.get('/api/v4/manager/research/workspace?date='+DATE)
            assert r.status_code==200
            assert r.json()['read_context']['mode']=='HISTORICAL_AS_OF'
            wrong=await c.get('/api/v4/manager/research/workspace?date='+DATE+'&view=latest')
            assert wrong.status_code==422
    asyncio.run(run())

@pytest.mark.parametrize('key,value',[('schema_version','WRONG'),('orders_sent',True),('owner','FAKE_OWNER'),('input_identity','f'*64)])
def test_saved_resealed_metadata_cannot_bypass_gate(service,monkeypatch,key,value):
    save_legacy_plan(service,monkeypatch)
    p=service.store.root/'workspace_plans'/DATE/'latest.json';row=service.store._read(p)
    row[key]=value;row['sha256']=workspace.digest({k:v for k,v in row.items() if k!='sha256'});p.write_text(json.dumps(row)) # attacker bypasses safe writer
    assert service.get_workspace(DATE,view='historical',now=NOW)['read_context']['status']=='SOURCE_FAILED'


def test_real_legacy_v1_without_reader_fingerprint_still_revalidates(service,monkeypatch):
    save_legacy_plan(service,monkeypatch)
    p=service.store.root/'workspace_plans'/DATE/'latest.json';row=service.store._read(p)
    row.pop('read_contract_sha256');row['sha256']=workspace.digest({k:v for k,v in row.items() if k!='sha256'});service.store._write_atomic(p,row)
    result=service.get_workspace(DATE,view='historical',now=NOW)
    assert result['plan_product']['consumed'] and result['read_context']['legacy_full_revalidation']
    assert 'announcement_source_validation' in result['read_metrics']['stages']


@pytest.mark.parametrize('field',['published_at','available_at','retrieved_at'])
def test_after_cutoff_field_never_admitted_as_historical_material(service,monkeypatch,field):
    save_legacy_plan(service,monkeypatch)
    p=service.store.root/'workspace_plans'/DATE/'latest.json';row=service.store._read(p)
    m=dict(published_at=CUTOFF.isoformat(),available_at=CUTOFF.isoformat(),retrieved_at=CUTOFF.isoformat())
    m[field]=NOW.isoformat();row['workspace']['materials']=[m]
    row['sha256']=workspace.digest({k:v for k,v in row.items() if k!='sha256'});service.store._write_atomic(p,row)
    assert service.get_workspace(DATE,view='historical',now=NOW)['read_context']['reason']=='HISTORY_MATERIAL_PIT_UNVERIFIED'


def test_saved_plan_symlink_is_rejected(service,tmp_path):
    external=tmp_path/'external.json';external.write_text('{}')
    p=service.store.root/'workspace_plans'/DATE/'latest.json';p.parent.mkdir(parents=True)
    p.symlink_to(external)
    assert service.get_workspace(DATE,view='historical',now=NOW)['read_context']['status']=='SOURCE_FAILED'


def test_exact_panel_changed_bytes_same_size_not_trusted_from_metadata(tmp_path):
    # Witness reads exact SHA each time, not a stat/mtime result cache.
    asset=tmp_path/'assets/hk_0_2';raw=b'SIMULATED ORIGINAL';sha=hashlib.sha256(raw).hexdigest()
    d=asset/'panels'/f'20260921-{sha[:12]}';d.mkdir(parents=True)
    p=d/'hkconnect_vipdoc_daily_panel.parquet';p.write_bytes(raw)
    manifest=dict(asset_schema_version='v3_shared_data.hk_0_2_panel_asset.v2',source_contract='tdx_vipdoc_71_day+verified_zero_trade_repairs',
        panel_max_date='20260921',panel_relative=f'panels/{d.name}/{p.name}',panel_sha256=sha,
        research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    (d/'manifest.json').write_text(json.dumps(manifest))
    assert workspace_plan._read_hk02_panel_witness(tmp_path,'20260921')[0]
    import os
    before=p.stat();p.write_bytes(b'x'*len(raw));os.utime(p,ns=(before.st_atime_ns,before.st_mtime_ns))
    witness,gaps=workspace_plan._read_hk02_panel_witness(tmp_path,'20260921')
    assert witness is None and 'PLAN_HK_02_PANEL_AUTHORITY_CHECKSUM_MISMATCH' in gaps


def test_multiple_exact_panel_revisions_are_not_chosen_by_mtime(tmp_path):
    base=tmp_path/'assets/hk_0_2/panels'
    for prefix in ['a'*12,'b'*12]:(base/('20260921-'+prefix)).mkdir(parents=True)
    witness,gaps=workspace_plan._read_hk02_panel_witness(tmp_path,'20260921')
    assert witness is None and 'PLAN_HK_02_EXACT_DATE_PANEL_AMBIGUOUS' in gaps


@pytest.mark.parametrize('code,status',[('WORKSPACE_READ_TIMEOUT',504),('WORKSPACE_READ_BUSY',503),('WORKSPACE_READ_CANCELLED',499)])
def test_real_asgi_distinguishes_read_outcomes(service,monkeypatch,code,status):
    import asyncio,httpx
    from fastapi import FastAPI
    from v4.manager_research.workspace_read_control import WorkspaceReadError
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    # Simulated worker failure injected at the service boundary; real router and HTTP serialization.
    monkeypatch.setattr(service,'get_workspace',lambda *a,**k:(_ for _ in []).throw(WorkspaceReadError(code)))
    app=FastAPI();app.include_router(create_manager_research_router(service))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            r=await c.get('/api/v4/manager/research/workspace?date='+DATE)
            assert r.status_code==status and r.json()['detail']==code
    asyncio.run(run())

@pytest.mark.parametrize('field,value',[('stocks',[None]),('materials',{}),('briefing',None),('schema_version','WRONG')])
def test_saved_structural_corruption_rejected_before_any_original_owner(service,monkeypatch,field,value):
    save_legacy_plan(service,monkeypatch)
    p=service.store.root/'workspace_plans'/DATE/'latest.json';row=service.store._read(p)
    row['workspace'][field]=value;row['sha256']=workspace.digest({k:v for k,v in row.items() if k!='sha256'});p.write_text(json.dumps(row))
    monkeypatch.setattr(service,'get_catalyst_observations',lambda *a:pytest.fail('malformed saved schema must fail before source scan'))
    assert service.get_workspace(DATE,view='historical',now=NOW)['read_context']['status']=='SOURCE_FAILED'
