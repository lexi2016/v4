"""Actual V5 subprocess adapter -> original plan store -> ordinary module API."""
from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen

from v5_shadow.digests import canonical_bytes, sha256_json
from v5_shadow.manager_plan import run_manager_plan, publish_workspace_read, ROUTE
from v5_shadow.module_api import create_module_server


class ManagerPlanAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        inputs = {}
        for name in ('manager', 'materials', 'us'):
            path = self.root/name;path.mkdir()
            inputs[name] = dict(root=str(path), files={})
        output = self.root/'plans';output.mkdir()
        (output/'.v5-manager-plan-root').write_text('v5.manager-plan-root.v1\n')
        self.request = dict(target_date='20261008', now='2026-10-09T10:00:00+08:00',
            action='read', view='dynamic', selection_date=None, announcement_date=None,
            inputs=inputs, rebound=None, manager_output_root=str(output))
        self.output = output
        self.daily = self.save_daily()

    def save_daily(self, generated='2026-10-09T09:00:00+08:00'):
        daily = dict(schema_version='v4.manager_research.us_mapping_daily_run.v1',
            target_trade_date='20261008', run_id='1'*32, generated_at=generated,
            research_cutoff='2026-10-08T09:00:00.123456+08:00', us_session_date='20261007',
            status='COMPLETED', source_status='READY',
            source_identity={'status':'VERIFIED','session_date':'20261007','payload_sha256':'a'*64},
            input_identity='b'*64, target_date_eligibility='CANNOT_CONFIRM',
            coverage={'full_market_coverage':False}, matches=[{'reason':'SYNTHETIC_RELATION'}],
            gaps=['SYNTHETIC_FIXTURE_NOT_PRODUCTION_EVIDENCE'], RESEARCH_ONLY=True,
            production_allowed=False, buy_gate_updated=False, orders_sent=False)
        daily['artifact_sha256'] = sha256_json(daily)
        prefix='us_mapping_research/20261008/'
        files={prefix+'runs/'+daily['run_id']+'.json':daily,
               prefix+'latest.json':dict(schema_version='v4.manager_research.us_mapping_daily_pointer.v1',
                    target_trade_date='20261008', run_id=daily['run_id'], artifact_sha256=daily['artifact_sha256'])}
        binding=self.request['inputs']['manager']
        for relative,value in files.items():
            path=Path(binding['root'])/relative;path.parent.mkdir(parents=True,exist_ok=True)
            raw=canonical_bytes(value);path.write_bytes(raw);binding['files'][relative]=hashlib.sha256(raw).hexdigest()
        return daily

    def files(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_actual_adapter_reads_workspace_without_source_or_output_writes(self):
        before=self.files();value=run_manager_plan(self.request)['payload']
        self.assertEqual(self.files(),before)
        self.assertEqual(value['us_mapping_research']['daily_run'],self.daily)
        self.assertEqual(value['us_market_attention']['status'],'INPUT_MISSING')
        self.assertEqual(value['us_market_attention']['expected_us_session'],'20261008')
        self.assertNotEqual(value['owner_chain']['us_mapping_daily_plan_reference']['status'],'CONSUMED')
        self.assertEqual([row['channel'] for row in value['daily_channels']['channels']],
                         ['ANNOUNCEMENT','HK_CONNECT','OVERSOLD'])

    def test_actual_adapter_saves_original_plan_and_same_run_attempt(self):
        self.request['action']='refresh';result=run_manager_plan(self.request)
        self.assertEqual(result['readback']['status'],'MATCHED')
        run=result['readback']['run_id']
        store=self.output/result['readback']['store_relative']
        self.assertEqual(result['readback']['store_relative'],'current_recovery')
        plan=json.loads((store/'workspace_plans/20261008'/f'{run}.json').read_bytes())
        attempt=json.loads((store/'workspace_plan_runs/20261008'/f'{run}.json').read_bytes())
        self.assertEqual(plan['run_id'],attempt['run_id'])
        self.assertEqual(result['readback']['attempt'],attempt)
        self.assertEqual(plan['sha256'],sha256_json({k:v for k,v in plan.items() if k!='sha256'}))
        self.assertNotEqual(plan['workspace']['owner_chain']['us_mapping_daily_plan_reference']['status'],'CONSUMED')
        self.assertFalse(result['natural_verified'])

    def test_rejected_daily_sha_does_not_change_adapter_plan_identity(self):
        first=run_manager_plan(self.request)['payload']
        self.save_daily('2026-10-09T09:01:00+08:00')
        second=run_manager_plan(self.request)['payload']
        self.assertEqual(first['input_identity'],second['input_identity'])
        self.assertNotEqual(first['us_mapping_research']['daily_run']['artifact_sha256'],
                            second['us_mapping_research']['daily_run']['artifact_sha256'])

    def test_same_run_terminal_tampering_is_rejected_on_real_readback(self):
        self.request['action']='refresh';saved=run_manager_plan(self.request)
        path=self.output/saved['readback']['store_relative']/'workspace_plan_runs/20261008'/(saved['readback']['run_id']+'.json')
        attempt=json.loads(path.read_bytes());attempt['run_id']='2'*32;attempt.pop('sha256')
        attempt['sha256']=sha256_json(attempt);path.write_bytes(canonical_bytes(attempt))
        self.request['action']='read';value=run_manager_plan(self.request)['payload']
        self.assertFalse(value['plan_product']['consumed'])
        self.assertEqual(value['plan_product']['status'],'OWNER_ATTEMPT_UNVERIFIED')

    def test_saved_plan_context_is_not_replaced_by_current_runtime_overlay(self):
        self.request['action']='refresh';first=run_manager_plan(self.request)['payload']
        before=self.files()
        self.request.update(action='read',now='2026-10-09T10:05:00+08:00')
        second=run_manager_plan(self.request)['payload']
        self.assertEqual(second['plan_product']['status'],'CURRENT_RECOVERY')
        self.assertTrue(second['plan_product']['consumed'])
        self.assertEqual(second['plan_product']['run_id'],first['plan_product']['run_id'])
        self.assertEqual(second['input_identity'],first['input_identity'])
        self.assertEqual(second['plan_context'],first['plan_context'])
        self.assertEqual(second['runtime_status_read_at'],self.request['now'])
        self.assertEqual(second['market_screen']['data_context']['research_cutoff'],self.request['now'])
        self.assertEqual(self.files(),before)

    def test_ordinary_auto_get_serves_committed_owner_response_without_computation(self):
        self.request.update(target_date='20261009',view='auto',now='2026-10-09T10:00:00+08:00')
        api_root=self.root/'api';api_root.mkdir()
        (api_root/'.v5-module-root').write_text('v5.module-root.v1:manager\n')
        config=dict(schema_version='v5.module_api.v1',module_id='manager',release_id='test-v5-manager',
                    data_root=str(api_root),routes=[ROUTE])
        published=publish_workspace_read(self.request,config,expected_generation=None)
        server=create_module_server(config)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        before=self.files()
        with urlopen('http://127.0.0.1:'+str(server.server_port)+ROUTE+'?date=20261009&view=auto',timeout=5) as response:
            actual=json.load(response)
        self.assertEqual(actual,published['result']['payload'])
        self.assertEqual(actual['date_bindings']['plan_date'],'20261009')
        self.assertEqual(self.files(),before)


if __name__=='__main__':unittest.main()
