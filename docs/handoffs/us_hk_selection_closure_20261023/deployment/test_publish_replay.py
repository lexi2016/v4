"""Publication boundary tests with the actual engine/types/store in fake state."""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import prepare_release as prep
import publish_replay as pub

WT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(WT),str(WT/'upstreams'),str(WT/'upstreams/v3_shared_data')]
from v4.manager_workbench import contracts as c,engines,service,us_mapping_replay as replay
from v4.manager_workbench.store import WorkbenchStore
from v4.manager_workbench.inputs.validation import batch as seal_batch

SCRATCH=WT/'.superpowers/sdd/2026-10-23-us-hk-selection-closure/scratch/deployment'
LIVE_PATHS=[Path('/Users/lexi/Library/LaunchAgents')/(name+'.plist') for name in ('com.lexi.v35.api-only','com.lexi.v35.scheduler')]
LIVE_PATHS += [Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2')/name for name in ('panel_latest.json','history_resolution_latest.json')]


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='rehearsal-publication-',dir=SCRATCH)
        self.addCleanup(temp.cleanup);self.root=Path(temp.name).resolve()
        self.live=self.root/'live';self.state=self.live/'manager_workbench';self.state.mkdir(parents=True)
        self.evidence=self.root/'evidence';self.evidence.mkdir()
        source=self.root/'sourcecode';source.mkdir()
        self.protected_input=self.state/'input_snapshots';self.protected_input.mkdir()
        context=c.RunContext(target_date='20261022',phase=c.Phase.NEXT_DAY,cutoff=pub.EXECUTION_CUTOFF,
            trigger='SCHEDULED',source_sessions={'us':'20261021','hk_price':'20261021'},rules_version='POSITIVE_OPERATING_RESEARCH_V1',
            scope_refs={'run_id':pub.SOURCE_RUN,'mwb_run_id':pub.SOURCE_RUN,'source_cutoff':pub.SOURCE_CUTOFF,'requested_lanes':['US_MAPPING']})
        batch=seal_batch(context,c.Lane.US_MAPPING,[],[],'explicit test fixture',
            c.Coverage(scope_count=0,observed_count=0,assessed_count=0,unassessed_count=0),gaps=['FIXTURE_NO_PIT_PROOF'])
        body=dict(derivative=True,authority='ORIGINAL_OWNERS_ONLY',context=context.model_dump(mode='json'),batches=[batch.model_dump(mode='json')])
        input_raw=c.canonical(body);input_sha=prep.digest(input_raw)
        self.input_path=self.protected_input/(input_sha+'.json');self.input_path.write_bytes(input_raw)
        self.snapshot_path=self.state/f'snapshots/{pub.SOURCE_RUN}.json';self.snapshot_path.parent.mkdir()
        original=dict(run_id=pub.SOURCE_RUN,product_sha256='f'*64,changes={'input_snapshot_sha256':input_sha},lanes=[])
        self.snapshot_path.write_bytes(c.canonical(original))
        catalog_path=self.state/f'catalog/20261022/NEXT_DAY/{pub.SOURCE_RUN}.json';catalog_path.parent.mkdir(parents=True)
        catalog=dict(run_id=pub.SOURCE_RUN,input_sha256='e'*64,product_sha256='f'*64)
        catalog_path.write_bytes(c.canonical(catalog))
        self.old_day_pointer=self.state/'pointers/20261022/NEXT_DAY.json';self.old_day_pointer.parent.mkdir(parents=True)
        self.old_day_pointer.write_bytes(c.canonical(catalog))
        row=dict(run_id=pub.SOURCE_RUN,target_date='20261022',phase='NEXT_DAY',input_sha256='e'*64,product_sha256='f'*64,
            input_snapshot_sha256=input_sha,us_batch_input_sha256=batch.input_sha256,pit_evidence_complete=False,
            exact_saved_input_replayable=True,classification='RETROSPECTIVE_ONLY',missing_evidence=['FIXTURE_NO_PIT_PROOF'],
            effective_proof_cutoff='2026-10-21T20:15:04+00:00',
            catalog=dict(path=str(catalog_path),sha256=prep.sha(catalog_path)),
            snapshot=dict(path=str(self.snapshot_path),sha256=prep.sha(self.snapshot_path)))
        days=[(datetime(2026,7,1)+timedelta(days=i)).strftime('%Y%m%d') for i in range(60)]
        inventory=dict(schema='v4.us_hk.replay_inventory.v1',outcome_free=True,state_root=str(self.state),
            calendar={'sessions':days},split={'eligible_dates':[],'sealed_dates':[]},runs=[row],
            inputs={input_sha:dict(path=str(self.input_path),sha256=input_sha,batches=[dict(lane='US_MAPPING',input_sha256=batch.input_sha256)])})
        inventory_path=self.root/'inventory.json';inventory_path.write_bytes(c.canonical(inventory))
        self.scope=dict(schema='v4.us_hk.replay_publication_scope.v1',state='READY',mode='REHEARSAL',
            rehearsal_root=str(self.root),source_root=str(source),live_state_root=str(self.live),evidence_root=str(self.evidence),
            stage_root=str(self.evidence/'stage'),target_date='20261022',phase='RETROSPECTIVE',trigger='MANUAL',
            source_run_id=pub.SOURCE_RUN,source_cutoff=pub.SOURCE_CUTOFF,source_execution_cutoff=pub.EXECUTION_CUTOFF,
            source_input=dict(path=str(self.input_path),sha256=input_sha),source_snapshot=dict(path=str(self.snapshot_path),sha256=prep.sha(self.snapshot_path)),
            source_batch_sha256=batch.input_sha256,inventory=dict(path=str(inventory_path),sha256=prep.sha(inventory_path)),source_files={},
            data_pointer_changes=[],result_pointer_relative='pointers/20261022/RETROSPECTIVE.json',
            safety=dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False))
        self.scope_path=self.root/'scope.json';self.prepared=self.evidence/'PREPARED.json'
        self.published=self.evidence/'PUBLISHED.json';self.rolled_back=self.evidence/'ROLLBACK.json'
        self.backend=SimpleNamespace(c=c,engines=engines,service=service,Store=WorkbenchStore,replay=replay)
        self.original={p: p.read_bytes() for p in (self.input_path,self.snapshot_path,self.old_day_pointer)}

    def scope_sha(self):
        self.scope_path.write_bytes(prep.json_bytes(self.scope));return prep.sha(self.scope_path)

    def prepare(self):
        return pub.prepare_replay(self.scope_path,self.scope_sha(),self.prepared,backend=self.backend,
            clock=lambda:datetime(2026,10,24,tzinfo=timezone.utc),new_id='b'*32)

    def publish(self,**kwargs):
        return pub.publish(self.prepared,prep.sha(self.prepared),self.published,backend=self.backend,**kwargs)

    def assert_originals(self):
        for path,raw in self.original.items():self.assertEqual(path.read_bytes(),raw)

    def test_real_engine_store_retrospective_and_exact_rollback(self):
        receipt=self.prepare();self.assert_originals()
        self.assertEqual(receipt['pipeline']['engine_calls'],1)
        self.assertEqual(receipt['pipeline']['model_calls'],0)
        published=self.publish();self.assertEqual(published['state'],'PUBLISHED_RETROSPECTIVE_MANUAL')
        snap=WorkbenchStore(self.live).read_plan(receipt['new_run_id'])
        self.assertEqual(snap.context.phase,c.Phase.RETROSPECTIVE);self.assertEqual(snap.context.trigger,'MANUAL')
        self.assertEqual(snap.context.scope_refs['source_cutoff'],pub.SOURCE_CUTOFF)
        self.assertEqual(snap.context.scope_refs['source_execution_cutoff'],pub.EXECUTION_CUTOFF)
        self.assertEqual(snap.lanes[0].selection.cutoff,pub.EXECUTION_CUTOFF)
        out=pub.rollback(self.prepared,prep.sha(self.prepared),dict(path=str(self.published),sha256=prep.sha(self.published)),self.rolled_back,backend=self.backend)
        self.assertEqual(out['state'],'RETROSPECTIVE_POINTER_RESTORED_HISTORY_RETAINED')
        self.assertFalse((self.state/receipt['pointer_relative']).exists())
        self.assertTrue((self.state/f"snapshots/{receipt['new_run_id']}.json").exists());self.assert_originals()

    def test_existing_retrospective_pointer_restored_exactly(self):
        pointer=self.state/'pointers/20261022/RETROSPECTIVE.json';old=c.canonical(dict(run_id='earlier',product_sha256='c'*64,generated_at=pub.EXECUTION_CUTOFF))
        pointer.write_bytes(old);self.prepare();self.publish()
        pub.rollback(self.prepared,prep.sha(self.prepared),dict(path=str(self.published),sha256=prep.sha(self.published)),self.rolled_back,backend=self.backend)
        self.assertEqual(pointer.read_bytes(),old);self.assert_originals()

    def test_original_quote_cutoff_cannot_be_extended(self):
        self.scope['source_cutoff']='2026-10-24T00:00:00Z'
        with self.assertRaisesRegex(prep.Stop,'ORIGINAL_CUTOFF_MISMATCH'):self.prepare()
        self.assertFalse(Path(self.scope['stage_root']).exists());self.assert_originals()

    def test_other_source_run_rejected(self):
        self.scope['source_run_id']='different'
        with self.assertRaisesRegex(prep.Stop,'PUBLICATION_BOUNDARY_INVALID'):self.prepare()

    def test_authority_pointer_grant_rejected(self):
        self.scope['data_pointer_changes']=['panel_latest.json']
        with self.assertRaisesRegex(prep.Stop,'PUBLICATION_BOUNDARY_INVALID'):self.prepare()

    def test_source_input_drift_rejected(self):
        self.input_path.write_bytes(b'changed original')
        with self.assertRaisesRegex(prep.Stop,'FILE_SHA_DRIFT'):self.prepare()
        self.assertFalse(Path(self.scope['stage_root']).exists())

    def test_preparation_collision_does_not_rerun(self):
        self.prepare()
        with patch.object(replay,'actual_engine',side_effect=AssertionError('must not rerun')):
            with self.assertRaisesRegex(prep.Stop,'REPLAY_PREPARATION_COLLISION'):self.prepare()

    def test_current_pointer_drift_before_publication_blocks_all_result_writes(self):
        receipt=self.prepare();pointer=self.state/receipt['pointer_relative'];pointer.write_bytes(c.canonical({'run_id':'new-owner'}))
        with self.assertRaisesRegex(prep.Stop,'POINTER_CAS_DRIFT_NO_PUBLICATION'):self.publish()
        self.assertFalse((self.state/f"snapshots/{receipt['new_run_id']}.json").exists());self.assert_originals()

    def test_pointer_race_inside_publication_lock_blocks_pointer_write(self):
        receipt=self.prepare();pointer=self.state/receipt['pointer_relative'];other=c.canonical({'run_id':'other-owner'})
        def race():pointer.write_bytes(other)
        with self.assertRaisesRegex(prep.Stop,'POINTER_CAS_DRIFT_INSIDE_STORE_LOCK'):self.publish(before_commit=race)
        self.assertEqual(pointer.read_bytes(),other);self.assert_originals()
        self.assertEqual(json.loads(self.published.read_bytes())['state'],'PARTIAL_REQUIRES_INSPECTION')

    def test_partial_new_run_is_not_overwritten_or_retried(self):
        receipt=self.prepare();path=self.state/f"attempts/{receipt['new_run_id']}.json";path.parent.mkdir();path.write_bytes(b'partial existing')
        with self.assertRaisesRegex(prep.Stop,'NEW_RUN_COLLISION_OR_PARTIAL_PUBLICATION_INSPECT'):self.publish()
        self.assertEqual(path.read_bytes(),b'partial existing');self.assert_originals()

    def test_prepared_product_tamper_rejected(self):
        receipt=self.prepare();path=Path(self.scope['stage_root'])/'manager_workbench'/receipt['files'][0]['relative'];path.write_bytes(b'tamper')
        with self.assertRaisesRegex(prep.Stop,'PREPARED_PRODUCT_FILE_DRIFT'):self.publish()
        self.assert_originals()

    def test_rollback_refuses_third_party_pointer(self):
        receipt=self.prepare();self.publish();pointer=self.state/receipt['pointer_relative'];pointer.write_bytes(b'third party')
        with self.assertRaisesRegex(prep.Stop,'ROLLBACK_POINTER_CAS_DRIFT'):
            pub.rollback(self.prepared,prep.sha(self.prepared),dict(path=str(self.published),sha256=prep.sha(self.published)),self.rolled_back,backend=self.backend)
        self.assertEqual(pointer.read_bytes(),b'third party');self.assert_originals()

    def test_engine_cannot_call_network_or_subprocess(self):
        for action in (lambda:socket.create_connection(('127.0.0.1',1)),lambda:subprocess.Popen(['/bin/echo','forbidden'])):
            with pub.no_external_execution():
                with self.assertRaisesRegex(prep.Stop,'NETWORK_CAPTURE_OR_PROCESS_EXECUTION_FORBIDDEN'):action()

    def test_publish_requires_separate_controller_pass_in_release_mode(self):
        self.prepare();self.scope['mode']='RELEASE';self.scope_sha()
        receipt=json.loads(self.prepared.read_bytes());receipt['scope_sha256']=prep.sha(self.scope_path)
        self.prepared.write_bytes(prep.json_bytes(receipt))
        with self.assertRaises(prep.Stop):self.publish()
        self.assert_originals()

    def test_prepared_receipt_cannot_expand_file_allowlist(self):
        self.prepare();receipt=json.loads(self.prepared.read_bytes())
        receipt['files'].append(dict(relative=f'snapshots/{pub.SOURCE_RUN}.json',sha256=prep.sha(self.snapshot_path)))
        self.prepared.write_bytes(prep.json_bytes(receipt))
        with self.assertRaisesRegex(prep.Stop,'PUBLICATION_FILE_SCOPE_NOT_DERIVED_FROM_PRODUCT'):self.publish()
        self.assert_originals()

    def test_prepared_receipt_cannot_change_pointer_phase(self):
        self.prepare();receipt=json.loads(self.prepared.read_bytes());receipt['pointer_relative']='pointers/20261022/NEXT_DAY.json'
        self.prepared.write_bytes(prep.json_bytes(receipt))
        with self.assertRaisesRegex(prep.Stop,'PUBLICATION_FILE_SCOPE_NOT_DERIVED_FROM_PRODUCT'):self.publish()
        self.assert_originals()

    def test_source_snapshot_reference_must_match_frozen_inventory(self):
        copy=self.root/'alternate-snapshot.json';copy.write_bytes(self.snapshot_path.read_bytes())
        self.scope['source_snapshot']['path']=str(copy)
        with self.assertRaisesRegex(prep.Stop,'FROZEN_SOURCE_REFERENCE_MISMATCH'):self.prepare()
        self.assert_originals()

    def test_staged_job_must_be_terminal_for_same_run(self):
        receipt=self.prepare();path=Path(self.scope['stage_root'])/f"manager_workbench/attempts/{receipt['new_run_id']}.json"
        value=json.loads(path.read_bytes());value['state']='RUNNING';path.write_bytes(c.canonical(value))
        for row in receipt['files']:
            if row['relative'].startswith('attempts/'):row['sha256']=prep.sha(path)
        self.prepared.write_bytes(prep.json_bytes(receipt))
        with self.assertRaisesRegex(prep.Stop,'PUBLICATION_TERMINAL_JOB_MISMATCH'):self.publish()
        self.assert_originals()

    def test_no_service_or_jobcoordinator_is_constructed(self):
        with patch.object(service,'ManagerService',side_effect=AssertionError('live service forbidden')), \
             patch('v4.manager_workbench.jobs.JobCoordinator',side_effect=AssertionError('coordinator forbidden')):
            self.prepare();self.publish()
        self.assert_originals()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--receipt',required=True);parser.add_argument('--cases',nargs='+')
    args=parser.parse_args();SCRATCH.mkdir(parents=True,exist_ok=True)
    output=Path(args.receipt).resolve();prep.require(output.is_relative_to(SCRATCH.resolve()),'TEST_RECEIPT_OUTSIDE_SCRATCH')
    before={str(p):prep.sha(p) for p in LIVE_PATHS}
    suite=unittest.TestSuite(PublicationTests(name) for name in args.cases) if args.cases else unittest.defaultTestLoader.loadTestsFromTestCase(PublicationTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    after={str(p):prep.sha(p) for p in LIVE_PATHS}
    value=dict(schema='v4.us_hk.publication_helper_tests.v1',tests_run=result.testsRun,passed=result.wasSuccessful(),
        failures=len(result.failures),errors=len(result.errors),cases=args.cases or 'ALL',live_unchanged=before==after,
        live_before=before,live_after=after,python=dict(executable=sys.executable,version=sys.version),
        source_dependency_sha256={str(Path(module.__file__)):prep.sha(module.__file__) for module in (c,engines,service,replay,sys.modules[WorkbenchStore.__module__])},
        helpers={p.name:prep.sha(p) for p in [Path(pub.__file__),Path(__file__)]},actual_live_operations=0,fixture_inputs_only=True)
    prep.write_new(output,prep.json_bytes(value));print(json.dumps(dict(receipt=str(output),sha256=prep.sha(output),passed=value['passed'],tests=result.testsRun)))
    raise SystemExit(0 if result.wasSuccessful() and before==after else 1)


if __name__=='__main__':main()
