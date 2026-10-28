"""stage_center.formula_margin_shadow: capture_price_receipt (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __capture_time_receipt_payload_body(_v4_scope, /, metadata, *, selector_result, selector_started_at, selector_finished_at):
    """Build a v2 receipt from the actual post-selector return envelope."""

    mode = _v4_global(_v4_scope, '_admission_mode')(metadata, default=None)
    trade_date, stage_id, cutoff_iso, _ = _v4_global(_v4_scope, '_stage_contract')(metadata)
    started = _v4_global(_v4_scope, '_validate_runtime_capture_timestamp')(selector_started_at, trade_date, stage_id)
    finished = _v4_global(_v4_scope, '_validate_runtime_capture_timestamp')(selector_finished_at, trade_date, stage_id)
    if finished < started:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector runtime timestamps are out of order")
    binding = _v4_global(_v4_scope, '_source_binding')(metadata, require_artifacts=True)
    source_artifact = _v4_global(_v4_scope, '_source_artifact_check')(metadata, expected_sha=binding["input_sha256"], required=True)
    actual = _v4_global(_v4_scope, '_validate_selector_return')(
        selector_result,
        metadata,
        expected_raw_artifact_sha=_v4_global(_v4_scope, 'str')(source_artifact["sha256"]),
    )
    d1_binding = _v4_global(_v4_scope, '_verified_manifest_binding')(metadata.get("d1_manifest"), "d1_manifest", require_artifact=True)
    formula_binding = metadata.get("formula_manifest_binding")
    if not _v4_global(_v4_scope, 'isinstance')(formula_binding, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest binding is required for capture_time_receipt")
    formula_state = _v4_global(_v4_scope, '_checked_file_artifact')(
        formula_binding.get("artifact"),
        "formula state artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(formula_binding.get("input_sha256") or "").lower(),
        required=True,
    )
    formula_rule = _v4_global(_v4_scope, '_checked_file_artifact')(
        formula_binding.get("rule_artifact"),
        "formula rule artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(formula_binding.get("rule_sha256") or "").lower(),
        required=True,
    )
    raw_artifact_sha = _v4_global(_v4_scope, 'str')(metadata.get("raw_artifact_sha256") or source_artifact["sha256"]).lower()
    if raw_artifact_sha != _v4_global(_v4_scope, 'str')(source_artifact["sha256"]).lower() or actual["raw_artifact_sha256"] != raw_artifact_sha:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt raw/source artifact binding mismatch")
    raw_input_sha = _v4_global(_v4_scope, 'str')(metadata.get("raw_input_sha256") or "").lower()
    if not _v4_global(_v4_scope, '_is_sha')(raw_input_sha):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt raw input SHA is required")
    return {
        "schema_version": _v4_global(_v4_scope, 'CAPTURE_TIME_RECEIPT_SCHEMA_VERSION'),
        "source": _v4_global(_v4_scope, 'CAPTURE_TIME_SOURCE'),
        "experiment_id": _v4_global(_v4_scope, 'EXPERIMENT_ID'),
        "admission_mode": mode,
        "invocation_verified": True,
        "invocation_verification_basis": _v4_global(_v4_scope, 'INVOCATION_VERIFICATION_BASIS'),
        "capture_origin": _v4_global(_v4_scope, 'CAPTURE_ORIGIN_SELECTOR'),
        "invocation_status": _v4_global(_v4_scope, 'INVOCATION_STATUS_VERIFIED'),
        "counts_as_forward_day": False,
        "natural_sample_count": 0,
        "trade_date": trade_date,
        "stage": stage_id,
        "cutoff_ts": cutoff_iso,
        "captured_at": finished.isoformat(),
        "selector_started_at": started.isoformat(),
        "selector_finished_at": finished.isoformat(),
        "production_run_id": actual["run_id"],
        "production_artifact_id": actual["artifact_id"],
        "production_algorithm_sha256": actual["algorithm_sha256"],
        "selector_result_sha256": actual["sha256"],
        "shadow_invocation_id": f"shadow-invocation-{_v4_global(_v4_scope, 'uuid').uuid4().hex}",
        "raw_input_sha256": raw_input_sha,
        "raw_artifact_sha256": raw_artifact_sha,
        "source_artifact_sha256": _v4_global(_v4_scope, 'str')(source_artifact["sha256"]).lower(),
        "production_rule_sha256": binding["rule_sha256"],
        "d1_manifest_sha256": _v4_global(_v4_scope, 'str')(d1_binding["sha256"]).lower(),
        "formula_input_sha256": _v4_global(_v4_scope, 'str')(formula_binding.get("input_sha256") or "").lower(),
        "formula_state_artifact_sha256": _v4_global(_v4_scope, 'str')(formula_state["sha256"]).lower(),
        "formula_rule_sha256": _v4_global(_v4_scope, 'str')(formula_binding.get("rule_sha256") or "").lower(),
        "formula_rule_artifact_sha256": _v4_global(_v4_scope, 'str')(formula_rule["sha256"]).lower(),
        "shadow_rule_version": _v4_global(_v4_scope, 'RULE_VERSION'),
        "comparator_version": _v4_global(_v4_scope, 'COMPARATOR_VERSION'),
        "selector_invocation": "stage_center.selection.select_hk_four_lane",
        "selector_invocation_status": "COMPLETED",
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }


def __validate_capture_time_receipt_body(_v4_scope, /, receipt, metadata, *, require_runtime, allow_invocation_verified, selector_result):
    """Validate a v2 receipt and keep direct freeze fail-closed."""

    if not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt must be an object")
    if not allow_invocation_verified and (
        receipt.get("invocation_verified") is True
        or receipt.get("selector_invocation_status") == "COMPLETED"
    ):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("INVOCATION_VERIFIED_RECEIPT_REQUIRES_SELECTOR_CAPTURE")
    if receipt.get("schema_version") != _v4_global(_v4_scope, 'CAPTURE_TIME_RECEIPT_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt schema mismatch")
    if receipt.get("source") != _v4_global(_v4_scope, 'CAPTURE_TIME_SOURCE'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt source mismatch")
    if receipt.get("experiment_id") != _v4_global(_v4_scope, 'EXPERIMENT_ID'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt experiment mismatch")
    mode = _v4_global(_v4_scope, '_admission_mode')(receipt, default=None)
    metadata_mode = _v4_global(_v4_scope, '_admission_mode')(metadata, default=None)
    if mode != metadata_mode:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt admission_mode mismatch")
    verified = receipt.get("invocation_verified") is True
    if verified:
        if not allow_invocation_verified:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("INVOCATION_VERIFIED_RECEIPT_REQUIRES_SELECTOR_CAPTURE")
        if receipt.get("invocation_verification_basis") != _v4_global(_v4_scope, 'INVOCATION_VERIFICATION_BASIS'):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt verification basis mismatch")
        if receipt.get("capture_origin") != _v4_global(_v4_scope, 'CAPTURE_ORIGIN_SELECTOR') or receipt.get("invocation_status") != _v4_global(_v4_scope, 'INVOCATION_STATUS_VERIFIED'):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt invocation status mismatch")
    else:
        if receipt.get("capture_origin") != _v4_global(_v4_scope, 'CAPTURE_ORIGIN_DIRECT') or receipt.get("invocation_status") != _v4_global(_v4_scope, 'INVOCATION_STATUS_DIRECT'):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("unverified capture_time_receipt origin/status mismatch")
        if receipt.get("counts_as_forward_day") is not False or receipt.get("natural_sample_count") != 0:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("unverified capture_time_receipt natural flags changed")
    trade_date, stage_id, cutoff_iso, _ = _v4_global(_v4_scope, '_stage_contract')(metadata)
    if _v4_global(_v4_scope, 'str')(receipt.get("trade_date") or "").replace("-", "") != trade_date:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt trade_date mismatch")
    if receipt.get("stage") != stage_id or _v4_global(_v4_scope, 'str')(receipt.get("cutoff_ts")) != cutoff_iso:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt stage/cutoff mismatch")
    captured_at = _v4_global(_v4_scope, '_parse_timestamp')(receipt.get("captured_at"), trade_date, "capture_time_receipt.captured_at")
    if require_runtime:
        _v4_global(_v4_scope, '_validate_runtime_capture_timestamp')(captured_at, trade_date, stage_id)
    if verified:
        started = _v4_global(_v4_scope, '_parse_timestamp')(receipt.get("selector_started_at"), trade_date, "selector_started_at")
        finished = _v4_global(_v4_scope, '_parse_timestamp')(receipt.get("selector_finished_at"), trade_date, "selector_finished_at")
        _v4_global(_v4_scope, '_validate_runtime_capture_timestamp')(started, trade_date, stage_id)
        _v4_global(_v4_scope, '_validate_runtime_capture_timestamp')(finished, trade_date, stage_id)
        if finished < started or finished != captured_at:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt runtime timestamps mismatch")
    binding = _v4_global(_v4_scope, '_source_binding')(metadata, require_artifacts=True)
    source_artifact = _v4_global(_v4_scope, '_source_artifact_check')(metadata, expected_sha=binding["input_sha256"], required=True)
    expected = {
        "raw_artifact_sha256": _v4_global(_v4_scope, 'str')(source_artifact["sha256"]).lower(),
        "source_artifact_sha256": _v4_global(_v4_scope, 'str')(source_artifact["sha256"]).lower(),
        "production_rule_sha256": binding["rule_sha256"],
        "shadow_rule_version": _v4_global(_v4_scope, 'RULE_VERSION'),
        "comparator_version": _v4_global(_v4_scope, 'COMPARATOR_VERSION'),
        "selector_invocation": "stage_center.selection.select_hk_four_lane",
        "selector_invocation_status": "COMPLETED",
    }
    for key, expected_value in expected.items():
        if _v4_global(_v4_scope, 'str')(receipt.get(key) or "").lower() != _v4_global(_v4_scope, 'str')(expected_value).lower():
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"capture_time_receipt {key} mismatch")
    raw_input_sha = metadata.get("raw_input_sha256")
    if raw_input_sha not in (None, "") and _v4_global(_v4_scope, 'str')(receipt.get("raw_input_sha256") or "").lower() != _v4_global(_v4_scope, 'str')(raw_input_sha).lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt raw input SHA mismatch")
    if verified:
        if not _v4_global(_v4_scope, 'str')(receipt.get("production_run_id") or "").strip() or not _v4_global(_v4_scope, 'str')(receipt.get("production_artifact_id") or "").strip():
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt selector identity is missing")
        if not _v4_global(_v4_scope, '_is_sha')(receipt.get("production_algorithm_sha256")) or not _v4_global(_v4_scope, '_is_sha')(receipt.get("selector_result_sha256")):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt selector SHA is invalid")
        if not _v4_global(_v4_scope, 'str')(receipt.get("shadow_invocation_id") or "").strip():
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt shadow invocation id is missing")
        if selector_result is not None:
            actual = _v4_global(_v4_scope, '_validate_selector_return')(
                selector_result,
                metadata,
                expected_raw_artifact_sha=_v4_global(_v4_scope, 'str')(source_artifact["sha256"]),
            )
            for key, actual_key in (
                ("production_run_id", "run_id"),
                ("production_artifact_id", "artifact_id"),
                ("production_algorithm_sha256", "algorithm_sha256"),
            ):
                if _v4_global(_v4_scope, 'str')(receipt.get(key) or "").lower() != _v4_global(_v4_scope, 'str')(actual[actual_key]).lower():
                    raise _v4_global(_v4_scope, 'ShadowInvalid')(f"capture_time_receipt {key} mismatch")
            if _v4_global(_v4_scope, 'str')(receipt.get("selector_result_sha256") or "").lower() != actual["sha256"]:
                raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt selector_result_sha256 mismatch")
    d1_manifest = _v4_global(_v4_scope, '_verified_manifest_binding')(metadata.get("d1_manifest"), "d1_manifest", require_artifact=True)
    if _v4_global(_v4_scope, 'str')(receipt.get("d1_manifest_sha256") or "").lower() != _v4_global(_v4_scope, 'str')(d1_manifest["sha256"]).lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt D1 manifest SHA mismatch")
    formula_binding = metadata.get("formula_manifest_binding")
    if not _v4_global(_v4_scope, 'isinstance')(formula_binding, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt formula binding is missing")
    formula_state = _v4_global(_v4_scope, '_checked_file_artifact')(
        formula_binding.get("artifact"),
        "formula state artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(formula_binding.get("input_sha256") or "").lower(),
        required=True,
    )
    formula_rule = _v4_global(_v4_scope, '_checked_file_artifact')(
        formula_binding.get("rule_artifact"),
        "formula rule artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(formula_binding.get("rule_sha256") or "").lower(),
        required=True,
    )
    formula_expected = {
        "formula_input_sha256": _v4_global(_v4_scope, 'str')(formula_binding.get("input_sha256") or "").lower(),
        "formula_state_artifact_sha256": _v4_global(_v4_scope, 'str')(formula_state["sha256"]).lower(),
        "formula_rule_sha256": _v4_global(_v4_scope, 'str')(formula_binding.get("rule_sha256") or "").lower(),
        "formula_rule_artifact_sha256": _v4_global(_v4_scope, 'str')(formula_rule["sha256"]).lower(),
    }
    for key, expected_value in formula_expected.items():
        if _v4_global(_v4_scope, 'str')(receipt.get(key) or "").lower() != expected_value:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"capture_time_receipt {key} mismatch")
    for flag, expected_value in _v4_global(_v4_scope, 'SAFETY_FLAGS').items():
        if receipt.get(flag) != expected_value:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt safety flags changed")
    return _v4_global(_v4_scope, 'dict')(receipt)
