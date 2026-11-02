"""Action-only projection helper for the existing isolated QFQ owner.

It consumes already persisted inputs and a SHA-bound correction ledger. It is
not a signal calculator and cannot publish or change live pointers.
"""
from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import shutil
import time

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


ACTION_FIELDS = ('kb_action_no_position', 'kb_action_no_position_status',
                 'kb_action_with_position', 'kb_action_with_position_status',
                 'kb_action_reasons', 'kb_action_rule_sha256')


def _array(array):
    return array.combine_chunks() if isinstance(array, pa.ChunkedArray) else array


def exact_values(left, right):
    """Match type, null mask and values, retaining float NaN and signed zero."""
    left, right = _array(left), _array(right)
    if left.type != right.type or len(left) != len(right) or not left.is_null().equals(right.is_null()):
        return False
    if pa.types.is_dictionary(left.type):
        return exact_values(pc.cast(left, left.type.value_type), pc.cast(right, right.type.value_type))
    if pa.types.is_floating(left.type):
        valid = np.logical_not(left.is_null().to_numpy(zero_copy_only=False))
        a = left.to_numpy(zero_copy_only=False)[valid]
        b = right.to_numpy(zero_copy_only=False)[valid]
        if left.type == pa.float64():
            return np.array_equal(a.view(np.uint64), b.view(np.uint64))
        if left.type == pa.float32():
            return np.array_equal(a.view(np.uint32), b.view(np.uint32))
        return False
    return left.equals(right)


