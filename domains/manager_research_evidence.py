"""Closed, read-only admission adapters for manager research evidence.

Only the existing HK membership authority and the existing shared Futu bridge
are admitted. Bare rule names, paths, row booleans and provider ratios are not
evidence. There is deliberately no invented historical/volume authority here.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, time
import json
from pathlib import Path
from typing import Any, Mapping, Sequence, Callable
from zoneinfo import ZoneInfo
from infrastructure.manager_input_attestation import atomic_create, aware, digest, encoded, load, resolve, PublicationError

HK=ZoneInfo('Asia/Hong_Kong')
MARKET='HK_CONNECT'
SLOT='1530'
FLAGS={'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
SNAPSHOT_SCHEMA='v4.manager_close_snapshot.v2'
RECEIPT_SCHEMA='v4.manager_close_snapshot_receipt.v1'
BRIDGE_REL='upstreams/v3_shared_data/shared_data/hk_auction_0920.py'
BRIDGE_OWNER='shared_data.hk_auction_0920.fetch_futu_snapshot'
_SEAL=object()

class EvidenceError(ValueError):
    """A bounded code plus safe, structured provenance; never a raw traceback."""
    def __init__(self, code: str, *, layer: str = 'SNAPSHOT', kind: str = 'INVALID',
                 field: str = 'evidence', artifact_ref: str | None = None,
                 owner_sha256: str | None = None,
                 source_owner: str | None = None,
                 producer_owner: str | None = None):
        import re
        if not isinstance(code, str) or not re.fullmatch(r'[A-Z0-9_:.-]{1,160}', code):
            code = 'EVIDENCE_VALIDATION_FAILED'
        super().__init__(code)
        self.diagnostic = {
            'schema_version': 'v4.manager_close_failure.v1', 'layer': layer,
            'kind': kind, 'code': code, 'field': field, 'artifact_ref': artifact_ref,
            'source_owner': source_owner or (
                'stage_center.hk_universe_preflight.ensure_hk_connect_universe'
                if layer.startswith('UNIVERSE') else None
            ),
            'source_code_ref': 'stage_center/hk_universe_preflight.py'
                if layer.startswith('UNIVERSE') else None,
            'source_code_sha256': owner_sha256,
        }
        if producer_owner is not None:
            self.diagnostic['producer_owner'] = producer_owner


def load_universe_owner(owner_root: Path | None = None, expected_sha256: str | None = None,
                       *, require_v2: bool = False):
    """Read the ORIGINAL owner at an explicit CAS-pinned root; no producer here.

    Unbound callers retain their release-local owner. Configured consumers do
    not copy a producer, silently switch to 'latest', or relax its contract.
    """
    import hashlib
    import importlib.util
    import re
    if owner_root is None and expected_sha256 is None:
        # Load this release's single original source file without importing the
        # unrelated Stage package __init__ (which has a wider runtime closure).
        owner_root = Path(__file__).resolve().parents[1]
        local_path = resolve(owner_root, 'stage_center/hk_universe_preflight.py')
        if not local_path.is_file():
            raise EvidenceError('HK_UNIVERSE_OWNER_SOURCE_MISSING', layer='UNIVERSE_OWNER',
                                kind='MISSING', field='source_code_ref')
        expected_sha256 = hashlib.sha256(local_path.read_bytes()).hexdigest()
    if (owner_root is None or not Path(owner_root).is_absolute()
        or not isinstance(expected_sha256, str)
        or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256)):
        raise EvidenceError('HK_UNIVERSE_OWNER_BINDING_REQUIRED', layer='UNIVERSE_OWNER',
                            kind='MISSING', field='owner_binding')
    try:
        path = resolve(Path(owner_root), 'stage_center/hk_universe_preflight.py')
        if not path.is_file():
            raise EvidenceError('HK_UNIVERSE_OWNER_SOURCE_MISSING', layer='UNIVERSE_OWNER',
                                kind='MISSING', field='source_code_ref')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
            raise EvidenceError('HK_UNIVERSE_OWNER_SHA_MISMATCH', layer='UNIVERSE_OWNER',
                                kind='CONFLICT', field='source_code_sha256')
        spec = importlib.util.spec_from_file_location('_manager_bound_hk_owner_' + expected_sha256, path)
        if spec is None or spec.loader is None:
            raise ValueError('invalid module spec')
        owner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(owner)
        if (Path(owner.__file__).resolve() != path.resolve()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256):
            raise EvidenceError('HK_UNIVERSE_OWNER_SHA_MISMATCH', layer='UNIVERSE_OWNER',
                                kind='CONFLICT', field='source_code_sha256')
        for name in ('ensure_hk_connect_universe', '_read_existing_manifest',
                     '_authority_payloads', '_authority_relative_paths', '_resolve_under', 'authority_run_id'):
            if not callable(getattr(owner, name, None)):
                raise ValueError('owner interface missing')
        if require_v2:
            for name in ('validate_captured_hk_connect_membership_v2',
                         'build_captured_hk_connect_authority_v2', '_canonical_json_line',
                         '_sha256_bytes'):
                if not callable(getattr(owner, name, None)):
                    raise ValueError('v2 owner interface missing')
        if type(getattr(owner, 'HK_UNIVERSE_MIN_COUNT', None)) is not int:
            raise ValueError('owner minimum contract missing')
        return owner
    except EvidenceError:
        raise
    except (OSError, ValueError, ImportError, AttributeError) as exc:
        raise EvidenceError('HK_UNIVERSE_OWNER_LOAD_FAILED', layer='UNIVERSE_OWNER',
                            kind='INVALID', field='owner_binding') from exc

@dataclass(frozen=True)
class VerifiedUniverse:
    codes: tuple[str,...]
    source: Mapping[str,Any]
    _seal: object=field(default=None,repr=False,compare=False)

@dataclass(frozen=True)
class VerifiedSnapshot:
    rows: tuple[Mapping[str,Any],...]
    errors: tuple[str,...]
    source: Mapping[str,Any]
    universe_sha256: str
    rows_sha256: str
    universe_source: Mapping[str,Any]
    _seal: object=field(default=None,repr=False,compare=False)


def admitted(universe: Any, snapshot: Any, rows: Sequence[Mapping[str,Any]]) -> bool:
    return (isinstance(universe,VerifiedUniverse) and universe._seal is _SEAL
            and isinstance(snapshot,VerifiedSnapshot) and snapshot._seal is _SEAL
            and snapshot.universe_sha256==universe.source['sha256']
            and snapshot.rows_sha256==digest(encoded(list(rows))))


def _read_captured_hk_connect_evidence_v2(root: Path, trade_date: str, *, owner: Any,
        owner_sha256: str, as_of: datetime | None,
        clock: Callable[[],datetime]) -> VerifiedUniverse:
    """Read the same-root captured-input authority and persisted availability."""
    import hashlib
    import re
    ref=f'universes/{trade_date}/HK_CONNECT_FULL_MARKET.json'
    def error(code, *, layer='UNIVERSE_ARTIFACT', kind='INVALID', field='artifact', reference=ref):
        return EvidenceError(code, layer=layer, kind=kind, field=field,
                             artifact_ref=reference, owner_sha256=owner_sha256,
                             source_owner=(
                                 'stage_center.hk_universe_preflight.'
                                 'validate_captured_hk_connect_membership_v2'
                             ),
                             producer_owner='v35_dispatcher.research_panel_daily_hk')
    def load_canonical(relative, *, layer, missing_code, invalid_code):
        try:
            path=owner._resolve_under(root, relative)
            if not path.is_file():
                raise error(missing_code, layer=layer, kind='MISSING', field='artifact_ref', reference=relative)
            raw=path.read_bytes()
            value=json.loads(raw.decode('utf-8'))
            if not isinstance(value,Mapping) or raw!=owner._canonical_json_line(dict(value)):
                raise error(invalid_code, layer=layer, field='canonical_bytes', reference=relative)
            return dict(value),raw
        except EvidenceError:
            raise
        except (OSError,UnicodeError,json.JSONDecodeError,TypeError,ValueError) as exc:
            raise error(invalid_code, layer=layer, field='artifact_ref', reference=relative) from exc

    artifact,artifact_bytes=load_canonical(
        ref,layer='UNIVERSE_ARTIFACT',missing_code='HK_UNIVERSE_V2_ARTIFACT_MISSING',
        invalid_code='HK_UNIVERSE_V2_ARTIFACT_INVALID')
    if (artifact.get('schema_version')!=getattr(owner,'HK_CONNECT_ARTIFACT_SCHEMA_V2',None)
        or any(artifact.get(key)!=trade_date for key in ('target_date','effective_date','trade_date','source_date'))
        or artifact.get('market')!='HK_CONNECT' or artifact.get('scope')!='FULL_MARKET'
        or artifact.get('source_role')!=getattr(owner,'HK_UNIVERSE_SOURCE_ROLE',None)
        or any(artifact.get(flag) is not False for flag in ('production_allowed','buy_gate_updated','orders_sent'))):
        raise error('HK_UNIVERSE_V2_ARTIFACT_SCOPE_INVALID',field='schema_date_market_safety')
    codes=artifact.get('codes')
    if (not isinstance(codes,list) or not codes or codes!=sorted(set(codes))
        or any(not isinstance(code,str) or not re.fullmatch(r'HK\.\d{5}',code) for code in codes)
        or type(artifact.get('code_count')) is not int or artifact['code_count']!=len(codes)
        or artifact.get('codes_sha256')!=owner._sha256(codes)):
        raise error('HK_UNIVERSE_V2_ARTIFACT_CODES_INVALID',field='codes')
    artifact_sha=hashlib.sha256(artifact_bytes).hexdigest()
    try:
        run=owner.authority_run_id(trade_date,artifact_sha)
        paths=owner._authority_relative_paths(trade_date,run)
    except (OSError,TypeError,ValueError) as exc:
        raise error('HK_UNIVERSE_V2_AUTHORITY_ID_INVALID',layer='UNIVERSE_AUTHORITY',field='run_id') from exc
    base=f'universes/{trade_date}/HK_CONNECT_FULL_MARKET.authority/{run}'
    capture_ref=f'{base}/capture.json'; publication_ref=f'{base}/publication.json'
    manifest,manifest_bytes=load_canonical(
        paths['manifest_relative'],layer='UNIVERSE_AUTHORITY',
        missing_code='HK_UNIVERSE_V2_MANIFEST_MISSING',invalid_code='HK_UNIVERSE_V2_MANIFEST_INVALID')
    receipt,receipt_bytes=load_canonical(
        paths['receipt_relative'],layer='UNIVERSE_AUTHORITY',
        missing_code='HK_UNIVERSE_V2_RECEIPT_MISSING',invalid_code='HK_UNIVERSE_V2_RECEIPT_INVALID')
    current,current_bytes=load_canonical(
        paths['current_relative'],layer='UNIVERSE_AUTHORITY',
        missing_code='HK_UNIVERSE_V2_CURRENT_MISSING',invalid_code='HK_UNIVERSE_V2_CURRENT_INVALID')
    capture,capture_bytes=load_canonical(
        capture_ref,layer='UNIVERSE_CAPTURE',
        missing_code='HK_UNIVERSE_V2_CAPTURE_MISSING',invalid_code='HK_UNIVERSE_V2_CAPTURE_INVALID')
    publication,publication_bytes=load_canonical(
        publication_ref,layer='UNIVERSE_PUBLICATION',
        missing_code='HK_UNIVERSE_V2_PUBLICATION_MISSING',invalid_code='HK_UNIVERSE_V2_PUBLICATION_INVALID')

    contract_owner={'code_ref':'stage_center/hk_universe_preflight.py',
                    'code_sha256':owner_sha256,
                    'role':'PURE_CAPTURED_HK_CONNECT_CONTRACT_V2'}
    producer=artifact.get('producer_owner')
    if not isinstance(producer,Mapping) or artifact.get('contract_owner')!=contract_owner:
        raise error('HK_UNIVERSE_V2_OWNER_BINDING_INVALID',layer='UNIVERSE_OWNER',field='contract_owner')
    try:
        validated=owner.validate_captured_hk_connect_membership_v2(capture,trade_date=trade_date)
        built=owner.build_captured_hk_connect_authority_v2(
            capture,trade_date=trade_date,producer_owner=producer,contract_owner=contract_owner)
    except (OSError,TypeError,ValueError,KeyError,AttributeError) as exc:
        raise error('HK_UNIVERSE_V2_CAPTURE_MEMBERSHIP_INVALID',layer='UNIVERSE_CAPTURE',field='capture') from exc
    if (capture_bytes!=built['capture_bytes'] or artifact_bytes!=built['artifact_bytes']
        or manifest_bytes!=built['manifest_bytes'] or receipt_bytes!=built['receipt_bytes']
        or current_bytes!=built['current_bytes'] or built['run_id']!=run
        or built['paths']!=paths or built['capture_relative']!=capture_ref
        or built['publication_relative']!=publication_ref):
        raise error('HK_UNIVERSE_V2_CHAIN_IDENTITY_MISMATCH',layer='UNIVERSE_AUTHORITY',
                    kind='CONFLICT',field='authority_chain')
    if (manifest.get('schema_version')!=getattr(owner,'HK_CONNECT_AUTHORITY_MANIFEST_SCHEMA_V2',None)
        or receipt.get('schema_version')!=getattr(owner,'HK_CONNECT_AUTHORITY_RECEIPT_SCHEMA_V2',None)
        or current.get('schema_version')!=getattr(owner,'HK_CONNECT_AUTHORITY_CURRENT_SCHEMA_V2',None)):
        raise error('HK_UNIVERSE_V2_CHAIN_SCHEMA_INVALID',layer='UNIVERSE_AUTHORITY',field='schema_version')
    expected_publication={
        'schema_version':getattr(owner,'HK_CONNECT_PUBLICATION_SCHEMA_V2',None),
        'status':'READY','target_date':trade_date,'effective_date':trade_date,
        'trade_date':trade_date,'source_date':trade_date,'market':'HK_CONNECT',
        'scope':'FULL_MARKET','run_id':run,'publication_relative':publication_ref,
        'acquired_at':validated['acquired_at'],'capture_run_id':validated['capture_run_id'],
        'capture_sha256':validated['capture_sha256'],
        'artifact_relative':paths['artifact_relative'],'artifact_sha256':built['artifact_sha256'],
        'manifest_relative':paths['manifest_relative'],'receipt_relative':paths['receipt_relative'],
        'current_relative':paths['current_relative'],'current_sha256':built['current_sha256'],
        'workload_id':producer.get('workload_id'),'producer_owner':dict(producer),
        'contract_owner':contract_owner,
        'forward_source_set':producer.get('forward_source_set'),
        'forward_source_set_sha256':producer.get('forward_source_set_sha256'),
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
    }
    publication_material=dict(publication)
    publication_digest=publication_material.pop('publication_sha256',None)
    if (not isinstance(publication_digest,str) or not re.fullmatch(r'[0-9a-f]{64}',publication_digest)
        or owner._sha256(publication_material)!=publication_digest):
        raise error('HK_UNIVERSE_V2_PUBLICATION_SHA_INVALID',layer='UNIVERSE_PUBLICATION',field='publication_sha256')
    if any(publication.get(key)!=value for key,value in expected_publication.items()):
        raise error('HK_UNIVERSE_V2_PUBLICATION_IDENTITY_INVALID',layer='UNIVERSE_PUBLICATION',field='identity')
    try:
        acquired=aware(validated['acquired_at']); available=aware(publication.get('available_at'))
    except PublicationError as exc:
        raise error('HK_UNIVERSE_V2_PUBLICATION_TIME_INVALID',layer='UNIVERSE_PUBLICATION',field='available_at') from exc
    if (acquired.astimezone(HK).strftime('%Y%m%d')!=trade_date
        or available.astimezone(HK).strftime('%Y%m%d')!=trade_date or available<acquired):
        raise error('HK_UNIVERSE_V2_AFTER_AS_OF_OR_WRONG_DATE',kind='PIT_UNSAFE',field='acquired_at/available_at')
    witnessed=clock()
    if (witnessed.tzinfo is None or available>witnessed
        or (as_of is not None and (as_of.tzinfo is None or witnessed>as_of
            or acquired>as_of or available>as_of))):
        raise error('HK_UNIVERSE_V2_AVAILABILITY_UNPROVEN_BY_AS_OF',kind='PIT_UNSAFE',field='available_at')
    src={
        'owner':producer.get('workload_id'),'role':'HK_CONNECT_FULL_MARKET_AUTHORITY',
        'source_role':artifact['source_role'],'market':'HK_CONNECT','lane':None,
        'source_date':trade_date,'artifact_ref':ref,'manifest_ref':paths['manifest_relative'],
        'receipt_ref':paths['receipt_relative'],'current_ref':paths['current_relative'],
        'capture_ref':capture_ref,'publication_ref':publication_ref,
        'sha256':artifact_sha,'run_id':run,'acquired_at':acquired.isoformat(),
        'observed_at':acquired.isoformat(),'available_at':available.isoformat(),
        'read_at':witnessed.isoformat(),'capture_run_id':validated['capture_run_id'],
        'capture_sha256':validated['capture_sha256'],'source_sha256':artifact['source_sha256'],
        'producer_owner':dict(producer),'contract_owner':contract_owner,
        'reason':'同根双板采集、authority 链与持久化 availability receipt 已逐字节校验',
    }
    return VerifiedUniverse(tuple(codes),src,_SEAL)


def read_universe_evidence(root: Path, trade_date: str, *, as_of: datetime | None = None,
                           clock: Callable[[],datetime] = lambda: datetime.now(HK),
                           authority_owner_root: Path | None = None,
                           authority_owner_sha256: str | None = None,
                           require_v2: bool = False) -> VerifiedUniverse:
    import re
    if not isinstance(trade_date, str) or not re.fullmatch(r'\d{8}', trade_date):
        raise EvidenceError('HK_UNIVERSE_DATE_INVALID', layer='UNIVERSE_ARTIFACT', field='trade_date')
    try:
        datetime.strptime(trade_date, '%Y%m%d')
    except ValueError as exc:
        raise EvidenceError('HK_UNIVERSE_DATE_INVALID', layer='UNIVERSE_ARTIFACT', field='trade_date') from exc
    if require_v2 and (authority_owner_root is None or authority_owner_sha256 is None):
        raise EvidenceError('HK_UNIVERSE_V2_OWNER_BINDING_REQUIRED', layer='UNIVERSE_OWNER',
                            kind='MISSING', field='owner_binding')
    owner = load_universe_owner(authority_owner_root, authority_owner_sha256,
                                require_v2=require_v2)
    owner_sha = digest(Path(owner.__file__).read_bytes())
    if require_v2:
        return _read_captured_hk_connect_evidence_v2(
            root, trade_date, owner=owner, owner_sha256=owner_sha,
            as_of=as_of, clock=clock,
        )
    ref = f'universes/{trade_date}/HK_CONNECT_FULL_MARKET.json'
    def error(code, *, layer='UNIVERSE_ARTIFACT', kind='INVALID', field='artifact', reference=ref):
        return EvidenceError(code, layer=layer, kind=kind, field=field,
                             artifact_ref=reference, owner_sha256=owner_sha)
    try:
        artifact = owner._resolve_under(root, ref)
        # Use the PINNED native owner's count/plate/byte rules, not a consumer's 651 constant.
        payload = owner._read_existing_manifest(artifact, trade_date,
                                                min_universe_count=owner.HK_UNIVERSE_MIN_COUNT)
    except (OSError, ValueError) as exc:
        text = str(exc)
        fields = [('trade_date', 'trade_date'), ('count/source_date', 'code_count'),
                  ('codes SHA', 'codes_sha256'), ('plate', 'plate_codes'),
                  ('source SHA', 'source_sha256'), ('source_role', 'source_role'),
                  ('schema', 'schema_version'), ('safety', 'safety_flags'),
                  ('codes', 'codes'), ('symlink', 'artifact_ref')]
        field = next((field for token, field in fields if token in text), 'artifact')
        raise error('HK_UNIVERSE_ARTIFACT_INVALID', field=field) from exc
    if payload is None:
        raise error('HK_CONNECT_EXACT_UNIVERSE_MISSING', kind='MISSING')
    try:
        observed = aware(payload.get('captured_at'))
    except PublicationError as exc:
        raise error('HK_UNIVERSE_CAPTURE_TIME_INVALID', field='captured_at') from exc
    if observed.strftime('%Y%m%d') != trade_date:
        raise error('HK_UNIVERSE_AFTER_AS_OF_OR_WRONG_DATE', kind='PIT_UNSAFE', field='captured_at')
    artifact_sha = digest(artifact.read_bytes())
    run = owner.authority_run_id(trade_date, artifact_sha)
    paths = owner._authority_relative_paths(trade_date, run)
    files = {}
    for key in ('current_relative', 'manifest_relative', 'receipt_relative'):
        try:
            files[key] = owner._resolve_under(root, paths[key])
            if not files[key].is_file():
                raise error('HK_UNIVERSE_AUTHORITY_CHAIN_MISSING', layer='UNIVERSE_AUTHORITY',
                            kind='MISSING', field=key, reference=paths[key])
        except EvidenceError:
            raise
        except (OSError, ValueError) as exc:
            raise error('HK_UNIVERSE_AUTHORITY_PATH_INVALID', layer='UNIVERSE_AUTHORITY',
                        field=key, reference=paths[key]) from exc
    try:
        current = load(files['current_relative'])
    except PublicationError as exc:
        raise error('HK_UNIVERSE_CURRENT_INVALID', layer='UNIVERSE_AUTHORITY',
                    field='current_relative', reference=paths['current_relative']) from exc
    materialization = current.get('source_materialization')
    # MANUAL_RECOVERY and unknown enums are NOT natural contemporaneous admission.
    if materialization not in {'FRESH_FUTU_ARTIFACT', 'VERIFIED_EXISTING_ARTIFACT_CHAIN_COMPLETION'}:
        raise error('HK_UNIVERSE_MATERIALIZATION_INVALID', layer='UNIVERSE_AUTHORITY',
                    field='source_materialization', reference=paths['current_relative'])
    try:
        chain = owner._authority_payloads(root, trade_date, payload,
            source_materialization=materialization,
            origin_claim='NOT_ASSERTED_REQUIRES_PARENT_SCHEDULER_RECEIPT')
        for key, kind in [('manifest_relative', 'manifest'), ('receipt_relative', 'receipt'),
                          ('current_relative', 'current')]:
            if files[key].read_bytes() != chain[kind + '_bytes']:
                raise error('HK_UNIVERSE_AUTHORITY_CONTENT_OR_SHA_MISMATCH', layer='UNIVERSE_AUTHORITY',
                            kind='CONFLICT', field=key, reference=paths[key])
    except EvidenceError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise error('HK_UNIVERSE_AUTHORITY_INVALID', layer='UNIVERSE_AUTHORITY') from exc
    witnessed = clock()
    if (witnessed.tzinfo is None or observed > witnessed
        or (as_of is not None and (as_of.tzinfo is None or witnessed > as_of))):
        raise error('HK_UNIVERSE_AVAILABILITY_UNPROVEN_BY_AS_OF', kind='PIT_UNSAFE', field='available_at')
    src = {'owner': 'stage_center.hk_universe_preflight.ensure_hk_connect_universe',
           'role': 'HK_CONNECT_FULL_MARKET_AUTHORITY', 'market': MARKET, 'lane': None,
           'source_date': trade_date, 'artifact_ref': ref, 'manifest_ref': paths['manifest_relative'],
           'receipt_ref': paths['receipt_relative'], 'sha256': artifact_sha, 'run_id': run,
           'observed_at': observed.isoformat(), 'available_at': witnessed.isoformat(),
           'reason': '既有当日港股通资格 authority；内容、manifest、receipt、current 全链校验'}
    return VerifiedUniverse(tuple(payload['codes']), src, _SEAL)


def _snapshot_ref(trade_date: str) -> str:
    try:
        if datetime.strptime(trade_date,'%Y%m%d').strftime('%Y%m%d')!=trade_date: raise ValueError
    except (ValueError,TypeError) as exc: raise EvidenceError('SNAPSHOT_DATE_INVALID') from exc
    return f'workbench_research/{trade_date}/inputs/1530_futu_snapshot.json'


def _check_times(trade_date: str, started: datetime, available: datetime) -> None:
    if started.tzinfo is None or available.tzinfo is None: raise EvidenceError('SNAPSHOT_TIME_NAIVE')
    started=started.astimezone(HK); available=available.astimezone(HK)
    if (started.strftime('%Y%m%d')!=trade_date or available.strftime('%Y%m%d')!=trade_date
        or not time(15,30)<=started.time()<time(15,32)
        or not started<=available or available.time()>=time(15,32)):
        raise EvidenceError('EXACT_1530_CAPTURE_WINDOW_MISSING')


def persist_snapshot(root: Path, *, trade_date: str, rows: Sequence[Mapping[str,Any]],
                     errors: Sequence[str], started_at: datetime, available_at: datetime,
                     universe: VerifiedUniverse, app_root: Path) -> Mapping[str,Any]:
    """Persist the single existing bridge's return without relabelling units.

    Called only by the one materializer while holding its slot lock. Times are
    measured before/after the bridge call, never copied from quote update_time.
    """
    if universe._seal is not _SEAL: raise EvidenceError('UNIVERSE_NOT_ADMITTED')
    _check_times(trade_date,started_at,available_at)
    ref=_snapshot_ref(trade_date)
    src={'owner':BRIDGE_OWNER,'code_sha256':digest(resolve(app_root,BRIDGE_REL).read_bytes()),
         'code_ref':BRIDGE_REL}
    # Preserve the bridge's decoded return as a JSON string, including its
    # non-standard NaN constants, alongside a strict-JSON null-normalized view.
    # No missing numeric field is filled or promoted to a fact.
    bridge_return=json.dumps({'rows':list(rows),'errors':list(errors)},ensure_ascii=False,sort_keys=True,default=str,allow_nan=True)
    normalized=json.loads(bridge_return,parse_constant=lambda _value: None)
    value={'schema_version':SNAPSHOT_SCHEMA,'market':MARKET,'trade_date':trade_date,'slot':SLOT,
           'started_at':started_at.isoformat(),'available_at':available_at.isoformat(),
           'universe_sha256':universe.source['sha256'],'universe_run_id':universe.source['run_id'],
           'universe_source':dict(universe.source),
           'bridge':src,'normalization':'NONFINITE_TO_NULL_V1','bridge_return_json':bridge_return,
           'bridge_return_sha256':digest(bridge_return.encode()),
           'rows':normalized['rows'],'errors':[str(x)[:160] for x in normalized['errors']],**FLAGS}
    raw=encoded(value); sha=digest(raw)
    receipt={'schema_version':RECEIPT_SCHEMA,'market':MARKET,'trade_date':trade_date,'slot':SLOT,
             'artifact_ref':ref,'artifact_sha256':sha,'bridge':src,'row_count':len(rows),
             'universe_sha256':universe.source['sha256'],'available_at':available_at.isoformat(),
             'run_id':'mcs-'+sha[:24],**FLAGS}
    artifact=resolve(root,ref); sidecar=resolve(root,ref+'.receipt.json')
    if not atomic_create(artifact,raw) and artifact.read_bytes()!=raw:
        raise EvidenceError('SNAPSHOT_IMMUTABLE_CONFLICT')
    if not atomic_create(sidecar,encoded(receipt)) and sidecar.read_bytes()!=encoded(receipt):
        raise EvidenceError('SNAPSHOT_RECEIPT_CONFLICT')
    return receipt


def read_snapshot_evidence(root: Path, trade_date: str, *, as_of: datetime,
                           universe: VerifiedUniverse, app_root: Path) -> VerifiedSnapshot:
    ref=_snapshot_ref(trade_date)
    path=resolve(root,ref); receipt=load(resolve(root,ref+'.receipt.json')); value=load(path)
    if universe._seal is not _SEAL: raise EvidenceError('UNIVERSE_NOT_ADMITTED')
    started=aware(value.get('started_at')); available=aware(value.get('available_at'))
    _check_times(trade_date,started,available)
    if available>as_of:
        raise EvidenceError('SNAPSHOT_AFTER_AS_OF')
    prior_universe=value.get('universe_source')
    if not isinstance(prior_universe,dict): raise EvidenceError('SNAPSHOT_UNIVERSE_WITNESS_MISSING')
    if {k:v for k,v in prior_universe.items() if k!='available_at'}!={k:v for k,v in universe.source.items() if k!='available_at'}:
        raise EvidenceError('SNAPSHOT_UNIVERSE_IDENTITY_MISMATCH')
    if not aware(prior_universe['observed_at']) <= aware(prior_universe['available_at']) <= started:
        raise EvidenceError('SNAPSHOT_UNIVERSE_WITNESS_TIME_INVALID')
    bridge={'owner':BRIDGE_OWNER,'code_ref':BRIDGE_REL,
            'code_sha256':digest(resolve(app_root,BRIDGE_REL).read_bytes())}
    identity={'schema_version':SNAPSHOT_SCHEMA,'market':MARKET,'trade_date':trade_date,'slot':SLOT,
              'universe_sha256':universe.source['sha256'],'universe_run_id':universe.source['run_id'],
              'bridge':bridge,**FLAGS}
    if any(value.get(k)!=v or (isinstance(v,bool) and value.get(k) is not v) for k,v in identity.items()):
        raise EvidenceError('SNAPSHOT_IDENTITY_INVALID')
    if value.get('normalization')!='NONFINITE_TO_NULL_V1' or not isinstance(value.get('bridge_return_json'),str):
        raise EvidenceError('SNAPSHOT_NORMALIZATION_UNBOUND')
    original=value['bridge_return_json']
    if digest(original.encode())!=value.get('bridge_return_sha256'):
        raise EvidenceError('SNAPSHOT_BRIDGE_RETURN_SHA_MISMATCH')
    try: normalized=json.loads(original,parse_constant=lambda _value: None)
    except ValueError as exc: raise EvidenceError('SNAPSHOT_BRIDGE_RETURN_INVALID') from exc
    if (value.get('rows')!=normalized.get('rows')
        or value.get('errors')!=[str(x)[:160] for x in normalized.get('errors',[])]):
        raise EvidenceError('SNAPSHOT_NORMALIZED_ROWS_MISMATCH')
    rows=value.get('rows'); errors=value.get('errors')
    if not isinstance(rows,list) or not all(isinstance(x,dict) for x in rows): raise EvidenceError('SNAPSHOT_ROWS_INVALID')
    if not isinstance(errors,list) or not all(isinstance(x,str) for x in errors): raise EvidenceError('SNAPSHOT_ERRORS_INVALID')
    if path.read_bytes()!=encoded(value): raise EvidenceError('SNAPSHOT_NONCANONICAL_OR_CORRUPTED')
    sha=digest(path.read_bytes())
    expected={'schema_version':RECEIPT_SCHEMA,'market':MARKET,'trade_date':trade_date,'slot':SLOT,
              'artifact_ref':ref,'artifact_sha256':sha,'bridge':bridge,'row_count':len(rows),
              'universe_sha256':universe.source['sha256'],'available_at':value['available_at'],
              'run_id':'mcs-'+sha[:24],**FLAGS}
    if encoded(receipt)!=encoded(expected): raise EvidenceError('SNAPSHOT_RECEIPT_SHA_OR_IDENTITY_MISMATCH')
    source={'owner':'v35_dispatcher.hourly_research','role':'EXISTING_SHARED_FUTU_1530_SNAPSHOT',
            'market':MARKET,'lane':'CLOSE_DISCOVERY','source_date':trade_date,'run_id':receipt['run_id'],
            'artifact_ref':ref,'receipt_ref':ref+'.receipt.json','manifest_ref':None,'sha256':sha,
            'observed_at':value['started_at'],'available_at':value['available_at'],
            'reason':'既有共享Futu桥原始响应；字节SHA、收据、桥代码身份、时点和资格输入绑定已验证'}
    return VerifiedSnapshot(tuple(rows),tuple(errors),source,universe.source['sha256'],digest(encoded(rows)),prior_universe,_SEAL)


def universe_at_snapshot(universe: VerifiedUniverse, snapshot: VerifiedSnapshot) -> VerifiedUniverse:
    """Restore the owner-receipted availability witness, not today's read time."""
    if not admitted(universe,snapshot,snapshot.rows): raise EvidenceError('SNAPSHOT_NOT_ADMITTED')
    return VerifiedUniverse(universe.codes,snapshot.universe_source,_SEAL)
