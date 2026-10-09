"""Mac-only integration candidate. Contract fixtures are not real owner evidence."""
from datetime import datetime,timezone,timedelta
import copy
import json
from pathlib import Path
import tempfile
import unittest
from v5_shadow import rebound_owner as owner
from v5_shadow.digests import sha256_json
from v5_shadow.manager_plan import run_manager_plan

class ManagerReboundObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();inputs={}
        for name in ('manager','materials','us'):
            p=self.root/name;p.mkdir();inputs[name]=dict(root=str(p),files={})
        self.output=self.root/'plans';self.output.mkdir();(self.output/'.v5-manager-plan-root').write_text('v5.manager-plan-root.v1\n')
        self.observed=self.root/'observed';self.observed.mkdir();(self.observed/'.v5-rebound-owner-root').write_bytes(owner.MARKER)
        # A failed, recorded-input contract fixture exercises retained owner errors
        # through the real store/manager subprocess; no market calculation claimed.
        request=dict(target_date='20261009',signal_date='20261008',research_cutoff='2026-10-09T05:00:00+00:00',data_kind='RECORDED_INPUT_REPLAY',files={})
        self.artifact=dict(schema_version='v5.rebound_owner.v1',run_id='9'*32,request=request,request_sha256=sha256_json(request),source_capsule_sha256=owner.PIN,execution_kind='MANUAL_RECORDED_INPUT_REPLAY',started_at='2026-10-09T05:00:01+00:00',finished_at='2026-10-09T05:00:02+00:00',snapshot=None,research_observation=None,legacy_diagnostic=None,computation_status='CANNOT_CONFIRM',formal_status='CANNOT_CONFIRM',reason_codes=['MASTER_RECEIPT_MISSING'],**owner.SAFETY)
        reference=owner._publish(self.observed,self.artifact)
        self.request=dict(target_date='20261009',now='2026-10-09T06:58:22.011193+00:00',action='read',view='dynamic',selection_date=None,announcement_date=None,inputs=inputs,rebound=None,manager_output_root=str(self.output),rebound_owner=dict(root=str(self.observed),reference=reference))

    def test_saved_failure_is_read_without_recompute_and_never_becomes_formal_screen(self):
        before={str(p):p.read_bytes() for p in self.observed.rglob('*') if p.is_file()}
        out=run_manager_plan(self.request)['payload'];observed=out['rebound_research_observation']
        self.assertEqual(observed['status'],'CANNOT_CONFIRM')
        self.assertIn('MASTER_RECEIPT_MISSING',observed['reason_codes'])
        self.assertIsNone(observed['eligible_screen']);self.assertIsNone(observed['research_observation'])
        self.assertFalse(out['market_screen']['main_screen_ready'])
        self.assertNotIn('legacy_diagnostic',observed)
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.observed.rglob('*') if p.is_file()})

    def test_damaged_receipt_is_visible_without_losing_other_workspace_lanes(self):
        (self.observed/'runs'/('9'*32)/'receipt.json').write_text('{}')
        out=run_manager_plan(self.request)['payload']
        self.assertIn('REBOUND_READBACK_SHA:receipt',out['rebound_research_observation']['reason_codes'])
        self.assertIn('daily_channels',out)
        self.assertIsNone(out['rebound_research_observation']['eligible_screen'])

    def test_late_finished_result_is_not_backfilled_into_earlier_context(self):
        self.request['now']='2026-10-09T04:00:00+00:00'
        out=run_manager_plan(self.request)['payload']['rebound_research_observation']
        self.assertIn('REBOUND_MANAGER_AFTER_CUTOFF',out['reason_codes'])
        self.assertIsNone(out['research_observation'])

    def test_target_date_mismatch_is_visible(self):
        self.request['target_date']='20261008'
        out=run_manager_plan(self.request)['payload']['rebound_research_observation']
        self.assertIn('REBOUND_MANAGER_DATE_MISMATCH',out['reason_codes'])

    def test_overlapping_plan_root_is_rejected(self):
        self.request['rebound_owner']['root']=str(self.output)
        with self.assertRaisesRegex(ValueError,'MANAGER_REBOUND_OWNER_ROOT_OVERLAP'):run_manager_plan(self.request)

    def test_old_shadow_and_new_owner_same_or_nested_roots_are_rejected(self):
        pair=self.root/'shadow-pair'
        for old,new in ((pair,pair),(pair,pair/'new'),(pair/'old',pair)):
            with self.subTest(old=str(old),new=str(new)):
                request=copy.deepcopy(self.request)
                request['rebound']={'root':str(old),'reference':{}}
                request['rebound_owner']['root']=str(new)
                with self.assertRaisesRegex(ValueError,'MANAGER_REBOUND_OWNER_ROOT_OVERLAP'):
                    run_manager_plan(request)

    def test_distinct_sibling_shadow_root_passes_path_admission(self):
        from v5_shadow.manager_plan import _request
        self.request['rebound']={'root':str(self.root/'legacy-shadow'),'reference':{}}
        self.assertEqual(_request(self.request),self.request)

    def test_refresh_retains_original_plan_readback_and_separate_observation(self):
        self.request['action']='refresh'
        out=run_manager_plan(self.request)
        self.assertEqual(out['readback']['status'],'MATCHED')
        run=out['readback']['run_id'];saved=json.loads((self.output/'workspace_plans/20261009'/f'{run}.json').read_bytes())
        self.assertNotIn('rebound_research_observation',saved['workspace'])
        self.assertFalse(out['payload']['market_screen']['main_screen_ready'])
        self.assertEqual(out['payload']['rebound_research_observation']['source_run_id'],'9'*32)

    def computed_fixture(self,kind):
        # Deliberately fabricated contract fixture; never a real calculation.
        from test_rebound_owner import request_for,legacy_screen
        request=request_for(self.root/'fixture-input')
        request.update(research_cutoff='2026-10-08T01:00:00+00:00',data_kind=kind)
        snapshot=owner.prepare_snapshot(request,self.root/'fixture-snapshot')
        legacy=legacy_screen()
        artifact=dict(self.artifact,run_id='8'*32,request=request,request_sha256=sha256_json(request),
            started_at='2026-10-08T01:00:01+00:00',finished_at='2026-10-08T01:00:02+00:00',
            execution_kind='SYNTHETIC_TEST' if kind=='SYNTHETIC' else 'MANUAL_RECORDED_INPUT_REPLAY',
            snapshot=snapshot,snapshot_sha256=snapshot['snapshot_sha256'],
            # Synthetic contract declaration, not dependency/runtime attestation.
            dependencies={'status':'MATCH'},implementation_identity=owner._identity(),
            context={'market_session':'20261007','plan_trade_date':'20261008'},
            computation_status=legacy['status'],reason_codes=list(owner.BLOCKERS),
            legacy_diagnostic={'status':'UNTRUSTED_LEGACY_ASSERTIONS','payload':legacy},
            research_observation=owner.research_projection(legacy,{}))
        self.request.update(target_date='20261008',now='2026-10-08T06:58:22+00:00')
        self.request['rebound_owner']['reference']=owner._publish(self.observed,artifact)

    def test_recorded_observation_is_downgraded_and_separate_from_formal_screen(self):
        self.computed_fixture('RECORDED_INPUT_REPLAY')
        payload=run_manager_plan(self.request)['payload']
        observation=payload['rebound_research_observation']
        self.assertIsNone(observation['eligible_screen'])
        self.assertFalse(observation['research_observation']['main_screen_ready'])
        self.assertEqual(observation['research_observation']['coverage']['strict_count'],1)
        self.assertFalse(payload['market_screen']['main_screen_ready'])
        self.assertNotIn('amount_hkd',json.dumps(observation))
        self.assertNotIn('legacy_diagnostic',observation)
        self.assertIn('REBOUND_PROVIDER_FINALITY_NOT_ATTESTED',observation['reason_codes'])

    def test_synthetic_computation_never_enters_manager_observation(self):
        self.computed_fixture('SYNTHETIC')
        observation=run_manager_plan(self.request)['payload']['rebound_research_observation']
        self.assertIsNone(observation['research_observation'])
        self.assertIn('REBOUND_MANAGER_SYNTHETIC_NOT_ADMITTED',observation['reason_codes'])
