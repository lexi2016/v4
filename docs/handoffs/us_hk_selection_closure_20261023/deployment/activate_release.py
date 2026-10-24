"""Hash-bound release CAS/rollback; real lifecycle requires a controller capsule."""
from __future__ import annotations

import argparse
import ast
import ctypes
from contextlib import contextmanager, ExitStack
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import select
import signal
import subprocess
import sys
import time
import urllib.request
import weakref
from uuid import uuid4

from prepare_release import (SCHEMA, REHEARSAL_BASE, LABELS, LAUNCHAGENTS, Stop, authorize,
                             digest, exact, inventory_tool, json_bytes, precheck,
                             read_json, release_paths, require, sha, write_new)


def require_real_admission_protocol(scope=None):
    # Independent P1: snapshots/release locks do not fence actual submitters.
    # Direct reload remains disabled. A complete profile only selects the
    # guardian protocol; it never turns an idle assertion into a fence.
    if scope is None or not isinstance(scope.get('activity',{}).get('admission_files'),dict):
        raise Stop('REAL_LIFECYCLE_BLOCKED_NO_ACCEPTED_ADMISSION_PROTOCOL')
    require(set(scope['activity']['admission_files'])=={'parent','candidate'},'ADMISSION_PROFILE_BOTH_DIRECTIONS_REQUIRED')


class _BsdInfo(ctypes.Structure):
    _fields_=[(name,ctypes.c_uint32) for name in ('flags','status','xstatus','pid','ppid','uid','gid','ruid','rgid','svuid','svgid','rfu')]+[
        ('comm',ctypes.c_char*16),('name',ctypes.c_char*32)]+[(name,ctypes.c_uint32) for name in
        ('nfiles','pgid','jobc','tdev','tpgid')]+[('nice',ctypes.c_int32),('start_sec',ctypes.c_uint64),('start_usec',ctypes.c_uint64)]


def process_token(pid):
    """Darwin kernel start time, including microseconds; never match PID alone."""
    require(type(pid) is int and pid>1,'PROCESS_PID_INVALID')
    lib=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True);info=_BsdInfo()
    size=lib.proc_pidinfo(pid,3,0,ctypes.byref(info),ctypes.sizeof(info))
    if size==0 and ctypes.get_errno() in (0,3):return None
    require(size==ctypes.sizeof(info) and info.pid==pid,'PROCESS_KERNEL_IDENTITY_UNKNOWN')
    return dict(pid=pid,start_sec=info.start_sec,start_usec=info.start_usec,status=info.status)


def same_process(token):
    current=process_token(token['pid'])
    return current is not None and all(current[k]==token[k] for k in ('pid','start_sec','start_usec'))


class _AuditToken(ctypes.Structure):
    _fields_=[('val',ctypes.c_uint32*8)]


def signal_identity(pid):
    """Acquire a kernel audit token whose PID version fences signal delivery."""
    before=process_token(pid);require(before is not None,'SIGNAL_OWNER_ABSENT')
    lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
    own=ctypes.c_uint32.in_dll(lib,'mach_task_self_').value;port=ctypes.c_uint32()
    require(lib.task_name_for_pid(own,pid,ctypes.byref(port))==0 and port.value,'SIGNAL_TASK_NAME_UNAVAILABLE')
    audit=_AuditToken();count=ctypes.c_uint32(8)
    try:
        require(lib.task_info(port.value,15,ctypes.byref(audit),ctypes.byref(count))==0 and count.value==8,
                'SIGNAL_AUDIT_TOKEN_UNAVAILABLE')
    finally:lib.mach_port_deallocate(own,port.value)
    bsm=ctypes.CDLL('/usr/lib/libbsm.dylib')
    bsm.audit_token_to_pid.argtypes=[_AuditToken];bsm.audit_token_to_pid.restype=ctypes.c_int
    bsm.audit_token_to_pidversion.argtypes=[_AuditToken];bsm.audit_token_to_pidversion.restype=ctypes.c_int
    require(bsm.audit_token_to_pid(audit)==pid and same_process(before),'SIGNAL_OWNER_CHANGED_DURING_TOKEN_READ')
    return dict(before,audit_token=list(audit.val),pid_version=bsm.audit_token_to_pidversion(audit))


def signal_exact_identity(token,signum):
    """No PID-only kill fallback: Darwin checks the audit-token PID version."""
    words=token.get('audit_token')
    require(isinstance(words,list) and len(words)==8 and all(type(v) is int and 0<=v<2**32 for v in words),
            'SIGNAL_AUDIT_IDENTITY_REQUIRED')
    audit=_AuditToken((ctypes.c_uint32*8)(*words));lib=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True)
    call=lib.proc_signal_with_audittoken;call.argtypes=[ctypes.POINTER(_AuditToken),ctypes.c_int];call.restype=ctypes.c_int
    ctypes.set_errno(0);rc=call(ctypes.byref(audit),signum)
    require(rc==0,'SIGNAL_AUDIT_IDENTITY_REJECTED:'+str(ctypes.get_errno()))


def durable_json(path,value,*,after_replace=None):
    """Own mutable progress journal; atomic visibility and flushed file bytes."""
    path=Path(path);temp=path.with_name(path.name+'.'+uuid4().hex+'.new')
    exact(path.parent);raw=json_bytes(value)
    with temp.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)
    if after_replace is not None:after_replace()
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)


_CONTROL_BUFFERS=weakref.WeakKeyDictionary()
MAX_CONTROL_BYTES=64*1024


def read_control(stream,timeout=None):
    # All protocol reads use the descriptor directly: TextIOWrapper.readline
    # may prefetch the next event, which select() cannot see in its buffer.
    pending=_CONTROL_BUFFERS.setdefault(stream,bytearray());fd=stream.fileno()
    deadline=time.monotonic()+timeout if timeout is not None else None
    while True:
        end=pending.find(b'\n')
        if end>=0:
            require(end<=MAX_CONTROL_BYTES,'GUARDIAN_CONTROL_FRAME_TOO_LARGE')
            raw=bytes(pending[:end]);del pending[:end+1]
            value=json.loads(raw.decode('utf-8'))
            require(isinstance(value,dict),'GUARDIAN_CONTROL_INVALID');return value
        require(len(pending)<=MAX_CONTROL_BYTES,'GUARDIAN_CONTROL_FRAME_TOO_LARGE')
        remaining=None if deadline is None else max(0,deadline-time.monotonic())
        if not select.select([fd],[],[],remaining)[0]:raise Stop('GUARDIAN_CONTROL_TIMEOUT')
        raw=os.read(fd,4096)
        if not raw:
            require(not pending,'GUARDIAN_CONTROL_PARTIAL_EOF');return None
        pending.extend(raw)


def emit_control(stream,value):
    try:stream.write(json.dumps(value)+'\n');stream.flush();return True
    except (BrokenPipeError,OSError):return False


