import hashlib
import tempfile
import unittest
from pathlib import Path
from v5_shadow.contracts import SourceEntry
from v5_shadow.source_capsule import inspect_capsule, verify_capsule

class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = b'VALUE = 7\n'
        (self.root / 'reader.py').write_bytes(self.data)
        self.entry = SourceEntry('lexi2016/v4', 'a'*40, 'api', 'snapshot/reader.py', 'reader.py', hashlib.sha1(b'blob '+str(len(self.data)).encode()+b'\0'+self.data).hexdigest(), hashlib.sha256(self.data).hexdigest())
    def capsule(self):
        return inspect_capsule(self.root, (self.entry,))
    def test_valid_source(self):
        self.assertEqual(verify_capsule(self.capsule(), self.root), ())
    def test_missing(self):
        capsule = self.capsule()
        (self.root / 'reader.py').unlink()
        self.assertIn('SOURCE_MISSING', verify_capsule(capsule, self.root))
    def test_changed(self):
        capsule = self.capsule()
        (self.root / 'reader.py').write_bytes(b'VALUE = 8\n')
        self.assertIn('SOURCE_SHA_MISMATCH', verify_capsule(capsule, self.root))
    def test_unlisted(self):
        capsule = self.capsule()
        (self.root / 'extra.py').write_text('')
        self.assertIn('SOURCE_UNDECLARED', verify_capsule(capsule, self.root))
    def test_symlink_rejected(self):
        capsule = self.capsule()
        (self.root / 'reader.py').unlink()
        (self.root / 'reader.py').symlink_to('/etc/hosts')
        self.assertIn('SOURCE_PATH_INVALID', verify_capsule(capsule, self.root))
    def test_parent_escape_rejected(self):
        entry = SourceEntry('lexi2016/v4','a'*40,'api','s','../escape.py','b'*40,'c'*64)
        with self.assertRaises(ValueError):
            inspect_capsule(self.root, (entry,))
    def test_blob_mismatch(self):
        entry = SourceEntry('lexi2016/v4','a'*40,'api','s','reader.py','b'*40,self.entry.sha256)
        capsule = inspect_capsule(self.root,(entry,))
        self.assertIn('SOURCE_BLOB_MISMATCH',verify_capsule(capsule,self.root))
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            inspect_capsule(self.root,(self.entry,self.entry))
if __name__ == '__main__': unittest.main()
