"""Full original collector entry with synthetic denied transport; no real network."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]

class CloudUSCollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory(prefix='v5-us-collector-contract-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root=Path(cls.temporary.name);cls.owner=cls.root/'owner'
        child=subprocess.run([sys.executable,'-B',str(BASE/'tools/cloud_preview/assemble_us_collector.py'),'--out',str(cls.owner)],capture_output=True,text=True)
        if child.returncode:raise RuntimeError(child.stderr)

    def child(self,script,*args):
        result=subprocess.run([sys.executable,'-I','-B','-c',script,str(BASE/'src'),str(self.owner),*map(str,args)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr+'\n'+result.stdout)
        return result.stdout

    def test_complete_original_cli_import_and_source_verification(self):
        output=self.child("import sys;sys.path.insert(0,sys.argv[1]);from v5_shadow.cloud_us_collector import main;main(['--owner-root',sys.argv[2],'--check-only'])")
        value=json.loads(output);self.assertEqual(value['files'],48);self.assertFalse(value['capture_executed'])

    def test_original_capture_writes_three_part_failed_contract_without_fallback(self):
        script=r'''
import sys,io,json,contextlib
from pathlib import Path
from datetime import datetime,timezone
from urllib.error import URLError
sys.path.insert(0,sys.argv[1])
from v5_shadow.cloud_us_collector import load_owner
from v5_shadow.cloud_transport import run_original_us_cli
owner,transport=load_owner(Path(sys.argv[2]));root=Path(sys.argv[3])
# Test-only clock and synthetic opener. No outbound socket may be used.
owner._capture_now=lambda value=None:datetime(2026,10,10,9,0,16,tzinfo=timezone.utc)
counts={'proxy':0,'direct':0}
class Proxy:
 def open(self,*args,**kwargs):
  counts['proxy']+=1
  raise URLError(OSError('Tunnel connection failed: 403 Synthetic policy refusal'))
class Direct:
 def open(self,*args,**kwargs):
  counts['direct']+=1;raise AssertionError('DIRECT_FALLBACK_FORBIDDEN')
def audit(event,args):
 if event.startswith(('socket.connect','socket.getaddrinfo','socket.sendto')):raise AssertionError('REAL_NETWORK_FORBIDDEN')
sys.addaudithook(audit)
output=io.StringIO()
with contextlib.redirect_stdout(output):
 status=run_original_us_cli(owner,transport,['--data-root',str(root),'--trade-date','20261009','--capture-phase','POST_CLOSE','--allow-late-post-close','--timeout','1'],allow_network_capture=True,transport_options={'proxy_url':'http://proxy.invalid','proxy_opener':Proxy(),'direct_opener':Direct()})
assert (root/'research/peripherals/20261009/external_finance.json').exists(),output.getvalue()
payload=json.loads((root/'research/peripherals/20261009/external_finance.json').read_bytes())
files=[str(p.relative_to(root)) for p in root.rglob('*.json')]
print(json.dumps({'exit':status,'counts':counts,'summary':json.loads(output.getvalue()),'files':files,'status':payload['status'],'feeds':payload['feed_receipts']}))
'''
        result=json.loads(self.child(script,self.root/'synthetic-data'))
        self.assertEqual(result['exit'],2);self.assertEqual(result['counts'],dict(proxy=6,direct=0))
        self.assertEqual(result['summary']['operation_status'],'NO_LANE_READY')
        self.assertEqual(result['status'],'CANNOT_CONFIRM')
        self.assertEqual(len(result['files']),3)
        for receipt in result['feeds']:
            # Frozen producer deliberately retains its original receipt schema.
            self.assertIn('403',receipt['error']);self.assertTrue(receipt['proxy_used'])
            self.assertFalse(receipt['fallback_used']);self.assertIsNone(receipt['http_status'])

    def test_source_tamper_rejected_before_owner_import(self):
        script=r'''
import sys,shutil
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.cloud_us_collector import load_owner
root=Path(sys.argv[3]);shutil.copytree(sys.argv[2],root)
with (root/'ops/_us_market_digest_parts/phase_payload.py').open('ab') as out:out.write(b'\n# tampered')
try:load_owner(root)
except ValueError as error:assert str(error).startswith('CLOUD_US_COLLECTOR_SOURCE_SHA:')
else:raise AssertionError('tampered collector accepted')
assert 'ops.us_market_digest' not in sys.modules
'''
        self.child(script,self.root/'tampered')

    def test_unmarked_and_overlapping_output_are_rejected_before_capture(self):
        from v5_shadow.cloud_us_collector import initialize_output,admit_output
        output=self.root/'marked';initialize_output(output,self.owner)
        self.assertEqual(admit_output(output,self.owner),output)
        with self.assertRaisesRegex(ValueError,'MARKED_PRIVATE_OUTPUT_REQUIRED'):admit_output(self.root/'unmarked',self.owner)
        with self.assertRaisesRegex(ValueError,'SOURCE_OVERLAP'):admit_output(self.owner,self.owner)
        with self.assertRaisesRegex(ValueError,'NEW_OUTPUT_REQUIRED'):initialize_output(output,self.owner)
