import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_hk_history_resolution import install_resolution, record
import test_hk_research_history as legacy_fixture
from upstreams.v3_shared_data.shared_data.hk_history_resolution import ResolutionError
from v4.manager_workbench.api import create_router
import pytest
import ast
import hashlib
import csv
import io
import os


def frozen_functions(relative, names, globals):
    path=Path(__file__).resolve().parents[1]/relative
    if os.environ.get('V4_HK_TEST_MATERIALIZER_APP') and relative.startswith('ops/'):
        path=Path(os.environ['V4_HK_TEST_MATERIALIZER_APP'])/relative
    if os.environ.get('V4_HK_TEST_REVIEWCORE_APP') and relative.startswith('upstreams/review_core/'):
        path=Path(os.environ['V4_HK_TEST_REVIEWCORE_APP'])/relative.removeprefix('upstreams/')
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    selected=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[])
    exec(compile(selected,str(path),'exec'),globals)
    return globals


def test_reviewcore_exact_pool_gate_preserves_namespace_and_rejects_missing_stale(monkeypatch,tmp_path):
    import os, sys
    import upstreams.v3_shared_data.shared_data.hk_history_resolution as resolver
    package=Path(resolver.__file__).parents[1]
    monkeypatch.setenv('V35_SHARED_PACKAGE_ROOT',str(package))
    provenance={'panel_sha256':'a'*64}
    pool=SimpleNamespace(run=SimpleNamespace(manifest={'provenance':provenance}),rows=[{'code_norm':'HK.00001'}])
    calls=[]
    class Helper:
        def verify_pool_quality(self,*args):calls.append(args)
    g=frozen_functions('upstreams/review_core/hk_sources.py',{'default_model_loader','_hk_resolution_helper'},
        dict(Path=Path,os=os,Any=object,StoreError=ValueError,import_shared=lambda name:SimpleNamespace(read_verified_hk_0_2_pool=lambda *a,**k:pool)))
    before=list(sys.path);names={key:value for key,value in sys.modules.items() if key.startswith('shared_data')}
    helper=g['_hk_resolution_helper']()
    assert helper.RULE==resolver.RULE and list(sys.path)==before
    assert {key:value for key,value in sys.modules.items() if key.startswith('shared_data')}==names
    g['_hk_resolution_helper']=lambda:Helper()
    assert g['default_model_loader'](tmp_path,'20261015','20261014') is pool
    assert calls==[(tmp_path,provenance,'20261014',['HK.00001'])]
    for reason in ['MISSING','STALE','MISMATCH']:
        def fail(*args,reason=reason):raise ResolutionError('HK_HISTORY_RESOLUTION_'+reason)
        g['_hk_resolution_helper']=lambda:SimpleNamespace(verify_pool_quality=fail)
        with pytest.raises(ResolutionError,match=reason):g['default_model_loader'](tmp_path,'20261015','20261014')


def test_materializer_quality_precedes_existing_return_and_publish():
    path=Path(__file__).resolve().parents[1]/'ops/materialize_manager_close_discovery.py'
    node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='recapture_close_minutes')
    text=ast.get_source_segment(path.read_text(),node)
    assert text.index("expected_pool=value['pool']") < text.index("'ALREADY_EXISTS'")
    assert text.index('expected_pool=pool') < text.index('payload_raw=encoded(payload)')


