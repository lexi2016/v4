"""stage_center.formula_margin_shadow: frozen_readers (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _record_invalid_capture_body(_v4_scope, /, output_root, metadata, reasons, *, context):
    """Write one immutable pre-freeze capture invalid ledger.

    This is intentionally separate from ``labels/invalid_ledger.json``:
    capture failures happen before a baseline can be frozen and therefore
    must never look like a labelled run.  The function is best-effort for the
    selector observer boundary and returns ``CANNOT_CONFIRM`` on write
    failure instead of raising a second error into production selection.
    """

    raw_metadata = _v4_global(_v4_scope, 'dict')(metadata) if _v4_global(_v4_scope, 'isinstance')(metadata, _v4_global(_v4_scope, 'Mapping')) else {}
    try:
        admission_mode = _v4_global(_v4_scope, '_admission_mode')(raw_metadata, default=None)
    except _v4_global(_v4_scope, 'ShadowInvalid'):
        admission_mode = None
    trade_text = _v4_global(_v4_scope, 'str')(raw_metadata.get("trade_date") or "").replace("-", "")
    trade_component = trade_text if _v4_global(_v4_scope, 'len')(trade_text) == 8 and trade_text.isdigit() else "unknown_date"
    stage_text = _v4_global(_v4_scope, 'str')(raw_metadata.get("stage") or raw_metadata.get("stage_id") or "")
    stage_component = stage_text if stage_text in _v4_global(_v4_scope, 'STAGE_CUTOFFS') else "unknown_stage"
    reason_list = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(_v4_global(_v4_scope, 'str')(reason) for reason in reasons if _v4_global(_v4_scope, 'str')(reason)))
    if not reason_list:
        reason_list = ["CAPTURE_INVALID"]
    try:
        root = _v4_global(_v4_scope, '_ensure_output_root')(output_root)
        date_root = root / trade_component
        stage_root = date_root / stage_component
        if date_root.is_symlink() or stage_root.is_symlink():
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture invalid-ledger directory cannot be symlinked")
        invalid_path = stage_root / "invalid_ledger.json"
        safe_context: Any = {}
        if _v4_global(_v4_scope, 'isinstance')(context, _v4_global(_v4_scope, 'Mapping')):
            try:
                safe_context = _v4_global(_v4_scope, 'json').loads(_v4_global(_v4_scope, 'json').dumps(_v4_global(_v4_scope, 'dict')(context), ensure_ascii=False, default=_v4_global(_v4_scope, 'str')))
            except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
                safe_context = {"context_serialization": "FAILED"}
        payload = {
            "schema_version": _v4_global(_v4_scope, 'SCHEMA_VERSION'),
            "experiment_id": _v4_global(_v4_scope, 'EXPERIMENT_ID'),
            "trade_date": trade_text or None,
            "stage": stage_text or None,
            "admission_mode": admission_mode,
            "status": "CANNOT_CONFIRM",
            "invalid_reasons": reason_list,
            "source_version": raw_metadata.get("source_version"),
            "input_sha256": raw_metadata.get("input_sha256"),
            "raw_input_sha256": raw_metadata.get("raw_input_sha256"),
            "raw_artifact_sha256": raw_metadata.get("raw_artifact_sha256"),
            "run_id": raw_metadata.get("run_id"),
            "comparator_version": raw_metadata.get("comparator_version"),
            "d1_manifest": raw_metadata.get("d1_manifest"),
            "formula_manifest_binding": raw_metadata.get("formula_manifest_binding"),
            "time_evidence": raw_metadata.get("time_evidence"),
            "context": safe_context,
            "recorded_before_selection_freeze": True,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        ledger_sha = _v4_global(_v4_scope, '_immutable_json')(invalid_path, payload)
        return {
            "status": "CANNOT_CONFIRM",
            "run_root": _v4_global(_v4_scope, 'str')(stage_root),
            "invalid_ledger": _v4_global(_v4_scope, 'str')(invalid_path),
            "invalid_ledger_sha256": ledger_sha,
            "invalid_reasons": reason_list,
            "safety": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'SAFETY_FLAGS')),
        }
    except _v4_global(_v4_scope, 'Exception') as error:
        return {
            "status": "CANNOT_CONFIRM",
            "invalid_reasons": [*reason_list, f"INVALID_LEDGER_WRITE_FAILED:{error}"],
            "safety": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'SAFETY_FLAGS')),
        }


def __read_frozen_body(_v4_scope, /, run_root):
    root = _v4_global(_v4_scope, 'Path')(run_root).expanduser().resolve()
    paths = {
        "members": root / "members.json",
        "baseline": root / "baseline_top10.json",
        "candidate": root / "candidate_top10.json",
        "receipt": root / "selection_receipt.json",
    }
    for label, path in paths.items():
        if not path.is_file() or path.is_symlink():
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"frozen {label} artifact is missing")
    members = _v4_global(_v4_scope, '_read_json')(paths["members"])
    baseline = _v4_global(_v4_scope, '_read_json')(paths["baseline"])
    candidate = _v4_global(_v4_scope, '_read_json')(paths["candidate"])
    receipt = _v4_global(_v4_scope, '_read_json')(paths["receipt"])
    if not _v4_global(_v4_scope, 'isinstance')(members, _v4_global(_v4_scope, 'dict')) or not _v4_global(_v4_scope, 'isinstance')(baseline, _v4_global(_v4_scope, 'dict')) or not _v4_global(_v4_scope, 'isinstance')(candidate, _v4_global(_v4_scope, 'dict')) or not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'dict')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("frozen artifacts must be JSON objects")
    receipt_payload_sha = receipt.get("receipt_payload_sha256")
    if not _v4_global(_v4_scope, '_is_sha')(receipt_payload_sha):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selection receipt payload SHA is missing")
    receipt_without_self_hash = _v4_global(_v4_scope, 'dict')(receipt)
    receipt_without_self_hash.pop("receipt_payload_sha256", None)
    if _v4_global(_v4_scope, 'sha256_bytes')(_v4_global(_v4_scope, 'canonical_json')(receipt_without_self_hash)) != _v4_global(_v4_scope, 'str')(receipt_payload_sha).lower():
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selection receipt payload hash mismatch")
    artifacts = receipt.get("artifacts")
    if not _v4_global(_v4_scope, 'isinstance')(artifacts, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selection receipt artifact map is missing")
    for label, path in paths.items():
        if label == "receipt":
            continue
        detail = artifacts.get(label)
        if not _v4_global(_v4_scope, 'isinstance')(detail, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, '_is_sha')(detail.get("sha256")):
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"selection receipt {label} SHA is missing")
        if _v4_global(_v4_scope, 'sha256_file')(path) != _v4_global(_v4_scope, 'str')(detail["sha256"]).lower():
            raise _v4_global(_v4_scope, 'ShadowInvalid')(f"frozen {label} hash mismatch")
    capture_detail = artifacts.get("capture_time_receipt")
    capture_record = receipt.get("capture_time_receipt")
    if capture_detail is not None or capture_record is not None:
        if not _v4_global(_v4_scope, 'isinstance')(capture_detail, _v4_global(_v4_scope, 'Mapping')) or capture_detail.get("path") != "capture_time_receipt.json":
            raise _v4_global(_v4_scope, 'ShadowInvalid')("selection receipt capture_time_receipt artifact is missing")
        if not _v4_global(_v4_scope, '_is_sha')(capture_detail.get("sha256")):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("selection receipt capture_time_receipt SHA is missing")
        capture_path = root / "capture_time_receipt.json"
        if not capture_path.is_file() or capture_path.is_symlink():
            raise _v4_global(_v4_scope, 'ShadowInvalid')("frozen capture_time_receipt artifact is missing")
        if _v4_global(_v4_scope, 'sha256_file')(capture_path) != _v4_global(_v4_scope, 'str')(capture_detail["sha256"]).lower():
            raise _v4_global(_v4_scope, 'ShadowInvalid')("frozen capture_time_receipt hash mismatch")
        persisted_capture = _v4_global(_v4_scope, '_read_json')(capture_path)
        if not _v4_global(_v4_scope, 'isinstance')(capture_record, _v4_global(_v4_scope, 'Mapping')) or persisted_capture != capture_record:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt payload mismatch")
        if persisted_capture.get("schema_version") != _v4_global(_v4_scope, 'CAPTURE_TIME_RECEIPT_SCHEMA_VERSION'):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt schema mismatch")
        if persisted_capture.get("source") != _v4_global(_v4_scope, 'CAPTURE_TIME_SOURCE'):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt source mismatch")
        for flag, expected in _v4_global(_v4_scope, 'SAFETY_FLAGS').items():
            if persisted_capture.get(flag) != expected:
                raise _v4_global(_v4_scope, 'ShadowInvalid')("capture_time_receipt safety flags changed")
        if persisted_capture.get("invocation_verified") is True:
            if persisted_capture.get("schema_version") != _v4_global(_v4_scope, 'CAPTURE_TIME_RECEIPT_SCHEMA_VERSION'):
                raise _v4_global(_v4_scope, 'ShadowInvalid')("invocation-verified capture receipt schema mismatch")
            if persisted_capture.get("capture_origin") != _v4_global(_v4_scope, 'CAPTURE_ORIGIN_SELECTOR') or persisted_capture.get("invocation_status") != _v4_global(_v4_scope, 'INVOCATION_STATUS_VERIFIED'):
                raise _v4_global(_v4_scope, 'ShadowInvalid')("invocation-verified capture receipt origin/status mismatch")
            if persisted_capture.get("invocation_verification_basis") != _v4_global(_v4_scope, 'INVOCATION_VERIFICATION_BASIS'):
                raise _v4_global(_v4_scope, 'ShadowInvalid')("invocation-verified capture receipt basis mismatch")
            capture_trade = _v4_global(_v4_scope, '_exact_date')(persisted_capture.get("trade_date"), "capture receipt trade_date")
            capture_stage = _v4_global(_v4_scope, 'str')(persisted_capture.get("stage") or "")
            started = _v4_global(_v4_scope, '_parse_timestamp')(persisted_capture.get("selector_started_at"), capture_trade, "selector_started_at")
            finished = _v4_global(_v4_scope, '_parse_timestamp')(persisted_capture.get("selector_finished_at"), capture_trade, "selector_finished_at")
            _v4_global(_v4_scope, '_validate_runtime_capture_timestamp')(started, capture_trade, capture_stage)
            _v4_global(_v4_scope, '_validate_runtime_capture_timestamp')(finished, capture_trade, capture_stage)
            if finished < started:
                raise _v4_global(_v4_scope, 'ShadowInvalid')("selector runtime timestamps are out of order")
    invocation_verified = receipt.get("invocation_verified") is True
    if _v4_global(_v4_scope, 'isinstance')(capture_record, _v4_global(_v4_scope, 'Mapping')) and capture_record.get("invocation_verified") is not invocation_verified:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("selection receipt/capture receipt invocation status mismatch")
    if _v4_global(_v4_scope, 'isinstance')(capture_record, _v4_global(_v4_scope, 'Mapping')):
        for key in ("capture_origin", "invocation_status", "counts_as_forward_day", "natural_sample_count"):
            if capture_record.get(key) != receipt.get(key):
                raise _v4_global(_v4_scope, 'ShadowInvalid')(f"selection receipt/capture receipt {key} mismatch")
    if invocation_verified:
        if receipt.get("capture_origin") != _v4_global(_v4_scope, 'CAPTURE_ORIGIN_SELECTOR') or receipt.get("invocation_status") != _v4_global(_v4_scope, 'INVOCATION_STATUS_VERIFIED'):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("invocation-verified frozen origin/status mismatch")
        provenance = receipt.get("provenance")
        required_provenance = _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'PROVENANCE_FILES')) | {"selector_result"}
        if not _v4_global(_v4_scope, 'isinstance')(provenance, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(provenance) != required_provenance:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("sealed provenance set is incomplete")
        selector_artifact = artifacts.get("selector_result")
        if not _v4_global(_v4_scope, 'isinstance')(selector_artifact, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'dict')(selector_artifact) != _v4_global(_v4_scope, 'dict')(provenance.get("selector_result") or {}):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("selection receipt selector_result artifact binding is missing")
        for name, detail in provenance.items():
            if not _v4_global(_v4_scope, 'isinstance')(detail, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, '_is_sha')(detail.get("sha256")):
                raise _v4_global(_v4_scope, 'ShadowInvalid')(f"sealed provenance {name} descriptor is invalid")
            relative = _v4_global(_v4_scope, 'str')(detail.get("path") or "")
            if name == "selector_result":
                if relative != "selector_result.json":
                    raise _v4_global(_v4_scope, 'ShadowInvalid')("selector_result provenance path is invalid")
            elif relative != f"provenance/{_v4_global(_v4_scope, 'PROVENANCE_FILES')[name][0]}":
                raise _v4_global(_v4_scope, 'ShadowInvalid')(f"sealed provenance {name} path is invalid")
            local = root / relative
            if not local.is_file() or local.is_symlink() or _v4_global(_v4_scope, 'sha256_file')(local) != _v4_global(_v4_scope, 'str')(detail["sha256"]).lower():
                raise _v4_global(_v4_scope, 'ShadowInvalid')(f"sealed provenance {name} hash mismatch")
        selector_detail = provenance["selector_result"]
        selector_path = root / _v4_global(_v4_scope, 'str')(selector_detail["path"])
        selector_result = _v4_global(_v4_scope, '_read_json')(selector_path)
        if not _v4_global(_v4_scope, 'isinstance')(selector_result, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("sealed selector_result must be an object")
        if _v4_global(_v4_scope, 'sha256_bytes')(_v4_global(_v4_scope, 'canonical_json')(selector_result)) != _v4_global(_v4_scope, 'str')(selector_detail["sha256"]).lower():
            raise _v4_global(_v4_scope, 'ShadowInvalid')("sealed selector_result canonical hash mismatch")
        identity_receipt: Mapping[str, Any] = capture_record if _v4_global(_v4_scope, 'isinstance')(capture_record, _v4_global(_v4_scope, 'Mapping')) else receipt
        selector_checks = {
            "production_run_id": selector_result.get("run_id"),
            "production_artifact_id": selector_result.get("artifact_id"),
            "production_algorithm_sha256": selector_result.get("algorithm_sha256"),
            "raw_artifact_sha256": selector_result.get("raw_artifact_sha256"),
        }
        for receipt_key, actual_value in selector_checks.items():
            if _v4_global(_v4_scope, 'str')(identity_receipt.get(receipt_key) or "").lower() != _v4_global(_v4_scope, 'str')(actual_value or "").lower():
                raise _v4_global(_v4_scope, 'ShadowInvalid')(f"sealed selector identity {receipt_key} mismatch")
        if _v4_global(_v4_scope, 'str')(identity_receipt.get("selector_result_sha256") or "").lower() != _v4_global(_v4_scope, 'str')(selector_detail["sha256"]).lower():
            raise _v4_global(_v4_scope, 'ShadowInvalid')("selection receipt selector_result SHA mismatch")
        source_detail = provenance["production_source"]
        if _v4_global(_v4_scope, 'str')(identity_receipt.get("source_artifact_sha256") or "").lower() != _v4_global(_v4_scope, 'str')(source_detail["sha256"]).lower():
            raise _v4_global(_v4_scope, 'ShadowInvalid')("sealed source_artifact_sha256 mismatch")
        if _v4_global(_v4_scope, 'str')(identity_receipt.get("raw_artifact_sha256") or "").lower() != _v4_global(_v4_scope, 'str')(source_detail["sha256"]).lower():
            raise _v4_global(_v4_scope, 'ShadowInvalid')("sealed raw_artifact_sha256 mismatch")
        if _v4_global(_v4_scope, 'str')(identity_receipt.get("raw_artifact_sha256") or "").lower() != _v4_global(_v4_scope, 'str')(identity_receipt.get("source_artifact_sha256") or "").lower():
            raise _v4_global(_v4_scope, 'ShadowInvalid')("raw/source artifact SHA equality mismatch")
        provenance_sha_checks = {
            "production_rule_sha256": "production_rule",
            "d1_manifest_sha256": "d1_manifest",
            "formula_state_artifact_sha256": "formula_state",
            "formula_rule_artifact_sha256": "formula_rule",
        }
        for receipt_key, provenance_key in provenance_sha_checks.items():
            if _v4_global(_v4_scope, 'str')(identity_receipt.get(receipt_key) or "").lower() != _v4_global(_v4_scope, 'str')(provenance[provenance_key]["sha256"]).lower():
                raise _v4_global(_v4_scope, 'ShadowInvalid')(f"sealed provenance {provenance_key} SHA mismatch")
        selector_top10 = _v4_global(_v4_scope, '_selector_result_codes')(selector_result)
        if _v4_global(_v4_scope, 'list')(baseline.get("codes", [])) != selector_top10:
            raise _v4_global(_v4_scope, 'ShadowInvalid')("frozen baseline does not equal sealed selector Top10")
    else:
        for artifact in (members, baseline, candidate, receipt):
            if artifact.get("capture_origin") != _v4_global(_v4_scope, 'CAPTURE_ORIGIN_DIRECT'):
                raise _v4_global(_v4_scope, 'ShadowInvalid')("direct frozen capture_origin changed")
            if artifact.get("invocation_verified") is not False:
                raise _v4_global(_v4_scope, 'ShadowInvalid')("direct frozen invocation_verified changed")
            if artifact.get("invocation_status") != _v4_global(_v4_scope, 'INVOCATION_STATUS_DIRECT'):
                raise _v4_global(_v4_scope, 'ShadowInvalid')("direct frozen invocation_status changed")
            if artifact.get("counts_as_forward_day") is not False or artifact.get("natural_sample_count") != 0:
                raise _v4_global(_v4_scope, 'ShadowInvalid')("direct frozen natural flags changed")
    for artifact in (members, baseline, candidate, receipt):
        if _v4_global(_v4_scope, 'any')(artifact.get(flag) != expected for flag, expected in _v4_global(_v4_scope, 'SAFETY_FLAGS').items()):
            raise _v4_global(_v4_scope, 'ShadowInvalid')("safety flags changed in frozen artifact")
    if receipt.get("truth_scope") != _v4_global(_v4_scope, 'TRUTH_SCOPE'):
        raise _v4_global(_v4_scope, 'ShadowInvalid')("frozen receipt truth_scope mismatch")
    if baseline.get("arm") != "B" or candidate.get("arm") != "F":
        raise _v4_global(_v4_scope, 'ShadowInvalid')("frozen arm labels are invalid")
    if baseline.get("codes") != [row.get("security_id") for row in baseline.get("rows", [])]:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("baseline codes/rows mismatch")
    if candidate.get("codes") != [row.get("security_id") for row in candidate.get("rows", [])]:
        raise _v4_global(_v4_scope, 'ShadowInvalid')("candidate codes/rows mismatch")
    return members, baseline, candidate, receipt


def __external_source_revalidation_body(_v4_scope, /, receipt, root):
    provenance = receipt.get("provenance")
    if not _v4_global(_v4_scope, 'isinstance')(provenance, _v4_global(_v4_scope, 'Mapping')):
        return "NOT_REQUESTED"
    statuses: list[str] = []
    for name in _v4_global(_v4_scope, 'PROVENANCE_FILES'):
        detail = provenance.get(name)
        if not _v4_global(_v4_scope, 'isinstance')(detail, _v4_global(_v4_scope, 'Mapping')):
            return "MISSING"
        external = _v4_global(_v4_scope, 'str')(detail.get("external_path") or "")
        path = _v4_global(_v4_scope, 'Path')(external).expanduser()
        if not external or not path.is_file() or path.is_symlink():
            statuses.append("MISSING")
        elif _v4_global(_v4_scope, 'sha256_file')(path) != _v4_global(_v4_scope, 'str')(detail.get("sha256") or "").lower():
            statuses.append("DRIFTED")
        else:
            statuses.append("PASS")
    if "MISSING" in statuses:
        return "MISSING"
    if "DRIFTED" in statuses:
        return "DRIFTED"
    return "PASS"


def _verify_frozen_artifacts_body(_v4_scope, /, run_root, *, external_revalidate):
    members, baseline, candidate, receipt = _v4_global(_v4_scope, '_read_frozen')(run_root)
    root = _v4_global(_v4_scope, 'Path')(run_root).expanduser().resolve()
    return {
        "status": "PASS",
        "frozen_integrity_status": "PASS",
        "integrity_scope": "LOCAL_FROZEN_AND_SEALED_PROVENANCE",
        "external_source_revalidation": (
            _v4_global(_v4_scope, '_external_source_revalidation')(receipt, root) if external_revalidate else "NOT_REQUESTED"
        ),
        "run_root": _v4_global(_v4_scope, 'str')(root),
        "trade_date": receipt.get("trade_date"),
        "stage": receipt.get("stage"),
        "baseline_codes": _v4_global(_v4_scope, 'list')(baseline.get("codes", [])),
        "candidate_codes": _v4_global(_v4_scope, 'list')(candidate.get("codes", [])),
        "member_count": _v4_global(_v4_scope, 'len')(members.get("rows", [])),
        "receipt_rule_version": receipt.get("rule_version"),
        "safety": {flag: receipt.get(flag) for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS')},
    }
