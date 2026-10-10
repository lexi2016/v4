"""Read-only, fixed-source A pool assembly in an independent Python worker."""
import sys
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import builtins
import csv
import errno
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
DESCRIPTOR_SHA256='d0fddbcaa1d5eb22f50edd5d651976b8bc2643122bc951b31733448dea8e23e4'
KINDS={'v192':set(),'fupan':{'pool','manifest'},'stage7':{'pool','manifest'},
       'wechat':{'rows','manifest'},'baimao':{'data'},'research':{'preview','selector'}}
EXPECTED_PREFIXES=('invalid upstream manifest:','invalid D-1 fupan ','D-1 fupan ',
                   'invalid D-1 Stage7 ','D-1 Stage7 ','invalid WeChat upstream ',
                   'WeChat upstream ','shared v1.9.2 ')
EXPECTED_RESEARCH_VALUE_ERRORS=frozenset({
    'hourly research archive-date mismatch',
    'hourly research manifest or receipt mismatch',
    'hourly research manifest points to missing payload',
    'hourly research slot directory is not a directory',
    'hourly research articles are invalid',
    'hourly research article is invalid',
    'hourly research article identity is invalid',
    'research slot must use HHMM',
    'research slot must be a real time',
})
_RESEARCH_TIMESTAMP_FIELDS=('source_generated_at','published_at','collected_at','first_seen_at')
_RESEARCH_STRING_LIST_FIELDS=(
    'source_dedup_keys','source_types','themes','top_catalysts','cannot_confirm',
    'stage_evidence.item.cannot_confirm','stage_evidence.evidence.quality_flags',
    'stage_evidence.evidence.cannot_confirm',
)
EXPECTED_RESEARCH_VALIDATOR_VALUE_ERRORS=frozenset({
    'invalid research stage_evidence_v1 fields',
    'invalid research stage_evidence_v1 schema',
    'research stage evidence date mismatch',
    'research stage evidence slot is invalid',
    'research stage evidence source SHA mismatch',
    'research stage evidence payload scope mismatch',
    'research stage evidence items must be a list',
    'invalid research stage evidence item',
    'research stage evidence item identity is incomplete',
    'invalid research stage evidence item fields',
    'research stage evidence item stock code is missing',
    'research stage evidence item quality is invalid',
    'research stage evidence flags must be strict booleans',
    'research stage evidence quality score is invalid',
    'research stage evidence raw quality score is invalid',
    'research stage evidence rows must be a list',
    'invalid research stage evidence row fields',
    'research stage evidence row identity is missing',
    'research stage evidence row flags must be strict booleans',
    'research archive_date must use YYYYMMDD',
    'research archive_date must be a real calendar date',
    'invalid research archive fields',
    'invalid research archive schema',
    'unsafe research archive boundary',
    'invalid research source SHA-256',
    'invalid research source schema',
    'research dedupe contract mismatch',
    'research archive requires articles',
    'research archive requires stock pool',
    'research article count mismatch',
    'research stock-pool count mismatch',
    'invalid research article fields',
    'research article date mismatch',
    'duplicate research article identity',
    'unsafe research article recommendation',
    'invalid research duplicate count',
    'research source dedup keys must be sorted and unique',
    'invalid research stock-pool fields',
    'invalid research stock-pool identity',
    'unsafe research stock-pool recommendation',
    'invalid research source counts',
    'research cannot_confirm must be sorted and unique',
    'research stage evidence row evidence_level is invalid',
    'research stage evidence row confidence is invalid',
}) | frozenset(
    f'invalid research stage evidence {field}'
    for field in ('payload_base_sha256','source_input_sha256','manifest_sha256','receipt_sha256')
) | frozenset(
    message
    for field in _RESEARCH_TIMESTAMP_FIELDS
    for message in (f'missing research {field}',f'invalid research {field}',
                    f'research {field} must include timezone')
) | frozenset(
    f'invalid research article {field}'
    for field in ('article_id','dedupe_key','source_path_sha256')
) | frozenset(f'invalid research {field}' for field in _RESEARCH_STRING_LIST_FIELDS)
EXPECTED_RESEARCH_RECEIPT_KEY_ERRORS=frozenset({
    'archive_date','source_input_sha256','article_count','stock_pool_count',
})
EXPECTED_RESEARCH_MANIFEST_SHAPE_ERRORS=frozenset(
    f"'{type_name}' object has no attribute 'get'"
    for type_name in ('list','str','int','float','NoneType','bool')
) | frozenset(
    f"'{type_name}' object has no attribute 'startswith'"
    for type_name in ('int','float','NoneType','bool','list','dict')
)
EXPECTED_RESEARCH_PAYLOAD_ROOT_TYPE_ERRORS=frozenset({
    'list indices must be integers or slices, not str',
    "string indices must be integers, not 'str'",
}) | frozenset(
    f"'{type_name}' object is not subscriptable"
    for type_name in ('int','float','NoneType','bool')
)
EXPECTED_RESEARCH_INPUT_SHAPE_TYPE_ERRORS=frozenset(
    f"'{type_name}' object is not iterable"
    for type_name in ('int','float','NoneType','bool')
)
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
    if not isinstance(lanes,list) or not 1<=len(lanes)<=6:raise ValueError('A_LANES_INVALID')
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


