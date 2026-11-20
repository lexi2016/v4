"""Append-only diagnostic retention at the existing collector boundary."""
from __future__ import annotations
import contextvars, hashlib, json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from infrastructure.owned_io import SafeRoot
from stage_center.contracts import SAFETY_FLAGS

_REQUEST_CONTEXT=contextvars.ContextVar('stage_collector_raw_request',default=None)

def _wall(): return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
def retained_collector_call(collector, plan, market, raw_root):
    """Retain returned rows before filtering, including invalid and zero rows.

    This is evidence of the actual collector call, not proof that a transport
    ran or that any returned value was valid/available at the original cutoff.
    """
    started=_wall();result=None;error=None
    token=_REQUEST_CONTEXT.set({'root':str(raw_root),'trade_date':plan.trade_date,
        'stage_id':plan.stage_id,'market':market,'requested_codes':list(plan.codes_for(market)),
        'candidate_current_sha256':plan.candidate_input.current_sha256})
    try:
        result=collector(plan,market)
        return result
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
        raise
    finally:
        _REQUEST_CONTEXT.reset(token)
        response=None if result is None else {key:getattr(result,key,None) for key in
            ('source_id','status','rows','requested_rows','missing_symbols','cannot_confirm','source_evidence')}
        record={'schema_version':'stage_center.collector_request_capture.v1',
            'trade_date':plan.trade_date,'stage_id':plan.stage_id,'market':market,
            'requested_codes':list(plan.codes_for(market)),
            'candidate_current_sha256':plan.candidate_input.current_sha256,
            'universe_binding_sha256':getattr(plan.universe_bindings.get(market),'sha256',None),
            'capture_started_at':started,'capture_finished_at':_wall(),
            'response':response,'error':error,'authorizes_selection':False,
            'transport_execution_verified':False,**SAFETY_FLAGS}
        raw=(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        if len(raw)>64*1024*1024:raise ValueError('COLLECTOR_DIAGNOSTIC_CAPTURE_TOO_LARGE')
        digest=hashlib.sha256(raw).hexdigest()
        relative=f'.collector_requests/{plan.trade_date}/{plan.stage_id}/{market}/{digest}.json'
        owned=SafeRoot(Path(raw_root))
        try:owned.write_bytes(relative,raw,require_absent=True)
        except FileExistsError:
            if owned.read_bytes(relative,max_bytes=64*1024*1024)!=raw:
                raise ValueError('COLLECTOR_CAPTURE_IMMUTABLE_CONFLICT')


def retained_process_call(process_runner,command,**kwargs):
    """Keep the existing process return before the shared bridge aggregates it.

    Never store inherited environment variables. Child arguments retain the
    exact per-batch request while requested_codes identifies the full plan.
    """
    scope=_REQUEST_CONTEXT.get()
    if scope is None:return process_runner(command,**kwargs)
    started=_wall();result=None;error=None;stdout=None;stderr=None
    try:
        result=process_runner(command,**kwargs)
        stdout=getattr(result,'stdout',None);stderr=getattr(result,'stderr',None)
        return result
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
        stdout=getattr(exc,'stdout',getattr(exc,'output',None));stderr=getattr(exc,'stderr',None)
        raise
    finally:
        def returned_bytes(value):
            if value is None:return b'','NOT_RETURNED'
            if isinstance(value,bytes):return value,'RETURNED_BYTES'
            if isinstance(value,str):return value.encode('utf-8','surrogatepass'),'RETURNED_TEXT_UTF8_SURROGATEPASS'
            raise TypeError('PROCESS_CAPTURE_RETURN_TYPE_UNSUPPORTED')
        out,out_kind=returned_bytes(stdout);err,err_kind=returned_bytes(stderr)
        record={k:v for k,v in scope.items() if k!='root'}
        oversized=len(out)>64*1024*1024 or len(err)>64*1024*1024
        record.update(schema_version='stage_center.process_response_capture.v1',
            child_command=list(command),child_cwd=str(kwargs.get('cwd','')),
            capture_started_at=started,capture_finished_at=_wall(),
            returncode=getattr(result,'returncode',None),error=error,
            stdout_sha256=hashlib.sha256(out).hexdigest(),stdout_size=len(out),stdout_representation=out_kind,
            stderr_sha256=hashlib.sha256(err).hexdigest(),stderr_size=len(err),stderr_representation=err_kind,
            evidence_status='CANNOT_CONFIRM_FULL_RESPONSE_NOT_RETAINED' if oversized else 'RETURNED_PROCESS_OUTPUT_RETAINED',
            authorizes_selection=False,**SAFETY_FLAGS)
        raw=(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
        digest=hashlib.sha256(raw).hexdigest()
        prefix=f'.process_requests/{scope["trade_date"]}/{scope["stage_id"]}/{scope["market"]}/{digest}'
        owned=SafeRoot(Path(scope['root']))
        for relative,data in [('request.json',raw),*(() if oversized else (('stdout.bin',out),('stderr.bin',err)))]:
            try:owned.write_bytes(prefix+'/'+relative,data,require_absent=True)
            except FileExistsError:
                if owned.read_bytes(prefix+'/'+relative,max_bytes=64*1024*1024)!=data:
                    raise ValueError('PROCESS_CAPTURE_IMMUTABLE_CONFLICT')
        if oversized:raise ValueError('CANNOT_CONFIRM_FULL_RESPONSE_NOT_RETAINED')
