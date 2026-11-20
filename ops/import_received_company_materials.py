"""Project received research into the existing company-materials owner contract.

prepare writes staging only. publish reuses the explicitly pinned existing
owner adapter (shared A_LONG lock, index/event CAS and owner.save). No provider,
financial parsing, selection, history evaluation, or scheduler is introduced.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
TEXT_FIELDS = ('business', 'profit_driver', 'growth_quality', 'cash_debt_quality',
               'industry_chain_position', 'bottleneck_evidence', 'customer_commercialization',
               'orders_capacity', 'valuation_method', 'valuation_date', 'valuation_assessment',
               'catalyst', 'key_risks', 'counter_evidence', 'evidence_summary', 'research_notes')
META_FIELDS = ('screened_name', 'verified_name', 'as_of', 'latest_financial_period',
               'research_as_of', 'research_tier', 'evidence_quality', 'status', 'risk_review_scope',
               'new_or_reused', 'prior_status', 'prior_research_as_of', 'reused_modules',
               'package_id', 'input_digest', 'source_date', 'observation_date', 'source_generation',
               'industry_secondary_status', 'industry_secondary_theme', 'industry_secondary_level',
               'industry_secondary_reason', 'industry_secondary_gap', 'scope_completion',
               'input_fundamental_status', 'research_scope_role')

V1_SCHEMA = 'V4_RECEIVED_RESEARCH_IMPORT_V1'
V2_SCHEMA = 'V4_RECEIVED_RESEARCH_IMPORT_V2'
V3_SCHEMA = 'V4_RECEIVED_RESEARCH_IMPORT_V3'
FORMULA_SCOPE_SCHEMA = 'V4_FORMULA_GROUP_SCOPED_IMPORT_V1'
FORMULA_PRESENTATION_REVISION_SCHEMA = 'V4_FORMULA_GROUP_PRESENTATION_REVISION_V1'
FORMULA_GROUPS = ('b23_entry', 'pb2_confirm')
FORMULA_SECONDARY_DISPLAY_FIELDS = frozenset({
    'industry_secondary_status', 'industry_secondary_theme',
    'failure_and_counterevidence', 'industry_external_evidence',
})
FORMULA_SHARED_SOURCE_MEMBERS = {
    'V2_DAILY_PERFORMANCE': 'DAILY_PERFORMANCE.csv',
    'V2_STRUCTURE_INPUT': 'STRUCTURE_INPUT.csv',
}
V2_SHARED_SOURCES = {
    'INPUT_CANDIDATES': ('shared_candidates', 'CANDIDATES.csv'),
    'INPUT_DAILY_PERFORMANCE': ('daily_performance_csv', 'DAILY_PERFORMANCE.csv'),
    'INPUT_PRIOR_RESEARCH': ('shared_prior_research', 'PRIOR_RESEARCH.csv'),
    'INPUT_PRIOR_SOURCES': ('shared_prior_sources', 'PRIOR_SOURCES.csv'),
}
CHAT_RESOURCE_PRIORITIES = {
    '300856.SZ': '优先补证', '688575.SH': '优先补证', '002284.SZ': '优先补证',
    '300726.SZ': '次级观察', '300890.SZ': '次级观察', '301348.SZ': '次级观察', '301548.SZ': '次级观察',
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path):
    return dict(path=str(Path(path).resolve()), sha256=sha(path))


def checked(reference):
    path = Path(reference['path'])
    if (not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path
            or not re.fullmatch(r'[a-f0-9]{64}', reference.get('sha256', ''))
            or sha(path) != reference['sha256']):
        raise ValueError('RECEIVED_REFERENCE_DRIFT:' + str(path))
    return path


def load(reference):
    return json.loads(checked(reference).read_text(encoding='utf-8-sig'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + f'.{os.getpid()}.pending')
    with temporary.open('xb') as stream:
        stream.write(canonical(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    return ref(path)


def pinned_module(reference, name):
    path = checked(reference)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_flags(value):
    return all(value.get(key) is expected for key, expected in FLAGS.items())


def _first_present(value, keys):
    for key in keys:
        candidate = value.get(key)
        if candidate not in (None, ''):
            return candidate
    return None


def normalize_import_config(value):
    """Normalize the V2 return aliases while leaving the V1 contract intact."""
    if not isinstance(value, dict) or not safe_flags(value):
        raise ValueError('RECEIVED_CONFIG_INVALID')
    schema = value.get('schema')
    if schema == V1_SCHEMA:
        if 'formula_scope' in value:
            raise ValueError('RECEIVED_FORMULA_SCOPE_V3_REQUIRED')
        return copy.deepcopy(value), 'V1'
    if schema == V3_SCHEMA:
        normalized=copy.deepcopy(value)
        normalized['schema']=V1_SCHEMA
        for key in ('source_date','target_date'):
            normalized[key]=str(normalized.get(key,'')).replace('-','')
        if 'formula_scope' in normalized and not isinstance(normalized['formula_scope'], dict):
            raise ValueError('RECEIVED_FORMULA_SCOPE_CONTRACT_INVALID')
        return normalized, 'V3'
    if schema != V2_SCHEMA:
        raise ValueError('RECEIVED_CONFIG_INVALID')
    normalized = copy.deepcopy(value)
    normalized['_source_schema'] = V2_SCHEMA
    normalized['schema'] = V1_SCHEMA
    normalized['source_date'] = _first_present(value, ('source_date', 'data_date'))
    normalized['target_date'] = _first_present(value, ('observation_date', 'target_date'))
    normalized['generation'] = _first_present(value, ('source_generation', 'generation'))
    normalized['input_sha256'] = _first_present(value, ('source_input_sha256', 'input_sha256'))
    numeric_manifest = value.get('numeric_manifest')
    normalized['numeric_manifest_sha256'] = _first_present(value, ('numeric_manifest_sha256',)) or (
        numeric_manifest.get('sha256') if isinstance(numeric_manifest, dict) else None)
    normalized['scope_count'] = _first_present(value, ('scope_count', 'scope'))
    inputs = value.get('inputs')
    if not isinstance(inputs, dict):
        raise ValueError('RECEIVED_CONFIG_INVALID')
    normalized_inputs = copy.deepcopy(inputs)
    aliases = {
        'fundamentals': ('fundamentals',),
        'sources': ('sources',),
        'claims': ('claim_lineage', 'claims'),
        'input_manifest': ('batch_manifest', 'input_manifest'),
        'return_manifest': ('return_manifest',),
        'daily_performance': ('daily_performance_csv', 'daily_performance'),
        'classification_rows': ('classification_rows', 'classification'),
        'classification_csv': ('classification_csv',),
        'classification_qa': ('classification_qa',),
        'priority_review': ('priority_review',),
    }
    for target, candidates in aliases.items():
        reference = _first_present(inputs, candidates)
        if not isinstance(reference, dict):
            raise ValueError('RECEIVED_V2_INPUT_ALIAS_MISSING:' + target)
        normalized_inputs[target] = reference
    shared = {}
    for source_id, (input_key, _) in V2_SHARED_SOURCES.items():
        reference = inputs.get(input_key)
        if not isinstance(reference, dict):
            raise ValueError('RECEIVED_V2_SHARED_INPUT_MISSING:' + source_id)
        shared[source_id] = reference
    normalized['_v2_shared_inputs'] = shared
    normalized['inputs'] = normalized_inputs
    if any(normalized.get(key) in (None, '') for key in (
            'source_date', 'target_date', 'generation', 'input_sha256', 'numeric_manifest_sha256', 'scope_count')):
        raise ValueError('RECEIVED_V2_IDENTITY_ALIAS_MISSING')
    return normalized, 'V2'


def exact_rows(rows, expected, label):
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(label + '_ROWS_INVALID')
    codes = [row.get('symbol') for row in rows]
    if len(codes) != len(set(codes)) or set(codes) != expected:
        raise ValueError(label + '_EXACT_SCOPE_CONFLICT')
    return {row['symbol']: row for row in rows}


def csv_rows(reference):
    with checked(reference).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def csv_rows_bytes(raw, label):
    try:
        stream = io.StringIO(raw.decode('utf-8-sig'), newline='')
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(label + '_CSV_HEADER_INVALID')
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError(label + '_CSV_INVALID') from error
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(label + '_CSV_ROW_WIDTH_INVALID')
    return rows


def _normalized_day(value, label):
    result = str(value or '').replace('-', '')
    if not re.fullmatch(r'\d{8}', result):
        raise ValueError(label + '_DATE_INVALID')
    return result


def _groups(value, label):
    if isinstance(value, list):
        result = value
    elif isinstance(value, str):
        result = [part for part in re.split(r'[|,;]', value.strip()) if part]
    else:
        raise ValueError(label + '_GROUPS_INVALID')
    if (not result or len(result) != len(set(result))
            or any(not isinstance(group, str) or group not in FORMULA_GROUPS for group in result)):
        raise ValueError(label + '_GROUPS_INVALID')
    return set(result)


def _json_strings(value, label):
    if value in (None, ''):
        return []
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, list) or any(not isinstance(item, str) or not item for item in result):
        raise ValueError(label + '_LIST_INVALID')
    if len(result) != len(set(result)):
        raise ValueError(label + '_DUPLICATE')
    return result


def _formula_scope_context(config, product, numeric_ref, date, target, generation, input_sha, root):
    """Verify the exact, opt-in formula roster and raw package before projecting any row."""
    scope = config.get('formula_scope')
    if (not isinstance(scope, dict) or scope.get('schema') != FORMULA_SCOPE_SCHEMA
            or set(scope) != {'schema', 'roster_pointer', 'roster_artifact', 'input_zip'}):
        raise ValueError('RECEIVED_FORMULA_SCOPE_CONTRACT_INVALID')
    pointer_ref, roster_ref, zip_ref = (scope.get('roster_pointer'), scope.get('roster_artifact'), scope.get('input_zip'))
    for name, reference in (('pointer', pointer_ref), ('roster', roster_ref), ('zip', zip_ref)):
        if not isinstance(reference, dict):
            raise ValueError('RECEIVED_FORMULA_SCOPE_REFERENCE_MISSING:' + name)
        checked(reference)
    if (not re.fullmatch(r'[0-9a-f]{64}', roster_ref.get('sha256', ''))
            or not re.fullmatch(r'[0-9a-f]{64}', pointer_ref.get('sha256', ''))):
        raise ValueError('RECEIVED_FORMULA_SCOPE_SHA_INVALID')
    pointer = load(pointer_ref)
    roster = load(roster_ref)
    receipt_ref = pointer.get('receipt')
    if not isinstance(receipt_ref, dict):
        raise ValueError('RECEIVED_FORMULA_SCOPE_RECEIPT_MISSING')
    receipt = load(receipt_ref)
    iso_date = f'{date[:4]}-{date[4:6]}-{date[6:]}'
    if (pointer.get('schema') != 'V4_WORKBENCH_MODULE_COMMIT_V1'
            or pointer.get('module') != 'formula_groups' or pointer.get('date') != iso_date
            or pointer.get('artifact') != roster_ref
            or any(pointer.get(key) is not value for key, value in FLAGS.items())
            or receipt.get('status') != 'COMMITTED' or receipt.get('artifact') != roster_ref
            or _normalized_day(receipt.get('source_date'), 'FORMULA_RECEIPT') != date
            or receipt.get('generation') != generation
            or receipt.get('numeric_manifest') != numeric_ref
            or any(receipt.get(key) is not value for key, value in FLAGS.items())):
        raise ValueError('RECEIVED_FORMULA_SCOPE_POINTER_CONFLICT')
    if (not isinstance(roster, dict) or roster.get('schema') != 'V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1'
            or _normalized_day(roster.get('source_date'), 'FORMULA_ROSTER') != date
            or _normalized_day(roster.get('observation_date'), 'FORMULA_ROSTER') != target
            or roster.get('generation') != generation or roster.get('input_sha256') != input_sha
            or roster.get('numeric_manifest') != numeric_ref
            or any(roster.get(key) is not value for key, value in FLAGS.items())):
        raise ValueError('RECEIVED_FORMULA_SCOPE_ROSTER_IDENTITY_CONFLICT')
    # The existing owner serializer stores canonical JSON. Refuse a roster whose
    # source bytes cannot be reproduced exactly inside that same immutable root.
    for reference, value, label in ((pointer_ref, pointer, 'POINTER'), (roster_ref, roster, 'ROSTER'),
                                    (receipt_ref, receipt, 'RECEIPT')):
        if hashlib.sha256(canonical(value) + b'\n').hexdigest() != reference['sha256']:
            raise ValueError('RECEIVED_FORMULA_SCOPE_NONCANONICAL_' + label)
    if (Path(pointer_ref['path']).parent.name != iso_date
            or Path(pointer_ref['path']).name != 'latest.json'
            or Path(roster_ref['path']).parent.name != 'artifacts'):
        raise ValueError('RECEIVED_FORMULA_SCOPE_PATH_CONFLICT')

    roster_rows = roster.get('rows')
    if not isinstance(roster_rows, list) or len(roster_rows) != config.get('scope_count'):
        raise ValueError('RECEIVED_FORMULA_SCOPE_ROSTER_COUNT_CONFLICT')
    roster_by_symbol = {}
    actual_counts = Counter()
    for row in roster_rows:
        symbol = row.get('symbol') if isinstance(row, dict) else None
        name = row.get('display_name') if isinstance(row, dict) else None
        groups = _groups(row.get('groups'), 'FORMULA_ROSTER') if isinstance(row, dict) else set()
        if (not isinstance(symbol, str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', symbol)
                or symbol in roster_by_symbol or not isinstance(name, str) or not name.strip()):
            raise ValueError('RECEIVED_FORMULA_SCOPE_ROSTER_ROW_INVALID')
        roster_by_symbol[symbol] = dict(symbol=symbol, display_name=name, groups=sorted(groups))
        actual_counts.update(groups)
    group_counts = roster.get('group_counts')
    overlap_count = sum(1 for item in roster_by_symbol.values() if len(item['groups']) > 1)
    if (not isinstance(group_counts, dict) or set(group_counts) != set(FORMULA_GROUPS)
            or any(type(group_counts[group]) is not int or group_counts[group] <= 0 for group in FORMULA_GROUPS)
            or dict(actual_counts) != group_counts
            or not isinstance(roster.get('formula_sha256'), dict)
            or set(roster['formula_sha256']) != set(FORMULA_GROUPS)
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
                   for value in roster['formula_sha256'].values())):
        raise ValueError('RECEIVED_FORMULA_SCOPE_GROUP_COUNTS_CONFLICT')
    owner_rows = product.get('row_refs')
    per_symbol = None

    zip_path = checked(zip_ref)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or 'INPUT_MANIFEST.json' not in names:
                raise ValueError('RECEIVED_FORMULA_INPUT_ZIP_MEMBERS_INVALID')
            input_manifest = json.loads(archive.read('INPUT_MANIFEST.json'))
            file_entries = input_manifest.get('files')
            if not isinstance(file_entries, list):
                raise ValueError('RECEIVED_FORMULA_INPUT_MANIFEST_FILES_INVALID')
            files_by_name = {}
            for entry in file_entries:
                if (not isinstance(entry, dict) or not isinstance(entry.get('name'), str)
                        or entry['name'] in files_by_name or type(entry.get('bytes')) is not int
                        or not re.fullmatch(r'[0-9a-f]{64}', entry.get('sha256', ''))):
                    raise ValueError('RECEIVED_FORMULA_INPUT_MANIFEST_ENTRY_INVALID')
                files_by_name[entry['name']] = entry
            if set(names) != set(files_by_name) | {'INPUT_MANIFEST.json'}:
                raise ValueError('RECEIVED_FORMULA_INPUT_ZIP_MEMBER_SET_CONFLICT')
            member_bytes = {}
            for name, entry in files_by_name.items():
                raw = archive.read(name)
                if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
                    raise ValueError('RECEIVED_FORMULA_INPUT_MEMBER_SHA_CONFLICT:' + name)
                member_bytes[name] = raw
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        raise ValueError('RECEIVED_FORMULA_INPUT_ZIP_INVALID') from error
    input_batch = input_manifest.get('batch')
    input_counts = input_manifest.get('counts')
    if (not isinstance(input_batch, str) or not input_batch
            or _normalized_day(input_manifest.get('source_date'), 'FORMULA_INPUT') != date
            or _normalized_day(input_manifest.get('observation_date'), 'FORMULA_INPUT') != target
            or input_manifest.get('source_generation') != generation
            or input_manifest.get('original_list_sha256') != roster_ref['sha256']
            or input_manifest.get('numeric_manifest_sha256') != numeric_ref['sha256']
            or not isinstance(input_counts, dict)
            or type(input_counts.get('candidates')) is not int
            or input_counts.get('candidates') != len(roster_by_symbol)
            or any(input_counts.get(group) != group_counts[group] for group in FORMULA_GROUPS)
            or type(input_counts.get('overlap')) is not int
            or input_counts.get('overlap') != overlap_count
            or input_manifest.get('research_only') is not True):
        raise ValueError('RECEIVED_FORMULA_INPUT_MANIFEST_IDENTITY_CONFLICT')
    input_validation = input_manifest.get('input_validation')
    if input_validation is not None and not isinstance(input_validation, dict):
        raise ValueError('RECEIVED_FORMULA_INPUT_VALIDATION_INVALID')
    if input_validation and (input_validation.get('input_zip_sha256') != zip_ref['sha256']
            or input_validation.get('scope_match') is not True
            or input_validation.get('date_match') is not True
            or input_validation.get('source_generation') != generation
            or input_validation.get('original_list_sha256') != roster_ref['sha256']):
        raise ValueError('RECEIVED_FORMULA_INPUT_VALIDATION_CONFLICT')
    if not isinstance(owner_rows, dict) or not set(roster_by_symbol) <= set(owner_rows):
        raise ValueError('RECEIVED_FORMULA_OWNER_ROW_REF_MISSING')
    per_symbol = input_manifest.get('per_symbol')
    if not isinstance(per_symbol, dict) or set(per_symbol) != set(roster_by_symbol):
        raise ValueError('RECEIVED_FORMULA_PER_SYMBOL_INPUT_BINDING_MISSING')
    for symbol, candidate in roster_by_symbol.items():
        reference = owner_rows[symbol]
        path = Path(reference.get('path', ''))
        if (not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path
                or not path.is_relative_to(root) or not re.fullmatch(r'[0-9a-f]{64}', reference.get('sha256', ''))
                or sha(path) != reference['sha256']
                or per_symbol[symbol].get('owner_row_sha256') != reference['sha256']):
            raise ValueError('RECEIVED_FORMULA_OWNER_ROW_SHA_CONFLICT:' + symbol)
        owner = json.loads(path.read_text(encoding='utf-8-sig'))
        if (owner.get('symbol') != symbol or owner.get('data_date') != date
                or owner.get('display_name') != candidate['display_name']
                or any(owner.get(key) is not value for key, value in FLAGS.items())):
            raise ValueError('RECEIVED_FORMULA_OWNER_ROW_IDENTITY_CONFLICT:' + symbol)

    required_members = {'CANDIDATES.csv', 'DAILY_PERFORMANCE.csv', 'STRUCTURE_INPUT.csv'}
    if not required_members <= set(member_bytes):
        raise ValueError('RECEIVED_FORMULA_INPUT_REQUIRED_MEMBER_MISSING')
    candidate_rows = exact_rows(csv_rows_bytes(member_bytes['CANDIDATES.csv'], 'FORMULA_CANDIDATES'),
                                set(roster_by_symbol), 'FORMULA_CANDIDATES')
    performance_rows = exact_rows(csv_rows_bytes(member_bytes['DAILY_PERFORMANCE.csv'], 'FORMULA_DAILY_PERFORMANCE'),
                                   set(roster_by_symbol), 'FORMULA_DAILY_PERFORMANCE')
    structure_rows = exact_rows(csv_rows_bytes(member_bytes['STRUCTURE_INPUT.csv'], 'FORMULA_STRUCTURE_INPUT'),
                                set(roster_by_symbol), 'FORMULA_STRUCTURE_INPUT')
    official_zip_sha = input_manifest.get('D_market_origin', {}).get('official_zip_sha256')
    if not isinstance(official_zip_sha, str) or not re.fullmatch(r'[0-9a-f]{64}', official_zip_sha):
        raise ValueError('RECEIVED_FORMULA_MARKET_SOURCE_IDENTITY_INVALID')
    for symbol, candidate in roster_by_symbol.items():
        candidate_row, perf_row = candidate_rows[symbol], performance_rows[symbol]
        structure_row = structure_rows[symbol]
        if (candidate_row.get('name') != candidate['display_name']
                or _normalized_day(candidate_row.get('D'), 'FORMULA_CANDIDATE') != date
                or _normalized_day(candidate_row.get('O'), 'FORMULA_CANDIDATE') != target
                or _groups(candidate_row.get('groups'), 'FORMULA_CANDIDATE') != set(candidate['groups'])):
            raise ValueError('RECEIVED_FORMULA_CANDIDATE_BINDING_CONFLICT:' + symbol)
        if (perf_row.get('name') != candidate['display_name']
                or _normalized_day(perf_row.get('D'), 'FORMULA_PERFORMANCE') != date
                or perf_row.get('price_basis') != 'RAW_UNADJUSTED'
                or perf_row.get('source_zip_sha256') != official_zip_sha
                or _groups(perf_row.get('groups'), 'FORMULA_PERFORMANCE') != set(candidate['groups'])
                or not perf_row.get('cod_member') or not perf_row.get('md1_member')
                or not str(perf_row.get('cod_record_index', '')).isdigit()
                or not str(perf_row.get('md1_record_sequence', '')).isdigit()):
            raise ValueError('RECEIVED_FORMULA_PERFORMANCE_BINDING_CONFLICT:' + symbol)
        if (structure_row.get('name') != candidate['display_name']
                or _groups(structure_row.get('groups'), 'FORMULA_STRUCTURE') != set(candidate['groups'])
                or structure_row.get('owner_row_sha256') != per_symbol[symbol].get('owner_row_sha256')):
            raise ValueError('RECEIVED_FORMULA_STRUCTURE_BINDING_CONFLICT:' + symbol)
    return dict(roster=roster, roster_rows=roster_by_symbol, roster_pointer=pointer,
                roster_pointer_ref=pointer_ref, roster_artifact_ref=roster_ref,
                roster_receipt=receipt, roster_receipt_ref=receipt_ref, roster_sha256=roster_ref['sha256'],
                input_manifest=input_manifest, input_member_bytes=member_bytes,
                candidates=candidate_rows, daily_performance=performance_rows,
                structure_input=structure_rows, owner_row_refs={symbol: owner_rows[symbol] for symbol in roster_by_symbol},
                group_counts=group_counts, overlap_count=overlap_count, input_batch=input_batch,
                formula_sha256=roster['formula_sha256'],
                input_zip_ref=zip_ref, official_zip_sha256=official_zip_sha)


def json_list(value, label):
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, list):
        raise ValueError(label + '_LIST_INVALID')
    return result


def v2_shared_symbol_scope(reference):
    rows = csv_rows(reference)
    symbols = set()
    for row in rows:
        symbol = row.get('symbol') or row.get('ts_code')
        if symbol:
            symbols.add(str(symbol).strip())
    if not symbols:
        raise ValueError('RECEIVED_SHARED_INPUT_SYMBOL_SCOPE_MISSING:' + reference['path'])
    return symbols


def validate_v2_shared_sources(config, source_rows, expected_scope, input_manifest):
    source_by_id = {row['source_id']: row for row in source_rows}
    global_rows = {key for key, row in source_by_id.items() if not (row.get('symbol') or '').strip()}
    if global_rows != set(V2_SHARED_SOURCES):
        raise ValueError('RECEIVED_GLOBAL_SOURCE_IDS_CONFLICT')
    manifest_files = input_manifest.get('files')
    if not isinstance(manifest_files, dict):
        raise ValueError('RECEIVED_SHARED_INPUT_MANIFEST_FILES_INVALID')
    scopes = {}
    for source_id, (input_key, filename) in V2_SHARED_SOURCES.items():
        reference = config['_v2_shared_inputs'][source_id]
        checked(reference)
        file_entry = manifest_files.get(filename)
        source = source_by_id[source_id]
        if (not isinstance(file_entry, dict)
                or file_entry.get('sha256') != reference.get('sha256')
                or source.get('title') != filename
                or source.get('sha256') != reference.get('sha256')
                or not str(source.get('url', '')).startswith('https://drive.google.com/')):
            raise ValueError('RECEIVED_SHARED_SOURCE_BINDING_CONFLICT:' + source_id)
        symbols = v2_shared_symbol_scope(reference)
        if not symbols <= expected_scope:
            raise ValueError('RECEIVED_SHARED_SOURCE_SCOPE_OUTSIDE_BATCH:' + source_id)
        if source_id in ('INPUT_CANDIDATES', 'INPUT_DAILY_PERFORMANCE') and symbols != expected_scope:
            raise ValueError('RECEIVED_SHARED_SOURCE_SCOPE_INCOMPLETE:' + source_id)
        scopes[source_id] = symbols
    return source_by_id, scopes


def validate_v2_classification(config, received, scope, date, target, generation, input_sha):
    classification_rows = exact_rows(load(config['inputs']['classification_rows']), scope, 'CLASSIFICATION')
    qa = load(config['inputs']['classification_qa'])
    classification_ref = config['inputs']['classification_rows']
    csv_ref = config['inputs']['classification_csv']
    if (qa.get('status') != 'PASS_364_SCOPE_WITH_TEXT_SUPPORTED_CLASSIFICATION'
            or qa.get('scope_count') != len(scope) or qa.get('unique_symbol_count') != len(scope)
            or qa.get('classification_count') != len(scope) or qa.get('unknown_count') != 0
            or qa.get('source_sha256') != config['inputs']['fundamentals']['sha256']
            or qa.get('priority_source_sha256') != config['inputs']['priority_review'].get('sha256')
            or qa.get('json_sha256') != classification_ref.get('sha256')
            or qa.get('csv_sha256') != csv_ref.get('sha256')
            or not safe_flags(qa)):
        raise ValueError('RECEIVED_CLASSIFICATION_QA_CONFLICT')
    for symbol, row in received.items():
        classification = classification_rows[symbol]
        source_ids = json_list(row.get('source_ids', '[]'), 'SOURCE_IDS')
        if (classification.get('source_date') != date
                or classification.get('observation_date') != target
                or classification.get('source_generation') != generation
                or classification.get('screened_name') != row.get('screened_name')
                or classification.get('industry_chain_position_received') != row.get('industry_chain_position')
                or classification.get('research_tier_received') != row.get('research_tier', '')
                or classification.get('source_ids') != source_ids
                or classification.get('status') != 'RESEARCH_MAIN_CLASSIFICATION_DERIVED'
                or not safe_flags(classification)
                or classification.get('research_main_industry') in (None, '', 'UNKNOWN')
                or classification.get('user_resource_priority') != CHAT_RESOURCE_PRIORITIES.get(symbol)
                or (classification.get('user_resource_priority') is None
                    and classification.get('user_resource_priority_source') is not None)
                or (classification.get('user_resource_priority') is not None
                    and classification.get('user_resource_priority_source') != config['inputs']['priority_review']['path'])
                or not isinstance(classification.get('basis_phrase'), str)
                or classification['basis_phrase'] not in row.get('business', '')
                    and classification['basis_phrase'] not in row.get('industry_chain_position', '')):
            raise ValueError('RECEIVED_CLASSIFICATION_ROW_CONFLICT:' + symbol)
    priority_counts = Counter(row.get('user_resource_priority') for row in classification_rows.values()
                              if row.get('user_resource_priority'))
    if len(scope) == 364 and set(CHAT_RESOURCE_PRIORITIES) <= scope and priority_counts != Counter({'优先补证': 3, '次级观察': 4}):
        raise ValueError('RECEIVED_CHAT_PRIORITY_SCOPE_CONFLICT')
    return classification_rows, dict(sorted(Counter(row['research_main_industry'] for row in classification_rows.values()).items())), dict(sorted(priority_counts.items()))


def _optional_number(value, label, integer=False):
    if value in (None, ''):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError('RECEIVED_DAILY_PERFORMANCE_NUMBER_INVALID:' + label)
    if not math.isfinite(result) or (integer and not result.is_integer()):
        raise ValueError('RECEIVED_DAILY_PERFORMANCE_NUMBER_INVALID:' + label)
    return int(result) if integer else result


def v2_daily_performance(row, date, target, generation, input_sha, numeric_manifest_sha):
    symbol = row.get('symbol')
    if (not symbol or row.get('ts_code') != symbol or row.get('trade_date') != date
            or row.get('source_date') != date or row.get('observation_date') != target
            or row.get('source_generation') != generation or row.get('input_sha256') != input_sha
            or row.get('manifest_sha256') != numeric_manifest_sha
            or row.get('industry_secondary_status') != 'NOT_RUN_FOR_20261105_GENERATION'
            or row.get('future_d2') not in (None, '') or row.get('future_d5') not in (None, '')):
        raise ValueError('RECEIVED_DAILY_PERFORMANCE_IDENTITY_CONFLICT:' + str(symbol))
    performance = copy.deepcopy(row)
    performance.update(
        target_date=target, numeric_manifest_sha256=numeric_manifest_sha,
        current_target_day_return_pct=None,
        current_target_day_performance_status='NOT_MATERIALIZED_NOT_READ',
        future_d2=None, future_d5=None,
        open=_optional_number(row.get('open'), symbol + ':open'),
        high=_optional_number(row.get('high'), symbol + ':high'),
        low=_optional_number(row.get('low'), symbol + ':low'),
        close=_optional_number(row.get('close'), symbol + ':close'),
        turnover_rate_pct=_optional_number(row.get('turnover_rate_pct'), symbol + ':turnover_rate_pct'),
        day_return_pct=_optional_number(row.get('pct_chg'), symbol + ':pct_chg'),
        previous_close=_optional_number(row.get('pre_close'), symbol + ':pre_close'),
        amount_yuan=_optional_number(row.get('amount'), symbol + ':amount'),
        volume_shares=_optional_number(row.get('volume'), symbol + ':volume'),
        all_history_percentile_pct=_optional_number(row.get('price_position_all_history_pct'), symbol + ':all_history_pct'),
        all_history_sample_count=_optional_number(row.get('price_position_all_history_n'), symbol + ':all_history_n', integer=True),
        near250_percentile_pct=_optional_number(row.get('price_position_250_pct'), symbol + ':near250_pct'),
        volume_to_current_MA5=_optional_number(row.get('volume_ratio_5'), symbol + ':volume_ratio_5'),
        volume_to_prior_MA5=None, volume_ratio_dates=[],
        fundamental_evidence_level='RECEIVED_RESEARCH_NOT_FULLY_VERIFIED',
        received_source_record=copy.deepcopy(row), **FLAGS)
    return performance


def prepare_master_payload(config, numeric_ref, numeric, scope, date, target, generation, input_sha):
    """The received master is an alias of existing material fields, not a new producer."""
    inputs=config['inputs']
    original=exact_rows(csv_rows(inputs['fundamentals']),scope,'FUNDAMENTALS')
    candidates=exact_rows(csv_rows(inputs['candidates']),scope,'CANDIDATES')
    performance_rows=exact_rows(csv_rows(inputs['daily_performance']),scope,'PERFORMANCE')
    secondary_rows=exact_rows(csv_rows(inputs['secondary_rows']),scope,'SECONDARY')
    source_manifest,returned=load(inputs['input_manifest']),load(inputs['return_manifest'])
    digest=inputs['candidates']['sha256']
    for manifest in (source_manifest,returned):
        if (str(manifest.get('source_date','')).replace('-','')!=date
                or str(manifest.get('observation_date','')).replace('-','')!=target
                or manifest.get('source_generation')!=generation or manifest.get('input_digest')!=digest
                or not safe_flags(manifest)):
            raise ValueError('RECEIVED_V3_MANIFEST_IDENTITY_CONFLICT')
    if (source_manifest.get('numeric_manifest')!=numeric_ref or source_manifest.get('scope')!=len(scope)
            or returned.get('batch_id')!=source_manifest.get('package_id')):
        raise ValueError('RECEIVED_V3_NUMERIC_MANIFEST_CONFLICT')
    for key,filename in (('candidates','CANDIDATES.csv'),('daily_performance','DAILY_PERFORMANCE.csv')):
        reference=inputs[key]
        if (returned.get('current_input_bindings',{}).get(filename,{}).get('sha256')!=reference['sha256']
                or source_manifest.get('files',{}).get(filename,{}).get('sha256')!=reference['sha256']):
            raise ValueError('RECEIVED_V3_SHARED_INPUT_CONFLICT:'+key)
    payloads={item.get('file_name'):item for item in returned.get('files',[])}
    for key in ('fundamentals','sources','secondary_rows'):
        reference=inputs[key];entry=payloads.get(Path(reference['path']).name,{})
        if entry.get('sha256')!=reference['sha256'] or entry.get('bytes')!=checked(reference).stat().st_size:
            raise ValueError('RECEIVED_V3_RETURN_FILE_CONFLICT:'+key)
    sources={}
    for raw in csv_rows(inputs['sources']):
        if not raw.get('source_id') or raw['source_id'] in sources:
            raise ValueError('RECEIVED_SOURCE_ID_CONFLICT:'+str(raw.get('source_id')))
        sources[raw['source_id']]={**raw,'sha256':raw.get('original_document_sha256'),
                                  'disclosed_at':raw.get('document_date')}
    received,performance,screens={},{},{}
    for symbol,row in original.items():
        candidate=candidates[symbol];perf=performance_rows[symbol];secondary=secondary_rows[symbol]
        for record in (row,candidate,perf):
            if (str(record.get('source_date','')).replace('-','')!=date
                    or str(record.get('observation_date','')).replace('-','')!=target
                    or record.get('source_generation')!=generation or record.get('input_sha256')!=input_sha
                    or record.get('manifest_sha256')!=numeric_ref['sha256']):
                raise ValueError('RECEIVED_V3_STOCK_IDENTITY_CONFLICT:'+symbol)
        for key in ('product_sha256','row_sha256','close','pre_close','pct_chg','amount','volume'):
            if row.get(key)!=(candidate if key in ('product_sha256','row_sha256') else perf).get(key):
                raise ValueError('RECEIVED_V3_ORIGINAL_INPUT_DRIFT:'+symbol+':'+key)
        for record in (row,secondary):
            if any(str(record.get(k)).lower()!=str(v).lower() for k,v in FLAGS.items()):
                raise ValueError('RECEIVED_STOCK_SAFETY_CONFLICT:'+symbol)
        if (str(secondary.get('source_date','')).replace('-','')!=date
                or str(secondary.get('observation_date','')).replace('-','')!=target
                or row.get('input_digest')!=digest or row.get('batch_id')!=returned['batch_id']
                or not row.get('research_status') or not secondary.get('industry_secondary_status')
                or str(secondary.get('industry_research_rank_is_trade_rank')).lower()!='false'):
            raise ValueError('RECEIVED_V3_SECONDARY_IDENTITY_CONFLICT:'+symbol)
        received[symbol]={**row,'source_date':date,'observation_date':target,
            'status':row['research_status'],'screened_name':row.get('name'),
            'verified_name':row.get('current_verified_name'),'package_id':row['batch_id'],
            '_received_source_record':row}
        try:
            missing=json.loads(row.get('missing_inputs') or '[]')
        except ValueError:
            missing=[row['missing_inputs']]
        if not isinstance(missing,list):raise ValueError('RECEIVED_V3_MISSING_INPUTS_INVALID:'+symbol)
        received[symbol]['missing_inputs']=missing
        value=dict(symbol=symbol,source_date=date,target_date=target,source_generation=generation,
            numeric_manifest_sha256=numeric_ref['sha256'],current_target_day_return_pct=None,
            current_target_day_performance_status='NOT_MATERIALIZED_NOT_READ',
            fundamental_evidence_level='RECEIVED_RESEARCH_NOT_FULLY_VERIFIED',
            received_source_record=perf,future_d2=None,future_d5=None,volume_ratio_dates=[],**FLAGS)
        for dest,source in dict(close='close',previous_close='pre_close',day_return_pct='pct_chg',
            open='open',high='high',low='low',amount_yuan='amount',volume_shares='volume',
            turnover_rate_pct='turnover_rate_pct',all_history_percentile_pct='position_all_pct',
            all_history_sample_count='position_all_n',near250_percentile_pct='position_250_pct',
            volume_to_current_MA5='volume_ratio_5').items():
            value[dest]=_optional_number(perf.get(source),symbol+':'+source,integer=dest.endswith('_count'))
        value['volume_to_prior_MA5']=None
        performance[symbol]=value
        screens[symbol]=dict(status='PARTIAL_RECEIVED_MODULE',role='RESEARCH_MAPPING_ONLY',
            source_date=date,target_date=target,recorded_at=returned.get('generated_at_utc'),
            errors=[],reference_status='RECEIVED_REFERENCE_ONLY',reference_fields={},
            received_record=secondary,source_ref=inputs['secondary_rows'],receipt=inputs['return_manifest'],**FLAGS)
    # Common material construction keeps dates normalized separately from untouched original rows.
    source_manifest={**source_manifest,'input_digest':digest}
    returned={**returned,'generated_at':returned.get('generated_at_utc')}
    return received,sources,performance,screens,source_manifest,returned


def prepare_formula_scope_payload(config, numeric_ref, scope, date, target, generation, input_sha, context):
    """Project the verified formula roster without widening or replacing the 265-row product."""
    inputs = config['inputs']
    original = exact_rows(csv_rows(inputs['fundamentals']), scope, 'FUNDAMENTALS')
    secondary_rows = exact_rows(csv_rows(inputs['secondary_rows']), scope, 'SECONDARY')
    industry_rows = exact_rows(csv_rows(inputs['industry_chain_mapping']), scope, 'INDUSTRY_CHAIN_MAPPING')
    returned = load(inputs['return_manifest'])
    if (returned.get('batch_id') != context['input_manifest'].get('batch')
            or _normalized_day(returned.get('source_trade_date'), 'FORMULA_RETURN') != date
            or _normalized_day(returned.get('observation_trade_date'), 'FORMULA_RETURN') != target
            or returned.get('original_roster_sha256') != context['roster_sha256']
            or returned.get('generation') != generation
            or returned.get('status_counts') != {'COMPLETED': 0, 'PARTIAL': len(scope), 'NOT_STARTED': 0, 'BLOCKED': 0}
            or returned.get('governance', {}).get('RESEARCH_ONLY') is not True
            or any(returned.get('governance', {}).get(key) != value for key, value in FLAGS.items())
            or any(returned.get('governance', {}).get(key) != 0 for key in (
                'selection_reruns', 'original_formula_reruns', 'chart_render_reruns', 'model_fits',
                'preprocessing_fits', 'hyperparameter_tuning_runs', 'orders_count'))):
        raise ValueError('RECEIVED_FORMULA_RETURN_MANIFEST_IDENTITY_CONFLICT')
    return_artifacts = returned.get('artifacts')
    if not isinstance(return_artifacts, list):
        raise ValueError('RECEIVED_FORMULA_RETURN_ARTIFACTS_INVALID')
    return_files = {}
    for entry in return_artifacts:
        name = entry.get('file_name') if isinstance(entry, dict) else None
        if not isinstance(name, str) or name in return_files:
            raise ValueError('RECEIVED_FORMULA_RETURN_ARTIFACT_ENTRY_INVALID')
        return_files[name] = entry
    for key, logical_name in (('fundamentals', 'RESEARCH_MASTER.csv'),
                              ('sources', 'SOURCES.csv'),
                              ('secondary_rows', 'INDUSTRY_SECONDARY.csv'),
                              ('industry_chain_mapping', 'INDUSTRY_CHAIN_MAPPING.csv')):
        reference = inputs[key]
        entry = return_files.get(logical_name)
        if (not isinstance(entry, dict) or entry.get('sha256') != reference.get('sha256')
                or entry.get('bytes') != checked(reference).stat().st_size):
            raise ValueError('RECEIVED_FORMULA_RETURN_FILE_CONFLICT:' + key)
    if (len(original) != len(scope) or len(secondary_rows) != len(scope)
            or len(industry_rows) != len(scope)):
        raise ValueError('RECEIVED_FORMULA_RETURN_SCOPE_CONFLICT')

    input_manifest = context['input_manifest']
    candidate_rows = context['candidates']
    performance_rows = context['daily_performance']
    structure_rows = context['structure_input']
    sources_by_id = {}
    for raw in csv_rows(inputs['sources']):
        source_id = raw.get('source_id')
        if not source_id or source_id in sources_by_id:
            raise ValueError('RECEIVED_SOURCE_ID_CONFLICT:' + str(source_id))
        sources_by_id[source_id] = {**raw, 'sha256': raw.get('sha256'),
                                    'disclosed_at': raw.get('publish_date'),
                                    'retrieved_at': raw.get('read_at')}

    # Explicitly bind only issuer records, the two all-roster input series, and
    # peer citations named for this stock in the returned industry mapping.
    per_stock_source_binding = {}
    source_reference_counts = Counter()
    for symbol in scope:
        peer_rows = json_list(industry_rows[symbol].get('peers_and_rationale') or '[]', 'FORMULA_PEER_MAPPING')
        peers = {}
        for peer in peer_rows:
            source_id, peer_symbol, peer_name = peer.get('source_id'), peer.get('symbol'), peer.get('name')
            if (not isinstance(source_id, str) or not source_id or source_id in peers
                    or not isinstance(peer_symbol, str)
                    or not re.fullmatch(r'[A-Z0-9]{1,12}\.[A-Z0-9]{1,8}', peer_symbol)
                    or not isinstance(peer_name, str) or not peer_name.strip()):
                raise ValueError('RECEIVED_FORMULA_PEER_MAP_ROW_INVALID:' + symbol)
            peers[source_id] = dict(symbol=peer_symbol, name=peer_name, rationale=peer.get('rationale'),
                                    scope=peer.get('scope'))
        master_row = original[symbol]
        secondary_row = secondary_rows[symbol]
        reference_origins = {}
        for field in ('source_ids', 'financial_source_ids', 'industry_source_ids'):
            for source_id in _json_strings(master_row.get(field), 'FORMULA_MASTER_' + field.upper()):
                reference_origins.setdefault(source_id, []).append(field)
        source_binding = {}
        for source_id in reference_origins:
            source = sources_by_id.get(source_id)
            if source is None:
                source_binding[source_id] = dict(status='QUARANTINED_UNKNOWN_APPLICABILITY',
                    reason='SOURCE_ID_NOT_PRESENT_IN_RETURN_SOURCE_REGISTRY', origins=reference_origins[source_id])
                source_reference_counts['quarantined_unknown_applicability'] += 1
                continue
            source_symbol = (source.get('symbol') or '').strip()
            if source_symbol == symbol:
                source_binding[source_id] = dict(status='VERIFIED_TARGET_ISSUER', applicability='TARGET_ISSUER',
                    source_symbol=source_symbol, origins=reference_origins[source_id])
                source_reference_counts['target_issuer'] += 1
                continue
            shared_member = FORMULA_SHARED_SOURCE_MEMBERS.get(source_id)
            expected_scope = f'ALL_{len(scope)}'
            if shared_member and source_symbol == expected_scope:
                file_entry = next((item for item in input_manifest['files'] if item.get('name') == shared_member), None)
                source_hash = source.get('sha256') or ''
                if (file_entry is not None and (source.get('locator') or '').startswith(shared_member + '；')
                        and str(source.get('url') or '').startswith('https://drive.google.com/')
                        and (not source_hash or source_hash == file_entry.get('sha256'))
                        and symbol in context['roster_rows']):
                    source_binding[source_id] = dict(status=f'VERIFIED_BATCH_INPUT_{len(scope)}',
                        applicability=f'BATCH_INPUT_ALL_{len(scope)}', source_symbol=source_symbol,
                        input_member=shared_member, input_member_sha256=file_entry['sha256'],
                        declared_scope=expected_scope, locator=source['locator'],
                        source_title=source.get('title'), source_url=source.get('url'),
                        source_registry_ref=inputs['sources'], origins=reference_origins[source_id])
                    source_reference_counts[f'batch_input_all_{len(scope)}'] += 1
                    continue
            peer = peers.get(source_id)
            if (peer and source_symbol in (peer['symbol'], 'PEER_ONLY')
                    and peer['name'] in (source.get('title') or '')):
                source_binding[source_id] = dict(status='VERIFIED_PEER_ONLY', applicability='PEER_ONLY',
                    source_symbol=source_symbol, peer_symbol=peer['symbol'], peer_name=peer['name'],
                    peer_mapping=peer, origins=reference_origins[source_id])
                source_reference_counts['peer_only'] += 1
                continue
            source_binding[source_id] = dict(status='QUARANTINED_UNKNOWN_APPLICABILITY',
                reason='FOREIGN_SOURCE_NOT_CORROBORATED_BY_PER_STOCK_PEER_MAPPING',
                source_symbol=source_symbol, origins=reference_origins[source_id])
            source_reference_counts['quarantined_unknown_applicability'] += 1
        per_stock_source_binding[symbol] = source_binding

    received, performance, screens, stock_scope = {}, {}, {}, {}
    market_fields = {
        'open': 'open_CNY', 'high': 'high_CNY', 'low': 'low_CNY', 'close': 'close_CNY',
        'previous_close': 'previous_close_CNY', 'pct_chg': 'change_pct_from_raw_previous_close',
        'volume': 'volume_shares', 'amount': 'amount_CNY',
    }
    for symbol in sorted(scope):
        row = original[symbol]
        candidate = candidate_rows[symbol]
        perf = performance_rows[symbol]
        secondary = secondary_rows[symbol]
        structure = structure_rows[symbol]
        membership = context['roster_rows'][symbol]
        row_date = _normalized_day(row.get('source_trade_date'), 'FORMULA_MASTER')
        observation_date = _normalized_day(row.get('observation_trade_date'), 'FORMULA_MASTER')
        if (row_date != date or observation_date != target
                or row.get('batch_id') != returned['batch_id']
                or secondary.get('batch_id') != returned['batch_id']
                or _normalized_day(secondary.get('source_trade_date'), 'FORMULA_SECONDARY') != date
                or _normalized_day(secondary.get('observation_trade_date'), 'FORMULA_SECONDARY') != target
                or _normalized_day(industry_rows[symbol].get('source_trade_date'), 'FORMULA_INDUSTRY') != date
                or _normalized_day(industry_rows[symbol].get('observation_trade_date'), 'FORMULA_INDUSTRY') != target
                or _groups(row.get('groups'), 'FORMULA_MASTER') != set(membership['groups'])
                or _groups(secondary.get('groups'), 'FORMULA_SECONDARY') != set(membership['groups'])
                or _groups(industry_rows[symbol].get('groups'), 'FORMULA_INDUSTRY') != set(membership['groups'])
                or candidate.get('name') != membership['display_name']
                or row.get('company') != membership['display_name']
                or secondary.get('company') != membership['display_name']
                or industry_rows[symbol].get('company') != membership['display_name']
                or structure.get('name') != membership['display_name']
                or row.get('research_status') != 'PARTIAL'
                or any(str(row.get(key)).lower() != str(value).lower() for key, value in FLAGS.items())):
            raise ValueError('RECEIVED_FORMULA_STOCK_IDENTITY_CONFLICT:' + symbol)
        for field, perf_field in market_fields.items():
            left = row.get({'open': 'd_open_price', 'high': 'd_high_price', 'low': 'd_low_price',
                            'close': 'd_close_price', 'previous_close': 'd_previous_close',
                            'pct_chg': 'd_change_pct', 'volume': 'd_volume_shares',
                            'amount': 'd_turnover_value'}[field])
            right = perf.get(perf_field)
            try:
                equal = Decimal(str(left)) == Decimal(str(right))
            except (InvalidOperation, TypeError, ValueError):
                equal = False
            if not equal:
                raise ValueError('RECEIVED_FORMULA_DAILY_INPUT_DRIFT:' + symbol + ':' + field)
        source_ids = list(per_stock_source_binding[symbol])
        missing_inputs = row.get('remaining_material_gaps') or ''
        try:
            parsed_missing = json.loads(missing_inputs) if isinstance(missing_inputs, str) else missing_inputs
            missing_inputs = parsed_missing if isinstance(parsed_missing, list) else [str(missing_inputs)]
        except (ValueError, TypeError):
            missing_inputs = [part.strip() for part in str(missing_inputs).split(';') if part.strip()]
        if not missing_inputs:
            missing_inputs = []
        normalized = {**row, 'source_date': date, 'observation_date': target,
            'source_generation': generation, 'input_sha256': input_sha,
            'manifest_sha256': numeric_ref['sha256'], 'input_digest': hashlib.sha256(
                context['input_member_bytes']['CANDIDATES.csv']).hexdigest(),
            'status': row.get('research_status'), 'screened_name': row.get('company'),
            'verified_name': row.get('verified_current_name') or row.get('company'),
            'research_as_of': None,
            'package_id': returned['batch_id'], 'source_ids': source_ids,
            'missing_inputs': missing_inputs, '_received_source_record': copy.deepcopy(row)}
        received[symbol] = normalized
        value = dict(symbol=symbol, source_date=date, target_date=target, source_generation=generation,
            numeric_manifest_sha256=numeric_ref['sha256'], current_target_day_return_pct=None,
            current_target_day_performance_status='NOT_MATERIALIZED_NOT_READ',
            fundamental_evidence_level='RECEIVED_RESEARCH_NOT_FULLY_VERIFIED',
            received_source_record=copy.deepcopy(perf), future_d2=None, future_d5=None,
            volume_ratio_dates=[], price_basis=perf.get('price_basis'), **FLAGS)
        for destination, source in (('open', 'open_CNY'), ('high', 'high_CNY'), ('low', 'low_CNY'),
                ('close', 'close_CNY'), ('previous_close', 'previous_close_CNY'),
                ('day_return_pct', 'change_pct_from_raw_previous_close'),
                ('amount_yuan', 'amount_CNY'), ('volume_shares', 'volume_shares')):
            value[destination] = _optional_number(perf.get(source), symbol + ':' + source)
        for destination in ('turnover_rate_pct', 'all_history_percentile_pct', 'all_history_sample_count',
                           'near250_percentile_pct', 'volume_to_current_MA5', 'volume_to_prior_MA5'):
            value[destination] = None
        performance[symbol] = value
        display_record = _formula_secondary_display_record(secondary)
        screens[symbol] = dict(status='PARTIAL_RECEIVED_MODULE', role='INDUSTRY_SECONDARY_RECEIVED',
            source_date=date, target_date=target, recorded_at=returned.get('created_at'), errors=[],
            reference_status='RECEIVED_REFERENCE_ONLY', reference_fields={},
            received_record=display_record, raw_received_record=copy.deepcopy(secondary),
            source_ref=inputs['secondary_rows'],
            receipt=inputs['return_manifest'], **FLAGS)
        stock_scope[symbol] = dict(symbol=symbol, name=membership['display_name'],
            groups=membership['groups'], source_date=date, observation_date=target,
            roster_sha256=context['roster_sha256'], owner_row_ref=context['owner_row_refs'][symbol],
            structure_input=copy.deepcopy(structure))
    source_manifest = dict(source_date=date, observation_date=target, source_generation=generation,
        input_digest=hashlib.sha256(context['input_member_bytes']['CANDIDATES.csv']).hexdigest(),
        numeric_manifest=numeric_ref, scope=len(scope), package_id=returned['batch_id'],
        files={entry['name']: dict(sha256=entry['sha256'], bytes=entry['bytes'])
               for entry in input_manifest['files']},
        **FLAGS)
    # The original return manifest has `created_at` rather than a synthetic
    # generated_at field; this alias is only used by the common receipt display.
    normalized_return = {**returned, 'generated_at': returned.get('created_at'), **FLAGS}
    summary = dict(source_date=date, target_date=target, generation=generation, input_sha256=input_sha,
        scope_count=len(scope), research_as_of=None,
        secondary_recorded_at=returned.get('created_at'), themes=[], technical_observe_count=0,
        wait_for_trigger_count=0, original_producer_status_counts={'PARTIAL': len(scope)},
        specified_primary_page_check_count=0, strict_full_chain_certified_count=0,
        return_schema=V3_SCHEMA, secondary_status='PARTIAL_RECEIVED_MODULE',
        secondary_status_counts={'PARTIAL_RECEIVED_MODULE': len(scope)},
        package_id=returned['batch_id'], formula_group_scope=dict(roster_sha256=context['roster_sha256'],
            group_counts=context['group_counts'], overlap_count=context['overlap_count'], candidate_count=len(scope),
            status='VERIFIED_EXACT_SUBSET'),
        source_binding_counts=dict(source_reference_counts), **FLAGS)
    return received, sources_by_id, performance, screens, source_manifest, normalized_return, summary, per_stock_source_binding, stock_scope


def _formula_secondary_display_record(source):
    """Add only fields the existing company card can display from this V2 row."""
    decision = source.get('decision')
    if decision not in {'SELECTED_FOR_EVIDENCE_BASED_RESEARCH', 'NOT_SELECTED_IN_THIS_BATCH'}:
        raise ValueError('RECEIVED_FORMULA_SECONDARY_DECISION_INVALID:' + str(source.get('symbol')))
    candidate_sector = source.get('candidate_sector')
    if not isinstance(candidate_sector, str) or not candidate_sector.strip():
        raise ValueError('RECEIVED_FORMULA_SECONDARY_CANDIDATE_SECTOR_MISSING:' + str(source.get('symbol')))
    record = copy.deepcopy(source)
    record.update(
        industry_secondary_status=(
            'PARTIAL_SELECTED_FOR_EVIDENCE_BASED_RESEARCH'
            if decision == 'SELECTED_FOR_EVIDENCE_BASED_RESEARCH'
            else 'PARTIAL_NOT_SELECTED_IN_THIS_BATCH'
        ),
        industry_secondary_theme=(
            '未列入本批研究方向' if candidate_sector == 'NOT_SELECTED' else candidate_sector
        ),
    )
    direct_mappings = {
        'failure_and_counterevidence': 'company_counterevidence',
        'industry_external_evidence': 'overseas_facts_and_counterevidence',
    }
    for target, origin in direct_mappings.items():
        value = source.get(origin)
        if isinstance(value, str) and value.strip():
            record[target] = value
    return record


def _validate_scoped_presentation_revision(index, config, context, revision):
    if revision is None:
        return None
    expected_sha = revision.get('expected_previous_manifest_sha256') if isinstance(revision, dict) else None
    if (not isinstance(revision, dict)
            or set(revision) != {'schema', 'expected_previous_manifest_sha256'}
            or revision.get('schema') != FORMULA_PRESENTATION_REVISION_SCHEMA
            or not isinstance(expected_sha, str)
            or not re.fullmatch(r'[0-9a-f]{64}', expected_sha)):
        raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_INVALID')
    if context is None:
        raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_REQUIRES_FORMULA_SCOPE')
    date = config['source_date']
    previous = index.get('company_materials_scoped', {}).get(date, {}).get(context['roster_sha256'])
    if not isinstance(previous, dict) or previous.get('sha256') != expected_sha:
        raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_PRIOR_REF_CONFLICT')
    if (previous.get('path') is None or not Path(previous['path']).is_file()
            or sha(previous['path']) != expected_sha):
        raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_PRIOR_MANIFEST_INVALID')
    return dict(schema=FORMULA_PRESENTATION_REVISION_SCHEMA,
                expected_previous_manifest_sha256=expected_sha,
                previous_ref=copy.deepcopy(previous), date=date,
                observation_date=config['target_date'], generation=config['generation'],
                input_sha256=config['input_sha256'], roster_sha256=context['roster_sha256'])


def _validate_revision_materials(previous_ref, materials, immutable_files, revision):
    previous = load(previous_ref)
    identity = dict(data_date=revision['date'], source_generation=revision['generation'],
                    input_sha256=revision['input_sha256'])
    if (any(previous.get(key) != value for key, value in identity.items())
            or previous.get('formula_group_scope', {}).get('source_date') != revision['date']
            or previous.get('formula_group_scope', {}).get('observation_date') != revision['observation_date']
            or previous.get('formula_group_scope', {}).get('roster_sha256') != revision['roster_sha256']
            or set(previous.get('items', {})) != set(materials.get('items', {}))
            or not safe_flags(previous)):
        raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_IDENTITY_CONFLICT')
    old_manifest_body = {key: value for key, value in previous.items() if key != 'items'}
    new_manifest_body = {key: value for key, value in materials.items() if key != 'items'}
    if old_manifest_body != new_manifest_body:
        raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_MANIFEST_DELTA_CONFLICT')
    for symbol, old_ref in previous['items'].items():
        old = load(old_ref)
        new_ref = materials['items'][symbol]
        new_path = immutable_files.get(new_ref['path'])
        if not isinstance(new_path, dict):
            raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_STAGED_ROW_MISSING:' + symbol)
        new = load(new_path)
        before_screen = old.get('secondary_screen')
        after_screen = new.get('secondary_screen')
        if (not isinstance(before_screen, dict) or not isinstance(after_screen, dict)
                or before_screen.get('role') != 'INDUSTRY_SECONDARY_RECEIVED'
                or after_screen.get('role') != before_screen.get('role')
                or after_screen.get('raw_received_record') != before_screen.get('received_record')):
            raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_RAW_ROW_CONFLICT:' + symbol)
        after_without_projection = copy.deepcopy(new)
        projected = after_without_projection['secondary_screen']['received_record']
        for key in FORMULA_SECONDARY_DISPLAY_FIELDS:
            projected.pop(key, None)
        after_without_projection['secondary_screen'].pop('raw_received_record', None)
        if after_without_projection != old:
            raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_NONDISPLAY_DELTA:' + symbol)


def prepare(config_reference, stage, *, scoped_presentation_revision=None):
    config, import_mode = normalize_import_config(load(config_reference))
    root, stage = Path(config['product_root']), Path(stage).resolve()
    if (not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root
            or stage.is_relative_to(root) or root.is_relative_to(stage)):
        raise ValueError('RECEIVED_STAGING_MUST_BE_ISOLATED')
    date, target = config['source_date'], config['target_date']
    if not re.fullmatch(r'\d{8}', date) or not re.fullmatch(r'\d{8}', target) or target <= date:
        raise ValueError('RECEIVED_DATE_CONFLICT')
    inputs = config['inputs']
    # Pin every input before constructing any publication plan.
    for reference in [config['owner_publisher'], config['publication_adapter'], *inputs.values()]:
        checked(reference)
    lock_path = Path(config['owner_lock'])
    info = lock_path.lstat()
    if lock_path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ValueError('EXISTING_SHARED_OWNER_LOCK_REQUIRED')
    lock = dict(path=str(lock_path.resolve()), device=info.st_dev, inode=info.st_ino)
    expected_index, expected_event = ref(root / 'index.json'), ref(root / 'events/latest.json')
    index, event = load(expected_index), load(expected_event)
    numeric_ref = index['dates'][date]
    numeric, product = load(numeric_ref), None
    product = load(numeric['artifact'])
    generation, input_sha = config['generation'], config['input_sha256']
    if (numeric_ref['sha256'] != config['numeric_manifest_sha256']
            or product.get('data_date') != date or numeric.get('data_date') != date
            or product.get('source_generation') != generation or numeric.get('source_generation') != generation
            or product.get('source_identity', {}).get('input_sha256') != input_sha
            or numeric.get('input_sha256') != input_sha
            or not safe_flags(event)):
        raise ValueError('RECEIVED_NUMERIC_OR_EVENT_IDENTITY_CONFLICT')
    latest_date = index.get('latest_date')
    latest_ref = index.get('latest')
    latest_numeric = load(latest_ref)
    if (not isinstance(latest_date, str) or date > latest_date or index['dates'].get(latest_date) != latest_ref
            or event.get('data_date') != latest_date or event.get('manifest') != latest_ref
            or event.get('artifact') != latest_numeric.get('artifact')
            or any(event.get(k) != latest_numeric.get(k) for k in ('data_date', 'source_generation', 'input_sha256'))):
        raise ValueError('RECEIVED_LATEST_NUMERIC_OR_EVENT_IDENTITY_CONFLICT')
    received_at = config.get('received_at') or datetime.now(timezone.utc).isoformat()
    try:
        received_time=datetime.fromisoformat(received_at.replace('Z','+00:00'))
        if received_time.tzinfo is None or received_time>datetime.now(timezone.utc):raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise ValueError('RECEIVED_LOCAL_RECEIPT_TIME_INVALID')
    if import_mode=='V3' and not config.get('received_at'):
        raise ValueError('RECEIVED_V3_LOCAL_RECEIPT_TIME_REQUIRED')
    formula_context = None
    if 'formula_scope' in config:
        if import_mode != 'V3':
            raise ValueError('RECEIVED_FORMULA_SCOPE_V3_REQUIRED')
        formula_context = _formula_scope_context(config, product, numeric_ref, date, target,
                                                generation, input_sha, root)
        scope = set(formula_context['roster_rows'])
        if len(scope) != config['scope_count']:
            raise ValueError('RECEIVED_FORMULA_SCOPE_COUNT_CONFLICT')
    else:
        codes = [row['symbol'] for row in product['rows']]
        scope = set(codes)
        if len(codes) != len(scope) or len(scope) != config['scope_count']:
            raise ValueError('RECEIVED_NUMERIC_EXACT_SCOPE_CONFLICT')
    scoped_revision = _validate_scoped_presentation_revision(
        index, config, formula_context, scoped_presentation_revision)
    if formula_context is None:
        received = exact_rows(csv_rows(inputs['fundamentals']), scope, 'FUNDAMENTALS')
        source_manifest = load(inputs['input_manifest'])
        return_manifest = load(inputs['return_manifest'])
    formula_summary = formula_source_bindings = formula_stock_scope = None
    if import_mode == 'V1':
        screens = exact_rows(load(inputs['secondary_rows']), scope, 'SECONDARY')
        performance_payload = load(inputs['daily_performance'])
        if (performance_payload.get('source_date') != date or performance_payload.get('target_date') != target
                or performance_payload.get('source_generation') != generation
                or performance_payload.get('numeric_manifest_sha256') != numeric_ref['sha256']
                or not safe_flags(performance_payload)):
            raise ValueError('RECEIVED_PERFORMANCE_IDENTITY_CONFLICT')
        performance = exact_rows(performance_payload['rows'], scope, 'PERFORMANCE')
        if any(source_manifest.get(k) != v for k, v in dict(source_date=date, target_date=target,
                source_generation=generation, source_input_sha256=input_sha,
                numeric_manifest_sha256=config['numeric_manifest_sha256']).items()):
            raise ValueError('RECEIVED_INPUT_MANIFEST_CONFLICT')
        if (return_manifest.get('source_date') != date or return_manifest.get('target_date') != target
                or return_manifest.get('input_digest') != source_manifest.get('input_digest')
                or not safe_flags(return_manifest)):
            raise ValueError('RECEIVED_RETURN_MANIFEST_CONFLICT')
        receipt = load(inputs['secondary_receipt'])
        if (receipt.get('scope_size') != len(scope) or receipt.get('strict_full_chain_certified_count') != 0
                or not safe_flags(receipt.get('safety_flags', {}))):
            raise ValueError('RECEIVED_SECONDARY_RECEIPT_CONFLICT')
        classification, classification_counts, priority_counts = {}, {}, {}
        shared_scopes = {}
    elif import_mode == 'V2':
        manifest_numeric = source_manifest.get('numeric_manifest')
        product_identity = source_manifest.get('numeric_product')
        if (source_manifest.get('source_date') != date or source_manifest.get('observation_date') != target
                or source_manifest.get('source_generation') != generation
                or source_manifest.get('scope') != len(scope)
                or not isinstance(manifest_numeric, dict) or manifest_numeric.get('sha256') != numeric_ref['sha256']
                or not isinstance(product_identity, dict) or product_identity.get('sha256') != numeric['artifact'].get('sha256')
                or not source_manifest.get('input_digest') or not safe_flags(source_manifest)):
            raise ValueError('RECEIVED_V2_INPUT_MANIFEST_CONFLICT')
        if (return_manifest.get('source_date') != date or return_manifest.get('observation_date') != target
                or return_manifest.get('source_generation') != generation
                or return_manifest.get('scope') != len(scope)
                or return_manifest.get('input_digest') != source_manifest.get('input_digest')
                or return_manifest.get('package_id') != source_manifest.get('package_id')
                or not safe_flags(return_manifest)):
            raise ValueError('RECEIVED_RETURN_MANIFEST_CONFLICT')
        source_rows_for_binding = csv_rows(inputs['sources'])
        sources_by_id, shared_scopes = validate_v2_shared_sources(config, source_rows_for_binding, scope, source_manifest)
        classification, classification_counts, priority_counts = validate_v2_classification(
            config, received, scope, date, target, generation, input_sha)
        performance_rows = csv_rows(inputs['daily_performance'])
        performance_source = exact_rows(performance_rows, scope, 'PERFORMANCE')
        performance = {symbol: v2_daily_performance(row, date, target, generation, input_sha, numeric_ref['sha256'])
                       for symbol, row in performance_source.items()}
        screens = {}
        for symbol, row in received.items():
            if row.get('industry_secondary_status') != 'NOT_RUN_FOR_20261105_GENERATION':
                raise ValueError('RECEIVED_V2_SECONDARY_STATUS_CONFLICT:' + symbol)
            screens[symbol] = dict(
                status='NOT_RUN_FOR_20261105_GENERATION', role='NOT_RUN', source_date=date,
                target_date=target, recorded_at=return_manifest.get('generated_at'), errors=[],
                reference_status='NOT_RUN', reference_fields={key: None for key in (
                    'p5_key_type', 'p5_key_date', 'p5_key_age', 'volume_to_current_MA5',
                    'volume_to_prior_MA5', 'amount_yuan', 'plan_status', 'p5_risk_label',
                    'mechanical_reversal_volume_amount_pass')},
                received_record=dict(industry_secondary_status=row.get('industry_secondary_status'),
                    theme=row.get('industry_secondary_theme') or None, level=row.get('industry_secondary_level') or None,
                    reason=row.get('industry_secondary_reason') or None, gap=row.get('industry_secondary_gap') or None,
                    full_chain_status='NOT_RUN_FOR_20261105_GENERATION'),
                source_ref=inputs['daily_performance'], receipt=inputs['return_manifest'], **FLAGS)
        receipt = None
    elif formula_context is not None:
        (received, sources_by_id, performance, screens, source_manifest, return_manifest,
         formula_summary, formula_source_bindings, formula_stock_scope) = prepare_formula_scope_payload(
            config, numeric_ref, scope, date, target, generation, input_sha, formula_context)
        source_rows_for_binding = list(sources_by_id.values())
        classification, classification_counts, priority_counts, shared_scopes = {}, {}, {}, {}
        receipt = None
    else:
        received,sources_by_id,performance,screens,source_manifest,return_manifest=prepare_master_payload(
            config,numeric_ref,numeric,scope,date,target,generation,input_sha)
        source_rows_for_binding=list(sources_by_id.values())
        classification,classification_counts,priority_counts,shared_scopes={},{},{},{}
        receipt=None
    if import_mode == 'V1':
        sources_by_id = {}
        source_rows_for_binding = csv_rows(inputs['sources'])
    for row in source_rows_for_binding:
        key = row['source_id']
        if key in sources_by_id and row != sources_by_id[key]:
            raise ValueError('RECEIVED_SOURCE_ID_CONFLICT:' + key)
        sources_by_id[key] = row
    claims = {symbol: [] for symbol in scope}
    for row in (csv_rows(inputs['claims']) if 'claims' in inputs else []):
        if row.get('symbol') in scope:
            claims[row['symbol']].append(row)
    if import_mode=='V3':
        for symbol,row in received.items():
            try:
                facts=json.loads(row.get('facts') or '[]')
            except (ValueError,TypeError):
                facts=[]  # Unstructured original text remains in received_source_record.
            claims[symbol]=facts if isinstance(facts,list) and all(isinstance(f,dict) for f in facts) else []
    audits = {symbol: [] for symbol in scope}
    for name, reference in inputs.items():
        if not name.startswith('primary_check_'):
            continue
        audit = load(reference)
        entries = audit.get('items', audit.get('stocks', [audit] if audit.get('symbol') else []))
        for entry in entries:
            if entry.get('symbol') in scope:
                audits[entry['symbol']].append(dict(receipt=reference, specified_scope=entry))
    roles = {}
    themes = []
    if import_mode == 'V1':
        selected = receipt.get('selected_watchlist_by_theme', {})
        for theme, groups in selected.items():
            section = dict(theme=theme)
            for role in ('technical_observe', 'wait_for_trigger'):
                section[role] = []
                for symbol in groups.get(role, []):
                    if symbol not in scope or symbol in roles:
                        raise ValueError('RECEIVED_SELECTED_SCOPE_CONFLICT')
                    roles[symbol] = role
                    section[role].append(dict(symbol=symbol, name=received[symbol].get('screened_name')))
            themes.append(section)
    summary = formula_summary or dict(source_date=date, target_date=target, generation=generation, input_sha256=input_sha,
                   scope_count=len(scope), research_as_of=return_manifest.get('research_as_of') or return_manifest.get('generated_at'),
                   secondary_recorded_at=receipt.get('at') if receipt else return_manifest.get('generated_at'), themes=themes,
                   technical_observe_count=sum(role == 'technical_observe' for role in roles.values()),
                   wait_for_trigger_count=sum(role == 'wait_for_trigger' for role in roles.values()),
                   original_producer_status_counts=dict(Counter(row.get('status') for row in received.values())),
                   specified_primary_page_check_count=sum(bool(value) for value in audits.values()),
                   strict_full_chain_certified_count=0, **FLAGS)
    if import_mode == 'V2':
        summary.update(return_schema=V2_SCHEMA,
                       secondary_status='NOT_RUN_FOR_20261105_GENERATION',
                       secondary_status_counts=dict(Counter(row.get('industry_secondary_status') for row in received.values())),
                       research_main_industry_counts=classification_counts,
                       user_resource_priority_counts=priority_counts,
                       research_tier_preserved_count=sum(bool(row.get('research_tier')) for row in received.values()),
                       classification_ref=inputs['classification_rows'], classification_csv_ref=inputs['classification_csv'],
                       package_id=source_manifest.get('package_id'))
    if import_mode=='V3' and formula_summary is None:
        summary.update(return_schema=V3_SCHEMA,package_id=return_manifest['batch_id'],secondary_status='PARTIAL_RECEIVED_MODULE',secondary_status_counts=dict(Counter(row['received_record']['industry_secondary_status'] for row in screens.values())))
    gap_by_symbol = ({row['symbol']: row['errors'] for row in receipt.get('quote_or_feature_gaps', [])}
                     if receipt else {})
    immutable_files = {}

    def immutable(folder, name, value):
        target_path = root / folder / hashlib.sha256(canonical(value)).hexdigest() / name
        staged_ref = save(stage / 'immutable' / target_path.relative_to(root), value)
        immutable_files[str(target_path)] = staged_ref
        return dict(path=str(target_path), sha256=staged_ref['sha256'])

    formula_scope_descriptor = None
    source_refs = copy.deepcopy(inputs)
    if formula_context is not None:
        scope_folder = 'company_materials/' + date + '/formula_scope'
        pointer_ref_inside = immutable(scope_folder, 'latest.json', formula_context['roster_pointer'])
        roster_ref_inside = immutable(scope_folder, 'roster.json', formula_context['roster'])
        receipt_ref_inside = immutable(scope_folder, 'receipt.json', formula_context['roster_receipt'])
        if (pointer_ref_inside['sha256'] != formula_context['roster_pointer_ref']['sha256']
                or roster_ref_inside['sha256'] != formula_context['roster_artifact_ref']['sha256']
                or receipt_ref_inside['sha256'] != formula_context['roster_receipt_ref']['sha256']):
            raise ValueError('RECEIVED_FORMULA_SCOPE_IMMUTABLE_COPY_SHA_CONFLICT')
        formula_scope_descriptor = dict(schema=FORMULA_SCOPE_SCHEMA, source_date=date,
            observation_date=target, source_generation=generation, input_sha256=input_sha,
            numeric_manifest=numeric_ref, roster_sha256=formula_context['roster_sha256'],
            formula_sha256=formula_context['formula_sha256'], group_counts=formula_context['group_counts'],
            overlap_count=formula_context['overlap_count'], candidate_count=len(scope), source_roster_pointer_ref=formula_context['roster_pointer_ref'],
            source_roster_artifact_ref=formula_context['roster_artifact_ref'],
            source_roster_receipt_ref=formula_context['roster_receipt_ref'],
            roster_pointer_ref=pointer_ref_inside, roster_artifact_ref=roster_ref_inside,
            roster_receipt_ref=receipt_ref_inside, input_zip_ref=formula_context['input_zip_ref'], **FLAGS)
        source_refs['formula_scope'] = dict(schema=FORMULA_SCOPE_SCHEMA,
            roster_pointer=formula_context['roster_pointer_ref'],
            roster_artifact=formula_context['roster_artifact_ref'],
            roster_receipt=formula_context['roster_receipt_ref'],
            input_zip=formula_context['input_zip_ref'])

    items = {}
    for symbol in sorted(scope):
        row, screen, perf = received[symbol], copy.deepcopy(screens[symbol]), copy.deepcopy(performance[symbol])
        if (row.get('source_date') != date or row.get('observation_date') != target
                or row.get('source_generation') != generation
                or row.get('input_digest') != source_manifest.get('input_digest')
                or perf.get('source_date') != date or perf.get('target_date') != target
                or perf.get('source_generation') != generation
                or perf.get('numeric_manifest_sha256') != numeric_ref['sha256']
                or perf.get('current_target_day_return_pct') is not None
                or perf.get('current_target_day_performance_status') != 'NOT_MATERIALIZED_NOT_READ'
                or not safe_flags(perf)):
            raise ValueError('RECEIVED_STOCK_IDENTITY_CONFLICT:' + symbol)
        if import_mode == 'V1':
            if (screen.get('source_date') != date or screen.get('target_date') != target
                    or screen.get('v4_generation') != generation
                    or screen.get('full_chain_status') != 'CANNOT_CONFIRM'):
                raise ValueError('RECEIVED_STOCK_IDENTITY_CONFLICT:' + symbol)
        elif import_mode=='V2' and (screen.get('source_date') != date or screen.get('target_date') != target
                or screen.get('status') != 'NOT_RUN_FOR_20261105_GENERATION'
                or screen.get('received_record', {}).get('full_chain_status') != 'NOT_RUN_FOR_20261105_GENERATION'
                or screen.get('reference_status') != 'NOT_RUN'
                or any(value is not None for value in screen.get('reference_fields', {}).values())):
            raise ValueError('RECEIVED_V2_SECONDARY_IDENTITY_CONFLICT:' + symbol)
        if any(str(row.get(k)).lower() != str(v).lower() for k, v in FLAGS.items()):
            raise ValueError('RECEIVED_STOCK_SAFETY_CONFLICT:' + symbol)
        source_ids = json_list(row.get('source_ids', '[]'), 'SOURCE_IDS')
        selected_sources = []
        quarantined_sources = []
        for source_id in source_ids:
            source = sources_by_id.get(source_id)
            if formula_context is not None:
                binding = (formula_source_bindings or {}).get(symbol, {}).get(source_id)
                if binding is None or binding.get('status') == 'QUARANTINED_UNKNOWN_APPLICABILITY':
                    quarantined_sources.append(dict(source_id=source_id, source_record=copy.deepcopy(source),
                        binding=binding or dict(status='QUARANTINED_UNKNOWN_APPLICABILITY',
                            reason='SOURCE_ID_HAS_NO_FORMULA_SCOPE_BINDING')))
                else:
                    selected_sources.append({**source, 'source_applicability': binding['applicability'],
                                             'source_scope_status': binding['status'],
                                             'source_scope_evidence': binding})
                continue
            shared_source_ok = (import_mode == 'V2' and source_id in V2_SHARED_SOURCES
                                and source is not None and not (source.get('symbol') or '').strip()
                                and symbol in shared_scopes.get(source_id, set()))
            master_source_ok = (import_mode=='V3' and source is not None
                                and (source.get('symbols') in ('BATCH_OR_METHOD','ALL','UNKNOWN')
                                     or symbol in (json_list(source['symbols'],'SOURCE_SYMBOLS') if str(source.get('symbols','')).startswith('[') else str(source.get('symbols','')).split('|'))))
            if source is None or (source.get('symbol') != symbol and not shared_source_ok and not master_source_ok):
                raise ValueError('RECEIVED_STOCK_SOURCE_CONFLICT:' + symbol + ':' + str(source_id))
            selected_sources.append({**source,'symbol_scope_status':'UNKNOWN_RECEIVED_ROW_REFERENCE_ONLY'} if import_mode=='V3' and source.get('symbols')=='UNKNOWN' else source)
        errors = sorted(set(screen.get('errors', []) + gap_by_symbol.get(symbol, [])))
        screen['errors'] = errors
        if import_mode == 'V1':
            # Keep original P5 values in a clearly separated received record; never
            # expose their conflicted numbers as valid comparison/display fields.
            secondary = dict(received_record=screen, role=roles.get(symbol, 'NOT_SELECTED'),
                             source_date=date, target_date=target, recorded_at=receipt.get('at'),
                             status='CANNOT_CONFIRM', errors=errors,
                             reference_status='QUARANTINED' if errors else 'RECEIVED_REFERENCE_ONLY',
                             reference_fields={key: None if errors else screen.get(key) for key in (
                                 'p5_key_type', 'p5_key_date', 'p5_key_age', 'volume_to_current_MA5',
                                 'volume_to_prior_MA5', 'amount_yuan', 'plan_status', 'p5_risk_label',
                                 'mechanical_reversal_volume_amount_pass')},
                             source_ref=inputs['secondary_rows'], receipt=inputs['secondary_receipt'])
        else:
            secondary = copy.deepcopy(screen)
        fields = {key: row.get(key) for key in TEXT_FIELDS + META_FIELDS}
        fields.update(source_ids=source_ids, missing_inputs=json_list(row.get('missing_inputs', '[]'), 'MISSING_INPUTS'),
                      claims=claims[symbol], sources=selected_sources,
                      evidence_status='RECEIVED_RESEARCH_NOT_FULLY_VERIFIED', historical_PIT_safe=False,
                      specified_primary_page_checks=audits[symbol])
        if import_mode=='V3':
            fields.update(received_source_record=copy.deepcopy(row['_received_source_record']))
        if formula_context is not None:
            fields.update(source_bindings=(formula_source_bindings or {}).get(symbol, {}),
                          quarantined_sources=quarantined_sources,
                          formula_group_membership=(formula_stock_scope or {}).get(symbol))
        if import_mode == 'V2':
            fields.update(received_source_record=copy.deepcopy(row),
                          research_main_classification=classification[symbol],
                          research_as_of=row.get('research_as_of'),
                          research_tier_received=row.get('research_tier'),
                          user_resource_priority=classification[symbol].get('user_resource_priority'))
        shard = dict(schema_version='v4.a_share.company_materials.v1', symbol=symbol, data_date=date,
                     source_generation=generation, input_sha256=input_sha, numeric_manifest=numeric_ref,
                     source_refs=source_refs, received_at=received_at, received_fundamentals=fields, secondary_screen=secondary,
                     daily_performance=perf, received_batch_summary=summary,
                     **({'formula_group_scope': formula_scope_descriptor,
                         'formula_group_membership': (formula_stock_scope or {}).get(symbol)}
                        if formula_context is not None else {}),
                     business_reported=dict(value=row.get('business'), asof_date=row.get('research_as_of') or row.get('as_of'),
                                            evidence_status='RECEIVED_RESEARCH_NOT_FULLY_VERIFIED'),
                     # Narrative financial text is intentionally not parsed.
                     financials_reported={}, shareholders_reported={}, report_catalog=[], **FLAGS)
        items[symbol] = immutable('company_materials/' + date, symbol + '.json', shard)
    materials = dict(schema_version='v4.a_share.company_materials_index.v1', data_date=date,
                     numeric_manifest=numeric_ref, source_generation=generation, input_sha256=input_sha,
                     items=items, received_at=received_at, source_refs=source_refs,
                     **({'formula_group_scope': formula_scope_descriptor} if formula_context is not None else {}), **FLAGS)
    material_ref = immutable('company_materials/' + date, 'index.json', materials)
    new_index, new_event = copy.deepcopy(index), copy.deepcopy(event)
    idempotent_scope = False
    revised_scope = False
    if formula_context is not None:
        scoped = new_index.setdefault('company_materials_scoped', {})
        if not isinstance(scoped, dict):
            raise ValueError('RECEIVED_FORMULA_SCOPED_INDEX_INVALID')
        by_date = scoped.setdefault(date, {})
        if not isinstance(by_date, dict):
            raise ValueError('RECEIVED_FORMULA_SCOPED_DATE_INDEX_INVALID')
        previous = by_date.get(formula_context['roster_sha256'])
        if previous is not None:
            previous_materials = load(previous)
            if previous_materials == materials and previous.get('sha256') == material_ref.get('sha256'):
                material_ref = previous
                idempotent_scope = True
            elif scoped_revision is not None:
                _validate_revision_materials(previous, materials, immutable_files, scoped_revision)
                by_date[formula_context['roster_sha256']] = material_ref
                revised_scope = True
            else:
                raise ValueError('RECEIVED_FORMULA_SCOPED_KEY_CONTENT_CONFLICT')
        else:
            if scoped_revision is not None:
                raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_PRIOR_REF_CONFLICT')
            by_date[formula_context['roster_sha256']] = material_ref
        # Scoped records are additive. Preserve the ordinary pointer, versions,
        # and event byte-for-byte, including for same-day formula/official overlap.
    else:
        previous = new_index.setdefault('company_materials', {}).get(date)
        if previous is not None:
            history = new_index.setdefault('company_materials_versions', {}).setdefault(date, [])
            if previous not in history:
                history.append(previous)
        new_index['company_materials'][date] = material_ref
        # A late return only changes its company module. Latest numeric completion
        # remains byte-identical; host module versions provide invalidation hints.
        if date == latest_date:
            new_event.update(company_materials=material_ref)
            new_event['event_id'] = hashlib.sha256(canonical({k: v for k, v in new_event.items() if k != 'event_id'})).hexdigest()
    if revised_scope:
        before = copy.deepcopy(index)
        after = copy.deepcopy(new_index)
        before['company_materials_scoped'][date][formula_context['roster_sha256']] = '__REVISION_POINTER__'
        after['company_materials_scoped'][date][formula_context['roster_sha256']] = '__REVISION_POINTER__'
        if before != after or new_event != event:
            raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_INDEX_DELTA_CONFLICT')
    plan = dict(schema='V4_RECEIVED_RESEARCH_PUBLICATION_PLAN_V1',
                status=('PREPARED_SCOPED_PRESENTATION_REVISION' if revised_scope else
                        'IDEMPOTENT_SCOPED_BINDING' if idempotent_scope else 'PREPARED_NOT_PUBLISHED'),
                config=config_reference, publication_adapter=config['publication_adapter'],
                owner_publisher=config['owner_publisher'], shared_owner_lock=lock, target_root=str(root),
                stage=str(stage), expected_index=expected_index, expected_event=expected_event,
                immutable_files=immutable_files, staged_index=save(stage / 'index.json', new_index),
                staged_event=save(stage / 'event.json', new_event), completed=sorted(scope),
                numeric_manifest=numeric_ref, numeric_artifact=numeric['artifact'],
                company_materials_ref=material_ref, scoped_presentation_revision=scoped_revision,
                idempotent=idempotent_scope, summary=summary, **FLAGS)
    save(stage / 'PUBLICATION_PLAN.json', plan)
    return plan


def publish(plan_reference):
    """Root calls only after independent acceptance; original owner performs writes."""
    plan = load(plan_reference)
    if plan.get('schema') != 'V4_RECEIVED_RESEARCH_PUBLICATION_PLAN_V1' or not safe_flags(plan):
        raise ValueError('RECEIVED_PLAN_INVALID')
    config = load(plan['config'])
    for reference in config['inputs'].values():
        checked(reference)
    if 'formula_scope' in config:
        for key in ('roster_pointer', 'roster_artifact', 'input_zip'):
            checked(config['formula_scope'][key])
    if plan['publication_adapter'] != config['publication_adapter'] or plan['owner_publisher'] != config['owner_publisher']:
        raise ValueError('RECEIVED_PUBLISH_OWNER_CONFLICT')
    if plan.get('status') == 'IDEMPOTENT_SCOPED_BINDING':
        root = Path(plan['target_root'])
        if ref(root / 'index.json') != plan['expected_index'] or ref(root / 'events/latest.json') != plan['expected_event']:
            raise ValueError('RECEIVED_PLAN_CAS_DRIFT')
        return dict(status='ALREADY_PUBLISHED_IDENTICAL_SCOPE', company_materials_ref=plan.get('company_materials_ref'),
                    completed=plan.get('completed', []), **FLAGS)
    adapter = pinned_module(plan['publication_adapter'], 'existing_received_material_publisher')
    if plan.get('status') == 'PREPARED_SCOPED_PRESENTATION_REVISION':
        revision = plan.get('scoped_presentation_revision')
        if (not isinstance(revision, dict)
                or revision.get('schema') != FORMULA_PRESENTATION_REVISION_SCHEMA
                or revision.get('previous_ref') is None):
            raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_PLAN_INVALID')

        def refresh_scoped_revision():
            root = Path(plan['target_root'])
            if (ref(root / 'index.json') != plan['expected_index']
                    or ref(root / 'events/latest.json') != plan['expected_event']):
                raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_CAS_DRIFT')
            current = load(plan['expected_index'])
            date, roster_sha = revision['date'], revision['roster_sha256']
            current_ref = current.get('company_materials_scoped', {}).get(date, {}).get(roster_sha)
            if (current_ref != revision['previous_ref']
                    or current_ref.get('sha256') != revision['expected_previous_manifest_sha256']):
                raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_PRIOR_REF_DRIFT')
            checked(current_ref)
            if sha(current_ref['path']) != revision['expected_previous_manifest_sha256']:
                raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_PRIOR_REF_DRIFT')
            old_index, new_index = load(plan['expected_index']), load(plan['staged_index'])
            staged_ref = new_index.get('company_materials_scoped', {}).get(date, {}).get(roster_sha)
            if staged_ref != plan.get('company_materials_ref'):
                raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_STAGED_REF_CONFLICT')
            old_index['company_materials_scoped'][date][roster_sha] = '__REVISION_POINTER__'
            new_index['company_materials_scoped'][date][roster_sha] = '__REVISION_POINTER__'
            if (old_index != new_index
                    or load(plan['staged_event']) != load(plan['expected_event'])):
                raise ValueError('RECEIVED_FORMULA_PRESENTATION_REVISION_INDEX_DELTA_CONFLICT')
            return plan

        return adapter.publish(plan, refresh=refresh_scoped_revision)
    return adapter.publish(plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', type=Path)
    group.add_argument('--publish', type=Path)
    parser.add_argument('--sha256', required=True, help='Exact config or plan SHA')
    parser.add_argument('--stage', type=Path)
    parser.add_argument('--revise-scoped-presentation', action='store_true',
                        help='Allow a formula scoped presentation-only revision guarded by prior manifest SHA')
    parser.add_argument('--expected-scoped-manifest-sha256',
                        help='Exact current formula scoped manifest SHA required for the presentation revision')
    args = parser.parse_args()
    if args.prepare and not args.stage:
        parser.error('--prepare requires --stage')
    if args.revise_scoped_presentation != bool(args.expected_scoped_manifest_sha256):
        parser.error('--revise-scoped-presentation and --expected-scoped-manifest-sha256 must be supplied together')
    if args.publish and (args.revise_scoped_presentation or args.expected_scoped_manifest_sha256):
        parser.error('scoped presentation revision options apply only to --prepare')
    reference = dict(path=str((args.prepare or args.publish).resolve()), sha256=args.sha256)
    revision = ({'schema': FORMULA_PRESENTATION_REVISION_SCHEMA,
                 'expected_previous_manifest_sha256': args.expected_scoped_manifest_sha256}
                if args.revise_scoped_presentation else None)
    result = prepare(reference, args.stage, scoped_presentation_revision=revision) if args.prepare else publish(reference)
    print(json.dumps(dict(status=result['status'], completed=len(result['completed']),
                          stage=result.get('stage'), **FLAGS), ensure_ascii=False))


if __name__ == '__main__':
    main()
