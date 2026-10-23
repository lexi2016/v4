"""Focused binding delta tests; no launchctl, signals, runtime imports or release writes."""
import ast
import copy
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import control_prepare as c
import activation_driver as d

OLD = Path('/Users/lexi/Desktop/学习/agents调试/V4_PRESELECTION_PROVENANCE_REPAIR_20261023')

class BindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=c.OWNER)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'binding.json'
        self.binding = json.loads(c.BINDING.read_bytes())
        self.binding.update(status='BOUND_INDEPENDENT_SOURCE_PASS',runtime_source_allowlist=['ops/x.py'],source_sha256={'ops/x.py':'a'*64,'ops/a_share_daily_sync.py':'b'*64})
        self.path.write_text(json.dumps(self.binding))
        self.patcher=patch.object(c,'BINDING',self.path);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.original=(OLD/'live/prepared-r3/original.plist').read_bytes()
        self.target=self.root/'target/app'

    def emit(self, raw=None):
        return c.candidate_plist(raw or self.original,'/old/app',self.target,self.binding['release_id'],self.root/'target/release-manifest.json','c'*64)

    def test_exact_common_app_binding_only(self):
        want=plistlib.loads(c.helper()['candidate_plist'](self.original,'/old/app',self.target,self.binding['release_id'],self.root/'target/release-manifest.json','c'*64))
        want['EnvironmentVariables']['PYTHONPATH']=str(self.target/'upstreams')+':'+str(self.target)
        want['EnvironmentVariables']['V35_RESEARCH_PANEL_A_SYNC_SCRIPT']=str(self.target/'ops/a_share_daily_sync.py')
        self.assertEqual(plistlib.loads(self.emit()),want)
        self.assertEqual(plistlib.loads(self.original)['EnvironmentVariables']['V35_RESEARCH_PANEL_A_SYNC_SCRIPT'],self.binding['original_sync_script'])

    def test_pending_config_cannot_execute(self):
        self.binding['status']='PREPARATION_ONLY_PENDING_SOURCE_PASS';self.path.write_text(json.dumps(self.binding))
        with self.assertRaisesRegex(ValueError,'final reviewed source binding required'):self.emit()

    def test_wrong_foreign_script_or_pythonpath_rejected(self):
        for key in ('V35_RESEARCH_PANEL_A_SYNC_SCRIPT','PYTHONPATH'):
            raw=plistlib.loads(self.original);raw['EnvironmentVariables'][key]='/wrong'
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'original sync script/PYTHONPATH binding drift'):self.emit(plistlib.dumps(raw))

    def test_foreign_source_sha_drift_rejected(self):
        self.binding['original_sync_script_sha256']='0'*64;self.path.write_text(json.dumps(self.binding))
        with self.assertRaisesRegex(ValueError,'original sync script/PYTHONPATH binding drift'):self.emit()

    def test_nonfixed_source_count_supported(self):
        for count in (1,9,11):
            b=copy.deepcopy(self.binding);b['runtime_source_allowlist']=['ops/p%d.py'%i for i in range(count)];b['source_sha256']={p:'a'*64 for p in b['runtime_source_allowlist']};b['source_sha256']['ops/a_share_daily_sync.py']='b'*64;self.path.write_text(json.dumps(b))
            with self.subTest(count=count):self.assertEqual(c.binding_config()['source_sha256'],b['source_sha256'])

    def test_invalid_or_missing_source_pin_and_path_rejected(self):
        variants=[]
        b=copy.deepcopy(self.binding);del b['source_sha256']['ops/a_share_daily_sync.py'];variants.append(b)
        b=copy.deepcopy(self.binding);b['source_sha256']['ops/x.py']='invalid';variants.append(b)
        for path in ('../escape.py','/outside.py','ops/notpython.txt'):
            b=copy.deepcopy(self.binding);b['runtime_source_allowlist']=[path];variants.append(b)
        for b in variants:
            self.path.write_text(json.dumps(b))
            with self.subTest(b=b),self.assertRaises(ValueError):c.binding_config()

    def test_packet_binding_drift_rejected_before_any_inventory(self):
        p=self.root/'packet.json';p.write_text(json.dumps({'independent_review':'PASS','candidate_inventory':{'x':{}},'source_binding_sha256':'0'*64,'source_sha256':self.binding['source_sha256']}))
        with patch.object(c,'helper',side_effect=AssertionError('inventory helper must not be reached')):
            with self.assertRaisesRegex(ValueError,'packet source binding drift'):c.verify_candidate_packet(p)

    def test_lifecycle_and_pdf_code_unchanged_ast(self):
        before=ast.parse((OLD/'live/owner/activation_driver.py').read_text());after=ast.parse(Path(d.__file__).read_text())
        def methods(tree,name):
            cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name)
            return {n.name:ast.dump(n,include_attributes=False) for n in cls.body if isinstance(n,ast.FunctionDef)}
        self.assertEqual(methods(before,'Driver'),methods(after,'Driver'))
        oldops,newops=methods(before,'RealOps'),methods(after,'RealOps')
        self.assertEqual({k:v for k,v in oldops.items() if k!='install_release'},{k:v for k,v in newops.items() if k!='install_release'})
        self.assertEqual(c.sha(OLD/'live/owner/pdf_readonly.py'),c.sha(c.OWNER/'pdf_readonly.py'))

if __name__=='__main__':unittest.main(verbosity=2)
