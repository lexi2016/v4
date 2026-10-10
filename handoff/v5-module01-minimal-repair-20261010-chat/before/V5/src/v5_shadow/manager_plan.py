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
from v5_shadow.announcement_bridge import _input_limit

BASE = Path(__file__).resolve().parents[2]
CAPSULE = BASE / 'vendor/manager_plan_baseline'
DESCRIPTOR = BASE / 'contracts/manager_plan_source_manifest.json'
PIN = '61f288f00095ce0e60adf20598123e702d855462ac7d7216334ecfd1064933f5'
ROUTE = '/api/v4/manager/research/workspace'
NAMESPACES = ('v4', 'contracts', 'infrastructure', 'ops', 'domains', 'stage_center')


class OverlayIO:
    """Original SafeRoot read protocol, with plan-owned paths routed durably."""
    def __init__(self, durable_io, private_io):
        self.durable_io = durable_io
        self.private_io = private_io

    def _reader(self, relative):
        return self.durable_io if str(relative).split('/')[0] in ('workspace_plans', 'workspace_plan_runs') else self.private_io

    def read_bytes(self, relative, **kwargs):
        return self._reader(relative).read_bytes(relative, **kwargs)

    def directory(self, relative=None, **kwargs):
        return self._reader(relative).directory(relative, **kwargs)

    def files(self, relative=None, *, suffix='.json'):
        return self._reader(relative).files(relative, suffix=suffix)


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
    required = ('target_date', 'now', 'action', 'view', 'selection_date',
                'announcement_date', 'inputs', 'rebound', 'manager_output_root')
    exact_keys(value, required + tuple(key for key in ('rebound_owner','membership','registry_observation','rebound_observation','announcement_offline_owner') if key in value))
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
    exact_keys(value['inputs'], ('manager','materials','us')+tuple(key for key in ('archives','native_master') if key in value['inputs']))
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
            if name=='native_master' and not relative.startswith('assets/hk_security_master/'):
                raise ValueError('MANAGER_NATIVE_MASTER_INPUT_PATH')
            if name == 'archives':
                from v5_shadow.archive_reader import PATTERN
                if relative != 'manifest.json' and not re.fullmatch(PATTERN, relative):
                    raise ValueError('MANAGER_ARCHIVE_INPUT_PATH')
            if name == 'manager' and not relative.startswith(('us_mapping_research/', 'workspace_announcements/',
                    'workspace_announcement_runs/', 'announcement_agent_runs/')):
                raise ValueError('MANAGER_OWNER_INPUT_PATH')
            if name == 'us' and not re.fullmatch(r'(?:research/peripherals/(?:manifest\.json|[0-9]{8}/external_finance\.json)|receipts/research/peripherals/[0-9]{8}/external_finance\.json)', relative):
                raise ValueError('MANAGER_US_INPUT_PATH')
            if name == 'materials' and not re.fullmatch(r'(?:blobs/[0-9a-f]{64}|index/[0-9a-f]{64}\.json)', relative):
                raise ValueError('MANAGER_MATERIAL_INPUT_PATH')
    if 'archives' in value['inputs']:
        archive_root = no_symlinks(value['inputs']['archives']['root'])
        for name, binding in value['inputs'].items():
            if name != 'archives':
                other = no_symlinks(binding['root'])
                if archive_root.is_relative_to(other) or other.is_relative_to(archive_root):
                    raise ValueError('MANAGER_ARCHIVE_ROOT_OVERLAP')
    if 'archives' in value['inputs'] and 'manifest.json' not in value['inputs']['archives']['files']:
        raise ValueError('MANAGER_ARCHIVE_MANIFEST_REQUIRED')
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
    if value.get('rebound_owner') is not None:
        binding = value['rebound_owner']
        exact_keys(binding, ('root', 'reference'))
        observed_root = no_symlinks(binding['root'])
        isolated_roots = [output, *roots]
        if value['rebound'] is not None:
            isolated_roots.append(rebound_root)
        for other in isolated_roots:
            if observed_root.is_relative_to(other) or other.is_relative_to(observed_root):
                raise ValueError('MANAGER_REBOUND_OWNER_ROOT_OVERLAP')
        reference = binding['reference']
        exact_keys(reference, ('run_id', 'artifact_sha256', 'manifest_sha256', 'receipt_sha256'))
        if not re.fullmatch(r'[0-9a-f]{32}', str(reference['run_id'])):
            raise ValueError('MANAGER_REBOUND_OWNER_RUN_ID')
        for key in ('artifact_sha256', 'manifest_sha256', 'receipt_sha256'):
            sha(reference[key])
    if value.get('membership') is not None:
        from v5_shadow.membership_reader import OWNER_SHA
        membership = value['membership']
        exact_keys(membership, ('root','files','authority_owner_sha256','require_v2'))
        if membership['require_v2'] is not True or membership['authority_owner_sha256'] != OWNER_SHA:
            raise ValueError('MANAGER_MEMBERSHIP_OWNER_BINDING')
        membership_root = no_symlinks(membership['root'])
        others = [output,*roots]
        for key in ('rebound','rebound_owner'):
            if value.get(key) is not None:others.append(no_symlinks(value[key]['root']))
        if any(membership_root.is_relative_to(other) or other.is_relative_to(membership_root) for other in others):
            raise ValueError('MANAGER_MEMBERSHIP_ROOT_OVERLAP')
        if not isinstance(membership['files'],dict) or len(membership['files']) != 7:
            raise ValueError('MANAGER_MEMBERSHIP_SEVEN_FILES')
        for relative,digest in membership['files'].items():
            common._relative(membership_root,relative);sha(digest)
            if not relative.startswith('universes/'+value['target_date']+'/') or not relative.endswith('.json'):
                raise ValueError('MANAGER_MEMBERSHIP_PATH')
    if value.get('announcement_offline_owner') is not None:
        binding=value['announcement_offline_owner']
        exact_keys(binding, ('root','binding_sha256','target_date','publication_date')+
            (('revision_manifest_sha256',) if 'revision_manifest_sha256' in binding else ()))
        if 'revision_manifest_sha256' in binding:sha(binding['revision_manifest_sha256'])
        root=no_symlinks(binding['root'])
        if not Path(binding['root']).is_absolute():raise ValueError('OFFLINE_MANAGER_ROOT')
        if root.is_relative_to(output) or output.is_relative_to(root):raise ValueError('OFFLINE_MANAGER_OUTPUT_OVERLAP')
        sha(binding['binding_sha256']);trade_date(binding['target_date'])
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',str(binding['publication_date'])):
            raise ValueError('OFFLINE_MANAGER_PUBLICATION_DATE')
        trade_date(binding['publication_date'].replace('-',''))
        if binding['target_date']!=value['target_date']:raise ValueError('OFFLINE_MANAGER_TARGET_DATE')
    if value.get('rebound_observation') is not None:
        binding=value['rebound_observation']
        exact_keys(binding, ('root','reference'))
        observed_root=no_symlinks(binding['root'])
        if not Path(binding['root']).is_absolute():raise ValueError('MANAGER_PANEL_OBSERVATION_ROOT')
        others=[output,*roots]
        for key in ('rebound','rebound_owner','membership','registry_observation'):
            if value.get(key) is not None:others.append(no_symlinks(value[key]['root']))
        if any(observed_root.is_relative_to(other) or other.is_relative_to(observed_root) for other in others):
            raise ValueError('MANAGER_PANEL_OBSERVATION_ROOT_OVERLAP')
        exact_keys(binding['reference'], ('run_id','artifact_sha256','manifest_sha256','receipt_sha256'))
        if not re.fullmatch(r'[0-9a-f]{32}',str(binding['reference']['run_id'])):
            raise ValueError('MANAGER_PANEL_OBSERVATION_RUN_ID')
        for key in ('artifact_sha256','manifest_sha256','receipt_sha256'):sha(binding['reference'][key])
    if value.get('registry_observation') is not None:
        registry = value['registry_observation']
        exact_keys(registry, ('root','files','source_date','source_label','format'))
        registry_root = no_symlinks(registry['root'])
        if not Path(registry['root']).is_absolute() or not registry_root.is_dir():
            raise ValueError('REGISTRY_ROOT')
        others = [output, *roots]
        for key in ('rebound','rebound_owner','membership'):
            if value.get(key) is not None: others.append(no_symlinks(value[key]['root']))
        if any(registry_root.is_relative_to(other) or other.is_relative_to(registry_root) for other in others):
            raise ValueError('REGISTRY_ROOT_OVERLAP')
        if not isinstance(registry['files'], dict) or len(registry['files']) != 1:
            raise ValueError('REGISTRY_SINGLE_RAW_FILE_REQUIRED')
        for relative, digest in registry['files'].items():
            common._relative(registry_root, relative); sha(digest)
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
            raw = _read_regular(fd, _input_limit(relative))
        finally:
            os.close(fd)
        total += len(raw)
        if total > 64 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('MANAGER_INPUT_SHA_OR_LIMIT')
        result[relative] = raw
    return result


