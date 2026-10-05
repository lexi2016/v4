from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

from tests.r3_scoped_loader import install as _install_scoped
_install_scoped()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_materializer_canary_identity_supports_isolated_replay_kind():
    from v4.manager_research.activation_canary import write_canary_sandbox_identity, claim_canary_sandbox_identity

    app = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='manager-materializer-replay-canary-') as temp:
        sandbox = Path(temp).resolve()
        state = sandbox / 'state'; state.mkdir()
        identities = sandbox / 'identities'; identities.mkdir()
        receipts = sandbox / 'receipts'; receipts.mkdir()
        identity = identities / 'materializer.json'
        receipt = receipts / 'materializer.json'
        replay_spec = sandbox / 'replay-spec.json'; replay_spec.write_text('{}')
        args = [
            '--state-root', str(state), '--trade-date', '20260925',
            '--replay-spec', str(replay_spec),
            '--sandbox-identity', str(identity), '--receipt', str(receipt),
        ]
        doc = write_canary_sandbox_identity(
            identity, 'materializer', data_root=state, receipt_path=receipt,
            app_root=app, argv=args,
        )
        claimed = claim_canary_sandbox_identity(
            identity, 'materializer', data_root=state, receipt_path=receipt,
            app_root=app, argv=args,
        )
        assert doc['kind'] == 'materializer'
        assert claimed['status'] == 'VERIFIED'
        assert claimed['kind'] == 'materializer'


def test_recovery_gate_accepts_verified_running_to_partial_owner_attempt_witness():
    from v4.manager_research.activation_canary import evaluate_recovery

    witness = {
        'schema_version': 'v4.manager_research.announcement_recovery_witness.v1',
        'target_trade_date': '20260925',
        'interrupted': {'run_id': 'a' * 32, 'state': 'RUNNING'},
        'recovered': {'run_id': 'b' * 32, 'state': 'PARTIAL'},
    }
    row = evaluate_recovery(
        interruption_observed=True,
        pre_interrupt_change_observed=True,
        announcement_returncode=0,
        materializer_returncode=0,
        recovery_paths={
            'workspace_announcement_runs/20260925/latest.json',
            'workbench_research/20260925/1530.json',
        },
        allowed_paths={
            'workspace_announcement_runs/20260925/latest.json',
            'workbench_research/20260925/1530.json',
        },
        owner_transaction_state=witness,
    )
    assert row['status'] == 'PASS'
    assert row['gaps'] == []


def test_shared_root_command_accepts_only_offline_replay_materializer(tmp_path):
    from ops.run_manager_state_compatibility_canary import _command

    app = Path(__file__).resolve().parents[1]
    source = tmp_path / 'source'; source.mkdir()
    replay_spec = tmp_path / 'replay.json'; replay_spec.write_text('{}')
    command = json.dumps([
        str(Path(sys.executable).resolve()), '-B', '-m', 'ops.run_manager_materializer_offline_replay',
        '--state-root', '{state_root}', '--trade-date', '20260925',
        '--replay-spec', str(replay_spec), '--replay-spec-sha256', _sha(replay_spec), '--sandbox-identity', '{sandbox_identity}', '--receipt', '{receipt}',
    ])
    rendered, identity = _command(command, tmp_path / 'sandbox', source, app, 'materializer')
    assert identity['entrypoint_name'] == 'ops.run_manager_materializer_offline_replay'
    assert identity['replay_spec_sha256'] == _sha(replay_spec)
    assert rendered[rendered.index('--state-root') + 1] == str(tmp_path / 'sandbox')

    live = json.dumps([
        str(Path(sys.executable).resolve()), '-B', '-m', 'ops.materialize_manager_close_discovery',
        '--state-root', '{state_root}', '--trade-date', '20260925',
    ])
    with pytest.raises(ValueError, match='CANARY_MATERIALIZER_OFFLINE_REPLAY_REQUIRED'):
        _command(live, tmp_path / 'sandbox', source, app, 'materializer')