def _verify_lane(lane,*,verify_optional=True):
    root=no_symlinks(lane['input_root'])
    optional=({lane['paths'][key] for key in ('preview','selector')}
              if lane['kind']=='research' and not verify_optional else set())
    for name,expected in lane['files'].items():
        if name in optional:continue
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
    allowed={};selected_root=None;enumerable_directories=set();fd_paths={};opened_fds=set();checked_open_active=False
    original_open=os.open;original_close=os.close
    original_builtin_open=builtins.open;original_io_open=io.open
    def select_lane(lane):
        nonlocal allowed,selected_root,enumerable_directories
        root=no_symlinks(lane['input_root'])
        selected_root=root
        allowed={_relative(root,name):digest for name,digest in lane['files'].items()}
        enumerable_directories={
            _relative(root,name).parent
            for name in lane['files']
            if Path(name).parent.parts
        }
    if sys.pycache_prefix is None:raise WorkerBoundaryViolation('A_SOURCE_CACHE_REQUIRED')
    cache=no_symlinks(Path(sys.pycache_prefix))
    libraries=(BASE,Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve(),Path(os.__file__).resolve().parent,cache)
    def _zoneinfo_target(candidate):
        # pandas/dateutil on this pinned macOS runtime opens only this UTC
        # alias while importing the frozen V1.9.2 reader.  Bind it to the
        # platform timezone database target; never trust a configurable TZPATH.
        alias=Path('/usr/share/zoneinfo/UTC')
        # Linux packages UTC as one fixed alias to a regular trusted file.
        # This is not permission to traverse arbitrary zoneinfo or caller links.
        linux_target=Path('/usr/share/zoneinfo/Etc/UTC')
        if candidate in (alias,linux_target):
            try:
                if (alias.is_symlink() and os.readlink(alias)=='Etc/UTC'
                        and no_symlinks(linux_target)==linux_target
                        and stat.S_ISREG(linux_target.stat().st_mode)):
                    return linux_target
            except (OSError,ValueError):
                pass
        database=Path('/private/var/db/timezone/tz')
        if candidate==alias:
            if not alias.parent.is_symlink():return None
        elif not candidate.is_relative_to(database):return None
        try:resolved=candidate.resolve(strict=True);relative=resolved.relative_to(database)
        except (OSError,RuntimeError,ValueError):return None
        if (not resolved.is_file() or len(relative.parts)!=3
                or relative.parts[-2:]!=('zoneinfo','UTC')):return None
        return resolved

    def _zoneinfo_file(candidate):return _zoneinfo_target(candidate) is not None

    def _missing_declared_input(candidate):
        if candidate.exists():raise InputEvidenceError('INPUT_UNEXPECTED_FILE')
        raise FileNotFoundError(errno.ENOENT,os.strerror(errno.ENOENT),str(candidate))

    def _redirect_zoneinfo_open(function,path,args,kwargs):
        if not isinstance(path,(str,bytes,os.PathLike)):return function(path,*args,**kwargs)
        target=_zoneinfo_target(Path(os.fsdecode(path)))
        mode=args[0] if args else kwargs.get('mode','r')
        if isinstance(mode,str) and any(char in mode for char in 'wax+'):
            raise WorkerBoundaryViolation('A_WORKER_WRITE_DENIED')
        if target is not None:return function(target,*args,**kwargs)
        candidate=_candidate(path,None)
        if candidate in allowed and allowed[candidate] is None:
            _missing_declared_input(candidate)
        return function(path,*args,**kwargs)

    def checked_builtin_open(path,*args,**kwargs):
        return _redirect_zoneinfo_open(original_builtin_open,path,args,kwargs)

    def checked_io_open(path,*args,**kwargs):
        return _redirect_zoneinfo_open(original_io_open,path,args,kwargs)

    def _candidate(path,dir_fd):
        if isinstance(path,int):raise WorkerBoundaryViolation('A_SOURCE_FD_OPEN_DENIED')
        raw=Path(os.fsdecode(path))
        if raw.is_absolute():candidate=raw
        elif dir_fd is None:candidate=Path.cwd()/raw
        else:
            parent=fd_paths.get(dir_fd)
            if parent is None:raise WorkerBoundaryViolation('A_DIR_FD_NOT_DECLARED')
            candidate=parent/raw
        try:return no_symlinks(candidate)
        except ValueError as error:
            if _zoneinfo_file(candidate):return candidate
            raise WorkerBoundaryViolation('A_INPUT_PATH_NOT_DECLARED') from error

    def _under_library(candidate):
        return any(candidate.is_relative_to(root) for root in libraries)

    def _input_directory(candidate):
        return (selected_root is not None
                and (selected_root.is_relative_to(candidate)
                     or any(path.is_relative_to(candidate) for path in enumerable_directories)))

    def checked_open(path,flags,mode=0o777,*,dir_fd=None):
        nonlocal checked_open_active
        if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
            raise WorkerBoundaryViolation('A_WORKER_WRITE_DENIED')
        candidate=_candidate(path,dir_fd)
        directory_flag=bool(flags & getattr(os,'O_DIRECTORY',0))
        is_directory=_input_directory(candidate) or _under_library(candidate)
        if directory_flag:
            if not is_directory or not candidate.is_dir():
                raise WorkerBoundaryViolation('A_INPUT_PATH_NOT_DECLARED')
        elif candidate in allowed:
            if allowed[candidate] is None:
                _missing_declared_input(candidate)
            if candidate.is_dir():
                raise WorkerBoundaryViolation('A_INPUT_PATH_NOT_DECLARED')
        elif _under_library(candidate) or _zoneinfo_file(candidate):
            if candidate.is_dir():raise WorkerBoundaryViolation('A_INPUT_PATH_NOT_DECLARED')
        else:
            raise WorkerBoundaryViolation('A_INPUT_PATH_NOT_DECLARED')
        checked_open_active=True
        try:
            open_path=_zoneinfo_target(candidate) or path
            if dir_fd is None:fd=original_open(open_path,flags,mode)
            else:fd=original_open(open_path,flags,mode,dir_fd=dir_fd)
        finally:checked_open_active=False
        try:is_opened_directory=stat.S_ISDIR(os.fstat(fd).st_mode)
        except OSError:
            original_close(fd);raise
        opened_fds.add(fd)
        if is_opened_directory:fd_paths[fd]=candidate
        else:fd_paths.pop(fd,None)
        return fd

    def checked_close(fd):
        try:original_close(fd)
        finally:
            fd_paths.pop(fd,None);opened_fds.discard(fd)

    os.open=checked_open;os.close=checked_close;builtins.open=checked_builtin_open;io.open=checked_io_open
    def audit(event,args):
        if event.startswith(('socket.','subprocess.','os.exec','os.spawn','os.posix_spawn')) or event in ('os.system','os.fork','os.forkpty'):
            raise WorkerBoundaryViolation('A_WORKER_NETWORK_OR_PROCESS_DENIED')
        if event in ('os.remove','os.rename','os.rmdir','os.mkdir','os.chmod','os.link','os.symlink','os.truncate',
                     'os.utime','os.chown','os.lchown','os.fchown','os.fchmod','os.setxattr','os.removexattr'):
            raise WorkerBoundaryViolation('A_WORKER_WRITE_DENIED')
        if event=='open':
            path,mode,flags=args
            if checked_open_active:return
            if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                raise WorkerBoundaryViolation('A_WORKER_WRITE_DENIED')
            if isinstance(path,int):
                if path not in opened_fds:raise WorkerBoundaryViolation('A_SOURCE_FD_OPEN_DENIED')
                return
            candidate=_candidate(path,None)
            if candidate in allowed and allowed[candidate] is None:
                _missing_declared_input(candidate)
            if candidate in allowed and allowed[candidate] is not None and not candidate.is_dir():return
            if (_under_library(candidate) or _zoneinfo_file(candidate)) and not candidate.is_dir():return
            raise WorkerBoundaryViolation('A_INPUT_PATH_NOT_DECLARED')
        if event in ('os.listdir','os.scandir'):
            path=args[0]
            candidate=fd_paths.get(path) if isinstance(path,int) else _candidate(path,None)
            if candidate is None or (candidate not in enumerable_directories and not _under_library(candidate)):
                raise WorkerBoundaryViolation('A_INPUT_PATH_NOT_DECLARED')
    sys.addaudithook(audit)
    return select_lane


