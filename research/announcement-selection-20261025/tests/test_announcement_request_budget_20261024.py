"""Task5 offline boundary tests: no provider, live state, or historical replay."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from infrastructure.owned_io import SafeRoot
from ops import run_manager_flash_announcements as bridge
from v4.manager_workbench import announcement_delivery as delivery
from v4.manager_workbench.announcement_preprocessing import SEMANTIC_CONTRACT

JOB = 'a' * 32
REPORT = 'b' * 64
EXTENSION = 'c' * 64


def digest(value):
    return hashlib.sha256(bridge.canonical(value)).hexdigest()


@pytest.fixture(autouse=True)
def disconnected(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('Task5 attempted socket/provider access')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(bridge, '_load_helper', forbidden)


def payload(aid, text='legal'):
    return {'article_id': aid, 'source_sha256': digest(aid + 'source'), 'body_sha256': digest(text),
            'article_body': text, 'article_metadata': {'symbol': 'HK.00001', 'publication_date': '2026-10-21'},
            'date': '2026-10-21', 'market': 'HK', 'model_id': 'qwen3_8_flash_next',
            'rules': 'fixture+temperature:0.0+thinking:off', 'stage': 'ordinary', 'role': 'announcement_reader',
            'messages': [{'role': 'system', 'content': 'base'}, {'role': 'user', 'content': text}],
            'prompt_sha256': digest('base'), 'configuration_sha256': 'd' * 64,
            'structured_output_schema': {'type': 'object'}, 'workflow_profile': bridge.PROFILE,
            'prompt_tokens_exact': 1}


def tokens(messages):
    # The body fits by itself; the final semantic instruction tips only BIG over cap.
    body = messages[-1]['content']
    return 101 if body == 'BIG' and SEMANTIC_CONTRACT in messages[0]['content'] else 1


@pytest.fixture
def extension_case(tmp_path, monkeypatch):
    root = tmp_path / 'isolated-state'; root.mkdir()
    originals = [payload('saved-' + str(i)) for i in range(14)]
    bad, neighbor = payload('oversize', 'BIG'), payload('neighbor')
    payloads = originals + [bad, neighbor]
    entries = [{**{k: p[k] for k in ('article_id', 'source_sha256', 'body_sha256')},
                'source_date': p['date'], 'symbol': 'HK.00001', 'primary_disposition': 'MODEL_ORDINARY',
                'part_count': 0, 'expected_requests': 1} for p in payloads]
    failed = {**{k: originals[0][k] for k in ('article_id', 'source_sha256', 'body_sha256')},
              'queue_key': 'e' * 64, 'logical_attempt': 2}
    plan = {'job_id': JOB, 'report_sha256': REPORT, 'target_date': '20261021', 'entries': entries,
            'failed': failed, 'source_artifacts': [{'root': 'state', 'artifact_ref': 'frozen-input', 'sha256': 'f' * 64}],
            'capture_product': {'sha256': '1' * 64}, 'execution_contract': {'implementation_sha256': '2' * 64,
                'configuration_sha256': 'd' * 64}, 'workload': {'articles': 16, 'expected_requests': 16}}
    material = {'runtime_limits': {'context_limit_tokens': 33892},
                'configuration_material': {'max_completion_tokens': 32768, 'semantic_contract_version': 'v1'},
                'configuration_sha256': 'd' * 64, 'runtime_settings_sha256': '3' * 64, 'model_settings_sha256': '4' * 64}
    jobs, stored, posts = {}, {}, []
    articles = []
    for p in payloads:
        key = digest(p['article_id'])
        saved = p in originals
        row = {**{k: p[k] for k in ('article_id', 'source_sha256', 'body_sha256')},
               'state': 'SUCCEEDED' if saved else 'DEFERRED', 'producer_sha256': 'original-producer'}
        if saved:
            item = {'idempotency_key': key, 'identity': {k: p[k] for k in bridge.QUEUE_IDENTITY_FIELDS},
                    'queue_id': bridge.QUEUE_ID, 'status': 'SUCCEEDED', 'attempt_count': 1,
                    'max_attempts': 1, 'attempts': [{'number': 1, 'status': 'SUCCEEDED'}],
                    'validated_path': 'synthetic/' + key, 'validated_sha256': digest(key)}
            jobs[key] = item; stored[key] = deepcopy(p)
            row.update(queue_key=key, result_ref=item['validated_path'], result_sha256=item['validated_sha256'])
        articles.append(row)
    # The extension's logical second attempt never erases the original failed
    # first request; both that failure and its saved replacement are charged.
    original_key = failed['queue_key']
    jobs[original_key] = {**deepcopy(jobs[digest(originals[0]['article_id'])]),
        'idempotency_key': original_key, 'status': 'FAILED',
        'attempts': [{'number': 1, 'status': 'FAILED'}]}
    stored[original_key] = deepcopy(originals[0])
    snap = {'schema': delivery.SCHEMA, 'job_id': JOB, 'preprocessing_report_sha256': REPORT,
            'state': 'PARTIAL', 'articles': articles}
    delivery.publish(SafeRoot(root), JOB, snap)
    preserved = deepcopy(jobs)
    class Queue:
        def _load_state(self): return {'jobs': deepcopy(jobs)}
        def enqueue(self, p):
            key = digest(p); stored[key] = deepcopy(p)
            jobs[key] = {'idempotency_key': key, 'queue_id': bridge.QUEUE_ID,
                         'identity': {k: p[k] for k in bridge.QUEUE_IDENTITY_FIELDS},
                         'status': 'PENDING', 'attempt_count': 0, 'max_attempts': 1, 'attempts': [],
                         'validated_path': 'synthetic/' + key, 'validated_sha256': digest(key)}
            return deepcopy(jobs[key])
    def saved(p, *_args, **_kwargs):
        matches = [(k, j) for k, j in jobs.items() if j['identity']['article_id'] == p['article_id']
                   and (stored[k].get('queue_task_kind') == p.get('queue_task_kind')
                        or p.get('queue_task_kind') != 'announcement_reader_part'
                        and stored[k].get('queue_task_kind') != 'announcement_reader_part')]
        return deepcopy(matches[0]) if matches else None
    def dispatch(_q, _ex, _v, keys, *, completed, dispatched_keys, **_kwargs):
        key, = keys; posts.append(deepcopy(stored[key])); dispatched_keys.append(key)
        jobs[key].update(status='SUCCEEDED', attempt_count=1, attempts=[{'number': 1, 'status': 'SUCCEEDED'}])
        return completed + 1, None
    monkeypatch.setattr(bridge, '_extension_plan', lambda *_a: (deepcopy(plan), EXTENSION))
    monkeypatch.setattr(bridge, '_owned_request_material', lambda *_a: deepcopy(material))
    monkeypatch.setattr(bridge, '_validator', lambda *_a: object())
    monkeypatch.setattr(bridge, '_extension_saved_task', saved)
    monkeypatch.setattr(bridge, '_queue_payload', lambda _r, j: deepcopy(stored[j['idempotency_key']]))
    monkeypatch.setattr(bridge, '_queue_result', lambda _r, j: (deepcopy(stored[j['idempotency_key']]), {}))
    monkeypatch.setattr(bridge, '_public_article', lambda _a, p, _o: {k: p[k] for k in ('article_id', 'source_sha256', 'body_sha256')})
    monkeypatch.setattr(bridge, '_transport_executor', lambda *_a: object())
    monkeypatch.setattr(bridge, '_dispatch_pending_queue_keys', dispatch)
    transport = SimpleNamespace(close=lambda: None)
    canary = SimpleNamespace(GatedStreamingTransport=lambda *_a, **_kw: transport)
    runner = SimpleNamespace(load_local_api_key=lambda: 'synthetic-key', MODEL_ID='qwen3_8_flash_next')
    kwargs = dict(state_root=root, capture_root=tmp_path / 'isolated-capture', job_id=JOB, report={},
                  report_sha256=REPORT, extension_sha256=EXTENSION, phase='CONTINUE_REMAINING',
                  payloads=payloads, long_specs={}, queue=Queue(), helper=None, runner=runner,
                  contract=None, canary=canary, queue_module=SimpleNamespace(ModelSlotBusy=type('Busy', (Exception,), {})),
                  length_canary=None, count_tokens=tokens, progress=lambda _v: None, stop_requested=lambda: False)
    def run(): return bridge._execute_extension({'target_date': '20261021', 'cutoff': '2026-10-21T18:00:00+08:00'}, **kwargs)
    return SimpleNamespace(run=run, root=root, jobs=jobs, preserved=preserved, posts=posts,
                           plan=plan, material=material, kwargs=kwargs, bad=bad, payloads=payloads, stored=stored)


def test_final_contract_overflow_isolates_article_and_preserves_14_successes(extension_case):
    c = extension_case
    result = c.run()
    assert result['state'] == 'PARTIAL'
    assert result['counts']['queue'] == {'succeeded': 15, 'failed': 1, 'pending': 0}
    assert [p['article_id'] for p in c.posts] == ['neighbor']
    assert SEMANTIC_CONTRACT in c.posts[0]['messages'][0]['content']
    for key, item in c.preserved.items(): assert c.jobs[key] == item
    snapshot, _ = delivery.read(SafeRoot(c.root), JOB)
    failure = next(a for a in snapshot['articles'] if a['article_id'] == 'oversize')
    assert failure['failure_code'] == 'EXTENSION_PROMPT_TOKEN_CAP_EXCEEDED'
    assert failure['request_budget_failure']['model_requests'] == 0
    assert failure['request_budget_failure']['queue_attempts'] == 0
    assert all(a.get('producer_sha256') == 'original-producer' for a in snapshot['articles'][:14])


def test_same_budget_failure_reentry_does_not_reset_attempts_or_issue_requests(extension_case):
    c = extension_case; c.run(); before = deepcopy(c.jobs)
    snapshot, _ = delivery.read(SafeRoot(c.root), JOB)
    fingerprint = next(a for a in snapshot['articles'] if a['article_id'] == 'oversize')['request_budget_failure']['fingerprint']
    result = c.run()
    again, _ = delivery.read(SafeRoot(c.root), JOB)
    assert result['model_requests'] == 0 and len(c.posts) == 1 and c.jobs == before
    failure = next(a for a in again['articles'] if a['article_id'] == 'oversize')
    assert failure['request_budget_failure']['fingerprint'] == fingerprint
    assert len(failure['request_budget_failures']) == 1
    assert again['recovery']['used_model_requests'] == 16
    assert again['recovery']['remaining_model_requests'] == 1


def test_unknown_tokenizer_error_is_terminal_without_enqueue(extension_case):
    c = extension_case
    def broken(_m): raise RuntimeError('TOKENIZER_UNKNOWN_FAILURE')
    c.kwargs['count_tokens'] = broken
    with pytest.raises(RuntimeError, match='TOKENIZER_UNKNOWN_FAILURE'): c.run()
    assert c.posts == [] and c.jobs == c.preserved


def test_facade_builds_and_counts_complete_messages_without_mutating_source():
    p = payload('oversize', 'BIG'); before = deepcopy(p)
    with pytest.raises(bridge.FlashRunError, match='EXTENSION_PROMPT_TOKEN_CAP_EXCEEDED'):
        bridge._extension_payload(p, {'configuration_sha256': 'd' * 64}, {'failed': {'article_id': 'other'}}, EXTENSION, tokens, 100)
    assert p == before
    exact = bridge._extension_payload(p, {'configuration_sha256': 'd' * 64}, {'failed': {'article_id': 'other'}}, EXTENSION, tokens, 101)
    assert exact['prompt_tokens_exact'] == 101 and exact['article_body'] == 'BIG'


def test_known_failure_does_not_even_recount_unchanged_final_request(extension_case):
    c = extension_case; c.run(); before = deepcopy(c.jobs)
    def changed_counter(_messages):
        pytest.fail('unchanged failed or successful input must not be blindly re-preflighted')
    c.kwargs['count_tokens'] = changed_counter
    assert c.run()['model_requests'] == 0
    assert c.jobs == before and len(c.posts) == 1


def test_part_final_contract_overflow_is_article_local(extension_case):
    c = extension_case
    entry = next(e for e in c.plan['entries'] if e['article_id'] == 'oversize')
    entry.update(primary_disposition='MODEL_LONG', part_count=1, expected_requests=2)
    c.plan['workload']['expected_requests'] += 1
    c.kwargs['payloads'] = [p for p in c.payloads if p['article_id'] != 'oversize']
    descriptor = {'part_index': 1, 'part_count': 1, 'part_sha256': '5' * 64}
    part = {**deepcopy(c.bad), 'queue_task_kind': 'announcement_reader_part', 'stage': 'part',
            'chunk_plan_sha256': '6' * 64, 'part_descriptor': descriptor}
    c.kwargs['long_specs'] = {'oversize': {'article': deepcopy(c.bad),
        'plan': {'parts': [descriptor]}, 'part_payloads': [part]}}
    result = c.run()
    assert result['state'] == 'PARTIAL' and [p['article_id'] for p in c.posts] == ['neighbor']
    snapshot, _ = delivery.read(SafeRoot(c.root), JOB)
    failure = next(a for a in snapshot['articles'] if a['article_id'] == 'oversize')
    assert failure['request_budget_failure']['identity']['stage'] == 'part'
    assert failure['request_budget_failure']['identity']['chunk_plan_sha256'] == '6' * 64
    before = deepcopy(c.jobs)
    assert c.run()['model_requests'] == 0 and c.jobs == before


def test_original_source_attempts_charge_budget_across_wrapper_jobs(extension_case):
    from v4.manager_workbench.announcement_resume import request_usage, recovery_description
    c = extension_case
    base = request_usage(c.plan, c.jobs, queue_id=bridge.QUEUE_ID)
    assert base['used_model_requests'] == 15 and base['remaining_model_requests'] == 2
    wrapper = deepcopy(c.plan); wrapper['job_id'] = '9' * 32
    assert request_usage(wrapper, c.jobs, queue_id=bridge.QUEUE_ID) == base
    recovery = recovery_description(c.plan, phase='CONTINUE_REMAINING', usage=base)
    assert recovery['source_job_id'] == JOB and recovery['report_sha256'] == REPORT
    assert recovery['execution_contract'] == c.plan['execution_contract']
    assert recovery['stage'] == 'CONTINUE_REMAINING'
    # No new request is admitted after all original source attempts are charged.
    for j in c.jobs.values():
        if j['status'] == 'SUCCEEDED': j['attempt_count'] = 2
    before = deepcopy(c.jobs)
    result = c.run()
    assert result['state'] == 'PARTIAL' and c.posts == [] and c.jobs == before
    assert result['system_stop']['failure_code'] == 'EXTENSION_REQUEST_BUDGET_EXHAUSTED'


def test_failure_fingerprint_tracks_source_code_config_and_stage_only(extension_case):
    from v4.manager_workbench.announcement_request_budget import finalize_extension_payload
    from v4.manager_workbench.announcement_resume import budget_failure, request_usage
    c = extension_case
    p = finalize_extension_payload(c.bad, c.material, c.plan, EXTENSION)
    p['prompt_tokens_exact'] = 101
    usage = request_usage(c.plan, c.jobs, queue_id=bridge.QUEUE_ID)
    def failure(plan=c.plan, value=p, used=usage, phase='CONTINUE_REMAINING'):
        return budget_failure(plan, value, phase=phase, usage=used,
            code='EXTENSION_PROMPT_TOKEN_CAP_EXCEEDED', cap=100)['fingerprint']
    fp = failure()
    assert failure(used={**usage, 'remaining_model_requests': 0}, phase='RECOVER_FAILED') == fp
    for field in ('source_sha256', 'body_sha256', 'configuration_sha256', 'stage'):
        changed = deepcopy(p); changed[field] = 'changed'
        assert failure(value=changed) != fp
    changed = deepcopy(c.plan); changed['execution_contract']['implementation_sha256'] = '7' * 64
    assert failure(plan=changed) != fp


def test_recovery_snapshot_facade_retains_original_bound_identity(extension_case, monkeypatch):
    from v4.manager_workbench import announcement_update as facade
    from v4.manager_workbench.contracts import JobState
    c = extension_case; c.run()
    _, bound = delivery.read(SafeRoot(c.root), JOB)
    monkeypatch.setattr(bridge, '_extension_checkpoint', lambda *_a: ('saved-key', 'SUCCEEDED'))
    service = SimpleNamespace(store=SimpleNamespace(root=c.root, io=SafeRoot(c.root)),
        jobs=SimpleNamespace(get=lambda _j: SimpleNamespace(state=JobState.PARTIAL)),
        config=SimpleNamespace(capture_root=c.root / 'isolated-capture'))
    owner = facade.AnnouncementUpdate(service)
    monkeypatch.setattr(owner, '_stop_requested', lambda _j: False)
    snapshot = owner.semantic_recovery_snapshot(JOB, REPORT)
    assert snapshot['job_id'] == JOB and snapshot['report_sha256'] == REPORT
    assert snapshot['delivery_sha256'] == bound['sha256'] and snapshot['remaining_articles'] == 0
    assert snapshot['recovery']['used_model_requests'] == 16 and snapshot['eligible'] is False
    # A source/code change never silently relabels the previous recovery receipt.
    c.plan['execution_contract']['implementation_sha256'] = '8' * 64
    blocked = owner.semantic_recovery_snapshot(JOB, REPORT)
    assert blocked['eligible'] is False and blocked['reason'] == 'EXTENSION_RECOVERY_DESCRIPTION_CHANGED'


def test_source_and_safety_errors_remain_terminal(extension_case, monkeypatch):
    c = extension_case
    def invalid(*_a): raise bridge.FlashRunError('EXTENSION_SOURCE_ARTIFACT_CHANGED')
    monkeypatch.setattr(bridge, '_extension_plan', invalid)
    with pytest.raises(bridge.FlashRunError, match='SOURCE_ARTIFACT_CHANGED'): c.run()
    assert c.posts == [] and c.jobs == c.preserved


@pytest.mark.parametrize('cap,count', [(0, 1), (100, -1), (100, True), (100, '101')])
def test_unknown_or_invalid_budget_is_never_deterministic_overflow(cap, count):
    from v4.manager_workbench.announcement_request_budget import preflight, RequestBudgetError
    with pytest.raises(ValueError) as exc:
        preflight(payload('test'), lambda _m: count, cap)
    assert not isinstance(exc.value, RequestBudgetError)


def test_synthesis_overflow_preserves_completed_part_and_legal_neighbor(extension_case, monkeypatch):
    from v4.manager_workbench import announcement_chunks as chunks
    c = extension_case
    entry = next(e for e in c.plan['entries'] if e['article_id'] == 'oversize')
    entry.update(primary_disposition='MODEL_LONG', part_count=1, expected_requests=2)
    c.plan['workload']['expected_requests'] += 1
    c.kwargs['payloads'] = [p for p in c.payloads if p['article_id'] != 'oversize']
    descriptor = {'part_index': 1, 'part_count': 1, 'part_sha256': '5' * 64}
    part = {**deepcopy(c.bad), 'queue_task_kind': 'announcement_reader_part', 'stage': 'part',
            'chunk_plan_sha256': '6' * 64, 'part_descriptor': descriptor}
    item = c.kwargs['queue'].enqueue(part); key = item['idempotency_key']
    c.jobs[key].update(status='SUCCEEDED', attempt_count=1, attempts=[{'number': 1, 'status': 'SUCCEEDED'}])
    saved_part = deepcopy(c.jobs[key])
    c.bad['fixed_fact_ledger'] = {}
    c.kwargs['long_specs'] = {'oversize': {'article': deepcopy(c.bad),
        'plan': {'parts': [descriptor], 'plan_sha256': '6' * 64, 'batch_binding_sha256': '7' * 64},
        'unit_map': {'source_unit_map_sha256': '8' * 64}, 'batch': {}, 'part_payloads': [part]}}
    c.material.update(prompt='original prompt\n\n' + SEMANTIC_CONTRACT,
        schema={'properties': {'facts': {'type': 'array'}, 'changes': {'type': 'array'}}}, citation_protocol='fixture')
    monkeypatch.setattr(bridge, '_read_internal_validated_result',
        lambda *_a: ({'reader_output': {}, 'citation_ranges': []}, '9' * 64, '0' * 64))
    monkeypatch.setattr(chunks, 'cross_part_ledger', lambda *_a, **_kw: {})
    monkeypatch.setattr(chunks, 'synthesis_intervals_from_reports', lambda *_a, **_kw: [])
    monkeypatch.setattr(chunks, 'reader_task_system_prompt', lambda prompt, _kind: prompt)
    monkeypatch.setattr(bridge, '_synthesis_messages', lambda **kw: [
        {'role': 'system', 'content': kw['system_prompt']}, {'role': 'user', 'content': 'BIG'}])
    result = c.run()
    assert result['state'] == 'PARTIAL' and [p['article_id'] for p in c.posts] == ['neighbor']
    assert c.jobs[key] == saved_part
    snapshot, _ = delivery.read(SafeRoot(c.root), JOB)
    failure = next(a for a in snapshot['articles'] if a['article_id'] == 'oversize')
    assert failure['failure_code'] == 'EXTENSION_SYNTHESIS_TOKEN_CAP_EXCEEDED'
    assert failure['parts_complete'] == 1
    before = deepcopy(c.jobs)
    c.kwargs['count_tokens'] = lambda _m: pytest.fail('known synthesis failure must not be recounted')
    assert c.run()['model_requests'] == 0 and c.jobs == before


@pytest.mark.parametrize('verdict', ['FAIL', 'PENDING'])
def test_semantic_approval_still_blocks_continuation(extension_case, monkeypatch, verdict):
    c = extension_case; c.plan['semantic_repair'] = {'queue_key': 'original-rejected-key'}
    monkeypatch.setattr(bridge, '_semantic_canary_review', lambda *_a: (verdict, None))
    with pytest.raises(bridge.FlashRunError, match='EXTENSION_SEMANTIC_CANARY_NOT_ACCEPTED'):
        c.run()
    assert c.posts == [] and c.jobs == c.preserved


def test_missing_original_attempt_or_unbound_allowance_is_terminal(extension_case):
    from v4.manager_workbench.announcement_resume import request_usage
    c = extension_case
    missing = deepcopy(c.jobs); missing.pop(c.plan['failed']['queue_key'])
    with pytest.raises(ValueError, match='EXTENSION_ORIGINAL_ATTEMPT_BUDGET_UNVERIFIED'):
        request_usage(c.plan, missing, queue_id=bridge.QUEUE_ID)
    unknown = deepcopy(c.plan); unknown['failed']['logical_attempt'] = 4
    with pytest.raises(ValueError, match='EXTENSION_REQUEST_ALLOWANCE_INVALID'):
        request_usage(unknown, c.jobs, queue_id=bridge.QUEUE_ID)
