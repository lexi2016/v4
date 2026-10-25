"""Pure source-bound announcement continuation and budget-failure descriptions.

No queue, attempt, job, source, or historical result is created or rewritten here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json


def _sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def request_usage(plan, jobs, *, queue_id):
    """Charge existing source-version attempts, including other job/prompt keys.

    The extension replaces the initial canary quantity limits. Its declared
    workload authorizes each planned request once; logical_attempt accounts for
    the explicitly bound failed-first repair(s), including the original attempt.
    A wrapper/new job never makes these already used source attempts disappear.
    """
    expected = plan['workload']['expected_requests']
    logical = plan['failed']['logical_attempt']
    if type(expected) is not int or expected < 1 or type(logical) is not int or logical not in {2, 3}:
        raise ValueError('EXTENSION_REQUEST_ALLOWANCE_INVALID')
    maximum = expected + logical - 1
    versions = {tuple(e[f] for f in ('article_id', 'source_sha256', 'body_sha256')) for e in plan['entries']}
    original = jobs.get(plan['failed']['queue_key'])
    if (not isinstance(original, dict) or original.get('queue_id') != queue_id
            or original.get('status') != 'FAILED' or original.get('attempt_count') != 1
            or tuple(original.get('identity', {}).get(f) for f in (
                'article_id', 'source_sha256', 'body_sha256')) != tuple(plan['failed'][f] for f in (
                'article_id', 'source_sha256', 'body_sha256'))):
        raise ValueError('EXTENSION_ORIGINAL_ATTEMPT_BUDGET_UNVERIFIED')
    used = 0
    attempts = []
    for key, job in sorted(jobs.items()):
        identity = job.get('identity', {})
        if job.get('queue_id') != queue_id or tuple(identity.get(f) for f in (
                'article_id', 'source_sha256', 'body_sha256')) not in versions:
            continue
        count = job.get('attempt_count')
        if type(count) is not int or count < 0:
            raise ValueError('EXTENSION_SAVED_ATTEMPT_COUNT_INVALID')
        used += count
        attempts.append({'queue_key': key, 'attempt_count': count, 'status': job.get('status'),
                         'queue_record_sha256': _sha(job)})
    return {'max_model_requests': maximum, 'used_model_requests': used,
            'remaining_model_requests': max(0, maximum - used),
            'attempts_sha256': _sha(attempts)}


def recovery_description(plan, *, phase, usage):
    return {'schema': 'v4.manager_workbench.announcement_source_recovery.v1',
            'source_job_id': plan['job_id'], 'report_sha256': plan['report_sha256'],
            'source_artifacts_sha256': _sha(plan['source_artifacts']),
            'capture_product': deepcopy(plan['capture_product']),
            'execution_contract': deepcopy(plan['execution_contract']),
            'stage': phase, **usage}


def budget_identity(plan, payload, *, code, cap):
    # Exclude mutable delivery counters and wrapper/run identities. The final
    # request, source, code/config, stage and cap determine this failure identity.
    identity = {'source_job_id': plan['job_id'], 'report_sha256': plan['report_sha256'],
                'source_artifacts_sha256': _sha(plan['source_artifacts']),
                'execution_contract': plan['execution_contract'],
                'article_id': payload['article_id'], 'source_sha256': payload['source_sha256'],
                'body_sha256': payload['body_sha256'], 'stage': payload['stage'],
                'model_id': payload['model_id'], 'configuration_sha256': payload['configuration_sha256'],
                'prompt_sha256': payload['prompt_sha256'], 'messages_sha256': _sha(payload['messages']),
                'schema_sha256': _sha(payload['structured_output_schema']),
                'chunk_plan_sha256': payload.get('chunk_plan_sha256'),
                'part_descriptor': payload.get('part_descriptor'), 'cap': cap, 'code': code}
    return identity


def budget_failure(plan, payload, *, phase, usage, code, cap):
    identity = budget_identity(plan, payload, code=code, cap=cap)
    return {'schema': 'v4.manager_workbench.announcement_request_budget_failure.v1',
            'fingerprint': _sha(identity), 'identity': identity, 'failure_code': code,
            'prompt_tokens_exact': payload['prompt_tokens_exact'], 'prompt_token_cap': cap,
            'model_requests': 0, 'queue_attempts': 0,
            'queue_action': 'ISOLATED_NO_ATTEMPT_NO_AUTOMATIC_RETRY',
            'recovery': recovery_description(plan, phase=phase, usage=usage)}


def extension_snapshot(plan, checkpoint, delivery, binding, *, job_is_partial, semantic):
    """Project the already verified original job/report and immutable delivery."""
    versions = {tuple(e[f] for f in ('article_id', 'source_sha256', 'body_sha256')) for e in plan['entries']}
    remaining = sum(e.get('state') in {'PENDING', 'DEFERRED'} for e in delivery['articles']
                    if tuple(e.get(f) for f in ('article_id', 'source_sha256', 'body_sha256')) in versions)
    phase = ('RECOVER_FAILED' if checkpoint is None or checkpoint[1] == 'PENDING'
             else 'CONTINUE_REMAINING' if checkpoint[1] == 'SUCCEEDED' else None)
    eligible = job_is_partial and phase is not None and (phase == 'RECOVER_FAILED' or remaining > 0)
    result = {**semantic, 'status': 'READY' if eligible else 'BLOCKED', 'eligible': eligible,
              'job_id': plan['job_id'], 'target_date': plan['target_date'],
              'report_sha256': plan['report_sha256'], 'delivery_sha256': binding['sha256'],
              'phase': phase, 'total_articles': len(plan['entries']), 'remaining_articles': remaining,
              'failed_article_id': plan['failed']['article_id'], 'checkpoint_state': checkpoint[1] if checkpoint else None}
    recovery = delivery.get('recovery')
    if recovery is not None:
        for field, expected in (
                ('source_job_id', plan['job_id']), ('report_sha256', plan['report_sha256']),
                ('execution_contract', plan['execution_contract']),
                ('source_artifacts_sha256', _sha(plan['source_artifacts']))):
            if recovery.get(field) != expected:
                raise ValueError('EXTENSION_RECOVERY_DESCRIPTION_CHANGED')
        result['recovery'] = deepcopy(recovery)
    return result
