from __future__ import annotations
from .validation import batch
from ..contracts import InputBatch, Lane


def load_inputs(context, adapters) -> dict[Lane, InputBatch]:
    """One unavailable owner cannot erase the other owners' valid inputs."""
    if not hasattr(context, "target_date"):
        from ..contracts import RunContext
        context = RunContext.model_validate(context)
    if not hasattr(adapters, "load"):
        from .authority import load_inputs as injected_load
        return {Lane(k): InputBatch.model_validate(v) for k,v in injected_load(context, adapters).items()}
    result = {}
    for lane in Lane:
        try:
            value = adapters.load(lane, context)
            value = InputBatch.model_validate(value) if isinstance(value, dict) else value
            if value.context != context or value.lane != lane:
                raise ValueError("INPUT_CONTEXT_MISMATCH")
            if value.input_sha256 != batch(context, lane, value.records, value.evidence_refs,
                                          value.scope_description, value.coverage, value.gaps,
                                          value.universe_ref).input_sha256:
                raise ValueError("INPUT_SHA_MISMATCH")
            result[lane] = value
        except (ValueError, OSError, KeyError, TypeError) as exc:
            result[lane] = batch(context, lane, [], [], "Owner unavailable", gaps=[
                str(exc) if str(exc).isupper() and len(str(exc)) <= 180 else "INPUT_OWNER_READ_FAILED"])
    article_id=context.scope_refs.get("canary_article_id")
    if article_id:
        original=result[Lane.ANNOUNCEMENT]
        selected=[r for r in original.records if r.get("article_id")==article_id or r.get("event_id")==article_id or r.get("original_event_id")==article_id]
        if len(selected)!=1:
            raise ValueError("CANARY_ARTICLE_NOT_UNIQUE_OR_FOUND")
        context.scope_refs["ANNOUNCEMENT"]["article_ids"]=[selected[0]["article_id"]]
        from ..contracts import Coverage
        result[Lane.ANNOUNCEMENT]=batch(context,Lane.ANNOUNCEMENT,selected,original.evidence_refs,
            "Explicit single-article canary from pinned observed corpus",Coverage(scope_count=1,observed_count=1),
            [],original.universe_ref)
    return result
