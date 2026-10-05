"""infrastructure.scheduling.executor_registry: research_materials (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _FixedExecutorRegistry__hourly_research_materials_body(_v4_scope, /, self, request):
    refresh_zsxq = _v4_global(_v4_scope, 'int')(request.slot) >= 900
    zsxq_refresh_failure: dict[str, Any] | None = None
    modules = [
        *(["ops.run_zsxq_hourly_delta"] if refresh_zsxq else []),
        "ops.materialize_research_peripherals",
        "ops.collect_hourly_research_input",
        "ops.run_hourly_research",
    ]
    if refresh_zsxq:
        zsxq = self._run(
            modules[0],
            [
                "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
                "--date", request.business_date,
                "--slot", request.slot,
            ],
        )
        if zsxq["status"] == "SUCCEEDED":
            try:
                decoded = _v4_global(_v4_scope, 'json').loads(_v4_global(_v4_scope, 'str')(zsxq.get("stdout") or "{}"))
            except _v4_global(_v4_scope, 'json').JSONDecodeError:
                decoded = {}
            if decoded.get("status") not in {"READY", "READY_EMPTY"}:
                zsxq["status"] = "FAILED"
                zsxq["reason"] = "paginated ZSXQ delta did not verify"
        if zsxq["status"] != "SUCCEEDED":
            zsxq_refresh_failure = _v4_global(_v4_scope, 'dict')(zsxq)
    peripheral_module = "ops.materialize_research_peripherals"
    peripherals = self._run(
        peripheral_module,
        [
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--trade-date", request.business_date,
            "--source", "both",
            "--reuse-existing",
            "--timeout", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_PERIPHERAL_FETCH_TIMEOUT_SECONDS')),
        ],
    )
    degraded_inputs = _v4_global(_v4_scope, '_audited_peripheral_degradation')(
        peripherals,
        data_root=self.data_root,
        trade_date=request.business_date,
    )
    if peripherals["status"] == "TIMEOUT" and degraded_inputs is None:
        degraded_inputs = _v4_global(_v4_scope, '_audited_peripheral_timeout_reuse')(
            data_root=self.data_root,
            trade_date=request.business_date,
        )
    if peripherals["status"] != "SUCCEEDED":
        if degraded_inputs is not None:
            peripherals["degraded_inputs"] = degraded_inputs
        else:
            peripherals["workload_id"] = "hourly_research"
            peripherals["modules"] = modules
            raise _v4_global(_v4_scope, 'WorkloadExecutionError')(peripherals)
    collected = self._run(
        "ops.collect_hourly_research_input",
        [
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--date", request.business_date,
            "--slot", request.slot,
        ],
    )
    try:
        collected_payload = _v4_global(_v4_scope, 'json').loads(_v4_global(_v4_scope, 'str')(collected.get("stdout") or "{}"))
    except _v4_global(_v4_scope, 'json').JSONDecodeError:
        collected_payload = {}
    collector_failure = _v4_global(_v4_scope, '_collector_not_materialized_result')(
        collected,
        workload_id="hourly_research",
        modules=modules,
        collector_payload=collected_payload,
    )
    if collector_failure is not None and zsxq_refresh_failure is None:
        if degraded_inputs is not None:
            collector_failure["degraded_inputs"] = degraded_inputs
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(collector_failure)
    if collected["status"] != "SUCCEEDED":
        if degraded_inputs is not None:
            collected["degraded_inputs"] = degraded_inputs
        collected["workload_id"] = "hourly_research"
        collected["modules"] = modules
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(collected)
    zsxq_degraded_input: dict[str, Any] | None = None
    if zsxq_refresh_failure is not None:
        fallback_row_count = collected_payload.get("row_count")
        verified_same_day_rows = (
            collected_payload.get("status") == "READY_WITH_RESEARCH_POOL"
            and _v4_global(_v4_scope, 'type')(fallback_row_count) is _v4_global(_v4_scope, 'int')
            and fallback_row_count > 0
        )
        if not verified_same_day_rows:
            failure = _v4_global(_v4_scope, 'dict')(zsxq_refresh_failure)
            failure.update(
                {
                    "workload_id": "hourly_research",
                    "modules": modules,
                    "reason": "ZSXQ_REFRESH_FAILED_NO_VERIFIED_SAME_DAY_INPUT",
                }
            )
            raise _v4_global(_v4_scope, 'WorkloadExecutionError')(failure)
        zsxq_degraded_input = {
            "reason": "ZSXQ_REFRESH_FAILED_REUSED_VERIFIED_SAME_DAY_INPUT",
            "refresh_exit_code": _v4_global(_v4_scope, 'int')(zsxq_refresh_failure.get("exit_code") or 0),
            "fallback_row_count": fallback_row_count,
            "fallback_source_path": _v4_global(_v4_scope, 'str')(
                collected_payload.get("source_path") or ""
            ),
        }
    if collector_failure is not None:
        if degraded_inputs is not None:
            collector_failure["degraded_inputs"] = degraded_inputs
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(collector_failure)
    run_arguments = [
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--date", request.business_date,
            "--target-date", request.business_date,
            "--slot", request.slot,
            "--mode", request.mode.value,
    ]
    if collected_payload.get("recovery") is True:
        recovery_relative = _v4_global(_v4_scope, 'str')(collected_payload.get("source_path") or "")
        recovery_path = _v4_global(_v4_scope, 'resolve_owned_path')(self.data_root, recovery_relative)
        run_arguments.extend(["--source", _v4_global(_v4_scope, 'str')(recovery_path)])
    result = self._run(
        "ops.run_hourly_research",
        run_arguments,
    )
    result["modules"] = modules
    if degraded_inputs is not None:
        result["degraded_inputs"] = degraded_inputs
    if zsxq_degraded_input is not None:
        result["zsxq_degraded_input"] = zsxq_degraded_input
    retryable_sources: list[str] = []
    if zsxq_degraded_input is not None:
        retryable_sources.append("zsxq")
    if degraded_inputs is not None:
        external_finance = _v4_global(_v4_scope, 'next')(
            (
                source
                for source in degraded_inputs.get("sources", [])
                if source.get("source") == "external_finance"
            ),
            None,
        )
        if (
            external_finance is not None
            and external_finance.get("status") == "CANNOT_CONFIRM"
            and external_finance.get("item_count") == 0
            and _v4_global(_v4_scope, 'any')(
                _v4_global(_v4_scope, 'str')(gap).startswith("EXTERNAL_FINANCE_FETCH_FAILED:")
                for gap in external_finance.get("cannot_confirm", [])
            )
        ):
            retryable_sources.append("external_finance")
    if result.get("status") == "SUCCEEDED" and retryable_sources:
        result.update(
            {
                "status": "FAILED",
                "workload_id": "hourly_research",
                "reason": "RESEARCH_SOURCE_REFRESH_RETRY_REQUIRED",
                "retryable_sources": _v4_global(_v4_scope, 'sorted')(retryable_sources),
                "hourly_artifact_status": "SUCCEEDED",
            }
        )
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(result)
    return result
