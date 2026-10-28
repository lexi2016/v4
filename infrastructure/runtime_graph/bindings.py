"""Strict, V4-native evidence source bindings for the frozen runtime graph."""

from __future__ import annotations

import copy
import fnmatch
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


BINDINGS_PATH = Path(__file__).resolve().parents[2] / "contracts" / "v35_runtime_graph_evidence_bindings.json"
BOUND_NODE_IDS = frozenset(
    {
        "bilibili_fupan_nightly",
        "FUPAN_VIDEO_CHECK",
        "FUPAN_VIDEO_DOWNLOAD_ASR",
        "FUPAN_STOCKDICT",
        "FUPAN_VIDEO_TABLE_OCR_ALIGN",
        "FUPAN_VIDEO_GAP",
        "FUPAN_V3_PUBLISH",
        "FUPAN_8771_VERIFY",
        "FUPAN_CLOSE_MATERIALS",
        "FUPAN_REVIEW_START",
        "FUPAN_A_SHARE_STRUCTURE",
        "ashare_v193_slot_selector_premarket",
        "hkconnect_d1_top100_prob_active",
        "v3_opening_intraday_stage_select_0925_1500",
        "hkconnect_model_selection_review",
        "ashare_research_panel",
        "hkconnect_research_panel",
    }
)
_FORBIDDEN_TEXT = ("v3_" + "system", "v35_" + "v3", "87" + "71")
_ALLOWED_TOP_KEYS = frozenset(
    {"node_id", "expected_outputs", "status_sources", "receipt_date_fields", "api_probe", "api_date_fields", "semantic_validator"}
)
_ALLOWED_API_PROBE_KEYS = frozenset(
    {"path", "kind", "date_role", "stage_id", "pool_id"}
)
_ALLOWED_API_KINDS = frozenset(
    {"review_close_chain", "review_model_selection", "preselection_pool", "workbench_stage"}
)
_ALLOWED_API_STAGE_IDS = frozenset(
    {
        "STAGE_0925",
        "STAGE_0930_0935",
        "STAGE_0935_0940",
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
    }
)
_ALLOWED_API_POOL_IDS = frozenset({"a_d1_premarket_pool", "hkconnect_d1_top100"})
_ALLOWED_API_PATHS = frozenset(
    {
        "/api/v4/review?date={date}",
        "/api/v4/preselection-pools?date={target_date}&limit=200",
    }
)
_ALLOWED_SOURCE_KEYS = frozenset(
    {
        "artifact_role",
        "kind",
        "path",
        "stage_id",
        "semantic_alias",
        "semantic_fields",
        "projection",
        "receipt_path",
        "artifact_path",
        "manifest_path",
        "manifest_key",
        "date_role",
        "expected_schema",
        "receipt_role",
    }
)
_ALLOWED_KINDS = frozenset({"v35_artifact", "v35_receipt", "stage_latest"})
_ALLOWED_ARTIFACT_ROLES = frozenset({"bilibili_source", "node_receipt"})
_ALLOWED_RECEIPT_ROLES = frozenset({"node_action"})
_ALLOWED_SEMANTIC_VALIDATORS = frozenset({"review"})
_ALLOWED_PROJECTIONS = frozenset({"root", "close_chain_node", "model_review"})
_ALLOWED_DATE_ROLES = frozenset({"business_date", "target_date"})
_ALLOWED_MANIFEST_KEYS = frozenset(
    {
        "a_share_reviews/{date}.json",
        "a_d1_premarket_pool",
        "hkconnect_d1_top100",
        "close_reviews/{date}.json",
        "close_review_sources/{date}/bilibili/acceptance.json",
        "close_review_sources/{date}/bilibili/source_index.json",
        "close_review_sources/{date}/bilibili/capture_manifest.json",
        "close_review_sources/{date}/bilibili/current_asr_pointer.json",
        "close_review_sources/{date}/bilibili/stock_mentions.json",
        "close_review_sources/{date}/bilibili/alignment_pointer.json",
        "close_review_sources/{date}/bilibili/video_gap_audit.json",
    }
)
_ALLOWED_PREFIXES = ("{data_root}/",)
_ALLOWED_RELATIVE_PATTERNS = (
    "a_share_reviews/{date}.json",
    "a_share_reviews/receipts/{date}.json",
    "a_share_reviews/manifest.json",
    "preselection_pools/{target_date}/a_d1_premarket_pool.json",
    "preselection_pools/{target_date}/hkconnect_d1_top100.json",
    "preselection_pools/{target_date}/receipts/a_d1_premarket_pool.json",
    "preselection_pools/{target_date}/receipts/hkconnect_d1_top100.json",
    "preselection_pools/{target_date}/manifest.json",
    "close_reviews/{date}.json",
    "receipts/close_reviews/{date}.json",
    "manifest.json",
    "runtime_graph/evidence/node_action_status/{date}/bilibili_fupan_nightly.json",
    "runtime_graph/evidence/node_action_status/{date}/FUPAN_VIDEO_CHECK.json",
    "runtime_graph/evidence/node_action_status/{date}/FUPAN_VIDEO_DOWNLOAD_ASR.json",
    "runtime_graph/evidence/node_action_status/{date}/FUPAN_STOCKDICT.json",
    "runtime_graph/evidence/node_action_status/{date}/FUPAN_VIDEO_TABLE_OCR_ALIGN.json",
    "runtime_graph/evidence/node_action_status/{date}/FUPAN_VIDEO_GAP.json",
    "runtime_graph/evidence/node_action_status/{date}/FUPAN_V3_PUBLISH.json",
    "runtime_graph/evidence/node_action_status/{date}/FUPAN_8771_VERIFY.json",
    "runtime_graph/evidence/research_panel_status/{date}/ashare_research_panel.json",
    "runtime_graph/evidence/research_panel_status/{date}/hkconnect_research_panel.json",
    "close_review_sources/{date}/bilibili/acceptance.json",
    "close_review_sources/{date}/bilibili/source_index.json",
    "close_review_sources/{date}/bilibili/manifest.json",
    "close_review_sources/{date}/bilibili/capture_manifest.json",
    "close_review_sources/{date}/bilibili/transcript_stockdict/current_asr_pointer.json",
    "close_review_sources/{date}/bilibili/transcript_stockdict/stock_mentions.json",
    "close_review_sources/{date}/bilibili/video_ocr_alignment/alignment_pointer.json",
    "close_review_sources/{date}/bilibili/video_gap/video_gap_audit.json",
    "stage_latest/{date}/STAGE_0925.json",
    "stage_latest/{date}/STAGE_0930_0935.json",
    "stage_latest/{date}/STAGE_0935_0940.json",
    "stage_latest/{date}/STAGE_0940_0945.json",
    "stage_latest/{date}/STAGE_0945_1030.json",
    "stage_latest/{date}/STAGE_1300_1315.json",
    "stage_latest/{date}/STAGE_1445_1500.json",
)
_ALLOWED_FIELD_PREFIXES = (
    "business_date",
    "trade_date",
    "target_date",
    "signal_date",
    "review_date",
    "date",
    "node_id",
    "task_id",
    "status",
    "reason",
    "row_count",
    "coverage_rate",
    "source_receipt_path",
    "source_receipt_sha256",
    "selector_pointer_path",
    "selector_artifact_path",
    "selector_artifact_sha256",
    "backtest_pointer_path",
    "backtest_artifact_path",
    "backtest_artifact_sha256",
    "sync_authority_status",
    "producer_artifact_sha256",
    "close_review_path",
    "close_review_sha256",
    "close_review_receipt_path",
    "close_review_receipt_sha256",
    "evidence.",
    "production_allowed",
    "buy_gate_updated",
    "orders_sent",
    "pool_id",
    "source_role",
    "rows",
    "research_only",
    "stage.",
    "close_chain.",
    "model_review.",
    "mainlines",
    "selected_",
    "markets.",
    "materialized_snapshot.",
    "effective_status",
    "write_policy",
    "buy_gate_effect",
    "live_order_effect",
    "evidence_mode",
    "reference_snapshot",
    "close_top20",
    "model_rows",
    "stage_rows",
    "board_rows",
    "anchor_role_rows",
    "target_video_",
    "video_augmented_review_complete",
    "today_bv_status",
    "asr_status",
    "source_index",
    "locked_videos",
    "videos",
    "cookie_mode",
    "schema_version",
)