class DeltaApplier:
    """Apply each recorded old→new action row exactly once per panel role."""

    def __init__(self, stock_index, *, q, old_generation, old_authority, new_authority, expected_rows):
        self.stocks = stock_index
        self.q = q
        self.old_generation = old_generation
        self.old_authority = old_authority
        self.new_authority = new_authority
        self.expected_rows = expected_rows
        self.seen = {}
        self.cache = {}
        self.applied = 0

    def _load(self, code):
        if code in self.cache:
            return self.cache[code]
        entry = self.stocks[code]
        ref = entry.get('overlay')
        if not ref or not entry.get('affected_rows'):
            raise self.q.QfqGateError('ACTION_DELTA_MISSING_OVERLAY:' + code)
        path = self.q._source(ref, owner='action delta ' + code)
        table = pq.read_table(path)
        meta = table.schema.metadata or {}
        expected = {b'old_candidate_generation': self.old_generation,
                    b'old_action_authority_sha256': self.old_authority,
                    b'new_action_authority_sha256': self.new_authority,
                    b'scope': 'ACTION_DELTA_NOT_A_PANEL'}
        if any(meta.get(k, b'').decode() != v for k, v in expected.items()):
            raise self.q.QfqGateError('ACTION_DELTA_OVERLAY_IDENTITY:' + code)
        dates = table['trade_date'].to_pylist()
        if (len(table) != entry['affected_rows'] or dates != sorted(set(dates))
                or set(table['ts_code'].to_pylist()) != {code}):
            raise self.q.QfqGateError('ACTION_DELTA_OVERLAY_KEYS:' + code)
        if set('input__' + f for f in self.q.SINGLE_ACTION_INPUTS) - set(table.column_names):
            raise self.q.QfqGateError('ACTION_DELTA_INPUT_FIELDS:' + code)
        if set(prefix + f for prefix in ('old__', 'new__') for f in ACTION_FIELDS) - set(table.column_names):
            raise self.q.QfqGateError('ACTION_DELTA_OUTPUT_FIELDS:' + code)
        self.seen[code] = bytearray(len(table))
        self.cache[code] = table
        return table

    def apply(self, batch):
        if not isinstance(batch, pa.RecordBatch):
            raise self.q.QfqGateError('ACTION_DELTA_BATCH_TYPE')
        names = batch.schema.names
        required = {'ts_code', 'trade_date', *self.q.SINGLE_ACTION_INPUTS, *ACTION_FIELDS}
        if required - set(names):
            raise self.q.QfqGateError('ACTION_DELTA_PANEL_FIELDS_MISSING')
        codes = batch.column(names.index('ts_code')).to_pylist()
        positions = defaultdict(list)
        for i, code in enumerate(codes):
            if code in self.stocks and self.stocks[code].get('affected_rows'):
                positions[code].append(i)
        if not positions:
            return batch
        dates = pc.cast(batch.column(names.index('trade_date')), pa.int64())
        replacements = {f: batch.column(names.index(f)).to_pylist() for f in ACTION_FIELDS}
        touched = False
        for code, items in positions.items():
            overlay = self._load(code)
            candidate_positions = pa.array(items, type=pa.int64())
            candidate_dates = pc.take(dates, candidate_positions)
            indexes = pc.index_in(candidate_dates, value_set=_array(overlay['trade_date']))
            valid = pc.is_valid(indexes)
            if not pc.any(valid).as_py():
                continue
            panel_positions = pc.filter(candidate_positions, valid)
            overlay_positions = pc.filter(indexes, valid)
            for field in self.q.SINGLE_ACTION_INPUTS:
                actual = pc.take(batch.column(names.index(field)), panel_positions)
                expected = pc.take(_array(overlay['input__' + field]), overlay_positions)
                try:
                    expected = pc.cast(expected, actual.type, safe=True)
                except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError) as error:
                    raise self.q.QfqGateError('ACTION_DELTA_INPUT_TYPE:' + code + ':' + field) from error
                if not exact_values(actual, expected):
                    raise self.q.QfqGateError('ACTION_DELTA_INPUT_MISMATCH:' + code + ':' + field)
            for field in ACTION_FIELDS:
                actual = pc.take(batch.column(names.index(field)), panel_positions)
                expected = pc.take(_array(overlay['old__' + field]), overlay_positions)
                try:
                    expected = pc.cast(expected, actual.type, safe=True)
                except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError) as error:
                    raise self.q.QfqGateError('ACTION_DELTA_OLD_TYPE:' + code + ':' + field) from error
                if not exact_values(actual, expected):
                    raise self.q.QfqGateError('ACTION_DELTA_OLD_VALUE_MISMATCH:' + code + ':' + field)
                new_values = pc.take(_array(overlay['new__' + field]), overlay_positions).to_pylist()
                for pos, value in zip(panel_positions.to_pylist(), new_values):
                    replacements[field][pos] = value
            for pos in overlay_positions.to_pylist():
                if self.seen[code][pos]:
                    raise self.q.QfqGateError('ACTION_DELTA_DUPLICATE_KEY:' + code)
                self.seen[code][pos] = 1
                self.applied += 1
            touched = True
        if not touched:
            return batch
        arrays = list(batch.columns)
        for field in ACTION_FIELDS:
            pos = names.index(field)
            arrays[pos] = pa.array(replacements[field], type=batch.schema.field(pos).type)
        return pa.RecordBatch.from_arrays(arrays, schema=batch.schema)

    def finish(self):
        if self.applied != self.expected_rows:
            raise self.q.QfqGateError('ACTION_DELTA_MISSING_KEYS')
        for code, entry in self.stocks.items():
            if entry.get('affected_rows') and (code not in self.seen or sum(self.seen[code]) != entry['affected_rows']):
                raise self.q.QfqGateError('ACTION_DELTA_INCOMPLETE_STOCK:' + code)
        return {'applied_rows': self.applied, 'affected_stocks': len(self.seen)}


def write_role(source, destination, schema, projector, *, budget):
    """Preserve source row groups and rewrite only action values in isolation."""
    old = pq.ParquetFile(source)
    if not old.schema_arrow.equals(schema, check_metadata=False):
        raise projector.q.QfqGateError('ACTION_DELTA_OUTPUT_SCHEMA_CHANGED')
    rows = 0
    with pq.ParquetWriter(destination, schema, compression='zstd') as writer:
        for group in range(old.num_row_groups):
            table = old.read_row_group(group)
            batches = [projector.apply(batch) for batch in table.to_batches(max_chunksize=65536)]
            output = pa.Table.from_batches(batches).replace_schema_metadata(schema.metadata)
            if len(output) != old.metadata.row_group(group).num_rows:
                raise projector.q.QfqGateError('ACTION_DELTA_ROW_GROUP_CHANGED')
            writer.write_table(output, row_group_size=len(output))
            rows += len(output)
            budget()
    budget()
    proof = projector.finish()
    return {'rows': rows, 'row_groups': old.num_row_groups, **proof}


