"""infrastructure.scheduling.executor_registry: preselection (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _FixedExecutorRegistry__verified_preselection_source_body(_v4_scope, /, self, *, module_leaf, reader_name, target_date, signal_date):
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
        pool = reader(
            self.shared_data_root,
            target_date=target_date,
            expected_signal_date=signal_date,
        )
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
    if self.preselection_input_root is None:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "preselection_pools",
                modules,
                "preselection input root not configured",
            )
        )
    a_exact_source, _a_exact_error = self._verified_preselection_source(
        module_leaf="v192_selector",
        reader_name="read_verified_v192_pool",
        target_date=request.target_date,
        signal_date=request.business_date,
    )
    hk_exact_source, hk_exact_error = self._verified_preselection_source(
        module_leaf="hk_0_2",
        reader_name="read_verified_hk_0_2_pool",
        target_date=request.target_date,
        signal_date=request.business_date,
    )
    def missing_entries(paths):
        missing = [str(path) for path in paths if not path.is_file()]
        return "fixed producer entry missing: " + ", ".join(missing) if missing else ""

    public_entry_error = missing_entries((self.shared_package_root / "scripts" / "capture_public_fupan.py",))
    a_entry_error = "" if a_exact_source is not None else missing_entries((
        self.shared_package_root / "scripts" / "materialize_v192_selector.py",
    ))
    hk_configuration_error = ""
    if hk_exact_source is None:
        if self.hk_universe_root is None:
            hk_configuration_error = "HK_UNIVERSE_ROOT_NOT_CONFIGURED"
        else:
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
    if a_exact_source is None:
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
    selector_gap = a_entry_error or selector_error or (
        "selector panel unresolved" if selector is None and a_exact_source is None else ""
    )
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
    if public_entry_error:
        public_result = self._failure_result("preselection_pools", ["scripts.capture_public_fupan"], public_entry_error)
    else:
        public_result = self._run(
            "scripts.capture_public_fupan",
            ["--trade-date", request.business_date],
            cwd=self.shared_package_root,
            env=trusted_env,
        )
    if public_result["status"] != "SUCCEEDED":
        public_result = _v4_global(_v4_scope, 'dict')(public_result)
        public_result["lane"] = "A_SHARE"
        public_result["status"] = "CANNOT_CONFIRM"
        a_lane_degradations.append(public_result)
    if a_exact_source is not None:
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
    hk_runtime_error = (
        None if hk_exact_source is not None else (hk_configuration_error or self._hk_0_2_runtime_error())
    )
    hk_runtime_missing = (
        False
        if hk_exact_source is not None
        else self._runner is _v4_global(_v4_scope, '_default_runner') and not self.hk_0_2_python_executable.is_file()
    )
    hk_runtime_unavailable = hk_runtime_error is not None or hk_runtime_missing
    if hk_exact_source is not None:
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
                "--through-date", request.business_date,
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
    if hk_exact_source is not None or hk_configuration_error:
        security_result = _v4_global(_v4_scope, 'dict')(update_result)
    else:
        security_result = self._run(
            "ops.ensure_hk_security_master",
            [
                "--store-root", _v4_global(_v4_scope, 'str')(self.shared_data_root),
                "--universe-root", _v4_global(_v4_scope, 'str')(self.hk_universe_root),
                "--shared-package-root", _v4_global(_v4_scope, 'str')(self.shared_package_root),
                "--trade-date", request.business_date,
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
    if hk_exact_source is not None:
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
                "--signal-date", request.business_date,
                "--target-date", request.target_date,
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
    if hk_exact_source is None and hk_exact_error and hk_result.get("status") != "SUCCEEDED":
        hk_lane_degradations.append({
            "status": "CANNOT_CONFIRM",
            "lane": "HK_CONNECT",
            "module": "shared_data.hk_0_2.read_verified_hk_0_2_pool",
            "reason": hk_exact_error,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    if selector is None:
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
    if lane_result["status"] != "SUCCEEDED":
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
    arguments = [
        "--trade-date", request.target_date,
        "--signal-date", request.business_date,
        "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
        "--input-root", _v4_global(_v4_scope, 'str')(self.preselection_input_root),
        "--shared-data-root", _v4_global(_v4_scope, 'str')(self.shared_data_root),
        "--shared-package-root", _v4_global(_v4_scope, 'str')(self.shared_package_root),
    ]
    if selector is not None:
        arguments[6:6] = ["--selector", _v4_global(_v4_scope, 'str')(selector)]
    result = self._run("ops.materialize_scheduled_preselection", arguments)
    result["modules"] = modules
    result["a_selector_status"] = (
        "READY"
        if a_exact_source is not None
        or (selector is not None and shared_result.get("status") == "SUCCEEDED")
        else "CANNOT_CONFIRM"
    )
    result["hk_lane_status"] = (
        "SUCCEEDED"
        if hk_exact_source is not None
        or (hk_result["status"] == "SUCCEEDED" and not hk_lane_degradations)
        else "CANNOT_CONFIRM"
    )
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
