"""Synthetic gate checks only; never a review of the frozen 392 decisions."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'review_gate_support', Path(__file__).with_name('test_decision_revision.py'))
support = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = support
spec.loader.exec_module(support)


class RevisionReviewGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.DecisionRevisionTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        support.DecisionRevisionTests.tearDownClass()

    def setUp(self):
        self.fixture = support.DecisionRevisionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.reviewer = json.loads(self.fixture.reviewer.read_bytes())

    def tearDown(self):
        self.fixture.tearDown()

    def snapshot(self):
        return {
            str(path.relative_to(self.fixture.parent)):
                ('file', path.read_bytes()) if path.is_file() else ('directory', None)
            for path in self.fixture.parent.rglob('*')
        }

    def reject_without_write(self, error='REVISION_REVIEW_BINDING_INVALID', **overrides):
        from infrastructure.owned_io import SafeRoot
        before = self.snapshot()
        # Instrument only mutation boundaries; parent evidence and create are real.
        with patch.object(SafeRoot, 'write_bytes', side_effect=AssertionError('write attempted')), \
             patch.object(SafeRoot, 'ensure_directory', side_effect=AssertionError('mkdir attempted')), \
             patch.object(SafeRoot, 'kernel_lock', side_effect=AssertionError('lock creation attempted')):
            with self.assertRaisesRegex(ValueError, '^' + error + '$'):
                self.fixture.create(**overrides)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.fixture.parent / 'decision_revisions').exists())

    def write_reviewer(self, value):
        support.support.dump(self.fixture.reviewer, value)

    def test_absent_binding_is_rejected_before_any_mutator(self):
        value = copy.deepcopy(self.reviewer)
        del value['decision_revision']
        self.write_reviewer(value)
        self.reject_without_write()

    def test_each_missing_binding_field_is_rejected_without_writes(self):
        for name in self.reviewer['decision_revision']:
            with self.subTest(field=name):
                value = copy.deepcopy(self.reviewer)
                del value['decision_revision'][name]
                self.write_reviewer(value)
                self.reject_without_write()

    def test_each_mismatched_binding_field_is_rejected_without_writes(self):
        for name in self.reviewer['decision_revision']:
            with self.subTest(field=name):
                value = copy.deepcopy(self.reviewer)
                value['decision_revision'][name] = 'different-value'
                self.write_reviewer(value)
                self.reject_without_write()

    def test_extra_binding_field_is_rejected_without_writes(self):
        value = copy.deepcopy(self.reviewer)
        value['decision_revision']['unreviewed_extra'] = 'not part of the binding'
        self.write_reviewer(value)
        self.reject_without_write()

    def test_non_object_binding_is_rejected_without_writes(self):
        for binding in (None, [], '', 0, True):
            with self.subTest(binding=binding):
                value = copy.deepcopy(self.reviewer)
                value['decision_revision'] = binding
                self.write_reviewer(value)
                self.reject_without_write()

    def test_previous_revision_binding_cannot_create_another_id(self):
        self.reject_without_write(revision_id='synthetic-next-revision')

    def test_wrong_parent_recovery_and_input_pins_are_rejected_without_writes(self):
        errors = {
            'parent_product_sha256': 'REVISION_PARENT_PIN_MISMATCH',
            'parent_receipt_sha256': 'REVISION_PARENT_PIN_MISMATCH',
            'recovery_sha256': 'OFFLINE_ANALYSIS_RECOVERY_SHA_MISMATCH',
            'semantic_sha256': 'REVISION_INPUT_SHA_MISMATCH',
            'reviewer_sha256': 'REVISION_INPUT_SHA_MISMATCH',
            'decisions_sha256': 'REVISION_INPUT_SHA_MISMATCH',
        }
        for name, error in errors.items():
            with self.subTest(pin=name):
                self.reject_without_write(error, **{name: '0' * 64})

    def test_changed_decision_digest_is_rejected_without_writes(self):
        value = copy.deepcopy(self.reviewer)
        value['decision_payload_sha256'] = '0' * 64
        self.write_reviewer(value)
        self.reject_without_write('REVISION_EXPLICIT_DECISIONS_REVIEW_REQUIRED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
