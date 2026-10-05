"""Reproduce candidate tests without DNS, outbound connections or shell execution.

This is a test harness, NOT an operating-system sandbox. Run the broad suite
only in an isolated workspace/container: legacy tests still name private
absolute evidence paths. New regression fixtures use pytest temporary roots.
Never point this harness or its evidence directory at a production state root.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

TARGETED_TESTS = (
    "tests/test_trading_safety_consistency.py",
    "tests/test_runner_config.py",
    "tests/test_trading_calendar_policy.py",
    "tests/test_stage_scoring.py",
    "tests/test_runtime_graph_posix_store.py",
    "tests/test_manager_research_router_contract.py",
    "tests/test_manager_research_recommendation.py",
    "tests/test_manager_research_catalyst_service.py",
    "tests/test_manager_research_event_source.py",
    "tests/test_manager_research_reader.py",
    "tests/test_research_http_transport.py",
)
BLOCKED_EVENTS = frozenset({
    "socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg",
    "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--suite", choices=("optimization", "targeted", "broad"), default="optimization")
    args = parser.parse_args()
    root = args.root.expanduser().resolve(strict=True)
    output = args.evidence_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    sandbox = output / ("sandbox-" + uuid4().hex)
    sandbox.mkdir(mode=0o700)
    home = sandbox / "home"
    home.mkdir()
    temp = sandbox / "tmp"
    temp.mkdir()
    os.chdir(root)
    sys.path[:0] = [str(root / "upstreams"), str(root)]
    sys.dont_write_bytecode = True
    os.environ.update(
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
        RESEARCH_ONLY="1", production_allowed="false", buy_gate_updated="false", orders_sent="false",
        HOME=str(home), TMPDIR=str(temp), TEMP=str(temp), TMP=str(temp),
        V35_DATA_ROOT=str(home / "data"), V4_MANAGER_RESEARCH_STATE_ROOT=str(home / "manager"),
    )
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "V35_STAGE_MODE", "V35_STAGE_CENTER_SELECTION_ROOT"):
        os.environ.pop(key, None)
    blocked: list[dict[str, str]] = []

    def audit(event: str, _arguments: tuple) -> None:
        if event in BLOCKED_EVENTS:
            blocked.append({"event": event})
            raise RuntimeError("OFFLINE_TEST_BLOCKED: " + event)

    sys.addaudithook(audit)
    selection = {
        "optimization": ["tests/optimization"],
        "targeted": list(TARGETED_TESTS),
        "broad": ["tests", "--continue-on-collection-errors", "--ignore=tests/test_stage_eight_runs.py"],
    }[args.suite]
    command = [
        "-q", "-ra", "-o", "addopts=", "-W", "error", "-W", "default::pytest.PytestWarning",
        "--basetemp=" + str(temp / "pytest"), "--junitxml=" + str(output / "pytest.xml"), *selection,
    ]
    started = time.monotonic()
    exit_code = 3
    try:
        import pytest
        exit_code = int(pytest.main(command))
        return exit_code
    finally:
        packages = {}
        for name in ("pytest", "fastapi", "starlette", "httpx", "pandas", "pyarrow", "pytdx"):
            try:
                packages[name] = version(name)
            except PackageNotFoundError:
                packages[name] = "NOT_INSTALLED"
        report = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "suite": args.suite, "root": str(root), "python": sys.version,
            "platform": {"sys_platform": sys.platform, "uname": list(os.uname()) if hasattr(os, "uname") else None},
            "declared_python": ">=3.14",
            "normative_environment": sys.version_info >= (3, 14),
            "production_acceptance": "CANNOT_CONFIRM",
            "elapsed_seconds": round(time.monotonic() - started, 3), "exit_code": exit_code,
            "pytest_arguments": command, "packages": packages, "blocked": blocked,
            "sandbox": str(sandbox),
            "scope_note": "Broad excludes only the known real-materialization test file; failures are retained. "
                          "This harness is not a filesystem/process-isolation security boundary.",
        }
        (output / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
