"""Host-owned Reader/Reviewer transport and read-only, preclaim input checks.

No worker is installed here. A caller may inject its existing channel object
with channel_id, submit(task), and poll(task_id, request_sha256). Submission is
explicit and never retried here; polling never submits. The original e06d owner
still performs all authoritative evidence/content checks before import.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from v5_shadow.contracts import aware, exact_keys, sha, trade_date
from v5_shadow.digests import canonical_bytes, sha256_json
from v5_shadow.module_api import _open_directory, _read_regular

CREATE_KEYS = ('parent_root','recovery_sha256','revision_id','parent_product_sha256','parent_receipt_sha256',
    'semantic_catalog','semantic_sha256','reviewer_output','reviewer_sha256','decisions','decisions_sha256')
OUTPUTS = dict(semantic_catalog='semantic_sha256', reviewer_output='reviewer_sha256', decisions='decisions_sha256')
INPUT_LIMIT = 64 * 1024 * 1024  # Original SafeRoot.read_bytes limit, unchanged.


def _text(value, code):
    if not isinstance(value,str) or not value.strip() or len(value)>256:raise ValueError(code)
    return value


def _identities(reader, reviewer):
    _text(reader,'DAILY_REVISION_REVIEW_IDENTITIES');_text(reviewer,'DAILY_REVISION_REVIEW_IDENTITIES')
    if reader==reviewer:raise ValueError('DAILY_REVISION_DISTINCT_REVIEWER')


def _path(value):
    if not isinstance(value,str):raise ValueError('REVISION_INPUT_PATH_INVALID')
    path=Path(value)
    if not path.is_absolute() or '..' in path.parts:raise ValueError('REVISION_INPUT_PATH_INVALID')
    return path


def _read_file(value, expected, root=None):
    path=_path(value);sha(expected)
    if root is not None and not path.is_relative_to(root):raise ValueError('REVISION_INPUT_OUTSIDE_PARENT_ROOT')
    parent=_open_directory(path.parent);fd=None
    try:
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        raw=_read_regular(fd,INPUT_LIMIT)
    finally:
        if fd is not None:os.close(fd)
        os.close(parent)
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('REVISION_INPUT_SHA_MISMATCH')
    return json.loads(raw)


def _binding(value):
    exact_keys(value,('revision_id','parent_product_sha256','parent_owner_receipt_file_sha256',
        'source_recovery_receipt_sha256','source_run_id'))
    if not isinstance(value['revision_id'],str) or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}',value['revision_id']):
        raise ValueError('REVISION_ID_INVALID')
    for name in ('parent_product_sha256','parent_owner_receipt_file_sha256','source_recovery_receipt_sha256'):sha(value[name])
    if not isinstance(value['source_run_id'],str) or not re.fullmatch('[0-9a-f]{32}',value['source_run_id']):
        raise ValueError('REVISION_SOURCE_RUN_INVALID')


def _task(task,now):
    exact_keys(task,('schema_version','task_id','channel_id','target_date','source_run_id','reader_identity',
        'reviewer_identity','review_scope','decision_revision','input_files','created_at','deadline','heartbeat_timeout_seconds'))
    if task['schema_version']!='v5.announcement_review_task.v1':raise ValueError('REVIEW_TASK_SCHEMA')
    for name in ('task_id','channel_id'):_text(task[name],'REVIEW_TASK_IDENTITY')
    trade_date(task['target_date']);_identities(task['reader_identity'],task['reviewer_identity']);_binding(task['decision_revision'])
    if task['source_run_id']!=task['decision_revision']['source_run_id']:raise ValueError('REVIEW_TASK_SOURCE_MISMATCH')
    if task['review_scope'] not in {'REVISION_BINDING_ONLY','READ_AND_REVIEW'}:raise ValueError('REVIEW_TASK_SCOPE')
    if not isinstance(task['input_files'],dict) or not task['input_files']:raise ValueError('REVIEW_TASK_INPUTS')
    for name,reference in task['input_files'].items():
        _text(name,'REVIEW_TASK_INPUTS');exact_keys(reference,('path','sha256'));_path(reference['path']);sha(reference['sha256'])
    if task['review_scope']=='REVISION_BINDING_ONLY' and not {'semantic_catalog','decisions'}<=set(task['input_files']):
        raise ValueError('REVIEW_TASK_FROZEN_INPUTS_REQUIRED')
    if (aware(task['created_at'])>now or aware(task['created_at'])>=aware(task['deadline'])
            or type(task['heartbeat_timeout_seconds']) is not int or not 1<=task['heartbeat_timeout_seconds']<=3600):
        raise ValueError('REVIEW_TASK_CLOCK')
    canonical_bytes(task)


def validate_review_return(task,receipt,*,now=None):
    """Validate transport declarations; this is not a semantic-review verdict."""
    now=now or datetime.now(timezone.utc);_task(task,now)
    exact_keys(receipt,('schema_version','task_id','request_sha256','channel_id','source_run_id','reader_identity',
        'reviewer_identity','status','submitted_at','heartbeat_at','reason_codes','output_files'))
    if receipt['schema_version']!='v5.announcement_review_return.v1':raise ValueError('REVIEW_RETURN_SCHEMA')
    if receipt['request_sha256']!=sha256_json(task):raise ValueError('REVIEW_RETURN_REQUEST_MISMATCH')
    for name in ('task_id','channel_id','source_run_id','reader_identity','reviewer_identity'):
        if receipt[name]!=task[name]:raise ValueError('REVIEW_RETURN_IDENTITY_MISMATCH')
    if receipt['status'] not in {'SUBMITTED','RUNNING','FAILED','COMPLETED','OUTCOME_UNKNOWN'}:raise ValueError('REVIEW_RETURN_STATUS')
    started=aware(receipt['submitted_at']);heartbeat=aware(receipt['heartbeat_at'])
    if not aware(task['created_at'])<=started<=heartbeat<=now or heartbeat>aware(task['deadline']):
        raise ValueError('REVIEW_RETURN_CLOCK')
    if receipt['status'] in {'SUBMITTED','RUNNING'} and (now-heartbeat).total_seconds()>task['heartbeat_timeout_seconds']:
        raise ValueError('REVIEW_HEARTBEAT_STALE')
    reasons=receipt['reason_codes']
    if not isinstance(reasons,list) or any(not isinstance(r,str) or not r for r in reasons):raise ValueError('REVIEW_RETURN_REASONS')
    if receipt['status'] in {'FAILED','OUTCOME_UNKNOWN'} and not reasons:raise ValueError('REVIEW_RETURN_FAILURE_REASON_REQUIRED')
    if receipt['status']=='COMPLETED':
        exact_keys(receipt['output_files'],OUTPUTS)
        for reference in receipt['output_files'].values():
            exact_keys(reference,('path','sha256'));_path(reference['path']);sha(reference['sha256'])
    elif receipt['output_files']!={}:raise ValueError('REVIEW_RETURN_PREMATURE_OUTPUTS')
    return dict(status=receipt['status'],request_sha256=sha256_json(task),
        receipt=json.loads(canonical_bytes(receipt)),retry_submission_automatically=False,natural_verified=False)


def _exchange(task,channel,operation,now):
    live_clock=now is None
    now=now or datetime.now(timezone.utc);_task(task,now)
    result=dict(request_sha256=sha256_json(task),retry_submission_automatically=False,natural_verified=False)
    if channel is None:return dict(result,status='BLOCKED_REVIEW_CHANNEL_NOT_BOUND')
    if getattr(channel,'channel_id',None)!=task['channel_id']:raise ValueError('REVIEW_CHANNEL_IDENTITY_MISMATCH')
    if operation=='submit' and now>=aware(task['deadline']):return dict(result,status='BLOCKED_REVIEW_WINDOW_CLOSED')
    # Existing source bytes, not self-declared hashes alone, precede submission.
    for reference in task['input_files'].values():_read_file(reference['path'],reference['sha256'])
    try:
        if operation=='submit':receipt=channel.submit(json.loads(canonical_bytes(task)))
        else:receipt=channel.poll(task['task_id'],result['request_sha256'])
    except Exception as error:
        return dict(result,status='OUTCOME_UNKNOWN_NO_AUTOMATIC_RETRY' if operation=='submit' else 'BLOCKED_REVIEW_POLL_FAILED',
            reason_codes=[type(error).__name__])
    # A real channel stamps its receipt inside the callback, after admission.
    # Keep an explicitly supplied clock fixed for deterministic host callers.
    returned_at=datetime.now(timezone.utc) if live_clock else now
    try:return validate_review_return(task,receipt,now=returned_at)
    except (ValueError,TypeError,KeyError):return dict(result,status='BLOCKED_INVALID_REVIEW_RETURN')


def submit_review_task(task,*,channel=None,now=None):
    """Explicit single submission to the already-bound host channel; no retries."""
    return _exchange(task,channel,'submit',now)


def poll_review_task(task,*,channel=None,now=None):
    """Poll only: this function can never submit or consume a business attempt."""
    return _exchange(task,channel,'poll',now)


def preflight_revision(request,*,now=None):
    """Block known missing/invalid review inputs before claiming a daily attempt.

    READY_FOR_ORIGINAL_OWNER means these structural checks passed, not that the
    parent, content, or external reviewer has been authoritatively accepted.
    """
    now=now or datetime.now(timezone.utc)
    base=dict(original_owner_verified=False,natural_verified=False)
    try:
        create=request.get('revision_create');identities=request.get('review_identities')
        if not create or not identities:return dict(base,status='BLOCKED',reason_codes=['WAITING_REAL_SEMANTIC_DECISIONS_AND_INDEPENDENT_REVIEWER'])
        if not isinstance(create,dict) or set(create)!=set(CREATE_KEYS):raise ValueError('DAILY_REVISION_CREATE_CONTRACT')
        if not isinstance(identities,dict) or set(identities)!={'parent_task_id','reader_identity','reviewer_identity'}:
            raise ValueError('DAILY_REVISION_REVIEW_IDENTITIES')
        _text(identities['parent_task_id'],'DAILY_REVISION_REVIEW_IDENTITIES')
        _identities(identities['reader_identity'],identities['reviewer_identity']);trade_date(request['target_date'])
        root=_path(create['parent_root'])
        recovery=_read_file(str(root/'recovery_receipt.json'),create['recovery_sha256'],root)
        binding=dict(revision_id=create['revision_id'],parent_product_sha256=create['parent_product_sha256'],
            parent_owner_receipt_file_sha256=create['parent_receipt_sha256'],
            source_recovery_receipt_sha256=create['recovery_sha256'],source_run_id=recovery['source_run_id'])
        _binding(binding)
        if recovery.get('derived_root')!=str(root):raise ValueError('REVISION_RECOVERY_ROOT_MISMATCH')
        documents={key:_read_file(create[key],create[sha_key],root) for key,sha_key in OUTPUTS.items()}
        reviewer=documents['reviewer_output']
        if not isinstance(reviewer,dict) or reviewer.get('decision_revision')!=binding:raise ValueError('REVISION_REVIEW_BINDING_INVALID')
        if reviewer.get('semantic_catalog_sha256')!=create['semantic_sha256']:
            raise ValueError('REVISION_REVIEW_SEMANTIC_SHA_MISMATCH')
        if (reviewer.get('schema_version')!='v4.manager_research.announcement_agent_review.v1'
                or reviewer.get('review_conclusion')!='PASS' or reviewer.get('target_trade_date')!=request['target_date']
                or reviewer.get('evidence_run_id')!=binding['source_run_id']
                or any(reviewer.get(k)!=identities[k] for k in ('reader_identity','reviewer_identity'))
                or aware(reviewer.get('reviewed_at'))>now):raise ValueError('DAILY_REVISION_REVIEW_OUTPUT_INVALID')
        document=documents['decisions']
        decisions=document['article_decisions'] if isinstance(document,dict) and set(document)=={'article_decisions'} else document
        logical_sha=hashlib.sha256(json.dumps(decisions,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        if (not isinstance(decisions,list) or not decisions or reviewer.get('decision_status')!='EXPLICIT_DISPOSITIONS'
                or reviewer.get('decision_payload_sha256')!=logical_sha):raise ValueError('REVISION_EXPLICIT_DECISIONS_REVIEW_REQUIRED')
        if 'review_handoff' in request:
            handoff=request['review_handoff'];exact_keys(handoff,('task','receipt'))
            task=handoff['task'];returned=validate_review_return(task,handoff['receipt'],now=now)
            if returned['status']!='COMPLETED':return dict(base,status='BLOCKED',reason_codes=['WAITING_REVIEW_RETURN_'+returned['status']])
            if (task['decision_revision']!=binding or task['target_date']!=request['target_date']
                    or any(task[k]!=identities[k] for k in ('reader_identity','reviewer_identity'))):raise ValueError('REVIEW_TASK_REVISION_MISMATCH')
            expected={key:dict(path=create[key],sha256=create[sha_key]) for key,sha_key in OUTPUTS.items()}
            if handoff['receipt']['output_files']!=expected:raise ValueError('REVIEW_RETURN_OUTPUT_MISMATCH')
            if task['review_scope']=='REVISION_BINDING_ONLY' and any(task['input_files'][k]!=expected[k] for k in ('semantic_catalog','decisions')):
                raise ValueError('REVIEW_FROZEN_DECISIONS_CHANGED')
        return dict(base,status='READY_FOR_ORIGINAL_OWNER',reason_codes=[])
    except FileNotFoundError:return dict(base,status='BLOCKED',reason_codes=['WAITING_REAL_REVISION_INPUT_FILES'])
    except (ValueError,TypeError,KeyError,OSError) as error:
        code=str(error)
        if not re.fullmatch('[A-Z][A-Z0-9_]+',code):code='DAILY_REVISION_PREFLIGHT_INVALID'
        return dict(base,status='BLOCKED',reason_codes=[code])
