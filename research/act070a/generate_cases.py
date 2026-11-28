"""Build the frozen ACT-070A D-only handoff from four pinned V4 sources."""

from __future__ import annotations

import argparse
import csv
import io
from collections import defaultdict
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory

from research.act070a.case_contract import (
    B_SCHEMA, CHART_NAME, FROZEN_GUARDS, INPUT_SCHEMA, KB_RULES, OHLCV_FIELDS, RECEIPT_SCHEMA,
    SOURCE_HASHES, Rejected, case_digest, ensure_no_later_date, iso_day, json_bytes, require, require_chronology,
    row_id, sha256, strict_json, verify_case,
)
from research.act070a.chart import CHART_SESSIONS, render_chart

V4_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
STATE_CONTRACT = Path(__file__).resolve().parents[1] / "act069a/V4.1_STRUCTURE_IDENTITY_STATE_MACHINE_CONTRACT_V1_0.json"
ACT069B = V4_ROOT / "artifacts/ACT069B_20261127/output"
SOURCE_PATHS = {
    "primitive_evidence_ledger": ACT069B / "ACT069B_JUNDA_002865_PRIMITIVE_EVIDENCE_LEDGER_DONLY_20261127.csv",
    "day_vs_chain_status": ACT069B / "ACT069B_JUNDA_002865_DAY_VS_CHAIN_STATUS_20261127.csv",
    "state_machine_contract": STATE_CONTRACT,
    "common_indicators_d_only": V4_ROOT / "artifacts/ACT067B_20261127/evidence/common_indicators_d_only.csv",
}
A_RECEIPT_NAME = "A_CASE_RECEIPT.json"
CAL_DIR = "01_CALIBRATION_4D"
TEST_DIR = "02_FIRST_TEST_8D"


def csv_rows(raw: bytes):
    return csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)


def parse_plan(plan: dict) -> list[dict]:
    require(isinstance(plan, dict) and set(plan) == {"calibration", "first_test"},
            "INVALID_CASE_PLAN", "expected calibration and first_test lists")
    calibration, first_test = plan["calibration"], plan["first_test"]
    require(isinstance(calibration, list) and len(calibration) == 4,
            "INVALID_CASE_PLAN", "four known calibration cases are required")
    require(first_test == [], "FIRST_TEST_NOT_CERTIFIED", "no source-bound segment isolation")
    require(all(isinstance(item, dict) and set(item) == {"case_id", "d"} for item in calibration),
            "INVALID_CASE_PLAN", "case_id and d are required")
    require([item["case_id"] for item in calibration] == [f"C{number:02d}" for number in range(1, 5)],
            "INVALID_CASE_PLAN", "A-assigned ordered calibration identities C01..C04")
    require(len({iso_day(item["d"]) for item in calibration}) == len(calibration),
            "INVALID_CASE_PLAN", "each case must have a distinct D")
    return calibration


def load_frozen_sources(days: set[str]) -> tuple[dict, dict, list[dict], dict]:
    """Only this loader opens market/proof sources. Bytes are pinned before parsing."""
    data = {}
    audit = {}
    for name, path in SOURCE_PATHS.items():
        raw = path.read_bytes()
        digest = sha256(raw)
        require(digest == SOURCE_HASHES[name], "SOURCE_HASH_MISMATCH", name)
        data[name] = raw
        audit[name] = {"path": str(path), "sha256": digest, "bytes": len(raw), "opens": 1}

    contract = strict_json(data["state_machine_contract"])
    require(contract["action"] == "ACT-069A" and contract["RESEARCH_ONLY"]
            and contract["S_FIT"] == contract["B_FIT"] == 0 and contract["production_allowed"] is False
            and contract["proof_gate"]["new_historical_authoritative_proofs_bound"] is False,
            "INVALID_UPSTREAM_CONTRACT", "ACT-069A proof boundaries")

    status_rows = [row for row in csv_rows(data["day_vs_chain_status"]) if row["signal_date"] in days]
    day_status = {row["signal_date"]: row for row in status_rows}
    require(len(status_rows) == len(day_status) and day_status.keys() == days,
            "SOURCE_CASE_MISSING", "D status must have one exact match")
    primitives = defaultdict(list)
    for row in csv_rows(data["primitive_evidence_ledger"]):
        if row["signal_date"] in days:
            primitives[row["signal_date"]].append(row)
    require(primitives.keys() == days, "SOURCE_CASE_MISSING", "D primitive ledger")

    maximum_index = max(int(row["stock_session_index"]) for row in status_rows)
    bars = list(islice(csv_rows(data["common_indicators_d_only"]), maximum_index + 1))
    require(len(bars) == maximum_index + 1, "SOURCE_CHART_WINDOW_MISSING", "chart source prefix")
    sessions = [iso_day(bar["date"]) for bar in bars]
    require(sessions == sorted(set(sessions)) and sessions[-1] == max(map(iso_day, days)),
            "SOURCE_CHART_WINDOW_MISSING", "exact, ordered session prefix")
    return day_status, dict(primitives), bars, audit


