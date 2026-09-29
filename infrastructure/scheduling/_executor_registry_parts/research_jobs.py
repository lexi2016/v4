"""infrastructure.scheduling.executor_registry: research_jobs (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _FixedExecutorRegistry__hourly_research_body(_v4_scope, /, self, request):
    from infrastructure.scheduling.manager_close_executor import (
        _manager_close_1530, _manager_universe_dependency)
    if request.slot == "1530":
        if _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'getattr')(request.mode, "value", request.mode)) != "LIVE":
            raise _v4_global(_v4_scope, 'WorkloadExecutionError')({"status": "FAILED", "workload_id": "hourly_research",
                "failure_class": "INVALID_INPUT", "reason": "CAPTURE_LIVE_ONLY", "exit_code": 2,
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False})
        return _manager_close_1530(self, request)
    dependency = None
    if (request.slot == "1500" and _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'getattr')(request.mode, "value", request.mode)) == "LIVE"
            and not _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'getattr')(self, k, None) for k in
                        ("repair_date", "repair_slot", "repair_expected_old_input_sha256"))):
        dependency = _manager_universe_dependency(self, request)
    try:
        result = self._hourly_research_materials(request)
    except _v4_global(_v4_scope, 'WorkloadExecutionError') as exc:
        if dependency is not None: exc.result["manager_close_dependency"] = dependency
        raise
    if dependency is not None: result["manager_close_dependency"] = dependency
    return result


def _FixedExecutorRegistry__zsxq_0830_body(_v4_scope, /, self, request):
    modules = [
        "ops.run_zsxq_hourly_delta",
        "ops.collect_hourly_research_input",
        "ops.run_hourly_research",
    ]
    fetched = self._run(
        modules[0],
        [
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--date", request.business_date,
            "--slot", request.slot,
        ],
    )
    if fetched["status"] == "SUCCEEDED":
        try:
            decoded = _v4_global(_v4_scope, 'json').loads(_v4_global(_v4_scope, 'str')(fetched.get("stdout") or "{}"))
        except _v4_global(_v4_scope, 'json').JSONDecodeError:
            decoded = {}
        if decoded.get("status") not in {"READY", "READY_EMPTY"}:
            fetched["status"] = "FAILED"
            fetched["reason"] = "ZSXQ 08:30 did not produce a verified status"
    if fetched["status"] != "SUCCEEDED":
        fetched["workload_id"] = "zsxq_0830"
        fetched["modules"] = modules
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(fetched)
    collected = self._run(
        modules[1],
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
        workload_id="zsxq_0830",
        modules=modules,
        collector_payload=collected_payload,
    )
    if collector_failure is not None:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(collector_failure)
    if collected["status"] != "SUCCEEDED":
        collected["workload_id"] = "zsxq_0830"
        collected["modules"] = modules
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(collected)
    result = self._run(
        modules[2],
        [
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--date", request.business_date,
            "--target-date", request.business_date,
            "--slot", request.slot,
            "--mode", request.mode.value,
        ],
    )
    result["modules"] = modules
    return result


def _FixedExecutorRegistry__morning_news_0830_body(_v4_scope, /, self, request):
    module = "scripts.run_scheduled_morning_news"
    modules = [module]
    if self.shared_data_root is None or self.shared_package_root is None:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "morning_news_0830",
                modules,
                "shared data root and shared package root are required",
            )
        )
    entry = self.shared_package_root / "scripts" / "run_scheduled_morning_news.py"
    if not entry.is_file():
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "morning_news_0830",
                modules,
                "fixed shared morning-news entry is missing",
            )
        )
    environment = _v4_global(_v4_scope, 'os').environ.copy()
    environment["V3_SHARED_DATA_STORE_ROOT"] = _v4_global(_v4_scope, 'str')(self.shared_data_root)
    result = self._run(
        module,
        ["--trade-date", request.business_date],
        cwd=self.shared_package_root,
        env=environment,
    )
    result["modules"] = modules
    return result


def _FixedExecutorRegistry__safe_lane_status_body(_v4_scope, /, payload):
    """Reduce an evidence adapter result without converting gaps to READY."""
    statuses: list[str] = []
    lanes = payload.get("lanes")
    if _v4_global(_v4_scope, 'isinstance')(lanes, _v4_global(_v4_scope, 'dict')):
        statuses.extend(
            _v4_global(_v4_scope, 'str')(item.get("status") or "CANNOT_CONFIRM").upper()
            for item in lanes.values()
            if _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'dict'))
        )
    direct = _v4_global(_v4_scope, 'str')(payload.get("status") or payload.get("overall_status") or "").upper()
    if direct:
        statuses.append(direct)
    if _v4_global(_v4_scope, 'any')(item in {"CANNOT_CONFIRM", "FAILED", "REJECTED", "FAIL"} for item in statuses):
        return "CANNOT_CONFIRM"
    if _v4_global(_v4_scope, 'any')(item in {"PARTIAL", "PARTIAL_WITH_ROWS", "EVIDENCE_GAP"} for item in statuses):
        return "PARTIAL"
    # An empty or malformed publisher envelope is not evidence of a ready
    # lane.  Keep it retryable/fail-closed rather than allowing a missing
    # producer receipt to become a successful scheduler ledger entry.
    return "CANNOT_CONFIRM"


def _FixedExecutorRegistry__run_close_review_node_body(_v4_scope, /, self, workload, request):
    node = _v4_global(_v4_scope, 'CLOSE_NODE_BY_WORKLOAD')[workload.workload_id]
    arguments = [
        "--node", node,
        "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
        "--business-date", request.business_date,
    ]
    if self.selector_data_root is not None:
        arguments.extend(["--selector-data-root", _v4_global(_v4_scope, 'str')(self.selector_data_root)])
    result = self._run("ops.run_v35_close_review_slot", arguments)
    result["modules"] = ["ops.run_v35_close_review_slot"]
    return result


def _FixedExecutorRegistry__failure_result_body(_v4_scope, /, self, workload_id, modules, message):
    return {
        "status": "FAILED",
        "workload_id": workload_id,
        "modules": modules,
        "exit_code": 1,
        "stdout": "",
        "stderr": message,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
