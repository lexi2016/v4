"""One bounded invocation of the original announcement owner; no service loop."""
from __future__ import annotations
import argparse
import hashlib
from datetime import datetime, time, timedelta
import json
import os
from pathlib import Path
import re
import signal
import sys
from typing import Any, Mapping
from zoneinfo import ZoneInfo

APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:sys.path.insert(0,str(APP_ROOT))


class AnnouncementCancelled(BaseException):
    pass


PLAN_REFRESH_DEFAULTS={
    'enabled':False,
    'start_local':'16:00',
    'end_local':'23:00',
    'max_attempts_per_target_date':3,
    'retry_backoff_seconds':600,
    'status':'PROPOSAL_ONLY',
}


def _plan_refresh_config(value: Mapping[str,Any] | None) -> dict[str,Any]:
    config=dict(PLAN_REFRESH_DEFAULTS)
    if isinstance(value,Mapping):
        allowed=set(PLAN_REFRESH_DEFAULTS)
        if set(value)-allowed:raise ValueError('PLAN_MATERIAL_REFRESH_FIELDS_INVALID')
        for key in allowed:
            if key in value:config[key]=value[key]
    elif value is not None:
        raise ValueError('PLAN_MATERIAL_REFRESH_CONFIG_INVALID')
    if type(config['enabled']) is not bool:
        raise ValueError('PLAN_MATERIAL_REFRESH_ENABLED_INVALID')
    if config['status']!='PROPOSAL_ONLY':
        raise ValueError('PLAN_MATERIAL_REFRESH_STATUS_INVALID')
    if not re.fullmatch(r'\d{2}:\d{2}',str(config['start_local'])) or not re.fullmatch(r'\d{2}:\d{2}',str(config['end_local'])):
        raise ValueError('PLAN_MATERIAL_REFRESH_WINDOW_INVALID')
    try:
        start=time.fromisoformat(str(config['start_local']))
        end=time.fromisoformat(str(config['end_local']))
    except ValueError as exc:
        raise ValueError('PLAN_MATERIAL_REFRESH_WINDOW_INVALID') from exc
    if start.second or start.microsecond or end.second or end.microsecond or not time(15,40)<=start<end<=time(23):
        raise ValueError('PLAN_MATERIAL_REFRESH_WINDOW_INVALID')
    attempts=config['max_attempts_per_target_date']
    backoff=config['retry_backoff_seconds']
    if isinstance(attempts,bool) or not isinstance(attempts,int) or not 1<=attempts<=5:
        raise ValueError('PLAN_MATERIAL_REFRESH_ATTEMPT_LIMIT_INVALID')
    if isinstance(backoff,bool) or not isinstance(backoff,int) or not 300<=backoff<=3600:
        raise ValueError('PLAN_MATERIAL_REFRESH_BACKOFF_INVALID')
    config['start_local']=start
    config['end_local']=end
    return config


def next_hk_session_date(source_date: str) -> str:
    """Map a real current session to the next HK securities session in the frozen calendar."""
    from contracts.trading_calendar import load_market_calendar,resolve_market_states,TradingDayState,parse_trade_date
    calendar=load_market_calendar()
    parsed=parse_trade_date(source_date,year=calendar.year)
    if parsed is None:raise ValueError('PLAN_MATERIAL_REFRESH_SOURCE_DATE_OUTSIDE_CALENDAR')
    state=resolve_market_states(calendar,source_date)['hk_securities']
    if state not in {TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}:
        raise ValueError('PLAN_MATERIAL_REFRESH_SOURCE_DATE_NOT_TRADING_DAY')
    for offset in range(1,32):
        candidate=parsed+timedelta(days=offset)
        if candidate.year!=calendar.year:break
        date=candidate.strftime('%Y%m%d')
        state=resolve_market_states(calendar,date)['hk_securities']
        if state in {TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}:
            return date
    raise ValueError('PLAN_MATERIAL_REFRESH_NEXT_SESSION_OUTSIDE_CALENDAR')


