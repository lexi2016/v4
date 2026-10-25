"""Conservative, source-unit-bound extraction for the temporary SIMPLE canary.

This module does not decide article disposition.  It records explicit labels,
rows, and narrowly defined arithmetic from a complete article body.  Any
relationship that cannot be tied to an exact source unit stays CANNOT_CONFIRM.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
from typing import Any, Iterable


PROTOCOL = "simple_fixed_facts_v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(
    r"(?P<date>(?:19|20)\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|"
    r"(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2})"
)
NUMBER_RE = re.compile(r"(?<![A-Za-z])[-−]?\d[\d,]*(?:\.\d+)?")
PERCENT_RE = re.compile(r"([-−]?\d[\d,]*(?:\.\d+)?)\s*%")
COMPANY_LABEL_RE = re.compile(
    r"^\s*(?:公司名稱|公司名称|發行人名稱|发行人名称|公司名稱|issuer\s+name|company\s+name)\s*[:：]?\s*(.*?)\s*$",
    re.IGNORECASE,
)
ISSUER_ROLE_LABEL_RE = re.compile(
    r"^\s*(?:發行人名稱|发行人名称|issuer\s+name)\s*[:：]?\s*(.*?)\s*$",
    re.IGNORECASE,
)
CODE_LABEL_RE = re.compile(
    r"(?:證券代號|证券代号|股份代號|股份代号|股票代碼|股票代码|證券代碼|证券代码|stock\s*code)"
    r"\s*(?:[（(][^）)]*[）)])?\s*[:：]?\s*([0-9]{4,6})",
    re.IGNORECASE,
)
LEGAL_SUFFIX_RE = re.compile(
    r"(?:有限責任公司|有限责任公司|股份有限公司|有限公司|有限合夥|有限合伙|"
    r"Limited(?:\s+Partnership)?|Co\.?\s*,?\s*Ltd\.?|Corporation|Corp\.?|Inc\.?)",
    re.IGNORECASE,
)
COMPANY_PHRASE_RE = re.compile(
    r"(?:中文公司名稱為|中文公司名称为|公司名稱為|公司名称为)\s*"
    r"(?P<name>[\u3400-\u9fffA-Za-z0-9&.,'’()（）\- ]{2,100}?"
    r"(?:有限責任公司|有限责任公司|股份有限公司|有限公司|Limited|Co\.?\s*,?\s*Ltd\.?|Corporation|Corp\.?|Inc\.?))"
    r"(?:的公司名稱|的公司名称)?",
    re.IGNORECASE,
)
PENDING_RE = re.compile(r"(?:擬註銷但(?:截至[^\s，,]{0,20})?尚未註銷|擬注销但(?:截至[^\s，,]{0,20})?尚未注销|待註銷但尚未註銷|待注销但尚未注销|pending\s+cancel(?:lation)?)", re.IGNORECASE)
TREASURY_RE = re.compile(r"(?:股份被持作庫存股份|股份被持作库存股份|持作庫存股份|持作库存股份|庫存股份變動|库存股份变动|treasury\s+shares?)", re.IGNORECASE)
CANCELLED_RE = re.compile(r"(?:已註銷|已注销|cancelled|canceled)", re.IGNORECASE)
EVENT_ROW_RE = re.compile(r"^\s*(?:(?:\d+\s*\)\.?|[A-Z]\s*[.)、．])\s*)?(?:購回股份|购回股份|股份回購|股份回购|回購股份|回购股份|贖回股份|赎回股份|repurchase|buyback)", re.IGNORECASE)
BALANCE_RE = re.compile(r"^\s*(?:上月底結存|上月底结存|本月底結存|本月底结存|期初結存|期初结存|期末結存|期末结存|於下列日期開始時的結存|于下列日期开始时的结存|於下列日期結束時的結存|于下列日期结束时的结存|opening\s+balance|closing\s+balance)", re.IGNORECASE)
MOVEMENT_RE = re.compile(r"^\s*(?:增加\s*/\s*減少|增加\s*/\s*减少|增加或減少|增加或减少|increase\s*/\s*decrease)", re.IGNORECASE)
SUMMARY_STATUS_RE = re.compile(r"(?:合共購回股份總數|合共回購股份總數|购回股份（擬註銷）數目|購回股份（擬註銷）數目|购回股份（擬持作庫存股份）數目|購回股份（擬持作庫存股份）數目|购回股份（拟持作库存股份）数目|購回股份（拟持作库存股份）数目)", re.IGNORECASE)
DAILY_HEADER_RE = re.compile(r"交易日.*(?:購回股份數目|购回股份数目).*(?:每股最高|每股最高購回價|每股最低|最低購回價|付出的價格總額|付出的价格总额)", re.IGNORECASE)
AUTH_DATE_RE = re.compile(r"(?:購回|回購|购回|回购)授權.*(?:決議|决议).*(?:獲通過|获通过|通過|通过).*(?:日期|date)", re.IGNORECASE)
AUTH_TOTAL_RE = re.compile(r"(?:(?:發行人|发行人).*可(?:根據|根据)|可(?:根據|根据)).*(?:購回授權|回購授權|购回授权|回购授权).*(?:總數|总数|total)", re.IGNORECASE)
AUTH_CUMULATIVE_RE = re.compile(r"根據購回授權|根據回購授權|根据购回授权|根据回购授权|under\s+the\s+repurchase\s+mandate", re.IGNORECASE)
AUTH_PERCENT_RE = re.compile(r"(?:佔|占).*(?:購回授權|回購授權|购回授权|回购授权).*(?:百分比|百分率|percentage)", re.IGNORECASE)
AUTH_DENOM_NOTE_RE = re.compile(
    r"(?:截至|於|于).{0,100}(?:購回|回購|购回|回购)授權.{0,100}(?:[決决]議[獲获]通過|[決决]議通過).{0,100}"
    r"(?:已發行股份總數|已发行股份总数|total\s+issued\s+shares)",
    re.IGNORECASE,
)
FORMULA_RE = re.compile(r"(?:\(a\)|（a）|a)\s*[×x*]\s*100\s*/", re.IGNORECASE)
REFERENCE_ONLY_RE = re.compile(r"(?:僅供參閱|仅供参阅|僅供參考|仅供参考|for\s+reference\s+only)", re.IGNORECASE)
PERIOD_RE = re.compile(
    r"(?:截至|截至本公司及其附屬公司|截至本公司及其附属公司)\s*"
    r"(?P<date>(?:19|20)\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2})\s*止"
    r"(?P<term>[^，,。；;\n]{0,30})",
    re.IGNORECASE,
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha(raw)


def _norm_date(value: str) -> str | None:
    text = re.sub(r"\s+", "", value)
    if "年" in text:
        match = re.fullmatch(r"((?:19|20)\d{2})年(\d{1,2})月(\d{1,2})日", text)
        if not match:
            return None
        year, month, day = map(int, match.groups())
    else:
        match = re.fullmatch(r"((?:19|20)\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
        if not match:
            return None
        year, month, day = map(int, match.groups())
    try:
        from datetime import date

        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _number_token(value: str) -> str | None:
    normalized = value.replace(",", "").replace("−", "-")
    try:
        Decimal(normalized)
    except InvalidOperation:
        return None
    return normalized


def _last_number(text: str) -> str | None:
    matches = list(NUMBER_RE.finditer(text))
    for match in reversed(matches):
        token = _number_token(match.group(0))
        if token is not None:
            return token
    return None


def _ref_for_line(line: dict[str, Any], unit_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    unit = unit_by_id[line["source_unit_id"]]
    return {
        "source_unit_id": unit["source_unit_id"],
        "source_unit_sha256": unit["unit_sha256"],
        "unit_start_cp": unit["start_cp"],
        "unit_end_cp": unit["end_cp"],
        "line_start_cp": line["start_cp"],
        "line_end_cp": line["end_cp"],
        "line_sha256": _sha(line["text"].encode("utf-8")),
    }


def _whitespace_compact_view(text: str) -> tuple[str, list[int]]:
    """Return a matching-only view and a deterministic map to original offsets."""
    characters: list[str] = []
    original_offsets: list[int] = []
    for offset, character in enumerate(text):
        if character.isspace():
            continue
        characters.append(character)
        original_offsets.append(offset)
    return "".join(characters), original_offsets


def _original_span_from_view(
    text: str,
    original_offsets: list[int],
    span: tuple[int, int],
) -> tuple[int, int]:
    """Map a non-normalized matching span back to the unchanged source text."""
    start, end = span
    if start < 0 or end < start or end > len(original_offsets):
        raise ValueError("FIXED_FACT_NORMALIZED_OFFSET_INVALID")
    if start == end:
        original = original_offsets[start] if start < len(original_offsets) else len(text)
        return original, original
    return original_offsets[start], original_offsets[end - 1] + 1


def _build_lines(body: str, source_units: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    units = list(source_units)
    cursor = 0
    unit_by_id: dict[str, dict[str, Any]] = {}
    for unit in units:
        if not isinstance(unit, dict) or not isinstance(unit.get("source_unit_id"), str):
            raise ValueError("FIXED_FACT_SOURCE_UNIT_INVALID")
        if unit["source_unit_id"] in unit_by_id or unit.get("start_cp") != cursor:
            raise ValueError("FIXED_FACT_SOURCE_UNIT_PARTITION_INVALID")
        text = unit.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("FIXED_FACT_SOURCE_UNIT_INVALID")
        if _sha(text.encode("utf-8")) != unit.get("unit_sha256"):
            raise ValueError("FIXED_FACT_SOURCE_UNIT_SHA_MISMATCH")
        if unit.get("end_cp") != cursor + len(text):
            raise ValueError("FIXED_FACT_SOURCE_UNIT_OFFSETS_INVALID")
        cursor += len(text)
        unit_by_id[unit["source_unit_id"]] = unit
    if cursor != len(body) or "".join(unit["text"] for unit in units) != body:
        raise ValueError("FIXED_FACT_SOURCE_UNIT_PARTITION_INVALID")

    lines: list[dict[str, Any]] = []
    offset = 0
    unit_index = 0
    for raw_line in body.splitlines(keepends=True):
        text = raw_line.rstrip("\r\n")
        while unit_index + 1 < len(units) and offset >= units[unit_index]["end_cp"]:
            unit_index += 1
        if text:
            unit = units[unit_index]
            if not (unit["start_cp"] <= offset and offset + len(raw_line) <= unit["end_cp"]):
                raise ValueError("FIXED_FACT_LINE_CROSSES_SOURCE_UNIT")
            lines.append({
                "text": text,
                "raw_text": raw_line,
                "start_cp": offset,
                "end_cp": offset + len(raw_line),
                "line_number": len(lines) + 1,
                "source_unit_id": unit["source_unit_id"],
            })
        offset += len(raw_line)
    if offset != len(body):
        raise ValueError("FIXED_FACT_LINE_PARTITION_INVALID")
    return lines, unit_by_id


def _reader_claims_for_line(line: dict[str, Any], unit: dict[str, Any]) -> list[str]:
    """Resolve prose to complete, unchanged sentences inside its original unit.

    Physical lines remain the extraction inputs for typed records. Reader
    claims instead use source sentence boundaries, so a PDF hard wrap cannot
    turn a date-bearing sentence into a verified fragment. This is deliberately
    conservative: unresolved prose rejects the ledger rather than disappearing.
    """
    text = line["text"].strip()
    source = unit["text"]
    start = line["start_cp"] - unit["start_cp"]
    previous = source[:start].rstrip()
    # These are existing, explicitly labeled atomic fields/rows, not prose
    # continuations. Do not concatenate a table or an issuer header with prose.
    legal_suffix = LEGAL_SUFFIX_RE.search(text)
    standalone_name = (
        legal_suffix is not None and legal_suffix.end() == len(text)
        and len(text) <= 140 and not re.search(r"[，。；;:：|]", text)
    )
    date_prefix = DATE_RE.match(text)
    numeric_date_row = (
        date_prefix is not None
        and re.fullmatch(
            r"(?:\s+(?:(?:HKD|HK\$|RMB|CNY|USD)\s*)?[-−]?\d[\d,]*(?:\.\d+)?%?){4}",
            text[date_prefix.end():], re.IGNORECASE,
        ) is not None
    )
    labeled_date = re.fullmatch(
        r"(?:呈交日期|提交日期|截至月份|截至本月底|變動日期|变动日期|事件發生日期|事件发生日期|交易日|"
        r"filing\s*date|event\s*date|trading\s*date)\s*[:：]?\s*" + DATE_RE.pattern,
        text, re.IGNORECASE,
    ) is not None
    # A label prefix proves only its field value, not a narrative suffix.
    # Preserve the existing code/name pair format, but require its whole tail
    # to be another explicit field rather than arbitrary prose.
    code_text = text.lstrip("（(")
    code_label = CODE_LABEL_RE.match(code_text)
    pure_code_line = code_label is not None and re.fullmatch(
        r"[）)]?(?:(?:\s+|[，,]\s*)(?:证券简称|證券簡稱)\s*[:：]\s*[^，,。；;！？!?]+)?",
        code_text[code_label.end():],
    ) is not None
    company_label = COMPANY_LABEL_RE.match(text)
    company_value = company_label.group(1).strip() if company_label else ""
    company_suffix = LEGAL_SUFFIX_RE.search(company_value)
    pure_company_line = (
        company_suffix is not None and company_suffix.end() == len(company_value)
        and not re.search(r"[，,。；;:：|]", company_value[:company_suffix.start()])
    )
    narrative_separator = re.search(r"[，。；;！？!?]|(?<!\d),|,(?!\d{3}(?:\D|$))", text)
    complete_reference_notice = (
        REFERENCE_ONLY_RE.search(text) is not None
        and text.endswith(("。", "！", "？", ".", "!", "?"))
        and (not previous or previous.endswith(("。", "！", "？", ".", "!", "?")))
    )
    structured = (
        DATE_RE.fullmatch(text) is not None
        or labeled_date
        or numeric_date_row
        or standalone_name
        or pure_company_line
        or pure_code_line
        or any(pattern.match(text) for pattern in (BALANCE_RE, MOVEMENT_RE, EVENT_ROW_RE))
        or (SUMMARY_STATUS_RE.search(text) is not None and NUMBER_RE.search(text) is not None)
        or any(pattern.search(text) for pattern in (AUTH_DATE_RE, AUTH_TOTAL_RE, AUTH_PERCENT_RE))
        # Retain the existing complete reference-only disclosure together
        # with its qualification; do not detach the notice from its subject.
        or complete_reference_notice
    )
    if structured and (not narrative_separator or standalone_name or pure_company_line
                       or pure_code_line or complete_reference_notice):
        return [text]

    end = start + len(line["text"])
    claims: list[str] = []
    cursor = 0
    # A full stop inside a decimal or URL is not a sentence boundary.
    endings = re.finditer(r"[。！？!?][”’」』\"']*|(?<![0-9])\.(?=\s|$)", source)
    spans = []
    for match in endings:
        spans.append((cursor, match.end(), True))
        cursor = match.end()
    spans.append((cursor, len(source), False))
    for left, right, terminated in spans:
        while left < right and source[left].isspace():
            left += 1
        while right > left and source[right - 1].isspace():
            right -= 1
        if left >= right or left >= end or right <= start:
            continue
        sentence = source[left:right]
        if not terminated:
            raise ValueError("FIXED_FACT_READER_CLAIM_INCOMPLETE")
        parts = sentence.splitlines()
        if len(parts) > 1:
            # A source unit can also hold headings/table blocks. It is not
            # permission to join those blocks or a newly introduced subject.
            boundary = re.compile(
                r"^(?:第[一二三四五六七八九十百0-9]+[章节章節部分]|"
                r"[一二三四五六七八九十]+[、．.]|[（(][一二三四五六七八九十0-9]+[）)]|"
                r"[A-Z][.、]|其他事項|其他事项|風險提示|风险提示|備查文件|备查文件|"
                r"(?:证券代码|證券代號|证券简称|公司名称|公司名稱|发行人|發行人|主承销商|主承銷商)\s*[:：])"
            )
            for index, part in enumerate(parts):
                stripped = part.strip()
                if (
                    not stripped or boundary.match(stripped)
                    or re.search(r"[|\t]|\S {2,}\S", part)
                    or (index and re.match(r"(?:本公司|另一家公司|另一公司|該公司|该公司|发行人|發行人)", stripped))
                ):
                    raise ValueError("FIXED_FACT_READER_CLAIM_AMBIGUOUS_BOUNDARY")
        # Keep internal newlines and all wording. The existing reader schema
        # cites the entire original unit; this exact substring is within it.
        claims.append(sentence)
    if not claims:
        raise ValueError("FIXED_FACT_READER_CLAIM_INCOMPLETE")
    return claims


def extract_fixed_facts(
    article_body: str,
    source_unit_map: dict[str, Any],
    article_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract explicit fixed facts and preserve an exact source-unit trace."""
    if not isinstance(article_body, str) or not article_body:
        raise ValueError("FIXED_FACT_BODY_INVALID")
    body_sha = _sha(article_body.encode("utf-8"))
    if not SHA_RE.fullmatch(str(source_unit_map.get("source_unit_map_sha256", ""))) or source_unit_map.get("body_sha256") != body_sha:
        raise ValueError("FIXED_FACT_SOURCE_UNIT_MAP_IDENTITY_INVALID")
    lines, unit_by_id = _build_lines(article_body, source_unit_map.get("units", []))
    # Keep article_metadata in the call contract for compatibility, but never
    # let a short or translated metadata alias establish source issuer identity.
    records: list[dict[str, Any]] = []
    facts: list[dict[str, str]] = []
    changes: list[dict[str, str]] = []
    seen_record_keys: set[str] = set()
    seen_reader_keys: set[tuple[str, str, str]] = set()
    unknowns: list[dict[str, Any]] = []

    def add_record(kind: str, label: str, value: Any, refs: list[dict[str, Any]], *, scope: str = "article_disclosure", status: str = "VERIFIED_FROM_SOURCE") -> dict[str, Any]:
        record = {
            "record_id": f"F{len(records) + 1:04d}",
            "kind": kind,
            "label": label,
            "value": value,
            "scope": scope,
            "status": status,
            "source_refs": refs,
        }
        key = _canonical_sha(record)
        if key in seen_record_keys:
            return next(item for item in records if _canonical_sha(item) == key)
        seen_record_keys.add(key)
        records.append(record)
        return record

    def add_reader(field: str, line: dict[str, Any], *, claim: str | None = None) -> None:
        unit = unit_by_id[line["source_unit_id"]]
        if claim is not None and claim != line["text"].strip():
            raise ValueError("FIXED_FACT_READER_CUSTOM_CLAIM_UNSUPPORTED")
        for exact_claim in _reader_claims_for_line(line, unit):
            if exact_claim not in unit["text"]:
                raise ValueError("FIXED_FACT_READER_CLAIM_OUTSIDE_SOURCE_UNIT")
            key = (field, line["source_unit_id"], exact_claim)
            if key in seen_reader_keys:
                continue
            seen_reader_keys.add(key)
            target = facts if field == "facts" else changes
            target.append({"claim": exact_claim, "source_unit_id": line["source_unit_id"]})

    def add_line(
        kind: str,
        label: str,
        value: Any,
        line: dict[str, Any],
        *,
        field: str = "facts",
        scope: str = "article_disclosure",
        match_span: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        refs = [_ref_for_line(line, unit_by_id)]
        if match_span is not None:
            start, end = match_span
            if start < 0 or end <= start or end > len(line["text"]):
                raise ValueError("FIXED_FACT_MATCH_SPAN_INVALID")
            quote = line["text"][start:end]
            refs[0].update({
                "match_start_cp": line["start_cp"] + start,
                "match_end_cp": line["start_cp"] + end,
                "match_quote": quote,
                "match_sha256": _sha(quote.encode("utf-8")),
            })
        if kind in {"issuer_name", "security_code"}:
            existing = next((
                record for record in records
                if record["kind"] == kind
                and record["value"] == value
                and [ref["source_unit_id"] for ref in record["source_refs"]] == [ref["source_unit_id"] for ref in refs]
            ), None)
            if existing is not None:
                add_reader(field, line)
                return existing
        record = add_record(kind, label, value, refs, scope=scope)
        add_reader(field, line)
        return record

    def standalone_legal_name_span(value: str) -> tuple[int, int] | None:
        if len(value) > 140:
            return None
        compact, offsets = _whitespace_compact_view(value)
        suffix = LEGAL_SUFFIX_RE.search(compact)
        if not suffix or suffix.end() != len(compact):
            return None
        prefix = compact[:suffix.start()]
        if not prefix or re.search(r"[，,。；;:：|]", prefix):
            return None
        start, end = _original_span_from_view(value, offsets, (0, len(compact)))
        return start, end

    def is_registration_descriptor(value: str) -> bool:
        compact, _ = _whitespace_compact_view(value)
        return (
            len(compact) <= 160
            and compact.startswith(("（", "("))
            and compact.endswith(("）", ")"))
            and re.search(r"(?:註冊成立|注册成立|registered|incorporated)", compact, re.IGNORECASE) is not None
        )

    # Issuer names are accepted from the opening issuer header only. The HKEX
    # disclaimer is a known preamble; every other line before the first body
    # code label must itself be an issuer name/label or registration descriptor.
    # A later signature or subsidiary name therefore cannot establish identity.
    disclaimer_unit_ids: set[str] = set()
    for unit in source_unit_map.get("units", []):
        compact_unit = re.sub(r"\s+", "", unit["text"])
        if (
            "香港交易及結算所有限公司" in compact_unit
            and "香港聯合交易所有限公司" in compact_unit
            and "概不負責" in compact_unit
        ):
            disclaimer_unit_ids.add(unit["source_unit_id"])

    first_code_line_index: int | None = None
    for index, line in enumerate(lines):
        compact_line, _ = _whitespace_compact_view(line["text"])
        if CODE_LABEL_RE.search(compact_line):
            first_code_line_index = index
            break

    header_issuer_line_indices: set[int] = set()
    if first_code_line_index is not None:
        header_lines: set[int] = set()
        prefix_is_header = True
        for index, line in enumerate(lines[:first_code_line_index]):
            if not line["text"].strip():
                continue
            if line["source_unit_id"] in disclaimer_unit_ids:
                continue
            company_label = COMPANY_LABEL_RE.match(line["text"])
            company_phrase = COMPANY_PHRASE_RE.search(line["text"])
            if (
                standalone_legal_name_span(line["text"]) is not None
                or company_label is not None
                or company_phrase is not None
                or is_registration_descriptor(line["text"])
            ):
                if standalone_legal_name_span(line["text"]) is not None or company_label or company_phrase:
                    header_lines.add(index)
                continue
            prefix_is_header = False
            break
        if prefix_is_header:
            header_issuer_line_indices = header_lines

    # Capture explicit company/code labels and legal-name phrases.
    for line_index, line in enumerate(lines):
        legal_name_span = standalone_legal_name_span(line["text"])
        if legal_name_span is not None and line_index in header_issuer_line_indices:
            name_quote = line["text"][legal_name_span[0]:legal_name_span[1]]
            add_line(
                "issuer_name",
                "standalone_source_legal_name",
                name_quote,
                line,
                match_span=legal_name_span,
            )
        company_match = COMPANY_LABEL_RE.match(line["text"])
        issuer_role_match = ISSUER_ROLE_LABEL_RE.match(line["text"])
        if company_match and company_match.group(1).strip() and (
            line_index in header_issuer_line_indices or issuer_role_match is not None
        ):
            value = company_match.group(1).strip()
            add_line("issuer_name", "explicit_company_label", value, line)
        if line_index in header_issuer_line_indices:
            for match in COMPANY_PHRASE_RE.finditer(line["text"]):
                value = match.group("name").strip().rstrip("，,；;。.")
                if value:
                    add_line("issuer_name", "explicit_legal_name_phrase", value, line)
        compact_line, line_offsets = _whitespace_compact_view(line["text"])
        code_match = CODE_LABEL_RE.search(compact_line)
        if code_match:
            raw_start, raw_end = _original_span_from_view(line["text"], line_offsets, code_match.span(1))
            match_start, match_end = _original_span_from_view(line["text"], line_offsets, code_match.span())
            raw_code = line["text"][raw_start:raw_end]
            code_value = re.sub(r"\s+", "", raw_code)
            add_line(
                "security_code",
                "explicit_security_code_label",
                code_value,
                line,
                match_span=(match_start, match_end),
            )
    for unit in source_unit_map.get("units", []):
        if any(
            record["kind"] == "security_code"
            and any(ref["source_unit_id"] == unit["source_unit_id"] for ref in record["source_refs"])
            for record in records
        ):
            continue
        compact_unit, unit_offsets = _whitespace_compact_view(unit["text"])
        code_match = CODE_LABEL_RE.search(compact_unit)
        if code_match:
            unit_line = {
                "text": unit["text"],
                "raw_text": unit["text"],
                "start_cp": unit["start_cp"],
                "end_cp": unit["end_cp"],
                "line_number": 0,
                "source_unit_id": unit["source_unit_id"],
            }
            raw_start, raw_end = _original_span_from_view(unit["text"], unit_offsets, code_match.span(1))
            match_start, match_end = _original_span_from_view(unit["text"], unit_offsets, code_match.span())
            code_value = re.sub(r"\s+", "", unit["text"][raw_start:raw_end])
            add_line(
                "security_code",
                "explicit_code_label_within_source_unit",
                code_value,
                unit_line,
                match_span=(match_start, match_end),
            )

    # Dates keep their source wording and receive a normalized ISO view only
    # when the calendar date itself is valid.
    for line in lines:
        dates = list(DATE_RE.finditer(line["text"]))
        if not dates:
            continue
        compact_line, _ = _whitespace_compact_view(line["text"])
        for match in dates:
            exact_date = match.group("date")
            normalized = _norm_date(exact_date)
            if re.search(r"呈交日期|提交日期|filingdate", compact_line, re.IGNORECASE):
                label = "filing_date"
            elif re.search(r"截至月份|截至本月底|asofmonth", compact_line, re.IGNORECASE):
                label = "reporting_cutoff_date"
            elif re.search(r"購回授權.*(?:決議|决议)|回購授權.*(?:決議|决议)|购回授权.*(?:决议|決議)|回购授权.*(?:决议|決議)", compact_line, re.IGNORECASE):
                label = "authorization_resolution_date"
            elif re.search(r"變動日期|变动日期|交易日|事件發生日期|事件发生日期|eventdate|tradingdate", compact_line, re.IGNORECASE):
                label = "event_or_trading_date"
            elif re.search(r"會議|会议|meeting", compact_line, re.IGNORECASE):
                label = "meeting_date"
            elif re.search(r"暫止期|暫停期|暂停期|suspensionperiod", compact_line, re.IGNORECASE):
                label = "restriction_end_date"
            elif re.search(r"(?:截至|期末|期終|期终|報告期|报告期|fortheperiod)", compact_line, re.IGNORECASE):
                label = "reporting_period_or_balance_date"
            else:
                label = "date_mention"
            add_line("date", label, {"source_date": exact_date, "normalized_date": normalized}, line)

    for line in lines:
        compact_line, line_offsets = _whitespace_compact_view(line["text"])
        period_match = PERIOD_RE.search(compact_line)
        if period_match:
            phrase_start, phrase_end = _original_span_from_view(line["text"], line_offsets, period_match.span())
            date_start, date_end = _original_span_from_view(line["text"], line_offsets, period_match.span("date"))
            term_start, term_end = _original_span_from_view(line["text"], line_offsets, period_match.span("term"))
            exact = line["text"][phrase_start:phrase_end]
            exact_date = line["text"][date_start:date_end]
            exact_term = line["text"][term_start:term_end]
            add_line("reporting_period", "explicit_period_end_phrase", {
                "source_phrase": exact,
                "end_date": exact_date,
                "normalized_end_date": _norm_date(exact_date),
                "period_term": exact_term,
            }, line, match_span=(phrase_start, phrase_end))

    # Explicit opening/closing balances are kept as source rows; the parser
    # does not assume a nearby amount is a different share-count denominator.
    for line in lines:
        if BALANCE_RE.match(line["text"]) and NUMBER_RE.search(line["text"]):
            date_match = DATE_RE.search(line["text"])
            amount_text = line["text"][date_match.end():] if date_match else line["text"]
            add_line("share_balance_row", "explicit_opening_or_closing_balance", {
                "source_row": line["text"].strip(),
                "numeric_tokens": [_number_token(m.group(0)) for m in NUMBER_RE.finditer(amount_text)],
            }, line, field="changes", scope="balance_at_labeled_date")
        if MOVEMENT_RE.match(line["text"]) and NUMBER_RE.search(line["text"]):
            add_line("share_movement_row", "explicit_labeled_increase_or_decrease", {
                "source_row": line["text"].strip(),
                "numeric_tokens": [_number_token(m.group(0)) for m in NUMBER_RE.finditer(line["text"])],
            }, line, field="changes", scope="source_labeled_movement_value")
        if SUMMARY_STATUS_RE.search(line["text"]) and NUMBER_RE.search(line["text"]):
            if re.search(r"擬持作庫存股份|拟持作库存股份", line["text"]):
                label, status = "reported_treasury_holding_count", "TREASURY_HOLDING"
            elif re.search(r"擬註銷|拟注销", line["text"]):
                label, status = "reported_planned_cancellation_count", "PLANNED_CANCELLATION"
            else:
                label, status = "reported_share_repurchase_total", "REPORTED_TOTAL"
            add_line("reported_transaction_status_count", label, {
                "source_row": line["text"].strip(),
                "numeric_tokens": [_number_token(m.group(0)) for m in NUMBER_RE.finditer(line["text"])],
                "status": status,
            }, line)

    # Transaction rows are recognized only from an explicit row label at the
    # start of a source line. Nearby date lines are separate evidence items.
    event_records: list[dict[str, Any]] = []
    paired_date_line_numbers: set[int] = set()
    for index, line in enumerate(lines):
        if not EVENT_ROW_RE.match(line["text"]):
            continue
        pending = bool(PENDING_RE.search(line["text"]))
        treasury = bool(TREASURY_RE.search(line["text"]))
        cancelled = bool(CANCELLED_RE.search(line["text"])) and not pending
        if not (pending or treasury or cancelled):
            continue
        status = "PENDING_CANCELLATION" if pending else "TREASURY_HOLDING" if treasury else "EXPLICITLY_CANCELLED" if cancelled else "CANNOT_CONFIRM"
        numeric_row = re.sub(r"^\s*(?:\d+\s*\)\.?\s*|[A-Z]\s*[.)、．]\s*)", "", line["text"])
        nums = [_number_token(match.group(0)) for match in NUMBER_RE.finditer(numeric_row)]
        nums = [value for value in nums if value is not None]
        percent_match = PERCENT_RE.search(line["text"])
        currency_match = re.search(r"(?:HKD|HK\$|RMB|CNY|USD|人民幣|人民币)\s*([-−]?\d[\d,]*(?:\.\d+)?)", line["text"], re.IGNORECASE)
        if not percent_match and not currency_match:
            continue
        row_value = {
            "source_row": line["text"].strip(),
            "share_quantity_token": nums[0] if nums else None,
            "reported_percentage_token": _number_token(percent_match.group(1)) if percent_match else None,
            "reported_price_token": _number_token(currency_match.group(1)) if currency_match else None,
            "currency": currency_match.group(0).split()[0] if currency_match else None,
            "status": status,
            "completion_status": "PENDING" if pending else "NOT_ESTABLISHED" if status == "CANNOT_CONFIRM" else "EXPLICIT_SOURCE_STATUS",
        }
        refs = [_ref_for_line(line, unit_by_id)]
        date_line = None
        for following in lines[index + 1:index + 5]:
            if re.search(r"(?:變動日期|变动日期|事件發生日期|事件发生日期|交易日)", following["text"], re.IGNORECASE):
                date_match = DATE_RE.search(following["text"])
                if date_match:
                    date_line = following
                break
            if EVENT_ROW_RE.match(following["text"]):
                break
        if date_line:
            row_value["event_date"] = DATE_RE.search(date_line["text"]).group("date")
            row_value["normalized_event_date"] = _norm_date(row_value["event_date"])
            refs.append(_ref_for_line(date_line, unit_by_id))
            paired_date_line_numbers.add(date_line["line_number"])
            add_reader("changes", date_line)
        else:
            row_value["event_date"] = None
            row_value["normalized_event_date"] = None
        record = add_record(
            "share_transaction_row",
            "explicit_share_repurchase_or_redemption_row",
            row_value,
            refs,
            scope="pending_cancellation_row" if pending else "treasury_or_other_explicit_transaction_row" if treasury or cancelled else "share_transaction_status_unconfirmed",
            status="VERIFIED_FROM_SOURCE" if status != "CANNOT_CONFIRM" else "CANNOT_CONFIRM",
        )
        event_records.append(record)
        add_reader("changes", line)

    in_pending_cancellation_section = False
    for line in lines:
        if re.search(r"^\s*B\.", line["text"]) and re.search(r"(?:擬註銷|拟注销|待註銷|待注销)", line["text"]):
            in_pending_cancellation_section = True
            continue
        if in_pending_cancellation_section and re.search(r"^\s*(?:B\.|C\.|第二章節|第二章节|購回報告|回購報告|购回报告|回购报告)", line["text"]):
            in_pending_cancellation_section = False
        if (
            in_pending_cancellation_section
            and line["line_number"] not in paired_date_line_numbers
            and re.search(r"(?:變動日期|变动日期)", line["text"])
        ):
            date_match = DATE_RE.search(line["text"])
            if date_match:
                add_record(
                    "share_transaction_date_without_values",
                    "dated_pending_cancellation_row_values_unresolved",
                    {
                        "date": date_match.group("date"),
                        "normalized_date": _norm_date(date_match.group("date")),
                        "share_quantity": None,
                        "percentage": None,
                        "price": None,
                        "transaction_status": "CANNOT_CONFIRM",
                    },
                    [_ref_for_line(line, unit_by_id)],
                    scope="explicit_date_only_missing_transaction_values",
                    status="CANNOT_CONFIRM",
                )
                add_reader("facts", line)
                unknowns.append({
                    "field": "share_transaction_values_for_dated_row",
                    "status": "CANNOT_CONFIRM",
                    "reason": "SOURCE_HAS_DATE_WITHOUT_A_RESOLVED_TRANSACTION_VALUE_ROW",
                    "source_unit_id": line["source_unit_id"],
                })

    # Parse daily repurchase summaries strictly under their own header. The
    # maximum and minimum prices retain their distinct column order.
    daily_rows: list[dict[str, Any]] = []
    for index, header in enumerate(lines):
        if not DAILY_HEADER_RE.search(header["text"]):
            continue
        for row in lines[index + 1:]:
            if re.search(r"^\s*(?:B\.|第二章節|第二章节|備註：|备注：)", row["text"], re.IGNORECASE):
                break
            date_match = DATE_RE.search(row["text"])
            if not date_match:
                continue
            after_date = row["text"][date_match.end():]
            values = [_number_token(m.group(0)) for m in NUMBER_RE.finditer(after_date)]
            values = [value for value in values if value is not None]
            row_value = {
                "trading_date": date_match.group("date"),
                "normalized_trading_date": _norm_date(date_match.group("date")),
                "share_quantity": values[0] if len(values) == 4 else None,
                "maximum_or_single_price": values[1] if len(values) == 4 else None,
                "minimum_price": values[2] if len(values) == 4 else None,
                "total_amount": values[3] if len(values) == 4 else None,
                "currency_tokens": re.findall(r"HKD|HK\$|RMB|CNY|USD", after_date, re.IGNORECASE),
                "source_row": row["text"].strip(),
                "parse_status": "VERIFIED_COLUMNS_BY_EXPLICIT_HEADER" if len(values) == 4 else "CANNOT_CONFIRM_COLUMN_RELATION",
            }
            record = add_record("daily_trade_summary_row", "explicit_daily_trade_summary_columns", row_value, [_ref_for_line(row, unit_by_id)], scope="daily_trade", status=row_value["parse_status"])
            daily_rows.append(record)
            add_reader("facts", row)

    # Capture explicit labeled authorization fields separately. A mandate cap
    # is never used as an issued-share denominator.
    authorization_date: tuple[str, dict[str, Any]] | None = None
    authorization_numerator: tuple[str, dict[str, Any]] | None = None
    authorization_reported_percent: tuple[str, dict[str, Any]] | None = None
    formula_line: dict[str, Any] | None = None
    for line in lines:
        text = line["text"]
        date_match = DATE_RE.search(text)
        if AUTH_DATE_RE.search(text) and date_match:
            authorization_date = (date_match.group("date"), line)
            add_line("authorization_resolution_date", "explicit_mandate_resolution_date", {
                "source_date": date_match.group("date"),
                "normalized_date": _norm_date(date_match.group("date")),
            }, line)
        if AUTH_TOTAL_RE.search(text):
            value = _last_number(text)
            if value is not None:
                add_line("authorization_share_cap", "explicit_mandate_total_cap", value, line, scope="authorization_cap_not_share_denominator")
        if AUTH_CUMULATIVE_RE.search(text) and re.search(r"(?:購回|回購|购回|回购).*(?:數目|数目|股數|股份數|shares)", text, re.IGNORECASE) and not AUTH_TOTAL_RE.search(text):
            value = _last_number(text)
            if value is not None:
                authorization_numerator = (value, line)
                add_line("cumulative_authorized_repurchase_count", "explicit_cumulative_mandate_count", value, line, scope="cumulative_under_authorization")
        if AUTH_PERCENT_RE.search(text):
            match = PERCENT_RE.search(text)
            if match:
                authorization_reported_percent = (_number_token(match.group(1)), line)
                add_line("reported_authorization_percentage", "explicit_cumulative_authorization_percentage", {
                    "reported_value": _number_token(match.group(1)),
                    "unit": "%",
                }, line, scope="cumulative_under_authorization")
        if FORMULA_RE.search(text) and re.search(r"已發行股份|已发行股份|issued\s+shares", text, re.IGNORECASE):
            formula_line = line

    # A resolution-date issued-share count is accepted only if one explicit
    # note binds it to the mandate-resolution date and issued-share label.
    denominator_candidates: list[tuple[str, dict[str, Any], str]] = []
    for unit in source_unit_map.get("units", []):
        compact = re.sub(r"\s+", "", unit["text"])
        if not AUTH_DENOM_NOTE_RE.search(compact):
            continue
        match = re.search(
            r"(?:已發行股份總數|已发行股份总数|totalissuedshares)(?:\(不包括庫存股份\)|（不包括庫存股份）|\(不包括库存股份\)|（不包括库存股份）)?(?:為|爲|为|是|:|：)?([0-9][0-9,]*)",
            compact,
            re.IGNORECASE,
        )
        if match:
            denominator_candidates.append((_number_token(match.group(1)) or "", unit, compact))
    denominator_record: dict[str, Any] | None = None
    if len(denominator_candidates) == 1:
        denominator_value, denominator_unit, denominator_context = denominator_candidates[0]
        denominator_record = add_record(
            "issued_share_denominator",
            "issued_shares_on_mandate_resolution_date",
            {"share_count": denominator_value, "share_basis": "issued shares as explicitly labeled in resolution-date note"},
            [{
                "source_unit_id": denominator_unit["source_unit_id"],
                "source_unit_sha256": denominator_unit["unit_sha256"],
                "unit_start_cp": denominator_unit["start_cp"],
                "unit_end_cp": denominator_unit["end_cp"],
                "unit_context_sha256": _sha(denominator_context.encode("utf-8")),
            }],
            scope="issued_shares_at_authorization_resolution_date",
        )
        # Keep the exact note as a separate fact citation; do not paraphrase it.
        unit_line = next((
            item for item in lines
            if item["source_unit_id"] == denominator_unit["source_unit_id"]
            and ("已發行股份總數" in item["text"] or "已发行股份总数" in item["text"])
        ), None)
        if unit_line:
            add_reader("facts", unit_line)
    elif len(denominator_candidates) > 1:
        unknowns.append({"field": "authorization_share_denominator", "status": "CANNOT_CONFIRM", "reason": "MULTIPLE_EXPLICIT_DENOMINATOR_NOTES"})

    calculation: dict[str, Any]
    if authorization_date and authorization_numerator and authorization_reported_percent and formula_line and denominator_record:
        numerator_value = authorization_numerator[0]
        denominator_value = denominator_record["value"]["share_count"]
        reported_value = authorization_reported_percent[0]
        try:
            raw_percent = Decimal(numerator_value) * Decimal("100") / Decimal(denominator_value)
            precision = len(reported_value.split(".", 1)[1]) if "." in reported_value else 0
            quantum = Decimal("1").scaleb(-precision)
            rounded_percent = raw_percent.quantize(quantum, rounding=ROUND_HALF_UP)
            reported_decimal = Decimal(reported_value)
            matches = rounded_percent == reported_decimal
            calculation = {
                "kind": "explicit_cumulative_authorization_ratio",
                "status": "VERIFIED_AT_REPORTED_PRECISION" if matches else "SOURCE_RATIO_MISMATCH",
                "numerator": numerator_value,
                "denominator": denominator_value,
                "denominator_basis": "issued shares excluding treasury on authorization-resolution date only if exact source label says so",
                "authorization_resolution_date": authorization_date[0],
                "formula": "numerator * 100 / denominator",
                "calculated_percentage_unrounded": str(raw_percent),
                "calculated_percentage_at_reported_precision": str(rounded_percent),
                "reported_percentage": reported_value,
                "source_refs": [
                    _ref_for_line(authorization_numerator[1], unit_by_id),
                    _ref_for_line(authorization_reported_percent[1], unit_by_id),
                    _ref_for_line(authorization_date[1], unit_by_id),
                    _ref_for_line(formula_line, unit_by_id),
                    *denominator_record["source_refs"],
                ],
            }
        except (InvalidOperation, ZeroDivisionError):
            calculation = {"kind": "explicit_cumulative_authorization_ratio", "status": "CANNOT_CONFIRM", "reason": "DECIMAL_CALCULATION_INVALID"}
    else:
        missing = []
        for name, value in (
            ("formula", formula_line),
            ("numerator", authorization_numerator),
            ("reported_percentage", authorization_reported_percent),
            ("authorization_resolution_date", authorization_date),
            ("resolution_date_issued_share_denominator", denominator_record),
        ):
            if value is None:
                missing.append(name)
        calculation = {
            "kind": "explicit_cumulative_authorization_ratio",
            "status": "CANNOT_CONFIRM",
            "missing_or_unbound_inputs": missing,
        }
    has_authorization_ratio_fields = any((authorization_date, authorization_numerator, authorization_reported_percent))
    calculations = [calculation] if has_authorization_ratio_fields else []
    if calculation["status"] == "CANNOT_CONFIRM" and has_authorization_ratio_fields:
        unknowns.append({"field": "authorization_ratio_calculation", "status": "CANNOT_CONFIRM", "reason": "EXPLICIT_FORMULA_NUMERATOR_DATE_AND_DENOMINATOR_NOT_ALL_BOUND"})

    # Current daily change percentages can be recomputed only for a single
    # explicitly labeled row with an explicit opening balance and source note
    # tying the percentage to the report's beginning balance.
    beginning_lines = [line for line in lines if BALANCE_RE.match(line["text"]) and re.search(r"(?:上月底結存|上月底结存|期初|開始時|开始时|opening)", line["text"], re.IGNORECASE) and NUMBER_RE.search(line["text"])]
    percentage_basis_explicit = any(
        re.search(r"(?:期初結存|期初结存|期初結餘|期初结余|beginning\s+balance)", line["text"], re.IGNORECASE)
        and re.search(r"(?:百分比|比例).{0,80}(?:期初|開始時|开始时|beginning)", line["text"], re.IGNORECASE)
        for line in lines
    )
    row_ratio_calculation = {"kind": "current_change_percentage", "status": "CANNOT_CONFIRM", "reason": "OPENING_DENOMINATOR_OR_UNIQUE_ROW_NOT_EXPLICIT"}
    has_current_reported_percent = any(record["value"].get("reported_percentage_token") is not None for record in event_records)
    if has_current_reported_percent and len(event_records) == 1 and len(beginning_lines) == 1 and percentage_basis_explicit:
        event = event_records[0]
        qty = event["value"].get("share_quantity_token")
        percent = event["value"].get("reported_percentage_token")
        opening_line = beginning_lines[0]
        opening_line_index = next(index for index, candidate in enumerate(lines) if candidate is opening_line)
        prior_context = re.sub(
            r"\s+", "", " ".join(candidate["text"] for candidate in lines[max(0, opening_line_index - 8):opening_line_index])
        )
        date_match = DATE_RE.search(opening_line["text"])
        amount_text = opening_line["text"][date_match.end():] if date_match else opening_line["text"]
        opening_nums = [_number_token(match.group(0)) for match in NUMBER_RE.finditer(amount_text)]
        opening_nums = [value for value in opening_nums if value is not None]
        has_issued_column = "已發行股份（不包括庫存股份）變動" in prior_context or "已發行股份（不包括庫存股份）數" in prior_context
        has_treasury_column = "庫存股份數目" in prior_context
        has_total_column = "已發行股份總數" in prior_context
        if not (has_issued_column and has_treasury_column and has_total_column):
            opening_nums = []
        if qty and percent and opening_nums:
            try:
                raw_percent = abs(Decimal(qty)) * Decimal("100") / Decimal(opening_nums[0])
                precision = len(percent.split(".", 1)[1]) if "." in percent else 0
                rounded = raw_percent.quantize(Decimal("1").scaleb(-precision), rounding=ROUND_HALF_UP)
                reported = Decimal(percent)
                row_ratio_calculation = {
                    "kind": "current_change_percentage",
                    "status": "VERIFIED_AT_REPORTED_PRECISION" if rounded == reported else "SOURCE_RATIO_MISMATCH",
                    "share_quantity": qty,
                    "opening_denominator": opening_nums[0],
                    "denominator_date": date_match.group("date") if date_match else None,
                    "reported_percentage": percent,
                    "calculated_percentage_unrounded": str(raw_percent),
                    "calculated_percentage_at_reported_precision": str(rounded),
                    "source_refs": [event["source_refs"][0], _ref_for_line(opening_line, unit_by_id)],
                }
            except (InvalidOperation, ZeroDivisionError):
                pass
    if has_current_reported_percent:
        calculations.append(row_ratio_calculation)
    if has_current_reported_percent and row_ratio_calculation["status"] == "CANNOT_CONFIRM":
        unknowns.append({"field": "current_change_percentage_calculation", "status": "CANNOT_CONFIRM", "reason": row_ratio_calculation["reason"]})

    # Preserve daily-trade header semantics and never merge them with
    # cumulative authorization rows or per-day change rows.
    for line in lines:
        if REFERENCE_ONLY_RE.search(line["text"]):
            add_line("reference_only_notice", "explicit_reference_only_language", {
                "source_text": line["text"].strip(),
                "underlying_transaction_status": "CANNOT_CONFIRM",
            }, line, scope="reference_only_does_not_establish_underlying_event")
            unknowns.append({"field": "underlying_event_from_reference_only_notice", "status": "CANNOT_CONFIRM", "reason": "REFERENCE_ONLY_TEXT_DOES_NOT_ESTABLISH_EVENT_COMPLETION"})

    issuer_records = [record for record in records if record["kind"] == "issuer_name"]
    code_records = [record for record in records if record["kind"] == "security_code"]
    period_records = [record for record in records if record["kind"] == "reporting_period"]
    if not issuer_records:
        unknowns.append({"field": "issuer_identity", "status": "CANNOT_CONFIRM", "reason": "NO_EXACT_BODY_NAME_OR_EXPLICIT_COMPANY_LABEL_FOUND"})
    if not code_records:
        unknowns.append({"field": "security_code", "status": "CANNOT_CONFIRM", "reason": "NO_EXPLICIT_BODY_CODE_LABEL_FOUND"})
    if not period_records and not any(record["label"] == "reporting_cutoff_date" for record in records):
        unknowns.append({"field": "reporting_period_or_cutoff", "status": "CANNOT_CONFIRM", "reason": "NO_EXPLICIT_PERIOD_OR_CUTOFF_LABEL_FOUND"})

    ledger = {
        "protocol": PROTOCOL,
        "body_sha256": body_sha,
        "source_unit_map_sha256": source_unit_map["source_unit_map_sha256"],
        "source_unit_count": len(source_unit_map["units"]),
        "source_unit_ids": [unit["source_unit_id"] for unit in source_unit_map["units"]],
        "records": records,
        "daily_trade_rows": daily_rows,
        "calculations": calculations,
        "unknowns": unknowns,
        "reader_facts": facts,
        "reader_changes": changes,
        "coverage": {
            "explicit_issuer_name": bool(issuer_records),
            "explicit_security_code": bool(code_records),
            "explicit_reporting_period_or_cutoff": bool(period_records or any(record["label"] == "reporting_cutoff_date" for record in records)),
            "explicit_transaction_rows": len(event_records),
            "daily_trade_rows": len(daily_rows),
            "source_unit_map_verified": True,
            "full_body_read_required_for_model": True,
        },
    }
    ledger["ledger_sha256"] = _canonical_sha({key: value for key, value in ledger.items() if key != "ledger_sha256"})
    return ledger
