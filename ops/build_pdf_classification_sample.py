"""Offline derivative ledger/classification sample over a frozen existing OCR snapshot.

No extraction, OCR, model, network, service, or original-state writes. Rule labels
are candidates. Writer-reviewed examples require a separate bound override file.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import csv
from datetime import date
import hashlib
import html
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import quote

MANIFEST_SHA = "e739287d70abaafe428dabe08fb1025308d195dd717053f8189fe5f84ace25c9"
SCHEMA = "v4.pdf_classification_sample.v1"
PRIMARY = ("券商/研究机构研究", "公司一手披露", "调研/会议记录", "新闻/资讯解读", "数据/白皮书/咨询报告", "教程/方法/其他", "待分类")
ROUTES = ("SAVE", "REUSE_CANDIDATE", "REVIEW", "LIGHT_EXTRACTION_CANDIDATE", "DEEP_RESEARCH_CANDIDATE")
INSTITUTIONS = ("Morgan Stanley", "Goldman Sachs", "J.P. Morgan", "JPMorgan", "Jefferies", "UBS", "Citi Research", "Barclays", "Bernstein", "Deutsche Bank", "BofA", "Nomura", "Macquarie", "DBS", "国盛证券", "国金证券", "中信证券", "中信建投", "华泰证券", "招商证券", "光大证券", "东吴证券", "开源证券", "国联民生", "民生证券", "中泰证券", "浙商证券", "中金公司", "中银证券", "长江证券", "东北证券", "西南证券", "天风证券", "兴业证券", "国信证券", "申万宏源", "广发证券", "华福证券", "平安证券", "华创证券", "华安证券", "华西证券", "财通证券", "东方证券", "国泰海通", "信达证券", "银河证券", "东兴证券", "国投证券", "华源证券")
STRONG_NEWS = r"风口研报|财联社|早知道|盘前必读|盘中资讯|今日早盘|当下市场重点题材|题材复盘|投资舆情|盘前热点|今日财经|今日题材"
MEETING = r"调研纪要|会议纪要|业绩会纪要|交流纪要|专家纪要|访谈纪要|调研记录|投资者关系活动记录|会议记录|访谈实录|调研问答|公司交流|专家交流|访谈记录|Earnings Call Transcript|Conference Call Transcript"
DATA = r"白皮书|统计公报|统计年鉴|white paper|whitepaper|产业发展报告|发展研究报告|行业调查报告|消费者调查|调研报告|麦肯锡|McKinsey|Deloitte|德勤|普华永道|PwC|艾瑞咨询|艾媒咨询|QuestMobile|易观分析|亿欧智库|罗兰贝格|灼识咨询|Euromonitor|中国信通院|中国信息通信研究院"
DISCLOSURE = r"財務報告摘要|财务报告摘要|財報發布|财报发布|公告编号|上市公告书|年度报告全文|半年度报告全文|季度报告全文|年度业绩公告|中期业绩公告|Annual Report|INTERIM REPORT|INTERIM RESULTS|EARNINGS PRESENTATION|业绩演示|业绩发布会演示|Investor Presentation"
OTHER = r"投资方法|交易方法|选股方法|投资教程|教学材料|课程讲义|培训教材|投资笔记|学习笔记|交易系统教程|交易心理|投资的底层逻辑|交易的底层逻辑|Technical Analysis Handbook"
BROKER = r"证券研究报告|研究报告|Research Report|Equity Research|INVESTMENT RESEARCH|RESEARCH|投资评级|行业评级|评级[:：]|BUY|Overweight|目标价|Target Price|公司点评|行业点评|行业深度|公司深度|行业周报|宏观专题"
NUMBER = re.compile(r"(?<![A-Za-z0-9])[+\-−]?\d+(?:[.,]\d+)*(?:[%％]|万亿|亿元|万元|亿|万|元|吨|倍|bps|bp|HKD|USD|KRW)?")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_raw(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_raw(value))


def read_json(path: Path, expected: str | None = None):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"INPUT_NOT_REGULAR:{path}")
    raw = path.read_bytes()
    if expected and sha(raw) != expected:
        raise ValueError(f"INPUT_SHA_MISMATCH:{path}")
    return json.loads(raw), raw


def bound_path(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("UNSAFE_DERIVED_REFERENCE")
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("UNSAFE_DERIVED_REFERENCE")
    return path


def normalize_exact(text: str) -> str:
    """NFC + whitespace collapse; retain numeric/word boundaries and every symbol."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def body_sha(pages: list[dict]) -> str:
    return sha(json.dumps([normalize_exact(p["text"]) for p in pages], ensure_ascii=False, separators=(",", ":")).encode())


def freeze_taxonomy(source: Path, output: Path):
    raw = source.read_bytes()
    tree = ast.parse(raw.decode())
    labels, version = [], None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_MARKET_MAPPING_VERSION" for t in node.targets):
            version = ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP":
            for row in node.value.elts:
                for key, value in zip(row.keys, row.values):
                    if isinstance(key, ast.Constant) and key.value == "label":
                        labels.append(ast.literal_eval(value))
    if not version or len(labels) != 24:
        raise ValueError("EXISTING_INDUSTRY_DICTIONARY_NOT_CONFIRMED")
    result = {"source_path": str(source), "source_sha256": sha(raw), "version": version, "labels": labels,
              "semantics": "Existing global theme dictionary; content-tag candidates only, not issuer industry assignment or trading mapping"}
    write_json(output, result)
    return result


def evidence(pages: list[dict], regex: str | None = None, *, default_page=1, limit=220):
    for page in pages:
        text = page["text"]
        match = re.search(regex, text, re.I) if regex else None
        if match or not regex and page["page_number"] == default_page:
            start = max(0, match.start() - 55) if match else 0
            snippet = re.sub(r"\s+", " ", text[start:start + limit]).strip()
            return {"page_number": page["page_number"], "page_text_sha256": sha(text.encode()), "excerpt": snippet}
    return None


def page_slice(pages, count=3, chars=14000):
    return "\n".join(page["text"] for page in pages[:count])[:chars]


def language(text):
    han = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if not han and not latin:
        return "UNKNOWN"
    if han > max(15, latin * .25) and latin > max(30, han * .5):
        return "ZH_EN_MIXED"
    return "ZH" if han >= latin * .25 else "EN"


def institution_pattern(name):
    escaped = re.escape(name)
    return r"(?<![A-Za-z])"+escaped+r"(?![A-Za-z])" if re.search(r"[A-Za-z]", name) else escaped


