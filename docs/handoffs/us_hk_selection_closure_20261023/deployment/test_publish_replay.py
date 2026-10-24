"""Publication boundary tests with the actual engine/types/store in fake state."""
from __future__ import annotations
import argparse
import ast
from contextlib import contextmanager
from copy import deepcopy
import inspect
import plistlib
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

    def dated23_fixture(self, *, actual_session='20261022', actual_cutoff='2026-10-22T20:15:02Z'):
        # Independent dated fixture:23 uses US22, source22 fixture remains byte-protected.
        run='3'*32;execution='2026-10-23T21:01:00.921047+08:00'
        ctx=c.RunContext(target_date='20261023',phase=c.Phase.NEXT_DAY,cutoff=execution,
            trigger='SCHEDULED',source_sessions={'us':actual_session,'hk_price':'20261022'},
            rules_version='POSITIVE_OPERATING_RESEARCH_V1',scope_refs={'run_id':run,'mwb_run_id':run,
            'source_cutoff':actual_cutoff,'us_session_date':actual_session,'requested_lanes':['US_MAPPING']})
        batch=seal_batch(ctx,c.Lane.US_MAPPING,[],[],'dated23 fixture',
            c.Coverage(scope_count=0,observed_count=0,assessed_count=0,unassessed_count=0),gaps=['FIXTURE_NO_PIT_PROOF'])
        body=dict(derivative=True,authority='ORIGINAL_OWNERS_ONLY',context=ctx.model_dump(mode='json'),batches=[batch.model_dump(mode='json')])
        raw=c.canonical(body);ish=prep.digest(raw);inp=self.protected_input/(ish+'.json');inp.write_bytes(raw)
        snap=self.state/f'snapshots/{run}.json';snap.write_bytes(c.canonical(dict(run_id=run,product_sha256='d'*64,changes={'input_snapshot_sha256':ish},lanes=[])))
        cat=self.state/f'catalog/20261023/NEXT_DAY/{run}.json';cat.parent.mkdir(parents=True)
        cat.write_bytes(c.canonical(dict(run_id=run,input_sha256='e'*64,product_sha256='d'*64,generated_at='2026-10-23T21:02:08.380824+08:00')))
        inventory=json.loads(Path(self.scope['inventory']['path']).read_bytes())
        row=dict(run_id=run,target_date='20261023',phase='NEXT_DAY',input_sha256='e'*64,product_sha256='d'*64,
            input_snapshot_sha256=ish,us_batch_input_sha256=batch.input_sha256,pit_evidence_complete=False,
            exact_saved_input_replayable=True,classification='RETROSPECTIVE_ONLY',missing_evidence=['FIXTURE_NO_PIT_PROOF'],
            generated_at='2026-10-23T21:02:08.380824+08:00',effective_proof_cutoff=replay.temporal_cutoff(ctx.model_dump(mode='json')),
            input_context={'market':'HK_CONNECT','target_date':'20261023','phase':'NEXT_DAY','cutoff':execution,
            'source_cutoff':'2026-10-22T20:15:02Z','source_sessions':{'us':'20261022','hk_price':'20261022'},'us_session_date':'20261022'},
            catalog=dict(path=str(cat),sha256=prep.sha(cat)),snapshot=dict(path=str(snap),sha256=prep.sha(snap)))
        inventory['runs'].append(row);inventory['inputs'][ish]=dict(path=str(inp),sha256=ish,batches=[dict(lane='US_MAPPING',input_sha256=batch.input_sha256)])
        ip=Path(self.scope['inventory']['path']);ip.write_bytes(c.canonical(inventory))
        self.scope.update(schema='v4.us_hk.replay_publication_scope.v2',source_run_id=run,target_date='20261023',
            source_input=dict(path=str(inp),sha256=ish),source_snapshot=dict(path=str(snap),sha256=prep.sha(snap)),
            source_batch_sha256=batch.input_sha256,source_cutoff='2026-10-22T20:15:02Z',source_execution_cutoff=execution,
            source_us_session='20261022',source_row_sha256=prep.digest(pub.canonical(row)),
            inventory=dict(path=str(ip),sha256=prep.sha(ip)),result_pointer_relative='pointers/20261023/RETROSPECTIVE.json')
        self.original.update({p:p.read_bytes() for p in (inp,snap,cat)})
        return row

    def test_dated23_own_input_six_files_latest_metadata_and_rollback(self):
        self.dated23_fixture();receipt=self.prepare();self.assert_originals()
        self.assertEqual(receipt['source_run_id'],'3'*32)
        self.assertEqual(receipt['pointer_relative'],'pointers/20261023/RETROSPECTIVE.json')
        self.assertIn('catalog/20261023/RETROSPECTIVE/'+receipt['new_run_id']+'.json',{r['relative'] for r in receipt['files']})
        before={p.relative_to(self.state).as_posix():p.read_bytes() for p in self.state.rglob('*.json')}
        self.publish();store=WorkbenchStore(self.live);snap=store.read_plan(receipt['new_run_id'])
        self.assertEqual(snap.context.target_date,'20261023');self.assertEqual(snap.context.source_sessions['us'],'20261022')
        self.assertEqual(snap.context.scope_refs['source_run_id'],'3'*32)
        self.assertEqual(snap.context.scope_refs['source_cutoff'],'2026-10-22T20:15:02Z')
        self.assertEqual(snap.lanes[0].selection.cutoff,'2026-10-23T21:01:00.921047+08:00')
        metadata,_=store.list_plan_metadata('20261023');self.assertEqual(metadata[0]['run_id'],receipt['new_run_id'])
        after={p.relative_to(self.state).as_posix() for p in self.state.rglob('*.json')}
        self.assertEqual(after-set(before),{r['relative'] for r in receipt['files']}|{'pointers/20261023/RETROSPECTIVE.json'})
        for rel,raw in before.items():self.assertEqual((self.state/rel).read_bytes(),raw)
        pub.rollback(self.prepared,prep.sha(self.prepared),dict(path=str(self.published),sha256=prep.sha(self.published)),self.rolled_back,backend=self.backend)
        self.assertFalse((self.state/'pointers/20261023/RETROSPECTIVE.json').exists());self.assert_originals()

    def test_dated23_scope_crosswires_rejected_before_engine(self):
        self.dated23_fixture();original=deepcopy(self.scope)
        mutations={'date':('target_date','20261022'),'run':('source_run_id',pub.SOURCE_RUN),
            'session':('source_us_session','20261021'),'batch':('source_batch_sha256',pub.SOURCE_BATCH),
            'cutoff':('source_cutoff',pub.SOURCE_CUTOFF),'execution':('source_execution_cutoff',pub.EXECUTION_CUTOFF),
            'row':('source_row_sha256','0'*64),'input':('source_input',dict(path=str(self.input_path),sha256=prep.sha(self.input_path)))}
        for name,(key,value) in mutations.items():
            self.scope=deepcopy(original);self.scope[key]=value
            with self.subTest(mutation=name),patch.object(replay,'actual_engine',side_effect=AssertionError('engine before datebinding')):
                with self.assertRaises(prep.Stop):self.prepare()
            self.assertFalse(Path(self.scope['stage_root']).exists());self.assert_originals()

    def test_dated23_actual_input_session_cannot_be_row_annotation(self):
        self.dated23_fixture(actual_session='20261021')
        with patch.object(replay,'actual_engine',side_effect=AssertionError('engine before source session check')):
            with self.assertRaisesRegex(prep.Stop,'FROZEN_SOURCE_SESSION_MISMATCH'):self.prepare()
        self.assertFalse(Path(self.scope['stage_root']).exists());self.assert_originals()

    def test_dated23_original_source_cutoff_cannot_be_replaced(self):
        self.dated23_fixture(actual_cutoff='2026-10-23T20:15:02Z')
        with patch.object(replay,'actual_engine',side_effect=AssertionError('engine before cutoff check')):
            with self.assertRaisesRegex(prep.Stop,'FROZEN_SOURCE_CONTEXT_MISMATCH'):self.prepare()
        self.assertFalse(Path(self.scope['stage_root']).exists());self.assert_originals()

    def test_dated23_pointer_race_preserves_new_owner(self):
        self.dated23_fixture();receipt=self.prepare();pointer=self.state/receipt['pointer_relative'];other=c.canonical({'run_id':'other23owner'})
        pointer.parent.mkdir(parents=True,exist_ok=True)
        with self.assertRaisesRegex(prep.Stop,'POINTER_CAS_DRIFT_INSIDE_STORE_LOCK'):
            self.publish(before_commit=lambda:pointer.write_bytes(other))
        self.assertEqual(pointer.read_bytes(),other);self.assert_originals()

    def test_dated23_prepared_row_pin_tamper_rejected(self):
        self.dated23_fixture();self.prepare();value=json.loads(self.prepared.read_bytes())
        value['source_row_sha256']='0'*64;self.prepared.write_bytes(prep.json_bytes(value))
        with self.assertRaisesRegex(prep.Stop,'PUBLICATION_PREPARED_DRIFT'):self.publish()
        self.assert_originals()

    def test_dated23_configured_double_root_uses_own_date_only(self):
        self.dated23_fixture();receipt,root,continuation,runner=self.configured_root_fixture()
        with patch.object(pub,'load_backend',return_value=self.backend),patch.object(pub.subprocess,'run',side_effect=runner):
            pub.publish(self.prepared,prep.sha(self.prepared),self.published,continuation=continuation)
            self.assertTrue((root/'pointers/20261023/RETROSPECTIVE.json').exists())
            self.assertFalse((self.state/'pointers/20261023/RETROSPECTIVE.json').exists())
            self.assertFalse((root/'pointers/20261022/RETROSPECTIVE.json').exists())
            pub.rollback(self.prepared,prep.sha(self.prepared),dict(path=str(self.published),sha256=prep.sha(self.published)),self.rolled_back,continuation=continuation)
        self.assertFalse((root/'pointers/20261023/RETROSPECTIVE.json').exists());self.assert_originals()

    def test_old_prepared_helper_hash_is_not_accepted_by_new_binary(self):
        self.prepare();value=json.loads(self.prepared.read_bytes());value['helper_sha256']='0'*64
        self.prepared.write_bytes(prep.json_bytes(value))
        with self.assertRaisesRegex(prep.Stop,'PUBLICATION_PREPARED_DRIFT'):self.publish()
        self.assert_originals()

    def configured_root_fixture(self, *, old_pointer=False):
        # The API config argument already ends with manager_workbench.
        self.scope['live_state_root']=str(self.state);root=self.state/'manager_workbench';root.mkdir()
        if old_pointer:
            self.old_deep_pointer=c.canonical({'run_id':'existing-deep-owner','product_sha256':'d'*64,'generated_at':pub.EXECUTION_CUTOFF})
            deep=root/self.scope['result_pointer_relative'];deep.parent.mkdir(parents=True);deep.write_bytes(self.old_deep_pointer)
            upper=self.state/self.scope['result_pointer_relative'];upper.write_bytes(c.canonical({'run_id':'upper-decoy'}))
            self.original[upper]=upper.read_bytes()
        receipt=self.prepare()
        source=Path(self.scope['source_root']);app=self.root/'active-api-app';app.mkdir()
        deployed={}
        for relative in ('v4/manager_workbench/store.py','v4/manager_workbench/contracts.py',
                         'v4/manager_workbench/engines/us_mapping.py','v4/manager_workbench/engines/strict_us_selection.py'):
            raw=(WT/relative).read_bytes() if relative.endswith('/store.py') else b'fake deployed source identity only\n'
            for base in (source,app):
                path=base/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            deployed[relative]=prep.digest(raw)
        self.config=self.root/'active-api-config.json';self.config.write_bytes(prep.json_bytes({'state_root':str(self.state)}))
        self.api_manifest=self.root/'api-manifest.json';self.api_manifest.write_bytes(b'{}\n')
        self.api_plist=self.root/'com.lexi.v35.api-only.plist'
        data={'WorkingDirectory':str(app),'EnvironmentVariables':{'V4_MANAGER_WORKBENCH_CONFIG_PATH':str(self.config)},
              'ProgramArguments':['/usr/bin/env','V4_MANAGER_WORKBENCH_CONFIG_PATH='+str(self.config),'fake-owner']}
        self.api_plist.write_bytes(plistlib.dumps(data))
        self.scope.update(mode='RELEASE',source_files=deployed,deployed_files=deployed,
            active_api={'plist':str(self.api_plist),'plist_sha256':prep.sha(self.api_plist),'app_root':str(app),
                'manifest':str(self.api_manifest),'manifest_sha256':prep.sha(self.api_manifest),
                'config':{'path':str(self.config),'sha256':prep.sha(self.config)}})
        self.addCleanup(patch.stopall)
        for name,value in [('WORKTREE',source),('LIVE_STATE',self.state),('API_PLIST',self.api_plist),
                           ('API_CONFIG',self.config),('API_CONFIG_SHA',prep.sha(self.config)),
                           ('SOURCE_INPUT',self.scope['source_input']['sha256']),('SOURCE_BATCH',self.scope['source_batch_sha256'])]:
            patch.object(pub,name,value).start()
        receipt['scope_sha256']=self.scope_sha();self.prepared.write_bytes(prep.json_bytes(receipt))
        cap=self.root/'publication-continuation.json'
        cap.write_bytes(prep.json_bytes({'schema':'v4.us_hk.execution_capsule.v1','verdict':'PASS',
            'authorized_actions':['publish_replay','rollback_replay'],'prepared_sha256':prep.sha(self.prepared),
            'scope_contract_sha256':prep.contract_sha(self.scope),
            'helper_sha256':{name:prep.sha(Path(__file__).with_name(name)) for name in ('prepare_release.py','activate_release.py','publish_replay.py')}}))
        continuation={'path':str(cap),'sha256':prep.sha(cap)}
        def runner(argv,**kwargs):
            if argv[:2]==['/bin/launchctl','print']:return SimpleNamespace(returncode=0,stdout='state = running\npid = 991\n')
            if argv[0]=='/usr/sbin/lsof':return SimpleNamespace(returncode=0,stdout='n'+str(app)+'\n')
            raise AssertionError('unexpected fake metadata command: '+repr(argv))
        return receipt,root,continuation,runner

    def test_configured_double_root_exact_six_files_pointer_and_rollback(self):
        receipt,root,continuation,runner=self.configured_root_fixture()
        self.assertEqual(pub.live_store_root(self.scope),root)
        before={p.relative_to(root).as_posix() for p in root.rglob('*.json')}
        with patch.object(pub,'load_backend',return_value=self.backend),patch.object(pub.subprocess,'run',side_effect=runner):
            result=pub.publish(self.prepared,prep.sha(self.prepared),self.published,continuation=continuation)
            self.assertEqual(result['state'],'PUBLISHED_RETROSPECTIVE_MANUAL')
            after={p.relative_to(root).as_posix() for p in root.rglob('*.json')}
            self.assertEqual(after-before,{row['relative'] for row in receipt['files']}|{receipt['pointer_relative']})
            self.assertFalse((self.state/receipt['pointer_relative']).exists())
            snap=WorkbenchStore(self.state).read_plan(receipt['new_run_id'])
            self.assertEqual(snap.run_id,receipt['new_run_id'])
            pub.rollback(self.prepared,prep.sha(self.prepared),{'path':str(self.published),'sha256':prep.sha(self.published)},
                self.rolled_back,continuation=continuation)
        self.assertFalse((root/receipt['pointer_relative']).exists())
        self.assertTrue((root/f"snapshots/{receipt['new_run_id']}.json").exists());self.assert_originals()

    def test_configured_prepare_cas_backup_and_rollback_use_deep_pointer(self):
        receipt,root,continuation,runner=self.configured_root_fixture(old_pointer=True)
        self.assertEqual(receipt['expected_old_pointer_sha256'],prep.digest(self.old_deep_pointer))
        self.assertEqual(Path(receipt['old_pointer_backup']).read_bytes(),self.old_deep_pointer)
        with patch.object(pub,'load_backend',return_value=self.backend),patch.object(pub.subprocess,'run',side_effect=runner):
            pub.publish(self.prepared,prep.sha(self.prepared),self.published,continuation=continuation)
            self.assert_originals()
            pub.rollback(self.prepared,prep.sha(self.prepared),{'path':str(self.published),'sha256':prep.sha(self.published)},
                self.rolled_back,continuation=continuation)
        self.assertEqual((root/receipt['pointer_relative']).read_bytes(),self.old_deep_pointer);self.assert_originals()

    def test_configured_root_refuses_upper_arbitrary_and_unpinned_config(self):
        receipt,root,continuation,runner=self.configured_root_fixture();original=deepcopy(self.scope)
        for mutation in ('upper','arbitrary','missing-config','path','hash'):
            self.scope=deepcopy(original)
            if mutation=='upper':self.scope['live_state_root']=str(self.live)
            elif mutation=='arbitrary':self.scope['live_state_root']=str(self.state/'another-owner')
            elif mutation=='missing-config':self.scope['active_api'].pop('config')
            elif mutation=='path':self.scope['active_api']['config']['path']=str(self.root/'other.json')
            else:self.scope['active_api']['config']['sha256']='0'*64
            with self.subTest(mutation=mutation),self.assertRaises(prep.Stop):pub.live_store_root(self.scope)
        self.assertFalse((root/f"snapshots/{receipt['new_run_id']}.json").exists());self.assert_originals()

    def test_configured_root_refuses_config_plist_and_store_contract_drift(self):
        receipt,root,continuation,runner=self.configured_root_fixture();config=self.config.read_bytes();binding=self.api_plist.read_bytes()
        self.config.write_bytes(config+b' ')
        with self.assertRaisesRegex(prep.Stop,'FILE_SHA_DRIFT'):pub.live_store_root(self.scope)
        self.config.write_bytes(config);data=plistlib.loads(binding)
        data['ProgramArguments'][1]='V4_MANAGER_WORKBENCH_CONFIG_PATH='+str(self.root/'wrong-config.json')
        self.api_plist.write_bytes(plistlib.dumps(data))
        with self.assertRaisesRegex(prep.Stop,'PUBLICATION_API_PLIST_DRIFT'):pub.live_store_root(self.scope)
        self.scope['active_api']['plist_sha256']=prep.sha(self.api_plist)
        with self.assertRaisesRegex(prep.Stop,'PUBLICATION_API_CONFIG_BINDING_DRIFT'):pub.live_store_root(self.scope)
        self.api_plist.write_bytes(binding);self.scope['active_api']['plist_sha256']=prep.sha(self.api_plist)
        deployed=Path(self.scope['active_api']['app_root'])/'v4/manager_workbench/store.py';raw=deployed.read_bytes();deployed.write_bytes(raw+b'\n')
        with self.assertRaisesRegex(prep.Stop,'PUBLICATION_STORE_SOURCE_DRIFT'):pub.live_store_root(self.scope)
        deployed.write_text('class WorkbenchStore:\n def __init__(self,state_root):\n  self.root=Path(state_root)\n')
        self.scope['deployed_files']['v4/manager_workbench/store.py']=prep.sha(deployed)
        self.scope['source_files']['v4/manager_workbench/store.py']=prep.sha(deployed)
        with self.assertRaisesRegex(prep.Stop,'STORE_ROOT_CONSTRUCTOR_UNRECOGNIZED'):pub.live_store_root(self.scope)
        self.assert_originals()

    def test_configured_root_publish_revalidates_config_inside_store_lock(self):
        receipt,root,continuation,runner=self.configured_root_fixture();original_lock=WorkbenchStore.lock
        @contextmanager
        def raced_lock(store,key):
            with original_lock(store,key):
                self.config.write_bytes(self.config.read_bytes()+b' ')
                yield
        with patch.object(pub,'load_backend',return_value=self.backend),patch.object(pub.subprocess,'run',side_effect=runner),patch.object(WorkbenchStore,'lock',raced_lock):
            with self.assertRaisesRegex(prep.Stop,'FILE_SHA_DRIFT'):
                pub.publish(self.prepared,prep.sha(self.prepared),self.published,continuation=continuation)
        self.assertFalse((root/f"snapshots/{receipt['new_run_id']}.json").exists())
        self.assertFalse((self.state/receipt['pointer_relative']).exists());self.assert_originals()

    def test_configured_root_rollback_revalidates_plist_inside_store_lock(self):
        receipt,root,continuation,runner=self.configured_root_fixture();original_lock=WorkbenchStore.lock
        with patch.object(pub,'load_backend',return_value=self.backend),patch.object(pub.subprocess,'run',side_effect=runner):
            pub.publish(self.prepared,prep.sha(self.prepared),self.published,continuation=continuation)
            pointer=root/receipt['pointer_relative'];raw=pointer.read_bytes()
            @contextmanager
            def raced_lock(store,key):
                with original_lock(store,key):
                    self.api_plist.write_bytes(self.api_plist.read_bytes()+b' ')
                    yield
            with patch.object(WorkbenchStore,'lock',raced_lock):
                with self.assertRaisesRegex(prep.Stop,'PUBLICATION_API_PLIST_DRIFT'):
                    pub.rollback(self.prepared,prep.sha(self.prepared),{'path':str(self.published),'sha256':prep.sha(self.published)},
                        self.rolled_back,continuation=continuation)
        self.assertEqual(pointer.read_bytes(),raw);self.assertFalse(self.rolled_back.exists());self.assert_originals()

    def test_configured_root_validation_never_constructs_store(self):
        receipt,root,continuation,runner=self.configured_root_fixture()
        with patch.object(WorkbenchStore,'__init__',side_effect=AssertionError('preflight Store construction forbidden')):
            self.assertEqual(pub.live_store_root(self.scope),root)
            loaded=pub.scope_load(self.scope_path,prep.sha(self.scope_path),'publish_replay',continuation)
            pub.active_api(loaded,runner=runner)
        self.assert_originals()

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
    output=Path(args.receipt).resolve();own=WT/'.superpowers/sdd/2026-10-23-us-hk-selection-closure/scratch/date23-visible-list/writer'
    prep.require(output.is_relative_to(SCRATCH.resolve()) or output.is_relative_to(own.resolve()),'TEST_RECEIPT_OUTSIDE_SCRATCH')
    before={str(p):prep.sha(p) for p in LIVE_PATHS}
    helper_dependencies_before={name:prep.sha(Path(__file__).with_name(name)) for name in ('prepare_release.py','activate_release.py')}
    root_contract_ast=prep.digest(ast.dump(ast.parse(inspect.getsource(pub.actual_store_root))).encode())
    loaded_root_code_sha256=prep.digest(pub.actual_store_root.__code__.co_code)
    suite=unittest.TestSuite(PublicationTests(name) for name in args.cases) if args.cases else unittest.defaultTestLoader.loadTestsFromTestCase(PublicationTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    after={str(p):prep.sha(p) for p in LIVE_PATHS}
    value=dict(schema='v4.us_hk.publication_helper_tests.v1',tests_run=result.testsRun,passed=result.wasSuccessful(),
        failures=len(result.failures),errors=len(result.errors),cases=args.cases or 'ALL',live_unchanged=before==after,
        live_before=before,live_after=after,python=dict(executable=sys.executable,version=sys.version),
        source_dependency_sha256={str(Path(module.__file__)):prep.sha(module.__file__) for module in (c,engines,service,replay,sys.modules[WorkbenchStore.__module__])},
        helpers={p.name:prep.sha(p) for p in [Path(pub.__file__),Path(__file__)]},
        runtime_helper_dependencies_before=helper_dependencies_before,
        runtime_helper_dependencies_after={name:prep.sha(Path(__file__).with_name(name)) for name in ('prepare_release.py','activate_release.py')},
        actual_store_root_AST_sha256=root_contract_ast,loaded_actual_store_root_code_sha256=loaded_root_code_sha256,
        actual_live_operations=0,fixture_inputs_only=True)
    prep.write_new(output,prep.json_bytes(value));print(json.dumps(dict(receipt=str(output),sha256=prep.sha(output),passed=value['passed'],tests=result.testsRun)))
    raise SystemExit(0 if result.wasSuccessful() and before==after else 1)


if __name__=='__main__':main()
