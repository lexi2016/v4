"""Incremental native controller checks. Never signal/lock/control a real owner."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'docs/handoffs/us_mapping_scheduler_integration_20261025/activate_candidate.py'
spec = importlib.util.spec_from_file_location('native_activation_under_test', SOURCE)
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


def test_migrated_atomic_functions_match_bound_owner_ast():
    origin = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_local_panel_completion_20261024/consumer_activation_r1/activate_api_r1.py')
    assert controller.sha(origin) == controller.ATOMIC_ORIGIN_SHA
    def nodes(path):
        return {n.name:ast.dump(n, include_attributes=False) for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef)}
    a, b = nodes(SOURCE), nodes(origin)
    assert all(a[name] == b[name] for name in ('sha', 'atomic_plist'))


def test_native_prepared_is_not_forged_old_prepared():
    review = controller.PRIVATE.parent / 'review/REVIEW.json'
    manifest = controller.native_product(dict(path=str(controller.CANDIDATE / 'PREPARED.json'), sha256=controller.NATIVE_SHA), controller.pin(review))
    assert manifest['schema_version'] == 'v4.release_candidate.v1'
    native = json.loads((controller.CANDIDATE / 'PREPARED.json').read_bytes())
    assert native['state'] == 'PREPARED_NOT_ACTIVATED' and 'scope_path' not in native
    assert 'scope_sha256' not in manifest['task_overlay']
    assert len(controller.legacy().ADMISSION_FILES['scheduler']) == 17


def test_plist_proposal_only_changes_owned_entry_and_five_env_selectors():
    old = dict(WorkingDirectory=str(controller.PARENT / 'app'),
        ProgramArguments=['/bin/bash', str(controller.PARENT / 'app/ops/launch_v35_macos_scheduler.sh')],
        KeepAlive=True, Label='com.lexi.v35.scheduler',
        EnvironmentVariables=dict(PYTHONPATH='/retained/site:/old/upstreams', V35_APP_ROOT=str(controller.PARENT / 'app'),
            V35_RELEASE_ID=controller.PARENT.name, V35_RELEASE_MANIFEST_PATH=str(controller.PARENT / 'release-manifest.json'),
            V35_RELEASE_MANIFEST_SHA256=controller.PARENT_SHA, V4_MANAGER_WORKBENCH_CONFIG_PATH='/owner/config.json',
            V35_RUNTIME_ROOT='/retained/binary', V35_RESEARCH_PANEL_A_SYNC_SCRIPT='/protected/driver', OTHER='same'))
    result = plistlib.loads(controller.proposed_plist(plistlib.dumps(old)))
    assert result['WorkingDirectory'] == str(controller.CANDIDATE / 'app')
    assert result['KeepAlive'] is True and result['Label'] == old['Label']
    assert result['EnvironmentVariables']['PYTHONPATH'].split(':')[:2] == [str(controller.CANDIDATE / 'app'), str(controller.CANDIDATE / 'app/upstreams')]
    changed = {k for k,v in result['EnvironmentVariables'].items() if old['EnvironmentVariables'].get(k) != v}
    assert changed == {'V35_APP_ROOT', 'V35_RELEASE_ID', 'V35_RELEASE_MANIFEST_PATH', 'V35_RELEASE_MANIFEST_SHA256', 'PYTHONPATH'}


@pytest.mark.parametrize('conflict', ['before', 'during', 'symlink'])
def test_atomic_plist_double_cas_and_type(tmp_path, monkeypatch, conflict):
    live = tmp_path / 'scheduler.plist'
    live.write_bytes(b'parent')
    monkeypatch.setattr(controller, 'LIVE', live)
    expected = controller.sha(live)
    if conflict == 'before': live.write_bytes(b'third-party')
    elif conflict == 'symlink':
        other = tmp_path / 'other'; other.write_bytes(b'parent')
        live.unlink(); live.symlink_to(other)
    else:
        original = controller.tempfile.mkstemp
        def drift(*args, **kwargs):
            value = original(*args, **kwargs)
            live.write_bytes(b'third-party')
            return value
        monkeypatch.setattr(controller.tempfile, 'mkstemp', drift)
    with pytest.raises(RuntimeError, match='CAS_CONFLICT|TYPE_CONFLICT'):
        controller.atomic_plist(b'candidate', expected)
    assert live.read_bytes() in (b'parent', b'third-party')


def test_atomic_plist_round_trip_preserves_mode_uid_gid(tmp_path, monkeypatch):
    live = tmp_path / 'scheduler.plist'; live.write_bytes(b'parent'); live.chmod(0o640)
    monkeypatch.setattr(controller, 'LIVE', live)
    before = live.stat()
    controller.atomic_plist(b'candidate', controller.sha(live))
    controller.atomic_plist(b'parent', controller.sha(live))
    assert live.read_bytes() == b'parent'
    assert (live.stat().st_mode, live.stat().st_uid, live.stat().st_gid) == (before.st_mode, before.st_uid, before.st_gid)


def kernel(pid=10001):
    return dict(pid=pid, start_sec=123, start_usec=456, status=2, audit_token=[1,2,3,4,5,6,7,8], pid_version=77)


class FakeKernel:
    def __init__(self, token): self.token = deepcopy(token); self.signals = []
    def process_token(self, pid): return deepcopy(self.token) if self.token and self.token['pid'] == pid else None
    def same(self, token):
        actual = self.process_token(token['pid'])
        return actual is not None and all(actual[k] == token[k] for k in ('pid', 'start_sec', 'start_usec'))
    def signal(self, token, number):
        assert self.same(token) and self.token['audit_token'] == token['audit_token']
        self.signals.append(number)
        if number == signal.SIGSTOP: self.token['status'] = 4
        elif number == signal.SIGCONT: self.token['status'] = 2
        elif number == signal.SIGKILL: self.token = None


class FakeOps:
    def __init__(self, kernel, direction, fault=None):
        self.kernel, self.direction, self.fault = kernel, direction, fault
        self.binding = 'parent' if direction == 'activate' else 'candidate'
        self.original = self.binding
        self.bootstraps = 0
        self.activity_calls = 0
        self.new_owner = False
    def verify_before_freeze(self):
        if self.fault == 'source-drift': raise ValueError('SOURCE_DRIFT')
    def frozen_activity(self):
        self.activity_calls += 1
        return dict(busy_work=['PDF_PROCESSING'] if self.fault == 'busy' else [])
    def verify_commit(self):
        assert self.kernel.token['status'] == 4
        if self.fault == 'precommit': raise KeyboardInterrupt()
    def replace_binding(self): self.binding = 'candidate' if self.direction == 'activate' else 'parent'
    def restore_precommit(self): self.binding = self.original
    def bootout(self):
        if self.fault == 'bootout-timeout': raise TimeoutError()
        self.kernel.token = None
    def job_state(self): return dict(state='running' if self.new_owner else 'absent')
    def bootstrap_once(self):
        assert self.kernel.token is None
        self.bootstraps += 1; self.new_owner = True
    def final_readback(self):
        if self.fault == 'readiness': raise ValueError('READINESS_FAILED')
        return dict(state='ACTIVATED' if self.direction == 'activate' else 'ROLLED_BACK')


@pytest.mark.parametrize('direction', ['activate', 'rollback'])
@pytest.mark.parametrize('fault', [None, 'busy', 'source-drift', 'precommit', 'bootout-timeout', 'readiness', 'precommit-eof', 'postcommit-eof'])
def test_real_freeze_guardian_state_machine_with_fake_kernel(tmp_path, monkeypatch, direction, fault):
    """Use the actual retained state machine, not a substitute FakeGuardian."""
    old = controller.legacy(); token = kernel(); host = FakeKernel(token)
    monkeypatch.setattr(old, 'process_token', host.process_token)
    monkeypatch.setattr(old, 'same_process', host.same)
    monkeypatch.setattr(old, 'signal_exact_identity', host.signal)
    frames = [{'action':'FREEZE'}, {'action':'COMMIT'}, {'action':'START'}]
    if fault == 'precommit-eof': frames = frames[:1]
    if fault == 'postcommit-eof': frames = frames[:2]
    incoming, outgoing = os.pipe()
    os.write(outgoing, ''.join(json.dumps(x)+'\n' for x in frames).encode()); os.close(outgoing)
    ops = FakeOps(host, direction, fault)
    journal = tmp_path / 'guardian.json'
    with os.fdopen(incoming, 'r') as control:
        guard = old.FreezeGuardian(ops, dict(owner_token=token, journal=str(journal), controller_pid=os.getpid()), control, io.StringIO())
        guard.run()
    result = json.loads(journal.read_bytes())
    assert ops.bootstraps <= 1
    if fault in {'busy', 'source-drift', 'precommit', 'precommit-eof'}:
        assert ops.binding == ops.original and not result['committed'] and ops.bootstraps == 0
        if signal.SIGSTOP in host.signals: assert host.signals[-1] == signal.SIGCONT
    else:
        assert result['committed'] and signal.SIGCONT not in host.signals and host.token is None
        assert ops.activity_calls == 2
        if fault == 'postcommit-eof': assert ops.bootstraps == 0
        elif fault == 'readiness': assert result['phase'] == 'INSPECTION_REQUIRED' and ops.bootstraps == 1
        else: assert result['phase'] == 'FINISHED' and ops.bootstraps == 1


def test_native_owner_identity_compares_audit_version_and_microseconds(tmp_path, monkeypatch):
    old = controller.legacy(); expected = kernel(); actual = deepcopy(expected)
    body = dict(scope=dict(activity=dict(expected_owner=expected)))
    observed = dict(state='running', app_root=str(controller.PARENT / 'app'), pid=expected['pid'])
    monkeypatch.setattr(old, 'signal_identity', lambda pid:actual)
    monkeypatch.setattr(old, 'same_process', lambda token:True)
    assert controller.owner_for_transition(body, {}, 'activate', observed, None) == actual
    for key in ('start_usec', 'pid_version', 'audit_token'):
        actual = deepcopy(expected)
        actual[key] = [8]*8 if key == 'audit_token' else actual[key]+1
        with pytest.raises(ValueError, match='KERNEL_OWNER_DRIFT'):
            controller.owner_for_transition(body, {}, 'activate', observed, None)


def test_rollback_requires_this_activation_new_owner_or_strict_absence(tmp_path, monkeypatch):
    old = controller.legacy(); token = kernel(10002)
    monkeypatch.setattr(old, 'signal_identity', lambda pid:token)
    monkeypatch.setattr(old, 'same_process', lambda value:True)
    body = dict(helper_sha256='helper', plists=dict(candidate_plist_sha256='candidate'))
    binding = dict(path='/private/binding', sha256='bound')
    receipt = dict(schema=controller.RESULT_SCHEMA, direction='activate', state='ACTIVATED', binding=binding,
        helper_sha256='helper', after_plist_sha256='candidate', runtime_kernel_identity=token)
    path = tmp_path / 'result.json'
    def save():
        path.write_text(json.dumps(receipt)); return controller.pin(path)
    observed = dict(state='running', pid=token['pid'], app_root=str(controller.CANDIDATE / 'app'))
    assert controller.owner_for_transition(body, binding, 'rollback', observed, save()) == token
    absent = dict(state='absent')
    with pytest.raises(ValueError, match='ABSENT_ROLLBACK_PROOF'):
        controller.owner_for_transition(body, binding, 'rollback', absent, save())
    receipt.update(state='FAILED_REQUIRES_INSPECTION', committed=True, named_job_absent=True,
        runtime_readback=absent, current_runtime_readback=absent)
    assert controller.owner_for_transition(body, binding, 'rollback', absent, save()) is None
    receipt['binding'] = dict(path='/other', sha256='wrong')
    with pytest.raises(ValueError, match='ROLLBACK_RECEIPT_BINDING'):
        controller.owner_for_transition(body, binding, 'rollback', observed, save())


@pytest.mark.parametrize('boundary', ['finish', 'precommit-eof', 'postcommit-eof', 'busy'])
def test_real_native_child_intent_and_existing_pipe_protocol(tmp_path, boundary):
    """The actual new CLI parser/intent/child executes the real old guardian.

    Owner is necessarily None. Protocol-only Ops cannot send a real signal,
    launchctl command, acquire a live lock, or write outside this private root.
    """
    root = tmp_path / ('protocol-' + boundary); root.mkdir()
    assert root.is_relative_to(controller.PRIVATE)
    intent = dict(schema=controller.INTENT_SCHEMA, mode='PROTOCOL_ONLY', controller_pid=os.getpid(), owner_token=None,
        protocol_root=str(root), journal=str(root/'journal.json'), receipt_path=str(root/'receipt.json'), busy=boundary == 'busy')
    path = root / 'intent.json'; path.write_text(json.dumps(intent))
    child = subprocess.Popen([sys.executable, '-B', str(SOURCE), '_guardian', str(path), controller.sha(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    old = controller.legacy()
    def event(name):
        value = old.read_control(child.stdout, 10)
        assert value and value['event'] == name, value
        return value
    try:
        ack = event('OWNED'); assert ack['guardian_pid'] == child.pid
        old.emit_control(child.stdin, dict(action='FREEZE'))
        if boundary == 'busy': event('ABORTED_PRECOMMIT')
        else:
            event('FROZEN_IDLE')
            if boundary != 'precommit-eof':
                old.emit_control(child.stdin, dict(action='COMMIT')); event('BOOTOUT_COMMITTED'); event('OLD_OWNER_EXITED')
                if boundary == 'finish': old.emit_control(child.stdin, dict(action='START')); event('FINISHED')
        child.stdin.close(); child.wait(timeout=10)
        assert child.returncode == 0, child.stderr.read()
        result = json.loads((root/'journal.json').read_bytes())
        assert result['controller_pid'] == os.getpid() and result['owner_token'] is None
        assert (root/'bootstrap.json').exists() == (boundary == 'finish')
        if boundary == 'finish': assert json.loads((root/'bootstrap.json').read_bytes())['count'] == 1
    finally:
        if not child.stdin.closed: child.stdin.close()
        child.wait(timeout=10)
        child.stdout.close(); child.stderr.close()


def test_protocol_mode_cannot_accept_real_owner():
    with pytest.raises(ValueError, match='PROTOCOL_CANNOT_OWN_PROCESS'):
        controller.ProtocolOnlyOps(dict(mode='PROTOCOL_ONLY', owner_token=kernel()))


def test_existing_activity_scanner_blocks_workbench_pdf_and_dispatch(tmp_path):
    old = controller.legacy()
    workbench = tmp_path / 'manager_workbench'; (workbench/'attempts').mkdir(parents=True)
    (workbench/'attempts/work.json').write_text(json.dumps(dict(state='RUNNING')))
    data = tmp_path/'data'; pdf = data/'external_sources/zsxq_hourly/zsxq_pdf_ingestion_index.json'
    pdf.parent.mkdir(parents=True)
    pdf.write_text(json.dumps(dict(schema_version='v4.zsxq_pdf_ingestion_index.v1', documents=dict(one=dict(engine_runs=dict(first=dict(status='PROCESSING')))))))
    ledger = tmp_path/'ledger'; claims=ledger/'claims/live'; claims.mkdir(parents=True)
    (claims/'one.json').write_text(json.dumps(dict(schema_version='v3_5.dispatch_claim.v1', mode='LIVE',
        business_date='20261025', slot='hourly', run_id='one', pid=99999)))
    from types import SimpleNamespace
    def runner(argv, **kwargs):
        assert argv[:2] == ['/bin/ps', '-p']
        return SimpleNamespace(returncode=0, stdout='99999\n')
    result=old.activity_snapshot(dict(role='scheduler', activity=dict(workbench_root=str(workbench), data_root=str(data), dispatcher_root=str(ledger))), runner)
    assert set(result['busy_work']) == {str(workbench/'attempts/work.json'), 'PDF_PROCESSING', 'DISPATCH_IN_FLIGHT'}


def test_native_commit_accepts_stopped_status_but_not_audit_drift(monkeypatch):
    from types import SimpleNamespace
    token=kernel(); current=deepcopy(token); current['status']=4
    ops=controller.NativeGuardianOps.__new__(controller.NativeGuardianOps)
    ops.intent=dict(binding={}, authority={}, owner_token=token)
    ops.direction='activate'; ops.body={}; ops.expected='pinned'; ops.pointer=Path('/not-opened')
    ops.lifecycle=SimpleNamespace(identity=lambda:dict(state='running'))
    monkeypatch.setattr(controller, 'verify_binding', lambda value:ops.body)
    monkeypatch.setattr(controller, 'execution_authority', lambda *args:None)
    real_sha=controller.sha
    monkeypatch.setattr(controller, 'sha', lambda path:'pinned' if path == ops.pointer else real_sha(path))
    monkeypatch.setattr(controller, 'owner_for_transition', lambda *args:current)
    ops.verify_before_freeze()  # Kernel status changes from RUNNING to STOPPED.
    current['pid_version'] += 1
    with pytest.raises(ValueError, match='OWNER_TOKEN_DRIFT'): ops.verify_before_freeze()


def test_native_prepare_writes_only_private_binding_without_acquiring_guards(tmp_path, monkeypatch):
    from types import SimpleNamespace
    old = controller.legacy()
    parent, candidate = tmp_path/'parent', tmp_path/'candidate'
    for root in (parent, candidate):
        for relative in old.ADMISSION_FILES['scheduler']:
            target=root/'app'/relative; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('retained-source\n')
        (root/'app/v4/manager_workbench/store.py').write_text('from pathlib import Path\nclass WorkbenchStore:\n def __init__(self,state_root):\n  self.root = Path(state_root) / "manager_workbench"\n')
    config=tmp_path/'config.json'; config.write_text(json.dumps(dict(state_root=str(tmp_path/'state'))))
    live=tmp_path/'scheduler.plist'
    live.write_bytes(plistlib.dumps(dict(WorkingDirectory=str(parent/'app'),
        ProgramArguments=['/bin/bash', str(parent/'app/ops/launch_v35_macos_scheduler.sh')],
        EnvironmentVariables=dict(PYTHONPATH='/retained', V4_MANAGER_WORKBENCH_CONFIG_PATH=str(config),
            V35_DATA_ROOT=str(tmp_path/'data'), V35_DISPATCH_LEDGER_ROOT=str(tmp_path/'dispatch'),
            V35_RESEARCH_PANEL_A_DATA_ROOT=str(tmp_path/'a-owner')))))
    before=live.read_bytes()
    monkeypatch.setattr(controller, 'PARENT', parent); monkeypatch.setattr(controller, 'CANDIDATE', candidate)
    monkeypatch.setattr(controller, 'LIVE', live); monkeypatch.setattr(controller, 'PLIST_SHA', controller.sha(live))
    monkeypatch.setattr(controller, 'PRIVATE', tmp_path)
    monkeypatch.setattr(controller, 'native_product', lambda *args:{})
    monkeypatch.setattr(controller, 'current_candidate_inventory', lambda *args:None)
    monkeypatch.setattr(controller, 'lifecycle_review', lambda *args:None)
    monkeypatch.setattr(controller, 'checked_protected', lambda *args:dict(python='/retained/python', binary_sha256='binary', source_identity_refs=[]))
    monkeypatch.setattr(old, 'LaunchctlLifecycle', lambda scope:SimpleNamespace(identity=lambda:dict(state='running', app_root=str(parent/'app'), pid=10001)))
    monkeypatch.setattr(old, 'signal_identity', lambda pid:kernel(pid))
    monkeypatch.setattr(old, 'same_process', lambda token:True)
    monkeypatch.setattr(old, 'lifecycle_identity', lambda scope:dict(uid=os.getuid(), pid=10001))
    def forbidden(*args, **kwargs): raise AssertionError('prepare must not acquire locks/signal/spawn')
    monkeypatch.setattr(old, 'release_guards', forbidden)
    monkeypatch.setattr(old, 'signal_exact_identity', forbidden)
    monkeypatch.setattr(controller.subprocess, 'Popen', forbidden)
    path=tmp_path/'spec.json'; path.write_text(json.dumps(dict(schema='v4.us_mapping.native_lifecycle_spec.v1',
        lifecycle_review={}, native_prepared={}, candidate_review={}, protected_owner_config={}, expected_parent_pid=10001, existing_kernel_locks=[])))
    result=controller.prepare(controller.pin(path), tmp_path/'prepared')
    binding=controller.read_pin(result)
    assert binding['schema'] == controller.BINDING_SCHEMA and 'scope_path' not in binding
    assert live.read_bytes() == before
    assert set((tmp_path/'prepared').iterdir()) == {tmp_path/'prepared'/name for name in ['BINDING.json','parent.plist','candidate.plist']}
    assert all(len(rows) == 17 for rows in binding['scope']['activity']['admission_files'].values())


def test_execution_authority_pins_binding_action_and_review(tmp_path):
    binding=dict(path='/private/binding', sha256='binding')
    body=dict(helper_sha256='reviewed', lifecycle_review=dict(path='/review', sha256='review'))
    value=dict(schema='v4.us_mapping.native_execution_authority.v1', action='activate', binding=binding,
        helper_sha256=body['helper_sha256'], lifecycle_review=body['lifecycle_review'])
    path=tmp_path/'authority.json'; path.write_text(json.dumps(value))
    assert controller.execution_authority(controller.pin(path), binding, body, 'activate') == value
    with pytest.raises(ValueError, match='AUTHORITY_MISMATCH'):
        controller.execution_authority(controller.pin(path), binding, body, 'rollback')
    with pytest.raises(ValueError, match='AUTHORITY_MISMATCH'):
        controller.execution_authority(controller.pin(path), dict(binding, sha256='drift'), body, 'activate')


@pytest.mark.parametrize('case', ['replaced-memory', 'replaced-journal', 'unchanged', 'never-remembered', 'absent', 'unknown'])
def test_native_failed_readiness_receipt_to_exact_owner_rollback(tmp_path, monkeypatch, case):
    """A failure-time observation cannot mint this activation's owner authority."""
    from types import SimpleNamespace
    old = controller.legacy()
    first, replacement = kernel(10001), kernel(10002)
    first_readback = dict(state='running', pid=first['pid'], app_root=str(controller.CANDIDATE / 'app'))
    remembered = dict(runtime_readback=first_readback, runtime_kernel_identity=first)
    if case in {'replaced-memory', 'replaced-journal', 'never-remembered'}:
        current_kernel = replacement
        current = dict(state='running', pid=replacement['pid'], app_root=str(controller.CANDIDATE / 'app'))
    elif case == 'unchanged': current_kernel, current = first, first_readback
    else: current_kernel, current = None, dict(state=case)
    if case == 'never-remembered': remembered = None
    journal = tmp_path/'guardian.json'
    progress = dict(phase='STOPPED_AFTER_COMMIT_NO_BOOTSTRAP', committed=True)
    if remembered is not None: progress['last_observed_new_owner'] = remembered
    journal.write_text(json.dumps(progress))
    pointer=tmp_path/'scheduler.plist'; pointer.write_bytes(b'candidate')
    receipt=tmp_path/'failure.json'
    ops=controller.NativeGuardianOps.__new__(controller.NativeGuardianOps)
    binding=dict(path='/private/native-binding.json', sha256='frozen-binding')
    ops.intent=dict(journal=str(journal), receipt_path=str(receipt), binding=binding)
    ops.direction='activate'; ops.expected='parent'; ops.raw=b'candidate'; ops.pointer=pointer; ops.calls=[]
    ops.last_new_owner=None if case == 'replaced-journal' else remembered
    ops.lifecycle=SimpleNamespace(identity=lambda:deepcopy(current))
    identity_reads=[]
    def identity(pid):
        identity_reads.append(pid)
        assert current_kernel is not None and current_kernel['pid'] == pid
        return deepcopy(current_kernel)
    monkeypatch.setattr(old, 'signal_identity', identity)
    monkeypatch.setattr(old, 'same_process', lambda token:current_kernel is not None and all(token[k] == current_kernel[k] for k in old._OWNER_KEYS))
    def forbidden(*args, **kwargs): raise AssertionError('No real/fake signal or lifecycle command is permitted in receipt regression')
    monkeypatch.setattr(old, 'signal_exact_identity', forbidden)
    monkeypatch.setattr(controller.subprocess, 'Popen', forbidden)
    ops.finish_journal()
    failure=json.loads(receipt.read_bytes())
    assert failure['recorded_new_owner'] == remembered
    assert failure['runtime_kernel_identity'] == (first if remembered is not None else None)
    assert failure['current_runtime_readback'] == current
    assert failure['current_runtime_kernel_identity'] == current_kernel
    body=dict(helper_sha256=controller.sha(SOURCE), plists=dict(candidate_plist_sha256=controller.sha(pointer)))
    if case == 'unchanged':
        assert controller.owner_for_transition(body, binding, 'rollback', current, controller.pin(receipt)) == first
    elif case == 'absent':
        # This remains valid even though the remembered owner readback is running.
        assert failure['runtime_readback']['state'] == 'running' and failure['named_job_absent'] is True
        assert controller.owner_for_transition(body, binding, 'rollback', current, controller.pin(receipt)) is None
    else:
        reason='KERNEL_OWNER_DRIFT' if case.startswith('replaced') else (
            'RECORDED_NEW_OWNER_REQUIRED' if case == 'never-remembered' else 'ROLLBACK_OWNER_ROOT')
        with pytest.raises(ValueError, match=reason):
            controller.owner_for_transition(body, binding, 'rollback', current, controller.pin(receipt))


