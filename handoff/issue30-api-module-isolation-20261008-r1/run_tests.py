#!/usr/bin/env python3
"""Replay the three frozen Issue #30 suites in new, hash-checked directories.

This is an offline source-test launcher. It neither imports the complete R2
application nor installs dependencies, deploys, or starts a real service.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


SCHEMA = "v4.issue30.portable_test_inputs.v1"
SUITES = ("release", "cutover", "preselection")
PRODUCT_OPS = (
    "api_release_integration.py", "build_release_candidate.py",
    "prepare_api_only_cutover.py", "create_api_module_delta.py",
)
SUPPORT_OPS = (
    "release_candidate_sources.py", "release_candidate_audit.py",
    "build_release_candidate_stage.py", "release_candidate_ports.py",
    "stage_service_overlay_contract.py",
)
PRESELECTION_APPS = ("app.py", "preselection_router.py", "preselection_service.py")
PRESELECTION_TESTS = (
    "scope_api_harness.py", "test_preselection_source_root_20261008.py",
    "test_issue28_preselection_hk_fallback.py", "test_issue30_preselection_module.py",
)
PRESELECTION_SUPPORT = (
    "contracts/stages.py", "contracts/trading_calendar.py", "contracts/trading_safety.py",
    "domains/preselection.py", "infrastructure/data_store.py",
    "infrastructure/interprocess_lock.py", "infrastructure/isolated_package_loader.py",
    "infrastructure/market_time.py", "infrastructure/owned_io.py",
    "infrastructure/owned_path.py", "infrastructure/preselection_pool_readers.py",
    "infrastructure/preselection_pool_sources.py", "infrastructure/preselection_pool_store.py",
    "infrastructure/preselection_pool_transactions.py", "infrastructure/review_core_fupan_pool_source.py",
    "infrastructure/review_core_stage7_pool_source.py", "infrastructure/scope_gate.py",
    "infrastructure/trading_safety.py", "stage_center/calendar.py",
    "stage_center/contracts.py", "stage_center/selection.py",
)
ACTUAL = "api_only_cutover_r2_ready.py"
RUNTIME_PREFIXES = (
    "after/ops", "after/apps/api/v35_api", "after/actual_cutover_reference",
    "tests/release", "tests/cutover", "tests/preselection",
    "test_support/release/ops", "test_support/preselection",
    "original/r2_app", "original/two_hunk_reference",
)
SAFETY = {
    "RESEARCH_ONLY": True, "production_allowed": False,
    "buy_gate_updated": False, "orders_sent": False,
    "deployed": False, "live_api_ui_tested": False,
    "full_r2_runtime_tested": False, "natural_period_acceptance": "NOT_RUN",
}

# An explicit, generated plugin records collection and report events. Relying
# on pytest's exit code or a human-readable "passed" line alone is insufficient.
METRICS_PLUGIN = r'''import hashlib
import json
import os
from pathlib import Path

DATA = {"schema_version": "v4.issue30.pytest_metrics.v1", "node_ids": [],
        "testscollected": 0, "deselected": 0, "collection_errors": 0,
        "passed_calls": 0, "failed_calls": 0, "failed_setup_teardown": 0,
        "skipped_reports": 0, "xfail_or_xpass_reports": 0, "reports": []}

def pytest_collection_finish(session):
    DATA["node_ids"] = [item.nodeid for item in session.items]
    DATA["testscollected"] = session.testscollected

def pytest_deselected(items):
    DATA["deselected"] += len(items)

def pytest_collectreport(report):
    if report.failed:
        DATA["collection_errors"] += 1

def pytest_runtest_logreport(report):
    DATA["reports"].append({"node_id": report.nodeid, "when": report.when,
                            "outcome": report.outcome,
                            "was_xfail": hasattr(report, "wasxfail")})
    if report.when == "call" and report.passed:
        DATA["passed_calls"] += 1
    if report.failed:
        DATA["failed_calls" if report.when == "call" else "failed_setup_teardown"] += 1
    if report.skipped:
        DATA["skipped_reports"] += 1
    if hasattr(report, "wasxfail"):
        DATA["xfail_or_xpass_reports"] += 1

def pytest_sessionfinish(session, exitstatus):
    DATA["exitstatus"] = int(exitstatus)
    DATA["testscollected"] = session.testscollected
    DATA["unique_node_ids"] = len(set(DATA["node_ids"]))
    DATA["node_ids_sha256"] = hashlib.sha256(
        ("\n".join(DATA["node_ids"]) + "\n").encode()).hexdigest()
    destination = Path(os.environ["ISSUE30_PORTABLE_METRICS"])
    with destination.open("x", encoding="utf-8") as output:
        json.dump(DATA, output, sort_keys=True, indent=2)
        output.write("\n")
'''

DEPENDENCY_PROBE = r'''import importlib
import importlib.metadata
import json
import platform
import shutil
import sys
requirements = json.loads(sys.argv[1])
result = {"python": sys.version, "executable": sys.executable,
          "platform": platform.platform(), "packages": {}, "errors": []}
if sys.version_info < (3, 11):
    result["errors"].append("Python 3.11 or newer is required")
try:
    import fcntl
except ImportError as error:
    result["errors"].append("POSIX fcntl is required: " + str(error))
for name in requirements:
    try:
        module = importlib.import_module(name)
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = "UNKNOWN"
        result["packages"][name] = {"version": version, "origin": getattr(module, "__file__", None)}
    except Exception as error:
        result["errors"].append(name + ": " + type(error).__name__ + ": " + str(error))
if sys.argv[2] == "release":
    result["git"] = shutil.which("git")
    if result["git"] is None:
        result["errors"].append("git is required for isolated source fixtures")
print(json.dumps(result, sort_keys=True))
raise SystemExit(2 if result["errors"] else 0)
'''


class ReplayError(ValueError):
    """A replay input, path, or result does not meet the frozen contract."""


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReplayError("DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def decode_json(raw: bytes) -> object:
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ReplayError("INVALID_JSON_NUMBER:" + value)))


def relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ReplayError("INVALID_RELATIVE_PATH:" + repr(value))
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in (".", "..") for part in path.parts):
        raise ReplayError("INVALID_RELATIVE_PATH:" + value)
    return value


def absolute_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or str(path) != value or any(part in (".", "..") for part in path.parts):
        raise ReplayError("ABSOLUTE_UNALIASED_PATH_REQUIRED:" + value)
    return path


def file_identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def directory_fd(path: Path):
    """Open every ancestor with NOFOLLOW; never resolve a symlink first."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ReplayError("PLATFORM_REQUIRES_POSIX_NOFOLLOW_AND_DIRECTORY_FDS")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            following = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def relative_parent(root_fd: int, relative: str, *, create: bool = False):
    parts = PurePosixPath(relative_path(relative)).parts
    descriptor = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            if create:
                try:
                    os.mkdir(component, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        yield descriptor, parts[-1]
    finally:
        os.close(descriptor)


def read_exact(root_fd: int, relative: str) -> bytes:
    with relative_parent(root_fd, relative) as (parent_fd, leaf):
        descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ReplayError("REGULAR_NON_HARDLINK_FILE_REQUIRED:" + relative)
            chunks = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
            path_after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            if file_identity(before) != file_identity(after) or file_identity(after) != file_identity(path_after):
                raise ReplayError("INPUT_CHANGED_DURING_READ:" + relative)
            return b"".join(chunks)
        finally:
            os.close(descriptor)


def write_new(root_fd: int, relative: str, raw: bytes, *, mode: int = 0o600) -> None:
    with relative_parent(root_fd, relative, create=True) as (parent_fd, leaf):
        descriptor = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent_fd)
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(raw)
            destination.flush()
            os.fchmod(destination.fileno(), mode)
            os.fsync(destination.fileno())


