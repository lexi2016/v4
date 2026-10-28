from __future__ import annotations
from datetime import datetime
import hashlib
import json
import re
from ..contracts import Coverage, EvidenceRef, InputBatch, digest


def raw_sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def owner_digest(value) -> str:
    # Existing producer canonical JSON deliberately has no trailing newline.
    return raw_sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def time_value(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def before(value, cutoff) -> bool:
    parsed, end = time_value(value), time_value(cutoff)
    return parsed is not None and end is not None and parsed <= end


def symbol(value) -> str | None:
    text = str(value or "")
    if re.fullmatch(r"HK\.\d{5}", text):
        return text
    if re.fullmatch(r"\d{1,5}", text):
        return "HK." + text.zfill(5)
    return None


def batch(context, lane, records, refs, scope, coverage=None, gaps=None, universe_ref=None):
    refs = [EvidenceRef.model_validate(r) if isinstance(r, dict) else r for r in refs]
    coverage = coverage or Coverage(observed_count=len(records), gaps=gaps or [])
    value = dict(context=context, lane=lane, records=records, evidence_refs=refs,
                 scope_description=scope, coverage=coverage, gaps=gaps or [], universe_ref=universe_ref)
    # Clock is not an input identity. Actual source availability is part of refs/records.
    identity = dict(target_date=context.target_date, market=context.market,
                    source_sessions=context.source_sessions, scope_refs={k:v for k,v in context.scope_refs.items()
                        if k not in {"run_id", "mwb_run_id", "timing_status", "source_cutoff"}},
                    lane=lane.value, records=records, refs=[r.model_dump(mode="json") for r in refs],
                    scope=scope, coverage=coverage.model_dump(mode="json"), gaps=gaps or [], universe_ref=universe_ref)
    return InputBatch(input_sha256=digest(identity), **value)
