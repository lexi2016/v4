"""Read-only frozen-input replay of the existing US mapping entry.

Only the CLI's explicitly isolated derivative directory is writable. This module
never constructs WorkbenchStore, adapters, clients, a scheduler or a live pointer.
"""
from __future__ import annotations

from datetime import datetime
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import tempfile
import time

from .us_mapping_replay_metrics import METRIC_POLICY, frozen_split

INVENTORY_SHA = '714314d500ae66f5f428ac08629ae92946d7a8506acd4cb87b1433ec2aafa6ed'
ENGINE_FILES = (
    'v4/manager_workbench/engines/us_mapping.py',
    'v4/manager_workbench/engines/us_mapping_consumption.py',
    'v4/manager_workbench/engines/strict_us_selection.py',
    'v4/manager_workbench/engines/us_mapping_policy.py',
    'v4/manager_workbench/engines/common.py',
    'v4/manager_workbench/engines/us_factor.py',
    'v4/manager_workbench/inputs/us_universe.py',
    'v4/manager_workbench/contracts.py',
    'v4/manager_workbench/inputs/strict_us_selection.py',
    'v4/manager_workbench/inputs/validation.py',
    'v4/manager_workbench/inputs/native.py',
    'v4/manager_workbench/inputs/source_bindings.py',
    'contracts/trading_calendar.py',
    'contracts/market_calendar_2026.json',
    'contracts/us_equity_calendar.py',
    'contracts/us_equity_calendar_2026.json',
    'infrastructure/owned_io.py',
    'upstreams/v3_shared_data/shared_data/hk_panel_audit.py',
)
REPLAY_FILES = (
    'v4/manager_workbench/us_mapping_replay.py',
    'v4/manager_workbench/us_mapping_replay_metrics.py',
    'ops/replay_us_mapping_selection.py',
)


class ReplayError(ValueError):
    pass


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _regular(path, root):
    path, root = Path(path).absolute(), Path(root).absolute()
    if '..' in path.parts or not path.is_relative_to(root) or any(p.is_symlink() for p in (path, *path.parents)):
        raise ReplayError('UNSAFE_FROZEN_PATH')
    if not path.is_file():
        raise ReplayError('FROZEN_FILE_MISSING')
    if any(part.upper().startswith('CURRENT') for part in path.relative_to(root).parts):
        raise ReplayError('CURRENT_RESOLUTION_FORBIDDEN')
    return path


def read_verified(ref, root, *, decode=True):
    path = _regular(ref['path'], root)
    if path.stat().st_size != ref.get('bytes', path.stat().st_size) or file_sha(path) != ref['sha256']:
        raise ReplayError('FROZEN_FILE_SHA_MISMATCH')
    if not decode:
        return None
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ReplayError('FROZEN_JSON_EXCEEDS_BOUND')
    with path.open() as stream:
        return json.load(stream)


def load_inventory(path, expected_sha=INVENTORY_SHA):
    path = Path(path).absolute()
    _regular(path, path.parent)
    if file_sha(path) != expected_sha:
        raise ReplayError('INVENTORY_SHA_MISMATCH')
    with path.open() as stream:
        d = json.load(stream)
    sessions = d['calendar']['sessions']
    if (d['schema'] != 'v4.us_hk.replay_inventory.v1' or not d['outcome_free']
            or len(sessions) != 60 or sessions != sorted(set(sessions))
            or len({r['run_id'] for r in d['runs']}) != len(d['runs'])
            or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', r['run_id']) for r in d['runs'])
            or d['split']['eligible_dates'] or d['split']['sealed_dates']):
        raise ReplayError('FROZEN_INVENTORY_CONTRACT_INVALID')
    if any(r['pit_evidence_complete'] for r in d['runs']):
        raise ReplayError('NEW_PIT_INPUT_REQUIRES_PRE_LABEL_FREEZE')
    return d


def temporal_cutoff(context):
    def parse(v):
        try:
            value = datetime.fromisoformat(v.replace('Z', '+00:00'))
            return value if value.tzinfo is not None else None
        except (ValueError, TypeError, AttributeError):
            return None
    source = parse(context.get('scope_refs', {}).get('source_cutoff'))
    execution = parse(context.get('cutoff'))
    return min(source, execution).isoformat() if source and execution else None


