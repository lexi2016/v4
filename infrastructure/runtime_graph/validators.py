"""Declared, source-aliased semantic checks for runtime graph artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from math import isfinite
from typing import Any

from .contracts import EvidenceLayer, EvidenceResult, GraphStatus
from .v4_validators import validate_v4_semantics


_PROFILE_ALIASES = {
    "v3_stage0925_visible_verify_0927": {"stage_visibility_status"},
    "v3_stage0925_visible_verify_0929": {"stage_visibility_status"},
    "v3_opening_intraday_stage_select_0925_1500": {"stage_workbench_snapshot"},
    "ashare_v193_slot_selector_premarket": {"a_selector_manifest", "a_selector_latest"},
    "hkconnect_d1_top100_prob_active": {"hk_d1_manifest", "hk_d1_latest"},
    "tomorrow_pool_2005": {"tomorrow_pool_status"},
    "hourly_research_delta": {"research_event"},
    "v3_hourly_research_delta_0730_1530": {"research_event"},
    "v3_zsxq_research_0830": {"zsxq_status"},
    "baimao_x_refresh": {"baimao_digest"},
    "FUPAN_V3_PUBLISH": {"fupan_review_v3", "fupan_publish_v35"},
    "FUPAN_8771_VERIFY": {"fupan_page_verify_receipt_v35"},
    "FUPAN_CLOSE_MATERIALS": {"fupan_close_chain_v35"},
    "FUPAN_REVIEW_START": {"fupan_close_chain_v35"},
    "FUPAN_A_SHARE_STRUCTURE": {"fupan_close_chain_v35"},
    "ashare_v193_slot_selector_premarket": {"a_selector_v35"},
    "hkconnect_d1_top100_prob_active": {"hk_d1_v35"},
    "v3_opening_intraday_stage_select_0925_1500": {"stage_latest_v35"},
    "hkconnect_model_selection_review": {"close_review_v35"},
}
_PROFILE_KINDS = {
    "v3_stage0925_visible_verify_0927": "stage",
    "v3_stage0925_visible_verify_0929": "stage",
    "v3_opening_intraday_stage_select_0925_1500": "stage",
    "ashare_v193_slot_selector_premarket": "pool",
    "hkconnect_d1_top100_prob_active": "pool",
    "tomorrow_pool_2005": "pool",
    "hourly_research_delta": "research",
    "v3_hourly_research_delta_0730_1530": "research",
    "v3_zsxq_research_0830": "research",
    "baimao_x_refresh": "research",
    "FUPAN_V3_PUBLISH": "review",
    "FUPAN_8771_VERIFY": "review",
    "FUPAN_CLOSE_MATERIALS": "review",
    "FUPAN_REVIEW_START": "review",
    "FUPAN_A_SHARE_STRUCTURE": "review",
    "ashare_v193_slot_selector_premarket": "pool",
    "hkconnect_d1_top100_prob_active": "pool",
    "v3_opening_intraday_stage_select_0925_1500": "stage",
    "hkconnect_model_selection_review": "review",
}
_STAGE_IDENTITIES = {
    "v3_stage0925_visible_verify_0927": "STAGE_0925",
    "v3_stage0925_visible_verify_0929": "STAGE_0925",
}
_STAGE_WORKBENCH_IDENTITIES = frozenset(
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
_SUCCESS = frozenset({"PASS", "READY", "SUCCESS", "COMPLETED", "STRICT_0_2_READY", "PASS_TOMORROW_POOL_READY", "USER_VISIBLE_STAGE_READY"})
_FATAL_TOKENS = ("FAIL", "ERROR", "FATAL", "ABORT", "CANCEL", "MISMATCH")


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_safe(item) for item in value]
    return str(value)


def _records(evidence: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    raw_sources = evidence.get("sources")
    if isinstance(raw_sources, Sequence) and not isinstance(raw_sources, str | bytes | bytearray):
        for source in raw_sources:
            if not isinstance(source, Mapping):
                continue
            alias = source.get("semantic_alias")
            fields = source.get("semantic_fields")
            if isinstance(alias, str) and isinstance(fields, Mapping):
                sources.append({"semantic_alias": alias, "semantic_fields": _safe(fields)})
    details = {
        "outputs": _safe(evidence.get("outputs") if isinstance(evidence.get("outputs"), Sequence) else []),
        "sources": sources,
        "receipts": _safe(evidence.get("receipts") if isinstance(evidence.get("receipts"), Sequence) else []),
    }
    return sources, details


def _result(status: GraphStatus, reason: str, details: dict[str, Any]) -> EvidenceResult:
    return EvidenceResult(EvidenceLayer.ARTIFACT, status, reason, details)


def _status(fields: Mapping[str, Any]) -> str:
    return str(fields.get("effective_status") or fields.get("latest_status") or fields.get("status") or "").upper()


def _fatal(fields: Mapping[str, Any]) -> bool:
    return any(token in _status(fields) for token in _FATAL_TOKENS)


def _date(fields: Mapping[str, Any], business_date: str, names: tuple[str, ...]) -> GraphStatus:
    present = [fields[name] for name in names if name in fields]
    if any(str(value) != business_date for value in present):
        return GraphStatus.FAIL
    return GraphStatus.PASS if present else GraphStatus.EVIDENCE_GAP


def _nonnegative(value: Any, *, positive: bool = False) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= (1 if positive else 0)


def _stage(fields: Mapping[str, Any], business_date: str, expected_stage_id: str) -> GraphStatus:
    if _fatal(fields) or _date(fields, business_date, ("trade_date",)) is GraphStatus.FAIL:
        return GraphStatus.FAIL
    if _date(fields, business_date, ("trade_date",)) is not GraphStatus.PASS:
        return GraphStatus.EVIDENCE_GAP
    stage_id = fields.get("stage_id")
    if stage_id != expected_stage_id:
        return GraphStatus.FAIL if isinstance(stage_id, str) and stage_id else GraphStatus.EVIDENCE_GAP
    if fields.get("production_allowed") is True or fields.get("buy_gate_effect") not in (None, "none") or fields.get("live_order_effect") not in (None, "none"):
        return GraphStatus.FAIL
    if fields.get("production_allowed") is not False or fields.get("buy_gate_effect") != "none" or fields.get("live_order_effect") != "none":
        return GraphStatus.EVIDENCE_GAP
    if _status(fields) not in _SUCCESS:
        return GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS if all(_nonnegative(fields.get(name)) for name in ("selected_a_rows", "selected_hk_rows")) else GraphStatus.EVIDENCE_GAP


def _stage_workbench(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    date = _date(fields, business_date, ("trade_date",))
    if _fatal(fields) or date is GraphStatus.FAIL:
        return GraphStatus.FAIL
    if date is not GraphStatus.PASS:
        return GraphStatus.EVIDENCE_GAP
    stage_id = fields.get("stage_id")
    if stage_id not in _STAGE_WORKBENCH_IDENTITIES:
        return GraphStatus.FAIL if isinstance(stage_id, str) and stage_id else GraphStatus.EVIDENCE_GAP
    if (
        fields.get("write_policy") not in (None, "scheduled_stage_snapshot_only")
        or fields.get("buy_gate_effect") not in (None, "none")
        or fields.get("live_order_effect") not in (None, "none")
    ):
        return GraphStatus.FAIL
    if (
        fields.get("write_policy") != "scheduled_stage_snapshot_only"
        or fields.get("buy_gate_effect") != "none"
        or fields.get("live_order_effect") != "none"
    ):
        return GraphStatus.EVIDENCE_GAP
    count_names = (
        "selected_a_rows",
        "selected_hk_rows",
        "selected_total_rows",
        "a_source_rows",
        "hk_source_rows",
        "a_candidate_count",
        "hk_candidate_count",
    )
    if not all(_nonnegative(fields.get(name)) for name in count_names):
        return GraphStatus.EVIDENCE_GAP
    selected_a = int(fields["selected_a_rows"])
    selected_hk = int(fields["selected_hk_rows"])
    if (
        selected_a != fields["a_candidate_count"]
        or selected_hk != fields["hk_candidate_count"]
        or selected_a + selected_hk != fields["selected_total_rows"]
        or selected_a > fields["a_source_rows"]
        or selected_hk > fields["hk_source_rows"]
    ):
        return GraphStatus.FAIL
    status = _status(fields)
    if not status:
        return GraphStatus.EVIDENCE_GAP
    if "NO_SOURCE_ROWS" in status and (
        fields["a_source_rows"] > 0 or fields["hk_source_rows"] > 0
    ):
        return GraphStatus.FAIL
    return GraphStatus.PASS


def _valid_yyyymmdd(value: Any) -> bool:
    try:
        return isinstance(value, str) and bool(datetime.strptime(value, "%Y%m%d"))
    except ValueError:
        return False


def _a_selector(fields: Mapping[str, Any], business_date: str, alias: str) -> GraphStatus:
    date_names = ("trade_date", "target_date") if alias == "a_selector_manifest" else ("latest_trade_date", "target_date", "trade_date")
    date = _date(fields, business_date, date_names)
    if fields.get("production_allowed") is True:
        return GraphStatus.FAIL
    if date is GraphStatus.FAIL:
        if alias == "a_selector_manifest":
            return GraphStatus.FAIL
        values = {str(fields[name]) for name in date_names if name in fields}
        if (
            len(values) != 1
            or not all(_valid_yyyymmdd(value) for value in values)
            or any(value > business_date for value in values)
        ):
            return GraphStatus.FAIL
        return GraphStatus.EVIDENCE_GAP
    signal_date = fields.get("signal_date")
    if signal_date is not None and not _valid_yyyymmdd(signal_date):
        return GraphStatus.FAIL
    if date is not GraphStatus.PASS or fields.get("research_only") is not True or fields.get("production_allowed") is not False:
        return GraphStatus.EVIDENCE_GAP
    count = next((fields[name] for name in ("row_count", "runtime_row_count") if name in fields), None)
    if not _nonnegative(count, positive=True):
        return GraphStatus.EVIDENCE_GAP
    pool_id = fields.get("pool_id")
    if pool_id != "ashare_v193_slot_selector_premarket":
        return GraphStatus.FAIL if isinstance(pool_id, str) and pool_id else GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS


def _hk_d1_manifest(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    date = _date(fields, business_date, ("target_date",))
    if date is GraphStatus.FAIL or _fatal(fields) or fields.get("production_allowed") is True or fields.get("buy_gate_changed") is True or fields.get("orders_sent") is True:
        return GraphStatus.FAIL
    if date is not GraphStatus.PASS or fields.get("strict_exact_0_2_ready") is not True:
        return GraphStatus.EVIDENCE_GAP
    if fields.get("research_only") is not True or fields.get("production_allowed") is not False or fields.get("buy_gate_changed") is not False or fields.get("orders_sent") is not False or not _nonnegative(fields.get("row_count"), positive=True):
        return GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS if _status(fields) in _SUCCESS else GraphStatus.EVIDENCE_GAP


def _hk_d1_latest(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    latest_target_date = fields.get("latest_target_date")
    if (
        not isinstance(latest_target_date, str)
        or not _valid_yyyymmdd(latest_target_date)
        or _fatal(fields)
        or fields.get("production_allowed") is True
    ):
        return GraphStatus.FAIL
    if latest_target_date < business_date:
        return GraphStatus.EVIDENCE_GAP
    if latest_target_date > business_date:
        signal_date = fields.get("signal_date")
        if signal_date is None:
            return GraphStatus.EVIDENCE_GAP
        if signal_date != business_date:
            return GraphStatus.FAIL
    if fields.get("strict_exact_0_2_ready") is not True:
        return GraphStatus.EVIDENCE_GAP
    if fields.get("research_only") is not True or fields.get("production_allowed") is not False:
        return GraphStatus.EVIDENCE_GAP
    if fields.get("d1_freshness_status") != "PASS" or fields.get("d1_freshness_ok") is not True:
        return GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS if _status(fields) in _SUCCESS else GraphStatus.EVIDENCE_GAP


def _tomorrow(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    if "business_exit_code" not in fields:
        return GraphStatus.EVIDENCE_GAP
    exit_code = fields.get("business_exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code != 0:
        return GraphStatus.FAIL
    if _fatal(fields):
        return GraphStatus.FAIL
    if _fatal({"status": fields.get("hk_d1_status")}):
        return GraphStatus.FAIL
    target = fields.get("target_date")
    try:
        target_valid = bool(
            isinstance(target, str)
            and datetime.strptime(target, "%Y%m%d")
        )
    except ValueError:
        target_valid = False
    signal = fields.get("signal_date")
    if signal is not None and not _valid_yyyymmdd(signal):
        return GraphStatus.FAIL
    if not target_valid:
        return GraphStatus.EVIDENCE_GAP
    if target <= business_date:
        return GraphStatus.EVIDENCE_GAP
    if signal != business_date:
        return GraphStatus.FAIL
    required = ("signal_date", "target_date", "formal_row_count", "premarket_row_count", "hk_d1_row_count", "hk_d1_status", "business_exit_code", "status", "registry_ok", "hkconnect_d1_ok", "hk_d1_freshness_status", "hk_d1_freshness_ok", "strict_exact_0_2_ready")
    if any(name not in fields for name in required):
        return GraphStatus.EVIDENCE_GAP
    if fields.get("status") != "PASS_TOMORROW_POOL_READY" or fields.get("registry_ok") is not True or fields.get("hkconnect_d1_ok") is not True or fields.get("hk_d1_freshness_status") != "PASS" or fields.get("hk_d1_freshness_ok") is not True or fields.get("strict_exact_0_2_ready") is not True:
        return GraphStatus.FAIL
    if not _nonnegative(fields.get("formal_row_count"), positive=True) or not _nonnegative(fields.get("premarket_row_count"), positive=True) or fields.get("hk_d1_row_count") != 100:
        return GraphStatus.FAIL
    return GraphStatus.PASS if _status({"status": fields.get("hk_d1_status")}) == "STRICT_0_2_READY" else GraphStatus.FAIL


def _research(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    if _date(fields, business_date, ("trade_date",)) is GraphStatus.FAIL:
        return GraphStatus.FAIL
    required = ("trade_date", "event_id", "event_reason", "write_policy", "default_status", "buy_gate_effect", "live_order_effect")
    if any(name not in fields for name in required):
        return GraphStatus.EVIDENCE_GAP
    if fields.get("write_policy") != "read_only" or fields.get("default_status") != "RESEARCH_ONLY":
        return GraphStatus.FAIL
    if fields.get("buy_gate_effect") != "none" or fields.get("live_order_effect") != "none":
        return GraphStatus.FAIL
    if not isinstance(fields.get("event_id"), str) or not fields["event_id"] or not isinstance(fields.get("event_reason"), str) or not fields["event_reason"]:
        return GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS


def _zsxq(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    date = _date(fields, business_date, ("trade_date",))
    if date is GraphStatus.FAIL or fields.get("fetch_ok") is False:
        return GraphStatus.FAIL
    if (
        date is not GraphStatus.PASS
        or fields.get("fetch_ok") is not True
        or fields.get("status") not in {"READY", "READY_EMPTY"}
        or not _nonnegative(fields.get("topic_count"))
        or fields.get("production_allowed") is not False
        or fields.get("buy_gate_updated") is not False
        or fields.get("orders_sent") is not False
    ):
        return GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS


def _baimao(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    date = _date(fields, business_date, ("business_date", "trade_date"))
    if date is GraphStatus.FAIL or fields.get("ok") is False:
        return GraphStatus.FAIL
    if (
        date is not GraphStatus.PASS
        or fields.get("ok") is not True
        or fields.get("status") != "REFRESHED_FROM_MIRRORS"
        or fields.get("production_allowed") is not False
        or fields.get("buy_gate_updated") is not False
        or fields.get("orders_sent") is not False
    ):
        return GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS


def _fupan_review(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    date = _date(fields, business_date, ("review_date",))
    if date is GraphStatus.FAIL:
        return GraphStatus.FAIL
    if date is not GraphStatus.PASS:
        return GraphStatus.EVIDENCE_GAP
    if (
        fields.get("buy_gate_allowed") is True
        or fields.get("trading_advice_allowed") is True
        or fields.get("no_buy_gate") is False
    ):
        return GraphStatus.FAIL
    if (
        fields.get("buy_gate_allowed") is not False
        or fields.get("trading_advice_allowed") is not False
        or fields.get("no_buy_gate") is not True
    ):
        return GraphStatus.EVIDENCE_GAP
    boards = fields.get("board_rows")
    anchors = fields.get("anchor_role_rows")
    if (
        not isinstance(boards, Sequence)
        or isinstance(boards, str | bytes | bytearray)
        or not boards
        or not isinstance(anchors, Sequence)
        or isinstance(anchors, str | bytes | bytearray)
        or not anchors
    ):
        return GraphStatus.FAIL
    status = fields.get("status")
    video_status = fields.get("target_video_review_status")
    evidence_count = fields.get("target_video_evidence_count")
    video_complete = fields.get("video_augmented_review_complete")
    if status == "INDEPENDENT_CLOSE_REVIEW_READY":
        if (
            video_status != "CANNOT_CONFIRM_TARGET_VIDEO_NOT_CONSUMED"
            or evidence_count != 0
            or video_complete is not False
        ):
            return GraphStatus.FAIL
        return GraphStatus.EVIDENCE_GAP
    if status == "VIDEO_AUGMENTED_REVIEW_READY":
        if (
            video_status != "TARGET_VIDEO_EVIDENCE_CONSUMED"
            or not _nonnegative(evidence_count, positive=True)
            or video_complete is not True
        ):
            return GraphStatus.FAIL
        return GraphStatus.PASS
    return GraphStatus.FAIL if isinstance(status, str) and status else GraphStatus.EVIDENCE_GAP


def validate_semantics(kind: str, evidence: Mapping[str, Any], business_date: str, *, node_id: str, target_date: str | None = None) -> EvidenceResult:
    """Validate only the profile explicitly declared for this exact node/source alias."""
    sources, details = _records(evidence)
    aliases = _PROFILE_ALIASES.get(node_id)
    if not aliases or _PROFILE_KINDS[node_id] != kind:
        return _result(GraphStatus.EVIDENCE_GAP, "SEMANTIC_ALIAS_UNDECLARED", details)
    if not sources or any(source["semantic_alias"] not in aliases for source in sources):
        return _result(GraphStatus.EVIDENCE_GAP, "SEMANTIC_ALIAS_UNDECLARED", details)
    validators = {
        "stage_visibility_status": lambda fields, date: _stage(fields, date, _STAGE_IDENTITIES[node_id]),
        "stage_workbench_snapshot": _stage_workbench,
        "a_selector_manifest": lambda fields, date: _a_selector(fields, date, "a_selector_manifest"),
        "a_selector_latest": lambda fields, date: _a_selector(fields, date, "a_selector_latest"),
        "hk_d1_manifest": _hk_d1_manifest,
        "hk_d1_latest": _hk_d1_latest,
        "tomorrow_pool_status": _tomorrow,
        "research_event": _research,
        "zsxq_status": _zsxq,
        "baimao_digest": _baimao,
        "fupan_review_v3": _fupan_review,
        "fupan_close_chain_v35": lambda fields, date: validate_v4_semantics("fupan_close_chain_v35", fields, date, node_id=node_id, target_date=target_date),
        "fupan_publish_v35": lambda fields, date: validate_v4_semantics("fupan_publish_v35", fields, date, node_id=node_id, target_date=target_date),
        "fupan_page_verify_receipt_v35": lambda fields, date: validate_v4_semantics("fupan_page_verify_receipt_v35", fields, date, node_id=node_id, target_date=target_date),
        "fupan_model_review_v35": lambda fields, date: validate_v4_semantics("fupan_model_review_v35", fields, date, node_id=node_id, target_date=target_date),
        "a_selector_v35": lambda fields, date: validate_v4_semantics("a_selector_v35", fields, date, node_id=node_id, target_date=target_date),
        "hk_d1_v35": lambda fields, date: validate_v4_semantics("hk_d1_v35", fields, date, node_id=node_id, target_date=target_date),
        "stage_latest_v35": lambda fields, date: validate_v4_semantics("stage_latest_v35", fields, date, node_id=node_id, target_date=target_date),
        "close_review_v35": lambda fields, date: validate_v4_semantics("close_review_v35", fields, date, node_id=node_id, target_date=target_date),
    }
    states = [validators[source["semantic_alias"]](source["semantic_fields"], business_date) for source in sources]
    if GraphStatus.FAIL in states:
        return _result(GraphStatus.FAIL, "SEMANTIC_CONTRADICTION", details)
    if all(state is GraphStatus.PASS for state in states):
        return _result(GraphStatus.PASS, "SEMANTIC_PASS", details)
    return _result(GraphStatus.EVIDENCE_GAP, "SEMANTIC_FIELDS_UNPROVEN", details)
