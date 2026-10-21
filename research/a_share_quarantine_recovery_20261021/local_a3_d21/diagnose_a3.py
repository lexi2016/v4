"""Registered three-name source/history counterfactual, original evaluator only.

No network, Windows SDK, authority publication or formula implementation changes.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import struct
import time
import traceback

RAW = {'O': 'open', 'H': 'high', 'L': 'low', 'C': 'close',
       'VOL': 'volume', 'AMOUNT': 'amount'}
SAFETY = dict(research_only=True, production_allowed=False,
              buy_gate_updated=False, orders_sent=False)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def scalar(value):
    value = float(value)
    return value if math.isfinite(value) else None


def require(value, reason):
    if not value:
        raise ValueError(reason)


def resource_gate(cfg):
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    require(peak < cfg['max_process_rss_bytes'], 'RSS_BOUND')
    return peak


def native_frame(target, origin, cfg, owner):
    """Keep the frozen original owner's native units, values and dtypes."""
    import numpy as np
    ref = target[origin]
    path = Path(ref['path'])
    payload = path.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == ref['sha256'], 'NATIVE_SHA_DRIFT:' + origin)
    require(payload and len(payload) % 32 == 0, 'NATIVE_FRAMING:' + origin)
    count = len(payload) // 32
    require(count <= cfg['max_rows_per_source'], 'NATIVE_ROW_BOUND:' + origin)
    dates = [struct.unpack_from('<I', payload, i)[0] for i in range(0, len(payload), 32)]
    for date in dates:
        datetime.strptime(str(date), '%Y%m%d')
    require(all(a < b for a, b in zip(dates, dates[1:])), 'NATIVE_ORDER_OR_DUPLICATE:' + origin)
    require(dates[-1] == int(cfg['signal_date']), 'NATIVE_EXACT_D21_TAIL:' + origin)
    frame = owner.read_day_tail(target['ts_code'], path, tail_records=count)
    require(len(frame) == count, 'OWNER_DROPPED_NATIVE_ROWS:' + origin)
    require(frame['trade_date'].tolist() == dates, 'OWNER_DATE_ALIGNMENT:' + origin)
    # Same mapping/date preparation as the frozen original R3 replay.
    frame['date8'] = frame['trade_date'].astype(str).str.replace('-', '', regex=False)
    require(not frame.duplicated(['ts_code', 'date8']).any(), 'DUPLICATE_FRAME_KEYS')
    frame = frame.sort_values(['ts_code', 'date8']).reset_index(drop=True)
    require(np.isfinite(frame[list(RAW.values())].to_numpy()).all(), 'NONFINITE_NATIVE')
    require((frame['date8'] <= cfg['signal_date']).all(), 'POST_SIGNAL_NATIVE_ROW')
    return frame, payload


def frame_raw(frame):
    return {key: frame[column].to_numpy(copy=True) for key, column in RAW.items()}


def exact_equal(left, right):
    import numpy as np
    return (left.dtype == right.dtype and left.shape == right.shape
            and np.array_equal(left, right, equal_nan=True)
            and left.tobytes() == right.tobytes())


