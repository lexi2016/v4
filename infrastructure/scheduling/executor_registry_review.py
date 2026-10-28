"""Review and close-stage executor handlers.

The facade rebinds these functions into its historical class interface.
"""
from __future__ import annotations

import importlib
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from contracts.runtime_tasks import DispatchRequest, WorkloadDefinition
from ops.daily_materialize import resolve_selector_panel

_HK_CLOSE_RETRY_INTERVAL_SECONDS = 120
_HK_CLOSE_MAX_WAIT_SECONDS = 1200
_HK_CLOSE_CUTOFF_ERROR_PREFIX = "final close cutoff not reached:"


_HK_CHILD_BINDING_ENV = (
    "V4_RESEARCH_PANEL_HK_CHILD_APP_ROOT",
    "V4_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_PATH",
    "V4_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_SHA256",
    "V4_RESEARCH_PANEL_HK_CHILD_RELEASE_ID",
    "V4_RESEARCH_PANEL_HK_CHILD_MODULE_SHA256",
)


def _resolve_hk_child_binding(environ: Mapping[str, str]) -> dict[str, str] | None:
    """Validate the optional HK-only child app and its exact release identity."""
    values = {key: str(environ.get(key) or "").strip() for key in _HK_CHILD_BINDING_ENV}
    if not any(values.values()):
        return None
    if not all(values.values()):
        raise ValueError("HK_CHILD_BINDING_INCOMPLETE")

    app_root_raw = values[_HK_CHILD_BINDING_ENV[0]]
    manifest_path_raw = values[_HK_CHILD_BINDING_ENV[1]]
    manifest_sha_expected = values[_HK_CHILD_BINDING_ENV[2]]
    release_id = values[_HK_CHILD_BINDING_ENV[3]]
    module_sha_expected = values[_HK_CHILD_BINDING_ENV[4]]
    if not all(
        len(value) == 64 and all(char in "0123456789abcdef" for char in value)
        for value in (manifest_sha_expected, module_sha_expected)
    ):
        raise ValueError("HK_CHILD_BINDING_SHA_PIN_INVALID")

    try:
        app_root_input = Path(app_root_raw)
        manifest_path_input = Path(manifest_path_raw)
        if not app_root_input.is_absolute() or not manifest_path_input.is_absolute():
            raise ValueError("HK_CHILD_BINDING_PATH_NOT_ABSOLUTE")
        app_root = app_root_input.resolve(strict=True)
        manifest_path = manifest_path_input.resolve(strict=True)
        if (
            app_root != app_root_input
            or manifest_path != manifest_path_input
            or not app_root.is_dir()
            or not manifest_path.is_file()
            or manifest_path.parent != app_root.parent
        ):
            raise ValueError("HK_CHILD_BINDING_PATH_INVALID")
        manifest_bytes = manifest_path.read_bytes()
        manifest_sha_actual = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_sha_actual != manifest_sha_expected:
            raise ValueError("HK_CHILD_BINDING_MANIFEST_SHA_MISMATCH")
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("HK_CHILD_BINDING_"):
            raise
        raise ValueError("HK_CHILD_BINDING_MANIFEST_UNREADABLE") from None

    if not isinstance(manifest, dict):
        raise ValueError("HK_CHILD_BINDING_MANIFEST_INVALID")
    candidate = manifest.get("candidate")
    if (
        manifest.get("schema_version") != "v4.release_candidate.v1"
        or not isinstance(candidate, dict)
        or candidate.get("app_root") != str(app_root)
        or candidate.get("release_id") != release_id
    ):
        raise ValueError("HK_CHILD_BINDING_MANIFEST_IDENTITY_MISMATCH")

    module_path_input = app_root / "ops" / "macos_research_panel_daily.py"
    try:
        module_path = module_path_input.resolve(strict=True)
        module_sha_actual = hashlib.sha256(module_path.read_bytes()).hexdigest()
    except OSError:
        raise ValueError("HK_CHILD_BINDING_PANEL_MODULE_UNAVAILABLE") from None
    if (
        module_path != module_path_input
        or not module_path.is_file()
        or module_sha_actual != module_sha_expected
    ):
        raise ValueError("HK_CHILD_BINDING_PANEL_MODULE_SHA_MISMATCH")
    inventory = manifest.get("application_inventory")
    entries = inventory.get("entries") if isinstance(inventory, dict) else None
    matching_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("path") == "ops/macos_research_panel_daily.py"
        and entry.get("kind") == "file"
    ] if isinstance(entries, list) else []
    if len(matching_entries) != 1 or matching_entries[0].get("sha256") != module_sha_expected:
        raise ValueError("HK_CHILD_BINDING_MANIFEST_MODULE_MISMATCH")

    return {
        "app_root": str(app_root),
        "release_manifest_path": str(manifest_path),
        "release_manifest_sha256": manifest_sha_actual,
        "release_id": release_id,
        "module_path": str(module_path),
        "module_sha256": module_sha_actual,
    }


