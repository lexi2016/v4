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
    paths=list(root.glob('*.json'))
    if len(paths)>4096:raise ValueError('PLAN_MATERIAL_REFRESH_ATTEMPT_BOUND_EXCEEDED')
    for path in sorted(paths):
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


def _saved_owner_readback(service:Any,target:str,saved:Mapping[str,Any]) -> dict[str,Any]:
    """Read the immutable attempt belonging to this exact saved owner product."""
    from copy import deepcopy
    run_id=str(saved.get('run_id') or '')
    if not re.fullmatch(r'[0-9a-f]{32}',run_id):
        raise ValueError('PLAN_MATERIAL_REFRESH_SAVED_RUN_INVALID')
    value=deepcopy(saved['workspace'])
    value['plan_product']={
        'status':'CURRENT','run_id':run_id,'sha256':saved.get('sha256'),
        'generated_at':saved.get('generated_at'),
        'execution_kind':saved.get('execution_kind','MANUAL_REFRESH'),
        'original_owner':saved.get('owner'),'consumed':True,
    }
    value['workspace_plan_attempt']=service.store._read(
        service.store.root/'workspace_plan_runs'/target/(run_id+'.json'))
    return value


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
    # Serialize admission, source identity, retry budget, and the existing
    # owner's write across API processes. This lock produces no business data.
    with service.store._transaction(target,'workspace-plan-evening-dispatch'):
        return _run_evening_owner(service,target,local,cfg)


def _run_evening_owner(service:Any,target:str,local:datetime,cfg:Mapping[str,Any]) -> dict[str,Any]:
    from v4.manager_research import workspace
    from v4.manager_research.workspace_plan_autorun import owner_plan_readback
    saved=workspace._read_plan(service.store,target)
    if saved and saved.get('execution_kind')=='SCHEDULED_PREOPEN':
        result=owner_plan_readback(_saved_owner_readback(service,target,saved),target,
                                  expected_kind='SCHEDULED_PREOPEN')
        return {**result,'status':'PARTIAL' if result['status']=='PARTIAL' else 'PRESERVED_SCHEDULED_PREOPEN',
                'owner_product_status':'PRESERVED_SCHEDULED_PREOPEN'}
    current=workspace.get_workspace(service,target,include_saved=False,now=local)
    current_identity=current.get('input_identity')
    if not re.fullmatch(r'[0-9a-f]{64}',str(current_identity or '')):
        raise ValueError('PLAN_MATERIAL_REFRESH_INPUT_IDENTITY_INVALID')
    if (saved and saved.get('input_identity')==current_identity
            and saved.get('workspace',{}).get('semantic_version')==current.get('semantic_version')):
        result=owner_plan_readback(_saved_owner_readback(service,target,saved),target,
                                  expected_kind='MANUAL_REFRESH')
        return {**result,'status':'PARTIAL' if result['status']=='PARTIAL' else 'ALREADY_CURRENT',
                'owner_product_status':'ALREADY_CURRENT'}
    attempts=_attempts_today(service,target,local)
    # The declared target-date budget does not restart when materials change.
    if len(attempts)>=cfg['max_attempts_per_target_date']:
        return {'status':'RETRY_LIMIT_REACHED','target_trade_date':target,'attempts':len(attempts),
            'policy_status':'PROPOSAL_ONLY'}
    if attempts:
        last=max(attempts,key=lambda row:row.get('started_at',''))
        if last.get('state')=='RUNNING':
            return {'status':'OWNER_RECONCILIATION_REQUIRED','target_trade_date':target,
                    'attempts':len(attempts),'policy_status':'PROPOSAL_ONLY'}
        if last.get('state')=='FAILED':
            finished=datetime.fromisoformat(str(last.get('finished_at') or last['started_at']))
            if (local-finished.astimezone(local.tzinfo)).total_seconds()<cfg['retry_backoff_seconds']:
                return {'status':'RETRY_BACKOFF','target_trade_date':target,'attempts':len(attempts),
                    'retry_after_seconds':cfg['retry_backoff_seconds'],'policy_status':'PROPOSAL_ONLY'}
    result=service.refresh_workspace_plan(target,execution_kind='MANUAL_REFRESH',now=local)
    readback=owner_plan_readback(result,target,expected_kind='MANUAL_REFRESH')
    saved=workspace._read_plan(service.store,target)
    if (not saved or saved.get('execution_kind')!='MANUAL_REFRESH'
            or saved.get('run_id')!=readback['run_id']
            or saved.get('sha256')!=readback['product_sha256']
            or saved.get('input_identity')!=readback['input_identity']):
        raise ValueError('PLAN_MATERIAL_REFRESH_READBACK_INVALID')
    return {**readback,
        'success_scope':'EXACT_DATE_RESEARCH_PLAN_NOT_FORMAL_RECOMMENDATION_OR_NATURAL_CAPTURE',
        'policy_status':'PROPOSAL_ONLY'}