def test_native_remembered_kernel_authority_cannot_change(tmp_path):
    from types import SimpleNamespace
    ops=controller.NativeGuardianOps.__new__(controller.NativeGuardianOps)
    journal=tmp_path/'journal.json'; journal.write_text(json.dumps(dict(phase='OLD_OWNER_EXITED', committed=True)))
    ops.intent=dict(journal=str(journal)); ops.last_new_owner=None
    first=kernel(10001)
    value=dict(state='running', pid=first['pid'], app_root=str(controller.CANDIDATE / 'app'))
    ops.remember_new_owner(value, first)
    with pytest.raises(ValueError, match='NEW_RUNTIME_KERNEL_OWNER_DRIFT'):
        ops.remember_new_owner(dict(value, pid=10002), kernel(10002))
    assert ops.last_new_owner['runtime_kernel_identity'] == first
    assert json.loads(journal.read_bytes())['last_observed_new_owner']['runtime_kernel_identity'] == first


@pytest.fixture
def actual_guard_stack(tmp_path, monkeypatch):
    """Exact runtime bytes/API composition, only filesystem roots redirected."""
    import fcntl
    import inspect
    import shutil
    native=controller.load_module('guard_compat_native', SOURCE)
    old=native.legacy()
    runtime_parent=controller.PARENT/'app'
    parent, candidate=tmp_path/'parent', tmp_path/'candidate'
    # Normal package import must resolve the actual retained implementation,
    # rather than a cached source module or a fake accepting arbitrary kwargs.
    for name in list(sys.modules):
        if name in {'infrastructure','ops'} or name.startswith(('infrastructure.', 'ops.')):
            monkeypatch.delitem(sys.modules, name)
    relatives=['infrastructure/__init__.py','infrastructure/owned_io.py','infrastructure/interprocess_lock.py',
        'ops/research_panel_qfq.py','ops/research_panel_factor_cache.py',
        'v4/manager_workbench/store.py']
    for root in (parent,candidate):
        for relative in relatives:
            target=root/'app'/relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(runtime_parent/relative, target)
    monkeypatch.syspath_prepend(str(parent/'app'))
    agents=tmp_path/'agents'; agents.mkdir()
    monkeypatch.setattr(old,'LAUNCHAGENTS',agents)
    monkeypatch.setattr(native,'PARENT',parent)
    workbench=tmp_path/'state/manager_workbench'; (workbench/'attempts').mkdir(parents=True)
    cfg=tmp_path/'config.json'; cfg.write_text(json.dumps(dict(state_root=str(workbench.parent))))
    pointer=agents/'com.lexi.v35.scheduler.plist'
    pointer.write_bytes(plistlib.dumps(dict(WorkingDirectory=str(parent/'app'),
        EnvironmentVariables=dict(V4_MANAGER_WORKBENCH_CONFIG_PATH=str(cfg)))))
    release=agents/'.com.lexi.v35.scheduler.release.lock'
    scope=dict(role='scheduler',parent_root=str(parent),candidate_root=str(candidate),plist=dict(path=str(pointer)),
        inventory_tool=dict(path=str(ROOT/'ops/api_release_integration.py'),sha256=native.DEPENDENCIES['ops/api_release_integration.py']),
        dependencies=[native.pin(cfg)],activity=dict(workbench_root=str(workbench),release_lock_path=str(release),
        existing_kernel_locks=[],admission_files={side:{'v4/manager_workbench/store.py':native.sha(root/'app/v4/manager_workbench/store.py')}
            for side,root in [('parent',parent),('candidate',candidate)]}))
    body=dict(scope=scope,qfq_data_root=str(tmp_path/'qfq-data'))
    from infrastructure import interprocess_lock, owned_io
    api=old.inventory_tool(scope['inventory_tool'])
    qfq=native.load_module('actual_qfq_guard_fixture',parent/'app/ops/research_panel_qfq.py')
    assert Path(interprocess_lock.__file__).is_relative_to(tmp_path)
    assert native.sha(interprocess_lock.__file__)==native.sha(runtime_parent/'infrastructure/interprocess_lock.py')
    signature=inspect.signature(interprocess_lock.owned_interprocess_lock)
    assert signature.parameters['timeout_message'].default is inspect.Parameter.empty
    announcement=workbench/'locks'/(hashlib.sha256(api.ANNOUNCEMENT_SUBMIT_LOCK_KEY.encode()).hexdigest()+'.lock')
    qfq_lock=Path(body['qfq_data_root'])/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publish.lock'
    paths=dict(release=release,mutex=Path(str(release)+'.mutex'),announcement=announcement,qfq=qfq_lock)
    report=dict(owned_interprocess_lock=dict(path=interprocess_lock.__file__,sha256=native.sha(interprocess_lock.__file__),
        original_path=str(runtime_parent/'infrastructure/interprocess_lock.py'),signature=str(signature)),
        owned_io=dict(path=owned_io.__file__,sha256=native.sha(owned_io.__file__)),
        announcement=dict(path=api.__file__,sha256=native.sha(api.__file__),signature=str(inspect.signature(api.announcement_flash_cutover_guard))),
        qfq=dict(path=qfq.__file__,sha256=native.sha(qfq.__file__),signature=str(inspect.signature(qfq.publication_lock))),
        roots=str(tmp_path),signal_calls=0,service_calls=0)
    (tmp_path/'actual-guard-identities.json').write_text(json.dumps(report,indent=2)+'\n')
    def forbidden(*args, **kwargs): raise AssertionError('Real process signals/service calls forbidden in guard fixture')
    monkeypatch.setattr(os,'kill',forbidden)
    monkeypatch.setattr(native.subprocess,'Popen',forbidden)
    def held(path):
        with path.open('r+b') as stream:
            with pytest.raises(BlockingIOError): fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    def free(path):
        with path.open('r+b') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB); fcntl.flock(stream,fcntl.LOCK_UN)
    yield dict(native=native,old=old,body=body,scope=scope,paths=paths,infra=interprocess_lock,api=api,qfq=qfq,held=held,free=free)