def _identity():
    names = ('native_identity_reader.py', 'hk_preselection.py', 'us_mapping_scope.py', 'announcement_offline_reader.py', 'manager_panel_observation.py', 'rebound_observation.py', 'registry_observation.py', 'membership_reader.py', 'hk_membership_recovery.py', 'rebound_owner.py', 'health.py', 'module_artifacts.py', 'archive_reader.py', 'archive_article_v2.py', 'archive_builder_v1.py', 'announcement_bridge.py', 'manager_plan.py', 'manager_plan_gate.py', 'manager_plan_io.py', 'a_preselection.py',
             'contracts.py', 'digests.py', 'composition.py', 'module_api.py', 'api_gateway.py',
             'shadow_store.py', 'legacy_adapter.py', 'source_capsule.py', 'provider_evidence.py', '__init__.py')
    return {name: hashlib.sha256((BASE / 'src/v5_shadow' / name).read_bytes()).hexdigest() for name in names}


def _plan_store_scope(request, hk):
    """Separate late current research from the original historical plan store."""
    output = no_symlinks(Path(request['manager_output_root']))
    past = request['target_date'] < aware(request['now']).astimezone(hk).strftime('%Y%m%d')
    if past and (request['action'] == 'refresh' or request['view'] in ('auto', 'dynamic')):
        recovery = no_symlinks(output / 'current_recovery')
        head = no_symlinks(recovery / 'workspace_plans' / request['target_date'] / 'latest.json')
        # A different target's recovery, or an uncommitted directory, cannot
        # hide this target's original historical qualification result.
        if request['action'] == 'refresh' or head.exists():
            return recovery, True
    return output, False


