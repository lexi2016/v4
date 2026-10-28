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

from domains.research_source_validation import collector_source_cutoff, strict_source_receipt_time
from infrastructure.research_source_evidence import read_zsxq_slot_evidence

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
    if manifest.get('publication_clock_contract') != 'ACTUAL_COMPLETION_V1':
        raise PublicationError('PUBLICATION_COMPLETION_CONTRACT_MISSING')
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
    manual_empty = (
        manifest.get('materialization_origin') == 'MANUAL_RECOVERY'
        and manifest.get('capture_origin') == 'ORIGINAL_SLOT'
        and manifest.get('original_time_capture') is True
        and manifest.get('natural_execution_verified') is False
    )
    output=[]
    for ref in sorted(refs):
        if ref!=expected: raise PublicationError('CATALYST_SOURCE_RECEIPT_OWNER_MISMATCH')
        path=resolve(data_root,ref)
        evidence=read_zsxq_slot_evidence(data_root,date,slot)
        if evidence is None or evidence.status_path.resolve()!=path.resolve():
            raise PublicationError('CATALYST_SOURCE_RECEIPT_INVALID')
        value=evidence.status
        if (value.get('trade_date')!=date or value.get('slot')!=slot or value.get('status_path')!=ref
            or value.get('source')!='zsxq' or value.get('fetch_ok') is not True
            or value.get('status') not in ({'READY','READY_EMPTY'} if manual_empty else {'READY','PARTIAL'})):
            raise PublicationError('CATALYST_SOURCE_RECEIPT_INVALID')
        fetched=strict_source_receipt_time(value.get('fetched_at'))
        cutoff=strict_source_receipt_time(value.get('source_cutoff'))
        if fetched is None or cutoff is None:
            raise PublicationError('CATALYST_SOURCE_RECEIPT_INVALID')
        completed = strict_source_receipt_time(value.get('source_completed_at'))
        if (completed is None or completed.strftime('%Y%m%d') != date
            or completed < fetched or completed > available_at
            or completed > aware(manifest.get('generated_at'))
            or completed > aware(manifest.get('published_at'))
            or value.get('summary_sha256') != evidence.summary_sha256
            or value.get('fetch_result_sha256') != evidence.fetch_result_sha256):
            raise PublicationError('CATALYST_SOURCE_COMPLETION_UNVERIFIED')
        if value.get('status') == 'PARTIAL':
            expected_partial = {
                'zsxq_source_completeness': 'PARTIAL',
                'zsxq_status_sha256': evidence.status_sha256,
                'zsxq_summary_sha256': evidence.summary_sha256,
                'zsxq_fetch_result_sha256': evidence.fetch_result_sha256,
                'zsxq_fetched_at': value['fetched_at'],
                'zsxq_source_completed_at': value['source_completed_at'],
            }
            if any(manifest.get(key) != val for key, val in expected_partial.items()):
                raise PublicationError('CATALYST_PARTIAL_SOURCE_BINDING_INVALID')
        receipt_sha=evidence.status_sha256
        declared_receipt_sha=str(manifest.get('source_receipt_sha256') or '').lower()
        if declared_receipt_sha and declared_receipt_sha!=receipt_sha:
            raise PublicationError('CATALYST_SOURCE_RECEIPT_SHA_MISMATCH')
        if manual_empty:
            expected_cutoff=collector_source_cutoff(date,slot)
            if (value.get('status')!='READY_EMPTY' or not declared_receipt_sha
                or manifest.get('source_cutoff')!=value.get('source_cutoff')
                or cutoff!=expected_cutoff or fetched.strftime('%Y%m%d')!=date
                or fetched>expected_cutoff):
                raise PublicationError('CATALYST_READY_EMPTY_RECEIPT_INVALID')
            proof=manifest.get('ready_empty_source_proof')
            expected_proof={
                'schema_version':'v3_5.zsxq_ready_empty.v1',
                'trade_date':date,'slot':slot,'status':'READY_EMPTY',
                'source_receipt_path':expected,'source_receipt_sha256':receipt_sha,
                'summary_sha256':evidence.summary_sha256,
                'fetch_result_sha256':evidence.fetch_result_sha256,
                'fetch_ok':True,'fetch_success':True,
                'page_count':value.get('page_count'),'topic_count':0,
                'effective_topic_count':0,'fetched_at':value.get('fetched_at'),
                'source_cutoff':value.get('source_cutoff'),
                'capture_origin':'ORIGINAL_SLOT',
                'materialization_origin':'MANUAL_RECOVERY',
                'materialized_at':manifest.get('materialized_at'),
                'available_at':manifest.get('available_at'),
                'natural_execution_verified':False,
            }
            try:
                materialized=aware(manifest.get('materialized_at'))
            except (TypeError,ValueError):
                materialized=None
            if (proof!=expected_proof or materialized is None
                or materialized.strftime('%Y%m%d')!=date
                or materialized<expected_cutoff or materialized>available_at
                or manifest.get('available_at')!=manifest.get('materialized_at')
                or manifest.get('generated_at')!=manifest.get('materialized_at')
                or manifest.get('published_at')!=manifest.get('materialized_at')):
                raise PublicationError('CATALYST_READY_EMPTY_PROOF_INVALID')
        if aware(value.get('fetched_at'))>available_at:
            raise PublicationError('CATALYST_SOURCE_FETCH_AFTER_PUBLICATION')
        # The existing collector already validates the source's item quality.
        # Here its exact status identity and actual bytes are bound, not re-fetched.
        for key in ('generated_at','available_at','captured_at','completed_at','published_at'):
            if value.get(key) is not None and aware(value[key])>available_at:
                raise PublicationError('CATALYST_SOURCE_RECEIPT_AFTER_PUBLICATION')
        output.append({'artifact_ref':ref,'sha256':receipt_sha})
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
    if actual.strftime('%Y%m%d')!=value['trade_date']:
        raise PublicationError('CATALYST_PUBLICATION_DATE_MISMATCH')
    return record