def primary_candidate(pages):
    head = page_slice(pages, 2, 11000)
    short = page_slice(pages, 1, 3500)
    institutions = [name for name in INSTITUTIONS if re.search(institution_pattern(name), head, re.I)]
    if re.search(STRONG_NEWS, short, re.I):
        return PRIMARY[3], "资讯栏目/题材线索", STRONG_NEWS, "正文出现明确资讯栏目或题材汇编结构"
    if institutions and re.search(r"证券研究报告|Equity Research|SWS RESEARCH|产业研究报告", short[:1800], re.I):
        return PRIMARY[0], "研究报告/策略/行业", re.escape(institutions[0]), "首页出版机构及研究报告结构明确；不会因引用会议纪要或白皮书改变材料性质"
    if re.search(r"发言人\s*\d{1,2}:\d{2}|说话人\s*\d|Speaker\s*\d+", short, re.I):
        return PRIMARY[2], "会议/访谈转录", r"发言人\s*\d{1,2}:\d{2}|说话人\s*\d|Speaker\s*\d+", "正文含发言人及时间戳；仅确认记录形式，不确认转录准确性或发言人身份"
    if re.search(MEETING, short[:900], re.I):
        return PRIMARY[2], "调研/会议记录", MEETING, "首页正文含纪要/调研记录性质标记；发言及记录身份仍需核验"
    if re.search(DATA, short, re.I) and not (institutions and re.search(r"证券研究报告", short)):
        return PRIMARY[4], "行业资料/咨询", DATA, "正文出现白皮书、统计或咨询机构资料标记"
    if re.search(DISCLOSURE, short, re.I) and not institutions:
        return PRIMARY[1], "公司披露/业绩材料", DISCLOSURE, "首页出现公告或公司报告/演示结构，未检测到研究机构出版标记"
    if re.search(OTHER, short, re.I) and not institutions:
        return PRIMARY[5], "方法/教学", OTHER, "正文明确方法或教学材料标记"
    if institutions and re.search(BROKER, head, re.I):
        marker = re.escape(institutions[0])
        return PRIMARY[0], "公司研究" if re.search(r"公司点评|公司深度|个股研究|Company Report", short, re.I) else "研究报告/策略/行业", marker, "正文同时出现研究机构名称和研究/评级结构；规则候选待语义核验"
    if re.search(r"催化因素|重点标的|市场热点|板块催化", short) and not institutions:
        return PRIMARY[3], "题材资讯汇编", r"催化因素|重点标的|市场热点|板块催化", "正文以事件催化/题材标的汇编为主，不以文件名认定券商研报"
    return PRIMARY[6], "未知", None, "现有正文证据不足以确认材料性质；禁止由文件名补定类别"


