"""Research-lane executor handlers.

The facade rebinds these functions into its historical class interface.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from contracts.runtime_tasks import DispatchRequest, WorkloadDefinition
from infrastructure.owned_path import resolve_owned_path
from ops.daily_materialize import resolve_selector_panel
from ops.us_market_digest import (
    resolve_capture_for_shanghai_slot,
    us_market_day_certification,
)

_PERIPHERAL_FETCH_TIMEOUT_SECONDS = 10
_HK_AUCTION_0920_TIMEOUT_SECONDS = 420


def _repair_requested(registry: Any) -> bool:
    return any(
        getattr(registry, field, None) is not None
        for field in (
            "repair_date",
            "repair_slot",
            "repair_expected_old_input_sha256",
        )
    )


def _repair_collector_arguments(
    registry: Any, request: DispatchRequest
) -> list[str]:
    """Return the one-shot repair flag only for the hourly collector."""

    if not _repair_requested(registry):
        return []
    repair_date = getattr(registry, "repair_date", None)
    repair_slot = getattr(registry, "repair_slot", None)
    expected_sha = getattr(registry, "repair_expected_old_input_sha256", None)
    if not all(
        isinstance(value, str) and value.strip()
        for value in (repair_date, repair_slot, expected_sha)
    ):
        raise ValueError("REPAIR_AUTH_INCOMPLETE")
    if repair_date != request.business_date or repair_slot != request.slot:
        raise ValueError("REPAIR_AUTH_DATE_SLOT_MISMATCH")
    if request.slot in {"0700", "0800"}:
        raise ValueError("REPAIR_SLOT_UNSUPPORTED")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha):
        raise ValueError("REPAIR_EXPECTED_SOURCE_SHA_INVALID")
    return ["--repair-expected-old-input-sha256", expected_sha.lower()]


def _hourly_research(
    self, request: DispatchRequest
) -> dict[str, Any]:
    if request.slot == "1530":
        # The facade rebinds this function's globals; keep the new helper an
        # explicit local import from the actual split module, not a new facade.
        from infrastructure.scheduling.executor_registry_research import _manager_close_1530
        return _manager_close_1530(self, request)
    manager_dependency = None
    if (request.slot == "1500" and not _repair_requested(self)
        and str(getattr(request.mode, "value", request.mode)) == "LIVE"):
        from infrastructure.scheduling.executor_registry_research import _manager_universe_dependency
        manager_dependency = _manager_universe_dependency(self, request)
    # The V3 hourly owner had no legal ZSXQ input before the dedicated 08:30
    # refresh.  Keep those two historical heartbeat slots visible as
    # successful no-ops instead of asking the collector to publish an empty
    # source and turning that expected state into a retryable failure.  The
    # first real source-producing path remains the independent 08:30 owner.
    if request.slot in {"0700", "0800"}:
        if _repair_requested(self):
            _repair_collector_arguments(self, request)
        return {
            "status": "SUCCEEDED",
            "slot": request.slot,
            "modules": [],
            "exit_code": 0,
            "no_op": True,
            "source_status": "EXPECTED_EMPTY",
            "skip_reason": "HOURLY_RESEARCH_NOT_SCHEDULED_BEFORE_ZSXQ_0830",
            "row_count": 0,
            "hourly_artifact_status": "NOT_SCHEDULED",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    repair_arguments = _repair_collector_arguments(self, request)
    refresh_zsxq = int(request.slot) >= 900
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
                "--data-root", str(self.data_root),
                "--date", request.business_date,
                "--slot", request.slot,
            ],
        )
        if zsxq["status"] == "SUCCEEDED":
            try:
                decoded = json.loads(str(zsxq.get("stdout") or "{}"))
            except json.JSONDecodeError:
                decoded = {}
            if decoded.get("status") not in {"READY", "READY_EMPTY"}:
                zsxq["status"] = "FAILED"
                zsxq["reason"] = "paginated ZSXQ delta did not verify"
        if zsxq["status"] != "SUCCEEDED":
            zsxq_refresh_failure = dict(zsxq)
    peripheral_module = "ops.materialize_research_peripherals"
    peripherals = self._run(
        peripheral_module,
        [
            "--data-root", str(self.data_root),
            "--trade-date", request.business_date,
            "--source", "both",
            "--reuse-existing",
            "--timeout", str(_PERIPHERAL_FETCH_TIMEOUT_SECONDS),
        ],
    )
    degraded_inputs = _audited_peripheral_degradation(
        peripherals,
        data_root=self.data_root,
        trade_date=request.business_date,
    )
    fresh_revalidation_attempted = False
    if degraded_inputs is None:
        # A stale CANNOT_CONFIRM peripheral can make the reuse-only attempt
        # fail before the materializer emits its authoritative code-2 summary.
        # Retry that one typed diagnostic through the original fresh producer;
        # its exit-0 success or independently audited exit-2 summary is the
        # only state allowed to continue. Every other fresh result remains a
        # hard workload failure below.
        diagnostic_lines = [
            line.strip()
            for value in (
                peripherals.get("stderr"),
                peripherals.get("error"),
                peripherals.get("stdout"),
            )
            if value not in {None, ""}
            for line in str(value).splitlines()
            if line.strip()
        ]
        missing_revalidation = (
            peripherals.get("status") == "FAILED"
            and peripherals.get("exit_code") == 1
            and any(
                line == "ValueError: research peripheral revalidation receipt is missing"
                for line in diagnostic_lines
            )
        )
        if missing_revalidation:
            fresh_revalidation_attempted = True
            peripherals = self._run(
                peripheral_module,
                [
                    "--data-root", str(self.data_root),
                    "--trade-date", request.business_date,
                    "--source", "both",
                    "--timeout", str(_PERIPHERAL_FETCH_TIMEOUT_SECONDS),
                ],
            )
            degraded_inputs = _audited_peripheral_degradation(
                peripherals,
                data_root=self.data_root,
                trade_date=request.business_date,
            )
    if (
        peripherals["status"] == "TIMEOUT"
        and degraded_inputs is None
        and not fresh_revalidation_attempted
    ):
        degraded_inputs = _audited_peripheral_timeout_reuse(
            data_root=self.data_root,
            trade_date=request.business_date,
        )
    if peripherals["status"] != "SUCCEEDED":
        if degraded_inputs is not None:
            peripherals["degraded_inputs"] = degraded_inputs
        else:
            peripherals["workload_id"] = "hourly_research"
            peripherals["modules"] = modules
            if manager_dependency is not None:
                peripherals["manager_close_dependency"] = manager_dependency
            raise WorkloadExecutionError(peripherals)
    collected = self._run(
        "ops.collect_hourly_research_input",
        [
            "--data-root", str(self.data_root),
            "--date", request.business_date,
            "--slot", request.slot,
        ]
        + repair_arguments,
    )
    try:
        collected_payload = json.loads(str(collected.get("stdout") or "{}"))
    except json.JSONDecodeError:
        collected_payload = {}
    collector_failure = _collector_not_materialized_result(
        collected,
        workload_id="hourly_research",
        modules=modules,
        collector_payload=collected_payload,
    )
    if collector_failure is not None and zsxq_refresh_failure is None:
        if degraded_inputs is not None:
            collector_failure["degraded_inputs"] = degraded_inputs
        if manager_dependency is not None:
            collector_failure["manager_close_dependency"] = manager_dependency
        raise WorkloadExecutionError(collector_failure)
    if collected["status"] != "SUCCEEDED":
        if degraded_inputs is not None:
            collected["degraded_inputs"] = degraded_inputs
        collected["workload_id"] = "hourly_research"
        collected["modules"] = modules
        if manager_dependency is not None:
            collected["manager_close_dependency"] = manager_dependency
        raise WorkloadExecutionError(collected)
    if _repair_requested(self):
        if collected_payload.get("recovery") is not True:
            raise ValueError("REPAIR_RECOVERY_NOT_CREATED")
    recovery_path: Path | None = None
    if collected_payload.get("recovery") is True:
        recovery_relative = collected_payload.get("source_path")
        if not isinstance(recovery_relative, str) or not recovery_relative.strip():
            raise ValueError("REPAIR_RECOVERY_SOURCE_INVALID")
        try:
            recovery_path = resolve_owned_path(self.data_root, recovery_relative)
        except ValueError as error:
            raise ValueError("REPAIR_RECOVERY_SOURCE_INVALID") from error
        if _repair_requested(self):
            recovery_sha = collected_payload.get("source_sha256")
            if not isinstance(recovery_sha, str) or not re.fullmatch(
                r"[0-9a-fA-F]{64}", recovery_sha
            ):
                raise ValueError("REPAIR_RECOVERY_SOURCE_SHA_INVALID")
            try:
                recovery_payload = json.loads(
                    recovery_path.read_text(encoding="utf-8-sig")
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("REPAIR_RECOVERY_SOURCE_INVALID") from error
            if not isinstance(recovery_payload, dict):
                raise ValueError("REPAIR_RECOVERY_SOURCE_INVALID")
            recovery_gaps = recovery_payload.get("cannot_confirm")
            has_late_recovery_gap = isinstance(recovery_gaps, list) and any(
                isinstance(gap, dict)
                and gap.get("reason") == "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"
                for gap in recovery_gaps
            )
            try:
                # This module is rebound into the fixed executor facade at
                # import time, so keep the existing store validator as a local
                # import rather than relying on this module's globals being
                # copied.
                from infrastructure.research_store import (
                    validate_hourly_recovery_provenance,
                )

                validate_hourly_recovery_provenance(
                    data_root=self.data_root,
                    archive_date=request.business_date,
                    slot=request.slot,
                    recovery_path=recovery_path,
                    recovery_sha256=recovery_sha,
                    recovery_payload=recovery_payload,
                    expected_source_sha256=self.repair_expected_old_input_sha256,
                    require_explicit_authorization=not has_late_recovery_gap,
                )
            except ValueError as error:
                raise ValueError("REPAIR_RECOVERY_PROVENANCE_INVALID") from error
    zsxq_degraded_input: dict[str, Any] | None = None
    if zsxq_refresh_failure is not None:
        fallback_row_count = collected_payload.get("row_count")
        verified_same_day_rows = (
            collected_payload.get("status") == "READY_WITH_RESEARCH_POOL"
            and type(fallback_row_count) is int
            and fallback_row_count > 0
        )
        if not verified_same_day_rows:
            failure = dict(zsxq_refresh_failure)
            failure.update(
                {
                    "workload_id": "hourly_research",
                    "modules": modules,
                    "reason": "ZSXQ_REFRESH_FAILED_NO_VERIFIED_SAME_DAY_INPUT",
                }
            )
            if manager_dependency is not None:
                failure["manager_close_dependency"] = manager_dependency
            raise WorkloadExecutionError(failure)
        zsxq_degraded_input = {
            "reason": "ZSXQ_REFRESH_FAILED_REUSED_VERIFIED_SAME_DAY_INPUT",
            "refresh_exit_code": int(zsxq_refresh_failure.get("exit_code") or 0),
            "fallback_row_count": fallback_row_count,
            "fallback_source_path": str(
                collected_payload.get("source_path") or ""
            ),
        }
    if collector_failure is not None:
        if degraded_inputs is not None:
            collector_failure["degraded_inputs"] = degraded_inputs
        if manager_dependency is not None:
            collector_failure["manager_close_dependency"] = manager_dependency
        raise WorkloadExecutionError(collector_failure)
    run_arguments = [
            "--data-root", str(self.data_root),
            "--date", request.business_date,
            "--target-date", request.business_date,
            "--slot", request.slot,
            "--mode", request.mode.value,
    ]
    if recovery_path is not None:
        run_arguments.extend(["--source", str(recovery_path)])
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
        external_finance = next(
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
            and any(
                str(gap).startswith("EXTERNAL_FINANCE_FETCH_FAILED:")
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
                "retryable_sources": sorted(retryable_sources),
                "hourly_artifact_status": "SUCCEEDED",
            }
        )
        if manager_dependency is not None:
            result["manager_close_dependency"] = manager_dependency
        raise WorkloadExecutionError(result)
    if manager_dependency is not None:
        result["manager_close_dependency"] = manager_dependency
    return result

def _us_market_digest(
    self, request: DispatchRequest
) -> dict[str, Any]:
    """Run only the seasonal US capture slot that is due now.

        Both DST variants are present in the catalog so launchd can remain a
        fixed-slot scheduler.  The explicit timezone resolver selects one
        active five-minute window; the other variant is a successful no-op and
        therefore cannot overwrite a same-session phase.
        """
    module = "ops.us_market_digest"
    try:
        capture = resolve_capture_for_shanghai_slot(
            request.business_date,
            request.slot,
        )
    except ValueError as error:
        if str(error) == "US_CAPTURE_SLOT_NOT_DUE":
            return {
                "status": "SUCCEEDED",
                "modules": [module],
                "exit_code": 0,
                "capture_status": "NOT_DUE",
                "capture_slot": request.slot,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        failure = self._failure_result(
            "us_market_digest",
            [module],
            str(error),
        )
        failure["failure_class"] = "INVALID_INPUT"
        raise WorkloadExecutionError(failure) from error

    market_day = us_market_day_certification(capture["us_session_date"])
    if market_day["reason"] == "US_MARKET_WEEKEND_UNCERTIFIED":
        return {
            "status": "SUCCEEDED",
            "modules": [module],
            "exit_code": 0,
            "capture_status": "CANNOT_CONFIRM",
            "capture_phase": capture["capture_phase"],
            "us_session_date": capture["us_session_date"],
            "market_day_status": market_day["status"],
            "market_day_reason": market_day["reason"],
            "cannot_confirm": [market_day["reason"]],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    result = self._run(
        module,
        [
            "--data-root", str(self.data_root),
            "--trade-date", capture["us_session_date"],
            "--capture-phase", capture["capture_phase"],
            "--timeout", str(_PERIPHERAL_FETCH_TIMEOUT_SECONDS),
        ],
    )
    result["modules"] = [module]
    result["capture_phase"] = capture["capture_phase"]
    result["us_session_date"] = capture["us_session_date"]
    result["market_day_status"] = market_day["status"]
    result["market_day_reason"] = market_day["reason"]
    result["cannot_confirm"] = [market_day["reason"]]
    if result["status"] != "SUCCEEDED":
        result["failure_class"] = "EXTERNAL_SOURCE"
        result["reason"] = "US_MARKET_CAPTURE_FAILED"
        raise WorkloadExecutionError(result)
    try:
        payload = json.loads(str(result.get("stdout") or "{}"))
    except json.JSONDecodeError as error:
        result.update(
            {
                "status": "FAILED",
                "failure_class": "CONTRACT",
                "reason": "US_MARKET_CAPTURE_INVALID_RESULT",
            }
        )
        raise WorkloadExecutionError(result) from error
    if not isinstance(payload, dict) or payload.get("status") not in {
        "READY",
        "READY_EMPTY",
    }:
        result.update(
            {
                "status": "FAILED",
                "failure_class": "UPSTREAM_NOT_READY",
                "reason": "US_MARKET_CAPTURE_NOT_READY",
                "capture_status": payload.get("status") if isinstance(payload, dict) else None,
            }
        )
        raise WorkloadExecutionError(result)
    result.update(
        {
            "capture_status": payload["status"],
            "payload_path": payload.get("payload_path"),
            "payload_sha256": payload.get("payload_sha256"),
            "capture_origin": payload.get("capture_origin"),
            "original_time_capture": payload.get("original_time_capture"),
        }
    )
    return result

def _zsxq_0830(self, request: DispatchRequest) -> dict[str, Any]:
    modules = [
        "ops.run_zsxq_hourly_delta",
        "ops.collect_hourly_research_input",
        "ops.run_hourly_research",
    ]
    fetched = self._run(
        modules[0],
        [
            "--data-root", str(self.data_root),
            "--date", request.business_date,
            "--slot", request.slot,
        ],
    )
    if fetched["status"] == "SUCCEEDED":
        try:
            decoded = json.loads(str(fetched.get("stdout") or "{}"))
        except json.JSONDecodeError:
            decoded = {}
        if decoded.get("status") not in {"READY", "READY_EMPTY"}:
            fetched["status"] = "FAILED"
            fetched["reason"] = "ZSXQ 08:30 did not produce a verified status"
    if fetched["status"] != "SUCCEEDED":
        fetched["workload_id"] = "zsxq_0830"
        fetched["modules"] = modules
        raise WorkloadExecutionError(fetched)
    collected = self._run(
        modules[1],
        [
            "--data-root", str(self.data_root),
            "--date", request.business_date,
            "--slot", request.slot,
        ],
    )
    try:
        collected_payload = json.loads(str(collected.get("stdout") or "{}"))
    except json.JSONDecodeError:
        collected_payload = {}
    collector_failure = _collector_not_materialized_result(
        collected,
        workload_id="zsxq_0830",
        modules=modules,
        collector_payload=collected_payload,
    )
    if collector_failure is not None:
        raise WorkloadExecutionError(collector_failure)
    if collected["status"] != "SUCCEEDED":
        collected["workload_id"] = "zsxq_0830"
        collected["modules"] = modules
        raise WorkloadExecutionError(collected)
    result = self._run(
        modules[2],
        [
            "--data-root", str(self.data_root),
            "--date", request.business_date,
            "--target-date", request.business_date,
            "--slot", request.slot,
            "--mode", request.mode.value,
        ],
    )
    result["modules"] = modules
    return result

def _morning_news_0830(self, request: DispatchRequest) -> dict[str, Any]:
    module = "scripts.run_scheduled_morning_news"
    modules = [module]
    if self.shared_data_root is None or self.shared_package_root is None:
        raise WorkloadExecutionError(
            self._failure_result(
                "morning_news_0830",
                modules,
                "shared data root and shared package root are required",
            )
        )
    entry = self.shared_package_root / "scripts" / "run_scheduled_morning_news.py"
    if not entry.is_file():
        raise WorkloadExecutionError(
            self._failure_result(
                "morning_news_0830",
                modules,
                "fixed shared morning-news entry is missing",
            )
        )
    environment = os.environ.copy()
    environment["V3_SHARED_DATA_STORE_ROOT"] = str(self.shared_data_root)
    result = self._run(
        module,
        ["--trade-date", request.business_date],
        cwd=self.shared_package_root,
        env=environment,
    )
    result["modules"] = modules
    return result

def _research_preselection_refresh(
    self, request: DispatchRequest
) -> dict[str, Any]:
    return self._run(
        "ops.refresh_research_preselection",
        [
            "--data-root", str(self.data_root),
            "--date", request.business_date,
        ],
    )

def _baimao_x_refresh(self, request: DispatchRequest) -> dict[str, Any]:
    return self._run(
        "ops.refresh_baimao_x_digest",
        [
            "--data-root", str(self.data_root),
            "--date", request.business_date,
            "--slot", request.slot,
        ],
    )

def _stage_workbench(
    self, request: DispatchRequest
) -> dict[str, Any]:
    if self.shared_data_root is None:
        raise WorkloadExecutionError(
            self._failure_result(
                "stage_workbench",
                ["ops.materialize_stage_workbench"],
                "shared data root not configured",
            )
        )
    try:
        stage_id = STAGE_BY_SLOT[request.slot]
    except KeyError as error:
        raise WorkloadExecutionError(
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
            "--data-root", str(self.data_root),
            "--date", request.business_date,
            "--stage", stage_id,
            "--shared-data-root", str(self.shared_data_root),
            *(
                ["--shared-package-root", str(self.shared_package_root)]
                if self.shared_package_root is not None
                else []
            ),
        ],
    )
    result["modules"] = modules
    capture_mode = os.environ.get("V4_MANAGER_CLOSE_CAPTURE_MODE", "").strip()
    if capture_mode and capture_mode != "PYTDX_LATE_OBSERVATION":
        raise WorkloadExecutionError({
            "status": "FAILED", "workload_id": "stage_workbench",
            "slot": request.slot, "modules": modules, "exit_code": 2,
            "failure_class": "INVALID_INPUT",
            "reason": "MANAGER_CLOSE_CAPTURE_MODE_INVALID",
            "stage_workbench_status": result.get("status"),
            "stage_workbench_exit_code": result.get("exit_code"),
            "production_allowed": False, "buy_gate_updated": False,
            "orders_sent": False,
        })
    if (capture_mode == "PYTDX_LATE_OBSERVATION" and request.slot == "1555"
            and str(getattr(request.mode, "value", request.mode)) == "LIVE"):
        from infrastructure.scheduling.executor_registry_research import (
            _manager_close_recapture_after_stage_workbench,
        )
        try:
            recapture = _manager_close_recapture_after_stage_workbench(
                self, request, stage_result=result
            )
        except WorkloadExecutionError as error:
            # The 15:55 Stage result remains authoritative. A recapture may
            # succeed after a Stage failure, but it may never upgrade that
            # Stage result or hide a separate recapture failure.
            if result.get("status") == "SUCCEEDED":
                raise
            result["stage_workbench_status"] = result.get("status")
            result["stage_workbench_exit_code"] = result.get("exit_code")
            result["manager_close_recapture"] = dict(error.result)
            return result
        result["manager_close_recapture"] = recapture
        result["stage_workbench_status"] = result.get("status")
        result["stage_workbench_exit_code"] = result.get("exit_code")
        if recapture.get("status") != "SUCCEEDED":
            failure = {
                "status": "FAILED", "workload_id": "stage_workbench",
                "slot": request.slot, "modules": modules,
                "exit_code": 2, "failure_class": "UPSTREAM_NOT_READY",
                "reason": "MANAGER_PYTDX_RECAPTURE_NOT_FULLY_MATERIALIZED",
                "stage_workbench_status": result.get("status"),
                "stage_workbench_exit_code": result.get("exit_code"),
                "manager_close_recapture": recapture,
                "production_allowed": False, "buy_gate_updated": False,
                "orders_sent": False,
            }
            raise WorkloadExecutionError(failure)
    return result

def _hk_auction_0920(self, request: DispatchRequest) -> dict[str, Any]:
    """Run the shared D-1-bound capture plus V3.5 materialization bridge.

    The capture entry owns the read-only verification of the exact-date
    canonical D-1 Top100 before it starts its single Futu capture.  The
    scheduler must not introduce a same-day full-market/security-master
    preflight, because that is a separate authority and is not an input to
    this 09:15 lane.
    """
    capture_module = "ops.run_hkconnect_0915_0920_capture"
    modules = [capture_module]
    if self.shared_data_root is None or self.shared_package_root is None:
        raise WorkloadExecutionError(
            self._failure_result(
                "hk_auction_0920",
                modules,
                "shared data root and shared package root are required",
            )
        )
    environment = os.environ.copy()
    environment["V3_SHARED_DATA_STORE_ROOT"] = str(self.shared_data_root)
    environment["V3_SHARED_FUTU_PYTHON"] = str(self.shared_futu_python_executable)
    configured_output_root = str(os.environ.get("V4_HK_AUCTION_OUTPUT_ROOT") or "").strip()
    if configured_output_root:
        output_root = Path(configured_output_root).expanduser()
        if not output_root.is_absolute():
            raise ValueError("V4_HK_AUCTION_OUTPUT_ROOT must be an absolute V4 state/data root")
        output_root = output_root.resolve()
        if (
            output_root.name != "data"
            or output_root.parent.name != "state"
            or output_root.parent.parent.name != "com.lexi.v4.local"
            or not output_root.is_dir()
        ):
            raise ValueError(
                "V4_HK_AUCTION_OUTPUT_ROOT must be an existing "
                "com.lexi.v4.local/state/data directory"
            )
    else:
        output_root = self.data_root
    result = self._run(
        capture_module,
        [
            "--data-root", str(output_root),
            "--shared-data-root", str(self.shared_data_root),
            "--shared-package-root", str(self.shared_package_root),
            "--trade-date", request.business_date,
            "--futu-python", str(self.shared_futu_python_executable),
        ],
        env=environment,
        timeout_seconds=_HK_AUCTION_0920_TIMEOUT_SECONDS,
    )
    result["modules"] = modules
    result["workload_id"] = "hk_auction_0920"
    result["output_root"] = str(output_root)
    if result["status"] != "SUCCEEDED":
        raise WorkloadExecutionError(result)
    return result



def _manager_universe_dependency(self: Any, request: DispatchRequest) -> dict[str, Any]:
    """Run inside existing 1500 hourly work; failure never stops sibling research."""
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError
    try:
        result = _manager_close_1530(self, request, prepare_only=True)
    except WorkloadExecutionError as exc:
        result = dict(exc.result)
    return {**result, 'dependency_phase': 'HK_UNIVERSE_PREPARE_ONLY',
            'snapshot_requested': False, 'candidate_publication_requested': False}

def _manager_close_1530(self: Any, request: DispatchRequest, *, prepare_only: bool = False) -> dict[str, Any]:
    """1530 only: the sole V4 materializer child, explicit roots and readback."""
    import hashlib
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError
    from infrastructure.manager_close_attempt import write_attempt

    module="ops.materialize_manager_close_discovery"
    flags={"RESEARCH_ONLY":True,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}
    configured_app=os.environ.get("V4_MANAGER_MATERIALIZER_APP_ROOT")
    configured_state=os.environ.get("V4_MANAGER_RESEARCH_STATE_ROOT")
    expected_child_sha = os.environ.get("V4_MANAGER_MATERIALIZER_SHA256", "")
    state=Path(configured_state).expanduser() if configured_state else None

    def fail(reason: str, child: dict[str, Any] | None = None, *, preserve_attempt: bool = False,
             diagnostic: dict | None = None, failure_class: str = "UPSTREAM_NOT_READY") -> None:
        # This is a non-data attempt receipt, never a second materializer.
        # An absent explicit state binding remains visible in the dispatcher
        # receipt; it must not be guessed from the V35 input root.
        if (not prepare_only and state is not None and state.is_absolute()
            and reason!="MANAGER_SLOT_LOCKED" and not preserve_attempt):
            try:
                write_attempt(state,request.business_date,"FAILED",reason,datetime.now(ZoneInfo("Asia/Hong_Kong")),diagnostic=diagnostic)
            except (ValueError,OSError):
                pass
        result={"status":"FAILED","workload_id":"hourly_research","slot":request.slot,
                "modules":[module],"exit_code":2,"failure_class":failure_class,
                "reason":reason,**flags}
        if re.fullmatch(r"[0-9a-f]{64}", expected_child_sha):
            result["materializer_expected_sha256"] = expected_child_sha
        if diagnostic is not None:
            result["failure_diagnostic"] = diagnostic
        if child:
            result["child_status"]=child.get("status")
            result["child_exit_code"]=child.get("exit_code")
        raise WorkloadExecutionError(result)

    capture_mode = os.environ.get("V4_MANAGER_CLOSE_CAPTURE_MODE", "").strip()
    if capture_mode and capture_mode != "PYTDX_LATE_OBSERVATION":
        fail("MANAGER_CLOSE_CAPTURE_MODE_INVALID", failure_class="INVALID_INPUT")
    if capture_mode == "PYTDX_LATE_OBSERVATION":
        if prepare_only and request.slot == "1500":
            return {"status": "SUCCEEDED", "slot": request.slot,
                    "modules": [module], "exit_code": 0, "no_op": True,
                    "reason": "FUTU_UNIVERSE_PREPARE_SKIPPED_BY_PYTDX_LATE_OBSERVATION_MODE",
                    "capture_mode": capture_mode, "snapshot_requested": False,
                    "candidate_publication_requested": False, **flags}
        if not prepare_only and request.slot == "1530":
            return {"status": "SUCCEEDED", "slot": request.slot,
                    "modules": [module], "exit_code": 0, "no_op": True,
                    "reason": "1530_CAPTURE_DISABLED_BY_PYTDX_LATE_OBSERVATION_MODE",
                    "capture_mode": capture_mode, **flags}
        fail("MANAGER_CLOSE_CAPTURE_SLOT_INVALID", failure_class="INVALID_INPUT")

    if not configured_app or state is None or not state.is_absolute():
        fail("MANAGER_EXPLICIT_BINDING_MISSING")
    app=Path(configured_app).expanduser()
    if not app.is_absolute(): fail("MANAGER_APP_ROOT_INVALID")
    app=app.resolve(); state=state.resolve()
    module_path=app/"ops/materialize_manager_close_discovery.py"
    for relative in ("ops/materialize_manager_close_discovery.py","apps/api/v35_api/app.py",
                     "apps/api/v35_api/manager_workbench_router.py","v4/manager_research/__init__.py"):
        if not (app/relative).is_file(): fail("MANAGER_APP_CLOSURE_MISSING")
    try:
        actual_child_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    except OSError:
        actual_child_sha = ""
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_child_sha)
            or actual_child_sha != expected_child_sha):
        fail("MANAGER_MATERIALIZER_SHA_MISMATCH",failure_class="INVALID_INPUT")
    if not getattr(self,"hk_universe_root",None) or not getattr(self,"shared_futu_python_executable",None):
        fail("MANAGER_EXISTING_DATA_BINDING_MISSING")
    owner_root = getattr(self, "repo_root", None)
    owner_sha = os.environ.get("V4_MANAGER_UNIVERSE_OWNER_SHA256", "")
    if (owner_root is None or not Path(owner_root).is_absolute()
        or not re.fullmatch(r"[0-9a-f]{64}", owner_sha)):
        fail("HK_UNIVERSE_OWNER_BINDING_REQUIRED",failure_class="INVALID_INPUT")
    owner_root = Path(owner_root).resolve()
    try:
        owner_path = resolve_owned_path(owner_root, "stage_center/hk_universe_preflight.py")
        actual_owner_sha = hashlib.sha256(owner_path.read_bytes()).hexdigest() if owner_path.is_file() else None
    except (ValueError, OSError):
        fail("HK_UNIVERSE_OWNER_BINDING_INVALID",failure_class="INVALID_INPUT")
    if actual_owner_sha != owner_sha:
        fail("HK_UNIVERSE_OWNER_SHA_MISMATCH",failure_class="INVALID_INPUT")
    env=dict(os.environ)
    env.update({"PYTHONPATH":os.pathsep.join(str(p) for p in (app,app/"upstreams",app/"upstreams/v3_shared_data")),
                "PYTHONNOUSERSITE":"1","PYTHONDONTWRITEBYTECODE":"1",
                "RESEARCH_ONLY":"true","PRODUCTION_ALLOWED":"false","BUY_GATE_UPDATED":"false","ORDERS_SENT":"false"})
    args=["--data-root",str(self.data_root),"--universe-root",str(self.hk_universe_root),
          "--futu-python",str(self.shared_futu_python_executable),"--trade-date",request.business_date,
          "--state-root",str(state),"--app-root",str(app),"--news-owner-root",str(self.repo_root),
          "--universe-owner-root",str(owner_root),"--universe-owner-sha256",owner_sha]
    rebound_root = os.environ.get('V4_CLOSE_REBOUND_AUTHORITY_ROOT')
    if not prepare_only and rebound_root:
        # No fallback to unrelated roots. The child checks closure before any
        # history witness; the original post-window guard still runs first.
        args.extend(['--rebound-authority-root', rebound_root])
    if prepare_only:
        args.append("--universe-only")
    try:
        child=self._run(module,args,cwd=app,env=env,**({"timeout_seconds":60} if prepare_only else {}))
    except (OSError, RuntimeError, ValueError):
        fail("MANAGER_CHILD_START_FAILED")
    if child.get("status")!="SUCCEEDED" or child.get("exit_code")!=0:
        try:
            failure_payload=json.loads(str(child.get("stdout") or ""))
        except (ValueError, TypeError):
            failure_payload={}
        identity_ok=(isinstance(failure_payload,dict)
            and failure_payload.get("schema_version")=="v4.manager_close_materialization_result.v1"
            and failure_payload.get("trade_date")==request.business_date and failure_payload.get("slot")=="1530"
            and failure_payload.get("state_root")==str(state)
            and failure_payload.get("module_origin")==str(module_path)
            and failure_payload.get("module_sha256")==expected_child_sha
            and failure_payload.get("module_sha256")==hashlib.sha256(module_path.read_bytes()).hexdigest()
            and all(failure_payload.get(k) is v for k,v in flags.items()))
        diagnostic = None
        if identity_ok and "failure_diagnostic" in failure_payload:
            from infrastructure.manager_close_attempt import validate_failure_diagnostic
            try:
                diagnostic = validate_failure_diagnostic(failure_payload["failure_diagnostic"])
                if diagnostic["code"] != failure_payload.get("reason"):
                    raise ValueError("reason mismatch")
            except ValueError:
                fail("MANAGER_CHILD_DIAGNOSTIC_INVALID",child,failure_class="INVALID_INPUT")
        child_class = "UPSTREAM_NOT_READY"
        if diagnostic is not None:
            if (diagnostic["layer"] == "CAPTURE_WINDOW" and diagnostic["kind"] == "EXPIRED"
                and diagnostic["code"] in {"EXACT_1530_SNAPSHOT_WINDOW_MISSED", "SNAPSHOT_RETURNED_AFTER_1530_WINDOW"}
                and failure_payload.get("terminal") is True and failure_payload.get("failure_class") == "NOT_DUE"):
                child_class = "NOT_DUE"
            elif diagnostic["kind"] in {"INVALID", "CONFLICT", "PIT_UNSAFE"}:
                child_class = "INVALID_INPUT"
        if prepare_only and identity_ok and diagnostic is not None:
            fail(diagnostic["code"],child,diagnostic=diagnostic,failure_class=child_class,preserve_attempt=True)
        if identity_ok and failure_payload.get("reason")=="MANAGER_SLOT_LOCKED":
            fail("MANAGER_SLOT_LOCKED",child)
        if identity_ok and failure_payload.get("status") in {"INPUT_MISSING","PENDING_SLOT","FAILED"}:
            try:
                attempt=json.loads(resolve_owned_path(state,f"workbench_research/{request.business_date}/1530.status.json").read_text())
                if (attempt.get("trade_date")==request.business_date and attempt.get("market")=="HK_CONNECT"
                    and attempt.get("slot")=="1530" and attempt.get("status")==failure_payload["status"]
                    and attempt.get("cannot_confirm")==[failure_payload.get("reason")]
                    and attempt.get("candidates")==[]
                    and attempt.get("priority_summary")=={"focus":[],"theme_changes":[],"risk_upgrades":[]}
                    and all(attempt.get(k) is v for k,v in flags.items())):
                    if diagnostic is not None and attempt.get("failure_diagnostic") != diagnostic:
                        fail("MANAGER_CHILD_DIAGNOSTIC_MISMATCH",child,failure_class="INVALID_INPUT")
                    fail(failure_payload["reason"],child,preserve_attempt=True,
                         diagnostic=diagnostic,failure_class=child_class)
            except (ValueError,TypeError,OSError):
                pass
        fail("MANAGER_CHILD_EXECUTION_FAILED",child)
    try:
        result=json.loads(str(child.get("stdout") or ""))
        if not isinstance(result,dict): raise ValueError
        if (result.get("schema_version")!="v4.manager_close_materialization_result.v1"
            or result.get("trade_date")!=request.business_date or result.get("slot")!="1530"
            or result.get("state_root")!=str(state)
            or result.get("module_origin")!=str(module_path)
            or result.get("module_sha256")!=expected_child_sha
            or result.get("module_sha256")!=hashlib.sha256(module_path.read_bytes()).hexdigest()
            or any(result.get(k) is not v for k,v in flags.items())): raise ValueError
        if prepare_only:
            if result.get("status") == "UNIVERSE_READY":
                if (result.get("universe_owner_sha256") != owner_sha
                    or type(result.get("code_count")) is not int or result["code_count"] <= 0
                    or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("authority_sha256", "")))
                    or not re.fullmatch(r"[0-9a-f]{24}", str(result.get("authority_run_id", "")))):
                    raise ValueError("dependency identity invalid")
                return {"status":"SUCCEEDED","slot":request.slot,"modules":[module],"exit_code":0,
                        "materializer":result,"materializer_expected_sha256":expected_child_sha,**flags}
            if result.get("status") != "NOT_APPLICABLE":
                raise ValueError("preparation returned a data product")
        if result.get("status")=="NOT_APPLICABLE":
            from contracts.trading_calendar import load_market_calendar,resolve_market_states,TradingDayState
            market=resolve_market_states(load_market_calendar(),request.business_date)["hk_connect"]
            if market not in {TradingDayState.NON_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}: raise ValueError
            return {"status":"SUCCEEDED","slot":"1530","modules":[module],"exit_code":0,
                    "no_op":True,"materializer":result,"materializer_expected_sha256":expected_child_sha,**flags}
        if result.get("status") not in {"MATERIALIZED","ALREADY_EXISTS"}: raise ValueError
        reference=f"workbench_research/{request.business_date}/1530.json"
        if result.get("artifact_ref")!=reference: raise ValueError
        artifact_path=resolve_owned_path(state,reference)
        raw=artifact_path.read_bytes(); payload=json.loads(raw)
        if (hashlib.sha256(raw).hexdigest()!=result.get("artifact_sha256")
            or payload.get("schema_version")!="v4.manager_workbench.research.v1"
            or payload.get("rule_version") not in {"manager-close-rework-r2-v1", "20260921_REBOUND_V3_1530_OBSERVATION_V1"}
            or payload.get("market")!="HK_CONNECT" or payload.get("trade_date")!=request.business_date
            or payload.get("slot")!="1530" or payload.get("run_id")!=result.get("run_id")
            or payload.get("status") not in {"READY","READY_EMPTY","PARTIAL"}
            or payload.get("status")!=result.get("artifact_status")
            or any(payload.get(k) is not v for k,v in flags.items())): raise ValueError
        candidates=payload.get("candidates")
        if not isinstance(candidates,list) or not all(isinstance(c,dict) for c in candidates): raise ValueError
        if any(type(result.get(k)) is not int for k in ("candidate_count","observation_count","qualified_count")): raise ValueError
        if (len(candidates)!=result["candidate_count"] or len(candidates)!=result["observation_count"]
            or sum(c.get("qualified") is True for c in candidates)!=result["qualified_count"]): raise ValueError
        _validate_manager_close_readback(payload)
        if payload['rule_version'] == '20260921_REBOUND_V3_1530_OBSERVATION_V1':
            if not rebound_root or not Path(rebound_root).expanduser().is_absolute():
                raise ValueError('REBOUND_HISTORY_AUTHORITY_ROOT_NOT_BOUND')
            expected_binding = dict(schema_version='v4.manager_close.rebound_authority_binding.v1',
                root_sha256=hashlib.sha256(str(Path(rebound_root).expanduser().resolve()).encode()).hexdigest())
            if (result.get('published_rule_version') != payload['rule_version']
                or result.get('rebound_authority_binding') != expected_binding
                or payload['rebound_screen'].get('authority_binding') != expected_binding):
                raise ValueError('REBOUND_HISTORY_AUTHORITY_BINDING_MISMATCH')
    except (ValueError,TypeError,KeyError,OSError):
        fail("MANAGER_CHILD_RESULT_INVALID",child)
    return {"status":"SUCCEEDED","slot":"1530","modules":[module],"exit_code":0,
            "materializer":result,"materializer_expected_sha256":expected_child_sha,
            "artifact_status":result["artifact_status"],
            "qualified_count":result["qualified_count"],**flags}


def _validate_manager_close_readback(payload: dict[str, Any]) -> None:
    """Versioned R2/V3 wire admission after the sole V4 child publishes.

    Full B1 validation runs in that child and in the API. This second readback
    rejects malformed/contradictory rows without importing V4 into the V35 owner.
    It never upgrades source strings into market evidence or enables new rules.
    """
    import math
    from datetime import datetime
    from zoneinfo import ZoneInfo
    rule = payload.get('rule_version')
    is_v3 = rule == '20260921_REBOUND_V3_1530_OBSERVATION_V1'
    if rule not in {'manager-close-rework-r2-v1', '20260921_REBOUND_V3_1530_OBSERVATION_V1'}:
        raise ValueError('RULE_VERSION_UNSUPPORTED')
    required = (('amount_100m_lt_le_200m_hkd', 'oversold_le_80pct_prior60_high',
                 'volume_ge_1_5_previous5_full_days', 'last_price_ge_1_03_low_so_far', 'final_close_confirmation')
                if is_v3 else
                ('turnover_gt_100m_hkd','verified_volume_expansion','verified_oversold_or_breakout','new_direct_pit_catalyst'))
    def stamp(value):
        if not isinstance(value,str): raise ValueError("TIME_MISSING")
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        if parsed.tzinfo is None: raise ValueError("TIME_NAIVE")
        return parsed
    as_of=stamp(payload.get("as_of")); generated=stamp(payload.get("generated_at"))
    local=as_of.astimezone(ZoneInfo("Asia/Hong_Kong"))
    if local.strftime("%Y%m%d")!=payload["trade_date"] or not (15,30)<=(local.hour,local.minute)<(15,32) or generated<as_of:
        raise ValueError("OBSERVATION_WINDOW_INVALID")
    coverage=payload.get("coverage",{})
    if any(type(coverage.get(k)) is not int or coverage[k]<0 for k in ("eligible_count","covered_count","missing_count")):
        raise ValueError("COVERAGE_INVALID")
    if coverage["covered_count"]+coverage["missing_count"]!=coverage["eligible_count"]: raise ValueError("COVERAGE_SUM_INVALID")
    symbols=set(); ids=set()
    for c in payload["candidates"]:
        if (not isinstance(c.get("candidate_id"),str) or not c["candidate_id"] or c["candidate_id"] in ids
            or not re.fullmatch(r"HK\.\d{5}",str(c.get("symbol",""))) or c["symbol"] in symbols
            or c.get("trade_date")!=payload["trade_date"]): raise ValueError("CANDIDATE_ID_INVALID")
        ids.add(c["candidate_id"]);symbols.add(c["symbol"])
        predicates=c.get("predicates")
        if not isinstance(predicates,list) or len(predicates)!=len(required): raise ValueError("CONDITIONS_MISSING")
        for p,key in zip(predicates,required):
            if (not isinstance(p,dict) or p.get("predicate_id")!=key or p.get("rule_version")!=payload["rule_version"]
                or not (type(p.get("value")) is bool or p.get("value")=="unknown")):
                raise ValueError("CONDITION_INVALID")
        if not is_v3 and any(p["value"]!="unknown" for p in predicates[1:3]): raise ValueError("UNIMPLEMENTED_AUTHORITY_POSITIVE")
        expected=False if any(p["value"] is False for p in predicates) else None
        if c.get("qualified") is not expected: raise ValueError("QUALIFIED_INCONSISTENT")
        for key in ("first_seen_at","last_seen_at","observed_at","available_at"):
            if stamp(c.get(key))>as_of: raise ValueError("CANDIDATE_FUTURE")
        amount=c.get("turnover_amount"); volume=c.get("volume_comparison")
        if (not isinstance(amount,dict) or "value" not in amount or not isinstance(volume,dict)
            or "ratio" not in volume or (not is_v3 and (volume["ratio"] is not None or volume.get("baseline_as_of") is not None))):
            raise ValueError("NESTED_VALUES_MISSING")
        value=amount["value"]
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value)): raise ValueError("AMOUNT_INVALID")
        if stamp(amount.get("as_of"))>as_of: raise ValueError("AMOUNT_FUTURE")
        if predicates[0]["value"]!="unknown":
            if (amount.get("currency")!="HKD" or amount.get("unit")!="HKD" or amount.get("contract_state")!="VERIFIED_HKD"
                or amount.get("status")!="OBSERVED" or value is None
                or predicates[0]["value"] is not (100_000_000<value<=200_000_000 if is_v3 else value>100_000_000)):
                raise ValueError("AMOUNT_CONTRACT_INVALID")
        sources=c.get("sources")
        if not isinstance(sources,list) or not sources: raise ValueError("LINEAGE_MISSING")
        for source in sources:
            if (not isinstance(source,dict) or any(not source.get(k) for k in ("owner","role","run_id","source_date","reason","sha256"))
                or source.get("lane") not in c.get("source_lanes",[]) or source.get("market")!="HK_CONNECT"
                or not re.fullmatch(r"[0-9a-f]{64}",str(source.get("sha256")))): raise ValueError("LINEAGE_INVALID")
            if not stamp(source.get("observed_at"))<=stamp(source.get("available_at"))<=as_of: raise ValueError("LINEAGE_FUTURE")

    if is_v3:
        _validate_manager_close_v3_wire(payload)


def _validate_manager_close_v3_wire(payload: dict[str, Any]) -> None:
    """Wire consistency only; source admission still belongs to V4 child/API.

    Do not import the V4 business modules into this separate hourly owner.
    This branch cannot promote unknown units or a 1530 price into final close.
    """
    import math
    from datetime import datetime
    from decimal import Decimal
    rule = '20260921_REBOUND_V3_1530_OBSERVATION_V1'
    phase = 'SNAPSHOT_1530_NOT_FINAL_CLOSE'
    screen = payload.get('rebound_screen')
    if (not isinstance(screen, dict) or screen.get('rule_version') != rule
        or screen.get('phase') != phase or 'final_close' not in screen
        or screen['final_close'] is not None or type(screen.get('confirmed_strict_count')) is not int
        or screen['confirmed_strict_count'] != 0 or payload.get('status') != 'PARTIAL'):
        raise ValueError('V3_FINAL_CLOSE_OR_PHASE_INVALID')
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)
    decisions = screen.get('source_rows')
    if not isinstance(decisions, list) or len(decisions) != payload['coverage']['covered_count']:
        raise ValueError('V3_DECISION_COVERAGE_INVALID')
    recorded = {}; groups = {'STRICT_ASOF_OBSERVATION': [], 'NEAR_ASOF_OBSERVATION': [], 'PENDING_EVIDENCE': []}
    for row in decisions:
        if not isinstance(row, dict) or not re.fullmatch(r'HK\.\d{5}', str(row.get('symbol', ''))) or row['symbol'] in recorded:
            raise ValueError('V3_DECISION_ID_INVALID')
        if (row.get('rule_version') != rule or row.get('approved_rule_version') != '20260921_REBOUND_V3'
            or row.get('phase') != phase or 'final_close' not in row or row['final_close'] is not None
            or row.get('close_confirmation') != 'unknown'):
            raise ValueError('V3_DECISION_PHASE_INVALID')
        metrics = row.get('metrics'); gates = metrics.get('gates') if isinstance(metrics, dict) else None
        if (not isinstance(gates, dict) or set(gates) != {'amount','oversold','volume','rebound'}
            or any(type(v) is not bool and v != 'unknown' for v in gates.values())):
            raise ValueError('V3_GATES_INVALID')
        strict = all(v is True for v in gates.values())
        near = (gates['amount'] is True and gates['oversold'] is True
                and all(gates[k] != 'unknown' for k in ('volume','rebound'))
                and sum(gates[k] is True for k in ('volume','rebound')) == 1)
        kind = ('EXCLUDED' if gates['amount'] is False or gates['oversold'] is False else
                'PENDING_EVIDENCE' if 'unknown' in gates.values() else
                'STRICT_ASOF_OBSERVATION' if strict else 'NEAR_ASOF_OBSERVATION' if near else 'EXCLUDED')
        if metrics.get('strict') is not strict or metrics.get('near') is not near or row.get('classification') != kind:
            raise ValueError('V3_UNKNOWN_OR_CLASSIFICATION_INVALID')
        for k in ('volume_ratio_5d','rebound_price_vs_low_pct','oversold_cutoff','near_failed_ratio'):
            if metrics.get(k) is not None and not number(metrics[k]): raise ValueError('V3_METRIC_INVALID')
        if gates['volume'] != 'unknown':
            ratio = metrics.get('volume_ratio_5d')
            if not number(ratio) or ratio < 0 or gates['volume'] is not (ratio >= 1.5):
                raise ValueError('V3_VOLUME_GATE_INVALID')
        if gates['rebound'] != 'unknown':
            price, low = row.get('last_price'), row.get('low_so_far')
            if (not number(price) or not number(low) or not 0 < low <= price
                or gates['rebound'] is not (Decimal(str(price)) >= Decimal('1.03') * Decimal(str(low)))):
                raise ValueError('V3_REBOUND_GATE_INVALID')
        if near:
            failed = 'volume' if gates['volume'] is False else 'rebound'
            failed_value = metrics['volume_ratio_5d'] if failed == 'volume' else metrics['rebound_price_vs_low_pct']
            threshold = 1.5 if failed == 'volume' else 3.0
            if (not number(failed_value) or metrics.get('near_failed_gate') != failed
                or metrics.get('near_failed_value') != failed_value or metrics.get('near_gate_value') != threshold
                or metrics.get('near_failed_ratio') != failed_value / threshold):
                raise ValueError('V3_NEAR_METRICS_INVALID')
        recorded[row['symbol']] = row
        if kind in groups: groups[kind].append(row['symbol'])
    visible = {r['symbol'] for r in decisions if r['classification'] != 'EXCLUDED'}
    if {c['symbol'] for c in payload['candidates']} != visible:
        raise ValueError('V3_VISIBLE_DECISION_SET_INVALID')
    for key, kind in [('strict_observation','STRICT_ASOF_OBSERVATION'),('near_observation','NEAR_ASOF_OBSERVATION'),('pending','PENDING_EVIDENCE')]:
        if (not isinstance(screen.get(key), list) or len(set(screen[key])) != len(screen[key])
            or set(screen[key]) != set(groups[kind])):
            raise ValueError('V3_GROUP_INVALID')
    for c in payload['candidates']:
        decision = c.get('position', {}).get('rebound_v3'); p = c['predicates']
        if not isinstance(decision, dict) or dict(symbol=c['symbol'], **decision) != recorded[c['symbol']]:
            raise ValueError('V3_CANDIDATE_DECISION_INVALID')
        gates = decision['metrics']['gates']
        if [v['value'] for v in p] != [gates[k] for k in ('amount','oversold','volume','rebound')] + ['unknown']:
            raise ValueError('V3_FIVE_PREDICATES_INVALID')
        priority = c.get('research_priority', {}); plan = c.get('observation_plan', {})
        if (c.get('data_status') != decision['classification'] or priority.get('level') != c['data_status']
            or priority.get('rule_version') != rule or priority.get('formal_rank_changed') is not False
            or priority.get('buy_gate_changed') is not False or plan.get('phase') != phase
            or 'final_close' not in plan or plan['final_close'] is not None):
            raise ValueError('V3_PLAN_OR_PRIORITY_INVALID')
        if gates['oversold'] != 'unknown':
            peak = c['position'].get('prior60_high'); price = decision.get('last_price')
            if not number(peak) or peak <= 0 or not number(price) or price <= 0:
                raise ValueError('V3_OVERSOLD_INPUT_INVALID')
            cutoff = Decimal('0.8') * Decimal(str(peak))
            if (decision['metrics'].get('oversold_cutoff') != float(cutoff)
                or gates['oversold'] is not (Decimal(str(price)) <= cutoff)):
                raise ValueError('V3_OVERSOLD_GATE_INVALID')
        volume = c['volume_comparison']; ratio = volume['ratio']
        if ratio is not None and (not number(ratio) or ratio < 0): raise ValueError('V3_VOLUME_RATIO_INVALID')
        if gates['volume'] == 'unknown':
            if ratio is not None or volume.get('baseline_as_of') is not None:
                raise ValueError('V3_UNKNOWN_VOLUME_INVALID')
        else:
            if ratio != decision['metrics']['volume_ratio_5d'] or volume.get('state') != 'CUMULATIVE_VS_PREVIOUS5_FULL_DAYS':
                raise ValueError('V3_VOLUME_COMPARISON_INVALID')
            baseline = datetime.fromisoformat(str(volume.get('baseline_as_of')).replace('Z','+00:00'))
            if baseline.tzinfo is None or baseline > datetime.fromisoformat(payload['as_of'].replace('Z','+00:00')):
                raise ValueError('V3_VOLUME_BASELINE_FUTURE')
    strict = sorted(groups['STRICT_ASOF_OBSERVATION'])
    near_rows = sorted((r for r in decisions if r['classification']=='NEAR_ASOF_OBSERVATION'),
        key=lambda r:(-(r['metrics']['near_failed_ratio'] or 0),r['symbol']))
    expected_focus = strict + [r['symbol'] for r in near_rows[:max(0,10-len(strict))]]
    if screen.get('focus_symbols') != expected_focus:
        raise ValueError('V3_FOCUS_INVALID')
    focus = payload.get('priority_summary', {}).get('focus', [])
    expected_ids = {c['candidate_id'] for c in payload['candidates'] if c['symbol'] in expected_focus}
    if (not isinstance(focus, list) or any(not isinstance(f, dict) for f in focus)
        or len(focus) != len(expected_ids) or {f.get('candidate_id') for f in focus} != expected_ids):
        raise ValueError('V3_FOCUS_ITEMS_INVALID')


def _manager_close_recapture_after_stage_workbench(
    self: Any, request: DispatchRequest, *, stage_result: dict[str, Any]
) -> dict[str, Any]:
    """Run the existing PyTDX recapture owner after the same-date 15:55 Stage.

    This is a caller of ``ops.materialize_manager_close_discovery`` only. It
    does not implement a quote producer, and it does not touch the historical
    1530 output lane.
    """
    import hashlib
    import json
    import os
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError

    module = "ops.materialize_manager_close_discovery"
    flags = {"RESEARCH_ONLY": True, "production_allowed": False,
             "buy_gate_updated": False, "orders_sent": False}

    def fail(reason: str, *, child: dict[str, Any] | None = None,
             failure_class: str = "UPSTREAM_NOT_READY") -> None:
        result = {"status": "FAILED", "workload_id": "stage_workbench",
                  "slot": request.slot, "modules": ["ops.materialize_stage_workbench", module],
                  "exit_code": 2, "failure_class": failure_class,
                  "reason": reason, "stage_workbench_status": stage_result.get("status"),
                  "stage_workbench_exit_code": stage_result.get("exit_code"), **flags}
        if child:
            result["close_recapture_child_status"] = child.get("status")
            result["close_recapture_child_exit_code"] = child.get("exit_code")
            try:
                payload = json.loads(str(child.get("stdout") or ""))
            except (TypeError, ValueError):
                payload = {}
            if isinstance(payload, dict):
                result["close_recapture_reason"] = payload.get("reason")
                result["close_recapture_status"] = payload.get("status")
            stderr = str(child.get("stderr") or "").strip()
            if stderr:
                result["child_stderr"] = stderr[:512]
        raise WorkloadExecutionError(result)

    if request.slot != "1555":
        fail("MANAGER_PYTDX_RECAPTURE_REQUIRES_1555_STAGE", failure_class="INVALID_INPUT")
    mode = str(getattr(request.mode, "value", request.mode))
    if mode != "LIVE":
        fail("MANAGER_PYTDX_RECAPTURE_LIVE_ONLY", failure_class="INVALID_INPUT")
    if not isinstance(stage_result, dict):
        fail("MANAGER_PYTDX_RECAPTURE_STAGE_RESULT_INVALID", failure_class="INVALID_INPUT")
    if os.environ.get("V4_MANAGER_CLOSE_CAPTURE_MODE", "").strip() != "PYTDX_LATE_OBSERVATION":
        fail("MANAGER_PYTDX_RECAPTURE_MODE_NOT_ENABLED", failure_class="INVALID_INPUT")

    configured_app = os.environ.get("V4_MANAGER_MATERIALIZER_APP_ROOT", "").strip()
    configured_sha = os.environ.get("V4_MANAGER_MATERIALIZER_SHA256", "").strip()
    configured_state = os.environ.get("V4_MANAGER_RESEARCH_STATE_ROOT", "").strip()
    configured_python = os.environ.get("V35_HK_0_2_REAL_PYTHON", "").strip()
    configured_provider = os.environ.get("V35_SHARED_PACKAGE_ROOT", "").strip()
    app = Path(configured_app).expanduser() if configured_app else None
    state = Path(configured_state).expanduser() if configured_state else None
    python = Path(configured_python).expanduser() if configured_python else None
    provider = Path(configured_provider).expanduser() if configured_provider else None
    universe = getattr(self, "hk_universe_root", None)
    shared_store = getattr(self, "shared_data_root", None)
    if (app is None or state is None or python is None or provider is None or universe is None
            or shared_store is None):
        fail("MANAGER_PYTDX_RECAPTURE_EXPLICIT_BINDING_MISSING", failure_class="INVALID_INPUT")
    app = app.resolve()
    state = state.resolve()
    universe = Path(universe).expanduser().resolve()
    shared_store = Path(shared_store).expanduser().resolve()
    provider = provider.resolve()
    module_path = app / module.replace(".", "/")
    module_path = module_path.with_suffix(".py")
    if (not app.is_dir() or not state.is_absolute() or not state.is_dir()
            or not universe.is_dir() or not provider.is_dir()
            or shared_store != (universe / ".runtime/data").resolve()
            or python is None or not python.is_absolute() or not python.is_file()
            or not os.access(python, os.X_OK)
            or not re.fullmatch(r"[0-9a-f]{64}", configured_sha)
            or not module_path.is_file()
            or hashlib.sha256(module_path.read_bytes()).hexdigest() != configured_sha):
        fail("MANAGER_PYTDX_RECAPTURE_BINDING_INVALID", failure_class="INVALID_INPUT")
    date = request.business_date
    expected_artifact = f"workbench_research/{date}/close_recapture.json"
    expected_receipt = f"workbench_research/{date}/close_recapture.receipt.json"
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": os.pathsep.join((str(app), str(app / "upstreams"),
                                        str(app / "upstreams/v3_shared_data"), str(provider))),
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "RESEARCH_ONLY": "true", "PRODUCTION_ALLOWED": "false",
        "BUY_GATE_UPDATED": "false", "ORDERS_SENT": "false",
    })
    args = ["--close-recapture", "--state-root", str(state),
            "--universe-root", str(universe), "--trade-date", date,
            "--app-root", str(app), "--pytdx-python", str(python),
            "--provider-root", str(provider)]
    timeout = min(420, max(30, int(getattr(self, "timeout_seconds", 420))))
    try:
        child = self._run(module, args, cwd=app, env=env, timeout_seconds=timeout)
    except (OSError, RuntimeError, ValueError) as error:
        fail(f"MANAGER_PYTDX_RECAPTURE_CHILD_START_FAILED:{type(error).__name__}")
    try:
        result = json.loads(str(child.get("stdout") or ""))
    except (TypeError, ValueError):
        result = {}
    identity = (isinstance(result, dict)
        and result.get("schema_version") == "v4.manager_close_recapture_result.v1"
        and result.get("source_trade_date") == date
        and result.get("module_origin") == str(module_path)
        and result.get("module_sha256") == configured_sha
        and result.get("state_root") == str(state)
        and result.get("capture_mode") == "LATE_OBSERVATION"
        and all(result.get(key) is value for key, value in flags.items()))
    if not identity:
        fail("MANAGER_PYTDX_RECAPTURE_CHILD_RESULT_INVALID", child=child, failure_class="INVALID_INPUT")
    if child.get("status") != "SUCCEEDED" or child.get("exit_code") != 0:
        reason = result.get("reason") or "MANAGER_PYTDX_RECAPTURE_CHILD_FAILED"
        fail(str(reason)[:160], child=child)
    if result.get("status") == "NOT_APPLICABLE":
        return {"status": "NOT_APPLICABLE", "slot": request.slot, "modules": [module],
                "exit_code": 0, "materializer": result, "no_op": True, **flags}
    if result.get("status") not in {"MATERIALIZED", "PARTIAL", "ALREADY_EXISTS"}:
        fail("MANAGER_PYTDX_RECAPTURE_STATUS_INVALID", child=child, failure_class="INVALID_INPUT")
    if result.get("artifact_ref") != expected_artifact or result.get("receipt_ref") != expected_receipt:
        fail("MANAGER_PYTDX_RECAPTURE_REFERENCE_INVALID", child=child, failure_class="INVALID_INPUT")
    try:
        artifact_path = resolve_owned_path(state, expected_artifact)
        receipt_path = resolve_owned_path(state, expected_receipt)
        artifact_raw = artifact_path.read_bytes()
        receipt_raw = receipt_path.read_bytes()
        payload = json.loads(artifact_raw)
        receipt = json.loads(receipt_raw)
        artifact_sha = hashlib.sha256(artifact_raw).hexdigest()
        receipt_sha = hashlib.sha256(receipt_raw).hexdigest()
        snapshot_ref = result.get("snapshot_ref")
        candidate_ref = result.get("candidate_overlay_ref")
        snapshot_sha = result.get("snapshot_sha256")
        candidate_sha = result.get("candidate_overlay_sha256")
        snapshot_raw = resolve_owned_path(state, snapshot_ref).read_bytes()
        candidate_raw = resolve_owned_path(state, candidate_ref).read_bytes()
        snapshot = json.loads(snapshot_raw)
        candidate_overlay = json.loads(candidate_raw)
        if (artifact_sha != result.get("artifact_sha256")
                or receipt_sha != result.get("receipt_sha256")
                or hashlib.sha256(snapshot_raw).hexdigest() != snapshot_sha
                or hashlib.sha256(candidate_raw).hexdigest() != candidate_sha
                or payload.get("schema_version") != "v4.manager_close_recapture.v1"
                or payload.get("source_trade_date") != date
                or payload.get("plan_trade_date") != result.get("plan_trade_date")
                or payload.get("capture_mode") != "LATE_OBSERVATION"
                or payload.get("observation_type") != "PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION"
                or payload.get("pool", {}).get("trade_date") != date
                or payload.get("source", {}).get("provider") != "pytdx_exhq"
                or payload.get("source", {}).get("source_id") != "pytdx"
                or payload.get("bar_window", {}).get("stage_id") != "STAGE_1545_1555"
                or payload.get("snapshot", {}).get("artifact_ref") != snapshot_ref
                or payload.get("snapshot", {}).get("sha256") != snapshot_sha
                or payload.get("candidate_overlay", {}).get("artifact_ref") != candidate_ref
                or payload.get("candidate_overlay", {}).get("sha256") != candidate_sha
                or receipt.get("schema_version") != "v4.manager_close_recapture_receipt.v1"
                or receipt.get("source_trade_date") != date
                or receipt.get("target_trade_date") != result.get("plan_trade_date")
                or receipt.get("artifact_ref") != expected_artifact
                or receipt.get("artifact_sha256") != artifact_sha
                or receipt.get("snapshot_ref") != result.get("snapshot_ref")
                or receipt.get("snapshot_sha256") != result.get("snapshot_sha256")
                or receipt.get("candidate_overlay_ref") != result.get("candidate_overlay_ref")
                or receipt.get("candidate_overlay_sha256") != result.get("candidate_overlay_sha256")
                or snapshot.get("schema_version") != "v4.manager_close_recapture_pytdx_snapshot.v1"
                or snapshot.get("source_trade_date") != date
                or snapshot.get("stage_id") != "STAGE_1545_1555"
                or candidate_overlay.get("schema_version") != "v4.manager_close_recapture_candidate_overlay.v1"
                or candidate_overlay.get("source_trade_date") != date
                or candidate_overlay.get("target_trade_date") != result.get("plan_trade_date")
                or not isinstance(candidate_overlay.get("rows"), list)
                or len(candidate_overlay["rows"]) != result.get("candidate_count")
                or type(result.get("candidate_count")) is not int
                or result.get("candidate_count") <= 0
                or result.get("candidate_count") != payload.get("candidate_overlay", {}).get("count")
                or any(payload.get(key) is not value for key, value in flags.items())
                or any(receipt.get(key) is not value for key, value in flags.items())):
            raise ValueError("CLOSE_RECAPTURE_READBACK_MISMATCH")
    except (OSError, TypeError, ValueError, KeyError):
        fail("MANAGER_PYTDX_RECAPTURE_STORE_READBACK_INVALID", child=child, failure_class="INVALID_INPUT")
    return {"status": "SUCCEEDED" if result.get("status") != "PARTIAL" else "PARTIAL",
            "slot": request.slot, "modules": [module], "exit_code": 0,
            "stage_workbench_status": stage_result.get("status"),
            "stage_workbench_exit_code": stage_result.get("exit_code"),
            "materializer": result, "artifact_sha256": artifact_sha,
            "receipt_sha256": receipt_sha, **flags}
