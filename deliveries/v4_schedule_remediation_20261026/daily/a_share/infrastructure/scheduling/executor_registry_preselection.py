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


def _hk_price_and_eligibility_dates(target_date: str) -> tuple[str, str]:
    """Keep HK securities pricing separate from Southbound eligibility."""
    from contracts.trading_calendar import load_market_calendar, previous_session

    calendar = load_market_calendar()
    price_signal_date = previous_session(
        calendar, target_date, market="hk_securities"
    )
    eligibility_source_date = previous_session(
        calendar, target_date, market="hk_connect"
    )
    return price_signal_date, eligibility_source_date


def _hk_next_target_date(business_date: str) -> str:
    """Use the deployed calendar API; reject dates outside its frozen year."""
    from datetime import datetime, timedelta
    from contracts.trading_calendar import TradingDayState, load_market_calendar, resolve_market_states

    calendar = load_market_calendar()
    if resolve_market_states(calendar, business_date)["hk_securities"] == TradingDayState.UNKNOWN:
        raise ValueError("next-session date is outside frozen calendar")
    cursor = datetime.strptime(business_date, "%Y%m%d").date() + timedelta(days=1)
    while cursor.year == calendar.year:
        day = cursor.strftime("%Y%m%d")
        if resolve_market_states(calendar, day)["hk_securities"] in {
            TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM,
        }:
            return day
        cursor += timedelta(days=1)
    raise ValueError("next session is outside frozen calendar")


def _hk_preselection_source_dates(
    business_date: str,
    hk_target_date: str,
) -> tuple[str, str]:
    """Bind price features to the business-date HK close and eligibility to D-1 Connect."""
    from contracts.trading_calendar import (
        TradingDayState,
        load_market_calendar,
        previous_session,
        resolve_market_states,
    )

    calendar = load_market_calendar()
    expected_target = _hk_next_target_date(business_date)
    if hk_target_date != expected_target:
        raise ValueError("HK target must be the next HK securities session")
    hk_state = resolve_market_states(calendar, business_date)["hk_securities"]
    if hk_state in {
        TradingDayState.FULL_TRADING_DAY,
        TradingDayState.HALF_TRADING_DAY_AM,
    }:
        price_signal_date = business_date
    else:
        price_signal_date = previous_session(
            calendar, business_date, market="hk_securities"
        )
    eligibility_source_date = previous_session(
        calendar, hk_target_date, market="hk_connect"
    )
    return price_signal_date, eligibility_source_date


