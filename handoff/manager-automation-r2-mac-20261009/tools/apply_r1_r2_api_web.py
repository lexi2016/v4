#!/usr/bin/env python3
"""Apply only the R1/R2 API+web deltas and manager tests to isolated snapshots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from datetime import datetime, timezone

E = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_AUTOMATION_R2_MAC_20261009")
API = E / "candidate/api"
WEB = E / "candidate/web"
TEST = E / "candidate/test"
R1 = E / "incoming/r1"
R2 = E / "incoming/r2"
R1_MANIFEST = R1 / "source_manifest.json"
R2_MANIFEST = R2 / "source_manifest.json"
R2_TEST_LINEAGE = R2 / "evidence/test_dependency_lineage.json"
PYTHON = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python")
PARITY_SOURCE = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/incoming/repair/after/tests/test_manager_announcement_parity_20261008.py")
RECEIPT = E / "evidence/receipts/r2_api_web_cumulative_application.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_root(profile: str, path: str) -> Path:
    if profile == "api" or (profile == "tests" and not path.startswith("apps/web/")):
        return API
    return WEB


def package_root(name: str) -> Path:
    return R1 if name == "r1" else R2


def selected_rows(name: str, manifest: dict) -> list[dict]:
    selected = []
    for row in manifest["files"]:
        profile, path = row["profile"], row["path"]
        if profile in ("api", "web"):
            selected.append(row)
        elif name == "r2" and profile == "tests":
            selected.append(row)
        elif name == "r1" and profile == "tests":
            # Use additive manager/API/web test inputs only. HK-only tests and
            # modified legacy tests with missing baseline bytes are out of scope.
            if row["before_sha256"] is None and not path.endswith(("test_hk_daily_publication_chain.py",)):
                selected.append(row)
    return selected


def expected_payload(package: Path, row: dict) -> tuple[Path, Path]:
    patch = package / row["patch_path"]
    payload = package / row["after_path"]
    if digest(patch) != row["patch_sha256"] or patch.stat().st_size != row["patch_bytes"]:
        raise RuntimeError(f"patch identity mismatch: {row['patch_path']}")
    if digest(payload) != row["after_sha256"] or payload.stat().st_size != row["after_bytes"]:
        raise RuntimeError(f"after payload identity mismatch: {row['after_path']}")
    return patch, payload


def make_parent_dirs_writable(root: Path, relative: str) -> list[dict]:
    changed = []
    current = root
    for part in Path(relative).parts[:-1]:
        current = current / part
        if not current.exists() or not current.is_dir():
            continue
        mode = stat.S_IMODE(current.stat().st_mode)
        if not (mode & stat.S_IWUSR):
            os.chmod(current, mode | stat.S_IWUSR)
            changed.append({"path": str(current), "mode_before": oct(mode),
                            "mode_after": oct(mode | stat.S_IWUSR)})
    return changed


def make_tree_dirs_writable(root: Path) -> list[dict]:
    changed = []
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        if current.is_symlink():
            continue
        mode = stat.S_IMODE(current.stat().st_mode)
        if not (mode & stat.S_IWUSR):
            os.chmod(current, mode | stat.S_IWUSR)
            changed.append({"path": str(current), "mode_before": oct(mode),
                            "mode_after": oct(mode | stat.S_IWUSR)})
    return changed


def run_git_apply(root: Path, patches: list[Path], check: bool) -> dict:
    cmd = ["git", "-C", str(root), "apply"]
    if check:
        cmd.append("--check")
    cmd.extend(str(patch) for patch in patches)
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(
            f"git apply {'--check ' if check else ''}failed at {root}: "
            f"exit={result.returncode}; stderr={result.stderr.strip()}; stdout={result.stdout.strip()}"
        )
    return {"cwd": str(root), "argv": cmd, "exit_code": result.returncode}


def run_verifier(stage: str, profile: str, source: Path, package: Path) -> dict:
    verifier = package / "tools/verify_delivery.py"
    report = E / f"evidence/{stage}_{profile}_after.json"
    cmd = [str(PYTHON), str(verifier), "--source-root", str(source),
           "--profile", profile, "--against", "after", "--report", str(report)]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if result.returncode:
        raise RuntimeError(
            f"delivery verifier failed stage={stage} profile={profile}: "
            f"exit={result.returncode}; stderr={result.stderr.strip()}; stdout={result.stdout.strip()}"
        )
    return {"argv": cmd, "exit_code": result.returncode,
            "stdout": result.stdout.strip(), "report": str(report)}


def apply_stage(name: str, manifest: dict) -> dict:
    package = package_root(name)
    rows = selected_rows(name, manifest)
    grouped: dict[Path, list[tuple[dict, Path]]] = {API: [], WEB: []}
    for row in rows:
        root = source_root(row["profile"], row["path"])
        target = root / row["path"]
        actual = digest(target) if target.is_file() else None
        if actual != row["before_sha256"]:
            raise RuntimeError(
                f"{name} exact preimage mismatch profile={row['profile']} path={row['path']} "
                f"expected={row['before_sha256']!r} actual={actual!r}"
            )
        patch, _payload = expected_payload(package, row)
        grouped[root].append((row, patch))

    checks, applies, after = [], [], []
    patch_groups = [(root, entries) for root, entries in grouped.items() if entries]
    for root, entries in patch_groups:
        checks.append(run_git_apply(root, [patch for _row, patch in entries], check=True))
    directory_mode_changes = []
    for root, entries in patch_groups:
        for row, _patch in entries:
            directory_mode_changes.extend(make_parent_dirs_writable(root, row["path"]))
    for root, entries in patch_groups:
        applies.append(run_git_apply(root, [patch for _row, patch in entries], check=False))
    for root, entries in patch_groups:
        for row, _patch in entries:
            target = root / row["path"]
            actual = digest(target) if target.is_file() else None
            if actual != row["after_sha256"]:
                raise RuntimeError(
                    f"{name} after SHA mismatch profile={row['profile']} path={row['path']} "
                    f"expected={row['after_sha256']} actual={actual!r}"
                )
            after.append({"profile": row["profile"], "path": row["path"],
                          "sha256": actual, "bytes": target.stat().st_size})
    return {
        "selected_rows": [{"profile": r["profile"], "path": r["path"],
                           "before_sha256": r["before_sha256"],
                           "after_sha256": r["after_sha256"]} for r in rows],
        "git_apply_checks": checks,
        "git_apply": applies,
        "candidate_directory_mode_changes": directory_mode_changes,
        "after_identities": after,
    }


def restore_fixed_test_dependency(lineage: dict) -> dict:
    row = next((r for r in lineage["files"]
                if r["path"] == "tests/test_manager_announcement_parity_20261008.py"), None)
    if row is None:
        raise RuntimeError("fixed R2 test dependency declaration lacks announcement parity fixture")
    target = API / row["path"]
    if target.exists():
        actual = digest(target)
        if actual != row["sha256"]:
            raise RuntimeError(f"existing test dependency differs from pin: {target} {actual}")
        status = "ALREADY_PRESENT_MATCHES_FIXED_PIN"
    else:
        actual = digest(PARITY_SOURCE) if PARITY_SOURCE.is_file() else None
        if actual != row["sha256"] or PARITY_SOURCE.stat().st_size != row["bytes"]:
            raise RuntimeError(
                f"fixed dependency source unavailable or differs: expected={row['sha256']} actual={actual!r}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PARITY_SOURCE, target)
        status = "RESTORED_TO_ISOLATED_TEST_TREE_FROM_FIXED_PIN"
    return {
        "path": row["path"], "sha256": digest(target), "bytes": target.stat().st_size,
        "declared_source_commit": row["source_commit"],
        "declared_source_paths": row["source_paths"],
        "actual_package_source": str(PARITY_SOURCE),
        "status": status,
    }


def verify_retained_r1(r2_manifest: dict) -> list[dict]:
    checked = []
    for row in r2_manifest.get("retained_r1_records", []):
        if row["profile"] not in ("api", "web"):
            continue
        root = API if row["profile"] == "api" else WEB
        target = root / row["path"]
        actual = digest(target) if target.is_file() else None
        if actual != row["sha256"]:
            raise RuntimeError(
                f"retained R1 API/web identity mismatch profile={row['profile']} "
                f"path={row['path']} expected={row['sha256']} actual={actual!r}"
            )
        checked.append({"profile": row["profile"], "path": row["path"],
                        "sha256": actual, "role": row.get("role")})
    return checked


def main() -> None:
    for path in (API, WEB, R1_MANIFEST, R2_MANIFEST, R2_TEST_LINEAGE, PYTHON):
        if not path.exists():
            raise SystemExit(f"required candidate/input missing: {path}")
    if RECEIPT.exists():
        raise SystemExit(f"receipt exists; refusing overwrite: {RECEIPT}")
    if TEST.exists():
        raise SystemExit(f"test assembly already exists; refusing overwrite: {TEST}")

    r1_manifest, r2_manifest = load(R1_MANIFEST), load(R2_MANIFEST)
    # Check web test dependencies from their fixed R2 declaration. Copy only if absent.
    restored_web = []
    for row in load(R2 / "required_dependencies.json")["restored_web_dependencies"]:
        target = WEB / row["path"]
        expected = row["sha256"]
        if target.is_file():
            actual = digest(target)
            if actual != expected or target.stat().st_size != row["bytes"]:
                raise RuntimeError(f"web dependency differs from fixed pin: {target} {actual}")
            status = "ALREADY_PRESENT_MATCHES_FIXED_PIN"
        else:
            payload = R2 / row["package_path"]
            if digest(payload) != expected or payload.stat().st_size != row["bytes"]:
                raise RuntimeError(f"packaged web dependency differs from fixed pin: {payload}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(payload, target)
            status = "RESTORED_TO_ISOLATED_TEST_TREE_FROM_FIXED_PIN"
        restored_web.append({"path": row["path"], "sha256": digest(target),
                             "bytes": target.stat().st_size,
                             "declared_source_commit": row["source_commit"],
                             "declared_source_path": row["source_path"], "status": status})

    r1_application = apply_stage("r1", r1_manifest)
    r1_verification = {
        "api": run_verifier("r1", "api", API, R1),
        "web": run_verifier("r1", "web", WEB, R1),
    }
    restored_python = restore_fixed_test_dependency(load(R2_TEST_LINEAGE))
    r2_application = apply_stage("r2", r2_manifest)
    r2_api_web_verification = {
        "api": run_verifier("r2", "api", API, R2),
        "web": run_verifier("r2", "web", WEB, R2),
    }
    shutil.copytree(API, TEST, symlinks=True, copy_function=shutil.copy2)
    test_tree_mode_changes = make_tree_dirs_writable(TEST)
    web_build_mode_changes = make_tree_dirs_writable(WEB)
    combined_web = TEST / "apps/web"
    if combined_web.exists():
        shutil.rmtree(combined_web)
    shutil.copytree(WEB / "apps/web", combined_web, symlinks=True, copy_function=shutil.copy2)
    r2_test_verification = run_verifier("r2", "tests", TEST, R2)
    retained = verify_retained_r1(r2_manifest)

    omitted_r1_tests = [
        {"path": row["path"], "before_sha256": row["before_sha256"],
         "reason": ("HK-only test profile excluded by frozen scope" if "hk_" in row["path"]
                    else "legacy test before bytes absent from scoped API snapshot; excluded from minimum R2 canary")}
        for row in r1_manifest["files"]
        if row["profile"] == "tests"
        and row not in selected_rows("r1", r1_manifest)
    ]
    receipt = {
        "schema_version": "v4.manager_r2_api_web_cumulative_application.v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "ISOLATED_CANDIDATE_ONLY; R1 API+WEB THEN R2 API+WEB; NO HK PRODUCTION PROFILES",
        "r1_source_manifest_sha256": digest(R1_MANIFEST),
        "r2_source_manifest_sha256": digest(R2_MANIFEST),
        "r1_commit": r1_manifest.get("local_comparison_commit"),
        "r2_parent_commit": r2_manifest.get("base_commit"),
        "r2_commit": "6a2fa48faf1da0a7d0d1715b3a4a40f55249b64c",
        "r1_application": r1_application,
        "r1_after_verification": r1_verification,
        "fixed_test_dependencies": {
            "web": restored_web,
            "python": [restored_python],
        },
        "r2_application": r2_application,
        "r2_after_verification": {**r2_api_web_verification, "tests": r2_test_verification},
        "isolated_test_assembly": {"root": str(TEST), "api_source": str(API),
                                   "web_source": str(WEB / "apps/web"),
                                   "web_component_overlay": "COPIED_EXACT_POSTPATCH_WEB_TREE",
                                   "candidate_directory_mode_changes": test_tree_mode_changes},
        "web_build_directory_mode_changes": web_build_mode_changes,
        "retained_r1_api_web_records": retained,
        "r1_test_files_omitted": omitted_r1_tests,
        "hk_profiles": "NOT_APPLIED",
        "production_or_service_actions": "NONE",
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "receipt": str(RECEIPT),
        "r1_api_web_files": len([r for r in r1_application["selected_rows"] if r["profile"] in ("api", "web")]),
        "r1_manager_test_files": len([r for r in r1_application["selected_rows"] if r["profile"] == "tests"]),
        "r2_files": len(r2_application["selected_rows"]),
        "retained_r1_api_web_files": len(retained),
        "r1_verify": "PASS_API_AND_WEB",
        "r2_verify": "PASS_API_WEB_AND_TESTS",
        "test_assembly": str(TEST),
        "hk_profiles": "NOT_APPLIED",
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
