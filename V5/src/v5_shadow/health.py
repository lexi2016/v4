"""Keep identity, dependency compatibility and input readiness separate."""
import hashlib
import json
import platform
import importlib.metadata
import importlib.util
import tomllib
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
from .contracts import Binding,HealthReport,ModuleManifest,RuntimeIdentity,SourceCapsule
from .digests import sha256_json,canonical_bytes
from .source_capsule import verify_capsule


def module_code_digest(root: Path | None=None) -> str:
    root=Path(root) if root else Path(__file__).resolve().parent
    entries=[]
    for path in sorted(root.rglob('*.py')):
        if path.is_symlink():raise ValueError('CODE_SYMLINK_REJECTED')
        entries.append({'path':path.relative_to(root).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    if not entries:raise ValueError('CODE_MISSING')
    return sha256_json({'files':entries})


def observe_dependencies(lock:Path) -> dict:
    """Compare actual installed distributions and import origins to this lock.

    This is installation identity, not a claim that wheel contents are secured
    against a hostile administrator or that arbitrary future locks are supported.
    """
    names={'python-dateutil':'dateutil','numpy':'numpy','pandas':'pandas',
           'pyarrow':'pyarrow','pytz':'pytz','six':'six','tzdata':'tzdata'}
    rows=[];reasons=[];seen=set()
    try:
        with lock.open('rb') as stream:packages=tomllib.load(stream)['package']
        for package in packages:
            if 'registry' not in package.get('source',{}):continue
            name=package['name'];wanted=package['version']
            if name in seen or name not in names:
                reasons.append('DEPENDENCY_LOCK_UNSUPPORTED');continue
            seen.add(name)
            try:
                version=importlib.metadata.version(name)
                dist=importlib.metadata.distribution(name)
                spec=importlib.util.find_spec(names[name])
                origin=Path(spec.origin).resolve() if spec and spec.origin else None
                site=Path(dist.locate_file('')).resolve()
                relative=origin.relative_to(site).as_posix() if origin else ''
                recorded={str(item).replace('\\','/') for item in (dist.files or ())}
                rows.append({'name':name,'version':version,'metadata_version':dist.version,
                             'origin':str(origin or ''),'installation_root':str(site)})
                if version!=wanted or dist.version!=wanted:reasons.append('DEPENDENCY_VERSION_MISMATCH:'+name)
                if not origin or relative not in recorded:reasons.append('DEPENDENCY_ORIGIN_MISMATCH:'+name)
            except (ImportError,ValueError,TypeError,OSError):
                reasons.append('DEPENDENCY_UNVERIFIED:'+name)
        if seen!=set(names):reasons.append('DEPENDENCY_LOCK_INCOMPLETE')
    except (OSError,ValueError,KeyError,TypeError):
        reasons.append('DEPENDENCY_LOCK_UNREADABLE')
    return {'status':'MATCH' if not reasons else 'UNVERIFIED',
            'packages':sorted(rows,key=lambda row:row['name']),'reason_codes':sorted(set(reasons))}


def observe_runtime(module:ModuleManifest,capsule:SourceCapsule,effective_config:dict) -> RuntimeIdentity:
    # Observed fields come from this installation, never from the requested release.
    base=Path(__file__).resolve().parents[2]
    release_path=base/'module_release.json'
    release=json.loads(release_path.read_text()) if release_path.is_file() else {}
    lock=base/'uv.lock'
    lock_sha=hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() and not lock.is_symlink() else ''
    dependencies=observe_dependencies(lock)
    if dependencies['status']!='MATCH':lock_sha=''
    source_root=base/'vendor'/'rebound_baseline'
    source_sha=capsule.manifest_sha256 if source_root.is_dir() and not verify_capsule(capsule,source_root) else ''
    return RuntimeIdentity(str(release.get('module_id','')),str(release.get('release_id','')),module_code_digest(),platform.python_version(),lock_sha,sha256_json(effective_config),source_sha,datetime.now(timezone.utc),sha256_json(dependencies),canonical_bytes(dependencies).decode())


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
    compatibility='INCOMPATIBLE' if not compatible else 'COMPATIBLE' if observed.dependency_lock_sha256 else 'UNVERIFIED'
    return HealthReport('v5.health.v1',identity,compatibility,input_status,tuple(reasons),want,actual)
