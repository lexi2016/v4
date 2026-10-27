"""One reviewed publication of this case; no actions in default CLI mode.

Uses original owner/queue/lane/API/collector locks and original CAS/reverse-CAS.
Only the Root controller may execute it after a fresh explicit handoff/review.
"""
from __future__ import annotations
import argparse, fcntl, json, os, re, stat, subprocess, sys, time
from contextlib import ExitStack, contextmanager
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import prepare as prep

TZ=ZoneInfo('Asia/Shanghai')


def boundary(moment,windows,margin=300):
    if moment.tzinfo is None:raise ValueError('AWARE_CONTROL_CLOCK_REQUIRED')
    moment=moment.astimezone(TZ)
    for start,end in windows:
        begin=moment.replace(hour=int(start[:2]),minute=int(start[2:]),second=0,microsecond=0)
        finish=moment.replace(hour=int(end[:2]),minute=int(end[2:]),second=0,microsecond=0)+timedelta(minutes=1)
        if begin-timedelta(seconds=margin)<=moment<finish:return {'ready':False,'reason':'PROTECTED_BUSINESS_WINDOW','start':start,'end':end}
    return {'ready':True}


@contextmanager
def same_inode_guard(row,*,wait_seconds=0,check_window=None):
    if wait_seconds<0:raise ValueError('NEGATIVE_LOCK_WAIT_BUDGET')
    fd=os.open(row['path'],os.O_RDWR|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):raise RuntimeError('ORIGINAL_LOCK_NOT_REGULAR')
        if (info.st_dev,info.st_ino)!=(row['device'],row['inode']):raise RuntimeError('ORIGINAL_LOCK_INODE_DRIFT')
        deadline=time.monotonic()+wait_seconds;retry=False
        while True:
            if check_window is not None:check_window()
            if retry and time.monotonic()>=deadline:raise RuntimeError('PENDING_ORIGINAL_LOCK_BUSY')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise RuntimeError('PENDING_ORIGINAL_LOCK_BUSY') from error
                retry=True
                time.sleep(min(0.25,remaining))
            else:break
        if check_window is not None:check_window()
        yield fd
    finally:os.close(fd)  # no unlink/recreate/LOCK_UN of a shared inherited description


def require_scope(plan):
    if plan.get('scope')!=prep.SCOPE:raise ValueError('BUSINESS_SCOPE_REQUIRED_OLD_PLAN_NOT_EXECUTABLE')
    rows=plan['operations']
    if len(rows)!=5 or {row['component'] for row in rows}!=set(prep.LABELS):raise ValueError('EXACT_FIVE_SERVICE_OPERATIONS_REQUIRED')
    for row in rows:
        label=prep.LABELS[row['component']]
        if row['label']!=label or row['plist']!=str(Path.home()/'Library/LaunchAgents'/(label+'.plist')):raise ValueError('FIXED_SERVICE_SCOPE')
    if any(plan.get(key) is not False for key in ('production_allowed','buy_gate_updated','orders_sent')):raise ValueError('UNSAFE_PLAN')
    mode=plan.get('control_mode','FULL')
    if mode not in ('FULL',prep.R4_MODE):raise ValueError('UNKNOWN_CONTROL_MODE')
    if mode==prep.R4_MODE:
        for row in rows:
            key=row['component'];base=plan['base'][key];meta=plan['components'][key]
            same=(meta['release_root']==str(Path(base['app_root']).parent) and meta['candidate_app']==base['app_root']
                and meta['path']==base['manifest'] and meta['sha256']==base['manifest_sha256']
                and meta['application_inventory_sha256']==base['application_inventory_sha256']
                and row['before_sha256']==row['after_sha256']==base['plist_sha256'])
            if key in prep.R4_UNCHANGED:
                if not same:raise ValueError('UNCHANGED_IDENTITY_DRIFT:'+key)
            elif (meta['release_root']==str(Path(base['app_root']).parent) or row['before_sha256']==row['after_sha256']):
                raise ValueError('R4_CHANGED_IDENTITY_AMBIGUOUS:'+key)


