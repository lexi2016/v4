"""Replay verified original raw, request supported historical minutes, or record a gap.

All outputs are immutable recovery evidence outside the original Stage roots.
This command never advances a selection/latest pointer or rewrites a receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from infrastructure.owned_io import SafeRoot
from stage_center.contracts import STAGE_BY_ID

FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def recover(*, config, trade_date, stage_id, market, action, output, symbols=(), provider=None):
    datetime.strptime(trade_date, "%Y%m%d")
    if stage_id not in STAGE_BY_ID or market not in STAGE_BY_ID[stage_id].markets:
        raise ValueError("RECOVERY_STAGE_MARKET_INVALID")
    output = Path(output).absolute()
    for key in ("raw_root", "selection_root", "receipt_root"):
        root = Path(config[key]).resolve()
        if output.resolve().is_relative_to(root) or root.is_relative_to(output.resolve()):
            raise ValueError("RECOVERY_OUTPUT_MUST_BE_ISOLATED")
    source_receipt = Path(config["receipt_root"]) / trade_date / stage_id / "receipt.json"
    original = source_receipt.read_bytes() if source_receipt.is_file() else None
    report = {"schema_version": "v4.stage_data_recovery.v1", "attempt_id": uuid4().hex,
        "trade_date": trade_date, "stage_id": stage_id, "market": market, "action": action,
        "requested_at": datetime.now(timezone.utc).isoformat(), "original_receipt_path": str(source_receipt),
        "original_receipt_sha256": hashlib.sha256(original).hexdigest() if original is not None else None,
        "status": "CANNOT_CONFIRM", "network_invocations": 0, "afterfact": action == "historical-minute",
        "natural_execution_verified": False, "pit_safe": False, "cannot_confirm": [], **FLAGS}
    rows = None
    raw = None
    try:
        if action == "replay-original":
            from stage_center.raw_store import RawStore
            from stage_center.runner import _read_verified_raw_source
            verified = RawStore(config["raw_root"]).verify_latest(trade_date, stage_id, market)["verified"]
            source = _read_verified_raw_source(Path(config["raw_root"]), verified)
            rows = list(source.rows)
            report.update(status="ORIGINAL_RAW_REPLAYED", source=verified, replayed_rows=len(rows), afterfact=False)
            report["cannot_confirm"] = list(source.cannot_confirm)
        elif action == "historical-minute":
            if market != "A_SHARE" or not symbols or len(symbols) > 3:
                raise ValueError("HISTORICAL_API_ONLY_BOUNDED_A_MINUTE_ROUTE_CONFIRMED")
            from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider
            active = provider or TdxMinuteReplayProvider()
            cutoff = STAGE_BY_ID[stage_id].cutoff
            cutoff_at = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T{cutoff}+08:00"
            report["network_invocations"] = 1
            batch = active.snapshot(symbols, trade_date=trade_date, stage_id=stage_id, cutoff_at=cutoff_at)
            rows = batch["rows"]
            raw = [{"request": list(key), "sha256": digest, "response": value} for key, (digest, value) in active._request_cache.items()]
            report.update(status="AFTERFACT_MINUTE_OBSERVATION", provider=batch["source"], cutoff_at=cutoff_at,
                replayed_rows=len(rows), source_time="TDX_IMPLICIT_MINUTE_SEQUENCE", amount_basis="SUM_MINUTE_PRICE_X_VOLUME_X100")
            report["cannot_confirm"] = [*batch.get("cannot_confirm", []), "ORIGINAL_CAPTURE_TIME_NOT_RECOVERED", "MINUTE_VOLUME_UNIT_NOT_INDEPENDENTLY_CERTIFIED", "ORDERBOOK_FIELDS_UNAVAILABLE", "NOT_ORIGINAL_STAGE_SELECTION"]
        elif action == "record-gap":
            report["cannot_confirm"] = ["ORIGINAL_POINT_IN_TIME_FIELDS_NOT_RECOVERABLE_WITH_CONFIRMED_API"]
        else:
            raise ValueError("RECOVERY_ACTION_INVALID")
    except Exception as error:
        report["status"] = "CANNOT_CONFIRM"
        report["error"] = f"{type(error).__name__}:{error}"
        report["cannot_confirm"].append("RECOVERY_INPUT_OR_API_UNAVAILABLE")
    finally:
        current = source_receipt.read_bytes() if source_receipt.is_file() else None
        if current != original:
            report.update(status="CANNOT_CONFIRM", original_receipt_unchanged=False)
            report["cannot_confirm"].append("ORIGINAL_RECEIPT_CHANGED_DURING_RECOVERY")
        else: report["original_receipt_unchanged"] = True
        io = SafeRoot(output)
        prefix = f"{trade_date}/{stage_id}/{report['attempt_id']}"
        if rows is not None:
            encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
            io.write_bytes(prefix + "/replayed_rows.json", encoded, require_absent=True)
            report["rows_sha256"] = hashlib.sha256(encoded).hexdigest()
        if raw is not None:
            encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
            io.write_bytes(prefix + "/raw_response.json", encoded, require_absent=True)
            report["raw_response_sha256"] = hashlib.sha256(encoded).hexdigest()
        io.write_bytes(prefix + "/recovery_receipt.json", json.dumps(report, ensure_ascii=False, sort_keys=True).encode(), require_absent=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--stage-id", required=True)
    parser.add_argument("--market", choices=("A_SHARE", "HK_CONNECT"), required=True)
    parser.add_argument("--action", choices=("replay-original", "historical-minute", "record-gap"), required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--symbols", default="")
    args = parser.parse_args()
    result = recover(config=json.loads(args.config.read_bytes()), trade_date=args.date, stage_id=args.stage_id,
        market=args.market, action=args.action, output=args.output, symbols=tuple(v for v in args.symbols.split(",") if v))
    print(json.dumps({k: result.get(k) for k in ("status", "attempt_id", "trade_date", "stage_id", "market", "replayed_rows", "network_invocations", "afterfact", "original_receipt_unchanged", "rows_sha256", "raw_response_sha256", "error")}, ensure_ascii=False))
    raise SystemExit(0 if result["status"] != "CANNOT_CONFIRM" else 3)
