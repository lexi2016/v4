"""Synthetic SDK frame fixtures; no quotes, no OpenD or production calls."""
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from v5_shadow.digests import canonical_bytes,sha256_json
from v5_shadow.hk_membership_recovery import run_recovery

class MembershipRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.output=self.root/'output';self.output.mkdir()
        (self.output/'.v5-hk-membership-root').write_text('v5.hk-membership-root.v1\n')
        self.day=datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Hong_Kong')).strftime('%Y%m%d')
        now=datetime.now(timezone.utc).isoformat()
        forward={k:'a'*64 for k in ('forward_receipt_sha256','candidate_manifest_sha256','candidate_build_receipt_sha256','api_writer_receipt_sha256','api_reviewer_receipt_sha256','api_source_mapping_sha256')};forward['source_head']='b'*40
        owner=dict(workload_id='v35_dispatcher.research_panel_daily_hk',code_ref='ops/_macos_research_panel_daily_parts/hk_market_capture.py',code_sha256='0a9651f88bc8a50d4b5e8ec4b6775a5291918f9f2556cf37c05b80a55cdfd84a',forward_source_set=forward,forward_source_set_sha256=sha256_json(forward))
        responses={}
        for plate in ('HK.GangGuTong','HK.LIST1922'):
            material=dict(requested_plate=plate,serialization_version='futu.dataframe.records.canonical-json.v1',columns=['code','stock_owner','stock_child_type'],rows=[{'code':f'HK.{i:05d}','stock_owner':{'$float':'nan'},'stock_child_type':{'$float':'nan'}} for i in range(1,699)])
            responses[plate]=dict(material,return_code=0,requested_at=now,completed_at=now,row_count=698,response_sha256=sha256_json(material))
        self.sdk=dict(schema_version='v4.manager_hk_connect_capture.v2',target_date=self.day,capture_run_id='synthetic-sdk',producer_owner=owner,plate_responses=responses,status='RAW_CAPTURED',production_allowed=False,buy_gate_updated=False,orders_sent=False)
        self.path=self.root/'sdk.json'

    def run_value(self,raw=None):
        raw=canonical_bytes(self.sdk) if raw is None else raw;self.path.write_bytes(raw)
        return run_recovery(dict(sdk_path=str(self.path),sdk_sha256=hashlib.sha256(raw).hexdigest(),output_root=str(self.output),target_date=self.day))

    def test_698_members_preserve_tagged_nan_and_unknown_quote_fields(self):
        result=self.run_value()
        self.assertEqual(result['code_count'],698)
        self.assertEqual(result['readback']['code_count'],698)
        self.assertEqual(result['quote_status'],'NOT_EVALUATED')
        self.assertIsNone(result['price_unit']);self.assertIsNone(result['market_finality'])
        self.assertFalse(result['natural_verified'])
        self.assertIn('HK_UNIVERSE_V2_AVAILABILITY_UNPROVEN_BY_AS_OF',result['prior_cutoff_rejection'])
        capture=json.loads((self.output/result['capture_relative']).read_bytes())
        self.assertEqual(capture['plate_responses'],self.sdk['plate_responses'])
        self.assertNotIn('rows',capture);self.assertNotIn('security_master_rows',capture)
        manifest=json.loads((self.output/result['manifest_relative']).read_bytes())
        self.assertEqual(manifest['origin_claim'],'RECOVERY_FROM_RETAINED_SDK_CAPTURE')
        self.assertNotEqual(manifest['origin_claim'],'SAME_JOB_CAPTURE_AND_PUBLICATION')

    def test_bare_nan_is_rejected_without_global_json_relaxation(self):
        self.sdk['unexpected']=float('nan')
        with self.assertRaisesRegex(ValueError,'NONFINITE_JSON'):self.run_value(json.dumps(self.sdk).encode())
        self.assertEqual(len(list(self.output.iterdir())),1)

    def test_response_sha_mismatch_rejects_membership(self):
        self.sdk['plate_responses']['HK.LIST1922']['response_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'response_sha'):self.run_value()

    def test_missing_or_nonstring_member_code_cannot_become_null_or_zero(self):
        self.sdk['plate_responses']['HK.LIST1922']['rows'][0]['code']=None
        with self.assertRaisesRegex(ValueError,'CODE_INVALID'):self.run_value()

    def test_quote_failure_does_not_become_verified_security_master(self):
        self.sdk['quote_status']='FAILED'
        out=self.run_value()
        self.assertEqual(out['security_master_status'],'NOT_EVALUATED')
        self.assertEqual(out['panel_status'],'NOT_EVALUATED')

    def test_source_hash_mismatch_does_not_publish(self):
        self.path.write_bytes(canonical_bytes(self.sdk))
        with self.assertRaisesRegex(ValueError,'SDK_SHA'):
            run_recovery(dict(sdk_path=str(self.path),sdk_sha256='0'*64,output_root=str(self.output),target_date=self.day))
        self.assertEqual(len(list(self.output.iterdir())),1)
