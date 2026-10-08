"""Local research-only immutable run store with a recoverable commit index."""
import fcntl
import hashlib
import json
import os
import re
import stat
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from .composition import atomic_bytes, shadow_root
from .contracts import (RunReference, RuntimeIdentity, SafetyFlags, ShadowResult,
    exact_keys, parse_request, parse_safety, aware, sha, trade_date)
from .digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
from .legacy_adapter import build_shadow_result
from .source_capsule import checked_path


def wire(value):
    if hasattr(value,'__dataclass_fields__'):return wire(asdict(value))
    if isinstance(value,datetime):return value.isoformat()
    if isinstance(value,Path):return str(value)
    if isinstance(value,dict):return {k:wire(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [wire(v) for v in value]
    return value


def _no_constant(value):raise ValueError('NONFINITE_JSON')


def _pairs(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ValueError('DUPLICATE_JSON_KEY')
        result[k]=v
    return result


def _load(root,relative):
    path=checked_path(root,relative)
    with path.open('rb') as source:raw=source.read(MAX_JSON_BYTES+1)
    if len(raw)>MAX_JSON_BYTES:raise ValueError('JSON_SIZE_EXCEEDED')
    value=json.loads(raw,parse_constant=_no_constant,object_pairs_hook=_pairs)
    if not isinstance(value,dict):raise ValueError('JSON_OBJECT_REQUIRED')
    return value,raw


def _dir(root,relative):
    checked_path(root,relative)
    parent=root
    for name in relative.split('/'):
        child=parent/name
        checked_path(root,child.relative_to(root).as_posix())
        child.mkdir(exist_ok=True)
        checked_path(root,child.relative_to(root).as_posix())
        fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        parent=child
    return parent


def _run_id(value):
    if not isinstance(value,str) or re.fullmatch('[0-9a-f]{32}',value) is None:raise ValueError('RUN_ID_INVALID')
    return value


def parse_result(value):
    exact_keys(value,ShadowResult.__dataclass_fields__)
    if value['schema_version']!='v5.rebound_shadow.v1' or value['formal_eligibility_status']!='UNVERIFIED' or value['natural_verified'] is not False:
        raise ValueError('RESULT_SAFETY_INVALID')
    safety=parse_safety(value['safety']);request=parse_request(value['request'])
    observed=dict(value['runtime'])
    # Previously committed v1 artifacts remain readable, but new executions
    # provide the observed dependency fingerprint as part of their identity.
    observed.setdefault('dependency_environment_sha256','')
    observed.setdefault('dependency_environment_json','')
    exact_keys(observed,RuntimeIdentity.__dataclass_fields__)
    if any(not isinstance(observed[k],str) for k in observed if k!='observed_at'):raise ValueError('RUNTIME_IDENTITY_INVALID')
    runtime=RuntimeIdentity(**{**observed,'observed_at':aware(observed['observed_at'])})
    if runtime.dependency_environment_sha256 or runtime.dependency_environment_json:
        sha(runtime.dependency_environment_sha256)
        if hashlib.sha256(runtime.dependency_environment_json.encode()).hexdigest()!=runtime.dependency_environment_sha256:
            raise ValueError('DEPENDENCY_OBSERVATION_MISMATCH')
    status=value['business_status']
    if status not in ('COMPLETED','VALID_EMPTY','PARTIAL','CANNOT_CONFIRM','FAILED'):raise ValueError('BUSINESS_STATUS_INVALID')
    if status in ('COMPLETED','VALID_EMPTY','PARTIAL'):
        for field in ('code_manifest_sha256','dependency_lock_sha256','effective_config_sha256','source_capsule_sha256'):sha(getattr(runtime,field))
        if request.input_snapshot_sha256 is None:raise ValueError('INPUT_IDENTITY_REQUIRED')
    started,finished=aware(value['started_at']),aware(value['finished_at'])
    inferred=build_shadow_result(request,runtime,value['legacy_screen'],started,finished)
    # A caller may preserve the legacy payload while explicitly downgrading an
    # unverified source. It must never upgrade unknown legacy output to success.
    if status not in ('CANNOT_CONFIRM','FAILED'):
        if status!=inferred.business_status or value['evaluated_count']!=inferred.evaluated_count:raise ValueError('RESULT_STATUS_OVERCLAIM')
    elif value['evaluated_count'] is not None:raise ValueError('UNKNOWN_COUNT_MUST_BE_NULL')
    if request.data_kind=='OWNER_VERIFIED' and status in ('COMPLETED','VALID_EMPTY','PARTIAL'):
        raise ValueError('OWNER_INPUT_ADMISSION_NOT_IMPLEMENTED')
    return ShadowResult(value['schema_version'],_run_id(value['run_id']),request,runtime,value['legacy_screen'],status,value['evaluated_count'],'UNVERIFIED',False,started,finished,safety)


def idempotency_key(request,runtime):
    if request.input_snapshot_sha256 is None:raise ValueError('INPUT_IDENTITY_UNKNOWN')
    identity=dict(module_id=runtime.module_id,target_trade_date=request.target_trade_date,
        research_cutoff=request.research_cutoff.isoformat(),execution_kind=request.execution_kind,data_kind=request.data_kind,
        input_snapshot_sha256=request.input_snapshot_sha256,code_manifest_sha256=runtime.code_manifest_sha256,
        dependency_lock_sha256=runtime.dependency_lock_sha256,source_capsule_sha256=runtime.source_capsule_sha256,
        effective_config_sha256=runtime.effective_config_sha256,python_version=runtime.python_version,release_id=runtime.release_id)
    if runtime.dependency_environment_sha256:
        identity['dependency_environment_sha256']=runtime.dependency_environment_sha256
    return sha256_json(identity)


def _cacheable(result):
    # PARTIAL and failed/unknown attempts are retained independently. They must
    # neither consume nor hit the successful-result cache.
    return result.request.input_snapshot_sha256 is not None and result.business_status in ('COMPLETED','VALID_EMPTY')


def _attempt_key(result,runtime=None):
    return sha256_json({'attempt':result.run_id,'request':wire(result.request),'runtime':wire(result.runtime) if runtime is None else runtime})


def _ref(value):
    exact_keys(value,RunReference.__dataclass_fields__)
    _run_id(value['run_id'])
    for k in ('artifact_sha256','manifest_sha256','receipt_sha256','idempotency_key'):sha(value[k])
    return RunReference(**value)


def _read_trio(root,target,run_id,key):
    trade_date(target);_run_id(run_id);sha(key)
    prefix=f'runs/{target}/{run_id}'
    artifact,artifact_raw=_load(root,prefix+'/artifact.json')
    manifest,manifest_raw=_load(root,prefix+'/manifest.json')
    receipt,receipt_raw=_load(root,prefix+'/receipt.json')
    ash=hashlib.sha256(artifact_raw).hexdigest();msh=hashlib.sha256(manifest_raw).hexdigest();rsh=hashlib.sha256(receipt_raw).hexdigest()
    if (manifest.get('schema_version')!='v5.shadow_manifest.v1' or receipt.get('schema_version')!='v5.shadow_receipt.v1'
        or any(v.get('run_id')!=run_id or v.get('target_trade_date')!=target or v.get('idempotency_key')!=key for v in (manifest,receipt))
        or manifest.get('artifact_sha256')!=ash or receipt.get('artifact_sha256')!=ash or receipt.get('manifest_sha256')!=msh
        or receipt.get('status')!='COMMITTED' or receipt.get('natural_verified') is not False):
        raise ValueError('SHADOW_TRIO_INTEGRITY_FAILED')
    result=parse_result(artifact)
    if result.run_id!=run_id or result.request.target_trade_date!=target:raise ValueError('SHADOW_ARTIFACT_IDENTITY_MISMATCH')
    legacy_identity='dependency_environment_sha256' not in artifact['runtime']
    expected=(idempotency_key(result.request,result.runtime) if _cacheable(result) or (legacy_identity and result.request.input_snapshot_sha256 is not None)
        else _attempt_key(result,artifact['runtime']))
    if key!=expected:raise ValueError('SHADOW_IDEMPOTENCY_MISMATCH')
    return result,RunReference(run_id,ash,msh,rsh,key)


def read_shadow(root:Path,ref:RunReference) -> ShadowResult:
    root=shadow_root(root);_ref(wire(ref))
    record,_=_load(root,'refs/'+ref.run_id+'.json')
    if _ref(record['reference'])!=ref:raise ValueError('SHADOW_REFERENCE_MISMATCH')
    result,actual=_read_trio(root,record['target_trade_date'],ref.run_id,ref.idempotency_key)
    if actual!=ref:raise ValueError('SHADOW_REFERENCE_HASH_MISMATCH')
    return result


def publish_shadow(root:Path,result:ShadowResult) -> RunReference:
    root=shadow_root(root);result=parse_result(wire(result))
    known=_cacheable(result)
    key=idempotency_key(result.request,result.runtime) if known else _attempt_key(result)
    for sub in ('locks','index','claims','refs','runs'):_dir(root,sub)
    lock=checked_path(root,'locks/'+key+'.lock')
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('LOCK_INVALID')
        fcntl.flock(fd,fcntl.LOCK_EX)
        index_rel='index/'+key+'.json';claim_rel='claims/'+key+'.json'
        index_path=checked_path(root,index_rel)
        if known and index_path.exists():
            previous,_=_load(root,index_rel);ref=_ref(previous['reference'])
            if ref.idempotency_key!=key or previous['target_trade_date']!=result.request.target_trade_date:
                raise ValueError('SHADOW_INDEX_IDENTITY_MISMATCH')
            old=read_shadow(root,ref)
            if _cacheable(old):return ref
        claim_path=checked_path(root,claim_rel)
        if known and claim_path.exists():
            previous,_=_load(root,claim_rel)
            if previous['target_trade_date']!=result.request.target_trade_date:
                raise ValueError('SHADOW_CLAIM_IDENTITY_MISMATCH')
            # Only missing files indicate a pre-commit crash. A corrupt existing
            # trio is an integrity failure and cannot be silently replaced.
            try:old,ref=_read_trio(root,previous['target_trade_date'],previous['run_id'],key)
            except FileNotFoundError:pass
            else:
                if _cacheable(old):
                    record={'target_trade_date':old.request.target_trade_date,'reference':wire(ref)}
                    atomic_bytes(checked_path(root,'refs/'+ref.run_id+'.json'),canonical_bytes(record))
                    atomic_bytes(index_path,canonical_bytes(record));return ref
        target=result.request.target_trade_date;run_id=result.run_id
        directory=checked_path(root,f'runs/{target}/{run_id}')
        if directory.exists():raise ValueError('IMMUTABLE_RUN_ALREADY_EXISTS')
        if known:atomic_bytes(claim_path,canonical_bytes({'run_id':run_id,'target_trade_date':target}))
        directory=_dir(root,f'runs/{target}/{run_id}')
        artifact_raw=canonical_bytes(wire(result));ash=hashlib.sha256(artifact_raw).hexdigest()
        manifest=dict(schema_version='v5.shadow_manifest.v1',run_id=run_id,target_trade_date=target,idempotency_key=key,artifact_sha256=ash)
        manifest_raw=canonical_bytes(manifest);msh=hashlib.sha256(manifest_raw).hexdigest()
        receipt=dict(schema_version='v5.shadow_receipt.v1',run_id=run_id,target_trade_date=target,idempotency_key=key,artifact_sha256=ash,manifest_sha256=msh,status='COMMITTED',natural_verified=False)
        atomic_bytes(directory/'artifact.json',artifact_raw);atomic_bytes(directory/'manifest.json',manifest_raw);atomic_bytes(directory/'receipt.json',canonical_bytes(receipt))
        _,ref=_read_trio(root,target,run_id,key)
        record={'target_trade_date':target,'reference':wire(ref)}
        atomic_bytes(checked_path(root,'refs/'+run_id+'.json'),canonical_bytes(record))
        if known:atomic_bytes(index_path,canonical_bytes(record))
        return ref
    finally:os.close(fd)
