"""Finite uid501 operation lease guardian; no root and no business writer.

Owns original-owner/API/announcement locks directly for the whole operation.
On abort it only consumes this operation's confirmed sleep guard and restores
service availability from the current exact before/after definition. It never
reverses a plist, a DONE publisher, accepted output or a healthy process.
"""
import argparse,contextlib,fcntl,importlib.util,json,os,re,stat,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('five_label_guarded',HERE/'four_role_control.py')
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)
R=C.recovery


def root_text(path):
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:
        raise C.Stop('ROOT_RECOVERY_ACK_METADATA')
    return C.read(path).decode().strip()



def validate_root_plan(p,root):
    if root_text(root/'plan_sha256')!=C.sha(C.canonical(p)):
        raise C.Stop('ROOT_ACK_PLAN_MISMATCH')


def abort_trigger(p,h,root,parent_current,parent_initial,now):
    if R.abort_path(HERE,h['operation_id']).exists():return 'COORDINATOR_REJECTED_ACK_OR_OPERATION'
    if parent_current!=parent_initial:return 'COORDINATOR_DIED_OR_IDENTITY_CHANGED'
    if now>h['expires_epoch']:return 'OPERATION_EXPIRED'
    if (root/'HELPER_ABORT').exists() or (root/'RESTORE_COMPLETE').exists():
        validate_root_plan(p,root)
        return 'ROOT_HELPER_PARTIAL_ARM_OR_ABORT'
    return None


def recovery_decision(initial,current,guard,restored,definition_known,children_alive,known_current=False):
    """Pure decision seam, separate from any launchctl action."""
    if not restored:return 'STOP_RESTORE_UNCONFIRMED'
    if not definition_known:return 'STOP_UNKNOWN_DEFINITION'
    if current is None:return 'KEEP_IDLE_OR_UNLOADED'
    if current==initial or known_current:return 'KEEP_HEALTHY_CURRENT_NO_SIGNAL'
    if not guard:return 'STOP_UNKNOWN_PROCESS_NO_SIGNAL'
    if children_alive:return 'WAIT_HEALTHY_CHILDREN_NO_SIGNAL'
    return 'REAP_OWN_SLEEP_GUARD_ONLY'


def current_definition(p,role,ops):
    row=C.row(p,role);digest=C.sha(C.read(row['plist']))
    if digest not in {row['before_sha256'],row['after_sha256']}:
        raise C.Stop('UNKNOWN_PLIST_OWNER_NO_RECONCILIATION')
    side='before' if digest==row['before_sha256'] else 'after'
    C.metadata.require(row['plist'],row['plist_metadata'])
    service=ops.service(role)
    definition=C.plistlib.loads(C.pin(row[side+'_file'],digest))
    if service['loaded']:
        text=service['text']
        def field(k):
            m=re.search(r'^\t'+re.escape(k)+r' = (.*)$',text,re.M);return m[1] if m else None
        match=re.search(r'^\targuments = \{\n(.*?)^\t\}',text,re.M|re.S)
        if (field('path')!=row['plist'] or field('working directory')!=definition['WorkingDirectory']
                or field('program')!=definition['ProgramArguments'][0]
                or not match or [x.strip() for x in match[1].splitlines() if x.strip()]!=definition['ProgramArguments']):
            raise C.Stop('UNKNOWN_LOADED_DEFINITION_NO_RECONCILIATION')
        envmatch=re.search(r'^\tenvironment = \{\n(.*?)^\t\}',text,re.M|re.S)
        env=dict(re.findall(r'^\s*([^\s]+) => (.*)$',envmatch[1],re.M)) if envmatch else {}
        if any(env.get(k)!=str(v) for k,v in definition['EnvironmentVariables'].items()):
            raise C.Stop('UNKNOWN_LOADED_ENVIRONMENT_NO_RECONCILIATION')
    return side,digest,service


