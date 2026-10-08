"""Reuse all supplied 17 recovery + 9 install tests with synthetic disk fixtures."""
import importlib
import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path

from release_test_fixture import synthetic_package

test_root = Path(__file__).resolve().parent
source_root = Path(os.environ.get('RELEASE_SOURCE_ROOT', test_root.parent / 'source')).resolve()
sys.path.insert(0, str(source_root / 'blocked_candidate_ops'))
import api_candidate_install_r2 as install

temp_root = test_root / 'tmp'
temp_root.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='existing-26-', dir=temp_root) as name:
    root = Path(name)
    with synthetic_package(install, source_root, root) as scope:
        test_install = importlib.import_module('test_api_candidate_install_r2')
        test_recovery = importlib.import_module('test_api_candidate_recovery')
        test_recovery.E = root
        if hasattr(test_recovery, 'DEFAULT_GUARD'):
            test_recovery.DEFAULT_GUARD = install.GUARD
        print(f'Python {platform.python_version()}; source={source_root}', flush=True)
        print(f'SYNTHETIC_UNIT_FIXTURE_ONLY; scope_items={len(scope)}; no host service operations', flush=True)
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
                                   for module in (test_recovery, test_install))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)
