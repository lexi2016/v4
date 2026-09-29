"""Focused A3 V2 catalog and status-boundary tests."""
from __future__ import annotations

from datetime import datetime
import plistlib
from pathlib import Path


def test_stage_workbench_is_external_stage_center_authority() -> None:
    from contracts.runtime_tasks import RuntimeCatalog
    from infrastructure.scheduling.catalog import load_workload_catalog

    catalog = load_workload_catalog()
    workload = next(row for row in catalog.workloads if row.workload_id == "stage_workbench")
    assert workload.enabled is False
    assert workload.owner_id == "stage_center"


def test_stage_workbench_missing_receipt_is_not_deferred_or_pending() -> None:
    from contracts.runtime_tasks import RuntimeCatalog
    from domains.task_status import _logical_row

    catalog = __import__("infrastructure.scheduling.catalog", fromlist=["load_workload_catalog"]).load_workload_catalog()
    workload = next(row for row in catalog.workloads if row.workload_id == "stage_workbench")
    result = _logical_row(
        workload,
        None,
        "20260825",
        datetime.fromisoformat("2026-08-25T16:00:00+08:00"),
    )
    assert result["status"] == "EXTERNAL_AUTHORITY"
    assert result["result_code"] == "STAGE_CENTER_EXTERNAL_AUTHORITY"


def test_v35_api_and_scheduler_bind_final_release_and_canonical_hk_root() -> None:
    release = Path(__file__).resolve().parents[2]
    final = "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260825T172000Z-v35-a3-stage-authority-binding-v5"
    root = "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data"
    for name in ("com.lexi.v35.local.plist", "com.lexi.v35.scheduler.plist"):
        payload = plistlib.loads((release / "deploy-plists" / name).read_bytes())
        env = payload["EnvironmentVariables"]
        assert env["V35_RELEASE_ID"] == final.rsplit("/", 1)[-1]
        assert env["V35_HK_UNIVERSE_ROOT"] == root
        assert final in payload["WorkingDirectory"]
        assert all(final in str(item) for item in payload["ProgramArguments"] if "/app/" in str(item))
        assert env["PRODUCTION_ALLOWED"] == "false"
        assert env["BUY_GATE_UPDATED"] == "false"
        assert env["ORDERS_SENT"] == "false"
