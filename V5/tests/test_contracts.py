import copy
import unittest
from v5_shadow.contracts import parse_manifest, parse_request, SafetyFlags
from v5_shadow.digests import canonical_bytes, sha256_json

def manifest(release='r1'):
    return dict(schema_version='v5.module.v1',module_id='rebound_shadow',release_id=release,
        code_manifest_sha256='a'*64,python_version='3.14',dependency_lock_sha256='b'*64,
        capabilities=['rebound.two_gate.v1'],requires=[],input_contracts=['hk02.panel.v1'],
        output_contract='v5.rebound_shadow.v1',entrypoint='v5_shadow.worker:worker_main',
        safety=dict(research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False))

def request():
    return dict(request_id='req1', target_trade_date='20261008',research_cutoff='2026-10-08T08:00:00+08:00',
        requested_at='2026-10-08T08:01:00+08:00',execution_kind='SHADOW_MANUAL',data_kind='SYNTHETIC',
        composition_sha256='c'*64,input_snapshot_sha256=None)

class ContractsTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_manifest(manifest()).module_id,'rebound_shadow')
        self.assertEqual(parse_request(request()).target_trade_date,'20261008')
    def test_each_unsafe_flag(self):
        for key in manifest()['safety']:
            value=manifest();value['safety'][key]=not value['safety'][key]
            with self.subTest(key=key),self.assertRaises(ValueError):parse_manifest(value)
    def test_integer_not_boolean(self):
        value=manifest();value['safety']['orders_sent']=0
        with self.assertRaises(ValueError):parse_manifest(value)
    def test_naive_invalid_date_unknown_fields(self):
        for field,value in [('research_cutoff','2026-10-08T08:00:00'),('target_trade_date','20260230'),('execution_kind','NATURAL'),('data_kind','TRUST_ME'),('unexpected',1),('composition_sha256','A'*64)]:
            data=request();data[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):parse_request(data)
    def test_history_requires_replay(self):
        data=request();data['research_cutoff']='2026-10-07T08:00:00+08:00'
        with self.assertRaises(ValueError):parse_request(data)
        data['execution_kind']='SHADOW_REPLAY'
        self.assertEqual(parse_request(data).research_cutoff.day,7)
    def test_future_cutoff_rejected(self):
        data=request();data['research_cutoff']='2026-10-08T10:00:00+08:00'
        with self.assertRaises(ValueError):parse_request(data)
    def test_json_strict(self):
        for value in [float('nan'),float('inf'),float('-inf')]:
            with self.assertRaises(ValueError):canonical_bytes({'v':value})
        self.assertEqual(canonical_bytes({'b':2,'a':'中'}),'{"a":"中","b":2}'.encode())
        self.assertEqual(sha256_json({'a':1,'b':2}),sha256_json({'b':2,'a':1}))
    def test_manifest_rejects_untrusted_entrypoint(self):
        value=manifest();value['entrypoint']='os:system'
        with self.assertRaises(ValueError):parse_manifest(value)
    def test_unknown_manifest(self):
        value=manifest();value['schema_version']='v9.module.v1'
        with self.assertRaises(ValueError):parse_manifest(value)
if __name__=='__main__':unittest.main()
