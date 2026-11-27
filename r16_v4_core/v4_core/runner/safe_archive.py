"""Safe archive filter with deduplicated 3-level manifest traversal & explicit C-class/mixed-root protection."""
from __future__ import annotations

from collections.abc import Iterator, Set as AbstractSet
from dataclasses import dataclass
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

PROTECTED_KEYWORDS = (
    "evidence",
    "receipt",
    "proof",
    "audit",
    "manifest",
    "handoff",
    "artifacts/",
    "rollback",
    # Explicit C-class historical data & mixed-state root guards
    "com.lexi.v35.local/state",
    "com.lexi.v4.local/state",
    "v3_shared_data",
    ".runtime/data",
    "research_panel_daily",
    "close_reviews",
    "preselection_inputs",
    "runtime_graph",
    "/state/data",
    "/state/dispatcher",
    "/workspace/数据",
)
PROTECTED_SUFFIXES = (".zip", ".log", ".jsonl", ".sha256")
ROLLBACK_SCRIPT = "rollback_to_legacy_three_roles.sh"
ROLLBACK_BACKUP_DIR = "legacy_three_roles_backup"
ROLLBACK_ROLE_PLISTS = frozenset({
    "com.lexi.v4.api.plist",
    "com.lexi.v4.scheduler.plist",
    "com.lexi.stage-center.scheduler.plist",
})
# The frozen originals include a group manifest and the three role release trees.
ROLLBACK_ROLE_RELEASES = (
    "v4-r2-rollup-20261124-api-r1",
    "v4-r2-20261125-main-daily-physical-r2",
    "v4-r2-20261125-stage-daily-physical-r2",
)
REQUIRED_GROUP_ROLES = frozenset({"api", "main", "stage"})
_GENERATED_CPYTHON_314_CACHE_NAME = re.compile(r"^.+\.cpython-314\.pyc$")


class ManifestCoverageError(ValueError):
    """An archive decision lacks a complete active manifest inventory."""


