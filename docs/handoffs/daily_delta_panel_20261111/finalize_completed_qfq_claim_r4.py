"""Controller-only final recording of one already committed original QFQ claim.

Default is read-only. --execute is permitted only after independent review.
Never calls admission, Claim.begin, a producer, retention planning or a service.
"""
from pathlib import Path
import argparse
import copy
import datetime
import hashlib
import json
import os
import plistlib
import sys
import time

N = Path(__file__).resolve().parent
PLAN = N / 'QFQ_COMPLETED_CLAIM_PLAN_R4.json'
PLAN_SHA256 = 'ba80a420ff41e5fda2b3c10fd6f05d7fffd460c2064179967f5ced407f2e022b'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def exact_row(g, registry, plan):
    require(sha(registry.path) == plan['expected_registry_sha256'], 'REGISTRY_SHA_DRIFT')
    state = registry.read()
    row = state['tasks'][plan['key']]
    require(row['token'] == plan['expected_token'] and canonical(row) == plan['expected_task_sha256'], 'EXACT_TASK_DRIFT')
    require(row['state'] == 'RUNNING' and row['attempts'] == plan['expected_attempts'] == 1, 'TASK_STATE_DRIFT')
    require(row['directory'] == plan['directory'] and row['reserved_bytes'] == plan['predicted'], 'TASK_BUDGET_OR_DIRECTORY_DRIFT')
    require(row['owner'] == plan['expected_owner'] and g.owner_state(row['owner']) == 'DEAD', 'OWNER_NOT_DEAD')
    for key, other in state['tasks'].items():
        if other['state'] in {'RUNNING', 'VALIDATING'}:
            require(g.owner_state(other['owner']) == 'DEAD', 'OWNER_LIVE_OR_UNKNOWN_NO_STEAL')
            require(key == plan['key'], 'OTHER_DEAD_OWNER_RECONCILIATION_REQUIRED')
    return state, row


def validate_current(g, q, policy, kwargs, plan):
    ready = g.verified_qfq_current(q, policy, plan['target'], kwargs)
    require(ready is not None and ready['status'] == 'READY', 'CURRENT_NOT_READY')
    summary = copy.deepcopy(plan['summary'])
    require(ready['generation_id'] == plan['expected_generation'] == summary['generation_id'], 'CURRENT_GENERATION_DRIFT')
    require(ready['target_date'] == summary['target_date'] == plan['target'], 'CURRENT_DATE_DRIFT')
    require(ready['candidate_sha256'] == summary['candidate_sha256'], 'CURRENT_SHA_DRIFT')
    pointers = {}
    for role in ('selector', 'backtest'):
        text = Path(policy['pointers'][role]).read_text(encoding='utf-8-sig')
        require(text.strip() == ready[role] == summary[role], 'CURRENT_PATH_DRIFT')
        contract = q.panel_contract(Path(ready[role]))
        require(contract['generation_id'] == plan['expected_generation'] and contract['asof_date'] == plan['target'], 'CURRENT_FOOTER_DRIFT')
        pointers[role] = text
    documents = {}
    for key in ('complete_owner_receipt', 'ready_owner_receipt'):
        ref = summary[key]
        require(sha(ref['path']) == ref['sha256'], 'SEALED_OWNER_RECEIPT_DRIFT')
        documents[key] = json.loads(Path(ref['path']).read_bytes())
    for doc in documents.values():
        require(doc['generation_id'] == summary['generation_id'] and doc['target_date'] == summary['target_date'], 'OWNER_RECEIPT_IDENTITY_DRIFT')
        require(doc['candidate_sha256'] == summary['candidate_sha256'], 'OWNER_RECEIPT_SHA_DRIFT')
        require(doc['candidates'] == {r: summary[r] for r in ('selector', 'backtest')}, 'OWNER_RECEIPT_PATH_DRIFT')
        for key, value in dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False).items():
            require(doc.get(key) == value and summary.get(key) == value, 'SAFETY_FLAG_DRIFT')
    require(documents['complete_owner_receipt']['status'] in {'CANDIDATE_READY', 'READY'}, 'CANDIDATE_NOT_READY')
    completion = documents['ready_owner_receipt']
    require(completion['status'] == 'READY' and completion['selector_pointer_ready'] is True and completion['backtest_pointer_ready'] is True, 'OWNER_NOT_COMPLETED')
    records = g.artifact_records([ready['selector'], ready['backtest']])
    require({r['path']: r['sha256'] for r in records} == {summary[r]: summary['candidate_sha256'][r] for r in ('selector', 'backtest')}, 'ARTIFACT_SHA_DRIFT')
    require(len(json.dumps(summary)) < 128 * 1024, 'RESULT_METADATA_BUDGET')
    return ready, summary, records, pointers


