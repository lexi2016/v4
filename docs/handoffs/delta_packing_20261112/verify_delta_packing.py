"""Read-only current-reader certification and isolated incremental packing oracle.

No formula evaluation, collection, source mutation, pointer publication or service.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import importlib.util
import itertools
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
import pyarrow as pa
import pyarrow.compute as pc
from ops import research_panel_delta as delta
from ops import research_panel_logical as logical
from ops import research_panel_qfq as owner


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):owner._json(Path(path),value)
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def same_values(left,right):
    if not left.schema.equals(right.schema,check_metadata=True) or len(left)!=len(right):
        raise AssertionError('EXACT_SCHEMA_OR_ROW_COUNT_CHANGED')
    for name,a,b in zip(left.schema.names,left.columns,right.columns):
        equal=pc.or_(pc.fill_null(pc.equal(a,b),False),pc.and_(pc.is_null(a),pc.is_null(b)))
        if pa.types.is_floating(a.type):equal=pc.or_(equal,pc.fill_null(pc.and_(pc.is_nan(a),pc.is_nan(b)),False))
        if len(a) and not pc.all(equal).as_py():raise AssertionError('EXACT_VALUE_OR_NULL_CHANGED:'+name)


def current_role(role,path,before_path,after_path,expected,threads,out):
    pa.set_cpu_count(threads);pa.set_io_thread_count(threads)
    source_hashes=(sha(before_path),sha(after_path))
    before=module(before_path,'packing_before_'+role);after=module(after_path,'packing_after_'+role)
    a,b=before.LogicalFile(path),after.LogicalFile(path)
    if not a.schema_arrow.equals(b.schema_arrow,check_metadata=True):raise AssertionError('PANEL_SCHEMA_CHANGED')
    started=time.perf_counter();rows=batches=0
    for left,right in itertools.zip_longest(a.iter_batches(batch_size=32768),b.iter_batches(batch_size=32768)):
        if left is None or right is None:raise AssertionError('BATCH_BOUNDARIES_CHANGED')
        same_values(left,right);rows+=len(left);batches+=1
        if batches%32==0:save(Path(out)/(role+'_progress.json'),dict(rows=rows,batches=batches,elapsed_seconds=time.perf_counter()-started))
    if rows!=expected or a.metadata.num_rows!=b.metadata.num_rows or rows!=a.metadata.num_rows:
        raise AssertionError('TOTAL_PANEL_ROWS_CHANGED')
    if source_hashes!=(sha(before_path),sha(after_path)):raise AssertionError('READER_SOURCE_CHANGED_DURING_CERTIFICATION')
    result=dict(status='PASS',role=role,rows=rows,columns=len(a.schema_arrow),batches=batches,
        schema_sha256=hashlib.sha256(a.schema_arrow.serialize()).hexdigest(),row_key_order='EXACT_UNCHANGED',null_nan='COMPARED_SEPARATELY',
        anchor=dict(path=str(path),sha256=sha(path)),before_sha256=sha(before_path),after_sha256=sha(after_path),
        elapsed_seconds=time.perf_counter()-started,formula_computations=0,source_writes=0)
    save(Path(out)/(role+'_reader_result.json'),result);return result


def certify(args,foundation,out):
    threads=max(1,min(7,((os.cpu_count()or 1)-4)//2))
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn'))as pool:
        futures=[pool.submit(current_role,role,info['path'],str(args.before_logical),str(ROOT/'ops/research_panel_logical.py'),info['rows'],threads,str(out))for role,info in foundation['roles'].items()]
        roles=[future.result()for future in futures]
    result=dict(status='PASS',scope='CURRENT_D11_BOTH_FULL_LOGICAL_PANELS_BEFORE_AFTER_STREAM',source_generation=foundation['generation'],
        roles=roles,formula_computations=0,source_writes=0,scope_note='First compatibility certification, not PIT or natural-run certification')
    save(out/'CURRENT_READER_CERTIFICATION.json',result);return result


def descriptor_raw(path):
    raw=Path(path).read_bytes();assert raw.startswith(logical.MAGIC);return json.loads(raw[len(logical.MAGIC):])


def shadow(args,foundation,out,canary):
    raw={role:descriptor_raw(info['path'])for role,info in foundation['roles'].items()}
    by_role={role:{code:block for block in desc['blocks'][1:]for code in block['symbols']}for role,desc in raw.items()}
    symbols=sorted(set.intersection(*(set(v)for v in by_role.values())))
    if canary:
        symbols=[next(s for s in symbols if s.endswith('.'+market))for market in ['SH','SZ','BJ']]
    assert symbols
    base={role:desc['blocks'][0]for role,desc in raw.items()};schemas={role:pa.ipc.read_schema(pa.BufferReader(__import__('base64').b64decode(desc['arrow_schema'])))for role,desc in raw.items()}
    # Physical source footers differ by stock. Only transport metadata is
    # replaced; values, field metadata, types, order and nulls remain exact.
    c=dict(run_dir=out/'run',run_id='SHADOW_NOT_PUBLISHABLE_'+foundation['generation'],target=20261111,
        identity=dict(input_sha256='D11_EXISTING_BLOCKS_STORAGE_ONLY'),schemas=schemas,
        candidates={role:out/role/'NOT_PUBLISHABLE.logical'for role in schemas},resource_plan=dict(job_budget_bytes=64*1024**3))
    q=dict(vars(owner));packer=delta._PackedWrites(q,c);scoped={role:[]for role in schemas};before_bytes={role:0 for role in schemas};expected_rows={role:0 for role in schemas};expected_files={role:set()for role in schemas};records={};started=time.perf_counter()
    def accept(items):
        for item in items:
            code=item['code'];record=item['record'];records[code]=record
            for role,value in record['roles'].items():delta._add_scoped_block(scoped[role],code,value['block'])
    for code in symbols:
        patches={};roles={}
        for role in schemas:
            block=by_role[role][code];path=Path(block['path']);assert logical.stamp(path)==block['stat'] and sha(path)==block['sha256']
            table=logical.physical.read_table(path)
            if set(table['ts_code'].to_pylist())!={code}:
                table=table.filter(pc.equal(table['ts_code'],code))
            meta={k:v for k,v in (schemas[role].metadata or{}).items()if k!=logical.META}
            table=table.replace_schema_metadata(meta);patches[role]=table;roles[role]=dict(appended_rows=len(table),revised_rows=0)
            expected_rows[role]+=len(table)
            if path not in expected_files[role]:before_bytes[role]+=path.stat().st_size;expected_files[role].add(path)
        record=dict(dependency=owner.canonical_sha(dict(source_generation=foundation['generation'],symbol=code,inputs={role:by_role[role][code]['sha256']for role in schemas})),
            classification='SHADOW_EXISTING_CHANGED_ROWS',roles=roles,logical_rows={role:len(t)for role,t in patches.items()},has_target={role:20261111 in t['trade_date'].to_pylist()for role,t in patches.items()})
        prepared=dict(code=code,dependency=record['dependency'],kind=record['classification'],checkpoint=c['run_dir']/'delta_checkpoints'/(code+'.'+record['dependency']+'.json'),record=record,patches=patches)
        accept(packer.add(prepared))
    accept(packer.flush())
    reports={}
    for role in schemas:
        target=c['candidates'][role];target.parent.mkdir(parents=True,exist_ok=True)
        # Delta-only, not a second full panel or a publishable generation.
        schema=schemas[role].remove_metadata()
        target.write_bytes(logical.anchor_bytes(schema,scoped[role],rows=expected_rows[role]))
        actual=logical.parquet.read_table(target)
        # Compare each source symbol and full field schema/null/value/order once.
        for code in symbols:
            block=by_role[role][code];before=logical.physical.read_table(block['path'])
            before=before.filter(pc.equal(before['ts_code'],code)).replace_schema_metadata(None)
            after=actual.filter(pc.equal(actual['ts_code'],code)).replace_schema_metadata(None)
            same_values(before,after)
        assert len(actual)==expected_rows[role]
        paths={Path(b['path'])for b in scoped[role]};new_bytes=sum(p.stat().st_size for p in paths)
        reports[role]=dict(rows=len(actual),symbols=len(symbols),columns=len(schema),old_physical_files=len(expected_files[role]),
            new_physical_files=len(paths),before_parquet_bytes=before_bytes[role],after_parquet_bytes=new_bytes,
            exact_schema_values_nulls_dates=True,source_base_rewritten=False)
    metadata_bytes=sum(p.stat().st_size for p in c['run_dir'].rglob('*.json'))
    result=dict(status='PASS',scope='THREE_MARKET_CANARY'if canary else'ALL_D11_INCREMENTAL_ROWS_ONLY',source_generation=foundation['generation'],
        symbols=len(symbols),roles=reports,packing_limits=packer.limits,checkpoint_and_seal_bytes=metadata_bytes,
        total_output_bytes=packer.written_bytes+metadata_bytes,elapsed_seconds=time.perf_counter()-started,formula_computations=0,source_writes=0,
        excluded_historical_bases={role:dict(path=b['path'],bytes=b['stat']['size'],rewritten=False)for role,b in base.items()},publishable=False)
    save(out/'SHADOW_RESULT.json',result);return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['current-reader','shadow-canary','shadow-full'],required=True);p.add_argument('--foundation',type=Path,required=True);p.add_argument('--before-logical',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    foundation=json.loads(args.foundation.read_text());assert foundation['status']=='FOUNDATION_D11_VERIFIED'
    for value in foundation['roles'].values():
        if out.is_relative_to(Path(value['path']).parent):raise ValueError('SHADOW_OUTPUT_INSIDE_FORMAL_SOURCE')
    observed=delta.observe_resources()
    save(out/'RESOURCE_OBSERVATION.json',observed)
    validation_sources={name:dict(path=str(path),sha256=sha(path))for name,path in {'delta':ROOT/'ops/research_panel_delta.py','logical':ROOT/'ops/research_panel_logical.py','validator':Path(__file__)}.items()}
    started=time.perf_counter()
    try:
        result=certify(args,foundation,out)if args.mode=='current-reader'else shadow(args,foundation,out,args.mode=='shadow-canary')
        if any(sha(v['path'])!=v['sha256']for v in validation_sources.values()):raise AssertionError('VALIDATION_SOURCE_CHANGED')
        result['validation_sources']=validation_sources
        result['resource_observation']=observed
        save(out/('CURRENT_READER_CERTIFICATION.json'if args.mode=='current-reader'else'SHADOW_RESULT.json'),result)
        print(json.dumps(dict(status=result['status'],mode=args.mode,elapsed_seconds=time.perf_counter()-started,roles=result.get('roles')),ensure_ascii=False),flush=True)
    except BaseException as error:
        save(out/'FAILURE.json',dict(status='FAIL',error=repr(error),mode=args.mode));raise


if __name__=='__main__':main()
