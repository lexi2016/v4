"""stage_center.formula_margin_shadow: capture_request (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_capture_request_static_body(_v4_scope, /, payload):
    """Validate the raw selector capture contract before invoking production.

    This gate deliberately stops before rank, baseline, or tau calculation.
    It is shared by the capture-specific preflight and the manual capture
    entrypoint so a preflight PASS means only that the selector may be called.
    """

    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture input must be an object")
    metadata = _v4_global(_v4_scope, '_metadata_from_input')(payload)
    if metadata.get("experiment_id", _v4_global(_v4_scope, 'EXPERIMENT_ID')) != _v4_global(_v4_scope, 'EXPERIMENT_ID'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("experiment_id mismatch")
    admission_mode = _v4_global(_v4_scope, '_admission_mode')(metadata, default=None)
    if admission_mode == _v4_global(_v4_scope, 'REAL_AUTHORITY'):
        # The owner has not supplied the exact membership manifest/receipt and
        # same-membership-bound final-close contract in this workspace.  A
        # caller assertion cannot turn a fixture into a real forward source.
        raise _v4_global(_v4_scope, 'ShadowInvalid')("REAL_AUTHORITY_CAPTURE_BLOCKED_OWNER_CONTRACT_PENDING")
    observation_mode = metadata.get("observation_mode")
    if observation_mode not in ("FORWARD_NATURAL", "FORWARD_SHADOW"):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("observation_mode must be FORWARD_NATURAL/FORWARD_SHADOW")
    if admission_mode == _v4_global(_v4_scope, 'ENGINEERING_FIXTURE') and observation_mode == "FORWARD_NATURAL":
        raise _v4_global(_v4_scope, 'ShadowInvalid')("ENGINEERING_FIXTURE_CAPTURE_REQUIRES_FORWARD_SHADOW")
    _v4_global(_v4_scope, '_reject_archive_or_proxy_metadata')(metadata)
    trade_date, stage_id, cutoff_iso, cutoff = _v4_global(_v4_scope, '_stage_contract')(metadata)
    captured_at = _v4_global(_v4_scope, '_parse_timestamp')(metadata.get("captured_at"), trade_date, "captured_at")
    if captured_at > cutoff:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("captured_at is after the stage cutoff")

    raw_rows = payload.get("rows")
    if not _v4_global(_v4_scope, 'isinstance')(raw_rows, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture raw rows are required")
    if _v4_global(_v4_scope, 'len')(raw_rows) != _v4_global(_v4_scope, 'POOL_LIMIT'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"capture requires exactly {_v4_global(_v4_scope, 'POOL_LIMIT')} raw D1 rows; got {_v4_global(_v4_scope, 'len')(raw_rows)}")
    raw_codes: list[str] = []
    for raw in raw_rows:
        if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture raw rows must be objects")
        raw_codes.append(_v4_global(_v4_scope, '_canonical_code')(raw.get("security_id", raw.get("code"))))
    if _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(raw_codes)) != _v4_global(_v4_scope, 'POOL_LIMIT'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("capture raw D1 codes must be unique")
    raw_code_set = _v4_global(_v4_scope, 'set')(raw_codes)

    binding = _v4_global(_v4_scope, '_source_binding')(metadata, require_artifacts=True, require_run_id=False)
    source_artifact = _v4_global(_v4_scope, '_source_artifact_check')(
        metadata,
        expected_sha=binding["input_sha256"],
        required=True,
    )
    raw_artifact_sha = metadata.get("raw_artifact_sha256")
    if not _v4_global(_v4_scope, '_is_sha')(raw_artifact_sha) or _v4_global(_v4_scope, 'str')(raw_artifact_sha).lower() != _v4_global(_v4_scope, 'str')(source_artifact["sha256"]).lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("raw_artifact_sha256 is not bound to the verified source artifact")
    raw_input_sha = _v4_global(_v4_scope, 'sha256_bytes')(_v4_global(_v4_scope, 'canonical_json')(raw_rows))
    declared_raw_input_sha = metadata.get("raw_input_sha256")
    if declared_raw_input_sha not in (None, "") and _v4_global(_v4_scope, 'str')(declared_raw_input_sha).lower() != raw_input_sha:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("raw_input_sha256 does not match selector input rows")
    source_payload = _v4_global(_v4_scope, '_read_json')(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(source_artifact["path"])))
    if not _v4_global(_v4_scope, 'isinstance')(source_payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact must contain an object")
    source_rows = source_payload.get("rows", source_payload.get("members"))
    if not _v4_global(_v4_scope, 'isinstance')(source_rows, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact rows are required")
    if _v4_global(_v4_scope, 'canonical_json')(source_rows) != _v4_global(_v4_scope, 'canonical_json')(raw_rows):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact rows do not canonically match selector raw input")

    d1_manifest = payload.get("d1_manifest", metadata.get("d1_manifest"))
    d1_binding = _v4_global(_v4_scope, '_verified_manifest_binding')(d1_manifest, "d1_manifest", require_artifact=True)
    d1_artifact = d1_binding.get("artifact")
    if not _v4_global(_v4_scope, 'isinstance')(d1_artifact, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("d1_manifest actual artifact is required")
    d1_payload = _v4_global(_v4_scope, '_read_json')(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(d1_artifact["path"])))
    if not _v4_global(_v4_scope, 'isinstance')(d1_payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("d1_manifest artifact must contain an object")
    d1_rows = d1_payload.get("rows", d1_payload.get("members"))
    if not _v4_global(_v4_scope, 'isinstance')(d1_rows, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(d1_rows) != _v4_global(_v4_scope, 'POOL_LIMIT'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("d1_manifest artifact must contain exactly 100 rows")
    d1_codes: list[str] = []
    for row in d1_rows:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("d1_manifest artifact rows must be objects")
        d1_codes.append(_v4_global(_v4_scope, '_canonical_code')(row.get("security_id", row.get("code"))))
    if _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(d1_codes)) != _v4_global(_v4_scope, 'POOL_LIMIT') or _v4_global(_v4_scope, 'set')(d1_codes) != raw_code_set:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("d1_manifest artifact members do not match selector raw input")

    formula_manifest = payload.get("formula_manifest", metadata.get("formula_manifest"))
    formula_states, formula_binding = _v4_global(_v4_scope, '_formula_manifest_states')(formula_manifest)
    if _v4_global(_v4_scope, 'len')(formula_states) != _v4_global(_v4_scope, 'POOL_LIMIT') or _v4_global(_v4_scope, 'set')(formula_states) != raw_code_set:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula state artifact must cover exactly the 100 selector codes")
    formula = _v4_global(_v4_scope, '_formula_provenance')(
        metadata,
        trade_date,
        cutoff,
        require_artifact=True,
    )
    if (
        formula["input_sha256"] != formula_binding["input_sha256"]
        or formula["rule_sha256"] != formula_binding["rule_sha256"]
    ):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula provenance hashes do not match the verified formula manifest")
    if formula.get("artifact", {}).get("sha256") != formula_binding.get("artifact", {}).get("sha256"):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula provenance state artifact is not the verified manifest artifact")
    if formula.get("rule_artifact", {}).get("sha256") != formula_binding.get("rule_artifact", {}).get("sha256"):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula provenance rule artifact is not the verified manifest rule artifact")

    time_evidence = payload.get("time_evidence", metadata.get("time_evidence"))
    if not _v4_global(_v4_scope, 'isinstance')(time_evidence, _v4_global(_v4_scope, 'Mapping')) or not time_evidence:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("verified time_evidence is required for selector capture")
    evidence_captured = time_evidence.get("captured_at")
    if not evidence_captured:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("time_evidence.captured_at is required")
    evidence_at = _v4_global(_v4_scope, '_parse_timestamp')(evidence_captured, trade_date, "time_evidence.captured_at")
    if evidence_at > cutoff:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("time_evidence.captured_at is after the stage cutoff")
    if evidence_at != captured_at:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("time_evidence.captured_at does not match metadata captured_at")
    for key, expected in (("trade_date", trade_date), ("stage", stage_id)):
        value = time_evidence.get(key)
        if value not in (None, "") and _v4_global(_v4_scope, 'str')(value).replace("-", "") != expected:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"time_evidence {key} does not match capture metadata")
    evidence_cutoff = time_evidence.get("cutoff_ts")
    if evidence_cutoff not in (None, "") and _v4_global(_v4_scope, '_parse_timestamp')(evidence_cutoff, trade_date, "time_evidence.cutoff_ts") != cutoff:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("time_evidence.cutoff_ts does not match capture metadata")

    return {
        "admission_mode": admission_mode,
        "trade_date": trade_date,
        "stage": stage_id,
        "cutoff_ts": cutoff_iso,
        "raw_input_sha256": raw_input_sha,
        "raw_artifact_sha256": _v4_global(_v4_scope, 'str')(raw_artifact_sha).lower(),
        "d1_manifest": d1_binding,
        "formula_manifest": formula_binding,
        "production_binding": binding,
        "time_evidence": _v4_global(_v4_scope, 'dict')(time_evidence),
    }


def _preflight_capture_input_body(_v4_scope, /, payload_or_path):
    """Run the static admission gate for a raw selector capture request.

    ``READY_FOR_CAPTURE_INVOCATION`` authorizes only the subsequent selector
    invocation.  It is never a frozen run and never increments a natural-day
    counter.
    """

    payload = _v4_global(_v4_scope, '_read_json')(payload_or_path) if _v4_global(_v4_scope, 'isinstance')(payload_or_path, (_v4_global(_v4_scope, 'Path'), _v4_global(_v4_scope, 'str'))) else payload_or_path
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        return {
            "status": "REJECTED",
            "capture_ready": False,
            "reasons": ["INPUT_NOT_OBJECT"],
            "natural_sample_count": 0,
            "counts_as_forward_day": False,
        }
    try:
        binding = _v4_global(_v4_scope, '_validate_capture_request_static')(payload)
    except _v4_global(_v4_scope, 'ShadowInvalid') as error:
        return {
            "status": "REJECTED",
            "capture_ready": False,
            "reasons": [_v4_global(_v4_scope, 'str')(error)],
            "natural_sample_count": 0,
            "counts_as_forward_day": False,
            "observation_mode": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_metadata_from_input')(payload).get("observation_mode") or "").upper(),
        }
    return {
        "status": "READY_FOR_CAPTURE_INVOCATION",
        "capture_ready": True,
        "admission_mode": binding["admission_mode"],
        "reasons": [],
        "trade_date": binding["trade_date"],
        "stage": binding["stage"],
        "cutoff_ts": binding["cutoff_ts"],
        "raw_input_sha256": binding["raw_input_sha256"],
        "natural_sample_count": 0,
        "counts_as_forward_day": False,
        "hit_ready": False,
        "frozen": False,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