def test_materializer_exact_run_clean_reuse_missing_stale_and_mismatch(tmp_path):
    import re
    from datetime import datetime
    class EvidenceError(ValueError):
        def __init__(self,message,**kwargs):super().__init__(message)
    digest=lambda raw:hashlib.sha256(raw).hexdigest()
    role='HK_CONNECT_D1_TOP100_0_2';run=tmp_path/'runs/20261015'/role/'fixed';run.mkdir(parents=True)
    rows=[dict(code=f'HK.{i:05d}',rank=i,target_date='20261015',signal_date='20261014',
        recommendation_status='WATCH_ONLY_BACKTEST_GATED',production_allowed='false',score_prob_active=1) for i in range(1,101)]
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    raw=stream.getvalue().encode();artifact=run/'pool.csv';artifact.write_bytes(raw)
    manifest=dict(schema_version='v3_shared_data.manifest.v1',market='HK_CONNECT',stage_id='D1_PREMARKET',trade_date='20261015',
        signal_date='20261014',row_count=100,source_id='hkconnect_0_2_frozen_prob_active',captured_at='2026-10-14T17:00:00+08:00',
        artifact_relative=artifact.relative_to(tmp_path).as_posix(),artifact_sha256=digest(raw),provenance=dict(source_contract='tdx_vipdoc_71_day_prob_active'))
    (run/'manifest.json').write_text(json.dumps(manifest))
    receipt=dict(schema_version='v3_shared_data.receipt.v1',status='READY',owner='v3_shared_data',role=role,trade_date='20261015',
        run_id='fixed',artifact_sha256=digest(raw),manifest_sha256=digest((run/'manifest.json').read_bytes()),
        production_allowed=False,buy_gate_updated=False,orders_sent=False)
    (run/'receipt.json').write_text(json.dumps(receipt))
    calls=[]
    g=frozen_functions('ops/materialize_manager_close_discovery.py',{'_read_close_recapture_pool'},dict(Path=Path,re=re,csv=csv,
        digest=digest,load=lambda p:json.loads(p.read_text()),resolve=lambda root,rel:root/rel,EvidenceError=EvidenceError,
        aware=datetime.fromisoformat,PublicationError=ValueError,_resolution_pool_quality=lambda *args:calls.append(args)))
    identity,selected=g['_read_close_recapture_pool'](tmp_path,'20261015')
    assert len(selected)==100 and len(calls)==1
    # Another run must not replace the pinned run during ALREADY_EXISTS reuse.
    (run.parent/'another').mkdir();(run.parent/'another/manifest.json').write_text('{}')
    assert g['_read_close_recapture_pool'](tmp_path,'20261015',expected_pool=identity)[0]==identity
    for reason in ['MISSING','STALE']:
        def fail(*args,reason=reason):raise ResolutionError('HK_HISTORY_RESOLUTION_'+reason)
        g['_resolution_pool_quality']=fail
        with pytest.raises(ResolutionError,match=reason):g['_read_close_recapture_pool'](tmp_path,'20261015',expected_pool=identity)
    g['_resolution_pool_quality']=lambda *args:None
    with pytest.raises(EvidenceError,match='PIN_MISMATCH'):
        g['_read_close_recapture_pool'](tmp_path,'20261015',expected_pool=dict(identity,artifact_sha256='0'*64))


def test_scorer_empty_clean_proxy_universe_is_typed_hold_before_model(tmp_path):
    fixture=legacy_fixture.HKResearchHistoryTests();fixture.setUp()
    try:
        owner,_,_=fixture._owned_fixture([legacy_fixture._b_row('HK.00001','2026-01-02',10.0)],
            [legacy_fixture._c_row('HK.00001',20260102,10.0)])
        import pandas as pd
        pointer=json.loads((owner/'panel_latest.json').read_text())
        manifest_path=owner/pointer['manifest_relative'];manifest=json.loads(manifest_path.read_text())
        panel_path=owner/manifest['panel_relative'];panel=pd.read_parquet(panel_path)
        panel['trade_date_compact']=panel['trade_date'].astype(str)
        panel.to_parquet(panel_path,index=False)
        manifest['panel_sha256']=hashlib.sha256(panel_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        contract=install_resolution(owner,[])
        from upstreams.v3_shared_data.shared_data.hk_history_resolution import ResolutionPolicy,guard_score_frame
        source='upstreams/v3_shared_data/shared_data/hk_0_2.py'
        app=os.environ.get('V4_HK_TEST_SHARED_APP')
        if app:
            path=Path(app)/'shared_data/hk_0_2.py'
            tree=ast.parse(path.read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='score_frozen_hk_0_2')
        else:
            path=Path(__file__).resolve().parents[1]/source
            tree=ast.parse(path.read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='score_frozen_hk_0_2')
        g=dict(Path=Path,Any=object,Iterable=list,validate_date=lambda v:v,StoreError=ValueError,ResolutionPolicy=ResolutionPolicy,
            guard_score_frame=guard_score_frame,_add_daily_features=lambda frame:frame,_add_proxy_labels=lambda frame:(frame,{}),
            load_frozen_hk_0_2_assets=lambda root:SimpleNamespace(root=owner,panel_path=owner/contract['bindings']['C_panel_relative'],
                panel_manifest=dict(panel_sha256=contract['bindings']['C_panel_sha256'])))
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),g)
        diagnostics={}
        with pytest.raises(ValueError,match='HK_HISTORY_RESOLUTION_PROXY_UNIVERSE_INSUFFICIENT'):
            g['score_frozen_hk_0_2'](owner,signal_date='20260102',target_date='20260103',diagnostics=diagnostics)
        assert diagnostics['history_resolution_score_status']=='HOLD'
        assert diagnostics['history_resolution_scoreable_count']==0
    finally:fixture.doCleanups()