def list_tree(root_fd: int, relative: str) -> set[str]:
    """Inventory importable trees without following file or directory aliases."""
    result = set()
    with relative_parent(root_fd, relative + "/placeholder") as (parent_fd, _):
        def visit(descriptor: int, prefix: str) -> None:
            for name in sorted(os.listdir(descriptor)):
                child = prefix + "/" + name
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    following = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                    try:
                        visit(following, child)
                    finally:
                        os.close(following)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    result.add(child)
                else:
                    raise ReplayError("RUNTIME_PATH_ALIAS_OR_SPECIAL_FILE:" + child)
        visit(parent_fd, relative)
    return result


def validate_manifest(manifest: object) -> dict[str, dict]:
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "files", "suites"}:
        raise ReplayError("INVALID_TEST_INPUTS_FIELDS")
    if manifest["schema_version"] != SCHEMA:
        raise ReplayError("UNSUPPORTED_TEST_INPUTS_SCHEMA")
    suites = manifest["suites"]
    if not isinstance(suites, dict) or set(suites) != set(SUITES):
        raise ReplayError("EXACTLY_THREE_SUITES_REQUIRED")
    for name, configuration in suites.items():
        if not isinstance(configuration, dict) or set(configuration) != {"expected_tests"}:
            raise ReplayError("INVALID_SUITE_FIELDS:" + name)
        count = configuration["expected_tests"]
        if type(count) is not int or count <= 0:
            raise ReplayError("POSITIVE_EXPECTED_TEST_COUNT_REQUIRED:" + name)
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise ReplayError("NONEMPTY_FILE_MANIFEST_REQUIRED")
    entries = {}
    paths = []
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
            raise ReplayError("INVALID_FILE_ENTRY_FIELDS")
        path = relative_path(entry["path"])
        if path == "TEST_INPUTS.json" or path in entries:
            raise ReplayError("DUPLICATE_OR_SELF_REFERENCING_FILE_ENTRY:" + path)
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise ReplayError("INVALID_FILE_SHA256:" + path)
        if type(entry["size"]) is not int or entry["size"] < 0:
            raise ReplayError("INVALID_FILE_SIZE:" + path)
        entries[path] = entry
        paths.append(path)
    if paths != sorted(paths) or len({path.casefold() for path in paths}) != len(paths):
        raise ReplayError("FILE_PATHS_MUST_BE_SORTED_AND_CASE_UNIQUE")
    if "run_tests.py" not in entries:
        raise ReplayError("RUNNER_SHA_MUST_BE_INCLUDED")
    return entries


