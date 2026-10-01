"""Preselection executor handlers.

The facade rebinds these functions into its historical class interface.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from contracts.runtime_tasks import DispatchRequest
from infrastructure.preselection_pool_store import PreselectionPoolStore
from ops.daily_materialize import resolve_selector_panel


def _verified_formal_pool_reuse(
    self, trade_date: str
) -> dict[str, Any] | None:
    """Reuse an already verified A/HK formal pair for the target date.

        The independent pool producers are the authority for this boundary.
        A scheduler tick must not re-enter the two formal-pool producers when
        both exact artifacts are complete.  The caller still runs the optional
        D-1 and research lanes, whose artifacts are independent of this pair.
        Returning ``None`` preserves the existing producer path for a date that
        has not yet acquired both exact formal artifacts.
        """

    expected = (
        ("a_d1_premarket_pool", "A", "SHARED_VERIFIED_V192"),
        ("hkconnect_d1_top100", "HK", "SHARED_VERIFIED_HK_0_2"),
    )
    pools: dict[str, dict[str, Any]] = {}
    try:
        store = PreselectionPoolStore(self.data_root)
        for pool_id, market, source_role in expected:
            payload = store.read_pool(trade_date, pool_id)
            if (
                payload.get("pool_id") != pool_id
                or payload.get("market") != market
                or payload.get("trade_date") != trade_date
                or payload.get("target_date") != trade_date
                or payload.get("source_role") != source_role
                or payload.get("stage_selection_eligible") is not True
                or payload.get("source_merge_role") == "SOURCE_ONLY"
                or payload.get("status") in {"CANNOT_CONFIRM", "MISSING", "VALID_EMPTY"}
            ):
                return None
            rows = payload.get("rows")
            if not isinstance(rows, list) or not rows:
                return None
            if any(
                payload.get(field) is not False
                for field in ("production_allowed", "buy_gate_updated", "orders_sent")
            ):
                return None
            if any(not isinstance(row, dict) for row in rows):
                return None
            codes = [
                str(
                    row.get("code")
                    or row.get("code_norm")
                    or row.get("symbol")
                    or ""
                ).strip()
                for row in rows
            ]
            if any(not code for code in codes) or len(set(codes)) != len(codes):
                return None
            if market == "HK" and len(rows) != 100:
                return None
            if market == "HK":
                from contracts.trading_calendar import load_market_calendar, previous_session
                from domains.preselection_materializer import build_shared_hk_0_2_pool
                price = previous_session(load_market_calendar(), trade_date, market="hk_securities")
                verified = build_shared_hk_0_2_pool(self.shared_data_root,
                    trade_date=trade_date, signal_date=price, eligibility_source_date=price,
                    eligibility_universe_root=_hk_owner_universe_root(self),
                    shared_package_root=self.shared_package_root)
                if verified != payload:
                    return None
            pools[pool_id] = payload
    except (FileNotFoundError, OSError, ValueError, RuntimeError, json.JSONDecodeError):
        return None
    return {
        "status": "SUCCEEDED",
        "workload_id": "preselection_pools",
        "target_date": trade_date,
        "a_selector_status": "READY",
        "hk_lane_status": "READY",
        "formal_pool_reuse": {
            "a_pool_id": "a_d1_premarket_pool",
            "a_row_count": len(pools["a_d1_premarket_pool"]["rows"]),
            "a_source_sha256": pools["a_d1_premarket_pool"].get("source_sha256"),
            "hk_pool_id": "hkconnect_d1_top100",
            "hk_row_count": len(pools["hkconnect_d1_top100"]["rows"]),
            "hk_source_sha256": pools["hkconnect_d1_top100"].get("source_sha256"),
        },
        "producer_called": False,
        "write_performed": False,
        "modules": ["infrastructure.preselection_pool_store"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }

def _hk_owner_universe_root(self):
    root = self.hk_universe_root
    if (root is not None and self.shared_data_root is not None
            and self.shared_data_root.resolve() == root.resolve() / ".runtime" / "data"):
        return self.shared_data_root
    return root


def _preselection_pools(
    self, request: DispatchRequest
) -> dict[str, Any]:
    from contracts.trading_calendar import load_market_calendar, previous_session, resolve_market_states
    calendar = load_market_calendar()
    states = resolve_market_states(calendar, request.business_date)
    a_lane_eligible = states["a_share"].value in {"FULL_TRADING_DAY", "HALF_TRADING_DAY_AM"}
    hk_lane_eligible = states["hk_securities"].value in {"FULL_TRADING_DAY", "HALF_TRADING_DAY_AM"}
    hk_signal_date = previous_session(calendar, request.target_date, market="hk_securities")
    # Exact current capture is the supported eligibility validity contract;
    # a previous Connect session is not itself a source authority.
    hk_eligibility_source_date = hk_signal_date
    hk_universe_root = _hk_owner_universe_root(self)
    reused = self._verified_formal_pool_reuse(request.target_date)
    modules = [
        "scripts.capture_public_fupan",
        "ops.materialize_shared_v192_preselection",
        "scripts.update_hk_0_2_panel",
        "ops.ensure_hk_security_master",
        "scripts.materialize_hk_0_2",
        "ops.materialize_d1_review_lanes",
        "ops.materialize_scheduled_preselection",
    ]
    if (
        self.shared_data_root is None
        or self.hk_universe_root is None
        or self.shared_package_root is None
    ):
        raise WorkloadExecutionError(
            self._failure_result(
                "preselection_pools",
                modules,
                "shared data root, HK universe root, and shared package root are required",
            )
        )
    if self.preselection_input_root is None:
        raise WorkloadExecutionError(
            self._failure_result(
                "preselection_pools",
                modules,
                "preselection input root not configured",
            )
        )
    shared_entries = ([self.shared_package_root / "scripts" / "capture_public_fupan.py"]
                      if a_lane_eligible else [])
    if reused is None:
        shared_entries.extend(
            (
                *((self.shared_package_root / "scripts" / "materialize_v192_selector.py",) if a_lane_eligible else ()),
                self.shared_package_root / "scripts" / "update_hk_0_2_panel.py",
                self.shared_package_root / "scripts" / "materialize_hk_0_2.py",
            )
        )
    for shared_entry in shared_entries:
        if not shared_entry.is_file():
            raise WorkloadExecutionError(
                self._failure_result(
                    "preselection_pools",
                    modules,
                    f"fixed shared entry missing: {shared_entry.name}",
                )
            )
    security_entry = (self.repo_root or Path.cwd()) / "ops" / "ensure_hk_security_master.py"
    if reused is None and not security_entry.is_file():
        raise WorkloadExecutionError(
            self._failure_result(
                "preselection_pools",
                modules,
                "fixed HK security-master entry missing",
            )
        )
    selector: Path | None = None
    selector_error = ""
    if not a_lane_eligible:
        selector_error = "A_SHARE_NON_TRADING_DAY"
    elif self.selector_data_root is None:
        selector_error = "selector data root not configured"
    else:
        try:
            selector = resolve_selector_panel(
                self.selector_data_root, request.business_date
            )
        except FileNotFoundError as error:
            selector_error = f"selector panel unresolved: {error}"
    trusted_env = os.environ.copy()
    trusted_env.update({
        "V3_SHARED_DATA_STORE_ROOT": str(self.shared_data_root),
        "V35_SHARED_PACKAGE_ROOT": str(self.shared_package_root),
        "V3_SHARED_FUTU_PYTHON": str(self.shared_futu_python_executable),
        "V35_HK_0_2_PYTHON": str(self.hk_0_2_python_executable),
        "V3_SHARED_HK_TDX_ROOT": str(self.hk_0_2_tdx_root),
    })
    if selector is not None:
        trusted_env["V3_SHARED_SELECTOR_READY_PANEL"] = str(selector)
    else:
        trusted_env.pop("V3_SHARED_SELECTOR_READY_PANEL", None)
    a_lane_degradations: list[dict[str, Any]] = []
    optional_lane_degradations: list[dict[str, Any]] = []
    if a_lane_eligible and selector_error and reused is None:
        a_lane_degradations.append(
            {
                "status": "CANNOT_CONFIRM",
                "lane": "A_SHARE",
                "reason": selector_error,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
    if not a_lane_eligible:
        public_result = {"status": "SKIPPED", "lane": "A_SHARE"}
    else:
        public_result = self._run(
            "scripts.capture_public_fupan",
            ["--trade-date", request.business_date],
            cwd=self.shared_package_root,
            env=trusted_env,
        )
    if a_lane_eligible and public_result["status"] != "SUCCEEDED":
        public_result = dict(public_result)
        public_result["lane"] = "A_SHARE_OPTIONAL" if reused is not None else "A_SHARE"
        public_result["status"] = "CANNOT_CONFIRM"
        (optional_lane_degradations if reused is not None else a_lane_degradations).append(public_result)
    if not a_lane_eligible:
        shared_result = {"status": "SKIPPED", "lane": "A_SHARE"}
    elif reused is not None:
        shared_result = {
            "status": "SUCCEEDED",
            "workload_id": "a_d1_premarket_pool",
            "reused": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    else:
        shared_result = self._run(
            "ops.materialize_shared_v192_preselection",
            [
                "--signal-date", request.business_date,
                "--target-date", request.target_date,
            ],
            cwd=self.repo_root,
            env=trusted_env,
            timeout_seconds=_V192_PRESELECTION_TIMEOUT_SECONDS,
        )
        if shared_result["status"] != "SUCCEEDED":
            shared_result = dict(shared_result)
            shared_result["lane"] = "A_SHARE"
            shared_result["status"] = "CANNOT_CONFIRM"
            a_lane_degradations.append(shared_result)
    hk_lane_degradations: list[dict[str, Any]] = []
    security_result: dict[str, Any] = {}
    universe_result: dict[str, Any] = {"status": "SKIPPED"}
    if reused is not None:
        update_result = {
            "status": "SUCCEEDED",
            "workload_id": "hkconnect_d1_top100",
            "reused": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        hk_result = dict(update_result)
        hk_result["modules"] = ["scripts.materialize_hk_0_2"]
    else:
        hk_runtime_error = self._hk_0_2_runtime_error()
        hk_runtime_missing = (
            self._runner is _default_runner
            and not self.hk_0_2_python_executable.is_file()
        )
        hk_runtime_unavailable = hk_runtime_error is not None or hk_runtime_missing
        if hk_runtime_unavailable:
            update_result = self._failure_result(
                "preselection_pools",
                ["scripts.update_hk_0_2_panel"],
                hk_runtime_error
                or f"HK 0.2 Python runtime missing: {self.hk_0_2_python_executable}",
            )
            update_result["lane"] = "HK_CONNECT"
            update_result["status"] = "CANNOT_CONFIRM"
            hk_lane_degradations.append(update_result)
        else:
            update_result = self._run(
                "scripts.update_hk_0_2_panel",
                [
                    "--asset-root", str(self.shared_data_root / "assets" / "hk_0_2"),
                    "--tdx-root", str(self.hk_0_2_tdx_root),
                    "--through-date", hk_signal_date,
                ],
                cwd=self.shared_package_root,
                env=trusted_env,
                python_executable=self.hk_0_2_python_executable,
            )
            if update_result["status"] != "SUCCEEDED":
                update_result = dict(update_result)
                update_result["lane"] = "HK_CONNECT"
                update_result["status"] = "CANNOT_CONFIRM"
                hk_lane_degradations.append(update_result)
        try:
            if hk_runtime_unavailable or not hk_lane_eligible:
                raise ValueError("HK_SOURCE_RUNTIME_OR_CALENDAR_UNAVAILABLE")
            if request.business_date != hk_signal_date:
                raise ValueError("HK_PRICE_SESSION_NOT_REACHED")
            from stage_center.hk_universe_preflight import ensure_hk_connect_universe
            source = ensure_hk_connect_universe(hk_universe_root, hk_signal_date)
            if source.get("ok") is not True or source.get("trade_date") != hk_signal_date:
                raise ValueError("HK_UNIVERSE_EXACT_SOURCE_UNAVAILABLE")
            universe_result = {"status": "SUCCEEDED", "source_date": hk_signal_date,
                               "artifact_sha256": source.get("artifact_sha256")}
        except (OSError, RuntimeError, ValueError, TypeError) as error:
            universe_result = {"status": "CANNOT_CONFIRM", "reason": str(error),
                "lane": "HK_CONNECT", "production_allowed": False,
                "buy_gate_updated": False, "orders_sent": False}
        if universe_result["status"] != "SUCCEEDED":
            security_result = dict(universe_result)
        else:
            security_result = self._run(
                "ops.ensure_hk_security_master",
                [
                    "--store-root", str(self.shared_data_root),
                    "--universe-root", str(hk_universe_root),
                    "--shared-package-root", str(self.shared_package_root),
                    "--trade-date", hk_eligibility_source_date,
                    "--futu-python", str(self.shared_futu_python_executable),
                ],
                cwd=self.repo_root,
                env=trusted_env,
            )
        if security_result["status"] != "SUCCEEDED":
            security_result = dict(security_result)
            security_result["lane"] = "HK_CONNECT"
            security_result["status"] = "CANNOT_CONFIRM"
            hk_lane_degradations.append(security_result)
        if security_result.get("status") != "SUCCEEDED":
            hk_result = dict(security_result)
        elif hk_runtime_unavailable:
            hk_result = dict(update_result)
            hk_result["modules"] = ["scripts.materialize_hk_0_2"]
        else:
            hk_result = self._run(
                "scripts.materialize_hk_0_2",
                [
                    "--store-root", str(self.shared_data_root),
                    "--asset-root", str(self.shared_data_root / "assets" / "hk_0_2"),
                    "--signal-date", hk_signal_date,
                    "--eligibility-source-date", hk_eligibility_source_date,
                    "--eligibility-universe-root", str(hk_universe_root),
                    "--target-date", request.target_date,
                ],
                cwd=self.shared_package_root,
                env=trusted_env,
                python_executable=self.hk_0_2_python_executable,
            )
            if hk_result["status"] != "SUCCEEDED":
                hk_result = dict(hk_result)
                hk_result["lane"] = "HK_CONNECT"
                hk_result["status"] = "CANNOT_CONFIRM"
                hk_lane_degradations.append(hk_result)
    if not a_lane_eligible:
        lane_result = {"status": "SKIPPED", "lane": "A_SHARE"}
    elif selector is None:
        lane_result = {
            "status": "CANNOT_CONFIRM",
            "exit_code": 1,
            "stdout": "",
            "stderr": selector_error,
            "modules": ["ops.materialize_d1_review_lanes"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    else:
        lane_result = self._run(
            "ops.materialize_d1_review_lanes",
            [
                "--trade-date", request.business_date,
                "--target-date", request.target_date,
                "--data-root", str(self.data_root),
                "--preselection-input-root", str(self.preselection_input_root),
                "--shared-data-root", str(self.shared_data_root),
                "--shared-package-root", str(self.shared_package_root),
                "--selector", str(selector),
                *(
                    ["--stage-selection-root", str(self.stage_selection_root)]
                    if self.stage_selection_root is not None
                    else []
                ),
            ],
        )
    if a_lane_eligible and lane_result["status"] != "SUCCEEDED":
        # The D-1 review lanes enrich the fupan/stage7 optional pools.  The
        # scheduled materializer already emits explicit CANNOT_CONFIRM
        # artifacts when those inputs are unavailable, so they must not
        # suppress the independently verified A v1.9.2 and HK 0.2 pools.
        optional_lane_degradations.append({
            "status": "CANNOT_CONFIRM",
            "module": "ops.materialize_d1_review_lanes",
            "exit_code": lane_result["exit_code"],
            "stdout": lane_result["stdout"],
            "stderr": lane_result["stderr"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    arguments = [
        "--trade-date", request.target_date,
        "--signal-date", request.business_date,
        "--data-root", str(self.data_root),
        "--input-root", str(self.preselection_input_root),
        "--shared-data-root", str(self.shared_data_root),
        "--shared-package-root", str(self.shared_package_root),
    ]
    if selector is not None:
        arguments[6:6] = ["--selector", str(selector)]
    if reused is not None and a_lane_eligible:
        arguments.append("--reuse-formal-pools")
    if not a_lane_eligible:
        arguments.extend(["--market", "HK"])
    arguments.extend(["--hk-signal-date", hk_signal_date,
        "--hk-eligibility-source-date", hk_eligibility_source_date,
        "--hk-eligibility-universe-root", str(hk_universe_root)])
    result = self._run("ops.materialize_scheduled_preselection", arguments)
    result["modules"] = modules
    result["hk_universe_publication"] = universe_result
    result["formal_pool_reuse"] = (
        reused.get("formal_pool_reuse") if reused is not None else None
    )
    result["a_selector_status"] = (
        "PRESERVED_NOT_EXECUTED" if not a_lane_eligible else "READY"
        if reused is not None
        else ("READY" if selector is not None and not a_lane_degradations else "CANNOT_CONFIRM")
    )
    result["hk_lane_status"] = (
        "READY"
        if reused is not None
        else (
            "SUCCEEDED"
            if hk_result["status"] == "SUCCEEDED" and not hk_lane_degradations
            else "CANNOT_CONFIRM"
        )
    )
    security_payload = security_result.get("_authoritative_payload")
    if isinstance(security_payload, dict):
        result["hk_security_master"] = dict(security_payload)
    if a_lane_degradations:
        result["a_lane_degradations"] = a_lane_degradations
    if hk_lane_degradations:
        result["hk_lane_degradations"] = hk_lane_degradations
    if optional_lane_degradations:
        result["optional_d1_review_lane"] = (
            optional_lane_degradations[0]
            if len(optional_lane_degradations) == 1
            else {
                "status": "CANNOT_CONFIRM",
                "lanes": optional_lane_degradations,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
    return result
