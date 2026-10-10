"""Stage-service candidate construction extracted from the V4 release builder."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .stage_service_overlay_contract import (
        LEGACY_STAGE_SERVICE_OVERLAY_PATHS,
        STAGE_DEADLINE_SERVICE_LABEL,
        STAGE_DATA_PATH_KEYS,
        STAGE_DISTRIBUTIONS,
        STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS,
        STAGE_SERVICE_RELEASE_CLOSURE_PATHS,
        STAGE_SERVICE_RELEASE_CLOSURE_SHA256,
        STAGE_SERVICE_LABEL,
        STAGE_SERVICE_LABELS,
        STAGE_SERVICE_OVERLAY_PATHS,
        STRICT_STAGE_SERVICE_OVERLAY_PATHS,
        _active_stage_manifest_identity,
        _validate_stage_manifest_bindings,
        _effective_stage_config,
        _merge_active_stage_config,
        require_complete_strict_stage_overlay,
        require_stage_overlay_source_hashes,
    )
except ImportError:
    _overlay_spec = importlib.util.spec_from_file_location(
        "_v4_stage_service_overlay_contract",
        Path(__file__).with_name("stage_service_overlay_contract.py"),
    )
    if _overlay_spec is None or _overlay_spec.loader is None:
        raise ImportError("cannot load the Stage service overlay contract")
    _overlay_contract = importlib.util.module_from_spec(_overlay_spec)
    _overlay_spec.loader.exec_module(_overlay_contract)
    LEGACY_STAGE_SERVICE_OVERLAY_PATHS = _overlay_contract.LEGACY_STAGE_SERVICE_OVERLAY_PATHS
    STAGE_DEADLINE_SERVICE_LABEL = _overlay_contract.STAGE_DEADLINE_SERVICE_LABEL
    STAGE_DATA_PATH_KEYS = _overlay_contract.STAGE_DATA_PATH_KEYS
    STAGE_DISTRIBUTIONS = _overlay_contract.STAGE_DISTRIBUTIONS
    STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS = _overlay_contract.STAGE_SERVICE_RELEASE_CLOSURE_ADDED_PATHS
    STAGE_SERVICE_RELEASE_CLOSURE_PATHS = _overlay_contract.STAGE_SERVICE_RELEASE_CLOSURE_PATHS
    STAGE_SERVICE_RELEASE_CLOSURE_SHA256 = _overlay_contract.STAGE_SERVICE_RELEASE_CLOSURE_SHA256
    STAGE_SERVICE_LABEL = _overlay_contract.STAGE_SERVICE_LABEL
    STAGE_SERVICE_LABELS = _overlay_contract.STAGE_SERVICE_LABELS
    STAGE_SERVICE_OVERLAY_PATHS = _overlay_contract.STAGE_SERVICE_OVERLAY_PATHS
    STRICT_STAGE_SERVICE_OVERLAY_PATHS = _overlay_contract.STRICT_STAGE_SERVICE_OVERLAY_PATHS
    _active_stage_manifest_identity = _overlay_contract._active_stage_manifest_identity
    _validate_stage_manifest_bindings = _overlay_contract._validate_stage_manifest_bindings
    _effective_stage_config = _overlay_contract._effective_stage_config
    _merge_active_stage_config = _overlay_contract._merge_active_stage_config
    require_complete_strict_stage_overlay = _overlay_contract.require_complete_strict_stage_overlay
    require_stage_overlay_source_hashes = _overlay_contract.require_stage_overlay_source_hashes

try:
    from .prepare_api_only_cutover import DEFAULT_FORMAL_RELEASE_ROOT
except ImportError:
    try:
        from prepare_api_only_cutover import DEFAULT_FORMAL_RELEASE_ROOT
    except ImportError:
        _cutover = sys.modules.get("_v4_prepare_api_only_cutover")
        if _cutover is None:
            _helper_path = Path(__file__).with_name("prepare_api_only_cutover.py")
            _helper_spec = importlib.util.spec_from_file_location(
                "_v4_stage_prepare_api_only_cutover", _helper_path
            )
            if _helper_spec is None or _helper_spec.loader is None:
                raise
            _cutover = importlib.util.module_from_spec(_helper_spec)
            _helper_spec.loader.exec_module(_cutover)
        DEFAULT_FORMAL_RELEASE_ROOT = _cutover.DEFAULT_FORMAL_RELEASE_ROOT

_CORE = None
_CORE_HELPERS = (
    "_resolved",
    "_is_within",
    "_normalise_relative",
    "_json_dump",
    "_copy_one",
    "_load_plist",
    "inventory_tree",
    "inventory_digest",
    "sha256_file",
    "_absolute_preserving_symlink",
    "utc_now",
)


def bind_core(core: object) -> None:
    """Bind the compatibility facade so shared behavior and patches stay live."""
    global _CORE
    _CORE = core
    for name in _CORE_HELPERS:
        globals()[name] = getattr(core, name)


def _run_git(source_root: Path, *args: str, binary: bool = False) -> str | bytes:
    if _CORE is None:
        raise RuntimeError("Stage candidate helpers are not bound to the release facade")
    return _CORE._run_git(source_root, *args, binary=binary)


def _guard_candidate_root(
    candidate_root: Path,
    *,
    source_root: Path,
    formal_release_root: Path,
) -> Path:
    candidate_root = _resolved(candidate_root)
    source_root = _resolved(source_root)
    formal_release_root = _resolved(formal_release_root)
    if candidate_root.exists() or candidate_root.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing candidate root: {candidate_root}")
    if _is_within(candidate_root, source_root) or _is_within(source_root, candidate_root):
        raise ValueError("candidate root must be separate from source checkout")
    if _is_within(candidate_root, formal_release_root):
        raise ValueError("candidate root must not be inside the formal release root")
    if not candidate_root.parent.exists():
        candidate_root.parent.mkdir(parents=True, exist_ok=True)
    return candidate_root


def _candidate_file_summary(candidate_root: Path) -> dict[str, object]:
    config = candidate_root / "config"
    staged = config / "com.lexi.v35.api-only.plist"
    plan = config / "api-only-cutover-plan.json"
    return {
        "manifest": {
            "path": str(candidate_root / "release-manifest.json"),
            "sha256": sha256_file(candidate_root / "release-manifest.json"),
        },
        "staged_api_plist": {"path": str(staged), "sha256": sha256_file(staged)},
        "cutover_plan": {"path": str(plan), "sha256": sha256_file(plan)},
        "candidate_root": str(candidate_root),
    }


def _stage_scheduler_identity(*, source_plist: Path, candidate_root: Path, release_id: str,
                              manifest_path: Path, manifest_sha256: str) -> dict[str, object]:
    """Render a copy only; no launchd calls or mutation of active plist/state."""
    payload = plistlib.loads(source_plist.read_bytes())
    env = payload.get("EnvironmentVariables")
    args = payload.get("ProgramArguments")
    if (not isinstance(env, dict) or not isinstance(args, list) or len(args) != 2
            or args[0] != "/bin/bash" or Path(str(args[1])).name != "launch_v35_macos_scheduler.sh"
            or not Path(str(env.get("V35_APP_ROOT", ""))).is_absolute()):
        raise ValueError("explicit scheduler launcher/app binding is required")
    old_app = Path(env["V35_APP_ROOT"])
    app = candidate_root / "app"
    staged = deepcopy(payload); new_env = staged["EnvironmentVariables"]
    # Only already-explicit code paths within the old app are rebased. External
    # data/credential/manager roots remain unchanged and require local review.
    rebound_paths = []
    for key, value in list(new_env.items()):
        if isinstance(value, str) and Path(value).is_absolute():
            try:
                relative = Path(value).relative_to(old_app)
            except ValueError:
                continue
            new_env[key] = str(app / relative)
            rebound_paths.append(new_env[key])
    new_env.update({"V35_APP_ROOT": str(app), "V35_RELEASE_ID": release_id,
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path), "V35_RELEASE_MANIFEST_SHA256": manifest_sha256,
        "PYTHONPATH": str(app / "upstreams") + ":" + str(app)})
    launcher = app / "ops/launch_v35_macos_scheduler.sh"
    staged["ProgramArguments"] = ["/bin/bash", str(launcher)]
    staged["WorkingDirectory"] = str(app)
    # Flag values are preserved, not repaired; unsafe sources are refused.
    for key in ("production_allowed", "buy_gate_updated", "orders_sent", "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT"):
        if key in new_env and str(new_env[key]).lower() not in {"false", "0"}:
            raise ValueError("unsafe scheduler source environment")
        new_env[key] = "false"
    target = candidate_root / "config/com.lexi.v35.scheduler.plist"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(plistlib.dumps(staged, fmt=plistlib.FMT_XML, sort_keys=True))
    return {"activation_status": "NOT_ACTIVATED", "launchctl_called": False,
            "path": str(target), "sha256": sha256_file(target),
            "release_id": release_id, "release_manifest_sha256": manifest_sha256,
            "missing_rebound_paths": sorted({str(path) for path in [launcher, *map(Path, rebound_paths)] if not path.exists()}),
            "external_runtime_bindings": "PRESERVED_REQUIRE_LOCAL_REVIEW"}


def _active_stage_release(stage_plist_path: Path, baseline_release_root: Path | None = None) -> dict[str, object]:
    """Resolve and verify the complete app tree named by the Stage plist."""
    payload = _load_plist(stage_plist_path)
    service_label = payload.get("Label")
    if service_label not in STAGE_SERVICE_LABELS:
        raise ValueError("Stage source LaunchAgent label mismatch")
    arguments = payload.get("ProgramArguments")
    deadline_only = service_label == STAGE_DEADLINE_SERVICE_LABEL
    expected_argument_count = 6 if deadline_only else 5
    if (not isinstance(arguments, list) or len(arguments) != expected_argument_count
            or (deadline_only and arguments[5] != "--deadline-only")):
        raise ValueError("Stage active plist arguments are invalid")
    script = Path(str(arguments[2])).expanduser()
    config = Path(str(arguments[4])).expanduser()
    if script.name != "run_stage_center_nodes.py" or script.parent.name != "ops":
        raise ValueError("Stage active plist entrypoint is invalid")
    app_root = script.parent.parent
    if config != app_root / "stage_center_tick_config.json":
        raise ValueError("Stage active plist config is outside its app baseline")
    release_root = baseline_release_root or app_root.parent
    release_root = _resolved(release_root)
    if _resolved(app_root) != release_root / "app":
        raise ValueError("Stage active release root does not match plist app path")
    if not config.is_file() or not script.is_file():
        raise FileNotFoundError("Stage active release entrypoint/config is missing")
    manifest_path = release_root / "release-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("Stage active release manifest is missing")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    identity = _active_stage_manifest_identity(manifest, app_root=app_root, release_root=release_root)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    active_config = json.loads(config.read_text(encoding="utf-8"))
    if not isinstance(active_config, dict) or not active_config.get("preselection_source_root"):
        raise ValueError("Stage active release has no preselection_source_root contract")
    _validate_stage_manifest_bindings(identity, environment=payload.get("EnvironmentVariables"),
        active_config=active_config, manifest_path=manifest_path, manifest_sha256=manifest_sha)
    stored = manifest.get("application_inventory")
    if not isinstance(stored, dict) or not isinstance(stored.get("entries"), list):
        raise ValueError("Stage active release inventory is missing")
    if inventory_digest(stored["entries"]) != stored.get("aggregate_sha256"):
        raise ValueError("Stage active release inventory manifest digest mismatch")
    actual = inventory_tree(app_root)
    def release_entries(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        normalised: list[dict[str, Any]] = []
        for row in entries:
            entry = {key: value for key, value in row.items() if key != "target_exists"}
            # macOS can report a copied symlink's lstat mode differently even
            # though its link target is identical. Symlink mode is not an
            # executable permission contract, so retain path and target checks.
            if entry.get("kind") == "symlink":
                entry.pop("mode", None)
            normalised.append(entry)
        return normalised
    if release_entries(actual) != release_entries(stored["entries"]):
        raise ValueError("Stage active release app does not match its inventory")
    return {
        "release_root": release_root,
        "app_root": app_root,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "identity": identity,
        "manifest_sha256": manifest_sha,
        "config_path": config,
        "config": active_config,
        "inventory": actual,
        "inventory_sha256": inventory_digest(actual),
        "service_label": service_label,
        "deadline_only": deadline_only,
    }


def _copy_stage_overlay(
    *, source_root: Path, candidate_app: Path, baseline_app: Path,
    overlay_paths: Sequence[str], active_config: Mapping[str, Any],
) -> tuple[list[dict[str, object]], set[str]]:
    records: list[dict[str, object]] = []
    changed_paths: set[str] = set()
    for raw_relative in overlay_paths:
        relative = _normalise_relative(raw_relative)
        source = source_root / relative
        target = candidate_app / relative
        base = baseline_app / relative
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"Stage overlay source must be a regular file: {relative}")
        source_sha = sha256_file(source)
        baseline_sha = sha256_file(base) if base.is_file() and not base.is_symlink() else None
        if base.is_symlink():
            raise ValueError(f"Stage overlay cannot replace an active-release symlink: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative == "stage_center_tick_config.json":
            source_config = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(source_config, dict):
                raise ValueError("Stage source config must be a JSON object")
            candidate_config = _merge_active_stage_config(source_config, active_config)
            _json_dump(target, candidate_config)
            result_sha = sha256_file(target)
            action = "MERGE_CURRENT_STAGE_CONFIG_WITH_ACTIVE_D1_ROOT"
        elif baseline_sha == source_sha:
            result_sha = baseline_sha
            action = "ACTIVE_BASELINE_BYTES_ALREADY_MATCH_SOURCE"
        else:
            _copy_one(source, target)
            result_sha = sha256_file(target)
            action = "OVERLAY_EXPLICIT_STAGE_SOURCE_DEPENDENCY"
        if result_sha != source_sha and relative != "stage_center_tick_config.json":
            raise ValueError(f"Stage overlay copy SHA mismatch: {relative}")
        if result_sha != baseline_sha:
            changed_paths.add(relative)
        records.append({
            "path": relative,
            "active_baseline_sha256": baseline_sha,
            "source_workspace_sha256": source_sha,
            "candidate_sha256": result_sha,
            "action": action,
        })
    return records, changed_paths


def _git_tracked_modes(source_root: Path) -> dict[str, str]:
    output = _run_git(source_root, "ls-files", "--stage", "-z", binary=True)
    assert isinstance(output, bytes)
    result: dict[str, str] = {}
    for entry in output.split(b"\0"):
        if not entry:
            continue
        metadata, separator, raw_path = entry.partition(b"\t")
        if not separator:
            continue
        mode = metadata.split(b" ", 1)[0].decode("ascii")
        result[_normalise_relative(raw_path.decode("utf-8"))] = mode
    return result


def _copy_stage_source_tree(
    source_root: Path,
    candidate_app: Path,
    tracked_paths: Sequence[str],
) -> list[dict[str, str]]:
    """Copy current tracked files while preserving visible deletions.

    The current checkout has a tracked absolute symlink at
    ``upstreams/review_core`` removed and a physical directory at that path.
    That replacement is not silently folded into a release.  It is recorded
    as an unresolved external owner path for this Stage batch.
    """
    modes = _git_tracked_modes(source_root)
    omitted: list[dict[str, str]] = []
    for relative in tracked_paths:
        source = source_root / relative
        mode = modes.get(relative, "")
        if source.is_dir() and mode == "120000":
            omitted.append({
                "path": relative,
                "reason": "tracked symlink is absent from working tree; untracked directory replacement excluded",
            })
            continue
        if not source.exists() and not source.is_symlink():
            omitted.append({"path": relative, "reason": "tracked path deleted in working tree"})
            continue
        if source.is_dir():
            raise ValueError(f"tracked file path became a directory: {source}")
        _copy_one(source, candidate_app / relative)
    return omitted


def _probe_stage_runtime(python: Path) -> dict[str, object]:
    """Read the selected interpreter and required Stage package versions."""
    if not python.is_file():
        return {"status": "CANNOT_CONFIRM", "python": str(python), "error": "INTERPRETER_MISSING"}
    code = (
        "import importlib.metadata as m, importlib.util, json, sys\n"
        f"names = {list(STAGE_DISTRIBUTIONS)!r}\n"
        "packages = {}\n"
        "for name in names:\n"
        " try: packages[name] = m.version(name)\n"
        " except m.PackageNotFoundError: packages[name] = None\n"
        "modules = {name: bool(importlib.util.find_spec(name)) for name in ('futu','pytdx','pandas','pyarrow','numpy')}\n"
        "print(json.dumps({'python': sys.version, 'executable': sys.executable, 'packages': packages, 'modules': modules}, sort_keys=True))\n"
    )
    try:
        result = subprocess.run(
            [str(python), "-B", "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=15,
        )
        observed = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"status": "CANNOT_CONFIRM", "python": str(python), "error": f"{type(exc).__name__}: {exc}"}
    missing = [name for name, version in observed["packages"].items() if version is None]
    return {
        "status": "OBSERVED_RESOLVED" if not missing else "OBSERVED_MISSING_PACKAGES",
        **observed,
        "missing_distributions": missing,
        "pip_available": _runtime_has_pip(python),
        "inventory_scope": "required Stage SDK and dataframe packages only; not a lockfile",
    }


def _deployed_stage_config_evidence(stage_plist_path: Path) -> dict[str, object]:
    """Read the active plist's referenced config to retain source/release deltas."""
    try:
        payload = _load_plist(stage_plist_path)
        arguments = payload.get("ProgramArguments")
        if (not isinstance(arguments, list) or len(arguments) not in (5, 6)
                or (len(arguments) == 6 and arguments[5] != "--deadline-only")):
            return {"status": "CANNOT_CONFIRM", "reason": "STAGE_PLIST_ARGUMENTS_INVALID"}
        config_path = Path(str(arguments[4])).expanduser()
        if not config_path.is_file():
            return {"status": "CANNOT_CONFIRM", "path": str(config_path), "reason": "DEPLOYED_STAGE_CONFIG_MISSING"}
        config_data = json.loads(config_path.read_text())
        if not isinstance(config_data, dict):
            return {"status": "CANNOT_CONFIRM", "path": str(config_path), "reason": "DEPLOYED_STAGE_CONFIG_NOT_OBJECT"}
        keys = (*STAGE_DATA_PATH_KEYS, "shared_data_root", "python_path", "release_id")
        return {
            "status": "READ_ONLY_REFERENCE_CAPTURED",
            "path": str(config_path),
            "sha256": sha256_file(config_path),
            "values": {key: config_data[key] for key in keys if key in config_data},
        }
    except (OSError, ValueError, plistlib.InvalidFileException, json.JSONDecodeError) as exc:
        return {"status": "CANNOT_CONFIRM", "reason": f"{type(exc).__name__}: {exc}"}


