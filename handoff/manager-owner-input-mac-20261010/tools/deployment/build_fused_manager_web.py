#!/usr/bin/env python3
"""Clean-build the fused web app with existing local dependencies only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path


E = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1")
WEB = E / "candidate/stage_r4_manager_r2_owner_input_r1_fused_r1/app/apps/web"
DEPS = Path("/Users/lexi/Desktop/学习/v4_app/apps/web/node_modules")
NODE = Path("/Users/lexi/.local/node-v24.19.0/bin/node")
VITE = DEPS / "vite/bin/vite.js"
LINK = WEB / "node_modules"
CONFIG = E / "tools/deployment/fused_candidate_vite_config.mjs"
LOG_DIR = E / "evidence/owner_input_r1/fusion_build"
LOG = LOG_DIR / "vite_build.log"
RECEIPT = LOG_DIR / "vite_build_receipt.json"
EXPECTED_MANAGER_WORKSPACE_SHA = "2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f"
EXPECTED_DAILY_CHANNELS_SHA = "c60254b69de369c8b50ef0ffa14dd49c802a3ae56ac4266dd9fe5f39ea40fecc"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_inventory(root: Path) -> dict[str, list[object]]:
    rows: dict[str, list[object]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            rows[path.relative_to(root).as_posix()] = ["symlink", os.readlink(path)]
        elif path.is_file():
            rows[path.relative_to(root).as_posix()] = ["file", path.stat().st_size, sha256(path)]
    return rows


def source_inventory(root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        if path.is_file() and "dist" not in path.relative_to(root).parts and "node_modules" not in path.relative_to(root).parts:
            rows[path.relative_to(root).as_posix()] = sha256(path)
    return rows


def modes_snapshot(root: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        try:
            result[str(path)] = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            pass
    return result


def make_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        try:
            mode = path.stat().st_mode
            path.chmod(mode | (stat.S_IWUSR | stat.S_IXUSR if path.is_dir() else stat.S_IWUSR))
        except FileNotFoundError:
            pass


def restore_modes(rows: dict[str, int]) -> None:
    for raw, mode in sorted(rows.items(), key=lambda item: len(Path(item[0]).parts), reverse=True):
        path = Path(raw)
        if path.exists() and not path.is_symlink():
            try:
                path.chmod(mode)
            except OSError:
                pass


def cache_snapshot(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False}
    return {
        "exists": True,
        "mtime_ns": path.stat().st_mtime_ns,
        "inventory": file_inventory(path) if path.is_dir() else {path.name: ["file", path.stat().st_size, sha256(path)]},
    }


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for path in (WEB, DEPS, NODE, VITE):
        if not path.exists():
            raise SystemExit(f"MISSING_BUILD_INPUT:{path}")
    if LINK.exists() or LINK.is_symlink():
        raise SystemExit(f"REFUSE_EXISTING_DEPENDENCY_PATH:{LINK}")
    manager_workspace = WEB / "src/api/managerWorkspace.ts"
    daily_channels = WEB / "src/manager-selection/dailyChannels.ts"
    if sha256(manager_workspace) != EXPECTED_MANAGER_WORKSPACE_SHA:
        raise SystemExit("MANAGER_WORKSPACE_SOURCE_SHA_MISMATCH")
    if sha256(daily_channels) != EXPECTED_DAILY_CHANNELS_SHA:
        raise SystemExit("DAILY_CHANNELS_SOURCE_SHA_MISMATCH")

    canonical_web = Path("/Users/lexi/Desktop/学习/v4_app/apps/web")
    package_hashes = {}
    for rel in ("package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"):
        candidate = WEB / rel
        canonical = canonical_web / rel
        if not candidate.is_file() or not canonical.is_file() or candidate.read_bytes() != canonical.read_bytes():
            raise SystemExit(f"BUILD_CONTRACT_FILE_DIFFERS_FROM_EXISTING_DEPS:{rel}")
        package_hashes[rel] = sha256(candidate)

    config_text = f'''import sourceConfig from '{WEB / "vite.config.ts"}';

const root = '{WEB}';
const cacheDir = '{LOG_DIR / "vite-cache"}';

export default {{
  ...sourceConfig,
  root,
  cacheDir,
  build: {{
    ...sourceConfig.build,
    emptyOutDir: true,
  }},
}};
'''
    if CONFIG.exists() and CONFIG.read_text(encoding="utf-8") != config_text:
        raise SystemExit(f"REFUSE_CONFIG_CONTENT_MISMATCH:{CONFIG}")
    CONFIG.write_text(config_text, encoding="utf-8")

    dist = WEB / "dist"
    before_dist = file_inventory(dist)
    source_before = source_inventory(WEB)
    canonical_cache = DEPS / ".vite"
    canonical_cache_before = cache_snapshot(canonical_cache)
    canonical_temp_cache = DEPS / ".vite-temp"
    canonical_temp_before = cache_snapshot(canonical_temp_cache)
    modes = modes_snapshot(WEB)
    command = [str(NODE), str(VITE), "build", "--config", str(CONFIG)]
    env = os.environ.copy()
    env.update({
        "PATH": f"{NODE.parent}:{env.get('PATH', '')}",
        "TMPDIR": str(LOG_DIR / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    make_writable(WEB)
    LINK.symlink_to(DEPS, target_is_directory=True)
    cleanup_error: str | None = None
    try:
        process = subprocess.run(command, cwd=WEB, env=env, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, check=False)
    finally:
        if LINK.is_symlink() and LINK.resolve() == DEPS.resolve():
            LINK.unlink()
        elif LINK.exists() or LINK.is_symlink():
            cleanup_error = "temporary_dependency_path_changed"
        restore_modes(modes)
    ended = datetime.now(timezone.utc).isoformat()
    LOG.write_text(process.stdout, encoding="utf-8")
    after_dist = file_inventory(dist)
    source_after = source_inventory(WEB)
    canonical_cache_after = cache_snapshot(canonical_cache)
    canonical_temp_after = cache_snapshot(canonical_temp_cache)
    removed = sorted(set(before_dist) - set(after_dist))
    added_or_changed = sorted(path for path in set(before_dist) | set(after_dist)
                              if before_dist.get(path) != after_dist.get(path))
    entrypoints = ("index.html", "manager-selection/index.html", "daily-research-command/index.html")
    html_refs: dict[str, list[str]] = {}
    missing_assets: list[str] = []
    for rel in entrypoints:
        path = dist / rel
        if not path.is_file():
            continue
        html = path.read_text(encoding="utf-8")
        refs = re.findall(r'(?:src|href)="([^"]*assets/[^"]+)"', html)
        html_refs[rel] = refs
        for href in refs:
            local = href.split("?", 1)[0].lstrip("/")
            if not (dist / local).is_file():
                missing_assets.append(f"{rel}:{href}")

    receipt = {
        "schema_version": "stage_r4_manager_r2_owner_input_r1_web_build.v1",
        "started_at_utc": started,
        "ended_at_utc": ended,
        "candidate_app_root": str(WEB.parent),
        "candidate_web_root": str(WEB),
        "command": command,
        "cwd": str(WEB),
        "exit_code": process.returncode,
        "log_path": str(LOG),
        "log_sha256": sha256(LOG),
        "vite_config_path": str(CONFIG),
        "vite_config_sha256": sha256(CONFIG),
        "node_path": str(NODE),
        "node_version": subprocess.run([str(NODE), "--version"], text=True,
                                       capture_output=True, check=True).stdout.strip(),
        "vite_path": str(VITE),
        "vite_version": json.loads((DEPS / "vite/package.json").read_text(encoding="utf-8"))["version"],
        "package_contract_hashes": package_hashes,
        "candidate_package_contract_matches_existing_environment": True,
        "manager_workspace_sha256": sha256(manager_workspace),
        "daily_channels_sha256": sha256(daily_channels),
        "source_unchanged_during_build": source_before == source_after,
        "source_inventory_sha256_before": hashlib.sha256(json.dumps(source_before, sort_keys=True).encode()).hexdigest(),
        "source_inventory_sha256_after": hashlib.sha256(json.dumps(source_after, sort_keys=True).encode()).hexdigest(),
        "dependency_link_path": str(LINK),
        "dependency_link_target": str(DEPS),
        "dependency_link_removed_after_build": not (LINK.exists() or LINK.is_symlink()),
        "canonical_dependency_cache_before": canonical_cache_before,
        "canonical_dependency_cache_after": canonical_cache_after,
        "canonical_dependency_cache_unchanged": canonical_cache_before == canonical_cache_after,
        "canonical_vite_temp_cache_before": canonical_temp_before,
        "canonical_vite_temp_cache_after": canonical_temp_after,
        "canonical_vite_temp_cache_unchanged": canonical_temp_before == canonical_temp_after,
        "dist_before_count": len(before_dist),
        "dist_before_inventory_sha256": hashlib.sha256(json.dumps(before_dist, sort_keys=True).encode()).hexdigest(),
        "dist_after_count": len(after_dist),
        "dist_after_bytes": sum(row[1] for row in after_dist.values() if row[0] == "file"),
        "dist_after_inventory_sha256": hashlib.sha256(json.dumps(after_dist, sort_keys=True).encode()).hexdigest(),
        "dist_added_or_changed_paths": added_or_changed,
        "dist_removed_paths": removed,
        "html_asset_references": html_refs,
        "missing_html_assets": missing_assets,
        "all_expected_entrypoints_and_assets_present": len(html_refs) == len(entrypoints) and not missing_assets,
        "build_mode": "clean_output_directory; candidate-only",
        "service_or_launchagent_changed": False,
        "canonical_source_changed": False,
        "business_state_changed": False,
        "temporary_cleanup_error": cleanup_error,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    valid = (
        process.returncode == 0
        and receipt["source_unchanged_during_build"]
        and receipt["dependency_link_removed_after_build"]
        and receipt["canonical_dependency_cache_unchanged"]
        and receipt["canonical_vite_temp_cache_unchanged"]
        and receipt["all_expected_entrypoints_and_assets_present"]
        and cleanup_error is None
    )
    print(json.dumps({
        "status": "PASS" if valid else "FAIL",
        "exit_code": process.returncode,
        "dist_before_count": len(before_dist),
        "dist_after_count": len(after_dist),
        "dist_added_or_changed_paths": added_or_changed,
        "dist_removed_paths": removed,
        "source_unchanged": receipt["source_unchanged_during_build"],
        "dependency_link_removed": receipt["dependency_link_removed_after_build"],
        "canonical_caches_unchanged": receipt["canonical_dependency_cache_unchanged"] and receipt["canonical_vite_temp_cache_unchanged"],
        "entrypoints_and_assets_present": receipt["all_expected_entrypoints_and_assets_present"],
        "receipt": str(RECEIPT),
    }, ensure_ascii=False, indent=2))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
