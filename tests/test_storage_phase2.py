"""Changed-scope tiny fixtures; actual publication, Reader and monitor seams."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_storage_governance as g
from ops import research_storage_pair as pair
from ops import research_storage_retention as r
from ops import mac_storage_monitor as monitor


@pytest.fixture
def policy(tmp_path,monkeypatch):
    root=tmp_path/'outputs';root.mkdir()
    p=dict(data_root=str(tmp_path),run_root=str(root),formal_roots={},governance=dict(
        enabled=True,registry_root=str(tmp_path/'registry'),pool_id='tiny',pool_identity_verified=True,
        ordinary_peak_budget_bytes=200*g.GIB,product_output_roots=[str(root)]))
    monkeypatch.setattr(g.shutil,'disk_usage',lambda _:types.SimpleNamespace(free=400*g.GIB,total=1000*g.GIB))
    return p


def test_registry_reserves_terminal_space_and_measures_exact_persisted_bytes(policy,tmp_path):
    config=g.configuration(policy);config['max_registry_bytes']=400*1024
    registry=g.Registry(config,tmp_path)
    with registry.writer():
        claim=g.Claim(registry,'a',tmp_path/'outputs/a',1024*1024);claim.begin()
        assert registry.path.stat().st_size==len(registry.encoded(registry.read()))
        state=registry.read();state['tasks']['a']['state']='FAILED_RECOVERABLE';registry.save(state)
        with pytest.raises(r.RetentionError,match='REGISTRY_BUDGET'):
            g.Claim(registry,'b',tmp_path/'outputs/b',1024).begin()
        artifact=tmp_path/'outputs/a';artifact.write_bytes(b'valid')
        # A result near the allowed128KiB replaces reserved padding, not grows
        # the main registry beyond its limit; live task control stays operable.
        claim.finish(dict(result='a'*(120*1024)),[artifact])
        assert registry.read()['tasks']['a']['state']=='READY'
        assert registry.path.stat().st_size<config['max_registry_bytes']


def test_registry_failed_state_can_checkpoint_and_finish_near_cap(policy,tmp_path):
    config=g.configuration(policy);config['max_registry_bytes']=280*1024
    registry=g.Registry(config,tmp_path)
    with registry.writer():
        claim=g.Claim(registry,'a',tmp_path/'outputs/a',1024*1024);claim.begin()
        claim.checkpoint();claim.finish(error=RuntimeError('failed'*170))
        value=registry.read();assert value['tasks']['a']['state']=='FAILED_RECOVERABLE'
        assert registry.remaining(value['tasks']['a'])==1024*1024
        assert registry.path.stat().st_size<config['max_registry_bytes']


def test_category_logical_accounting_does_not_double_charge_allocated_difference(policy,tmp_path):
    config=g.configuration(policy);config['ordinary_peak_budget_bytes']=1000
    reg=g.Registry(config,tmp_path)
    state=dict(tasks={'a':dict(reserved_bytes=1000,written_bytes=100,logical_written_bytes=300,category='ordinary',state='RUNNING')})
    # System reserve spends allocated100; class reserve spends logical300.
    reg.space(state,'a',900,category='ordinary',optional_full=False,category_used=300,category_remaining_bytes=700)


def _report(moment):
    return dict(capacity=dict(observed_utc=moment.isoformat(),timestamp=moment.timestamp(),volume_path='/',total_bytes=100,
        available_bytes=50,threshold='HEALTHY',history_parse_errors=[]))


def _monitor_config(tmp_path,dry=False):
    root=tmp_path/'new_ordinary'
    return dict(audit_root=str(tmp_path),ordinary_retention=dict(root=str(root),approved_root=str(root),dry_run=dry,
        allow_future_owned_ordinary_rotation=True))


def test_monitor_fourteen_RUNS_not_days_ninety_day_lightweight_trend(tmp_path):
    cfg=_monitor_config(tmp_path);now=datetime(2026,11,8,tzinfo=timezone.utc)
    first=now-timedelta(days=91)
    monitor.ordinary_retention(cfg,_report(first),now=first)
    for n in range(16):result=monitor.ordinary_retention(cfg,_report(now+timedelta(seconds=n)),now=now+timedelta(seconds=n))
    root=Path(cfg['ordinary_retention']['root']);state=json.loads((root/'index.json').read_text())
    assert len(state['reports'])==14 and result['detailed_keep_runs']==14
    rows,errors=monitor.load_history(root/'trend.jsonl');assert not errors and len(rows)==16
    assert result['trend_keep_days']==90


def test_monitor_dryrun_protected_critical_legacy_and_unowned_boundaries(tmp_path):
    old=tmp_path/'old_evidence';old.write_bytes(b'protected')
    cfg=_monitor_config(tmp_path,dry=True);now=datetime.now(timezone.utc)
    for n in range(16):result=monitor.ordinary_retention(cfg,_report(now+timedelta(seconds=n)),now=now+timedelta(seconds=n))
    assert result['dry_run'] and result['deleted_bytes']==0 and result['decisions']
    root=Path(cfg['ordinary_retention']['root']);state=json.loads((root/'index.json').read_text())
    protected=state['reports'][0]['name'];cfg['ordinary_retention']['protected_report_ids']=[protected];cfg['ordinary_retention']['dry_run']=False
    critical=_report(now);critical['critical_evidence']=True
    monitor.ordinary_retention(cfg,critical,now=now+timedelta(seconds=17))
    assert (root/protected).exists() and old.read_bytes()==b'protected'
    foreign=tmp_path/'foreign';foreign.mkdir();(foreign/'old.json').write_text('old')
    cfg['ordinary_retention'].update(root=str(foreign),approved_root=str(foreign))
    with pytest.raises(ValueError,match='PREEXISTS_UNOWNED'):monitor.ordinary_retention(cfg,_report(now),now=now)


def test_monitor_identity_failure_is_recorded_no_delete(tmp_path):
    cfg=_monitor_config(tmp_path,dry=True);now=datetime.now(timezone.utc)
    for n in range(15):monitor.ordinary_retention(cfg,_report(now),now=now+timedelta(seconds=n))
    root=Path(cfg['ordinary_retention']['root']);state=json.loads((root/'index.json').read_text());name=state['reports'][0]['name']
    (root/name).write_text('changed');cfg['ordinary_retention']['dry_run']=False
    result=monitor.ordinary_retention(cfg,_report(now),now=now+timedelta(seconds=16))
    assert any(row['name']==name and row['status']=='BLOCKED' for row in result['decisions'])
    assert (root/name).read_text()=='changed'
    assert any(row.get('rotation_error') for row in json.loads((root/'index.json').read_text())['reports'])


def make_version(data,number):
    root=data/('version'+str(number));root.mkdir();receipt=root/'candidate_receipt.json'
    contract=dict(schema='a_share_qfq_panel_v1',generation_id=str(number)*64,input_sha256='input'+str(number),snapshot_file_sha256='snapshot'+str(number),
        adjustment_snapshot=dict(path='immutable_snapshot'+str(number),sha256='snapshot'+str(number)),asof_date=20261108,price_basis='QFQ_ASOF',volume_basis='RAW',convention='unchanged',generation_manifest_path=str(receipt))
    paths={role:root/(role+'.parquet') for role in ('selector','backtest')}
    table=pa.table(dict(ts_code=['000001.SZ'],trade_date=['20261108'],close=[float(number)])).replace_schema_metadata({pair.META:json.dumps(contract).encode()})
    for path in paths.values():pq.write_table(table,path)
    r.atomic_json(receipt,dict(generation_id=contract['generation_id'],input_sha256=contract['input_sha256'],candidates={role:str(path) for role,path in paths.items()},candidate_sha256={role:r.digest(path) for role,path in paths.items()}))
    return paths


@pytest.fixture
def versions(tmp_path,monkeypatch):
    data=tmp_path/'data';data.mkdir();root=tmp_path/'pairs'
    monkeypatch.setenv('V4_STORAGE_PAIR_ROOT',str(root));monkeypatch.setenv('V4_STORAGE_PAIR_DATA_ROOT',str(data))
    paths=make_version(data,1)
    for role,pointer in pair.pointers(data).items():pointer.parent.mkdir(parents=True);pointer.write_text(str(paths[role])+'\n')
    journal=data/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json';r.atomic_json(journal,dict(status='COMMITTED'))
    pair.seed_configured()
    return data,root,[paths,make_version(data,2),make_version(data,3)]


def actual_publish(data,root,paths,monkeypatch=None):
    from ops import research_panel_qfq as q
    policy=dict(data_root=str(data),run_root=str(data),formal_roots={},governance=dict(enabled=True,
        registry_root=str(root/'registry'),pool_id='tiny',pool_identity_verified=True,ordinary_peak_budget_bytes=200*g.GIB))
    pointers=pair.pointers(data);expected={role:p.read_bytes() for role,p in pointers.items()}
    journal=data/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json'
    with q.publication_lock(data):
        with g.admission(policy,key=paths['selector'].parent.name,directory=paths['selector'].parent,predicted=128*g.MIB) as (claim,_):
            with g.qfq_write_seams(q,claim):q.publish_pair(pointers,paths,expected,journal)
            claim.finish(dict(status='READY'),list(paths.values()))


def test_three_actual_publications_long_read_lease_rotation_and_released_use(versions):
    data,root,paths=versions
    with pair.request_binding(data) as old:
        first=old.manifest['id'];actual_publish(data,root,paths[1]);actual_publish(data,root,paths[2])
        assert pq.read_table(old.paths['selector']).to_pylist()[0]['close']==1
        with pytest.raises(r.RetentionError,match='EFFECTIVE_READER_LEASE'):
            with pair.retire_candidate(root,first):pass
        with pair.acquire(root) as new:assert new.manifest['identity']['generation_id']=='3'*64
    with pytest.raises(r.RetentionError,match='LEASE_RELEASED'):old.pointer_bytes('selector')
    with pair.retire_candidate(root,first):pass
    state=r.read_json(root/'current.json')
    for ref in [state['current'],state['rollback']]:
        with pytest.raises(r.RetentionError,match='CURRENT_OR_ROLLBACK'):
            with pair.retire_candidate(root,ref['id']):pass


def test_actual_publish_fault_between_pair_replaces_keeps_manifest_and_restores_pair(versions,monkeypatch):
    from ops import research_panel_qfq as q
    data,root,paths=versions;before=(root/'current.json').read_bytes();original=q._write
    def fail(path,payload):
        if path==pair.pointers(data)['backtest'] and payload== (str(paths[1]['backtest'])+'\n').encode():raise OSError('injected second replacement')
        return original(path,payload)
    monkeypatch.setattr(q,'_write',fail)
    with pytest.raises(OSError):actual_publish(data,root,paths[1])
    assert (root/'current.json').read_bytes()==before
    assert all(p.read_text().strip()==str(paths[0][role]) for role,p in pair.pointers(data).items())


def test_crash_after_original_commit_before_manifest_reconciles_idempotently(versions):
    from ops import research_panel_qfq as q
    data,root,paths=versions;old=(root/'current.json').read_bytes();pointers=pair.pointers(data)
    with q.publication_lock(data):q.publish_pair(pointers,paths[1],{r:p.read_bytes() for r,p in pointers.items()},data/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json')
    assert (root/'current.json').read_bytes()==old
    with pair.acquire(root) as binding:assert binding.paths==paths[0]
    pair.seed_configured();once=(root/'current.json').read_bytes();pair.seed_configured();assert (root/'current.json').read_bytes()==once
    with pair.acquire(root) as binding:assert binding.paths==paths[1]


def test_actual_crossprocess_live_sleep_crash_lease_no_timeout_or_pid_guess(versions):
    data,root,paths=versions
    child='''import sys,time\nfrom pathlib import Path\nfrom ops import research_storage_pair as p\nwith p.acquire(Path(sys.argv[1])) as b:\n print(b.manifest['id'],flush=True)\n time.sleep(120)\n'''
    process=subprocess.Popen([sys.executable,'-u','-c',child,str(root)],stdout=subprocess.PIPE,text=True)
    try:
        first=process.stdout.readline().strip();assert len(first)==64
        actual_publish(data,root,paths[1]);actual_publish(data,root,paths[2])
        with pytest.raises(r.RetentionError,match='EFFECTIVE_READER_LEASE'):
            with pair.retire_candidate(root,first):pass
        process.kill();process.wait(timeout=5) # only our disposable fixture child
        with pair.retire_candidate(root,first):pass
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)
        process.stdout.close()


def test_pair_exception_and_lazy_lifetime_contract(versions):
    data,root,paths=versions
    with pytest.raises(RuntimeError):
        with pair.request_binding(data) as b:raise RuntimeError('Reader error')
    assert b.closed
    @pair.paired_request
    def lazy(shared_data_root):return iter([1])
    with pytest.raises(r.RetentionError,match='LAZY_RETURN'):lazy(data)
    assert pair.current_binding() is None


def test_actual_imported_helper_write_is_guarded_and_foreign_call_passes(policy,tmp_path):
    from ops import research_panel_tdx_adjustment_inputs as helper
    with g.admission(policy,key='helper',directory=tmp_path/'outputs/helper',predicted=1024*1024) as (claim,_):
        with g.input_write_seams(claim):
            claim.paused=True
            path=tmp_path/'not_written'
            with pytest.raises(g.SpaceBlocked):helper._save_bytes(path,b'tiny')
            assert not path.exists()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:executor.submit(helper._save_bytes,tmp_path/'foreign',b'untouched').result()
            assert (tmp_path/'foreign').read_bytes()==b'untouched'


def test_actual_raw_sync_entry_blocks_before_loading_or_download(monkeypatch,tmp_path):
    import ops
    active='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-storage-governance-20261108-r2/v4-storage-governance-20261108-r2-main/app/ops'
    monkeypatch.setattr(ops,'__path__',[*ops.__path__,active])
    from ops import macos_research_panel_daily_authority as owner
    @contextmanager
    def blocked(**kwargs):raise g.SpaceBlocked('input blocked');yield
    monkeypatch.setattr(g,'input_preflight',blocked)
    monkeypatch.setattr(owner,'_load_authority_module',lambda *a:pytest.fail('source invoked before admission'))
    with pytest.raises(g.SpaceBlocked,match='input blocked'):
        owner.run_windows_a_sync_authority('not-loaded',tmp_path,'20261108',tmp_path)


def test_same_actual_shared_reader_reads_immutable_path_during_publish(versions):
    import importlib.util
    data,root,paths=versions
    source=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/data_layer_interface_current/DATA_LAYER_INTERFACE.py')
    # Original Reader demands producer basis fields. Extend only tiny fixture
    # manifest/metadata (never actual source files or production panels).
    for version in paths:
        receipt=version['selector'].parent/'candidate_receipt.json';value=json.loads(receipt.read_text())
        schema=pq.read_schema(version['selector']);contract=json.loads(schema.metadata[pair.META])
        for key in ('schema','snapshot_file_sha256','asof_date','price_basis','volume_basis','convention'):
            value[key]=contract[key]
        value['field_basis']={};r.atomic_json(receipt,value)
    # Identity includes receipt SHA, so seed a new fixture manifest consistently.
    pair.seed_configured()
    with pair.request_binding(data) as binding:
        spec=importlib.util.spec_from_file_location('actual_immutable_shared_reader_fixture',source)
        reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
        pair.bind_shared_reader(reader,binding)
        journal=data/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json'
        # Simulate the real owner's first pointer replacement/PREPARED gap;
        # bound Reader must not resolve new CURRENT/backtest a second time.
        pair.pointers(data)['selector'].write_text(str(paths[1]['selector'])+'\n')
        r.atomic_json(journal,dict(status='PREPARED'))
        frame=reader.load_selector_ready(columns=['ts_code','trade_date','close'],panel_path=binding.paths['selector'],profile=None)
        assert frame.close.tolist()==[1.] and frame.attrs['panel_metadata']['generation_id']=='1'*64
        binding.assert_open()


def test_actual_api_history_lock_and_name_fallback_bind_once(versions,monkeypatch):
    from apps.api.v4_api import a_share_panel_history as history
    import importlib
    active=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-workbench-source-close-quote-20261105-r1/v4-workbench-source-close-quote-20261105-r1-api/app')
    for name in ('contracts','domains','infrastructure','upstreams'):
        package=importlib.import_module(name)
        monkeypatch.setattr(package,'__path__',[*package.__path__,str(active/name)])
    from apps.api.v4_api import preselection_service as names
    data,root,paths=versions
    monkeypatch.setenv('V4_A_SHARE_HISTORY_DATA_ROOT',str(data))
    monkeypatch.setattr(history,'_profile_direct_qfq',lambda *a,**k:None)
    # Formula conflict remains the existing business outcome; real entry uses
    # bound pair without trying to re-enter the held publisher lock.
    from ops import research_panel_qfq as q
    with q.publication_lock(data):
        answer=history.read_history(data,'000001.SZ','20261108','20261108',history.VERSION)
        assert answer['status']=='CANNOT_CONFIRM'
        assert 'PUBLICATION_IN_PROGRESS' not in answer['cannot_confirm']
        assert names._load_a_name_map('20261108')==('',{})
    assert pair.current_binding() is None


def test_actual_tdx_fallback_serializer_is_guarded_without_algorithm_change(policy,tmp_path,monkeypatch):
    import pandas as pd
    from ops import research_panel_tdx_adjustment_inputs as tdx
    root=tmp_path/'metadata';root.mkdir();(root/'official_gbbq').mkdir();raw=root/'raw.gbbq';raw.write_bytes((1).to_bytes(4,'little')+b'0'*29)
    policy_file=root/'category.json';r.atomic_json(policy_file,dict(policy_id='TDX_GBBQ_CATEGORY1_AFFINE_BJ_V1',controller='fixture',category_policy={'1':'PRICE_ACTION_PER10_CASH_RIGHTS_BONUS_AFFINE'}))
    ref=dict(path=str(policy_file),sha256=r.digest(policy_file));r.atomic_json(root/'qfq_tdx_official_source.json',dict(category_policy_receipt=ref))
    captured=dict(raw=dict(path=str(raw),sha256=r.digest(raw)),archive=dict(path=str(raw),sha256=r.digest(raw)),parser=dict(path=str(raw),sha256=r.digest(raw)),observed_at='2026-11-08T00:00:00+00:00')
    monkeypatch.setattr(tdx,'official_snapshot',lambda *a,**k:(raw,captured))
    class Parser:
        def get_df(self,path):
            return pd.DataFrame([dict(code='430047',market=2,datetime=20261101,category=1,
                hongli_panqianliutong=1.,peigujia_qianzongguben=0.,songgu_qianzongguben=0.,peigu_houzongguben=0.)])
    with g.admission(policy,key='tdx_fallback',directory=tmp_path/'outputs/fallback',predicted=1024*1024) as (claim,_):
        with g.input_write_seams(claim):
            claim.paused=True
            with pytest.raises(g.SpaceBlocked):tdx.build_fallback(root,{'430047.BJ':dict(history_start_date=20260101)},20261108,parser_factory=Parser)
            assert not list(root.rglob('*.parquet')) and not list(root.rglob('*.pending'))
            claim.paused=False
            result=tdx.build_fallback(root,{'430047.BJ':dict(history_start_date=20260101)},20261108,parser_factory=Parser)
            assert result['symbols']['430047.BJ']['events']==[dict(ex_date=20261101,a=1.,b=-.1,volume_a=1.)]
            assert list(root.rglob('*.parquet'))


def test_monitor_weekly_cannot_trigger_legacy_deep_inventory(tmp_path,monkeypatch):
    # Same public run entry, with an old-style configured weekly path. No
    # collector module, inventory tree, or recursive scan is invoked.
    monkeypatch.setattr(monitor,'BASE',tmp_path/'08_MONITORING')
    source=tmp_path/'business';source.mkdir();(source/'data').write_bytes(b'preserve')
    cfg=dict(audit_root=str(tmp_path),history_dir=str(tmp_path/'history'),volume_path=str(tmp_path),inventory_paths={'weekly':[str(source)]})
    result=monitor.run(cfg,'weekly')
    assert result['directory_growth_status'].startswith('SUPPRESSED_DEEP_INVENTORY')
    assert not (tmp_path/'history/inventories').exists() and (source/'data').read_bytes()==b'preserve'


def test_control_allowance_is_inside_original_reservation_before_commit(policy,tmp_path):
    from ops import research_panel_qfq as q
    # A task with only32MiB has no permission to start the64MiB control phase,
    # even with abundant current filesystem free space.
    with g.admission(policy,key='control',directory=tmp_path/'outputs/control',predicted=32*g.MIB) as (claim,_):
        with g.qfq_write_seams(q,claim):
            with pytest.raises(g.SpaceBlocked,match='PREDICTED_PEAK_EXCEEDED'):
                q.publish_pair({}, {}, {}, tmp_path/'journal')
            assert not (tmp_path/'journal').exists()
    with g.admission(policy,key='control_good',directory=tmp_path/'outputs/good',predicted=128*g.MIB) as (claim,_):
        pointers={role:tmp_path/(role+'.txt') for role in ('selector','backtest')}
        for p in pointers.values():p.write_text('old\n')
        with g.qfq_write_seams(q,claim):
            q.publish_pair(pointers,{r:tmp_path/(r+'.new') for r in pointers},{r:b'old\n' for r in pointers},tmp_path/'journal')
            assert claim.publication_control_reserved_bytes==64*g.MIB
            assert claim.control_written<64*g.MIB


def test_initial_seed_binds_exact_baseline_rollback_once(versions,monkeypatch):
    data,root,paths=versions;receipt=paths[2]['selector'].parent/'candidate_receipt.json'
    value=r.read_json(receipt);value['baseline_panel_sha256']={role:r.digest(path) for role,path in paths[1].items()};r.atomic_json(receipt,value)
    for role,pointer in pair.pointers(data).items():pointer.write_text(str(paths[2][role])+'\n')
    newroot=root.parent/'fresh_pair_seed';monkeypatch.setenv('V4_STORAGE_PAIR_ROOT',str(newroot))
    with pytest.raises(r.RetentionError,match='NOT_EXACT_BASELINE'):pair.seed_configured(rollback_paths=paths[0])
    assert not (newroot/'current.json').exists()
    pair.seed_configured(rollback_paths=paths[1]);state=r.read_json(newroot/'current.json')
    assert r.read_json(Path(state['current']['path']))['roles']['selector']['path']==str(paths[2]['selector'])
    assert r.read_json(Path(state['rollback']['path']))['roles']['selector']['path']==str(paths[1]['selector'])
    before=(newroot/'current.json').read_bytes();pair.seed_configured();assert (newroot/'current.json').read_bytes()==before


def test_actual_publisher_process_crash_in_prepared_gap_recovers_original_pair(versions):
    from ops import research_panel_qfq as q
    data,root,paths=versions;before=(root/'current.json').read_bytes()
    code='''import os,sys,runpy\nfrom pathlib import Path\nfrom ops import research_panel_qfq as q\nfrom ops import research_storage_pair as p\ndata,root,version=map(Path,sys.argv[1:]);original=q._write\ndef crash(path,payload):\n original(path,payload)\n if path==p.pointers(data)['selector']:os._exit(71)\nq._write=crash\nm=runpy.run_path('tests/test_storage_phase2.py')\nm['actual_publish'](data,root,{r:version/(r+'.parquet') for r in ('selector','backtest')})\n'''
    process=subprocess.run([sys.executable,'-c',code,str(data),str(root),str(paths[1]['selector'].parent)],timeout=10,capture_output=True,text=True)
    assert process.returncode==71,process.stderr
    assert (root/'current.json').read_bytes()==before
    with pair.acquire(root) as binding:assert pq.read_table(binding.paths['selector']).column('close').to_pylist()==[1.]
    with q.publication_lock(data):q.recover_pair(data/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json',pair.pointers(data))
    assert all(pointer.read_text().strip()==str(paths[0][role]) for role,pointer in pair.pointers(data).items())
    assert (root/'current.json').read_bytes()==before


def test_refreshing_invocation_key_survives_its_own_snapshot_update(tmp_path):
    snapshot=tmp_path/'snapshot.json';snapshot.write_text('{"asof":20261105}')
    dependency=tmp_path/'dependency.py';dependency.write_text('# fixed numerical dependency\n')
    module=types.SimpleNamespace(__file__=str(dependency),input_path=lambda root:snapshot)
    kwargs=dict(driver_path=dependency,formula_path=dependency,contract_csv=dependency,refresh_inputs=True,publish=True)
    before=g.qfq_invocation_key(module,tmp_path,20261106,kwargs)
    snapshot.write_text('{"asof":20261106,"owner_refreshed":true}')
    assert g.qfq_invocation_key(module,tmp_path,20261106,kwargs)==before
    assert g.qfq_invocation_key(module,tmp_path,20261109,kwargs)!=before
    # Explicit offline immutable-snapshot calls must retain exact SHA identity.
    kwargs['refresh_inputs']=False
    first=g.qfq_invocation_key(module,tmp_path,20261106,kwargs)
    snapshot.write_text('{"asof":20261106,"revision":2}')
    assert g.qfq_invocation_key(module,tmp_path,20261106,kwargs)!=first


def test_failed_refresh_retries_one_original_registry_row(policy,tmp_path):
    snapshot=tmp_path/'snapshot.json';snapshot.write_text('old target snapshot')
    dependency=tmp_path/'dependency.py';dependency.write_text('fixed owner')
    module=types.SimpleNamespace(__file__=str(dependency),input_path=lambda root:snapshot)
    kwargs=dict(driver_path=dependency,formula_path=dependency,contract_csv=dependency,refresh_inputs=True)
    def key():return g.qfq_invocation_key(module,tmp_path,20261109,kwargs)
    original=key();directory=Path(policy['run_root'])/'original'
    with pytest.raises(RuntimeError):
        with g.admission(policy,key=original,directory=directory,predicted=g.MIB):
            snapshot.write_text('new target snapshot persisted before failure')
            raise RuntimeError('owner failed after refresh')
    with g.admission(policy,key=key(),directory=directory,predicted=g.MIB) as (claim,_):
        state=claim.registry.read();assert list(state['tasks'])==[original]
        assert state['tasks'][original]['attempts']==2 and state['tasks'][original]['resumed']
        claim.finish(error=RuntimeError('fixture ended; no producer'))


def test_monitor_cap_accounts_entire_atomic_index_maintenance_peak(tmp_path,monkeypatch):
    cfg=_monitor_config(tmp_path);cfg['ordinary_retention']['max_bytes']=1024*1024
    now=datetime.now(timezone.utc);report=_report(now);report['critical_evidence']=True
    monitor.ordinary_retention(cfg,report,now=now)
    root=Path(cfg['ordinary_retention']['root']);state=json.loads((root/'index.json').read_text());template=state['reports'][0]
    payload=(root/template['name']).read_bytes();state['reports']=[]
    for n in range(700):
        name=f'protected_fixture_{n:05}.json';(root/name).write_bytes(payload)
        state['reports'].append({**template,'name':name,'critical':True})
    monitor.save_json(root/'index.json',state)
    cap=cfg['ordinary_retention']['max_bytes'];used=sum(p.stat().st_size for p in root.iterdir() if p.is_file())
    # The prior128KiB guess would admit while the actual index is larger.
    (root/'unknown_preserved_evidence').write_bytes(b'X'*(cap-150*1024-used))
    before={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
    result=monitor.ordinary_retention(cfg,report,now=now)
    assert result['status'].startswith('SUPPRESSED_OWN_BUDGET')
    assert result['maintenance_peak_bytes']>cap
    assert {p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}==before


@pytest.mark.parametrize('reconcile_failure',[False,True])
def test_real_ready_reuse_reconciles_original_committed_pair_gap(versions,monkeypatch,reconcile_failure):
    from ops import research_panel_qfq as q
    data,root,paths=versions;pointers=pair.pointers(data)
    journal=data/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json'
    # Original owner committedV2, followed by process/control failure before
    # atomic paired metadata commit. Cooperating Readers still safely seeV1.
    with q.publication_lock(data):q.publish_pair(pointers,paths[1],{r:p.read_bytes() for r,p in pointers.items()},journal)
    with pair.acquire(root) as binding:assert binding.paths==paths[0]
    runs=data/'runs';run=runs/('qfq_'+'2'*20);run.mkdir(parents=True)
    status=dict(status='READY',generation_id='2'*64,run_dir=str(run),selector_pointer_ready=True,backtest_pointer_ready=True,
        **r.FLAGS,candidates={role:str(p) for role,p in paths[1].items()},candidate_sha256={role:r.digest(p) for role,p in paths[1].items()})
    r.atomic_json(run/'stage_status.json',status);r.atomic_json(run/'candidate_receipt.json',status)
    pins=data/'pins.json';r.atomic_json(pins,dict(expected_main_app_root=str(Path(g.__file__).resolve().parents[1])))
    policy=dict(data_root=str(data),run_root=str(runs),formal_roots={role:str(data) for role in pointers},
        pointers={role:str(p) for role,p in pointers.items()},managed_pin_inventory=dict(path=str(pins),sha256=r.digest(pins)),
        governance=dict(enabled=True,registry_root=str(root/'registry'),pool_id='tiny',pool_identity_verified=True))
    policy_file=data/'policy.json';r.atomic_json(policy_file,policy)
    monkeypatch.setenv('V4_RESEARCH_RETENTION_POLICY',str(policy_file));monkeypatch.setenv('V4_RESEARCH_RETENTION_POLICY_SHA256',r.digest(policy_file))
    monkeypatch.setattr(r,'load_policy',lambda *a,**k:policy) # isolate already-reviewed load-policy binding gates
    monkeypatch.setattr(q,'load_snapshot',lambda *a:{})
    monkeypatch.setattr(q,'generation_identity',lambda *a:dict(input_sha256='input2'))
    original_contract=q.panel_contract
    monkeypatch.setattr(q,'panel_contract',lambda p:{**original_contract(p),'turnover_input_sha256':'fixtureturnover'})
    turnover=types.ModuleType('ops.research_panel_turnover');turnover.load_daily=lambda *a:types.SimpleNamespace(identity='fixtureturnover')
    monkeypatch.setitem(sys.modules,'ops.research_panel_turnover',turnover)
    if reconcile_failure:
        monkeypatch.setattr(pair,'publish_configured',lambda *a:(_ for _ in ()).throw(OSError('pair control unavailable')))
    def forbidden(**kwargs):pytest.fail('READY reuse must not invoke producer')
    def invoke():return r.run_with_retention(forbidden,data_root=data,return_root=runs,pointers=pointers,target=20261108,ready_check=lambda:True,
        driver_path=data/'driver',formula_path=data/'formula',contract_csv=data/'contract',tdx_root=data)
    if reconcile_failure:
        with pytest.raises(OSError,match='pair control unavailable'):invoke()
        with pair.acquire(root) as binding:assert binding.paths==paths[0]
    else:
        answer=invoke();assert answer['already_current']
        assert answer['storage_pair']['status']=='VERIFIED_REUSE_PAIR_RECONCILED'
        with pair.acquire(root) as binding:assert binding.paths==paths[1]
        assert not (root/'registry').exists() # safe metadata reuse needs no disk/task admission