def verify_role(source, destination, projector, *, progress=lambda *_: None):
    """Read back both artifacts and compare every key, value, type and null."""
    old, new = pq.ParquetFile(source), pq.ParquetFile(destination)
    if (old.metadata.num_rows != new.metadata.num_rows or old.num_row_groups != new.num_row_groups
            or not old.schema_arrow.equals(new.schema_arrow, check_metadata=False)):
        raise projector.q.QfqGateError('ACTION_DELTA_READBACK_SCHEMA_OR_ROWS')
    rows = 0
    for group in range(old.num_row_groups):
        before, after = old.read_row_group(group), new.read_row_group(group)
        if len(before) != len(after):
            raise projector.q.QfqGateError('ACTION_DELTA_READBACK_GROUP_ROWS')
        predicted = pa.Table.from_batches([projector.apply(batch) for batch in before.to_batches(max_chunksize=65536)])
        for name in before.column_names:
            expected = predicted[name] if name in ACTION_FIELDS else before[name]
            if not exact_values(expected, after[name]):
                raise projector.q.QfqGateError('ACTION_DELTA_READBACK_VALUE:' + str(group) + ':' + name)
        rows += len(before)
        progress(group + 1, old.num_row_groups, rows)
    proof = projector.finish()
    return {'status': 'PASS', 'rows': rows, 'row_groups': old.num_row_groups,
            'non_action_columns_exact': len(old.schema_arrow) - len(ACTION_FIELDS),
            'action_columns_match_bound_delta': len(ACTION_FIELDS), **proof}


def _path_ref(q, path):
    p = Path(path).resolve(strict=True)
    return {'path': str(p), 'sha256': q.sha(p)}


def _read(q, reference, owner):
    path = q._source(reference, owner=owner)
    if 'bytes' in reference and path.stat().st_size != reference['bytes']:
        raise q.QfqGateError('ACTION_DELTA_REFERENCE_SIZE:' + owner)
    return json.loads(path.read_text())


def _same_ref(left, right):
    return (isinstance(left, dict) and isinstance(right, dict)
            and all(left.get(k) == right.get(k) for k in ('path', 'sha256')))


def _stamp(path):
    s = Path(path).stat()
    return {'device': s.st_dev, 'inode': s.st_ino, 'size': s.st_size,
            'mtime_ns': s.st_mtime_ns, 'ctime_ns': s.st_ctime_ns}


def _isolated_root(path, q):
    p = Path(path)
    if not p.is_absolute() or p.is_symlink():
        raise q.QfqGateError('ACTION_DELTA_ISOLATION_ROOT_INVALID')
    p = p.resolve()
    protected = [Path.home() / 'Library/Application Support/com.lexi.v35.local/state',
                 Path.home() / 'Library/Application Support/com.lexi.v4.local/state']
    if any(p == x.resolve() or p in x.resolve().parents or x.resolve() in p.parents for x in protected):
        raise q.QfqGateError('ACTION_DELTA_ACTIVE_ROOT_FORBIDDEN')
    p.mkdir(parents=True, exist_ok=True)
    return p