def _verified_formal_pool_reuse(
    self, trade_date: str, *, _hk_only: bool = False
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
    def reject_hk_or_fallback():
        if 'a_d1_premarket_pool' not in pools:
            return None
        return {"status":"FAILED", "exit_code":1, "failure_class":"HK_HISTORY_RESOLUTION_CACHE_REJECTED",
            "a_selector_status":"READY", "hk_lane_status":"QUARANTINED",
            "hk_quality_rejected":True, "producer_called":False, "write_performed":False,
            "formal_pool_reuse":{"a_pool_id":"a_d1_premarket_pool",
                "a_source_sha256":pools['a_d1_premarket_pool'].get('source_sha256')},
            "reason":"HK_HISTORY_RESOLUTION_CACHE_REJECTED", "production_allowed":False,
            "buy_gate_updated":False, "orders_sent":False}
    try:
        store = PreselectionPoolStore(self.data_root)
        for pool_id, market, source_role in expected:
            if _hk_only and market != "HK":
                continue
            try:
                payload = store.read_pool(trade_date, pool_id)
            except FileNotFoundError as error:
                if pool_id == "hkconnect_d1_top100" and error.args == (pool_id,) and "a_d1_premarket_pool" in pools:
                    return {"hk_missing_retry": True, "a_identity": {"pool_id": "a_d1_premarket_pool",
                        "source_sha256": pools["a_d1_premarket_pool"].get("source_sha256")}}
                raise
            if (
                payload.get("pool_id") != pool_id
                or payload.get("market") != market
                or payload.get("trade_date") != trade_date
                or (market != "HK" and payload.get("target_date") != trade_date)
                or payload.get("source_role") != source_role
                or payload.get("stage_selection_eligible") is not True
                or payload.get("source_merge_role") == "SOURCE_ONLY"
                or payload.get("status") in {"CANNOT_CONFIRM", "MISSING", "VALID_EMPTY"}
            ):
                return reject_hk_or_fallback()
            rows = payload.get("rows")
            if not isinstance(rows, list) or not rows:
                return reject_hk_or_fallback()
            if any(
                payload.get(field) is not False
                for field in ("production_allowed", "buy_gate_updated", "orders_sent")
            ):
                return reject_hk_or_fallback()
            if any(not isinstance(row, dict) for row in rows):
                return reject_hk_or_fallback()
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
                return reject_hk_or_fallback()
            if market == "HK" and len(rows) != 100:
                return reject_hk_or_fallback()
            if market == "HK":
                if payload.get("status") not in {"READY", "STRICT_0_2_READY", "HK_0_2_TOP100_READY"}:
                    return reject_hk_or_fallback()
                try:
                    from infrastructure.scheduling.executor_registry_preselection import _hk_price_and_eligibility_dates
                    expected_signal, eligibility_source_date = _hk_price_and_eligibility_dates(trade_date)
                    if eligibility_source_date != expected_signal:
                        raise ValueError("HK_SPLIT_DATE_CONTRACT_UNSUPPORTED")
                    signal_dates = {str(row.get("signal_date") or "") for row in rows}
                    target_dates = {str(row.get("target_date") or "") for row in rows}
                    if len(signal_dates) != 1 or target_dates != {trade_date}:
                        raise ValueError("HK_HISTORY_RESOLUTION_CACHE_ROW_DATE_MISMATCH")
                    signal_date = next(iter(signal_dates))
                    if (signal_date != expected_signal
                            or (payload.get("signal_date") is not None and payload["signal_date"] != signal_date)
                            or (payload.get("target_date") is not None and payload["target_date"] != trade_date)
                            or any(row.get("trade_date") is not None and row["trade_date"] != trade_date for row in rows)):
                        raise ValueError("HK_HISTORY_RESOLUTION_CACHE_ROW_DATE_MISMATCH")
                    from infrastructure.isolated_package_loader import load_isolated_package_module
                    module = load_isolated_package_module(self.shared_package_root,
                        package_directory="shared_data", module_leaf="hk_0_2",
                        namespace_prefix="hk_history_cache_gate")
                    reader_arguments = {"target_date": trade_date, "expected_signal_date": signal_date}
                    verified = module.read_verified_hk_0_2_pool(self.shared_data_root, **reader_arguments)
                    if (verified.run.receipt.get("status") != "READY"
                            or verified.run.verification["artifact_sha256"] != payload.get("source_sha256")
                            or verified.run.verification["artifact_sha256"] != payload.get("source_artifact_sha256",payload.get("source_sha256"))
                            or verified.run.verification["manifest_sha256"] != payload.get("source_manifest_sha256")
                            or verified.run.verification["receipt_sha256"] != payload.get("source_receipt_sha256")
                            or verified.run.verification["run_id"] != payload.get("source_run_id")):
                        raise ValueError("HK_HISTORY_RESOLUTION_CACHE_SOURCE_IDENTITY_MISMATCH")
                    cached_projection = [(code, str(row["rank"]).strip()) for code, row in zip(codes, rows)]
                    verified_projection = [(str(row["code_norm"]).strip(), str(row["rank"]).strip()) for row in verified.rows]
                    if (cached_projection != verified_projection
                            or [rank for _, rank in cached_projection] != [str(i) for i in range(1, 101)]):
                        raise ValueError("HK_HISTORY_RESOLUTION_CACHE_ROWS_MISMATCH")
                    import math
                    cached_values = [(float(row["pool_score"]), row.get("history_resolution_identity")) for row in rows]
                    verified_values = [(float(row["score_prob_active"]), row.get("history_resolution_identity")) for row in verified.rows]
                    if (cached_values != verified_values
                            or any(not math.isfinite(score) or not isinstance(identity, str) or len(identity) != 64 for score, identity in cached_values)
                            or any(row.get(flag) is not False for row in rows for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))):
                        raise ValueError("HK_HISTORY_RESOLUTION_CACHE_VALUES_MISMATCH")
                except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
                    if _hk_only:
                        return None  # the original refresh path remains responsible for a rejected cache
                    # A is already independently verified. Never enter its producer or rewrite its cache.
                    unsupported = str(error) == "HK_SPLIT_DATE_CONTRACT_UNSUPPORTED"
                    return {"status":"FAILED", "exit_code":1,
                        "failure_class":"UPSTREAM_NOT_READY" if unsupported else "HK_HISTORY_RESOLUTION_CACHE_REJECTED",
                        "a_selector_status":"READY", "hk_lane_status":"CANNOT_CONFIRM" if unsupported else "QUARANTINED",
                        "hk_quality_rejected":True, "producer_called":False, "write_performed":False,
                        "formal_pool_reuse":{"a_pool_id":"a_d1_premarket_pool",
                            "a_source_sha256":pools["a_d1_premarket_pool"].get("source_sha256")},
                        "reason":str(error) if unsupported else "HK_HISTORY_RESOLUTION_CACHE_REJECTED", "production_allowed":False,
                        "buy_gate_updated":False, "orders_sent":False}
            pools[pool_id] = payload
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return reject_hk_or_fallback()
    if _hk_only:
        return {
            "status": "SUCCEEDED", "hk_lane_status": "READY",
            "hk_pool_id": "hkconnect_d1_top100", "hk_row_count": 100,
            "hk_source_sha256": pools["hkconnect_d1_top100"].get("source_sha256"),
            "producer_called": False, "write_performed": False,
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }
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

