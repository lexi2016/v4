"""No-fallback, owner-injected exact-date input loading for A research.

Each adapter is a callable(context) returning a frozen-identity InputBatch.
The caller/B controls owner activation, read-only credentials and calendars.
"""
from __future__ import annotations
from ..engines.common import LANES, plain, digest, valid_sha, validate_context


def _missing(context, lane, code):
    return dict(context=context, lane=lane, universe_ref=None, records=[], evidence_refs=[],
        input_sha256=digest(dict(missing=code,lane=lane,context=context)), scope_description="AUTHORITY_UNAVAILABLE",
        coverage=dict(scope_count=None, observed_count=None, assessed_count=None,
                      unassessed_count=None, gaps=[code]), gaps=[code])


def _load_one(context, lane, loader):
    if loader is None:
        return _missing(context, lane, "AUTHORITY_ADAPTER_NOT_BOUND")
    try:
        batch = plain(loader(context))
    except Exception:
        return _missing(context, lane, "AUTHORITY_ADAPTER_FAILED")
    if not isinstance(batch, dict) or batch.get("context") != context or batch.get("lane") != lane:
        return _missing(context, lane, "AUTHORITY_CONTEXT_MISMATCH")
    if not isinstance(batch.get("records"), list) or not isinstance(batch.get("evidence_refs"), list):
        return _missing(context, lane, "AUTHORITY_BATCH_SHAPE")
    if not isinstance(batch.get("coverage"), dict) or not isinstance(batch.get("gaps"), list):
        return _missing(context, lane, "AUTHORITY_COVERAGE_MISSING")
    if not isinstance(batch.get("universe_ref"), str) or not batch.get("universe_ref") or not batch.get("scope_description"):
        return _missing(context, lane, "AUTHORITY_SCOPE_MISSING")
    if not valid_sha(batch.get("input_sha256")):
        return _missing(context, lane, "AUTHORITY_INPUT_SHA_MISSING")
    # The adapter provides the source identity; hash binds an unmodified batch
    # snapshot for downstream validation, not as a second authority/source.
    if any(not isinstance(e, dict) or not e.get("evidence_id") or not e.get("role") or
           e.get("verification") not in ("VERIFIED","CANNOT_CONFIRM","INVALID") for e in batch["evidence_refs"]):
        return _missing(context, lane, "AUTHORITY_EVIDENCE_SHAPE")
    incomplete=[e for e in batch["evidence_refs"] if e.get("verification")!="VERIFIED" or
                not e.get("owner") or not valid_sha(e.get("sha256"))]
    if incomplete:
        batch=dict(batch,gaps=list(batch["gaps"])+["AUTHORITY_EVIDENCE_UNVERIFIED"])
    return batch


def load_inputs(context, adapters):
    context=plain(context)
    validate_context(context)
    if not isinstance(adapters, dict):
        raise ValueError("MWB_INJECTED_ADAPTERS_REQUIRED")
    if set(adapters) - set(LANES):
        raise ValueError("MWB_UNREGISTERED_ADAPTER")
    return {lane: _load_one(context, lane, adapters.get(lane)) for lane in LANES}
