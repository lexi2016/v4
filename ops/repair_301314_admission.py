"""Exact 20261110 source-metadata repair through the existing daily owner.

No acquisition, raw rewrite, validator edit, whole-universe evaluation or implicit
publication. Published source receipts supply acceptance; this module supplies
checked typed facts only for the frozen symbol/snapshot/generation.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import zipfile


SYMBOL = '301314.SZ'
TARGET = 20261110
GENERATION = 'cfaef27985f1053b4e888645a3ee8d512792edbae62d33cffafa41ff3c0685b5'
SNAPSHOT_SHA = 'd0cae0e45f242c2d89d99d8d3b22e07f03e9c6497d555a31c9480e99e130fb8f'
HELPER_SHA = '7d67ba9898ebc1e816d082ae43ca0f51e3a9bc16278a589c0104524af925047a'
RUNTIME = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-storage-recovery-20261110-r1/v4-daily-storage-recovery-20261110-r1-main/app')
RUNTIME_DEPENDENCIES = {
    '_a_share_daily_sync_parts/official_daily_package.py': 'ff15f25c287e49f554a08038a4c1e503a044b25829fea77a8663f89bd11dd276',
    'research_storage_retention.py': '1c55d06730bea852828f1a85bdcc227957d87645b789a7ae24825d6f9993bbbf',
    'research_panel_factor_cache.py': '158f1d26b1a803c280b27139cb8b2f3ab0d9c9fe418bff91f6a0bfc9ef1f04f9',
    'bootstrap_stock_event_history.py': 'befdec34344d8826e4a6a08ca74977de73a08f862d8292b04b71b9a0be20ed5c',
    'research_storage_pair.py': '3b7d65c14b8872909e81eb6117f38db8403606a9d3edb4683955753a0bb4fad8',
    'research_panel_qfq.py': '05e8aa7aa19c1ae998481360d80fb99a39498ffd31c5945caedd5c791daa1fad',
    'sync_stock_history_completion.py': '8ac31ebf6aca340ef9f4262e959cf72d16c29c86b185b4058e73c96ea872f6da',
}
import ops
for _name, _expected in RUNTIME_DEPENDENCIES.items():
    if hashlib.sha256((RUNTIME / 'ops' / _name).read_bytes()).hexdigest() != _expected:
        raise ValueError('EXACT_301314_RUNTIME_DEPENDENCY_DRIFT:' + _name)
ops.__path__.append(str(RUNTIME / 'ops'))
import ops._a_share_daily_sync_parts as _sync_parts
_sync_parts.__path__.append(str(RUNTIME / 'ops/_a_share_daily_sync_parts'))
DOMAIN_DEPENDENCIES = {
    'research_daily_product.py': '48cccee9eb4c77d2d09965a3e25354580278d14605e835d28833998a327c39e3',
    'research_daily_statistics.py': '49f20f898517131403b329b99565a5b244c5a74b5a30f5cae54c4ced77187fff',
}
import domains
for _name, _expected in DOMAIN_DEPENDENCIES.items():
    if hashlib.sha256((RUNTIME / 'domains' / _name).read_bytes()).hexdigest() != _expected:
        raise ValueError('EXACT_301314_RUNTIME_DOMAIN_DRIFT:' + _name)
domains.__path__.append(str(RUNTIME / 'domains'))
from ops import research_panel_daily_product as owner

SCHEMA = 'V4_EXACT_301314_20261110_TYPED_SOURCE_FACT_V1'
DATA_ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
SOURCE_CONFIG = Path('/Users/lexi/Desktop/学习/v4_app/.task_worktrees/a-daily-dashboard-closure-20261029/docs/handoffs/a_daily_dashboard_closure_20261029/SOURCE_CONFIG.json')


def load(ref):
    return json.loads(owner.checked(ref).read_bytes())


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def bind_runtime_dependencies():
    """Explicit pinned dependencies omitted from the Git baseline, no copies."""
    import ops
    refs = []
    for name, expected in RUNTIME_DEPENDENCIES.items():
        ref = dict(path=str(RUNTIME / 'ops' / name), sha256=expected)
        owner.checked(ref)
        refs.append(ref)
    path = str(RUNTIME / 'ops')
    if path not in ops.__path__:
        ops.__path__.append(path)
    return refs + [dict(path=str(RUNTIME / 'domains' / name), sha256=expected) for name, expected in DOMAIN_DEPENDENCIES.items()]


def scope(context, symbol=SYMBOL):
    require(symbol == SYMBOL and context.target == TARGET and context.generation == GENERATION
            and context.snapshot_ref['sha256'] == SNAPSHOT_SHA
            and context.config['admission_helper']['sha256'] == HELPER_SHA,
            'EXACT_301314_SOURCE_SCOPE_CONFLICT')
    item = context.snapshot['symbols'][symbol]
    require(not any(k in item for k in ('history_end_date', 'accepted_evidence', 'source_config', 'source_policy')),
            'EXACT_301314_ORIGINAL_METADATA_CHANGED')
    return item


def collect_source_fact(context):
    """Full-symbol raw/adjustment/pair equality plus existing stock-specific receipts."""
    import numpy as np
    import pyarrow.parquet as pq
    item = scope(context)
    dependencies = bind_runtime_dependencies()
    from ops import research_panel_qfq as q
    require(owner.reference(Path(q.__file__)) == next(r for r in dependencies if r['path'].endswith('/research_panel_qfq.py')), 'EXACT_301314_RAW_OWNER_DRIFT')
    meta_ref = owner.reference(Path(context.receipt['run_dir']) / 'meta.json')
    worker = load(meta_ref)['formula_processing']['worker_context']
    driver_ref = dict(path=worker['driver_path'], sha256=worker['driver_sha256'])
    formula_ref = dict(path=worker['canonical_formula_path'], sha256=worker['canonical_formula_sha256'])
    driver, _ = q.authorities(owner.checked(driver_ref), owner.checked(formula_ref))
    for ref in item['raw_files']:
        owner.checked(ref)
    raw = q.resolved_raw_history(SYMBOL, item, TARGET, driver)
    require(not raw.empty and not raw.trade_date.duplicated().any()
            and int(raw.trade_date.min()) == item['history_start_date']
            and int(raw.trade_date.max()) == TARGET, 'EXACT_301314_FULL_RAW_HISTORY_CONFLICT')
    # Check the extracted archive against its original member, without copying
    # the whole archive or treating its latest date as acceptance.
    archive_ref = next(r for r in context.snapshot['source_files'] if r['sha256'] == 'a56c962378a5d3dd86a90186cc830ee6c8fd968557ce6eddeb310d203c5ff3c0')
    archive_path = Path(archive_ref['path']); archive_stat = archive_path.stat()
    with zipfile.ZipFile(archive_path) as archive:
        members = [n for n in archive.namelist() if n.replace(chr(92), '/').lower().endswith('/sz301314.day') or n.lower() == 'sz301314.day']
        require(len(members) == 1, 'EXACT_301314_ARCHIVE_MEMBER_AMBIGUOUS')
        member_sha = hashlib.sha256(archive.read(members[0])).hexdigest()
    require(member_sha == item['raw_files'][0]['sha256'] and archive_path.stat() == archive_stat,
            'EXACT_301314_ARCHIVE_MEMBER_CONFLICT')
    factor = context.snapshot['research_factor_receipts']['symbols'][SYMBOL]
    response_ref = factor['original_provider_response']; response = load(response_ref)
    require(response_ref in context.snapshot['source_files'] and response.get('code') == 'SZ.301314'
            and response.get('return_code') == 0, 'EXACT_301314_FACTOR_RESPONSE_CONFLICT')
    events = [dict(ex_date=int(r['ex_div_date'].replace('-', '')), a=r['forward_adj_factorA'],
                   b=r['forward_adj_factorB'], volume_a=r['backward_adj_factorA']) for r in response['rows']
              if int(r['ex_div_date'].replace('-', '')) <= TARGET]
    require(events == item['events'], 'EXACT_301314_ADJUSTMENT_EVENTS_CONFLICT')
    factor_config = load(factor['configuration']); parent = load(factor['parent_metadata'])
    parent_symbol = parent['symbols'][SYMBOL]
    require(factor['identity_binding'] == dict(code=SYMBOL, market='SZ', provider_request_code='SZ.301314')
            and factor['ts_code'] == SYMBOL and factor['target_date'] == TARGET
            and factor['status'] == 'RESEARCH_CACHE_CARRY_FORWARD' and factor['historical_PIT'] is False
            and factor['verification']['changed_rows'] is False
            and factor['verification']['effective_events_in_window'] is False
            and factor['verification']['source_coverage_end_date'] == TARGET
            and factor_config['target_date'] == TARGET
            and parent_symbol['verification']['full_row_fingerprint'] == factor['verification']['full_row_fingerprint']
            and parent_symbol.get('original_provider_response', parent_symbol.get('response')) == response_ref,
            'EXACT_301314_FACTOR_CARRY_FORWARD_CONFLICT')
    for key in ('raw', 'derived_parquet', 'derived_receipt', 'capture', 'category_policy', 'parser'):
        owner.checked(factor_config['current_detector'][key])
    require(factor['verification']['source_capture'] == factor_config['current_detector']['capture'],
            'EXACT_301314_FACTOR_DETECTOR_CONFLICT')
    # Independent current native acceptance exists in the original sync owner.
    sync_ref = context.receipt['turnover_input']['binding']['sync']; sync = load(sync_ref)
    native_rows = [r for r in sync['symbol_reconciliation'] if r.get('symbol') == '301314' and r.get('market') == 0]
    require(str(sync['target_date']) == str(TARGET) and len(native_rows) == 1, 'EXACT_301314_NATIVE_RECEIPT_SCOPE_CONFLICT')
    native = native_rows[0]; lineage = native['source_lineage']; native_ref = item['raw_files'][1]
    require(native.get('classification') == 'ACCEPTED' and native.get('quarantine') is False
            and native.get('target_date_ready') is True and native.get('last_date_after') == TARGET
            and native.get('source_sha256_after') == native_ref['sha256'] and native.get('path') == native_ref['path']
            and lineage.get('code') == '301314' and lineage.get('market') == 0 and lineage.get('target_date') == TARGET,
            'EXACT_301314_NATIVE_ACCEPTANCE_CONFLICT')
    for ref in [lineage['input_ref'], lineage['package'], *native['raw_response_snapshots']]:
        owner.checked(ref)
    adjusted = q.apply_adjustments(raw, events, TARGET)
    columns = ['open', 'high', 'low', 'close', 'vol', 'amount']
    expected = adjusted[columns].to_numpy(dtype='float64')
    require(np.isfinite(expected).all(), 'EXACT_301314_ADJUSTED_NONFINITE')
    roles = {}
    context.unchanged()
    for role, path in context.receipt['candidates'].items():
        p = Path(path); stamp = p.stat(); contract = q.panel_contract(p)
        require(contract['generation_id'] == GENERATION and contract['snapshot_file_sha256'] == SNAPSHOT_SHA
                and contract['input_sha256'] == context.identity['input_sha256'], 'EXACT_301314_PAIR_CONTRACT_CONFLICT')
        schema = pq.read_schema(p); volume = 'volume' if 'volume' in schema.names else 'vol'
        frame = pq.read_table(p, columns=['ts_code', 'trade_date', 'open', 'high', 'low', 'close', volume, 'amount'],
                              filters=[('ts_code', '=', SYMBOL)]).to_pandas().sort_values('trade_date').reset_index(drop=True)
        dates = frame.trade_date.astype(int).tolist()
        values = np.asarray([[float(r[c if c != 'vol' else volume]) for c in columns] for r in frame.to_dict('records')])
        require(dates == adjusted.trade_date.astype(int).tolist() and np.array_equal(values, expected)
                and p.stat() == stamp, 'EXACT_301314_FULL_ADJUSTED_PAIR_VALUES_CONFLICT:' + role)
        roles[role] = dict(path=path, sha256=context.receipt['candidate_sha256'][role],
                           stat=dict(size=stamp.st_size, mtime_ns=stamp.st_mtime_ns), rows=len(frame),
                           values_sha256=owner.digest(dict(dates=dates, columns=columns, values=values.tolist())))
    require(set(roles) == {'selector', 'backtest'}, 'EXACT_301314_PAIRED_ROLES_CONFLICT')
    context.unchanged()
    return dict(schema=SCHEMA, symbol=SYMBOL, target_date=TARGET, source_generation=GENERATION,
                snapshot=context.snapshot_ref, producer_receipt=context.receipt_ref, helper=context.config['admission_helper'],
                source_identity=context.identity, original_missing_fields=['history_end_date', 'accepted_evidence'],
                effective_history_end_date=TARGET, raw_refs=item['raw_files'], resolved_rows=len(raw),
                first_date=int(raw.trade_date.min()), last_date=int(raw.trade_date.max()),
                archive_member=dict(archive=archive_ref, member=members[0], member_sha256=member_sha),
                events=events, factor_receipt_sha256=owner.digest(factor), factor_parent=factor['parent_metadata'],
                factor_response=response_ref, source_configuration=factor['configuration'],
                existing_native_admission=sync_ref, native_row_sha256=owner.digest(native),
                paired_roles=roles, runtime_dependencies=dependencies, driver=driver_ref, formula=formula_ref,
                accepted_evidence=[sync_ref, response_ref, factor['configuration']],
                historical_PIT=False, provider_revision_coverage='CANNOT_CONFIRM', **owner.FLAGS)


def verified_fact(context, ref):
    proof = load(ref)
    require(proof == collect_source_fact(context), 'EXACT_301314_TYPED_FACT_DRIFT')
    return proof


def qualify(context, ref):
    """Call the unchanged original validator over two proven metadata additions."""
    proof = verified_fact(context, ref)
    args = (SYMBOL, str(TARGET), context.footer, context.receipt, context.quarantine,
            context.generation, Path(context.quarantine_ref['path']))
    original = context.helper.verify_symbol_admission(*args)
    require(original.get('reason') == 'CURRENT_SYMBOL_HISTORY_END_MISMATCH', 'EXACT_301314_ORIGINAL_REASON_CHANGED')
    snapshot = copy.deepcopy(context.snapshot)
    snapshot['symbols'][SYMBOL]['history_end_date'] = proof['effective_history_end_date']
    previous = context.helper.read_json
    context.helper.read_json = lambda p: snapshot if Path(p) == Path(context.snapshot_ref['path']) else previous(p)
    try:
        date_only = context.helper.verify_symbol_admission(*args)
        require(date_only.get('reason') == 'CURRENT_SYMBOL_ACCEPTANCE_REFERENCES_MISSING', 'EXACT_301314_DATE_ONLY_ORACLE_CONFLICT')
        snapshot['symbols'][SYMBOL]['accepted_evidence'] = proof['accepted_evidence']
        result = context.helper.verify_symbol_admission(*args)
    finally:
        context.helper.read_json = previous
    require(result.get('status') == 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH', 'EXACT_301314_ORIGINAL_VALIDATOR_REJECTED')
    result['history_end_metadata'] = dict(schema=SCHEMA, original_admission=original, date_only_admission=date_only,
        original_missing_fields=proof['original_missing_fields'], evidence=ref, original_helper=proof['helper'],
        derived_accepted_evidence=proof['accepted_evidence'], snapshot_bytes_unchanged=True,
        validator=owner.reference(Path(owner.__file__)))
    return result


def context():
    bind_runtime_dependencies()
    cfg_ref = owner.reference(SOURCE_CONFIG)
    return owner.SourceContext(DATA_ROOT, TARGET, source_config=(load(cfg_ref), cfg_ref))


def prepare(computation_ref, output):
    from ops.research_panel_top200 import prepare_exact_301314_row
    done=load(computation_ref);ref=done['typed_fact']
    os.environ['V4_A_DAILY_301314_TYPED_FACT_PATH']=ref['path']
    os.environ['V4_A_DAILY_301314_TYPED_FACT_SHA256']=ref['sha256']
    ctx=context();root=Path(done['expected_index']['path']).parent;ctx.root=root
    return prepare_exact_301314_row(ctx,root,output,computation_ref)


def verify_preparation_owner(ref):
    """Verify the reviewed preparation bytes; publication never reexecutes them.

    The existing runtime publisher changes ops.__path__. A package import can
    therefore resolve another release even while the reviewed file is intact.
    Bind the exact sibling source path and its plan-pinned SHA directly.
    """
    expected=Path(__file__).resolve().with_name('research_panel_top200.py')
    require(ref.get('path')==str(expected), 'EXACT_301314_PREPARATION_PATH_CONFLICT')
    return owner.checked(ref)


def publish(plan_ref):
    """Controller-only explicit activation; existing owner owns locks and CAS."""
    from ops.sync_stock_history_completion import publish as publish_owner
    plan=load(plan_ref);done=load(plan['computation']);fact=done['typed_fact']
    require(plan['status']=='PREPARED_EXACT_301314_METADATA_ROW', 'EXACT_301314_PUBLICATION_PLAN_SCOPE')
    os.environ['V4_A_DAILY_301314_TYPED_FACT_PATH']=fact['path']
    os.environ['V4_A_DAILY_301314_TYPED_FACT_SHA256']=fact['sha256']
    ctx=context();ctx.root=Path(plan['target_root'])
    def guarded():
        verified_fact(ctx,fact);ctx.unchanged()
        for ref in plan['new_unreferenced_files']:owner.checked(ref)
        require(owner.reference(done['original_cache']['path'])==done['original_cache'], 'EXACT_301314_CACHE_CAS_MOVED')
        verify_preparation_owner(plan['preparation_owner'])
        require(plan['owner_publisher']==owner.reference(Path(owner.__file__))
                and done['repair_code']==owner.reference(Path(__file__)), 'EXACT_301314_PUBLISHER_CODE_DRIFT')
        return plan
    receipt=publish_owner(plan,refresh=guarded)
    try:
        require(owner.reference(done['original_cache']['path'])==done['original_cache'], 'EXACT_301314_CACHE_CAS_MOVED_AFTER_INDEX')
        cache_after=owner.save(done['original_cache']['path'],load(done['cache']))
    except BaseException:
        stage=Path(plan['stage'])
        rollback={**plan,'status':'PREPARED_EXACT_301314_ROLLBACK','expected_index':receipt['index'],'expected_event':receipt['event'],
            'staged_index':owner.save(stage/'rollback_index.json',receipt['before']['index']),
            'staged_event':owner.save(stage/'rollback_event.json',receipt['before']['event']),'immutable_files':{}}
        publish_owner(rollback)
        raise
    result=dict(status='PUBLISHED_EXACT_301314_METADATA_ROW',publication=receipt,cache_before=done['original_cache'],
        cache_after=cache_after,computation=plan['computation'],unchanged_other_row_refs=5807,**owner.FLAGS)
    owner.save(Path(plan['stage'])/'EXACT_301314_PUBLICATION_RECEIPT.json',result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['source-facts','prepare','publish'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--computation', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--plan-sha256')
    args = parser.parse_args()
    if args.operation=='source-facts':
        require(args.output is not None,'EXACT_301314_OUTPUT_REQUIRED')
        result=owner.save(args.output,collect_source_fact(context()),immutable=True)
    elif args.operation=='prepare':
        require(args.output is not None and args.computation is not None,'EXACT_301314_PREPARE_ARGUMENTS_REQUIRED')
        result=prepare(owner.reference(args.computation),args.output)
        result={k:result[k]for k in ('status','numeric_manifest','artifact','candidate_namespace')}
    else:
        require(args.plan is not None and args.plan_sha256 is not None,'EXACT_301314_PINNED_PLAN_REQUIRED')
        result=publish(dict(path=str(args.plan),sha256=args.plan_sha256))
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
