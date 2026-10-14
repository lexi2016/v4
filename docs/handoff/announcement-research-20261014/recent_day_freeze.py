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


def _recent_day_system_prompt(contract: Any) -> str:
    import batch_runner as runner

    prompt = runner.build_system_prompt(contract, runner.SIMPLE_WORKFLOW_PROFILE)
    old_role = "- wire JSON 中 facts 和 changes 必须都输出空数组；程序会在保存原始模型响应后，从冻结账本生成这两个最终字段及精确引文。模型负责经营/业绩判断，不重新生成固定事实字段。reason 可引用账本 record_id；若为解释经营含义而提及已核验的名称、期间、数量或状态，必须与正文及账本一致，不得改值或把不同关系合并成一个无完整依据的事实 claim。模型响应的判断字段由程序原样保留。"
    new_role = "- wire JSON 中 facts 必须输出空数组；程序会在保存原始模型响应后，从冻结账本注入固定事实和比例及其精确引文。changes 由你根据完整正文填写经营/业绩变化，所有 claim 必须由所引 source_unit_id 支持；程序仅将该引用投影成原文 quote 和 locator，不替你生成、删除或改写 changes。其余判断字段由程序保持模型原样。"
    old_output = "facts 和 changes 均为 []；action=lookup 时 reader_output=null。source_sha256 和 body_sha256 是必填字符串；本轮输入没有提供哈希值，请填空字符串，程序会从冻结队列注入精确值。"
    new_output = "facts 为 []（程序将注入固定事实与比例）；changes 按正文披露填写模型经营/业绩判断，没有有据变化时留空。action=lookup 时 reader_output=null。source_sha256 和 body_sha256 是必填字符串；本轮输入没有提供哈希值，请填空字符串，程序会从冻结队列注入精确值。"
    if prompt.count(old_role) != 1 or prompt.count(old_output) != 1:
        raise RuntimeError("TEMPORARY_PROMPT_REBIND_SOURCE_DRIFT")
    prompt = prompt.replace(old_role, new_role, 1).replace(old_output, new_output, 1)
    if "facts 和 changes 均为 []" in prompt or "changes 必须都输出空数组" in prompt:
        raise RuntimeError("TEMPORARY_PROMPT_CONTRADICTORY_ROLE_RULE")
    return prompt


def _messages_for_article(article: dict[str, Any], contract: Any, system_prompt: str) -> list[dict[str, str]]:
    import batch_runner as runner
    import build_length_canary as length_canary

    batch = length_canary.make_batch([article], "RECENT_DAY_" + _sha(article["article_id"].encode("utf-8"))[:16])
    messages = runner.build_messages(batch, contract, runner.SIMPLE_WORKFLOW_PROFILE)
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


