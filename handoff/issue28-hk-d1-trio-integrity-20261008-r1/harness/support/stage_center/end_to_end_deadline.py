"""One monotonic five-second budget, phase evidence and cooperative write gates.

An entry timestamp is only a lower bound (interpreter startup precedes it).
A parent watchdog must independently measure before Popen through final receipt
and process exit. This module cannot interrupt a blocking native/provider call;
checkpoint enforcement alone is explicitly not a hard wall-clock guarantee.
There is no scheduler, collector, secondary writer or automatic retry here.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

BUDGET_NS = 5_000_000_000

class DeadlineExceeded(ValueError):
    pass

def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

class Trace:
    def __init__(self, *, entry_ns: int, entry_wall_ns: int, parent_start_ns: int | None=None,
                 policy: str='observe', trace_path: Path | None=None,
                 mono: Callable[[],int]=time.monotonic_ns, wall: Callable[[],int]=time.time_ns):
        if policy not in {'observe','enforce'}: raise ValueError('DEADLINE_POLICY_INVALID')
        if type(entry_ns) is not int or entry_ns<=0: raise ValueError('ENTRY_ANCHOR_INVALID')
        if parent_start_ns is not None and (type(parent_start_ns) is not int or not 0<parent_start_ns<=entry_ns):
            raise ValueError('PARENT_ANCHOR_INVALID')
        self.entry_ns=entry_ns;self.entry_wall_ns=entry_wall_ns
        self.start_ns=parent_start_ns if parent_start_ns is not None else entry_ns
        self.parent_supplied=parent_start_ns is not None;self.policy=policy;self.mono=mono;self.wall=wall
        self.events=[];self.writes_possible=False;self.final=None;self.due_wall_ns=None
        self._fd=None;self._last_ns=entry_ns
        if trace_path is not None:
            path=Path(trace_path)
            if path.is_symlink() or any(v.is_symlink() for v in path.parents):raise ValueError('TRACE_SYMLINK')
            self._fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        self.event('ENTRY_ANCHOR',entry_monotonic_ns=entry_ns,entry_wall_ns=entry_wall_ns,
                   start_scope='PARENT_SUPPLIED_REQUIRES_PARENT_VERIFICATION' if self.parent_supplied else 'ENTRY_LOWER_BOUND',budget_ns=BUDGET_NS)
    def event(self,phase: str,**fields: Any) -> dict[str,Any]:
        n=self.mono();w=self.wall()
        if n<self._last_ns:raise ValueError('MONOTONIC_CLOCK_REVERSED')
        self._last_ns=n
        row={'seq':len(self.events),'phase':phase,'monotonic_ns':n,'wall_time_utc':datetime.fromtimestamp(w/1e9,timezone.utc).isoformat(),
             'wall_time_ns':w,'elapsed_ns':n-self.start_ns,**fields}
        self.events.append(row)
        if self._fd is not None:
            data=(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
            while data:
                size=os.write(self._fd,data)
                if size<=0:raise OSError('TRACE_SHORT_WRITE')
                data=data[size:]
            os.fsync(self._fd)
        return row
    def checkpoint(self,phase: str,**fields: Any) -> dict[str,Any]:
        row=self.event(phase,**fields)
        if row['elapsed_ns']>BUDGET_NS and self.policy=='enforce':
            raise DeadlineExceeded(f'END_TO_END_5S_EXCEEDED:{phase}:{row["elapsed_ns"]}')
        return row
    def begin_write(self,phase: str,**fields: Any) -> None:
        self.checkpoint(phase+'_START',**fields)
        self.writes_possible=True
    def end_write(self,phase: str,**fields: Any) -> None:
        self.event(phase+'_COMPLETED',**fields)
    def due(self,scheduled: datetime | None,**fields: Any) -> None:
        if scheduled is not None:
            if scheduled.tzinfo is None or scheduled.utcoffset() is None:raise ValueError('DUE_TZ_REQUIRED')
            self.due_wall_ns=int(scheduled.timestamp()*1e9)
        self.event('DUE_ANCHOR',scheduled_at=scheduled.isoformat() if scheduled else None,**fields)
    def final_receipt(self,path: Path,*,status: str,durable: bool) -> None:
        record=self.event('FINAL_RECEIPT_COMPLETED',receipt_path=str(path),status=status,
                          receipt_sha256=sha_file(path) if durable else None,receipt_durable=durable)
        self.final=record
    def summary(self) -> dict[str,Any]:
        elapsed=self.mono()-self.start_ns
        if elapsed<0:raise ValueError('MONOTONIC_CLOCK_REVERSED')
        over=elapsed>BUDGET_NS
        return {'schema_version':'stage_center.end_to_end_timing.v1','budget_ns':BUDGET_NS,'policy':self.policy,
                'measurement_scope':'PARENT_SUPPLIED_REQUIRES_PARENT_VERIFICATION' if self.parent_supplied else 'ENTRY_LOWER_BOUND',
                'elapsed_ns':elapsed,'budget_status':'EXCEEDED' if over else 'WITHIN_OBSERVED_INTERVAL',
                'deadline_met':False if over else None, # Only the independent parent may close its measured bound.
                'business_success_verified':False,'natural_verified':False,
                'business_write_may_have_occurred':self.writes_possible,
                'blocking_call_hard_timeout_covered':False,'final_receipt':self.final,
                'due_to_final_receipt_wall_ns':(self.final['wall_time_ns']-self.due_wall_ns) if self.final and self.due_wall_ns is not None else None,
                'due_metric_scope':'WALL_CLOCK_OBSERVATION_NOT_SYNTHETIC_EVALUATED_AT_OR_MONOTONIC_DURATION',
                'events':list(self.events)}
    def close(self):
        if self._fd is not None:os.close(self._fd);self._fd=None

_CURRENT: Trace | None = None

def set_current(trace: Trace | None) -> None:
    global _CURRENT
    _CURRENT=trace

def install(entry_ns: int,entry_wall_ns: int) -> Trace:
    global _CURRENT
    parent=os.environ.get('V4_STAGE_PARENT_START_NS')
    path=os.environ.get('V4_STAGE_TRACE_PATH')
    _CURRENT=Trace(entry_ns=entry_ns,entry_wall_ns=entry_wall_ns,parent_start_ns=int(parent) if parent else None,
                   policy=os.environ.get('V4_STAGE_DEADLINE_POLICY','observe'),trace_path=Path(path) if path else None)
    return _CURRENT

def checkpoint(phase: str,**fields: Any) -> None:
    if _CURRENT:_CURRENT.checkpoint(phase,**fields)

def event(phase: str,**fields: Any) -> None:
    if _CURRENT:_CURRENT.event(phase,**fields)

def due(scheduled: datetime | None,**fields: Any) -> None:
    if _CURRENT:_CURRENT.due(scheduled,**fields)

def begin_write(phase: str,**fields: Any) -> None:
    if _CURRENT:_CURRENT.begin_write(phase,**fields)

def end_write(phase: str,**fields: Any) -> None:
    if _CURRENT:_CURRENT.end_write(phase,**fields)

def summary() -> dict[str,Any] | None:
    return _CURRENT.summary() if _CURRENT else None

def failure_fields(error: Exception) -> dict[str,Any]:
    if not isinstance(error,DeadlineExceeded):return {}
    return {'first_failed_layer':'END_TO_END_DEADLINE','deadline_status':'EXCEEDED',
            'partial_commit_possible':bool(_CURRENT and _CURRENT.writes_possible),'deadline_budget_ns':BUDGET_NS}

def before_receipt(payload: Mapping[str,Any]) -> dict[str,Any]:
    result=dict(payload)
    if not _CURRENT:return result
    _CURRENT.event('RECEIPT_WRITE_START',status=result.get('status'))
    if _CURRENT.policy=='enforce' and _CURRENT.mono()-_CURRENT.start_ns>BUDGET_NS:
        result.update(status='PARTIAL_COMMIT_RETRY_REQUIRED' if result.get('write_performed') else 'CANNOT_CONFIRM',
                      first_failed_layer='END_TO_END_DEADLINE',deadline_status='EXCEEDED',deadline_budget_ns=BUDGET_NS,
                      partial_commit_possible=_CURRENT.writes_possible,error='END_TO_END_5S_EXCEEDED_BEFORE_RECEIPT')
        if 'node_outcome' in result:result['node_outcome']='TRANSIENT'
    return result

def receipt_written(path: Path,result: Mapping[str,Any]) -> None:
    if not _CURRENT:return
    # Existing writer fsyncs the temporary file and atomically replaces it.
    # Complete directory persistence before claiming the receipt endpoint.
    fd=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(fd)
    finally:os.close(fd)
    _CURRENT.event('RECEIPT_WRITE_COMPLETED',receipt_path=str(path),receipt_sha256=sha_file(path),status=result.get('status'),receipt_durable=True)

def complete_receipt(path: Path,result: Mapping[str,Any],*,
                     rewrite: Callable[[Mapping[str,Any]],Mapping[str,Any]] | None=None
                     ) -> dict[str,Any]:
    completed=dict(result)
    if not _CURRENT:return completed
    # Also works for an explicitly supplied original writer in an isolated test.
    with path.open('rb') as stream:os.fsync(stream.fileno())
    fd=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(fd)
    finally:os.close(fd)
    _CURRENT.final_receipt(path,status=str(completed.get('status') or 'CANNOT_CONFIRM'),durable=True)
    elapsed=_CURRENT.mono()-_CURRENT.start_ns
    pending_path=(pending_receipt_marker(path)
                  if rewrite is not None and is_stage_node_receipt(path) else None)
    has_pending=bool(pending_path and (pending_path.exists() or pending_path.is_symlink()))
    if has_pending and _CURRENT.policy!='enforce':
        completed=_pending_result(completed,pending_path,'OBSERVE_REQUIRES_ENFORCE_RECOVERY')
        if isinstance(result,dict):result.update(completed)
        _CURRENT.event('DEADLINE_RECEIPT_PENDING_UNRESOLVED',receipt_path=str(path),status=completed.get('status'))
        return completed
    if elapsed<=BUDGET_NS and has_pending and _receipt_is_settled(completed):
        try:
            pending_path.unlink()
            parent_fd=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try:os.fsync(parent_fd)
            finally:os.close(parent_fd)
        except OSError as error:
            completed=_pending_result(completed,pending_path,'CLEANUP_FAILED',error)
            if isinstance(result,dict):result.update(completed)
            _CURRENT.event('DEADLINE_RECEIPT_PENDING_CLEANUP_FAILED',receipt_path=str(path),status=completed.get('status'))
            return completed
        _CURRENT.event('DEADLINE_RECEIPT_PENDING_CLEARED',receipt_path=str(path))
        elapsed=_CURRENT.mono()-_CURRENT.start_ns
    if _CURRENT.policy!='enforce' or elapsed<=BUDGET_NS:
        return completed

    # A file or directory fsync can itself cross the budget.  Keep the already
    # published business-write facts, but durably replace a success receipt
    # with a failure result before returning it to the node scheduler.
    if completed.get('status') not in {'CANNOT_CONFIRM','PARTIAL_COMMIT_RETRY_REQUIRED'}:
        completed['status']=('PARTIAL_COMMIT_RETRY_REQUIRED'
                             if completed.get('write_performed') is True or _CURRENT.writes_possible
                             else 'CANNOT_CONFIRM')
    if 'node_outcome' in completed:completed['node_outcome']='TRANSIENT'
    completed.setdefault('first_failed_layer','END_TO_END_DEADLINE')
    completed.update(deadline_status='EXCEEDED',deadline_budget_ns=BUDGET_NS,
                     partial_commit_possible=bool(_CURRENT.writes_possible),
                     error=completed.get('error') or 'END_TO_END_5S_EXCEEDED_AFTER_RECEIPT_DURABILITY')
    marker_status='NOT_APPLICABLE'
    if pending_path is not None:
        try:
            marker_status=ensure_pending_marker(path,completed)
        except OSError as error:
            completed=_pending_result(completed,pending_path,'DURABILITY_FAILED',error)
            completed.update(deadline_status='CANNOT_CONFIRM',deadline_budget_ns=BUDGET_NS)
            if rewrite is not None:
                try:
                    persisted=dict(rewrite(completed))
                except Exception as write_error:
                    completed.update(deadline_receipt_fallback_rewrite_status='FAILED',
                                     deadline_receipt_fallback_rewrite_error=f'{type(write_error).__name__}: {write_error}')
                else:
                    completed=_pending_result(persisted,pending_path,'DURABILITY_FAILED',error)
                    completed.update(deadline_receipt_fallback_rewrite_status='WRITTEN',
                                     deadline_receipt_fallback_receipt_status=persisted.get('status'))
                    _CURRENT.final_receipt(path,status=str(persisted.get('status') or 'CANNOT_CONFIRM'),durable=True)
            if isinstance(result,dict):result.update(completed)
            _CURRENT.event('DEADLINE_RECEIPT_PENDING_MARKER_FAILED',receipt_path=str(path),status=completed.get('status'))
            return completed
    completed['deadline_receipt_pending_marker_status']=marker_status
    if rewrite is None:
        completed['deadline_receipt_rewrite_status']='NOT_CONFIGURED'
        completed['deadline_receipt_pending_marker_path']=str(pending_path)
        if isinstance(result,dict):result.update(completed)
        return completed
    try:
        completed=dict(rewrite(completed))
    except Exception as error:
        completed=dict(result)
        if completed.get('status') not in {'CANNOT_CONFIRM','PARTIAL_COMMIT_RETRY_REQUIRED'}:
            completed['status']=('PARTIAL_COMMIT_RETRY_REQUIRED'
                                 if completed.get('write_performed') is True or _CURRENT.writes_possible
                                 else 'CANNOT_CONFIRM')
        if 'node_outcome' in completed:completed['node_outcome']='TRANSIENT'
        completed.setdefault('first_failed_layer','END_TO_END_DEADLINE')
        completed.update(deadline_status='EXCEEDED',deadline_budget_ns=BUDGET_NS,
                         partial_commit_possible=bool(_CURRENT.writes_possible),
                         deadline_receipt_rewrite_status='FAILED',
                         deadline_receipt_rewrite_error=f'{type(error).__name__}: {error}',
                         deadline_receipt_pending_marker_path=str(pending_path),
                         deadline_receipt_pending_marker_status=marker_status)
        if isinstance(result,dict):result.update(completed)
        _CURRENT.event('FINAL_RECEIPT_REWRITE_FAILED',receipt_path=str(path),status=completed.get('status'))
        return completed
    _CURRENT.final_receipt(path,status=str(completed.get('status') or 'CANNOT_CONFIRM'),durable=True)
    if pending_path is not None:
        try:
            pending_path.unlink()
            parent_fd=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try:os.fsync(parent_fd)
            finally:os.close(parent_fd)
        except FileNotFoundError:
            completed['deadline_receipt_pending_marker_cleanup_status']='ALREADY_ABSENT'
        except OSError as error:
            completed=_pending_result(completed,pending_path,'CLEANUP_FAILED',error)
            completed['deadline_receipt_pending_marker_cleanup_status']='FAILED'
        else:
            completed['deadline_receipt_pending_marker_cleanup_status']='REMOVED'
    return completed


def _receipt_is_settled(result: Mapping[str,Any]) -> bool:
    return result.get('status') in {'READY','READY_EMPTY','NOOP_ALREADY_VERIFIED'} or result.get('node_outcome') in {'SETTLED','SETTLED_PARTIAL'}


def pending_receipt_marker(path: Path) -> Path:
    return Path(f'{path}.deadline-pending')


_STAGE_NODE_RECEIPT_IDS=frozenset({'STAGE_0925','STAGE_0930_0935','STAGE_0935_0940',
                                  'STAGE_0940_0945','STAGE_0945_1030','STAGE_1300_1315',
                                  'STAGE_1445_1500','STAGE_1545_1555'})


def is_stage_node_receipt(path: Path) -> bool:
    """Restrict pending markers to the scheduler's date/stage node receipt."""
    return (path.name=='receipt.json' and path.parent.name in _STAGE_NODE_RECEIPT_IDS
            and len(path.parent.parent.name)==8 and path.parent.parent.name.isdigit())


