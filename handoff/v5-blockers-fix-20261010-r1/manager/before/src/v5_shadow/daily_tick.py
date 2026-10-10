"""One existing-dispatcher tick over a prepared exact-date private request bundle."""
import sys
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
from datetime import datetime,timezone,timedelta
import json
import plistlib
from v5_shadow.daily_dispatch import dispatch_due
from v5_shadow.daily_owner_adapters import adapter_identity,read_announcement_owner,run_manager_daily
from v5_shadow.daily_rebound_owner import run_rebound_owner,PIN as REBOUND_PIN
from v5_shadow.daily_us_owner import bind_us_owner
from v5_shadow.digests import sha256_json,canonical_bytes
from v5_shadow.module_api import _open_directory,_read_at
from v5_shadow.contracts import aware
import os

LABEL='com.lexi.v5.daily.candidate'


def default_slots(target):
    date=target[:4]+'-'+target[4:6]+'-'+target[6:]
    return dict(scheduled_at=date+'T08:00:00+08:00',deadline=date+'T08:45:00+08:00',
        research_cutoff=date+'T08:00:00+08:00',half_day_bound=True,max_attempts=1,
        plan_at=date+'T08:45:00+08:00',plan_deadline=date+'T09:00:00+08:00',
        schedule_basis='NEW_V5_DEFAULT_NOT_VERIFIED_V4_SCHEDULE')


def tick(config):
    if config.get('enabled') is not True:return dict(status='DISABLED',natural_verified=False)
    today=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d')
    fd=_open_directory(config['bundle_root'])
    try:
        if _read_at(fd,None,'.v5-daily-bundles')!=b'v5.daily-bundles.v1\n':raise ValueError('DAILY_BUNDLE_MARKER')
        try:bundle=json.loads(_read_at(fd,None,today+'.json'))
        except FileNotFoundError:return dict(status='BLOCKED_CURRENT_BUNDLE_MISSING',natural_verified=False)
    finally:os.close(fd)
    if bundle['target_date']!=today:raise ValueError('DAILY_BUNDLE_TARGET')
    from v5_shadow.announcement_offline_reader import PIN as ANNOUNCEMENT_PIN,REVISION_PIN
    from v5_shadow.manager_plan import PIN as MANAGER_PIN, _identity as manager_identity
    registration=adapter_identity(config,dict(announcement=ANNOUNCEMENT_PIN,revision=REVISION_PIN,rebound=REBOUND_PIN,
        manager=MANAGER_PIN,manager_implementation=manager_identity()))
    bindings=dict(us_mapping=bind_us_owner(config),
        announcement=dict(registration,invoke=read_announcement_owner),
        rebound=dict(registration,invoke=run_rebound_owner))
    jobs=[];rejected=[]
    defaults=default_slots(today)
    for job in bundle['jobs']:
        try:
            job=dict({key:defaults[key] for key in ('scheduled_at','deadline','research_cutoff','half_day_bound','max_attempts')},**job)
            lane=job['lane'];request=job['owner_request']
            if lane=='announcement':
                if 'revision_create' in request:
                    if request['target_date']!=today:raise ValueError('ANNOUNCEMENT_REVISION_TARGET')
                    create=request['revision_create']
                    if not create or not request.get('review_identities') or any(not Path(create.get(key,'')).is_file() for key in ('semantic_catalog','reviewer_output','decisions')):
                        rejected.append(dict(lane=lane,status='BLOCKED_WAITING_REAL_ANALYSIS_REVIEW_DECISIONS'));continue
                elif request['binding']['target_date']!=today or request['cutoff']!=job['research_cutoff']:
                    raise ValueError('ANNOUNCEMENT_DATE_CUTOFF')
            elif lane=='rebound':
                if request['request']['target_date']!=today:raise ValueError('REBOUND_TARGET_DATE')
            if lane not in bindings:raise ValueError('DAILY_UNKNOWN_OWNER')
            identity={k:bindings[lane][k] for k in ('code_sha256','config_sha256','dependency_sha256')}
            jobs.append(dict(job,identity=dict(identity,lane=lane,target_date=today,
                research_cutoff=job['research_cutoff'],input_sha256=sha256_json(request))))
        except Exception as error:
            rejected.append(dict(lane=job.get('lane') if isinstance(job,dict) else None,
                                 status='BLOCKED_OWNER_CONTRACT',reason=type(error).__name__))
    result=dispatch_due(jobs,bindings,config['ledger_root'])
    # At 08:45 the execution window closes, but already saved owner products
    # remain readable for the plan. Never re-execute to recover their references.
    from v5_shadow.run_ledger import read_run
    for job,row in zip(jobs,result['lanes']):
        if 'state' not in row:
            state=read_run(config['ledger_root'],job['identity'])
            if state is not None:row['state']=state
    result['lanes'].extend(rejected)
    manager=bundle.get('manager_request')
    template=bundle.get('manager_template')
    if manager is None and template is None:result['manager']=dict(status='BLOCKED_POST_OWNER_REQUEST_MISSING')
    else:
        try:
            now=datetime.now(timezone.utc)
            if template is not None:
                if now<aware(defaults['plan_at']):
                    result['manager']=dict(status='WAITING_0845_PLAN_WINDOW');return result
                if now>=aware(defaults['plan_deadline']):
                    result['manager']=dict(status='MISSED_PLAN_WINDOW_NO_BACKFILL');return result
                from v5_shadow.daily_manager_assembly import assemble_manager_request
                manager=assemble_manager_request(template,result['lanes'],config['ledger_root'],registration)
            saved=run_manager_daily(manager,config['ledger_root'],registration)
            result['manager']=dict(status=saved.get('status','PLAN_SAVED_BUSINESS_BLOCKED'))
        except Exception as error:result['manager']=dict(status='BLOCKED_OR_OUTCOME_UNKNOWN',reason=type(error).__name__)
    return result


def launchd_contract(config_path, *, python, interval=300):
    """Render only. Installation/enablement belong to the existing Mac task."""
    config_path=Path(config_path);python=Path(python)
    if not config_path.is_absolute() or not python.is_absolute() or type(interval) is not int or interval<60:
        raise ValueError('DAILY_LAUNCHD_CONTRACT')
    return dict(Label=LABEL,ProgramArguments=[str(python),'-I','-B',str(Path(__file__).resolve()),
        '--config',str(config_path)],StartInterval=interval,RunAtLoad=False,Disabled=True,
        ProcessType='Background')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--render-launchd',action='store_true')
    parser.add_argument('--python',default=sys.executable)
    args=parser.parse_args()
    if args.render_launchd:sys.stdout.buffer.write(plistlib.dumps(launchd_contract(args.config,python=args.python)))
    else:
        result=tick(json.loads(args.config.read_bytes()))
        # Operational logs contain statuses only, not raw private artifacts.
        print(canonical_bytes(dict(status=result['status'],natural_verified=False,
            lanes=[dict(lane=row['lane'],status=row['status']) for row in result.get('lanes',[])],
            manager=result.get('manager'))).decode())
