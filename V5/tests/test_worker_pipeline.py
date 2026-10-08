"""End-to-end worker, parent commit and CLI readback; SYNTHETIC inputs only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_contracts import manifest, request
from test_frozen_reader import SCRIPT
from v5_shadow.digests import canonical_bytes, sha256_json
from v5_shadow.health import module_code_digest

BASE = Path(__file__).resolve().parents[1]
RELEASE = 'v5-rebound-shadow-r1'

class WorkerPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.app = self.root / 'app'
        self.app.mkdir()
        for directory in ('src/v5_shadow', 'vendor/rebound_baseline', 'contracts'):
            shutil.copytree(BASE / directory, self.app / directory,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copyfile(BASE / 'uv.lock', self.app / 'uv.lock')
        if (BASE / 'run_shadow.py').is_file():
            shutil.copyfile(BASE / 'run_shadow.py', self.app / 'run_shadow.py')
        if (BASE / 'module_release.json').is_file():
            shutil.copyfile(BASE / 'module_release.json', self.app / 'module_release.json')
        self.source = self.root / 'synthetic-source'
        self.source.mkdir()
        self.output = self.root / 'shadow-output'
        self.output.mkdir()
        (self.output / '.v5-shadow-root').write_text('v5.shadow-root.v1\n')
        self.env = dict(os.environ, PYTHONPATH=str(self.app / 'src') + os.pathsep + str(BASE / 'tests'),
                        PYTHONDONTWRITEBYTECODE='1')
        descriptor = json.loads((self.app / 'contracts/rebound_source_manifest.json').read_text())
        module = manifest(RELEASE)
        module['code_manifest_sha256'] = module_code_digest(self.app / 'src/v5_shadow')
        module['dependency_lock_sha256'] = hashlib.sha256((self.app / 'uv.lock').read_bytes()).hexdigest()
        calendar = self.app / 'vendor/rebound_baseline/contracts/market_calendar_2026.json'
        self.config = dict(schema_version='v5.composition.v1', revision=1,
                           modules={'rebound_shadow': module}, bindings={'rebound_shadow': dict(
                               authority_root=str(self.source), shadow_root=str(self.output),
                               calendar_sha256=hashlib.sha256(calendar.read_bytes()).hexdigest(),
                               source_capsule_sha256=sha256_json(descriptor['entries']), input_snapshot_sha256=None)})
        self.config_path = self.root / 'composition.json'
        self.config_path.write_bytes(canonical_bytes(self.config))
        self.req = request()
        self.req.update(execution_kind='SHADOW_REPLAY', composition_sha256=sha256_json(self.config))
        self.req_path = self.root / 'request.json'
        self.req_path.write_bytes(canonical_bytes(self.req))

    def call(self, *args):
        launcher = self.app / 'run_shadow.py'
        entry = [str(launcher)] if launcher.is_file() else ['-m', 'v5_shadow']
        p = subprocess.run([sys.executable, '-B', *entry, *args],
                           env=self.env, capture_output=True, text=True, timeout=90)
        self.assertTrue(p.stdout.strip(), p.stderr)
        return p.returncode, json.loads(p.stdout)

    def fixture(self):
        p = subprocess.run([sys.executable, '-B', '-c', SCRIPT, str(self.app), str(self.source), 'fixture'],
                           env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        # Successful runs require an explicit input identity. Bind the actual
        # synthetic fixture bytes, not a made-up digest or real-owner claim.
        digest = sha256_json(self.source_bytes())
        self.config['bindings']['rebound_shadow']['input_snapshot_sha256'] = digest
        self.config_path.write_bytes(canonical_bytes(self.config))
        self.req.update(input_snapshot_sha256=digest, composition_sha256=sha256_json(self.config))
        self.req_path.write_bytes(canonical_bytes(self.req))

    def run_shadow(self):
        return self.call('run-shadow', '--composition', str(self.config_path), '--request', str(self.req_path),
                         '--output-root', str(self.output))

    def source_bytes(self):
        return {str(p.relative_to(self.source)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.source.rglob('*') if p.is_file()}

    def test_worker_commit_readback_and_repeat_same_run(self):
        self.fixture()
        before = self.source_bytes()
        code, first = self.run_shadow()
        self.assertEqual(code, 0, first)
        self.assertEqual(first['status'], 'COMPLETED')
        self.assertEqual(first['result']['legacy_screen']['coverage']['strict_count'], 1)
        self.assertFalse(first['result']['natural_verified'])
        self.assertEqual(first['data_kind'], 'SYNTHETIC')
        run_id = first['reference']['run_id']
        self.assertEqual(first['result']['run_id'], run_id)
        code, read = self.call('read-result', '--output-root', str(self.output), '--target-date', '20261008', '--run-id', run_id)
        self.assertEqual(code, 0, read)
        self.assertEqual(read['result'], first['result'])
        code, second = self.run_shadow()
        self.assertEqual(code, 0, second)
        self.assertEqual(second['reference'], first['reference'])
        self.assertEqual(second['result'], first['result'])
        self.assertEqual(self.source_bytes(), before)

    def test_missing_input_saved_as_unknown(self):
        code, result = self.run_shadow()
        self.assertEqual(code, 2, result)
        self.assertEqual(result['status'], 'CANNOT_CONFIRM')
        self.assertIsNone(result['result']['evaluated_count'])
        code, read = self.call('read-result', '--output-root', str(self.output), '--target-date', '20261008',
                              '--run-id', result['reference']['run_id'])
        self.assertEqual(code, 2, read)
        self.assertEqual(read['result'], result['result'])

    def test_code_drift_rejected_before_publication(self):
        path = self.app / 'src/v5_shadow/legacy_adapter.py'
        path.write_text(path.read_text() + '\n# synthetic byte drift\n')
        code, result = self.run_shadow()
        self.assertEqual(code, 3, result)
        self.assertIn('RUNTIME_CODE_MANIFEST_SHA256_MISMATCH', result['reason_codes'])
        self.assertFalse((self.output / 'refs').exists())

if __name__ == '__main__':
    unittest.main()
