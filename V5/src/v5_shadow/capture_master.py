"""Operator-bound Futu reference replay into an isolated, immutable V5 store.

No acquisition, membership publication, V4 discovery or scheduler registration.
Bindings are trusted application configuration, never fields supplied by a feed.
Prepared values are process-local capabilities, not importable JSON authorizations.
"""
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import types
import uuid
import weakref
from zoneinfo import ZoneInfo

from .composition import no_symlinks, atomic_bytes
from .contracts import aware, sha, trade_date
from .digests import canonical_bytes, sha256_json, MAX_JSON_BYTES
from .provider_evidence import normalize_security_references, encode_sdk_value, FIELDS

BASE=Path(__file__).resolve().parents[2]
SCHEMA='v5.futu_master_generation.v1'
CAPSULE_SHA256='f7d407a0063c4fea5e2966dd82485b78440a723cd72b165bf492d2a4d609f30c'
SAFETY=dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,
            natural_verified=False,formal_eligibility_verified=False)
_PREPARED=weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class MasterBinding:
    root: Path
    trade_date: str
    cutoff: str
    codes: tuple[str,...]
    membership_source_sha256: str
    producer_code_sha256: str
    raw_records_sha256: str
    snapshot_receipt_sha256: str
    protected_roots: tuple[Path,...]=()


@dataclass(frozen=True,eq=False)
class PreparedMaster:
    payload: bytes


def _binding(binding):
    if not isinstance(binding,MasterBinding):raise ValueError('BINDING_REQUIRED')
    trade_date(binding.trade_date);aware(binding.cutoff)
    for value in (binding.membership_source_sha256,binding.producer_code_sha256,
                  binding.raw_records_sha256,binding.snapshot_receipt_sha256):sha(value)
    if (not isinstance(binding.codes,tuple) or not 600<=len(binding.codes)<=10000
        or any(not isinstance(c,str) or not re.fullmatch(r'HK\.[0-9]{5}',c) for c in binding.codes)
        or len(set(binding.codes))!=len(binding.codes)):
        raise ValueError('MEMBERSHIP_SCOPE_INVALID')
    root=no_symlinks(binding.root)
    protected=[]
    for path in (*binding.protected_roots,BASE):
        path=no_symlinks(path)
        if root.is_relative_to(path) or path.is_relative_to(root):raise ValueError('SOURCE_OUTPUT_OVERLAP')
        protected.append(str(path))
    return dict(root=str(root),trade_date=binding.trade_date,cutoff=binding.cutoff,codes=list(binding.codes),
                membership_source_sha256=binding.membership_source_sha256,
                producer_code_sha256=binding.producer_code_sha256,raw_records_sha256=binding.raw_records_sha256,
                snapshot_receipt_sha256=binding.snapshot_receipt_sha256,protected_roots=protected)


def _implementation_identity():
    names=('capture_master.py','provider_evidence.py','digests.py','composition.py','contracts.py')
    return dict(contract='v5.futu_master_adapter.v1',legacy_capsule_sha256=CAPSULE_SHA256,
                source_file_sha256={name:hashlib.sha256(no_symlinks(Path(__file__).parent/name).read_bytes()).hexdigest() for name in names})


