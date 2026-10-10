"""Synthetic original-owner identity transport and actual workspace integration."""
from datetime import datetime,timezone
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from v5_shadow.native_identity_reader import read_private
from v5_shadow.manager_plan import run_manager_plan


class NativeIdentityReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.native=self.root/'native';self.native.mkdir()
        self.make_master('2026-10-08T08:00:00+00:00')

    def make_master(self,captured):
        script=r'''
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.hk_preselection import _source_bytes,_HKLoader
sys.meta_path.insert(0,_HKLoader(_source_bytes()))
from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master
publish_hk_security_master(Path(sys.argv[2]),trade_date='20261008',
 rows=[{'code':'HK.00001','name':'SYNTHETIC ISSUER NOT REAL EVIDENCE'}],
 universe_codes_sha256='a'*64,captured_at=sys.argv[3])
'''
        result=subprocess.run([sys.executable,'-I','-B','-c',script,str(Path(__file__).resolve().parents[1]/'src'),str(self.native),captured],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr)
        self.binding=dict(root=str(self.native),files={str(p.relative_to(self.native)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.native.rglob('*') if p.is_file()})

    def manager_request(self):
        inputs={}
        for name in ('manager','materials','us'):
            path=self.root/name;path.mkdir(exist_ok=True);inputs[name]=dict(root=str(path),files={})
        inputs['native_master']=self.binding
        output=self.root/'output';output.mkdir(exist_ok=True)
        (output/'.v5-manager-plan-root').write_bytes(b'v5.manager-plan-root.v1\n')
        return dict(target_date='20261009',now='2026-10-09T01:00:00+00:00',action='refresh',view='dynamic',
            selection_date=None,announcement_date=None,inputs=inputs,rebound=None,manager_output_root=str(output))

    def test_original_reader_returns_rows_manifest_without_modifying_source(self):
        before={p:p.read_bytes() for p in self.native.rglob('*') if p.is_file()}
        result=read_private(self.binding,'20261008')
        self.assertEqual(result['master']['HK.00001']['name'],'SYNTHETIC ISSUER NOT REAL EVIDENCE')
        self.assertEqual(result['manifest']['trade_date'],'20261008')
        self.assertEqual(before,{p:p.read_bytes() for p in self.native.rglob('*') if p.is_file()})

    def test_original_manager_material_discovery_gets_native_identity(self):
        result=run_manager_plan(self.manager_request())
        discovery=result['payload']['material_discovery_evidence']
        self.assertEqual(discovery['identity_witness']['source_date'],'20261008')
        self.assertEqual(discovery['coverage']['identity_row_count'],1)
        self.assertEqual(discovery['identity_witness']['role'],'REFERENCE_SESSION_IDENTITY_NOT_TARGET_CONNECT_MEMBERSHIP')
        self.assertEqual(result['readback']['status'],'MATCHED')
        self.assertNotIn('MATERIAL_DISCOVERY_NATIVE_SECURITY_MASTER_ROOT_NOT_BOUND',discovery['gaps'])

    def test_wrong_owner_date_rejected(self):
        with self.assertRaisesRegex(ValueError,'OWNER_READ_FAILED'):read_private(self.binding,'20261007')

    def test_native_rows_after_cutoff_keep_original_rejection(self):
        self.native=self.root/'future-native';self.native.mkdir()
        self.make_master('2026-10-10T00:00:00+00:00')
        result=run_manager_plan(self.manager_request())
        discovery=result['payload']['material_discovery_evidence']
        self.assertIsNone(discovery['identity_witness'])
        self.assertTrue(any('NATIVE_IDENTITY_READ_FAILED' in gap for gap in discovery['gaps']))

    def recovery_request(self):
        request=self.manager_request()
        request.update(now=datetime.now(timezone.utc).isoformat(),view='auto')
        self.assertGreater(request['now'][:10],'2026-10-09')
        return request

    def test_crossday_current_recovery_with_native_binding_keeps_same_run(self):
        request=self.recovery_request()
        before={p:p.read_bytes() for p in self.native.rglob('*') if p.is_file()}
        saved=run_manager_plan(request)
        page=run_manager_plan(dict(request,action='read'))['payload']
        self.assertEqual(page['plan_product']['status'],'CURRENT_RECOVERY')
        self.assertTrue(page['plan_product']['consumed'])
        self.assertFalse(page['plan_product']['historical_eligible'])
        self.assertEqual(page['plan_product']['run_id'],saved['readback']['run_id'])
        self.assertEqual(page['plan_product']['sha256'],saved['readback']['plan_sha256'])
        discovery=page['material_discovery_evidence']
        self.assertEqual(discovery['coverage']['identity_row_count'],1)
        self.assertEqual(discovery['identity_witness']['source_date'],'20261008')
        self.assertEqual(discovery['identity_witness']['role'],'REFERENCE_SESSION_IDENTITY_NOT_TARGET_CONNECT_MEMBERSHIP')
        self.assertFalse(page['production_allowed']);self.assertFalse(page['orders_sent'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.native.rglob('*') if p.is_file()})

    def test_crossday_native_bad_binding_sha_rejected_before_save(self):
        request=self.recovery_request();request=copy.deepcopy(request)
        name=next(iter(request['inputs']['native_master']['files']))
        request['inputs']['native_master']['files'][name]='0'*64
        with self.assertRaisesRegex(ValueError,'MANAGER_INPUT_SHA_OR_LIMIT'):run_manager_plan(request)
        self.assertFalse((self.root/'output/current_recovery').exists())

    def test_crossday_other_target_cannot_consume_wrong_native_session(self):
        request=self.recovery_request();request['target_date']='20261008'
        result=run_manager_plan(request)['payload']
        discovery=result['material_discovery_evidence']
        self.assertIsNone(discovery['identity_witness'])
        self.assertTrue(any('NATIVE_IDENTITY_READ_FAILED' in gap for gap in discovery['gaps']))
        self.assertFalse(result['production_allowed']);self.assertFalse(result['orders_sent'])

    def test_crossday_resealed_outer_binding_cannot_forge_native_identity(self):
        request=self.recovery_request()
        manifest=next(self.native.rglob('manifest.json'))
        value=json.loads(manifest.read_bytes());value['trade_date']='20261007'
        manifest.write_text(json.dumps(value))
        self.binding['files'][str(manifest.relative_to(self.native))]=hashlib.sha256(manifest.read_bytes()).hexdigest()
        result=run_manager_plan(request)['payload'];discovery=result['material_discovery_evidence']
        self.assertIsNone(discovery['identity_witness'])
        self.assertTrue(any('NATIVE_IDENTITY_READ_FAILED' in gap for gap in discovery['gaps']))
        self.assertFalse(result['production_allowed']);self.assertFalse(result['orders_sent'])
