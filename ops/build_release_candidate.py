#!/usr/bin/env python3
"""Build an inactive API candidate from the active release plus explicit deltas.

The builder verifies the active API plist, release manifest, and full app
inventory, then copies that immutable app and applies only a SHA-pinned delta
receipt. It never changes a live plist, calls ``launchctl``, or copies runtime
data or a virtual environment.
"""

from __future__ import annotations

import argparse
import importlib.util
from copy import deepcopy
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from .api_release_integration import (
        build_integrated_app, inventory_tree as integration_inventory_tree,
        module_role_contract,
    )
except ImportError:
    try:
        from api_release_integration import (
            build_integrated_app, inventory_tree as integration_inventory_tree,
            module_role_contract,
        )
    except ImportError:
        _integration_spec = importlib.util.spec_from_file_location(
            "_v4_api_release_integration", Path(__file__).with_name("api_release_integration.py")
        )
        if _integration_spec is None or _integration_spec.loader is None:
            raise ImportError("cannot load adjacent API release integration guard")
        _integration_module = importlib.util.module_from_spec(_integration_spec)
        sys.modules[_integration_spec.name] = _integration_module
        _integration_spec.loader.exec_module(_integration_module)
        build_integrated_app = _integration_module.build_integrated_app
        integration_inventory_tree = _integration_module.inventory_tree
        module_role_contract = _integration_module.module_role_contract

try:  # Running as ``python ops/build_release_candidate.py``.
    from prepare_api_only_cutover import (
        DEFAULT_FORMAL_RELEASE_ROOT,
        DEFAULT_MANAGER_STATE_ROOT,
        describe_preserved_environment,
        render_module_cutover,
        render_cutover,
        sha256_file,
    )
except ImportError:  # Imported as ``ops.build_release_candidate`` in tests.
    try:
        from .prepare_api_only_cutover import (
            DEFAULT_FORMAL_RELEASE_ROOT,
            DEFAULT_MANAGER_STATE_ROOT,
            describe_preserved_environment,
            render_module_cutover,
            render_cutover,
            sha256_file,
        )
    except ImportError:  # Loaded directly with importlib in a focused test.
        _helper_path = Path(__file__).with_name("prepare_api_only_cutover.py")
        _helper_spec = importlib.util.spec_from_file_location(
            "_v4_prepare_api_only_cutover", _helper_path
        )
        if _helper_spec is None or _helper_spec.loader is None:
            raise
        _helper = importlib.util.module_from_spec(_helper_spec)
        _helper_spec.loader.exec_module(_helper)
        DEFAULT_FORMAL_RELEASE_ROOT = _helper.DEFAULT_FORMAL_RELEASE_ROOT
        DEFAULT_MANAGER_STATE_ROOT = _helper.DEFAULT_MANAGER_STATE_ROOT
        describe_preserved_environment = _helper.describe_preserved_environment
        render_module_cutover = _helper.render_module_cutover
        render_cutover = _helper.render_cutover
        sha256_file = _helper.sha256_file


