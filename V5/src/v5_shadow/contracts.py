from dataclasses import dataclass

@dataclass(frozen=True)
class SourceEntry:
    repository: str
    commit: str
    variant: str
    snapshot_path: str
    relative_path: str
    git_blob_sha: str
    sha256: str

@dataclass(frozen=True)
class SourceCapsule:
    entries: tuple[SourceEntry, ...]
    manifest_sha256: str
    python_version: str
    dependency_lock_sha256: str

from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
from .digests import canonical_bytes

@dataclass(frozen=True)
class SafetyFlags:
    research_only: bool = True
    production_allowed: bool = False
    buy_gate_updated: bool = False
    orders_sent: bool = False

@dataclass(frozen=True)
class DependencyRequirement:
    module_id: str
    input_contract: str
    required_capabilities: tuple[str, ...]

@dataclass(frozen=True)
class ModuleManifest:
    schema_version: str
    module_id: str
    release_id: str
    code_manifest_sha256: str
    python_version: str
    dependency_lock_sha256: str
    capabilities: tuple[str, ...]
    requires: tuple[DependencyRequirement, ...]
    input_contracts: tuple[str, ...]
    output_contract: str
    entrypoint: str
    safety: SafetyFlags

@dataclass(frozen=True)
class Binding:
    authority_root: Path | None
    shadow_root: Path
    calendar_sha256: str
    source_capsule_sha256: str
    input_snapshot_sha256: str | None

@dataclass(frozen=True)
class Composition:
    schema_version: str
    revision: int
    modules: dict[str, ModuleManifest]
    bindings: dict[str, Binding]

@dataclass(frozen=True)
class ShadowRequest:
    request_id: str
    target_trade_date: str
    research_cutoff: datetime
    requested_at: datetime
    execution_kind: str
    data_kind: str
    composition_sha256: str
    input_snapshot_sha256: str | None

@dataclass(frozen=True)
class RuntimeIdentity:
    module_id: str
    release_id: str
    code_manifest_sha256: str
    python_version: str
    dependency_lock_sha256: str
    effective_config_sha256: str
    source_capsule_sha256: str
    observed_at: datetime
    dependency_environment_sha256: str = ''
    dependency_environment_json: str = ''

LegacyScreen = dict

@dataclass(frozen=True)
class HealthReport:
    schema_version: str
    identity_status: str
    compatibility_status: str
    input_status: str
    reason_codes: tuple[str, ...]
    expected: dict
    observed: dict

@dataclass(frozen=True)
class ShadowResult:
    schema_version: str
    run_id: str
    request: ShadowRequest
    runtime: RuntimeIdentity
    legacy_screen: LegacyScreen
    business_status: str
    evaluated_count: int | None
    formal_eligibility_status: str
    natural_verified: bool
    started_at: datetime
    finished_at: datetime
    safety: SafetyFlags

@dataclass(frozen=True)
class RunReference:
    run_id: str
    artifact_sha256: str
    manifest_sha256: str
    receipt_sha256: str
    idempotency_key: str


def exact_keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('CONTRACT_FIELDS_INVALID')


def text(value):
    if not isinstance(value,str) or not value.strip() or len(value)>1024:
        raise ValueError('CONTRACT_TEXT_INVALID')
    return value


def sha(value):
    if not isinstance(value,str) or re.fullmatch('[0-9a-f]{64}',value) is None:
        raise ValueError('CONTRACT_SHA_INVALID')
    return value


def texts(value):
    if not isinstance(value,list) or len(value)>128 or len(set(map(str,value)))!=len(value):
        raise ValueError('CONTRACT_LIST_INVALID')
    return tuple(text(v) for v in value)


def aware(value):
    if not isinstance(value,str):
        raise ValueError('CONTRACT_TIME_INVALID')
    try:
        result=datetime.fromisoformat(value)
    except (TypeError,ValueError) as exc:
        raise ValueError('CONTRACT_TIME_INVALID') from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('CONTRACT_TIMEZONE_REQUIRED')
    return result


def trade_date(value):
    if not isinstance(value,str) or re.fullmatch('[0-9]{8}',value) is None:
        raise ValueError('CONTRACT_DATE_INVALID')
    try:
        datetime.strptime(value,'%Y%m%d')
    except ValueError as exc:
        raise ValueError('CONTRACT_DATE_INVALID') from exc
    return value


def parse_safety(value):
    expected={'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    exact_keys(value, expected)
    if any(type(value[k]) is not bool or value[k] is not v for k,v in expected.items()):
        raise ValueError('SAFETY_BOUNDARY_INVALID')
    return SafetyFlags()


def parse_manifest(value: dict) -> ModuleManifest:
    exact_keys(value, ModuleManifest.__dataclass_fields__)
    canonical_bytes(value)
    if value['schema_version']!='v5.module.v1':
        raise ValueError('MODULE_SCHEMA_INVALID')
    module=text(value['module_id'])
    if re.fullmatch('[a-z][a-z0-9_]{0,63}',module) is None:
        raise ValueError('MODULE_ID_INVALID')
    if module=='rebound_shadow' and (value['output_contract']!='v5.rebound_shadow.v1' or value['entrypoint']!='v5_shadow.worker:worker_main'):
        raise ValueError('MODULE_ENTRYPOINT_INVALID')
    if not isinstance(value['requires'],list):
        raise ValueError('CONTRACT_DEPENDENCIES_INVALID')
    requires=[]
    for item in value['requires']:
        exact_keys(item, DependencyRequirement.__dataclass_fields__)
        requires.append(DependencyRequirement(text(item['module_id']),text(item['input_contract']),texts(item['required_capabilities'])))
    if len({r.module_id for r in requires}) != len(requires):
        raise ValueError('CONTRACT_DEPENDENCIES_INVALID')
    version=text(value['python_version'])
    if re.fullmatch(r'3\.[0-9]+(?:\.[0-9]+)?',version) is None:
        raise ValueError('PYTHON_VERSION_INVALID')
    return ModuleManifest(value['schema_version'],module,text(value['release_id']),sha(value['code_manifest_sha256']),version,
        sha(value['dependency_lock_sha256']),texts(value['capabilities']),tuple(requires),texts(value['input_contracts']),text(value['output_contract']),text(value['entrypoint']),parse_safety(value['safety']))


def parse_request(value: dict) -> ShadowRequest:
    exact_keys(value, ShadowRequest.__dataclass_fields__)
    canonical_bytes(value)
    request_id=text(value['request_id'])
    if re.fullmatch('[a-zA-Z0-9_-]{1,128}',request_id) is None:
        raise ValueError('REQUEST_ID_INVALID')
    target=trade_date(value['target_trade_date'])
    cutoff, requested=aware(value['research_cutoff']),aware(value['requested_at'])
    kind=value['execution_kind']
    if kind not in ('SHADOW_MANUAL','SHADOW_REPLAY') or value['data_kind'] not in ('SYNTHETIC','OWNER_VERIFIED'):
        raise ValueError('REQUEST_KIND_INVALID')
    if cutoff>requested:
        raise ValueError('FUTURE_CUTOFF')
    if kind=='SHADOW_MANUAL' and cutoff.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d')!=target:
        raise ValueError('HISTORICAL_CUTOFF_REQUIRES_REPLAY')
    input_sha=value['input_snapshot_sha256']
    if input_sha is not None:sha(input_sha)
    return ShadowRequest(request_id,target,cutoff,requested,kind,value['data_kind'],sha(value['composition_sha256']),input_sha)
