"""Transport existing native identity owner output; never infer issuer identity."""
import sys
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import copy
import importlib
import json
import os
import subprocess
from types import ModuleType
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
from v5_shadow.hk_preselection import _source_bytes,_HKLoader,DESCRIPTOR_SHA256


def read_private(binding,date):
    _source_bytes();request=dict(binding=binding,date=date)
    child=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve())],
        input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    if child.returncode:raise ValueError('NATIVE_IDENTITY_OWNER_READ_FAILED:'+child.stderr.decode(errors='replace')[-1000:])
    if len(child.stdout)>MAX_JSON_BYTES:raise ValueError('NATIVE_IDENTITY_RESPONSE_LIMIT')
    value=json.loads(child.stdout)
    if value.get('request_sha256')!=sha256_json(request) or value.get('owner_source_sha256')!=DESCRIPTOR_SHA256:
        raise ValueError('NATIVE_IDENTITY_RESPONSE_IDENTITY')
    _source_bytes();return value


def install_transport(root,date,result):
    """Only original verified rows cross this boundary; discovery keeps gates."""
    prefix='upstreams.v3_shared_data.shared_data'
    names=('upstreams','upstreams.v3_shared_data',prefix,prefix+'.store',prefix+'.hashing',prefix+'.hk_security_master')
    if any(name in sys.modules for name in names):raise ValueError('NATIVE_IDENTITY_NAMESPACE_OCCUPIED')
    for name in names:
        module=ModuleType(name)
        if name in names[:3]:module.__path__=[]
        sys.modules[name]=module
    class NativeStoreError(RuntimeError):pass
    def load_verified(actual_root,actual_date):
        if Path(actual_root)!=Path(root) or actual_date!=date:raise NativeStoreError('NATIVE_IDENTITY_ROOT_OR_DATE_MISMATCH')
        if result.get('error'):raise NativeStoreError(result['error'])
        return copy.deepcopy(result['master']),copy.deepcopy(result['manifest'])
    sys.modules[prefix+'.store'].StoreError=NativeStoreError
    sys.modules[prefix+'.hashing'].sha256_json=sha256_json
    sys.modules[prefix+'.hk_security_master'].load_verified_hk_security_master=load_verified


def worker(request):
    from v5_shadow.manager_plan import _snapshot
    before=_snapshot(request['binding'])
    sys.meta_path.insert(0,_HKLoader(_source_bytes()))
    module=importlib.import_module('upstreams.v3_shared_data.shared_data.hk_security_master')
    root=Path(request['binding']['root'])
    def audit(event,args):
        if event.startswith(('socket.','subprocess.','os.exec','os.spawn','os.posix_spawn')) or event in ('os.system','os.fork','os.forkpty'):
            raise PermissionError('NATIVE_IDENTITY_NETWORK_PROCESS_DENIED')
        if event in ('os.mkdir','os.remove','os.rename','os.rmdir','os.chmod','os.link','os.symlink','os.truncate','os.utime','os.chown'):
            raise PermissionError('NATIVE_IDENTITY_WRITE_DENIED')
        if event=='open' and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
            raise PermissionError('NATIVE_IDENTITY_WRITE_DENIED')
        if event=='open' and isinstance(args[0],(str,bytes)):
            path=Path(os.fsdecode(args[0]))
            if path.is_absolute() and path.is_relative_to(root) and str(path.relative_to(root)) not in request['binding']['files']:
                raise PermissionError('NATIVE_IDENTITY_UNDECLARED_INPUT')
    sys.addaudithook(audit)
    master,manifest=module.load_verified_hk_security_master(request['binding']['root'],request['date'])
    if _snapshot(request['binding'])!=before:raise ValueError('NATIVE_IDENTITY_INPUT_CHANGED')
    return dict(master=master,manifest=manifest,request_sha256=sha256_json(request),owner_source_sha256=DESCRIPTOR_SHA256)


if __name__=='__main__':
    raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
    if len(raw)>MAX_JSON_BYTES:raise ValueError('NATIVE_IDENTITY_REQUEST_LIMIT')
    sys.stdout.buffer.write(canonical_bytes(worker(json.loads(raw))))