@pytest.mark.parametrize('side',['parent','candidate'])
def test_actual_release_ann_qfq_guard_stack_acquires_and_releases(actual_guard_stack,side):
    g=actual_guard_stack
    pointer=Path(g['scope']['plist']['path']); value=plistlib.loads(pointer.read_bytes())
    value['WorkingDirectory']=str(Path(g['scope'][side+'_root'])/'app'); pointer.write_bytes(plistlib.dumps(value))
    with g['native'].guards(g['body']):
        assert g['paths']['release'].is_file()
        for name in ('mutex','announcement','qfq'): g['held'](g['paths'][name])
    assert not g['paths']['release'].exists()
    for name in ('mutex','announcement','qfq'): g['free'](g['paths'][name])


@pytest.mark.parametrize('busy',['release','announcement','qfq'])
def test_actual_guard_stack_busy_unwinds_prior_locks(actual_guard_stack,busy):
    g=actual_guard_stack
    if busy=='release':
        holder=g['infra'].owned_interprocess_lock(g['paths']['release'],timeout_seconds=.1,timeout_message='FIXTURE_BUSY')
        message='SCHEDULER_RELEASE_LOCK_BUSY'
    elif busy=='announcement':
        holder=g['api'].announcement_flash_cutover_guard(Path(g['scope']['activity']['workbench_root']),timeout_seconds=.1)
        message='API_RELEASE_ANNOUNCEMENT_SUBMIT_LOCK_BUSY'
    else:
        holder=g['qfq'].publication_lock(Path(g['body']['qfq_data_root'])); message='QFQ_OWNER_ALREADY_ACTIVE'
    with holder:
        with pytest.raises((ValueError,RuntimeError),match=message):
            with g['native'].guards(g['body']): raise AssertionError('busy composition admitted')
        if busy!='release': assert not g['paths']['release'].exists()
        if busy=='qfq':
            g['free'](g['paths']['mutex']); g['free'](g['paths']['announcement'])
    assert not g['paths']['release'].exists()
    g['free'](g['paths']['mutex'])
    for name in ('announcement','qfq'):
        if g['paths'][name].exists(): g['free'](g['paths'][name])


