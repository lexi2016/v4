"""Three representative read-only TDX queries, only during the real A session."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from infrastructure.owned_io import SafeRoot
from infrastructure.tdx_minute_replay_provider import _connected_api

SAMPLES = (("SH", 1, "600000"), ("SZ", 0, "000001"), ("BJ", 0, "920001"))


def run(output, *, now=None, api_factory=_connected_api):
    from contracts.trading_calendar import load_market_calendar, resolve_market_states, TradingDayState
    moment = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    day = moment.strftime("%Y%m%d"); clock = moment.strftime("%H:%M:%S")
    states = resolve_market_states(load_market_calendar(), day)
    morning = "09:30:00" <= clock <= "11:30:00"
    afternoon = "13:00:00" <= clock <= "15:00:00"
    eligible = ((states["a_share"] == TradingDayState.FULL_TRADING_DAY and (morning or afternoon))
        or (states["a_share"] == TradingDayState.HALF_TRADING_DAY_AM and morning))
    report = {"schema_version": "v4.tdx_three_market_canary.v1", "observed_at": moment.isoformat(),
        "date": day, "sample_rule": "SH600000,SZ000001,BJ920001; source time/unit/raw fields; all independently confirmed to PASS",
        "status": "CANNOT_CONFIRM", "network_invocations": 0, "samples": [],
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    if not eligible:
        report["reason"] = "OUTSIDE_REAL_TRADING_WINDOW"
        report["samples"] = [{"market": market, "code": code, "status": "CANNOT_CONFIRM", "source_time": None, "unit": None, "raw_response": None} for market, _, code in SAMPLES]
    else:
        api = api_factory()
        try:
            for market, number, code in SAMPLES:
                try:
                    report["network_invocations"] += 1
                    raw = api.get_security_quotes([(number, code)])
                    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str).encode()
                    report["samples"].append({"market": market, "code": code, "status": "CANNOT_CONFIRM",
                        "raw_response": raw, "raw_response_sha256": hashlib.sha256(encoded).hexdigest(),
                        "source_time_fields": [{k: v for k, v in row.items() if "time" in k.lower()} for row in (raw or [])],
                        "fields": sorted(raw[0]) if raw else [], "unit": None,
                        "reason": "SOURCE_TIMESTAMP_AND_UNITS_REQUIRE_INDEPENDENT_ATTESTATION"})
                except Exception as error:
                    report["samples"].append({"market": market, "code": code, "status": "CANNOT_CONFIRM", "error": f"{type(error).__name__}:{error}"})
        finally: api.disconnect()
    SafeRoot(output).write_bytes("tdx-trade-window-canary.json", json.dumps(report, ensure_ascii=False, sort_keys=True, default=str).encode(), require_absent=True)
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(); result = run(args.output)
    print(json.dumps({"status": result["status"], "reason": result.get("reason"), "network_invocations": result["network_invocations"]}))
