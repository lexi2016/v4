"""Synthetic private membership -> original v2 reader -> original manager scope."""
from datetime import datetime,timezone,timedelta
import copy
import json
from pathlib import Path
import unittest
import test_hk_membership_recovery as fixtures
from v5_shadow.manager_plan import run_manager_plan
from v5_shadow.membership_reader import OWNER_SHA
from unittest.mock import patch
from synthetic_worker_clock import synthetic_worker_clock, clock_at

class ManagerMembershipTests(unittest.TestCase):
    def setUp(self):
        # Fixed synthetic trading day, not today's possibly closed HK session.
        self.enterContext(synthetic_worker_clock({'hk_membership_recovery':'2026-10-09T07:00:00+00:00'}))
        self.enterContext(patch.object(fixtures,'datetime',clock_at('2026-10-09T06:59:00+00:00')))
        fixture=fixtures.MembershipRecoveryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;published=fixture.run_value();self.published=published
        inputs={}
        for name in ('manager','materials','us'):
            path=fixture.root/name;path.mkdir();inputs[name]=dict(root=str(path),files={})
        output=fixture.root/'plans';output.mkdir();(output/'.v5-manager-plan-root').write_text('v5.manager-plan-root.v1\n')
        self.request=dict(target_date=fixture.day,now='2026-10-09T07:01:00+00:00',action='read',view='dynamic',selection_date=None,announcement_date=None,inputs=inputs,rebound=None,manager_output_root=str(output),membership=dict(root=str(fixture.output),files=published['files'],authority_owner_sha256=OWNER_SHA,require_v2=True))

    def test_698_bound_members_reach_original_scope_without_binding_master(self):
        result=run_manager_plan(self.request)
        self.assertEqual(len(result['membership_readback']['codes']),698)
        self.assertIn('TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2',json.dumps(result['payload']))
        self.assertNotIn('HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND',json.dumps(result['payload']))
        self.assertIn('SCREEN_AUTHORITY_ROOT_NOT_BOUND',json.dumps(result['payload']))
        self.assertFalse(result['natural_verified'])

    def test_qualification_published_after_cutoff_remains_unverified(self):
        self.request['now']=self.published['readback']['source']['acquired_at']
        result=run_manager_plan(self.request)
        self.assertIn('HK_CONNECT_TARGET_AUTHORITY_AFTER_CUTOFF_OR_WRONG_DATE',json.dumps(result['payload']))

    def test_bad_artifact_sha_is_an_explicit_missing_scope_not_global_lane_failure(self):
        name=next(n for n in self.request['membership']['files'] if n.endswith('/sdk.capture.json'))
        self.request['membership']['files']=dict(self.request['membership']['files'],**{name:'0'*64})
        result=run_manager_plan(self.request)
        self.assertIn('MANAGER_INPUT_SHA_OR_LIMIT',json.dumps(result))
        self.assertIn('daily_channels',result['payload'])

    def test_wrong_owner_or_v1_switch_rejected(self):
        for field,value in [('authority_owner_sha256','0'*64),('require_v2',False)]:
            request=copy.deepcopy(self.request);request['membership'][field]=value
            with self.assertRaisesRegex(ValueError,'MANAGER_MEMBERSHIP_OWNER_BINDING'):run_manager_plan(request)

    def test_missing_seventh_file_rejected(self):
        self.request['membership']['files']=dict(self.request['membership']['files'])
        self.request['membership']['files'].pop(next(iter(self.request['membership']['files'])))
        with self.assertRaisesRegex(ValueError,'MANAGER_MEMBERSHIP_SEVEN_FILES'):run_manager_plan(self.request)

    def test_refresh_original_same_run_readback_retains_qualification(self):
        self.request['action']='refresh';result=run_manager_plan(self.request)
        self.assertEqual(result['readback']['status'],'MATCHED')
        self.assertIn('TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2',json.dumps(result['payload']))

    def test_closed_target_still_rejected_by_original_plan_gate(self):
        request=copy.deepcopy(self.request);request.pop('membership');request['target_date']='20261010'
        with self.assertRaisesRegex(ValueError,'PLAN_TARGET_NOT_VERIFIED_HK_TRADING_SESSION'):
            run_manager_plan(request)