def test_actual_guard_stack_exception_and_role_path_checks(actual_guard_stack):
    g=actual_guard_stack
    with pytest.raises(RuntimeError,match='inside guard'):
        with g['native'].guards(g['body']): raise RuntimeError('inside guard')
    assert not g['paths']['release'].exists()
    for name in ('mutex','announcement','qfq'): g['free'](g['paths'][name])
    g['scope']['activity']['release_lock_path']=str(g['paths']['release'].with_name('wrong-role.lock'))
    with pytest.raises(ValueError,match='SCHEDULER_RELEASE_LOCK_PATH'):
        with g['native'].guards(g['body']): raise AssertionError('wrong role lock admitted')
    assert not g['paths']['release'].exists()


@pytest.fixture
def authorized_four_fixture(tmp_path,monkeypatch):
    """Unchanged authority/original readers; only metadata I/O roots map to F."""
    import types
    native=controller.load_module('native_four_binding_test',SOURCE)
    readers=native.legacy_recovery()
    actual_path=Path
    pins=deepcopy(native.LEGACY_ACTIVITY_PINS)
    receipt=json.loads(actual_path(pins['receipt']['path']).read_bytes())
    authority=json.loads(actual_path(pins['authority']['path']).read_bytes())
    root=tmp_path/'private-evidence'; root.mkdir(mode=0o700)
    mapping={}
    def copy(source,target):
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(actual_path(source).read_bytes()); target.chmod(actual_path(source).stat().st_mode & 0o777)
        mapping[str(source)]=target
    copy(pins['authority']['path'],tmp_path/'AUTHORIZATION.json')
    copy(pins['receipt']['path'],root/'DISPOSITION.json')
    for row in receipt['records']:
        # Preserve the identity-sensitive filename and HK target parent name.
        source=actual_path(row['path'])
        copy(source,tmp_path/'live'/source.parent.name/source.name)
        copy(row['backup_path'],root/actual_path(row['backup_path']).name)
    def mapped_path(value):
        return mapping.get(str(value),actual_path(value))
    def exact(value,**kwargs): return readers_exact(mapped_path(value),**kwargs)
    readers_exact=readers.exact
    # Clone the existing read_json code with only its filesystem resolver
    # redirected. The fixed authority constants and reader logic stay exact.
    read_json_globals=dict(readers.read_json.__globals__,exact=exact)
    readers.read_json=types.FunctionType(readers.read_json.__code__,read_json_globals,
        readers.read_json.__name__,readers.read_json.__defaults__,readers.read_json.__closure__)
    readers.exact=exact
    monkeypatch.setattr(native,'Path',mapped_path)
    monkeypatch.setattr(native,'legacy_recovery',lambda:readers)
    return dict(native=native,readers=readers,pins=pins,receipt=receipt,authority=authority,mapping=mapping,root=root)


