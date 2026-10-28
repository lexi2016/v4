"""stage_center.formula_margin_shadow: capture_payload (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_selector_return_body(_v4_scope, /, selector_result, metadata, *, expected_raw_artifact_sha):
    """Validate the actual envelope returned by ``select_hk_four_lane``."""

    if not _v4_global(_v4_scope, 'isinstance')(selector_result, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return envelope must be an object")
    required = (
        "run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256",
        "selection_status", "trade_date", "stage_id", "market", "rows",
    )
    for key in required:
        if key not in selector_result or selector_result.get(key) in (None, ""):
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"selector return {key} is required")
    trade_date, stage_id, _, _ = _v4_global(_v4_scope, '_stage_contract')(metadata)
    if _v4_global(_v4_scope, 'str')(selector_result.get("trade_date") or "").replace("-", "") != trade_date:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return trade_date mismatch")
    if _v4_global(_v4_scope, 'str')(selector_result.get("stage_id") or "") != stage_id:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return stage_id mismatch")
    if _v4_global(_v4_scope, 'str')(selector_result.get("market") or "") != _v4_global(_v4_scope, 'MARKET'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return market mismatch")
    if _v4_global(_v4_scope, 'str')(selector_result.get("raw_artifact_sha256") or "").lower() != _v4_global(_v4_scope, 'str')(expected_raw_artifact_sha).lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return raw_artifact_sha256 mismatch")
    if not _v4_global(_v4_scope, '_is_sha')(selector_result.get("algorithm_sha256")):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return algorithm_sha256 is invalid")
    if not _v4_global(_v4_scope, 'str')(selector_result.get("run_id") or "").strip() or not _v4_global(_v4_scope, 'str')(selector_result.get("artifact_id") or "").strip():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector return identity is missing")
    top10 = _v4_global(_v4_scope, '_selector_result_codes')(selector_result)
    return {
        "run_id": _v4_global(_v4_scope, 'str')(selector_result["run_id"]).strip(),
        "artifact_id": _v4_global(_v4_scope, 'str')(selector_result["artifact_id"]).strip(),
        "algorithm_sha256": _v4_global(_v4_scope, 'str')(selector_result["algorithm_sha256"]).lower(),
        "raw_artifact_sha256": _v4_global(_v4_scope, 'str')(selector_result["raw_artifact_sha256"]).lower(),
        "selection_status": _v4_global(_v4_scope, 'str')(selector_result["selection_status"]),
        "top10_codes": top10,
        "sha256": _v4_global(_v4_scope, 'sha256_bytes')(_v4_global(_v4_scope, 'canonical_json')(_v4_global(_v4_scope, 'dict')(selector_result))),
    }


def _build_selector_capture_payload_body(_v4_scope, /, *, metadata, raw_rows, sorted_rows, production_rows, formula_manifest, time_evidence, d1_manifest, raw_artifact_sha256):
    """Adapt a real selector hook capture into a frozen shadow input.

    The adapter assigns ``production_rank`` from the selector's full sorted
    output.  It never accepts a caller-supplied rank and never derives
    eligibility from ``formal_eligible``: rows that the selector actually
    ranked carry ``selection_eligible=True`` and become the shadow's explicit
    eligible set.  Formula states are joined only from the verified manifest;
    no formula producer or fallback is called here.
    """

    if not _v4_global(_v4_scope, 'isinstance')(metadata, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector capture metadata is required")
    admission_mode = _v4_global(_v4_scope, '_admission_mode')(metadata)
    if not _v4_global(_v4_scope, 'isinstance')(time_evidence, _v4_global(_v4_scope, 'Mapping')) or not time_evidence:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("verified time_evidence is required for a selector capture")
    if not _v4_global(_v4_scope, 'isinstance')(raw_rows, _v4_global(_v4_scope, 'Sequence')) or _v4_global(_v4_scope, 'isinstance')(raw_rows, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'bytes'))):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector raw_rows must be a sequence")
    if not _v4_global(_v4_scope, 'isinstance')(sorted_rows, _v4_global(_v4_scope, 'Sequence')) or _v4_global(_v4_scope, 'isinstance')(sorted_rows, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'bytes'))):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector sorted_rows must be a sequence")
    if not _v4_global(_v4_scope, 'isinstance')(production_rows, _v4_global(_v4_scope, 'Sequence')) or _v4_global(_v4_scope, 'isinstance')(production_rows, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'bytes'))):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector production_rows must be a sequence")
    d1_binding = _v4_global(_v4_scope, '_verified_manifest_binding')(d1_manifest, "d1_manifest", require_artifact=True)
    formula_states, formula_binding = _v4_global(_v4_scope, '_formula_manifest_states')(formula_manifest)
    metadata_copy = _v4_global(_v4_scope, 'dict')(metadata)
    metadata_copy["admission_mode"] = admission_mode
    if raw_artifact_sha256 is None:
        raw_artifact_sha256 = metadata_copy.get("raw_artifact_sha256")
    if not _v4_global(_v4_scope, '_is_sha')(raw_artifact_sha256):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("raw_artifact_sha256 is required for a selector capture")
    declared_raw_artifact_sha = metadata_copy.get("raw_artifact_sha256")
    if declared_raw_artifact_sha not in (None, "") and _v4_global(_v4_scope, 'str')(declared_raw_artifact_sha).lower() != _v4_global(_v4_scope, 'str')(raw_artifact_sha256).lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("metadata raw_artifact_sha256 does not match selector raw artifact SHA")
    source_record = _v4_global(_v4_scope, '_checked_file_artifact')(
        metadata_copy.get("source_artifact"),
        "source_artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(metadata_copy.get("input_sha256") or "").lower(),
        required=True,
    )
    rule_record = _v4_global(_v4_scope, '_checked_file_artifact')(
        metadata_copy.get("rule_artifact"),
        "rule_artifact",
        expected_sha=_v4_global(_v4_scope, 'str')(metadata_copy.get("rule_sha256") or "").lower(),
        required=True,
    )
    if not _v4_global(_v4_scope, 'isinstance')(source_record, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'str')(source_record["sha256"]).lower() != _v4_global(_v4_scope, 'str')(raw_artifact_sha256).lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("raw_artifact_sha256 is not bound to the verified source artifact")
    metadata_copy["source_artifact"] = source_record
    metadata_copy["rule_artifact"] = rule_record
    formula_provenance = metadata_copy.get("formula_provenance")
    if not _v4_global(_v4_scope, 'isinstance')(formula_provenance, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_provenance is required for a selector capture")
    formula_provenance_copy = _v4_global(_v4_scope, 'dict')(formula_provenance)
    if (
        _v4_global(_v4_scope, 'str')(formula_provenance_copy.get("input_sha256", formula_provenance_copy.get("input_sha")) or "").lower()
        != _v4_global(_v4_scope, 'str')(formula_binding["input_sha256"]).lower()
        or _v4_global(_v4_scope, 'str')(formula_provenance_copy.get("rule_sha256", formula_provenance_copy.get("rule_sha")) or "").lower()
        != _v4_global(_v4_scope, 'str')(formula_binding["rule_sha256"]).lower()
    ):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("formula_manifest hashes do not match formula_provenance")
    formula_provenance_copy["artifact"] = formula_binding["artifact"]
    formula_provenance_copy["rule_artifact"] = formula_binding["rule_artifact"]
    metadata_copy["formula_provenance"] = formula_provenance_copy
    metadata_copy["d1_manifest"] = d1_binding
    metadata_copy["time_evidence"] = _v4_global(_v4_scope, 'dict')(time_evidence)
    metadata_copy["formula_manifest_binding"] = formula_binding
    raw_input_sha = _v4_global(_v4_scope, 'sha256_bytes')(_v4_global(_v4_scope, 'canonical_json')(_v4_global(_v4_scope, 'list')(raw_rows)))
    declared_raw_input_sha = metadata_copy.get("raw_input_sha256")
    if declared_raw_input_sha not in (None, "") and _v4_global(_v4_scope, 'str')(declared_raw_input_sha).lower() != raw_input_sha:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("raw_input_sha256 does not match selector input rows")
    metadata_copy["raw_input_sha256"] = raw_input_sha
    metadata_copy["raw_artifact_sha256"] = _v4_global(_v4_scope, 'str')(raw_artifact_sha256).lower()

    if _v4_global(_v4_scope, 'len')(sorted_rows) != _v4_global(_v4_scope, 'POOL_LIMIT'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')(f"full selector sorted rows are required; got {_v4_global(_v4_scope, 'len')(sorted_rows)}")
    if _v4_global(_v4_scope, 'len')(production_rows) < _v4_global(_v4_scope, 'TOP_K'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector production Top10 rows are missing")

    raw_by_code: dict[str, Mapping[str, Any]] = {}
    for raw in raw_rows:
        if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("selector raw rows must be objects")
        code = _v4_global(_v4_scope, '_canonical_code')(raw.get("security_id", raw.get("code")))
        if code in raw_by_code:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"duplicate selector raw row: {code}")
        raw_by_code[code] = raw
    d1_artifact = d1_binding.get("artifact")
    if not _v4_global(_v4_scope, 'isinstance')(d1_artifact, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("d1_manifest actual artifact is required")
    d1_payload = _v4_global(_v4_scope, '_read_json')(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(d1_artifact["path"])))
    if not _v4_global(_v4_scope, 'isinstance')(d1_payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("d1_manifest artifact must contain an object")
    d1_source = d1_payload.get("rows", d1_payload.get("members"))
    if not _v4_global(_v4_scope, 'isinstance')(d1_source, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("d1_manifest artifact rows are required")
    d1_codes = {
        _v4_global(_v4_scope, '_canonical_code')(row.get("security_id", row.get("code")))
        for row in d1_source
        if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
    }
    if d1_codes != _v4_global(_v4_scope, 'set')(raw_by_code):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("d1_manifest artifact members do not match selector raw input")
    source_artifact = metadata_copy.get("source_artifact")
    if not _v4_global(_v4_scope, 'isinstance')(source_artifact, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact actual bytes are required")
    source_payload = _v4_global(_v4_scope, '_read_json')(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(source_artifact["path"])))
    if not _v4_global(_v4_scope, 'isinstance')(source_payload, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact must contain an object")
    source_rows = source_payload.get("rows", source_payload.get("members"))
    if not _v4_global(_v4_scope, 'isinstance')(source_rows, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact rows are required")
    if _v4_global(_v4_scope, 'canonical_json')(source_rows) != _v4_global(_v4_scope, 'canonical_json')(_v4_global(_v4_scope, 'list')(raw_rows)):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact rows do not canonically match selector raw input")
    source_codes = {
        _v4_global(_v4_scope, '_canonical_code')(row.get("security_id", row.get("code")))
        for row in source_rows
        if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
    }
    if source_codes != _v4_global(_v4_scope, 'set')(raw_by_code):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("source_artifact rows do not match selector raw input")
    sorted_codes: list[str] = []
    capture_rows: list[dict[str, Any]] = []
    for rank, selected in _v4_global(_v4_scope, 'enumerate')(sorted_rows, start=1):
        if not _v4_global(_v4_scope, 'isinstance')(selected, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("selector sorted rows must be objects")
        code = _v4_global(_v4_scope, '_canonical_code')(selected.get("security_id", selected.get("code")))
        sorted_codes.append(code)
        source = raw_by_code.get(code)
        if source is None:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"selector raw input is missing ranked member: {code}")
        if selected.get("selection_eligible") is not True:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{code}: selection_eligible must come from the selector hook")
        states = formula_states.get(code)
        if states is None:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"formula_manifest state is missing: {code}")
        merged = _v4_global(_v4_scope, 'dict')(source)
        # Comparator fields and lane labels come from the actual selector
        # output.  The raw source remains responsible for explicit price/time
        # semantics and for the original member identity.
        merged.update(_v4_global(_v4_scope, 'dict')(selected))
        merged["security_id"] = code
        merged["code"] = code
        merged["eligible"] = True
        merged["selection_eligible"] = True
        merged["production_rank"] = rank
        lane = selected.get("candidate_lanes")
        if not _v4_global(_v4_scope, 'isinstance')(lane, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'))) or not lane:
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"{code}: selector candidate_lanes are required")
        merged["lane"] = _v4_global(_v4_scope, 'list')(lane)
        merged["stage_score"] = selected.get("stage_score")
        merged["candidate_bucket"] = selected.get("candidate_bucket")
        merged["trade_status_contract"] = selected.get("trade_status_contract")
        merged["pct_chg"] = selected.get("pct_chg")
        merged["volume_ratio"] = selected.get("volume_ratio")
        merged.update(states)
        merged["stage_price"] = _v4_global(_v4_scope, '_capture_price_alias')(merged, "stage_price", "last_price", "price", "lastPrice")
        merged["price_ts"] = _v4_global(_v4_scope, '_capture_price_alias')(merged, "price_ts", "update_time", "source_last_bar_time")
        merged["currency"] = _v4_global(_v4_scope, '_capture_price_alias')(merged, "currency", "quote_currency", "price_currency")
        merged["adjustment_mode"] = _v4_global(_v4_scope, '_capture_price_alias')(merged, "adjustment_mode")
        merged["price_source"] = _v4_global(_v4_scope, '_capture_price_alias')(merged, "price_source")
        capture_rows.append(merged)

    production_codes = [
        _v4_global(_v4_scope, '_canonical_code')(row.get("security_id", row.get("code")))
        for row in production_rows
        if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
    ]
    if _v4_global(_v4_scope, 'len')(production_codes) < _v4_global(_v4_scope, 'TOP_K'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector production rows contain fewer than ten codes")
    if production_codes[:_v4_global(_v4_scope, 'TOP_K')] != sorted_codes[:_v4_global(_v4_scope, 'TOP_K')]:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("production Top10 does not match the selector's pre-cap sorted rows")
    if _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(sorted_codes)) != _v4_global(_v4_scope, 'len')(sorted_codes):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("duplicate selector sorted row code")
    if _v4_global(_v4_scope, 'set')(sorted_codes) != _v4_global(_v4_scope, 'set')(raw_by_code):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selector raw input/member set does not match full sorted rows")
    metadata_copy["d1_pool_size"] = _v4_global(_v4_scope, 'len')(capture_rows)
    metadata_copy["selector_capture_binding"] = {
        "raw_artifact_sha256": _v4_global(_v4_scope, 'str')(raw_artifact_sha256).lower(),
        "raw_input_sha256": raw_input_sha,
        "d1_manifest": d1_binding,
        "formula_manifest": formula_binding,
        "time_evidence": _v4_global(_v4_scope, 'dict')(time_evidence),
        "production_top10_codes": production_codes[:_v4_global(_v4_scope, 'TOP_K')],
        "selection_eligible_definition": "rows returned by select_hk_four_lane before public Top10 cap",
    }
    return {**metadata_copy, "rows": capture_rows}