def prepare_futu_master(records, snapshot_receipt, binding):
    identity=_binding(binding)
    if (sha256_json(snapshot_receipt)!=binding.snapshot_receipt_sha256
        or sha256_json(encode_sdk_value(records))!=binding.raw_records_sha256
        or snapshot_receipt.get('schema_version')!='v5.futu_snapshot_receipt.v1'
        or snapshot_receipt.get('source_kind')!='FUTU_OPEND_MARKET_SNAPSHOT'
        or snapshot_receipt.get('producer_code_sha256')!=binding.producer_code_sha256):
        raise ValueError('SOURCE_NOT_ADMITTED')
    if not isinstance(records,list) or any(not isinstance(r,dict) for r in records):raise ValueError('RECORDS_INVALID')
    codes=[r.get('code') for r in records]
    if len(codes)!=len(set(codes)) or set(codes)!=set(binding.codes):raise ValueError('MEMBERSHIP_CODES_MISMATCH')
    lookup={r['code']:r for r in records};seen=set();completed=[]
    cutoff=aware(binding.cutoff);available=aware(snapshot_receipt['available_at'])
    batches=snapshot_receipt.get('batches')
    if not isinstance(batches,list) or not 1<=len(batches)<=10000:raise ValueError('BATCHES_INVALID')
    for batch in batches:
        requested=aware(batch['requested_at']);finished=aware(batch['completed_at'])
        if not requested<=finished<=available<=cutoff:raise ValueError('SNAPSHOT_TIME_INVALID')
        if finished.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')!=binding.trade_date:
            raise ValueError('SNAPSHOT_DATE_MISMATCH')
        batch_codes=batch.get('codes')
        if (not isinstance(batch_codes,list) or not batch_codes
            or any(not isinstance(c,str) for c in batch_codes)
            or len(batch_codes)!=len(set(batch_codes)) or seen.intersection(batch_codes)
            or not set(batch_codes)<=set(lookup)):
            raise ValueError('BATCH_CODES_INVALID')
        if sha256_json(encode_sdk_value([lookup[c] for c in batch_codes]))!=batch.get('raw_records_sha256'):
            raise ValueError('BATCH_RECORDS_MISMATCH')
        seen.update(batch_codes);completed.append((finished,batch['completed_at']))
    if seen!=set(codes):raise ValueError('BATCH_COVERAGE_INCOMPLETE')
    captured=max(completed,key=lambda pair:pair[0])[1]
    normalized=normalize_security_references(records,captured_at=captured)
    for row in normalized['rows']:
        if (row['issues'] or row['security_type']!='STOCK'
            or any(row['field_status'][f]!='KNOWN' for f in ('name','listing_date','lot_size','sec_status'))
            or row['listing_date'].replace('-','')>binding.trade_date):raise ValueError('MASTER_FIELDS_INVALID')
        for key in ('outstanding_shares','circular_market_val','lot_size'):
            value=row[key]
            if isinstance(value,int) and int(float(value))!=value:raise ValueError('MASTER_NUMERIC_PRECISION_LOSS')
    value=dict(schema_version=SCHEMA,origin='OPERATOR_BOUND_RECORDED_FUTU_REPLAY',
               binding=identity,implementation=_implementation_identity(),
               snapshot_receipt=snapshot_receipt,normalized=normalized,**SAFETY)
    prepared=PreparedMaster(canonical_bytes(value));_PREPARED[prepared]=prepared.payload
    return prepared