def signed_rows(case_id: str, day: str, bars: list[dict], primitives: list[dict], day_status: dict):
    cutoff = iso_day(day)
    index = int(day_status["stock_session_index"])
    left = index + 1 - CHART_SESSIONS
    require(left >= 0 and index < len(bars) and bars[index]["date"] == day,
            "SOURCE_CHART_WINDOW_MISSING", day)
    chart_rows = []
    for ordinal, bar in enumerate(bars[left:index + 1], start=1):
        item_id = row_id(case_id, "BAR", f"{ordinal:02d}")
        stamp = bar["date"]
        require_chronology(stamp, stamp, cutoff, item_id)
        chart_rows.append({
            "row_id": item_id, "kind": "CHART_BAR", "status": "OBSERVED_D_ONLY",
            "occurred_date": stamp, "first_knowable_date": stamp,
            "source": {"id": "common_indicators_d_only", "stock_session_index": left + ordinal - 1},
            "fields": {key: bar[key] for key in ("date", *OHLCV_FIELDS)},
        })

    ledger = []
    require(len(primitives) == 35, "INVALID_PRIMITIVE_ROSTER", day)
    require(len({(row["primitive_id"], row["fact_name"]) for row in primitives}) == len(primitives),
            "INVALID_PRIMITIVE_ROSTER", "duplicate primitive/fact identity")
    for number, row in enumerate(primitives, start=1):
        item_id = row_id(case_id, "PRIM", row["primitive_id"], f"{number:02d}")
        require(row["primitive_id"] in {"P1", "P2", "P3", "P4", "P5"},
                "INVALID_PRIMITIVE_ROSTER", item_id)
        require_chronology(row["occurred_date"], row["first_knowable_date"], cutoff, item_id)
        ensure_no_later_date(row, cutoff, item_id)
        fact = row["fact_value"]
        if fact.startswith(("{", "[")):
            fact = strict_json(fact.encode("utf-8"))
        ledger.append({
            "row_id": item_id, "kind": "PRIMITIVE", "status": row["handoff_status"],
            "primitive_id": row["primitive_id"], "occurred_date": row["occurred_date"],
            "first_knowable_date": row["first_knowable_date"], "gap_reason": row["gap_reason"],
            "source": {"id": "primitive_evidence_ledger", "locator": row["source_locator"]},
            "fields": {row["fact_name"]: fact},
        })

    ensure_no_later_date(day_status, cutoff, day)
    require(day_status["day_eligibility_method"] == "B2_D0", "INVALID_B2_INVARIANT", day)
    immutable_b2 = {key: day_status[key] for key in (
        "day_eligibility", "day_eligibility_reason", "event_chain_state_b2")}
    immutable_b2["formal_b2_event_presence"] = "ABSENT"
    day_row = {
        "row_id": row_id(case_id, "B2", "DAY"), "kind": "A_DAY_STATUS", "status": "OBSERVED_D_ONLY",
        "occurred_date": day, "first_knowable_date": day,
        "source": {"id": "day_vs_chain_status", "locator": day_status["source_locator"]},
        "fields": immutable_b2,
    }
    return chart_rows, [*chart_rows, *ledger, day_row], immutable_b2


