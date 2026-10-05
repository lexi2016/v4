"""infrastructure.scheduling.executor_registry: close_review (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _FixedExecutorRegistry__review_core_pool_pipeline_body(_v4_scope, /, self, request):
    """Run the verified natural Review Core adapter at the 21:15 slot."""
    module = "ops.run_review_core_natural_pool_pipeline"
    package_root = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get("V35_REVIEW_CORE_PACKAGE_ROOT", _v4_global(_v4_scope, 'str')(self.data_root / "review_core"))
    )
    shared_package_root = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get(
            "V35_REVIEW_CORE_SHARED_PACKAGE_ROOT",
            _v4_global(_v4_scope, 'str')(self.shared_package_root or self.data_root / "shared_package"),
        )
    )
    shared_store_root = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get(
            "V35_REVIEW_CORE_SHARED_STORE_ROOT",
            _v4_global(_v4_scope, 'str')(self.shared_data_root or self.data_root / "shared_store"),
        )
    )
    runtime_root = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').environ.get("V35_REVIEW_CORE_RUNTIME_ROOT", _v4_global(_v4_scope, 'str')(self.data_root)))
    calendar_path = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get(
            "V35_REVIEW_CORE_CALENDAR_PATH",
            _v4_global(_v4_scope, 'str')((self.repo_root or _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, '__file__')).resolve().parents[2]) / "contracts" / "market_calendar_2026.json"),
        )
    )
    hk_root = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get("V35_REVIEW_CORE_HK_ROOT", _v4_global(_v4_scope, 'str')(self.hk_universe_root or self.data_root / "hk"))
    )
    close_root = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').environ.get("V35_REVIEW_CORE_CLOSE_ROOT", _v4_global(_v4_scope, 'str')(self.data_root / "close_reviews")))
    fupan_root = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get("V35_REVIEW_CORE_FUPAN_STORE_ROOT", _v4_global(_v4_scope, 'str')(self.data_root / "fupan_store"))
    )
    stage7_root = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get("V35_REVIEW_CORE_STAGE7_STORE_ROOT", _v4_global(_v4_scope, 'str')(self.data_root / "stage7_store"))
    )
    bundle_root = _v4_global(_v4_scope, 'Path')(
        _v4_global(_v4_scope, 'os').environ.get("V35_REVIEW_CORE_BUNDLE_ROOT", _v4_global(_v4_scope, 'str')(self.data_root / "review_bundle"))
    )
    result = self._run(
        module,
        [
            "--trade-date", request.business_date,
            "--target-date", request.target_date,
            "--calendar-path", _v4_global(_v4_scope, 'str')(calendar_path),
            "--review-core-package-root", _v4_global(_v4_scope, 'str')(package_root),
            "--shared-package-root", _v4_global(_v4_scope, 'str')(shared_package_root),
            "--shared-store-root", _v4_global(_v4_scope, 'str')(shared_store_root),
            "--runtime-root", _v4_global(_v4_scope, 'str')(runtime_root),
            "--hk-root", _v4_global(_v4_scope, 'str')(hk_root),
            "--close-root", _v4_global(_v4_scope, 'str')(close_root),
            "--fupan-store-root", _v4_global(_v4_scope, 'str')(fupan_root),
            "--stage7-store-root", _v4_global(_v4_scope, 'str')(stage7_root),
            "--bundle-root", _v4_global(_v4_scope, 'str')(bundle_root),
        ],
    )
    payload = self._decoded_stdout(result)
    pipeline_status = _v4_global(_v4_scope, 'str')(payload.get("status") or payload.get("overall_status") or "CANNOT_CONFIRM").upper()
    result.update(
        {
            "pipeline_status": pipeline_status,
            "target_date": request.target_date,
            "modules": [module],
            "source_result": payload,
        }
    )
    # ReviewCore is the independent 21:15 owner.  PARTIAL, EVIDENCE_GAP,
    # and CANNOT_CONFIRM are preserved as evidence but remain retryable;
    # only an exit-0 READY envelope may close this scheduler slot.
    if result["status"] != "SUCCEEDED" or pipeline_status != "READY":
        result.update(
            {
                "status": "FAILED",
                "workload_id": "review_core_pool_pipeline",
                "failure_class": "UPSTREAM_NOT_READY",
                "reason": "REVIEW_CORE_POOL_PIPELINE_NOT_READY",
            }
        )
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(result)
    result["status"] = "SUCCEEDED"
    return result


def _FixedExecutorRegistry__a_share_close_review_body(_v4_scope, /, self, request):
    if self.selector_data_root is None:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "a_share_close_review",
                ["ops.build_a_share_close_review"],
                "selector data root not configured",
            )
        )
    try:
        panel = _v4_global(_v4_scope, 'resolve_selector_panel')(
            self.selector_data_root, request.business_date
        )
    except _v4_global(_v4_scope, 'FileNotFoundError') as error:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "a_share_close_review",
                ["ops.build_a_share_close_review"],
                f"selector panel unresolved: {error}",
            )
        ) from error
    pointer_dir = self.data_root / ".dispatcher_tmp"
    pointer_dir.mkdir(parents=True, exist_ok=True)
    pointer = pointer_dir / "selector_panel_pointer.txt"
    pointer.write_text(_v4_global(_v4_scope, 'str')(panel), encoding="utf-8")
    return self._run(
        "ops.build_a_share_close_review",
        [
            "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
            "--date", request.business_date,
            "--panel-pointer", _v4_global(_v4_scope, 'str')(pointer),
        ],
    )


def _FixedExecutorRegistry__hk_connect_close_review_body(_v4_scope, /, self, request):
    collector_module = "ops.collect_hkconnect_close_snapshot"
    builder_module = "ops.build_close_review"
    modules = [collector_module, builder_module]
    if self.stage_selection_root is None:
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(
            self._failure_result(
                "hk_connect_close_review",
                modules,
                "stage selection root not configured",
            )
        )
    elapsed_wait = 0
    attempts = 0
    while True:
        attempts += 1
        collector = self._run(
            collector_module,
            [
                "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
                "--date", request.business_date,
            ],
        )
        collector["attempts"] = attempts
        collector["slept_seconds"] = elapsed_wait
        if collector["status"] == "SUCCEEDED":
            break

        combined_output = "\n".join(
            _v4_global(_v4_scope, 'str')(collector.get(field) or "") for field in ("stdout", "stderr")
        )
        retryable = collector["status"] == "TIMEOUT" or (
            collector["status"] == "FAILED"
            and _v4_global(_v4_scope, '_HK_CLOSE_CUTOFF_ERROR_PREFIX') in combined_output
        )
        if not retryable or elapsed_wait >= _v4_global(_v4_scope, '_HK_CLOSE_MAX_WAIT_SECONDS'):
            collector["workload_id"] = "hk_connect_close_review"
            collector["modules"] = modules
            raise _v4_global(_v4_scope, 'WorkloadExecutionError')(collector)

        sleep_seconds = _v4_global(_v4_scope, 'min')(
            _v4_global(_v4_scope, '_HK_CLOSE_RETRY_INTERVAL_SECONDS'),
            _v4_global(_v4_scope, '_HK_CLOSE_MAX_WAIT_SECONDS') - elapsed_wait,
        )
        self._sleeper(sleep_seconds)
        elapsed_wait += sleep_seconds

    builder_arguments = [
        "--data-root", _v4_global(_v4_scope, 'str')(self.data_root),
        "--date", request.business_date,
        "--stage-selection-root", _v4_global(_v4_scope, 'str')(self.stage_selection_root),
    ]
    builder = self._run(builder_module, builder_arguments)
    builder["workload_id"] = "hk_connect_close_review"
    builder["modules"] = modules
    builder["attempts"] = attempts
    builder["slept_seconds"] = elapsed_wait
    if builder["status"] != "SUCCEEDED":
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(builder)
    return builder
