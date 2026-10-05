#!/usr/bin/env python3
"""Build a reproducible, inactive release candidate for the canonical 8873 app.

The builder copies the Git-tracked v4_app tree and the currently present
``apps/web/dist`` tree into a *new* directory below an evidence root.  It
records source identity, working-tree deltas, dependency observations,
LaunchAgent differences, and a staged api-only rollback plan.  It never
publishes to ``~/Library/.../releases``, changes a plist, calls ``launchctl``,
or copies runtime data.
"""

from __future__ import annotations

import argparse
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

try:  # Running as ``python ops/build_release_candidate.py``.
    from prepare_api_only_cutover import (
        DEFAULT_FORMAL_RELEASE_ROOT,
        DEFAULT_MANAGER_STATE_ROOT,
        describe_preserved_environment,
        render_cutover,
        sha256_file,
    )
except ImportError:  # Imported as ``ops.build_release_candidate`` in tests.
    try:
        from .prepare_api_only_cutover import (
            DEFAULT_FORMAL_RELEASE_ROOT,
            DEFAULT_MANAGER_STATE_ROOT,
            describe_preserved_environment,
            render_cutover,
            sha256_file,
        )
    except ImportError:  # Loaded directly with importlib in a focused test.
        import importlib.util

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
        render_cutover = _helper.render_cutover
        sha256_file = _helper.sha256_file


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


def _is_within(path: Path, root: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(root))
    except ValueError:
        return False
    return True


def _normalise_relative(path: str | Path) -> str:
    value = Path(path).as_posix()
    if Path(value).is_absolute() or not value or value in {".", ".."} or ".." in Path(value).parts:
        raise ValueError(f"unsafe relative path: {path}")
    return value


def _run_git(source_root: Path, *args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=source_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
    )
    return result.stdout


def _git_tracked_paths(source_root: Path) -> list[str]:
    output = _run_git(source_root, "ls-files", "--cached", "-z", binary=True)
    assert isinstance(output, bytes)
    return sorted(
        _normalise_relative(item.decode("utf-8"))
        for item in output.split(b"\0")
        if item
    )


def _git_untracked_paths(source_root: Path) -> list[str]:
    output = _run_git(
        source_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        binary=True,
    )
    assert isinstance(output, bytes)
    return sorted(
        _normalise_relative(item.decode("utf-8"))
        for item in output.split(b"\0")
        if item
    )


def _validate_explicit_untracked_paths(
    source_root: Path,
    requested_paths: Sequence[str | Path],
    *,
    tracked_paths: Sequence[str],
    untracked_paths: Sequence[str],
) -> list[str]:
    """Validate the bounded untracked include list before copying anything."""

    normalised = [_normalise_relative(path) for path in requested_paths]
    if len(normalised) != len(set(normalised)):
        raise ValueError("explicit untracked include paths must be unique")
    tracked = set(tracked_paths)
    tracked_overlap = sorted(set(normalised) & tracked)
    if tracked_overlap:
        raise ValueError(
            "explicit untracked include path(s) are already tracked: "
            + ", ".join(tracked_overlap)
        )
    untracked = set(untracked_paths)
    missing = sorted(set(normalised) - untracked)
    if missing:
        raise FileNotFoundError(
            "approved explicit untracked include path(s) are not current untracked files: "
            + ", ".join(missing)
        )
    for relative in normalised:
        source = source_root / relative
        if any((source_root / Path(relative).parents[i]).is_symlink()
               for i in range(len(Path(relative).parents) - 1)) or source.is_symlink() or not source.is_file():
            raise ValueError(
                f"approved explicit untracked include must be a regular file: {source}"
            )
    return sorted(normalised)


def _explicit_include_provenance(paths: Sequence[str]) -> list[dict[str, object]]:
    return [
        {"path": path, "approval": "CALLER_EXPLICIT_REVIEWED_PATH",
         **dict(APPROVED_UNTRACKED_CANDIDATE_PATHS.get(path, {}))}
        for path in paths
    ]


def copy_explicit_untracked_tree(
    source_root: Path, candidate_app: Path, relative_paths: Sequence[str]
) -> None:
    for relative in relative_paths:
        _copy_one(source_root / relative, candidate_app / relative)


