"""Read a pinned, published V4 review through its original reader, without recomputing."""
import sys
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy
import hashlib
import importlib
import json
import os
import stat
import subprocess
import tempfile
from v5_shadow import a_preselection as common
from v5_shadow.contracts import exact_keys,trade_date,sha
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
from v5_shadow.composition import no_symlinks

BASE=Path(__file__).resolve().parents[2]
CAPSULE=BASE/'vendor/review_readback_baseline'
DESCRIPTOR=BASE/'contracts/review_readback_source_manifest.json'
PIN='f732cc8bf0cdd1218d1f8e9d575fa3298c564d439d550cba772a7f64407fdd11'
SCHEMA='v5.review_bridge.v1'

def _request(value):
    exact_keys(value,('target_date','input_root','input_files'))
    day=trade_date(value['target_date']);root=no_symlinks(value['input_root'])
    if not root.is_absolute() or not root.is_dir():raise ValueError('REVIEW_ROOT_INVALID')
    names={f'close_reviews/{day}.json',f'receipts/close_reviews/{day}.json','manifest.json'}
    if not isinstance(value['input_files'],dict) or set(value['input_files'])!=names:raise ValueError('REVIEW_INPUT_SET')
    for digest in value['input_files'].values():sha(digest)
    canonical_bytes(value)
    return value

def _read_inputs(request, with_payload=False):
    root=no_symlinks(request['input_root']);result={};payloads={}
    for name,expected in request['input_files'].items():
        path=common._relative(root,name)
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_JSON_BYTES:raise ValueError('REVIEW_INPUT_SIZE_OR_TYPE')
            with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(MAX_JSON_BYTES+1)
            after=os.fstat(fd)
            if len(raw)>MAX_JSON_BYTES or len(raw)!=before.st_size or any(getattr(before,k)!=getattr(after,k) for k in ('st_ino','st_dev','st_size','st_mtime_ns','st_ctime_ns')):raise ValueError('REVIEW_INPUT_CHANGED')
        finally:os.close(fd)
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=expected:raise ValueError('REVIEW_INPUT_SHA')
        result[name]=digest
        if with_payload:payloads[name]=json.loads(raw)
    return (result,payloads) if with_payload else result

def _sources():
    descriptor=json.loads(no_symlinks(DESCRIPTOR).read_bytes())
    if sha256_json(descriptor)!=PIN:raise ValueError('REVIEW_SOURCE_DESCRIPTOR')
    result={}
    for entry in descriptor['entries']:
        data=common._relative(CAPSULE,entry['relative_path']).read_bytes()
        if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('REVIEW_SOURCE_BYTES')
        result[entry['relative_path']]=data
    return result

class _Loader(common._FrozenLoader):
    def exec_module(self,module):
        if module.__name__ in self.packages:module.__path__=[]
        item=self.sources.get(module.__name__)
        if item:
            name,data,_=item;module.__file__=str(CAPSULE/name)
            exec(compile(data,module.__file__,'exec'),module.__dict__)

