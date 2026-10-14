# Existing-engine announcement queue candidate

Status: `CANDIDATE_ONLY; NOT_INTEGRATED; INFERENCE_NOT_RUN; QUALITY_NOT_ASSESSED`.

`announcement_queue.py` is a pure importable persistence/scheduling module. It is not a producer, service, endpoint, CLI, model adapter, web-search broker, or second frontend. The existing V4 announcement engine remains responsible for source selection, model/API calls, timeout enforcement, the current schema/source/quote validator, and any semantic or research acceptance. This module only accepts already-collected full article records, serializes work by model, stores returned raw bytes before parsing, and exposes progress snapshots.

## Input and identity

Call `enqueue()` once per complete article or `enqueue_many()` with the complete current set. Each mapping uses these fields:

```text
date, market, article_id, source_sha256, body_sha256,
prompt_sha256, model_id, configuration_sha256, rules,
role or stage, article_body
```

The four SHA fields are lowercase SHA-256 hex. `body_sha256` is recomputed over the exact UTF-8 `article_body`, including whitespace. The stable idempotency key hashes the canonical identity fields: date, market, article ID, source/body/prompt/configuration SHA, model ID, rules, role, and stage. A changed identity gets a new queue item. An exact identity/payload already present is deduplicated, including across queue IDs in the same state root; conflicting payload or queue-policy bytes raise `IdempotencyConflict`.

If required identity/material is missing or invalid, the key additionally binds the complete normalized payload SHA so two different malformed source rows remain separate `MISSING_MATERIAL` records instead of colliding on null identity fields.

`max_body_bytes` is an optional admission threshold measured against the complete UTF-8 body. Oversize records are retained intact with status `OVERSIZE` and are not submitted. Ready records are ordered shortest-body-first by UTF-8 byte length. No body is truncated. Missing or invalid required material remains visible as `MISSING_MATERIAL`; it is never converted to a zero result or omitted silently.

## Existing-engine integration seam

The caller chooses an app-owned private state directory and uses the same path for every queue/process sharing one model. This is the scope of the `fcntl` model lock; separate state roots do not coordinate. The callback must use the existing supported engine path with one article and return its unparsed response body. It must enforce its own finite transport/request timeout and raise `TimeoutError` or `ExecutorFailure`; arbitrary callbacks cannot be safely cancelled by this module. If transport has partial response bytes, place them in `ExecutorFailure.raw_response` so they are persisted before the failure is recorded.

```python
from pathlib import Path

from announcement_queue import (
    ExecutorFailure,
    SerialAnnouncementQueue,
    ValidationRejected,
)

queue = SerialAnnouncementQueue(
    state_root=Path(app_state) / "announcement-engine-queue",
    queue_id=existing_run_id,
    model_id=selected_model_id,
    max_attempts=2,
    max_body_bytes=None,  # or a frozen queue policy; this never truncates
)
queue.enqueue_many(complete_article_records)

def execute_one(job):
    # Adapter calls the existing engine for job.payload['article_body'] exactly.
    # Return the raw response body as str/bytes; do not parse or discard it here.
    return existing_engine_call_with_bounded_timeout(job)

def validate_one(job, parsed_json):
    # Delegate to the existing V4 validator; reject with a stable code on failure.
    try:
        return existing_v4_validator(job, parsed_json)
    except ExistingValidationError as exc:
        raise ValidationRejected(str(exc), code="V4_VALIDATOR_REJECTED") from exc

queue.run_pending(execute_one, validate_one)
snapshot = queue.snapshot()  # publish counts/statuses through the existing V4 page/API owner

retry_keys = queue.retry_failed()  # returns only retryable failures
queue.run_pending(execute_one, validate_one, idempotency_keys=retry_keys)
```

Before integration, the owner must map the actual V4 fields to this input contract and prove the callback calls the supported per-article engine path. No network/broker endpoint is guessed or added here. If the supported engine adapter or owner boundary requires edits outside this directory, stop and return the owner/API gap rather than widening this candidate.

## Persistence and recovery

The state root contains `queue-state.json`, a shared model/state lock directory, and one private item directory per idempotency key. The exact input body, raw response for each attempt, and accepted validator output are separate files. New directories are mode `0700`; state, lock, input, raw, and validated files are mode `0600`. State updates use atomic replace and fsync. The state root must be writable and backed by the same durable local filesystem for all workers in the lock domain.

Every attempt records start, raw persistence, failure/rejection or completion, and elapsed seconds. Parsing and validation happen only after the raw response file is durably written. Invalid JSON, timeout, transport exception, validator rejection, or input read failure becomes a persisted `FAILED` attempt and does not stop the next pending article. `retry_failed()` schedules only failures below each item's frozen `max_attempts`; successful identities are never rerun. Once the model lock is acquired, a stale `RUNNING` record is marked `INTERRUPTED` and returns to `PENDING` only if its attempt bound permits. A raw response found from that interrupted attempt remains recorded, but is never assumed to be validated or successful.

`snapshot()` returns queue/model identifiers, item status counts, per-item identity/attempt/error/artifact receipts, `unassessed_count`, `not_selected_count: 0`, and `conservation_ok`. Within the enqueued identity set, every unique item is exactly one of `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `OVERSIZE`, or `MISSING_MATERIAL`; these status counts sum to `total`. A `PENDING`/`RUNNING` item is unassessed, not “not selected.” The owner must compare its complete upstream input count and identity set with the accepted queue set; a snapshot by itself cannot prove that upstream omitted no rows.

## Acceptance boundary

Fault-injection tests exercise timeout, transport failure with partial raw bytes, invalid JSON, quote-validator rejection, continuing to the next item, explicit bounded failure retry, success idempotency, configuration-identity change, preserved oversize body/counts, stale `RUNNING` recovery, and two processes using different queue IDs with one model/state root. These prove queue mechanics only. No production adapter, UI/API integration, real inference, source completeness, validator semantics, quality acceptance, or research result has been exercised. The queue is research-only and does not change model policy, BUY gates, or trading permissions.

Integration gaps remain `CANNOT_CONFIRM`: whether the current canonical V4 engine exposes a per-article raw-response callback and current validator in a form that can satisfy this seam; whether its caller can enforce a finite transport timeout; and which app-owned durable state path every same-model worker can share. Resolve these at the existing owner boundary before integration. This batch deliberately does not inspect or modify that owner.
