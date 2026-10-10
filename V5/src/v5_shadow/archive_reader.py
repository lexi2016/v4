"""Isolated frozen R10 archive validator; never imports its US dependencies into manager."""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy
import hashlib
import importlib
import json
import os
import re
import subprocess
from types import SimpleNamespace
from v5_shadow import a_preselection as common
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES

BASE=Path(__file__).resolve().parents[2]
CAPSULE=BASE/'vendor/archive_reader_baseline'
DESCRIPTOR=BASE/'contracts/archive_reader_source_manifest.json'
PIN='33a4b671c4b2b6b89db2c3e8bed7efdc8d1ee8fc983ff005d2ade2692d47b2a4'
ARCHIVE_PATTERN=r'(?:receipts/)?research/(?:archives/[0-9]{8}|hourly/live/[0-9]{8}/[0-9]{4})\.json'
from v5_shadow.archive_article_v2 import CAPTURE_PATTERN, INPUT_PATTERN
from v5_shadow.archive_builder_v1 import BUILDER_PATTERN, builder_identity
PATTERN='(?:'+ARCHIVE_PATTERN+'|'+CAPTURE_PATTERN+'|'+INPUT_PATTERN+'|'+BUILDER_PATTERN+')'


def article_v2_identity():
    return sha256_json({
        'adapter':hashlib.sha256((BASE/'src/v5_shadow/archive_article_v2.py').read_bytes()).hexdigest(),
        'producer_manifest':hashlib.sha256((BASE/'producers/archive-acquisition-v2/manifest.json').read_bytes()).hexdigest(),
        'builder':builder_identity(),
    })


def sources():
    manifest=json.loads(DESCRIPTOR.read_bytes())
    if sha256_json(manifest)!=PIN:raise ValueError('ARCHIVE_SOURCE_PIN')
    result={}
    for row in manifest['entries']:
        raw=(CAPSULE/row['relative_path']).read_bytes()
        if len(raw)!=row['bytes'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('ARCHIVE_SOURCE_BYTES')
        result[row['relative_path']]=raw
    return result


class _Loader(common._FrozenLoader):
    def exec_module(self,module):
        if module.__name__ in self.packages:
            # Namespace-only packages avoid unrelated scheduler/provider exports.
            module.__path__=[]
            return
        item=self.sources.get(module.__name__)
        if item:
            relative,raw,_=item;module.__file__=str(CAPSULE/relative)
            exec(compile(raw,module.__file__,'exec'),module.__dict__)


def read_private(root, binding):
    """root already contains only SHA-pinned copied bytes; original root never passed to child."""
    sources()
    request={'root':str(root),'files':binding['files']}
    process=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(root.parent/'archive-cache'),str(Path(__file__).resolve())],input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,
        env={k:v for k,v in os.environ.items() if not k.startswith(('V4_','V35_'))})
    if len(process.stdout)>MAX_JSON_BYTES:raise ValueError('ARCHIVE_READER_OUTPUT_LIMIT')
    try:out=json.loads(process.stdout)
    except ValueError as exc:raise ValueError('ARCHIVE_READER_RESPONSE:'+process.stderr.decode(errors='replace')[-1000:]) from exc
    if process.returncode:raise ValueError(out.get('reason','ARCHIVE_READER_FAILED'))
    if (out.get('source_capsule_sha256')!=PIN or out.get('request_sha256')!=sha256_json(request)
            or out.get('article_v2_source_sha256')!=article_v2_identity()):raise ValueError('ARCHIVE_READER_IDENTITY')
    # Stable provenance identity; physical private paths must not churn plan hashes.
    for row in out['records'].values():
        if row.get('binding'):
            row['binding']['source_root']=binding['root']
            row['binding']['ledger_root']=str(Path(binding['root']).parent/'dispatcher')
    sources()
    return out


def _unwrap(row,key):
    if row.get('error'):
        error=row['error'];kind={'ValueError':ValueError,'TypeError':TypeError,'KeyError':KeyError,'OSError':OSError,'RuntimeError':RuntimeError,'ImportError':ImportError}.get(error['type'],RuntimeError)
        raise kind(error['message'])
    return copy.deepcopy(row.get(key))


