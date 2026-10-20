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
import sys
from datetime import datetime, timezone
import unicodedata
from urllib.parse import quote

MANIFEST_SHA = "e739287d70abaafe428dabe08fb1025308d195dd717053f8189fe5f84ace25c9"
SCHEMA = "v4.pdf_classification_sample.v1"
RULES_VERSION = "full-body-structure-v5-anchored-cues-20261020"
PRIMARY = ("券商/研究机构研究", "公司一手披露", "调研/会议记录", "新闻/资讯解读", "数据/白皮书/咨询报告", "教程/方法/其他", "待分类")
ROUTES = ("SAVE", "REUSE_CANDIDATE", "REVIEW", "LIGHT_EXTRACTION_CANDIDATE", "DEEP_RESEARCH_CANDIDATE")
INSTITUTIONS = ("Morgan Stanley", "Goldman Sachs", "J.P. Morgan", "JPMorgan", "Jefferies", "UBS", "Citi Research", "Barclays", "Bernstein", "Deutsche Bank", "BofA", "Nomura", "Macquarie", "DBS", "国盛证券", "国金证券", "中信证券", "中信建投", "华泰证券", "招商证券", "光大证券", "东吴证券", "开源证券", "国联民生", "民生证券", "中泰证券", "浙商证券", "中金公司", "中银证券", "长江证券", "东北证券", "西南证券", "天风证券", "兴业证券", "国信证券", "申万宏源", "广发证券", "华福证券", "平安证券", "华创证券", "华安证券", "华西证券", "财通证券", "东方证券", "国泰海通", "信达证券", "银河证券", "东兴证券", "国投证券", "华源证券", "爱建证券", "招银国际", "招銀国际", "CMB INTERNATIONAL", "HUAAN SECURITIES", "AIJIAN SECURITIES", "摩根大通", "J.P.Morgan", "财信证券", "CHASING SECURITIES", "PING AN SECURITIES")
STRONG_NEWS = r"Bloomberg[\s\S]{0,60}News Story|【彭博】|风口研报|财联社|早知道|盘前必读|盘中资讯|今日早盘|当下市场重点题材|题材复盘|投资舆情|盘前热点|今日财经|今日题材"
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


def derivative_guide(text):
    return sum(bool(re.search(marker, text)) for marker in (r"全文摘要", r"章节速览", r"思维导图")) >= 2


def publisher_candidate(pages, primary):
    """Cover branding only; body mentions, citations and guide titles are not bylines."""
    if primary not in (PRIMARY[0], PRIMARY[3], PRIMARY[4]):
        return None, None
    short = page_slice(pages, 1, 2200)
    if derivative_guide(short):
        return None, None
    if primary == PRIMARY[3]:
        for label, pattern in (("Bloomberg", r"Bloomberg[\s\S]{0,60}News Story|【彭博】"), ("财联社", r"(?m)^\s*(?:来源[：:]\s*)?财联社(?:\s*$|[\s（(]|记者|[0-9一二三四五六七八九十]+月)")):
            ref = evidence(pages[:1], pattern)
            if ref:
                return label, ref
        return None, None
    if primary == PRIMARY[4]:
        names = ("Deloitte", "德勤", "McKinsey", "麦肯锡", "PwC", "普华永道", "中国信通院", "中国信息通信研究院", "QuestMobile")
    else:
        names = INSTITUTIONS
    aliases = {"CHASING SECURITIES":"财信证券", "PING AN SECURITIES":"平安证券", "HUAAN SECURITIES":"华安证券", "AIJIAN SECURITIES":"爱建证券", "CMB INTERNATIONAL":"招银国际", "招銀国际":"招银国际", "J.P.Morgan":"J.P. Morgan", "JPMorgan":"J.P. Morgan", "摩根大通":"J.P. Morgan", "德勤":"Deloitte", "麦肯锡":"McKinsey", "普华永道":"PwC"}
    # Standalone cover brand lines or explicitly branded research headings.
    candidates = {}
    for name in names:
        pattern = institution_pattern(name)
        for line in short.splitlines():
            institute_heading = re.fullmatch(r"[ \t]*"+pattern+r"研究(?:院|所)(?:[\u3400-\u9fff]{0,12}研究(?:团队|小组))?[ \t]*", line)
            account_heading = (re.fullmatch(r"[ \t]*"+pattern+r"研究微信服务号[ \t]*", line)
                               and re.search(r"(?m)^[ \t]*(?:证券分析师|证券研究报告|SWS RESEARCH)[ \t]*$", short, re.I))
            if re.search(pattern, line, re.I) and (institute_heading or account_heading or re.fullmatch(r"\s*"+pattern+r"[\s.,·|/-]*(?:RESEARCH|证券研究所|研究报告)?[\s.,·|/-]*", line, re.I) or re.fullmatch(r"[ \t]*"+pattern+r"[ \t|·/-]*(?:研究(?:所|报告)?|RESEARCH|环球市场)[ \t.,·|/-]*", line, re.I)):
                canonical = aliases.get(name, name)
                candidates[canonical] = evidence(pages[:1], re.escape(line.strip()))
                break
    if len(candidates) == 1:
        return next(iter(candidates.items()))
    return None, None


def classification_binding(document, receipt, pages, taxonomy, refs):
    return {"document_id": document["document_id"], "pdf_sha256": document["pdf_sha256"],
            "page_text_sequence_sha256": body_sha(pages) if pages else None,
            "page_input_sha256": (refs["page_input"] or {}).get("sha256"),
            "receipt_sha256": (refs["receipt"] or {}).get("sha256"),
            "status": (receipt or {}).get("status", "PENDING"), "rules_version": RULES_VERSION,
            "source_code_sha256": sha(Path(__file__).read_bytes()),
            "taxonomy_sha256": sha(json_raw(taxonomy)), "document_identity_sha256": sha(json_raw(document))}


def cached_metadata(document, receipt, pages, taxonomy, refs, cache_root=None, metrics=None):
    binding = classification_binding(document, receipt, pages, taxonomy, refs)
    key = sha(json_raw(binding))
    path = cache_root / key[:2] / (key+".json") if cache_root else None
    if path and path.exists():
        cached, _ = read_json(path)
        if cached.get("binding") != binding or sha(json_raw(cached["metadata"])) != cached.get("metadata_sha256"):
            raise ValueError("CLASSIFICATION_CACHE_BINDING_OR_CONTENT_MISMATCH")
        metadata = cached["metadata"]
        outcome = "reused"
    else:
        metadata = candidate_metadata(document, receipt, pages, taxonomy)
        metadata["company_entity_evidence"] = company_entities(pages, metadata["primary_type_candidate"])
        metadata["main_research_companies"] = [x["name"] for x in metadata["company_entity_evidence"] if x["role"] == "main_header_candidate"]
        metadata["mentioned_companies"] = [x["name"] for x in metadata["company_entity_evidence"] if x["role"] == "mentioned_literal_candidate"]
        metadata["company_status"] = "LITERAL_BODY_ENTITY_CANDIDATES_NO_STOCK_MAPPING" if metadata["company_entity_evidence"] else "UNKNOWN_PENDING_ENTITY_REVIEW"
        metadata["main_company_status"] = "LITERAL_HEADER_CANDIDATE_UNVERIFIED" if metadata["main_research_companies"] else "UNKNOWN_NOT_EXTRACTED"
        metadata["mentioned_company_status"] = "UNKNOWN_NOT_EXTRACTED"
        metadata["body_quality_metrics"] = {"page_count":len(pages),"empty_page_count":sum(not p["text"].strip() for p in pages),"replacement_character_count":sum(p["text"].count("\ufffd") for p in pages),"scope":"mechanical text metrics only; numerical fidelity and source authenticity unverified"}
        metadata["classification_binding"] = binding
        metadata["classification_cache_key"] = key
        if path:
            write_json(path, {"binding": binding, "metadata_sha256": sha(json_raw(metadata)), "metadata": metadata})
        outcome = "classified"
    if metrics is not None:
        metrics[outcome] = metrics.get(outcome, 0)+1
        metrics.setdefault(outcome+"_document_ids", []).append(document["document_id"])
    return metadata