class FreezeGuardian:
    """Owns the stopped PID until safe recovery or committed idle termination.

    The controller's pipe is the precommit lease. This independent session
    survives controller exceptions/death. No postcommit path resumes the owner.
    """
    def __init__(self,ops,intent,control,output):
        self.ops,self.intent,self.control,self.output=ops,intent,control,output
        self.token=intent['owner_token'];self.committed=False;self.stop_requested=False;self.changed=False
        self.phase='OWNED';self.journal=Path(intent['journal']);self.calls=[]

    def record(self,phase,**extra):
        self.phase=phase;value=dict(schema='v4.us_hk.freeze_guardian.v1',phase=phase,
            owner_token=self.token,committed=self.committed or phase=='BOOTOUT_COMMITTED',stop_requested=self.stop_requested,
            guardian_pid=os.getpid(),controller_pid=self.intent['controller_pid'],calls=self.calls,**extra)
        callback=(lambda:setattr(self,'committed',True)) if phase=='BOOTOUT_COMMITTED' else None
        durable_json(self.journal,value,after_replace=callback)

    def exact_signal(self,signum,*,must_stopped=False):
        require(same_process(self.token),'GUARDIAN_OWNER_IDENTITY_CHANGED')
        current=process_token(self.token['pid'])
        if must_stopped:require(current['status']==4,'GUARDIAN_OWNER_NO_LONGER_STOPPED')
        self.calls.append(dict(signal=signum,pid=self.token['pid']))
        signal_exact_identity(self.token,signum)

    def owner_gone(self):
        if self.token is None:return True
        current=process_token(self.token['pid'])
        return current is None or current['status']==5 or not same_process(self.token)

    def recover_before_commit(self,reason):
        require(not self.committed,'COMMITTED_OWNER_MUST_NOT_RESUME')
        restore_error=None;resume_error=None
        try:
            if self.changed:self.ops.restore_precommit()
        except Exception as error:restore_error=type(error).__name__
        finally:
            if self.stop_requested and self.token is not None and same_process(self.token):
                current=process_token(self.token['pid'])
                # CONT also cancels our pending STOP if stop confirmation failed.
                if current['status']!=5:
                    try:self.exact_signal(signal.SIGCONT)
                    except Exception as error:resume_error=str(error)
        phase='INSPECTION_REQUIRED' if resume_error else 'ABORTED_PRECOMMIT'
        self.record(phase,reason=reason,restore_error=restore_error,resume_error=resume_error)
        emit_control(self.output,dict(event=phase,reason=reason))

    def finish_committed_owner(self):
        # A failed/timed-out launchctl request is never permission to CONT.
        if not self.owner_gone():
            self.exact_signal(signal.SIGKILL,must_stopped=True)
        deadline=time.monotonic()+5
        while not self.owner_gone():
            require(time.monotonic()<deadline,'GUARDIAN_IDLE_OWNER_EXIT_UNCONFIRMED');time.sleep(.02)
        self.record('OLD_OWNER_EXITED')
        state=self.ops.job_state()
        require(state.get('state')=='absent','GUARDIAN_NEW_OR_UNKNOWN_OWNER_PRESERVED')

    def run(self):
        self.record('OWNED');emit_control(self.output,dict(event='OWNED',guardian_pid=os.getpid()))
        try:
            command=read_control(self.control,10)
            require(command is not None and command.get('action')=='FREEZE','GUARDIAN_NO_FREEZE_REQUEST')
            self.ops.verify_before_freeze()
            if self.token is not None:
                require(same_process(self.token),'GUARDIAN_OWNER_IDENTITY_CHANGED')
                require(process_token(self.token['pid'])['status'] in (2,3),'GUARDIAN_OWNER_ALREADY_STOPPED_OR_UNKNOWN')
                self.stop_requested=True;self.record('STOP_REQUESTED');self.exact_signal(signal.SIGSTOP)
                deadline=time.monotonic()+5
                while True:
                    current=process_token(self.token['pid'])
                    require(same_process(self.token),'GUARDIAN_OWNER_CHANGED_DURING_STOP')
                    if current['status']==4:break
                    require(time.monotonic()<deadline,'GUARDIAN_STOP_UNCONFIRMED');time.sleep(.01)
            else:require(self.ops.job_state().get('state')=='absent','ABSENT_RECOVERY_OWNER_APPEARED')
            self.record('FROZEN')
            activity=self.ops.frozen_activity()
            require(activity.get('busy_work')==[],'FROZEN_OWNER_HEALTHY_WORK_OR_UNKNOWN')
            self.record('FROZEN_IDLE',activity=activity)
            emit_control(self.output,dict(event='FROZEN_IDLE'))
            command=read_control(self.control,30)
            require(command is not None and command.get('action')=='COMMIT','GUARDIAN_CONTROLLER_ABORTED')
            # No target thread can admit work between this observation and exit.
            if self.token is not None:
                require(same_process(self.token) and process_token(self.token['pid'])['status']==4,'GUARDIAN_FROZEN_FENCE_LOST')
            else:require(self.ops.job_state().get('state')=='absent','ABSENT_RECOVERY_OWNER_APPEARED')
            self.ops.verify_commit();require(self.ops.frozen_activity().get('busy_work')==[],'FROZEN_OWNER_HEALTHY_WORK_OR_UNKNOWN')
            self.changed=True;self.ops.replace_binding()
            # Commit is durable before bootout. On an exception below, resume
            # is forbidden; only this frozen-idle original PID may be finished.
            mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGTERM,signal.SIGINT})
            try:self.record('BOOTOUT_COMMITTED')
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
            emit_control(self.output,dict(event='BOOTOUT_COMMITTED'))
            try:
                if self.token is not None:self.ops.bootout()
            except Exception as error:self.record('BOOTOUT_UNKNOWN',error_type=type(error).__name__)
            self.finish_committed_owner()
            emit_control(self.output,dict(event='OLD_OWNER_EXITED'))
            command=read_control(self.control,30)
            if command is None or command.get('action')!='START':
                self.record('STOPPED_AFTER_COMMIT_NO_BOOTSTRAP');return
            require(self.ops.job_state().get('state')=='absent','GUARDIAN_NEW_OR_UNKNOWN_OWNER_PRESERVED')
            self.ops.bootstrap_once()
            result=self.ops.final_readback();self.record('FINISHED',result=result)
            emit_control(self.output,dict(event='FINISHED',result=result))
        except BaseException as error:
            if not self.committed:self.recover_before_commit(type(error).__name__+':'+str(error))
            else:
                try:self.finish_committed_owner()
                except Exception as recovery:self.record('INSPECTION_REQUIRED',error_type=type(error).__name__,recovery_error=str(recovery))
                else:self.record('STOPPED_AFTER_COMMIT_NO_BOOTSTRAP',error_type=type(error).__name__)
                emit_control(self.output,dict(event='INSPECTION_REQUIRED',phase=self.phase))


class DummyGuardianOps:
    """Physical tests only: exact controller child, marker and own scratch root."""
    def __init__(self,intent):
        self.intent=intent;root=exact(intent['rehearsal_root'])
        require(root.name.startswith('rehearsal-') and root.is_relative_to(exact(REHEARSAL_BASE)),'DUMMY_BOUNDARY_INVALID')
        for key in ('journal','activity_path','binding_path'):
            require(exact(intent[key],exists=False).is_relative_to(root),'DUMMY_PATH_ESCAPE')
        if intent['owner_token'] is not None:
            pid=intent['owner_token']['pid']
            query=subprocess.run(['/bin/ps','-p',str(pid),'-o','ppid=,command='],capture_output=True,text=True,timeout=5)
            require(query.returncode==0 and int(query.stdout.split()[0])==intent['controller_pid'] and
                    'TASK6_GUARDIAN_DUMMY' in query.stdout,'DUMMY_NOT_OWNED_MARKED_CHILD')
        else:require(intent.get('explicit_absent_recovery') is True,'DUMMY_ABSENT_RECOVERY_NOT_EXPLICIT')
        self.binding=Path(intent['binding_path']);self.before=self.binding.read_bytes()

    def verify_before_freeze(self):
        if self.intent['owner_token'] is not None:require(same_process(self.intent['owner_token']),'DUMMY_OWNER_DRIFT')
        else:require(self.job_state()['state']=='absent','DUMMY_ABSENT_OWNER_APPEARED')
    def frozen_activity(self):
        value=json.loads(Path(self.intent['activity_path']).read_bytes())
        require(isinstance(value.get('busy_work'),list),'DUMMY_ACTIVITY_UNKNOWN');return value
    def verify_commit(self):require(self.binding.read_bytes()==self.before,'DUMMY_BINDING_CAS')
    def replace_binding(self):
        durable_json(self.binding,dict(binding='candidate'))
        if self.intent.get('binding_error')=='after_write':raise OSError('dummy post-write fault')
    def restore_precommit(self):
        if self.binding.read_bytes()==json_bytes(dict(binding='candidate')):
            self.binding.write_bytes(self.before)
        else:require(self.binding.read_bytes()==self.before,'DUMMY_THIRD_PARTY_BINDING_PRESERVED')
    def bootout(self):
        if self.intent.get('bootout_mode')=='timeout':raise subprocess.TimeoutExpired('dummy bootout',1)
        # Bootout in a dummy namespace: never controls launchd or a service.
        token=self.intent['owner_token'];require(same_process(token),'DUMMY_PID_REUSED')
        signal_exact_identity(token,signal.SIGKILL)
    def job_state(self):
        other=self.intent.get('restarted_token')
        if other and same_process(other):return dict(state='running',pid=other['pid'])
        return dict(state='absent')
    def bootstrap_once(self):durable_json(Path(self.intent['rehearsal_root'])/'bootstrap-called.json',dict(count=1))
    def final_readback(self):return dict(state='ACTIVATED_DUMMY_ONLY')


