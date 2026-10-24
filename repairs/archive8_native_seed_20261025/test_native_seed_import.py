"""Registered focused synthetic IO checks; no real native or panel IO."""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


CONFIG = json.loads(Path(sys.argv[1]).read_text())
GO = json.loads(Path(sys.argv[2]).read_text())
assert GO['authorized'] is True and GO['decision'] == 'GO_NATIVE_HELPER_FOCUSED_SYNTHETIC_REVIEW'
assert GO['execution_id'] == CONFIG['execution_id']
assert GO['code_sha256'] == sha(__file__) and GO['config_sha256'] == sha(sys.argv[1])
assert GO['input_sha256'] == CONFIG['input']['sha256']
assert sha(CONFIG['input']['path']) == CONFIG['input']['sha256']
for ref in json.loads(Path(CONFIG['input']['path']).read_text())['files']:
    assert sha(ref['path']) == ref['sha256'], 'FROZEN_CONTROL_DRIFT'
for ref in GO['registry_receipts'].values():
    assert sha(ref['path']) == ref['sha256']
    assert json.loads(Path(ref['path']).read_text())['event_sha256'] == ref['event_sha256']
RUN = Path(CONFIG['run_root']); RUN.mkdir(exist_ok=False)
spec = importlib.util.spec_from_file_location('exact8_seed_helper_under_review', CONFIG['helper']['path'])
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
ORIGINAL_NATIVE = helper.NATIVE


def audit(event, args):
    if event.startswith('socket.') or event == 'subprocess.Popen':
        raise RuntimeError('SYNTHETIC_ONLY_NO_NETWORK_OR_SUBPROCESS')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        if args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            assert Path(os.fsdecode(args[0])).resolve().is_relative_to(RUN), 'OUT_OF_RUN_WRITE'
    if event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.link'):
        for value in args[:2] if event in ('os.rename', 'os.link') else args[:1]:
            if isinstance(value, (str, bytes, os.PathLike)):
                assert Path(os.fsdecode(value)).resolve().is_relative_to(RUN), 'OUT_OF_RUN_MUTATION'


sys.addaudithook(audit)


class FakeOriginalPublisher:
    @contextlib.contextmanager
    def publication_lock(self, root):
        yield


