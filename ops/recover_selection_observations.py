"""Deterministic offline observation recovery from exact archived Stage trios.

No live store, current pointer, provider, API or scheduler is imported or written.
The output is a research evidence derivative, never a replacement selection or a
formal KPI. A supplied externally checked SOURCE_INDEX SHA is mandatory.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

SEVEN = ('STAGE_0925','STAGE_0930_0935','STAGE_0935_0940','STAGE_0940_0945','STAGE_0945_1030','STAGE_1300_1315','STAGE_1445_1500')
SAFETY = ('production_allowed','buy_gate_updated','orders_sent')
V1_FIELDS = ('code','score','rank','status','formal_eligible','support','pressure','invalidation','source_mode','lane_evidence','action_level','trade_status')

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical(value: Any) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False).encode('utf-8')

def csha(value: Any) -> str:
    return sha(canonical(value))

def safe_file(root: Path, relative: str) -> Path:
    if not isinstance(relative,str) or not relative or '\\' in relative:
        raise ValueError('UNSAFE_PATH')
    p=PurePosixPath(relative)
    if p.is_absolute() or p.as_posix()!=relative or any(v in {'.','..'} for v in p.parts):
        raise ValueError('UNSAFE_PATH')
    current=root
    if root.is_symlink(): raise ValueError('SYMLINK_ROOT')
    for part in p.parts:
        current=current/part
        if current.is_symlink(): raise ValueError('SYMLINK_COMPONENT')
    current.resolve().relative_to(root.resolve())
    if not current.is_file(): raise ValueError(f'EXACT_FILE_MISSING:{relative}')
    return current

def require(condition: bool, reason: str) -> None:
    if not condition: raise ValueError(reason)

def verify_trio(artifact: bytes, manifest: Mapping[str,Any], receipt: Mapping[str,Any], pointer: Mapping[str,Any], date: str, stage: str, market: str) -> dict[str,Any]:
    require(re.fullmatch(r'\d{8}',date) is not None, 'DATE_INVALID')
    require(stage in (*SEVEN,'STAGE_1545_1555') and market in {'A_SHARE','HK_CONNECT'},'KEY_INVALID')
    env=manifest.get('selection_envelope')
    require(isinstance(env,dict),'ENVELOPE_MISSING')
    for obj in (pointer,manifest,receipt,env):
        require(all(obj.get(flag) is False for flag in SAFETY),'SAFETY_INVALID')
        for key,value in [('trade_date',date),('stage_id',stage),('market',market),('run_id',pointer.get('run_id'))]:
            require(obj.get(key)==value, f'IDENTITY_MISMATCH:{key}')
    require(isinstance(pointer.get('run_id'),str) and re.fullmatch(r'run-[0-9a-f]{24}',pointer['run_id']) is not None,'RUN_ID_INVALID')
    for obj in (manifest,receipt,pointer):
        require(obj.get('owner')=='stage_center' and obj.get('role')==f'{market}_SELECTION_{stage}','OWNER_ROLE_INVALID')
        require(obj.get('artifact_sha256')==sha(artifact),'ARTIFACT_SHA_MISMATCH')
        require(obj.get('artifact_relative')==f"selection_runs/{date}/{market}_SELECTION_{stage}/{pointer['run_id']}/artifact.csv",'ARTIFACT_PATH_MISMATCH')
    require(manifest.get('schema_version')=='stage_center.selection.manifest.v1','MANIFEST_SCHEMA')
    require(receipt.get('schema_version')=='stage_center.selection.receipt.v1','RECEIPT_SCHEMA')
    require(env.get('schema_version') in {'stage_center.selection.v1','stage_center.selection.v2'},'ENVELOPE_SCHEMA')
    require(pointer.get('manifest_sha256')==receipt.get('manifest_sha256')==csha(manifest),'MANIFEST_SHA_MISMATCH')
    require(pointer.get('receipt_sha256')==csha(receipt),'RECEIPT_SHA_MISMATCH')
    require(pointer.get('idempotency_key')==receipt.get('idempotency_key') and re.fullmatch('[0-9a-f]{64}',str(receipt.get('idempotency_key'))) is not None,'IDEMPOTENCY_MISMATCH')
    for key in ('algorithm_id','algorithm_sha256','raw_artifact_sha256','selection_status'):
        require(env.get(key)==manifest.get(key)==receipt.get(key),f'ENVELOPE_BINDING:{key}')
    rows=env.get('rows')
    require(isinstance(rows,list),'ROWS_MISSING')
    require(type(env.get('selected_rows')) is int and env['selected_rows']==manifest.get('row_count')==receipt.get('row_count')==len(rows),'ROW_COUNT_MISMATCH')
    csv_reader=csv.DictReader(io.StringIO(artifact.decode('utf-8-sig')))
    require(tuple(csv_reader.fieldnames or ())==V1_FIELDS,'CSV_FIELDS_UNSUPPORTED')
    csv_rows=list(csv_reader)
    require(len(csv_rows)==len(rows),'CSV_ROW_COUNT')
    codes=[]
    for original,projected in zip(rows,csv_rows):
        require(isinstance(original,dict),'INVALID_ROW')
        require(isinstance(original.get('code'),str) and re.fullmatch(r'HK\.\d{5}' if market=='HK_CONNECT' else r'(?:A|SH|SZ|BJ)\.\d{6}',original['code']) is not None,'ROW_MARKET')
        codes.append(original['code'])
        for key in V1_FIELDS:
            value=original.get(key)
            expected=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')) if isinstance(value,(list,dict)) else '' if value is None else str(value)
            require(projected[key]==expected,f'CSV_ENVELOPE_MISMATCH:{key}')
    require(len(codes)==len(set(codes)),'DUPLICATE_CODE')
    return {'trade_date':date,'stage_id':stage,'market':market,'selection_envelope':env,
            'pointer':dict(pointer),'manifest_sha256':csha(manifest),'receipt_sha256':csha(receipt),'artifact_sha256':sha(artifact)}

def recover(history_root: Path, *, expected_index_sha: str, trade_date: str='20260923') -> dict[str,Any]:
    root=Path(history_root)
    index_path=safe_file(root,'SOURCE_INDEX.json'); require(sha(index_path.read_bytes())==expected_index_sha,'INDEX_SHA_MISMATCH')
    index=json.loads(index_path.read_bytes()); records=index.get('entries');require(isinstance(records,list),'INDEX_ENTRIES')
    seen=set()
    for row in records:
        relative=row['copy_relative_path'];require(relative not in seen,'INDEX_DUPLICATE');seen.add(relative)
        data=safe_file(root,relative).read_bytes()
        require(sha(data)==row['sha256'] and len(data)==row['bytes'],f'SOURCE_BYTES_MISMATCH:{relative}')
    def read_indexed(relative):
        require(relative in seen,'UNINDEXED_SOURCE:'+relative)
        return safe_file(root,relative).read_bytes()
    ptr_relative=f'evidence/selection/selection_latest_{trade_date}_excerpt.json'
    pointer=json.loads(read_indexed(ptr_relative));require(pointer.get('trade_date')==trade_date,'POINTER_DATE')
    entries=pointer.get('entries');require(isinstance(entries,dict) and len(entries)==pointer.get('date_entry_count'),'POINTER_ENTRIES')
    native_relative=f'evidence/native_close_review/{trade_date}.json'
    native_bytes=read_indexed(native_relative);native=json.loads(native_bytes)
    require(native.get('trade_date')==trade_date and all(native.get(f) is False for f in SAFETY),'NATIVE_IDENTITY')
    groups=[]; observations=[]; hk_rows=[]; bindings=[]
    top20=native.get('close_top20');require(isinstance(top20,list),'NATIVE_TOP20_MISSING')
    top_codes=[r['code'] for r in top20];require(len(top_codes)==20 and len(set(top_codes))==20,'NATIVE_TOP20_COUNT')
    for key,p in sorted(entries.items()):
        parts=key.split('/');require(len(parts)==3 and parts[0]==trade_date,'POINTER_KEY')
        date,stage,market=parts
        prefix=f'evidence/stage_selection/{date}/{date}/{stage}/{market}'
        g=verify_trio(read_indexed(prefix+'/artifact.csv'),json.loads(read_indexed(prefix+'/manifest.json')),json.loads(read_indexed(prefix+'/receipt.json')),p,date,stage,market)
        groups.append(g);env=g['selection_envelope']
        for row in env['rows']:
            observations.append({'stage_id':stage,'market':market,'trade_date':date,'run_id':env['run_id'],
                                 'selection_artifact_sha256':g['artifact_sha256'],'original_row':row})
        if market=='HK_CONNECT' and stage in SEVEN:
            declaration=(native.get('stage_input_evidence') or {}).get(stage) or {}
            fields=('run_id','artifact_id','algorithm_sha256','raw_artifact_sha256','selected_rows','source_status','selection_status','source_rows','requested_rows')
            comparisons={f:declaration.get(f)==env.get(f) for f in fields}
            bindings.append({'stage_id':stage,'matches':comparisons,'declaration_matches_selection':all(comparisons.values()),
                             'artifact_sha256':g['artifact_sha256'],'manifest_sha256':g['manifest_sha256'],'receipt_sha256':g['receipt_sha256']})
            for row in env['rows']:
                hk_rows.append({'code':row['code'],'evidence_status':'PARTIAL','hit_top20':row['code'] in top_codes,
                                'name':row.get('name') or row.get('stock_name') or row['code'],
                                'stage_id':stage,'stage_rank':row['rank'],'trade_date':date})
    # Compare in contract stage order, retaining within-stage row/rank order.
    hk_rows.sort(key=lambda r:(SEVEN.index(r['stage_id']),r['stage_rank']))
    codes=list(dict.fromkeys(r['code'] for r in hk_rows)); hits=[c for c in codes if c in top_codes]
    native_rows=native.get('stage_rows')
    formal_blockers=[f"{g['stage_id']}:{g['selection_envelope']['selection_status']}" for g in groups if g['market']=='HK_CONNECT' and g['stage_id'] in SEVEN and g['selection_envelope']['selection_status']!='READY']
    present={g['stage_id'] for g in groups if g['market']=='HK_CONNECT'}
    formal_blockers += ['MISSING_HK_STAGE:'+stage for stage in SEVEN if stage not in present]
    # Declared IDs matching captured selections is stronger than stage-ID-only,
    # but cannot prove an unsupplied raw market-data/execution lineage.
    return {'schema':'v4.offline_selection_observation_recovery.v1','trade_date':trade_date,
            'status':'OFFLINE_OBSERVATIONS_RECONSTRUCTED_NOT_PUBLISHED',
            'source_index_sha256':expected_index_sha,'source_count_verified':len(records),
            'source_pointer_excerpt_sha256':sha(read_indexed(ptr_relative)),'native_source_sha256':sha(native_bytes),
            'verified_group_count':len(groups),'selection_observations':observations,
            'group_bindings':[{k:v for k,v in g.items() if k!='selection_envelope'} for g in groups],
            'hk_observed':{'row_count':len(hk_rows),'unique_code_count':len(codes),'codes':codes,'hit_count':len(hits),'hit_codes':hits,'stage_rows':hk_rows,'evidence_status':'PARTIAL_RESEARCH_ONLY'},
            'native_binding':{'matching_stage_count':sum(b['declaration_matches_selection'] for b in bindings),'per_stage':bindings,
                              'rows_equal':hk_rows==native_rows,'scope':'CAPTURED_DECLARATIONS_AND_SELECTION_TRIOS_MATCH_NOT_RAW_INPUT_OR_EXECUTION_ATTESTATION'},
            'formal_seven_stage_union':{'status':'CANNOT_CONFIRM','selected_count':None,'blockers':formal_blockers or ['FORMAL_RAW_INPUT_EXECUTION_ATTESTATION_NOT_PROVIDED']},
            'unrecovered':['A_SHARE_0925_EXACT_TICKS','HK_STAGE8_VALID_SNAPSHOT','SH.601091_AUTHORITY_NAME','DAILY_EXACT_INPUT','SIX_SLOT_EXACT_TRIOS'],
            'recovery_flags':{'authoritative_write_performed':False,'historical_ticks_reconstructed':False,'natural_verified':False,**{f:False for f in SAFETY}}}

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--history-root',type=Path,required=True);p.add_argument('--source-index-sha256',required=True);p.add_argument('--date',default='20260923')
    a=p.parse_args();result=recover(a.history_root,expected_index_sha=a.source_index_sha256,trade_date=a.date)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2));return 0

if __name__=='__main__': raise SystemExit(main())
