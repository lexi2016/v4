"""Full-universe isolated recovery ledger, 4 processes (2 on observed pressure).

Each stock must close its original Par prefix to the requested date. Existing
original foundation/N/state51 are reused; only hidden native state is initialized.
Missing histories and exceptions are recorded per stock, never replaced by Mac.
"""
import argparse,concurrent.futures,datetime,hashlib,json,multiprocessing,os,re,shutil,subprocess,sys,time
from pathlib import Path
from bootstrap import initialize_from_original
from native_state import encode,decode
from recovery import Kernel
from source_prefix import Loader,MissingSource,BASIS_KEYS
from environment import observed_environment
from continuation_checks import runtime_identity,check_resume,read_receipt,check_saved_hashes,check_daily_parent,check_daily_result

_WORKER=None
_RESOURCE_CACHE={}


def resources(output=None):
    key=str(output)
    if key in _RESOURCE_CACHE and time.monotonic()-_RESOURCE_CACHE[key][0]<5:return dict(_RESOURCE_CACHE[key][1])
    available=None;pressure=None;method='UNKNOWN'
    try:
        import psutil
        available=psutil.virtual_memory().available;method='PSUTIL_AVAILABLE'
    except ImportError:
        if Path('/proc/meminfo').exists():
            available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024;method='LINUX_MEMAVAILABLE'
    if sys.platform=='darwin':
        if available is None:
            vm=subprocess.run(['/usr/bin/vm_stat'],capture_output=True,text=True,check=True).stdout
            page_size=int(re.search(r'page size of (\d+) bytes',vm).group(1));pages={name:int(re.search(r'^'+re.escape(name)+r':\s+(\d+)',vm,re.M).group(1)) for name in ('Pages free','Pages inactive','Pages speculative')}
            available=sum(pages.values())*page_size;method='MAC_FREE_PLUS_INACTIVE_PLUS_SPECULATIVE_ESTIMATE'
        p=subprocess.run(['/usr/sbin/sysctl','-n','kern.memorystatus_vm_pressure_level'],capture_output=True,text=True)
        if p.returncode==0:pressure=int(p.stdout.strip())
    result=dict(observed_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),cpu_count=os.cpu_count(),available_memory_method=method,output_disk_free_bytes=shutil.disk_usage(output).free if output else None,available_memory_bytes=available,memory_pressure_level=pressure,pressure_observed=(available is not None and available<24*1024**3) or (pressure is not None and pressure>=2))
    _RESOURCE_CACHE[key]=(time.monotonic(),result);return dict(result)


def initialize_worker(config):
    global _WORKER
    if runtime_identity(config.get('environment_binding',{}))!=runtime_identity(observed_environment()):raise ValueError('LOCAL_RUNTIME_BINDING_CHANGED')
    kernel=Kernel(config['par'],config['latest'],config['dependencies']);loader=Loader(config['par'],config['catalog'],config['index']);_WORKER=(kernel,loader,config)


def save_state(root,state):
    blob=encode(state);sha=hashlib.sha256(blob).hexdigest();path=root/(state['symbol']+'_'+state['asof']+'.recovered.bin')
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('IMMUTABLE_RECOVERY_STATE_CONFLICT:'+str(path))
    else:
        temporary=path.with_name(path.name+'.pending.'+str(os.getpid()));temporary.write_bytes(blob);os.replace(temporary,path)
    return dict(path=str(path),sha256=sha,asof=state['asof'],bytes=len(blob),mtime_ns=path.stat().st_mtime_ns,product_kind='NEW_RECOVERY_PRODUCT_NOT_HISTORIC_ORIGINAL')


def compact(result,receipt_path,reused=False):
    return {k:result[k] for k in ('symbol','status','physical_asof','counters','seconds') if k in result} | dict(receipt_path=str(receipt_path),receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),states=result.get('states',[]),reused_completed_checkpoint=reused)


