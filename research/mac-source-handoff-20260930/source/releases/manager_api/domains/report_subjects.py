"""Classify report title roles without replacing source entities or issuer masters.

An explicit title code is textual evidence, not Stock Connect eligibility or a
security-master attestation. No lookup, I/O, network, price or score mutation.
"""
from __future__ import annotations
from copy import deepcopy
import re
from typing import Any, Mapping

_BROKER_LABELS = frozenset({"申万宏源", "国泰海通", "国联民生", "中金公司", "国盛海外", "高盛", "摩根士丹利", "汇丰", "野村", "瑞银"})
_NAMED_CODE = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z·&]{2,24}(?:-(?:SW|W|B|P|S))?)\s*[（(]\s*"
    r"(?P<code>(?:HK\.\d{1,5}|\d{1,5}\.HK|(?:SH|SZ|BJ|A)\.\d{6}|\d{6}(?:\.(?:SH|SZ|BJ))?))\s*[）)]", re.I)

_NAMED_DASH_CODE = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z·&]{2,24})[-—–](?P<code>\d{6})[-—–：:]", re.I)


def canonical_title_code(value: Any) -> str | None:
    raw = str(value or "").strip().upper()
    hk = re.fullmatch(r"(?:HK\.(\d{1,5})|(\d{1,5})\.HK)", raw)
    if hk:
        return "HK." + (hk.group(1) or hk.group(2)).zfill(5)
    a = re.fullmatch(r"(?:(?:A|SH|SZ|BJ)\.)?(\d{6})(?:\.(?:SH|SZ|BJ))?", raw)
    return "A." + a.group(1) if a else None


def report_title_evidence(title: str, source_type: str = "") -> dict[str, Any]:
    text = str(title or "").splitlines()[0] if str(title or "").splitlines() else ""
    # Remove only leading channel hashtags/separators for publisher matching;
    # the original title and evidence spans remain unchanged.
    publisher_title = re.sub(r"^(?:\s*#[^#\n]{1,30}#\s*[｜|：:]?\s*)+", "", text)
    publisher_title_offset = len(text) - len(publisher_title)
    prefix = re.match(
        r"^\s*(?P<label>[^\s\-—–()（）]{2,24})"
        r"(?:\s*[（(]\s*(?P<code>(?:HK\.\d{1,5}|\d{1,5}\.HK|"
        r"(?:(?:SH|SZ|BJ|A)\.)?\d{6}(?:\.(?:SH|SZ|BJ))?))\s*[）)])?"
        r"\s*[-—–]\s*(?P<body>.+)",
        publisher_title,
        re.I,
    )
    publisher = ""
    publisher_code: str | None = None
    publisher_body_start: int | None = None
    if prefix:
        label = prefix.group("label")
        if label.endswith(("证券", "券商", "研究所", "投研")) or label in _BROKER_LABELS:
            publisher = label
            publisher_code = canonical_title_code(prefix.group("code")) if prefix.group("code") else None
            publisher_body_start = publisher_title_offset + prefix.start("body")

    subjects: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in [*_NAMED_CODE.finditer(text), *_NAMED_DASH_CODE.finditer(text)]:
        code = canonical_title_code(match.group("code"))
        name = match.group("name")
        is_code_bearing_publisher_prefix = (
            bool(publisher)
            and publisher_code is not None
            and publisher_body_start is not None
            and match.start() < publisher_body_start
            and name == publisher
            and code == publisher_code
        )
        if is_code_bearing_publisher_prefix:
            continue
        if code and (name, code) not in seen:
            seen.add((name, code))
            subjects.append({"name": name, "code": code, "raw_code": match.group("code"),
                             "market": "HK" if code.startswith("HK.") else "A",
                             "evidence": match.group(0), "identity_status": "TITLE_TEXT_ONLY"})
    report_mode = bool(publisher or re.search(r"\.pdf\b", text, re.I) or source_type in {"research_db", "research_report"})
    return {"is_report": report_mode, "publisher": publisher or None, "subjects": subjects,
            "title": text, "scope": "TITLE_TEXT_NOT_SECURITY_MASTER_NOT_RECOMMENDATION_CLEARANCE"}