def reconcile_role(p,h,role,ops,root,run,deadline):
    statepath=run/('reconcile-'+role+'.json')
    if statepath.exists():raise C.Stop('EXISTING_RECONCILIATION_INTENT_NO_REPLAY')
    intent=root/(role+'.intent')
    if not intent.exists():return {'status':'NO_OWN_ARM_INTENT_NO_ACTION'}
    if root_text(intent)!='INTENT':raise C.Stop('ARM_INTENT_INVALID')
    status=root_text(root/(role+'.restore.status'))
    if status not in {'RESTORED_NORMAL_ARGV','UNLOADED_NO_PENDING_INSTANCE'}:
        raise C.Stop('ROOT_RESTORE_UNCONFIRMED:'+role+':'+status)
    if status=='RESTORED_NORMAL_ARGV' and root_text(root/(role+'.restore.rc'))!='0':raise C.Stop('RESTORE_RC_NOT_SUCCESS')
    side,digest,service=current_definition(p,role,ops)
    if status=='RESTORED_NORMAL_ARGV' and root_text(root/(role+'.restore.definition_sha256'))!=digest:
        raise C.Stop('RESTORED_DEFINITION_CHANGED_NO_ACTION')
    initial=h['identities'][role]
    current=ops.identity(service['pid']) if service.get('pid') else None
    guard=bool(current and re.search(r'(?:^|\s)/bin/sleep 604800\s*$',current['ps_text'])
               and current!=initial)
    checkpoint=run/('owned-'+role+'.checkpoint.json')
    children=json.loads(C.read(checkpoint)).get('children',{}) if checkpoint.exists() else {}
    alive=lambda: any(ops.identity(int(pid))==identity for pid,identity in children.items())
    known_current=bool(current and (root/(role+'.restore.ps_sha256')).exists() and root_text(root/(role+'.restore.ps_sha256'))==current['ps_sha256'] and not guard)
    decision=recovery_decision(initial,current,guard,True,True,alive(),known_current)
    if decision.startswith('STOP_'):raise C.Stop(decision+':'+role)
    if decision=='WAIT_HEALTHY_CHILDREN_NO_SIGNAL':
        while alive() and time.monotonic()<deadline:time.sleep(.2)
        if alive():raise C.Stop('HEALTHY_CHILDREN_STILL_RUNNING_NO_SIGNAL:'+role)
        side,now_digest,service=current_definition(p,role,ops)
        if now_digest!=digest or ops.identity(service.get('pid'))!=current:
            raise C.Stop('GUARD_CHANGED_WHILE_CHILDREN_DRAINED')
        decision='REAP_OWN_SLEEP_GUARD_ONLY'
    if decision=='REAP_OWN_SLEEP_GUARD_ONLY':
        if initial and ops.identity(initial['pid'])==initial:
            raise C.Stop('ORIGINAL_HEALTHY_OWNER_STILL_ALIVE_NO_SIGNAL')
        C.save(statepath,{'phase':'GUARD_BOOTOUT_INTENT','guard':current,'definition_sha256':digest,
                          'current_side':side,'not_a_batch_rollback':True})
        ops.bootout_guard(role,current,initial)  # uid501; exact harmless guard only.
        C.save(statepath,{'phase':'GUARD_UNLOADED','guard':current,'definition_sha256':digest})
        while ops.identity(current['pid'])==current and time.monotonic()<deadline:time.sleep(.1)
        if ops.identity(current['pid'])==current:raise C.Stop('GUARD_EXIT_NOT_CONFIRMED_NO_BOOTSTRAP')
        ops.absent(role)
        C.pin(C.row(p,role)['plist'],digest)
        C.save(statepath,{'phase':'BOOTSTRAP_CURRENT_INTENT','definition_sha256':digest})
        ops.cmd(['/bin/launchctl','bootstrap','gui/501',C.row(p,role)['plist']])
        C.save(statepath,{'phase':'CURRENT_DEFINITION_AVAILABLE','definition_sha256':digest,
                          'current_side':side,'not_a_batch_rollback':True})
        return {'status':'OWN_GUARD_CONSUMED_CURRENT_DEFINITION_BOOTSTRAPPED','current_side':side}
    if not service['loaded']:
        prior=json.loads(C.read(checkpoint)) if checkpoint.exists() else {}
        post_guard_phases={'GUARD_BOOTOUT_INTENT','WAIT_GUARD_GONE','CAS_INTENT','PLIST_APPLIED','OLD_DISABLE_INTENT','OLD_DISABLED','DEST_ENABLE_INTENT','DEST_ENABLED','BOOTSTRAP_INTENT','READBACK','HEALTH','DONE'}
        if prior.get('phase') not in post_guard_phases or not isinstance(prior.get('guard'),dict):
            raise C.Stop('OWN_GUARD_UNLOAD_NOT_RECORDED_NO_BOOTSTRAP')
        if initial and ops.identity(initial['pid'])==initial or alive():
            raise C.Stop('HEALTHY_ORIGINAL_OR_CHILD_STILL_ALIVE_NO_BOOTSTRAP')
        # An own prior guard bootout may have completed before coordinator death.
        # Current exact plist is kept; no automatic inverse of a published release.
        C.save(statepath,{'phase':'BOOTSTRAP_CURRENT_INTENT','definition_sha256':digest})
        ops.cmd(['/bin/launchctl','bootstrap','gui/501',C.row(p,role)['plist']])
        C.save(statepath,{'phase':'CURRENT_DEFINITION_AVAILABLE','definition_sha256':digest,
                          'not_a_batch_rollback':True})
        return {'status':'CURRENT_EXACT_UNLOADED_DEFINITION_BOOTSTRAPPED','current_side':side}
    return {'status':decision,'current_side':side,'process_untouched':True}


