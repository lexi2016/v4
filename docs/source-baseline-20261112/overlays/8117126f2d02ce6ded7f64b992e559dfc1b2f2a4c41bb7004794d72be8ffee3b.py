"""Default-off notifications after the authoritative Stage receipt commits."""
from __future__ import annotations
import importlib
import logging
import json
import os
from pathlib import Path


def deliver(*, config, trade_date, stage_id, receipt, settled, mode):
    if not settled or mode not in {"NATURAL", "RECOVERY"}: return []
    results = []
    for enabled, module_name, function_name in (
        (config.get("close_review_completion_enabled"), "ops.consume_close_stage_completion", "notify"),
        (config.get("report_evidence_sidecar_enabled"), "infrastructure.report_evidence_sidecar", "on_stage_completed"),
    ):
        if enabled:
            try:
                callback = getattr(importlib.import_module(module_name), function_name)
                value = callback(config=config, trade_date=trade_date, stage_id=stage_id, receipt=receipt)
                results.append({"consumer": module_name, "result": value})
            except Exception as error:
                logging.getLogger(__name__).exception("STAGE_COMPLETION_CONSUMER_FAILED:%s:%s", module_name, error)
                results.append({"consumer": module_name, "status": "CANNOT_CONFIRM", "error": f"{type(error).__name__}:{error}"})
    return results


def on_main_milestone(*, selection_root, trade_date, stage_id, usable):
    """The existing Main milestone consumes the same committed Stage envelope."""
    if os.environ.get("V4_STAGE_REPORT_EVIDENCE_ENABLED") != "1": return {"status": "DISABLED"}
    if not usable: return {"status": "EVIDENCE_GAP", "reason": "STAGE_NOT_COMPLETE"}
    config = {"selection_root": str(selection_root), "receipt_root": str(Path(selection_root).parent / "receipts"),
              "report_evidence_sidecar_enabled": True}
    try:
        path = Path(config["receipt_root"]) / trade_date / stage_id / "receipt.json"
        receipt = json.loads(path.read_bytes())
        return {"status": "COMPLETION_CONSUMED", "consumers": deliver(config=config, trade_date=trade_date,
            stage_id=stage_id, receipt=receipt, settled=True, mode="NATURAL")}
    except Exception as error:
        return {"status": "EVIDENCE_GAP", "reason": type(error).__name__}
