"""domains.preselection_materializer: source_identity (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_shared_v192_projection_body(_v4_scope, /, pool, verification, *, trade_date, signal_date):
    run_id = _v4_global(_v4_scope, 'str')(verification.get("run_id") or "").strip()
    artifact_relative = _v4_global(_v4_scope, 'str')(verification.get("artifact_relative") or "")
    expected_artifact = f"runs/{trade_date}/{_v4_global(_v4_scope, 'SHARED_V192_ROLE')}/{run_id}/artifact.csv"
    if not run_id or artifact_relative != expected_artifact:
        raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 role/run provenance mismatch")
    artifact_sha = _v4_global(_v4_scope, 'str')(verification.get("artifact_sha256") or "").lower()
    if not _v4_global(_v4_scope, 're').fullmatch(r"[0-9a-f]{64}", artifact_sha):
        raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 artifact SHA is invalid")
    try:
        expected_count = _v4_global(_v4_scope, 'int')(verification.get("row_count"))
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
        raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 row count is invalid")
    source_rows = [_v4_global(_v4_scope, 'dict')(row) for row in pool.rows]
    if expected_count != _v4_global(_v4_scope, 'len')(source_rows):
        raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 row count drift")
    seen: set[str] = _v4_global(_v4_scope, 'set')()
    for index, row in _v4_global(_v4_scope, 'enumerate')(source_rows, start=1):
        symbol = _v4_global(_v4_scope, '_a_symbol')(row.get("ts_code"))
        if not symbol or symbol in seen or _v4_global(_v4_scope, '_row_number')(row.get("review_rank_v19"), 0) != index:
            raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 candidate codes/order drift")
        if _v4_global(_v4_scope, 'str')(row.get("signal_date") or "") != signal_date or _v4_global(_v4_scope, 'str')(row.get("target_date") or "") != trade_date:
            raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 row date drift")
        if _v4_global(_v4_scope, 'str')(row.get("rank_usage_boundary") or "") != _v4_global(_v4_scope, 'SHARED_V192_RANK_BOUNDARY'):
            raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 rank boundary drift")
        if _v4_global(_v4_scope, 'str')(row.get("formal_recommendation_allowed") or "").lower() not in {"false", "0"}:
            raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 recommendation gate drift")
        missing = [field for field in _v4_global(_v4_scope, 'SHARED_V192_ENTRY_FIELDS') if row.get(field) in (None, "")]
        if missing:
            raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 contract missing:" + ",".join(missing))
        if _v4_global(_v4_scope, 'str')(row.get("formula_source") or "") != _v4_global(_v4_scope, 'SHARED_V192_FORMULA_SOURCE'):
            raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 formula_source drift")
        if _v4_global(_v4_scope, 'str')(row.get("gold_brick_context") or "") not in {"none", "old_gold_candidate"}:
            raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 gold context drift")
        seen.add(symbol)
    return source_rows
