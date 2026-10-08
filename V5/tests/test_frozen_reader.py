"""Run the original reader in disposable processes against synthetic file owners."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from v5_shadow.legacy_adapter import load_pinned_reader

BASE=Path(__file__).resolve().parents[1]
SCRIPT='''
import hashlib,json,sys
from pathlib import Path
from v5_shadow.contracts import Binding,parse_request
from v5_shadow.source_capsule import inspect_capsule
from v5_shadow.cli import load_capsule
from v5_shadow.legacy_adapter import load_pinned_reader,run_legacy_screen
base=Path(sys.argv[1]);root=Path(sys.argv[2]);mode=sys.argv[3]
calendar=base/'vendor/rebound_baseline/contracts/market_calendar_2026.json'
binding=Binding(root,root.parent,hashlib.sha256(calendar.read_bytes()).hexdigest(),load_capsule().manifest_sha256,None)
request=parse_request(dict(request_id='synthetic',target_trade_date='20261008',research_cutoff='2026-10-08T08:00:00+08:00',requested_at='2026-10-08T08:01:00+08:00',execution_kind='SHADOW_REPLAY',data_kind='SYNTHETIC',composition_sha256='c'*64,input_snapshot_sha256=None))
if mode=='fixture':
 from fixtures.rebound_factory import publish_fixture
 original=load_pinned_reader(binding)
 print(json.dumps({'manifest':publish_fixture(root,original)}))
elif mode=='direct':
 original=load_pinned_reader(binding);context=original.plan_context(request.target_trade_date,now=request.research_cutoff)
 print(json.dumps(original.read_rebound_screen(root,context),allow_nan=False))
else:print(json.dumps(run_legacy_screen(request,binding),allow_nan=False))
'''
class FrozenReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'source';self.root.mkdir()
    def call(self,mode):
        env=dict(os.environ,PYTHONPATH=str(BASE/'src')+os.pathsep+str(BASE/'tests'),PYTHONDONTWRITEBYTECODE='1')
        p=subprocess.run([sys.executable,'-B','-c',SCRIPT,str(BASE),str(self.root),mode],capture_output=True,text=True,env=env,timeout=60)
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(p.stdout)
    def test_missing_panel_is_unknown(self):
        out=self.call('adapter');self.assertEqual(out['status'],'CANNOT_CONFIRM');self.assertIsNone(out['input_identity'])
    def test_real_file_fixture_two_gate_and_parity(self):
        self.call('fixture');direct=self.call('direct');wrapped=self.call('adapter')
        self.assertEqual(direct,wrapped)
        self.assertTrue(wrapped['main_screen_ready'])
        self.assertEqual(wrapped['coverage']['strict_count'],1)
        self.assertEqual(wrapped['coverage']['near_count'],2)
        self.assertEqual(wrapped['coverage']['excluded_count'],1)
    def test_future_revision_rejected(self):
        info=self.call('fixture');path=Path(info['manifest']);value=json.loads(path.read_text());value['manifest_prepared_at']='2026-10-08T10:00:00+08:00';path.write_text(json.dumps(value))
        self.assertEqual(self.call('adapter')['status'],'CANNOT_CONFIRM')
if __name__=='__main__':unittest.main()
