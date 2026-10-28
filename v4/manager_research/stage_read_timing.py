"""Manager read-only Stage schedule/attempt/artifact dimensions. Never ensure.

The existing scheduler owns due/calendar decisions. Missing artifact and missing
receipt are not evidence of execution failure. A verified failed attempt or
concrete identity/integrity error always remains visible before the window.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping
from contracts.stages import STAGE_DEFINITIONS
from .workspace_projection import HK, date_token


def project_stage_read_timing(source: Mapping[str,Any], date: str, now: datetime, *, attempt=None,
                              ledger_verified_empty=False, due_evaluator=None) -> dict:
    date=date_token(date)
    if now.tzinfo is None:raise ValueError('STAGE_STATUS_AWARE_CLOCK_REQUIRED')
    now=now.astimezone(HK)
    stage_id=source.get('stage_id') or source.get('target_stage_id')
    reasons=list(source.get('cannot_confirm') or source.get('gaps') or [])
    status=source.get('status','CANNOT_CONFIRM')
    result={'stage_id':stage_id,'target_trade_date':date,'evaluated_at':now.isoformat(),
      'artifact_status':status,'artifact_verified':False,'source_reasons':reasons,
      'execution_state':'SCHEDULE_UNVERIFIED','schedule_state':'CANNOT_CONFIRM','schedule_overview':[],
      'read_only':True,'owner_called':False,'binding_verified':False}
    declared_execution=source.get('execution_evidence')
    declared_attempt=(isinstance(declared_execution,Mapping)
      and declared_execution.get('status')=='DECLARED_ONLY'
      and type(declared_execution.get('node_attempt_count')) is int
      and declared_execution.get('node_attempt_count')>0)
    if isinstance(declared_execution,Mapping):
        result['source_execution_evidence']=deepcopy(dict(declared_execution))
    if declared_attempt:
        result['attempt_verification']='UNVERIFIED_SOURCE_DECLARATION'
    try:
        if due_evaluator is None:
            from stage_center.scheduler import evaluate_due
            due_evaluator=evaluate_due
        ids=[stage_id] if stage_id in STAGE_DEFINITIONS else list(STAGE_DEFINITIONS)
        for key in ids:
            decision=due_evaluator(key,date,now)
            result['schedule_overview'].append({'stage_id':key,'status':decision.status,
              'scheduled_at':decision.scheduled_at.isoformat() if decision.scheduled_at else None,
              'calendar':dict(decision.calendar)})
        states={item['status'] for item in result['schedule_overview']}
        result['schedule_state']=next(iter(states)) if len(states)==1 else 'MIXED_STAGE_SCHEDULE'
    except (ImportError,ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
        result['schedule_error']=type(exc).__name__;states={'CANNOT_CONFIRM'}
    invalid=(source.get('target_trade_date',source.get('trade_date',date))!=date or
       any(any(word in str(reason) for word in ('SHA_MISMATCH','HASH_INVALID','TARGET_DATE_MISMATCH','CONTRACT_INVALID','SOURCE_INTEGRITY_FAILED')) for reason in reasons))
    if invalid:result['execution_state']='ARTIFACT_INVALID'
    elif isinstance(attempt,Mapping) and attempt.get('verification')=='ORIGINAL_LEDGER_CHAIN_VERIFIED' and attempt.get('state') in {'FAILED','RUNNING'}:
        result['execution_state']=attempt['state'];result['run_id']=attempt.get('run_id')
    elif declared_attempt:
        # A source-declared node attempt conflicts with an empty ledger, but it
        # is not independently verified and must not be promoted to FAILED.
        result['execution_state']='DUE_RECEIPT_UNKNOWN'
    elif status in {'READY','READY_EMPTY','EMPTY','SUCCEEDED','PARTIAL','PARTIAL_WITH_ROWS'}:
        result['execution_state']='PRODUCT_AVAILABLE' # original reader assertion, not new independent validation
    elif status=='FAILED':result['execution_state']='SOURCE_READ_FAILED'
    elif states=={'NOT_DUE'}:result['execution_state']='NOT_DUE'
    elif states=={'SKIPPED_NON_TRADING_DAY'}:result['execution_state']='SKIPPED_NON_TRADING_DAY'
    elif stage_id not in STAGE_DEFINITIONS and states-{'CANNOT_CONFIRM'}:result['execution_state']='STAGE_ID_UNBOUND'
    elif states and states<={'DUE','LATE_CATCHUP_REPLAY'}:
        result['execution_state']='DUE_NO_ATTEMPT' if ledger_verified_empty else 'DUE_RECEIPT_UNKNOWN'
    return result