def source_proxy(result):
    """Only transports original validated outputs/errors to the unchanged workspace reader."""
    records=result['records'];slots=result['slots']
    def read(date,slot='',mode='LIVE'):
        if mode!='LIVE':raise ValueError('ARCHIVE_READER_LIVE_ONLY')
        return _unwrap(records.get(date+'/'+slot,{}),'payload')
    def binding(date,*,slot='',mode='LIVE'):
        if mode!='LIVE':raise ValueError('ARCHIVE_READER_LIVE_ONLY')
        return _unwrap(records.get(date+'/'+slot,{}),'binding')
    return SimpleNamespace(store=SimpleNamespace(read_exact=read),
        hourly_store=SimpleNamespace(read_exact=read,list_slots=lambda date,mode: _unwrap(slots.get(date,{'value':[]}),'value') if mode=='LIVE' else []),artifact_binding=binding)


def _read_only_boundary(root):
    # SafeRoot uses openat relative descriptors; do not interpret those names
    # as cwd-relative paths. Bind the original store root and prohibit mutation.
    safe=importlib.import_module('infrastructure.owned_io').SafeRoot
    original_init=safe.__init__
    def init(instance,path):
        if Path(path).absolute()!=root:raise PermissionError('ARCHIVE_ROOT_NOT_BOUND')
        original_init(instance,path)
    safe.__init__=init
    def audit(event,args):
        if event.startswith(('socket.','subprocess.','os.exec','os.spawn','os.posix_spawn')) or event in ('os.system','os.fork','os.forkpty'):
            raise PermissionError('ARCHIVE_NETWORK_OR_PROCESS_DENIED')
        if event in ('os.remove','os.rename','os.rmdir','os.mkdir','os.chmod','os.link','os.symlink','os.truncate','os.utime','os.chown','os.lchown','os.fchown','os.fchmod','os.setxattr','os.removexattr'):
            raise PermissionError('ARCHIVE_WRITE_DENIED')
        if event=='open':
            _,mode,flags=args
            if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                raise PermissionError('ARCHIVE_WRITE_DENIED')
    sys.addaudithook(audit)


def worker(request):
    root=Path(request['root']).resolve();files=request['files']
    if not root.is_dir() or 'manifest.json' not in files:raise ValueError('ARCHIVE_PRIVATE_ROOT_OR_MANIFEST')
    for name,digest in files.items():
        if name!='manifest.json' and not re.fullmatch(PATTERN,name):raise ValueError('ARCHIVE_INPUT_PATH')
        p=common._relative(root,name)
        if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('ARCHIVE_PRIVATE_SHA')
    manifest=json.loads((root/'manifest.json').read_bytes())
    days=set()
    for name in {*files,*manifest}:
        if re.fullmatch(ARCHIVE_PATTERN,name):days.add(re.search(r'/([0-9]{8})(?:/|\.json)',name).group(1))
    if len(days)>370:raise ValueError('ARCHIVE_DATE_BOUND')
    sys.meta_path.insert(0,_Loader(sources()))
    from v5_shadow.archive_article_v2 import install_validator
    def read_evidence(name):
        if name not in files:raise ValueError('ARTICLE_V2_UNDECLARED_FILE')
        return common._relative(root,name).read_bytes()
    install_validator(read_evidence)
    module=importlib.import_module('infrastructure.research_lane_source')
    source=module.ResearchLaneSource(root,ledger_root=root/'unused-ledger')
    # Construction only touched the private root. Reads now prohibit writes,
    # network/process creation; source_root is never available in this process.
    _read_only_boundary(root)
    def capture(call):
        try:return call()
        except (ValueError,TypeError,KeyError,OSError,RuntimeError,ImportError) as exc:
            return {'error':{'type':type(exc).__name__,'message':str(exc)}}
    records={};slots={}
    def record(day,slot):
        payload=source.hourly_store.read_exact(day,slot,mode='LIVE') if slot else source.store.read_exact(day)
        return {'payload':payload,'binding':source.artifact_binding(day,slot=slot,mode='LIVE') if payload is not None else None}
    for day in sorted(days):
        records[day+'/']=capture(lambda:record(day,''))
        slots[day]=capture(lambda:{'value':source.hourly_store.list_slots(day,mode='LIVE')})
        for slot in slots[day].get('value',[]):records[day+'/'+slot]=capture(lambda:record(day,slot))
    for name,digest in files.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise ValueError('ARCHIVE_PRIVATE_CHANGED')
    return dict(records=records,slots=slots,source_capsule_sha256=PIN,
        article_v2_source_sha256=article_v2_identity(),request_sha256=sha256_json(request))


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('ARCHIVE_REQUEST_LIMIT')
        print(canonical_bytes(worker(json.loads(raw))).decode())
    except Exception as exc:
        print(json.dumps({'reason':type(exc).__name__+':'+str(exc)}));raise SystemExit(1)
