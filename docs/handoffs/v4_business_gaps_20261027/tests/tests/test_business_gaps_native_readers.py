import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import re
from zoneinfo import ZoneInfo

import pytest

FLAGS=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)


def reader(config):
    path=Path(__file__).parents[1]/'domains/runtime_graph_evidence.py'
    cls=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='CurrentEvidenceReader')
    def proof(path,root,*,kind):
        path=Path(path);assert path.is_relative_to(root) and path.resolve()==path
        raw=path.read_bytes();value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('EVIDENCE_NOT_OBJECT')
        return value,dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),kind=kind)
    ns=dict(Path=Path,datetime=datetime,ZoneInfo=ZoneInfo,FLAGS=FLAGS,re=re,proof=proof,safe=lambda value:None)
    exec(compile(ast.Module(body=[cls],type_ignores=[]),str(path),'exec'),ns)
    return ns['CurrentEvidenceReader'](config)


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path


@pytest.mark.parametrize('bad',[None,'date','node','safety','clock'])
def test_hk_original_diagnostic_identity_is_observation_not_selection(tmp_path,bad):
    root=tmp_path/'receipts';path=root/'20261027/STAGE_1545_1555/precapture_attempts/owned.json'
    value=dict(schema='stage_center.hk_precapture_diagnostic.v1',attempt_id='owned',trade_date='20261027',stage_id='STAGE_1545_1555',
        node_id='PRECAPTURE_1550',status='PRECAPTURE_COMPLETE',evaluated_at='2026-10-27T15:50:00+08:00',
        authorizes_selection=False,grants_retry=False,pre_captures=[dict(requested_rows=100,returned_rows=100)],**FLAGS)
    if bad=='date':value['trade_date']='20261028'
    elif bad=='node':value['node_id']='PRECAPTURE_OTHER'
    elif bad=='safety':value['orders_sent']=True
    elif bad=='clock':value['evaluated_at']='2026-10-27T15:50:00'
    write(path,value);before=path.read_bytes()
    result=reader({'stage_receipt_root':str(root)})._independent('20261027',dict(node_id='PRECAPTURE_1550',owner='STAGE_PRECAPTURE',business_stage_id='STAGE_1545_1555'))
    assert result['status']==('OBSERVED' if bad is None else 'CANNOT_CONFIRM')
    assert result['business_status']=='CANNOT_CONFIRM' and path.read_bytes()==before
    if bad is None:
        assert result['authorizes_selection'] is False and result['returned_rows']==100
        assert result['evidence'][0]['sha256']==hashlib.sha256(before).hexdigest()


def test_a_failed_attempt_preserves_real_failure_and_clock_without_becoming_ready_empty(tmp_path):
    path=write(tmp_path/'native_opening/20261027/STAGE_0925/attempts/owned.json',dict(trade_date='20261027',stage_id='STAGE_0925',
        attempt_id='owned',authorizes_selection=False,finished_at='2026-10-27T09:25:01+08:00',status='CANNOT_CONFIRM',error='A_NATIVE_NO_VALID_OBSERVATION_ROWS',
        payload={'requested_symbols':['A.000995','A.600048','A.920575'],'rows':[]},**FLAGS))
    result=reader({'native_reader_roots':{'stage_a_opening_root':str(tmp_path)}})._independent('20261027',dict(node_id='PRECAPTURE_A_0925',owner='STAGE_PRECAPTURE',business_stage_id='PRECAPTURE_A_0925'))
    assert result['source_status']=='CANNOT_CONFIRM' and result['returned_rows']==0
    assert result['reason']=='A_NATIVE_NO_VALID_OBSERVATION_ROWS' and result['business_status']=='CANNOT_CONFIRM'


def test_manager_terminal_job_never_infers_current_pid_or_plan_acceptance(tmp_path,monkeypatch):
    class JobRecord:
        @staticmethod
        def model_validate(value):
            return SimpleNamespace(**{**value,'context':SimpleNamespace(target_date=value.pop('target_date')),'state':SimpleNamespace(value=value.pop('state'))})
    monkeypatch.setitem(sys.modules,'v4.manager_workbench.contracts',SimpleNamespace(JobRecord=JobRecord))
    write(tmp_path/'manager_workbench/attempts/owned.json',dict(job_id='owned',run_id='result',target_date='20261027',state='SUCCEEDED',
        finished_at='2026-10-27T16:00:00+08:00',last_progress_at=None,started_at=None,failure_code=None,completed_count=2,total_count=2))
    result=reader({'native_reader_roots':{'manager_main_state_root':str(tmp_path)}})._independent('20261027',dict(node_id='manager_workbench',owner='MANAGER_WORKBENCH'))
    assert result['status']=='SUCCEEDED' and result['execution_phase']=='COMPLETED_OWNER_JOB'
    assert result['business_status']=='CANNOT_CONFIRM' and 'pid' not in result


