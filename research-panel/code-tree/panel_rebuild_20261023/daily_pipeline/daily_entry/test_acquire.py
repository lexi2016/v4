import importlib.util, unittest, io, zipfile
from pathlib import Path
class AcquireTests(unittest.TestCase):
 def module(self):
  p=Path(__file__).with_name('acquire.py');self.assertTrue(p.exists(),'actual isolated acquisition entry missing')
  s=importlib.util.spec_from_file_location('acquire',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_scope_includes_quarantine(self):
  m=self.module();self.assertEqual(m.full_scope({'securities':[{'symbol':'000528.SZ'},{'symbol':'600000.SH'},{'symbol':'920001.BJ'}]}),['000528.SZ','600000.SH'])
 def test_event_index_not_semantic_change(self):
  m=self.module();a=[{'record_index':1,'code':'000001','market':0,'date':20261023,'category':1,'c1':1}];b=[dict(a[0],record_index=2)];self.assertEqual(m.changed_symbols(a,b),[])
 def test_event_value_change_is_blocked_symbol(self):
  m=self.module();a=[{'record_index':1,'code':'000001','market':0,'date':20261023,'category':1,'c1':1}];b=[dict(a[0],c1=2)];self.assertEqual(m.changed_symbols(a,b),['000001.SZ'])
 def test_unsafe_zip_rejected(self):
  m=self.module();b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('../gbbq','x')
  with self.assertRaisesRegex(ValueError,'UNSAFE'):m.inspect_zip(b.getvalue())
 def test_zip_size_cap(self):
  m=self.module();b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('gbbq','123456')
  with self.assertRaisesRegex(ValueError,'SIZE'):m.inspect_zip(b.getvalue(),5)
 def test_http_get_rejects_changed_etag(self):
  from unittest.mock import patch
  m=self.module()
  class Response:
   status=200
   def __init__(self,headers):self.headers=headers
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def read(self,n):return b'abcd'
  class Opener:
   def __init__(self):self.responses=iter([Response({'Content-Length':'4','ETag':'one'}),Response({'ETag':'two'})])
   def open(self,*a,**kw):return next(self.responses)
  with patch.object(m.urllib.request,'build_opener',return_value=Opener()):
   with self.assertRaisesRegex(ValueError,'ETAG_CHANGED'):m.acquire_url('https://www.tdx.com.cn/products/data/data/g4day/20261026.zip',Path(__file__).parent/'test_acquire_outputs')
 def test_http_get_isolated_bytes_hash_and_length(self):
  from unittest.mock import patch
  import hashlib, uuid
  m=self.module();b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('fixture.txt','synthetic not market data')
  body=b.getvalue();calls=[]
  class Response:
   status=200
   headers={'Content-Length':str(len(body)),'ETag':'fixture'}
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def read(self,n):return body[:n]
  class Opener:
   def open(self,req,**kw):calls.append(req);return Response()
  root=Path(__file__).parent/'test_acquire_outputs'/uuid.uuid4().hex
  with patch.object(m.urllib.request,'build_opener',return_value=Opener()):r=m.acquire_url('https://www.tdx.com.cn/products/data/data/g4day/20261026.zip',root)
  self.assertEqual([x.get_method() for x in calls],['HEAD','GET'])
  self.assertEqual(calls[1].get_header('If-match'),'fixture')
  self.assertEqual(Path(r['path']).read_bytes(),body)
  self.assertEqual(r['sha256'],hashlib.sha256(body).hexdigest())
  self.assertEqual(r['bytes'],len(body));self.assertTrue(r['downloaded'])
 def test_changed_archive_decoded_cache_reused_and_verified(self):
  import uuid, types
  m=self.module();self.assertTrue(hasattr(m,'cached_events'),'changed archive cache missing')
  root=Path(__file__).parent/'test_acquire_outputs'/uuid.uuid4().hex
  root.mkdir(parents=True);constants=root/'constants';constants.write_bytes(b'fixture-constants')
  archive=io.BytesIO()
  with zipfile.ZipFile(archive,'w') as z:z.writestr('gbbq',b'fixture-encrypted')
  calls=[]
  def decode(data,constant):calls.append(1);return [{'market':0,'code':'000001','date':20261023,'category':1}]
  engine=types.SimpleNamespace(decode_gbbq=decode)
  a=m.cached_events(archive.getvalue(),'fixture-hash',root,engine,constants,'fixture-decoder-hash')
  b=m.cached_events(archive.getvalue(),'fixture-hash',root,engine,constants,'fixture-decoder-hash')
  self.assertEqual(len(calls),1);self.assertEqual(a[0],b[0]);self.assertTrue(b[2])
  b[0].write_text('[]')
  with self.assertRaisesRegex(ValueError,'DECODED_CACHE'):m.cached_events(archive.getvalue(),'fixture-hash',root,engine,constants,'fixture-decoder-hash')