def company_entities(pages, primary):
    # Literal cover company-name + ticker-like text is only an entity hint. Never
    # validate/assign the nearby number as a stock code or infer issuer industry.
    result = []
    if not pages:
        return result
    for match in re.finditer(r"(?m)^\s*([\u3400-\u9fffA-Za-z][\u3400-\u9fffA-Za-z .&-]{1,35})\s*[（(]\s*(?:\d{4,6}(?:\.[A-Z]{1,3})?)\s*[）)]", pages[0]["text"][:1800]):
        name = match.group(1).strip()
        if any(v in name for v in ("证券", "指数", "资料", "来源")):
            continue
        result.append({"name":name,"role":"main_header_candidate","evidence":evidence(pages[:1],re.escape(match.group(0).strip())),"identity_status":"LITERAL_NAME_ONLY_NO_CODE_VALIDATION"})
    return result[:3]


def owned_news_marker(pages):
    """A source-owned column/byline, never a prose mention of a newswire."""
    head = page_slice(pages, 1, 2000)
    columns = r"风口研报|九点特供|盘中宝|狙击龙虎榜|点金互动易|电报解读|季报高增长|脱水研报|财联社早知道|早知道|机构龙虎榜解读|公告全知道|掘金行业龙头|研选|玩转ETF"
    # Generic “机构调研” is a column only with an enclosed heading or a
    # standalone heading plus source-owned news context, never “机构调研是…”.
    survey_column = r"(?m)^[ \t]*[【\[（(]机构调研[】\]）)]"
    if re.search(survey_column, head):
        return survey_column
    if re.search(r"(?m)^[ \t]*机构调研[ \t]*$", head) and re.search(r"财联社|电报内容|xuangu(?:tong)?\.com\.cn", head, re.I):
        return r"(?m)^[ \t]*机构调研[ \t]*$"
    patterns = [r"(?m)^\s*[【\[（(]?(?:"+columns+r")", r"(?m)^\s*[^\n]{0,160}(?:脱水研报|强势股脱水)",
                r"xuangu(?:tong)?\.com\.cn|本文来自持牌证券机构|研报深度复盘",
                r"(?m)^\s*[©CＣ]?财联社资讯获悉", r"(?m)^\s*[©CＣ]?财联社(?:[0-9一二三四五六七八九十]+月|记者)",
                r"Bloomberg[\s\S]{0,60}News Story|【彭博】"]
    for pattern in patterns:
        if re.search(pattern, head, re.I):
            return pattern
    if re.search(r"(?m)^\s*[©CＣ]?财联社\s*$", head) and re.search(r"电报内容|题材解读|大头条|今日精选|市场大热点|互动易情绪指标", head):
        return r"(?m)^\s*[©CＣ]?财联社\s*$"
    return None


def publication_structure_marker(pages):
    head = page_slice(pages, 1, 6000)
    support = r"分析师|执业|研究员|投资评级|评级|目标价|证券分析|本报告导读|投资要点|核心观点|策略跟踪报告|股票研究|S\d{12}|SAC|Analyst|Rating|Target|Disclosures"
    explicit = r"(?m)^\s*[•·●]*\s*(?:证券研究报告|策略研究报告|Equity Research|Investment Research|Global Research)"
    if re.search(explicit, head, re.I) and re.search(support, page_slice(pages, 2, 16000), re.I):
        return explicit
    record_title = any(re.fullmatch(r"\s*[^\n。；;]{0,40}(?:"+MEETING+r")(?:\s*|[：:|].{0,80})",line,re.I) and not re.search(r"引用|提及|参考|据|指出|认为",line)
                       for line in head[:900].splitlines()[:15])
    if record_title:
        return None
    brand = r"(?m)^\s*(?:[^\n]{1,22}证券(?:股份有限公司|有限公司)?|[A-Z .,&]{2,60}SECURITIES(?:[A-Z .,&]{0,25})?)\s*$"
    if re.search(brand, head[:2000], re.I) and re.search(support, head, re.I):
        return brand
    issuer, _ref = publisher_candidate(pages, PRIMARY[0])
    localized_heading = r"(?m)^[ \t]*(?:(?:中国(?:[ \t]*A股)?|亚洲|香港|全球)[ \t]*)?(?:股票策略|市场策略|证券研究|行业研究)[ \t]*$"
    if issuer and re.search(localized_heading, head[:1600]):
        return localized_heading
    institute_heading = r"(?m)^[ \t]*[^\n]{1,22}证券研究(?:院|所)(?:[\u3400-\u9fff]{0,12}研究(?:团队|小组))?[ \t]*$"
    team_heading = r"(?m)^[ \t]*[\u3400-\u9fff]{0,30}研究(?:团队|小组)[ \t]*$"
    if issuer and re.search(institute_heading, head[:1600]) and re.search(team_heading, head[:1600]):
        return institute_heading
    return None


def disposition(row):
    status = row["ocr_status_asof"]
    if status == "PENDING":
        return "WAITING_OCR", "待OCR", "固定快照尚无终态准备记录；尚未取得正文，不属于正文证据不足"
    if status == "FAILED":
        return "EXTRACTION_FAILED", "提取失败", "原准备记录为FAILED；保留失败身份，待原OCR owner处置，不以空正文推断材料形式"
    if row.get("quality_flags") or status == "READY" and row["text_characters"] < 80:
        return "READY_QUALITY_REVIEW", row["primary_type_candidate"] if row["primary_type_candidate"] != PRIMARY[6] else "正文质量待核", "已有正文但过短或存在有证据的可读性异常；原READY状态不改，质量与材料形式分开复核"
    if row["primary_type_candidate"] == PRIMARY[6]:
        return "QUARANTINED_FORM_REVIEW" if status == "QUARANTINED" else "READY_FORM_REVIEW", "待核分类", "已读取逐页正文；未识别可靠出版或记录结构，需按原页人工核材料形式，机构未知不单独构成阻断"
    return "FORM_CANDIDATE", row["primary_type_candidate"], row["classification_reason"]


