"""Explicit, receipt-bound V192 same-day revision; no selector or scheduler.

The two roots are NOT atomic. A durable PREPARED record precedes replay; every
entry checks actual roots. Recovery uses the original local journal only after
checking that it cannot overwrite another pool. No operation runs on import.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import errno
import os
import re
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

APP_ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-calendar-binding-20261021-r1/app')
SHARED_PACKAGE_ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-tdx-conflict-repair-shared-20261015-r4/app/upstreams/v3_shared_data')
DEPENDENCIES = {
    'app/domains/preselection_materializer.py': '8004fcd6c5d9d8a36f6e7380849af42c87ddd2d41b8cb9363a39e31bc632866b',
    'app/infrastructure/preselection_pool_store.py': '5c79a3ab612e04506d6751fd821854ec152e58d234feec18d4dee5e3d531c744',
    'app/infrastructure/preselection_pool_transactions.py': '22cca047d8d2da3ec9b1c4d3d18fd09026887ee48a95868757bfc598d094d58d',
    'app/infrastructure/preselection_pool_readers.py': '7b153abba65eb2387a3f2d87c96466ab5cf38aa331f51b4661940f4c9149c9cc',
    'app/infrastructure/formula_generation.py': '0904603912d6257cb02f41dfaf66c080e2f682e690b1c1901a86a7bafe1e74f0',
    'app/infrastructure/isolated_package_loader.py': 'c714d4b95c03da061f592e076cd12188dbeefcd9f0fae7aeaae18c0450e915eb',
    'shared/shared_data/v192_selector.py': '3654d9dd77887714fefb9a938a00277e0ab8215fbebf367436a0a6710205e008',
    'shared/shared_data/store.py': '87042083dad178442c75386e59ae4b2fd9bab0a3c92b5c3a090ddb90e6b52a16',
    'shared/shared_data/allowlist.py': 'a5e307f15416fe422a0ad36f60d6996f6a3f74753581dc589ef93149178dd206',
    'shared/shared_data/collectors.py': 'f59dc7f70939a033fcde715aef33c5e063cb10b20c98caf17ee3a42c4884c159',
}
POOL = 'a_d1_premarket_pool'
ROLE = 'A_SHARE_V192_PREMARKET_POOL_V3'
SIGNAL = '20261020'
TARGET = '20261021'
IDENTITY_KEYS = ('run_id', 'artifact_sha256', 'manifest_sha256', 'receipt_sha256',
                 'artifact_relative', 'manifest_relative', 'receipt_relative')
FLAGS = {'research_only': True, 'production_allowed': False,
         'buy_gate_updated': False, 'orders_sent': False}
LOCK_RECOVERY_BUDGET_SECONDS = 40.0


class RevisionStop(ValueError):
    """A failed boundary; do not automatically retry a changed identity."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RevisionStop(reason)


def regular(path: Path) -> Path:
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'STOP_NONEXACT_PATH')
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'STOP_SYMLINK')
    require(path.is_file(), 'STOP_FILE_MISSING:' + str(path))
    return path


def bound_json(evidence: Mapping[str, Any]) -> dict[str, Any]:
    path = regular(Path(evidence['path']))
    require(file_sha(path) == evidence['sha256'], 'STOP_BOUND_FILE_DRIFT')
    value = json.loads(path.read_bytes())
    require(isinstance(value, dict), 'STOP_BOUND_JSON_TYPE')
    return value


def identity(value: Mapping[str, Any]) -> dict[str, str]:
    require(all(isinstance(value.get(k), str) and value[k] for k in IDENTITY_KEYS),
            'STOP_INCOMPLETE_SHARED_IDENTITY')
    result = {k: value[k] for k in IDENTITY_KEYS}
    require(all(re.fullmatch('[0-9a-f]{64}', result[k]) for k in IDENTITY_KEYS if k.endswith('sha256')),
            'STOP_INVALID_SHARED_SHA')
    prefix = f'runs/{TARGET}/{ROLE}/{result["run_id"]}'
    for key, leaf in (('artifact_relative', 'artifact.csv'), ('manifest_relative', 'manifest.json'),
                      ('receipt_relative', 'receipt.json')):
        require(result[key] == f'{prefix}/{leaf}', 'STOP_SHARED_RELATIVE_PATH')
    require(re.fullmatch('[A-Za-z0-9_-]+', result['run_id']) is not None, 'STOP_RUN_ID')
    return result