ADMISSION_FILES={
    'api':{'v4/manager_workbench/'+name+'.py' for name in ('jobs','store','service','binding','config')}|
        {'v4/manager_workbench/inputs/'+name+'.py' for name in ('capture_jobs','native','source_bindings')}|
        {'infrastructure/manual_collection.py',
         'v4/manager_research/hkex_runtime.py','v4/manager_research/workspace_announcements.py'}|
        {'v4/manager_research/workspace.py','v4/manager_research/workspace_projection.py',
         'domains/research_review_generation/assembly.py'}|
        {'apps/api/v35_api/'+name+'.py' for name in ('app','manual_collection_router','review_router','hkex_announcements_router')},
    'scheduler':{'ops/launch_v35_macos_scheduler.sh'}|
        {'ops/'+name+'.py' for name in ('run_v35_macos_scheduler_daemon','run_v35_macos_scheduler','run_scheduled_slot','run_zsxq_hourly_delta')}|
        {'infrastructure/scheduling/'+name+'.py' for name in ('dispatcher','execution_ledger','executor_registry')}|
        {'v4/manager_workbench/'+name+'.py' for name in ('supervisor','jobs','store','service','scheduler','config')}|
        {'v4/manager_workbench/inputs/'+name+'.py' for name in ('capture_jobs','native','source_bindings')},
}