def primary_candidate(pages):
    head = page_slice(pages, 2, 11000)
    short = page_slice(pages, 1, 3500)
    institutions = [name for name in INSTITUTIONS if re.search(institution_pattern(name), head, re.I)]
    if derivative_guide(short):
        return PRIMARY[5], "二手导读/摘要导出", r"全文摘要|章节速览|思维导图", "正文含摘要导出模板；标题提及机构不代表机构原文，来源与转写可靠性待核"
    news_marker = owned_news_marker(pages)
    if news_marker:
        return PRIMARY[3], "资讯栏目/研报摘要", news_marker, "正文栏目标题、采编署名或电报结构归属资讯；引述券商/咨询机构不改变二手资讯形式"
    if re.search(r"招股说明书",short) and re.search(r"首次公开发行|发行人声明|申报稿",page_slice(pages,3)):
        return PRIMARY[1], "招股说明书/申报材料", r"招股说明书", "正文声明招股说明书及首次公开发行/发行人信息；保荐券商是中介，不当作研报发行机构"
    publication_marker = publication_structure_marker(pages)
    if publication_marker:
        return PRIMARY[0], "研究报告/研究简报", publication_marker, "正文研究出版结构与分析师/评级/研究导读等共同支持材料形式；机构字典缺失独立保留unknown"
    if re.search(r"(?m)^\s*(?:KPMG|毕马威)\s*$", short, re.I) and re.search(r"IPO市场|报告|回顾", page_slice(pages, 2)):
        return PRIMARY[4], "咨询机构市场报告", r"KPMG|毕马威", "正文封面咨询品牌与市场回顾/报告结构共同支持咨询材料形式"
    cover_news = r"(?m)^\s*[【\[]?(?:风口研报|早知道|盘前必读|盘中资讯|今日早盘|题材复盘|投资舆情|盘前热点|今日财经|今日题材)|Bloomberg[\s\S]{0,60}News Story|【彭博】"
    if re.search(cover_news, short[:1000], re.I):
        return PRIMARY[3], "资讯栏目/题材线索", STRONG_NEWS, "正文出现明确资讯栏目或题材汇编结构"
    publication_form = r"(?m)^\s*(?:(?:(?:中国|香港|亚洲|全球|美国|欧洲|亚太)\s*)?证券研究(?:报告)?|Equity Research|SWS RESEARCH|产业研究报告|行业研究|公司覆盖|[^\n]{0,12}(?:策略|行业|公司|宏观)(?:点评|周报|日报|月报|深度|专题|研究))\s*$"
    if institutions and re.search(publication_form, short[:1800], re.I):
        return PRIMARY[0], "研究报告/策略/行业", re.escape(institutions[0]), "首页出版机构及研究报告结构明确；不会因引用会议纪要或白皮书改变材料性质"
    if re.search(r"(?m)^\s*(?:来源[：:]\s*)?财联社(?:\s*$|[\s（(]|记者|[0-9一二三四五六七八九十]+月)", short[:1000]):
        return PRIMARY[3], "资讯署名/电讯", r"(?m)^\s*(?:来源[：:]\s*)?财联社", "资讯正文署名或电讯行，不把据财联社引用视为出版机构"
    if re.search(r"发言人\s*\d{1,2}:\d{2}|说话人\s*\d|Speaker\s*\d+", short, re.I):
        return PRIMARY[2], "会议/访谈转录", r"发言人\s*\d{1,2}:\d{2}|说话人\s*\d|Speaker\s*\d+", "正文含发言人及时间戳；仅确认记录形式，不确认转录准确性或发言人身份"
    meeting_headline = next((line.strip() for line in short[:900].splitlines()[:12] if re.search(MEETING,line,re.I) and len(line.strip())<=100 and not re.search(r"引用|提及|参考|据|指出|认为|[。；;]",line)), None)
    if meeting_headline:
        return PRIMARY[2], "调研/会议记录", re.escape(meeting_headline), "首页标题含纪要/调研记录性质标记，排除正文引用；发言及记录身份仍需核验"
    if re.search(r"(?m)^\s*(?:Q\s*&\s*A|问答|问[:：]|Q[:：])", short) and not (institutions and re.search(BROKER, head, re.I)):
        return PRIMARY[2], "问答记录", r"Q\s*&\s*A|问答|问[:：]|Q[:：]", "正文问答结构；记录形式可识别，但发言人、原始出处与事实仍待核"
    if re.search(DATA, short[:1000], re.I) and not (institutions and re.search(r"证券研究报告", short)):
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
    if re.search(r"(?m)^\s*(?:行业近况|行业动态|热点速评|业绩预览|观点聚焦|投资建议)\s*$", short) and re.search(r"盈利预测|估值|风险|投资建议|评论", page_slice(pages, 3)):
        return PRIMARY[0], "研究简报/节录（机构待核）", r"行业近况|行业动态|热点速评|业绩预览|观点聚焦|投资建议", "正文有行业简报及建议/评论/估值等研究结构；不因缺机构署名而留空材料形式"
    if re.search(r"[（(]\s*\d{6}\s*[）)]",short[:500]) and all(re.search(v,short) for v in ("盈利预测","估值","风险")):
        return PRIMARY[0], "公司业绩研究简报/节录（机构待核）", r"盈利预测", "正文公司题名与盈利预测、估值、风险等研究章节共同支持业绩简报形式；不确认原机构或邻近证券代码映射"
    record_marker = r"(?m)^\s*(?:问答整理|Q\.?\s*&\s*A|Q8A|O&A|C&A|08[:：]A|[（(]28\.A|会议要点)(?:\s|$)|^\s*Q\d+[:：]|发言人\s*\d{1,2}:\d{2}|说话人\s*\d|Speaker\s*\d+"
    for page in pages:
        prepared = page["text"][:6000]
        if re.search(r"发言人\s*\d{1,2}:\d{2}|说话人\s*\d|Speaker\s*\d+", prepared, re.I) or re.search(r"(?m)^\s*问答整理\s*\n[\s\S]{0,200}(?:Q\d*\s*[:：]|答[:：]|电话会议|问答环节)", prepared):
            return PRIMARY[2], "后续页问答/转录记录", record_marker, "既有准备正文后续页含问答整理与问答/电话会或发言人结构；只确认记录形式，来源和转录事实仍待核"
        if re.search(record_marker, prepared, re.I) and len(re.findall(r"[？?]", prepared)) >= 2:
            return PRIMARY[2], "问答整理（含OCR标题形变）", record_marker, "既有正文有问答标题/编号和连续问答结构；只识别记录形式，保留来源和转写质量不确定性"
    if any(re.search(record_marker,p['text'][:6000],re.I) for p in pages) and sum(len(re.findall(r"[？?]",p['text'])) for p in pages)>=2:
        return PRIMARY[2], "跨页问答整理", record_marker, "正文问答标题与跨页连续问答结构共同支持记录形式，标题断页不再阻断"
    if re.search(r"(?m)^\s*[^\n]{0,50}调研总结\s*$|^\s*会议要点\s*$", short[:600]):
        return PRIMARY[2], "调研总结/会议要点", r"调研总结|会议要点", "正文标题明确调研总结/会议要点并有观点条目，来源及发言身份仍待核"
    if re.search(r"原视频",short[:800]) and re.search(r"演讲嘉宾",short[:1800]):
        return PRIMARY[2], "视频演讲整理", r"原视频|演讲嘉宾", "正文声明原视频和演讲嘉宾，为演讲整理材料；不验证视频链接/嘉宾身份或转写事实"
    if re.search(r"调研", short[:400]) and re.search(r"专家观点整理|以下内容来自资深行业专家|核心要点|主题概览|核心观点", short):
        return PRIMARY[2], "产业调研观点整理", r"调研|专家观点整理", "正文调研标题与专家观点/主题结构共同支持产业调研摘要形式；不认证发言人与原机构"
    fallback_news = r"股票市场复盘|股票巿场复盘|市场日志|市场⽇志|题材机会梳理|策略复盘|收市点评|TMT BREAKOUT|(?m:^\s*[一二三四五六七八九十]+、市场热点)"
    if re.search(fallback_news, short, re.I):
        return PRIMARY[3], "市场复盘/栏目解读", fallback_news, "正文栏目与市场评论结构支持资讯解读，非由文件名认定机构研究"
    return PRIMARY[6], "未知", None, "现有正文证据不足以确认材料性质；禁止由文件名补定类别"


