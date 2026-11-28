"""Migrate only the four pinned clean V1 calibration cases to V1.1."""

from __future__ import annotations

import argparse
from pathlib import Path
from subprocess import SubprocessError
from tempfile import TemporaryDirectory

from research.act070a import case_contract as v1
from research.act070a.chart import render_chart
from research.act071a.case_contract import (
    B_SCHEMA, CALIBRATION_DIR, CASE_FILES, FIRST_TEST_DIR, INPUT_SCHEMA, KB_RULES, PNG_NAME,
    RECEIPT_NAME, RECEIPT_SCHEMA, SVG_NAME, normalize_rows, verify_case,
)
from research.act071a.chart import RENDERER, render_png

V1_RECEIPT_HASH = "efad66c16d92267b492f0b42a1cfdc652b1a371b861edc7886cd9224294a0824"
CALIBRATION = {"C01": "2025-02-26", "C02": "2018-05-31", "C03": "2026-05-26", "C04": "2017-10-31"}


def build_case(*, case_id: str, stock_code: str, day: str, scope: str, rows: list[dict],
               immutable_b2: dict, source_sha256: dict, schema: bytes, kb: bytes) -> tuple[dict, bytes, bytes]:
    rows = normalize_rows(rows)
    chart_rows = [row for row in rows if row["kind"] == "CHART_BAR"]
    svg = render_chart(chart_rows)
    png = render_png(svg)
    case = {
        "schema_version": INPUT_SCHEMA, "case_id": case_id, "d": day, "stock_code": stock_code,
        "scope": scope, "guards": v1.FROZEN_GUARDS,
        "chart": {
            "renderer": RENDERER, "row_ids": [row["row_id"] for row in chart_rows],
            "svg": {"path": SVG_NAME, "sha256": v1.sha256(svg)},
            "png": {"path": PNG_NAME, "sha256": v1.sha256(png)},
        },
        "schema_sha256": v1.sha256(schema), "kb_sha256": v1.sha256(kb),
        "kb_rule_ids": [card["id"] for card in v1.strict_json(kb)["cards"]],
        "source_sha256": source_sha256, "rows": rows, "immutable_b2": immutable_b2,
    }
    case["input_sha256"] = v1.case_digest(case)
    verify_case(case, svg, png, schema, kb, case_id, case["input_sha256"], verify_raster=False)
    return case, svg, png


def write_case(group: Path, bundle: tuple[dict, bytes, bytes], schema: bytes, kb: bytes) -> dict:
    case, svg, png = bundle
    case_id = case["case_id"]
    directory = group / case_id
    directory.mkdir()
    payloads = (v1.json_bytes(case) + b"\n", svg, png, schema, kb)
    for name, payload in zip(CASE_FILES, payloads, strict=True):
        (directory / name).write_bytes(payload)
    chart_rows = [row for row in case["rows"] if row["kind"] == "CHART_BAR"]
    return {
        "directory": f"{group.name}/{case_id}", "d": case["d"], "stock_code": case["stock_code"],
        "scope": case["scope"], "input_sha256": case["input_sha256"], "immutable_b2": case["immutable_b2"],
        "chart_bars": len(chart_rows),
        "session_start": chart_rows[0]["source"]["stock_session_index"],
        "session_end": chart_rows[-1]["source"]["stock_session_index"],
        "max_delivered_chart_date": chart_rows[-1]["occurred_date"],
        "max_ref_occurred_date": max(row["occurred_date"] for row in case["rows"]),
        "max_ref_first_knowable_date": max(row["first_knowable_date"] for row in case["rows"]),
        "file_sha256": {name: v1.sha256(raw) for name, raw in zip(CASE_FILES, payloads, strict=True)},
    }


def _read_safe_v1_file(root: Path, relative: str, accesses: dict) -> bytes:
    path = root / relative
    v1.require(path.resolve() == path and path.is_file(), "SOURCE_NOT_ALLOWED", relative)
    raw = path.read_bytes()
    accesses[relative] = {"sha256": v1.sha256(raw), "opens": 1}
    return raw


