"""Focused check for identity fields on the daemon's FINISHED observation."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from ops import run_v4_macos_scheduler_daemon as daemon


def main() -> None:
    job = {"business_date": "20261123", "slot": "1610"}
    run_id = "0123456789abcdef0123456789abcdef"
    checks = [
        ("valid_exact_date_slot", {"run_id": run_id, "business_date": "20261123", "slot": "1610"}, run_id),
        ("wrong_date", {"run_id": run_id, "business_date": "20261122", "slot": "1610"}, None),
        ("wrong_slot", {"run_id": run_id, "business_date": "20261123", "slot": "1540"}, None),
        ("short_id", {"run_id": run_id[:-1], "business_date": "20261123", "slot": "1610"}, None),
        ("non_hex_id", {"run_id": "g" + run_id[1:], "business_date": "20261123", "slot": "1610"}, None),
        ("missing_id", {"business_date": "20261123", "slot": "1610"}, None),
        ("missing_result", None, None),
    ]
    results = []
    for name, payload, expected in checks:
        actual = daemon._validated_observation_run_id(payload, job)
        if actual != expected:
            raise AssertionError(f"{name}: expected {expected!r}, got {actual!r}")
        results.append({"case": name, "result": actual, "pass": True})
    out = {
        "schema": "v4.daemon_finished_run_id_validation.v1",
        "status": "PASS_STRICT_RUN_ID_AND_JOB_BINDING",
        "release_root": str(Path(daemon.__file__).resolve().parents[1].parent),
        "app_root": str(Path(daemon.__file__).resolve().parents[1]),
        "no_site": sys.flags.no_site,
        "pycache_prefix": sys.pycache_prefix,
        "cases": results,
        "cases_passed": len(results),
        "scheduler_started": False,
        "registry_or_ledger_touched": False,
    }
    (Path(__file__).resolve().parent / "DAEMON_RUN_ID_VALIDATION_RECEIPT.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
