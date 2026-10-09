"""Original behavioral RED is a subprocess control; no legacy namespace leaks."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

FIXTURE = Path(__file__).parent / 'fixtures/manager_owner'


class ManagerDateGateProcessTests(unittest.TestCase):
    def test_original_owner_still_reproduces_five_admission_failures_without_errors(self):
        result = subprocess.run([sys.executable, '-B', str(FIXTURE/'check_original.py'), '-v'],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('Ran 7 tests', result.stderr)
        self.assertIn('FAILED (failures=5)', result.stderr)
        self.assertNotIn('ERROR:', result.stderr)

    def test_production_loaded_owner_admission_boundaries(self):
        result = subprocess.run([sys.executable, '-B', str(FIXTURE/'check_candidate.py'), '-v'],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ran 8 tests', result.stderr)


if __name__ == '__main__':unittest.main()
