"""V1.1 A-owned case format, D-only chronology and chart bindings."""

from __future__ import annotations

import re
from pathlib import Path

from research.act070a.case_contract import (
    FROZEN_GUARDS, OHLCV_FIELDS, SOURCE_HASHES, case_digest, decimal_number,
    ensure_no_later_date, iso_day, json_bytes, require, require_chronology, row_id,
    sha256, strict_json,
)
from research.act070a.chart import CHART_SESSIONS, render_chart
from research.act071a.chart import RENDERER, render_png

HERE = Path(__file__).resolve().parent
B_SCHEMA = HERE / "act071a_b_output_schema_v1_1.json"
KB_RULES = HERE / "kb_rule_cards_v1_1.json"
OUTPUT_SCHEMA = "ACT070A_B_OUTPUT_V1_1"
INPUT_SCHEMA = "ACT070A_CASE_INPUT_V1_1"
RECEIPT_SCHEMA = "ACT070A_A_CASE_RECEIPT_V1_1"
RECEIPT_NAME = "A_CASE_RECEIPT_V1_1.json"
CALIBRATION_DIR = "01_CALIBRATION_4D_V1_1"
FIRST_TEST_DIR = "02_FIRST_TEST_8D_V1_1"
SVG_NAME = "chart.svg"
PNG_NAME = "chart.png"
CASE_FILES = ("input.json", SVG_NAME, PNG_NAME, B_SCHEMA.name, KB_RULES.name)
FIELD_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,47}")
STOCK_PATTERN = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)")
CASE_PATTERNS = {"EXPOSED_REGRESSION": re.compile(r"C0[1-4]"), "FIRST_TEST": re.compile(r"T0[1-8]")}


def normalize_rows(rows: list[dict]) -> list[dict]:
    projected = []
    for row in rows:
        fields = dict(row["fields"])
        if "OHLCV" in fields:
            require(row["kind"] == "PRIMITIVE" and "ohlcv" not in fields,
                    "OHLCV_ALIAS_COLLISION", row["row_id"])
            fields["ohlcv"] = fields.pop("OHLCV")
        projected.append({**row, "fields": fields})
    return projected


