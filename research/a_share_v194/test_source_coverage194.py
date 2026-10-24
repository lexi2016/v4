"""One narrow synthetic derivation fixture; no real research data or fits."""
import copy
import csv
import hashlib
import json

import pytest

import source_coverage194 as coverage


def test_source_coverage_scope_states_zero_dates_and_invalid_rejection(tmp_path, monkeypatch):
    root = tmp_path / 'evidence'
    saved = root / 'inputs/saved'
    saved.mkdir(parents=True)
    monkeypatch.setattr(coverage, 'EVIDENCE_ROOT', root)

    def csvfile(name, rows):
        path = saved / name
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
        return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), rows=len(rows))

    dates = ['2001-01-02', '2001-01-03', '2001-01-04']
    original = [dict(target_date=day, note='saved,unaltered', selection_slots='0') for day in dates]
    fields = ['target_date', 'source_fupan', 'source_stage7', 'source_research']
    raw_rows = [dict(zip(fields, row)) for row in [
        [dates[0], 'hit', 'confirmed_absent', 'unknown'],
        [dates[0], 'unknown', 'hit', 'confirmed_absent'],
        [dates[1], 'confirmed_absent', 'unknown', 'hit']]]
    model_rows = [raw_rows[0]]
    parent = dict(schema='V194_DATASET_MANIFEST_V2', files={
        'coverage': csvfile('coverage.csv', original),
        'raw_candidate_union': csvfile('raw.csv', raw_rows),
        'candidates': csvfile('candidates.csv', model_rows),
        'truth': dict(path='/saved/truth.csv', sha256='unchanged', rows=5)},
        source_state_columns=['source_' + lane for lane in coverage.LANES],
        eligible_target_dates=dates, label_definition='unchanged-target-D',
        engine_source_bindings={'original': 'unchanged'}, semantic_ready=False,
        training_allowed=False, **coverage.FLAGS)

    def bind_parent(value, name):
        path = saved / name
        path.write_text(json.dumps(value))
        return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    parent['input_sha256'] = coverage.canonical_sha(parent['files'])
    parent_ref = bind_parent(parent, 'parent.json')
    original_bytes = {path: path.read_bytes() for path in saved.iterdir()}
    config = dict(schema='V194_SOURCE_COVERAGE_DERIVATION_V1', execution_id='synthetic-only',
        parent_manifest=parent_ref, output_dir=str(root / 'inputs/derived'), **coverage.FLAGS)
    receipt = coverage.derive(config, 'synthetic-config-sha')
    derived = json.loads((root / 'inputs/derived/MANIFEST.json').read_text())
    with (root / 'inputs/derived/coverage.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3 and len(coverage.FIELDS) == 20
    for old, new in zip(original, rows):
        assert {key: new[key] for key in old} == old
    assert receipt['scope_rows'] == {'raw': 3, 'model': 1}
    assert rows[0]['raw_source_state_denominator'] == '2'
    assert rows[0]['model_source_state_denominator'] == '1'
    assert rows[0]['raw_source_fupan_unknown_rows'] == '1'
    assert rows[0]['model_source_fupan_unknown_rows'] == '0'
    assert rows[1]['raw_source_fupan_confirmed_absent_rows'] == '1'
    for scope in ('raw', 'model'):
        for row in rows:
            for lane in coverage.LANES:
                assert sum(int(row[f'{scope}_source_{lane}_{state}_rows']) for state in coverage.STATES) == int(row[scope + '_source_state_denominator'])
    assert all(rows[2][field] == '0' for field in coverage.FIELDS)
    assert coverage.verify_core_equivalence(parent, derived) == receipt['core_identity_sha256']
    assert derived['files']['truth'] == parent['files']['truth']
    altered = copy.deepcopy(derived)
    altered['label_definition'] = 'changed'
    with pytest.raises(ValueError, match='MANIFEST_CORE_DRIFT'):
        coverage.verify_core_equivalence(parent, altered)
    assert all(path.read_bytes() == value for path, value in original_bytes.items())

    invalid = copy.deepcopy(parent)
    invalid['files']['raw_candidate_union'] = csvfile('invalid.csv', [dict(raw_rows[0], source_fupan='0')])
    invalid['input_sha256'] = coverage.canonical_sha(invalid['files'])
    bad_config = dict(config, parent_manifest=bind_parent(invalid, 'invalid_parent.json'),
                      output_dir=str(root / 'inputs/invalid_derived'))
    with pytest.raises(ValueError, match='SOURCE_STATE_INVALID'):
        coverage.derive(bad_config, 'synthetic-bad-config')
    assert not (root / 'inputs/invalid_derived').exists()