def _runtime_has_pip(python: Path) -> bool:
    try:
        result = subprocess.run(
            [str(python), "-B", "-c", "import pip; print(pip.__version__)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(result.stdout.strip())


def _render_stage_service_binding(
    *,
    source_plist: Path,
    candidate_root: Path,
    release_id: str,
    manifest_path: Path,
    manifest_sha256: str,
    runtime_python: Path,
    source_runtime_python: Path | None = None,
    service_label: str = STAGE_SERVICE_LABEL,
    deadline_only: bool = False,
) -> dict[str, object]:
    """Write an inactive Stage LaunchAgent bound to its explicit interpreter."""
    payload = _load_plist(source_plist)
    if (service_label not in STAGE_SERVICE_LABELS or payload.get("Label") != service_label
            or deadline_only != (service_label == STAGE_DEADLINE_SERVICE_LABEL)):
        raise ValueError("Stage source LaunchAgent label mismatch")
    original_args = payload.get("ProgramArguments")
    expected_argument_count = 6 if deadline_only else 5
    if (not isinstance(original_args, list) or len(original_args) != expected_argument_count
            or original_args[1] != "-B"
            or original_args[3:4] != ["--config"]
            or Path(str(original_args[2])).name != "run_stage_center_nodes.py"
            or Path(str(original_args[4])).name != "stage_center_tick_config.json"
            or (deadline_only and original_args[5] != "--deadline-only")):
        raise ValueError("Stage source LaunchAgent entrypoint/config binding mismatch")
    env = payload.get("EnvironmentVariables")
    if not isinstance(env, dict):
        raise ValueError("Stage source LaunchAgent EnvironmentVariables is required")
    for key in ("NODE_CALENDAR_WAIT_MAX_SECONDS", "NODE_MAX_ATTEMPTS", "NODE_RETRY_BACKOFF_SECONDS"):
        if str(env.get(key, "")) == "":
            raise ValueError(f"Stage source LaunchAgent is missing frozen control: {key}")
    if str(env["NODE_CALENDAR_WAIT_MAX_SECONDS"]) != "5":
        raise ValueError("Stage calendar wait must remain at the frozen 5-second setting")
    for key in ("PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT",
                "production_allowed", "buy_gate_updated", "orders_sent"):
        if key in env and str(env[key]).lower() not in {"false", "0"}:
            raise ValueError(f"unsafe Stage source LaunchAgent environment: {key}")

    app = candidate_root / "app"
    stage_script = app / "ops/run_stage_center_nodes.py"
    stage_config = app / "stage_center_tick_config.json"
    shared_package = app / "upstreams/v3_shared_data"
    if not stage_script.is_file() or not stage_config.is_file() or not shared_package.is_dir():
        raise FileNotFoundError("candidate Stage source closure is incomplete")

    config_data = json.loads(stage_config.read_text())
    if not isinstance(config_data, dict):
        raise ValueError("Stage config must contain a JSON object")
    if not isinstance(config_data.get("preselection_source_root"), str) or not config_data["preselection_source_root"].strip():
        raise ValueError("Stage config must preserve preselection_source_root")
    if config_data.get("node_calendar_wait_max_seconds") != 5:
        raise ValueError("Stage config calendar wait must remain at the frozen 5-second setting")
    if config_data.get("node_max_attempts") != 3 or config_data.get("node_retry_backoff_seconds") != 60:
        raise ValueError("Stage retry controls differ from the frozen source values")
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if config_data.get("safety", {}).get(key) is not False:
            raise ValueError(f"Stage config safety flag must remain false: {key}")

    source_python = source_runtime_python or Path(str(config_data.get("python_path", "")))
    runtime_python = _absolute_preserving_symlink(runtime_python)
    if not runtime_python.is_absolute():
        raise ValueError("Stage runtime interpreter must be an absolute path")
    config_data["release_id"] = release_id
    config_data["python_path"] = str(runtime_python)
    # shared_data_root names the packaged bridge code; data roots stay exactly
    # as supplied by the current source config for owner-aware follow-up.
    config_data["shared_data_root"] = str(shared_package)
    stage_config.write_text(json.dumps(config_data, ensure_ascii=False, indent=2) + "\n")

    staged = deepcopy(payload)
    new_env = staged["EnvironmentVariables"]
    new_env.update({
        "PYTHONPATH": str(app / "upstreams") + ":" + str(app),
        "STAGE_CENTER_CONFIG": str(stage_config),
        "V35_RELEASE_ID": release_id,
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha256,
        "REVIEW_CORE_PACKAGE_ROOT": str(app / "upstreams"),
        "V35_REVIEW_CORE_PACKAGE_ROOT": str(app / "upstreams"),
        "V4_STAGE_DEADLINE_POLICY": "observe",
    })
    staged["ProgramArguments"] = [
        str(runtime_python), "-B", str(stage_script), "--config", str(stage_config)
    ]
    if deadline_only:
        staged["ProgramArguments"].append("--deadline-only")
    staged["WorkingDirectory"] = str(app)
    target = candidate_root / "config" / f"{service_label}.plist"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(plistlib.dumps(staged, fmt=plistlib.FMT_XML, sort_keys=True))
    return {
        "label": service_label,
        "path": str(target),
        "sha256": sha256_file(target),
        "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False,
        "config_path": str(stage_config),
        "config_sha256": sha256_file(stage_config),
        "runtime_python": str(runtime_python),
        "source_runtime_python": str(source_python),
        "calendar_wait_seconds": 5,
        "deadline_policy": "observe",
        "deadline_only": deadline_only,
        "source_config_roots_preserved": {
            key: value for key, value in config_data.items() if key in STAGE_DATA_PATH_KEYS
        },
        "shared_data_root_rebased_to_candidate_package": str(shared_package),
    }


def build_stage_service_candidate(
    *,
    source_root: Path,
    candidate_root: Path,
    stage_plist_path: Path,
    runtime_python: Path | None = None,
    release_id: str,
    formal_release_root: Path = DEFAULT_FORMAL_RELEASE_ROOT,
    receipt_path: Path | None = None,
    baseline_release_root: Path | None = None,
    overlay_paths: Sequence[str | Path] | None = None,
) -> dict[str, object]:
    """Build Stage from the complete active release plus an explicit overlay.

    The dirty V4 workspace is only read for the allow-listed Stage source
    paths. Its other tracked or untracked bytes never enter the candidate.
    """
    source_root = _resolved(source_root)
    stage_plist_path = _resolved(stage_plist_path)
    candidate_root = _guard_candidate_root(
        candidate_root, source_root=source_root, formal_release_root=formal_release_root
    )
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    if not stage_plist_path.is_file():
        raise FileNotFoundError(stage_plist_path)
    if receipt_path is None:
        receipt_path = candidate_root.parent / f"{candidate_root.name}-stage-build-receipt.json"
    receipt_path = _resolved(receipt_path)
    if _is_within(receipt_path, source_root) or _is_within(receipt_path, formal_release_root):
        raise ValueError("Stage build receipt must be outside source and formal release roots")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError(f"refusing to overwrite Stage build receipt: {receipt_path}")

    automatic_overlay = overlay_paths is None
    if automatic_overlay:
        overlay_relatives: tuple[str, ...] = ()
    else:
        overlay_relatives = tuple(_normalise_relative(str(path)) for path in overlay_paths)
        if len(set(overlay_relatives)) != len(overlay_relatives):
            raise ValueError("duplicate Stage overlay path")
        allowed = set(STAGE_SERVICE_OVERLAY_PATHS)
        if not set(overlay_relatives).issubset(allowed):
            raise ValueError("Stage overlay path is outside the reviewed allowlist")

    active = _active_stage_release(stage_plist_path, baseline_release_root)
    active_config = active["config"]
    if automatic_overlay:
        effective_config = _effective_stage_config(
            source_root=source_root,
            overlay_paths=LEGACY_STAGE_SERVICE_OVERLAY_PATHS,
            active_config=active_config,
        )
        overlay_relatives = (
            STAGE_SERVICE_OVERLAY_PATHS
            if effective_config.get("publication_mode") == "strict_commit_required"
            else LEGACY_STAGE_SERVICE_OVERLAY_PATHS
        )
    else:
        effective_config = _effective_stage_config(
            source_root=source_root,
            overlay_paths=overlay_relatives,
            active_config=active_config,
        )
    require_complete_strict_stage_overlay(
        source_root=source_root,
        overlay_paths=overlay_relatives,
        effective_config=effective_config,
    )
    require_stage_overlay_source_hashes(
        source_root=source_root,
        overlay_paths=overlay_relatives,
    )
    baseline_app = Path(active["app_root"])
    baseline_inventory = list(active["inventory"])
    base_manifest = active["manifest"]
    candidate_root.mkdir()
    marker = candidate_root / ".candidate-build-in-progress"
    marker.write_text(f"created_at={utc_now()}\n")
    try:
        candidate_app = candidate_root / "app"
        shutil.copytree(baseline_app, candidate_app, symlinks=True)
        copied_inventory = inventory_tree(candidate_app)
        if copied_inventory != baseline_inventory:
            raise ValueError("Stage active baseline copy changed before overlay")

        overlay_records, changed_paths = _copy_stage_overlay(
            source_root=source_root,
            candidate_app=candidate_app,
            baseline_app=baseline_app,
            overlay_paths=overlay_relatives,
            active_config=active_config,
        )
        config_path = candidate_app / "stage_center_tick_config.json"
        if not config_path.is_file():
            raise FileNotFoundError(config_path)
        config_data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config_data, dict) or not config_data.get("preselection_source_root"):
            raise ValueError("Stage candidate config must preserve preselection_source_root")
        selected_python = runtime_python or Path(str(config_data.get("python_path", "")))
        source_python = Path(str(config_data.get("python_path", "")))
        source_data_paths = {
            key: config_data.get(key) for key in STAGE_DATA_PATH_KEYS if key in config_data
        }
        source_config_identity = {
            "release_id": config_data.get("release_id"),
            "shared_data_root": config_data.get("shared_data_root"),
            "python_path": str(source_python),
        }
        selected_python = _absolute_preserving_symlink(selected_python)
        candidate_shared_package = candidate_app / "upstreams/v3_shared_data"
        if not candidate_shared_package.is_dir():
            raise FileNotFoundError(candidate_shared_package)
        config_data["release_id"] = release_id
        config_data["python_path"] = str(selected_python)
        config_data["shared_data_root"] = str(candidate_shared_package)
        config_path.write_text(json.dumps(config_data, ensure_ascii=False, indent=2) + "\n")
        changed_paths.add("stage_center_tick_config.json")

        runtime = _probe_stage_runtime(selected_python)
        if runtime.get("status") != "OBSERVED_RESOLVED":
            # Keep the candidate inspectable, but never claim that its selected
            # service interpreter is available when package probing fails.
            raise ValueError(f"Stage bound runtime probe failed: {runtime.get('status')}")
        app_inventory = inventory_tree(candidate_app)
        baseline_by_path = {str(row["path"]): row for row in baseline_inventory}
        candidate_by_path = {str(row["path"]): row for row in app_inventory}
        allowed_changed = set(changed_paths)
        removed = sorted(set(baseline_by_path) - set(candidate_by_path) - allowed_changed)
        added = sorted(set(candidate_by_path) - set(baseline_by_path) - allowed_changed)
        altered = sorted(
            path for path in set(baseline_by_path) & set(candidate_by_path)
            if path not in allowed_changed and baseline_by_path[path] != candidate_by_path[path]
        )
        if removed or added or altered:
            raise ValueError(f"Stage overlay changed bytes outside its allowlist: removed={removed} added={added} altered={altered}")
        preserved_paths = sorted(path for path in baseline_by_path if path not in allowed_changed)
        preserved_entries = [baseline_by_path[path] for path in preserved_paths]
        candidate_preserved_entries = [candidate_by_path[path] for path in preserved_paths]
        if preserved_entries != candidate_preserved_entries:
            raise ValueError("Stage active release non-overlay byte preservation check failed")

        commit = str(_run_git(source_root, "rev-parse", "HEAD")).strip()
        overlay_manifest = {
            "active_release_id": active["identity"]["release_id"],
            "active_release_manifest_sha256": active["manifest_sha256"],
            "active_application_inventory_sha256": base_manifest["application_inventory"]["aggregate_sha256"],
            "source_workspace_commit": commit,
            "workspace_full_tree_copied": False,
            "non_overlay_active_release_bytes_preserved": True,
            "non_overlay_path_count": len(preserved_paths),
            "non_overlay_inventory_sha256": inventory_digest(preserved_entries),
            "allowlist": list(overlay_relatives),
            "entries": overlay_records,
        }
        overlay_manifest_sha = hashlib.sha256(
            json.dumps(overlay_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        data_paths = {
            key: config_data.get(key) for key in STAGE_DATA_PATH_KEYS if key in config_data
        }
        manifest: dict[str, object] = {
            "schema_version": "v4.stage_service_candidate.v2",
            "generated_at": utc_now(),
            "candidate_status": "READY_FOR_REVIEW_WITH_GAPS",
            "activation_status": "NOT_ACTIVATED",
            "deployment_status": "CANNOT_CONFIRM",
            "source": {
                "root": str(source_root),
                "integration_base": {
                    "release_root": str(active["release_root"]),
                    "app_root": str(baseline_app),
                    "release_id": active["identity"]["release_id"],
                    "release_manifest_sha256": active["manifest_sha256"],
                    "application_inventory_sha256": base_manifest["application_inventory"]["aggregate_sha256"],
                },
                "stage_overlay": overlay_manifest,
                "stage_overlay_manifest_sha256": overlay_manifest_sha,
            },
            "candidate": {
                "root": str(candidate_root),
                "app_root": str(candidate_app),
                "release_id": release_id,
                "formal_release_root": str(_resolved(formal_release_root)),
                "overwrite_policy": "refuse an existing path; offline evidence only",
                "data_copy_performed": False,
                "service_activated": False,
                "formal_release_written": False,
            },
            "application_inventory": {
                "entry_count": len(app_inventory),
                "aggregate_sha256": inventory_digest(app_inventory),
                "entries": app_inventory,
            },
            "stage_service": {
                "label": active["service_label"],
                "deadline_only": active["deadline_only"],
                "entrypoint": "ops/run_stage_center_nodes.py",
                "config": "stage_center_tick_config.json",
                "runtime_binding": str(selected_python),
                "current_source_config_identity": source_config_identity,
                "runtime_observation": runtime,
                "python_package_manifest": {
                    "status": "CANNOT_CONFIRM",
                    "reason": "The current 3.14.6 environment has no pip and no formal lockfile/wheelhouse; observed versions are not a reproducible build lock.",
                },
            },
            "data_paths": {
                "external_roots": data_paths,
                "current_source_config_roots": source_data_paths,
                "active_release_config_roots": {
                    key: active_config[key] for key in STAGE_DATA_PATH_KEYS if key in active_config
                },
                "deployed_release_reference": _deployed_stage_config_evidence(stage_plist_path),
                "data_copy_performed": False,
                "data_roots_rebased": False,
                "owner_review": "PENDING_DATA_CONTRACT_RECEIPT",
                "v35_roots_preserved": [
                    key for key in ("v4_research_data_root", "preselection_source_root")
                    if key in data_paths and str(data_paths[key]).startswith("/REDACTED_LOCAL_HOME/Library/Application Support/com.lexi.v35.local/")
                ],
            },
            "frozen_controls": {
                "calendar_wait_seconds": 5,
                "node_max_attempts": config_data.get("node_max_attempts"),
                "retry_backoff_seconds": config_data.get("node_retry_backoff_seconds"),
                "deadline_policy": "observe",
                "strict_5_second_chain_acceptance": "CANNOT_CONFIRM",
                "natural_stage_behavior": "CANNOT_CONFIRM",
            },
            "verification_gaps": [
                "strict end-to-end 5-second production timing has not been independently proven",
                "natural Stage schedule/readback is not verified by an offline source candidate",
                "runtime package versions lack a formal lockfile and rebuildable wheelhouse",
                "V35 preselection/research roots require per-collection owner and conflict review before data cutover",
                "the active release baseline includes external shared package links whose replacement owner remains unresolved",
            ],
        }
        manifest_path = candidate_root / "release-manifest.json"
        _json_dump(manifest_path, manifest)
        manifest_sha = sha256_file(manifest_path)
        service_binding = _render_stage_service_binding(
            source_plist=stage_plist_path,
            candidate_root=candidate_root,
            release_id=release_id,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha,
            runtime_python=selected_python,
            source_runtime_python=source_python,
            service_label=str(active["service_label"]),
            deadline_only=bool(active["deadline_only"]),
        )
        final_inventory = inventory_tree(candidate_app)
        if final_inventory != app_inventory:
            raise ValueError("Stage binding renderer changed files outside the generated config")
        marker.unlink()
        receipt = {
            "schema_version": "v4.stage_service_candidate_receipt.v2",
            "generated_at": utc_now(),
            "candidate_status": manifest["candidate_status"],
            "activation_status": "NOT_ACTIVATED",
            "deployment_status": "CANNOT_CONFIRM",
            "candidate_root": str(candidate_root),
            "baseline_release_root": str(active["release_root"]),
            "baseline_release_manifest_sha256": active["manifest_sha256"],
            "manifest_path": str(manifest_path),
            "manifest_sha256": manifest_sha,
            "application_inventory_sha256": inventory_digest(final_inventory),
            "stage_overlay_manifest_sha256": overlay_manifest_sha,
            "service_binding": service_binding,
            "source_commit": commit,
            "stage_overlay_paths": list(overlay_relatives),
            "guard": "Offline Stage candidate from verified active-release baseline plus explicit Stage overlays; no launchd, formal release, or data root was changed.",
        }
        _json_dump(receipt_path, receipt)
        receipt["receipt_path"] = str(receipt_path)
        return receipt
    except Exception:
        raise