@pytest.mark.parametrize('direction',['activate','rollback'])
def test_authorized_four_bound_into_each_native_execution_direction(authorized_four_fixture,tmp_path,direction):
    g=authorized_four_fixture; native=g['native']; pins=g['pins']
    receipt=native.verify_legacy_activity(pins)
    assert receipt['execution_state']=='UNKNOWN' and receipt['original_records_changed'] is False
    assert receipt['completion_or_idle_proven'] is False
    binding=dict(path='/private/native-binding.json',sha256='native-binding')
    body=dict(helper_sha256='reviewed-native',lifecycle_review=dict(path='/review',sha256='review'),legacy_activity_disposition=pins)
    authority=dict(schema='v4.us_mapping.native_execution_authority.v1',action=direction,binding=binding,
        helper_sha256=body['helper_sha256'],lifecycle_review=body['lifecycle_review'],legacy_activity_disposition=pins)
    path=tmp_path/'native-authority.json'; path.write_text(json.dumps(authority))
    assert native.execution_authority(native.pin(path),binding,body,direction)==authority
    del authority['legacy_activity_disposition']; path.write_text(json.dumps(authority))
    with pytest.raises(ValueError,match='EXECUTION_AUTHORITY_MISMATCH'):
        native.execution_authority(native.pin(path),binding,body,direction)


