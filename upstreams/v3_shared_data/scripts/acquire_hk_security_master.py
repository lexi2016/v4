"""Acquire one verified HK Connect security master from local Futu OpenD."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.hk_security_master import (
    load_verified_hk_security_master,
    publish_hk_security_master,
)
from shared_data.hashing import sha256_json
from shared_data.paths import resolve_under
from shared_data.store import StoreError
from scripts.acquire_stage_raw import resolve_futu_python
from scripts.live_acquisition.universe import (
    HK_CONNECT_MIN_FULL_COUNT,
    normalize_symbol,
    resolve_stage_universe,
)


MARKER = "__FUTU_HK_SECURITY_MASTER_JSON__"
_PROBE = r'''
import json
import sys
import futu as ft

payload = json.loads(sys.stdin.read())
codes = payload["codes"]
ctx = ft.OpenQuoteContext(host="127.0.0.1", port=11111)
rows = []
errors = []
try:
    for start in range(0, len(codes), 300):
        chunk = codes[start:start + 300]
        ret, data = ctx.get_market_snapshot(chunk)
        if ret != ft.RET_OK:
            errors.append({"codes": chunk[:5], "count": len(chunk), "error": str(data)})
            continue
        rows.extend(data.to_dict(orient="records"))
finally:
    ctx.close()
fields = ("code", "name", "outstanding_shares", "circular_market_val", "listing_date", "lot_size", "stock_owner", "stock_child_type", "sec_status")
projected = [{key: row.get(key) for key in fields} for row in rows]
print("__FUTU_HK_SECURITY_MASTER_JSON__" + json.dumps({"rows": projected, "errors": errors}, ensure_ascii=False, default=str))
'''


def collect_futu_hk_security_master(
    python_path: Path | str,
    codes: list[str],
    *,
    process_runner: Callable[..., Any] = subprocess.run,
    timeout_seconds: float = 90,
) -> list[dict[str, Any]]:
    python_path = Path(python_path)
    if not python_path.is_file():
        raise StoreError(f"Futu Python missing: {python_path}")
    if not codes or len(set(codes)) != len(codes) or any(
        not isinstance(code, str) or not code.startswith("HK.") or len(code) != 8
        for code in codes
    ):
        raise StoreError("HK security-master codes invalid")
    proc = process_runner(
        [str(python_path), "-c", _PROBE],
        input=json.dumps({"codes": codes}, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        shell=False,
    )
    if proc.returncode != 0:
        raise StoreError(f"Futu security-master probe failed: {str(proc.stderr or proc.stdout)[-1000:]}")
    payload = None
    for line in reversed((proc.stdout or "").splitlines()):
        if line.startswith(MARKER):
            raw_payload = line[len(MARKER):].strip()
            try:
                # The OpenD child can append a same-line diagnostic after the
                # marker payload.  Keep the marker authoritative and decode
                # exactly one JSON value, matching the live Futu bridge.
                payload = json.JSONDecoder().raw_decode(raw_payload)[0]
            except (TypeError, ValueError) as exc:
                raise StoreError("Futu security-master payload invalid") from exc
            break
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise StoreError("Futu security-master payload invalid")
    if payload.get("errors"):
        raise StoreError("Futu security-master snapshot incomplete: " + json.dumps(payload["errors"], ensure_ascii=False)[:1000])
    by_code = {str(row.get("code") or ""): row for row in payload["rows"] if isinstance(row, dict)}
    if set(by_code) != set(codes):
        missing = sorted(set(codes) - set(by_code))
        raise StoreError(f"Futu security-master coverage incomplete: {len(by_code)}/{len(codes)} missing={missing[:10]}")
    for code, row in by_code.items():
        if not str(row.get("name") or "").strip():
            raise StoreError(f"Futu security-master name missing: {code}")
    return [by_code[code] for code in codes]


def _load_exact_date_hk_panel_codes(
    store_root: Path | str, trade_date: str
) -> tuple[list[str], str]:
    """Resolve the exact-date HK panel when its formal universe CAS is absent.

    The daily HK 0.2 panel is the upstream producer for the signal-date
    reference set.  It is allowed to seed the security-master code list only
    when its own manifest proves ``panel_max_date == trade_date``; no prior
    panel or current-day snapshot is substituted.
    """
    root = Path(store_root)
    asset_root = root / "assets" / "hk_0_2"
    try:
        latest = json.loads(
            (asset_root / "panel_latest.json").read_text(encoding="utf-8")
        )
        manifest_path = resolve_under(
            asset_root, str(latest["manifest_relative"])
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(manifest.get("panel_max_date") or "") != trade_date:
            raise StoreError(
                "HK exact-date panel max date mismatch: "
                f"{manifest.get('panel_max_date')!r} != {trade_date!r}"
            )
        panel_path = resolve_under(
            asset_root, str(manifest["panel_relative"])
        )
        import pandas as pd

        frame = pd.read_parquet(
            panel_path,
            columns=["trade_date_compact", "code_norm"],
        )
        dates = frame["trade_date_compact"].astype(str).str.replace(
            "-", "", regex=False
        )
        codes = sorted(
            {
                normalize_symbol(str(value), "HK_CONNECT")
                for value in frame.loc[dates.eq(trade_date), "code_norm"].dropna()
            }
        )
    except (OSError, KeyError, TypeError, ValueError, ImportError) as error:
        raise StoreError(
            f"HK exact-date panel codes unavailable for {trade_date}: {error}"
        ) from error
    if len(codes) < HK_CONNECT_MIN_FULL_COUNT:
        raise StoreError(
            "HK exact-date panel code coverage below minimum: "
            f"{len(codes)} < {HK_CONNECT_MIN_FULL_COUNT}"
        )
    return codes, sha256_json(codes)


def ensure_hk_security_master(
    store_root: Path | str,
    trade_date: str,
    python_path: Path | str,
    *,
    collector: Callable[..., list[dict[str, Any]]] = collect_futu_hk_security_master,
) -> dict[str, Any]:
    store_root = Path(store_root)
    try:
        universe = resolve_stage_universe(store_root, trade_date, "HK_CONNECT")
        universe_codes = list(universe.codes)
        universe_codes_sha256 = universe.codes_sha256
    except ValueError as error:
        if "trusted universe manifest missing" not in str(error):
            raise
        universe_codes, universe_codes_sha256 = _load_exact_date_hk_panel_codes(
            store_root, trade_date
        )
    try:
        rows, manifest = load_verified_hk_security_master(store_root, trade_date)
    except StoreError:
        rows, manifest = {}, {}
    if (
        manifest.get("universe_codes_sha256") == universe_codes_sha256
        and manifest.get("valuation_eligibility_field") == "circular_market_val"
        and set(rows) == set(universe_codes)
    ):
        return {
            "ok": True,
            "status": "READY",
            "reused": True,
            "row_count": len(rows),
            "run_id": manifest.get("run_id"),
        }
    collected = collector(Path(python_path), universe_codes)
    published = publish_hk_security_master(
        store_root,
        trade_date=trade_date,
        rows=collected,
        universe_codes_sha256=universe_codes_sha256,
        captured_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    return {
        "ok": True,
        "status": "READY",
        "reused": False,
        "row_count": published["row_count"],
        "run_id": published["run_id"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", required=True)
    args = parser.parse_args(argv)
    root_text = str(os.environ.get("V3_SHARED_DATA_STORE_ROOT") or "").strip()
    try:
        if not root_text:
            raise StoreError("V3_SHARED_DATA_STORE_ROOT missing")
        result = ensure_hk_security_master(
            Path(root_text), args.trade_date, resolve_futu_python()
        )
    except (OSError, StoreError, ValueError) as error:
        result = {"ok": False, "status": "FAILED", "error": str(error)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
