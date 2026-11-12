"""Stage completion consumer. Default off; writes only derived isolated sidecars."""
from __future__ import annotations
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo
from infrastructure.report_evidence_index import SAFETY, canonical, digest


def sidecar_key(date, stage, selection_run, market):
    if not re.fullmatch(r'\d{8}', date) or not re.fullmatch(r'STAGE_[0-9_]+', stage):
        raise ValueError('INVALID_STAGE_SCOPE')
    if not re.fullmatch(r'run-[A-Za-z0-9_.-]+', selection_run) or market not in {'A_SHARE','HK_CONNECT'}:
        raise ValueError('INVALID_SELECTION_SCOPE')
    return digest(canonical([date, stage, selection_run, market]))


def _root(value, selection_root, data_root):
    root = Path(value).absolute()
    for source in (Path(selection_root).resolve(), Path(data_root).resolve()):
        if root.resolve() == source or source in root.resolve().parents or root.resolve() in source.parents:
            raise ValueError('SIDECAR_ROOT_MUST_BE_ISOLATED')
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError('SIDECAR_SYMLINK_REJECTED')
    return root


async def materialize(*, config, trade_date, stage_id, receipt, service, root):
    from stage_center.selection import SelectionStore
    from stage_center.contracts import STAGE_BY_ID
    if receipt.get('trade_date') != trade_date or receipt.get('stage_id') != stage_id:
        raise ValueError('RUNNER_SCOPE_MISMATCH')
    if any(receipt.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):
        raise ValueError('RUNNER_SAFETY_MISMATCH')
    if receipt.get('mode')=='BACKFILL' or receipt.get('dispatch_mode')=='BACKFILL' or receipt.get('historical_backfill') is True:
        raise ValueError('BACKFILL_NOT_FORMAL_STAGE_COMPLETION')
    store = SelectionStore(config['selection_root'])
    if not config.get('receipt_root'):
        raise ValueError('RUNNER_RECEIPT_ROOT_UNVERIFIED')
    receipt_path = Path(config['receipt_root']) / trade_date / stage_id / 'receipt.json'
    if receipt_path.is_symlink() or any(p.is_symlink() for p in receipt_path.parents):
        raise ValueError('RUNNER_RECEIPT_SYMLINK_REJECTED')
    receipt_raw = receipt_path.read_bytes()
    if json.loads(receipt_raw) != receipt:
        raise ValueError('PERSISTED_RUNNER_RECEIPT_MISMATCH')
    markets = list((receipt.get('markets') or {}).keys())
    cutoff = datetime.strptime(trade_date + STAGE_BY_ID[stage_id].cutoff, '%Y%m%d%H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Shanghai')).isoformat()
    outputs = []
    for market in markets:
        original = receipt['markets'][market]
        try:
            # Bind the real store, never a version-dependent display projection.
            envelope = store.read_verified(trade_date,stage_id,market)
            run = str(original.get('run_id') or '')
            verified = store._verify_run(trade_date,stage_id,market,run)
            expected = dict(trade_date=trade_date,stage_id=stage_id,market=market)
            if (verified['envelope'] != envelope or envelope.get('selection_mode')=='BACKFILL' or
                any(envelope.get(k)!=v for k,v in expected.items()) or
                any(original.get(k)!=envelope.get(k) for k in ('run_id','artifact_id')) or
                any(k in original and original[k]!=v for k,v in expected.items()) or
                any(k in original and original[k]!=envelope.get(k) for k in ('algorithm_sha256','raw_artifact_sha256'))):
                raise ValueError('ORIGINAL_SELECTION_BINDING_UNVERIFIED')
        except (OSError,ValueError,KeyError,TypeError):
            outputs.append(dict(market=market,status='EVIDENCE_GAP',reason='ORIGINAL_SELECTION_BINDING_UNVERIFIED'))
            continue
        key = sidecar_key(trade_date,stage_id,run,market)
        generation = None
        with service.index.connect() as db:
            generation = service.index.generation(db)
        binding = dict(original_selection_run=run,market=market,date=trade_date,stage=stage_id,
            cutoff=cutoff,cutoff_source='stage_center.contracts.StageSpec.cutoff',index_generation=generation,
            selection_root=str(store.root),selection_artifact_sha256=verified['artifact_sha256'],selection_manifest_sha256=verified['manifest_sha256'],
            selection_receipt_sha256=verified['receipt_sha256'],runner_receipt_observed_sha256=digest(receipt_raw),
            runner_receipt_verified=True, runner_verification_scope='PERSISTED_DECLARATION_AND_SELECTION_TRIO_ONLY_NOT_NATURAL_EXECUTION',
            runner_execution_status='PERSISTED_DECLARATION_AND_TRIO_BOUND_EXECUTION_UNVERIFIED')
        path=root/(key+'.json')
        if path.exists():
            old=json.loads(path.read_text())
            if old.get('binding') == binding:
                outputs.append(dict(market=market,status='REUSED',path=str(path)))
                continue
        evidence=[]
        for row in envelope['rows']:
            code=str(row['code'])
            result=await service.search(code,security=code,market='A' if market=='A_SHARE' else 'HK',
                mode='historical_evidence',as_of=cutoff,limit=3)
            evidence.append(dict(code=code,evidence=result))
        # Recheck the same input bytes after retrieval; sidecar never blesses a new run.
        if store.read_verified(trade_date,stage_id,market) != envelope:
            raise ValueError('SELECTION_CHANGED_DURING_SIDECAR')
        with service.index.connect() as db:
            if service.index.generation(db) != generation:
                raise ValueError('INDEX_GENERATION_CHANGED_DURING_SIDECAR')
        payload=dict(schema_version='v4.stage_report_evidence.v1',status='EXPLANATION_ONLY',binding=binding,
            rows=evidence,selection_scores_used=False,independent_corrob_count_basis='UNIQUE_ORIGINAL_PDF_SHA',**SAFETY)
        root.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.tmp');temp.write_text(canonical(payload));os.replace(temp,path)
        outputs.append(dict(market=market,status='MATERIALIZED',path=str(path)))
    return dict(status='SIDECAR_ONLY',items=outputs,**SAFETY)