def _load_refactor_component(name: str):
    """Load an adjacent static helper for package, script and importlib callers."""
    qualified = (__package__ + "." + name) if __package__ else (__name__ + "__" + name)
    if qualified in sys.modules:
        return sys.modules[qualified]
    spec = importlib.util.spec_from_file_location(qualified, Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load release refactor component: " + name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(qualified, None)
        raise
    return module


_release_sources = _load_refactor_component("release_candidate_sources")
_release_audit = _load_refactor_component("release_candidate_audit")


SCHEMA_VERSION = "v4.release_candidate.v1"
DEFAULT_DEPENDENCIES = ("fastapi", "uvicorn", "httpx", "starlette", "pandas", "pyarrow", "pytdx")
DIST_RELATIVE_ROOT = "apps/web/dist"
SAFETY_KEYS = (
    "RESEARCH_ONLY",
    "research_only",
    "PRODUCTION_ALLOWED",
    "production_allowed",
    "BUY_GATE_UPDATED",
    "buy_gate_updated",
    "ORDERS_SENT",
    "orders_sent",
)

# Historical provenance for the original three inclusions.  The explicit CLI
# list is now the caller's reviewed allowlist; unlisted files are NEVER copied.
APPROVED_UNTRACKED_CANDIDATE_PATHS: dict[str, dict[str, object]] = {
    "ops/run_v35_macos_scheduler_daemon.py": {
        "feature": "persistent-minute scheduler process-lifetime wrapper",
        "required_by": "ops/launch_v35_macos_scheduler.sh",
        "import_evidence": 'exec "$python_bin" -S -m ops.run_v35_macos_scheduler_daemon ...',
    },
    "apps/web/src/components/review/DailyResearchReviewPanel.vue": {
        "feature": "M3 daily research review display",
        "required_by": "apps/web/src/views/ReviewView.vue",
        "import_evidence": 'import DailyResearchReviewPanel from "../components/review/DailyResearchReviewPanel.vue"',
    },
    "domains/daily_research_review.py": {
        "feature": "M3 daily research review read projection",
        "required_by": "apps/api/v35_api/review_router.py",
        "import_evidence": "from domains.daily_research_review import load_daily_research_review",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _absolute_preserving_symlink(path: Path) -> Path:
    """Make an executable binding absolute without discarding venv identity."""
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _is_within(path: Path, root: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(root))
    except ValueError:
        return False
    return True


def _normalise_relative(path: str | Path) -> str:
    return _release_sources._normalise_relative(path, _api=sys.modules[__name__])


def _run_git(source_root: Path, *args: str, binary: bool = False) -> str | bytes:
    return _release_sources._run_git(source_root, *args, binary=binary, _api=sys.modules[__name__])


def _git_tracked_paths(source_root: Path) -> list[str]:
    return _release_sources._git_tracked_paths(source_root, _api=sys.modules[__name__])


def _git_untracked_paths(source_root: Path) -> list[str]:
    return _release_sources._git_untracked_paths(source_root, _api=sys.modules[__name__])


def _validate_explicit_untracked_paths(
    source_root: Path,
    requested_paths: Sequence[str | Path],
    *,
    tracked_paths: Sequence[str],
    untracked_paths: Sequence[str],
) -> list[str]:
    """Validate the bounded untracked include list before copying anything."""
    return _release_sources._validate_explicit_untracked_paths(source_root, requested_paths, tracked_paths=tracked_paths, untracked_paths=untracked_paths, _api=sys.modules[__name__])


def _explicit_include_provenance(paths: Sequence[str]) -> list[dict[str, object]]:
    return _release_sources._explicit_include_provenance(paths, _api=sys.modules[__name__])


def copy_explicit_untracked_tree(
    source_root: Path, candidate_app: Path, relative_paths: Sequence[str]
) -> None:
    return _release_sources.copy_explicit_untracked_tree(source_root, candidate_app, relative_paths, _api=sys.modules[__name__])


def git_snapshot(
    source_root: Path,
    *,
    include_untracked_hashes: bool = True,
    included_untracked_paths: Sequence[str] = (),
) -> dict[str, object]:
    """Capture Git identity and a bounded working-tree summary without writes."""
    return _release_sources.git_snapshot(source_root, include_untracked_hashes=include_untracked_hashes, included_untracked_paths=included_untracked_paths, _api=sys.modules[__name__])


def snapshot_legacy_git(repo: Path, evidence_root: Path) -> dict[str, object]:
    """Save only tracked status/diff for the legacy repo.

    ``--untracked-files=no`` and ``git diff`` intentionally avoid walking or
    copying the legacy repository's potentially large untracked tree.
    """
    return _release_sources.snapshot_legacy_git(repo, evidence_root, _api=sys.modules[__name__])


def _entry_for_path(root: Path, relative: str) -> dict[str, object]:
    return _release_sources._entry_for_path(root, relative, _api=sys.modules[__name__])


def _walk_entries(root: Path) -> list[str]:
    return _release_sources._walk_entries(root, _api=sys.modules[__name__])


def _copy_one(source: Path, destination: Path) -> None:
    return _release_sources._copy_one(source, destination, _api=sys.modules[__name__])


def copy_tracked_tree(source_root: Path, candidate_app: Path, tracked_paths: Sequence[str]) -> None:
    return _release_sources.copy_tracked_tree(source_root, candidate_app, tracked_paths, _api=sys.modules[__name__])


def copy_dist(source_root: Path, candidate_app: Path) -> None:
    return _release_sources.copy_dist(source_root, candidate_app, _api=sys.modules[__name__])


def inventory_tree(root: Path) -> list[dict[str, object]]:
    # Keep the candidate producer and active-base guard on one inventory rule.
    return integration_inventory_tree(root)


def inventory_digest(entries: Sequence[Mapping[str, object]]) -> str:
    return _release_sources.inventory_digest(entries, _api=sys.modules[__name__])


def _describe_path(value: str) -> dict[str, object] | None:
    return _release_audit._describe_path(value, _api=sys.modules[__name__])


def _describe_scheduler_path_value(value: str) -> object:
    return _release_audit._describe_scheduler_path_value(value, _api=sys.modules[__name__])


def _file_summary(path: Path) -> dict[str, object]:
    return _release_audit._file_summary(path, _api=sys.modules[__name__])


def _load_plist(path: Path) -> dict[str, Any]:
    return _release_audit._load_plist(path, _api=sys.modules[__name__])


def _plist_environment(plist: Mapping[str, Any]) -> dict[str, str]:
    return _release_audit._plist_environment(plist, _api=sys.modules[__name__])


def audit_scheduler(
    *,
    source_root: Path,
    scheduler_plist_path: Path,
) -> dict[str, object]:
    """Compare the current scheduler binding with v4 entrypoint dependencies."""
    return _release_audit.audit_scheduler(source_root=source_root, scheduler_plist_path=scheduler_plist_path, _api=sys.modules[__name__])


def _probe_dependency_process(python: Path, names: Sequence[str]) -> dict[str, object]:
    return _release_audit._probe_dependency_process(python, names, _api=sys.modules[__name__])


def dependency_probe(python: Path, names: Sequence[str] = DEFAULT_DEPENDENCIES) -> dict[str, object]:
    # Preserve the venv launcher path for subprocess execution.  Resolving a
    # venv symlink first would invoke the base interpreter and silently lose
    # the venv's site-packages, which would make a valid dependency set look
    # missing.
    return _release_audit.dependency_probe(python, names, _api=sys.modules[__name__])


def manager_state_audit(
    *,
    current_root: Path,
    candidate_root: Path,
) -> dict[str, object]:
    current_root = _resolved(current_root)
    candidate_root = _resolved(candidate_root)
    commits = current_root / ".commits"
    sample_commits: list[str] = []
    if commits.is_dir():
        for date_dir in sorted(commits.iterdir()):
            if not date_dir.is_dir() or date_dir.is_symlink():
                continue
            for path in sorted(date_dir.iterdir()):
                if path.is_file():
                    sample_commits.append(path.relative_to(commits).as_posix())
                if len(sample_commits) >= 5:
                    break
            if len(sample_commits) >= 5:
                break
    candidate_commits = candidate_root / ".commits"
    candidate_commits.mkdir(parents=True, exist_ok=True)
    distinct = _resolved(current_root) != _resolved(candidate_root)
    return {
        "status": "OBSERVED" if distinct else "CANNOT_CONFIRM",
        "current_root": str(current_root),
        "current_root_exists": current_root.exists() or current_root.is_symlink(),
        "current_commits_root": str(commits),
        "current_commits_exists": commits.is_dir(),
        "observed_commit_samples": sample_commits,
        "authority_layout": ".commits/<YYYYMMDD>/<input_identity>.json",
        "candidate_root": str(candidate_root),
        "candidate_root_exists": candidate_root.exists(),
        "candidate_commits_root": str(candidate_commits),
        "candidate_state_is_empty": not any(candidate_commits.iterdir()),
        "roots_are_distinct": distinct,
        "candidate_state_copied": False,
        "current_state_modified": False,
        "write_guard": "Candidate API must receive V4_MANAGER_RESEARCH_STATE_ROOT and old/new writers must not share a root.",
    }


# Stage service candidate implementation stays separate from the API release builder.
if __package__:
    from . import build_release_candidate_stage as _stage_builders
else:
    try:
        import build_release_candidate_stage as _stage_builders
    except ImportError:
        _stage_spec = importlib.util.spec_from_file_location(
            "_v4_build_release_candidate_stage",
            Path(__file__).with_name("build_release_candidate_stage.py"),
        )
        if _stage_spec is None or _stage_spec.loader is None:
            raise ImportError("cannot load the Stage candidate builder module")
        _stage_builders = importlib.util.module_from_spec(_stage_spec)
        sys.modules[_stage_spec.name] = _stage_builders
        _stage_spec.loader.exec_module(_stage_builders)
_stage_builders.bind_core(sys.modules[__name__])
for _stage_name in (
    "_guard_candidate_root", "_candidate_file_summary", "_stage_scheduler_identity",
    "STAGE_SERVICE_LABEL", "STAGE_SERVICE_OVERLAY_PATHS", "STAGE_DATA_PATH_KEYS",
    "STAGE_DISTRIBUTIONS", "_active_stage_release", "_merge_active_stage_config",
    "_copy_stage_overlay", "_git_tracked_modes", "_copy_stage_source_tree",
    "_probe_stage_runtime", "_deployed_stage_config_evidence", "_runtime_has_pip",
    "_render_stage_service_binding", "build_stage_service_candidate",
):
    globals()[_stage_name] = getattr(_stage_builders, _stage_name)


def build_module_candidate(
    *, source_root: Path, candidate_root: Path, active_api_plist_path: Path,
    release_id: str, role: str, api_integration_delta_receipt_path: Path,
    base_role: str = "gateway", bootstrap_transition: bool = False,
    formal_release_root: Path = DEFAULT_FORMAL_RELEASE_ROOT,
    receipt_path: Path | None = None,
    include_untracked_paths: Sequence[str | Path] = (),
) -> dict[str, object]:
    """Build one complete role release from the verified active API snapshot."""
    if role not in {"gateway", "stage", "manager"} or base_role not in {"gateway", "stage", "manager"}:
        raise ValueError("API_MODULE_ROLE_INVALID")
    source_root = _resolved(source_root)
    gateway_contract = module_role_contract()
    role_config = gateway_contract["roles"][role]
    candidate_root = _guard_candidate_root(
        candidate_root, source_root=source_root, formal_release_root=formal_release_root
    )
    role_release_root = _resolved(Path(str(role_config["release_root"])))
    if _is_within(candidate_root, role_release_root) or _is_within(role_release_root, candidate_root):
        raise ValueError("module candidate must be separate from its formal role release root")
    if candidate_root.name != release_id:
        raise ValueError("module release id must match the candidate directory name")
    active_api_plist_path = _resolved(active_api_plist_path)
    delta_path = _resolved(api_integration_delta_receipt_path)
    if not source_root.is_dir() or not active_api_plist_path.is_file() or not delta_path.is_file():
        raise FileNotFoundError("module candidate source, active role plist, or delta receipt is missing")
    if delta_path.is_symlink():
        raise ValueError("API_RELEASE_DELTA_RECEIPT_PATH_INVALID")
    if receipt_path is None:
        receipt_path = candidate_root.parent / f"{candidate_root.name}-build-receipt.json"
    receipt_path = _resolved(receipt_path)
    if _is_within(receipt_path, source_root) or _is_within(receipt_path, formal_release_root):
        raise ValueError("module candidate receipt must be outside source and formal release roots")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite receipt: {receipt_path}")

    candidate_root.mkdir()
    marker = candidate_root / ".candidate-build-in-progress"
    marker.write_text(f"created_at={utc_now()}\n")
    try:
        integration = build_integrated_app(
            active_api_plist_path=active_api_plist_path,
            source_root=source_root,
            candidate_root=candidate_root,
            delta_receipt_path=delta_path,
            explicit_untracked_paths=[str(item) for item in include_untracked_paths],
            role=role,
            base_role=base_role,
            bootstrap_transition=bootstrap_transition,
        )
        candidate_app = candidate_root / "app"
        entries = inventory_tree(candidate_app)
        module_contract_path = candidate_app / "deployment" / "api_module_contracts.json"
        if not module_contract_path.is_file() or module_contract_path.is_symlink():
            raise ValueError("API_RELEASE_MODULE_CONTRACT_REQUIRED")
        with module_contract_path.open("r", encoding="utf-8") as handle:
            module_contract = json.load(handle)
        if module_contract.get("schema_version") != "v4.api_module_contracts.v1":
            raise ValueError("API_MODULE_CONTRACT_SCHEMA_INVALID")
        candidate_role_config = module_contract.get("roles", {}).get(role)
        if not isinstance(candidate_role_config, Mapping):
            raise ValueError("API_MODULE_ROLE_CONFIG_MISSING")
        module_contract_sha256 = sha256_file(module_contract_path)
        manifest: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": utc_now(),
            "candidate_status": "READY_FOR_REVIEW",
            "activation_status": "NOT_ACTIVATED",
            "deployment_status": "CANNOT_CONFIRM",
            "candidate": {
                "root": str(candidate_root),
                "app_root": str(candidate_app),
                "release_id": release_id,
                "module_role": role,
                "module_contract_sha256": module_contract_sha256,
                "formal_release_root": str(formal_release_root),
                "data_copy_performed": False,
                "runtime_venv_copied": False,
                "ignored_runtime_data_copied": False,
                "overwrite_policy": "refuse existing role candidate; active plist unchanged",
            },
            "source": {
                "active_role_plist": str(active_api_plist_path),
                "api_integration_delta_receipt": str(delta_path),
                "active_release_bytes_copied": True,
                "source_workspace_full_tree_copied": False,
            },
            "api_integration": integration,
            "role_contract": {
                "label": candidate_role_config["label"],
                "port": candidate_role_config["port"],
                "plist_name": candidate_role_config["plist_name"],
                "release_root": candidate_role_config["release_root"],
                "lock_name": candidate_role_config["lock_name"],
                "owns_static_assets": candidate_role_config["owns_static_assets"],
            },
            "application_inventory": {
                "entry_count": len(entries),
                "aggregate_sha256": inventory_digest(entries),
                "entries": entries,
            },
            "verification_gaps": [
                "module API was not activated or restarted by this builder",
                "target port availability must be checked again immediately before activation",
                "cross-role behavior and gateway static preservation await independent review and readback",
            ],
        }
        manifest_path = candidate_root / "release-manifest.json"
        _json_dump(manifest_path, manifest)
        manifest_sha = sha256_file(manifest_path)
        plan = render_module_cutover(
            source_active_plist_path=active_api_plist_path,
            candidate_root=candidate_root,
            release_id=release_id,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha,
            role=role,
            base_role=base_role,
            source_root=source_root,
            formal_release_root=formal_release_root,
        )
        marker.unlink()
        receipt = {
            "schema_version": "v4.api_module_candidate_receipt.v1",
            "candidate_status": manifest["candidate_status"],
            "activation_status": "NOT_ACTIVATED",
            "deployment_status": "CANNOT_CONFIRM",
            "target_role": role,
            "candidate_root": str(candidate_root),
            "manifest_path": str(manifest_path),
            "manifest_sha256": manifest_sha,
            "application_inventory_sha256": manifest["application_inventory"]["aggregate_sha256"],
            "delta_paths": [row["path"] for row in integration["delta_entries"]],
            "staged_plist": plan["candidate_plist"],
            "cutover_plan": plan["plan_path"],
            "active_plist_changed": False,
            "launchctl_called": False,
        }
        _json_dump(receipt_path, receipt)
        receipt["receipt_path"] = str(receipt_path)
        return receipt
    except Exception:
        raise


def build_candidate(
    *,
    source_root: Path,
    candidate_root: Path,
    api_plist_path: Path,
    scheduler_plist_path: Path,
    python: Path,
    release_id: str,
    api_integration_delta_receipt_path: Path,
    backup_plist_path: Path | None = None,
    legacy_repo: Path | None = None,
    legacy_evidence_root: Path | None = None,
    formal_release_root: Path = DEFAULT_FORMAL_RELEASE_ROOT,
    dependency_names: Sequence[str] = DEFAULT_DEPENDENCIES,
    receipt_path: Path | None = None,
    include_untracked_paths: Sequence[str | Path] = (),
) -> dict[str, object]:
    source_root = _resolved(source_root)
    candidate_root = _guard_candidate_root(
        candidate_root, source_root=source_root, formal_release_root=formal_release_root
    )
    api_plist_path = _resolved(api_plist_path)
    scheduler_plist_path = _resolved(scheduler_plist_path)
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    if not api_plist_path.is_file():
        raise FileNotFoundError(api_plist_path)
    if not scheduler_plist_path.is_file():
        raise FileNotFoundError(scheduler_plist_path)
    api_integration_delta_receipt_path = _resolved(api_integration_delta_receipt_path)
    if not api_integration_delta_receipt_path.is_file() or api_integration_delta_receipt_path.is_symlink():
        raise FileNotFoundError(api_integration_delta_receipt_path)

    if receipt_path is None:
        receipt_path = candidate_root.parent / f"{candidate_root.name}-build-receipt.json"
    receipt_path = _resolved(receipt_path)
    if _is_within(receipt_path, source_root) or _is_within(receipt_path, formal_release_root):
        raise ValueError("receipt path must not be in source or formal release root")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite receipt: {receipt_path}")

    legacy_receipt: dict[str, object] | None = None
    if legacy_repo is not None:
        legacy_root = legacy_evidence_root or (candidate_root.parent / "legacy-v35-git-snapshot")
        if _is_within(legacy_root, source_root) or _is_within(legacy_root, formal_release_root):
            raise ValueError("legacy Git evidence must be outside source and formal release trees")
        legacy_receipt = snapshot_legacy_git(legacy_repo, legacy_root)

    # Reserve the destination before any source content is written.  A
    # marker makes an interrupted build visibly incomplete and prevents a
    # later invocation from treating it as an overwriteable target.
    candidate_root.mkdir()
    marker = candidate_root / ".candidate-build-in-progress"
    marker.write_text(f"created_at={utc_now()}\n")
    try:
        candidate_app = candidate_root / "app"
        tracked_paths = _git_tracked_paths(source_root)
        untracked_paths = _git_untracked_paths(source_root)
        included_untracked_paths = _validate_explicit_untracked_paths(
            source_root,
            include_untracked_paths,
            tracked_paths=tracked_paths,
            untracked_paths=untracked_paths,
        )
        api_integration = build_integrated_app(
            active_api_plist_path=api_plist_path,
            source_root=source_root,
            candidate_root=candidate_root,
            delta_receipt_path=api_integration_delta_receipt_path,
            explicit_untracked_paths=included_untracked_paths,
        )
        app_inventory = inventory_tree(candidate_app)
        if app_inventory != integration_inventory_tree(candidate_app):
            raise ValueError("API_RELEASE_INTEGRATION_INVENTORY_BACKEND_MISMATCH")
        dist_inventory = [
            item
            for item in app_inventory
            if str(item["path"]) == DIST_RELATIVE_ROOT
            or str(item["path"]).startswith(DIST_RELATIVE_ROOT + "/")
        ]
        source_snapshot = git_snapshot(
            source_root,
            include_untracked_hashes=True,
            included_untracked_paths=included_untracked_paths,
        )
        source_snapshot["candidate_copy_policy"] = (
            "verified active API release app plus only the declared SHA-pinned delta receipt; "
            "all non-delta active release entries are byte-preserved"
        )
        with api_plist_path.open("rb") as handle:
            api_plist = plistlib.load(handle)
        api_environment = describe_preserved_environment(api_plist)
        scheduler_audit = audit_scheduler(
            source_root=source_root,
            scheduler_plist_path=scheduler_plist_path,
        )
        raw_manager_root = api_environment["variables"].get("V4_MANAGER_RESEARCH_STATE_ROOT")
        if not (isinstance(raw_manager_root, Mapping)
                and isinstance(raw_manager_root.get("value"), str)
                and Path(str(raw_manager_root["value"])).is_absolute()):
            raise ValueError("explicit V4_MANAGER_RESEARCH_STATE_ROOT is required")
        current_manager_root = Path(str(raw_manager_root["value"]))
        candidate_manager_root = candidate_root / "state" / "manager_auto_research"
        state_audit = manager_state_audit(
            current_root=current_manager_root,
            candidate_root=candidate_manager_root,
        )
        dependencies = dependency_probe(python, dependency_names)
        source_symlinks = [item for item in app_inventory if item.get("kind") == "symlink"]
        missing_symlink_targets = [
            str(item["path"]) for item in source_symlinks if not item.get("target_exists")
        ]
        manifest: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": utc_now(),
            "candidate_status": "READY_FOR_REVIEW"
            if dependencies.get("status") == "OBSERVED_RESOLVED" and not missing_symlink_targets
            else "READY_FOR_REVIEW_WITH_DEPENDENCY_GAP",
            "activation_status": "NOT_ACTIVATED",
            "deployment_status": "CANNOT_CONFIRM",
            "source": {
                "root": str(source_root),
                "git": source_snapshot,
                "tracked_file_count": len(tracked_paths),
                "tracked_paths_copied": False,
                "active_release_bytes_copied": True,
                "explicit_untracked_paths_copied": included_untracked_paths,
                "explicit_untracked_provenance": _explicit_include_provenance(
                    included_untracked_paths
                ),
                "working_tree_dist_included": False,
                "api_integration_delta_receipt_path": str(api_integration_delta_receipt_path),
            },
            "api_integration": api_integration,
            "candidate": {
                "root": str(candidate_root),
                "app_root": str(candidate_app),
                "release_id": release_id,
                "formal_release_root": str(_resolved(formal_release_root)),
                "overwrite_policy": "refuse existing candidate root; API pointer changes are not performed",
                "data_copy_performed": False,
                "ignored_runtime_data_copied": False,
                "runtime_venv_copied": False,
            },
            "application_inventory": {
                "entry_count": len(app_inventory),
                "aggregate_sha256": inventory_digest(app_inventory),
                "entries": app_inventory,
                "symlink_entries": source_symlinks,
                "missing_symlink_targets": missing_symlink_targets,
            },
            "frontend_dist": {
                "source_relative_root": DIST_RELATIVE_ROOT,
                "entry_count": len(dist_inventory),
                "aggregate_sha256": inventory_digest(dist_inventory),
                "entries": dist_inventory,
                "included_from_current_source": False,
                "preserved_from_active_release": True,
            },
            "external_dependencies": dependencies,
            "runtime_environment": {
                "api_only_current_plist": {
                    "path": str(api_plist_path),
                    "sha256": sha256_file(api_plist_path),
                    "preserved_environment": api_environment,
                },
                "roots_and_safety_are_preserved_in_staged_plan": True,
                "formal_runtime_inventory": {
                    "status": "CANNOT_CONFIRM",
                    "reason": "No runtime inventory manifest was supplied; path probes are observational.",
                },
            },
            "manager_state": state_audit,
            "scheduler_audit": scheduler_audit,
            "cutover": {
                "api_only_plan": "config/api-only-cutover-plan.json",
                "staged_plist": "config/com.lexi.v35.api-only.plist",
                "launchctl_called": False,
                "formal_plist_changed": False,
                "scheduler_rebound": False,
                "scheduler_candidate": "config/com.lexi.v35.scheduler.plist",
                "manager_state_must_be_isolated": True,
            },
            "verification_gaps": [
                "formal runtime inventory and dependency manifest are not present in this candidate receipt",
                "API process/API/UI/natural slot were not activated or verified by this builder",
                "scheduler semantic parity and a v4 scheduler rebind remain CANNOT_CONFIRM",
                "historical manager-state data was not copied or migrated; new authority is .commits/<YYYYMMDD>/<input_identity>.json",
            ],
        }
        manifest_path = candidate_root / "release-manifest.json"
        _json_dump(manifest_path, manifest)
        manifest_sha = sha256_file(manifest_path)
        plan = render_cutover(
            source_plist_path=api_plist_path,
            candidate_root=candidate_root,
            release_id=release_id,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha,
            backup_plist_path=backup_plist_path,
            current_manager_state_root=current_manager_root,
            candidate_manager_state_root=candidate_manager_root,
            source_root=source_root,
            formal_release_root=formal_release_root,
        )
        scheduler_candidate = _stage_scheduler_identity(
            source_plist=scheduler_plist_path, candidate_root=candidate_root,
            release_id=release_id, manifest_path=manifest_path, manifest_sha256=manifest_sha)
        marker.unlink()
        receipt = {
            "schema_version": "v4.release_candidate_receipt.v1",
            "generated_at": utc_now(),
            "candidate_status": manifest["candidate_status"],
            "activation_status": "NOT_ACTIVATED",
            "deployment_status": "CANNOT_CONFIRM",
            "candidate": _candidate_file_summary(candidate_root),
            "manifest_sha256": manifest_sha,
            "application_inventory_sha256": manifest["application_inventory"]["aggregate_sha256"],
            "frontend_dist_inventory_sha256": manifest["frontend_dist"]["aggregate_sha256"],
            "frontend_dist_entry_count": len(dist_inventory),
            "explicit_untracked_paths": included_untracked_paths,
            "staged_cutover_plan": {
                "activation_status": plan["activation_status"],
                "launchctl_called": plan["launchctl_called"],
                "manager_state": plan["manager_state"],
                "candidate_plist_sha256": plan["candidate_plist"]["sha256"],
                "plan_path": str(candidate_root / "config" / "api-only-cutover-plan.json"),
            },
            "scheduler_candidate": scheduler_candidate,
            "scheduler_decision": scheduler_audit["decision"],
            "scheduler_status": scheduler_audit["status"],
            "source_commit": source_snapshot["commit"],
            "source_tracked_diff_sha256": source_snapshot["tracked_diff_sha256"],
            "guard": "Candidate is evidence-only. No formal release, launchd service, scheduled task, or data root was changed.",
        }
        if legacy_receipt is not None:
            receipt["legacy_git_snapshot"] = legacy_receipt
        _json_dump(receipt_path, receipt)
        receipt["receipt_path"] = str(receipt_path)
        return receipt
    except Exception:
        # Leave a marked incomplete candidate for inspection.  Never remove
        # a path that existed before this invocation.
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--api-plist", type=Path)
    parser.add_argument(
        "--api-module-role", choices=("gateway", "stage", "manager"),
        help="build one isolated API role from the active gateway release plus its SHA-pinned delta",
    )
    parser.add_argument("--api-module-base-role", choices=("gateway", "stage", "manager"), default="gateway")
    parser.add_argument("--api-module-bootstrap-transition", action="store_true")
    parser.add_argument("--scheduler-plist", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--release-id", required=True)
    parser.add_argument(
        "--api-integration-delta-receipt",
        type=Path,
        help="required before/after SHA receipt for the exact API files changed from the active release",
    )
    parser.add_argument(
        "--stage-service-candidate",
        action="store_true",
        help="build an inactive Stage-only service binding and source package",
    )
    parser.add_argument("--stage-plist", type=Path)
    parser.add_argument(
        "--stage-runtime-python",
        type=Path,
        help="explicit interpreter for com.lexi.stage-center.scheduler; defaults to the Stage source config",
    )
    parser.add_argument(
        "--stage-overlay-path",
        dest="stage_overlay_paths",
        action="append",
        default=[],
        metavar="RELATIVE_PATH",
        help="explicitly overlay one reviewed Stage source dependency on the active release baseline; repeat per path",
    )
    parser.add_argument("--backup-plist", type=Path)
    parser.add_argument("--legacy-repo", type=Path)
    parser.add_argument("--legacy-evidence-root", type=Path)
    parser.add_argument("--receipt-path", type=Path)
    parser.add_argument("--formal-release-root", type=Path, default=DEFAULT_FORMAL_RELEASE_ROOT)
    parser.add_argument(
        "--include-untracked-path",
        dest="include_untracked_paths",
        action="append",
        default=[],
        metavar="RELATIVE_PATH",
        help=(
            "explicitly include one approved current untracked file; repeat for "
            "each approved path; all other untracked files remain excluded"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.api_module_role is not None:
            if args.stage_service_candidate:
                raise ValueError("--api-module-role cannot be combined with --stage-service-candidate")
            if args.api_plist is None or args.api_integration_delta_receipt is None:
                raise ValueError("--api-plist and --api-integration-delta-receipt are required for an API module")
            receipt = build_module_candidate(
                source_root=args.source_root,
                candidate_root=args.candidate_root,
                active_api_plist_path=args.api_plist,
                release_id=args.release_id,
                role=args.api_module_role,
                api_integration_delta_receipt_path=args.api_integration_delta_receipt,
                base_role=args.api_module_base_role,
                bootstrap_transition=args.api_module_bootstrap_transition,
                formal_release_root=args.formal_release_root,
                receipt_path=args.receipt_path,
                include_untracked_paths=args.include_untracked_paths,
            )
            print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.stage_service_candidate:
            if args.stage_plist is None:
                raise ValueError("--stage-plist is required with --stage-service-candidate")
            stage_overlays = args.stage_overlay_paths or None
            receipt = build_stage_service_candidate(
                source_root=args.source_root,
                candidate_root=args.candidate_root,
                stage_plist_path=args.stage_plist,
                runtime_python=args.stage_runtime_python,
                release_id=args.release_id,
                formal_release_root=args.formal_release_root,
                receipt_path=args.receipt_path,
                overlay_paths=stage_overlays,
            )
            print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.api_plist is None or args.scheduler_plist is None:
            raise ValueError("--api-plist and --scheduler-plist are required for the full V4 candidate")
        if args.api_integration_delta_receipt is None:
            raise ValueError("--api-integration-delta-receipt is required for an API candidate")
        receipt = build_candidate(
            source_root=args.source_root,
            candidate_root=args.candidate_root,
            api_plist_path=args.api_plist,
            scheduler_plist_path=args.scheduler_plist,
            python=args.python,
            release_id=args.release_id,
            api_integration_delta_receipt_path=args.api_integration_delta_receipt,
            backup_plist_path=args.backup_plist,
            legacy_repo=args.legacy_repo,
            legacy_evidence_root=args.legacy_evidence_root,
            receipt_path=args.receipt_path,
            formal_release_root=args.formal_release_root,
            include_untracked_paths=args.include_untracked_paths,
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (FileExistsError, FileNotFoundError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"release candidate build refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
