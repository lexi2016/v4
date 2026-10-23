import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import control_prepare as control


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.claim = dict(run_id='r', business_date='20261023', scheduled_date='20261023', target_date='20261026', slot='1800', mode='LIVE', workload_id='hourly_research')
        self.receipt = dict(self.claim, status='FAILED', finished_at='2026-10-23T10:00:00Z', production_allowed=False, buy_gate_updated=False, orders_sent=False, workload_results=[dict(workload_id='hourly_research', status='SUCCEEDED', production_allowed=False, buy_gate_updated=False, orders_sent=False)])

    def signed(self, receipt):
        value = copy.deepcopy(receipt)
        value['ledger_sha256'] = hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',', ':')).encode()).hexdigest()
        return value

    def test_persisted_success_in_failed_dispatch_is_terminal(self):
        self.assertEqual(control.receipt_state(self.claim,self.signed(self.receipt)), 'TERMINAL_MATCH')

    def test_in_process_claim_without_receipt_blocks(self):
        self.assertEqual(control.receipt_state(self.claim,None), 'ACTIVE_OR_UNCONFIRMED')

    def test_other_run_receipt_blocks(self):
        self.receipt['run_id']='other'
        self.assertEqual(control.receipt_state(self.claim,self.signed(self.receipt)), 'IDENTITY_MISMATCH_STOP')

    def test_invalid_digest_blocks(self):
        receipt=self.signed(self.receipt);receipt['status']='SUCCEEDED'
        self.assertEqual(control.receipt_state(self.claim,receipt), 'INVALID_RECEIPT_STOP')

    def test_workload_missing_from_terminal_receipt_blocks(self):
        self.receipt['workload_results']=[]
        self.assertEqual(control.receipt_state(self.claim,self.signed(self.receipt)), 'WORKLOAD_RESULT_UNCONFIRMED_STOP')

    def test_unsafe_result_blocks(self):
        self.receipt['workload_results'][0]['orders_sent']=True
        self.assertEqual(control.receipt_state(self.claim,self.signed(self.receipt)), 'UNSAFE_WORKLOAD_STOP')

    def test_child_grandchild_detected(self):
        self.assertEqual(control.descendants(10,[(10,1),(11,10),(12,11),(13,1)]),[11,12])

    def test_inventory_byte_mode_symlink_and_rollback_bytes(self):
        h=control.helper()
        with tempfile.TemporaryDirectory(dir=control.OWNER) as folder:
            root=Path(folder); app=root/'app';app.mkdir(); f=app/'source.py';f.write_bytes(b'baseline');(app/'link').symlink_to('source.py')
            before=h['inventory'](app); backup=f.read_bytes(); f.write_bytes(b'candidate')
            self.assertNotEqual(h['inventory'](app),before)
            f.write_bytes(backup); self.assertEqual(h['inventory'](app),before)
            f.chmod(0o600); self.assertNotEqual(h['inventory'](app),before)
            self.assertEqual(before['link']['target'],'source.py')

    def test_reviewed_candidate_drift_rejected(self):
        h=control.helper()
        with tempfile.TemporaryDirectory(dir=control.OWNER) as folder:
            root=Path(folder);app=root/'app';app.mkdir();f=app/'source.py';f.write_bytes(b'accepted')
            packet=dict(independent_review='PASS',candidate_app=str(app),candidate_inventory=h['inventory'](app))
            p=root/'packet.json';p.write_text(json.dumps(packet));f.write_bytes(b'drift')
            with self.assertRaisesRegex(ValueError,'candidate full inventory drift'):
                control.verify_candidate_packet(p)

    def test_reviewed_manifest_drift_rejected(self):
        h=control.helper()
        with tempfile.TemporaryDirectory(dir=control.OWNER) as folder:
            root=Path(folder);app=root/'app';app.mkdir()
            manifest=root/'manifest.json';manifest.write_bytes(b'accepted')
            packet=dict(independent_review='PASS',candidate_app=str(app),candidate_inventory=h['inventory'](app),release_manifest=str(manifest),release_manifest_sha256=control.sha(manifest))
            p=root/'packet.json';p.write_text(json.dumps(packet));manifest.write_bytes(b'drift')
            with self.assertRaisesRegex(ValueError,'release_manifest drift'):
                control.verify_candidate_packet(p)

    def test_prepare_packet_missing_review_rejected(self):
        with tempfile.TemporaryDirectory(dir=control.OWNER) as folder:
            p=Path(folder)/'packet.json';p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'reviewed packet required'):
                control.verify_candidate_packet(p)

if __name__ == '__main__':
    unittest.main()
