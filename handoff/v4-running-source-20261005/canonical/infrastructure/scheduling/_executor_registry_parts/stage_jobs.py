"""infrastructure.scheduling.executor_registry: stage_jobs (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _FixedExecutorRegistry__stage_workbench_body(_v4_scope, /, self, request):
    if self.shared_data_root is None:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "stage_workbench",
                ["ops.materialize_stage_workbench"],
                "shared data root not configured",
            )
        )
    try:
        stage_id = _v4_global(_v4_scope, 'STAGE_BY_SLOT')[request.slot]
    except _v4_global(_v4_scope, 'KeyError') as error:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "stage_workbench",
                ["ops.materialize_stage_workbench"],
                f"unknown stage slot: {request.slot}",
            )
        ) from error
    modules = ["ops.materialize_stage_workbench"]
    result = self._run(
        "ops.materialize_stage_workbench",
        [
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--date", request.business_date,
            "--stage", stage_id,
            "--shared-data-root", _v4_global(_v4_scope, 'str')(self.shared_data_root),
            *(
                ["--shared-package-root", _v4_global(_v4_scope, 'str')(self.shared_package_root)]
                if self.shared_package_root is not None
                else []
            ),
        ],
    )
    result["modules"] = modules
    capture_mode = _v4_global(_v4_scope, 'os').environ.get(
        "V4_MANAGER_CLOSE_CAPTURE_MODE", ""
    ).strip()
    request_mode = _v4_global(_v4_scope, 'str')(
        _v4_global(_v4_scope, 'getattr')(request.mode, "value", request.mode)
    )
    if (request.slot == "1555" and stage_id == "STAGE_1545_1555"
            and capture_mode == "PYTDX_LATE_OBSERVATION"
            and request_mode == "LIVE"):
        from infrastructure.scheduling.manager_close_executor import (
            _manager_close_recapture_after_stage_workbench,
        )
        try:
            recapture = _manager_close_recapture_after_stage_workbench(
                self, request, stage_result=result
            )
        except _v4_global(_v4_scope, 'WorkloadExecutionError') as error:
            if result.get("status") == "SUCCEEDED" and result.get("exit_code") == 0:
                raise
            result["manager_close_recapture"] = {
                "status": "FAILED",
                "failure": dict(error.result),
            }
            result["modules"] = [*modules, "ops.materialize_manager_close_discovery"]
            return result
        result["manager_close_recapture"] = recapture
        result["modules"] = [*modules, "ops.materialize_manager_close_discovery"]
    return result


def _FixedExecutorRegistry__hk_auction_0920_body(_v4_scope, /, self, request):
    """Run the single-owner shared capture plus V3.5 materialization bridge."""
    security_module = "ops.ensure_hk_security_master"
    capture_module = "ops.run_hkconnect_0915_0920_capture"
    modules = [security_module, capture_module]
    if (
        self.shared_data_root is None
        or self.hk_universe_root is None
        or self.shared_package_root is None
    ):
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "hk_auction_0920",
                modules,
                "shared data root, HK universe root, and shared package root are required",
            )
        )
    security_entry = (self.repo_root or _v4_global(_v4_scope, 'Path').cwd()) / "ops" / "ensure_hk_security_master.py"
    if not security_entry.is_file():
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "hk_auction_0920",
                modules,
                "fixed HK security-master entry missing",
            )
        )
    environment = _v4_global(_v4_scope, 'os').environ.copy()
    environment["V3_SHARED_DATA_STORE_ROOT"] = _v4_global(_v4_scope, 'str')(self.shared_data_root)
    environment["V3_SHARED_FUTU_PYTHON"] = _v4_global(_v4_scope, 'str')(self.shared_futu_python_executable)
    security_result = self._run(
        security_module,
        [
            "--store-root", _v4_global(_v4_scope, 'str')(self.shared_data_root),
            "--universe-root", _v4_global(_v4_scope, 'str')(self.hk_universe_root),
            "--shared-package-root", _v4_global(_v4_scope, 'str')(self.shared_package_root),
            "--trade-date", request.business_date,
            "--futu-python", _v4_global(_v4_scope, 'str')(self.shared_futu_python_executable),
        ],
        env=environment,
    )
    if security_result["status"] != "SUCCEEDED":
        security_result["modules"] = modules
        security_result["workload_id"] = "hk_auction_0920"
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(security_result)
    result = self._run(
        capture_module,
        [
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--shared-data-root", _v4_global(_v4_scope, 'str')(self.shared_data_root),
            "--shared-package-root", _v4_global(_v4_scope, 'str')(self.shared_package_root),
            "--trade-date", request.business_date,
            "--futu-python", _v4_global(_v4_scope, 'str')(self.shared_futu_python_executable),
        ],
        env=environment,
        timeout_seconds=_v4_global(_v4_scope, '_HK_AUCTION_0920_TIMEOUT_SECONDS'),
    )
    result["modules"] = modules
    result["workload_id"] = "hk_auction_0920"
    if result["status"] != "SUCCEEDED":
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(result)
    return result


def _FixedExecutorRegistry__run_stage_center_milestone_body(_v4_scope, /, self, workload, request):
    if self.stage_selection_root is None:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                workload.workload_id,
                ["ops.run_stage_center_milestone"],
                "stage selection root not configured",
            )
        )
    node, stage_id, _market = _v4_global(_v4_scope, 'MILESTONE_BY_WORKLOAD')[workload.workload_id]
    result = self._run(
        "ops.run_stage_center_milestone",
        [
            "--node", node,
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--date", request.business_date,
            "--stage-id", stage_id,
            "--selection-root", _v4_global(_v4_scope, 'str')(self.stage_selection_root),
        ],
    )
    result["modules"] = ["ops.run_stage_center_milestone"]
    # The enabled 15:55 owner is fupan_review_start. Keep its same-date PyTDX
    # recapture independent of Stage readback: a Stage failure still triggers
    # the existing recapture helper, and cannot be turned green by its result.
    request_mode = _v4_global(_v4_scope, 'str')(
        _v4_global(_v4_scope, 'getattr')(request.mode, "value", request.mode)
    )
    if (workload.workload_id == "fupan_review_start" and request.slot == "1555"
            and request_mode == "LIVE"):
        stage_status = result.get("status")
        stage_exit_code = result.get("exit_code")
        result["stage_readback_status"] = stage_status
        result["stage_readback_exit_code"] = stage_exit_code
        try:
            from infrastructure.scheduling.manager_close_executor import (
                _manager_close_recapture_after_stage_workbench,
            )

            recapture = _manager_close_recapture_after_stage_workbench(
                self, request, stage_result=result
            )
        except _v4_global(_v4_scope, 'WorkloadExecutionError') as error:
            recapture = dict(error.result)
            recapture["workload_id"] = "manager_close_recapture"
            result["manager_close_recapture"] = recapture
            result["manager_close_recapture_status"] = recapture.get("status", "FAILED")
            result["modules"] = [
                "ops.run_stage_center_milestone",
                "ops.materialize_manager_close_discovery",
            ]
            if stage_status == "SUCCEEDED":
                result.update({
                    "status": "FAILED",
                    "exit_code": recapture.get("exit_code", 2),
                    "failure_class": recapture.get("failure_class", "UPSTREAM_NOT_READY"),
                    "reason": "MANAGER_PYTDX_RECAPTURE_FAILED",
                })
            return result
        result["manager_close_recapture"] = recapture
        result["manager_close_recapture_status"] = recapture.get("status")
        result["modules"] = [
            "ops.run_stage_center_milestone",
            "ops.materialize_manager_close_discovery",
        ]
    return result
