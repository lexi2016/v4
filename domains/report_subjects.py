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

# Accepted Main source dependency; API project_report_roles and its existing
# pure title/classification functions above retain their exact prior bodies.
_MAIN_EXPLICIT_REPORT_MARKER = re.compile(r"(?:#研报#|#研究报告#)")
POLICY_VERSION = "report_subject_scoring.v1"

def _main_report_title_evidence(title: str, source_type: str='') -> dict[str, Any]:
    text = str(title or '').splitlines()[0] if str(title or '').splitlines() else ''
    publisher_title = re.sub('^(?:\\s*#[^#\\n]{1,30}#\\s*[｜|：:]?\\s*)+', '', text)
    publisher_title_offset = len(text) - len(publisher_title)
    prefix = re.match('^\\s*(?P<label>[^\\s\\-—–()（）]{2,24})(?:\\s*[（(]\\s*(?P<code>(?:HK\\.\\d{1,5}|\\d{1,5}\\.HK|(?:(?:SH|SZ|BJ|A)\\.)?\\d{6}(?:\\.(?:SH|SZ|BJ))?))\\s*[）)])?\\s*[-—–]\\s*(?P<body>.+)', publisher_title, re.I)
    publisher = ''
    publisher_code: str | None = None
    publisher_body_start: int | None = None
    if prefix:
        label = prefix.group('label')
        if label.endswith(('证券', '券商', '研究所', '投研')) or label in _BROKER_LABELS:
            publisher = label
            publisher_code = canonical_title_code(prefix.group('code')) if prefix.group('code') else None
            publisher_body_start = publisher_title_offset + prefix.start('body')
    subjects: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in [*_NAMED_CODE.finditer(text), *_NAMED_DASH_CODE.finditer(text)]:
        code = canonical_title_code(match.group('code'))
        name = match.group('name')
        is_code_bearing_publisher_prefix = bool(publisher) and publisher_code is not None and (publisher_body_start is not None) and (match.start() < publisher_body_start) and (name == publisher) and (code == publisher_code)
        if is_code_bearing_publisher_prefix:
            continue
        if code and (name, code) not in seen:
            seen.add((name, code))
            subjects.append({'name': name, 'code': code, 'raw_code': match.group('code'), 'market': 'HK' if code.startswith('HK.') else 'A', 'evidence': match.group(0), 'identity_status': 'TITLE_TEXT_ONLY'})
    report_mode = bool(publisher or _MAIN_EXPLICIT_REPORT_MARKER.search(text) or re.search('\\.pdf\\b', text, re.I) or (source_type in {'research_db', 'research_report'}))
    return {'is_report': report_mode, 'publisher': publisher or None, 'subjects': subjects, 'title': text, 'scope': 'TITLE_TEXT_NOT_SECURITY_MASTER_NOT_RECOMMENDATION_CLEARANCE'}

def _main_classify_report_entity(title: str, code: Any, name: Any, source_type: str='') -> dict[str, Any]:
    info = _main_report_title_evidence(title, source_type)
    entity_code = canonical_title_code(code)
    entity_name = str(name or '').strip()
    subjects = info['subjects']
    role = 'NONREPORT_EXISTING_ENTITY'
    eligible = True
    if info['is_report']:
        eligible = False
        explicit = [s for s in subjects if entity_code and s['code'] == entity_code]
        same_name = [s for s in subjects if entity_name and s['name'] == entity_name]
        if explicit:
            role = 'TITLE_SUBJECT_EXPLICIT_CODE'
            eligible = True
        elif same_name:
            role = 'EXPLICIT_MARKET_OR_CODE_CONFLICT'
        elif entity_name and entity_name == info['publisher']:
            role = 'REPORT_PUBLISHER'
        elif entity_name and entity_name in info['title'] and (not subjects):
            role = 'TITLE_NAME_MARKET_UNCONFIRMED'
        else:
            role = 'BODY_OR_OTHER_ENTITY_MENTION'
    return {'entity_role': role, 'research_subject_eligible': eligible, 'report_publisher': info['publisher'], 'title_subjects': deepcopy(subjects), 'entity_classification_scope': info['scope'], 'classification_is_report': info['is_report']}

