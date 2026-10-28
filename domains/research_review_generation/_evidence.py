"""Bind the one materialized input to actual source/raw/authority bytes.

All referenced evidence is copied byte-for-byte into the explicit state root
and read through SafeRoot. A content hash is not a signature: trust begins at
the caller-approved code/config/input hashes and the one authorized writer.
"""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path

from infrastructure.owned_io import SafeRoot
from ._cache import encoded,digest,explicit_root
from ._owned_io import BoundaryError
from ._snapshot import FUNCTIONS,SECTIONS,SOURCE_ROLE,sha

FALSE_FLAGS={'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}


def put_content(io: SafeRoot, prefix: str, raw: bytes) -> dict:
    path=prefix+'/'+digest(raw)+'.json'
    try:io.write_bytes(path,raw,require_absent=True)
    except FileExistsError:
        if io.read_bytes(path)!=raw:raise BoundaryError('content-address collision')
    return {'path':path,'bytes':len(raw),'sha256':digest(raw)}


def read_bound(io: SafeRoot, binding: dict, *, prefixes: tuple[str,...]) -> tuple[dict,bytes]:
    if not isinstance(binding,dict) or not isinstance(binding.get('path'),str):
        raise BoundaryError('actual evidence file binding required')
    path=binding['path']
    SafeRoot._parts(path)
    if not path.startswith(prefixes):
        raise BoundaryError('evidence path outside approved state subdirectories')
    raw=io.read_bytes(path,max_bytes=64*1024*1024)
    if len(raw)!=binding.get('bytes') or digest(raw)!=sha(binding.get('sha256')):
        raise BoundaryError('evidence bytes/SHA drift: '+path)
    try:
        obj=json.loads(raw,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite evidence')))
    except (ValueError,UnicodeError) as exc:
        raise BoundaryError('evidence JSON invalid') from exc
    if not isinstance(obj,dict):raise BoundaryError('evidence must be a JSON object')
    return obj,raw


def _logical(payload: dict) -> dict:
    value=deepcopy(payload)
    value.pop('authority_receipt',None);value.pop('authority_receipt_sha256',None)
    return value


def _values(payload):
    values=dict(payload['functions'])
    for name in SECTIONS:
        parent,child=name.split('.')
        values[name]=payload['functions']['get_'+parent][1].get(child)
    values['news']=payload['news']
    values['calendar']={'settled':payload['calendar'].get('settled')}
    return values


def seal_snapshot(*, state_root: Path, payload: dict, raw_refs: list[dict],
                  reflection_manifest: list[dict], implementation_sha256: str,
                  cache_refs: list[dict] | None = None) -> tuple[dict,str]:
    """Finalization inside the existing owner's task lock; not another producer."""
    io=SafeRoot(explicit_root(state_root));out=deepcopy(payload)
    target=out['trade_date'];values=_values(out)
    source_refs={}
    for key,value in values.items():
        metadata=out['calendar'] if key=='calendar' else out['sources'].get(key)
        if metadata is None:
            # Missing required evidence remains missing for the public validator.
            continue
        meta={k:v for k,v in metadata.items() if k not in {'source_path','source_bytes','source_sha256'}}
        doc={'schema':'v4.vibe_source.v1','source_key':key,'target_date':target,
             'source_role':SOURCE_ROLE,'metadata':meta,'value':value,
             'raw_refs':deepcopy(raw_refs),'cache_refs':deepcopy(cache_refs or []),**FALSE_FLAGS}
        ref=put_content(io,'sources',encoded(doc))
        metadata.update(source_path=ref['path'],source_bytes=ref['bytes'],source_sha256=ref['sha256'])
        source_refs[key]=ref
    receipt={'schema':'v4.vibe_authority_receipt.v1','target_date':target,
             'authority_id':out['authority_id'],'source_role':SOURCE_ROLE,
             'implementation_manifest_sha256':sha(implementation_sha256),
             'logical_input_sha256':digest(encoded(_logical(out))),
             'sources':source_refs,'raw_refs':deepcopy(raw_refs),'cache_refs':deepcopy(cache_refs or []),
             'reflection_manifest':deepcopy(reflection_manifest),
             'provider_counts':deepcopy(out.get('provider_counts',{})),
             'date_evidence_scope':'REQUEST_AND_ENVELOPE_VALIDATED_NOT_PROVIDER_TRUTH_OR_PIT',**FALSE_FLAGS}
    ref=put_content(io,'receipts',encoded(receipt))
    out['authority_receipt']=ref;out['authority_receipt_sha256']=ref['sha256']
    # Verify bytes before publishing the ready-to-consume input.
    verify_evidence(state_root=state_root,payload=out,implementation_sha256=implementation_sha256,
                    reflection_manifest=reflection_manifest)
    raw=encoded(out)
    name='inputs/'+target+'.json'
    try:io.write_bytes(name,raw,require_absent=True)
    except FileExistsError:
        if io.read_bytes(name)!=raw:raise BoundaryError('exact-date input already exists with different bytes')
    return out,digest(raw)


def verify_evidence(*,state_root: Path,payload: dict,implementation_sha256: str,
                    reflection_manifest: list[dict]) -> dict:
    io=SafeRoot(explicit_root(state_root));target=payload['trade_date']
    receipt,_=read_bound(io,payload.get('authority_receipt'),prefixes=('receipts/',))
    if payload['authority_receipt_sha256']!=payload['authority_receipt']['sha256']:
        raise BoundaryError('authority receipt pointers disagree')
    if (receipt.get('schema')!='v4.vibe_authority_receipt.v1' or receipt.get('target_date')!=target or
        receipt.get('source_role')!=SOURCE_ROLE or receipt.get('authority_id')!=payload['authority_id'] or
        receipt.get('implementation_manifest_sha256')!=implementation_sha256 or
        receipt.get('logical_input_sha256')!=digest(encoded(_logical(payload)))):
        raise BoundaryError('authority receipt identity/content mismatch')
    for flag in FALSE_FLAGS:
        if receipt.get(flag) is not False:raise BoundaryError('authority receipt unsafe flags')
    if receipt.get('reflection_manifest')!=reflection_manifest:
        raise BoundaryError('reflection inventory drift against authority receipt')
    values=_values(payload);source_refs=receipt.get('sources')
    if not isinstance(source_refs,dict) or set(source_refs)!=set((*FUNCTIONS,*SECTIONS,'news','calendar')):
        raise BoundaryError('authority receipt source closure incomplete')
    for key,ref in source_refs.items():
        metadata=payload['calendar'] if key=='calendar' else payload['sources'].get(key,{})
        if ref!={'path':metadata.get('source_path'),'bytes':metadata.get('source_bytes'),'sha256':metadata.get('source_sha256')}:
            raise BoundaryError('source pointer differs from receipt')
        doc,_=read_bound(io,ref,prefixes=('sources/',))
        expected_meta={k:v for k,v in metadata.items() if k not in {'source_path','source_bytes','source_sha256'}}
        if (doc.get('schema')!='v4.vibe_source.v1' or doc.get('target_date')!=target or
            doc.get('source_key')!=key or doc.get('source_role')!=SOURCE_ROLE or
            doc.get('value')!=values[key] or doc.get('metadata')!=expected_meta or
            doc.get('raw_refs')!=receipt.get('raw_refs') or doc.get('cache_refs')!=receipt.get('cache_refs')):
            raise BoundaryError('source content/date/provenance mismatch')
    refs=receipt.get('raw_refs',[])
    if not isinstance(refs,list):raise BoundaryError('raw refs invalid')
    for ref in refs:
        obj,_=read_bound(io,ref,prefixes=('raw/',))
        if (obj.get('schema')!='v4.vibe_raw.v1' or obj.get('review_target_date')!=target or
            obj.get('identity',{}).get('session')!=ref.get('session') or
            obj.get('result',{}).get('kind')!=ref.get('kind')):
            raise BoundaryError('raw request date/identity differs from binding')
    cache_refs=receipt.get('cache_refs',[])
    for ref in cache_refs:
        obj,_=read_bound(io,ref,prefixes=('cache_evidence/',))
        if (obj.get('schema')!='v4.vibe_cache_evidence.v1' or obj.get('review_target_date')!=target or
            obj.get('session')!=ref.get('session')):
            raise BoundaryError('cache source identity differs from binding')
        import base64
        raw=base64.b64decode(obj.get('content_base64',''),validate=True)
        if digest(raw)!=obj.get('original_sha256') or len(raw)!=obj.get('original_bytes'):
            raise BoundaryError('cache original bytes binding differs')
    return {'authority_receipt_independently_verified':True,
            'receipt_sha256':payload['authority_receipt_sha256'],
            'source_files_verified':len(source_refs),'raw_files_verified':len(refs),
            'cache_files_verified':len(cache_refs),'reflection_files_verified':len(reflection_manifest),
            'response_date_truth':'CANNOT_CONFIRM_WHERE_PROVIDER_OMITS_DATE_ECHO',
            'pit_claim':False}
