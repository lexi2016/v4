import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import issue35_canary as c

HK = ZoneInfo('Asia/Hong_Kong')
D = '20261012'
PUB = '20261009'
HASH = 'a' * 64
RUN = 'a' * 32
FLAGS = {'RESEARCH_ONLY': True, 'production_allowed': False,
         'buy_gate_updated': False, 'orders_sent': False}


def workspace(*, plan_status='CURRENT', us_status='NOT_RUN', with_oversold_run=False):
    return {
        **FLAGS,
        'target_trade_date': D,
        'date_bindings': {'plan_date': D, 'selection_date': D, 'announcement_date': PUB},
        'plan_product': {'status': plan_status, 'consumed': plan_status == 'CURRENT',
                         'run_id': RUN, 'sha256': HASH},
        'daily_channels': {'channels': [
            {'channel': 'ANNOUNCEMENT', 'status': 'CANNOT_CONFIRM', 'candidate_count': None,
             'rows': [], 'gaps': ['ANNOUNCEMENT_EXACT_DATE_PRODUCT_NOT_CONSUMED']},
            {'channel': 'OVERSOLD', 'status': 'PARTIAL', 'candidate_count': 214,
             'run_id': RUN if with_oversold_run else None,
             'product_sha256': HASH if with_oversold_run else None,
             'rows': [{'symbol': 'HK.00175', 'name': '吉利汽车',
                       'reason': 'research only', 'selection_status': 'SELECTED'}],
             'gaps': ['REBOUND_HISTORY_VOLUME_UNIT_NOT_PROVEN']},
            {'channel': 'HK_CONNECT', 'status': 'CANNOT_CONFIRM', 'candidate_count': None,
             'rows': [], 'gaps': ['HK_ORIGINAL_STAGE_DATE_OR_MARKET_MISMATCH']}
        ]},
        'us_market_attention': {'status': 'READY', 'expected_us_session': PUB,
                                'raw_industry_up': [{}] * 18,
                                'raw_individual_up': [{}] * 23},
        'us_mapping_research': {'daily_run': {'status': us_status,
            'run_id': RUN if us_status == 'COMPLETED' else None,
            'artifact_sha256': HASH if us_status == 'COMPLETED' else None,
            'matches': [{'us_symbol': 'NVDA', 'hk_symbol': 'HK.01234'}] if us_status == 'COMPLETED' else []}}
    }


class Issue35CanaryTests(unittest.TestCase):
    def test_raw_us_ready_is_not_completed_hk_daily_mapping(self):
        got = c.extract_workspace(workspace(), D, PUB)
        self.assertEqual(got['us']['raw_individual_up_count'], 23)
        self.assertEqual(got['us']['daily_run_status'], 'NOT_RUN')
        self.assertFalse(got['us']['verified_daily'])
        self.assertFalse(got['business_complete'])
        self.assertIn('US_DAILY_NOT_VERIFIED', got['blocking_codes'])

    def test_no_run_or_sha_oversold_cannot_be_promoted_to_verified(self):
        got = c.extract_workspace(workspace(), D, PUB)
        self.assertEqual(got['lanes']['OVERSOLD']['visible_rows'], 1)
        self.assertEqual(got['lanes']['OVERSOLD']['candidate_count'], 214)
        self.assertIsNone(got['lanes']['OVERSOLD']['run_id'])
        self.assertFalse(got['lanes']['OVERSOLD']['owner_identity_present'])
        self.assertIn('OVERSOLD_OWNER_IDENTITY_MISSING', got['blocking_codes'])

    def test_missing_counts_remain_null_not_zero(self):
        got = c.extract_workspace(workspace(), D, PUB)
        self.assertIsNone(got['lanes']['ANNOUNCEMENT']['candidate_count'])
        self.assertEqual(got['lanes']['ANNOUNCEMENT']['visible_rows'], 0)
        self.assertEqual(got['lanes']['ANNOUNCEMENT']['status'], 'CANNOT_CONFIRM')

    def test_wrong_explicit_binding_rejected(self):
        broken = workspace()
        broken['date_bindings']['announcement_date'] = '20261008'
        with self.assertRaisesRegex(ValueError, 'BINDINGS_MISMATCH'):
            c.extract_workspace(broken, D, PUB)

    def test_any_unsafe_flag_rejected(self):
        broken = workspace()
        broken['production_allowed'] = True
        with self.assertRaisesRegex(ValueError, 'RESEARCH_ONLY_FLAGS'): 
            c.extract_workspace(broken, D, PUB)

    def test_same_saved_plan_must_stay_current_across_two_auto_reads(self):
        self.assertTrue(c.verify_two_auto(workspace(), workspace(), D, PUB)['stable'])
        self.assertFalse(c.verify_two_auto(workspace(), workspace(plan_status='STALE_INPUTS_CHANGED'), D, PUB)['stable'])
        other = workspace()
        other['plan_product']['sha256'] = 'b' * 64
        self.assertFalse(c.verify_two_auto(workspace(), other, D, PUB)['stable'])

    def test_future_us_owner_is_not_dispatched_in_advance(self):
        now = datetime(2026, 10, 11, 22, 0, tzinfo=HK)
        with self.assertRaisesRegex(ValueError, 'US_MAPPING_FUTURE_TARGET_NOT_ELIGIBLE'):
            c.ensure_us_due(D, now)
        c.ensure_us_due(D, datetime(2026, 10, 12, 9, 0, tzinfo=HK))

    def test_import_only_registered_reference_envelope(self):
        ref = {'schema_version': 'v4.manager_research.announcement_analysis_import_ref.v1',
               'evidence_run_id': RUN, 'handoff_manifest_sha256': HASH,
               'product_sha256': HASH}
        self.assertEqual(c.validate_import_ref(ref), ref)
        with self.assertRaisesRegex(ValueError, 'IMPORT_REF_INVALID'):
            c.validate_import_ref({**ref, 'stocks': [{'symbol': 'HK.00001'}]})

    def test_only_explicit_local_8873_origin(self):
        self.assertEqual(c.local_origin('http://127.0.0.1:8873'), 'http://127.0.0.1:8873')
        for bad in ['https://127.0.0.1:8873', 'http://evil.com:8873',
                    'http://localhost:8000', 'http://user:pass@localhost:8873']:
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'ORIGIN_INVALID'):
                c.local_origin(bad)

if __name__ == '__main__':
    unittest.main()
