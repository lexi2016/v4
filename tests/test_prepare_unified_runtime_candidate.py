"""Bounded reviewed-removal helper tests; never invokes prepare() or writes a candidate."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from ops.prepare_unified_runtime_candidate import apply_reviewed_removals


def sha(raw):return hashlib.sha256(raw).hexdigest()


class ReviewedRemovalTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.app=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_removed_and_absent_cases_never_create(self):
        relative='ops/reviewed.py';raw=b'reviewed removal\n';target=self.app/relative
        target.parent.mkdir(parents=True);target.write_bytes(raw)
        removed,absent=apply_reviewed_removals(self.app,{relative:sha(raw),'ops/already-absent.py':'0'*64})
        self.assertEqual(removed,[relative]);self.assertEqual(absent,['ops/already-absent.py'])
        self.assertFalse(target.exists());self.assertFalse((self.app/'ops/already-absent.py').exists())

    def test_changed_bytes_are_rejected_without_unlink(self):
        relative='ops/reviewed.py';target=self.app/relative
        target.parent.mkdir(parents=True);target.write_bytes(b'changed bytes\n')
        with self.assertRaisesRegex(ValueError,'REVIEWED_REMOVAL_BYTES_CHANGED'):
            apply_reviewed_removals(self.app,{relative:'0'*64})
        self.assertTrue(target.exists())


if __name__=='__main__':unittest.main()
