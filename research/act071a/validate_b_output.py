"""Validate V1.1 candidate-only B JSON against a separate trusted A receipt."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from subprocess import SubprocessError

from research.act070a.case_contract import Rejected, iso_day, json_bytes, require, strict_json
from research.act070a.validate_b_output import SCHEMA_KEYS, resolve_ref, validate_claim as validate_v1_claim
from research.act071a.case_contract import B_SCHEMA, KB_RULES, PNG_NAME, RECEIPT_SCHEMA, SVG_NAME, verify_case

SUPPORTED_KEYS = SCHEMA_KEYS | {"allOf", "if", "then", "else"}


def matches_schema(value, node: dict, defs: dict) -> bool:
    """Evaluate the fixed V1.1 Draft 2020-12 keywords, including sibling rules."""
    require(not set(node) - SUPPORTED_KEYS, "UNSUPPORTED_SCHEMA", "unexpected schema keyword")
    if "$ref" in node:
        target = node["$ref"]
        require(target.startswith("#/$defs/"), "UNSUPPORTED_SCHEMA", target)
        if not matches_schema(value, defs[target.removeprefix("#/$defs/")], defs):
            return False
    if "anyOf" in node and not any(matches_schema(value, spec, defs) for spec in node["anyOf"]):
        return False
    if not all(matches_schema(value, spec, defs) for spec in node.get("allOf", [])):
        return False
    if "if" in node:
        branch = "then" if matches_schema(value, node["if"], defs) else "else"
        if branch in node and not matches_schema(value, node[branch], defs):
            return False
    if "const" in node and value != node["const"]:
        return False
    if "enum" in node and value not in node["enum"]:
        return False

    kind = node.get("type")
    kinds = {"object": dict, "array": list, "string": str, "null": type(None)}
    require(kind is None or kind in kinds, "UNSUPPORTED_SCHEMA", str(kind))
    if kind is not None and not isinstance(value, kinds[kind]):
        return False
    if isinstance(value, dict):
        props = node.get("properties", {})
        return (set(node.get("required", [])) <= value.keys()
                and (node.get("additionalProperties") is not False or value.keys() <= props.keys())
                and all(matches_schema(value[key], spec, defs) for key, spec in props.items() if key in value))
    if isinstance(value, list):
        return (len(value) >= node.get("minItems", 0)
                and ("items" not in node or all(matches_schema(item, node["items"], defs) for item in value))
                and (not node.get("uniqueItems") or len({json_bytes(item) for item in value}) == len(value)))
    return not isinstance(value, str) or "pattern" not in node or re.fullmatch(node["pattern"], value) is not None


def validate_claim(claim: dict, rows: dict, cutoff) -> dict:
    links = claim["anchor_links"]
    if claim["type"] == "OLD_ANCHOR_INVALIDATION":
        invalidations = [link["ref"] for link in links if link["relation"] == "INVALIDATES"]
        require(len(invalidations) == 1, "OLD_ANCHOR_PROOF_REQUIRED", claim["id"])
        old_anchor = invalidations[0]
        row = resolve_ref(old_anchor, rows, cutoff)
        record = row["fields"][old_anchor["field"]]
        require(row["kind"] == "PRIMITIVE" and old_anchor["field"] == "registered_support_object"
                and isinstance(record, dict) and set(record) == {"anchor_id", "threshold_ref"},
                "OLD_ANCHOR_PROOF_REQUIRED", claim["id"])
        # The legacy proof evaluator requires one bound support. This exact
        # relation target must qualify, so a REFERENCE cannot substitute for it.

    # The V1 evaluator rechecks bound break evidence and price/source roles and
    # takes the latest knowable date across all refs, including counterevidence.
    legacy = {**claim, "anchor_links": [link["ref"] for link in links]}
    verdict = validate_v1_claim(legacy, rows, cutoff)
    return {**verdict, "phase_label": claim["phase_label"]}


def validate_output(raw: bytes, case: dict, svg: bytes, png: bytes, schema_raw: bytes,
                    kb_raw: bytes, trusted_case_id: str, trusted_sha256: str) -> dict:
    try:
        rows = verify_case(case, svg, png, schema_raw, kb_raw, trusted_case_id, trusted_sha256)
        schema = strict_json(schema_raw)
        response = strict_json(raw)
        require(matches_schema(response, schema, schema["$defs"]), "SCHEMA_INVALID", "B output")
        require(response["case_id"] == trusted_case_id, "CASE_ID_MISMATCH", "B case ID")
        require(response["input_sha256"] == trusted_sha256, "INPUT_HASH_MISMATCH", "B case digest")
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
    except (KeyError, TypeError, AttributeError, ValueError, RecursionError, OSError, SubprocessError):
        return {"accepted": False, "code": "INVALID_CASE", "detail": "malformed case package or renderer"}


def validate_from_paths(case_dir: Path, trusted_receipt: Path, output: Path) -> dict:
    try:
        case_dir = case_dir.resolve()
        require(not trusted_receipt.resolve().is_relative_to(case_dir),
                "INVALID_A_RECEIPT", "A must hold the receipt separately from B")
        receipt = strict_json(trusted_receipt.read_bytes())
        require(receipt["schema_version"] == RECEIPT_SCHEMA, "INVALID_A_RECEIPT", "receipt schema")
        case_id = case_dir.name
        require(case_id in receipt["cases"], "CASE_ID_MISMATCH", "case is absent from A receipt")
        case = strict_json((case_dir / "input.json").read_bytes())
        return validate_output(
            output.read_bytes(), case, (case_dir / SVG_NAME).read_bytes(), (case_dir / PNG_NAME).read_bytes(),
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
