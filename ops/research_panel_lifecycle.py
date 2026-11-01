"""Bounded 20261030 lifecycle source binding for the existing QFQ owner.

This verifies source evidence and previously computed formula frames. It does
not admit securities, publish a panel, or infer a complete market universe.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from ops.research_panel_factor_cache import QfqGateError

_FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
_READERS = {}


def _reader(path: Path, digest: str):
    """Keep the reviewed reader's own identity/stat caches for all 31 stocks."""
    from ops.research_panel_qfq import sha
    if sha(path) != digest:
        raise QfqGateError('LIFECYCLE_READER_SHA_DRIFT')
    key = (str(path), digest)
    if key not in _READERS:
        spec = importlib.util.spec_from_file_location('qfq_lifecycle_admission_reader', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _READERS[key] = module
    return _READERS[key]


def _safe(value):
    return (isinstance(value, dict) and value.get('historical_PIT') is False
            and all(value.get(k) is v for k, v in _FLAGS.items()))


def _item(entry: dict, target: int) -> dict:
    code = entry['symbol']; start = entry['listing_date']
    return dict(history_start_date=start, history_end_date=target, compute_start_date=start,
        required_output_start_date=start, publish_roles=['selector', 'backtest'],
        event_coverage_complete=True, events=entry['adjustment_events'], raw_files=entry['raw_files'],
        accepted_evidence=[entry['listing_binding'], entry['history_metadata'],
                           entry['row_lineage_receipt'], entry['adjustment_binding']],
        raw_resolution='ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2',
        source_method='TDX_OFFICIAL_TERMS_BOUND_CONVERSION' if code.endswith('.BJ') else 'FUTU_GET_REHAB_AFFINE')


def _original_kernel_unchanged(old: Path, current: Path) -> None:
    def functions(path):
        return {node.name: node for node in ast.parse(path.read_text()).body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    left, right = functions(old), functions(current)
    for name in ('_load', 'authorities', 'resolved_raw_history', 'apply_adjustments', 'append_user_formula_v1'):
        if ast.dump(left[name], include_attributes=False) != ast.dump(right[name], include_attributes=False):
            raise QfqGateError('LIFECYCLE_FORMULA_KERNEL_CHANGED:' + name)
    before, after = left['rebuild_symbol'], right['rebuild_symbol']
    last = after.body[-1]
    if (not isinstance(last, ast.Return) or not isinstance(last.value, ast.Call)
            or not isinstance(last.value.func, ast.Name) or last.value.func.id != 'append_kb_signals'
            or len(last.value.args) != 1):
        raise QfqGateError('LIFECYCLE_FORMULA_WRAPPER_CHANGED')
    last.value = last.value.args[0]
    if ast.dump(before, include_attributes=False) != ast.dump(after, include_attributes=False):
        raise QfqGateError('LIFECYCLE_FORMULA_FRAME_KERNEL_CHANGED')


def _verify_lineage(reader, entry: dict, code: str, dates: list[int]) -> None:
    lineage = reader._lifecycle_json(entry['row_lineage_receipt'])
    rows = lineage.get('lineage'); target = str(dates[-1])
    if (lineage.get('symbol') != code or str(lineage.get('target_date', lineage.get('last_date'))) != target
            or not isinstance(rows, list) or len(rows) != len(dates)):
        raise QfqGateError('LIFECYCLE_LINEAGE_SCOPE_CONFLICT:' + code)
    if lineage.get('status') != 'RAW_CANDIDATE_SOURCE_GATES_PASS':
        guard = reader._lifecycle_json(entry['ipo_guard_receipt']); row = guard.get('candidate_row', {})
        reasons = guard.get('ipo_evidence', {}).get('records', [])
        if (lineage.get('status') != 'CANNOT_CONFIRM' or guard.get('schema') != 'A_SYNC_301686_ISOLATED_OWNER_CANARY_V1'
                or guard.get('candidate_sync_status') != 'PASS' or guard.get('dry_run') is not True
                or guard.get('seed_configured') is not False or guard.get('old_reason') != 'CROSS_DAY_CLOSE_RATIO'
                or guard.get('source_file_unchanged') is not True or not reader._lifecycle_safety(guard)
                or row.get('symbol') != code[:6] or row.get('market') != {'SZ':0, 'SH':1, 'BJ':2}[code[-2:]]
                or row.get('classification') != 'ACCEPTED' or row.get('target_date_ready') is not True
                or row.get('source_sha256_after') != entry['whole_row_source_sha256']
                or not any(item.get('symbol') == code and item.get('status') == 'EXPLAINED_FIRST_IPO_FIVE_SESSIONS'
                           for item in reasons)):
            raise QfqGateError('LIFECYCLE_IPO_GUARD_UNBOUND:' + code)
    selected = {}
    for reference in entry['raw_files']:
        path = reader._lifecycle_ref(reference); raw = path.read_bytes(); reader._lifecycle_ref(reference)
        if not raw or len(raw) % 32:
            raise QfqGateError('LIFECYCLE_RAW_FILE_SHAPE:' + code)
        for offset in range(0, len(raw), 32):
            chunk = raw[offset:offset + 32]; day = reader._LIFECYCLE_DAY.unpack(chunk)[0]
            if day in selected:
                raise QfqGateError('LIFECYCLE_RAW_DUPLICATE_DATE:' + code)
            selected[day] = chunk
    if sorted(selected) != dates:
        raise QfqGateError('LIFECYCLE_RAW_DATE_SCOPE:' + code)
    for day, row in zip(dates, rows):
        if (row.get('date') != day or row.get('raw32_sha256') != hashlib.sha256(selected[day]).hexdigest()
                or reader._lifecycle_original_bar(row, code, day) != selected[day]):
            raise QfqGateError('LIFECYCLE_WHOLE_ROW_SOURCE_CONFLICT:' + code + ':' + str(day))
    if hashlib.sha256(b''.join(selected[day] for day in dates)).hexdigest() != entry['whole_row_source_sha256']:
        raise QfqGateError('LIFECYCLE_RAW_ASSEMBLED_IDENTITY:' + code)


def verify_snapshot(snapshot: dict, target: int) -> dict:
    """Require unchanged baseline and verified raw/listing/adjustment/frame inputs."""
    from ops import research_panel_qfq as q
    def load(reference, owner):
        return json.loads(q._source(reference, owner=owner).read_text())
    contract_path = Path(__file__).resolve().parents[1] / 'contracts/a_share_lifecycle_admission_v1.json'
    contract = json.loads(contract_path.read_text()); additions_ref = snapshot.get('lifecycle_additions')
    descriptor = load(additions_ref, 'lifecycle additions'); source = load(descriptor['source_descriptor'], 'lifecycle source descriptor')
    if (contract.get('schema') != 'a_share_lifecycle_admission_v1' or contract.get('target_date') != target
            or contract.get('scope') != 'ISOLATED_CANDIDATE_ONLY' or not _safe(contract)
            or descriptor.get('schema') != 'qfq_lifecycle_additions_v1'
            or descriptor.get('status') != 'SOURCE_BOUND_PREPARED_NOT_ADMITTED'
            or descriptor.get('asof_date') != target or not _safe(descriptor)
            or descriptor.get('baseline_generation_id') != contract['baseline_generation_id']
            or descriptor['baseline_snapshot'].get('sha256') != contract['baseline_snapshot_sha256']
            or {k:v.get('sha256') for k,v in descriptor['baseline_roles'].items()} != contract['baseline_roles_sha256']
            or descriptor['source_descriptor'].get('sha256') != contract['source_descriptor_sha256']
            or descriptor['reader_config'].get('sha256') != contract['reader_config_sha256']
            or descriptor['reader_review'].get('sha256') != contract['reader_review_sha256']
            or descriptor['lifecycle_contract'].get('sha256') != q.sha(contract_path)
            or source.get('schema') != 'a_share_lifecycle_addition_source_descriptor_draft.v1'
            or source.get('status') != contract['source_status'] or source.get('target_date') != target
            or source.get('symbol_count') != contract['source_symbol_count']
            or source.get('row_count') != contract['source_row_count'] or not _safe(source)):
        raise QfqGateError('LIFECYCLE_DESCRIPTOR_IDENTITY_CONFLICT')
    q._source(descriptor['lifecycle_contract'], owner='lifecycle contract')
    baseline = load(descriptor['baseline_snapshot'], 'lifecycle old snapshot')
    if q.canonical_sha(baseline) != contract['baseline_input_sha256']:
        raise QfqGateError('LIFECYCLE_BASELINE_INPUT_CONFLICT')
    config = load(descriptor['reader_config'], 'lifecycle reader configuration'); reader_ref = config['admission_helper']
    if reader_ref.get('sha256') != contract['reader_sha256']:
        raise QfqGateError('LIFECYCLE_READER_IDENTITY_CONFLICT')
    review = load(descriptor['reader_review'], 'lifecycle independent reader review')
    if (review.get('verdict') != 'REVIEWED/PASS' or review.get('behavior_verified') is not True
            or review.get('evidence_class') != 'CONTROLLER_TRANSCRIPTION_OF_AUTHENTICATED_COLLABORATION_FINAL'
            or not review.get('reviewer_id') or review.get('recorded_by') != '/root'
            or review.get('reader', {}).get('path') != reader_ref.get('path')
            or review.get('reader', {}).get('sha256') != reader_ref.get('sha256')
            or any(review.get('findings', {}).get(k) != 0 for k in ('P0', 'P1', 'P2'))):
        raise QfqGateError('LIFECYCLE_READER_REVIEW_CONFLICT')
    q._source(review['reviewed_handoff'], owner='lifecycle reviewed handoff')
    q._source(review['tests'], owner='lifecycle reviewed tests')
    reader_path = q._source(reader_ref, owner='lifecycle admission reader'); reader = _reader(reader_path, reader_ref['sha256'])
    sync = reader._lifecycle_json(descriptor['original_sync_receipt'])
    markets = {0:'SZ', 1:'SH', 2:'BJ'}
    def sync_codes(rows):
        if not isinstance(rows, list) or not rows:
            raise QfqGateError('LIFECYCLE_ORIGINAL_SYNC_TARGET_INVALID')
        result = set()
        for row in rows:
            code, market = row.get('symbol'), row.get('market')
            if not isinstance(code, str) or len(code) != 6 or not code.isdigit() or market not in markets:
                raise QfqGateError('LIFECYCLE_ORIGINAL_SYNC_TARGET_INVALID')
            result.add(code + '.' + markets[market])
        return result
    original = sync_codes(sync.get('target_keys'))
    if (str(sync.get('target_date')) != str(target) or sync_codes(sync.get('symbol_reconciliation')) != original
            or baseline.get('original_target_codes') != sorted(original)
            or source.get('original_sync_receipt') != descriptor['original_sync_receipt']):
        raise QfqGateError('LIFECYCLE_ORIGINAL_SYNC_RECONCILIATION_CONFLICT')
    entries = source.get('symbols'); bindings = descriptor.get('symbols')
    if not isinstance(entries, dict) or not isinstance(bindings, dict) or set(entries) != set(bindings) or len(entries) != 31:
        raise QfqGateError('LIFECYCLE_ADDITION_SET_CONFLICT')
    codes = set(entries); prior = set(baseline.get('symbols', {})) | original
    for key in ('quarantine_symbols', 'original_quarantine_eligible', 'retained_history_codes', 'legacy_preservation_codes'):
        prior.update(baseline.get(key) or ())
    if codes & prior or any(not q.CODE.fullmatch(code) for code in codes):
        raise QfqGateError('LIFECYCLE_ADDITION_COLLIDES_WITH_BASELINE')
    changed = {'symbols', 'source_files', 'lifecycle_additions', 'lifecycle_addition_codes', 'effective_target_codes'}
    if ({k:v for k,v in snapshot.items() if k not in changed} != {k:v for k,v in baseline.items() if k not in changed}
            or snapshot.get('original_target_codes') != baseline['original_target_codes']
            or snapshot.get('lifecycle_addition_codes') != sorted(codes)
            or snapshot.get('effective_target_codes') != sorted(original | codes)
            or set(snapshot.get('symbols', {})) != set(baseline['symbols']) | codes
            or any(snapshot['symbols'].get(code) != value for code,value in baseline['symbols'].items())
            or snapshot.get('source_files', [])[:len(baseline['source_files'])] != baseline['source_files']):
        raise QfqGateError('LIFECYCLE_BASELINE_SNAPSHOT_CHANGED')
    if any(snapshot['symbols'][code] != _item(entries[code], target) for code in codes):
        raise QfqGateError('LIFECYCLE_SYMBOL_BINDING_CONFLICT')
    required = [additions_ref, descriptor['source_descriptor'], descriptor['reader_config'], descriptor['reader_review'], reader_ref,
                descriptor['lifecycle_contract'], source['market_calendar'], source['frame_index']]
    for entry in entries.values():
        required.extend((entry['listing_binding'], entry['history_metadata'], entry['row_lineage_receipt'],
                         entry['listing_pdf'], entry['formula_frame'], entry['adjustment_binding']))
        if entry.get('ipo_guard_receipt'):
            required.append(entry['ipo_guard_receipt'])
    if any(item not in snapshot['source_files'] for item in required):
        raise QfqGateError('LIFECYCLE_SOURCE_CLOSURE_INCOMPLETE')
    calendar = load(source['market_calendar'], 'lifecycle market calendar')
    if (calendar.get('schema') != 'D222_PER_EXCHANGE_SOURCE_CALENDAR_V1'
            or calendar.get('source_generation') != contract['baseline_generation_id']
            or calendar.get('input_sha256') != contract['baseline_input_sha256']
            or calendar.get('panel_sha256') != contract['baseline_roles_sha256']['selector']
            or calendar.get('asof_date') != target or not _safe(calendar)):
        raise QfqGateError('LIFECYCLE_CALENDAR_BINDING_CONFLICT')
    index = load(source['frame_index'], 'lifecycle formula frame index')
    if source['frame_index'].get('sha256') != contract['formula_frame_index_sha256']:
        raise QfqGateError('LIFECYCLE_FRAME_INDEX_IDENTITY_CONFLICT')
    indexed = {row['symbol']:row for row in index['items']}
    if (index.get('status') != 'ISOLATED_FRAMES_NOT_PANEL_OR_PRODUCT' or set(indexed) != codes
            or sum(row.get('rows', 0) for row in indexed.values()) != contract['source_row_count']):
        raise QfqGateError('LIFECYCLE_FRAME_INDEX_COVERAGE_CONFLICT')
    example = indexed[sorted(codes)[0]]['inputs']; old_q = q._source(example['qfq'], owner='lifecycle original qfq')
    driver_path = q._source(example['driver'], owner='lifecycle original driver')
    formula_path = q._source(example['formula'], owner='lifecycle original formula')
    _original_kernel_unchanged(old_q, Path(q.__file__).resolve()); driver, _ = q.authorities(driver_path, formula_path)
    frame_refs = {}; total = 0
    try:
        for code in sorted(codes):
            entry = entries[code]; dates = entry['dates']; item = snapshot['symbols'][code]; row = indexed[code]
            if (entry.get('symbol') != code or entry.get('target_date') != target or not isinstance(dates, list)
                    or not dates or dates != sorted(set(dates)) or any(type(day) is not int for day in dates)
                    or entry.get('listing_date') != dates[0] or dates[-1] != target or entry.get('history_count') != len(dates)
                    or not set(dates).issubset(set(calendar.get('dates', {}).get(code[-2:], [])))
                    or bindings[code].get('source_entry_sha256') != q.canonical_sha(entry)
                    or set(bindings[code].get('roles', [])) != {'selector', 'backtest'}
                    or row.get('frame') != entry['formula_frame'] or row.get('rows') != len(dates)
                    or any(row.get('inputs', {}).get(key) != example[key] for key in ('qfq', 'driver', 'formula'))):
                raise QfqGateError('LIFECYCLE_SYMBOL_SOURCE_CONFLICT:' + code)
            reader._lifecycle_listing(entry, code, dates[0])
            reader._lifecycle_adjustment(entry, code, item, str(target), dates[0])
            _verify_lineage(reader, entry, code, dates)
            raw = q.resolved_raw_history(code, item, target, driver); adjusted = q.apply_adjustments(raw, item['events'], target)
            frame = pq.read_table(q._source(entry['formula_frame'], owner='lifecycle original formula frame')).to_pandas()
            if frame.trade_date.astype(int).tolist() != dates or adjusted.trade_date.astype(int).tolist() != dates:
                raise QfqGateError('LIFECYCLE_FRAME_DATE_CONFLICT:' + code)
            for name in ('open', 'high', 'low', 'close', 'vol', 'volume', 'amount'):
                if not np.array_equal(frame[name].to_numpy(dtype=float), adjusted[name].to_numpy(dtype=float), equal_nan=True):
                    raise QfqGateError('LIFECYCLE_FRAME_BAR_CONFLICT:' + code + ':' + name)
            frame_refs[code] = entry['formula_frame']; total += len(dates)
    except (KeyError, TypeError, ValueError, OSError, IndexError) as exc:
        raise QfqGateError('LIFECYCLE_SOURCE_VERIFICATION_FAILED:' + str(exc)) from exc
    if total != contract['source_row_count']:
        raise QfqGateError('LIFECYCLE_SOURCE_ROW_COUNT_CONFLICT')
    return dict(descriptor=descriptor, descriptor_ref=additions_ref, source=source, baseline=baseline,
        baseline_input_sha256=contract['baseline_input_sha256'], frame_refs=frame_refs,
        contract_sha256=q.sha(contract_path), helper_sha256=q.sha(Path(__file__)), reader_ref=reader_ref,
        source_descriptor_ref=descriptor['source_descriptor'], market_calendar=source['market_calendar'],
        semantic_sha256=q.canonical_sha(dict(descriptor=additions_ref, contract_sha256=q.sha(contract_path),
            helper_sha256=q.sha(Path(__file__)), reader=reader_ref, source_descriptor=descriptor['source_descriptor'])))


def write_pair_resolution(snapshot: dict, verified: dict, target: int, generation: str,
                          candidate_refs: dict, destination: Path) -> dict:
    """Bind actual paired output keys to verified sources before admission.

    The resolution deliberately does not point back to the generation receipt.
    It is a candidate-only source proof, never an independent universe census.
    """
    from ops import research_panel_qfq as q
    descriptor = verified['descriptor']; source = verified['source']; codes = set(source['symbols'])
    if (verified['descriptor_ref'] != snapshot.get('lifecycle_additions')
            or set(candidate_refs) != {'selector', 'backtest'} or not codes
            or set(descriptor['symbols']) != codes):
        raise QfqGateError('LIFECYCLE_RESOLUTION_INPUT_CONFLICT')
    reader_ref = verified['reader_ref']
    reader = _reader(q._source(reader_ref, owner='lifecycle admission reader'), reader_ref['sha256'])
    roles = {}
    for role in ('selector', 'backtest'):
        old_path = q._source(descriptor['baseline_roles'][role], owner='lifecycle old panel ' + role)
        new_path = q._source(candidate_refs[role], owner='lifecycle candidate panel ' + role)
        meta = q.panel_contract(new_path)
        if (meta.get('generation_id') != generation or meta.get('input_sha256') != q.canonical_sha(snapshot)
                or meta.get('asof_date') != target or meta.get('lifecycle_additions') != verified['descriptor_ref']):
            raise QfqGateError('LIFECYCLE_RESOLUTION_PANEL_IDENTITY:' + role)
        old_dates = reader._lifecycle_panel_dates_map(old_path, codes)
        new_dates = reader._lifecycle_panel_dates_map(new_path, codes)
        if any(old_dates[code] or new_dates[code] != source['symbols'][code]['dates'] for code in codes):
            raise QfqGateError('LIFECYCLE_RESOLUTION_PANEL_KEYS:' + role)
        roles[role] = dict(candidate_refs[role])
    facts = {}
    for code in sorted(codes):
        entry = source['symbols'][code]; item = snapshot['symbols'][code]
        if descriptor['symbols'][code]['source_entry_sha256'] != q.canonical_sha(entry):
            raise QfqGateError('LIFECYCLE_RESOLUTION_SOURCE_ENTRY:' + code)
        facts[code] = dict(source_entry_sha256=q.canonical_sha(entry), listing_date=entry['listing_date'],
                           dates_sha256=q.canonical_sha(entry['dates']), raw_files=entry['raw_files'],
                           row_lineage_receipt=entry['row_lineage_receipt'],
                           events_sha256=q.canonical_sha(item['events']),
                           roles={'selector':'PASS', 'backtest':'PASS'})
    value = dict(schema='qfq_lifecycle_coverage_resolution_v1', status='CANDIDATE_SOURCE_AND_PAIR_BOUND',
                 target_date=target, generation_id=generation, input_sha256=q.canonical_sha(snapshot),
                 lifecycle_additions=verified['descriptor_ref'], baseline_snapshot=descriptor['baseline_snapshot'],
                 original_sync_receipt=descriptor['original_sync_receipt'], source_descriptor=descriptor['source_descriptor'],
                 role_panels=roles, codes=facts, independent_market_master_claim=False,
                 historical_PIT=False, **_FLAGS)
    destination = Path(destination)
    if destination.exists():
        if json.loads(destination.read_text()) != value:
            raise QfqGateError('LIFECYCLE_RESOLUTION_IMMUTABLE_CONFLICT')
    else:
        q._json(destination, value)
    return dict(path=str(destination), sha256=q.sha(destination))


def verify_pair_admission(snapshot: dict, verified: dict, receipt: dict, quarantine: dict,
                          destination: Path) -> dict:
    """Run the reviewed shared admission reader on every added stock."""
    from ops import research_panel_qfq as q
    reader_ref = verified['reader_ref']
    reader = _reader(q._source(reader_ref, owner='lifecycle admission reader'), reader_ref['sha256'])
    original_read = reader.read_json
    snapshot_path = Path(receipt['adjustment_snapshot']['path'])
    # The reader still checks the snapshot SHA for every request. Avoid parsing
    # the same verified 100 MB input 31 times within this one isolated run.
    reader.read_json = lambda path: snapshot if Path(path) == snapshot_path else original_read(path)
    try:
        footer = q.panel_contract(Path(receipt['candidates']['selector']))
        rows = {}
        for code in sorted(verified['source']['symbols']):
            result = reader.verify_symbol_admission(code, str(receipt['target_date']), footer, receipt,
                quarantine, receipt['generation_id'], Path(receipt['quarantine_manifest']['path']))
            if (result.get('status') != 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
                    or result.get('membership_basis') != 'VERIFIED_LIFECYCLE_ADDITION'):
                raise QfqGateError('LIFECYCLE_READER_ADMISSION_FAILED:' + code + ':' + str(result))
            rows[code] = result
    finally:
        reader.read_json = original_read
    value = dict(schema='qfq_lifecycle_shared_reader_admission_v1', status='CANDIDATE_31_ADMISSION_PASS',
                 generation_id=receipt['generation_id'], input_sha256=receipt['input_sha256'],
                 lifecycle_additions=receipt['lifecycle_additions'], lifecycle_resolution=receipt['lifecycle_resolution'],
                 reader=reader_ref, count=len(rows), stocks=rows, independent_market_master_claim=False,
                 historical_PIT=False, **_FLAGS)
    destination = Path(destination)
    if destination.exists():
        if json.loads(destination.read_text()) != value:
            raise QfqGateError('LIFECYCLE_ADMISSION_IMMUTABLE_CONFLICT')
    else:
        q._json(destination, value)
    return dict(path=str(destination), sha256=q.sha(destination))
