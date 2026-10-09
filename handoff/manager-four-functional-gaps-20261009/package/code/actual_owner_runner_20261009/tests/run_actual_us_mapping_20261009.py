from __future__ import annotations
import hashlib, json, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

E = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_REAL_RESULT_RECOVERY_20261009")
SOURCE = E / "candidate/original_r3_business_source"
DATA = E / "outputs/us_mapping_recovery/input_data"
EXPECTED = {
    "research/peripherals/20261008/external_finance.json": "6c96e5bb2681e8407670d5f79cafd014935d3e6592130102157d54759c64aa16",
    "receipts/research/peripherals/20261008/external_finance.json": "fab53928b64ec6764fb26bc6a3b8ec5d69d9927859c11ae18771f323672d7e4b",
}
for relative, sha in EXPECTED.items():
    actual = hashlib.sha256((DATA / relative).read_bytes()).hexdigest()
    if actual != sha:
        raise SystemExit(f"INPUT_SHA_MISMATCH:{relative}")
sys.path.insert(0, str(SOURCE))
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader
from v4.manager_research.workspace_projection import HK

now = datetime.now(HK)
run_key = now.strftime("%Y%m%dT%H%M%S%z")
run_root = E / "outputs/us_mapping_recovery/runs" / run_key
run_root.mkdir(parents=True, exist_ok=False)
manager_root = run_root / "manager_state"
owner = ManagerResearchJobService(
    ManagerResearchStore(manager_root), None, None,
    workspace_us_market_reader=ResearchPeripheralUsMarketReader(DATA),
)
try:
    result = owner.refresh_us_mapping_research(
        "20261009", now=now,
        execution_context={"trigger_kind": "MANUAL", "timing": "LATE_CATCHUP"},
    )
finally:
    owner.close()
product_path = manager_root / "us_mapping_research" / "20261009" / "runs" / f"{result.get('run_id')}.json" if result.get("run_id") else None
summary = {
    "actual_invoked_method": "ManagerResearchJobService.refresh_us_mapping_research",
    "target_trade_date": "20261009",
    "actual_started_at": result.get("execution_context", {}).get("started_at"),
    "actual_finished_at": result.get("execution_context", {}).get("finished_at"),
    "natural_run_verified": result.get("execution_context", {}).get("natural_run_verified"),
    "trigger_kind": result.get("execution_context", {}).get("trigger_kind"),
    "timing": result.get("execution_context", {}).get("timing"),
    "research_cutoff_policy": result.get("research_cutoff_policy"),
    "status": result.get("status"),
    "execution_status": result.get("execution_status"),
    "run_id": result.get("run_id"),
    "generated_at": result.get("generated_at"),
    "artifact_sha256": result.get("artifact_sha256"),
    "us_session_date": result.get("us_session_date"),
    "coverage": result.get("coverage"),
    "match_count": len(result.get("matches") or []),
    "gaps": result.get("gaps"),
    "input_payload_sha256": EXPECTED["research/peripherals/20261008/external_finance.json"],
    "input_receipt_sha256": EXPECTED["receipts/research/peripherals/20261008/external_finance.json"],
    "reader_lineage": result.get("source_identity") or result.get("coverage", {}).get("source_identity"),
    "safety": {key: result.get(key) for key in ("RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent")},
    "run_root": str(run_root),
    "product_path": str(product_path) if product_path and product_path.exists() else None,
}
summary["summary_sha256"] = hashlib.sha256(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
out = run_root / "actual_owner_result_summary.json"
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
