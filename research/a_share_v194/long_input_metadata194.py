"""Append-only source-coverage metadata over the frozen long-input tables.

No panel/event read, feature evaluation, label construction, fit, or OOF.
Real aggregation requires a registered START binding the exact helper and tests.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path('/Users/lexi/Desktop/学习/因子工厂')
LONG = ROOT / 'research/a_share_v194_long_history_20261024'
PARENT = LONG / 'inputs/long_input_build_r1_20261024_01/MANIFEST.json'
PARENT_SHA = '3985c5576a150e697e62c7c8cc9b1f4ad0e0bec1952f19e890ca0a7433f9420b'
REGISTRY = ROOT / 'contracts/EXPERIMENT_REGISTRY.jsonl'
LANES = ('source_fupan', 'source_stage7', 'source_research')
STATES = ('hit', 'confirmed_absent', 'unknown')
SCOPES = ('raw', 'model')
FLAGS = dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def require(value: Any, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(sha(path) == hashlib.sha256(payload).hexdigest(), 'OUTPUT_EXISTS_DIFFERENT:' + str(path))
        return
    tmp = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    with tmp.open('xb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    # link creates exclusively; a concurrent writer cannot be overwritten.
    os.link(tmp, path)
    tmp.unlink()
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, sort_keys=True,
        indent=2, allow_nan=False) + '\n').encode())


def aggregate(rows: Iterable[Mapping[str, str]], allowed_dates: set[str]) -> dict[str, Counter]:
    """Count explicit states only; never infer absence from a missing hit."""
    result: dict[str, Counter] = {}
    previous: tuple[str, str] | None = None
    for row in rows:
        day, code = row['target_date'], row['code']
        require(day in allowed_dates, 'UNEXPECTED_CANDIDATE_DATE:' + day)
        key = (day, code)
        require(previous is None or key > previous, 'CANDIDATE_KEYS_NOT_SORTED_UNIQUE:' + repr(key))
        previous = key
        counts = result.setdefault(day, Counter())
        counts['denominator'] += 1
        for lane in LANES:
            state = row[lane]
            require(state in STATES, 'INVALID_SOURCE_STATE:' + lane + ':' + repr(state))
            counts[lane + '_' + state + '_rows'] += 1
    return result


def hashed_rows(binding: Mapping[str, Any]) -> Iterable[dict[str, str]]:
    """Hash bytes during the one CSV aggregation pass, without reading truth."""
    path = Path(binding['path'])
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        def lines():
            for index, raw in enumerate(stream):
                digest.update(raw)
                yield raw.decode('utf-8-sig' if index == 0 else 'utf-8')
        yield from csv.DictReader(lines())
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_ino, after.st_size, after.st_mtime_ns), 'CSV_STAT_DRIFT:' + str(path))
    require(digest.hexdigest() == binding['sha256'], 'CSV_SHA_DRIFT:' + str(path))


def coverage_columns() -> list[str]:
    return [column for scope in SCOPES for column in [scope + '_source_state_denominator',
        *(scope + '_' + lane + '_' + state + '_rows' for lane in LANES for state in STATES)]]


def enrich_coverage(base: list[dict[str, str]], raw: Mapping[str, Counter],
                    model: Mapping[str, Counter]) -> list[dict[str, Any]]:
    days = [row['target_date'] for row in base]
    require(days == sorted(set(days)), 'COVERAGE_DATES_NOT_SORTED_UNIQUE')
    require(set(raw) <= set(days) and set(model) <= set(days), 'AGGREGATE_DATE_OUTSIDE_COVERAGE')
    result = []
    for original in base:
        row: dict[str, Any] = dict(original)
        day = row['target_date']
        for scope, values, old_column in (('raw', raw, 'raw_candidate_union_rows'),
                                         ('model', model, 'candidate_rows')):
            counts = values.get(day, Counter())
            denominator = counts['denominator']
            require(denominator == int(row[old_column]), 'DENOMINATOR_PARITY_FAIL:' + scope + ':' + day)
            row[scope + '_source_state_denominator'] = denominator
            for lane in LANES:
                require(sum(counts[lane + '_' + state + '_rows'] for state in STATES) == denominator,
                        'STATE_PARTITION_FAIL:' + scope + ':' + lane + ':' + day)
                for state in STATES:
                    row[scope + '_' + lane + '_' + state + '_rows'] = counts[lane + '_' + state + '_rows']
                if scope == 'raw':
                    require(counts[lane + '_hit_rows'] == int(row[lane + '_hit_rows']),
                            'PARENT_RAW_HIT_PARITY_FAIL:' + lane + ':' + day)
        result.append(row)
    return result


def validate_start(contract_path: Path, start_event: str) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = load(contract_path)
    own = Path(__file__).resolve()
    expected_codes = {str(own): sha(own), str(own.with_name('test_long_input_metadata194.py')):
                      sha(own.with_name('test_long_input_metadata194.py'))}
    require(contract['code_sha256'] == expected_codes, 'METADATA_CODE_BINDING_DRIFT')
    require(contract['parent_manifest'] == {'path': str(PARENT), 'sha256': PARENT_SHA},
            'METADATA_PARENT_BINDING_DRIFT')
    out = Path(contract['output_directory'])
    require(out.parent.resolve() == (LONG / 'inputs').resolve() and out.resolve() != PARENT.parent.resolve(),
            'METADATA_OUTPUT_PATH_OUTSIDE_NEW_INPUT_VERSION')
    found = None
    with REGISTRY.open(encoding='utf-8') as stream:
        for line in stream:
            event = json.loads(line)
            if event.get('event_sha256') == start_event:
                found = event
                break
    require(found is not None and found.get('event_type') == 'RUN_STARTED' and
            found.get('execution_id') == contract['execution_id'] and
            found.get('contract_sha256') == sha(contract_path) and
            found.get('code_sha256') == expected_codes, 'METADATA_REGISTERED_START_BINDING_REQUIRED')
    require(all(found.get(key) == value for key, value in FLAGS.items()), 'METADATA_SAFETY_FLAG_DRIFT')
    return contract, found


def run(contract_path: Path, start_event: str) -> dict[str, Any]:
    contract, event = validate_start(contract_path, start_event)
    require(sha(PARENT) == PARENT_SHA, 'PARENT_MANIFEST_SHA_DRIFT')
    parent = load(PARENT)
    base = list(hashed_rows(parent['files']['coverage']))
    dates = {row['target_date'] for row in base}
    raw = aggregate(hashed_rows(parent['files']['raw_candidate_union']), dates)
    model = aggregate(hashed_rows(parent['files']['candidates']), dates)
    coverage = enrich_coverage(base, raw, model)
    require(sum(row['raw_source_state_denominator'] for row in coverage) == parent['raw_candidate_union_rows'],
            'PARENT_RAW_ROW_COUNT_DRIFT')
    require(sum(row['model_source_state_denominator'] for row in coverage) == parent['candidate_rows'],
            'PARENT_MODEL_ROW_COUNT_DRIFT')
    out = Path(contract['output_directory'])
    identity = {'parent_manifest_sha256': PARENT_SHA, 'contract_sha256': sha(contract_path),
                'start_event_sha256': start_event, 'code_sha256': contract['code_sha256']}
    identity_path = out / 'METADATA_BUILD_IDENTITY.json'
    require(not out.exists() or identity_path.is_file(), 'UNBOUND_METADATA_OUTPUT_DIRECTORY')
    atomic_json(identity_path, identity)
    text = io.StringIO(newline='')
    fields = [*base[0], *coverage_columns()]
    writer = csv.DictWriter(text, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(coverage)
    coverage_path = out / 'coverage.csv'
    atomic_bytes(coverage_path, text.getvalue().encode())
    definitions = {scope: {'denominator_column': scope + '_source_state_denominator',
        'denominator_definition': 'row count of frozen ' + ('raw_candidate_union' if scope == 'raw' else 'candidates') +
            ' table for target_date; not the 5533-code universe denominator',
        'partition': 'Each source: hit + confirmed_absent + unknown equals this denominator; empty date gives 0/0/0.',
        'columns': [scope + '_' + lane + '_' + state + '_rows' for lane in LANES for state in STATES]}
        for scope in SCOPES}
    dictionary_ref = parent['files']['dictionary']
    require(sha(Path(dictionary_ref['path'])) == dictionary_ref['sha256'], 'PARENT_DICTIONARY_SHA_DRIFT')
    dictionary = load(Path(dictionary_ref['path']))
    dictionary['daily_source_coverage'] = definitions
    dictionary['legacy_source_hit_rows_scope'] = 'Existing source_<lane>_hit_rows are raw_candidate_union hit counts.'
    dictionary['source_state_metadata_policy'] = 'Aggregate frozen explicit values only; no inferred confirmed_absent, no unknown-to-zero conversion.'
    dictionary_path = out / 'DATA_DICTIONARY.json'
    atomic_json(dictionary_path, dictionary)
    child = copy.deepcopy(parent)
    child.update(parent_manifest={'path': str(PARENT), 'sha256': PARENT_SHA},
                 metadata_revision='DAILY_SOURCE_TRISTATE_COVERAGE_R1',
                 metadata_execution_id=contract['execution_id'], metadata_start_event_sha256=start_event,
                 metadata_contract={'path': str(contract_path), 'sha256': sha(contract_path)},
                 daily_source_coverage=definitions)
    for key, path in (('coverage', coverage_path), ('dictionary', dictionary_path)):
        child['files'][key] = {'path': str(path), 'sha256': sha(path), 'rows': len(coverage) if key == 'coverage' else -1}
    child['input_sha256'] = canonical_sha(child['files'])
    child['source_code_sha256'].update(contract['code_sha256'])
    child_path = out / 'MANIFEST.json'
    atomic_json(child_path, child)
    reused = {key: binding for key, binding in parent['files'].items() if key not in {'coverage', 'dictionary'}}
    require(all(child['files'][key] == binding for key, binding in reused.items()), 'REUSED_FILE_BINDING_DRIFT')
    receipt = {'status': 'METADATA_REPAIR_READY_FOR_INDEPENDENT_REVIEW',
        'execution_id': contract['execution_id'], 'start_event_sha256': event['event_sha256'],
        'parent_manifest': child['parent_manifest'], 'manifest': {'path': str(child_path), 'sha256': sha(child_path)},
        'reused_file_bindings': reused, 'reused_file_policy': 'Original paths and SHA bindings reused; no copying or rereading truth/panel/events.',
        'coverage': child['files']['coverage'], 'dictionary': child['files']['dictionary'],
        'date_count': len(coverage), 'daily_source_coverage': definitions,
        'source_totals': {scope: {column: sum(row[column] for row in coverage)
            for column in coverage_columns() if column.startswith(scope + '_')} for scope in SCOPES},
        'parent_counts_preserved': {key: parent[key] for key in ('raw_candidate_union_rows', 'candidate_rows',
            'truth_rows', 'raw_formula_natural_rows', 'technical_candidate_exclusions', 'eligible_dates')},
        'source_code_sha256': contract['code_sha256'], 'fit_count': 0, 'oof_count': 0,
        'feature_evaluations': 0, 'label_computations': 0, 'canary_reruns': 0,
        'independent_review_status': 'PENDING', **FLAGS}
    atomic_json(out / 'AUTHOR_RECEIPT.json', receipt)
    return {'manifest': receipt['manifest'], 'receipt_path': str(out / 'AUTHOR_RECEIPT.json'),
            'receipt_sha256': sha(out / 'AUTHOR_RECEIPT.json'), 'status': receipt['status'], **FLAGS}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--start-event', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.contract, args.start_event), ensure_ascii=False, sort_keys=True), flush=True)
