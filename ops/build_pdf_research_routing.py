#!/usr/bin/env python3
"""Build a source-bound disposition projection; never execute OCR or models."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

RULES_VERSION = "question-bound-routing-v1-20261020"
ROUTES = {"SAVE", "REUSE", "REVIEW", "LIGHT_EXTRACTION", "DEEP_RESEARCH"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def checked_ref(ref):
    if not ref or not ref.get("path") or not ref.get("sha256"):
        raise ValueError("MISSING_SOURCE_BINDING")
    if sha(ref["path"]) != ref["sha256"]:
        raise ValueError("INPUT_DRIFT: " + ref["path"])
    return ref


def evidence_valid(row, evidence):
    """Evidence must name an original page and its unmodified text digest."""
    return bool(evidence and evidence.get("excerpt") and any(
        p.get("page_number") == evidence.get("page_number")
        and p.get("text_sha256") == evidence.get("page_text_sha256")
        for p in row.get("source_references", {}).get("pages", [])))


def accepted_first_reuse(handoff, rows):
    """Only the reviewed display combination qualifies, never its failed original."""
    if not handoff:
        return {}
    docid = handoff["document_id"]
    row = rows[docid]
    prepared = handoff["prepared_source"]
    if (prepared["document_id"] != docid
            or prepared["page_input"]["sha256"] != row["frozen_page_input_sha256"]
            or handoff["page_input"]["sha256"] != row["frozen_page_input_sha256"]):
        raise ValueError("REUSE_INPUT_IDENTITY_MISMATCH")
    for ref in [prepared["page_input"], prepared["prepared_receipt"],
                handoff["page_input"], handoff["report"], handoff["receipt"],
                handoff["display_report"], handoff["original_model_report_content_review"]["receipt"],
                handoff["display_combination_content_review"]["receipt"]]:
        checked_ref(ref)
    review = read(handoff["display_combination_content_review"]["receipt"]["path"])
    original_review = read(handoff["original_model_report_content_review"]["receipt"]["path"])
    receipt = read(handoff["receipt"]["path"])
    checked_ref(review["source_pdf"])
    if (review.get("status") != "REPORT_WITH_ERRATUM_PASS"
            or review.get("display") != handoff["erratum_delivery"]["display"]
            or review["display"]["sha256"] != handoff["display_report"]["sha256"]
            or review["source_pdf"]["sha256"] != row["pdf_sha256"]
            or review["original_model_report"]["sha256"] != handoff["report"]["sha256"]
            or handoff["original_model_report_content_review"]["status"] != "REPORT_CONTENT_FAIL"
            or original_review.get("status") != "REPORT_CONTENT_FAIL"
            or receipt.get("document_id") != docid
            or receipt.get("pdf_sha256") != row["pdf_sha256"]
            or receipt.get("page_input", {}).get("sha256") != row["frozen_page_input_sha256"]
            or receipt.get("prepared_text_page_input_sha256") != row["frozen_page_input_sha256"]
            or receipt.get("report", {}).get("sha256") != handoff["report"]["sha256"]):
        raise ValueError("REUSE_RESULT_OR_REVIEW_BINDING_MISMATCH")
    return {docid: {"status": "REPORT_WITH_ERRATUM_PASS", "reusable_result": handoff["display_report"],
                    "original_model_report_status": "REPORT_CONTENT_FAIL",
                    "original_model_report": handoff["report"],
                    "independent_review": handoff["display_combination_content_review"]["receipt"],
                    "input_page_sha256": row["frozen_page_input_sha256"],
                    "scope": "Existing reviewed display combination only; external assertions remain NON_PIT/unverified"}}


def package_bindings(packages, rows):
    """A package author supplies exact questions and source excerpts, not scores."""
    result = defaultdict(list)
    for package in packages:
        if package.get("kind") not in {"company", "industry", "event"} or not package.get("question"):
            raise ValueError("PACKAGE_REQUIRES_KIND_AND_QUESTION")
        for item in package["documents"]:
            row = rows[item["document_id"]]
            ev = item.get("evidence")
            if not evidence_valid(row, ev) or not item.get("question_link"):
                raise ValueError("PACKAGE_REQUIRES_PAGE_EVIDENCE_AND_QUESTION_LINK")
            checked_ref({"path": row["frozen_page_input_path"], "sha256": row["frozen_page_input_sha256"]})
            page = next(p for p in read(row["frozen_page_input_path"])["pages"]
                        if p["page_number"] == ev["page_number"])
            if ev["excerpt"] not in page["text"]:
                raise ValueError("PACKAGE_EXCERPT_NOT_IN_ORIGINAL_PAGE")
            result[row["document_id"]].append({"package_id": package["package_id"], "kind": package["kind"],
                "question": package["question"], "question_link": item["question_link"], "evidence": ev,
                "source_semantic_review": item.get("source_semantic_review", "PENDING_PACKAGE_INPUT_REVIEW"),
                "claim_status": "SOURCE_AUTHOR_CLAIM_NOT_EXTERNALLY_VERIFIED"})
    return result


def route_one(row, authorized_ids, reuse, packages, relations):
    docid = row["document_id"]
    gaps = []
    restrictions = []
    if row.get("report_date", {}).get("value") is None:
        restrictions.append("发布日期未知：日期敏感的前后变化/PIT比较须先核日期；不阻断检索或无日期结论的摘录")
    if row.get("original_institution_candidate") is None:
        restrictions.append("机构未知：不得升级为已认证机构观点；保留原始渠道/说话者不确定性")
    if not row.get("verified_stock_codes"):
        restrictions.append("无核实股票代码：不得从提及实体推断A/HK/US证券映射或可交易资格")
    quality_bad = row.get("ocr_status_asof") != "READY"
    form_bad = row.get("classification_state") in {"EXTRACTION_FAILED", "READY_QUALITY_REVIEW", "READY_FORM_REVIEW"}
    if quality_bad or form_bad:
        route = "REVIEW"
        gaps = (["ocr_status_asof=" + str(row.get("ocr_status_asof"))] if quality_bad else [])
        if form_bad:
            gaps.append("classification_state=" + str(row.get("classification_state")))
        reason = "质量或材料形式存在明确阻断；" + row.get("classification_reason", row.get("route_reason", "待核原页"))
        action = "保留原件与冻结文本；由原OCR/材料核验owner核对所列问题；完成前只作受限检索，不生成事实/投资结论"
    elif docid in reuse:
        route, reason = "REUSE", "输入SHA与已有展示组合、独立语义验收逐项绑定；仅复用带人工勘误组合，原模型报告FAIL保留"
        action = "引用reusable_result及独立receipt；展示原REPORT_CONTENT_FAIL与勘误边界；不重复模型调用"
    elif packages.get(docid):
        route, reason = "DEEP_RESEARCH", "本轮具体研究包问题与正文原页绑定；研究的是所列问题，不以标题/长度/热度判高价值"
        action = "按research_questions核对作者事实、预测与分歧，保留原页数字和口径；只在冻结17样本授权内由模型owner执行"
    elif row.get("route_candidate") == "REUSE_CANDIDATE":
        route, reason = "REVIEW", "确证相同分页正文仅支持重复关系；缺少输入与有效研究结果的绑定，不能判定可复用"
        gaps = ["有效结果及独立内容验收绑定缺失"]
        action = "原文仍可检索；核实同正文的有效结果及来源适用性，无结果时待具体研究任务触发；不重跑模型"
    elif (row.get("primary_type_candidate") == "调研/会议记录"
          or (row.get("primary_type_candidate") == "新闻/资讯解读"
              and (row.get("page_count") or 0) <= 5)):
        route, reason = "LIGHT_EXTRACTION", "正文材料形式支持会议记录/短事件事实卡用途；只需提取说话者、对象、事件、原数字、日期及不确定性"
        action = "待样例模板验收及任务触发后提取事实卡；说话者/日期未核实则明确未知；本轮不执行该批量摘录"
    else:
        route, reason = "SAVE", "保留全文可检索，当前尚无与本轮研究问题的原页绑定；相关性待具体任务触发，不判为低价值"
        action = "保留原件/冻结文本/分类候选索引；按公司、行业或事件任务召回后核原页新增事实与分歧，再决定摘录或深度研究"
    if route == "REVIEW":
        restrictions.append("当前阻断仅限制相应事实/材料形式/复用结论；原件保留且不丢失身份")
    ev = row.get("classification_evidence")
    out = {"document_id": docid, "route": route, "route_reason": reason, "next_action": action,
        "blocking_fields": gaps, "restricted_uses": restrictions, "selection_evidence": ev,
        "selection_evidence_status": "SOURCE_PAGE_BOUND" if evidence_valid(row, ev) else "UNAVAILABLE_RETAINED_NOT_GUESSED",
        "research_questions": packages.get(docid, []), "existing_result": reuse.get(docid, {
            "status": row.get("existing_analysis_status", "UNKNOWN_NOT_READ"), "valid_result_binding": False}),
        "duplicate_relations": relations.get(docid, []),
        "model_execution_authorized": docid in authorized_ids,
        "model_authorization_scope": "FROZEN_REMAINING17_SAMPLE_ONLY" if docid in authorized_ids else "NONE_NO_WIDER_BATCH_RELEASE",
        "model_execution_performed_by_routing": False, "semantic_verification": "NOT_ESTABLISHED_BY_ROUTING",
        "original_metadata": copy.deepcopy(row)}
    assert route in ROUTES
    return out


def build(build_root, selection_path, handoff_path, expected_build_sha, expected_manifest_sha, packages=None):
    root = Path(build_root)
    checked_ref({"path": str(root / "BUILD.json"), "sha256": expected_build_sha})
    binding = read(root / "BUILD.json")
    for name in ["ledger.json", "statistics.json", "all-relations.json"]:
        checked_ref({"path": str(root / name), "sha256": binding["artifacts"][name]["sha256"]})
    ledger = read(root / "ledger.json")
    manifest_ref = ledger["final_prepared_manifest"]
    if manifest_ref["sha256"] != expected_manifest_sha:
        raise ValueError("MANIFEST_IDENTITY_MISMATCH")
    checked_ref(manifest_ref)
    manifest = read(manifest_ref["path"])
    rows = ledger["documents"]
    byid = {r["document_id"]: r for r in rows}
    ids = [r["document_id"] for r in rows]
    manifest_ids = [r["document_id"] for r in manifest["documents"]]
    if len(set(ids)) != len(ids) or len(set(manifest_ids)) != len(manifest_ids) or set(ids) != set(manifest_ids):
        raise ValueError("LEDGER_MANIFEST_ID_RECONCILIATION_FAIL")
    selection = read(selection_path)
    if selection["prepared_text_manifest_sha256"] != expected_manifest_sha:
        raise ValueError("SELECTION_MANIFEST_MISMATCH")
    selected_ids = [r["document_id"] for r in selection["documents"]]
    canary = selection["canary_document_id"]
    if len(selected_ids) != 18 or len(set(selected_ids)) != 18 or canary not in selected_ids:
        raise ValueError("EXPECTED_FROZEN18_WITH_ONE_COMPLETED_CANARY")
    for item in selection["documents"]:
        if item["page_input"]["sha256"] != byid[item["document_id"]]["frozen_page_input_sha256"]:
            raise ValueError("SELECTION_INPUT_DRIFT")
    authorized = set(selected_ids) - {canary}
    reuse = accepted_first_reuse(read(handoff_path), byid)
    if set(reuse) != {canary}:
        raise ValueError("COMPLETED_CANARY_REUSE_BINDING_REQUIRED")
    package_map = package_bindings(packages or [], byid)
    relations = defaultdict(list)
    rel = read(root / "all-relations.json")
    for group in rel["exact_normalized_text_groups"]:
        for docid in group["document_ids"]:
            relations[docid].append({"relation": group["relation"], "group_id": group["group_id"],
                "document_ids": group["document_ids"], "confirmed": True,
                "confirmed_scope": "SAME_NORMALIZED_PAGE_SEQUENCE_ONLY_NOT_RESULT_VALIDITY", "action": "PRESERVE_ALL_NO_MERGE"})
    for pair in rel["repost_or_version_candidates"]:
        for docid in [pair["left_document_id"], pair["right_document_id"]]:
            relations[docid].append({"relation": pair["relation"], "relation_id": pair["relation_id"],
                "document_ids": [pair["left_document_id"], pair["right_document_id"]], "confirmed": False,
                "numeric_scope": pair["numeric_scope"], "left_only_numeric_tokens": pair["left_only_numeric_tokens"],
                "right_only_numeric_tokens": pair["right_only_numeric_tokens"], "action": "PRESERVE_BOTH_NO_MERGE"})
    routed = [route_one(row, authorized, reuse, package_map, relations) for row in rows]
    counts = dict(sorted(Counter(r["route"] for r in routed).items()))
    transitions = dict(sorted(Counter(r["original_metadata"]["route_candidate"] + " -> " + r["route"] for r in routed).items()))
    stats = {"document_count": len(rows), "unique_ids": len(byid), "manifest_ids_reconciled": True,
        "route_counts": counts, "old_to_new_route_counts": transitions, "authorized_model_sample_count": len(authorized),
        "reuse_valid_result_count": len(reuse), "duplicate_result_candidates_not_automatically_reused": 10,
        "bound_package_questions": len(packages or []), "package_source_document_count": len(package_map),
        "package_content_acceptance": "NOT_ESTABLISHED_BY_QUESTION_BINDING",
        "original_classification_statuses_preserved": True, "population_semantic_accuracy": "CANNOT_CONFIRM_NOT_MEASURED_BY_ROUTING",
        "model_requests": 0, "ocr_calls": 0, "downloads": 0, "deletions": 0, "merges": 0,
        "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    inputs = {"build": {"path": str(root / "BUILD.json"), "sha256": expected_build_sha},
        "manifest": manifest_ref, "selection18": {"path": str(selection_path), "sha256": sha(selection_path)},
        "first_reuse_handoff": {"path": str(handoff_path), "sha256": sha(handoff_path)}}
    for ref in inputs.values():
        checked_ref(ref)
    return {"schema": "v4.pdf_research_routing.v1", "rules_version": RULES_VERSION, "inputs": inputs,
        "statistics": stats, "documents": routed}


def write_outputs(result, output):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in [("routing.json", result), ("statistics.json", result["statistics"])]:
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["document_id", "route", "route_reason", "next_action", "model_execution_authorized",
        "blocking_fields", "restricted_uses", "research_questions", "existing_result", "duplicate_relations",
        "selection_evidence", "original_pdf_path", "primary_type_candidate", "ocr_status_asof", "report_date",
        "original_institution_candidate", "verified_stock_codes", "frozen_page_input_sha256"]
    with (out / "routing.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in result["documents"]:
            flat = {key: row.get(key, row["original_metadata"].get(key)) for key in fields}
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in flat.items()})
    stats = result["statistics"]
    lines = ["# 2209份PDF当前处理分流", "", "状态：Writer产物，待独立路由验收。这里只决定当前处置，不证明2209份语义准确或释放模型全量准入。", "",
        "每份一个路由；原文件、原分类/未知字段和数字证据全部保留在 routing.json 的 original_metadata。CSV用于既有资料看板下载/详情补充，不创建服务。", "",
        "| 路由 | 份数 | 当前用途 |", "|---|---:|---|"]
    descriptions = {"SAVE": "保留可检索；相关性待具体任务触发，非低价值", "REUSE": "仅已验收带勘误展示组合；原报告FAIL保留", "REVIEW": "列具体阻断字段及受限用途，保留原件", "LIGHT_EXTRACTION": "会议/短事件事实卡任务；此轮不扩大执行", "DEEP_RESEARCH": "本轮具体问题及原页证据绑定；不是全量模型放行"}
    lines += [f"| {route} | {stats['route_counts'].get(route, 0)} | {descriptions[route]} |" for route in sorted(ROUTES)]
    lines += ["", f"身份对账：{stats['document_count']}条、{stats['unique_ids']}个唯一ID，与冻结manifest集合一致。模型准入只保留原18中的剩余17；已完成首份不重跑。路由构建模型/OCR/下载调用均为0。", "",
        "机构未知不等于无价值；发布日期未知只限制日期敏感比较。READY只代表原准备状态。10个原复用候选未自动当有效结果；相同正文与52对转载/版本候选分别保留，全部原件不合并、不删除。", "",
        "## 本轮研究包问题", ""]
    seen = {}
    for row in result["documents"]:
        for question in row["research_questions"]:
            seen[question["package_id"]] = question
    lines += [f"- {q['package_id']} ({q['kind']}): {q['question']}" for q in seen.values()] or ["三包问题绑定尚未到达；未凭标题指定深度研究。"]
    lines += ["", "## 旧路由变化", "", "| 旧候选 → 当前路由 | 份数 |", "|---|---:|"]
    lines += [f"| {transition} | {count} |" for transition, count in stats["old_to_new_route_counts"].items()]
    lines += ["", "独立Reviewer只验新路由规则、身份对账和边界；原60份及既有分类验收不重复宣称泛化准确率。结果/原件/来源真实性、投资有效性和PIT安全均不因路由而升级。", ""]
    (out / "routing-report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["build-root", "selection18", "first-handoff", "expected-build-sha", "expected-manifest-sha", "output"]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--packages", help="JSON object with packages list, frozen by model/package owner")
    args = parser.parse_args()
    if Path(args.output).resolve().is_relative_to(Path(args.build_root).resolve()):
        raise ValueError("OUTPUT_MUST_NOT_MODIFY_ACCEPTED_BUILD")
    packages = read(args.packages)["packages"] if args.packages else []
    result = build(args.build_root, args.selection18, args.first_handoff,
                   args.expected_build_sha, args.expected_manifest_sha, packages)
    if args.packages:
        result["inputs"]["packages"] = {"path": args.packages, "sha256": sha(args.packages)}
    result["source_sha256"] = sha(__file__)
    write_outputs(result, args.output)
    print(json.dumps(result["statistics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
