"""Score/action adapter at the existing daily-product completion boundary.

The preserved KB authorities own every rule. This adapter saves only requested
new daily observations, reuses exact stock-prefix caches, and never runs on GET.
"""
from __future__ import annotations
from ops.research_panel_logical import dataset as panel_dataset, parquet as pq
import ast
from concurrent.futures import ProcessPoolExecutor
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import textwrap

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SCHEMA = 'v4.workbench.daily_score_action.v1'
COLUMNS = ['ts_code','trade_date','open','high','low','close','volume','pre_close','pct_chg','user_v1_sell_signal_daily']


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
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path or sha(path) != ref['sha256']:
        raise ValueError('SCORE_REFERENCE_CONFLICT')
    return json.loads(path.read_bytes())


def save(root, value):
    raw = canonical(value) + b'\n'
    path = Path(root) / (hashlib.sha256(raw).hexdigest() + '.json')
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
    paths = [Path(m.__file__) for m in (kb_signal_authority, kb_hold_score, kb_n_structure, kb_action_authority)]
    paths += [Path(__file__).resolve()]
    paths += [root/'contracts'/name for name in ('a_share_kb_fields_v1.json','a_share_kb_hold_score_v1.json','a_share_kb_n_structure_v1.json','a_share_kb_action_v1.json')]
    return {path.name: sha(path) for path in paths}


def target_kb(frame, dates):
    """Evaluate the original authority only on missing output dates.

    Its full-prefix indicator cache and the only two loop-carried counters are
    retained. No predicate/expression or default is replaced. Historical KB
    labels are neither regenerated nor overwritten. Default authority remains
    byte-identical to the accepted R5 source.
    """
    from ops import kb_signal_authority as kb
    tree = ast.parse(textwrap.dedent(inspect.getsource(kb.append_kb_signals)))
    fn = tree.body[0]
    loop = next(n for n in fn.body if isinstance(n, ast.For) and ast.unparse(n.target) == '(i, day)')
    # Before the original per-row body: advance exactly its two state updates
    # for skipped output rows. Indicator recurrence is in the original _cache.
    skip = ast.parse('''
if int(day.trade_date) not in _requested_output_dates:
    if close_prefix and n >= 114 and cache['white'][i] > 0 and cache['yellow'][i] > 0:
        valid_line_indices.append(i)
    if n >= 9:
        color = 1 if cache['brick'][i] >= cache['brick'][i-1] else -1
        color_count = color_count + 1 if color == prev_color else 1
        prev_color = color
    for name in names:
        outputs[name].append(None)
    continue
''').body[0]
    # close_prefix and n are assigned before the first conditional.
    index = next(i for i, n in enumerate(loop.body) if isinstance(n, ast.If))
    loop.body.insert(index, skip)
    env = dict(kb.__dict__, _requested_output_dates=set(dates))
    exec(compile(ast.fix_missing_locations(tree), str(Path(kb.__file__)), 'exec'), env)
    return env['append_kb_signals'](frame)


def score_prefix(rows, previous=None):
    """Resume the exact preserved score recurrence, saving only its state."""
    from ops import kb_hold_score as owner
    from types import FunctionType
    tree=ast.parse(textwrap.dedent(inspect.getsource(owner.score_history)))
    fn=tree.body[0]
    # Keep all original rule expressions; supply the validated prefix state.
    loop=next(node for node in fn.body if isinstance(node,ast.For))
    original_init=fn.body[:fn.body.index(loop)]
    init=ast.parse("""
result=[]
closes=list(saved.get('closes', []));highs=list(saved.get('highs', []));lows=list(saved.get('lows', []))
previous_date=saved.get('previous_date', 0)
k=saved.get('k', 50.0);d=saved.get('d', 50.0)
kdj_prefix_valid=saved.get('kdj_prefix_valid', True)
prefix_count=saved.get('count', 0);retained_count=len(closes)
""").body
    fn.body=init+fn.body[fn.body.index(loop):]
    for node in ast.walk(loop):
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='n':
            node.value=ast.parse('prefix_count + len(closes) - retained_count',mode='eval').body
    final=fn.body[-1]
    assert isinstance(final,ast.Return)
    final.value=ast.parse("(result, dict(closes=closes[-24:],highs=highs[-9:],lows=lows[-9:],previous_date=previous_date,k=k,d=d,kdj_prefix_valid=kdj_prefix_valid,count=prefix_count+len(rows)))",mode='eval').body
    env=dict(owner.__dict__,saved=previous or {})
    exec(compile(ast.fix_missing_locations(tree),str(Path(owner.__file__)),'exec'),env)
    raw,state=env['score_history'](rows)
    # Run the unchanged original source-to-J validation/supplemental mapping.
    project=FunctionType(owner.project_single_history.__code__,dict(owner.__dict__,score_history=lambda _:raw),owner.project_single_history.__name__,owner.project_single_history.__defaults__)
    project.__kwdefaults__=owner.project_single_history.__kwdefaults__
    return project(rows[0]['ts_code'],rows,scope='ADMITTED_A_SHARE'),state


def plain(value):
    if hasattr(value, 'item'): value = value.item()
    if isinstance(value, float) and not math.isfinite(value): return None
    return value


