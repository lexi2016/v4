#!/usr/bin/env python3
"""Read-only, SHA-gated metadata audit for the three frozen HK parquet inputs.

This is an audit helper, not a data producer. It writes only metadata summaries
beside this script and never exports source OHLCV rows or values.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import statistics
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


OUT_DIR = Path(__file__).resolve().parent
RTOL = 1e-6
ATOL = 1e-6

DATASETS = {
    "A": {
        "label": "old_feature_613",
        "path": Path(
            "/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/"
            "versions/20260722/20260722_20260722_172235_10744/feature.parquet"
        ),
        "sha256": "1437f5198e6d7a537bc2a11ad17e86042bb9ca2c894ad341126c0a7c05d0052e",
        "size_bytes": 139225381,
        "columns": ["symbol", "asof_date", "trade_date", "amount_1d", "volume_1d", "ret_1d"],
    },
    "B": {
        "label": "overnight_daily_bars_691",
        "path": Path(
            "/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/"
            "versions/20260912/20260912_operator_d1_overnight/daily_bars.parquet"
        ),
        "sha256": "17f5b62b6ec0264d48b6ee66ce0cd31aa8c1deb661e3e765b90b780add2eb230",
        "size_bytes": 17142047,
        "columns": ["code", "date", "open", "high", "low", "close", "amount", "trade"],
    },
    "C": {
        "label": "runtime_panel_717",
        "path": Path(
            "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/"
            "workspace/v3_shared_data/.runtime/data/assets/hk_0_2/panels/"
            "20261014-3958528f3441/hkconnect_vipdoc_daily_panel.parquet"
        ),
        "sha256": "3958528f34416925df7d5e5ba4bfdde4e92ad35494b1712eacc20013df59cb37",
        "size_bytes": 21117431,
        "columns": [
            "code_norm", "trade_date", "open", "high", "low", "close",
            "amount", "trade", "pct_chg",
        ],
    },
}

EXPECTED_CODE_COUNTS = {"A": 613, "B": 691, "C": 717}
EXPECTED_CODE_SET_COUNTS = {
    "A_intersect_B": 597,
    "A_minus_B": 16,
    "B_minus_A": 94,
    "A_minus_C": 0,
    "C_minus_A": 104,
    "B_minus_C": 0,
    "C_minus_B": 26,
    "C_minus_A_union_B": 10,
    "union": 717,
}

PRESERVATION_COMPANIONS = [
    {
        "dataset": "A",
        "path": "/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260722/20260722_20260722_172235_10744/label.parquet",
        "size_bytes": 1687590,
        "parsed": False,
    },
    {
        "dataset": "A",
        "path": "/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260722/20260722_20260722_172235_10744/acceptance.json",
        "size_bytes": 8687,
        "parsed": False,
    },
    {
        "dataset": "A",
        "path": "/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260722/20260722_20260722_172235_10744/manifest.json",
        "size_bytes": 6503,
        "parsed": False,
    },
    {
        "dataset": "A",
        "path": "/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260722/20260722_20260722_172235_10744/summary.json",
        "size_bytes": 105193,
        "parsed": False,
    },
    {
        "dataset": "B",
        "path": "/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260912/20260912_operator_d1_overnight/operator_feature.parquet",
        "size_bytes": 157352913,
        "parsed": False,
    },
    {
        "dataset": "B",
        "path": "/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260912/20260912_operator_d1_overnight/operator_label.parquet",
        "size_bytes": 17440217,
        "parsed": False,
    },
    {
        "dataset": "B",
        "path": "/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260912/20260912_operator_d1_overnight/acceptance.json",
        "size_bytes": 905,
        "parsed": False,
    },
    {
        "dataset": "B",
        "path": "/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260912/20260912_operator_d1_overnight/manifest.json",
        "size_bytes": 2274,
        "parsed": False,
    },
    {
        "dataset": "C",
        "path": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2/panels/20261014-3958528f3441/manifest.json",
        "size_bytes": 113580,
        "parsed": False,
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_input_identities() -> dict[str, dict[str, Any]]:
    """Verify every expected SHA before opening any parquet for data reads."""
    verified: dict[str, dict[str, Any]] = {}
    for key, spec in DATASETS.items():
        source = spec["path"]
        if not source.is_file():
            raise FileNotFoundError(f"input file missing: {source}")
        resolved = source.resolve(strict=True)
        actual_sha = sha256_file(resolved)
        if actual_sha != spec["sha256"]:
            raise RuntimeError(
                f"SHA-256 mismatch for {key}: expected={spec['sha256']} actual={actual_sha}"
            )
        stat = resolved.stat()
        if stat.st_size != spec["size_bytes"]:
            raise RuntimeError(
                f"size mismatch for {key}: expected={spec['size_bytes']} observed={stat.st_size}"
            )
        verified[key] = {
            "path": str(source),
            "resolved_path": str(resolved),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "expected_sha256": spec["sha256"],
            "observed_sha256": actual_sha,
        }
    return verified


def companion_metadata() -> list[dict[str, Any]]:
    """Hash named preservation companions only; never parse labels or manifests."""
    rows: list[dict[str, Any]] = []
    for item in PRESERVATION_COMPANIONS:
        source = Path(item["path"])
        if not source.is_file():
            raise FileNotFoundError(f"preservation companion missing: {source}")
        resolved = source.resolve(strict=True)
        size_bytes = resolved.stat().st_size
        if size_bytes != item["size_bytes"]:
            raise RuntimeError(
                f"preservation companion size mismatch: {source} "
                f"expected={item['size_bytes']} observed={size_bytes}"
            )
        rows.append({
            "dataset": item["dataset"],
            "filename": source.name,
            "path": str(source),
            "resolved_path": str(resolved),
            "size_bytes": size_bytes,
            "sha256": sha256_file(resolved),
            "parsed": False,
            "backup_created": False,
        })
    return rows


def normalize_code(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, np.integer)):
        text = str(int(value)).zfill(5)
    elif isinstance(value, (float, np.floating)) and math.isfinite(float(value)) and float(value).is_integer():
        text = str(int(value)).zfill(5)
    else:
        text = str(value).strip().upper()
        if text.endswith(".HK"):
            text = text[:-3]
        if text.startswith("HK."):
            text = text[3:]
        if re.fullmatch(r"\d+", text):
            text = text.zfill(5)
    return text or None


def normalize_date_value(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date, np.datetime64)):
        stamp = pd.Timestamp(value)
    else:
        text = str(value).strip()
        if re.fullmatch(r"\d{8}(?:\.0+)?", text):
            stamp = pd.to_datetime(text[:8], format="%Y%m%d", errors="coerce")
        elif re.fullmatch(r"\d{14}(?:\.0+)?", text):
            stamp = pd.to_datetime(text[:8], format="%Y%m%d", errors="coerce")
        else:
            stamp = pd.to_datetime(text, errors="coerce")
    if pd.isna(stamp):
        return None
    if getattr(stamp, "tzinfo", None) is not None:
        stamp = stamp.tz_convert("Asia/Hong_Kong").tz_localize(None)
    return pd.Timestamp(stamp).strftime("%Y%m%d")


def normalize_date_series(values: pd.Series) -> pd.Series:
    return values.map(normalize_date_value).astype("string")


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def json_bytes(payload: dict[str, Any]) -> bytes:
    text = json.dumps(clean_json(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def csv_bytes(rows: list[dict[str, Any]], empty_fields: list[str] | None = None) -> bytes:
    fieldnames: list[str] = []
    for row in rows:
        for field_name in row:
            if field_name not in fieldnames:
                fieldnames.append(field_name)
    if not rows and empty_fields:
        fieldnames = empty_fields
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def read_dataset(key: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    spec = DATASETS[key]
    source = spec["path"].resolve(strict=True)
    schema = pq.read_schema(source)
    missing = sorted(set(spec["columns"]) - set(schema.names))
    if missing:
        raise RuntimeError(f"required columns missing in {key}: {missing}")
    metadata = pq.read_metadata(source)
    table = pq.read_table(source, columns=spec["columns"])
    frame = table.to_pandas()
    if len(frame) != metadata.num_rows:
        raise RuntimeError(f"row-count mismatch while reading {key}")

    code_field = {"A": "symbol", "B": "code", "C": "code_norm"}[key]
    frame["_code"] = frame[code_field].map(normalize_code).astype("string")
    if key == "A":
        frame["_asof"] = normalize_date_series(frame["asof_date"])
        frame["_trade_date"] = normalize_date_series(frame["trade_date"])
        duplicate_asof = int(frame.duplicated(["_code", "_asof"]).sum())
        duplicate_trade = int(frame.duplicated(["_code", "_trade_date"]).sum())
        date_fields = {"asof_date": "_asof", "trade_date": "_trade_date"}
        duplicates = {"code_asof_date": duplicate_asof, "code_trade_date": duplicate_trade}
    else:
        date_field = "date" if key == "B" else "trade_date"
        frame["_date"] = normalize_date_series(frame[date_field])
        duplicate_count = int(frame.duplicated(["_code", "_date"]).sum())
        date_fields = {date_field: "_date"}
        duplicates = {"code_date": duplicate_count}

    if frame["_code"].isna().any():
        raise RuntimeError(f"null/unparseable security codes in {key}")
    if any(duplicates.values()):
        raise RuntimeError(f"duplicate code-date keys in {key}: {duplicates}")

    inventory = {
        "label": spec["label"],
        "rows": int(metadata.num_rows),
        "columns": int(metadata.num_columns),
        "fields": [
            {"name": field.name, "type": str(field.type), "nullable": field.nullable}
            for field in schema
        ],
        "distinct_code_count": int(frame["_code"].nunique()),
        "missing_code_rows": int(frame["_code"].isna().sum()),
        "non_five_digit_numeric_code_count": int(
            (~frame["_code"].str.fullmatch(r"\d{5}", na=False)).sum()
        ),
        "duplicate_keys": duplicates,
        "date_ranges": {},
        "daily_row_count_min_median_max": {},
    }
    for label, field_name in date_fields.items():
        dates = frame[field_name].dropna()
        daily_counts = frame.loc[frame[field_name].notna()].groupby(field_name).size()
        inventory["date_ranges"][label] = {
            "first": str(dates.min()) if len(dates) else None,
            "last": str(dates.max()) if len(dates) else None,
            "unique_days": int(dates.nunique()),
            "missing_rows": int(frame[field_name].isna().sum()),
        }
        inventory["daily_row_count_min_median_max"][label] = {
            "min": int(daily_counts.min()) if len(daily_counts) else None,
            "median": float(daily_counts.median()) if len(daily_counts) else None,
            "max": int(daily_counts.max()) if len(daily_counts) else None,
        }
    return frame, inventory


def per_code_stats(frame: pd.DataFrame, date_col: str) -> dict[str, dict[str, Any]]:
    grouped = frame.groupby("_code", sort=True, dropna=False)
    result: dict[str, dict[str, Any]] = {}
    for code, subframe in grouped:
        dates = subframe[date_col].dropna()
        result[str(code)] = {
            "rows": int(len(subframe)),
            "first": str(dates.min()) if len(dates) else "",
            "last": str(dates.max()) if len(dates) else "",
            "unique_days": int(dates.nunique()),
        }
    return result


def compare_numeric(
    joined: pd.DataFrame,
    left_column: str,
    right_column: str,
    label: str,
    pair: str,
) -> dict[str, Any]:
    left = pd.to_numeric(joined[left_column], errors="coerce").to_numpy(dtype="float64")
    right = pd.to_numeric(joined[right_column], errors="coerce").to_numpy(dtype="float64")
    valid = np.isfinite(left) & np.isfinite(right)
    exact = valid & (left == right)
    close = np.zeros(len(joined), dtype=bool)
    if valid.any():
        close[valid] = np.isclose(left[valid], right[valid], rtol=RTOL, atol=ATOL)
    return {
        "pair": pair,
        "comparison": label,
        "joined_rows": int(len(joined)),
        "comparable_rows": int(valid.sum()),
        "rows_missing_numeric_value": int((~valid).sum()),
        "exact_equal_rows": int(exact.sum()),
        "within_tolerance_but_not_exact_rows": int((close & ~exact).sum()),
        "not_within_tolerance_rows": int((valid & ~close).sum()),
        "rtol": RTOL,
        "atol": ATOL,
        "values_exported": False,
        "semantic_or_unit_equivalence_claimed": False,
    }


def date_summary(series: pd.Series) -> dict[str, Any]:
    dates = series.dropna().astype(str)
    counts = dates.value_counts().sort_index()
    latest_date = str(dates.max()) if len(dates) else None
    return {
        "first": str(dates.min()) if len(dates) else None,
        "last": str(dates.max()) if len(dates) else None,
        "unique_days": int(dates.nunique()),
        "latest_date_rows": int(counts.loc[latest_date]) if latest_date else None,
        "rows_per_day_min_median_max": {
            "min": int(counts.min()) if len(counts) else None,
            "median": float(counts.median()) if len(counts) else None,
            "max": int(counts.max()) if len(counts) else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--write-dir",
        type=Path,
        help="explicitly authorize writing generated metadata into this exact audit directory",
    )
    mode.add_argument(
        "--verify",
        action="store_true",
        help="recompute in memory and compare with existing audit metadata without writing",
    )
    mode.add_argument(
        "--stdout",
        action="store_true",
        help="same read-only recomputation and artifact comparison as --verify; print brief PASS",
    )
    args = parser.parse_args()
    write_dir: Path | None = None
    if args.write_dir is not None:
        write_dir = args.write_dir.resolve(strict=True)
        if write_dir != OUT_DIR:
            parser.error(f"writes are restricted to the authorized audit directory: {OUT_DIR}")

    verified = verify_input_identities()
    companions = companion_metadata()
    frames: dict[str, pd.DataFrame] = {}
    inventories: dict[str, dict[str, Any]] = {}
    for key in ("A", "B", "C"):
        frames[key], inventories[key] = read_dataset(key)
        inventories[key].update(verified[key])

    frames["A"] = frames["A"].rename(columns={
        "symbol": "A_symbol", "amount_1d": "A_amount_1d",
        "volume_1d": "A_volume_1d", "ret_1d": "A_ret_1d",
    })
    frames["B"] = frames["B"].rename(columns={
        "open": "B_open", "high": "B_high", "low": "B_low", "close": "B_close",
        "amount": "B_amount", "trade": "B_trade",
    })
    frames["C"] = frames["C"].rename(columns={
        "open": "C_open", "high": "C_high", "low": "C_low", "close": "C_close",
        "amount": "C_amount", "trade": "C_trade", "pct_chg": "C_pct_chg",
    })

    code_sets = {key: set(frame["_code"].dropna().astype(str)) for key, frame in frames.items()}
    union = set.union(*code_sets.values())
    set_counts = {
        "A_intersect_B": len(code_sets["A"] & code_sets["B"]),
        "A_minus_B": len(code_sets["A"] - code_sets["B"]),
        "B_minus_A": len(code_sets["B"] - code_sets["A"]),
        "A_minus_C": len(code_sets["A"] - code_sets["C"]),
        "C_minus_A": len(code_sets["C"] - code_sets["A"]),
        "B_minus_C": len(code_sets["B"] - code_sets["C"]),
        "C_minus_B": len(code_sets["C"] - code_sets["B"]),
        "C_minus_A_union_B": len(code_sets["C"] - (code_sets["A"] | code_sets["B"])),
        "union": len(union),
    }
    for key, expected in EXPECTED_CODE_COUNTS.items():
        if inventories[key]["distinct_code_count"] != expected:
            raise RuntimeError(
                f"distinct code count mismatch {key}: "
                f"expected={expected} observed={inventories[key]['distinct_code_count']}"
            )
    if set_counts != EXPECTED_CODE_SET_COUNTS:
        raise RuntimeError(f"code-set receipt mismatch: {set_counts}")

    membership = []
    for code in sorted(union):
        membership.append({
            "code": code,
            "in_A": int(code in code_sets["A"]),
            "in_B": int(code in code_sets["B"]),
            "in_C": int(code in code_sets["C"]),
        })
    if len(membership) != 717:
        raise RuntimeError(f"membership row count mismatch: {len(membership)}")

    differences = []
    for left, right in (("A", "B"), ("A", "C"), ("B", "C")):
        for side, codes in ((f"{left}_minus_{right}", code_sets[left] - code_sets[right]),
                            (f"{right}_minus_{left}", code_sets[right] - code_sets[left])):
            for code in sorted(codes):
                differences.append({
                    "comparison": f"{left}_vs_{right}",
                    "side": side,
                    "code": code,
                })
    for code in sorted(code_sets["C"] - (code_sets["A"] | code_sets["B"])):
        differences.append({
            "comparison": "C_vs_A_union_B",
            "side": "C_minus_A_union_B",
            "code": code,
        })

    a = frames["A"].copy()
    b = frames["B"].copy()
    c = frames["C"].copy()
    a_asof = a[["_code", "_asof", "A_amount_1d", "A_volume_1d", "A_ret_1d"]].rename(
        columns={"_code": "code", "_asof": "date"}
    )
    a_trade = a[["_code", "_trade_date", "A_amount_1d", "A_volume_1d", "A_ret_1d"]].rename(
        columns={"_code": "code", "_trade_date": "date"}
    )
    b_keys = b[["_code", "_date", "B_open", "B_high", "B_low", "B_close", "B_amount", "B_trade"]].rename(
        columns={"_code": "code", "_date": "date"}
    )
    c_keys = c[["_code", "_date", "C_open", "C_high", "C_low", "C_close", "C_amount", "C_trade", "C_pct_chg"]].rename(
        columns={"_code": "code", "_date": "date"}
    )

    bc = b_keys.merge(c_keys, on=["code", "date"], how="inner", validate="one_to_one")
    ac = a_asof.merge(c_keys, on=["code", "date"], how="inner", validate="one_to_one")
    ab = a_asof.merge(b_keys, on=["code", "date"], how="inner", validate="one_to_one")

    overlap_rows: list[dict[str, Any]] = []
    for field in ("open", "high", "low", "close", "amount", "trade"):
        overlap_rows.append(compare_numeric(
            bc, f"B_{field}", f"C_{field}", field, "B_vs_C_same_code_date"
        ))
    for field in ("amount", "volume"):
        overlap_rows.append(compare_numeric(
            ac,
            "A_amount_1d" if field == "amount" else "A_volume_1d",
            "C_amount" if field == "amount" else "C_trade",
            field,
            "A_asof_vs_C_trade_date",
        ))
        overlap_rows.append(compare_numeric(
            ab,
            "A_amount_1d" if field == "amount" else "A_volume_1d",
            "B_amount" if field == "amount" else "B_trade",
            field,
            "A_asof_vs_B_date",
        ))
    b_trade = pd.to_numeric(bc["B_trade"], errors="coerce").to_numpy(dtype="float64")
    c_trade = pd.to_numeric(bc["C_trade"], errors="coerce").to_numpy(dtype="float64")
    finite_trade = np.isfinite(b_trade) & np.isfinite(c_trade)
    both_zero = finite_trade & (b_trade == 0) & (c_trade == 0)
    b_zero_c_nonzero = finite_trade & (b_trade == 0) & (c_trade != 0)
    b_nonzero_c_zero = finite_trade & (b_trade != 0) & (c_trade == 0)
    both_nonzero = finite_trade & (b_trade != 0) & (c_trade != 0)
    exact_nonzero = both_nonzero & (b_trade == c_trade)
    scale_100 = np.zeros(len(bc), dtype=bool)
    if both_nonzero.any():
        scale_100[both_nonzero] = np.isclose(
            c_trade[both_nonzero], b_trade[both_nonzero] * 100.0,
            rtol=RTOL, atol=ATOL,
        )
    scale_100 &= both_nonzero & ~exact_nonzero
    other_nonzero = both_nonzero & ~exact_nonzero & ~scale_100
    b_amount = pd.to_numeric(bc["B_amount"], errors="coerce").to_numpy(dtype="float64")
    c_amount = pd.to_numeric(bc["C_amount"], errors="coerce").to_numpy(dtype="float64")
    c_both_zero = (c_amount == 0) & (c_trade == 0)
    b_any_positive = (b_amount > 0) | (b_trade > 0)
    b_both_positive = (b_amount > 0) & (b_trade > 0)
    zero_pair = b_any_positive & c_both_zero
    zero_pair_both_b_positive = b_both_positive & c_both_zero
    zero_rows_by_date = (
        bc.loc[zero_pair, "date"].astype(str).value_counts().sort_index().to_dict()
    )
    overlap_rows.extend([
        {
            "pair": "B_vs_C_same_code_date",
            "comparison": "trade_volume_relation_counts",
            "joined_rows": int(len(bc)),
            "comparable_rows": int(finite_trade.sum()),
            "rows_missing_numeric_value": int((~finite_trade).sum()),
            "exact_equal_rows": int(exact_nonzero.sum()),
            "within_tolerance_but_not_exact_rows": int(scale_100.sum()),
            "not_within_tolerance_rows": int(other_nonzero.sum()),
            "rtol": RTOL,
            "atol": ATOL,
            "both_zero_rows": int(both_zero.sum()),
            "B_zero_C_nonzero_rows": int(b_zero_c_nonzero.sum()),
            "B_nonzero_C_zero_rows": int(b_nonzero_c_zero.sum()),
            "semantic_or_unit_equivalence_claimed": False,
        },
        {
            "pair": "B_vs_C_same_code_date",
            "comparison": "B_positive_amount_and_trade_while_C_both_zero",
            "joined_rows": int(len(bc)),
            "comparable_rows": int(zero_pair.sum()),
            "rows_missing_numeric_value": 0,
            "exact_equal_rows": 0,
            "within_tolerance_but_not_exact_rows": 0,
            "not_within_tolerance_rows": int(zero_pair.sum()),
            "rtol": RTOL,
            "atol": ATOL,
            "date_row_counts": json.dumps(zero_rows_by_date, sort_keys=True),
            "B_both_amount_and_trade_positive_C_both_zero_rows": int(zero_pair_both_b_positive.sum()),
            "semantic_or_unit_equivalence_claimed": False,
        },
    ])

    coverage_a_asof = per_code_stats(a, "_asof")
    coverage_a_trade = per_code_stats(a, "_trade_date")
    coverage_b = per_code_stats(b, "_date")
    coverage_c = per_code_stats(c, "_date")
    coverage_rows = []
    for code in sorted(union):
        a_asof_stats = coverage_a_asof.get(code, {})
        a_trade_stats = coverage_a_trade.get(code, {})
        b_stats = coverage_b.get(code, {})
        c_stats = coverage_c.get(code, {})
        coverage_rows.append({
            "code": code,
            "A_present": int(code in code_sets["A"]),
            "A_rows": a_asof_stats.get("rows", 0),
            "A_asof_first_date": a_asof_stats.get("first", ""),
            "A_asof_last_date": a_asof_stats.get("last", ""),
            "A_asof_unique_days": a_asof_stats.get("unique_days", 0),
            "A_trade_first_date": a_trade_stats.get("first", ""),
            "A_trade_last_date": a_trade_stats.get("last", ""),
            "A_trade_unique_days": a_trade_stats.get("unique_days", 0),
            "B_present": int(code in code_sets["B"]),
            "B_rows": b_stats.get("rows", 0),
            "B_first_date": b_stats.get("first", ""),
            "B_last_date": b_stats.get("last", ""),
            "B_unique_days": b_stats.get("unique_days", 0),
            "C_present": int(code in code_sets["C"]),
            "C_rows": c_stats.get("rows", 0),
            "C_first_date": c_stats.get("first", ""),
            "C_last_date": c_stats.get("last", ""),
            "C_unique_days": c_stats.get("unique_days", 0),
        })

    output_rows = {
        "code_membership.csv": membership,
        "code_set_differences.csv": differences,
        "per_code_coverage.csv": coverage_rows,
        "overlap_conflicts.csv": overlap_rows,
        "preservation_inventory.csv": companions,
    }
    output_blobs = {
        name: csv_bytes(rows, ["comparison", "side", "code"] if name == "code_set_differences.csv" else None)
        for name, rows in output_rows.items()
    }

    inventory_payload = {
        "audit_kind": "read_only_hk_three_dataset_inventory",
        "data_values_exported": False,
        "code_normalization": "trim/uppercase; remove .HK or HK. wrapper; zero-fill numeric code strings to width 5",
        "date_normalization": "YYYYMMDD; timezone-aware timestamps converted to Asia/Hong_Kong before date truncation",
        "datasets": inventories,
        "preservation_companions": companions,
        "preservation_note": "metadata only; companion contents not parsed; no backup copy created",
    }
    output_blobs["inventory.json"] = json_bytes(inventory_payload)

    summary = {
        "audit_kind": "read_only_hk_three_dataset_comparison",
        "data_values_exported": False,
        "numeric_tolerance": {"rtol": RTOL, "atol": ATOL},
        "dataset_code_counts": {key: len(code_sets[key]) for key in ("A", "B", "C")},
        "pairwise_code_set_counts": set_counts,
        "A_intersect_B_intersect_C": len(code_sets["A"] & code_sets["B"] & code_sets["C"]),
        "all_A_codes_in_C": code_sets["A"] <= code_sets["C"],
        "all_B_codes_in_C": code_sets["B"] <= code_sets["C"],
        "code_membership_rows": len(membership),
        "code_difference_rows": len(differences),
        "row_key_join_counts": {
            "B_C_same_code_date": int(len(bc)),
            "A_asof_C_trade_date": int(len(ac)),
            "A_asof_B_date": int(len(ab)),
        },
        "row_key_difference_counts": {
            "B_C_same_code_date": {
                "B_rows_only": int(len(b) - len(bc)),
                "C_rows_only": int(len(c) - len(bc)),
                "union_rows": int(len(b) + len(c) - len(bc)),
            },
            "A_asof_C_trade_date": {
                "A_asof_rows_only": int(len(a) - len(ac)),
                "C_rows_only": int(len(c) - len(ac)),
                "union_rows": int(len(a) + len(c) - len(ac)),
            },
            "A_asof_B_date": {
                "A_asof_rows_only": int(len(a) - len(ab)),
                "B_rows_only": int(len(b) - len(ab)),
                "union_rows": int(len(a) + len(b) - len(ab)),
            },
        },
        "date_coverage": {
            "A_asof_date": date_summary(a["_asof"]),
            "A_trade_date": date_summary(a["_trade_date"]),
            "B_date": date_summary(b["_date"]),
            "C_trade_date": date_summary(c["_date"]),
        },
        "duplicate_code_date_keys": {
            key: inventory["duplicate_keys"] for key, inventory in inventories.items()
        },
        "overlap_metric_rows": overlap_rows,
        "interpretation_limits": [
            "code-set containment does not establish historical row/date/field coverage",
            "numeric differences do not adjudicate source correctness or unit equivalence",
            "A asof_date and trade_date are retained as separate date roles",
            "PIT, source, currency, price adjustment, volume units, and zero-trade semantics require separate confirmation",
        ],
    }
    output_blobs["summary.json"] = json_bytes(summary)

    output_files = [
        "inventory.json", "summary.json", "code_membership.csv",
        "per_code_coverage.csv", "code_set_differences.csv", "overlap_conflicts.csv",
        "preservation_inventory.csv",
    ]
    manifest = {
        "audit_kind": "read_only_hk_three_dataset_audit",
        "script_path": str(Path(__file__).resolve()),
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "python": sys.version.split()[0],
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "pyarrow": __import__("pyarrow").__version__,
        "inputs": {
            key: {
                "path": verified[key]["path"],
                "resolved_path": verified[key]["resolved_path"],
                "size_bytes": verified[key]["size_bytes"],
                "sha256": verified[key]["observed_sha256"],
            }
            for key in ("A", "B", "C")
        },
        "preservation_companions": [
            {
                "dataset": item["dataset"],
                "path": item["path"],
                "resolved_path": item["resolved_path"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
                "parsed": False,
                "backup_created": False,
            }
            for item in companions
        ],
        "outputs": {
            name: {
                "size_bytes": len(output_blobs[name]),
                "sha256": hashlib.sha256(output_blobs[name]).hexdigest(),
            }
            for name in output_files
        },
        "raw_market_rows_exported": False,
        "migration_or_pointer_change": False,
    }
    output_blobs["audit_manifest.json"] = json_bytes(manifest)

    if write_dir is not None:
        for name, content in output_blobs.items():
            (write_dir / name).write_bytes(content)
        status = "PASS_READ_ONLY_AUDIT_WRITTEN"
    else:
        for name, expected_bytes in output_blobs.items():
            artifact = OUT_DIR / name
            if not artifact.is_file():
                raise FileNotFoundError(f"expected audit metadata is missing: {artifact}")
            observed_bytes = artifact.read_bytes()
            if observed_bytes != expected_bytes:
                raise RuntimeError(f"recomputed metadata differs from saved artifact: {artifact.name}")
        status = "PASS_READ_ONLY_VERIFY"

    result = {
        "status": status,
        "verified_inputs": {
            key: {"path": verified[key]["resolved_path"], "sha256": verified[key]["observed_sha256"]}
            for key in ("A", "B", "C")
        },
        "code_counts": summary["dataset_code_counts"],
        "set_counts": set_counts,
        "row_key_join_counts": summary["row_key_join_counts"],
        "verified_artifact_count": len(output_blobs) if write_dir is None else None,
        "outputs": list(output_blobs),
    }
    if args.stdout:
        print(json.dumps({
            "status": status,
            "code_counts": summary["dataset_code_counts"],
            "set_counts": set_counts,
            "verified_artifact_count": len(output_blobs),
        }, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
