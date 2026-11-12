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


# The anchor contract already permits a physical block to contain many symbols.
# A sealed batch is a storage commit, not a new producer or numerical result.
BATCH_META = b'v4.original_panel.delta_batch.v1'
BATCH_SEAL = 'v4.original_panel.delta_batch_seal.v1'


def _packing_limits(c):
    budget = (c.get('resource_plan') or {}).get('job_budget_bytes', 64 * 1024**3)
    maximum = max(1, min(64 * 1024**2, budget // 64))
    return dict(max_bytes=maximum, max_symbols=max(1, min(128, maximum // (512 * 1024))))


def _batch_common(c):
    return dict(generation_id=c['run_id'], asof_date=c['target'], input_sha256=c['identity']['input_sha256'])


def _batch_path(q, c, role, footer):
    return c['candidates'][role].parent / 'delta_blocks' / ('batch.' + q['canonical_sha'](footer) + '.parquet')


def _seal_key(q, value):
    return q['canonical_sha'](dict(schema=BATCH_SEAL, **value['identity'],
        dependencies={code: row['dependency'] for code, row in value['records'].items()}))


def _read_seal(q, ref):
    path = q['_source'](ref, owner='committed delta batch seal')
    value = json.loads(path.read_text())
    if (value.get('schema') != BATCH_SEAL or not value.get('records') or not value.get('blocks')
            or path.name != _seal_key(q, value) + '.json'):
        raise ValueError('DELTA_BATCH_SEAL_IDENTITY')
    for role, block in value['blocks'].items():
        artifact = q['_source'](dict(path=block['path'], sha256=block['sha256']), owner='sealed delta batch role ' + role)
        if logical.stamp(artifact) != block['stat']:
            raise ValueError('DELTA_BATCH_SEAL_BLOCK_CHANGED')
    return value


def _sealed_record(q, ref, code):
    import copy
    seal = _read_seal(q, ref)
    if code not in seal['records']:
        raise ValueError('DELTA_BATCH_MEMBER_MISSING')
    record = copy.deepcopy(seal['records'][code])
    record['batch_seal'] = ref
    for role, value in record['roles'].items():
        block = copy.deepcopy(seal['blocks'][role])
        block['metadata_refs'] = block.get('metadata_refs', []) + [ref]
        value.update(artifact=dict(path=block['path'], sha256=block['sha256']), block=block)
    return record


def _thin_record(record):
    import copy
    result = copy.deepcopy(record)
    for value in result['roles'].values():
        value.pop('block', None)
    return result


def _load_checkpoint(q, path, code):
    raw = json.loads(Path(path).read_text())
    if raw.get('schema') == BATCH_SEAL:
        return _sealed_record(q, dict(path=str(path), sha256=q['sha'](path)), code)
    if 'batch_seal' not in raw:
        return raw
    result = _sealed_record(q, raw['batch_seal'], code)
    if _thin_record(result) != raw:
        raise ValueError('DELTA_BATCH_CHECKPOINT_INDEX_DRIFT')
    return result


def _sealed_members(q, run, *, identity=None):
    """Discover only atomically committed storage batches, never loose outputs."""
    result = {}
    for path in sorted((Path(run) / 'delta_batch_seals').glob('*.json')):
        ref = dict(path=str(path), sha256=q['sha'](path))
        seal = _read_seal(q, ref)
        if identity is not None and seal['identity'] != identity:
            raise ValueError('DELTA_BATCH_SEAL_GENERATION_DRIFT')
        for code, record in seal['records'].items():
            old = result.get(code)
            if old and old['dependency'] != record['dependency']:
                raise ValueError('DELTA_BATCH_DUPLICATE_MEMBER_DEPENDENCY')
            result.setdefault(code, dict(reference=ref, dependency=record['dependency']))
    return result


class _PackedWrites:
    """Bound parent-owned Arrow patches; workers still only calculate."""
    def __init__(self, q, c):
        self.q, self.c, self.limits = q, c, _packing_limits(c)
        self.pending, self.bytes = [], 0
        self.written_bytes = self.reused_bytes = 0
        self.reused_paths = set()
        self.failed = None

    def reused(self, path):
        path = Path(path)
        if path not in self.reused_paths:
            self.reused_paths.add(path)
            self.reused_bytes += path.stat().st_size

    def _file(self, path, table):
        q = self.q
        path.parent.mkdir(parents=True, exist_ok=True)
        memory = pa.BufferOutputStream()
        logical.physical.write_table(table, memory, compression='zstd')
        payload = memory.getvalue()
        expected_sha = hashlib.sha256(payload).hexdigest()
        if path.exists():
            if q['sha'](path) != expected_sha:
                raise ValueError('DELTA_UNREGISTERED_OUTPUT_CONFLICT:' + str(path))
            self.reused(path)
        else:
            # The original owner fsyncs and atomically renames this bounded
            # payload. A failed write never leaves a partial final batch file.
            q['_write'](path, payload.to_pybytes())
            self.written_bytes += path.stat().st_size
        if q['sha'](path) != expected_sha:
            raise ValueError('DELTA_WRITTEN_BLOCK_SHA')
        return logical.descriptor(path, sha256=expected_sha,
            symbols=set(table['ts_code'].to_pylist()), key_rows=key_index(path))

    def _single(self, prepared):
        q, c = self.q, self.c
        code, dependency, checkpoint, record = (prepared[k] for k in ('code', 'dependency', 'checkpoint', 'record'))
        for role, patch in prepared['patches'].items():
            path = c['candidates'][role].parent / 'delta_blocks' / (code + '.' + dependency + '.parquet')
            meta = {k: v for k, v in (patch.schema.metadata or {}).items() if k != logical.META}
            meta[b'v4.original_panel.delta_block.v1'] = json.dumps(dict(**_batch_common(c), dependency=dependency,
                role=role, symbol=code)).encode()
            block = self._file(path, patch.replace_schema_metadata(meta))
            record['roles'][role].update(artifact=dict(path=str(path), sha256=block['sha256']), block=block)
        q['_json'](checkpoint, record)
        return prepared

    def add(self, prepared):
        if self.failed is not None:
            raise self.failed
        size = sum(table.nbytes for table in prepared['patches'].values())
        result = []
        try:
            if not prepared['patches']:
                return [self._single(prepared)]
            if size > self.limits['max_bytes']:
                result.extend(self.flush())
                result.append(self._single(prepared))
                return result
            if self.pending and (self.bytes + size > self.limits['max_bytes']
                    or len(self.pending) >= self.limits['max_symbols']):
                result.extend(self.flush())
            self.pending.append(prepared)
            self.bytes += size
            if len(self.pending) >= self.limits['max_symbols']:
                result.extend(self.flush())
            return result
        except BaseException as error:
            self.failed = error
            raise

    def flush(self):
        if self.failed is not None:
            raise self.failed
        if not self.pending:
            return []
        pending = sorted(self.pending, key=lambda item: item['code'])
        try:
            if len(pending) == 1:
                result = [self._single(pending[0])]
            else:
                blocks = {}
                for role in self.c['schemas']:
                    members = [item for item in pending if role in item['patches']]
                    if not members:
                        continue
                    tables = [item['patches'][role] for item in members]
                    if not all(table.schema.equals(tables[0].schema, check_metadata=True) for table in tables):
                        raise ValueError('DELTA_BATCH_SCHEMA_DRIFT')
                    table = pa.concat_tables(tables)
                    footer = dict(**_batch_common(self.c), role=role,
                        members={item['code']: dict(dependency=item['dependency'], rows=len(item['patches'][role])) for item in members})
                    meta = {k: v for k, v in (table.schema.metadata or {}).items() if k != logical.META}
                    meta[BATCH_META] = json.dumps(footer, sort_keys=True).encode()
                    blocks[role] = self._file(_batch_path(self.q, self.c, role, footer), table.replace_schema_metadata(meta))
                seal = dict(schema=BATCH_SEAL, identity=_batch_common(self.c), blocks=blocks,
                    records={item['code']: item['record'] for item in pending})
                path = self.c['run_dir'] / 'delta_batch_seals' / (_seal_key(self.q, seal) + '.json')
                if path.exists():
                    if json.loads(path.read_text()) != seal:
                        raise ValueError('DELTA_BATCH_SEAL_CONFLICT')
                else:
                    self.q['_json'](path, seal)
                ref = dict(path=str(path), sha256=self.q['sha'](path))
                # A seal is committed only after both role files exist and match
                # their hashes. Per-stock files are small, recoverable indexes.
                result = []
                for item in pending:
                    record = _sealed_record(self.q, ref, item['code'])
                    self.q['_json'](item['checkpoint'], _thin_record(record))
                    result.append({**item, 'record': record})
            self.pending, self.bytes = [], 0
            return result
        except BaseException as error:
            self.failed = error
            raise


def _add_scoped_block(blocks, code, block):
    """One physical reference; only verified members enter the logical scope."""
    import copy
    previous = next((old for old in blocks if old['path'] == block['path']), None)
    if previous is None:
        previous = copy.deepcopy(block)
        previous['symbols'] = []
        previous['key_rows'] = {}
        blocks.append(previous)
    elif any(previous.get(key) != block.get(key) for key in ('sha256', 'stat', 'rows', 'row_groups', 'metadata_refs')):
        raise ValueError('DELTA_SHARED_BLOCK_DESCRIPTOR_DRIFT')
    previous['symbols'] = sorted(set(previous['symbols']) | {code})
    previous['key_rows'][code] = list(block['key_rows'][code])


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
    c['sealed_records'] = _sealed_members(q, run, identity=_batch_common(c))
    packer = _PackedWrites(q, c)
    processed_results = 0
    def accept(code, kind, record):
        for role in currents:
            counts[role]['panel_rows'] += record['logical_rows'][role]
            if record['has_target'][role]: current_symbols[role].add(code)
            value = record['roles'].get(role)
            if value:
                _add_scoped_block(deltas[role], code, value['block'])
                for key in ('appended_rows', 'revised_rows'): counts[role][key] += value[key]
        classifications[code] = kind
    source_semantics = {key: meta[key] for key in ('driver_sha256','formula_sha256','user_formula_sha256','field_contract_sha256')}
    source_semantics['kernel_sha256'] = q['computation_kernel_sha'](Path(q['__file__']))
    from concurrent.futures import wait,FIRST_COMPLETED
    import multiprocessing,os,time
    backend=c.get('compute_backend','thread')
    if backend=='process':
        multiprocessing.set_executable(q['sys'].executable)
        pool=q['ProcessPoolExecutor'](max_workers=c['workers'],mp_context=multiprocessing.get_context('spawn'),
            initializer=_initialize_delta_process,initargs=(_process_state(c,source_semantics),))
    else:
        pool=q['ThreadPoolExecutor'](max_workers=c['workers'])
    c['_delta_pool']=pool
    limit=(c.get('resource_plan')or{}).get('max_pending',2*c['workers'])
    maximum_inflight=0;worker_pids=set();cpu_seconds=0.;started=time.perf_counter();failure=None
    stop=run/'STOP_REQUESTED'
    def progress(stage='ORIGINAL_DELTA_STORAGE'):
        q['_json'](run/'progress.json',dict(stage=stage,completed=len(classifications),total=len(expected),
            reused_checkpoints=resumed,new_delta_file_bytes=packer.written_bytes,compute_backend=backend,
            buffered_computations=len(packer.pending),buffered_patch_bytes=packer.bytes,packing_limits=packer.limits,
            workers=c['workers'],max_pending=limit,maximum_inflight=maximum_inflight,
            worker_pids=sorted(worker_pids),worker_cpu_seconds=cpu_seconds,elapsed_seconds=time.perf_counter()-started))
    for bucket,codes in buckets.items():
        frames={}
        for role,path in currents.items():
            table=(old_views[role][bucket].read() if role in old_views and bucket in old_views[role]
                else q['pq'].read_table(path,filters=[('ts_code','in',codes)]) if role not in old_views
                else pa.Table.from_batches([],schema=schemas[role]))
            series=table['ts_code'].to_pandas();positions=series.groupby(series,sort=False).indices
            frames[role]={code:table.take(pa.array(rows,type=pa.int64()))for code,rows in positions.items()}
        for code in codes:
            if code not in expected and code not in quarantine:
                for role in currents:counts[role]['panel_rows']+=len(frames[role].get(code,[]))
        iterator=iter(code for code in codes if code in expected);pending={};exhausted=False
        while pending or not exhausted:
            if failure is None and stop.exists():failure=InterruptedError('DELTA_STOP_REQUESTED_DRAINED')
            while failure is None and not exhausted and len(pending)<limit:
                code=next(iterator,None)
                if code is None:exhausted=True;break
                if backend=='process':
                    stock_frames={role:frames[role][code]for role in frames if code in frames[role]}
                    payload=(code,snapshot['symbols'][code],old_snapshot['symbols'].get(code),old_snapshot['asof_date'],stock_frames,c.get('recovered',{}).get(code))
                    future=pool.submit(_delta_process_task,payload)
                else:
                    future=pool.submit(_stock_work,q,c,code,frames,old_snapshot,schemas,source_semantics)
                pending[future]=code;maximum_inflight=max(maximum_inflight,len(pending))
            if not pending:break
            done,_=wait(pending,return_when=FIRST_COMPLETED)
            for future in done:
                code=pending.pop(future)
                try:
                    prepared=future.result()
                    processed_results += 1
                    worker_pids.add(prepared['worker_pid']);cpu_seconds+=prepared['cpu_seconds']
                    item,kind,dependency,checkpoint=(prepared[k]for k in ('item','kind','dependency','checkpoint'))
                    if checkpoint.is_file():
                        saved=_load_checkpoint(q,checkpoint,code)
                        if saved['dependency']!=dependency or saved.get('classification')!=kind:raise ValueError('DELTA_CHECKPOINT_IDENTITY')
                        origin=prepared.get('origin');validation=c
                        if origin:
                            validation={**c,'run_id':origin['source_generation'],'run_dir':Path(origin.get('source_run',c['run_dir'])),'candidates':{r:Path(p)for r,p in origin['source_candidates'].items()}}
                        _validate_resume(q,validation,code,dependency,saved,frames,schemas)
                        record=saved;resumed+=1
                        for value in record['roles'].values(): packer.reused(value['artifact']['path'])
                        if prepared.get('checkpoint_member') and not origin:
                            q['_json'](run/'delta_checkpoints'/(code+'.'+dependency+'.json'),_thin_record(record))
                        accept(code,kind,record)
                    else:
                        for completed in packer.add(prepared):
                            accept(completed['code'],completed['kind'],completed['record'])
                except BaseException as error:
                    eligible=snapshot.get('original_quarantine_eligible',{})
                    if isinstance(error,q['QfqGateError']) and code in eligible:
                        quarantine[code]=dict(reason=str(error),original_status=eligible[code]);classifications[code]='ORIGINAL_QUARANTINE_ELIGIBLE_FAILURE'
                    elif failure is None:failure=error
                if backend=='process' and processed_results%32==0 and failure is None:
                    plan=resource_plan(observe_resources(),c.get('requested_workers'))
                    limit=min(2*c['workers'],plan['max_pending'])
                    if plan['drained']:failure=MemoryError('DELTA_RESOURCE_LIMIT_DRAINED')
                if len(classifications)%max(1,min(16,c['workers']))==0 or failure is not None:progress('DRAINING'if failure else'ORIGINAL_DELTA_STORAGE')
            if failure is not None:exhausted=True
        if packer.failed is None:
            try:
                for completed in packer.flush():
                    accept(completed['code'],completed['kind'],completed['record'])
            except BaseException as error:
                failure = failure or error
        progress('DRAINED'if failure else'ORIGINAL_DELTA_STORAGE')
        if failure is not None:raise failure
    pool.shutdown(wait=True);c.pop('_delta_pool',None)
    logical_written,reused_bytes=packer.written_bytes,packer.reused_bytes
    for role in deltas:
        deltas[role].sort(key=lambda block:(q['_bucket'](block['symbols'][0]),block['symbols'][0]))
    if c.get('delta_resume_control'):
        references=[c['checkpoint_resume'],c['delta_resume_control']['source_status']]
        for role in prior:
            prior[role][0]={**prior[role][0],'metadata_refs':prior[role][0].get('metadata_refs',[])+references}
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
    # Preserve the original closed-source revalidation before any CURRENT
    # transaction. A consumed recovery artifact is still a checked input.
    recovered=c.get('recovered',{})
    partial=[item for item in recovered.values() if item.get('read_only_original') is True]
    if c.get('checkpoint_resume') is not None:
        control=json.loads(q['_source'](c['checkpoint_resume'],owner='D11 recovery before publication').read_text())
        if partial:
            for key in ('source_core','original_snapshot'):
                q['_source'](control[key],owner='D11 partial original source before publication')
    for item in recovered.values():
        if item.get('read_only_original') is True:q['_partial_checkpoint_file'](item)
        elif item.get('read_only_delta') is True:q['_source'](item['checkpoint'],owner='delta checkpoint before publication')
        else:q['_source'](item['artifact'],owner='recovered computation before publication')
    if c.get('delta_resume_control'):
        _resume_sources(q,c['delta_resume_control'])
        q['_source'](c['delta_resume_control']['source_status'],owner='original delta run still closed')
    # Source and paired-baseline checks are identical to the original owner.
    if q['generation_identity'](q['load_snapshot'](c['snapshot_file'],target),c['driver_path'],c['formula_path'],c['contract_csv']) != {k:v for k,v in c['identity'].items() if k!='turnover_input_sha256'}:
        raise ValueError('INPUT_CHANGED_DURING_BUILD')
    c['turnover'].verify_binding()
    if not q['turnover_watch_unchanged'](c['readiness']['turnover_watch']):
        raise q['QfqGateError']('TURNOVER_INPUT_STATUS_CHANGED_DURING_BUILD')
    if q['factor_cache_identity'](data_root,target,snapshot)!=c['readiness']['factor_cache_identity']:
        raise q['QfqGateError']('FACTOR_CACHE_CHANGED_DURING_BUILD')
    for ref in c['inherited_quarantine'].values():
        q['_source'](ref,owner='prior-generation quarantine before publication')
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
    before = None;baseline_proof=[]
    if old_item is not None:
        before,baseline_proof = baseline_raw_history(q,code,old_item,item,old_snapshot['asof_date'],target,raw_driver,raw)
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
    origin=None;checkpoint_member=None
    restored=c.get('recovered',{}).get(code)
    if not checkpoint.is_file() and restored is not None and restored.get('read_only_delta') is True:
        origin=restored
        checkpoint=q['_source'](restored['checkpoint'],owner='sealed original delta checkpoint '+code)
        checkpoint_member=restored['checkpoint'].get('member')
    sealed=c.get('sealed_records',{}).get(code)
    if not checkpoint.is_file() and sealed is not None and sealed['dependency']==dependency:
        checkpoint=q['_source'](sealed['reference'],owner='completed same-run batch member '+code)
        checkpoint_member=code
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
    return dict(code=code,item=item,kind=kind,dependency=dependency,checkpoint=checkpoint,checkpoint_member=checkpoint_member,computed=computed,origin=origin,baseline_proof=baseline_proof)


def _validate_persisted_patch(q, c, code, dependency, saved, role, value, schema=None):
    path = q['_source'](value['artifact'], owner='delta resume source ' + code)
    patch = q['pq'].read_table(path)
    metadata = patch.schema.metadata or {}
    if schema is not None and not patch.schema.equals(schema, check_metadata=False):
        raise ValueError('DELTA_CHECKPOINT_ARTIFACT_IDENTITY')
    if BATCH_META in metadata:
        footer = json.loads(metadata[BATCH_META])
        members = footer.get('members', {})
        if (set(footer) != set(_batch_common(c)) | {'role', 'members'}
                or {key: footer.get(key) for key in _batch_common(c)} != _batch_common(c)
                or footer.get('role') != role or code not in members
                or members[code].get('dependency') != dependency
                or set(members) != set(patch['ts_code'].to_pylist())
                or not set(members) <= set(c['snapshot']['symbols'])
                or path != _batch_path(q, c, role, footer)):
            raise ValueError('DELTA_BATCH_ARTIFACT_IDENTITY')
        ref = saved.get('batch_seal')
        if not ref or Path(ref['path']).parent != c['run_dir'] / 'delta_batch_seals':
            raise ValueError('DELTA_BATCH_SEAL_PATH')
        seal = _read_seal(q, ref)
        if seal['identity'] != _batch_common(c):
            raise ValueError('DELTA_BATCH_SEAL_GENERATION_DRIFT')
        for member, item in members.items():
            record = seal['records'].get(member, {})
            subset = patch.filter(pc.equal(patch['ts_code'], member))
            if (item != dict(dependency=record.get('dependency'), rows=len(subset))
                    or role not in record.get('roles', {})):
                raise ValueError('DELTA_BATCH_MEMBER_IDENTITY')
        expected = logical.descriptor(path, sha256=value['artifact']['sha256'],
            symbols=members, key_rows=key_index(path))
        expected['metadata_refs'] = expected.get('metadata_refs', []) + [ref]
        if value['block'] != expected:
            raise ValueError('DELTA_CHECKPOINT_BLOCK_DESCRIPTOR')
        all_keys = list(zip(patch['ts_code'].to_pylist(), patch['trade_date'].to_pylist()))
        if len(set(all_keys)) != len(all_keys):
            raise ValueError('DELTA_CHECKPOINT_KEYS')
        if any(int(day) > c['target'] for _, day in all_keys):
            raise ValueError('DELTA_CHECKPOINT_KEYS')
        patch = patch.filter(pc.equal(patch['ts_code'], code))
    else:
        expected = c['candidates'][role].parent / 'delta_blocks' / (code + '.' + dependency + '.parquet')
        footer = json.loads(metadata.get(b'v4.original_panel.delta_block.v1', b'{}'))
        required = dict(**_batch_common(c), dependency=dependency, role=role, symbol=code)
        if footer != required or path != expected or set(patch['ts_code'].to_pylist()) != {code}:
            raise ValueError('DELTA_CHECKPOINT_ARTIFACT_IDENTITY')
        expected = logical.descriptor(path, sha256=value['artifact']['sha256'], symbols=[code],
            key_rows={code: list(range(q['pq'].ParquetFile(path).num_row_groups))})
        if value['block'] != expected:
            raise ValueError('DELTA_CHECKPOINT_BLOCK_DESCRIPTOR')
    if value['block']['path'] != str(path) or value['artifact']['sha256'] != value['block']['sha256']:
        raise ValueError('DELTA_CHECKPOINT_PATH_OR_SHA')
    days = [int(x) for x in patch['trade_date'].to_pylist()]
    if len(set(days)) != len(days) or not days or max(days) > c['target']:
        raise ValueError('DELTA_CHECKPOINT_KEYS')
    return patch


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
            patch=_validate_persisted_patch(q,c,code,dependency,saved,role,value,schema)
            days=[int(x)for x in patch['trade_date'].to_pylist()]
            appended=len(set(days)-old_keys)
            if value['appended_rows']!=appended or value['revised_rows']!=len(days)-appended:
                raise ValueError('DELTA_CHECKPOINT_COUNTS')
            keys=old_keys|set(days)
        if saved['logical_rows'][role]!=len(keys) or saved['has_target'][role]!=(c['target'] in keys):
            raise ValueError('DELTA_CHECKPOINT_LOGICAL_COUNTS')


def baseline_raw_history(q,code,old_item,item,old_asof,target,driver,current):
    """Authenticate old bytes, including an exact prefix of an appended file.

    _source remains unchanged. The fallback accepts only identical source paths
    and slicing semantics, independently authenticated new whole bytes and the
    exact old whole SHA reconstructed as a contiguous prefix. A revision fails.
    """
    try:
        return q['resolved_raw_history'](code,old_item,old_asof,driver),[]
    except q['QfqGateError'] as error:
        if not str(error).startswith('SOURCE_BINDING_FAILED:'):raise
        original=error
    previous,current_refs=old_item['raw_files'],item['raw_files']
    semantic=lambda ref:{k:v for k,v in ref.items() if k!='sha256'}
    if (len(previous)!=len(current_refs) or any(semantic(a)!=semantic(b) for a,b in zip(previous,current_refs))
            or any(old_item.get(k)!=item.get(k) for k in ('raw_resolution','history_start_date','compute_start_date'))):
        raise original
    import struct
    proofs=[]
    for before,after in zip(previous,current_refs):
        path=q['_source'](after,owner='current whole for baseline '+code)
        stamp=logical.stamp(path);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=after['sha256'] or logical.stamp(path)!=stamp:
            raise q['QfqGateError']('BASELINE_PREFIX_CURRENT_CHANGED:'+code)
        if before['sha256']==after['sha256']:continue
        size=driver.DAY_STRUCT.size
        if size!=32 or len(raw)%size:raise original
        days=[struct.unpack_from('<I',raw,i)[0] for i in range(0,len(raw),size)]
        if days!=sorted(set(days)) or not days or max(days)>target:raise original
        n=sum(day<=old_asof for day in days);prefix=raw[:n*size]
        if hashlib.sha256(prefix).hexdigest()!=before['sha256'] or not all(d>old_asof for d in days[n:]):raise original
        proofs.append(dict(original=before,current=after,old_asof=old_asof,prefix_rows=n,
            prefix_sha256=before['sha256'],added_dates=days[n:]))
    if not proofs:raise original
    return current.loc[current.trade_date.le(old_asof)].copy(),proofs


def observe_resources():
    """Current CPU/RSS/available-memory observation; no disk survey."""
    import multiprocessing,os,re,subprocess
    pids=[os.getpid()]+[child.pid for child in multiprocessing.active_children() if child.pid]
    text=subprocess.check_output(['ps','-o','pid=,rss=','-p',','.join(map(str,pids))],text=True)
    rss={int(line.split()[0]):int(line.split()[1])*1024 for line in text.splitlines() if line.strip()}
    pressure=subprocess.check_output(['memory_pressure'],text=True)
    match=re.search(r'System-wide memory free percentage:\s*(\d+)%',pressure)
    if not match:raise ValueError('DELTA_MEMORY_PRESSURE_UNAVAILABLE')
    total=int(subprocess.check_output(['sysctl','-n','hw.memsize'],text=True))
    return dict(cpu_cores=os.cpu_count()or 1,physical_memory_bytes=total,
        available_bytes=total*int(match[1])//100,memory_pressure_free_percent=int(match[1]),
        cumulative_rss_bytes=sum(rss.values()),parent_rss_bytes=rss.get(os.getpid(),0),
        maximum_worker_rss_bytes=max((v for p,v in rss.items() if p!=os.getpid()),default=0),pids=pids)


def resource_plan(observed,requested=None):
    gib=1024**3;budget=min(64*gib,observed['physical_memory_bytes']//2)
    reserve=min(24*gib,observed['physical_memory_bytes']*3//16)
    estimate=max(2*gib,observed.get('maximum_worker_rss_bytes',0))
    ceiling=max(1,observed['cpu_cores']-2)
    if requested is not None:
        if type(requested)is not int or requested<1:raise ValueError('DELTA_WORKER_CAP_INVALID')
        ceiling=min(ceiling,requested)
    capacity=min(max(0,budget-observed['parent_rss_bytes']),max(0,observed['available_bytes']-reserve))
    workers=max(1,min(ceiling,capacity//estimate))
    return dict(workers=workers,max_pending=2*workers,job_budget_bytes=budget,reserve_available_bytes=reserve,
        estimated_worker_bytes=estimate,observed=observed,requested_upper_bound=requested,
        drained=(observed['cumulative_rss_bytes']>=budget or observed['available_bytes']<reserve))


def _calculate_roles(q,c,code,prepared,frames,schemas):
    """Original assembly/math, executed in a worker; never writes or publishes."""
    item,kind,dependency,computed=(prepared[k]for k in ('item','kind','dependency','computed'))
    target,driver=c['target'],c['driver']
    record=dict(dependency=dependency,classification=kind,roles={},logical_rows={},has_target={},
        baseline_prefix_proofs=prepared.get('baseline_proof',[]))
    patches={}
    for role,schema in schemas.items():
        old=frames[role].get(code,pa.Table.from_batches([],schema=schema))
        if not len(old) and role not in item.get('publish_roles',[]):
            record['logical_rows'][role]=0;record['has_target'][role]=False;continue
        if computed is None:
            final_rows=len(old);has_target=target in [int(x)for x in old['trade_date'].to_pylist()];patch=None
        else:
            rebuilt=computed
            if not len(old) and c.get('history') is None and c.get('addition') is None and role in c.get('role_start',{}):
                rebuilt=rebuilt.loc[rebuilt.trade_date.ge(c['role_start'][role])].copy()
            frame=q['merge_rebuilt'](old.to_pandas(),rebuilt,role=role,driver=driver,history_extension=c['retained_history']is not None)
            frame=c['turnover'].apply_target(code,frame)
            if role=='selector' and frame.trade_date.eq(target).any():
                gate=driver.validate_new_selector_rows(frame.loc[frame.trade_date.eq(target)],schema,target)
                if gate['status']!='PASS':raise ValueError('ORIGINAL_SELECTOR_FORMULA_GATE_FAILED:'+code)
            fresh=q['_table'](frame,schema,driver,role,history_extension=c['retained_history']is not None)
            patch=changed_rows(old,fresh);final_rows=len(fresh);has_target=bool(frame.trade_date.eq(target).any())
        record['logical_rows'][role]=final_rows;record['has_target'][role]=has_target
        if patch is not None and len(patch):
            old_dates={int(x)for x in old['trade_date'].to_pylist()}
            appended=sum(int(day)not in old_dates for day in patch['trade_date'].to_pylist())
            patches[role]=patch
            record['roles'][role]=dict(appended_rows=appended,revised_rows=len(patch)-appended)
    return record,patches


def _stock_work(q,c,code,frames,old_snapshot,schemas,source_semantics):
    import os,time
    started=time.process_time()
    prepared=_prepare(q,c,code,frames,old_snapshot,schemas,source_semantics)
    if not prepared['checkpoint'].is_file():
        prepared['record'],prepared['patches']=_calculate_roles(q,c,code,prepared,frames,schemas)
    prepared.pop('computed',None)
    prepared.update(worker_pid=os.getpid(),cpu_seconds=time.process_time()-started)
    return prepared


_PROCESS_STATE=None


def _initialize_delta_process(state):
    from ops import research_panel_qfq as owner
    if (owner.sha(Path(owner.__file__))!=state['identity']['adapter_sha256']
            or owner.sha(Path(__file__))!=state['identity']['delta_owner_sha256']):
        raise ValueError('DELTA_PROCESS_SOURCE_IDENTITY_DRIFT')
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    owner._initialize_symbol_process(str(state['driver_path']),str(state['formula_path']))
    global _PROCESS_STATE
    _PROCESS_STATE={**state,'driver':owner._PROCESS_DRIVER}


def _delta_process_task(payload):
    from ops import research_panel_qfq as owner
    code,item,old_item,old_asof,stock_frames,restored=payload
    c={**_PROCESS_STATE,'snapshot':dict(symbols={code:item}),'recovered':({code:restored}if restored else{})}
    old=dict(asof_date=old_asof,symbols=({code:old_item}if old_item else{}))
    frames={role:{code:table}for role,table in stock_frames.items()}
    return _stock_work(vars(owner),c,code,frames,old,c['schemas'],c['source_semantics'])


def _process_state(c,source_semantics):
    fields=['target','run_dir','currents','schemas','contracts','baseline_hashes','identity','turnover','role_start','driver_path','formula_path','sealed_records']
    result={key:c[key]for key in fields}
    result.update(retained_history=(True if c['retained_history']is not None else None),source_semantics=source_semantics)
    return result


DELTA_RECOVERY_SCHEMA='qfq_delta_checkpoint_recovery_v1'


def _selected_math_sha(path,names,deep=False):
    import ast
    tree=ast.parse(Path(path).read_text())
    nodes=[n for n in (ast.walk(tree)if deep else tree.body) if isinstance(n,ast.FunctionDef)and n.name in names]
    if {n.name for n in nodes}!=set(names):raise ValueError('DELTA_RESUME_MATH_DEFINITION_MISSING')
    return hashlib.sha256(json.dumps([ast.dump(n,include_attributes=False)for n in nodes],sort_keys=True).encode()).hexdigest()


def _resume_sources(q,value):
    if value.get('schema')!=DELTA_RECOVERY_SCHEMA or value.get('recovery_scope')!='SAME_DAY_DELTA_PROCESS_V1':
        raise q['QfqGateError']('DELTA_RESUME_SCHEMA_UNKNOWN')
    if any(value.get(k)!=flag for k,flag in q['FLAGS'].items()):raise q['QfqGateError']('DELTA_RESUME_FLAGS')
    actual={'target_core':Path(q['__file__']),'target_delta':Path(__file__),'target_logical':Path(logical.__file__)}
    for name,path in actual.items():
        if value[name]['path']!=str(path)or q['_source'](value[name],owner='delta resume '+name)!=path:
            raise q['QfqGateError']('DELTA_RESUME_TARGET_SOURCE')
    old_core=q['_source'](value['source_core'],owner='original delta core')
    old_delta=q['_source'](value['source_delta'],owner='original delta adapter')
    if old_core.name!='research_panel_qfq.py'or old_delta!=old_core.with_name('research_panel_delta.py'):
        raise q['QfqGateError']('DELTA_RESUME_ORIGINAL_SOURCE_PATH')
    names={'_table','merge_rebuilt','rebuild_symbol','apply_adjustments','resolved_raw_history','append_user_formula_v1','authorities','_load'}
    if _selected_math_sha(old_core,names)!=_selected_math_sha(actual['target_core'],names):
        raise q['QfqGateError']('DELTA_RESUME_CORE_MATH_CHANGED')
    old_logical=q['_source'](value['source_logical'],owner='original logical reader')
    if old_logical!=old_core.with_name('research_panel_logical.py')or _selected_math_sha(old_logical,{'_project','_columns'},True)!=_selected_math_sha(actual['target_logical'],{'_project','_columns'},True):
        raise q['QfqGateError']('DELTA_RESUME_LOGICAL_PROJECTION_CHANGED')
    names={'raw_identity','factor_state','changed_rows'}
    if _selected_math_sha(old_delta,names)!=_selected_math_sha(actual['target_delta'],names):
        raise q['QfqGateError']('DELTA_RESUME_ROW_MATH_CHANGED')
    review=json.loads(q['_source'](value['independent_review'],owner='delta process review').read_text())
    if review.get('verdict')!='REVIEWED/PASS'or not review.get('reviewer')or review.get('reviewer')==review.get('writer'):
        raise q['QfqGateError']('DELTA_RESUME_INDEPENDENT_REVIEW_REQUIRED')
    binding=json.loads(q['_source'](review['source_binding'],owner='reviewed process source binding').read_text())
    for relative,before,after in [('ops/research_panel_qfq.py','source_core','target_core'),('ops/research_panel_delta.py','source_delta','target_delta'),('ops/research_panel_logical.py','source_logical','target_logical')]:
        matches=[i for i in binding['items']if i['owner']=='main'and i['target_relative']==relative]
        if len(matches)!=1 or matches[0]['before_sha256']!=value[before]['sha256']or matches[0]['after_sha256']!=value[after]['sha256']:
            raise q['QfqGateError']('DELTA_RESUME_REVIEW_SOURCE_PAIR')


def fixed_delta_resume_input(q,ref,target,snapshot_file):
    value=json.loads(q['_source'](ref,owner='explicit checkpoint resume').read_text())
    if value.get('schema')!=DELTA_RECOVERY_SCHEMA:return None
    _resume_sources(q,value)
    original=q['_source'](value['original_snapshot'],owner='fixed same-day delta input')
    expected=snapshot_file.parent/'adjustment_snapshots'/(value['original_snapshot']['sha256']+'.json')
    if value.get('asof_date')!=target or original!=expected:
        raise q['QfqGateError']('DELTA_RESUME_SNAPSHOT_PATH_OR_DATE')
    # A new source release cannot silently replace the already-bound descriptor.
    q['_source'](dict(path=str(snapshot_file),sha256=value['original_snapshot']['sha256']),owner='unchanged active same-day input')
    snapshot=q['load_snapshot'](original,target)
    if q['canonical_sha'](snapshot)!=value['source_identity']['input_sha256']:
        raise q['QfqGateError']('DELTA_RESUME_SNAPSHOT_IDENTITY')
    value['_validated_snapshot']=snapshot
    return value


def load_delta_recovery(q,value,snapshot,identity,baseline,data_root):
    _resume_sources(q,value)
    old=value['source_identity'];target=snapshot['asof_date'];chunks=value['chunks']
    if (value.get('asof_date')!=target or set(old)!=set(identity)
            or any(old[k]!=v for k,v in identity.items()if k not in {'adapter_sha256','delta_owner_sha256','logical_reader_sha256'})
            or value.get('baseline_panel_sha256')!=baseline or old['input_sha256']!=q['canonical_sha'](snapshot)
            or old['adapter_sha256']!=value['source_core']['sha256']or old['delta_owner_sha256']!=value['source_delta']['sha256']or old['logical_reader_sha256']!=value['source_logical']['sha256']
            or identity['adapter_sha256']!=value['target_core']['sha256']or identity['delta_owner_sha256']!=value['target_delta']['sha256']or identity['logical_reader_sha256']!=value['target_logical']['sha256']
            or not isinstance(chunks,dict)or not chunks or not set(chunks)<=set(snapshot['symbols'])
            or value.get('completed_count')!=len(chunks)or value.get('total_count')!=len(snapshot['symbols'])):
        raise q['QfqGateError']('DELTA_RESUME_EXACT_INPUT_BASE_SCOPE')
    original=q['_source'](value['original_snapshot'],owner='original same-day delta snapshot')
    if json.loads(original.read_text())!=snapshot:raise q['QfqGateError']('DELTA_RESUME_SNAPSHOT_CHANGED')
    if not value.get('factor_cache_identity')or q['factor_cache_identity'](data_root,target,snapshot)!=value['factor_cache_identity']:
        raise q['QfqGateError']('DELTA_RESUME_FACTOR_STATE_CHANGED')
    run=Path(value['source_run']);generation=q['canonical_sha'](dict(target=target,baseline_panel_sha256=baseline,**old))
    expected=Path(data_root).parents[1]/'research_panel_daily/a_formula_runs'/('qfq_'+generation[:20])
    status=json.loads(q['_source'](value['source_status'],owner='original delta terminal status').read_text())
    if (run!=expected or value['source_generation']!=generation or value['source_status']['path']!=str(run/'stage_status.json')
            or status.get('status')not in {'FAILED','PAUSED'}or status.get('generation_id')!=generation
            or status.get('candidates')!=value['source_candidates']or status.get('adjustment_snapshot')!=value['original_snapshot']
            or any(status.get(k)!=v for k,v in old.items())):
        raise q['QfqGateError']('DELTA_RESUME_ORIGINAL_RUN_NOT_CLOSED')
    result={}
    validation=dict(run_id=generation,run_dir=run,target=target,identity=old,
        candidates={role:Path(path) for role,path in value['source_candidates'].items()},snapshot=snapshot)
    for code,ref in chunks.items():
        path=q['_source'](ref,owner='original delta checkpoint '+code);saved=_load_checkpoint(q,path,code)
        expected=run/'delta_checkpoints'/(code+'.'+saved['dependency']+'.json')
        sealed=ref.get('member')==code and path.parent==run/'delta_batch_seals'
        if (not (path==expected or sealed) or ('member' in ref and not sealed)
                or set(saved['logical_rows'])!=set(value['source_candidates']) or set(saved['has_target'])!=set(value['source_candidates'])):
            raise q['QfqGateError']('DELTA_RESUME_CHECKPOINT_PATH_OR_SCOPE:'+code)
        for role,item in saved['roles'].items():
            _validate_persisted_patch(q,validation,code,saved['dependency'],saved,role,item)
        result[code]=dict(checkpoint=ref,read_only_delta=True,source_generation=generation,
            source_run=str(run),source_candidates=value['source_candidates'])
    return result


def prepare_delta_resume(*,source_run,target_core,target_delta,independent_review,data_root):
    """Read only one explicitly named failed run; return a small sealed-ref body.

    Controller saves this immutable body and passes {path,sha256} through the
    existing authority checkpoint_resume argument. No live payload is written.
    """
    from ops import research_panel_qfq as owner
    q=vars(owner);run=Path(source_run);status_ref=dict(path=str(run/'stage_status.json'),sha256=owner.sha(run/'stage_status.json'))
    status=json.loads(owner._source(status_ref,owner='closed original delta run').read_text())
    keys=set(q['_GENERATION_TUPLE_KEYS'])|{'input_sha256','logical_reader_sha256','delta_owner_sha256','turnover_input_sha256'}
    identity={k:status[k]for k in keys}
    snapshot=json.loads(owner._source(status['adjustment_snapshot'],owner='original delta snapshot').read_text())
    files=sorted((run/'delta_checkpoints').glob('*.json'));chunks={}
    for p in files:
        code=p.name.split('.')[0]+'.'+p.name.split('.')[1]
        if code in chunks:raise owner.QfqGateError('DELTA_RESUME_DUPLICATE_STOCK')
        chunks[code]=dict(path=str(p),sha256=owner.sha(p))
    for code, sealed in _sealed_members(q,run).items():
        chunks.setdefault(code,{**sealed['reference'],'member':code})
    value=dict(schema=DELTA_RECOVERY_SCHEMA,recovery_scope='SAME_DAY_DELTA_PROCESS_V1',asof_date=status['asof_date'],source_run=str(run),source_generation=status['generation_id'],
        source_identity=identity,source_status=status_ref,source_candidates=status['candidates'],baseline_panel_sha256=status['baseline_panel_sha256'],
        original_snapshot=status['adjustment_snapshot'],source_core=dict(path=str(Path(target_core).parent/'research_panel_qfq.py'),sha256=identity['adapter_sha256']),
        source_delta=dict(path=str(Path(target_delta).parent/'research_panel_delta.py'),sha256=identity['delta_owner_sha256']),source_logical=dict(path=str(Path(target_core).parent/'research_panel_logical.py'),sha256=identity['logical_reader_sha256']),
        target_core=dict(path=str(target_core),sha256=owner.sha(Path(target_core))),target_delta=dict(path=str(target_delta),sha256=owner.sha(Path(target_delta))),target_logical=dict(path=str(Path(logical.__file__)),sha256=owner.sha(Path(logical.__file__))),
        independent_review=independent_review,completed_count=len(chunks),total_count=len(snapshot['symbols']),chunks=chunks,
        factor_cache_identity=owner.factor_cache_identity(Path(data_root),status['asof_date'],snapshot),**owner.FLAGS)
    # Original source refs belong to the old release, supplied by its truthful
    # delta_owner/adapter bytes in the controller's source-binding inventory.
    review=json.loads(owner._source(independent_review,owner='parallel review').read_text())
    binding=json.loads(owner._source(review['source_binding'],owner='parallel source binding').read_text())
    for key,relative in [('source_core','ops/research_panel_qfq.py'),('source_delta','ops/research_panel_delta.py'),('source_logical','ops/research_panel_logical.py')]:
        item=next(i for i in binding['items']if i['owner']=='main'and i['target_relative']==relative)
        value[key]['path']=item['target']
    load_delta_recovery(q,value,snapshot,{**identity,'adapter_sha256':value['target_core']['sha256'],'delta_owner_sha256':value['target_delta']['sha256'],'logical_reader_sha256':value['target_logical']['sha256']},value['baseline_panel_sha256'],Path(data_root))
    if files!=sorted((run/'delta_checkpoints').glob('*.json'))or owner.sha(run/'stage_status.json')!=status_ref['sha256']:
        raise owner.QfqGateError('DELTA_RESUME_ORIGINAL_RUN_CHANGED')
    return value