def _mark_current_recovery(payload, request):
    """Describe a native dynamic read truthfully without changing its plan SHA."""
    product = payload.get('plan_product', {})
    if product.get('status') == 'CURRENT' and product.get('consumed') is True:
        product.update(status='CURRENT_RECOVERY', owner_status='CURRENT')
    product['historical_eligible'] = False
    payload['read_context'].update(mode='CURRENT_RECOVERY',
        requested_view=request['view'], owner_view='dynamic', read_as_of=request['now'],
        historical_eligible=False, v5_contract='v5.manager_current_recovery.v1')
    payload['observation_mode'] = ('CURRENT_RECOVERY_PLAN_READBACK'
        if product.get('consumed') is True else 'CURRENT_RECOVERY_PREVIEW')
    # These channels were already checked by the original owner before the
    # response-only status discriminator above. Keep its execution references
    # and stock/admission results; add the same explicit nonhistorical scope.
    payload['daily_channels'].update(read_scope='CURRENT_RECOVERY', historical_eligible=False)


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
    registry_snapshot = None; registry_rows = None; registry_error = None
    if request.get('registry_observation') is not None:
        from v5_shadow.registry_observation import decode, project, clock
        registry_started = clock()
        try:
            registry_snapshot = _snapshot(request['registry_observation'])
            registry_root = private/'registry'; registry_root.mkdir(); roots['registry']=registry_root
            for relative, raw in registry_snapshot.items():
                target=registry_root/relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            registry_private_binding = dict(request['registry_observation'], root=str(registry_root))
            if _snapshot(registry_private_binding) != registry_snapshot:
                raise ValueError('REGISTRY_PRIVATE_COPY_MISMATCH')
            registry_rows = decode(next(iter(registry_snapshot.values())), request['registry_observation'])
        except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
            registry_error = str(error) if isinstance(error, ValueError) else 'REGISTRY_READ_FAILED:' + type(error).__name__
    membership_readback = None; membership_snapshot = None
    if request.get('membership') is not None:
        from v5_shadow.membership_reader import read_private as read_membership, install_transport
        membership_root = private/'membership';membership_root.mkdir();roots['membership']=membership_root
        try:
            membership_snapshot = _snapshot(request['membership'])
            for relative,raw in membership_snapshot.items():
                target=membership_root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            membership_readback = read_membership(membership_root,request['membership']['files'],request['target_date'])
        except (OSError,ValueError,KeyError,TypeError) as error:
            membership_readback = dict(target_date=request['target_date'],error=str(error) if isinstance(error,ValueError) else 'MEMBERSHIP_INPUT_READ_FAILED:'+type(error).__name__)
    archive_readback = None
    if 'archives' in roots:
        from v5_shadow.archive_reader import read_private, source_proxy
        archive_readback = read_private(roots['archives'], request['inputs']['archives'])
    rebound = None
    if request['rebound'] is not None:
        from v5_shadow.shadow_store import read_shadow, _ref
        rebound = read_shadow(Path(request['rebound']['root']), _ref(request['rebound']['reference']))
    observation_artifact = None; observation_error = None
    if request.get('rebound_owner') is not None:
        from v5_shadow.rebound_owner import read_rebound_owner, manager_projection, SAFETY as observation_safety
        observation_binding = request['rebound_owner']
        try:
            observation_artifact = read_rebound_owner(observation_binding['root'], observation_binding['reference'])
        except (OSError, ValueError, KeyError, TypeError) as error:
            observation_error = str(error) if isinstance(error, ValueError) else 'REBOUND_OWNER_READ_FAILED:' + type(error).__name__
    panel_artifact=None; panel_error=None
    if request.get('rebound_observation') is not None:
        from v5_shadow.rebound_observation import read_rebound_observation, SAFETY as panel_safety
        panel_binding=request['rebound_observation']
        try:
            panel_artifact=read_rebound_observation(panel_binding['root'],panel_binding['reference'])
        except (OSError,ValueError,KeyError,TypeError) as error:
            panel_error=str(error) if isinstance(error,ValueError) else 'PANEL_OBSERVATION_READ_FAILED:'+type(error).__name__
    offline_result=None;offline_error=None
    if request.get('announcement_offline_owner') is not None:
        from v5_shadow.announcement_offline_reader import read_owner, install_transport as install_offline_transport
        try:offline_result=read_owner(request['announcement_offline_owner'],request['now'])
        except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as error:
            offline_error=str(error) if isinstance(error,ValueError) else 'OFFLINE_MANAGER_READ_FAILED:'+type(error).__name__
    workspace = load_owner()
    native_identity_readback=None
    if 'native_master' in roots:
        from v5_shadow.native_identity_reader import read_private as read_native,install_transport as install_native
        from v4.manager_research.workspace_plan import plan_context
        native_day=plan_context(request['target_date'],now=aware(request['now']))['market_session']
        try:
            native_identity_readback=read_native(dict(root=str(roots['native_master']),files=request['inputs']['native_master']['files']),native_day)
        except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as error:
            native_identity_readback=dict(error=str(error) if isinstance(error,ValueError) else 'NATIVE_IDENTITY_READ_FAILED:'+type(error).__name__)
        install_native(roots['native_master'],native_day,native_identity_readback)
    if membership_readback is not None:
        install_transport(roots['membership'],membership_readback)
    store_module = importlib.import_module('v4.manager_research.store')
    material_module = importlib.import_module('v4.manager_research.materials')
    bridge = importlib.import_module('v4.manager_research.us_market_bridge')
    io = importlib.import_module('infrastructure.owned_io')
    output, current_recovery = _plan_store_scope(request, workspace.HK)
    if current_recovery and request['action'] == 'refresh':
        # Original dir-fd I/O creates only the new store. Neither old plans nor
        # their exact-date latest pointers are used as a recovery destination.
        io.SafeRoot(request['manager_output_root']).ensure_directory('current_recovery')
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
        observation_reader=None, _close_observation_reader=None,
        _existing_research_source=source_proxy(archive_readback) if archive_readback is not None else None,
        _catalyst_data_root=None, _catalyst_news_owner_root=None, _workspace_ledger_root=None,
        _workspace_security_master_root=roots.get('native_master'), _workspace_screen_authority_root=None,
        _workspace_us_market_reader=bridge.ResearchPeripheralUsMarketReader(roots['us']) if snapshots['us'] else None,
        get_catalyst_observations=lambda date: dict(status='CANNOT_CONFIRM', target_trade_date=date,
            cards=[], gaps=['V5_CATALYST_OWNER_NOT_BOUND'], **workspace.FLAGS))
    # Preserve the original analysis -> exact catalog -> handoff/cutoff reader
    # chain on the same private inputs; no full service or collector is loaded.
    analysis = importlib.import_module('v4.manager_research.announcement_analysis')
    announcements = importlib.import_module('v4.manager_research.workspace_announcements')
    service.get_announcement_date_catalog = lambda date, publication: announcements.read_date_catalog(service, date, publication)
    service.get_announcement_analysis = lambda date, publication=None: analysis.read(service, date, publication)
    if request.get('announcement_offline_owner') is not None:
        install_offline_transport(service,announcements,request['announcement_offline_owner'],offline_result,offline_error)
    # History enumerates and reads through _io directly. Route those original
    # plan reads to the same durable owner, not to the private input directory.
    service.store._io = OverlayIO(durable._io, service.store._io)
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
        owner_view = 'dynamic' if current_recovery else request['view']
        if current_recovery:
            original_plan_attempt = workspace.verified_plan_attempt
            def recovery_plan_attempt(store, saved):
                attempt = original_plan_attempt(store, saved)
                if attempt is None:
                    raise ValueError('CURRENT_RECOVERY_EXACT_OWNER_ATTEMPT_MISSING')
                return attempt
            # The original manual legacy path allows no journal. A new
            # recovery requires its exact journal before native readback and
            # daily channel projections can describe any saved consumption.
            workspace.verified_plan_attempt = recovery_plan_attempt
        payload = workspace.get_workspace(service, request['target_date'], now=now, view=owner_view,
            selection_date=request['selection_date'], announcement_date=request['announcement_date'])
        readback = dict(status='READ_ONLY', plan_product=payload.get('plan_product'))
    readback['store_relative'] = 'current_recovery' if current_recovery else '.'
    if current_recovery:
        _mark_current_recovery(payload, request)
    from v5_shadow.us_mapping_scope import describe_scope
    mapping_payload=payload.get('us_mapping_research')
    if isinstance(mapping_payload,dict):
        mapping_owner=importlib.import_module('v4.manager_research.us_mapping_research')
        mapping_payload['coverage_diagnostics']=describe_scope(mapping_payload.get('daily_run') or {},
            payload.get('us_market_attention') or {},mapping_owner._read_reviewed())
    if request.get('rebound_owner') is not None:
        # Independent read-time observation, never feed legacy_diagnostic into
        # the formal screen, selection algorithm or immutable saved workspace.
        context = payload.get('plan_context') or {}
        if observation_artifact is not None:
            try:
                if read_rebound_owner(observation_binding['root'], observation_binding['reference']) != observation_artifact:
                    raise ValueError('REBOUND_OWNER_CHANGED_DURING_MANAGER_READ')
                observation = manager_projection(observation_artifact,
                    target_date=request['target_date'], research_cutoff=context['research_cutoff'],
                    market_session=context['market_session'])
            except (OSError, ValueError, KeyError, TypeError) as error:
                observation_error = str(error) if isinstance(error, ValueError) else 'REBOUND_OWNER_READ_FAILED:' + type(error).__name__
        if observation_error is not None:
            observation = dict(status='CANNOT_CONFIRM', eligible_screen=None,
                research_observation=None, reason_codes=[observation_error],
                source_run_id=observation_binding['reference']['run_id'], **observation_safety)
        observation['binding_reference'] = copy.deepcopy(observation_binding['reference'])
        observation['scope'] = 'INDEPENDENT_READ_TIME_OBSERVATION_NOT_SAVED_PLAN_OR_FORMAL_SELECTION'
        payload['rebound_research_observation'] = observation
    if request.get('rebound_observation') is not None:
        if panel_artifact is not None:
            try:
                if read_rebound_observation(panel_binding['root'],panel_binding['reference']) != panel_artifact:
                    raise ValueError('PANEL_OBSERVATION_CHANGED_DURING_READ')
                context=payload.get('plan_context') or {}
                from v5_shadow.manager_panel_observation import current_observation
                panel_observation=current_observation(panel_artifact,target_date=request['target_date'],
                    market_session=context['market_session'],plan_research_cutoff=context['research_cutoff'],view=request['view'])
            except (OSError,ValueError,KeyError,TypeError) as error:
                panel_error=str(error) if isinstance(error,ValueError) else 'PANEL_OBSERVATION_READ_FAILED:'+type(error).__name__
        if panel_error is not None:
            panel_observation=dict(rows=None,computation_status='CANNOT_CONFIRM',reason_codes=[panel_error],
                source_run_id=panel_binding['reference']['run_id'],**panel_safety)
        panel_observation['binding_reference']=copy.deepcopy(panel_binding['reference'])
        panel_observation['scope']='INDEPENDENT_CURRENT_PANEL_OBSERVATION_NOT_SAVED_PLAN_OR_SELECTION'
        from v5_shadow.manager_panel_observation import summarize
        payload['rebound_panel_observation']=summarize(panel_observation)
    if request.get('registry_observation') is not None:
        if registry_error is None:
            observation = project(registry_rows, request['registry_observation'], archive_readback, registry_started)
            if (_snapshot(request['registry_observation']) != registry_snapshot or
                    _snapshot(registry_private_binding) != registry_snapshot):
                raise ValueError('REGISTRY_CHANGED_DURING_READ')
            observation['read_receipt'].update(observed_finished_at=clock(), before_after_raw_sha256_stable=True)
        else:
            observation = dict(status='CANNOT_CONFIRM', clues=[], reason_codes=[registry_error],
                formal_eligible=False, fresh_catalyst_eligible=False, natural_verified=False,
                scope='INDEPENDENT_CURRENT_READ_NOT_SAVED_PLAN_OR_FORMAL_SELECTION')
        payload['registry_research_observation'] = observation
    if violations:
        raise ValueError('MANAGER_BOUNDARY_VIOLATION:' + ','.join(violations))
    for name, binding in request['inputs'].items():
        if _snapshot(binding) != snapshots[name]:
            raise ValueError('MANAGER_INPUT_CHANGED')
    if membership_snapshot is not None and _snapshot(request['membership']) != membership_snapshot:
        raise ValueError('MANAGER_MEMBERSHIP_INPUT_CHANGED')
    _sources()
    archive_diagnostics = None if archive_readback is None else dict(
        source_capsule_sha256=archive_readback['source_capsule_sha256'],
        article_v2_source_sha256=archive_readback['article_v2_source_sha256'],
        validated_artifacts=sum(row.get('payload') is not None for row in archive_readback['records'].values()),
        rejected_artifacts={key:row['error'] for key,row in archive_readback['records'].items() if 'error' in row},
        rejected_slot_lists={key:row['error'] for key,row in archive_readback['slots'].items() if 'error' in row},
        supplied_file_sha256=request['inputs']['archives']['files'],
        coverage_basis='BOUND_FILES_AND_ORIGINAL_MANIFEST_NOT_FULL_MARKET')
    return dict(schema_version='v5.manager_plan.v1', payload=payload, readback=readback, archive_readback=archive_diagnostics,
        membership_readback=membership_readback,
        native_identity_readback=None if native_identity_readback is None else dict(
            error=native_identity_readback.get('error'),owner_source_sha256=native_identity_readback.get('owner_source_sha256'),
            manifest=native_identity_readback.get('manifest'),role='REFERENCE_SESSION_IDENTITY_NOT_TARGET_CONNECT_MEMBERSHIP'),
        announcement_offline_readback=None if request.get('announcement_offline_owner') is None else dict(
            status='VERIFIED_READ_TRANSPORT' if offline_error is None else 'CANNOT_CONFIRM',
            error=offline_error,binding=request['announcement_offline_owner'],
            consumption=None if offline_result is None else offline_result['consumption']),
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

    Keep the exact query identity. Auto may explicitly select a committed
    CURRENT_RECOVERY dynamic read for that target; it never labels it history
    or populates unrelated dates. Explicit history retains the original gate.
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