def runtime_mapping(entries: dict[str, dict]) -> dict[str, str]:
    """Return destination -> source; mappings preserve author harness paths."""
    mapping = {}

    def add(source: str, destination: str) -> None:
        if source not in entries:
            raise ReplayError("REQUIRED_TEST_INPUT_MISSING:" + source)
        if destination in mapping:
            raise ReplayError("RUNTIME_DESTINATION_COLLISION:" + destination)
        mapping[destination] = source

    for name in PRODUCT_OPS:
        add("after/ops/" + name, "release/ops/" + name)
    for name in SUPPORT_OPS:
        add("test_support/release/ops/" + name, "release/ops/" + name)
    release_tests = [path for path in entries if path.startswith("tests/release/")]
    if not release_tests or not any(PurePosixPath(path).name.startswith("test_") for path in release_tests):
        raise ReplayError("RELEASE_TESTS_MISSING")
    for source in release_tests:
        if len(PurePosixPath(source).parts) != 3 or not source.endswith(".py"):
            raise ReplayError("FLAT_PYTHON_RELEASE_TESTS_REQUIRED:" + source)
        add(source, "release/tests/" + PurePosixPath(source).name)

    cutover = "cutover/work/cutover_analysis/"
    add("after/actual_cutover_reference/" + ACTUAL, cutover + "candidate/" + ACTUAL)
    for required in ("test_actual_api_cutover.py", "probe_cutover_boundaries.py"):
        if "tests/cutover/" + required not in entries:
            raise ReplayError("REQUIRED_TEST_INPUT_MISSING:tests/cutover/" + required)
    for source in (path for path in entries if path.startswith("tests/cutover/")):
        if len(PurePosixPath(source).parts) != 3 or not source.endswith(".py"):
            raise ReplayError("FLAT_PYTHON_CUTOVER_TESTS_REQUIRED:" + source)
        filename = PurePosixPath(source).name
        destination = cutover + ("" if filename == "probe_cutover_boundaries.py" else "tests/") + filename
        add(source, destination)
    add("after/ops/api_release_integration.py", "cutover/work/integration_core/candidate/ops/api_release_integration.py")
    for relative in ("source/actual_cutover_reference/" + ACTUAL,
                     "source/unreviewed_draft/ops/api_release_integration.py"):
        add("original/issue30/" + relative, "cutover/input/baseline/" + relative)

    for name in PRESELECTION_APPS:
        add("after/apps/api/v35_api/" + name, "preselection/after/apps/api/v35_api/" + name)
    for name in PRESELECTION_TESTS:
        if "tests/preselection/" + name not in entries:
            raise ReplayError("REQUIRED_TEST_INPUT_MISSING:tests/preselection/" + name)
    for source in (path for path in entries if path.startswith("tests/preselection/")):
        if len(PurePosixPath(source).parts) != 3 or not source.endswith(".py"):
            raise ReplayError("FLAT_PYTHON_PRESELECTION_TESTS_REQUIRED:" + source)
        add(source, "preselection/tests/" + PurePosixPath(source).name)
    for relative in PRESELECTION_SUPPORT:
        add("test_support/preselection/" + relative, "preselection/test_support/" + relative)
    for original, destination in (("r2_app", "r2_app_byte_match"), ("two_hunk_reference", "two_hunk_reference")):
        add("original/" + original + "/apps/api/v35_api/app.py",
            "preselection/source/" + destination + "/apps/api/v35_api/app.py")

    mapped_sources = set(mapping.values())
    for source in entries:
        if any(source.startswith(prefix + "/") for prefix in RUNTIME_PREFIXES) and source not in mapped_sources:
            raise ReplayError("UNMAPPED_RUNTIME_INPUT:" + source)
    return mapping