def _expected(error,kind=None):
    if isinstance(error,(InputEvidenceError,OSError,UnicodeError,csv.Error,json.JSONDecodeError)):return True
    if type(error).__name__=='StoreError' and type(error).__module__.endswith('.store'):return True
    if type(error) is ValueError and kind=='research' and str(error) in (
            EXPECTED_RESEARCH_VALUE_ERRORS|EXPECTED_RESEARCH_VALIDATOR_VALUE_ERRORS):return True
    if (type(error) is KeyError and kind=='research' and len(error.args)==1
            and type(error.args[0]) is str and error.args[0] in EXPECTED_RESEARCH_RECEIPT_KEY_ERRORS):return True
    if (type(error) is AttributeError and kind=='research'
            and str(error) in EXPECTED_RESEARCH_MANIFEST_SHAPE_ERRORS):return True
    if (type(error) is TypeError and kind=='research'
            and str(error) in (EXPECTED_RESEARCH_PAYLOAD_ROOT_TYPE_ERRORS
                               |EXPECTED_RESEARCH_INPUT_SHAPE_TYPE_ERRORS)):return True
    return type(error) is ValueError and str(error).startswith(EXPECTED_PREFIXES)


def _build(module,lane,target,signal):
    root=no_symlinks(lane['input_root']);paths={k:_relative(root,v) for k,v in lane['paths'].items()}
    if lane['kind']=='research':
        try:
            return module.build_hourly_research_pool(root,trade_date=target)
        except FileNotFoundError:
            preview,selector=paths['preview'],paths['selector']
            if preview.is_file() and selector.is_file():
                _verify_lane(lane)
                return module.build_research_preview_pool(preview,selector,target)
            reason=('A_SELECTOR_PANEL_UNAVAILABLE' if preview.is_file() and not selector.is_file()
                    else 'A_RESEARCH_HOURLY_WINDOW_EVIDENCE_MISSING')
            return module.build_expected_missing_pool(
                target,pool_id='a_share_research_recommendation_pool',
                display_name='A股研报推荐股票池',market='A',reason=reason)
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
            _verify_lane(lane,verify_optional=lane['kind']!='research')
            with redirect_stdout(io.StringIO()):artifact=_build(module,lane,request['target_date'],request['signal_date'])
            _verify_lane(lane,verify_optional=(
                lane['kind']!='research' or artifact.get('source_role')=='RAW_SOURCE'))
        except Exception as error:
            if not _expected(error,lane['kind']):raise
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
            select_lane(lane);artifact=outcome['artifact']
            _verify_lane(lane,verify_optional=(
                lane['kind']!='research' or artifact.get('source_role')=='RAW_SOURCE'))
    _source_bytes()
    return _bound_result(dict(schema_version='v5.a_preselection_assembly.v1',status=('ASSEMBLED' if accepted==len(outcomes) else 'PARTIAL') if accepted else 'CANNOT_CONFIRM',
                target_date=request['target_date'],signal_date=request['signal_date'],data_kind=request['data_kind'],
                row_count=row_count if accepted else None,lanes=outcomes,request_sha256=sha256_json(request),
                source_capsule_sha256=DESCRIPTOR_SHA256,implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                input_binding_status='DECLARED_BYTES_CHECKED_FOR_ACCESSED_SOURCES',
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
