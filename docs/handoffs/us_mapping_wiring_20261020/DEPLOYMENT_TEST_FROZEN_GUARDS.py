"""Hermetic post-verify publication guards; real stores/services are never instantiated."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy
import hashlib
import importlib.util
import json
import plistlib
import tempfile
import unittest

DOC=Path(__file__).resolve().parent
if DOC.name=="local_only":DOC=DOC.parent
PREP=json.loads((DOC/'DEPLOYMENT_RESULT_PREPARED.json').read_bytes())
def canonical(obj):return (json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(raw):return hashlib.sha256(raw).hexdigest()

class FrozenGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='frozen-guards-',dir=DOC/'local_only')
        self.root=Path(self.tmp.name)
        spec=importlib.util.spec_from_file_location('guard_under_test',DOC/'publish_wiring_result.py')
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        m=self.m;m.DOC=self.root/'docs';m.DOC.mkdir();m.LIVE_STATE=self.root/'live';m.STAGE=self.root/'stage'
        self.live=m.LIVE_STATE/'manager_workbench'
        self.pointer=self.live/'pointers/20261020/NEXT_DAY.json';self.pointer.parent.mkdir(parents=True)
        self.receipt=copy.deepcopy(PREP)
        self.snap=SimpleNamespace(run_id=PREP['new_run_id'],product_sha256=PREP['product_sha256'],generated_at=PREP['snapshot_generated_at'])
        self.job=SimpleNamespace(job_id=PREP['new_job_id'])
        self.new=dict(run_id=self.snap.run_id,product_sha256=self.snap.product_sha256,generated_at=self.snap.generated_at)
        self.new_sha=digest(canonical(self.new));assert self.new_sha=='985b91b19eaaf878f87295f02d8f191d2aaf4bcc2150911522a5e2a68823a248'
        self.pointer.write_bytes(canonical(PREP['old_pointer_value']))
        self.calls=[]
        outer=self
        class FakeStore:
            def __init__(self,*args):outer.calls.append('store')
            def _write(self,path,obj,**kwargs):path.write_bytes(canonical(obj))
            def save_input(self,*args):outer.calls.append('save_input')
            def save_checkpoint(self,*args):outer.calls.append('save_checkpoint')
            def save_job(self,*args):outer.calls.append('save_job')
            def commit_plan(self,snapshot):
                outer.calls.append('commit_plan')
                value=outer.new if snapshot.run_id==outer.snap.run_id else PREP['old_pointer_value']
                self._write(outer.pointer,value,immutable=False)
                return snapshot
        self.env=dict(canonical=canonical,WorkbenchStore=FakeStore,
            PlanSnapshot=SimpleNamespace(model_validate=lambda value: self.snap if value.get('new') else SimpleNamespace(**PREP['old_pointer_value'])))
        m.verify=lambda sha: (self.receipt,self.env,self.snap,self.job)
        self.live_snapshot=self.live/'snapshots'/(self.snap.run_id+'.json');self.live_snapshot.parent.mkdir(parents=True)
        old=self.live/'snapshots'/(m.SOURCE_RUN+'.json');old.write_text('{}')
        old_input=self.live/'input_snapshots'/(m.SOURCE_INPUT+'.json');old_input.parent.mkdir();old_input.write_text('{}')
        self.old_input=old_input;self.old_snapshot=old
        self.real_sha=m.sha
        self.temp_plist=self.root/'api.plist';self.temp_plist.write_bytes(plistlib.dumps(dict(WorkingDirectory=str(m.CANDIDATE/'app'))))
        m.Path=lambda value: self.temp_plist if str(value)=='/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist' else Path(value)
        def test_sha(path):
            if path==self.temp_plist:return '9e6fa1a90073cbc32b76f86c157ba2c86145b28b08f0927986b5e13ecdbbca1e'
            if path==self.old_input:return m.SOURCE_INPUT
            if path==self.old_snapshot:return PREP['source_snapshot_sha256']
            return self.real_sha(path)
        m.sha=test_sha
        stage_input=m.STAGE/'manager_workbench/input_snapshots'/(PREP['full_input_snapshot_sha256']+'.json')
        stage_input.parent.mkdir(parents=True);stage_input.write_text('{}')

    def tearDown(self):self.tmp.cleanup()

    def write_receipt(self,**changes):
        value=dict(prepared_receipt_sha256='frozen',run_id=self.snap.run_id,product_sha256=self.snap.product_sha256,actual_pointer_sha256=self.new_sha)
        value.update(changes)
        (self.m.DOC/'DEPLOYMENT_PUBLICATION_RECEIPT.json').write_text(json.dumps(value))

    def rejected_without_writes(self,action):
        before=self.pointer.read_bytes()
        with self.assertRaises(AssertionError):action()
        self.assertEqual(self.pointer.read_bytes(),before)
        self.assertEqual(self.calls,[])

    def test_f1_parallel_pointer_cannot_be_authorized_by_future_receipt(self):
        self.pointer.write_bytes(canonical(dict(run_id='parallel-newer-run',product_sha256='f'*64,generated_at=self.snap.generated_at)))
        self.write_receipt(actual_pointer_sha256=self.real_sha(self.pointer))
        self.rejected_without_writes(lambda:self.m.rollback('frozen'))

    def test_f1_wrong_receipt_product_rejected(self):
        self.pointer.write_bytes(canonical(self.new));self.write_receipt(product_sha256='0'*64)
        self.rejected_without_writes(lambda:self.m.rollback('frozen'))

    def test_f2_same_run_tampered_product_not_idempotent(self):
        self.live_snapshot.write_text('{"new":true}')
        self.pointer.write_bytes(canonical(dict(self.new,product_sha256='0'*64)))
        self.rejected_without_writes(lambda:self.m.publish('frozen',True))

    def test_f2_same_run_tampered_time_not_idempotent(self):
        self.live_snapshot.write_text('{"new":true}')
        self.pointer.write_bytes(canonical(dict(self.new,generated_at='2026-10-20T12:00:00+08:00')))
        self.rejected_without_writes(lambda:self.m.publish('frozen',True))

    def test_exact_idempotent_readback_has_no_writes(self):
        self.live_snapshot.write_text('{"new":true}');self.pointer.write_bytes(canonical(self.new))
        self.m.publish('frozen',True);self.assertEqual(self.calls,[])

    def launch(self,state='running',pid='12345',cwd_ok=True):
        def run(args,**kwargs):
            if args[0]=='/bin/launchctl':
                text='\tstate = '+state+'\n\tworking directory = '+str(self.m.CANDIDATE/'app')+'\n'
                if pid is not None:text+='\tpid = '+pid+'\n'
                return SimpleNamespace(returncode=0,stdout=text)
            assert args[0]=='/usr/sbin/lsof' and args[args.index('-p')+1]==pid
            return SimpleNamespace(returncode=0,stdout='p'+pid+'\nn'+(str(self.m.CANDIDATE/'app') if cwd_ok else '/parallel/app')+'\n')
        return patch.object(self.m.subprocess,'run',side_effect=run)

    def test_f3_not_running_without_pid_rejected(self):
        with self.launch(state='not running',pid=None):self.rejected_without_writes(lambda:self.m.publish('frozen',True))

    def test_f3_running_without_pid_rejected(self):
        with self.launch(pid=None):self.rejected_without_writes(lambda:self.m.publish('frozen',True))

    def test_f3_pid_wrong_cwd_rejected(self):
        with self.launch(cwd_ok=False):self.rejected_without_writes(lambda:self.m.publish('frozen',True))

    def test_running_pid_correct_cwd_can_reach_isolated_store(self):
        with self.launch():self.m.publish('frozen',True)
        self.assertEqual(self.real_sha(self.pointer),self.new_sha)
        self.assertEqual(self.calls,['store','save_input','save_job','commit_plan'])

    def test_exact_rollback_restores_old_pointer_keeps_new_snapshot(self):
        self.live_snapshot.write_text('{"new":true}');self.pointer.write_bytes(canonical(self.new));self.write_receipt()
        self.m.rollback('frozen')
        self.assertEqual(self.real_sha(self.pointer),PREP['old_pointer_sha256'])
        self.assertTrue(self.live_snapshot.exists())

if __name__=='__main__':unittest.main(verbosity=2)