def read_inputs(package: Path) -> tuple[dict, dict[str, bytes], dict[str, str], bytes, tuple]:
    with directory_fd(package) as descriptor:
        root_identity = file_identity(os.fstat(descriptor))[:2]
        raw_manifest = read_exact(descriptor, "TEST_INPUTS.json")
        manifest = decode_json(raw_manifest)
        entries = validate_manifest(manifest)
        mapping = runtime_mapping(entries)
        captured = {}
        for path, entry in entries.items():
            raw = read_exact(descriptor, path)
            if len(raw) != entry["size"] or sha256(raw) != entry["sha256"]:
                raise ReplayError("TEST_INPUT_SHA_OR_SIZE_MISMATCH:" + path)
            captured[path] = raw
        for prefix in RUNTIME_PREFIXES:
            unlisted = list_tree(descriptor, prefix) - set(entries)
            if unlisted:
                raise ReplayError("UNLISTED_RUNTIME_FILES:" + ",".join(sorted(unlisted)))
        if read_exact(descriptor, "TEST_INPUTS.json") != raw_manifest:
            raise ReplayError("TEST_INPUTS_CHANGED_DURING_VERIFICATION")
    with directory_fd(package) as descriptor:
        if file_identity(os.fstat(descriptor))[:2] != root_identity:
            raise ReplayError("PACKAGE_ROOT_CHANGED_DURING_VERIFICATION")
        for path, raw in captured.items():
            if read_exact(descriptor, path) != raw:
                raise ReplayError("INPUT_CHANGED_DURING_VERIFICATION:" + path)
    return manifest, captured, mapping, raw_manifest, root_identity


def clean_environment(python: Path, suite_root: Path, import_paths: list[Path], metrics: Path) -> dict[str, str]:
    # Inherit no user environment. In particular, no auth, service roots,
    # PYTHONPATH, PYTEST_PLUGINS/ADDOPTS, LD_PRELOAD, or git configuration leaks in.
    search_path = [str(python.parent), "/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/opt/homebrew/bin"]
    return {
        "PATH": os.pathsep.join(dict.fromkeys(search_path)),
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "PYTHONUTF8": "1",
        "TMPDIR": str(suite_root / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": "", "PYTEST_PLUGINS": "",
        "PYTHONPATH": os.pathsep.join(str(path) for path in import_paths),
        "ISSUE30_PORTABLE_METRICS": str(metrics), "ISSUE30_ROUTE_MODE": "candidate",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
        "RESEARCH_ONLY": "true", "PRODUCTION_ALLOWED": "false",
        "BUY_GATE_UPDATED": "false", "ORDERS_SENT": "false",
    }


def run_process(command: list[str], cwd: Path, env: dict[str, str], log: Path, timeout: int) -> dict:
    started = time.monotonic()
    timed_out = False
    with log.open("xb") as stream:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True, umask=0o022)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        except BaseException:
            # Only this launcher's new process group is terminated on interruption.
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
            raise
    return {"command": command, "cwd": str(cwd), "exit_code": process.returncode,
            "timed_out": timed_out, "elapsed_seconds": round(time.monotonic() - started, 6)}