def test_append_current_binding_available_to_API_D1_and_dependency_readers():
    import pandas as pd
    from upstreams.v3_shared_data.shared_data.hk_history_resolution import ResolutionPolicy,guard_score_frame,guard_rebound_frame
    from upstreams.v3_shared_data.shared_data.hk_d1_evidence import read_verified_hk_d1_evidence
    fixture=legacy_fixture.HKResearchHistoryTests();fixture.setUp()
    try:
        owner,_,_=fixture._owned_fixture([legacy_fixture._b_row('HK.00001','2026-01-02',10.0)],
            [legacy_fixture._c_row('HK.00001',20260102,10.0)])
        manifest_path=owner/'panels/v1/manifest.json';manifest=json.loads(manifest_path.read_text())
        source=owner/manifest['panel_relative'];base=pd.read_parquet(source)
        base['trade_date_compact']=base.trade_date.astype(str);base['pre_close']=10.0;base['pct_chg']=0.0
        base.to_parquet(source,index=False)
        manifest.update(panel_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),panel_max_date='20260102',
            source_contract='NATIVE_APPEND_FIXTURE',increment_contract='EXACT_APPEND_V1')
        manifest_path.write_text(json.dumps(manifest));install_resolution(owner,[])
        old=ResolutionPolicy(owner);old_token=old.encode_proof(old.proof(required_fields=('close',),start='20260102',end='20260102',consumer='old'))
        future=base.copy();future['trade_date']=20260103;future['trade_date_compact']='20260103'
        current=pd.concat([base,future],ignore_index=True);folder=owner/'panels/v2';folder.mkdir()
        current.to_parquet(folder/'panel.parquet',index=False)
        manifest.update(panel_relative='panels/v2/panel.parquet',panel_sha256=hashlib.sha256((folder/'panel.parquet').read_bytes()).hexdigest(),panel_rows=2,panel_max_date='20260103')
        (folder/'manifest.json').write_text(json.dumps(manifest));(owner/'panel_latest.json').write_text(json.dumps(dict(manifest_relative='panels/v2/manifest.json')))
        policy=ResolutionPolicy(owner);assert policy.append_proof['status']=='APPEND_ONLY_COMPATIBLE'
        with pytest.raises(ResolutionError,match='STALE'):policy.verify_proof(old_token,required_fields=('close',))
        app=FastAPI();app.include_router(create_router(SimpleNamespace(config=SimpleNamespace(shared_root=fixture.root))))
        with TestClient(app) as client:
            result=client.get('/api/v4/manager-workbench/hk-history',params=dict(symbol='HK.00001',start='20260103',end='20260103'))
            assert result.status_code==200 and len(result.json()['data']['rows'])==1
        rows,proof=read_verified_hk_d1_evidence(fixture.root,target_trade_date='20260104')
        assert len(rows)==1 and proof['panel_sha256']==manifest['panel_sha256']
        assert len(guard_score_frame(current,policy,'20260103'))==2
        rebound=guard_rebound_frame(current,fixture.root,panel_sha256=manifest['panel_sha256'],
            sessions=dict(prior60=['20260102'],previous5=['20260102']),current_day='20260103')
        assert len(rebound)==2 and len(rebound.attrs['history_resolution_proofs'])==3
        # Same guard declarations used before the actual oversold calculation.
        assert len(policy.guard_frame(current,required_fields=('high','close'),end='20260103',lookback=61))==2
        assert len(policy.guard_frame(current,required_fields=('trade',),end='20260103',lookback=6))==2
    finally:fixture.doCleanups()


