"""stage_center.selection: selection_envelope (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __selection_envelope_body(_v4_scope, /, *, trade_date, stage_id, market, raw_artifact_sha256, source_status, input_rows, rows, requested_rows, missing_symbols, cannot_confirm, source_evidence, algorithm_sha256):
    _v4_global(_v4_scope, '_validate_date')(trade_date)
    _v4_global(_v4_scope, '_validate_market')(stage_id, market)
    _v4_global(_v4_scope, '_validate_sha')(raw_artifact_sha256, "raw_artifact_sha256")
    if algorithm_sha256 not in _v4_global(_v4_scope, 'ALGORITHM_SHA_ALLOWLIST'):
        raise _v4_global(_v4_scope, 'SelectionError')("selection algorithm binding mismatch")
    if source_status not in _v4_global(_v4_scope, 'SELECTION_STATUSES'):
        source_status = "CANNOT_CONFIRM" if source_status in {"READ_FAILED", "CANNOT_CONFIRM"} else "READY"
    output_rows = [_v4_global(_v4_scope, 'dict')(row) for row in rows]
    cannot = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, 'str')(item) for item in cannot_confirm if _v4_global(_v4_scope, 'str')(item)))
    missing = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, 'str')(item) for item in missing_symbols if _v4_global(_v4_scope, 'str')(item)))
    requested = input_rows if requested_rows is None else _v4_global(_v4_scope, 'int')(requested_rows)
    if requested < 0:
        raise _v4_global(_v4_scope, 'SelectionError')("requested_rows must be non-negative")
    if not output_rows:
        status = "CANNOT_CONFIRM" if cannot or source_status in {"CANNOT_CONFIRM", "PARTIAL_WITH_ROWS"} else "READY_EMPTY"
    elif source_status == "CANNOT_CONFIRM" or cannot:
        status = "PARTIAL_WITH_ROWS"
    elif source_status == "PARTIAL_WITH_ROWS":
        status = "PARTIAL_WITH_ROWS"
    elif source_status == "READY" and requested > input_rows:
        # A collector that returns fewer rows than its declared request is
        # partial even when it did not provide an explicit missing-symbol
        # list. A Top-10 cap does not trigger this branch because ``input_rows``
        # remains the full exact-date acquisition count.
        status = "PARTIAL_WITH_ROWS"
    elif source_status == "READY_EMPTY":
        status = "CANNOT_CONFIRM"
    else:
        status = "READY"
    coverage = _v4_global(_v4_scope, 'round')(_v4_global(_v4_scope, 'min')(_v4_global(_v4_scope, 'len')(output_rows) / requested, 1.0), 6) if requested else (1.0 if not output_rows else 0.0)
    artifact_id, run_id = _v4_global(_v4_scope, '_selection_identity_ids')(
        trade_date,
        stage_id,
        market,
        raw_artifact_sha256,
        algorithm_sha256,
        output_rows,
    )
    envelope = {
        "schema_version": _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSION'),
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": market,
        "artifact_id": artifact_id,
        "run_id": run_id,
        "algorithm_id": _v4_global(_v4_scope, 'SELECTION_ALGORITHM_ID'),
        "algorithm_sha256": algorithm_sha256,
        "raw_artifact_sha256": raw_artifact_sha256,
        "source_status": source_status,
        "selection_status": status,
        "requested_rows": requested,
        "source_rows": input_rows,
        "selected_rows": _v4_global(_v4_scope, 'len')(output_rows),
        "coverage_ratio": coverage,
        "missing_symbols": missing,
        "rows": output_rows,
        "source_evidence": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, 'str')(item) for item in source_evidence if _v4_global(_v4_scope, 'str')(item))),
        "cannot_confirm": cannot,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    return envelope


def __cap_recommendations_body(_v4_scope, /, rows, *, preserve_legacy):
    """Return the immutable legacy V3 recommendation slice.

    Ranking is completed by each selector before this helper is called. The
    helper therefore only applies the public Top-10 boundary and re-numbers
    the exposed slice; it never re-sorts or manufactures rows. Python's list
    order remains the authoritative tie-break order.
    """
    capped = [_v4_global(_v4_scope, 'dict')(row) for row in (rows if preserve_legacy else rows[:_v4_global(_v4_scope, 'STAGE_RECOMMENDATION_LIMIT')])]
    for rank, row in _v4_global(_v4_scope, 'enumerate')(capped, start=1):
        row["rank"] = rank
    return capped
