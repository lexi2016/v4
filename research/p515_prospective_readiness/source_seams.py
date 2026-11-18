"""Read-only verification for caller-supplied V4 evidence in P5.15.

The future operator binds the original bytes and sealed expected identities before
calling these functions. They never resolve CURRENT, query V4 or run a model.
"""
from datetime import date
import hashlib
import json
import math
import re

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\Z")
_ALLOWED_ROW_FIELDS = frozenset({"ts_code", "trade_date", "open", "high", "low", "close", "volume"})
_PRICE = ("open", "high", "low", "close", "volume")


def _pairs(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON object field")
    return result


def _unique_json(raw, expected_sha):
    if not isinstance(raw, bytes) or not _SHA.fullmatch(expected_sha or ""):
        raise ValueError("Missing original bytes or pinned SHA")
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("V4 evidence SHA mismatch")
    return json.loads(raw, object_pairs_hook=_pairs)


def _iso(compact):
    if not re.fullmatch(r"[0-9]{8}", compact or ""):
        raise ValueError("DATE_NOT_COMPACT")
    return date.fromisoformat(compact).isoformat()


def verify_top200(raw_body, D, source_metadata):
    """Verify the exact captured workbench response and return its ordered roster.

    `source_metadata` comes from the D manifest checked by the caller. It
    separates the numeric-workbench and panel source manifests.
    """
    iso = _iso(D)
    body = _unique_json(raw_body, source_metadata.get("top200_raw_sha256"))
    if body.get("schema") != "V4_A_SHARE_TOP200_V1" or body.get("data_date") != D:
        raise ValueError("TOP200_PRODUCT_OR_DATE")
    if body.get("status") not in {"PARTIAL_DESCRIPTIVE", "READY"}:
        raise ValueError("TOP200_PRODUCT_STATUS")
    bindings = (
        (body.get("source_generation"), source_metadata.get("generation")),
        (body.get("input_sha256"), source_metadata.get("input_sha256")),
        (body.get("numeric_manifest", {}).get("sha256"),
         source_metadata.get("top200_numeric_manifest_sha256")),
        (body.get("artifact", {}).get("sha256"), source_metadata.get("top200_artifact_sha256")),
    )
    if any(not _SHA.fullmatch(known or "") or actual != known for actual, known in bindings):
        raise ValueError("TOP200_SOURCE_IDENTITY")
    if "coverage" in body:
        raise ValueError("Expected bounded workbench response")
    rows = body.get("top200")
    if body.get("top200_count") != 200 or not isinstance(rows, list) or len(rows) != 200:
        raise ValueError("TOP200_CARDINALITY")
    roster = []
    for rank, row in enumerate(rows, 1):
        code = row.get("symbol")
        if (type(row.get("rank")) is not int or row["rank"] != rank
                or not _CODE.fullmatch(code or "") or row.get("source_date") != iso):
            raise ValueError("TOP200_RANK_OR_ROW_SOURCE")
        roster.append((rank, code))
    if len({code for _, code in roster}) != len(roster):
        raise ValueError("TOP200_DUPLICATE_SECURITY")
    return tuple(roster)


def verify_reader_projection(raw, D, source_metadata, roster, accepted_sessions):
    """Verify a bounded Reader export, including each raw row's time and scope.

    Missing bars remain absent. No user-price values or outcomes are synthesized.
    The exact row export and the expected identifiers must both be sealed by the
    upstream capture workflow.
    """
    _iso(D)
    body = _unique_json(raw, source_metadata.get("reader_projection_sha256"))
    if body.get("format") != "P515_D_ONLY_READER_PROJECTION_V1" or body.get("D") != D:
        raise ValueError("READER_PROJECTION_FORMAT_OR_DATE")
    for k in ("generation", "input_sha256", "panel_manifest_sha256", "reader_sha256",
              "adjustment_snapshot_sha256"):
        expected = source_metadata.get(k)
        if not _SHA.fullmatch(expected or "") or body.get(k) != expected:
            raise ValueError("READER_PROJECTION_SOURCE")
    if (body.get("price_basis"), body.get("volume_basis"), body.get("price_adjustment_asof")) != (
            "QFQ_ASOF", "QFQ_EVENT_VOLUME", D):
        raise ValueError("READER_PROJECTION_BASIS")
    query = body.get("query", {})
    start, end = query.get("start"), query.get("end")
    _iso(start)
    dates = list(accepted_sessions)
    if (end != D or dates != sorted(set(dates))
            or not dates or dates[0] != start or dates[-1] != D or len(dates) > 120):
        raise ValueError("READER_PROJECTION_WINDOW")
    codes = query.get("ts_codes")
    actual_roster = {code for _, code in roster if code.endswith((".SH", ".SZ"))}
    if (not isinstance(codes, list) or len(codes) != len(set(codes))
            or set(codes) != actual_roster or set(query.get("columns", ())) != _ALLOWED_ROW_FIELDS):
        raise ValueError("READER_PROJECTION_QUERY")
    seen = set()
    rows = body.get("rows")
    if not isinstance(rows, list):
        raise ValueError("READER_PROJECTION_ROWS")
    sessions = set(dates)
    for row in rows:
        code, ts = row.get("ts_code"), row.get("trade_date")
        if (frozenset(row) != _ALLOWED_ROW_FIELDS or code not in actual_roster or
                ts not in sessions or (code, ts) in seen):
            raise ValueError("READER_PROJECTION_ROW_OR_DUPLICATE")
        if any(x is not None and (type(x) not in (float, int) or not math.isfinite(x))
               for x in map(row.get, _PRICE)):
            raise ValueError("READER_PROJECTION_BAD_NUMBER")
        seen.add((code, ts))
    return {"projection_sha256": source_metadata["reader_projection_sha256"], "rows": len(seen),
            "max_trade_date": max((ts for _, ts in seen), default=None),
            "D_bar_codes": tuple(sorted(code for code, ts in seen if ts == D))}