def terminal_reasons(trace):
    val = lambda name: float(trace[name][-1])
    truth = lambda name: math.isfinite(val(name)) and val(name) != 0
    b2_parts = {'RISK0_lt45': val('RISK0') < 45,
                'FRESH_ge70': val('FRESH') >= 70, 'FCON': truth('FCON')}
    same_relief = (truth('STABLE') or (val('LINESCR') >= 10 and val('HEALTH') >= 4
                   and val('UPSH') <= 6 and val('DWHITE') <= 10) or truth('VOLSTB'))
    b3_parts = {'NOT_B2ROLE': not truth('B2ROLE'), 'RISK0_lt50': val('RISK0') < 50,
                'CONT0_ge70': val('CONT0') >= 70, 'CCON': truth('CCON'),
                'NOT_MULTI_AND_RELIEF': not (truth('MULTI') and same_relief)}
    fcon_parts = {'ROUTEH': truth('ROUTEH'),
                  'DIRECTB_or_B1PRE_ge4': truth('DIRECTB') or val('B1PRE') >= 4,
                  'B2CNT0_or_DAYB2_gt20_or_RESET0': val('B2CNT') == 0 or val('DAYB2') > 20 or truth('RESET0')}
    require(all(b2_parts.values()) == truth('B2ROLE'), 'B2ROLE_REASON_PARITY')
    require(all(b3_parts.values()) == truth('B3ROLE'), 'B3ROLE_REASON_PARITY')
    require(all(fcon_parts.values()) == truth('FCON'), 'FCON_REASON_PARITY')
    require((truth('BRICKPOOL') or truth('PRIMARY') or truth('SECONDARY')) == truth('ENTRYPOOL'), 'ENTRY_REASON_PARITY')
    reconstructed = truth('ENTRYPOOL') and (truth('B2ROLE') or (truth('B3ROLE') and val('RISK0') < 45))
    require(reconstructed == truth('XG'), 'XG_REASON_PARITY')
    return {'selected': truth('XG'), 'ENTRYPOOL': truth('ENTRYPOOL'),
            'ENTRYPOOL_terms': {k: truth(k) for k in ('BRICKPOOL', 'PRIMARY', 'SECONDARY')},
            'B2ROLE_terms': b2_parts, 'B2ROLE_failed_terms': [k for k, v in b2_parts.items() if not v],
            'B3ROLE_terms': b3_parts, 'B3ROLE_failed_terms': [k for k, v in b3_parts.items() if not v],
            'FCON_terms': fcon_parts, 'terminal_RISK0_lt45': val('RISK0') < 45,
            'recorded_values': {k: scalar(trace[k][-1]) for k in
                ('ENTRYPOOL', 'FRESH', 'CONT0', 'RISK0', 'B2ROLE', 'B3ROLE', 'FCON', 'CCON',
                 'MULTI', 'STABLE', 'LINESCR', 'HEALTH', 'UPSH', 'DWHITE', 'VOLSTB',
                 'ROUTEH', 'DIRECTB', 'B1PRE', 'B2CNT', 'DAYB2', 'RESET0', 'XG')},
            'original_thresholds_unchanged': True}