def test_replay_seed_builder_copies_only_existing_1530_inputs(tmp_path):
    from v4.manager_research.materializer_replay import build_replay_seed

    source = tmp_path / 'source'
    inputs = source / 'workbench_research/20260925/inputs'; inputs.mkdir(parents=True)
    snapshot = inputs / '1530_futu_snapshot.json'
    snapshot_receipt = inputs / '1530_futu_snapshot.json.receipt.json'
    history = inputs / '1530_rebound_history.json'
    snapshot.write_text(json.dumps({'trade_date':'20260925','started_at':'2026-09-25T15:30:10+08:00','available_at':'2026-09-25T15:30:20+08:00'}))
    snapshot_receipt.write_text('{}')
    history.write_text(json.dumps({'trade_date':'20260925','source_files':[]}))
    published = source / 'workbench_research/20260925/1530.json'; published.write_text('published')
    destination = tmp_path / 'seed'

    receipt = build_replay_seed(source, destination, '20260925')
    assert receipt['status'] == 'READY'
    assert (destination / snapshot.relative_to(source)).is_file()
    assert (destination / snapshot_receipt.relative_to(source)).is_file()
    assert (destination / history.relative_to(source)).is_file()
    assert not (destination / published.relative_to(source)).exists()


def _seed_origin_bundle_fixture(tmp_path, app):
    from v4.manager_research.materializer_replay import build_replay_seed

    date='20260924'
    origin,data,universe,news_owner,universe_owner,rebound,spec=_replay_identity_fixture(tmp_path,app)
    # A natural source may already have its published result. The replay seed
    # is deliberately built from only the three immutable input witnesses.
    published=origin/f'workbench_research/{date}/1530.json'
    published.write_text('{"historical_result":true}')
    replay=tmp_path/'replay'; replay.mkdir()
    seed=replay/'state_seed'
    seed_receipt=build_replay_seed(origin,seed,date)
    spec_path=replay/'replay-spec.json'
    spec_path.write_text(json.dumps(spec,sort_keys=True))
    spec_sha=_sha(spec_path)
    bundle_path=replay/'replay-bundle.json'
    bundle_path.write_text(json.dumps({
        'schema_version':'v4.manager_close_offline_replay_bundle.v1','status':'READY',
        'seed':seed_receipt,'replay_spec':str(spec_path),'replay_spec_sha256':spec_sha,
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
    },sort_keys=True))
    return origin,seed,bundle_path,spec_path,spec_sha,date


def test_replay_origin_bundle_binds_real_manager_root_to_exact_three_file_seed(tmp_path):
    from v4.manager_research.materializer_replay import validate_replay_origin_bundle

    app=Path(__file__).resolve().parents[1]
    origin,seed,bundle,spec,spec_sha,date=_seed_origin_bundle_fixture(tmp_path,app)
    verified=validate_replay_origin_bundle(bundle,expected_seed_root=seed,
        expected_trade_date=date,expected_replay_spec_path=spec,
        expected_replay_spec_sha256=spec_sha,expected_source_state_root=origin)
    expected={
        f'workbench_research/{date}/inputs/1530_futu_snapshot.json',
        f'workbench_research/{date}/inputs/1530_futu_snapshot.json.receipt.json',
        f'workbench_research/{date}/inputs/1530_rebound_history.json',
    }
    assert verified['source_state_root']==str(origin)
    assert verified['replay_seed_root']==str(seed)
    assert set(verified['copied_inputs'])==expected
    assert verified['seed_manifest_before']==verified['copied_inputs']
    assert not any(path.endswith('/1530.json') or path.endswith('/1530.receipt.json')
        for path in verified['seed_manifest_before'])


