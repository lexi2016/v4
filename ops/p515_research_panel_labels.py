"""Bind P5.15 research annotations to an existing V4 panel generation."""
from __future__ import annotations

import argparse
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from p515_sample_frame import bind_source, code_exchange, is_a_share_record, sha256_file


SCHEMA = "p515.research_panel_label_overlay.v1"
FRAME_SCHEMA = "p515.full_universe_sample_frame.v1"
KEY = ("stable_security_id", "observation_date")
MARKERS = ("native_breakout_marker", "native_pullback_marker", "original_buy_signal")
FIELDS = (
    "selection_date_cohort", "exchange_stratum", "primary_sampling_stratum",
    "cap_tier_as_stored_nonpit", "liquidity_tercile_within_exchange_day",
    "volatility_tercile_within_exchange_day", "price_position_proxy", "market_regime_proxy",
    *MARKERS, "archetype_candidate_category", "archetype_proxy_reason",
    "phase_label", "pullback_label", "PIT_status", "UNKNOWN_reason",
)
SOURCE_FIELDS = (
    "selector_pointer_sha256", "selector_anchor_sha256", "generation_id",
    "candidate_receipt_sha256", "logical_reader_sha256",
)
PENDING_FIELDS = {
    "phase_label": "UNKNOWN_NOT_CREATED",
    "pullback_label": "UNKNOWN_NOT_CREATED",
    "PIT_status": "CANNOT_CONFIRM_HISTORICAL_PIT",
}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n").encode()


def sample_key(security, day):
    if not re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", security):
        raise ValueError(f"Invalid A-share stable security ID: {security}")
    if not re.fullmatch(r"[0-9]{8}", day):
        raise ValueError(f"Observation date must use YYYYMMDD: {day}")
    date(int(day[:4]), int(day[4:6]), int(day[6:]))
    return security, day


def panel_binding(pointer, reader, expected):
    if sha256_file(pointer) != expected["selector_pointer_sha256"]:
        raise ValueError("P515_STALE_SELECTOR_POINTER")
    panel, _, contract, _, bound = bind_source(pointer, reader)
    source = {
        "selector_pointer_sha256": hashlib.sha256(bound["pointer_bytes"]).hexdigest(),
        "selector_anchor_sha256": hashlib.sha256(bound["anchor_bytes"]).hexdigest(),
        "generation_id": contract["generation_id"],
        "candidate_receipt_sha256": hashlib.sha256(bound["manifest_bytes"]).hexdigest(),
        "logical_reader_sha256": sha256_file(reader),
    }
    if source != {field: expected[field] for field in SOURCE_FIELDS}:
        raise ValueError("P515_STALE_PANEL_GENERATION_OR_READER")
    return source, bound["reader_module"].LogicalFile(panel)


def frame_rows(path, expected_count):
    rows = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"stable_security_id", "trade_date", "ts_code", "market_type", "exchange", *FIELDS}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("P515_FRAME_COLUMNS_MISSING")
        for entry in reader:
            key = sample_key(entry["stable_security_id"], entry["trade_date"])
            if key in rows or key[0] != entry["ts_code"] or not is_a_share_record(entry):
                raise ValueError(f"P515_FRAME_KEY_CONFLICT: {key}")
            if code_exchange(entry)[0] != entry["exchange_stratum"]:
                raise ValueError(f"P515_FRAME_EXCHANGE_MISMATCH: {key}")
            if any(entry[field] != value for field, value in PENDING_FIELDS.items()):
                raise ValueError(f"P515_FRAME_CONTAINS_UNEXPECTED_ADJUDICATION: {key}")
            annotation = {field: entry[field] for field in FIELDS}
            for field in MARKERS:
                marker = annotation[field]
                if marker not in {"FALSE", "TRUE", "UNKNOWN"}:
                    raise ValueError(f"P515_FRAME_MARKER_INVALID: {field}={marker}")
                annotation[field] = {"FALSE": 0, "TRUE": 1, "UNKNOWN": "UNKNOWN"}[marker]
            rows[key] = annotation
    if not rows or len(rows) != expected_count:
        raise ValueError("P515_FRAME_ROW_COUNT_CONFLICT")
    return rows