def report_date_candidate(pages):
    unknown = {"value":None,"status":"UNKNOWN","evidence":None}
    if not pages:
        return unknown
    numeric = r"(20\d{2})[年./-]\s*(\d{1,2})[月./-]\s*(\d{1,2})日?"
    def valid(groups):
        try:return date(*map(int,groups)).isoformat()
        except ValueError:return None
    def result(items, status):
        values={v for v,ref in items if v}
        if len(values)!=1:return unknown
        value=next(iter(values))
        return {"value":value,"status":status,"evidence":next(ref for v,ref in items if v==value)}
    # Explicit publication semantics precede all standalone table/header dates.
    explicit=[]
    for match in re.finditer(r"(?:报告日期|发布日期|发布时间|發佈日期|Report date|Publication date)[^\n\d]{0,35}"+numeric,pages[0]["text"][:5000],re.I):
        explicit.append((valid(match.groups()),evidence(pages[:1],re.escape(match.group(0).strip()))))
    if explicit:return result(explicit,"EXPLICIT_REPORT_PUBLICATION_DATE_CANDIDATE")
    mastheads=[];standalone=[]
    for page in pages[:2]:
        text=page["text"][:5000]
        for match in re.finditer(r"(?m)^\s*"+numeric+r"\s*$",text):
            before=text[max(0,match.start()-180):match.start()]
            brand=any(re.search(r"(?m)^\s*"+institution_pattern(name)+r"\s*$",before,re.I) for name in INSTITUTIONS)
            bad_context=re.search(r"市场数据|基础数据|收盘价|数据来源|资料来源|截至|截止|as of|market data|相关研究|相關研究|相关报告|相關報告",before,re.I)
            ref=evidence([page],re.escape(match.group(0).strip()))
            value=valid(match.groups())
            # A new standalone brand/date masthead after a sidebar starts a fresh
            # publication context; market data earlier in OCR order cannot win.
            recent_brand=any(re.search(r"(?m)^\s*"+institution_pattern(name)+r"\s*$",before[-90:],re.I) for name in INSTITUTIONS)
            if brand and recent_brand:mastheads.append((value,ref))
            elif page["page_number"]==1 and match.start()<1000 and not bad_context:standalone.append((value,ref))
    if mastheads:return result(mastheads,"COVER_MASTHEAD_DATE_CANDIDATE")
    if standalone:return result(standalone,"BODY_HEADER_DATE_CANDIDATE")
    # English cover dates and Bloomberg's explicitly formatted news header.
    text=pages[0]["text"][:1000]
    month_names={name:i for i,name in enumerate(("January","February","March","April","May","June","July","August","September","October","November","December"),1)}
    english=[]
    for line in text.splitlines():
        value=None
        m=re.fullmatch(r"\s*(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})\s*",line)
        n=re.fullmatch(r"\s*([A-Za-z]+)\s+(\d{1,2}),?\s+(20\d{2})\s*",line)
        us=re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(20\d{2})\s*",line) if re.search(r"Bloomberg[\s\S]{0,60}News Story",text[:300],re.I) else None
        try:
            if m and m[2].title() in month_names:value=date(int(m[3]),month_names[m[2].title()],int(m[1]))
            elif n and n[1].title() in month_names:value=date(int(n[3]),month_names[n[1].title()],int(n[2]))
            elif us:value=date(int(us[3]),int(us[1]),int(us[2]))
        except ValueError:continue
        if value:english.append((value.isoformat(),evidence(pages[:1],re.escape(line.strip()))))
    return result(english,"BODY_HEADER_DATE_CANDIDATE") if english else unknown


def candidate_metadata(document, receipt, pages, taxonomy):
    text = page_slice(pages)
    primary, subtype, marker, reason = primary_candidate(pages)
    issuer, issuer_ref = publisher_candidate(pages, primary)
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
        "original_institution_candidate": issuer, "institution_status": "COVER_BRAND_PUBLISHER_CANDIDATE_NOT_AUTHENTICATED" if issuer else "UNKNOWN_OR_CONFLICTED",
        "institution_evidence": issuer_ref,
        "repost_channels_candidate": channels, "author": None, "author_status": "UNKNOWN_NOT_GUESSED",
        "report_date": ({"value": None, "status": "UNKNOWN_EXPORT_OR_TRANSCRIPT_TIMESTAMP_NOT_PUBLICATION", "evidence": None} if re.search(r"_导读|_原文|发言人\s*\d{1,2}:\d{2}", page_slice(pages, 1, 1200)) else report_date_candidate(pages)), "collection_dates": sorted(set(collection_dates)), "collection_date_basis": "COLLECTION_DIRECTORY_ONLY_NOT_PUBLICATION_DATE",
        "industry_theme_candidates": label_hits, "industry_evidence": industry_evidence, "industry_dictionary_version": taxonomy["version"],
        "markets_mentioned_candidate": markets, "market_semantics": "Text mention only, not issuer domicile, exchange eligibility or A/HK mapping",
        "main_research_companies": [], "mentioned_companies": [], "company_status": "UNKNOWN_PENDING_ENTITY_REVIEW", "verified_stock_codes": [], "stock_code_status": "UNKNOWN_NO_GUESSED_MAPPING",
        "exact_body_sha256": body_sha(pages) if any(p["text"].strip() for p in pages) else None,
        "exact_body_scope": "NFC_WHITESPACE_COLLAPSE_PAGE_SEQUENCE" if pages else None,
        "text_quality": "PREPARED_READY_OCR_SEMANTICS_UNREVIEWED" if ready else selected_status,
        "existing_analysis_status": "PRIOR_REPORT_REFERENCE_PRESENT_NOT_REVIEWED" if receipt and (receipt.get("revision") or {}).get("supersedes") else "UNKNOWN_NOT_READ",
        "route_candidate": route, "route_reason": route_reason, "deep_research_scope": "NO_EXPLICIT_RESEARCH_QUESTION_NO_HIGH_VALUE_ASSIGNMENT",
        "duplicate_group": None, "version_group": None, "relation_candidates": [], "relation_status": "UNASSESSED_NOT_NO_RELATION",
    }


