"""Shared ACT-070A protocol and package integrity checks."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
B_SCHEMA = HERE / "act070a_b_output_schema_v1.json"
KB_RULES = HERE / "kb_rule_cards_v1.json"
INPUT_SCHEMA = "ACT070A_CASE_INPUT_V1"
RECEIPT_SCHEMA = "ACT070A_A_CASE_RECEIPT_V1"
CHART_NAME = "chart.svg"
ISO_DATE_TOKEN = re.compile(r"(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?![0-9])")
PRICE_FIELDS = ("open", "high", "low", "close")
OHLCV_FIELDS = (*PRICE_FIELDS, "volume")
SOURCE_HASHES = {
    "primitive_evidence_ledger": "11d360a7acda5b67061cef46d773934b50be1cd43a8fd6a9783da2c030542444",
    "day_vs_chain_status": "c13ceac91f2731affd8b3725dd780d0d0bb049058b43d07f4291c107e852fb18",
    "state_machine_contract": "3c5beebdc9ee120f452caf529b8d9e2f589a0fad50bf6dbd0e40af1ecea99bcd",
    "common_indicators_d_only": "4d886e42bb64990db759be8dc63425ddde8bf226d1bd16759b450e194c1499cb",
}
FROZEN_GUARDS = {
    "RESEARCH_ONLY": True,
    "S_FIT": 0,
    "B_FIT": 0,
    "PRODUCTION_ALLOWED": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


class Rejected(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def require(condition: object, code: str, detail: str) -> None:
    if not condition:
        raise Rejected(code, detail[:256])


def strict_json(raw: bytes):
    def pairs_to_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "DUPLICATE_JSON_KEY", key)
            result[key] = value
        return result

    def reject_constant(token):
        raise Rejected("INVALID_JSON", token)

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs_to_object, parse_constant=reject_constant)
    except Rejected:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise Rejected("INVALID_JSON", str(exc)) from exc


def json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def case_digest(case: dict) -> str:
    return sha256(json_bytes({key: value for key, value in case.items() if key != "input_sha256"}))


def iso_day(value) -> date:
    require(isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value),
            "INVALID_DATE", str(value))
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise Rejected("INVALID_DATE", value) from exc


def decimal_number(value) -> Decimal:
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise Rejected("INVALID_PRICE", str(value)) from exc
    require(number.is_finite(), "INVALID_PRICE", str(value))
    return number


def require_chronology(occurred, known, cutoff, subject):
    occurred_on, known_on = iso_day(occurred), iso_day(known)
    require(occurred_on <= known_on, "INVALID_CHRONOLOGY", subject)
    require(known_on <= cutoff, "OUT_OF_D_REFERENCE", subject)


def ensure_no_later_date(value, cutoff, subject: str) -> None:
    if isinstance(value, dict):
        for item in value.values():
            ensure_no_later_date(item, cutoff, subject)
    elif isinstance(value, list):
        for item in value:
            ensure_no_later_date(item, cutoff, subject)
    elif isinstance(value, str):
        for token in ISO_DATE_TOKEN.findall(value):
            require(iso_day(token) <= cutoff, "OUT_OF_D_REFERENCE", subject)


def row_id(case_id: str, *parts: str) -> str:
    return "_".join((case_id, *parts))


def verify_case(case: dict, chart_raw: bytes, schema_raw: bytes, kb_raw: bytes,
                trusted_case_id: str, trusted_sha256: str) -> dict[str, dict]:
    require(isinstance(case, dict) and case.get("schema_version") == INPUT_SCHEMA,
            "INVALID_CASE", "case input schema")
    require(case.get("case_id") == trusted_case_id, "CASE_ID_MISMATCH", "A receipt differs")
    require(case.get("input_sha256") == trusted_sha256 == case_digest(case),
            "INPUT_HASH_MISMATCH", "case payload differs from A receipt")
    cutoff = iso_day(case["d"])
    require(case["schema_sha256"] == sha256(schema_raw) == sha256(B_SCHEMA.read_bytes()),
            "SCHEMA_HASH_MISMATCH", "case schema differs from frozen schema")
    require(case["kb_sha256"] == sha256(kb_raw) == sha256(KB_RULES.read_bytes()),
            "KB_HASH_MISMATCH", "case rules differ from frozen KB")
    kb = strict_json(kb_raw)
    require(case["kb_rule_ids"] == [card["id"] for card in kb["cards"]], "INVALID_CASE", "KB rule roster")
    require(case["source_sha256"] == SOURCE_HASHES, "SOURCE_HASH_MISMATCH", "upstream pin differs")
    require(json_bytes(case["guards"]) == json_bytes(FROZEN_GUARDS), "INVALID_CASE", "research guards")
    chart = case["chart"]
    require(chart["path"] == CHART_NAME and chart["sha256"] == sha256(chart_raw),
            "CHART_HASH_MISMATCH", "exact chart bytes differ")
    rows = {}
    chart_row_ids = []
    for row in case["rows"]:
        item_id = row["row_id"]
        require(isinstance(item_id, str) and item_id.startswith(f"{trusted_case_id}_") and item_id not in rows,
                "INVALID_WHITELIST", "row ID must be assigned once within the A case")
        require_chronology(row["occurred_date"], row["first_knowable_date"], cutoff, item_id)
        ensure_no_later_date(row, cutoff, item_id)
        require(row["status"] in {"OBSERVED_D_ONLY", "MISSING_SOURCE"} and isinstance(row["fields"], dict),
                "INVALID_WHITELIST", item_id)
        rows[item_id] = row
        if row["kind"] == "CHART_BAR":
            fields = row["fields"]
            require(row["status"] == "OBSERVED_D_ONLY" and set(fields) == {"date", *OHLCV_FIELDS}
                    and fields["date"] == row["occurred_date"] == row["first_knowable_date"],
                    "INVALID_CHART_MAPPING", item_id)
            prices = [decimal_number(fields[key]) for key in OHLCV_FIELDS]
            opening, high, low, close, volume = prices
            require(0 < low <= min(opening, close) <= max(opening, close) <= high and volume >= 0,
                    "INVALID_CHART_MAPPING", item_id)
            chart_row_ids.append(item_id)
    require(chart_row_ids and chart["row_ids"] == chart_row_ids,
            "INVALID_CHART_MAPPING", "ordered chart/whitelist parity")
    chart_days = [rows[item_id]["fields"]["date"] for item_id in chart_row_ids]
    require(chart_days == sorted(set(chart_days)) and chart_days[-1] == case["d"],
            "INVALID_CHART_MAPPING", "chart order, uniqueness or D endpoint")

    immutable_b2 = case["immutable_b2"]
    b2_row = rows.get(row_id(trusted_case_id, "B2", "DAY"))
    require(b2_row and b2_row["kind"] == "A_DAY_STATUS" and b2_row["status"] == "OBSERVED_D_ONLY"
            and b2_row["occurred_date"] == case["d"] and b2_row["fields"] == immutable_b2
            and set(immutable_b2) == {"day_eligibility", "day_eligibility_reason", "event_chain_state_b2",
                                      "formal_b2_event_presence"}
            and immutable_b2["day_eligibility"] in {"FALSE", "UNKNOWN"}
            and immutable_b2["event_chain_state_b2"] == "UNKNOWN"
            and immutable_b2["formal_b2_event_presence"] == "ABSENT",
            "INVALID_B2_INVARIANT", "A status/absence must remain immutable")
    return rows
