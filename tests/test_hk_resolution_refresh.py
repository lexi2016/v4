"""HK-only correction publication CAS must preserve A and exact source identity."""
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
import importlib.util
from domains.preselection_materializer import build_shared_hk_0_2_pool,build_expected_missing_pool
from infrastructure.preselection_pool_store import PreselectionPoolStore
import infrastructure.isolated_package_loader as loader
import upstreams.v3_shared_data.shared_data.hk_history_resolution as resolution


@pytest.fixture
def refresh_case(tmp_path,monkeypatch):
    token='b64url.test';identity=hashlib.sha256(token.encode()).hexdigest()
    source_rows=[dict(code_norm=f'HK.{i:05d}',rank=str(i),name=f'Name{i}',score_prob_active=1-i/1000,
        signal_date='20261014',target_date='20261015',d1_freshness_status='PASS',selected_strategy='prob_active',history_resolution_identity=identity) for i in range(1,101)]
    verification=dict(artifact_sha256='a'*64,manifest_sha256='b'*64,receipt_sha256='c'*64,run_id='fresh',row_count=100,artifact_relative='runs/20261015/HK_CONNECT_D1_TOP100_0_2/fresh/artifact.csv')
    pool=SimpleNamespace(rows=tuple(source_rows),run=SimpleNamespace(verification=verification,
        receipt=dict(status='READY',production_allowed=False,buy_gate_updated=False,orders_sent=False),
        manifest=dict(provenance=dict(history_resolution_proof=token))))
    module=SimpleNamespace(read_verified_hk_0_2_pool=lambda *a,**kw:pool)
    monkeypatch.setattr(loader,'load_isolated_package_module',lambda *a,**kw:module)
    class Policy:
        def verify_proof(self,*args,**kwargs):return dict(corrections_sha256='d'*64)
    policy=Policy();monkeypatch.setattr(resolution,'policy_for_shared',lambda *a:policy)
    artifact=build_shared_hk_0_2_pool(tmp_path,trade_date='20261015',signal_date='20261014',reader=lambda *a,**kw:pool)
    # The existing runtime mapper retains row proof identities but omits these
    # optional top-level pins. The HK-only publication orchestrator adds them
    # from this exact verified run before requesting the strict refresh CAS.
    helper=Path(__file__).resolve().parents[1]/'docs/handoffs/hk_tdx_conflict_repair_20261015/publish_hk_only.py'
    spec=importlib.util.spec_from_file_location('hk_only_publication_test',helper)
    orchestrator=importlib.util.module_from_spec(spec);spec.loader.exec_module(orchestrator)
    artifact=orchestrator.complete_consumer_identity(artifact,pool)
    store=PreselectionPoolStore(tmp_path/'data')
    a=build_expected_missing_pool('20261015',pool_id='a_d1_premarket_pool',display_name='A unchanged',market='A',reason='fixture')
    a.update(status='V192_CANDIDATE_READY',source_role='SHARED_VERIFIED_V192',source_sha256='e'*64,source_path='runs/A/unchanged',producer_id='v3_shared_v192',cannot_confirm=[],rows=[dict(symbol='SZ.000001',market='A',pool_rank=1,stock_name='A ready',production_allowed=False,buy_gate_updated=False,orders_sent=False)])
    store.materialize(a)
    old=copy.deepcopy(artifact);old['source_sha256']='0'*64;old['source_run_id']='old';old['rows'][0]['pool_score']=2.
    store.materialize(old)
    snapshot=store.read_pool_snapshot('20261015','hkconnect_d1_top100')
    expected={k:snapshot[k] for k in ['artifact_raw_sha256','receipt_raw_sha256','manifest_raw_sha256']}
    a_paths=[store.root/'preselection_pools/20261015/a_d1_premarket_pool.json',store.root/'preselection_pools/20261015/receipts/a_d1_premarket_pool.json']
    a_bytes={p:p.read_bytes() for p in a_paths};a_hash=snapshot['manifest']['a_d1_premarket_pool']
    return SimpleNamespace(store=store,artifact=artifact,pool=pool,expected=expected,policy=policy,a_bytes=a_bytes,a_hash=a_hash,root=tmp_path)


def refresh(case,**kw):
    return case.store.refresh_verified_hk_resolution(kw.get('payload',case.artifact),
        expected_previous=kw.get('expected',case.expected),shared_root=case.root,shared_package_root=case.root)


