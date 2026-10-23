"""Frozen repair scope; real local stores/callers, external processes are forbidden."""
from __future__ import annotations
import contextlib
import copy
import csv
import hashlib
import importlib
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import pytest

if not os.environ.get('V4_REPAIR_EVIDENCE_ROOT'):
    pytest.skip('requires the frozen local provenance repair evidence capsule', allow_module_level=True)
E = Path(os.environ['V4_REPAIR_EVIDENCE_ROOT'])
F = E / 'writer/fixtures'
FLAGS = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fixture(name):
    return json.loads((F / name).read_text())


def request(slot='1800', target='20261026'):
    from contracts.runtime_tasks import DispatchRequest, DispatchMode
    return DispatchRequest(scheduled_date='20261023', business_date='20261023', target_date=target, slot=slot, mode=DispatchMode.LIVE)


def pool_gate(artifacts):
    import inspect
    from ops.materialize_scheduled_preselection import _formal_pool_gate
    return _formal_pool_gate(artifacts, **({'market_scope':'CROSS_MARKET'}
        if 'market_scope' in inspect.signature(_formal_pool_gate).parameters else {}))


def slot_blocks_retry(*args,**kwargs):
    import importlib.util
    if importlib.util.find_spec('ops.run_v35_macos_scheduler_due') is not None:
        from ops.run_v35_macos_scheduler_due import _slot_blocks_retry
    else:
        from ops.run_v35_macos_scheduler import _slot_blocks_retry
    return _slot_blocks_retry(*args,**kwargs)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    paths = {k: tmp_path / k for k in ['data','shared','selector','input','package']}
    for p in paths.values(): p.mkdir()
    for k, env in [('data','V35_DATA_ROOT'),('shared','V35_SHARED_DATA_ROOT'),('selector','V35_SELECTOR_DATA_ROOT'),('input','V35_PRESELECTION_INPUT_ROOT')]: monkeypatch.setenv(env, str(paths[k]))
    monkeypatch.setenv('V35_RELEASE_ID','test-candidate')
    monkeypatch.setenv('V35_UPSTREAM_FINGERPRINT','static-tree')
    from infrastructure.scheduling import dispatcher
    if hasattr(dispatcher,'validate_release_identity'):
        app=Path(dispatcher.__file__).resolve().parents[2]
        entries=[{'path':rel,'kind':'file','size':(app/rel).stat().st_size,'sha256':sha(app/rel)} for rel in dispatcher._RUNTIME_IDENTITY_FILES]
        manifest=tmp_path/'release-manifest.json'
        manifest.write_text(json.dumps({'schema_version':'v4.release_candidate.v1','candidate':{'app_root':str(app),'release_id':'test-candidate'},
            'application_inventory':{'entry_count':len(entries),'entries':entries,'aggregate_sha256':hashlib.sha256(json.dumps(entries,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}}))
        monkeypatch.setenv('V35_APP_ROOT',str(app));monkeypatch.setenv('V35_RELEASE_MANIFEST_PATH',str(manifest));monkeypatch.setenv('V35_RELEASE_MANIFEST_SHA256',sha(manifest))
    return SimpleNamespace(**paths)


def test_existing_v192_reuses_without_selector_env(roots, monkeypatch, capsys):
    # Reading the producer-only env before the verified reader breaks reuse.
    from ops import materialize_shared_v192_preselection as wrapper
    class StoreError(Exception): pass
    def read(root, *, target_date, expected_signal_date):
        assert target_date == '20261026' and expected_signal_date == '20261023'
        return SimpleNamespace(run=SimpleNamespace(receipt={'status':'READY'},manifest={'provenance':{}},verification={'run_id':'verified-existing'}))
    def forbidden(*a, **k): pytest.fail('existing exact source entered producer')
    module=SimpleNamespace(StoreError=StoreError,read_verified_v192_pool=read,materialize_frozen_v192_selector=forbidden)
    monkeypatch.setattr(wrapper,'load_isolated_package_module',lambda *a, **k: module)
    monkeypatch.setenv('V35_SHARED_PACKAGE_ROOT',str(roots.package));monkeypatch.setenv('V3_SHARED_DATA_STORE_ROOT',str(roots.shared));monkeypatch.delenv('V3_SHARED_SELECTOR_READY_PANEL',raising=False)
    assert wrapper.main(['--signal-date','20261023','--target-date','20261026']) == 0
    assert json.loads(capsys.readouterr().out)['already_exists'] is True


def test_missing_v192_is_typed_without_scoring(roots, monkeypatch, capsys):
    from ops import materialize_shared_v192_preselection as wrapper
    class StoreError(Exception): pass
    def missing(*a, **k): raise StoreError('no latest run for exact target')
    def forbidden(*a, **k): pytest.fail('missing selector entered scorer')
    monkeypatch.setattr(wrapper,'load_isolated_package_module',lambda *a,**k: SimpleNamespace(StoreError=StoreError,read_verified_v192_pool=missing,materialize_frozen_v192_selector=forbidden))
    monkeypatch.setenv('V35_SHARED_PACKAGE_ROOT',str(roots.package));monkeypatch.setenv('V3_SHARED_DATA_STORE_ROOT',str(roots.shared));monkeypatch.delenv('V3_SHARED_SELECTOR_READY_PANEL',raising=False)
    assert wrapper.main(['--signal-date','20261023','--target-date','20261026']) == 1
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='CANNOT_CONFIRM' and result['failure_class']=='UPSTREAM_NOT_READY'


def test_valid210_and_hk100_survive_missing_formal_a(roots):
    from ops.materialize_scheduled_preselection import _formal_pool_gate, _missing, publish_scheduled_artifacts
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    a=fixture('a_share_research_recommendation_pool.json');hk=fixture('hkconnect_d1_top100.json')
    missing=_missing('20261026',pool_id='a_d1_premarket_pool',display_name='A',market='A',reason='A_V192_EXACT_INPUT_MISSING')
    store=PreselectionPoolStore(roots.data)
    results=publish_scheduled_artifacts(store,[missing,a,hk])
    gate=pool_gate([missing,a,hk])
    assert gate['research_ready'] is True and gate['status'] in {'PARTIAL_WITH_ROWS','PARTIAL'}
    assert gate['required']['a_d1_premarket_pool']['ready'] is False
    assert len(store.read_pool('20261026',a['pool_id'])['rows'])==210
    assert len(store.read_pool('20261026',hk['pool_id'])['rows'])==100
    assert not (roots.data/'preselection_pools/20261026/a_d1_premarket_pool.json').exists()
    assert results[0]['status']=='DEFERRED'


def test_all_missing_or_invalid_is_not_admitted():
    from ops.materialize_scheduled_preselection import _formal_pool_gate, _missing
    missing=_missing('20261026',pool_id='a_d1_premarket_pool',display_name='A',market='A',reason='MISSING')
    bad=fixture('a_share_research_recommendation_pool.json');bad['source_sha256']='bad'
    gate=pool_gate([missing,bad])
    assert gate['research_ready'] is False and gate['status']=='CANNOT_CONFIRM'


def frozen_recovery(root, mutate=None):
    # Preserve exact original content except mandatory owned-path rebinding.
    payload=fixture('1800.recovery-a4d7d02dea8f6e61.json')
    canonical=root/'research/incoming/20261023/1800.json';canonical.parent.mkdir(parents=True,exist_ok=True)
    for obj in [payload,payload['recovery_metadata']]:
        obj['source_path']=str(canonical);obj['original_source_path']=str(canonical)
    if mutate: mutate(payload)
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode();h=hashlib.sha256(raw).hexdigest()
    path=canonical.with_name('1800.recovery-'+h[:16]+'.json');path.write_bytes(raw)
    return path,payload


def test_actual_first_admission_recovery_advances_to_unchanged_pit_rejection(roots):
    from ops import run_hourly_research as runner
    path,payload=frozen_recovery(roots.data)
    before=path.read_bytes()
    with pytest.raises(ValueError, match="source is not point-in-time safe|HOURLY_SOURCE_MANIFEST_PIT_MISMATCH"):
        runner.run_hourly_research_file(data_root=roots.data,source=path,business_date='20261023',target_date='20261023',slot='1800',mode='LIVE')
    assert path.read_bytes()==before
    assert payload['original_time_capture'] is False and payload['natural_execution_verified'] is False
    assert not (path.parent/'1800.json').exists()
    assert not (roots.data/'research/hourly').exists()


@pytest.mark.parametrize('change',[
    lambda p:p['source_manifest'].update(hourly_slot='1700'),
    lambda p:p['source_manifest'].update(trade_date='20261022'),
    lambda p:p['source_manifest'].update(pit_cutoff='2026-10-23T18:01:00+08:00'),
    lambda p:p.update(original_time_capture=True),
    lambda p:p.update(natural_execution_verified=True),
    lambda p:p['recovery_metadata'].update(original_source_sha256='a'*64),
    lambda p:p['source_manifest'].update(source_receipts=[]),
])
def test_bad_recovery_provenance_rejects_without_publication(roots,change):
    from ops.run_hourly_research import run_hourly_research_file
    path,_=frozen_recovery(roots.data,change)
    with pytest.raises(ValueError): run_hourly_research_file(data_root=roots.data,source=path,business_date='20261023',target_date='20261023',slot='1800',mode='LIVE')
    assert not (roots.data/'research/hourly').exists()


def test_runner_event_cutoff_still_includes_last_microsecond():
    from domains.research_source_validation import runner_source_cutoff,collector_source_cutoff
    assert runner_source_cutoff('20261023','1800').isoformat()=='2026-10-23T18:00:59.999999+08:00'
    assert collector_source_cutoff('20261023','1800').isoformat()=='2026-10-23T18:00:59+08:00'


def test_typed_deterministic_failure_wins_over_sibling_missing_text():
    from infrastructure.scheduling.dispatcher import _failure_class
    assert _failure_class(({'failure_class':'INVALID_INPUT','status':'FAILED'}, {'status':'FAILED','stderr':'upstream missing'}))=='INVALID_INPUT'


def test_same_input_wait_stops_then_new_input_allows_one_attempt(roots,tmp_path):
    from infrastructure.scheduling.input_retry_identity import observe_input_identity, make_input_wait
    req=request();identity=observe_input_identity('preselection_pools',req.business_date,req.target_date,req.slot)
    wait=make_input_wait(identity,'EXACT_INPUT_MISSING')
    ledger=tmp_path/'ledger';receipts=ledger/'receipts/live/20261023/1800';receipts.mkdir(parents=True)
    rec={'status':'FAILED','slot':'1800','business_date':'20261023','target_date':'20261026','release_id':'test-candidate','upstream_fingerprint':'static-tree','failure_class':'UPSTREAM_NOT_READY','finished_at':'2026-10-23T10:00:00Z','retry_after':'2026-10-23T10:05:00Z','workload_results':[{'workload_id':'preselection_pools','status':'FAILED','input_wait':wait}]}
    (receipts/'one.dispatch-receipt.json').write_text(json.dumps(rec))
    kwargs=dict(moment=datetime(2026,10,23,12,tzinfo=UTC),release_id='test-candidate',upstream_fingerprint='static-tree')
    assert slot_blocks_retry(ledger,'20261023','1800',**kwargs) is True
    # An unrelated registry entry and logs cannot awaken it.
    (roots.shared/'latest.json').write_text(json.dumps({'entries':{'20261022/UNRELATED':{'run_id':'new'}}}))
    assert slot_blocks_retry(ledger,'20261023','1800',**kwargs) is True
    pointer=roots.selector/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt';pointer.parent.mkdir();pointer.write_text(str(roots.selector/'new-panel.parquet'))
    assert slot_blocks_retry(ledger,'20261023','1800',**kwargs) is False
    new_wait=make_input_wait(observe_input_identity('preselection_pools',req.business_date,req.target_date,req.slot),'EXACT_INPUT_MISSING')
    rec['workload_results'][0]['input_wait']=new_wait
    rec['finished_at']='2026-10-23T10:10:00Z';rec['attempt']=2
    (receipts/'two.dispatch-receipt.json').write_text(json.dumps(rec))
    assert slot_blocks_retry(ledger,'20261023','1800',**kwargs) is True


def test_network_failure_retains_backoff(roots,tmp_path):
    p=tmp_path/'ledger/receipts/live/20261023/1800';p.mkdir(parents=True)
    (p/'one.dispatch-receipt.json').write_text(json.dumps({'status':'FAILED','failure_class':'NETWORK','finished_at':'2026-10-23T10:00:00Z','retry_after':'2026-10-23T10:05:00Z'}))
    assert slot_blocks_retry(tmp_path/'ledger','20261023','1800',moment=datetime(2026,10,23,10,4,tzinfo=UTC)) is True
    assert slot_blocks_retry(tmp_path/'ledger','20261023','1800',moment=datetime(2026,10,23,10,6,tzinfo=UTC)) is False


def install_shared_fixture(roots,monkeypatch,*,target='20261026'):
    """Keep the external read-only store checksum chain real; no models/panels."""
    from infrastructure.isolated_package_loader import load_isolated_package_module
    provider=load_isolated_package_module(F/'shared-package',package_directory='shared_data',module_leaf='consumer',namespace_prefix='repair_test_shared')
    entries={}
    roles=['HK_CONNECT_D1_TOP100_0_2'] if target=='20261026' else ['HK_CONNECT_D1_TOP100_0_2','A_SHARE_V192_PREMARKET_POOL_V3']
    for role in roles:
        if target=='20261026':
            entry=fixture('hk-latest-entry.json');directory=F
            files={'artifact':directory/'hk-source.csv','manifest':directory/'hk-source.manifest.json','receipt':directory/'hk-source.receipt.json'}
        else:
            directory=F/'target23'/role;entry=json.loads((directory/'entry.json').read_text())
            files={kind:directory/(kind+('.csv' if kind=='artifact' else '.json')) for kind in ['artifact','manifest','receipt']}
        entries[target+'/'+role]=entry
        for kind,path in files.items():
            dest=roots.shared/entry[kind+'_relative'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
    (roots.shared/'latest.json').write_text(json.dumps({'schema_version':'v3_shared_data.latest.v1','entries':entries}))
    # Read the real immutable artifact/manifest/receipt chain below the external
    # strict leaf boundary. Heavy resolution-policy/model assets are intentionally
    # excluded. Production still uses the unchanged full strict leaf reader.
    def reader(role):
        def read(root,*,target_date,expected_signal_date):
            run=provider.read_verified_latest(root,target_date,role)
            assert run.manifest['provenance']['signal_date']==expected_signal_date
            with run.artifact_path.open(encoding='utf-8-sig') as handle: rows=list(csv.DictReader(handle))
            return SimpleNamespace(run=run,rows=rows)
        return read
    import infrastructure.isolated_package_loader as loader
    actual=loader.load_isolated_package_module
    def load(root,*,module_leaf,**kwargs):
        if module_leaf=='hk_0_2':return SimpleNamespace(read_verified_hk_0_2_pool=reader('HK_CONNECT_D1_TOP100_0_2'),StoreError=provider.StoreError,SafeRootStore=provider.SafeRootStore,HK_0_2_ROLE='HK_CONNECT_D1_TOP100_0_2')
        if module_leaf=='v192_selector':return SimpleNamespace(read_verified_v192_pool=reader('A_SHARE_V192_PREMARKET_POOL_V3'),StoreError=provider.StoreError)
        return actual(root,module_leaf=module_leaf,**kwargs)
    monkeypatch.setattr(loader,'load_isolated_package_module',load)
    import infrastructure.scheduling.executor_registry as facade
    if hasattr(facade,'load_isolated_package_module'):monkeypatch.setattr(facade,'load_isolated_package_module',load)
    return {**{role:reader(role) for role in roles},'_StoreError':provider.StoreError},entries


def cached_hk(roots):
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    pool=fixture('hkconnect_d1_top100.json')
    PreselectionPoolStore(roots.data).materialize(pool)
    return pool


def test_strict_hk_reuses_independently_without_duplicate_cache_hashes(roots,monkeypatch):
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    readers,_=install_shared_fixture(roots,monkeypatch);pool=cached_hk(roots)
    assert 'source_manifest_sha256' not in pool and 'source_receipt_sha256' not in pool
    reg=FixedExecutorRegistry(data_root=roots.data,shared_data_root=roots.shared,shared_package_root=roots.package)
    if not hasattr(reg,'_verified_formal_pool_reuse'):
        from ops.materialize_scheduled_preselection import _verified_cached_formal_pool
        from infrastructure.preselection_pool_store import PreselectionPoolStore
        reused_pool=_verified_cached_formal_pool(PreselectionPoolStore(roots.data),'hkconnect_d1_top100','20261026',roots.shared,roots.package)
        assert len(reused_pool['rows'])==100 and reused_pool==pool
        return
    reused=reg._verified_formal_pool_reuse('20261026')
    assert len(reused['pools']['hkconnect_d1_top100']['rows'])==100
    assert 'a_d1_premarket_pool' not in reused['pools']
    assert not reused['rejected']


@pytest.mark.parametrize('kind',['declared_hash','declared_name_pin','manifest','receipt','date','row_score'])
def test_hk_bad_cache_or_source_is_never_reused(roots,monkeypatch,kind):
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    readers,entries=install_shared_fixture(roots,monkeypatch);pool=fixture('hkconnect_d1_top100.json')
    if kind=='declared_hash':pool['source_manifest_sha256']='0'*64
    if kind=='declared_name_pin':pool['rows'][0]['name_resolution']={'source_sha256':'0'*64}
    if kind=='date':pool['signal_date']='20261022'
    if kind=='row_score':pool['rows'][0]['pool_score']+=0.01
    PreselectionPoolStore(roots.data).materialize(pool)
    if kind in {'manifest','receipt'}:
        p=roots.shared/entries['20261026/HK_CONNECT_D1_TOP100_0_2'][kind+'_relative'];d=json.loads(p.read_text());d['row_count' if kind=='manifest' else 'status']=101 if kind=='manifest' else 'FAILED';p.write_text(json.dumps(d))
    reg=FixedExecutorRegistry(data_root=roots.data,shared_data_root=roots.shared,shared_package_root=roots.package)
    if not hasattr(reg,'_verified_formal_pool_reuse'):
        from ops.materialize_scheduled_preselection import _verified_cached_formal_pool
        with pytest.raises((ValueError,readers['_StoreError'])):
            _verified_cached_formal_pool(PreselectionPoolStore(roots.data),'hkconnect_d1_top100','20261026',roots.shared,roots.package)
        return
    reused=reg._verified_formal_pool_reuse('20261026')
    assert 'hkconnect_d1_top100' not in reused['pools']
    assert 'hkconnect_d1_top100' in reused['rejected']


def test_complete_real_builder_pair_reuses_both_lanes(roots,monkeypatch):
    from domains.preselection_materializer import build_shared_hk_0_2_pool,build_shared_v192_premarket_pool
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    readers,_=install_shared_fixture(roots,monkeypatch,target='20261023');store=PreselectionPoolStore(roots.data)
    for role,builder in [('HK_CONNECT_D1_TOP100_0_2',build_shared_hk_0_2_pool),('A_SHARE_V192_PREMARKET_POOL_V3',build_shared_v192_premarket_pool)]:
        store.materialize(builder(roots.shared,trade_date='20261023',signal_date='20261022',reader=readers[role]))
    reg=FixedExecutorRegistry(data_root=roots.data,shared_data_root=roots.shared,shared_package_root=roots.package)
    if not hasattr(reg,'_verified_formal_pool_reuse'):
        from ops.materialize_scheduled_preselection import _verified_cached_formal_pool
        assert len(_verified_cached_formal_pool(store,'hkconnect_d1_top100','20261023',roots.shared,roots.package)['rows'])==100
        assert len(_verified_cached_formal_pool(store,'a_d1_premarket_pool','20261023',roots.shared,roots.package)['rows'])==3
        return
    reused=reg._verified_formal_pool_reuse('20261023')
    assert set(reused['pools'])=={'a_d1_premarket_pool','hkconnect_d1_top100'} and not reused['rejected']
    assert reused['producer_called'] is False


def test_a_ready_hk_missing_retains_hk_only_retry(roots,monkeypatch):
    from domains.preselection_materializer import build_shared_v192_premarket_pool
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    readers,_=install_shared_fixture(roots,monkeypatch,target='20261023')
    pool=build_shared_v192_premarket_pool(roots.shared,trade_date='20261023',signal_date='20261022',reader=readers['A_SHARE_V192_PREMARKET_POOL_V3'])
    PreselectionPoolStore(roots.data).materialize(pool)
    reg=FixedExecutorRegistry(data_root=roots.data,shared_data_root=roots.shared,shared_package_root=roots.package)
    if not hasattr(reg,'_verified_formal_pool_reuse'):
        from infrastructure.scheduling._executor_registry_parts.preselection import _retry_missing_hk_only
        from contracts.runtime_tasks import DispatchRequest,DispatchMode
        a_path=roots.data/'preselection_pools/20261023/a_d1_premarket_pool.json';before=sha(a_path)
        result=_retry_missing_hk_only(reg,DispatchRequest(scheduled_date='20261022',business_date='20261022',target_date='20261023',slot='1730',mode=DispatchMode.LIVE),signal_date='20261022',target_date='20261023',a_identity={'source_sha256':pool['source_sha256']},eligibility_source_date='20261022')
        assert result['status']=='SUCCEEDED' and result['hk_only_retry'] is True
        assert result['A_producer_called'] is False and sha(a_path)==before
        return
    reused=reg._verified_formal_pool_reuse('20261023')
    assert reused['hk_missing_retry'] is True and reused['a_identity']['source_sha256']==pool['source_sha256']


def test_observer_rejects_escaping_pointer_without_hot_loop(roots,tmp_path):
    from infrastructure.scheduling.input_retry_identity import observe_input_identity,make_input_wait,input_wait_changed
    pointer=roots.selector/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt';pointer.parent.mkdir()
    pointer.write_text(str(tmp_path/'outside.parquet'))
    wait=make_input_wait(observe_input_identity('preselection_pools','20261023','20261026','1800'),'MISSING')
    assert wait['observations']['selector_availability']['state']=='REJECTED_OWNED_PATH'
    assert input_wait_changed(wait) is False
    (tmp_path/'outside.parquet').write_bytes(b'not owned')
    assert input_wait_changed(wait) is False


def test_recovery_versions_are_not_new_input(roots):
    from infrastructure.scheduling.input_retry_identity import observe_input_identity,make_input_wait,input_wait_changed
    path,payload=frozen_recovery(roots.data)
    wait=make_input_wait(observe_input_identity('hourly_research','20261023','20261023','1800'),'PIT_INVALID')
    payload['source_manifest']['generated_at']='2026-10-23T18:20:00+08:00';payload['source_manifest']['published_at']='2026-10-23T18:20:00+08:00';payload['source_manifest']['version']='retry-version'
    encoded=json.dumps(payload,sort_keys=True).encode();h=hashlib.sha256(encoded).hexdigest();path.with_name('1800.recovery-'+h[:16]+'.json').write_bytes(encoded)
    assert input_wait_changed(wait) is False


def test_real_preselection_caller_skips_ready_hk_and_research_producers(roots,monkeypatch):
    import subprocess
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from ops import materialize_scheduled_preselection as cli
    readers,_=install_shared_fixture(roots,monkeypatch);cached_hk(roots)
    store=PreselectionPoolStore(roots.data);research=fixture('a_share_research_recommendation_pool.json');store.materialize(research)
    before=sha(roots.data/'preselection_pools/20261026/a_share_research_recommendation_pool.json')
    for name in ['capture_public_fupan.py','materialize_v192_selector.py']:
        path=roots.package/'scripts'/name;path.parent.mkdir(exist_ok=True);path.write_text('# external boundary, never executed')
    def no_research(*a,**k):pytest.fail('already successful research pool re-entered producer')
    monkeypatch.setattr(cli,'build_hourly_research_pool',no_research)
    monkeypatch.setattr(cli,'load_baimao_preselection_pool',lambda *a,**k:cli._missing('20261026',pool_id='a_share_baimao_research_map',display_name='B',market='A',reason='MISSING'))
    def missing_a(*a,**k):raise FileNotFoundError('exact A input missing')
    calls=[]
    def external(command,*,cwd,timeout_seconds,env):
        name=command[2];calls.append(name)
        if name.startswith('scripts.update_hk') or name in {'ops.ensure_hk_security_master','scripts.materialize_hk_0_2'}:pytest.fail('verified HK re-entered producer/security/scorer')
        if name=='ops.materialize_scheduled_preselection':
            output=io.StringIO()
            with contextlib.redirect_stdout(output):code=cli.main(list(command[3:]),pool_reader=missing_a,hk_pool_reader=readers['HK_CONNECT_D1_TOP100_0_2'])
            return subprocess.CompletedProcess(command,code,output.getvalue(),'')
        if name=='ops.materialize_shared_v192_preselection':return subprocess.CompletedProcess(command,1,json.dumps({'status':'CANNOT_CONFIRM','reason':'A_V192_EXACT_INPUT_MISSING'}),'')
        return subprocess.CompletedProcess(command,0,json.dumps({'status':'READY'}),'')
    reg=FixedExecutorRegistry(data_root=roots.data,shared_data_root=roots.shared,shared_package_root=roots.package,
        hk_universe_root=roots.shared,selector_data_root=None,preselection_input_root=roots.input,repo_root=Path(cli.__file__).parents[1],runner=external)
    result=reg._preselection_pools(request())
    assert result['status']=='SUCCEEDED'
    assert result['consumer_status']=='PARTIAL_WITH_ROWS'
    assert result['input_wait']['pending_pool_ids']==['a_d1_premarket_pool']
    assert result['input_wait']['wait_for_input_change'] is True
    assert len(store.read_pool('20261026',research['pool_id'])['rows'])==210
    assert sha(roots.data/'preselection_pools/20261026/a_share_research_recommendation_pool.json')==before
    assert result['hk_lane_status'] in {'READY','SUCCEEDED'}


def catalog_for_partial_test():
    from contracts.runtime_tasks import RuntimeCatalog,WorkloadDefinition,SafetyBoundary
    from contracts.trading_calendar import MarketScope,RunPolicy,SessionRequirement
    safe=SafetyBoundary(**FLAGS)
    workloads=tuple(WorkloadDefinition(workload_id=n,owner_id=n,run_policy=RunPolicy.NATURAL_DAY,
        market_scope=MarketScope.CROSS_MARKET,session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
        slots=('1800',),command=(),aliases=(),enabled=True,scheduled_date_role='SCHEDULED_DATE',
        signal_date_role='BUSINESS_DATE',target_date_role='TARGET_DATE',safety=safe)
        for n in ['hourly_research','preselection_pools'])
    return RuntimeCatalog(schema_version='test',workloads=workloads,task_registrations=(),retired_owners=(),safety=safe,_source_payload={})


def test_partial_input_wait_releases_only_incomplete_claim_and_resumes_once(roots,tmp_path):
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    from infrastructure.scheduling.input_retry_identity import observe_input_identity,make_input_wait
    ledger=ExecutionLedger(tmp_path/'ledger');req=request();calls=[]
    def execute(workload,request,decision):
        calls.append(workload.workload_id)
        if workload.workload_id=='hourly_research':return {'status':'SUCCEEDED',**FLAGS}
        identity=observe_input_identity('preselection_pools','20261023','20261026','1800',['a_d1_premarket_pool'])
        return {'status':'SUCCEEDED','consumer_status':'PARTIAL_WITH_ROWS','input_wait':make_input_wait(identity,'V192_MISSING'),**FLAGS}
    first=dispatch_due(req,catalog_for_partial_test(),execute,ledger=ledger)
    assert first.status=='SUCCEEDED'
    sibling=ledger.root/'workloads/live/20261023/1800/hourly_research.workload-claim.json'
    pending=ledger.root/'workloads/live/20261023/1800/preselection_pools.workload-claim.json'
    assert sibling.is_file() and not pending.exists()
    sibling_sha=sha(sibling)
    kwargs=dict(moment=datetime(2026,10,23,23,tzinfo=UTC),release_id='test-candidate',upstream_fingerprint='static-tree')
    assert slot_blocks_retry(ledger.root,'20261023','1800',**kwargs) is True
    # A direct repeated request must also remain quiet, even if due is bypassed.
    dispatch_due(req,catalog_for_partial_test(),execute,ledger=ledger)
    assert calls==['hourly_research','preselection_pools']
    pointer=roots.selector/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt';pointer.parent.mkdir();pointer.write_text(str(roots.selector/'new.parquet'))
    assert slot_blocks_retry(ledger.root,'20261023','1800',**kwargs) is False
    dispatch_due(req,catalog_for_partial_test(),execute,ledger=ledger)
    assert calls==['hourly_research','preselection_pools','preselection_pools']
    assert sha(sibling)==sibling_sha and not pending.exists()
    assert slot_blocks_retry(ledger.root,'20261023','1800',**kwargs) is True


def test_direct_panel_dependencies_awaken_once_and_ignore_attempt_envelopes(roots):
    from infrastructure.scheduling.input_retry_identity import observe_input_identity,make_input_wait,input_wait_changed
    root=roots.data.parent/'research_panel_daily/receipts';root.mkdir(parents=True)
    receipt=root/'a-20261023.json';receipt.write_text(json.dumps({'status':'FAILED','source_sha256':'a'*64,'generated_at':'old','error':'same failure'}))
    wait=make_input_wait(observe_input_identity('research_panel_runtime_evidence','20261023','20261026','1730'),'PRODUCER_NOT_READY')
    assert input_wait_changed(wait) is False
    receipt.write_text(json.dumps({'status':'FAILED','source_sha256':'a'*64,'generated_at':'new','error':'same failure','attempt':10}))
    assert input_wait_changed(wait) is False
    receipt.write_text(json.dumps({'status':'READY','source_sha256':'b'*64,'generated_at':'later'}))
    assert input_wait_changed(wait) is True
    recovered=make_input_wait(observe_input_identity('research_panel_runtime_evidence','20261023','20261026','1730'),'HK_CLOSE_MISSING')
    assert input_wait_changed(recovered) is False
    p=roots.data/'close_reviews/20261023.json';p.parent.mkdir();p.write_text(json.dumps({'status':'READY','trade_date':'20261023','source_sha256':'c'*64}))
    assert input_wait_changed(recovered) is True
    frozen=make_input_wait(observe_input_identity('research_panel_runtime_evidence','20261023','20261026','1730'),'WAIT')
    p.write_text('{tampered')
    assert input_wait_changed(frozen) is True
    rejected=make_input_wait(observe_input_identity('research_panel_runtime_evidence','20261023','20261026','1730'),'INVALID')
    assert input_wait_changed(rejected) is False


def test_capture_retry_contract_is_not_replaced_by_hourly_input_wait():
    from infrastructure.scheduling.input_retry_identity import observe_input_identity
    assert observe_input_identity('hourly_research','20261023','20261023','1530') is None


def test_malformed_retry_receipt_fails_closed_without_breaking_due(roots,tmp_path):
    p=tmp_path/'ledger/receipts/live/20261023/1800';p.mkdir(parents=True)
    (p/'bad.dispatch-receipt.json').write_text(json.dumps({'status':'FAILED','attempt':'bad','failure_class':'UPSTREAM_NOT_READY','finished_at':'2026-10-23T10:00:00Z'}))
    assert slot_blocks_retry(tmp_path/'ledger','20261023','1800',moment=datetime(2026,10,23,12,tzinfo=UTC)) is True


def test_real_hourly_caller_types_genuine_pit_failure(roots):
    import subprocess
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from ops.run_hourly_research import run_hourly_research_file
    source,_=frozen_recovery(roots.data)
    def external(command,*,cwd,timeout_seconds,env):
        name=command[2]
        if name=='ops.collect_hourly_research_input':
            payload={'status':'READY_WITH_RESEARCH_POOL','row_count':93,'recovery':True,'source_path':str(source.relative_to(roots.data)),'source_sha256':sha(source)}
        elif name=='ops.run_hourly_research':
            with pytest.raises(ValueError) as error:
                run_hourly_research_file(data_root=roots.data,source=source,business_date='20261023',target_date='20261023',slot='1800',mode='LIVE')
            return subprocess.CompletedProcess(command,1,'','ValueError: '+str(error.value))
        elif name in {'ops.run_zsxq_hourly_delta','ops.materialize_research_peripherals'}:
            payload={'status':'READY'}
        else:pytest.fail('unexpected external operation: '+name)
        return subprocess.CompletedProcess(command,0,json.dumps(payload),'')
    reg=FixedExecutorRegistry(data_root=roots.data,repo_root=source.parents[4],runner=external)
    result=reg._hourly_research(request(target='20261023'))
    assert result['status']=='FAILED' and result['failure_class']=='INVALID_INPUT'
    assert result['failure_code']=='HOURLY_SOURCE_PIT_INVALID'
    assert not (roots.data/'research/hourly').exists()


@pytest.mark.parametrize('failure_kind',['INVALID_INPUT','UPSTREAM_NOT_READY','CONTRACT','HK_HISTORY_RESOLUTION_CACHE_REJECTED'])
def test_mixed_failure_receipt_releases_claims_and_retries_only_network(roots,tmp_path,monkeypatch,failure_kind):
    from dataclasses import replace
    from datetime import timedelta
    from infrastructure.scheduling import dispatcher
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    clock=[datetime(2026,10,23,10,tzinfo=UTC)]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)
    monkeypatch.setattr(dispatcher,'datetime',Clock)
    ledger=ExecutionLedger(tmp_path/'ledger');calls=[];catalog=catalog_for_partial_test()
    catalog=replace(catalog,workloads=(*catalog.workloads,replace(catalog.workloads[0],workload_id='successful_sibling',owner_id='successful_sibling')))
    def execute(workload,req,decision):
        calls.append(workload.workload_id)
        if workload.workload_id=='successful_sibling':return {'status':'SUCCEEDED',**FLAGS}
        return {'status':'FAILED','failure_class':'NETWORK' if workload.workload_id=='hourly_research' else failure_kind,**FLAGS}
    first=dispatcher.dispatch_due(request(),catalog,execute,ledger=ledger)
    payload=json.loads((ledger.root/first.receipt_path).read_text())
    assert payload['release_id']=='test-candidate' and payload['upstream_fingerprint']=='static-tree'
    assert payload['retry_after']
    for workload in ['hourly_research','preselection_pools']:
        assert not (ledger.root/f'workloads/live/20261023/1800/{workload}.workload-claim.json').exists()
    assert not (ledger.root/'claims/live/20261023/1800/dispatch.claim.json').exists()
    sibling=ledger.root/'workloads/live/20261023/1800/successful_sibling.workload-claim.json';before=sha(sibling)
    kwargs=dict(release_id='test-candidate',upstream_fingerprint='static-tree')
    assert slot_blocks_retry(ledger.root,'20261023','1800',moment=clock[0]+timedelta(minutes=4),**kwargs) is True
    # A changed deterministic dependency permits its one validation attempt,
    # without waking a transient sibling before that sibling's deadline.
    pointer=roots.selector/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt';pointer.parent.mkdir();pointer.write_text(str(roots.selector/'new.parquet'))
    assert slot_blocks_retry(ledger.root,'20261023','1800',moment=clock[0],**kwargs) is False
    clock[0]+=timedelta(seconds=1)
    dispatcher.dispatch_due(request(),catalog,execute,ledger=ledger)
    assert calls==['hourly_research','preselection_pools','successful_sibling','preselection_pools']
    clock[0]+=timedelta(minutes=6)
    assert slot_blocks_retry(ledger.root,'20261023','1800',moment=clock[0],**kwargs) is False
    third=dispatcher.dispatch_due(request(),catalog,execute,ledger=ledger)
    assert calls==['hourly_research','preselection_pools','successful_sibling','preselection_pools','hourly_research']
    assert sha(sibling)==before
    pending=next(r for r in third.workload_results if r['workload_id']=='preselection_pools')
    assert pending['reason']=='UNCHANGED_INPUT_WAIT' and pending['producer_called'] is False
    assert slot_blocks_retry(ledger.root,'20261023','1800',moment=clock[0],**kwargs) is True


@pytest.mark.parametrize('remaining_kind,blocked_after',[('NETWORK',False),('EXTERNAL_SOURCE',False),('SAFETY',True),('UNKNOWN',True)])
def test_mixed_due_receipt_preserves_transient_backoff(roots,tmp_path,remaining_kind,blocked_after):
    from infrastructure.scheduling.input_retry_identity import observe_input_identity,make_input_wait
    wait=make_input_wait(observe_input_identity('preselection_pools','20261023','20261026','1800'),'INVALID_INPUT')
    p=tmp_path/'ledger/receipts/live/20261023/1800';p.mkdir(parents=True)
    p.joinpath('one.dispatch-receipt.json').write_text(json.dumps({'status':'FAILED','failure_class':'INVALID_INPUT','finished_at':'2026-10-23T10:00:00Z','workload_results':[
        {'workload_id':'hourly_research','status':'FAILED','failure_class':remaining_kind},
        {'workload_id':'preselection_pools','status':'FAILED','failure_class':'INVALID_INPUT','input_wait':wait}]}))
    assert slot_blocks_retry(tmp_path/'ledger','20261023','1800',moment=datetime(2026,10,23,10,4,tzinfo=UTC)) is True
    assert slot_blocks_retry(tmp_path/'ledger','20261023','1800',moment=datetime(2026,10,23,12,tzinfo=UTC)) is blocked_after


def test_deterministic_failure_without_observer_preserves_release_identity(roots,tmp_path):
    from dataclasses import replace
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    ledger=ExecutionLedger(tmp_path/'ledger');catalog=catalog_for_partial_test()
    catalog=replace(catalog,workloads=(replace(catalog.workloads[0],workload_id='no_input_observer',owner_id='no_input_observer'),))
    receipt=dispatch_due(request(),catalog,lambda *a:{'status':'FAILED','failure_class':'CONTRACT',**FLAGS},ledger=ledger)
    payload=json.loads((ledger.root/receipt.receipt_path).read_text())
    assert payload['release_id']=='test-candidate' and payload['failure_class']=='CONTRACT'
    assert 'input_wait' not in payload['workload_results'][0]
    assert not (ledger.root/'claims/live/20261023/1800/dispatch.claim.json').exists()
    assert not (ledger.root/'workloads/live/20261023/1800/no_input_observer.workload-claim.json').exists()


@pytest.mark.parametrize('terminal',['SAFETY','UNKNOWN'])
def test_changed_wait_does_not_override_terminal_sibling(roots,tmp_path,terminal):
    from infrastructure.scheduling.dispatcher import dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    ledger=ExecutionLedger(tmp_path/'ledger');calls=[]
    def execute(workload,req,decision):
        calls.append(workload.workload_id)
        return {'status':'FAILED','failure_class':terminal if workload.workload_id=='hourly_research' else 'INVALID_INPUT',**FLAGS}
    first=dispatch_due(request(),catalog_for_partial_test(),execute,ledger=ledger)
    receipt=ledger.root/first.receipt_path;before=sha(receipt)
    pointer=roots.selector/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt';pointer.parent.mkdir();pointer.write_text(str(roots.selector/'new.parquet'))
    blocked=slot_blocks_retry(ledger.root,'20261023','1800',moment=datetime(2026,10,24,23,tzinfo=UTC),release_id='test-candidate',upstream_fingerprint='static-tree')
    # Exercise the actual due-to-dispatch caller boundary from the repro.
    if not blocked:dispatch_due(request(),catalog_for_partial_test(),execute,ledger=ledger)
    assert calls==['hourly_research','preselection_pools']
    assert blocked is True and sha(receipt)==before


def test_bad_research_cache_is_quarantined_through_publication(roots,monkeypatch):
    import inspect
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from ops import materialize_scheduled_preselection as cli
    readers,_=install_shared_fixture(roots,monkeypatch);hk=cached_hk(roots);store=PreselectionPoolStore(roots.data)
    store.materialize(fixture('a_share_research_recommendation_pool.json'))
    folder=roots.data/'preselection_pools/20261026';p=folder/'a_share_research_recommendation_pool.json'
    payload=json.loads(p.read_text());payload['rows'][0]['pool_score']=99;p.write_text(json.dumps(payload))
    protected=[p,folder/'manifest.json',folder/'receipts/a_share_research_recommendation_pool.json',folder/'hkconnect_d1_top100.json',folder/'receipts/hkconnect_d1_top100.json']
    before={p:sha(p) for p in protected}
    def forbidden(*a,**k):pytest.fail('quarantined research cache entered rebuild')
    monkeypatch.setattr(cli,'build_hourly_research_pool',forbidden)
    monkeypatch.setattr(cli,'load_baimao_preselection_pool',lambda *a,**k:cli._missing('20261026',pool_id='a_share_baimao_research_map',display_name='B',market='A',reason='MISSING'))
    def missing_a(*a,**k):raise FileNotFoundError('exact A input missing')
    kwargs=dict(trade_date='20261026',signal_date='20261023',selector=None,input_root=roots.input,data_root=roots.data,shared_data_root=roots.shared,shared_package_root=roots.package,pool_reader=missing_a,hk_pool_reader=readers['HK_CONNECT_D1_TOP100_0_2'])
    if 'reuse_formal_pools' in inspect.signature(cli.build_scheduled_artifacts).parameters:kwargs['reuse_formal_pools']={'hkconnect_d1_top100':hk}
    artifacts=cli.build_scheduled_artifacts(**kwargs)
    rejected=next(a for a in artifacts if a['pool_id']=='a_share_research_recommendation_pool')
    assert rejected['source_role']=='EXPECTED_MISSING' and not rejected['rows']
    assert any('preselection-pool manifest or receipt SHA mismatch' in reason for reason in rejected['cannot_confirm'])
    results=cli.publish_scheduled_artifacts(store,[a for a in artifacts if a['pool_id'] in {'a_share_research_recommendation_pool','hkconnect_d1_top100'}])
    assert next(r for r in results if r.get('pool_id')=='a_share_research_recommendation_pool')['status']=='DEFERRED'
    assert pool_gate(artifacts)['research_ready'] is True
    assert len(store.read_pool('20261026','hkconnect_d1_top100')['rows'])==100
    assert all(sha(p)==digest for p,digest in before.items())
    with pytest.raises(ValueError,match='SHA mismatch'):store.read_pool('20261026','a_share_research_recommendation_pool')