def _verify_rows(case: dict, cutoff) -> tuple[dict, list]:
    rows, chart_rows = {}, []
    for row in case["rows"]:
        item_id = row["row_id"]
        require(isinstance(item_id, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", item_id)
                and item_id.startswith(f"{case['case_id']}_") and item_id not in rows,
                "INVALID_WHITELIST", "case-local unique A row ID")
        require_chronology(row["occurred_date"], row["first_knowable_date"], cutoff, item_id)
        ensure_no_later_date(row, cutoff, item_id)
        fields = row["fields"]
        require(row["status"] in {"OBSERVED_D_ONLY", "MISSING_SOURCE"} and isinstance(fields, dict)
                and all(FIELD_PATTERN.fullmatch(field) for field in fields),
                "INVALID_WHITELIST", item_id)
        rows[item_id] = row
        if row["kind"] != "CHART_BAR":
            continue
        require(row["status"] == "OBSERVED_D_ONLY" and set(fields) == {"date", *OHLCV_FIELDS}
                and fields["date"] == row["occurred_date"] == row["first_knowable_date"],
                "INVALID_CHART_MAPPING", item_id)
        opening, high, low, close, volume = [decimal_number(fields[key]) for key in OHLCV_FIELDS]
        require(0 < low <= min(opening, close) <= max(opening, close) <= high and volume >= 0,
                "INVALID_CHART_MAPPING", item_id)
        chart_rows.append(row)

    require(len(chart_rows) == CHART_SESSIONS
            and case["chart"]["row_ids"] == [row["row_id"] for row in chart_rows],
            "INVALID_CHART_MAPPING", "ordered chart whitelist")
    chart_days = [row["fields"]["date"] for row in chart_rows]
    require(chart_days == sorted(set(chart_days)) and chart_days[-1] == case["d"],
            "INVALID_CHART_MAPPING", "chart order, uniqueness or D endpoint")
    indices = [row["source"]["stock_session_index"] for row in chart_rows]
    require(all(type(index) is int and index >= 0 for index in indices)
            and indices == list(range(indices[0], indices[0] + CHART_SESSIONS)),
            "INVALID_CHART_MAPPING", "stock-session indices must be consecutive")
    return rows, chart_rows


def verify_case(case: dict, svg: bytes, png: bytes, schema_raw: bytes, kb_raw: bytes,
                trusted_case_id: str, trusted_sha256: str, *, verify_raster: bool = True) -> dict:
    require(isinstance(case, dict) and case.get("schema_version") == INPUT_SCHEMA,
            "INVALID_CASE", "case input schema")
    require(case.get("case_id") == trusted_case_id, "CASE_ID_MISMATCH", "A receipt differs")
    require(case.get("input_sha256") == trusted_sha256 == case_digest(case),
            "INPUT_HASH_MISMATCH", "case payload differs from A receipt")
    scope = CASE_PATTERNS.get(case["scope"])
    require(scope and scope.fullmatch(trusted_case_id) and STOCK_PATTERN.fullmatch(case["stock_code"]),
            "INVALID_CASE", "case group or A-share stock code")
    cutoff = iso_day(case["d"])
    require(case["schema_sha256"] == sha256(schema_raw) == sha256(B_SCHEMA.read_bytes()),
            "SCHEMA_HASH_MISMATCH", "case schema differs from frozen schema")
    require(case["kb_sha256"] == sha256(kb_raw) == sha256(KB_RULES.read_bytes()),
            "KB_HASH_MISMATCH", "case rules differ from frozen KB")
    require(case["kb_rule_ids"] == [card["id"] for card in strict_json(kb_raw)["cards"]],
            "INVALID_CASE", "KB rule roster")
    source = case["source_sha256"]
    require(isinstance(source, dict) and source
            and all(FIELD_PATTERN.fullmatch(key) and re.fullmatch(r"[a-f0-9]{64}", value)
                    for key, value in source.items())
            and (case["scope"] != "EXPOSED_REGRESSION"
                 or (case["stock_code"] == "002865.SZ" and source == SOURCE_HASHES)),
            "SOURCE_HASH_MISMATCH", "upstream identity differs")
    require(json_bytes(case["guards"]) == json_bytes(FROZEN_GUARDS), "INVALID_CASE", "research guards")

    chart = case["chart"]
    require(chart["svg"] == {"path": SVG_NAME, "sha256": sha256(svg)}
            and chart["png"] == {"path": PNG_NAME, "sha256": sha256(png)}
            and chart["renderer"] == RENDERER, "CHART_HASH_MISMATCH", "SVG, PNG or renderer differs")
    rows, chart_rows = _verify_rows(case, cutoff)
    require(render_chart(chart_rows) == svg, "INVALID_CHART_MAPPING", "SVG and A bars differ")
    if verify_raster:
        require(render_png(svg) == png, "INVALID_CHART_MAPPING", "PNG and frozen SVG raster differ")

    immutable = case["immutable_b2"]
    status = rows.get(row_id(trusted_case_id, "B2", "DAY"))
    final = chart_rows[-1]["fields"]
    bullish = decimal_number(final["close"]) > decimal_number(final["open"])
    require(status and status["kind"] == "A_DAY_STATUS" and status["status"] == "OBSERVED_D_ONLY"
            and status["occurred_date"] == case["d"] and status["fields"] == immutable
            and set(immutable) == {"day_eligibility", "day_eligibility_reason", "event_chain_state_b2",
                                  "formal_b2_event_presence"}
            and immutable["day_eligibility"] == ("UNKNOWN" if bullish else "FALSE")
            and immutable["event_chain_state_b2"] == "UNKNOWN"
            and immutable["formal_b2_event_presence"] == "ABSENT",
            "INVALID_B2_INVARIANT", "A status, required candle direction or chain absence")
    return rows
