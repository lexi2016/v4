"""Synthetic saved panel observation integration; no business computation."""
import copy
import json
from pathlib import Path
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from v5_shadow import rebound_observation as owner
from v5_shadow.digests import sha256_json
from v5_shadow.manager_plan import run_manager_plan
from test_manager_rebound_observation import ManagerReboundObservationTests
from test_rebound_observation import raw_row
from synthetic_worker_clock import synthetic_worker_clock


class ManagerPanelObservationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(synthetic_worker_clock({'manager_plan':'2026-10-09T13:06:00+00:00'}))
        fixture=ManagerReboundObservationTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.request=copy.deepcopy(fixture.request);self.request.pop('rebound_owner')
        self.root=fixture.root/'panel-observation';self.root.mkdir()
        (self.root/'.v5-rebound-observation-root').write_bytes(owner.MARKER)
        request=dict(schema_version='v5.rebound_observation_request.v1',target_date='20261009',signal_date='20261008',
            data_kind='RECORDED_INPUT_CURRENT',input_root='/SYNTHETIC_CONTRACT_FIXTURE_NOT_REAL',
            paths={'panel':'panel.parquet','panel_manifest':'manifest.json'},files={'panel.parquet':'a'*64,'manifest.json':'b'*64})
        files={name:{'sha256':digest} for name,digest in request['files'].items()}
        snapshot=dict(files=files,snapshot_sha256=sha256_json(files),source_file_sha256=request['files'],owner_origin_verified=False,owner_read_lease_verified=False)
        descriptor,_=owner._capsule();calendar=descriptor['bindings']['vendor/rebound_baseline/contracts/market_calendar_2026.json']
        stamp='2026-10-09T05:00:01+00:00';raw=raw_row()
        raw.update(history_status='PARTIAL_UNKNOWN',history_unknown_reasons='MISSING_HISTORY',oversold_flag=None,volume_flag_5d_ge_1_5=None,
            missing_prior60_dates=['20261005','20261006','20261007'],missing_previous5_dates=['20261005','20261006','20261007'])
        self.artifact=dict(schema_version='v5.rebound_observation.v1',run_id='7'*32,request=request,request_sha256=sha256_json(request),
            started_at='2026-10-09T05:00:00+00:00',observed_at=stamp,finished_at='2026-10-09T05:00:02+00:00',
            source_capsule_sha256=owner.PIN,execution_kind='CURRENT_RECORDED_PANEL_OBSERVATION',snapshot=snapshot,snapshot_sha256=snapshot['snapshot_sha256'],
            rows=owner.project_rows([raw],'20261008',stamp),counts=dict(observed_rows=1,numeric_input_complete=0,numeric_input_incomplete=1),
            computation_status='NATIVE_VALUES_OBSERVED',reason_codes=list(owner.GAPS),
            context=dict(market_session='20261008',plan_trade_date='20261009',research_cutoff=stamp,calendar_sha256=calendar),
            history_sessions={'calendar_sha256':calendar},dependencies={'status':'MATCH'},
            source_identity=dict(panel_sha256='a'*64,panel_manifest_sha256='b'*64,calendar_sha256=calendar,original_source_sha256=descriptor['source_sha256']),
            implementation_identity=owner._identity(),calculation_identity='FROZEN_NUMERIC_BODY_EXTRACT_NOT_COMPLETE_MASTER_OWNER',
            scale_evidence=copy.deepcopy(owner.SCALE),finality_status='NOT_ATTESTED_BY_PROVIDER',eligibility_status='UNVERIFIED',**owner.SAFETY)
        self.bind()

    def bind(self):
        self.request['rebound_observation']=dict(root=str(self.root),reference=owner._publish(self.root,self.artifact))

    def test_saved_rows_read_twice_without_recompute_or_formal_change(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        plain=copy.deepcopy(self.request);plain.pop('rebound_observation');baseline=run_manager_plan(plain)['payload']
        result=run_manager_plan(self.request)['payload'];observation=result.pop('rebound_panel_observation')
        self.assertEqual(result,baseline);self.assertIsNone(observation['eligible_screen'])
        summary=observation['row_summary'];self.assertEqual(summary['numeric_input_incomplete'],1)
        self.assertEqual(summary['missing_history_dates'],['20261005','20261006','20261007'])
        self.assertTrue(all(value['unknown']==1 for value in summary['native_comparison_counts'].values()))
        self.assertEqual(summary['all_rows_sha256'],sha256_json(self.artifact['rows']))
        self.assertNotIn('rows',observation)
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_broken_receipt_is_optional_gap(self):
        (self.root/'runs'/('7'*32)/'receipt.json').write_text('{}')
        result=run_manager_plan(self.request)['payload']
        self.assertIn('OBSERVATION_READBACK_SHA:receipt',result['rebound_panel_observation']['reason_codes'])
        self.assertIsNone(result['rebound_panel_observation']['row_summary']);self.assertIn('daily_channels',result)

    def test_missing_artifact_does_not_block_workspace(self):
        (self.root/'runs'/('7'*32)/'artifact.json').unlink()
        result=run_manager_plan(self.request)['payload']
        self.assertIsNone(result['rebound_panel_observation']['row_summary']);self.assertIn('daily_channels',result)

    def test_date_guard_preserved_and_caller_now_not_observation_clock(self):
        result=run_manager_plan(dict(self.request,target_date='20261008'))['payload']['rebound_panel_observation']
        self.assertIn('OBSERVATION_MANAGER_DATE_MISMATCH',result['reason_codes']);self.assertIsNone(result['row_summary'])
        result=run_manager_plan(dict(self.request,now='2026-10-09T04:00:00+00:00'))['payload']['rebound_panel_observation']
        self.assertIsNotNone(result['row_summary'])
        self.assertEqual(result['time_basis'],'SERVER_CURRENT_READ_NOT_PLAN_PIT')
        self.assertFalse(result['consumed_by_saved_plan'])

    def current_fixture(self, *, future=False, view='auto'):
        from v5_shadow.manager_panel_observation import current_observation
        artifact=copy.deepcopy(self.artifact)
        observed='2026-10-09T20:53:19+08:00' if not future else '2026-10-09T21:07:00+08:00'
        artifact.update(started_at=observed,observed_at=observed,finished_at='2026-10-09T20:53:20+08:00' if not future else '2026-10-09T21:07:01+08:00')
        artifact['context']['research_cutoff']=observed
        for row in artifact['rows']:row['observed_at']=observed
        before=copy.deepcopy(artifact)
        with patch('v5_shadow.manager_panel_observation.datetime') as clock:
            clock.now.return_value=datetime.fromisoformat('2026-10-09T21:06:00+08:00').astimezone(timezone.utc)
            result=current_observation(artifact,target_date='20261009',market_session='20261008',
                plan_research_cutoff='2026-10-09T18:15:54+08:00',view=view)
        self.assertEqual(artifact,before)
        return result

    def test_1815_plan_2053_observation_2106_server_read_are_separate(self):
        result=self.current_fixture()
        self.assertIsNotNone(result['rows'])
        self.assertEqual(result['observed_at'],'2026-10-09T20:53:19+08:00')
        self.assertEqual(result['plan_research_cutoff'],'2026-10-09T18:15:54+08:00')
        self.assertEqual(result['observation_read_as_of'],'2026-10-09T13:06:00+00:00')
        self.assertFalse(result['consumed_by_saved_plan']);self.assertIsNone(result['eligible_screen'])

    def test_future_observation_rejected_against_real_read_clock(self):
        result=self.current_fixture(future=True)
        self.assertIsNone(result['rows']);self.assertIn('OBSERVATION_MANAGER_AFTER_CUTOFF',result['reason_codes'])

    def test_explicit_historical_view_hides_current_rows(self):
        result=self.current_fixture(view='historical')
        self.assertIsNone(result['rows'])
        self.assertIn('OBSERVATION_CURRENT_READ_HIDDEN_FOR_HISTORICAL_VIEW',result['reason_codes'])

    def test_synthetic_kind_cannot_enter_observation(self):
        self.artifact['run_id']='6'*32;self.artifact['request']['data_kind']='SYNTHETIC'
        self.artifact['request_sha256']=sha256_json(self.artifact['request']);self.artifact['execution_kind']='SYNTHETIC_TEST';self.bind()
        result=run_manager_plan(self.request)['payload']['rebound_panel_observation']
        self.assertIn('OBSERVATION_MANAGER_SYNTHETIC_REJECTED',result['reason_codes']);self.assertIsNone(result['row_summary'])

    def test_refresh_observation_not_saved_with_plan(self):
        result=run_manager_plan(dict(self.request,action='refresh'))
        self.assertEqual(result['readback']['status'],'MATCHED')
        saved=json.loads((self.fixture.output/'workspace_plans/20261009'/f"{result['readback']['run_id']}.json").read_bytes())
        self.assertNotIn('rebound_panel_observation',saved['workspace'])
        self.assertIn('rebound_panel_observation',result['payload'])

    def test_root_overlap_and_reference_sha_rejected(self):
        for root in (self.fixture.output,Path(self.request['inputs']['materials']['root'])):
            value=copy.deepcopy(self.request);value['rebound_observation']['root']=str(root)
            with self.assertRaisesRegex(ValueError,'MANAGER_PANEL_OBSERVATION_ROOT_OVERLAP'):run_manager_plan(value)
        value=copy.deepcopy(self.request);value['rebound_observation']['reference']['artifact_sha256']='not-sha'
        with self.assertRaises(ValueError):run_manager_plan(value)

    def test_full_695_rows_summarized_without_raising_workspace_budget(self):
        from v5_shadow.manager_panel_observation import summarize
        from v5_shadow.api_gateway import _parse_response
        from v5_shadow.digests import canonical_bytes
        rows=[dict(self.artifact['rows'][0],code='HK.'+str(i).zfill(5)) for i in range(695)]
        observation=owner.manager_observation(self.artifact,target_date='20261009',market_session='20261008',research_cutoff=self.request['now'])
        observation['rows']=rows
        summary=summarize(observation)
        self.assertEqual(summary['row_summary']['observed_rows'],695)
        self.assertEqual(summary['row_summary']['numeric_input_incomplete'],695)
        self.assertTrue(all(c['unknown']==695 for c in summary['row_summary']['native_comparison_counts'].values()))
        payload={'materials':[{'source_row':{}} for _ in range(84000)],'rebound_panel_observation':summary}
        _parse_response(canonical_bytes(payload),manager_workspace=True)
        self.assertIsNone(summary['eligible_screen'])

    def test_same_saved_panel_is_hidden_on_next_calendar_day(self):
        with synthetic_worker_clock({'manager_plan':'2026-10-10T13:06:00+00:00'}):
            result=run_manager_plan(self.request)['payload']['rebound_panel_observation']
        self.assertIsNone(result['row_summary'])
        self.assertIn('OBSERVATION_CURRENT_READ_HIDDEN_FOR_HISTORICAL_VIEW',result['reason_codes'])
