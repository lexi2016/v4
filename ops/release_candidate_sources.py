"""Release-candidate operations with explicit compatibility dependencies.

No module-global core binding or reverse facade import is used. These are
existing inactive-builder operations, not a deployment or migration service.
"""
from __future__ import annotations
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, TYPE_CHECKING
if TYPE_CHECKING:
    from ops.release_candidate_ports import BuilderAPI

def _normalise_relative(path: str | Path, *, _api: BuilderAPI) -> str:
    value = Path(path).as_posix()
    if Path(value).is_absolute() or not value or value in {".", ".."} or ".." in Path(value).parts:
        raise ValueError(f"unsafe relative path: {path}")
    return value


def _run_git(source_root: Path, *args: str, binary: bool, _api: BuilderAPI) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=source_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
    )
    return result.stdout


def _git_tracked_paths(source_root: Path, *, _api: BuilderAPI) -> list[str]:
    output = _api._run_git(source_root, "ls-files", "--cached", "-z", binary=True)
    assert isinstance(output, bytes)
    return sorted(
        _api._normalise_relative(item.decode("utf-8"))
        for item in output.split(b"\0")
        if item
    )


def _git_untracked_paths(source_root: Path, *, _api: BuilderAPI) -> list[str]:
    output = _api._run_git(
        source_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        binary=True,
    )
    assert isinstance(output, bytes)
    return sorted(
        _api._normalise_relative(item.decode("utf-8"))
        for item in output.split(b"\0")
        if item
    )


def _validate_explicit_untracked_paths(source_root: Path, requested_paths: Sequence[str | Path], *, tracked_paths: Sequence[str], untracked_paths: Sequence[str], _api: BuilderAPI) -> list[str]:
    """Validate the bounded untracked include list before copying anything."""

    normalised = [_api._normalise_relative(path) for path in requested_paths]
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


def _explicit_include_provenance(paths: Sequence[str], *, _api: BuilderAPI) -> list[dict[str, object]]:
    return [
        {"path": path, "approval": "CALLER_EXPLICIT_REVIEWED_PATH",
         **dict(_api.APPROVED_UNTRACKED_CANDIDATE_PATHS.get(path, {}))}
        for path in paths
    ]


def copy_explicit_untracked_tree(source_root: Path, candidate_app: Path, relative_paths: Sequence[str], *, _api: BuilderAPI) -> None:
    for relative in relative_paths:
        _api._copy_one(source_root / relative, candidate_app / relative)


def git_snapshot(source_root: Path, *, include_untracked_hashes: bool, included_untracked_paths: Sequence[str], _api: BuilderAPI) -> dict[str, object]:
    """Capture Git identity and a bounded working-tree summary without writes."""

    source_root = _api._resolved(source_root)
    diff = _api._run_git(source_root, "diff", "--no-ext-diff", "--binary", "--", binary=True)
    assert isinstance(diff, bytes)
    status = _api._run_git(
        source_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    diff_stat = _api._run_git(source_root, "diff", "--stat", "--no-ext-diff", "--")
    assert isinstance(status, str) and isinstance(diff_stat, str)
    untracked = _api._git_untracked_paths(source_root)
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
                    {"path": relative, "kind": "file", "sha256": _api.sha256_file(path)}
                )
            else:
                untracked_entries.append({"path": relative, "kind": "other"})
    included = sorted(_api._normalise_relative(path) for path in included_untracked_paths)
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
        "repository": str(_api._run_git(source_root, "rev-parse", "--show-toplevel")).strip(),
        "commit": str(_api._run_git(source_root, "rev-parse", "HEAD")).strip(),
        "tree": str(_api._run_git(source_root, "rev-parse", "HEAD^{tree}")).strip(),
        "branch": str(_api._run_git(source_root, "branch", "--show-current")).strip(),
        "tracked_status_porcelain": status,
        "tracked_diff_stat": diff_stat,
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "tracked_diff_bytes": len(diff),
        "untracked_count": len(untracked),
        "untracked_files": untracked_entries,
        "included_untracked_paths": included,
        "candidate_copy_policy": copy_policy,
    }


