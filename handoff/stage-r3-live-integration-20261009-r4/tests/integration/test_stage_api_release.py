"""Real release guards and original publication functions; simulated launchd/HTTP.

The candidate and R3 data are freshly produced by the existing integration
fixture. No test starts a service or performs market acquisition.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import sys
import stat
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

WORK = Path(__file__).resolve().parents[2]
TOOLS = Path(os.environ.get('R4_TOOL_ROOT', WORK / 'publication/tools'))
REFERENCES = Path(os.environ.get('R4_PUBLICATION_REFERENCE_ROOT', WORK / 'publication/reference'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


@pytest.fixture
def publication(tmp_path, monkeypatch):
    sibling = Path(__file__).with_name('test_live_release_preparation.py')
    fixture_file = sibling if sibling.exists() else WORK / 'integration/tests/test_live_release_preparation.py'
    fixture = load('_publication_integration_fixture', fixture_file, monkeypatch)
    case = fixture.case.__wrapped__(tmp_path, monkeypatch)
    manager = tmp_path / 'manager_state'
    disabled = tmp_path / 'disabled-binding.json'
    dump(disabled, dict(enabled=False, announcement_collection_enabled=False,
                        plan_material_refresh_only=False, manager_state_root=str(manager)))
    screen = tmp_path / 'screen_authority'; screen.mkdir()
    stage_plist = tmp_path / 'stage-scheduler.plist'
    stage_plist.write_bytes(b'UNCHANGED STAGE SCHEDULER\n')
    current = plistlib.loads(case.pointer.read_bytes())
    current.update(KeepAlive=True, RunAtLoad=False)
    current['ProgramArguments'][1:1] = [
        'V4_MANAGER_PLAN_OWNER_BINDING_PATH=' + str(disabled),
        'V4_MANAGER_SCREEN_AUTHORITY_ROOT=' + str(screen),
    ]
    case.pointer.write_bytes(plistlib.dumps(current, sort_keys=True))
    case.pointer_before = case.pointer.read_bytes()
    result = case.tool.prepare_live_release(**case.args)
    shutil.copyfile(Path(case.tool.__file__), case.package / 'tools/prepare_live_release.py')
    tool_file = TOOLS / 'stage_api_release.py'
    tool = load('_stage_publication_under_test', tool_file, monkeypatch) if tool_file.exists() else SimpleNamespace()
    assert callable(getattr(tool, 'prepare_stage_publication', None)), 'bounded Stage publisher is missing'
    publisher = tool._load_publisher(REFERENCES / 'api_only_cutover_issue32_r4.py')
    # Temporary machine paths stand in for the fixed Mac surfaces. Production
    # wrapper contains no assignments to any publisher constants.
    for name, value in {
        'ACTIVE_API_PLIST': case.pointer, 'ACTIVE_SCHEDULER_PLIST': case.args['scheduler_plist'],
        'STAGE_CENTER_SCHEDULER_PLIST': stage_plist, 'DISABLED_BINDING_PATH': disabled,
        'SCREEN_AUTHORITY_ROOT': screen, 'FORMAL_MANAGER_STATE': manager,
        'PINNED_PYTHON': Path(sys.executable), 'LAUNCHCTL': Path(sys.executable),
        'INTEGRATION_GUARD_PATH': REFERENCES / 'api_release_integration_before.py',
    }.items():
        monkeypatch.setattr(publisher, name, value)
    original_loader = tool._load_publisher
    monkeypatch.setattr(tool, '_load_publisher', lambda path: (original_loader(path), publisher)[1])
    monkeypatch.setattr(tool, 'APPROVED_RESEARCH_RUN', deepcopy(case.research.binding_module.APPROVED_RESEARCH_RUN))
    binding_path = Path(result['candidate_app']) / 'stage_center/approved_research_read.json'
    binding = json.loads(binding_path.read_text())
    monkeypatch.setattr(tool, 'READER_SOURCES', binding['reader_sources'])
    # Load the candidate's actual fixture reader and project with the delivered
    # route. Fixture approval constants are only substituted in temporary files.
    api_tests = Path(os.environ.get('R4_API_TEST_ROOT', fixture.API / 'tests'))
    api_fixture = load('_publication_api_fixture', api_tests / 'conftest.py', monkeypatch)
    app = Path(result['candidate_app'])
    load('stage_center.execution_evidence', app / 'stage_center/execution_evidence.py', monkeypatch)
    consumer = load('stage_center.consumer', app / 'stage_center/consumer.py', monkeypatch)
    reader_module = load('stage_center.research_read_binding', app / 'stage_center/research_read_binding.py', monkeypatch)
    reader = reader_module.ApprovedResearchReadBinding(binding_path=binding_path,
        history_root=case.research.history.root, api_root=app,
        expected_reader_sha256=sha((app / 'stage_center/research_read_binding.py').read_bytes()))
    case.research.consumer = consumer
    case.research.binding_module = reader_module
    route = api_fixture.route_source(case.research, research_reader=reader)['stage_workbench']
    old_route = api_fixture.route_source(case.research, phase='before')['stage_workbench']
    state = SimpleNamespace(role='base', pid=101, calls=[], http_fault=None,
                            fail_candidate_bootstrap=False, fail_base_bootstrap=False,
                            before_action=None, printed_transition=False, clock=0.0,
                            startup_polls=0, http_refusals=0, startup_timeout=False,
                            startup_absent=False, historical_natural=False,
                            after_action=None, leased_actions=[])
    old_identity = publisher._identity_from_plist(case.pointer.read_bytes())
    candidate_identity = {'V35_APP_ROOT': result['candidate_app'],
        'V35_RELEASE_ID': case.args['release_id'], 'V35_RELEASE_MANIFEST_SHA256': result['manifest_sha256']}

    def run(command, **kwargs):
        action = command[1]
        if action == 'print':
            if state.role == 'candidate' and state.startup_absent:
                return SimpleNamespace(returncode=113, stdout='', stderr='Could not find service')
            if state.role == 'candidate' and (state.startup_polls or state.startup_timeout):
                state.startup_polls = max(0, state.startup_polls - 1)
                return SimpleNamespace(returncode=0, stdout='state = waiting\n', stderr='')
            if state.role is None:
                return SimpleNamespace(returncode=113, stdout='', stderr='Could not find service')
            if state.role == 'transition':
                state.role = None
                return SimpleNamespace(returncode=0, stdout='state = waiting\n', stderr='')
            identity = old_identity if state.role == 'base' else candidate_identity
            output = 'state = running\npid = ' + str(state.pid) + '\n' + '\n'.join(k + '=' + v for k, v in identity.items())
            return SimpleNamespace(returncode=0, stdout=output, stderr='')
        state.calls.append(action)
        leases = list(publisher._INTEGRATION_GUARD_LEASES.values())
        assert len(leases) == 1, 'every simulated service action must retain the original lease'
        publisher._require_release_lock(leases[0][0])
        state.leased_actions.append(action)
        if state.before_action:
            state.before_action(action)
        if action == 'bootout':
            state.role = 'transition' if state.printed_transition else None
        elif action == 'bootstrap':
            role = 'base' if sha(case.pointer.read_bytes()) == sha(case.pointer_before) else 'candidate'
            if (role == 'candidate' and state.fail_candidate_bootstrap) or (role == 'base' and state.fail_base_bootstrap):
                return SimpleNamespace(returncode=5, stdout='', stderr='SYNTHETIC_BOOTSTRAP_FAILURE')
            state.role = role; state.pid += 1
        else:
            raise AssertionError(command)
        if state.after_action:
            state.after_action(action)
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def http(path):
        if path == '/openapi.json':
            if state.role == 'candidate' and state.http_refusals:
                state.http_refusals -= 1
                raise ValueError('API_ONLY_HTTP_READBACK_FAILED:/openapi.json:URLError')
            return 200, json.dumps({'paths': {publisher.MANAGER_WORKSPACE_ROUTE: {'get': {}},
                '/api/v3/workbench/stage': {'get': {}}}}).encode()
        parsed = urlsplit(path)
        if parsed.path == '/api/v3/workbench/stage':
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            selected = route if state.role == 'candidate' else old_route
            payload = selected(date=query['date'], stage=query['stage'], limit=int(query.get('limit', 50)))
            payload = deepcopy(payload)
            target = query['date'] == '20261009' and query['stage'] == 'STAGE_0930_0935'
            if not target and state.historical_natural:
                payload.setdefault('execution_evidence', {}).update(natural_verified=True, execution_verified=True)
            if state.role == 'candidate' and state.http_fault:
                fault = state.http_fault
                if target:
                    if fault == 'run': payload['markets']['HK']['run_id'] = 'run-wrong'
                    if fault == 'safety': payload['orders_sent'] = True
                    if fault == 'reader': payload['research_read_binding']['reader_sources']['stage_center/consumer.py'] = 'f' * 64
                    if fault == 'row': payload['markets']['HK']['rows'][0]['code'] = 'HK.BAD'
                    if fault == 'count': payload['markets']['HK']['rows'].pop()
                    if fault == 'natural': payload['execution_evidence']['natural_verified'] = True
                    if fault == 'unified': payload['unified_rows'] = []
                    if fault == 'selected_algorithm': payload['execution_evidence']['selection_results']['A_SHARE']['algorithm_sha256'] = 'f' * 64
                    if fault == 'requested': payload['markets']['A']['requested_rows'] = 200
                elif fault == 'history': payload['markets']['A']['run_id'] = 'run-history-drift'
                elif fault == 'history_safety': payload['orders_sent'] = True
                elif fault == 'history_natural':
                    payload['execution_evidence'] = {'natural_verified': True, 'execution_verified': True}
            return 200, json.dumps(payload).encode()
        relative = parsed.path.lstrip('/')
        if not relative or relative.endswith('/'): relative += 'index.html'
        source = (app if state.role == 'candidate' else case.app) / 'apps/web/dist' / relative
        raw = source.read_bytes()
        if state.role == 'candidate' and state.http_fault == 'static': raw += b'WRONG HTTP CACHE'
        return 200, raw

    monkeypatch.setattr(publisher, 'subprocess', SimpleNamespace(run=run))
    monkeypatch.setattr(publisher, '_http_get', http)
    # These clocks only avoid simulated launchd's polling delay.
    def clock():
        state.clock += 0.1
        return state.clock
    def sleep(seconds):
        state.clock += seconds
    monkeypatch.setattr(publisher, 'time', SimpleNamespace(monotonic=clock, sleep=sleep))
    args = dict(preparation_receipt=Path(result['receipt_path']),
        expected_preparation_sha256=sha(Path(result['receipt_path']).read_bytes()),
        publisher_path=REFERENCES / 'api_only_cutover_issue32_r4.py',
        stage_guard_path=case.package / 'release_tools/after/ops/api_release_integration.py')
    return SimpleNamespace(case=case, tool=tool, publisher=publisher, state=state,
        args=args, result=result, binding=binding, route=route, old_route=old_route,
        pointer=case.pointer, before=case.pointer_before, manager=manager, stage_plist=stage_plist)


def prepare(case):
    return case.tool.prepare_stage_publication(**case.args)


def execute(case, prepared):
    return case.tool.execute_stage_publication(plan_path=Path(prepared['plan_path']),
        expected_plan_sha256=prepared['plan_sha256'], confirmation=case.tool.CONFIRM_EXECUTE,
        expected_current_sha256=prepared['current_plist_sha256'],
        expected_staged_sha256=prepared['staged_plist_sha256'])


def rollback(case, prepared, result, current=None):
    return case.tool.rollback_stage_publication(plan_path=Path(prepared['plan_path']),
        expected_plan_sha256=prepared['plan_sha256'], receipt_path=Path(result['receipt_path']),
        expected_receipt_sha256=result['receipt_sha256'], confirmation=case.tool.CONFIRM_ROLLBACK,
        expected_current_sha256=current or sha(case.pointer.read_bytes()))


def test_prepare_preserves_manager_history_and_has_no_service_actions(publication):
    case = publication
    prepared = prepare(case)
    assert prepared['status'] == 'STAGE_PUBLICATION_PREPARED_NOT_DEPLOYED'
    assert case.pointer.read_bytes() == case.before and case.state.calls == []
    plan = json.loads(Path(prepared['plan_path']).read_text())
    assert plan['history']['root'] == str(case.case.research.history.root)
    assert len(plan['history']['selection_dates']) == 19
    assert plan['manager_state_root'] == str(case.manager)
    staged = plistlib.loads(Path(plan['target']['staged_api_plist_path']).read_bytes())
    before = plistlib.loads(case.before)
    assert staged['ProgramArguments'][-2:] == before['ProgramArguments'][-2:]
    assert [x for x in staged['ProgramArguments'] if x.startswith('V4_MANAGER_RESEARCH_STATE_ROOT=')] == [
        'V4_MANAGER_RESEARCH_STATE_ROOT=' + str(case.manager)]


def test_execute_and_manual_rollback_reuse_original_transaction(publication):
    case = publication; prepared = prepare(case); result = execute(case, prepared)
    assert result['status'] == 'STAGE_API_SWITCHED_AND_READBACK_VERIFIED'
    assert result['runtime_verification']['research']['market_row_counts'] == {'A_SHARE': 10, 'HK_CONNECT': 10}
    assert result['runtime_verification']['history']['checked_pairs'] == 19
    assert case.state.calls == ['bootout', 'bootstrap']
    restored = rollback(case, prepared, result)
    assert restored['status'] == 'ROLLED_BACK_TO_PREIMAGE'
    assert case.pointer.read_bytes() == case.before and case.state.role == 'base'


@pytest.mark.parametrize('fault', ['run', 'safety', 'reader', 'row', 'count', 'natural', 'static', 'history', 'history_safety'])
def test_bad_candidate_readback_automatically_restores_preimage(publication, fault):
    case = publication; prepared = prepare(case); case.state.http_fault = fault
    with pytest.raises(ValueError, match='FAILED_AND_ROLLED_BACK'):
        execute(case, prepared)
    assert case.pointer.read_bytes() == case.before and case.state.role == 'base'


@pytest.mark.parametrize('fault', ['pointer', 'manifest', 'staged', 'history', 'scheduler', 'plan'])
def test_preflight_drift_has_no_service_action(publication, fault):
    case = publication; prepared = prepare(case)
    plan = json.loads(Path(prepared['plan_path']).read_text())
    files = {'pointer': case.pointer, 'manifest': Path(case.result['manifest_path']),
        'staged': Path(plan['target']['staged_api_plist_path']),
        'history': case.case.research.history.root / 'selection_latest.json',
        'scheduler': case.stage_plist, 'plan': Path(prepared['plan_path'])}
    path = files[fault]; path.chmod(0o600); path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError): execute(case, prepared)
    assert case.state.calls == []


def test_bootstrap_failure_uses_original_automatic_recovery(publication):
    case = publication; prepared = prepare(case); case.state.fail_candidate_bootstrap = True
    with pytest.raises(ValueError, match='FAILED_AND_ROLLED_BACK'): execute(case, prepared)
    assert case.pointer.read_bytes() == case.before and case.state.role == 'base'


def test_manual_rollback_after_candidate_corruption_does_not_require_candidate(publication):
    case = publication; prepared = prepare(case); result = execute(case, prepared)
    (Path(case.result['candidate_app']) / 'stage_center/consumer.py').write_text('CORRUPTED\n')
    restored = rollback(case, prepared, result)
    assert restored['status'] == 'ROLLED_BACK_TO_PREIMAGE'
    assert case.pointer.read_bytes() == case.before


@pytest.mark.parametrize('fault', ['receipt', 'prepared', 'backup', 'plan'])
def test_rollback_rejects_tampered_proofs_before_service_action(publication, fault):
    case = publication; prepared = prepare(case); result = execute(case, prepared)
    receipt = json.loads(Path(result['receipt_path']).read_text())
    paths = {'receipt': Path(result['receipt_path']), 'prepared': Path(receipt['prepared_receipt']['path']),
        'backup': Path(receipt['backup_path']), 'plan': Path(prepared['plan_path'])}
    path = paths[fault]; path.chmod(0o600); path.write_bytes(path.read_bytes() + b' ')
    actions = list(case.state.calls)
    with pytest.raises(ValueError): rollback(case, prepared, result)
    assert case.state.calls == actions


def test_unknown_pointer_after_bootout_is_not_overwritten(publication):
    case = publication; prepared = prepare(case)
    def race(action):
        if action == 'bootout': case.pointer.write_bytes(b'UNKNOWN CONCURRENT POINTER')
    case.state.before_action = race
    with pytest.raises(ValueError, match='ROLLBACK_INCOMPLETE'): execute(case, prepared)
    assert case.pointer.read_bytes() == b'UNKNOWN CONCURRENT POINTER'
    assert case.state.calls == ['bootout']


def test_explicit_confirmation_and_expected_hashes_are_required(publication):
    case = publication; prepared = prepare(case)
    with pytest.raises(ValueError):
        case.tool.execute_stage_publication(plan_path=Path(prepared['plan_path']),
            expected_plan_sha256=prepared['plan_sha256'], confirmation='YES',
            expected_current_sha256=prepared['current_plist_sha256'],
            expected_staged_sha256=prepared['staged_plist_sha256'])
    assert case.state.calls == []


@pytest.mark.parametrize('field', ['current', 'staged', 'plan'])
def test_wrong_expected_hash_arguments_never_touch_service(publication, field):
    case = publication; prepared = prepare(case)
    values = dict(plan_path=Path(prepared['plan_path']), expected_plan_sha256=prepared['plan_sha256'],
        confirmation=case.tool.CONFIRM_EXECUTE, expected_current_sha256=prepared['current_plist_sha256'],
        expected_staged_sha256=prepared['staged_plist_sha256'])
    values['expected_' + field + '_sha256'] = 'f' * 64
    with pytest.raises(ValueError): case.tool.execute_stage_publication(**values)
    assert case.state.calls == []


def test_shared_publication_lock_contention_never_touches_service(publication):
    case = publication; prepared = prepare(case)
    guard = case.publisher._load_integration_guard()
    with guard.shared_api_release_lock(case.pointer):
        with pytest.raises(ValueError, match='SHARED_LOCK_BUSY'): execute(case, prepared)
    assert case.state.calls == [] and case.pointer.read_bytes() == case.before


def test_candidate_waits_for_launchd_and_http_readiness(publication):
    case = publication; prepared = prepare(case)
    case.state.startup_polls = 3; case.state.http_refusals = 2
    result = execute(case, prepared)
    assert result['runtime_verification']['readiness']['poll_count'] == 6
    assert case.state.calls == case.state.leased_actions == ['bootout', 'bootstrap']


def test_candidate_startup_timeout_returns_structured_recovery_context(publication):
    case = publication; prepared = prepare(case); case.state.startup_timeout = True
    with pytest.raises(case.tool.PublicationFailure) as error:
        execute(case, prepared)
    context = error.value.context
    assert context['recovery_status'] == 'ROLLBACK_INCOMPLETE'
    assert context['receipt_sha256'] == sha(Path(context['receipt_path']).read_bytes())
    # Resolve the synthetic transition, then the same explicit receipt resumes.
    case.state.startup_timeout = False
    result = rollback(case, prepared, context)
    assert result['status'] == 'ROLLED_BACK_TO_PREIMAGE'
    assert case.pointer.read_bytes() == case.before


def test_same_identity_pointer_drift_after_bootstrap_is_rejected(publication):
    case = publication; prepared = prepare(case)
    def change(action):
        if action == 'bootstrap' and case.state.role == 'candidate':
            value = plistlib.loads(case.pointer.read_bytes()); value['ThrottleInterval'] = 999
            case.pointer.write_bytes(plistlib.dumps(value, sort_keys=True))
    case.state.after_action = change
    with pytest.raises(case.tool.PublicationFailure) as error: execute(case, prepared)
    assert error.value.context['recovery_status'] == 'ROLLBACK_INCOMPLETE'
    assert plistlib.loads(case.pointer.read_bytes())['ThrottleInterval'] == 999


def test_resume_after_failed_base_bootstrap_with_absent_pointer(publication):
    case = publication; prepared = prepare(case)
    case.state.fail_candidate_bootstrap = case.state.fail_base_bootstrap = True
    with pytest.raises(case.tool.PublicationFailure) as error: execute(case, prepared)
    assert error.value.context['recovery_status'] == 'ROLLBACK_INCOMPLETE'
    case.pointer.unlink(); case.state.fail_base_bootstrap = False
    result = rollback(case, prepared, error.value.context, current='ABSENT')
    assert result['status'] == 'ROLLED_BACK_TO_PREIMAGE'
    assert result['observed_current_plist_sha256'] == sha(case.before)
    assert case.pointer.read_bytes() == case.before


def test_existing_historical_natural_evidence_is_not_reclassified(publication):
    case = publication; case.state.historical_natural = True; prepared = prepare(case)
    result = execute(case, prepared)
    assert result['status'] == 'STAGE_API_SWITCHED_AND_READBACK_VERIFIED'


def test_manager_history_bytes_modes_and_result_flags_survive_switch_and_rollback(publication):
    case = publication
    marker = case.manager / 'preserved.bin'; marker.write_bytes(b'OWNER STATE\n'); marker.chmod(0o440)
    roots = [case.manager, case.case.research.history.root]
    def snapshot():
        return {(str(path), sha(path.read_bytes()), stat.S_IMODE(path.stat().st_mode))
                for root in roots for path in root.rglob('*') if path.is_file()}
    before = snapshot(); prepared = prepare(case); result = execute(case, prepared)
    assert snapshot() == before
    restored = rollback(case, prepared, result)
    assert snapshot() == before
    for value in (prepared, result, restored):
        assert all(value[key] is expected for key, expected in case.tool.FLAGS.items())
    assert case.state.calls == case.state.leased_actions


def test_startup_absence_timeout_can_automatically_restore_base(publication):
    case = publication; prepared = prepare(case); case.state.startup_absent = True
    with pytest.raises(case.tool.PublicationFailure) as error: execute(case, prepared)
    assert error.value.context['recovery_status'] == 'ROLLED_BACK_TO_PREIMAGE'
    assert case.pointer.read_bytes() == case.before and case.state.role == 'base'


@pytest.mark.parametrize('fault', ['unified', 'selected_algorithm', 'requested'])
def test_verified_selection_counts_and_unified_projection_are_bound(publication, fault):
    case = publication; prepared = prepare(case); case.state.http_fault = fault
    with pytest.raises(ValueError, match='FAILED_AND_ROLLED_BACK'):
        execute(case, prepared)
    assert case.pointer.read_bytes() == case.before and case.state.role == 'base'


def test_cli_failure_has_concrete_receipt_and_current_sha_for_continuation(publication, capsys):
    case = publication; prepared = prepare(case); case.state.http_fault = 'run'
    result = case.tool.main(['execute', '--plan-path', prepared['plan_path'],
        '--expected-plan-sha256', prepared['plan_sha256'], '--confirmation', case.tool.CONFIRM_EXECUTE,
        '--expected-current-sha256', prepared['current_plist_sha256'],
        '--expected-staged-sha256', prepared['staged_plist_sha256']])
    value = json.loads(capsys.readouterr().out)
    assert result == 2 and value['status'] == 'FAILED_CLOSED'
    assert value['receipt_sha256'] == sha(Path(value['receipt_path']).read_bytes())
    assert value['observed_current_plist_sha256'] == sha(case.before)
    assert value['recovery_status'] == 'ROLLED_BACK_TO_PREIMAGE'
    assert all(value[key] is expected for key, expected in case.tool.FLAGS.items())