def validate_unchanged_prior(plan,old):
    if plan.get('control_mode','FULL')!=prep.R4_MODE:return
    for key in prep.R4_UNCHANGED:
        current=plan['components'][key];previous=old['components'][key]
        if any(current[field]!=previous[field] for field in ('candidate_app','path','release_root','sha256','application_inventory_sha256')):
            raise ValueError('UNCHANGED_PRIOR_IDENTITY_DRIFT:'+key)
        now=next(r for r in plan['operations'] if r['component']==key)
        before=next(r for r in old['operations'] if r['component']==key)
        if any(now[field]!=before[field] for field in ('label','plist','before_sha256','after_sha256')):
            raise ValueError('UNCHANGED_PRIOR_PLIST_DRIFT:'+key)


def idle_facts(rows,old_pid,before_pdf_lock,cycle,unfinished):
    """No pending-index gate. Existing active work must finish naturally.

    The original ingestion lock excludes document admission/OCR. A tick child
    born only after that lock was acquired cannot have admitted a document;
    original daemon shutdown may reap that lock-waiting child. A preexisting
    child, enqueue producer or any other descendant is never treated as idle.
    """
    descendants=set();parents={old_pid}
    while parents:
        children={pid for pid,row in rows.items() if row['ppid'] in parents and pid not in descendants}
        descendants.update(children);parents=children
    blocked=[]
    for pid in descendants:
        command=rows[pid]['command']
        new_tick=pid not in before_pdf_lock and '-m ops.run_zsxq_hourly_delta ' in command and '--pdf-queue-tick' in command
        if new_tick:blocked.append(pid)
        else:return {'ready':False,'reason':'EXISTING_MAIN_CHILD_ACTIVE','pid':pid}
    for pid,row in rows.items():
        if '--pdf-queue-tick' in row['command'] and pid not in blocked:return {'ready':False,'reason':'EXISTING_PDF_CHILD_ACTIVE','pid':pid}
    if unfinished:return {'ready':False,'reason':'UNFINISHED_MAIN_CLAIM'}
    if not cycle:return {'ready':False,'reason':'CURRENT_MAIN_IDLE_CYCLE_UNCONFIRMED'}
    return {'ready':True,'unadmitted_post_lock_pdf_children':blocked}


