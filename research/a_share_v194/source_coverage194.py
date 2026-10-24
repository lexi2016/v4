"""Derive coverage metadata from saved candidate states; never evaluate or fit."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path

EVIDENCE_ROOT = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_v194_full_history_20261024')
LANES = ('fupan', 'stage7', 'research')
STATES = ('hit', 'confirmed_absent', 'unknown')
FIELDS = [field for scope in ('raw', 'model') for field in (
    scope + '_source_state_denominator',
    *(f'{scope}_source_{lane}_{state}_rows' for lane in LANES for state in STATES))]
FLAGS = dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def stat_identity(path):
    value = path.stat()
    return dict(inode=value.st_ino, size=value.st_size, mtime_ns=value.st_mtime_ns)


class DigestReader(io.RawIOBase):
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def readable(self):
        return True

    def readinto(self, buffer):
        size = self.stream.readinto(buffer)
        if size:
            self.digest.update(memoryview(buffer)[:size])
        return size


def bound_rows(ref, base, observations):
    """Hash and parse each saved CSV in one byte pass, retaining source stat."""
    require(isinstance(ref, dict) and ref.get('path') and ref.get('sha256'), 'CSV_BINDING_REQUIRED')
    path = Path(ref['path'])
    path = (path if path.is_absolute() else base / path).resolve()
    before = stat_identity(path)
    count = 0
    with path.open('rb') as raw:
        digest = DigestReader(raw)
        with io.TextIOWrapper(io.BufferedReader(digest), encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), 'CSV_HEADER_INVALID')
            for row in reader:
                require(None not in row and all(value is not None for value in row.values()), 'CSV_ROW_SHAPE_INVALID')
                count += 1
                yield reader.fieldnames, row
        actual_sha = digest.digest.hexdigest()
    require(stat_identity(path) == before, 'CSV_STAT_DRIFT:' + str(path))
    require(actual_sha == ref['sha256'], 'CSV_SHA_DRIFT:' + str(path))
    require(type(ref.get('rows')) is int and count == ref['rows'], 'CSV_ROW_COUNT_DRIFT:' + str(path))
    observations.append(dict(path=str(path), sha256=actual_sha, rows=count,
                             before_stat=before, after_stat=stat_identity(path)))


def derive_counts(ref, base, dates, scope, observations):
    counts = {day: {name: 0 for name in FIELDS if name.startswith(scope + '_')} for day in dates}
    for fields, row in bound_rows(ref, base, observations):
        require(all(name in fields for name in ('target_date', 'source_fupan', 'source_stage7', 'source_research')),
                'SOURCE_STATE_COLUMNS_MISSING')
        day = row['target_date']
        require(day in counts, 'SOURCE_DATE_OUTSIDE_COVERAGE:' + day)
        counts[day][scope + '_source_state_denominator'] += 1
        for lane in LANES:
            state = row['source_' + lane]
            require(state in STATES, 'SOURCE_STATE_INVALID:' + lane + ':' + str(state))
            counts[day][f'{scope}_source_{lane}_{state}_rows'] += 1
    for values in counts.values():
        for lane in LANES:
            require(sum(values[f'{scope}_source_{lane}_{state}_rows'] for state in STATES)
                    == values[scope + '_source_state_denominator'], 'SOURCE_DENOMINATOR_DRIFT')
    return counts


def core_identity(manifest):
    core = copy.deepcopy(manifest)
    core.pop('input_sha256', None)
    core.pop('source_coverage_extension', None)
    core['files'].pop('coverage')
    return core


def verify_core_equivalence(parent, derived):
    require(set(derived) == set(parent) | {'source_coverage_extension'}, 'MANIFEST_KEYS_DRIFT')
    require(set(derived['files']) == set(parent['files']), 'MANIFEST_FILE_KEYS_DRIFT')
    require(core_identity(parent) == core_identity(derived), 'MANIFEST_CORE_DRIFT')
    require(derived['input_sha256'] == canonical_sha(derived['files']), 'DERIVED_INPUT_SHA_DRIFT')
    return canonical_sha(core_identity(parent))


def write_json_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def derive(config, config_sha256):
    require(config.get('schema') == 'V194_SOURCE_COVERAGE_DERIVATION_V1', 'CONFIG_SCHEMA_DRIFT')
    require(all(config.get(key) is value for key, value in FLAGS.items()), 'UNSAFE_FLAGS')
    require(bool(config.get('execution_id')), 'EXECUTION_ID_REQUIRED')
    ref = config['parent_manifest']
    parent_path = Path(ref['path']).resolve()
    require(parent_path.is_relative_to(EVIDENCE_ROOT.resolve() / 'inputs'), 'PARENT_OUTSIDE_INPUTS')
    parent_stat = stat_identity(parent_path)
    parent_bytes = parent_path.read_bytes()
    require(hashlib.sha256(parent_bytes).hexdigest() == ref['sha256'], 'PARENT_MANIFEST_SHA_DRIFT')
    parent = json.loads(parent_bytes)
    require('source_coverage_extension' not in parent, 'PARENT_ALREADY_EXTENDED')
    require(parent['input_sha256'] == canonical_sha(parent['files']), 'PARENT_INPUT_SHA_DRIFT')
    require(parent['source_state_columns'] == ['source_' + lane for lane in LANES], 'SOURCE_ORDER_DRIFT')
    output = Path(config['output_dir']).resolve()
    require(output.is_relative_to(EVIDENCE_ROOT.resolve() / 'inputs') and not output.exists(), 'OUTPUT_NOT_NEW_INPUT_DIR')
    observations = []
    original = list(bound_rows(parent['files']['coverage'], parent_path.parent, observations))
    require(bool(original), 'COVERAGE_EMPTY')
    fields = original[0][0]
    require('target_date' in fields and not set(fields) & set(FIELDS), 'COVERAGE_HEADER_CONFLICT')
    days = [row['target_date'] for _, row in original]
    require(len(days) == len(set(days)), 'COVERAGE_DUPLICATE_DATE')
    raw = derive_counts(parent['files']['raw_candidate_union'], parent_path.parent, days, 'raw', observations)
    model = derive_counts(parent['files']['candidates'], parent_path.parent, days, 'model', observations)
    require(stat_identity(parent_path) == parent_stat, 'PARENT_MANIFEST_STAT_DRIFT')
    output.mkdir(parents=True, exist_ok=False)
    coverage = output / 'coverage.csv'
    with coverage.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields + FIELDS, lineterminator='\n')
        writer.writeheader()
        for _, row in original:
            writer.writerow({**row, **raw[row['target_date']], **model[row['target_date']]})
        stream.flush()
        os.fsync(stream.fileno())
    provenance = dict(schema='V194_SOURCE_COVERAGE_EXTENSION_V1', execution_id=config['execution_id'],
        config_sha256=config_sha256, helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        parent_manifest=ref, parent_input_sha256=parent['input_sha256'], inputs=observations,
        original_coverage_fields=fields, appended_fields=FIELDS,
        policy='Each scope counts its actual saved three-state cells; zero-row dates have zero denominators. No absence inference.',
        formula_evaluations=0, new_label_evaluations=0, model_fits=0, maximum_claim='DIRECTION_ONLY', **FLAGS)
    derived = copy.deepcopy(parent)
    derived['files']['coverage'] = dict(path=str(coverage), sha256=hashlib.sha256(coverage.read_bytes()).hexdigest(), rows=len(days))
    derived['source_coverage_extension'] = provenance
    derived['input_sha256'] = canonical_sha(derived['files'])
    core_sha = verify_core_equivalence(parent, derived)
    manifest_path = output / 'MANIFEST.json'
    write_json_new(manifest_path, derived)
    receipt = dict(schema='V194_SOURCE_COVERAGE_DERIVATION_RECEIPT_V1', status='DERIVED_METADATA_ONLY_PENDING_INDEPENDENT_REVIEW',
        execution_id=config['execution_id'], parent_manifest=ref,
        manifest=dict(path=str(manifest_path), sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest()),
        input_sha256=derived['input_sha256'], coverage=derived['files']['coverage'], core_identity_sha256=core_sha,
        unchanged_file_bindings={key: item for key, item in parent['files'].items() if key != 'coverage'},
        preserved_original_columns=True, original_coverage_row_order_preserved=True,
        scope_rows={item: sum(v[item + '_source_state_denominator'] for v in values.values()) for item, values in [('raw', raw), ('model', model)]},
        provenance=provenance, **FLAGS)
    write_json_new(output / 'DERIVATION_RECEIPT.json', receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--config-sha256', required=True)
    args = parser.parse_args()
    payload = Path(args.config).read_bytes()
    require(hashlib.sha256(payload).hexdigest() == args.config_sha256, 'CONFIG_SHA_DRIFT')
    config = json.loads(payload)
    require(config['helper_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'HELPER_SHA_DRIFT')
    result = derive(config, args.config_sha256)
    print(json.dumps({'status': result['status'], 'manifest': result['manifest'], 'scope_rows': result['scope_rows']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
