"""Keep identity, dependency compatibility and input readiness separate."""
import hashlib
import json
import platform
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
from .contracts import Binding,HealthReport,ModuleManifest,RuntimeIdentity,SourceCapsule
from .digests import sha256_json
from .source_capsule import verify_capsule


def module_code_digest(root: Path | None=None) -> str:
    root=Path(root) if root else Path(__file__).resolve().parent
    entries=[]
    for path in sorted(root.rglob('*.py')):
        if path.is_symlink():raise ValueError('CODE_SYMLINK_REJECTED')
        entries.append({'path':path.relative_to(root).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    if not entries:raise ValueError('CODE_MISSING')
    return sha256_json({'files':entries})


def observe_runtime(module:ModuleManifest,capsule:SourceCapsule,effective_config:dict) -> RuntimeIdentity:
    # Observed fields come from this installation, never from the requested release.
    base=Path(__file__).resolve().parents[2]
    release_path=base/'module_release.json'
    release=json.loads(release_path.read_text()) if release_path.is_file() else {}
    lock=base/'uv.lock'
    lock_sha=hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() and not lock.is_symlink() else ''
    source_root=base/'vendor'/'rebound_baseline'
    source_sha=capsule.manifest_sha256 if source_root.is_dir() and not verify_capsule(capsule,source_root) else ''
    return RuntimeIdentity(str(release.get('module_id','')),str(release.get('release_id','')),module_code_digest(),platform.python_version(),lock_sha,sha256_json(effective_config),source_sha,datetime.now(timezone.utc))


def evaluate_health(expected:ModuleManifest,binding:Binding,expected_config_sha256:str,observed:RuntimeIdentity,input_evidence:dict) -> HealthReport:
    reasons=[]
    want={'module_id':expected.module_id,'release_id':expected.release_id,'code_manifest_sha256':expected.code_manifest_sha256,
        'dependency_lock_sha256':expected.dependency_lock_sha256,'effective_config_sha256':expected_config_sha256,'source_capsule_sha256':binding.source_capsule_sha256}
    missing=False
    for key,value in want.items():
        actual=getattr(observed,key)
        if not actual:missing=True;reasons.append('RUNTIME_'+key.upper()+'_UNVERIFIED')
        elif actual!=value:reasons.append('RUNTIME_'+key.upper()+'_MISMATCH')
    # Treat declared Python major.minor as a runtime floor, not a patch-level pin.
    try:
        compatible=tuple(map(int,observed.python_version.split('.')[:2]))>=tuple(map(int,expected.python_version.split('.')[:2]))
    except (ValueError,AttributeError):compatible=False
    if not compatible:reasons.append('PYTHON_RUNTIME_INCOMPATIBLE')
    identity='MISMATCH' if any(r.endswith('_MISMATCH') for r in reasons) else 'UNVERIFIED' if missing else 'MATCH'
    status=input_evidence.get('status')
    if status in ('MISSING','INVALID'):
        input_status=status;reasons.append('INPUT_'+status)
    elif (status=='READY' and input_evidence.get('data_kind')=='OWNER_VERIFIED'
          and input_evidence.get('owner_verified') is True
          and input_evidence.get('stable_snapshot_verified') is True
          and binding.input_snapshot_sha256 is not None
          and input_evidence.get('snapshot_sha256')==binding.input_snapshot_sha256):
        input_status='READY'
    else:
        input_status='UNVERIFIED';reasons.append('INPUT_UNVERIFIED')
    if input_evidence.get('data_kind')=='SYNTHETIC':reasons.append('SYNTHETIC_NOT_REAL_BUSINESS')
    actual=asdict(observed);actual['observed_at']=observed.observed_at.isoformat()
    want['python_minimum']=expected.python_version
    return HealthReport('v5.health.v1',identity,'COMPATIBLE' if compatible else 'INCOMPATIBLE',input_status,tuple(reasons),want,actual)
