#!/usr/bin/env python3
"""Freeze and deterministically route the captured Eastmoney HK daily window.

This is a temporary evidence helper. It reads the two existing immutable
CaptureStore products and the existing V2 Connect membership authority. It
does not fetch, infer operating impact, choose securities, or call a model.
Run from the V4 checkout with its existing venv so the pinned native
membership verifier is importable.
"""
from __future__ import annotations

import hashlib
import argparse
from copy import deepcopy
import ipaddress
import json
import re
import secrets
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo


PIPELINE_DIR = Path(__file__).resolve().parents[2]
V4_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
UNIVERSE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/"
    "workspace/v3_shared_data/.runtime/data"
)
LEFT = datetime.fromisoformat("2026-10-13T21:43:25+08:00")
RIGHT = datetime.fromisoformat("2026-10-14T21:43:25+08:00")
TZ = ZoneInfo("Asia/Shanghai")
PRODUCTS = (
    {
        "path": Path(
            "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/"
            "manager_workbench_capture/products/"
            "11cbccc238771b8d2627c6075a5229e7450eb9d944ef78c210af3119fcd2d130.json"
        ),
        "sha256": "11cbccc238771b8d2627c6075a5229e7450eb9d944ef78c210af3119fcd2d130",
        "run_id": "6f28ecf230f840a19983727718b82453",
        "date": "2026-10-13",
        "elapsed_seconds": None,
        "elapsed_note": "原始 Oct 13 归档无可复核 wrapper wall 计时；不重构或冒充为实测。",
    },
    {
        "path": Path(
            "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/"
            "manager_workbench_capture/products/"
            "a08f72fa72acc71eace7cba0aeec4e657bcfa084ad6813528daed43d2b987047.json"
        ),
        "sha256": "a08f72fa72acc71eace7cba0aeec4e657bcfa084ad6813528daed43d2b987047",
        "run_id": "6eec68e11a764e55afa8a32082f7e524",
        "date": "2026-10-14",
        "elapsed_seconds": 115.078,
        "elapsed_note": "原始 capture_window wrapper 单调时钟实测；非模型时间。",
    },
)

OUTPUT_DIR = Path(__file__).resolve().parent
RECORDS_PATH = OUTPUT_DIR / "source-window-records.jsonl"
TRIAGE_PATH = OUTPUT_DIR / "triage-manifest.json"
CANDIDATES_PATH = OUTPUT_DIR / "candidate-titles.md"
CAPTURE_STORE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench_capture"
)
CANDIDATE_ROOT = OUTPUT_DIR / "candidate-172" / "ready-v2"
GUOEN_TARGETED_EVIDENCE_ROOT = PIPELINE_DIR / "evidence" / "guoen-live-rerun-20261015"
GUOEN_TARGETED_RANGE_CANDIDATE_ROOT = PIPELINE_DIR / "evidence" / "announcement-rootcause-20261016" / "guoen-targeted-range-v2"
GUOEN_TARGETED_SOURCE_ROOT = OUTPUT_DIR / "candidate-172" / "recovery-balanced-v1"
GUOEN_TARGETED_SOURCE_MANIFEST_SHA256 = "45a8bd91af72dbffb4fff7a623e60090a0fbee58467fa358449e5ae92fe017dd"
GUOEN_TARGETED_SOURCE_BATCH_SHA256 = "4ef836e5826770f2dfe481db5d4937723043e555a7d883563dca5bc35a5a5b20"
GUOEN_TARGETED_IDS = (
    "EASTMONEY:AN202610141830470256",
    "EASTMONEY:AN202610141830469348",
)
GUOEN_TARGETED_SOURCE_SHAS = {
    "EASTMONEY:AN202610141830470256": {
        "source_sha256": "1e045cf97957b7926f28c6cca8c7de573871620a614c9bc6ba6c7aeaf2171a88",
        "body_sha256": "6dd64a38447d9cd8c00a9401ed36b0787bad88377254376b879127ba1cd64b07",
    },
    "EASTMONEY:AN202610141830469348": {
        "source_sha256": "c9c575160bdb9d76f9fe641e42ada097286a45125d920768ff23f99f1c27d3e1",
        "body_sha256": "36f8a449ebe5b8fa8d8c73922975743d69627dee9b4fce69e4723096cf963500",
    },
}
GUOEN_TARGETED_SCHEMA = "recent_day_flash_guoen_targeted_candidate.v1"
GUOEN_TARGETED_RANGE_SCHEMA = "recent_day_flash_guoen_targeted_candidate.v2"
CAPABILITY_SAMPLE_SCHEMA = "recent_day_flash_capability_sample_candidate.v1"
CAPABILITY_SAMPLE_ROOT = PIPELINE_DIR / "evidence" / "announcement-screening-capability-20261016"
CAPABILITY_SAMPLE_CANDIDATE_ROOT = CAPABILITY_SAMPLE_ROOT / "capability-sample-v1"
CAPABILITY_SOURCE_ROOT = PIPELINE_DIR / "evidence" / "new-announcements-20261016"
CAPABILITY_SOURCE_INPUT = CAPABILITY_SOURCE_ROOT / "capability-sample-inputs.jsonl"
CAPABILITY_SOURCE_MANIFEST = CAPABILITY_SOURCE_ROOT / "capability-sample-manifest.json"
CAPABILITY_SOURCE_INPUT_SHA256 = "38eabc6e76c31d9f95eefa3cde408a58558a9eb8b74168d11951d5f8746bd6ad"
CAPABILITY_SOURCE_MANIFEST_SHA256 = "8ca3b235c62357408c7f5dc63470008a79211a47c2c5c6c372f239ffa9534ae5"
CAPABILITY_SAMPLE_MAX_COUNT = 8
UNSEEN_NONROUTINE_INPUT = CAPABILITY_SOURCE_ROOT / "nonroutine-unseen-sample-input.jsonl"
UNSEEN_NONROUTINE_INPUT_SHA256 = "27ed105f64827bc87f95893292d1aecfe9d19499067e4660396b758e2763f01b"
UNSEEN_NONROUTINE_CAPTURE_MANIFEST = CAPABILITY_SOURCE_ROOT / "incremental-capture-manifest.json"
UNSEEN_NONROUTINE_CAPTURE_MANIFEST_SHA256 = "de5877a851c85aad4933b87d0da845e499e94d2b8115e0ec454bbd34ba26f499"
UNSEEN_NONROUTINE_COVERAGE = CAPABILITY_SOURCE_ROOT / "incremental-capture-coverage.json"
UNSEEN_NONROUTINE_COVERAGE_SHA256 = "c6854a18500e3273d71be67f2d31900aa3630709e59188f33cb5f27fd2b5955b"
UNSEEN_NONROUTINE_ARTICLE_ID = "EASTMONEY:AN202610151830479227"
UNSEEN_NONROUTINE_BODY_SHA256 = "85fcbef2e9f53d5d0e0348424dc0cbfda9df72780ac8129a765e0b19525e466f"
UNSEEN_NONROUTINE_SOURCE_SHA256 = "8cae39a545e4e012f69bc83386649e1f09c0089e6e07ccc40e1b68742b5942b2"
UNSEEN_NONROUTINE_SOURCE_MANIFEST = CAPABILITY_SAMPLE_ROOT / "nonroutine-unseen-v1" / "normalized-source-manifest.json"

# Modules are loaded lazily for the original read-only triage command. The
# temporary Flash adapter below reuses their existing contracts and transport.
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


_sha = _sha256


def _load_products() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for spec in PRODUCTS:
        raw = spec["path"].read_bytes()
        digest = _sha256(raw)
        if digest != spec["sha256"]:
            raise RuntimeError(f"CAPTURE_PRODUCT_SHA_MISMATCH:{spec['path'].name}")
        product = json.loads(raw)
        if (
            product.get("schema_version") != "mwb.capture.window.v1"
            or product.get("source") != "EASTMONEY_HK"
            or product.get("owner") != "v4.manager_workbench.capture_announcements"
            or product.get("run_id") != spec["run_id"]
        ):
            raise RuntimeError(f"CAPTURE_PRODUCT_IDENTITY_MISMATCH:{spec['path'].name}")
        inside: list[dict[str, Any]] = []
        outside_count = 0
        for row in product.get("rows", []):
            timestamp = row.get("display_time")
            if not isinstance(timestamp, str):
                continue
            instant = datetime.fromisoformat(timestamp)
            if instant.tzinfo is None:
                raise RuntimeError(f"DISPLAY_TIME_WITHOUT_OFFSET:{row.get('art_code')}")
            instant = instant.astimezone(TZ)
            if LEFT <= instant < RIGHT:
                wrapped = dict(row)
                wrapped["_capture_product"] = {
                    "path": str(spec["path"]),
                    "sha256": digest,
                    "run_id": spec["run_id"],
                    "publication_date": spec["date"],
                    "elapsed_seconds": spec["elapsed_seconds"],
                    "elapsed_note": spec["elapsed_note"],
                }
                inside.append(wrapped)
            else:
                outside_count += 1
        all_rows.extend(inside)
        catalogue = (product.get("catalogues") or [{}])[0]
        summaries.append(
            {
                "path": str(spec["path"]),
                "sha256": digest,
                "run_id": product["run_id"],
                "publication_date": spec["date"],
                "catalogue_rows": len(product.get("rows", [])),
                "window_rows": len(inside),
                "outside_window_rows": outside_count,
                "body_complete_full_product": sum(
                    bool(r.get("body_complete")) for r in product.get("rows", [])
                ),
                "body_failed_full_product": sum(
                    not bool(r.get("body_complete")) for r in product.get("rows", [])
                ),
                "catalogue_pages": len(catalogue.get("page_receipts", [])),
                "catalogue_total_hits": catalogue.get("total_hits"),
                "terminal_empty_seen": catalogue.get("terminal_empty_seen"),
                "catalogue_gaps": catalogue.get("gaps", []),
                "product_gaps": product.get("gaps", []),
                "capture_elapsed_seconds": spec["elapsed_seconds"],
                "capture_elapsed_note": spec["elapsed_note"],
                "research_cutoff": (product.get("window") or {}).get("research_cutoff"),
                "capture_available_after_research_cutoff": (
                    "CAPTURE_AVAILABLE_AFTER_RESEARCH_CUTOFF" in product.get("gaps", [])
                ),
            }
        )
    return all_rows, summaries


def _read_membership() -> tuple[set[str], dict[str, Any]]:
    sys.path.insert(0, str(V4_ROOT))
    from domains.manager_research_evidence import read_universe_evidence

    owner_file = V4_ROOT / "stage_center" / "hk_universe_preflight.py"
    owner_sha = _sha256(owner_file.read_bytes())
    verified = read_universe_evidence(
        UNIVERSE_ROOT,
        "20261012",
        authority_owner_root=V4_ROOT,
        authority_owner_sha256=owner_sha,
        require_v2=True,
    )
    src = dict(verified.source)
    if (
        src.get("role") != "HK_CONNECT_FULL_MARKET_AUTHORITY"
        or src.get("source_role") != "FUTU_HKCONNECT_PLATE_MEMBERSHIP"
        or src.get("source_date") != "20261012"
        or src.get("code_sha256") == ""
    ):
        raise RuntimeError("MONTHLY_CONNECT_AUTHORITY_IDENTITY_INVALID")
    available = datetime.fromisoformat(src["available_at"])
    if available > LEFT:
        raise RuntimeError("MONTHLY_CONNECT_AUTHORITY_NOT_AVAILABLE_BEFORE_WINDOW")
    return set(verified.codes), {
        "status": "VERIFIED_SAVED_MONTHLY_AUTHORITY; ACTIVE_8873_BINDING_CANNOT_CONFIRM",
        "code_count": len(verified.codes),
        "codes_sha256_artifact": src.get("sha256"),
        "run_id": src.get("run_id"),
        "source_date": src.get("source_date"),
        "available_at": src.get("available_at"),
        "read_at": src.get("read_at"),
        "read_at_after_frozen_window": datetime.fromisoformat(src["read_at"]) > RIGHT,
        "owner": src.get("owner"),
        "role": src.get("role"),
        "source_role": src.get("source_role"),
        "owner_code_sha256": owner_sha,
        "artifact_ref": src.get("artifact_ref"),
        "manifest_ref": src.get("manifest_ref"),
        "receipt_ref": src.get("receipt_ref"),
        "current_ref": src.get("current_ref"),
        "capture_ref": src.get("capture_ref"),
        "publication_ref": src.get("publication_ref"),
        "capture_run_id": src.get("capture_run_id"),
        "capture_sha256": src.get("capture_sha256"),
        "source_sha256": src.get("source_sha256"),
    }


def _membership_for_row(
    row: dict[str, Any], universe: set[str]
) -> tuple[list[dict[str, Any]], str]:
    expansions = row.get("source_issuer_codes")
    if not isinstance(expansions, list) or not expansions:
        return [], "CANNOT_CONFIRM"
    result: list[dict[str, Any]] = []
    for issuer in expansions:
        code = issuer.get("code") if isinstance(issuer, dict) else None
        if isinstance(code, str) and re.fullmatch(r"HK\.\d{5}", code):
            status = "MEMBER" if code in universe else "NON_MEMBER"
        else:
            status = "CANNOT_CONFIRM"
        result.append(
            {
                "code": code,
                "source_issuer_name": issuer.get("name") if isinstance(issuer, dict) else None,
                "status": status,
            }
        )
    if any(item["status"] == "MEMBER" for item in result):
        article_status = "HAS_MEMBER"
    elif any(item["status"] == "CANNOT_CONFIRM" for item in result):
        article_status = "CANNOT_CONFIRM"
    else:
        article_status = "ALL_KNOWN_NON_MEMBER"
    return result, article_status


def _body_status(row: dict[str, Any]) -> tuple[str, str | None]:
    text = row.get("body_text")
    if not row.get("body_complete") or not isinstance(text, str) or not text:
        return "UNKNOWN_BODY_MISSING", None
    expected = row.get("body_text_sha256")
    actual = _sha256(text.encode("utf-8"))
    if not isinstance(expected, str) or actual != expected:
        return "UNKNOWN_BODY_HASH_MISMATCH", actual
    # `text_characters` in CaptureStore is the sum of page text lengths before
    # the producer joins pages with separator newlines, so it need not equal
    # len(body_text). The producer's complete flag plus exact body SHA is the
    # integrity contract here; do not misclassify separator bytes as loss.
    return "COMPLETE_HASH_VERIFIED", actual


def _triage(row: dict[str, Any], body_status: str) -> tuple[str, str, str | None]:
    """Route by explicit complete-body document type; never predict disposition."""
    if body_status != "COMPLETE_HASH_VERIFIED":
        return (
            "UNKNOWN_BODY_MISSING_OR_INTEGRITY_FAILURE",
            "正文缺失或完整性校验失败；不以标题或空文本判断低价值，留待来源修复。",
            None,
        )
    title = str(row.get("title") or "")
    body = str(row.get("body_text") or "")
    flat = re.sub(r"\s+", " ", body)

    if "翌日披露报表" in title and (
        "翌日披露報表" in body
        or ("已發行股份" in body and "股份購回" in body and "庫存股份" in body)
    ):
        return (
            "LOW_PRIORITY_SHARE_CAPITAL_FORM",
            "正文确认是完整翌日披露股份变动/回购表；隔离于经营变化精读，仍保留在股本与回购事件队列。",
            "share_capital_follow_up",
        )
    if title == "资产净值" and ("资产净值" in body or "資產淨值" in body):
        return (
            "LOW_PRIORITY_NAV_REPORT",
            "完整正文仅为资产净值/单位净值报告；转估值资料队列，不作为当前经营变化候选。",
            "valuation_follow_up",
        )
    if (
        any(token in title for token in ("董事会会议", "董事会會議", "召开董事会", "董事会召开日期"))
        and any(token in flat for token in ("将于", "將於", "謹定於", "兹定於", "謹訂於"))
        and any(token in flat for token in ("董事會會議", "董事会会议", "董事會會議"))
        and not any(token in title for token in ("投票结果", "决议", "審議結果", "审议结果"))
        and not any(token in title for token in ("股息实施", "分紅派息實施"))
    ):
        follow_up = "earnings_or_meeting_follow_up"
        if any(token in flat for token in ("股息（如有）", "派付中期股息", "建議中期股息", "特別股息")):
            follow_up = "meeting_agenda_includes_possible_dividend"
        return (
            "LOW_PRIORITY_FUTURE_MEETING_SCHEDULE",
            "完整正文只提供未来会议日期/拟审议事项，没有本次会议决议或已披露业绩；留待正式决议/业绩公告回收。",
            follow_up,
        )

    static_doc = any(
        token in title
        for token in (
            "董事名单与其角色和职能",
            "董事名单与其角色及职能",
            "董事名单与其角色和职能",
            "委员会工作细则",
            "委任表格",
            "代表委任表格",
            "选择表格",
            "接纳表格",
            "申请表格",
            "通知信函及回条",
            "通知信函 –",
            "通知信函-",
            "非登记持有人之通知信函",
            "登记股东之通知信函",
        )
    )
    if static_doc and len(flat) > 0:
        return (
            "LOW_PRIORITY_PROCEDURAL_OR_GOVERNANCE_DOCUMENT",
            "完整正文确认为治理资料/会议或股息相关程序表格；转入对应治理或公司行动队列，不当作经营变化证据。",
            "governance_or_corporate_action_follow_up",
        )

    risk_markers = (
        "盈利预警",
        "盈利警告",
        "清盘呈请",
        "清盤呈請",
        "法律诉讼",
        "訴訟進展",
        "暂停买卖",
        "暫停買賣",
        "股权高度集中",
        "股權高度集中",
        "死亡事故",
        "人员伤亡",
        "員工死亡",
    )
    if any(token in title for token in risk_markers) or any(token in flat for token in risk_markers):
        return (
            "RETAIN_RISK_REVIEW",
            "正文或标题包含明确风险/诉讼/持续经营风险信号；单独进入风险核读，不推作正向经营候选。",
            "risk_review",
        )

    operating_markers = (
        "業績預告",
        "业绩预告",
        "盈利预警",
        "盈利预增",
        "经营数据",
        "运营数据",
        "營運數據",
        "生产报告",
        "生產報告",
        "上网电量",
        "新签合同",
        "新簽合同",
        "業務更新",
        "业务更新",
        "业务最新情况",
        "業務最新情況",
        "商品交易总额",
        "商品交易總額",
        "收入較去年同期",
        "收入较去年同期",
        "营运统计数据",
        "營運統計數據",
    )
    if any(token in title or token in body for token in operating_markers):
        return (
            "RETAIN_POTENTIAL_OPERATING_RESEARCH",
            "完整正文包含可供核验的业绩/产量/销量/合同/经营更新信息；仅供模型/研究者判断，脚本未作正向结论。",
            "operating_review",
        )

    corporate_markers = (
        "配售",
        "供股",
        "股份回购",
        "股份購回",
        "收购",
        "收購",
        "出售",
        "股息",
        "分紅",
        "可转换债券",
        "可換股債券",
        "清盘",
        "清盤",
        "基金",
    )
    if any(token in title or token in body[:5000] for token in corporate_markers):
        return (
            "RETAIN_CORPORATE_ACTION_REVIEW",
            "完整正文涉及资本、交易或股东行动；与经营变化分流，避免误当作经营改善/恶化。",
            "corporate_action_review",
        )
    return (
        "RETAIN_UNCLASSIFIED_REVIEW",
        "正文完整，但未命中安全的低优先级或潜在经营类型；保留全文供后续判断，不按标题排除。",
        "manual_content_review",
    )