def _hk_child_environment(
    binding: Mapping[str, str], *, environ: Mapping[str, str]
) -> dict[str, str]:
    """Replace stale owner identity and module roots in the HK child only."""
    child_env = {str(key): str(value) for key, value in environ.items()}
    for key in tuple(child_env):
        if key.startswith("V4_MANAGER_") or key.startswith("V4_RELEASE_"):
            child_env.pop(key, None)
    for key in (
        "V4_APP_ROOT",
        "V4_UPSTREAM_FINGERPRINT",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "V4_HK_CAPTURE_PATH",
        "V4_HK_CAPTURE_RUN_ID",
        *_HK_CHILD_BINDING_ENV,
    ):
        child_env.pop(key, None)

    app_root = Path(binding["app_root"])
    pythonpath = [app_root]
    for relative in ("upstreams", "upstreams/v3_shared_data"):
        candidate_path = app_root / relative
        if candidate_path.is_dir() and not candidate_path.is_symlink():
            pythonpath.append(candidate_path)
    child_env.update(
        {
            "PYTHONPATH": os.pathsep.join(str(path) for path in pythonpath),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "V4_APP_ROOT": binding["app_root"],
            "V4_RELEASE_ID": binding["release_id"],
            "V4_RELEASE_MANIFEST_PATH": binding["release_manifest_path"],
            "V4_RELEASE_MANIFEST_SHA256": binding["release_manifest_sha256"],
            "RESEARCH_ONLY": "true",
            "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false",
            "ORDERS_SENT": "false",
        }
    )
    return child_env



def _daily_materialize(self, request: DispatchRequest) -> dict[str, Any]:
    """Run the single 21:40 owner with explicit business/target dates."""
    module = "ops.daily_materialize"
    arguments = [
        "--data-root", str(self.data_root),
        "--business-date", request.business_date,
        "--target-date", request.target_date,
    ]
    if self.shared_data_root is not None:
        arguments.extend(["--shared-data-root", str(self.shared_data_root)])
    if self.selector_data_root is not None:
        arguments.extend(["--selector-data-root", str(self.selector_data_root)])
    if self.stage_selection_root is not None:
        arguments.extend(["--stage-selection-root", str(self.stage_selection_root)])
    result = self._run(module, arguments)
    result["modules"] = [module]
    return result