def _preselection_pools(
    self, request: DispatchRequest
) -> dict[str, Any]:
    # The facade rebinds this handler's globals; helpers must be imported locally.
    from infrastructure.scheduling.executor_registry_preselection import (
        _hk_next_target_date, _hk_preselection_source_dates, _retry_missing_hk_only,
        _verified_formal_pool_reuse,
    )
    # HK pricing and eligibility follow their own frozen sessions, independently of A.
    try:
        hk_target_date = _hk_next_target_date(request.business_date)
        hk_signal_date, hk_eligibility_source_date = _hk_preselection_source_dates(
            request.business_date, hk_target_date
        )
    except ValueError as error:
        raise WorkloadExecutionError(
            self._failure_result("preselection_pools", [], str(error))
        ) from error
    hk_date_contract_error = (
        "HK_SPLIT_DATE_CONTRACT_UNSUPPORTED"
        if hk_signal_date != hk_eligibility_source_date else ""
    )
    # A pending journal must not be recovered as a side effect of an HK-only retry.
    pending = self.data_root / "preselection_pending_commits"
    local_day = self.data_root / "preselection_pools" / request.target_date
    if ((local_day / "a_d1_premarket_pool.json").exists()
            and not (self.data_root / "preselection_pools" / hk_target_date / "hkconnect_d1_top100.json").exists()
            and pending.exists() and any(pending.rglob("*.json"))):
        return {"status": "FAILED", "exit_code": 1, "failure_class": "UPSTREAM_NOT_READY",
            "reason": "HK_RETRY_PENDING_JOURNAL", "a_selector_status": "CANNOT_CONFIRM",
            "hk_lane_status": "QUARANTINED", "producer_called": False, "A_producer_called": False,
            "write_performed": False, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    reused = (self._verified_formal_pool_reuse(request.target_date)
        if hk_target_date == request.target_date and not hk_date_contract_error else None)
    if reused is not None and reused.get("hk_missing_retry"):
        return _retry_missing_hk_only(self, request, signal_date=hk_signal_date,
            target_date=hk_target_date, a_identity=reused["a_identity"],
            eligibility_source_date=hk_eligibility_source_date)
    if reused is not None and reused.get("hk_quality_rejected"):
        return reused  # keep exact A bytes; HK rejection must not fall through to paired producers
    hk_reused = (
        _verified_formal_pool_reuse(self, hk_target_date, _hk_only=True)
        if reused is None and not hk_date_contract_error else None
    )
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
    shared_entries = [
        self.shared_package_root / "scripts" / "capture_public_fupan.py",
    ]
    if reused is None:
        shared_entries.append(self.shared_package_root / "scripts" / "materialize_v192_selector.py")
        if not hk_date_contract_error and hk_reused is None:
            shared_entries.extend((
                self.shared_package_root / "scripts" / "update_hk_0_2_panel.py",
                self.shared_package_root / "scripts" / "materialize_hk_0_2.py",
            ))
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
    if reused is None and hk_reused is None and not hk_date_contract_error and not security_entry.is_file():
        raise WorkloadExecutionError(
            self._failure_result(
                "preselection_pools",
                modules,
                "fixed HK security-master entry missing",
            )
        )
    hk_universe_root = self.hk_universe_root
    if (self.shared_data_root.resolve() == self.hk_universe_root.resolve() / ".runtime" / "data"
            and (self.shared_data_root / "universes").is_dir()
            and (self.shared_data_root / "assets" / "hk_security_master").is_dir()):
        hk_universe_root = self.shared_data_root
    selector: Path | None = None
    selector_error = ""
    if self.selector_data_root is None:
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
    if selector_error and reused is None:
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
    public_result = self._run(
        "scripts.capture_public_fupan",
        ["--trade-date", request.business_date],
        cwd=self.shared_package_root,
        env=trusted_env,
    )
    if public_result["status"] != "SUCCEEDED":
        public_result = dict(public_result)
        public_result["lane"] = "A_SHARE_OPTIONAL" if reused is not None else "A_SHARE"
        public_result["status"] = "CANNOT_CONFIRM"
        (optional_lane_degradations if reused is not None else a_lane_degradations).append(public_result)
    if reused is not None:
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
    if reused is not None or hk_reused is not None:
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
    elif hk_date_contract_error:
        hk_result = self._failure_result("preselection_pools", [], hk_date_contract_error)
        hk_result.update(status="CANNOT_CONFIRM", lane="HK_CONNECT",
            first_gate="HK_DATE_CONTRACT", reason=hk_date_contract_error,
            failure_class="UPSTREAM_NOT_READY", producer_called=False, write_performed=False)
        hk_lane_degradations.append(dict(hk_result))
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
        security_result = self._run(
            "ops.ensure_hk_security_master",
            [
                "--store-root", str(self.shared_data_root),
                "--universe-root", str(hk_universe_root),
                "--shared-package-root", str(self.shared_package_root),
                "--trade-date", hk_eligibility_source_date,
                "--futu-python", str(self.shared_futu_python_executable),
                "--prepare-exact-date",
            ],
            cwd=self.repo_root,
            env=trusted_env,
        )
        if security_result["status"] != "SUCCEEDED":
            security_result = dict(security_result)
            security_result["lane"] = "HK_CONNECT"
            security_result["status"] = "CANNOT_CONFIRM"
            hk_lane_degradations.append(security_result)
        if hk_runtime_unavailable:
            hk_result = dict(update_result)
            hk_result["modules"] = ["scripts.materialize_hk_0_2"]
            hk_result["first_gate"] = "HK_RUNTIME"
        elif update_result["status"] != "SUCCEEDED" or security_result["status"] != "SUCCEEDED":
            # Preparation may run when its own output is absent. Scoring must
            # wait until both original-owner prerequisites have succeeded.
            failed_input = update_result if update_result["status"] != "SUCCEEDED" else security_result
            hk_result = dict(failed_input)
            hk_result["modules"] = ["scripts.materialize_hk_0_2"]
            hk_result["producer_called"] = False
            hk_result["first_gate"] = (
                "HK_PRICE_PANEL" if update_result["status"] != "SUCCEEDED" else "HK_SECURITY_MASTER"
            )
        else:
            hk_result = self._run(
                "scripts.materialize_hk_0_2",
                [
                    "--store-root", str(self.shared_data_root),
                    "--asset-root", str(self.shared_data_root / "assets" / "hk_0_2"),
                    "--signal-date", hk_signal_date,
                    "--target-date", hk_target_date,
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
    if selector is None:
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
    if lane_result["status"] != "SUCCEEDED":
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
        "--hk-target-date", hk_target_date,
        "--hk-signal-date", hk_signal_date,
        "--hk-eligibility-source-date", hk_eligibility_source_date,
        "--data-root", str(self.data_root),
        "--input-root", str(self.preselection_input_root),
        "--shared-data-root", str(self.shared_data_root),
        "--shared-package-root", str(self.shared_package_root),
    ]
    if selector is not None:
        arguments[6:6] = ["--selector", str(selector)]
    if reused is not None:
        arguments.append("--reuse-formal-pools")
    result = self._run("ops.materialize_scheduled_preselection", arguments)
    # The actual facade is not assumed to implement the canonical stdout
    # decoder. Consume only its existing authoritative-payload boundary.
    materializer_payload = result.get("_authoritative_payload")
    local_gate_present = isinstance(materializer_payload, dict) and "formal_pool_gate" in materializer_payload
    formal_pool_gate = materializer_payload.get("formal_pool_gate") if local_gate_present else None
    formal_required = (
        formal_pool_gate.get("required")
        if isinstance(formal_pool_gate, dict) and isinstance(formal_pool_gate.get("required"), dict)
        else {}
    )
    hk_local_gate = formal_required.get("hkconnect_d1_top100")
    hk_local_ready = not hk_date_contract_error and isinstance(hk_local_gate, dict) and hk_local_gate.get("ready") is True
    hk_local_research_ready = (
        not hk_date_contract_error
        and isinstance(hk_local_gate, dict)
        and hk_local_gate.get("research_ready") is True
        and hk_local_gate.get("status") == "PARTIAL_WITH_ROWS"
    )
    # Verified local reuse is the legacy contract when no gate is emitted.
    # An explicit rejection still wins over a previously verified pair.
    hk_local_accepted = (
        hk_local_ready
        or hk_local_research_ready
        or ((reused is not None or hk_reused is not None) and not local_gate_present)
    )
    result["hk_local_pool_gate_status"] = (
        "READY"
        if hk_local_ready
        else "PARTIAL_WITH_ROWS"
        if hk_local_research_ready
        else "CANNOT_CONFIRM"
        if local_gate_present
        else "UNAVAILABLE"
    )
    if isinstance(formal_pool_gate, dict):
        result["formal_pool_gate"] = formal_pool_gate
    result["modules"] = modules
    result["hk_target_date"] = hk_target_date
    result["hk_signal_date"] = hk_signal_date
    result["hk_eligibility_source_date"] = hk_eligibility_source_date
    if hk_date_contract_error:
        result["hk_date_contract_error"] = hk_date_contract_error
    result["formal_pool_reuse"] = (
        reused.get("formal_pool_reuse") if reused is not None else None
    )
    if hk_reused is not None:
        result["hk_lane_reuse"] = hk_reused
    result["a_selector_status"] = (
        "READY"
        if reused is not None
        else ("READY" if selector is not None and not a_lane_degradations else "CANNOT_CONFIRM")
    )
    result["hk_lane_status"] = (
        "READY"
        if (reused is not None or hk_reused is not None) and hk_local_accepted
        else "PARTIAL_WITH_ROWS" if hk_local_research_ready
        else "SUCCEEDED" if hk_local_ready
        else "CANNOT_CONFIRM"
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
    if not hk_local_accepted:
        # A/local materialization above remains available to its consumers.
        # A failed required HK lane must not settle this dispatch as successful
        # and thereby suppress the existing ledger's recoverable retry path.
        result["materializer_status"] = result["status"]
        result["status"] = "FAILED"
        result["exit_code"] = result.get("exit_code") or 1
        if not result.get("failure_class"):
            result["failure_class"] = hk_result.get("failure_class") or "UPSTREAM_NOT_READY"
        if reused is None and hk_result["status"] != "SUCCEEDED":
            result["first_gate"] = hk_result.get("first_gate") or "HK_SCORING"
            detail = str(hk_result.get("stderr") or hk_result.get("reason") or "HK input preparation not ready")
        else:
            result["first_gate"] = "HK_LOCAL_POOL" if local_gate_present else "HK_LOCAL_POOL_CONTRACT_UNAVAILABLE"
            detail = f"{result['first_gate']}: required local HK pool is not verified for target_date={request.target_date}"
        result["stderr"] = (str(result.get("stderr") or "") + "\n" + detail).strip()
    return result


def _retry_missing_hk_only(self, request, *, signal_date, target_date, a_identity, eligibility_source_date=None):
    """Retry one absent HK pool without entering any A or aggregate producer."""
    import hashlib
    import json
    from pathlib import Path
    from infrastructure.isolated_package_loader import load_isolated_package_module
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from domains.preselection_materializer import build_shared_hk_0_2_pool
    from infrastructure.interprocess_lock import owned_interprocess_lock

    pool_id = "hkconnect_d1_top100"
    calls = []
    wrote_consumer = False
    def result(reason, *, ready=False):
        retryable = reason.startswith("HK_RETRY_UPSTREAM_NOT_READY:") or reason in {
            "HK_RETRY_PENDING_JOURNAL", "HK_RETRY_RUNTIME_OR_UNIVERSE_MISSING", "HK_SPLIT_DATE_CONTRACT_UNSUPPORTED"}
        return {"status": "SUCCEEDED" if ready else "FAILED", "exit_code": 0 if ready else 1,
            "failure_class": None if ready else "UPSTREAM_NOT_READY" if retryable else "HK_HISTORY_RESOLUTION_CACHE_REJECTED",
            "reason": reason, "a_selector_status": "READY", "hk_lane_status": "READY" if ready else "CANNOT_CONFIRM" if retryable else "QUARANTINED",
            "a_exact_source_reused": a_identity, "hk_only_retry": True,
            "modules": list(calls), "producer_called": bool(calls), "A_producer_called": False,
            "write_performed": wrote_consumer or bool(calls), "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False}
    if eligibility_source_date is not None and eligibility_source_date != signal_date:
        return result("HK_SPLIT_DATE_CONTRACT_UNSUPPORTED")
    try:
        if self.shared_data_root is None or self.shared_package_root is None:
            raise ValueError("HK_RETRY_ROOT_NOT_CONFIGURED")
        root = Path(self.data_root)
        day = root / "preselection_pools" / target_date
        manifest_path = day / "manifest.json"
        hk_paths = (day / (pool_id + ".json"), day / "receipts" / (pool_id + ".json"),
            root / "preselection_pending_commits" / target_date / (pool_id + ".json"))
        def absent():
            manifest = json.loads(manifest_path.read_bytes()) if manifest_path.exists() else {}
            if not isinstance(manifest, dict) or pool_id in manifest or any(p.exists() for p in hk_paths):
                raise ValueError("HK_RETRY_LOCAL_PARTIAL_OR_RACE")
            return manifest
        before_manifest = absent()
        # Never let a ready-A retry reconcile an unrelated pending journal.
        pending = root / "preselection_pending_commits"
        if pending.exists() and any(pending.rglob("*.json")):
            raise ValueError("HK_RETRY_PENDING_JOURNAL")
        def protected():
            return {str(p.relative_to(day)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in day.rglob("*") if p.is_file() and p != manifest_path
                and p not in hk_paths and pool_id not in p.parts and p.name != pool_id + ".json"} if day.exists() else {}
        before_files = protected()
        module = load_isolated_package_module(self.shared_package_root,
            package_directory="shared_data", module_leaf="hk_0_2", namespace_prefix="hk_history_cache_gate")
        def read():
            arguments = {"target_date": target_date, "expected_signal_date": signal_date}
            pool = module.read_verified_hk_0_2_pool(self.shared_data_root, **arguments)
            if pool.run.receipt.get("status") != "READY" or len(pool.rows) != 100:
                raise ValueError("HK_RETRY_SOURCE_NOT_READY100")
            return pool
        source_store = module.SafeRootStore(Path(self.shared_data_root))
        source_key = source_store._entry_key(target_date,module.HK_0_2_ROLE)
        # Classify physical absence through the existing authoritative latest
        # contract before strict reader's master-first verification.
        missing_shared = source_key not in source_store._load_latest()["entries"]
        if not missing_shared:
            pool = read()  # existing run/master/proof failures remain HOLD
        else:
            if self.hk_universe_root is None or not self.hk_0_2_python_executable.is_file():
                raise ValueError("HK_RETRY_RUNTIME_OR_UNIVERSE_MISSING")
            runtime_error = self._hk_0_2_runtime_error()
            if runtime_error:
                raise ValueError(str(runtime_error))
            universe = self.hk_universe_root
            if (self.shared_data_root.resolve() == universe.resolve() / ".runtime" / "data"
                    and (self.shared_data_root / "universes").is_dir()
                    and (self.shared_data_root / "assets" / "hk_security_master").is_dir()):
                universe = self.shared_data_root
            import os
            env = os.environ.copy()
            env.update(V3_SHARED_DATA_STORE_ROOT=str(self.shared_data_root),
                V35_SHARED_PACKAGE_ROOT=str(self.shared_package_root),
                V3_SHARED_FUTU_PYTHON=str(self.shared_futu_python_executable),
                V35_HK_0_2_PYTHON=str(self.hk_0_2_python_executable),
                V3_SHARED_HK_TDX_ROOT=str(self.hk_0_2_tdx_root))
            steps = [
                ("scripts.update_hk_0_2_panel", ["--asset-root", str(self.shared_data_root / "assets" / "hk_0_2"),
                    "--tdx-root", str(self.hk_0_2_tdx_root), "--through-date", signal_date], self.shared_package_root, self.hk_0_2_python_executable),
                ("ops.ensure_hk_security_master", ["--store-root", str(self.shared_data_root), "--universe-root", str(universe),
                    "--shared-package-root", str(self.shared_package_root), "--trade-date", eligibility_source_date or signal_date,
                    "--futu-python", str(self.shared_futu_python_executable), "--prepare-exact-date"], self.repo_root, None),
                ("scripts.materialize_hk_0_2", ["--store-root", str(self.shared_data_root),
                    "--asset-root", str(self.shared_data_root / "assets" / "hk_0_2"),
                    "--signal-date", signal_date, "--target-date", target_date], self.shared_package_root, self.hk_0_2_python_executable)]
            for name, arguments, cwd, python in steps:
                if source_key in source_store._load_latest()["entries"]:
                    pool = read()  # a concurrent valid source may be consumed, never overwritten
                    break
                absent()
                if protected() != before_files or (json.loads(manifest_path.read_bytes()) if manifest_path.exists() else {}) != before_manifest:
                    raise ValueError("HK_RETRY_NON_HK_PREIMAGE_CHANGED")
                kwargs = {"cwd": cwd, "env": env}
                if python is not None: kwargs["python_executable"] = python
                calls.append(name)
                outcome = self._run(name, arguments, **kwargs)
                if outcome.get("status") != "SUCCEEDED":
                    return result("HK_RETRY_UPSTREAM_NOT_READY:" + name)
            else:
                pool = read()
        payload = build_shared_hk_0_2_pool(self.shared_data_root, trade_date=target_date,
            signal_date=signal_date, reader=lambda *a, **kw: pool)
        verification = pool.run.verification
        if (payload.get("pool_id") != pool_id or payload.get("market") != "HK"
                or payload.get("source_role") != "SHARED_VERIFIED_HK_0_2"
                or payload.get("source_sha256") != verification["artifact_sha256"]
                or payload.get("source_run_id") != verification["run_id"]
                or payload.get("status") not in {"READY", "STRICT_0_2_READY", "HK_0_2_TOP100_READY"}):
            raise ValueError("HK_RETRY_MAPPER_IDENTITY_MISMATCH")
        # READY is the deployed scheduler's local-cache status; raw source status stays in its run.
        payload["status"] = "READY"
        for field, value in {"signal_date": signal_date, "target_date": target_date,
                "source_manifest_sha256": verification["manifest_sha256"],
                "source_receipt_sha256": verification["receipt_sha256"]}.items():
            if field in payload and payload[field] != value:
                raise ValueError("HK_RETRY_MAPPER_PIN_MISMATCH")
            payload[field] = value
        cached_projection = [(str(row.get("code") or row.get("code_norm") or row.get("symbol") or "").strip(), str(row["rank"]).strip()) for row in payload["rows"]]
        source_projection = [(str(row["code_norm"]).strip(), str(row["rank"]).strip()) for row in pool.rows]
        if (cached_projection != source_projection or len(cached_projection) != 100
                or len({code for code, _ in cached_projection}) != 100
                or [rank for _, rank in cached_projection] != [str(i) for i in range(1, 101)]):
            raise ValueError("HK_RETRY_MAPPER_ROWS_MISMATCH")
        absent()
        if protected() != before_files or (json.loads(manifest_path.read_bytes()) if manifest_path.exists() else {}) != before_manifest:
            raise ValueError("HK_RETRY_NON_HK_PREIMAGE_CHANGED")
        store = PreselectionPoolStore(root)
        store._preflight_required_write_context(target_date, pool_id)
        with owned_interprocess_lock(root / ".import.lock", timeout_seconds=10,
                timeout_message="HK-only retry import lock timeout"):
            store._assert_write_allowed(target_date, pool_id)
            absent()
            if pending.exists() and any(pending.rglob("*.json")):
                raise ValueError("HK_RETRY_PENDING_JOURNAL")
            if protected() != before_files or (json.loads(manifest_path.read_bytes()) if manifest_path.exists() else {}) != before_manifest:
                raise ValueError("HK_RETRY_NON_HK_PREIMAGE_CHANGED")
            # Create-absent, including identical-payload races; no journal recovery.
            store._materialize_unlocked(payload)
            wrote_consumer = True
        if protected() != before_files or {k: v for k, v in json.loads(manifest_path.read_bytes()).items() if k != pool_id} != before_manifest:
            raise ValueError("HK_RETRY_NON_HK_POSTIMAGE_CHANGED")
        # The actual scheduler gate re-reads the exact stored payload and the same strict source.
        stored = PreselectionPoolStore(root).read_pool(target_date, pool_id)
        current = read()
        if (stored != payload or current.run.verification != pool.run.verification
                or [(str(r["code_norm"]).strip(), str(r["rank"]).strip()) for r in current.rows] != source_projection):
            raise ValueError("HK_RETRY_FINAL_SOURCE_OR_CACHE_CHANGED")
        formal_gate = getattr(self, "_verified_formal_pool_reuse", None)
        verified_pair = formal_gate(target_date) if formal_gate is not None else {
            "status": "SUCCEEDED", "hk_lane_status": "READY",
            "formal_pool_reuse": {"a_exact_source": a_identity,
                "hk_source_sha256": current.run.verification["artifact_sha256"], "hk_row_count": 100}}
        if not isinstance(verified_pair, dict) or verified_pair.get("status") != "SUCCEEDED" or verified_pair.get("hk_lane_status") != "READY":
            raise ValueError("HK_RETRY_FINAL_CACHE_GATE_REJECTED")
        output = result("HK_ONLY_MISSING_POOL_RETRY_READY", ready=True)
        output["formal_pool_reuse"] = verified_pair.get("formal_pool_reuse")
        return output
    except Exception as error:
        if type(error).__name__ not in {"StoreError"} and not isinstance(error, (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError)):
            raise
        return result(str(error))
