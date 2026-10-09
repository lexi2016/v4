"""Independent, recorded-input rebound owner; no collection or formal admission.

The pinned V4 two-gate calculation runs against a private byte-bound copy.
Owner output is retained as untrusted diagnostics. Only a downgraded research
projection is consumable; byte stability never certifies units or membership.
"""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import copy
import hashlib
import importlib
import io
import json
import os
import re
import stat
import subprocess
import tempfile
import threading
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timezone

from v5_shadow import a_preselection as common
from v5_shadow.composition import no_symlinks
from v5_shadow.contracts import aware, exact_keys, sha, trade_date
from v5_shadow.digests import canonical_bytes, sha256_json, MAX_JSON_BYTES
from v5_shadow.health import observe_dependencies
from v5_shadow.module_api import _open_directory, _read_at
from v5_shadow.module_artifacts import _directory, _write_once
from v5_shadow.source_capsule import checked_path

BASE = Path(__file__).resolve().parents[2]
CAPSULE = BASE / 'vendor/rebound_baseline'
DESCRIPTOR = BASE / 'contracts/rebound_owner_capsule.json'
PIN = '0a3f24142b3c63c2e16c08bd44fbac1d9d4909069d42fe3e5fae4c7204c3fb6e'
ROLES = ('panel_manifest', 'panel', 'master_manifest', 'master_artifact', 'master_receipt')
NAMESPACES = ('v4', 'contracts', 'infrastructure', 'v3_shared_data')
MARKER = b'v5.rebound-owner-root.v1\n'
SAFETY = dict(research_only=True, production_allowed=False, buy_gate_updated=False,
              orders_sent=False, natural_verified=False, formal_eligibility_verified=False)
