"""Read-only, fixed-source A pool assembly in an independent Python worker."""
import sys
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import csv
import hashlib
import importlib
import importlib.abc
import importlib.util
import io
import json
import os
import stat
import subprocess
import tempfile
from contextlib import redirect_stdout
from datetime import datetime,timezone

from v5_shadow.composition import no_symlinks
from v5_shadow.contracts import sha,trade_date,exact_keys
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
from v5_shadow.provider_evidence import encode_sdk_value

BASE=Path(__file__).resolve().parents[2]
CAPSULE=BASE/'vendor/a_preselection_baseline'
DESCRIPTOR=BASE/'contracts/a_preselection_source_manifest.json'
DESCRIPTOR_SHA256='5a8cc5e96d266adac80949eb8aee12127ae4978c98547686cc5f46f8094ae1d0'
KINDS={'v192':set(),'fupan':{'pool','manifest'},'stage7':{'pool','manifest'},
       'wechat':{'rows','manifest'},'baimao':{'data'}}
EXPECTED_PREFIXES=('invalid upstream manifest:','invalid D-1 fupan ','D-1 fupan ',
                   'invalid D-1 Stage7 ','D-1 Stage7 ','invalid WeChat upstream ',
                   'WeChat upstream ','shared v1.9.2 ')
SAFETY=dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,
            natural_verified=False,formal_eligibility_verified=False)


class InputEvidenceError(ValueError):pass
class WorkerBoundaryViolation(RuntimeError):pass