def report_date_candidate(pages):
    if not pages:
        return {"value": None, "status": "UNKNOWN", "evidence": None}
    text = pages[0]["text"][:5000]
    text = re.split(r"相关研究|相關研究|相关报告|相關報告", text, maxsplit=1)[0]
    patterns = [
        r"(?m)^\s*(20\d{2})[年./-]\s*(\d{1,2})[月./-]\s*(\d{1,2})日?\s*$",
        r"(?:报告日期|发布日期|发布时间|發佈日期|Report date|Publication date)[^\n\d]{0,35}(20\d{2})[年./-]\s*(\d{1,2})[月./-]\s*(\d{1,2})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text[:1000] if pattern.startswith("(?m)") else text, re.I):
            try:
                value = date(*map(int, match.groups())).isoformat()
            except ValueError:
                continue
            return {"value": value, "status": "BODY_HEADER_DATE_CANDIDATE", "evidence": evidence(pages, re.escape(match.group(0).strip()))}
    return {"value": None, "status": "UNKNOWN", "evidence": None}


def candidate_metadata(document, receipt, pages, taxonomy):
    text = page_slice(pages)
    primary, subtype, marker, reason = primary_candidate(pages)
    institutions = [name for name in INSTITUTIONS if re.search(institution_pattern(name), text, re.I)]
    issuer = institutions[0] if primary == PRIMARY[0] and len(institutions) == 1 else None
    label_hits = [label for label in taxonomy["labels"] if label in text]
    industry_evidence = {label: evidence(pages[:3], re.escape(label)) for label in label_hits}
    # Existing dictionary labels only. No stock/issuer mapping or guessed ticker.
    channels = [v for v in ("财联社", "小牛研报纪要", "知识星球") if v in text]
    collection_dates = []
    for value in document.get("collection_directories", []):
        m = re.fullmatch(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", value)
        if m:
            collection_dates.append(date(*map(int, m.groups())).isoformat())
    markets = []
    market_terms = {"HK": r"港股|Hong Kong|[0-9]{4,5}\.HK\b", "US": r"美股|U\.S\. Equit|US Equity|Nasdaq|NYSE", "A": r"A股|A 股|沪深|[0-9]{6}\.(?:SH|SZ)\b", "KR": r"[0-9]{6}\.KS\b|Korea|韩国", "JP": r"Japan|日本|[0-9]{4}\.T\b"}
    for market, term in market_terms.items():
        if re.search(term, text, re.I):
            markets.append(market)
    title_lines = [line.strip() for line in (pages[0]["text"].splitlines() if pages else []) if len(line.strip()) >= 5]
    body_title = " / ".join(title_lines[:3])[:180] if title_lines else None
    selected_status = receipt.get("status", "PENDING") if receipt else "PENDING"
    ready = selected_status == "READY"
    route = "REVIEW" if not ready or primary == PRIMARY[6] else "LIGHT_EXTRACTION_CANDIDATE" if primary == PRIMARY[3] and len(pages) <= 10 and "财联社" in channels else "SAVE"
    route_reason = "质量/身份或材料性质待核；未知不等于低价值" if route == "REVIEW" else "暂无明确研究问题；保留可检索，不自动判高价值或生成研究" if route == "SAVE" else "短事件材料的轻量字段摘录候选；仍需来源/日期确认与批准模板"
    return {
        "document_id": document["document_id"], "pdf_sha256": document["pdf_sha256"], "pdf_bytes": document["pdf_bytes"],
        "original_pdf_path": document["local_pdf_path"], "all_source_paths": document.get("source_paths", []),
        "filename_candidate_title": Path(document["local_pdf_path"]).stem, "body_header_candidate_title": body_title,
        "title_status": "BODY_HEADER_CANDIDATE" if body_title else "FILENAME_HINT_ONLY", "ocr_status_asof": selected_status,
        "page_count": len(pages) or (receipt.get("page_count") if receipt else None), "text_characters": sum(len(p["text"]) for p in pages),
        "page_count_status": "PREPARED_RECEIPT" if receipt else "UNKNOWN_PENDING", "language_candidate": language(text),
        "primary_type_candidate": primary, "subtype_candidate": subtype, "classification_status": "RULE_CANDIDATE_NOT_SEMANTICALLY_ACCEPTED",
        "classification_reason": reason, "classification_evidence": evidence(pages, marker) if pages else None,
        "original_institution_candidate": issuer, "institution_status": "BODY_MENTION_PUBLISHER_CANDIDATE" if issuer else "UNKNOWN_OR_CONFLICTED",
        "institution_evidence": evidence(pages[:3], re.escape(issuer)) if issuer else None,
        "repost_channels_candidate": channels, "author": None, "author_status": "UNKNOWN_NOT_GUESSED",
        "report_date": ({"value": None, "status": "UNKNOWN_EXPORT_OR_TRANSCRIPT_TIMESTAMP_NOT_PUBLICATION", "evidence": None} if re.search(r"_导读|_原文|发言人\s*\d{1,2}:\d{2}", page_slice(pages, 1, 1200)) else report_date_candidate(pages)), "collection_dates": sorted(set(collection_dates)), "collection_date_basis": "COLLECTION_DIRECTORY_ONLY_NOT_PUBLICATION_DATE",
        "industry_theme_candidates": label_hits, "industry_evidence": industry_evidence, "industry_dictionary_version": taxonomy["version"],
        "markets_mentioned_candidate": markets, "market_semantics": "Text mention only, not issuer domicile, exchange eligibility or A/HK mapping",
        "main_research_companies": [], "mentioned_companies": [], "company_status": "UNKNOWN_PENDING_ENTITY_REVIEW", "verified_stock_codes": [], "stock_code_status": "UNKNOWN_NO_GUESSED_MAPPING",
        "exact_body_sha256": body_sha(pages) if ready and pages else None,
        "exact_body_scope": "NFC_WHITESPACE_COLLAPSE_PAGE_SEQUENCE" if ready and pages else None,
        "text_quality": "PREPARED_READY_OCR_SEMANTICS_UNREVIEWED" if ready else selected_status,
        "existing_analysis_status": "PRIOR_REPORT_REFERENCE_PRESENT_NOT_REVIEWED" if receipt and (receipt.get("revision") or {}).get("supersedes") else "UNKNOWN_NOT_READ",
        "route_candidate": route, "route_reason": route_reason, "deep_research_scope": "NO_EXPLICIT_RESEARCH_QUESTION_NO_HIGH_VALUE_ASSIGNMENT",
        "duplicate_group": None, "version_group": None, "relation_candidates": [], "relation_status": "UNASSESSED_NOT_NO_RELATION",
    }


def load_frozen_inputs(manifest_path, progress_path, snapshot_receipt_path, prepared_root, taxonomy):
    manifest, _ = read_json(manifest_path, MANIFEST_SHA)
    snapshot, _ = read_json(snapshot_receipt_path)
    progress, progress_raw = read_json(progress_path, snapshot["progress_sha256"])
    if progress.get("parent_manifest_sha256") != MANIFEST_SHA:
        raise ValueError("PROGRESS_PARENT_IDENTITY_MISMATCH")
    documents = manifest["documents"]
    ids = [d["document_id"] for d in documents]
    if len(ids) != 2209 or len(set(ids)) != 2209 or any(d["document_id"] != d["pdf_sha256"] for d in documents):
        raise ValueError("FROZEN_2209_IDENTITY_INVALID")
    statuses = {d["document_id"]: d for d in progress["documents"]}
    if len(statuses) != len(progress["documents"]) or not set(statuses) <= set(ids):
        raise ValueError("PROGRESS_IDENTITY_PARTITION_INVALID")
    rows, texts, index = [], {}, {}
    for document in documents:
        document_id = document["document_id"]
        row = statuses.get(document_id)
        receipt, pages = None, []
        refs = {"receipt": None, "page_input": None, "pages": []}
        if row:
            path = bound_path(prepared_root, row["receipt_path"])
            receipt, _ = read_json(path, row["receipt_sha256"])
            if (receipt.get("document_id") != document_id or receipt.get("pdf_sha256") != document["pdf_sha256"]
                    or receipt.get("parent_manifest_sha256") != MANIFEST_SHA or receipt.get("status") != row["status"]):
                raise ValueError("PREPARED_RECEIPT_IDENTITY_MISMATCH")
            refs["receipt"] = {"path": str(path), "sha256": row["receipt_sha256"]}
            page_ref = receipt.get("page_input")
            if page_ref:
                page_path = bound_path(prepared_root, page_ref["path"])
                page_input, _ = read_json(page_path, page_ref["sha256"])
                if (page_input.get("document_id") != document_id or page_input.get("pdf_sha256") != document["pdf_sha256"]
                        or page_input.get("manifest_sha256") != MANIFEST_SHA):
                    raise ValueError("PREPARED_TEXT_IDENTITY_MISMATCH")
                pages = page_input["pages"]
                if len(pages) != receipt["page_count"]:
                    raise ValueError("PREPARED_PAGE_COVERAGE_MISMATCH")
                for number, page in enumerate(pages, 1):
                    text_sha = sha(page["text"].encode())
                    if page.get("page_number") != number or page.get("text_sha256") not in (None, text_sha):
                        raise ValueError("PREPARED_PAGE_TEXT_SHA_MISMATCH")
                    refs["pages"].append({"page_number": number, "text_sha256": text_sha})
                refs["page_input"] = {"path": str(page_path), "sha256": page_ref["sha256"]}
        metadata = candidate_metadata(document, receipt, pages, taxonomy)
        metadata["source_references"] = refs
        metadata["frozen_page_input_sha256"] = refs["page_input"]["sha256"] if refs["page_input"] else None
        metadata["frozen_page_input_path"] = refs["page_input"]["path"] if refs["page_input"] else None
        metadata["prepared_receipt_sha256"] = refs["receipt"]["sha256"] if refs["receipt"] else None
        metadata["asof_utc"] = snapshot["asof_utc"]
        rows.append(metadata)
        texts[document_id] = pages
        index[document_id] = refs
    return rows, texts, snapshot, index


def select_sample(rows, count=60):
    """Frozen deterministic strata, minimum five where observed supply allows."""
    eligible = [r for r in rows if r["source_references"]["page_input"]]
    selected = []
    coverage = Counter()
    def features(row):
        return {row["language_candidate"], "LONG" if (row["page_count"] or 0) >= 30 else "SHORT" if (row["page_count"] or 0) <= 5 else "MEDIUM", row["institution_status"], row["ocr_status_asof"], "DATE_UNKNOWN" if row["report_date"]["value"] is None else "DATE_HEADER", row["collection_dates"][0] if row["collection_dates"] else "COLLECTION_UNKNOWN"}
    def take(pool):
        candidate = min(pool, key=lambda r: (-sum(1/(1+coverage[f]) for f in features(r)), r["document_id"]))
        selected.append(candidate["document_id"])
        coverage.update(features(candidate))
    by_class = {label: [r for r in eligible if r["primary_type_candidate"] == label] for label in PRIMARY}
    for label in PRIMARY:
        for _ in range(min(5, len(by_class[label]))):
            take([r for r in by_class[label] if r["document_id"] not in selected])
    while len(selected) < count:
        remaining = [r for r in eligible if r["document_id"] not in selected]
        if not remaining:
            raise ValueError("INSUFFICIENT_FROZEN_TEXT_FOR_60_SAMPLE")
        take(remaining)
    return selected, {label: len(by_class[label]) for label in PRIMARY}


def _ngrams(text):
    value = normalize_exact(text)
    return {value[i:i+3] for i in range(max(0, len(value)-2))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a or b else 0.0


def pairs_candidates(rows, texts, count=10):
    """Bounded deterministic retrieval only. Fuzzy score never establishes duplicate."""
    ready = [r for r in rows if r["ocr_status_asof"] == "READY" and r["exact_body_sha256"]]
    groups = defaultdict(list)
    for row in ready:
        groups[row["exact_body_sha256"]].append(row)
    pairs, seen = [], set()
    def add(left, right, relation, reason, similarity=None):
        key = tuple(sorted((left["document_id"], right["document_id"])))
        if key in seen:
            return
        seen.add(key)
        lp, rp = texts[left["document_id"]], texts[right["document_id"]]
        left_numbers = set(NUMBER.findall(page_slice(lp, 3, 18000)))
        right_numbers = set(NUMBER.findall(page_slice(rp, 3, 18000)))
        common = left_numbers & right_numbers
        pairs.append({"pair_id": len(pairs)+1, "left_document_id": left["document_id"], "right_document_id": right["document_id"], "left_pdf_path": left["original_pdf_path"], "right_pdf_path": right["original_pdf_path"], "relation_candidate": relation, "reason": reason, "similarity_for_retrieval_only": similarity,
                      "confirmed_same_pdf_sha": left["pdf_sha256"] == right["pdf_sha256"], "confirmed_same_normalized_page_sequence": left["exact_body_sha256"] == right["exact_body_sha256"],
                      "left_evidence": evidence(lp), "right_evidence": evidence(rp), "left_page_input": left["source_references"]["page_input"], "right_page_input": right["source_references"]["page_input"],
                      "numeric_comparison_scope": "First three prepared pages, up to18000 chars; retain signs/decimals/units. Not a complete factual-difference audit",
                      "shared_numeric_tokens": sorted(common)[:15], "left_only_numeric_tokens": sorted(left_numbers-right_numbers)[:15], "right_only_numeric_tokens": sorted(right_numbers-left_numbers)[:15],
                      "left_report_date": left["report_date"], "right_report_date": right["report_date"], "action": "PRESERVE_BOTH_NO_MERGE", "confirmation_status": "EXACT_NORMALIZED_TEXT_PROVEN" if relation == "SAME_NORMALIZED_TEXT" else "CANDIDATE_REQUIRES_SOURCE_REVIEW"})
    for group in sorted(groups.values(), key=lambda g: (-len(g), g[0]["document_id"])):
        if len(group) > 1:
            for other in group[1:2]:
                add(group[0], other, "SAME_NORMALIZED_TEXT", "Different file identities; exact NFC/whitespace-collapse normalized page text sequence matches. Retain both source records.", 1.0)
                if len(pairs) >= 3:
                    break
        if len(pairs) >= 3:
            break
    # Candidate title groups are filename hints only; evidence and text diffs shown.
    titlegrams = {r["document_id"]: _ngrams(re.sub(r"\d{6,8}|20\d{2}年\d+月\d+日", "", r["filename_candidate_title"])) for r in ready}
    by_theme = defaultdict(list)
    for row in ready:
        for label in row["industry_theme_candidates"][:3]:
            by_theme[label].append(row)
    proposals = []
    for group in by_theme.values():
        group = sorted(group, key=lambda r: r["document_id"])
        # At most 25 neighbors per item; no all-pairs embedding/scoring service.
        for i, left in enumerate(group):
            for right in group[i+1:i+26]:
                score = jaccard(titlegrams[left["document_id"]], titlegrams[right["document_id"]])
                if score >= .30:
                    proposals.append((score, left, right))
    for score, left, right in sorted(proposals, key=lambda p: (-p[0], p[1]["document_id"], p[2]["document_id"])):
        if len(pairs) >= min(7, count):
            break
        if left["exact_body_sha256"] == right["exact_body_sha256"]:
            continue
        add(left, right, "SIMILAR_OR_VERSION_CANDIDATE", "Title/topic retrieval overlap; page text differs. Repost versus revision is unresolved, never merged.", round(score, 4))
    for theme, group in sorted(by_theme.items()):
        if len(pairs) >= count:
            break
        if len(group) < 2:
            continue
        left = min(group, key=lambda r: r["document_id"])
        others = [r for r in group if r["document_id"] != left["document_id"] and r["exact_body_sha256"] != left["exact_body_sha256"] and jaccard(titlegrams[left["document_id"]], titlegrams[r["document_id"]]) < .25]
        if others:
            right = min(others, key=lambda r: r["document_id"])
            add(left, right, "SAME_THEME_DISTINCT_MATERIAL", f"Both prepared texts mention existing theme {theme}; different text and low title overlap. Topic similarity does not justify deduplication.")
    if len(pairs) != count:
        raise ValueError("INSUFFICIENT_DISTINCT_REAL_RELATION_PAIRS")
    return pairs, {"same_pdf_sha_groups": sum(n>1 for n in Counter(r["pdf_sha256"] for r in ready).values()), "same_normalized_page_sequence_groups": sum(len(g)>1 for g in groups.values()), "ready_body_identity_denominator": len(ready), "exact_text_pair_count_in_sample": sum(p["relation_candidate"]=="SAME_NORMALIZED_TEXT" for p in pairs), "merged_or_deleted": 0}


def apply_relation_reviews(pairs, review_path):
    if review_path is None:
        return pairs, None
    review, raw = read_json(review_path)
    items = review["pairs"]
    if len(items) != len(pairs) or review.get("manifest_sha256") != MANIFEST_SHA:
        raise ValueError("RELATION_REVIEW_COVERAGE_MISMATCH")
    result = []
    for pair, item in zip(pairs, items, strict=True):
        if any(item.get(key) != pair.get(key) for key in ("pair_id", "left_document_id", "right_document_id")):
            raise ValueError("RELATION_REVIEW_IDENTITY_MISMATCH")
        relation = item["reviewed_relation"]
        if relation == "SAME_NORMALIZED_TEXT" and not pair["confirmed_same_normalized_page_sequence"]:
            raise ValueError("RELATION_REVIEW_FALSE_EXACT_DUPLICATE")
        if relation not in {"SAME_NORMALIZED_TEXT", "SIMILAR_REPOST_CANDIDATE", "DIFFERENT_CONTENT_VERSION_CANDIDATE", "SAME_TAG_ONLY_DISTINCT_MATERIAL"}:
            raise ValueError("RELATION_REVIEW_LABEL_INVALID")
        for side in ("left", "right"):
            page_input, _ = read_json(Path(pair[side+"_page_input"]["path"]), pair[side+"_page_input"]["sha256"])
            ref = item[side+"_evidence"]
            number = ref["page_number"]
            if not 1 <= number <= len(page_input["pages"]):
                raise ValueError("RELATION_REVIEW_PAGE_NUMBER_INVALID")
            text = page_input["pages"][number-1]["text"]
            if sha(text.encode()) != ref["page_text_sha256"] or ref["excerpt"] not in re.sub(r"\s+", " ", text).strip():
                raise ValueError("RELATION_REVIEW_EXCERPT_MISMATCH")
        result.append({**pair, "relation_candidate": relation, "reason": item["reason"], "left_evidence": item["left_evidence"], "right_evidence": item["right_evidence"], "difference_review": item["difference_review"], "writer_verification": "WRITER_REVIEWED_PENDING_INDEPENDENT_REVIEW"})
    return result, {"path": str(review_path), "sha256": sha(raw)}


def csv_value(value):
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else "" if value is None else str(value)
    return "'"+text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fields})


def build_stats(rows, sample_ids, pairs_summary, snapshot, taxonomy):
    def count(key):
        return dict(sorted(Counter(str(r.get(key)) for r in rows).items()))
    def multi(key):
        return dict(sorted(Counter(tag for r in rows for tag in set(r.get(key, []))).items()))
    return {"schema": SCHEMA, "asof_utc": snapshot["asof_utc"], "denominator": 2209,
            "ocr_status_counts": count("ocr_status_asof"), "primary_type_candidate_counts": count("primary_type_candidate"),
            "route_candidate_counts": count("route_candidate"), "language_candidate_counts": count("language_candidate"),
            "multilabel_counts_nonexclusive": {"industry_themes": multi("industry_theme_candidates"), "markets_mentioned": multi("markets_mentioned_candidate"), "collection_dates": multi("collection_dates"), "repost_channels": multi("repost_channels_candidate")},
            "source_institution_candidate_counts": count("original_institution_candidate"), "report_date_status_counts": dict(Counter(r["report_date"]["status"] for r in rows)),
            "dictionary": taxonomy, "sample_count": len(sample_ids), "dedup": pairs_summary,
            "boundary": "All2209 identity rows reconciled; labels are rule candidates, not full-cohort semantic acceptance. Pending is not completed. Multilabel counts need not sum2209.",
            "model_requests": 0, "ocr_calls": 0, "downloads": 0, "merges": 0, "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def apply_sample_reviews(rows_by_id, sample_ids, review_path, texts=None):
    if review_path is None:
        return [dict(rows_by_id[k], sample_verification="RULE_CANDIDATE_NOT_WRITER_REVIEWED") for k in sample_ids], None
    review, raw = read_json(review_path)
    if review.get("sample_document_ids") != sample_ids or review.get("manifest_sha256") != MANIFEST_SHA:
        raise ValueError("SAMPLE_REVIEW_SELECTION_BINDING_MISMATCH")
    overrides = review["documents"]
    if set(overrides) != set(sample_ids):
        raise ValueError("SAMPLE_REVIEW_COVERAGE_MISMATCH")
    result = []
    for document_id in sample_ids:
        row = rows_by_id[document_id]
        item = overrides[document_id]
        if item["primary_type"] not in PRIMARY or item["route"] not in ROUTES:
            raise ValueError("SAMPLE_REVIEW_LABEL_INVALID")
        if item["route"] == "DEEP_RESEARCH_CANDIDATE" and not item.get("explicit_research_question"):
            raise ValueError("NO_RESEARCH_QUESTION_FOR_DEEP_ROUTE")
        allowed_hashes = {p["page_number"]: p["text_sha256"] for p in row["source_references"]["pages"]}
        for ref in item["evidence"]:
            if allowed_hashes.get(ref["page_number"]) != ref["page_text_sha256"]:
                raise ValueError("SAMPLE_REVIEW_PAGE_EVIDENCE_MISMATCH")
            if texts is None or ref["excerpt"] not in re.sub(r"\s+", " ", texts[document_id][ref["page_number"]-1]["text"]).strip():
                raise ValueError("SAMPLE_REVIEW_EXCERPT_NOT_IN_SOURCE")
        result.append({**row, "sample_verification": "WRITER_REVIEWED_PENDING_INDEPENDENT_REVIEW", "sample_primary_type": item["primary_type"], "sample_subtype": item.get("subtype", row["subtype_candidate"]), "sample_reason": item["reason"], "sample_evidence": item["evidence"], "sample_route": item["route"], "sample_route_reason": item["route_reason"], "sample_date": item.get("report_date", {"value": None, "status": "UNKNOWN"}), "sample_original_institution": item.get("original_institution"), "sample_main_research_companies": item.get("main_research_companies", []), "sample_mentioned_companies": item.get("mentioned_companies", []), "sample_certainty": item["certainty"], "stock_code_status": "UNKNOWN_NO_GUESSED_MAPPING"})
    return result, {"path": str(review_path), "sha256": sha(raw)}


def render_report(path, stats, sample, pairs):
    e = lambda value: html.escape(str(value if value is not None else "未知"), quote=True)
    def cite(row, ref):
        if not ref:
            return "正文证据待核"
        href = quote(row["original_pdf_path"], safe="/")+"#page="+str(ref["page_number"])
        return f'<blockquote>{e(ref["excerpt"])}</blockquote><a href="{e(href)}">原 PDF 第{ref["page_number"]}页</a><small>PDF SHA {e(row["pdf_sha256"])}<br>page text SHA {e(ref["page_text_sha256"])}</small>'
    cards = []
    byid = {r["document_id"]: r for r in sample}
    for row in sample:
        label = row.get("sample_primary_type", row["primary_type_candidate"])
        route = row.get("sample_route", row["route_candidate"])
        refs = row.get("sample_evidence") or [row["classification_evidence"]]
        cards.append(f'<details class="sample" data-type="{e(label)}" data-route="{e(route)}" data-status="{e(row["ocr_status_asof"])}"><summary><b>{e(label)}</b> · {e(row["filename_candidate_title"])} <span>{e(route)}</span></summary><p>{e(row.get("sample_reason", row["classification_reason"]))}</p><p>核验状态：{e(row["sample_verification"])}；OCR={e(row["ocr_status_asof"])}；{e(row["page_count"])}页；语言候选={e(row["language_candidate"])}；机构={e(row.get("sample_original_institution", row["original_institution_candidate"]))}</p><p>发布日期：{e(row.get("sample_date", row["report_date"]))}；采集目录日期：{e(row["collection_dates"])}（不作为发布日期）</p><p>主研究公司：{e(row.get("sample_main_research_companies", []))}；提及公司：{e(row.get("sample_mentioned_companies", []))}；证券代码：未知，不猜配</p><p>主题候选：{e(row["industry_theme_candidates"])}；分流理由：{e(row.get("sample_route_reason", row["route_reason"]))}</p>{"".join(cite(row, ref) for ref in refs if ref)}<small>document_id={e(row["document_id"])}<br>冻结文本输入={e(row["source_references"]["page_input"])}</small></details>')
    pair_cards = []
    for pair in pairs:
        pair_cards.append(f'<details class="pair"><summary>关系样例 {pair["pair_id"]} · {e(pair["relation_candidate"])}</summary><p>{e(pair["reason"])}</p><p>左 {e(pair["left_document_id"])}<br>右 {e(pair["right_document_id"])}</p><p>同 PDF SHA={e(pair["confirmed_same_pdf_sha"])}；同归一化分页正文={e(pair["confirmed_same_normalized_page_sequence"])}；动作：保留双方、不合并</p><blockquote>左 p.{pair["left_evidence"]["page_number"]}：{e(pair["left_evidence"]["excerpt"])}</blockquote><blockquote>右 p.{pair["right_evidence"]["page_number"]}：{e(pair["right_evidence"]["excerpt"])}</blockquote><p>差异核验：{e(pair.get("difference_review", "候选，尚待正文核对"))}</p><p>左独有数字/日期：{e(pair["left_only_numeric_tokens"])}<br>右独有数字/日期：{e(pair["right_only_numeric_tokens"])}<br>对比边界：{e(pair["numeric_comparison_scope"])}</p><a href="{e(quote(pair["left_pdf_path"],safe="/")+"#page="+str(pair["left_evidence"]["page_number"]))}">左原PDF p.{pair["left_evidence"]["page_number"]}</a> · <a href="{e(quote(pair["right_pdf_path"],safe="/")+"#page="+str(pair["right_evidence"]["page_number"]))}">右原PDF p.{pair["right_evidence"]["page_number"]}</a><small>左page text SHA {e(pair["left_evidence"]["page_text_sha256"])}<br>右page text SHA {e(pair["right_evidence"]["page_text_sha256"])}<br>左输入 {e(pair["left_page_input"])}<br>右输入 {e(pair["right_page_input"])}</small></details>')
    status = " · ".join(f'{e(k)} {v}' for k, v in stats["ocr_status_counts"].items())
    distribution = "".join(f'<tr><td>{e(k)}</td><td>{v}</td></tr>' for k, v in stats["primary_type_candidate_counts"].items())
    sample_distribution = "".join(f'<tr><td>{e(k)}</td><td>{v["sample_count"]}</td><td>{v["source_or_content_uncertain"]}</td></tr>' for k,v in stats["sample_unknown_by_class"].items() if v["sample_count"])
    multi_stats = e(json.dumps(stats["multilabel_counts_nonexclusive"],ensure_ascii=False))
    company_stats = e(json.dumps(stats["sample_main_company_counts_nonexclusive"],ensure_ascii=False))
    source_stats = e(json.dumps({"来源机构候选":stats["source_institution_candidate_counts"],"日期证据状态":stats["report_date_status_counts"],"语言候选":stats["language_candidate_counts"]},ensure_ascii=False))
    ocr_options = "".join(f"<option>{e(k)}</option>" for k in sorted({row["ocr_status_asof"] for row in sample}))
    options = "".join(f'<option>{e(k)}</option>' for k in PRIMARY)
    doc = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PDF 分类与去重看板 · 2026-10-20</title><style>body{{font:16px/1.65 system-ui,sans-serif;background:#f5f7fa;color:#172b40;max-width:1150px;margin:0 auto;padding:28px}}h1{{font-size:28px}}h2{{margin-top:36px}}.banner,details,table{{background:white;border:1px solid #d8e0e8;border-radius:9px;padding:16px;margin:12px 0}}summary{{cursor:pointer}}summary span{{float:right;font-size:12px;color:#47657e}}small{{display:block;overflow-wrap:anywhere;color:#526677}}blockquote{{border-left:3px solid #698ea8;padding-left:12px;margin:15px 0;background:#f7fafc}}input,select{{padding:10px;margin:6px 8px 6px 0;max-width:90%}}table{{border-collapse:collapse;min-width:380px}}td,th{{padding:7px 18px;text-align:left;border-bottom:1px solid #e4e9ee}}a{{color:#16638e}}.warn{{color:#8b4a12}}[hidden]{{display:none!important}}</style><body><h1>PDF 分类与去重看板</h1><div class="banner"><b>2209 个原始身份全部对账；本页展示60份样例、10对真实材料关系。</b><p>固定快照 {e(stats["asof_utc"])}（UTC）：{status}。只反映该时点，不追随仍在运行的OCR。</p><p class="warn">全量标签为规则候选；样例 Writer 核验等待独立 Reviewer。无模型分析、无OCR重跑、无删除合并、无买入信号；未设研究问题，不自动判高价值。行业/公司/主题为多标签，统计不相加为2209。</p><p><b>身份2209</b> · <b>快照READY {stats["ocr_status_counts"].get("READY",0)}</b> · <b>快照待完成 {stats["ocr_status_counts"].get("PENDING",0)}</b> · <b>样例60 / 关系10对</b></p><a href="ledger.csv">完整台账 CSV</a> · <a href="ledger.json">完整台账 JSON</a> · <a href="statistics.json">统计 JSON</a> · <a href="sample60.csv">60份样例 CSV</a> · <a href="relations10.json">10对证据 JSON</a></div><h2>全量规则候选主类（互斥，含待分类）</h2><table><tr><th>类型</th><th>文件数 / 2209</th></tr>{distribution}</table><p>确证相同分页正文组：{stats["dedup"]["same_normalized_page_sequence_groups"]} / {stats["dedup"]["ready_body_identity_denominator"]} 份READY正文；相同文件SHA组为0（manifest内2209唯一PDF身份）。没有真实正例时不会补造重复。</p><h2>样例主类与待核率</h2><table><tr><th>Writer标签</th><th>样本数/60</th><th>来源或内容仍待核</th></tr>{sample_distribution}</table><p>独立分类准确率：尚未评分。样例为覆盖/边界抽样，不代表总体频率或全量准确率。主类和署名识别不等于报告事实已验收；来源或OCR质量待核单列。公司披露、咨询仅各1份，按当前检出事实保留，不补造5份。</p><details><summary>多标签覆盖与公司对象（非互斥计数）</summary><p>{multi_stats}</p><p>样例主研究公司：{company_stats}。主对象与提及对象分开；全量实体尚未核验，证券代码仍为未知。</p></details><details><summary>来源、报告日期与语言覆盖</summary><p>{source_stats}</p><p>机构与语言为规则候选；机构名称是正文归属声明，不等于官方来源真实性已认证。转载渠道单列。下载目录/转录生成时间不充当报告发布日期。</p></details><h2>60份可筛选样例</h2><input id="q" placeholder="搜索标题、公司、主题、证据"><select id="kind"><option value="">全部主类</option>{options}</select><select id="route"><option value="">全部分流</option>{"".join(f"<option>{x}</option>" for x in ROUTES)}</select><select id="ocr"><option value="">全部OCR状态</option>{ocr_options}</select><p id="visible"></p>{"".join(cards)}<h2>10对重复/转载/版本或同主题材料证据</h2><p>相似分数仅用于候选召回；数字、正负号、日期、单位保留。不同观点或数字不会自动合并。</p>{"".join(pair_cards)}<script>function filter(){{let q=document.getElementById('q').value.toLowerCase(),k=document.getElementById('kind').value,r=document.getElementById('route').value,o=document.getElementById('ocr').value,n=0;document.querySelectorAll('.sample').forEach(x=>{{let ok=(!q||x.textContent.toLowerCase().includes(q))&&(!k||x.dataset.type===k)&&(!r||x.dataset.route===r)&&(!o||x.dataset.status===o);x.hidden=!ok;if(ok)n++}});document.getElementById('visible').textContent='显示 '+n+' / 60'}}['q','kind','route','ocr'].forEach(id=>document.getElementById(id).addEventListener('input',filter));filter();</script></body></html>'''
    path.write_text(doc, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--taxonomy-source", type=Path)
    parser.add_argument("--sample-review", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--relation-review", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    out = args.output_root.resolve()
    # Only a derivative output root is written. It may never be an input/original root.
    if not out.is_relative_to(args.input_root.resolve().parent):
        raise ValueError("OUTPUT_MUST_STAY_IN_DERIVATIVE_EVIDENCE_ROOT")
    if out == args.prepared_root.resolve() or out.is_relative_to(args.prepared_root.resolve()):
        raise ValueError("OUTPUT_CANNOT_WRITE_PREPARED_ROOT")
    out.mkdir(parents=True, exist_ok=True)
    taxonomy_path = args.input_root / "industry-taxonomy.json"
    if args.taxonomy_source:
        taxonomy = freeze_taxonomy(args.taxonomy_source, taxonomy_path)
    else:
        taxonomy, _ = read_json(taxonomy_path)
    rows, texts, snapshot, index = load_frozen_inputs(args.input_root/"batch-manifest.json", args.input_root/"ocr-progress-snapshot.json", args.input_root/"snapshot-receipt.json", args.prepared_root, taxonomy)
    sample_ids, supply = select_sample(rows)
    if args.selection:
        selection, _ = read_json(args.selection)
        if selection.get("manifest_sha256") != MANIFEST_SHA or selection.get("progress_sha256") != snapshot["progress_sha256"]:
            raise ValueError("FROZEN_SELECTION_INPUT_MISMATCH")
        sample_ids = selection["sample_document_ids"]
        if len(sample_ids) != 60 or len(set(sample_ids)) != 60 or not set(sample_ids) <= {r["document_id"] for r in rows if r["source_references"]["page_input"]}:
            raise ValueError("FROZEN_SELECTION_COVERAGE_MISMATCH")
    byid = {r["document_id"]: r for r in rows}
    pairs, pair_summary = pairs_candidates(rows, texts)
    pairs, pair_review_ref = apply_relation_reviews(pairs, args.relation_review)
    pair_summary["writer_review_ref"] = pair_review_ref
    exact_groups = defaultdict(list)
    for row in rows:
        if row["exact_body_sha256"]:
            exact_groups[row["exact_body_sha256"]].append(row["document_id"])
    for digest, ids in exact_groups.items():
        if len(ids)>1:
            for item in ids:
                byid[item]["duplicate_group"] = "normalized-body:"+digest
    for pair in pairs:
        for side in ("left", "right"):
            record = byid[pair[side+"_document_id"]]
            record["relation_candidates"].append({"pair_id": pair["pair_id"], "other_document_id": pair[("right" if side=="left" else "left")+"_document_id"], "relation": pair["relation_candidate"], "action": "PRESERVE_BOTH_NO_MERGE"})
            record["relation_status"] = "EXACT_NORMALIZED_BODY_MATCH" if pair["confirmed_same_normalized_page_sequence"] else "RELATION_CANDIDATE_ONLY"
            if pair["relation_candidate"]=="DIFFERENT_CONTENT_VERSION_CANDIDATE":
                record["version_group"] = "candidate-pair:"+str(pair["pair_id"])
    sample, review_ref = apply_sample_reviews(byid, sample_ids, args.sample_review, texts)
    stats = build_stats(rows, sample_ids, pair_summary, snapshot, taxonomy)
    stats["sample_supply_by_candidate_class"] = supply
    stats["sample_writer_review_ref"] = review_ref
    stats["sample_candidate_class_counts"] = dict(Counter(byid[k]["primary_type_candidate"] for k in sample_ids))
    stats["sample_writer_class_counts"] = dict(Counter(r.get("sample_primary_type", "UNREVIEWED") for r in sample))
    stats["sample_certainty_counts"] = dict(Counter(r.get("sample_certainty", "UNREVIEWED") for r in sample))
    stats["sample_ocr_status_counts"] = dict(Counter(r["ocr_status_asof"] for r in sample))
    stats["sample_sampling_boundary"] = "Purposeful coverage/boundary sample, not random; sample class/quality proportions do not estimate population proportions or full-cohort accuracy"
    stats["sample_route_counts"] = dict(Counter(r.get("sample_route", r["route_candidate"]) for r in sample))
    stats["sample_main_company_counts_nonexclusive"] = dict(Counter(name for r in sample for name in set(r.get("sample_main_research_companies", []))))
    stats["sample_mentioned_company_counts_nonexclusive"] = dict(Counter(name for r in sample for name in set(r.get("sample_mentioned_companies", []))))
    stats["sample_unknown_by_class"] = {label: {"sample_count": sum(r.get("sample_primary_type")==label for r in sample), "source_or_content_uncertain": sum(r.get("sample_primary_type")==label and (r.get("sample_certainty")!="TYPE_AND_SOURCE_IDENTIFIED" or r["ocr_status_asof"]!="READY") for r in sample)} for label in PRIMARY}
    stats["sample_rule_writer_label_disagreement_count"] = sum(r.get("sample_primary_type",r["primary_type_candidate"])!=r["primary_type_candidate"] for r in sample)
    stats["sample_semantic_accuracy"] = "NOT_SCORED_INDEPENDENT_REVIEW_PENDING"
    assert sum(stats["ocr_status_counts"].values()) == sum(stats["primary_type_candidate_counts"].values()) == 2209
    write_json(out/"ledger.json", {"schema": SCHEMA, "snapshot": snapshot, "documents": rows})
    write_json(out/"frozen-text-index.json", {"snapshot": snapshot, "documents": index})
    write_json(out/"statistics.json", stats)
    write_json(out/"sample-selection.json", {"manifest_sha256": MANIFEST_SHA, "progress_sha256": snapshot["progress_sha256"], "algorithm": "frozen_selection_reused" if args.selection else "deterministic_class_min5_if_available_then_feature_coverage_v1", "sample_document_ids": sample_ids, "supply_by_candidate_class": supply, "class_shortfalls": {label: n for label,n in supply.items() if n<5}})
    write_json(out/"sample60.json", {"schema": SCHEMA, "documents": sample})
    write_json(out/"relations10.json", {"summary": pair_summary, "pairs": pairs})
    fields = [k for k in rows[0] if k not in {"source_references", "industry_evidence"}]
    write_csv(out/"ledger.csv", rows, fields)
    sample_fields = fields+["sample_verification","sample_primary_type","sample_subtype","sample_reason","sample_evidence","sample_route","sample_route_reason","sample_date","sample_original_institution","sample_main_research_companies","sample_mentioned_companies","sample_certainty"]
    write_csv(out/"sample60.csv", sample, sample_fields)
    render_report(out/"report.html", stats, sample, pairs)
    md = ["# PDF 分类样例快照", f"asof UTC: {snapshot['asof_utc']}", "", "身份分母2209；全量为规则候选，独立语义验收尚未完成。", "", "## OCR快照", "", *[f"- {k}: {v}" for k,v in stats["ocr_status_counts"].items()], "", "## 主类候选", "", *[f"- {k}: {v}" for k,v in stats["primary_type_candidate_counts"].items()], "", "[交互筛选报告](report.html) · [60份CSV](sample60.csv) · [完整台账](ledger.csv)", "", "## 样例", ""]
    for i,row in enumerate(sample,1):
        md += [f"### {i}. {row['filename_candidate_title']}", "", f"{row.get('sample_primary_type',row['primary_type_candidate'])} · {row.get('sample_route',row['route_candidate'])} · {row['sample_verification']}", "", row.get('sample_reason',row['classification_reason']), "", f"document_id: `{row['document_id']}`", ""]
        for ref in row.get("sample_evidence") or [row["classification_evidence"]]:
            if ref:
                md += [f"> p.{ref['page_number']} {ref['excerpt']}", "", f"page text SHA `{ref['page_text_sha256']}`", ""]
    relation_md = ["# 10对真实材料关系样例", "", "所有关系保留双方；相似检索分数不能作为合并条件。原始PDF及页文本SHA以relations10.json为准。", ""]
    for pair in pairs:
        relation_md += [f"## {pair['pair_id']}. {pair['relation_candidate']}", "", pair['reason'], "", pair.get('difference_review', '候选尚待原文核对'), ""]
        for side in ('left', 'right'):
            ref = pair[side+'_evidence']
            relation_md += [f"{side}: `{pair[side+'_document_id']}`", "", f"> p.{ref['page_number']} {ref['excerpt']}", "", f"page text SHA `{ref['page_text_sha256']}`", ""]
    (out/"relations10.md").write_text("\n".join(relation_md)+"\n",encoding="utf-8")
    (out/"sample60.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    (out/"statistics.md").write_text("\n".join(md[:md.index("## 样例")])+"\n",encoding="utf-8")
    artifacts = {str(p.relative_to(out)): {"sha256":sha(p.read_bytes()),"bytes":p.stat().st_size} for p in out.iterdir() if p.is_file() and p.name != "BUILD.json"}
    write_json(out/"BUILD.json", {"schema":SCHEMA,"source_sha256":sha(Path(__file__).read_bytes()),"manifest_sha256":MANIFEST_SHA,"snapshot":snapshot,"runtime_seconds":round(time.monotonic()-started,3),"runtime":"stdlib offline","sample_review":review_ref,"artifacts":artifacts,"model_requests":0,"ocr_calls":0,"downloads":0,"deleted_or_merged":0})
    print(json.dumps({"ledger":2209,"snapshot":stats["ocr_status_counts"],"primary":stats["primary_type_candidate_counts"],"sample":stats["sample_candidate_class_counts"],"pairs":pair_summary,"output":str(out)},ensure_ascii=False))


if __name__ == "__main__":
    main()
