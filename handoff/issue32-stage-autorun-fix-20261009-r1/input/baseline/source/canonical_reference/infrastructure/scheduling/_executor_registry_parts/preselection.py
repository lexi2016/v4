"""infrastructure.scheduling.executor_registry: preselection (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


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
    if a_lane_eligible and a_exact_source is None:
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
    return result