@pytest.mark.parametrize('case',[
    'wrong-bound-origin','wrong-seed-root','wrong-date','missing-input','extra-input',
    'bad-origin-sha','changed-origin','changed-seed','extra-seed-file','published-seed-output','seed-symlink',
])
def test_replay_origin_bundle_rejects_root_date_mapping_or_seed_drift(tmp_path,case):
    from v4.manager_research.materializer_replay import validate_replay_origin_bundle

    app=Path(__file__).resolve().parents[1]
    origin,seed,bundle,spec,spec_sha,date=_seed_origin_bundle_fixture(tmp_path,app)
    payload=json.loads(bundle.read_text())
    inputs=payload['seed']['copied_inputs']
    if case=='wrong-bound-origin':
        other=tmp_path/'other'; other.mkdir()
        expected_source=other
    else:
        expected_source=origin
    if case=='missing-input':
        inputs.pop(next(iter(inputs)))
    elif case=='extra-input':
        inputs['workbench_research/20260924/inputs/extra.json']='a'*64
    elif case=='bad-origin-sha':
        inputs[next(iter(inputs))]='not-a-sha'
    elif case=='changed-origin':
        path=origin/next(iter(inputs)); path.write_bytes(path.read_bytes()+b'changed')
    elif case=='changed-seed':
        path=seed/next(iter(inputs)); path.write_bytes(path.read_bytes()+b'changed')
    elif case=='extra-seed-file':
        (seed/'unexpected.json').write_text('{}')
    elif case=='published-seed-output':
        (seed/f'workbench_research/{date}/1530.json').write_text('{}')
    elif case=='seed-symlink':
        (seed/'escape.json').symlink_to(tmp_path/'outside.json')
    bundle.write_text(json.dumps(payload,sort_keys=True))
    expected_seed=tmp_path/'other-seed' if case=='wrong-seed-root' else seed
    expected_date='20260925' if case=='wrong-date' else date
    with pytest.raises(ValueError):
        validate_replay_origin_bundle(bundle,expected_seed_root=expected_seed,
            expected_trade_date=expected_date,expected_replay_spec_path=spec,
            expected_replay_spec_sha256=spec_sha,expected_source_state_root=expected_source)


def test_offline_replay_runner_blocks_snapshot_fetch_and_external_processes_on_invalid_universe(tmp_path):
    from v4.manager_research.materializer_replay import execute_offline_replay

    app = Path(__file__).resolve().parents[1]
    materializer = app / 'ops/materialize_manager_close_discovery.py'
    state = tmp_path / 'state'
    inputs = state / 'workbench_research/20260925/inputs'; inputs.mkdir(parents=True)
    (inputs / '1530_futu_snapshot.json').write_text(json.dumps({
        'trade_date':'20260925','started_at':'2026-09-25T15:30:10+08:00','available_at':'2026-09-25T15:30:20+08:00'
    }))
    (inputs / '1530_futu_snapshot.json.receipt.json').write_text('{}')
    (inputs / '1530_rebound_history.json').write_text(json.dumps({'trade_date':'20260925','source_files':[]}))
    data = tmp_path / 'data'; data.mkdir()
    universe = tmp_path / 'universe'; universe.mkdir()
    news = tmp_path / 'news'; (news / 'ops').mkdir(parents=True); (news / 'ops/collect_hourly_research_input.py').write_text('# fixture')
    rebound = tmp_path / 'rebound'; (rebound / 'assets/hk_0_2').mkdir(parents=True); (rebound / 'assets/hk_security_master').mkdir(parents=True)
    (rebound / 'assets/hk_0_2/panel_latest.json').write_text('{}')
    (rebound / 'assets/hk_security_master/latest.json').write_text('{}')
    owner = tmp_path / 'owner'; owner.mkdir()
    spec = {
        'schema_version':'v4.manager_close_offline_replay_spec.v1',
        'trade_date':'20260925',
        'clock_iso':'2026-09-25T15:30:30+08:00',
        'materializer_app_root':str(app),
        'materializer_source_sha256':_sha(materializer),
        'data_root':str(data),
        'universe_root':str(universe),
        'news_owner_root':str(news),
        'universe_owner_root':str(owner),
        'universe_owner_sha256':'0' * 64,
        'rebound_authority_root':str(rebound),
    }
    result = execute_offline_replay(spec, state_root=state)
    assert result['status'] == 'SAFE_REPLAY_FAILED'
    assert result['snapshot_fetch_calls'] == 0
    assert result['external_process_calls'] == 0
    assert result['network_calls'] == 0
    assert result['materializer_result']['status'] in {'FAILED','INPUT_MISSING'}


def _attempt(date: str, run_id: str, state: str) -> dict:
    from v4.manager_research.workspace import seal_attempt
    row = {
        'schema_version':'v4.manager_research.workspace_attempt.v1',
        'target_trade_date':date,'run_id':run_id,
        'owner':'ManagerResearchJobService.refresh_announcements',
        'state':state,'execution_kind':'MANUAL_REFRESH',
        'started_at':'2026-09-25T07:00:00+00:00','last_success_at':None,
        'failure_reasons':[], 'RESEARCH_ONLY':True,'production_allowed':False,
        'buy_gate_updated':False,'orders_sent':False,
    }
    if state != 'RUNNING': row['finished_at']='2026-09-25T07:00:01+00:00'
    return seal_attempt(row)


