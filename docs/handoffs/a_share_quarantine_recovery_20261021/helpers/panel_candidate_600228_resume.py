"""Resume saved products after checker int->float32 construction failure.

Never reruns the original successful full-context formula or selector checks.
Only unfinished backtest-volume dtype validation, receipts and planned merge.
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import hashlib, importlib.util, json, os, resource, struct, time
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
R = Path(__file__).resolve().parents[1]
E = 'A_SHARE_QUARANTINE_PANEL_CANDIDATE_600228_20261021_R2_01'

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(8*1024*1024), b''): h.update(b)
    return h.hexdigest()

def save(p, x):
    with Path(p).open('x') as f:
        json.dump(x, f, ensure_ascii=False, indent=2, allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())

def main():
    phase = sys.argv[1]; assert phase in ('complete_features', 'panels')
    cfg = json.loads((R / 'PANEL_CANDIDATE_600228_R2_CONTRACT.json').read_text())
    gate = (R / 'registry_receipts/PANEL_CANDIDATE_600228_R2_REGISTRY_START.json').read_text()
    assert E in gate and 'RUN_STARTED' in gate
    for x in cfg['input_bindings']: assert sha(x['path']) == x['sha256'], 'Frozen saved product/source drift'
    stage = R / 'panel_candidate_600228' / E
    if phase == 'complete_features': stage.mkdir(mode=0o700, parents=True, exist_ok=False)
    else: assert (stage / 'FEATURES_RECEIPT.json').exists()
    source = R / 'helpers/panel_candidate_600228.py'
    spec = importlib.util.spec_from_file_location('saved_original_panel_functions', source)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); module.E = E
    owner = module.owner_module(cfg, stage)
    with (stage / (phase + '_runtime.log')).open('x') as stream:
        class Log:
            def log(self, msg): stream.write(str(msg)+'\n'); stream.flush()
        if phase == 'panels':
            module.panels(cfg, stage, owner, Log())
        else:
            began = time.monotonic(); oldstage = Path(cfg['prior_stage'])
            old_selector = json.loads((oldstage / 'legacy_selector_FEATURE_RECEIPT.json').read_text())
            backtest = pq.read_table(oldstage / 'legacy_backtest_repair_rows.parquet')
            raw = owner.read_day_tail('600228.SH', Path(cfg['source_candidate_path']), tail_records=298)
            assert raw['trade_date'].astype(int).tolist() == [int(d) for d in backtest['trade_date'].to_pylist()]
            field = backtest.schema.field('vol')
            # Exact original role storage projection, not Arrow's stricter
            # int-list safe-cast precondition (which rejected >2**24 integers).
            expected = owner.coerce_series_to_arrow(raw['vol'].reset_index(drop=True), field)
            assert backtest['vol'].combine_chunks().equals(expected), 'Backtest volume role dtype mismatch'
            controls = np.array([0, 16777216, 18035862, 4294967295], dtype=np.uint64)
            actual_controls = owner.coerce_series_to_arrow(module.pd.Series(controls), field)
            ieee_controls = pa.array(controls.astype(np.float32).astype(np.float64).tolist(), type=field.type)
            assert actual_controls.equals(ieee_controls), 'IEEE float32 native volume control mismatch'
            save(stage / 'VOLUME_ORACLE_CORRECTION.json', {'old_error': 'ArrowInvalid intlist18035862->float32 safe cast',
                'old_failed_execution': 'A_SHARE_QUARANTINE_PANEL_CANDIDATE_600228_20261021_01',
                'correction': 'Use exact originalowner coerce_series_to_arrow (numeric floatlist -> role float32) and independent IEEE numpy float32 projection controls',
                'native_volume_unit': 'Unchanged owner.read_day_tail raw uint32 count, no /100 or economic-unit reinterpretation',
                'input_controls': [int(v) for v in controls], 'owner_float32_controls': actual_controls.to_pylist(),
                'ieee_float32_controls': ieee_controls.to_pylist(), 'all298_existing_volume_values_equal': True,
                'candidate_values_changed': False, 'thresholds_changed': False})
            policy = owner.build_contract_policy_or_fail()
            binding = json.loads((R / 'INTAKE_MANIFEST.json').read_text())
            original = pq.read_table(oldstage / 'legacy_backtest_original_stock.parquet')
            old_dates = {int(d) for d in original['trade_date'].to_pylist()}
            first, last = int(raw['trade_date'].min()), int(raw['trade_date'].max())
            requirements = json.loads(Path(cfg['panel_key_requirements']).read_text())['legacy_backtest']
            unknown = {name: backtest[name].null_count for name in backtest.column_names if backtest[name].null_count}
            backtest_role = {'role': 'legacy_backtest', 'repair_table_path': str(oldstage / 'legacy_backtest_repair_rows.parquet'),
                'repair_table_sha256': sha(oldstage / 'legacy_backtest_repair_rows.parquet'), 'repair_rows': backtest.num_rows,
                'retire_keys': [['600228.SH', int(d)] for d in requirements['retire_keys_if_native_policy_accepted']],
                'old_stock_rows': original.num_rows, 'old_outside_window_rows': sum(d < first for d in old_dates),
                'new_inserted_keys': len(set(map(int, raw['trade_date'])) - old_dates),
                'unknown_null_counts': unknown, 'unavailable_derived_columns': ['ma120', 'ma250'],
                'prior_control_flow_evidence': 'Originalfailed line152 reached onlyafter bothrole boundaryasserts and firstfive backtest rawfieldchecks. Original13bindings +7savedproducts fixed; formula notrerun.',
                'existing_schema_policy_gate': owner.contract_schema_gate(backtest.schema, policy, 'backtest'),
                'field_completeness': 'CANNOT_CONFIRM_FULL_SCHEMA; unavailable definitions remainnull; oldnoncomputed samekey values carried by originalfrozen helper'}
            save(stage / 'legacy_backtest_FEATURE_RECEIPT.json', backtest_role)
            save(stage / 'legacy_selector_FEATURE_RECEIPT.json', old_selector)
            context = oldstage / 'full_history_context.day'; data = context.read_bytes()
            context_first = struct.unpack_from('<I', data, 0)[0]
            receipt = {'execution_id': E, 'phase': 'complete_features', 'status': 'SAVED_RAW_DEFINED_FORMULA_PRODUCTS_COMPLETED_WITH_EXPLICIT_FIELD_GAPS',
                 'full_context_rows': len(data)//32, 'context_first_date': context_first, 'context_last_date': last,
                 'context_path': str(context), 'context_sha256': sha(context), 'emitted_first_date': first,
                 'emitted_last_date': last, 'emitted_rows': backtest.num_rows,
                 'prior_formula_and_selector_reused': True, 'formula_calls_this_execution': 0,
                 'critical_gate_evidence': 'Originalsource reached line152 after fullchain/critical asserts; savedselectorreceipt and bothrepairtables frozen; no numericalgate detail invented.',
                 'roles': {'legacy_selector': old_selector, 'legacy_backtest': backtest_role},
                 'elapsed_seconds': time.monotonic()-began, 'process_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                 'network_calls': 0, 'authority_writes': 0, 'pointer_writes': 0, 'full_schema_ready': False}
            save(stage / 'FEATURES_RECEIPT.json', receipt)
    result = stage / ('FEATURES_RECEIPT.json' if phase == 'complete_features' else 'PANELS_RECEIPT.json')
    print(json.dumps({'execution_id': E, 'phase': phase, 'receipt_path': str(result), 'sha256': sha(result)}))

if __name__ == '__main__': main()
