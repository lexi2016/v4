"""Publication evidence emitted by the EXISTING hourly-input collector.

This is not a news collector. It records the bytes that the owner has actually
published and the wall-clock time at which those bytes became observable.
Trust boundary: the configured owner root and its owned data directory, not
an arbitrary producer/version string inside an input JSON. No mtime fallback.
"""
from __future__ import annotations
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Mapping
from zoneinfo import ZoneInfo

SCHEMA = 'v4.manager_input_publication.v1'
PRODUCER = 'ops.collect_hourly_research_input'
HK = ZoneInfo('Asia/Hong_Kong')
CODE_PATHS = ('ops/collect_hourly_research_input.py', 'domains/research_hourly.py')
CODE_KEYS = ('collector_identity_sha256', 'research_hourly_domain_identity_sha256')
SLOTS = frozenset({'0830', *(f'{hour:02}00' for hour in range(7,24))})

class PublicationError(ValueError):
    """A bounded evidence code; never return host paths to the UI."""


def encoded(value: Any) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def aware(value: Any) -> datetime:
    if not isinstance(value,str): raise PublicationError('PUBLICATION_TIME_MISSING')
    try: dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as exc: raise PublicationError('PUBLICATION_TIME_INVALID') from exc
    if dt.tzinfo is None or dt.utcoffset() is None: raise PublicationError('PUBLICATION_TIME_NAIVE')
    return dt.astimezone(HK)


def resolve(root: Path, relative: str) -> Path:
    if not isinstance(relative,str) or not relative or '\\' in relative:
        raise PublicationError('EVIDENCE_PATH_INVALID')
    parts=PurePosixPath(relative)
    if parts.is_absolute() or '..' in parts.parts or parts.as_posix()!=relative:
        raise PublicationError('EVIDENCE_PATH_INVALID')
    root=Path(root).expanduser().resolve()
    path=root
    for part in parts.parts:
        path=path/part
        if path.is_symlink(): raise PublicationError('EVIDENCE_SYMLINK_REFUSED')
    if not path.resolve().is_relative_to(root): raise PublicationError('EVIDENCE_PATH_ESCAPE')
    return path


def load(path: Path) -> dict[str,Any]:
    try: value=json.loads(path.read_bytes())
    except (OSError,ValueError,UnicodeError) as exc: raise PublicationError('EVIDENCE_UNREADABLE') from exc
    if not isinstance(value,dict): raise PublicationError('EVIDENCE_OBJECT_REQUIRED')
    return value


def atomic_create(path: Path, data: bytes) -> bool:
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        try: os.link(name,path); return True
        except FileExistsError: return False
    finally:
        try: os.unlink(name)
        except FileNotFoundError: pass


def _identity(path: Path, data_root: Path, owner_root: Path) -> tuple[str,dict,dict,dict]:
    try: relative=Path(path).absolute().relative_to(Path(data_root).absolute()).as_posix()
    except ValueError as exc: raise PublicationError('INPUT_OUTSIDE_OWNED_ROOT') from exc
    path=resolve(data_root,relative)
    value=load(path); manifest=value.get('source_manifest')
    if not isinstance(manifest,dict): raise PublicationError('CATALYST_SOURCE_MANIFEST_MISSING')
    for key,expected in {'schema_version':'v3_research_lane.v2','module_id':'research_intelligence',
                         'write_policy':'read_only','default_status':'RESEARCH_ONLY',
                         'buy_gate_effect':'none','live_order_effect':'none'}.items():
        if value.get(key)!=expected: raise PublicationError('CATALYST_INPUT_SCHEMA_OR_SAFETY_INVALID')
    if manifest.get('module_path')!='v3.5/domains/research_hourly':
        raise PublicationError('CATALYST_MODULE_IDENTITY_INVALID')
    date=value.get('trade_date'); slot=manifest.get('hourly_slot')
    if not isinstance(date,str) or not re.fullmatch(r'\d{8}',date) or slot not in SLOTS:
        raise PublicationError('CATALYST_SOURCE_DATE_SLOT_INVALID')
    if relative!=f'research/incoming/{date}/{slot}.json':
        raise PublicationError('CATALYST_EXACT_INPUT_PATH_MISMATCH')
    if manifest.get('trade_date')!=date or manifest.get('producer')!=PRODUCER:
        raise PublicationError('CATALYST_OWNER_IDENTITY_MISMATCH')
    if not isinstance(manifest.get('version'),str) or not re.fullmatch(r'\d{14}-[0-9a-f]{8}',manifest['version']):
        raise PublicationError('CATALYST_RUN_MISSING')
    code={key:digest(resolve(owner_root,rel).read_bytes()) for key,rel in zip(CODE_KEYS,CODE_PATHS)}
    if any(manifest.get(key)!=sha for key,sha in code.items()):
        raise PublicationError('CATALYST_OWNER_CODE_IDENTITY_MISMATCH')
    code['publication_writer_sha256']=digest(resolve(owner_root,'infrastructure/manager_input_attestation.py').read_bytes())
    generated=aware(manifest.get('generated_at'))
    if generated.strftime('%Y%m%d')!=date:
        raise PublicationError('CATALYST_MANIFEST_DATE_MISMATCH')
    return relative,value,manifest,code