HOURLY_SCHEMA = 'v4.hourly_research_publication.v1'


def _hourly_bindings(data_root: Path, owner_root: Path, date: str, slot: str,
                     mode: str, as_of: datetime) -> tuple[Path, dict]:
    """Bind already-written materialization, its receipt and original input."""
    from infrastructure.research_store import HourlyResearchStore
    store = HourlyResearchStore(data_root)
    payload = store.read_exact(date, slot, mode=mode)
    if payload is None:
        raise PublicationError('HOURLY_PUBLICATION_PAYLOAD_MISSING')
    relative = store._relative(date, slot, mode)
    receipt_relative = store._receipt_relative(date, slot, mode)
    payload_path = resolve(data_root, relative)
    receipt_path = resolve(data_root, receipt_relative)
    source_sha = payload.get('source_input_sha256')
    if not isinstance(source_sha, str) or not re.fullmatch('[0-9a-f]{64}', source_sha):
        raise PublicationError('HOURLY_PUBLICATION_SOURCE_INVALID')
    witness = resolve(data_root, f'research/hourly/source/{source_sha}.json')
    if digest(witness.read_bytes()) != source_sha:
        raise PublicationError('HOURLY_PUBLICATION_SOURCE_SHA_MISMATCH')
    input_path = resolve(data_root, f'research/incoming/{date}/{slot}.json')
    if digest(input_path.read_bytes()) != source_sha:
        raise PublicationError('HOURLY_PUBLICATION_INPUT_SHA_MISMATCH')
    publication = read_attestation(input_path, data_root=data_root,
                                   owner_root=owner_root, as_of=as_of)
    bindings = {
        'schema_version': HOURLY_SCHEMA, 'trade_date': date, 'slot': slot, 'mode': mode,
        'artifact_ref': relative, 'artifact_sha256': digest(payload_path.read_bytes()),
        'receipt_ref': receipt_relative, 'receipt_sha256': digest(receipt_path.read_bytes()),
        'source_input_sha256': source_sha,
        'input_publication_sha256': digest(resolve(data_root, f'research/incoming/{date}/{slot}.json.publication.json').read_bytes()),
        'input_available_at': publication['available_at'],
        'availability_time_status': 'UNVERIFIED_LOCAL_CLOCK',
        'materializer_sha256': digest(resolve(owner_root, 'ops/run_hourly_research.py').read_bytes()),
        'RESEARCH_ONLY': True, 'production_allowed': False,
        'buy_gate_updated': False, 'orders_sent': False,
    }
    return resolve(data_root, f'research/hourly/publication/{mode.lower()}/{date}/{slot}.json'), bindings


