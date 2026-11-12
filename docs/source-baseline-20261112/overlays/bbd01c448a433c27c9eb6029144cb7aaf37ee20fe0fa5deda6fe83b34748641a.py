"""infrastructure.stage_acquisition_universe_contracts: rows_metadata (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __walk_source_dates_body(_v4_scope, /, value, trade_date, location):
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        for key, nested in value.items():
            folded = _v4_global(_v4_scope, 'str')(key).casefold()
            # These are the date-bearing fields that can turn a post-event or
            # future target into a stage-input row.  Other evidence timestamps
            # are intentionally left as descriptive metadata.
            if (
                folded in {"signal_date", "target_date", "future_signal_date", "future_target_date"}
                or "signal_date" in folded
                or "target_date" in folded
            ):
                _v4_global(_v4_scope, '_parse_date_field')(_v4_global(_v4_scope, 'str')(key), nested, trade_date, location)
            _v4_global(_v4_scope, '_walk_source_dates')(nested, trade_date, f"{location}.{key}")
    elif _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list')):
        for index, nested in _v4_global(_v4_scope, 'enumerate')(value):
            _v4_global(_v4_scope, '_walk_source_dates')(nested, trade_date, f"{location}[{index}]")
    elif _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'tuple')):
        for index, nested in _v4_global(_v4_scope, 'enumerate')(value):
            _v4_global(_v4_scope, '_walk_source_dates')(nested, trade_date, f"{location}[{index}]")


def _validate_stage_row_body(_v4_scope, /, row, pool_id, trade_date, index):
    """Validate and canonicalize one row shared by projection and strict reads."""

    if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} row {index} is invalid"
        )
    if "pool_id" not in row or _v4_global(_v4_scope, 'str')(row.get("pool_id") or "") != pool_id:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} row {index} pool identity is not bound"
        )
    _v4_global(_v4_scope, '_walk_forbidden_outcomes')(row, f"pool[{pool_id}].row[{index}]")
    _v4_global(_v4_scope, '_walk_source_dates')(row, trade_date, f"pool[{pool_id}].row[{index}]")
    if "stage_selection_eligible" in row and row.get("stage_selection_eligible") is not True:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} row {index} cannot be confirmed: "
            "stage_selection_eligible is not true"
        )
    code = _v4_global(_v4_scope, '_canonical_code')(row, pool_id, index)
    normalized = _v4_global(_v4_scope, 'dict')(row)
    normalized["symbol"] = code
    normalized["market"] = "A"
    normalized["pool_id"] = pool_id
    return normalized


def _validate_pool_source_metadata_body(_v4_scope, /, payload, trade_date, pool_id):
    """Validate the common physical-pool identity, dates, flags, and reasons."""

    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} artifact is not an object"
        )
    if _v4_global(_v4_scope, 'str')(payload.get("pool_id") or "") != pool_id:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(f"required A pool {pool_id} identity mismatch")
    if _v4_global(_v4_scope, 'str')(payload.get("trade_date") or "") != trade_date:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(f"required A pool {pool_id} date mismatch")
    if _v4_global(_v4_scope, 'str')(payload.get("market") or "").strip().upper() != "A":
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(f"required A pool {pool_id} market mismatch")
    expected_status, expected_producer, expected_role = _v4_global(_v4_scope, 'a_pool_contract')(pool_id)
    actual_status = payload.get("status")
    if actual_status != expected_status and actual_status not in _v4_global(_v4_scope, '_POOL_DIAGNOSTIC_STATUSES'):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} status is not confirmed"
        )
    # An unavailable lane remains in the six-lane provenance list, but it
    # must not be mistaken for a producer result.  A confirmed lane keeps the
    # exact producer/source-role contract.
    if actual_status == expected_status:
        if payload.get("producer_id") != expected_producer:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"required A pool {pool_id} producer identity mismatch"
            )
        if payload.get("source_role") != expected_role:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"required A pool {pool_id} source role mismatch"
            )
    else:
        if not _v4_global(_v4_scope, 'isinstance')(payload.get("producer_id"), _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, 'isinstance')(
            payload.get("source_role"), _v4_global(_v4_scope, 'str')
        ):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"required A pool {pool_id} diagnostic source identity is invalid"
            )
    source_path = _v4_global(_v4_scope, 'str')(payload.get("source_path") or "").strip()
    source_sha = _v4_global(_v4_scope, 'str')(payload.get("source_sha256") or "").lower()
    if not source_path or _v4_global(_v4_scope, '_SHA256').fullmatch(source_sha) is None:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} artifact identity is incomplete"
        )
    if "target_date" in payload and _v4_global(_v4_scope, 'str')(payload.get("target_date") or "") != trade_date:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} target_date mismatch"
        )
    _v4_global(_v4_scope, '_walk_forbidden_outcomes')(payload, f"pool[{pool_id}]")
    _v4_global(_v4_scope, '_walk_source_dates')(payload, trade_date, f"pool[{pool_id}]")
    for field in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if payload.get(field) is not False:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"required A pool {pool_id} safety boundary mismatch"
            )
    eligibility = payload.get("stage_selection_eligible")
    if "stage_selection_eligible" in payload and eligibility is not True:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} cannot be confirmed: "
            "stage_selection_eligible is not true"
        )
    reasons = payload.get("cannot_confirm")
    if not _v4_global(_v4_scope, 'isinstance')(reasons, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) for item in reasons):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} cannot_confirm is invalid"
        )
    blocking, notes = _v4_global(_v4_scope, 'split_cannot_confirm')(reasons)
    return _v4_global(_v4_scope, 'dict')(payload), blocking, notes


def _validate_pool_rows_body(_v4_scope, /, payload, pool_id, trade_date, *, allow_empty):
    """Validate all rows, including exact pool ownership and PIT/leakage fields."""

    rows = payload.get("rows")
    if not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} rows are invalid"
        )
    if not rows:
        if allow_empty:
            return []
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(f"required A pool {pool_id} has no rows")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = _v4_global(_v4_scope, 'set')()
    for index, raw_row in _v4_global(_v4_scope, 'enumerate')(rows):
        row = _v4_global(_v4_scope, 'validate_stage_row')(raw_row, pool_id, trade_date, index)
        code = row["symbol"]
        if code in seen:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"required A pool {pool_id} contains duplicate code {code}"
            )
        seen.add(code)
        normalized.append(row)
    return normalized