def input_batch_sha(batch):
    c = batch['context']
    return digest(dict(target_date=c['target_date'], market=c['market'], source_sessions=c['source_sessions'],
        scope_refs={k: v for k, v in c['scope_refs'].items()
                    if k not in {'run_id', 'mwb_run_id', 'timing_status', 'source_cutoff'}},
        lane=batch['lane'], records=batch['records'], refs=batch['evidence_refs'],
        scope=batch['scope_description'], coverage=batch['coverage'], gaps=batch['gaps'],
        universe_ref=batch['universe_ref']))


def _case_input_sha(row):
    return row.get('input_snapshot_sha256') or row.get('source_input_snapshot_sha256')


def load_case(inventory, row):
    if not (row['exact_saved_input_replayable'] or row.get('source_linked_us_input_replayable')):
        raise ReplayError('NO_FROZEN_US_INPUT')
    root = Path(inventory['state_root'])
    catalog = read_verified(row['catalog'], root)
    if any(catalog.get(k) != row[k] for k in ('run_id', 'input_sha256', 'product_sha256')):
        raise ReplayError('CATALOG_IDENTITY_MISMATCH')
    snapshot = read_verified(row['snapshot'], root)
    if snapshot.get('run_id') != row['run_id'] or snapshot.get('product_sha256') != row['product_sha256']:
        raise ReplayError('SAVED_PRODUCT_IDENTITY_MISMATCH')
    sha = _case_input_sha(row)
    ref = inventory['inputs'][sha]
    body = read_verified(ref, root)
    if Path(ref['path']).stem != sha or digest(body) != sha:
        raise ReplayError('INPUT_BODY_IDENTITY_MISMATCH')
    matches = [b for b in body['batches'] if b['lane'] == 'US_MAPPING']
    if len(matches) != 1 or body.get('authority') != 'ORIGINAL_OWNERS_ONLY' or body.get('derivative') is not True:
        raise ReplayError('SAVED_US_BATCH_INVALID')
    batch = matches[0]
    context = batch['context']
    if (input_batch_sha(batch) != batch['input_sha256']
            or context['market'] != 'HK_CONNECT' or context['target_date'] != row['target_date']):
        raise ReplayError('BATCH_IDENTITY_MISMATCH')
    for field in ('market', 'target_date', 'phase', 'cutoff', 'rules_version', 'source_sessions'):
        if body['context'].get(field) != context.get(field):
            raise ReplayError('INPUT_CONTEXT_MISMATCH')
    expected = next(b for b in ref['batches'] if b['lane'] == 'US_MAPPING')
    if batch['input_sha256'] != expected['input_sha256']:
        raise ReplayError('INVENTORIED_BATCH_SHA_MISMATCH')
    if row.get('source_linked_us_input_replayable'):
        source_id = row['freeze_context']['source_run_id']
        source = next((r for r in inventory['runs'] if r['run_id'] == source_id), None)
        if (not source or source.get('input_snapshot_sha256') != sha
                or snapshot.get('changes', {}).get('source_run_id') != source_id
                or source['us_batch_input_sha256'] != batch['input_sha256']):
            raise ReplayError('PREOPEN_SOURCE_LINK_MISMATCH')
        lanes = snapshot.get('lanes', [])
        lanes = list(lanes.values()) if isinstance(lanes, dict) else lanes
        lane = next((v for v in lanes if v['lane'] == 'US_MAPPING'), None)
        if not lane or lane['input_sha256'] != batch['input_sha256'] or lane['state'] == 'NOT_RUN':
            raise ReplayError('PREOPEN_SOURCE_BATCH_MISMATCH')
        if snapshot['context']['cutoff'] != row['snapshot_context']['cutoff']:
            raise ReplayError('PREOPEN_FREEZE_CUTOFF_MISMATCH')
    elif context['phase'] != row['phase'] or snapshot.get('changes', {}).get('input_snapshot_sha256') != sha:
        raise ReplayError('DIRECT_RUN_CONTEXT_MISMATCH')
    if temporal_cutoff(context) != row.get('effective_proof_cutoff'):
        raise ReplayError('ORIGINAL_SOURCE_CUTOFF_MISMATCH')
    before = original_dispositions(snapshot)
    return context, batch, before