def test_recovery_witness_is_built_only_from_validated_owner_attempts(tmp_path):
    from ops.run_manager_state_compatibility_canary import _announcement_recovery_witness
    root=tmp_path/'state'; runroot=root/'workspace_announcement_runs/20260925'; runroot.mkdir(parents=True)
    interrupted=_attempt('20260925','a'*32,'RUNNING')
    (runroot/'latest.json').write_text(json.dumps(interrupted))
    first=_announcement_recovery_witness(root,'20260925',None)
    assert first['interrupted']['state']=='RUNNING'
    recovered=_attempt('20260925','b'*32,'PARTIAL')
    (runroot/'latest.json').write_text(json.dumps(recovered))
    final=_announcement_recovery_witness(root,'20260925',first)
    assert final['interrupted']['run_id']=='a'*32
    assert final['recovered']['run_id']=='b'*32
    assert final['recovered']['state']=='PARTIAL'


def test_materializer_result_validator_requires_safe_offline_replay_and_zero_fallbacks():
    from v4.manager_research.activation_canary import _materializer_result_valid
    sandbox={
        'status':'VERIFIED','kind':'materializer','run_id':'a'*32,
        'identity_sha256':'1'*64,'owner_entrypoint_sha256':'2'*64,
        'app_inventory_sha256':'3'*64,'data_tree_sha256':'4'*64,'argv_sha256':'5'*64,
    }
    payload={
        'schema_version':'v4.manager_research.materializer_offline_replay.v1',
        'status':'SAFE_REPLAY_SUCCEEDED','snapshot_fetch_calls':0,'external_process_calls':0,
        'network_calls':0,'input_unchanged':True,'input_identity_sha256':'6'*64,
        'sandbox_identity':sandbox,
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
    }
    row={'returncode':0,'timed_out':False,'stdout_tail':json.dumps(payload)}
    assert _materializer_result_valid(row) is True
    row2={**row,'stdout_tail':json.dumps({**payload,'network_calls':1})}
    assert _materializer_result_valid(row2) is False


def test_materializer_invocation_gets_per_run_identity_and_receipt(tmp_path):
    from ops.run_manager_state_compatibility_canary import _prepare_materializer_invocation
    app=Path(__file__).resolve().parents[1]
    replay=tmp_path/'replay.json'; replay.write_text('{}')
    template=[str(Path(sys.executable).resolve()),'-B','-m','ops.run_manager_materializer_offline_replay',
        '--state-root','{state_root}','--trade-date','20260925','--replay-spec',str(replay),
        '--replay-spec-sha256',_sha(replay),'--sandbox-identity','{sandbox_identity}','--receipt','{receipt}']
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory(prefix='manager-state-canary-') as td:
        sandbox=Path(td).resolve(); state=sandbox/'scenario'; state.mkdir()
        rendered,identity_path,receipt_path,identity=_prepare_materializer_invocation(
            template,sandbox_root=sandbox,data_root=state,app=app,invocation_id='materializer')
        assert identity['kind']=='materializer'
        assert identity_path.is_file()
        assert str(identity_path) in rendered and str(receipt_path) in rendered


def test_materializer_command_identity_round_trips_through_activation_validator(tmp_path):
    import json, sys
    from ops.run_manager_state_compatibility_canary import _command
    from v4.manager_research.activation_canary import _stored_command_identity
    app=Path(__file__).resolve().parents[1]; source=tmp_path/'source'; source.mkdir()
    replay=tmp_path/'replay.json'; replay.write_text('{}')
    command=json.dumps([str(Path(sys.executable).resolve()),'-B','-m','ops.run_manager_materializer_offline_replay',
        '--state-root','{state_root}','--trade-date','20260925','--replay-spec',str(replay),
        '--replay-spec-sha256',_sha(replay),'--sandbox-identity','{sandbox_identity}','--receipt','{receipt}'])
    _rendered,identity=_command(command,tmp_path/'sandbox',source,app,'materializer')
    assert _stored_command_identity(identity,'materializer',app) is True