def work(job):
    kernel,loader,config=_WORKER;started=time.monotonic();symbol=job['symbol'];root=Path(config['states']);record_path=root/(symbol+'.receipt.json')
    try:
        if job.get('event_date')!=config['target'] or not job.get('continuation_ref'):raise MissingSource('NO_ORIGINAL_TARGET_CONTINUATION:'+str(job.get('event_date')))
        previous=None
        if record_path.exists():
            previous=read_receipt(record_path,job.get('_expected_receipt_sha256'))
            completed=check_resume(previous,job,config,kernel.code_binding);check_saved_hashes(previous)
            if completed==len(job.get('advance_refs',[])):return compact(previous,record_path,True)
            state=decode(Path(previous['states'][-1]['path']).read_bytes())
            if state['code_binding']!=kernel.code_binding or state['asof']!=previous['physical_asof'] or state['symbol']!=symbol:raise ValueError('RESUME_STATE_BOUNDARY')
            states=list(previous['states']);advances=list(previous.get('advances',[]));consumed=list(previous.get('requested_advances',[]))
            parent_ref=(state.get('daily_source_refs') or [job['continuation_ref']])[-1];parent_bundle=loader.bundle(parent_ref);source_binding=previous['source_binding']
        else:
            document=loader.load(job['continuation_ref'],config['target'])
            if document['bundle']['symbol']!=symbol or document['context']['symbol']!=symbol:raise ValueError('JOB_SOURCE_SYMBOL_MISMATCH')
            state=initialize_from_original(kernel,document);states=[save_state(root,state)];advances=[];consumed=[];parent_bundle=document['bundle'];parent_ref=job['continuation_ref'];source_binding=document['source_binding']
        def persist():
            result=dict(symbol=symbol,status='COMPLETE',physical_asof=state['asof'],source_ref=job['continuation_ref'],requested_advances=list(consumed),states=list(states),counters=state['counters'],advances=list(advances),code_binding=kernel.code_binding,driver_binding=config['driver_binding'],environment_binding=config['environment_binding'],source_binding=source_binding,RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,seconds=time.monotonic()-started)
            if record_path.exists():
                old=record_path.read_bytes();old_asof=json.loads(old)['physical_asof'];archive=root/(symbol+'_'+old_asof+'.receipt.json')
                if not archive.exists():archive.write_bytes(old)
            data=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode();temporary=record_path.with_suffix('.pending');temporary.write_bytes(data);os.replace(temporary,record_path)
            return result
        if previous is None:persist()
        for ref in job.get('advance_refs',[])[len(consumed):]:
            child=loader.bundle(ref);check_daily_parent(parent_bundle,child,symbol,parent_ref,state['count']+1)
            rows=list(state['original_rows']);loader.append_day(rows,child['daily51'],symbol)
            result,state,audit=kernel.step(state,rows[-1]);check_daily_result(state,child);state['original_state51']=child['state51']
            state.setdefault('daily_source_refs',[]).append(ref);states.append(save_state(root,state));advances.append(dict(asof=state['asof'],execution=audit));consumed.append(ref);parent_bundle=child;parent_ref=ref
            persist()
        return compact(read_receipt(record_path),record_path)
    except Exception as error:
        partial=compact(read_receipt(record_path),record_path) if record_path.exists() else {}
        return dict(partial,symbol=symbol,status='MISSING_SOURCE' if isinstance(error,MissingSource) else 'ERROR',error_type=type(error).__name__,error=str(error),seconds=time.monotonic()-started,production_allowed=False)