def original_dispositions(snapshot):
    lanes = snapshot.get('lanes', [])
    lanes = list(lanes.values()) if isinstance(lanes, dict) else lanes
    us = next((v for v in lanes if v.get('lane') == 'US_MAPPING'), {})
    states = {}
    for item in us.get('rows', []):
        code = item.get('symbol')
        if isinstance(code, str) and code.startswith('HK.'):
            states.setdefault(code, set()).add(item.get('decision', 'MISSING'))
    return {'legacy_row_count': len(us.get('rows', [])), 'legacy_state': us.get('state'),
            'symbols': {s: sorted(v) for s, v in sorted(states.items())},
            'saved_plan_counts': snapshot.get('counts'), 'legacy_has_canonical_selection': bool(us.get('selection'))}


def selection_diff(before, selection):
    candidates = {v['symbol']: v for v in selection['candidates']}
    strict = {v['symbol']: v for v in selection['strict_decisions']}
    if (len(candidates) != len(selection['candidates']) or len(strict) != len(selection['strict_decisions'])
            or set(candidates) != set(strict)):
        raise ReplayError('CANONICAL_STOCK_FATES_INCOMPLETE')
    old = before['symbols']
    fates = []
    for code in sorted(set(old) | set(candidates)):
        candidate, decision = candidates.get(code), strict.get(code)
        fates.append({'symbol': code, 'before_legacy_decisions': old.get(code, []),
                      'after_research_state': candidate['research_state'] if candidate else None,
                      'after_decision': decision['decision'] if decision else 'NOT_CANDIDATE',
                      'strict': decision, 'candidate': candidate})
    return {'before_legacy_symbol_count': len(old), 'after_candidate_count': len(candidates),
            'before_legacy_symbols': sorted(old),
            'after_candidate_symbols': list(candidates),
            'candidate_original_order_top10': list(candidates)[:10],
            'added_symbols': sorted(set(candidates) - set(old)),
            'removed_symbols': sorted(set(old) - set(candidates)),
            'before_legacy_selected_symbols': sorted(s for s, v in old.items() if 'SELECTED' in v),
            'after_selected_symbols': [v['symbol'] for v in selection['strict_decisions'] if v['decision'] == 'SELECTED'],
            'semantic_comparison': 'LEGACY_DISPOSITIONS_VS_NEW_CANONICAL; NOT_EQUIVALENT_STRICT_CONTRACTS',
            'stock_fates': fates}


def source_manifest(source_root):
    root = Path(source_root)
    files = {p: file_sha(_regular(root / p, root)) for p in ENGINE_FILES + REPLAY_FILES}
    # PREOPEN projection changes affect only linked PREOPEN cases.
    source = _regular(root / 'v4/manager_workbench/service.py', root).read_text()
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'project_preopen_lane')
    preopen = {'v4/manager_workbench/service.py::project_preopen_lane': digest(ast.dump(function, include_attributes=False))}
    return {'engine_and_replay': files, 'preopen_projection': preopen}


