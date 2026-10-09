#!/usr/bin/env python3
"""Read the original store and existing HTTP projection for one exact run."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

import stage_patch

IDENTITIES = ("trade_date", "stage_id", "market", "run_id", "artifact_id", "algorithm_sha256",
              "raw_artifact_sha256", "selected_rows")


def market_object(evidence, key, market):
    section = evidence.get(key)
    value = section.get(market) if isinstance(section, dict) else None
    return value if isinstance(value, dict) else {}


def projection_issues(payload, selected, market, name):
    """Malformed JSON projections fail into evidence, without escaping the probe."""
    if not isinstance(payload, dict):
        return [f"{name}:RESPONSE_NOT_JSON_OBJECT"]
    evidence = payload.get("execution_evidence")
    if not isinstance(evidence, dict):
        return [f"{name}:EXECUTION_EVIDENCE_NOT_JSON_OBJECT"]
    summary = market_object(evidence, "selection_results", market)
    issues = []
    for key in IDENTITIES:
        if selected.get(key) is None or summary.get(key) != selected[key]:
            issues.append(f"{name}:{key}:DIFFERS_FROM_ORIGINAL_STORE")
    for key in ("runtime_source_identity", "hk_current_day_research"):
        if key in selected and summary.get(key) != selected[key]:
            issues.append(f"{name}:{key}:DIFFERS_FROM_ORIGINAL_STORE")
    if any(payload.get(flag) is not value for flag, value in stage_patch.FLAGS.items()):
        issues.append(f"{name}:SAFETY_FLAG_CONFLICT")
    if evidence.get("natural_verified") is not False:
        issues.append(f"{name}:NATURAL_PROOF_MISLABELLED")
    if market_object(evidence, "selection_artifact_bindings", market).get("status") != "BOUND_TO_VERIFIED_SELECTION_TRIO":
        issues.append(f"{name}:OWNER_RECEIPT_NOT_BOUND_TO_SELECTION_TRIO")
    if isinstance(selected.get("runtime_source_identity"), dict):
        if market_object(evidence, "selection_source_bindings", market).get("status") != "SELECTION_SOURCE_IDENTITY_BOUND_TO_TRIO_AND_OWNER_HISTORY":
            issues.append(f"{name}:SOURCE_IDENTITY_NOT_BOUND_TO_SELECTION_AND_OWNER")
    if selected.get("input_mode") == "CURRENT_DAY_RESEARCH_ONLY":
        if market_object(evidence, "input_binding_status", market).get("status") != "RESEARCH_INPUT_BOUND_TO_SELECTION_AND_OWNER_HISTORY":
            issues.append(f"{name}:RESEARCH_INPUT_NOT_BOUND")
        if evidence.get("attempt_mode") != "MANUAL_CURRENT_DAY_RESEARCH":
            issues.append(f"{name}:CURRENT_RESEARCH_EXECUTION_MODE_DIFFERS")
    if market == "A_SHARE" and market_object(evidence, "input_binding_status", market).get("status") != "OWNER_DECLARED_INPUT_BOUND_TO_SELECTION":
        issues.append(f"{name}:A_INPUT_NOT_BOUND_TO_SELECTION_AND_OWNER")
    return issues


def probe(args):
    address = urlsplit(args.base_url)
    if address.scheme not in ("http", "https") or not address.netloc or address.query or address.fragment:
        raise ValueError("base-url must be an HTTP(S) origin or application prefix")
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
    for name, query in queries.items():
        url = args.base_url.rstrip("/") + "/api/v3/workbench/stage?" + urlencode(query)
        try:
            with urlopen(url, timeout=20) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("response exceeds bound")
            payload = json.loads(raw)
            issues.extend(projection_issues(payload, selected, args.market, name))
            responses[name] = {"url": url, "response_sha256": hashlib.sha256(raw).hexdigest(),
                               "payload": payload}
        except (OSError, ValueError, TypeError) as error:
            issues.append(f"{name}:{type(error).__name__}:{error}")
    issues.extend(projection_issues(local, selected, args.market, "local"))
    result = {
        "schema_version": "v4.stage.same_run_readback.v2",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "SAME_RUN_VERIFIED" if not issues else "CANNOT_CONFIRM",
        "date": args.date, "stage_id": args.stage, "market": args.market,
        "selection_identity": {key: selected.get(key) for key in IDENTITIES},
        "local_consumer": local, "http": responses, "issues": issues,
        "scope": "ORIGINAL_STORE_OWNER_RECEIPT_AND_EXISTING_API_EXACT_AND_PAGE_DEFAULT_QUERIES",
        "browser_render_acceptance": "PENDING_MAC_BROWSER", "natural_verified": False,
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    return result


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
    forbidden = (args.api_root, args.selection_root, args.receipt_root)
    try:
        report = stage_patch.new_report_path(args.report, forbidden_roots=forbidden)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "CANNOT_CONFIRM", "error": str(error)}))
        return 2
    try:
        result = probe(args)
    except (OSError, ValueError, TypeError, KeyError, ImportError, RuntimeError) as error:
        result = {"schema_version": "v4.stage.same_run_readback.v2", "status": "CANNOT_CONFIRM",
                  "checked_at": datetime.now(timezone.utc).isoformat(),
                  "date": args.date, "stage_id": args.stage, "market": args.market,
                  "selection_identity": {}, "issues": [f"{type(error).__name__}: {error}"],
                  "browser_render_acceptance": "PENDING_MAC_BROWSER", "natural_verified": False,
                  **stage_patch.FLAGS}
    try:
        stage_patch.write_new_report(report, json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                     forbidden_roots=forbidden)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "CANNOT_CONFIRM", "error": str(error)}))
        return 2
    print(json.dumps({"status": result["status"], "identity": result["selection_identity"],
                      "issues": result["issues"], "report": str(report)}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "SAME_RUN_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
