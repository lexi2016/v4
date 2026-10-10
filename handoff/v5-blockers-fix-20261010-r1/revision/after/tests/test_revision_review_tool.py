"""Read-only request/preflight tests with clearly synthetic review records."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'tools/review_revision_binding.py'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n')


class RevisionReviewToolTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(TOOL.is_file(), 'read-only revision reviewer request/preflight tool is absent')
        spec = importlib.util.spec_from_file_location('revision_review_tool', TOOL)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.tmp = tempfile.TemporaryDirectory(prefix='synthetic-review-preflight-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.semantic = self.root / 'semantic.json'
        self.decisions = self.root / 'decisions.json'
        self.original = self.root / 'original-reviewer.json'
        self.returned = self.root / 'returned-reviewer.json'
        dump(self.semantic, {'synthetic_fixture_only': True, 'records': []})
        dump(self.decisions, {'article_decisions': [{'synthetic_fixture_only': True}]})
        self.binding = dict(
            revision_id='synthetic-revision', parent_product_sha256='a' * 64,
            parent_owner_receipt_file_sha256='b' * 64,
            source_recovery_receipt_sha256='c' * 64, source_run_id='d' * 32)
        self.original_value = dict(
            review_conclusion='PASS', reader_identity='synthetic-reader',
            reviewer_identity='synthetic-independent-reviewer',
            evidence_run_id='d' * 32, decision_status='EXPLICIT_DISPOSITIONS',
            decision_payload_sha256='e' * 64,
            semantic_catalog_sha256=sha(self.semantic.read_bytes()),
            reviewed_at='2026-10-09T12:00:00+00:00', synthetic_fixture_only=True)
        dump(self.original, self.original_value)
        self.pins = dict(original_reviewer_file_sha256=sha(self.original.read_bytes()),
            semantic_catalog_file_sha256=sha(self.semantic.read_bytes()),
            article_decisions_file_sha256=sha(self.decisions.read_bytes()),
            article_decisions_logical_sha256='e' * 64)
        self.request = self.tool.make_request(self.binding, self.pins)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}

    def inspect(self, returned=True, returned_sha=None):
        before = self.snapshot()
        result = self.tool.inspect_review(self.request,
            original_reviewer=self.original, semantic_catalog=self.semantic,
            decisions=self.decisions, reviewer_output=self.returned if returned else None,
            reviewer_sha256=returned_sha if returned_sha is not None else
                sha(self.returned.read_bytes()) if returned and self.returned.exists() else None)
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.root / 'decision_revisions').exists())
        return result

    def make_returned(self, **changes):
        value = copy.deepcopy(self.original_value)
        value['decision_revision'] = copy.deepcopy(self.binding)
        value.update(changes)
        dump(self.returned, value)
        return value

    def test_request_contains_binding_and_pins_without_becoming_a_reviewer(self):
        self.assertEqual(self.request['expected_decision_revision'], self.binding)
        self.assertEqual(self.request['frozen_inputs'], self.pins)
        self.assertEqual(self.request['status'], 'BLOCKED_AWAITING_ORIGINAL_REVIEWER')
        self.assertNotIn('review_conclusion', self.request)
        self.assertNotIn('decision_revision', self.request)
        self.assertFalse(self.request['semantic_review_performed'])
        self.assertFalse(self.request['authorizes_import'])

    def test_pending_review_stays_blocked_without_writes(self):
        result = self.inspect(returned=False)
        self.assertEqual(result['status'], 'BLOCKED_AWAITING_ORIGINAL_REVIEWER')
        self.assertFalse(result['authorizes_import'])

    def test_valid_structure_does_not_claim_original_authorship_or_semantic_review(self):
        self.make_returned()
        result = self.inspect()
        self.assertEqual(result['status'], 'STRUCTURAL_BINDING_VERIFIED')
        self.assertFalse(result['authorship_verified'])
        self.assertFalse(result['semantic_review_performed'])
        self.assertFalse(result['authorizes_import'])
        self.assertEqual(result['reviewer_file_sha256'], sha(self.returned.read_bytes()))

    def test_original_fields_cannot_change_while_adding_binding(self):
        for name, changed in (('reviewer_identity', 'other-reviewer'),
                              ('decision_payload_sha256', 'f' * 64),
                              ('reviewed_at', '2026-10-10T12:00:00+00:00')):
            with self.subTest(field=name):
                self.make_returned(**{name: changed})
                self.assertIn('ORIGINAL_REVIEW_FIELDS_CHANGED', self.inspect()['error_codes'])

    def test_boolean_and_numeric_type_drift_is_rejected(self):
        for original, returned in ((False, 0), (True, 1), (392, 392.0), (392.0, 392)):
            with self.subTest(original=original, returned=returned):
                self.original_value['immutable_detail'] = original
                dump(self.original, self.original_value)
                self.pins['original_reviewer_file_sha256'] = sha(self.original.read_bytes())
                self.request = self.tool.make_request(self.binding, self.pins)
                self.make_returned(immutable_detail=returned)
                result = self.inspect()
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertIn('ORIGINAL_REVIEW_FIELDS_CHANGED', result['error_codes'])
                self.assertEqual(result['changed_original_fields'], ['immutable_detail'])

    def test_nested_object_and_array_type_drift_is_rejected(self):
        cases = [
            ({'body': {'complete': False}}, {'body': {'complete': 0}}),
            ({'rows': [{'count': 392}]}, {'rows': [{'count': 392.0}]}),
            ([{'flags': [True, False]}], [{'flags': [1, 0]}]),
        ]
        for original, returned in cases:
            with self.subTest(original=original, returned=returned):
                self.original_value['immutable_detail'] = original
                dump(self.original, self.original_value)
                self.pins['original_reviewer_file_sha256'] = sha(self.original.read_bytes())
                self.request = self.tool.make_request(self.binding, self.pins)
                self.make_returned(immutable_detail=returned)
                result = self.inspect()
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertIn('ORIGINAL_REVIEW_FIELDS_CHANGED', result['error_codes'])

    def precise_review(self, original_token, returned_token):
        original_raw = json.dumps(self.original_value, sort_keys=True)
        self.original.write_text(original_raw[:-1] + ',"exact_number":' + original_token + '}\n')
        self.pins['original_reviewer_file_sha256'] = sha(self.original.read_bytes())
        self.request = self.tool.make_request(self.binding, self.pins)
        self.make_returned()
        returned_raw = self.returned.read_text().rstrip()
        self.returned.write_text(returned_raw[:-1] + ',"exact_number":' + returned_token + '}\n')

    def test_decimal_value_drift_beyond_binary_float_precision_is_rejected(self):
        for original, returned in (
                ('9007199254740993.0', '9007199254740992.0'),
                ('1.0000000000000000001', '1.0')):
            with self.subTest(original=original, returned=returned):
                self.precise_review(original, returned)
                result = self.inspect()
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertIn('ORIGINAL_REVIEW_FIELDS_CHANGED', result['error_codes'])
                self.assertEqual(result['changed_original_fields'], ['exact_number'])

    def test_unchanged_complex_json_types_and_values_remain_valid(self):
        self.original_value['immutable_detail'] = {
            'flag': False, 'items': [None, True, 392, 392.0, '392', {'ratio': 1.25}]}
        dump(self.original, self.original_value)
        self.pins['original_reviewer_file_sha256'] = sha(self.original.read_bytes())
        self.request = self.tool.make_request(self.binding, self.pins)
        value = self.make_returned()
        # Different object key order does not change JSON field types or values.
        self.returned.write_text(json.dumps(value, sort_keys=False) + '\n')
        result = self.inspect()
        self.assertEqual(result['status'], 'STRUCTURAL_BINDING_VERIFIED')
        self.assertFalse(result['authorship_verified'])
        self.assertFalse(result['authorizes_import'])

    def test_equivalent_exact_decimal_spellings_remain_valid(self):
        self.precise_review('9007199254740993.0', '9007199254740993.00')
        self.assertEqual(self.inspect()['status'], 'STRUCTURAL_BINDING_VERIFIED')

    def test_nonstandard_numbers_in_returned_reviewer_are_rejected(self):
        for token in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(token=token):
                self.make_returned()
                raw = self.returned.read_text().rstrip()
                self.returned.write_text(raw[:-1] + ',"new_provenance":' + token + '}\n')
                result = self.inspect()
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertIn('REVIEWER_JSON_INVALID', result['error_codes'])

    def test_nonstandard_numbers_in_original_reviewer_are_rejected(self):
        for token in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(token=token):
                raw = json.dumps(self.original_value, sort_keys=True)
                self.original.write_text(raw[:-1] + ',"original_provenance":' + token + '}\n')
                self.pins['original_reviewer_file_sha256'] = sha(self.original.read_bytes())
                self.request = self.tool.make_request(self.binding, self.pins)
                self.make_returned()
                result = self.inspect()
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertIn('ORIGINAL_REVIEWER_JSON_INVALID', result['error_codes'])

    def test_nonstandard_numbers_in_request_json_are_rejected(self):
        self.make_returned()
        request_path = self.root / 'request.json'
        for token in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(token=token):
                raw = json.dumps(self.request, sort_keys=True)
                request_path.write_text(raw[:-1] + ',"request_note":' + token + '}\n')
                output = io.StringIO()
                before = self.snapshot()
                with contextlib.redirect_stdout(output):
                    rc = self.tool.main(['inspect', '--request', str(request_path),
                        '--request-sha256', sha(request_path.read_bytes()),
                        '--original-reviewer', str(self.original),
                        '--semantic-catalog', str(self.semantic), '--decisions', str(self.decisions),
                        '--reviewer-output', str(self.returned),
                        '--reviewer-sha256', sha(self.returned.read_bytes())])
                self.assertEqual(before, self.snapshot())
                self.assertEqual(rc, 2)
                self.assertIn('REQUEST_JSON_INVALID', json.loads(output.getvalue())['error_codes'])

    def test_missing_wrong_and_extra_binding_are_blocked(self):
        variants = [None, {**self.binding, 'revision_id': 'other-id'},
                    {**self.binding, 'unreviewed_extra': True}]
        for binding in variants:
            with self.subTest(binding=binding):
                self.make_returned(decision_revision=binding)
                self.assertIn('REVISION_REVIEW_BINDING_INVALID', self.inspect()['error_codes'])

    def test_new_returned_file_requires_its_explicit_sha(self):
        self.make_returned()
        self.assertIn('RETURNED_REVIEWER_SHA_MISMATCH',
            self.inspect(returned_sha='0' * 64)['error_codes'])
        before = self.snapshot()
        result = self.tool.inspect_review(self.request,
            original_reviewer=self.original, semantic_catalog=self.semantic,
            decisions=self.decisions, reviewer_output=self.returned, reviewer_sha256=None)
        self.assertIn('RETURNED_REVIEWER_SHA_REQUIRED', result['error_codes'])
        self.assertEqual(before, self.snapshot())

    def test_each_changed_frozen_input_is_blocked(self):
        self.make_returned()
        for path, error in ((self.original, 'ORIGINAL_REVIEWER_SHA_MISMATCH'),
                            (self.semantic, 'SEMANTIC_CATALOG_SHA_MISMATCH'),
                            (self.decisions, 'ARTICLE_DECISIONS_SHA_MISMATCH')):
            raw = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(raw + b' ')
                self.assertIn(error, self.inspect()['error_codes'])
            path.write_bytes(raw)

    def test_duplicate_json_keys_are_rejected(self):
        self.make_returned()
        raw = self.returned.read_text().rstrip()
        self.returned.write_text(raw[:-1] + ',"decision_revision":null}\n')
        self.assertIn('REVIEWER_JSON_INVALID', self.inspect()['error_codes'])

    def test_symlink_inputs_are_rejected_without_writes(self):
        self.make_returned()
        alias = self.root / 'alias-reviewer.json'
        alias.symlink_to(self.returned)
        result = self.tool.inspect_review(self.request,
            original_reviewer=self.original, semantic_catalog=self.semantic,
            decisions=self.decisions, reviewer_output=alias,
            reviewer_sha256=sha(self.returned.read_bytes()))
        self.assertIn('INPUT_SYMLINK_FORBIDDEN', result['error_codes'])

    def test_cli_emits_read_only_request_with_the_fixed_real_pins(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = self.tool.main(['request', '--revision-id', 'decision-r20261010-review'])
        self.assertEqual(rc, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['expected_decision_revision']['parent_product_sha256'],
            'e724d07b39e5b4fb3ccbb0b4536f4519b4badbfd3783cad7ee6506a7af242ad6')
        self.assertEqual(result['frozen_inputs']['original_reviewer_file_sha256'],
            '981f89ebbcee269701ad69e4c346944f9da37cfcb1693032ca11de65c3e4eb29')
        self.assertEqual(result['status'], 'BLOCKED_AWAITING_ORIGINAL_REVIEWER')

    def test_cli_rejects_request_file_sha_mismatch(self):
        request_path = self.root / 'request.json'
        dump(request_path, self.request)
        output = io.StringIO()
        before = self.snapshot()
        with contextlib.redirect_stdout(output):
            rc = self.tool.main(['inspect', '--request', str(request_path),
                '--request-sha256', '0' * 64, '--original-reviewer', str(self.original),
                '--semantic-catalog', str(self.semantic), '--decisions', str(self.decisions)])
        self.assertEqual(rc, 2)
        self.assertIn('REQUEST_SHA_MISMATCH', json.loads(output.getvalue())['error_codes'])
        self.assertEqual(before, self.snapshot())

    def test_invalid_request_values_are_rejected(self):
        for name, changed in (('revision_id', '../escape'),
                              ('source_run_id', 'bad-run'),
                              ('parent_product_sha256', 'BAD-PIN')):
            with self.subTest(field=name), self.assertRaisesRegex(ValueError, 'REQUEST_INVALID'):
                self.tool.make_request({**self.binding, name: changed}, self.pins)


if __name__ == '__main__':
    unittest.main(verbosity=2)