def parse_junit(raw: bytes) -> dict:
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ReplayError("UNEXPECTED_JUNIT_DTD")
    root = ET.fromstring(raw)
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root)
        if not suites or any(suite.tag != "testsuite" for suite in suites):
            raise ReplayError("INVALID_JUNIT_SUITE_STRUCTURE")
    else:
        raise ReplayError("INVALID_JUNIT_ROOT")
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    cases = []
    for suite in suites:
        if suite.findall("testsuite"):
            raise ReplayError("NESTED_JUNIT_SUITES_UNSUPPORTED")
        for key in totals:
            value = suite.attrib.get(key)
            if value is None or not re.fullmatch(r"[0-9]+", value):
                raise ReplayError("INVALID_JUNIT_COUNT:" + key)
            totals[key] += int(value)
        cases.extend(suite.findall("testcase"))
    totals["testcase_elements"] = len(cases)
    totals["failure_elements"] = sum(len(case.findall("failure")) for case in cases)
    totals["error_elements"] = sum(len(case.findall("error")) for case in cases)
    totals["skipped_elements"] = sum(len(case.findall("skipped")) for case in cases)
    return totals


def evaluate_results(expected: int, process: dict, metrics: object, junit: dict) -> list[str]:
    failures = []
    if process["exit_code"] != 0 or process["timed_out"]:
        failures.append("PYTEST_PROCESS_FAILED_OR_TIMED_OUT")
    if not isinstance(metrics, dict) or metrics.get("schema_version") != "v4.issue30.pytest_metrics.v1":
        return failures + ["PYTEST_METRICS_MISSING_OR_INVALID"]
    equal_expected = ("testscollected", "unique_node_ids", "passed_calls")
    zero_expected = ("exitstatus", "deselected", "collection_errors", "failed_calls",
                     "failed_setup_teardown", "skipped_reports", "xfail_or_xpass_reports")
    for key in equal_expected:
        if type(metrics.get(key)) is not int or metrics[key] != expected:
            failures.append("METRICS_COUNT_MISMATCH:" + key)
    nodes = metrics.get("node_ids")
    if not isinstance(nodes, list) or len(nodes) != expected or any(not isinstance(node, str) for node in nodes):
        failures.append("COLLECTED_NODE_COUNT_MISMATCH")
    elif len(set(nodes)) != expected:
        failures.append("DUPLICATE_COLLECTED_NODE_IDS")
    for key in zero_expected:
        if type(metrics.get(key)) is not int or metrics[key] != 0:
            failures.append("METRICS_NOT_ZERO:" + key)
    for key in ("tests", "testcase_elements"):
        if junit.get(key) != expected:
            failures.append("JUNIT_COUNT_MISMATCH:" + key)
    for key in ("failures", "errors", "skipped", "failure_elements", "error_elements", "skipped_elements"):
        if junit.get(key) != 0:
            failures.append("JUNIT_NOT_ZERO:" + key)
    return failures


def artifact(path: Path, output_root: Path) -> dict:
    with directory_fd(output_root) as descriptor:
        raw = read_exact(descriptor, path.relative_to(output_root).as_posix())
    return {"path": path.relative_to(output_root).as_posix(), "sha256": sha256(raw), "size": len(raw)}