def classify_report_entity(title: str, code: Any, name: Any, source_type: str = "") -> dict[str, Any]:
    info = report_title_evidence(title, source_type)
    entity_code = canonical_title_code(code)
    entity_name = str(name or "").strip()
    subjects = info["subjects"]
    role = "NONREPORT_EXISTING_ENTITY"
    eligible = True
    if info["is_report"]:
        eligible = False
        explicit = [s for s in subjects if entity_code and s["code"] == entity_code]
        same_name = [s for s in subjects if entity_name and s["name"] == entity_name]
        if explicit:
            role = "TITLE_SUBJECT_EXPLICIT_CODE"
            eligible = True
        elif same_name:
            role = "EXPLICIT_MARKET_OR_CODE_CONFLICT"
        elif entity_name and entity_name == info["publisher"]:
            role = "REPORT_PUBLISHER"
        elif entity_name and entity_name in info["title"] and not subjects:
            role = "TITLE_NAME_MARKET_UNCONFIRMED"
        else:
            role = "BODY_OR_OTHER_ENTITY_MENTION"
    return {"entity_role": role, "research_subject_eligible": eligible,
            "report_publisher": info["publisher"], "title_subjects": deepcopy(subjects),
            "entity_classification_scope": info["scope"], "classification_is_report": info["is_report"]}


def project_report_roles(lane: dict[str, Any]) -> dict[str, Any]:
    """Annotate verified reader outputs; retain all original entities and scores.

    Only a separate subject-eligibility field is added. The browser must show
    excluded original entities as evidence rather than quietly deleting them.
    """
    output = deepcopy(lane)
    timeline = output.get("stock_research_timeline")
    timeline = timeline if isinstance(timeline, list) else []
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    subjects: dict[tuple[str, str], dict[str, Any]] = {}
    for row in timeline:
        if not isinstance(row, dict):
            continue
        title = str(row.get("source_title") or row.get("title") or "")
        classification = classify_report_entity(title, row.get("stock_code") or row.get("code"), row.get("stock_name") or row.get("name"), str(row.get("source_type") or ""))
        row.update(classification)
        grouped.setdefault(str(row.get("stock_code") or row.get("code") or ""), []).append(row)
        for subject in classification["title_subjects"]:
            key = (subject["code"], title)
            subjects.setdefault(key, {**subject, "source_title": title,
                "source_path": row.get("source_path"), "event_id": row.get("event_id") or row.get("evidence_id"),
                "formal_eligible": False})
    pool = output.get("stock_research_daily")
    for row in pool if isinstance(pool, list) else []:
        if not isinstance(row, dict):
            continue
        events = grouped.get(str(row.get("stock_code") or row.get("code") or ""), [])
        if events:
            row["report_subject_eligible"] = any(event.get("research_subject_eligible") is True for event in events)
            row["entity_roles"] = list(dict.fromkeys(str(event["entity_role"]) for event in events))
            row["subject_evidence_count"] = sum(event.get("research_subject_eligible") is True for event in events)
            row["original_entity_evidence_count"] = len(events)
        else:
            row["report_subject_eligible"] = None
            row["entity_roles"] = ["SOURCE_EVENT_BINDING_MISSING"]
    zsxq = output.get("zsxq_hourly")
    for row in (zsxq.get("items") or []) if isinstance(zsxq, dict) else []:
        if isinstance(row, dict):
            row.update(classify_report_entity(str(row.get("title") or row.get("source_title") or ""), row.get("stock_code") or row.get("code"), row.get("stock_name") or row.get("name"), "zsxq"))
    output["report_title_subjects"] = list(subjects.values())
    output["report_entity_classification"] = {
        "scope": "READ_ONLY_TITLE_ROLE_PROJECTION_ORIGINAL_ENTITIES_AND_SCORES_RETAINED",
        "active_producer_fixed": False, "historical_artifacts_rebuilt": False,
        "source_owner_status": "EXACT_ACTIVE_PRODUCER_PREIMAGE_REQUIRED", "formal_eligible": False,
    }
    return output
