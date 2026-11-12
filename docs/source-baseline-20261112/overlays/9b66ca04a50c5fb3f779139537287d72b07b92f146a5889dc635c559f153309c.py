"""Consume a committed Stage close event through the existing dispatch claim."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from zoneinfo import ZoneInfo

from contracts.runtime_tasks import DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from stage_center.consumer import StageSelectionConsumer

CLOSE_STAGES = {"STAGE_1445_1500": ("1500", "fupan_close_materials", "A_SHARE"),
                "STAGE_1545_1555": ("1555", "fupan_review_start", "HK_CONNECT")}


def consume(*, trade_date, stage_id, selection_root, receipt_root, data_root, ledger_root, registry=None, now=None):
    slot, workload_id, market = CLOSE_STAGES[stage_id]
    moment = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    from ops.run_v4_macos_scheduler_due import _slot_retry_deadline
    if moment.strftime("%Y%m%d") != trade_date or moment > _slot_retry_deadline(trade_date, slot):
        return {"status": "EXPIRED", "source": "STAGE_COMPLETION"}
    consumer = StageSelectionConsumer(selection_root)
    selected = consumer.get(trade_date, stage_id, markets=(market,))
    lane = selected.get("markets", {}).get(market, {})
    # Normal natural envelopes predate the optional backfill provenance flags.
    # Verify the existing trio and the actual committed runner receipt rather
    # than requiring those absent display fields or trusting well-shaped SHAs.
    envelope = consumer.store.read_verified(trade_date, stage_id, market)
    runner_path = Path(receipt_root) / trade_date / stage_id / "receipt.json"
    runner = json.loads(runner_path.read_bytes())
    runner_lane = runner.get("markets", {}).get(market, {})
    if (selected.get("trade_date") != trade_date or selected.get("stage_id") != stage_id
        or selected.get("status") not in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"}
        or lane.get("selection_mode") == "BACKFILL"
        or envelope.get("run_id") != lane.get("run_id")
        or envelope.get("artifact_id") != lane.get("artifact_id")
        or runner.get("schema_version") != "stage_center.runner.receipt.v1"
        or runner.get("trade_date") != trade_date or runner.get("stage_id") != stage_id
        or runner.get("dispatch_mode") not in {"NATURAL", "RECOVERY"}
        or runner.get("mode") == "BACKFILL"
        or runner_lane.get("run_id") != envelope.get("run_id")
        or runner_lane.get("artifact_id") != envelope.get("artifact_id")
        or runner_lane.get("selection_status", runner_lane.get("status")) not in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"}
        or any(runner.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
        or any(selected.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        return {"status": "CANNOT_CONFIRM", "reason": "COMMITTED_STAGE_COMPLETION_NOT_VERIFIED"}
    request = DispatchRequest(trade_date, trade_date, trade_date, slot, "LIVE")
    registry = registry or FixedExecutorRegistry(data_root=Path(data_root), stage_selection_root=Path(selection_root))
    receipt = dispatch_due(request, load_workload_catalog(), registry, ledger=ExecutionLedger(Path(ledger_root)), completion_workload_ids=(workload_id,))
    import hashlib
    return {**receipt.to_dict(), "source": "STAGE_COMPLETION", "runner_receipt_sha256": hashlib.sha256(runner_path.read_bytes()).hexdigest(), "selection_run_id": envelope["run_id"]}


def notify(*, config, trade_date, stage_id, receipt):
    """Opt-in child uses the pinned Main owner, never Stage's import identity."""
    if not config.get("close_review_completion_enabled") or stage_id not in CLOSE_STAGES:
        return {"status": "DISABLED"}
    if receipt.get("dispatch_mode") not in {"NATURAL", "RECOVERY"}:
        return {"status": "SKIPPED_NON_NATURAL"}
    binding = config["research_owner_binding"]
    app = Path(binding["app_root"])
    import hashlib
    if hashlib.sha256((app.parent / "release-manifest.json").read_bytes()).hexdigest() != binding["manifest_sha256"]:
        raise ValueError("COMPLETION_MAIN_MANIFEST_CHANGED")
    main_plist = Path.home() / "Library/LaunchAgents/com.lexi.v4.scheduler.plist"
    main_env = plistlib.loads(main_plist.read_bytes())["EnvironmentVariables"]
    if (main_env.get("V4_APP_ROOT") != str(app) or main_env.get("V4_RELEASE_ID") != binding["release_id"]
        or main_env.get("V4_RELEASE_MANIFEST_SHA256") != binding["manifest_sha256"]):
        raise ValueError("COMPLETION_MAIN_LOADED_BINDING_NOT_CURRENT")
    env = os.environ.copy()
    env.update(main_env)
    for name in list(env):
        if name.startswith("V4_SCHEDULER_LANE_") or name in {"V4_SCHEDULER_RESOLVED_DATE", "V4_SCHEDULER_RESOLVED_SLOT"}:
            env.pop(name)
    env.update(V4_APP_ROOT=str(app), V4_RELEASE_ID=binding["release_id"],
               V4_RELEASE_MANIFEST_PATH=str(app.parent / "release-manifest.json"), V4_RELEASE_MANIFEST_SHA256=binding["manifest_sha256"],
               PYTHONPATH=str(app / "upstreams"), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-B", "-m", "ops.consume_close_stage_completion", "--date", trade_date,
        "--stage-id", stage_id, "--selection-root", str(config["selection_root"]), "--receipt-root", str(config["receipt_root"]),
        "--data-root", str(config["v4_research_data_root"]), "--ledger-root", str(config["research_scheduler_ledger_root"])],
        cwd=app, env=env, capture_output=True, text=True, timeout=240, check=False)
    return {"status": "DELIVERED" if result.returncode == 0 else "CANNOT_CONFIRM", "exit_code": result.returncode,
            "stdout": result.stdout[-2000:], "stderr": result.stderr[-1000:]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--stage-id", choices=tuple(CLOSE_STAGES), required=True)
    for name in ("selection-root", "receipt-root", "data-root", "ledger-root"): parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = consume(trade_date=args.date, stage_id=args.stage_id, selection_root=args.selection_root, receipt_root=args.receipt_root, data_root=args.data_root, ledger_root=args.ledger_root)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] in {"SUCCEEDED", "DUPLICATE_WORKLOAD_SKIPPED", "CONCURRENCY_SKIPPED", "EXPIRED"} else 1)
