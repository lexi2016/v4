#!/usr/bin/env python3
"""Run exactly the 57 offline four-issue regressions in a fresh source copy.

Use an isolated source checkout, never a live application/state directory.
The checkout must already have the four after files and 16 unchanged R2 files.
This tool neither applies a patch nor runs an operator capture command.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import traceback
from types import ModuleType
import xml.etree.ElementTree as ET

PACKAGE = Path(__file__).resolve().parents[1]
TEST_GROUPS = {
    "test_manager_four_app_wiring.py": 6,
    "test_manager_four_announcement_integration.py": 8,
    "test_manager_four_hk_readers.py": 30,
    "test_manager_four_plan_owner_readback.py": 13,
}
EXPECTED_TOTAL = sum(TEST_GROUPS.values())
SUPPORT_CLI = "tests/support/app/ops/run_manager_daily_announcement.py"
SUPPORT_CLI_SHA256 = "aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38"
SUPPORT_HELPER = "tests/support/app/tests/test_manager_us_mapping_research.py"
EXCLUDED_DIRECTORIES = frozenset({
    ".git", "venv", ".venv", "test_env", "node_modules", "dist", "__pycache__",
    ".pytest_cache", ".runtime", "runtime", "state", "data", "output", "outputs",
    "logs", "artifacts", "results", "captures", "receipts",
})


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("MODULE_SPEC_UNAVAILABLE:" + name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _verifier():
    return _load_module("_four_delivery_verifier", PACKAGE / "tools/verify_delivery.py")


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _source_files(root: Path):
    """Walk source bytes without following any link; skip named dependency/state trees."""
    def walk(folder: Path):
        for path in sorted(folder.iterdir()):
            # node_modules is often a dependency symlink; never traverse it.
            if path.name in EXCLUDED_DIRECTORIES and (path.is_symlink() or path.is_dir()):
                continue
            if path.is_symlink():
                raise ValueError("UNEXPECTED_SOURCE_SYMLINK:" + path.relative_to(root).as_posix())
            if path.is_dir():
                yield from walk(path)
            elif stat.S_ISREG(path.stat().st_mode):
                if path.suffix not in {".pyc", ".pyo"}:
                    yield path
            else:
                raise ValueError("SOURCE_ENTRY_NOT_REGULAR:" + path.relative_to(root).as_posix())
    yield from walk(root)


def _snapshot(root: Path, verifier) -> dict:
    return {path.relative_to(root).as_posix(): verifier.file_identity(path)
            for path in _source_files(root)}


def _differences(expected: dict, actual: dict) -> dict:
    return {
        "missing": sorted(expected.keys() - actual.keys()),
        "added": sorted(actual.keys() - expected.keys()),
        "changed": sorted(key for key in expected.keys() & actual.keys() if expected[key] != actual[key]),
    }


def _changed(differences: dict) -> bool:
    return any(differences.values())


def _versions() -> dict:
    dependencies = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            dependencies[name] = dist.version
    return {"python_version": sys.version, "python_executable": sys.executable,
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(), "dependencies": dict(sorted(dependencies.items()))}


def _install_guard(protected_roots: tuple[Path, ...], events: list, executed: set) -> None:
    """Block explicit absolute source writes and sockets; record executed files.

    This is deliberately not a descriptor-aware filesystem sandbox. The real
    owners use dir_fd and fdopen for safe temporary writes. Those operations
    remain available; copied-source and original-source SHA checks are the
    regression's content-preservation gate.
    """
    def protected(value) -> bool:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        path = Path(os.fsdecode(value))
        # open audit events omit dir_fd. Do not guess the base for a relative
        # target or misclassify legitimate owner writes through descriptors.
        if not path.is_absolute():
            return False
        path = path.resolve(strict=False)
        return any(path == root or path.is_relative_to(root) for root in protected_roots)

    def audit(event, args):
        if event == "exec":
            filename = getattr(args[0], "co_filename", "")
            if filename and not filename.startswith("<"):
                path = Path(filename).absolute().resolve(strict=False)
                if path.is_relative_to(protected_roots[1]):
                    executed.add(str(path))
        if event == "socket.connect":
            events.append({"event": event, "reason": "OFFLINE_TEST_NETWORK_ATTEMPT"})
            raise PermissionError("OFFLINE_TEST_NETWORK_ATTEMPT")
        paths = []
        if event == "open":
            mode, flags = args[1], args[2]
            writing = ((isinstance(mode, str) and any(char in mode for char in "wax+"))
                       or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT
                                                               | os.O_TRUNC | os.O_APPEND)))
            if writing:
                paths = args[:1]
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown",
                       "os.truncate", "os.utime"}:
            paths = args[:1]
        elif event in {"os.rename", "os.link"}:
            paths = args[:2]
        elif event == "os.symlink":
            paths = args[1:2]
        for path in paths:
            if protected(path):
                events.append({"event": event, "path": os.fsdecode(path),
                               "reason": "PROTECTED_SOURCE_WRITE_ATTEMPT"})
                raise PermissionError("PROTECTED_SOURCE_WRITE_ATTEMPT:" + os.fsdecode(path))

    sys.addaudithook(audit)


def _worker(out: Path) -> int:
    config = json.loads((out / "source_identity.json").read_text(encoding="utf-8"))
    original = Path(config["original_source_root"])
    execution = Path(config["execution_source_root"])
    verifier = _verifier()
    receipt = {"status": "FAIL", "pytest_exit_code": None, "expected_tests": EXPECTED_TOTAL,
               "test_groups": {}, "loaded_modules": [], "module_identity_errors": [],
               "guard_events": [], "executed_source_files": [], **_versions()}
    module_records, executed = {}, set()
    source_expected = {row["path"]: {"sha256": row["sha256"], "bytes": row["bytes"]}
                       for row in config["execution_files"]}
    support = {
        str((PACKAGE / SUPPORT_CLI).resolve()): "test_only_prior_delivered_cli",
        str((PACKAGE / SUPPORT_HELPER).resolve()): "test_only_fixture_helper",
    }
    business_names = {path.name for path in execution.iterdir()
                      if path.is_dir() and path.name.isidentifier() and path.name != "tests"}

    def capture_modules():
        for name, module in list(sys.modules.items()):
            if module is None:
                continue
            filename = getattr(module, "__file__", None)
            if filename:
                path = Path(filename).absolute().resolve(strict=False)
                role = support.get(str(path))
                relative = path.relative_to(execution).as_posix() if path.is_relative_to(execution) else None
                if relative is not None:
                    role = "bundled_regression_test" if relative in config["bundled_test_paths"] else "copied_source"
                if role:
                    identity = verifier.file_identity(path)
                    row = {"module": name, "path": str(path), "role": role, **identity}
                    if relative is not None:
                        row["source_relative_path"] = relative
                        if identity != source_expected.get(relative):
                            receipt["module_identity_errors"].append("EXECUTED_FILE_IDENTITY_MISMATCH:" + name)
                    module_records[(name, str(path), identity["sha256"])] = row
                elif name.split(".", 1)[0] in business_names:
                    receipt["module_identity_errors"].append("BUSINESS_IMPORT_OUTSIDE_EXECUTION_SOURCE:" + name
                                                              + ":" + str(path))
            elif name.split(".", 1)[0] in business_names and hasattr(module, "__path__"):
                paths = [str(Path(path).resolve()) for path in module.__path__]
                if any(not Path(path).is_relative_to(execution) for path in paths):
                    receipt["module_identity_errors"].append("BUSINESS_NAMESPACE_OUTSIDE_EXECUTION_SOURCE:" + name)
                module_records[(name, "namespace", "")] = {
                    "module": name, "role": "source_namespace", "namespace_paths": paths,
                    "path": None, "sha256": None, "bytes": None,
                }

    class FixedTests:
        def __init__(self):
            self.collected = Counter()
            self.outcomes = {}

        def pytest_collection_modifyitems(self, session, config, items):
            actual = Counter(Path(str(item.path)).name for item in items)
            self.collected = actual
            allowed = {str(execution / "tests" / name) for name in TEST_GROUPS}
            if actual != Counter(TEST_GROUPS) or any(str(Path(item.path).resolve()) not in allowed for item in items):
                import pytest
                raise pytest.UsageError("EXACT_57_TEST_COLLECTION_REQUIRED:" + json.dumps(dict(actual), sort_keys=True))
            capture_modules()
            if receipt["module_identity_errors"]:
                import pytest
                raise pytest.UsageError("BUSINESS_SOURCE_IDENTITY_REJECTED")

        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                self.outcomes[report.nodeid] = report.outcome
            elif report.failed:
                self.outcomes[report.nodeid] = "error"
            elif report.skipped:
                self.outcomes[report.nodeid] = "skipped"
            if report.when == "teardown":
                capture_modules()

        def totals(self):
            result = {}
            for name, expected in TEST_GROUPS.items():
                outcomes = Counter(value for nodeid, value in self.outcomes.items()
                                   if Path(nodeid.split("::", 1)[0]).name == name)
                result[name] = {"expected": expected, "collected": self.collected[name],
                               **{key: outcomes[key] for key in ("passed", "failed", "error", "skipped")},
                               "not_run": self.collected[name] - sum(outcomes.values())}
            return result

    plugin = FixedTests()
    try:
        verifier.verify(PACKAGE, source_root=execution, side="after")
        _install_guard((original, execution, PACKAGE), receipt["guard_events"], executed)
        sys.path[:] = [str(execution)] + [path for path in sys.path if path != str(execution)]
        import pytest

        # Only this prior delivered CLI is support. Its production imports still
        # resolve to the selected source. The source's own CLI file is untouched.
        cli_path = PACKAGE / SUPPORT_CLI
        if verifier.file_identity(cli_path)["sha256"] != SUPPORT_CLI_SHA256:
            raise ValueError("TEST_SUPPORT_CLI_PIN_MISMATCH")
        ops = importlib.import_module("ops")
        cli = _load_module("ops.run_manager_daily_announcement", cli_path)
        setattr(ops, "run_manager_daily_announcement", cli)
        support_app = str((PACKAGE / "tests/support/app").resolve())
        sys.path[:] = [str(execution)] + [path for path in sys.path
                                        if path not in {str(execution), support_app}]

        # Tests use both qualified and bare imports of the same HK fixture.
        # This is a test namespace only; no business namespace is replaced.
        tests = ModuleType("tests")
        tests.__path__ = [str(execution / "tests")]
        tests.__package__ = "tests"
        tests.__spec__ = importlib.util.spec_from_loader("tests", loader=None, is_package=True)
        sys.modules["tests"] = tests
        hk = _load_module("tests.test_manager_four_hk_readers",
                          execution / "tests/test_manager_four_hk_readers.py")
        setattr(tests, "test_manager_four_hk_readers", hk)
        sys.modules["test_manager_four_hk_readers"] = hk
        _load_module("test_manager_us_mapping_research", PACKAGE / SUPPORT_HELPER)
        capture_modules()

        args = ["-q", "-p", "no:cacheprovider", "--noconftest", "--import-mode=importlib",
                "-c", str(out / "pytest.ini"), "--rootdir", str(execution),
                "--basetemp", str(out / "pytest_tmp"), "--junitxml", str(out / "junit.xml"),
                "-o", "addopts=", "-o", "junit_family=xunit2"]
        args.extend(str(execution / "tests" / name) for name in TEST_GROUPS)
        receipt["pytest_arguments"] = args
        receipt["pytest_exit_code"] = int(pytest.main(args, plugins=[plugin]))
        capture_modules()
        receipt["test_groups"] = plugin.totals()
        receipt["passed_tests"] = sum(row["passed"] for row in receipt["test_groups"].values())
        receipt["status"] = "PASS" if (receipt["pytest_exit_code"] == 0
            and receipt["passed_tests"] == EXPECTED_TOTAL
            and not receipt["module_identity_errors"] and not receipt["guard_events"]) else "FAIL"
    except Exception as exc:
        receipt["reason"] = str(exc)
        traceback.print_exc()
    finally:
        capture_modules()
        receipt["test_groups"] = plugin.totals()
        receipt["loaded_modules"] = sorted(module_records.values(), key=lambda row: (row["module"], row["path"] or ""))
        receipt["module_identity_errors"] = sorted(set(receipt["module_identity_errors"]))
        receipt["executed_source_files"] = [{"path": path, **verifier.file_identity(Path(path))}
                                              for path in sorted(executed) if Path(path).is_file()]
        if receipt["module_identity_errors"] or receipt["guard_events"]:
            receipt["status"] = "FAIL"
        receipt["test_only_support"] = [{"path": path, "role": role, **verifier.file_identity(Path(path))}
                                        for path, role in support.items()]
        receipt["business_namespace_shims"] = False
        receipt["test_namespace"] = {"name": "tests", "path": str(execution / "tests"),
                                     "hk_bare_name_alias": "tests.test_manager_four_hk_readers"}
        receipt["sys_path_first"] = sys.path[0]
        _write_json(out / "worker_environment.json", receipt)
    return 0 if receipt["status"] == "PASS" else 1


def run(source: Path, out: Path) -> int:
    source = source.expanduser().resolve(strict=True)
    out = out.expanduser().resolve(strict=False)
    if not source.is_dir():
        raise ValueError("SOURCE_ROOT_NOT_DIRECTORY")
    if out == source or out.is_relative_to(source) or source.is_relative_to(out):
        raise ValueError("OUTPUT_MUST_BE_OUTSIDE_SOURCE_ROOT_AND_NOT_ITS_ANCESTOR")
    if out == PACKAGE or PACKAGE.is_relative_to(out) or (out.is_relative_to(PACKAGE)
                                                         and not out.is_relative_to(PACKAGE / "LOCAL")):
        raise ValueError("PACKAGE_OUTPUTS_MUST_BE_UNDER_LOCAL_OR_OUTSIDE_PACKAGE")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("OUTPUT_DIRECTORY_MUST_BE_NEW_OR_EMPTY")
    out.mkdir(parents=True, exist_ok=True)
    execution = out / "source"
    receipt = {"schema_version": "v4.manager_four_function_repair.regression.v1",
               "status": "FAIL", "started_at": datetime.now(timezone.utc).isoformat(),
               "original_source_root": str(source), "execution_source_root": str(execution),
               "package_root": str(PACKAGE), "output_root": str(out),
               "pytest_exit_code": None, "worker_exit_code": None,
               "identity_scope": "Offline copied dependency assembly; not a complete Mac R2 release identity.",
               "deployment": "NOT_RUN", "live_api": "NOT_RUN", "natural_run": "NOT_RUN",
               "full_project_gate": "NOT_RUN", "patch_applied": False,
               "write_audit_scope": "ABSOLUTE_PATHS_ONLY",
               "descriptor_write_prevention": False, "general_security_sandbox": False,
               "source_preservation_basis": "Before/after SHA256 and byte counts of the declared copied source inventory; excluded dependency/state trees are listed in source_identity.json. This is content verification, not a general filesystem sandbox.",
               "dependency_installation": "NOT_RUN", **_versions()}
    verifier = _verifier()
    original_files, execution_expected = None, None
    try:
        receipt["before_verification"] = verifier.verify(PACKAGE, source_root=source, side="after")
        original_files = _snapshot(source, verifier)
        execution.mkdir()
        for relative in original_files:
            target = execution / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(verifier.exact_file(source, relative), target)
        execution_expected = dict(original_files)
        bundled = []
        for name in TEST_GROUPS:
            relative = "tests/" + name
            target = execution / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(verifier.exact_file(PACKAGE, relative), target)
            execution_expected[relative] = verifier.file_identity(PACKAGE / relative)
            bundled.append({"path": relative, "package_path": str(PACKAGE / relative),
                            "execution_path": str(target), **execution_expected[relative]})
        copy_diff = _differences(execution_expected, _snapshot(execution, verifier))
        if _changed(copy_diff):
            raise ValueError("EXECUTION_COPY_MISMATCH:" + json.dumps(copy_diff))
        receipt["execution_verification"] = verifier.verify(PACKAGE, source_root=execution, side="after")
        identity = {"original_source_root": str(source), "execution_source_root": str(execution),
                    "excluded_directory_names": sorted(EXCLUDED_DIRECTORIES),
                    "excluded_file_suffixes": [".pyc", ".pyo"],
                    "original_files": [{"path": path, "original_path": str(source / path), **identity}
                                       for path, identity in original_files.items()],
                    "execution_files": [{"path": path, "execution_path": str(execution / path), **identity}
                                        for path, identity in execution_expected.items()],
                    "bundled_test_paths": [row["path"] for row in bundled], "bundled_tests": bundled}
        _write_json(out / "source_identity.json", identity)
        for directory in ("work", "tmp"):
            (out / directory).mkdir()
        (out / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
        env = os.environ.copy()
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
            env.pop(name, None)
        env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                    "TMPDIR": str(out / "tmp"), "TMP": str(out / "tmp"), "TEMP": str(out / "tmp")})
        command = [sys.executable, "-B", "-I", str(Path(__file__).resolve()), "--_worker", str(out)]
        receipt["worker_command"] = command
        receipt["worker_cwd"] = str(out / "work")
        with (out / "pytest.log").open("w", encoding="utf-8") as log:
            process = subprocess.run(command, cwd=out / "work", env=env, stdout=log,
                                     stderr=subprocess.STDOUT, check=False)
        receipt["worker_exit_code"] = process.returncode
        worker_path = out / "worker_environment.json"
        if worker_path.is_file():
            receipt.update(json.loads(worker_path.read_text(encoding="utf-8")))
        else:
            receipt["reason"] = "WORKER_RECEIPT_MISSING"
        junit = out / "junit.xml"
        if junit.is_file():
            suites = list(ET.parse(junit).getroot().iter("testsuite"))
            receipt["junit_totals"] = {
                key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
                for key in ("tests", "failures", "errors", "skipped")
            }
            if any(receipt["junit_totals"].get(key, 0) != expected for key, expected in
                   (("tests", EXPECTED_TOTAL), ("failures", 0), ("errors", 0), ("skipped", 0))):
                receipt["status"] = "FAIL"
                receipt["reason"] = "JUNIT_TOTALS_NOT_57_PASSED"
        else:
            receipt["status"] = "FAIL"
            receipt["junit_status"] = "NOT_CREATED"
        if process.returncode != 0:
            receipt["status"] = "FAIL"
    except Exception as exc:
        receipt["status"] = "FAIL"
        receipt["reason"] = str(exc)
        with (out / "pytest.log").open("a", encoding="utf-8") as log:
            log.write("RUNNER_FAILURE:" + str(exc) + "\n")
    finally:
        try:
            if original_files is not None:
                receipt["original_source_differences"] = _differences(original_files, _snapshot(source, verifier))
                receipt["original_source_checked_files"] = len(original_files)
                if _changed(receipt["original_source_differences"]):
                    receipt["status"] = "FAIL"
                    receipt["reason"] = "ORIGINAL_SOURCE_CHANGED"
            if execution_expected is not None:
                receipt["execution_source_differences"] = _differences(execution_expected, _snapshot(execution, verifier))
                if _changed(receipt["execution_source_differences"]):
                    receipt["status"] = "FAIL"
                    receipt["reason"] = "EXECUTION_SOURCE_CHANGED"
        except Exception as exc:
            receipt["status"] = "FAIL"
            receipt["postcheck_error"] = str(exc)
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        receipt["runner_exit_code"] = 0 if receipt["status"] == "PASS" else 1
        _write_json(out / "environment.json", receipt)
    print(json.dumps({"status": receipt["status"], "runner_exit_code": receipt["runner_exit_code"],
                      "pytest_exit_code": receipt.get("pytest_exit_code"),
                      "junit_totals": receipt.get("junit_totals"), "output_dir": str(out),
                      "reason": receipt.get("reason")}, ensure_ascii=False))
    return receipt["runner_exit_code"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--_worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker is not None:
        return _worker(args._worker.resolve(strict=True))
    if args.source_root is None or args.output_dir is None:
        parser.error("--source-root and --output-dir are required")
    try:
        return run(args.source_root, args.output_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
