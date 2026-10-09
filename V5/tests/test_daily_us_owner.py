import copy
import unittest
from unittest.mock import patch
from v5_shadow.daily_us_owner import run_us_owner, bind_us_owner
from v5_shadow.digests import sha256_json


class DailyUsOwnerTests(unittest.TestCase):
    def result(self, status='VALID_EMPTY'):
        daily=dict(target_trade_date='20261009',run_id='synthetic',status=status,
                   us_session_date='20261008',target_date_eligibility='CANNOT_CONFIRM')
        daily['artifact_sha256']=sha256_json(daily)
        return dict(persisted_daily=daily,payload={'daily_run':copy.deepcopy(daily)},
                    readback_status='MATCHED',execution_kind='MANUAL_RECOVERY')

    def test_existing_owner_called_and_qualification_not_promoted(self):
        request=dict(target_date='20261009',manager_output_root='/synthetic')
        with patch('v5_shadow.daily_us_owner.run_us_mapping',return_value=self.result()) as owner:
            receipt=run_us_owner(request,'ledger-attempt')
        owner.assert_called_once_with(request)
        self.assertEqual(receipt['status'],'SUCCEEDED')
        self.assertFalse(receipt['product_reference']['natural_verified'])
        self.assertEqual(receipt['product_reference']['execution_kind'],'MANUAL_RECOVERY')
        self.assertEqual(receipt['product_reference']['target_date_eligibility'],'CANNOT_CONFIRM')

    def test_missing_source_is_not_success_or_automatic_retry(self):
        with patch('v5_shadow.daily_us_owner.run_us_mapping',return_value=self.result('INPUT_MISSING')):
            receipt=run_us_owner(dict(target_date='20261009',manager_output_root='/synthetic'),'attempt')
        self.assertEqual(receipt['status'],'FAILED');self.assertFalse(receipt['retry_safe_without_external_effect'])

    def test_mismatching_readback_is_rejected(self):
        result=self.result();result['payload']['daily_run']['run_id']='different'
        with patch('v5_shadow.daily_us_owner.run_us_mapping',return_value=result):
            with self.assertRaisesRegex(ValueError,'READBACK'):
                run_us_owner(dict(target_date='20261009'),'attempt')

    def test_binding_is_stable_and_config_changes_identity(self):
        first=bind_us_owner({'enabled':False})
        self.assertEqual(first,bind_us_owner({'enabled':False}))
        self.assertNotEqual(first['config_sha256'],bind_us_owner({'enabled':True})['config_sha256'])
