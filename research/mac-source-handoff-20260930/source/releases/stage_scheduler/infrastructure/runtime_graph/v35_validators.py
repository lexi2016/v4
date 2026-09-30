"""V3.5-native semantic validators for the evidence-binding overlay."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import GraphStatus


_STAGE_IDS = frozenset(
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
_SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")


def _generic_validators() -> Any:
    from . import validators

    return validators


def _safe_flags(fields: Mapping[str, Any]) -> GraphStatus:
    values = [fields.get(name) for name in _SAFETY_FLAGS]
    if any(value is True for value in values):
        return GraphStatus.FAIL
    return GraphStatus.PASS if all(value is False for value in values) else GraphStatus.EVIDENCE_GAP


def _fupan_chain(fields: Mapping[str, Any], business_date: str, node_id: str) -> GraphStatus:
    generic = _generic_validators()
    date = generic._date(fields, business_date, ("business_date", "trade_date"))
    if date is GraphStatus.FAIL or _safe_flags(fields) is GraphStatus.FAIL:
        return GraphStatus.FAIL
    if date is not GraphStatus.PASS or _safe_flags(fields) is not GraphStatus.PASS:
        return GraphStatus.EVIDENCE_GAP
    if fields.get("task_id") != node_id or fields.get("status") != "READY":
        return GraphStatus.FAIL if fields.get("task_id") or fields.get("status") else GraphStatus.EVIDENCE_GAP
    if not isinstance(fields.get("reason"), str) or not fields["reason"]:
        return GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS if generic._nonnegative(fields.get("row_count"), positive=True) else GraphStatus.EVIDENCE_GAP


def _fupan_model_review(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    generic = _generic_validators()
    date = generic._date(fields, business_date, ("review_date",))
    flags = _safe_flags(fields)
    if date is GraphStatus.FAIL or flags is GraphStatus.FAIL:
        return GraphStatus.FAIL
    if date is not GraphStatus.PASS or flags is not GraphStatus.PASS:
        return GraphStatus.EVIDENCE_GAP
    if fields.get("status") != "INDEPENDENT_CLOSE_REVIEW_READY":
        return GraphStatus.FAIL if fields.get("status") else GraphStatus.EVIDENCE_GAP
    if not isinstance(fields.get("board_rows"), Sequence) or isinstance(fields.get("board_rows"), str) or not fields["board_rows"]:
        return GraphStatus.EVIDENCE_GAP
    if not isinstance(fields.get("anchor_role_rows"), Sequence) or isinstance(fields.get("anchor_role_rows"), str) or not fields["anchor_role_rows"]:
        return GraphStatus.EVIDENCE_GAP
    if fields.get("target_video_review_status") != "CANNOT_CONFIRM_TARGET_VIDEO_NOT_CONSUMED" or fields.get("target_video_evidence_count") != 0 or fields.get("video_augmented_review_complete") is not False:
        return GraphStatus.FAIL
    return GraphStatus.PASS


def _pool(
    fields: Mapping[str, Any],
    business_date: str,
    target_date: str | None,
    *,
    pool_id: str,
    status: str,
    source_role: str,
    required_rows: int,
) -> GraphStatus:
    target = target_date or business_date
    generic = _generic_validators()
    if _safe_flags(fields) is GraphStatus.FAIL:
        return GraphStatus.FAIL
    if any(fields.get(name) != target for name in ("trade_date", "target_date")) or fields.get("signal_date") != business_date:
        return GraphStatus.FAIL
    if _safe_flags(fields) is not GraphStatus.PASS or fields.get("pool_id") != pool_id or fields.get("status") != status or fields.get("source_role") != source_role:
        return GraphStatus.EVIDENCE_GAP if fields.get("pool_id") == pool_id else GraphStatus.FAIL
    rows = fields.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, str) or len(rows) < required_rows:
        return GraphStatus.EVIDENCE_GAP
    for row in rows:
        if not isinstance(row, Mapping):
            return GraphStatus.FAIL
        if any(row.get(name) is True for name in _SAFETY_FLAGS):
            return GraphStatus.FAIL
        if row.get("signal_date") is not None and row.get("signal_date") != business_date:
            return GraphStatus.FAIL
        if row.get("target_date") is not None and row.get("target_date") != target:
            return GraphStatus.FAIL
        if row.get("trade_date") is not None and row.get("trade_date") not in {business_date, target}:
            return GraphStatus.FAIL
    return GraphStatus.PASS


def _stage(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    generic = _generic_validators()
    date = generic._date(fields, business_date, ("trade_date",))
    flags = _safe_flags(fields)
    if date is GraphStatus.FAIL or flags is GraphStatus.FAIL:
        return GraphStatus.FAIL
    if date is not GraphStatus.PASS or flags is not GraphStatus.PASS:
        return GraphStatus.EVIDENCE_GAP
    if fields.get("stage_id") not in _STAGE_IDS:
        return GraphStatus.FAIL if fields.get("stage_id") else GraphStatus.EVIDENCE_GAP
    if fields.get("write_policy") not in {"native_stage_snapshot_only", "scheduled_stage_snapshot_only"} or fields.get("buy_gate_effect") != "none" or fields.get("live_order_effect") != "none":
        return GraphStatus.FAIL
    names = ("selected_a_rows", "selected_hk_rows", "selected_total_rows", "a_source_rows", "hk_source_rows", "a_candidate_count", "hk_candidate_count")
    if not all(generic._nonnegative(fields.get(name)) for name in names):
        return GraphStatus.EVIDENCE_GAP
    if fields["selected_a_rows"] != fields["a_candidate_count"] or fields["selected_hk_rows"] != fields["hk_candidate_count"] or fields["selected_total_rows"] != fields["selected_a_rows"] + fields["selected_hk_rows"]:
        return GraphStatus.FAIL
    return GraphStatus.PASS if generic._status(fields) else GraphStatus.EVIDENCE_GAP


def _close_review(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    generic = _generic_validators()
    date = generic._date(fields, business_date, ("trade_date",))
    flags = _safe_flags(fields)
    if date is GraphStatus.FAIL or flags is GraphStatus.FAIL:
        return GraphStatus.FAIL
    if date is not GraphStatus.PASS or flags is not GraphStatus.PASS:
        return GraphStatus.EVIDENCE_GAP
    if fields.get("status") != "MODEL_REVIEW_READY" or fields.get("write_policy") != "review_only_read_only" or fields.get("evidence_mode") != "V3_5_NATIVE_PRODUCTION" or fields.get("reference_snapshot") is not False:
        return GraphStatus.FAIL
    for name in ("close_top20", "model_rows", "stage_rows"):
        if not isinstance(fields.get(name), Sequence) or isinstance(fields.get(name), str) or not fields[name]:
            return GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS


def _publish(fields: Mapping[str, Any], business_date: str) -> GraphStatus:
    """Validate the native review artifact that the publish node materializes.

    The close chain is intentionally allowed to remain ``PARTIAL_REVIEW``:
    the video branch can be legitimately CANNOT_CONFIRM while the native
    close/model review and mainlines are already materialized.  The first
    three deterministic close nodes are the non-video publication boundary.
    """
    generic = _generic_validators()
    date = generic._date(fields, business_date, ("trade_date",))
    flags = _safe_flags(fields)
    if date is GraphStatus.FAIL or flags is GraphStatus.FAIL:
        return GraphStatus.FAIL
    if date is not GraphStatus.PASS or flags is not GraphStatus.PASS:
        return GraphStatus.EVIDENCE_GAP
    if fields.get("schema_version") != "v3_5.a_share_review.v1":
        return GraphStatus.FAIL if fields.get("schema_version") else GraphStatus.EVIDENCE_GAP
    if fields.get("source_role") != "V3_5_NATIVE_CLOSE_MODEL":
        return GraphStatus.FAIL if fields.get("source_role") else GraphStatus.EVIDENCE_GAP
    if fields.get("write_policy") != "review_only_read_only":
        return GraphStatus.FAIL if fields.get("write_policy") else GraphStatus.EVIDENCE_GAP
    close_status = fields.get("close_chain_status")
    if close_status not in {"PARTIAL_REVIEW", "READY"}:
        return GraphStatus.FAIL if close_status else GraphStatus.EVIDENCE_GAP
    nodes = fields.get("close_chain_nodes")
    if not isinstance(nodes, Sequence) or isinstance(nodes, str) or len(nodes) < 3:
        return GraphStatus.EVIDENCE_GAP
    expected = ("FUPAN_CLOSE_MATERIALS", "FUPAN_REVIEW_START", "FUPAN_A_SHARE_STRUCTURE")
    for row, task_id in zip(nodes[:3], expected):
        if not isinstance(row, Mapping):
            return GraphStatus.FAIL
        if row.get("task_id") != task_id or row.get("business_date") != business_date or row.get("status") != "READY":
            return GraphStatus.FAIL
    model_status = fields.get("model_review_status")
    if model_status not in {"INDEPENDENT_CLOSE_REVIEW_READY", "VIDEO_AUGMENTED_REVIEW_READY"}:
        return GraphStatus.FAIL if model_status else GraphStatus.EVIDENCE_GAP
    mainlines = fields.get("mainlines")
    if not isinstance(mainlines, Sequence) or isinstance(mainlines, str) or not mainlines:
        return GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS


def _page_verify_receipt(fields: Mapping[str, Any], business_date: str, *, node_id: str) -> GraphStatus:
    """Validate the single native loopback verification receipt only."""
    generic = _generic_validators()
    date = generic._date(fields, business_date, ("trade_date", "business_date", "date"))
    flags = _safe_flags(fields)
    if date is GraphStatus.FAIL or flags is GraphStatus.FAIL:
        return GraphStatus.FAIL
    if date is not GraphStatus.PASS or flags is not GraphStatus.PASS:
        return GraphStatus.EVIDENCE_GAP
    if node_id != "FUPAN_8771_VERIFY":
        return GraphStatus.FAIL
    if fields.get("node_id") != node_id:
        return GraphStatus.FAIL if fields.get("node_id") else GraphStatus.EVIDENCE_GAP
    if fields.get("status") != "SUCCESS":
        return GraphStatus.FAIL if fields.get("status") else GraphStatus.EVIDENCE_GAP
    if fields.get("reason") != "HTTP_200_CONFIRMED":
        return GraphStatus.FAIL if fields.get("reason") else GraphStatus.EVIDENCE_GAP
    return GraphStatus.PASS


def validate_v35_semantics(
    alias: str,
    fields: Mapping[str, Any],
    business_date: str,
    *,
    node_id: str,
    target_date: str | None = None,
) -> GraphStatus:
    if alias == "fupan_close_chain_v35":
        return _fupan_chain(fields, business_date, node_id)
    if alias == "fupan_model_review_v35":
        return _fupan_model_review(fields, business_date)
    if alias == "a_selector_v35":
        return _pool(fields, business_date, target_date, pool_id="a_d1_premarket_pool", status="V192_CANDIDATE_READY", source_role="SHARED_VERIFIED_V192", required_rows=1)
    if alias == "hk_d1_v35":
        return _pool(fields, business_date, target_date, pool_id="hkconnect_d1_top100", status="STRICT_0_2_READY", source_role="SHARED_VERIFIED_HK_0_2", required_rows=100)
    if alias == "stage_latest_v35":
        return _stage(fields, business_date)
    if alias == "close_review_v35":
        return _close_review(fields, business_date)
    if alias == "fupan_publish_v35":
        return _publish(fields, business_date)
    if alias == "fupan_page_verify_receipt_v35":
        return _page_verify_receipt(fields, business_date, node_id=node_id)
    raise ValueError("V35_SEMANTIC_ALIAS_UNDECLARED")