def build_case(item: dict, bars: list[dict], primitives: list[dict], day_status: dict,
               schema_raw: bytes, kb_raw: bytes) -> tuple[dict, bytes]:
    case_id, day = item["case_id"], item["d"]
    chart_rows, rows, immutable_b2 = signed_rows(case_id, day, bars, primitives, day_status)
    chart = render_chart(chart_rows)
    case = {
        "schema_version": INPUT_SCHEMA, "case_id": case_id, "d": day,
        "guards": FROZEN_GUARDS,
        "chart": {"path": CHART_NAME, "sha256": sha256(chart), "row_ids": [row["row_id"] for row in chart_rows]},
        "schema_sha256": sha256(schema_raw), "kb_sha256": sha256(kb_raw),
        "kb_rule_ids": [card["id"] for card in strict_json(kb_raw)["cards"]],
        "source_sha256": SOURCE_HASHES, "rows": rows, "immutable_b2": immutable_b2,
    }
    case["input_sha256"] = case_digest(case)
    verify_case(case, chart, schema_raw, kb_raw, case_id, case["input_sha256"])
    return case, chart


def generate(plan_raw: bytes, out: Path) -> dict:
    planned = parse_plan(strict_json(plan_raw))
    require(not out.exists() and not out.is_symlink(), "OUTPUT_EXISTS", str(out))
    statuses, primitives, bars, audit = load_frozen_sources({item["d"] for item in planned})
    schema_raw, kb_raw = B_SCHEMA.read_bytes(), KB_RULES.read_bytes()
    bundles = [
        build_case(item, bars, primitives[item["d"]], statuses[item["d"]], schema_raw, kb_raw)
        for item in planned
    ]
    receipt = {
        "schema_version": RECEIPT_SCHEMA, "guards": FROZEN_GUARDS, "plan_sha256": sha256(plan_raw),
        "sources": audit, "pinned_source_opens": sum(source["opens"] for source in audit.values()),
        "future_source_opens": 0, "source_access_scope": "Pinned D-only aggregate integrity reads only",
        "calibration_count": len(bundles), "first_test_count": 0,
        "first_test_status": "NO_CERTIFIED_FIRST_TEST",
        "first_test_reason": "SEGMENT_DEFINITION_SOURCE_UNBOUND",
        "cases": {},
    }
    with TemporaryDirectory(prefix=".act070a-", dir=out.parent) as temp:
        stage = Path(temp) / "pack"
        (stage / CAL_DIR).mkdir(parents=True)
        (stage / TEST_DIR).mkdir()
        for case, chart in bundles:
            case_dir = stage / CAL_DIR / case["case_id"]
            case_dir.mkdir()
            (case_dir / "input.json").write_bytes(json_bytes(case) + b"\n")
            (case_dir / CHART_NAME).write_bytes(chart)
            (case_dir / B_SCHEMA.name).write_bytes(schema_raw)
            (case_dir / KB_RULES.name).write_bytes(kb_raw)
            receipt["cases"][case["case_id"]] = {
                "directory": f"{CAL_DIR}/{case['case_id']}", "d": case["d"], "input_sha256": case["input_sha256"],
                "chart_sha256": case["chart"]["sha256"], "chart_bars": len(case["chart"]["row_ids"]),
                "whitelist_rows": len(case["rows"]),
                "max_delivered_chart_date": case["d"],
                "max_ref_occurred_date": max(row["occurred_date"] for row in case["rows"]),
                "max_ref_first_knowable_date": max(row["first_knowable_date"] for row in case["rows"]),
                "immutable_b2": case["immutable_b2"],
            }
        (stage / A_RECEIPT_NAME).write_bytes(json_bytes(receipt) + b"\n")
        require(not out.exists() and not out.is_symlink(), "OUTPUT_EXISTS", str(out))
        stage.rename(out)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="new package directory in an existing parent")
    args = parser.parse_args()
    try:
        receipt = generate(args.plan.read_bytes(), args.out.absolute())
    except (Rejected, OSError, ValueError, KeyError) as exc:
        print(json_bytes({"status": "STOP", "code": getattr(exc, "code", "SOURCE_OR_IO_ERROR"),
                          "detail": str(exc)}).decode("utf-8"))
        return 1
    print(json_bytes({"status": "GENERATED", "calibration_count": receipt["calibration_count"],
                      "first_test_count": receipt["first_test_count"], "future_source_opens": 0,
                      "receipt": str(args.out / A_RECEIPT_NAME)}).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
