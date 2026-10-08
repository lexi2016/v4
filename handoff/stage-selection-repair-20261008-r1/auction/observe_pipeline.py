"""Capture compact synthetic values and immutable identities from the real chain."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from assemble_support import BUNDLE, assemble


def observe() -> dict:
    from fastapi.testclient import TestClient
    from api_route_harness import create_isolated_workbench
    sys.path.insert(0, str(BUNDLE / "tests"))
    from test_a_auction_prev_close import (
        DATE, STAGE, auction_row, through_adapter, publish_and_read,
    )

    fields = ("prev_close_price", "current_change_pct", "qmt_gap_pct",
              "current_change_pct_missing_reason", "score", "rank")
    cases = []
    for name, previous in (("100_to_105", 100), ("missing", None),
                           ("zero", 0), ("negative", -100), ("nonfinite", float("inf"))):
        envelope = through_adapter([auction_row(previous=previous, price=105)])
        with tempfile.TemporaryDirectory(prefix="issue28-auction-fixture-") as temporary:
            verified, _, store = publish_and_read(Path(temporary), envelope)
            with TestClient(create_isolated_workbench(store.root)) as client:
                response = client.get("/api/v3/workbench/stage", params={"date": DATE, "stage": STAGE, "limit": 10})
            assert response.status_code == 200
            payload = response.json()
            latest = store._latest()["entries"][store._key(DATE, STAGE, "A_SHARE")]
            cases.append({
                "case": name, "builder_selector": {key: envelope["rows"][0].get(key) for key in fields},
                "verified_readback": {key: verified["rows"][0].get(key) for key in fields},
                "api_unified_row": {key: payload["unified_rows"][0].get(key) for key in fields},
                "run_id": verified["run_id"], "artifact_id": verified["artifact_id"],
                "algorithm_sha256": verified["algorithm_sha256"],
                "artifact_sha256": latest["artifact_sha256"],
                "manifest_sha256": latest["manifest_sha256"],
                "receipt_sha256": latest["receipt_sha256"],
                "api_run_matches": payload["selection_markets"]["A_SHARE"]["run_id"] == verified["run_id"],
                "source": "SYNTHETIC_FIXTURE_ONLY; NOT_20261008_BUSINESS_ROWS",
            })
    rows = [auction_row(code=f"A.{index:06d}", previous=100, price=price)
            for index, price in ((101, 95), (102, 105), (103, 100))]
    ranked = through_adapter(rows)
    return {
        "owner": os.environ["ISSUE28_OWNER"], "phase": os.environ["ISSUE28_PHASE"],
        "scope": "FROZEN_IMPORTS_AND_EXACT_ROUTE_IN_PROCESS_HTTP; NOT_CURRENT_OWNER_APP",
        "cases": cases,
        "rank_fixture": [{key: row[key] for key in ("code", "score", "rank")}
                         for row in ranked["rows"]],
        "algorithm_sha256": ranked["algorithm_sha256"],
        "business_artifacts_changed": False, "services_changed": False,
        "orders_sent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", choices=("canonical", "active_stage_reference"))
    parser.add_argument("--phase", choices=("before", "after"))
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--output", type=Path, default=BUNDLE / "logs")
    options = parser.parse_args()
    if options.worker:
        print(json.dumps(observe(), indent=2, allow_nan=False))
        return 0
    if options.owner is None or options.phase is None:
        parser.error("--owner and --phase are required")
    options.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="issue28-auction-observation-") as temporary:
        runroot = assemble(options.owner, options.phase, Path(temporary) / "runroot")
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(runroot), str(BUNDLE))),
                           PYTHONDONTWRITEBYTECODE="1", ISSUE28_OWNER=options.owner,
                           ISSUE28_PHASE=options.phase)
        command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
        result = subprocess.run(command, env=environment, cwd=BUNDLE, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stem = f"{options.owner}_{options.phase}_pipeline"
        (options.output / f"{stem}.log").write_text(result.stderr)
        if result.returncode == 0:
            value = json.loads(result.stdout)
            (options.output / f"{stem}.json").write_text(result.stdout)
            print(json.dumps({"path": f"{stem}.json", "first_case": value["cases"][0],
                              "rank_fixture": value["rank_fixture"]}))
        else:
            print(result.stderr)
        (options.output / f"{stem}.execution.json").write_text(json.dumps({
            "command": command, "cwd": str(BUNDLE), "exit_code": result.returncode,
            "stderr_log": f"{stem}.log",
            "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        }, indent=2) + "\n")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