def run_plan_material_refresh_only_cycle(service:Any,source_date:str,*,now:datetime,
                                         plan_config:Mapping[str,Any],preopen_config:Mapping[str,Any] | None=None,
                                         morning_config:Mapping[str,Any] | None=None) -> dict[str,Any]:
    """Existing injected owner only; the worker uses the bound API RPC below."""
    from v4.manager_research.workspace_plan_autorun import run_scheduled_preopen_plan_safe,run_scheduled_morning_plan
    morning=run_scheduled_morning_plan(service,source_date,now=now,config=morning_config)
    preopen=run_scheduled_preopen_plan_safe(service,source_date,now=now,config=preopen_config)
    draft=run_next_hk_session_plan_material_refresh(service,source_date,now=now,config=plan_config)
    failed=any(row.get('status')=='FAILED' for row in (morning,preopen,draft))
    partial=any(row.get('status')=='PARTIAL' for row in (morning,preopen,draft))
    return {'status':'FAILED' if failed else 'PARTIAL' if partial else 'SUCCEEDED','preopen_plan':preopen,
        'morning_plan':morning,
        'next_session_draft':draft,'announcement_collection':{'status':'DISABLED_PLAN_REFRESH_ONLY',
            'announcement_network_requests':0},'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}


def scheduled_cycle_branch(source_date:str,*,now:datetime,plan_config:Mapping[str,Any] | None,
                           preopen_config:Mapping[str,Any] | None=None,
                           morning_plan_config:Mapping[str,Any] | None=None) -> str | None:
    """Resolve the original morning, pre-open, or next-session window."""
    from v4.manager_research.workspace_plan_autorun import morning_config,morning_window,preopen_window
    from v4.manager_research.workspace_projection import HK,date_token
    from contracts.trading_calendar import load_market_calendar,resolve_market_states,TradingDayState
    source=date_token(source_date)
    if now.tzinfo is None or now.astimezone(HK).strftime('%Y%m%d')!=source:
        raise ValueError('PLAN_OWNER_SOURCE_DATE_CLOCK_MISMATCH')
    local=now.astimezone(HK)
    state=resolve_market_states(load_market_calendar(),source)['hk_securities']
    if state not in {TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}:
        return None
    morning=morning_config(morning_plan_config)
    if morning['enabled']:
        start,freeze=morning_window(source)
        if start<=local<freeze and (local.hour*60+local.minute)%(morning['interval_seconds']//60)==0:
            return 'MORNING'
    preopen=preopen_config or {'enabled':True,'lead_seconds':180,'status':'PROPOSAL_ONLY'}
    if preopen.get('enabled',True):
        start,end=preopen_window(source,lead_seconds=preopen.get('lead_seconds',180))
        if start<=local<end:return 'PREOPEN'
    cfg=_plan_refresh_config(plan_config)
    local_time=local.timetz().replace(tzinfo=None)
    if cfg['enabled'] and cfg['start_local']<=local_time<cfg['end_local']:
        return 'EVENING_NEXT_SESSION'
    return None


def scheduled_cycle_target(source_date:str,*,now:datetime,plan_config:Mapping[str,Any] | None,
                           preopen_config:Mapping[str,Any] | None=None,
                           morning_plan_config:Mapping[str,Any] | None=None) -> str | None:
    branch=scheduled_cycle_branch(source_date,now=now,plan_config=plan_config,
        preopen_config=preopen_config,morning_plan_config=morning_plan_config)
    return (next_hk_session_date(source_date) if branch=='EVENING_NEXT_SESSION'
            else source_date if branch is not None else None)


def daily_cycle_branch(source_date:str,*,now:datetime,plan_config:Mapping[str,Any] | None,
                       preopen_config:Mapping[str,Any] | None=None,
                       morning_plan_config:Mapping[str,Any] | None=None,
                       daily_config:Mapping[str,Any] | None=None) -> tuple[str | None,str | None]:
    """Keep original windows and add only the sealed finite same-day catch-up slots."""
    from infrastructure.scheduling.manager_announcement_supervisor import daily_automation_config
    from v4.manager_research.workspace_projection import HK,date_token
    from contracts.trading_calendar import load_market_calendar,resolve_market_states,TradingDayState
    source=date_token(source_date)
    if now.tzinfo is None or now.astimezone(HK).strftime('%Y%m%d')!=source:
        raise ValueError('PLAN_OWNER_SOURCE_DATE_CLOCK_MISMATCH')
    original=scheduled_cycle_branch(source,now=now,plan_config=plan_config,
        preopen_config=preopen_config,morning_plan_config=morning_plan_config)
    if original in {'MORNING','PREOPEN'}:
        return original,None
    cfg=daily_automation_config(daily_config)
    if not cfg['enabled']:
        return original,None
    state=resolve_market_states(load_market_calendar(),source)['hk_securities']
    if state not in {TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}:
        return None,None
    local=now.astimezone(HK)
    slot=local.strftime('%H:%M')
    if slot in cfg['same_day_catchup_slots_local']:
        return 'SAME_DAY_CATCHUP',local.strftime('%Y%m%dT%H%M')
    return original,None


def daily_cycle_target(source_date:str,*,now:datetime,plan_config:Mapping[str,Any] | None,
                       preopen_config:Mapping[str,Any] | None=None,
                       morning_plan_config:Mapping[str,Any] | None=None,
                       daily_config:Mapping[str,Any] | None=None) -> str | None:
    branch,_=daily_cycle_branch(source_date,now=now,plan_config=plan_config,
        preopen_config=preopen_config,morning_plan_config=morning_plan_config,
        daily_config=daily_config)
    return (next_hk_session_date(source_date) if branch=='EVENING_NEXT_SESSION'
            else source_date if branch is not None else None)


def daily_admitted_branch_is_live(source_date:str,target_date:str,branch:str,*,scheduled_slot:str | None,
                                  now:datetime,plan_config:Mapping[str,Any] | None,
                                  preopen_config:Mapping[str,Any] | None=None,
                                  morning_plan_config:Mapping[str,Any] | None=None,
                                  daily_config:Mapping[str,Any] | None=None) -> bool:
    """Revalidate an already-admitted daily slot without losing minute-rollover work.

    Admission happens once in the bound RPC. The bounded US preparation and
    plan call can cross a wall-clock minute, so the original slot is retained
    for up to two minutes while still requiring the same Hong Kong trade date.
    A fresh child cannot use this grace period: its RPC must first pass the
    exact-minute ``daily_cycle_branch`` admission above.
    """
    from datetime import timedelta
    from v4.manager_research.workspace_projection import HK,date_token
    source=date_token(source_date);target=date_token(target_date)
    if now.tzinfo is None or now.astimezone(HK).strftime('%Y%m%d')!=source:
        return False
    local=now.astimezone(HK)
    if branch in {'MORNING','SAME_DAY_CATCHUP'}:
        if not isinstance(scheduled_slot,str) or not re.fullmatch(source+r'T\d{4}',scheduled_slot):
            return False
        slot_time=datetime.strptime(scheduled_slot,'%Y%m%dT%H%M').replace(tzinfo=HK)
        if local < slot_time or local >= slot_time+timedelta(seconds=120):
            return False
        if branch=='MORNING':
            from v4.manager_research.workspace_plan_autorun import morning_config,morning_window
            cfg=morning_config(morning_plan_config)
            start,freeze=morning_window(source)
            return bool(target==source and cfg['enabled'] and start<=slot_time<freeze
                and (slot_time.hour*60+slot_time.minute)%(cfg['interval_seconds']//60)==0)
        from infrastructure.scheduling.manager_announcement_supervisor import daily_automation_config
        cfg=daily_automation_config(daily_config)
        return bool(target==source and cfg['enabled']
            and slot_time.strftime('%H:%M') in cfg['same_day_catchup_slots_local'])
    expected_branch,expected_slot=daily_cycle_branch(source,now=local,plan_config=plan_config,
        preopen_config=preopen_config,morning_plan_config=morning_plan_config,daily_config=daily_config)
    expected_target=daily_cycle_target(source,now=local,plan_config=plan_config,
        preopen_config=preopen_config,morning_plan_config=morning_plan_config,daily_config=daily_config)
    return bool(expected_branch==branch and expected_target==target and expected_slot==scheduled_slot)


def run_same_day_catchup_plan(service:Any,target_trade_date:str,*,now:datetime,
                              scheduled_slot:str,trigger_id:str,
                              us_market_request_context:Mapping[str,Any] | None=None) -> dict[str,Any]:
    """Refresh only through the original manual plan owner with truthful late timing."""
    from v4.manager_research.workspace import _read_plan
    from v4.manager_research.workspace_plan_autorun import owner_plan_readback
    from v4.manager_research.workspace_projection import HK,date_token
    from v4.manager_research.workspace import get_workspace
    from v4.manager_research.workspace import verified_plan_attempt
    from datetime import datetime as _datetime
    target=date_token(target_trade_date);local=now.astimezone(HK)
    if local.strftime('%Y%m%d')!=target or not re.fullmatch(target+r'T\d{4}',scheduled_slot):
        raise ValueError('SAME_DAY_CATCHUP_IDENTITY_INVALID')
    scheduled_for=_datetime.strptime(scheduled_slot,'%Y%m%dT%H%M').replace(tzinfo=HK)
    execution_context={'trigger_kind':'SCHEDULED','timing':'LATE_CATCHUP',
        'scheduled_for':scheduled_for.isoformat(),'trigger_id':trigger_id,
        'natural_run_verified':False}
    saved=_read_plan(service.store,target)
    current=get_workspace(service,target,include_saved=False,now=local,
        us_market_request_context=us_market_request_context)
    unchanged=bool(saved is not None and saved.get('input_identity')==current.get('input_identity')
        and saved.get('workspace',{}).get('semantic_version')==current.get('semantic_version'))
    if unchanged and saved.get('execution_kind')=='SCHEDULED_PREOPEN':
        result=_saved_owner_readback(service,target,saved)
        plan=owner_plan_readback(result,target,expected_kind='SCHEDULED_PREOPEN')
        plan={**plan,'status':'PRESERVED_SCHEDULED_PREOPEN',
            'owner_product_status':'PRESERVED_SCHEDULED_PREOPEN'}
    elif (unchanged and saved.get('execution_kind')=='MANUAL_REFRESH'
          and isinstance(saved.get('execution_context'),Mapping)):
        result=_saved_owner_readback(service,target,saved)
        plan=owner_plan_readback(result,target,expected_kind='MANUAL_REFRESH')
    else:
        value=service.refresh_workspace_plan(target,execution_kind='MANUAL_REFRESH',now=local,
            execution_context=execution_context,
            us_market_request_context=us_market_request_context)
        plan=owner_plan_readback(value,target,expected_kind='MANUAL_REFRESH')
    valid=valid_owner_plan_result(plan,'SAME_DAY_CATCHUP')
    state=plan.get('status')
    status=('PARTIAL' if valid and state=='PARTIAL' else 'SUCCEEDED' if valid else 'FAILED')
    reasons=plan.get('failure_reasons') if isinstance(plan.get('failure_reasons'),list) else None
    return {'status':status,'branch':'SAME_DAY_CATCHUP','target_trade_date':target,
        'plan_result':plan,'failure_reasons':reasons,
        'owner':'ManagerResearchJobService.refresh_workspace_plan','policy_status':'PROPOSAL_ONLY',
        'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}


def valid_owner_plan_result(plan:Mapping[str,Any],branch:str) -> bool:
    """The wire receipt preserves the same owner/run/attempt contract as the wrapper."""
    if any(key in plan and not isinstance(plan[key],str) for key in ('status','owner_attempt_state')):
        return False
    expected={'MORNING':'SCHEDULED_MORNING','PREOPEN':'SCHEDULED_PREOPEN',
              'EVENING_NEXT_SESSION':'MANUAL_REFRESH','SAME_DAY_CATCHUP':'MANUAL_REFRESH'}.get(branch)
    preserved=(branch in {'MORNING','EVENING_NEXT_SESSION','SAME_DAY_CATCHUP'}
        and plan.get('owner_product_status')=='PRESERVED_SCHEDULED_PREOPEN'
        and plan.get('execution_kind')=='SCHEDULED_PREOPEN')
    return bool(expected and (plan.get('execution_kind')==expected or preserved)
        and plan.get('execution_kind_source')=='OWNER_READBACK'
        and plan.get('owner')=='ManagerResearchJobService.refresh_workspace_plan'
        and re.fullmatch(r'[0-9a-f]{32}',str(plan.get('run_id') or ''))
        and plan.get('owner_attempt_run_id')==plan.get('run_id')
        and re.fullmatch(r'[0-9a-f]{64}',str(plan.get('owner_attempt_sha256') or ''))
        and re.fullmatch(r'[0-9a-f]{64}',str(plan.get('product_sha256') or ''))
        and re.fullmatch(r'[0-9a-f]{64}',str(plan.get('input_identity') or ''))
        and isinstance(plan.get('failure_reasons'),list)
        and ((plan.get('owner_attempt_state')=='PARTIAL' and plan.get('status')=='PARTIAL'
              and bool(plan.get('failure_reasons')))
             or (plan.get('owner_attempt_state') in {'SUCCEEDED','SUCCEEDED_EMPTY'}
                 and not plan.get('failure_reasons')
                 and plan.get('status') in {'MATERIALIZED','ALREADY_MATERIALIZED',
                                          'ALREADY_CURRENT','PRESERVED_SCHEDULED_PREOPEN'})))


def run_scheduled_plan_target(service:Any,target_trade_date:str,source_date:str,*,now:datetime,
                              plan_config:Mapping[str,Any] | None,
                              preopen_config:Mapping[str,Any] | None=None,
                              morning_plan_config:Mapping[str,Any] | None=None,
                              daily_config:Mapping[str,Any] | None=None,
                              daily_branch:str | None=None,scheduled_slot:str | None=None,
                              trigger_id:str | None=None,
                              us_market_request_context:Mapping[str,Any] | None=None) -> dict[str,Any]:
    """Execute one target-date branch through the injected Manager owner."""
    from v4.manager_research.workspace_plan_autorun import run_scheduled_preopen_plan_safe,run_scheduled_morning_plan
    from v4.manager_research.workspace_projection import HK,date_token
    source=date_token(source_date);target=date_token(target_trade_date)
    if daily_branch is None:
        if scheduled_cycle_target(source,now=now,plan_config=plan_config,preopen_config=preopen_config,
                                  morning_plan_config=morning_plan_config)!=target:
            raise ValueError('PLAN_OWNER_TARGET_DATE_OR_WINDOW_MISMATCH')
        branch=scheduled_cycle_branch(source,now=now,plan_config=plan_config,preopen_config=preopen_config,
                                      morning_plan_config=morning_plan_config)
    else:
        if not daily_admitted_branch_is_live(source,target,daily_branch,scheduled_slot=scheduled_slot,
                now=now,plan_config=plan_config,preopen_config=preopen_config,
                morning_plan_config=morning_plan_config,daily_config=daily_config):
            raise ValueError('PLAN_OWNER_DAILY_TARGET_OR_WINDOW_MISMATCH')
        branch=daily_branch
    if branch=='MORNING':
        execution_context=None
        if daily_branch is not None:
            from datetime import datetime as _datetime
            scheduled_for=_datetime.strptime(str(scheduled_slot),'%Y%m%dT%H%M').replace(tzinfo=HK)
            execution_context={'trigger_kind':'SCHEDULED','timing':'ON_TIME',
                'scheduled_for':scheduled_for.isoformat(),'trigger_id':trigger_id,
                'natural_run_verified':False}
        plan=run_scheduled_morning_plan(service,target,now=now,config=morning_plan_config,
            execution_context=execution_context,us_market_request_context=us_market_request_context)
        branch_status_override=None
        branch_failure_override=None
    elif branch=='PREOPEN':
        plan=run_scheduled_preopen_plan_safe(service,target,now=now,config=preopen_config)
        branch_status_override=None
        branch_failure_override=None
    elif branch=='SAME_DAY_CATCHUP':
        if scheduled_slot is None or trigger_id is None:
            raise ValueError('SAME_DAY_CATCHUP_IDENTITY_REQUIRED')
        catchup=run_same_day_catchup_plan(service,target,now=now,scheduled_slot=scheduled_slot,
            trigger_id=trigger_id,us_market_request_context=us_market_request_context)
        plan=catchup.get('plan_result') if isinstance(catchup,Mapping) else None
        if not isinstance(plan,Mapping):
            raise ValueError('SAME_DAY_CATCHUP_OWNER_READBACK_MISSING')
        plan=dict(plan)
        branch_status_override=catchup.get('status')
        branch_failure_override=catchup.get('failure_reasons')
    else:
        plan=run_next_hk_session_plan_material_refresh(service,source,now=now,config=plan_config)
        if plan.get('target_trade_date')!=target:raise ValueError('PLAN_OWNER_EVENING_TARGET_MISMATCH')
        branch='EVENING_NEXT_SESSION'
        branch_status_override=None
        branch_failure_override=None
    state=plan.get('status')
    successful={'MATERIALIZED','ALREADY_MATERIALIZED','ALREADY_CURRENT','PRESERVED_SCHEDULED_PREOPEN'}
    status='SUCCEEDED' if state in successful else 'PARTIAL' if state in {'PARTIAL','RETRY_BACKOFF'} else 'FAILED'
    reasons=plan.get('failure_reasons') if isinstance(plan.get('failure_reasons'),list) else None
    owner_readback_valid=valid_owner_plan_result(plan,branch)
    if branch_status_override=='FAILED' and status=='SUCCEEDED':
        status='FAILED'
        reasons=branch_failure_override if isinstance(branch_failure_override,list) else ['PLAN_BRANCH_STATUS_INVALID']
    elif branch_status_override=='PARTIAL' and status=='SUCCEEDED':
        status='PARTIAL'
        reasons=branch_failure_override if isinstance(branch_failure_override,list) else reasons
    if status=='SUCCEEDED' and not owner_readback_valid:
        status='FAILED'
        reasons=['PLAN_OWNER_PRODUCT_READBACK_INVALID']
    elif owner_readback_valid and plan.get('owner_attempt_state')=='PARTIAL':
        status='PARTIAL'
    elif status in {'FAILED','PARTIAL'} and not reasons:
        reason=plan.get('reason') or state
        reason=str(reason) if isinstance(reason,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}',reason) else 'PLAN_BRANCH_STATUS_INVALID'
        reasons=['PLAN_BRANCH_'+reason]
    return {'status':status,
        'branch':branch,'target_trade_date':target,'plan_result':plan,
        'failure_reasons':reasons,
        'owner':'ManagerResearchJobService.refresh_workspace_plan','policy_status':'PROPOSAL_ONLY',
        'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding',required=True)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args(argv)
    from infrastructure.scheduling.manager_announcement_supervisor import load_binding
    try:
        value=load_binding(args.binding,APP_ROOT)
    except (ValueError,OSError,KeyError,TypeError) as exc:
        from v4.manager_research.plan_owner_dispatch import local_admission_failure
        print(json.dumps(local_admission_failure(exc)))
        return 2
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
    from v4.manager_research.workspace_projection import HK
    now=datetime.now(HK)
    from infrastructure.scheduling.manager_announcement_supervisor import daily_automation_config
    daily_config=daily_automation_config(value.get('daily_automation'))
    if value['enabled'] and daily_config['enabled']:
        plan_target=daily_cycle_target(now.strftime('%Y%m%d'),now=now,
            plan_config=value.get('plan_material_refresh'),preopen_config=value.get('preopen_plan'),
            morning_plan_config=value.get('morning_plan'),daily_config=value.get('daily_automation'))
    else:
        plan_target=(scheduled_cycle_target(now.strftime('%Y%m%d'),now=now,
            plan_config=value.get('plan_material_refresh'),preopen_config=value.get('preopen_plan'),
            morning_plan_config=value.get('morning_plan')) if value['enabled'] else None)
    if args.dry_run:
        print(json.dumps(dict(status='DRY_RUN',dry_run=True,network_requests=0,state_writes=0,
            plan_material_refresh_only=plan_only,plan_target_trade_date=plan_target,
            announcement_collection='DISABLED_PLAN_REFRESH_ONLY' if plan_only else ('ENABLED' if announcement_enabled else 'DISABLED'),
            policy_status='PROPOSAL_ONLY',RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)))
        return 0
    if plan_only:
        if plan_target is None:
            print(json.dumps(dict(status='NOT_DUE' if value['enabled'] else 'DISABLED',network_requests=0,state_writes=0,
                owner_execution_status='OWNER_NOT_CALLED',
                plan_material_refresh_only=True,announcement_collection='DISABLED_PLAN_REFRESH_ONLY',
                policy_status='PROPOSAL_ONLY',RESEARCH_ONLY=True,production_allowed=False,
                buy_gate_updated=False,orders_sent=False)))
            return 0
        try:
            from v4.manager_research.plan_owner_dispatch import request_bound_daily_cycle,request_bound_plan_cycle
            result=(request_bound_daily_cycle(args.binding,plan_target) if daily_config['enabled']
                    else request_bound_plan_cycle(args.binding,plan_target))
        except (ValueError,OSError,TimeoutError) as exc:
            from v4.manager_research.plan_owner_dispatch import rpc_call_failure
            result=rpc_call_failure(exc)
        print(json.dumps({**result,'policy_status':'PROPOSAL_ONLY','announcement_network_requests':0,
            'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}))
        return 2 if result.get('status')=='FAILED' else 0
    from v4.manager_research.announcement_autorun import policy_due
    status='DISABLED' if not value['enabled'] else 'ELIGIBLE' if policy_due(now,value['policy']) else 'OUTSIDE_WINDOW'
    if status!='ELIGIBLE':
        print(json.dumps(dict(status=status,dry_run=False,network_requests=0,state_writes=0,
            plan_material_refresh_only=False,announcement_collection='ENABLED' if announcement_enabled else 'DISABLED',
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
        # Plan calls always cross the same bound API boundary, including when
        # the separately opted-in material collector runs in this child. This
        # child never constructs a second, partially injected plan owner.
        plan_result={'status':'NOT_DUE'}
        if plan_target is not None:
            try:
                from v4.manager_research.plan_owner_dispatch import request_bound_plan_cycle
                plan_result=request_bound_plan_cycle(args.binding,plan_target)
            except (ValueError,OSError,TimeoutError) as exc:
                from v4.manager_research.plan_owner_dispatch import rpc_call_failure
                plan_result={**rpc_call_failure(exc),'blocks_announcement':False}
        if not announcement_enabled:
            print(json.dumps(dict(status='ANNOUNCEMENT_COLLECTION_DISABLED',plan_cycle=plan_result,
                production_allowed=False,buy_gate_updated=False,orders_sent=False)))
            return 0
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
            plan_cycle=plan_result, production_allowed=False,buy_gate_updated=False,orders_sent=False)))
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