def snapshot_legacy_git(repo: Path, evidence_root: Path, *, _api: BuilderAPI) -> dict[str, object]:
    """Save only tracked status/diff for the legacy repo.

    ``--untracked-files=no`` and ``git diff`` intentionally avoid walking or
    copying the legacy repository's potentially large untracked tree.
    """

    repo = _api._resolved(repo)
    evidence_root = _api._resolved(evidence_root)
    if _api._is_within(evidence_root, repo) or _api._is_within(repo, evidence_root):
        raise ValueError("legacy Git evidence must be outside the legacy checkout")
    evidence_root.mkdir(parents=True, exist_ok=True)
    status = _api._run_git(repo, "status", "--porcelain=v1", "--untracked-files=no")
    diff = _api._run_git(repo, "diff", "--no-ext-diff", "--binary", "--", binary=True)
    diff_stat = _api._run_git(repo, "diff", "--stat", "--no-ext-diff", "--")
    assert isinstance(status, str) and isinstance(diff, bytes) and isinstance(diff_stat, str)
    (evidence_root / "git-status-tracked-only.txt").write_text(status)
    (evidence_root / "git-diff.patch").write_bytes(diff)
    (evidence_root / "git-diff-stat.txt").write_text(diff_stat)
    receipt = {
        "schema_version": "v4.legacy_v35_git_snapshot.v1",
        "generated_at": _api.utc_now(),
        "repository": str(_api._run_git(repo, "rev-parse", "--show-toplevel")).strip(),
        "commit": str(_api._run_git(repo, "rev-parse", "HEAD")).strip(),
        "branch": str(_api._run_git(repo, "branch", "--show-current")).strip(),
        "status_path": str(evidence_root / "git-status-tracked-only.txt"),
        "diff_path": str(evidence_root / "git-diff.patch"),
        "diff_stat_path": str(evidence_root / "git-diff-stat.txt"),
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "tracked_diff_bytes": len(diff),
        "untracked_tree_scanned": False,
        "untracked_tree_copied": False,
        "scope": "tracked status and tracked diff only; legacy checkout left in place",
    }
    _api._json_dump(evidence_root / "snapshot-receipt.json", receipt)
    return receipt


def _entry_for_path(root: Path, relative: str, *, _api: BuilderAPI) -> dict[str, object]:
    relative = _api._normalise_relative(relative)
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
        "sha256": _api.sha256_file(path),
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "size": info.st_size,
    }


def _walk_entries(root: Path, *, _api: BuilderAPI) -> list[str]:
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


def _copy_one(source: Path, destination: Path, *, _api: BuilderAPI) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
        return
    if not source.is_file():
        raise ValueError(f"source entry is not a regular file or symlink: {source}")
    shutil.copy2(source, destination, follow_symlinks=False)


def copy_tracked_tree(source_root: Path, candidate_app: Path, tracked_paths: Sequence[str], *, _api: BuilderAPI) -> None:
    for relative in tracked_paths:
        source = source_root / relative
        _api._copy_one(source, candidate_app / relative)


def copy_dist(source_root: Path, candidate_app: Path, *, _api: BuilderAPI) -> None:
    source_dist = source_root / _api.DIST_RELATIVE_ROOT
    if not source_dist.is_dir():
        raise FileNotFoundError(f"required current frontend dist is missing: {source_dist}")
    entries = _api._walk_entries(source_dist)
    if not entries:
        raise FileNotFoundError(f"required current frontend dist is empty: {source_dist}")
    destination_dist = candidate_app / _api.DIST_RELATIVE_ROOT
    for relative in entries:
        _api._copy_one(source_dist / relative, destination_dist / relative)


def inventory_tree(root: Path, *, _api: BuilderAPI) -> list[dict[str, object]]:
    return [_api._entry_for_path(root, relative) for relative in _api._walk_entries(root)]


def inventory_digest(entries: Sequence[Mapping[str, object]], *, _api: BuilderAPI) -> str:
    canonical = json.dumps(list(entries), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