class Runtime:
    """Use the exact release, rejecting an already imported workspace version.

    Call from a dedicated operation/test process. Data roots are supplied by the
    binding; dependency roots are fixed and never inferred from cwd/PYTHONPATH.
    """
    def __init__(self) -> None:
        self.check_dependencies()
        sys.path.insert(0, str(APP_ROOT))
        try:
            self.local_module = importlib.import_module('infrastructure.preselection_pool_store')
            self.materializer = importlib.import_module('domains.preselection_materializer')
            self.generation = importlib.import_module('infrastructure.formula_generation')
            loader = importlib.import_module('infrastructure.isolated_package_loader')
            self.lock = importlib.import_module('infrastructure.interprocess_lock').owned_interprocess_lock
            for key in DEPENDENCIES:
                if key.startswith('app/'):
                    mod = importlib.import_module(key[4:-3].replace('/', '.'))
                    require(Path(mod.__file__).resolve() == (APP_ROOT / key[4:]).resolve(),
                            'STOP_IMPORTED_RUNTIME_DRIFT')
            self.selector = loader.load_isolated_package_module(
                SHARED_PACKAGE_ROOT, package_directory='shared_data',
                module_leaf='v192_selector', namespace_prefix='v35_shared_data')
        finally:
            sys.path.remove(str(APP_ROOT))
        self.check_dependencies()

    @staticmethod
    def check_dependencies() -> None:
        for key, expected in DEPENDENCIES.items():
            root, relative = key.split('/', 1)
            path = (APP_ROOT if root == 'app' else SHARED_PACKAGE_ROOT) / relative
            require(file_sha(regular(path)) == expected, 'STOP_DEPENDENCY_DRIFT:' + key)