def record_completion(g, registry, policy, plan, summary, records, pointers, operator_ref):
    """Caller holds original owner/publication/pool-writer locks throughout."""
    with registry.transaction():
        state, row = exact_row(g, registry, plan)
        for role, text in pointers.items():
            require(Path(policy['pointers'][role]).read_text(encoding='utf-8-sig') == text, 'CURRENT_CHANGED_BEFORE_RECORDING')
        for key in ('complete_owner_receipt', 'ready_owner_receipt'):
            require(sha(summary[key]['path']) == summary[key]['sha256'], 'OWNER_RECEIPT_CHANGED_BEFORE_RECORDING')
        g.validate_artifacts(records)
        row.update(state='READY', result=summary, artifacts=records, reserved_bytes=0, written_bytes=0,
                   heartbeat=time.time(), completion_reconciliation=operator_ref)
        # Owner/token/attempts/logical bytes/billing paths remain original.
        registry.save(state)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    require(sha(PLAN) == PLAN_SHA256, 'SEALED_PLAN_DRIFT')
    plan = json.loads(PLAN.read_bytes())
    live = Path.home() / 'Library/LaunchAgents/com.lexi.v4.scheduler.plist'
    env = plistlib.loads(live.read_bytes())['EnvironmentVariables']
    os.environ.update(env); app = Path(env['V4_APP_ROOT'])
    require(str(app) == plan['source_app'], 'MAIN_APP_CHANGED')
    os.chdir(app); sys.path.insert(0, str(app))
    from ops import research_storage_governance as g, research_panel_qfq as q
    from ops.research_storage_retention import owner_lock
    require(sha(g.__file__) == plan['governance_before_sha256'], 'GOVERNANCE_SOURCE_DRIFT')
    policy = g.configured_policy()
    registry = g.Registry(g.configuration(policy), policy['data_root'])
    formula = json.loads((N / 'DELTA_INTEGRATION_REFERENCE.json').read_bytes())['formula']['kwargs']
    request = json.loads((N / 'PARALLEL_CHAIN_REQUEST.json').read_bytes())
    kwargs = dict(driver_path=app / 'ops/vendor/data_layer_daily_formula_increment_update_v1.py',
        formula_path=Path(formula['canonical_formula_path']), tdx_root=Path(formula['qfq_original_tdx_root']),
        contract_csv=Path(formula['contract_csv']), publish=True, workers=None, refresh_inputs=True,
        storage_layout='arrow_blocks_v1', checkpoint_resume=request['formula_kwargs']['checkpoint_resume'])
    require(g.qfq_invocation_key(q, Path(policy['data_root']), plan['target'], kwargs) == plan['key'], 'OPERATION_KEY_DRIFT')
    if not args.execute:
        _, row = exact_row(g, registry, plan)
        print(json.dumps(dict(status='READ_ONLY_PLAN_READY_FOR_REVIEW', script_sha256=sha(__file__), plan_sha256=sha(PLAN),
            registry_sha256=sha(registry.path), key=plan['key'], owner_state=g.owner_state(row['owner']),
            producer_invoked=False, claim_begin_invoked=False, registry_written=False)))
        return
    with owner_lock(policy), owner_lock(policy, publication=True), registry.writer():
        with registry.transaction():
            exact_row(g, registry, plan)
        ready, summary, records, pointers = validate_current(g, q, policy, kwargs, plan)
        operator = g.process_identity(); require(operator is not None, 'OPERATOR_IDENTITY_UNKNOWN')
        intent = dict(schema='qfq_completed_original_claim_reconciliation.v1', status='VERIFIED_COMPLETION_INTENT',
            recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), operator=operator,
            script=dict(path=str(Path(__file__).resolve()), sha256=sha(__file__)),
            plan=dict(path=str(PLAN), sha256=sha(PLAN)), key=plan['key'],
            before_registry_sha256=plan['expected_registry_sha256'], before_task_sha256=plan['expected_task_sha256'],
            original_owner=plan['expected_owner'], original_attempts=plan['expected_attempts'],
            generation_id=ready['generation_id'], complete_owner_receipt=summary['complete_owner_receipt'],
            ready_owner_receipt=summary['ready_owner_receipt'], artifacts=records,
            method='EXACT_CAS_FINAL_RECORDING_OF_ORIGINAL_COMMITTED_OWNER',
            producer_invoked=False, claim_begin_invoked=False, CURRENT_changed=False, budget_changed=False)
        intent_path = N / ('QFQ_COMPLETION_INTENT_' + canonical(intent) + '.json')
        raw = (json.dumps(intent, ensure_ascii=False, indent=2) + '\n').encode()
        with intent_path.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        operator_ref = dict(path=str(intent_path), sha256=sha(intent_path))
        # All policy/admission inputs are untouched: this only records completion
        # already proved by original owner publication, without new work or space.
        record_completion(g, registry, policy, plan, summary, records, pointers, operator_ref)
        final = registry.read()['tasks'][plan['key']]
        require(final['state'] == 'READY' and final['owner'] == plan['expected_owner']
                and final['token'] == plan['expected_token'] and final['attempts'] == plan['expected_attempts']
                and final['reserved_bytes'] == final['written_bytes'] == 0
                and final['result'] == summary and final['artifacts'] == records, 'FINAL_RECORDING_READBACK_FAILED')
        for role, text in pointers.items():
            require(Path(policy['pointers'][role]).read_text(encoding='utf-8-sig') == text, 'CURRENT_CHANGED_AFTER_RECORDING')
        result = dict(status='ORIGINAL_COMPLETED_CLAIM_RECORDED_READY', key=plan['key'], generation_id=ready['generation_id'],
            before_registry_sha256=plan['expected_registry_sha256'], after_registry_sha256=sha(registry.path),
            original_owner_retained=True, original_attempts=final['attempts'], operator_receipt=operator_ref,
            producer_invoked=False, claim_begin_invoked=False, CURRENT_changed=False, budget_changed=False)
        output = N / 'QFQ_DIRECT_COMPLETION_RESULT_R4.json'
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
