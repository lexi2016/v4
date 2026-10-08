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
        data=json.loads(self.prepare().payload)
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
        from dataclasses import replace
        self.receipt['producer_code_sha256']='c'*64
        original=self.binding
        self.binding=replace(self.binding,snapshot_receipt_sha256=sha256_json(self.receipt))
        with self.assertRaisesRegex(ValueError,'SOURCE_NOT_ADMITTED'):self.prepare()
        self.binding=original
        self.records,self.receipt=fixture();self.records[0]['name']='changed'
        with self.assertRaisesRegex(ValueError,'SOURCE_NOT_ADMITTED'):self.prepare()
    def test_missing_extra_duplicate_codes_rejected(self):
        from dataclasses import replace
        from v5_shadow.capture_master import prepare_futu_master
        for altered in (self.records[:-1],self.records+[self.records[0]]):
            binding=replace(self.binding,raw_records_sha256=sha256_json(encode_sdk_value(altered)))
            with self.assertRaisesRegex(ValueError,'MEMBERSHIP_CODES_MISMATCH'):
                prepare_futu_master(altered,self.receipt,binding)
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
        (self.root/'.v5-master-root').write_text('v5.master-root.v1\n')
        link=self.root.parent/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):publish_futu_master(data,replace(self.binding,root=link))
    def test_reference_identity_mismatch_rejected(self):
        from v5_shadow.capture_master import publish_futu_master,read_futu_master
        ref=publish_futu_master(self.prepare(),self.binding);ref['receipt_sha256']='d'*64
        with self.assertRaises(ValueError):read_futu_master(ref,self.binding)

    def test_multiple_batches_use_their_own_raw_and_latest_time(self):
        from dataclasses import replace
        from v5_shadow.capture_master import prepare_futu_master
        first=copy.deepcopy(self.receipt['batches'][0]);second=copy.deepcopy(first)
        first['codes']=[r['code'] for r in self.records[:300]]
        first['raw_records_sha256']=sha256_json(encode_sdk_value(self.records[:300]))
        second['codes']=[r['code'] for r in self.records[300:]]
        second['raw_records_sha256']=sha256_json(encode_sdk_value(self.records[300:]))
        second['completed_at']='2026-10-08T12:00:30+08:00'
        self.receipt['batches']=[first,second]
        binding=replace(self.binding,snapshot_receipt_sha256=sha256_json(self.receipt))
        prepared=json.loads(prepare_futu_master(self.records,self.receipt,binding).payload)
        self.assertEqual(prepared['normalized']['captured_at'],second['completed_at'])
        second['raw_records_sha256']=first['raw_records_sha256']
        binding=replace(binding,snapshot_receipt_sha256=sha256_json(self.receipt))
        with self.assertRaisesRegex(ValueError,'BATCH_RECORDS_MISMATCH'):
            prepare_futu_master(self.records,self.receipt,binding)
    def test_batch_duplicate_or_available_before_completion_rejected(self):
        from dataclasses import replace
        from v5_shadow.capture_master import prepare_futu_master
        for variant in ('duplicate','early'):
            receipt=copy.deepcopy(self.receipt)
            if variant=='duplicate':receipt['batches']*=2
            else:receipt['available_at']='2026-10-08T12:00:00+08:00'
            binding=replace(self.binding,snapshot_receipt_sha256=sha256_json(receipt))
            with self.assertRaises(ValueError):prepare_futu_master(self.records,receipt,binding)
    def test_modified_prepared_semantics_rejected_before_write(self):
        from v5_shadow.capture_master import publish_futu_master
        from v5_shadow.digests import canonical_bytes
        from dataclasses import replace
        prepared=self.prepare();data=json.loads(prepared.payload);data['normalized']['rows'][0]['name']='TAMPERED'
        data['normalized']['sha256']=sha256_json({k:v for k,v in data['normalized'].items() if k!='sha256'})
        with self.assertRaises(ValueError):publish_futu_master(replace(prepared,payload=canonical_bytes(data)),self.binding)
    def test_writer_failure_does_not_replace_preexisting_generation(self):
        from v5_shadow import capture_master as module
        prepared=self.prepare();first=module.publish_futu_master(prepared,self.binding)
        with patch.object(module,'_load_legacy',side_effect=ValueError('CAPSULE_CORRUPT')):
            with self.assertRaises(ValueError):module.publish_futu_master(prepared,self.binding)
        self.assertEqual(module.read_futu_master(first,self.binding)['rows']['HK.00001']['name'],'SYNTHETIC 1')

    def test_protected_root_and_internal_symlinks_rejected(self):
        from dataclasses import replace
        from v5_shadow.capture_master import prepare_futu_master,publish_futu_master
        with self.assertRaisesRegex(ValueError,'SOURCE_OUTPUT_OVERLAP'):
            prepare_futu_master(self.records,self.receipt,replace(self.binding,protected_roots=(self.root.parent,)))
        outside=self.root.parent/'outside';outside.mkdir()
        for index,part in enumerate(('generations','.master.lock')):
            # Each negative owns a fresh root: the first failure legitimately
            # creates its regular lock before rejecting the generations link.
            case=self.root/f'case-{index}';case.mkdir()
            (case/'.v5-master-root').write_text('v5.master-root.v1\n')
            binding=replace(self.binding,root=case)
            path=case/part;path.symlink_to(outside,target_is_directory=True)
            prepared=prepare_futu_master(self.records,self.receipt,binding)
            with self.assertRaises(ValueError):publish_futu_master(prepared,binding)
            self.assertTrue(path.is_symlink())
    def test_pre_rename_failure_is_invisible_and_retry_recovers(self):
        from v5_shadow import capture_master as module
        prepared=self.prepare()
        with patch.object(module.os,'rename',side_effect=OSError('INJECTED_RENAME')):
            with self.assertRaises(OSError):module.publish_futu_master(prepared,self.binding)
        self.assertFalse(list((self.root/'generations').iterdir()))
        ref=module.publish_futu_master(prepared,self.binding)
        self.assertEqual(len(module.read_futu_master(ref,self.binding)['rows']),600)

    def test_commit_only_corruption_is_not_adopted_on_retry(self):
        from v5_shadow.capture_master import publish_futu_master,read_futu_master
        data=self.prepare();ref=publish_futu_master(data,self.binding)
        path=self.root/'generations'/ref['generation_id']/'COMMIT.json'
        receipt=json.loads(path.read_text());receipt['natural_verified']=True
        path.write_text(json.dumps(receipt))
        for action in (lambda:read_futu_master(ref,self.binding),lambda:publish_futu_master(data,self.binding)):
            with self.assertRaises(ValueError):action()
    def test_missing_committed_reference_is_not_silently_reconstructed(self):
        from v5_shadow.capture_master import publish_futu_master
        data=self.prepare();ref=publish_futu_master(data,self.binding)
        (self.root/'references'/(ref['generation_id']+'.json')).unlink()
        with self.assertRaisesRegex(ValueError,'GENERATION_COMMIT_INCOMPLETE'):
            publish_futu_master(data,self.binding)

    def test_copied_capability_and_changed_code_identity_rejected(self):
        from dataclasses import replace
        from v5_shadow import capture_master as module
        prepared=self.prepare()
        with self.assertRaisesRegex(ValueError,'PREPARED_NOT_ADMITTED'):
            module.publish_futu_master(replace(prepared),self.binding)
        with patch.object(module,'_implementation_identity',return_value={'changed':True}):
            with self.assertRaisesRegex(ValueError,'IMPLEMENTATION_IDENTITY_MISMATCH'):
                module.publish_futu_master(prepared,self.binding)
    def test_resealed_legacy_policy_mismatch_rejected(self):
        from v5_shadow import capture_master as module
        from v5_shadow.digests import canonical_bytes
        prepared=self.prepare();ref=module.publish_futu_master(prepared,self.binding)
        gen=self.root/'generations'/ref['generation_id']
        path=next(gen.rglob('manifest.json'));manifest=json.loads(path.read_text())
        manifest['stage_valuation_policy']='UNSAFE_OTHER_POLICY';path.write_bytes(canonical_bytes(manifest))
        legacy_receipt=path.parent/'receipt.json';r=json.loads(legacy_receipt.read_text())
        r['manifest_sha256']=sha256_json(manifest);legacy_receipt.write_bytes(canonical_bytes(r))
        commit=gen/'COMMIT.json';r=json.loads(commit.read_text());r['files']=module._files(gen)
        commit.write_bytes(canonical_bytes(r));ref['receipt_sha256']=sha256_json(r)
        with self.assertRaisesRegex(ValueError,'LEGACY_METADATA_MISMATCH'):
            module.read_futu_master(ref,self.binding)

if __name__=='__main__':unittest.main()