def git_snapshot(
    source_root: Path,
    *,
    include_untracked_hashes: bool = True,
    included_untracked_paths: Sequence[str] = (),
) -> dict[str, object]:
    """Capture Git identity and a bounded working-tree summary without writes."""

    source_root = _resolved(source_root)
    diff = _run_git(source_root, "diff", "--no-ext-diff", "--binary", "--", binary=True)
    assert isinstance(diff, bytes)
    status = _run_git(
        source_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    diff_stat = _run_git(source_root, "diff", "--stat", "--no-ext-diff", "--")
    assert isinstance(status, str) and isinstance(diff_stat, str)
    untracked = _git_untracked_paths(source_root)
    untracked_entries: list[dict[str, object]] = []
    if include_untracked_hashes:
        for relative in untracked:
            path = source_root / relative
            if path.is_symlink():
                untracked_entries.append(
                    {
                        "path": relative,
                        "kind": "symlink",
                        "target": os.readlink(path),
                        "target_exists": path.exists(),
                    }
                )
            elif path.is_file():
                untracked_entries.append(
                    {"path": relative, "kind": "file", "sha256": sha256_file(path)}
                )
            else:
                untracked_entries.append({"path": relative, "kind": "other"})
    included = sorted(_normalise_relative(path) for path in included_untracked_paths)
    if included:
        copy_policy = (
            "Git-tracked paths plus explicit approved untracked paths "
            + ", ".join(included)
            + " and current apps/web/dist; all other untracked files are recorded but not copied into app."
        )
    else:
        copy_policy = (
            "Git-tracked paths plus explicit current apps/web/dist; untracked operational helpers "
            "are recorded but not copied into app."
        )
    return {
        "repository": str(_run_git(source_root, "rev-parse", "--show-toplevel")).strip(),
        "commit": str(_run_git(source_root, "rev-parse", "HEAD")).strip(),
        "tree": str(_run_git(source_root, "rev-parse", "HEAD^{tree}")).strip(),
        "branch": str(_run_git(source_root, "branch", "--show-current")).strip(),
        "tracked_status_porcelain": status,
        "tracked_diff_stat": diff_stat,
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "tracked_diff_bytes": len(diff),
        "untracked_count": len(untracked),
        "untracked_files": untracked_entries,
        "included_untracked_paths": included,
        "candidate_copy_policy": copy_policy,
    }


def snapshot_legacy_git(repo: Path, evidence_root: Path) -> dict[str, object]:
    """Save only tracked status/diff for the legacy repo.

    ``--untracked-files=no`` and ``git diff`` intentionally avoid walking or
    copying the legacy repository's potentially large untracked tree.
    """

    repo = _resolved(repo)
    evidence_root = _resolved(evidence_root)
    if _is_within(evidence_root, repo) or _is_within(repo, evidence_root):
        raise ValueError("legacy Git evidence must be outside the legacy checkout")
    evidence_root.mkdir(parents=True, exist_ok=True)
    status = _run_git(repo, "status", "--porcelain=v1", "--untracked-files=no")
    diff = _run_git(repo, "diff", "--no-ext-diff", "--binary", "--", binary=True)
    diff_stat = _run_git(repo, "diff", "--stat", "--no-ext-diff", "--")
    assert isinstance(status, str) and isinstance(diff, bytes) and isinstance(diff_stat, str)
    (evidence_root / "git-status-tracked-only.txt").write_text(status)
    (evidence_root / "git-diff.patch").write_bytes(diff)
    (evidence_root / "git-diff-stat.txt").write_text(diff_stat)
    receipt = {
        "schema_version": "v4.legacy_v35_git_snapshot.v1",
        "generated_at": utc_now(),
        "repository": str(_run_git(repo, "rev-parse", "--show-toplevel")).strip(),
        "commit": str(_run_git(repo, "rev-parse", "HEAD")).strip(),
        "branch": str(_run_git(repo, "branch", "--show-current")).strip(),
        "status_path": str(evidence_root / "git-status-tracked-only.txt"),
        "diff_path": str(evidence_root / "git-diff.patch"),
        "diff_stat_path": str(evidence_root / "git-diff-stat.txt"),
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "tracked_diff_bytes": len(diff),
        "untracked_tree_scanned": False,
        "untracked_tree_copied": False,
        "scope": "tracked status and tracked diff only; legacy checkout left in place",
    }
    _json_dump(evidence_root / "snapshot-receipt.json", receipt)
    return receipt


def _entry_for_path(root: Path, relative: str) -> dict[str, object]:
    relative = _normalise_relative(relative)
    path = root / relative
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return {
            "path": relative,
            "kind": "symlink",
            "target": os.readlink(path),
            "target_exists": path.exists(),
        }
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"unsupported file type in candidate scope: {path}")
    return {
        "path": relative,
        "kind": "file",
        "sha256": sha256_file(path),
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "size": info.st_size,
    }