def project_symbol(args):
    symbol, rows, target, basis, root, rules, qualification = args
    from ops.kb_hold_score import project_single_history, apply_n_score
    from ops.kb_n_structure import project_n_history,n_prefix_sha256
    from ops.kb_action_authority import project_action
    import pandas as pd
    rows = [{k: plain(v) for k,v in r.items()} for r in rows]
    rows.sort(key=lambda r: int(r['trade_date']))
    prefix = digest(rows)
    # Admission is a real input even when every price byte is unchanged.
    # Bind status/reason explicitly and the complete canonical evidence object
    # (raw refs, acceptance receipts, dates and their SHAs) before cache lookup.
    qualification = qualification if isinstance(qualification, dict) else {
        'status': 'UNKNOWN', 'reason': 'QUALIFICATION_NOT_BOUND'}
    admission = dict(status=qualification.get('status'), reason=qualification.get('reason'),
                     evidence_sha256=digest(qualification))
    identity = dict(symbol=symbol, trade_date=target, price_basis=basis, rules=rules,
                    prefix_sha256=prefix, qualification=admission)
    key = digest(identity)
    cachepath = Path(root)/'stock_cache'/symbol/(key+'.json')
    if cachepath.is_file():
        record=json.loads(cachepath.read_bytes())
        if record.get('cache_identity') != identity: raise ValueError('SCORE_CACHE_IDENTITY_CONFLICT')
        return dict(symbol=symbol, record=record, reused=True)
    common = dict(symbol=symbol, trade_date=target, cache_identity=identity, historical_PIT=False, **FLAGS)
    if (qualification.get('status')!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
            or not rows or str(rows[-1]['trade_date']) != str(target)):
        record=dict(status='UNKNOWN', reason=qualification.get('reason') or 'EXACT_TARGET_BAR_UNAVAILABLE',
                    hold_score=None, action=None, **common)
    else:
        frame=pd.DataFrame(rows).rename(columns={'volume':'vol'})
        result=target_kb(frame, {int(target)})
        target_kb_row={k:plain(v) for k,v in result.iloc[-1].to_dict().items() if k.startswith('kb_')}
        # Preserve the original score caller's independent pinned J authority.
        from ops.kb_signal_authority import project_bound_kb_j
        js=project_bound_kb_j(symbol,rows)
        source=[dict(r,volume=r['volume'],kb_b1_j=j['kb_b1_j']) for r,j in zip(rows,js)]
        prior=None;offset=0
        for path in sorted(cachepath.parent.glob('*.json')) if cachepath.parent.exists() else []:
            candidate=json.loads(path.read_bytes());ci=candidate.get('cache_identity',{})
            count=candidate.get('input_rows',0)
            if (candidate.get('recurrence') and ci.get('rules')==rules and ci.get('price_basis')==basis
                    and 0<count<len(rows) and count>offset and str(candidate.get('trade_date'))<str(target)
                    and digest(rows[:count])==ci.get('prefix_sha256')):
                prior=candidate;offset=count
        score,score_state=score_prefix(source[offset:],prior['recurrence']['score'] if prior else None)
        nidentity=dict(generation_id='daily-score:'+key,input_sha256=prefix,
            rule_sha256=rules['a_share_kb_n_structure_v1.json'],helper_sha256=rules['kb_n_structure.py'],
            calendar_sha256=None,price_basis_sha256=digest(basis),price_basis='QFQ_ASOF')
        if prior:
            # The unchanged N owner checks the checkpoint integrity and exact
            # current HLC prefix; the new outer record binds the new source.
            old=prior['recurrence']['n']
            nidentity=dict(old['identity'])
            ns,checkpoint=project_n_history(symbol,rows[offset:],identity=nidentity,
                checkpoint=old,expected_prefix_sha256=n_prefix_sha256(symbol,rows[:offset]))
        else:ns,checkpoint=project_n_history(symbol,rows,identity=nidentity)
        score=apply_n_score(symbol,source[offset:],score,ns,rule_sha256=nidentity['rule_sha256'],
                           helper_sha256=nidentity['helper_sha256'],scope='ADMITTED_A_SHARE')
        current_score=score[-1]
        # Action authority consumes the accepted KB state and independent
        # original sell signal; preserve nullable inputs without bool coercion.
        action=project_action(target_kb_row | current_score |
            {'user_v1_sell_signal_daily':rows[-1].get('user_v1_sell_signal_daily')},
            rule_sha256=rules['a_share_kb_action_v1.json'])
        record=dict(status='MATERIALIZED',hold_score=current_score,action=action,kb=target_kb_row,
                    n_structure=ns[-1]['kb_n_structure'],input_rows=len(rows),
                    recurrence=dict(score=score_state,n=checkpoint),incremental_prefix_rows=offset,new_observation_rows=len(rows)-offset,**common)
    cachepath.parent.mkdir(parents=True,exist_ok=True)
    raw=canonical(record)+b'\n'
    if cachepath.exists() and cachepath.read_bytes()!=raw:raise ValueError('SCORE_CACHE_MOVED')
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
        args.append((symbol,buckets[symbol],target,context.identity['basis'],str(root),rules,source.get('qualification',{})))
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
        source_selector_sha256=context.identity['selector_artifact_sha256'],rules=rules,price_basis=context.identity['basis'],
        items=items,counts=dict(total=len(items),materialized=sum(r['record']['status']=='MATERIALIZED' for r in results),
        unknown=sum(r['record']['status']=='UNKNOWN' for r in results)),
        historical_PIT=False,**FLAGS)
    context.unchanged()
    context._score_action_last_run=dict(reused=sum(r['reused'] for r in results),computed=sum(not r['reused'] for r in results))
    ref=save(root/'indexes',value)
    return dict(status='READY' if not value['counts']['unknown'] else 'PARTIAL_WITH_UNKNOWN',index=ref,
        data_date=target,source_generation=context.generation,input_sha256=context.identity['input_sha256'],
        numeric_manifest=numeric_manifest,counts=value['counts'],**FLAGS)


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
    path=stage/'PUBLICATION_PLAN.json';path.write_bytes(canonical(plan)+b'\n')
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