def test_normal_api_filters_held_fields_and_audit_retains_both_sources():
    fixture=legacy_fixture.HKResearchHistoryTests();fixture.setUp()
    try:
        owner,_,_=fixture._owned_fixture(
            [legacy_fixture._b_row('HK.00001','2026-01-02',10.0,trade=10),legacy_fixture._b_row('HK.00001','2026-01-03',11.0,trade=10)],
            [legacy_fixture._c_row('HK.00001',20260102,10.0,trade=1000),legacy_fixture._c_row('HK.00001',20260103,11.0,trade=1000)])
        install_resolution(owner,[record('HK.00001','20260102',held=('trade',)),
                                  record('HK.00001','20260103',confirmed=('trade',))])
        app=FastAPI();app.include_router(create_router(SimpleNamespace(config=SimpleNamespace(shared_root=fixture.root))))
        params=dict(symbol='HK.00001',start='20260102',end='20260103')
        with TestClient(app) as client:
            usable=client.get('/api/v4/manager-workbench/hk-history',params=params)
            assert usable.status_code==200
            data=usable.json()['data'];assert data['mode']=='usable'
            assert data['quarantine_count']==1 and len(data['rows'])==1
            assert data['rows'][0]['date']=='20260103' and data['rows'][0]['raw_fields']['trade']==1000
            assert data['rows'][0]['counterpart'] is None
            close=client.get('/api/v4/manager-workbench/hk-history',params=dict(params,fields='close')).json()['data']
            assert close['quarantine_count']==0 and len(close['rows'])==2
            assert all(set(row['raw_fields'])=={'close'} for row in close['rows'])
            audit=client.get('/api/v4/manager-workbench/hk-history',params=dict(params,mode='audit')).json()['data']
            assert len(audit['rows'])==2 and audit['rows'][0]['counterpart']['raw_fields']['trade']==10
            assert audit['rows'][0]['raw_fields']['trade']==1000
            assert client.get('/api/v4/manager-workbench/hk-history',params=dict(params,fields='bad')).status_code==422
            (owner/'history_resolution_latest.json').unlink()
            assert client.get('/api/v4/manager-workbench/hk-history',params=params).status_code==503
            assert client.get('/api/v4/manager-workbench/hk-history',params=dict(params,mode='audit')).status_code==200
    finally:
        fixture.doCleanups()