def load_frozen_inputs(manifest_path, progress_path, snapshot_receipt_path, prepared_root, taxonomy, cache_root=None, cache_metrics=None):
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
        metadata = cached_metadata(document, receipt, pages, taxonomy, refs, cache_root, cache_metrics)
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
    body_denominator = stats["dedup"].get("available_text_identity_denominator", stats["dedup"]["ready_body_identity_denominator"])
    body_denominator_label = "可用准备正文（含隔离，质量状态单列）" if "available_text_identity_denominator" in stats["dedup"] else "READY正文"
    sample_distribution = "".join(f'<tr><td>{e(k)}</td><td>{v["sample_count"]}</td><td>{v["source_or_content_uncertain"]}</td></tr>' for k,v in stats["sample_unknown_by_class"].items() if v["sample_count"])
    multi_stats = e(json.dumps(stats["multilabel_counts_nonexclusive"],ensure_ascii=False))
    company_stats = e(json.dumps(stats["sample_main_company_counts_nonexclusive"],ensure_ascii=False))
    source_stats = e(json.dumps({"来源机构候选":stats["source_institution_candidate_counts"],"日期证据状态":stats["report_date_status_counts"],"语言候选":stats["language_candidate_counts"]},ensure_ascii=False))
    ocr_options = "".join(f"<option>{e(k)}</option>" for k in sorted({row["ocr_status_asof"] for row in sample}))
    options = "".join(f'<option>{e(k)}</option>' for k in PRIMARY)
    doc = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PDF 分类与去重看板 · 2026-10-20</title><style>body{{font:16px/1.65 system-ui,sans-serif;background:#f5f7fa;color:#172b40;max-width:1150px;margin:0 auto;padding:28px}}h1{{font-size:28px}}h2{{margin-top:36px}}.banner,details,table{{background:white;border:1px solid #d8e0e8;border-radius:9px;padding:16px;margin:12px 0}}summary{{cursor:pointer}}summary span{{float:right;font-size:12px;color:#47657e}}small{{display:block;overflow-wrap:anywhere;color:#526677}}blockquote{{border-left:3px solid #698ea8;padding-left:12px;margin:15px 0;background:#f7fafc}}input,select{{padding:10px;margin:6px 8px 6px 0;max-width:90%}}table{{border-collapse:collapse;min-width:380px}}td,th{{padding:7px 18px;text-align:left;border-bottom:1px solid #e4e9ee}}a{{color:#16638e}}.warn{{color:#8b4a12}}[hidden]{{display:none!important}}</style><body><h1>PDF 分类与去重看板</h1><div class="banner"><b>2209 个原始身份全部对账；本页展示60份样例、10对真实材料关系。</b><p>固定快照 {e(stats["asof_utc"])}（UTC）：{status}。只反映该时点，不追随仍在运行的OCR。</p><p class="warn">全量标签为规则候选；样例 Writer 核验等待独立 Reviewer。无模型分析、无OCR重跑、无删除合并、无买入信号；未设研究问题，不自动判高价值。行业/公司/主题为多标签，统计不相加为2209。</p><p><b>身份2209</b> · <b>快照READY {stats["ocr_status_counts"].get("READY",0)}</b> · <b>快照待完成 {stats["ocr_status_counts"].get("PENDING",0)}</b> · <b>样例60 / 关系10对</b></p><a href="ledger.csv">完整台账 CSV</a> · <a href="ledger.json">完整台账 JSON</a> · <a href="statistics.json">统计 JSON</a> · <a href="sample60.csv">60份样例 CSV</a> · <a href="relations10.json">10对证据 JSON</a></div><h2>全量规则候选主类（互斥，含待分类）</h2><table><tr><th>类型</th><th>文件数 / 2209</th></tr>{distribution}</table><p>确证相同分页正文组：{stats["dedup"]["same_normalized_page_sequence_groups"]} / {body_denominator} 份{body_denominator_label}；相同文件SHA组为0（manifest内2209唯一PDF身份）。没有真实正例时不会补造重复。</p><h2>样例主类与待核率</h2><table><tr><th>Writer标签</th><th>样本数/60</th><th>来源或内容仍待核</th></tr>{sample_distribution}</table><p>独立分类准确率：尚未评分。样例为覆盖/边界抽样，不代表总体频率或全量准确率。主类和署名识别不等于报告事实已验收；来源或OCR质量待核单列。公司披露、咨询仅各1份，按当前检出事实保留，不补造5份。</p><details><summary>多标签覆盖与公司对象（非互斥计数）</summary><p>{multi_stats}</p><p>样例主研究公司：{company_stats}。主对象与提及对象分开；全量实体尚未核验，证券代码仍为未知。</p></details><details><summary>来源、报告日期与语言覆盖</summary><p>{source_stats}</p><p>机构与语言为规则候选；机构名称是正文归属声明，不等于官方来源真实性已认证。转载渠道单列。下载目录/转录生成时间不充当报告发布日期。</p></details><h2>60份可筛选样例</h2><input id="q" placeholder="搜索标题、公司、主题、证据"><select id="kind"><option value="">全部主类</option>{options}</select><select id="route"><option value="">全部分流</option>{"".join(f"<option>{x}</option>" for x in ROUTES)}</select><select id="ocr"><option value="">全部OCR状态</option>{ocr_options}</select><p id="visible"></p>{"".join(cards)}<h2>10对重复/转载/版本或同主题材料证据</h2><p>相似分数仅用于候选召回；数字、正负号、日期、单位保留。不同观点或数字不会自动合并。</p>{"".join(pair_cards)}<script>function filter(){{let q=document.getElementById('q').value.toLowerCase(),k=document.getElementById('kind').value,r=document.getElementById('route').value,o=document.getElementById('ocr').value,n=0;document.querySelectorAll('.sample').forEach(x=>{{let ok=(!q||x.textContent.toLowerCase().includes(q))&&(!k||x.dataset.type===k)&&(!r||x.dataset.route===r)&&(!o||x.dataset.status===o);x.hidden=!ok;if(ok)n++}});document.getElementById('visible').textContent='显示 '+n+' / 60'}}['q','kind','route','ocr'].forEach(id=>document.getElementById(id).addEventListener('input',filter));filter();</script></body></html>'''
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

def verify_terminal_manifest(value, expected_ids):
    rows = value.get('documents', [])
    ids = [r.get('document_id') for r in rows]
    counts = Counter(r.get('status') for r in rows)
    if (value.get('status') != 'FROZEN_COMPLETE' or value.get('parent_manifest_sha256') != MANIFEST_SHA
            or value.get('full_cohort') is not True or value.get('parent_document_count') != 2209
            or len(ids) != 2209 or len(set(ids)) != 2209 or set(ids) != set(expected_ids)
            or not set(counts) <= {'READY', 'QUARANTINED', 'FAILED'}
            or value.get('counts') != {'total':2209,'ready':counts['READY'],'quarantined':counts['QUARANTINED'],'failed':counts['FAILED'],'pending':0}):
        raise ValueError('FULL_OCR_TERMINAL_MANIFEST_REQUIRED')
    return rows


def freeze_full_snapshot(root, prepared, require_final=False, refresh=False):
    manifest, _ = read_json(root/'input/batch-manifest.json', MANIFEST_SHA)
    final_ref = None
    if require_final:
        final_path = prepared/'prepared-text-manifest.json'
        if not final_path.exists():
            raise ValueError('WAITING_OCR_FINAL_MANIFEST_ABSENT_NO_EXTRACTION_ATTEMPTED')
        final, raw = read_json(final_path)
        verify_terminal_manifest(final, [d['document_id'] for d in manifest['documents']])
        final_ref = {'path':str(final_path),'sha256':sha(raw),'counts':final['counts']}
    elif refresh:
        _progress, raw = read_json(prepared/'progress.json')  # single atomic producer file read
    else:
        receipt, _ = read_json(root/'input/snapshot-receipt.json')
        _progress, raw = read_json(root/'input/ocr-progress-snapshot.json', receipt['progress_sha256'])
        return root/'input', None
    frozen = root/'snapshots'/sha(raw)
    if not frozen.exists():
        frozen.mkdir(parents=True)
        (frozen/'ocr-progress-snapshot.json').write_bytes(raw)
        (frozen/'batch-manifest.json').write_bytes((root/'input/batch-manifest.json').read_bytes())
        (frozen/'industry-taxonomy.json').write_bytes((root/'input/industry-taxonomy.json').read_bytes())
        write_json(frozen/'snapshot-receipt.json', {'asof_utc':datetime.now(timezone.utc).isoformat(),'progress_sha256':sha(raw),'source':str(prepared/('prepared-text-manifest.json' if require_final else 'progress.json')),'method':'ONE_READ_IMMUTABLE_SNAPSHOT','final_manifest':final_ref})
    return frozen, final_ref


def full_relations(rows, texts):
    """All exact groups; bounded title retrieval for differing-text candidates."""
    exact, titles = defaultdict(list), defaultdict(list)
    for row in rows:
        if row['exact_body_sha256']:
            exact[row['exact_body_sha256']].append(row['document_id'])
            title = re.sub(r'\d{6,8}|20\d{2}年\d+月\d+日', '', row['filename_candidate_title'])
            # Retrieval identity only. Text symbols/numbers never removed for proof.
            titles[normalize_exact(title).casefold()].append(row['document_id'])
    byid = {r['document_id']:r for r in rows}
    groups = []
    for digest, ids in sorted(exact.items()):
        if len(ids) > 1:
            group = {'group_id':'normalized-body:'+digest,'document_ids':sorted(ids),'relation':'SAME_NORMALIZED_PAGE_SEQUENCE','normalization':'NFC_WHITESPACE_ONLY_PRESERVE_PAGE_SEQUENCE_DIGITS_SIGNS_UNITS_WORD_BOUNDARIES','quality_statuses':dict(Counter(byid[k]['ocr_status_asof'] for k in ids)),'action':'PRESERVE_ALL_NO_MERGE'}
            groups.append(group)
            for k in ids:
                byid[k]['duplicate_group'] = group['group_id']
                byid[k]['relation_status'] = 'EXACT_NORMALIZED_BODY_MATCH_SOURCE_QUALITY_SEPARATE'
                ready_ids=sorted(v for v in ids if byid[v]['ocr_status_asof']=='READY')
                if byid[k]['ocr_status_asof']=='READY' and ready_ids and k!=ready_ids[0]:
                    byid[k]['route_candidate']='REUSE_CANDIDATE'
                    byid[k]['route_reason']='严格相同分页正文已确证；仅作为复用候选，来源与既有研究匹配仍须核验；保留所有原件'
    candidates = []
    for title, ids in sorted(titles.items()):
        if not title or len(ids) < 2:
            continue
        for i,left in enumerate(sorted(ids)):
            for right in sorted(ids)[i+1:i+26]:
                if byid[left]['exact_body_sha256'] == byid[right]['exact_body_sha256']:
                    continue
                candidate = {'relation_id':sha((left+right).encode()),'left_document_id':left,'right_document_id':right,'relation':'REPOST_OR_VERSION_CANDIDATE_DIFFERENT_TEXT','retrieval_reason':'date-stripped filename title equal; filename is retrieval hint only, not duplicate proof','left_evidence':evidence(texts[left]),'right_evidence':evidence(texts[right]),'left_page_input':byid[left]['source_references']['page_input'],'right_page_input':byid[right]['source_references']['page_input'],'left_only_numeric_tokens':sorted(set(NUMBER.findall(page_slice(texts[left])))-set(NUMBER.findall(page_slice(texts[right]))))[:15],'right_only_numeric_tokens':sorted(set(NUMBER.findall(page_slice(texts[right])))-set(NUMBER.findall(page_slice(texts[left]))))[:15],'numeric_scope':'first3pages/14000chars, candidate only; not complete numeric audit','action':'PRESERVE_BOTH_NO_MERGE'}
                candidates.append(candidate)
                for k,other in ((left,right),(right,left)):
                    byid[k]['relation_candidates'].append({'other_document_id':other,'relation_id':candidate['relation_id'],'relation':candidate['relation'],'action':candidate['action']})
    return {'same_file_groups':[],'exact_normalized_text_groups':groups,'repost_or_version_candidates':candidates,'retrieval_boundary':'all same-title groups, max25 later neighbors per item; no claim of exhaustive fuzzy duplicate recall; same-topic relations remain separate examples','same_pdf_identity_denominator':len(rows),'available_text_denominator':sum(bool(r['exact_body_sha256']) for r in rows),'deleted':0,'merged':0}


def coverage_stats(rows):
    n=len(rows)
    predicates={'material_type':lambda r:r['primary_type_candidate']!=PRIMARY[6], 'institution':lambda r:r['original_institution_candidate'] is not None,'report_date':lambda r:r['report_date']['value'] is not None,'language':lambda r:r['language_candidate']!='UNKNOWN','main_company_literal':lambda r:bool(r['main_research_companies']),'mentioned_company_literal':lambda r:bool(r['mentioned_companies']),'verified_stock_code':lambda r:bool(r['verified_stock_codes']),'theme':lambda r:bool(r['industry_theme_candidates']),'market_mention':lambda r:bool(r['markets_mentioned_candidate']),'source_page_index':lambda r:bool(r['source_references']['pages'])}
    return {k:{'candidate_present':sum(bool(fn(r)) for r in rows),'unknown_or_not_extracted':sum(not fn(r) for r in rows),'denominator':n,'semantic_acceptance':'NOT_FULL_COHORT_VERIFIED'} for k,fn in predicates.items()}


def apply_full_form_reviews(rows, texts, review_path):
    if review_path is None:
        return None
    review, raw = read_json(review_path)
    byid = {r['document_id']:r for r in rows}
    items = review.get('documents', [])
    if review.get('manifest_sha256') != MANIFEST_SHA or len({r['document_id'] for r in items}) != len(items):
        raise ValueError('FULL_FORM_REVIEW_IDENTITY_INVALID')
    for item in items:
        row = byid.get(item['document_id'])
        if (row is None or item.get('pdf_sha256') != row['pdf_sha256']
                or item.get('page_input_sha256') != row['frozen_page_input_sha256']
                or item.get('exact_body_sha256') != row['exact_body_sha256']
                or row['ocr_status_asof'] not in {'READY','QUARANTINED'}
                or item.get('primary_type') not in PRIMARY or not item.get('evidence') or not item.get('reason')):
            raise ValueError('FULL_FORM_REVIEW_SOURCE_BINDING_MISMATCH')
        for ref in item['evidence']:
            number = ref['page_number']
            pages = texts[row['document_id']]
            if not 1 <= number <= len(pages):
                raise ValueError('FULL_FORM_REVIEW_PAGE_INVALID')
            text = pages[number-1]['text']
            if sha(text.encode()) != ref['page_text_sha256'] or ref['excerpt'] not in re.sub(r'\s+',' ',text).strip():
                raise ValueError('FULL_FORM_REVIEW_EVIDENCE_MISMATCH')
        row.update({'primary_type_candidate':item['primary_type'],'subtype_candidate':item.get('subtype','正文人工核定候选'),
                    'classification_reason':item['reason'],'classification_evidence':item['evidence'][0],
                    'classification_status':'WRITER_SOURCE_BOUND_FORM_LABEL_PENDING_INDEPENDENT_REVIEW',
                    'manual_form_review':{'file_sha256':sha(raw),'page_input_sha256':item['page_input_sha256'],'exact_body_sha256':item['exact_body_sha256']},
                    'quality_flags':item.get('quality_flags',[]),'route_candidate':'REVIEW',
                    'route_reason':'材料形式为绑定正文的人工候选；独立语义或质量/来源仍待核，不触发模型'})
    return {'path':str(review_path),'sha256':sha(raw),'document_count':len(items),'scope':'material form/quality proposal only; no issuer/date/code override'}


def render_full_report(path, stats, rows, sample, pairs, validation):
    # Preserve reviewed60 and10-pair content in the same single static artifact.
    display_stats={**stats,"primary_type_candidate_counts":stats.get("material_disposition_counts",stats["primary_type_candidate_counts"])}
    render_report(path, display_stats, sample, pairs)
    old=path.read_text()
    old=old.replace("全量规则候选主类（互斥，含待分类）","材料形式与处理去向（互斥；待OCR/提取失败单列）")
    old=old.replace('本页展示60份样例、10对真实材料关系。','本页提供全部2209份分页索引、保留60份历史样例及10对关系证据。')
    old=old.replace('样例 Writer 核验等待独立 Reviewer。','历史60份材料形式及10关系已独立PASS；全量新候选及F1-F4返修待独立增量验收。')
    old=old.replace('独立分类准确率：尚未评分。','历史样例主类形式独立60/60；这是开发回归集，不能估计全量准确率。该60份原独立56/60（93.33%）FAIL保留；返修后仅作回归，不能再声称未见泛化准确率。')
    old=old.replace('WRITER_REVIEWED_PENDING_INDEPENDENT_REVIEW','HISTORICAL_SAMPLE_FORM_INDEPENDENT_PASS_SOURCE_AUTHENTICITY_SEPARATE')
    compact=[]
    for row in rows:
        compact.append({k:row.get(k) for k in ('document_id','pdf_sha256','original_pdf_path','filename_candidate_title','body_header_candidate_title','primary_type_candidate','display_material_type','classification_state','disposition_reason','quality_flags','ocr_status_asof','route_candidate','route_reason','classification_reason','classification_evidence','original_institution_candidate','institution_status','institution_evidence','report_date','collection_dates','language_candidate','main_research_companies','mentioned_companies','industry_theme_candidates','markets_mentioned_candidate','text_quality','text_characters','page_count','source_references','duplicate_group','relation_candidates','classification_binding','manual_form_review','company_status','main_company_status','mentioned_company_status','body_quality_metrics')})
    payload=json.dumps(compact,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    opts=lambda vals:''.join('<option>'+html.escape(str(x))+'</option>' for x in sorted(set(vals)) if x)
    panel='''<h2>全部2209份 · 分页检索</h2><p>每条为正文规则候选；历史样例另列。READY仅表示正文准备完成，来源真实性、数字与投资结论未获验证。非READY保留且进入REVIEW。公司为字面对象候选；代码不猜配。<br>严格相同分页正文仅折叠显示，不删除、不合并；质量状态独立保留。</p><div class="banner"><input id="full-q" aria-label="搜索完整台账" placeholder="搜索标题、公司、机构、主题或ID"><select id="full-type"><option value="">全部主类</option>'''+opts(r.get('display_material_type') or r['primary_type_candidate'] for r in rows)+'''</select><select id="full-route"><option value="">全部分流</option>'''+opts(ROUTES)+'''</select><select id="full-status"><option value="">全部OCR状态</option>'''+opts(r['ocr_status_asof'] for r in rows)+'''</select><select id="full-language"><option value="">全部语言</option>'''+opts(r['language_candidate'] for r in rows)+'''</select><label><input type="checkbox" id="full-fold">折叠严格相同正文组</label><p id="full-count" aria-live="polite"></p><button id="full-prev">上一页</button> <span id="full-page"></span> <button id="full-next">下一页</button></div><div id="full-list"></div><details><summary>全量字段覆盖与未知（分母各2209）</summary><pre style="white-space:pre-wrap">'''+html.escape(json.dumps(stats['field_coverage'],ensure_ascii=False,indent=2))+'''</pre></details><p>验证集60份曾在初次调优前冻结；原独立56/60（93.33%）未达95%目标，现已揭示用于返修，仅作回归。排除原60样例及关系开发资料；不是总体准确率估计。<a href="validation60.json">新60份原页证据与候选字段</a> · <a href="all-relations.json">全部关系索引</a> · <a href="regression12.json">12项已知差异逐项归因</a></p>'''
    script=r'''<script id="full-data" type="application/json">PAYLOAD</script><script>
const fullRows=JSON.parse(document.getElementById('full-data').textContent);const fullPageSize=25;let fullPage=0,fullFiltered=[];
function fullSelect(data,q,k,r,o,l,fold){const seen=new Set();return data.filter(x=>{if(k&&(x.display_material_type||x.primary_type_candidate)!==k||r&&x.route_candidate!==r||o&&x.ocr_status_asof!==o||l&&x.language_candidate!==l)return false;if(q&&!JSON.stringify(x).toLowerCase().includes(q.toLowerCase()))return false;if(fold&&x.duplicate_group){if(seen.has(x.duplicate_group))return false;seen.add(x.duplicate_group)}return true})}
function fullEl(tag,text,parent){const n=document.createElement(tag);n.textContent=text;if(parent)parent.appendChild(n);return n}
function fullCite(row,ref,parent){if(!ref)return;fullEl('blockquote',ref.excerpt,parent);const a=fullEl('a','原PDF 第'+ref.page_number+'页',parent);a.href=encodeURI(row.original_pdf_path).replace(/#/g,'%23').replace(/\?/g,'%3F')+'#page='+ref.page_number;fullEl('small','页正文SHA '+ref.page_text_sha256,parent)}
function fullRender(){const list=document.getElementById('full-list');list.replaceChildren();const total=Math.max(1,Math.ceil(fullFiltered.length/fullPageSize));fullPage=Math.max(0,Math.min(fullPage,total-1));for(const x of fullFiltered.slice(fullPage*fullPageSize,(fullPage+1)*fullPageSize)){const d=fullEl('details','',list);fullEl('summary',(x.display_material_type||x.primary_type_candidate)+' · '+x.filename_candidate_title+' · '+x.ocr_status_asof,d);fullEl('p','规则候选待独立语义验收 · '+x.route_candidate+'：'+x.route_reason,d);fullEl('p',x.classification_reason,d);fullEl('p','分类去向 '+x.classification_state+'：'+x.disposition_reason+'；质量标记 '+JSON.stringify(x.quality_flags),d);fullEl('p','机构候选：'+(x.original_institution_candidate||'未知')+'（'+x.institution_status+'）；报告日期：'+JSON.stringify(x.report_date)+'；采集日期仅作采集：'+x.collection_dates.join(', '),d);fullEl('p','语言候选 '+x.language_candidate+'；正文质量 '+x.text_quality+'；'+x.page_count+'页 / '+x.text_characters+'字符；机械质量指标 '+JSON.stringify(x.body_quality_metrics),d);fullEl('p','主对象候选 '+(x.main_research_companies.length?JSON.stringify(x.main_research_companies):'未知/未抽取')+'；提及对象 '+(x.mentioned_companies.length?JSON.stringify(x.mentioned_companies):'未知/未抽取')+'；代码未知；主题 '+x.industry_theme_candidates.join(', ')+'；市场仅文字提及 '+x.markets_mentioned_candidate.join(', '),d);fullCite(x,x.classification_evidence,d);fullCite(x,x.institution_evidence,d);const p=fullEl('details','',d);fullEl('summary','原页索引及SHA（'+x.source_references.pages.length+'页）',p);for(const ref of x.source_references.pages){const a=fullEl('a','p.'+ref.page_number+' ',p);a.href=encodeURI(x.original_pdf_path).replace(/#/g,'%23').replace(/\?/g,'%3F')+'#page='+ref.page_number;fullEl('small',ref.text_sha256,p)}fullEl('small','PDF SHA '+x.pdf_sha256+'；文本输入 '+JSON.stringify(x.source_references.page_input)+'；严格重复组 '+(x.duplicate_group||'无已确证组（不等于不存在相似）')+'；关系候选 '+JSON.stringify(x.relation_candidates)+'；分类绑定 '+JSON.stringify(x.classification_binding),d)}document.getElementById('full-count').textContent='筛选/折叠后 '+fullFiltered.length+' / 原始身份2209；每页25份';document.getElementById('full-page').textContent=(fullPage+1)+' / '+total;document.getElementById('full-prev').disabled=fullPage===0;document.getElementById('full-next').disabled=fullPage===total-1}
function fullFilter(){fullPage=0;fullFiltered=fullSelect(fullRows,...['full-q','full-type','full-route','full-status','full-language'].map(k=>document.getElementById(k).value),document.getElementById('full-fold').checked);fullRender()}['full-q','full-type','full-route','full-status','full-language','full-fold'].forEach(k=>document.getElementById(k).addEventListener('input',fullFilter));document.getElementById('full-prev').addEventListener('click',()=>{fullPage--;fullRender()});document.getElementById('full-next').addEventListener('click',()=>{fullPage++;fullRender()});fullFilter();</script>'''.replace('PAYLOAD',payload)
    old=old.replace('<h2>60份可筛选样例</h2>',panel+'<h2>历史60份可筛选样例 · 固定于原样例快照</h2><p>历史样例 asof UTC：'+html.escape(sample[0]['asof_utc'])+'；原独立验收仅材料形式/关系范围，不代表官方来源或事实认证。</p>')
    old=old.replace('</body>',script+'</body>')
    path.write_text(old,encoding='utf-8')


def full_main(argv):
    parser=argparse.ArgumentParser(description='Incremental offline classification over existing prepared text; no OCR/model')
    parser.add_argument('--full',action='store_true');parser.add_argument('--evidence-root',type=Path,required=True);parser.add_argument('--prepared-root',type=Path,required=True);parser.add_argument('--sample-root',type=Path,required=True);parser.add_argument('--refresh-snapshot',action='store_true');parser.add_argument('--require-final',action='store_true')
    parser.add_argument('--snapshot-root',type=Path)
    parser.add_argument('--classification-review',type=Path)
    args=parser.parse_args(argv);root=args.evidence_root.resolve();prepared=args.prepared_root.resolve()
    if root.name!='V4_PDF_CLASSIFICATION_FULL_20261020_R1' or root.is_relative_to(prepared) or root==args.sample_root.resolve():raise ValueError('FULL_OUTPUT_ROOT_SCOPE_INVALID')
    started=time.monotonic()
    if args.snapshot_root:
        if args.require_final or args.refresh_snapshot or not args.snapshot_root.resolve().is_relative_to(root):
            raise ValueError('EXPLICIT_SNAPSHOT_SCOPE_OR_FLAGS_INVALID')
        inp,final_ref=args.snapshot_root.resolve(),None
    else:
        inp,final_ref=freeze_full_snapshot(root,prepared,args.require_final,args.refresh_snapshot)
    taxonomy,_=read_json(inp/'industry-taxonomy.json');metrics={}
    rows,texts,snapshot,index=load_frozen_inputs(inp/'batch-manifest.json',inp/'ocr-progress-snapshot.json',inp/'snapshot-receipt.json',prepared,taxonomy,root/'classification-cache',metrics)
    form_review_ref=apply_full_form_reviews(rows,texts,args.classification_review)
    for row in rows:
        state,label,reason=disposition(row)
        row.update({'classification_state':state,'display_material_type':label,'disposition_reason':reason})
        if state in {'WAITING_OCR','EXTRACTION_FAILED','READY_QUALITY_REVIEW','READY_FORM_REVIEW','QUARANTINED_FORM_REVIEW'}:
            row['route_candidate']='REVIEW';row['route_reason']=reason
        if state in {'WAITING_OCR','EXTRACTION_FAILED'}:
            row['classification_reason']=reason
    validation,validation_raw=read_json(root/'input/validation60-frozen-before-tuning.json')
    if validation['manifest_sha256']!=MANIFEST_SHA or set(validation['sample_document_ids'])&set(validation['exclusion_document_ids']):raise ValueError('VALIDATION_HOLDOUT_BINDING_INVALID')
    sample_data,_=read_json(args.sample_root/'delivery/sample60.json');sample=sample_data['documents'];sample_ids=[r['document_id'] for r in sample]
    old_pairs,_=read_json(args.sample_root/'delivery/relations10.json');pairs=old_pairs['pairs']
    relations=full_relations(rows,texts);byid={r['document_id']:r for r in rows}
    pair_summary={'same_normalized_page_sequence_groups':len(relations['exact_normalized_text_groups']),'ready_body_identity_denominator':sum(r['ocr_status_asof']=='READY' and bool(r['exact_body_sha256']) for r in rows),'available_text_identity_denominator':relations['available_text_denominator'],'writer_review_ref':old_pairs['summary'].get('writer_review_ref'),'all_text_scope':'all available text including quarantined; quality separately shown','merged_or_deleted':0}
    stats=build_stats(rows,sample_ids,pair_summary,snapshot,taxonomy)
    stats['material_disposition_counts']=dict(Counter(r['display_material_type'] for r in rows))
    stats['classification_state_counts']=dict(Counter(r['classification_state'] for r in rows))
    stats['full_form_review']=form_review_ref
    stats.update({'field_coverage':coverage_stats(rows),'sample_unknown_by_class':{label:{'sample_count':sum(r['sample_primary_type']==label for r in sample),'source_or_content_uncertain':sum(r['sample_primary_type']==label and (r['sample_certainty']!='TYPE_AND_SOURCE_IDENTIFIED' or r['ocr_status_asof']!='READY') for r in sample)} for label in PRIMARY},'sample_main_company_counts_nonexclusive':dict(Counter(n for r in sample for n in r.get('sample_main_research_companies',[]))),'classification_rules_version':RULES_VERSION,'incremental':metrics,'final_prepared_manifest':final_ref,'full_delivery_status':'OCR_TERMINAL_CLASSIFICATION_CANDIDATE_PENDING_INDEPENDENT_REVIEW' if final_ref else 'IMPLEMENTATION_HANDOFF_WAITING_OCR','validation60_selection_sha256':sha(validation_raw),'semantic_accuracy':'PRIOR_INDEPENDENT56_OF60_FAIL_RETAINED_NOW_REPAIR_REGRESSION_ONLY','validation60_role':'Revealed by independent review; no longer held-out after F1-F4 repair; cannot claim unseen generalization or population accuracy','historical60_scope':'Development regression only; prior independent form PASS preserved; no population estimate','repost_or_version_candidate_pairs':len(relations['repost_or_version_candidates'])})
    initial,_=read_json(root/'input/pre-tuning-old60-disagreements.json');regression=[]
    for item in initial:
        row=byid[item['document_id']];regression.append({**item,'new_candidate':row['primary_type_candidate'],'matches_reviewed_form':row['primary_type_candidate']==item['reviewed'],'new_reason':row['classification_reason'],'evidence':row['classification_evidence'],'root_cause':'导出摘要模板非原机构材料' if item['reviewed']==PRIMARY[5] else '原字典缺机构别名/封面研究结构' if item['reviewed']==PRIMARY[0] else '新闻栏目或问答结构缺识别'})
    if not all(r['matches_reviewed_form'] for r in regression):raise ValueError('KNOWN12_FORM_REGRESSION_UNRESOLVED:'+','.join(r['document_id'] for r in regression if not r['matches_reviewed_form']))
    build_key=sha(json_raw({'progress':snapshot['progress_sha256'],'source':sha(Path(__file__).read_bytes()),'validation':sha(validation_raw),'sample60':sha(json_raw(sample_data)),'form_review':form_review_ref}))[:20]
    out=root/'builds'/build_key
    if out.exists():
        existing,_=read_json(out/'BUILD.json')
        for name,ref in existing['artifacts'].items():
            artifact=bound_path(out,name)
            if not artifact.is_file() or artifact.is_symlink() or sha(artifact.read_bytes())!=ref['sha256']:
                raise ValueError('EXISTING_BUILD_SHA_MISMATCH')
        write_json(root/'LAST_INVOCATION.json',{'existing_immutable_build_reused':True,'build':str(out),'incremental':metrics,'source_sha256':sha(Path(__file__).read_bytes())})
        print(json.dumps({'status':stats['full_delivery_status'],'existing_build_reused':str(out),'incremental':{k:v for k,v in metrics.items() if not k.endswith('_document_ids')}},ensure_ascii=False));return
    out.mkdir(parents=True)
    write_json(out/'ledger.json',{'schema':'v4.pdf_full_classification.v1','snapshot':snapshot,'final_prepared_manifest':final_ref,'documents':rows});write_json(out/'frozen-text-index.json',{'snapshot':snapshot,'documents':index});write_json(out/'statistics.json',stats);write_json(out/'all-relations.json',relations);write_json(out/'regression12.json',regression)
    write_json(out/'sample60.json',sample_data);write_json(out/'relations10.json',old_pairs)
    validation_rows=[byid[k] for k in validation['sample_document_ids']]
    write_json(out/'validation60.json',{'selection':validation,'selection_sha256':sha(validation_raw),'boundary':'Originally frozen before tuning; independent56/60 FAIL retained. Revealed F1-F4 now used for bounded repair regression; not unseen validation or population accuracy. Unknown separate.','documents':validation_rows})
    write_csv(out/'ledger.csv',rows,list(rows[0]));write_csv(out/'sample60.csv',sample,list(sample[0]))
    render_full_report(out/'report.html',stats,rows,sample,pairs,validation_rows)
    (out/'statistics.md').write_text('# 全量分类索引\n\n'+stats['full_delivery_status']+'\n\n固定UTC '+snapshot['asof_utc']+'；原身份分母2209。\n\nOCR '+json.dumps(stats['ocr_status_counts'],ensure_ascii=False)+'\n\n主类候选 '+json.dumps(stats['primary_type_candidate_counts'],ensure_ascii=False)+'\n\n[完整分页看板](report.html) · [字段覆盖](statistics.json) · [新冻结60证据](validation60.json)\n\n全量规则候选不等于全量语义验收。非READY隔离保留，零OCR/模型/合并/删除。\n',encoding='utf-8')
    artifacts={p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(out.iterdir()) if p.is_file()}
    build={'schema':'v4.pdf_full_classification.build.v1','status':stats['full_delivery_status'],'source_sha256':sha(Path(__file__).read_bytes()),'manifest_sha256':MANIFEST_SHA,'snapshot':snapshot,'final_prepared_manifest':final_ref,'rules_version':RULES_VERSION,'incremental':metrics,'runtime_seconds':round(time.monotonic()-started,3),'artifacts':artifacts,'ocr_calls':0,'model_requests':0,'downloads':0,'merges':0,'deletions':0}
    write_json(out/'BUILD.json',build);write_json(root/'LATEST_BUILD.json',{'build':str(out),'build_sha256':sha((out/'BUILD.json').read_bytes()),'status':build['status']})
    print(json.dumps({'status':build['status'],'output':str(out),'ocr':stats['ocr_status_counts'],'primary':stats['primary_type_candidate_counts'],'incremental':{k:v for k,v in metrics.items() if not k.endswith('_document_ids')},'runtime_seconds':build['runtime_seconds']},ensure_ascii=False))


if __name__ == "__main__":
    full_main(sys.argv[1:]) if '--full' in sys.argv[1:] else main()