BLOCKERS = ('REBOUND_HISTORY_VOLUME_UNIT_NOT_PROVEN',
            'REBOUND_HISTORY_PRICE_CURRENCY_NOT_PROVEN',
            'REBOUND_AMOUNT_UNIT_NOT_PROVEN', 'REBOUND_PROVIDER_FINALITY_NOT_ATTESTED',
            'REBOUND_TARGET_MEMBERSHIP_NOT_BOUND', 'REBOUND_NATURAL_RUN_NOT_VERIFIED')


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('REBOUND_DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('REBOUND_NONFINITE_JSON')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _request(value):
    exact_keys(value, ('schema_version', 'target_date', 'signal_date', 'research_cutoff',
                       'data_kind', 'input_root', 'paths', 'files'))
    if value['schema_version'] != 'v5.rebound_owner_request.v1':
        raise ValueError('REBOUND_REQUEST_SCHEMA')
    if trade_date(value['signal_date']) >= trade_date(value['target_date']):
        raise ValueError('REBOUND_SIGNAL_DATE')
    cutoff = aware(value['research_cutoff'])
    if cutoff > datetime.now(timezone.utc):
        raise ValueError('REBOUND_FUTURE_CUTOFF')
    if value['data_kind'] not in ('SYNTHETIC', 'RECORDED_INPUT_REPLAY'):
        raise ValueError('REBOUND_DATA_KIND')
    root = no_symlinks(value['input_root'])
    if not root.is_dir():
        raise ValueError('REBOUND_INPUT_ROOT')
    for code_root in (BASE, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()):
        if root.is_relative_to(code_root) or code_root.is_relative_to(root):
            raise ValueError('REBOUND_INPUT_CODE_OVERLAP')
    if not isinstance(value['paths'], dict) or set(value['paths']) != set(ROLES):
        raise ValueError('REBOUND_REQUIRED_ROLES:panel_manifest,panel,master_manifest,master_artifact,master_receipt')
    files = value['files']
    if not isinstance(files, dict) or not 5 <= len(files) <= 32:
        raise ValueError('REBOUND_INPUT_FILES')
    for relative, digest in files.items():
        checked_path(root, relative)
        sha(digest)
        if not re.fullmatch(r'assets/(?:hk_0_2/panels/[A-Za-z0-9._-]+/(?:manifest\.json|hkconnect_vipdoc_daily_panel\.parquet)|hk_security_master/runs/[0-9]{8}/[A-Za-z0-9_-]+/(?:manifest\.json|artifact\.csv|receipt\.json))', relative):
            raise ValueError('REBOUND_INPUT_PATH')
    if len(set(value['paths'].values())) != len(ROLES):
        raise ValueError('REBOUND_DUPLICATE_ROLE')
    for relative in value['paths'].values():
        if relative not in files:
            raise ValueError('REBOUND_ROLE_NOT_BOUND')
    canonical_bytes(value)
    return copy.deepcopy(value)


def _file(root, relative, *, destination=None):
    """No-follow descriptor walk, bounded streaming read and same-fd stability."""
    path = checked_path(root, relative)
    directory = _open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    output = None
    try:
        before = os.fstat(fd)
        limit = 512 * 1024**2 if relative.endswith('.parquet') else 8 * 1024**2
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError('REBOUND_INPUT_SIZE_OR_TYPE')
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            output = destination.open('xb')
        digest = hashlib.sha256(); count = 0
        while chunk := os.read(fd, 1024**2):
            count += len(chunk)
            if count > before.st_size:
                raise ValueError('REBOUND_INPUT_CHANGED_DURING_READ')
            digest.update(chunk)
            if output is not None:
                output.write(chunk)
        after = os.fstat(fd)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if count != before.st_size or any(getattr(before, k) != getattr(after, k) for k in fields):
            raise ValueError('REBOUND_INPUT_CHANGED_DURING_READ')
        return dict(sha256=digest.hexdigest(), bytes=count)
    finally:
        os.close(fd)
        if output is not None:
            output.close()


def _metadata(root, request):
    paths = request['paths']; day = request['signal_date']
    panel = _json(checked_path(root, paths['panel_manifest']).read_bytes())
    master = _json(checked_path(root, paths['master_manifest']).read_bytes())
    receipt = _json(checked_path(root, paths['master_receipt']).read_bytes())
    expected = dict(panel='assets/hk_0_2/' + str(panel.get('panel_relative', '')),
                    master_artifact='assets/hk_security_master/' + str(master.get('artifact_relative', '')))
    if (panel.get('panel_max_date') != day or master.get('trade_date') != day
            or receipt.get('trade_date') != day):
        raise ValueError('REBOUND_EXACT_SIGNAL_DATE_REQUIRED')
    if (any(paths[k] != v for k, v in expected.items())
            or Path(paths['panel_manifest']).parent != Path(paths['panel']).parent
            or Path(paths['master_manifest']).parent != Path(paths['master_artifact']).parent
            or Path(paths['master_receipt']).parent != Path(paths['master_artifact']).parent):
        raise ValueError('REBOUND_MANIFEST_PATH_BINDING')
    if (panel.get('panel_sha256') != request['files'][paths['panel']]
            or master.get('artifact_sha256') != request['files'][paths['master_artifact']]
            or receipt.get('artifact_sha256') != master.get('artifact_sha256')
            or receipt.get('manifest_sha256') != sha256_json(master)
            or not master.get('run_id') or receipt.get('run_id') != master['run_id']
            or receipt.get('status') != 'READY'):
        raise ValueError('REBOUND_OWNER_RECEIPT_OR_SHA_MISMATCH')
    cutoff = aware(request['research_cutoff'])
    for document, key, reason in ((panel, 'manifest_prepared_at', 'PANEL'), (master, 'captured_at', 'MASTER')):
        try:
            available = aware(document.get(key))
        except ValueError as error:
            raise ValueError('REBOUND_' + reason + '_AVAILABILITY_UNPROVEN') from error
        if available > cutoff:
            raise ValueError('REBOUND_' + reason + '_AFTER_CUTOFF')
    return panel, master, receipt


def prepare_snapshot(request, destination):
    request = _request(request)
    source = no_symlinks(request['input_root']); target = no_symlinks(destination)
    if target.exists() or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('REBOUND_PRIVATE_SNAPSHOT_PATH')
    target.mkdir(mode=0o700)
    entries = {}; total = 0
    for relative, expected in sorted(request['files'].items()):
        identity = _file(source, relative, destination=checked_path(target, relative))
        if identity['sha256'] != expected:
            raise ValueError('REBOUND_INPUT_SHA_MISMATCH:' + relative)
        total += identity['bytes']
        if total > 1024**3:
            raise ValueError('REBOUND_SNAPSHOT_SIZE')
        entries[relative] = identity
    panel, master, _ = _metadata(target, request)
    # Routing only: never invent an owner receipt or backdate availability.
    pointers = {
        'assets/hk_0_2/panel_latest.json': dict(manifest_relative=request['paths']['panel_manifest'].removeprefix('assets/hk_0_2/')),
        'assets/hk_security_master/latest.json': dict(schema_version='v3_shared_data.hk_security_master_latest.v1',
            entries={request['signal_date']: dict(run_id=master['run_id'],
                manifest_relative=request['paths']['master_manifest'].removeprefix('assets/hk_security_master/'),
                receipt_relative=request['paths']['master_receipt'].removeprefix('assets/hk_security_master/'))})}
    for relative, value in pointers.items():
        raw = canonical_bytes(value); path = checked_path(target, relative)
        path.write_bytes(raw)
        entries[relative] = dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    for path in target.rglob('*'):
        if path.is_file():
            path.chmod(0o400)
    for path in sorted((p for p in target.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        path.chmod(0o500)
    target.chmod(0o500)
    return dict(schema_version='v5.rebound_private_snapshot.v1', files=entries,
        snapshot_sha256=sha256_json(entries), source_file_sha256=request['files'],
        adapter_generated_routing=list(pointers), status='PRIVATE_COPY_SHA_BOUND',
        owner_read_lease_verified=False, owner_origin_verified=False,
        historical_availability='OWNER_METADATA_CUTOFF_CHECKED_NOT_HISTORICAL_PROCESS_PROOF')


def _verify_private(root, snapshot):
    if snapshot['snapshot_sha256'] != sha256_json(snapshot['files']):
        raise ValueError('REBOUND_SNAPSHOT_IDENTITY')
    paths = list(root.rglob('*'))
    if any(path.is_symlink() for path in paths):
        raise ValueError('REBOUND_PRIVATE_SYMLINK')
    actual = {p.relative_to(root).as_posix() for p in paths if not p.is_dir()}
    if actual != set(snapshot['files']):
        raise ValueError('REBOUND_SNAPSHOT_FILE_SET')
    for name, expected in snapshot['files'].items():
        if _file(root, name) != expected:
            raise ValueError('REBOUND_PRIVATE_INPUT_CHANGED')


def _sources():
    descriptor = _json(DESCRIPTOR.read_bytes())
    if sha256_json(descriptor) != PIN:
        raise ValueError('REBOUND_CAPSULE_DESCRIPTOR')
    for relative, expected in descriptor['bindings'].items():
        if hashlib.sha256(checked_path(BASE, relative).read_bytes()).hexdigest() != expected:
            raise ValueError('REBOUND_CAPSULE_BINDING:' + relative)
    sources = {}
    original = _json((BASE / 'contracts/rebound_source_manifest.json').read_bytes())
    for entry in original['entries']:
        raw = checked_path(CAPSULE, entry['relative_path']).read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if hashlib.sha256(raw).hexdigest() != entry['sha256'] or blob != entry['git_blob_sha']:
            raise ValueError('REBOUND_CAPSULE_BYTES:' + entry['relative_path'])
        sources[entry['relative_path']] = raw
    return sources


class _Loader(common._FrozenLoader):
    def find_spec(self, fullname, path=None, target=None):
        found = super().find_spec(fullname, path, target)
        if found is None and fullname.split('.')[0] in NAMESPACES:
            raise ImportError('REBOUND_SOURCE_CLOSURE:' + fullname)
        return found

    def exec_module(self, module):
        if module.__name__ in self.packages:
            module.__path__ = []
        item = self.sources.get(module.__name__)
        if item:
            relative, raw, _ = item
            module.__file__ = str(CAPSULE / relative)
            exec(compile(raw, module.__file__, 'exec'), module.__dict__)


def _identity():
    names = ('rebound_owner.py', 'a_preselection.py', 'composition.py', 'contracts.py',
             'digests.py', 'health.py', 'module_api.py', 'module_artifacts.py',
             'api_gateway.py', 'provider_evidence.py', 'source_capsule.py', '__init__.py')
    return {name: hashlib.sha256((BASE / 'src/v5_shadow' / name).read_bytes()).hexdigest() for name in names}


def _guard(private):
    violations = []
    readable = (private, CAPSULE, BASE / 'contracts', BASE / 'src',
                Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve())
    resources = (BASE / 'uv.lock', BASE / 'pyproject.toml')
    directories = {}
    local = threading.local()
    original_open = os.open
    def reject(reason):
        violations.append(reason)
        raise PermissionError(reason)
    def admit(path, flags):
        candidate = no_symlinks(Path(path).absolute())
        if candidate in resources or any(candidate.is_relative_to(root) for root in readable):
            return candidate
        # SafeRoot opens ancestors one descriptor at a time. Only a directory
        # traversal may touch these ancestors; files outside the roots may not.
        if flags & os.O_DIRECTORY and any(root.is_relative_to(candidate) for root in readable):
            return candidate
        reject('REBOUND_READ_OUTSIDE_PRIVATE_INPUT')
    def guarded_open(path, flags, mode=0o777, *, dir_fd=None):
        value = Path(os.fsdecode(path))
        if not value.is_absolute() and dir_fd is not None:
            known = directories.get(dir_fd)
            observed = os.fstat(dir_fd)
            if known is None or known[1:] != (observed.st_dev, observed.st_ino):
                reject('REBOUND_UNKNOWN_DIRECTORY_DESCRIPTOR')
            value = known[0] / value
        candidate = admit(value, flags)
        local.open_admitted = True
        try:
            fd = original_open(path, flags, mode, dir_fd=dir_fd)
        finally:
            local.open_admitted = False
        observed = os.fstat(fd)
        if stat.S_ISDIR(observed.st_mode):
            directories[fd] = (candidate, observed.st_dev, observed.st_ino)
        else:
            directories.pop(fd, None)
        return fd
    def audit(event, args):
        if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn', 'os.posix_spawn')) or event in ('os.system', 'os.fork', 'os.forkpty'):
            reject('REBOUND_NETWORK_OR_PROCESS_DENIED')
        if event in ('os.remove', 'os.rename', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.link',
                     'os.symlink', 'os.truncate', 'os.utime', 'os.chown', 'os.fchmod', 'os.fchown'):
            reject('REBOUND_WRITE_DENIED')
        if event == 'open':
            path, mode, flags = args
            if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                reject('REBOUND_WRITE_DENIED')
            if not isinstance(path, int) and not getattr(local, 'open_admitted', False):
                admit(os.fsdecode(path), flags)
    os.open = guarded_open
    sys.addaudithook(audit)
    return violations


def research_projection(legacy, native_evidence):
    """Preserve gate numbers/groups; strip assertions absent from native proof."""
    def scrub(value):
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key == 'amount_hkd':
                result['amount_native'] = item
            elif key == 'verified_session':
                result['observed_session'] = item
            elif key in ('amount_unit', 'price_currency', 'volume_unit', 'currency'):
                result[key] = None
            elif key == 'session_kind':
                result[key] = 'NOT_ATTESTED_BY_PROVIDER'
            elif key == 'connect_eligibility':
                result[key] = 'UNVERIFIED'
            elif key == 'qualification_status':
                result[key] = 'UNVERIFIED_RESEARCH_OBSERVATION'
            else:
                result[key] = scrub(item)
        return result
    projected = scrub(legacy)
    projected.update(schema_version='v5.rebound_research_observation.v1',
        original_computation_status=legacy.get('status'), status='CANNOT_CONFIRM',
        main_screen_ready=False, native_evidence=copy.deepcopy(native_evidence),
        gaps=sorted(set(legacy.get('gaps', []) + list(BLOCKERS) + native_evidence.get('gaps', []))),
        **SAFETY)
    return projected


def _calculate(envelope):
    request = envelope['request']; private = no_symlinks(envelope['private_root'])
    snapshot = envelope['snapshot']
    if sys.version_info < (3, 14):
        raise ValueError('REBOUND_PYTHON_REQUIRES_3_14')
    sources = _sources(); dependencies = observe_dependencies(BASE / 'uv.lock')
    if dependencies['status'] != 'MATCH':
        raise ValueError('REBOUND_DEPENDENCIES:' + ','.join(dependencies['reason_codes']))
    if any(name.split('.')[0] in NAMESPACES for name in sys.modules):
        raise ValueError('REBOUND_FRESH_PROCESS_REQUIRED')
    sys.meta_path.insert(0, _Loader(sources))
    original = importlib.import_module('v4.manager_research.workspace_plan')
    importlib.import_module('pandas'); importlib.import_module('pyarrow.parquet')
    # Preload the pinned read closure before installing permanent write guards.
    importlib.import_module('infrastructure.owned_io')
    importlib.import_module('v3_shared_data.shared_data.hk_security_master')
    context = original.plan_context(request['target_date'], now=aware(request['research_cutoff']))
    if context['market_session'] != request['signal_date']:
        raise ValueError('REBOUND_SIGNAL_CALENDAR_MISMATCH')
    _verify_private(private, snapshot)
    panel, master, _ = _metadata(private, request)
    violations = _guard(private)
    native = original.rebound_native_evidence(panel, required_session=request['signal_date'],
        observed_at=datetime.now(timezone.utc), master_captured_at=master['captured_at'])
    with redirect_stdout(io.StringIO()):
        legacy = original.read_rebound_screen(private, context)
    if violations:
        raise ValueError('REBOUND_BOUNDARY_VIOLATION:' + ','.join(violations))
    _verify_private(private, snapshot)
    # Explicit selected-role provenance must agree with what the original reader used.
    if legacy.get('main_screen_ready') is True:
        authority = legacy['authority']; witness = authority['panel_witness']; sec = authority['security_master']
        for role, observed in (('panel_manifest', witness['panel_manifest_sha256']),
                               ('panel', witness['panel_sha256']),
                               ('master_manifest', sec['manifest_sha256']),
                               ('master_artifact', sec['artifact_sha256'])):
            if observed != request['files'][request['paths'][role]]:
                raise ValueError('REBOUND_SELECTED_OWNER_MISMATCH:' + role)
    _sources()
    return dict(legacy_diagnostic=dict(status='UNTRUSTED_LEGACY_ASSERTIONS', payload=legacy),
        research_observation=research_projection(legacy, native), dependencies=dependencies,
        context=context, implementation_identity=_identity(), source_capsule_sha256=PIN,
        request_sha256=sha256_json(request), snapshot_sha256=snapshot['snapshot_sha256'])


def _output(root):
    root = no_symlinks(root); fd = _open_directory(root)
    try:
        if _read_at(fd, None, '.v5-rebound-owner-root') != MARKER:
            raise ValueError('REBOUND_OUTPUT_MARKER')
        if root.is_relative_to(BASE) or BASE.is_relative_to(root):
            raise ValueError('REBOUND_OUTPUT_CODE_OVERLAP')
        return root, fd
    except Exception:
        os.close(fd)
        raise


def _publish(root, artifact):
    _validate_artifact(artifact)
    root, fd = _output(root)
    try:
        runs = _directory(fd, 'runs')
        try:
            run = _directory(runs, artifact['run_id'])
        finally:
            os.close(runs)
        try:
            raw = canonical_bytes(artifact); digest = hashlib.sha256(raw).hexdigest()
            manifest = dict(schema_version='v5.rebound_owner_manifest.v1', run_id=artifact['run_id'],
                artifact_sha256=digest, target_date=artifact['request']['target_date'],
                request_sha256=artifact['request_sha256'], source_capsule_sha256=PIN)
            mraw = canonical_bytes(manifest); msha = hashlib.sha256(mraw).hexdigest()
            receipt = dict(schema_version='v5.rebound_owner_receipt.v1', run_id=artifact['run_id'],
                artifact_sha256=digest, manifest_sha256=msha, status='COMMITTED', **SAFETY)
            rraw = canonical_bytes(receipt)
            _write_once(run, 'artifact.json', raw)
            _write_once(run, 'manifest.json', mraw)
            # Receipt last: an interrupted pair is not a committed run.
            _write_once(run, 'receipt.json', rraw)
            ref = dict(run_id=artifact['run_id'], artifact_sha256=digest,
                manifest_sha256=msha, receipt_sha256=hashlib.sha256(rraw).hexdigest())
        finally:
            os.close(run)
    finally:
        os.close(fd)
    if read_rebound_owner(root, ref) != artifact:
        raise ValueError('REBOUND_INDEPENDENT_READBACK_MISMATCH')
    return ref


def read_rebound_owner(root, reference):
    exact_keys(reference, ('run_id', 'artifact_sha256', 'manifest_sha256', 'receipt_sha256'))
    if not re.fullmatch(r'[0-9a-f]{32}', str(reference['run_id'])):
        raise ValueError('REBOUND_RUN_ID')
    for key in ('artifact_sha256', 'manifest_sha256', 'receipt_sha256'):
        sha(reference[key])
    _, fd = _output(root)
    try:
        runs = os.open('runs', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            run = os.open(reference['run_id'], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=runs)
        finally:
            os.close(runs)
        try:
            documents = {}
            for name in ('artifact', 'manifest', 'receipt'):
                raw = _read_at(run, None, name + '.json')
                if hashlib.sha256(raw).hexdigest() != reference[name + '_sha256']:
                    raise ValueError('REBOUND_READBACK_SHA:' + name)
                documents[name] = _json(raw)
        finally:
            os.close(run)
    finally:
        os.close(fd)
    artifact, manifest, receipt = (documents[k] for k in ('artifact', 'manifest', 'receipt'))
    if (any(v.get('run_id') != reference['run_id'] for v in documents.values())
            or artifact.get('schema_version') != 'v5.rebound_owner.v1'
            or manifest.get('schema_version') != 'v5.rebound_owner_manifest.v1'
            or receipt.get('schema_version') != 'v5.rebound_owner_receipt.v1'
            or receipt.get('status') != 'COMMITTED'
            or manifest.get('artifact_sha256') != reference['artifact_sha256']
            or receipt.get('artifact_sha256') != reference['artifact_sha256']
            or receipt.get('manifest_sha256') != reference['manifest_sha256']
            or manifest.get('target_date') != artifact['request']['target_date']
            or manifest.get('request_sha256') != sha256_json(artifact['request'])
            or artifact.get('request_sha256') != manifest['request_sha256']
            or manifest.get('source_capsule_sha256') != artifact.get('source_capsule_sha256')
            or any(v.get(k) is not expected for v in (artifact, receipt) for k, expected in SAFETY.items())
            or artifact.get('formal_status') != 'CANNOT_CONFIRM'):
        raise ValueError('REBOUND_READBACK_CONTRACT')
    _validate_artifact(artifact)
    return artifact


def _validate_artifact(artifact):
    """A receipt's hashes attest bytes; their semantic contract is separate."""
    if (artifact.get('schema_version') != 'v5.rebound_owner.v1'
            or artifact.get('source_capsule_sha256') != PIN
            or artifact.get('formal_status') != 'CANNOT_CONFIRM'
            or any(artifact.get(k) is not v for k, v in SAFETY.items())):
        raise ValueError('REBOUND_ARTIFACT_SAFETY_OR_SOURCE')
    request = artifact['request']
    if sha256_json(request) != artifact['request_sha256']:
        raise ValueError('REBOUND_ARTIFACT_REQUEST')
    if request['data_kind'] not in ('SYNTHETIC', 'RECORDED_INPUT_REPLAY'):
        raise ValueError('REBOUND_ARTIFACT_DATA_KIND')
    expected_kind = 'SYNTHETIC_TEST' if request['data_kind'] == 'SYNTHETIC' else 'MANUAL_RECORDED_INPUT_REPLAY'
    if artifact['execution_kind'] != expected_kind:
        raise ValueError('REBOUND_ARTIFACT_EXECUTION_KIND')
    if not aware(request['research_cutoff']) <= aware(artifact['started_at']) <= aware(artifact['finished_at']):
        raise ValueError('REBOUND_ARTIFACT_CLOCK')
    snapshot = artifact['snapshot']; observation = artifact['research_observation']
    if snapshot is not None:
        if (snapshot.get('snapshot_sha256') != sha256_json(snapshot['files'])
                or snapshot.get('source_file_sha256') != request['files']
                or snapshot.get('status') != 'PRIVATE_COPY_SHA_BOUND'
                or snapshot.get('owner_read_lease_verified') is not False
                or snapshot.get('owner_origin_verified') is not False):
            raise ValueError('REBOUND_ARTIFACT_SNAPSHOT')
        for relative, digest in request['files'].items():
            if snapshot['files'].get(relative, {}).get('sha256') != digest:
                raise ValueError('REBOUND_ARTIFACT_INPUT_BINDING')
    if observation is None:
        if artifact['legacy_diagnostic'] is not None or artifact['computation_status'] != 'CANNOT_CONFIRM':
            raise ValueError('REBOUND_FAILED_ARTIFACT_OBSERVATION')
        return
    diagnostic = artifact['legacy_diagnostic']; legacy = diagnostic['payload']
    if (snapshot is None or diagnostic.get('status') != 'UNTRUSTED_LEGACY_ASSERTIONS'
            or artifact.get('snapshot_sha256') != snapshot['snapshot_sha256']
            or artifact.get('context', {}).get('market_session') != request['signal_date']
            or artifact.get('context', {}).get('plan_trade_date') != request['target_date']
            or legacy.get('schema_version') != 'v4.manager_research.rebound_v3_screen.v1'
            or legacy.get('rule_version') != '20260923_REBOUND_TWO_GATE_V1'
            or legacy.get('target_trade_date') != request['target_date']
            or legacy.get('verified_session') != request['signal_date']
            or artifact['computation_status'] != legacy.get('status')
            or artifact['computation_status'] not in ('READY', 'READY_WITH_GAPS', 'CANNOT_CONFIRM')
            or any(legacy.get(k) is not False for k in ('production_allowed', 'buy_gate_updated', 'orders_sent'))
            or legacy.get('RESEARCH_ONLY') is not True
            or artifact.get('dependencies', {}).get('status') != 'MATCH'
            or canonical_bytes(observation) != canonical_bytes(research_projection(legacy, observation['native_evidence']))
            or not set(BLOCKERS).issubset(artifact['reason_codes'])):
        raise ValueError('REBOUND_ARTIFACT_OBSERVATION_CONTRACT')
    identity = artifact.get('implementation_identity')
    if not isinstance(identity, dict) or set(identity) != set(_identity()):
        raise ValueError('REBOUND_ARTIFACT_IMPLEMENTATION_IDENTITY')
    for digest in identity.values():
        sha(digest)


def manager_projection(artifact, *, target_date, research_cutoff, market_session):
    """Call only with read_rebound_owner output. Never returns a formal screen."""
    _validate_artifact(artifact)
    reasons = list(artifact.get('reason_codes', [])); request = artifact['request']
    cutoff = aware(research_cutoff)
    if request['data_kind'] != 'RECORDED_INPUT_REPLAY':
        reasons.append('REBOUND_MANAGER_SYNTHETIC_NOT_ADMITTED')
    if request['target_date'] != target_date or request['signal_date'] != market_session:
        reasons.append('REBOUND_MANAGER_DATE_MISMATCH')
    if aware(request['research_cutoff']) > cutoff or aware(artifact['finished_at']) > cutoff:
        reasons.append('REBOUND_MANAGER_AFTER_CUTOFF')
    admissible_observation = not any(x.startswith('REBOUND_MANAGER_') for x in reasons)
    return dict(status='CANNOT_CONFIRM', eligible_screen=None,
        research_observation=copy.deepcopy(artifact.get('research_observation')) if admissible_observation else None,
        reason_codes=sorted(set(reasons + list(BLOCKERS))), source_run_id=artifact['run_id'],
        data_kind=request['data_kind'], execution_kind=artifact['execution_kind'], **SAFETY)


def run_rebound_owner(request, output_root):
    request = _request(request); output, fd = _output(output_root); os.close(fd)
    source = no_symlinks(request['input_root'])
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('REBOUND_INPUT_OUTPUT_OVERLAP')
    started = datetime.now(timezone.utc); identity = _identity()
    artifact = dict(schema_version='v5.rebound_owner.v1', run_id=uuid.uuid4().hex,
        request=request, request_sha256=sha256_json(request), started_at=started.isoformat(),
        source_capsule_sha256=PIN, implementation_identity=identity,
        execution_kind='MANUAL_RECORDED_INPUT_REPLAY' if request['data_kind'] != 'SYNTHETIC' else 'SYNTHETIC_TEST',
        formal_status='CANNOT_CONFIRM', computation_status='NOT_RUN', reason_codes=list(BLOCKERS),
        snapshot=None, research_observation=None, legacy_diagnostic=None,
        isolation='PRIVATE_READONLY_COPY_AND_PYTHON_GUARDS_NOT_OS_SANDBOX', **SAFETY)
    try:
        _sources()
        with tempfile.TemporaryDirectory(prefix='v5-rebound-owner-') as temporary:
            private = Path(temporary).resolve() / 'inputs'
            snapshot = prepare_snapshot(request, private); artifact['snapshot'] = snapshot
            envelope = dict(request=request, private_root=str(private), snapshot=snapshot)
            env = {k: v for k, v in os.environ.items() if not k.startswith(('V4_', 'V5_', 'PYTHON'))}
            result = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker'],
                input=canonical_bytes(envelope), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, timeout=180)
            if len(result.stdout) > MAX_JSON_BYTES:
                raise ValueError('REBOUND_WORKER_RESPONSE_SIZE')
            value = _json(result.stdout)
            if result.returncode:
                raise ValueError(value.get('reason', 'REBOUND_WORKER_FAILED'))
            if (value.get('request_sha256') != artifact['request_sha256']
                    or value.get('snapshot_sha256') != snapshot['snapshot_sha256']
                    or value.get('source_capsule_sha256') != PIN
                    or value.get('implementation_identity') != identity or _identity() != identity):
                raise ValueError('REBOUND_WORKER_IDENTITY')
            _verify_private(private, snapshot)
            artifact.update(value)
            artifact['computation_status'] = value['legacy_diagnostic']['payload'].get('status', 'CANNOT_CONFIRM')
            artifact['reason_codes'] = value['research_observation']['gaps']
    except (ValueError, OSError, TypeError, KeyError, subprocess.TimeoutExpired) as error:
        artifact.update(computation_status='CANNOT_CONFIRM', research_observation=None, legacy_diagnostic=None)
        artifact['reason_codes'] = sorted(set(list(BLOCKERS) + [type(error).__name__ + ':' + str(error)]))
    artifact['finished_at'] = datetime.now(timezone.utc).isoformat()
    reference = _publish(output, artifact)
    return dict(reference=reference, readback=read_rebound_owner(output, reference))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--output-root', type=Path)
    args = parser.parse_args()
    if args.worker:
        raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError('REBOUND_REQUEST_SIZE')
        return _calculate(_json(raw))
    if args.request is None or args.output_root is None:
        parser.error('--request and --output-root are required')
    result = run_rebound_owner(_json(args.request.read_bytes()), args.output_root)
    return dict(reference=result['reference'], computation_status=result['readback']['computation_status'],
                formal_status=result['readback']['formal_status'], reason_codes=result['readback']['reason_codes'])


if __name__ == '__main__':
    try:
        print(canonical_bytes(main()).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED', reason=type(error).__name__ + ':' + str(error))).decode())
        raise SystemExit(1)