class FocusedSeedIO(unittest.TestCase):
    def setUp(self):
        self.root = RUN / self._testMethodName; self.root.mkdir()
        self.native = self.root / 'native'; self.native.mkdir()
        helper.NATIVE = self.native
        self.pointer = self.root / 'pointer'; self.pointer.write_bytes(b'old-generation\n')
        before = self.root / 'before'; before.write_bytes(self.pointer.read_bytes())
        self.panel = self.root / 'old-panel'; self.panel.write_bytes(b'synthetic-old-panel')
        st = self.panel.stat()
        counts = dict(zip(sorted(helper.CODES), [17, 29, 25, 21, 39, 34, 38, 18]))
        seeds = {}
        for code, rows in counts.items():
            source = self.root / (code + '.source')
            # Synthetic non-market byte strings test exact IO preservation only.
            source.write_bytes((code.encode() + b'x' * 26) * rows)
            seeds[code] = dict(destination=str(self.native / ('sh' + code + '.day')),
                               original_bytes=dict(path=str(source), sha256=sha(source)),
                               rows=rows, last_date=20261019)
        self.config = dict(execution_id='SYNTHETIC_EXACT8', generation_id='synthetic-new',
                           data_root=str(self.root), journal_path=str(self.root / 'journal.json'),
                           seeds=seeds, pointer_CAS=[dict(path=str(self.pointer), before=dict(path=str(before), sha256=sha(before)))],
                           metadata_CAS=[], panel_stat_CAS=[dict(path=str(self.panel), stat_binding=dict(st_dev=st.st_dev, st_ino=st.st_ino, st_size=st.st_size, st_mtime_ns=st.st_mtime_ns))])
        self.publisher = FakeOriginalPublisher()

    def tearDown(self):
        helper.NATIVE = ORIGINAL_NATIVE

    def test_success_exact_bytes_and_explicit_owned_recovery(self):
        result = helper.create_seeds(self.config, self.publisher)
        self.assertEqual(result['status'], 'IMPORTED_SEEDS_ONLY_AWAITING_ORIGINAL_ADOPTION')
        for item in self.config['seeds'].values():
            self.assertEqual(Path(item['destination']).read_bytes(), Path(item['original_bytes']['path']).read_bytes())
        recovered = helper.rollback_import(self.config, self.publisher)
        self.assertEqual(recovered['status'], 'ROLLED_BACK_OWNED_IMPORT_ONLY')
        self.assertFalse(list(self.native.iterdir()))

    def test_preexisting_destination_is_preserved(self):
        destination = Path(next(iter(self.config['seeds'].values()))['destination'])
        destination.write_bytes(b'third-party')
        with self.assertRaisesRegex(RuntimeError, 'EXPECTED_ABSENT'):
            helper.create_seeds(self.config, self.publisher)
        self.assertEqual(destination.read_bytes(), b'third-party')
        self.assertFalse(Path(self.config['journal_path']).exists())

    def test_racing_foreign_hardlink_eexist_preserved_both_rollback_paths(self):
        original = os.link; raced = []
        def competitor(source, destination):
            original(source, destination); raced.append(Path(destination))
            raise FileExistsError('competitor linked the same owned temp first')
        with patch.object(helper.os, 'link', side_effect=competitor):
            with self.assertRaises(FileExistsError):
                helper.create_seeds(self.config, self.publisher)
        self.assertEqual(len(raced), 1)
        expected = raced[0].read_bytes()
        record = json.loads(Path(self.config['journal_path']).read_text())
        self.assertFalse(record['created'][0]['linked'])
        self.assertIn(str(raced[0]), record['unowned_or_unacknowledged_destinations_preserved'])
        helper.rollback_import(self.config, self.publisher)
        self.assertEqual(raced[0].read_bytes(), expected)

    def test_link_failure_rolls_back_only_owned_complete_temps_and_seeds(self):
        original = os.link; calls = []
        def fail_fourth(source, destination):
            calls.append(str(destination))
            if len(calls) == 4:
                raise OSError('injected link failure')
            return original(source, destination)
        with patch.object(helper.os, 'link', side_effect=fail_fourth):
            with self.assertRaises(OSError):
                helper.create_seeds(self.config, self.publisher)
        self.assertFalse(list(self.native.iterdir()))
        self.assertEqual(json.loads(Path(self.config['journal_path']).read_text())['status'], 'ROLLED_BACK_OWNED_IMPORT_ONLY')

    def test_cas_change_stops_cleanup_and_preserves_conflicting_state(self):
        original = os.link; calls = []
        def change_pointer(source, destination):
            original(source, destination); calls.append(str(destination))
            if len(calls) == 1:
                self.pointer.write_bytes(b'third-party-generation\n')
        with patch.object(helper.os, 'link', side_effect=change_pointer):
            with self.assertRaisesRegex(RuntimeError, 'CAS_BYTES'):
                helper.create_seeds(self.config, self.publisher)
        self.assertEqual(self.pointer.read_bytes(), b'third-party-generation\n')
        self.assertEqual(len(list(self.native.glob('*.day'))), 8)
        with self.assertRaisesRegex(RuntimeError, 'CAS_BYTES'):
            helper.rollback_import(self.config, self.publisher)

    def test_native_readback_failure_rolls_back_unchanged_owned_links(self):
        original = Path.read_bytes; injected = []
        def fail_first_native(path):
            if path.parent == self.native and path.suffix == '.day' and not injected:
                injected.append(str(path))
                raise OSError('injected native readback failure')
            return original(path)
        with patch.object(Path, 'read_bytes', fail_first_native):
            with self.assertRaises(OSError):
                helper.create_seeds(self.config, self.publisher)
        self.assertEqual(len(injected), 1)
        self.assertFalse(list(self.native.iterdir()))


began = time.monotonic()
suite = unittest.defaultTestLoader.loadTestsFromTestCase(FocusedSeedIO)
result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
report = dict(execution_id=CONFIG['execution_id'], passed=result.testsRun-len(result.failures)-len(result.errors),
              tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
              elapsed_seconds=time.monotonic()-began, real_native_writes=0, real_panel_reads=0,
              network_calls=0, helper_sha256=sha(CONFIG['helper']['path']),
              research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
(RUN / 'RESULT.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
print(json.dumps(report, sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
