"""Explicit, isolated announcement context. No production service is constructed.

Fixture is display evidence only. Readonly uses the authoritative reader with
explicit authorities; unavailable semantic authority stays UNREVIEWED. A real
single-article request is possible only with a separately frozen Task8 manifest.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from infrastructure.owned_io import SafeRoot
from .announcement_update import AnnouncementUpdate
from .announcement_candidate import CandidateEvidenceError
from .contracts import JobState, validate_date

PREFIX = '/api/v4/announcement-test'
REPO = Path(__file__).resolve().parents[2]
SAFETY = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SHA = re.compile(r'^[a-f0-9]{64}$')
PROTECTED = [Path('/Users/lexi/Desktop/学习/v4_app'),
    Path('/Users/lexi/Library/Application Support/com.lexi.v4.local'),
    Path('/Users/lexi/Library/Application Support/com.lexi.v35.local'),
    Path('/Users/lexi/Desktop/学习/v3_system')]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(value: str | Path, *, within: Path | None = None) -> Path:
    p = Path(value)
    if not p.is_absolute() or '..' in p.parts or any(x.is_symlink() for x in (p, *p.parents)):
        raise ValueError('TEST_PATH_UNSAFE')
    if any(p == root or root in p.parents or p in root.parents for root in PROTECTED):
        raise ValueError('TEST_PRODUCTION_ROOT_FORBIDDEN')
    if within is not None and (p == within or within not in p.parents):
        raise ValueError('TEST_PATH_OUTSIDE_ROOT')
    return p


def envelope(value: Any) -> dict:
    return dict(schema_version='v4.manager_workbench.v1', state=value.get('state', 'READY'), data=value, gaps=[], **SAFETY)


class FrozenIO(SafeRoot):
    """Only enumerated immutable material is readable, including nested refs."""
    def __init__(self, root: Path, inventory: dict[str, str], *, logical_root=None, declared_sizes=None):
        super().__init__(root)
        self.inventory = inventory
        self.logical_root = logical_root
        self.declared_sizes = declared_sizes or {}

    def read_bytes(self, relative, *, max_bytes=64*1024*1024):
        self._parts(relative)
        expected = self.inventory.get(relative)
        if expected is None:
            raise FileNotFoundError('TEST_MATERIAL_NOT_ENUMERATED')
        declared = self.declared_sizes.get(relative)
        capture_product = (self.logical_root == 'capture'
            and SHA.fullmatch(str(expected)) and relative == 'products/'+expected+'.json')
        if declared is not None:
            if type(declared) is not int or declared < 0:
                raise ValueError('TEST_MATERIAL_SIZE_INVALID')
        # Only this explicitly enumerated content-addressed capture kind shares
        # the original capture reader's bounded 256MiB contract. Other roots and
        # objects retain 64MiB, even when their names look like capture products.
        if capture_product and declared is not None and max_bytes in (64*1024*1024, 256*1024*1024):
            if declared > 256*1024*1024:
                raise ValueError('TEST_CAPTURE_SIZE_LIMIT')
            max_bytes = 256*1024*1024
        else:
            max_bytes = min(max_bytes, 64*1024*1024)
        raw = super().read_bytes(relative, max_bytes=max_bytes)
        if declared is not None and len(raw) != declared:
            raise ValueError('TEST_MATERIAL_SIZE_CHANGED')
        if digest(raw) != expected:
            raise ValueError('TEST_SOURCE_DRIFT')
        return raw

    def files(self, relative):
        prefix = '/'.join(self._parts(relative)) + '/'
        return sorted({name[len(prefix):].split('/')[0] for name in self.inventory if name.startswith(prefix)})

    def write_bytes(self, *_args, **_kwargs):
        raise ValueError('TEST_READONLY_WRITE_FORBIDDEN')

    def ensure_directory(self, *_args, **_kwargs):
        raise ValueError('TEST_READONLY_WRITE_FORBIDDEN')


class ReadonlyIO(SafeRoot):
    """Generated isolated results are readable but GET has no write capability."""
    write_bytes = FrozenIO.write_bytes
    ensure_directory = FrozenIO.ensure_directory


@dataclass
class TestContext:
    __test__ = False
    path: Path
    expected_sha256: str
    allowed_test_root: Path
    value: dict
    roots: dict[str, Path]
    inventories: dict[str, dict[str, str]]
    inventory_sizes: dict[str, dict[str, int]]

    @classmethod
    def load(cls, path: Path, expected_sha256: str, *, allowed_test_root: Path):
        allowed = _path(allowed_test_root)
        path = _path(path, within=allowed)
        raw = SafeRoot(path.parent).read_bytes(path.name)
        if not SHA.fullmatch(expected_sha256) or digest(raw) != expected_sha256:
            raise ValueError('TEST_CONTEXT_SHA_CHANGED')
        value = json.loads(raw)
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(value.get('test_run_id', '')))
                or value.get('mode', 'fixture') not in {'fixture', 'readonly', 'canary'}):
            raise ValueError('TEST_CONTEXT_INVALID')
        value.setdefault('mode', 'fixture')
        validate_date(value['target_date'])
        state = _path(value['independent_state_root'], within=allowed)
        roots = {role: _path(root, within=allowed) for role, root in value['read_only_material_roots'].items()}
        if not roots or any(state == p or p in state.parents or state in p.parents for p in roots.values()):
            raise ValueError('TEST_STATE_MATERIAL_OVERLAP')
        manifest_ref = value['source_manifest']
        manifest_path = _path(manifest_ref['path'], within=allowed)
        if not any(p in manifest_path.parents for p in roots.values()):
            raise ValueError('TEST_MANIFEST_OUTSIDE_MATERIAL')
        manifest_raw = SafeRoot(manifest_path.parent).read_bytes(manifest_path.name)
        if not SHA.fullmatch(str(manifest_ref['sha256'])) or digest(manifest_raw) != manifest_ref['sha256']:
            raise ValueError('TEST_MANIFEST_SHA_CHANGED')
        inventory = {role: {} for role in roots}
        sizes = {role: {} for role in roots}
        for entry in json.loads(manifest_raw)['files']:
            role, ref, sha = entry['root'], entry['artifact_ref'], entry['sha256']
            if role not in roots or not SHA.fullmatch(str(sha)) or ref in inventory[role]:
                raise ValueError('TEST_MANIFEST_ENTRY_INVALID')
            SafeRoot._parts(ref)
            inventory[role][ref] = sha
            if 'bytes' in entry:
                sizes[role][ref] = entry['bytes']
        instance = cls(path, expected_sha256, allowed, value, roots, inventory, sizes)
        instance.verify()
        return instance

    def io(self, role: str) -> FrozenIO:
        return FrozenIO(self.roots[role], self.inventories[role], logical_root=role,
            declared_sizes=self.inventory_sizes[role])

    def verify(self):
        _path(self.allowed_test_root)
        _path(self.path, within=self.allowed_test_root)
        if digest(SafeRoot(self.path.parent).read_bytes(self.path.name)) != self.expected_sha256:
            raise ValueError('TEST_CONTEXT_SHA_CHANGED')
        state = _path(self.value['independent_state_root'], within=self.allowed_test_root)
        for role, root in self.roots.items():
            _path(root, within=self.allowed_test_root)
            if root == state or root in state.parents or state in root.parents:
                raise ValueError('TEST_STATE_MATERIAL_OVERLAP')
            io = self.io(role)
            for ref in self.inventories[role]:
                io.read_bytes(ref)
            manifest_path = Path(self.value['source_manifest']['path'])
            for entry in root.rglob('*'):
                if entry.is_symlink():
                    raise ValueError('TEST_MATERIAL_SYMLINK_FORBIDDEN')
                if entry.is_file() and entry != manifest_path and entry.relative_to(root).as_posix() not in self.inventories[role]:
                    raise ValueError('TEST_MATERIAL_NOT_ENUMERATED')
        manifest = self.value['source_manifest']
        p = _path(manifest['path'], within=self.allowed_test_root)
        if digest(SafeRoot(p.parent).read_bytes(p.name)) != manifest['sha256']:
            raise ValueError('TEST_MANIFEST_SHA_CHANGED')
        codes = self.value.get('code_identity')
        if not isinstance(codes, dict) or not codes:
            raise ValueError('TEST_CODE_IDENTITY_MISSING')
        for ref, expected in codes.items():
            SafeRoot._parts(ref)
            if not SHA.fullmatch(str(expected)) or digest(SafeRoot(REPO).read_bytes(ref)) != expected:
                raise ValueError('TEST_CODE_DRIFT')
        if (not SHA.fullmatch(str(self.value.get('config_identity','')))
                or not self.value.get('model_identity',{}).get('model_id')
                or not SHA.fullmatch(str(self.value['model_identity'].get('configuration_sha256','')))):
            raise ValueError('TEST_CONFIG_MODEL_IDENTITY_INVALID')
        if self.value['mode'] != 'fixture':
            required = {'state','capture','shared','config'}
            if not required.issubset(self.roots):
                raise ValueError('TEST_READONLY_ROOTS_MISSING')
            raw = self.io('config').read_bytes('config.json')
            config = json.loads(raw)
            if (digest(raw) != self.value['config_identity'] or config.get('model_identity') != self.value['model_identity']):
                raise ValueError('TEST_CONFIG_BINDING_CHANGED')
            if self.value['model_identity']['model_id'] != 'qwen3_8_flash_next':
                raise ValueError('TEST_EXPLICIT_FLASH_MODEL_REQUIRED')
            required_codes = {'v4/manager_workbench/announcement_test.py', 'v4/manager_workbench/announcement_update.py',
                'v4/manager_workbench/announcement_projection.py','v4/manager_workbench/announcement_delivery.py',
                'ops/run_manager_flash_announcements.py','infrastructure/model_execution_gate.py'}
            if not required_codes.issubset(codes):
                raise ValueError('TEST_CODE_IDENTITY_INCOMPLETE')

    def public(self):
        self.verify()
        canary_allowed = self.value['mode'] == 'canary' and self.value.get('canary',{}).get('approval_stage') == 'TASK8_FROZEN_SINGLE_ARTICLE'
        if canary_allowed:
            try: ReadonlyIO(self.value['independent_state_root']).read_bytes('test-canary-attempt.json')
            except FileNotFoundError: pass
            else: canary_allowed = False
        return {**{k: deepcopy(self.value[k]) for k in ('test_run_id','target_date','mode','read_only_material_roots',
                'independent_state_root','code_identity','config_identity','model_identity')},
            'source_manifest_sha256': self.value['source_manifest']['sha256'],
            'canary_allowed': canary_allowed,
            'evidence_kind': 'FIXTURE_NOT_PRODUCTION_EVIDENCE' if self.value['mode']=='fixture' else 'ISOLATED_SAVED_MATERIAL_NOT_NATURAL_EXECUTION'}

    def first_authority(self, state_io):
        """Only a descriptor in this SHA-verified context grants FIRST custody."""
        descriptor = self.value.get('first_semantic_authority')
        if descriptor is None:
            return None
        from .announcement_semantic_authority import FirstSemanticAuthority
        code_ref = 'v4/manager_workbench/announcement_semantic_authority.py'
        if self.value['code_identity'].get(code_ref) != digest(SafeRoot(REPO).read_bytes(code_ref)):
            raise ValueError('TEST_FIRST_AUTHORITY_CODE_UNBOUND')
        return FirstSemanticAuthority(descriptor, state_io=state_io,
            capture_io=self.io('capture'), authority_io=self.io('config'), code_io=SafeRoot(REPO),
            context_binding={'run_id':self.value['test_run_id'], 'context_sha256':self.expected_sha256,
                'source_manifest_sha256':self.value['source_manifest']['sha256']})

    def read_flash(self):
        self.verify()
        if self.value['mode'] == 'fixture':
            value = json.loads(self.io('fixture').read_bytes('fixture.json'))
        else:
            io = self.io('state')
            read_root = self.roots['state']
            if self.value['mode'] == 'canary':
                runtime = ReadonlyIO(self.value['independent_state_root'])
                try:
                    marker = json.loads(runtime.read_bytes('test-canary-attempt.json'))
                except FileNotFoundError:
                    pass
                else:
                    if marker != {'test_run_id':self.value['test_run_id'],
                            'source_manifest_sha256':self.value['source_manifest']['sha256']}:
                        raise ValueError('TEST_RUNTIME_SOURCE_CHANGED')
                    io, read_root = runtime, runtime.root
            def cursor(name):
                try: return json.loads(io.read_bytes('cursors/'+name+'.json'))
                except FileNotFoundError: return None
            def get_job(job_id):
                try: item = json.loads(io.read_bytes('attempts/'+job_id+'.json'))
                except FileNotFoundError: raise KeyError(job_id) from None
                context = SimpleNamespace(**item['context'])
                fields = {k:item.get(k) for k in ('step','completed_count','total_count','failure_code','last_progress_at','finished_at')}
                return SimpleNamespace(**fields,job_id=job_id,context=context,state=JobState(item['state']),failed_steps=item.get('failed_steps',[]))
            service = SimpleNamespace(store=SimpleNamespace(root=read_root,io=io,cursor=cursor),
                jobs=SimpleNamespace(get=get_job), config=SimpleNamespace(shared_root=self.roots['shared'],
                    capture_root=self.roots['capture'],source_bindings={}))
            def pinned():
                raise CandidateEvidenceError('TEST_HISTORICAL_PIN_NOT_AUTHENTICATED')
            def semantic(job_id, report_sha):
                return {'job_id':job_id,'report_sha256':report_sha,'eligible':False,
                        'status':'BLOCKED','reason':'TEST_SEMANTIC_AUTHORITY_UNBOUND','quarantined_results':[]}
            class ContextReader(AnnouncementUpdate):
                def resume_snapshot(self, target_date):
                    return {'eligible':False,'status':'BLOCKED','reason':'TEST_READONLY_CONTEXT','target_date':target_date}
            # Both authorities are mandatory here. Never fall back to the live
            # historical pin, runtime helper/config or production service.
            reader = ContextReader(service,pinned_reader=pinned,semantic_reader=semantic,
                first_authority=self.first_authority(io))
            value = reader.read(self.value['target_date'])
            value['current_pointer'] = cursor('announcement_flash_latest')
        value = deepcopy(value)
        value['test_evidence_kind'] = self.public()['evidence_kind']
        value['test_context_binding'] = {'test_run_id':self.value['test_run_id'],
            'target_date':self.value['target_date'],'source_manifest_sha256':self.value['source_manifest']['sha256']}
        value.update(SAFETY)
        return value

    def execute_canary(self, *, execute=subprocess.run):
        self.verify()
        plan = self.value.get('canary', {})
        if self.value['mode'] != 'canary' or plan.get('approval_stage') != 'TASK8_FROZEN_SINGLE_ARTICLE':
            raise ValueError('TEST_CANARY_NOT_AUTHORIZED')
        from ops import run_manager_flash_announcements as runner
        from .announcement_delivery import read as read_delivery
        job = plan['job_id']
        if not re.fullmatch('[a-f0-9]{32}',job): raise ValueError('TEST_CANARY_JOB_INVALID')
        prefix = 'announcement_flash/jobs/'+job
        source = self.io('state')
        raw = source.read_bytes(prefix+'/input.json')
        report_raw = source.read_bytes(prefix+'/preprocessing-report.json')
        inp, report = json.loads(raw), json.loads(report_raw)
        entries = report.get('execution_manifest',[])
        if (digest(raw) != plan['input_sha256'] or digest(report_raw) != plan['report_sha256']
                or inp.get('job_id') != job or inp.get('target_date') != self.value['target_date']
                or report.get('job_id') != job or report.get('target_date') != self.value['target_date']
                or any(report.get('processing_contract',{}).get(k) != self.value['model_identity'][k]
                    for k in ('model_id','configuration_sha256'))
                or report.get('first_article_id') != plan['article_id'] or len(entries) != 1
                or entries[0].get('article_id') != plan['article_id'] or entries[0].get('body_sha256') != plan['body_sha256']
                or report.get('counts',{}).get('expected_model_requests') != 1
                or report.get('counts',{}).get('model_required_articles') != 1
                or not any(a.get('article_id')==plan['article_id'] and a.get('source_sha256')==plan['source_sha256']
                    and a.get('body_sha256')==plan['body_sha256'] for a in report.get('catalogue',[]))):
            raise ValueError('TEST_SINGLE_ARTICLE_BINDING_CHANGED')
        delivered, _ = read_delivery(source,job)
        if delivered is not None: raise ValueError('TEST_CANARY_ALREADY_ATTEMPTED')
        if any(ref.startswith('announcement_flash/queue/locks/') for ref in self.inventories['state']):
            raise ValueError('TEST_SOURCE_LOCK_COPY_FORBIDDEN')
        gate_ref = plan['legacy_gate_binding_ref']
        gate_raw = self.io('config').read_bytes(gate_ref)
        gate = json.loads(gate_raw)
        if gate.get('code_identity') != self.value['code_identity']:
            raise ValueError('TEST_GATE_CODE_IDENTITY_CHANGED')
        first_authority = self.first_authority(ReadonlyIO(self.value['independent_state_root']))
        if first_authority is not None:
            if first_authority.job_id != job:
                raise ValueError('TEST_FIRST_AUTHORITY_JOB_CHANGED')
            first_authority.preflight(prepared_io=source)
        runner._test_legacy_gate(gate, self.value['model_identity']['model_id'])
        # Only explicit POST reaches these writes. The immutable input files and
        # the real existing runner/gate remain the execution authority.
        state = Path(self.value['independent_state_root'])
        target = SafeRoot(state)
        target.write_bytes('test-canary-attempt.json',json.dumps({'test_run_id':self.value['test_run_id'],
            'source_manifest_sha256':self.value['source_manifest']['sha256']}).encode(),require_absent=True)
        for ref in self.inventories['state']:
            target.write_bytes(ref,source.read_bytes(ref),require_absent=True)
        def save(ref, value):
            target.write_bytes(ref,json.dumps(value,ensure_ascii=False,sort_keys=True).encode()+b'\n')
        current = {'job_id':job,'context':{'target_date':self.value['target_date']},'state':'RUNNING',
            'step':'ISOLATED_SINGLE_ARTICLE','completed_count':0,'total_count':1,'failure_code':None,
            'last_progress_at':datetime.now().astimezone().isoformat(),'evidence_kind':'ISOLATED_EXPLICIT_CANARY'}
        save('attempts/'+job+'.json',current)
        save('cursors/announcement_flash_latest.json',{'job_id':job,'target_date':self.value['target_date'],'state':'RUNNING'})
        save('cursors/announcement_flash_delivery_index.json',{'items':[{'job_id':job,'target_date':self.value['target_date']}]})
        gate_path = self.roots['config']/gate_ref
        command = [str(runner.RUNTIME_PYTHON),'-B',str(REPO/'ops/run_manager_flash_announcements.py'),
            '--state-root',str(state),'--capture-root',str(self.roots['capture']),
            '--shared-root',str(self.roots['shared']),'--job-id',job,
            '--execute-preprocessed-report-sha256',plan['report_sha256'],'--execution-phase','FIRST',
            '--legacy-gate-binding',str(gate_path),'--legacy-gate-binding-sha256',digest(gate_raw)]
        self.verify()
        try:
            result = execute(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                             env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'},check=False)
        except (OSError,subprocess.SubprocessError) as exc:
            current.update(state='FAILED',failure_code='TEST_RUNNER_FAILED',finished_at=datetime.now().astimezone().isoformat())
            save('attempts/'+job+'.json',current)
            raise ValueError('TEST_RUNNER_FAILED') from exc
        delivered, _ = read_delivery(ReadonlyIO(state),job)
        current.update(state='PARTIAL' if result.returncode == 0 and delivered else 'FAILED',
            step='RETURNED_UNREVIEWED',failure_code=None if delivered else 'TEST_FINAL_DELIVERY_UNAVAILABLE',
            finished_at=datetime.now().astimezone().isoformat())
        save('attempts/'+job+'.json',current)
        save('cursors/announcement_flash_latest.json',{'job_id':job,'target_date':self.value['target_date'],'state':current['state']})
        return {'state':current['state'],
            'returncode':result.returncode,'test_run_id':self.value['test_run_id'],
            'semantic_status':'UNREVIEWED','natural_execution':'NOT_VERIFIED'}


def create_app(context: TestContext, *, execute=subprocess.run) -> FastAPI:
    context.verify()
    app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    @app.get(PREFIX+'/context')
    def get_context():
        try: return envelope(context.public())
        except (ValueError,OSError,KeyError): raise HTTPException(409,'TEST_CONTEXT_CHANGED') from None
    @app.get(PREFIX+'/announcement-flash')
    def get_flash(test_run_id: str, target_date: str):
        if test_run_id != context.value['test_run_id'] or target_date != context.value['target_date']:
            raise HTTPException(409,'TEST_CONTEXT_MISMATCH')
        try: return envelope(context.read_flash())
        except (ValueError,OSError,KeyError): raise HTTPException(409,'TEST_READ_FAILED_CLOSED') from None
    @app.post(PREFIX+'/canary')
    async def canary(request: Request):
        body = await request.json()
        if body != {k:context.public()[k] for k in ('test_run_id','target_date','source_manifest_sha256')}:
            raise HTTPException(409,'TEST_CONTEXT_MISMATCH')
        from starlette.concurrency import run_in_threadpool
        try: return envelope(await run_in_threadpool(context.execute_canary,execute=execute))
        except (ValueError,OSError,KeyError): raise HTTPException(409,'TEST_CANARY_FAILED_CLOSED') from None
    return app
