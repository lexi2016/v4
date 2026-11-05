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
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from collections import Counter

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
        return copy.deepcopy(value), 'V1'
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


def prepare(config_reference, stage):
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
            or index.get('latest_date') != date or index.get('latest') != numeric_ref
            or event.get('data_date') != date or event.get('source_generation') != generation
            or event.get('input_sha256') != input_sha or event.get('manifest') != numeric_ref
            or event.get('artifact') != numeric['artifact'] or not safe_flags(event)):
        raise ValueError('RECEIVED_NUMERIC_OR_EVENT_IDENTITY_CONFLICT')
    codes = [row['symbol'] for row in product['rows']]
    scope = set(codes)
    if len(codes) != len(scope) or len(scope) != config['scope_count']:
        raise ValueError('RECEIVED_NUMERIC_EXACT_SCOPE_CONFLICT')
    received = exact_rows(csv_rows(inputs['fundamentals']), scope, 'FUNDAMENTALS')
    source_manifest = load(inputs['input_manifest'])
    return_manifest = load(inputs['return_manifest'])
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
    else:
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
    if import_mode == 'V1':
        sources_by_id = {}
        source_rows_for_binding = csv_rows(inputs['sources'])
    for row in source_rows_for_binding:
        key = row['source_id']
        if key in sources_by_id and row != sources_by_id[key]:
            raise ValueError('RECEIVED_SOURCE_ID_CONFLICT:' + key)
        sources_by_id[key] = row
    claims = {symbol: [] for symbol in scope}
    for row in csv_rows(inputs['claims']):
        if row.get('symbol') in scope:
            claims[row['symbol']].append(row)
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
    summary = dict(source_date=date, target_date=target, generation=generation, input_sha256=input_sha,
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
    gap_by_symbol = ({row['symbol']: row['errors'] for row in receipt.get('quote_or_feature_gaps', [])}
                     if receipt else {})
    immutable_files = {}

    def immutable(folder, name, value):
        target_path = root / folder / hashlib.sha256(canonical(value)).hexdigest() / name
        staged_ref = save(stage / 'immutable' / target_path.relative_to(root), value)
        immutable_files[str(target_path)] = staged_ref
        return dict(path=str(target_path), sha256=staged_ref['sha256'])

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
        elif (screen.get('source_date') != date or screen.get('target_date') != target
                or screen.get('status') != 'NOT_RUN_FOR_20261105_GENERATION'
                or screen.get('received_record', {}).get('full_chain_status') != 'NOT_RUN_FOR_20261105_GENERATION'
                or screen.get('reference_status') != 'NOT_RUN'
                or any(value is not None for value in screen.get('reference_fields', {}).values())):
            raise ValueError('RECEIVED_V2_SECONDARY_IDENTITY_CONFLICT:' + symbol)
        if any(str(row.get(k)).lower() != str(v).lower() for k, v in FLAGS.items()):
            raise ValueError('RECEIVED_STOCK_SAFETY_CONFLICT:' + symbol)
        source_ids = json_list(row.get('source_ids', '[]'), 'SOURCE_IDS')
        selected_sources = []
        for source_id in source_ids:
            source = sources_by_id.get(source_id)
            shared_source_ok = (import_mode == 'V2' and source_id in V2_SHARED_SOURCES
                                and source is not None and not (source.get('symbol') or '').strip()
                                and symbol in shared_scopes.get(source_id, set()))
            if source is None or (source.get('symbol') != symbol and not shared_source_ok):
                raise ValueError('RECEIVED_STOCK_SOURCE_CONFLICT:' + symbol + ':' + str(source_id))
            selected_sources.append(source)
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
        if import_mode == 'V2':
            fields.update(received_source_record=copy.deepcopy(row),
                          research_main_classification=classification[symbol],
                          research_as_of=row.get('research_as_of'),
                          research_tier_received=row.get('research_tier'),
                          user_resource_priority=classification[symbol].get('user_resource_priority'))
        shard = dict(schema_version='v4.a_share.company_materials.v1', symbol=symbol, data_date=date,
                     source_generation=generation, input_sha256=input_sha, numeric_manifest=numeric_ref,
                     source_refs=inputs, received_fundamentals=fields, secondary_screen=secondary,
                     daily_performance=perf, received_batch_summary=summary,
                     business_reported=dict(value=row.get('business'), asof_date=row.get('research_as_of') or row.get('as_of'),
                                            evidence_status='RECEIVED_RESEARCH_NOT_FULLY_VERIFIED'),
                     # Narrative financial text is intentionally not parsed.
                     financials_reported={}, shareholders_reported={}, report_catalog=[], **FLAGS)
        items[symbol] = immutable('company_materials/' + date, symbol + '.json', shard)
    materials = dict(schema_version='v4.a_share.company_materials_index.v1', data_date=date,
                     numeric_manifest=numeric_ref, source_generation=generation, input_sha256=input_sha,
                     items=items, source_refs=inputs, **FLAGS)
    material_ref = immutable('company_materials/' + date, 'index.json', materials)
    new_index, new_event = copy.deepcopy(index), copy.deepcopy(event)
    new_index.setdefault('company_materials', {})[date] = material_ref
    new_event.update(company_materials=material_ref)
    new_event['event_id'] = hashlib.sha256(canonical({k: v for k, v in new_event.items() if k != 'event_id'})).hexdigest()
    plan = dict(schema='V4_RECEIVED_RESEARCH_PUBLICATION_PLAN_V1', status='PREPARED_NOT_PUBLISHED',
                config=config_reference, publication_adapter=config['publication_adapter'],
                owner_publisher=config['owner_publisher'], shared_owner_lock=lock, target_root=str(root),
                stage=str(stage), expected_index=expected_index, expected_event=expected_event,
                immutable_files=immutable_files, staged_index=save(stage / 'index.json', new_index),
                staged_event=save(stage / 'event.json', new_event), completed=sorted(scope),
                numeric_manifest=numeric_ref, numeric_artifact=numeric['artifact'],
                summary=summary, **FLAGS)
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
    if plan['publication_adapter'] != config['publication_adapter'] or plan['owner_publisher'] != config['owner_publisher']:
        raise ValueError('RECEIVED_PUBLISH_OWNER_CONFLICT')
    adapter = pinned_module(plan['publication_adapter'], 'existing_received_material_publisher')
    return adapter.publish(plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', type=Path)
    group.add_argument('--publish', type=Path)
    parser.add_argument('--sha256', required=True, help='Exact config or plan SHA')
    parser.add_argument('--stage', type=Path)
    args = parser.parse_args()
    if args.prepare and not args.stage:
        parser.error('--prepare requires --stage')
    reference = dict(path=str((args.prepare or args.publish).resolve()), sha256=args.sha256)
    result = prepare(reference, args.stage) if args.prepare else publish(reference)
    print(json.dumps(dict(status=result['status'], completed=len(result['completed']),
                          stage=result.get('stage'), **FLAGS), ensure_ascii=False))


if __name__ == '__main__':
    main()