def _identity():
    paths=[Path(__file__),BASE/'src/v5_shadow/a_preselection.py',BASE/'src/v5_shadow/contracts.py',
           BASE/'src/v5_shadow/digests.py',BASE/'src/v5_shadow/composition.py',BASE/'src/v5_shadow/provider_evidence.py',BASE/'src/v5_shadow/__init__.py']
    return {str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def _readonly_guard():
    # The frozen SafeRoot reader uses dir_fd opens. Python audit events omit the
    # directory fd, so enforce mutation/network denial without pretending to
    # enforce an OS read sandbox. Input identity is checked separately.
    def audit(event,args):
        if event.startswith(('socket.','subprocess.','os.exec','os.spawn','os.posix_spawn')) or event in ('os.system','os.fork','os.forkpty'):
            raise RuntimeError('REVIEW_NETWORK_OR_PROCESS_DENIED')
        if event in ('os.remove','os.rename','os.rmdir','os.mkdir','os.chmod','os.link','os.symlink','os.truncate','os.utime','os.chown','os.lchown','os.fchown','os.fchmod','os.setxattr','os.removexattr'):
            raise RuntimeError('REVIEW_WRITE_DENIED')
        if event=='open':
            path,mode,flags=args
            if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                raise RuntimeError('REVIEW_WRITE_DENIED')
    sys.addaudithook(audit)

def _assemble(value):
    request=_request(value);before,snapshot=_read_inputs(request,True);day=request['target_date']
    if any(n in sys.modules for n in ('domains','infrastructure','contracts','apps')):raise ValueError('REVIEW_FRESH_PROCESS_REQUIRED')
    sys.meta_path.insert(0,_Loader(_sources()))
    store_module=importlib.import_module('infrastructure.review_store')
    data_module=importlib.import_module('infrastructure.data_store')
    envelope_module=importlib.import_module('domains.review_envelope')
    projection=importlib.import_module('apps.api.v35_api._review_router_parts.hk_projection')
    _readonly_guard()
    store=store_module.ReviewStore(Path(request['input_root']))
    reference=store.read_reference(day)
    if reference is None or reference.get('schema_version')!='v3_5.close_review.v1' or reference.get('trade_date')!=day:raise ValueError('REVIEW_NATIVE_RESULT_MISSING')
    if reference!=snapshot[f'close_reviews/{day}.json']:raise ValueError('REVIEW_READ_IDENTITY_CHANGED')
    expected=data_module._sha256(reference)
    if snapshot['manifest.json'].get(f'close_reviews/{day}.json')!=expected or snapshot[f'receipts/close_reviews/{day}.json']!={'schema_version':'v3_import_receipt.v1','payload_path':f'close_reviews/{day}.json','source_sha256':expected,'trade_date':day}:raise ValueError('REVIEW_SNAPSHOT_EVIDENCE_MISMATCH')
    flags={k:False for k in ('production_allowed','buy_gate_updated','orders_sent')}
    parent=projection.__native_hk_parent_body({'_sha256':data_module._sha256,'deepcopy':copy.deepcopy,'_SAFETY_FLAGS':flags},day,reference)
    review=envelope_module.review_envelope(day,a_review=None,hk_review=parent)
    review['v5_readback']=dict(read_only=True,source_date=day,source_origin_verified=False,source_identity_scope='CALLER_BOUND_BYTES_AND_ORIGINAL_CONTRACT',
        input_files=before,source_capsule_sha256=PIN,v5_computation_performed=False,v5_natural_run=False)
    catalog=dict(default_date=day,navigation_date=day,navigation_timezone='Asia/Shanghai',dates=[day],review_dates=[day],
        stage_dates=[],future_target_dates=[],research_dates=[],hk_observation_only_dates=[],requested_date=None,selected_date=day,
        runtime_identity=dict(application='V5',status='READ_ONLY_ORIGINAL_RESULT',release_id='review-readback-r1',process_status='CANNOT_CONFIRM'))
    if _read_inputs(request)!=before:raise ValueError('REVIEW_INPUT_CHANGED')
    _sources()
    return dict(schema_version=SCHEMA,readback_kind='BOUND_REVIEW_ARTIFACT_READBACK',review=review,catalog=catalog,
        input_files=before,request_sha256=sha256_json(request),source_capsule_sha256=PIN,implementation_identity=_identity(),
        natural_verified=False,v5_computation_performed=False,**flags)

def run_review_bridge(request):
    request=_request(request);_read_inputs(request);identity=_identity()
    with tempfile.TemporaryDirectory(prefix='v5-review-readback-') as cache:
        result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+cache,str(Path(__file__).resolve())],
            input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    if len(result.stdout)>MAX_JSON_BYTES:raise ValueError('REVIEW_RESPONSE_SIZE')
    try:out=json.loads(result.stdout)
    except (ValueError,UnicodeError) as error:raise ValueError('REVIEW_WORKER_RESPONSE:'+result.stderr.decode(errors='replace')[-1000:]) from error
    if result.returncode:raise ValueError(out.get('reason','REVIEW_WORKER_FAILED'))
    if (out.get('schema_version')!=SCHEMA or out.get('request_sha256')!=sha256_json(request)
        or out.get('source_capsule_sha256')!=PIN or out.get('implementation_identity')!=identity or _identity()!=identity
        or out.get('input_files')!=_read_inputs(request) or out.get('natural_verified') is not False):raise ValueError('REVIEW_WORKER_IDENTITY')
    return out

if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('REVIEW_REQUEST_SIZE')
        print(canonical_bytes(_assemble(json.loads(raw))).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED',reason=type(error).__name__+':'+str(error))).decode());raise SystemExit(1)
