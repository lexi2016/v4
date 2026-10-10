"""Explicit Mac original-owner chain; requires the existing fixed e06d bundle.

Run separately with V5_ANNOUNCEMENT_REVISION_TEST_BUNDLE. Missing fixture is an
error, never a skipped acceptance. No real capture or model output is created.
"""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from v5_shadow.daily_announcement_revision import run_revision
from v5_shadow.announcement_offline_reader import read_owner


class DailyRevisionOriginalChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bundle=Path(os.environ['V5_ANNOUNCEMENT_REVISION_TEST_BUNDLE']).resolve()
        script=r'''
import importlib.util,json,sys
from pathlib import Path
path=Path(sys.argv[1])/'tests/test_decision_revision.py'
spec=importlib.util.spec_from_file_location('revision_fixture',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.DecisionRevisionTests.setUpClass()
fixture=module.DecisionRevisionTests();fixture.setUp();fixture.fixture.tmp._finalizer.detach()
create=dict(parent_root=str(fixture.parent),recovery_sha256=fixture.fixture.recovery_sha,revision_id='decision-r1',
    parent_product_sha256=fixture.parent_sha,parent_receipt_sha256=fixture.receipt_sha,
    semantic_catalog=str(fixture.semantic),semantic_sha256=module.support.sha(fixture.semantic.read_bytes()),
    reviewer_output=str(fixture.reviewer),reviewer_sha256=module.support.sha(fixture.reviewer.read_bytes()),
    decisions=str(fixture.decisions),decisions_sha256=module.support.sha(fixture.decisions.read_bytes()))
print(json.dumps(create))
'''
        child=subprocess.run([sys.executable,'-I','-B','-c',script,str(bundle)],capture_output=True,text=True,timeout=180)
        if child.returncode:raise AssertionError(child.stderr)
        create=json.loads(child.stdout.splitlines()[-1]);cls.parent=Path(create['parent_root'])
        cls.addClassCleanup(shutil.rmtree,cls.parent.parent)
        before={str(p.relative_to(cls.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.parent.rglob('*') if p.is_file()}
        cls.receipt=run_revision(dict(target_date='20261009',revision_create=create,
            review_identities=dict(parent_task_id='synthetic-revision-task',reader_identity='fixture-reader',
                                   reviewer_identity='fixture-independent-reviewer')),'synthetic-ledger-attempt')
        cls.binding=cls.receipt['product_reference']['binding']
        for name,digest in before.items():
            if hashlib.sha256((cls.parent/name).read_bytes()).hexdigest()!=digest:raise AssertionError('PARENT_CHANGED:'+name)

    def test_original_revision_commands_and_readonly_manager_transport(self):
        self.assertEqual(self.receipt['status'],'BLOCKED')
        root=Path(self.binding['root'])
        before={str(p):p.read_bytes() for p in self.parent.rglob('*') if p.is_file()}
        result=read_owner(self.binding,datetime.now(timezone.utc).isoformat())
        self.assertEqual(result['consumption']['status'],'CONSUMED')
        self.assertEqual(result['analysis']['analysis']['stock_selection']['article_count'],2)
        self.assertEqual(result['analysis']['analysis']['stock_selection']['selected_stock_count'],1)
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.parent.rglob('*') if p.is_file()})
        with self.assertRaisesRegex(ValueError,'REVISION_BINDING_SHA'):
            read_owner(dict(self.binding,revision_manifest_sha256='0'*64),datetime.now(timezone.utc).isoformat())

    def test_original_manager_save_then_auto_read_consumes_revision(self):
        from v5_shadow.manager_plan import run_manager_plan
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();inputs={}
            for name in ('manager','materials','us'):
                path=root/name;path.mkdir();inputs[name]=dict(root=str(path),files={})
            output=root/'plans';output.mkdir();(output/'.v5-manager-plan-root').write_bytes(b'v5.manager-plan-root.v1\n')
            request=dict(target_date='20261009',now=datetime.now(timezone.utc).isoformat(),action='refresh',view='auto',
                selection_date=None,announcement_date=None,inputs=inputs,rebound=None,
                manager_output_root=str(output),announcement_offline_owner=self.binding)
            saved=run_manager_plan(request);page=run_manager_plan(dict(request,action='read'))
            self.assertEqual(saved['readback']['status'],'MATCHED')
            self.assertEqual(saved['readback']['run_id'],page['payload']['plan_product']['run_id'])
            self.assertEqual(saved['readback']['plan_sha256'],page['payload']['plan_product']['sha256'])
            self.assertEqual(saved['announcement_offline_readback']['consumption']['status'],'CONSUMED')
            self.assertEqual(page['announcement_offline_readback']['consumption']['status'],'CONSUMED')
            self.assertEqual(saved['payload']['plan_product']['status'],'CURRENT_RECOVERY')
            self.assertEqual(page['payload']['read_context']['mode'],'CURRENT_RECOVERY')
            self.assertFalse(page['payload']['read_context']['historical_eligible'])
            self.assertEqual(saved['announcement_offline_readback']['consumption']['product_sha256'],
                page['announcement_offline_readback']['consumption']['product_sha256'])

    def test_removed_admitted_revision_input_refuses_current_recovery_readback(self):
        from v5_shadow.manager_plan import run_manager_plan
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();inputs={}
            for name in ('manager','materials','us'):
                path=root/name;path.mkdir();inputs[name]=dict(root=str(path),files={})
            output=root/'plans';output.mkdir();(output/'.v5-manager-plan-root').write_bytes(b'v5.manager-plan-root.v1\n')
            request=dict(target_date='20261009',now=datetime.now(timezone.utc).isoformat(),action='refresh',view='auto',
                selection_date=None,announcement_date=None,inputs=inputs,rebound=None,
                manager_output_root=str(output),announcement_offline_owner=self.binding)
            saved=run_manager_plan(request)
            self.assertEqual(saved['announcement_offline_readback']['consumption']['status'],'CONSUMED')
            before={str(path):path.read_bytes() for path in output.rglob('*') if path.is_file()}
            request.pop('announcement_offline_owner')
            page=run_manager_plan(dict(request,action='read'))['payload']
            self.assertEqual(page['plan_product']['status'],'STALE_INPUTS_CHANGED')
            self.assertFalse(page['plan_product']['consumed'])
            self.assertEqual(page['plan_product']['run_id'],saved['readback']['run_id'])
            self.assertNotEqual(page['input_identity'],saved['payload']['input_identity'])
            self.assertEqual(before,{str(path):path.read_bytes() for path in output.rglob('*') if path.is_file()})
