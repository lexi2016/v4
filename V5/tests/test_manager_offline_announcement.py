"""Mac regressions. Optional full chain reuses the fixed upstream synthetic fixture."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime,timezone
from types import SimpleNamespace
import unittest
from v5_shadow.announcement_offline_reader import install_transport,read_owner


class OfflineAnnouncementTransportTests(unittest.TestCase):
    def setUp(self):
        self.binding=dict(root='/bound',binding_sha256='a'*64,target_date='20261009',publication_date='2026-10-08')
        self.cutoff='2026-10-09T15:03:27.459945+00:00'
        self.old=lambda *a,**k:{'old_owner':True,'consumed':False}
        self.service=SimpleNamespace(get_announcement_date_catalog=self.old,get_announcement_analysis=self.old)
        self.module=SimpleNamespace(read_analysis_consumption=self.old)
        self.result=dict(catalog={'verified_offline_catalog':True},analysis={'analysis':{'status':'VERIFIED'}},
            consumption={'status':'CONSUMED','consumed':True,'research_references':[]},cutoff=self.cutoff)

    def install(self,error=None):install_transport(self.service,self.module,self.binding,self.result,error)

    def test_overlay_keeps_new_terminal_and_installs_existing_manager_checks(self):
        script=r"""
import sys
from v5_shadow.announcement_offline_reader import APP,install_consumer_contract,CONSUMER_FUNCTIONS
sys.path.insert(0,str(APP))
from v4.manager_research import workspace_announcements as module
terminal=module.validate_terminal_body_capture
assert not hasattr(module,'read_analysis_consumption')
install_consumer_contract(module)
assert module.validate_terminal_body_capture is terminal
for name in CONSUMER_FUNCTIONS:
    assert getattr(module,name).__code__.co_filename=='<pinned-manager-announcement-consumption>'
