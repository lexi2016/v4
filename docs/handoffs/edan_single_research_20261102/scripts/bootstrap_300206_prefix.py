"""Bounded one-stock orchestration of the existing QFQ authority; no publish."""
from pathlib import Path
import json
import math
import sys
import time

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from ops import research_panel_qfq as q
from ops.junda_feedback_candidate import same

ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent
CODE = '300206.SZ'
TARGET = 20261030
PRIOR = PARENT / 'n_hold_score_integration_20261102_r1/SOURCE_GATE_N_R2.json'
READY = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_readiness.json')

def ref(path):
    return {'path':str(path), 'sha256':q.sha(path)}

def record(path, obj):
    if path.exists():
        raise RuntimeError('IMMUTABLE_OUTPUT_EXISTS:' + str(path))
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n')
    return ref(path)

started = time.monotonic()
frozen = json.loads((PARENT / 'FROZEN_BASELINE.json').read_text())
gate = json.loads(PRIOR.read_text())
assert gate['status'] == 'PASS_RELOCATED_SOURCE_GATE'
snapshot_ref = frozen['roles']['selector']['contract']['adjustment_snapshot']
snapshot_path = q._source(snapshot_ref, owner='single stock adjustment snapshot')
snapshot = json.loads(snapshot_path.read_text())
assert q.canonical_sha(snapshot) == gate['canonical_input_sha256']
assert CODE in snapshot['symbols'] and CODE not in snapshot['quarantine_symbols']
refs = json.loads(READY.read_text())['code_refs']
for item in refs:
    assert q.sha(item['path']) == item['sha256']
driver, formula, contract = [Path(item['path']) for item in refs]
driver_obj, _ = q.authorities(driver, formula)
identity = q.generation_identity(snapshot, driver, formula, contract, gate['relocation_ref'])
identity.update(turnover_input_sha256=frozen['roles']['selector']['contract']['turnover_input_sha256'],
                confirmed_gap_snapshot_file_sha256=snapshot_ref['sha256'], **q._n_sha256s())
baseline = {role:item['panel_sha256'] for role, item in frozen['roles'].items()}
tables, inputs = {}, {}
for role, info in frozen['roles'].items():
    path = Path(info['panel'])
    expected_stat = (info['size_bytes'], info['mtime_ns'], info['inode'])
    s = path.stat()
    assert (s.st_size, s.st_mtime_ns, s.st_ino) == expected_stat
    original = pq.read_table(path, filters=[('ts_code', '=', CODE)])
    volume = 'volume' if role == 'selector' else 'vol'
    frame = original.select(['ts_code','trade_date','open','high','low','close',volume,'pre_close','pct_chg']).to_pandas().rename(columns={volume:'vol'})
    frame['trade_date'] = pd.to_numeric(frame.trade_date).astype(int)
    assert frame.trade_date.is_monotonic_increasing and not frame.trade_date.duplicated().any()
    assert len(frame) and set(frame.ts_code) == {CODE}
    tables[role], inputs[role] = original, frame
    s = path.stat()
    assert (s.st_size, s.st_mtime_ns, s.st_ino) == expected_stat
left, right = inputs['selector'], inputs['backtest']
assert left.trade_date.equals(right.trade_date)
for name in ['open','high','low','close','vol','pre_close','pct_chg']:
    assert ((left[name] == right[name]) | (left[name].isna() & right[name].isna())).all(), name
item = snapshot['symbols'][CODE]
expected = int(item.get('compute_start_date') or item['history_start_date'])
assert int(left.trade_date.iloc[0]) == expected and int(left.trade_date.iloc[-1]) == TARGET
parts = ROOT / 'prefix_checkpoints'
parts.mkdir(exist_ok=True)
print('KB_PREFIX_START', CODE, len(left), flush=True)
q._kb_seed_checkpoint(CODE, left, item, expected, TARGET, identity, baseline, parts, driver_obj)
base = {role:q._kb_overlay_retained(table, q.kb_schema(table.schema), parts) for role,table in tables.items()}
data = base['selector'].to_pandas()
source_generation = frozen['roles']['selector']['contract']['generation_id']
print('KB_N_START', flush=True)
n_rows, n_checkpoint = q._single_n_daily(CODE, data, identity, source_generation)
data = q._single_feedback_daily(CODE, data, n_rows)
data = q._single_action_daily(CODE, data)
data = q._single_yidong_daily(CODE, data)
fingerprint = q.canonical_sha({'kind':'EDAN_QFQ_SINGLE_GAP_V1', 'source_generation':source_generation,
                              'baseline':baseline, 'snapshot':snapshot_ref, 'identity':identity})