def _materialize_worker(payload):
    from apps.api.v4_api.report_evidence_router import configured_service
    config=payload['config']
    data_root=os.environ.get('V4_RESEARCH_DATA_ROOT')
    sidecar_root=os.environ.get('V4_REPORT_EVIDENCE_SIDECAR_ROOT')
    if not data_root or not sidecar_root:
        return dict(status='EVIDENCE_GAP',reason='SIDECAR_NOT_CONFIGURED',**SAFETY)
    service=configured_service(data_root)
    if service is None or not service.index.path.is_file():
        return dict(status='EVIDENCE_GAP',reason='INDEX_NOT_CONFIGURED',**SAFETY)
    root=_root(sidecar_root,config['selection_root'],data_root)
    return asyncio.run(materialize(config=config,trade_date=payload['trade_date'],stage_id=payload['stage_id'],receipt=payload['receipt'],service=service,root=root))


def _job_id(payload):
    refs=payload['receipt'].get('markets')
    if not isinstance(refs,dict) or not refs:
        raise ValueError('RUNNER_MARKETS_REQUIRED')
    identities=[]
    for market,ref in sorted(refs.items()):
        sidecar_key(payload['trade_date'],payload['stage_id'],str(ref.get('run_id') or ''),market)
        identities.append([market,ref['run_id'],ref.get('artifact_id')])
    return digest(canonical([payload['trade_date'],payload['stage_id'],identities,digest(canonical(payload['receipt']))]))


def _job_io(root,create=True):
    from infrastructure.owned_io import SafeRoot
    io=SafeRoot(root/'jobs')
    if create:io.ensure_directory()
    return io


def _write_job_receipt(io,job_id,status,**fields):
    value=dict(schema_version='v4.report_evidence.completion_job.v1',job_id=job_id,status=status,
               observed_at=datetime.now(ZoneInfo('UTC')).isoformat(),**fields,**SAFETY)
    io.write_bytes(job_id+'.receipt.json',canonical(value).encode())
    return value


def _read_job_receipt(io,job_id):
    value=json.loads(io.read_bytes(job_id+'.receipt.json'))
    if not isinstance(value,dict) or value.get('job_id')!=job_id:
        raise ValueError('JOB_IDENTITY_MISMATCH')
    if value.get('status') not in ('SUBMITTED','RUNNING','COMPLETED','FAILED'):
        raise ValueError('JOB_STATE_UNKNOWN')
    return value


def _running_worker(active):
    """True=matching live worker, False=observed dead/other, None=unknown."""
    if not active:return False
    pid=active.get('pid');job_id=active.get('job_id')
    if type(pid) is not int or pid<=0 or not isinstance(job_id,str) or not re.fullmatch('[0-9a-f]{64}',job_id):
        return None
    try:
        command=subprocess.check_output(['ps','-ww','-p',str(pid),'-o','command='],text=True,stderr=subprocess.DEVNULL,timeout=2)
        return 'ops.run_report_evidence_sidecar_job' in command and job_id in command
    except subprocess.CalledProcessError:
        try:
            os.kill(pid,0)
        except ProcessLookupError:
            return False
        except OSError:
            return None
        return None
    except (OSError,subprocess.TimeoutExpired):
        return None