def main(a):
    config={k:str(getattr(a,k)) for k in ('par','latest','dependencies','catalog','index','states')};config['target']=a.target;config['code_binding']=Kernel(config['par'],config['latest'],config['dependencies']).code_binding;config['environment_binding']=observed_environment();config['driver_binding']={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('batch_restore.py','bootstrap.py','source_prefix.py','environment.py','continuation_checks.py')}
    prior_raw=a.prior_catalog.read_bytes();catalog=json.loads(prior_raw);prior_sha=hashlib.sha256(prior_raw).hexdigest();jobs=catalog['latest_selections']
    if len(jobs)!=5575 or len({r['symbol'] for r in jobs})!=5575:raise ValueError('EXACT5575_SCOPE_REQUIRED')
    additions=json.loads(a.advances.read_bytes()) if a.advances else {}
    jobs=[{**job,'advance_refs':additions.get(job['symbol'],[])} for job in jobs]
    a.states.mkdir(parents=True,exist_ok=True);a.output.mkdir(parents=True,exist_ok=True)
    # Full-range ledger exists before the first submission; no hidden truncation.
    ledger={job['symbol']:dict(symbol=job['symbol'],status='PENDING') for job in jobs};resource_start=resources(a.states)
    if resource_start['output_disk_free_bytes']<24*1024**3:raise RuntimeError('OUTPUT_DISK_RESERVE_24G_NOT_AVAILABLE')
    workers=2 if resource_start['pressure_observed'] else 4
    pending=list(jobs);completed=0;resource_events=[dict(event='START',workers=workers,**resource_start)]
    path=a.output/'BATCH_LEDGER.json';last_snapshot=time.monotonic()
    if path.exists():
        previous=json.loads(path.read_bytes())
        if previous.get('prior_catalog_sha256')==prior_sha and previous.get('target')==a.target:
            by_symbol={job['symbol']:job for job in jobs}
            for record in previous['records']:
                job=by_symbol.get(record['symbol'])
                if not job or not record.get('receipt_path') or not record.get('receipt_sha256'):continue
                job['_expected_receipt_sha256']=record['receipt_sha256']
                if record.get('status')!='COMPLETE':continue
                try:
                    receipt=read_receipt(record['receipt_path'],record['receipt_sha256'])
                    consumed=check_resume(receipt,job,config,config['code_binding']);check_saved_hashes(receipt)
                    if consumed!=len(job.get('advance_refs',[])):continue
                except (OSError,ValueError,KeyError):continue
                ledger[record['symbol']]=compact(receipt,Path(record['receipt_path']),True);completed+=1
            pending=[job for job in jobs if ledger[job['symbol']]['status']!='COMPLETE']
            resource_events.append(dict(event='MATCHING_KERNEL_SOURCE_JOB_AND_SHA_COMPLETE_ITEMS_REUSED',count=completed))
    def snapshot():
        counts={}
        for row in ledger.values():counts[row['status']]=counts.get(row['status'],0)+1
        result=dict(schema='par5575.native_recovery.ledger.v1',target=a.target,scope_count=5575,prior_catalog_sha256=prior_sha,code_binding=config['code_binding'],driver_binding=config['driver_binding'],environment_binding=config['environment_binding'],counts=counts,workers=workers,resources=resource_events,records=list(ledger.values()),production_allowed=False)
        temporary=path.with_suffix('.pending');temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');os.replace(temporary,path)
    snapshot()
    while pending:
        # On pressure, drain healthy work then recreate only this local pool at2.
        shrink=False
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),initializer=initialize_worker,initargs=(config,)) as pool:
            active={}
            while pending or active:
                while pending and len(active)<workers and not shrink:
                    job=pending.pop(0);active[pool.submit(work,job)]=job['symbol']
                if not active:break
                done,_=concurrent.futures.wait(active,return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    symbol=active.pop(future)
                    try:result=future.result()
                    except Exception as error:result=dict(symbol=symbol,status='WORKER_ERROR',error_type=type(error).__name__,error=str(error),production_allowed=False)
                    ledger[symbol]=result;completed+=1
                if workers==4 and resources(a.states)['pressure_observed']:
                    shrink=True;resource_events.append(dict(event='DRAIN_TO2',completed=completed,**resources(a.states)))
                if completed%100==0 or time.monotonic()-last_snapshot>30:
                    snapshot();last_snapshot=time.monotonic()
                if completed%100==0:print(json.dumps(dict(completed=completed,total=5575,pending=len(pending),workers=workers)),flush=True)
        if shrink:workers=2
    snapshot();print(json.dumps(dict(ledger=str(path),scope_count=5575,completed=completed,status='ALL_ITEMS_RECORDED')),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('par','latest','dependencies','catalog','index','states','prior-catalog','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--target',default='20261109');p.add_argument('--advances',type=Path);main(p.parse_args())
