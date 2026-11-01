"""Sidecar compatibility regressions: bind the real store protocol, not UI fields."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import os
import sys
from domains.report_evidence import ReportEvidenceService
from infrastructure.report_evidence_index import ReportIndex,digest,SAFETY
from infrastructure.report_evidence_sidecar import materialize
from tests.test_report_evidence import Owner,Tokens,detail

class SidecarCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.doc='a'*64
        self.owner=Owner(self.root/'source');self.owner.docs[self.doc]=detail(self.doc)
        self.index=ReportIndex(self.root/'index',self.owner);self.index.initialize();self.index.upsert(self.owner.docs[self.doc],Tokens())
        self.service=ReportEvidenceService(self.index)
        self.stage='STAGE_1445_1500';self.date='20261027';self.market='A_SHARE'
        self.envelope=dict(trade_date=self.date,stage_id=self.stage,market=self.market,run_id='run-fixture',artifact_id='selection-fixture',algorithm_sha256=digest('algo'),raw_artifact_sha256=digest('raw'),rows=[{'code':'A.301216','rank':1,'score':99}])
        self.receipt=dict(trade_date=self.date,stage_id=self.stage,markets={self.market:copy.deepcopy(self.envelope)},dispatch_mode='NATURAL',**SAFETY)
        self.receipt_root=self.root/'receipts';p=self.receipt_root/self.date/self.stage/'receipt.json';p.parent.mkdir(parents=True);p.write_text(json.dumps(self.receipt));self.path=p;self.before=p.read_bytes()
        env=self.envelope
        class ExistingStore:
            def __init__(self,root):self.root=Path(root)
            def read_verified(self,date,stage,market):
                if (date,stage,market)!=(env['trade_date'],env['stage_id'],env['market']):raise ValueError('scope')
                return copy.deepcopy(env)
            def _verify_run(self,date,stage,market,run):
                result=self.read_verified(date,stage,market)
                if run!=env['run_id']:raise ValueError('run')
                return dict(envelope=result,artifact_sha256=digest('csv'),manifest_sha256=digest('manifest'),receipt_sha256=digest('selection-receipt'))
        self.store_patch=patch('stage_center.selection.SelectionStore',ExistingStore);self.store_patch.start()
        self.config=dict(selection_root=str(self.root/'selection'),receipt_root=str(self.receipt_root))
    def tearDown(self):self.store_patch.stop();self.temp.cleanup()
    async def materialize(self,receipt=None):
        return await materialize(config=self.config,trade_date=self.date,stage_id=self.stage,receipt=receipt or self.receipt,service=self.service,root=self.root/'sidecars')

    async def test_store_trio_binding_without_consumer_constructor_or_display_field(self):
        # Old Main/Stage constructors reject the new keyword; neither is needed.
        with patch('stage_center.consumer.StageSelectionConsumer',side_effect=TypeError('old constructor')):
            result=await self.materialize()
        self.assertEqual(result['items'][0]['status'],'MATERIALIZED')
        value=json.loads(Path(result['items'][0]['path']).read_text())
        self.assertEqual(value['binding']['original_selection_run'],'run-fixture')
        self.assertEqual(value['binding']['selection_manifest_sha256'],digest('manifest'))
        self.assertEqual(value['binding']['cutoff'],'2026-10-27T15:00:00+08:00')
        # The only source becomes available the next day: it cannot enter Stage evidence.
        self.assertEqual(value['rows'][0]['evidence']['hits'],[])
        self.assertEqual(self.path.read_bytes(),self.before)

    async def test_original_receipt_and_run_identity_refuse_forgery(self):
        forged=copy.deepcopy(self.receipt);forged['markets'][self.market]['run_id']='run-other'
        with self.assertRaisesRegex(ValueError,'PERSISTED_RUNNER_RECEIPT_MISMATCH'):
            await self.materialize(forged)
        self.path.write_text(json.dumps(forged))
        result=await self.materialize(forged)
        self.assertEqual(result['items'][0]['status'],'EVIDENCE_GAP')
        self.assertFalse((self.root/'sidecars').exists())

    async def test_explicit_receipt_root_and_backfill_gate(self):
        self.config.pop('receipt_root')
        with self.assertRaisesRegex(ValueError,'RUNNER_RECEIPT_ROOT_UNVERIFIED'):await self.materialize()
        self.config['receipt_root']=str(self.receipt_root)
        backfill={**self.receipt,'mode':'BACKFILL'}
        with self.assertRaisesRegex(ValueError,'BACKFILL_NOT_FORMAL'):await self.materialize(backfill)

    async def test_completion_submit_is_fixed_async_idempotent_and_single_flight(self):
        from infrastructure.report_evidence_sidecar import on_stage_completed,consume_sidecar_job
        env=dict(V4_STAGE_REPORT_EVIDENCE_ENABLED='1',V4_RESEARCH_DATA_ROOT=str(self.owner.root),V4_REPORT_EVIDENCE_SIDECAR_ROOT=str(self.root/'sidecars'))
        kwargs=dict(config=self.config,trade_date=self.date,stage_id=self.stage,receipt=self.receipt)
        with patch.dict(os.environ,env),patch('infrastructure.report_evidence_sidecar.subprocess.Popen',return_value=SimpleNamespace(pid=12345)) as spawn:
            first=on_stage_completed(**kwargs);self.assertEqual(first['status'],'SUBMITTED')
            self.assertEqual(spawn.call_args.args[0][:5],[sys.executable,'-B','-m','ops.run_report_evidence_sidecar_job','--job-id'])
            with patch('infrastructure.report_evidence_sidecar._running_worker',return_value=True):
                duplicate=on_stage_completed(**kwargs);self.assertEqual(duplicate['status'],'REUSED');self.assertEqual(spawn.call_count,1)
                active=self.root/'sidecars/jobs/active.json';active.write_text(json.dumps(dict(pid=12345,job_id='f'*64)))
                busy=on_stage_completed(**kwargs);self.assertEqual(busy['status'],'BUSY');self.assertEqual(spawn.call_count,1)
            result=dict(status='SIDECAR_ONLY',items=[dict(status='MATERIALIZED')])
            with patch('infrastructure.report_evidence_sidecar._materialize_worker',return_value=result):
                done=consume_sidecar_job(first['job_id']);self.assertEqual(done['status'],'COMPLETED')
            repeated=on_stage_completed(**kwargs);self.assertEqual(repeated['status'],'REUSED');self.assertEqual(repeated['job_status'],'COMPLETED');self.assertEqual(spawn.call_count,1)
        self.assertEqual(self.path.read_bytes(),self.before)

    async def test_duplicate_observes_worker_finishing_during_pid_probe(self):
        from infrastructure.report_evidence_sidecar import on_stage_completed
        env=dict(V4_STAGE_REPORT_EVIDENCE_ENABLED='1',V4_RESEARCH_DATA_ROOT=str(self.owner.root),V4_REPORT_EVIDENCE_SIDECAR_ROOT=str(self.root/'sidecars'))
        kwargs=dict(config=self.config,trade_date=self.date,stage_id=self.stage,receipt=self.receipt)
        with patch.dict(os.environ,env),patch('infrastructure.report_evidence_sidecar.subprocess.Popen',return_value=SimpleNamespace(pid=12345)):
            first=on_stage_completed(**kwargs)
            path=self.root/'sidecars/jobs'/(first['job_id']+'.receipt.json')
            def finish_during_probe(active):
                value=json.loads(path.read_text());value['status']='COMPLETED';path.write_text(json.dumps(value));return False
            with patch('infrastructure.report_evidence_sidecar._running_worker',side_effect=finish_during_probe):
                duplicate=on_stage_completed(**kwargs)
            self.assertEqual(duplicate['status'],'REUSED')
            self.assertEqual(json.loads(path.read_text())['status'],'COMPLETED')

    async def test_unknown_ps_is_busy_and_does_not_overwrite_worker_terminal(self):
        import subprocess,threading,time
        from infrastructure import report_evidence_sidecar as module
        from infrastructure.interprocess_lock import owned_interprocess_lock
        env=dict(V4_STAGE_REPORT_EVIDENCE_ENABLED='1',V4_RESEARCH_DATA_ROOT=str(self.owner.root),V4_REPORT_EVIDENCE_SIDECAR_ROOT=str(self.root/'sidecars'))
        kwargs=dict(config=self.config,trade_date=self.date,stage_id=self.stage,receipt=self.receipt)
        with patch.dict(os.environ,env),patch.object(module.subprocess,'Popen',return_value=SimpleNamespace(pid=12345)):
            first=module.on_stage_completed(**kwargs);jobs=self.root/'sidecars/jobs';entered=threading.Event();finish=threading.Event();errors=[]
            def worker():
                try:
                    with owned_interprocess_lock(jobs/'consumer.lock',timeout_seconds=1,timeout_message='busy'):
                        io=module._job_io(self.root/'sidecars');module._write_job_receipt(io,first['job_id'],'RUNNING',worker_pid=12345);entered.set();finish.wait(2);module._write_job_receipt(io,first['job_id'],'COMPLETED')
                except Exception as error:errors.append(error);entered.set()
            thread=threading.Thread(target=worker);thread.start();self.assertTrue(entered.wait(2))
            try:
                with patch.object(module.subprocess,'check_output',side_effect=subprocess.TimeoutExpired('ps',2)):
                    t=time.perf_counter();result=module.on_stage_completed(**kwargs);elapsed=time.perf_counter()-t
                self.assertEqual(result['status'],'BUSY');self.assertEqual(result['job_status'],'LIVENESS_UNKNOWN');self.assertLess(elapsed,.5)
            finally:finish.set();thread.join(2)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
            path=jobs/(first['job_id']+'.receipt.json');before=path.read_bytes();self.assertEqual(json.loads(before)['status'],'COMPLETED')
            self.assertEqual(module.on_stage_completed(**kwargs)['status'],'REUSED');self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.path.read_bytes(),self.before)

    async def test_orphan_check_uses_same_consumer_lock_without_waiting(self):
        import threading,time
        from infrastructure import report_evidence_sidecar as module
        from infrastructure.interprocess_lock import owned_interprocess_lock
        env=dict(V4_STAGE_REPORT_EVIDENCE_ENABLED='1',V4_RESEARCH_DATA_ROOT=str(self.owner.root),V4_REPORT_EVIDENCE_SIDECAR_ROOT=str(self.root/'sidecars'))
        kwargs=dict(config=self.config,trade_date=self.date,stage_id=self.stage,receipt=self.receipt)
        with patch.dict(os.environ,env),patch.object(module.subprocess,'Popen',return_value=SimpleNamespace(pid=12345)):
            first=module.on_stage_completed(**kwargs);jobs=self.root/'sidecars/jobs';entered=threading.Event();finish=threading.Event();errors=[]
            def worker():
                try:
                    with owned_interprocess_lock(jobs/'consumer.lock',timeout_seconds=1,timeout_message='busy'):
                        io=module._job_io(self.root/'sidecars');module._write_job_receipt(io,first['job_id'],'RUNNING',worker_pid=12345);entered.set();finish.wait(2);module._write_job_receipt(io,first['job_id'],'COMPLETED')
                except Exception as error:errors.append(error);entered.set()
            thread=threading.Thread(target=worker);thread.start();self.assertTrue(entered.wait(2))
            try:
                with patch.object(module,'_running_worker',return_value=False):
                    t=time.perf_counter();result=module.on_stage_completed(**kwargs);elapsed=time.perf_counter()-t
                self.assertEqual(result['status'],'BUSY');self.assertEqual(result['reason'],'SIDECAR_CONSUMER_BUSY');self.assertLess(elapsed,.5)
            finally:finish.set();thread.join(2)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
            self.assertEqual(json.loads((jobs/(first['job_id']+'.receipt.json')).read_text())['status'],'COMPLETED')
            self.assertEqual(module.on_stage_completed(**kwargs)['status'],'REUSED')
        self.assertEqual(self.path.read_bytes(),self.before)

    async def test_confirmed_dead_fails_once_and_terminal_states_are_immutable(self):
        import subprocess
        from infrastructure import report_evidence_sidecar as module
        env=dict(V4_STAGE_REPORT_EVIDENCE_ENABLED='1',V4_RESEARCH_DATA_ROOT=str(self.owner.root),V4_REPORT_EVIDENCE_SIDECAR_ROOT=str(self.root/'sidecars'))
        kwargs=dict(config=self.config,trade_date=self.date,stage_id=self.stage,receipt=self.receipt)
        with patch.dict(os.environ,env),patch.object(module.subprocess,'Popen',return_value=SimpleNamespace(pid=12345)):
            first=module.on_stage_completed(**kwargs)
            with patch.object(module.subprocess,'check_output',side_effect=subprocess.CalledProcessError(1,'ps')),patch.object(module.os,'kill',side_effect=ProcessLookupError()):
                result=module.on_stage_completed(**kwargs)
            self.assertEqual(result['status'],'EVIDENCE_GAP');self.assertEqual(result['reason'],'WORKER_EXITED_WITHOUT_COMPLETION')
            path=self.root/'sidecars/jobs'/(first['job_id']+'.receipt.json');before=path.read_bytes()
            with patch.object(module,'_materialize_worker',side_effect=AssertionError('must not restart terminal job')):
                self.assertEqual(module.consume_sidecar_job(first['job_id'])['status'],'FAILED')
            self.assertEqual(path.read_bytes(),before);self.assertEqual(module.on_stage_completed(**kwargs)['reason'],'JOB_PREVIOUSLY_FAILED')
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_pid_probe_distinguishes_unknown_from_observed_dead(self):
        import subprocess
        from infrastructure import report_evidence_sidecar as module
        active=dict(pid=12345,job_id='a'*64)
        with patch.object(module.subprocess,'check_output',side_effect=subprocess.TimeoutExpired('ps',2)):
            self.assertIsNone(module._running_worker(active))
        with patch.object(module.subprocess,'check_output',side_effect=OSError('probe unavailable')):
            self.assertIsNone(module._running_worker(active))
        with patch.object(module.subprocess,'check_output',side_effect=subprocess.CalledProcessError(1,'ps')),patch.object(module.os,'kill',side_effect=ProcessLookupError()):
            self.assertIs(module._running_worker(active),False)
        with patch.object(module.subprocess,'check_output',side_effect=subprocess.CalledProcessError(1,'ps')),patch.object(module.os,'kill',return_value=None):
            self.assertIsNone(module._running_worker(active))
        with patch.object(module.subprocess,'check_output',return_value='python -B -m ops.run_report_evidence_sidecar_job --job-id '+'a'*64):
            self.assertIs(module._running_worker(active),True)

    async def test_failed_job_is_separate_and_duplicate_does_not_retry(self):
        from infrastructure.report_evidence_sidecar import on_stage_completed,consume_sidecar_job
        env=dict(V4_STAGE_REPORT_EVIDENCE_ENABLED='1',V4_RESEARCH_DATA_ROOT=str(self.owner.root),V4_REPORT_EVIDENCE_SIDECAR_ROOT=str(self.root/'sidecars'))
        kwargs=dict(config=self.config,trade_date=self.date,stage_id=self.stage,receipt=self.receipt)
        with patch.dict(os.environ,env),patch('infrastructure.report_evidence_sidecar.subprocess.Popen',return_value=SimpleNamespace(pid=12345)) as spawn:
            first=on_stage_completed(**kwargs)
            with patch('infrastructure.report_evidence_sidecar._materialize_worker',side_effect=ValueError('QUERY_FAILED')):
                done=consume_sidecar_job(first['job_id']);self.assertEqual(done['status'],'FAILED');self.assertEqual(done['reason'],'QUERY_FAILED')
            repeated=on_stage_completed(**kwargs);self.assertEqual(repeated['status'],'EVIDENCE_GAP');self.assertEqual(repeated['reason'],'JOB_PREVIOUSLY_FAILED');self.assertEqual(spawn.call_count,1)
        self.assertEqual(self.path.read_bytes(),self.before)

if __name__=='__main__':unittest.main()
