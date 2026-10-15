#!/usr/bin/env python3
"""Candidate-bound wrapper for the existing exact-date recovery driver."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import sys

DOC_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DOC_ROOT.parents[2]
BINDING_PATH = DOC_ROOT / "scheduler_cache_release_binding.json"
EXPECTED_BINDING_SHA256 = "bee081cef3b5327b90d738d3fca3ca6610cff59fd702afb91c18e57b37422334"
RECOVERY_CORE_SHA256 = "b757420def3382d363331d8a6bc46c28eced034bdf220f2d7fa60a639d00da5f"
INVENTORY_HELPER_SHA256 = "86804204fae3484bf4277e6b2d4cdb7b1dea34ea7af530ebe2a036d845246f31"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_pinned_inventory_helper():
    """Load the exact reviewed inventory utility by file path, never by app import name."""
    source = REPO_ROOT / "ops/api_release_integration.py"
    if source.is_symlink() or source.resolve(strict=True) != source:
        raise RuntimeError("CACHE_INVENTORY_HELPER_PATH_NOT_EXACT")
    if _sha(source) != INVENTORY_HELPER_SHA256:
        raise RuntimeError("CACHE_INVENTORY_HELPER_SHA_MISMATCH")
    spec = importlib.util.spec_from_file_location(
        "_v4_oversold_cache_pinned_api_release_integration", source
    )
    if spec is None or spec.loader is None or spec.origin is None:
        raise RuntimeError("CACHE_INVENTORY_HELPER_SPEC_UNAVAILABLE")
    if Path(spec.origin).resolve(strict=True) != source:
        raise RuntimeError("CACHE_INVENTORY_HELPER_ORIGIN_MISMATCH")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if Path(str(module.__file__)).resolve(strict=True) != source:
        raise RuntimeError("CACHE_INVENTORY_HELPER_LOADED_ORIGIN_MISMATCH")
    return module


def _bind_recovery():
    if _sha(BINDING_PATH) != EXPECTED_BINDING_SHA256:
        raise RuntimeError("CACHE_RECOVERY_BINDING_SHA_MISMATCH")
    binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    recovery_path = DOC_ROOT / "recover_oversold_20261016.py"
    if _sha(recovery_path) != RECOVERY_CORE_SHA256:
        raise RuntimeError("REVIEWED_RECOVERY_CORE_SHA_MISMATCH")
    sys.path.insert(0, str(DOC_ROOT))
    import recover_oversold_20261016 as recovery
    import scheduler_release_cutover as cutover

    recovery.__file__ = str(Path(__file__).resolve())
    recovery.DOC_ROOT = DOC_ROOT
    recovery.OVERSOLD_CANDIDATE = Path(binding["candidate_root"])
    recovery.ACTIVE_PLIST = Path(binding["active_plist_path"])
    recovery.ACTIVE_RELEASE_ROOT = Path(binding["candidate_root"])
    recovery.ACTIVE_APP_ROOT = Path(binding["candidate_app_root"])
    recovery.ACTIVE_CONFIG = Path(binding["manager_config_path"])
    recovery.ACTIVE_RUNTIME_ROOT = Path(binding["runtime_root"])
    recovery.ACTIVE_RELEASE_ID = binding["candidate_release_id"]
    recovery.ACTIVE_PID = None
    recovery.ACTIVE_PLIST_SHA256 = binding["candidate_staged_plist_sha256"]
    recovery.ACTIVE_MANIFEST_SHA256 = binding["candidate_manifest_sha256"]
    recovery.ACTIVE_CONFIG_SHA256 = binding["manager_config_sha256"]
    recovery.OVERSOLD_CANDIDATE_MANIFEST_SHA256 = binding["candidate_manifest_sha256"]
    recovery.OVERSOLD_CANDIDATE_PLIST_SHA256 = binding["candidate_staged_plist_sha256"]
    recovery.ACTIVATION_RECEIPT = Path(binding["activation_receipt_path"])
    recovery.SOURCE_DAY = binding["source_day"]
    recovery.TARGET_DATE = binding["target_date"]

    cutover.PLIST = Path(binding["active_plist_path"])
    cutover.ACTIVE_CONFIG = Path(binding["manager_config_path"])

    def validate_candidate_scheduler_identity() -> dict[str, object]:
        plist_path = Path(binding["active_plist_path"])
        app_root = Path(binding["candidate_app_root"])
        candidate_root = Path(binding["candidate_root"])
        manifest_path = Path(binding["candidate_manifest_path"])
        staged_path = Path(binding["candidate_staged_plist_path"])
        config_path = Path(binding["manager_config_path"])
        if _sha(plist_path) != binding["candidate_staged_plist_sha256"]:
            raise RuntimeError("ACTIVE_CANDIDATE_PLIST_SHA_MISMATCH")
        if _sha(staged_path) != binding["candidate_staged_plist_sha256"]:
            raise RuntimeError("STAGED_CANDIDATE_PLIST_SHA_MISMATCH")
        if _sha(manifest_path) != binding["candidate_manifest_sha256"]:
            raise RuntimeError("ACTIVE_CANDIDATE_MANIFEST_SHA_MISMATCH")
        if _sha(config_path) != binding["manager_config_sha256"]:
            raise RuntimeError("ACTIVE_MANAGER_CONFIG_SHA_MISMATCH")
        job = recovery._active_launchd_snapshot()
        pid = job.get("pid")
        if (job.get("returncode") != 0 or job.get("state") != "running" or not isinstance(pid, int)
                or Path(str(job.get("plist_path") or "")).resolve() != plist_path.resolve()
                or job.get("program") != "/bin/bash"
                or Path(str(job.get("working_directory") or "")).resolve() != app_root.resolve()):
            raise RuntimeError("ACTIVE_CANDIDATE_LAUNCHD_IDENTITY_MISMATCH")
        try:
            plist = plistlib.loads(plist_path.read_bytes())
        except (OSError, plistlib.InvalidFileException) as error:
            raise RuntimeError("ACTIVE_CANDIDATE_PLIST_UNREADABLE") from error
        env = plist.get("EnvironmentVariables") if isinstance(plist, dict) else None
        args = plist.get("ProgramArguments") if isinstance(plist, dict) else None
        expected_env = {
            "V35_APP_ROOT": str(app_root),
            "V35_RELEASE_ID": binding["candidate_release_id"],
            "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
            "V35_RELEASE_MANIFEST_SHA256": binding["candidate_manifest_sha256"],
            "V35_RUNTIME_ROOT": binding["runtime_root"],
            "V4_MANAGER_WORKBENCH_CONFIG_PATH": str(config_path),
            "PYTHONPATH": f"{app_root / 'upstreams'}:{app_root}",
        }
        if (not isinstance(env, dict) or any(env.get(key) != value for key, value in expected_env.items())
                or args != ["/bin/bash", str(app_root / "ops/launch_v35_macos_scheduler.sh")]
                or plist.get("WorkingDirectory") != str(app_root)):
            raise RuntimeError("ACTIVE_CANDIDATE_PLIST_SELECTOR_MISMATCH")
        for key in ("PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT",
                    "production_allowed", "buy_gate_updated", "orders_sent"):
            if key in env and str(env[key]).lower() not in {"false", "0"}:
                raise RuntimeError(f"ACTIVE_SAFETY_FLAG_NOT_FALSE:{key}")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            activation = json.loads(Path(binding["activation_receipt_path"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("CANDIDATE_MANIFEST_OR_ACTIVATION_RECEIPT_UNREADABLE") from error
        base = manifest.get("base")
        candidate = manifest.get("candidate")
        if (manifest.get("role") != "scheduler" or not isinstance(base, dict)
                or base.get("manifest_sha256") != binding["base_manifest_sha256"]
                or base.get("plist_sha256") != binding["base_plist_preimage_sha256"]
                or base.get("app_root") != binding["base_app_root"]
                or not isinstance(candidate, dict)
                or candidate.get("release_id") != binding["candidate_release_id"]
                or candidate.get("root") != str(candidate_root)
                or candidate.get("app_root") != str(app_root)
                or manifest.get("release_id") != binding["candidate_release_id"]):
            raise RuntimeError("CANDIDATE_RELEASE_LINEAGE_MISMATCH")
        inventory = manifest.get("application_inventory")
        entries = inventory.get("entries") if isinstance(inventory, dict) else None
        if not isinstance(entries, list):
            raise RuntimeError("CANDIDATE_RELEASE_INVENTORY_MISSING")
        inventory_helper = _load_pinned_inventory_helper()
        actual_entries = inventory_helper.inventory_tree(app_root)
        if (actual_entries != entries or inventory_helper.inventory_digest(actual_entries) != inventory.get("aggregate_sha256")):
            raise RuntimeError("ACTIVE_CANDIDATE_APP_INVENTORY_MISMATCH")
        for relative, expected_sha in binding["candidate_source_sha256"].items():
            matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("path") == relative]
            if (len(matches) != 1 or matches[0].get("sha256") != expected_sha
                    or _sha(app_root / relative) != expected_sha):
                raise RuntimeError("ACTIVE_CANDIDATE_SOURCE_SHA_MISMATCH")
        if (activation.get("status") != "ACTIVATED_RUNTIME_ONLY"
                or activation.get("candidate_release_manifest_sha256") != binding["candidate_manifest_sha256"]
                or activation.get("candidate_staged_plist_sha256") != binding["candidate_staged_plist_sha256"]):
            raise RuntimeError("CANDIDATE_ACTIVATION_RECEIPT_MISMATCH")

        identity = cutover._process_identity_for_root(
            pid, app_root, selector_plist=plist_path, job_snapshot=job)
        recovery.ACTIVE_PID = pid
        return {
            "label": "com.lexi.v35.scheduler",
            "pid": pid,
            "release_id": binding["candidate_release_id"],
            "release_root": str(candidate_root),
            "app_root": str(app_root),
            "plist_sha256": binding["candidate_staged_plist_sha256"],
            "manifest_sha256": binding["candidate_manifest_sha256"],
            "manager_config_sha256": binding["manager_config_sha256"],
            "source_sha256": binding["candidate_source_sha256"],
            "active_release_identity": "VERIFIED_EXACT_CACHE_CANDIDATE",
            "process_identity": identity,
        }

    recovery._validate_active_scheduler_identity = validate_candidate_scheduler_identity
    try:
        validate_candidate_scheduler_identity()
    except Exception:
        recovery.ACTIVE_PID = None
    return recovery


if __name__ == "__main__":
    try:
        recovery = _bind_recovery()
    except Exception as error:
        raise SystemExit(f"RECOVERY_CANNOT_CONFIRM_BINDING:{type(error).__name__}:{str(error)[:200]}")
    raise SystemExit(recovery.main())
