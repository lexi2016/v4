#!/usr/bin/env python3
"""Run narrow fused-candidate type, UI, Python and import-identity checks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


E = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1")
APP = E / "candidate/stage_r4_manager_r2_owner_input_r1_fused_r1/app"
WEB = APP / "apps/web"
TESTS = E / "tests/owner_input_r1/package/tests/tests"
TEST_APP_CONTEXT = E / "tests/owner_input_r1/app_context"
UI_HARNESS = E / "tests/fused_candidate_ui_20261010_r1_retry4"
UI_TEST_SOURCE = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_DEPLOY_20261009/candidate/three_channel_r1/app")
UI_WEB = UI_HARNESS / "apps/web"
PYTHON = Path("/Users/lexi/Desktop/学习/v4_app/.venv/bin/python")
DEPS = Path("/Users/lexi/Desktop/学习/v4_app/apps/web/node_modules")
NODE = Path("/Users/lexi/.local/node-v24.19.0/bin/node")
VITEST = DEPS / "vitest/vitest.mjs"
TSC = DEPS / ".bin/vue-tsc"
LINK = WEB / "node_modules"
RUN_ROOT = E / "evidence/owner_input_r1/fused_targeted_checks_20261010_r1_retry4"
LOG_DIR = RUN_ROOT / "logs"
CACHE_DIR = RUN_ROOT / "vite-cache"
TMP_DIR = RUN_ROOT / "tmp"
RECEIPT = RUN_ROOT / "fused_targeted_checks_receipt.json"
TSCONFIG = E / "tools/deployment/tsconfig_fused_manager_sources.json"
VITEST_CONFIG = E / "tools/deployment/fused_candidate_vitest_config_retry4.mjs"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def app_inventory(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if "__pycache__" in path.parts or ".pytest_cache" in path.parts or path.suffix == ".pyc":
            continue
        rows.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
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


def parse_junit(path: Path) -> dict[str, int] | None:
    if not path.is_file():
        return None
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    return {
        "tests": len(cases),
        "failures": len(root.findall(".//failure")),
        "errors": len(root.findall(".//error")),
        "skipped": len(root.findall(".//skipped")),
    }


def cache_snapshot(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False}
    return {"exists": True, "mtime_ns": path.stat().st_mtime_ns, "mode": stat.S_IMODE(path.stat().st_mode)}


def prepare_ui_harness() -> None:
    if UI_HARNESS.exists():
        raise SystemExit(f"REFUSE_EXISTING_UI_HARNESS:{UI_HARNESS}")
    for path in (UI_TEST_SOURCE,):
        if not path.exists():
            raise SystemExit(f"MISSING_UI_HARNESS_INPUT:{path}")
    api = UI_WEB / "src/api"
    selection = UI_WEB / "src/manager-selection"
    adapters = selection / "adapters"
    tests = UI_HARNESS / "tests"
    api.mkdir(parents=True)
    adapters.mkdir(parents=True)
    tests.mkdir()

    source_web = UI_TEST_SOURCE / "apps/web"
    for name in ("managerWorkspace.threeChannel.spec.ts", "managerWorkspace.dailyAutomation.spec.ts"):
        shutil.copy2(source_web / "src/api" / name, api / name)
    (api / "managerWorkspace.ts").symlink_to(WEB / "src/api/managerWorkspace.ts")
    (adapters / "workspaceDecision.ts").symlink_to(WEB / "src/manager-selection/adapters/workspaceDecision.ts")
    (selection / "dailyChannels.ts").symlink_to(WEB / "src/manager-selection/dailyChannels.ts")
    shutil.copy2(source_web / "src/manager-selection/dailyChannels.testHelper.ts", selection / "dailyChannels.testHelper.ts")
    for name in (
        "manager_daily_ui_owner_fixture.py",
        "test_manager_us_mapping_isolation_20261008.py",
        "manager_three_channel_ui_fixture.py",
        "test_manager_three_channel_hk_reader.py",
        "r3_scoped_loader.py",
    ):
        shutil.copy2(UI_TEST_SOURCE / "tests" / name, tests / name)
    three_channel_fixture = tests / "manager_three_channel_ui_fixture.py"
    fixture_text = three_channel_fixture.read_text(encoding="utf-8")
    resolved_owner = '"owner_module": str(Path(owner.__file__).resolve()),'
    lexical_owner = '"owner_module": str(ROOT / "upstreams/v3_shared_data/shared_data/hk_security_master.py"),'
    if fixture_text.count(resolved_owner) != 1:
        raise SystemExit("UI_FIXTURE_OWNER_PATH_SOURCE_PATTERN_MISMATCH")
    three_channel_fixture.write_text(fixture_text.replace(resolved_owner, lexical_owner), encoding="utf-8")
    for name in ("contracts", "domains", "infrastructure", "stage_center", "upstreams", "v3_shared_data", "v4"):
        (UI_HARNESS / name).symlink_to(APP / name, target_is_directory=True)
    (UI_HARNESS / "apps/api").symlink_to(APP / "apps/api", target_is_directory=True)
    (UI_HARNESS / "apps/__init__.py").symlink_to(APP / "apps/__init__.py")

    # The UI tests import these candidate modules through symlinks, so pin their
    # exact bytes before execution and keep all test-only files outside the app.
    symlinked = {
        "apps/web/src/api/managerWorkspace.ts": WEB / "src/api/managerWorkspace.ts",
        "apps/web/src/manager-selection/adapters/workspaceDecision.ts": WEB / "src/manager-selection/adapters/workspaceDecision.ts",
        "apps/web/src/manager-selection/dailyChannels.ts": WEB / "src/manager-selection/dailyChannels.ts",
    }
    for relative, target in symlinked.items():
        link = UI_HARNESS / relative
        if not link.is_symlink() or link.resolve() != target.resolve():
            raise SystemExit(f"UI_SOURCE_BINDING_MISMATCH:{relative}")

    vitest_config = f'''export default {{
  root: {json.dumps(str(UI_WEB))},
  cacheDir: {json.dumps(str(CACHE_DIR))},
  server: {{ fs: {{ allow: [{json.dumps(str(E))}] }} }},
  test: {{ environment: "jsdom", include: ["src/api/managerWorkspace.threeChannel.spec.ts", "src/api/managerWorkspace.dailyAutomation.spec.ts"] }}
}};
'''
    VITEST_CONFIG.write_text(vitest_config, encoding="utf-8")


def run_command(name: str, command: list[str], cwd: Path, env: dict[str, str], junit: Path | None = None) -> dict[str, object]:
    started = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(command, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    ended = datetime.now(timezone.utc).isoformat()
    log = LOG_DIR / f"{name}.log"
    log.write_text(result.stdout, encoding="utf-8", errors="replace")
    return {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "started_at_utc": started,
        "ended_at_utc": ended,
        "exit_code": result.returncode,
        "log_path": str(log),
        "log_sha256": sha256(log),
        "junit_path": str(junit) if junit else None,
        "junit_sha256": sha256(junit) if junit and junit.is_file() else None,
        "junit": parse_junit(junit) if junit else None,
    }


def main() -> int:
    if RUN_ROOT.exists():
        raise SystemExit(f"REFUSE_EXISTING_RUN_ROOT:{RUN_ROOT}")
    for path in (APP, TESTS, TEST_APP_CONTEXT, PYTHON, DEPS, NODE, VITEST, TSC, UI_TEST_SOURCE):
        if not path.exists():
            raise SystemExit(f"MISSING_CHECK_INPUT:{path}")
    if LINK.exists() or LINK.is_symlink():
        raise SystemExit(f"REFUSE_EXISTING_DEPENDENCY_PATH:{LINK}")
    RUN_ROOT.mkdir(parents=True)
    LOG_DIR.mkdir()
    CACHE_DIR.mkdir()
    TMP_DIR.mkdir()

    typecheck_config = {
        "extends": str(WEB / "tsconfig.json"),
        "compilerOptions": {"incremental": False, "noEmit": True, "types": []},
        "files": [str(WEB / "src/api/managerWorkspace.ts"), str(WEB / "src/manager-selection/dailyChannels.ts")],
        "include": [],
    }
    TSCONFIG.write_text(json.dumps(typecheck_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prepare_ui_harness()
    ui_bindings = [
        {"harness_path": str(UI_HARNESS / relative), "candidate_path": str(target), "sha256": sha256(target)}
        for relative, target in (
            ("apps/web/src/api/managerWorkspace.ts", WEB / "src/api/managerWorkspace.ts"),
            ("apps/web/src/manager-selection/adapters/workspaceDecision.ts", WEB / "src/manager-selection/adapters/workspaceDecision.ts"),
            ("apps/web/src/manager-selection/dailyChannels.ts", WEB / "src/manager-selection/dailyChannels.ts"),
        )
    ]

    import_code = """
