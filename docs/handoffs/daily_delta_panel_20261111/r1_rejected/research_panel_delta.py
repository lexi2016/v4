"""Incremental persistence inside the original QFQ owner and publication lock.

The pinned full-prefix engine remains the numerical oracle. Only changed rows
are persisted. No new collector, pointer, source authority or periodic worker.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

from ops import research_panel_logical as logical

PROJECTED = set(logical.DISPLAY) | {'raw_source_ref_sha256'}


def key_index(path):
    file = logical.physical.ParquetFile(path)
    index = {}
    for group in range(file.num_row_groups):
        for code in pc.unique(file.read_row_group(group, columns=['ts_code'])['ts_code']).to_pylist():
            index.setdefault(code, []).append(group)
    return index


def raw_identity(frame):
    fields = ['trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount']
    # Canonical numeric bytes, not object-array pointers or global run identity.
    values = frame[fields].to_numpy(dtype='<f8', copy=True)
    return hashlib.sha256(values.tobytes()).hexdigest()


def factor_state(item):
    # Only the four inputs actually consumed by the unchanged affine QFQ math.
    # Receipt/time/source SHA differences remain real generation provenance.
    return [(int(e['ex_date']),float(e['a']),float(e['b']),float(e['volume_a'])) for e in item['events']]


def changed_rows(old, fresh):
    """Exact original output comparison; NULL and NaN remain distinct in Arrow."""
    previous = {(code,int(day)): i for i, (code,day) in enumerate(zip(old['ts_code'].to_pylist(),old['trade_date'].to_pylist()))}
    fresh_dates = [(code,int(day)) for code,day in zip(fresh['ts_code'].to_pylist(),fresh['trade_date'].to_pylist())]
    if len(set(fresh_dates)) != len(fresh_dates) or not set(previous).issubset(fresh_dates):
        raise ValueError('DELTA_OLD_KEYS_LOST_OR_DUPLICATE')
    fields = [name for name in fresh.column_names if name not in PROJECTED]
    keep, positions, old_positions = [], [], []
    for position, day in enumerate(fresh_dates):
        before = previous.get(day)
        if before is None:
            keep.append(position); continue
        positions.append(position); old_positions.append(before)
    if positions:
        left = old.take(pa.array(old_positions, type=pa.int64()))
        right = fresh.take(pa.array(positions, type=pa.int64()))
        changed = np.zeros(len(positions), dtype=bool)
        for name in fields:
            a, b = left[name], right[name]
            equal = pc.or_(pc.fill_null(pc.equal(a, b), False), pc.and_(pc.is_null(a), pc.is_null(b)))
            if pa.types.is_floating(a.type):
                equal = pc.or_(equal, pc.fill_null(pc.and_(pc.is_nan(a), pc.is_nan(b)), False))
            changed |= np.logical_not(equal.to_numpy(zero_copy_only=False))
        keep.extend(position for position, different in zip(positions, changed) if different)
    return fresh.take(pa.array(sorted(keep), type=pa.int64()))


class _RawDriver:
    def __init__(self, driver):
        self.driver, self.cache = driver, {}
    def __getattr__(self, name):
        return getattr(self.driver, name)
    def read_day_tail(self, code, path, tail_records):
        key = str(path), tail_records
        if key not in self.cache:
            self.cache[key] = self.driver.read_day_tail(code, path, tail_records=tail_records)
        return self.cache[key].copy()


def run_delta(q, c):
    try:
        return _run_delta(q, c)
    except BaseException as exc:
        q['_json'](c['run_dir']/'stage_status.json', dict(status='FAILED', error=str(exc),
            run_dir=str(c['run_dir']),target_date=c['target'],candidates={r:str(p)for r,p in c['candidates'].items()},
            storage_layout='ARROW_BLOCKS_V1', **c['meta']))
        raise
    finally:
        pool = c.pop('_delta_pool', None)
        if pool is not None:
            pool.shutdown(wait=True)


def _run_delta(q, c):
    """Called by run_daily_rebuild after its original source/identity checks."""
    target, snapshot, meta = c['target'], c['snapshot'], c['meta']
    currents, schemas, run = c['currents'], c['schemas'], c['run_dir']
    driver, data_root = c['driver'], c['data_root']
    q['_json'](run / 'stage_status.json', dict(status='RUNNING', stage='ORIGINAL_DELTA_STORAGE', **meta))
    old_snapshot = json.loads(q['_source'](next(iter(c['contracts'].values()))['adjustment_snapshot'],
                                         owner='delta original committed snapshot').read_text())
    prior = {}
    old_views = {}
    all_old = set().union(*c['old_symbols'].values())
    for role, path in currents.items():
        if logical.is_logical(path):
            original = logical.LogicalFile(path)
            prior[role] = list(original.blocks)
        else:
            old_views[role] = q['spool_current'](path, run / ('current_' + role + '_buckets'), c['baseline_hashes'][role])
            groups={group:codes for view in old_views[role].values() for group,codes in view.groups.items()}
            index={}
            for group,codes in groups.items():
                for code in codes:index.setdefault(code,[]).append(group)
            prior[role] = [logical.descriptor(path, sha256=c['baseline_hashes'][role], key_rows=index)]
    expected = set(snapshot['symbols'])
    ordered = sorted(all_old | expected)
    buckets = {i: [code for code in ordered if q['_bucket'](code) == i] for i in range(32)}
    deltas = {role: [] for role in currents}
    counts = {role: dict(panel_rows=0, target_date_symbols=0, old_key_conservation=True,
                        appended_rows=0, revised_rows=0) for role in currents}
    current_symbols = {role: set() for role in currents}
    quarantine = dict(snapshot.get('quarantine_symbols', {}))
    quarantine.update({code:dict(reason=c.get('legacy_policy',{}).get('reason','LEGACY_BASIS_UNKNOWN'),
        legacy_non_target=True,policy=snapshot.get('legacy_preservation_policy')) for code in c.get('legacy_codes',[])})
    classifications, resumed, logical_written, reused_bytes = {}, 0, 0, 0
    source_semantics = {key: meta[key] for key in ('driver_sha256','formula_sha256','user_formula_sha256','field_contract_sha256')}
    source_semantics['kernel_sha256'] = q['computation_kernel_sha'](Path(q['__file__']))
    for bucket, codes in buckets.items():
        frames = {}
        for role, path in currents.items():
            table = (old_views[role][bucket].read() if role in old_views and bucket in old_views[role]
                     else q['pq'].read_table(path, filters=[('ts_code', 'in', codes)]) if role not in old_views
                     else pa.Table.from_batches([], schema=schemas[role]))
            series=table['ts_code'].to_pandas()
            positions=series.groupby(series,sort=False).indices
            frames[role] = {code:table.take(pa.array(rows,type=pa.int64())) for code,rows in positions.items()}
        pool = q['ThreadPoolExecutor'](max_workers=c['workers'])
        c['_delta_pool'] = pool
        pending = {}
        remaining = iter(code for code in codes if code in expected)
        def submit_next():
            code = next(remaining, None)
            if code is not None:
                pending[code] = pool.submit(_prepare, q, c, code, frames, old_snapshot, schemas, source_semantics)
        for _ in range(c['workers'] * 2):
            submit_next()
        for code in codes:
            if code not in expected:
                for role in currents:
                    old = frames[role].get(code)
                    if old is not None and code not in quarantine:
                        counts[role]['panel_rows'] += len(old)
                continue
            try:
                prepared = pending.pop(code).result()
            except q['QfqGateError'] as exc:
                eligible=snapshot.get('original_quarantine_eligible',{})
                if code not in eligible: raise
                quarantine[code]=dict(reason=str(exc),original_status=eligible[code])
                classifications[code]='ORIGINAL_QUARANTINE_ELIGIBLE_FAILURE'
                submit_next()
                continue
            submit_next()
            item,kind,dependency,checkpoint,computed = (prepared[k] for k in ('item','kind','dependency','checkpoint','computed'))
            classifications[code] = kind
            if checkpoint.is_file():
                saved = json.loads(checkpoint.read_text())
                if saved['dependency'] != dependency or saved.get('classification')!=kind:
                    raise ValueError('DELTA_CHECKPOINT_IDENTITY')
                _validate_resume(q,c,code,dependency,saved,frames,schemas)
                for role, value in saved['roles'].items():
                    q['_source'](value['artifact'], owner='delta resume ' + code)
                    deltas[role].append(value['block'])
                    reused_bytes += Path(value['artifact']['path']).stat().st_size
                    for key in ('appended_rows','revised_rows'):
                        counts[role][key] += value[key]
                for role in currents:
                    counts[role]['panel_rows'] += saved['logical_rows'][role]
                    if saved['has_target'][role]:
                        current_symbols[role].add(code)
                resumed += 1
                continue
            record = dict(dependency=dependency, classification=kind, roles={}, logical_rows={}, has_target={})
            for role, schema in schemas.items():
                old = frames[role].get(code, pa.Table.from_batches([], schema=schema))
                if not len(old) and role not in item.get('publish_roles', []):
                    record['logical_rows'][role] = 0
                    record['has_target'][role] = False
                    continue
                if computed is None:
                    final_rows = len(old)
                    has_target = target in [int(x) for x in old['trade_date'].to_pylist()]
                    patch = None
                else:
                    rebuilt = computed
                    if not len(old) and c.get('history') is None and c.get('addition') is None and role in c.get('role_start',{}):
                        rebuilt = rebuilt.loc[rebuilt.trade_date.ge(c['role_start'][role])].copy()
                    frame = q['merge_rebuilt'](old.to_pandas(), rebuilt, role=role, driver=driver,
                                               history_extension=c['retained_history'] is not None)
                    frame = c['turnover'].apply_target(code, frame)
                    if role == 'selector' and frame.trade_date.eq(target).any():
                        gate = driver.validate_new_selector_rows(frame.loc[frame.trade_date.eq(target)], schema, target)
                        if gate['status'] != 'PASS':
                            raise ValueError('ORIGINAL_SELECTOR_FORMULA_GATE_FAILED:' + code)
                    fresh = q['_table'](frame, schema, driver, role, history_extension=c['retained_history'] is not None)
                    patch = changed_rows(old, fresh)
                    final_rows, has_target = len(fresh), bool(frame.trade_date.eq(target).any())
                record['logical_rows'][role] = final_rows
                record['has_target'][role] = has_target
                counts[role]['panel_rows'] += final_rows
                if has_target:
                    current_symbols[role].add(code)
                if patch is not None and len(patch):
                    path = c['candidates'][role].parent / 'delta_blocks' / (code + '.' + dependency + '.parquet')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    block_meta = {k:v for k,v in (patch.schema.metadata or {}).items() if k != logical.META}
                    block_meta[b'v4.original_panel.delta_block.v1'] = json.dumps(dict(
                        generation_id=c['run_id'], dependency=dependency, role=role, symbol=code,
                        asof_date=target, input_sha256=c['identity']['input_sha256'])).encode()
                    patch = patch.replace_schema_metadata(block_meta)
                    if path.exists():
                        memory = pa.BufferOutputStream()
                        logical.physical.write_table(patch, memory, compression='zstd')
                        if q['sha'](path) != hashlib.sha256(memory.getvalue()).hexdigest():
                            raise ValueError('DELTA_UNREGISTERED_OUTPUT_CONFLICT:' + str(path))
                        reused_bytes += path.stat().st_size
                    else:
                        q['pq'].write_table(patch, path, compression='zstd')
                        logical_written += path.stat().st_size
                    block = logical.descriptor(path, sha256=q['sha'](path), symbols=[code], key_rows={code:list(range(q['pq'].ParquetFile(path).num_row_groups))})
                    old_dates = {int(x) for x in old['trade_date'].to_pylist()}
                    appended = sum(int(day) not in old_dates for day in patch['trade_date'].to_pylist())
                    value = dict(artifact=dict(path=str(path), sha256=block['sha256']), block=block,
                                 appended_rows=appended, revised_rows=len(patch)-appended)
                    record['roles'][role] = value
                    deltas[role].append(block)
                    counts[role]['appended_rows'] += appended
                    counts[role]['revised_rows'] += len(patch)-appended
            q['_json'](checkpoint, record)
        pool.shutdown(wait=True)
        c.pop('_delta_pool', None)
        q['_json'](run / 'progress.json', dict(stage='ORIGINAL_DELTA_STORAGE', completed=len(classifications),
            total=len(expected), reused_checkpoints=resumed, new_delta_file_bytes=logical_written))
    projection = dict(asof_date=target, skip_symbols=sorted(c['retained_history_codes']), raw_lineage={code:{
        r.get('source_role'):r['sha256'] for r in item['raw_files'] if r.get('source_role')}
        for code,item in snapshot['symbols'].items()})
    for role, candidate in c['candidates'].items():
        counts[role]['target_date_symbols'] = len(current_symbols[role])
        if len(current_symbols[role]) < snapshot.get('accepted_target_date_floor', 1):
            raise ValueError('ORIGINAL_ACCEPTED_FLOOR_FAILED:' + role)
        schema = schemas[role].with_metadata({**(schemas[role].metadata or {}), logical.META:json.dumps(meta).encode()})
        payload = logical.anchor_bytes(schema, prior[role] + deltas[role], rows=counts[role]['panel_rows'],
                                       excluded_symbols=quarantine, projection=projection)
        if candidate.exists():
            if candidate.read_bytes() != payload:
                raise ValueError('DELTA_IMMUTABLE_ANCHOR_CONFLICT')
        else:
            q['_write'](candidate, payload)
    # Source and paired-baseline checks are identical to the original owner.
    if q['generation_identity'](q['load_snapshot'](c['snapshot_file'],target),c['driver_path'],c['formula_path'],c['contract_csv']) != {k:v for k,v in c['identity'].items() if k!='turnover_input_sha256'}:
        raise ValueError('INPUT_CHANGED_DURING_BUILD')
    c['turnover'].verify_binding()
    for path in c['candidates'].values():
        logical.validate_closure(path)
    q['check_baseline'](c['pointers'],c['frozen_baseline'])
    q['_json'](run / 'quarantine_manifest.json', dict(generation_id=c['run_id'], reasons=quarantine,
        inherited_quarantine_manifests=list(c['inherited_quarantine'].values()), artifacts={}, counts=counts, excluded_from_accepted=True))
    receipt = dict(status='CANDIDATE_READY', target_date=target, run_dir=str(run),
        candidates={r:str(p) for r,p in c['candidates'].items()}, candidate_sha256={r:q['sha'](p) for r,p in c['candidates'].items()},
        quarantine_manifest=dict(path=str(run/'quarantine_manifest.json'),sha256=q['sha'](run/'quarantine_manifest.json')),
        counts=counts, storage_layout='ARROW_BLOCKS_V1', dependency_classifications=classifications,
        reused_delta_checkpoints=resumed, new_delta_file_bytes=logical_written,
        reused_delta_file_bytes=reused_bytes, **meta)
    q['_json'](run / 'candidate_receipt.json', receipt)
    if c['publish']:
        q['verify_release_gate'](c['snapshot_file'].parent,c['candidates']['selector'],c['identity'],target,snapshot['convention'])
        q['publish_pair'](c['pointers'],c['candidates'],c['expected'],c['journal'],expected_baseline=c['frozen_baseline'])
        q['_json'](c['baseline_file'],q['baseline_binding'](c['pointers']))
        q['_json'](c['snapshot_file'].with_name('qfq_readiness.json'),c['readiness'])
        receipt.update(status='READY',selector_pointer_ready=True,backtest_pointer_ready=True)
    receipt.update(selector=str(c['candidates']['selector']),backtest=str(c['candidates']['backtest']),
        authority=dict(final_status='PASS_QFQ_FULL_HISTORY' if c['publish'] else 'CANDIDATE_READY',
                       source_sha256=c['identity']['input_sha256'],generation_id=c['run_id']))
    compatibility = dict(receipt, final_status=receipt['authority']['final_status'], latest_trade_date=target,
        selector_current_after=receipt['selector'], backtest_current_after=receipt['backtest'], qfq_contract=meta,
        canonical_rebuild_stage_status='FULL_LOGICAL_HISTORY_ORIGINAL_CANONICAL_PURE_FUNCTION',
        formula_processing=dict(worker_context=dict(driver_path=str(c['driver_path']),
            driver_sha256=c['identity']['driver_sha256'], canonical_formula_path=str(c['formula_path']),
            canonical_formula_sha256=c['identity']['formula_sha256'])))
    q['_json'](run/'meta.json',compatibility)
    q['_json'](run/'task_summary.json',compatibility)
    q['_json'](run/'stage_status.json',receipt)
    return receipt


def _prepare(q, c, code, frames, old_snapshot, schemas, source_semantics):
    snapshot,target,driver,run=c['snapshot'],c['target'],c['driver'],c['run_dir']
    currents = c['currents']
    item = snapshot['symbols'][code]
    raw_driver = _RawDriver(driver)
    raw = q['resolved_raw_history'](code, item, target, raw_driver)
    old_item = old_snapshot.get('symbols', {}).get(code)
    old_end = max((max(int(x) for x in t['trade_date'].to_pylist()) for t in [frames[r].get(code) for r in currents]
                   if t is not None and len(t)), default=0)
    before = None
    if old_item is not None:
        before = q['resolved_raw_history'](code, old_item, old_snapshot['asof_date'], raw_driver)
    events_same = old_item is not None and factor_state(old_item) == factor_state(item)
    rules_same=all(all(contract.get(key)==source_semantics[key] for key in
        ('driver_sha256','formula_sha256','user_formula_sha256','field_contract_sha256')) for contract in c['contracts'].values())
    shape_same=old_item is not None and all(old_item.get(key)==item.get(key) for key in
        ('history_extension','history_start_date','compute_start_date'))
    prefix_same = before is not None and raw_identity(before) == raw_identity(raw.loc[raw.trade_date.le(int(before.trade_date.max()))])
    kind = ('NEW_OR_MISSING_HISTORY' if before is None else 'RULE_REVISION' if not rules_same else 'FACTOR_REVISION' if not events_same
            else 'RAW_REVISION' if not prefix_same or not shape_same else 'APPEND' if int(raw.trade_date.max()) > old_end else 'UNCHANGED')
    dependency = q['canonical_sha'](dict(code=code, raw=raw_identity(raw), events=factor_state(item),history_extension=item.get('history_extension'),
        compute_start=item.get('compute_start_date'), rules=source_semantics,
        baseline=c['baseline_hashes'],turnover_input=c['identity'].get('turnover_input_sha256'),
        schemas={r: hashlib.sha256(s.remove_metadata().serialize()).hexdigest() for r, s in schemas.items()}))
    checkpoint = run / 'delta_checkpoints' / (code + '.' + dependency + '.json')
    computed = None
    if kind != 'UNCHANGED' and not checkpoint.is_file():
        recovered=c.get('recovered',{}).get(code)
        if recovered is not None:
            path=(q['_partial_checkpoint_file'](recovered) if recovered.get('read_only_original') is True
                  else q['_source'](recovered['artifact'],owner='delta reviewed pure checkpoint '+code))
            computed=q['pq'].read_table(path).to_pandas()
            if set(computed.ts_code.astype(str))!={code}:raise q['QfqGateError']('DELTA_RECOVERED_ROW_CODE_CONFLICT:'+code)
        else:
            computed=q['rebuild_symbol'](code, item, target, raw_driver)
    return dict(item=item,kind=kind,dependency=dependency,checkpoint=checkpoint,computed=computed)


def _validate_resume(q,c,code,dependency,saved,frames,schemas):
    if set(saved['logical_rows'])!=set(schemas) or set(saved['has_target'])!=set(schemas) or not set(saved['roles'])<=set(schemas):
        raise ValueError('DELTA_CHECKPOINT_ROLE_SCOPE')
    for role,schema in schemas.items():
        old=frames[role].get(code,pa.Table.from_batches([],schema=schema))
        old_keys={int(x) for x in old['trade_date'].to_pylist()}
        value=saved['roles'].get(role)
        if value is None:
            keys=old_keys
        else:
            expected=c['candidates'][role].parent/'delta_blocks'/(code+'.'+dependency+'.parquet')
            if value['artifact']['path']!=str(expected) or value['block']['path']!=str(expected) or value['artifact']['sha256']!=value['block']['sha256']:
                raise ValueError('DELTA_CHECKPOINT_PATH_OR_SHA')
            path=q['_source'](value['artifact'],owner='delta resume source '+code)
            patch=q['pq'].read_table(path)
            footer=json.loads((patch.schema.metadata or {}).get(b'v4.original_panel.delta_block.v1',b'{}'))
            required=dict(generation_id=c['run_id'],dependency=dependency,role=role,symbol=code,asof_date=c['target'],input_sha256=c['identity']['input_sha256'])
            if footer!=required or not patch.schema.equals(schema,check_metadata=False) or set(patch['ts_code'].to_pylist())!={code}:
                raise ValueError('DELTA_CHECKPOINT_ARTIFACT_IDENTITY')
            days=[int(x) for x in patch['trade_date'].to_pylist()]
            if len(set(days))!=len(days) or not days or max(days)>c['target']:
                raise ValueError('DELTA_CHECKPOINT_KEYS')
            if value['block']!=logical.descriptor(path,sha256=value['artifact']['sha256'],symbols=[code],key_rows={code:list(range(q['pq'].ParquetFile(path).num_row_groups))}):
                raise ValueError('DELTA_CHECKPOINT_BLOCK_DESCRIPTOR')
            appended=len(set(days)-old_keys)
            if value['appended_rows']!=appended or value['revised_rows']!=len(days)-appended:
                raise ValueError('DELTA_CHECKPOINT_COUNTS')
            keys=old_keys|set(days)
        if saved['logical_rows'][role]!=len(keys) or saved['has_target'][role]!=(c['target'] in keys):
            raise ValueError('DELTA_CHECKPOINT_LOGICAL_COUNTS')
