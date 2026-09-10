"""V3-ordered close-review task state derived from exact-date evidence."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from infrastructure.data_store import _date


CHAIN_TASKS = (
    ("FUPAN_CLOSE_MATERIALS", "15:00", "收盘前总结材料"),
    ("FUPAN_REVIEW_START", "15:55", "收盘后复盘启动"),
    ("FUPAN_A_SHARE_STRUCTURE", "16:05", "A股收盘数据与题材骨架"),
    ("FUPAN_VIDEO_CHECK", "20:30", "最新复盘视频检查"),
    ("FUPAN_VIDEO_DOWNLOAD_ASR", "20:40", "视频下载与转写"),
    ("FUPAN_STOCKDICT", "20:50", "股票字典校正"),
    ("FUPAN_VIDEO_TABLE_OCR_ALIGN", "21:05", "视频表格OCR/ASR/新闻对齐"),
    ("FUPAN_VIDEO_GAP", "21:08", "页面复盘对视频差距"),
    ("FUPAN_V3_PUBLISH", "21:10", "第三版复盘发布"),
    ("FUPAN_8771_VERIFY", "21:15", "页面与接口验收"),
)


def _node(
    task_id: str,
    slot: str,
    label: str,
    trade_date: str,
    status: str,
    reason: str,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "slot": slot,
        "label": label,
        "business_date": trade_date,
        "status": status,
        "reason": reason,
        "evidence": deepcopy(evidence or []),
    }


def _video_state(
    trade_date: str,
    video_acceptance: Mapping[str, Any] | None,
    video_capture: Mapping[str, Any] | None,
) -> tuple[str, str, list[dict[str, Any]], str, str]:
    if video_acceptance is None:
        return (
            "NOT_MATERIALIZED",
            "SAME_DAY_VIDEO_NOT_LOCKED",
            [],
            "NOT_MATERIALIZED",
            "DEPENDENCY_FUPAN_VIDEO_CHECK_NOT_MATERIALIZED",
        )
    if not isinstance(video_acceptance, Mapping):
        raise ValueError("video acceptance must be an object")
    if _date(str(video_acceptance.get("trade_date") or "")) != trade_date:
        raise ValueError("video acceptance date does not match close-review date")
    checks = video_acceptance.get("checks")
    if not isinstance(checks, Mapping):
        raise ValueError("video acceptance checks are missing")
    same_day = int(checks.get("same_day_video_count") or 0)
    today_status = str(video_acceptance.get("today_bv_status") or "")
    evidence = [{
        "source_id": "bilibili_fupan_acceptance",
        "trade_date": trade_date,
        "status": str(video_acceptance.get("status") or "CANNOT_CONFIRM"),
        "today_bv_status": today_status,
        "same_day_video_count": same_day,
        "asr_status": str(video_acceptance.get("asr_status") or "NOT_USED"),
    }]
    if today_status != "TODAY_BV_LOCKED" or same_day <= 0:
        return (
            "NOT_MATERIALIZED",
            "SAME_DAY_VIDEO_NOT_LOCKED",
            evidence,
            "NOT_MATERIALIZED",
            "DEPENDENCY_FUPAN_VIDEO_CHECK_NOT_MATERIALIZED",
        )
    if video_capture is not None:
        if not isinstance(video_capture, Mapping) or video_capture.get("trade_date") != trade_date:
            raise ValueError("video capture date does not match close-review date")
        asr_status = str(video_capture.get("status") or "")
        evidence.append({
            "source_id": "bilibili_capture_manifest",
            "trade_date": trade_date,
            "status": asr_status,
            "video_count": len(video_capture.get("videos") or []),
        })
    else:
        asr_status = str(video_acceptance.get("asr_status") or "")
    if asr_status == "ASR_READY":
        return (
            "READY",
            "SAME_DAY_VIDEO_LOCKED",
            evidence,
            "READY",
            "SAME_DAY_ASR_READY",
        )
    if asr_status == "ASR_REVIEW_REQUIRED":
        return (
            "READY",
            "SAME_DAY_VIDEO_LOCKED",
            evidence,
            "PARTIAL_REVIEW_REQUIRED",
            "ASR_REVIEW_REQUIRED",
        )
    return (
        "READY",
        "SAME_DAY_VIDEO_LOCKED",
        evidence,
        "NOT_MATERIALIZED",
        "SAME_DAY_ASR_NOT_READY",
    )


def build_close_review_chain(
    trade_date: str,
    *,
    close_source_evidence: list[dict[str, Any]],
    video_acceptance: Mapping[str, Any] | None = None,
    video_capture: Mapping[str, Any] | None = None,
    stockdict_pointer: Mapping[str, Any] | None = None,
    ocr_alignment_pointer: Mapping[str, Any] | None = None,
    video_gap_pointer: Mapping[str, Any] | None = None,
    ui_acceptance: bool = False,
) -> dict[str, Any]:
    """Build the exact legacy order without turning missing video into prose."""
    trade_date = _date(trade_date)
    if not close_source_evidence:
        raise ValueError("close source evidence is required")
    for row in close_source_evidence:
        if not isinstance(row, Mapping) or str(row.get("trade_date") or "") != trade_date:
            raise ValueError("close source evidence date mismatch")
    video_status, video_reason, video_evidence, asr_status, asr_reason = _video_state(
        trade_date, video_acceptance, video_capture
    )
    nodes = [
        _node(*CHAIN_TASKS[0], trade_date, "READY", "EXACT_DATE_CLOSE_SOURCE_FROZEN", close_source_evidence),
        _node(*CHAIN_TASKS[1], trade_date, "READY", "CLOSE_REVIEW_STARTED_FROM_FROZEN_SOURCE", close_source_evidence),
        _node(*CHAIN_TASKS[2], trade_date, "READY", "DETERMINISTIC_A_SHARE_STRUCTURE_READY", close_source_evidence),
        _node(*CHAIN_TASKS[3], trade_date, video_status, video_reason, video_evidence),
        _node(*CHAIN_TASKS[4], trade_date, asr_status, asr_reason, video_evidence),
    ]
    stockdict_ready = (
        isinstance(stockdict_pointer, Mapping)
        and stockdict_pointer.get("trade_date") == trade_date
        and stockdict_pointer.get("status") == "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY"
    )
    if stockdict_pointer is not None and not isinstance(stockdict_pointer, Mapping):
        raise ValueError("stockdict pointer must be an object")
    nodes.append(_node(
        *CHAIN_TASKS[5], trade_date,
        "READY_WITH_REVIEW_BOUNDARY" if stockdict_ready else "NOT_MATERIALIZED",
        "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY" if stockdict_ready else "DEPENDENCY_FUPAN_VIDEO_DOWNLOAD_ASR_NOT_READY",
        [{"source_id": "current_asr_pointer", "trade_date": trade_date, "status": stockdict_pointer.get("status")}]
        if stockdict_ready else [],
    ))
    ocr_ready = (
        isinstance(ocr_alignment_pointer, Mapping)
        and ocr_alignment_pointer.get("trade_date") == trade_date
        and ocr_alignment_pointer.get("status") == "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY"
        and int(ocr_alignment_pointer.get("row_count") or 0) > 0
    )
    if ocr_alignment_pointer is not None and not isinstance(ocr_alignment_pointer, Mapping):
        raise ValueError("OCR alignment pointer must be an object")
    nodes.append(_node(
        *CHAIN_TASKS[6], trade_date,
        "READY_WITH_REVIEW_BOUNDARY" if ocr_ready else "NOT_MATERIALIZED",
        "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY" if ocr_ready else "DEPENDENCY_FUPAN_STOCKDICT_NOT_READY",
        [{"source_id": "video_ocr_alignment", "trade_date": trade_date, "row_count": ocr_alignment_pointer.get("row_count")}]
        if ocr_ready else [],
    ))
    gap_ready = (
        isinstance(video_gap_pointer, Mapping)
        and video_gap_pointer.get("trade_date") == trade_date
        and video_gap_pointer.get("status") == "VIDEO_GAP_AUDIT_READY"
        and int(video_gap_pointer.get("gap_row_count") or 0) > 0
    )
    if video_gap_pointer is not None and not isinstance(video_gap_pointer, Mapping):
        raise ValueError("video gap pointer must be an object")
    nodes.append(_node(
        *CHAIN_TASKS[7], trade_date,
        "READY_WITH_REVIEW_BOUNDARY" if gap_ready else "NOT_MATERIALIZED",
        "VIDEO_GAP_AUDIT_READY" if gap_ready else "DEPENDENCY_FUPAN_VIDEO_TABLE_OCR_ALIGN_NOT_READY",
        [{"source_id": "video_gap_audit", "trade_date": trade_date, "gap_row_count": video_gap_pointer.get("gap_row_count")}]
        if gap_ready else [],
    ))
    missing = [
        node["task_id"]
        for node in nodes
        if node["status"] not in {"READY", "READY_WITH_REVIEW_BOUNDARY"}
    ]
    if missing:
        publish_status = "NOT_MATERIALIZED"
        publish_reason = "DETERMINISTIC_REVIEW_NOT_PUBLISHED_PENDING_DEPENDENCIES"
    else:
        publish_status = "READY"
        publish_reason = "DETERMINISTIC_REVIEW_READY_ALL_DEPENDENCIES_CLOSED"
    nodes.append(_node(
        *CHAIN_TASKS[8], trade_date, publish_status, publish_reason,
        close_source_evidence,
    ))
    # FUPAN_8771_VERIFY must not report ready while the page has not been
    # accepted; it stays NOT_MATERIALIZED until publish is READY and UI
    # acceptance evidence is present.
    if publish_status == "READY" and ui_acceptance:
        verify_status = "READY"
        verify_reason = "ARTIFACT_MANIFEST_API_PAGE_ACCEPTED"
    elif publish_status == "READY":
        verify_status = "NOT_MATERIALIZED"
        verify_reason = "UI_ACCEPTANCE_PENDING"
    else:
        verify_status = "NOT_MATERIALIZED"
        verify_reason = "DEPENDENCY_FUPAN_V3_PUBLISH_NOT_READY"
    nodes.append(_node(
        *CHAIN_TASKS[9], trade_date, verify_status, verify_reason,
        close_source_evidence,
    ))
    chain_status = "READY" if not missing and publish_status == "READY" and verify_status == "READY" else "PARTIAL_REVIEW"
    return {
        "schema_version": "v3_5.close_review_chain.v1",
        "trade_date": trade_date,
        "status": chain_status,
        "nodes": nodes,
        "cannot_confirm": missing,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def validate_close_review_chain(payload: Mapping[str, Any], trade_date: str) -> None:
    trade_date = _date(trade_date)
    if payload.get("schema_version") != "v3_5.close_review_chain.v1" or payload.get("trade_date") != trade_date:
        raise ValueError("invalid close-review chain identity")
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or [node.get("task_id") for node in nodes] != [row[0] for row in CHAIN_TASKS]:
        raise ValueError("invalid close-review chain order")
    if any(node.get("business_date") != trade_date for node in nodes):
        raise ValueError("close-review chain date mismatch")
    if any(payload.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise ValueError("unsafe close-review chain")
