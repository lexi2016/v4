"""Synthetic-only regression tests; no market/source artifacts are read."""
from collections import Counter
from pathlib import Path
import csv
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

import long_input_metadata194 as m


def row(day, code, states):
    return {'target_date': day, 'code': code, **dict(zip(m.LANES, states))}


class MetadataTests(unittest.TestCase):
    def test_unknown_is_counted_without_inventing_absence(self):
        day = '2021-06-01'
        counts = m.aggregate([row(day, '000001.SZ', ['unknown', 'hit', 'confirmed_absent']),
                              row(day, '000002.SZ', ['unknown', 'unknown', 'hit'])], {day})
        self.assertEqual(counts[day]['source_fupan_unknown_rows'], 2)
        self.assertEqual(counts[day]['source_fupan_confirmed_absent_rows'], 0)
        self.assertEqual(counts[day]['source_research_confirmed_absent_rows'], 1)

    def test_denominators_are_separate_and_empty_date_is_preserved(self):
        day, empty = '2021-06-01', '2021-06-02'
        rows = [row(day, '000001.SZ', ['hit', 'unknown', 'unknown']),
                row(day, '000002.SZ', ['unknown', 'unknown', 'unknown'])]
        raw = m.aggregate(rows, {day, empty})
        model = m.aggregate(rows[1:], {day, empty})
        base = [{'target_date': d, 'raw_candidate_union_rows': str(n), 'candidate_rows': str(k),
                 **{lane + '_hit_rows': str(int(d == day and lane == 'source_fupan')) for lane in m.LANES}}
                for d, n, k in [(day, 2, 1), (empty, 0, 0)]]
        output = m.enrich_coverage(base, raw, model)
        self.assertEqual(output[0]['raw_source_state_denominator'], 2)
        self.assertEqual(output[0]['model_source_state_denominator'], 1)
        self.assertEqual(output[0]['model_source_fupan_unknown_rows'], 1)
        self.assertTrue(all(output[1][column] == 0 for column in m.coverage_columns()))
        self.assertTrue(all(str(output[i][k]) == value for i, original in enumerate(base) for k, value in original.items()))
        base[0]['candidate_rows'] = '2'
        with self.assertRaisesRegex(ValueError, 'DENOMINATOR_PARITY_FAIL:model'):
            m.enrich_coverage(base, raw, model)

    def test_invalid_state_duplicate_key_and_unknown_date_fail_closed(self):
        day = '2021-06-01'
        valid = row(day, '000001.SZ', ['unknown'] * 3)
        for rows, dates, error in [([row(day, '000001.SZ', ['0', 'unknown', 'hit'])], {day}, 'INVALID_SOURCE_STATE'),
                                   ([valid, valid], {day}, 'NOT_SORTED_UNIQUE'),
                                   ([valid], set(), 'UNEXPECTED_CANDIDATE_DATE')]:
            with self.assertRaisesRegex(ValueError, error):
                m.aggregate(rows, dates)

    def test_hash_checked_during_multiline_csv_stream_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'synthetic.csv'
            with p.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['target_date', 'code', *m.LANES, 'evidence'])
                writer.writeheader()
                writer.writerow({**row('2021-06-01', '000001.SZ', ['unknown'] * 3), 'evidence': 'line1\nline2'})
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            actual = list(m.hashed_rows({'path': str(p), 'sha256': digest}))
            self.assertEqual(actual[0]['evidence'], 'line1\nline2')
            with self.assertRaisesRegex(ValueError, 'CSV_SHA_DRIFT'):
                list(m.hashed_rows({'path': str(p), 'sha256': '0' * 64}))
            output = Path(tmp) / 'out.json'
            m.atomic_bytes(output, b'{}')
            m.atomic_bytes(output, b'{}')
            with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS_DIFFERENT'):
                m.atomic_bytes(output, b'[]')

    def test_child_manifest_reuses_truth_without_reading_or_changing_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            day = '2021-06-01'
            candidate = row(day, '000001.SZ', ['unknown', 'hit', 'unknown'])
            base = {'target_date': day, 'raw_candidate_union_rows': '1', 'candidate_rows': '1',
                    **{lane + '_hit_rows': str(int(lane == 'source_stage7')) for lane in m.LANES}}
            def csv_binding(name, record):
                path = directory / name
                with path.open('w', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(record))
                    writer.writeheader()
                    writer.writerow(record)
                return {'path': str(path), 'sha256': m.sha(path), 'rows': 1}
            dictionary = directory / 'dictionary.json'
            dictionary.write_text('{}')
            truth = {'path': str(directory / 'never_read_truth.csv'), 'sha256': 'a' * 64, 'rows': 1}
            parent = {'files': {'raw_candidate_union': csv_binding('raw.csv', candidate),
                'candidates': csv_binding('model.csv', candidate), 'coverage': csv_binding('coverage.csv', base),
                'dictionary': {'path': str(dictionary), 'sha256': m.sha(dictionary), 'rows': -1}, 'truth': truth},
                'raw_candidate_union_rows': 1, 'candidate_rows': 1, 'truth_rows': 1,
                'raw_formula_natural_rows': 0, 'technical_candidate_exclusions': 0, 'eligible_dates': 1,
                'eligible_target_dates': [day], 'training_allowed': False, 'source_code_sha256': {}}
            parent_path = directory / 'parent.json'
            parent_path.write_text(json.dumps(parent))
            parent_bytes = parent_path.read_bytes()
            contract_path = directory / 'contract.json'
            contract_path.write_text('{}')
            out = directory / 'child'
            contract = {'execution_id': 'FIXTURE', 'output_directory': str(out), 'code_sha256': {'synthetic': 'b' * 64}}
            with patch.object(m, 'validate_start', return_value=(contract, {'event_sha256': 'c' * 64})), \
                 patch.object(m, 'PARENT', parent_path), patch.object(m, 'PARENT_SHA', m.sha(parent_path)):
                m.run(contract_path, 'c' * 64)
            child = json.loads((out / 'MANIFEST.json').read_text())
            self.assertEqual(parent_path.read_bytes(), parent_bytes)
            self.assertEqual(child['files']['truth'], truth)
            self.assertFalse(Path(truth['path']).exists())
            self.assertEqual(child['eligible_target_dates'], [day])
            self.assertFalse(child['training_allowed'])
            self.assertNotEqual(child['files']['coverage']['path'], parent['files']['coverage']['path'])


if __name__ == '__main__':
    unittest.main()
