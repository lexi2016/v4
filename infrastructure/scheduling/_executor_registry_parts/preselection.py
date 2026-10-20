"""infrastructure.scheduling.executor_registry: preselection (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global

_EXACT_HK_POOL_LATEST_RUN_MISSING = "EXACT_HK_POOL_LATEST_RUN_MISSING"


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
    """Return the next HK securities session after the workload business date."""
    from contracts.trading_calendar import load_market_calendar, next_session

    return next_session(
        load_market_calendar(), business_date, market="hk_securities"
    )


def _hk_preselection_source_dates(
    business_date: str,
    hk_target_date: str,
) -> tuple[str, str]:
    """Bind price features to the business-date HK close and eligibility to D-1 Connect."""
    from contracts.trading_calendar import (
        TradingDayState,
        load_market_calendar,
        next_session,
        previous_session,
        resolve_market_states,
    )

    calendar = load_market_calendar()
    expected_target = next_session(
        calendar, business_date, market="hk_securities"
    )
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


def _preselection_market_lane_states(trade_date: str) -> tuple[str, str]:
    """Return this workload's independent A and HK-securities day states."""
    from contracts.trading_calendar import load_market_calendar, resolve_market_states

    states = resolve_market_states(load_market_calendar(), trade_date)
    return states["a_share"].value, states["hk_securities"].value


def _FixedExecutorRegistry__verified_preselection_source_body(
    _v4_scope,
    /,
    self,
    *,
    module_leaf,
    reader_name,
    target_date,
    signal_date,
    eligibility_source_date=None,
):
    """Read an exact V4 shared source before deciding to run its producer."""
    if self.shared_data_root is None or self.shared_package_root is None:
        return None, "shared source root not configured"
    module = None
    try:
        module = _v4_global(_v4_scope, 'load_isolated_package_module')(
            self.shared_package_root,
            package_directory="shared_data",
            module_leaf=module_leaf,
            namespace_prefix=f"v35_preselection_{module_leaf}",
        )
        reader = _v4_global(_v4_scope, 'getattr')(module, reader_name)
        reader_arguments = {
            "target_date": target_date,
            "expected_signal_date": signal_date,
        }
        if eligibility_source_date and eligibility_source_date != signal_date:
            reader_arguments["expected_eligibility_source_date"] = eligibility_source_date
        pool = reader(self.shared_data_root, **reader_arguments)
        receipt = _v4_global(_v4_scope, 'dict')(pool.run.receipt)
        if receipt.get("status") != "READY" or _v4_global(_v4_scope, 'any')(
            receipt.get(field) is not False
            for field in ("production_allowed", "buy_gate_updated", "orders_sent")
        ):
            return None, "exact source receipt is not READY/research-safe"
        if module_leaf == "hk_0_2":
            # This source-only path has no cached row projection to reuse.
            # Require the exact verified pool's complete ordered code/rank projection.
            hk_rows = list(pool.rows)
            hk_projection = [(str(row["code_norm"]).strip(), str(row["rank"]).strip()) for row in hk_rows]
            if (len(hk_projection) != 100
                    or [rank for _, rank in hk_projection] != [str(i) for i in range(1, 101)]
                    or len({code for code, _ in hk_projection}) != 100
                    or any(not code for code, _ in hk_projection)):
                return None, "HK_HISTORY_RESOLUTION_SOURCE_ROWS_MISMATCH"
            from contracts.trading_calendar import load_market_calendar, previous_session
            import math
            if (signal_date != previous_session(load_market_calendar(), target_date, market="hk_securities")
                    or any(str(row.get("signal_date") or "") != signal_date
                        or str(row.get("target_date") or "") != target_date for row in hk_rows)
                    or any(not math.isfinite(float(row["score_prob_active"])) for row in hk_rows)):
                return None, "HK_HISTORY_RESOLUTION_SOURCE_DATE_OR_SCORE_MISMATCH"
        return {
            "status": "READY",
            "run_id": receipt.get("run_id"),
            "artifact_sha256": pool.run.verification.get("artifact_sha256"),
            "row_count": pool.run.verification.get("row_count"),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ""
    except _v4_global(_v4_scope, 'Exception') as error:
        if _v4_global(_v4_scope, 'type')(error).__name__ not in {"StoreError", "ModuleNotFoundError"} and not _v4_global(_v4_scope, 'isinstance')(
            error, (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'AttributeError'))
        ):
            raise
        store_error_type = (
            _v4_global(_v4_scope, 'getattr')(module, "StoreError", None)
            if module is not None
            else None
        )
        hk_0_2_role = (
            _v4_global(_v4_scope, 'getattr')(module, "HK_0_2_ROLE", None)
            if module is not None
            else None
        )
        if (
            module_leaf == "hk_0_2"
            and reader_name == "read_verified_hk_0_2_pool"
            and store_error_type is not None
            and hk_0_2_role
            and _v4_global(_v4_scope, 'isinstance')(error, store_error_type)
            and _v4_global(_v4_scope, 'str')(error)
            == f"no latest run for {target_date} / {hk_0_2_role}"
        ):
            return None, _EXACT_HK_POOL_LATEST_RUN_MISSING
        return None, _v4_global(_v4_scope, 'str')(error)