print('KB_GAP_START', flush=True)
data, sidecar = q._single_gap_daily(CODE, data, identity, parts, fingerprint, source_generation, n_rows)
assert len(data) == len(left) == len(n_rows)

all_fields = q.SINGLE_FEEDBACK_FIELDS | q.SINGLE_ACTION_FIELDS | q.SINGLE_YIDONG_FIELDS | q.SINGLE_GAP_FIELDS
def field_type(name):
    if name in q.SINGLE_FEEDBACK_FIELDS:
        return (pa.string() if name.endswith('_reason') or name == 'kb_hold_score_status' else
                pa.int8() if name in {'kb_hold_score','kb_hold_score_min','kb_hold_score_max'} else
                pa.float64() if name in {'kb_hold_bbi','kb_hold_k','kb_hold_d'} else pa.bool_())
    if name in q.SINGLE_ACTION_FIELDS:
        return pa.string()
    kind = (q.SINGLE_YIDONG_FIELD_TYPES if name in q.SINGLE_YIDONG_FIELDS else q.SINGLE_GAP_FIELD_TYPES)[name]
    return {'string':pa.string(), 'bool':pa.bool_(), 'double':pa.float64(),
            'int8':pa.int8(), 'int32':pa.int32(), 'int64':pa.int64()}[kind]

outputs = {}
for role, original in tables.items():
    output = base[role]
    rebuild = pa.array(data['kb_rebuild'], type=pa.bool_(), from_pandas=True)
    output = output.set_column(output.schema.get_field_index('kb_rebuild'), pa.field('kb_rebuild', pa.bool_(), nullable=True), rebuild)
    for name in sorted(all_fields):
        assert name not in output.column_names, name
        typ = field_type(name)
        output = output.append_column(pa.field(name, typ, nullable=True), pa.array(data[name], type=typ, from_pandas=True))
    target = ROOT / ('EDAN_' + role.upper() + '_INTERIM_R1.parquet')
    if target.exists(): raise RuntimeError('IMMUTABLE_OUTPUT_EXISTS:' + str(target))
    pq.write_table(output, target, compression='zstd')
    readback = pq.read_table(target)
    for name in original.column_names:
        assert same(original[name], readback[name]), (role, name)
    outputs[role] = {**ref(target), 'rows':len(readback), 'columns':len(readback.column_names), 'original_columns_unchanged':True}

n_values = ROOT / 'EDAN_N_VALUES_R1.parquet'
if n_values.exists(): raise RuntimeError('IMMUTABLE_OUTPUT_EXISTS:' + str(n_values))
rows = [{'ts_code':r['ts_code'], 'trade_date':str(r['trade_date']),
         'kb_hold_trend_up':r['kb_hold_trend_up'], 'kb_hold_trend_up_reason':r['kb_hold_trend_up_reason'],
         'kb_n_structure_json':json.dumps(r['kb_n_structure'],ensure_ascii=False,sort_keys=True,separators=(',',':'))}
        for r in n_rows]
pq.write_table(pa.Table.from_pylist(rows), n_values, compression='zstd')
n_checkpoint_ref = record(ROOT / 'EDAN_N_CHECKPOINT_R1.json', n_checkpoint)
last_names = ['trade_date','kb_hold_close_up','kb_hold_above_bbi','kb_hold_volume_ok','kb_hold_trend_up',
              'kb_hold_j_not_dead','kb_hold_score','kb_hold_score_min','kb_hold_score_max','kb_hold_score_status']
last = data[last_names].tail(1).to_dict('records')[0]
for k,v in list(last.items()):
    if pd.isna(v): last[k] = None
    elif hasattr(v, 'item'): last[k] = v.item()
receipt = {'schema':'v4.edan_single_prefix_interim.v1', 'status':'ISOLATED_INTERMEDIATE_PENDING_SOURCE_GATE_AND_REVIEW',
           'symbol':CODE, 'asof':TARGET, 'source_generation':source_generation, 'snapshot':snapshot_ref,
           'prior_source_gate':ref(PRIOR), 'baseline_panel_sha256':baseline, 'identity':identity,
           'rows':len(data), 'first_date':expected, 'last_date':TARGET, 'outputs':outputs,
           'gap_sidecar':sidecar, 'n_values':ref(n_values), 'n_checkpoint':n_checkpoint_ref,
           'last_score':last, 'elapsed_seconds':round(time.monotonic()-started,2), **q.FLAGS}
result = record(ROOT / 'EDAN_PREFIX_INTERIM_R1.json', receipt)
print(json.dumps({'status':receipt['status'], 'receipt':result, 'outputs':outputs,
                  'last_score':last, 'seconds':receipt['elapsed_seconds']}, ensure_ascii=False), flush=True)