def assert_a_unchanged(case):
    assert all(p.read_bytes()==b for p,b in case.a_bytes.items())
    assert case.store.read_pool_snapshot('20261015','hkconnect_d1_top100')['manifest']['a_d1_premarket_pool']==case.a_hash


def test_hk_refresh_exact_cas_commits_only_hk_with_archive(refresh_case):
    c=refresh_case;r=refresh(c)
    assert r['previous_sha256']!=r['sha256'];assert_a_unchanged(c)
    snapshot=c.store.read_pool_snapshot('20261015','hkconnect_d1_top100')
    assert snapshot['artifact']==c.artifact
    assert list((c.store.root/'preselection_pools').rglob('*'))


@pytest.mark.parametrize('variant',['partial','codes','ranks','score','foreign_market','stale_proof','race','no_cas','missing_source_manifest','missing_source_receipt','missing_row_identity'])
def test_hk_refresh_failclosed_without_a_writes(refresh_case,variant):
    c=refresh_case;payload=copy.deepcopy(c.artifact);expected=dict(c.expected)
    if variant=='partial':payload['status']='PARTIAL'
    if variant=='codes':payload['rows'][0]['symbol']='HK.09999'
    if variant=='ranks':payload['rows'][0]['pool_rank']=999
    if variant=='score':payload['rows'][0]['pool_score']=999
    if variant=='foreign_market':payload['market']='A'
    if variant=='stale_proof':
        def fail(*a,**kw):raise ValueError('STALE_PROOF')
        c.policy.verify_proof=fail
    if variant=='race':expected['artifact_raw_sha256']='f'*64
    if variant=='no_cas':expected.pop('receipt_raw_sha256')
    if variant=='missing_source_manifest':payload.pop('source_manifest_sha256')
    if variant=='missing_source_receipt':payload.pop('source_receipt_sha256')
    if variant=='missing_row_identity':payload['rows'][0].pop('history_resolution_identity')
    before=c.store.read_pool_snapshot('20261015','hkconnect_d1_top100')['artifact_raw_sha256']
    with pytest.raises(ValueError):refresh(c,payload=payload,expected=expected)
    assert c.store.read_pool_snapshot('20261015','hkconnect_d1_top100')['artifact_raw_sha256']==before
    assert_a_unchanged(c)


def test_shared_hk_refresh_binds_new_proof_before_artifact_identity(tmp_path,monkeypatch):
    import upstreams.v3_shared_data.shared_data.hk_0_2 as hk
    from upstreams.v3_shared_data.shared_data.store import SafeRootStore,StoreError
    root=tmp_path/'shared';current=['b64url.old']
    class Policy:
        @property
        def corrections_sha256(self):return None if current[0]=='b64url.old' else 'd'*64
        def check_panel(self,value):assert value=='a'*64
        def _validate_score_admission(self,proof):pass  # publication identity fixture only
        def verify_proof(self,token,**kwargs):
            if token!=current[0]:raise StoreError('STALE_PROOF')
            codes=[f'HK.{i:05d}' for i in range(1,501)]
            return dict(allowed_codes=codes,excluded_codes=[],score_coverage=dict(eligible_codes=codes,
                original_signal_codes=codes,scoreable_signal_codes=codes,quality_quarantined_codes=[],missing_signal_codes=[]))
    monkeypatch.setattr(hk,'policy_for_shared',lambda *a:Policy())
    master_manifest=dict(run_id='master',artifact_sha256='e'*64,captured_at='2026-10-14T17:00:00+08:00')
    monkeypatch.setattr(hk,'_load_verified_security_master',lambda *a:({f'HK.{i:05d}':{} for i in range(1,501)},master_manifest))
    rows=[dict(trade_date='20261015',target_date='20261015',signal_date='20261014',bar_time='17:30',rank=i,
        code_norm=f'HK.{i:05d}',code=f'HK.{i:05d}',name=f'Name{i}',score_prob_active=1-i/1000,
        selected_strategy='prob_active',d1_freshness_status='PASS',production_allowed=False,research_only=True,cannot_confirm='') for i in range(1,101)]
    old=hk.publish_hk_0_2_rows(root,signal_date='20261014',target_date='20261015',rows=rows,panel_sha256='a'*64,history_resolution_proof=current[0])
    old_verified=SafeRootStore(root).verify_latest('20261015',hk.HK_0_2_ROLE)['verified']
    expected={k:old_verified[k] for k in ['run_id','artifact_sha256','manifest_sha256','receipt_sha256','artifact_relative','manifest_relative','receipt_relative']}
    current[0]='b64url.new'
    new=hk.publish_hk_0_2_rows(root,signal_date='20261014',target_date='20261015',rows=rows,panel_sha256='a'*64,history_resolution_proof=current[0],expected_previous=expected)
    assert new['run_id']!=old['run_id'] and new['artifact_sha256']!=old['artifact_sha256']
    assert (root/expected['artifact_relative']).is_file()
    assert all(row['history_resolution_identity']==hashlib.sha256(current[0].encode()).hexdigest() for row in hk.read_verified_hk_0_2_pool(root,target_date='20261015',expected_signal_date='20261014').rows)


