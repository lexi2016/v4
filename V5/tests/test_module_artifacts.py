"""Immutable daily API generations, atomic publication and per-module rollback."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from v5_shadow.digests import canonical_bytes, sha256_json
from v5_shadow.module_api import create_module_server, response_key


class ModuleArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / '.v5-module-root').write_text('v5.module-root.v1:manager\n')
        self.config = dict(schema_version='v5.module_api.v1', module_id='manager', release_id='r1',
                           data_root=str(self.root), routes=['/api/v4/manager/research/workspace'])

    def record(self, date='20261008', revision=1):
        payload = {'target_trade_date': date, 'revision': revision, 'RESEARCH_ONLY': True,
                   'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
        return dict(schema_version='v5.module_response.v1', module_id='manager', release_id='r1',
                    path=self.config['routes'][0], query={'date': date}, payload=payload,
                    payload_sha256=sha256_json(payload), source_input_sha256='a' * 64,
                    data_kind='SYNTHETIC', generated_at='2026-10-08T12:00:00+08:00', status_code=200)

    def publish(self, records, expected=None):
        from v5_shadow.module_artifacts import publish_generation
        return publish_generation(self.config, records, expected_generation=expected)['generation_sha256']

    def api(self):
        server = create_module_server(self.config)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:' + str(server.server_address[1])

    def read(self, url, date='20261008'):
        try:
            with urlopen(url + self.config['routes'][0] + '?date=' + date, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_running_api_sees_atomic_new_generation(self):
        url = self.api()
        first = self.publish([self.record()])
        self.assertEqual(self.read(url), (200, self.record()['payload']))
        second = self.publish([self.record(revision=2)], first)
        self.assertNotEqual(first, second)
        self.assertEqual(self.read(url), (200, self.record(revision=2)['payload']))

    def test_new_date_preserves_previous_date(self):
        first = self.publish([self.record()])
        self.publish([self.record('20261009')], first)
        url = self.api()
        self.assertEqual(self.read(url)[0], 200)
        self.assertEqual(self.read(url, '20261009')[0], 200)
        self.assertEqual(self.read(url, '20261010')[0], 503)

    def test_old_generation_and_objects_remain_immutable(self):
        first = self.publish([self.record()])
        saved = {p.relative_to(self.root): p.read_bytes() for folder in ('objects', 'generations')
                 for p in (self.root / folder).glob('*.json')}
        self.publish([self.record(revision=2)], first)
        self.assertTrue(saved)
        for path, raw in saved.items():
            self.assertEqual((self.root / path).read_bytes(), raw)

    def test_legacy_records_adopted_on_first_publication(self):
        old = self.record('20261007')
        path = self.root / 'responses' / (response_key('manager', old['path'], old['query']) + '.json')
        path.parent.mkdir()
        path.write_bytes(canonical_bytes(old))
        self.publish([self.record()])
        self.assertEqual(self.read(self.api(), '20261007'), (200, old['payload']))
        self.assertEqual(path.read_bytes(), canonical_bytes(old))

    def test_stale_compare_and_swap_rejected(self):
        first = self.publish([self.record()])
        self.publish([self.record(revision=2)], first)
        active = (self.root / 'active.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'GENERATION_CONFLICT'):
            self.publish([self.record(revision=3)], first)
        self.assertEqual((self.root / 'active.json').read_bytes(), active)

    def test_invalid_payload_never_replaces_success(self):
        first = self.publish([self.record()])
        bad = self.record(revision=2)
        bad['payload_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.publish([bad], first)
        self.assertEqual(self.read(self.api()), (200, self.record()['payload']))

    def test_other_release_rejected(self):
        bad = self.record()
        bad['release_id'] = 'r2'
        with self.assertRaises(ValueError):
            self.publish([bad])
        self.assertFalse((self.root / 'active.json').exists())

    def test_duplicate_response_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            self.publish([self.record(), self.record(revision=2)])

    def test_same_snapshot_reuses_generation(self):
        first = self.publish([self.record()])
        self.assertEqual(self.publish([self.record()], first), first)

    def test_rollback_is_explicit_atomic_activation(self):
        from v5_shadow.module_artifacts import activate_generation
        first = self.publish([self.record()])
        second = self.publish([self.record(revision=2)], first)
        url = self.api()
        result = activate_generation(self.config, first, expected_generation=second)
        self.assertEqual(result['generation_sha256'], first)
        self.assertEqual(self.read(url), (200, self.record()['payload']))

    def test_bad_active_index_does_not_fall_back_to_legacy(self):
        self.publish([self.record()])
        (self.root / 'active.json').write_text('{}')
        self.assertEqual(self.read(self.api())[0], 409)

    def test_missing_object_does_not_fall_back(self):
        self.publish([self.record()])
        for path in (self.root / 'objects').glob('*.json'):
            path.unlink()
        self.assertEqual(self.read(self.api())[0], 409)

    def test_symlink_object_directory_rejected(self):
        first = self.publish([self.record()])
        source = self.root / 'objects'
        source.rename(self.root / 'real_objects')
        source.symlink_to(self.root / 'real_objects', target_is_directory=True)
        self.assertEqual(self.read(self.api())[0], 409)
        with self.assertRaises((ValueError, OSError)):
            self.publish([self.record(revision=2)], first)

    def test_two_publishers_with_same_expected_head_only_one_wins(self):
        first = self.publish([self.record()])
        barrier = threading.Barrier(2)
        results = []
        def worker(revision):
            barrier.wait()
            try:
                results.append(('ok', self.publish([self.record(revision=revision)], first)))
            except ValueError as error:
                results.append(('error', str(error)))
        threads = [threading.Thread(target=worker, args=(revision,)) for revision in (2, 3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual([r[0] for r in results].count('ok'), 1)
        self.assertEqual([r[0] for r in results].count('error'), 1)
        self.assertIn('GENERATION_CONFLICT', next(r[1] for r in results if r[0] == 'error'))


if __name__ == '__main__':
    unittest.main()
