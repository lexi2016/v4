"""Run explicit offline candidate suites; nonzero outcomes remain nonzero.

SDK fixtures are installed only in individual subprocess test environments.
They do not mask the existing suite's missing real pytdx dependency.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

NEW = ["tests/test_v16_panel_takeover_candidate.py", "tests/test_v16_due_candidate.py",
       "tests/test_v16_public_chain_fixture.py", "tests/test_v16_reader_daemon_candidate.py"]
EXISTING = ["tests/test_v4_scheduler_alignment.py", "tests/test_a_share_daily_sync.py",
            "tests/test_macos_research_panel_daily_ensure.py", "tests/test_macos_scheduler_hourly_catchup.py",
            "tests/test_scheduler_workload_integration.py", "tests/test_daily_research_review.py",
            "tests/test_manager_contract_hardening.py", "tests/test_manager_lifecycle_hardening.py"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("new", "existing", "combined"), default="new")
    parser.add_argument("--output", type=Path, required=True, help="new verification directory, not production data")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.output.expanduser().absolute()
    # mkdir(exist_ok=False) keeps old evidence and prevents pytest from deleting
    # a caller's existing tree via --basetemp. Symlink ancestors are rejected.
    if any(part.is_symlink() for part in (out, *out.parents)):
        parser.error("output must not use a symlink")
    out.mkdir(parents=True, exist_ok=False)
    os.chdir(root)
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(root), str(root / "upstreams/v3_shared_data")]
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", RESEARCH_ONLY="1",
                      production_allowed="false", buy_gate_updated="false", orders_sent="false",
                      V4_CANDIDATE_EVIDENCE_DIR=str(out / "integration"))
    os.environ["PYTHONPATH"] = os.pathsep.join(sys.path)
    blocked = []
    def guard(event, values):
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname", "socket.sendto"}:
            blocked.append(event)
            raise PermissionError("OFFLINE_NETWORK_FORBIDDEN")
        if event == "subprocess.Popen" and any(x in str(values[0]) for x in ("launchctl", "systemctl")):
            blocked.append(event)
            raise PermissionError("SERVICE_CONTROL_FORBIDDEN")
    sys.addaudithook(guard)
    import pytest
    selected = NEW if args.suite == "new" else EXISTING if args.suite == "existing" else EXISTING + NEW
    arguments = ["-q", "-p", "no:cacheprovider", "-o", "addopts=-W error",
                 "--basetemp=" + str(out / "tmp"), "--junitxml=" + str(out / "results.xml"), *selected]
    start = time.monotonic()
    code = int(pytest.main(arguments))
    (out / "result.json").write_text(json.dumps({"suite": args.suite, "exit_code": code,
        "pytest_arguments": arguments, "python": sys.version, "elapsed_seconds": time.monotonic()-start,
        "blocked_network_or_service_actions": blocked, "note": "fixture tests, not deployed/natural verification"}, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
