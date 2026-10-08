"""Bound, immutable announcement readback using original catalog and analysis owners."""
import sys
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib
import importlib
import json
import os
import re
import subprocess
import tempfile
import threading
from types import MappingProxyType
from v5_shadow import a_preselection as common
from v5_shadow.contracts import exact_keys,trade_date,sha
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
from v5_shadow.composition import no_symlinks
from v5_shadow.module_api import _open_directory,_read_regular
from v5_shadow.review_bridge import _readonly_guard

BASE=Path(__file__).resolve().parents[2]
CAPSULE=BASE/'vendor/announcement_readback_baseline'
DESCRIPTOR=BASE/'contracts/announcement_readback_source_manifest.json'
PIN='bad8248a2b53efa82dbefdc62a04dae1aaf4237d6e43b02e3b445f773cfdfa90'
SCHEMA='v5.announcement_bridge.v1'
_READ_CONTEXT=threading.local()
# Input-only exception for the original registered body corpus (21,861,605
# observed bytes). HTTP/JSON output remains 16 MiB; all other inputs do too.
MAX_HANDOFF_BODY_BYTES=32*1024*1024

def _input_limit(relative):
    return MAX_HANDOFF_BODY_BYTES if re.fullmatch(r'announcement_agent_runs/[0-9a-f]{32}/evidence/body_corpus\.json',relative) else MAX_JSON_BYTES

def _request(value):
    exact_keys(value,('target_date','publication_date','manager_root','materials_root','manager_files','material_files'))
    target=trade_date(value['target_date']);p=value['publication_date']
    if p is not None and (not isinstance(p,str) or not re.fullmatch(r'(\d{8}|\d{4}-\d{2}-\d{2})',p)):raise ValueError('ANNOUNCEMENT_PUBLICATION_DATE')
    publication=trade_date(p.replace('-','')) if p is not None else None
    if publication is not None and publication>target:raise ValueError('ANNOUNCEMENT_PUBLICATION_AFTER_TARGET')
    roots=[]
    for key in ('manager_root','materials_root'):
        if not isinstance(value[key],str) or not Path(value[key]).is_absolute():raise ValueError('ANNOUNCEMENT_ROOT_INVALID')
        root=no_symlinks(value[key])
        if not root.is_dir():raise ValueError('ANNOUNCEMENT_ROOT_INVALID')
        roots.append(root)
    if roots[0].is_relative_to(roots[1]) or roots[1].is_relative_to(roots[0]):raise ValueError('ANNOUNCEMENT_ROOTS_OVERLAP')
    prefix=f'workspace_announcements/{target}/eastmoney_date_catalog/{publication}/'
    attempts=f'workspace_announcement_runs/{target}/eastmoney_date_catalog/{publication}/'
    for key in ('manager_files','material_files'):
        files=value[key]
        if not isinstance(files,dict) or not 1<=len(files)<=4096:raise ValueError('ANNOUNCEMENT_FILES_INVALID')
        for name,digest in files.items():
            if not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name:raise ValueError('ANNOUNCEMENT_INPUT_PATH')
            sha(digest)
            if key=='manager_files':
                dated=(name.startswith((prefix,attempts)) if publication is not None else bool(re.fullmatch(r'workspace_announcement(?:s|_runs)/'+target+r'/eastmoney_date_catalog/[0-9]{8}/.+',name)))
                handoff=bool(re.fullmatch(r'announcement_agent_runs/[0-9a-f]{32}/evidence/(?:[A-Za-z0-9_.-]+\.json|body_batch/bodies/AN[A-Z0-9]{8,32}\.json)',name))
                if not name.endswith('.json') or not (dated or handoff):raise ValueError('ANNOUNCEMENT_MANAGER_PATH')
            elif not re.fullmatch(r'(blobs/[0-9a-f]{64}|index/[0-9a-f]{64}\.json)',name):raise ValueError('ANNOUNCEMENT_MATERIAL_PATH')
    if publication is not None and not {prefix+'analysis.v1.json',prefix+'owner_import_receipt.v1.json',prefix+'latest.json'}<=set(value['manager_files']):raise ValueError('ANNOUNCEMENT_REQUIRED_INPUT_MISSING')
    canonical_bytes(value)
    return value

def _snapshot(root,files):
    root=no_symlinks(root);result={};total=0
    for relative,digest in files.items():
        path=common._relative(root,relative);directory=_open_directory(path.parent)
        try:
            _READ_CONTEXT.leaf=path.name
            try:fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
            finally:_READ_CONTEXT.leaf=None
        finally:os.close(directory)
        try:data=_read_regular(fd,_input_limit(relative))
        finally:os.close(fd)
        total+=len(data)
        if total>64*1024*1024:raise ValueError('ANNOUNCEMENT_INPUT_TOTAL_LIMIT')
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('ANNOUNCEMENT_INPUT_SHA')
        result[relative]=data
    return result