assert 'validate_registered_handoff' in module.read_analysis_consumption.__code__.co_names
assert 'validate_owner_analysis_import_receipt' in module.read_analysis_consumption.__code__.co_names
"""
        child=subprocess.run([sys.executable,'-B','-c',script],capture_output=True,text=True,timeout=30)
        self.assertEqual(child.returncode,0,child.stderr)

    def test_exact_pair_selects_offline_owner_interface(self):
        self.install()
        self.assertEqual(self.service.get_announcement_date_catalog('20261009','2026-10-08'),self.result['catalog'])
        self.assertEqual(self.service.get_announcement_analysis('20261009','2026-10-08'),self.result['analysis'])
        result=self.module.read_analysis_consumption(self.service,'20261009','2026-10-08',cutoff=self.cutoff)
        self.assertTrue(result['consumed'])
        result['consumed']=False;self.assertTrue(self.result['consumption']['consumed'])

    def test_old_owner_preserved_for_unbound_pair_or_service(self):
        self.install()
        self.assertTrue(self.service.get_announcement_date_catalog('20261008','2026-10-07')['old_owner'])
        self.assertTrue(self.service.get_announcement_analysis('20261008','2026-10-07')['old_owner'])
        self.assertTrue(self.module.read_analysis_consumption(object(),'20261009','2026-10-08',cutoff=self.cutoff)['old_owner'])

    def test_wrong_cutoff_cannot_relabel_validated_consumption(self):
        self.install()
        result=self.module.read_analysis_consumption(self.service,'20261009','2026-10-08',cutoff='2026-10-09T14:00:00Z')
        self.assertFalse(result['consumed']);self.assertIn('OFFLINE_MANAGER_EXACT_CUTOFF_REQUIRED',result['gaps'])

    def test_bad_owner_retains_explicit_gap_not_old_catalog_fallback(self):
        self.install('OFFLINE_ANALYSIS_OWNER_IDENTITY_MISMATCH')
        with self.assertRaisesRegex(ValueError,'OWNER_IDENTITY'):self.service.get_announcement_date_catalog('20261009','2026-10-08')
        result=self.module.read_analysis_consumption(self.service,'20261009','2026-10-08',cutoff=self.cutoff)
        self.assertFalse(result['consumed']);self.assertEqual(result['gaps'],['OFFLINE_ANALYSIS_OWNER_IDENTITY_MISMATCH'])

    def test_future_acquisition_verdict_preserved(self):
        self.result['consumption'].update(status='NOT_CONSUMED_AFTER_CUTOFF',consumed=False,gaps=['ANNOUNCEMENT_ANALYSIS_NOT_AVAILABLE_AT_PLAN_CUTOFF'])
        self.install();result=self.module.read_analysis_consumption(self.service,'20261009','2026-10-08',cutoff=self.cutoff)
        self.assertFalse(result['consumed']);self.assertEqual(result['status'],'NOT_CONSUMED_AFTER_CUTOFF')


@unittest.skipUnless(os.environ.get('V5_ANNOUNCEMENT_OFFLINE_TEST_BUNDLE'),'fixed 1a699a0 upstream fixture bundle required')
class OfflineAnnouncementOriginalChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bundle=Path(os.environ['V5_ANNOUNCEMENT_OFFLINE_TEST_BUNDLE']).resolve()
        # Upstream test creates explicitly synthetic recovery + registered handoff
        # + import using original owners. Its deny-network hook stays in that child.
        script=r'''
import importlib.util,json,sys
from pathlib import Path
p=Path(sys.argv[1])/'tests/test_offline_analysis_chain.py'
spec=importlib.util.spec_from_file_location('offline_fixture',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.OfflineAnalysisChainTests.setUpClass()
f=m.OfflineAnalysisChainTests();f.setUp();f.tmp._finalizer.detach()
f.test_prepare_verify_import_and_readback_keep_failed_pages_unassessed()
print(json.dumps({'root':str(f.derived)}))
'''
        child=subprocess.run([sys.executable,'-I','-B','-c',script,str(bundle)],capture_output=True,text=True,timeout=120)
        if child.returncode:raise AssertionError(child.stderr)
        cls.root=Path(json.loads(child.stdout.splitlines()[-1])['root'])
        cls.addClassCleanup(shutil.rmtree,cls.root.parent)
        raw=(cls.root/'manager_binding.v1.json').read_bytes();value=json.loads(raw)
        cls.binding=dict(root=str(cls.root),binding_sha256=hashlib.sha256(raw).hexdigest(),target_date=value['target_trade_date'],publication_date=value['publication_date'])

    def test_real_original_interfaces_with_retained_failed_pages_and_readonly_evidence(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=read_owner(self.binding,datetime.now(timezone.utc).isoformat())
        self.assertEqual(result['analysis']['analysis']['status'],'VERIFIED')
        self.assertEqual(result['consumption']['status'],'CONSUMED')
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_original_future_acquisition_cutoff_gate(self):
        result=read_owner(self.binding,'2026-10-09T00:00:00+00:00')
        self.assertEqual(result['consumption']['status'],'NOT_CONSUMED_AFTER_CUTOFF')
        self.assertFalse(result['consumption']['consumed'])

    def test_wrong_date_and_tampered_binding_sha(self):
        for change,reason in [({'publication_date':'2026-10-07'},'BINDING_IDENTITY'),({'binding_sha256':'0'*64},'BINDING_SHA')]:
            with self.assertRaisesRegex(ValueError,reason):read_owner(dict(self.binding,**change),datetime.now(timezone.utc).isoformat())

    def test_recovery_evidence_and_wrong_owner_rejected(self):
        for name,reason in [('recovery_receipt.json','RECOVERY_SHA_MISMATCH'),('offline_analysis_owner_identity.json','OWNER_IDENTITY_MISMATCH'),('transport_policy.json','BLOCKED_POLICY_CHANGED')]:
            path=self.root/name;original=path.read_bytes()
            try:
                path.write_bytes(b'{}')
                with self.assertRaisesRegex(ValueError,reason):read_owner(self.binding,datetime.now(timezone.utc).isoformat())
            finally:path.write_bytes(original)

    def test_actual_manager_refresh_and_same_run_readback_use_new_consumer(self):
        from v5_shadow.manager_plan import run_manager_plan
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();inputs={}
            for name in ('manager','materials','us'):
                path=root/name;path.mkdir();inputs[name]={'root':str(path),'files':{}}
            output=root/'plans';output.mkdir();(output/'.v5-manager-plan-root').write_text('v5.manager-plan-root.v1\n')
            request=dict(target_date='20261009',now=datetime.now(timezone.utc).isoformat(),action='refresh',view='dynamic',
                selection_date=None,announcement_date=None,inputs=inputs,rebound=None,manager_output_root=str(output),announcement_offline_owner=self.binding)
            result=run_manager_plan(request)
            self.assertEqual(result['readback']['status'],'MATCHED')
            products=result['payload']['announcement_reviewed_analysis']['products']
            product=next(row for row in products if row['target_trade_date']=='20261009' and row['publication_date']=='2026-10-08')
            self.assertEqual(product['status'],'CONSUMED')
            self.assertEqual(product['product_sha256'],result['announcement_offline_readback']['consumption']['product_sha256'])

    def test_default_query_uses_original_calendar_and_real_default_read(self):
        cutoff=datetime.now(timezone.utc).isoformat()
        explicit=read_owner(self.binding,cutoff)
        default=read_owner(self.binding,cutoff,default_analysis=True)
        self.assertEqual(default['analysis']['date_selection_basis'],'PREVIOUS_HK_TRADING_SESSION')
        self.assertEqual(default['analysis']['publication_date'],'2026-10-08')
        self.assertEqual(explicit['analysis']['date_selection_basis'],'EXPLICIT')
        self.assertEqual(default['analysis']['analysis'],explicit['analysis']['analysis'])
