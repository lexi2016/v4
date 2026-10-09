"""V5 binding of independent saved owners to the original manager workspace.

No service pool, collectors or scheduler. Mutations are explicit manual plan
refreshes; ordinary API responses are published separately as immutable reads.
"""
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
import threading
from types import SimpleNamespace
from v5_shadow import a_preselection as common
from v5_shadow.composition import no_symlinks
from v5_shadow.contracts import exact_keys, aware, trade_date, sha
from v5_shadow.digests import canonical_bytes, sha256_json, MAX_JSON_BYTES
from v5_shadow.module_api import _open_directory, _read_regular
from v5_shadow.manager_plan_io import install_manager_boundary

BASE = Path(__file__).resolve().parents[2]
CAPSULE = BASE / 'vendor/manager_plan_baseline'
DESCRIPTOR = BASE / 'contracts/manager_plan_source_manifest.json'
PIN = '45527d7135e7d728d0d563f4d3d70cd54001045c9a8b6d56288b27d44aeab736'
ROUTE = '/api/v4/manager/research/workspace'
NAMESPACES = ('v4', 'contracts', 'infrastructure', 'ops', 'domains', 'stage_center')


def _sources():
    descriptor = json.loads(DESCRIPTOR.read_bytes())
    if sha256_json(descriptor) != PIN:
        raise ValueError('MANAGER_SOURCE_DESCRIPTOR')
    result = {}
    for entry in descriptor['entries']:
        raw = common._relative(CAPSULE, entry['relative_path']).read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('MANAGER_SOURCE_BYTES:' + entry['relative_path'])
        result[entry['relative_path']] = raw
    return result


class _Loader(common._FrozenLoader):
    def find_spec(self, fullname, path=None, target=None):
        found = super().find_spec(fullname, path, target)
        if found is None and fullname.split('.')[0] in NAMESPACES:
            raise ImportError('MANAGER_SOURCE_CLOSURE:' + fullname)
        return found

    def exec_module(self, module):
        if module.__name__ in self.packages:
            module.__path__ = []
        item = self.sources.get(module.__name__)
        if item:
            name, raw, _ = item
            module.__file__ = str(CAPSULE / name)
            exec(compile(raw, module.__file__, 'exec'), module.__dict__)


def load_owner():
    if any(name.split('.')[0] in NAMESPACES for name in sys.modules):
        raise ValueError('MANAGER_FRESH_PROCESS_REQUIRED')
    sys.meta_path.insert(0, _Loader(_sources()))
    return importlib.import_module('v4.manager_research.workspace')


def _request(value):
    exact_keys(value, ('target_date', 'now', 'action', 'view', 'selection_date',
                       'announcement_date', 'inputs', 'rebound', 'manager_output_root'))
    trade_date(value['target_date'])
    if aware(value['now']) > datetime.now(timezone.utc):
        raise ValueError('MANAGER_FUTURE_CUTOFF')
    if value['action'] not in ('read', 'refresh') or value['view'] not in ('auto', 'dynamic', 'historical'):
        raise ValueError('MANAGER_ACTION_OR_VIEW')
    for key in ('selection_date', 'announcement_date'):
        if value[key] is not None:
            trade_date(value[key])
    if value['action'] == 'refresh' and (value['selection_date'] is not None or value['announcement_date'] is not None):
        raise ValueError('MANAGER_REFRESH_USES_ORIGINAL_TARGET_BINDINGS')
    exact_keys(value['inputs'], ('manager', 'materials', 'us'))
    roots = []
    for name, binding in value['inputs'].items():
        exact_keys(binding, ('root', 'files'))
        root = no_symlinks(binding['root'])
        if not Path(binding['root']).is_absolute() or not root.is_dir():
            raise ValueError('MANAGER_INPUT_ROOT')
        roots.append(root)
        if not isinstance(binding['files'], dict) or len(binding['files']) > 8192:
            raise ValueError('MANAGER_INPUT_FILES')
        for relative, digest in binding['files'].items():
            common._relative(root, relative)
            sha(digest)
            if name == 'manager' and not relative.startswith(('us_mapping_research/', 'workspace_announcements/',
                    'workspace_announcement_runs/', 'announcement_agent_runs/')):
                raise ValueError('MANAGER_OWNER_INPUT_PATH')
            if name == 'us' and not re.fullmatch(r'(?:research/peripherals/(?:manifest\.json|[0-9]{8}/external_finance\.json)|receipts/research/peripherals/[0-9]{8}/external_finance\.json)', relative):
                raise ValueError('MANAGER_US_INPUT_PATH')
            if name == 'materials' and not re.fullmatch(r'(?:blobs/[0-9a-f]{64}|index/[0-9a-f]{64}\.json)', relative):
                raise ValueError('MANAGER_MATERIAL_INPUT_PATH')
    output = no_symlinks(value['manager_output_root'])
    if not Path(value['manager_output_root']).is_absolute() or not output.is_dir():
        raise ValueError('MANAGER_OUTPUT_ROOT')
    if any(output.is_relative_to(root) or root.is_relative_to(output) for root in roots):
        raise ValueError('MANAGER_INPUT_OUTPUT_OVERLAP')
    if no_symlinks(output / '.v5-manager-plan-root').read_bytes() != b'v5.manager-plan-root.v1\n':
        raise ValueError('MANAGER_OUTPUT_MARKER')
    if value['rebound'] is not None:
        exact_keys(value['rebound'], ('root', 'reference'))
        rebound_root = no_symlinks(value['rebound']['root'])
        if output.is_relative_to(rebound_root) or rebound_root.is_relative_to(output):
            raise ValueError('MANAGER_REBOUND_OUTPUT_OVERLAP')
    canonical_bytes(value)
    return value


