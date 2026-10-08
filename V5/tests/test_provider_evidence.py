"""Reference-field normalization never claims membership or invents numbers."""
import json
import math
import unittest
from v5_shadow.digests import sha256_json


def row(**changes):
    data=dict(code='HK.00001',name='SYNTHETIC',stock_type='STOCK',lot_size=100,
              listing_date='2020-01-01',sec_status='NORMAL',stock_owner=float('nan'),
              stock_child_type=None,outstanding_shares=float('nan'),circular_market_val=None)
    data.update(changes);return data

class ProviderEvidenceTests(unittest.TestCase):
    def normalize(self, rows):
        from v5_shadow.provider_evidence import normalize_security_references
        return normalize_security_references(rows,captured_at='2026-10-08T12:00:00+08:00')
    def test_common_stock_owner_not_applicable(self):
        value=self.normalize([row()]);item=value['rows'][0]
        self.assertIsNone(item['stock_owner'])
        self.assertEqual(item['field_status']['stock_owner'],'NOT_APPLICABLE')
        self.assertEqual(item['issues'],[])
        self.assertEqual(value['raw']['records'][0]['stock_owner'],{'$float':'nan'})
        json.dumps(value,allow_nan=False)
    def test_unknown_shares_stay_unknown_not_zero(self):
        item=self.normalize([row()])['rows'][0]
        self.assertIsNone(item['outstanding_shares'])
        self.assertEqual(item['field_status']['outstanding_shares'],'UNKNOWN')
    def test_derivative_requires_owner(self):
        item=self.normalize([row(stock_type='WARRANT')])['rows'][0]
        self.assertIn('STOCK_OWNER_REQUIRED',item['issues'])
    def test_unknown_type_does_not_claim_not_applicable(self):
        data=row();data.pop('stock_type')
        item=self.normalize([data])['rows'][0]
        self.assertIn('SECURITY_TYPE_UNVERIFIED',item['issues'])
        self.assertNotEqual(item['field_status']['stock_owner'],'NOT_APPLICABLE')
    def test_infinity_is_invalid_not_optional_missing(self):
        item=self.normalize([row(outstanding_shares=float('inf'))])['rows'][0]
        self.assertIn('INVALID_OUTSTANDING_SHARES',item['issues'])
        self.assertEqual(item['field_status']['outstanding_shares'],'INVALID')
    def test_literal_nan_and_tag_not_coerced(self):
        for owner in ('nan',{'$float':'nan'}):
            item=self.normalize([row(stock_owner=owner)])['rows'][0]
            self.assertIn('INVALID_STOCK_OWNER',item['issues'])
    def test_required_lot_and_negative_shares(self):
        item=self.normalize([row(lot_size=None,outstanding_shares=-1)])['rows'][0]
        self.assertIn('INVALID_LOT_SIZE',item['issues'])
        self.assertIn('INVALID_OUTSTANDING_SHARES',item['issues'])
    def test_explicit_snapshot_flag_proves_stock_type(self):
        data=row();data.pop('stock_type');data['equity_valid']=True
        self.assertEqual(self.normalize([data])['rows'][0]['security_type'],'STOCK')
    def test_conflicting_type_flags_rejected(self):
        item=self.normalize([row(wrt_valid=True)])['rows'][0]
        self.assertIn('SECURITY_TYPE_CONFLICT',item['issues'])
    def test_seal_binds_raw_and_normalized_values(self):
        value=self.normalize([row()]);seal=value.pop('sha256')
        self.assertEqual(seal,sha256_json(value))
        self.assertEqual(value['raw_sha256'],sha256_json(value['raw']))
        changed=self.normalize([row(name='SYNTHETIC_CHANGED')])
        self.assertNotEqual(seal,changed['sha256'])
        self.assertFalse(changed['membership_verified'])
    def test_input_untouched_duplicate_and_naive_clock_rejected(self):
        data=row();self.normalize([data]);self.assertTrue(math.isnan(data['stock_owner']))
        with self.assertRaises(ValueError):self.normalize([data,data])
        from v5_shadow.provider_evidence import normalize_security_references
        with self.assertRaises(ValueError):normalize_security_references([data],captured_at='2026-10-08T12:00:00')

if __name__=='__main__':unittest.main()