def actual_store_root(app,state_root):
    """Derive the pinned constructor's root without importing/creating a Store."""
    tree=ast.parse((Path(app)/'v4/manager_workbench/store.py').read_text())
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='WorkbenchStore')
    init=next(n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    values=[n.value for n in ast.walk(init) if isinstance(n,ast.Assign) and any(
        isinstance(t,ast.Attribute) and isinstance(t.value,ast.Name) and t.value.id=='self' and t.attr=='root' for t in n.targets)]
    expected=ast.parse('Path(state_root) / "manager_workbench"',mode='eval').body
    require(len(values)==1 and ast.dump(values[0])==ast.dump(expected),'STORE_ROOT_CONSTRUCTOR_UNRECOGNIZED')
    return exact(Path(state_root)/'manager_workbench',exists=False)


def effective_plist_environment(binding):
    env=dict(binding['EnvironmentVariables'])
    env.update({arg.split('=',1)[0]:arg.split('=',1)[1] for arg in binding.get('ProgramArguments',[])
        if isinstance(arg,str) and '=' in arg and not arg.startswith('/')})
    return env


def pinned_owner_config(scope,environment):
    path=environment.get('V4_MANAGER_WORKBENCH_CONFIG_PATH');require(path,'OWNER_CONFIG_REQUIRED')
    pins=[p for p in scope.get('dependencies',[]) if p['path']==path]
    require(len(pins)==1 and sha(exact(path))==pins[0]['sha256'],'API_OWNER_CONFIG_UNPINNED')
    return json.loads(Path(path).read_bytes())


def verify_activity_closure(scope,prepared,direction):
    """Bind the finite retained submitters and the API's other durable owners."""
    activity=scope['activity'];side='parent' if direction=='activate' else 'candidate'
    pins=activity['admission_files'][side]
    require(set(pins)==ADMISSION_FILES[scope['role']],'ADMISSION_SOURCE_CLOSURE_INCOMPLETE')
    app=Path(scope[side+'_root'])/'app'
    from prepare_release import child
    for relative,expected in pins.items():require(sha(child(app,relative))==expected,'ADMISSION_SOURCE_DRIFT')
    binding=plistlib.loads(Path(prepared['original_plist' if direction=='activate' else 'candidate_plist']).read_bytes())
    old=effective_plist_environment(binding);config=pinned_owner_config(scope,old)
    require(activity['workbench_root']==str(actual_store_root(app,config['state_root'])),'WORKBENCH_ACTIVITY_ROOT_NOT_OWNER_STORE')
    if scope['role']=='scheduler':
        require(activity['data_root']==old.get('V35_DATA_ROOT') and
                activity['dispatcher_root']==old.get('V35_DISPATCH_LEDGER_ROOT'),'SCHEDULER_ACTIVITY_ROOT_NOT_OWNER_ENV')
        return
    base=old.get('V35_REVIEW_CORE_CLOSE_ROOT') or old.get('V35_DATA_ROOT');require(base,'API_MANUAL_ROOT_UNKNOWN')
    review=old.get('V4_DAILY_REVIEW_ROOT');binding=old.get('V4_REVIEW_GENERATION_BINDINGS_PATH')
    generation_enabled=bool(review and binding and old.get('V4_REVIEW_GENERATION_BINDINGS_SHA256'))
    expected={'manual_collection':str(Path(base).parent/'manual_collection'),
        'manual_generation':str(Path(review).parent) if generation_enabled else None,
        'hkex_announcements':str(exact(config['manager_root']))}
    specs=activity.get('retained_owner_queues',[])
    require(len(specs)==3 and {s['kind']:s.get('root') for s in specs}==expected,'API_DURABLE_OWNER_QUEUE_CLOSURE_REQUIRED')


class RealGuardianOps:
    def __init__(self,intent):
        self.intent=intent;pin=intent['prepared'];self.prepared=read_json(pin['path'],pin['sha256'])
        self.scope=read_json(self.prepared['scope_path'],self.prepared['scope_sha256']);self.direction=intent['direction']
        require(self.scope.get('mode')=='RELEASE' and self.direction in ('activate','rollback'),'GUARDIAN_REAL_MODE_REQUIRED')
        require_real_admission_protocol(self.scope)
        authorize(self.scope,self.direction);verify_prepared(self.scope,self.prepared)
        evidence=exact(self.scope['evidence_root'])
        for key in ('journal','receipt_path'):
            require(exact(intent[key],exists=False).is_relative_to(evidence),'GUARDIAN_EVIDENCE_ESCAPE')
        require(intent['helper_sha256']==sha(Path(__file__)),'GUARDIAN_HELPER_DRIFT')
        self.lifecycle=LaunchctlLifecycle(self.scope)
        self.expected=self.prepared['original_plist_sha256'] if self.direction=='activate' else self.prepared['candidate_plist_sha256']
        self.source=self.prepared['candidate_plist'] if self.direction=='activate' else self.prepared['original_plist']
        self.target=str(Path(self.scope['candidate_root'] if self.direction=='activate' else self.scope['parent_root'])/'app')
        self.previous=str(Path(self.scope['parent_root'] if self.direction=='activate' else self.scope['candidate_root'])/'app')
        self.pointer=exact(self.scope['plist']['path']);self.raw=Path(self.source).read_bytes()
        self.before=self.pointer.read_bytes();self.calls=[]
        require(digest(self.before)==self.expected,'CURRENT_PLIST_CAS_DRIFT')
        require(plistlib.loads(self.raw)['WorkingDirectory']==self.target,'TARGET_PLIST_CWD')
        if intent['owner_token'] is None:
            require(self.direction=='rollback','ABSENT_OWNER_ONLY_EXPLICIT_ROLLBACK')
            verify_recovery_pin(intent.get('recovery_pin'),self.prepared,intent['prepared']['sha256'])
        verify_activity_closure(self.scope,self.prepared,self.direction)

    def verify_before_freeze(self):
        authorize(self.scope,self.direction);verify_prepared(self.scope,self.prepared)
        require(sha(self.pointer)==self.expected,'CURRENT_PLIST_CAS_DRIFT')
        observed=self.lifecycle.identity()
        if self.intent['owner_token'] is None:
            require(observed['state']=='absent','ABSENT_RECOVERY_OWNER_APPEARED');return
        require(observed['state']=='running' and observed['app_root']==self.previous and
                observed['pid']==self.intent['owner_token']['pid'],'GUARDIAN_RUNTIME_IDENTITY_DRIFT')
        if self.direction=='activate':require(observed['pid']==self.scope['activity']['expected_pid'],'ACTIVE_PID_DRIFT')
        verify_owner_binding(self.scope,self.prepared,self.intent['prepared']['sha256'],self.direction,
            self.intent['owner_token'],self.intent.get('recovery_pin'))

    def frozen_activity(self):
        value=self.lifecycle.inspect()
        if self.intent['owner_token'] is None:
            require(value['state']=='absent','ABSENT_RECOVERY_OWNER_APPEARED');return value
        require(value['pid']==self.intent['owner_token']['pid'] and value['app_root']==self.previous,
                'GUARDIAN_FROZEN_RUNTIME_IDENTITY_DRIFT')
        return value

    def verify_commit(self):
        self.verify_before_freeze()
        require(sha(self.intent['prepared']['path'])==self.intent['prepared']['sha256'],'GUARDIAN_PREPARED_DRIFT')
        verify_activity_closure(self.scope,self.prepared,self.direction)
        require(Path(self.source).read_bytes()==self.raw,'GUARDIAN_TARGET_PLIST_DRIFT')

    def replace_binding(self):replace_rehearsal_plist(self.pointer,self.raw,self.prepared['original_plist_mode'])
    def restore_precommit(self):
        current=self.pointer.read_bytes()
        require(current in (self.before,self.raw),'GUARDIAN_PRECOMMIT_THIRD_PARTY_DRIFT')
        if current==self.raw:replace_rehearsal_plist(self.pointer,self.before,self.prepared['original_plist_mode'])
    def bootout(self):
        cmd=['/bin/launchctl','bootout',self.lifecycle.domain+'/'+self.lifecycle.label];self.calls.append(cmd)
        result=self.lifecycle.command(cmd);require(result.returncode==0,'BOOTOUT_UNKNOWN')
    def job_state(self):return self.lifecycle.identity()
    def bootstrap_once(self):
        require(self.job_state()['state']=='absent','GUARDIAN_NEW_OR_UNKNOWN_OWNER_PRESERVED')
        cmd=['/bin/launchctl','bootstrap',self.lifecycle.domain,str(self.pointer)];self.calls.append(cmd)
        result=self.lifecycle.command(cmd);require(result.returncode==0,'BOOTSTRAP_UNKNOWN_NO_RETRY')
    def final_readback(self):
        deadline=time.monotonic()+16
        while True:
            try:value=self.lifecycle.inspect()
            except Stop:value={'state':'starting'}
            if value.get('state')=='running' and value.get('app_root')==self.target:break
            require(time.monotonic()<deadline,'GUARDIAN_NEW_OWNER_READBACK_PENDING');time.sleep(.25)
        require(sha(self.pointer)==digest(self.raw),'GUARDIAN_BINDING_READBACK_DRIFT')
        if self.scope['role']=='api':
            for path in ('/healthz','/readyz'):
                status,_=self.lifecycle.http_get('http://127.0.0.1:8873'+path);require(status==200,'API_HEALTH_READBACK_FAILED')
        signals=json.loads(Path(self.intent['journal']).read_bytes())['calls']
        result=dict(schema='v4.us_hk.release_transition.v1',mode='RELEASE',state='ACTIVATED' if self.direction=='activate' else 'ROLLED_BACK',
            direction=self.direction,prepared_sha256=self.intent['prepared']['sha256'],before_plist_sha256=self.expected,
            after_plist_sha256=digest(self.raw),target_app_root=self.target,runtime_readback=value,
            guardian_journal=self.intent['journal'],helper_sha256=sha(Path(__file__)),source_cutoff_changed=False,
            runtime_kernel_identity=signal_identity(value['pid']),
            data_pointer_changes=[],live_operations=len(self.calls)+len(signals),lifecycle_calls=self.calls,
            guardian_signals=signals,admission_fence='KERNEL_STOP_EXACT_IDLE_OWNER')
        write_new(self.intent['receipt_path'],json_bytes(result));return result

    def finish_journal(self,journal):
        if Path(self.intent['receipt_path']).exists():return
        progress=json.loads(Path(journal).read_bytes())
        try:
            observed=self.lifecycle.identity()
            kernel=signal_identity(observed['pid']) if observed.get('state')=='running' else None
        except Exception:observed=dict(state='unknown');kernel=None
        write_new(self.intent['receipt_path'],json_bytes(dict(schema='v4.us_hk.release_transition.v1',mode='RELEASE',
            state='FAILED_REQUIRES_INSPECTION',direction=self.direction,prepared_sha256=self.intent['prepared']['sha256'],
            after_plist_sha256=digest(self.raw),current_plist_sha256=sha(self.pointer),helper_sha256=sha(Path(__file__)),
            guardian_journal=str(journal),guardian_phase=progress['phase'],committed=progress['committed'],
            runtime_readback=observed,runtime_kernel_identity=kernel,
            live_operations=len(self.calls)+len(progress['calls']),lifecycle_calls=self.calls,guardian_signals=progress['calls'],
            retry_permitted=False,data_pointer_changes=[])))


def guardian_main(intent_path,intent_sha):
    intent=read_json(intent_path,intent_sha)
    require(intent.get('schema')=='v4.us_hk.guardian_intent.v1','GUARDIAN_INTENT_SCHEMA')
    if intent.get('mode')=='DUMMY_PROCESS_TEST':ops=DummyGuardianOps(intent)
    elif intent.get('mode')=='RELEASE':ops=RealGuardianOps(intent)
    else:raise Stop('GUARDIAN_MODE_UNKNOWN')
    def interrupted(signum,frame):raise Stop('GUARDIAN_SIGNAL_INTERRUPTION:'+str(signum))
    signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
    guard=release_guards(ops.scope) if intent['mode']=='RELEASE' else ExitStack()
    with guard:
        try:FreezeGuardian(ops,intent,sys.stdin,sys.stdout).run()
        finally:
            if hasattr(ops,'finish_journal'):ops.finish_journal(intent['journal'])


def verify_recovery_pin(pin,prepared,prepared_sha):
    require(isinstance(pin,dict),'EXPLICIT_RECOVERY_RECEIPT_REQUIRED')
    value=read_json(pin['path'],pin['sha256'])
    require(value.get('state')=='FAILED_REQUIRES_INSPECTION' and value.get('direction')=='activate' and
            value.get('prepared_sha256')==prepared_sha and
            value.get('after_plist_sha256')==prepared['candidate_plist_sha256'] and
            value.get('helper_sha256')==sha(Path(__file__)),'PARTIAL_ROLLBACK_RECEIPT_MISMATCH')


def verify_owner_binding(scope,prepared,prepared_sha,direction,token,recovery_pin):
    if direction=='activate':expected=scope['activity'].get('expected_owner')
    else:
        require(isinstance(recovery_pin,dict),'ROLLBACK_CURRENT_OWNER_RECEIPT_REQUIRED')
        value=read_json(recovery_pin['path'],recovery_pin['sha256'])
        require(value.get('state') in {'ACTIVATED','FAILED_REQUIRES_INSPECTION'} and
                value.get('direction')=='activate' and value.get('prepared_sha256')==prepared_sha and
                value.get('after_plist_sha256')==prepared['candidate_plist_sha256'] and
                value.get('helper_sha256')==sha(Path(__file__)),'ROLLBACK_OWNER_RECEIPT_MISMATCH')
        require(value.get('runtime_readback',{}).get('app_root')==str(Path(scope['candidate_root'])/'app'),
                'ROLLBACK_OWNER_ROOT_MISMATCH')
        expected=value.get('runtime_kernel_identity')
    keys=('pid','start_sec','start_usec','audit_token','pid_version')
    require(isinstance(expected,dict) and all(k in expected and token.get(k)==expected[k] for k in keys),
            'CURRENT_OWNER_NOT_FROZEN_CAPSULE_IDENTITY')


def restore_healthy_parent_binding(scope,prepared,prepared_sha,lifecycle,receipt_path,recovery_pin):
    """Explicit failed-cutover recovery; no signal/reload of the healthy parent."""
    verify_recovery_pin(recovery_pin,prepared,prepared_sha)
    with release_guards(scope):
        verify_prepared(scope,prepared)
        pointer=exact(scope['plist']['path']);require(sha(pointer)==prepared['candidate_plist_sha256'],'CURRENT_PLIST_CAS_DRIFT')
        observed=lifecycle.identity();require(observed['state']=='running' and
            observed['app_root']==str(Path(scope['parent_root'])/'app'),'HEALTHY_PARENT_IDENTITY_DRIFT')
        token=process_token(observed['pid']);require(token is not None,'HEALTHY_PARENT_PID_UNKNOWN')
        raw=Path(prepared['original_plist']).read_bytes()
        require(digest(raw)==prepared['original_plist_sha256'],'BACKUP_DRIFT')
        replace_rehearsal_plist(pointer,raw,prepared['original_plist_mode'])
        after=lifecycle.identity();require(after==observed and same_process(token),'HEALTHY_PARENT_CHANGED_DURING_BINDING_RESTORE')
        result=dict(schema='v4.us_hk.release_transition.v1',mode='RELEASE',state='ROLLED_BACK_BINDING_ONLY',direction='rollback',
            prepared_sha256=prepared_sha,before_plist_sha256=prepared['candidate_plist_sha256'],
            after_plist_sha256=sha(pointer),runtime_readback=after,helper_sha256=sha(Path(__file__)),
            live_operations=1,guardian_signals=[],lifecycle_calls=[],data_pointer_changes=[])
        write_new(receipt_path,json_bytes(result));return result


def guarded_transition(scope,prepared,prepared_path,prepared_sha,direction,lifecycle,receipt_path,recovery_pin):
    require_real_admission_protocol(scope)
    require(isinstance(lifecycle,LaunchctlLifecycle),'REAL_LIFECYCLE_ADAPTER_REQUIRED')
    verify_activity_closure(scope,prepared,direction)
    evidence=exact(scope['evidence_root']);receipt=exact(receipt_path,exists=False)
    require(receipt.is_relative_to(evidence) and not receipt.exists(),'TRANSITION_RECEIPT_COLLISION_OR_ESCAPE')
    observed=lifecycle.identity()
    if direction=='rollback' and observed.get('state')=='running' and observed.get('app_root')==str(Path(scope['parent_root'])/'app'):
        return restore_healthy_parent_binding(scope,prepared,prepared_sha,lifecycle,receipt,recovery_pin)
    token=None
    if observed['state']=='running':
        previous=str(Path(scope['parent_root'] if direction=='activate' else scope['candidate_root'])/'app')
        require(observed['app_root']==previous,'RUNTIME_IDENTITY_DRIFT');token=signal_identity(observed['pid'])
        require(token is not None,'OWNER_KERNEL_IDENTITY_UNKNOWN')
        require(token['status'] in (2,3),'OWNER_ALREADY_STOPPED_OR_UNKNOWN')
        verify_owner_binding(scope,prepared,prepared_sha,direction,token,recovery_pin)
    else:
        require(direction=='rollback' and observed['state']=='absent','RUNTIME_IDENTITY_DRIFT')
        verify_recovery_pin(recovery_pin,prepared,prepared_sha)
    run_id=uuid4().hex;intent_path=evidence/('guardian-intent-'+run_id+'.json');journal=evidence/('guardian-journal-'+run_id+'.json')
    intent=dict(schema='v4.us_hk.guardian_intent.v1',mode='RELEASE',controller_pid=os.getpid(),
        owner_token=token,prepared=dict(path=str(exact(prepared_path)),sha256=prepared_sha),direction=direction,
        recovery_pin=recovery_pin,journal=str(journal),receipt_path=str(receipt),helper_sha256=sha(Path(__file__)))
    with intent_path.open('xb') as stream:stream.write(json_bytes(intent));stream.flush();os.fsync(stream.fileno())
    guardian=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'_guardian',str(intent_path),sha(intent_path)],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,close_fds=True)
    def event(expected):
        value=read_control(guardian.stdout,45)
        require(value is not None and value.get('event')==expected,'GUARDIAN_TRANSITION_REQUIRES_INSPECTION:'+str(value))
        return value
    try:
        ack=event('OWNED')  # Ownership ACK before the only possible SIGSTOP.
        require(ack.get('guardian_pid')==guardian.pid,'GUARDIAN_ACK_PID_MISMATCH')
        owned=json.loads(journal.read_bytes())
        require(owned.get('phase')=='OWNED' and owned.get('guardian_pid')==guardian.pid and
                owned.get('controller_pid')==os.getpid() and owned.get('owner_token')==token,'GUARDIAN_OWNERSHIP_JOURNAL_MISMATCH')
        emit_control(guardian.stdin,dict(action='FREEZE'));event('FROZEN_IDLE')
        emit_control(guardian.stdin,dict(action='COMMIT'));event('BOOTOUT_COMMITTED');event('OLD_OWNER_EXITED')
        # A separate explicit command, never an automatic response to failure.
        emit_control(guardian.stdin,dict(action='START'));event('FINISHED')
        guardian.stdin.close();guardian.wait(timeout=10)
        require(guardian.returncode==0,'GUARDIAN_EXIT_UNKNOWN')
        result=json.loads(receipt.read_bytes());require(result['state'] in {'ACTIVATED','ROLLED_BACK'},'GUARDIAN_RESULT_NOT_SUCCESS')
        return result
    except BaseException:
        if not guardian.stdin.closed:guardian.stdin.close()
        # Do not terminate a guardian that may own a stopped process. It has the
        # immutable intent and pipe-EOF recovery protocol, independent of us.
        try:guardian.wait(timeout=20)
        except subprocess.TimeoutExpired:raise Stop('GUARDIAN_STILL_OWNS_RECOVERY_INSPECT:'+str(journal))
        raise