def materialize_candidate(*, q, delta_ref, baseline_ref, driver_ref, formula_ref,
                          contract_csv_ref, source_relocation_ref, output_root, prepare_only=False):
    """Build a paired action correction through QFQ, without publishing it."""
    from ops import research_panel_daily_107_binding as daily
    from ops import research_panel_lifecycle as lifecycle
    from ops.research_panel_turnover import DailyTurnover

    root = _isolated_root(output_root, q)
    with q.publication_lock(root):
        summary = _read(q, delta_ref, 'action correction summary')
        descriptor = _read(q, baseline_ref, 'action correction baseline')
        if (summary.get('schema') != 'v4.a_share.action_delta_summary.v1'
                or summary.get('status') != 'ACTION_DELTA_READY_NOT_PAIRED'
                or summary.get('new_pair_sha256') is not None or set(summary.get('action_fields', [])) != set(ACTION_FIELDS)
                or descriptor.get('schema') != 'a_share_kb_daily_continuation_v1'
                or not _same_ref(descriptor.get('baseline_receipt'), summary.get('source_candidate'))
                or any(summary.get(k) != v or descriptor.get(k) != v for k, v in q.FLAGS.items())):
            raise q.QfqGateError('ACTION_DELTA_DESCRIPTOR_CONFLICT')
        prior = _read(q, summary['source_candidate'], 'action correction prior receipt')
        att = _read(q, summary['source_attestation'], 'action correction prior attestation')
        run = _read(q, summary['stock_run'], 'action correction stock run')
        stocks = _read(q, summary['stock_index'], 'action correction stock index')
        if (prior.get('status') != 'CANDIDATE_READY' or att.get('status') != 'PASS'
                or att.get('candidate_receipt_sha256') != summary['source_candidate']['sha256']
                or prior.get('generation_id') != summary.get('old_candidate_generation')
                or prior.get('candidate_sha256') != summary.get('old_pair_sha256')
                or prior.get('single_action_authority_sha256') != summary.get('old_action_authority_sha256')
                or prior.get('single_action_contract_sha256') != summary.get('action_rule_contract_sha256')
                or run.get('status') != 'ACTION_DELTA_STOCKS_COMPLETE_NOT_A_PAIR'
                or set(run.get('stock_receipts', {})) != set(stocks)
                or set(stocks) != set(prior.get('confirmed_gap_sidecars', {}))
                or len(stocks) != summary.get('stock_count')
                or sum(x.get('affected_rows', 0) for x in stocks.values()) != summary.get('changed_rows')):
            raise q.QfqGateError('ACTION_DELTA_SOURCE_IDENTITY_CONFLICT')
        action_path = q._source(summary['action_authority'], owner='corrected action authority')
        if action_path.resolve() != Path(q.__file__).with_name('kb_action_authority.py').resolve():
            raise q.QfqGateError('ACTION_DELTA_ACTION_AUTHORITY_NOT_LOADED')
        for code, item in stocks.items():
            if item.get('stock_receipt') != run['stock_receipts'][code]:
                raise q.QfqGateError('ACTION_DELTA_STOCK_RECEIPT_CONFLICT:' + code)
        sources = {}
        for role in ('selector', 'backtest'):
            source = Path(prior['candidates'][role])
            bound = att['roles'][role]
            if (str(source) != bound['path'] or prior['candidate_sha256'][role] != bound['sha256']
                    or descriptor['baseline_roles'][role]['sha256'] != bound['sha256']
                    or _stamp(source) != bound['stat']):
                raise q.QfqGateError('ACTION_DELTA_ATTESTED_ROLE_CONFLICT:' + role)
            sources[role] = source
        target = int(prior['target_date'])
        snapshot_path = q._source(prior['adjustment_snapshot'], owner='action correction snapshot')
        if prior['adjustment_snapshot'] != descriptor['baseline_snapshot']:
            raise q.QfqGateError('ACTION_DELTA_SNAPSHOT_REFERENCE_CONFLICT')
        snapshot = q.load_snapshot(snapshot_path, target, source_relocation_ref)
        driver = q._source(driver_ref, owner='action correction driver')
        formula = q._source(formula_ref, owner='action correction formula')
        contract_csv = q._source(contract_csv_ref, owner='action correction CSV contract')
        q.authorities(driver, formula)
        old_adapter = q._source(descriptor['baseline_adapter'], owner='action correction original QFQ adapter')
        if (descriptor['baseline_adapter']['sha256'] != prior['adapter_sha256']
                or daily.computation_semantics_sha(old_adapter, q) != daily.computation_semantics_sha(Path(q.__file__), q)):
            raise q.QfqGateError('ACTION_DELTA_UNRELATED_QFQ_KERNEL_CHANGED')
        identity = q.generation_identity(snapshot, driver, formula, contract_csv, source_relocation_ref)
        for key, value in identity.items():
            if key not in ('adapter_sha256', 'single_action_authority_sha256') and prior.get(key) != value:
                raise q.QfqGateError('ACTION_DELTA_OTHER_IDENTITY_CHANGED:' + key)
        if (identity['input_sha256'] != prior['input_sha256']
                or identity['single_action_authority_sha256'] != summary['action_authority']['sha256']
                or identity['single_action_contract_sha256'] != prior['single_action_contract_sha256']):
            raise q.QfqGateError('ACTION_DELTA_RULE_OR_INPUT_CONFLICT')
        contract_ref = prior['full_research_contract']
        q.full_research_contract(contract_ref)
        if contract_ref['sha256'] != prior['full_research_contract_sha256']:
            raise q.QfqGateError('ACTION_DELTA_FULL_CONTRACT_CONFLICT')
        expected = dict(research_scope='ADMITTED_A_SHARE', full_research_contract_sha256=contract_ref['sha256'],
            single_feedback_enabled=True, single_action_enabled=True, single_yidong_enabled=True,
            confirmed_gap_enabled=True, confirmed_gap_contract_sha256=q.gap_rule_sha256(),
            confirmed_gap_helper_sha256=q.gap_helper_sha256s(),
            confirmed_gap_rebuild_contract_sha256=q.sha(Path(q.__file__).resolve().parents[1] / 'contracts/a_share_kb_rebuild_brick_v1.json'),
            confirmed_gap_components_contract_sha256=q.sha(Path(q.__file__).resolve().parents[1] / 'contracts/a_share_kb_signal_components_v1.json'),
            confirmed_gap_snapshot_file_sha256=q.sha(snapshot_path), n_structure_enabled=True, **q._n_sha256s())
        if any(prior.get(k) != v for k, v in expected.items()):
            raise q.QfqGateError('ACTION_DELTA_OTHER_RESEARCH_RULE_CHANGED')
        prior_turnover = prior.get('turnover_input') or {}
        turnover = DailyTurnover(target, None, {}, prior_turnover.get('binding', {}), prior_turnover.get('failure'))
        turnover.verify_binding()
        if turnover.identity != prior.get('turnover_input_sha256'):
            raise q.QfqGateError('ACTION_DELTA_TURNOVER_BINDING_CHANGED')
        identity.update(expected, turnover_input_sha256=turnover.identity,
                        action_correction_summary_sha256=delta_ref['sha256'],
                        action_correction_helper_sha256=q.sha(Path(__file__)))
        # Close the inherited 31-stock source gate before creating either
        # large role artifact, not after spending the storage budget.
        verified = lifecycle.verify_snapshot(snapshot, target)
        generation = q.canonical_sha(dict(target=target, baseline_panel_sha256=prior['candidate_sha256'], **identity))
        run_dir = root / ('qfq_action_' + generation[:20])
        run_dir.mkdir(parents=True, exist_ok=True)
        config = dict(schema='a_share_qfq_action_correction_v1', generation_id=generation, target_date=target,
            source_generation=prior['generation_id'], source_receipt=summary['source_candidate'],
            source_attestation=summary['source_attestation'], delta_summary=delta_ref, identity=identity,
            baseline_panel_sha256=prior['candidate_sha256'], historical_PIT=False, **q.FLAGS)
        config_path = run_dir / 'config.json'
        if config_path.exists() and json.loads(config_path.read_text()) != config:
            raise q.QfqGateError('ACTION_DELTA_RESUME_IDENTITY_CHANGED')
        if not config_path.exists():
            q._json(config_path, config)
        if (run_dir / 'candidate_receipt.json').exists():
            raise q.QfqGateError('ACTION_DELTA_CANDIDATE_ALREADY_EXISTS')
        budget_bytes, reserve_bytes = 14 * 1024**3, 24 * 1024**3
        if shutil.disk_usage(root).free < budget_bytes + reserve_bytes and not any(run_dir.glob('*.parquet')):
            raise q.QfqGateError('ACTION_DELTA_INSUFFICIENT_DISK_RESERVE')
        if prepare_only:
            result = dict(status='ACTION_CORRECTION_PREFLIGHT_PASS_NOT_PAIRED', generation_id=generation,
                config=_path_ref(q, config_path), source_gate='LOAD_SNAPSHOT_AND_LIFECYCLE_VERIFIED',
                action_delta=delta_ref, old_pair_sha256=prior['candidate_sha256'],
                free_bytes=shutil.disk_usage(root).free, storage_write_budget_bytes=budget_bytes,
                minimum_free_bytes=reserve_bytes, global_pointers_updated=False, **q.FLAGS)
            path = run_dir / 'preflight.json'
            if path.exists():
                raise q.QfqGateError('ACTION_DELTA_PREFLIGHT_ALREADY_EXISTS')
            q._json(path, result)
            return {**result, 'preflight': _path_ref(q, path)}
        role_paths = {role: run_dir / (role + '.parquet') for role in ('selector', 'backtest')}
        progress_path = run_dir / 'progress.json'

        def budget():
            written = sum(p.stat().st_size for p in run_dir.glob('*.parquet*') if p.is_file())
            free = shutil.disk_usage(root).free
            q._json(progress_path, dict(status='RUNNING', stage='WRITING_ACTION_ONLY_PAIR',
                generation_id=generation, written_bytes=written, free_bytes=free, **q.FLAGS))
            if written > budget_bytes or free < reserve_bytes:
                raise q.QfqGateError('ACTION_DELTA_STORAGE_LIMIT')

        def make_applier():
            return DeltaApplier(stocks, q=q, old_generation=prior['generation_id'],
                old_authority=prior['single_action_authority_sha256'],
                new_authority=identity['single_action_authority_sha256'], expected_rows=summary['changed_rows'])

        role_proofs = {}
        try:
            for role in ('selector', 'backtest'):
                old_meta = q.panel_contract(sources[role])
                if (old_meta.get('generation_id') != prior['generation_id']
                        or old_meta.get('input_sha256') != prior['input_sha256']):
                    raise q.QfqGateError('ACTION_DELTA_OLD_FOOTER_IDENTITY:' + role)
                meta = {**old_meta, **identity, 'generation_id': generation,
                    'generation_manifest_path': str(run_dir / 'candidate_receipt.json'),
                    'baseline_panel_sha256': prior['candidate_sha256'],
                    'action_correction': {'source_generation': prior['generation_id'], 'summary': delta_ref,
                        'old_authority_sha256': prior['single_action_authority_sha256'],
                        'new_authority_sha256': identity['single_action_authority_sha256'],
                        'sidecar_source_generation': prior['generation_id']},
                    'cross_generation_n_checkpoint_reused': False}
                old_schema = pq.ParquetFile(sources[role]).schema_arrow
                metadata = dict(old_schema.metadata or {})
                metadata[q.META_KEY] = json.dumps(meta, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
                schema = old_schema.with_metadata(metadata)
                target_path = role_paths[role]
                ready_path = run_dir / (role + '.ready.json')
                if ready_path.exists():
                    ready = json.loads(ready_path.read_text())
                    if (ready.get('generation_id') != generation or ready.get('delta_sha256') != delta_ref['sha256']
                            or ready.get('source_sha256') != prior['candidate_sha256'][role]
                            or ready.get('candidate_sha256') != q.sha(target_path) or ready.get('proof', {}).get('status') != 'PASS'):
                        raise q.QfqGateError('ACTION_DELTA_ROLE_CHECKPOINT_CONFLICT:' + role)
                    role_proofs[role] = ready['proof']
                    continue
                if not target_path.exists():
                    temporary = run_dir / (role + '.' + str(time.time_ns()) + '.parquet.partial')
                    write_role(sources[role], temporary, schema, make_applier(), budget=budget)
                    if target_path.exists():
                        raise q.QfqGateError('ACTION_DELTA_ROLE_CONCURRENT_WRITE:' + role)
                    os.rename(temporary, target_path)
                footer = q.panel_contract(target_path)
                if footer != meta:
                    raise q.QfqGateError('ACTION_DELTA_NEW_FOOTER_CONFLICT:' + role)
                def report(done, total, rows):
                    q._json(progress_path, dict(status='RUNNING', stage='VERIFYING_ACTION_PAIR', role=role,
                        row_groups_completed=done, row_groups_total=total, rows=rows,
                        generation_id=generation, free_bytes=shutil.disk_usage(root).free, **q.FLAGS))
                proof = verify_role(sources[role], target_path, make_applier(), progress=report)
                role_proofs[role] = proof
                q._json(ready_path, dict(schema='a_share_qfq_action_role_ready_v1', generation_id=generation,
                    source_sha256=prior['candidate_sha256'][role], candidate_sha256=q.sha(target_path),
                    delta_sha256=delta_ref['sha256'], proof=proof, **q.FLAGS))
            if any(_stamp(sources[r]) != att['roles'][r]['stat'] for r in sources):
                raise q.QfqGateError('ACTION_DELTA_SOURCE_CHANGED_DURING_RUN')
            q._source(delta_ref, owner='action correction summary final')
            q._source(summary['action_authority'], owner='action authority final')
            candidate_refs = {role: _path_ref(q, path) for role, path in role_paths.items()}
            equivalence = dict(schema='v4.a_share.action_correction_equivalence.v1', status='PASS',
                generation_id=generation, input_sha256=identity['input_sha256'], target_date=target,
                baseline_generation_id=prior['generation_id'], baseline_panel_sha256=prior['candidate_sha256'],
                candidate_sha256={r: candidate_refs[r]['sha256'] for r in candidate_refs},
                action_delta_summary=delta_ref, roles=role_proofs,
                unchanged_scope='ALL_NON_ACTION_ARROW_COLUMNS_KEYS_TYPES_NULL_NAN_AND_SIGNED_ZERO',
                inherited_sidecars_source_generation=prior['generation_id'],
                cross_generation_n_checkpoint_reused=False, historical_PIT=False, **q.FLAGS)
            proof_path = run_dir / 'action_correction_equivalence.json'
            q._json(proof_path, equivalence)
            quarantine = _read(q, prior['quarantine_manifest'], 'action correction quarantine')
            quarantine['generation_id'] = generation
            quarantine_path = run_dir / 'quarantine_manifest.json'
            q._json(quarantine_path, quarantine)
            resolution = lifecycle.write_pair_resolution(snapshot, verified, target, generation,
                                                         candidate_refs, run_dir / 'lifecycle_resolution.json')
            metadata = q.panel_contract(role_paths['selector'])
            receipt = {**prior, **metadata, 'status': 'CANDIDATE_READY', 'target_date': target,
                'run_dir': str(run_dir), 'candidates': {r: str(p) for r, p in role_paths.items()},
                'candidate_sha256': {r: candidate_refs[r]['sha256'] for r in candidate_refs},
                'quarantine_manifest': _path_ref(q, quarantine_path), 'quarantine_manifest_path': str(quarantine_path),
                'lifecycle_resolution': resolution, 'action_correction_equivalence': _path_ref(q, proof_path)}
            receipt_path = run_dir / 'candidate_receipt.json'
            q._json(receipt_path, receipt)
            admission = lifecycle.verify_pair_admission(snapshot, verified, receipt, quarantine,
                                                         run_dir / 'lifecycle_admission.json')
            roles = {}
            for role, path in role_paths.items():
                pf = pq.ParquetFile(path); footer = q.panel_contract(path)
                if footer.get('generation_id') != generation or footer.get('input_sha256') != identity['input_sha256']:
                    raise q.QfqGateError('ACTION_DELTA_FINAL_FOOTER_CONFLICT:' + role)
                roles[role] = dict(path=str(path), sha256=candidate_refs[role]['sha256'],
                    rows=pf.metadata.num_rows, columns=len(pf.schema_arrow), stat=_stamp(path),
                    footer_generation_id=footer['generation_id'], footer_input_sha256=footer['input_sha256'])
            attestation = dict(schema='v4.a_share.paired_candidate_attestation.v1', status='PASS',
                generation_id=generation, input_sha256=identity['input_sha256'],
                candidate_receipt=_path_ref(q, receipt_path), candidate_receipt_sha256=q.sha(receipt_path),
                roles=roles, source_attestation=summary['source_attestation'],
                action_correction_equivalence=_path_ref(q, proof_path), lifecycle_admission=admission,
                historical_PIT=False, **q.FLAGS)
            attest_path = run_dir / 'paired_attestation.json'
            q._json(attest_path, attestation)
            q._json(progress_path, dict(status='CANDIDATE_READY', generation_id=generation,
                candidate_receipt=_path_ref(q, receipt_path), paired_attestation=_path_ref(q, attest_path),
                global_pointers_updated=False, **q.FLAGS))
            return dict(status='CANDIDATE_READY', generation_id=generation,
                candidate_receipt=_path_ref(q, receipt_path), paired_attestation=_path_ref(q, attest_path),
                action_correction_equivalence=_path_ref(q, proof_path), lifecycle_admission=admission,
                global_pointers_updated=False, **q.FLAGS)
        except BaseException as error:
            q._json(run_dir / ('failure_' + str(time.time_ns()) + '.json'), dict(status='FAILED',
                generation_id=generation, error=repr(error), historical_PIT=False, **q.FLAGS))
            raise