def _replay_identity_fixture(tmp_path, app):
    date='20260924'
    state=tmp_path/'state'; data=tmp_path/'data'; universe=tmp_path/'universe'
    news_owner=tmp_path/'news-owner'; universe_owner=tmp_path/'universe-owner'; rebound=tmp_path/'rebound'
    inputs=state/f'workbench_research/{date}/inputs'; inputs.mkdir(parents=True)
    (inputs/'1530_futu_snapshot.json').write_text(json.dumps({
        'trade_date':date,'started_at':'2026-09-24T15:30:10+08:00','available_at':'2026-09-24T15:30:20+08:00'}))
    (inputs/'1530_futu_snapshot.json.receipt.json').write_text('{}')
    (inputs/'1530_rebound_history.json').write_text(json.dumps({'trade_date':date,'source_files':[]}))
    data.mkdir(); universe.mkdir(); (news_owner/'ops').mkdir(parents=True)
    (news_owner/'ops/collect_hourly_research_input.py').write_text('# fixture owner path')
    owner_path=universe_owner/'stage_center/hk_universe_preflight.py'; owner_path.parent.mkdir(parents=True)
    actual_owner=app/'stage_center/hk_universe_preflight.py'
    owner_path.write_bytes(actual_owner.read_bytes())
    (rebound/'assets/hk_0_2').mkdir(parents=True)
    (rebound/'assets/hk_security_master').mkdir(parents=True)
    (rebound/'assets/hk_0_2/panel_latest.json').write_text('{}')
    (rebound/'assets/hk_security_master/latest.json').write_text('{}')
    spec={
        'schema_version':'v4.manager_close_offline_replay_spec.v1','trade_date':date,
        'clock_iso':'2026-09-24T15:30:30+08:00','materializer_app_root':str(app),
        'materializer_source_sha256':_sha(app/'ops/materialize_manager_close_discovery.py'),
        'data_root':str(data),'universe_root':str(universe),'news_owner_root':str(news_owner),
        'universe_owner_root':str(universe_owner),'universe_owner_sha256':_sha(owner_path),
        'rebound_authority_root':str(rebound),
    }
    return state,data,universe,news_owner,universe_owner,rebound,spec


def test_replay_identity_tracks_news_json_and_materializer_import_sources(tmp_path):
    from v4.manager_research.activation_canary import _MATERIALIZER_RUNTIME_FILES
    from v4.manager_research.materializer_replay import _input_identity

    app=Path(__file__).resolve().parents[1]
    state,data,_universe,_news_owner,_universe_owner,_rebound,spec=_replay_identity_fixture(tmp_path,app)
    before=_input_identity(spec,state)
    news=(data/f"research/incoming/{spec['trade_date']}/1530.json")
    news.parent.mkdir(parents=True); news.write_text(json.dumps({'fixture_input':True}))
    after=_input_identity(spec,state)

    assert after!=before
    assert after['news_inputs']['files'][news.relative_to(data).as_posix()]==_sha(news)
    assert after['materializer_app_sources']=={
        rel:_sha(app/rel) for rel in _MATERIALIZER_RUNTIME_FILES
    }
    assert {
        'apps/api/v35_api/manager_workbench_router.py',
        'apps/__init__.py',
        'apps/api/__init__.py',
        'apps/api/v35_api/__init__.py',
        'contracts/__init__.py',
        'infrastructure/__init__.py',
        'domains/manager_close_discovery.py',
        'domains/manager_catalyst_tracking.py',
    }<=set(after['materializer_app_sources'])



def test_replay_identity_changes_when_a_stable_local_import_dependency_changes(tmp_path):
    from v4.manager_research.activation_canary import _MATERIALIZER_RUNTIME_FILES
    from v4.manager_research.materializer_replay import _input_identity

    canonical = Path(__file__).resolve().parents[1]
    app = tmp_path / "writer-app"
    app.mkdir()
    for relative in _MATERIALIZER_RUNTIME_FILES:
        source = canonical / relative
        target = app / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    owner_source = canonical / "stage_center/hk_universe_preflight.py"
    (app / "stage_center").mkdir(exist_ok=True)
    shutil.copy2(owner_source, app / "stage_center/hk_universe_preflight.py")

    state, _data, _universe, _news_owner, _universe_owner, _rebound, spec = _replay_identity_fixture(tmp_path, app)
    relative = "upstreams/v3_shared_data/shared_data/hk_security_master.py"
    before = _input_identity(spec, state)
    dependency = app / relative
    dependency.write_text(dependency.read_text(encoding="utf-8") + "\n# changed in writer root\n", encoding="utf-8")
    after = _input_identity(spec, state)

    assert before["materializer_app_sources"][relative] != after["materializer_app_sources"][relative]
    assert after["materializer_app_sources"][relative] == _sha(dependency)
    assert before != after