def ensure_pending_marker(path: Path,result: Mapping[str,Any]) -> str:
    marker=pending_receipt_marker(path)
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)
    try:
        fd=os.open(marker,flags,0o600)
        created=True
    except FileExistsError:
        fd=os.open(marker,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        created=False
    try:
        if created:
            payload={'schema_version':'stage_center.deadline_receipt_pending.v1',
                     'receipt_path':str(path),'receipt_sha256':sha_file(path),
                     'status':result.get('status'),
                     'partial_commit_possible':bool(result.get('partial_commit_possible'))}
            data=(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
            while data:
                size=os.write(fd,data)
                if size<=0:raise OSError('DEADLINE_MARKER_SHORT_WRITE')
                data=data[size:]
        os.fsync(fd)
    finally:
        os.close(fd)
    parent_fd=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(parent_fd)
    finally:os.close(parent_fd)
    return 'CREATED' if created else 'EXISTING'


def _pending_result(result: Mapping[str,Any],marker: Path,status: str,
                    error: OSError | None=None) -> dict[str,Any]:
    failed=dict(result)
    failed.update(status='CANNOT_CONFIRM',first_failed_layer='END_TO_END_DEADLINE',
                  deadline_status='CANNOT_CONFIRM',deadline_receipt_pending=True,
                  node_outcome='TRANSIENT',
                  deadline_receipt_pending_marker_path=str(marker),
                  deadline_receipt_pending_marker_status=status)
    if error is not None:
        failed['deadline_receipt_pending_marker_error']=f'{type(error).__name__}: {error}'
    failed['partial_commit_possible']=bool(result.get('partial_commit_possible'))
    return failed


def source_observation(result: Any) -> dict[str, Any]:
    """Record bounded source timestamp samples without claiming their validity."""
    rows = getattr(result, "rows", ())
    stamps: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in ("update_time", "source_timestamp", "timestamp", "bar_time"):
            value = row.get(key)
            if value is not None:
                text = f"{key}={value}"
                if text not in stamps:
                    stamps.append(text)
    return {"source_status": getattr(result, "status", None),
            "source_rows": len(rows),
            "source_requested_rows": getattr(result, "requested_rows", None),
            "source_timestamp_samples": stamps[:4],
            "source_timestamp_distinct_count": len(stamps),
            "source_timestamp_verified": False,
            "scope": "BOUNDED_SOURCE_OBSERVATION_NOT_PIT_ATTESTATION"}


def install_offline_canary_guard(root: Path) -> None:
    """Best-effort Python audit restriction, NOT an OS sandbox.

    Used only by the explicit offline measurement process. Production invocation
    does not install it. Frozen source reads are allowed; network/process launch
    and writes outside the new canary root are refused before the event.
    """
    import sys
    allowed=Path(root).resolve(strict=True)
    if Path(root).is_symlink():raise ValueError('CANARY_ROOT_SYMLINK')
    original_open = os.open
    def check(value: Any, dir_fd: int | None=None):
        if isinstance(value,int):return
        path=Path(os.fsdecode(value))
        if not path.is_absolute() and dir_fd is not None and dir_fd >= 0:
            stat=os.fstat(dir_fd)
            candidates=[allowed,*(p for p in allowed.rglob('*') if p.is_dir() and not p.is_symlink())]
            bases=[p for p in candidates if (p.stat().st_dev,p.stat().st_ino)==(stat.st_dev,stat.st_ino)]
            if len(bases)!=1:raise PermissionError('CANARY_DIR_FD_OUTSIDE_ROOT')
            path=bases[0]/path
        resolved=path.resolve()
        try:resolved.relative_to(allowed)
        except ValueError:raise PermissionError('CANARY_WRITE_OUTSIDE_ROOT')
    def guarded_open(path, flags, mode=0o777, *, dir_fd=None):
        # CPython open audit does not expose dir_fd; validate this explicit
        # canary-only seam before the original os.open (business source intact).
        if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):check(path,dir_fd)
        return original_open(path,flags,mode,dir_fd=dir_fd)
    def audit(event_name: str,args: tuple):
        if event_name.startswith('socket.') or event_name in {'subprocess.Popen','os.system','os.posix_spawn','os.posix_spawnp','pty.spawn','os.fork','os.forkpty'} or event_name.startswith('os.exec'):
            raise PermissionError('OFFLINE_CANARY_NETWORK_OR_PROCESS_BLOCKED')
        if event_name=='open':
            path,mode,flags=args
            if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):check(path)
        elif event_name in {'os.rename','os.replace','os.link'}:
            check(args[0],args[2] if len(args)>2 else None);check(args[1],args[3] if len(args)>3 else None)
        elif event_name in {'os.remove','os.rmdir'}:
            check(args[0],args[1] if len(args)>1 else None)
        elif event_name in {'os.mkdir','os.chmod','os.chown','os.utime','os.truncate'}:
            check(args[0])
        elif event_name=='os.symlink':
            raise PermissionError('CANARY_SYMLINK_CREATION_BLOCKED')
    os.open=guarded_open
    sys.addaudithook(audit)