def generate(v1_root: Path, out: Path) -> dict:
    v1.require(not out.exists() and not out.is_symlink(), "OUTPUT_EXISTS", str(out))
    v1_root = v1_root.absolute()
    schema, kb = B_SCHEMA.read_bytes(), KB_RULES.read_bytes()
    old_schema, old_kb = v1.B_SCHEMA.read_bytes(), v1.KB_RULES.read_bytes()
    accesses = {}
    raw_receipt = _read_safe_v1_file(v1_root, "A_CASE_RECEIPT.json", accesses)
    v1.require(v1.sha256(raw_receipt) == V1_RECEIPT_HASH,
               "SOURCE_HASH_MISMATCH", "expected ACT070A controlled A receipt")
    receipt_v1 = v1.strict_json(raw_receipt)
    v1.require(receipt_v1["schema_version"] == v1.RECEIPT_SCHEMA and set(receipt_v1["cases"]) == CALIBRATION.keys(),
               "SOURCE_CASE_MISSING", "fixed ACT070A V1 calibration roster")

    bundles = []
    for case_id, day in CALIBRATION.items():
        directory = f"01_CALIBRATION_4D/{case_id}"
        prior = v1.strict_json(_read_safe_v1_file(v1_root, f"{directory}/input.json", accesses))
        svg = _read_safe_v1_file(v1_root, f"{directory}/chart.svg", accesses)
        v1.verify_case(prior, svg, old_schema, old_kb, case_id, receipt_v1["cases"][case_id]["input_sha256"])
        v1.require(prior["d"] == day, "SOURCE_CASE_MISSING", case_id)
        bundle = build_case(case_id=case_id, stock_code="002865.SZ", day=day, scope="EXPOSED_REGRESSION",
                            rows=prior["rows"], immutable_b2=prior["immutable_b2"],
                            source_sha256=prior["source_sha256"], schema=schema, kb=kb)
        v1.require(bundle[1] == svg, "INVALID_CHART_MAPPING", "frozen V1 and V1.1 SVG differ")
        bundles.append(bundle)

    receipt = {
        "schema_version": RECEIPT_SCHEMA, "guards": v1.FROZEN_GUARDS,
        "calibration_count": len(bundles), "first_test_count": 0, "first_test_status": "PHASE_2_PENDING",
        "safe_v1_input_reads": accesses, "historical_forward_source_opens": 0, "models_called": 0,
        "cases": {},
    }
    with TemporaryDirectory(prefix=".act071a-", dir=out.parent) as temp:
        stage = Path(temp) / "pack"
        calibration = stage / CALIBRATION_DIR
        calibration.mkdir(parents=True)
        (stage / FIRST_TEST_DIR).mkdir()
        for bundle in bundles:
            receipt["cases"][bundle[0]["case_id"]] = write_case(calibration, bundle, schema, kb)
        (stage / RECEIPT_NAME).write_bytes(v1.json_bytes(receipt) + b"\n")
        v1.require(not out.exists() and not out.is_symlink(), "OUTPUT_EXISTS", str(out))
        stage.rename(out)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-root", type=Path, required=True, help="controlled V1 cases directory")
    parser.add_argument("--out", type=Path, required=True, help="new package directory in an existing parent")
    args = parser.parse_args()
    try:
        receipt = generate(args.v1_root, args.out.absolute())
    except (v1.Rejected, OSError, ValueError, KeyError, SubprocessError) as exc:
        print(v1.json_bytes({"status": "STOP", "code": getattr(exc, "code", "SOURCE_OR_IO_ERROR"),
                             "detail": str(exc)}).decode("utf-8"))
        return 1
    print(v1.json_bytes({"status": "GENERATED", "calibration_count": receipt["calibration_count"],
                        "historical_forward_source_opens": receipt["historical_forward_source_opens"],
                        "safe_v1_input_opens": len(receipt["safe_v1_input_reads"]),
                        "receipt": str(args.out / RECEIPT_NAME)}).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