def proof_locks(p,h,ops):
    """Acquire all operation locks in this process; nothing is inherited."""
    stack=contextlib.ExitStack()
    try:
        g=p['owner_guard'];fd=os.open(g['path'],os.O_RDWR|os.O_NOFOLLOW)
        stack.callback(os.close,fd);s=os.fstat(fd)
        if (s.st_dev,s.st_ino)!=(g['device'],g['inode']):raise C.Stop('ORIGINAL_GUARD_IDENTITY')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        ops.protection(h)
        integration=C.load_api_integration(p)
        stack.enter_context(integration.announcement_flash_cutover_guard(Path(p['announcement_workbench_root']),timeout_seconds=10))
        lease=stack.enter_context(integration.shared_api_release_lock(Path(C.row(p,'api')['plist']),timeout_seconds=2,role='gateway'))
        integration.assert_api_release_lock(lease,Path(C.row(p,'api')['plist']),role='gateway')
        return stack
    except BaseException:stack.close();raise


def inspect(p,h):
    ops=C.Live(p,h['reverse']);root=Path(h['root_ack_dir'])
    return {'operation_id':h['operation_id'],'root_ack_dir':str(root),'labels':{
        role:{'loaded':ops.service(role),'arm_intent':(root/(role+'.intent')).exists(),
              'restore_status':root_text(root/(role+'.restore.status')) if (root/(role+'.restore.status')).exists() else 'MISSING'}
        for role in C.ROLES}}


