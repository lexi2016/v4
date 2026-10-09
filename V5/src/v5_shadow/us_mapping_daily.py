"""Original US mapping build/persist/readback over bound private input copies."""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import copy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
import re
import subprocess
import tempfile
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from v5_shadow import a_preselection as common
from v5_shadow.composition import no_symlinks
from v5_shadow.contracts import aware, exact_keys, sha, trade_date
from v5_shadow.digests import canonical_bytes, sha256_json, MAX_JSON_BYTES
from v5_shadow.module_api import _open_directory, _read_regular
from v5_shadow.us_mapping_io import install_owner_boundary

BASE = Path(__file__).resolve().parents[2]
CAPSULE = BASE / 'vendor/us_mapping_baseline'
DESCRIPTOR = BASE / 'contracts/us_mapping_source_manifest.json'
PIN = '97129b2c480879fbc8dc12e7ee5170928e86a9cc24a1b9c689eb3fbb830a3682'
NAMESPACES = ('v4', 'ops', 'infrastructure', 'contracts')


def _request(value):
    exact_keys(value, ('target_date', 'now', 'us_data_root', 'us_files', 'manager_output_root'))
    trade_date(value['target_date'])
    cutoff = aware(value['now'])
    if cutoff > datetime.now(timezone.utc):
        raise ValueError('US_MAPPING_FUTURE_CUTOFF')
    roots = []
    for key in ('us_data_root', 'manager_output_root'):
        if not isinstance(value[key], str) or not Path(value[key]).is_absolute():
            raise ValueError('US_MAPPING_ROOT_INVALID')
        root = no_symlinks(value[key])
        if not root.is_dir():
            raise ValueError('US_MAPPING_ROOT_INVALID')
        roots.append(root)
    if roots[0].is_relative_to(roots[1]) or roots[1].is_relative_to(roots[0]):
        raise ValueError('US_MAPPING_ROOTS_OVERLAP')
    directory = _open_directory(roots[1])
    try:
        try:
            fd = os.open('.v5-us-mapping-root', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                marker = _read_regular(fd, 64)
            finally:
                os.close(fd)
        except OSError as error:
            raise ValueError('US_MAPPING_OUTPUT_NOT_INITIALIZED') from error
        if marker != b'v5.us-mapping-root.v1\n':
            raise ValueError('US_MAPPING_OUTPUT_NOT_INITIALIZED')
    finally:
        os.close(directory)
    files = value['us_files']
    if not isinstance(files, dict) or len(files) != 3:
        raise ValueError('US_MAPPING_EXACT_SOURCE_SET')
    dates = []
    for name, digest in files.items():
        if not isinstance(name, str):
            raise ValueError('US_MAPPING_EXACT_SOURCE_SET')
        sha(digest)
        match = re.fullmatch(r'research/peripherals/([0-9]{8})/external_finance\.json', name)
        if match:
            dates.append(trade_date(match.group(1)))
    if len(dates) != 1:
        raise ValueError('US_MAPPING_EXACT_SOURCE_SET')
    expected = {'research/peripherals/manifest.json',
                f'research/peripherals/{dates[0]}/external_finance.json',
                f'receipts/research/peripherals/{dates[0]}/external_finance.json'}
    if set(files) != expected:
        raise ValueError('US_MAPPING_EXACT_SOURCE_SET')
    canonical_bytes(value)
    return dates[0]


def _snapshot(root, files):
    result = {}
    total = 0
    for name, digest in files.items():
        path = common._relative(no_symlinks(root), name)
        directory = _open_directory(path.parent)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        try:
            raw = _read_regular(fd, MAX_JSON_BYTES)
        finally:
            os.close(fd)
        total += len(raw)
        if total > 3 * MAX_JSON_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('US_MAPPING_INPUT_SHA_OR_SIZE')
        result[name] = raw
    return result


def _sources():
    descriptor = json.loads(no_symlinks(DESCRIPTOR).read_bytes())
    if sha256_json(descriptor) != PIN:
        raise ValueError('US_MAPPING_SOURCE_PIN')
    result = {}
    for entry in descriptor['entries']:
        raw = common._relative(CAPSULE, entry['relative_path']).read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('US_MAPPING_SOURCE_BYTES')
        result[entry['relative_path']] = raw
    return result


def _identity():
    names = ('us_mapping_scope.py', 'us_mapping_daily.py', 'us_mapping_io.py', 'a_preselection.py', 'contracts.py',
             'digests.py', 'composition.py', 'module_api.py', 'api_gateway.py', 'provider_evidence.py', '__init__.py')
    return {name: hashlib.sha256((BASE / 'src/v5_shadow' / name).read_bytes()).hexdigest() for name in names}


class _Loader(common._FrozenLoader):
    def find_spec(self, fullname, path=None, target=None):
        found = super().find_spec(fullname, path, target)
        if found is None and fullname.split('.')[0] in NAMESPACES:
            raise ImportError('US_MAPPING_SOURCE_CLOSURE:' + fullname)
        return found

    def exec_module(self, module):
        if module.__name__ in self.packages:
            module.__path__ = []
        item = self.sources.get(module.__name__)
        if item:
            name, raw, _ = item
            module.__file__ = str(CAPSULE / name)
            exec(compile(raw, module.__file__, 'exec'), module.__dict__)


def _worker(envelope):
    exact_keys(envelope, ('request', 'private_input'))
    request = envelope['request']
    supplied_session = _request(request)
    private = no_symlinks(envelope['private_input'])
    if not sys.pycache_prefix or not private.is_relative_to(no_symlinks(sys.pycache_prefix)):
        raise ValueError('US_MAPPING_PRIVATE_SNAPSHOT_REQUIRED')
    _snapshot(private, request['us_files'])
    sources = _sources()
    if any(name.split('.')[0] in NAMESPACES for name in sys.modules):
        raise ValueError('US_MAPPING_FRESH_PROCESS_REQUIRED')
    for name in ('America/New_York', 'Asia/Hong_Kong', 'Asia/Shanghai'):
        ZoneInfo(name)
    sys.meta_path.insert(0, _Loader(sources))
    plans = importlib.import_module('v4.manager_research.workspace_plan')
    mapping = importlib.import_module('v4.manager_research.us_mapping_research')
    bridge = importlib.import_module('v4.manager_research.us_market_bridge')
    stores = importlib.import_module('v4.manager_research.store')
    io = importlib.import_module('infrastructure.owned_io')
    cutoff = aware(request['now'])
    target = request['target_date']
    context = plans.plan_context(target, now=cutoff)
    session = bridge.latest_completed_session(aware(context['research_cutoff'])).session_date
    if session != supplied_session:
        raise ValueError('US_MAPPING_SOURCE_SESSION_MISMATCH')
    started = datetime.now(timezone.utc)

    def frozen_context(date, *, now=None):
        if date != target or now != started:
            raise ValueError('US_MAPPING_CONTEXT_INVOCATION')
        return copy.deepcopy(context)

    # The original now argument serves two meanings. Bind only its context
    # dependency, so original persistence hashes the actual generated_at while
    # price/session/relationship decisions retain the requested historical cutoff.
    mapping.plan_context = frozen_context
    violations = install_owner_boundary(io.SafeRoot, private, Path(request['manager_output_root']),
                                        target, set(request['us_files']))
    store = stores.ManagerResearchStore(Path(request['manager_output_root']))
    reader = bridge.ResearchPeripheralUsMarketReader(private)
    service = SimpleNamespace(store=store, _workspace_us_market_reader=reader)
    persisted = mapping.persist_daily_run(service, target, now=started)
    payload = mapping.read_workspace_mapping(service, target)
    from v5_shadow.us_mapping_scope import describe_scope
    scope=describe_scope(persisted,bridge.project_us_market(reader,target,context),mapping._read_reviewed())
    if persisted != payload['daily_run']:
        raise ValueError('US_MAPPING_READBACK_MISMATCH')
    if violations:
        raise ValueError('US_MAPPING_BOUNDARY_VIOLATION:' + ','.join(violations))
    _snapshot(private, request['us_files'])
    _sources()
    return dict(schema_version='v5.us_mapping_daily.v1', execution_kind='MANUAL_RECOVERY',
                requested_research_cutoff=request['now'], context_sha256=sha256_json(context),
                actual_started_at=started.isoformat(), actual_finished_at=datetime.now(timezone.utc).isoformat(),
                source_capsule_sha256=PIN, implementation_identity=_identity(), persisted_daily=persisted, payload=payload,
                readback_status='MATCHED', coverage_diagnostics=scope, input_sha_before=request['us_files'],
                input_sha_after=request['us_files'], source_origin_verified=False,
                natural_verified=False, isolation='PINNED_OWNER_PYTHON_WRITE_GUARDS_NOT_OS_SANDBOX')


def run_us_mapping(request):
    _request(request)
    _sources()
    identity = _identity()
    try:
        inputs = _snapshot(request['us_data_root'], request['us_files'])
    except OSError as error:
        raise ValueError('US_MAPPING_INPUT_NOT_AVAILABLE') from error
    with tempfile.TemporaryDirectory(prefix='v5-us-mapping-') as temporary:
        cache = Path(temporary).resolve()
        private = cache / 'source'
        private.mkdir()
        for name, raw in inputs.items():
            path = private / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        environment = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONSAFEPATH='1')
        environment.pop('PYTHONPATH', None)
        environment.pop('PYTHONSTARTUP', None)
        envelope = dict(request=request, private_input=str(private))
        completed = subprocess.run([sys.executable, '-B', '-X', 'pycache_prefix=' + str(cache),
                                    str(Path(__file__).resolve()), '--worker'],
                                   input=canonical_bytes(envelope), capture_output=True, env=environment,
                                   timeout=120, cwd=cache)
        if completed.returncode:
            raise RuntimeError('US_MAPPING_WORKER_FAILED:' + completed.stderr.decode('utf-8', errors='replace')[-12000:])
        if len(completed.stdout) > MAX_JSON_BYTES:
            raise ValueError('US_MAPPING_OUTPUT_SIZE')
        result = json.loads(completed.stdout)
    _snapshot(request['us_data_root'], request['us_files'])
    _sources()
    if result.get('implementation_identity') != identity or _identity() != identity:
        raise ValueError('US_MAPPING_IMPLEMENTATION_CHANGED')
    return result


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker']:
        raise SystemExit('worker invocation required')
    raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError('US_MAPPING_REQUEST_SIZE')
    sys.stdout.buffer.write(canonical_bytes(_worker(json.loads(raw))))