def _decoded_stdout(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("_authoritative_payload")
    if isinstance(payload, dict):
        decoded = dict(payload)
        lane = decoded.get("lane")
        if lane in {"A", "HK"} and "lanes" not in decoded:
            return {
                "overall_status": decoded.get("status") or "CANNOT_CONFIRM",
                "lanes": {lane: decoded},
            }
        return decoded
    try:
        decoder = _decode_authoritative_payload
    except NameError:
        decoder = getattr(
            importlib.import_module("infrastructure.scheduling." + "executor_" + "registry"),
            "_decode_authoritative_payload",
        )

    decoded, _error = decoder(result)
    if decoded is None:
        return {}
    lane = decoded.get("lane")
    if lane in {"A", "HK"} and "lanes" not in decoded:
        return {
            "overall_status": decoded.get("status") or "CANNOT_CONFIRM",
            "lanes": {lane: decoded},
        }
    return decoded

def _safe_lane_status(payload: dict[str, Any]) -> str:
    """Reduce an evidence adapter result without converting gaps to READY."""
    statuses: list[str] = []
    lanes = payload.get("lanes")
    if isinstance(lanes, dict):
        statuses.extend(
            str(item.get("status") or "CANNOT_CONFIRM").upper()
            for item in lanes.values()
            if isinstance(item, dict)
        )
    direct = str(payload.get("status") or payload.get("overall_status") or "").upper()
    if direct:
        statuses.append(direct)
    if any(item in {"CANNOT_CONFIRM", "FAILED", "REJECTED", "FAIL"} for item in statuses):
        return "CANNOT_CONFIRM"
    if any(item in {"PARTIAL", "PARTIAL_WITH_ROWS", "EVIDENCE_GAP"} for item in statuses):
        return "PARTIAL"
    # An empty or malformed publisher envelope is not evidence of a ready
    # lane.  Keep it retryable/fail-closed rather than allowing a missing
    # producer receipt to become a successful scheduler ledger entry.
    return "CANNOT_CONFIRM"

def _research_panel_runtime_evidence(
    self, request: DispatchRequest
) -> dict[str, Any]:
    """Publish A/H panel receipts after their independent daily producers.

        This workload only publishes lineage metadata.  It never invokes the
        A/H producer and never turns a missing receipt into a successful lane.
        """
    module = "ops.publish_research_panel_runtime_receipt"
    selector_root = self.selector_data_root or self.data_root / "selector"
    producer_root = Path(
        os.environ.get(
            "V4_RESEARCH_PANEL_RECEIPT_ROOT",
            str(self.data_root.parent / "research_panel_daily" / "receipts"),
        )
    )
    selector_pointer = Path(
        os.environ.get(
            "V4_SELECTOR_POINTER",
            str(selector_root / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"),
        )
    )
    backtest_pointer = Path(
        os.environ.get(
            "V4_BACKTEST_POINTER",
            str(selector_root / "backtest_panel_interface_current" / "CURRENT_BACKTEST_BASE_PANEL.txt"),
        )
    )
    close_path = Path(
        os.environ.get(
            "V4_CLOSE_REVIEW_PATH",
            str(self.data_root / "close_reviews" / f"{request.business_date}.json"),
        )
    )
    close_receipt = Path(
        os.environ.get(
            "V4_CLOSE_REVIEW_RECEIPT",
            str(self.data_root / "receipts" / "close_reviews" / f"{request.business_date}.json"),
        )
    )
    result = self._run(
        module,
        [
            "--date", request.business_date,
            "--data-root", str(self.data_root),
            "--producer-receipt-root", str(producer_root),
            "--selector-pointer", str(selector_pointer),
            "--backtest-pointer", str(backtest_pointer),
            "--close-review-path", str(close_path),
            "--close-review-receipt", str(close_receipt),
        ],
    )
    payload = self._decoded_stdout(result)
    lane_status = self._safe_lane_status(payload)
    lanes = payload.get("lanes")
    a_status = (
        str(lanes.get("A", {}).get("status") or "CANNOT_CONFIRM").upper()
        if isinstance(lanes, dict) and isinstance(lanes.get("A"), dict)
        else "CANNOT_CONFIRM"
    )
    hk_status = (
        str(lanes.get("HK", {}).get("status") or "CANNOT_CONFIRM").upper()
        if isinstance(lanes, dict) and isinstance(lanes.get("HK"), dict)
        else "CANNOT_CONFIRM"
    )
    # The publisher's accepted semantic is exit 0 with a verified HK lane
    # and an A lane that may be READY or PARTIAL.  A non-zero publisher
    # exit, missing lanes, or CANNOT_CONFIRM must remain a retryable
    # failure so the five-minute catch-up can run after the source recovers.
    accepted = (
        result["status"] == "SUCCEEDED"
        and isinstance(lanes, dict)
        and a_status in {"READY", "PARTIAL"}
        and hk_status == "READY"
    )
    result.update(
        {
            "lane_status": lane_status,
            "evidence_status": lane_status,
            "modules": [module],
            "source_result": payload,
            "a_lane_status": a_status,
            "hk_lane_status": hk_status,
        }
    )
    if not accepted:
        result.update(
            {
                "status": "FAILED",
                "workload_id": "research_panel_runtime_evidence",
                "failure_class": "UPSTREAM_NOT_READY",
                "reason": "RESEARCH_PANEL_RUNTIME_EVIDENCE_NOT_READY",
            }
        )
        raise WorkloadExecutionError(result)
    result["status"] = "SUCCEEDED"
    return result

def _research_panel_daily(
    self, request: DispatchRequest, *, lane: str
) -> dict[str, Any]:
    """Run the existing dated A/H producer with its exact plist arguments.

        The formal V4 research-panel LaunchAgent already proves this entry
        point and its authority-chain arguments.  The unified scheduler only
        reuses that command for one explicit lane at its canonical post-close
        slot; it does not create a second collector or infer missing inputs.
        Missing bindings are a typed configuration gap and remain retryable.
        """
    module = "ops.macos_research_panel_daily"
    hk_child_binding = None
    if lane == "HK":
        from infrastructure.scheduling import executor_registry_review as binding_helpers
        try:
            hk_child_binding = binding_helpers._resolve_hk_child_binding(os.environ)
        except ValueError as error:
            failure = self._failure_result(
                "research_panel_daily_hk", [module], str(error)
            )
            failure.update(
                status="FAILED", failure_class="INVALID_INPUT", reason=str(error)
            )
            raise WorkloadExecutionError(failure)
    names = (
        "V4_RESEARCH_PANEL_RECEIPT_ROOT",
        "V4_RESEARCH_PANEL_A_TDX_ROOT",
        "V4_RESEARCH_PANEL_HK_TDX_ROOT",
        "V4_RESEARCH_PANEL_A_SYNC_SCRIPT",
        "V4_RESEARCH_PANEL_A_FORMULA_SCRIPT",
        "V4_RESEARCH_PANEL_A_SEED_PANEL",
        "V4_RESEARCH_PANEL_A_DATA_ROOT",
        "V4_RESEARCH_PANEL_A_SELECTOR_POINTER",
        "V4_RESEARCH_PANEL_A_BACKTEST_POINTER",
        "V4_RESEARCH_PANEL_A_SELECTOR_SEED",
        "V4_RESEARCH_PANEL_A_BACKTEST_SEED",
        "V4_RESEARCH_PANEL_A_CONTRACT_CSV",
        "V4_RESEARCH_PANEL_A_CANONICAL_FORMULA",
        "V4_RESEARCH_PANEL_A_RETURN_ROOT",
        "V4_RESEARCH_PANEL_HK_UPDATER_SCRIPT",
        "V4_RESEARCH_PANEL_HK_ASSET_ROOT",
    )
    missing = [name for name in names if not str(os.environ.get(name) or "").strip()]
    if missing:
        failure = self._failure_result(
            "research_panel_daily_a" if lane == "A" else "research_panel_daily_hk",
            [module],
            "research panel producer bindings missing: " + ",".join(missing),
        )
        failure["failure_class"] = "CONFIGURATION_MISSING"
        raise WorkloadExecutionError(failure)
    env = {name: str(os.environ[name]) for name in names}
    arguments = [
        "--date", request.business_date,
        "--lane", lane,
        "--receipt-root", env["V4_RESEARCH_PANEL_RECEIPT_ROOT"],
        "--a-tdx-root", env["V4_RESEARCH_PANEL_A_TDX_ROOT"],
        "--hk-tdx-root", env["V4_RESEARCH_PANEL_HK_TDX_ROOT"],
        "--a-minimum-rows", "5000",
        "--a-sync-script", env["V4_RESEARCH_PANEL_A_SYNC_SCRIPT"],
        "--a-formula-script", env["V4_RESEARCH_PANEL_A_FORMULA_SCRIPT"],
        "--a-seed-panel", env["V4_RESEARCH_PANEL_A_SEED_PANEL"],
        "--a-data-root", env["V4_RESEARCH_PANEL_A_DATA_ROOT"],
        "--a-selector-pointer", env["V4_RESEARCH_PANEL_A_SELECTOR_POINTER"],
        "--a-backtest-pointer", env["V4_RESEARCH_PANEL_A_BACKTEST_POINTER"],
        "--a-selector-seed", env["V4_RESEARCH_PANEL_A_SELECTOR_SEED"],
        "--a-backtest-seed", env["V4_RESEARCH_PANEL_A_BACKTEST_SEED"],
        "--a-contract-csv", env["V4_RESEARCH_PANEL_A_CONTRACT_CSV"],
        "--a-canonical-formula", env["V4_RESEARCH_PANEL_A_CANONICAL_FORMULA"],
        "--a-return-root", env["V4_RESEARCH_PANEL_A_RETURN_ROOT"],
        "--hk-updater-script", env["V4_RESEARCH_PANEL_HK_UPDATER_SCRIPT"],
        "--hk-python-executable", str(self.hk_0_2_python_executable),
        "--hk-asset-root", env["V4_RESEARCH_PANEL_HK_ASSET_ROOT"],
    ]
    if lane == "HK" and hk_child_binding is not None:
        result = self._run(
            module,
            arguments,
            cwd=Path(hk_child_binding["app_root"]),
            env=binding_helpers._hk_child_environment(
                hk_child_binding, environ=os.environ
            ),
        )
    else:
        result = self._run(module, arguments)
    payload = self._decoded_stdout(result)
    lanes = payload.get("lanes")
    lane_payload = lanes.get(lane) if isinstance(lanes, dict) else None
    lane_status = (
        str(lane_payload.get("status") or "CANNOT_CONFIRM").upper()
        if isinstance(lane_payload, dict)
        else "CANNOT_CONFIRM"
    )
    source_reason = (
        lane_payload.get("reason") if isinstance(lane_payload, dict) else None
    )
    source_authority_status = (
        lane_payload.get("authority_status") if isinstance(lane_payload, dict) else None
    )
    a_authority_rebuild = (
        lane == "A"
        and lane_status in {"PARTIAL", "PARTIAL_WITH_ROWS"}
        and (
            str(source_reason or "").upper() == "A_SYNC_AUTHORITY_REBUILD_REQUIRED"
            or str(source_authority_status or "").upper() == "REBUILD_REQUIRED"
        )
    )
    if isinstance(source_reason, str) and source_reason:
        result["reason"] = source_reason
    if isinstance(source_authority_status, str) and source_authority_status:
        result["authority_status"] = source_authority_status
    partial_a = lane == "A" and lane_status in {"PARTIAL", "PARTIAL_WITH_ROWS"}
    if lane_status == "READY" or partial_a:
        try:
            receipt_reader = _read_exact_dated_receipt
        except NameError:
            receipt_reader = getattr(
                importlib.import_module("infrastructure.scheduling." + "executor_" + "registry"),
                "_read_exact_dated_receipt",
            )
        receipt, receipt_error = receipt_reader(module, arguments)

        if lane == "A":
            receipt_validator = getattr(
                __import__(
                    "ops.macos_research_panel_daily_receipts",
                    fromlist=("validate_a_receipt",),
                ),
                "validate_a_receipt",
            )
            expected_receipt_status = "READY" if lane_status == "READY" else "PARTIAL_WITH_ROWS"
            receipt_valid = (
                receipt_validator(
                    receipt,
                    request.business_date,
                    selector_pointer=env["V4_RESEARCH_PANEL_A_SELECTOR_POINTER"],
                    backtest_pointer=env["V4_RESEARCH_PANEL_A_BACKTEST_POINTER"],
                )
                == expected_receipt_status
            )
        else:
            receipt_valid = isinstance(receipt, dict) and receipt.get("status") == "READY"
        if not receipt_valid:
            lane_status = "CANNOT_CONFIRM"
            result["source_receipt_error"] = receipt_error or "EXACT_DATED_RECEIPT_STATUS_MISMATCH"
        elif partial_a and isinstance(receipt, dict):
            lane_status = "PARTIAL_WITH_ROWS"
            result.update(
                {
                    "status": "SUCCEEDED",
                    "row_count": receipt.get("row_count"),
                    "coverage_rate": receipt.get("coverage_rate"),
                    "accepted_target_date_file_count": receipt.get("accepted_target_date_file_count"),
                    "accepted_count": receipt.get("accepted_count"),
                    "quarantine_count": receipt.get("quarantine_count"),
                    "target_count": receipt.get("target_count"),
                    "reconciliation": receipt.get("reconciliation"),
                    "authority_status": "REBUILD_REQUIRED",
                    "reason": result.get("reason") or receipt.get("reason") or "A_SYNC_AUTHORITY_REBUILD_REQUIRED",
                    "cannot_confirm": receipt.get("cannot_confirm"),
                }
            )
    result.update(
        {
            "lane": lane,
            "lane_status": lane_status,
            "target_date": request.business_date,
            "modules": [module],
            "source_result": payload,
        }
    )
    accepted_partial_a = lane == "A" and lane_status == "PARTIAL_WITH_ROWS"
    if result["status"] != "SUCCEEDED" or (lane_status != "READY" and not accepted_partial_a):
        failure = {
            "status": "FAILED",
            "workload_id": "research_panel_daily_a" if lane == "A" else "research_panel_daily_hk",
            "failure_class": "CONTRACT" if a_authority_rebuild else "UPSTREAM_NOT_READY",
        }
        if a_authority_rebuild:
            if isinstance(source_reason, str) and source_reason:
                failure["reason"] = source_reason
        else:
            failure["reason"] = "RESEARCH_PANEL_DAILY_LANE_NOT_READY"
        result.update(failure)
        raise WorkloadExecutionError(result)
    return result

def _wechat_preselection_sync(self, request: DispatchRequest) -> dict[str, Any]:
    """Sync the exact pair; missing source is CANNOT_CONFIRM + retryable."""
    module = "ops.wechat_preselection_sync"
    # The canonical future producer boundary is the V4 input lane.  The
    # historical 20260821 pair under ``preselection_pools`` was a one-time
    # canary/evidence source and is never a natural-production fallback.
    configured_root = self.preselection_input_root
    if configured_root is None:
        configured_root = os.environ.get("V4_WECHAT_INPUT_ROOT")
    input_root = Path(
        configured_root
        if configured_root is not None
        else self.data_root / "preselection_inputs"
    )
    canonical_input_root = self.data_root / "preselection_inputs"
    try:
        input_root.resolve().relative_to(canonical_input_root.resolve())
    except (OSError, ValueError) as error:
        failure = self._failure_result(
            "wechat_preselection_sync",
            [module],
            "WeChat input root must remain under data_root/preselection_inputs; historical preselection_pools is evidence-only",
        )
        failure["failure_class"] = "CONTRACT"
        raise WorkloadExecutionError(
            failure
        ) from error
    receipt = self.data_root / "receipts" / "wechat_preselection" / f"{request.target_date}.json"
    result = self._run(
        module,
        [
            "--effective-date", request.target_date,
            "--input-root", str(input_root),
            "--data-root", str(self.data_root),
            "--receipt", str(receipt),
        ],
    )
    payload = self._decoded_stdout(result)
    status = str(payload.get("status") or "").upper()
    result.update(
        {
            "lane_status": status or "CANNOT_CONFIRM",
            "target_date": request.target_date,
            "modules": [module],
            "source_result": payload,
        }
    )
    # This is a consumer-side sync of an already verified exact pair.  It
    # is successful only when the child exits 0 and reports READY.  A
    # missing/partial pair is a retryable upstream gap, not a terminal
    # CANNOT_CONFIRM success that would block later catch-up.
    if result["status"] != "SUCCEEDED" or status != "READY":
        result.update(
            {
                "status": "FAILED",
                "workload_id": "wechat_preselection_sync",
                "failure_class": "UPSTREAM_NOT_READY",
                "reason": "WECHAT_EXACT_DATE_INPUT_NOT_READY",
            }
        )
        raise WorkloadExecutionError(result)
    result["status"] = "SUCCEEDED"
    return result

def _review_core_pool_pipeline(self, request: DispatchRequest) -> dict[str, Any]:
    """Run the verified natural Review Core adapter at the 21:15 slot."""
    module = "ops.run_review_core_natural_pool_pipeline"
    package_root = Path(
        os.environ.get("V4_REVIEW_CORE_PACKAGE_ROOT", str(self.data_root / "review_core"))
    )
    shared_package_root = Path(
        os.environ.get(
            "V4_REVIEW_CORE_SHARED_PACKAGE_ROOT",
            str(self.shared_package_root or self.data_root / "shared_package"),
        )
    )
    shared_store_root = Path(
        os.environ.get(
            "V4_REVIEW_CORE_SHARED_STORE_ROOT",
            str(self.shared_data_root or self.data_root / "shared_store"),
        )
    )
    runtime_root = Path(os.environ.get("V4_REVIEW_CORE_RUNTIME_ROOT", str(self.data_root)))
    calendar_path = Path(
        os.environ.get(
            "V4_REVIEW_CORE_CALENDAR_PATH",
            str((self.repo_root or Path(__file__).resolve().parents[2]) / "contracts" / "market_calendar_2026.json"),
        )
    )
    hk_root = Path(
        os.environ.get("V4_REVIEW_CORE_HK_ROOT", str(self.hk_universe_root or self.data_root / "hk"))
    )
    close_root = Path(os.environ.get("V4_REVIEW_CORE_CLOSE_ROOT", str(self.data_root / "close_reviews")))
    fupan_root = Path(
        os.environ.get("V4_REVIEW_CORE_FUPAN_STORE_ROOT", str(self.data_root / "fupan_store"))
    )
    stage7_root = Path(
        os.environ.get("V4_REVIEW_CORE_STAGE7_STORE_ROOT", str(self.data_root / "stage7_store"))
    )
    bundle_root = Path(
        os.environ.get("V4_REVIEW_CORE_BUNDLE_ROOT", str(self.data_root / "review_bundle"))
    )
    result = self._run(
        module,
        [
            "--trade-date", request.business_date,
            "--target-date", request.target_date,
            "--calendar-path", str(calendar_path),
            "--review-core-package-root", str(package_root),
            "--shared-package-root", str(shared_package_root),
            "--shared-store-root", str(shared_store_root),
            "--runtime-root", str(runtime_root),
            "--hk-root", str(hk_root),
            "--close-root", str(close_root),
            "--fupan-store-root", str(fupan_root),
            "--stage7-store-root", str(stage7_root),
            "--bundle-root", str(bundle_root),
        ],
    )
    payload = self._decoded_stdout(result)
    pipeline_status = str(payload.get("status") or payload.get("overall_status") or "CANNOT_CONFIRM").upper()
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
        raise WorkloadExecutionError(result)
    result["status"] = "SUCCEEDED"
    return result

def _run_stage_center_milestone(
    self, workload: WorkloadDefinition, request: DispatchRequest
) -> dict[str, Any]:
    if self.stage_selection_root is None:
        raise WorkloadExecutionError(
            self._failure_result(
                workload.workload_id,
                ["ops.run_stage_center_milestone"],
                "stage selection root not configured",
            )
        )
    node, stage_id, _market = MILESTONE_BY_WORKLOAD[workload.workload_id]
    result = self._run(
        "ops.run_stage_center_milestone",
        [
            "--node", node,
            "--data-root", str(self.data_root),
            "--date", request.business_date,
            "--stage-id", stage_id,
            "--selection-root", str(self.stage_selection_root),
        ],
    )
    result["modules"] = ["ops.run_stage_center_milestone"]
    # The existing 15:55 manager PyTDX owner is independent of the Stage
    # readback. Attempt it after the fupan node returns, even when the Stage
    # reader reports a failure; never turn either result green using the other.
    if (workload.workload_id == "fupan_review_start" and request.slot == "1555"
            and str(getattr(request.mode, "value", request.mode)) == "LIVE"):
        stage_status = result.get("status")
        stage_exit_code = result.get("exit_code")
        result["stage_readback_status"] = stage_status
        result["stage_readback_exit_code"] = stage_exit_code
        try:
            from infrastructure.scheduling.executor_registry_research import (
                _manager_close_recapture_after_stage_workbench,
            )
            recapture = _manager_close_recapture_after_stage_workbench(
                self, request, stage_result=result
            )
        except WorkloadExecutionError as error:
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

def _run_close_review_node(
    self, workload: WorkloadDefinition, request: DispatchRequest
) -> dict[str, Any]:
    node = CLOSE_NODE_BY_WORKLOAD[workload.workload_id]
    arguments = [
        "--node", node,
        "--data-root", str(self.data_root),
        "--business-date", request.business_date,
    ]
    if self.selector_data_root is not None:
        arguments.extend(["--selector-data-root", str(self.selector_data_root)])
    result = self._run("ops.run_v4_close_review_slot", arguments)
    result["modules"] = ["ops.run_v4_close_review_slot"]
    return result

def _a_share_close_review(
    self, request: DispatchRequest
) -> dict[str, Any]:
    if self.selector_data_root is None:
        raise WorkloadExecutionError(
            self._failure_result(
                "a_share_close_review",
                ["ops.build_a_share_close_review"],
                "selector data root not configured",
            )
        )
    try:
        panel = resolve_selector_panel(
            self.selector_data_root, request.business_date
        )
    except FileNotFoundError as error:
        result = self._failure_result(
            "a_share_close_review",
            ["ops.build_a_share_close_review"],
            f"selector panel unresolved: {error}",
        )
        # The same exact-date selector may arrive after the close slot.  This
        # is a missing dependency, not a terminal model/contract failure.
        result.update(failure_class="INPUT_MISSING", reason="A_CLOSE_SELECTOR_PANEL_UNAVAILABLE")
        raise WorkloadExecutionError(result) from error
    pointer_dir = self.data_root / ".dispatcher_tmp"
    pointer_dir.mkdir(parents=True, exist_ok=True)
    pointer = pointer_dir / "selector_panel_pointer.txt"
    pointer.write_text(str(panel), encoding="utf-8")
    return self._run(
        "ops.build_a_share_close_review",
        [
            "--data-root", str(self.data_root),
            "--date", request.business_date,
            "--panel-pointer", str(pointer),
        ],
    )


def _hk_connect_close_review(
    self, request: DispatchRequest
) -> dict[str, Any]:
    collector_module = "ops.collect_hkconnect_close_snapshot"
    builder_module = "ops.build_close_review"
    modules = [collector_module, builder_module]
    if self.stage_selection_root is None:
        raise WorkloadExecutionError(
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
                "--data-root", str(self.data_root),
                "--date", request.business_date,
            ],
        )
        collector["attempts"] = attempts
        collector["slept_seconds"] = elapsed_wait
        if collector["status"] == "SUCCEEDED":
            break

        combined_output = "\n".join(
            str(collector.get(field) or "") for field in ("stdout", "stderr")
        )
        retryable = collector["status"] == "TIMEOUT" or (
            collector["status"] == "FAILED"
            and _HK_CLOSE_CUTOFF_ERROR_PREFIX in combined_output
        )
        if not retryable or elapsed_wait >= _HK_CLOSE_MAX_WAIT_SECONDS:
            collector["workload_id"] = "hk_connect_close_review"
            collector["modules"] = modules
            raise WorkloadExecutionError(collector)

        sleep_seconds = min(
            _HK_CLOSE_RETRY_INTERVAL_SECONDS,
            _HK_CLOSE_MAX_WAIT_SECONDS - elapsed_wait,
        )
        self._sleeper(sleep_seconds)
        elapsed_wait += sleep_seconds

    builder_arguments = [
        "--data-root", str(self.data_root),
        "--date", request.business_date,
        "--stage-selection-root", str(self.stage_selection_root),
    ]
    builder = self._run(builder_module, builder_arguments)
    builder["workload_id"] = "hk_connect_close_review"
    builder["modules"] = modules
    builder["attempts"] = attempts
    builder["slept_seconds"] = elapsed_wait
    if builder["status"] != "SUCCEEDED":
        raise WorkloadExecutionError(builder)
    return builder
