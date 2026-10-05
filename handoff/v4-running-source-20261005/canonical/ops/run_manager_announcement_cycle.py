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

VIBE_REFRESH_DEFAULTS={"enabled":False,"time_local":"06:55","status":"PROPOSAL_ONLY"}


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


def _vibe_refresh_config(value: Mapping[str,Any] | None) -> dict[str,Any]:
    config=dict(VIBE_REFRESH_DEFAULTS)
    if value is not None:
        if not isinstance(value,Mapping) or set(value)-set(config):
            raise ValueError("VIBE_REFRESH_CONFIG_INVALID")
        config.update(value)
    if (type(config["enabled"]) is not bool or config["time_local"]!="06:55"
            or config["status"]!="PROPOSAL_ONLY"):
        raise ValueError("VIBE_REFRESH_CONFIG_INVALID")
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
                                         plan_config:Mapping[str,Any] | None,preopen_config:Mapping[str,Any] | None=None,
                                         morning_config:Mapping[str,Any] | None=None) -> dict[str,Any]:
    """Run bounded morning, pre-open and evening owners; never collect announcements."""
    from v4.manager_research.workspace_plan_autorun import run_scheduled_preopen_plan_safe
    from v4.manager_research.workspace_plan_autorun import run_scheduled_morning_plan
    morning=run_scheduled_morning_plan(service,source_date,now=now,config=morning_config)
    preopen=run_scheduled_preopen_plan_safe(service,source_date,now=now,config=preopen_config)
    draft=run_next_hk_session_plan_material_refresh(service,source_date,now=now,config=plan_config)
    failed=any(item.get('status')=='FAILED' for item in (morning,preopen,draft))
    partial=any(item.get('status')=='PARTIAL' for item in (morning,preopen,draft))
    return {'status':'FAILED' if failed else 'PARTIAL' if partial else 'SUCCEEDED','preopen_plan':preopen,
        'morning_plan':morning,
        'next_session_draft':draft,'announcement_collection':{'status':'DISABLED_PLAN_REFRESH_ONLY',
            'announcement_network_requests':0},'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}


def scheduled_cycle_target(source_date:str,*,now:datetime,plan_config:Mapping[str,Any] | None,
                           preopen_config:Mapping[str,Any] | None=None,
                           morning_plan_config:Mapping[str,Any] | None=None) -> str | None:
    """Resolve the exact current or next-session target for this one scheduled tick."""
    from v4.manager_research.workspace_plan_autorun import morning_config,morning_window,preopen_window
    from v4.manager_research.workspace_projection import HK,date_token

    source=date_token(source_date)
    if now.tzinfo is None:
        raise ValueError("PLAN_OWNER_CLOCK_MUST_BE_AWARE")
    local=now.astimezone(HK)
    if local.strftime("%Y%m%d")!=source:
        raise ValueError("PLAN_OWNER_SOURCE_DATE_CLOCK_MISMATCH")
    morning=morning_config(morning_plan_config)
    if morning["enabled"]:
        start,freeze=morning_window(source)
        if start<=local<freeze and (local.hour*60+local.minute)%(morning["interval_seconds"]//60)==0:
            return source
    preopen=preopen_config or {"enabled":True,"lead_seconds":180,"status":"PROPOSAL_ONLY"}
    if preopen.get("enabled",True):
        start,end=preopen_window(source,lead_seconds=preopen.get("lead_seconds",180))
        if start<=local<end:
            return source
    draft=_plan_refresh_config(plan_config)
    local_time=local.timetz().replace(tzinfo=None)
    if draft["enabled"] and draft["start_local"]<=local_time<draft["end_local"]:
        return next_hk_session_date(source)
    return None


def run_scheduled_plan_target(service:Any,target_trade_date:str,source_date:str,*,now:datetime,
                              plan_config:Mapping[str,Any] | None,
                              preopen_config:Mapping[str,Any] | None=None,
                              morning_plan_config:Mapping[str,Any] | None=None) -> dict[str,Any]:
    """Dispatch one exact-date plan branch through the caller's existing owner."""
    from v4.manager_research.workspace_plan_autorun import (
        morning_config as validate_morning_config,
        morning_window,
        preopen_window,
        run_scheduled_morning_plan,
        run_scheduled_preopen_plan_safe,
    )
    from v4.manager_research.workspace_projection import HK,date_token

    source=date_token(source_date); target=date_token(target_trade_date); local=now.astimezone(HK)
    expected=scheduled_cycle_target(source,now=local,plan_config=plan_config,
        preopen_config=preopen_config,morning_plan_config=morning_plan_config)
    if expected!=target:
        raise ValueError("PLAN_OWNER_TARGET_DATE_OR_WINDOW_MISMATCH")
    morning=validate_morning_config(morning_plan_config)
    if morning["enabled"]:
        start,freeze=morning_window(source)
        if start<=local<freeze and (local.hour*60+local.minute)%(morning["interval_seconds"]//60)==0:
            result=run_scheduled_morning_plan(service,target,now=local,config=morning_plan_config)
            branch="MORNING"
        else:
            result=None
    else:
        result=None
    if result is None:
        preopen=preopen_config or {"enabled":True,"lead_seconds":180,"status":"PROPOSAL_ONLY"}
        start,end=preopen_window(source,lead_seconds=preopen.get("lead_seconds",180))
        if preopen.get("enabled",True) and start<=local<end:
            result=run_scheduled_preopen_plan_safe(service,target,now=local,config=preopen)
            branch="PREOPEN"
    if result is None:
        result=run_next_hk_session_plan_material_refresh(service,source,now=local,config=plan_config)
        if result.get("target_trade_date")!=target:
            raise ValueError("PLAN_OWNER_EVENING_TARGET_MISMATCH")
        branch="EVENING_NEXT_SESSION"
    branch_status=result.get("status")
    status="FAILED" if branch_status=="FAILED" else "PARTIAL" if branch_status=="PARTIAL" else "SUCCEEDED"
    return {"status":status,"branch":branch,"target_trade_date":target,"plan_result":result,
        "owner":"ManagerResearchJobService.refresh_workspace_plan","policy_status":"PROPOSAL_ONLY",
        "RESEARCH_ONLY":True,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}


def vibe_refresh_due(binding:Mapping[str,Any],now:datetime) -> bool:
    config=_vibe_refresh_config(binding.get("vibe_refresh"))
    if not binding.get("enabled") or not config["enabled"] or now.tzinfo is None:
        return False
    local=now.astimezone(ZoneInfo("Asia/Shanghai"))
    return (local.hour,local.minute)==(6,55)


def run_vibe_refresh_only(binding:Mapping[str,Any],source_date:str,*,now:datetime) -> dict[str,Any]:
    if not vibe_refresh_due(binding,now):
        raise ValueError("VIBE_REFRESH_OUTSIDE_SAFE_WINDOW")
    binding_path=binding.get("vibe_binding_path")
    if not isinstance(binding_path,str) or not binding_path:
        raise ValueError("VIBE_BINDING_PATH_NOT_CONFIGURED")
    from ops.refresh_manager_vibe_radar_binding import capture_and_bind,eligible_hk_plan_trade_date
    target=eligible_hk_plan_trade_date(source_date)
    return capture_and_bind(target,binding_path,now=now)


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
    from v4.manager_research.workspace_plan_autorun import morning_config as validate_morning_config
    morning_plan_config=validate_morning_config(value.get('morning_plan'))
    vibe_config=_vibe_refresh_config(value.get('vibe_refresh'))
    if vibe_config['enabled'] and not isinstance(value.get('vibe_binding_path'),str):
        raise ValueError('VIBE_BINDING_PATH_NOT_CONFIGURED')
    if plan_only and (not plan_config['enabled'] or announcement_enabled):
        raise ValueError('PLAN_MATERIAL_REFRESH_ONLY_CONFIG_INVALID')
    if any(os.environ.get(k,'false').lower() not in {'false','0','off',''} for k in
           ('PRODUCTION_ALLOWED','BUY_GATE_UPDATED','ORDERS_SENT')):
        raise ValueError('ANNOUNCEMENT_WORKER_UNSAFE_ENVIRONMENT')
    from v4.manager_research.announcement_autorun import policy_due
    from v4.manager_research.workspace_projection import HK
    now=datetime.now(HK)
    if args.dry_run:
        target=scheduled_cycle_target(now.strftime('%Y%m%d'),now=now,plan_config=plan_config,
            preopen_config=value.get('preopen_plan'),morning_plan_config=morning_plan_config)
        print(json.dumps(dict(status='DRY_RUN',dry_run=True,network_requests=0,state_writes=0,
            vibe_refresh_due=vibe_refresh_due(value,now),plan_target_trade_date=target,
            plan_material_refresh_only=plan_only,
            announcement_collection='DISABLED_PLAN_REFRESH_ONLY' if plan_only else ('ENABLED' if announcement_enabled else 'DISABLED'),
            policy_status='PROPOSAL_ONLY',RESEARCH_ONLY=True,production_allowed=False,
            buy_gate_updated=False,orders_sent=False)))
        return 0
    if vibe_refresh_due(value,now):
        try:
            result=run_vibe_refresh_only(value,now.strftime('%Y%m%d'),now=now)
        except Exception as exc:
            result={'status':'FAILED','reason':type(exc).__name__,
                'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
        print(json.dumps({**result,'policy_status':'PROPOSAL_ONLY','announcement_network_requests':0,
            'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}))
        return 2 if result.get('status')=='FAILED' else 0

    plan_target=scheduled_cycle_target(now.strftime('%Y%m%d'),now=now,plan_config=plan_config,
        preopen_config=value.get('preopen_plan'),morning_plan_config=morning_plan_config)
    if plan_target is not None:
        try:
            from v4.manager_research.plan_owner_dispatch import request_bound_plan_cycle
            result=request_bound_plan_cycle(args.binding,plan_target)
        except (ValueError,OSError,TimeoutError) as exc:
            result={'status':'FAILED','reason':type(exc).__name__,
                'outcome':'OWNER_READBACK_REQUIRED_NO_RETRY'}
        print(json.dumps({**result,'policy_status':'PROPOSAL_ONLY','announcement_network_requests':0,
            'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}))
        return 2 if result.get('status')=='FAILED' else 0

    if plan_only or not announcement_enabled:
        print(json.dumps(dict(status='NOT_DUE',network_requests=0,state_writes=0,
            plan_material_refresh_only=plan_only,
            announcement_collection='DISABLED_PLAN_REFRESH_ONLY' if plan_only else 'DISABLED',
            policy_status='PROPOSAL_ONLY',RESEARCH_ONLY=True,production_allowed=False,
            buy_gate_updated=False,orders_sent=False)))
        return 0
    status='DISABLED' if not value['enabled'] else 'ELIGIBLE' if policy_due(now,value['policy']) else 'OUTSIDE_WINDOW'
    if status!='ELIGIBLE':
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
        result=service.refresh_announcements(now.strftime('%Y%m%d'),schedule=dict(
            policy=value['policy'],priority_codes=value['priority_codes'],now=now.isoformat(),
            execution_identity=dict(status='BOUND_WORKER',app_root_sha256=hashlib.sha256(str(APP_ROOT).encode()).hexdigest(),
                source_inventory_sha256=hashlib.sha256(json.dumps(value['files'],sort_keys=True).encode()).hexdigest(),
                python_sha256=value['python_sha256'])))
        print(json.dumps(dict(status=result['status'],attempt=(result.get('attempt') or {}).get('run_id'),
            announcement_collection='ENABLED',RESEARCH_ONLY=True,production_allowed=False,
            buy_gate_updated=False,orders_sent=False)))
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