def test_materializer_worker_and_writer_source_inventories_are_separate_contracts():
    from v4.manager_research.activation_canary import (
        _MATERIALIZER_APP_FILES, _MATERIALIZER_REPLAY_WORKER_FILES, _MATERIALIZER_RUNTIME_FILES,
    )
    assert set(_MATERIALIZER_REPLAY_WORKER_FILES).isdisjoint(_MATERIALIZER_RUNTIME_FILES)
    assert _MATERIALIZER_APP_FILES == _MATERIALIZER_REPLAY_WORKER_FILES + _MATERIALIZER_RUNTIME_FILES
    assert len(_MATERIALIZER_REPLAY_WORKER_FILES) == 3
    assert len(_MATERIALIZER_RUNTIME_FILES) == 27
    assert len(_MATERIALIZER_APP_FILES) == 30
    assert "ops/materialize_manager_close_discovery.py" in _MATERIALIZER_RUNTIME_FILES
    assert "ops/run_manager_materializer_offline_replay.py" not in _MATERIALIZER_RUNTIME_FILES
    assert "upstreams/v3_shared_data/shared_data/__init__.py" in _MATERIALIZER_RUNTIME_FILES
    assert "upstreams/v3_shared_data/shared_data/collectors.py" in _MATERIALIZER_RUNTIME_FILES
    assert "upstreams/v3_shared_data/shared_data/constants.py" in _MATERIALIZER_RUNTIME_FILES
    assert "upstreams/v3_shared_data/shared_data/hk_security_master.py" in _MATERIALIZER_RUNTIME_FILES


def test_materializer_input_identity_rejects_unscanned_or_unsafe_universe_tree():
    from v4.manager_research.activation_canary import _MATERIALIZER_RUNTIME_FILES, _materializer_input_identity_valid

    def payload(tree,*,include_tree=True):
        identity={
            'state_inputs':{'workbench_research/20260924/inputs/1530_futu_snapshot.json':'a'*64},
            'rebound_inputs':{'assets/hk_security_master/latest.json':'b'*64},
            'news_inputs':{'prior_session_date':'20260923','files':{}},
            'materializer_app_sources':{path:'c'*64 for path in _MATERIALIZER_RUNTIME_FILES},
            'universe_owner_source_sha256':'d'*64,'news_owner_source_sha256':'e'*64,
            'materializer_source_sha256':'f'*64,
        }
        if include_tree: identity['universe_date_tree']=tree
        return {'input_unchanged':True,'input_identity_before':identity,'input_identity_after':identity,
            'input_identity_sha256':hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()}

    valid_path='universes/20260924/HK/00001.json'
    valid_hash='1'*64
    assert _materializer_input_identity_valid(payload({valid_path:valid_hash}))
    assert _materializer_input_identity_valid(payload({}))
    invalid_trees=[
        {'__identity_error__':'UNAVAILABLE_OR_UNSAFE'},
        None,
        [],
        {valid_path:'not-a-sha256'},
        {'../escape.json':valid_hash},
        {'/absolute.json':valid_hash},
        {'C:/drive-path.json':valid_hash},
        {r'universes\\20260924\\HK\\00001.json':valid_hash},
        {'universes//20260924/HK/00001.json':valid_hash},
    ]
    for tree in invalid_trees:
        assert not _materializer_input_identity_valid(payload(tree)), repr(tree)
    assert not _materializer_input_identity_valid(payload(None,include_tree=False))


