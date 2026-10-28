"""ops.run_review_core_natural_pool_pipeline: official_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _validate_official_result_body(_v4_scope, /, official, request, *, official_exit_code, exit_code, stderr):
    """Validate the official receipt and return the adapter envelope."""

    if official_exit_code is None:
        official_exit_code = _v4_global(_v4_scope, 'int')(exit_code if exit_code is not None else 0)
    envelope = _v4_global(_v4_scope, '_base_envelope')(request)
    errors: list[dict[str, str]] = []
    observed_status = _v4_global(_v4_scope, '_status')(official.get("status"))
    official_schema = official.get("schema") or official.get("schema_version")
    if official_schema != _v4_global(_v4_scope, 'OFFICIAL_SCHEMA'):
        errors.append(_v4_global(_v4_scope, '_error')("InvalidOfficialSchema", "official receipt schema is unsupported"))
    if official.get("trade_date") not in (None, request.trade_date):
        errors.append(_v4_global(_v4_scope, '_error')("DateIdentityMismatch", "official trade_date does not match request"))
    if official.get("previous_trade_date") not in (None, request.previous_trade_date):
        errors.append(_v4_global(_v4_scope, '_error')("DateIdentityMismatch", "official previous_trade_date does not match request"))
    if official.get("target_date") not in (None, request.target_date):
        errors.append(_v4_global(_v4_scope, '_error')("DateIdentityMismatch", "official target_date does not match request"))
    if official_exit_code != 0:
        errors.append(_v4_global(_v4_scope, '_error')("OfficialPipelineExit", f"official pool_pipeline exited with code {official_exit_code}"))
    if stderr.strip():
        envelope["stderr"] = stderr[-2000:]

    if observed_status not in {"READY", "READY_EMPTY", "PARTIAL", "CANNOT_CONFIRM", "FAILED"}:
        errors.append(_v4_global(_v4_scope, '_error')("InvalidStatus", "official status is missing or unsupported"))

    observed_flags = {name: official.get(name) for name in _v4_global(_v4_scope, 'SAFETY_FLAGS')}
    envelope["observed_safety_flags"] = observed_flags
    for name in _v4_global(_v4_scope, 'SAFETY_FLAGS'):
        if official.get(name) is not False:
            errors.append(_v4_global(_v4_scope, '_error')("UnsafeSafetyFlag", f"official {name} is not false"))

    raw_workloads = official.get("workloads")
    if not _v4_global(_v4_scope, 'isinstance')(raw_workloads, _v4_global(_v4_scope, 'Mapping')):
        raw_workloads = {}
        errors.append(_v4_global(_v4_scope, '_error')("MissingWorkloads", "official workloads object is missing"))
    workloads: dict[str, dict[str, Any]] = {}
    for name in _v4_global(_v4_scope, 'WORKLOADS'):
        value = raw_workloads.get(name)
        if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
            workloads[name] = {
                "status": "CANNOT_CONFIRM",
                "error": _v4_global(_v4_scope, '_error')("MissingWorkload", f"official workload is missing: {name}"),
            }
            errors.append(_v4_global(_v4_scope, '_error')("MissingWorkload", name))
            continue
        item = _v4_global(_v4_scope, 'dict')(value)
        _v4_global(_v4_scope, '_copy_provenance_fields')(item)
        item_status = _v4_global(_v4_scope, '_status')(item.get("status"))
        if item_status not in {"READY", "READY_EMPTY", "PARTIAL", "CANNOT_CONFIRM", "FAILED"}:
            workloads[name] = {
                "status": "CANNOT_CONFIRM",
                "observed_status": item_status,
                "error": _v4_global(_v4_scope, '_error')("InvalidWorkloadStatus", name),
            }
            errors.append(_v4_global(_v4_scope, '_error')("InvalidWorkloadStatus", name))
            continue
        item["status"] = item_status
        nested_flags = item.get("safety_flags")
        for flag in _v4_global(_v4_scope, 'SAFETY_FLAGS'):
            if flag in item and item.get(flag) is not False:
                errors.append(_v4_global(_v4_scope, '_error')("UnsafeSafetyFlag", f"workload {name} {flag} is not false"))
            if _v4_global(_v4_scope, 'isinstance')(nested_flags, _v4_global(_v4_scope, 'Mapping')) and flag in nested_flags and nested_flags.get(flag) is not False:
                errors.append(_v4_global(_v4_scope, '_error')("UnsafeSafetyFlag", f"workload {name} safety_flags.{flag} is not false"))
        if not _v4_global(_v4_scope, '_has_provenance')(item):
            errors.append(_v4_global(_v4_scope, '_error')("MissingProvenance", name))
            if item_status in {"READY", "READY_EMPTY"}:
                item["observed_status"] = item_status
                item["status"] = "CANNOT_CONFIRM"
                item["error"] = _v4_global(_v4_scope, '_error')("MissingProvenance", f"workload lacks provenance: {name}")
        workloads[name] = item
    envelope["workloads"] = workloads

    run_id_value = official.get("run_id") or official.get("run")
    if not _v4_global(_v4_scope, 'isinstance')(run_id_value, _v4_global(_v4_scope, 'str')) or not run_id_value.strip():
        errors.append(_v4_global(_v4_scope, '_error')("MissingRunProvenance", "official run_id is missing"))
    envelope["run_id"] = _v4_global(_v4_scope, 'str')(run_id_value or "")
    envelope["receipt_path"] = _v4_global(_v4_scope, 'str')(official.get("receipt_path") or "")
    envelope["official_status"] = observed_status or "CANNOT_CONFIRM"
    envelope["official_result"] = _v4_global(_v4_scope, 'dict')(official)

    workload_statuses = [_v4_global(_v4_scope, 'str')(workloads[name].get("status") or "CANNOT_CONFIRM") for name in _v4_global(_v4_scope, 'WORKLOADS')]
    all_ready = _v4_global(_v4_scope, 'all')(status in {"READY", "READY_EMPTY"} for status in workload_statuses)
    if observed_status == "READY" and not all_ready:
        errors.append(_v4_global(_v4_scope, '_error')("StatusMismatch", "READY official status requires every workload READY"))
    if observed_status == "PARTIAL" and not _v4_global(_v4_scope, 'any')(status == "PARTIAL" for status in workload_statuses):
        errors.append(_v4_global(_v4_scope, '_error')("StatusMismatch", "PARTIAL official status requires a PARTIAL workload"))

    if errors:
        final_status = "CANNOT_CONFIRM"
    elif observed_status == "READY" and all_ready:
        final_status = "READY"
    elif observed_status == "PARTIAL":
        final_status = "PARTIAL"
    else:
        final_status = "CANNOT_CONFIRM"
    envelope["status"] = final_status
    envelope["overall_status"] = final_status
    envelope["errors"] = errors
    if errors:
        envelope["error"] = errors[0]
    return envelope