def build(args):
    manifest_bytes = args.frame_manifest.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != args.frame_manifest_sha256:
        raise ValueError("P515_FRAME_MANIFEST_SHA_MISMATCH")
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != FRAME_SCHEMA or manifest.get("research_only") is not True:
        raise ValueError("P515_FRAME_SCHEMA_OR_SCOPE_MISMATCH")
    if manifest["production_allowed"] is not False or manifest["source"]["declared_historical_pit_certified"] is not False:
        raise ValueError("P515_FRAME_SCOPE_CONFLICT")
    frame_sha = sha256_file(args.frame)
    if frame_sha != manifest["output"]["sample_csv_sha256"]:
        raise ValueError("P515_FRAME_CSV_SHA_MISMATCH")
    source, _ = panel_binding(args.pointer, args.reader, manifest["source"])
    annotations = frame_rows(args.frame, manifest["sampling"]["actual_n"])
    if sha256_file(args.frame) != frame_sha:
        raise ValueError("P515_FRAME_CHANGED_DURING_READ")
    result = {
        "schema": SCHEMA, "research_only": True, "production_allowed": False,
        "source": source, "sample_frame_manifest_sha256": args.frame_manifest_sha256,
        "sample_frame_csv_sha256": frame_sha, "adjudicated_rows": 0,
        "rows": [{**dict(zip(KEY, key)), **annotation} for key, annotation in sorted(annotations.items())],
    }
    if sha256_file(args.pointer) != source["selector_pointer_sha256"]:
        raise ValueError("P515_POINTER_CHANGED_DURING_BUILD")
    with args.output.open("xb") as stream:
        stream.write(json_bytes(result))
    return {"rows": len(annotations), "sha256": sha256_file(args.output), "generation_id": source["generation_id"]}


def lookup(args):
    keys = [sample_key(*value) for value in args.key]
    if len(keys) > 24 or len(set(keys)) != len(keys):
        raise ValueError("Use 1 through 24 distinct exact panel keys per request")
    raw = args.overlay.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.overlay_sha256:
        raise ValueError("P515_OVERLAY_SHA_MISMATCH")
    overlay = json.loads(raw)
    if (
        overlay.get("schema") != SCHEMA
        or overlay.get("research_only") is not True
        or overlay.get("production_allowed") is not False
        or overlay.get("adjudicated_rows") != 0
    ):
        raise ValueError("P515_OVERLAY_SCHEMA_OR_SCOPE_MISMATCH")
    source, logical = panel_binding(args.pointer, args.reader, overlay["source"])
    annotations = {}
    for row in overlay["rows"]:
        key = sample_key(row[KEY[0]], row[KEY[1]])
        if key in annotations:
            raise ValueError(f"P515_OVERLAY_DUPLICATE_KEY: {key}")
        if any(row[field] != value for field, value in PENDING_FIELDS.items()):
            raise ValueError(f"P515_OVERLAY_CONTAINS_UNEXPECTED_ADJUDICATION: {key}")
        annotations[key] = {field: row[field] for field in FIELDS}
    # This filter form allows the established logical reader to use its own
    # symbol-to-block index. Apply exact date+security membership after read.
    columns = ["ts_code", "trade_date", "market_type", "exchange"]
    table = logical.read(columns=columns, filters=[
        ("ts_code", "in", sorted({key[0] for key in keys})),
        ("trade_date", "in", sorted({key[1] for key in keys})),
    ])
    requested = set(keys)
    panel_rows = {}
    for row in table.to_pylist():
        key = row["ts_code"], row["trade_date"]
        if key in panel_rows:
            raise ValueError(f"P515_PANEL_DUPLICATE_KEY: {key}")
        if key in requested:
            if not is_a_share_record(row):
                raise ValueError(f"P515_PANEL_MARKET_SCOPE_CONFLICT: {key}")
            panel_rows[key] = row

    result = []
    for key in keys:
        panel_row = panel_rows.get(key)
        annotation = annotations.get(key)
        if annotation and panel_row is None:
            raise ValueError(f"P515_OVERLAY_KEY_NOT_IN_BOUND_PANEL: {key}")
        if annotation and annotation["exchange_stratum"] != code_exchange(panel_row)[0]:
            raise ValueError(f"P515_OVERLAY_EXCHANGE_MISMATCH: {key}")
        if annotation:
            research = {"status": "SAMPLED_PENDING_ADJUDICATION", **annotation}
        else:
            status = "NOT_SAMPLED" if panel_row else "PANEL_ROW_MISSING"
            research = {"status": status, **PENDING_FIELDS, "UNKNOWN_reason": status}
        result.append({**dict(zip(KEY, key)), "panel": panel_row, "p515_research": research})
    if sha256_file(args.pointer) != source["selector_pointer_sha256"]:
        raise ValueError("P515_POINTER_CHANGED_DURING_LOOKUP")
    return {"generation_id": source["generation_id"], "overlay_sha256": args.overlay_sha256, "rows": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build")
    builder.add_argument("--frame", required=True, type=Path)
    builder.add_argument("--frame-manifest", required=True, type=Path)
    builder.add_argument("--frame-manifest-sha256", required=True)
    builder.add_argument("--output", required=True, type=Path)
    reader = commands.add_parser("lookup")
    reader.add_argument("--overlay", required=True, type=Path)
    reader.add_argument("--overlay-sha256", required=True)
    reader.add_argument("--key", required=True, action="append", nargs=2, metavar=("SECURITY", "YYYYMMDD"))
    for child in (builder, reader):
        child.add_argument("--pointer", required=True, type=Path)
        child.add_argument("--reader", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = build(args) if args.command == "build" else lookup(args)
    except (OSError, KeyError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    print(json_bytes(result).decode(), end="")


if __name__ == "__main__":
    main()
