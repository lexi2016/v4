"""Frozen ownership contract for the visible V3.5 nineteen-node timeline."""
from __future__ import annotations

from typing import Any


def _node(
    position: int,
    node_id: str,
    planned_slot: str,
    label: str,
    owner_id: str,
    owner_kind: str,
    *,
    workload_id: str | None = None,
    stage_id: str | None = None,
    retry_slots: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "position": position,
        "node_id": node_id,
        "planned_slot": planned_slot,
        "label": label,
        "owner_id": owner_id,
        "owner_kind": owner_kind,
        "workload_id": workload_id,
        "stage_id": stage_id,
        "retry_slots": retry_slots,
    }


CLOSE_TIMELINE: tuple[dict[str, Any], ...] = (
    _node(1, "STAGE_0925", "0925", "09:20/09:25竞价选股", "stage_center.STAGE_0925", "STAGE_CENTER", stage_id="STAGE_0925"),
    _node(2, "STAGE_0930_0935", "0935", "09:30-09:35", "stage_center.STAGE_0930_0935", "STAGE_CENTER", stage_id="STAGE_0930_0935"),
    _node(3, "STAGE_0935_0940", "0940", "09:35-09:40", "stage_center.STAGE_0935_0940", "STAGE_CENTER", stage_id="STAGE_0935_0940"),
    _node(4, "STAGE_0940_0945", "0945", "09:40-09:45", "stage_center.STAGE_0940_0945", "STAGE_CENTER", stage_id="STAGE_0940_0945"),
    _node(5, "STAGE_0945_1030", "1030", "09:45-10:30", "stage_center.STAGE_0945_1030", "STAGE_CENTER", stage_id="STAGE_0945_1030"),
    _node(6, "STAGE_1300_1315", "1315", "13:00-13:15", "stage_center.STAGE_1300_1315", "STAGE_CENTER", stage_id="STAGE_1300_1315"),
    _node(7, "STAGE_1445_1500", "1500", "14:45-15:00", "stage_center.STAGE_1445_1500", "STAGE_CENTER", stage_id="STAGE_1445_1500"),
    _node(8, "STAGE_1545_1555", "1555", "15:45-15:55港股", "stage_center.STAGE_1545_1555", "STAGE_CENTER", stage_id="STAGE_1545_1555"),
    _node(9, "hkconnect_model_selection_review", "1610", "16:10 港股通正式收盘：0.2 × 七阶段 Top20", "v35_dispatcher.hk_connect_close_review", "V35", workload_id="hk_connect_close_review"),
    _node(10, "FUPAN_CLOSE_MATERIALS", "1500", "15:00 收盘前总结材料", "v35_dispatcher.fupan_close_materials", "V35", workload_id="fupan_close_materials", stage_id="STAGE_1445_1500"),
    _node(11, "FUPAN_REVIEW_START", "1555", "15:55 收盘后复盘启动", "v35_dispatcher.fupan_review_start", "V35", workload_id="fupan_review_start", stage_id="STAGE_1545_1555"),
    _node(12, "FUPAN_A_SHARE_STRUCTURE", "1605", "16:05 A股收盘数据与题材骨架", "v35_dispatcher.a_share_close_review", "V35", workload_id="a_share_close_review", retry_slots=("1710",)),
    _node(13, "FUPAN_VIDEO_CHECK", "2030", "20:30 最新复盘视频检查", "v35_dispatcher.fupan_video_check", "V35", workload_id="fupan_video_check"),
    _node(14, "FUPAN_VIDEO_DOWNLOAD_ASR", "2040", "20:40 视频下载与转写", "v35_dispatcher.fupan_video_download_asr", "V35", workload_id="fupan_video_download_asr"),
    _node(15, "FUPAN_STOCKDICT", "2050", "20:50 股票字典校正", "v35_dispatcher.fupan_stockdict", "V35", workload_id="fupan_stockdict"),
    _node(16, "FUPAN_VIDEO_TABLE_OCR_ALIGN", "2105", "21:05 视频表格OCR/ASR/新闻对齐", "v35_dispatcher.fupan_video_table_ocr_align", "V35", workload_id="fupan_video_table_ocr_align"),
    _node(17, "FUPAN_VIDEO_GAP", "2108", "21:08 页面复盘对视频差距", "v35_dispatcher.fupan_video_gap", "V35", workload_id="fupan_video_gap"),
    _node(18, "FUPAN_V3_PUBLISH", "2110", "21:10 第三版复盘发布", "v35_dispatcher.fupan_v3_publish", "V35", workload_id="fupan_v3_publish"),
    _node(19, "FUPAN_8771_VERIFY", "2115", "21:15 8873 页面与接口验收", "v35_dispatcher.fupan_8873_verify", "V35", workload_id="fupan_8771_verify"),
)

CLOSE_TIMELINE_SLOT_TO_NODE = {
    "1610": "hk_connect_close_review",
    "1500": "FUPAN_CLOSE_MATERIALS",
    "1555": "FUPAN_REVIEW_START",
    "1605": "FUPAN_A_SHARE_STRUCTURE",
    "2030": "FUPAN_VIDEO_CHECK",
    "2040": "FUPAN_VIDEO_DOWNLOAD_ASR",
    "2050": "FUPAN_STOCKDICT",
    "2105": "FUPAN_VIDEO_TABLE_OCR_ALIGN",
    "2108": "FUPAN_VIDEO_GAP",
    "2110": "FUPAN_V3_PUBLISH",
    "2115": "FUPAN_8771_VERIFY",
}


def visible_timeline_owners(catalog: Any) -> list[dict[str, Any]]:
    """Return the exact one-owner projection used by API and focused tests."""
    workload_ids = {row.workload_id for row in catalog.workloads}
    rows: list[dict[str, Any]] = []
    for item in CLOSE_TIMELINE:
        workload_id = item.get("workload_id")
        if item["owner_kind"] == "V35" and workload_id not in workload_ids:
            raise ValueError(f"timeline workload owner missing: {workload_id}")
        rows.append(dict(item))
    return rows


__all__ = ["CLOSE_TIMELINE", "CLOSE_TIMELINE_SLOT_TO_NODE", "visible_timeline_owners"]
