"""R9 artifact contract and original owner rebinding; synthetic source identities.
The actual R9 store is used, not the canonical cache store. No market/provider run.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace

import pytest
from domains import preselection_materializer as projector
from infrastructure.preselection_pool_store import PreselectionPoolStore

FLAGS = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)
ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def qualification(price):
    captured=f'{price[:4]}-{price[4:6]}-{price[6:]}T17:20:00+08:00'
    return dict(schema_version='v4.hk_eligibility_asof.v1', source_date=price,
        captured_at=captured, security_master_captured_at=captured,
        validity='EXACT_CAPTURE_DATE_ONLY',source_role='FUTU_HKCONNECT_PLATE_MEMBERSHIP',
        authority_run_id='synthetic-authority',security_master_run_id='synthetic-master',
        code_count=696, natural_verified=False, **FLAGS,
        **{key:'b'*64 for key in ('source_sha256','codes_sha256','authority_artifact_sha256',
           'authority_manifest_sha256','authority_receipt_sha256','authority_current_sha256',
           'security_master_artifact_sha256')})


def artifact(price='20261007',target='20261008'):
    src=[dict(code_norm=f'HK.{i:05d}',name=f'SYNTHETIC {i}',rank=i,
        score_prob_active=(101-i)/101,signal_date=price,target_date=target,
        d1_freshness_status='PASS',selected_strategy='prob_active') for i in range(1,101)]
    runid='synthetic-hk-d1'
    verification=dict(run_id=runid,row_count=100,artifact_sha256='c'*64,
        artifact_relative=f'runs/{target}/HK_CONNECT_D1_TOP100_0_2/{runid}/artifact.csv',
        manifest_sha256='d'*64,receipt_sha256='e'*64)
    pool=SimpleNamespace(rows=src,run=SimpleNamespace(verification=verification,receipt=FLAGS,
        manifest={'provenance':{'eligibility_asof_hex':canonical(qualification(price)).hex()}}))
    def reader(root,**kwargs):
        assert kwargs==dict(target_date=target,expected_signal_date=price,expected_eligibility_source_date=price)
        return pool
    return projector.build_shared_hk_0_2_pool(Path('/SYNTHETIC_NOT_READ'),
        trade_date=target,signal_date=price,eligibility_source_date=price,reader=reader)


def seed_a(root,target):
    value=projector._artifact(trade_date=target,pool_id='a_d1_premarket_pool',display_name='SYNTHETIC',
        market='A',status='READY',producer_id='synthetic',source_role='SHARED_VERIFIED_V192',
        source_path='SYNTHETIC',source_sha256='a'*64,rows=[dict(symbol='A.600000',**FLAGS)])
    store=PreselectionPoolStore(root);store.materialize(value)
    return value


def bytes_map(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('price,target', [('20261002','20261005'),('20261005','20261006'),
    ('20261006','20261007'),('20261007','20261008'),('20261008','20261009')])
def test_projector_fields_survive_actual_r9_trio_and_existing_a(tmp_path,price,target):
    a=seed_a(tmp_path,target);before=bytes_map(tmp_path);value=artifact(price,target)
    store=PreselectionPoolStore(tmp_path)
    store.materialize(value)
    assert store.read_pool(target,'hkconnect_d1_top100')==value
    snapshot=store.read_pool_snapshot(target,'hkconnect_d1_top100')
    assert snapshot['payload']['historical_provenance']==value['historical_provenance']
    assert snapshot['artifact_sha256']==hashlib.sha256(canonical(value)).hexdigest()
    assert store.read_pool(target,'a_d1_premarket_pool')==a
    assert all((tmp_path/p).read_bytes()==b for p,b in before.items() if 'a_d1_premarket_pool' in p)
    prior=json.loads(before[f'preselection_pools/{target}/manifest.json'])
    after=json.loads((tmp_path/f'preselection_pools/{target}/manifest.json').read_bytes())
    assert all(after[k]==v for k,v in prior.items())


@pytest.mark.parametrize('mutation', ['unknown','a_lane','half_extension','empty_hash','wrong_run',
    'wrong_artifact','wrong_source_date','future_capture','qualification_type','unsafe'])
def test_extension_cannot_relax_identity_and_unknown_field_checks(tmp_path,mutation):
    value=artifact();p=value['historical_provenance'];q=p['eligibility_asof']
    if mutation=='unknown':value['unreviewed_field']=True
    elif mutation=='a_lane':value.update(market='A',pool_id='a_d1_premarket_pool',source_role='SHARED_VERIFIED_V192')
    elif mutation=='half_extension':value.pop('source_receipt_sha256')
    elif mutation=='empty_hash':value['source_manifest_sha256']=''
    elif mutation=='wrong_run':p['d1_source_run_id']='wrong'
    elif mutation=='wrong_artifact':p['d1_source_artifact_sha256']='f'*64
    elif mutation=='wrong_source_date':q['source_date']='20260930'
    elif mutation=='future_capture':q['captured_at']='2026-10-08T17:20:00+08:00'
    elif mutation=='qualification_type':p['eligibility_asof']=[]
    elif mutation=='unsafe':q['orders_sent']=True
    before=bytes_map(tmp_path)
    with pytest.raises(ValueError):PreselectionPoolStore(tmp_path).materialize(value)
    assert bytes_map(tmp_path)==before


def test_retained_provenance_is_inside_original_hash_boundary(tmp_path):
    value=artifact();store=PreselectionPoolStore(tmp_path);store.materialize(value)
    path=tmp_path/'preselection_pools/20261008/hkconnect_d1_top100.json'
    changed=deepcopy(value);changed['historical_provenance']['eligibility_asof']['captured_at']='2026-10-07T17:21:00+08:00'
    path.write_bytes(canonical(changed))
    with pytest.raises(ValueError,match='SHA mismatch'):store.read_pool('20261008','hkconnect_d1_top100')


@pytest.mark.parametrize('price,target', [('20261007','20261008'),('20261008','20261009')])
@pytest.mark.parametrize('publisher_available',[True,False])
def test_r9_rebound_owner_uses_real_module_helpers_not_injected_globals(tmp_path,monkeypatch,price,target,publisher_available):
    """R9 FunctionType(globals()) rule; subprocess/provider are deliberate seams.
    Not a claim that unexecuted R9 research/review handlers were integrated.
    """
    import os
    from contracts.runtime_tasks import DispatchRequest, DispatchMode
    from ops.daily_materialize import resolve_selector_panel
    from stage_center import hk_universe_preflight as publisher
    from infrastructure.scheduling import executor_registry_preselection as owner
    data=tmp_path/'data';a=seed_a(data,target);before=bytes_map(data)
    shared=tmp_path/'shared';shared.mkdir()
    package=tmp_path/'package';(package/'scripts').mkdir(parents=True)
    for name in ('capture_public_fupan','materialize_v192_selector','update_hk_0_2_panel','materialize_hk_0_2'):
        (package/'scripts'/f'{name}.py').write_text('# SYNTHETIC ENTRY\n')
    app=tmp_path/'app';(app/'ops').mkdir(parents=True);(app/'ops/ensure_hk_security_master.py').write_text('# SYNTHETIC\n')
    calls=[];pub=[]
    def ensure(root,date):
        pub.append((root,date))
        if not publisher_available:raise ValueError('SYNTHETIC_MISSING_CAPTURE')
        return dict(ok=True,status='READY',trade_date=date,code_count=696,**FLAGS)
    monkeypatch.setattr(publisher,'ensure_hk_connect_universe',ensure)
    def child(module,arguments,**kwargs):
        calls.append((module,arguments));return dict(status='SUCCEEDED',exit_code=0,stdout='{}',stderr='',**FLAGS)
    def default(*a,**k):raise AssertionError('network must not run')
    obj=SimpleNamespace(data_root=data,shared_data_root=shared,hk_universe_root=shared,shared_package_root=package,
        preselection_input_root=tmp_path/'inputs',repo_root=app,selector_data_root=None,stage_selection_root=None,
        shared_futu_python_executable=Path('/SYNTHETIC_PYTHON'),hk_0_2_python_executable=Path('/SYNTHETIC_HK_PYTHON'),
        hk_0_2_tdx_root=tmp_path/'tdx',_runner=child,_run=child,_hk_0_2_runtime_error=lambda:None,
        _failure_result=lambda w,m,e:dict(status='FAILED',exit_code=1,stdout='',stderr=e,**FLAGS))
    # Exact R9 rebinding property: owner-only globals are NOT copied into facade.
    scope=dict(json=json,os=os,Path=Path,PreselectionPoolStore=PreselectionPoolStore,
        resolve_selector_panel=resolve_selector_panel,WorkloadExecutionError=RuntimeError,
        _default_runner=default,_V192_PRESELECTION_TIMEOUT_SECONDS=1800)
    for name in ('_verified_formal_pool_reuse','_preselection_pools'):
        src=getattr(owner,name)
        rebound=FunctionType(src.__code__,scope,name,src.__defaults__,src.__closure__)
        rebound.__kwdefaults__=src.__kwdefaults__
        setattr(obj,name,rebound.__get__(obj))
    assert '_hk_owner_universe_root' not in scope
    request=DispatchRequest(scheduled_date=price,business_date=price,target_date=target,slot='1730',mode=DispatchMode.LIVE)
    result=obj._preselection_pools(request)
    assert pub==[(shared,price)]
    if not publisher_available:
        assert result['hk_lane_status']=='CANNOT_CONFIRM'
        assert not any(n in ('ops.ensure_hk_security_master','scripts.materialize_hk_0_2') for n,args in calls)
    elif price=='20261007':
        assert not any(n in ('scripts.capture_public_fupan','ops.materialize_shared_v192_preselection','ops.materialize_d1_review_lanes') for n,args in calls)
        sec=next(args for n,args in calls if n=='ops.ensure_hk_security_master')
        assert sec[sec.index('--trade-date')+1]==price
    assert PreselectionPoolStore(data).read_pool(target,'a_d1_premarket_pool')==a
    assert bytes_map(data)==before