def _beneath(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def is_protected_evidence(path: str, *, protected_roots: set[str] | None = None) -> bool:
    norm = path.strip().replace("\\", "/").casefold()
    parts = norm.split("/")
    if any(k in norm for k in PROTECTED_KEYWORDS) or norm.endswith(PROTECTED_SUFFIXES):
        return True
    if (ROLLBACK_BACKUP_DIR in parts or ROLLBACK_SCRIPT in parts
            or parts[-1] in ROLLBACK_ROLE_PLISTS or any(name in parts for name in ROLLBACK_ROLE_RELEASES)):
        return True
    return any(
        _beneath(norm, root.strip().replace("\\", "/").rstrip("/").casefold())
        for root in protected_roots or ()
        if root.strip()
    )


def _normalize_rel_path(raw_path: str) -> str:
    p = raw_path.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def _resolve_ref_path(base_file: Path, target: str) -> Path:
    p = Path(target)
    return p if p.is_absolute() else (base_file.parent / p)


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _runtime_inventory_matches(app_root: Path, entries: list[dict[str, Any]]) -> bool:
    """Check the release producer's canonical file inventory under the role-bound root."""
    def reraise(error: OSError) -> None:
        raise error

    try:
        if app_root.resolve(strict=True) != app_root or not app_root.is_dir():
            return False
        actual = {}
        for directory, directories, filenames in os.walk(app_root, followlinks=False, onerror=reraise):
            parent = Path(directory)
            for name in directories + filenames:
                path = parent / name
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode):
                    continue
                relative = path.relative_to(app_root).as_posix()
                if (stat.S_ISREG(info.st_mode) and parent.name == "__pycache__"
                        and parent != app_root and _GENERATED_CPYTHON_314_CACHE_NAME.fullmatch(name)):
                    continue
                actual[relative] = info

        if sorted(actual) != [entry["path"] for entry in entries]:
            return False
        for entry in entries:
            relative = entry["path"]
            info = actual[relative]
            path = app_root / relative
            if stat.S_ISLNK(info.st_mode):
                observed = {"path": relative, "kind": "symlink", "target": os.readlink(path), "target_exists": path.exists()}
            elif stat.S_ISREG(info.st_mode):
                with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
                    if os.fstat(handle.fileno()) != info:
                        return False
                    digest = file_digest(handle, "sha256").hexdigest()
                    after = os.fstat(handle.fileno())
                    if (after.st_mtime_ns, after.st_ctime_ns) != (info.st_mtime_ns, info.st_ctime_ns):
                        return False
                observed = {
                    "path": relative, "kind": "file", "sha256": digest,
                    "mode": f"{stat.S_IMODE(info.st_mode):04o}", "size": info.st_size,
                }
            else:
                return False
            if entry != observed:
                return False
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _collect_manifest_records(
    manifest_json: Path,
    *,
    dedup_map: dict[tuple[str, str, str], dict[str, Any]],
    fingerprints: dict[Path, str],
    runtime_paths: set[str],
    level: int = 1,
    role: str = "single",
    expected_sha256: str | None = None,
    expected_app_root: str | None = None,
) -> None:
    try:
        resolved = manifest_json.resolve(strict=True)
        if resolved in fingerprints or not resolved.is_file():
            raise ManifestCoverageError(f"Invalid, shared or cyclic manifest: {manifest_json}")
        raw = resolved.read_bytes()
        fingerprint = sha256(raw).hexdigest()
        if expected_sha256 is not None and fingerprint != expected_sha256:
            raise ManifestCoverageError(f"Manifest checksum mismatch: {manifest_json}")
        data = json.loads(raw)
    except ManifestCoverageError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ManifestCoverageError(f"Unreadable manifest: {manifest_json}") from exc
    if not isinstance(data, dict):
        raise ManifestCoverageError(f"Invalid manifest object: {manifest_json}")
    fingerprints[resolved] = fingerprint

    current_role = data.get("role", role)
    if not isinstance(current_role, str) or not current_role.strip() or (level > 1 and current_role != role):
        raise ManifestCoverageError(f"Manifest role mismatch: {manifest_json}")
    if level == 2 and "role" not in data:
        raise ManifestCoverageError(f"Missing release manifest role: {manifest_json}")
    app_root = data.get("app_root", "")
    if not isinstance(app_root, str) or (level > 1 and not Path(app_root).is_absolute()):
        raise ManifestCoverageError(f"Missing explicit application root: {manifest_json}")

    def follow(reference: object, child_role: str, child_app_root: str | None = None) -> None:
        if not isinstance(reference, dict) or not isinstance(reference.get("path"), str) or not reference["path"].strip():
            raise ManifestCoverageError(f"Invalid child manifest reference: {manifest_json}")
        declared_sha = reference.get("sha256")
        if "sha256" in reference and not _valid_sha256(declared_sha):
            raise ManifestCoverageError(f"Invalid child manifest checksum: {manifest_json}")
        _collect_manifest_records(
            _resolve_ref_path(resolved, reference["path"]), dedup_map=dedup_map, fingerprints=fingerprints,
            runtime_paths=runtime_paths, level=level + 1, role=child_role, expected_sha256=declared_sha,
            expected_app_root=child_app_root,
        )

    def inventory(items: object, *, exact: bool = False) -> int:
        if not isinstance(items, list):
            raise ManifestCoverageError(f"Invalid protected inventory: {manifest_json}")
        paths = set()
        file_count = 0
        for item in items:
            if isinstance(item, str) and not exact:
                item = {"path": item}
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ManifestCoverageError(f"Invalid protected inventory entry: {manifest_json}")
            path = _normalize_rel_path(item["path"])
            if not path or not Path(path).parts or ".." in Path(path).parts or "\x00" in path:
                raise ManifestCoverageError(f"Invalid protected inventory path: {manifest_json}")
            kind = item.get("kind")
            digest = item.get("sha256")
            if exact:
                if path != item["path"] or Path(path).as_posix() != path or Path(path).is_absolute() or path in paths:
                    raise ManifestCoverageError(f"Invalid exact inventory path: {manifest_json}")
                if kind not in ("dir", "directory", "file", "symlink", "link"):
                    raise ManifestCoverageError(f"Invalid exact inventory kind: {manifest_json}")
                if kind == "file" and not _valid_sha256(digest):
                    raise ManifestCoverageError(f"Missing exact inventory file checksum: {manifest_json}")
                paths.add(path)
            if kind in ("dir", "directory"):
                continue
            if kind not in (None, "file", "symlink", "link") or (digest is not None and not isinstance(digest, str)):
                raise ManifestCoverageError(f"Invalid protected inventory entry: {manifest_json}")
            key = (current_role, app_root, path)
            existing = dedup_map.get(key)
            if existing is None:
                dedup_map[key] = {"role": current_role, "app_root": app_root, "path": path, "sha256": digest}
            elif existing["sha256"] is None:
                existing["sha256"] = digest
            elif digest is not None and existing["sha256"] != digest:
                raise ManifestCoverageError(f"Conflicting protected inventory entries: {manifest_json}")
            file_count += 1
        return file_count

    if level == 1:
        roles_map = data.get("roles")
        if (not isinstance(roles_map, dict) or not REQUIRED_GROUP_ROLES <= roles_map.keys()
                or "startup_manifest" in data or data.get("activation_status", "ACTIVE") != "ACTIVE"):
            raise ManifestCoverageError(f"Incomplete active three-role group manifest: {manifest_json}")
        for child_role, reference in roles_map.items():
            follow(reference, child_role)
    elif level == 2:
        if "roles" in data or "startup_manifest" not in data:
            raise ManifestCoverageError(f"Missing release startup manifest: {manifest_json}")
        follow(data["startup_manifest"], role, app_root)
    else:
        exact = data.get("application_inventory")
        if app_root != expected_app_root:
            raise ManifestCoverageError(f"Startup application root does not match release: {manifest_json}")
        if "roles" in data or "startup_manifest" in data or not isinstance(exact, dict):
            raise ManifestCoverageError(f"Missing exact startup application inventory: {manifest_json}")
        entries = exact.get("entries")
        count = exact.get("entry_count")
        if not isinstance(entries, list) or type(count) is not int or count != len(entries):
            raise ManifestCoverageError(f"Incomplete exact startup application inventory: {manifest_json}")
        try:
            inventory_bytes = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        except UnicodeError as exc:
            raise ManifestCoverageError(f"Invalid startup inventory encoding: {manifest_json}") from exc
        if exact.get("aggregate_sha256") != sha256(inventory_bytes).hexdigest() or not inventory(entries, exact=True):
            raise ManifestCoverageError(f"Unproven startup application inventory: {manifest_json}")
        root = Path(app_root)
        if not _runtime_inventory_matches(root, entries):
            raise ManifestCoverageError(f"Startup inventory differs from the application root: {manifest_json}")
        runtime_paths.update(str(root / entry["path"]) for entry in entries)

    for field in ("overlay_files", "app_files"):
        if field in data:
            inventory(data[field])


