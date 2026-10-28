"""Import a frozen VIPDOC daily panel into V4-owned close-snapshot storage."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from infrastructure.hkconnect_close_store import CloseSnapshotStore


_HK_CODE = re.compile(r"^HK\.(\d{1,5})$")


def _code(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = _HK_CODE.fullmatch(text)
    return f"HK.{int(match.group(1)):05d}" if match else ""


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_vipdoc_rows(
    trade_date: str,
    records: Iterable[Mapping[str, Any]],
    *,
    source_input_sha256: str,
    name_map: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    names = {str(code): str(name).strip() for code, name in (name_map or {}).items() if str(name).strip()}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in records:
        row_date = str(source.get("trade_date_compact") or source.get("trade_date") or "")
        code = _code(source.get("code_norm") or source.get("code"))
        close = _number(source.get("close"))
        pre_close = _number(source.get("pre_close"))
        if row_date != trade_date or not code or code in seen or close is None or pre_close in (None, 0.0):
            continue
        seen.add(code)
        amount = _number(source.get("amount")) or 0.0
        rows.append(
            {
                "trade_date": trade_date,
                "code": code,
                "name": names.get(code) or str(source.get("name") or "").strip(),
                "close": close,
                "pre_close": pre_close,
                "amount": amount,
                "pct_chg_close": round((close / pre_close - 1.0) * 100.0, 8),
                "source": "TDX_VIPDOC_DAILY_PANEL",
            }
        )
    rows.sort(key=lambda row: row["code"])
    return {
        "schema_version": "v3_5.hkconnect_close_snapshot.v1",
        "trade_date": trade_date,
        "status": "READY",
        "source_mode": "TDX_VIPDOC_DAILY_PANEL",
        "source_input_sha256": source_input_sha256,
        "universe_count": len(rows),
        "same_date_row_count": len(rows),
        "coverage_ratio": 1.0,
        "rows": rows,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _load_name_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, Mapping):
        return {str(code): str(name) for code, name in payload.items()}
    raise ValueError("name map must be a JSON object")


def import_vipdoc_file(
    *,
    data_root: Path,
    source: Path,
    trade_date: str,
    name_map_path: Path | None = None,
) -> dict[str, str]:
    import pandas as pd

    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    frame = pd.read_parquet(source)
    payload = normalize_vipdoc_rows(
        trade_date,
        frame.to_dict(orient="records"),
        source_input_sha256=source_sha,
        name_map=_load_name_map(name_map_path),
    )
    return CloseSnapshotStore(data_root).import_snapshot(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a verified VIPDOC HK Connect close panel")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--name-map", type=Path)
    args = parser.parse_args()
    result = import_vipdoc_file(
        data_root=args.data_root,
        source=args.source,
        trade_date=args.date,
        name_map_path=args.name_map,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