def scheduler_module():
    path=Path(__file__).resolve().parents[1]/'docs/handoffs/hk_conflict_resolution_20261015/source_projection/scheduler/infrastructure/scheduling/executor_registry_preselection.py'
    if os.environ.get('V4_HK_TEST_SCHEDULER_APP'):
        path=Path(os.environ['V4_HK_TEST_SCHEDULER_APP'])/'infrastructure/scheduling/executor_registry_preselection.py'
    spec=importlib.util.spec_from_file_location('candidate_hk_scheduler_gate',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('hk_problem',['missing','partial','status','count','proof'])
def test_actual_scheduler_A_ready_HK_stale_never_runs_or_writes_A(monkeypatch,hk_problem):
    module=scheduler_module()
    def payload(pool_id):
        hk=pool_id=='hkconnect_d1_top100'
        return dict(pool_id=pool_id,market='HK' if hk else 'A',trade_date='20261015',target_date='20261015',
            signal_date='20261014',source_role='SHARED_VERIFIED_HK_0_2' if hk else 'SHARED_VERIFIED_V192',
            stage_selection_eligible=True,status='READY',production_allowed=False,buy_gate_updated=False,orders_sent=False,
            source_sha256='a'*64,rows=[dict(code='HK.'+str(i).zfill(5)) for i in range(1,101)] if hk else [dict(code='600000.SH')])
    a_before=json.dumps(payload('a_d1_premarket_pool'),sort_keys=True)
    def read_pool(date,pool_id):
        value=payload(pool_id)
        if pool_id=='hkconnect_d1_top100':
            if hk_problem=='missing':raise FileNotFoundError('missing HK only')
            if hk_problem=='partial':value['rows']=value['rows'][:62];value['status']='PARTIAL'
            if hk_problem=='status':value['status']='CANNOT_CONFIRM'
            if hk_problem=='count':value['rows']=[]
        return value
    monkeypatch.setattr(module,'PreselectionPoolStore',lambda root:SimpleNamespace(read_pool=read_pool))
    import infrastructure.isolated_package_loader as loader
    def rejected(*args,**kwargs):
        return SimpleNamespace(read_verified_hk_0_2_pool=lambda *a,**k:(_ for _ in ()).throw(ResolutionError('HK_HISTORY_RESOLUTION_CACHE_PROOF_MISSING')))
    monkeypatch.setattr(loader,'load_isolated_package_module',rejected)
    calls=[]
    service=SimpleNamespace(data_root=Path('/synthetic'),shared_data_root=Path('/synthetic'),shared_package_root=Path('/synthetic'),
        _run=lambda *a,**k:calls.append(a))
    service._verified_formal_pool_reuse=lambda date:module._verified_formal_pool_reuse(service,date)
    result=module._preselection_pools(service,SimpleNamespace(target_date='20261015'))
    assert result['a_selector_status']=='READY' and result['hk_lane_status']=='QUARANTINED'
    assert result['producer_called'] is False and result['write_performed'] is False and calls==[]
    assert json.dumps(payload('a_d1_premarket_pool'),sort_keys=True)==a_before


@pytest.mark.parametrize('problem',['PARTIAL100','different_codes','different_rank','exact_match'])
def test_scheduler_cached_HK_must_exactly_project_verified_READY_pool(monkeypatch,problem):
    module=scheduler_module()
    verified_rows=[dict(code_norm=f'HK.{i:05d}',rank=str(i)) for i in range(1,101)]
    a=dict(pool_id='a_d1_premarket_pool',market='A',trade_date='20261015',target_date='20261015',
        source_role='SHARED_VERIFIED_V192',stage_selection_eligible=True,status='READY',rows=[dict(code='600000.SH')],
        production_allowed=False,buy_gate_updated=False,orders_sent=False,source_sha256='a'*64)
    hk=dict(a,pool_id='hkconnect_d1_top100',market='HK',signal_date='20261014',source_role='SHARED_VERIFIED_HK_0_2',
        source_artifact_sha256='b'*64,source_manifest_sha256='c'*64,
        rows=[dict(code=row['code_norm'],rank=int(row['rank'])) for row in verified_rows])
    if problem=='PARTIAL100':hk['status']='PARTIAL'
    if problem=='different_codes':hk['rows']=[dict(code=f'HK.{i+100:05d}',rank=i) for i in range(1,101)]
    if problem=='different_rank':hk['rows'][0]['rank']=2
    before=json.dumps(a,sort_keys=True)
    monkeypatch.setattr(module,'PreselectionPoolStore',lambda root:SimpleNamespace(read_pool=lambda date,pool_id:a if pool_id==a['pool_id'] else hk))
    import infrastructure.isolated_package_loader as loader
    verified=SimpleNamespace(rows=verified_rows,run=SimpleNamespace(verification=dict(artifact_sha256='b'*64,manifest_sha256='c'*64)))
    monkeypatch.setattr(loader,'load_isolated_package_module',lambda *args,**kwargs:SimpleNamespace(read_verified_hk_0_2_pool=lambda *a,**k:verified))
    calls=[]
    service=SimpleNamespace(data_root=Path('/synthetic'),shared_data_root=Path('/synthetic'),shared_package_root=Path('/synthetic'),
        _run=lambda *a,**k:calls.append(a))
    service._verified_formal_pool_reuse=lambda date:module._verified_formal_pool_reuse(service,date)
    if problem=='exact_match':
        result=service._verified_formal_pool_reuse('20261015')
        assert result['status']=='SUCCEEDED' and result['hk_lane_status']=='READY'
    else:
        result=module._preselection_pools(service,SimpleNamespace(target_date='20261015'))
        assert result['hk_lane_status']=='QUARANTINED' and result['a_selector_status']=='READY'
        assert result['hk_quality_rejected'] is True
    assert result['producer_called'] is False and result['write_performed'] is False
    assert calls==[] and json.dumps(a,sort_keys=True)==before


@pytest.mark.parametrize('problem',['PARTIAL100','duplicate_codes','different_rank','exact_match'])
def test_canonical_scheduler_source_only_HK_projection(problem):
    import builtins
    rows=[dict(code_norm=f'HK.{i:05d}',rank=str(i)) for i in range(1,101)]
    if problem=='duplicate_codes':rows[1]['code_norm']=rows[0]['code_norm']
    if problem=='different_rank':rows[0]['rank']='2'
    pool=SimpleNamespace(rows=rows,run=SimpleNamespace(receipt=dict(status='PARTIAL' if problem=='PARTIAL100' else 'READY',
        production_allowed=False,buy_gate_updated=False,orders_sent=False,run_id='synthetic'),
        verification=dict(artifact_sha256='a'*64,row_count=100)))
    scope=dict(load_isolated_package_module=lambda *a,**k:SimpleNamespace(read_verified_hk_0_2_pool=lambda *a,**k:pool))
    def read_global(scope,name):return scope[name] if name in scope else getattr(builtins,name)
    name='_FixedExecutorRegistry__verified_preselection_source_body'
    g=frozen_functions('infrastructure/scheduling/_executor_registry_parts/preselection.py',{name},dict(_v4_global=read_global))
    result,reason=g[name](scope,SimpleNamespace(shared_data_root=Path('/synthetic'),shared_package_root=Path('/synthetic')),
        module_leaf='hk_0_2',reader_name='read_verified_hk_0_2_pool',target_date='20261015',signal_date='20261014')
    if problem=='exact_match':assert result['status']=='READY' and reason==''
    else:assert result is None and reason
