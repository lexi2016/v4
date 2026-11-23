"""Score/action adapter at the existing daily-product completion boundary.

The preserved KB authorities own every rule. This adapter saves only requested
new daily observations, reuses exact stock-prefix caches, and never runs on GET.
"""
from __future__ import annotations
from ops import workbench_score_calculation as calculation
from ops.research_panel_logical import dataset as panel_dataset, parquet as pq
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SCHEMA = 'v4.workbench.daily_score_action.v1'
COLUMNS = calculation.COLUMNS
WRITER_MODULE = 'materialize_workbench_score_action.py'
CALCULATION_MODULE = 'workbench_score_calculation.py'
# Only the audited extraction is semantically equivalent to these old caches.
LEGACY_EQUIVALENT_CALCULATION_SHA256 = '4e039f65ef92e597bed7af212a7d98ccf8ca523100b1fc854e3a0b177f74b152'
LEGACY_WRITER_SHA256S = (
    'c70c1d8bd6dba9fe2e89dba88d7ded5cff05342ee13ef1516087355b966f52df',
    '005c8b3ef4723ffc56385d2ad91d5487e3cd3aeb30d56886671f063e39c96b1b',
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(path):
    return dict(path=str(Path(path).resolve()), sha256=sha(path))


def checked(ref):
    path = Path(ref['path'])
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError('SCORE_REFERENCE_CONFLICT')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise ValueError('SCORE_REFERENCE_CONFLICT')
    return json.loads(raw)


def save(root, value):
    raw = canonical(value) + b'\n'
    path = Path(root) / (hashlib.sha256(raw).hexdigest() + '.json')
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError('SCORE_IMMUTABLE_CONFLICT')
        return reference(path)
    from ops.research_daily_capacity import serialized_write
    with serialized_write(path, raw, copies=1):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != raw: raise ValueError('SCORE_IMMUTABLE_CONFLICT')
        else:
            tmp = path.with_name('.' + path.name + '.' + str(os.getpid()))
            tmp.write_bytes(raw)
            os.replace(tmp, path)
        return reference(path)


def authority_identity():
    from ops import kb_signal_authority, kb_hold_score, kb_n_structure, kb_action_authority
    root = Path(__file__).resolve().parents[1]
    paths = [Path(m.__file__) for m in (kb_signal_authority, kb_hold_score, kb_n_structure, kb_action_authority, calculation)]
    paths += [root/'contracts'/name for name in ('a_share_kb_fields_v1.json','a_share_kb_hold_score_v1.json','a_share_kb_n_structure_v1.json','a_share_kb_action_v1.json')]
    return {path.name: sha(path) for path in paths}


def writer_provenance():
    path = Path(__file__).resolve()
    return dict(module=path.name, sha256=sha(path))


def legacy_rule_maps(rules):
    if rules.get(CALCULATION_MODULE) != LEGACY_EQUIVALENT_CALCULATION_SHA256:
        return ()
    shared = {name: value for name, value in rules.items() if name != CALCULATION_MODULE}
    return tuple(dict(shared, **{WRITER_MODULE: value}) for value in LEGACY_WRITER_SHA256S)


def matches_authority(index, expected_rules):
    rules = index.get('rules')
    if not isinstance(rules, dict):
        return False
    if WRITER_MODULE in rules:
        return index.get('writer_provenance') is None and rules in legacy_rule_maps(expected_rules)
    return rules == expected_rules and calculation.valid_writer_provenance(index.get('writer_provenance'))


def row_writer_sha256s(rows):
    writers = set()
    for row in rows:
        provenance = row.get('writer_provenance')
        if not calculation.valid_writer_provenance(provenance):
            raise ValueError('SCORE_ROW_WRITER_PROVENANCE_INVALID')
        writers.add(provenance['sha256'])
    return sorted(writers)


def project_symbol(args):
    symbol, rows, target, basis, root, rules, provenance, qualification = args
    rows, qualification, identity = calculation.normalize_score_input(
        symbol, rows, target, basis, rules, qualification)
    key = digest(identity)
    cachepath = Path(root) / 'stock_cache' / symbol / (key + '.json')
    if cachepath.is_file():
        record = json.loads(cachepath.read_bytes())
        if (record.get('cache_identity') != identity
                or not calculation.valid_writer_provenance(record.get('writer_provenance'))):
            raise ValueError('SCORE_CACHE_IDENTITY_CONFLICT')
        return dict(symbol=symbol, record=record, reused=True)

    prior_records = (json.loads(path.read_bytes()) for path in sorted(cachepath.parent.glob('*.json')))
    record = calculation.calculate_score(symbol, rows, target, basis, rules, qualification,
                                         identity, prior_records, legacy_rule_maps(rules))
    record['writer_provenance'] = provenance
    raw = canonical(record) + b'\n'
    if cachepath.exists() and cachepath.read_bytes() != raw:
        raise ValueError('SCORE_CACHE_MOVED')
    from ops.research_daily_capacity import serialized_write
    with serialized_write(cachepath, raw):
        cachepath.parent.mkdir(parents=True, exist_ok=True)
        cachepath.write_bytes(raw)
    return dict(symbol=symbol, record=record, reused=False)


def materialize(context, product, numeric_manifest, *, output_root=None, workers=None, symbols=None):
    """Called by original materialize_daily_product, after numeric closure.

    A replay passes output_root to keep publication isolated. The returned
    descriptor is attached by the original owner to its existing index/event.
    """
    import pyarrow.dataset as ds
    context.unchanged()
    root=Path(output_root) if output_root is not None else context.root/'score_action'
    target=str(context.target)
    requested=sorted(symbols or [r['symbol'] for r in product['rows']])
    if not set(requested)<=set(product['row_refs']):raise ValueError('SCORE_SCOPE_CONFLICT')
    rules=authority_identity()
    provenance=writer_provenance()
    # One shared Parquet scan for this missing output batch, no per-stock scan.
    dataset=panel_dataset(context.panel,format='parquet')
    columns=[c for c in COLUMNS if c in dataset.schema.names]
    if set(COLUMNS)-set(columns):raise ValueError('SCORE_INPUT_COLUMNS_UNBOUND')
    table=pq.read_table(context.panel,columns=columns,filters=[('ts_code','in',requested),('trade_date','<=',target)])
    buckets={s:[] for s in requested}
    for row in table.to_pylist():buckets[row['ts_code']].append(row)
    args=[]
    for symbol in requested:
        source=checked(product['row_refs'][symbol])
        if source.get('symbol')!=symbol or source.get('data_date')!=target:raise ValueError('SCORE_ADMISSION_ROW_CONFLICT')
        args.append((symbol,buckets[symbol],target,context.identity['basis'],str(root),rules,provenance,source.get('qualification',{})))
    if workers is None:
        from ops.research_daily_product_parallel import memory_state,resource_plan
        workers=resource_plan(memory_state(),max(1,len(args)))['workers']
    if workers<=1:results=list(map(project_symbol,args))
    else:
        import multiprocessing
        with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
            results=list(pool.map(project_symbol,args,chunksize=1,buffersize=workers*2))
    items={r['symbol']:save(root/'records',r['record']) for r in results}
    value=dict(schema=SCHEMA,data_date=target,source_generation=context.generation,
        input_sha256=context.identity['input_sha256'],numeric_manifest=numeric_manifest,
        source_selector_sha256=context.identity['selector_artifact_sha256'],rules=rules,
        writer_provenance=provenance,price_basis=context.identity['basis'],
        row_writer_sha256s=row_writer_sha256s(r['record'] for r in results),
        items=items,counts=dict(total=len(items),materialized=sum(r['record']['status']=='MATERIALIZED' for r in results),
        unknown=sum(r['record']['status']=='UNKNOWN' for r in results)),
        historical_PIT=False,**FLAGS)
    context.unchanged()
    context._score_action_last_run=dict(reused=sum(r['reused'] for r in results),computed=sum(not r['reused'] for r in results))
    ref=save(root/'indexes',value)
    return dict(status='READY' if not value['counts']['unknown'] else 'PARTIAL_WITH_UNKNOWN',index=ref,
        data_date=target,source_generation=context.generation,input_sha256=context.identity['input_sha256'],
        numeric_manifest=numeric_manifest,counts=value['counts'],**FLAGS)


def _score_union_index(score_root, base_descriptor, new_descriptor, identity, basis, selector_sha):
    def read_index(descriptor):
        ref = descriptor['index']
        if (not Path(ref['path']).is_relative_to(score_root)
                or any(descriptor.get(key) != value for key, value in identity.items())
                or any(descriptor.get(key) is not value for key, value in FLAGS.items())):
            raise ValueError('SCORE_UNION_DESCRIPTOR_CONFLICT')
        value = checked(ref)
        if (value.get('schema') != SCHEMA or value.get('historical_PIT') is not False
                or any(value.get(key) != expected for key, expected in identity.items())
                or any(value.get(key) is not expected for key, expected in FLAGS.items())
                or value.get('counts') != descriptor.get('counts')
                or value.get('price_basis') != basis
                or value.get('source_selector_sha256') != selector_sha
                or not matches_authority(value, expected_rules)
                or not isinstance(value.get('items'), dict)
                or not isinstance(value.get('counts'), dict)
                or value['counts'].get('total') != len(value['items'])):
            raise ValueError('SCORE_UNION_INDEX_CONFLICT')
        return value

    expected_rules = authority_identity()
    new_index = read_index(new_descriptor)
    base_index = read_index(base_descriptor) if base_descriptor else new_index
    if base_index['rules'] != new_index['rules']:
        raise ValueError('SCORE_UNION_ROW_ENCODING_CONFLICT')
    items = dict(base_index['items'])
    for symbol, ref in new_index['items'].items():
        prior_ref = items.get(symbol)
        if prior_ref is not None and prior_ref != ref:
            raise ValueError('SCORE_UNION_OVERLAP_CONFLICT')
        if prior_ref is None:
            items[symbol] = ref
    counts = dict(total=len(items), materialized=0, unknown=0)
    records = {}
    new_encoding = WRITER_MODULE not in base_index['rules']
    for symbol, ref in items.items():
        if not Path(ref['path']).is_relative_to(score_root):
            raise ValueError('SCORE_UNION_ROW_ROOT_CONFLICT')
        row = checked(ref)
        cache = row.get('cache_identity') or {}
        outcome = row.get('status')
        if (row.get('symbol') != symbol or str(row.get('trade_date')) != identity['data_date']
                or row.get('historical_PIT') is not False
                or any(row.get(key) is not value for key, value in FLAGS.items())
                or cache.get('rules') != base_index['rules']
                or cache.get('writer_provenance') is not None
                or cache.get('price_basis') != basis
                or outcome not in {'MATERIALIZED', 'UNKNOWN'}):
            raise ValueError('SCORE_UNION_ROW_CONFLICT')
        counts[outcome.lower()] += 1
        records[symbol] = row
    result = dict(base_index, items=items, counts=counts)
    if new_encoding:
        for source_index in (base_index, new_index):
            observed = row_writer_sha256s(records[symbol] for symbol in source_index['items'])
            if source_index.get('row_writer_sha256s') != observed:
                raise ValueError('SCORE_UNION_WRITER_PARTITION_CONFLICT')
        result['row_writer_sha256s'] = row_writer_sha256s(records.values())
    elif any(row.get('writer_provenance') is not None for row in records.values()):
        raise ValueError('SCORE_UNION_LEGACY_WRITER_CONFLICT')
    return result


def publish_formula_score_union(context, descriptor, stage_root):
    """Add the committed roster to the existing date through the Main CAS owner."""
    from ops import research_panel_daily_product as owner
    from ops.sync_stock_history_completion import DEFAULT_OWNER_LOCK, publish

    root = Path(context.root).resolve(strict=True)
    stage_root = Path(stage_root).resolve()
    if stage_root == root or stage_root.is_relative_to(root):
        raise ValueError('SCORE_STAGE_NOT_ISOLATED')
    context.unchanged()
    index_ref = reference(root / 'index.json')
    event_ref = reference(root / 'events/latest.json')
    index, event = checked(index_ref), checked(event_ref)
    day = str(context.target)
    numeric = index.get('dates', {}).get(day)
    if (not isinstance(numeric, dict) or index.get('latest_date') != day
            or str(event.get('data_date')) != day or event.get('manifest') != numeric
            or event.get('source_generation') != context.generation
            or event.get('input_sha256') != context.identity['input_sha256']):
        raise ValueError('SCORE_UNION_NUMERIC_MOVED')
    identity = dict(data_date=day, source_generation=context.generation,
                    input_sha256=context.identity['input_sha256'], numeric_manifest=numeric)
    incumbent = index.get('score_action', {}).get(day)
    if not incumbent or not incumbent.get('index'):
        incumbent = None
    value = _score_union_index(root / 'score_action', incumbent, descriptor, identity,
                               context.identity['basis'], context.identity['selector_artifact_sha256'])
    if incumbent is not None and value == checked(incumbent['index']):
        return dict(status='ALREADY_PUBLISHED_SCORE_UNION', descriptor=incumbent, **FLAGS)
    counts = value['counts']
    if value.get('writer_provenance') is not None:
        value['writer_provenance'] = writer_provenance()
    stage = stage_root / digest([index_ref['sha256'], event_ref['sha256'], descriptor['index']['sha256']])
    staged = save(stage / 'assets', value)
    target = root / 'score_action' / 'indexes' / Path(staged['path']).name
    merged = dict(descriptor, index=dict(path=str(target), sha256=staged['sha256']), counts=counts,
                  status='PARTIAL_WITH_UNKNOWN' if counts['unknown'] else 'READY')
    new_index = dict(index, score_action={**index.get('score_action', {}), day: merged})
    new_event = dict(event, score_action=merged)
    new_event['event_id'] = digest({key: value for key, value in new_event.items() if key != 'event_id'})
    lock = DEFAULT_OWNER_LOCK
    stat = lock.lstat()
    if lock.is_symlink() or not lock.is_file():
        raise ValueError('SCORE_OWNER_LOCK_INVALID')
    plan = dict(status='PREPARED_FORMULA_SCORE_UNION',
                owner_publisher=reference(owner.__file__), shared_owner_lock=dict(
                    path=str(lock), device=stat.st_dev, inode=stat.st_ino),
                target_root=str(root), stage=str(stage), expected_index=index_ref, expected_event=event_ref,
                immutable_files={str(target): staged}, staged_index=save(stage / 'index', new_index),
                staged_event=save(stage / 'event', new_event), completed=sorted(value['items']), **FLAGS)
    context.unchanged()
    receipt = publish(plan)
    return dict(status='PUBLISHED_SCORE_UNION', descriptor=merged,
                index=receipt['index'], event=receipt['event'], **FLAGS)


def prepare_publication(descriptor_ref, config_ref, stage):
    """Prepare only; the original shared-lock publisher owns the final writes.

    Re-run preparation after another module publishes. Numeric manifest, rows,
    company modules and all other index fields are copied unchanged from CAS.
    """
    import copy
    descriptor=checked(descriptor_ref);config=checked(config_ref)
    root=Path(config['product_root']).resolve();stage=Path(stage).resolve()
    if stage==root or stage.is_relative_to(root):raise ValueError('SCORE_STAGE_NOT_ISOLATED')
    index_ref=reference(root/'index.json');event_ref=reference(root/'events/latest.json')
    index=checked(index_ref);event=checked(event_ref);day=descriptor['data_date']
    if index.get('dates',{}).get(day)!=descriptor['numeric_manifest']:raise ValueError('SCORE_NUMERIC_MOVED')
    source_index=checked(descriptor['index'])
    if source_index['numeric_manifest']!=descriptor['numeric_manifest']:raise ValueError('SCORE_PREPARED_IDENTITY_CONFLICT')
    files={};items={};targetbase=root/'score_action'
    for symbol,ref in source_index['items'].items():
        row=checked(ref)
        if row['symbol']!=symbol or str(row['trade_date'])!=day:raise ValueError('SCORE_PREPARED_ROW_CONFLICT')
        # The original owner stores this immutable file as both a read record
        # and the reusable per-stock recurrence, without duplicating bytes.
        target=targetbase/'stock_cache'/symbol/(digest(row['cache_identity'])+'.json')
        staged=save(stage/'assets',row);files[str(target)]=staged
        items[symbol]=dict(path=str(target),sha256=staged['sha256'])
    final_index=dict(source_index,items=items)
    staged=save(stage/'assets',final_index);target=targetbase/'indexes'/Path(staged['path']).name
    files[str(target)]=staged
    final_descriptor=dict(descriptor,index=dict(path=str(target),sha256=staged['sha256']))
    new_index=copy.deepcopy(index);new_index.setdefault('score_action',{})[day]=final_descriptor
    new_event=copy.deepcopy(event)
    if day==index.get('latest_date'):
        new_event['score_action']=final_descriptor
        new_event['event_id']=digest({k:v for k,v in new_event.items() if k!='event_id'})
    lock=Path(config['owner_lock']);st=lock.lstat()
    if lock.is_symlink() or not lock.is_file():raise ValueError('SCORE_OWNER_LOCK_INVALID')
    plan=dict(schema='V4_SCORE_ACTION_PUBLICATION_PLAN_V1',status='PREPARED_NOT_PUBLISHED',
        descriptor=final_descriptor,prepared_descriptor=descriptor_ref,config=config_ref,
        publication_adapter=config['publication_adapter'],owner_publisher=config['owner_publisher'],
        shared_owner_lock=dict(path=str(lock),device=st.st_dev,inode=st.st_ino),target_root=str(root),stage=str(stage),
        expected_index=index_ref,expected_event=event_ref,immutable_files=files,
        staged_index=save(stage/'index',new_index),staged_event=save(stage/'event',new_event),
        completed=sorted(items),numeric_manifest=descriptor['numeric_manifest'],**FLAGS)
    stage.mkdir(parents=True,exist_ok=True)
    path=stage/'PUBLICATION_PLAN.json'
    from ops.research_daily_capacity import serialized_write
    raw=canonical(plan)+b'\n'
    with serialized_write(path,raw):path.write_bytes(raw)
    return reference(path)


def publish(plan_ref):
    """Explicit post-review call only: unchanged existing A_LONG/CAS owner."""
    import importlib.util
    plan=checked(plan_ref)
    if plan.get('schema')!='V4_SCORE_ACTION_PUBLICATION_PLAN_V1' or any(plan.get(k)!=v for k,v in FLAGS.items()):
        raise ValueError('SCORE_PUBLICATION_PLAN_CONFLICT')
    config=checked(plan['config'])
    for key in ('publication_adapter','owner_publisher'):
        if plan[key]!=config[key] or sha(plan[key]['path'])!=plan[key]['sha256']:raise ValueError('SCORE_PUBLISHER_IDENTITY_CONFLICT')
    ref=plan['publication_adapter'];spec=importlib.util.spec_from_file_location('original_score_shared_publisher',ref['path'])
    owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    return owner.publish(plan)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-publication',type=Path)
    parser.add_argument('--publish',type=Path)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--config-sha256')
    parser.add_argument('--stage',type=Path)
    args=parser.parse_args()
    if bool(args.prepare_publication)==bool(args.publish):parser.error('exactly one action required')
    ref=dict(path=str((args.prepare_publication or args.publish).resolve()),sha256=args.sha256)
    result=(prepare_publication(ref,dict(path=str(args.config.resolve()),sha256=args.config_sha256),args.stage)
            if args.prepare_publication else publish(ref))
    print(json.dumps(result,ensure_ascii=False,indent=2))