class SameDayRevision:
    def __init__(self, binding: Mapping[str, Any], *, local_store: Any, runtime: Runtime):
        self.b = json.loads(canonical(binding))
        self.local = local_store
        self.rt = runtime
        self.s = runtime.selector
        self.binding_sha = digest(self.b)
        require(self.b.get('schema') == 'v192.same_day_revision.binding.v1', 'STOP_BINDING_SCHEMA')
        require(self.b.get('revision_mode') == 'SAME_DAY_WHOLE_POOL_REVISION', 'STOP_EXPLICIT_REVISION_REQUIRED')
        require(self.b.get('signal_date') == SIGNAL and self.b.get('target_date') == TARGET,
                'STOP_DATE_BOUNDARY')
        operation_id = self.b.get('operation_id', '')
        require(isinstance(operation_id, str) and re.fullmatch('[A-Za-z0-9_-]{1,100}', operation_id) is not None,
                'STOP_OPERATION_ID')
        require(self.b.get('dependencies') == DEPENDENCIES, 'STOP_DEPENDENCY_BINDING')
        require(self.b.get('safety') == FLAGS, 'STOP_SAFETY_BINDING')
        for root in (self.b['local_root'], self.b['shared_root'], self.b['candidate']['store_root']):
            path = Path(root)
            require(path.is_absolute() and '..' not in path.parts and path.is_dir()
                    and not any(p.is_symlink() for p in (path, *path.parents)), 'STOP_STORE_ROOT')
        require(Path(self.b['local_root']).resolve() == self.local.root.resolve(), 'STOP_LOCAL_ROOT')
        require(type(self.local) is runtime.local_module.PreselectionPoolStore, 'STOP_LOCAL_STORE_TYPE')
        self._check_gate_binding()
        self.old_shared = identity(self.b['expected_previous_shared'])
        self.candidate_id = identity(self.b['candidate']['identity'])
        self.record = f'v192_same_day_revisions/{operation_id}.json'
        self.lock_claim_relative = f'v192_same_day_revisions/{operation_id}.shared-lock.json'
        self.shared = self.s._V192ManifestStore(Path(self.b['shared_root']), role=ROLE)
        self.shared_io = runtime.local_module.SafeRoot(self.shared.root)
        self.shared_store_module = importlib.import_module(self.s.SafeRootStore.__module__)
        require(self.shared_store_module.STORE_LOCK_TIMEOUT_SECONDS == 10.0
                and self.shared_store_module.STORE_LOCK_STALE_SECONDS == 30.0,
                'STOP_ORIGINAL_LOCK_CONSTANT_DRIFT')
        require(self.shared.root.resolve() != Path(self.b['candidate']['store_root']).resolve(), 'STOP_CANDIDATE_IS_LIVE')
        require(self.shared.root.resolve() != self.local.root.resolve(), 'STOP_ROOT_ALIAS')

    def _check_gate_binding(self) -> None:
        # Preserve the existing caller's gate semantics, including its explicit
        # default None/False. Never install a new permit or lower an enabled gate.
        gate = self.local._write_gate_context
        require(gate is None or isinstance(gate, self.rt.local_module.StoreGateContext), 'STOP_INVALID_WRITE_GATE_CONTEXT')
        context = None if gate is None else dict(control_dir=str(gate.control_dir),
                expected_permit_sha256=gate.expected_permit_sha256, expected_owner_id=gate.expected_owner_id,
                expected_release_sha256=gate.expected_release_sha256, expected_root=str(gate.expected_root))
        require(self.b.get('write_gate') == dict(require_write_gate_context=self.local._require_write_gate_context,
                                               context=context),
                'STOP_WRITE_GATE_BINDING')

    def _admit(self) -> Any:
        self.rt.check_dependencies()
        proof = bound_json(self.b['independent_pass'])
        require(proof.get('schema') == 'v192.whole_pool_independent_pass.v1'
                and proof.get('decision') == 'PASS' and proof.get('scope') == 'WHOLE_POOL'
                and proof.get('independent') is True and proof.get('partial') is False,
                'STOP_WHOLE_POOL_INDEPENDENT_PASS_REQUIRED')
        require(isinstance(proof.get('writer'), str) and proof['writer']
                and isinstance(proof.get('reviewer'), str) and proof['reviewer']
                and proof['reviewer'] != proof['writer'], 'STOP_INDEPENDENT_REVIEWER')
        admission = {k: self.b[k] for k in ('candidate', 'generation', 'source_panel',
                     'universe', 'dependencies', 'signal_date', 'target_date', 'safety')}
        require(proof.get('binding') == admission, 'STOP_PASS_SCOPE_DRIFT')
        universe = self.b['universe']
        require(universe.get('scope') == 'WHOLE_POOL' and universe.get('signal_date') == SIGNAL
                and isinstance(universe.get('key_count'), int) and not isinstance(universe['key_count'], bool)
                and universe['key_count'] > 0
                and re.fullmatch('[0-9a-f]{64}', str(universe.get('key_sha256'))) is not None,
                'STOP_UNIVERSE_SUMMARY')
        producer = bound_json(universe['producer_evidence'])
        # Field paths name existing producer metadata. No universe is computed here.
        for key in ('signal_date', 'key_count', 'key_sha256'):
            value: Any = producer
            parts = universe['producer_fields'][key]
            require(isinstance(parts, list) and parts and all(isinstance(x, str) for x in parts),
                    'STOP_UNIVERSE_FIELD_PATH')
            for part in parts:
                require(isinstance(value, dict) and part in value, 'STOP_UNIVERSE_FIELD_MISSING')
                value = value[part]
            require(type(value) is type(universe[key]) and value == universe[key], 'STOP_PRODUCER_UNIVERSE_DRIFT')
        g = self.b['generation']
        bound_json({'path': g['pointer'], 'sha256': g['pointer_sha256']})
        generation = self.rt.generation.read_formula_generation(
            g['pointer'], expected_target_date=SIGNAL, require_source=True)
        require(generation['sha256'] == g['pointer_sha256'] and generation['generation_id'] == g['generation_id'],
                'STOP_GENERATION_DRIFT')
        panel = self.b['source_panel']
        panel_path = regular(Path(panel['path']))
        require(file_sha(panel_path) == panel['sha256'], 'STOP_SOURCE_PANEL_DRIFT')
        role = panel['generation_role']
        require(role in ('selector', 'selector_source'), 'STOP_GENERATION_PANEL_ROLE')
        require(Path(generation[role]).resolve() == panel_path.resolve()
                and generation[role + '_evidence']['sha256'] == panel['sha256'], 'STOP_PANEL_GENERATION_BINDING')
        candidate = self.s.read_verified_v192_pool(
            self.b['candidate']['store_root'], target_date=TARGET, expected_signal_date=SIGNAL)
        require(identity(candidate.run.verification) == self.candidate_id, 'STOP_CANDIDATE_DRIFT')
        require(candidate.run.verification['status'] == 'READY' and len(candidate.rows) > 0,
                'STOP_NONEMPTY_READY_REQUIRED')
        manifest = candidate.run.manifest
        require(manifest['provenance']['panel_sha256'] == panel['sha256'], 'STOP_CANDIDATE_PANEL_BINDING')
        require(manifest.get('source_id') == 'fmla04_v192_frozen_selector'
                and manifest.get('stage_id') == self.s.V192_STAGE_ID
                and manifest.get('collector') == 'file_replay' and manifest.get('market') == 'A_SHARE'
                and manifest.get('cutoff_at') == '17:30:00', 'STOP_CANDIDATE_SOURCE_SPEC')
        source = regular(Path(self.b['candidate']['store_root']) / self.candidate_id['artifact_relative'])
        required_columns = ('trade_date', 'signal_date', 'target_date', 'bar_time', 'ts_code',
                            'candidate_role', 'multi_head_final_role', 'entry_pool',
                            *self.s.V192_ENTRY_FIELDS, *self.s.V192_INTERMEDIATE_FIELDS,
                            'formula_source', 'rank_usage_boundary', 'formal_recommendation_allowed')
        spec = self.s.SourceSpec(
            source_id=manifest['source_id'], role=ROLE, trade_date=TARGET, market=manifest['market'],
            stages=(manifest['stage_id'],), cutoff_at=manifest['cutoff_at'], source_path=source,
            required_columns=required_columns, expected_input_sha256=self.candidate_id['artifact_sha256'],
            expected_row_count=candidate.run.verification['row_count'], provenance=dict(manifest['provenance']))
        self.shared.allowlist = self.s.AllowlistRegistry({(TARGET, ROLE): (spec,)})
        idem = self.s.sha256_json(dict(owner='v3_shared_data', source_id=spec.source_id,
                                    trade_date=TARGET, role=ROLE, stage_id=self.s.V192_STAGE_ID,
                                    input_sha256=self.candidate_id['artifact_sha256']))
        self.expected_run = f'{TARGET}-{ROLE.lower().replace("_", "-")}-{idem[:12]}'
        require(self.expected_run == self.candidate_id['run_id']
                and self.expected_run != self.old_shared['run_id'], 'STOP_DETERMINISTIC_RUN_ID')
        self.candidate = candidate
        return candidate

    def _shared_state(self) -> tuple[dict[str, Any], dict[str, str]]:
        result = self.shared.verify_latest(TARGET, ROLE)
        actual = identity(result['verified'])
        require(identity(result['latest']) == actual, 'STOP_SHARED_LATEST_TRIO_DRIFT')
        return result['latest'], actual

    def _input_fence(self) -> None:
        """Recheck frozen external bytes before each publication boundary."""
        self._check_gate_binding()
        self.rt.check_dependencies()
        bound_json(self.b['independent_pass'])
        bound_json(self.b['universe']['producer_evidence'])
        g = self.b['generation']
        bound_json({'path': g['pointer'], 'sha256': g['pointer_sha256']})
        panel = self.b['source_panel']
        require(file_sha(regular(Path(panel['path']))) == panel['sha256'], 'STOP_SOURCE_PANEL_DRIFT')
        candidate = self.s.read_verified_v192_pool(self.b['candidate']['store_root'],
            target_date=TARGET, expected_signal_date=SIGNAL)
        require(identity(candidate.run.verification) == self.candidate_id, 'STOP_CANDIDATE_DRIFT')

    def _owned_new_run(self) -> dict[str, str]:
        verified = self.shared.verify_run(TARGET, ROLE, self.expected_run, expected_owner='v3_shared_data')
        new = identity(verified)
        manifest = self.shared._read_json(self.shared.root / new['manifest_relative'])
        receipt = self.shared._read_json(self.shared.root / new['receipt_relative'])
        require(verified['status'] == 'READY' and new['artifact_sha256'] == self.candidate_id['artifact_sha256']
                and receipt.get('supersedes') == self.old_shared and receipt.get('historical_backfill') is True
                and manifest.get('provenance') == self.candidate.run.manifest['provenance']
                and manifest.get('source_id') == 'fmla04_v192_frozen_selector'
                and manifest.get('stage_id') == self.s.V192_STAGE_ID and manifest.get('role') == ROLE,
                'STOP_NEW_RUN_OWNERSHIP')
        supersession = self.shared._read_json(self.shared.root / receipt['supersession_relative'])
        require(supersession.get('previous') == self.old_shared and supersession.get('replacement') == new,
                'STOP_SUPERSESSION_DRIFT')
        return new

    def _local_expected(self, snapshot: Mapping[str, Any]) -> None:
        expected = self.b['expected_previous_local']
        require(snapshot['artifact_sha256'] == expected['artifact_sha256']
                and snapshot['receipt_raw_sha256'] == expected['receipt_raw_sha256']
                and snapshot['artifact_relative'] == expected['artifact_relative']
                and snapshot['receipt_relative'] == expected['receipt_relative'], 'STOP_LOCAL_A_CAS')
        payload = snapshot['artifact']
        require(payload.get('source_role') == 'SHARED_VERIFIED_V192'
                and payload.get('artifact_role') == ROLE and payload.get('artifact_version') == 'V3'
                and payload.get('source_run_id') == self.old_shared['run_id']
                and payload.get('source_sha256') == self.old_shared['artifact_sha256']
                and payload.get('source_path') == self.old_shared['artifact_relative']
                and payload.get('signal_date') == SIGNAL and payload.get('target_date') == TARGET,
                'STOP_LOCAL_OLD_SHARED_BINDING')

    def _save(self, state: dict[str, Any], phase: str) -> None:
        state['phase'] = phase
        self.local._write(self.record, state)

    def _shared_lock_snapshot(self) -> dict[str, Any] | None:
        """Read one exact original PID/token lock through a bound directory fd."""
        with self.shared_io.directory() as parent:
            try:
                fd = os.open(self.shared.lock_path.name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except FileNotFoundError:
                return None
            try:
                meta = os.fstat(fd)
                require(stat.S_ISREG(meta.st_mode) and meta.st_size <= 128, 'STOP_SHARED_LOCK_UNKNOWN_OWNER')
                raw = os.read(fd, 129)
                try:
                    visible = os.stat(self.shared.lock_path.name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError as error:
                    raise RevisionStop('STOP_SHARED_LOCK_REPLACED') from error
                require((meta.st_dev, meta.st_ino) == (visible.st_dev, visible.st_ino),
                        'STOP_SHARED_LOCK_REPLACED')
                match = re.fullmatch(rb'([1-9][0-9]{0,18}):([0-9a-f]{32})', raw)
                require(match is not None, 'STOP_SHARED_LOCK_UNKNOWN_OWNER')
                root = os.fstat(parent)
                return dict(token=raw.decode('ascii'), pid=int(match[1]), dev=meta.st_dev, ino=meta.st_ino,
                            mtime_ns=meta.st_mtime_ns, ctime_ns=meta.st_ctime_ns,
                            root_dev=root.st_dev, root_ino=root.st_ino)
            finally:
                os.close(fd)

    def _lock_claim(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        return dict(schema='v192.same_day_revision.shared_lock_claim.v1', binding_sha256=self.binding_sha,
            operation_id=self.b['operation_id'], local_root=str(self.local.root), shared_root=str(self.shared.root),
            signal_date=SIGNAL, target_date=TARGET, expected_run_id=self.expected_run,
            expected_previous_shared=self.old_shared, owner=dict(snapshot))

    def _read_lock_claim(self) -> dict[str, Any] | None:
        try:
            claim = self.local._read(self.lock_claim_relative)
        except FileNotFoundError:
            return None
        require(isinstance(claim, dict) and isinstance(claim.get('owner'), dict)
                and claim == self._lock_claim(claim['owner']), 'STOP_SHARED_LOCK_CLAIM_DRIFT')
        return claim

    @staticmethod
    def _require_dead_pid(pid: int) -> None:
        # ESRCH alone proves death. Reused PIDs, EPERM and unknown errors stop.
        require(pid != os.getpid(), 'STOP_SHARED_LOCK_OWNER_NOT_DEAD')
        try:
            os.kill(pid, 0)
        except OSError as error:
            require(error.errno == errno.ESRCH, 'STOP_SHARED_LOCK_OWNER_NOT_DEAD')
        else:
            raise RevisionStop('STOP_SHARED_LOCK_OWNER_NOT_DEAD')

    def _wait_for_original_shared_lock(self, claim: Mapping[str, Any] | None, *, deadline: float) -> bool:
        """Wait only for our dead owner to reach the existing stale window.

        No shared lock deletion occurs here. The original implementation owns
        stale handling and O_EXCL acquisition; its constants remain unchanged.
        A private mutex is deliberately not treated as covering legacy writers.
        """
        recovering = False
        while True:
            observed = self._shared_lock_snapshot()
            if observed is None:
                require(deadline - time.monotonic() >= self.shared_store_module.STORE_LOCK_TIMEOUT_SECONDS,
                        'STOP_SHARED_LOCK_RECOVERY_DEADLINE')
                return recovering
            require(claim is not None and observed == claim['owner'], 'STOP_SHARED_LOCK_UNBOUND_OR_REPLACED')
            require(self._load_record() is not None, 'STOP_SHARED_LOCK_WITHOUT_PREPARED')
            self._require_dead_pid(observed['pid'])
            recovering = True
            remaining = deadline - time.monotonic()
            # Reserve the original 10-second acquisition timeout. Exhaustion
            # stops before another acquisition attempt or any business replay.
            timeout = self.shared_store_module.STORE_LOCK_TIMEOUT_SECONDS
            require(remaining >= timeout, 'STOP_SHARED_LOCK_RECOVERY_DEADLINE')
            age = time.time() - observed['mtime_ns'] / 1_000_000_000
            require(age >= 0, 'STOP_SHARED_LOCK_CLOCK_UNCERTAIN')
            stale = self.shared_store_module.STORE_LOCK_STALE_SECONDS
            if age > stale:
                return recovering
            delay = min(0.02, stale - age + 0.001, remaining - timeout)
            require(delay > 0, 'STOP_SHARED_LOCK_RECOVERY_DEADLINE')
            time.sleep(delay)

    @contextmanager
    def _shared_lock(self, *, original_lock=None):
        """Original shared lock plus operation-bound acquisition evidence."""
        deadline = time.monotonic() + LOCK_RECOVERY_BUDGET_SECONDS
        prior_claim = self._read_lock_claim()
        recovered = self._wait_for_original_shared_lock(prior_claim, deadline=deadline)
        claim_raw = None
        try:
            with (original_lock or self.shared._lock)():
                require(time.monotonic() <= deadline, 'STOP_SHARED_LOCK_RECOVERY_DEADLINE')
                acquired = self._shared_lock_snapshot()
                require(acquired is not None and acquired['pid'] == os.getpid(), 'STOP_SHARED_LOCK_ACQUISITION_IDENTITY')
                self._check_gate_binding()
                self.local._assert_write_allowed(TARGET, POOL)
                claim_raw = canonical(self._lock_claim(acquired))
                # This control receipt is persisted before business work or a
                # phase save, so os._exit cannot leave an unbound later lock.
                self.local._io.write_bytes(self.lock_claim_relative, claim_raw)
                if recovered:
                    self._input_fence()
                require(self._shared_lock_snapshot() == acquired, 'STOP_SHARED_LOCK_REPLACED')
                yield
        except self.shared_store_module.LockTimeoutError as error:
            raise RevisionStop('STOP_SHARED_LOCK_ORIGINAL_TIMEOUT') from error
        finally:
            # The original context releases its own token first. A surviving
            # claim after process exit is evidence; unknown shared locks never
            # trigger deletion here. Local import lock serializes this control file.
            if claim_raw is not None and self._shared_lock_snapshot() is None:
                self.local._io.unlink_if_same(self.lock_claim_relative, claim_raw)

    def _load_record(self) -> dict[str, Any] | None:
        try:
            state = self.local._read(self.record)
        except FileNotFoundError:
            return None
        require(state.get('schema') == 'v192.same_day_revision.operation.v1'
                and state.get('binding_sha256') == self.binding_sha
                and state.get('expected_run_id') == self.expected_run, 'STOP_OPERATION_RECEIPT_DRIFT')
        old = state['old_local']
        require(digest(old['artifact']) == self.b['expected_previous_local']['artifact_sha256']
                and digest(old['receipt']) == self.b['expected_previous_local']['receipt_raw_sha256']
                and identity(state['old_shared_entry']) == self.old_shared, 'STOP_OPERATION_PREIMAGE_DRIFT')
        return state

    def _pending_guard(self, state: Mapping[str, Any] | None) -> None:
        pending_path = self.local._pending_relative(trade_date=TARGET, pool_id=POOL)
        base = self.local.root / 'preselection_pending_commits'
        if base.exists():
            require(not any(p.is_symlink() for p in (base, *base.parents)), 'STOP_PENDING_SYMLINK')
            for path in base.rglob('*'):
                require(not path.is_symlink(), 'STOP_PENDING_SYMLINK')
                if path.is_file():
                    require(path == self.local.root / pending_path, 'STOP_PENDING_OTHER_POOL')
        if not self.local._path(pending_path).exists():
            return
        require(state is not None, 'STOP_UNOWNED_A_PENDING')
        pending = self.local._read(pending_path)
        require(pending.get('schema_version') == 'v4.preselection_pending_commit.v1'
                and pending.get('trade_date') == TARGET and pending.get('pool_id') == POOL,
                'STOP_PENDING_IDENTITY')
        old = self.local._read_pending_side_unlocked(pending, 'old')
        new = self.local._read_pending_side_unlocked(pending, 'new')
        require(old['manifest'].get(POOL) == old['artifact_sha256']
                and new['manifest'].get(POOL) == new['artifact_sha256'], 'STOP_PENDING_MANIFEST_A_IDENTITY')
        # A durable record may lag the shared commit. Derive this identity from
        # the immutable run, rather than trusting the record's phase/new SHA.
        expected_new, _ = self._new_local(self._owned_new_run(), latest=False)
        expected_pair = {self.b['expected_previous_local']['artifact_sha256'], digest(expected_new)}
        require({old['artifact_sha256'], new['artifact_sha256']} == expected_pair
                and None not in expected_pair and len(expected_pair) == 2, 'STOP_UNOWNED_A_PENDING')
        current_manifest = self.local._read(old['manifest_path'])
        others = lambda value: {k: v for k, v in value.items() if k != POOL}
        require(others(current_manifest) == others(old['manifest']) == others(new['manifest']),
                'STOP_PENDING_OTHER_POOL_DRIFT')
        # Only the inherited writer's exact ordered prefixes (and its reverse
        # restoration prefixes) are recoverable. Membership of each SHA alone
        # is insufficient: a later third A must never be reconciled away.
        paths = (old['artifact_path'], old['receipt_path'], old['manifest_path'])
        try:
            actual = tuple(self.local._io.read_bytes(path) for path in paths)
        except FileNotFoundError as error:
            raise RevisionStop('STOP_LOCAL_A_CAS') from error
        before = tuple(canonical(old[key]) for key in ('artifact', 'receipt', 'manifest'))
        after = tuple(canonical(new[key]) for key in ('artifact', 'receipt', 'manifest'))
        allowed = (before, (after[0], before[1], before[2]),
                   (after[0], after[1], before[2]), after)
        require(actual in allowed, 'STOP_LOCAL_A_CAS')
        # Only now may the inherited reconciler write its complete manifest.
        self.local._reconcile_pending_commit_unlocked(TARGET, POOL)

    def _ensure_archives(self, state: dict[str, Any],
                         revisions: tuple[tuple[Mapping[str, Any], Mapping[str, Any]], ...]) -> None:
        """Complete only exact, durably claimed archive halves for this operation.

        The generic archiver remains unchanged. Inspect every existing component
        before writing either the intent or a missing component; unknown bytes
        and unclaimed partial archives are never replaced or adopted.
        """
        expected: dict[str, dict[str, Any]] = {}
        existing: dict[str, bytes | None] = {}
        partial = False
        for payload, main_receipt in revisions:
            sha = digest(payload)
            artifact_path, receipt_path = self.local._revision_relative(TARGET, POOL, sha)
            receipt = dict(schema_version='v4.preselection_recovery_revision_receipt.v1',
                trade_date=TARGET, pool_id=POOL, artifact_path=artifact_path, artifact_sha256=sha,
                source_sha256=payload.get('source_sha256'), source_role=payload.get('source_role'),
                main_receipt=dict(main_receipt), production_allowed=False, buy_gate_updated=False, orders_sent=False)
            expected[artifact_path] = dict(payload)
            expected[receipt_path] = receipt
            pair = []
            for path in (artifact_path, receipt_path):
                try:
                    raw = self.local._io.read_bytes(path)
                except FileNotFoundError:
                    raw = None
                require(raw is None or raw == canonical(expected[path]), 'STOP_ARCHIVE_IDENTITY_DRIFT')
                existing[path] = raw
                pair.append(raw is not None)
            partial = partial or pair[0] != pair[1]
        intent = {path: digest(value) for path, value in expected.items()}
        saved_intent = state.get('local_archive_intent')
        if saved_intent is None:
            require(not partial, 'STOP_UNOWNED_PARTIAL_ARCHIVE')
            state['local_archive_intent'] = intent
            # This exact operation record is durable before the first archive
            # component, including when the process exits between the two writes.
            self._save(state, state['phase'])
        else:
            require(saved_intent == intent, 'STOP_ARCHIVE_INTENT_DRIFT')
        for payload, main_receipt in revisions:
            sha = digest(payload)
            artifact_path, receipt_path = self.local._revision_relative(TARGET, POOL, sha)
            present = (existing[artifact_path] is not None, existing[receipt_path] is not None)
            if present[0] != present[1]:
                missing = receipt_path if present[0] else artifact_path
                self.local._write(missing, expected[missing])
            # Missing pairs use the original implementation; complete pairs
            # use its integrity validation. All partial pairs above were claimed.
            self.local._archive_recovery_revision(TARGET, POOL, sha, payload, main_receipt)

    def _commit_local(self, snapshot: Mapping[str, Any], payload: Mapping[str, Any],
                      receipt: Mapping[str, Any], state: dict[str, Any]) -> None:
        old_sha, new_sha = snapshot['artifact_sha256'], digest(payload)
        self._ensure_archives(state, ((snapshot['artifact'], snapshot['receipt']), (payload, receipt)))
        # The import lock is held. Re-read and merge just the A entry.
        manifest = self.local._read(snapshot['manifest_relative'])
        require(manifest.get(POOL) == old_sha, 'STOP_LOCAL_MANIFEST_A_CAS')
        snapshot = dict(snapshot, manifest=dict(manifest))
        manifest = dict(manifest)
        manifest[POOL] = new_sha
        self.local._commit_main_snapshot(snapshot, payload=payload, receipt=receipt, manifest=manifest)

    def _require_absent_target(self) -> None:
        target = self.shared.runs_root / TARGET / ROLE / self.expected_run
        require(not target.exists() and not target.is_symlink(), 'STOP_RETAINED_TARGET_RUN')

    def _replay_absent_target(self) -> None:
        # The pre-PREPARED check alone has a gap before replay takes its own
        # shared lock. Guard that exact inherited lock acquisition too, without
        # changing a generic class or taking the same shared lock recursively.
        original_lock = self.shared._lock
        @contextmanager
        def checked_replay_lock():
            with self._shared_lock(original_lock=original_lock):
                _, current = self._shared_state()
                if current == self.old_shared:
                    self._require_absent_target()
                else:
                    require(current['run_id'] == self.expected_run and current == self._owned_new_run(),
                            'STOP_SHARED_A_CAS')
                yield
        self.shared._lock = checked_replay_lock
        try:
            self.shared.replay_file(owner='v3_shared_data', trade_date=TARGET, role=ROLE,
                source_id='fmla04_v192_frozen_selector', stage_id=self.s.V192_STAGE_ID,
                historical_backfill=True, expected_previous=self.old_shared)
        finally:
            self.shared._lock = original_lock

    def _new_local(self, new: Mapping[str, Any], *, latest: bool) -> tuple[dict[str, Any], dict[str, Any]]:
        reader = None
        if not latest:
            # Rollback after shared pointer restoration still reads the immutable
            # verified new trio; CSV identity equals the semantically read candidate.
            verified = self.shared.verify_run(TARGET, ROLE, new['run_id'], expected_owner='v3_shared_data')
            receipt = self.shared._read_json(self.shared.root / new['receipt_relative'])
            pool = SimpleNamespace(rows=self.candidate.rows,
                                   run=SimpleNamespace(verification=verified, receipt=receipt))
            reader = lambda *args, **kwargs: pool
        payload = self.rt.materializer.build_shared_v192_premarket_pool(
            self.shared.root, trade_date=TARGET, signal_date=SIGNAL,
            shared_package_root=SHARED_PACKAGE_ROOT, reader=reader)
        self.rt.local_module.validate_pool_artifact(payload)
        require(payload['source_run_id'] == new['run_id'] and payload['source_sha256'] == new['artifact_sha256'],
                'STOP_PROJECTION_SOURCE_DRIFT')
        artifact_relative, _ = self.local._relative(TARGET, POOL)
        receipt = self.local._receipt(trade_date=TARGET, pool_id=POOL, artifact_path=artifact_relative,
                                     artifact_sha256=digest(payload), payload=payload)
        return payload, receipt

    def apply(self) -> dict[str, Any]:
        self._admit()  # Read-only admission before either store lock/write.
        self.local._preflight_required_write_context(TARGET, POOL)
        with self.rt.lock(self.local.root / '.import.lock', timeout_seconds=10,
                          timeout_message='data-root import lock timeout'):
            self.local._assert_write_allowed(TARGET, POOL)
            self._input_fence()
            state = self._load_record()
            require(state is None or state.get('direction') == 'APPLY', 'STOP_ROLLBACK_IN_PROGRESS')
            with self._shared_lock():
                old_entry, current = self._shared_state()
                require(current == self.old_shared or (state is not None and current['run_id'] == self.expected_run),
                        'STOP_SHARED_A_CAS')
                if current != self.old_shared:
                    require(current == self._owned_new_run(), 'STOP_SHARED_A_CAS')
                old_verified = identity(self.shared.verify_run(TARGET, ROLE, self.old_shared['run_id'], expected_owner='v3_shared_data'))
                require(old_verified == self.old_shared, 'STOP_OLD_RUN_DRIFT')
                if current == self.old_shared:
                    self._require_absent_target()
                # Guard/reconcile while the shared A CAS is also stable.
                self._pending_guard(state)
                snapshot = self.local._read_pool_snapshot_unlocked(TARGET, POOL)
                if state is None:
                    require(current == self.old_shared, 'STOP_SHARED_A_CAS')
                    self._local_expected(snapshot)
                    state = dict(schema='v192.same_day_revision.operation.v1', binding_sha256=self.binding_sha,
                                 expected_run_id=self.expected_run, direction='APPLY',
                                 old_shared_entry=old_entry, old_local=snapshot, safety=FLAGS,
                                 manifest_sha256_at_prepare=snapshot['manifest_raw_sha256'])
                    self._save(state, 'PREPARED')
                else:
                    require(current == self.old_shared or current['run_id'] == self.expected_run, 'STOP_SHARED_A_CAS')
            if current == self.old_shared:
                self._local_expected(snapshot)
                # Replay owns its shared lock; never hold that lock here.
                self._replay_absent_target()
            with self._shared_lock():
                entry, current = self._shared_state()
                new = self._owned_new_run()
                require(current == new and entry.get('superseded_from') == self.old_shared, 'STOP_SHARED_A_CAS')
                payload, receipt = self._new_local(new, latest=True)
                require(snapshot['artifact_sha256'] in (self.b['expected_previous_local']['artifact_sha256'], digest(payload)),
                        'STOP_LOCAL_A_CAS')
                if snapshot['artifact_sha256'] == self.b['expected_previous_local']['artifact_sha256']:
                    self._local_expected(snapshot)
                state.update(new_shared=new, new_local_sha256=digest(payload), new_local_receipt_sha256=digest(receipt))
                self._save(state, 'SHARED_COMMITTED')
                self._input_fence()
                if snapshot['artifact_sha256'] != digest(payload):
                    self._commit_local(snapshot, payload, receipt, state)
                result = self.local._read_pool_snapshot_unlocked(TARGET, POOL)
                require(result['artifact'] == payload and result['receipt'] == receipt, 'STOP_LOCAL_READBACK')
                state['manifest_sha256_after_local'] = result['manifest_raw_sha256']
                self._save(state, 'LOCAL_COMMITTED')
            return state

    def rollback(self) -> dict[str, Any]:
        self._admit()
        self.local._preflight_required_write_context(TARGET, POOL)
        with self.rt.lock(self.local.root / '.import.lock', timeout_seconds=10,
                          timeout_message='data-root import lock timeout'):
            self.local._assert_write_allowed(TARGET, POOL)
            self._input_fence()
            state = self._load_record()
            require(state is not None, 'STOP_ROLLBACK_WITHOUT_PREPARED')
            with self._shared_lock():
                _, current = self._shared_state()
                require(current == self.old_shared or current['run_id'] == self.expected_run, 'STOP_SHARED_A_CAS')
                if current != self.old_shared:
                    require(current == self._owned_new_run(), 'STOP_SHARED_A_CAS')
                old_verified = identity(self.shared.verify_run(TARGET, ROLE, self.old_shared['run_id'], expected_owner='v3_shared_data'))
                require(old_verified == self.old_shared, 'STOP_OLD_RUN_DRIFT')
                self._pending_guard(state)
                snapshot = self.local._read_pool_snapshot_unlocked(TARGET, POOL)
                old_sha = self.b['expected_previous_local']['artifact_sha256']
                if current == self.old_shared and snapshot['artifact_sha256'] == old_sha:
                    self._local_expected(snapshot)
                    state['direction'] = 'ROLLBACK'
                    self._save(state, 'ROLLED_BACK')
                    return state
                new = self._owned_new_run()
                payload, receipt = self._new_local(new, latest=False)
                require(current in (self.old_shared, new)
                        and snapshot['artifact_sha256'] in (old_sha, digest(payload)), 'STOP_ROLLBACK_A_CAS')
                if snapshot['artifact_sha256'] == digest(payload):
                    require(snapshot['artifact'] == payload and snapshot['receipt'] == receipt, 'STOP_ROLLBACK_LOCAL_IDENTITY')
                else:
                    self._local_expected(snapshot)
                state.update(direction='ROLLBACK', new_shared=new, new_local_sha256=digest(payload),
                             new_local_receipt_sha256=digest(receipt))
                self._save(state, 'ROLLBACK_PREPARED')
                if snapshot['artifact_sha256'] == old_sha and state.get('local_archive_intent') is not None:
                    self._ensure_archives(state, ((state['old_local']['artifact'], state['old_local']['receipt']),
                                                  (payload, receipt)))
                if current == new:
                    latest = self.shared._load_latest()
                    latest['entries'] = dict(latest['entries'])
                    latest['entries'][self.shared._entry_key(TARGET, ROLE)] = state['old_shared_entry']
                    self.shared._write_json(self.shared.latest_path, latest)
                    require(self._shared_state()[1] == self.old_shared, 'STOP_ROLLBACK_SHARED_READBACK')
                self._save(state, 'ROLLBACK_SHARED_COMMITTED')
                if snapshot['artifact_sha256'] != old_sha:
                    self._commit_local(snapshot, state['old_local']['artifact'], state['old_local']['receipt'], state)
                restored = self.local._read_pool_snapshot_unlocked(TARGET, POOL)
                self._local_expected(restored)
                self._save(state, 'ROLLED_BACK')
                return state
