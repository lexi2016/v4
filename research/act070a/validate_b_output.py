"""Validate a candidate-only B response and derive observable dates on A."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from research.act070a.case_contract import (
    B_SCHEMA, CHART_NAME, KB_RULES, PRICE_FIELDS, RECEIPT_SCHEMA, Rejected, decimal_number,
    iso_day, json_bytes, require, require_chronology, strict_json, verify_case,
)
from research.act070a.chart import render_chart

SCHEMA_KEYS = {
    "$schema", "$id", "$defs", "$ref", "anyOf", "type", "const", "enum", "pattern",
    "properties", "required", "additionalProperties", "items", "uniqueItems", "minItems",
}
REF_ROLES = ("anchor_links", "evidence_refs", "counterevidence_refs")
CLAIM_KB = {
    "KEY_K": "KB_KEY_K",
    "PIVOT": "KB_N_BREATHING",
    "SUPPORT": "KB_SUPPORT_BREAK",
    "OLD_ANCHOR_INVALIDATION": "KB_SUPPORT_BREAK",
    "PHASE": "KB_N_BREATHING",
}


def matches_schema(value, node: dict, defs: dict) -> bool:
    """The fixed schema uses only this subset of Draft 2020-12."""
    if set(node) - SCHEMA_KEYS:
        raise Rejected("UNSUPPORTED_SCHEMA", "unexpected schema keyword")
    if "$ref" in node:
        ref = node["$ref"]
        require(ref.startswith("#/$defs/"), "UNSUPPORTED_SCHEMA", ref)
        if not matches_schema(value, defs[ref.removeprefix("#/$defs/")], defs):
            return False
    if "anyOf" in node and not any(matches_schema(value, option, defs) for option in node["anyOf"]):
        return False
    if "const" in node and value != node["const"]:
        return False
    if "enum" in node and value not in node["enum"]:
        return False
    kind = node.get("type")
    if kind == "object":
        props = node["properties"]
        return (isinstance(value, dict) and set(node["required"]) <= value.keys()
                and (node.get("additionalProperties") is not False or value.keys() <= props.keys())
                and all(matches_schema(item, props[key], defs) for key, item in value.items() if key in props))
    if kind == "array":
        return (isinstance(value, list) and len(value) >= node.get("minItems", 0)
                and all(matches_schema(item, node["items"], defs) for item in value)
                and (not node.get("uniqueItems") or len({json_bytes(item) for item in value}) == len(value)))
    if kind == "string":
        return isinstance(value, str) and ("pattern" not in node or re.fullmatch(node["pattern"], value) is not None)
    if kind == "null":
        return value is None
    require(kind is None, "UNSUPPORTED_SCHEMA", str(kind))
    return True


def resolve_ref(ref: dict, rows: dict[str, dict], cutoff, *, permitted_fields=None) -> dict:
    item_id, field = ref["row_id"], ref["field"]
    row = rows.get(item_id)
    require(row is not None, "UNKNOWN_REFERENCE", item_id)
    require(row["status"] != "MISSING_SOURCE", "MISSING_SOURCE_REFERENCE", item_id)
    require(field in row["fields"], "UNKNOWN_REFERENCE", f"{item_id}.{field}")
    require(permitted_fields is None or (row["kind"] == "CHART_BAR" and field in permitted_fields),
            "REFERENCE_ROLE_MISMATCH", f"{item_id}.{field}")
    require_chronology(row["occurred_date"], row["first_knowable_date"], cutoff, item_id)
    return row


def anchored_break(claim: dict, rows: dict[str, dict], cutoff) -> str:
    """A source-bound old object and same-object close break are mandatory."""
    anchors = []
    for ref in claim["anchor_links"]:
        row = rows[ref["row_id"]]
        if row["kind"] == "PRIMITIVE" and ref["field"] == "registered_support_object":
            record = row["fields"][ref["field"]]
            if isinstance(record, dict) and set(record) == {"anchor_id", "threshold_ref"}:
                anchors.append((row, record))
    breaks = []
    for ref in claim["evidence_refs"]:
        row = rows[ref["row_id"]]
        if row["kind"] == "PRIMITIVE" and ref["field"] == "anchored_invalidation":
            record = row["fields"][ref["field"]]
            if isinstance(record, dict) and set(record) == {"anchor_id", "kind", "close_ref"}:
                breaks.append((row, record))
    require(len(anchors) == 1 and len(breaks) == 1, "OLD_ANCHOR_PROOF_REQUIRED", claim["id"])
    (anchor_row, anchor), (break_row, broken) = anchors[0], breaks[0]
    require(isinstance(anchor["anchor_id"], str) and anchor["anchor_id"]
            and anchor["anchor_id"] == broken["anchor_id"] and broken["kind"] == "ACTIVE_ANCHOR_CLOSE_BREAK",
            "OLD_ANCHOR_PROOF_REQUIRED", claim["id"])
    threshold_ref, close_ref = anchor["threshold_ref"], broken["close_ref"]
    require(threshold_ref in claim["anchor_links"] and close_ref in claim["evidence_refs"],
            "OLD_ANCHOR_PROOF_REQUIRED", claim["id"])
    threshold_row = resolve_ref(threshold_ref, rows, cutoff, permitted_fields=PRICE_FIELDS)
    close_row = resolve_ref(close_ref, rows, cutoff, permitted_fields=("close",))
    require(threshold_row["first_knowable_date"] <= anchor_row["first_knowable_date"]
            < break_row["occurred_date"] == close_row["occurred_date"]
            and decimal_number(close_row["fields"]["close"])
            < decimal_number(threshold_row["fields"][threshold_ref["field"]]),
            "OLD_ANCHOR_PROOF_REQUIRED", claim["id"])
    return break_row["occurred_date"]


def validate_claim(claim: dict, rows: dict[str, dict], cutoff) -> dict:
    require(CLAIM_KB[claim["type"]] in claim["kb_rule_ids"], "KB_RULE_MISMATCH", claim["id"])
    referenced = []
    for role in REF_ROLES:
        for ref in claim[role]:
            row = resolve_ref(ref, rows, cutoff)
            require(row["kind"] != "A_DAY_STATUS" or role == "counterevidence_refs",
                    "IMMUTABLE_B2_REFERENCE", claim["id"])
            referenced.append(row)
    require(claim["evidence_refs"], "CANDIDATE_EVIDENCE_REQUIRED", claim["id"])

    span = {}
    for key, ref in claim["span_refs"].items():
        if ref is not None:
            span[key] = resolve_ref(ref, rows, cutoff, permitted_fields=("date",))
    require("end" not in span or "start" in span, "INVALID_SPAN", claim["id"])
    if "end" in span:
        require(span["start"]["occurred_date"] <= span["end"]["occurred_date"], "INVALID_SPAN", claim["id"])
    referenced.extend(span.values())

    prices = {}
    for key, ref in claim["price_refs"].items():
        if ref is not None:
            row = resolve_ref(ref, rows, cutoff, permitted_fields=PRICE_FIELDS)
            prices[key] = decimal_number(row["fields"][ref["field"]])
            referenced.append(row)
    if set(prices) == {"low", "high"}:
        require(prices["low"] <= prices["high"], "INVALID_PRICE_RANGE", claim["id"])

    occurred, knowable, rule = "UNRESOLVED", "UNRESOLVED", "UNRESOLVED"
    if claim["type"] == "OLD_ANCHOR_INVALIDATION":
        occurred, rule = anchored_break(claim, rows, cutoff), "ANCHORED_BREAK_V1"
    if claim["type"] == "KEY_K" and "end" in span and span["start"] == span["end"]:
        bar_id = span["start"]["row_id"]
        cited = {ref["field"] for ref in claim["evidence_refs"] if ref["row_id"] == bar_id}
        if "volume" in cited and cited.intersection(PRICE_FIELDS):
            occurred, rule = span["start"]["occurred_date"], "SINGLE_BAR_KEY_K_V1"
    if rule != "UNRESOLVED":
        knowable = max(row["first_knowable_date"] for row in referenced)
        require_chronology(occurred, knowable, cutoff, claim["id"])
    return {
        "id": claim["id"], "type": claim["type"], "status": claim["status"],
        "occurred_date": occurred, "first_knowable_date": knowable, "time_rule": rule,
    }


def validate_output(raw: bytes, case: dict, chart_raw: bytes, schema_raw: bytes,
                    kb_raw: bytes, trusted_case_id: str, trusted_sha256: str) -> dict:
    try:
        rows = verify_case(case, chart_raw, schema_raw, kb_raw, trusted_case_id, trusted_sha256)
        require(render_chart([rows[item_id] for item_id in case["chart"]["row_ids"]]) == chart_raw,
                "INVALID_CHART_MAPPING", "chart contents disagree with ordered bar whitelist")
        schema = strict_json(schema_raw)
        response = strict_json(raw)
        require(matches_schema(response, schema, schema["$defs"]), "SCHEMA_INVALID", "B output")
        require(response["case_id"] == trusted_case_id, "CASE_ID_MISMATCH", "B case_id")
        require(response["input_sha256"] == trusted_sha256, "INPUT_HASH_MISMATCH", "B input_sha256")
        ids = [claim["id"] for claim in response["claims"]]
        require(len(ids) == len(set(ids)), "DUPLICATE_CLAIM_ID", "claim IDs")
        require(ids or response["abstain_codes"], "ABSTAIN_CODE_REQUIRED", "empty response")
        cutoff = iso_day(case["d"])
        claims = [validate_claim(claim, rows, cutoff) for claim in response["claims"]]
        return {"accepted": True, "code": "ACCEPTED_CANDIDATE_ONLY", "case_id": trusted_case_id,
                "input_sha256": trusted_sha256, "claims": claims, "abstain_codes": response["abstain_codes"],
                "immutable_b2": case["immutable_b2"]}
    except Rejected as exc:
        return {"accepted": False, "code": exc.code, "detail": str(exc)}
    except (KeyError, TypeError, AttributeError, ValueError, RecursionError):
        return {"accepted": False, "code": "INVALID_CASE", "detail": "malformed case package"}


def validate_from_paths(case_dir: Path, trusted_receipt: Path, output: Path) -> dict:
    try:
        case_dir = case_dir.resolve()
        require(not trusted_receipt.resolve().is_relative_to(case_dir),
                "INVALID_A_RECEIPT", "trusted digest must be held separately by A")
        receipt = strict_json(trusted_receipt.read_bytes())
        require(receipt["schema_version"] == RECEIPT_SCHEMA, "INVALID_A_RECEIPT", "receipt schema")
        case = strict_json((case_dir / "input.json").read_bytes())
        case_id = case_dir.name
        require(case_id in receipt["cases"], "CASE_ID_MISMATCH", "case is absent from A receipt")
        return validate_output(
            output.read_bytes(), case, (case_dir / CHART_NAME).read_bytes(),
            (case_dir / B_SCHEMA.name).read_bytes(), (case_dir / KB_RULES.name).read_bytes(),
            case_id, receipt["cases"][case_id]["input_sha256"],
        )
    except Rejected as exc:
        return {"accepted": False, "code": exc.code, "detail": str(exc)}
    except (OSError, KeyError, TypeError, AttributeError):
        return {"accepted": False, "code": "INPUT_OR_RECEIPT_UNAVAILABLE", "detail": "case, response or A receipt"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--trusted-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="raw B response JSON")
    args = parser.parse_args()
    verdict = validate_from_paths(args.case_dir, args.trusted_receipt, args.output)
    print(json_bytes(verdict).decode("utf-8"))
    return 0 if verdict["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
