"""Read-only existing OpenD quote-chain evidence; writes research-local files only.

Does not import/publish a close snapshot, alter selection, or query trade accounts.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
from pathlib import Path
import sys
import time


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def save(root, name, value):
    raw = encode(value)
    path = root / name
    if path.exists():
        raise ValueError("IMMUTABLE_RESEARCH_CAPTURE_ALREADY_EXISTS")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    args = parser.parse_args()
    if "local_only/research" not in str(args.raw_root):
        raise ValueError("RAW_PATH_MUST_BE_LOCAL_ONLY_RESEARCH")
    args.raw_root.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(args.runtime), str(args.runtime/"upstreams")]
    from ops.collect_hkconnect_close_snapshot import HKCONNECT_PLATE_CODES, _default_quote_context_factory
    import pandas as pd
    def clean(value):
        if isinstance(value, dict):return {str(k):clean(v) for k,v in value.items()}
        if isinstance(value, list):return [clean(v) for v in value]
        if value is None or (not isinstance(value,(dict,list)) and pd.isna(value)):return None
        if hasattr(value,"item"):return clean(value.item())
        return value
    started = datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat()
    if started[:10] != "2026-10-20" or started[11:19] < "16:10:00":
        raise ValueError("CURRENT_DATE_OR_FINAL_CLOSE_CUTOFF_MISMATCH")
    quote = _default_quote_context_factory()
    plates=[];batches=[]
    try:
        universe={}
        for code in HKCONNECT_PLATE_CODES:
            status,frame=quote.get_plate_stock(code)
            if status != 0:raise RuntimeError("PLATE_READ_FAILED:"+code+":"+str(frame))
            rows=clean(frame.to_dict(orient="records"))
            plates.append(dict(plate_code=code,rows=rows))
            for row in rows:
                symbol=row.get("code")
                if symbol and symbol.startswith("HK."):universe[symbol]=row.get("stock_name") or row.get("name")
        codes=sorted(universe)
        if len(codes)<600:raise ValueError("CURRENT_HK_CONNECT_SCOPE_TOO_SMALL")
        universe_sha=save(args.raw_root,"top20-universe-frozen.json",dict(target_date="20261020",captured_at=started,plate_codes=list(HKCONNECT_PLATE_CODES),codes=codes,plates=plates))
        for offset in range(0,len(codes),200):
            queried_at=datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat()
            status,frame=quote.get_market_snapshot(codes[offset:offset+200])
            if status != 0:raise RuntimeError("SNAPSHOT_READ_FAILED:"+str(offset)+":"+str(frame))
            batches.append(dict(offset=offset,queried_at=queried_at,requested_codes=codes[offset:offset+200],rows=clean(frame.to_dict(orient="records"))))
            if offset+200<len(codes):time.sleep(1)
    finally:
        quote.close()
    completed=datetime.now(ZoneInfo("Asia/Hong_Kong")).isoformat()
    snapshots=[row for batch in batches for row in batch["rows"]]
    codes_returned=[row["code"] for row in snapshots]
    if len(codes_returned)!=len(set(codes_returned)):raise ValueError("DUPLICATE_SNAPSHOT_CODES")
    raw_sha=save(args.raw_root,"top20-current-close-snapshots.json",dict(target_date="20261020",provider="FUTU_OPENAPI",api="get_market_snapshot",scope_source="get_plate_stock",chain="ops.collect_hkconnect_close_snapshot read-only factory and same plate/batch parameters; no publication",started_at=started,completed_at=completed,universe_sha256=universe_sha,batches=batches,RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False))
    print(json.dumps(dict(started_at=started,completed_at=completed,universe_count=len(codes),snapshot_count=len(snapshots),missing_snapshot_count=len(set(codes)-set(codes_returned)),update_date_counts=dict(Counter(str(r.get("update_time"))[:10] for r in snapshots)),raw_sha256=raw_sha,universe_sha256=universe_sha),ensure_ascii=False))


if __name__=="__main__":main()