def _sources():
    descriptor=json.loads(no_symlinks(DESCRIPTOR).read_bytes())
    if sha256_json(descriptor)!=PIN:raise ValueError('ANNOUNCEMENT_SOURCE_PIN')
    result={}
    for entry in descriptor['entries']:
        data=common._relative(CAPSULE,entry['relative_path']).read_bytes()
        if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('ANNOUNCEMENT_SOURCE_BYTES')
        result[entry['relative_path']]=data
    return result

class _Loader(common._FrozenLoader):
    def find_spec(self,fullname,path=None,target=None):
        found=super().find_spec(fullname,path,target)
        if found is None and fullname.split('.')[0]=='v4':raise ImportError('ANNOUNCEMENT_SOURCE_CLOSURE:'+fullname)
        return found
    def exec_module(self,module):
        if module.__name__ in self.packages:module.__path__=[]
        item=self.sources.get(module.__name__)
        if item:
            name,data,_=item;module.__file__=str(CAPSULE/name)
            exec(compile(data,module.__file__,'exec'),module.__dict__)

class _SnapshotIO:
    """Only declared immutable input bytes. No writer, lock, fetch, or repair API."""
    def __init__(self,files):self.files=MappingProxyType(files);self.reads=set()
    def read_bytes(self,relative,*,max_bytes=64*1024*1024):
        if not isinstance(relative,str) or relative not in self.files:raise FileNotFoundError('ANNOUNCEMENT_UNBOUND_INPUT')
        data=self.files[relative]
        if len(data)>max_bytes:raise ValueError('ANNOUNCEMENT_READER_SIZE')
        self.reads.add(relative);return data

def _identity():
    names=('announcement_bridge.py','review_bridge.py','module_api.py','api_gateway.py','a_preselection.py','contracts.py','composition.py','digests.py','provider_evidence.py','__init__.py')
    return {f'src/v5_shadow/{name}':hashlib.sha256((BASE/'src/v5_shadow'/name).read_bytes()).hexdigest() for name in names}