def build() -> dict[str, Any]:
    rows, product_summaries = _load_products()
    rows.sort(key=lambda r: (datetime.fromisoformat(r["display_time"]).astimezone(TZ), r["art_code"]))
    ids = [r.get("art_code") for r in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("DUPLICATE_ART_CODE_IN_FROZEN_WINDOW")

    universe, membership_source = _read_membership()
    records: list[dict[str, Any]] = []
    triage_rows: list[dict[str, Any]] = []
    membership_expansions: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    body_counts: Counter[str] = Counter()
    member_article_counts: Counter[str] = Counter()
    official_time_present = 0
    for index, row in enumerate(rows, start=1):
        body_status, computed_body_sha = _body_status(row)
        body_counts[body_status] += 1
        category, reason, route = _triage(row, body_status)
        category_counts[category] += 1
        expanded, article_membership = _membership_for_row(row, universe)
        member_article_counts[article_membership] += 1
        issuer_codes = list(row.get("source_issuer_codes") or [])
        membership_expansions.extend(
            {"art_code": row.get("art_code"), **entry} for entry in expanded
        )
        official_time = row.get("first_hkex_publication_time")
        if isinstance(official_time, str) and official_time != "CANNOT_CONFIRM":
            official_time_present += 1
        raw_record = {
            "record_index": index,
            "art_code": row.get("art_code"),
            "title": row.get("title"),
            "source": "EASTMONEY_HK",
            "source_scope": "EASTMONEY_ONLY",
            "display_time": row.get("display_time"),
            "source_display_time_raw": row.get("source_display_time_raw"),
            "first_hkex_publication_time": row.get("first_hkex_publication_time"),
            "publication_time_basis": row.get("publication_time_basis"),
            "original_point_in_time_availability": row.get("original_point_in_time_availability"),
            "publication_window_status": row.get("publication_window_status"),
            "source_issuer_codes": issuer_codes,
            "source_sha256": row.get("source_sha256"),
            "listing_source_ref": row.get("listing_source_ref"),
            "body_artifact_ref": row.get("body_artifact_ref"),
            "body_complete": bool(row.get("body_complete")),
            "body_status": row.get("body_status"),
            "body_text_sha256": row.get("body_text_sha256"),
            "computed_body_text_sha256": computed_body_sha,
            "body_text": row.get("body_text"),
            "pages": row.get("pages"),
            "content_page_count": row.get("content_page_count"),
            "gaps": row.get("gaps", []),
            "raw_row": row.get("raw_row"),
            "capture_product": row.get("_capture_product"),
        }
        records.append(raw_record)
        triage_rows.append(
            {
                "art_code": row.get("art_code"),
                "title": row.get("title"),
                "display_time": row.get("display_time"),
                "issuer_expansion": issuer_codes,
                "issuer_membership": expanded,
                "article_membership_status": article_membership,
                "body_status": body_status,
                "body_sha256": row.get("body_text_sha256"),
                "source_sha256": row.get("source_sha256"),
                "source_ref": row.get("body_artifact_ref"),
                "capture_product_sha256": row["_capture_product"]["sha256"],
                "route": category,
                "route_bucket": route,
                "reason": reason,
                "model_or_semantic_judgment": "NOT_RUN",
            }
        )

    issuer_counts = Counter(item["status"] for item in membership_expansions)
    membership_source["resolved_issuer_expansion_counts"] = {
        "member": issuer_counts["MEMBER"],
        "non_member": issuer_counts["NON_MEMBER"],
        "cannot_confirm": issuer_counts["CANNOT_CONFIRM"],
    }
    membership_source["article_counts"] = {
        "has_at_least_one_member": member_article_counts["HAS_MEMBER"],
        "all_known_non_member": member_article_counts["ALL_KNOWN_NON_MEMBER"],
        "cannot_confirm": member_article_counts["CANNOT_CONFIRM"],
    }

    with RECORDS_PATH.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    records_sha = _sha256(RECORDS_PATH.read_bytes())

    candidate_groups: dict[str, list[dict[str, Any]]] = {}
    for item in triage_rows:
        if item["route"].startswith("RETAIN_"):
            candidate_groups.setdefault(item["route"], []).append(item)
    operating_candidate_count = len(candidate_groups.get("RETAIN_POTENTIAL_OPERATING_RESEARCH", []))
    risk_review_count = len(candidate_groups.get("RETAIN_RISK_REVIEW", []))
    md: list[str] = [
        "# 近 24 小时港股公告程序初筛标题清单",
        "",
        "窗口：`2026-10-13T21:43:25+08:00 <= display_time < 2026-10-14T21:43:25+08:00`。",
        "以下是程序路由清单，不是正向推荐或语义审核结果；所有正文和来源字段见 `source-window-records.jsonl`。仅 `RETAIN_POTENTIAL_OPERATING_RESEARCH` 是经营判断候选；`RETAIN_RISK_REVIEW` 单列。公司行动与未分类项目不自动提交模型。",
        "正文不完整的公告列为 `UNKNOWN`，不会进入低优先级隔离。",
        "",
        f"经营判断候选标题：{operating_candidate_count}；单列风险复核：{risk_review_count}；程序隔离低优先级：{sum(n for k, n in category_counts.items() if k.startswith('LOW_PRIORITY_'))}；公司行动与未分类路由不自动提交模型；正文/完整性未知：{category_counts['UNKNOWN_BODY_MISSING_OR_INTEGRITY_FAILURE']}。",
        "",
    ]
    for group, items in sorted(candidate_groups.items()):
        md.extend([f"## {group}（{len(items)}）", ""])
        for item in items:
            codes = ", ".join(x.get("code", "?") for x in item["issuer_expansion"]) or "issuer CANNOT_CONFIRM"
            md.append(
                f"- `{item['art_code']}` · {codes} · {item['title']} · "
                f"`{item['article_membership_status']}` · body `{item['body_status']}` · "
                f"source/body SHA `{item['source_sha256']}` / `{item['body_sha256'] or 'CANNOT_CONFIRM'}`"
            )
        md.append("")
    CANDIDATES_PATH.write_text("\n".join(md) + "\n", encoding="utf-8")

    manifest = {
        "schema": "recent_day_eastmoney_hk_window_freeze.v1",
        "created_at_local": datetime.now(TZ).isoformat(timespec="seconds"),
        "purpose": "程序初筛与可追溯冻结；不包含模型判断、正向推荐、正式 API/UI 接入或交易信号。",
        "scope": {
            "source": "EASTMONEY_HK",
            "source_scope": "EASTMONEY_ONLY",
            "left_inclusive": LEFT.isoformat(),
            "right_exclusive": RIGHT.isoformat(),
            "filter_field": "display_time",
            "filter_timezone": "Asia/Shanghai",
            "official_hkex_first_publication_time": "CANNOT_CONFIRM when absent in source record",
            "source_pit": "CANNOT_CONFIRM; capture completed after research cutoff",
        },
        "capture_products": product_summaries,
        "counts": {
            "window_article_rows": len(rows),
            "unique_art_code": len(set(ids)),
            "issuer_expansions": len(membership_expansions),
            "complete_body_hash_verified": body_counts["COMPLETE_HASH_VERIFIED"],
            "body_missing_or_integrity_failure": body_counts["UNKNOWN_BODY_MISSING"],
            "other_body_integrity_failure": sum(
                count for key, count in body_counts.items() if key.startswith("UNKNOWN_BODY_") and key != "UNKNOWN_BODY_MISSING"
            ),
            "first_hkex_publication_time_verified_present": official_time_present,
            "first_hkex_publication_time_cannot_confirm": len(rows) - official_time_present,
            "programmatic_operating_candidate_count": operating_candidate_count,
            "separate_risk_review_count": risk_review_count,
            "corporate_action_review_count": category_counts["RETAIN_CORPORATE_ACTION_REVIEW"],
            "unclassified_review_count": category_counts["RETAIN_UNCLASSIFIED_REVIEW"],
            "triage_route_counts": dict(sorted(category_counts.items())),
            "triage_body_status_counts": dict(sorted(body_counts.items())),
        },
        "connect_membership": membership_source,
        "membership_cannot_confirm_articles": [
            item["art_code"] for item in triage_rows if item["article_membership_status"] == "CANNOT_CONFIRM"
        ],
        "body_or_source_exceptions": [
            item
            for item in triage_rows
            if item["body_status"] != "COMPLETE_HASH_VERIFIED"
        ],
        "triage_policy": {
            "low_priority_categories": {
                "LOW_PRIORITY_SHARE_CAPITAL_FORM": "完整翌日披露表只转股本/回购队列；不从经营研究正文中删除。",
                "LOW_PRIORITY_NAV_REPORT": "完整资产净值/单位净值转估值资料队列。",
                "LOW_PRIORITY_FUTURE_MEETING_SCHEDULE": "仅未来会议安排，无本次决议/业绩；可含待审议派息，保留跟进标记。",
                "LOW_PRIORITY_PROCEDURAL_OR_GOVERNANCE_DOCUMENT": "完整治理资料或程序表格转治理/公司行动队列。",
            },
            "default": "正文完整但未命中明确程序性/非经营类型则保留；风险独立分流；标题命中只作路由而非正向/负向判断。",
            "missing_body": "UNKNOWN; never classified low priority from a title or missing text.",
            "model_judgment": "NOT_RUN",
        },
        "artifacts": {
            "source_window_records": str(RECORDS_PATH),
            "source_window_records_sha256": records_sha,
            "candidate_titles": str(CANDIDATES_PATH),
            "triage_manifest": str(TRIAGE_PATH),
            "candidate_title_rows": sum(len(items) for items in candidate_groups.values()),
        },
        "article_triage": triage_rows,
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "model_called": False,
            "service_or_ui_started": False,
            "new_source_fetch_in_helper": False,
        },
    }
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    TRIAGE_PATH.write_bytes(raw)
    return manifest


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes())
    except Exception as exc:
        raise RuntimeError(f"FROZEN_JSON_UNREADABLE:{path.name}:{type(exc).__name__}") from None


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _write_immutable(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if path.read_bytes() != raw:
            raise RuntimeError(f"FROZEN_ARTIFACT_CONFLICT:{path.name}")
        return
    path.write_bytes(raw)
    path.chmod(0o600)


def _load_frozen_candidate_rows() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    records_raw = RECORDS_PATH.read_bytes()
    triage = _read_json(TRIAGE_PATH)
    if _sha(records_raw) != triage.get("artifacts", {}).get("source_window_records_sha256"):
        raise RuntimeError("FROZEN_SOURCE_WINDOW_RECORDS_SHA_MISMATCH")
    records = [json.loads(line) for line in records_raw.decode("utf-8").splitlines() if line]
    record_by_id = {row.get("art_code"): row for row in records}
    triage_rows = triage.get("article_triage")
    triage_by_id = {row.get("art_code"): row for row in triage_rows or []}
    if len(records) != 340 or len(record_by_id) != 340 or len(triage_by_id) != 340:
        raise RuntimeError("FROZEN_WINDOW_ARTICLE_IDENTITY_INVALID")
    if set(record_by_id) != set(triage_by_id):
        raise RuntimeError("FROZEN_WINDOW_TRIAGE_IDENTITY_MISMATCH")
    retained = [item for item in triage_rows if str(item.get("route", "")).startswith("RETAIN_")]
    isolated = [item for item in triage_rows if str(item.get("route", "")).startswith("LOW_PRIORITY_")]
    exceptions = [item for item in triage_rows if str(item.get("route", "")).startswith("UNKNOWN_")]
    if (len(retained), len(isolated), len(exceptions)) != (172, 163, 5):
        raise RuntimeError("FROZEN_DECISION_LOCK_COUNTS_MISMATCH")
    for item in retained:
        record = record_by_id[item["art_code"]]
        if (
            item.get("body_status") != "COMPLETE_HASH_VERIFIED"
            or record.get("body_complete") is not True
            or not isinstance(record.get("body_text"), str)
            or not record["body_text"]
            or _sha(record["body_text"].encode("utf-8")) != item.get("body_sha256")
            or record.get("source_sha256") != item.get("source_sha256")
        ):
            raise RuntimeError(f"RETAINED_SOURCE_BODY_IDENTITY_INVALID:{item['art_code']}")
    return record_by_id, triage_by_id, triage


def _source_origins_for_record(
    record: dict[str, Any], capture_cache: dict[str, dict[str, Any]], page_cache: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    capture = record["capture_product"]
    capture_path = Path(capture["path"])
    capture_raw = capture_path.read_bytes()
    if _sha(capture_raw) != capture.get("sha256"):
        raise RuntimeError(f"CAPTURE_PRODUCT_SHA_MISMATCH:{record['art_code']}")
    if capture["sha256"] not in capture_cache:
        capture_cache[capture["sha256"]] = json.loads(capture_raw)
    capture_product = capture_cache[capture["sha256"]]
    capture_matches = [(index, row) for index, row in enumerate(capture_product.get("rows", [])) if row.get("art_code") == record["art_code"]]
    if len(capture_matches) != 1:
        raise RuntimeError(f"CAPTURE_PRODUCT_ROW_IDENTITY_INVALID:{record['art_code']}")
    capture_index, capture_row = capture_matches[0]
    if capture_row.get("raw_row") != record.get("raw_row") or capture_row.get("source_sha256") != record.get("source_sha256"):
        raise RuntimeError(f"CAPTURE_PRODUCT_ROW_CONTENT_MISMATCH:{record['art_code']}")

    listing = record.get("listing_source_ref")
    if not isinstance(listing, dict) or not isinstance(listing.get("sha256"), str):
        raise RuntimeError(f"LISTING_PAGE_ORIGIN_MISSING:{record['art_code']}")
    page_path = CAPTURE_STORE_ROOT / listing["artifact_ref"]
    page_raw = page_path.read_bytes()
    if _sha(page_raw) != listing["sha256"]:
        raise RuntimeError(f"LISTING_PAGE_SHA_MISMATCH:{record['art_code']}")
    if listing["sha256"] not in page_cache:
        page_cache[listing["sha256"]] = json.loads(page_raw)
    page_value = page_cache[listing["sha256"]]
    page_rows = ((page_value.get("data") or {}).get("list"))
    page_matches = [(index, row) for index, row in enumerate(page_rows or []) if row.get("art_code") == record["art_code"]]
    if len(page_matches) != 1:
        raise RuntimeError(f"LISTING_PAGE_ROW_IDENTITY_INVALID:{record['art_code']}")
    page_index, page_row = page_matches[0]
    if page_row != record.get("raw_row"):
        raise RuntimeError(f"LISTING_PAGE_ROW_CONTENT_MISMATCH:{record['art_code']}")

    body_ref = record.get("body_artifact_ref")
    if not isinstance(body_ref, str) or not body_ref.startswith("products/"):
        raise RuntimeError(f"BODY_PRODUCT_REFERENCE_INVALID:{record['art_code']}")
    body_path = CAPTURE_STORE_ROOT / body_ref
    body_raw = body_path.read_bytes()
    if _sha(body_raw) != record.get("source_sha256"):
        raise RuntimeError(f"BODY_PRODUCT_SHA_MISMATCH:{record['art_code']}")
    body_product = json.loads(body_raw)
    if (
        body_product.get("art_code") != record["art_code"]
        or body_product.get("body_text") != record.get("body_text")
        or body_product.get("body_text_sha256") != record.get("body_text_sha256")
    ):
        raise RuntimeError(f"BODY_PRODUCT_CONTENT_MISMATCH:{record['art_code']}")

    origins = [
        {
            "source_product_sha256": capture["sha256"],
            "source_row_index": capture_index,
            "row_fingerprint_sha256": _sha(_canonical_bytes(capture_row)),
            "source_ref": f"products/{capture_path.name}#rows/{capture_index}",
            "role": "BOUND_CAPTURE_PRODUCT_ROW",
        },
        {
            "source_product_sha256": listing["sha256"],
            "source_row_index": page_index,
            "row_fingerprint_sha256": _sha(_canonical_bytes(page_row)),
            "source_ref": f"{listing['artifact_ref']}#data/list/{page_index}",
            "role": "FULL_DATE_DIRECTORY_PAGE",
        },
        {
            "source_product_sha256": record["source_sha256"],
            "source_row_index": 0,
            "row_fingerprint_sha256": record["source_sha256"],
            "source_ref": f"{body_ref}#notice",
            "role": "VERIFIED_FULL_NOTICE_BODY_OBJECT",
        },
    ]
    return origins, body_product


def _article_for_record(
    record: dict[str, Any], triage: dict[str, Any], capture_cache: dict[str, dict[str, Any]], page_cache: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    import batch_runner as runner

    origins, body_product = _source_origins_for_record(record, capture_cache, page_cache)
    codes = record.get("source_issuer_codes") or []
    names = list(dict.fromkeys(
        item.get("name") for item in codes
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item.get("name")
    ))
    valid_codes = list(dict.fromkeys(
        item.get("code") for item in codes
        if isinstance(item, dict) and isinstance(item.get("code"), str) and re.fullmatch(r"HK\.\d{5}", item["code"])
    ))
    article_id = f"EASTMONEY:{record['art_code']}"
    metadata = {
        "publication_date": body_product.get("publication_date") or str(record["display_time"])[:10],
        "title": record.get("title") or "CANNOT_CONFIRM",
        "issuer_name": "；".join(names) if names else "CANNOT_CONFIRM",
        "symbol": valid_codes[0] if len(valid_codes) == 1 else "CANNOT_CONFIRM",
        "observed_at": (record.get("listing_source_ref") or {}).get("available_at"),
        "available_at": body_product.get("available_at"),
        "pit_status": "CANNOT_CONFIRM",
        "pit_reason": None,
        "source_origins": origins,
        "source_issuer_codes": codes,
        "source_issuer_membership": triage.get("issuer_membership", []),
        "article_membership_status": triage.get("article_membership_status", "CANNOT_CONFIRM"),
        "source_scope": record.get("source_scope"),
        "source_display_time": record.get("display_time"),
        "first_hkex_publication_time": record.get("first_hkex_publication_time", "CANNOT_CONFIRM"),
        "triage_route": triage.get("route"),
    }
    article = {
        "article_id": article_id,
        "source_sha256": record["source_sha256"],
        "body_sha256": record["body_text_sha256"],
        "article_body": record["body_text"],
        "article_metadata": metadata,
    }
    unit_map = runner.build_source_unit_map(article["article_body"], article["body_sha256"])
    ledger = runner.simple_fixed_facts.extract_fixed_facts(article["article_body"], unit_map, metadata)
    article["fixed_fact_ledger"] = ledger
    return article, {"unit_map": unit_map, "ledger": ledger}


def _recent_day_system_prompt(contract: Any, workflow_profile: str | None = None) -> str:
    import batch_runner as runner

    workflow_profile = workflow_profile or runner.SIMPLE_WORKFLOW_PROFILE
    if workflow_profile not in {runner.SIMPLE_WORKFLOW_PROFILE, runner.SIMPLE_WORKFLOW_RANGE_PROFILE}:
        raise RuntimeError("RECENT_DAY_WORKFLOW_PROFILE_UNSUPPORTED")
    prompt = runner.build_system_prompt(contract, workflow_profile)
    if workflow_profile == runner.SIMPLE_WORKFLOW_RANGE_PROFILE:
        return prompt
    old_role = "- wire JSON 中 facts 和 changes 必须都输出空数组；程序会在保存原始模型响应后，从冻结账本生成这两个最终字段及精确引文。模型负责经营/业绩判断，不重新生成固定事实字段。reason 可引用账本 record_id；若为解释经营含义而提及已核验的名称、期间、数量或状态，必须与正文及账本一致，不得改值或把不同关系合并成一个无完整依据的事实 claim。模型响应的判断字段由程序原样保留。"
    new_role = (
        "- wire JSON 中 facts 必须输出空数组；程序会在保存原始模型响应后，从冻结账本注入固定事实和比例及其精确引文。changes 由你根据完整正文填写经营/业绩变化，所有 claim 必须由所引 source_unit_id 支持；程序仅将该引用投影成原文 quote 和 locator，不替你生成、删除或改写 changes。其余判断字段由程序保持模型原样。"
        if workflow_profile == runner.SIMPLE_WORKFLOW_PROFILE
        else "- wire JSON 中 facts 必须输出空数组；程序会在保存原始模型响应后，从冻结账本注入固定事实和比例及其精确引文。changes 由你根据完整正文填写经营/业绩变化，每条 claim 使用 start_source_unit_id/end_source_unit_id 标记完整连续正文范围；程序只投影该范围，不替你生成、删除或改写 changes。其余判断字段由程序保持模型原样。"
    )
    old_output = "facts 和 changes 均为 []；action=lookup 时 reader_output=null。source_sha256 和 body_sha256 是必填字符串；本轮输入没有提供哈希值，请填空字符串，程序会从冻结队列注入精确值。"
    new_output = "facts 为 []（程序将注入固定事实与比例）；changes 按正文披露填写模型经营/业绩判断，没有有据变化时留空。action=lookup 时 reader_output=null。source_sha256 和 body_sha256 是必填字符串；本轮输入没有提供哈希值，请填空字符串，程序会从冻结队列注入精确值。"
    if prompt.count(old_role) != 1 or prompt.count(old_output) != 1:
        raise RuntimeError("TEMPORARY_PROMPT_REBIND_SOURCE_DRIFT")
    prompt = prompt.replace(old_role, new_role, 1).replace(old_output, new_output, 1)
    if "facts 和 changes 均为 []" in prompt or "changes 必须都输出空数组" in prompt:
        raise RuntimeError("TEMPORARY_PROMPT_CONTRADICTORY_ROLE_RULE")
    return prompt


def _messages_for_article(
    article: dict[str, Any],
    contract: Any,
    system_prompt: str,
    workflow_profile: str | None = None,
) -> list[dict[str, str]]:
    import batch_runner as runner
    import build_length_canary as length_canary

    batch = length_canary.make_batch([article], "RECENT_DAY_" + _sha(article["article_id"].encode("utf-8"))[:16])
    messages = runner.build_messages(batch, contract, workflow_profile or runner.SIMPLE_WORKFLOW_PROFILE)
    messages[0]["content"] = system_prompt
    return messages


def _token_count(tokenizer: Any, messages: list[dict[str, str]]) -> int:
    encoded = tokenizer.apply_chat_template(messages, tools=[], tokenize=True, add_generation_prompt=True)
    try:
        encoded = encoded.get("input_ids")
    except AttributeError:
        try:
            encoded = encoded["input_ids"]
        except (KeyError, TypeError, IndexError):
            pass
    if isinstance(encoded, list) and encoded and isinstance(encoded[0], list):
        encoded = encoded[0]
    if not isinstance(encoded, (list, tuple)):
        raise RuntimeError("TOKENIZER_CHAT_TEMPLATE_COUNT_INVALID")
    return len(encoded)


def prepare_172() -> dict[str, Any]:
    """Freeze all retained complete source bodies and a zero-attempt queue."""
    import automatic_canary_server as canary
    import announcement_queue as queue_module
    import batch_runner as runner
    import build_length_canary as length_canary
    from transformers import AutoTokenizer

    started = time.monotonic()
    record_by_id, _triage_by_id, triage_manifest = _load_frozen_candidate_rows()
    records_sha = _sha(RECORDS_PATH.read_bytes())
    triage_sha = _sha(TRIAGE_PATH.read_bytes())
    contract = runner.load_active_contract()
    system_prompt = _recent_day_system_prompt(contract)
    prompt_sha = _sha(system_prompt.encode("utf-8"))
    structured_schema = runner.build_simple_workflow_schema(contract)
    schema_sha = _sha(_canonical_bytes(structured_schema))
    reader_schema_sha = _sha(_canonical_bytes(contract.reader_schema))
    wire_reader_schema_sha = _sha(_canonical_bytes(runner.build_simple_reader_wire_schema(contract)))
    parser_path = Path(runner.simple_fixed_facts.__file__).resolve()
    parser_sha = _sha(parser_path.read_bytes())
    sampling_policy = canary._verified_simple_workflow_sampling_policy()
    if canary.SIMPLE_WORKFLOW_REQUEST_TEMPERATURE != 0.0 or sampling_policy.get("request_temperature") != 0.0:
        raise RuntimeError("REQUEST_TEMPERATURE_NOT_ZERO")
    if sampling_policy.get("temperature_zero_sampler") != "installed oMLX sampler selects argmax when temperature == 0":
        raise RuntimeError("TEMPERATURE_ZERO_SAMPLER_UNVERIFIED")
    tokenizer = AutoTokenizer.from_pretrained(
        str(runner.OMLX_TOKENIZER_PATH), local_files_only=True, trust_remote_code=False, use_fast=True
    )
    runtime_limits = runner.load_runtime_limits()
    settings_sha = _sha(runner.OMLX_SETTINGS_PATH.read_bytes())
    model_settings_sha = _sha(runner.OMLX_MODEL_SETTINGS_PATH.read_bytes())
    config_material = {
        "model_id": runner.MODEL_ID,
        "request_temperature": 0.0,
        "enable_thinking": False,
        "request_schema_sha256": schema_sha,
        "runtime_settings_sha256": settings_sha,
        "model_settings_sha256": model_settings_sha,
        "runtime_limits": runtime_limits,
        "max_completion_tokens": canary.MAX_COMPLETION_TOKENS,
        "request_policy": sampling_policy,
    }
    config_sha = _sha(_canonical_bytes(config_material))
    retain_triage = [item for item in triage_manifest["article_triage"] if item["route"].startswith("RETAIN_")]
    capture_cache: dict[str, dict[str, Any]] = {}
    page_cache: dict[str, dict[str, Any]] = {}
    articles: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    preflight: list[dict[str, Any]] = []
    for item in retain_triage:
        record = record_by_id[item["art_code"]]
        article, derived = _article_for_record(record, item, capture_cache, page_cache)
        unit_map, ledger = derived["unit_map"], derived["ledger"]
        messages = _messages_for_article(article, contract, system_prompt)
        prompt_tokens = _token_count(tokenizer, messages)
        body_bytes = len(article["article_body"].encode("utf-8"))
        unit_map_sha = unit_map["source_unit_map_sha256"]
        context_admission = "INPUT_FITS" if prompt_tokens <= runtime_limits["context_limit_tokens"] else "INPUT_EXCEEDS_CONTEXT"
        execution_admission = "DIRECT_SINGLE_REQUEST" if context_admission == "INPUT_FITS" else "AWAITING_FULL_BODY_CHUNKING"
        articles.append(article)
        preflight.append({
            "article_id": article["article_id"],
            "art_code": item["art_code"],
            "triage_route": item["route"],
            "title": item["title"],
            "source_sha256": article["source_sha256"],
            "body_sha256": article["body_sha256"],
            "body_length_bytes": body_bytes,
            "source_unit_map_sha256": unit_map_sha,
            "source_unit_count": len(unit_map["units"]),
            "fixed_fact_parser_protocol": ledger["protocol"],
            "fixed_fact_parser_sha256": parser_sha,
            "fixed_fact_ledger_sha256": ledger["ledger_sha256"],
            "fixed_fact_record_count": len(ledger["records"]),
            "fixed_fact_unknown_count": len(ledger["unknowns"]),
            "injected_reader_fact_count": len(ledger["reader_facts"]),
            "model_owned_changes": True,
            "prompt_tokens_exact": prompt_tokens,
            "context_limit_tokens": runtime_limits["context_limit_tokens"],
            "context_admission": context_admission,
            "execution_admission": execution_admission,
            "source_origins": article["article_metadata"]["source_origins"],
            "membership_status": item["article_membership_status"],
            "issuer_expansion": item["issuer_expansion"],
            "first_hkex_publication_time": record.get("first_hkex_publication_time", "CANNOT_CONFIRM"),
        })
        one_batch = length_canary.make_batch([article], "RECENT_DAY_" + _sha(article["article_id"].encode("utf-8"))[:16])
        payloads.append({
            **{name: article[name] for name in ("article_id", "source_sha256", "body_sha256", "article_body", "article_metadata", "fixed_fact_ledger")},
            "source_unit_map_sha256": unit_map_sha,
            "source_unit_map": unit_map,
            "date": article["article_metadata"]["publication_date"],
            "market": "HK",
            "prompt_sha256": prompt_sha,
            "model_id": runner.MODEL_ID,
            "configuration_sha256": config_sha,
            "rules": f"recent_day_reader_v1+unit-map:{unit_map_sha}+fixed-ledger:{ledger['ledger_sha256']}+schema:{schema_sha}+temperature:0.0+thinking:off",
            "role": "announcement_reader",
            "stage": "recent_day_20261014_flash_review",
            "messages": messages,
            "structured_output_schema": structured_schema,
            "validated_article_batch": one_batch,
            "prompt_tokens_exact": prompt_tokens,
            "context_limit_tokens": runtime_limits["context_limit_tokens"],
            "context_admission": context_admission,
            "execution_admission": execution_admission,
        })

    # The existing queue selects the smallest full body first; preserve that
    # deterministic scheduler order while retaining every original body.
    order = sorted(range(len(payloads)), key=lambda idx: (len(payloads[idx]["article_body"].encode("utf-8")), payloads[idx]["article_id"]))
    articles = [articles[index] for index in order]
    payloads = [payloads[index] for index in order]
    preflight = [preflight[index] for index in order]
    batch_id = "RECENT_DAY_20261014_" + _sha(_canonical_bytes([(a["article_id"], a["source_sha256"], a["body_sha256"]) for a in articles]))[:20]
    full_batch = length_canary.make_batch(articles, batch_id)
    identity_material = {
        "article_source_bodies": [(row["article_id"], row["source_sha256"], row["body_sha256"]) for row in preflight],
        "prompt_sha256": prompt_sha,
        "schema_sha256": schema_sha,
        "configuration_sha256": config_sha,
        "parser_sha256": parser_sha,
        "records_sha256": records_sha,
        "triage_sha256": triage_sha,
    }
    candidate_id = _sha(_canonical_bytes(identity_material))[:20]
    queue_id = f"recent-day-20261014-172-{candidate_id}"
    queue_root = CANDIDATE_ROOT / "queue-state" / queue_id
    existing_state_path = queue_root / "queue-state.json"
    if existing_state_path.exists():
        prior = _read_json(existing_state_path)
        if any(item.get("attempt_count", 0) != 0 or item.get("status") != "PENDING" for item in prior.get("jobs", {}).values()):
            raise RuntimeError("CANDIDATE_QUEUE_ALREADY_HAS_ATTEMPTS")
    queue = queue_module.SerialAnnouncementQueue(queue_root, queue_id, runner.MODEL_ID, max_attempts=canary.MAX_ATTEMPTS)
    queue.enqueue_many(payloads)
    snapshot = queue.snapshot()
    if len(snapshot["items"]) != 172 or any(item["attempt_count"] != 0 or item["status"] != "PENDING" for item in snapshot["items"]):
        raise RuntimeError("ZERO_ATTEMPT_QUEUE_INVALID")
    elapsed = round(time.monotonic() - started, 6)
    queue_receipt = {
        "schema": "recent_day_flash_queue_zero_attempt.v1",
        "queue_id": queue_id,
        "model_id": runner.MODEL_ID,
        "article_count": len(snapshot["items"]),
        "counts": snapshot["status_counts"],
        "direct_single_request_count": sum(row["execution_admission"] == "DIRECT_SINGLE_REQUEST" for row in preflight),
        "awaiting_full_body_chunking_count": sum(row["execution_admission"] == "AWAITING_FULL_BODY_CHUNKING" for row in preflight),
        "attempt_count_total": sum(item["attempt_count"] for item in snapshot["items"]),
        "items": [
            {"article_id": item["identity"]["article_id"], "idempotency_key": item["idempotency_key"], "status": item["status"], "attempt_count": item["attempt_count"], "body_length_bytes": item["body_length_bytes"], "source_sha256": item["identity"]["source_sha256"], "body_sha256": item["identity"]["body_sha256"], "execution_admission": next(row["execution_admission"] for row in preflight if row["article_id"] == item["identity"]["article_id"])}
            for item in snapshot["items"]
        ],
    }
    queue_raw = json.dumps(queue_receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    batch_raw = json.dumps(full_batch, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _write_immutable(CANDIDATE_ROOT / "zero-attempt-queue.json", queue_raw)
    _write_immutable(CANDIDATE_ROOT / "validated-batch.json", batch_raw)
    low_ids = [item["art_code"] for item in triage_manifest["article_triage"] if item["route"].startswith("LOW_PRIORITY_")]
    exception_ids = [item["art_code"] for item in triage_manifest["article_triage"] if item["route"].startswith("UNKNOWN_")]
    manifest = {
        "schema": "recent_day_flash_172_candidate.v1",
        "candidate_id": candidate_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "purpose": "临时 research-only Flash 深读候选冻结；不改变 canonical V4，不形成 BUY/交易信号。",
        "source_window": {"left_inclusive": LEFT.isoformat(), "right_exclusive": RIGHT.isoformat(), "filter_field": "display_time", "timezone": "Asia/Shanghai", "official_hkex_first_publication_time": "CANNOT_CONFIRM when absent", "pit_status": "CANNOT_CONFIRM"},
        "source_inputs": {"source_window_records_path": str(RECORDS_PATH), "source_window_records_sha256": records_sha, "triage_manifest_path": str(TRIAGE_PATH), "triage_manifest_sha256": triage_sha, "capture_products": triage_manifest.get("capture_products"), "monthly_connect_membership": triage_manifest.get("connect_membership")},
        "counts": {
            "window_unique_art_code": 340,
            "issuer_expansions": 345,
            "queued_complete_articles": 172,
            "direct_single_request_articles": sum(row["execution_admission"] == "DIRECT_SINGLE_REQUEST" for row in preflight),
            "awaiting_full_body_chunking_articles": sum(row["execution_admission"] == "AWAITING_FULL_BODY_CHUNKING" for row in preflight),
            "isolated_low_priority_articles": len(low_ids),
            "body_or_source_exception_articles": len(exception_ids),
            "queued_operating_route": sum(row["triage_route"] == "RETAIN_POTENTIAL_OPERATING_RESEARCH" for row in preflight),
            "queued_risk_route": sum(row["triage_route"] == "RETAIN_RISK_REVIEW" for row in preflight),
            "queued_corporate_action_route": sum(row["triage_route"] == "RETAIN_CORPORATE_ACTION_REVIEW" for row in preflight),
            "queued_unclassified_route": sum(row["triage_route"] == "RETAIN_UNCLASSIFIED_REVIEW" for row in preflight),
            "official_first_publication_time_cannot_confirm": 172,
            "membership_is_metadata_only": True,
        },
        "isolated_ids": {"low_priority": low_ids, "body_or_source_exceptions": exception_ids},
        "queue": {"queue_id": queue_id, "state_root": str(queue_root), "zero_attempt_queue_path": str(CANDIDATE_ROOT / "zero-attempt-queue.json"), "zero_attempt_queue_sha256": _sha(queue_raw), "validated_batch_path": str(CANDIDATE_ROOT / "validated-batch.json"), "validated_batch_sha256": _sha(batch_raw), "attempts_at_freeze": 0, "max_attempts": canary.MAX_ATTEMPTS, "body_truncation": False, "scheduler": "existing SerialAnnouncementQueue; ascending UTF-8 body bytes; single worker"},
        "model_request_policy": {
            "model_id": runner.MODEL_ID,
            "workflow_profile": runner.SIMPLE_WORKFLOW_PROFILE,
            "request_temperature": 0.0,
            "enable_thinking": False,
            "sampling_policy": sampling_policy,
            "sampling_policy_sha256": _sha(_canonical_bytes(sampling_policy)),
            "native_structured_output": True,
            "native_model_tools": False,
            "structured_output_schema_sha256": schema_sha,
            "reader_schema_sha256": reader_schema_sha,
            "wire_reader_schema_sha256": wire_reader_schema_sha,
            "schema_unchanged_from_active_contract": True,
            "system_prompt_sha256": prompt_sha,
            "prompt_source_sha256": _sha(runner.SIMPLE_WORKFLOW_PROMPT.encode("utf-8")),
            "prompt_adaptation": "temporary role split: program injects fixed facts; model authors changes; source-unit references are projected to exact quotes/locators",
            "fixed_fact_parser_protocol": runner.simple_fixed_facts.PROTOCOL,
            "fixed_fact_parser_sha256": parser_sha,
            "runtime_settings_sha256": settings_sha,
            "model_settings_sha256": model_settings_sha,
            "configuration_sha256": config_sha,
            "runtime_limits": runtime_limits,
            "max_completion_tokens": canary.MAX_COMPLETION_TOKENS,
        },
        "preflight": {
            "script_wall_seconds": elapsed,
            "prompt_tokenizer_loaded_locally": True,
            "model_weights_loaded": False,
            "context_unfit_ids": [row["article_id"] for row in preflight if row["context_admission"] != "INPUT_FITS"],
            "direct_eligible_ids": [row["article_id"] for row in preflight if row["execution_admission"] == "DIRECT_SINGLE_REQUEST"],
            "awaiting_full_body_chunking_ids": [row["article_id"] for row in preflight if row["execution_admission"] == "AWAITING_FULL_BODY_CHUNKING"],
            "queue_order": [row["article_id"] for row in preflight],
        },
        "articles": preflight,
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "model_called": False, "ui_started": False, "source_fetch_performed_by_helper": False},
    }
    manifest_raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _write_immutable(CANDIDATE_ROOT / "candidate-manifest.json", manifest_raw)
    _write_immutable(CANDIDATE_ROOT / "candidate-manifest.sha256", (_sha(manifest_raw) + "\n").encode("ascii"))
    return {"candidate_root": str(CANDIDATE_ROOT), "manifest_path": str(CANDIDATE_ROOT / "candidate-manifest.json"), "manifest_sha256": _sha(manifest_raw), "queue_id": queue_id, "counts": manifest["counts"], "preflight_script_wall_seconds": elapsed, "context_unfit_ids": manifest["preflight"]["context_unfit_ids"], "direct_single_request_count": manifest["counts"]["direct_single_request_articles"], "awaiting_full_body_chunking_count": manifest["counts"]["awaiting_full_body_chunking_articles"], "model_called": False}


def _guoen_targeted_request_material(contract: Any, *, range_profile: bool = False) -> dict[str, Any]:
    import automatic_canary_server as canary
    import importlib
    import batch_runner as runner

    runner.simple_fixed_facts = importlib.reload(runner.simple_fixed_facts)
    parser_path = Path(runner.simple_fixed_facts.__file__).resolve()
    if parser_path != (PIPELINE_DIR / "simple_fixed_facts.py").resolve():
        raise RuntimeError("GUOEN_TARGETED_PARSER_PATH_MISMATCH")
    canonical_path_sha = _sha(runner.V4_ANNOUNCEMENT_SOURCE.read_bytes())
    if contract.source_sha256 != canonical_path_sha:
        raise RuntimeError("GUOEN_TARGETED_CANONICAL_CONTRACT_CHANGED")
    workflow_profile = runner.SIMPLE_WORKFLOW_RANGE_PROFILE if range_profile else runner.SIMPLE_WORKFLOW_PROFILE
    citation_protocol = (
        runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL
        if range_profile
        else runner.SIMPLE_WORKFLOW_SINGLE_CITATION_PROTOCOL
    )
    prompt = _recent_day_system_prompt(contract, workflow_profile)
    schema = runner.build_simple_workflow_schema(contract, citation_protocol)
    sampling_policy = canary._verified_simple_workflow_sampling_policy()
    runtime_limits = runner.load_runtime_limits()
    settings_sha = _sha(runner.OMLX_SETTINGS_PATH.read_bytes())
    model_settings_sha = _sha(runner.OMLX_MODEL_SETTINGS_PATH.read_bytes())
    parser_sha = _sha(parser_path.read_bytes())
    material = {
        "model_id": runner.MODEL_ID,
        "request_temperature": 0.0,
        "enable_thinking": False,
        "request_schema_sha256": _sha(_canonical_bytes(schema)),
        "request_schema_wrapper_sha256": _sha(_canonical_bytes({"json": schema})),
        "runtime_settings_sha256": settings_sha,
        "model_settings_sha256": model_settings_sha,
        "runtime_limits": runtime_limits,
        "max_completion_tokens": canary.MAX_COMPLETION_TOKENS,
        "request_policy": sampling_policy,
    }
    return {
        "workflow_profile": workflow_profile,
        "citation_protocol": citation_protocol,
        "range_profile": range_profile,
        "prompt": prompt,
        "prompt_sha256": _sha(prompt.encode("utf-8")),
        "schema": schema,
        "schema_sha256": material["request_schema_sha256"],
        "schema_wrapper_sha256": material["request_schema_wrapper_sha256"],
        "reader_schema_sha256": _sha(_canonical_bytes(contract.reader_schema)),
        "wire_reader_schema_sha256": _sha(_canonical_bytes(runner.build_simple_reader_wire_schema(contract, citation_protocol))),
        "sampling_policy": sampling_policy,
        "sampling_policy_sha256": _sha(_canonical_bytes(sampling_policy)),
        "runtime_limits": runtime_limits,
        "runtime_settings_sha256": settings_sha,
        "model_settings_sha256": model_settings_sha,
        "configuration_material": material,
        "configuration_sha256": _sha(_canonical_bytes(material)),
        "parser_protocol": runner.simple_fixed_facts.PROTOCOL,
        "parser_sha256": parser_sha,
        "canonical_contract_sha256": canonical_path_sha,
        "source_code_sha256": (
            {
                "batch_runner.py": _sha((PIPELINE_DIR / "batch_runner.py").read_bytes()),
                "automatic_canary_server.py": _sha((PIPELINE_DIR / "automatic_canary_server.py").read_bytes()),
                "recent_day_freeze.py": _sha(Path(__file__).read_bytes()),
            }
            if range_profile
            else None
        ),
    }


def _validate_guoen_targeted_live_binding(manifest: dict[str, Any], contract: Any) -> None:
    """Fail closed unless this process has the exact code and request contract frozen by the candidate."""
    import batch_runner as runner

    expected = manifest.get("model_request_policy")
    if not isinstance(expected, dict):
        raise RuntimeError("GUOEN_TARGETED_REQUEST_POLICY_MISSING")
    range_profile = manifest.get("schema") == GUOEN_TARGETED_RANGE_SCHEMA
    actual = _guoen_targeted_request_material(contract, range_profile=range_profile)
    comparisons = {
        "model_id": runner.MODEL_ID,
        "workflow_profile": actual["workflow_profile"],
        "request_temperature": 0.0,
        "enable_thinking": False,
        "sampling_policy": actual["sampling_policy"],
        "sampling_policy_sha256": actual["sampling_policy_sha256"],
        "structured_output_schema_sha256": actual["schema_sha256"],
        "reader_schema_sha256": actual["reader_schema_sha256"],
        "wire_reader_schema_sha256": actual["wire_reader_schema_sha256"],
        "system_prompt_sha256": actual["prompt_sha256"],
        "prompt_source_sha256": _sha(runner.SIMPLE_WORKFLOW_PROMPT.encode("utf-8")),
        "fixed_fact_parser_protocol": actual["parser_protocol"],
        "fixed_fact_parser_sha256": actual["parser_sha256"],
        "canonical_contract_source_sha256": actual["canonical_contract_sha256"],
        "runtime_settings_sha256": actual["runtime_settings_sha256"],
        "model_settings_sha256": actual["model_settings_sha256"],
        "configuration_sha256": actual["configuration_sha256"],
        "runtime_limits": actual["runtime_limits"],
        "max_completion_tokens": actual["configuration_material"]["max_completion_tokens"],
    }
    if range_profile:
        comparisons["structured_output_schema_inner_sha256"] = actual["schema_sha256"]
        comparisons["structured_output_schema_wrapper_sha256"] = actual["schema_wrapper_sha256"]
        comparisons["citation_protocol"] = actual["citation_protocol"]
        comparisons["source_code_sha256"] = actual["source_code_sha256"]
        comparisons["request_settings_sha256_provenance"] = "candidate_prepare_local_disk_readback"
        comparisons["active_server_memory_settings"] = "CANNOT_CONFIRM"
    for field, value in comparisons.items():
        if expected.get(field) != value:
            raise RuntimeError(f"GUOEN_TARGETED_LIVE_BINDING_MISMATCH:{field}")
    if expected.get("schema_unchanged_from_active_contract") is not True:
        raise RuntimeError("GUOEN_TARGETED_SCHEMA_GATE_INVALID")


def _validate_guoen_targeted_candidate_files(root: Path, manifest: dict[str, Any], queue: Any, contract: Any) -> None:
    import batch_runner as runner

    range_profile = manifest.get("schema") == GUOEN_TARGETED_RANGE_SCHEMA
    workflow_profile = runner.SIMPLE_WORKFLOW_RANGE_PROFILE if range_profile else runner.SIMPLE_WORKFLOW_PROFILE
    citation_protocol = (
        runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL
        if range_profile
        else runner.SIMPLE_WORKFLOW_SINGLE_CITATION_PROTOCOL
    )
    expected_schema = runner.build_simple_workflow_schema(contract, citation_protocol)
    queue_meta = manifest.get("queue")
    if (
        manifest.get("schema") not in {GUOEN_TARGETED_SCHEMA, GUOEN_TARGETED_RANGE_SCHEMA}
        or manifest.get("candidate_kind") != "guoen_targeted_two_article_rerun"
        or manifest.get("counts", {}).get("target_article_count") != 2
        or not isinstance(queue_meta, dict)
        or queue_meta.get("max_attempts") != 1
        or queue.max_attempts != 1
        or queue.model_id != runner.MODEL_ID
    ):
        raise RuntimeError("GUOEN_TARGETED_QUEUE_POLICY_INVALID")
    if queue_meta.get("queue_id") != queue.queue_id:
        raise RuntimeError("GUOEN_TARGETED_QUEUE_ID_MISMATCH")
    expected_root = (root / "queue-state" / queue_meta["queue_id"]).resolve()
    if Path(queue_meta.get("state_root", "")).resolve() != expected_root:
        raise RuntimeError("GUOEN_TARGETED_QUEUE_ROOT_OUTSIDE_CANDIDATE")
    batch_path = Path(queue_meta.get("validated_batch_path", "")).resolve()
    if batch_path != (root / "validated-batch.json").resolve():
        raise RuntimeError("GUOEN_TARGETED_BATCH_PATH_OUTSIDE_CANDIDATE")
    batch_raw = batch_path.read_bytes()
    if _sha(batch_raw) != queue_meta.get("validated_batch_sha256"):
        raise RuntimeError("GUOEN_TARGETED_BATCH_SHA_MISMATCH")
    batch = json.loads(batch_raw)
    articles = batch.get("articles")
    expected_ids = list(manifest.get("target_article_ids") or [])
    if batch.get("expected_count") != 2 or not isinstance(articles, list) or len(articles) != 2:
        raise RuntimeError("GUOEN_TARGETED_BATCH_COUNT_INVALID")
    if [article.get("article_id") for article in articles] != expected_ids or set(expected_ids) != set(GUOEN_TARGETED_IDS):
        raise RuntimeError("GUOEN_TARGETED_BATCH_IDENTITY_MISMATCH")
    meta_by_id = {row.get("article_id"): row for row in manifest.get("articles", []) if isinstance(row, dict)}
    if set(meta_by_id) != set(expected_ids):
        raise RuntimeError("GUOEN_TARGETED_MANIFEST_IDENTITY_MISMATCH")
    for article in articles:
        article_id = article["article_id"]
        frozen = GUOEN_TARGETED_SOURCE_SHAS[article_id]
        metadata = article.get("article_metadata")
        row = meta_by_id[article_id]
        if (
            article.get("source_sha256") != frozen["source_sha256"]
            or article.get("body_sha256") != frozen["body_sha256"]
            or _sha(article.get("article_body", "").encode("utf-8")) != frozen["body_sha256"]
            or not isinstance(metadata, dict)
            or _sha(_canonical_bytes(metadata)) != row.get("article_metadata_sha256")
        ):
            raise RuntimeError(f"GUOEN_TARGETED_SOURCE_BINDING_MISMATCH:{article_id}")
        unit_map = runner.build_source_unit_map(article["article_body"], article["body_sha256"])
        ledger = runner.simple_fixed_facts.extract_fixed_facts(article["article_body"], unit_map, metadata)
        if article.get("fixed_fact_ledger") != ledger or ledger.get("ledger_sha256") != row.get("fixed_fact_ledger_sha256"):
            raise RuntimeError(f"GUOEN_TARGETED_FIXED_LEDGER_MISMATCH:{article_id}")
        if unit_map.get("source_unit_map_sha256") != row.get("source_unit_map_sha256"):
            raise RuntimeError(f"GUOEN_TARGETED_SOURCE_UNIT_MAP_MISMATCH:{article_id}")
        runner._simple_fixed_fact_ledger(article, unit_map)
    state = json.loads(queue.state_path.read_bytes())
    queued_jobs = [job for job in state.get("jobs", {}).values() if queue.queue_id in job.get("queue_ids", [job.get("queue_id")]) and job.get("model_id") == queue.model_id]
    if len(queued_jobs) != 2 or {job.get("identity", {}).get("article_id") for job in queued_jobs} != set(expected_ids):
        raise RuntimeError("GUOEN_TARGETED_QUEUE_ITEMS_INVALID")
    article_by_id = {article["article_id"]: article for article in articles}
    for job in queued_jobs:
        article_id = job["identity"]["article_id"]
        if job.get("max_attempts") != 1 or job.get("attempt_count", 0) > 1:
            raise RuntimeError("GUOEN_TARGETED_QUEUE_ATTEMPT_POLICY_INVALID")
        input_path = (queue.state_root / job["input_path"]).resolve()
        if not input_path.is_relative_to(queue.state_root.resolve()):
            raise RuntimeError("GUOEN_TARGETED_QUEUE_INPUT_OUTSIDE_ROOT")
        payload_raw = input_path.read_bytes()
        payload = json.loads(payload_raw)
        article = article_by_id[article_id]
        row = meta_by_id[article_id]
        expected_messages = _messages_for_article(
            article,
            contract,
            _recent_day_system_prompt(contract, workflow_profile),
            workflow_profile,
        )
        queued_messages = payload.get("messages")
        messages_match = (
            isinstance(queued_messages, list)
            and len(queued_messages) == 2
            and [item.get("role") for item in queued_messages if isinstance(item, dict)] == ["system", "user"]
            and queued_messages[0].get("content") == expected_messages[0].get("content")
        )
        if messages_match:
            prefix, suffix = "ARTICLE_DATA_BEGIN\n", "\nARTICLE_DATA_END"
            queued_user = queued_messages[1].get("content")
            expected_user = expected_messages[1].get("content")
            try:
                messages_match = (
                    isinstance(queued_user, str)
                    and isinstance(expected_user, str)
                    and queued_user.startswith(prefix)
                    and queued_user.endswith(suffix)
                    and expected_user.startswith(prefix)
                    and expected_user.endswith(suffix)
                    and json.loads(queued_user[len(prefix):-len(suffix)]) == json.loads(expected_user[len(prefix):-len(suffix)])
                )
            except Exception:
                messages_match = False
        payload_mismatches = []
        if job.get("payload_sha256") != _sha(_canonical_bytes(payload)):
            payload_mismatches.append("payload_sha256")
        payload_mismatches.extend(key for key in ("article_id", "source_sha256", "body_sha256", "article_body", "article_metadata", "fixed_fact_ledger") if payload.get(key) != article.get(key))
        if payload.get("model_id") != runner.MODEL_ID:
            payload_mismatches.append("model_id")
        if payload.get("prompt_sha256") != manifest["model_request_policy"].get("system_prompt_sha256"):
            payload_mismatches.append("prompt_sha256")
        if payload.get("configuration_sha256") != manifest["model_request_policy"].get("configuration_sha256"):
            payload_mismatches.append("configuration_sha256")
        if not messages_match:
            payload_mismatches.append("messages")
        if payload.get("structured_output_schema") != expected_schema:
            payload_mismatches.append("structured_output_schema")
        if range_profile:
            if payload.get("workflow_profile") != workflow_profile:
                payload_mismatches.append("workflow_profile")
            if payload.get("citation_protocol") != citation_protocol:
                payload_mismatches.append("citation_protocol")
        if payload.get("execution_admission") != row.get("execution_admission"):
            payload_mismatches.append("execution_admission")
        if payload_mismatches:
            raise RuntimeError(f"GUOEN_TARGETED_QUEUE_PAYLOAD_MISMATCH:{article_id}:{','.join(payload_mismatches)}")
    snap = queue.snapshot()
    if snap.get("total") != 2 or {row["identity"].get("article_id") for row in snap["items"]} != set(expected_ids):
        raise RuntimeError("GUOEN_TARGETED_QUEUE_SNAPSHOT_INVALID")


def prepare_guoen_targeted(candidate_root: Path, *, range_profile: bool = False) -> dict[str, Any]:
    """Prepare a new, isolated two-notice queue from the previously frozen source batch."""
    import automatic_canary_server as canary
    import announcement_queue as queue_module
    import batch_runner as runner
    import build_length_canary as length_canary
    from transformers import AutoTokenizer

    started = time.monotonic()
    root = candidate_root.expanduser().resolve()
    allowed_root = (
        GUOEN_TARGETED_RANGE_CANDIDATE_ROOT.resolve()
        if range_profile
        else GUOEN_TARGETED_EVIDENCE_ROOT.resolve()
    )
    if root == allowed_root or not root.is_relative_to(allowed_root):
        raise RuntimeError("GUOEN_TARGETED_CANDIDATE_ROOT_OUTSIDE_EVIDENCE")
    if root.exists():
        raise RuntimeError("GUOEN_TARGETED_CANDIDATE_ROOT_ALREADY_EXISTS")

    source_manifest_path = GUOEN_TARGETED_SOURCE_ROOT / "candidate-manifest.json"
    source_batch_path = GUOEN_TARGETED_SOURCE_ROOT / "validated-batch.json"
    source_manifest_raw = source_manifest_path.read_bytes()
    source_batch_raw = source_batch_path.read_bytes()
    source_manifest_sha = _sha(source_manifest_raw)
    source_batch_sha = _sha(source_batch_raw)
    if source_manifest_sha != GUOEN_TARGETED_SOURCE_MANIFEST_SHA256 or source_batch_sha != GUOEN_TARGETED_SOURCE_BATCH_SHA256:
        raise RuntimeError("GUOEN_TARGETED_SOURCE_CANDIDATE_SHA_MISMATCH")
    source_manifest = json.loads(source_manifest_raw)
    source_manifest_policy = source_manifest.get("model_request_policy", {})
    source_batch = json.loads(source_batch_raw)
    source_articles = source_batch.get("articles")
    if source_batch.get("expected_count") != 172 or not isinstance(source_articles, list) or len(source_articles) != 172:
        raise RuntimeError("GUOEN_TARGETED_SOURCE_BATCH_IDENTITY_INVALID")
    source_by_id = {row.get("article_id"): row for row in source_articles if isinstance(row, dict)}
    if len(source_by_id) != 172 or not set(GUOEN_TARGETED_IDS).issubset(source_by_id):
        raise RuntimeError("GUOEN_TARGETED_SOURCE_TARGETS_MISSING")
    contract = runner.load_active_contract()
    request = _guoen_targeted_request_material(contract, range_profile=range_profile)
    workflow_profile = request["workflow_profile"]
    citation_protocol = request["citation_protocol"]
    compare_fields = {
        "model_id": runner.MODEL_ID,
        "request_temperature": 0.0,
        "enable_thinking": False,
        "sampling_policy_sha256": request["sampling_policy_sha256"],
        "runtime_limits": request["runtime_limits"],
        "max_completion_tokens": request["configuration_material"]["max_completion_tokens"],
        "model_settings_sha256": request["model_settings_sha256"],
    }
    if not range_profile:
        compare_fields.update({
            "workflow_profile": runner.SIMPLE_WORKFLOW_PROFILE,
            "structured_output_schema_sha256": request["schema_sha256"],
            "reader_schema_sha256": request["reader_schema_sha256"],
            "wire_reader_schema_sha256": request["wire_reader_schema_sha256"],
            "system_prompt_sha256": request["prompt_sha256"],
            "prompt_source_sha256": _sha(runner.SIMPLE_WORKFLOW_PROMPT.encode("utf-8")),
        })
    for field, value in compare_fields.items():
        if source_manifest_policy.get(field) != value:
            raise RuntimeError(f"GUOEN_TARGETED_FROZEN_REQUEST_POLICY_MISMATCH:{field}")
    if canary.SIMPLE_WORKFLOW_REQUEST_TEMPERATURE != 0.0 or request["sampling_policy"].get("request_temperature") != 0.0:
        raise RuntimeError("REQUEST_TEMPERATURE_NOT_ZERO")
    if request["sampling_policy"].get("temperature_zero_sampler") != "installed oMLX sampler selects argmax when temperature == 0":
        raise RuntimeError("TEMPERATURE_ZERO_SAMPLER_UNVERIFIED")
    tokenizer = AutoTokenizer.from_pretrained(
        str(runner.OMLX_TOKENIZER_PATH), local_files_only=True, trust_remote_code=False, use_fast=True
    )
    runtime_limits = request["runtime_limits"]

    triage_by_id = {row.get("article_id"): row for row in source_manifest.get("articles", []) if isinstance(row, dict)}
    articles: list[dict[str, Any]] = []
    preflight: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for article_id in GUOEN_TARGETED_IDS:
        source_article = source_by_id[article_id]
        frozen = GUOEN_TARGETED_SOURCE_SHAS[article_id]
        original_metadata = source_article.get("article_metadata")
        body = source_article.get("article_body")
        if (
            source_article.get("source_sha256") != frozen["source_sha256"]
            or source_article.get("body_sha256") != frozen["body_sha256"]
            or not isinstance(body, str)
            or _sha(body.encode("utf-8")) != frozen["body_sha256"]
            or not isinstance(original_metadata, dict)
        ):
            raise RuntimeError(f"GUOEN_TARGETED_SOURCE_ROW_INVALID:{article_id}")
        article = deepcopy(source_article)
        article["article_metadata"] = deepcopy(original_metadata)
        unit_map = runner.build_source_unit_map(article["article_body"], article["body_sha256"])
        ledger = runner.simple_fixed_facts.extract_fixed_facts(article["article_body"], unit_map, article["article_metadata"])
        article["fixed_fact_ledger"] = ledger
        messages = _messages_for_article(article, contract, request["prompt"], workflow_profile)
        prompt_tokens = _token_count(tokenizer, messages)
        body_length = len(article["article_body"].encode("utf-8"))
        unit_map_sha = unit_map["source_unit_map_sha256"]
        context_admission = "INPUT_FITS" if prompt_tokens <= runtime_limits["context_limit_tokens"] else "INPUT_EXCEEDS_CONTEXT"
        execution_admission = "DIRECT_SINGLE_REQUEST" if context_admission == "INPUT_FITS" else "AWAITING_FULL_BODY_CHUNKING"
        original_manifest_row = triage_by_id.get(article_id, {})
        metadata_sha = _sha(_canonical_bytes(original_metadata))
        articles.append(article)
        preflight.append({
            "article_id": article_id,
            "art_code": article_id.split(":", 1)[-1],
            "triage_route": original_manifest_row.get("triage_route", "CANNOT_CONFIRM"),
            "title": original_metadata.get("title"),
            "source_sha256": article["source_sha256"],
            "body_sha256": article["body_sha256"],
            "article_metadata_sha256": metadata_sha,
            "body_length_bytes": body_length,
            "source_unit_map_sha256": unit_map_sha,
            "source_unit_count": len(unit_map["units"]),
            "fixed_fact_parser_protocol": runner.simple_fixed_facts.PROTOCOL,
            "fixed_fact_parser_sha256": request["parser_sha256"],
            "fixed_fact_ledger_sha256": ledger["ledger_sha256"],
            "fixed_fact_record_count": len(ledger["records"]),
            "fixed_fact_unknown_count": len(ledger["unknowns"]),
            "injected_reader_fact_count": len(ledger["reader_facts"]),
            "model_owned_changes": True,
            "prompt_tokens_exact": prompt_tokens,
            "context_limit_tokens": runtime_limits["context_limit_tokens"],
            "context_admission": context_admission,
            "execution_admission": execution_admission,
            "source_origins": article["article_metadata"]["source_origins"],
            "membership_status": article["article_metadata"].get("article_membership_status", "CANNOT_CONFIRM"),
            "issuer_expansion": article["article_metadata"].get("source_issuer_membership", []),
            "first_hkex_publication_time": article["article_metadata"].get("first_hkex_publication_time", "CANNOT_CONFIRM"),
        })
        one_batch = length_canary.make_batch([article], "GUOEN_TARGETED_20261015_" + _sha(article_id.encode("utf-8"))[:16])
        payloads.append({
            **{name: article[name] for name in ("article_id", "source_sha256", "body_sha256", "article_body", "article_metadata", "fixed_fact_ledger")},
            "source_unit_map_sha256": unit_map_sha,
            "source_unit_map": unit_map,
            "date": article["article_metadata"]["publication_date"],
            "market": "HK",
            "prompt_sha256": request["prompt_sha256"],
            "model_id": runner.MODEL_ID,
            "configuration_sha256": request["configuration_sha256"],
            "rules": f"recent_day_reader_v2+profile:{workflow_profile}+citation:{citation_protocol}+unit-map:{unit_map_sha}+fixed-ledger:{ledger['ledger_sha256']}+schema:{request['schema_sha256']}+temperature:0.0+thinking:off",
            "role": "announcement_reader",
            "stage": "guoen_targeted_20261015_flash_rerun",
            "messages": messages,
            "structured_output_schema": request["schema"],
            "workflow_profile": workflow_profile,
            "citation_protocol": citation_protocol,
            "validated_article_batch": one_batch,
            "prompt_tokens_exact": prompt_tokens,
            "context_limit_tokens": runtime_limits["context_limit_tokens"],
            "context_admission": context_admission,
            "execution_admission": execution_admission,
        })

    order = sorted(range(2), key=lambda index: (len(articles[index]["article_body"].encode("utf-8")), articles[index]["article_id"]))
    articles = [articles[index] for index in order]
    preflight = [preflight[index] for index in order]
    payloads = [payloads[index] for index in order]
    target_ids = [row["article_id"] for row in preflight]
    source_identity = [(row["article_id"], row["source_sha256"], row["body_sha256"], row["article_metadata_sha256"]) for row in preflight]
    run_id = "guoen-live-rerun-20261015-" + secrets.token_hex(12)
    candidate_id = _sha(_canonical_bytes({
        "run_id": run_id,
        "source_identity": source_identity,
        "prompt_sha256": request["prompt_sha256"],
        "schema_sha256": request["schema_sha256"],
        "configuration_sha256": request["configuration_sha256"],
        "parser_sha256": request["parser_sha256"],
        "canonical_contract_sha256": request["canonical_contract_sha256"],
        "source_batch_sha256": source_batch_sha,
        "workflow_profile": workflow_profile,
        "citation_protocol": citation_protocol,
        "source_code_sha256": request["source_code_sha256"],
    }))[:20]
    queue_id = f"recent-day-guoen-range-v2-{candidate_id}" if range_profile else f"recent-day-guoen-20261015-{candidate_id}"
    queue_root = root / "queue-state" / queue_id
    batch_id = ("GUOEN_TARGETED_RANGE_V2_" if range_profile else "GUOEN_TARGETED_20261015_") + candidate_id
    full_batch = length_canary.make_batch(articles, batch_id)
    batch_raw = json.dumps(full_batch, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"

    # Create the run root only after all frozen input and request checks pass.
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.mkdir(mode=0o700)
    queue = queue_module.SerialAnnouncementQueue(queue_root, queue_id, runner.MODEL_ID, max_attempts=1, max_body_bytes=None)
    queue.enqueue_many(payloads)
    snapshot = queue.snapshot()
    if len(snapshot["items"]) != 2 or any(item["attempt_count"] != 0 or item["status"] != "PENDING" or item["max_attempts"] != 1 for item in snapshot["items"]):
        raise RuntimeError("GUOEN_TARGETED_ZERO_ATTEMPT_QUEUE_INVALID")
    elapsed = round(time.monotonic() - started, 6)
    zero_queue = {
        "schema": "recent_day_guoen_targeted_zero_attempt_queue.v1",
        "run_id": run_id,
        "queue_id": queue_id,
        "article_count": 2,
        "model_id": runner.MODEL_ID,
        "counts": snapshot["status_counts"],
        "attempt_count_total": 0,
        "max_attempts": 1,
        "items": [
            {"article_id": item["identity"]["article_id"], "idempotency_key": item["idempotency_key"], "status": item["status"], "attempt_count": item["attempt_count"], "max_attempts": item["max_attempts"], "source_sha256": item["identity"]["source_sha256"], "body_sha256": item["identity"]["body_sha256"], "body_length_bytes": item["body_length_bytes"]}
            for item in snapshot["items"]
        ],
    }
    zero_queue_raw = json.dumps(zero_queue, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _write_immutable(root / "validated-batch.json", batch_raw)
    _write_immutable(root / "zero-attempt-queue.json", zero_queue_raw)
    queue_receipt_path = root / "zero-attempt-queue.json"
    batch_path = root / "validated-batch.json"
    manifest = {
        "schema": GUOEN_TARGETED_RANGE_SCHEMA if range_profile else GUOEN_TARGETED_SCHEMA,
        "candidate_kind": "guoen_targeted_two_article_rerun",
        "candidate_id": candidate_id,
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "purpose": "隔离复核固定的两篇 Guoen 公告；保留原文和来源身份，不改变模型、门禁或 canonical V4。",
        "target_article_ids": target_ids,
        "source_window": source_manifest.get("source_window"),
        "source_inputs": {
            "source_candidate_root": str(GUOEN_TARGETED_SOURCE_ROOT),
            "source_candidate_manifest_sha256": source_manifest_sha,
            "source_validated_batch_path": str(source_batch_path.resolve()),
            "source_validated_batch_sha256": source_batch_sha,
            "source_copy_policy": "article_id, article_body, article_metadata, source_sha256, and body_sha256 are copied byte/value-identically; only fixed_fact_ledger is recomputed by the manifest-pinned parser",
        },
        "counts": {
            "target_article_count": 2,
            "queued_complete_articles": 2,
            "direct_single_request_articles": sum(row["execution_admission"] == "DIRECT_SINGLE_REQUEST" for row in preflight),
            "awaiting_full_body_chunking_articles": sum(row["execution_admission"] == "AWAITING_FULL_BODY_CHUNKING" for row in preflight),
            "isolated_low_priority_articles": 0,
            "body_or_source_exception_articles": 0,
            "official_first_publication_time_cannot_confirm": sum(row["first_hkex_publication_time"] == "CANNOT_CONFIRM" for row in preflight),
            "membership_is_metadata_only": True,
        },
        "queue": {
            "queue_id": queue_id,
            "state_root": str(queue_root),
            "zero_attempt_queue_path": str(queue_receipt_path),
            "zero_attempt_queue_sha256": _sha(zero_queue_raw),
            "validated_batch_path": str(batch_path),
            "validated_batch_sha256": _sha(batch_raw),
            "attempts_at_freeze": 0,
            "max_attempts": 1,
            "body_truncation": False,
            "max_concurrency": 1,
            "system_error_policy": "stop remaining requests after first system/transport/empty-response failure; no automatic retry",
            "scheduler": "existing SerialAnnouncementQueue; ascending UTF-8 body bytes; single worker",
        },
        "model_request_policy": {
            "model_id": runner.MODEL_ID,
            "workflow_profile": workflow_profile,
            "citation_protocol": citation_protocol,
            "request_temperature": 0.0,
            "enable_thinking": False,
            "sampling_policy": request["sampling_policy"],
            "sampling_policy_sha256": request["sampling_policy_sha256"],
            "native_structured_output": True,
            "native_model_tools": False,
            "structured_output_schema_sha256": request["schema_sha256"],
            "structured_output_schema_inner_sha256": request["schema_sha256"],
            "structured_output_schema_wrapper_sha256": request["schema_wrapper_sha256"],
            "reader_schema_sha256": request["reader_schema_sha256"],
            "wire_reader_schema_sha256": request["wire_reader_schema_sha256"],
            "schema_unchanged_from_active_contract": True,
            "system_prompt_sha256": request["prompt_sha256"],
            "prompt_source_sha256": _sha(runner.SIMPLE_WORKFLOW_PROMPT.encode("utf-8")),
            "prompt_adaptation": (
                "recent-day temporary role split; fixed facts are program-injected; model-authored changes use article-bound contiguous source-unit ranges projected by the shared exact-source projector"
                if range_profile
                else "same frozen recent-day temporary role split; fixed facts are program-injected; model-authored changes cite source-unit IDs projected by the existing projector"
            ),
            "fixed_fact_parser_protocol": request["parser_protocol"],
            "fixed_fact_parser_sha256": request["parser_sha256"],
            "canonical_contract_source_sha256": request["canonical_contract_sha256"],
            "runtime_settings_sha256": request["runtime_settings_sha256"],
            "request_settings_sha256_provenance": "candidate_prepare_local_disk_readback",
            "active_server_memory_settings": "CANNOT_CONFIRM",
            "model_settings_sha256": request["model_settings_sha256"],
            "source_code_sha256": request["source_code_sha256"],
            "configuration_sha256": request["configuration_sha256"],
            "runtime_limits": runtime_limits,
            "max_completion_tokens": request["configuration_material"]["max_completion_tokens"],
            "frozen_source_request_policy_matches": not range_profile,
            "frozen_source_sampling_runtime_limits_model_settings_compatible": True,
            "runtime_settings_sha_changed_from_source_candidate": source_manifest_policy.get("runtime_settings_sha256") != request["runtime_settings_sha256"],
        },
        "preflight": {
            "script_wall_seconds": elapsed,
            "prompt_tokenizer_loaded_locally": True,
            "model_weights_loaded": False,
            "context_unfit_ids": [row["article_id"] for row in preflight if row["context_admission"] != "INPUT_FITS"],
            "direct_eligible_ids": [row["article_id"] for row in preflight if row["execution_admission"] == "DIRECT_SINGLE_REQUEST"],
            "awaiting_full_body_chunking_ids": [row["article_id"] for row in preflight if row["execution_admission"] == "AWAITING_FULL_BODY_CHUNKING"],
            "queue_order": target_ids,
        },
        "articles": preflight,
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "model_called": False, "ui_started": False, "source_fetch_performed_by_helper": False},
    }
    _validate_guoen_targeted_live_binding(manifest, contract)
    _validate_guoen_targeted_candidate_files(root, manifest, queue, contract)
    manifest_raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _write_immutable(root / "candidate-manifest.json", manifest_raw)
    _write_immutable(root / "candidate-manifest.sha256", (_sha(manifest_raw) + "\n").encode("ascii"))
    prepare_receipt = {
        "schema": "guoen_targeted_candidate_prepare_receipt.v2" if range_profile else "guoen_targeted_candidate_prepare_receipt.v1",
        "status": "PREPARED_ZERO_ATTEMPTS",
        "run_id": run_id,
        "candidate_id": candidate_id,
        "candidate_root": str(root),
        "candidate_manifest_sha256": _sha(manifest_raw),
        "validated_batch_sha256": _sha(batch_raw),
        "zero_attempt_queue_sha256": _sha(zero_queue_raw),
        "queue_id": queue_id,
        "article_ids": target_ids,
        "workflow_profile": workflow_profile,
        "citation_protocol": citation_protocol,
        "structured_output_schema_inner_sha256": request["schema_sha256"],
        "structured_output_schema_wrapper_sha256": request["schema_wrapper_sha256"],
        "runtime_settings_sha256": request["runtime_settings_sha256"],
        "model_settings_sha256": request["model_settings_sha256"],
        "source_code_sha256": request["source_code_sha256"],
        "active_server_memory_settings": "CANNOT_CONFIRM",
        "model_requests": 0,
        "model_called": False,
        "ui_started": False,
        "current_parser_sha256": request["parser_sha256"],
        "canonical_contract_source_sha256": request["canonical_contract_sha256"],
        "old_source_batch_sha256": source_batch_sha,
        "old_source_manifest_sha256": source_manifest_sha,
        "attempt_count_total": 0,
        "review_status": "PENDING_INDEPENDENT_READONLY_REVIEW",
    }
    prepare_receipt_raw = json.dumps(prepare_receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _write_immutable(root / "prepare-receipt.json", prepare_receipt_raw)
    return {
        "status": "PREPARED_ZERO_ATTEMPTS",
        "candidate_root": str(root),
        "candidate_manifest_sha256": _sha(manifest_raw),
        "prepare_receipt_sha256": _sha(prepare_receipt_raw),
        "run_id": run_id,
        "candidate_id": candidate_id,
        "queue_id": queue_id,
        "article_ids": target_ids,
        "attempt_count_total": 0,
        "model_called": False,
        "ui_started": False,
    }


def _load_unseen_nonroutine_source_bundle() -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify the independently reviewed single unseen sample against both capture receipts."""
    input_raw = UNSEEN_NONROUTINE_INPUT.read_bytes()
    capture_raw = UNSEEN_NONROUTINE_CAPTURE_MANIFEST.read_bytes()
    coverage_raw = UNSEEN_NONROUTINE_COVERAGE.read_bytes()
    actual_hashes = {
        "input": _sha(input_raw),
        "capture_manifest": _sha(capture_raw),
        "coverage": _sha(coverage_raw),
    }
    expected_hashes = {
        "input": UNSEEN_NONROUTINE_INPUT_SHA256,
        "capture_manifest": UNSEEN_NONROUTINE_CAPTURE_MANIFEST_SHA256,
        "coverage": UNSEEN_NONROUTINE_COVERAGE_SHA256,
    }
    if actual_hashes != expected_hashes:
        raise RuntimeError("UNSEEN_NONROUTINE_SOURCE_PROVENANCE_SHA_MISMATCH")
    input_lines = [line for line in input_raw.splitlines() if line.strip()]
    if len(input_lines) != 1:
        raise RuntimeError("UNSEEN_NONROUTINE_INPUT_ROW_COUNT_INVALID")
    row = json.loads(input_lines[0])
    if not isinstance(row, dict) or row.get("article_id") != UNSEEN_NONROUTINE_ARTICLE_ID:
        raise RuntimeError("UNSEEN_NONROUTINE_INPUT_IDENTITY_INVALID")
    evidence = row.get("source_evidence")
    input_listing = evidence.get("listing_source_ref") if isinstance(evidence, dict) else None
    capture_listing = None
    if (
        row.get("source") != "EASTMONEY_HK"
        or row.get("market") != "HK"
        or not isinstance(evidence, dict)
        or evidence.get("source_sha256") != UNSEEN_NONROUTINE_SOURCE_SHA256
        or evidence.get("body_sha256") != UNSEEN_NONROUTINE_BODY_SHA256
        or _sha(str(row.get("article_body") or "").encode("utf-8")) != UNSEEN_NONROUTINE_BODY_SHA256
    ):
        raise RuntimeError("UNSEEN_NONROUTINE_INPUT_SOURCE_BINDING_INVALID")
    capture = json.loads(capture_raw)
    coverage = json.loads(coverage_raw)
    if (
        capture.get("schema_version") != "v4.announcement.incremental_capture_manifest.v1"
        or coverage.get("schema_version") != "v4.announcement.incremental_coverage.v1"
    ):
        raise RuntimeError("UNSEEN_NONROUTINE_CAPTURE_SCHEMA_INVALID")
    capture_rows = capture.get("rows")
    capture_row = next((item for item in capture_rows if item.get("article_id") == UNSEEN_NONROUTINE_ARTICLE_ID), None) if isinstance(capture_rows, list) else None
    capture_listing = capture_row.get("listing_source_ref") if isinstance(capture_row, dict) else None
    capture_codes = capture_row.get("source_issuer_codes") if isinstance(capture_row, dict) else None
    normalized_capture_codes = [
        {key: issuer.get(key) for key in ("code", "name", "source_stock_code")}
        for issuer in capture_codes if isinstance(issuer, dict)
    ] if isinstance(capture_codes, list) else None
    capture_sample = capture.get("unseen_nonroutine_sample")
    coverage_sample = coverage.get("unseen_nonroutine_sample")
    if not isinstance(capture_row, dict) or not isinstance(capture_sample, dict) or not isinstance(coverage_sample, dict):
        raise RuntimeError("UNSEEN_NONROUTINE_CAPTURE_ROW_MISSING")
    expected_sample = {
        "article_id": UNSEEN_NONROUTINE_ARTICLE_ID,
        "body_sha256": UNSEEN_NONROUTINE_BODY_SHA256,
        "source_sha256": UNSEEN_NONROUTINE_SOURCE_SHA256,
        "sample_input_path": str(UNSEEN_NONROUTINE_INPUT.resolve()),
        "sample_input_sha256": UNSEEN_NONROUTINE_INPUT_SHA256,
    }
    capture_binding = {key: capture_sample.get(key) for key in expected_sample}
    coverage_binding = {key: coverage_sample.get(key) for key in expected_sample}
    row_binding = {
        "article_id": capture_row.get("article_id"),
        "body_sha256": capture_row.get("body_text_sha256"),
        "source_sha256": capture_row.get("source_sha256"),
        "sample_input_path": capture_sample.get("sample_input_path"),
        "sample_input_sha256": capture_sample.get("sample_input_sha256"),
    }
    if (
        capture_binding != expected_sample
        or coverage_binding != expected_sample
        or row_binding != expected_sample
        or capture_row.get("body_complete") is not True
        or capture_row.get("body_status") != "COMPLETE_HASH_VERIFIED"
        or capture_row.get("computed_body_text_sha256") != UNSEEN_NONROUTINE_BODY_SHA256
        or capture_row.get("title") != row.get("title")
        or capture_row.get("publication_date") != row.get("publication_date")
        or capture_row.get("body_artifact_ref") != evidence.get("body_artifact_ref")
        or capture_listing != input_listing
        or normalized_capture_codes != row.get("issuer_codes")
        or capture_sample.get("model_inference_performed") is not False
        or capture_sample.get("model_seen_in_prior_actual_request_queues") is not False
        or capture.get("semantic_assessment") != "NOT_RUN"
        or coverage.get("model_inference_performed") is not False
    ):
        raise RuntimeError("UNSEEN_NONROUTINE_CAPTURE_BINDING_INVALID")
    provenance = {
        "kind": "incremental_capture_input",
        "capture_manifest_path": str(UNSEEN_NONROUTINE_CAPTURE_MANIFEST.resolve()),
        "capture_manifest_sha256": UNSEEN_NONROUTINE_CAPTURE_MANIFEST_SHA256,
        "coverage_path": str(UNSEEN_NONROUTINE_COVERAGE.resolve()),
        "coverage_sha256": UNSEEN_NONROUTINE_COVERAGE_SHA256,
        "capture_row_body_status": capture_row.get("body_status"),
        "model_inference_performed": False,
        "model_seen_in_prior_actual_request_queues": False,
        "original_point_in_time_availability": capture.get("original_point_in_time_availability", "CANNOT_CONFIRM"),
        "capture_status": capture.get("status", "CANNOT_CONFIRM"),
        "coverage_status": coverage.get("status", "CANNOT_CONFIRM"),
    }
    return row, provenance


def prepare_unseen_nonroutine_source_manifest(
    manifest_path: Path = UNSEEN_NONROUTINE_SOURCE_MANIFEST,
) -> dict[str, Any]:
    """Create an immutable one-row adapter manifest from the verified capture bundle."""
    path = manifest_path.expanduser().resolve()
    if not path.is_relative_to(CAPABILITY_SAMPLE_ROOT.resolve()):
        raise RuntimeError("UNSEEN_NONROUTINE_MANIFEST_PATH_OUTSIDE_EVIDENCE")
    row, provenance = _load_unseen_nonroutine_source_bundle()
    line = UNSEEN_NONROUTINE_INPUT.read_bytes().splitlines()[0]
    sample = [{
        "article_id": UNSEEN_NONROUTINE_ARTICLE_ID,
        "body_sha256": UNSEEN_NONROUTINE_BODY_SHA256,
        "source_sha256": UNSEEN_NONROUTINE_SOURCE_SHA256,
        "input_line_sha256": _sha(line),
        "history_class": "UNSEEN",
        "stratum": "nonroutine_unseen",
    }]
    manifest = {
        "schema_version": "v4.announcement.capability_sample_manifest.v1",
        "status": "SOURCE_PROVENANCE_VERIFIED_CAPTURE_PARTIAL",
        "input_file": str(UNSEEN_NONROUTINE_INPUT.resolve()),
        "input_file_sha256": UNSEEN_NONROUTINE_INPUT_SHA256,
        "sample": sample,
        "source_provenance": provenance,
        "safety": {
            "research_only": True,
            "model_inference_performed": False,
            "original_point_in_time_availability": provenance["original_point_in_time_availability"],
            "semantic_assessment": "NOT_RUN",
        },
    }
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _write_immutable(path, raw)
    return {
        "manifest_path": str(path),
        "manifest_sha256": _sha(raw),
        "input_path": str(UNSEEN_NONROUTINE_INPUT.resolve()),
        "input_sha256": UNSEEN_NONROUTINE_INPUT_SHA256,
        "article_id": row["article_id"],
        "source_provenance": provenance,
    }


def _verify_capability_sample_source_provenance(
    source_manifest: dict[str, Any],
    input_path: Path,
    manifest_path: Path,
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    provenance = source_manifest.get("source_provenance")
    if provenance is None:
        return None
    if (
        not isinstance(provenance, dict)
        or input_path.resolve() != UNSEEN_NONROUTINE_INPUT.resolve()
        or not manifest_path.resolve().is_relative_to(CAPABILITY_SAMPLE_ROOT.resolve())
        or len(records) != 1
        or records[0]["input"].get("article_id") != UNSEEN_NONROUTINE_ARTICLE_ID
        or source_manifest.get("input_file") != str(UNSEEN_NONROUTINE_INPUT.resolve())
        or source_manifest.get("input_file_sha256") != UNSEEN_NONROUTINE_INPUT_SHA256
    ):
        raise RuntimeError("UNSEEN_NONROUTINE_NORMALIZED_MANIFEST_IDENTITY_INVALID")
    row, expected_provenance = _load_unseen_nonroutine_source_bundle()
    if records[0]["input"] != row or provenance != expected_provenance:
        raise RuntimeError("UNSEEN_NONROUTINE_NORMALIZED_MANIFEST_PROVENANCE_MISMATCH")
    expected_line = UNSEEN_NONROUTINE_INPUT.read_bytes().splitlines()[0]
    expected_sample = [{
        "article_id": UNSEEN_NONROUTINE_ARTICLE_ID,
        "body_sha256": UNSEEN_NONROUTINE_BODY_SHA256,
        "source_sha256": UNSEEN_NONROUTINE_SOURCE_SHA256,
        "input_line_sha256": _sha(expected_line),
        "history_class": "UNSEEN",
        "stratum": "nonroutine_unseen",
    }]
    if source_manifest.get("sample") != expected_sample:
        raise RuntimeError("UNSEEN_NONROUTINE_NORMALIZED_MANIFEST_SAMPLE_MISMATCH")
    return expected_provenance


def _load_capability_sample_rows(
    input_raw: bytes,
    manifest_raw: bytes,
    expected_input_sha256: str,
    expected_manifest_sha256: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Verify the reviewed source bundle and keep cohort labels out of model rows."""
    if _sha(input_raw) != expected_input_sha256 or _sha(manifest_raw) != expected_manifest_sha256:
        raise RuntimeError("CAPABILITY_SAMPLE_SOURCE_SHA_MISMATCH")
    source_manifest = json.loads(manifest_raw)
    if not isinstance(source_manifest, dict) or not isinstance(source_manifest.get("sample"), list):
        raise RuntimeError("CAPABILITY_SAMPLE_MANIFEST_INVALID")
    if source_manifest.get("schema_version") != "v4.announcement.capability_sample_manifest.v1":
        raise RuntimeError("CAPABILITY_SAMPLE_MANIFEST_SCHEMA_INVALID")
    raw_lines = [line for line in input_raw.splitlines() if line.strip()]
    input_rows = [json.loads(line) for line in raw_lines]
    sample_meta = source_manifest["sample"]
    if not 1 <= len(sample_meta) <= CAPABILITY_SAMPLE_MAX_COUNT or len(input_rows) != len(sample_meta):
        raise RuntimeError("CAPABILITY_SAMPLE_COUNT_OUT_OF_RANGE")
    ids = [row.get("article_id") for row in sample_meta if isinstance(row, dict)]
    if len(ids) != len(sample_meta) or len(set(ids)) != len(ids):
        raise RuntimeError("CAPABILITY_SAMPLE_MANIFEST_IDENTITY_INVALID")
    if any(not isinstance(row, dict) for row in input_rows):
        raise RuntimeError("CAPABILITY_SAMPLE_INPUT_ROW_INVALID")

    allowed_input_keys = {
        "article_id", "article_body", "issuer_codes", "market", "publication_date",
        "source", "source_display_time", "source_evidence", "target_date", "title",
    }
    forbidden_input_keys = {
        "history_class", "sample_history", "source_route", "triage_route", "previous_model_evidence",
        "expected_output", "answer", "prediction", "source_review_status",
    }
    result: list[dict[str, Any]] = []
    for line_raw, row, frozen in zip(raw_lines, input_rows, sample_meta, strict=True):
        if set(row) - allowed_input_keys or set(row) & forbidden_input_keys:
            raise RuntimeError("CAPABILITY_SAMPLE_INPUT_CONTAINS_SIDECAR_FIELDS")
        article_id = row.get("article_id")
        evidence = row.get("source_evidence")
        body = row.get("article_body")
        if (
            article_id != frozen.get("article_id")
            or not isinstance(article_id, str)
            or not re.fullmatch(r"EASTMONEY:AN\d+", article_id)
            or row.get("source") not in {"EASTMONEY", "EASTMONEY_HK"}
            or row.get("market") != "HK"
            or not isinstance(row.get("title"), str)
            or not isinstance(row.get("publication_date"), str)
            or not isinstance(body, str)
            or not body
            or not isinstance(evidence, dict)
        ):
            raise RuntimeError("CAPABILITY_SAMPLE_SOURCE_ROW_INVALID")
        body_sha = evidence.get("body_sha256")
        source_sha = evidence.get("source_sha256")
        if (
            not isinstance(body_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", body_sha)
            or not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha)
            or _sha(body.encode("utf-8")) != body_sha
            or body_sha != frozen.get("body_sha256")
            or source_sha != frozen.get("source_sha256")
            or _sha(line_raw) != frozen.get("input_line_sha256")
        ):
            raise RuntimeError(f"CAPABILITY_SAMPLE_ROW_HASH_MISMATCH:{article_id}")
        history_class = frozen.get("history_class")
        stratum = frozen.get("stratum")
        if history_class not in {"UNSEEN", "DEVELOPMENT", "RETEST"} or not isinstance(stratum, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", stratum):
            raise RuntimeError(f"CAPABILITY_SAMPLE_HISTORY_METADATA_INVALID:{article_id}")
        result.append({
            "input": row,
            "source_history": {"history_class": history_class, "stratum": stratum},
            "input_line_sha256": _sha(line_raw),
        })
    return source_manifest, result


def _capability_sample_article(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    import batch_runner as runner

    row = record["input"]
    evidence = row["source_evidence"]
    body = row["article_body"]
    body_sha = evidence["body_sha256"]
    codes = row.get("issuer_codes") or []
    if not isinstance(codes, list) or any(not isinstance(item, dict) for item in codes):
        raise RuntimeError("CAPABILITY_SAMPLE_ISSUER_CODES_INVALID")
    names = list(dict.fromkeys(item.get("name") for item in codes if isinstance(item.get("name"), str) and item.get("name")))
    valid_codes = list(dict.fromkeys(item.get("code") for item in codes if isinstance(item.get("code"), str) and re.fullmatch(r"HK\.\d{5}", item["code"])))
    listing = evidence.get("listing_source_ref")
    page_evidence = evidence.get("body_page_evidence")
    if not isinstance(listing, dict) or not isinstance(page_evidence, list) or not page_evidence:
        raise RuntimeError("CAPABILITY_SAMPLE_SOURCE_ORIGINS_MISSING")
    origins = []
    for role, origin, row_index in [("LISTING_SOURCE_ROW", listing, 0), *[("BODY_CONTENT_PAGE", page, index) for index, page in enumerate(page_evidence)]]:
        artifact_ref = origin.get("artifact_ref")
        artifact_sha = origin.get("sha256")
        if not isinstance(artifact_ref, str) or not artifact_ref or not isinstance(artifact_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha):
            raise RuntimeError("CAPABILITY_SAMPLE_SOURCE_ORIGIN_INVALID")
        origins.append({
            "role": role,
            "row_fingerprint_sha256": _sha(_canonical_bytes(origin)),
            "source_product_sha256": artifact_sha,
            "source_ref": artifact_ref,
            "source_row_index": row_index,
        })
    metadata = {
        "publication_date": row["publication_date"],
        "title": row["title"],
        "issuer_name": "；".join(names) if names else "CANNOT_CONFIRM",
        "symbol": valid_codes[0] if len(valid_codes) == 1 else "CANNOT_CONFIRM",
        "observed_at": listing.get("available_at") if isinstance(listing, dict) else evidence.get("available_at"),
        "available_at": evidence.get("available_at"),
        "pit_status": "CANNOT_CONFIRM",
        "pit_reason": evidence.get("original_point_in_time_availability"),
        "source_issuer_codes": codes,
        "source_issuer_membership": [],
        "article_membership_status": "CANNOT_CONFIRM",
        "source_scope": "EASTMONEY_ONLY",
        "source_origins": origins,
        "body_artifact_ref": evidence.get("body_artifact_ref"),
        "source_display_time": row.get("source_display_time"),
        "first_hkex_publication_time": evidence.get("first_hkex_publication_time", "CANNOT_CONFIRM"),
    }
    article = {
        "article_id": row["article_id"],
        "source_sha256": evidence["source_sha256"],
        "body_sha256": body_sha,
        "article_body": body,
        "article_metadata": metadata,
    }
    unit_map = runner.build_source_unit_map(body, body_sha)
    ledger = runner.simple_fixed_facts.extract_fixed_facts(body, unit_map, metadata)
    article["fixed_fact_ledger"] = ledger
    return article, {"unit_map": unit_map, "ledger": ledger}


def _capability_sample_request_material(contract: Any) -> dict[str, Any]:
    return _guoen_targeted_request_material(contract, range_profile=True)


def _validate_capability_sample_live_binding(manifest: dict[str, Any], contract: Any) -> None:
    import batch_runner as runner

    policy = manifest.get("model_request_policy")
    if not isinstance(policy, dict):
        raise RuntimeError("CAPABILITY_SAMPLE_REQUEST_POLICY_MISSING")
    current = _capability_sample_request_material(contract)
    checks = {
        "model_id": runner.MODEL_ID,
        "workflow_profile": current["workflow_profile"],
        "citation_protocol": current["citation_protocol"],
        "request_temperature": 0.0,
        "enable_thinking": False,
        "sampling_policy": current["sampling_policy"],
        "sampling_policy_sha256": current["sampling_policy_sha256"],
        "structured_output_schema_sha256": current["schema_sha256"],
        "structured_output_schema_inner_sha256": current["schema_sha256"],
        "structured_output_schema_wrapper_sha256": current["schema_wrapper_sha256"],
        "system_prompt_sha256": current["prompt_sha256"],
        "fixed_fact_parser_protocol": current["parser_protocol"],
        "fixed_fact_parser_sha256": current["parser_sha256"],
        "canonical_contract_source_sha256": current["canonical_contract_sha256"],
        "runtime_settings_sha256": current["runtime_settings_sha256"],
        "request_settings_sha256_provenance": "candidate_prepare_local_disk_readback",
        "active_server_memory_settings": "CANNOT_CONFIRM",
        "model_settings_sha256": current["model_settings_sha256"],
        "source_code_sha256": current["source_code_sha256"],
        "configuration_sha256": current["configuration_sha256"],
        "runtime_limits": current["runtime_limits"],
        "max_completion_tokens": current["configuration_material"]["max_completion_tokens"],
    }
    for key, value in checks.items():
        if policy.get(key) != value:
            raise RuntimeError(f"CAPABILITY_SAMPLE_LIVE_BINDING_MISMATCH:{key}")


def _validate_capability_sample_candidate_files(root: Path, manifest: dict[str, Any], queue: Any, contract: Any) -> None:
    import batch_runner as runner

    if (
        manifest.get("schema") != CAPABILITY_SAMPLE_SCHEMA
        or manifest.get("candidate_kind") != "announcement_capability_sample"
        or manifest.get("model_request_policy", {}).get("workflow_profile") != runner.SIMPLE_WORKFLOW_RANGE_PROFILE
    ):
        raise RuntimeError("CAPABILITY_SAMPLE_CANDIDATE_POLICY_INVALID")
    source = manifest.get("source_inputs", {})
    source_input_path = Path(source.get("sample_input_path", "")).resolve()
    source_manifest_path = Path(source.get("sample_manifest_path", "")).resolve()
    manifest_path_allowed = source_manifest_path.is_relative_to(CAPABILITY_SOURCE_ROOT.resolve()) or source_manifest_path.is_relative_to(CAPABILITY_SAMPLE_ROOT.resolve())
    if not source_input_path.is_relative_to(CAPABILITY_SOURCE_ROOT.resolve()) or not manifest_path_allowed:
        raise RuntimeError("CAPABILITY_SAMPLE_SOURCE_PATH_OUTSIDE_EVIDENCE")
    source_manifest, records = _load_capability_sample_rows(
        source_input_path.read_bytes(), source_manifest_path.read_bytes(),
        source.get("sample_input_sha256", ""), source.get("sample_manifest_sha256", ""),
    )
    _verify_capability_sample_source_provenance(source_manifest, source_input_path, source_manifest_path, records)
    if source.get("source_review_status") != "SOURCE_REVIEW_PASS":
        raise RuntimeError("CAPABILITY_SAMPLE_SOURCE_REVIEW_NOT_PASSED")
    expected_ids = [record["input"]["article_id"] for record in records]
    if manifest.get("target_article_ids") != expected_ids or manifest.get("counts", {}).get("target_article_count") != len(expected_ids):
        raise RuntimeError("CAPABILITY_SAMPLE_TARGET_IDENTITY_MISMATCH")
    queue_meta = manifest.get("queue", {})
    if queue_meta.get("max_attempts") != 1 or queue.max_attempts != 1 or queue.model_id != runner.MODEL_ID:
        raise RuntimeError("CAPABILITY_SAMPLE_QUEUE_POLICY_INVALID")
    if queue_meta.get("queue_id") != queue.queue_id:
        raise RuntimeError("CAPABILITY_SAMPLE_QUEUE_ID_MISMATCH")
    expected_root = (root / "queue-state" / queue.queue_id).resolve()
    if Path(queue_meta.get("state_root", "")).resolve() != expected_root:
        raise RuntimeError("CAPABILITY_SAMPLE_QUEUE_ROOT_OUTSIDE_CANDIDATE")
    batch_path = Path(queue_meta.get("validated_batch_path", "")).resolve()
    if batch_path != (root / "validated-batch.json").resolve() or _sha(batch_path.read_bytes()) != queue_meta.get("validated_batch_sha256"):
        raise RuntimeError("CAPABILITY_SAMPLE_BATCH_BINDING_MISMATCH")
    batch = json.loads(batch_path.read_bytes())
    articles = batch.get("articles")
    if batch.get("expected_count") != len(expected_ids) or not isinstance(articles, list) or [a.get("article_id") for a in articles] != expected_ids:
        raise RuntimeError("CAPABILITY_SAMPLE_BATCH_IDENTITY_INVALID")
    rebuilt = [_capability_sample_article(record)[0] for record in records]
    if articles != rebuilt:
        raise RuntimeError("CAPABILITY_SAMPLE_BATCH_SOURCE_CHANGED")
    current = _capability_sample_request_material(contract)
    _validate_capability_sample_live_binding(manifest, contract)
    by_id = {article["article_id"]: article for article in articles}
    queue_items = queue.snapshot().get("items", [])
    if len(queue_items) != len(expected_ids) or {item.get("identity", {}).get("article_id") for item in queue_items} != set(expected_ids):
        raise RuntimeError("CAPABILITY_SAMPLE_QUEUE_IDENTITY_INVALID")
    for item in queue_items:
        article_id = item["identity"]["article_id"]
        if item.get("max_attempts") != 1 or item.get("attempt_count", 0) > 1:
            raise RuntimeError("CAPABILITY_SAMPLE_QUEUE_ATTEMPT_POLICY_INVALID")
        persisted_state = json.loads(queue.state_path.read_bytes())
        state_item = persisted_state.get("jobs", {}).get(item["idempotency_key"])
        if not isinstance(state_item, dict) or not isinstance(state_item.get("input_path"), str):
            raise RuntimeError(f"CAPABILITY_SAMPLE_QUEUE_INPUT_MISSING:{article_id}")
        input_path = (queue.state_root / state_item["input_path"]).resolve()
        if not input_path.is_relative_to(queue.state_root.resolve()):
            raise RuntimeError("CAPABILITY_SAMPLE_QUEUE_INPUT_OUTSIDE_ROOT")
        payload = json.loads(input_path.read_bytes())
        article = by_id[article_id]
        if payload.get("article_id") != article_id or payload.get("article_body") != article["article_body"] or payload.get("article_metadata") != article["article_metadata"] or payload.get("fixed_fact_ledger") != article["fixed_fact_ledger"]:
            raise RuntimeError(f"CAPABILITY_SAMPLE_QUEUE_SOURCE_MISMATCH:{article_id}")
        if payload.get("messages") != _messages_for_article(article, contract, current["prompt"], current["workflow_profile"]):
            raise RuntimeError(f"CAPABILITY_SAMPLE_QUEUE_MESSAGE_MISMATCH:{article_id}")
        if payload.get("structured_output_schema") != current["schema"] or payload.get("citation_protocol") != current["citation_protocol"]:
            raise RuntimeError(f"CAPABILITY_SAMPLE_QUEUE_SCHEMA_MISMATCH:{article_id}")
        user_content = payload.get("messages", [{}, {}])[1].get("content", "") if isinstance(payload.get("messages"), list) and len(payload["messages"]) > 1 else ""
        if not isinstance(user_content, str) or not user_content.startswith("ARTICLE_DATA_BEGIN\n") or not user_content.endswith("\nARTICLE_DATA_END"):
            raise RuntimeError(f"CAPABILITY_SAMPLE_MODEL_MESSAGE_FORMAT_INVALID:{article_id}")
        model_input = json.loads(user_content[len("ARTICLE_DATA_BEGIN\n"):-len("\nARTICLE_DATA_END")])
        if not isinstance(model_input, dict) or set(model_input) & {"history_class", "sample_history", "previous_model_evidence", "triage_route", "source_route", "expected_output", "answer", "prediction"}:
            raise RuntimeError(f"CAPABILITY_SAMPLE_MODEL_MESSAGE_SIDECAR_LEAK:{article_id}")


def prepare_capability_sample(
    candidate_root: Path,
    *,
    source_input_path: Path = CAPABILITY_SOURCE_INPUT,
    source_manifest_path: Path = CAPABILITY_SOURCE_MANIFEST,
    expected_input_sha256: str = CAPABILITY_SOURCE_INPUT_SHA256,
    expected_manifest_sha256: str = CAPABILITY_SOURCE_MANIFEST_SHA256,
    source_review_status: str | None = None,
) -> dict[str, Any]:
    """Prepare a small, source-pinned range-citation sample; make no model requests."""
    import automatic_canary_server as canary
    import announcement_queue as queue_module
    import batch_runner as runner
    import build_length_canary as length_canary
    from transformers import AutoTokenizer

    root = candidate_root.expanduser().resolve()
    allowed_root = CAPABILITY_SAMPLE_CANDIDATE_ROOT.resolve()
    if root == allowed_root or not root.is_relative_to(allowed_root):
        raise RuntimeError("CAPABILITY_SAMPLE_CANDIDATE_ROOT_OUTSIDE_EVIDENCE")
    if root.exists():
        raise RuntimeError("CAPABILITY_SAMPLE_CANDIDATE_ROOT_ALREADY_EXISTS")
    input_path = source_input_path.expanduser().resolve()
    manifest_path = source_manifest_path.expanduser().resolve()
    source_root = CAPABILITY_SOURCE_ROOT.resolve()
    manifest_path_allowed = manifest_path.is_relative_to(source_root) or manifest_path.is_relative_to(CAPABILITY_SAMPLE_ROOT.resolve())
    if not input_path.is_relative_to(source_root) or not manifest_path_allowed:
        raise RuntimeError("CAPABILITY_SAMPLE_SOURCE_PATH_OUTSIDE_EVIDENCE")
    if source_review_status != "SOURCE_REVIEW_PASS":
        raise RuntimeError("CAPABILITY_SAMPLE_SOURCE_REVIEW_NOT_PASSED")
    input_raw, manifest_raw = input_path.read_bytes(), manifest_path.read_bytes()
    source_manifest, records = _load_capability_sample_rows(input_raw, manifest_raw, expected_input_sha256, expected_manifest_sha256)
    source_provenance = _verify_capability_sample_source_provenance(source_manifest, input_path, manifest_path, records)
    contract = runner.load_active_contract()
    request = _capability_sample_request_material(contract)
    if canary.SIMPLE_WORKFLOW_REQUEST_TEMPERATURE != 0.0 or request["sampling_policy"].get("request_temperature") != 0.0:
        raise RuntimeError("REQUEST_TEMPERATURE_NOT_ZERO")
    if request["sampling_policy"].get("temperature_zero_sampler") != "installed oMLX sampler selects argmax when temperature == 0":
        raise RuntimeError("TEMPERATURE_ZERO_SAMPLER_UNVERIFIED")
    tokenizer = AutoTokenizer.from_pretrained(str(runner.OMLX_TOKENIZER_PATH), local_files_only=True, trust_remote_code=False, use_fast=True)
    articles: list[dict[str, Any]] = []
    preflight: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for record in records:
        row = record["input"]
        article, artifacts = _capability_sample_article(record)
        # The batch artifact is written with sorted keys and reopened by the
        # UI verifier. Use that same canonical order before constructing the
        # request so its byte-exact user message remains reproducible.
        article = json.loads(_canonical_bytes(article))
        messages = _messages_for_article(article, contract, request["prompt"], request["workflow_profile"])
        prompt_tokens = _token_count(tokenizer, messages)
        body_length = len(article["article_body"].encode("utf-8"))
        context_admission = "INPUT_FITS" if prompt_tokens <= request["runtime_limits"]["context_limit_tokens"] else "INPUT_EXCEEDS_CONTEXT"
        execution_admission = "DIRECT_SINGLE_REQUEST" if context_admission == "INPUT_FITS" else "AWAITING_FULL_BODY_CHUNKING"
        article_meta = article["article_metadata"]
        evidence = row["source_evidence"]
        articles.append(article)
        preflight.append({
            "article_id": article["article_id"],
            "art_code": article["article_id"].split(":", 1)[-1],
            "triage_route": "CAPABILITY_SAMPLE_ONLY",
            "title": article_meta["title"],
            "source_sha256": article["source_sha256"],
            "body_sha256": article["body_sha256"],
            "article_metadata_sha256": _sha(_canonical_bytes(article_meta)),
            "source_evidence_sha256": _sha(_canonical_bytes(evidence)),
            "source_evidence_ref": evidence.get("body_artifact_ref"),
            "source_input_line_sha256": record["input_line_sha256"],
            "sample_history": record["source_history"],
            "body_length_bytes": body_length,
            "source_unit_map_sha256": artifacts["unit_map"]["source_unit_map_sha256"],
            "source_unit_count": len(artifacts["unit_map"]["units"]),
            "fixed_fact_parser_protocol": runner.simple_fixed_facts.PROTOCOL,
            "fixed_fact_parser_sha256": request["parser_sha256"],
            "fixed_fact_ledger_sha256": artifacts["ledger"]["ledger_sha256"],
            "fixed_fact_record_count": len(artifacts["ledger"]["records"]),
            "fixed_fact_unknown_count": len(artifacts["ledger"]["unknowns"]),
            "injected_reader_fact_count": len(artifacts["ledger"]["reader_facts"]),
            "model_owned_changes": True,
            "prompt_tokens_exact": prompt_tokens,
            "context_limit_tokens": request["runtime_limits"]["context_limit_tokens"],
            "context_admission": context_admission,
            "execution_admission": execution_admission,
            "membership_status": "CANNOT_CONFIRM",
            "first_hkex_publication_time": article_meta["first_hkex_publication_time"],
        })
        one_batch = length_canary.make_batch([article], "CAPABILITY_SAMPLE_" + _sha(article["article_id"].encode("utf-8"))[:16])
        payloads.append({
            **{name: article[name] for name in ("article_id", "source_sha256", "body_sha256", "article_body", "article_metadata", "fixed_fact_ledger")},
            "source_unit_map_sha256": artifacts["unit_map"]["source_unit_map_sha256"],
            "source_unit_map": artifacts["unit_map"],
            "date": article_meta["publication_date"],
            "market": "HK",
            "prompt_sha256": request["prompt_sha256"],
            "model_id": runner.MODEL_ID,
            "configuration_sha256": request["configuration_sha256"],
            "rules": f"announcement_capability_sample+profile:{request['workflow_profile']}+citation:{request['citation_protocol']}+unit-map:{artifacts['unit_map']['source_unit_map_sha256']}+fixed-ledger:{artifacts['ledger']['ledger_sha256']}+schema:{request['schema_sha256']}+temperature:0.0+thinking:off",
            "role": "announcement_reader",
            "stage": "announcement_capability_sample_20261016",
            "messages": messages,
            "structured_output_schema": request["schema"],
            "workflow_profile": request["workflow_profile"],
            "citation_protocol": request["citation_protocol"],
            "validated_article_batch": one_batch,
            "prompt_tokens_exact": prompt_tokens,
            "context_limit_tokens": request["runtime_limits"]["context_limit_tokens"],
            "context_admission": context_admission,
            "execution_admission": execution_admission,
        })
    target_ids = [row["article_id"] for row in preflight]
    source_identity = [(row["article_id"], row["source_sha256"], row["body_sha256"], row["article_metadata_sha256"]) for row in preflight]
    run_id = "announcement-capability-sample-20261016-" + secrets.token_hex(8)
    candidate_id = _sha(_canonical_bytes({
        "run_id": run_id,
        "source_identity": source_identity,
        "input_sha256": expected_input_sha256,
        "source_manifest_sha256": expected_manifest_sha256,
        "prompt_sha256": request["prompt_sha256"],
        "schema_sha256": request["schema_sha256"],
        "configuration_sha256": request["configuration_sha256"],
        "source_code_sha256": request["source_code_sha256"],
    }))[:20]
    queue_id = f"recent-day-capability-sample-{candidate_id}"
    queue_root = root / "queue-state" / queue_id
    batch_id = "CAPABILITY_SAMPLE_" + candidate_id
    full_batch = length_canary.make_batch(articles, batch_id)
    batch_raw = json.dumps(full_batch, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    counts_history = Counter(row["sample_history"]["history_class"] for row in preflight)
    stratum_counts = Counter(row["sample_history"]["stratum"] for row in preflight)
    root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.mkdir(mode=0o700)
    queue = queue_module.SerialAnnouncementQueue(queue_root, queue_id, runner.MODEL_ID, max_attempts=1, max_body_bytes=None)
    queue.enqueue_many(sorted(payloads, key=lambda p: (len(p["article_body"].encode("utf-8")), p["article_id"])))
    snapshot = queue.snapshot()
    if len(snapshot["items"]) != len(target_ids) or any(item["attempt_count"] != 0 or item["status"] != "PENDING" or item["max_attempts"] != 1 for item in snapshot["items"]):
        raise RuntimeError("CAPABILITY_SAMPLE_ZERO_ATTEMPT_QUEUE_INVALID")
    zero_queue = {
        "schema": "recent_day_capability_sample_zero_attempt_queue.v1",
        "run_id": run_id,
        "queue_id": queue_id,
        "article_count": len(target_ids),
        "model_id": runner.MODEL_ID,
        "counts": snapshot["status_counts"],
        "attempt_count_total": 0,
        "max_attempts": 1,
        "items": [
            {"article_id": item["identity"]["article_id"], "idempotency_key": item["idempotency_key"], "status": item["status"], "attempt_count": item["attempt_count"], "max_attempts": item["max_attempts"], "source_sha256": item["identity"]["source_sha256"], "body_sha256": item["identity"]["body_sha256"], "body_length_bytes": item["body_length_bytes"]}
            for item in snapshot["items"]
        ],
    }
    zero_queue_raw = json.dumps(zero_queue, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _write_immutable(root / "validated-batch.json", batch_raw)
    _write_immutable(root / "zero-attempt-queue.json", zero_queue_raw)
    manifest = {
        "schema": CAPABILITY_SAMPLE_SCHEMA,
        "candidate_kind": "announcement_capability_sample",
        "candidate_id": candidate_id,
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "purpose": "受限的公告文本研究能力样本；输出仅用于复核，不是收益、交易或候选结论。",
        "target_article_ids": target_ids,
        "source_inputs": {
            "sample_input_path": str(input_path),
            "sample_input_sha256": expected_input_sha256,
            "sample_manifest_path": str(manifest_path),
            "sample_manifest_sha256": expected_manifest_sha256,
            "source_review_status": source_review_status,
            "source_review_provenance": "independent screening_sample_review pass reported through parent handoff; no standalone receipt file was present in this evidence root",
            "source_review_receipt_path": "CANNOT_CONFIRM",
            "capture_provenance": source_provenance or "SOURCE_MANIFEST_HAS_NO_CAPTURE_PROVENANCE_BLOCK",
            "source_copy_policy": "only source input rows are converted to model articles; cohort history and prior-request evidence remain manifest-only and are never copied into model messages",
        },
        "sample_history": {
            "history_class_counts": dict(sorted(counts_history.items())),
            "stratum_counts": dict(sorted(stratum_counts.items())),
            "status": source_manifest.get("status", "CANNOT_CONFIRM"),
            "sealed_blind": False,
        },
        "counts": {
            "target_article_count": len(target_ids),
            "queued_complete_articles": len(target_ids),
            "direct_single_request_articles": sum(row["execution_admission"] == "DIRECT_SINGLE_REQUEST" for row in preflight),
            "awaiting_full_body_chunking_articles": sum(row["execution_admission"] == "AWAITING_FULL_BODY_CHUNKING" for row in preflight),
            "isolated_low_priority_articles": 0,
            "body_or_source_exception_articles": 0,
            "official_first_publication_time_cannot_confirm": sum(row["first_hkex_publication_time"] == "CANNOT_CONFIRM" for row in preflight),
            "membership_is_metadata_only": True,
        },
        "queue": {
            "queue_id": queue_id,
            "state_root": str(queue_root),
            "zero_attempt_queue_path": str(root / "zero-attempt-queue.json"),
            "zero_attempt_queue_sha256": _sha(zero_queue_raw),
            "validated_batch_path": str(root / "validated-batch.json"),
            "validated_batch_sha256": _sha(batch_raw),
            "attempts_at_freeze": 0,
            "max_attempts": 1,
            "body_truncation": False,
            "max_concurrency": 1,
            "system_error_policy": "stop remaining requests after first system/transport/empty-response failure; no automatic retry",
            "scheduler": "existing SerialAnnouncementQueue; ascending UTF-8 body bytes; single worker",
        },
        "model_request_policy": {
            "model_id": runner.MODEL_ID,
            "workflow_profile": request["workflow_profile"],
            "citation_protocol": request["citation_protocol"],
            "request_temperature": 0.0,
            "enable_thinking": False,
            "sampling_policy": request["sampling_policy"],
            "sampling_policy_sha256": request["sampling_policy_sha256"],
            "native_structured_output": True,
            "native_model_tools": False,
            "structured_output_schema_sha256": request["schema_sha256"],
            "structured_output_schema_inner_sha256": request["schema_sha256"],
            "structured_output_schema_wrapper_sha256": request["schema_wrapper_sha256"],
            "reader_schema_sha256": request["reader_schema_sha256"],
            "wire_reader_schema_sha256": request["wire_reader_schema_sha256"],
            "system_prompt_sha256": request["prompt_sha256"],
            "prompt_source_sha256": _sha(runner.SIMPLE_WORKFLOW_PROMPT.encode("utf-8")),
            "prompt_adaptation": "frozen existing range-v2 prompt; this candidate changes only the source sample",
            "fixed_fact_parser_protocol": request["parser_protocol"],
            "fixed_fact_parser_sha256": request["parser_sha256"],
            "canonical_contract_source_sha256": request["canonical_contract_sha256"],
            "runtime_settings_sha256": request["runtime_settings_sha256"],
            "request_settings_sha256_provenance": "candidate_prepare_local_disk_readback",
            "active_server_memory_settings": "CANNOT_CONFIRM",
            "model_settings_sha256": request["model_settings_sha256"],
            "source_code_sha256": request["source_code_sha256"],
            "configuration_sha256": request["configuration_sha256"],
            "runtime_limits": request["runtime_limits"],
            "max_completion_tokens": request["configuration_material"]["max_completion_tokens"],
        },
        "preflight": {
            "prompt_tokenizer_loaded_locally": True,
            "model_weights_loaded": False,
            "context_unfit_ids": [row["article_id"] for row in preflight if row["context_admission"] != "INPUT_FITS"],
            "direct_eligible_ids": [row["article_id"] for row in preflight if row["execution_admission"] == "DIRECT_SINGLE_REQUEST"],
            "awaiting_full_body_chunking_ids": [row["article_id"] for row in preflight if row["execution_admission"] == "AWAITING_FULL_BODY_CHUNKING"],
            "queue_order": [item["identity"]["article_id"] for item in snapshot["items"]],
        },
        "articles": preflight,
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "model_called": False, "ui_started": False, "source_fetch_performed_by_helper": False},
    }
    _validate_capability_sample_live_binding(manifest, contract)
    _validate_capability_sample_candidate_files(root, manifest, queue, contract)
    manifest_raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _write_immutable(root / "candidate-manifest.json", manifest_raw)
    _write_immutable(root / "candidate-manifest.sha256", (_sha(manifest_raw) + "\n").encode("ascii"))
    receipt = {
        "schema": "announcement_capability_sample_prepare_receipt.v1",
        "status": "PREPARED_ZERO_ATTEMPTS",
        "candidate_root": str(root),
        "candidate_id": candidate_id,
        "candidate_manifest_sha256": _sha(manifest_raw),
        "validated_batch_sha256": _sha(batch_raw),
        "zero_attempt_queue_sha256": _sha(zero_queue_raw),
        "source_input_sha256": expected_input_sha256,
        "source_manifest_sha256": expected_manifest_sha256,
        "source_review_status": source_review_status,
        "target_article_ids": target_ids,
        "article_count": len(target_ids),
        "model_id": runner.MODEL_ID,
        "workflow_profile": request["workflow_profile"],
        "citation_protocol": request["citation_protocol"],
        "runtime_settings_sha256": request["runtime_settings_sha256"],
        "model_settings_sha256": request["model_settings_sha256"],
        "source_code_sha256": request["source_code_sha256"],
        "active_server_memory_settings": "CANNOT_CONFIRM",
        "attempt_count_total": 0,
        "model_called": False,
        "ui_started": False,
        "review_status": "PENDING_INDEPENDENT_READONLY_REVIEW",
    }
    receipt_raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _write_immutable(root / "prepare-receipt.json", receipt_raw)
    return {
        "status": "PREPARED_ZERO_ATTEMPTS",
        "candidate_root": str(root),
        "candidate_id": candidate_id,
        "candidate_manifest_sha256": _sha(manifest_raw),
        "prepare_receipt_sha256": _sha(receipt_raw),
        "queue_id": queue_id,
        "article_ids": target_ids,
        "attempt_count_total": 0,
        "model_called": False,
        "ui_started": False,
    }


def _project_recent_day_simple_output(
    envelope: Any,
    article: dict[str, Any],
    contract: Any,
    expected_unit_map_sha256: str,
    *,
    range_profile: bool = False,
    batch: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import batch_runner as runner

    if range_profile:
        if batch is None:
            raise runner.BatchError("SIMPLE_WORKFLOW_RANGE_BATCH_REQUIRED")
        projected, receipt = runner.project_simple_workflow_output(
            envelope,
            batch,
            contract,
            expected_source_unit_map_sha256_by_article={
                article["article_id"]: expected_unit_map_sha256
            },
            citation_protocol=runner.SIMPLE_WORKFLOW_RANGE_CITATION_PROTOCOL,
            preserve_model_changes=True,
        )
        receipt.update({
            "protocol": "recent_day_fixed_facts_model_changes_unit_ranges_v2",
            "model_wire_fact_count_discarded": receipt["model_fixed_fields_replaced"]["counts"]["facts"],
            "model_changes_preserved_count": len(projected["results"][0]["reader_output"]["changes"]),
            "reader_schema_sha256": _sha(_canonical_bytes(contract.reader_schema)),
        })
        return projected, receipt

    if not isinstance(envelope, dict):
        raise runner.BatchError("SIMPLE_WORKFLOW_FINAL_RESULT_REQUIRED")
    checked = runner.parse_simple_workflow_envelope(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    if checked is None or checked.get("action") != "complete":
        raise runner.BatchError("SIMPLE_WORKFLOW_FINAL_RESULT_REQUIRED")
    reader_output = checked.get("reader_output")
    runner._validate_json_schema(reader_output, runner.build_simple_reader_wire_schema(contract))
    unit_map = runner.build_source_unit_map(article["article_body"], article["body_sha256"])
    if unit_map["source_unit_map_sha256"] != expected_unit_map_sha256:
        raise runner.BatchError("SIMPLE_WORKFLOW_SOURCE_UNIT_MAP_MISMATCH")
    ledger = runner._simple_fixed_fact_ledger(article, unit_map)
    units = {unit["source_unit_id"]: unit for unit in unit_map["units"]}
    output = json.loads(json.dumps(reader_output, ensure_ascii=False))
    raw_model_facts = list(output["facts"])
    raw_model_risk_notes = list(output["risk_notes"])
    output["facts"] = json.loads(json.dumps(ledger["reader_facts"], ensure_ascii=False))
    pit = runner._simple_workflow_pit_provenance(article)
    output["risk_notes"].append(pit["annotation"])
    output["source_sha256"] = article["source_sha256"]
    output["body_sha256"] = article["body_sha256"]
    projections: list[dict[str, Any]] = []
    for field_name in runner.SOURCE_SPAN_CITATION_FIELDS:
        projected = []
        for index, citation in enumerate(output[field_name]):
            unit_id = citation["source_unit_id"]
            unit = units.get(unit_id)
            if unit is None:
                raise runner.BatchError("SIMPLE_WORKFLOW_SOURCE_UNIT_UNKNOWN")
            quote = unit["text"]
            projected.append({"claim": citation["claim"], "quote": quote, "locator": f"article_body[codepoint:{unit['start_cp']}:{unit['end_cp']}]"})
            projections.append({"field": field_name, "index": index, "source_unit_id": unit_id, "unit_sha256": unit["unit_sha256"], "quote_sha256": _sha(quote.encode("utf-8"))})
        output[field_name] = projected
    runner._validate_json_schema(output, contract.reader_schema)
    return {"results": [{"article_id": article["article_id"], "reader_output": output}]}, {
        "protocol": "recent_day_fixed_facts_model_changes_v1",
        "article_id": article["article_id"],
        "source_sha256": article["source_sha256"],
        "body_sha256": article["body_sha256"],
        "source_unit_map_sha256": unit_map["source_unit_map_sha256"],
        "fixed_fact_ledger_sha256": ledger["ledger_sha256"],
        "injected_fixed_fact_count": len(ledger["reader_facts"]),
        "model_wire_fact_count_discarded": len(raw_model_facts),
        "model_changes_preserved_count": len(output["changes"]),
        "model_risk_notes_before_program_pit_annotation": {"count": len(raw_model_risk_notes), "sha256": _sha(_canonical_bytes(raw_model_risk_notes))},
        "program_input_pit_provenance": pit,
        "citation_projections": projections,
        "reader_schema_sha256": _sha(_canonical_bytes(contract.reader_schema)),
    }


def _runtime_error_from_raw_response(raw: bytes) -> dict[str, Any] | None:
    """Extract a bounded API/runtime error from either JSON or SSE response bytes."""
    candidates: list[Any] = []
    try:
        candidates.append(json.loads(raw.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError):
        pass
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            candidates.append(json.loads(data))
        except json.JSONDecodeError:
            continue
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("error"), dict):
            continue
        error = candidate["error"]
        result: dict[str, Any] = {}
        for key in ("code", "omlx_code", "type", "param"):
            value = error.get(key)
            if isinstance(value, str) and value:
                result[key] = value[:120]
        message = error.get("message")
        if isinstance(message, str) and message:
            result["message"] = message[:1200]
        for key in ("estimated_bytes", "limit_bytes"):
            value = error.get(key)
            if type(value) is int and value >= 0:
                result[key] = value
        if result:
            result["error_code"] = result.get("omlx_code") or result.get("code") or "MODEL_API_ERROR"
            return result
    return None


def _last_raw_stream_response(transport: Any) -> tuple[Path | None, bytes]:
    attempt_dir = getattr(transport, "_attempt_dir", None)
    if not isinstance(attempt_dir, Path) or not attempt_dir.exists():
        return None, b""
    paths = sorted(attempt_dir.glob("round-*.raw.sse"))
    if not paths:
        return None, b""
    path = paths[-1]
    try:
        return path, path.read_bytes()
    except OSError:
        return path, b""


class _RecentDayUI:
    def __init__(self, candidate_root: Path):
        import announcement_queue as queue_module
        import batch_runner as runner

        self.root = candidate_root.resolve()
        raw = (self.root / "candidate-manifest.json").read_bytes()
        if _sha(raw) != (self.root / "candidate-manifest.sha256").read_text(encoding="ascii").strip():
            raise RuntimeError("CANDIDATE_MANIFEST_SHA_MISMATCH")
        self.manifest = json.loads(raw)
        self.is_guoen_targeted = self.manifest.get("schema") in {GUOEN_TARGETED_SCHEMA, GUOEN_TARGETED_RANGE_SCHEMA}
        self.is_guoen_range = self.manifest.get("schema") == GUOEN_TARGETED_RANGE_SCHEMA
        self.is_capability_sample = self.manifest.get("schema") == CAPABILITY_SAMPLE_SCHEMA
        self.uses_range_citations = self.is_guoen_range or self.is_capability_sample
        supported_schemas = {GUOEN_TARGETED_SCHEMA, GUOEN_TARGETED_RANGE_SCHEMA, CAPABILITY_SAMPLE_SCHEMA, "recent_day_flash_172_candidate.v1"}
        if self.manifest.get("schema") not in supported_schemas:
            raise RuntimeError("CANDIDATE_SCHEMA_UNSUPPORTED")
        queue_meta = self.manifest["queue"]
        self.queue = queue_module.SerialAnnouncementQueue(
            queue_meta["state_root"], queue_meta["queue_id"], self.manifest["model_request_policy"]["model_id"],
            max_attempts=queue_meta["max_attempts"], max_body_bytes=None,
        )
        self.contract = runner.load_active_contract()
        if self.is_guoen_targeted:
            _validate_guoen_targeted_live_binding(self.manifest, self.contract)
            _validate_guoen_targeted_candidate_files(self.root, self.manifest, self.queue, self.contract)
            self.candidate_description = "当前独立候选仅含指定的两篇 Guoen 公告；完整冻结正文、原 metadata、source SHA 与 body SHA 保持原值。模型请求 qwen3_8_flash_next，temperature=0、Thinking Off；单并发、最多一次尝试，首次系统错误后停止余下请求。"
            self.page_title = "Guoen 公告独立复核"
            self.table_header = "公告 / 复核范围 / 成员状态"
        elif self.is_capability_sample:
            _validate_capability_sample_live_binding(self.manifest, self.contract)
            _validate_capability_sample_candidate_files(self.root, self.manifest, self.queue, self.contract)
            count = self.manifest["counts"]["target_article_count"]
            history_counts = self.manifest["sample_history"]["history_class_counts"]
            history_text = "、".join(f"{key} {value}" for key, value in sorted(history_counts.items()))
            history_scope = "混合历史；非封存盲测" if len(history_counts) > 1 else "单类样本；非封存盲测"
            self.candidate_description = (
                f"{count} 条研究能力样本；样本历史：{history_text}。{history_scope}。模型请求 qwen3_8_flash_next，temperature=0、Thinking Off；"
                "单并发、每篇最多一次尝试，完整正文采用连续 source-unit 范围引用。未向模型提供样本历史标签或期待答案。"
            )
            self.page_title = "公告文本能力小样本"
            self.table_header = "公告 / 样本历史 / Connect"
        else:
            self.candidate_description = "完整冻结队列172篇，163篇低优先级公告和5篇正文异常保持隔离。172按公告 art_code 计数；发行人展开及月度港股通成员仅作元数据，未知不补造代码。正文不截断，单并发，temperature=0，Thinking Off；170篇符合单次上下文限制的正文可直接运行，2篇完整正文超限但仍保持PENDING，等待完整正文分块处理。官方首次发布时间/PIT保持 CANNOT_CONFIRM。"
            self.page_title = "近24小时港股公告研究"
            self.table_header = "公告 / 初筛路由 / 成员状态"
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.worker: threading.Thread | None = None
        self.stop_requested = False
        self.state = "READY_NO_MODEL_REQUEST"
        self.start_block_code: str | None = None
        self.system_failure: dict[str, Any] | None = None
        self.current: dict[str, Any] | None = None
        self.partial_by_key: dict[str, str] = {}
        self.finished_at: str | None = None
        self.probe_gate = self.manifest.get("recovery_probe_gate")
        self.probe_phase: str | None = None
        self.probe_receipt_path = self.root / "probe-stop-receipt.json"
        stream_root = self.root / "stream-evidence" / "streams"
        self.model_requests_started = sum(1 for _ in stream_root.rglob("round-*.request-input.json")) if stream_root.exists() else 0
        self.article_meta = {row["article_id"]: row for row in self.manifest["articles"]}
        snapshot = self.queue.snapshot()
        expected_count = (
            self.manifest["counts"]["target_article_count"]
            if self.is_capability_sample
            else 2 if self.is_guoen_targeted else 172
        )
        if len(self.article_meta) != expected_count or {x["identity"].get("article_id") for x in snapshot["items"]} != set(self.article_meta):
            raise RuntimeError("UI_QUEUE_MANIFEST_IDENTITY_MISMATCH")
        if self.probe_gate is not None:
            if (
                not isinstance(self.probe_gate, dict)
                or self.probe_gate.get("schema") != "recent_day_single_probe_gate.v1"
                or self.probe_gate.get("article_id") not in self.article_meta
                or self.article_meta[self.probe_gate["article_id"]].get("execution_admission") != "DIRECT_SINGLE_REQUEST"
            ):
                raise RuntimeError("RECOVERY_PROBE_GATE_INVALID")
            probe_item = next(x for x in snapshot["items"] if x["identity"].get("article_id") == self.probe_gate["article_id"])
            if self.probe_receipt_path.exists():
                receipt = json.loads(self.probe_receipt_path.read_bytes())
                raw_path = Path(receipt.get("raw_response_path", ""))
                if not raw_path.is_absolute():
                    raw_path = self.root / raw_path
                try:
                    raw_valid = raw_path.resolve().is_relative_to(self.root.resolve()) and raw_path.is_file() and _sha(raw_path.read_bytes()) == receipt.get("raw_response_sha256")
                except (OSError, ValueError):
                    raw_valid = False
                if (
                    receipt.get("schema") == "recent_day_single_probe_stop.v1"
                    and receipt.get("queue_id") == self.manifest["queue"]["queue_id"]
                    and receipt.get("article_id") == self.probe_gate["article_id"]
                    and receipt.get("status") in {"SUCCEEDED", "FAILED"}
                    and probe_item.get("attempt_count", 0) >= 1
                    and probe_item.get("status") == receipt.get("status")
                    and probe_item.get("raw_sha256") == receipt.get("raw_response_sha256")
                    and raw_valid
                ):
                    self.probe_phase = "PROBE_COMPLETE_AWAITING_CONTINUE"
                else:
                    self.probe_phase = "PROBE_RESULT_UNCONFIRMED"
                    self.state = "STOPPED_PROBE_UNCONFIRMED"
                    self.start_block_code = "PROBE_RESULT_UNCONFIRMED"
            elif probe_item.get("attempt_count", 0) == 0 and probe_item.get("status") == "PENDING":
                self.probe_phase = "PROBE_REQUIRED"
            else:
                self.probe_phase = "PROBE_RESULT_UNCONFIRMED"
                self.state = "STOPPED_PROBE_UNCONFIRMED"
                self.start_block_code = "PROBE_RESULT_UNCONFIRMED"
        failure_path = self.root / "system-failure-stop.json"
        if failure_path.exists():
            failure = json.loads(failure_path.read_bytes())
            if failure.get("schema") != "recent_day_system_failure_stop.v1":
                raise RuntimeError("SYSTEM_FAILURE_RECEIPT_INVALID")
            self.system_failure = failure
            self.state = "STOPPED_SYSTEM_FAILURE"
            self.start_block_code = str(failure.get("error_code") or "SYSTEM_FAILURE_STOPPED")

    def _on_event(self, key: str, event: dict[str, Any]) -> None:
        if event.get("type") == "answer_chunk" and isinstance(event.get("text"), str):
            with self.lock:
                self.partial_by_key[key] = self.partial_by_key.get(key, "") + event["text"]

    def _direct_pending_keys(self) -> set[str]:
        snap = self.queue.snapshot()
        return {
            row["idempotency_key"]
            for row in snap["items"]
            if row["status"] == "PENDING"
            and self.article_meta.get(row["identity"].get("article_id"), {}).get("execution_admission") == "DIRECT_SINGLE_REQUEST"
        }

    def status(self) -> dict[str, Any]:
        snap = self.queue.snapshot()
        with self.lock:
            items = []
            for row in snap["items"]:
                article_id = row["identity"].get("article_id")
                meta = self.article_meta.get(article_id, {})
                items.append({
                    "article_id": article_id, "title": meta.get("title"),
                    "triage_route": meta.get("triage_route"), "membership_status": meta.get("membership_status"),
                    "sample_history": meta.get("sample_history") if self.is_capability_sample else None,
                    "status": row["status"], "attempt_count": row["attempt_count"], "max_attempts": row["max_attempts"],
                    "body_length_bytes": row["body_length_bytes"], "prompt_tokens_exact": meta.get("prompt_tokens_exact"),
                    "context_admission": meta.get("context_admission"), "execution_admission": meta.get("execution_admission"), "source_sha256": row["identity"].get("source_sha256"),
                    "body_sha256": row["identity"].get("body_sha256"), "idempotency_key": row["idempotency_key"],
                    "raw_available": bool(row.get("raw_path")), "raw_path": row.get("raw_path"),
                    "error_code": (row.get("last_error") or {}).get("code") if isinstance(row.get("last_error"), dict) else None,
                    "partial_text": self.partial_by_key.get(row["idempotency_key"], ""),
                })
            unfit_ids = list(self.manifest["preflight"]["context_unfit_ids"])
            current = dict(self.current) if self.current else None
            if current and current.get("idempotency_key"):
                current["partial_text"] = self.partial_by_key.get(current["idempotency_key"], "")
            return {
                "state": self.state, "start_block_code": self.start_block_code,
                "stop_requested": self.stop_requested, "finished_at": self.finished_at,
                "recovery_probe": ({"article_id": self.probe_gate["article_id"], "phase": self.probe_phase} if self.probe_gate else None),
                "system_failure": dict(self.system_failure) if self.system_failure else None,
                "current": current, "queue_id": self.manifest["queue"]["queue_id"],
                "candidate_kind": self.manifest.get("candidate_kind", "recent_day_flash_172_candidate"),
                "candidate_description": self.candidate_description,
                "counts": self.manifest["counts"], "queue_status_counts": snap["status_counts"],
                "direct_eligible_count": len(self.manifest["preflight"]["direct_eligible_ids"]),
                "direct_pending_count": len(self._direct_pending_keys()),
                "awaiting_chunking_count": len(self.manifest["preflight"]["awaiting_full_body_chunking_ids"]),
                "context_unfit_count": len(unfit_ids), "context_unfit_ids": unfit_ids,
                "items": items, "model_called": self.model_requests_started > 0,
            }

    def start(self) -> tuple[bool, str | None]:
        import automatic_canary_server as canary
        import batch_runner as runner

        with self.lock:
            if self.system_failure is not None:
                self.state = "STOPPED_SYSTEM_FAILURE"
                self.start_block_code = str(self.system_failure.get("error_code") or "SYSTEM_FAILURE_STOPPED")
                return False, "SYSTEM_FAILURE_STOPPED"
            if self.probe_phase == "PROBE_RESULT_UNCONFIRMED":
                self.state = "STOPPED_PROBE_UNCONFIRMED"
                self.start_block_code = "PROBE_RESULT_UNCONFIRMED"
                return False, "PROBE_RESULT_UNCONFIRMED"
            if self.probe_phase == "PROBE_REQUIRED":
                probe_id = self.probe_gate["article_id"]
                probe_pending = any(
                    row["identity"].get("article_id") == probe_id and row["idempotency_key"] in self._direct_pending_keys()
                    for row in self.queue.snapshot()["items"]
                )
                if not probe_pending:
                    self.state = "STOPPED_PROBE_UNCONFIRMED"
                    self.start_block_code = "PROBE_ITEM_NOT_PENDING"
                    self.probe_phase = "PROBE_RESULT_UNCONFIRMED"
                    return False, "PROBE_ITEM_NOT_PENDING"
            if self.state in {"START_PREFLIGHT", "RUNNING", "STOP_AFTER_CURRENT_REQUEST"} or (self.worker is not None and self.worker.is_alive()):
                return False, "ALREADY_RUNNING"
            if not self._direct_pending_keys():
                if self.queue.snapshot()["status_counts"].get("PENDING", 0) > 0:
                    self.state = "WAITING_FOR_FULL_BODY_CHUNKING"
                    return False, "AWAITING_FULL_BODY_CHUNKING"
                return False, "NO_PENDING_ITEMS"
            self.state = "START_PREFLIGHT"
            self.stop_requested = False
            self.start_block_code = None
        admin = None
        try:
            if self.is_guoen_targeted:
                self._verify_guoen_targeted_candidate()
            elif self.is_capability_sample:
                self._verify_capability_sample_candidate()
            api_key = runner.load_local_api_key()
            admin = canary.AdminSession(api_key)
            active, waiting = admin.activity()
            if active or waiting:
                raise RuntimeError("MODEL_BUSY_ACTIVE_REQUESTS")
            if not admin.model_ready():
                raise RuntimeError("MODEL_NOT_READY")
            policy = self.manifest["model_request_policy"]
            if policy.get("request_temperature") != 0.0 or policy.get("enable_thinking") is not False:
                raise RuntimeError("REQUEST_POLICY_MISMATCH")
        except Exception as exc:
            with self.lock:
                self.state = "START_BLOCKED"
                self.start_block_code = str(exc).split(":", 1)[0] or type(exc).__name__
            return False, self.start_block_code
        finally:
            if admin is not None:
                admin.close()
        with self.lock:
            self.state = "RUNNING"
            worker_name = (
                "recent-day-guoen-serial-worker" if self.is_guoen_targeted
                else "recent-day-capability-sample-worker" if self.is_capability_sample
                else "recent-day-172-serial-worker"
            )
            self.worker = threading.Thread(target=self._run_queue, args=(api_key,), name=worker_name, daemon=True)
            self.worker.start()
        return True, None

    def _verify_guoen_targeted_candidate(self) -> None:
        raw = (self.root / "candidate-manifest.json").read_bytes()
        expected_sha = (self.root / "candidate-manifest.sha256").read_text(encoding="ascii").strip()
        if _sha(raw) != expected_sha or json.loads(raw) != self.manifest:
            raise RuntimeError("GUOEN_TARGETED_MANIFEST_CHANGED")
        _validate_guoen_targeted_live_binding(self.manifest, self.contract)
        _validate_guoen_targeted_candidate_files(self.root, self.manifest, self.queue, self.contract)

    def _verify_capability_sample_candidate(self) -> None:
        raw = (self.root / "candidate-manifest.json").read_bytes()
        expected_sha = (self.root / "candidate-manifest.sha256").read_text(encoding="ascii").strip()
        if _sha(raw) != expected_sha or json.loads(raw) != self.manifest:
            raise RuntimeError("CAPABILITY_SAMPLE_MANIFEST_CHANGED")
        _validate_capability_sample_live_binding(self.manifest, self.contract)
        _validate_capability_sample_candidate_files(self.root, self.manifest, self.queue, self.contract)

    def stop(self) -> bool:
        with self.lock:
            if self.worker is None or not self.worker.is_alive():
                return False
            self.stop_requested = True
            self.state = "STOP_AFTER_CURRENT_REQUEST"
            return True

    def _persist_system_failure(self, job: Any, error_code: str, error: dict[str, Any], raw_path: Path | None, raw: bytes) -> None:
        if self.system_failure is not None:
            return
        try:
            relative_raw_path = str(raw_path.resolve().relative_to(self.root)) if raw_path is not None else None
        except (OSError, ValueError):
            relative_raw_path = None
        receipt = {
            "schema": "recent_day_system_failure_stop.v1",
            "queue_id": self.manifest["queue"]["queue_id"],
            "article_id": job.payload.get("article_id"),
            "idempotency_key": job.idempotency_key,
            "attempt": job.attempt,
            "error_code": error_code,
            "error": error,
            "raw_response_path": relative_raw_path,
            "raw_response_sha256": _sha(raw) if raw else None,
            "detected_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "queue_policy": "stop remaining requests after first system/transport/empty-response failure; no automatic retry",
        }
        raw_receipt = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        with self.lock:
            if self.system_failure is None:
                self.system_failure = receipt
                self.start_block_code = error_code
        _write_immutable(self.root / "system-failure-stop.json", raw_receipt)

    def _run_queue(self, api_key: str) -> None:
        import automatic_canary_server as canary
        import announcement_queue as queue_module
        import batch_runner as runner

        policy = self.manifest.get("model_request_policy", {})
        transport = canary.GatedStreamingTransport(
            api_key,
            self.root / "stream-evidence",
            expected_runtime_settings_sha256=(policy.get("runtime_settings_sha256") if self.is_guoen_targeted or self.is_capability_sample else None),
            expected_model_settings_sha256=(policy.get("model_settings_sha256") if self.is_guoen_targeted or self.is_capability_sample else None),
        )
        try:
            while True:
                with self.lock:
                    if self.stop_requested:
                        self.state = "STOPPED_WITH_PENDING_ITEMS"
                        break
                allowed_keys = self._direct_pending_keys()
                if self.probe_phase == "PROBE_REQUIRED":
                    probe_id = self.probe_gate["article_id"]
                    probe_key = next((x["idempotency_key"] for x in self.queue.snapshot()["items"] if x["identity"].get("article_id") == probe_id), None)
                    allowed_keys = {probe_key} if probe_key in allowed_keys else set()
                if not allowed_keys:
                    pending = self.queue.snapshot()["status_counts"].get("PENDING", 0)
                    if pending:
                        with self.lock:
                            self.state = "WAITING_FOR_FULL_BODY_CHUNKING"
                    break

                def executor(job: Any) -> str:
                    if job.payload.get("context_admission") != "INPUT_FITS":
                        raise queue_module.ExecutorFailure("INPUT_EXCEEDS_CONTEXT", code="INPUT_EXCEEDS_CONTEXT", raw_response=b"")
                    transport.begin_job(job)
                    with self.lock:
                        self.current = {"article_id": job.payload["article_id"], "idempotency_key": job.idempotency_key, "title": self.article_meta[job.payload["article_id"]].get("title"), "status": "RUNNING"}
                    try:
                        with self.lock:
                            self.model_requests_started += 1
                        completion = transport.complete_batch(
                            job.payload["messages"],
                            on_event=lambda event: self._on_event(job.idempotency_key, event),
                            tools=[], structured_outputs={"json": job.payload["structured_output_schema"]},
                            workflow_profile=(
                                runner.SIMPLE_WORKFLOW_RANGE_PROFILE
                                if self.uses_range_citations
                                else runner.SIMPLE_WORKFLOW_PROFILE
                            ),
                        )
                    except Exception as exc:
                        raw_path, raw = _last_raw_stream_response(transport)
                        runtime_error = _runtime_error_from_raw_response(raw) or {}
                        transport_message = str(exc)
                        status_prefix = "CHAT_HTTP_STATUS:"
                        if not runtime_error:
                            runtime_error = {"error_code": "MODEL_TRANSPORT_FAILURE", "exception_type": type(exc).__name__, "message": transport_message[:500]}
                        if transport_message.startswith(status_prefix) and transport_message[len(status_prefix):].isdigit():
                            runtime_error["http_status"] = int(transport_message[len(status_prefix):])
                        error_code = runtime_error.get("error_code") or "MODEL_TRANSPORT_FAILURE"
                        self._persist_system_failure(job, error_code, runtime_error, raw_path, raw)
                        transport.finish_job(status="FAILED", code=error_code)
                        raise queue_module.ExecutorFailure("MODEL_SYSTEM_FAILURE", code=error_code, raw_response=raw) from None
                    raw_path, raw = _last_raw_stream_response(transport)
                    runtime_error = _runtime_error_from_raw_response(raw)
                    if runtime_error is not None:
                        error_code = str(runtime_error["error_code"])
                        self._persist_system_failure(job, error_code, runtime_error, raw_path, raw)
                        transport.finish_job(status="FAILED", code=error_code, completion=completion)
                        raise queue_module.ExecutorFailure("MODEL_SYSTEM_FAILURE", code=error_code, raw_response=raw)
                    if not completion.final_text:
                        error = {"error_code": "EMPTY_MODEL_OUTPUT", "message": "model returned no final content"}
                        self._persist_system_failure(job, "EMPTY_MODEL_OUTPUT", error, raw_path, raw)
                        transport.finish_job(status="FAILED", code="EMPTY_MODEL_OUTPUT", completion=completion)
                        raise queue_module.ExecutorFailure("EMPTY_MODEL_OUTPUT", code="EMPTY_MODEL_OUTPUT", raw_response=raw)
                    transport.finish_job(status="RESPONSE_RECEIVED", completion=completion)
                    with self.lock:
                        self.current.update({"status": "RESPONSE_RECEIVED", "model_wall_seconds": completion.wall_seconds, "completion_tokens": (completion.usage or {}).get("completion_tokens")})
                    return completion.final_text

                def validator(job: Any, parsed: Any) -> Any:
                    import batch_runner as local_runner

                    payload = job.payload
                    batch = payload["validated_article_batch"]
                    article = batch["articles"][0]
                    projected, receipt = _project_recent_day_simple_output(
                        parsed,
                        article,
                        self.contract,
                        payload["source_unit_map_sha256"],
                        range_profile=self.uses_range_citations,
                        batch=batch,
                    )
                    valid, errors = local_runner._validate_batch_output(json.dumps(projected, ensure_ascii=False, separators=(",", ":")), batch, self.contract)
                    receipt_path = self.root / "projection-receipts" / f"{job.idempotency_key}.json"
                    if errors or set(valid) != {article["article_id"]}:
                        code = errors.get(article["article_id"], "MODEL_OUTPUT_VALIDATION_REJECTED")
                        raw_receipt = json.dumps({"status": "REJECTED", "code": code, "projection": receipt}, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
                        _write_immutable(receipt_path.with_suffix(".rejected.json"), raw_receipt)
                        raise queue_module.ValidationRejected(code, code=code)
                    raw_receipt = json.dumps({"status": "VALIDATED", "projection": receipt}, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
                    _write_immutable(receipt_path, raw_receipt)
                    return projected

                result = self.queue.run_next(executor, validator, wait_for_model_slot=False, idempotency_keys=allowed_keys)
                if result is None:
                    break
                with self.lock:
                    self.current = {"article_id": result.get("identity", {}).get("article_id"), "status": result.get("status"), "error_code": (result.get("last_error") or {}).get("code") if isinstance(result.get("last_error"), dict) else None}
                    if self.system_failure is not None:
                        self.state = "STOPPED_SYSTEM_FAILURE"
                        self.start_block_code = str(self.system_failure.get("error_code") or "SYSTEM_FAILURE_STOPPED")
                        break
                    if self.probe_phase == "PROBE_REQUIRED" and result.get("identity", {}).get("article_id") == self.probe_gate["article_id"]:
                        raw_path_value = result.get("raw_path")
                        raw_path = Path(raw_path_value) if isinstance(raw_path_value, str) else None
                        try:
                            if raw_path is None or not raw_path.is_file():
                                raise RuntimeError("PROBE_RAW_MISSING")
                            resolved_raw = raw_path.resolve()
                            relative_raw = resolved_raw.relative_to(self.root.resolve())
                            raw_sha256 = _sha(raw_path.read_bytes())
                            if result.get("raw_sha256") != raw_sha256 or result.get("status") not in {"SUCCEEDED", "FAILED"}:
                                raise RuntimeError("PROBE_RESULT_UNCONFIRMED")
                            receipt = {
                                "schema": "recent_day_single_probe_stop.v1",
                                "queue_id": self.manifest["queue"]["queue_id"],
                                "article_id": self.probe_gate["article_id"],
                                "idempotency_key": result.get("idempotency_key"),
                                "attempt_count": result.get("attempt_count"),
                                "status": result.get("status"),
                                "raw_response_path": str(relative_raw),
                                "raw_response_sha256": raw_sha256,
                                "validation_error_code": (result.get("last_error") or {}).get("code") if isinstance(result.get("last_error"), dict) else None,
                            }
                            _write_immutable(self.probe_receipt_path, json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
                            self.probe_phase = "PROBE_COMPLETE_AWAITING_CONTINUE"
                            self.state = "PROBE_COMPLETE_AWAITING_CONTINUE"
                        except (OSError, ValueError, RuntimeError) as exc:
                            self.probe_phase = "PROBE_RESULT_UNCONFIRMED"
                            self.state = "STOPPED_PROBE_UNCONFIRMED"
                            self.start_block_code = str(exc).split(":", 1)[0] or "PROBE_RESULT_UNCONFIRMED"
                        break
        except Exception as exc:
            with self.lock:
                self.state = "WORKER_STOPPED_WITH_ERROR"
                self.start_block_code = type(exc).__name__
        finally:
            transport.close()
            with self.lock:
                if self.state == "RUNNING":
                    counts = self.queue.snapshot()["status_counts"]
                    self.state = "FINISHED" if counts.get("PENDING", 0) == 0 else "STOPPED_WITH_PENDING_ITEMS"
                self.finished_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                self.current = None


_UI_HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-__NONCE__'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"><title>__PAGE_TITLE__</title><style>body{font:15px system-ui,sans-serif;max-width:1250px;margin:2rem auto;padding:0 1rem;color:#15202b}button{margin:.4rem;padding:.55rem 1rem}button:disabled{opacity:.45}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #d9e0e7;padding:.4rem;text-align:left;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:28rem;overflow:auto;background:#f2f5f7;padding:.75rem}</style></head><body><h1>__PAGE_HEADING__</h1><p><b>研究用途；不构成选股、BUY资格或交易指令。</b>__CANDIDATE_DESCRIPTION__</p><p id="status">正在读取冻结队列…</p><p><button id="start">Start / 继续剩余队列</button><button id="stop">停止后续队列（当前请求结束后生效）</button></p><p id="role"></p><p id="current"></p><table><thead><tr><th>__ITEM_HEADER__</th><th>队列状态</th><th>正文 bytes / prompt tokens / 上下文</th><th>source/body SHA</th><th>失败 / raw</th></tr></thead><tbody id="items"></tbody></table><div id="raw"></div><script nonce="__NONCE__">const csrf="__CSRF__";async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{...(opts.headers||{}),...(opts.method?{"X-Recent-Day-CSRF":csrf,"Content-Type":"application/json"}:{})}});const j=await r.json();if(!r.ok)throw new Error(j.code||"request_failed");return j}function el(tag,text){const x=document.createElement(tag);x.textContent=text;return x}function render(s){const q=s.queue_status_counts;document.getElementById('status').textContent=`${s.state} · 队列 ${s.counts.queued_complete_articles} / 可直接运行 ${s.direct_pending_count}/${s.direct_eligible_count} / 待完整分块 ${s.awaiting_chunking_count} · ${q.PENDING||0}待处理 / ${q.RUNNING||0}运行 / ${q.SUCCEEDED||0}通过 / ${q.FAILED||0}失败 · 隔离${s.counts.isolated_low_priority_articles||0} / 异常${s.counts.body_or_source_exception_articles||0} · 已发模型请求：${s.model_called?'是':'否'}${s.start_block_code?' · '+s.start_block_code:''}`;const probe=s.recovery_probe;const start=document.getElementById('start');if(probe){start.textContent=probe.phase==='PROBE_REQUIRED'?'开始单篇恢复探针':probe.phase==='PROBE_COMPLETE_AWAITING_CONTINUE'?`继续剩余队列（${s.direct_pending_count}篇）`:'恢复探针状态未确认';}start.disabled=['RUNNING','START_PREFLIGHT','FINISHED','STOPPED_SYSTEM_FAILURE','STOPPED_PROBE_UNCONFIRMED'].includes(s.state)||!(s.direct_pending_count>0);document.getElementById('stop').disabled=!['RUNNING','STOP_AFTER_CURRENT_REQUEST'].includes(s.state);document.getElementById('role').textContent=__ROLE_DESCRIPTION__+(s.system_failure?' 系统故障已停止余下请求：'+s.system_failure.error_code+'；'+((s.system_failure.error||{}).message||''):'');const c=document.getElementById('current');c.replaceChildren();if(s.current)c.append(el('p',`当前：${s.current.title||s.current.article_id} · ${s.current.article_id} · ${s.current.status}${s.current.model_wall_seconds!=null?' · 模型wall '+s.current.model_wall_seconds+'s':''}${s.current.error_code?' · '+s.current.error_code:''}`),el('pre',s.current.partial_text||''));const body=document.getElementById('items');body.replaceChildren();for(const x of s.items){const tr=document.createElement('tr');const sampleHistory=x.sample_history?` · ${x.sample_history.history_class} / ${x.sample_history.stratum}`:` · ${x.triage_route} · Connect ${x.membership_status}`;tr.append(el('td',`${x.title||x.article_id} · ${x.article_id}${sampleHistory}`),el('td',`${x.status} · ${x.attempt_count}/${x.max_attempts}`),el('td',`${x.body_length_bytes} · ${x.prompt_tokens_exact} · ${x.context_admission} · ${x.execution_admission}`),el('td',`source ${x.source_sha256.slice(0,12)} · body ${x.body_sha256.slice(0,12)}`));const last=document.createElement('td');last.textContent=x.error_code||'';if(x.raw_available){const b=el('button','查看原始回答');b.onclick=async()=>{const r=await fetch('/api/raw?key='+encodeURIComponent(x.idempotency_key));document.getElementById('raw').replaceChildren(el('pre',await r.text()))};last.appendChild(b)}tr.appendChild(last);body.appendChild(tr)}}async function refresh(){try{render(await api('/api/status'))}catch(e){document.getElementById('status').textContent='状态读取失败：'+e.message}}document.getElementById('start').onclick=async()=>{try{await api('/api/start',{method:'POST',body:'{}'});await refresh()}catch(e){alert(e.message)}};document.getElementById('stop').onclick=async()=>{try{await api('/api/stop',{method:'POST',body:'{}'});await refresh()}catch(e){alert(e.message)}};refresh();setInterval(refresh,1500);</script></body></html>"""


def serve_candidate(candidate_root: Path, port: int = 0) -> None:
    ui = _RecentDayUI(candidate_root)
    nonce = secrets.token_urlsafe(18)
    if ui.is_capability_sample:
        page_title = ui.page_title
        heading = "公告文本能力小样本（临时研究）"
        item_header = ui.table_header
        role_description = (
            "固定事实由程序从完整正文抽取并注入；changes、impact、条件、反证及经营判断由模型输出并保留。"
            "脚本只投影 start_source_unit_id/end_source_unit_id 标记的连续 source-unit 范围为精确 quote/locator，并附程序 PIT 注记。"
            "Connect 成员资格不筛除队列；超上下文文章保留完整正文和 PENDING 状态，不会误报完成或失败。"
        )
    else:
        page_title = "近24小时港股公告研究"
        heading = "近24小时港股公告深读（临时研究）"
        item_header = "公告 / 初筛路由 / 成员状态"
        role_description = (
            "固定事实由程序从完整正文抽取并注入；changes、impact、条件、反证及经营判断由模型输出并保留。"
            "脚本只投影 source_unit_id 为精确 quote/locator，并附程序 PIT 注记。Connect 成员资格不筛除队列。"
            "超上下文文章保留完整正文和PENDING状态，不会误报完成或失败。"
        )
    page = (
        _UI_HTML.replace("__NONCE__", nonce)
        .replace("__CSRF__", ui.csrf)
        .replace("__PAGE_TITLE__", page_title)
        .replace("__PAGE_HEADING__", heading)
        .replace("__ITEM_HEADER__", item_header)
        .replace("__CANDIDATE_DESCRIPTION__", ui.candidate_description)
        .replace("__ROLE_DESCRIPTION__", json.dumps(role_description, ensure_ascii=False))
    )

    class Handler(BaseHTTPRequestHandler):
        server_version = "RecentDayLoopback/1"

        def log_message(self, _fmt: str, *_args: Any) -> None:
            return

        def _loopback(self) -> bool:
            try:
                address = ipaddress.ip_address(self.client_address[0])
                host = self.headers.get("Host", "").split(":", 1)[0].strip("[]")
                return address.is_loopback and host in {"127.0.0.1", "localhost"}
            except Exception:
                return False

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if not self._loopback():
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            if self.path == "/":
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._send(200, json.dumps(ui.status(), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            elif self.path.startswith("/api/raw?"):
                from urllib.parse import parse_qs, urlsplit
                key = (parse_qs(urlsplit(self.path).query).get("key") or [""])[0]
                item = next((row for row in ui.queue.snapshot()["items"] if row["idempotency_key"] == key), None)
                raw_path = Path(item["raw_path"]) if item and item.get("raw_path") else None
                if raw_path is None or not raw_path.is_file():
                    self._send(404, b"not found", "text/plain; charset=utf-8")
                else:
                    self._send(200, raw_path.read_bytes(), "text/plain; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            if not self._loopback() or self.headers.get("X-Recent-Day-CSRF") != ui.csrf:
                self._send(403, b'{"code":"FORBIDDEN"}', "application/json; charset=utf-8")
                return
            if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_address[1]}"):
                self._send(403, b'{"code":"CROSS_ORIGIN_FORBIDDEN"}', "application/json; charset=utf-8")
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > 8192:
                self._send(413, b'{"code":"REQUEST_TOO_LARGE"}', "application/json; charset=utf-8")
                return
            if length:
                try:
                    json.loads(self.rfile.read(length))
                except Exception:
                    self._send(400, b'{"code":"INVALID_JSON"}', "application/json; charset=utf-8")
                    return
            if self.path == "/api/start":
                ok, code = ui.start()
                self._send(200 if ok else 409, json.dumps({"started": ok, "code": code}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            elif self.path == "/api/stop":
                self._send(200, json.dumps({"stopped": ui.stop()}, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            else:
                self._send(404, b'{"code":"NOT_FOUND"}', "application/json; charset=utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    queue_snapshot = ui.queue.snapshot()
    print(json.dumps({"status": "READY_NO_MODEL_REQUEST", "ui_url": f"http://127.0.0.1:{server.server_address[1]}/", "candidate_kind": ui.manifest.get("candidate_kind", "recent_day_flash_172_candidate"), "queue_id": ui.manifest["queue"]["queue_id"], "queue_count": queue_snapshot["total"], "direct_single_request_count": ui.manifest["counts"]["direct_single_request_articles"], "awaiting_full_body_chunking_count": ui.manifest["counts"]["awaiting_full_body_chunking_articles"], "low_priority_isolated": ui.manifest["counts"].get("isolated_low_priority_articles", 0), "body_exceptions_isolated": ui.manifest["counts"].get("body_or_source_exception_articles", 0), "model_called": ui.model_requests_started > 0, "bind": "127.0.0.1"}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze, prepare, or serve the recent-day HK announcement research run.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--triage", action="store_true", help="Rebuild deterministic frozen-window triage artifacts.")
    group.add_argument("--prepare-172", action="store_true", help="Create the full 172-item zero-attempt queue; no model calls.")
    group.add_argument("--prepare-guoen-targeted", action="store_true", help="Create a separate zero-attempt queue containing only the two frozen Guoen notices.")
    group.add_argument("--prepare-guoen-targeted-range-v2", action="store_true", help="Create a zero-attempt two-notice candidate using article-bound contiguous citation ranges under evidence/announcement-rootcause-20261016/.")
    group.add_argument("--prepare-capability-sample", action="store_true", help="Prepare a source-reviewed 1..8 announcement capability sample with zero model attempts.")
    group.add_argument("--prepare-unseen-nonroutine", action="store_true", help="Prepare a separate one-item zero-attempt candidate from the provenance-verified unseen nonroutine notice.")
    group.add_argument("--serve", action="store_true", help="Serve the temporary loopback UI; inference requires a visible Start click.")
    parser.add_argument("--candidate-root", type=Path, default=None)
    parser.add_argument("--sample-input", type=Path, default=None)
    parser.add_argument("--sample-manifest", type=Path, default=None)
    parser.add_argument("--sample-input-sha256", default=None)
    parser.add_argument("--sample-manifest-sha256", default=None)
    parser.add_argument("--source-review-status", choices=("SOURCE_REVIEW_PASS",), default=None)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    if args.serve:
        serve_candidate(args.candidate_root or CANDIDATE_ROOT, args.port)
        return 0
    if args.prepare_172:
        print(json.dumps(prepare_172(), ensure_ascii=False, sort_keys=True))
        return 0
    if args.prepare_guoen_targeted:
        if args.candidate_root is None:
            parser.error("--prepare-guoen-targeted requires an explicit --candidate-root under evidence/guoen-live-rerun-20261015")
        print(json.dumps(prepare_guoen_targeted(args.candidate_root), ensure_ascii=False, sort_keys=True))
        return 0
    if args.prepare_guoen_targeted_range_v2:
        if args.candidate_root is None:
            parser.error("--prepare-guoen-targeted-range-v2 requires an explicit --candidate-root under evidence/announcement-rootcause-20261016/guoen-targeted-range-v2")
        print(json.dumps(prepare_guoen_targeted(args.candidate_root, range_profile=True), ensure_ascii=False, sort_keys=True))
        return 0
    if args.prepare_capability_sample:
        if args.candidate_root is None:
            parser.error("--prepare-capability-sample requires --candidate-root under evidence/announcement-screening-capability-20261016/capability-sample-v1")
        if args.source_review_status != "SOURCE_REVIEW_PASS":
            parser.error("--prepare-capability-sample requires an independent SOURCE_REVIEW_PASS")
        custom_source = any((args.sample_input, args.sample_manifest, args.sample_input_sha256, args.sample_manifest_sha256))
        if custom_source and not all((args.sample_input, args.sample_manifest, args.sample_input_sha256, args.sample_manifest_sha256)):
            parser.error("custom sample sources require both paths and both SHA-256 values")
        result = prepare_capability_sample(
            args.candidate_root,
            source_input_path=args.sample_input or CAPABILITY_SOURCE_INPUT,
            source_manifest_path=args.sample_manifest or CAPABILITY_SOURCE_MANIFEST,
            expected_input_sha256=args.sample_input_sha256 or CAPABILITY_SOURCE_INPUT_SHA256,
            expected_manifest_sha256=args.sample_manifest_sha256 or CAPABILITY_SOURCE_MANIFEST_SHA256,
            source_review_status=args.source_review_status,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.prepare_unseen_nonroutine:
        if args.candidate_root is None:
            parser.error("--prepare-unseen-nonroutine requires --candidate-root under evidence/announcement-screening-capability-20261016/capability-sample-v1")
        if args.source_review_status != "SOURCE_REVIEW_PASS":
            parser.error("--prepare-unseen-nonroutine requires an independent SOURCE_REVIEW_PASS")
        source = prepare_unseen_nonroutine_source_manifest()
        result = prepare_capability_sample(
            args.candidate_root,
            source_input_path=UNSEEN_NONROUTINE_INPUT,
            source_manifest_path=Path(source["manifest_path"]),
            expected_input_sha256=UNSEEN_NONROUTINE_INPUT_SHA256,
            expected_manifest_sha256=source["manifest_sha256"],
            source_review_status=args.source_review_status,
        )
        result["source_manifest_path"] = source["manifest_path"]
        result["source_manifest_sha256"] = source["manifest_sha256"]
        result["capture_provenance"] = source["source_provenance"]
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    result = build()
    print(json.dumps({
        "manifest": str(TRIAGE_PATH),
        "manifest_sha256": _sha(TRIAGE_PATH.read_bytes()),
        "records": str(RECORDS_PATH),
        "records_sha256": result["artifacts"]["source_window_records_sha256"],
        "candidate_titles": str(CANDIDATES_PATH),
        "counts": result["counts"],
        "membership": result["connect_membership"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
