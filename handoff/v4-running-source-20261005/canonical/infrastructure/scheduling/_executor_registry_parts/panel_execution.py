"""infrastructure.scheduling.executor_registry: panel_execution (review candidate, not deployment)."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping
from ._namespace import read_global as _v4_global


_HK_CHILD_BINDING_ENV = (
    "V35_RESEARCH_PANEL_HK_CHILD_APP_ROOT",
    "V35_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_PATH",
    "V35_RESEARCH_PANEL_HK_CHILD_RELEASE_MANIFEST_SHA256",
    "V35_RESEARCH_PANEL_HK_CHILD_RELEASE_ID",
    "V35_RESEARCH_PANEL_HK_CHILD_MODULE_SHA256",
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
        if key.startswith("V4_MANAGER_") or key.startswith("V35_RELEASE_"):
            child_env.pop(key, None)
    for key in (
        "V35_APP_ROOT",
        "V35_UPSTREAM_FINGERPRINT",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "V35_HK_CAPTURE_PATH",
        "V35_HK_CAPTURE_RUN_ID",
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
            "V35_APP_ROOT": binding["app_root"],
            "V35_RELEASE_ID": binding["release_id"],
            "V35_RELEASE_MANIFEST_PATH": binding["release_manifest_path"],
            "V35_RELEASE_MANIFEST_SHA256": binding["release_manifest_sha256"],
            "RESEARCH_ONLY": "true",
            "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false",
            "ORDERS_SENT": "false",
        }
    )
    return child_env


def _FixedExecutorRegistry__research_panel_daily_body(_v4_scope, /, self, request, *, lane):
    """Reuse the single public producer; require exact bound disk evidence.

        Config is lane-local. stdout is only a compact envelope, never the full
        upstream artifact, and cannot grant READY without its dated receipt.
    """
    module = "ops.macos_research_panel_daily"
    hk_child_binding = None
    if lane == "HK":
        try:
            hk_child_binding = _resolve_hk_child_binding(_v4_global(_v4_scope, 'os').environ)
        except ValueError as error:
            failure = self._failure_result("research_panel_daily_hk", [module], str(error))
            failure.update(status="FAILED", failure_class="INVALID_INPUT", reason=str(error))
            raise _v4_global(_v4_scope, 'WorkloadExecutionError')(failure)
    common = ("RECEIPT_ROOT",)
    a_names = (
        "A_TDX_ROOT", "A_SYNC_SCRIPT", "A_FORMULA_SCRIPT", "A_SEED_PANEL",
        "A_DATA_ROOT", "A_SELECTOR_POINTER", "A_BACKTEST_POINTER", "A_SELECTOR_SEED",
        "A_BACKTEST_SEED", "A_CONTRACT_CSV", "A_CANONICAL_FORMULA", "A_RETURN_ROOT",
    )
    hk_names = ("HK_TDX_ROOT", "HK_UPDATER_SCRIPT", "HK_PYTHON_EXECUTABLE", "HK_ASSET_ROOT")
    names = common + (a_names if lane == "A" else hk_names)
    a_receipt_root = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'os').environ.get("V35_RESEARCH_PANEL_A_RECEIPT_ROOT") or "").strip()
    if lane == "A" and a_receipt_root:
        receipt_root = a_receipt_root
        receipt_env_name = "V35_RESEARCH_PANEL_A_RECEIPT_ROOT"
    else:
        receipt_root = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'os').environ.get("V35_RESEARCH_PANEL_RECEIPT_ROOT") or "").strip()
        receipt_env_name = "V35_RESEARCH_PANEL_RECEIPT_ROOT"
    generation_pointer = _v4_global(_v4_scope, 'str')(
        _v4_global(_v4_scope, 'os').environ.get("V35_RESEARCH_PANEL_A_FORMULA_GENERATION_POINTER") or ""
    ).strip() if lane == "A" else ""
    env = {name: _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'os').environ.get("V35_RESEARCH_PANEL_" + name) or "").strip() for name in names}
    env["RECEIPT_ROOT"] = receipt_root
    missing = ["V35_RESEARCH_PANEL_" + name for name, value in env.items() if not value]
    if not receipt_root and receipt_env_name not in missing:
        missing.append(receipt_env_name)
    if missing:
        failure = self._failure_result(
            "research_panel_daily_" + lane.lower(), [module],
            "research panel producer bindings missing: " + ",".join(missing),
        )
        failure["failure_class"] = "CONFIGURATION_MISSING"
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(failure)
    if lane == "HK":
        # Honour the launcher's explicit interpreter (including .invalid),
        # then reuse the existing exact-version gate before any collection.
        if self._hk_0_2_python_explicit:
            env["HK_PYTHON_EXECUTABLE"] = _v4_global(_v4_scope, 'str')(self.hk_0_2_python_executable)
        runtime_error = self._hk_0_2_runtime_error(env["HK_PYTHON_EXECUTABLE"])
        if runtime_error is not None:
            failure = self._failure_result("research_panel_daily_hk", [module], runtime_error)
            failure.update(failure_class="UPSTREAM_NOT_READY", reason="HK_RUNTIME_NOT_VERIFIED")
            raise _v4_global(_v4_scope, 'WorkloadExecutionError')(failure)
    arguments = ["--date", request.business_date, "--lane", lane]
    for name, value in env.items():
        arguments.extend(["--" + name.lower().replace("_", "-"), value])
    if lane == "A":
        arguments.extend(["--a-minimum-rows", "5000"])
        if generation_pointer:
            arguments.extend(["--a-formula-generation-pointer", generation_pointer])
        # Snapshot these inputs at dispatch, including in persistent mode.
        for key, flag in (("V35_A_SYNC_HOST", "--a-host"),
                          ("V35_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS", "--a-sync-run-budget-seconds")):
            value = _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'os').environ.get(key) or "").strip()
            if value:
                arguments.extend([flag, value])
    if lane == "HK" and hk_child_binding is not None:
        child_env = _hk_child_environment(
            hk_child_binding, environ=_v4_global(_v4_scope, 'os').environ
        )
        result = self._run(
            module,
            arguments,
            cwd=_v4_global(_v4_scope, 'Path')(hk_child_binding["app_root"]),
            env=child_env,
        )
    else:
        result = self._run(module, arguments)
    payload = self._decoded_stdout(result)
    lanes = payload.get("lanes")
    lane_payload = lanes.get(lane) if _v4_global(_v4_scope, 'isinstance')(lanes, _v4_global(_v4_scope, 'dict')) else None
    lane_status = (
        _v4_global(_v4_scope, 'str')(lane_payload.get("status") or "CANNOT_CONFIRM").upper()
        if _v4_global(_v4_scope, 'isinstance')(lane_payload, _v4_global(_v4_scope, 'dict'))
        else "CANNOT_CONFIRM"
    )
    receipt_verified = False
    receipt_reason = "EXACT_RECEIPT_NOT_VERIFIED"
    try:
        if not _v4_global(_v4_scope, 'isinstance')(lane_payload, _v4_global(_v4_scope, 'dict')):
            raise _v4_global(_v4_scope, 'ValueError')("MISSING_LANE_ENVELOPE")
        if (payload.get("schema_version") != "v3.macos.research_panel_authority_envelope.v1"
                or payload.get("target_date") != request.business_date
                or payload.get("requested_lane") != lane
                or _v4_global(_v4_scope, 'any')(payload.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
            raise _v4_global(_v4_scope, 'ValueError')("ENVELOPE_IDENTITY_OR_SAFETY_MISMATCH")
        raw = _v4_global(_v4_scope, 'SafeRoot')(env["RECEIPT_ROOT"]).read_bytes(f"{lane.lower()}-{request.business_date}.json")
        if (_v4_global(_v4_scope, 'len')(raw) != lane_payload.get("receipt_bytes")
                or _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest() != lane_payload.get("receipt_sha256")):
            raise _v4_global(_v4_scope, 'ValueError')("RECEIPT_BYTES_OR_SHA_MISMATCH")
        receipt = _v4_global(_v4_scope, 'json').loads(raw)
        if (not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'dict'))
                or receipt.get("schema_version") != "v3.macos.research_panel_receipt.v1"
                or receipt.get("target_date") != request.business_date
                or receipt.get("lane") != lane or receipt.get("status") != lane_status
                or _v4_global(_v4_scope, 'any')(receipt.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
            raise _v4_global(_v4_scope, 'ValueError')("RECEIPT_IDENTITY_OR_SAFETY_MISMATCH")
        if lane == "A" and generation_pointer:
            try:
                generation = _v4_global(_v4_scope, 'read_formula_generation')(
                    generation_pointer,
                    expected_target_date=request.business_date,
                    require_source=True,
                )
            except (_v4_global(_v4_scope, 'FormulaGenerationError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')) as error:
                raise _v4_global(_v4_scope, 'ValueError')(f"FORMULA_GENERATION_INVALID:{error}") from error
            receipt_generation = receipt.get("generation")
            if not _v4_global(_v4_scope, 'isinstance')(receipt_generation, _v4_global(_v4_scope, 'dict')):
                formula_detail = receipt.get("formula")
                receipt_generation = (
                    formula_detail.get("generation_pointer")
                    if _v4_global(_v4_scope, 'isinstance')(formula_detail, _v4_global(_v4_scope, 'dict'))
                    else None
                )
            if (
                not _v4_global(_v4_scope, 'isinstance')(receipt_generation, _v4_global(_v4_scope, 'dict'))
                or _v4_global(_v4_scope, 'str')(receipt_generation.get("generation_id") or "") != generation["generation_id"]
                or _v4_global(_v4_scope, 'str')(receipt_generation.get("sha256") or "").lower() != generation["sha256"]
            ):
                raise _v4_global(_v4_scope, 'ValueError')("FORMULA_GENERATION_RECEIPT_MISMATCH")
        receipt_verified = True
        receipt_reason = "EXACT_DATE_BYTES_VERIFIED"
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError')) as error:
        receipt_reason = _v4_global(_v4_scope, 'type')(error).__name__ + ":" + _v4_global(_v4_scope, 'str')(error)[:180]
    result.update(
        {
            "lane": lane,
            "lane_status": lane_status,
            "target_date": request.business_date,
            "modules": [module],
            "source_result": payload,
            "receipt_verified": receipt_verified,
            "receipt_verification_reason": receipt_reason,
        }
    )
    if result["status"] != "SUCCEEDED" or lane_status != "READY" or not receipt_verified:
        result.update(
            {
                "status": "FAILED",
                "workload_id": "research_panel_daily_a" if lane == "A" else "research_panel_daily_hk",
                "failure_class": "UPSTREAM_NOT_READY",
                "reason": "RESEARCH_PANEL_DAILY_LANE_NOT_READY",
            }
        )
        raise _v4_global(_v4_scope, 'WorkloadExecutionError')(result)
    return result
