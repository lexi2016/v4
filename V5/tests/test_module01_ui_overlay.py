"""Run the original guarded installer on disposable, exact-source candidates.

V5_MODULE01_WEB_ROOT points to the assembled original frontend dependency tree.
It provides three pinned unchanged dependencies; no fixture replacements exist.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1] / 'ui/manager-workbench'


@unittest.skipUnless(os.environ.get('V5_MODULE01_WEB_ROOT'), 'Original assembled web dependency root required')
class Module01OverlayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='module01-overlay-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.package = root / 'package'
        shutil.copytree(BASE, self.package)
        self.manifest = json.loads((self.package / 'overlay-manifest.json').read_bytes())
        self.web = root / 'web'
        self.web.mkdir()
        (self.web / '.v5-ui-candidate').write_text('v5.ui-candidate.v1\n')
        for relative in self.manifest['unchanged']:
            source = Path(os.environ['V5_MODULE01_WEB_ROOT']) / relative
            target = self.web / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for row in self.manifest['changes']:
            target = self.web / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.package / row['source'], target)

    def apply(self):
        return subprocess.run([sys.executable, '-B', str(self.package / 'apply_candidate.py'),
            '--web-root', str(self.web)], capture_output=True, text=True, timeout=30)

    def snapshot(self):
        return {str(p.relative_to(self.web)): p.read_bytes() for p in self.web.rglob('*') if p.is_file()}

    def test_reapplying_verified_current_candidate_succeeds_without_byte_changes(self):
        before = self.snapshot()
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), before)
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'SOURCE_OVERLAY_APPLIED_NOT_TESTED_OR_BUILT')

    def test_changed_daily_channel_remains_rejected_before_any_write(self):
        path = self.web / 'src/manager-selection/dailyChannels.ts'
        path.write_bytes(path.read_bytes() + b'\n// synthetic unexpected drift\n')
        before = self.snapshot()
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('UI_BASE_FILE_MISMATCH:src/manager-selection/dailyChannels.ts', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_unmodified_dependency_pin_still_rejects_drift(self):
        path = self.web / 'src/manager-selection/dailyChannels.testHelper.ts'
        path.write_bytes(path.read_bytes() + b'\n// synthetic dependency drift\n')
        before = self.snapshot()
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('UI_BASE_DEPENDENCY_MISMATCH:src/manager-selection/dailyChannels.testHelper.ts', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_unexpected_overlay_source_bytes_are_rejected_before_any_write(self):
        row = self.manifest['changes'][0]
        source = self.package / row['source']
        source.write_bytes(source.read_bytes() + b'\n// synthetic overlay drift\n')
        before = self.snapshot()
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('UI_OVERLAY_SOURCE_MISMATCH:' + row['path'], result.stderr)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