@pytest.mark.parametrize('drift',['authority-bytes','receipt-bytes','original-bytes','backup-bytes',
    'authority-mode','receipt-mode','original-mode','backup-mode','root-mode'])
def test_authorized_four_rejects_any_exact_metadata_drift(authorized_four_fixture,drift):
    g=authorized_four_fixture; native=g['native']; pins=g['pins']; row=g['receipt']['records'][-1]
    kind,mutation=drift.split('-')
    logical={'authority':pins['authority']['path'],'receipt':pins['receipt']['path'],
        'original':row['path'],'backup':row['backup_path']}
    path=g['root'] if kind=='root' else g['mapping'][logical[kind]]
    if mutation=='mode': path.chmod(0o755 if kind=='root' else 0o640)
    else:
        raw=path.read_bytes(); path.write_bytes(bytes([raw[0]^1])+raw[1:])
    with pytest.raises(ValueError): native.verify_legacy_activity(pins)


def test_authorized_four_original_reader_still_rejects_wrong_task_id(authorized_four_fixture):
    g=authorized_four_fixture
    record=deepcopy(g['receipt']['records'][-1]); record['job_id']='different-task'
    with pytest.raises(ValueError,match='FOUR_WORKBENCH_IDENTITY_DRIFT'):
        g['readers'].original(record)


