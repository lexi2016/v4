"""V4 immutable-release and scoped runtime-boundary assertions."""
from __future__ import annotations

import json
import plistlib
from pathlib import Path


V35_FINAL = "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260825T172000Z-v35-a3-stage-authority-binding-v5"
V35_LOG_ROOT = "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/logs"


def test_stage_workbench_fixed_catalog_projection() -> None:
    from infrastructure.scheduling.catalog import load_workload_catalog

    catalog = load_workload_catalog()
    logical = [row for row in catalog.workloads if row.workload_id == "stage_workbench"]
    assert len(logical) == 1
    row = logical[0]
    assert row.enabled is False
    assert row.owner_id == "stage_center"
    assert row.aliases == ("eight_stage_materialize",)
    source = catalog.source_payload
    source_rows = [item for item in source["workloads"] if item["workload_id"] == "stage_workbench"]
    assert len(source_rows) == 1
    assert source_rows[0]["enabled"] is False
    assert source_rows[0]["owner_id"] == "stage_center"


def test_v4_v35_plists_bind_external_logs_and_final() -> None:
    release = Path(__file__).resolve().parents[2]
    expected = {
        "com.lexi.v35.local.plist": (
            f"{V35_LOG_ROOT}/v35-a3-v4-api.stdout.log",
            f"{V35_LOG_ROOT}/v35-a3-v4-api.stderr.log",
        ),
        "com.lexi.v35.scheduler.plist": (
            f"{V35_LOG_ROOT}/v35-a3-v4-scheduler.stdout.log",
            f"{V35_LOG_ROOT}/v35-a3-v4-scheduler.stderr.log",
        ),
    }
    for name, (stdout, stderr) in expected.items():
        payload = plistlib.loads((release / "deploy-plists" / name).read_bytes())
        assert (payload["StandardOutPath"], payload["StandardErrorPath"]) == (stdout, stderr)
        assert "/releases/" not in stdout + stderr
        assert payload["WorkingDirectory"] == V35_FINAL + "/app"
        env = payload["EnvironmentVariables"]
        assert env["V35_RELEASE_ID"] == V35_FINAL.rsplit("/", 1)[-1]
        assert env["V35_HK_UNIVERSE_ROOT"] == "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data"
        assert env["PRODUCTION_ALLOWED"] == "false"
        assert env["BUY_GATE_UPDATED"] == "false"
        assert env["ORDERS_SENT"] == "false"