def bind_report_attachments(topic: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Bind an entity to its own explicit attachment title, never a neighbour's.

    Non-subject entities remain as excluded evidence. This is a textual binding,
    not a master/Connect attestation, and cannot recover omitted attachment names.
    Caller retains the original topic and company array in the raw source record.
    """
    title = str(topic.get('title') or topic.get('evidence') or '知识星球研报')
    files = topic.get('attachment_file_names')
    titles = list(dict.fromkeys((str(v) for v in files if isinstance(v, str) and v))) if isinstance(files, list) else []
    report_titles = [v for v in titles if _main_report_title_evidence(v)['is_report']]
    companies = topic.get('companies')
    companies = [companies] if isinstance(companies, Mapping) else companies if isinstance(companies, list) else []
    out: list[dict[str, Any]] = []
    for company in companies:
        if not isinstance(company, Mapping):
            continue
        choices = report_titles or [title]
        classified = [(t, _main_classify_report_entity(t, company.get('code'), company.get('name'), 'zsxq')) for t in choices]
        subject_matches = [(t, c) for t, c in classified if c['research_subject_eligible']]
        matches = subject_matches or [(t, c) for t, c in classified if c['entity_role'] in {'REPORT_PUBLISHER', 'EXPLICIT_MARKET_OR_CODE_CONFLICT', 'TITLE_NAME_MARKET_UNCONFIRMED'}]
        if not matches:
            unmatched = _main_classify_report_entity('', company.get('code'), company.get('name'), 'research_report')
            unmatched.update(entity_role='UNMATCHED_REPORT_ATTACHMENT', research_subject_eligible=False, report_publisher=None, title_subjects=[])
            matches = [('', unmatched)]
        for bound_title, classification in matches:
            binding = {**deepcopy(dict(company)), **classification, 'original_topic_title': title, 'attachment_binding_status': 'NO_MATCH_UNCONFIRMED' if classification['entity_role'] == 'UNMATCHED_REPORT_ATTACHMENT' else 'TITLE_TEXT_ONLY' if classification['research_subject_eligible'] else 'EXCLUDED_OR_UNCONFIRMED', 'attachment_names_complete': topic.get('attachment_file_count', len(titles)) == len(titles)}
            if bound_title:
                binding['bound_source_title'] = bound_title
            out.append(binding)
    return out

def apply_report_subject_policy(source: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute only groups affected by report-role exclusions.

    Retain all raw records, entities, timeline rows and article IDs. Existing
    30/15/5 + 5 per distinct source, capped at 100, is unchanged; only eligible
    evidence participates. Unaffected groups are byte-semantically unchanged.
    Recomputed from source titles every time; caller supplied flags are not trusted.
    """
    out = deepcopy(dict(source))
    timeline = out.get('stock_research_timeline')
    if not isinstance(timeline, list):
        raise ValueError('REPORT_POLICY_TIMELINE_MISSING')
    grouped: dict[str, list[dict[str, Any]]] = {}
    audit: list[dict[str, Any]] = []
    for row in timeline:
        if not isinstance(row, dict):
            continue
        role = _main_classify_report_entity(str(row.get('source_title') or row.get('title') or ''), row.get('stock_code') or row.get('code'), row.get('stock_name') or row.get('name'), str(row.get('source_type') or ''))
        cannot_confirm = row.get('cannot_confirm')
        if isinstance(cannot_confirm, (list, tuple)) and 'ZSXQ_REPORT_ATTACHMENT_UNMATCHED' in cannot_confirm:
            role.update(entity_role='UNMATCHED_REPORT_ATTACHMENT', research_subject_eligible=False)
        row.update(role)
        code = str(row.get('stock_code') or row.get('code') or '')
        grouped.setdefault(code, []).append(row)
        if not role['research_subject_eligible']:
            audit.append({'stock_code': code, 'source_title': row.get('source_title') or row.get('title'), 'source_path': row.get('source_path'), 'evidence_id': row.get('evidence_id'), 'entity_role': role['entity_role'], 'research_subject_eligible': False})
    affected = {row['stock_code'] for row in audit}
    daily = out.get('stock_research_daily')
    if not isinstance(daily, list):
        raise ValueError('REPORT_POLICY_DAILY_MISSING')
    new_scores: dict[str, dict[str, Any]] = {}
    for row in daily:
        if not isinstance(row, dict) or str(row.get('stock_code')) not in affected:
            continue
        code = str(row['stock_code'])
        eligible = [r for r in grouped[code] if r['research_subject_eligible']]
        strong = sum((r.get('evidence_level') == 'L3_STRONG' for r in eligible))
        medium = sum((r.get('evidence_level') == 'L2_MEDIUM' for r in eligible))
        weak = sum((r.get('evidence_level') == 'L1_WEAK' for r in eligible))
        types = sorted({str(r.get('source_type') or '') for r in eligible})
        points = sum((30 if r.get('evidence_level') == 'L3_STRONG' else 15 if r.get('evidence_level') == 'L2_MEDIUM' else 5 for r in eligible))
        status = 'HOT' if strong else 'REPEATED' if len(eligible) >= 2 else 'CANNOT_CONFIRM' if not eligible or eligible[0].get('cannot_confirm') else 'NEW'
        row.update(research_score=min(points + 5 * len(types), 100), research_status=status, evidence_count=len(eligible), source_count=len(types), strong_evidence_count=strong, medium_evidence_count=medium, weak_evidence_count=weak, source_types=types, themes=sorted({str(r['theme']) for r in eligible if r.get('theme')}), top_catalysts=sorted({str(r['catalyst']) for r in eligible if r.get('catalyst')}), latest_evidence_sentence=str(eligible[-1].get('evidence_sentence') or '') if eligible else '', report_subject_eligible=bool(eligible), original_entity_evidence_count=len(grouped[code]))
        new_scores[code] = row
    for row in out.get('research_pool_bridge') or []:
        if not isinstance(row, dict) or str(row.get('stock_code')) not in new_scores:
            continue
        daily_row = new_scores[str(row['stock_code'])]
        row['research_score'] = daily_row['research_score']
        row['evidence_level'] = 'L3_STRONG' if daily_row['strong_evidence_count'] else 'L2_MEDIUM' if daily_row['medium_evidence_count'] else 'L1_WEAK'
        row['report_subject_eligible'] = daily_row['report_subject_eligible']
        row['source_evidence_ids'] = [r['evidence_id'] for r in grouped[str(row['stock_code'])] if r.get('research_subject_eligible') and r.get('evidence_id')]
        if not daily_row['report_subject_eligible']:
            row['reason'] = '原证券实体证据保留；无已确认报告对象证据，不贡献研究评分。'
    if affected:
        daily.sort(key=lambda r: (-float(r.get('research_score') or 0), str(r.get('first_seen_time') or ''), str(r.get('stock_code') or '')))
    out['report_entity_audit'] = {'policy_version': POLICY_VERSION, 'excluded_evidence': audit, 'excluded_evidence_count': len(audit), 'affected_codes': sorted(affected), 'score_weights_changed': False, 'security_master_attested': False, 'original_entities_retained': True, 'historical_capture_reconstructed': False}
    return out
