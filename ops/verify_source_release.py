#!/usr/bin/env python3
"""Compare the canonical v4_app source with a deployed app tree.

The comparison is intentionally narrow.  It hashes source files selected by
Git under the canonical runtime roots, records explicit symlink identities,
and never follows an upstream symlink while collecting files.  The release
tree is read only; the only writes performed by this command are an optional
JSON receipt and an optional Git evidence snapshot outside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "v4.source_release_compare.v1"
RELEASE_ROOT_ENV = "V4_RELEASE_APP_ROOT"

# These roots are the executable/source contract for the 8873 app.  The
# generated frontend dist is deliberately outside this list: it has no
# checked-in source counterpart in v4_app and remains CANNOT_CONFIRM until a
# build artifact receipt is supplied.
CANONICAL_FILE_ROOTS = (
    "apps/api",
    "apps/web/src",
    "domains",
    "infrastructure",
    "v4",
    "ops",
    "contracts",
    "stage_center",
    "upstreams/v3_shared_data",
    "upstreams/review_core",
    "components",
)

# Runtime upstream identity is part of the deployment contract.  We record
# the link text and target existence only; target contents are never walked.
CANONICAL_LINK_PATHS = (
    "v3_shared_data",
)

# This helper is an evidence tool added after the frozen release.  It must not
# make an otherwise equal application source tree fail comparison.
# These are evidence/deployment-governance helpers, not runtime business
# files.  Keeping them outside the fixed runtime comparison prevents an
# uncommitted receipt tool from changing the meaning of the 8873 source
# baseline.  Any caller-supplied override is reported as CUSTOM_SCOPE.
DEFAULT_EXCLUDES = (
    "ops/verify_source_release.py",
    "ops/build_release_candidate.py",
    "ops/prepare_api_only_cutover.py",
)

# A full release contains generated assets, manifests, and data mounts whose
# provenance is checked by separate gates.  Keep the gap explicit in every
# receipt instead of silently claiming the whole release is equal.
UNCHECKED_RELEASE_SCOPE = (
    "apps/web/dist (generated frontend output; no checked-in source tree)",
    "release verification/manifests outside the canonical file roots",
    "runtime data roots and external upstream target contents",
)


@dataclass(frozen=True)
class FileEntry:
    path: str
    kind: str
    sha256: str | None
    mode: int | None
    target: str | None = None
    target_exists: bool | None = None

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "path": self.path,
            "kind": self.kind,
        }
        if self.sha256 is not None:
            data["sha256"] = self.sha256
        if self.mode is not None:
            data["mode"] = f"{self.mode:04o}"
        if self.target is not None:
            data["target"] = self.target
            data["target_exists"] = bool(self.target_exists)
        return data


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalise_relative(path: str | Path) -> str:
    normalised = Path(path).as_posix()
    if Path(normalised).is_absolute() or normalised in {"", ".", ".."}:
        raise ValueError(f"expected a relative path: {path}")
    if ".." in Path(normalised).parts:
        raise ValueError(f"path escapes selected root: {path}")
    return normalised


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry_for_path(root: Path, relative_path: str) -> FileEntry:
    absolute = root / relative_path
    relative_path = _normalise_relative(relative_path)
    info = absolute.lstat()
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(absolute)
        return FileEntry(
            path=relative_path,
            kind="symlink",
            sha256=None,
            mode=None,
            target=target,
            target_exists=os.path.exists(absolute),
        )
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"unsupported source entry type: {relative_path}")
    return FileEntry(
        path=relative_path,
        kind="file",
        sha256=_hash_file(absolute),
        mode=stat.S_IMODE(info.st_mode),
    )


def _git_output(source_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=source_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def git_metadata(source_root: Path) -> dict[str, object]:
    """Return the source identity and current status without changing Git."""

    return {
        "repository": _git_output(source_root, "rev-parse", "--show-toplevel").strip(),
        "commit": _git_output(source_root, "rev-parse", "HEAD").strip(),
        "branch": _git_output(source_root, "branch", "--show-current").strip(),
        "status_porcelain": _git_output(
            source_root, "status", "--porcelain=v1", "--untracked-files=all"
        ),
    }


def git_source_paths(source_root: Path, file_roots: Sequence[str]) -> list[str]:
    """List tracked and non-ignored source files under the selected roots."""

    output = _git_output(
        source_root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        *file_roots,
    )
    return sorted(
        {
            _normalise_relative(path)
            for path in output.split("\0")
            if path
        }
    )


def collect_source_entries(
    source_root: Path,
    file_roots: Sequence[str] = CANONICAL_FILE_ROOTS,
    excludes: Sequence[str] = DEFAULT_EXCLUDES,
) -> dict[str, FileEntry]:
    excluded = {_normalise_relative(path) for path in excludes}
    entries: dict[str, FileEntry] = {}
    for file_root in file_roots:
        root = source_root / _normalise_relative(file_root)
        if not root.is_dir():
            raise FileNotFoundError(f"source file root does not exist: {file_root}")
    for relative_path in git_source_paths(source_root, file_roots):
        if relative_path in excluded:
            continue
        absolute = source_root / relative_path
        if not absolute.exists() and not absolute.is_symlink():
            raise FileNotFoundError(f"Git source path is missing: {relative_path}")
        entries[relative_path] = _entry_for_path(source_root, relative_path)
    return entries


def _walk_release_paths(release_root: Path, file_roots: Sequence[str]) -> Iterable[str]:
    for file_root in file_roots:
        root = release_root / file_root
        if not root.exists() and not root.is_symlink():
            continue
        if root.is_symlink():
            yield _normalise_relative(file_root)
            continue
        if not root.is_dir():
            continue
        for directory, directories, filenames in os.walk(root, followlinks=False):
            # Do not descend through a symlink.  It is yielded as an entry so
            # a link accidentally introduced inside the scope is visible.
            safe_directories: list[str] = []
            for name in directories:
                candidate = Path(directory) / name
                if candidate.is_symlink():
                    yield _normalise_relative(candidate.relative_to(release_root))
                else:
                    safe_directories.append(name)
            directories[:] = safe_directories
            for name in filenames:
                yield _normalise_relative((Path(directory) / name).relative_to(release_root))


def collect_release_entries(
    release_root: Path,
    file_roots: Sequence[str] = CANONICAL_FILE_ROOTS,
    excludes: Sequence[str] = DEFAULT_EXCLUDES,
) -> dict[str, FileEntry]:
    excluded = {_normalise_relative(path) for path in excludes}
    entries: dict[str, FileEntry] = {}
    for relative_path in sorted(set(_walk_release_paths(release_root, file_roots))):
        if relative_path in excluded:
            continue
        absolute = release_root / relative_path
        entries[relative_path] = _entry_for_path(release_root, relative_path)
    return entries


def collect_link_entries(
    root: Path,
    link_paths: Sequence[str] = CANONICAL_LINK_PATHS,
) -> dict[str, FileEntry]:
    entries: dict[str, FileEntry] = {}
    for link_path in link_paths:
        relative_path = _normalise_relative(link_path)
        absolute = root / relative_path
        if not absolute.is_symlink():
            continue
        entries[relative_path] = _entry_for_path(root, relative_path)
    return entries


def _entry_signature(entry: FileEntry) -> tuple[object, ...]:
    return (
        entry.kind,
        entry.sha256,
        entry.mode,
        entry.target,
        entry.target_exists,
    )


def _tree_digest(entries: Mapping[str, FileEntry]) -> str:
    digest = hashlib.sha256()
    for path in sorted(entries):
        entry = entries[path]
        digest.update(json.dumps(entry.as_dict(), sort_keys=True).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _counts_by_root(entries: Mapping[str, FileEntry], file_roots: Sequence[str]) -> dict[str, int]:
    return {
        root: sum(path == root or path.startswith(f"{root}/") for path in entries)
        for root in file_roots
    }


def compare_entry_sets(
    source_entries: Mapping[str, FileEntry],
    release_entries: Mapping[str, FileEntry],
    source_links: Mapping[str, FileEntry],
    release_links: Mapping[str, FileEntry],
) -> dict[str, object]:
    missing = sorted(set(source_entries) - set(release_entries))
    extra = sorted(set(release_entries) - set(source_entries))
    mismatched: list[dict[str, object]] = []
    for path in sorted(set(source_entries) & set(release_entries)):
        source_entry = source_entries[path]
        release_entry = release_entries[path]
        if _entry_signature(source_entry) != _entry_signature(release_entry):
            mismatched.append(
                {
                    "path": path,
                    "source": source_entry.as_dict(),
                    "release": release_entry.as_dict(),
                }
            )

    missing_links = sorted(set(source_links) - set(release_links))
    extra_links = sorted(set(release_links) - set(source_links))
    mismatched_links: list[dict[str, object]] = []
    for path in sorted(set(source_links) & set(release_links)):
        source_link = source_links[path]
        release_link = release_links[path]
        if _entry_signature(source_link) != _entry_signature(release_link):
            mismatched_links.append(
                {
                    "path": path,
                    "source": source_link.as_dict(),
                    "release": release_link.as_dict(),
                }
            )

    source_links_with_missing_targets = sorted(
        path for path, entry in source_links.items() if not entry.target_exists
    )
    release_links_with_missing_targets = sorted(
        path for path, entry in release_links.items() if not entry.target_exists
    )

    selected_scope_pass = not (
        missing
        or extra
        or mismatched
        or missing_links
        or extra_links
        or mismatched_links
        or source_links_with_missing_targets
        or release_links_with_missing_targets
    )
    return {
        "status": "PASS" if selected_scope_pass else "FAIL",
        "same_origin_selected_scope": selected_scope_pass,
        "missing_files_in_release": missing,
        "extra_files_in_release": extra,
        "mismatched_files": mismatched,
        "missing_links_in_release": missing_links,
        "extra_links_in_release": extra_links,
        "mismatched_links": mismatched_links,
        "source_links_with_missing_targets": source_links_with_missing_targets,
        "release_links_with_missing_targets": release_links_with_missing_targets,
        "source_file_count": len(source_entries),
        "release_file_count": len(release_entries),
        "source_tree_sha256": _tree_digest(source_entries),
        "release_tree_sha256": _tree_digest(release_entries),
    }


def compare_roots(
    source_root: Path,
    release_root: Path,
    *,
    file_roots: Sequence[str] = CANONICAL_FILE_ROOTS,
    link_paths: Sequence[str] = CANONICAL_LINK_PATHS,
    excludes: Sequence[str] = DEFAULT_EXCLUDES,
) -> dict[str, object]:
    source_root = source_root.expanduser().resolve()
    release_root = release_root.expanduser().resolve()
    if source_root == release_root:
        raise ValueError("source and release roots must be distinct resolved paths")
    if not source_root.is_dir():
        raise FileNotFoundError(f"source root does not exist: {source_root}")
    if not release_root.is_dir():
        raise FileNotFoundError(f"release root does not exist: {release_root}")

    file_roots = tuple(_normalise_relative(path) for path in file_roots)
    link_paths = tuple(_normalise_relative(path) for path in link_paths)
    excludes = tuple(_normalise_relative(path) for path in excludes)
    source_entries = collect_source_entries(source_root, file_roots, excludes)
    release_entries = collect_release_entries(release_root, file_roots, excludes)
    source_links = collect_link_entries(source_root, link_paths)
    release_links = collect_link_entries(release_root, link_paths)
    comparison = compare_entry_sets(
        source_entries,
        release_entries,
        source_links,
        release_links,
    )
    comparison.update(
        {
            "source_links": [source_links[path].as_dict() for path in sorted(source_links)],
            "release_links": [release_links[path].as_dict() for path in sorted(release_links)],
            "source_missing_expected_links": sorted(set(link_paths) - set(source_links)),
            "release_missing_expected_links": sorted(set(link_paths) - set(release_links)),
        }
    )
    comparison["status"] = (
        "PASS"
        if comparison["status"] == "PASS"
        and not comparison["source_missing_expected_links"]
        and not comparison["release_missing_expected_links"]
        else "FAIL"
    )
    comparison["same_origin_selected_scope"] = comparison["status"] == "PASS"
    comparison["source_file_counts_by_root"] = _counts_by_root(source_entries, file_roots)
    comparison["release_file_counts_by_root"] = _counts_by_root(release_entries, file_roots)
    comparison["source_entries"] = [
        source_entries[path].as_dict() for path in sorted(source_entries)
    ]
    comparison["release_entries"] = [
        release_entries[path].as_dict() for path in sorted(release_entries)
    ]
    return comparison


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _assert_external_output(path: Path, source_root: Path, release_root: Path) -> Path:
    resolved = path.expanduser().resolve()
    for protected_root in (source_root.resolve(), release_root.resolve()):
        if resolved == protected_root or protected_root in resolved.parents:
            raise ValueError(f"evidence output must be outside protected tree: {resolved}")
    return resolved


def write_git_snapshot(source_root: Path, output_dir: Path) -> dict[str, object]:
    """Save auditable Git status/diff material outside the repository."""

    # The release root is not available in this helper; build_receipt performs
    # the stronger source/release guard before calling it.
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    status = _git_output(source_root, "status", "--porcelain=v1", "--untracked-files=all")
    diff = _git_output(source_root, "diff", "--no-ext-diff", "--binary", "--")
    diff_stat = _git_output(source_root, "diff", "--no-ext-diff", "--stat", "--")
    _write_text(output_dir / "git-status.txt", status)
    _write_text(output_dir / "git-diff.patch", diff)
    _write_text(output_dir / "git-diff-stat.txt", diff_stat)

    untracked = []
    for line in status.splitlines():
        if line.startswith("?? "):
            relative = line[3:]
            candidate = source_root / relative
            if candidate.is_file() and not candidate.is_symlink():
                untracked.append(
                    {
                        "path": relative,
                        "sha256": _hash_file(candidate),
                        "bytes": candidate.stat().st_size,
                    }
                )
    _write_text(
        output_dir / "untracked-files.json",
        json.dumps(untracked, ensure_ascii=False, indent=2) + "\n",
    )
    return {
        "directory": str(output_dir),
        "status_file": str(output_dir / "git-status.txt"),
        "diff_file": str(output_dir / "git-diff.patch"),
        "diff_stat_file": str(output_dir / "git-diff-stat.txt"),
        "untracked_file_manifest": str(output_dir / "untracked-files.json"),
        "status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
        "diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
    }


def build_receipt(
    source_root: Path,
    release_root: Path,
    *,
    file_roots: Sequence[str] = CANONICAL_FILE_ROOTS,
    link_paths: Sequence[str] = CANONICAL_LINK_PATHS,
    excludes: Sequence[str] = DEFAULT_EXCLUDES,
    git_snapshot_dir: Path | None = None,
    scope_mode: str | None = None,
) -> dict[str, object]:
    comparison = compare_roots(
        source_root,
        release_root,
        file_roots=file_roots,
        link_paths=link_paths,
        excludes=excludes,
    )
    fixed_scope = (
        tuple(file_roots) == tuple(CANONICAL_FILE_ROOTS)
        and tuple(link_paths) == tuple(CANONICAL_LINK_PATHS)
        and tuple(excludes) == tuple(DEFAULT_EXCLUDES)
    )
    computed_scope_mode = "FIXED_CANONICAL" if fixed_scope else "CUSTOM_SCOPE"
    if scope_mode is not None and scope_mode not in {"FIXED_CANONICAL", "CUSTOM_SCOPE"}:
        raise ValueError(f"unsupported scope mode: {scope_mode}")
    if scope_mode is not None and scope_mode != computed_scope_mode:
        raise ValueError(
            f"scope_mode {scope_mode} does not match the supplied comparison scope "
            f"({computed_scope_mode})"
        )
    resolved_scope_mode = computed_scope_mode
    receipt: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "source_root": str(source_root.expanduser().resolve()),
        "release_root": str(release_root.expanduser().resolve()),
        "source_git": git_metadata(source_root.expanduser().resolve()),
        "scope": {
            "scope_mode": resolved_scope_mode,
            "fixed_acceptance_scope": resolved_scope_mode == "FIXED_CANONICAL",
            "canonical_file_roots": list(file_roots),
            "canonical_link_paths": list(link_paths),
            "excluded_source_paths": list(excludes),
            "unchecked_release_scope": list(UNCHECKED_RELEASE_SCOPE),
            "follows_upstream_symlinks": False,
            "reads_runtime_data": False,
            "writes_release_tree": False,
        },
        "comparison": comparison,
        # A selected-scope PASS does not close the separate generated-assets
        # and runtime-inventory gates.
        "selected_scope_status": (
            comparison["status"]
            if resolved_scope_mode == "FIXED_CANONICAL"
            else ("CUSTOM_SCOPE" if comparison["status"] == "PASS" else "CUSTOM_SCOPE_FAIL")
        ),
        "fixed_scope_status": comparison["status"] if resolved_scope_mode == "FIXED_CANONICAL" else "NOT_APPLICABLE",
        "deployment_status": "CANNOT_CONFIRM",
    }
    if git_snapshot_dir is not None:
        _assert_external_output(git_snapshot_dir, source_root, release_root)
        receipt["git_snapshot"] = write_git_snapshot(
            source_root.expanduser().resolve(), git_snapshot_dir
        )
    return receipt


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare canonical v4_app source files and link identities with a release app."
    )
    project_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--source-root", type=Path, default=project_root)
    parser.add_argument(
        "--release-root",
        type=Path,
        default=None,
        help=f"release app root; defaults to ${RELEASE_ROOT_ENV}",
    )
    parser.add_argument("--receipt", type=Path, help="write a JSON receipt at this path")
    parser.add_argument(
        "--git-snapshot-dir",
        type=Path,
        help="also save Git status/diff material in this external directory",
    )
    parser.add_argument(
        "--file-root",
        action="append",
        dest="file_roots",
        help="override canonical file roots; repeat for multiple roots",
    )
    parser.add_argument(
        "--link-path",
        action="append",
        dest="link_paths",
        help="override canonical link paths; repeat for multiple links",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        dest="excludes",
        help="exclude a relative source/release path from the selected scope",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    source_root = args.source_root.expanduser().resolve()
    release_root = args.release_root
    if release_root is None:
        configured = os.environ.get(RELEASE_ROOT_ENV)
        if not configured:
            parser.error(f"--release-root or ${RELEASE_ROOT_ENV} is required")
        release_root = Path(configured)
    file_roots = tuple(args.file_roots or CANONICAL_FILE_ROOTS)
    link_paths = tuple(args.link_paths or CANONICAL_LINK_PATHS)
    excludes = tuple(args.excludes or DEFAULT_EXCLUDES)
    custom_scope_requested = any(
        value is not None for value in (args.file_roots, args.link_paths, args.excludes)
    )

    try:
        if args.receipt is not None:
            _assert_external_output(args.receipt, source_root, release_root)
        receipt = build_receipt(
            source_root,
            release_root,
            file_roots=file_roots,
            link_paths=link_paths,
            excludes=excludes,
            git_snapshot_dir=args.git_snapshot_dir,
            scope_mode="CUSTOM_SCOPE" if custom_scope_requested else "FIXED_CANONICAL",
        )
    except (FileNotFoundError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"verification error: {exc}", file=sys.stderr)
        return 2

    if args.receipt is not None:
        _write_json(args.receipt, receipt)
    print(
        json.dumps(
            {
                "selected_scope_status": receipt["selected_scope_status"],
                "scope_mode": receipt["scope"]["scope_mode"],
                "deployment_status": receipt["deployment_status"],
                "source_file_count": receipt["comparison"]["source_file_count"],
                "release_file_count": receipt["comparison"]["release_file_count"],
                "receipt": str(args.receipt.expanduser().resolve())
                if args.receipt is not None
                else None,
            },
            ensure_ascii=False,
        )
    )
    return 0 if receipt["comparison"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