def _attempts_today(service:Any,target_date:str,local_now:datetime) -> list[dict[str,Any]]:
    from v4.manager_research.workspace import validate_attempt
    root=Path(service.store.root)/'workspace_plan_runs'/target_date
    if not root.is_dir():return []
    rows=[]
    for path in sorted(root.glob('*.json')):
        if path.name=='latest.json':continue
        row=service.store._read(path)
        if row is None:continue
        try:row=validate_attempt(row,target_date)
        except (TypeError,ValueError,KeyError) as exc:
            raise ValueError('PLAN_MATERIAL_REFRESH_ATTEMPT_INVALID') from exc
        started=row.get('started_at')
        try:started_at=datetime.fromisoformat(str(started))
        except ValueError:continue
        if (row.get('execution_kind')=='MANUAL_REFRESH' and started_at.tzinfo is not None
                and started_at.astimezone(local_now.tzinfo).date()==local_now.date()):
            rows.append(row)
    return rows


def run_next_hk_session_plan_material_refresh(service:Any,source_date:str,*,now:datetime,
                                               config:Mapping[str,Any] | None=None) -> dict[str,Any]:
    """Persist a next-session MANUAL_REFRESH through the existing workspace-plan owner."""
    cfg=_plan_refresh_config(config)
    if now.tzinfo is None:raise ValueError('PLAN_MATERIAL_REFRESH_CLOCK_MUST_BE_AWARE')
    local=now.astimezone(ZoneInfo('Asia/Hong_Kong'))
    if not cfg['enabled']:return {'status':'DISABLED','policy_status':'PROPOSAL_ONLY'}
    if local.strftime('%Y%m%d')!=source_date:
        raise ValueError('PLAN_MATERIAL_REFRESH_SOURCE_DATE_CLOCK_MISMATCH')
    if local.timetz().replace(tzinfo=None)<cfg['start_local']:
        return {'status':'NOT_DUE','policy_status':'PROPOSAL_ONLY'}
    if local.timetz().replace(tzinfo=None)>=cfg['end_local']:
        return {'status':'EXPIRED_NO_BACKFILL','policy_status':'PROPOSAL_ONLY'}
    target=next_hk_session_date(source_date)
    from v4.manager_research import workspace
    saved=workspace._read_plan(service.store,target)
    if saved and saved.get('execution_kind')=='SCHEDULED_PREOPEN':
        return {'status':'PRESERVED_SCHEDULED_PREOPEN','target_trade_date':target,
            'run_id':saved.get('run_id'),'product_sha256':saved.get('sha256'),
            'policy_status':'PROPOSAL_ONLY'}
    current=workspace.get_workspace(service,target,include_saved=False,now=local)
    current_identity=current.get('input_identity')
    if not re.fullmatch(r'[0-9a-f]{64}',str(current_identity or '')):
        raise ValueError('PLAN_MATERIAL_REFRESH_INPUT_IDENTITY_INVALID')
    if (saved and saved.get('input_identity')==current_identity
            and saved.get('workspace',{}).get('semantic_version')==current.get('semantic_version')):
        return {'status':'ALREADY_CURRENT','target_trade_date':target,'run_id':saved.get('run_id'),
            'product_sha256':saved.get('sha256'),'input_identity':current_identity,
            'execution_kind':saved.get('execution_kind','MANUAL_REFRESH'),'policy_status':'PROPOSAL_ONLY'}
    attempts=_attempts_today(service,target,local)
    matching=[row for row in attempts if row.get('input_identity')==current_identity]
    unknown_failures=[row for row in attempts if row.get('state')=='FAILED' and not row.get('input_identity')]
    relevant=matching+unknown_failures
    if relevant:
        last=max(relevant,key=lambda row:row.get('started_at',''))
        if last.get('state')=='FAILED':
            finished=datetime.fromisoformat(str(last.get('finished_at') or last['started_at']))
            if (local-finished.astimezone(local.tzinfo)).total_seconds()<cfg['retry_backoff_seconds']:
                return {'status':'RETRY_BACKOFF','target_trade_date':target,'attempts':len(relevant),
                    'retry_after_seconds':cfg['retry_backoff_seconds'],'policy_status':'PROPOSAL_ONLY'}
    if len(relevant)>=cfg['max_attempts_per_target_date']:
        return {'status':'RETRY_LIMIT_REACHED','target_trade_date':target,'attempts':len(relevant),
            'policy_status':'PROPOSAL_ONLY'}
    result=service.refresh_workspace_plan(target,execution_kind='MANUAL_REFRESH',now=local)
    saved=workspace._read_plan(service.store,target)
    if not saved or saved.get('execution_kind')!='MANUAL_REFRESH':
        raise ValueError('PLAN_MATERIAL_REFRESH_READBACK_INVALID')
    attempt=result.get('workspace_plan_attempt',{}) if isinstance(result,Mapping) else {}
    return {'status':'PARTIAL' if attempt.get('state')=='PARTIAL' else 'MATERIALIZED',
        'target_trade_date':target,'run_id':saved.get('run_id'),
        'product_sha256':saved.get('sha256'),'input_identity':saved.get('input_identity'),
        'execution_kind':'MANUAL_REFRESH','owner':saved.get('owner'),
        'owner_attempt_state':attempt.get('state'),'failure_reasons':attempt.get('failure_reasons',[]),
        'success_scope':'EXACT_DATE_RESEARCH_PLAN_NOT_FORMAL_RECOMMENDATION_OR_NATURAL_CAPTURE',
        'policy_status':'PROPOSAL_ONLY'}


