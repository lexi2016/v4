"""One D10 frozen Top200 refresh through original stage/publication owners.

No collection, ranking rerun, formula evaluation or all-market structure build.
Default inspect is read-only; prepare stages; publish needs a pinned explicit plan.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from statistics import mean

R3 = Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/top200_yesterday_20261110/source_gap_repair_r3')
HERE = Path(__file__).resolve().parent
GEN = '231df8b469ade0ba8e6286d6cee624353aa46a5568cca569ffdf286bb7c28f81'
DAY = '20261110'
ADMISSION = {'301314.SZ', '920202.BJ', '605258.SH', '002623.SZ'}
OLD_TOP_SHA = '323e4eeaf6c748c6c6569c3f73ba2d66fe01fef58bab880e7baef32a6ab257bb'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def setup():
    p = R3/'direct_update/920202_current_completion/complete_920202.py'
    require(hashlib.sha256(p.read_bytes()).hexdigest() == 'ee78f5dfdcf4d4e4c89a28f3e59b4b851b515c91b508be72276788d1be36700d', 'ACCEPTED_CONTEXT_ADAPTER_DRIFT')
    spec = importlib.util.spec_from_file_location('exact_d10_source_context', p)
    shared = importlib.util.module_from_spec(spec); spec.loader.exec_module(shared)
    owner, staging, lock, env = shared.setup()
    from ops import research_panel_top200 as top
    return shared, owner, top, lock, env


def load(owner, ref):
    return json.loads(owner.checked(ref).read_bytes())


def build(shared, owner, top, c):
    """Reuse certified rows; run the frozen 61-session feature only for eight."""
    import gzip
    ir, er = owner.reference(c.root/'index.json'), owner.reference(c.root/'events/latest.json')
    index, event = load(owner, ir), load(owner, er)
    require(ir['sha256'] == '8bfc13b140edcac00b1647bbc1bce6a2d15688d535c9786363081db2c134dac6'
            and er['sha256'] == 'c050804be0a87057659d0b7e38da0b56c4e28e6e06fd02190ebbd9a516931cc1', 'POST_920202_PUBLICATION_CAS_MOVED')
    mr = index['dates'][DAY]; manifest = load(owner, mr); product = load(owner, manifest['artifact'])
    require(product['source_identity'] == c.identity and product['processed_count'] == 5809
            and product['unique_count'] == 380 and event['manifest'] == mr and event['artifact'] == manifest['artifact'], 'CURRENT_NUMERIC_IDENTITY_CONFLICT')
    prior_ref = index['top200'][DAY]
    require(prior_ref['sha256'] == OLD_TOP_SHA, 'FROZEN_TOP200_MOVED')
    prior = load(owner, prior_ref)
    require(prior['data_date'] == DAY and prior['preparation_asof'] == '20261109' and prior['top200_count'] == 200
            and prior['status'] == 'PARTIAL_DESCRIPTIVE' and len({r['symbol'] for r in prior['top200']}) == 200
            and [r['rank'] for r in prior['top200']] == list(range(1, 201)), 'FROZEN_TOP200_SCOPE_CONFLICT')
    for key in ('official_input', 'official_package', 'classification_source', 'rule'):
        owner.checked(prior[key])
    require(prior['rule']['sha256'] == top.TRIAL_SHA, 'FROZEN_STRUCTURE_RULE_DRIFT')
    canary_ref = owner.reference(R3/'direct_update/reuse_actual_input/FULL_ORIGINAL_REUSE_CANARY.json')
    canary = load(owner, canary_ref)
    require(canary['status'] == 'PASS_FULL_ORIGINAL_SAME_ASOF_REUSE_CANARY' and canary['changed_count'] == 8
            and canary['reused_count'] == 5766 and canary['snapshot']['sha256'] == c.snapshot_ref['sha256'], 'ACCEPTED_REUSE_PROOF_CONFLICT')
    reuse_input = load(owner, canary['same_asof_input']); baseline = load(owner, reuse_input['baseline_receipt'])
    require(prior['source_generation'] == baseline['generation_id'] and baseline['generation_id'].startswith('cfaef27985f1053b'), 'PRIOR_TOP200_PRICE_BASELINE_CONFLICT')
    reused, changed = set(canary['reused_codes']), set(canary['changed_codes'])
    topcodes = {r['symbol'] for r in prior['top200']}
    require(topcodes <= reused | changed and topcodes & changed == {'002623.SZ', '605258.SH', '920202.BJ'}
            and '301314.SZ' in reused, 'TOP200_ACCEPTED_DELTA_SCOPE_CONFLICT')
    admission_refs = {symbol: product['row_refs'][symbol] for symbol in sorted(ADMISSION)}
    for symbol, ref in admission_refs.items():
        row = load(owner, ref); q = row['qualification']
        require(row['symbol'] == symbol and row['data_date'] == DAY and q['status'] == 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
                and q['source_generation'] == GEN and q['snapshot_sha256'] == c.snapshot_ref['sha256'], 'CURRENT_SOURCE_ADMISSION_MISSING:'+symbol)
    charts = load(owner, index['original_charts'][DAY]['manifest'])
    sample = next(iter(charts['samples'].values()))
    retained = json.loads(gzip.decompress(owner.checked(sample['source_cache']).read_bytes()))
    require(retained['identity'] == c.identity, 'CURRENT_CALENDAR_SOURCE_CONFLICT')
    expected = [d for d in retained['calendar'] if d < int(DAY)][-61:]
    require(len(expected) == 61 and expected[-1] == 20261109, 'TECHNICAL_CUTOFF_CONFLICT')
    histories = top.structure_histories(c.panel, sorted(changed | ADMISSION), expected)
    feature = top.frozen_function('feature', dict(histories=histories, expected=expected, mean=mean,
        finite=lambda v: isinstance(v, (int, float)) and math.isfinite(v)))
    payload = copy.deepcopy(prior); coverage = {r['symbol']: r for r in payload['coverage']}
    deltas = {}
    for symbol in sorted(changed):
        value = feature(symbol)
        value.update(history_asof='20261109', history_basis='QFQ_ASOF_20261110_NOT_HISTORICAL_PIT')
        old = copy.deepcopy(coverage[symbol]); coverage[symbol].update(value)
        delta = {k: dict(before=old.get(k), after=v) for k, v in value.items() if old.get(k) != v}
        require(coverage[symbol]['structure'] == old['structure'], 'STRUCTURE_BUCKET_CHANGED_REQUIRES_BOUNDED_STAT_REFRESH')
        deltas[symbol] = delta
    status_ref = owner.reference(R3/'sources/status/OFFICIAL_STATUS_FACTS.json')
    status = next(r for r in load(owner, status_ref)['rows'] if r['symbol'] == '002623')
    require(status['status'] == 'CONTROL_TRANSFER_SUSPENSION_RESUMED' and status['suspension_start'] == 20261103
            and status['resume_date'] == 20261110, 'AMD_SUSPENSION_FACT_CONFLICT')
    notice_ref = {k: status['pdf'][k] for k in ('path', 'sha256')}
    owner.checked(notice_ref)
    windows = {}
    for symbol in sorted(ADMISSION):
        dates = [r['trade_date'] for r in histories[symbol]]
        missing = sorted(set(expected)-set(dates))
        require(len(dates) == {'301314.SZ':52, '002623.SZ':56, '605258.SH':60, '920202.BJ':25}[symbol], 'OBSERVED_WINDOW_SCOPE_CHANGED')
        reason = '严格连续61个市场交易日门未满足；当前来源已核验，窗口为'+str(len(dates))+'/61条，不补造缺席日期K线'
        if symbol == '002623.SZ':
            require(missing == [20261103,20261104,20261105,20261106,20261109], 'SUSPENSION_WINDOW_DATES_CONFLICT')
            reason = 'D9仍停牌，11月10日复牌；窗口56/61条，五个停牌交易日不造K线，原61日门保持UNKNOWN'
        if symbol == '920202.BJ':
            require(dates[0] == 20260929, 'LISTING_START_CONFLICT')
            reason = '9月29日上市，D9窗口仅25/61条；不补上市前K线，原61日门保持UNKNOWN'
        windows[symbol] = dict(expected_market_sessions=61, available_records=len(dates), absent_session_dates=missing,
            latest_actual_date=max(dates), source_admission=admission_refs[symbol], reason=reason,
            **({'official_status':status_ref, 'official_notice':notice_ref, 'asof_tradability':'SUSPENDED_NO_D9_BAR', 'resume_date':20261110} if symbol == '002623.SZ' else {}))
        coverage[symbol]['structure_detail'] = reason
    # Non-output/quarantined legacy rows are outside the same-asof price set.
    # Compare their existing 61-session windows mechanically; no feature call.
    legacy = set(coverage) - reused - changed
    oldpanel = Path(baseline['candidates']['selector']); stamp = oldpanel.stat()
    require(baseline['candidate_sha256']['selector'] == reuse_input['baseline_roles']['selector']['sha256'], 'LEGACY_PANEL_RECEIPT_CONFLICT')
    before = top.structure_histories(oldpanel, sorted(legacy), expected)
    after = top.structure_histories(c.panel, sorted(legacy), expected)
    require(before == after and oldpanel.stat() == stamp, 'LEGACY_COVERAGE_WINDOW_CHANGED')
    current = {r['symbol']: r for r in product['rows']}
    old_top = {r['symbol']: r for r in prior['top200']}
    for row in payload['top200']:
        if row['symbol'] in changed:
            row.update({k: v for k, v in coverage[row['symbol']].items() if k in ('bars', 'structure', 'structure_status', 'history_asof', 'history_basis')})
        row['current_groups'] = current.get(row['symbol'], {}).get('groups', '')
        if row['symbol'] in windows:
            row['structure_detail'] = windows[row['symbol']]['reason']
    unaffected = [s for s in topcodes - ADMISSION if next(r for r in payload['top200'] if r['symbol'] == s) == old_top[s]]
    require(len(unaffected) == 196, 'UNRELATED_TOP200_ROW_CHANGED')
    require(prior['comparison']['previous_session']['numeric_manifest'] == index['dates']['20261109'], 'PRIOR_SESSION_BINDING_MOVED')
    payload['comparison']['same_day'] = top.roster_comparison(product, topcodes, DAY, '同日事后描述对照', mr)
    payload.update(numeric_manifest=mr, source_generation=GEN, input_sha256=c.identity['input_sha256'],
        input_fingerprint=owner.digest(dict(date=DAY, input=prior['official_input'], classification=prior['classification_version'],
            generation=GEN, input_sha256=c.identity['input_sha256'], rule=top.TRIAL_SHA)))
    # Structure bucket memberships and frozen raw rank/amounts did not change;
    # the original descriptive aggregate statistics remain exactly reusable.
    require(payload['statistics'] == prior['statistics'] and payload['comparison']['previous_session'] == prior['comparison']['previous_session'], 'FROZEN_STATISTICS_DRIFT')
    payload['computation'] = dict(reused_prior_top200=prior_ref, accepted_same_asof_reuse=canary_ref,
        current_source_admission=admission_refs, current_numeric_manifest=mr, source_generation=GEN,
        computed_structures=8, affected_structure_symbols=sorted(changed), top200_changed_source_symbols=sorted(topcodes & changed),
        actual_feature_deltas=deltas, reused_unchanged_top200_rows=196, legacy_window_equality_symbols=sorted(legacy),
        source_window_facts=windows,
        legacy_window_values_sha256=owner.digest(after), formula_engine_calls=0, ranking_recomputed=False,
        structure_statistics_reused=True, future_automatic_refresh=False)
    c.unchanged()
    proof = dict(expected_index=ir, expected_event=er, prior_top200=prior_ref, current_numeric_manifest=mr,
        current_snapshot=c.snapshot_ref, prior_receipt=reuse_input['baseline_receipt'], accepted_reuse=canary_ref,
        top200_symbols_sha256=owner.digest([r['symbol'] for r in payload['top200']]),
        untouched_top200_rows=196, feature_calls=8, legacy_window_equality_count=len(legacy), actual_feature_deltas=deltas,
        owner_sources=[owner.reference(Path(owner.__file__)), owner.reference(Path(top.__file__)),
            owner.reference(shared.APP/'ops/sync_stock_history_completion.py')],
        source_admission=admission_refs, panel_stat=dict(size=c.panel.stat().st_size, mtime_ns=c.panel.stat().st_mtime_ns),
        source_window_facts=windows,
        preparation_asof='20261109', ranking_recomputed=False, formula_calls=0, full_market_build_calls=0, **owner.FLAGS)
    return payload, proof


def main():
    p = argparse.ArgumentParser()
    p.add_argument('operation', nargs='?', choices=['inspect', 'prepare', 'publish'], default='inspect')
    p.add_argument('--output', type=Path, default=HERE/'prepared')
    p.add_argument('--plan', type=Path); p.add_argument('--plan-sha256'); p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    shared, owner, top, lock, env = setup()
    from ops.research_storage_pair import paired_request
    @paired_request
    def run():
        c = shared.context(owner, env)
        if a.operation in ('inspect', 'prepare'):
            shared.idle(lock)
            payload, proof = build(shared, owner, top, c)
            if a.operation == 'inspect':
                return dict(status='READ_ONLY_TOP200_DELTA_VERIFIED', proof=proof)
            require(not a.execute, 'PREPARE_DOES_NOT_PUBLISH')
            a.output.mkdir(parents=True, exist_ok=True)
            proof_ref = owner.save(a.output/'PROOF.json', proof, immutable=True)
            payload_ref = owner.save(a.output/'PAYLOAD.json', payload, immutable=True)
            plan = top.stage(payload, c.root, a.output/'staged', owner.reference(Path(owner.__file__)))
            require(plan['expected_index'] == proof['expected_index'] and plan['expected_event'] == proof['expected_event'], 'PREPARE_CAS_MOVED')
            plan.update(script=owner.reference(Path(__file__)), proof=proof_ref, payload=payload_ref)
            pr = owner.save(a.output/'PLAN.json', plan, immutable=True)
            return dict(status='PREPARED_TOP200_NOT_PUBLISHED', plan=pr, top200_count=200, untouched_rows=196, feature_calls=8, formula_calls=0, **owner.FLAGS)
        require(a.execute and a.plan and a.plan_sha256, 'EXPLICIT_PINNED_EXECUTE_REQUIRED')
        plan_ref = dict(path=str(a.plan.resolve()), sha256=a.plan_sha256); plan = load(owner, plan_ref)
        require(plan['script'] == owner.reference(Path(__file__)), 'PLAN_SCRIPT_DRIFT')
        from ops.sync_stock_history_completion import publish
        def refresh():
            proof = load(owner, plan['proof'])
            for ref in proof['owner_sources'] + list(proof['source_admission'].values()):
                owner.checked(ref)
            require(owner.reference(c.root/'index.json') == proof['expected_index'] and owner.reference(c.root/'events/latest.json') == proof['expected_event']
                    and c.snapshot_ref == proof['current_snapshot'] and c.generation == GEN
                    and dict(size=c.panel.stat().st_size, mtime_ns=c.panel.stat().st_mtime_ns) == proof['panel_stat'], 'TOP200_PUBLICATION_SOURCE_OR_CAS_MOVED')
            load(owner, plan['payload']); c.unchanged()
            return plan
        result = publish(plan, refresh=refresh)
        owner.save(Path(plan['stage'])/'TOP200_PUBLICATION_RESULT.json', result, immutable=True)
        return result
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == '__main__':
    main()