def _relative(root,value):
    if not isinstance(value,str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
        raise ValueError('INPUT_PATH_INVALID')
    path=no_symlinks(root/value)
    if not path.is_relative_to(root):raise ValueError('INPUT_PATH_ESCAPE')
    return path


def _request(value):
    exact_keys(value,('target_date','signal_date','data_kind','lanes'))
    target=trade_date(value['target_date']);signal=trade_date(value['signal_date'])
    if signal>=target or value['data_kind'] not in ('SYNTHETIC','RECORDED_INPUT_REPLAY'):
        raise ValueError('A_REQUEST_INVALID')
    lanes=value['lanes']
    if not isinstance(lanes,list) or not 1<=len(lanes)<=5:raise ValueError('A_LANES_INVALID')
    seen=set()
    for lane in lanes:
        exact_keys(lane,('kind','input_root','paths','files'))
        kind=lane['kind']
        if kind not in KINDS or kind in seen:raise ValueError('A_LANE_INVALID_OR_DUPLICATE')
        seen.add(kind);root=no_symlinks(lane['input_root'])
        for code_root in (BASE,Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve(),Path(os.__file__).resolve().parent):
            if root.is_relative_to(code_root) or code_root.is_relative_to(root):raise ValueError('INPUT_CODE_ROOT_OVERLAP')
        if not isinstance(lane['paths'],dict) or set(lane['paths'])!=KINDS[kind]:raise ValueError('A_LANE_PATHS_INVALID')
        if not isinstance(lane['files'],dict) or not 1<=len(lane['files'])<=2000:raise ValueError('INPUT_FILE_MAP_INVALID')
        for name,digest in lane['files'].items():
            _relative(root,name)
            if digest is not None:sha(digest)
        for name in lane['paths'].values():
            _relative(root,name)
            if name not in lane['files']:raise ValueError('INPUT_PATH_NOT_BOUND')
    canonical_bytes(value)
    return value


def _file_sha(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        start=os.fstat(fd)
        if not stat.S_ISREG(start.st_mode) or start.st_size>256*1024**2:raise InputEvidenceError('INPUT_FILE_INVALID')
        digest=hashlib.sha256();size=0
        while data:=os.read(fd,1024**2):
            size+=len(data)
            if size>start.st_size:raise InputEvidenceError('INPUT_CHANGED_DURING_READ')
            digest.update(data)
        end=os.fstat(fd)
        if (start.st_ino,start.st_dev,start.st_size,start.st_mtime_ns,start.st_ctime_ns)!=(end.st_ino,end.st_dev,end.st_size,end.st_mtime_ns,end.st_ctime_ns) or size!=start.st_size:
            raise InputEvidenceError('INPUT_CHANGED_DURING_READ')
        return digest.hexdigest()
    finally:os.close(fd)


def _verify_lane(lane):
    root=no_symlinks(lane['input_root'])
    for name,expected in lane['files'].items():
        path=_relative(root,name)
        if expected is None:
            if path.exists():raise InputEvidenceError('INPUT_UNEXPECTED_FILE')
        elif _file_sha(path)!=expected:raise InputEvidenceError('INPUT_BYTES_MISMATCH')


def _source_bytes():
    value=json.loads(no_symlinks(DESCRIPTOR).read_bytes())
    if sha256_json(value)!=DESCRIPTOR_SHA256:raise ValueError('A_SOURCE_MANIFEST_MISMATCH')
    sources={}
    for item in value['entries']:
        path=_relative(CAPSULE,item['relative_path']);data=path.read_bytes()
        if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise ValueError('A_SOURCE_BYTES_MISMATCH')
        sources[item['relative_path']]=data
    return sources


class _FrozenLoader(importlib.abc.MetaPathFinder,importlib.abc.Loader):
    def __init__(self,sources):
        self.sources={};self.packages=set()
        for relative,data in sources.items():
            if not relative.endswith('.py'):continue
            package=relative.endswith('/__init__.py')
            name=relative[:-12].replace('/','.') if package else relative[:-3].replace('/','.')
            self.sources[name]=(relative,data,package)
            parts=name.split('.')
            for i in range(1,len(parts)):self.packages.add('.'.join(parts[:i]))
            if package:self.packages.add(name)
    def find_spec(self,fullname,path=None,target=None):
        if fullname in self.sources or fullname in self.packages:
            return importlib.util.spec_from_loader(fullname,self,is_package=fullname in self.packages)
        if fullname.split('.')[0] in ('domains','infrastructure','upstreams','contracts'):
            raise ImportError('A_SOURCE_CLOSURE_INCOMPLETE:'+fullname)
        return None
    def create_module(self,spec):return None
    def exec_module(self,module):
        item=self.sources.get(module.__name__)
        if module.__name__ in self.packages:module.__path__=[]
        if item:
            relative,data,_=item;module.__file__=str(CAPSULE/relative)
            exec(compile(data,module.__file__,'exec'),module.__dict__)


def _guard(lanes):
    allowed=set()
    def select_lane(lane):
        nonlocal allowed
        root=no_symlinks(lane['input_root'])
        allowed={_relative(root,name) for name in lane['files']}
    if sys.pycache_prefix is None:raise WorkerBoundaryViolation('A_SOURCE_CACHE_REQUIRED')
    cache=no_symlinks(Path(sys.pycache_prefix))
    libraries=(BASE,Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve(),Path(os.__file__).resolve().parent,cache)
    def audit(event,args):
        if event.startswith(('socket.','subprocess.','os.exec','os.spawn','os.posix_spawn')) or event in ('os.system','os.fork','os.forkpty'):
            raise WorkerBoundaryViolation('A_WORKER_NETWORK_OR_PROCESS_DENIED')
        if event in ('os.remove','os.rename','os.rmdir','os.mkdir','os.chmod','os.link','os.symlink','os.truncate',
                     'os.utime','os.chown','os.lchown','os.fchown','os.fchmod','os.setxattr','os.removexattr'):
            raise WorkerBoundaryViolation('A_WORKER_WRITE_DENIED')
        if event=='open':
            path,mode,flags=args
            if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                raise WorkerBoundaryViolation('A_WORKER_WRITE_DENIED')
            if isinstance(path,int):return
            candidate=no_symlinks(Path(os.fsdecode(path)).absolute())
            if candidate not in allowed and not any(candidate.is_relative_to(root) for root in libraries):
                raise WorkerBoundaryViolation('A_INPUT_PATH_NOT_DECLARED')
    sys.addaudithook(audit)
    return select_lane


def _expected(error):
    if isinstance(error,(InputEvidenceError,OSError,UnicodeError,csv.Error,json.JSONDecodeError)):return True
    if type(error).__name__=='StoreError' and type(error).__module__.endswith('.store'):return True
    return type(error) is ValueError and str(error).startswith(EXPECTED_PREFIXES)


def _build(module,lane,target,signal):
    root=no_symlinks(lane['input_root']);paths={k:_relative(root,v) for k,v in lane['paths'].items()}
    if lane['kind']=='v192':
        reader=importlib.import_module('upstreams.v3_shared_data.shared_data.v192_selector').read_verified_v192_pool
        return module.build_shared_v192_premarket_pool(root,trade_date=target,signal_date=signal,reader=reader)
    if lane['kind']=='fupan':return module.build_fupan_watchlist_pool(paths['pool'],paths['manifest'],trade_date=target,signal_date=signal)
    if lane['kind']=='stage7':return module.build_stage7_review_pool(paths['pool'],paths['manifest'],trade_date=target,signal_date=signal)
    if lane['kind']=='wechat':return module.build_wechat_pool(paths['manifest'],paths['rows'],target)
    return module.build_baimao_pool(paths['data'],target)


def _bound_result(result):
    try:
        canonical_bytes(result)
        return result
    except ValueError as error:
        if str(error)!='JSON_SIZE_EXCEEDED':raise
    # Diagnostics may be omitted; accepted source rows are never truncated.
    for lane in result['lanes']:
        if not lane['accepted']:
            removed=False
            for key in ('rejected_artifact','rejected_artifact_tagged'):
                removed=lane.pop(key,None) is not None or removed
            if removed:lane['rejected_artifact_status']='OMITTED_TOTAL_OUTPUT_LIMIT'
    canonical_bytes(result)
    return result


def _assemble(request):
    request=_request(request);sources=_source_bytes();finder=_FrozenLoader(sources)
    if any(name in sys.modules for name in ('domains','infrastructure','contracts','upstreams')):
        raise ValueError('A_WORKER_REQUIRES_FRESH_PROCESS')
    sys.meta_path.insert(0,finder)
    calendar_module=importlib.import_module('contracts.trading_calendar')
    calendar=calendar_module.load_market_calendar()
    states=calendar_module.resolve_market_states(calendar,request['target_date'])
    if states['a_share'].value not in ('FULL_TRADING_DAY','HALF_TRADING_DAY_AM'):raise ValueError('A_TARGET_NOT_TRADING_DAY')
    if calendar_module.previous_session(calendar,request['target_date'],market='a_share')!=request['signal_date']:
        raise ValueError('A_SIGNAL_NOT_PREVIOUS_SESSION')
    # Load fixed code before permanent guards; no V4 writer is called.
    module=importlib.import_module('domains.preselection_materializer')
    validator=importlib.import_module('infrastructure.preselection_pool_store').validate_pool_artifact
    select_lane=_guard(request['lanes']);outcomes=[];accepted=0;row_count=0
    for lane in request['lanes']:
        select_lane(lane);artifact=None
        try:
            _verify_lane(lane)
            with redirect_stdout(io.StringIO()):artifact=_build(module,lane,request['target_date'],request['signal_date'])
            _verify_lane(lane)
        except Exception as error:
            if not _expected(error):raise
            outcomes.append(dict(kind=lane['kind'],accepted=False,reason=type(error).__name__+':'+str(error),artifact=None))
            continue
        try:
            validator(artifact);canonical_bytes(artifact)
            if artifact.get('trade_date')!=request['target_date'] or artifact.get('market')!='A':raise ValueError('A_OUTPUT_IDENTITY_MISMATCH')
        except ValueError as error:
            reason=('LEGACY_EMPTY_STATUS_CONTRACT_MISMATCH' if artifact.get('status')=='V192_CANDIDATE_READY_EMPTY' and artifact.get('rows')==[] else 'SOURCE_OUTPUT_INVALID:'+str(error))
            rejected=dict(kind=lane['kind'],accepted=False,reason=reason,artifact=None)
            try:
                canonical_bytes(artifact);rejected['rejected_artifact']=artifact
            except ValueError:
                try:
                    tagged=encode_sdk_value(artifact);canonical_bytes(tagged)
                    rejected['rejected_artifact_tagged']=tagged
                except ValueError:rejected['rejected_artifact_status']='NOT_JSON_SERIALIZABLE_WITHIN_BOUND'
            outcomes.append(rejected);continue
        usable=bool(artifact['rows']) and artifact.get('status') not in ('CANNOT_CONFIRM','MISSING')
        valid_empty=artifact.get('status')=='VALID_EMPTY' and artifact['rows']==[]
        accepted+=int(usable or valid_empty);row_count+=len(artifact['rows']) if usable else 0
        outcomes.append(dict(kind=lane['kind'],accepted=usable or valid_empty,reason='' if usable or valid_empty else 'SOURCE_NOT_READY',artifact=artifact))
    for lane,outcome in zip(request['lanes'],outcomes):
        if outcome['accepted']:
            select_lane(lane);_verify_lane(lane)
    _source_bytes()
    return _bound_result(dict(schema_version='v5.a_preselection_assembly.v1',status=('ASSEMBLED' if accepted==len(outcomes) else 'PARTIAL') if accepted else 'CANNOT_CONFIRM',
                target_date=request['target_date'],signal_date=request['signal_date'],data_kind=request['data_kind'],
                row_count=row_count if accepted else None,lanes=outcomes,request_sha256=sha256_json(request),
                source_capsule_sha256=DESCRIPTOR_SHA256,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                input_binding_status='DECLARED_BYTES_CHECKED',
                isolation_status='PYTHON_GUARDS_ONLY_OS_UNVERIFIED',finished_at=datetime.now(timezone.utc).isoformat(),**SAFETY))


def run_a_preselection(request):
    request=_request(request);implementation_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='v5-a-source-cache-') as cache:
        process=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),str(Path(__file__).resolve()),'--worker'],
                               input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if len(process.stdout)>MAX_JSON_BYTES:raise ValueError('A_WORKER_OUTPUT_TOO_LARGE')
    try:result=json.loads(process.stdout)
    except (ValueError,UnicodeError) as error:raise ValueError('A_WORKER_RESPONSE_INVALID:'+process.stderr.decode(errors='replace')[-2000:]) from error
    if process.returncode!=0:raise ValueError(result.get('reason','A_WORKER_FAILED'))
    if result.get('request_sha256')!=sha256_json(request):raise ValueError('A_WORKER_REQUEST_MISMATCH')
    if (result.get('implementation_sha256')!=implementation_sha
        or hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=implementation_sha
        or result.get('source_capsule_sha256')!=DESCRIPTOR_SHA256):raise ValueError('A_WORKER_CODE_IDENTITY_MISMATCH')
    if any(result.get(k)!=v for k,v in SAFETY.items()):raise ValueError('A_WORKER_SAFETY_MISMATCH')
    if (result.get('schema_version')!='v5.a_preselection_assembly.v1'
        or any(result.get(k)!=request[k] for k in ('target_date','signal_date','data_kind'))
        or result.get('status') not in ('ASSEMBLED','PARTIAL','CANNOT_CONFIRM')
        or not isinstance(result.get('lanes'),list)
        or [lane.get('kind') for lane in result['lanes']]!=[lane['kind'] for lane in request['lanes']]):
        raise ValueError('A_WORKER_CONTRACT_MISMATCH')
    return result


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('REQUEST_TOO_LARGE')
        result=_assemble(json.loads(raw))
        print(canonical_bytes(result).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED',reason=type(error).__name__+':'+str(error))).decode())
        raise SystemExit(1)
