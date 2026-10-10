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

    def test_extra_package_initializers_and_legacy_bytecode_rejected_before_execution(self):
        for relative in ('ops/__init__.py', 'ops/_us_market_digest_parts/__init__.py', 'ops/__init__.pyc', 'ops/__pycache__/__init__.cpython-314.pyc'):
            with self.subTest(relative=relative):
                self.child(r"""
import sys,shutil,tempfile
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.cloud_us_collector import load_owner
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'owner';shutil.copytree(sys.argv[2],root)
 (root/sys.argv[3]).parent.mkdir(parents=True,exist_ok=True)
 (root/sys.argv[3]).write_bytes(b"raise AssertionError('UNPINNED_CODE_EXECUTED')")
 try:load_owner(root)
 except ValueError as error:assert 'UNLISTED' in str(error),str(error)
 else:raise AssertionError('extra source accepted')
 assert 'ops.us_market_digest' not in sys.modules
""", relative)

    def test_poisoned_valid_source_cache_is_ignored_and_original_bytes_execute(self):
        self.child(r"""
import sys,shutil,tempfile,py_compile,importlib.util,marshal
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.cloud_us_collector import load_owner
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'owner';shutil.copytree(sys.argv[2],root)
 source=root/'ops/us_market_digest.py';cache=Path(py_compile.compile(str(source),doraise=True))
 raw=cache.read_bytes();cache.write_bytes(raw[:16]+marshal.dumps(compile("raise AssertionError('POISONED_CACHE_EXECUTED')",str(source),'exec')))
 before=cache.read_bytes();owner,transport=load_owner(root)
 assert owner.__file__==str(source)
 assert cache.read_bytes()==before
""")

    def test_external_namespace_shadow_cannot_execute(self):
        self.child(r"""
import sys,tempfile
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.cloud_us_collector import load_owner
with tempfile.TemporaryDirectory() as tmp:
 shadow=Path(tmp);(shadow/'ops').mkdir();(shadow/'ops/__init__.py').write_text("raise AssertionError('EXTERNAL_SHADOW_EXECUTED')")
 sys.path.insert(0,str(shadow));owner,transport=load_owner(Path(sys.argv[2]))
 assert owner.__file__==str(Path(sys.argv[2])/'ops/us_market_digest.py')
""")

    def test_module_origin_and_namespace_path_tampering_are_rejected(self):
        self.child(r"""
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.cloud_us_collector import load_owner,audit_modules
owner,transport=load_owner(Path(sys.argv[2]));audit_modules()
original=owner.__spec__.origin;owner.__spec__.origin='/tmp/unpinned.py'
try:audit_modules()
except ValueError as error:assert 'MODULE_ORIGIN' in str(error)
else:raise AssertionError('false origin accepted')
owner.__spec__.origin=original
namespace=sys.modules['ops'];original=namespace.__path__;namespace.__path__=['/tmp/external-ops']
try:audit_modules()
except ValueError as error:assert 'MODULE_ORIGIN' in str(error)
else:raise AssertionError('external namespace accepted')
namespace.__path__=original;audit_modules()
""")

    def test_successful_synthetic_rss_and_quotes_publish_and_original_reader_roundtrip(self):
        result=json.loads(self.child(r"""
import sys,io,json,contextlib,hashlib
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,sys.argv[1])
from v5_shadow.cloud_us_collector import load_owner,audit_modules,verify
from v5_shadow.cloud_transport import run_original_us_cli
owner,transport=load_owner(Path(sys.argv[2]));root=Path(sys.argv[3])
owner._capture_now=lambda value=None:datetime(2026,10,10,9,0,16,tzinfo=timezone.utc)
counts={'quote':0,'rss':0,'direct':0}
class Response(io.BytesIO):status=200
class Proxy:
 def open(self,request,*args,**kwargs):
  url=request.full_url
  if 'qt.gtimg.cn' in url:
   counts['quote']+=1;records=[]
   for name in url.split('q=',1)[1].split(','):
    fields=['']*31;fields[1]=name;fields[2]=name[2:];fields[3]='110';fields[4]='100';fields[30]='20261009160000'
    records.append('v_'+name+'="'+'~'.join(fields)+'";')
   return Response(('\n'.join(records)).encode())
  assert 'news.google.com/rss/' in url,url
  counts['rss']+=1
  return Response(b'<rss version="2.0"><channel><item><title>NVIDIA semiconductor earnings growth - Reuters</title><description>NVIDIA reports semiconductor revenue growth.</description><link>https://example.invalid/synthetic-nvidia</link><source url="https://example.invalid">Reuters</source><pubDate>Fri, 09 Oct 2026 19:00:00 GMT</pubDate></item></channel></rss>')
class Direct:
 def open(self,*args,**kwargs):counts['direct']+=1;raise AssertionError('DIRECT_FORBIDDEN')
def audit(event,args):
 if event.startswith(('socket.connect','socket.getaddrinfo','socket.sendto')):raise AssertionError('REAL_NETWORK_FORBIDDEN')
sys.addaudithook(audit)
output=io.StringIO()
with contextlib.redirect_stdout(output):
 status=run_original_us_cli(owner,transport,['--data-root',str(root),'--trade-date','20261009','--capture-phase','POST_CLOSE','--allow-late-post-close','--timeout','1'],allow_network_capture=True,transport_options={'proxy_url':'http://proxy.invalid','proxy_opener':Proxy(),'direct_opener':Direct()})
from infrastructure.research_peripheral_store import ResearchPeripheralStore
saved=json.loads((root/'research/peripherals/20261009/external_finance.json').read_bytes())
before={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
read=ResearchPeripheralStore(root).read_exact('20261009','external_finance')
assert read==saved,(read.keys(),saved.keys())
after={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()};assert before==after
verify(Path(sys.argv[2]));audit_modules()
print(json.dumps({'exit':status,'summary':json.loads(output.getvalue()),'counts':counts,'status':saved['status'],'items':saved['item_count'],'snapshot':saved['market_snapshot'],'files':[str(p.relative_to(root)) for p in root.rglob('*.json')]}))
""",self.root/'synthetic-success'))
        self.assertEqual(result['exit'],0,result)
        self.assertEqual(result['counts'],dict(quote=1,rss=5,direct=0))
        self.assertEqual(result['status'],'READY',result)
        self.assertGreater(result['items'],0)
        self.assertEqual(result['snapshot']['status'],'READY',result)
        self.assertEqual(len(result['snapshot']['quotes']),33)
        self.assertEqual(len(result['snapshot']['rows']),24)
        self.assertTrue(all(row['status']=='READY' for row in result['snapshot']['rows']))
        self.assertFalse(result['snapshot']['orders_sent'])
        self.assertFalse(result['snapshot']['production_allowed'])
        self.assertEqual(len(result['files']),3)

    def test_normal_interpreter_cache_is_accepted_without_rewriting(self):
        self.child(r"""
import sys,shutil,tempfile,py_compile
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from v5_shadow.cloud_us_collector import load_owner
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp)/'owner';shutil.copytree(sys.argv[2],root)
 cache=Path(py_compile.compile(str(root/'ops/us_market_digest.py'),doraise=True))
 before=cache.read_bytes();load_owner(root);assert cache.read_bytes()==before
""")
