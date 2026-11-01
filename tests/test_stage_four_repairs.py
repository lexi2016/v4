"""Frozen offline regression: real inputs are read-only and never enter git.

STAGE_FOUR_BUNDLE points to an inventory-sealed, allowlisted candidate bundle.
Synthetic failures are named explicitly; no provider contacts OpenD/network.
"""
from __future__ import annotations
import copy, hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BUNDLE=Path(os.environ['STAGE_FOUR_BUNDLE'])
IDENTITIES=json.loads((BUNDLE/'candidates.json').read_bytes())
APP=Path(IDENTITIES['stage']['app_root'])
sys.path.insert(0,str(APP))
LIVE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state')
DATA=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
CONFIG=json.loads((APP/'stage_center_tick_config.json').read_bytes())
RESULTS=[]
def sha(raw):return hashlib.sha256(raw).hexdigest()
def runtime_env(role='stage'):
    row=IDENTITIES[role];app=Path(row['app_root'])
    return {**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(app),
        'V4_APP_ROOT':str(app),'V4_RELEASE_ID':row['release_id'],
        'V4_RELEASE_MANIFEST_PATH':str(app.parent/'release-manifest.json'),
        'V4_RELEASE_MANIFEST_SHA256':row['manifest_sha256'],
        'STAGE_CENTER_CONFIG':str(app/'stage_center_tick_config.json')}

class FourRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='stage-four-case-',dir='/private/tmp')
        self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,runtime_env());self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def candidate(self):
        from stage_center.candidate_input import read_candidate_input
        return read_candidate_input(CONFIG['candidate_acquisition_root'],'20261030')
    def snapshot(self,date):
        source=LIVE/'stage/raw/.hk_active_snapshots_v2'/date/'STAGE_1545_1555/snapshot.json'
        raw=source.read_bytes();p=json.loads(raw)
        target=self.root/'raw/.hk_active_snapshots_v2'/date/'STAGE_1545_1555/snapshot.json'
        target.parent.mkdir(parents=True);target.write_bytes(raw)
        RESULTS.append({'source':str(source),'sha256':sha(raw),'date':date})
        return p,source,raw
    def plan(self,date,payload):
        from stage_center.acquisition import build_plan,StageUniverseBinding
        c=replace(self.candidate(),trade_date=date)
        binding=StageUniverseBinding.ready(market='HK_CONNECT',trade_date=date,
            role='HK_CONNECT_D1_TOP100',codes=tuple(payload['codes']),source_run_id='sealed-original',
            sha256=payload['pool_artifact_sha256'],evidence=())
        return build_plan(c.root,date,'STAGE_1545_1555',candidate=c,universe_bindings={'HK_CONNECT':binding})
    def test_01_real_candidate_and_bad_sha(self):
        from stage_center.candidate_input import read_candidate_input,CandidateInputError,_effective_execution_input
        c=self.candidate()
        self.assertEqual(c.original_row_count,532);self.assertEqual(c.effective_row_count,531)
        self.assertIn('A.261029',c.original_codes);self.assertNotIn('A.261029',c.codes)
        self.assertEqual(c.quarantined_codes,('A.261029',))
        with self.assertRaisesRegex(CandidateInputError,'SHA mismatch'):
            read_candidate_input(c.root,c.trade_date,expected_current_sha256='0'*64)
        with self.assertRaisesRegex(CandidateInputError,'all quarantined'):
            _effective_execution_input(replace(c,codes=('A.261029',)))
        from contracts.a_share_entity_filter import invalid_a_share_symbols
        self.assertEqual(invalid_a_share_symbols(('A.300115','A.301029','A.510300','A.159915','HK.02915')),[])
        RESULTS.append({'case':'real_candidate','original':532,'effective':531,'current_sha256':c.current_sha256})
    def test_02_real_hourly_owner_and_cutoff(self):
        from infrastructure.manager_input_attestation import read_stage_hourly_attestation,PublicationError
        expected=[('20261030','0900','2026-10-30T09:25:05+08:00','sop-closure'),
            ('20261030','1000','2026-10-30T10:30:05+08:00','name-zoom'),
            ('20261101','2000','2026-11-01T20:59:59+08:00','r6-main')]
        for date,slot,clock,owner in expected:
            record,evidence=read_stage_hourly_attestation(stage_app=APP,data_root=DATA,date=date,slot=slot,
                mode='LIVE',as_of=datetime.fromisoformat(clock))
            self.assertTrue(any(owner in e for e in evidence));self.assertIn('completion_witness',record)
            RESULTS.append({'case':'real_hourly','date':date,'slot':slot,'owner':owner,'as_of':clock})
        with self.assertRaises(PublicationError):
            read_stage_hourly_attestation(stage_app=APP,data_root=DATA,date='20261030',slot='1000',mode='LIVE',
                as_of=datetime.fromisoformat('2026-10-30T09:25:05+08:00'))
        from stage_center.research_context import load_research_context
        for cutoff in ('09:25:05','10:30:05'):
            context=load_research_context(DATA,trade_date='20261030',stage_cutoff=cutoff)
            self.assertTrue(context.selected_slot)
            RESULTS.append({'case':'real_stage_context','cutoff':cutoff,'selected_slot':context.selected_slot})
    def test_03_real_partial_snapshot_only_99_to_provider(self):
        from stage_center.hk_stage8.rtdata import _collect_hk_stage8_natural
        p,source,raw=self.snapshot('20261030');seen=[]
        def provider(codes,**kwargs):seen.extend(codes);return {'rows':[],'errors':['OFFLINE_BOUNDARY_PROBE_NO_NETWORK']}
        result=_collect_hk_stage8_natural(self.plan('20261030',p),codes=p['codes'],snapshot_root=self.root/'raw',
            rtdata_provider=provider,natural_now=datetime.fromisoformat('2026-10-30T15:55:00+08:00'))
        self.assertEqual(len(seen),99);self.assertNotIn('HK.02915',seen)
        self.assertEqual(result.requested_rows,100);self.assertEqual(source.read_bytes(),raw)
        self.assertTrue(list((self.root/'raw/.hk_stage8_rtdata_captures').rglob('*.json')))
        RESULTS.append({'case':'real_D30_partial_boundary','provider_received':99,'excluded':'HK.02915',
                        'result':result.status,'data_limitation':'NO_SEALED_D30_RTDATA; boundary probe only'})
    def test_04_real_D29_raw_replay(self):
        from stage_center.hk_stage8.rtdata import _collect_hk_stage8_natural
        p,source,raw=self.snapshot('20261029')
        capture=LIVE/'stage/raw/.hk_stage8_rtdata_captures/20261029/STAGE_1545_1555/951a4a6b04c135087fde8d5838032b0d901708db25ee3e2bbef9bc9e26933ddc.json'
        original=capture.read_bytes();fetched=json.loads(original)
        result=_collect_hk_stage8_natural(self.plan('20261029',p),codes=p['codes'],snapshot_root=self.root/'raw',
            rtdata_provider=lambda *a,**k:fetched,natural_now=datetime.fromisoformat('2026-10-29T15:55:00+08:00'))
        self.assertTrue(result.rows);self.assertEqual(capture.read_bytes(),original);self.assertEqual(source.read_bytes(),raw)
        self.assertTrue(all(r['trade_date']=='20261029' for r in result.rows))
        RESULTS.append({'case':'real_D29_sealed_replay','source':str(capture),'sha256':sha(original),
            'result':result.status,'rows':len(result.rows),'natural_verified':False})
    def test_05_synthetic_snapshot_negative_and_exception_capture(self):
        from stage_center.hk_stage8.rtdata import _collect_hk_stage8_natural
        p,_,_=self.snapshot('20261030');plan=self.plan('20261030',p)
        def fail(*args,**kwargs):raise RuntimeError('synthetic provider disconnected')
        result=_collect_hk_stage8_natural(plan,codes=p['codes'],snapshot_root=self.root/'raw',rtdata_provider=fail,
            natural_now=datetime.fromisoformat('2026-10-30T15:55:00+08:00'))
        captures=list((self.root/'raw/.hk_stage8_rtdata_captures').rglob('*.json'))
        self.assertEqual(len(captures),1);body=json.loads(captures[0].read_bytes())
        self.assertEqual(len(body['codes']),99);self.assertIn('synthetic provider disconnected',body['errors'][0])
        path=self.root/'raw/.hk_active_snapshots_v2/20261030/STAGE_1545_1555/snapshot.json'
        for mutation in ('bad_sha','late','all_excluded'):
            damaged=copy.deepcopy(p)
            if mutation=='bad_sha':damaged['snapshot_sha256']='0'*64
            elif mutation=='late':damaged['provider_finished_at']='2026-10-30T15:55:01+08:00'
            else:
                for row in damaged['rows']:row['update_time']='2026-10-29 15:54:00'
                from stage_center.hk_stage8.snapshot import _snapshot_rows_sha
                damaged['snapshot_sha256']=_snapshot_rows_sha(damaged['rows'])
            path.write_text(json.dumps(damaged));seen=[]
            result=_collect_hk_stage8_natural(plan,codes=p['codes'],snapshot_root=self.root/'raw',
                rtdata_provider=lambda codes,**k:seen.extend(codes),natural_now=datetime.fromisoformat('2026-10-30T15:55:00+08:00'))
            self.assertFalse(seen);self.assertEqual(result.status,'CANNOT_CONFIRM',mutation)
    def test_06_real_partial_receipt_retry_keeps_HK(self):
        import ops.run_stage_center_nodes as nodes
        from stage_center._runner_parts.runner_receipts import _ExecutionScope
        from stage_center import end_to_end_deadline
        source=LIVE/'stage/receipts/20261030/STAGE_0930_0935/receipt.json'
        original=source.read_bytes();prior=json.loads(original);hk=copy.deepcopy(prior['markets']['HK_CONNECT'])
        self.assertFalse(nodes._stage_settled(prior));self.assertEqual(nodes._node_outcome(prior['status'],prior),'TRANSIENT')
        cfg={**CONFIG,'receipt_root':str(self.root/'receipts'),'node_retry_backoff_seconds':0}
        receipt=Path(cfg['receipt_root'])/'20261030/STAGE_0930_0935/receipt.json'
        receipt.parent.mkdir(parents=True);receipt.write_bytes(original)
        calls=[]
        class Runner:
            config=SimpleNamespace(receipt_root=Path(cfg['receipt_root']))
            def _receipt_path(self,*args):return receipt
            def due_decisions(self,*args,**kwargs):return [SimpleNamespace(stage_id='STAGE_0930_0935',status='DUE',scheduled_at=datetime.fromisoformat('2026-10-30T09:35:05+08:00'))]
            def _write_receipt(self,payload,*args):
                scope=getattr(self,'_execution_scope',None)
                record=scope.merge(payload,*args) if scope else payload
                receipt.write_text(json.dumps(record));return record
            def _run_one(self,decision):
                calls.extend(self._execution_scope.markets)
                return self._write_receipt({'status':'CANNOT_CONFIRM','markets':{'A_SHARE':{'selection_status':'CANNOT_CONFIRM','selected_rows':0,'cannot_confirm':['synthetic persistent A failure']}},'write_performed':False},'20261030','STAGE_0930_0935')
        runner=Runner()
        from stage_center.market_retry import dispatch_partial_market_retry
        result=dispatch_partial_market_retry(vars(nodes),cfg,'20261030','STAGE_0930_0935',
            datetime.fromisoformat('2026-10-30T10:00:00+08:00'),mode='NATURAL',runner=runner,receipt=prior)
        self.assertEqual(calls,['A_SHARE']);self.assertEqual(result['markets']['HK_CONNECT'],hk)
        self.assertEqual(source.read_bytes(),original)
        self.assertTrue(list(receipt.parent.glob('attempt_evidence/preserved-*/PRIOR_RECEIPT.json')))
        exhausted=copy.deepcopy(prior);exhausted['node_attempt_count']=3
        result=dispatch_partial_market_retry(vars(nodes),cfg,'20261030','STAGE_0930_0935',datetime.fromisoformat('2026-10-30T09:35:05+08:00'),mode='NATURAL',runner=runner,receipt=exhausted)
        self.assertEqual(result['status'],'SKIPPED_RETRY_EXHAUSTED')
        runner.due_decisions=lambda *a,**k:[SimpleNamespace(stage_id='STAGE_0930_0935',status='LATE_CATCHUP_REPLAY')]
        result=dispatch_partial_market_retry(vars(nodes),cfg,'20261030','STAGE_0930_0935',datetime.fromisoformat('2026-10-30T12:00:00+08:00'),mode='RECOVERY',runner=runner,receipt=prior)
        self.assertTrue(result['afterfact_required']);self.assertEqual(calls,['A_SHARE'])
        RESULTS.append({'case':'real_partial_receipt_synthetic_DUE_retry',
            'source':str(source),'sha256':sha(original),'markets_called':calls,
            'HK_receipt_object_unchanged':True,'DUE_decision':'SYNTHETIC_SCOPE_REGRESSION_ONLY',
            'late_decision':'LATE_CATCHUP_REPLAY_NO_FORMAL_CALL'})
    def test_07_collector_and_afterfact_raw_failure_retention(self):
        from stage_center.collector_capture import retained_collector_call
        from stage_center.snapshot_recovery import persist_recovery_request
        plan=SimpleNamespace(trade_date='20261030',stage_id='STAGE_0930_0935',candidate_input=self.candidate(),
            universe_bindings={},codes_for=lambda market:('A.300115',))
        def fail(*a):raise RuntimeError('synthetic A transport error, original detail')
        with self.assertRaises(RuntimeError):retained_collector_call(fail,plan,'A_SHARE',self.root)
        paths=list((self.root/'.collector_requests').rglob('*.json'));self.assertEqual(len(paths),1)
        record=json.loads(paths[0].read_bytes());self.assertEqual(record['requested_codes'],['A.300115'])
        self.assertIn('original detail',record['error']['message']);self.assertFalse(record['authorizes_selection'])
        from stage_center.acquisition import SourceResult
        returned=SourceResult('synthetic','CANNOT_CONFIRM',rows=({'code':'A.261029','bad_value':'keep raw'},))
        retained_collector_call(lambda *a:returned,plan,'A_SHARE',self.root)
        self.assertTrue(any('keep raw' in p.read_text() for p in (self.root/'.collector_requests').rglob('*.json')))
        cfg={'selection_root':str(self.root)}
        result=persist_recovery_request(cfg,'20261030',['A.300115'],started_at='2026-11-01T21:00:00+08:00',
            finished_at='2026-11-01T21:00:01+08:00',error='synthetic failure')
        self.assertEqual(sha((self.root/result['relative_path']).read_bytes()),result['sha256'])
    def test_08_sealed_SOP_and_API_identity(self):
        env=runtime_env('api');app=Path(IDENTITIES['api']['app_root'])
        code="import json;from infrastructure.operations_sop_reader import read_sop;from infrastructure.scheduling.dispatcher import validate_release_identity;v=read_sop('stage-selection');print(json.dumps({'identity':validate_release_identity(),'sha256':v['sha256'],'has_recovery_command':'stage_data_recovery.py' in v['content']}))"
        result=subprocess.run([sys.executable,'-B','-c',code],cwd=app,env=env,capture_output=True,text=True,check=True)
        record=json.loads(result.stdout);self.assertTrue(record['has_recovery_command'])
        self.assertEqual(record['sha256'],sha((app/'docs/operations/STAGE_SELECTION_SOP.md').read_bytes()))
        env['V4_RELEASE_MANIFEST_SHA256']='0'*64
        bad=subprocess.run([sys.executable,'-B','-c',code],cwd=app,env=env,capture_output=True,text=True)
        self.assertNotEqual(bad.returncode,0)
    def test_09_real_scoped_runner_store_replay_preserves_HK_bytes(self):
        """Real runner/stores, offline original raw; no claim of timely recovery."""
        import ops.run_stage_center_nodes as nodes
        from stage_center._runner_parts.runner_receipts import scoped_recovery_runner
        date='20261030';stage='STAGE_0930_0935';key=f'{date}/{stage}'
        cfg={**CONFIG}
        for lane,pointer in [('raw','latest.json'),('selection','selection_latest.json')]:
            src=LIVE/'stage'/lane;dst=self.root/lane;dst.mkdir()
            index=json.loads((src/pointer).read_bytes());entries=index['entries']
            for identity,entry in entries.items():
                if identity.startswith(key+'/'):
                    prefix=Path(entry['artifact_relative']).parent
                    shutil.copytree(src/prefix,dst/prefix)
            shutil.copyfile(src/pointer,dst/pointer)
            cfg[lane+'_root']=str(dst)
        src=LIVE/'stage/raw';dst=self.root/'raw'
        bundles=json.loads((src/'bundle_latest.json').read_bytes())
        entry=bundles['entries'][key]
        relative=next(v for k,v in entry.items() if k.endswith('_relative'))
        prefix=Path(relative).parent;shutil.copytree(src/prefix,dst/prefix)
        shutil.copyfile(src/'bundle_latest.json',dst/'bundle_latest.json')
        cfg['receipt_root']=str(self.root/'receipts')
        shutil.copytree(LIVE/'stage/receipts'/date/stage,Path(cfg['receipt_root'])/date/stage)
        receipt=Path(cfg['receipt_root'])/date/stage/'receipt.json';prior=json.loads(receipt.read_bytes())
        protected={str(p.relative_to(self.root)):sha(p.read_bytes()) for p in self.root.rglob('*')
                   if p.is_file() and ('HK_CONNECT' in str(p) or p.name=='selection_latest.json')}
        runner=nodes._build_runner(cfg)
        def forbid(*a,**k):raise AssertionError('offline replay must not call any provider')
        runner.collectors={'A_SHARE':forbid,'HK_CONNECT':forbid}
        scoped=scoped_recovery_runner(runner,markets=('A_SHARE',),prior_receipt=prior,attempt_count=2,
            origin='OFFLINE_SEALED_RAW_ACCEPTANCE_ONLY')
        decision=next(d for d in runner.due_decisions(date,datetime.fromisoformat('2026-10-30T09:35:05+08:00'),historical_backfill=False) if d.stage_id==stage)
        result=scoped._run_one(decision)
        self.assertEqual(result['markets']['HK_CONNECT'],prior['markets']['HK_CONNECT'])
        # selection_latest may gain A, but its original HK entry is byte-equivalent.
        before_index=json.loads((LIVE/'stage/selection/selection_latest.json').read_bytes())
        after_index=json.loads((self.root/'selection/selection_latest.json').read_bytes())
        self.assertEqual(before_index['entries'][key+'/HK_CONNECT'],after_index['entries'][key+'/HK_CONNECT'])
        for relative,digest in protected.items():
            if relative.endswith('selection_latest.json'):continue
            self.assertEqual(sha((self.root/relative).read_bytes()),digest)
        RESULTS.append({'case':'real_scoped_runner_raw_replay','result':result['status'],
            'A_selected_rows':result['markets'].get('A_SHARE',{}).get('selected_rows'),
            'HK_immutable_files_verified':len(protected)-1,'provider_invocations':0,'natural_verified':False})
    def test_10_real_existing_observation_recovery_command(self):
        from ops.stage_data_recovery import run
        date='20261030';stage='STAGE_0925';cfg={**CONFIG,'selection_root':str(self.root/'selection'),
            'receipt_root':str(self.root/'receipts')}
        src=LIVE/'stage/selection';dst=Path(cfg['selection_root']);dst.mkdir()
        pointer_relative=f'snapshot_recovery/current/{date}/{stage}/A_SHARE.json'
        raw=(src/pointer_relative).read_bytes();pointer=json.loads(raw)
        target=dst/pointer_relative;target.parent.mkdir(parents=True);target.write_bytes(raw)
        for key in ('artifact','manifest','receipt','capture'):
            relative=pointer[key+'_relative'];target=dst/relative;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(src/relative,target)
        original=(LIVE/'stage/receipts'/date/stage/'receipt.json').read_bytes()
        receipt=Path(cfg['receipt_root'])/date/stage/'receipt.json';receipt.parent.mkdir(parents=True);receipt.write_bytes(original)
        with self.assertRaisesRegex(ValueError,'CAS_MISMATCH'):
            run(cfg,date,stage,action='select-existing',expected_receipt_sha256='0'*64)
        report=run(cfg,date,stage,action='select-existing',expected_receipt_sha256=sha(original))
        self.assertEqual(report['status'],'SNAPSHOT_RESELECTION_READY')
        selected=report['snapshot_reselection']['selections'][0]
        self.assertEqual(selected['selected_rows'],10);self.assertEqual(selected['recommendation_status'],'WATCH_ONLY')
        self.assertEqual(receipt.read_bytes(),original)
        RESULTS.append({'case':'real_existing_observation_CAS_recovery_command','status':report['status'],
            'selected_rows':10,'action':'WATCH_ONLY','captured_at':selected['captured_at'],
            'network_invocations':0,'original_receipt_sha256':sha(original),'natural_verified':False})
    def test_11_native_precapture_failure_and_raw_bad_response(self):
        from infrastructure.stage_quote_provider import precapture_native_a_opening,NativeAOpeningSnapshotProvider
        edge=datetime.fromisoformat('2026-10-30T09:25:00+08:00')
        cfg={**CONFIG,'a_auction_root':str(self.root/'auction')}
        class Failing:
            def prepare(self):raise RuntimeError('synthetic native prepare error with original detail')
            def close(self):pass
        result=precapture_native_a_opening(cfg,'20261030',sleep=lambda _:None,now=lambda:edge,provider=Failing())
        self.assertEqual(result['status'],'CANNOT_CONFIRM')
        body=json.loads(Path(result['attempt_evidence']).read_bytes())
        self.assertEqual(len(body['requested_codes']),531);self.assertNotIn('A.261029',body['requested_codes'])
        self.assertIn('original detail',body['error']);self.assertIn('finished_at',body)
        with patch('infrastructure.stage_quote_provider.NativeAOpeningSnapshotProvider',side_effect=RuntimeError('synthetic constructor error')):
            result=precapture_native_a_opening(cfg,'20261030',sleep=lambda _:None,now=lambda:edge)
        self.assertIn('constructor error',Path(result['attempt_evidence']).read_text())
        class Primary:
            def snapshot(self,*a,**k):return {'trade_date':'20261029','stage_id':'STAGE_0925','rows':[{'symbol':'A.261029','raw':'bad row must survive'}]}
        native=NativeAOpeningSnapshotProvider(primary=Primary(),fallback=object(),now=lambda:edge,sleep=lambda _:None)
        result=native.snapshot(['A.300115'],trade_date='20261030',capability_only=True)
        self.assertEqual(result['raw_batches'][0]['rows'][0]['raw'],'bad row must survive')
        app=Path(IDENTITIES['a_precapture']['app_root'])
        code="from stage_center.candidate_input import read_candidate_input; c=read_candidate_input("+repr(CONFIG['candidate_acquisition_root'])+",'20261030');assert c.original_row_count==532 and len(c.codes)==531 and 'A.261029' not in c.codes;print('PRECAPTURE_ENTITY_BOUNDARY_PASS')"
        result=subprocess.run([sys.executable,'-B','-c',code],cwd=app,env=runtime_env('a_precapture'),capture_output=True,text=True,check=True)
        self.assertIn('PRECAPTURE_ENTITY_BOUNDARY_PASS',result.stdout)
    def test_12_process_raw_before_aggregation_and_timeout(self):
        from stage_center.collector_capture import retained_collector_call
        from stage_center.live_collectors import _scoped_process_runner
        from stage_center.acquisition import SourceResult
        plan=SimpleNamespace(trade_date='20261030',stage_id='STAGE_0930_0935',candidate_input=self.candidate(),
            universe_bindings={},codes_for=lambda market:('A.300115',))
        raw_stdout=b'{"raw_rows":[{"code":"261029","invalid_original":"retained-before-aggregation"}]}'
        calls=[]
        def process(command,**kwargs):
            calls.append(command);return subprocess.CompletedProcess(command,0,stdout=raw_stdout,stderr=b'original warning')
        run=_scoped_process_runner(Path(CONFIG['shared_data_root']),process)
        def collector(*a):
            returned=run([sys.executable,'-m','scripts.live_acquisition.pytdx_hq_probe','--codes','300115'],capture_output=True)
            self.assertEqual(returned.stdout,raw_stdout)
            return SourceResult('synthetic_HQ','CANNOT_CONFIRM',cannot_confirm=('synthetic bridge aggregate rejected',))
        retained_collector_call(collector,plan,'A_SHARE',self.root)
        self.assertEqual(len(calls),1)
        files=list((self.root/'.process_requests').rglob('request.json'));self.assertEqual(len(files),1)
        record=json.loads(files[0].read_bytes());self.assertEqual(record['stdout_sha256'],sha(raw_stdout))
        self.assertEqual((files[0].parent/'stdout.bin').read_bytes(),raw_stdout)
        self.assertEqual(record['requested_codes'],['A.300115']);self.assertNotIn('env',record)
        run(['synthetic-after-context-reset'])
        self.assertEqual(len(list((self.root/'.process_requests').rglob('request.json'))),1)
        def timeout(command,**kwargs):raise subprocess.TimeoutExpired(command,1,output=b'partial original stdout',stderr=b'timeout stderr')
        timed=_scoped_process_runner(Path(CONFIG['shared_data_root']),timeout)
        with self.assertRaises(subprocess.TimeoutExpired):
            retained_collector_call(lambda *a:timed(['synthetic-timeout']),plan,'A_SHARE',self.root)
        files=list((self.root/'.process_requests').rglob('request.json'));self.assertEqual(len(files),2)
        self.assertTrue(any((p.parent/'stdout.bin').read_bytes()==b'partial original stdout' for p in files))
        RESULTS.append({'case':'synthetic_process_injection_seam','process_calls_per_request':1,
            'stdout_before_aggregation_retained':True,'timeout_partial_stdout_retained':True,
            'context_reset_verified':True,'network_invocations':0})
    def test_13_actual_API_SOP_endpoint_inprocess_isolated_state(self):
        app=Path(IDENTITIES['api']['app_root']);env=runtime_env('api')
        code='''import asyncio,hashlib,json,os
from pathlib import Path
import httpx
from apps.api.v4_api.app import create_app
from infrastructure.scheduling.dispatcher import validate_release_identity
root=Path(os.environ['STAGE_FOUR_HTTP_STATE']);root.mkdir()
app=create_app(data_root=root/'data',shared_data_root=root/'shared',ledger_root=root/'ledger',
    stage_center_selection_root=root/'selection',manager_research_state_root=root/'manager',
    research_data_root=root/'research',research_ledger_root=root/'research-ledger',
    morning_news_data_root=root/'morning',preselection_source_root=root/'preselection')
async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://isolated-candidate') as c:
        response=await c.get('/api/v4/operations/sop',params={'doc':'stage-selection'})
        assert response.status_code==200,response.text
        data=response.json();expected=Path(os.environ['V4_APP_ROOT'])/'docs/operations/STAGE_SELECTION_SOP.md'
        assert data['sha256']==hashlib.sha256(expected.read_bytes()).hexdigest()
        assert 'stage_data_recovery.py' in data['content']
        unknown=await c.get('/api/v4/operations/sop',params={'doc':'/tmp/arbitrary'})
        assert unknown.status_code==422
        identity=validate_release_identity()
        os.environ['V4_RELEASE_MANIFEST_SHA256']='0'*64
        rejected=await c.get('/api/v4/operations/sop',params={'doc':'stage-selection'})
        assert rejected.status_code==503
        print(json.dumps({'status':'ASGI_ENDPOINT_VERIFIED','endpoint':'/api/v4/operations/sop?doc=stage-selection',
            'http_status':200,'unknown_document_status':422,'bad_manifest_status':503,'sha256':data['sha256'],
            'identity':identity,'state_root':str(root),'listener_started':False,'network_invocations':0}))
asyncio.run(main())
'''
        env['STAGE_FOUR_HTTP_STATE']=str(self.root/'api-state')
        result=subprocess.run([sys.executable,'-B','-c',code],cwd=app,env=env,capture_output=True,text=True,check=True)
        record=json.loads(result.stdout.strip().splitlines()[-1]);RESULTS.append(record)

if __name__=='__main__':
    suite=(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name,FourRepairTests)
        for name in sys.argv[1:]) if len(sys.argv)>1 else unittest.defaultTestLoader.loadTestsFromTestCase(FourRepairTests))
    selected_names=sys.argv[1:] if len(sys.argv)>1 else unittest.defaultTestLoader.getTestCaseNames(FourRepairTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    failed_names={test.id().split('.')[-1] for test,_ in result.failures+result.errors}
    output=Path(os.environ.get('STAGE_FOUR_RESULTS','/private/tmp/v4-stage-four-results.json'))
    output.write_text(json.dumps({'passed':result.wasSuccessful(),'tests_run':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'cases':RESULTS,
        'outcome_by_test':{name:'FAIL' if name in failed_names else 'PASS' for name in selected_names},
        'natural_verified':False,'candidate_bundle':str(BUNDLE)},ensure_ascii=False,indent=2)+'\n')
    raise SystemExit(0 if result.wasSuccessful() else 1)
