#!/usr/bin/env python3
"""Stdlib-only launcher review. Never invokes pytest or imports product code.

The pytest subprocess is intercepted before execution. A separate interception
returns a synthetic exit 1 solely to verify launcher exit propagation. Temporary
copies and simulated output are removed; this report is not product test evidence.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parents[2] / "delivery_hk_integrity_r1"
PRODUCTION_PREFIXES = ("stage_center", "infrastructure", "ops")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def no_product_modules():
    return not any(name == prefix or name.startswith(prefix + ".")
                   for name in sys.modules for prefix in PRODUCTION_PREFIXES)


class InterceptedBeforePytest(Exception):
    pass


def main():
    assert no_product_modules()
    input_manifest = json.loads((BUNDLE / "harness/INPUT_MANIFEST.json").read_text())
    original_manifest_sha = sha(BUNDLE / "harness/INPUT_MANIFEST.json")
    records = []
    with tempfile.TemporaryDirectory(prefix="packaging-only-", dir=HERE) as temp_name:
        temp = Path(temp_name)
        bundle = temp / "copy"
        paths = {entry["path"] for entry in input_manifest["files"]}
        paths.update({"harness/INPUT_MANIFEST.json", "candidate_identity.json",
                      "after/stage_center/_runner_parts/hk_input_validation.py"})
        for relative in paths:
            target = bundle / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BUNDLE / relative, target)
        launcher = load(bundle / "harness/run_regressions.py", "review_launcher")
        # Resolve ordinary host metadata before intercepting subprocess.run;
        # platform may otherwise invoke uname inside the exit-plumbing probe.
        launcher.platform.platform()
        launcher.verify_inputs()
        records.append({"probe": "exact_manifest_bytes", "status": "PASS", "entries": len(input_manifest["files"])})

        # Model a leftover initializer in a directory where a package was unpacked.
        # This source must neither be copied nor executed.
        for owner in ("actual_stage_owner", "canonical"):
            for package in ("stage_center", "infrastructure"):
                unlisted = bundle / "input/source" / owner / package / "__init__.py"
                unlisted.write_text("raise AssertionError('UNLISTED_INITIALIZER_MUST_NOT_EXECUTE')\n")

        captures = []
        for owner, phase in (("actual_stage_owner", "before"),
                             ("actual_stage_owner", "after"), ("canonical", "after")):
            def intercept(command, **kwargs):
                env = kwargs["env"]
                assert "PYTEST_ADDOPTS" not in env
                assert "PYTEST_PLUGINS" not in env
                assert env["PYTHONPATH"] == ""
                assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
                assert env["PYTHONDONTWRITEBYTECODE"] == "1"
                assert command[command.index("-c") + 1] == str(bundle / "harness/pytest.ini")
                assert f"--confcutdir={bundle / 'harness'}" in command
                assert command[-2:] == ["tests/test_hk_split_date_identity_closure.py", "tests/test_root_identity_probe.py"]
                assert kwargs["cwd"] == bundle / "harness"
                app = Path(env["ISSUE28_TEST_APP"])
                assert app.is_relative_to(temp / "runs")
                expected = json.loads(Path(env["ISSUE28_TEST_IMPORT_EXPECTATIONS"]).read_text())
                app_files = {str(path.relative_to(app)) for path in app.rglob("*") if path.is_file()}
                declared = {key.removeprefix("app/") for key in expected if key.startswith("app/")}
                assert app_files == declared and len(app_files) == 13
                assert not list(app.rglob("__init__.py"))
                differences = []
                for relative in app_files:
                    assert sha(app / relative) == expected["app/" + relative]
                    if sha(app / relative) != sha(bundle / "input/source" / owner / relative):
                        differences.append(relative)
                assert sorted(differences) == ([str(launcher.RELATIVE)] if phase == "after" else [])
                captures.append({"owner": owner, "phase": phase, "app": str(app), "env": env})
                raise InterceptedBeforePytest()

            argv = ["run_regressions.py", "--owner", owner, "--phase", phase,
                    "--output-dir", str(temp / "runs")]
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {
                "PYTEST_ADDOPTS": "--deselect=original_known_failure",
                "PYTEST_PLUGINS": "must_not_load_live_plugin",
                "PYTHONPATH": "/would-be-live-source-root",
            }), patch.object(launcher.subprocess, "run", side_effect=intercept):
                try:
                    launcher.main()
                except InterceptedBeforePytest:
                    pass
                else:
                    raise AssertionError("pytest interception was not reached")
            assert no_product_modules()
            records.append({"probe": "owner_allowlist_overlay_and_clean_pytest_invocation",
                            "owner": owner, "phase": phase, "status": "PASS",
                            "source_files": 13, "product_subprocess_executed": False})

        extra = bundle / "harness/support/stage_center/__init__.py"
        extra.write_text("raise AssertionError('UNLISTED_SUPPORT_MUST_NOT_EXECUTE')\n")
        try:
            launcher.verify_inputs()
        except ValueError as error:
            assert "inventory differs" in str(error)
            records.append({"probe": "unlisted_support_initializer_rejected", "status": "PASS", "error": str(error)})
        else:
            raise AssertionError("unlisted support initializer was accepted")
        extra.unlink()

        # Audit synthetic top-level module records without importing their code.
        selected = captures[-1]
        before_path = list(sys.path)
        with patch.dict(os.environ, selected["env"]):
            conftest = load(bundle / "harness/conftest.py", "review_conftest")
            try:
                for package in ("stage_center", "infrastructure"):
                    outside = temp / (package + "_untrusted_initializer.py")
                    outside.write_text("raise AssertionError('NO_PRODUCT_CODE_EXECUTED')\n")
                    module = types.ModuleType(package)
                    module.__file__ = str(outside)
                    with patch.dict(sys.modules, {package: module}):
                        try:
                            conftest.pytest_sessionfinish(None, 1)
                        except RuntimeError as error:
                            assert "escaped the isolated source roots" in str(error)
                            records.append({"probe": "top_level_package_escape_rejected", "package": package,
                                            "status": "PASS", "error": str(error)})
                        else:
                            raise AssertionError("top-level package escaped audit")
            finally:
                sys.path[:] = before_path
        assert no_product_modules()

        # Launcher plumbing only: a nonzero original-suite subprocess cannot be
        # converted into launcher success. No XML or product test is synthesized.
        def original_failure(command, **kwargs):
            assert command[-1] == "tests/test_hk_prior_observation_source_binding.py"
            return subprocess.CompletedProcess(command, 1,
                "SIMULATED_LAUNCHER_EXIT_PROBE_ONLY_NO_PYTEST_OR_PRODUCT_TEST_EXECUTED\n")
        argv = ["run_regressions.py", "--owner", "actual_stage_owner", "--suite", "original",
                "--output-dir", str(temp / "exit-runs")]
        with patch.object(sys, "argv", argv), patch.object(launcher.subprocess, "run", side_effect=original_failure), contextlib.redirect_stdout(io.StringIO()):
            exit_code = launcher.main()
        assert exit_code == 1
        records.append({"probe": "original_nonzero_exit_is_preserved", "status": "PASS", "simulated_subprocess_exit": 1,
                        "launcher_exit": exit_code, "product_subprocess_executed": False})
        assert no_product_modules()

    assert original_manifest_sha == sha(BUNDLE / "harness/INPUT_MANIFEST.json")
    report = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "scope": "PACKAGING_LAUNCHER_ISOLATION_ONLY_NO_PRODUCT_TEST_EXECUTION",
        "status": "PASS", "product_tests_executed": 0, "product_modules_imported": 0,
        "python": sys.version,
        "reviewed_files": {relative: sha(BUNDLE / relative) for relative in (
            "harness/run_regressions.py", "harness/conftest.py", "harness/pytest.ini",
            "harness/INPUT_MANIFEST.json", "after/stage_center/_runner_parts/hk_input_validation.py")},
        "checks": records,
        "temporary_copy_removed": True,
    }
    (HERE / "LAUNCHER_ISOLATION_PROBES.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