def execute_suite(name: str, output_root: Path, output_fd: int, python: Path,
                  expected: int, timeout: int) -> dict:
    suite_root = output_root / "isolated" / name
    evidence = output_root / "results" / name
    evidence.mkdir(parents=True)
    (suite_root / "tmp").mkdir()
    config = suite_root / "pytest.ini"
    write_new(output_fd, config.relative_to(output_root).as_posix(), b"[pytest]\n")
    plugin_root = output_root / "_runner"
    if name == "release":
        cwd, test_path = suite_root, suite_root / "tests"
        imports = [plugin_root, suite_root, suite_root / "tests"]
    elif name == "cutover":
        cwd = suite_root / "work/cutover_analysis"
        test_path = cwd / "tests"
        imports = [plugin_root, suite_root / "work/integration_core/candidate", cwd / "tests"]
    else:
        cwd, test_path = suite_root, suite_root / "tests"
        imports = [plugin_root, suite_root / "after", suite_root / "test_support", suite_root / "tests"]
    env = clean_environment(python, suite_root, imports, evidence / "metrics.json")
    if name == "cutover":
        env["CUTOVER_SOURCE"] = str(cwd / "candidate" / ACTUAL)
        env["INTEGRATION_SOURCE"] = str(suite_root / "work/integration_core/candidate/ops/api_release_integration.py")
    write_new(output_fd, "results/" + name + "/environment.json", json_bytes(env))
    requirements = ["pytest"]
    if name == "preselection":
        requirements += ["fastapi", "httpx", "starlette", "pydantic", "anyio"]
    dependencies = run_process(
        [str(python), "-B", "-c", DEPENDENCY_PROBE, json.dumps(requirements), name],
        cwd, env, evidence / "dependency_probe.log", min(timeout, 60))
    result = {"suite": name, "expected_tests": expected, "dependency_probe": dependencies,
              "scope": "ISOLATED_SYNTHETIC_SOURCE_TEST", "status": "FAIL", "problems": []}
    try:
        probe_lines = (evidence / "dependency_probe.log").read_text().splitlines()
        result["runtime"] = decode_json(probe_lines[-1].encode())
    except (ValueError, IndexError, UnicodeError):
        result["runtime"] = {"errors": ["DEPENDENCY_PROBE_OUTPUT_INVALID"]}
    if dependencies["exit_code"] != 0 or dependencies["timed_out"] or result["runtime"].get("errors"):
        result["status"] = "DEPENDENCY_ERROR"
        result["problems"].append("DEPENDENCIES_NOT_AVAILABLE_NO_INSTALL_ATTEMPTED")
    else:
        command = [str(python), "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   "-p", "_issue30_portable_metrics", "-c", str(config),
                   "--rootdir", str(suite_root), "--confcutdir", str(suite_root),
                   "--basetemp", str(suite_root / "tmp/pytest"),
                   "--junitxml", str(evidence / "junit.xml")]
        if name == "preselection":
            command += ["-W", "error", "-W", "default::starlette.exceptions.StarletteDeprecationWarning"]
        command.append(str(test_path))
        result["pytest"] = run_process(command, cwd, env, evidence / "pytest.log", timeout)
        try:
            metrics = decode_json((evidence / "metrics.json").read_bytes())
            if not isinstance(metrics, dict):
                raise ReplayError("PYTEST_METRICS_NOT_AN_OBJECT")
            junit = parse_junit((evidence / "junit.xml").read_bytes())
            result["metrics"] = {key: value for key, value in metrics.items() if key not in ("reports", "node_ids")}
            result["junit"] = junit
            result["problems"] += evaluate_results(expected, result["pytest"], metrics, junit)
        except (OSError, ValueError, ET.ParseError) as error:
            result["problems"].append("RESULT_EVIDENCE_INVALID:" + type(error).__name__ + ":" + str(error))
        if not result["problems"]:
            result["status"] = "PASS"
    result["artifacts"] = [artifact(path, output_root) for path in sorted(evidence.iterdir()) if path.is_file()]
    write_new(output_fd, "results/" + name + "/result.json", json_bytes(result))
    print(json.dumps({"suite": name, "status": result["status"], "expected_tests": expected,
                      "collected": result.get("metrics", {}).get("testscollected"),
                      "passed": result.get("metrics", {}).get("passed_calls"),
                      "problems": result["problems"]}, ensure_ascii=False), flush=True)
    return result