def run_plan_material_refresh_only_cycle(service:Any,source_date:str,*,now:datetime,
                                         plan_config:Mapping[str,Any],preopen_config:Mapping[str,Any] | None=None) -> dict[str,Any]:
    """Run the pre-open owner when due and evening draft owner; never call announcement collection."""
    from v4.manager_research.workspace_plan_autorun import run_scheduled_preopen_plan_safe
    preopen=run_scheduled_preopen_plan_safe(service,source_date,now=now,config=preopen_config)
    draft=run_next_hk_session_plan_material_refresh(service,source_date,now=now,config=plan_config)
    failed=preopen.get('status')=='FAILED' or draft.get('status')=='FAILED'
    partial=draft.get('status')=='PARTIAL'
    return {'status':'FAILED' if failed else 'PARTIAL' if partial else 'SUCCEEDED','preopen_plan':preopen,
        'next_session_draft':draft,'announcement_collection':{'status':'DISABLED_PLAN_REFRESH_ONLY',
            'announcement_network_requests':0},'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding',required=True)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args(argv)
    from infrastructure.scheduling.manager_announcement_supervisor import load_binding
    value=load_binding(args.binding,APP_ROOT)
    if sys.version_info < (3,14):raise RuntimeError('PYTHON_314_REQUIRED')
    if Path.cwd().resolve()!=APP_ROOT:raise ValueError('ANNOUNCEMENT_WORKER_CWD_MISMATCH')
    plan_only=value.get('plan_material_refresh_only',False)
    announcement_enabled=value.get('announcement_collection_enabled',True)
    if type(plan_only) is not bool or type(announcement_enabled) is not bool:
        raise ValueError('ANNOUNCEMENT_COLLECTION_CONFIG_INVALID')
    plan_config=_plan_refresh_config(value.get('plan_material_refresh'))
    if plan_only and (not plan_config['enabled'] or announcement_enabled):
        raise ValueError('PLAN_MATERIAL_REFRESH_ONLY_CONFIG_INVALID')
    if any(os.environ.get(k,'false').lower() not in {'false','0','off',''} for k in
           ('PRODUCTION_ALLOWED','BUY_GATE_UPDATED','ORDERS_SENT')):
        raise ValueError('ANNOUNCEMENT_WORKER_UNSAFE_ENVIRONMENT')
    from v4.manager_research.announcement_autorun import policy_due
    from v4.manager_research.workspace_projection import HK
    now=datetime.now(HK)
    status='DISABLED' if not value['enabled'] else 'ELIGIBLE' if policy_due(now,value['policy']) else 'OUTSIDE_WINDOW'
    if args.dry_run or status!='ELIGIBLE':
        print(json.dumps(dict(status=status,dry_run=args.dry_run,network_requests=0,
            state_writes=0,plan_material_refresh_only=plan_only,
            announcement_collection='DISABLED_PLAN_REFRESH_ONLY' if plan_only else ('ENABLED' if announcement_enabled else 'DISABLED'),
            policy_status='PROPOSAL_ONLY',production_allowed=False,buy_gate_updated=False,orders_sent=False)))
        return 0
    def cancel(signum,frame):raise AnnouncementCancelled('ANNOUNCEMENT_WORKER_DEADLINE_OR_CANCEL')
    old={s:signal.signal(s,cancel) for s in (signal.SIGALRM,signal.SIGTERM,signal.SIGINT)}
    signal.setitimer(signal.ITIMER_REAL,48)
    service=None
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU,(45,46))
            os.nice(10)
        except (ValueError,OSError):
            # Do not silently execute when configured resource isolation fails.
            raise RuntimeError('ANNOUNCEMENT_RESOURCE_BOUND_UNAVAILABLE')
        from v4.manager_research.materials import MaterialStore
        from v4.manager_research.store import ManagerResearchStore
        from v4.manager_research.hkex_provider import HkexOfficialProvider
        from v4.manager_research.service import ManagerResearchJobService
        root=Path(value['manager_state_root'])
        materials=MaterialStore(root/'materials')
        provider=HkexOfficialProvider(material_store=materials,timeout=5)
        service=ManagerResearchJobService(ManagerResearchStore(root),None,provider,
            material_store=materials,workspace_security_master_root=Path(value['security_master_root']))
        now=datetime.now(HK)
        from v4.manager_research.workspace_plan_autorun import run_scheduled_preopen_plan_safe
        if plan_only:
            try:
                result=run_plan_material_refresh_only_cycle(service,now.strftime('%Y%m%d'),now=now,
                    plan_config=value.get('plan_material_refresh'),preopen_config=value.get('preopen_plan'))
            except Exception as exc:
                reason=str(exc)
                if not re.fullmatch(r'[A-Z0-9_:. -]{1,160}',reason):reason=type(exc).__name__
                result={'status':'FAILED','reason':reason,
                    'announcement_collection':{'status':'DISABLED_PLAN_REFRESH_ONLY','announcement_network_requests':0},
                    'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
            print(json.dumps(dict(**result,policy_status='PROPOSAL_ONLY',
                production_allowed=False,buy_gate_updated=False,orders_sent=False)))
            return 2 if result.get('status')=='FAILED' else 0
        plan_result=run_scheduled_preopen_plan_safe(service,now.strftime('%Y%m%d'),now=now,
            config=value.get('preopen_plan'))
        if not announcement_enabled:
            print(json.dumps(dict(status='ANNOUNCEMENT_COLLECTION_DISABLED',preopen_plan=plan_result,
                production_allowed=False,buy_gate_updated=False,orders_sent=False)))
            return 0
        result=service.refresh_announcements(now.strftime('%Y%m%d'),schedule=dict(
            policy=value['policy'],priority_codes=value['priority_codes'],now=now.isoformat(),
            execution_identity=dict(status='BOUND_WORKER',app_root_sha256=hashlib.sha256(str(APP_ROOT).encode()).hexdigest(),
                source_inventory_sha256=hashlib.sha256(json.dumps(value['files'],sort_keys=True).encode()).hexdigest(),
                python_sha256=value['python_sha256'])))
        print(json.dumps(dict(status=result['status'],attempt=(result.get('attempt') or {}).get('run_id'),
            preopen_plan=plan_result, production_allowed=False,buy_gate_updated=False,orders_sent=False)))
        return 0
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        for signum,handler in old.items():signal.signal(signum,handler)
        if service is not None:service.close()


if __name__=='__main__':
    try:raise SystemExit(main())
    except (Exception,AnnouncementCancelled) as exc:
        print(json.dumps({'status':'FAILED','reason':type(exc).__name__,'production_allowed':False,
                          'buy_gate_updated':False,'orders_sent':False}))
        raise SystemExit(2)
