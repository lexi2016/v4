"""Observe exactly the owner's requested calls; fixtures never contact an SDK."""
import json
import unittest
from unittest.mock import patch
from v5_shadow.digests import sha256_json
from v5_shadow.provider_evidence import encode_sdk_value

class Frame:
    def __init__(self,rows):self.rows=rows
    def to_dict(self,orient):
        assert orient=='records'
        return self.rows


def row(code):
    return dict(code=code,name='SYNTHETIC',equity_valid=True,stock_owner=float('nan'),
                lot_size=100,listing_date='2020-01-01',sec_status='NORMAL',
                outstanding_shares=None,circular_market_val=None,stock_child_type=None)

class SnapshotRecordingTests(unittest.TestCase):
    def recorder(self,call):
        from v5_shadow.snapshot_recording import SnapshotRecorder
        return SnapshotRecorder(call,producer_code_sha256='a'*64)
    def test_owner_called_once_original_return_and_full_fields_retained(self):
        calls=[];result=(0,Frame([row('HK.00001')]))
        def owner(codes):calls.append(codes);return result
        recorder=self.recorder(owner);codes=['HK.00001']
        self.assertIs(recorder(codes),result);self.assertIs(calls[0],codes)
        records,receipt=recorder.seal()
        self.assertEqual(len(calls),1);self.assertTrue(records[0]['equity_valid'])
        self.assertEqual(receipt['batches'][0]['codes'],codes)
        self.assertEqual(receipt['batches'][0]['raw_records_sha256'],sha256_json(encode_sdk_value(records)))
        self.assertFalse(receipt['natural_verified']);self.assertFalse(receipt['membership_verified'])
    def test_real_clock_order_and_batch_separation(self):
        recorder=self.recorder(lambda codes:(0,Frame([row(c) for c in codes])))
        times=['2026-10-08T04:00:00+00:00','2026-10-08T04:00:01+00:00',
               '2026-10-08T04:00:02+00:00','2026-10-08T04:00:03+00:00','2026-10-08T04:00:04+00:00']
        with patch('v5_shadow.snapshot_recording._now',side_effect=times):
            recorder(['HK.00001']);recorder(['HK.00002']);records,receipt=recorder.seal()
        self.assertEqual(len(receipt['batches']),2)
        self.assertEqual(receipt['batches'][0]['requested_at'],times[0])
        self.assertEqual(receipt['batches'][1]['completed_at'],times[3])
        self.assertEqual(receipt['available_at'],times[4])
        self.assertEqual(len(records),2)
    def test_mutating_owner_frame_after_return_does_not_change_recorded_values(self):
        frame=Frame([row('HK.00001')]);recorder=self.recorder(lambda codes:(0,frame))
        recorder(['HK.00001']);frame.rows[0]['name']='CHANGED'
        records,receipt=recorder.seal();self.assertEqual(records[0]['name'],'SYNTHETIC')
    def test_provider_error_return_is_unchanged_and_cannot_seal(self):
        response=(-1,'failure');calls=[]
        recorder=self.recorder(lambda codes:(calls.append(codes) or response))
        self.assertIs(recorder(['HK.00001']),response)
        with self.assertRaisesRegex(ValueError,'CAPTURE_INCOMPLETE'):recorder.seal()
        self.assertEqual(len(calls),1)
    def test_provider_exception_propagates_without_retry(self):
        calls=[];error=RuntimeError('original')
        def owner(codes):calls.append(codes);raise error
        recorder=self.recorder(owner)
        with self.assertRaises(RuntimeError) as result:recorder(['HK.00001'])
        self.assertIs(result.exception,error);self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):recorder.seal()
    def test_wrong_or_repeated_codes_do_not_get_complete_receipt(self):
        for records in ([row('HK.00002')],[row('HK.00001'),row('HK.00001')]):
            result=(0,Frame(records));recorder=self.recorder(lambda codes:result)
            self.assertIs(recorder(['HK.00001']),result)
            with self.assertRaises(ValueError):recorder.seal()
        recorder=self.recorder(lambda codes:(0,Frame([row(c) for c in codes])))
        recorder(['HK.00001']);recorder(['HK.00001'])
        with self.assertRaises(ValueError):recorder.seal()
    def test_raw_row_order_is_bound_to_request_order(self):
        recorder=self.recorder(lambda codes:(0,Frame([row(c) for c in reversed(codes)])))
        recorder(['HK.00001','HK.00002']);records,receipt=recorder.seal()
        self.assertEqual([r['code'] for r in records],['HK.00001','HK.00002'])
        self.assertEqual(receipt['batches'][0]['provider_returned_codes'],['HK.00002','HK.00001'])
    def test_empty_recording_and_reversed_clock_rejected(self):
        recorder=self.recorder(lambda codes:(0,Frame([row(c) for c in codes])))
        with self.assertRaises(ValueError):recorder.seal()
        with patch('v5_shadow.snapshot_recording._now',side_effect=[
                '2026-10-08T04:00:02+00:00','2026-10-08T04:00:01+00:00']):
            recorder(['HK.00001'])
        with self.assertRaises(ValueError):recorder.seal()
    def test_sealed_recorder_refuses_more_calls_and_returns_detached_copy(self):
        calls=[]
        def owner(codes):calls.append(codes);return 0,Frame([row(c) for c in codes])
        recorder=self.recorder(owner);recorder(['HK.00001']);records,receipt=recorder.seal()
        records[0]['name']='MUTATION';receipt['batches'].clear()
        again,receipt2=recorder.seal();self.assertEqual(again[0]['name'],'SYNTHETIC')
        self.assertEqual(len(receipt2['batches']),1)
        with self.assertRaises(ValueError):recorder(['HK.00002'])
        self.assertEqual(len(calls),1)
    def test_full_recording_can_feed_existing_master_preparation(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from v5_shadow.capture_master import MasterBinding,prepare_futu_master
        recorder=self.recorder(lambda codes:(0,Frame([row(c) for c in codes])))
        codes=[f'HK.{i:05}' for i in range(1,601)]
        times=['2026-10-08T04:00:00+00:00','2026-10-08T04:00:01+00:00','2026-10-08T04:00:02+00:00']
        with patch('v5_shadow.snapshot_recording._now',side_effect=times):
            recorder(codes);records,receipt=recorder.seal()
        with TemporaryDirectory() as temp:
            binding=MasterBinding(Path(temp).resolve(),'20261008','2026-10-08T04:00:03+00:00',tuple(codes),
                                  'b'*64,'a'*64,sha256_json(encode_sdk_value(records)),sha256_json(receipt))
            prepared=prepare_futu_master(records,receipt,binding)
        self.assertEqual(len(json.loads(prepared.payload)['normalized']['rows']),600)

    def test_only_owner_can_retry_and_failed_attempt_stays_visible(self):
        calls=[]
        def owner(codes):
            calls.append(codes)
            return (-1,'temporary') if len(calls)==1 else (0,Frame([row(c) for c in codes]))
        recorder=self.recorder(owner)
        self.assertEqual(recorder(['HK.00001'])[0],-1);self.assertEqual(len(calls),1)
        recorder(['HK.00001']);records,receipt=recorder.seal()
        self.assertEqual(len(calls),2);self.assertEqual(len(records),1)
        self.assertEqual([a['status'] for a in receipt['attempts']],['PROVIDER_ERROR','RECORDED'])

    def test_unsupported_iterator_not_consumed_before_owner(self):
        seen=[]
        def codes():
            seen.append('yield');yield 'HK.00001'
        supplied=codes();observed=[]
        def owner(value):observed.extend(value);return 0,Frame([row(c) for c in observed])
        recorder=self.recorder(owner);recorder(supplied)
        self.assertEqual(observed,['HK.00001']);self.assertEqual(seen,['yield'])
        with self.assertRaises(ValueError):recorder.seal()
    def test_exception_clock_failure_cannot_be_hidden_by_retry(self):
        calls=[];error=RuntimeError('original')
        def owner(codes):
            calls.append(codes)
            if len(calls)==1:raise error
            return 0,Frame([row(c) for c in codes])
        recorder=self.recorder(owner)
        with patch('v5_shadow.snapshot_recording._now',side_effect=[
                '2026-10-08T04:00:02+00:00','2026-10-08T04:00:01+00:00']):
            with self.assertRaises(RuntimeError) as caught:recorder(['HK.00001'])
        self.assertIs(caught.exception,error)
        recorder(['HK.00001'])
        with self.assertRaisesRegex(ValueError,'CAPTURE_INCOMPLETE'):recorder.seal()

    def test_error_after_success_is_not_hidden_by_old_coverage(self):
        for use_exception in (False,True):
            calls=[]
            def owner(codes):
                calls.append(codes)
                if len(calls)==1:return 0,Frame([row(c) for c in codes])
                if use_exception:raise RuntimeError('failed new attempt')
                return -1,'failure'
            recorder=self.recorder(owner);recorder(['HK.00001'])
            if use_exception:
                with self.assertRaises(RuntimeError):recorder(['HK.00001'])
            else:recorder(['HK.00001'])
            with self.assertRaises(ValueError):recorder.seal()
            self.assertEqual(len(calls),2)
    def test_attempt_limit_preserves_owner_call_but_blocks_seal(self):
        calls=[];response=(0,Frame([row('HK.00001')]))
        recorder=self.recorder(lambda codes:(calls.append(codes) or response))
        recorder._attempts=[{} for _ in range(10000)]
        self.assertIs(recorder(['HK.00001']),response);self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):recorder.seal()
    def test_keyword_arguments_pass_through_unchanged(self):
        calls=[]
        def owner(*,code_list,extra):
            calls.append((code_list,extra));return 0,Frame([row(c) for c in code_list])
        codes=['HK.00001'];recorder=self.recorder(owner)
        recorder(code_list=codes,extra='SAME')
        self.assertIs(calls[0][0],codes);self.assertEqual(calls[0][1],'SAME')
        records,_=recorder.seal();self.assertEqual(len(records),1)

    def test_failed_attempt_cannot_finish_after_seal_clock(self):
        calls=[]
        def owner(codes):
            calls.append(codes)
            return (-1,'temporary') if len(calls)==1 else (0,Frame([row(c) for c in codes]))
        recorder=self.recorder(owner)
        times=['2026-10-08T04:00:00+00:00','2026-10-08T04:00:10+00:00',
               '2026-10-08T04:00:02+00:00','2026-10-08T04:00:03+00:00','2026-10-08T04:00:04+00:00']
        with patch('v5_shadow.snapshot_recording._now',side_effect=times):
            recorder(['HK.00001']);recorder(['HK.00001'])
            with self.assertRaisesRegex(ValueError,'CAPTURE_CLOCK_INVALID'):recorder.seal()

if __name__=='__main__':unittest.main()
