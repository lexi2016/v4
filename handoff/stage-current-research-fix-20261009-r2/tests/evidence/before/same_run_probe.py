#!/usr/bin/env python3
"""Read the original store and existing HTTP projection for one exact run."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-root", type=Path, required=True)
    parser.add_argument("--selection-root", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--date", default="20261009")
    parser.add_argument("--stage", default="STAGE_1545_1555")
    parser.add_argument("--market", choices=("A_SHARE", "HK_CONNECT"), default="HK_CONNECT")
    parser.add_argument("--run-id")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.api_root.resolve(strict=True)))
    from stage_center.consumer import StageSelectionConsumer
    consumer = StageSelectionConsumer(args.selection_root, execution_receipt_root=args.receipt_root)
    selected = (consumer.store._verify_run(args.date, args.stage, args.market, args.run_id)["envelope"]
                if args.run_id else consumer.store.read_verified(args.date, args.stage, args.market))
    run_id = selected["run_id"]
    local = consumer.get(args.date, args.stage, markets=(args.market,), selection_run_id=run_id)
    queries = {
        "exact_run": {"date": args.date, "stage": args.stage, "market": args.market,
                      "selection_run_id": run_id, "limit": 50},
        # The existing Vue workbench uses this ordinary query. Checking both
        # prevents an exact API URL from concealing a different page default.
        "page_default": {"date": args.date, "stage": args.stage, "limit": 50},
    }
    responses, issues = {}, []
    identities = ("run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256", "selected_rows")
    for name, query in queries.items():
        url = args.base_url.rstrip("/") + "/api/v3/workbench/stage?" + urlencode(query)
        try:
            with urlopen(url, timeout=20) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("response exceeds bound")
            payload = json.loads(raw)
            evidence = payload.get("execution_evidence") or {}
            summary = (evidence.get("selection_results") or {}).get(args.market) or {}
            for key in identities:
                if summary.get(key) != selected.get(key):
                    issues.append(f"{name}:{key}:DIFFERS_FROM_ORIGINAL_STORE")
            if any(payload.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
                issues.append(f"{name}:SAFETY_FLAG_CONFLICT")
            if evidence.get("natural_verified") is not False:
                issues.append(f"{name}:NATURAL_PROOF_MISLABELLED")
            responses[name] = {"url": url, "response_sha256": hashlib.sha256(raw).hexdigest(),
                               "payload": payload}
        except (OSError, ValueError, TypeError) as error:
            issues.append(f"{name}:{type(error).__name__}:{error}")
    evidence = local["execution_evidence"]
    trio = (evidence.get("selection_artifact_bindings") or {}).get(args.market) or {}
    if trio.get("status") != "BOUND_TO_VERIFIED_SELECTION_TRIO":
        issues.append("LOCAL_OWNER_RECEIPT_NOT_BOUND_TO_SELECTION_TRIO")
    if selected.get("input_mode") == "CURRENT_DAY_RESEARCH_ONLY":
        research = (evidence.get("input_binding_status") or {}).get(args.market) or {}
        if research.get("status") != "RESEARCH_INPUT_BOUND_TO_SELECTION_AND_OWNER_HISTORY":
            issues.append("LOCAL_RESEARCH_INPUT_NOT_BOUND")
        if evidence.get("attempt_mode") != "MANUAL_CURRENT_DAY_RESEARCH":
            issues.append("CURRENT_RESEARCH_EXECUTION_MODE_DIFFERS")
    result = {
        "schema_version": "v4.stage.same_run_readback.v2",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "SAME_RUN_VERIFIED" if not issues else "CANNOT_CONFIRM",
        "date": args.date, "stage_id": args.stage, "market": args.market,
        "selection_identity": {key: selected.get(key) for key in identities},
        "local_consumer": local, "http": responses, "issues": issues,
        "scope": "ORIGINAL_STORE_OWNER_RECEIPT_AND_EXISTING_API_EXACT_AND_PAGE_DEFAULT_QUERIES",
        "browser_render_acceptance": "PENDING_MAC_BROWSER", "natural_verified": False,
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "identity": result["selection_identity"],
                      "issues": issues, "report": str(args.report)}, ensure_ascii=False, indent=2))
    return 0 if not issues else 2


if __name__ == "__main__":
    raise SystemExit(main())
