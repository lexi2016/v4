"""Safe archive filter with deduplicated 3-level manifest traversal & explicit C-class/mixed-root protection."""
from __future__ import annotations

import json
import os
from pathlib import Path
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


def _collect_manifest_records(
    manifest_json: Path,
    *,
    role: str = "single",
    visited: set[Path],
    dedup_map: dict[tuple[str, str, str], dict[str, Any]],
) -> None:
    resolved = manifest_json.resolve()
    if resolved in visited or not resolved.exists():
        return
    visited.add(resolved)
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return

    current_role = str(data.get("role") or role)
    app_root = str(data.get("app_root") or "")

    def _add(rel_path: str, sha256: str | None) -> None:
        np = _normalize_rel_path(rel_path)
        if not np:
            return
        key = (current_role, app_root, np)
        existing = dedup_map.get(key)
        if existing is None:
            dedup_map[key] = {"role": current_role, "app_root": app_root, "path": np, "sha256": sha256}
        elif existing.get("sha256") is None and sha256 is not None:
            existing["sha256"] = sha256

    # Level 1: group-manifest.json -> $.roles.<role>.path
    roles_map = data.get("roles")
    if isinstance(roles_map, dict):
        for r_name, r_info in roles_map.items():
            if isinstance(r_info, dict) and isinstance(r_info.get("path"), str):
                _collect_manifest_records(
                    _resolve_ref_path(resolved, r_info["path"]),
                    role=str(r_name),
                    visited=visited,
                    dedup_map=dedup_map,
                )

    # Level 2: role release-manifest.json -> $.startup_manifest.path + $.overlay_files
    startup_ref = data.get("startup_manifest")
    if isinstance(startup_ref, dict) and isinstance(startup_ref.get("path"), str):
        _collect_manifest_records(
            _resolve_ref_path(resolved, startup_ref["path"]),
            role=current_role,
            visited=visited,
            dedup_map=dedup_map,
        )

    overlay_files = data.get("overlay_files")
    if isinstance(overlay_files, list):
        for item in overlay_files:
            if isinstance(item, str):
                _add(item, None)
            elif isinstance(item, dict) and isinstance(item.get("path"), str):
                _add(item["path"], item.get("sha256"))

    # Level 3: startup-manifest.json -> $.application_inventory.entries[*] (kind=file) & $.app_files[*]
    inv = data.get("application_inventory")
    entries = inv.get("entries", []) if isinstance(inv, dict) else []
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("path"), str):
            continue
        kind = e.get("kind")
        if kind is not None and kind != "file":
            continue
        _add(e["path"], e.get("sha256"))

    app_files = data.get("app_files")
    if isinstance(app_files, list):
        for e in app_files:
            if isinstance(e, str):
                _add(e, None)
            elif isinstance(e, dict) and isinstance(e.get("path"), str):
                _add(e["path"], e.get("sha256"))


def load_manifest_records(manifest_json: Path) -> list[dict[str, Any]]:
    """Return deduplicated role-attributed file records preserving (role, app_root, path, sha256)."""
    dedup_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    _collect_manifest_records(Path(manifest_json), visited=set(), dedup_map=dedup_map)
    return list(dedup_map.values())


def load_manifest_paths(manifest_json: Path) -> set[str]:
    """Extract all protected file paths across group -> role -> startup manifests."""
    return {r["path"] for r in load_manifest_records(manifest_json) if r.get("path")}


def filter_safe_archive_paths(
    candidate_paths: list[str],
    git_tracked_paths: set[str],
    active_manifest_paths: set[str],
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

    def identities(paths: set[str]) -> tuple[set[str], set[str], bool]:
        lexical, canonical = set(), set()
        unresolved = False
        for raw in paths:
            path = _normalize_rel_path(raw)
            if not path:
                continue
            lexical.add(absolute(path).casefold())
            target = real(path)
            if target:
                canonical.add(target.casefold())
            else:
                unresolved = True
        return lexical, canonical, unresolved

    active, active_real, active_unresolved = identities(active_manifest_paths)
    dirty, dirty_real, dirty_unresolved = identities(dirty_git_paths or set())
    unresolved_guard = unresolved_protection or active_unresolved or dirty_unresolved
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