def _project_recent_day_simple_output(envelope: Any, article: dict[str, Any], contract: Any, expected_unit_map_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    import batch_runner as runner

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
        queue_meta = self.manifest["queue"]
        self.queue = queue_module.SerialAnnouncementQueue(
            queue_meta["state_root"], queue_meta["queue_id"], self.manifest["model_request_policy"]["model_id"],
            max_attempts=queue_meta["max_attempts"], max_body_bytes=None,
        )
        self.contract = runner.load_active_contract()
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
        stream_root = self.root / "stream-evidence" / "streams"
        self.model_requests_started = sum(1 for _ in stream_root.rglob("round-*.request-input.json")) if stream_root.exists() else 0
        self.article_meta = {row["article_id"]: row for row in self.manifest["articles"]}
        snapshot = self.queue.snapshot()
        if len(self.article_meta) != 172 or {x["identity"].get("article_id") for x in snapshot["items"]} != set(self.article_meta):
            raise RuntimeError("UI_QUEUE_MANIFEST_IDENTITY_MISMATCH")
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
                "system_failure": dict(self.system_failure) if self.system_failure else None,
                "current": current, "queue_id": self.manifest["queue"]["queue_id"],
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
            self.worker = threading.Thread(target=self._run_queue, args=(api_key,), name="recent-day-172-serial-worker", daemon=True)
            self.worker.start()
        return True, None

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

        transport = canary.GatedStreamingTransport(api_key, self.root / "stream-evidence")
        try:
            while True:
                with self.lock:
                    if self.stop_requested:
                        self.state = "STOPPED_WITH_PENDING_ITEMS"
                        break
                allowed_keys = self._direct_pending_keys()
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
                            workflow_profile=runner.SIMPLE_WORKFLOW_PROFILE,
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
                    projected, receipt = _project_recent_day_simple_output(parsed, article, self.contract, payload["source_unit_map_sha256"])
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


_UI_HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-__NONCE__'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"><title>近24小时港股公告研究</title><style>body{font:15px system-ui,sans-serif;max-width:1250px;margin:2rem auto;padding:0 1rem;color:#15202b}button{margin:.4rem;padding:.55rem 1rem}button:disabled{opacity:.45}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #d9e0e7;padding:.4rem;text-align:left;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:28rem;overflow:auto;background:#f2f5f7;padding:.75rem}</style></head><body><h1>近24小时港股公告深读（临时研究）</h1><p><b>研究用途；不构成选股、BUY资格或交易指令。</b>完整冻结队列172篇，163篇低优先级公告和5篇正文异常保持隔离。172按公告 art_code 计数；发行人展开及月度港股通成员仅作元数据，未知不补造代码。正文不截断，单并发，temperature=0，Thinking Off；170篇符合单次上下文限制的正文可直接运行，2篇完整正文超限但仍保持PENDING，等待完整正文分块处理。官方首次发布时间/PIT保持 CANNOT_CONFIRM。</p><p id="status">正在读取冻结队列…</p><p><button id="start">Start / 继续剩余队列</button><button id="stop">停止后续队列（当前请求结束后生效）</button></p><p id="role"></p><p id="current"></p><table><thead><tr><th>公告 / 初筛路由 / 成员状态</th><th>队列状态</th><th>正文 bytes / prompt tokens / 上下文</th><th>source/body SHA</th><th>失败 / raw</th></tr></thead><tbody id="items"></tbody></table><div id="raw"></div><script nonce="__NONCE__">const csrf="__CSRF__";async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{...(opts.headers||{}),...(opts.method?{"X-Recent-Day-CSRF":csrf,"Content-Type":"application/json"}:{})}});const j=await r.json();if(!r.ok)throw new Error(j.code||"request_failed");return j}function el(tag,text){const x=document.createElement(tag);x.textContent=text;return x}function render(s){const q=s.queue_status_counts;document.getElementById('status').textContent=`${s.state} · 队列 ${s.counts.queued_complete_articles} / 可直接运行 ${s.direct_pending_count}/${s.direct_eligible_count} / 待完整分块 ${s.awaiting_chunking_count} · ${q.PENDING||0}待处理 / ${q.RUNNING||0}运行 / ${q.SUCCEEDED||0}通过 / ${q.FAILED||0}失败 · 隔离163 / 异常5 · 已发模型请求：${s.model_called?'是':'否'}${s.start_block_code?' · '+s.start_block_code:''}`;document.getElementById('start').disabled=['RUNNING','START_PREFLIGHT','FINISHED','STOPPED_SYSTEM_FAILURE'].includes(s.state)||!(s.direct_pending_count>0);document.getElementById('stop').disabled=!['RUNNING','STOP_AFTER_CURRENT_REQUEST'].includes(s.state);document.getElementById('role').textContent='固定事实由程序从完整正文抽取并注入；changes、impact、条件、反证及经营判断由模型输出并保留。脚本只投影 source_unit_id 为精确 quote/locator，并附程序 PIT 注记。Connect 成员资格不筛除队列。超上下文文章保留完整正文和PENDING状态，不会误报完成或失败。'+(s.system_failure?' 系统故障已停止余下请求：'+s.system_failure.error_code+'；'+((s.system_failure.error||{}).message||''):'');const c=document.getElementById('current');c.replaceChildren();if(s.current)c.append(el('p',`当前：${s.current.title||s.current.article_id} · ${s.current.article_id} · ${s.current.status}${s.current.model_wall_seconds!=null?' · 模型wall '+s.current.model_wall_seconds+'s':''}${s.current.error_code?' · '+s.current.error_code:''}`),el('pre',s.current.partial_text||''));const body=document.getElementById('items');body.replaceChildren();for(const x of s.items){const tr=document.createElement('tr');tr.append(el('td',`${x.title||x.article_id} · ${x.article_id} · ${x.triage_route} · Connect ${x.membership_status}`),el('td',`${x.status} · ${x.attempt_count}/${x.max_attempts}`),el('td',`${x.body_length_bytes} · ${x.prompt_tokens_exact} · ${x.context_admission} · ${x.execution_admission}`),el('td',`source ${x.source_sha256.slice(0,12)} · body ${x.body_sha256.slice(0,12)}`));const last=document.createElement('td');last.textContent=x.error_code||'';if(x.raw_available){const b=el('button','查看原始回答');b.onclick=async()=>{const r=await fetch('/api/raw?key='+encodeURIComponent(x.idempotency_key));document.getElementById('raw').replaceChildren(el('pre',await r.text()))};last.appendChild(b)}tr.appendChild(last);body.appendChild(tr)}}async function refresh(){try{render(await api('/api/status'))}catch(e){document.getElementById('status').textContent='状态读取失败：'+e.message}}document.getElementById('start').onclick=async()=>{try{await api('/api/start',{method:'POST',body:'{}'});await refresh()}catch(e){alert(e.message)}};document.getElementById('stop').onclick=async()=>{try{await api('/api/stop',{method:'POST',body:'{}'});await refresh()}catch(e){alert(e.message)}};refresh();setInterval(refresh,1500);</script></body></html>"""


def serve_candidate(candidate_root: Path, port: int = 0) -> None:
    ui = _RecentDayUI(candidate_root)
    nonce = secrets.token_urlsafe(18)
    page = _UI_HTML.replace("__NONCE__", nonce).replace("__CSRF__", ui.csrf)

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
    print(json.dumps({"status": "READY_NO_MODEL_REQUEST", "ui_url": f"http://127.0.0.1:{server.server_address[1]}/", "queue_id": ui.manifest["queue"]["queue_id"], "queue_count": 172, "direct_single_request_count": ui.manifest["counts"]["direct_single_request_articles"], "awaiting_full_body_chunking_count": ui.manifest["counts"]["awaiting_full_body_chunking_articles"], "low_priority_isolated": 163, "body_exceptions_isolated": 5, "model_called": False, "bind": "127.0.0.1"}, ensure_ascii=False), flush=True)
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
    group.add_argument("--serve", action="store_true", help="Serve the temporary loopback UI; inference requires a visible Start click.")
    parser.add_argument("--candidate-root", type=Path, default=CANDIDATE_ROOT)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    if args.serve:
        serve_candidate(args.candidate_root, args.port)
        return 0
    if args.prepare_172:
        print(json.dumps(prepare_172(), ensure_ascii=False, sort_keys=True))
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