def run(a):
    if os.getuid()!=501:raise C.Stop('UID501_ONLY')
    p=json.loads(C.read(a.plan));C.scope(p);C.verify_review(a.review,a.review_sha256,p)
    h=json.loads(C.pin(a.handoff,a.handoff_sha256));op=h['operation_id'];ops=C.Live(p,h['reverse'])
    if a.action=='inspect':print(json.dumps(inspect(p,h)));return
    if a.action=='reconcile':
        fresh=json.loads(C.pin(a.reconciliation_handoff,a.reconciliation_handoff_sha256))
        if (fresh.get('operation_id')!=op or fresh.get('plan_sha256')!=C.sha(C.canonical(p)) or not fresh['observed_epoch']<=time.time()<=fresh['expires_epoch'] or not 0<fresh['expires_epoch']-fresh['observed_epoch']<=300 or fresh.get('no_parallel_lifecycle_owner') is not True):raise C.Stop('FRESH_RECONCILIATION_HANDOFF_REQUIRED')
        result={'operation_id':op,'status':'EXPLICIT_ABORT_RECONCILIATION_NOT_BATCH_ROLLBACK','roles':{}}
        with proof_locks(p,fresh,ops):
            root=Path(h['root_ack_dir']);validate_root_plan(p,root);root_text(root/'RESTORE_COMPLETE')
            run=HERE/('owned-run-'+op);run.mkdir(exist_ok=True)
            for role in C.ROLES:
                side,digest,service=current_definition(p,role,ops)
                current=ops.identity(service['pid']) if service.get('pid') else None
                observed=fresh['role_observations'][role]
                if observed!={'definition_sha256':digest,'current_identity':current}:raise C.Stop('RECONCILIATION_CURRENT_OWNER_DRIFT')
                result['roles'][role]=reconcile_role(p,h,role,ops,root,run,time.monotonic()+p['recovery']['guardian_reconcile_seconds'])
            C.save(HERE/('owned-reconciliation-'+op+'.json'),result)
        print(json.dumps(result));return
    parent={'pid':a.parent_pid,'ps_sha256':a.parent_ps_sha256}
    initial_parent=ops.identity(parent['pid'])
    if initial_parent is None or initial_parent['ps_sha256']!=parent['ps_sha256']:
        raise C.Stop('PARENT_IDENTITY_REQUIRED_BEFORE_GUARDIAN_LEASE')
    C.handoff(p,h,h['reverse'])
    result={'operation_id':op,'status':'LEASE_START','not_a_batch_rollback':True}
    with proof_locks(p,h,ops):
        try:
            if a.action=='watch':
                for role in C.ROLES:ops.original(role,h['identities'][role])
                ready=R.ready_path(HERE,op)
                if ready.exists():raise C.Stop('EXISTING_READY_NO_REPLAY')
                C.save(ready,{'operation_id':op,'plan_sha256':C.sha(C.canonical(p)),
                    'guardian':ops.identity(os.getpid()),'parent':initial_parent,
                    'leases':'ORIGINAL_OWNER_AND_SHARED_API_AND_ANNOUNCEMENT_HELD_BY_THIS_PROCESS'})
                finish=HERE/('owned-finish-'+op+'.json')
                while True:
                    if finish.exists():
                        value=json.loads(C.read(finish))
                        checkpoints=HERE/('owned-run-'+op)
                        if value.get('operation_id')!=op or any(json.loads(C.read(checkpoints/('owned-'+r+'.checkpoint.json'))).get('phase')!='DONE' for r in C.ROLES):
                            raise C.Stop('NORMAL_FINISH_NOT_ALL_DONE')
                        ops.main_unchanged()
                        for role in C.ROLES:
                            state=json.loads(C.read(checkpoints/('owned-'+role+'.checkpoint.json')))
                            ops.completed(role,state['new'])
                        C.save(HERE/('owned-guardian-'+op+'.discharge.json'),{'operation_id':op,'plan_sha256':C.sha(C.canonical(p)),'all_roles_done_and_loaded_verified':True})
                        result['status']='NORMAL_DONE_WAIT_HELPER_DISCHARGE';break
                    now=ops.identity(parent['pid'])
                    reason=abort_trigger(p,h,Path(h['root_ack_dir']),now,initial_parent,time.time())
                    if reason:
                        R.request_abort(C,h,HERE,reason);result['status']='ABORT_RESTORE_WAIT';break
                    time.sleep(.2)
        except BaseException as failure:
            R.request_abort(C,h,HERE,'GUARDIAN_WATCH_FAILURE:'+str(failure));result.update(status='ABORT_RESTORE_WAIT',watch_failure=str(failure))
        root=Path(h['root_ack_dir']);deadline=time.monotonic()+p['recovery']['cleanup_grace_seconds']+10
        while not (root/'RESTORE_COMPLETE').exists() and not (root/'HELPER_DONE').exists():
            # Before any privileged arm, abort is already safe and requires no helper.
            if not root.exists() or not any((root/(r+'.intent')).exists() for r in C.ROLES):
                result['status']='ABORTED_BEFORE_ANY_ARM';break
            if time.monotonic()>deadline:raise C.Stop('ROOT_RESTORE_ACK_UNKNOWN_RECONCILE_REQUIRED')
            time.sleep(.2)
        if root.exists():validate_root_plan(p,root)
        if (root/'HELPER_DONE').exists():
            if root_text(root/'HELPER_DONE')!='DISCHARGED':raise C.Stop('HELPER_DISCHARGE_INVALID')
            result['status']='NORMAL_DONE_ALL_GUARDS_DISCHARGED'
        elif (root/'RESTORE_COMPLETE').exists():
            root_text(root/'RESTORE_COMPLETE');run=HERE/('owned-run-'+op);run.mkdir(exist_ok=True)
            deadline=time.monotonic()+p['recovery']['guardian_reconcile_seconds']
            outcomes={}
            for role in C.ROLES:
                try:outcomes[role]=reconcile_role(p,h,role,ops,root,run,deadline)
                except C.Stop as error:outcomes[role]={'status':'STOP_NO_RETRY','reason':str(error)}
            result.update(status='ABORT_BINDINGS_RECONCILED_NOT_BATCH_ROLLBACK' if all(x.get('status')!='STOP_NO_RETRY' for x in outcomes.values()) else 'ABORT_UNRESOLVED_EXACT_RECONCILIATION_REQUIRED',roles=outcomes)
        C.save(R.outcome_path(HERE,op),result)
    print(json.dumps(result))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['watch','inspect','reconcile']);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--review',type=Path,required=True);ap.add_argument('--review-sha256',required=True);ap.add_argument('--handoff',type=Path,required=True);ap.add_argument('--handoff-sha256',required=True);ap.add_argument('--reconciliation-handoff',type=Path);ap.add_argument('--reconciliation-handoff-sha256');ap.add_argument('--parent-pid',type=int);ap.add_argument('--parent-ps-sha256');a=ap.parse_args()
    try:run(a)
    except BaseException as error:
        try:
            h=json.loads(C.read(a.handoff));op=h['operation_id']
            C.save(R.outcome_path(HERE,op),{'operation_id':op,'status':'STOP_UNKNOWN_NO_ACTION_REPLAY','error':str(error),
                'read_only_inspection_command':[os.sys.executable,'-B',str(Path(__file__).resolve()),'inspect','--plan',str(a.plan),'--review',str(a.review),'--review-sha256',a.review_sha256,'--handoff',str(a.handoff),'--handoff-sha256',a.handoff_sha256],
                'reconciliation_artifact':str(HERE/('owned-run-'+op)),'not_a_batch_rollback':True})
        except Exception:pass
        raise
if __name__=='__main__':main()