def _walk_entries(root: Path) -> list[str]:
    if not root.exists() and not root.is_symlink():
        return []
    if root.is_symlink() or root.is_file():
        return [""]
    result: list[str] = []
    for directory, directories, filenames in os.walk(root, followlinks=False):
        directories.sort()
        filenames.sort()
        safe_directories: list[str] = []
        for name in directories:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                result.append(relative)
            else:
                safe_directories.append(name)
        directories[:] = safe_directories
        for name in filenames:
            result.append((Path(directory) / name).relative_to(root).as_posix())
    return sorted(result)


def _copy_one(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
        return
    if not source.is_file():
        raise ValueError(f"source entry is not a regular file or symlink: {source}")
    shutil.copy2(source, destination, follow_symlinks=False)


def copy_tracked_tree(source_root: Path, candidate_app: Path, tracked_paths: Sequence[str]) -> None:
    for relative in tracked_paths:
        source = source_root / relative
        _copy_one(source, candidate_app / relative)


def copy_dist(source_root: Path, candidate_app: Path) -> None:
    source_dist = source_root / DIST_RELATIVE_ROOT
    if not source_dist.is_dir():
        raise FileNotFoundError(f"required current frontend dist is missing: {source_dist}")
    entries = _walk_entries(source_dist)
    if not entries:
        raise FileNotFoundError(f"required current frontend dist is empty: {source_dist}")
    destination_dist = candidate_app / DIST_RELATIVE_ROOT
    for relative in entries:
        _copy_one(source_dist / relative, destination_dist / relative)


def inventory_tree(root: Path) -> list[dict[str, object]]:
    return [_entry_for_path(root, relative) for relative in _walk_entries(root)]


def inventory_digest(entries: Sequence[Mapping[str, object]]) -> str:
    canonical = json.dumps(list(entries), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _describe_path(value: str) -> dict[str, object] | None:
    if not (value.startswith("/") or value.startswith("~")):
        return None
    path = Path(value).expanduser()
    result: dict[str, object] = {
        "path": value,
        "exists": path.exists() or path.is_symlink(),
        "is_symlink": path.is_symlink(),
        "resolved_target": str(_resolved(path)),
    }
    if path.is_symlink():
        result["link_target"] = os.readlink(path)
    resolved = _resolved(path)
    result["resolved_exists"] = resolved.exists()
    if resolved.is_file():
        result["kind"] = "file"
        result["code_sha256"] = sha256_file(resolved)
    elif resolved.is_dir():
        result["kind"] = "directory"
    else:
        result["kind"] = "missing"
    return result


def _describe_scheduler_path_value(value: str) -> object:
    if ":" in value and value.startswith("/"):
        return {
            "value": value,
            "segments": [_describe_path(segment) for segment in value.split(":")],
        }
    return _describe_path(value) or {"value": value}


def _file_summary(path: Path) -> dict[str, object]:
    result: dict[str, object] = {"path": str(path), "exists": path.exists() or path.is_symlink()}
    if path.is_symlink():
        result.update(
            {
                "kind": "symlink",
                "target": os.readlink(path),
                "target_exists": path.exists(),
                "resolved_target": str(_resolved(path)),
            }
        )
    elif path.is_file():
        result.update({"kind": "file", "sha256": sha256_file(path)})
    elif path.is_dir():
        result["kind"] = "directory"
    else:
        result["kind"] = "missing"
    return result


def _load_plist(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        value = plistlib.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"plist root must be a dictionary: {path}")
    return value


def _plist_environment(plist: Mapping[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    arguments = plist.get("ProgramArguments", [])
    if isinstance(arguments, list):
        for item in arguments:
            if isinstance(item, str) and "=" in item:
                key, value = item.split("=", 1)
                if key and key.replace("_", "").isalnum():
                    values[key] = value
    raw = plist.get("EnvironmentVariables", {})
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                values[key] = str(value)
    return values


def audit_scheduler(
    *,
    source_root: Path,
    scheduler_plist_path: Path,
) -> dict[str, object]:
    """Compare the current scheduler binding with v4 entrypoint dependencies."""

    scheduler_plist_path = _resolved(scheduler_plist_path)
    plist = _load_plist(scheduler_plist_path)
    environment = _plist_environment(plist)
    arguments = plist.get("ProgramArguments", [])
    current_script = ""
    if isinstance(arguments, list):
        for item in arguments:
            if isinstance(item, str) and item.endswith(".sh"):
                current_script = item
                break
    current_app_root = Path(environment["V35_APP_ROOT"]) if environment.get("V35_APP_ROOT") else (
        Path(current_script).parent.parent if current_script else Path("/")
    )
    current_app_root = _resolved(current_app_root)
    source_root = _resolved(source_root)
    relative_files = (
        "ops/launch_v35_macos_scheduler.sh",
        "ops/run_v35_macos_scheduler.py",
        "ops/run_scheduled_slot.py",
        "ops/collect_runtime_graph.py",
        "contracts/runtime_workloads.json",
        "ops/launch_hk_0_2_python_nosite.sh",
    )
    comparisons: list[dict[str, object]] = []
    for relative in relative_files:
        source = source_root / relative
        current = current_app_root / relative
        source_summary = _file_summary(source)
        current_summary = _file_summary(current)
        same = bool(
            source_summary.get("exists")
            and current_summary.get("exists")
            and source_summary.get("kind") == current_summary.get("kind")
            and (
                source_summary.get("sha256") == current_summary.get("sha256")
                if source_summary.get("kind") == "file"
                else source_summary.get("target") == current_summary.get("target")
            )
        )
        comparisons.append(
            {
                "relative_path": relative,
                "source": source_summary,
                "current_release": current_summary,
                "same_bytes_or_link": same,
            }
        )

    path_bindings: dict[str, object] = {}
    for key in sorted(environment):
        value = environment[key]
        if key in SAFETY_KEYS:
            path_bindings[key] = {"value": value}
        elif key.startswith("V35_") or key == "PYTHONPATH":
            path_bindings[key] = _describe_scheduler_path_value(value)
    safety_flags = {key: environment.get(key) for key in SAFETY_KEYS if key in environment}
    safety_ok = bool(safety_flags) and all(
        str(value).lower() in {"false", "0", "no"} for value in safety_flags.values()
    )
    path_probes = [
        value
        for value in path_bindings.values()
        if isinstance(value, Mapping) and "resolved_exists" in value
    ]
    path_ok = all(bool(value.get("resolved_exists")) for value in path_probes)
    mismatches = [item["relative_path"] for item in comparisons if not item["same_bytes_or_link"]]
    # A byte comparison does not prove scheduler semantic parity.  In this
    # milestone the current release retains the background duty; rebind to the
    # v4 checkout remains unconfirmed and is never performed automatically.
    return {
        "schema_version": "v4.scheduler_binding_audit.v1",
        "status": "CANNOT_CONFIRM",
        "current_plist": {"path": str(scheduler_plist_path), "sha256": sha256_file(scheduler_plist_path)},
        "label": plist.get("Label"),
        "current_release_id": environment.get("V35_RELEASE_ID"),
        "current_app_root": str(current_app_root),
        "current_program": current_script,
        "comparisons": comparisons,
        "mismatching_dependencies": mismatches,
        "path_bindings": path_bindings,
        "all_observed_path_bindings_resolve": path_ok,
        "safety_flags": safety_flags,
        "safety_flags_are_research_only": safety_ok,
        "semantic_parity": "CANNOT_CONFIRM",
        "decision": "RETAIN_CURRENT_BINDING_ONLY",
        "rebind_performed": False,
        "conclusion": "Current scheduler release may remain the background owner with its existing roots and safety flags. Rebinding it to v4_app is not confirmed because scheduler entrypoints and workload contracts differ; no scheduler plist or task was changed.",
        "differences": [
            "source and current scheduler launcher/module are not byte-identical",
            "source and current run_scheduled_slot/runtime_workloads are not byte-identical",
            "the current HK 0.2 launcher exists only in the current release while the v4 source path is absent",
            "hash parity cannot establish timing, state-root, or semantic parity",
        ],
    }


def _probe_dependency_process(python: Path, names: Sequence[str]) -> dict[str, object]:
    probe_code = r'''
import importlib.metadata
import importlib.util
import json
import os
import sys

names = json.loads(sys.argv[1])
records = []
for name in names:
    record = {"module": name, "found": False, "origin": None, "version": None}
    try:
        spec = importlib.util.find_spec(name)
    except Exception as exc:
        record["error"] = type(exc).__name__
        spec = None
    if spec is not None:
        record["found"] = True
        record["origin"] = getattr(spec, "origin", None)
    try:
        record["version"] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        record["version"] = None
    except Exception as exc:
        record["version_error"] = type(exc).__name__
    records.append(record)
print(json.dumps({"python": sys.executable, "version": sys.version, "modules": records}, ensure_ascii=False))
'''
    result = subprocess.run(
        [str(python), "-c", probe_code, json.dumps(list(names))],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        return {
            "status": "CANNOT_CONFIRM",
            "interpreter": str(python),
            "returncode": result.returncode,
            "stderr_class": result.stderr.strip().splitlines()[-1][:160] if result.stderr.strip() else "",
            "modules": [],
        }
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "status": "CANNOT_CONFIRM",
            "interpreter": str(python),
            "returncode": result.returncode,
            "stderr_class": "probe output was not JSON",
            "modules": [],
        }
    for record in parsed.get("modules", []):
        origin = record.get("origin")
        if isinstance(origin, str) and origin not in {"built-in", "frozen"}:
            path = Path(origin)
            record["origin_exists"] = path.exists()
            record["origin_resolved"] = str(_resolved(path))
            if path.is_file():
                record["origin_sha256"] = sha256_file(path)
                record["origin_kind"] = "file"
            elif path.is_dir():
                record["origin_kind"] = "directory"
            else:
                record["origin_kind"] = "missing"
    missing = [record.get("module") for record in parsed.get("modules", []) if not record.get("found")]
    parsed["status"] = "OBSERVED_RESOLVED" if not missing else "CANNOT_CONFIRM"
    parsed["missing_modules"] = missing
    parsed["interpreter_observation"] = _file_summary(python)
    parsed["formal_runtime_dependency_inventory"] = {
        "status": "CANNOT_CONFIRM",
        "reason": "No formal runtime dependency inventory was supplied; this is an environment probe only.",
    }
    return parsed


def dependency_probe(python: Path, names: Sequence[str] = DEFAULT_DEPENDENCIES) -> dict[str, object]:
    # Preserve the venv launcher path for subprocess execution.  Resolving a
    # venv symlink first would invoke the base interpreter and silently lose
    # the venv's site-packages, which would make a valid dependency set look
    # missing.
    python = python.expanduser()
    if not python.is_file():
        return {
            "status": "CANNOT_CONFIRM",
            "interpreter": str(python),
            "interpreter_exists": False,
            "modules": [],
            "formal_runtime_dependency_inventory": {
                "status": "CANNOT_CONFIRM",
                "reason": "interpreter path is missing",
            },
        }
    result = _probe_dependency_process(python, names)
    result["interpreter_exists"] = True
    result["interpreter_requested"] = str(python)
    result["interpreter_resolved"] = str(_resolved(python))
    return result


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


def build_candidate(
    *,
    source_root: Path,
    candidate_root: Path,
    api_plist_path: Path,
    scheduler_plist_path: Path,
    python: Path,
    release_id: str,
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
        candidate_app.mkdir()
        tracked_paths = _git_tracked_paths(source_root)
        untracked_paths = _git_untracked_paths(source_root)
        included_untracked_paths = _validate_explicit_untracked_paths(
            source_root,
            include_untracked_paths,
            tracked_paths=tracked_paths,
            untracked_paths=untracked_paths,
        )
        copy_tracked_tree(source_root, candidate_app, tracked_paths)
        copy_explicit_untracked_tree(source_root, candidate_app, included_untracked_paths)
        copy_dist(source_root, candidate_app)
        app_inventory = inventory_tree(candidate_app)
        dist_inventory = [
            item
            for item in app_inventory
            if str(item["path"]) == DIST_RELATIVE_ROOT
            or str(item["path"]).startswith(DIST_RELATIVE_ROOT + "/")
        ]
        source_snapshot = git_snapshot(
            source_root, included_untracked_paths=included_untracked_paths
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
                "tracked_paths_copied": True,
                "explicit_untracked_paths_copied": included_untracked_paths,
                "explicit_untracked_provenance": _explicit_include_provenance(
                    included_untracked_paths
                ),
                "working_tree_dist_included": True,
            },
            "candidate": {
                "root": str(candidate_root),
                "app_root": str(candidate_app),
                "release_id": release_id,
                "formal_release_root": str(_resolved(formal_release_root)),
                "overwrite_policy": "refuse existing candidate root and never write formal release root",
                "data_copy_performed": False,
                "ignored_runtime_data_copied": False,
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
                "included_from_current_source": True,
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
    parser.add_argument("--api-plist", type=Path, required=True)
    parser.add_argument("--scheduler-plist", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--release-id", required=True)
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
        receipt = build_candidate(
            source_root=args.source_root,
            candidate_root=args.candidate_root,
            api_plist_path=args.api_plist,
            scheduler_plist_path=args.scheduler_plist,
            python=args.python,
            release_id=args.release_id,
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