def publish_hourly_attestation(*, data_root: Path, owner_root: Path,
                               date: str, slot: str, mode: str) -> dict:
    """Called only after the existing materializer has finished its writes.

    The clock is sampled after reading the complete payload/receipt/witness.
    Retries preserve earlier evidence; missing evidence is recorded at retry
    time, never at the source's earlier generation time.
    """
    sidecar, bindings = _hourly_bindings(data_root, owner_root, date, slot, mode, datetime.now(HK))
    actual = datetime.now(HK)
    record = {**bindings, 'available_at': actual.isoformat(timespec='microseconds')}
    if atomic_create(sidecar, encoded(record)):
        return record
    return _read_hourly_publication_metadata(data_root=data_root, owner_root=owner_root,
                                             date=date, slot=slot, mode=mode, as_of=actual)


def _read_hourly_publication_metadata(*, data_root: Path, owner_root: Path,
                            date: str, slot: str, mode: str, as_of: datetime) -> dict:
    sidecar, bindings = _hourly_bindings(data_root, owner_root, date, slot, mode, as_of)
    record = load(sidecar)
    actual = aware(record.get('available_at'))
    if actual > as_of or actual < aware(bindings['input_available_at']):
        raise PublicationError('HOURLY_PUBLICATION_AFTER_AS_OF')
    if actual.strftime('%Y%m%d') != date:
        raise PublicationError('HOURLY_PUBLICATION_DATE_MISMATCH')
    if encoded(record) != encoded({**bindings, 'available_at': record['available_at']}):
        raise PublicationError('HOURLY_PUBLICATION_IDENTITY_OR_SHA_MISMATCH')
    return record


def read_hourly_attestation(*, data_root: Path, owner_root: Path,
                            date: str, slot: str, mode: str, as_of: datetime,
                            scheduler_ledger_root: Path | None = None) -> dict:
    """Use original scheduler completion as a conservative local upper bound.

    The mutable sidecar alone is never a time witness. The independent original
    dispatch receipt must bind its exact returned record, archive and source.
    The existing unanchored hash chain is a local consistency contract; it does
    NOT authenticate coordinated malicious rewrites of the whole ledger.
    """
    record = _read_hourly_publication_metadata(data_root=data_root, owner_root=owner_root,
                                             date=date, slot=slot, mode=mode, as_of=as_of)
    if scheduler_ledger_root is None:
        raise PublicationError('HOURLY_PUBLICATION_TIME_WITNESS_UNAVAILABLE')
    witness = _scheduler_completion_witness(record, data_root=data_root, owner_root=owner_root,
                                          ledger_root=scheduler_ledger_root, as_of=as_of)
    return {**record, 'completion_witness': witness}