def _snapshot(binding):
    result = {}; total = 0
    for relative, digest in binding['files'].items():
        path = common._relative(no_symlinks(binding['root']), relative)
        directory = _open_directory(path.parent)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        try:
            raw = _read_regular(fd, 32 * 1024 * 1024)
        finally:
            os.close(fd)
        total += len(raw)
        if total > 128 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('MANAGER_INPUT_SHA_OR_LIMIT')
        result[relative] = raw
    return result


def _identity():
    names = ('manager_plan.py', 'manager_plan_gate.py', 'manager_plan_io.py', 'a_preselection.py',
             'contracts.py', 'digests.py', 'composition.py', 'module_api.py', 'api_gateway.py',
             'shadow_store.py', 'legacy_adapter.py', 'source_capsule.py', 'provider_evidence.py', '__init__.py')
    return {name: hashlib.sha256((BASE / 'src/v5_shadow' / name).read_bytes()).hexdigest() for name in names}


def _assemble(request):
    request = _request(request)
    snapshots = {name: _snapshot(binding) for name, binding in request['inputs'].items()}
    if not sys.pycache_prefix:
        raise ValueError('MANAGER_PRIVATE_SNAPSHOT_REQUIRED')
    private = no_symlinks(sys.pycache_prefix) / 'owner-inputs'
    roots = {}
    for name, files in snapshots.items():
        root = private / name; root.mkdir(parents=True); roots[name] = root
        for relative, raw in files.items():
            target = root / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    rebound = None
    if request['rebound'] is not None:
        from v5_shadow.shadow_store import read_shadow, _ref
        rebound = read_shadow(Path(request['rebound']['root']), _ref(request['rebound']['reference']))
    workspace = load_owner()
    store_module = importlib.import_module('v4.manager_research.store')
    material_module = importlib.import_module('v4.manager_research.materials')
    bridge = importlib.import_module('v4.manager_research.us_market_bridge')
    io = importlib.import_module('infrastructure.owned_io')
    output = Path(request['manager_output_root'])
    # Construct only the original read/write primitives, without the service
    # pool or the original constructor's jobs/products/receipts mkdir side effects.
    def plan_store():
        store = store_module.ManagerResearchStore.__new__(store_module.ManagerResearchStore)
        store.root = output; store._io = io.SafeRoot(output)
        store._lock = threading.RLock(); store._held = threading.local()
        return store
    durable = plan_store()
    class OwnerStore(store_module.ManagerResearchStore):
        def _read(self, path):
            relative = path.relative_to(self.root)
            if relative.parts[0] in ('workspace_plans', 'workspace_plan_runs'):
                return durable._read(output / relative)
            return super()._read(path)
        def _write_atomic(self, path, value):
            relative = path.relative_to(self.root)
            if not re.fullmatch(r'workspace_plan(?:s|_runs)/' + request['target_date'] + r'/(?:latest|[0-9a-f]{32})\.json', str(relative)):
                raise ValueError('MANAGER_PLAN_WRITE_SCOPE')
            if request['action'] != 'refresh':
                raise ValueError('MANAGER_GET_WRITE_FORBIDDEN')
            return durable._write_atomic(output / relative, value)
        def _transaction(self, date, identity):
            if request['action'] != 'refresh' or date != request['target_date'] or identity != 'workspace-plan-refresh':
                raise ValueError('MANAGER_TRANSACTION_SCOPE')
            return durable._transaction(date, identity)
    service = SimpleNamespace(store=OwnerStore(roots['manager']),
        _material_store=material_module.MaterialStore(roots['materials']),
        observation_reader=None, _close_observation_reader=None, _existing_research_source=None,
        _catalyst_data_root=None, _catalyst_news_owner_root=None, _workspace_ledger_root=None,
        _workspace_security_master_root=None, _workspace_screen_authority_root=None,
        _workspace_us_market_reader=bridge.ResearchPeripheralUsMarketReader(roots['us']) if snapshots['us'] else None,
        get_catalyst_observations=lambda date: dict(status='CANNOT_CONFIRM', target_trade_date=date,
            cards=[], gaps=['V5_CATALYST_OWNER_NOT_BOUND'], **workspace.FLAGS))
    # History enumerates and reads through _io directly. Route those original
    # plan reads to the same durable owner, not to the private input directory.
    private_io = service.store._io
    class OverlayIO:
        def read_bytes(self, relative, **kwargs):
            selected = durable._io if str(relative).split('/')[0] in ('workspace_plans', 'workspace_plan_runs') else private_io
            return selected.read_bytes(relative, **kwargs)
        def directory(self, relative=None, **kwargs):
            selected = durable._io if str(relative).split('/')[0] in ('workspace_plans', 'workspace_plan_runs') else private_io
            return selected.directory(relative, **kwargs)
    service.store._io = OverlayIO()
    # Consume the independently committed rebound owner, never recompute its
    # algorithm within the manager. Missing evidence retains the original empty
    # screen and its UNKNOWN fields/reasons.
    original_screen = workspace.read_rebound_screen
    def committed_screen(_root, context):
        if rebound is None:
            return original_screen(None, context)
        if (rebound.request.target_trade_date != request['target_date']
                or rebound.request.research_cutoff > aware(context['research_cutoff'])
                or rebound.finished_at > aware(context['research_cutoff'])):
            value = original_screen(None, context)
            value['gaps'].append('V5_REBOUND_TARGET_OR_CUTOFF_MISMATCH')
            return value
        if rebound.business_status not in {'COMPLETED', 'VALID_EMPTY', 'PARTIAL'} or rebound.request.data_kind != 'OWNER_VERIFIED':
            value = original_screen(None, context)
            value['gaps'].append('V5_REBOUND_OWNER_ADMISSION_UNVERIFIED')
            return value
        screen = copy.deepcopy(rebound.legacy_screen)
        if screen.get('data_context', {}).get('price_signal_date') != context.get('market_session'):
            value = original_screen(None, context)
            value['gaps'].append('V5_REBOUND_PRICE_SESSION_MISMATCH')
            return value
        return screen
    workspace.read_rebound_screen = committed_screen
    violations = install_manager_boundary(io.SafeRoot, roots, output, request['target_date'],
                                         read_only=request['action'] == 'read')
    now = aware(request['now'])
    if request['action'] == 'refresh':
        payload = workspace.refresh_workspace_plan(service, request['target_date'], now=now)
        independent = plan_store()
        saved = workspace._read_plan(independent, request['target_date'])
        attempt = workspace.verified_plan_attempt(independent, saved)
        if (attempt is None or saved['run_id'] != attempt['run_id']
                or saved['run_id'] != payload['plan_product']['run_id']
                or saved['sha256'] != payload['plan_product']['sha256']
                or saved['input_identity'] != payload['input_identity']):
            raise ValueError('MANAGER_INDEPENDENT_PLAN_READBACK_MISMATCH')
        readback = dict(status='MATCHED', run_id=saved['run_id'], plan_sha256=saved['sha256'],
                        attempt=attempt, input_identity=saved['input_identity'])
    else:
        payload = workspace.get_workspace(service, request['target_date'], now=now, view=request['view'],
            selection_date=request['selection_date'], announcement_date=request['announcement_date'])
        readback = dict(status='READ_ONLY', plan_product=payload.get('plan_product'))
    if violations:
        raise ValueError('MANAGER_BOUNDARY_VIOLATION:' + ','.join(violations))
    for name, binding in request['inputs'].items():
        if _snapshot(binding) != snapshots[name]:
            raise ValueError('MANAGER_INPUT_CHANGED')
    _sources()
    return dict(schema_version='v5.manager_plan.v1', payload=payload, readback=readback,
        request_sha256=sha256_json(request), source_capsule_sha256=PIN, implementation_identity=_identity(),
        execution_kind='MANUAL_REFRESH' if request['action']=='refresh' else 'READ_ONLY',
        natural_verified=False, source_origin_verified=False, production_allowed=False,
        buy_gate_updated=False, orders_sent=False, isolation='PINNED_OWNER_PYTHON_GUARDS_NOT_OS_SANDBOX',
        owner_bindings=dict(us='ORIGINAL_EXACT_SESSION_READER_AND_SAVED_DAILY',
            announcements='ORIGINAL_SAVED_CATALOG_BODY_AND_ANALYSIS_READERS',
            rebound='COMMITTED_SHADOW_REFERENCE_REQUIRES_OWNER_ADMISSION',
            continuity='NOT_BOUND', stage='NOT_BOUND', catalyst='NOT_BOUND'))


