"""Read-side timing with an injected already-verified calendar decision. No ensure."""
from datetime import datetime
from types import SimpleNamespace
from copy import deepcopy
import importlib.util
import pytest
from contracts.stages import STAGE_DEFINITIONS

def module():
 assert importlib.util.find_spec('v4.manager_research.stage_read_timing'), 'Stage timing read contract not wired'
 from v4.manager_research import stage_read_timing
 return stage_read_timing

def due(stage,date,now):
 scheduled=datetime.fromisoformat('2026-09-28T'+STAGE_DEFINITIONS[stage]['cutoff']+'+08:00')
 return SimpleNamespace(status='NOT_DUE' if now<scheduled else 'DUE',scheduled_at=scheduled,
                        calendar={'hk_securities':'FULL_TRADING_DAY','a_share':'NON_TRADING_DAY'})


def project(source=None,at='2026-09-28T07:51:00+08:00',attempt=None,empty=False):
 return module().project_stage_read_timing(source or {'status':'CANNOT_CONFIRM','target_trade_date':'20260928',
  'stage_id':'STAGE_0925','cannot_confirm':['SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID','EXECUTION_RECEIPT_MISSING']},
  '20260928',datetime.fromisoformat(at),attempt=attempt,ledger_verified_empty=empty,due_evaluator=due)


def test_before_window_no_artifact_is_not_a_failed_run():
 r=project();assert r['execution_state']=='NOT_DUE';assert r['artifact_status']=='CANNOT_CONFIRM'
 assert r['source_reasons']==['SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID','EXECUTION_RECEIPT_MISSING']
 assert r['artifact_verified'] is False


def test_due_and_verified_no_attempt_separated_from_unknown_ledger():
 assert project(at='2026-09-28T09:25:05+08:00',empty=True)['execution_state']=='DUE_NO_ATTEMPT'
 assert project(at='2026-09-28T09:25:05+08:00')['execution_state']=='DUE_RECEIPT_UNKNOWN'


def test_real_failed_attempt_never_hidden_by_not_due():
 a={'verification':'ORIGINAL_LEDGER_CHAIN_VERIFIED','state':'FAILED','run_id':'abc'}
 assert project(attempt=a)['execution_state']=='FAILED'


def test_fake_failed_attempt_cannot_assert_execution_failure():
 assert project(attempt={'state':'FAILED'})['execution_state']=='NOT_DUE'


def test_invalid_artifact_not_relabelled_healthy_before_due():
 r=project(source={'target_trade_date':'20260928','stage_id':'STAGE_0925','status':'CANNOT_CONFIRM','cannot_confirm':['ARTIFACT_SHA_MISMATCH']})
 assert r['execution_state']=='ARTIFACT_INVALID';assert r['schedule_state']=='NOT_DUE'


def test_calendar_unknown_stays_unknown():
 m=module();r=m.project_stage_read_timing({},'20260928',datetime.fromisoformat('2026-09-28T07:00:00+08:00'),
  due_evaluator=lambda *a:SimpleNamespace(status='CANNOT_CONFIRM',scheduled_at=None,calendar={}))
 assert r['execution_state']=='SCHEDULE_UNVERIFIED'


def test_all_stages_not_due_can_describe_unknown_stage_reader_without_inventing_id():
 r=project(source={'target_trade_date':'20260928','status':'CANNOT_CONFIRM'})
 assert r['execution_state']=='NOT_DUE';assert r['stage_id'] is None
 assert len(r['schedule_overview'])==8


def test_unknown_stage_with_partial_due_cannot_claim_no_attempt():
 r=project(source={'target_trade_date':'20260928','status':'CANNOT_CONFIRM'},at='2026-09-28T10:00:00+08:00',empty=True)
 assert r['execution_state']=='STAGE_ID_UNBOUND'


def test_hk_market_not_inferred_from_a_share_calendar():
 r=project();assert r['schedule_overview'][0]['calendar']['a_share']=='NON_TRADING_DAY'
 assert r['schedule_state']=='NOT_DUE'


def test_other_date_artifact_invalid_and_input_immutable():
 s={'status':'READY','target_trade_date':'20260925','stage_id':'STAGE_0925'};before=deepcopy(s)
 assert project(source=s)['execution_state']=='ARTIFACT_INVALID';assert s==before


def test_verified_empty_product_is_result_not_failure():
 assert project(source={'status':'READY_EMPTY','target_trade_date':'20260928','stage_id':'STAGE_0925'})['execution_state']=='PRODUCT_AVAILABLE'


def test_declared_unverified_natural_attempt_is_not_hidden_by_verified_empty_ledger():
 source={'target_trade_date':'20260928','trade_date':'20260928','stage_id':'STAGE_0930_0935',
  'status':'CANNOT_CONFIRM','execution_evidence':{'status':'DECLARED_ONLY','attempt_mode':'NATURAL',
  'node_attempt_count':1,'node_outcome':'TRANSIENT','first_failed_layer':'EXACT_SELECTION_INPUT_BINDING',
  'error':'synthetic exact-binding failure fixture','execution_verified':False,'natural_verified':False}}
 r=project(source=source,at='2026-09-28T09:35:30+08:00',empty=True)
 assert r['execution_state']=='DUE_RECEIPT_UNKNOWN'
 assert r['attempt_verification']=='UNVERIFIED_SOURCE_DECLARATION'
 assert r['source_execution_evidence']==source['execution_evidence']
 assert r['source_execution_evidence']['execution_verified'] is False