@contextmanager
def transition_lock(evidence):
    path = exact(Path(evidence) / "transition.lock", exists=False)
    # Rehearsal only. RELEASE uses release_guards and the retained owner routines.
    with path.open("a+b") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Stop("TRANSITION_BUSY") from error
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def verify_prepared(scope, prepared):
    require(scope.get("schema") == SCHEMA and scope.get("state") == "READY", "SCOPE_NOT_READY")
    require(scope.get('mode')==prepared.get('mode') and scope['mode'] in ('REHEARSAL','RELEASE'), 'MODE_MISMATCH')
    require(prepared.get("state") == "PREPARED" and prepared.get("schema") == "v4.us_hk.release_prepared.v1", "PREPARED_INVALID")
    require(scope["data_pointer_changes"] == prepared["data_pointer_changes"] == [], "DATA_PROMOTION_FORBIDDEN")
    if scope['mode']=='REHEARSAL':
        boundary = exact(scope["rehearsal_root"])
        require(boundary.name.startswith("rehearsal-") and boundary.is_relative_to(exact(REHEARSAL_BASE)) and
                boundary != REHEARSAL_BASE, "REHEARSAL_BOUNDARY_INVALID")
        for raw in [scope["parent_root"], scope["candidate_root"], scope["source_root"], scope["evidence_root"], scope["plist"]["path"],
                    prepared["original_plist"], prepared["candidate_plist"]]:
            require(exact(raw).is_relative_to(boundary) and Path(raw) != boundary, "REHEARSAL_PATH_ESCAPE")
    else:
        release_paths(scope)
        require(scope['role'] in LABELS,'SHARED_PACKAGE_HAS_NO_LIFECYCLE')
    require(prepared["candidate_root"] == scope["candidate_root"] and prepared["parent_root"] == scope["parent_root"], "PREPARED_ROOT_MISMATCH")
    require(sha(prepared["original_plist"]) == prepared["original_plist_sha256"] == scope["plist"]["sha256"], "BACKUP_DRIFT")
    require(sha(prepared["candidate_plist"]) == prepared["candidate_plist_sha256"], "PROPOSAL_DRIFT")
    require(sha(Path(__file__).with_name("prepare_release.py")) == prepared["helper_sha256"], "PREPARE_HELPER_DRIFT")
    candidate = exact(scope["candidate_root"])
    manifest = read_json(candidate / "release-manifest.json", prepared["candidate_manifest_sha256"])
    require(manifest["task_overlay"]["scope_sha256"] == prepared["scope_sha256"], "MANIFEST_SCOPE_MISMATCH")
    tool = inventory_tool(scope["inventory_tool"])
    entries = tool.inventory_tree(candidate / "app")
    require(entries == manifest["application_inventory"]["entries"] and
            tool.inventory_digest(entries) == prepared["candidate_inventory_sha256"], "CANDIDATE_INVENTORY_DRIFT")
    # Check parent, source, dependencies and review again without treating the
    # currently candidate-bound plist as its original preimage.
    without_plist = dict(scope, plist=None)
    precheck(without_plist, tool)


