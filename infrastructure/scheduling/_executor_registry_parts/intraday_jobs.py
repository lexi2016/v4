"""infrastructure.scheduling.executor_registry: intraday_jobs (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _FixedExecutorRegistry__classify_intraday_failure_body(_v4_scope, /, self, result):
    """Keep the child's request boundary visible to scheduler retry logic."""

    payload = self._decoded_stdout(result)
    state = _v4_global(_v4_scope, 'str')(payload.get("attempt_state") or "").strip().upper()
    error_code = _v4_global(_v4_scope, 'str')(payload.get("error_code") or "").strip().upper()
    outcome_codes = {
        "INTRADAY_NO_REQUEST",
        "INTRADAY_REQUEST_ATTEMPTED",
        "INTRADAY_ATTEMPT_UNKNOWN",
    }
    if error_code == "INTRADAY_NO_REQUEST" and state != "FAILED_NO_REQUEST":
        # The state is the durable request-boundary fact.  A no-request
        # code cannot override a sent/in-flight/unknown state (or a
        # missing state), otherwise a retry may duplicate provider work.
        failure_class = "INTRADAY_ATTEMPT_UNKNOWN"
        state = state or "ATTEMPT_UNKNOWN"
    elif state == "FAILED_NO_REQUEST" and error_code in outcome_codes - {"INTRADAY_NO_REQUEST"}:
        # A terminal no-request marker contradicts another outcome code;
        # preserve the observed state but refuse to make it retryable.
        failure_class = "INTRADAY_ATTEMPT_UNKNOWN"
    elif state == "FAILED_NO_REQUEST":
        failure_class = "INTRADAY_NO_REQUEST"
    elif state == "REQUEST_ATTEMPTED":
        failure_class = "INTRADAY_REQUEST_ATTEMPTED"
    elif state in {"REQUEST_IN_FLIGHT", "ATTEMPT_UNKNOWN", "PREPARED", "STARTED"}:
        failure_class = "INTRADAY_ATTEMPT_UNKNOWN"
    elif not state and error_code in {"INTRADAY_CAPTURE_REFUSED", "INTRADAY_BINDING_REFUSED"}:
        failure_class = "INTRADAY_BINDING_REFUSED"
        state = "BINDING_REFUSED"
    else:
        # A timeout, malformed child envelope, or unrecognised state cannot
        # prove that no provider request happened, so it is never retried.
        failure_class = "INTRADAY_ATTEMPT_UNKNOWN"
        state = state or "ATTEMPT_UNKNOWN"
    classified = _v4_global(_v4_scope, 'dict')(result)
    classified.update(
        {
            "failure_class": failure_class,
            "attempt_state": state,
            "error_code": error_code or "INTRADAY_ATTEMPT_OUTCOME_UNDECLARED",
        }
    )
    return classified


def _FixedExecutorRegistry__intraday_research_body(_v4_scope, /, self, request):
    """The existing scheduler's single replacement for Vibe six-slot capture."""
    from infrastructure.owned_io import SafeRoot
    from domains.intraday_research import load_intraday_binding, _commit
    module = "ops.run_intraday_research"
    try:
        if (request.mode.value != "LIVE"
                or request.scheduled_date != request.business_date
                or request.target_date != request.business_date):
            raise _v4_global(_v4_scope, 'ValueError')("intraday capture cannot backfill current quotes")
        config_path = _v4_global(_v4_scope, 'os').environ["V4_INTRADAY_CONFIG_PATH"]
        config_sha = _v4_global(_v4_scope, 'os').environ["V4_INTRADAY_CONFIG_SHA256"]
        source_sha = _v4_global(_v4_scope, 'os').environ["V4_INTRADAY_SOURCE_MANIFEST_SHA256"]
        binding = load_intraday_binding(_v4_global(_v4_scope, 'Path')(config_path), config_sha, source_sha)
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError')):
        return self._failure_result("v4_intraday_research", [module], "INTRADAY_BINDING_REFUSED")
    result = self._run(module, ["--date", request.business_date, "--slot", request.slot,
        "--config", config_path, "--config-sha256", config_sha,
        "--source-manifest-sha256", source_sha])
    if result["status"] != "SUCCEEDED":
        return self._classify_intraday_failure(result)
    try:
        payload = _v4_global(_v4_scope, 'json').loads(_v4_global(_v4_scope, 'str')(result.get("stdout") or ""))
        day = f"{request.business_date[:4]}-{request.business_date[4:6]}-{request.business_date[6:]}"
        slot = request.slot[:2] + ":" + request.slot[2:]
        _, proof = _commit(SafeRoot(_v4_global(_v4_scope, 'Path')(binding["state_root"]) / "intraday"), day, slot, expected_config=config_sha)
        if (payload.get("status") not in {"SUCCEEDED", "ALREADY_EXISTS"}
                or payload.get("date") != day or payload.get("slot") != slot
                or _v4_global(_v4_scope, 'any')(payload.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
                or _v4_global(_v4_scope, 'any')(payload.get(key) != proof[key] for key in ("artifact_sha256", "manifest_sha256", "receipt_sha256"))):
            raise _v4_global(_v4_scope, 'ValueError')("intraday result identity mismatch")
        result.update({"receipt_verified": True, "capture_status": payload["status"], "intraday_evidence": proof})
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError')):
        return self._failure_result("v4_intraday_research", [module], "INTRADAY_RECEIPT_VERIFICATION_FAILED")
    return result