def _reject_text(value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True).replace("FUPAN_8771_VERIFY", "").lower()
    if any(token in text for token in _FORBIDDEN_TEXT):
        raise ValueError("V4_BINDING_LEGACY_DEPENDENCY")


def _validate_path(value: Any) -> str:
    if not isinstance(value, str) or not value or ".." in value or "\\" in value:
        raise ValueError("V4_BINDING_PATH_INVALID")
    if not value.startswith(_ALLOWED_PREFIXES):
        raise ValueError("V4_BINDING_PATH_INVALID")
    if os.path.isabs(value):
        raise ValueError("V4_BINDING_PATH_INVALID")
    relative = value[len("{data_root}/") :]
    if not any(fnmatch.fnmatchcase(relative, pattern) for pattern in _ALLOWED_RELATIVE_PATTERNS):
        raise ValueError("V4_BINDING_PATH_INVALID")
    return value


def _validate_fields(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("V4_BINDING_FIELDS_INVALID")
    result: dict[str, str] = {}
    for name, path in value.items():
        if not isinstance(name, str) or not name or not isinstance(path, str) or not path:
            raise ValueError("V4_BINDING_FIELDS_INVALID")
        if ".." in path or "[" in path or "]" in path:
            raise ValueError("V4_BINDING_FIELDS_INVALID")
        if not any(path.startswith(prefix) for prefix in _ALLOWED_FIELD_PREFIXES):
            raise ValueError("V4_BINDING_FIELDS_INVALID")
        result[name] = path
    return result


def _validate_api_probe(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("V4_BINDING_API_PROBES_INVALID")
    result: list[dict[str, Any]] = []
    for probe in value:
        if not isinstance(probe, Mapping) or set(probe) - _ALLOWED_API_PROBE_KEYS:
            raise ValueError("V4_BINDING_API_PROBE_INVALID")
        path = probe.get("path")
        # Historical contracts retain their original hash; normalize only the read view.
        if isinstance(path, str) and path.startswith("/api/v3/"):
            path = "/api/v4/" + path[len("/api/v3/"):]
        kind = probe.get("kind")
        date_role = probe.get("date_role", "business_date")
        if not isinstance(path, str) or not path or "{" not in path:
            raise ValueError("V4_BINDING_API_PROBE_INVALID")
        if path in _ALLOWED_API_PATHS:
            pass
        elif (
            path.startswith("/api/v4/workbench/stage?date={date}&stage=")
            and path.endswith("&limit=10")
            and path.count("stage=") == 1
        ):
            stage_id = path.split("stage=", 1)[1].split("&", 1)[0]
            if stage_id not in _ALLOWED_API_STAGE_IDS:
                raise ValueError("V4_BINDING_API_PROBE_INVALID")
        else:
            raise ValueError("V4_BINDING_API_PROBE_INVALID")
        if kind not in _ALLOWED_API_KINDS or date_role not in _ALLOWED_DATE_ROLES:
            raise ValueError("V4_BINDING_API_PROBE_INVALID")
        if kind == "workbench_stage":
            stage_id = probe.get("stage_id")
            if stage_id not in _ALLOWED_API_STAGE_IDS or f"stage={stage_id}&" not in path:
                raise ValueError("V4_BINDING_API_PROBE_INVALID")
            if date_role != "business_date":
                raise ValueError("V4_BINDING_API_PROBE_INVALID")
        elif kind == "preselection_pool":
            if probe.get("pool_id") not in _ALLOWED_API_POOL_IDS:
                raise ValueError("V4_BINDING_API_PROBE_INVALID")
            if path != "/api/v4/preselection-pools?date={target_date}&limit=200" or date_role != "target_date":
                raise ValueError("V4_BINDING_API_PROBE_INVALID")
        elif kind in {"review_close_chain", "review_model_selection"}:
            if path != "/api/v4/review?date={date}" or date_role != "business_date":
                raise ValueError("V4_BINDING_API_PROBE_INVALID")
        normalized = copy.deepcopy(dict(probe))
        normalized["path"] = path
        result.append(normalized)
    return result


def _validate_api_subject(node_id: str, probes: list[dict[str, Any]]) -> None:
    if node_id in {"FUPAN_CLOSE_MATERIALS", "FUPAN_REVIEW_START", "FUPAN_A_SHARE_STRUCTURE"}:
        if len(probes) != 1 or probes[0].get("kind") != "review_close_chain":
            raise ValueError("V4_BINDING_API_PROBE_INVALID")
        return
    if node_id == "hkconnect_model_selection_review":
        if len(probes) != 1 or probes[0].get("kind") != "review_model_selection":
            raise ValueError("V4_BINDING_API_PROBE_INVALID")
        return
    if node_id == "ashare_v193_slot_selector_premarket":
        if len(probes) != 1 or probes[0].get("kind") != "preselection_pool" or probes[0].get("pool_id") != "a_d1_premarket_pool":
            raise ValueError("V4_BINDING_API_PROBE_INVALID")
        return
    if node_id == "hkconnect_d1_top100_prob_active":
        if len(probes) != 1 or probes[0].get("kind") != "preselection_pool" or probes[0].get("pool_id") != "hkconnect_d1_top100":
            raise ValueError("V4_BINDING_API_PROBE_INVALID")
        return
    if node_id == "v3_opening_intraday_stage_select_0925_1500":
        if len(probes) != len(_ALLOWED_API_STAGE_IDS) or {probe.get("kind") for probe in probes} != {"workbench_stage"} or {
            probe.get("stage_id") for probe in probes
        } != _ALLOWED_API_STAGE_IDS:
            raise ValueError("V4_BINDING_API_PROBE_INVALID")
        return
    raise ValueError("V4_BINDING_API_PROBE_INVALID")


def _validate_source(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - _ALLOWED_SOURCE_KEYS:
        raise ValueError("V4_BINDING_SOURCE_INVALID")
    kind = value.get("kind")
    if kind not in _ALLOWED_KINDS:
        raise ValueError("V4_BINDING_SOURCE_INVALID")
    _validate_path(value.get("path"))
    if kind == "stage_latest" and (
        not isinstance(value.get("stage_id"), str) or value["stage_id"] not in {
            "STAGE_0925",
            "STAGE_0930_0935",
            "STAGE_0935_0940",
            "STAGE_0940_0945",
            "STAGE_0945_1030",
            "STAGE_1300_1315",
            "STAGE_1445_1500",
        }
    ):
        raise ValueError("V4_BINDING_SOURCE_INVALID")
    if "artifact_role" in value and value["artifact_role"] not in _ALLOWED_ARTIFACT_ROLES:
        raise ValueError("V4_BINDING_SOURCE_INVALID")
    if "receipt_role" in value and value["receipt_role"] not in _ALLOWED_RECEIPT_ROLES:
        raise ValueError("V4_BINDING_SOURCE_INVALID")
    if value.get("receipt_role") == "node_action" and kind != "v35_receipt":
        raise ValueError("V4_BINDING_SOURCE_INVALID")
    if kind != "v35_receipt":
        alias = value.get("semantic_alias")
        if not isinstance(alias, str) or not alias:
            raise ValueError("V4_BINDING_SOURCE_INVALID")
        fields = _validate_fields(value.get("semantic_fields"))
        if value.get("projection", "root") not in _ALLOWED_PROJECTIONS:
            raise ValueError("V4_BINDING_SOURCE_INVALID")
        if kind == "v35_artifact" and not isinstance(value.get("expected_schema"), str):
            raise ValueError("V4_BINDING_SOURCE_INVALID")
        if kind == "stage_latest" and "expected_schema" in value:
            raise ValueError("V4_BINDING_SOURCE_INVALID")
        if not fields:
            raise ValueError("V4_BINDING_SOURCE_INVALID")
    for name in ("receipt_path", "artifact_path", "manifest_path"):
        if name in value:
            _validate_path(value[name])
    if "manifest_key" in value and (
        not isinstance(value["manifest_key"], str)
        or value["manifest_key"] not in _ALLOWED_MANIFEST_KEYS
    ):
        raise ValueError("V4_BINDING_SOURCE_INVALID")
    if value.get("date_role", "business_date") not in _ALLOWED_DATE_ROLES:
        raise ValueError("V4_BINDING_SOURCE_INVALID")
    return copy.deepcopy(dict(value))


def _validate_binding(value: Any, expected_node_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - _ALLOWED_TOP_KEYS:
        raise ValueError("V4_BINDING_INVALID")
    if value.get("node_id") != expected_node_id or expected_node_id not in BOUND_NODE_IDS:
        raise ValueError("V4_BINDING_NODE_INVALID")
    if "semantic_validator" in value and value["semantic_validator"] not in _ALLOWED_SEMANTIC_VALIDATORS:
        raise ValueError("V4_BINDING_SEMANTIC_VALIDATOR_INVALID")
    outputs = value.get("expected_outputs")
    if not isinstance(outputs, list) or not outputs or not all(isinstance(item, str) for item in outputs):
        raise ValueError("V4_BINDING_OUTPUTS_INVALID")
    validated_outputs = [_validate_path(item) for item in outputs]
    sources = value.get("status_sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("V4_BINDING_SOURCES_INVALID")
    validated_sources = [_validate_source(source) for source in sources]
    if not any(source["kind"] == "v35_artifact" or source["kind"] == "stage_latest" for source in validated_sources):
        raise ValueError("V4_BINDING_ARTIFACT_SOURCE_MISSING")
    validated_api = _validate_api_probe(value["api_probe"]) if "api_probe" in value else None
    if validated_api is not None:
        _validate_api_subject(expected_node_id, validated_api)
    return {
        "node_id": expected_node_id,
        "expected_outputs": validated_outputs,
        "status_sources": validated_sources,
        **({"semantic_validator": value["semantic_validator"]} if "semantic_validator" in value else {}),
        **({"receipt_date_fields": copy.deepcopy(value["receipt_date_fields"])} if "receipt_date_fields" in value else {}),
        **({"api_probe": validated_api} if validated_api is not None else {}),
        **({"api_date_fields": copy.deepcopy(value["api_date_fields"])} if "api_date_fields" in value else {}),
    }


def load_v35_evidence_bindings(path: Path | None = None) -> dict[str, dict[str, Any]]:
    source = BINDINGS_PATH if path is None else Path(path)
    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("V4_BINDINGS_DUPLICATE_FIELD")
            result[key] = value
        return result
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"), object_pairs_hook=reject_duplicate_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("V4_BINDINGS_UNREADABLE") from error
    _reject_text(payload)
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "v3_5.runtime_graph_evidence_bindings.v1":
        raise ValueError("V4_BINDINGS_SCHEMA_INVALID")
    if set(payload) != {"schema_version", "node_ids", "bindings"}:
        raise ValueError("V4_BINDINGS_SCHEMA_INVALID")
    node_ids = payload.get("node_ids")
    if not isinstance(node_ids, list) or frozenset(node_ids) != BOUND_NODE_IDS or len(node_ids) != len(BOUND_NODE_IDS):
        raise ValueError("V4_BINDINGS_NODE_SET_INVALID")
    rows = payload.get("bindings")
    if not isinstance(rows, list) or len(rows) != len(BOUND_NODE_IDS):
        raise ValueError("V4_BINDINGS_ROWS_INVALID")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("V4_BINDING_INVALID")
        node_id = row.get("node_id")
        if node_id in result:
            raise ValueError("V4_BINDINGS_DUPLICATE")
        result[str(node_id)] = _validate_binding(row, str(node_id))
    if frozenset(result) != BOUND_NODE_IDS:
        raise ValueError("V4_BINDINGS_NODE_SET_INVALID")
    return result


def overlay_node_evidence(node: Mapping[str, Any], binding: Mapping[str, Any] | None) -> dict[str, Any]:
    """Clone a frozen descriptor and overlay evidence declarations only."""
    original = copy.deepcopy(dict(node))
    if binding is None:
        return original
    node_id = original.get("node_id")
    if node_id not in BOUND_NODE_IDS or binding.get("node_id") != node_id:
        raise ValueError("V4_BINDING_NODE_INVALID")
    checked = _validate_binding(binding, str(node_id))
    for key in checked:
        if key == "node_id":
            continue
        original[key] = copy.deepcopy(checked[key])
    return original


__all__ = ["BINDINGS_PATH", "BOUND_NODE_IDS", "load_v35_evidence_bindings", "overlay_node_evidence"]