def on_stage_completed(*, config, trade_date, stage_id, receipt):
    if os.environ.get('V4_STAGE_REPORT_EVIDENCE_ENABLED') != '1':
        return dict(status='DISABLED',**SAFETY)
    # Submit only. A healthy cold owner read belongs to the short-lived worker,
    # never to the authoritative Stage completion lock or its next slot.
    from infrastructure.interprocess_lock import owned_interprocess_lock
    from infrastructure.owned_io import SafeRoot
    started=time.perf_counter()
    try:
        data_root=os.environ.get('V4_RESEARCH_DATA_ROOT')
        value=os.environ.get('V4_REPORT_EVIDENCE_SIDECAR_ROOT')
        if not data_root or not value or not config.get('receipt_root'):
            return dict(status='EVIDENCE_GAP',reason='SIDECAR_NOT_CONFIGURED',**SAFETY)
        root=_root(value,config['selection_root'],data_root)
        payload=dict(config={k:str(config[k]) for k in ('selection_root','receipt_root')},
                     trade_date=trade_date,stage_id=stage_id,receipt=receipt)
        job_id=_job_id(payload)
        original=SafeRoot(Path(config['receipt_root'])).read_bytes(f'{trade_date}/{stage_id}/receipt.json',max_bytes=1_048_576)
        if json.loads(original)!=receipt:
            raise ValueError('PERSISTED_RUNNER_RECEIPT_MISMATCH')
        io=_job_io(root)
        with owned_interprocess_lock(root/'jobs/submit.lock',timeout_seconds=.05,timeout_message='SIDECAR_SUBMIT_BUSY'):
            try:previous=_read_job_receipt(io,job_id)
            except FileNotFoundError:previous={}
            if previous.get('status')=='COMPLETED':
                return dict(status='REUSED',job_id=job_id,job_status='COMPLETED',callback_seconds=time.perf_counter()-started,**SAFETY)
            if previous.get('status')=='FAILED':
                return dict(status='EVIDENCE_GAP',job_id=job_id,reason='JOB_PREVIOUSLY_FAILED',callback_seconds=time.perf_counter()-started,**SAFETY)
            try:active=json.loads(io.read_bytes('active.json'))
            except FileNotFoundError:active={}
            live=_running_worker(active)
            if live is None:
                return dict(status='BUSY',job_id=job_id,job_status='LIVENESS_UNKNOWN',callback_seconds=time.perf_counter()-started,**SAFETY)
            if live:
                status='REUSED' if active.get('job_id')==job_id else 'BUSY'
                return dict(status=status,job_id=job_id,active_job_id=active.get('job_id'),job_status='IN_FLIGHT',callback_seconds=time.perf_counter()-started,**SAFETY)
            if previous.get('status') in {'SUBMITTED','RUNNING'}:
                # Same lock as the worker's RUNNING -> terminal writes. Never
                # wait on healthy materialization while holding Stage's lock.
                with owned_interprocess_lock(root/'jobs/consumer.lock',timeout_seconds=0,timeout_message='SIDECAR_CONSUMER_BUSY'):
                    previous=_read_job_receipt(io,job_id)
                    if previous.get('status')=='COMPLETED':
                        return dict(status='REUSED',job_id=job_id,job_status='COMPLETED',callback_seconds=time.perf_counter()-started,**SAFETY)
                    if previous.get('status')=='FAILED':
                        return dict(status='EVIDENCE_GAP',job_id=job_id,reason='JOB_PREVIOUSLY_FAILED',callback_seconds=time.perf_counter()-started,**SAFETY)
                    pid=previous.get('worker_pid') or (active.get('pid') if active.get('job_id')==job_id else None)
                    observed=_running_worker(dict(job_id=job_id,pid=pid))
                    if observed is not False:
                        return dict(status='BUSY',job_id=job_id,job_status='LIVENESS_UNKNOWN' if observed is None else 'IN_FLIGHT',callback_seconds=time.perf_counter()-started,**SAFETY)
                    _write_job_receipt(io,job_id,'FAILED',reason='WORKER_EXITED_WITHOUT_COMPLETION')
                    return dict(status='EVIDENCE_GAP',job_id=job_id,reason='WORKER_EXITED_WITHOUT_COMPLETION',**SAFETY)
            io.write_bytes(job_id+'.job.json',canonical(payload).encode())
            _write_job_receipt(io,job_id,'SUBMITTED')
            log_path=root/'jobs'/(job_id+'.worker.log')
            if log_path.is_symlink():raise ValueError('WORKER_LOG_SYMLINK_REJECTED')
            with log_path.open('ab',buffering=0) as log:
                child=subprocess.Popen([sys.executable,'-B','-m','ops.run_report_evidence_sidecar_job','--job-id',job_id],
                    stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,
                    cwd=Path.cwd(),env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            io.write_bytes('active.json',canonical(dict(job_id=job_id,pid=child.pid)).encode())
            return dict(status='SUBMITTED',job_id=job_id,worker_pid=child.pid,callback_seconds=time.perf_counter()-started,**SAFETY)
    except Exception as error:
        code=str(error) if re.fullmatch('[A-Z][A-Z0-9_]+',str(error)) else type(error).__name__
        status='BUSY' if code in {'SIDECAR_SUBMIT_BUSY','SIDECAR_CONSUMER_BUSY'} else 'EVIDENCE_GAP'
        return dict(status=status,job_id=locals().get('job_id'),reason=code,callback_seconds=time.perf_counter()-started,**SAFETY)


def consume_sidecar_job(job_id):
    from infrastructure.interprocess_lock import owned_interprocess_lock
    if not re.fullmatch('[0-9a-f]{64}',job_id):raise ValueError('INVALID_JOB_ID')
    value=os.environ.get('V4_REPORT_EVIDENCE_SIDECAR_ROOT')
    if not value:raise ValueError('SIDECAR_NOT_CONFIGURED')
    root=Path(value);io=_job_io(root,create=False)
    payload=json.loads(io.read_bytes(job_id+'.job.json',max_bytes=1_048_576))
    root=_root(root,payload['config']['selection_root'],os.environ['V4_RESEARCH_DATA_ROOT'])
    if _job_id(payload)!=job_id:raise ValueError('JOB_IDENTITY_MISMATCH')
    started=time.perf_counter()
    try:
        with owned_interprocess_lock(root/'jobs/consumer.lock',timeout_seconds=.05,timeout_message='SIDECAR_CONSUMER_BUSY'):
            previous=_read_job_receipt(io,job_id)
            if previous.get('status')=='COMPLETED':return dict(status='REUSED',job_id=job_id,**SAFETY)
            if previous.get('status')=='FAILED':return previous
            _write_job_receipt(io,job_id,'RUNNING',worker_pid=os.getpid())
            try:
                result=_materialize_worker(payload)
                success=result.get('status')=='SIDECAR_ONLY' and all(x.get('status') in {'MATERIALIZED','REUSED'} for x in result.get('items',[]))
                return _write_job_receipt(io,job_id,'COMPLETED' if success else 'FAILED',worker_pid=os.getpid(),wall_seconds=time.perf_counter()-started,result=result)
            except Exception as error:
                code=str(error) if re.fullmatch('[A-Z][A-Z0-9_]+',str(error)) else type(error).__name__
                return _write_job_receipt(io,job_id,'FAILED',worker_pid=os.getpid(),wall_seconds=time.perf_counter()-started,reason=code)
    except ValueError as error:
        if str(error)=='SIDECAR_CONSUMER_BUSY':
            return dict(status='BUSY',job_id=job_id,reason='SINGLE_CONSUMER_IN_FLIGHT',**SAFETY)
        raise


def read_sidecar(root, *, date, stage, selection_run, market):
    key=sidecar_key(date,stage,selection_run,market)
    if not root:
        return dict(status='EVIDENCE_GAP',reason='SIDECAR_NOT_CONFIGURED',**SAFETY)
    path=Path(root)/(key+'.json')
    if not path.is_file():
        return dict(status='EVIDENCE_GAP',reason='SIDECAR_NOT_MATERIALIZED',**SAFETY)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('SIDECAR_SYMLINK_REJECTED')
    value=json.loads(path.read_text())
    binding=value.get('binding',{})
    if any(binding.get(k)!=v for k,v in [('date',date),('stage',stage),('original_selection_run',selection_run),('market',market)]):
        raise ValueError('SIDECAR_BINDING_MISMATCH')
    from stage_center.selection import SelectionStore
    selected = SelectionStore(binding['selection_root'])._verify_run(date,stage,market,selection_run)
    for field, original in [('artifact_sha256','selection_artifact_sha256'),('manifest_sha256','selection_manifest_sha256'),('receipt_sha256','selection_receipt_sha256')]:
        if selected[field] != binding[original]:
            raise ValueError('ORIGINAL_SELECTION_SHA_CHANGED')
    # Do not serve stale original text merely because the sidecar is persisted.
    from apps.api.v4_api.report_evidence_router import configured_service
    service=configured_service(os.environ.get('V4_RESEARCH_DATA_ROOT',''))
    if service is None:
        return dict(status='EVIDENCE_GAP',reason='INDEX_NOT_CONFIGURED',**SAFETY)
    with service.index.connect() as db:
        if service.index.generation(db)!=binding.get('index_generation'):
            return dict(status='EVIDENCE_GAP',reason='INDEX_GENERATION_CHANGED',**SAFETY)
    for row in value.get('rows',[]):
        for hit in row.get('evidence',{}).get('hits',[]):
            for cid in hit.get('merged_chunk_ids', [hit['chunk_id']]):
                service.read(cid)
    return value