@pytest.fixture
def authorized_activity_adapter(authorized_four_fixture,monkeypatch):
    g=authorized_four_fixture; native=g['native']; old=native.legacy()
    row=g['receipt']['records'][-1]; target=row['path']
    raw=dict(state='running',pid=10001,app_root=str(controller.PARENT/'app'),activity_sha256='a'*64,
        busy_work=[target,'PDF_PROCESSING','DISPATCH_IN_FLIGHT','ACTIVE_CHILD_PROCESS',
            str(Path(target).with_name('unrelated-new-task.json')),g['receipt']['records'][0]['path']])
    calls=[]
    class CompleteScan:
        def __init__(self,scope): self.scope=scope
        def inspect(self): calls.append('complete-scan'); return deepcopy(raw)
    monkeypatch.setattr(old,'LaunchctlLifecycle',CompleteScan)
    scope=dict(role='scheduler',activity=dict(workbench_root=str(Path(target).parent.parent)))
    return dict(**g,raw=raw,calls=calls,scope=scope,target=target)


def test_native_metadata_adapter_removes_only_authorized_role_path(authorized_activity_adapter):
    g=authorized_activity_adapter
    lifecycle=g['native'].native_lifecycle(g['scope'],g['pins'])
    value=lifecycle.inspect()
    assert g['calls']==['complete-scan']
    assert value['busy_work']==g['raw']['busy_work'][1:]
    assert g['raw']['busy_work'].count(g['target'])==1
    assert value['administratively_disposed_work']==[g['target']]
    assert value['legacy_activity_disposition']==g['pins']
    assert value['legacy_execution_state']=='UNKNOWN' and value['original_records_changed'] is False
    assert value['completion_or_idle_proven'] is False