def test_absent_roots_do_not_infer_default_or_call_producer():
    for node in ('PREP_0915','manager_workbench','manager_workbench_api','us_market_digest_independent','zsxq_pdf'):
        result=reader({})._independent('20261027',dict(node_id=node,owner='INDEPENDENT'))
        assert result['status']=='CANNOT_CONFIRM' and result['reader_status']=='NATIVE_EVIDENCE_MISSING_OR_UNVERIFIED'


def test_us_independent_broken_chain_never_reads_terminal_or_main_ledger(tmp_path):
    obj=reader({'native_reader_roots':{'us_ledger_root':str(tmp_path)}})
    obj._independent.__func__.__globals__['ExecutionLedger']=lambda root:SimpleNamespace(verify_receipt_chain=lambda *a,**k:(False,'BROKEN'))
    result=obj._independent('20261027',dict(node_id='us_market_digest_independent',owner='V4_US_MARKET_DIGEST'))
    assert result['status']=='CANNOT_CONFIRM' and result['reason']=='US_INDEPENDENT_LEDGER_CHAIN:BROKEN'


def test_pdf_compact_uses_original_metadata_resolver_without_certifying_completion(tmp_path,monkeypatch):
    root=tmp_path/'external_sources/zsxq_hourly';root.mkdir(parents=True)
    write(root/'zsxq_pdf_ingestion_index.json',{})
    module=SimpleNamespace(STATE_RELATIVE='external_sources/zsxq_hourly/zsxq_pdf_ingestion_index.json',
        read_pdf_ingestion_projection=lambda *a:pytest.fail('compact must not repeat full document verification'),
        _read_index=lambda store:{'documents':{'d':{'source':{'trade_date':'20261027'},'engine_runs':{'e':{'status':'READY'}}}}},
        _latest_engine_run=lambda row:('e',row['engine_runs']['e']))
    monkeypatch.setitem(sys.modules,'infrastructure.zsxq_pdf_ingestion',module)
    result=reader({'native_reader_roots':{'pdf_data_root':str(tmp_path)}})._independent('20261027',dict(node_id='zsxq_pdf',owner='ZSXQ_PDF'),compact=True)
    assert result['status']=='CANNOT_CONFIRM' and result['source_status_counts']=={'READY':1}
    assert result['reason']=='NATIVE_QUEUE_INDEX_ONLY_COMPLETION_NOT_VERIFIED' and len(result['evidence'])==1


@pytest.mark.parametrize('old_status',['FAILED','SUCCEEDED'])
def test_valid_new_run_keeps_old_terminal_in_explicit_last_completed_result(tmp_path,monkeypatch,old_status):
    from datetime import timedelta
    now=datetime.now(ZoneInfo('Asia/Shanghai'));started=now-timedelta(minutes=5)
    module=SimpleNamespace(_observation_time=datetime.fromisoformat,
        _observation_process_state=lambda *a:('RUNNING','newrun','NATIVE_BOUND'))
    monkeypatch.setitem(sys.modules,'domains.task_status',module)
    config={'ledger_root':str(tmp_path),'inbox':str(tmp_path/'transport/inbox'),'main':{'app_root':'/owner/app','registry_sha256':'a'*64}}
    obj=reader(config);birth={'process_start_token':'owned_birth','process_started_at':started.isoformat()}
    obj._execution_entry.__func__.__globals__['process_identity']=lambda pid:birth
    entry=dict(caller_file='/owner/app/infrastructure/scheduling/executor_registry.py',caller_sha256='a'*64,caller_function='__call__',
        owner_id='OWNER',attempt=1,slot='1700',run_id='newrun',pid=42,parent_pid=41,observed_at=now.isoformat(),
        source_path=str(tmp_path/'receipts/live/20261027/1700/newrun.dispatch-receipt.json'),**birth)
    obj._entry_records=lambda *a:[(entry,{'path':'entry','sha256':'b'*64})]
    for rel in ('claims/live/20261027/1700/dispatch.claim.json','workloads/live/20261027/1700/task.workload-claim.json'):
        write(tmp_path/rel,{'created_at':started.isoformat()})
    node={'status':old_status,'business_status':old_status,'run_id':'oldrun','execution_phase':'COMPLETED','observed_at':started.isoformat()}
    obj._execution_entry(node,SimpleNamespace(workload_id='task',owner_id='OWNER',slots=('1700',)),'20261027',SimpleNamespace(root=tmp_path),[],{'current_runtime_verified':True,'pid':41})
    assert node['execution_phase']=='RUNNING_VERIFIED_OBSERVATION'
    assert node['execution_observation']['run_id']=='newrun' and node['last_completed_result']['run_id']=='oldrun'
    assert node['last_completed_result']['status']==old_status and node['status']==old_status
    assert node['result_scope']=='LAST_COMPLETED_RESULT_CURRENT_RUN_IN_PROGRESS'
