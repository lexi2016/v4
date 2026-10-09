"""Durable bounded attempts. An interrupted RUNNING attempt never auto-retries."""
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import json
import os
import stat
from uuid import uuid4
from v5_shadow.contracts import exact_keys,sha,trade_date,aware
from v5_shadow.digests import canonical_bytes,sha256_json
from v5_shadow.module_api import _open_directory,_read_at
from v5_shadow.module_artifacts import _directory

LANES={'announcement','us_mapping','rebound','manager_plan'}
MARKER=b'v5.daily-run-ledger.v1\n'


def identity_key(identity):
    exact_keys(identity,('lane','target_date','input_sha256','research_cutoff','code_sha256','config_sha256','dependency_sha256'))
    if identity['lane'] not in LANES:raise ValueError('DAILY_LANE')
    trade_date(identity['target_date']);aware(identity['research_cutoff'])
    for field in ('input_sha256','code_sha256','config_sha256','dependency_sha256'):sha(identity[field])
    return sha256_json(identity)


@contextmanager
def locked(root,identity):
    key=identity_key(identity);fd=_open_directory(root)
    lock=None;lane=None;day=None
    try:
        if _read_at(fd,None,'.v5-daily-run-ledger')!=MARKER:raise ValueError('DAILY_LEDGER_MARKER')
        lane=_directory(fd,identity['lane']);day=_directory(lane,identity['target_date'])
        flags=os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK
        # Avoid Darwin's concurrent first-create openat(O_CREAT) fallback race.
        # Only EEXIST means another creator won; real ENOENT must propagate.
        # Never unlink/replace this inode: flock users must share the same lock.
        try:lock=os.open('.lock',flags|os.O_CREAT|os.O_EXCL,0o600,dir_fd=day)
        except FileExistsError:lock=os.open('.lock',flags,dir_fd=day)
        if not stat.S_ISREG(os.fstat(lock).st_mode):raise ValueError('DAILY_LEDGER_LOCK')
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield day,key
    finally:
        for item in (lock,day,lane,fd):
            if item is not None:os.close(item)


def _read(fd,name):
    try:return json.loads(_read_at(fd,None,name))
    except FileNotFoundError:return None


def read_run(root,identity):
    """Read a committed atomic state without admitting work or creating paths."""
    key=identity_key(identity);fd=_open_directory(root);lane=day=None
    try:
        if _read_at(fd,None,'.v5-daily-run-ledger')!=MARKER:raise ValueError('DAILY_LEDGER_MARKER')
        try:
            lane=os.open(identity['lane'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            day=os.open(identity['target_date'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=lane)
        except FileNotFoundError:return None
        state=_read(day,key+'.json')
        if state is not None and (state['identity']!=identity or state['identity_sha256']!=key):
            raise ValueError('DAILY_LEDGER_IDENTITY')
        return state
    finally:
        for item in (day,lane,fd):
            if item is not None:os.close(item)


def _write(fd,name,value):
    temporary='.'+uuid4().hex+'.tmp'
    out=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
    try:
        with os.fdopen(out,'wb') as stream:
            stream.write(canonical_bytes(value));stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,name,src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
    finally:
        try:os.unlink(temporary,dir_fd=fd)
        except FileNotFoundError:pass


def claim_run(root,identity,*,max_attempts=2):
    if type(max_attempts) is not int or not 1<=max_attempts<=3:raise ValueError('DAILY_RETRY_BOUND')
    with locked(root,identity) as (fd,key):
        state=_read(fd,key+'.json')
        if state is None:state=dict(identity=identity,identity_sha256=key,attempts=[],latest_success=None)
        if state['identity']!=identity or state['identity_sha256']!=key:raise ValueError('DAILY_LEDGER_IDENTITY')
        attempts=state['attempts']
        if state['latest_success'] is not None:return dict(status='REUSED_SUCCESS',state=state)
        if attempts and attempts[-1]['status']=='RUNNING':return dict(status='IN_PROGRESS_OR_OUTCOME_UNKNOWN',state=state)
        if attempts and not attempts[-1].get('retry_safe_without_external_effect',False):return dict(status='RETRY_BLOCKED',state=state)
        if len(attempts)>=max_attempts:return dict(status='RETRY_EXHAUSTED',state=state)
        attempt=dict(run_id=uuid4().hex,status='RUNNING',started_at=datetime.now(timezone.utc).isoformat(),finished_at=None,
                     retry_safe_without_external_effect=False)
        attempts.append(attempt);_write(fd,key+'.json',state)
        return dict(status='CLAIMED',identity=identity,identity_sha256=key,run_id=attempt['run_id'])


def finish_run(root,claim,receipt):
    exact_keys(receipt,('status','product_reference','readback_verified','retry_safe_without_external_effect','reason_codes'))
    if receipt['status'] not in {'SUCCEEDED','FAILED','BLOCKED'}:raise ValueError('DAILY_TERMINAL_STATUS')
    if type(receipt['readback_verified']) is not bool or type(receipt['retry_safe_without_external_effect']) is not bool:raise ValueError('DAILY_RECEIPT_BOOL')
    if receipt['status']=='SUCCEEDED' and (receipt['readback_verified'] is not True or not isinstance(receipt['product_reference'],dict) or not receipt['product_reference']):raise ValueError('DAILY_PRODUCT_READBACK_REQUIRED')
    if not isinstance(receipt['reason_codes'],list) or any(not isinstance(r,str) for r in receipt['reason_codes']):raise ValueError('DAILY_REASON_CODES')
    with locked(root,claim['identity']) as (fd,key):
        state=_read(fd,key+'.json')
        if key!=claim['identity_sha256'] or state is None or state['attempts'][-1]['run_id']!=claim['run_id'] or state['attempts'][-1]['status']!='RUNNING':raise ValueError('DAILY_STALE_CLAIM')
        attempt=state['attempts'][-1];attempt.update(receipt,finished_at=datetime.now(timezone.utc).isoformat(),natural_verified=False)
        if receipt['status']=='SUCCEEDED':state['latest_success']=dict(attempt)
        _write(fd,key+'.json',state)
        return state