def source_compare(mac, windows, stage):
    """Exact comparison only; never normalize or decide which source wins."""
    mm = {str(row['date8']): row for row in mac.to_dict('records')}
    wm = {str(row['date8']): row for row in windows.to_dict('records')}
    overlap = sorted(mm.keys() & wm.keys())
    rows, counts = [], {key: 0 for key in RAW.values()}
    for date in overlap:
        for field in RAW.values():
            left, right = mm[date][field], wm[date][field]
            if left != right:
                counts[field] += 1
                rows.append(dict(date=date, field=field, mac_value=left, windows_value=right,
                                 comparison='EXACT_NO_ROUNDING_OR_TOLERANCE'))
    if rows:
        with (stage / 'SOURCE_FIELD_DIFFERENCES.csv').open('x', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    result = dict(mac_only_dates=sorted(mm.keys() - wm.keys()), windows_only_dates=sorted(wm.keys() - mm.keys()),
                  common_dates=len(overlap), different_cells_by_field=counts,
                  different_dates=len({r['date'] for r in rows}),
                  latest_date_equal=mm[max(mm)] == wm[max(wm)] if max(mm) == max(wm) else False,
                  amount_volume_units='Frozen owner raw stored amount and raw stored volume; no conversion',
                  source_vintage_or_precision_cause='CANNOT_CONFIRM_FROM_DIFFERENCES_ALONE')
    save(stage / 'SOURCE_PARITY.json', result)
    return result


def stock(cfg, target, root, owner, evaluator, program, prior_helper):
    import numpy as np
    stage = root / target['ts_code']
    stage.mkdir(mode=0o700)
    result = dict(ts_code=target['ts_code'], status='RUNNING', formula_evaluations=0,
                  started_at=datetime.now(timezone.utc).isoformat(), **SAFETY)
    started = time.monotonic()
    try:
        mac, mac_bytes = native_frame(target, 'mac', cfg, owner)
        windows, windows_bytes = native_frame(target, 'windows', cfg, owner)
        mac_jan = mac.loc[mac['date8'] >= cfg['history_start']].reset_index(drop=True)
        windows_jan = windows.loc[windows['date8'] >= cfg['history_start']].reset_index(drop=True)
        require(not mac_jan.empty and not windows_jan.empty, 'EMPTY_JAN_WINDOW')
        cut = len(windows) - len(windows_jan)
        full_raw, jan_raw = frame_raw(windows), frame_raw(windows_jan)
        require(windows['date8'].tolist()[cut:] == windows_jan['date8'].tolist(), 'PREFIX_DATE_PARITY')
        require(all(exact_equal(full_raw[k][cut:], jan_raw[k]) for k in RAW), 'PREFIX_OHLCVA_BYTE_PARITY')
        jan_native_bytes = b''.join(windows_bytes[i:i+32] for i in range(0, len(windows_bytes), 32)
                                   if struct.unpack_from('<I', windows_bytes, i)[0] >= int(cfg['history_start']))
        require(jan_native_bytes == windows_bytes[cut*32:], 'PREFIX_NATIVE_ROW_BYTE_PARITY')
        prefix = dict(prefix_rows=cut, full_rows=len(windows), jan_rows=len(windows_jan),
                      same_source_sha256=target['windows']['sha256'],
                      jan_native_rows_sha256=hashlib.sha256(jan_native_bytes).hexdigest(),
                      suffix_raw_arrays_and_dates_byte_identical=True,
                      fixed_history_windows=[cfg['history_start'], str(windows.iloc[0]['date8'])],
                      one_variable='WINDOWS_NATIVE_HISTORY_PREFIX_LENGTH_ONLY')
        save(stage / 'PREFIX_IDENTITY.json', prefix)
        parity = source_compare(mac_jan, windows_jan, stage)
        scenarios = {'mac_jan': mac_jan, 'windows_jan': windows_jan, 'windows_full': windows}
        traces, summaries = {}, {}
        for name, frame in scenarios.items():
            resource_gate(cfg)
            require(time.monotonic()-started < cfg['max_stock_wall_seconds'], 'STOCK_TIME_BOUND')
            raw = frame_raw(frame)
            dates = frame['date8'].tolist()
            fingerprints = prior_helper.raw_fingerprints(raw, dates)
            result['formula_evaluations'] += 1
            trace = evaluator.evaluate(program, raw, target['ts_code'])
            require(len(trace) == 255, 'NOT_ALL255')
            require(all(value.shape == (len(frame),) for value in trace.values()), 'VECTOR_SHAPE')
            require(math.isfinite(float(trace['XG'][-1])), 'NONFINITE_XG')
            np.savez_compressed(stage / (name + '_ALL255_VECTORS.npz'), **trace)
            save(stage / (name + '_DATES.json'), dates)
            latest = {k: {'D': scalar(v[-1]), 'D_minus_1': scalar(v[-2])} for k, v in trace.items()}
            save(stage / (name + '_LATEST255.json'), latest)
            reasons = terminal_reasons(trace)
            save(stage / (name + '_LEAF_REASONS.json'), dict(terminal=reasons,
                 BKTURN=prior_helper.branch_facts(trace, raw, dates),
                 dependencies={key: sorted(evaluator.names_used(node)) for key, node in program}))
            summary = dict(rows=len(frame), first_date=dates[0], last_date=dates[-1],
                           selected=reasons['selected'], latest_gate_values=reasons['recorded_values'],
                           raw_fingerprints=fingerprints, dtypes={k: str(v.dtype) for k, v in raw.items()},
                           formal_panel_baseline_reused=False,
                           reason_no_baseline_reuse='No existing full-vector receipt with identical native raw-array identity; bounded fresh original evaluation',
                           price_basis='RAW_NATIVE_UNADJUSTED_NO_XDXR')
            summaries[name] = summary
            traces[name] = trace
            save(stage / (name + '_INPUT_IDENTITY.json'), summary)
        differences = {}
        for label, left_name, right_name, offset in [
            ('windows_history_prefix', 'windows_jan', 'windows_full', cut),
            ('mac_vs_windows_same_jan', 'mac_jan', 'windows_jan', 0)]:
            left, right = traces[left_name], traces[right_name]
            d_changes = [key for key in left if scalar(left[key][-1]) != scalar(right[key][-1])]
            vector_changes = {}
            if scenarios[left_name]['date8'].tolist() == scenarios[right_name]['date8'].tolist()[offset:]:
                for key in left:
                    a, b = left[key], right[key][offset:]
                    equal = (a == b) | (np.isnan(a) & np.isnan(b))
                    if not equal.all():
                        vector_changes[key] = int((~equal).sum())
            differences[label] = dict(left=left_name, right=right_name,
                left_selected=summaries[left_name]['selected'], right_selected=summaries[right_name]['selected'],
                gate_flip=summaries[left_name]['selected'] != summaries[right_name]['selected'],
                latest_changed_assignments=d_changes, aligned_vector_changed_cells=vector_changes,
                latest_values={key: {'left': scalar(left[key][-1]), 'right': scalar(right[key][-1])} for key in d_changes})
        save(stage / 'FORMULA_DIFFERENCES.json', differences)
        result.update(status='LOCAL_ORIGINAL255_COUNTERFACTUAL_COMPLETE', scenarios=summaries,
                      source_parity=parity, prefix_identity=prefix, comparisons=differences,
                      actual_windows_engine_parity='CANNOT_CONFIRM_NOT_EXECUTED',
                      formal_selection_changed=False, raw_authority_mutations=0)
    except BaseException as exc:
        result.update(status='STOPPED', error_type=type(exc).__name__, error=str(exc))
        (stage / 'exception.txt').write_text(traceback.format_exc())
    result.update(ended_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-started,
                  peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  artifacts={p.name: sha(p) for p in sorted(stage.iterdir()) if p.is_file()})
    save(stage / 'STOCK_RECEIPT.json', result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', required=True, type=Path)
    parser.add_argument('--phase', required=True, choices=('canary', 'remaining'))
    args = parser.parse_args()
    cfg = json.loads(args.contract.read_text())
    require(Path(sys.executable).resolve() == Path(cfg['python_executable']).resolve(), 'PYTHON_IDENTITY')
    start = json.loads(Path(cfg['start_receipt_path']).read_text())
    require(start['execution_id'] == cfg['execution_id'] and start['event_type'] == 'RUN_STARTED'
            and start['contract_sha256'] == sha(args.contract)
            and start['code_sha256'] == sha(__file__), 'REAL_START_IDENTITY')
    root = Path(cfg['output_path'])
    if args.phase == 'canary':
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
    else:
        canary = json.loads((root / 'canary_RECEIPT.json').read_text())
        require(canary['safe_to_continue'], 'CANARY_NOT_SAFE')
    began = time.monotonic()
    receipt = dict(execution_id=cfg['execution_id'], phase=args.phase, formula_evaluations=0,
                   contract_sha256=sha(args.contract), code_sha256=sha(__file__),
                   start_event_sha256=start['event_sha256'], safe_to_continue=False,
                   stock_results=[], **SAFETY)
    try:
        # Actual input reads/hashes occur only after the verified official START.
        for ref in cfg['input_bindings']:
            require(sha(ref['path']) == ref['sha256'], 'FROZEN_INPUT_DRIFT:' + ref['path'])
        owner = load(cfg['native_owner']['path'], 'a3_frozen_native_owner')
        evaluator = load(cfg['evaluator']['path'], 'a3_frozen_original255')
        prior_helper = load(cfg['frame_helper']['path'], 'a3_prior_pure_helpers')
        program = evaluator.compile_original(cfg['formula']['path'])
        chosen = cfg['targets'][:1] if args.phase == 'canary' else cfg['targets'][1:]
        resource_gate(cfg)
        for target in chosen:
            one = stock(cfg, target, root, owner, evaluator, program, prior_helper)
            receipt['stock_results'].append(one)
            receipt['formula_evaluations'] += one['formula_evaluations']
            if one['status'] != 'LOCAL_ORIGINAL255_COUNTERFACTUAL_COMPLETE':
                break
        receipt['safe_to_continue'] = (len(receipt['stock_results']) == len(chosen)
            and all(r['status'] == 'LOCAL_ORIGINAL255_COUNTERFACTUAL_COMPLETE' for r in receipt['stock_results'])
            and resource_gate(cfg) < cfg['max_process_rss_bytes'])
        require(receipt['formula_evaluations'] <= (3 if args.phase == 'canary' else 6), 'FORMULA_CALL_BOUND')
    except BaseException as exc:
        receipt.update(error_type=type(exc).__name__, error=str(exc))
        (root / (args.phase + '_exception.txt')).write_text(traceback.format_exc())
    receipt.update(elapsed_seconds=time.monotonic()-began,
                   peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   authority_writes=0, network_calls=0, sdk_calls=0)
    save(root / (args.phase + '_RECEIPT.json'), receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k != 'stock_results'}, sort_keys=True))
    return 0 if receipt['safe_to_continue'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