def test_valid_sandbox_child_intercepts_universe_owner_fallback_without_external_effects(tmp_path,monkeypatch,capsys,request):
    import subprocess
    from ops.run_manager_materializer_offline_replay import main
    from v4.manager_research.activation_canary import write_canary_sandbox_identity
    import v4.manager_research.materializer_replay as replay_module

    app=Path(__file__).resolve().parents[1]
    sandbox=Path(tempfile.mkdtemp(prefix='manager-materializer-replay-canary-')).resolve()
    request.addfinalizer(lambda: __import__('shutil').rmtree(sandbox,ignore_errors=True))
    state,data,universe,news_owner,universe_owner,rebound,spec=_replay_identity_fixture(sandbox,app)
    identities=sandbox/'identities'; identities.mkdir()
    receipts=sandbox/'receipts'; receipts.mkdir()
    spec_path=sandbox/'replay-spec.json'; spec_path.write_text(json.dumps(spec,sort_keys=True))
    identity=identities/'materializer.json'; receipt=receipts/'materializer.json'
    args=['--state-root',str(state),'--trade-date',spec['trade_date'],'--replay-spec',str(spec_path),
        '--replay-spec-sha256',_sha(spec_path),'--sandbox-identity',str(identity),'--receipt',str(receipt)]
    write_canary_sandbox_identity(identity,'materializer',data_root=state,receipt_path=receipt,
        app_root=app,argv=args)
    snapshot=state/f"workbench_research/{spec['trade_date']}/inputs/1530_futu_snapshot.json"
    snapshot_bytes=snapshot.read_bytes()
    state_before_files={p.relative_to(state).as_posix():_sha(p) for p in sorted(state.rglob('*')) if p.is_file()}
    before_external={
        'data':_tree_sha(data),'universe':_tree_sha(universe),'news_owner':_tree_sha(news_owner),
        'universe_owner':_tree_sha(universe_owner),'rebound':_tree_sha(rebound),
    }
    real_run=subprocess.run
    triggered=[]
    expected_env={
        'PATH':str(Path(sys.executable).parent),'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1',
        'PRODUCTION_ALLOWED':'false','BUY_GATE_UPDATED':'false','ORDERS_SENT':'false','LANG':'C','LC_ALL':'C',
    }
    def remove_fixture_input_at_child_boundary(command,*positional,**options):
        if len(command)>3 and command[1]=='-B' and command[2]=='-c' and 'V4_OFFLINE_REPLAY_RESULT=' in command[3]:
            assert options.get('env')==expected_env
            snapshot.unlink()
            triggered.append('offline-replay-child-start')
        return real_run(command,*positional,**options)
    monkeypatch.setattr(replay_module.subprocess,'run',remove_fixture_input_at_child_boundary)
    try:
        code=main(args)
    finally:
        snapshot.write_bytes(snapshot_bytes)

    captured=capsys.readouterr()
    output=json.loads(receipt.read_text())
    assert triggered==['offline-replay-child-start']
    assert code==2
    assert output['status']=='SAFE_REPLAY_FAILED'
    assert output['external_process_calls']==1, json.dumps(output,indent=2,sort_keys=True)
    assert output['network_calls']==0
    assert output['snapshot_fetch_calls']==0
    assert output['materializer_result']['reason']=='OFFLINE_REPLAY_MATERIALIZER_EXCEPTION:RuntimeError:OFFLINE_REPLAY_EXTERNAL_PROCESS_FORBIDDEN'
    assert output['sandbox_identity']['status']=='VERIFIED'
    assert identity.with_name(identity.name+'.started').is_file()
    assert not (state/f"workbench_research/{spec['trade_date']}/1530.json").exists()
    assert not list(universe.rglob('*'))
    state_after_files={p.relative_to(state).as_posix():_sha(p) for p in sorted(state.rglob('*')) if p.is_file()}
    expected_failure_outputs={f"workbench_research/{spec['trade_date']}/1530.lock.mutex",
        f"workbench_research/{spec['trade_date']}/1530.status.json"}
    assert set(state_after_files)==set(state_before_files)|expected_failure_outputs
    assert all(state_after_files[path]==digest for path,digest in state_before_files.items())
    status=json.loads((state/f"workbench_research/{spec['trade_date']}/1530.status.json").read_text())
    assert status['status']=='PENDING_SLOT'
    assert status['RESEARCH_ONLY'] is True
    assert status['production_allowed'] is False
    assert status['buy_gate_updated'] is False
    assert status['orders_sent'] is False
    assert {
        'data':_tree_sha(data),'universe':_tree_sha(universe),'news_owner':_tree_sha(news_owner),
        'universe_owner':_tree_sha(universe_owner),'rebound':_tree_sha(rebound),
    }==before_external
    assert 'OFFLINE_REPLAY_EXTERNAL_PROCESS_FORBIDDEN' in output['materializer_result']['reason']


