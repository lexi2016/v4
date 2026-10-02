"""Synthetic network/model boundaries; real existing publisher/readers/stores.

No market data, natural execution claim, Stage selection or service operation.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.isolated_package_loader import load_isolated_package_module
from infrastructure.preselection_pool_store import PreselectionPoolStore
from domains import preselection_materializer as projector
from ops import materialize_scheduled_preselection as scheduled
from stage_center import hk_universe_preflight as publisher
from stage_center import runner as stage

ROOT = Path(os.environ.get("HK_R3_APP_ROOT", Path(__file__).resolve().parents[1])).resolve()
PACKAGE = ROOT / 'upstreams/v3_shared_data'
FLAGS = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)


def mod(leaf):
    return load_isolated_package_module(PACKAGE, package_directory='shared_data',
        module_leaf=leaf, namespace_prefix='hk19_contract')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def file_map(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def rows(price, target):
    return [dict(rank=i, trade_date=target, bar_time='17:30', code=f'HK.{i:05d}',
        code_norm=f'HK.{i:05d}', ts_code=f'{i:05d}.HK_CONNECT', name=f'SYNTHETIC {i}',
        signal_date=price, target_date=target, score_prob_active=(101-i)/101,
        selected_strategy='prob_active', weekly_tuning_selected_strategy='prob_active',
        production_allowed=False, research_only=True, d1_freshness_status='PASS', cannot_confirm='') for i in range(1,101)]


def seed_authority(root, price, monkeypatch):
    now = datetime.strptime(price, '%Y%m%d').replace(hour=17, minute=20, tzinfo=ZoneInfo('Asia/Shanghai'))
    codes = [f'HK.{i:05d}' for i in range(1, 652)]
    class Frame:
        def to_dict(self, *, orient):
            assert orient == 'records'
            return [{'code': c} for c in codes]
    class Quote:
        def get_plate_stock(self, plate):
            assert plate in publisher.HKCONNECT_PLATE_CODES
            return 0, Frame()
        def close(self): pass
    monkeypatch.setattr(publisher, '_default_quote_context_factory', Quote)
    monkeypatch.setattr(publisher, '_current_shanghai', lambda supplied: now)
    outcome = publisher.ensure_hk_connect_universe(root, price)
    sec = mod('hk_security_master')
    sec.publish_hk_security_master(root, trade_date=price,
        rows=[{'code': c, 'name': 'SYNTHETIC '+c} for c in codes],
        universe_codes_sha256=hashlib.sha256(canonical(codes)).hexdigest(),
        captured_at=now.replace(minute=21).isoformat())
    return outcome


def seed_a(root, target):
    a = projector._artifact(trade_date=target, pool_id='a_d1_premarket_pool',
        display_name='SYNTHETIC PERSISTED A', market='A', status='READY',
        producer_id='synthetic_existing_A', source_role='SHARED_VERIFIED_V192',
        source_path='SYNTHETIC.csv', source_sha256='a'*64,
        rows=[dict(symbol='A.600000', stock_name='SYNTHETIC A', pool_rank=1, pool_score=1,
            trade_date=target, signal_date='20260930', market='A', **FLAGS)])
    store = PreselectionPoolStore(root)
    store.materialize(a)
    return store.read_pool(target, 'a_d1_premarket_pool')


@pytest.mark.parametrize('price,target', [('20261007','20261008'), ('20261008','20261009')])
def test_real_shared_projector_stage_chain_has_capture_provenance(tmp_path, monkeypatch, price, target):
    shared=tmp_path/'shared'; data=tmp_path/'data'
    authority=seed_authority(shared,price,monkeypatch)
    existing_a=seed_a(data,target); before=file_map(data)
    hk=mod('hk_0_2')
    hk.publish_hk_0_2_rows(shared, signal_date=price, target_date=target,
        rows=rows(price,target), panel_sha256='b'*64)
    verified=hk.read_verified_hk_0_2_pool(shared, target_date=target, expected_signal_date=price)
    qualification=json.loads(bytes.fromhex(verified.run.manifest['provenance'].get('eligibility_asof_hex', '')).decode())
    assert isinstance(qualification,dict), 'missing original eligibility as-of binding'
    assert qualification['source_date']==price
    assert qualification['authority_artifact_sha256']==authority['artifact_sha256']
    assert qualification['captured_at'].startswith(price[:4]+'-'+price[4:6]+'-'+price[6:])
    assert qualification['natural_verified'] is False
    artifacts=scheduled.build_scheduled_artifacts(trade_date=target, signal_date='20260930',
        hk_signal_date=price, hk_eligibility_source_date=price, selector=None,
        input_root=tmp_path/'inputs', data_root=data, shared_data_root=shared,
        shared_package_root=PACKAGE, markets=('HK',))
    assert [a['market'] for a in artifacts]==['HK']
    if hasattr(scheduled, "publish_scheduled_artifacts"):
        scheduled.publish_scheduled_artifacts(PreselectionPoolStore(data), artifacts)
    else:
        scheduled.materialize_preselection_date(PreselectionPoolStore(data), artifacts)
    assert PreselectionPoolStore(data).read_pool(target,'a_d1_premarket_pool')==existing_a
    assert all((data/p).read_bytes()==b for p,b in before.items()
               if 'a_d1_premarket_pool' in p)
    manifest=f'preselection_pools/{target}/manifest.json'
    old_manifest=json.loads(before[manifest]); new_manifest=json.loads((data/manifest).read_bytes())
    for key,value in old_manifest.items():
        assert new_manifest[key]==value
    path,digest=stage._validate_hk_d1(data,target)
    assert path.name=='hkconnect_d1_top100.json' and len(digest)==64
    assert all(artifacts[0][flag] is False for flag in FLAGS)


@pytest.mark.parametrize('bad', ['missing_capture','wrong_date','future_capture','master_codes','authority_sha'])
def test_shared_rejects_unverified_eligibility_not_using_master_time(tmp_path,monkeypatch,bad):
    shared=tmp_path/'shared';price='20261007';target='20261008'
    outcome=seed_authority(shared,price,monkeypatch)
    artifact=Path(outcome['manifest'])
    if bad=='master_codes':
        sec=mod('hk_security_master')
        sec.publish_hk_security_master(shared,trade_date=price,
            rows=[{'code':f'HK.{i:05d}','name':'SYNTHETIC'} for i in range(1,101)],
            universe_codes_sha256='f'*64,captured_at='2026-10-07T17:21:00+08:00')
    else:
        value=json.loads(artifact.read_bytes())
        if bad=='missing_capture':value.pop('captured_at')
        elif bad=='wrong_date':value['source_date']='20260930'
        elif bad=='future_capture':value['captured_at']='2026-10-08T17:20:00+08:00'
        else:value['source_sha256']='f'*64
        artifact.write_bytes(canonical(value))
    before=file_map(shared)
    hk=mod('hk_0_2')
    with pytest.raises((ValueError,OSError, hk.StoreError)):
        hk.publish_hk_0_2_rows(shared,signal_date=price,target_date=target,
            rows=rows(price,target),panel_sha256='b'*64)
    assert file_map(shared)==before


def test_price_day_stale_oct8_preview_is_not_stage_input(tmp_path,monkeypatch):
    shared=tmp_path/'shared';seed_authority(shared,'20260930',monkeypatch)
    hk=mod('hk_0_2')
    hk.publish_hk_0_2_rows(shared,signal_date='20260930',target_date='20261008',
        rows=rows('20260930','20261008'),panel_sha256='b'*64)
    before=file_map(shared)
    with pytest.raises(ValueError):
        projector.build_shared_hk_0_2_pool(shared,trade_date='20261008',signal_date='20260930',
                                         shared_package_root=PACKAGE)
    assert file_map(shared)==before


def test_shared_source_identity_change_after_publication_is_not_hidden(tmp_path,monkeypatch):
    shared=tmp_path/'shared';out=seed_authority(shared,'20261007',monkeypatch)
    hk=mod('hk_0_2')
    hk.publish_hk_0_2_rows(shared,signal_date='20261007',target_date='20261008',
        rows=rows('20261007','20261008'),panel_sha256='b'*64)
    Path(out['manifest']).write_bytes(Path(out['manifest']).read_bytes()+b' ')
    with pytest.raises((ValueError,hk.StoreError)):
        hk.read_verified_hk_0_2_pool(shared,target_date='20261008',expected_signal_date='20261007')


@pytest.mark.parametrize('price,target', [('20261007','20261008'),('20261008','20261009')])
@pytest.mark.parametrize('publisher_available', [True, False])
def test_original_owner_invokes_existing_publisher_and_preserves_a_on_hk_only(tmp_path,monkeypatch,price,target,publisher_available):
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    import infrastructure.scheduling.executor_registry as registry
    shared=tmp_path/'shared';(shared/'universes').mkdir(parents=True);(shared/'assets/hk_security_master').mkdir(parents=True)
    package=tmp_path/'package';(package/'scripts').mkdir(parents=True)
    for name in ('capture_public_fupan','materialize_v192_selector','update_hk_0_2_panel','materialize_hk_0_2'):
        (package/'scripts'/f'{name}.py').write_text('# synthetic entry only\n')
    source=tmp_path/'app';(source/'ops').mkdir(parents=True);(source/'ops/ensure_hk_security_master.py').write_text('# synthetic entry only\n')
    data=tmp_path/'data';a=seed_a(data,target);original=file_map(data);calls=[];pub=[]
    def ensure(root,trade_date):
        pub.append((Path(root),trade_date))
        if not publisher_available:
            raise ValueError('SYNTHETIC_ORIGINAL_CAPTURE_UNAVAILABLE')
        return dict(ok=True,status='READY',trade_date=trade_date,
            artifact_sha256='a'*64,code_count=651,**FLAGS)
    monkeypatch.setattr(publisher,'ensure_hk_connect_universe',ensure)
    def child(command,*,cwd,timeout_seconds,env):
        module=command[2];args=command[3:];calls.append((module,args))
        return subprocess.CompletedProcess(command,0,'{}','')
    obj=FixedExecutorRegistry(data,shared_data_root=shared,hk_universe_root=shared,shared_package_root=package,
        preselection_input_root=tmp_path/'inputs',repo_root=source,runner=child)
    # Bind the existing facade method for this source layout. R9 has pair
    # reuse; canonical has a per-source reader. Never invent module globals.
    if hasattr(type(obj), '_verified_formal_pool_reuse'):
        monkeypatch.setattr(obj,'_verified_formal_pool_reuse',lambda target:None)
    else:
        monkeypatch.setattr(obj,'_verified_preselection_source',
                            lambda **kwargs:(None, 'SYNTHETIC prior source absent'))
    monkeypatch.setattr(obj,'_hk_0_2_runtime_error',lambda:None)
    req=DispatchRequest(scheduled_date=price,business_date=price,target_date=target,slot='1730',mode=DispatchMode.LIVE)
    result=obj._preselection_pools(req)
    assert pub==[(shared,price)], 'original publisher was not reached'
    if not publisher_available:
        assert not any(name in ('ops.ensure_hk_security_master','scripts.materialize_hk_0_2') for name,args in calls)
        assert result['hk_lane_status']=='CANNOT_CONFIRM'
        assert file_map(data)==original
        return
    sec=next(args for name,args in calls if name=='ops.ensure_hk_security_master')
    assert sec[sec.index('--trade-date')+1]==price
    if price=='20261007':
        assert not any(n in ('scripts.capture_public_fupan','ops.materialize_shared_v192_preselection','ops.materialize_d1_review_lanes') for n,_ in calls)
        args=next(args for name,args in calls if name=='ops.materialize_scheduled_preselection')
        assert args[args.index('--market')+1]=='HK'
    assert PreselectionPoolStore(data).read_pool(target,'a_d1_premarket_pool')==a
    assert file_map(data)==original


def test_explicit_separate_universe_root_survives_shared_cli(tmp_path,monkeypatch):
    import sys
    universe=tmp_path/'universe';shared=tmp_path/'shared';price='20261007';target='20261008'
    seed_authority(universe,price,monkeypatch)
    codes=[f'HK.{i:05d}' for i in range(1,652)]
    mod('hk_security_master').publish_hk_security_master(shared,trade_date=price,
        rows=[{'code':c,'name':'SYNTHETIC '+c} for c in codes],
        universe_codes_sha256=hashlib.sha256(canonical(codes)).hexdigest(),
        captured_at='2026-10-07T17:21:00+08:00')
    hk=mod('hk_0_2')
    hk.publish_hk_0_2_rows(shared,signal_date=price,target_date=target,
        eligibility_universe_root=universe,rows=rows(price,target),panel_sha256='b'*64)
    before=file_map(shared)
    process=subprocess.run([sys.executable,'-B',str(PACKAGE/'scripts/materialize_hk_0_2.py'),
        '--store-root',str(shared),'--asset-root',str(tmp_path/'unused-assets'),
        '--signal-date',price,'--target-date',target,
        '--eligibility-source-date',price,'--eligibility-universe-root',str(universe)],
        capture_output=True,text=True,timeout=15)
    assert process.returncode==0,(process.stdout,process.stderr)
    assert json.loads(process.stdout)['already_exists'] is True
    assert file_map(shared)==before


def test_original_scheduled_hk_only_cli_does_not_publish_a_missing_pool(tmp_path,monkeypatch,capsys):
    shared=tmp_path/'shared';data=tmp_path/'data';price='20261007';target='20261008'
    seed_authority(shared,price,monkeypatch)
    hk=mod('hk_0_2');hk.publish_hk_0_2_rows(shared,signal_date=price,target_date=target,
        rows=rows(price,target),panel_sha256='b'*64)
    a=seed_a(data,target);before=file_map(data)
    code=scheduled.main(['--trade-date',target,'--signal-date','20260930',
        '--hk-signal-date',price,'--hk-eligibility-source-date',price,
        '--market','HK','--input-root',str(tmp_path/'no-A-inputs'),
        '--shared-data-root',str(shared),'--shared-package-root',str(PACKAGE),'--data-root',str(data),
        '--hk-eligibility-universe-root',str(shared)])
    assert code==0,capsys.readouterr()
    assert PreselectionPoolStore(data).read_pool(target,'a_d1_premarket_pool')==a
    assert all((data/p).read_bytes()==b for p,b in before.items() if 'a_d1_premarket_pool' in p)
    assert len(PreselectionPoolStore(data).read_pool(target,'hkconnect_d1_top100')['rows'])==100


def test_existing_oct8_early_preview_is_not_overwritten_or_relabelled(tmp_path,monkeypatch):
    shared=tmp_path/'shared';hk=mod('hk_0_2')
    seed_authority(shared,'20260930',monkeypatch)
    hk.publish_hk_0_2_rows(shared,signal_date='20260930',target_date='20261008',
        rows=rows('20260930','20261008'),panel_sha256='b'*64)
    seed_authority(shared,'20261007',monkeypatch)
    before=file_map(shared)
    with pytest.raises(hk.StoreError):
        hk.publish_hk_0_2_rows(shared,signal_date='20261007',target_date='20261008',
            rows=rows('20261007','20261008'),panel_sha256='c'*64)
    assert file_map(shared)==before


@pytest.mark.parametrize('eligibility',['20260930','20261008'])
def test_resealed_past_or_future_source_is_not_assumed_valid_for_price_day(tmp_path,monkeypatch,eligibility):
    shared=tmp_path/'shared';seed_authority(shared,eligibility,monkeypatch);before=file_map(shared)
    hk=mod('hk_0_2')
    with pytest.raises(hk.StoreError):
        hk.publish_hk_0_2_rows(shared,signal_date='20261007',target_date='20261008',
            eligibility_source_date=eligibility,rows=rows('20261007','20261008'),panel_sha256='b'*64)
    assert file_map(shared)==before


def test_workload_policy_only_changes_preselection_not_six_other_catalog_entries():
    from contracts.trading_calendar import RunPolicy,MarketScope,SessionRequirement
    from domains.runtime_policy import evaluate_run_policy
    decision=evaluate_run_policy(RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,'20261007','1730',
        market_scope=MarketScope.CROSS_MARKET,session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY)
    assert decision.eligible and decision.eligible_markets==('hk_securities',)
    catalog=json.loads((ROOT/'contracts/runtime_workloads.json').read_text())
    entry=next(x for x in catalog['workloads'] if x['workload_id']=='preselection_pools')
    assert entry['run_policy']=='A_OR_HK_SECURITIES_TRADE_DAY'
