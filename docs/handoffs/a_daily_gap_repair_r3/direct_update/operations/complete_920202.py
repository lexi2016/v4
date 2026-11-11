"""One dated source-metadata completion, using existing owner compute/CAS.

Default inspect is read-only. prepare stages a reviewed operation, not activation.
No acquisition, new generation, panel calculation, service operation or source edit.
"""
from pathlib import Path
import argparse
import copy
import fcntl
import hashlib
import json
import os
import plistlib
import sys

APP = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-panel-daily-source-fix-20261111-r2/v4-panel-daily-source-fix-20261111-r2-main/app')
R3 = Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/top200_yesterday_20261110/source_gap_repair_r3')
HERE = Path(__file__).resolve().parent
SYMBOL = '920202.BJ'
DAY = '20261110'
GEN = '231df8b469ade0ba8e6286d6cee624353aa46a5568cca569ffdf286bb7c28f81'
SNAP = '8931359eef37cb114643f635e936934b2bb0678406df4bde2964ca899de2632c'
NATIVE = 'e70ffacad074aa8a9445427ecf31f87621066f5bd4a1b657f995e98cee94842b'
EXPECTED = {'original': 'UNKNOWN', 'nav_smallk': 'FALSE', 'nav_pullback': 'UNKNOWN', 'nav_breakout': 'FALSE'}
PINS = {'ops/research_panel_qfq.py': '7b1f6b4ef739c7074cfcb1e4b1fda6910d4c02e70f8bf5bf653aaf696a95ca13',
        'ops/research_panel_daily_source.py': '454907923172ce3c97a0555aa3ae67147f16c71a993210bbc3024ecb563f9122'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def setup():
    for name, expected in PINS.items():
        require(hashlib.sha256((APP/name).read_bytes()).hexdigest() == expected, 'FROZEN_RUNTIME_DRIFT:'+name)
    env = plistlib.loads(Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.scheduler.plist').read_bytes())['EnvironmentVariables']
    os.environ.update(env)
    # This one row has no TRUE event. Use the original direct statistics path;
    # prepare never writes the shared event-case SQLite cache.
    os.environ.pop('V4_RESEARCH_EVENT_CASE_CACHE', None)
    sys.path.insert(0, str(APP))
    from ops import research_panel_daily_product as owner
    from ops.sync_stock_history_completion import Staging, DEFAULT_OWNER_LOCK
    return owner, Staging, DEFAULT_OWNER_LOCK, env


def load(owner, ref):
    return json.loads(owner.checked(ref).read_bytes())


def idle(lock):
    fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)


def context(owner, env):
    cfg = Path(env['V4_RESEARCH_DAILY_PRODUCT_CONFIG'])
    c = owner.SourceContext(Path(env['V4_RESEARCH_PANEL_A_DATA_ROOT']), int(DAY), source_config=(json.loads(cfg.read_bytes()), owner.reference(cfg)))
    c.root = Path(env['V4_A_SHARE_DAILY_PRODUCT_ROOT'])/'daily_products/a_share'
    require(c.generation == GEN and c.snapshot_ref['sha256'] == SNAP, 'EXACT_GENERATION_MOVED')
    require(c.config['admission_helper']['sha256'] == '7d67ba9898ebc1e816d082ae43ca0f51e3a9bc16278a589c0104524af925047a', 'HELPER_DRIFT')
    item = c.snapshot['symbols'][SYMBOL]
    require(not any(k in item for k in ('history_end_date', 'accepted_evidence', 'source_config', 'source_policy')), 'ORIGINAL_MISSING_FIELDS_CHANGED')
    require(item['events'] == [] and item['event_coverage_complete'] is True, 'EVENT_SCOPE_CHANGED')
    return c


def fact(owner, c):
    import numpy as np
    import pyarrow.parquet as pq
    from ops import research_panel_qfq as q
    item = c.snapshot['symbols'][SYMBOL]
    oldroot = R3/'writer/920202'
    oldfact = owner.reference(oldroot/'SOURCE_FACTS.json')
    oldcheck = owner.reference(oldroot/'920202.BJ.parquet')
    ready = owner.reference(oldroot/'SINGLE_SYMBOL_READY.json')
    gate = owner.reference(oldroot/'ORIGINAL_SELECTOR_GATE.json')
    require(oldfact['sha256'] == 'a41a2e31cfd3f95fe715992bc3781f3e945919118615c57fab60c747fd4a51b4'
            and oldcheck['sha256'] == '854ce13738100406a4fdba8f087e9fdef9e85288a1af2e4d2cc71f974542da54'
            and gate['sha256'] == '4bcf1ca5a657b967c4101ebd03281abf2891ed244a4b7adf14a4d346bbae3b1f', 'OLD_SINGLE_SYMBOL_PROOF_DRIFT')
    evidence = load(owner, oldfact)
    require(load(owner, ready)['status'] == 'SINGLE_SYMBOL_GATE_PASS' and load(owner, gate)['status'] == 'PASS', 'OLD_SINGLE_SYMBOL_NOT_PASS')
    for key in ('native', 'current_fallback', 'current_witness', 'existing_owner'):
        owner.checked(evidence[key])
    for value in evidence['current_detector'].values():
        if isinstance(value, dict) and 'path' in value:
            owner.checked(value)
    native = next(ref for ref in item['raw_files'] if ref['path'].endswith('/bj920202.day'))
    require(native['sha256'] == NATIVE, 'NATIVE_SCOPE_CHANGED')
    completion_ref = owner.reference(R3/'direct_update/native_execution/EIGHT_NATIVE_COMPLETION.json')
    completion = load(owner, completion_ref)
    entries = [v for v in completion['items'] if v['path'] == native['path']]
    require(completion['status'] == 'EIGHT_NATIVE_COMPLETE_NO_FORMULA_OR_PANEL_BUILD'
            and completion['network_requests'] == 0 and len(entries) == 1
            and entries[0]['after_sha256'] == NATIVE and entries[0]['status'] == 'APPLIED_NATIVE_ONLY'
            and entries[0]['source_mode'] == 'CAPTURE_REPLAY', 'CURRENT_NATIVE_ACCEPTANCE_CONFLICT')
    fallback_ref = owner.reference(Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/runtime/cache/data_layer_daily_formula_increment_update_v1/tdx_official_adjustment_fallback.json'))
    fallback = load(owner, fallback_ref)['symbols'][SYMBOL]
    require(fallback['events'] == item['events'] and fallback['event_coverage_complete'] is True
            and fallback['history_coverage_start_date'] == 20260929 and fallback['history_coverage_end_date'] == int(DAY)
            and fallback['price_convention'] == evidence['adjustment_method'], 'CURRENT_FULL_WINDOW_FALLBACK_CONFLICT')
    for ref in fallback['source_files']:
        owner.checked(ref)
    worker = load(owner, owner.reference(Path(c.receipt['run_dir'])/'meta.json'))['formula_processing']['worker_context']
    driver_ref = dict(path=worker['driver_path'], sha256=worker['driver_sha256'])
    formula_ref = dict(path=worker['canonical_formula_path'], sha256=worker['canonical_formula_sha256'])
    driver, _ = q.authorities(owner.checked(driver_ref), owner.checked(formula_ref))
    raw = q.resolved_raw_history(SYMBOL, item, int(DAY), driver)
    require(len(raw) == 26 and not raw.trade_date.duplicated().any() and raw.trade_date.astype(int).tolist() == evidence['all_dates'], 'RAW_26_SCOPE_CONFLICT')
    adjusted = q.apply_adjustments(raw, item['events'], int(DAY))
    columns = ['open', 'high', 'low', 'close', 'vol', 'amount']
    expected = adjusted[columns].to_numpy(dtype='float64')
    roles = {}
    for role, path in {'old_single_checkpoint': str(oldcheck['path']), **c.receipt['candidates']}.items():
        p = Path(path); stamp = p.stat(); schema = pq.read_schema(p)
        volume = 'volume' if 'volume' in schema.names else 'vol'
        frame = pq.read_table(p, columns=['ts_code', 'trade_date', 'open', 'high', 'low', 'close', volume, 'amount'], filters=[('ts_code', '=', SYMBOL)]).to_pandas().sort_values('trade_date')
        values = frame.rename(columns={volume: 'vol'})[columns].to_numpy(dtype='float64')
        require(frame.trade_date.astype(int).tolist() == raw.trade_date.astype(int).tolist() and np.array_equal(values, expected) and p.stat() == stamp, 'FULL26_PAIR_PARITY_CONFLICT:'+role)
        roles[role] = dict(path=str(p), rows=26, values_sha256=owner.digest(dict(dates=raw.trade_date.astype(int).tolist(), columns=columns, values=values.tolist())),
                           stat=dict(size=stamp.st_size, mtime_ns=stamp.st_mtime_ns), sha256=oldcheck['sha256'] if role == 'old_single_checkpoint' else c.receipt['candidate_sha256'][role])
    c.unchanged()
    return dict(schema='V4_EXACT_920202_D10_GENERATION231_SOURCE_METADATA_V1', symbol=SYMBOL, target_date=int(DAY), source_generation=GEN,
                snapshot=c.snapshot_ref, producer_receipt=c.receipt_ref, source_identity=c.identity, source_config=c.config_ref,
                helper=c.config['admission_helper'], runtime_owner=owner.reference(Path(owner.__file__)), raw_owner=owner.reference(Path(q.__file__)),
                original_missing_fields=['history_end_date', 'accepted_evidence'], effective_history_end_date=int(DAY), raw_refs=item['raw_files'],
                events=[], resolved_rows=26, first_date=20260929, paired_roles=roles, old_source_fact=oldfact, old_single_gate=gate,
                current_fallback=fallback_ref, current_fallback_symbol_sha256=owner.digest(fallback), native_completion=completion_ref,
                driver=driver_ref, formula=formula_ref, runtime_dependencies=[owner.reference(APP/name) for name in (
                    'ops/sync_stock_history_completion.py', 'ops/render_original_formula_projection.py',
                    'domains/research_daily_product.py', 'domains/research_daily_statistics.py')],
                accepted_evidence=[oldfact, ready, completion_ref, fallback_ref],
                historical_PIT=False, future_automatic_admission='CANNOT_CONFIRM_NOT_CLAIMED', **owner.FLAGS)


def qualify(owner, c, typed, typed_ref):
    require(fact(owner, c) == typed, 'TYPED_FACT_DRIFT')
    args = (SYMBOL, DAY, c.footer, c.receipt, c.quarantine, GEN, Path(c.quarantine_ref['path']))
    original = c.helper.verify_symbol_admission(*args)
    require(original == dict(status='UNKNOWN', reason='CURRENT_SYMBOL_HISTORY_END_MISMATCH'), 'ORIGINAL_REASON_CHANGED')
    snapshot = copy.deepcopy(c.snapshot)
    snapshot['symbols'][SYMBOL]['history_end_date'] = int(DAY)
    previous = c.helper.read_json
    c.helper.read_json = lambda p: snapshot if Path(p) == Path(c.snapshot_ref['path']) else previous(p)
    try:
        date_only = c.helper.verify_symbol_admission(*args)
        require(date_only == dict(status='UNKNOWN', reason='CURRENT_SYMBOL_ACCEPTANCE_REFERENCES_MISSING'), 'DATE_ONLY_ORACLE_CHANGED')
        snapshot['symbols'][SYMBOL]['accepted_evidence'] = typed['accepted_evidence']
        result = c.helper.verify_symbol_admission(*args)
    finally:
        c.helper.read_json = previous
    require(result['status'] == 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH', 'UNCHANGED_VALIDATOR_REJECTED')
    result['history_end_metadata'] = dict(schema=typed['schema'], evidence=typed_ref, original_admission=original,
        date_only_admission=date_only, original_missing_fields=typed['original_missing_fields'], original_helper=typed['helper'],
        snapshot_bytes_unchanged=True, future_automatic_admission=False)
    return result


def inputs(owner, c):
    ir, er = owner.reference(c.root/'index.json'), owner.reference(c.root/'events/latest.json')
    completed = json.loads((R3/'direct_update/OWNER_COMPLETION_INDEX_REFS.json').read_bytes())
    require(ir == completed['index'] and er == completed['event']
            and ir['sha256'] == 'a837bf000345795bd0ec91bc885e102fe150236f03a468ead118b5a343da7bf1'
            and er['sha256'] == '248dd3cdf11746fb05c2c147483f6a1e9e686c634c30bf85512a9623795aa571', 'FROZEN_COMPLETION_INDEX_MOVED')
    index, event = load(owner, ir), load(owner, er)
    mr = index['dates'][DAY]; manifest = load(owner, mr); product = load(owner, manifest['artifact'])
    require(index['latest'] == mr and index['latest_date'] == DAY and event['manifest'] == mr and event['artifact'] == manifest['artifact']
            and event['source_generation'] == GEN and product['source_identity'] == c.identity
            and product['processed_count'] == len(product['row_refs']) == 5809 and not product['sample_only'], 'ACTUAL_COMPLETED_PRODUCT_REQUIRED')
    require(SYMBOL not in {r['symbol'] for r in product['rows']}, 'UNSELECTED_SYMBOL_SCOPE_CHANGED')
    return ir, er, index, event, mr, manifest, product


def prepare(owner, Staging, lock, c, output):
    idle(lock)
    ir, er, index, event, mr, manifest, product = inputs(owner, c)
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    typed = fact(owner, c); typed_ref = owner.save(output/'TYPED_FACT.json', typed, immutable=True)
    q = qualify(owner, c, typed, typed_ref)
    # Only the original single-symbol current-date calculation is run.
    actual_root = c.root; c.root = output/'calculation'
    c.qualify = lambda symbol: q if symbol == SYMBOL else (_ for _ in ()).throw(ValueError('OUTSIDE_SINGLE_SYMBOL'))
    row, cache, _ = owner.compute_stock(c, SYMBOL)
    c.root = actual_root
    require({g:row['evaluation']['groups'][g]['status'] for g in owner.GROUPS} == EXPECTED and row['groups'] == '', 'GENUINE_WARMUP_OR_GROUP_ORACLE_CHANGED')
    row.update(owner.FLAGS)
    # The daily owner serializes Decimal values as strings before a later
    # completion publisher receives the row. Preserve that exact boundary.
    row = json.loads(owner.canonical(row))
    writer = Staging(c.root, output/'staged')
    new = copy.deepcopy(product); oldrow = load(owner, product['row_refs'][SYMBOL])
    require(oldrow['qualification'] == dict(status='UNKNOWN', reason='CURRENT_SYMBOL_HISTORY_END_MISMATCH'), 'ACTUAL_OLD_ROW_SCOPE_CHANGED')
    new['row_refs'][SYMBOL] = writer.immutable('exact_metadata_rows/'+DAY, SYMBOL+'.json', row)
    for g in owner.GROUPS:
        before, after = oldrow['evaluation']['groups'][g]['status'], row['evaluation']['groups'][g]['status']
        new['three_value_counts'][g][before] -= 1
        new['three_value_counts'][g][after] = new['three_value_counts'][g].get(after, 0)+1
        new['group_counts'][g] = new['three_value_counts'][g].get('TRUE', 0)
    new['unknown_count'] += int(bool(row['pending_groups']))-int(bool(oldrow['pending_groups']))
    new['status'] = 'PARTIAL_WITH_ROWS' if new['unknown_count'] else 'READY'
    unchanged = [s for s in product['row_refs'] if s != SYMBOL and product['row_refs'][s] == new['row_refs'][s]]
    require(len(unchanged) == 5808 and new['rows'] == product['rows'] and new['unique_count'] == product['unique_count'], 'NON_TARGET_OR_MEMBERSHIP_DRIFT')
    artifact = writer.immutable('versions/'+DAY+'/'+GEN, 'product.json', new)
    nm = {**manifest, 'artifact':artifact, 'counts':new['three_value_counts'], 'status':new['status']}
    nmr = writer.immutable('exact_metadata_rows/'+DAY+'/manifests', 'manifest.json', nm)
    # Build all index-side metadata in staging. Chart view bytes are generated
    # by the original renderer only inside the locked publish refresh callback.
    ni, ne = copy.deepcopy(index), copy.deepcopy(event)
    ni['dates'][DAY] = nmr; ni['latest'] = nmr
    preserved_prior_views = {}
    for key in ('event_cases', 'display_names', 'company_materials', 'top200'):
        ref = index.get(key, {}).get(DAY)
        if not ref:
            continue
        value = load(owner, ref)
        if key == 'top200' and value['numeric_manifest'] != mr:
            # The completed original lane preserved this older view. This
            # one-symbol operation must neither relabel it nor recalculate it.
            preserved_prior_views[key] = dict(reference=ref, numeric_manifest=value['numeric_manifest'], status='PRIOR_BINDING_PRESERVED_NOT_CURRENTLY_CERTIFIED')
            continue
        if key == 'event_cases':
            origins = value.setdefault('case_numeric_origins', {})
            for symbol, shard in value['items'].items():
                origins.setdefault(symbol, load(owner, shard)['numeric_manifest'])
        if key == 'company_materials':
            value['source_numeric_manifest'] = value.get('source_numeric_manifest', value['numeric_manifest'])
        require(value['numeric_manifest'] == mr, 'AUXILIARY_MANIFEST_DRIFT:'+key)
        value['numeric_manifest'] = nmr
        ni[key][DAY] = writer.immutable(key+'/'+DAY, Path(ref['path']).name, value)
        if key in ne:
            ne[key] = ni[key][DAY]
    score = copy.deepcopy(index['score_action'][DAY]); score_index = load(owner, score['index'])
    require(score['numeric_manifest'] == score_index['numeric_manifest'] == mr and SYMBOL not in score_index['items'], 'SCORE_SCOPE_DRIFT')
    score_index['numeric_manifest'] = nmr
    score.update(numeric_manifest=nmr, index=writer.immutable('score_action/indexes', 'index.json', score_index))
    ni['score_action'][DAY] = score; ne['score_action'] = score
    v192 = copy.deepcopy(index['v192_assets'][DAY])
    require(not v192.get('module') and v192['status'] == 'CANNOT_CONFIRM' and v192['numeric_manifest'] == mr, 'V192_UNEXPECTED_SCOPE_CHANGE')
    v192['numeric_manifest'] = nmr; ni['v192_assets'][DAY] = v192; ne['v192_assets'] = v192
    prior_cache_path = actual_root/'history'/cache['rule_sha256']/SYMBOL/'checkpoint.json'
    prior_cache = owner.reference(prior_cache_path) if prior_cache_path.exists() else None
    ni.setdefault('exact_metadata_rows', {}).setdefault(DAY, {})[SYMBOL] = dict(typed_fact=typed_ref, row=new['row_refs'][SYMBOL], original_row=product['row_refs'][SYMBOL], previous_index=writer.immutable('exact_metadata_rows/'+DAY, 'previous_index.json', index))
    ne.update(manifest=nmr, artifact=artifact, unknown_count=new['unknown_count'], status=new['status'])
    info = lock.stat()
    plan = dict(status='PREPARED_EXACT_920202_NOT_PUBLISHED', expected_index=ir, expected_event=er,
        typed_fact=typed_ref, script=owner.reference(Path(__file__)), expected_cache=prior_cache, cache_path=str(prior_cache_path),
        candidate_cache=owner.save(output/'CACHE.json', cache), new_product=owner.save(output/'PRODUCT.json', new),
        staged_index_without_charts=owner.save(output/'INDEX_WITHOUT_CHARTS.json', ni), staged_event_without_charts=owner.save(output/'EVENT_WITHOUT_CHARTS.json', ne),
        immutable_files=writer.files, numeric_manifest=nmr, artifact=artifact, original_numeric_manifest=mr,
        old_chart_descriptor=index['original_charts'][DAY], completed=[SYMBOL], changed=[SYMBOL],
        owner_publisher=owner.reference(Path(owner.__file__)), shared_owner_lock=dict(path=str(lock), device=info.st_dev, inode=info.st_ino),
        target_root=str(actual_root), stage=str(output), unchanged_other_row_refs=5808, new_groups=EXPECTED,
        group_counts_before=product['three_value_counts'], group_counts_after=new['three_value_counts'],
        preserved_prior_views=preserved_prior_views,
        chart_view_recipe='ORIGINAL_FINALIZE_OWNER_CHARTS_REBIND_WITH_PNG_HARDLINKS; NO_FORMULA_RECOMPUTATION',
        panel_or_generation_rebuilds=0, single_current_row_compute_count=1, future_automatic_admission=False, **owner.FLAGS)
    owner.save(output/'PLAN.json', plan, immutable=True)
    require(owner.reference(actual_root/'index.json') == ir and owner.reference(actual_root/'events/latest.json') == er, 'INDEX_MOVED_DURING_PREPARE')
    c.unchanged()
    return plan


def publish(owner, c, plan_ref):
    from ops.sync_stock_history_completion import publish as original_publish
    from ops.render_original_formula_projection import finalize_owner_charts
    plan = load(owner, plan_ref)
    require(plan['status'] == 'PREPARED_EXACT_920202_NOT_PUBLISHED' and plan['script'] == owner.reference(Path(__file__)), 'PLAN_CODE_DRIFT')
    root, output = Path(plan['target_root']), Path(plan['stage'])
    def finish():
        typed = load(owner, plan['typed_fact']); require(fact(owner, c) == typed, 'SOURCE_MOVED_BEFORE_PUBLISH')
        require(owner.reference(root/'index.json') == plan['expected_index'] and owner.reference(root/'events/latest.json') == plan['expected_event'], 'PUBLICATION_CAS_MOVED')
        if plan['expected_cache'] is not None:
            owner.checked(plan['expected_cache'])
        else:
            require(not Path(plan['cache_path']).exists(), 'ABSENT_CACHE_CAS_MOVED')
        ni = load(owner, plan['staged_index_without_charts']); ne = load(owner, plan['staged_event_without_charts']); product = load(owner, plan['new_product'])
        descriptor = plan['old_chart_descriptor']; oldcharts = load(owner, descriptor['manifest']); oldreceipt = load(owner, descriptor['receipt'])
        require(oldreceipt['status'] == 'OWNER_CHARTS_COMPLETED' and set(oldcharts['samples']) == {r['symbol'] for r in product['rows']} and SYMBOL not in oldcharts['samples'], 'CHART_SCOPE_DRIFT')
        parts = {str(Path(v['source_cache']['path']).parent.parent) for v in oldcharts['samples'].values()}
        require(len(parts) == 1, 'RETAINED_CHART_NAMESPACE_DRIFT')
        def reuse_png(items):
            for item in items:
                old = oldcharts['samples'][item['symbol']]
                require(product['row_refs'][item['symbol']] == old['product_row_ref'] and item['rows'] == old['rows'], 'UNCHANGED_CHART_ROW_DRIFT')
                src = owner.checked(old['PNG']); dst = Path(item['png'])
                if dst.exists():
                    require(owner.reference(dst)['sha256'] == old['PNG']['sha256'], 'PNG_REUSE_DRIFT')
                else:
                    os.link(src, dst)
            return {}
        view = finalize_owner_charts(c, Path(next(iter(parts))), product, plan['numeric_manifest'], plan['artifact'], gaps={}, png_renderer=reuse_png)
        require(view['status'] == 'OWNER_CHARTS_COMPLETED', 'CHART_REBIND_INCOMPLETE')
        ni['original_charts'][DAY] = view; ne['original_charts'] = view
        ne['event_id'] = owner.digest({k:v for k,v in ne.items() if k != 'event_id'})
        c.unchanged()
        return {**plan, 'staged_index': owner.save(output/'FINAL_INDEX.json', ni), 'staged_event':owner.save(output/'FINAL_EVENT.json', ne)}
    result = original_publish(plan, refresh=finish)
    # The index/event commit is owned by the original publisher. The cache is
    # an immutable input to that single row, not a new source of eligibility.
    result.update(symbol=SYMBOL, typed_fact=plan['typed_fact'], unchanged_other_row_refs=5808, cache_activation='NOT_CHANGED; staged current evaluation is bound by row', future_automatic_admission=False)
    owner.save(output/'PUBLICATION_RESULT.json', result, immutable=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', nargs='?', choices=['inspect', 'prepare', 'publish'], default='inspect')
    parser.add_argument('--output', type=Path, default=HERE/'prepared')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--execute', action='store_true')
    a = parser.parse_args()
    owner, staging, lock, env = setup()
    from ops.research_storage_pair import paired_request
    @paired_request
    def run():
        c = context(owner, env)
        if a.operation == 'inspect':
            current = fact(owner, c)
            return dict(status='READ_ONLY_EXACT_920202_SOURCE_PARITY', generation=GEN, rows=current['resolved_rows'], fields_missing=current['original_missing_fields'], source_fact_sha256=owner.digest(current), future_automatic_admission=False, **owner.FLAGS)
        if a.operation == 'prepare':
            require(not a.execute, 'PREPARE_NEVER_EXECUTES_PUBLICATION')
            p = prepare(owner, staging, lock, c, a.output)
            return dict(status=p['status'], plan=owner.reference(a.output/'PLAN.json'), unchanged_other_row_refs=5808, new_groups=p['new_groups'], published=False, **owner.FLAGS)
        require(a.execute and a.plan and a.plan_sha256, 'EXPLICIT_PINNED_EXECUTE_REQUIRED')
        return publish(owner, c, dict(path=str(a.plan.resolve()), sha256=a.plan_sha256))
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == '__main__':
    main()