def test_hk_refresh_actual_legacy_contract_without_top_level_dates(refresh_case):
    c=refresh_case;payload=copy.deepcopy(c.artifact)
    payload.pop('signal_date',None);payload.pop('target_date',None)
    refresh(c,payload=payload);assert_a_unchanged(c)


@pytest.mark.parametrize('which',['mixed','missing','top_mismatch','not_d1'])
def test_hk_refresh_rejects_nonunique_or_unbound_row_dates(refresh_case,which):
    c=refresh_case;payload=copy.deepcopy(c.artifact)
    if which=='mixed':payload['rows'][0]['signal_date']='20261013'
    if which=='missing':payload['rows'][0].pop('signal_date')
    if which=='top_mismatch':payload['signal_date']='20261013'
    if which=='not_d1':
        payload['signal_date']='20261013'
        for row in payload['rows']:row['signal_date']='20261013'
    with pytest.raises(ValueError):refresh(c,payload=payload)
    assert_a_unchanged(c)


def shared_hk_projection():
    """Load the actual shared variant without touching a running namespace."""
    import os
    root=Path(__file__).resolve().parents[1]
    app=os.environ.get('V4_HK_TEST_REPAIR_SHARED_APP')
    path=(Path(app)/'shared_data/hk_0_2.py' if app else root/'docs/handoffs/hk_tdx_conflict_repair_20261015/source_projection/shared/shared_data/hk_0_2.py')
    name='upstreams.v3_shared_data.shared_data._hk_repair_materialize_test'
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name]=module;spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('kind',['quality','real_missing','wrong_excluded','forged_proof','short100'])
def test_actual_shared_materialize_quality_is_not_missing_date(tmp_path,monkeypatch,kind):
    hk=shared_hk_projection()
    allowed=[f'HK.{i:05d}' for i in range(1,501)];held='HK.00999'
    original=allowed+([held] if kind!='real_missing' else [])
    proof=dict(allowed_codes=allowed,excluded_codes=[held],score_coverage=dict(
        eligible_codes=sorted(allowed+[held]),original_signal_codes=sorted(original),
        scoreable_signal_codes=allowed,quality_quarantined_codes=[held] if kind!='real_missing' else [],
        missing_signal_codes=[held] if kind=='real_missing' else []))
    if kind=='wrong_excluded':proof['excluded_codes']=[]
    token='bad' if kind=='forged_proof' else 'valid'
    class Policy:
        def verify_proof(self,value,**kwargs):
            if value!='valid':raise ValueError('STALE_PROOF')
            return proof
        def _validate_score_admission(self,value):pass  # materialize classification fixture only
    monkeypatch.setattr(hk,'policy_for_shared',lambda *a:Policy())
    monkeypatch.setattr(hk,'load_frozen_hk_0_2_assets',lambda *a:SimpleNamespace(panel_manifest={'panel_sha256':'a'*64}))
    master={c:{'name':'Name'} for c in allowed+[held]}
    monkeypatch.setattr(hk,'_load_verified_security_master',lambda *a:(master,{}))
    def score(*args,diagnostics,**kwargs):
        diagnostics.update(history_resolution_proof=token,missing_signal_codes=[held])
        return [{'code_norm':c} for c in allowed[:99 if kind=='short100' else 100]]
    monkeypatch.setattr(hk,'score_frozen_hk_0_2',score)
    monkeypatch.setattr(hk,'_fill_name_placeholders',lambda rows,*a,**kw:rows)
    def publish(*args,rows,partial_reasons,**kwargs):
        # This stub models only the existing row-count gate, not a model.
        if len(rows)!=100:raise ValueError('TOP100_REQUIRED')
        return dict(status='PARTIAL' if partial_reasons else 'READY',reasons=partial_reasons)
    monkeypatch.setattr(hk,'publish_hk_0_2_rows',publish)
    if kind in ['wrong_excluded','forged_proof','short100']:
        with pytest.raises(ValueError):hk.materialize_frozen_hk_0_2(tmp_path,tmp_path,signal_date='20261014',target_date='20261015')
    else:
        result=hk.materialize_frozen_hk_0_2(tmp_path,tmp_path,signal_date='20261014',target_date='20261015')
        assert result['status']==('READY' if kind=='quality' else 'PARTIAL')
        assert result['reasons']==([] if kind=='quality' else [f'HK_0_2_SIGNAL_ROW_MISSING:{held}'])