def replace_rehearsal_plist(path, raw, mode):
    p = exact(path)
    temporary = p.with_name(p.name + ".task6-new")
    write_new(temporary, raw)
    temporary.chmod(mode)
    os.replace(temporary, p)


@contextmanager
def release_guards(scope):
    """Existing API/announcement guards; scheduler uses the same owned-lock routine."""
    tool=inventory_tool(scope['inventory_tool'])
    binding=plistlib.loads(Path(scope['plist']['path']).read_bytes())
    app=Path(binding['WorkingDirectory'])
    side='parent' if app==Path(scope['parent_root'])/'app' else 'candidate'
    require(app==Path(scope[side+'_root'])/'app','GUARD_OWNER_APP_UNKNOWN')
    config=pinned_owner_config(scope,effective_plist_environment(binding))
    require(sha(app/'v4/manager_workbench/store.py')==scope['activity']['admission_files'][side]['v4/manager_workbench/store.py'],
            'ADMISSION_SOURCE_DRIFT')
    require(scope['activity']['workbench_root']==str(actual_store_root(app,config['state_root'])),'GUARD_ROOT_NOT_OWNER_STORE')
    parent=Path(scope['parent_root'])/'app'
    before=list(sys.path)
    sys.path[:0]=[str(parent),str(parent/'upstreams')]
    try:
        with ExitStack() as stack:
            if scope['role']=='api':
                stack.enter_context(tool.shared_api_release_lock(Path(scope['plist']['path']),timeout_seconds=2,role='gateway'))
            else:
                from infrastructure.interprocess_lock import owned_interprocess_lock
                lock=LAUNCHAGENTS/'.com.lexi.v35.scheduler.release.lock'
                require(scope['activity']['release_lock_path']==str(lock),'SCHEDULER_RELEASE_LOCK_PATH')
                stack.enter_context(owned_interprocess_lock(lock,timeout_seconds=2))
            stack.enter_context(tool.announcement_flash_cutover_guard(Path(scope['activity']['workbench_root']),timeout_seconds=2))
            for raw in scope['activity'].get('existing_kernel_locks',[]):
                path=exact(raw)
                require(path.is_file(),'ACTIVITY_LOCK_MISSING')
                stream=stack.enter_context(path.open('r+b'))
                try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError as error:raise Stop('HEALTHY_ACTIVITY_LOCK_BUSY') from error
            yield
    finally:
        sys.path[:]=before


def transition(prepared_path, prepared_sha, direction, lifecycle, receipt_path, *, recovery_pin=None):
    require(direction in ("activate", "rollback"), "DIRECTION_INVALID")
    prepared = read_json(prepared_path, prepared_sha)
    scope = read_json(prepared["scope_path"], prepared["scope_sha256"])
    if scope.get('mode')=='RELEASE':
        authorize(scope,direction)
        require(isinstance(lifecycle,LaunchctlLifecycle),'REAL_LIFECYCLE_ADAPTER_REQUIRED')
        verify_prepared(scope,prepared)
        require_real_admission_protocol(scope)
        return guarded_transition(scope,prepared,prepared_path,prepared_sha,direction,lifecycle,receipt_path,recovery_pin)
    verify_prepared(scope, prepared)
    evidence = exact(scope["evidence_root"])
    receipt = exact(receipt_path, exists=False)
    require(receipt.is_relative_to(evidence) and not receipt.exists(), "TRANSITION_RECEIPT_COLLISION_OR_ESCAPE")
    pointer = exact(scope["plist"]["path"])
    expected = prepared["original_plist_sha256"] if direction == "activate" else prepared["candidate_plist_sha256"]
    raw_source = prepared["candidate_plist"] if direction == "activate" else prepared["original_plist"]
    target_root = str(Path(scope["candidate_root"] if direction == "activate" else scope["parent_root"]) / "app")
    previous_root = str(Path(scope["parent_root"] if direction == "activate" else scope["candidate_root"]) / "app")
    guard=release_guards(scope) if scope['mode']=='RELEASE' else transition_lock(evidence)
    with guard:
        # CAS checked inside the same lock as the only allowed pointer write.
        require(sha(prepared_path) == prepared_sha, "PREPARED_RECEIPT_CHANGED_DURING_TRANSITION")
        require(sha(prepared["scope_path"]) == prepared["scope_sha256"], "SCOPE_CHANGED_DURING_TRANSITION")
        verify_prepared(scope, prepared)
        require(sha(pointer) == expected, "CURRENT_PLIST_CAS_DRIFT")
        observed = lifecycle.inspect()
        recovery=False;already_parent=False
        if direction=='rollback' and recovery_pin and (observed.get('state')=='absent' or
                observed.get('state')=='running' and observed.get('app_root')==target_root):
            failed=read_json(recovery_pin['path'],recovery_pin['sha256'])
            require(failed.get('state')=='FAILED_REQUIRES_INSPECTION' and failed.get('direction')=='activate' and
                    failed.get('prepared_sha256')==prepared_sha and failed.get('after_plist_sha256')==expected and
                    failed.get('helper_sha256')==sha(Path(__file__)), 'PARTIAL_ROLLBACK_RECEIPT_MISMATCH')
            recovery=True
            already_parent=observed.get('state')=='running'
        require(recovery or (observed.get("app_root") == previous_root and observed.get("state") == "running"), "RUNTIME_IDENTITY_DRIFT")
        if scope['mode']=='RELEASE' and direction=='activate':
            require(observed.get('pid')==scope['activity']['expected_pid'],'ACTIVE_PID_DRIFT')
        require(already_parent or observed.get("busy_work") == [], "HEALTHY_WORK_IN_FLIGHT")
        raw = Path(raw_source).read_bytes()
        raw_expected = prepared["candidate_plist_sha256"] if direction == "activate" else prepared["original_plist_sha256"]
        require(digest(raw) == raw_expected, "TARGET_PLIST_CHANGED_DURING_TRANSITION")
        require(plistlib.loads(raw)["WorkingDirectory"] == target_root, "TARGET_PLIST_CWD")
        result = dict(schema="v4.us_hk.release_transition.v1", mode=scope['mode'], direction=direction,
                      prepared_sha256=prepared_sha, before_plist_sha256=expected,
                      after_plist_sha256=digest(raw), target_app_root=target_root,
                      source_cutoff_changed=False, data_pointer_changes=[], live_operations=0,
                      partial_rollback=recovery,
                      helper_sha256=sha(Path(__file__)))
        # Final activity/current-plist snapshot immediately before any replacement.
        confirm=lifecycle.inspect()
        require(confirm==observed and sha(pointer)==expected,'ACTIVITY_OR_IDENTITY_CHANGED_BEFORE_CUTOVER')
        replace_rehearsal_plist(pointer, raw, prepared["original_plist_mode"])
        try:
            if not already_parent:lifecycle.reload(target_root)
            after = lifecycle.inspect()
            require(sha(pointer) == digest(raw) and after.get("state") == "running" and
                    after.get("app_root") == target_root, "LIFECYCLE_READBACK_FAILED")
        except Exception as error:
            # Preserve exact partial outcome. Never blindly reload or roll back.
            result.update(state="FAILED_REQUIRES_INSPECTION", error_type=type(error).__name__,
                          current_plist_sha256=sha(pointer),
                          live_operations=len(getattr(lifecycle,'calls',[])) if scope['mode']=='RELEASE' else 0)
            write_new(receipt, json_bytes(result))
            raise Stop("PARTIAL_TRANSITION_REQUIRES_INSPECTION") from error
        result.update(state="ACTIVATED" if direction == "activate" else "ROLLED_BACK", runtime_readback=after,
                      live_operations=len(getattr(lifecycle,'calls',[])) if scope['mode']=='RELEASE' else 0)
        write_new(receipt, json_bytes(result))
        return result