def run_manager_plan(request):
    request = _request(request); identity = _identity()
    env = {key: value for key, value in os.environ.items() if not key.startswith('V4_')}
    with tempfile.TemporaryDirectory(prefix='v5-manager-plan-') as cache:
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'pycache_prefix='+str(Path(cache).resolve()),
            str(Path(__file__).resolve())], input=canonical_bytes(request), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, timeout=120)
    if len(result.stdout) > MAX_JSON_BYTES:
        raise ValueError('MANAGER_RESPONSE_LIMIT')
    try:
        value = json.loads(result.stdout)
    except (ValueError, UnicodeError) as error:
        raise ValueError('MANAGER_WORKER_RESPONSE:' + result.stderr.decode(errors='replace')[-2000:]) from error
    if result.returncode:
        raise ValueError(value.get('reason', 'MANAGER_WORKER_FAILED'))
    if (value.get('schema_version') != 'v5.manager_plan.v1' or value.get('request_sha256') != sha256_json(request)
            or value.get('source_capsule_sha256') != PIN or value.get('implementation_identity') != identity
            or _identity() != identity or value.get('natural_verified') is not False):
        raise ValueError('MANAGER_WORKER_IDENTITY')
    return value


def publish_workspace_read(request, config, *, expected_generation):
    """Explicit publication; HTTP GET only serves this committed generation.

    Keep the exact query identity: auto is actually computed with view=auto,
    never relabel a dynamic preview as history or populate unrelated dates.
    """
    if request['action'] != 'read':
        raise ValueError('MANAGER_API_REQUIRES_READ_RESULT')
    from v5_shadow.module_artifacts import publish_generation
    result = run_manager_plan(request)
    query = dict(date=request['target_date'], view=request['view'])
    for key in ('selection_date', 'announcement_date'):
        if request[key] is not None:
            query[key] = request[key]
    record = dict(schema_version='v5.module_response.v1', module_id=config['module_id'],
        release_id=config['release_id'], path=ROUTE, query=query, payload=result['payload'],
        payload_sha256=sha256_json(result['payload']), source_input_sha256=result['request_sha256'],
        data_kind='OWNER_RESULT', generated_at=datetime.now(timezone.utc).isoformat(), status_code=200)
    publication = publish_generation(config, [record], expected_generation=expected_generation)
    return dict(result=result, publication=publication)


if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError('MANAGER_REQUEST_LIMIT')
        print(canonical_bytes(_assemble(json.loads(raw))).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED', reason=type(error).__name__+':'+str(error))).decode())
        raise SystemExit(1)
