"""Build a compact exact-name registry from a verified Mac selector panel."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def build(source: Path, destination: Path) -> dict[str, object]:
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    parquet = pq.ParquetFile(source)
    latest_group = parquet.read_row_group(
        parquet.num_row_groups - 1,
        columns=["trade_date", "ts_code", "name"],
    )
    dates = [str(value or "").replace("-", "")[:8] for value in latest_group["trade_date"].to_pylist()]
    latest_date = max(dates)
    rows: dict[str, tuple[str, str, str]] = {}
    for row_date, raw_code, raw_name in zip(
        dates,
        latest_group["ts_code"].to_pylist(),
        latest_group["name"].to_pylist(),
    ):
        ts_code = str(raw_code or "").strip().upper()
        name = str(raw_name or "").strip()
        if row_date == latest_date and len(ts_code) == 9 and len(name) >= 2:
            rows.setdefault(ts_code, (latest_date, ts_code, name))
    if len(rows) < 1000:
        raise ValueError(f"selector security master too small: {len(rows)}")
    table = pa.table(
        {
            "trade_date": [row[0] for row in rows.values()],
            "ts_code": [row[1] for row in rows.values()],
            "name": [row[2] for row in rows.values()],
        }
    )
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    pq.write_table(table, temporary, compression="zstd")
    os.replace(temporary, destination)
    return {
        "status": "READY",
        "selector_date": latest_date,
        "row_count": len(rows),
        "destination": str(destination),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.source, arguments.destination), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