@pytest.mark.parametrize('count',[499,500])
def test_actual_shared_scorer_500_signal_coverage_gate(tmp_path,monkeypatch,count):
    import pandas as pd
    hk=shared_hk_projection();codes=[f'HK.{i:05d}' for i in range(1,count+1)]
    frame=pd.DataFrame({'code_norm':codes,'trade_date_compact':['20261014']*count})
    proof=dict(allowed_codes=codes,excluded_codes=[],excluded_code_count=0)
    class Policy:
        def __init__(self,*a):pass
        def check_panel(self,*a):pass
        def encode_proof(self,p):return 'token'
    monkeypatch.setattr(hk,'ResolutionPolicy',Policy)
    monkeypatch.setattr(hk,'load_frozen_hk_0_2_assets',lambda *a:SimpleNamespace(root=tmp_path,panel_path=tmp_path/'unused',panel_manifest={'panel_sha256':'a'*64},model_manifest={'feature_columns':[]}))
    monkeypatch.setattr(pd,'read_parquet',lambda *a:frame.copy())
    def guard(f,*a):f.attrs['history_resolution_proof']=proof;return f
    monkeypatch.setattr(hk,'guard_score_frame',guard)
    monkeypatch.setattr(hk,'_add_daily_features',lambda f:f)
    monkeypatch.setattr(hk,'_add_proxy_labels',lambda f:(f,{'20261014':['proof_of_proxy_stage_only']}))
    monkeypatch.setattr(hk,'_add_proxy_memory',lambda f,*a:f)
    monkeypatch.setattr(hk,'_load_models',lambda *a,**kw:None)
    def stop_after_gate(*a):raise RuntimeError('PASSED_500_GATE')
    monkeypatch.setattr(hk,'_score_with_strategies',stop_after_gate)
    if count==499:
        with pytest.raises(hk.StoreError,match='coverage below 500'):hk.score_frozen_hk_0_2(tmp_path,signal_date='20261014',target_date='20261015',eligible_codes=codes)
    else:
        with pytest.raises(RuntimeError,match='PASSED_500_GATE'):hk.score_frozen_hk_0_2(tmp_path,signal_date='20261014',target_date='20261015',eligible_codes=codes)


def test_existing_hk_create_and_conflict_leave_a_pending_untouched(refresh_case):
    c=refresh_case;payload=copy.deepcopy(c.artifact);payload['trade_date']='20261016'
    for field,value in [('signal_date','20261015'),('target_date','20261016')]:
        if field in payload:payload[field]=value
        for row in payload['rows']:row[field]=value;row['trade_date']='20261016'
    a=c.store._read('preselection_pools/20261015/a_d1_premarket_pool.json');a['trade_date']='20261016'
    c.store.materialize(a)
    pending=c.store.root/'preselection_pending_commits/20261016/a_d1_premarket_pool.json'
    pending.parent.mkdir(parents=True,exist_ok=True);pending.write_bytes(b'A_PENDING_SENTINEL_MUST_NOT_BE_RECOVERED')
    a_paths=[c.store.root/'preselection_pools/20261016/a_d1_premarket_pool.json',c.store.root/'preselection_pools/20261016/receipts/a_d1_premarket_pool.json',pending]
    before={p:p.read_bytes() for p in a_paths};manifest=c.store._read('preselection_pools/20261016/manifest.json')
    c.store.materialize(payload)
    conflicting=copy.deepcopy(payload);conflicting['rows'][0]['pool_score']=999
    with pytest.raises(ValueError,match='conflicting'):c.store.materialize(conflicting)
    assert all(p.read_bytes()==raw for p,raw in before.items())
    assert c.store._read('preselection_pools/20261016/manifest.json')['a_d1_premarket_pool']==manifest['a_d1_premarket_pool']
