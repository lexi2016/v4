"""stage_center.formula_margin_shadow: shadow_build (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_shadow_body(_v4_scope, /, payload, *, require_full_pool, require_artifacts, allow_invocation_verified):
    """Validate one input and build the frozen B/F artifacts in memory.

    No output is written by this function.  The returned object is suitable
    for ``freeze_snapshot`` and is also useful for a small deterministic
    canary test.
    """

    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("input snapshot must be an object")
    metadata = _v4_global(_v4_scope, '_metadata_from_input')(payload)
    if metadata.get("experiment_id", _v4_global(_v4_scope, 'EXPERIMENT_ID')) != _v4_global(_v4_scope, 'EXPERIMENT_ID'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("experiment_id mismatch")
    admission_mode = _v4_global(_v4_scope, '_admission_mode')(metadata)
    if admission_mode == _v4_global(_v4_scope, 'REAL_AUTHORITY'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("REAL_AUTHORITY_BUILD_BLOCKED_OWNER_CONTRACT_PENDING")
    metadata = {**_v4_global(_v4_scope, 'dict')(metadata), "admission_mode": admission_mode}
    trade_date, stage_id, cutoff_iso, cutoff = _v4_global(_v4_scope, '_stage_contract')(metadata)
    if metadata.get("observation_mode") not in ("FORWARD_NATURAL", "FORWARD_SHADOW"):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("observation_mode must be FORWARD_NATURAL/FORWARD_SHADOW")
    _v4_global(_v4_scope, '_reject_archive_or_proxy_metadata')(metadata)
    if _v4_global(_v4_scope, 'isinstance')(metadata.get("capture_time_receipt"), _v4_global(_v4_scope, 'Mapping')):
        _v4_global(_v4_scope, '_validate_capture_time_receipt')(
            metadata["capture_time_receipt"],
            metadata,
            require_runtime=True,
            allow_invocation_verified=allow_invocation_verified,
            selector_result=(
                metadata.get("selector_result")
                if _v4_global(_v4_scope, 'isinstance')(metadata.get("selector_result"), _v4_global(_v4_scope, 'Mapping'))
                else None
            ),
        )
    captured_at = _v4_global(_v4_scope, '_parse_timestamp')(metadata.get("captured_at"), trade_date, "captured_at")
    if captured_at > cutoff:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("captured_at is after the stage cutoff")
    binding = _v4_global(_v4_scope, '_source_binding')(metadata, require_artifacts=require_artifacts)
    production_source_artifact = _v4_global(_v4_scope, '_source_artifact_check')(
        metadata,
        expected_sha=binding["input_sha256"],
        required=require_artifacts,
    )
    formula = _v4_global(_v4_scope, '_formula_provenance')(
        metadata,
        trade_date,
        cutoff,
        require_artifact=require_artifacts,
    )
    rows = payload.get("rows")
    if rows is None:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("input snapshot rows are missing")
    normalised = _v4_global(_v4_scope, '_validate_rows')(rows, cutoff, require_full_pool=require_full_pool)
    _v4_global(_v4_scope, '_verify_source_artifact_rows')(production_source_artifact, normalised)
    _v4_global(_v4_scope, '_verify_formula_artifact_rows')(formula.get("artifact"), normalised)
    declared_pool_size = metadata.get("d1_pool_size")
    if declared_pool_size not in (None, ""):
        if _v4_global(_v4_scope, 'isinstance')(declared_pool_size, _v4_global(_v4_scope, 'bool')) or _v4_global(_v4_scope, 'int')(declared_pool_size) != _v4_global(_v4_scope, 'len')(normalised):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("d1_pool_size does not match the recorded member rows")
    eligible = [row for row in normalised if row["eligible"]]
    original_order = _v4_global(_v4_scope, 'sorted')(eligible, key=lambda item: _v4_global(_v4_scope, 'int')(item["production_rank"]))
    candidate_order, candidate_details = _v4_global(_v4_scope, '_derive_candidate')(eligible)
    capture_receipt = metadata.get("capture_time_receipt")
    invocation_verified = _v4_global(_v4_scope, 'isinstance')(capture_receipt, _v4_global(_v4_scope, 'Mapping')) and capture_receipt.get("invocation_verified") is True
    capture_origin = _v4_global(_v4_scope, 'CAPTURE_ORIGIN_SELECTOR') if invocation_verified else _v4_global(_v4_scope, 'CAPTURE_ORIGIN_DIRECT')
    invocation_status = _v4_global(_v4_scope, 'INVOCATION_STATUS_VERIFIED') if invocation_verified else _v4_global(_v4_scope, 'INVOCATION_STATUS_DIRECT')
    provenance_flags = {
        "capture_origin": capture_origin,
        "invocation_verified": invocation_verified,
        "invocation_status": invocation_status,
        "counts_as_forward_day": False,
        "natural_sample_count": 0,
    }
    # The B arm is always the original production order.  It must be taken
    # before the formula-only reorder; using candidate_order here would make
    # the baseline silently inherit the F arm.
    candidate_by_code = {_v4_global(_v4_scope, 'str')(row["security_id"]): row for row in candidate_order}
    baseline = [candidate_by_code[_v4_global(_v4_scope, 'str')(row["security_id"])] for row in original_order[:_v4_global(_v4_scope, 'TOP_K')]]
    # The candidate order is allowed to differ only inside the frozen class.
    # This explicit check makes a future code change fail closed.
    changed = [
        (_v4_global(_v4_scope, 'str')(left["security_id"]), _v4_global(_v4_scope, 'str')(right["security_id"]))
        for left, right in _v4_global(_v4_scope, 'zip')(_v4_global(_v4_scope, 'sorted')(eligible, key=lambda x: _v4_global(_v4_scope, 'int')(x["production_rank"])), candidate_order)
        if _v4_global(_v4_scope, 'str')(left["security_id"]) != _v4_global(_v4_scope, 'str')(right["security_id"])
    ]
    if _v4_global(_v4_scope, 'any')(
        _v4_global(_v4_scope, '_equivalence_class')(_v4_global(_v4_scope, 'next')(row for row in eligible if _v4_global(_v4_scope, 'str')(row["security_id"]) == left))
        != _v4_global(_v4_scope, '_equivalence_class')(_v4_global(_v4_scope, 'next')(row for row in candidate_order if _v4_global(_v4_scope, 'str')(row["security_id"]) == right))
        for left, right in changed
    ):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("candidate attempted a cross-equivalence-class reorder")
    full_rows = [_v4_global(_v4_scope, 'dict')(row) for row in candidate_order]
    baseline_payload = {
        "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
        "experiment_id": _v4_global(_v4_scope, 'EXPERIMENT_ID'),
        "admission_mode": admission_mode,
        "trade_date": trade_date,
        "stage": stage_id,
        "cutoff_ts": cutoff_iso,
        "market": _v4_global(_v4_scope, 'MARKET'),
        "arm": "B",
        "codes": [_v4_global(_v4_scope, 'str')(row["security_id"]) for row in baseline],
        "rows": [_v4_global(_v4_scope, 'dict')(row) for row in baseline],
        **provenance_flags,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    candidate_payload = {
        "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
        "experiment_id": _v4_global(_v4_scope, 'EXPERIMENT_ID'),
        "admission_mode": admission_mode,
        "trade_date": trade_date,
        "stage": stage_id,
        "cutoff_ts": cutoff_iso,
        "market": _v4_global(_v4_scope, 'MARKET'),
        "arm": "F",
        "codes": [_v4_global(_v4_scope, 'str')(row["security_id"]) for row in candidate_order[:_v4_global(_v4_scope, 'TOP_K')]],
        "rows": [_v4_global(_v4_scope, 'dict')(row) for row in candidate_order[:_v4_global(_v4_scope, 'TOP_K')]],
        "selection_rule": _v4_global(_v4_scope, 'RULE_VERSION'),
        "tau": candidate_details["tau"],
        **provenance_flags,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    members_payload = {
        "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
        "experiment_id": _v4_global(_v4_scope, 'EXPERIMENT_ID'),
        "admission_mode": admission_mode,
        "trade_date": trade_date,
        "stage": stage_id,
        "cutoff_ts": cutoff_iso,
        "market": _v4_global(_v4_scope, 'MARKET'),
        "d1_pool_count": _v4_global(_v4_scope, 'len')(full_rows),
        "eligible_count": _v4_global(_v4_scope, 'len')(eligible),
        **provenance_flags,
        "rows": full_rows,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    receipt = {
        "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
        "experiment_id": _v4_global(_v4_scope, 'EXPERIMENT_ID'),
        "admission_mode": admission_mode,
        "trade_date": trade_date,
        "stage": stage_id,
        "cutoff_ts": cutoff_iso,
        "market": _v4_global(_v4_scope, 'MARKET'),
        "rule_version": _v4_global(_v4_scope, 'RULE_VERSION'),
        "comparator_version": _v4_global(_v4_scope, 'COMPARATOR_VERSION'),
        "comparator_key_order": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'COMPARATOR_KEY_NAMES')),
        "pre_score_key_order": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'PRE_SCORE_KEY_NAMES')),
        "production_binding": binding,
        "production_source_artifact": production_source_artifact,
        "formula_provenance": formula,
        **provenance_flags,
        **(
            {"capture_time_receipt": _v4_global(_v4_scope, 'dict')(metadata["capture_time_receipt"])}
            if _v4_global(_v4_scope, 'isinstance')(metadata.get("capture_time_receipt"), _v4_global(_v4_scope, 'Mapping'))
            else {}
        ),
        **(
            {"selector_capture_binding": _v4_global(_v4_scope, 'dict')(metadata["selector_capture_binding"])}
            if _v4_global(_v4_scope, 'isinstance')(metadata.get("selector_capture_binding"), _v4_global(_v4_scope, 'Mapping'))
            else {}
        ),
        "selection": candidate_details,
        "d1_pool_count": _v4_global(_v4_scope, 'len')(full_rows),
        "eligible_count": _v4_global(_v4_scope, 'len')(eligible),
        "artifacts": {
            "members": {"path": "members.json"},
            "baseline": {"path": "baseline_top10.json"},
            "candidate": {"path": "candidate_top10.json"},
        },
        "labels": {"status": "PENDING_AFTER_CUTOFF", "path": "labels/labels.json"},
        "truth_scope": _v4_global(_v4_scope, 'TRUTH_SCOPE'),
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    return {
        "root_metadata": {
            "admission_mode": admission_mode,
            "trade_date": trade_date,
            "stage": stage_id,
            "cutoff_ts": cutoff_iso,
            "market": _v4_global(_v4_scope, 'MARKET'),
            "production_binding": binding,
            "production_source_artifact": production_source_artifact,
            "formula_provenance": formula,
            **provenance_flags,
            **(
                {"selector_result": _v4_global(_v4_scope, 'dict')(metadata["selector_result"])}
                if _v4_global(_v4_scope, 'isinstance')(metadata.get("selector_result"), _v4_global(_v4_scope, 'Mapping'))
                else {}
            ),
            **(
                {"d1_manifest": _v4_global(_v4_scope, 'dict')(metadata["d1_manifest"])}
                if _v4_global(_v4_scope, 'isinstance')(metadata.get("d1_manifest"), _v4_global(_v4_scope, 'Mapping'))
                else {}
            ),
            **(
                {"formula_manifest_binding": _v4_global(_v4_scope, 'dict')(metadata["formula_manifest_binding"])}
                if _v4_global(_v4_scope, 'isinstance')(metadata.get("formula_manifest_binding"), _v4_global(_v4_scope, 'Mapping'))
                else {}
            ),
            **(
                {"capture_time_receipt": _v4_global(_v4_scope, 'dict')(metadata["capture_time_receipt"])}
                if _v4_global(_v4_scope, 'isinstance')(metadata.get("capture_time_receipt"), _v4_global(_v4_scope, 'Mapping'))
                else {}
            ),
        },
        "members": members_payload,
        "baseline": baseline_payload,
        "candidate": candidate_payload,
        "receipt": receipt,
    }


def _preflight_input_body(_v4_scope, /, payload_or_path):
    """Check whether an input is eligible for a forward manual observation.

    Existing archives, fixtures, replays, and CF/proxy inputs are deliberately
    rejected.  This is an engineering preflight and never counts as a natural
    canary day.
    """

    payload = _v4_global(_v4_scope, '_read_json')(payload_or_path) if _v4_global(_v4_scope, 'isinstance')(payload_or_path, (_v4_global(_v4_scope, 'Path'), _v4_global(_v4_scope, 'str'))) else payload_or_path
    reasons: list[str] = []
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        return {"status": "REJECTED", "forward_eligible": False, "reasons": ["INPUT_NOT_OBJECT"], "natural_sample_count": 0}
    metadata = _v4_global(_v4_scope, '_metadata_from_input')(payload)
    try:
        admission_mode = _v4_global(_v4_scope, '_admission_mode')(metadata, default=None)
    except _v4_global(_v4_scope, 'ShadowInvalid') as error:
        admission_mode = None
        reasons.append(_v4_global(_v4_scope, 'str')(error))
    mode = _v4_global(_v4_scope, 'str')(metadata.get("observation_mode") or "").upper()
    source_mode = _v4_global(_v4_scope, 'str')(metadata.get("source_mode") or metadata.get("source_kind") or "").upper()
    if mode not in {"FORWARD_NATURAL", "FORWARD_SHADOW"}:
        reasons.append("FORWARD_OBSERVATION_MODE_REQUIRED")
    if _v4_global(_v4_scope, 'any')(token in source_mode for token in ("LEGACY", "ARCHIVE", "HISTORICAL", "FIXTURE", "REPLAY", "CF", "PROXY")):
        reasons.append("LEGACY_OR_PROXY_SOURCE_REJECTED")
    try:
        _v4_global(_v4_scope, '_reject_archive_or_proxy_metadata')(metadata)
    except _v4_global(_v4_scope, 'ShadowInvalid'):
        if "LEGACY_OR_PROXY_SOURCE_REJECTED" not in reasons:
            reasons.append("LEGACY_OR_PROXY_SOURCE_REJECTED")
    try:
        _v4_global(_v4_scope, '_stage_contract')(metadata)
    except _v4_global(_v4_scope, 'ShadowInvalid') as error:
        reasons.append(_v4_global(_v4_scope, 'str')(error))
    try:
        _v4_global(_v4_scope, '_source_binding')(metadata)
    except _v4_global(_v4_scope, 'ShadowInvalid') as error:
        reasons.append(_v4_global(_v4_scope, 'str')(error))
    if not _v4_global(_v4_scope, 'isinstance')(metadata.get("rows", payload.get("rows")), _v4_global(_v4_scope, 'list')):
        reasons.append("ROWS_MISSING")
    # A preflight never claims that a historical date is natural merely because
    # the file is readable.  The producer must mark the observation explicitly.
    captured = metadata.get("captured_at")
    if not captured:
        reasons.append("CAPTURED_AT_REQUIRED")
    else:
        try:
            trade_date = _v4_global(_v4_scope, '_exact_date')(metadata.get("trade_date"), "trade_date")
            cutoff = _v4_global(_v4_scope, '_parse_timestamp')(metadata.get("cutoff_ts"), trade_date, "cutoff_ts")
            captured_at = _v4_global(_v4_scope, '_parse_timestamp')(captured, trade_date, "captured_at")
            if captured_at > cutoff:
                reasons.append("CAPTURED_AT_AFTER_CUTOFF")
        except _v4_global(_v4_scope, 'ShadowInvalid') as error:
            reasons.append(_v4_global(_v4_scope, 'str')(error))
    # Preflight must exercise the same full-pool and row-shape gates as the
    # persistent freeze path.  A readable JSON file with an empty or short
    # rows list is therefore never reported as forward-eligible.
    try:
        build_payload = _v4_global(_v4_scope, 'dict')(payload)
        if _v4_global(_v4_scope, 'isinstance')(payload.get("metadata"), _v4_global(_v4_scope, 'Mapping')):
            build_payload["metadata"] = _v4_global(_v4_scope, 'dict')(payload["metadata"])
        _v4_global(_v4_scope, 'build_shadow')(build_payload, require_full_pool=True, require_artifacts=True)
    except _v4_global(_v4_scope, 'ShadowInvalid') as error:
        reasons.append(f"INPUT_VALIDATION:{error}")
    return {
        "status": (
            "ENGINEERING_ONLY"
            if not reasons and admission_mode == _v4_global(_v4_scope, 'ENGINEERING_FIXTURE')
            else ("PASS" if not reasons else "REJECTED")
        ),
        "forward_eligible": not reasons and admission_mode == _v4_global(_v4_scope, 'REAL_AUTHORITY'),
        "admission_mode": admission_mode,
        "reasons": reasons,
        "natural_sample_count": 0,
        "counts_as_forward_day": False,
        "hit_ready": False,
        "observation_mode": mode,
        "source_mode": source_mode,
    }