def test_replay_origin_evidence_keeps_expected_source_at_manager_root(tmp_path):
    from v4.manager_research.materializer_replay import (
        validate_replay_origin_bundle,
        validate_replay_origin_evidence,
    )

    app=Path(__file__).resolve().parents[1]
    origin,seed,bundle,spec,spec_sha,date=_seed_origin_bundle_fixture(tmp_path,app)
    evidence=validate_replay_origin_bundle(bundle,expected_seed_root=seed,
        expected_trade_date=date,expected_replay_spec_path=spec,
        expected_replay_spec_sha256=spec_sha,expected_source_state_root=origin)
    checked=validate_replay_origin_evidence(evidence,expected_source_state_root=origin,
        expected_replay_seed_root=seed,expected_trade_date=date)
    assert checked['source_state_root']==str(origin)
    assert checked['replay_seed_root']==str(seed)
    with pytest.raises(ValueError,match='REPLAY_ORIGIN_EVIDENCE_ROOT_OR_DATE_MISMATCH'):
        validate_replay_origin_evidence(evidence,expected_source_state_root=seed,
            expected_replay_seed_root=seed,expected_trade_date=date)
    mutated={**evidence,'origin_inputs_after':{**evidence['origin_inputs_after'],
        next(iter(evidence['copied_inputs'])):'0'*64}}
    with pytest.raises(ValueError,match='REPLAY_ORIGIN_EVIDENCE_UNCHANGED_INPUTS_INVALID'):
        validate_replay_origin_evidence(mutated,expected_source_state_root=origin,
            expected_replay_seed_root=seed,expected_trade_date=date)


def test_shared_root_canary_uses_origin_bundle_but_launches_only_a_seed_clone(tmp_path,monkeypatch):
    import ops.run_manager_state_compatibility_canary as canary

    app=Path(__file__).resolve().parents[1]
    origin,seed,bundle,spec,spec_sha,date=_seed_origin_bundle_fixture(tmp_path,app)
    security=tmp_path/'security-master'; security.mkdir()
    announcement=[str(Path(sys.executable).resolve()),'-B','-m','ops.run_manager_announcement_owner_canary',
        '--state-root','{state_root}','--trade-date',date,'--security-master-root',str(security),
        '--sandbox-identity','{sandbox_identity}','--receipt','{receipt}']
    materializer=[str(Path(sys.executable).resolve()),'-B','-m','ops.run_manager_materializer_offline_replay',
        '--state-root','{state_root}','--trade-date',date,'--replay-spec',str(spec),
        '--replay-spec-sha256',spec_sha,'--sandbox-identity','{sandbox_identity}','--receipt','{receipt}']
    observed=[]
    class StopAtChild(RuntimeError):
        pass
    def stop_before_child(argv,cwd,timeout):
        state=Path(argv[argv.index('--state-root')+1])
        observed.append(state)
        assert state not in {origin,seed}
        assert state.name=='announcement'
        raise StopAtChild
    monkeypatch.setattr(canary,'_run',stop_before_child)
    args=['--source-state-root',str(seed),'--seed-origin-receipt',str(bundle),
        '--app-root',str(app),'--announcement-command-json',json.dumps(announcement),
        '--materializer-command-json',json.dumps(materializer),'--timeout-seconds','2',
        '--interrupt-after-seconds','1','--receipt',str(tmp_path/'activation.json')]
    without_origin=args.copy()
    origin_flag=without_origin.index('--seed-origin-receipt')
    del without_origin[origin_flag:origin_flag+2]
    with pytest.raises(ValueError,match='CANARY_SEED_ORIGIN_RECEIPT_REQUIRED'):
        canary.main(without_origin)
    assert observed==[]
    with pytest.raises(StopAtChild):
        canary.main(args)
    assert len(observed)==1


def _tree_sha(root: Path) -> str:
    rows={p.relative_to(root).as_posix():_sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
