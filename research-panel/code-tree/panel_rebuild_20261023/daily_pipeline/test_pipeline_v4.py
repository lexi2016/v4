"""V4 isolated cross-day and identity tests; no real future market observations."""
import importlib.util,tempfile,unittest,copy,struct,zipfile,json
from pathlib import Path
import test_integration as old
HERE=Path(__file__).resolve().parent
class PipelineV4Tests(unittest.TestCase):
 def setUp(self):
  self.assertTrue((HERE/'pipeline_v4.py').exists(),'V4 volume-aware pipeline is not implemented')
  s=importlib.util.spec_from_file_location('daily_v4_test',HERE/'pipeline_v4.py');self.p=importlib.util.module_from_spec(s);s.loader.exec_module(self.p)
 def fixture(self,d):
  c=old.fixture(d);mp=Path(c['manifest']['path']);m=self.p.load(mp)
  m['volume_contract']={'volume_encoding':self.p.VOLUME.RAW_ENCODING}
  self.p.save(mp,m);c['manifest']['sha256']=self.p.sha(mp)
  sp=Path(c['sidecar']['path']);s=self.p.load(sp);s['manifest_sha256']=self.p.sha(mp);self.p.save(sp,s);c['sidecar']['sha256']=self.p.sha(sp)
  return c
 def test_new_day_staged_schema_bound_and_idempotent(self):
  with tempfile.TemporaryDirectory(dir=HERE) as d:
   c=self.fixture(d);r=self.p.run(c,Path(d)/'run','stage');self.assertEqual(r['counts']['passed'],2)
   self.assertEqual(r['counts']['formula_compute_calls'],2);self.assertFalse(r['publish_allowed'])
   v=Path(r['version_path']);m=self.p.load(v/'PARTITION_MANIFEST.json')
   self.assertEqual(m['volume_contract']['volume_encoding'],self.p.VOLUME.OUTPUT_ENCODING)
   self.assertEqual(m['volume_contract']['decoder_sha256'],self.p.VOLUME.DECODER_SHA)
   for x in r['stocks'].values():self.assertEqual(x['g4_volume_check']['status'],'NUMERICALLY_VALIDATED')
   r2=self.p.run(c,Path(d)/'run','stage');self.assertEqual(r2['counts']['reused_shards'],2);self.assertEqual(r2['counts']['formula_compute_calls'],0)
   self.assertFalse((Path(d)/'run/CURRENT.json').exists())
 def test_missing_volume_schema_is_not_guessed(self):
  with tempfile.TemporaryDirectory(dir=HERE) as d:
   c=old.fixture(d)
   with self.assertRaisesRegex(ValueError,'VOLUME_SCHEMA'):self.p.prepare(c)
 def test_old_cache_cannot_reuse_as_v4(self):
  recs={r['symbol']:r for r in self.p.load(self.p.PROJECT/'data/PARTITION_MANIFEST.json')['securities']}
  self.assertIsNone(self.p.cached_rows([self.p.PROJECT/'cache/conditional_computed'], '000001.SZ',20261023,recs['000001.SZ'], {'securities':{}}))
 def test_bad_g4_units_quarantine_only_affected_stock(self):
  with tempfile.TemporaryDirectory(dir=HERE) as d:
   c=self.fixture(d);path=Path(c['daily']['path'])
   with zipfile.ZipFile(path) as z:cod=z.read('sz261026.cod');md=bytearray(z.read('sz261026.md1'))
   struct.pack_into('<d',md,72,1e10)
   with zipfile.ZipFile(path,'w') as z:z.writestr('sz261026.cod',cod);z.writestr('sz261026.md1',md)
   c['daily']['sha256']=self.p.sha(path);sp=Path(c['source_receipt']['path']);r=self.p.load(sp);r['daily_sha256']=self.p.sha(path);self.p.save(sp,r);c['source_receipt']['sha256']=self.p.sha(sp)
   result=self.p.run(c,Path(d)/'run','stage');self.assertEqual(result['counts']['passed'],1);self.assertEqual(result['counts']['failed'],1)
   self.assertIn('VWAP_OUTSIDE_RAW_OHLC',result['stocks']['000001.SZ']['reason']);self.assertEqual(result['stocks']['000002.SZ']['status'],'PASS')
 def test_staged_decoded_schema_supports_next_day_without_redecode(self):
  with tempfile.TemporaryDirectory(dir=HERE) as d:
   root=Path(d);c=self.fixture(d);first=self.p.run(c,root/'first','stage');v=Path(first['version_path'])
   c['manifest']={'path':str(v/'PARTITION_MANIFEST.json'),'sha256':self.p.sha(v/'PARTITION_MANIFEST.json')}
   c['sidecar']={'path':str(v/'PARTITION_AUDIT_SIDECAR.json'),'sha256':self.p.sha(v/'PARTITION_AUDIT_SIDECAR.json')}
   for k in ('date','vintage','g4_trade_date','events_vintage'):c[k]='20261027'
   oldzip=Path(c['daily']['path']);newzip=root/'g4day_20261027.zip'
   with zipfile.ZipFile(oldzip) as z:cod=z.read('sz261026.cod');md=z.read('sz261026.md1')
   with zipfile.ZipFile(newzip,'w') as z:z.writestr('sz261027.cod',cod);z.writestr('sz261027.md1',md)
   c['daily']={'path':str(newzip),'sha256':self.p.sha(newzip)}
   sp=root/'next-source.json';self.p.save(sp,{'date':'20261027','daily_sha256':self.p.sha(newzip),'events_sha256':c['events']['sha256'],'daily_source_url':'fixture://day27','events_source_url':'fixture://unchanged'})
   c['source_receipt']={'path':str(sp),'sha256':self.p.sha(sp)}
   second=self.p.run(c,root/'second','stage');self.assertEqual(second['counts']['passed'],2)
   for r in second['stocks'].values():
    self.assertEqual(r['volume_check']['input_encoding'],self.p.VOLUME.OUTPUT_ENCODING)
    self.assertEqual(r['volume_check']['decoded_rows'],0);self.assertEqual(r['rows'],3)
   self.assertFalse(second['publish_allowed'])
 def test_encoding_schema_enters_run_identity(self):
  with tempfile.TemporaryDirectory(dir=HERE) as d:
   c=self.fixture(d);a=self.p.prepare(c)[-1]
   mp=Path(c['manifest']['path']);m=self.p.load(mp);m['volume_contract']=self.p.VOLUME.contract();self.p.save(mp,m);c['manifest']['sha256']=self.p.sha(mp)
   sp=Path(c['sidecar']['path']);x=self.p.load(sp);x['manifest_sha256']=self.p.sha(mp);self.p.save(sp,x);c['sidecar']['sha256']=self.p.sha(sp)
   b=self.p.prepare(c)[-1]
   self.assertNotEqual(self.p.run_key(a),self.p.run_key(b))
   self.assertEqual(b['source_volume_contract']['decoder_sha256'],self.p.VOLUME.DECODER_SHA)
 def test_all_live_policy_stocks_remain_blocked(self):
  live=self.p.load(self.p.PROJECT/'cache/READ_INVALIDATIONS.json')
  with tempfile.TemporaryDirectory(dir=HERE) as d:
   for symbol in live['securities']:
    r=self.p.query_snapshot(Path(d),symbol,'20261023');self.assertFalse(r['research_consumption_allowed']);self.assertIsNone(r['row'])
if __name__=='__main__':unittest.main()