class FakeLifecycle:
    """Explicit test fixture; never consults or controls the host lifecycle."""
    def __init__(self, app_root, *, busy_work=None, fail=False, state="running"):
        self.app_root, self.busy_work = app_root, [] if busy_work is None else busy_work
        self.fail, self.state, self.calls = fail, state, []

    def inspect(self):
        return dict(app_root=self.app_root, state=self.state, busy_work=self.busy_work)

    def reload(self, target):
        self.calls.append(target)
        if self.fail:
            self.state = "unknown"
            raise RuntimeError("FAKE_LIFECYCLE_PARTIAL_FAILURE")
        self.app_root = target


def activity_snapshot(scope, runner):
    activity=scope['activity'];root=exact(activity['workbench_root'])
    require(root.name=='manager_workbench','ACTIVITY_WORKBENCH_ROOT')
    attempts=exact(root/'attempts')
    busy=[];identities=[]
    queue_patterns={'manual_collection':'jobs/*.json','manual_generation':'manual_generation/*.json',
                    'hkex_announcements':'workspace_announcement_runs/**/*.json'}
    for spec in activity.get('retained_owner_queues',[]):
        kind=spec['kind'];require(kind in queue_patterns,'RETAINED_OWNER_KIND_UNKNOWN')
        if spec.get('root') is None:
            require(kind=='manual_generation','ONLY_UNCONFIGURED_MANUAL_GENERATION_MAY_BE_ABSENT');continue
        queue_root=exact(spec['root'],exists=False)
        if not queue_root.exists():identities.append((str(queue_root),None));continue
        for path in sorted(queue_root.glob(queue_patterns[kind])):
            raw=exact(path).read_bytes();row=json.loads(raw);identities.append((str(path),digest(raw)))
            if kind=='manual_collection':
                require(row.get('origin')=='CONTROLLED_MANUAL_COLLECTION' and row.get('status') in
                        {'PENDING','RUNNING','READY','REUSED','PARTIAL','CANNOT_CONFIRM'},'MANUAL_COLLECTION_STATE_UNKNOWN')
                if row['status'] in {'PENDING','RUNNING'} or not row.get('finished_at'):busy.append(str(path))
            elif kind=='manual_generation':
                require(row.get('schema_version')=='v4.manual_review_attempt.v1' and row.get('status') in
                        {'RUNNING','SUCCEEDED','FAILED','ALREADY_EXISTS'},'MANUAL_GENERATION_STATE_UNKNOWN')
                if row['status']=='RUNNING':busy.append(str(path))
            else:
                require(row.get('schema_version')=='v4.manager_research.workspace_attempt.v1' and row.get('state') in
                        {'RUNNING','PARTIAL','FAILED','SUCCEEDED','SUCCEEDED_EMPTY'},'HKEX_ATTEMPT_STATE_UNKNOWN')
                if row['state']=='RUNNING' or not row.get('finished_at'):busy.append(str(path))
                else:
                    unsigned={k:v for k,v in row.items() if k!='sha256'}
                    require(row.get('sha256')==digest(json.dumps(unsigned,ensure_ascii=False,sort_keys=True,
                        separators=(',',':'),allow_nan=False).encode()),'HKEX_TERMINAL_ATTEMPT_SHA_INVALID')
    for p in sorted(attempts.glob('*.json')):
        raw=exact(p).read_bytes();record=json.loads(raw)
        require(record.get('state') in {'QUEUED','RUNNING','SUCCEEDED','PARTIAL','FAILED','CANCELLED','INTERRUPTED','USER_STOPPED'},'UNKNOWN_WORKBENCH_JOB_STATE')
        identities.append((str(p),digest(raw)))
        if record['state'] in {'QUEUED','RUNNING'}:busy.append(str(p))
        else:require(record.get('finished_at'),'WORKBENCH_TERMINAL_ATTEMPT_INCOMPLETE')
    queue=root/'announcement_flash/queue/queue-state.json'
    if queue.exists():
        raw=exact(queue).read_bytes();value=json.loads(raw)
        require(value.get('schema')=='v4.announcement-engine-queue/v1' and isinstance(value.get('jobs'),dict),'ANNOUNCEMENT_QUEUE_SCHEMA_DRIFT')
        identities.append((str(queue),digest(raw)))
        for row in value['jobs'].values():
            require(isinstance(row,dict) and isinstance(row.get('status'),str),'ANNOUNCEMENT_QUEUE_STATE_INVALID')
            if row['status']=='RUNNING':busy.append('ANNOUNCEMENT_RUNNING')
    else:identities.append((str(queue),None))  # Existing owner treats absent queue as empty.
    if scope['role']=='scheduler':
        data=exact(activity['data_root']);pdf=data/'external_sources/zsxq_hourly/zsxq_pdf_ingestion_index.json'
        if pdf.exists():
            raw=exact(pdf).read_bytes();index=json.loads(raw)
            require(index.get('schema_version')=='v4.zsxq_pdf_ingestion_index.v1' and
                    isinstance(index.get('documents'),dict),'PDF_INDEX_SCHEMA_DRIFT')
            identities.append((str(pdf),digest(raw)))
            for document in index['documents'].values():
                require(isinstance(document,dict) and isinstance(document.get('engine_runs',{}),dict),'PDF_ENGINE_RUNS_INVALID')
                for run in document.get('engine_runs',{}).values():
                    require(isinstance(run,dict) and run.get('status') in {'PENDING','PROCESSING','PARTIAL','READY','FAILED'},'PDF_RUN_STATE_UNKNOWN')
                    if run['status']=='PROCESSING':busy.append('PDF_PROCESSING')
        else:identities.append((str(pdf),None))  # Same empty-index contract as existing owner.
        ledger=exact(activity['dispatcher_root']);claims=exact(ledger/'claims/live')
        for claim_path in sorted(claims.rglob('*.json')):
            raw=exact(claim_path).read_bytes();claim=json.loads(raw)
            require(claim.get('schema_version') in {'v3_5.dispatch_claim.v1','v3_5.workload_claim.v1'} and claim.get('mode')=='LIVE','DISPATCH_CLAIM_SCHEMA_DRIFT')
            identities.append((str(claim_path),digest(raw)))
            parts=[str(claim.get(k,'')) for k in ('business_date','slot','run_id')]
            require(all(re.fullmatch(r'[A-Za-z0-9_-]+',p) for p in parts),'DISPATCH_CLAIM_ID_INVALID')
            receipt=ledger/'receipts/live'/parts[0]/parts[1]/(parts[2]+'.dispatch-receipt.json')
            if receipt.exists():
                receipt_raw=exact(receipt).read_bytes();done=json.loads(receipt_raw)
                unsigned={k:v for k,v in done.items() if k!='ledger_sha256'}
                expected=digest(json.dumps(unsigned,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
                require(done.get('ledger_sha256')==expected and done.get('finished_at') and
                        done.get('status') in {'SUCCEEDED','FAILED','NO_DUE_WORKLOADS','NO_ELIGIBLE_WORKLOADS',
                            'NON_TRADING_DAY','NON_TRADING_DAY_CADENCE','CONCURRENCY_SKIPPED',
                            'DRY_RUN_SELECTED','DUPLICATE_WORKLOAD_SKIPPED','CAPTURE_NOT_DUE'} and
                        all(done.get(k)==claim.get(k) for k in ('run_id','scheduled_date','business_date','target_date','slot','mode')) and
                        all(done.get(k) is False for k in ('production_allowed','buy_gate_updated','orders_sent')),
                        'DISPATCH_RECEIPT_UNCONFIRMED')
                identities.append((str(receipt),digest(receipt_raw)))
            else:
                pid=claim.get('pid');require(type(pid) is int and pid>0,'DISPATCH_PID_UNKNOWN')
                process=runner(['/bin/ps','-p',str(pid),'-o','pid='],capture_output=True,text=True,timeout=10)
                require(process.returncode in (0,1),'DISPATCH_OWNER_QUERY_UNKNOWN')
                if process.returncode==0:busy.append('DISPATCH_IN_FLIGHT')
                else:require(not process.stdout.strip(),'DISPATCH_OWNER_QUERY_UNKNOWN')
    return dict(busy_work=busy,activity_sha256=digest(json_bytes(identities)))


class LaunchctlLifecycle:
    """One exact named role, bounded lifecycle; subprocess injectable for tests."""
    def __init__(self,scope,*,runner=None,sleeper=None,clock=None,http_get=None):
        self.scope=scope;self.runner=runner or subprocess.run
        self.sleeper=sleeper or time.sleep;self.clock=clock or time.monotonic
        self.http_get=http_get or self._http_get;self.calls=[]
        require(scope['role'] in LABELS,'ROLE_HAS_NO_SERVICE')
        self.label=LABELS[scope['role']];self.domain='gui/'+str(scope['activity']['uid'])

    def command(self,args):
        return self.runner(args,capture_output=True,text=True,timeout=10)

    def identity(self):
        result=self.command(['/bin/launchctl','print',self.domain+'/'+self.label])
        if result.returncode==113:return dict(state='absent',app_root=None,pid=None)
        require(result.returncode==0,'LAUNCHCTL_PRINT_UNAVAILABLE')
        state=re.search(r'^\s*state = (\S+)\s*$',result.stdout,re.M)
        pid=re.search(r'^\s*pid = ([1-9][0-9]*)\s*$',result.stdout,re.M)
        require(state and state.group(1)=='running' and pid,'LAUNCHCTL_NOT_RUNNING')
        pid=int(pid.group(1))
        cwd=self.command(['/usr/sbin/lsof','-a','-p',str(pid),'-d','cwd','-Fn'])
        require(cwd.returncode==0,'PROCESS_CWD_UNAVAILABLE')
        roots=[line[1:] for line in cwd.stdout.splitlines() if line.startswith('n')]
        require(len(roots)==1,'PROCESS_CWD_AMBIGUOUS')
        comm=self.command(['/bin/ps','-p',str(pid),'-o','comm='])
        require(comm.returncode==0 and comm.stdout.strip()==self.scope['runtime_probe']['python']['path'], 'PROCESS_INTERPRETER_MISMATCH')
        return dict(state='running',pid=pid,app_root=roots[0])

    def inspect(self):
        value=self.identity();activity=activity_snapshot(self.scope,self.runner)
        if value['pid']:
            children=self.command(['/bin/ps','-axo','pid=,ppid='])
            require(children.returncode==0,'PROCESS_CHILD_SCAN_UNAVAILABLE')
            rows=[line.split() for line in children.stdout.splitlines() if line.strip()]
            require(all(len(row)==2 and all(x.isdigit() for x in row) for row in rows),'PROCESS_CHILD_SCAN_INVALID')
            if any(int(row[1])==value['pid'] for row in rows):activity['busy_work'].append('ACTIVE_CHILD_PROCESS')
        return dict(value,**activity)

    @staticmethod
    def _http_get(url):
        with urllib.request.urlopen(url,timeout=5) as result:return result.status,result.read(128*1024)

    def reload(self,target):
        require_real_admission_protocol()
        current=self.inspect()
        require(not current['busy_work'],'HEALTHY_WORK_IN_FLIGHT')
        if current['state']=='running':
            cmd=['/bin/launchctl','bootout',self.domain+'/'+self.label]
            self.calls.append(cmd);result=self.command(cmd)
            require(result.returncode==0,'BOOTOUT_FAILED_INSPECT_BEFORE_RETRY')
            deadline=self.clock()+16
            for _ in range(65):
                state=self.command(['/bin/launchctl','print',self.domain+'/'+self.label])
                if state.returncode==113:break
                require(state.returncode==0,'JOB_EXIT_STATE_UNKNOWN')
                require(self.clock()<deadline,'JOB_EXIT_PENDING_NO_BOOTSTRAP')
                self.sleeper(.25)
            else:raise Stop('JOB_EXIT_PENDING_NO_BOOTSTRAP')
        require(self.identity()['state']=='absent','JOB_NOT_ABSENT_BEFORE_BOOTSTRAP')
        cmd=['/bin/launchctl','bootstrap',self.domain,self.scope['plist']['path']]
        self.calls.append(cmd);result=self.command(cmd)
        require(result.returncode==0,'BOOTSTRAP_FAILED_INSPECT_BEFORE_RETRY')
        # launchd starts KeepAlive jobs; no repeated bootstrap/kickstart.
        deadline=self.clock()+16
        for _ in range(65):
            try:observed=self.identity()
            except Stop:observed={'state':'starting'}
            if observed.get('state')=='running' and observed.get('app_root')==target:break
            require(self.clock()<deadline,'NEW_RUNTIME_READBACK_PENDING')
            self.sleeper(.25)
        else:raise Stop('NEW_RUNTIME_READBACK_PENDING')
        if self.scope['role']=='api':
            for path in ('/healthz','/readyz'):
                status,_=self.http_get('http://127.0.0.1:8873'+path)
                require(status==200,'API_HEALTH_READBACK_FAILED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direction", choices=["activate", "rollback"])
    parser.add_argument("--prepared", required=True)
    parser.add_argument("--prepared-sha256", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--rehearsal", action="store_true")
    parser.add_argument('--recovery-receipt')
    parser.add_argument('--recovery-sha256')
    args = parser.parse_args()
    prepared = read_json(args.prepared, args.prepared_sha256)
    root = prepared["parent_root"] if args.direction == "activate" else prepared["candidate_root"]
    scope=read_json(prepared['scope_path'],prepared['scope_sha256'])
    require(args.rehearsal==(scope['mode']=='REHEARSAL'),'CLI_MODE_MISMATCH')
    lifecycle = FakeLifecycle(str(Path(root) / "app")) if args.rehearsal else LaunchctlLifecycle(scope)
    recovery=dict(path=args.recovery_receipt,sha256=args.recovery_sha256) if args.recovery_receipt and args.recovery_sha256 else None
    result = transition(args.prepared, args.prepared_sha256, args.direction, lifecycle, args.receipt,recovery_pin=recovery)
    print(json.dumps(dict(state=result["state"], live_operations=result['live_operations'], receipt=args.receipt)))


if __name__ == "__main__":
    if len(sys.argv)==4 and sys.argv[1]=='_guardian':guardian_main(sys.argv[2],sys.argv[3])
    else:main()