import hashlib, importlib, json, sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(); sys.path.insert(0,str(root))
names=['apps.api.v35_api.app','apps.api.v35_api.manager_research_router','stage_center.consumer','stage_center.research_read_binding','v4.manager_research.workspace','v4.manager_research.connect_selection','v4.manager_research.service']
rows=[]
for name in names:
 m=importlib.import_module(name); p=Path(m.__file__).resolve(); raw=p.read_bytes()
 rows.append({'module':name,'file':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'under_candidate':p.is_relative_to(root)})
print(json.dumps(rows,ensure_ascii=False))
"""

    env = os.environ.copy()
    removed_env_keys = sorted(key for key in env if key.startswith(("V4_", "V35_")))
    for key in removed_env_keys:
        env.pop(key, None)
    env.update({
        "PATH": f"{PYTHON.parent}:{NODE.parent}:{env.get('PATH', '')}",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(TMP_DIR),
        "V4_TEST_APP_ROOT": str(TEST_APP_CONTEXT),
        "PLAN_AUDIT_APP_ROOT": str(APP),
        "PYTHONPATH": os.pathsep.join((str(APP), str(TESTS))),
    })

    before_inventory = app_inventory(APP)
    canonical_cache = DEPS / ".vite"
    canonical_temp = DEPS / ".vite-temp"
    cache_before = cache_snapshot(canonical_cache)
    temp_before = cache_snapshot(canonical_temp)
    results: list[dict[str, object]] = []

    import_result = run_command("candidate_import_identity", [str(PYTHON), "-B", "-c", import_code, str(APP)], APP, env)
    results.append(import_result)
    import_log = Path(import_result["log_path"])
    if import_result["exit_code"] != 0:
        imports = []
    else:
        imports = json.loads(import_log.read_text(encoding="utf-8").splitlines()[-1])

    modes = modes_snapshot(WEB)
    make_writable(WEB)
    LINK.symlink_to(DEPS, target_is_directory=True)
    ui_link_removed = False
    try:
        typecheck = run_command("changed_manager_sources_typecheck", [str(TSC), "--noEmit", "--project", str(TSCONFIG)], WEB, env)
        results.append(typecheck)
        ui_link = UI_WEB / "node_modules"
        if ui_link.exists() or ui_link.is_symlink():
            raise SystemExit(f"REFUSE_UI_HARNESS_DEPENDENCY_PATH:{ui_link}")
        ui_link.symlink_to(DEPS, target_is_directory=True)
        ui_env = dict(env)
        ui_env.update({
            "V4_TEST_SOURCE_ROOT": str(UI_HARNESS),
            "V4_TEST_PYTHON": str(PYTHON),
            "PYTHONPATH": os.pathsep.join((str(APP), str(TESTS), str(UI_HARNESS / "tests"))),
        })
        try:
            ui_tests = run_command("manager_selection_and_daily_automation_vitest", [str(NODE), str(VITEST), "run", "--config", str(VITEST_CONFIG)], UI_WEB, ui_env)
            results.append(ui_tests)
        finally:
            if ui_link.is_symlink() and ui_link.resolve() == DEPS.resolve():
                ui_link.unlink()
            ui_link_removed = not (ui_link.exists() or ui_link.is_symlink())
    finally:
        if LINK.is_symlink() and LINK.resolve() == DEPS.resolve():
            LINK.unlink()
        restore_modes(modes)

    test_run = LOG_DIR / "pytest_manager_app_plan_and_hk_wiring"
    test_run.mkdir()
    test_junit = test_run / "junit.xml"
    test_env = dict(env)
    test_env["TMPDIR"] = str(TMP_DIR)
    test_env["PYTHONPATH"] = os.pathsep.join((str(APP), str(TESTS)))
    python_tests = [
        str(TESTS / "test_manager_app_plan_identity_20261009.py"),
        str(TESTS / "test_manager_hk_authority_app_wiring_20261009.py"),
    ]
    pytest_command = [str(PYTHON), "-B", "-m", "pytest", "-q", "--tb=short", "--color=no",
                      "-p", "no:cacheprovider", f"--basetemp={TMP_DIR / 'pytest'}",
                      f"--junitxml={test_junit}", *python_tests]
    results.append(run_command("fused_candidate_python_app_tests", pytest_command, APP, test_env, test_junit))

    after_inventory = app_inventory(APP)
    source_drift = []
    before_map = {row["path"]: row for row in before_inventory}
    after_map = {row["path"]: row for row in after_inventory}
    for rel in sorted(set(before_map) | set(after_map)):
        if before_map.get(rel) != after_map.get(rel):
            source_drift.append({"path": rel, "before": before_map.get(rel), "after": after_map.get(rel)})
    cache_after = cache_snapshot(canonical_cache)
    temp_after = cache_snapshot(canonical_temp)
    ui_bindings_valid = all(
        Path(row["harness_path"]).is_symlink()
        and Path(row["harness_path"]).resolve() == Path(row["candidate_path"]).resolve()
        and sha256(Path(row["harness_path"])) == row["sha256"]
        for row in ui_bindings
    )
    all_zero = all(result["exit_code"] == 0 for result in results)
    all_imports_candidate = bool(imports) and all(row["under_candidate"] for row in imports)
    receipt = {
        "schema_version": "stage_r4_manager_r2_owner_input_r1_fused_targeted_checks.v1",
        "status": "PASS" if all_zero and all_imports_candidate and ui_bindings_valid and ui_link_removed and not source_drift and cache_before == cache_after and temp_before == temp_after else "FAIL",
        "candidate_app_root": str(APP),
        "environment": {
            "python_path": str(PYTHON),
            "python_version": subprocess.run([str(PYTHON), "-B", "--version"], capture_output=True, text=True, check=True).stdout.strip(),
            "node_path": str(NODE),
            "node_version": subprocess.run([str(NODE), "--version"], capture_output=True, text=True, check=True).stdout.strip(),
            "vite_version": json.loads((DEPS / "vite/package.json").read_text(encoding="utf-8"))["version"],
            "pytest_version": subprocess.run([str(PYTHON), "-B", "-m", "pytest", "--version"], capture_output=True, text=True, check=True).stdout.strip(),
        },
        "removed_project_environment_key_names": removed_env_keys,
        "import_identity": {"command_log": import_result["log_path"], "modules": imports,
                            "all_modules_loaded_from_candidate": all_imports_candidate},
        "commands": results,
        "temporary_dependency_link": {"path": str(LINK), "target": str(DEPS), "removed": not (LINK.exists() or LINK.is_symlink())},
        "ui_test_source_bindings": ui_bindings,
        "ui_test_source_bindings_valid": ui_bindings_valid,
        "ui_test_support_root": str(UI_HARNESS),
        "ui_test_support_files_sha256": {
            str(path.relative_to(UI_HARNESS)): sha256(path)
            for path in sorted(UI_HARNESS.rglob("*")) if path.is_file() and not path.is_symlink()
        },
        "ui_harness_dependency_link": {"path": str(UI_WEB / "node_modules"), "target": str(DEPS), "removed": ui_link_removed},
        "canonical_dependency_caches_before": {"vite": cache_before, "vite_temp": temp_before},
        "canonical_dependency_caches_after": {"vite": cache_after, "vite_temp": temp_after},
        "canonical_dependency_caches_unchanged": cache_before == cache_after and temp_before == temp_after,
        "candidate_tree_inventory_sha256_before": hashlib.sha256(json.dumps(before_inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "candidate_tree_inventory_sha256_after": hashlib.sha256(json.dumps(after_inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "candidate_tree_unchanged_during_checks": not source_drift,
        "candidate_tree_drift": source_drift,
        "all_command_exit_codes_zero": all_zero,
        "service_or_launchagent_changed": False,
        "business_state_changed": False,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": receipt["status"],
        "command_results": [{"name": row["name"], "exit_code": row["exit_code"], "junit": row["junit"]} for row in results],
        "imports_candidate": all_imports_candidate,
        "source_tree_unchanged": not source_drift,
        "dependency_link_removed": receipt["temporary_dependency_link"]["removed"],
        "canonical_dependency_caches_unchanged": receipt["canonical_dependency_caches_unchanged"],
        "receipt": str(RECEIPT),
    }, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
