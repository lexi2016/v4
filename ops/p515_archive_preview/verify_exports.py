#!/usr/bin/env python3
"""Independently compare native-browser downloads to immutable D17 source CSV cells."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


CONTRACT = {
    "disposition": ("00_全范围处置.csv", "D17_disposition_5572_original.csv", 5572, 7),
    "shortlist": ("01_量价初筛.csv", "D17_shortlist_822_original.csv", 822, 27),
    "scores": ("03_模型精选排序.csv", "D17_scores_33_original.csv", 33, 20),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return list(csv.reader(source))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--ui-root", required=True)
    args = parser.parse_args()
    source_root = Path(args.source_root)
    ui_root = Path(args.ui_root)
    browser_receipt_path = ui_root / "BROWSER_RECEIPT.json"
    browser_receipt = json.loads(browser_receipt_path.read_text(encoding="utf-8"))
    if browser_receipt.get("status") != "PASS_BROWSER_UI_AND_NATIVE_DOWNLOADS":
        raise SystemExit("native exports cannot be accepted before browser UI/download PASS")

    results = {}
    for key, (source_name, export_name, expected_rows, expected_columns) in CONTRACT.items():
        source = source_root / source_name
        exported = ui_root / "native_exports" / export_name
        original_cells = read_csv(source)
        downloaded_cells = read_csv(exported)
        if not original_cells or len(original_cells[0]) != expected_columns or len(original_cells) - 1 != expected_rows:
            raise SystemExit(f"source count/schema mismatch: {source_name}")
        if len(downloaded_cells) != len(original_cells):
            raise SystemExit(f"native download row count mismatch: {export_name}")
        if downloaded_cells != original_cells:
            for row_index, (left, right) in enumerate(zip(original_cells, downloaded_cells)):
                if left != right:
                    raise SystemExit(f"native download cell mismatch {export_name} row={row_index+1}")
            raise SystemExit(f"native download cell mismatch: {export_name}")
        if any(len(row) != expected_columns for row in downloaded_cells):
            raise SystemExit(f"native download column count mismatch: {export_name}")
        results[key] = {
            "source_file": str(source.resolve()),
            "source_bytes": source.stat().st_size,
            "source_sha256": sha256(source),
            "browser_native_export_file": str(exported.resolve()),
            "export_bytes": exported.stat().st_size,
            "export_sha256": sha256(exported),
            "rows": expected_rows,
            "columns": expected_columns,
            "data_cells": expected_rows * expected_columns,
            "all_cells_equal_including_empty_values": True,
            "header_and_column_order_equal": True,
        }

    result = {
        "status": "PASS_ALL_BROWSER_NATIVE_EXPORT_CELLS_EQUAL_SOURCE",
        "parser": "Python csv.reader independent of browser CSV parser",
        "browser_receipt": str(browser_receipt_path.resolve()),
        "exports": results,
        "original_33_score_data_cells": results["scores"]["data_cells"],
        "new_score_join_or_columns": 0,
    }
    out = ui_root / "EXPORT_VERIFICATION.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
