"""Real master adapter contract exercised with fixtures only in temp directories."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from v5_shadow.digests import sha256_json
from v5_shadow.provider_evidence import encode_sdk_value


def fixture():
    records=[dict(code=f'HK.{i:05}',name=f'SYNTHETIC {i}',stock_type='STOCK',
                  listing_date='2020-01-01',sec_status='NORMAL',lot_size=100,
                  outstanding_shares=float('nan'),circular_market_val=None,
                  stock_owner=None,stock_child_type=None) for i in range(1,601)]
    raw_hash=sha256_json(encode_sdk_value(records))
    receipt=dict(schema_version='v5.futu_snapshot_receipt.v1',
                 source_kind='FUTU_OPEND_MARKET_SNAPSHOT',producer_code_sha256='a'*64,
                 available_at='2026-10-08T12:01:00+08:00',batches=[dict(
                     requested_at='2026-10-08T12:00:00+08:00',
                     completed_at='2026-10-08T12:00:01+08:00',
                     codes=[r['code'] for r in records],raw_records_sha256=raw_hash)])
    return records,receipt


class CaptureMasterTests(unittest.TestCase):
    def setUp(self):
        from v5_shadow.capture_master import MasterBinding
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()/'private';self.root.mkdir()
        (self.root/'.v5-master-root').write_text('v5.master-root.v1\n')
        self.records,self.receipt=fixture()
        self.binding=MasterBinding(self.root,'20261008','2026-10-08T12:02:00+08:00',
            tuple(r['code'] for r in self.records),'b'*64,'a'*64,
            sha256_json(encode_sdk_value(self.records)),sha256_json(self.receipt))
    def prepare(self):
        from v5_shadow.capture_master import prepare_futu_master
        return prepare_futu_master(self.records,self.receipt,self.binding)
    def test_prepare_preserves_unknown_and_actual_snapshot_time(self):
        data=json.loads(self.prepare())
        self.assertEqual(data['normalized']['captured_at'],'2026-10-08T12:00:01+08:00')
        self.assertIsNone(data['normalized']['rows'][0]['outstanding_shares'])
        self.assertFalse(data['natural_verified']);self.assertFalse(data['formal_eligibility_verified'])
    def test_real_writer_reader_roundtrip_and_idempotency(self):
        from v5_shadow.capture_master import publish_futu_master,read_futu_master
        prepared=self.prepare()
        with patch('socket.socket',side_effect=AssertionError('NO_NETWORK')):
            reference=publish_futu_master(prepared,self.binding)
            value=read_futu_master(reference,self.binding)
            again=publish_futu_master(prepared,self.binding)
        self.assertEqual(reference,again);self.assertEqual(len(value['rows']),600)
        self.assertEqual(value['rows']['HK.00001']['outstanding_shares'],'')
        self.assertEqual(value['field_states']['HK.00001']['stock_owner'],'NOT_APPLICABLE')
        self.assertFalse(value['natural_verified'])
    def test_untrusted_receipt_and_raw_change_rejected(self):
        self.receipt['producer_code_sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'SOURCE_NOT_ADMITTED'):self.prepare()
        self.records,self.receipt=fixture();self.records[0]['name']='changed'
        with self.assertRaisesRegex(ValueError,'SOURCE_NOT_ADMITTED'):self.prepare()
    def test_missing_extra_duplicate_codes_rejected(self):
        for altered in (self.records[:-1],self.records+[self.records[0]]):
            from v5_shadow.capture_master import prepare_futu_master
            with self.assertRaises(ValueError):prepare_futu_master(altered,self.receipt,self.binding)
    def test_new_snapshot_cannot_be_relabelled_old_date(self):
        from dataclasses import replace
        from v5_shadow.capture_master import prepare_futu_master
        with self.assertRaisesRegex(ValueError,'SNAPSHOT_DATE_MISMATCH'):
            prepare_futu_master(self.records,self.receipt,replace(self.binding,trade_date='20261007'))
    def test_cutoff_and_naive_clock_rejected(self):
        from dataclasses import replace
        from v5_shadow.capture_master import prepare_futu_master
        for cutoff in ('2026-10-08T11:59:00+08:00','2026-10-08T12:02:00'):
            with self.assertRaises(ValueError):prepare_futu_master(self.records,self.receipt,replace(self.binding,cutoff=cutoff))
    def test_binding_requires_full_minimum_universe(self):
        from dataclasses import replace
        from v5_shadow.capture_master import prepare_futu_master
        with self.assertRaisesRegex(ValueError,'MEMBERSHIP_SCOPE_INVALID'):
            prepare_futu_master(self.records,self.receipt,replace(self.binding,codes=self.binding.codes[:3]))
    def test_invalid_field_rejected_even_with_matching_hashes(self):
        from dataclasses import replace
        from v5_shadow.capture_master import prepare_futu_master
        self.records[0]['lot_size']=-1
        h=sha256_json(encode_sdk_value(self.records));self.receipt['batches'][0]['raw_records_sha256']=h
        binding=replace(self.binding,raw_records_sha256=h,snapshot_receipt_sha256=sha256_json(self.receipt))
        with self.assertRaisesRegex(ValueError,'MASTER_FIELDS_INVALID'):
            prepare_futu_master(self.records,self.receipt,binding)
    def test_corruption_is_not_overwritten_on_retry(self):
        from v5_shadow.capture_master import publish_futu_master,read_futu_master
        data=self.prepare();ref=publish_futu_master(data,self.binding)
        gen=self.root/'generations'/ref['generation_id']
        artifact=next(gen.rglob('artifact.csv'));artifact.write_text('corrupted')
        for action in (lambda:read_futu_master(ref,self.binding),lambda:publish_futu_master(data,self.binding)):
            with self.assertRaises(ValueError):action()
        self.assertEqual(artifact.read_text(),'corrupted')
    def test_failure_before_commit_leaves_no_visible_generation(self):
        from v5_shadow import capture_master as module
        data=self.prepare()
        with patch.object(module,'_verify_legacy_rows',side_effect=ValueError('INJECTED')):
            with self.assertRaisesRegex(ValueError,'INJECTED'):module.publish_futu_master(data,self.binding)
        self.assertFalse((self.root/'generations').exists() and list((self.root/'generations').iterdir()))
        self.assertTrue(list(self.root.glob('.pending-*')))
    def test_root_marker_and_symlink_rejected(self):
        from dataclasses import replace
        from v5_shadow.capture_master import publish_futu_master
        data=self.prepare();(self.root/'.v5-master-root').unlink()
        with self.assertRaises(ValueError):publish_futu_master(data,self.binding)
        link=self.root.parent/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):publish_futu_master(data,replace(self.binding,root=link))
    def test_reference_identity_mismatch_rejected(self):
        from v5_shadow.capture_master import publish_futu_master,read_futu_master
        ref=publish_futu_master(self.prepare(),self.binding);ref['receipt_sha256']='d'*64
        with self.assertRaises(ValueError):read_futu_master(ref,self.binding)

if __name__=='__main__':unittest.main()