class Controller:
    def __init__(self,plan_path):
        self.path=Path(plan_path).absolute();self.p=prep.load(self.path);require_scope(self.p)
        self.journal=None;self.phase='FORWARD';self.attempted=set();self.uncertain=False;self.pdf_before=set()
        prep.pin(self.p['prepare_path'],self.p['prepare_sha256'])
        for row in self.p['helpers'].values():prep.pin(row['path'],row['sha256'])
        self.integration=prep.module('publication_integrator',self.p['helpers']['integration']['path'])
        self.op=prep.module('publication_operator',self.p['helpers']['operator']['path'])
        self.guard_module=prep.module('publication_main_guard',self.p['helpers']['main_guard']['path'])
        contract=self.p['api_module_contract'];prep.pin(contract['path'],contract['sha256']);self.integration.MODULE_CONTRACT_PATH=Path(contract['path'])
        params=dict(self.p['main_guard_parameters']);main=self.p['base']['main'];target=self.p['components']['main']
        params.update(old_root=main['app_root'],live_plist=main['plist'],before_plist_sha256=main['plist_sha256'],
            old_daemon_sha256=prep.sha(Path(main['app_root'])/'ops/run_v35_macos_scheduler_daemon.py'),
            new_root=str(Path(target['release_root'])/'app'),new_release_id=Path(target['release_root']).name,new_manifest_sha256=target['sha256'])
        self.g=self.guard_module.LiveOps(params)
        self.op.run=self.read_command  # original operator parser, original bounded subprocess owner

    def read_command(self,args):
        r=self.g.command(['/bin/launchctl',*args],allow_missing=True,timeout=15)
        convert=lambda value:value.encode() if isinstance(value,str) else value
        return subprocess.CompletedProcess(args,r.returncode,convert(r.stdout),convert(r.stderr))

    def record(self,event,**fields):
        row={'at':datetime.now(TZ).isoformat(),'event':event,**fields}
        self.journal.write(json.dumps(row,ensure_ascii=False)+'\n');self.journal.flush();os.fsync(self.journal.fileno())
        print(json.dumps(row,ensure_ascii=False),flush=True)

    def row(self,key):return self.op.op(self.p,key)

    def cas(self,after=False):
        owner=self.p['locks']['owner'];prep.pin(owner['marker'],owner['marker_sha256'])
        for row in self.p['operations']:prep.pin(row['plist'],row['after_sha256'] if after else row['before_sha256'])
        for row in self.p['frozen_inputs'].values():prep.pin(row['path'],row['sha256'])
        prep.pin(self.p['prior_plan'],self.p['prior_plan_sha256']);prep.pin(self.p['config_path'],self.p['config_sha256'])
        for row in prep.load(self.p['frozen_inputs']['source_freeze']['path'])['overlay_entries']:prep.pin(row['source_path'],row['after_sha256'])
        for row in self.p['read_only_services']:prep.pin(row['plist'],row['plist_sha256'])

    def command(self,args):
        valid=False
        allowed={'api','collector'} if self.p.get('control_mode','FULL')==prep.R4_MODE else set(prep.LABELS)
        if args[0] in ('bootout','enable','disable'):
            valid=len(args)==2 and args[1] in {f'gui/{os.getuid()}/'+prep.LABELS[key] for key in allowed}
            if args[0] in ('enable','disable'):valid=valid and args[1].endswith('/'+prep.LABELS['collector'])
        elif args[0]=='bootstrap':valid=len(args)==3 and args[1]==f'gui/{os.getuid()}' and args[2] in {row['plist'] for row in self.p['operations'] if row['component'] in allowed}
        if not valid:raise RuntimeError('SERVICE_ACTION_OUTSIDE_FIXED_SCOPE')
        if self.uncertain and self.phase=='FORWARD':raise RuntimeError('UNKNOWN_PRIOR_OUTCOME_REQUIRES_RECONCILIATION')
        token=(self.phase,tuple(args))
        if token in self.attempted:raise RuntimeError('NO_BLIND_SERVICE_RETRY')
        self.attempted.add(token);self.record('COMMAND_INTENT',args=args,phase=self.phase)
        try:r=self.read_command(args)
        except BaseException as error:
            self.uncertain=True;self.record('COMMAND_OUTCOME_UNKNOWN',args=args,error=repr(error));raise
        self.record('COMMAND_RESULT',args=args,returncode=r.returncode,stdout=r.stdout.decode(errors='replace'),stderr=r.stderr.decode(errors='replace'))
        if r.returncode:self.uncertain=True;raise RuntimeError('COMMAND_NONZERO_RECONCILE_GUARDS_RETAINED')
        return r

    def window(self):
        result=boundary(datetime.now(TZ),self.p['protected_windows'],self.p['minimum_margin_seconds'])
        if not result['ready']:raise RuntimeError('PENDING_PROTECTED_BUSINESS_WINDOW')

    def idle(self,old):
        self.g.check_old(old);self.window();self.stage_idle();rows=self.g.processes()
        log=Path(self.p['main_guard_parameters']['log_path'])
        with log.open('rb') as stream:stream.seek(max(0,log.stat().st_size-4*1024*1024));raw=stream.read()
        records=[]
        for line in raw.splitlines():
            try:value=json.loads(line)
            except (ValueError,UnicodeDecodeError):continue
            if isinstance(value,dict) and value.get('status')=='DAEMON_DISPATCH_CYCLE':records.append(value)
        last=records[-1] if records else {};minute=datetime.now(TZ).strftime('%Y-%m-%dT%H:%M')
        cycle=(last.get('minute')==minute and last.get('active_children')==0 and last.get('queued_slots')==0)
        result=idle_facts(rows,old['pid'],self.pdf_before,cycle,self.g.claims(old['pid'])['unfinished'])
        if not result['ready']:raise RuntimeError('PENDING_'+result['reason'])
        return result

    def stage_idle(self):
        for key in ('stage','a_precapture'):
            pid=self.op.label_state(self.row(key)['label'])
            if pid not in (None,0):raise RuntimeError('PENDING_ORIGINAL_STAGE_ACTIVE:'+key)
        roots={self.p['base']['stage']['app_root'],str(Path(self.p['components']['stage']['release_root'])/'app')}
        for row in self.g.processes().values():
            if any(root+'/ops/run_stage_center_nodes.py' in row['command'] for root in roots):
                raise RuntimeError('PENDING_ORIGINAL_STAGE_PROCESS_ACTIVE')

    def verify_stage(self,plan):
        observed={}
        for key in ('stage','a_precapture'):
            meta=plan['components'][key];root=Path(meta['release_root'])/'app';row=self.op.op(plan,key)
            if self.op.label_state(row['label']) is None:raise RuntimeError('STAGE_LABEL_UNLOADED:'+key)
            result=self.read_command(['print',f'gui/{os.getuid()}/'+row['label']]);text=result.stdout.decode(errors='replace')
            if result.returncode or str(root/'ops/run_stage_center_nodes.py') not in text or str(root/'stage_center_tick_config.json') not in text:
                raise RuntimeError('STAGE_LOADED_DEFINITION_MISMATCH:'+key)
            value=plistlib_read(row['plist']);prep.validate_stage_plist(value,value,root,root,key);prep.assert_safety(value)
            env=prep.environment(value)
            for field,expected in {'V35_RELEASE_ID':root.parent.name,'V35_RELEASE_MANIFEST_SHA256':meta['sha256']}.items():
                if env.get(field)!=expected:raise RuntimeError('STAGE_ENV_IDENTITY_MISMATCH:'+field)
            pid=self.op.label_state(row['label'])
            if pid:
                identity=self.g.identity(pid)
                if not identity or str(root/'ops/run_stage_center_nodes.py') not in identity['command'] or self.g.cwd(pid)!=str(root):raise RuntimeError('STAGE_PID_IDENTITY_MISMATCH')
                self.g.verify_python_executable(identity)
            observed[key]={'pid':pid,'launcher':str(root/'ops/run_stage_center_nodes.py'),
                'launcher_sha256':prep.sha(root/'ops/run_stage_center_nodes.py'),'config_sha256':prep.sha(root/'stage_center_tick_config.json')}
        return observed

    def verify_unchanged(self):
        result=[]
        for row in self.p['read_only_services']:
            prep.pin(row['plist'],row['plist_sha256'])
            target=f"gui/{os.getuid()}/"+row['label'];observed=self.read_command(['print',target])
            if observed.returncode or row['expected_launcher'] not in observed.stdout.decode(errors='replace'):
                raise RuntimeError('READ_ONLY_SERVICE_BINDING_DRIFT:'+row['label'])
            prep.pin(row['expected_launcher'],row['launcher_sha256']);result.append({'label':row['label'],'status':'UNCHANGED_BINDING_VERIFIED'})
        return result

    def verify_main(self,plan):
        row=self.op.op(plan,'main');meta=plan['components']['main'];root=str(Path(meta['release_root'])/'app')
        service=self.g.service()
        if not service.get('pid'):raise RuntimeError('MAIN_PID_NOT_READY')
        identity=self.g.identity(service['pid'])
        if not identity or '-m ops.run_v35_macos_scheduler_daemon' not in identity['command'] or self.g.cwd(identity['pid'])!=root:raise RuntimeError('MAIN_ACTUAL_PID_ROOT_MISMATCH')
        if root+'/ops/launch_v35_macos_scheduler.sh' not in service.get('text',''):raise RuntimeError('MAIN_LOADED_LAUNCHER_MISMATCH')
        self.g.verify_python_executable(identity)
        value=plistlib_read(row['plist']);prep.require_main_launcher(value,root)
        env=prep.environment(value)
        for key,expected in {'V35_APP_ROOT':root,'V35_RELEASE_ID':Path(meta['release_root']).name,'V35_RELEASE_MANIFEST_SHA256':meta['sha256']}.items():
            if env.get(key)!=expected:raise RuntimeError('MAIN_ENV_MISMATCH:'+key)
        self.op.verify_release(plan,'main')
        return {'pid_identity':identity,'launcher':root+'/ops/launch_v35_macos_scheduler.sh',
            'module_sha256':{rel:prep.sha(Path(root)/rel) for rel in ('ops/run_v35_macos_scheduler_daemon.py','infrastructure/zsxq_pdf_ingestion.py')}}

    def verify(self,plan):
        self.verify_inventory(plan)
        self.verify_api_binding(plan)
        main=self.verify_main(plan);observed=self.op.observe_api(plan);self.op.validate_api_observation(plan,observed)
        return {'main':main,'api':observed,'stage':self.verify_stage(plan),'unchanged_services':self.verify_unchanged()}

    def verify_api_candidate(self,*,active_pointer,lease=None):
        with prep.api_identity_scope(self.integration,self.p['base']['api'],self.p['api_module_contract']):
            return self.integration.verify_api_release_candidate(candidate_root=Path(self.p['components']['api']['release_root']),
                active_api_plist_path=Path(self.row('api')['plist']),expected_manifest_sha256=self.p['components']['api']['sha256'],
                active_pointer=active_pointer,lock_lease=lease,require_shared_lock=lease is not None)

    def verify_api_binding(self,plan):
        if plan['components']['api']['release_root']==self.p['components']['api']['release_root']:
            return self.verify_api_candidate(active_pointer='candidate')
        with prep.api_identity_scope(self.integration,self.p['base']['api'],self.p['api_module_contract']):
            current=self.integration.read_active_release(Path(self.row('api')['plist']))
        if self.integration._base_binding(current)!=self.p['api_baseline']:raise RuntimeError('ACTUAL_API_ROLLBACK_BASE_DRIFT')
        return current

    def verify_inventory(self,plan,*,candidate=False):
        for key in prep.LABELS:
            meta=plan['components'][key];prep.pin(meta['path'],meta['sha256'])
            manifest=prep.load(meta['path']);expected=meta['application_inventory_sha256']
            root=Path(meta['candidate_app']) if candidate else Path(meta['release_root'])/'app'
            if not candidate:prep.pin(root.parent/'release-manifest.json',meta['sha256'])
            actual=self.integration.inventory_tree(root)
            frozen=manifest.get('application_inventory')
            if frozen is not None and (frozen['aggregate_sha256']!=expected or frozen['entries']!=actual):raise RuntimeError('COMPLETE_INVENTORY_DRIFT:'+key)
            if self.integration.inventory_digest(actual)!=expected:raise RuntimeError('COMPLETE_INVENTORY_DRIFT:'+key)

    def stage_verified(self):
        self.verify_inventory(self.p,candidate=True)
        self.op.stage(self.p)
        self.verify_inventory(self.p)

    def verify_graph(self,plan):
        meta=plan['components']['collector'];root=str(Path(meta['release_root'])/'app')
        target=f'gui/{os.getuid()}/'+prep.LABELS['collector']
        result=self.read_command(['print',target]);text=result.stdout.decode(errors='replace')
        if result.returncode or root+'/ops/collect_runtime_graph.py' not in text or plan['config_target'] not in text:
            raise RuntimeError('GRAPH_LOADED_DEFINITION_MISMATCH')
        disabled=self.read_command(['print-disabled',f'gui/{os.getuid()}'])
        if disabled.returncode or re.search(r'"com\.lexi\.v35\.runtime-graph"\s*=>\s*true',disabled.stdout.decode(errors='replace')):
            raise RuntimeError('GRAPH_ENABLED_STATE_UNCONFIRMED')
        self.op.verify_release(plan,'collector')
        return {'loaded_definition_root':root,'config_sha256':plan['config_sha256']}

    def wait_verify(self,plan):
        for attempt in range(30):
            try:return self.verify(plan)
            except Exception as error:
                self.record('READONLY_READBACK_PENDING',attempt=attempt,error=repr(error))
                if attempt==29:raise
                time.sleep(1)

    def binding(self,key,old):
        validate_unchanged_prior(self.p,old)
        row=self.row(key);digest=prep.sha(row['plist'])
        if digest not in (row['before_sha256'],row['after_sha256']):raise RuntimeError('UNKNOWN_PLIST_BYTES:'+key)
        pid=self.op.label_state(row['label'])
        unchanged=self.p.get('control_mode','FULL')==prep.R4_MODE and key in prep.R4_UNCHANGED
        if pid is None:return {'loaded':False,'disk':'UNCHANGED' if unchanged else ('OLD' if digest==row['before_sha256'] else 'NEW')}
        text=self.read_command(['print',f'gui/{os.getuid()}/'+row['label']]).stdout.decode(errors='replace')
        roots={'OLD':old['components'][key]['release_root'],'NEW':self.p['components'][key]['release_root']}
        suffix={'main':'/app/ops/launch_v35_macos_scheduler.sh','collector':'/app/ops/collect_runtime_graph.py','api':'/app','stage':'/app/ops/run_stage_center_nodes.py','a_precapture':'/app/ops/run_stage_center_nodes.py'}[key]
        candidates=[version for version,root in roots.items() if root+suffix in text]
        if key!='collector' and pid:
            cwd=self.g.cwd(pid);candidates=[version for version,root in roots.items() if cwd==str(Path(root)/'app')]
        if unchanged:
            if set(candidates)!={'OLD','NEW'}:raise RuntimeError('UNKNOWN_LOADED_DEFINITION:'+key)
            return {'loaded':True,'pid':pid,'version':'UNCHANGED','disk':'UNCHANGED'}
        if len(candidates)!=1:raise RuntimeError('UNKNOWN_LOADED_DEFINITION:'+key)
        return {'loaded':True,'pid':pid,'version':candidates[0],'disk':'OLD' if digest==row['before_sha256'] else 'NEW'}

    def wait_exit(self,identity):
        if identity is None:raise RuntimeError('EXIT_PID_IDENTITY_UNCONFIRMED')
        for attempt in range(30):
            current=self.g.identity(identity['pid'])
            if current is None:return
            if current!=identity:raise RuntimeError('EXIT_PID_REUSED_NO_FURTHER_ACTION')
            if attempt==29:raise RuntimeError('OLD_PROCESS_EXIT_UNCONFIRMED')
            time.sleep(1)

    def unload(self,key):
        pid=self.op.label_state(self.row(key)['label'])
        if pid is None:return
        if key in ('stage','a_precapture') and pid!=0:raise RuntimeError('STAGE_CHILD_MUST_FINISH_NATURALLY')
        if key=='collector' and pid!=0:raise RuntimeError('GRAPH_CHILD_MUST_FINISH_NATURALLY')
        if key=='main' and pid:
            rows=self.g.processes();facts=idle_facts(rows,pid,self.pdf_before,True,[])
            if not facts['ready']:raise RuntimeError('MAIN_CHILD_MUST_FINISH_NATURALLY')
        identity=self.g.identity(pid) if pid else None
        self.command(['bootout',f'gui/{os.getuid()}/'+self.row(key)['label']])
        if pid:self.wait_exit(identity)

    def bootstrap(self,key):self.command(['bootstrap',f'gui/{os.getuid()}',self.row(key)['plist']])

    def rollback(self,old):
        self.phase='ROLLBACK'
        states={key:self.binding(key,old) for key in prep.LABELS}
        if self.p.get('control_mode','FULL')==prep.R4_MODE:
            for key in prep.R4_UNCHANGED:
                if not states[key]['loaded'] or states[key].get('version')!='UNCHANGED':raise RuntimeError('UNCHANGED_SERVICE_NOT_BOUND:'+key)
        for key in ('collector','stage','a_precapture','main','api'):
            if self.p.get('control_mode','FULL')==prep.R4_MODE and key in prep.R4_UNCHANGED:
                continue
            if states[key].get('version')=='OLD' and states[key]['disk']=='OLD':continue
            self.unload(key);self.record('ROLLBACK_PLIST_INTENT',component=key)
            self.op.install_plist(self.row(key),rollback=True)
        for key in ('main','api','stage','a_precapture'):
            if self.p.get('control_mode','FULL')==prep.R4_MODE and key in prep.R4_UNCHANGED:continue
            if self.op.label_state(self.row(key)['label']) is None:self.bootstrap(key)
        self.wait_verify(old)
        if self.op.label_state(self.row('collector')['label']) is None:
            self.op.activate_graph(old,observe=self.op.observe_api,command=self.command,state=self.op.label_state)
        self.cas(after=False);self.verify_graph(old);return self.verify(old)

    def execute(self,review_path,review_sha):
        try:return self._execute(review_path,review_sha)
        finally:
            if self.journal is not None:self.journal.close()  # includes early failure and successful recovery

    def _execute(self,review_path,review_sha):
        prep.pin(review_path,review_sha);review=prep.load(review_path)
        if (review.get('verdict')!='PASS' or review.get('deployment_plan_sha256')!=prep.sha(self.path)
            or review.get('controller_sha256')!=prep.sha(__file__) or review.get('prepare_sha256')!=self.p['prepare_sha256']
            or review.get('source_freeze_sha256')!=self.p['frozen_inputs']['source_freeze']['sha256']):raise RuntimeError('SCOPED_CONTROL_REVIEW_REQUIRED')
        h=prep.handoff_ready(self.p['handoff']['path'],self.p['handoff']['sha256'])
        if h.get('deployment_executable') is not True:raise RuntimeError('PENDING_PARENT_EXECUTION_AUTHORITY')
        self.window();self.cas()
        old=prep.load(self.p['prior_plan']);validate_unchanged_prior(self.p,old);owner=self.p['locks']['owner']
        prep.pin(owner['marker'],owner['marker_sha256']);marker=prep.load(owner['marker'])
        if marker.get('active') is not False or marker.get('phase')!='DONE':raise RuntimeError('PENDING_ORIGINAL_OWNER_ACTIVE')
        with ExitStack() as stack:
            stack.enter_context(same_inode_guard(owner))
            for lane in ('lane_A_LONG','lane_DEFAULT'):stack.enter_context(same_inode_guard(self.p['locks'][lane]))
            self.pdf_before=set(self.g.processes())
            stack.enter_context(same_inode_guard(self.p['locks']['pdf_ingestion'],wait_seconds=180,check_window=self.window))
            stack.enter_context(self.integration.announcement_flash_cutover_guard(Path(self.p['workbench_root']),timeout_seconds=0))
            lease=stack.enter_context(self.integration.shared_api_release_lock(Path(self.row('api')['plist']),timeout_seconds=0))
            stack.enter_context(same_inode_guard(self.p['locks']['collector']))
            identity=self.g.initial_old(self.p['base']['main']['pid']);self.idle(identity);self.cas();self.verify(old);self.verify_graph(old)
            self.journal=(self.path.parent/'ROOT_EXECUTION.jsonl').open('x')
            self.record('ORIGINAL_GUARDS_HELD',idle=self.idle(identity))
            started=False
            try:
                self.stage_verified()
                receipt_name=self.integration.DELTA_RECEIPT_NAME
                source=Path(self.p['components']['api']['path']).parent/receipt_name;target=Path(self.p['components']['api']['release_root'])/receipt_name
                if target.exists():prep.pin(target,prep.sha(source))
                else:
                    with target.open('xb') as stream:stream.write(source.read_bytes());stream.flush();os.fsync(stream.fileno())
                self.verify_api_candidate(active_pointer='base',lease=lease)
                self.idle(identity);self.cas();self.window();self.verify_inventory(self.p);started=True
                # PDF admission is locked and existing processing has finished.
                changed={'api','collector'} if self.p.get('control_mode','FULL')==prep.R4_MODE else set(prep.LABELS)
                for key in ('stage','a_precapture','main','collector','api'):
                    if key in changed:self.unload(key)
                for key in ('main','api','collector','stage','a_precapture'):
                    if key in changed:self.record('PLIST_CAS_INTENT',component=key);self.op.install_plist(self.row(key))
                for key in ('main','api','stage','a_precapture'):
                    if key in changed:self.bootstrap(key)
                self.wait_verify(self.p)
                self.op.activate_graph(self.p,observe=self.op.observe_api,command=self.command,state=self.op.label_state)
                self.cas(after=True);self.verify_graph(self.p);self.record('NEW_BINDINGS_VERIFIED',proof=self.verify(self.p))
            except BaseException as error:
                self.record('FAILURE_GUARDS_RETAINED',error=repr(error),service_actions_started=started)
                if not started:raise
                while True:
                    decision=sys.stdin.readline().strip()
                    try:
                        if decision=='RECONCILE':self.record('READONLY_RECONCILIATION',bindings={key:self.binding(key,old) for key in prep.LABELS})
                        elif decision=='ROLLBACK':self.record('OLD_BINDINGS_VERIFIED',proof=self.rollback(old));break
                        elif decision=='VERIFY_NEW':
                            self.cas(after=True);proof=self.verify(self.p)
                            if self.op.label_state(self.row('collector')['label']) is None:raise RuntimeError('GRAPH_NOT_LOADED')
                            self.verify_graph(self.p)
                            self.record('NEW_BINDINGS_VERIFIED',proof=proof);break
                        else:time.sleep(1)
                    except BaseException as recovery:self.record('RECOVERY_UNCONFIRMED_GUARDS_RETAINED',error=repr(recovery))
            self.record('GUARDS_RELEASE_NEXT')
        self.record('GUARDS_RELEASED')


def plistlib_read(path):
    import plistlib
    with Path(path).open('rb') as stream:return plistlib.load(stream)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--execute-reviewed',action='store_true');parser.add_argument('--review',type=Path);parser.add_argument('--review-sha');args=parser.parse_args()
    if not args.execute_reviewed:print(json.dumps({'status':'PLAN_ONLY','plan_sha256':prep.sha(args.plan)}))
    else:Controller(args.plan).execute(args.review,args.review_sha)
