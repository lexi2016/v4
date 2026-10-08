"""Actual loopback HTTP and HTML readback of committed synthetic results."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from test_shadow_store import result
from v5_shadow.shadow_store import publish_shadow

class ReadonlyWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / '.v5-shadow-root').write_text('v5.shadow-root.v1\n')
        self.value = result()
        self.value.legacy_screen['excluded'][0].update(name='<script>alert(1)</script>', reason_for_exclusion='两道门均未通过')
        self.ref = publish_shadow(self.root, self.value)
        from v5_shadow.web import create_server
        self.server = create_server(self.root, host='127.0.0.1', port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.url = 'http://127.0.0.1:' + str(self.server.server_address[1])
    def close_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)
    def get(self, path):
        try:
            with urllib.request.urlopen(self.url + path, timeout=5) as response:
                return response.status, response.headers, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read().decode()
    def test_api_and_page_same_committed_run(self):
        status, headers, body = self.get('/api/runs?target_date=20261008')
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['runs'][0]['run_id'], self.ref.run_id)
        query = '?target_date=20261008&run_id=' + self.ref.run_id
        status, _, body = self.get('/api/result' + query)
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertEqual(data['reference']['artifact_sha256'], self.ref.artifact_sha256)
        self.assertEqual(data['result']['run_id'], self.ref.run_id)
        status, _, html = self.get('/' + query)
        self.assertEqual(status, 200, html)
        for text in ('V5', '20261008', self.ref.run_id, self.ref.artifact_sha256, 'HK.00001', '两道门均未通过', 'SYNTHETIC', '未验证'):
            self.assertIn(text, html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('no-store', headers.get('Cache-Control', ''))
    def test_date_without_run_is_not_successful_zero(self):
        status, _, body = self.get('/api/runs?target_date=20261009')
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['status'], 'NOT_RUN')
        status, _, html = self.get('/?target_date=20261009')
        self.assertEqual(status, 200, html)
        self.assertIn('尚无已提交结果', html)
        self.assertNotIn(self.ref.run_id, html)
    def test_wrong_date_and_traversal_rejected(self):
        for path in ('/api/result?target_date=20261009&run_id=' + self.ref.run_id,
                     '/api/result?target_date=20261008&run_id=../../etc/passwd',
                     '/api/runs?target_date=20260230'):
            status, _, body = self.get(path)
            self.assertIn(status, (400, 404), body)
    def test_corrupted_artifact_cannot_render_success(self):
        p = self.root / 'runs/20261008' / self.ref.run_id / 'artifact.json'
        p.write_text('{}')
        status, _, body = self.get('/api/result?target_date=20261008&run_id=' + self.ref.run_id)
        self.assertEqual(status, 409, body)
        self.assertEqual(json.loads(body)['status'], 'INVALID')
    def test_readonly_and_localhost_only(self):
        before = {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.root.rglob('*') if p.is_file()}
        self.get('/api/runs?target_date=20261008')
        req = urllib.request.Request(self.url + '/api/run', data=b'{}', method='POST')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        self.assertIn(caught.exception.code, (405, 501))
        after = {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        from v5_shadow.web import create_server
        with self.assertRaises(ValueError):create_server(self.root, host='0.0.0.0', port=0)
if __name__ == '__main__':
    unittest.main()