def _scheduler_completion_witness(record: dict, *, data_root: Path, owner_root: Path,
                                  ledger_root: Path, as_of: datetime) -> dict:
    from infrastructure.owned_io import SafeRoot
    date, slot, mode = record['trade_date'], record['slot'], record['mode']
    if mode != 'LIVE':
        raise PublicationError('HOURLY_COMPLETION_MODE_INVALID')
    ledger = SafeRoot(ledger_root)
    folder = f'receipts/live/{date}/{slot}'
    files = ledger.files(folder, suffix='.dispatch-receipt.json')
    receipts = []
    for name in files:
        raw = ledger.read_bytes(f'{folder}/{name}')
        value = json.loads(raw)
        if (not isinstance(value, dict) or value.get('schema_version') != 'v3_5.dispatch.v1'
            or value.get('business_date') != date or value.get('slot') != slot
            or value.get('mode') != 'LIVE'
            or not re.fullmatch('[0-9a-f]{32}', str(value.get('run_id', '')))
            or name != value['run_id'] + '.dispatch-receipt.json'
            or value.get('receipt_path') != f'{folder}/{name}'
            or value.get('ledger_sha256') != digest(encoded({key: val for key, val in value.items() if key != 'ledger_sha256'})[:-1])):
            raise PublicationError('HOURLY_COMPLETION_LEDGER_INVALID')
        receipts.append((value, raw))
    by_sha = {value['ledger_sha256']: value for value, _ in receipts}
    if len(by_sha) != len(receipts) or not receipts:
        raise PublicationError('HOURLY_COMPLETION_WITNESS_MISSING')
    heads = [value for value in by_sha.values() if not value.get('prev_ledger_sha256')]
    successors = {}
    for value in by_sha.values():
        prev = value.get('prev_ledger_sha256', '')
        if prev:
            if prev not in by_sha or prev in successors:
                raise PublicationError('HOURLY_COMPLETION_LEDGER_CHAIN_INVALID')
            successors[prev] = value['ledger_sha256']
    if len(heads) != 1:
        raise PublicationError('HOURLY_COMPLETION_LEDGER_CHAIN_INVALID')
    current, seen = heads[0]['ledger_sha256'], set()
    while current not in seen:
        seen.add(current)
        if current not in successors:break
        current = successors[current]
    if len(seen) != len(by_sha):
        raise PublicationError('HOURLY_COMPLETION_LEDGER_CHAIN_INVALID')
    manifest = json.loads(SafeRoot(owner_root.parent).read_bytes('release-manifest.json'))
    payload = json.loads(SafeRoot(data_root).read_bytes(record['artifact_ref']))
    payload_sha = digest(encoded(payload)[:-1])
    late = False
    for value, raw in receipts:
        if (value.get('status') != 'SUCCEEDED' or value.get('release_id') != manifest.get('release_id')
            or any(value.get(key) != date for key in ('scheduled_date', 'target_date'))
            or any(value.get(key) is not False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'))
            or any('hourly_research' not in value.get(key, []) for key in
                   ('selected_workload_ids', 'invoked_workload_ids', 'started_workload_ids', 'succeeded_workload_ids'))):
            continue
        matches = [item for item in value.get('workload_results', []) if isinstance(item, dict) and item.get('workload_id') == 'hourly_research']
        if len(matches) != 1:continue
        workload = matches[0]; authority = workload.get('_authoritative_payload')
        if (workload.get('status') != 'SUCCEEDED' or workload.get('exit_code') != 0
            or not {'ops.run_zsxq_hourly_delta', 'ops.collect_hourly_research_input', 'ops.run_hourly_research'}.issubset(workload.get('modules', []))
            or any(workload.get(key) is not False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'))
            or not isinstance(authority, dict)
            or authority.get('schema_version') != 'v3_5.hourly_research_run.v1'
            or authority.get('status') != 'SUCCEEDED'
            or authority.get('capture_origin') not in {'ORIGINAL_SLOT', 'LATE_RECOVERY'}
            or any(authority.get(key) is not False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'))
            or authority.get('business_date') != date or authority.get('target_date') != date
            or authority.get('slot') != slot or authority.get('mode') != mode
            or authority.get('payload_path') != record['artifact_ref']
            or authority.get('payload_sha256') != payload_sha
            or authority.get('external_source_sha256') != record['source_input_sha256']):
            continue
        if authority.get('hourly_publication') != record:
            raise PublicationError('HOURLY_COMPLETION_PUBLICATION_RECORD_MISMATCH')
        finished = aware(value.get('finished_at'))
        if finished < aware(record['available_at']) or finished.strftime('%Y%m%d') != date:
            raise PublicationError('HOURLY_COMPLETION_CLOCK_INVALID')
        if finished > as_of:
            late = True;continue
        return {'kind': 'ORIGINAL_SCHEDULER_LOCAL_COMPLETION_UPPER_BOUND',
                'receipt_ref': value['receipt_path'], 'receipt_sha256': digest(raw),
                'ledger_sha256': value['ledger_sha256'], 'run_id': value['run_id'],
                'finished_at': value['finished_at'], 'release_id': value['release_id'],
                'whole_ledger_malicious_rewrite_authenticated': False}
    raise PublicationError('HOURLY_COMPLETION_AFTER_AS_OF' if late else 'HOURLY_COMPLETION_WITNESS_MISSING')


# The installed launcher pins Stage. Stage's release inventory
# pins its fixed config; that config, not any research artifact, pins Main.
_MAIN_RESEARCH_FILES = (
    *CODE_PATHS, 'infrastructure/manager_input_attestation.py',
    'ops/run_hourly_research.py', 'ops/run_zsxq_hourly_delta.py',
    'infrastructure/research_source_evidence.py',
    'domains/research_source_validation.py', 'domains/research.py',
    'domains/report_subjects.py', 'infrastructure/scheduling/dispatcher.py',
    'infrastructure/scheduling/execution_ledger.py', 'infrastructure/scheduling/executor_registry.py',
    'infrastructure/scheduling/executor_registry_research.py', 'contracts/runtime_workloads.json',
)
_STAGE_RESEARCH_FILES = (
    'stage_center_tick_config.json', 'stage_center/research_context.py',
    'infrastructure/manager_input_attestation.py',
    'infrastructure/research_source_evidence.py',
    'domains/research_source_validation.py', 'domains/research_hourly.py',
    'domains/research.py',
)


def _absolute_release_app(value: Any) -> Path:
    if (not isinstance(value, str) or not value.startswith('/')
        or '\\' in value or '..' in Path(value).parts
        or str(Path(value)) != value or Path(value).name != 'app'):
        raise PublicationError('RESEARCH_OWNER_ROOT_INVALID')
    return Path(value)


def _release_manifest(app: Path, release_id: str, manifest_sha: str,
                      required: tuple[str, ...]) -> dict:
    """Read only exact pinned release files, using the existing no-follow I/O."""
    from infrastructure.owned_io import SafeRoot
    if not isinstance(manifest_sha, str) or not re.fullmatch('[0-9a-f]{64}', manifest_sha):
        raise PublicationError('RESEARCH_RELEASE_MANIFEST_PIN_INVALID')
    raw = SafeRoot(app.parent).read_bytes('release-manifest.json', max_bytes=16 * 1024 * 1024)
    if digest(raw) != manifest_sha:
        raise PublicationError('RESEARCH_RELEASE_MANIFEST_SHA_MISMATCH')
    manifest = json.loads(raw)
    if (manifest.get('schema_version') != 'v4.runtime_graph_repair_release.v1'
        or manifest.get('app_root') != str(app)
        or manifest.get('release_id') != release_id
        or manifest.get('RESEARCH_ONLY') is not True
        or any(manifest.get(key) is not False for key in
               ('production_allowed', 'buy_gate_updated', 'orders_sent'))):
        raise PublicationError('RESEARCH_RELEASE_IDENTITY_MISMATCH')
    inventory = manifest.get('application_inventory', {})
    entries = inventory.get('entries')
    if (not isinstance(entries, list) or inventory.get('entry_count') != len(entries)
        or digest(json.dumps(entries, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode()) != inventory.get('aggregate_sha256')
        or any(not isinstance(item, dict) or not isinstance(item.get('path'), str) for item in entries)):
        raise PublicationError('RESEARCH_RELEASE_INVENTORY_INVALID')
    by_path = {item['path']: item for item in entries}
    if len(by_path) != len(entries):
        raise PublicationError('RESEARCH_RELEASE_INVENTORY_DUPLICATE')
    source = SafeRoot(app)
    for relative in required:
        item = by_path.get(relative, {})
        content = source.read_bytes(relative, max_bytes=8 * 1024 * 1024)
        if (item.get('kind') != 'file' or item.get('size') != len(content)
            or item.get('sha256') != digest(content)):
            raise PublicationError('RESEARCH_RELEASE_CODE_OR_CONFIG_DRIFT')
    return manifest


def trusted_research_owner(stage_app: Path, data_root: Path) -> tuple[Path, Path, tuple[str, ...]]:
    """Resolve Main only through the existing launcher's Stage release pins.

    There is no input-derived owner path, artifact-provided code allowlist,
    current/latest discovery, root override argument or symlink fallback.
    Publication control must seal Main first, pin it in Stage's fixed config,
    seal Stage, then update the existing launcher's Stage identity tuple.
    """
    from infrastructure.owned_io import SafeRoot
    stage = _absolute_release_app(os.environ.get('V4_APP_ROOT'))
    if stage != stage_app:
        raise PublicationError('RESEARCH_STAGE_RUNTIME_ROOT_MISMATCH')
    manifest_path = os.environ.get('V4_RELEASE_MANIFEST_PATH')
    config_path = os.environ.get('STAGE_CENTER_CONFIG')
    if (manifest_path != str(stage.parent / 'release-manifest.json')
        or config_path != str(stage / 'stage_center_tick_config.json')):
        raise PublicationError('RESEARCH_STAGE_FIXED_PATH_MISMATCH')
    stage_pin = os.environ.get('V4_RELEASE_MANIFEST_SHA256', '')
    _release_manifest(stage, os.environ.get('V4_RELEASE_ID', ''), stage_pin, _STAGE_RESEARCH_FILES)
    config_raw = SafeRoot(stage).read_bytes('stage_center_tick_config.json')
    config = json.loads(config_raw)
    # Re-read the verified inventory binding for the exact bytes parsed here.
    stage_manifest = _release_manifest(stage, os.environ.get('V4_RELEASE_ID', ''), stage_pin, _STAGE_RESEARCH_FILES)
    config_entries = {item['path']: item for item in stage_manifest['application_inventory']['entries']}
    if digest(config_raw) != config_entries['stage_center_tick_config.json']['sha256']:
        raise PublicationError('RESEARCH_STAGE_CONFIG_DRIFT')
    if config.get('schema_version') != 'stage_center.tick_config.v1':
        raise PublicationError('RESEARCH_STAGE_CONFIG_SCHEMA_INVALID')
    configured_data = config.get('v4_research_data_root')
    if not isinstance(configured_data, str) or Path(configured_data) != data_root:
        raise PublicationError('RESEARCH_OWNER_DATA_ROOT_MISMATCH')
    with SafeRoot(configured_data).directory():
        pass
    binding = config.get('research_owner_binding')
    if (not isinstance(binding, dict) or set(binding) != {'app_root', 'release_id', 'manifest_sha256'}
        or not isinstance(binding.get('release_id'), str) or not binding['release_id']):
        raise PublicationError('RESEARCH_OWNER_BINDING_MISSING')
    owner = _absolute_release_app(binding['app_root'])
    _release_manifest(owner, binding['release_id'], binding['manifest_sha256'], _MAIN_RESEARCH_FILES)
    ledger_root = config.get('research_scheduler_ledger_root')
    if (not isinstance(ledger_root, str) or not ledger_root.startswith('/')
        or '..' in Path(ledger_root).parts or str(Path(ledger_root)) != ledger_root):
        raise PublicationError('RESEARCH_COMPLETION_LEDGER_ROOT_MISSING')
    with SafeRoot(ledger_root).directory():
        pass
    return owner, Path(ledger_root), (
        f'v4_research_stage_manifest_sha256={stage_pin}',
        f'v4_research_stage_config_sha256={digest(config_raw)}',
        f"v4_research_owner_release_id={binding['release_id']}",
        f"v4_research_owner_manifest_sha256={binding['manifest_sha256']}",
    )


def read_stage_hourly_attestation(*, stage_app: Path, data_root: Path, date: str,
                                  slot: str, mode: str, as_of: datetime) -> tuple[dict, tuple[str, ...]]:
    """Read immutable pre-rename provenance through a fixed Stage config pin.

    Historical roots supply bytes for verification only. No imports, execution,
    path discovery, data writes, signature waiver or different cutoff is used.
    """
    from infrastructure.owned_io import SafeRoot
    current, ledger, evidence = trusted_research_owner(stage_app, data_root)
    if (not re.fullmatch('[0-9]{8}', str(date)) or not re.fullmatch('[0-9]{4}', str(slot))
        or mode != 'LIVE'):
        raise PublicationError('HOURLY_PROVENANCE_REQUEST_INVALID')
    config = json.loads(SafeRoot(stage_app).read_bytes('stage_center_tick_config.json'))
    historical = config.get('research_historical_owner_bindings', [])
    if not isinstance(historical, list) or len(historical) > 1:
        raise PublicationError('HOURLY_PROVENANCE_ALLOWLIST_INVALID')
    record = json.loads(SafeRoot(data_root).read_bytes(f'research/hourly/publication/live/{date}/{slot}.json'))
    materializer_sha = record.get('materializer_sha256') if isinstance(record, dict) else None
    selected = current
    if materializer_sha != digest(SafeRoot(current).read_bytes('ops/run_hourly_research.py')):
        selected = None
        for binding in historical:
            if not isinstance(binding, dict) or set(binding) != {'app_root', 'release_id', 'manifest_sha256'}:
                raise PublicationError('HOURLY_PROVENANCE_ALLOWLIST_INVALID')
            previous = _absolute_release_app(binding['app_root'])
            _release_manifest(previous, binding['release_id'], binding['manifest_sha256'], _MAIN_RESEARCH_FILES)
            if materializer_sha == digest(SafeRoot(previous).read_bytes('ops/run_hourly_research.py')):
                selected = previous
                evidence = (*evidence, f"v4_research_historical_owner_release_id={binding['release_id']}",
                            f"v4_research_historical_owner_manifest_sha256={binding['manifest_sha256']}",
                            'v4_research_historical_owner_scope=READ_ONLY_IMMUTABLE_PROVENANCE_NO_EXECUTABLE_FALLBACK')
        if selected is None:
            raise PublicationError('HOURLY_PROVENANCE_OWNER_NOT_ALLOWLISTED')
    publication = read_hourly_attestation(data_root=data_root, owner_root=selected,
        date=date, slot=slot, mode=mode, as_of=as_of, scheduler_ledger_root=ledger)
    return publication, evidence