def _load_inventory(manifest_json: Path) -> tuple[list[dict[str, Any]], tuple[tuple[Path, str], ...], frozenset[str]]:
    dedup_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    fingerprints: dict[Path, str] = {}
    runtime_paths: set[str] = set()
    _collect_manifest_records(
        manifest_json, dedup_map=dedup_map, fingerprints=fingerprints, runtime_paths=runtime_paths,
    )
    return list(dedup_map.values()), tuple(sorted(fingerprints.items())), frozenset(runtime_paths)


def load_manifest_records(manifest_json: Path) -> list[dict[str, Any]]:
    """Return deduplicated role-attributed file records preserving (role, app_root, path, sha256)."""
    records, _, _ = _load_inventory(Path(manifest_json))
    return records


@dataclass(frozen=True, eq=False, slots=True)
class _VerifiedManifestPaths(AbstractSet[str]):
    manifest: Path
    paths: frozenset[str]
    fingerprints: tuple[tuple[Path, str], ...]
    runtime_paths: frozenset[str]

    def __contains__(self, path: object) -> bool:
        return path in self.paths

    def __iter__(self) -> Iterator[str]:
        return iter(self.paths)

    def __len__(self) -> int:
        return len(self.paths)

    @classmethod
    def _from_iterable(cls, paths: Iterator[str]) -> frozenset[str]:
        # Set operations carry only path hints, never the manifest proof.
        return frozenset(paths)

    def still_verified(self) -> bool:
        try:
            observed = load_manifest_paths(self.manifest)
        except ManifestCoverageError:
            return False
        return (self.fingerprints == observed.fingerprints and self.paths == observed.paths
                and self.runtime_paths == observed.runtime_paths)


