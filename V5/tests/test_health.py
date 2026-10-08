import unittest
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
from test_contracts import manifest
from v5_shadow.contracts import parse_manifest,Binding,RuntimeIdentity
from v5_shadow.health import evaluate_health,observe_runtime
from v5_shadow.source_capsule import inspect_capsule

class HealthTests(unittest.TestCase):
    def setUp(self):
        self.module=parse_manifest(manifest())
        self.binding=Binding(None,Path('/unused'),'d'*64,'e'*64,'f'*64)
        self.observed=RuntimeIdentity('rebound_shadow','r1','a'*64,'3.14','b'*64,'c'*64,'e'*64,datetime.now(timezone.utc))
    def test_alive_wrong_release(self):
        result=evaluate_health(self.module,self.binding,'c'*64,replace(self.observed,release_id='old'),{'status':'READY','data_kind':'SYNTHETIC'})
        self.assertEqual(result.identity_status,'MISMATCH')
        self.assertIn('RUNTIME_RELEASE_ID_MISMATCH',result.reason_codes)
    def test_identity_not_business(self):
        result=evaluate_health(self.module,self.binding,'c'*64,self.observed,{'status':'MISSING'})
        self.assertEqual(result.identity_status,'MATCH');self.assertEqual(result.input_status,'MISSING')
    def test_unverified_input_cannot_be_ready(self):
        for data in ({'status':'READY'},{'status':'READY','data_kind':'OWNER_VERIFIED'},{'status':'READY','data_kind':'SYNTHETIC'}):
            result=evaluate_health(self.module,self.binding,'c'*64,self.observed,data)
            self.assertEqual(result.input_status,'UNVERIFIED')
    def test_unknown_is_not_ready(self):
        result=evaluate_health(self.module,self.binding,'c'*64,self.observed,{'status':'SURPRISE'})
        self.assertEqual(result.input_status,'UNVERIFIED')
    def test_real_attestation(self):
        result=evaluate_health(self.module,self.binding,'c'*64,self.observed,dict(status='READY',data_kind='OWNER_VERIFIED',owner_verified=True,stable_snapshot_verified=True,snapshot_sha256='f'*64))
        self.assertEqual(result.input_status,'READY')
    def test_mismatch_and_missing_kept(self):
        result=evaluate_health(self.module,self.binding,'c'*64,replace(self.observed,code_manifest_sha256='0'*64),{'status':'MISSING'})
        self.assertIn('RUNTIME_CODE_MANIFEST_SHA256_MISMATCH',result.reason_codes)
        self.assertIn('INPUT_MISSING',result.reason_codes)
if __name__=='__main__':unittest.main()
