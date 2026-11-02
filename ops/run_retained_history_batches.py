"""Resume existing retained-history owner over a bound generic-view index.

No prices, labels or panels are calculated here.  The original single-stock
history owner calculates only missing event statistics; verified old history
and successfully checkpointed shards are reused.  Output is isolated.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import sys
import tempfile

from ops import bootstrap_stock_event_history as owner


def _root(path):
    path=Path(path)
    if not path.is_absolute() or path.is_symlink():raise ValueError('HISTORY_BATCH_ROOT_INVALID')
    path=path.resolve()
    protected=[Path.home()/'Library/Application Support/com.lexi.v35.local/state',
               Path.home()/'Library/Application Support/com.lexi.v4.local/state']
    if any(path==p.resolve() or path in p.resolve().parents or p.resolve() in path.parents for p in protected):
        raise ValueError('HISTORY_BATCH_ROOT_OVERLAPS_ACTIVE_STATE')
    path.mkdir(parents=True,exist_ok=True)
    return path


def _identity(index):
    return {k:index.get(k) for k in ('source_date','source_generation','input_sha256',
        'candidate_generation','candidate_input_sha256','paired_receipt','pair_sha256')}


def _verified_ready_history(index,symbol):
    entry=index.get('symbols',{}).get(symbol,{})
    if entry.get('status')!='READY' or not entry.get('binding'):return None
    bound=owner.load(entry['binding']);history=bound.get('details',{}).get('history',{})
    if history.get('status')!='READY' or not history.get('asset'):return None
    if (bound.get('symbol')!=symbol or bound.get('candidate_generation')!=index.get('candidate_generation')
            or history.get('candidate_generation')!=index.get('candidate_generation')
            or any(bound.get(k)!=v for k,v in owner.FLAGS.items())):
        raise ValueError('HISTORY_BATCH_PRIOR_BINDING_CONFLICT:'+symbol)
    owner.load_path(history['asset'])
    return {'binding':entry['binding'],'history':history,'history_input':bound.get('history_input')}


def plan(index_ref, prior_index_ref, calendar_ref, output_root, *, expected_owner_sha256):
    """Validate and partition inputs; no formula or history calculation."""
    root=_root(output_root)
    if owner.sha(owner.__file__)!=expected_owner_sha256:raise ValueError('HISTORY_BATCH_OWNER_SHA_DRIFT')
    index=owner.load(index_ref);prior=owner.load(prior_index_ref);calendar=owner.load(calendar_ref)
    if (index.get('schema')!='v4.workbench.generic_single_index.v1'
            or prior.get('schema')!='v4.workbench.generic_single_index.v1'
            or _identity(index)!=_identity(prior)
            or any(index.get(k)!=v or prior.get(k)!=v for k,v in owner.FLAGS.items())
            or calendar.get('historical_PIT') is not False):
        raise ValueError('HISTORY_BATCH_INDEX_IDENTITY_CONFLICT')
    result={};jobs=[]
    for symbol,entry in sorted(index.get('symbols',{}).items()):
        if entry.get('status')!='READY' or not entry.get('binding'):
            result[symbol]={'status':'UNKNOWN','reason':entry.get('reason','VIEW_NOT_READY')};continue
        current=owner.load(entry['binding'])
        if (current.get('symbol')!=symbol or current.get('candidate_generation')!=index['candidate_generation']
                or current.get('candidate_input_sha256')!=index['candidate_input_sha256']
                or current.get('paired_receipt')!=index['paired_receipt']
                or any(current.get(k)!=v for k,v in owner.FLAGS.items())):
            raise ValueError('HISTORY_BATCH_CURRENT_BINDING_CONFLICT:'+symbol)
        previous=_verified_ready_history(prior,symbol)
        if previous:
            old_input=previous['history_input'] or {};new_input=current.get('history_input') or {}
            if any(old_input.get(k)!=new_input.get(k) for k in ('sha256','bytes','decoded_bytes','encoding')):
                result[symbol]={'status':'UNKNOWN','reason':'EXISTING_HISTORY_INPUT_CHANGED'};continue
            owner.load_path(old_input);owner.load_path(new_input)
            result[symbol]={'status':'REUSED_EXISTING_HISTORY','prior_binding':previous['binding'],
                            'history':previous['history']};continue
        existing=_verified_ready_history(index,symbol)
        if existing:
            result[symbol]={'status':'REUSED_EXISTING_HISTORY','prior_binding':existing['binding'],
                            'history':existing['history']};continue
        source_ref=entry.get('projection_source_index') or index_ref
        source=owner.load(source_ref);source_entry=source.get('symbols',{}).get(symbol,{})
        if (_identity(source)!=_identity(index) or source_entry.get('binding')!=entry['binding']
                or source_entry.get('status')!='READY'):
            raise ValueError('HISTORY_BATCH_PROJECTION_SOURCE_CONFLICT:'+symbol)
        producer=source.get('projection_producer') or {};owner.load_path(producer)
        history_input=current.get('history_input');owner.load_path(history_input)
        key={'symbol':symbol,'binding':entry['binding'],'history_input':history_input,'calendar':calendar_ref,
             'paired_receipt':index['paired_receipt'],'projection_producer_sha256':producer['sha256'],
             'history_owner_sha256':expected_owner_sha256}
        fingerprint=hashlib.sha256(owner.canonical(key)).hexdigest()
        checkpoint=root/'checkpoints'/symbol/(fingerprint+'.json')
        failure=root/'failures'/symbol/(fingerprint+'.json')
        if failure.is_file():
            saved=owner.load(owner.ref(failure))
            if saved.get('key')!=key:raise ValueError('HISTORY_BATCH_FAILURE_IDENTITY_CONFLICT:'+symbol)
            result[symbol]={'status':'FAILED','failure':owner.ref(failure)};continue
        if checkpoint.is_file():
            saved=owner.load(owner.ref(checkpoint));shard=owner.load(saved['shard'])
            if (saved.get('key')!=key or shard.get('symbol')!=symbol or shard.get('history_input')!=history_input
                    or shard.get('projection_binding')!=entry['binding'] or shard.get('market_calendar')!=calendar_ref
                    or shard.get('paired_receipt')!=index['paired_receipt']
                    or shard.get('producer_sha256')!=expected_owner_sha256):
                raise ValueError('HISTORY_BATCH_CHECKPOINT_IDENTITY_CONFLICT:'+symbol)
            result[symbol]={'status':'REUSED_CHECKPOINT','shard':saved['shard'],
                            'source_index':shard['projection_index']};continue
        jobs.append({'symbol':symbol,'source_index':source_ref,'producer_sha256':producer['sha256'],
                     'calendar':calendar_ref,'output_root':str(root),'checkpoint':str(checkpoint),
                     'failure':str(failure),'key':key})
    return index,result,jobs


def _run_one(job):
    root=Path(job['output_root'])
    if job.get('compact'):
        temporary_root=root/'temporary_history';temporary_root.mkdir(parents=True,exist_ok=True)
        temporary=Path(tempfile.mkdtemp(prefix=job['symbol']+'.',dir=temporary_root))
        try:
            original=owner.build_retained_pair_history(job['source_index'],job['symbol'],job['calendar'],
                temporary,expected_projection_sha256=job['producer_sha256'])
            original_path=owner.load_path(original)
            if temporary.resolve() not in original_path.resolve().parents:
                raise ValueError('HISTORY_TEMPORARY_OUTPUT_OUTSIDE_ROOT')
            raw=original_path.read_bytes()
            if len(raw)>32*1024*1024 or hashlib.sha256(raw).hexdigest()!=original['sha256']:
                raise ValueError('HISTORY_UNCOMPRESSED_IDENTITY_CONFLICT')
            packed=gzip.compress(raw,compresslevel=5,mtime=0)
            if len(packed)>8*1024*1024 or gzip.decompress(packed)!=raw:
                raise ValueError('HISTORY_GZIP_ROUNDTRIP_FAILED')
            digest=hashlib.sha256(packed).hexdigest()
            destination=root/'compressed_shards'/job['symbol']/(digest+'.json.gz')
            destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists():
                if hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:
                    raise ValueError('HISTORY_GZIP_IMMUTABLE_CONFLICT')
            else:
                pending=destination.with_name('.'+destination.name+'.'+str(os.getpid())+'.pending')
                with pending.open('xb') as output:
                    output.write(packed);output.flush();os.fsync(output.fileno())
                os.replace(pending,destination)
            shard={'path':str(destination.resolve()),'sha256':digest,'bytes':len(packed),
                   'encoding':'gzip','decoded_bytes':len(raw),'decoded_sha256':original['sha256']}
            if owner.load(shard)!=json.loads(raw):raise ValueError('HISTORY_GZIP_OWNER_READBACK_CONFLICT')
        except Exception as error:
            raise ValueError('HISTORY_TEMPORARY_PRESERVED:'+str(temporary)+':'+str(error)) from error
        # Only this invocation's verified, fully recoverable temporary bytes.
        shutil.rmtree(temporary)
    else:
        shard=owner.build_retained_pair_history(job['source_index'],job['symbol'],job['calendar'],
            root,expected_projection_sha256=job['producer_sha256'])
    checkpoint=Path(job['checkpoint'])
    value={'schema':'v4.a_share.retained_history_batch_checkpoint.v1','key':job['key'],'shard':shard,**owner.FLAGS}
    if checkpoint.exists():
        if owner.load(owner.ref(checkpoint))!=value:raise ValueError('HISTORY_BATCH_CHECKPOINT_COLLISION')
    else:owner.save(checkpoint,value)
    return shard


def run(index_ref, prior_index_ref, calendar_ref, output_root, *, expected_owner_sha256, workers, max_new,
        compact=False):
    if type(workers) is not int or not 1<=workers<=4 or type(max_new) is not int or max_new<1:
        raise ValueError('HISTORY_BATCH_RESOURCE_LIMIT')
    root=_root(output_root)
    index,results,jobs=plan(index_ref,prior_index_ref,calendar_ref,root,expected_owner_sha256=expected_owner_sha256)
    failures=[s for s,x in results.items() if x['status']=='FAILED']
    chosen=[] if failures else jobs[:max_new]
    for job in chosen:job['compact']=compact
    remaining=jobs if failures else jobs[max_new:]
    multiprocessing.set_executable(sys.executable)
    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for start in range(0,len(chosen),workers):
            if shutil.disk_usage(root).free<=24*1024**3+256*1024**2:
                remaining=chosen[start:]+remaining
                break
            batch=chosen[start:start+workers];futures={pool.submit(_run_one,job):job for job in batch}
            for future in as_completed(futures):
                job=futures[future];symbol=job['symbol']
                try:results[symbol]={'status':'CALCULATED','shard':future.result(),'source_index':job['source_index']}
                except Exception as error:
                    failure={'schema':'v4.a_share.retained_history_batch_failure.v1','job':job,'key':job['key'],
                        'error':type(error).__name__+': '+str(error),**owner.FLAGS}
                    failure_ref=owner.save(job['failure'],failure)
                    results[symbol]={'status':'FAILED','failure':failure_ref};failures.append(symbol)
            owner.save(root/'progress.json',{'completed':len(results),'total':len(index['symbols']),
                       'failures':failures,'last_batch_start':start,**owner.FLAGS})
            if failures:
                remaining=chosen[start+workers:]+remaining;break
    if owner.sha(index_ref['path'])!=index_ref['sha256'] or owner.sha(prior_index_ref['path'])!=prior_index_ref['sha256'] or owner.sha(calendar_ref['path'])!=calendar_ref['sha256']:
        raise ValueError('HISTORY_BATCH_SOURCE_CHANGED_DURING_RUN')
    for job in remaining:results[job['symbol']]={'status':'PENDING','reason':'BATCH_LIMIT_OR_FAILURE_STOP'}
    counts={status:sum(x['status']==status for x in results.values()) for status in
            ('CALCULATED','REUSED_CHECKPOINT','REUSED_EXISTING_HISTORY','UNKNOWN','FAILED','PENDING')}
    status='PARTIAL' if failures or remaining else 'BATCH_COMPLETE_WITH_UNKNOWN' if counts['UNKNOWN'] else 'BATCH_COMPLETE'
    receipt={'schema':'v4.a_share.retained_history_batch.v1','status':status,
        'index':index_ref,'prior_index':prior_index_ref,'calendar':calendar_ref,
        'history_owner':{'path':str(Path(owner.__file__).resolve()),'sha256':expected_owner_sha256},
        'candidate_generation':index['candidate_generation'],'counts':counts,'results':results,
        'historical_PIT':False,**owner.FLAGS}
    digest=hashlib.sha256(owner.canonical(receipt)).hexdigest()
    path=root/'receipts'/(digest+'.json')
    if path.exists():
        if owner.load(owner.ref(path))!=receipt:raise ValueError('HISTORY_BATCH_RECEIPT_COLLISION')
        receipt_ref=owner.ref(path)
    else:receipt_ref=owner.save(path,receipt)
    return {'status':receipt['status'],'receipt':receipt_ref,'counts':counts}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('index','prior-index','calendar','output-root'):parser.add_argument('--'+name,required=True,type=Path)
    for name in ('index-sha256','prior-index-sha256','calendar-sha256','owner-sha256'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--workers',type=int,default=2);parser.add_argument('--max-new',type=int)
    parser.add_argument('--plan-only',action='store_true')
    parser.add_argument('--compact',action='store_true')
    args=parser.parse_args()
    references=[{'path':str(path.resolve()),'sha256':digest} for path,digest in
        ((args.index,args.index_sha256),(args.prior_index,args.prior_index_sha256),(args.calendar,args.calendar_sha256))]
    if args.plan_only:
        index,results,jobs=plan(*references,args.output_root,expected_owner_sha256=args.owner_sha256)
        value={'status':'PLAN_ONLY_NO_HISTORY_COMPUTED','total':len(index['symbols']),
            'existing':len(results),'pending':len(jobs),
            'counts':{s:sum(row['status']==s for row in results.values())
                      for s in ('REUSED_CHECKPOINT','REUSED_EXISTING_HISTORY','UNKNOWN','FAILED')}}
    else:
        value=run(*references,args.output_root,expected_owner_sha256=args.owner_sha256,
                  workers=args.workers,max_new=args.max_new,compact=args.compact)
    print(json.dumps(value,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
