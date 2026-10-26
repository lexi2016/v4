"""One fixed-label controller recipe. Default CLI is plan-only.

All action intent is fsynced before the action. Armed checkpoints are never
silently abandoned or automatically disarmed. A nonblocking flock permits one
executor; --resume continues the same owned operation after a crash.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo
import admin_bridge as bridge

ROOT=Path(__file__).resolve().parent
TZ=ZoneInfo('Asia/Shanghai')
TERMINAL={'SUCCEEDED','FAILED','NON_TRADING_DAY','NON_TRADING_DAY_CADENCE','NO_DUE_WORKLOADS','NO_ELIGIBLE_WORKLOADS','DUPLICATE_WORKLOAD_SKIPPED','EXPIRED'}

class StopOwned(RuntimeError): pass
class BoundaryRevoked(StopOwned): pass

def sha(raw): return hashlib.sha256(raw).hexdigest()
def canonical(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def stamp(): return datetime.now(TZ).isoformat()
def read_bytes(path,limit=64*1024*1024):
    path=Path(path)
    if path.is_symlink(): raise StopOwned('SYMLINK_DENIED:'+str(path))
    with path.open('rb') as stream: raw=stream.read(limit+1)
    if len(raw)>limit: raise StopOwned('READ_LIMIT:'+str(path))
    return raw

def read_json(path):
    value=json.loads(read_bytes(path))
    if not isinstance(value,dict): raise StopOwned('JSON_OBJECT_REQUIRED')
    return value

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            out.write((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode());out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
        dfd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(dfd)
        finally:os.close(dfd)
    finally:
        if os.path.exists(temp):os.unlink(temp)

class Journal:
    def __init__(self,path,plan,*,resume=False):
        self.path=Path(path)
        if (not self.path.resolve().is_relative_to(ROOT)
                or not (self.path.name=='owned-checkpoint.json' or self.path.name.endswith('.checkpoint.json'))):
            raise StopOwned('CHECKPOINT_MUST_BE_OWNED_CASE_FILE')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.marker=ROOT/'service-owned-operation.json'
        self.fd=os.open(bridge.LOCK_PATH,os.O_RDWR|os.O_NOFOLLOW)
        try:
            try:fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error:raise StopOwned('OWNED_EXECUTOR_STILL_RUNNING') from error
            legacy=bridge.legacy_consumed_failure()
            if self.marker.exists():
                owner=read_json(self.marker)
                if owner.get('active') and owner.get('checkpoint')!=str(self.path):
                    raise StopOwned('EXISTING_ARMED_OPERATION_REQUIRES_ITS_CHECKPOINT')
            self.plan=plan
            if self.path.exists():
                if not resume:raise StopOwned('EXISTING_CHECKPOINT_REQUIRES_RESUME')
                self.data=read_json(self.path)
                if self.marker.exists():
                    recorded=read_json(self.marker)
                    if recorded.get('active') and recorded.get('operation_id')!=self.data.get('operation_id'):
                        raise StopOwned('OWNED_CHECKPOINT_OPERATION_ID_MISMATCH')
                if self.data['plan_sha256']!=sha(canonical(plan)):raise StopOwned('PLAN_CHANGED')
            else:
                if resume:raise StopOwned('RESUME_CHECKPOINT_MISSING')
                self.data={'schema':'v4.main_guard_checkpoint.v3','operation_id':uuid4().hex,
                    'plan_sha256':sha(canonical(plan)),'phase':'PREPARED','armed':False,
                    'original_disabled':None,'disabled_state_untouched':True,'actions':[],
                    'descendants_seen':{},'created_at':stamp(),'legacy_consumed_failed_closure':legacy}
                self.save()
        except BaseException:
            os.close(self.fd);raise
    def save(self,phase=None,**updates):
        if phase:self.data['phase']=phase
        self.data.update(updates,updated_at=stamp(),executor_pid=os.getpid())
        atomic_json(self.path,self.data)
        active=(self.data.get('armed') or self.data['phase'] in {
            'ARM_REQUESTED','TERM_REQUESTED','DRAINING','GUARD_VERIFIED',
            'GUARD_BOOTOUT_REQUESTED','GUARD_REMOVING','PLIST_CAS_REQUESTED','PLIST_APPLIED',
            'BOOTSTRAP_REQUESTED','READBACK'}) and self.data['phase']!='DONE'
        atomic_json(self.marker,{'operation_id':self.data['operation_id'],'checkpoint':str(self.path),
            'plan_sha256':self.data['plan_sha256'],'phase':self.data['phase'],'active':bool(active),
            'executor_pid':os.getpid(),'updated_at':stamp()})
    def intent(self,phase,action):
        self.data['actions'].append({'intent':action,'at':stamp()});self.save(phase)
    def close(self):os.close(self.fd)

class LiveOps:
    """Fixed PLAN paths/label only. No arbitrary program or service argument."""
    def __init__(self,p):
        self.p=p;self.actions=[];self.pdf_reader=None
        if p['service']!='gui/501/com.lexi.v35.scheduler' or p['guard_program']!='/bin/sleep':raise StopOwned('FIXED_SCOPE_VIOLATION')
        if not 604800<=p['guard_seconds']<691200:raise StopOwned('GUARD_DURATION_OUTSIDE_FROZEN_RANGE')
    def command(self,args,*,allow_missing=False,timeout=15):
        result=subprocess.run(args,capture_output=True,text=True,timeout=timeout,
            env={**os.environ,'LC_ALL':'C'},check=False)
        if result.returncode and not allow_missing:raise StopOwned('COMMAND_FAILED:'+str(args[:3])+':'+str(result.returncode)+':'+result.stderr[-300:])
        return result
    def verify_package(self):
        p=self.p
        self.verified_python_binary()
        if sha(read_bytes(p['proposed_plist']))!=p['after_plist_sha256']:raise StopOwned('PROPOSED_PLIST_SHA_CHANGED')
        new=Path(p['new_root']).parent
        raw=read_bytes(new/'release-manifest.json')
        if sha(raw)!=p['new_manifest_sha256']:raise StopOwned('STAGED_MANIFEST_SHA_CHANGED')
        m=json.loads(raw)
        for rel,expected in m['files'].items():
            candidate=new/rel
            if not candidate.resolve().is_relative_to(new) or sha(read_bytes(candidate))!=expected:raise StopOwned('STAGED_FILE_SHA:'+rel)
        for key in ('external_a_clean_component_sources','external_a_clean_binding_files'):
            for name,expected in m[key].items():
                if sha(read_bytes(name))!=expected:raise StopOwned('A_DEPENDENCY_SHA:'+name)
        if any(new.rglob('*.pyc')):raise StopOwned('UNMANIFESTED_PYC_PRESENT')
        if sha(read_bytes(p['c_source_pass_receipt']))!=p['c_source_pass_sha256']:raise StopOwned('C_PASS_RECEIPT_CHANGED')
        if read_json(p['c_source_pass_receipt'])['verdict']!='PASS':raise StopOwned('C_SOURCE_NOT_PASS')
        if sha(read_bytes('/bin/sleep'))!=p['guard_program_sha256']:raise StopOwned('APPLE_SLEEP_SHA_CHANGED')
        self.command(['/usr/bin/codesign','-v','-R=anchor apple','/bin/sleep'])
        proposed=plistlib.loads(read_bytes(p['proposed_plist']))
        if proposed['Label']!='com.lexi.v35.scheduler' or proposed['WorkingDirectory']!=p['new_root']:raise StopOwned('PROPOSED_BINDING_SCOPE')
        if proposed['EnvironmentVariables']['V35_RELEASE_MANIFEST_SHA256']!=p['new_manifest_sha256']:raise StopOwned('PROPOSED_MANIFEST_BINDING')
    def service(self):
        r=self.command(['/bin/launchctl','print',self.p['service']],allow_missing=True)
        if r.returncode:
            if 'Could not find service' in r.stderr:return {'loaded':False,'pid':None}
            raise StopOwned('SERVICE_READ_UNKNOWN:'+r.stderr[-200:])
        pid=re.search(r'^\s*pid = (\d+)\s*$',r.stdout,re.M)
        exit_code=re.search(r'^\s*last exit code = (-?\d+)\s*$',r.stdout,re.M)
        return {'loaded':True,'pid':int(pid.group(1)) if pid else None,
                'last_exit_code':int(exit_code.group(1)) if exit_code else None,'text':r.stdout}
    def disabled(self):
        r=self.command(['/bin/launchctl','print-disabled',self.p['domain']])
        found=re.search(r'"com\.lexi\.v35\.scheduler"\s*=>\s*(true|false)',r.stdout)
        return found is not None and found.group(1)=='true'
    def processes(self):
        r=self.command(['/bin/ps','-ww','-axo','pid=,ppid=,pgid=,lstart=,command='])
        rows={}
        for line in r.stdout.splitlines():
            parts=line.split(None,8)
            if len(parts)!=9:continue
            try:pid,ppid,pgid=map(int,parts[:3])
            except ValueError:continue
            rows[pid]={'pid':pid,'ppid':ppid,'pgid':pgid,'start':' '.join(parts[3:8]),'command':parts[8]}
        return rows
    def identity(self,pid,rows=None):
        row=(rows or self.processes()).get(pid)
        if not row:return None
        stable={key:row[key] for key in ('pid','start','command')}
        return {**stable,'identity_sha256':sha(canonical(stable))}
    def descendants(self,pid,rows):
        seen=set();parents={pid}
        while parents:
            next_pids={r['pid'] for r in rows.values() if r['ppid'] in parents and r['pid'] not in seen}
            seen|=next_pids;parents=next_pids
        return sorted(seen)
    def cwd(self,pid):
        r=self.command(['/usr/sbin/lsof','-a','-p',str(pid),'-d','cwd','-Fn'])
        paths=[s[1:] for s in r.stdout.splitlines() if s.startswith('n')]
        if len(paths)!=1:raise StopOwned('PROCESS_CWD_UNKNOWN')
        return paths[0]
    def check_old(self,expected):
        s=self.service();rows=self.processes();identity=self.identity(expected['pid'],rows)
        if s['pid']!=expected['pid'] or identity!=expected:raise StopOwned('OLD_OWNER_CHANGED')
        if self.cwd(expected['pid'])!=self.p['old_root']:raise StopOwned('OLD_ROOT_CHANGED')
        if sha(read_bytes(self.p['live_plist']))!=self.p['before_plist_sha256']:raise StopOwned('LIVE_PLIST_CAS_CHANGED')
        if self.disabled():raise StopOwned('DISABLED_STATE_CHANGED_BY_OTHER_OWNER')
        return rows
    def initial_old(self,expected_pid):
        if self.disabled():raise StopOwned('ORIGINAL_SERVICE_DISABLED')
        s=self.service();rows=self.processes()
        if not re.search(r'^\s*properties = .*\bkeepalive\b',s.get('text',''),re.M):raise StopOwned('LOADED_KEEPALIVE_NOT_CONFIRMED')
        if self.p['old_root']+'/ops/launch_v35_macos_scheduler.sh' not in s.get('text',''):raise StopOwned('LOADED_OLD_WRAPPER_NOT_CONFIRMED')
        if s['pid']!=expected_pid:raise StopOwned('INITIAL_PID_CHANGED')
        identity=self.identity(expected_pid,rows)
        if not identity or '-m ops.run_v35_macos_scheduler_daemon' not in identity['command']:raise StopOwned('NOT_ORIGINAL_MAIN_DAEMON')
        if self.cwd(expected_pid)!=self.p['old_root']:raise StopOwned('INITIAL_OLD_ROOT_MISMATCH')
        if sha(read_bytes(Path(self.p['old_root'])/'ops/run_v35_macos_scheduler_daemon.py'))!=self.p['old_daemon_sha256']:raise StopOwned('OLD_DAEMON_SOURCE_CHANGED')
        return identity
    def receipt(self,relative):
        root=Path(self.p['ledger_root']);path=root/relative
        if not path.resolve().is_relative_to(root):raise StopOwned('RECEIPT_PATH_ESCAPE')
        value=read_json(path)
        body={k:v for k,v in value.items() if k!='ledger_sha256'}
        if value.get('ledger_sha256')!=sha(canonical(body)):raise StopOwned('DISPATCH_RECEIPT_SELF_SHA')
        if value.get('mode')!='LIVE' or not value.get('run_id') or value.get('status') not in TERMINAL or any(value.get(k) is not False for k in ('production_allowed','orders_sent','buy_gate_updated')):raise StopOwned('DISPATCH_NOT_TERMINAL_SAFE')
        return value
    def claims(self,pid):
        root=Path(self.p['ledger_root']);day=datetime.now(TZ).strftime('%Y%m%d')
        paths=list((root/'claims/live'/day).glob('*/dispatch.claim.json'))+list((root/'workloads/live'/day).glob('*/*.workload-claim.json'))
        if len(paths)>1024:raise StopOwned('CLAIM_READ_BOUND')
        signatures=[];unfinished=[]
        for path in paths:
            raw=read_bytes(path);claim=json.loads(raw)
            if claim.get('pid')!=pid:continue
            signatures.append([str(path),sha(raw)])
            rel=f"receipts/live/{claim['business_date']}/{claim['slot']}/{claim['run_id']}.dispatch-receipt.json"
            try:value=self.receipt(rel)
            except FileNotFoundError:unfinished.append({'slot':claim.get('slot'),'run_id':claim.get('run_id')});continue
            if value.get('run_id')!=claim['run_id'] or value.get('business_date')!=claim['business_date']:raise StopOwned('CLAIM_RECEIPT_IDENTITY')
        return {'epoch':sha(canonical(signatures)),'unfinished':unfinished}
    def cycle(self,pid):
        path=Path(self.p['log_path'])
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-2*1024*1024));raw=stream.read()
        last_result=None;last_cycle=None;last_actual=None
        for line in raw.decode('utf-8',errors='replace').splitlines():
            try:value=json.loads(line)
            except ValueError:continue
            if not isinstance(value,dict):continue
            if value.get('status')=='DAEMON_CYCLE' and value.get('pid')==pid:
                last_cycle=value
                if last_result and last_result.get('run_id') and last_result.get('receipt_path'):last_actual=last_result
            elif value.get('schema_version') in {'v3_5.scheduled_slot_result.v1','v3_5.macos_scheduler_result.v1'}:
                last_result=value
        if not last_cycle or last_cycle.get('minute')!=datetime.now(TZ).strftime('%Y-%m-%dT%H:%M'):
            return {'ready':False,'reason':'CURRENT_MINUTE_CYCLE_NOT_COMPLETE'}
        if not last_actual:
            # A freshly started daemon can complete many NO_DUE minutes before
            # ever producing a dispatch receipt. This is an idle-cycle proof,
            # not a dispatch receipt/run or business READY state.
            if last_cycle.get('result_status')!='NO_DUE_SLOT':
                return {'ready':False,'reason':'ACTUAL_TERMINAL_DISPATCH_NOT_FOUND'}
            records=raw.splitlines()
            if len(records)<2 or not raw.endswith(b'\n'):
                return {'ready':False,'reason':'NO_DUE_RECORDS_NOT_COMPLETE'}
            try:result=json.loads(records[-2]);completed=json.loads(records[-1])
            except (ValueError,UnicodeDecodeError):
                return {'ready':False,'reason':'NO_DUE_RECORDS_NOT_PAIRED'}
            if not isinstance(result,dict) or completed!=last_cycle:
                return {'ready':False,'reason':'NO_DUE_RECORDS_NOT_PAIRED'}
            now=datetime.now(TZ);minute=now.strftime('%Y-%m-%dT%H:%M')
            release=Path(self.p['old_root']).parent.name
            if (result.get('schema_version')!='v3_5.macos_scheduler_result.v1'
                    or result.get('status')!='NO_DUE_SLOT'
                    or result.get('business_date')!=now.strftime('%Y%m%d')
                    or result.get('observed_slot')!=now.strftime('%H%M')
                    or result.get('run_id') is not None or result.get('receipt_path') is not None
                    or completed.get('schema_version')!='v3_5.macos_scheduler_daemon.v1'
                    or completed.get('minute')!=minute or completed.get('pid')!=pid
                    or type(completed.get('return_code')) is not int or completed['return_code']!=0
                    or any(row.get('release_id')!=release for row in (result,completed))
                    or any(row.get(key) is not False for row in (result,completed)
                           for key in ('production_allowed','orders_sent','buy_gate_updated'))):
                return {'ready':False,'reason':'NO_DUE_CURRENT_COMPLETION_MISMATCH'}
            owner=self.identity(pid);service=self.service()
            if (not owner or owner['pid']!=pid or service.get('pid')!=pid
                    or not re.search(r'-m ops\.run_v35_macos_scheduler_daemon(?:\s|$)',owner['command'])
                    or self.cwd(pid)!=self.p['old_root']):
                return {'ready':False,'reason':'NO_DUE_ACTUAL_OWNER_SOURCE_MISMATCH'}
            try:started=datetime.strptime(owner['start'],'%a %b %d %H:%M:%S %Y').replace(tzinfo=TZ)
            except ValueError:return {'ready':False,'reason':'NO_DUE_OWNER_START_UNKNOWN'}
            if started>now or started.strftime('%Y-%m-%dT%H:%M')>minute:
                return {'ready':False,'reason':'NO_DUE_OWNER_START_AFTER_RECORD'}
            for key,expected in (('V35_APP_ROOT',self.p['old_root']),('V35_RELEASE_ID',release)):
                observed=re.findall(r'^\s*'+key+r'\s*=>\s*(.*?)\s*$',service.get('text',''),re.M)
                if not observed or set(observed)!={expected}:
                    return {'ready':False,'reason':'NO_DUE_LOADED_SOURCE_MISMATCH'}
            source_sha=sha(read_bytes(Path(self.p['old_root'])/'ops/run_v35_macos_scheduler_daemon.py'))
            if source_sha!=self.p['old_daemon_sha256']:raise StopOwned('OLD_DAEMON_SOURCE_CHANGED')
            if self.identity(pid)!=owner:raise StopOwned('NO_DUE_OWNER_CHANGED_DURING_PROOF')
            if datetime.now(TZ).strftime('%Y-%m-%dT%H:%M')!=minute:
                return {'ready':False,'reason':'NO_DUE_BOUNDARY_CROSSED_MINUTE'}
            return {'ready':True,'proof_kind':'COMPLETED_NO_DUE_CYCLE','run_id':None,
                'cycle_sha':sha(canonical(last_cycle)),
                'result_record_sha256':sha(records[-2]),'cycle_record_sha256':sha(records[-1]),
                'owner_identity':owner,'source_sha256':source_sha,'release_id':release,'minute':minute}
        value=self.receipt(last_actual['receipt_path'])
        if value.get('run_id')!=last_actual['run_id']:raise StopOwned('LOG_RECEIPT_RUN_MISMATCH')
        return {'ready':True,'cycle_sha':sha(canonical(last_cycle)),'run_id':value['run_id']}
    def pdf_empty(self):
        p=self.p;source=Path(p['old_root'])/'infrastructure/zsxq_pdf_ingestion.py'
        if sha(read_bytes(source))!=p['old_pdf_source_sha256']:raise StopOwned('OLD_PDF_HELPER_CHANGED')
        index=Path(p['data_root'])/'external_sources/zsxq_hourly/zsxq_pdf_ingestion_index.json'
        before=sha(read_bytes(index)) if index.exists() else 'ABSENT'
        if self.pdf_reader is None:
            sys.path.insert(0,p['old_root'])
            module=importlib.import_module('infrastructure.zsxq_pdf_ingestion')
            if Path(module.__file__).resolve()!=source.resolve():raise StopOwned('PDF_HELPER_IMPORT_SHADOW')
            self.pdf_reader=module.pending_pdf_tasks
        pending=self.pdf_reader(Path(p['data_root']))  # existing read-only source/index verifier; no OCR/download
        after=sha(read_bytes(index)) if index.exists() else 'ABSENT'
        if before!=after:return {'ready':False,'reason':'PDF_INDEX_CHANGED_DURING_READ'}
        return {'ready':not pending,'epoch':after,'pending_count':len(pending)}
    def safe_pdf_boundary(self,old):
        boundary_minute=datetime.now(TZ).strftime('%Y-%m-%dT%H:%M')
        self.check_old(old)
        if sha(read_bytes(self.p['manager_config']))!=self.p['manager_config_sha256']:raise StopOwned('MANAGER_CONFIG_CHANGED')
        if read_json(self.p['manager_config']).get('capture_enabled') is not False:raise StopOwned('ANNOUNCEMENT_CAPTURE_NOT_EXCLUDED')
        rows=self.processes();desc=self.descendants(old['pid'],rows)
        # A PDF producer can enqueue after an empty-index check. Never TERM
        # while one is still active, even if it is not a direct child.
        producers=[r['pid'] for r in rows.values() if any(x in r['command'] for x in (
            '-m ops.run_zsxq_hourly_delta','-m ops.zsxq_pdf_ingestion','--pdf-queue-tick'))]
        if producers:return {'ready':False,'reason':'ACTIVE_PDF_OR_ENQUEUE_PRODUCER','pids':producers}
        claims=self.claims(old['pid']);cycle=self.cycle(old['pid'])
        if claims['unfinished'] or not cycle['ready']:
            return {'ready':False,'reason':'MAIN_CYCLE_NOT_RETURNED','claims':claims['unfinished']}
        pdf=self.pdf_empty()
        if not pdf['ready']:return {'ready':False,'reason':'PDF_WORK_NOT_EMPTY','pdf':pdf}
        rows2=self.check_old(old)
        if self.descendants(old['pid'],rows2)!=desc:return {'ready':False,'reason':'DESCENDANT_SET_CHANGED'}
        if any(r['pid']!=old['pid'] and r['pgid']==rows2[old['pid']]['pgid'] for r in rows2.values()):return {'ready':False,'reason':'OLD_PROCESS_GROUP_MEMBER_ACTIVE'}
        # Hooks may still be doing healthy in-process work. That is allowed:
        # manual TERM only sets the Event and no bootout occurs until guard.
        now=datetime.now(TZ)
        if now.strftime('%Y-%m-%dT%H:%M')!=boundary_minute:return {'ready':False,'reason':'BOUNDARY_CROSSED_MINUTE'}
        if 60-now.second-now.microsecond/1e6<5:return {'ready':False,'reason':'WAIT_NEXT_MINUTE_MARGIN'}
        return {'ready':True,'epoch':sha(canonical([claims['epoch'],cycle,pdf['epoch'],desc])),
                'pdf_epoch':pdf['epoch'],'dispatch_run_id':cycle['run_id']}
    def arm(self):
        raise StopOwned('ROOT_DEBUG_ONLY_VIA_REVIEWED_ADMIN_HELPER')
    def term_old(self,old):
        proof=self.safe_pdf_boundary(old)
        if not proof['ready']:raise BoundaryRevoked('PDF_BOUNDARY_REVOKED_NO_TERM_SENT')
        # No subprocess/file reads between this fresh gate and the exact-PID syscall.
        os.kill(old['pid'],signal.SIGTERM)
        return proof
    def observe(self,old):
        s=self.service();rows=self.processes();old_now=self.identity(old['pid'],rows)
        if old_now is not None and old_now!=old:raise StopOwned('OLD_PID_REUSED_NO_SIGNAL')
        return {'service':s,'rows':rows,'old_alive':old_now is not None,
                'owner':self.identity(s['pid'],rows) if s.get('pid') else None}
    def guard(self,observation):
        owner=observation['owner'];s=observation['service'];rows=observation['rows']
        if not owner:return None
        if shlex.split(owner['command'])!=['/bin/sleep',str(self.p['guard_seconds'])]:raise StopOwned('UNEXPECTED_REPLACEMENT_OWNER_NO_SIGNAL')
        if self.command(['/bin/ps','-p',str(owner['pid']),'-o','comm=']).stdout.strip()!='/bin/sleep':raise StopOwned('GUARD_ACTUAL_EXECUTABLE_MISMATCH')
        if sha(read_bytes('/bin/sleep'))!=self.p['guard_program_sha256']:raise StopOwned('GUARD_BINARY_CHANGED')
        if self.descendants(owner['pid'],rows) or any(r['pid']!=owner['pid'] and r['pgid']==rows[owner['pid']]['pgid'] for r in rows.values()):raise StopOwned('GUARD_HAS_CHILD_OR_PROCESS_GROUP_WORK')
        if self.claims(owner['pid'])['unfinished']:raise StopOwned('GUARD_HAS_BUSINESS_CLAIM')
        if s.get('last_exit_code')!=0:raise StopOwned('ORIGINAL_MAIN_DID_NOT_EXIT_NORMALLY')
        if self.disabled():raise StopOwned('DISABLED_STATE_CHANGED')
        if sha(read_bytes(self.p['live_plist']))!=self.p['before_plist_sha256']:raise StopOwned('LIVE_PLIST_CHANGED_BEFORE_GUARD_REMOVAL')
        return owner
    def old_children_finished(self,seen):
        rows=self.processes()
        return all((current:=self.identity(int(pid),rows)) is None or current['start']!=identity['start']
                   for pid,identity in seen.items())
    def bootout_guard(self,guard,old):
        ob=self.observe(old)
        if ob['old_alive'] or self.guard(ob)!=guard:raise StopOwned('GUARD_OWNER_CHANGED_BEFORE_BOOTOUT')
        self.command(['/bin/launchctl','bootout',self.p['service']],timeout=15)
    def gone(self,identity):
        current=self.identity(identity['pid'])
        return current is None or current['start']!=identity['start']
    def assert_unloaded(self):
        if self.service()['loaded']:raise StopOwned('SERVICE_STILL_OR_AGAIN_LOADED_NO_TOUCH')
    def cas_plist(self):
        self.assert_unloaded();self.verify_package()
        target=Path(self.p['live_plist']);raw=read_bytes(target);current=sha(raw)
        if current==self.p['after_plist_sha256']:return
        if current!=self.p['before_plist_sha256']:raise StopOwned('LIVE_PLIST_CAS_CONFLICT')
        info=target.stat()
        if info.st_uid!=os.getuid():raise StopOwned('PLIST_OWNER_PERMISSION_MISMATCH')
        fd,temp=tempfile.mkstemp(prefix='.'+target.name+'.guard-r3.',dir=target.parent)
        try:
            with os.fdopen(fd,'wb') as out:
                os.fchmod(out.fileno(),stat.S_IMODE(info.st_mode));out.write(read_bytes(self.p['proposed_plist']));out.flush();os.fsync(out.fileno())
            if sha(read_bytes(target))!=current:raise StopOwned('PLIST_CHANGED_AT_CAS')
            os.replace(temp,target)
            dfd=os.open(target.parent,os.O_RDONLY)
            try:os.fsync(dfd)
            finally:os.close(dfd)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    def bootstrap(self):
        self.assert_unloaded()
        if self.disabled():raise StopOwned('SERVICE_DISABLED_BY_OTHER_OWNER')
        if sha(read_bytes(self.p['live_plist']))!=self.p['after_plist_sha256']:raise StopOwned('POST_CAS_PLIST_MISMATCH')
        self.command(['/bin/launchctl','bootstrap',self.p['domain'],self.p['live_plist']])
    def verified_python_binary(self):
        expected=self.p['expected_python_resolved']
        if str(Path(self.p['expected_python']).resolve(strict=True))!=expected:
            raise StopOwned('EXPECTED_PYTHON_RESOLVED_BINDING_CHANGED')
        if sha(read_bytes(expected))!=self.p['expected_python_binary_sha256']:
            raise StopOwned('EXPECTED_PYTHON_BINARY_SHA_CHANGED')
        return expected
    def verify_python_executable(self,identity):
        expected=self.verified_python_binary()
        result=self.command(['/usr/sbin/lsof','-a','-p',str(identity['pid']),'-d','txt','-Fn'])
        mapped=[line[1:] for line in result.stdout.splitlines() if line.startswith('n')]
        if expected not in mapped:raise StopOwned('NEW_PYTHON_NATIVE_EXECUTABLE_MISMATCH')
        if self.identity(identity['pid'])!=identity:raise StopOwned('NEW_OWNER_CHANGED_DURING_EXECUTABLE_READBACK')
    def new_binding(self):
        s=self.service()
        if not s['loaded'] or not s.get('pid'):return None
        identity=self.identity(s['pid'])
        if not identity:return None
        if self.cwd(identity['pid'])!=self.p['new_root']:raise StopOwned('NEW_ROOT_READBACK_MISMATCH')
        expected={'V35_APP_ROOT':self.p['new_root'],'V35_RELEASE_ID':self.p['new_release_id'],
            'V35_RELEASE_MANIFEST_PATH':str(Path(self.p['new_root']).parent/'release-manifest.json'),
            'V35_RELEASE_MANIFEST_SHA256':self.p['new_manifest_sha256']}
        for key,value in expected.items():
            observed=re.findall(r'^\s*'+key+r'\s*=>\s*(.*?)\s*$',s['text'],re.M)
            if not observed or set(observed)!={value}:raise StopOwned('NEW_ENV_BINDING_MISMATCH:'+key)
        if '-m ops.run_v35_macos_scheduler_daemon' not in identity['command']:
            expected_wrapper=str(Path(self.p['new_root'])/'ops/launch_v35_macos_scheduler.sh')
            if identity['command']=='/bin/bash '+expected_wrapper:return None
            raise StopOwned('UNKNOWN_NEW_OWNER_AFTER_BOOTSTRAP')
        # macOS ps renders argv without shell-quoting paths containing spaces.
        # Compare the full frozen absolute interpreter prefix and its boundary;
        # parse only the known option/module suffix, never the path as shell text.
        python=self.p['expected_python']
        if not identity['command'].startswith(python+' '):raise StopOwned('NEW_PYTHON_READBACK_MISMATCH')
        suffix=identity['command'][len(python):].lstrip()
        if not re.match(r'-S\s+-m\s+ops\.run_v35_macos_scheduler_daemon(?:\s|$)',suffix):
            raise StopOwned('UNKNOWN_NEW_OWNER_AFTER_BOOTSTRAP')
        self.verify_python_executable(identity)
        self.verify_package()
        if sha(read_bytes(self.p['live_plist']))!=self.p['after_plist_sha256']:raise StopOwned('FINAL_PLIST_SHA')
        return identity
    def wait(self):time.sleep(.5)

class Recipe:
    def __init__(self,ops,journal):self.ops=ops;self.j=journal;self.last_wait=None
    def wait_owned(self,reason):
        if reason!=self.last_wait:
            self.j.save(wait_reason=reason,ownership='RETAINED_UNTIL_DONE_OR_EXPLICIT_RECONCILIATION')
            print(json.dumps({'phase':self.j.data['phase'],'wait':reason,'checkpoint':str(self.j.path)}),flush=True)
            self.last_wait=reason
        self.ops.wait()
    def ready(self,old):
        one=self.ops.safe_pdf_boundary(old)
        if not one['ready']:return one
        two=self.ops.safe_pdf_boundary(old)
        if not two['ready'] or one['epoch']!=two['epoch']:raise StopOwned('FRESH_PDF_CLAIM_BOUNDARY_CHANGED')
        return two
    def run(self,expected_pid=None):
        d=self.j.data
        phase=d['phase']
        try:
            while True:
                phase=d['phase']
                if phase=='PREPARED':
                    self.ops.verify_package();old=self.ops.initial_old(expected_pid)
                    self.j.save('WAIT_SAFE_BEFORE_ARM',old=old,original_disabled=False)
                elif phase=='WAIT_SAFE_BEFORE_ARM':
                    proof=self.ready(d['old'])
                    if not proof['ready']:self.wait_owned(proof['reason']);continue
                    self.j.intent('ARM_REQUESTED','launchctl debug next invocation /bin/sleep')
                    bridge.prepare(self.j,self.ops)
                elif phase=='ARM_REQUESTED':
                    bridge.accept(self.j,self.ops)
                elif phase=='ARMED':
                    ob=self.ops.observe(d['old'])
                    if not ob['old_alive']:
                        self.j.save('DRAINING',old_exited_before_term=True);continue
                    if ob['owner']!=d['old']:raise StopOwned('OWNER_CHANGED_AFTER_ARM_NO_SIGNAL')
                    proof=self.ready(d['old'])
                    if not proof['ready']:self.wait_owned(proof['reason']);continue
                    self.j.intent('TERM_REQUESTED','SIGTERM exact original main PID only')
                    try:
                        actual_proof=self.ops.term_old(d['old'])
                    except BoundaryRevoked:
                        self.j.save('ARMED',term_not_sent='FRESH_PDF_BOUNDARY_REVOKED')
                        self.wait_owned('RECHECK_SAFE_PDF_BOUNDARY_NO_TERM_WAS_SENT');continue
                    self.j.save('DRAINING',term_delivered=True,pdf_boundary=actual_proof or proof)
                elif phase=='TERM_REQUESTED':
                    # A crash can occur on either side of kill(). Do not repeat
                    # an unknown action. Observed old exit safely reconciles it.
                    ob=self.ops.observe(d['old'])
                    if ob['old_alive']:raise StopOwned('TERM_OUTCOME_UNKNOWN_NO_REPEAT')
                    self.j.save('DRAINING',term_delivery='UNKNOWN_OLD_EXIT_CONFIRMED_NO_REPEAT')
                elif phase=='DRAINING':
                    ob=self.ops.observe(d['old'])
                    if ob['old_alive']:
                        if ob['owner']!=d['old']:raise StopOwned('LABEL_OWNER_CHANGED_WHILE_OLD_ALIVE')
                        seen_before=dict(d['descendants_seen'])
                        for pid in self.ops.descendants(d['old']['pid'],ob['rows']):
                            identity=self.ops.identity(pid,ob['rows'])
                            if identity:d['descendants_seen'][str(pid)]=identity
                        if d['descendants_seen']!=seen_before:self.j.save()
                        self.wait_owned('ORIGINAL_MAIN_AND_HOOKS_DRAINING_NO_BOOTOUT_TIMEOUT');continue
                    if not ob['owner']:
                        self.wait_owned('ORIGINAL_EXITED_WAIT_DOCUMENTED_NEXT_INVOCATION_GUARD');continue
                    guard=self.ops.guard(ob)
                    if not self.ops.old_children_finished(d['descendants_seen']):
                        self.wait_owned('OLD_DESCENDANTS_FINISHING_NO_SIGNALS');continue
                    self.j.save('GUARD_VERIFIED',guard=guard,debug_override_disposition='CONSUMED_BY_VERIFIED_GUARD')
                elif phase=='GUARD_VERIFIED':
                    self.j.intent('GUARD_BOOTOUT_REQUESTED','bootout verified harmless sleep guard only')
                    self.ops.bootout_guard(d['guard'],d['old'])
                    self.j.save('GUARD_REMOVING')
                elif phase=='GUARD_BOOTOUT_REQUESTED':
                    # Unknown action outcome is reconciled only by absence.
                    if self.ops.service()['loaded']:raise StopOwned('GUARD_BOOTOUT_OUTCOME_UNKNOWN_NO_RETRY')
                    self.j.save('GUARD_REMOVING')
                elif phase=='GUARD_REMOVING':
                    self.ops.assert_unloaded()
                    if not self.ops.gone(d['guard']):self.wait_owned('VERIFIED_GUARD_EXITING');continue
                    self.j.intent('PLIST_CAS_REQUESTED','CAS exact already reviewed proposed plist')
                    self.ops.cas_plist();self.j.save('PLIST_APPLIED')
                elif phase=='PLIST_CAS_REQUESTED':
                    # File SHA makes this atomic action reconcilable, unlike debug.
                    self.ops.cas_plist();self.j.save('PLIST_APPLIED')
                elif phase=='PLIST_APPLIED':
                    self.j.intent('BOOTSTRAP_REQUESTED','bootstrap same label with reviewed binding')
                    self.ops.bootstrap();self.j.save('READBACK')
                elif phase in {'BOOTSTRAP_REQUESTED','READBACK'}:
                    if phase=='BOOTSTRAP_REQUESTED' and not self.ops.service()['loaded']:
                        raise StopOwned('BOOTSTRAP_OUTCOME_UNKNOWN_SERVICE_ABSENT_NO_RETRY')
                    identity=self.ops.new_binding()
                    if not identity:
                        self.wait_owned('REVIEWED_NEW_BINDING_STARTING_READBACK_ONLY');continue
                    self.j.save('DONE',new=identity,ownership='COMPLETED',business_acceptance='NOT_CLAIMED',armed=False)
                    return d
                elif phase=='DONE':
                    self.j.save('DONE',ownership='COMPLETED',armed=False)
                    return d
                else:raise StopOwned('UNKNOWN_PHASE:'+phase)
        except BaseException as error:
            # Intent phase is retained so the single owned operation can be
            # resumed/reconciled. No unarm, new-PID stop or rollback guess.
            self.j.save(last_error=type(error).__name__+':'+str(error),
                ownership='RETAINED_RECONCILIATION_REQUIRED' if d.get('armed') or d['phase']=='ARM_REQUESTED' else 'UNARMED_STOPPED')
            raise

def approve_execution(receipt_path,expected_sha):
    raw=read_bytes(receipt_path)
    if sha(raw)!=expected_sha:raise StopOwned('FINAL_REVIEW_RECEIPT_SHA')
    r=json.loads(raw);manifest_raw=read_bytes(ROOT/'CASE_MANIFEST.json');manifest_sha=sha(manifest_raw)
    manifest=json.loads(manifest_raw)
    for relative,expected in manifest['files'].items():
        path=ROOT/relative
        if not path.resolve().is_relative_to(ROOT) or sha(read_bytes(path))!=expected:
            raise StopOwned('FINAL_CASE_FILE_CHANGED:'+relative)
    if r.get('verdict') not in {'PASS','REVIEWED/PASS'} or r.get('case_manifest_sha256')!=manifest_sha:
        raise StopOwned('FINAL_CASE_REVIEW_NOT_PASS_OR_SCOPE_MISMATCH')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute-reviewed',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--expected-old-pid',type=int)
    parser.add_argument('--review-receipt',type=Path)
    parser.add_argument('--review-sha256')
    parser.add_argument('--checkpoint',type=Path,default=ROOT/'owned-checkpoint.json')
    args=parser.parse_args()
    if not (ROOT/'PLAN.json').exists():
        print(json.dumps({'status':'FINAL_R2_BINDING_PENDING_NO_LIVE_ACTION'}));return 2
    plan=read_json(ROOT/'PLAN.json')
    if not args.execute_reviewed:
        print(json.dumps({'status':'PLAN_ONLY_NO_LIVE_ACTION','plan':plan,'checkpoint':str(args.checkpoint)},ensure_ascii=False,indent=2));return 0
    if not args.review_receipt or not args.review_sha256:raise StopOwned('FINAL_REVIEW_RECEIPT_REQUIRED')
    approve_execution(args.review_receipt,args.review_sha256)
    if not args.resume and args.expected_old_pid is None:raise StopOwned('FRESH_EXPECTED_OLD_PID_REQUIRED')
    journal=Journal(args.checkpoint,plan,resume=args.resume)
    try:
        result=Recipe(LiveOps(plan),journal).run(args.expected_old_pid)
        print(json.dumps({'phase':result['phase'],'checkpoint':str(journal.path),'new':result.get('new')},ensure_ascii=False));return 0
    except BaseException as error:
        print(json.dumps({'status':'STOP_WITH_OWNED_CHECKPOINT','phase':journal.data['phase'],
            'reason':str(error),'checkpoint':str(journal.path),'resume_required':journal.data.get('armed') or journal.data['phase'] not in {'PREPARED','WAIT_SAFE_BEFORE_ARM'}},ensure_ascii=False),file=sys.stderr)
        return 2
    finally:journal.close()

if __name__=='__main__':raise SystemExit(main())
