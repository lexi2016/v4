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
import os
from pathlib import Path
import re
import stat
import sys
from collections import Counter

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
TEXT_FIELDS = ('business', 'profit_driver', 'growth_quality', 'cash_debt_quality',
               'valuation_method', 'valuation_date', 'valuation_assessment',
               'catalyst', 'key_risks', 'counter_evidence', 'evidence_summary', 'research_notes')
META_FIELDS = ('screened_name', 'verified_name', 'as_of', 'latest_financial_period',
               'research_tier', 'evidence_quality', 'status', 'risk_review_scope')


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


def prepare(config_reference, stage):
    config = load(config_reference)
    if config.get('schema') != 'V4_RECEIVED_RESEARCH_IMPORT_V1' or not safe_flags(config):
        raise ValueError('RECEIVED_CONFIG_INVALID')
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
    screens = exact_rows(load(inputs['secondary_rows']), scope, 'SECONDARY')
    performance_payload = load(inputs['daily_performance'])
    if (performance_payload.get('source_date') != date or performance_payload.get('target_date') != target
            or performance_payload.get('source_generation') != generation
            or performance_payload.get('numeric_manifest_sha256') != numeric_ref['sha256']
            or not safe_flags(performance_payload)):
        raise ValueError('RECEIVED_PERFORMANCE_IDENTITY_CONFLICT')
    performance = exact_rows(performance_payload['rows'], scope, 'PERFORMANCE')
    source_manifest = load(inputs['input_manifest'])
    return_manifest = load(inputs['return_manifest'])
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
    sources_by_id = {}
    for row in csv_rows(inputs['sources']):
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
    selected = receipt.get('selected_watchlist_by_theme', {})
    roles = {}
    themes = []
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
                   scope_count=len(scope), research_as_of=return_manifest.get('research_as_of'),
                   secondary_recorded_at=receipt.get('at'), themes=themes,
                   technical_observe_count=sum(role == 'technical_observe' for role in roles.values()),
                   wait_for_trigger_count=sum(role == 'wait_for_trigger' for role in roles.values()),
                   original_producer_status_counts=dict(Counter(row.get('status') for row in received.values())),
                   specified_primary_page_check_count=sum(bool(value) for value in audits.values()),
                   strict_full_chain_certified_count=0, **FLAGS)
    gap_by_symbol = {row['symbol']: row['errors'] for row in receipt.get('quote_or_feature_gaps', [])}
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
                or screen.get('source_date') != date or screen.get('target_date') != target
                or screen.get('v4_generation') != generation or screen.get('full_chain_status') != 'CANNOT_CONFIRM'
                or perf.get('source_date') != date or perf.get('target_date') != target
                or perf.get('source_generation') != generation
                or perf.get('numeric_manifest_sha256') != numeric_ref['sha256']
                or perf.get('current_target_day_return_pct') is not None
                or perf.get('current_target_day_performance_status') != 'NOT_MATERIALIZED_NOT_READ'
                or not safe_flags(perf)):
            raise ValueError('RECEIVED_STOCK_IDENTITY_CONFLICT:' + symbol)
        if any(str(row.get(k)).lower() != str(v).lower() for k, v in FLAGS.items()):
            raise ValueError('RECEIVED_STOCK_SAFETY_CONFLICT:' + symbol)
        source_ids = json_list(row.get('source_ids', '[]'), 'SOURCE_IDS')
        selected_sources = []
        for source_id in source_ids:
            source = sources_by_id.get(source_id)
            if source is None or source.get('symbol') != symbol:
                raise ValueError('RECEIVED_STOCK_SOURCE_CONFLICT:' + symbol + ':' + str(source_id))
            selected_sources.append(source)
        errors = sorted(set(screen.get('errors', []) + gap_by_symbol.get(symbol, [])))
        screen['errors'] = errors
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
        fields = {key: row.get(key) for key in TEXT_FIELDS + META_FIELDS}
        fields.update(source_ids=source_ids, missing_inputs=json_list(row.get('missing_inputs', '[]'), 'MISSING_INPUTS'),
                      claims=claims[symbol], sources=selected_sources,
                      evidence_status='RECEIVED_RESEARCH_NOT_FULLY_VERIFIED', historical_PIT_safe=False,
                      specified_primary_page_checks=audits[symbol])
        shard = dict(schema_version='v4.a_share.company_materials.v1', symbol=symbol, data_date=date,
                     source_generation=generation, input_sha256=input_sha, numeric_manifest=numeric_ref,
                     source_refs=inputs, received_fundamentals=fields, secondary_screen=secondary,
                     daily_performance=perf, received_batch_summary=summary,
                     business_reported=dict(value=row.get('business'), asof_date=row.get('as_of'),
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
