"""Advance SHA-bound new recovery checkpoints; never initialize history again."""
import argparse,concurrent.futures,hashlib,json,multiprocessing,time
from pathlib import Path
import batch_restore
from batch_restore import initialize_worker,resources,save_state
from native_state import decode
from source_prefix import BASIS_KEYS,MissingSource
from environment import observed_environment
from continuation_checks import runtime_identity,check_daily_parent,check_daily_result


def advance(job):
    kernel,loader,config=batch_restore._WORKER;symbol=job['symbol'];states=[];receipt_ref=job['receipt'];last_receipt=None
    try:
        blob=Path(receipt_ref['path']).read_bytes()
        if hashlib.sha256(blob).hexdigest()!=receipt_ref['sha256']:raise ValueError('EXTERNAL_RECEIPT_SHA')
        previous=json.loads(blob)
        if previous['symbol']!=symbol or previous['code_binding']!=kernel.code_binding or runtime_identity(previous.get('environment_binding',{}))!=runtime_identity(observed_environment()):raise ValueError('CHECKPOINT_CODE_SYMBOL')
        saved=previous['states'][-1];blob=Path(saved['path']).read_bytes()
        if hashlib.sha256(blob).hexdigest()!=saved['sha256']:raise ValueError('EXTERNAL_STATE_SHA')
        state=decode(blob)
        if state['code_binding']!=kernel.code_binding or state['asof']!=previous['physical_asof']:raise ValueError('CHECKPOINT_BOUNDARY')
        parent_ref=(state.get('daily_source_refs') or [state['source_binding']['original_bundle_ref']])[-1]
        parent=loader.bundle(parent_ref)
        if not job['advance_refs']:raise MissingSource('NO_ORIGINAL_NEXT_DAY_REFERENCES')
        for ref in job['advance_refs']:
            child=loader.bundle(ref)
            check_daily_parent(parent,child,symbol,parent_ref,state['count']+1)
            rows=list(state['original_rows']);loader.append_day(rows,child['daily51'],symbol)
            result,state,audit=kernel.step(state,rows[-1]);check_daily_result(state,child);state['original_state51']=child['state51'];state.setdefault('daily_source_refs',[]).append(ref)
            saved=save_state(Path(config['states']),state);states.append(saved)
            new=dict(previous,physical_asof=state['asof'],states=previous['states']+[saved],counters=state['counters'],requested_advances=previous.get('requested_advances',[])+[ref],advances=previous.get('advances',[])+[dict(asof=state['asof'],execution=audit)],advance_driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
            path=Path(config['states'])/(symbol+'_'+state['asof']+'.receipt.json');data=(json.dumps(new,ensure_ascii=False,indent=2)+'\n').encode()
            if path.exists() and path.read_bytes()!=data:raise ValueError('IMMUTABLE_ADVANCE_RECEIPT_CONFLICT')
            if not path.exists():path.write_bytes(data)
            last_receipt=dict(path=str(path),sha256=hashlib.sha256(data).hexdigest());previous=new;parent_ref=ref;parent=child
        return dict(symbol=symbol,status='COMPLETE',physical_asof=state['asof'],receipt=last_receipt,new_states=states,historical_initializations=0,production_allowed=False)
    except Exception as error:
        return dict(symbol=symbol,status='PARTIAL' if last_receipt else 'MISSING_SOURCE' if isinstance(error,MissingSource) else 'ERROR',receipt=last_receipt,new_states=states,error_type=type(error).__name__,error=str(error),historical_initializations=0,production_allowed=False)


def main(a):
    receipts=json.loads(a.receipt_index.read_bytes());advances=json.loads(a.advance_index.read_bytes());jobs=[dict(symbol=s,receipt=r,advance_refs=advances.get(s,[])) for s,r in receipts.items()]
    config={k:str(getattr(a,k)) for k in ('par','latest','dependencies','catalog','index','states')};config['environment_binding']=observed_environment();a.states.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
    info=resources(a.states)
    if info['output_disk_free_bytes']<24*1024**3:raise RuntimeError('OUTPUT_DISK_RESERVE_24G_NOT_AVAILABLE')
    workers=2 if info['pressure_observed'] else 4;records=[];pending=list(jobs);events=[info];last_snapshot=time.monotonic()
    def snapshot():
        result=dict(status='ALL_ITEMS_RECORDED' if not pending and len(records)==len(jobs) else 'RUNNING',workers=workers,resources=events,count=len(jobs),completed=len(records),records=records,production_allowed=False)
        path=a.output/'ADVANCE_LEDGER.json';temporary=path.with_suffix('.pending');temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)
    snapshot()
    while pending:
        shrink=False
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),initializer=initialize_worker,initargs=(config,)) as pool:
            active={}
            while pending or active:
                while pending and len(active)<workers and not shrink:
                    job=pending.pop(0);active[pool.submit(advance,job)]=job['symbol']
                if not active:break
                done,_=concurrent.futures.wait(active,return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    symbol=active.pop(future)
                    try:records.append(future.result())
                    except Exception as error:records.append(dict(symbol=symbol,status='WORKER_ERROR',error=str(error),production_allowed=False))
                current=resources(a.states)
                if workers==4 and current['pressure_observed']:shrink=True;events.append(dict(event='DRAIN_TO2',**current))
                if len(records)%100==0 or time.monotonic()-last_snapshot>30:snapshot();last_snapshot=time.monotonic()
        if shrink:workers=2
    snapshot();print(json.dumps(dict(count=len(jobs),status='ALL_ITEMS_RECORDED')))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('par','latest','dependencies','catalog','index','states','receipt-index','advance-index','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