def _source_bindings(data_root: Path, manifest: Mapping[str,Any], available_at: datetime) -> list[dict]:
    refs=manifest.get('source_receipts')
    if not isinstance(refs,list) or not refs or len(refs)!=len(set(refs)):
        raise PublicationError('CATALYST_SOURCE_RECEIPTS_MISSING')
    date=manifest['trade_date']; slot=manifest['hourly_slot']
    expected=f'research_module/runtime_outputs/zsxq_hourly/{date}/{slot}/v35_zsxq_hourly_status_{date}_{slot}.json'
    output=[]
    for ref in sorted(refs):
        if ref!=expected: raise PublicationError('CATALYST_SOURCE_RECEIPT_OWNER_MISMATCH')
        path=resolve(data_root,ref); value=load(path)
        if (value.get('trade_date')!=date or value.get('slot')!=slot or value.get('status_path')!=ref
            or value.get('fetch_ok') is not True or value.get('status')!='READY'):
            raise PublicationError('CATALYST_SOURCE_RECEIPT_INVALID')
        if aware(value.get('fetched_at'))>available_at:
            raise PublicationError('CATALYST_SOURCE_FETCH_AFTER_PUBLICATION')
        # The existing collector already validates the source's item quality.
        # Here its exact status identity and actual bytes are bound, not re-fetched.
        for key in ('generated_at','available_at','captured_at','completed_at','published_at'):
            if value.get(key) is not None and aware(value[key])>available_at:
                raise PublicationError('CATALYST_SOURCE_RECEIPT_AFTER_PUBLICATION')
        output.append({'artifact_ref':ref,'sha256':digest(path.read_bytes())})
    return output


def publish_attestation(path: Path, *, data_root: Path, owner_root: Path,
                        available_at: datetime | None = None) -> dict[str,Any]:
    """Post-publication hook; production callers MUST omit the test clock seam.

    No rewriting/backdating of the input or of an older receipt. Legacy and
    recovery outputs that cannot meet this contract remain unattested.
    """
    actual=available_at or datetime.now(HK)
    if actual.tzinfo is None: raise PublicationError('PUBLICATION_TIME_NAIVE')
    actual=actual.astimezone(HK)
    relative,value,manifest,code=_identity(path,data_root,owner_root)
    if aware(manifest['generated_at'])>actual: raise PublicationError('PUBLICATION_BEFORE_INPUT')
    source_bindings=_source_bindings(data_root,manifest,actual)
    sidecar=resolve(data_root,relative+'.publication.json')
    record={'schema_version':SCHEMA,'producer':PRODUCER,'market':'MULTI_MARKET_RESEARCH',
            'trade_date':value['trade_date'],'slot':manifest['hourly_slot'],'run_id':'hip-'+digest(resolve(data_root,relative).read_bytes())[:24],
            'artifact_ref':relative,'artifact_sha256':digest(resolve(data_root,relative).read_bytes()),
            'source_manifest_sha256':digest(encoded(manifest)), 'owner_code':code,
            'available_at':actual.isoformat(timespec='microseconds'),'source_bindings':source_bindings,
            'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    if not atomic_create(sidecar,encoded(record)):
        previous=read_attestation(path,data_root=data_root,owner_root=owner_root,as_of=actual)
        if previous['artifact_sha256']!=record['artifact_sha256']:
            raise PublicationError('PUBLICATION_IMMUTABLE_CONFLICT')
        return previous
    return record


def read_attestation(path: Path, *, data_root: Path, owner_root: Path, as_of: datetime) -> dict:
    relative,value,manifest,code=_identity(path,data_root,owner_root)
    record=load(resolve(data_root,relative+'.publication.json'))
    actual=aware(record.get('available_at'))
    if as_of.tzinfo is None or actual>as_of: raise PublicationError('CATALYST_SOURCE_AFTER_AS_OF')
    expected={'schema_version':SCHEMA,'producer':PRODUCER,'market':'MULTI_MARKET_RESEARCH',
              'trade_date':value['trade_date'],'slot':manifest['hourly_slot'],'run_id':'hip-'+digest(resolve(data_root,relative).read_bytes())[:24],
              'artifact_ref':relative,'artifact_sha256':digest(resolve(data_root,relative).read_bytes()),
              'source_manifest_sha256':digest(encoded(manifest)),'owner_code':code,
              'available_at':record['available_at'],'source_bindings':_source_bindings(data_root,manifest,actual),
              'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    if encoded(record)!=encoded(expected): raise PublicationError('CATALYST_PUBLICATION_IDENTITY_OR_SHA_MISMATCH')
    if aware(manifest['generated_at'])>actual: raise PublicationError('PUBLICATION_BEFORE_INPUT')
    # A receipt observed on a later day cannot be used to prove earlier availability.
    if actual.strftime('%Y%m%d')<value['trade_date']:
        raise PublicationError('CATALYST_PUBLICATION_DATE_MISMATCH')
    return record
