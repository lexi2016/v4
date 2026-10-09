"""Exact seven-file V5 membership readback in an isolated original-reader process."""
import sys
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib
import importlib
import json
import os
import subprocess
from types import ModuleType,SimpleNamespace
from v5_shadow.hk_membership_recovery import CAPSULE,PIN,_sources,_Loader
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
OWNER_SHA='2b121a55eeff37a1838f64e47a3ee5abf0a3f2e19afae87a6fcca4a22e08c7ef'


def read_private(root,files,target):
    _sources();request=dict(root=str(root),files=files,target_date=target)
    p=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve())],input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,
        env={k:v for k,v in os.environ.items() if not k.startswith(('V4_','V35_'))})
    if len(p.stdout)>MAX_JSON_BYTES:raise ValueError('MEMBERSHIP_READ_RESPONSE_LIMIT')
    try:result=json.loads(p.stdout)
    except ValueError as exc:raise ValueError('MEMBERSHIP_READ_RESPONSE_INVALID') from exc
    if p.returncode:raise ValueError(result.get('reason','MEMBERSHIP_READER_FAILED'))
    if result.get('request_sha256')!=sha256_json(request) or result.get('source_capsule_sha256')!=PIN:raise ValueError('MEMBERSHIP_READ_IDENTITY')
    _sources();return result


def install_transport(root,result):
    """Transport native reader output only; original connect_selection still gates it."""
    module=ModuleType('domains.manager_research_evidence')
    def read_universe_evidence(actual_root,date,*,require_v2=False,authority_owner_root=None,authority_owner_sha256=None,**kwargs):
        if (Path(actual_root)!=root or date!=result['target_date'] or require_v2 is not True
            or Path(authority_owner_root)!=CAPSULE or authority_owner_sha256!=OWNER_SHA or kwargs):
            raise ValueError('MEMBERSHIP_TRANSPORT_BINDING_MISMATCH')
        if result.get('error'):
            error=ValueError(result['error']);error.diagnostic=result.get('diagnostic');raise error
        return SimpleNamespace(codes=tuple(result['codes']),source=dict(result['source']))
    module.read_universe_evidence=read_universe_evidence
    sys.modules[module.__name__]=module
    os.environ['V4_MANAGER_UNIVERSE_ROOT']=str(root)
    os.environ['V4_MANAGER_UNIVERSE_OWNER_ROOT']=str(CAPSULE)
    os.environ['V4_MANAGER_UNIVERSE_OWNER_SHA256']=OWNER_SHA


def worker(request):
    root=Path(request['root']);files=request['files'];target=request['target_date']
    def verify():
        if len(files)!=7:raise ValueError('MEMBERSHIP_SEVEN_FILES_REQUIRED')
        for name,digest in files.items():
            from v5_shadow.a_preselection import _relative
            if hashlib.sha256(_relative(root,name).read_bytes()).hexdigest()!=digest:raise ValueError('MEMBERSHIP_INPUT_SHA')
    verify();sys.meta_path.insert(0,_Loader(_sources()))
    def audit(event,args):
        if event.startswith(('socket.','subprocess.','os.exec','os.spawn','os.posix_spawn')) or event in ('os.system','os.fork','os.forkpty'):
            raise PermissionError('MEMBERSHIP_READ_NETWORK_OR_PROCESS_DENIED')
        if event in ('os.mkdir','os.remove','os.rename','os.rmdir','os.chmod','os.link','os.symlink','os.truncate','os.utime','os.chown','os.fchown','os.fchmod'):
            raise PermissionError('MEMBERSHIP_READ_WRITE_DENIED')
        if event=='open':
            _,mode,flags=args
            if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                raise PermissionError('MEMBERSHIP_READ_WRITE_DENIED')
    sys.addaudithook(audit)
    evidence=importlib.import_module('domains.manager_research_evidence')
    result=dict(target_date=target,request_sha256=sha256_json(request),source_capsule_sha256=PIN)
    try:
        verified=evidence.read_universe_evidence(root,target,authority_owner_root=CAPSULE,authority_owner_sha256=OWNER_SHA,require_v2=True)
        source=dict(verified.source)
        expected={source[k] for k in ('artifact_ref','manifest_ref','receipt_ref','current_ref','capture_ref','publication_ref')}
        sdk_relative=str(Path(source['capture_ref']).with_name('sdk.capture.json'));expected.add(sdk_relative)
        if set(files)!=expected:raise ValueError('MEMBERSHIP_EXACT_FILE_SET')
        capture=json.loads((root/source['capture_ref']).read_bytes())
        if capture.get('v5_recovery',{}).get('sdk_raw_sha256')!=files[sdk_relative]:raise ValueError('MEMBERSHIP_SDK_BINDING')
        from v5_shadow.hk_membership_recovery import _reject_constant
        sdk=json.loads((root/sdk_relative).read_bytes(),parse_constant=_reject_constant)
        if (sdk.get('status')!='RAW_CAPTURED' or any(sdk.get(key)!=capture.get(key)
            for key in ('schema_version','target_date','capture_run_id','producer_owner','plate_responses'))):
            raise ValueError('MEMBERSHIP_SDK_CAPTURE_IDENTITY')
        result.update(codes=list(verified.codes),source=source)
    except (OSError,ValueError,KeyError,TypeError) as error:
        result.update(error=str(error) if isinstance(error,ValueError) else 'MEMBERSHIP_READ_FAILED:'+type(error).__name__,diagnostic=getattr(error,'diagnostic',None))
    verify();return result


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('MEMBERSHIP_REQUEST_LIMIT')
        print(canonical_bytes(worker(json.loads(raw))).decode())
    except Exception as error:
        print(json.dumps({'reason':type(error).__name__+':'+str(error)}));raise SystemExit(1)
