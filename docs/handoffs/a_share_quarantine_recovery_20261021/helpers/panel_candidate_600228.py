"""Original-owner full-context formula and exact-key staged panel repair.

No main(), network, publication or authority writes. Canonical full partition
outputs only supplement fields discarded by the daily updater. Missing
definitions remain explicit nulls; this is never a full-schema readiness claim.
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import datetime as dt, fcntl, gc, hashlib, importlib.util, json, os, resource, struct, time
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq
R = Path(__file__).resolve().parents[1]
E = 'A_SHARE_QUARANTINE_PANEL_CANDIDATE_600228_20261021_01'
CODE = '600228.SH'

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''): h.update(b)
    return h.hexdigest()

def save(p, x):
    with Path(p).open('x') as f:
        json.dump(x, f, ensure_ascii=False, indent=2, allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())

def stat(p):
    s = Path(p).stat(); return {'inode': s.st_ino, 'mtime_ns': s.st_mtime_ns, 'size': s.st_size}

def native(b):
    assert b and len(b) % 32 == 0
    out = {}; previous = None
    for off in range(0, len(b), 32):
        row = b[off:off + 32]; d = struct.unpack_from('<I', row)[0]
        dt.datetime.strptime(str(d), '%Y%m%d'); assert previous is None or previous < d
        out[d] = row; previous = d
    return out

def owner_module(cfg, stage):
    p = cfg['owner_path']; spec = importlib.util.spec_from_file_location('frozen_600228_panel_owner', p)
    owner = importlib.util.module_from_spec(spec); sys.modules[spec.name] = owner; spec.loader.exec_module(owner)
    owner.CANONICAL_FORMULA_PATH = Path(cfg['canonical_formula_path']); owner._CANONICAL_FORMULA_MODULE = None
    owner.CONTRACT_CSV = Path(cfg['contract_csv']); owner.TDX_ROOT = Path(cfg['tdx_root'])
    for name in ('DATA_ROOT', 'RETURN_ROOT', 'SCRIPT_DIR', 'RUN_DIR', 'XDXR_CACHE_ROOT', 'PROMOTED_SELECTOR_ROOT', 'PROMOTED_BACKTEST_ROOT'):
        setattr(owner, name, stage / name.lower())
    owner.SELECTOR_POINTER = stage / 'UNPUBLISHED_SELECTOR_POINTER.txt'
    owner.BACKTEST_POINTER = stage / 'UNPUBLISHED_BACKTEST_POINTER.txt'
    return owner

def same_values(left, right):
    assert left.schema.equals(right.schema, check_metadata=False), 'Preservation schema drift'
    assert left.num_rows == right.num_rows, 'Preservation row count drift'
    bad = []
    for field in left.schema:
        a = left[field.name].combine_chunks(); b = right[field.name].combine_chunks()
        if pa.types.is_dictionary(field.type): a = a.cast(field.type.value_type); b = b.cast(field.type.value_type)
        if not pc.all(pc.equal(pc.is_null(a), pc.is_null(b))).as_py(): bad.append(field.name); continue
        equal = pc.equal(a, b)
        if pa.types.is_floating(a.type): equal = pc.or_kleene(equal, pc.and_(pc.is_nan(a), pc.is_nan(b)))
        if pc.all(pc.fill_null(equal, True)).as_py() is False: bad.append(field.name)
    assert not bad, 'Unchanged field values differ:' + ','.join(bad)

def features(cfg, stage, owner, log):
    began = time.monotonic(); binding = json.loads((R / 'INTAKE_MANIFEST.json').read_text())
    for x in binding['panels'].values():
        assert stat(x['target_path']) == x['stat'] and sha(x['pointer_path']) == x['pointer_sha256']
    policy = owner.build_contract_policy_or_fail()
    archive = native(Path(cfg['archive_member_path']).read_bytes()); windows = native(Path(cfg['windows_snapshot_path']).read_bytes())
    candidate = native(Path(cfg['source_candidate_path']).read_bytes()); first, last = min(candidate), max(candidate)
    context = dict(archive)
    for d in (20261020, 20261021): assert d in windows; context[d] = windows[d]
    context = {d: b for d, b in context.items() if d <= last}
    assert {d: b for d, b in context.items() if first <= d <= last} == candidate, 'Context/output native mismatch'
    context_path = stage / 'full_history_context.day'
    with context_path.open('xb') as f: f.write(b''.join(context[d] for d in sorted(context)))
    hist = owner.read_day_tail(CODE, context_path, tail_records=len(context))
    assert len(hist) == len(context) and int(hist['trade_date'].min()) == min(context)
    # Stock-filtered existing snapshots only; no all-universe recomputation.
    old = {}; schemas = {}
    for role, x in binding['panels'].items():
        table = ds.dataset(x['target_path'], format='parquet').to_table(filter=ds.field('ts_code') == CODE)
        assert len(set(table['trade_date'].to_pylist())) == table.num_rows
        pq.write_table(table, stage / (role + '_original_stock.parquet'))
        old[role] = table; schemas[role] = table.schema
    selector_old = old['legacy_selector']; dates = [int(d) for d in selector_old['trade_date'].to_pylist()]
    latest_static = owner.read_latest_static_map(stage / 'legacy_selector_original_stock.parquet', max(dates),
                        owner.STATIC_MAP_CANDIDATES, log, active_ts_codes=[CODE])
    # Actual source has no gbbq. Freeze absence and do not create CA evidence.
    gbbq = Path(cfg['tdx_root']) / 'T0002/hq_cache/gbbq'
    assert not gbbq.exists(), 'XDXR source presence changed from frozen contract'
    xdxr = owner.load_tdx_xdxr_events(Path(cfg['tdx_root']), log, min_trade_date=min(context), wanted_ts_codes=[CODE])
    assert xdxr.empty
    captured = {}; original_partition = owner._compute_canonical_v192_formula
    def retain_partition_return(frame):
        answer = original_partition(frame); captured['canonical'] = answer.copy(deep=True); return answer
    owner._compute_canonical_v192_formula = retain_partition_return
    generated = owner.compute_formula_features(hist, base_after_date=first-1, latest_static=latest_static,
                            log=log, emit_all_rows=True, xdxr_events=xdxr)
    owner._compute_canonical_v192_formula = original_partition
    complete = captured['canonical']; supplemental = []
    for col in complete.columns:
        if col not in generated:
            generated[col] = complete[col].to_numpy(); supplemental.append(col)
    assert generated[['ts_code', 'trade_date']].astype(str).equals(hist[['ts_code', 'trade_date']].astype(str))
    chain = owner.audit_pre_close_chain(generated); assert chain['status'] == 'PASS'
    selected = generated[generated['trade_date'].between(first, last)].copy().reset_index(drop=True)
    assert set(map(int, selected['trade_date'])) == set(candidate)
    formula_gate = owner.validate_new_selector_rows(selected, schemas['legacy_selector'], last)
    assert formula_gate['status'] == 'PASS', 'Original formula critical-field gate rejects candidate'
    requirements = json.loads(Path(cfg['panel_key_requirements']).read_text()); roles = {}
    for role, table in old.items():
        schema = schemas[role]; frame = selected.copy()
        if role == 'legacy_selector': frame = owner.append_contract_provenance(frame, Path(binding['panels'][role]['target_path']), owner.CONTRACT_PROVENANCE_FIELD_DEFAULTS['field_contract_version'])
        else: frame = owner.append_backtest_provenance_and_tradeability(frame, Path(binding['panels'][role]['target_path']))
        existing = {int(row['trade_date']): row for row in table.to_pylist()}
        missing_definitions = [f.name for f in schema if f.name not in frame]
        # Explicitly unavailable derived definitions must not retain stale
        # historic results or be guessed from their names.
        unavailable_derived = [f for f in cfg['unavailable_derived_columns'] if f in schema.names]
        projected, alignment = owner.build_table_for_schema(frame, schema, 'selector' if role == 'legacy_selector' else 'backtest', policy=None)
        metadata_preserved = []; unknown_counts = {}
        carry = set(missing_definitions) | (set(owner.STATIC_MAP_CANDIDATES) & set(schema.names))
        for field in schema:
            col = field.name
            if col in unavailable_derived:
                values = [None] * len(frame)
            elif col in carry:
                values = [existing[int(d)].get(col) if int(d) in existing else
                          frame.iloc[i][col] if col in frame and col in owner.STATIC_MAP_CANDIDATES and col != 'bars_since_list' else None
                          for i, d in enumerate(frame['trade_date'])]
                metadata_preserved.append(col)
            else: continue
            cleaned = [None if v is None or (not isinstance(v, (list, dict)) and pd.isna(v)) else v for v in values]
            array = pa.array(cleaned, type=field.type)
            projected = projected.set_column(schema.get_field_index(col), field, array)
            if array.null_count: unknown_counts[col] = array.null_count
        assert projected.schema.equals(schema, check_metadata=False)
        retire_dates = requirements[role]['retire_keys_if_native_policy_accepted']
        assert len(retire_dates) == 6 and not set(retire_dates) & set(candidate)
        before = table.to_pandas(); before['trade_date'] = before['trade_date'].astype(int)
        boundary = owner.audit_increment_boundary(before[before['trade_date'] < first], selected)
        assert boundary['status'] in ('PASS', 'PASS_WITH_XDXR_EXEMPTION'), 'Repair start boundary discontinuity'
        out = stage / (role + '_repair_rows.parquet'); pq.write_table(projected, out)
        # Every raw field is the original owner codec projection in the role dtype.
        expected_raw = selected[['trade_date', 'open', 'high', 'low', 'close', 'amount', 'volume', 'vol']].copy()
        actual = projected.to_pandas()
        for col in ('open', 'high', 'low', 'close', 'amount', 'volume' if role == 'legacy_selector' else 'vol'):
            field = schema.field(col); expected_array = pa.array(expected_raw[col].tolist(), type=field.type)
            assert projected[col].combine_chunks().equals(expected_array), 'Role raw dtype projection mismatch:' + col
        role_receipt = {'role': role, 'repair_table_path': str(out), 'repair_table_sha256': sha(out),
            'repair_rows': projected.num_rows, 'retire_keys': [[CODE, int(d)] for d in retire_dates],
            'old_stock_rows': table.num_rows, 'old_outside_window_rows': sum(d < first for d in existing),
            'old_window_keys': sum(first <= d <= last for d in existing),
            'new_inserted_keys': len(set(candidate) - set(existing)), 'boundary_gate': boundary,
            'missing_daily_or_canonical_definitions': missing_definitions, 'unavailable_derived_columns': unavailable_derived,
            'unknown_null_counts': unknown_counts, 'same_date_noncomputed_or_static_preserved': metadata_preserved,
            'original_alignment_policy_observed': alignment, 'default_zeros_for_missing_definitions_exposed': False,
            'existing_schema_policy_gate': owner.contract_schema_gate(schema, policy, role),
            'field_completeness': 'CANNOT_CONFIRM_FULL_SCHEMA; undefined derived/finance/context retained as gap',
            'raw_and_defined_calculation_scope': 'Original daily functions plus only missing original canonical partition outputs'}
        save(stage / (role + '_FEATURE_RECEIPT.json'), role_receipt); roles[role] = role_receipt
    for x in binding['panels'].values(): assert stat(x['target_path']) == x['stat']
    save(stage / 'FEATURES_RECEIPT.json', {'execution_id': E, 'phase': 'features', 'status': 'RAW_DEFINED_FORMULA_AND_REPAIR_TABLES_COMPLETE_WITH_EXPLICIT_FIELD_GAPS',
         'full_context_rows': len(context), 'context_first_date': min(context), 'context_last_date': max(context),
         'context_path': str(context_path), 'context_sha256': sha(context_path), 'emitted_first_date': first, 'emitted_last_date': last,
         'emitted_rows': len(selected), 'canonical_supplemental_columns': supplemental, 'formula_gate': formula_gate,
         'pre_close_chain_gate': chain, 'xdxr_source_status': 'Existing configured gbbq absent; no historical CA proof invented',
         'roles': roles, 'elapsed_seconds': time.monotonic()-began, 'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
         'network_calls': 0, 'authority_writes': 0, 'pointer_writes': 0, 'full_schema_ready': False})

def panels(cfg, stage, owner, log):
    began = time.monotonic(); fr = json.loads((stage / 'FEATURES_RECEIPT.json').read_text())
    binding = json.loads((R / 'INTAKE_MANIFEST.json').read_text()); results = {}
    for role, item in fr['roles'].items():
        p = binding['panels'][role]; current = Path(p['target_path'])
        assert stat(current) == p['stat'] and sha(p['pointer_path']) == p['pointer_sha256']
        assert sha(item['repair_table_path']) == item['repair_table_sha256']
        new = pq.read_table(item['repair_table_path']); output = stage / (role + '_UNPUBLISHED_candidate.parquet')
        receipt = owner.write_appended_parquet(current, new, output, log, retire_keys=[tuple(k) for k in item['retire_keys']])
        # The exact writer retains each old batch as one row group; compare
        # every unaffected field, including dictionary values/nulls/NaNs.
        affected = {(CODE, int(d)) for d in new['trade_date'].to_pylist()} | {tuple(k) for k in item['retire_keys']}
        oldpf, outpf = pq.ParquetFile(current), pq.ParquetFile(output); rg = 0; preserved = 0
        for batch in oldpf.iter_batches(batch_size=65536):
            old = pa.Table.from_batches([batch], schema=oldpf.schema_arrow)
            keep = [(str(x['ts_code']), int(x['trade_date'])) not in affected for x in old.select(['ts_code', 'trade_date']).to_pylist()]
            retained = old if all(keep) else old.filter(pa.array(keep, type=pa.bool_()))
            if not retained.num_rows: continue
            same_values(retained, outpf.read_row_group(rg)); rg += 1; preserved += retained.num_rows
        same_values(new, outpf.read_row_group(rg)); assert outpf.metadata.num_row_groups == rg + 1
        assert preserved == receipt['current_rows_retained'] and stat(current) == p['stat']
        assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss < cfg['max_process_rss_bytes']
        result = {'role': role, 'candidate_path': str(output), 'candidate_sha256': sha(output), 'writer': receipt,
                  'all_unaffected_rows_and_fields_verified_equal': preserved, 'field_mismatch_count': 0,
                  'new_rows_verified_against_original_owner_repair_table': new.num_rows,
                  'retire_count': len(item['retire_keys']), 'original_input_unchanged_stat': stat(current),
                  'full_schema_ready': False, 'field_gaps': item['unknown_null_counts']}
        save(stage / (role + '_PANEL_RECEIPT.json'), result); results[role] = result
        del oldpf, outpf, new; gc.collect()
    save(stage / 'PANELS_RECEIPT.json', {'execution_id': E, 'phase': 'panels', 'status': 'UNPUBLISHED_EXACT_KEY_PANEL_CANDIDATES_WITH_EXPLICIT_FIELD_GAPS',
         'roles': results, 'elapsed_seconds': time.monotonic()-began,
         'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
         'authority_writes': 0, 'pointer_writes': 0, 'independent_review': 'PENDING; not restored/deployed/fullschemaREADY'})

def main():
    phase = sys.argv[1]; assert phase in ('features', 'panels')
    cfg = json.loads((R / 'PANEL_CANDIDATE_600228_CONTRACT.json').read_text())
    gate = (R / 'registry_receipts/PANEL_CANDIDATE_600228_REGISTRY_START.json').read_text()
    assert E in gate and 'RUN_STARTED' in gate
    for x in cfg['input_bindings']: assert sha(x['path']) == x['sha256'], 'Frozen input drift'
    lock = (R / 'PANEL_CANDIDATE_600228.lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stage = R / 'panel_candidate_600228' / E
    if phase == 'features': stage.mkdir(mode=0o700, parents=True, exist_ok=False)
    else: assert stage.is_dir() and (stage / 'FEATURES_RECEIPT.json').exists()
    owner = owner_module(cfg, stage)
    with (stage / (phase + '_runtime.log')).open('x') as stream:
        class Log:
            def log(self, message): stream.write(str(message)+'\n'); stream.flush()
        (features if phase == 'features' else panels)(cfg, stage, owner, Log())
    receipt = stage / ('FEATURES_RECEIPT.json' if phase == 'features' else 'PANELS_RECEIPT.json')
    print(json.dumps({'execution_id': E, 'phase': phase, 'receipt_path': str(receipt), 'sha256': sha(receipt)}))

if __name__ == '__main__': main()