def make_freeze(inventory, inventory_sha, source_root):
    split = frozen_split(inventory['calendar']['sessions'], inventory['split']['eligible_dates'])
    if split['sealed_dates'] != inventory['split']['sealed_dates']:
        raise ReplayError('SEALED_SPLIT_CHANGED')
    body = {'schema': 'v4.us_hk.replay_freeze.v1', 'inventory_sha256': inventory_sha,
            'code': source_manifest(source_root), 'python': platform.python_version(),
            'metric_policy': METRIC_POLICY, 'split': split,
            'coverage_sessions': inventory['calendar']['sessions'], 'actual_label_access': 'FORBIDDEN_ZERO_ELIGIBLE_DATES',
            'safety': {'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}}
    return {**body, 'freeze_sha256': digest(body)}


def case_fingerprint(freeze, row):
    return digest({'code': freeze['code']['engine_and_replay'],
        'preopen': freeze['code']['preopen_projection'] if row.get('source_linked_us_input_replayable') else None,
        'python': freeze['python'], 'metric_policy': freeze['metric_policy'], 'split': freeze['split'],
        'inventory_sha256': freeze['inventory_sha256'], 'case': row})


def output_root(path, inventory_path):
    root, boundary = Path(path).absolute(), Path(inventory_path).absolute().parent
    if '..' in root.parts or root == boundary or not root.is_relative_to(boundary) or any(p.is_symlink() for p in (root, *root.parents)):
        raise ReplayError('OUTPUT_NOT_ISOLATED_UNDER_INVENTORY_DIRECTORY')
    return root


def atomic_json(path, value):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ReplayError('UNSAFE_REPLAY_OUTPUT_PATH')
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(value)
    if path.exists():
        if path.read_bytes() != raw:
            raise ReplayError('IMMUTABLE_REPLAY_OUTPUT_COLLISION')
        return
    fd, name = tempfile.mkstemp(prefix='.replay-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Link is atomic and refuses to overwrite a concurrent completed writer.
        try:
            os.link(name, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ReplayError('IMMUTABLE_REPLAY_OUTPUT_COLLISION')
    finally:
        os.unlink(name)


def actual_engine(context, batch):
    from .engines.us_mapping import run_us_mapping
    return run_us_mapping(context, batch)


def actual_preopen(lane, *, cutoff):
    from .service import project_preopen_lane
    return project_preopen_lane(lane, cutoff=cutoff)


def _plain(value):
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else value


def completeness(selection):
    """Final REJECT may coexist with unknown gates; absent legacy flag is unknown."""
    pending = sum(g.get('state') == 'PENDING' for d in selection['strict_decisions'] for g in d.get('gates', []))
    complete = selection.get('evaluation_complete') is True and pending == 0
    return {'evaluation_complete': complete, 'declared_evaluation_complete': selection.get('evaluation_complete'),
            'pending_gate_count': pending, 'selected_zero_classification':
            'COMPLETE_STRICT_ZERO_PIT_STILL_UNVERIFIED' if complete else 'INCOMPLETE_OR_UNKNOWN_ZERO_NA',
            'daily_return': None, 'effect_status': 'NOT_EVALUABLE'}


def execute_case(inventory, row, freeze, *, engine=actual_engine, preopen=actual_preopen, deterministic=False):
    started = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    fingerprint = case_fingerprint(freeze, row)
    receipt = {'schema': 'v4.us_hk.replay_case.v1', 'fingerprint': fingerprint,
               'replay_id': 'replay-' + fingerprint[:24], 'source_run_id': row['run_id'],
               'target_date': row['target_date'], 'phase': row['phase'],
               'inventory_classification': row['classification'], 'input_snapshot_sha256': _case_input_sha(row),
               'effective_proof_cutoff': row.get('effective_proof_cutoff'),
               'pit_evaluable': False, 'effect_status': 'NOT_EVALUABLE',
               'missing_evidence': row['missing_evidence'], 'safety': freeze['safety']}
    if not (row['exact_saved_input_replayable'] or row.get('source_linked_us_input_replayable')):
        receipt.update(status='MISSING_REPLAY_INPUT', elapsed_seconds=0)
        return receipt
    try:
        context, batch, before = load_case(inventory, row)
        original_batch_sha = digest(batch)

        def run():
            value = _plain(engine(context, batch))
            if row.get('source_linked_us_input_replayable'):
                value = _plain(preopen(value, cutoff=row['snapshot_context']['cutoff']))
            selection = value.get('selection')
            if not isinstance(selection, dict) or selection.get('schema_version') != 'v4.us_hk.selection.v1':
                raise ReplayError('CANONICAL_SELECTION_NOT_EMITTED')
            if digest(batch) != original_batch_sha:
                raise ReplayError('ENGINE_MUTATED_FROZEN_BATCH')
            return selection

        selection = run()
        semantic_sha = digest(selection)
        receipt.update(engine_selection=selection, semantic_sha256=semantic_sha,
                       original=before, comparison=selection_diff(before, selection))
        if deterministic and digest(run()) != semantic_sha:
            raise ReplayError('SAME_INPUT_SEMANTICS_DIFFER')
        # This historical inventory has no qualified price proof. A selected result
        # would be material evidence of an engine/provenance failure, never alpha.
        if selection.get('counts', {}).get('selected') or any(v.get('decision') == 'SELECTED' for v in selection['strict_decisions']):
            raise ReplayError('SELECTED_WITHOUT_FROZEN_HISTORICAL_PRICE_PROOF')
        receipt.update(status='REPLAYED_ENGINEERING_ONLY', engine_selection=selection,
                       semantic_sha256=semantic_sha, deterministic_checked=deterministic,
                       original=before, comparison=selection_diff(before, selection),
                       original_context={k: context[k] for k in ('target_date', 'phase', 'cutoff', 'source_sessions')},
                       original_source_cutoff=context['scope_refs'].get('source_cutoff'),
                       completeness=completeness(selection))
    except Exception as exc:
        receipt.update(status='RUNTIME_FAILURE', error={'type': type(exc).__name__, 'message': str(exc)[:800]})
    receipt['elapsed_seconds'] = round(time.monotonic() - started, 6)
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    receipt['resources'] = {'peak_rss_bytes_macos': usage_after.ru_maxrss,
        'user_seconds': usage_after.ru_utime - usage_before.ru_utime,
        'system_seconds': usage_after.ru_stime - usage_before.ru_stime,
        'input_blocks': usage_after.ru_inblock - usage_before.ru_inblock,
        'output_blocks': usage_after.ru_oublock - usage_before.ru_oublock}
    return receipt


def run_to_checkpoint(inventory, row, freeze, root, *, deterministic=False):
    fingerprint = case_fingerprint(freeze, row)
    path = Path(root) / 'cases' / row['target_date'] / (row['run_id'] + '-' + fingerprint + '.json')
    if path.exists():
        _regular(path, root)
        if row['exact_saved_input_replayable'] or row.get('source_linked_us_input_replayable'):
            for ref in (row['catalog'], row['snapshot'], inventory['inputs'][_case_input_sha(row)]):
                read_verified(ref, inventory['state_root'], decode=False)
        with path.open() as stream:
            saved = json.load(stream)
        unsigned = {k: v for k, v in saved.items() if k != 'receipt_sha256'}
        if saved.get('fingerprint') != fingerprint or saved.get('receipt_sha256') != digest(unsigned):
            raise ReplayError('CHECKPOINT_IDENTITY_MISMATCH')
        if saved.get('engine_selection') and digest(saved['engine_selection']) != saved.get('semantic_sha256'):
            raise ReplayError('CHECKPOINT_SEMANTIC_SHA_MISMATCH')
        if deterministic and saved.get('status') == 'REPLAYED_ENGINEERING_ONLY' and not saved.get('deterministic_checked'):
            raise ReplayError('CHECKPOINT_DOES_NOT_COVER_DETERMINISM')
        return {'path': str(path), 'sha256': file_sha(path), 'reused': True,
                'source_run_id': row['run_id'], 'status': saved['status']}
    receipt = execute_case(inventory, row, freeze, deterministic=deterministic)
    receipt['receipt_sha256'] = digest(receipt)
    atomic_json(path, receipt)
    return {'path': str(path), 'sha256': file_sha(path), 'reused': False,
            'source_run_id': row['run_id'], 'status': receipt['status']}


def aggregate(inventory, freeze, references):
    cases = {}
    for ref in references:
        if file_sha(ref['path']) != ref['sha256']:
            raise ReplayError('CASE_RECEIPT_CHANGED')
        with Path(ref['path']).open() as stream:
            case = json.load(stream)
        cases[case['source_run_id']] = case
    days = []
    for original in inventory['days']:
        rows = [cases[r] for r in original['saved_run_ids'] if r in cases]
        # Multiple runs are distinct versions; never cherry-pick/average their names.
        days.append({**original, 'replay_statuses': {r['source_run_id']: r['status'] for r in rows},
                     'daily_return': None, 'effect_status': 'NOT_EVALUABLE',
                     'run_versions_kept_separate': True})
    reason_counts = {}
    for case in cases.values():
        for reason in case['missing_evidence']:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {'schema': 'v4.us_hk.replay_aggregate.v1', 'freeze_sha256': freeze['freeze_sha256'],
            'coverage_denominator': 60, 'inventory_saved_runs': len(inventory['runs']),
            'processed_runs': len(cases), 'status_counts': {s: sum(c['status'] == s for c in cases.values()) for s in sorted({c['status'] for c in cases.values()})},
            'pit_evaluable_dates': [], 'sealed_dates': [], 'labels_read': 0,
            'effect_status': 'NOT_EVALUABLE', 'curve_segments': [], 'gross_metrics': None,
            'not_evaluable_reason_counts': reason_counts, 'days': days, 'case_receipts': references,
            'safety': freeze['safety']}