def run(args: argparse.Namespace) -> int:
    script = absolute_path(os.path.abspath(__file__))
    if script.name != "run_tests.py":
        raise ReplayError("RUNNER_FILENAME_MUST_BE_RUN_TESTS_PY")
    package = script.parent
    output_root = absolute_path(args.output_root)
    if output_root == package or package in output_root.parents or output_root in package.parents:
        raise ReplayError("OUTPUT_ROOT_MUST_BE_OUTSIDE_PACKAGE")
    python = Path(os.path.abspath(args.python or sys.executable))
    # A venv interpreter is commonly a symlink. It is an explicitly selected
    # trusted executable, not a packaged source input, and must retain its venv path.
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ReplayError("PYTHON_EXECUTABLE_NOT_AVAILABLE:" + str(python))
    manifest, captured, mapping, raw_manifest, package_identity = read_inputs(package)
    with directory_fd(output_root.parent) as parent_fd:
        os.mkdir(output_root.name, 0o700, dir_fd=parent_fd)  # Never reuse an existing output root.
    with directory_fd(output_root) as descriptor:
        output_identity = file_identity(os.fstat(descriptor))[:2]
        started = utc_now()
        write_new(descriptor, "TEST_INPUTS.json", raw_manifest)
        write_new(descriptor, "INPUT_VERIFICATION.json", json_bytes({
            "status": "PASS", "verified_file_count": len(captured),
            "test_inputs_sha256": sha256(raw_manifest), "runner_sha256": sha256(captured["run_tests.py"]),
            "source_package": str(package), "safety": SAFETY,
        }))
        write_new(descriptor, "_runner/_issue30_portable_metrics.py", METRICS_PLUGIN.encode(), mode=0o644)
        for destination, source in mapping.items():
            write_new(descriptor, "isolated/" + destination, captured[source], mode=0o644)
        write_new(descriptor, "LAYOUT.json", json_bytes({
            "mapping": [{"source": source, "destination": "isolated/" + destination,
                         "sha256": sha256(captured[source]), "size": len(captured[source])}
                        for destination, source in sorted(mapping.items())],
            "metrics_plugin_sha256": sha256(METRICS_PLUGIN.encode()),
        }))
        results = []
        problems = []
        for name in SUITES:
            with directory_fd(output_root) as checked_fd:
                if file_identity(os.fstat(checked_fd))[:2] != output_identity:
                    raise ReplayError("OUTPUT_ROOT_REPLACED")
            results.append(execute_suite(name, output_root, descriptor, python,
                                         manifest["suites"][name]["expected_tests"], args.timeout_seconds))
        for destination, source in mapping.items():
            if read_exact(descriptor, "isolated/" + destination) != captured[source]:
                problems.append("COPIED_SOURCE_CHANGED_DURING_TESTS:" + destination)
        with directory_fd(package) as checked_fd:
            if file_identity(os.fstat(checked_fd))[:2] != package_identity:
                problems.append("PACKAGE_ROOT_REPLACED")
            if read_exact(checked_fd, "TEST_INPUTS.json") != raw_manifest:
                problems.append("PACKAGE_MANIFEST_CHANGED")
            for source, raw in captured.items():
                if read_exact(checked_fd, source) != raw:
                    problems.append("PACKAGE_INPUT_CHANGED:" + source)
        passed = not problems and all(result["status"] == "PASS" for result in results)
        summary = {
            "schema_version": "v4.issue30.portable_test_result.v1", "status": "PASS" if passed else "FAIL",
            "started_utc": started, "finished_utc": utc_now(), "problems": problems,
            "expected_tests_total": sum(manifest["suites"][name]["expected_tests"] for name in SUITES),
            "passed_tests_total": sum(result.get("metrics", {}).get("passed_calls", 0) for result in results),
            "test_inputs_sha256": sha256(raw_manifest), "runner_sha256": sha256(captured["run_tests.py"]),
            "suites": [{"name": result["suite"], "status": result["status"],
                        "expected_tests": result["expected_tests"],
                        "result": artifact(output_root / "results" / result["suite"] / "result.json", output_root)}
                       for result in results],
            "safety": SAFETY,
            "limitations": [
                "Source tests use isolated synthetic filesystem fixtures and simulated service/HTTP responses.",
                "Preselection loads real router/service modules and exact app registration AST with a historical dependency closure.",
                "The complete current R2 app, live sources, deployment, API/UI, and natural periods are NOT tested.",
                "Verified source and explicit dependencies are trusted code; this launcher is not an OS sandbox.",
                "No network access, dependency installation, publication, or service action is requested by the launcher.",
            ],
        }
        write_new(descriptor, "SUMMARY.json", json_bytes(summary))
    print(json.dumps({"status": summary["status"], "expected_tests_total": summary["expected_tests_total"],
                      "passed_tests_total": summary["passed_tests_total"],
                      "summary": str(output_root / "SUMMARY.json")}, ensure_ascii=False), flush=True)
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, help="New absolute directory outside this package; its parent must exist and contain no symlink aliases")
    parser.add_argument("--python", help="Trusted Python environment with dependencies already installed; defaults to sys.executable")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Per-suite process timeout, including a maximum 60-second dependency probe (default: 900)")
    args = parser.parse_args()
    if args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")
    try:
        return run(args)
    except (ReplayError, OSError, ValueError) as error:
        print(json.dumps({"status": "ERROR", "reason": type(error).__name__ + ": " + str(error),
                          "deployed": False, "full_r2_runtime_tested": False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