def _read_json(path):
    path=no_symlinks(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size>MAX_JSON_BYTES:raise ValueError('ARTIFACT_FILE_INVALID')
        with os.fdopen(fd,'rb',closefd=False) as handle:data=handle.read(MAX_JSON_BYTES+1)
        if len(data)>MAX_JSON_BYTES:raise ValueError('ARTIFACT_TOO_LARGE')
        return json.loads(data)
    finally:os.close(fd)


@contextmanager
def _load_legacy():
    descriptor=_read_json(BASE/'contracts/security_master_source_manifest.json')
    if descriptor.get('schema_version')!='v5.security_master_capsule.v1' or sha256_json(descriptor)!=CAPSULE_SHA256:
        raise ValueError('CAPSULE_INVALID')
    root=no_symlinks(BASE/'vendor/security_master_baseline')
    sources={}
    for entry in descriptor['entries']:
        relative=entry['capsule_path'];path=no_symlinks(root/relative)
        if not path.is_relative_to(root) or path.suffix!='.py':raise ValueError('CAPSULE_PATH_INVALID')
        data=path.read_bytes()
        if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise ValueError('CAPSULE_BYTES_MISMATCH')
        sources[path.stem]=data
    order=('constants','hashing','paths','allowlist','collectors','store','__init__','hk_security_master')
    if set(sources)!=set(order):raise ValueError('CAPSULE_CLOSURE_INVALID')
    prefix='_v5_master_'+uuid.uuid4().hex
    package=types.ModuleType(prefix);package.__path__=[];package.__package__=prefix
    sys.modules[prefix]=package
    try:
        for name in order:
            fullname=prefix if name=='__init__' else prefix+'.'+name
            module=package if name=='__init__' else types.ModuleType(fullname)
            module.__package__=prefix;module.__file__=str(root/'shared_data'/f'{name}.py')
            sys.modules[fullname]=module
            exec(compile(sources[name],module.__file__,'exec'),module.__dict__)
        yield sys.modules[prefix+'.hk_security_master'],sha256_json(descriptor)
    finally:
        for name in list(sys.modules):
            if name==prefix or name.startswith(prefix+'.'):sys.modules.pop(name,None)


def _validate_evidence(value,binding):
    if value.get('schema_version')!=SCHEMA or value.get('binding')!=_binding(binding):raise ValueError('MASTER_BINDING_MISMATCH')
    if any(value.get(k)!=v for k,v in SAFETY.items()):raise ValueError('MASTER_SAFETY_INVALID')
    if value.get('implementation')!=_implementation_identity():raise ValueError('IMPLEMENTATION_IDENTITY_MISMATCH')
    if sha256_json(value['snapshot_receipt'])!=binding.snapshot_receipt_sha256:raise ValueError('RECEIPT_BINDING_MISMATCH')
    normalized=value['normalized']
    if sha256_json({k:v for k,v in normalized.items() if k!='sha256'})!=normalized['sha256']:
        raise ValueError('NORMALIZED_SEAL_INVALID')
    if (sha256_json(normalized['raw']['records'])!=binding.raw_records_sha256
        or sha256_json(normalized['raw'])!=normalized['raw_sha256']):raise ValueError('RAW_BINDING_MISMATCH')


def _verify_legacy_rows(legacy,generation,evidence,binding):
    rows,manifest=legacy.load_verified_hk_security_master(generation,binding.trade_date)
    normalized=evidence['normalized'];captured=normalized['captured_at']
    if (set(rows)!=set(binding.codes) or manifest.get('trade_date')!=binding.trade_date
        or manifest.get('captured_at')!=captured
        or manifest.get('universe_codes_sha256')!=sha256_json(sorted(binding.codes))):
        raise ValueError('LEGACY_IDENTITY_MISMATCH')
    for source in normalized['rows']:
        expected={key:('' if source[key] is None else str(source[key])) for key in FIELDS}
        for key in ('outstanding_shares','circular_market_val','lot_size'):
            expected[key]='' if source[key] is None else str(float(source[key]))
        expected.update(captured_at=captured,source='FUTU_OPEND_MARKET_SNAPSHOT')
        if rows.get(source['code'])!=expected:raise ValueError('LEGACY_FIELD_MISMATCH')
    legacy_rows=legacy._normalize_rows([{key:r[key] for key in FIELDS} for r in normalized['rows']],captured)
    universe_sha=sha256_json(sorted(binding.codes))
    run_id=sha256_json(dict(trade_date=binding.trade_date,universe_codes_sha256=universe_sha,rows=legacy_rows))[:24]
    relative=f'runs/{binding.trade_date}/{run_id}'
    safety={key:False for key in ('production_allowed','buy_gate_updated','orders_sent')}
    expected_manifest=dict(schema_version=legacy.MANIFEST_SCHEMA_VERSION,trade_date=binding.trade_date,
        run_id=run_id,captured_at=captured,row_count=len(rows),universe_codes_sha256=universe_sha,
        artifact_relative=relative+'/artifact.csv',artifact_sha256=manifest['artifact_sha256'],
        stage_valuation_policy='OUTSTANDING_SHARES_X_CUTOFF_LAST_PRICE',
        valuation_eligibility_field='circular_market_val',later_snapshot_price_allowed=False,**safety)
    asset=generation/'assets/hk_security_master'
    expected_receipt=dict(schema_version=legacy.RECEIPT_SCHEMA_VERSION,status='READY',trade_date=binding.trade_date,
        run_id=run_id,artifact_sha256=manifest['artifact_sha256'],manifest_sha256=sha256_json(expected_manifest),**safety)
    expected_latest=dict(schema_version=legacy.LATEST_SCHEMA_VERSION,entries={binding.trade_date:dict(
        run_id=run_id,manifest_relative=relative+'/manifest.json',receipt_relative=relative+'/receipt.json')})
    if (manifest!=expected_manifest or _read_json(asset/relative/'receipt.json')!=expected_receipt
        or _read_json(asset/'latest.json')!=expected_latest):raise ValueError('LEGACY_METADATA_MISMATCH')
    expected_files={'evidence.json','assets/hk_security_master/latest.json',
                    *('assets/hk_security_master/'+relative+'/'+name for name in ('artifact.csv','manifest.json','receipt.json'))}
    if set(_files(generation))!=expected_files:raise ValueError('LEGACY_FILE_SET_MISMATCH')
    return rows


def _files(root):
    result={}
    for path in sorted(root.rglob('*')):
        path=no_symlinks(path)
        if path.is_dir():continue
        if not path.is_file() or path.stat().st_size>MAX_JSON_BYTES:raise ValueError('GENERATION_FILE_INVALID')
        if path.name=='COMMIT.json' and path.parent==root:continue
        result[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _root(binding):
    root=Path(_binding(binding)['root']);marker=no_symlinks(root/'.v5-master-root')
    if not marker.is_file() or marker.read_text()!='v5.master-root.v1\n':raise ValueError('MASTER_ROOT_NOT_INITIALIZED')
    return root


def _fsync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def _read(reference,binding,legacy,source_sha):
    root=_root(binding)
    if not isinstance(reference,dict) or set(reference)!={'generation_id','receipt_sha256'}:
        raise ValueError('REFERENCE_INVALID')
    generation_id=sha(reference['generation_id']);sha(reference['receipt_sha256'])
    generation=no_symlinks(root/'generations'/generation_id)
    receipt=_read_json(generation/'COMMIT.json')
    expected_keys={'schema_version','generation_id','source_capsule_sha256','files',*SAFETY}
    if (set(receipt)!=expected_keys or receipt.get('schema_version')!=SCHEMA
        or any(receipt.get(k)!=v for k,v in SAFETY.items())):
        raise ValueError('COMMIT_CONTRACT_INVALID')
    if (sha256_json(receipt)!=reference['receipt_sha256'] or receipt['generation_id']!=generation_id
        or receipt['source_capsule_sha256']!=source_sha or receipt['files']!=_files(generation)):
        raise ValueError('GENERATION_IDENTITY_MISMATCH')
    evidence=_read_json(generation/'evidence.json');_validate_evidence(evidence,binding)
    if sha256_json(evidence)!=generation_id:raise ValueError('GENERATION_CONTENT_MISMATCH')
    rows=_verify_legacy_rows(legacy,generation,evidence,binding)
    return dict(rows=rows,field_states={r['code']:r['field_status'] for r in evidence['normalized']['rows']},
                origin=evidence['origin'],reference=reference,**SAFETY)


def read_futu_master(reference,binding):
    with _load_legacy() as (legacy,source_sha):return _read(reference,binding,legacy,source_sha)


def publish_futu_master(prepared,binding):
    if not isinstance(prepared,PreparedMaster) or _PREPARED.get(prepared)!=prepared.payload:
        raise ValueError('PREPARED_NOT_ADMITTED')
    evidence=json.loads(prepared.payload);_validate_evidence(evidence,binding)
    root=_root(binding);generation_id=hashlib.sha256(prepared.payload).hexdigest()
    lock=no_symlinks(root/'.master.lock');fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('MASTER_LOCK_INVALID')
        fcntl.flock(fd,fcntl.LOCK_EX)
        parents=no_symlinks(root/'generations');parents.mkdir(exist_ok=True);_fsync_dir(root)
        final=no_symlinks(parents/generation_id)
        with _load_legacy() as (legacy,source_sha):
            refs=no_symlinks(root/'references');refs.mkdir(exist_ok=True);_fsync_dir(root)
            refpath=no_symlinks(refs/(generation_id+'.json'))
            if final.exists():
                if not refpath.is_file():raise ValueError('GENERATION_COMMIT_INCOMPLETE')
                reference=_read_json(refpath)
                if reference.get('generation_id')!=generation_id:raise ValueError('REFERENCE_IDENTITY_MISMATCH')
                _read(reference,binding,legacy,source_sha)
                return reference
            if refpath.exists():raise ValueError('REFERENCE_WITHOUT_GENERATION')
            pending=no_symlinks(root/('.pending-'+uuid.uuid4().hex));pending.mkdir(mode=0o700);_fsync_dir(root)
            atomic_bytes(pending/'evidence.json',prepared.payload)
            normalized=evidence['normalized']
            legacy.publish_hk_security_master(pending,trade_date=binding.trade_date,
                rows=[{key:row[key] for key in FIELDS} for row in normalized['rows']],
                universe_codes_sha256=sha256_json(sorted(binding.codes)),captured_at=normalized['captured_at'])
            _verify_legacy_rows(legacy,pending,evidence,binding)
            receipt=dict(schema_version=SCHEMA,generation_id=generation_id,
                         source_capsule_sha256=source_sha,files=_files(pending),**SAFETY)
            atomic_bytes(pending/'COMMIT.json',canonical_bytes(receipt))
            for directory in sorted((p for p in pending.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):_fsync_dir(directory)
            _fsync_dir(pending)
            os.rename(pending,final);_fsync_dir(parents);_fsync_dir(root)
            reference=dict(generation_id=generation_id,receipt_sha256=sha256_json(receipt))
            _read(reference,binding,legacy,source_sha)
            atomic_bytes(refpath,canonical_bytes(reference))
            return reference
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
