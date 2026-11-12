"""Strict, self-hashed artifact/API/page parity receipt contract."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit


SCHEMA_VERSION = "v3_5.parity_receipt.v1"
LANE_STATUSES = frozenset({"PASS", "FAIL", "CANNOT_CONFIRM"})
SLICE_GATE_CLASSIFICATIONS = frozenset({"PASS", "EXPECTED_FAIL_NOT_PARITY"})
RAW_INPUT_ORIGINS = frozenset({"RAW_SOURCE", "LEGACY_FINAL_API"})
RAW_INPUT_USES = frozenset({"LIVE", "EXPECTED_ANSWER_ORACLE"})
VIEWPORT_SOURCES = frozenset({"BUILT_IN_BROWSER", "PLAYWRIGHT_FALLBACK"})
SOURCE_MISMATCH_REASON = "SOURCE_SHA_MISMATCH_V3_V4"
FALLBACK_REASON = "BUILT_IN_BROWSER_CONTROL_UNAVAILABLE"
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_HEX = frozenset("0123456789abcdef")
_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


class ParityReceiptError(ValueError):
    """Raised when parity evidence is incomplete, inconsistent, or tampered."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _HEX for character in value)
    )


def _date(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ParityReceiptError("business date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ParityReceiptError("business date must be real") from error
    return value


def _identifier(value: Any, context: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ParityReceiptError(f"invalid {context}")
    return value


def _relative_path(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ParityReceiptError(f"invalid {context} path")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or bool(windows_path.root)
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ParityReceiptError(f"invalid {context} path")
    return value


def _exact_mapping(value: Any, keys: set[str], context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ParityReceiptError(f"invalid {context}")
    return value


def _file_ref(value: Any, context: str, *, required: bool) -> None:
    if value is None and not required:
        return
    item = _exact_mapping(value, {"path", "sha256"}, context)
    _relative_path(item["path"], context)
    if not _is_sha256(item["sha256"]):
        raise ParityReceiptError(f"invalid {context} SHA")


def _string_list(value: Any, context: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or value != sorted(set(value))
    ):
        raise ParityReceiptError(f"invalid {context}")
    return value


def _non_empty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ParityReceiptError(f"invalid {context}")
    return value


def _lane_common(lane: Mapping[str, Any], business_date: str, context: str) -> str:
    status = lane.get("status")
    if status not in LANE_STATUSES:
        raise ParityReceiptError(f"invalid {context} status")
    if lane.get("observed_date") != business_date:
        raise ParityReceiptError(f"{context} date mismatch")
    differences = _string_list(lane.get("differences"), f"{context} differences")
    cannot_confirm = _string_list(
        lane.get("cannot_confirm"), f"{context} cannot_confirm"
    )
    if status == "PASS" and (differences or cannot_confirm):
        raise ParityReceiptError(f"PASS {context} must have no differences")
    if status == "FAIL" and not differences:
        raise ParityReceiptError(f"FAIL {context} requires differences")
    if status == "CANNOT_CONFIRM" and not cannot_confirm:
        raise ParityReceiptError(f"CANNOT_CONFIRM {context} requires reason")
    return str(status)


def _row_counts(value: Any, context: str) -> None:
    counts = _exact_mapping(value, {"v3", "v35"}, context)
    if any(type(count) is not int or count < 0 for count in counts.values()):
        raise ParityReceiptError(f"invalid {context}")


def _artifact_lane(value: Any, business_date: str) -> str:
    keys = {
        "status",
        "observed_date",
        "v3_artifact",
        "v3_manifest",
        "v35_artifact",
        "v35_manifest",
        "row_counts",
        "differences",
        "cannot_confirm",
    }
    lane = _exact_mapping(value, keys, "artifact lane")
    status = _lane_common(lane, business_date, "artifact lane")
    for field in ("v3_artifact", "v3_manifest", "v35_artifact", "v35_manifest"):
        _file_ref(lane[field], field, required=status == "PASS")
    _row_counts(lane["row_counts"], "artifact row_counts")
    return status


def _local_url(
    value: Any,
    context: str,
    *,
    business_date: str,
    expected_port: int,
) -> None:
    if not isinstance(value, str):
        raise ParityReceiptError(f"invalid {context}")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != expected_port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ParityReceiptError(f"invalid {context}")
    query = parse_qs(parsed.query, keep_blank_values=True)
    for field in ("date", "archive_date"):
        if field in query and query[field] != [business_date]:
            raise ParityReceiptError(f"{context} date mismatch")


def _api_lane(value: Any, business_date: str) -> str:
    keys = {
        "status",
        "observed_date",
        "endpoints",
        "http_status",
        "payload_sha256",
        "row_counts",
        "differences",
        "cannot_confirm",
    }
    lane = _exact_mapping(value, keys, "api lane")
    status = _lane_common(lane, business_date, "api lane")
    endpoints = _exact_mapping(lane["endpoints"], {"v3", "v35"}, "api endpoints")
    for name, endpoint in endpoints.items():
        _local_url(
            endpoint,
            f"api {name} endpoint",
            business_date=business_date,
            expected_port=8771 if name == "v3" else 8872,
        )
    http_status = _exact_mapping(
        lane["http_status"], {"v3", "v35"}, "api http_status"
    )
    if any(
        type(code) is not int or code < 100 or code > 599
        for code in http_status.values()
    ):
        raise ParityReceiptError("invalid api http_status")
    payload_sha = _exact_mapping(
        lane["payload_sha256"], {"v3", "v35"}, "api payload_sha256"
    )
    if any(not _is_sha256(digest) for digest in payload_sha.values()):
        raise ParityReceiptError("invalid api payload SHA")
    _row_counts(lane["row_counts"], "api row_counts")
    if status == "PASS" and any(code != 200 for code in http_status.values()):
        raise ParityReceiptError("PASS api lane requires HTTP 200")
    return status


def _side_mapping(value: Any, context: str) -> Mapping[str, Any]:
    return _exact_mapping(value, {"v3", "v35"}, context)


def _page_lane(value: Any, business_date: str) -> str:
    keys = {
        "status",
        "observed_date",
        "urls",
        "titles",
        "row_counts",
        "screenshots",
        "console_errors",
        "console_warnings",
        "timing_ms",
        "loading_complete",
        "horizontal_overflow",
        "differences",
        "cannot_confirm",
    }
    lane = _exact_mapping(value, keys, "page lane")
    status = _lane_common(lane, business_date, "page lane")
    urls = _side_mapping(lane["urls"], "page urls")
    for name, url in urls.items():
        _local_url(
            url,
            f"page {name} URL",
            business_date=business_date,
            expected_port=8771 if name == "v3" else 8872,
        )
    titles = _side_mapping(lane["titles"], "page titles")
    if any(not isinstance(title, str) for title in titles.values()):
        raise ParityReceiptError("invalid page titles")
    _row_counts(lane["row_counts"], "page row_counts")
    screenshots = _side_mapping(lane["screenshots"], "page screenshots")
    for name, screenshot in screenshots.items():
        _file_ref(screenshot, f"page {name} screenshot", required=status == "PASS")
    errors = _side_mapping(lane["console_errors"], "page console_errors")
    warnings = _side_mapping(lane["console_warnings"], "page console_warnings")
    for name in ("v3", "v35"):
        _string_list(errors[name], f"page {name} console_errors")
        _string_list(warnings[name], f"page {name} console_warnings")
    timing = _side_mapping(lane["timing_ms"], "page timing_ms")
    if any(
        value is not None
        and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < 0
        )
        for value in timing.values()
    ):
        raise ParityReceiptError("invalid page timing_ms")
    loading = _side_mapping(lane["loading_complete"], "page loading_complete")
    overflow = _side_mapping(
        lane["horizontal_overflow"], "page horizontal_overflow"
    )
    if any(
        type(value) is not bool
        for value in [*loading.values(), *overflow.values()]
    ):
        raise ParityReceiptError("invalid page state")
    if status == "PASS":
        if not all(loading.values()):
            raise ParityReceiptError("PASS page lane requires completed loading")
        if any(overflow.values()):
            raise ParityReceiptError("PASS page lane rejects horizontal overflow")
        if any(errors[name] for name in ("v3", "v35")):
            raise ParityReceiptError("PASS page lane requires zero console errors")
    return status


def _validate_body(receipt: Mapping[str, Any]) -> None:
    expected_keys = {
        "schema_version",
        "feature_id",
        "graph_baseline_semantic_hash",
        "graph_node_ids",
        "business_date",
        "view_id",
        "viewport",
        "source_sha256",
        "lanes",
        "verdict",
        "safety",
    }
    optional_keys = {"raw_input_sha256", "graph_slice_semantic_hash"}
    if not expected_keys <= set(receipt) <= expected_keys | optional_keys:
        raise ParityReceiptError("invalid parity receipt fields")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise ParityReceiptError("invalid parity receipt schema")
    _identifier(receipt.get("feature_id"), "feature_id")
    _identifier(receipt.get("view_id"), "view_id")
    if "raw_input_sha256" in receipt and not _is_sha256(receipt["raw_input_sha256"]):
        raise ParityReceiptError("invalid raw input SHA")
    if "graph_slice_semantic_hash" in receipt and not _is_sha256(
        receipt["graph_slice_semantic_hash"]
    ):
        raise ParityReceiptError("invalid graph slice semantic hash")
    if not _is_sha256(receipt.get("graph_baseline_semantic_hash")):
        raise ParityReceiptError("invalid graph baseline semantic hash")
    graph_node_ids = receipt.get("graph_node_ids")
    if (
        not isinstance(graph_node_ids, list)
        or not graph_node_ids
        or any(not isinstance(value, str) or not value for value in graph_node_ids)
        or graph_node_ids != sorted(set(graph_node_ids))
    ):
        raise ParityReceiptError("invalid graph_node_ids")
    business_date = _date(receipt.get("business_date"))
    viewport = _exact_mapping(
        receipt.get("viewport"),
        {"width", "height", "device_scale_factor", "source"},
        "viewport",
    )
    if (
        type(viewport["width"]) is not int
        or viewport["width"] < 320
        or type(viewport["height"]) is not int
        or viewport["height"] < 240
        or isinstance(viewport["device_scale_factor"], bool)
        or not isinstance(viewport["device_scale_factor"], (int, float))
        or viewport["device_scale_factor"] <= 0
        or viewport["source"] not in VIEWPORT_SOURCES
    ):
        raise ParityReceiptError("invalid viewport")
    source_sha = _exact_mapping(
        receipt.get("source_sha256"), {"v3", "v35"}, "source_sha256"
    )
    if any(not _is_sha256(digest) for digest in source_sha.values()):
        raise ParityReceiptError("invalid source SHA")
    lanes = _exact_mapping(
        receipt.get("lanes"), {"artifact", "api", "page"}, "parity lanes"
    )
    statuses = {
        "artifact": _artifact_lane(lanes["artifact"], business_date),
        "api": _api_lane(lanes["api"], business_date),
        "page": _page_lane(lanes["page"], business_date),
    }
    if source_sha["v3"] != source_sha["v35"]:
        for lane_name, status in statuses.items():
            if (
                status != "CANNOT_CONFIRM"
                or SOURCE_MISMATCH_REASON
                not in lanes[lane_name]["cannot_confirm"]
            ):
                raise ParityReceiptError(
                    "source SHA mismatch requires CANNOT_CONFIRM in every lane"
                )
    if viewport["source"] == "PLAYWRIGHT_FALLBACK" and (
        statuses["page"] != "CANNOT_CONFIRM"
        or FALLBACK_REASON not in lanes["page"]["cannot_confirm"]
    ):
        raise ParityReceiptError(
            "Playwright fallback requires visible built-in browser CANNOT_CONFIRM"
        )
    expected_verdict = (
        "FAIL"
        if "FAIL" in statuses.values()
        else "CANNOT_CONFIRM"
        if "CANNOT_CONFIRM" in statuses.values()
        else "PASS"
    )
    if receipt.get("verdict") != expected_verdict:
        raise ParityReceiptError("parity verdict does not match lane statuses")
    if receipt.get("safety") != _SAFETY:
        raise ParityReceiptError("unsafe parity receipt")


def _validate_slice_body(slice_contract: Mapping[str, Any]) -> Mapping[str, Any]:
    required_keys = {
        "legacy_source_refs",
        "raw_input_refs",
        "business_date",
        "cutoff",
        "v3_identities",
        "expected_v3_behavior",
        "allowed_paths",
        "rules",
        "expected_gate_classification",
    }
    slice_data = _exact_mapping(slice_contract.get("parity_slice"), required_keys, "graph slice")
    legacy_source_refs = slice_data.get("legacy_source_refs")
    if not isinstance(legacy_source_refs, list) or not legacy_source_refs:
        raise ParityReceiptError("missing legacy source refs")
    for item in legacy_source_refs:
        _file_ref(item, "legacy source ref", required=True)
    raw_input_refs = slice_data.get("raw_input_refs")
    if not isinstance(raw_input_refs, list) or not raw_input_refs:
        raise ParityReceiptError("missing raw input refs")
    for item in raw_input_refs:
        raw = _exact_mapping(item, {"path", "sha256", "origin", "use"}, "raw input ref")
        _relative_path(raw["path"], "raw input ref")
        if not _is_sha256(raw["sha256"]):
            raise ParityReceiptError("invalid raw input SHA")
        if raw["origin"] not in RAW_INPUT_ORIGINS or raw["use"] not in RAW_INPUT_USES:
            raise ParityReceiptError("invalid raw input origin/use")
        if raw["origin"] == "LEGACY_FINAL_API" and raw["use"] == "LIVE":
            raise ParityReceiptError("LEGACY_FINAL_API is forbidden for LIVE")
    _date(slice_data.get("business_date"))
    _non_empty_string(slice_data.get("cutoff"), "cutoff")
    identities = _exact_mapping(
        slice_data.get("v3_identities"), {"producers", "api", "dom"}, "V3 identities"
    )
    for field in ("producers", "api", "dom"):
        values = identities[field]
        if not isinstance(values, list) or not values:
            raise ParityReceiptError(f"missing V3 {field} identities")
        for item in values:
            _non_empty_string(item, f"V3 {field} identity")
    if not _string_list(slice_data.get("expected_v3_behavior"), "expected V3 behavior"):
        raise ParityReceiptError("missing expected V3 behavior")
    allowed_paths = slice_data.get("allowed_paths")
    if not isinstance(allowed_paths, list) or not allowed_paths:
        raise ParityReceiptError("missing allowed paths")
    for path in allowed_paths:
        _relative_path(path, "allowed")
    rules = _exact_mapping(slice_data.get("rules"), {"PASS", "REJECT"}, "slice rules")
    for name in ("PASS", "REJECT"):
        if not _string_list(rules[name], f"{name} rules"):
            raise ParityReceiptError(f"missing {name} rules")
    if slice_data.get("expected_gate_classification") not in SLICE_GATE_CLASSIFICATIONS:
        raise ParityReceiptError("invalid expected gate classification")
    if {key: slice_contract.get(key) for key in _SAFETY} != _SAFETY:
        raise ParityReceiptError("unsafe graph slice contract")
    return slice_data


def seal_graph_slice_contract(slice_contract: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        key: deepcopy(value)
        for key, value in slice_contract.items()
        if key != "semantic_hash"
    }
    _validate_slice_body(body)
    sealed = {**body, "semantic_hash": _sha256(body)}
    validate_graph_slice_contract(sealed)
    return sealed


def validate_graph_slice_contract(slice_contract: Mapping[str, Any]) -> None:
    if not isinstance(slice_contract, Mapping):
        raise ParityReceiptError("invalid graph slice contract schema")
    semantic_hash = slice_contract.get("semantic_hash")
    if not _is_sha256(semantic_hash):
        raise ParityReceiptError("invalid graph slice semantic hash")
    body = {
        key: deepcopy(value)
        for key, value in slice_contract.items()
        if key != "semantic_hash"
    }
    if _sha256(body) != semantic_hash:
        raise ParityReceiptError("graph slice semantic hash mismatch")
    _identifier(body.get("feature_id"), "feature_id")
    if not _is_sha256(body.get("graph_baseline_semantic_hash")):
        raise ParityReceiptError("invalid graph slice semantic hash")
    graph_node_ids = body.get("graph_node_ids")
    if (
        not isinstance(graph_node_ids, list)
        or not graph_node_ids
        or any(not isinstance(value, str) or not value for value in graph_node_ids)
    ):
        raise ParityReceiptError("missing graph node ids")
    _validate_slice_body(body)


def classify_parity_receipt_against_slice(
    receipt: Mapping[str, Any], slice_contract: Mapping[str, Any]
) -> str:
    """Return the fail-closed classification after binding a receipt to one slice."""
    validate_graph_slice_contract(slice_contract)
    validate_parity_receipt(receipt)
    slice_data = _validate_slice_body(slice_contract)
    if receipt["feature_id"] != slice_contract["feature_id"]:
        raise ParityReceiptError("receipt feature does not match graph slice")
    if receipt["graph_baseline_semantic_hash"] != slice_contract["graph_baseline_semantic_hash"]:
        raise ParityReceiptError("receipt graph hash does not match graph slice")
    if set(receipt["graph_node_ids"]) != set(slice_contract["graph_node_ids"]):
        raise ParityReceiptError("receipt graph nodes do not match graph slice")
    if receipt["business_date"] != slice_data["business_date"]:
        raise ParityReceiptError("receipt business date does not match graph slice")
    if "raw_input_sha256" not in receipt:
        raise ParityReceiptError("receipt is missing raw input SHA")
    if receipt.get("graph_slice_semantic_hash") != slice_contract["semantic_hash"]:
        raise ParityReceiptError("receipt slice hash does not match graph slice")
    raw_hashes = {item["sha256"] for item in slice_data["raw_input_refs"]}
    if receipt["raw_input_sha256"] not in raw_hashes:
        raise ParityReceiptError("receipt raw input SHA does not match graph slice")
    statuses = [receipt["lanes"][lane]["status"] for lane in ("artifact", "api", "page")]
    classification = (
        "PASS"
        if receipt["verdict"] == "PASS" and all(status == "PASS" for status in statuses)
        else "EXPECTED_FAIL_NOT_PARITY"
    )
    if classification != slice_data["expected_gate_classification"]:
        raise ParityReceiptError("receipt classification does not match graph slice")
    return classification


def seal_parity_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    body = {
        key: deepcopy(value)
        for key, value in receipt.items()
        if key != "receipt_semantic_hash"
    }
    _validate_body(body)
    return {**body, "receipt_semantic_hash": _sha256(body)}


def validate_parity_receipt(receipt: Mapping[str, Any]) -> None:
    if not isinstance(receipt, Mapping):
        raise ParityReceiptError("invalid parity receipt schema")
    semantic_hash = receipt.get("receipt_semantic_hash")
    if not _is_sha256(semantic_hash):
        raise ParityReceiptError("invalid parity receipt semantic hash")
    body = {
        key: deepcopy(value)
        for key, value in receipt.items()
        if key != "receipt_semantic_hash"
    }
    if _sha256(body) != semantic_hash:
        raise ParityReceiptError("parity receipt semantic hash mismatch")
    _validate_body(body)


def validate_parity_receipt_against_graph(
    receipt: Mapping[str, Any],
    graph_baseline: Mapping[str, Any],
    inventory_v2: Mapping[str, Any],
) -> None:
    validate_parity_receipt(receipt)
    try:
        from ops.migration.graph_baseline import (
            GraphBaselineError,
            validate_graph_baseline,
            validate_inventory_v2,
        )
    except ImportError as error:
        raise ParityReceiptError(f"invalid graph authority: {error}") from error
    try:
        validate_graph_baseline(graph_baseline)
        validate_inventory_v2(inventory_v2, baseline=graph_baseline)
    except GraphBaselineError as error:
        raise ParityReceiptError(f"invalid graph authority: {error}") from error
    if receipt["graph_baseline_semantic_hash"] != graph_baseline["semantic_hash"]:
        raise ParityReceiptError("parity graph baseline hash mismatch")
    registry = graph_baseline.get("graph_node_registry")
    registered_ids = registry.get("ids") if isinstance(registry, Mapping) else None
    if (
        not isinstance(registered_ids, list)
        or any(not isinstance(value, str) or not value for value in registered_ids)
    ):
        raise ParityReceiptError("invalid graph node registry")
    unknown = sorted(set(receipt["graph_node_ids"]) - set(registered_ids))
    if unknown:
        raise ParityReceiptError(f"unknown graph node: {unknown[0]}")
    features = inventory_v2.get("features")
    feature = (
        next(
            (
                item
                for item in features
                if isinstance(item, Mapping)
                and item.get("feature_id") == receipt["feature_id"]
            ),
            None,
        )
        if isinstance(features, list)
        else None
    )
    if not isinstance(feature, Mapping):
        raise ParityReceiptError("feature is not present in inventory v2")
    feature_nodes = feature.get("graph_node_ids")
    if not isinstance(feature_nodes, list) or not (
        set(receipt["graph_node_ids"]) & set(feature_nodes)
    ):
        raise ParityReceiptError("parity receipt has no feature-owned graph node")


__all__ = [
    "ParityReceiptError",
    "FALLBACK_REASON",
    "SCHEMA_VERSION",
    "SOURCE_MISMATCH_REASON",
    "seal_parity_receipt",
    "seal_graph_slice_contract",
    "classify_parity_receipt_against_slice",
    "validate_graph_slice_contract",
    "validate_parity_receipt",
    "validate_parity_receipt_against_graph",
]
