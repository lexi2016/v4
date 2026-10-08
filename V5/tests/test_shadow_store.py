import copy,json,tempfile,unittest
from datetime import datetime,timezone
from dataclasses import replace
from pathlib import Path
from test_contracts import request
from v5_shadow.contracts import RuntimeIdentity,parse_request
from v5_shadow.legacy_adapter import build_shadow_result
from v5_shadow.shadow_store import idempotency_key,publish_shadow,read_shadow

def result():
    value=request();value['input_snapshot_sha256']='f'*64
    req=parse_request(value)
    runtime=RuntimeIdentity('rebound_shadow','r1','a'*64,'3.14.7','b'*64,'c'*64,'e'*64,datetime.now(timezone.utc))
    raw=dict(schema_version='v4.manager_research.rebound_v3_screen.v1',rule_version='20260923_REBOUND_TWO_GATE_V1',target_trade_date='20261008',status='READY',main_screen_ready=True,input_identity='a'*64,authority={'source':'SYNTHETIC'},coverage=dict(input_candidate_count=1,row_accounted_count=1,history_pending_count=0,screen_unresolved_count=0,strict_count=0,near_count=0,excluded_count=1),strict=[],near=[],excluded=[{'code':'HK.00001'}],pending=[],screen_unresolved=[],gaps=[])
    start=datetime.now(timezone.utc)
    return build_shadow_result(req,runtime,raw,start,datetime.now(timezone.utc))

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'.v5-shadow-root').write_text('v5.shadow-root.v1\n')
    def test_round_trip(self):
        data=result();ref=publish_shadow(self.root,data)
        self.assertEqual(read_shadow(self.root,ref),data)
    def test_idempotency_ignores_request_clock_and_siblings(self):
        one=result();two=replace(one,run_id='b'*32,request=replace(one.request,request_id='other',composition_sha256='d'*64),finished_at=datetime.now(timezone.utc))
        self.assertEqual(idempotency_key(one.request,one.runtime),idempotency_key(two.request,two.runtime))
        self.assertEqual(publish_shadow(self.root,one),publish_shadow(self.root,two))
    def test_new_input_is_new_run(self):
        one=result();two=replace(result(),request=replace(one.request,input_snapshot_sha256='0'*64))
        self.assertNotEqual(publish_shadow(self.root,one),publish_shadow(self.root,two))
    def test_corrupt_read_rejected(self):
        data=result();ref=publish_shadow(self.root,data)
        path=self.root/'runs'/'20261008'/ref.run_id/'artifact.json';path.write_text('{}')
        with self.assertRaises(ValueError):read_shadow(self.root,ref)
    def test_incomplete_run_never_indexed(self):
        from unittest.mock import patch
        import v5_shadow.shadow_store as store
        original=store.atomic_bytes
        def crash(path,payload):
            if path.name=='manifest.json':raise OSError('SYNTHETIC_CRASH')
            return original(path,payload)
        with patch.object(store,'atomic_bytes',side_effect=crash),self.assertRaises(OSError):publish_shadow(self.root,result())
        self.assertFalse(list((self.root/'index').glob('*.json')))
        other=result();ref=publish_shadow(self.root,other)
        self.assertEqual(read_shadow(self.root,ref),other)
    def test_symlink_output_rejected(self):
        (self.root/'runs').symlink_to('/tmp')
        with self.assertRaises(ValueError):publish_shadow(self.root,result())
    def test_failure_does_not_overwrite_success(self):
        good=result();ref=publish_shadow(self.root,good)
        bad=replace(result(),business_status='CANNOT_CONFIRM',evaluated_count=None,request=replace(good.request,input_snapshot_sha256=None))
        failure_ref=publish_shadow(self.root,bad)
        self.assertNotEqual(ref.run_id,failure_ref.run_id)
        self.assertEqual(read_shadow(self.root,ref),good)
    def test_natural_or_live_safety_refused(self):
        data=replace(result(),natural_verified=True)
        with self.assertRaises(ValueError):publish_shadow(self.root,data)
if __name__=='__main__':unittest.main()