def _prepare_private_inputs(manager,materials):
    if not sys.pycache_prefix:raise ValueError('ANNOUNCEMENT_PRIVATE_CACHE_REQUIRED')
    cache=no_symlinks(sys.pycache_prefix)
    root=cache/'bound-inputs';root.mkdir(mode=0o700)
    outputs=[]
    for group,files in (('manager',manager),('materials',materials)):
        directory=root/group;directory.mkdir(mode=0o700);outputs.append(directory)
        for name,data in files.items():
            path=directory/name;path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as stream:stream.write(data)
            path.chmod(0o400)
        for path in sorted((p for p in directory.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):path.chmod(0o500)
        directory.chmod(0o500)
    root.chmod(0o500)
    return outputs

def _input_read_guard(request,private_roots):
    allowed=set();roots=[];direct_reads={'manager':set(),'materials':set()}
    for index,(rootkey,filekey) in enumerate((('manager_root','manager_files'),('materials_root','material_files'))):
        for root in (no_symlinks(request[rootkey]),private_roots[index]):
            roots.append(root);allowed.update(common._relative(root,name) for name in request[filekey])
    if not sys.pycache_prefix:raise ValueError('ANNOUNCEMENT_PRIVATE_CACHE_REQUIRED')
    cache=no_symlinks(sys.pycache_prefix)
    libraries=(BASE,Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve(),Path(os.__file__).resolve().parent,cache)
    def audit(event,args):
        if event!='open':return
        name,mode,flags=args
        if isinstance(name,int) or flags & os.O_DIRECTORY:return
        path=Path(os.fsdecode(name))
        # Only the verified dir_fd snapshot reader may open its current leaf.
        if not path.is_absolute():
            if len(path.parts)==1 and path.name==getattr(_READ_CONTEXT,'leaf',None):return
            path=path.absolute()
        path=no_symlinks(path)
        # Declared input roots take precedence even when inside BASE/cache.
        if any(path.is_relative_to(root) for root in roots):
            if path not in allowed:raise RuntimeError('ANNOUNCEMENT_UNBOUND_READ_DENIED')
            for group,root in zip(('manager','materials'),private_roots):
                if path.is_relative_to(root):direct_reads[group].add(str(path.relative_to(root)))
            return
        if not any(path.is_relative_to(root) for root in libraries):raise RuntimeError('ANNOUNCEMENT_UNBOUND_READ_DENIED')
    sys.addaudithook(audit)
    return direct_reads

def _assemble(value):
    request=_request(value);target=request['target_date'];publication=request['publication_date']
    if any(n in sys.modules for n in ('v4','contracts','infrastructure')):raise ValueError('ANNOUNCEMENT_FRESH_PROCESS_REQUIRED')
    sys.meta_path.insert(0,_Loader(_sources()))
    analysis=importlib.import_module('v4.manager_research.announcement_analysis')
    workspace=importlib.import_module('v4.manager_research.workspace_announcements')
    store_module=importlib.import_module('v4.manager_research.store')
    material_module=importlib.import_module('v4.manager_research.materials')
    effective=dict(request)
    if publication is None:effective['publication_date']=analysis.previous_hk_session(target)
    _request(effective)
    manager=_snapshot(request['manager_root'],request['manager_files']);materials=_snapshot(request['materials_root'],request['material_files'])
    private_roots=_prepare_private_inputs(manager,materials)
    manager_io=_SnapshotIO(manager);material_io=_SnapshotIO(materials)
    class ReadOnlyStore:
        root=private_roots[0]
        _io=manager_io
        def _read(self,path):return store_module.ManagerResearchStore._read(self,path)
    class ReadOnlyMaterials(material_module.MaterialStore):
        def fetch(self,*args,**kwargs):raise RuntimeError('ANNOUNCEMENT_FETCH_FORBIDDEN')
        def parsed(self,*args,**kwargs):raise RuntimeError('ANNOUNCEMENT_PARSE_WRITE_FORBIDDEN')
    class Service:
        store=ReadOnlyStore()
        _material_store=ReadOnlyMaterials(private_roots[1])
        def get_announcement_date_catalog(self,date,publication_date):
            self.catalog=workspace.read_date_catalog(self,date,publication_date)
            return self.catalog
    service=Service();service._material_store._io=material_io
    _readonly_guard()
    direct_reads=_input_read_guard(request,private_roots)
    payload=analysis.read(service,target,publication)
    if service.catalog.get('readback_status')!='VERIFIED' or payload.get('analysis',{}).get('status')!='VERIFIED':raise ValueError('ANNOUNCEMENT_ORIGINAL_READBACK_REJECTED:'+','.join(payload.get('analysis',{}).get('gaps',[])))
    if payload.get('target_trade_date')!=target:raise ValueError('ANNOUNCEMENT_OUTPUT_DATE')
    product_path=analysis.product_path(service.store,target,payload['publication_date'])
    raw_product=service.store._read(product_path)
    raw_receipt=service.store._read(product_path.with_name('owner_import_receipt.v1.json'))
    payload['owner_import_receipt']=workspace.validate_owner_analysis_import_receipt(raw_receipt,raw_product)
    payload['consumption_validation']=workspace.read_analysis_consumption(service,target,payload['publication_date'],analysis_readback=payload)
    product_dir=str(product_path.parent.relative_to(service.store.root))
    catalog_raw=manager[product_dir+'/latest.json'];run_id=json.loads(catalog_raw).get('run_id')
    if not isinstance(run_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}',run_id):raise ValueError('ANNOUNCEMENT_CATALOG_RUN_ID')
    mirror=product_dir+'/'+run_id+'.json'
    if manager.get(mirror)!=catalog_raw:raise ValueError('ANNOUNCEMENT_CATALOG_MIRROR_MISMATCH')
    if manager!=_snapshot(request['manager_root'],request['manager_files']) or materials!=_snapshot(request['materials_root'],request['material_files']):raise ValueError('ANNOUNCEMENT_INPUT_CHANGED')
    _sources()
    flags={k:False for k in ('production_allowed','buy_gate_updated','orders_sent')}
    if any(payload.get(k) is not False for k in flags):raise ValueError('ANNOUNCEMENT_OUTPUT_SAFETY')
    return dict(schema_version=SCHEMA,payload=payload,catalog=service.catalog,
        readback_kind='BOUND_ANNOUNCEMENT_ARTIFACT_READBACK',source_origin_verified=False,workspace_consumption_verified=False,
        natural_verified=False,v5_computation_performed=False,input_files={'manager':request['manager_files'],'materials':request['material_files']},
        original_reader_accesses={'manager':sorted(manager_io.reads|direct_reads['manager']),'materials':sorted(material_io.reads|direct_reads['materials'])},
        input_view='PRIVATE_READ_ONLY_SNAPSHOT',isolation_status='PYTHON_GUARDS_NOT_OS_SANDBOX',
        request_sha256=sha256_json(request),source_capsule_sha256=PIN,implementation_identity=_identity(),**flags)

def run_announcement_bridge(request):
    request=_request(request);identity=_identity()
    with tempfile.TemporaryDirectory(prefix='v5-announcement-readback-') as cache:
        result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),str(Path(__file__).resolve())],
            input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if len(result.stdout)>MAX_JSON_BYTES:raise ValueError('ANNOUNCEMENT_OUTPUT_LIMIT')
    try:out=json.loads(result.stdout)
    except (ValueError,UnicodeError) as error:raise ValueError('ANNOUNCEMENT_WORKER_RESPONSE:'+result.stderr.decode(errors='replace')[-1000:]) from error
    if result.returncode:raise ValueError(out.get('reason','ANNOUNCEMENT_WORKER_FAILED'))
    if (out.get('schema_version')!=SCHEMA or out.get('request_sha256')!=sha256_json(request)
        or out.get('source_capsule_sha256')!=PIN or out.get('implementation_identity')!=identity or _identity()!=identity
        or out.get('source_origin_verified') is not False or out.get('workspace_consumption_verified') is not False
        or out.get('natural_verified') is not False):raise ValueError('ANNOUNCEMENT_WORKER_IDENTITY')
    return out

if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('ANNOUNCEMENT_REQUEST_LIMIT')
        print(canonical_bytes(_assemble(json.loads(raw))).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED',reason=type(error).__name__+':'+str(error))).decode());raise SystemExit(1)
