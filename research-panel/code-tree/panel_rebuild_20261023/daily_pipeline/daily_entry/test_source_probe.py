import importlib.util, unittest
from pathlib import Path
class ProbeTests(unittest.TestCase):
 def module(self):
  p=Path(__file__).with_name('source_probe.py');self.assertTrue(p.exists(),'metadata probe missing')
  s=importlib.util.spec_from_file_location('probe',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
 def test_only_official_daily_sources(self):
  m=self.module();urls=m.source_urls('20261026');self.assertEqual(len(urls),3);self.assertIn('/g4day/20261026.zip',urls[2]);self.assertTrue(all(x.startswith('https://') for x in urls))
 def test_date_injection_rejected(self):
  m=self.module()
  with self.assertRaises(ValueError):m.source_urls('../20261026')
 def test_conditional_headers(self):
  m=self.module();self.assertEqual(m.conditionals({'etag':'abc','last-modified':'def'}),{'If-None-Match':'abc','If-Modified-Since':'def'})
 def test_missing_headers_not_manufactured(self):
  m=self.module();self.assertEqual(m.conditionals({}),{})