def load_manifest_paths(manifest_json: Path) -> _VerifiedManifestPaths:
    """Read an immutable, decision-time-verifiable group -> release -> startup inventory."""
    manifest = Path(manifest_json).absolute()
    records, fingerprints, runtime_paths = _load_inventory(manifest)
    return _VerifiedManifestPaths(manifest, frozenset(record["path"] for record in records), fingerprints, runtime_paths)


def filter_safe_archive_paths(
    candidate_paths: list[str],
    git_tracked_paths: set[str],
    active_manifest_paths: AbstractSet[str] | None,
    *,
    dirty_git_paths: set[str] | None = None,
    protected_roots: set[str] | None = None,
    rollback_dependencies: set[str] | None = None,
    repo_root: Path | None = None,
) -> dict[str, list[str]]:
    """Compare lexical and real identities before an archive candidate can be allowed."""
    root = os.path.realpath(repo_root if repo_root is not None else Path.cwd())

    def absolute(path: str) -> str:
        return os.path.normpath(os.path.join(root, path))

    def real(path: str) -> str | None:
        # Keep ".." until realpath resolves links in preceding path components.
        raw = os.path.join(root, path)
        try:
            return os.path.realpath(raw, strict=True)
        except FileNotFoundError:
            return os.path.realpath(raw)
        except (OSError, ValueError):
            return None

    def relative_for_keywords(path: str) -> str:
        return os.path.relpath(path, root) if _beneath(path, root) else path

    explicit_inputs = {
        _normalize_rel_path(path) for path in (protected_roots or set()) | (rollback_dependencies or set())
        if _normalize_rel_path(path)
    }
    explicit_protection = {absolute(path) for path in explicit_inputs}
    unresolved_protection = False
    # If a configured protected root is itself a link, also guard its target.
    for path in explicit_inputs:
        target = real(path)
        if target:
            explicit_protection.add(target)
        else:
            unresolved_protection = True

    def protected(path: str) -> bool:
        if is_protected_evidence(relative_for_keywords(path)):
            return True
        return any(_beneath(path.casefold(), guard.casefold()) for guard in explicit_protection)

    def identities(paths: AbstractSet[str]) -> tuple[set[str], set[str], bool]:
        lexical, canonical = set(), set()
        unresolved = False
        for raw in paths:
            path = _normalize_rel_path(raw) if isinstance(raw, str) else ""
            if not path:
                unresolved = True
                continue
            lexical.add(absolute(path).casefold())
            target = real(path)
            if target:
                canonical.add(target.casefold())
            else:
                unresolved = True
        return lexical, canonical, unresolved

    if isinstance(active_manifest_paths, _VerifiedManifestPaths):
        verified = active_manifest_paths.still_verified()
        active_inputs = active_manifest_paths.paths | active_manifest_paths.runtime_paths
    else:
        verified = False
        active_inputs = active_manifest_paths or set()
    active, active_real, active_unresolved = identities(active_inputs)
    dirty, dirty_real, dirty_unresolved = identities(dirty_git_paths or set())
    unresolved_guard = not verified or not active or unresolved_protection or active_unresolved or dirty_unresolved
    tracked = {absolute(_normalize_rel_path(p)) for p in git_tracked_paths}
    safe, skipped_active, skipped_missing, skipped_dirty, skipped_evidence = [], [], [], [], []
    for p in candidate_paths:
        np = _normalize_rel_path(p)
        base = absolute(np)
        if base.casefold() in active:
            skipped_active.append(p)
        elif base.casefold() in dirty:
            skipped_dirty.append(p)
        elif (not np or p != p.strip() or "\\" in p
              or protected(base) or not _beneath(base, root)):
            skipped_evidence.append(p)
        else:
            target = real(np)
            if target and (target.casefold() in active_real or target.casefold() in active):
                skipped_active.append(p)
            elif target and (target.casefold() in dirty_real or target.casefold() in dirty):
                skipped_dirty.append(p)
            elif (unresolved_guard or target is None or protected(target) or not _beneath(target, root)
                  or target != base or ".." in Path(np).parts):
                skipped_evidence.append(p)
            elif base not in tracked:
                skipped_missing.append(p)
            else:
                safe.append(p)
    return {
        "safe_to_archive": safe,
        "skipped_active_manifest": skipped_active,
        "skipped_dirty_git": skipped_dirty,
        "skipped_protected_evidence": skipped_evidence,
        "skipped_not_in_git": skipped_missing,
    }
