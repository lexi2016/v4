"""One registered formal001210/native bridge; reuse existing native255 vectors."""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import resource
import traceback


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stat(path):
    s = Path(path).stat()
    return dict(inode=s.st_ino, mtime_ns=s.st_mtime_ns, size_bytes=s.st_size)


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def require(value, reason):
    if not value:
        raise ValueError(reason)


def load(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def scalar(value):
    value = float(value)
    return value if math.isfinite(value) else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', required=True, type=Path)
    args = parser.parse_args()
    cfg = json.loads(args.contract.read_text())
    start = json.loads(Path(cfg['start_receipt_path']).read_text())
    require(start['event_type'] == 'RUN_STARTED' and start['execution_id'] == cfg['execution_id']
            and start['contract_sha256'] == sha(args.contract) and start['code_sha256'] == sha(__file__), 'REAL_START_IDENTITY')
    require(Path(sys.executable).resolve() == Path(cfg['python_executable']).resolve(), 'PYTHON_IDENTITY')
    out = Path(cfg['output_path'])
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    result = dict(execution_id=cfg['execution_id'], status='RUNNING', formal_formula_evaluations=0,
                  native_formula_evaluations=0, start_event_sha256=start['event_sha256'],
                  started_at=datetime.now(timezone.utc).isoformat(), code_sha256=sha(__file__),
                  contract_sha256=sha(args.contract), panel_full_hash_recomputed=False,
                  research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    try:
        for ref in cfg['input_bindings']:
            require(sha(ref['path']) == ref['sha256'], 'FROZEN_INPUT_DRIFT:' + ref['path'])
        panel = cfg['formal_panel']
        require(stat(panel['path']) == panel['stat'], 'FORMAL_PHYSICAL_PANEL_DRIFT')
        binding = json.loads(Path(cfg['formal_input_binding']['path']).read_text())
        require(binding['selector']['target_path'] == panel['path']
                and binding['selector']['target_stat'] == panel['stat'], 'FORMAL_BINDING_TARGET_MISMATCH')
        helper = load(cfg['a3_source']['path'], 'formal001210_prior_a3_pure')
        owner = load(cfg['native_owner']['path'], 'formal001210_frozen_native_owner')
        evaluator = load(cfg['evaluator']['path'], 'formal001210_original255')
        import numpy as np
        import pyarrow as pa
        import pyarrow.dataset as ds
        import pyarrow.parquet as pq
        dataset = ds.dataset(panel['path'], format='parquet')
        fields = ['ts_code', 'trade_date', *helper.RAW.values()]
        require({k: str(dataset.schema.field(k).type) for k in fields} == cfg['raw_schema'], 'FORMAL_RAW_SCHEMA_DRIFT')
        predicate = ((ds.field('ts_code') == cfg['ts_code']) & (ds.field('trade_date') >= cfg['history_start'])
                     & (ds.field('trade_date') <= cfg['signal_date']))
        table = dataset.to_table(columns=fields, filter=predicate)
        require(0 < table.num_rows <= cfg['max_rows'], 'FORMAL_ROW_BOUND')
        frame = table.to_pandas()
        frame['date8'] = frame['trade_date'].astype(str).str.replace('-', '', regex=False)
        require(not frame.duplicated(['ts_code', 'date8']).any(), 'FORMAL_DUPLICATE_KEYS')
        frame = frame.sort_values(['ts_code', 'date8']).reset_index(drop=True)
        require(set(frame['ts_code']) == {cfg['ts_code']} and frame.iloc[-1]['date8'] == cfg['signal_date'], 'FORMAL_DATE_OR_CODE_SCOPE')
        require(stat(panel['path']) == panel['stat'], 'FORMAL_PANEL_CHANGED_DURING_READ')
        pq.write_table(pa.Table.from_pandas(frame[fields], preserve_index=False), out / 'FORMAL001210_SIX_RAW_INPUT.parquet')
        formal_dates = frame['date8'].tolist()
        formal_raw = helper.frame_raw(frame)
        a3_cfg = json.loads(Path(cfg['a3_contract']['path']).read_text())
        native_frame, _ = helper.native_frame(cfg['native_target'], 'mac', a3_cfg, owner)
        native_jan = native_frame.loc[native_frame['date8'] >= cfg['history_start']].reset_index(drop=True)
        native_dates = native_jan['date8'].tolist()
        native_raw = helper.frame_raw(native_jan)
        prior_helper = load(cfg['prior_helper']['path'], 'formal001210_prior_fingerprints')
        native_identity = json.loads(Path(cfg['native_input_identity']['path']).read_text())
        current_native_fingerprints = prior_helper.raw_fingerprints(native_raw, native_dates)
        require(current_native_fingerprints == native_identity['raw_fingerprints'], 'PRIOR_NATIVE_ARRAY_IDENTITY_DRIFT')
        require(native_dates == json.loads(Path(cfg['native_dates']['path']).read_text()), 'PRIOR_NATIVE_DATES_DRIFT')
        with np.load(cfg['native_vectors']['path'], allow_pickle=False) as stored:
            native_trace = {key: stored[key] for key in stored.files}
        require(len(native_trace) == 255 and all(v.shape == (len(native_jan),) for v in native_trace.values()), 'PRIOR_NATIVE_VECTOR_SHAPE')
        require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss < cfg['max_rss_bytes'], 'RSS_BOUND')
        expected = None
        # Filter the immutable existing trace by its exact code token; never
        # decode numerical vectors belonging to any other stock.
        with Path(cfg['accepted_formal_trace']['path']).open() as stream:
            for line in stream:
                if '"ts_code": "001210.SZ"' in line or '"ts_code":"001210.SZ"' in line:
                    row = json.loads(line)
                    if row['ts_code'] == cfg['ts_code']:
                        require(expected is None, 'AMBIGUOUS_FORMAL_TRACE')
                        expected = row
        require(expected is not None and expected['signal_date'] == cfg['signal_date'], 'FORMAL_TRACE_MISSING_OR_DATE')
        require(expected['observed_history_bars'] == len(frame), 'FORMAL_HISTORY_COUNT_DRIFT')
        formal_fingerprints = prior_helper.raw_fingerprints(formal_raw, formal_dates)
        require(formal_dates == native_dates, 'FORMAL_NATIVE_DATE_KEYS_DIFFER')
        rows, dtypes, counts = [], {}, {}
        for key, field in helper.RAW.items():
            left, right = formal_raw[key], native_raw[key]
            dtypes[field] = dict(formal=str(left.dtype), native=str(right.dtype), equal=left.dtype == right.dtype)
            differences = np.flatnonzero(left != right)
            counts[field] = len(differences)
            for i in differences:
                a, b = left[i].item(), right[i].item()
                rows.append(dict(date=formal_dates[i], field=field, formal_value=a, native_value=b,
                    formal_hex=float(a).hex() if isinstance(a, float) else str(a),
                    native_hex=float(b).hex() if isinstance(b, float) else str(b)))
        if rows:
            with (out / 'FORMAL_NATIVE_RAW_DIFFERENCES.csv').open('x', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        save(out / 'RAW_INPUT_BRIDGE.json', dict(dates_identical=True, rows=len(formal_dates),
             formal_fingerprints=formal_fingerprints, native_fingerprints=current_native_fingerprints,
             differences_by_field=counts, dtypes=dtypes, any_dtype_coercion=False,
             formal_panel_identity=panel, native_source_identity=cfg['native_target']['mac'],
             date_first=formal_dates[0], date_last=formal_dates[-1],
             source_projection_policy='Originalowner/schema values retained; no tolerance, scaling, rounding or replacement'))
        require(all(x['equal'] for x in dtypes.values()), 'DTYPE_MISMATCH_REQUIRES_CONTROLLER_NO_COERCION')
        program = evaluator.compile_original(cfg['formula']['path'])
        result['formal_formula_evaluations'] += 1
        formal_trace = evaluator.evaluate(program, formal_raw, cfg['ts_code'])
        require(len(formal_trace) == 255, 'FORMAL_255_COUNT')
        np.savez_compressed(out / 'FORMAL_ALL255_VECTORS.npz', **formal_trace)
        latest = {key: scalar(value[-1]) for key, value in formal_trace.items()}
        save(out / 'FORMAL_LATEST255.json', latest)
        parity = {key: latest[key] == expected['all_255_assignments'][key] for key in formal_trace}
        save(out / 'ACCEPTED_FORMAL255_PARITY.json', dict(all255_exact=all(parity.values()),
             different_assignments=[key for key, equal in parity.items() if not equal],
             expected_selected=expected['selected'], observed_selected=bool(latest['XG']),
             expected_history_bars=expected['observed_history_bars'], observed_history_bars=len(frame)))
        require(all(parity.values()) and bool(latest['XG']) == expected['selected'], 'ACCEPTED_FORMAL255_REPRODUCTION_DRIFT')
        formal_reasons, native_reasons = helper.terminal_reasons(formal_trace), helper.terminal_reasons(native_trace)
        changes = {key: dict(formal=latest[key], native=scalar(native_trace[key][-1]))
                   for key in formal_trace if latest[key] != scalar(native_trace[key][-1])}
        save(out / 'FORMAL_NATIVE_LATEST255_DIFFERENCES.json', changes)
        save(out / 'FORMAL_NATIVE_LEAF_REASONS.json', dict(formal=formal_reasons, native=native_reasons,
             formal_BKTURN=prior_helper.branch_facts(formal_trace, formal_raw, formal_dates),
             native_BKTURN=prior_helper.branch_facts(native_trace, native_raw, native_dates)))
        result.update(status='FORMAL001210_ACCEPTED255_REPRODUCED_NATIVE_BRIDGE_COMPLETE',
             accepted_formal255_exact=True, formal_selected=formal_reasons['selected'],
             reused_native_selected=native_reasons['selected'], outcome_flip=formal_reasons['selected'] != native_reasons['selected'],
             formal_gate_values=formal_reasons['recorded_values'], native_gate_values=native_reasons['recorded_values'],
             raw_different_cells_by_field=counts, raw_dtypes=dtypes,
             different_latest_assignments=list(changes), exact_native_array_identity_reused=True,
             discrepancy_classification='BOUND_FORMAL_RAW_VALUES_DIFFER_FROM_ACCEPTED_NATIVE_AT_IDENTICAL_DTYPES_AND_DATES; cause/repair requires controller',
             panel_bug_declared=False, repair_performed=False,
             actual_windows_engine='CANNOT_CONFIRM_NOT_EXECUTED')
        require(stat(panel['path']) == panel['stat'], 'FORMAL_PANEL_CHANGED_AT_END')
    except BaseException as exc:
        result.update(status='BRIDGE_STOPPED', error_type=type(exc).__name__, error=str(exc))
        (out / 'exception.txt').write_text(traceback.format_exc())
    result.update(ended_at=datetime.now(timezone.utc).isoformat(),
                  peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  authority_writes=0, network_calls=0, sdk_calls=0,
                  artifacts={p.name: sha(p) for p in out.iterdir() if p.is_file()})
    save(out / 'BRIDGE_RECEIPT.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ['artifacts']}, sort_keys=True))
    return 0 if result['status'] == 'FORMAL001210_ACCEPTED255_REPRODUCED_NATIVE_BRIDGE_COMPLETE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