def _FixedExecutorRegistry__preselection_pools_body(_v4_scope, /, self, request):
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
        or self.shared_package_root is None
    ):
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "preselection_pools",
                modules,
                "shared data root and shared package root are required",
            )
        )
    try:
        hk_target_date = _hk_next_target_date(request.business_date)
        hk_signal_date, hk_eligibility_source_date = _hk_preselection_source_dates(
            request.business_date, hk_target_date
        )
    except ValueError as error:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result("preselection_pools", modules, str(error))
        ) from error
    a_market_state, hk_market_state = _preselection_market_lane_states(
        request.business_date
    )
    trading_states = {"FULL_TRADING_DAY", "HALF_TRADING_DAY_AM"}
    a_lane_eligible = a_market_state in trading_states
    # A may be open on an HK holiday: still prepare the next HK session
    # from its last real close rather than skipping the HK producer.
    _, hk_market_state = _preselection_market_lane_states(hk_target_date)
    hk_lane_eligible = hk_market_state in trading_states
    if a_lane_eligible and self.preselection_input_root is None:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result("preselection_pools", modules, "preselection input root not configured")
        )
    materializer_input_root = self.preselection_input_root or (self.data_root / "preselection_inputs")
    if a_lane_eligible:
        a_exact_source, _a_exact_error = self._verified_preselection_source(
            module_leaf="v192_selector",
            reader_name="read_verified_v192_pool",
            target_date=request.target_date,
            signal_date=request.business_date,
        )
    else:
        a_exact_source, _a_exact_error = None, ""
    if hk_lane_eligible:
        hk_exact_source, hk_exact_error = _FixedExecutorRegistry__verified_preselection_source_body(
            _v4_scope,
            self,
            module_leaf="hk_0_2",
            reader_name="read_verified_hk_0_2_pool",
            target_date=hk_target_date,
            signal_date=hk_signal_date,
            eligibility_source_date=hk_eligibility_source_date,
        )
    else:
        hk_exact_source, hk_exact_error = None, ""
    if (
        a_exact_source is not None
        and hk_lane_eligible
        and hk_exact_source is None
        and hk_exact_error != _EXACT_HK_POOL_LATEST_RUN_MISSING
    ):
        return {"status":"FAILED", "exit_code":1, "failure_class":"HK_HISTORY_RESOLUTION_CACHE_REJECTED",
            "a_selector_status":"READY", "hk_lane_status":"QUARANTINED",
            "a_exact_source_reused":a_exact_source,"producer_called":False,"write_performed":False,
            "production_allowed":False,"buy_gate_updated":False,"orders_sent":False}
    if a_exact_source is not None and hk_lane_eligible:
        local_hk = self.data_root / "preselection_pools" / hk_target_date / "hkconnect_d1_top100.json"
        if ((hk_exact_source is None and hk_exact_error == _EXACT_HK_POOL_LATEST_RUN_MISSING)
                or (not local_hk.exists() and hk_exact_source is not None)):
            return _retry_missing_hk_only(self, request, signal_date=hk_signal_date,
                target_date=hk_target_date, a_identity=a_exact_source,
                eligibility_source_date=hk_eligibility_source_date)
    def missing_entries(paths):
        missing = [str(path) for path in paths if not path.is_file()]
        return "fixed producer entry missing: " + ", ".join(missing) if missing else ""

    public_entry_error = missing_entries((self.shared_package_root / "scripts" / "capture_public_fupan.py",)) if a_lane_eligible else ""
    a_entry_error = "" if (not a_lane_eligible or a_exact_source is not None) else missing_entries((
        self.shared_package_root / "scripts" / "materialize_v192_selector.py",
    ))
    hk_configuration_error = ""
    hk_universe_root = self.hk_universe_root

    def has_canonical_hk_authority_layout(root):
        return (
            root is not None
            and root.is_dir()
            and (root / "universes").is_dir()
            and (root / "assets" / "hk_security_master").is_dir()
        )

    if hk_lane_eligible and hk_exact_source is None:
        if self.hk_universe_root is None:
            hk_configuration_error = "HK_UNIVERSE_ROOT_NOT_CONFIGURED"
        else:
            configured_universe_root = self.hk_universe_root.expanduser().resolve()
            shared_store_root = (
                self.shared_data_root.expanduser().resolve()
                if self.shared_data_root is not None
                else None
            )
            if (
                shared_store_root is not None
                and shared_store_root == configured_universe_root / ".runtime" / "data"
                and has_canonical_hk_authority_layout(self.shared_data_root)
            ):
                # The active LaunchAgent keeps the outer workspace root for
                # manager close recapture.  HK preselection consumes the
                # existing canonical child only for this exact root relation.
                hk_universe_root = self.shared_data_root
            elif has_canonical_hk_authority_layout(self.hk_universe_root):
                # Separate store and universe roots remain valid when the
                # explicitly configured universe root has the canonical HK
                # authority layout.
                hk_universe_root = self.hk_universe_root
            else:
                hk_configuration_error = "HK_UNIVERSE_ROOT_INVALID"
            if not hk_configuration_error:
                hk_configuration_error = missing_entries((
                    self.shared_package_root / "scripts" / "update_hk_0_2_panel.py",
                    self.shared_package_root / "scripts" / "materialize_hk_0_2.py",
                    (self.repo_root or _v4_global(_v4_scope, 'Path').cwd()) / "ops" / "ensure_hk_security_master.py",
                ))
    generation_pointer = _v4_global(_v4_scope, 'str')(
        _v4_global(_v4_scope, 'os').environ.get("V35_RESEARCH_PANEL_A_FORMULA_GENERATION_POINTER") or ""
    ).strip()
    selector: Path | None = None
    selector_error = ""
    # D-1 review lanes also consume the close panel when the main pool is reused.
    if a_lane_eligible:
        if self.selector_data_root is None and not generation_pointer:
            selector_error = "selector data root not configured"
        else:
            try:
                if generation_pointer:
                    selector = _v4_global(_v4_scope, 'resolve_selector_panel')(
                        self.selector_data_root,
                        request.business_date,
                        formula_generation_pointer=generation_pointer,
                    )
                else:
                    # Keep the legacy two-argument call shape for registry
                    # fixtures and compatibility consumers.  The strict V4
                    # path is selected only when its explicit pointer exists.
                    selector = _v4_global(_v4_scope, 'resolve_selector_panel')(
                        self.selector_data_root, request.business_date
                    )
            except _v4_global(_v4_scope, 'FileNotFoundError') as error:
                selector_error = f"selector panel unresolved: {error}"
    selector_gap = (a_entry_error or selector_error or (
        "selector panel unresolved" if selector is None and a_exact_source is None else ""
    )) if a_lane_eligible else ""
    trusted_env = _v4_global(_v4_scope, 'os').environ.copy()
    trusted_env.update({
        "V3_SHARED_DATA_STORE_ROOT": _v4_global(_v4_scope, 'str')(self.shared_data_root),
        "V35_SHARED_PACKAGE_ROOT": _v4_global(_v4_scope, 'str')(self.shared_package_root),
        "V3_SHARED_FUTU_PYTHON": _v4_global(_v4_scope, 'str')(self.shared_futu_python_executable),
        "V35_HK_0_2_PYTHON": _v4_global(_v4_scope, 'str')(self.hk_0_2_python_executable),
        "V3_SHARED_HK_TDX_ROOT": _v4_global(_v4_scope, 'str')(self.hk_0_2_tdx_root),
    })
    if selector is not None:
        trusted_env["V3_SHARED_SELECTOR_READY_PANEL"] = _v4_global(_v4_scope, 'str')(selector)
    else:
        trusted_env.pop("V3_SHARED_SELECTOR_READY_PANEL", None)
    a_lane_degradations: list[dict[str, Any]] = []
    if not a_lane_eligible:
        status = "SKIPPED" if a_market_state == "NON_TRADING_DAY" else "CANNOT_CONFIRM"
        public_result = {
            "status": status,
            "lane": "A_SHARE",
            "reason": "A_SHARE_NON_TRADING_DAY" if status == "SKIPPED" else "A_SHARE_CALENDAR_UNKNOWN",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if status == "CANNOT_CONFIRM":
            a_lane_degradations.append(public_result)
    elif public_entry_error:
        public_result = self._failure_result("preselection_pools", ["scripts.capture_public_fupan"], public_entry_error)
    else:
        public_result = self._run(
            "scripts.capture_public_fupan",
            ["--trade-date", request.business_date],
            cwd=self.shared_package_root,
            env=trusted_env,
        )
    if a_lane_eligible and public_result["status"] != "SUCCEEDED":
        public_result = _v4_global(_v4_scope, 'dict')(public_result)
        public_result["lane"] = "A_SHARE"
        public_result["status"] = "CANNOT_CONFIRM"
        a_lane_degradations.append(public_result)
    if not a_lane_eligible:
        shared_result = {
            "status": "SKIPPED" if a_market_state == "NON_TRADING_DAY" else "CANNOT_CONFIRM",
            "lane": "A_SHARE",
            "reason": "A_SHARE_NON_TRADING_DAY" if a_market_state == "NON_TRADING_DAY" else "A_SHARE_CALENDAR_UNKNOWN",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if shared_result["status"] == "CANNOT_CONFIRM":
            a_lane_degradations.append(shared_result)
    elif a_exact_source is not None:
        shared_result = {
            "status": "SUCCEEDED",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "lane": "A_SHARE",
            "exact_source_reused": a_exact_source,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    elif selector_gap:
        shared_result = {
                "status": "CANNOT_CONFIRM",
                "lane": "A_SHARE",
                "module": "ops.materialize_shared_v192_preselection",
                "workload_id": "ops.materialize_shared_v192_preselection",
                "reason": selector_gap,
                "stderr": selector_gap,
                "failure_class": "UPSTREAM_NOT_READY",
                "signal_date": request.business_date,
                "target_date": request.target_date,
                "first_gate": "PRODUCER_ENTRY" if a_entry_error else "SOURCE_PANEL",
                "producer_called": False,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
        }
        a_lane_degradations.append(shared_result)
    else:
        shared_result = self._run(
            "ops.materialize_shared_v192_preselection",
            [
                "--signal-date", request.business_date,
                "--target-date", request.target_date,
                *(["--generation-pointer", generation_pointer] if generation_pointer else []),
            ],
            cwd=self.repo_root,
            env=trusted_env,
            timeout_seconds=_v4_global(_v4_scope, '_V192_PRESELECTION_TIMEOUT_SECONDS'),
        )
        if shared_result["status"] != "SUCCEEDED":
            shared_result = _v4_global(_v4_scope, 'dict')(shared_result)
            shared_result["lane"] = "A_SHARE"
            shared_result["status"] = "CANNOT_CONFIRM"
            a_lane_degradations.append(shared_result)
    # The selector is required by the A v1.9.2 producer above only.  The
    # public fupan, HK 0.2, D-1 optional, and scheduled materializer lanes
    # remain independent and continue with an explicit A gap.
    hk_lane_degradations: list[dict[str, Any]] = []
    hk_runtime_error = None if (not hk_lane_eligible or hk_exact_source is not None) else (hk_configuration_error or self._hk_0_2_runtime_error())
    hk_runtime_missing = (
        False
        if not hk_lane_eligible or hk_exact_source is not None
        else self._runner is _v4_global(_v4_scope, '_default_runner') and not self.hk_0_2_python_executable.is_file()
    )
    hk_runtime_unavailable = hk_runtime_error is not None or hk_runtime_missing
    if not hk_lane_eligible:
        update_result = {
            "status": "SKIPPED" if hk_market_state == "NON_TRADING_DAY" else "CANNOT_CONFIRM",
            "lane": "HK_CONNECT",
            "reason": "HK_SECURITIES_NON_TRADING_DAY" if hk_market_state == "NON_TRADING_DAY" else "HK_SECURITIES_CALENDAR_UNKNOWN",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if update_result["status"] == "CANNOT_CONFIRM":
            hk_lane_degradations.append(update_result)
    elif hk_exact_source is not None:
        update_result = {
            "status": "SUCCEEDED", "exit_code": 0, "stdout": "", "stderr": "",
            "lane": "HK_CONNECT", "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False,
        }
    elif hk_runtime_unavailable:
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
                "--asset-root", _v4_global(_v4_scope, 'str')(self.shared_data_root / "assets" / "hk_0_2"),
                "--tdx-root", _v4_global(_v4_scope, 'str')(self.hk_0_2_tdx_root),
                "--through-date", hk_signal_date,
            ],
            cwd=self.shared_package_root,
            env=trusted_env,
            python_executable=self.hk_0_2_python_executable,
        )
        if update_result["status"] != "SUCCEEDED":
            update_result = _v4_global(_v4_scope, 'dict')(update_result)
            update_result["lane"] = "HK_CONNECT"
            update_result["status"] = "CANNOT_CONFIRM"
            hk_lane_degradations.append(update_result)
    if not hk_lane_eligible:
        security_result = _v4_global(_v4_scope, 'dict')(update_result)
    elif hk_exact_source is not None or hk_configuration_error:
        security_result = _v4_global(_v4_scope, 'dict')(update_result)
    else:
        security_result = self._run(
            "ops.ensure_hk_security_master",
            [
                "--store-root", _v4_global(_v4_scope, 'str')(self.shared_data_root),
                "--universe-root", _v4_global(_v4_scope, 'str')(hk_universe_root),
                "--shared-package-root", _v4_global(_v4_scope, 'str')(self.shared_package_root),
                "--trade-date", hk_eligibility_source_date,
                "--futu-python", _v4_global(_v4_scope, 'str')(self.shared_futu_python_executable),
                "--prepare-exact-date",
            ],
            cwd=self.repo_root,
            env=trusted_env,
        )
        if security_result["status"] != "SUCCEEDED":
            security_result = _v4_global(_v4_scope, 'dict')(security_result)
            security_result["lane"] = "HK_CONNECT"
            security_result["status"] = "CANNOT_CONFIRM"
            hk_lane_degradations.append(security_result)
    if not hk_lane_eligible:
        hk_result = _v4_global(_v4_scope, 'dict')(update_result)
        hk_result["modules"] = ["scripts.materialize_hk_0_2"]
    elif hk_exact_source is not None:
        hk_result = {**update_result, "exact_source_reused": hk_exact_source}
    elif hk_runtime_unavailable:
        hk_result = _v4_global(_v4_scope, 'dict')(update_result)
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
                "--store-root", _v4_global(_v4_scope, 'str')(self.shared_data_root),
                "--asset-root", _v4_global(_v4_scope, 'str')(self.shared_data_root / "assets" / "hk_0_2"),
                "--signal-date", hk_signal_date,
                "--eligibility-source-date", hk_eligibility_source_date,
                "--target-date", hk_target_date,
            ],
            cwd=self.shared_package_root,
            env=trusted_env,
            python_executable=self.hk_0_2_python_executable,
        )
        if hk_result["status"] != "SUCCEEDED":
            hk_result = _v4_global(_v4_scope, 'dict')(hk_result)
            hk_result["lane"] = "HK_CONNECT"
            hk_result["status"] = "CANNOT_CONFIRM"
            hk_lane_degradations.append(hk_result)
    if hk_lane_eligible and hk_exact_source is None and hk_exact_error and hk_result.get("status") != "SUCCEEDED":
        hk_lane_degradations.append({
            "status": "CANNOT_CONFIRM",
            "lane": "HK_CONNECT",
            "module": "shared_data.hk_0_2.read_verified_hk_0_2_pool",
            "reason": hk_exact_error,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    if not a_lane_eligible:
        lane_result = {
            "status": "SKIPPED" if a_market_state == "NON_TRADING_DAY" else "CANNOT_CONFIRM",
            "lane": "A_SHARE",
            "reason": "A_SHARE_NON_TRADING_DAY" if a_market_state == "NON_TRADING_DAY" else "A_SHARE_CALENDAR_UNKNOWN",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    elif selector is None:
        lane_result = {
            "status": "CANNOT_CONFIRM",
            "exit_code": 1,
            "stdout": "",
            "stderr": selector_gap,
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
                "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
                "--preselection-input-root", _v4_global(_v4_scope, 'str')(self.preselection_input_root),
                "--shared-data-root", _v4_global(_v4_scope, 'str')(self.shared_data_root),
                "--shared-package-root", _v4_global(_v4_scope, 'str')(self.shared_package_root),
                "--selector", _v4_global(_v4_scope, 'str')(selector),
                *(
                    ["--stage-selection-root", _v4_global(_v4_scope, 'str')(self.stage_selection_root)]
                    if self.stage_selection_root is not None
                    else []
                ),
            ],
        )
    optional_lane_degradation = None
    if a_lane_eligible and lane_result["status"] != "SUCCEEDED":
        # The D-1 review lanes enrich the fupan/stage7 optional pools.  The
        # scheduled materializer already emits explicit CANNOT_CONFIRM
        # artifacts when those inputs are unavailable, so they must not
        # suppress the independently verified A v1.9.2 and HK 0.2 pools.
        optional_lane_degradation = {
            "status": "CANNOT_CONFIRM",
            "module": "ops.materialize_d1_review_lanes",
            "exit_code": lane_result["exit_code"],
            "stdout": lane_result["stdout"],
            "stderr": lane_result["stderr"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    if not a_lane_eligible and not hk_lane_eligible:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result("preselection_pools", modules, "no market lane is eligible on the business date")
        )
    market_scope = (
        "CROSS_MARKET" if a_lane_eligible and hk_lane_eligible
        else "A_SHARE" if a_lane_eligible
        else "HK_CONNECT"
    )
    arguments = [
        "--trade-date", request.target_date,
        "--signal-date", request.business_date,
        "--market-scope", market_scope,
        "--hk-signal-date", hk_signal_date,
        "--hk-eligibility-source-date", hk_eligibility_source_date,
        "--hk-target-date", hk_target_date,
        "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
        "--input-root", _v4_global(_v4_scope, 'str')(materializer_input_root),
        "--shared-data-root", _v4_global(_v4_scope, 'str')(self.shared_data_root),
        "--shared-package-root", _v4_global(_v4_scope, 'str')(self.shared_package_root),
    ]
    if selector is not None:
        arguments[6:6] = ["--selector", _v4_global(_v4_scope, 'str')(selector)]
    result = self._run("ops.materialize_scheduled_preselection", arguments)
    materializer_payload = self._decoded_stdout(result)
    formal_pool_gate = materializer_payload.get("formal_pool_gate")
    formal_required = (
        formal_pool_gate.get("required")
        if isinstance(formal_pool_gate, dict) and isinstance(formal_pool_gate.get("required"), dict)
        else {}
    )
    result["modules"] = modules
    result["hk_target_date"] = hk_target_date
    result["hk_signal_date"] = hk_signal_date
    result["hk_eligibility_source_date"] = hk_eligibility_source_date
    a_gate = formal_required.get("a_d1_premarket_pool")
    hk_gate = formal_required.get("hkconnect_d1_top100")
    result["a_lane_status"] = (
        "NOT_APPLICABLE"
        if a_market_state == "NON_TRADING_DAY"
        else "CANNOT_CONFIRM"
        if not a_lane_eligible
        else "SUCCEEDED" if isinstance(a_gate, dict) and a_gate.get("ready") is True
        else "CANNOT_CONFIRM"
    )
    result["a_selector_status"] = result["a_lane_status"]
    result["hk_lane_status"] = (
        "NOT_APPLICABLE"
        if hk_market_state == "NON_TRADING_DAY"
        else "CANNOT_CONFIRM"
        if not hk_lane_eligible
        else "SUCCEEDED" if isinstance(hk_gate, dict) and hk_gate.get("ready") is True
        else "CANNOT_CONFIRM"
    )
    if isinstance(formal_pool_gate, dict):
        result["formal_pool_gate"] = formal_pool_gate
    if a_exact_source is not None:
        result["a_exact_source_reused"] = a_exact_source
    if hk_exact_source is not None:
        result["hk_exact_source_reused"] = hk_exact_source
    if a_lane_degradations:
        result["a_lane_degradations"] = a_lane_degradations
    if hk_lane_degradations:
        result["hk_lane_degradations"] = hk_lane_degradations
    if optional_lane_degradation is not None:
        result["optional_d1_review_lane"] = optional_lane_degradation
    if hk_lane_eligible and result["hk_lane_status"] != "SUCCEEDED":
        # Keep independently verified A output while leaving the failed HK
        # lane recoverable through the dispatcher's existing retry contract.
        result["materializer_status"] = result["status"]
        result["status"] = "FAILED"
        result["exit_code"] = result.get("exit_code") or 1
        if not result.get("failure_class"):
            result["failure_class"] = hk_result.get("failure_class") or "UPSTREAM_NOT_READY"
        if hk_result["status"] != "SUCCEEDED":
            result["first_gate"] = hk_result.get("first_gate") or "HK_SCORING"
            detail = str(hk_result.get("stderr") or hk_result.get("reason") or "HK input preparation not ready")
        else:
            result["first_gate"] = "HK_LOCAL_POOL"
            detail = f"HK_LOCAL_POOL: required local HK pool is not verified for target_date={hk_target_date}"
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
            "HK_RETRY_PENDING_JOURNAL", "HK_RETRY_RUNTIME_OR_UNIVERSE_MISSING"}
        return {"status": "SUCCEEDED" if ready else "FAILED", "exit_code": 0 if ready else 1,
            "failure_class": None if ready else "UPSTREAM_NOT_READY" if retryable else "HK_HISTORY_RESOLUTION_CACHE_REJECTED",
            "reason": reason, "a_selector_status": "READY", "hk_lane_status": "READY" if ready else "CANNOT_CONFIRM" if retryable else "QUARANTINED",
            "a_exact_source_reused": a_identity, "hk_only_retry": True,
            "modules": list(calls), "producer_called": bool(calls), "A_producer_called": False,
            "write_performed": wrote_consumer or bool(calls), "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False}
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
            if eligibility_source_date is not None and eligibility_source_date != signal_date:
                arguments["expected_eligibility_source_date"] = eligibility_source_date
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
                    "--signal-date", signal_date, "--target-date", target_date,
                    *(["--eligibility-source-date", eligibility_source_date] if eligibility_source_date is not None else [])], self.shared_package_root, self.hk_0_2_python_executable)]
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