@pytest.mark.parametrize('fault',['missing','duplicate','wrong-role','wrong-root'])
def test_native_metadata_adapter_refuses_nonexact_scope(authorized_activity_adapter,fault):
    g=authorized_activity_adapter
    if fault=='missing': g['raw']['busy_work'].remove(g['target'])
    elif fault=='duplicate': g['raw']['busy_work'].append(g['target'])
    elif fault=='wrong-role': g['scope']['role']='api'
    else: g['scope']['activity']['workbench_root']='/unrelated/manager_workbench'
    lifecycle=g['native'].native_lifecycle(g['scope'],g['pins'])
    with pytest.raises(ValueError,match='LEGACY_ACTIVITY_ROLE_NOT_EXACT|LEGACY_ACTIVITY_PATH_MISSING_OR_DUPLICATE'):
        lifecycle.inspect()


@pytest.mark.parametrize('field',['authority','receipt','authenticator_sha256'])
def test_native_legacy_binding_rejects_other_unknown_authority(authorized_four_fixture,field):
    g=authorized_four_fixture; pins=deepcopy(g['pins'])
    if field=='authenticator_sha256': pins[field]='0'*64
    else: pins[field]['sha256']='0'*64
    with pytest.raises(ValueError,match='LEGACY_ACTIVITY_PINS_NOT_EXACT'):
        g['native'].verify_legacy_activity(pins)
