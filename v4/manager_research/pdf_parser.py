"""Pinned, page-aware PDF parsing for official manager research sources.

The live host does not install a PDF dependency.  This module loads the
private BSD-licensed pypdf 6.10.0 closure shipped beside it and keeps the
parser boundary explicit: page text is evidence, while a fact is promoted
only when a generic field or narrative rule can retain its period, units and
original short excerpt.
"""

from __future__ import annotations

from io import BytesIO
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
import math
from .errors import public_error
from typing import Any, Iterable, Mapping


PINNED_PYPDF_VERSION = "6.10.0"
_PACKAGE_DIR = Path(__file__).resolve().parent
_VENDOR_DIR = _PACKAGE_DIR / "_vendor"
_VENDOR_PACKAGE_DIR = _VENDOR_DIR / "pypdf"
_DEPENDENCY_MANIFEST = _PACKAGE_DIR / "DEPENDENCY_MANIFEST.json"
_PYPDF_MODULE_NAME = "pypdf"
_PDF_READER: Any | None = None
_DEPENDENCY_CHECKED = False


class PdfParseError(RuntimeError):
    """The pinned parser could not read a document safely."""


def _tree_hash(root: Path) -> str:
    from hashlib import sha256

    digest = sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _check_private_dependency() -> None:
    global _DEPENDENCY_CHECKED
    if _DEPENDENCY_CHECKED:
        return
    try:
        manifest = json.loads(_DEPENDENCY_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PdfParseError("private pypdf dependency manifest is unreadable") from exc
    if (
        manifest.get("name") != "pypdf"
        or manifest.get("version") != PINNED_PYPDF_VERSION
        or manifest.get("vendor_path") != "_vendor/pypdf"
        or manifest.get("license") != "BSD-3-Clause"
    ):
        raise PdfParseError("private pypdf dependency manifest is not pinned to 6.10.0/BSD-3-Clause")
    if not _VENDOR_PACKAGE_DIR.is_dir() or _tree_hash(_VENDOR_PACKAGE_DIR) != manifest.get("package_tree_sha256"):
        raise PdfParseError("private pypdf package tree SHA-256 does not match its manifest")
    license_path = _VENDOR_DIR / "licenses" / "pypdf-6.10.0-LICENSE"
    if not license_path.is_file():
        raise PdfParseError("private pypdf LICENSE is missing")
    from hashlib import sha256

    license_digest = sha256(license_path.read_bytes()).hexdigest()
    if license_digest != manifest.get("license_sha256"):
        raise PdfParseError("private pypdf LICENSE SHA-256 does not match its manifest")
    _DEPENDENCY_CHECKED = True


def _load_pdf_reader() -> Any:
    """Load only the vendored pypdf package, never a host/global install."""

    global _PDF_READER
    if _PDF_READER is not None:
        return _PDF_READER
    _check_private_dependency()
    loaded = sys.modules.get(_PYPDF_MODULE_NAME)
    expected_init = (_VENDOR_PACKAGE_DIR / "__init__.py").resolve()
    if loaded is None:
        spec = importlib.util.spec_from_file_location(
            _PYPDF_MODULE_NAME,
            expected_init,
            submodule_search_locations=[str(_VENDOR_PACKAGE_DIR)],
        )
        if spec is None or spec.loader is None:
            raise PdfParseError("cannot load private pypdf package")
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[_PYPDF_MODULE_NAME] = loaded
        try:
            spec.loader.exec_module(loaded)
        except BaseException:
            sys.modules.pop(_PYPDF_MODULE_NAME, None)
            raise
    loaded_path = getattr(loaded, "__file__", None)
    if not isinstance(loaded_path, str) or Path(loaded_path).resolve() != expected_init:
        raise PdfParseError("an external pypdf module is already loaded")
    if getattr(loaded, "__version__", None) != PINNED_PYPDF_VERSION:
        raise PdfParseError("loaded pypdf version is not 6.10.0")
    reader = getattr(loaded, "PdfReader", None)
    if reader is None:
        raise PdfParseError("private pypdf has no PdfReader")
    _PDF_READER = reader
    return reader


def _normal_line(value: str) -> str:
    return re.sub(r"[ \t\f\v]+", " ", value.replace("\xa0", " ")).strip()


def _normal_page_text(value: str) -> str:
    return "\n".join(line for line in (_normal_line(item) for item in value.replace("\r", "").split("\n")) if line)


def extract_pdf_pages(body: bytes, *, max_bytes: int = 32 * 1024 * 1024,
                      max_pages: int = 500, max_text_characters: int = 8_000_000,
                      timeout_seconds: float = 30.0) -> list[dict[str, Any]]:
    """Bound page/text work; exceedance rejects the whole extraction.

    Deadline checks are cooperative between parser calls, not a claim that an
    in-process third-party parser can be forcibly interrupted. Existing page
    failures still yield no facts for that page, never synthetic evidence.
    """
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in (max_bytes, max_pages, max_text_characters)):
        raise PdfParseError("PDF_BUDGET_INVALID")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise PdfParseError("PDF_BUDGET_INVALID")
    if len(body) > max_bytes:
        raise PdfParseError("PDF_BYTE_BUDGET_EXCEEDED")
    if not body.startswith(b"%PDF"):
        return []
    deadline = time.monotonic() + timeout_seconds
    try:
        reader = _load_pdf_reader()(BytesIO(body), strict=False)
    except Exception as exc:
        raise PdfParseError(public_error(exc)) from exc
    if len(reader.pages) > max_pages:
        raise PdfParseError("PDF_PAGE_BUDGET_EXCEEDED")
    pages: list[dict[str, Any]] = []
    total = 0
    for page_number, page in enumerate(reader.pages, start=1):
        if time.monotonic() >= deadline:
            raise PdfParseError("PDF_TIME_BUDGET_EXCEEDED")
        try:
            text = _normal_page_text(page.extract_text() or "")
        except Exception:
            text = ""
        total += len(text)
        if total > max_text_characters:
            raise PdfParseError("PDF_TEXT_BUDGET_EXCEEDED")
        if text:
            pages.append({"page": page_number, "text": text})
    if time.monotonic() >= deadline:
        raise PdfParseError("PDF_TIME_BUDGET_EXCEEDED")
    return pages


def extract_pdf_text(body: bytes) -> tuple[str, list[str]]:
    """Compatibility helper returning page text and real page locators."""

    pages = extract_pdf_pages(body)
    return "\n".join(str(page["text"]) for page in pages), [f"PDF page {page['page']}" for page in pages]


# HKEX text extraction uses several Unicode dash characters for negative
# amounts.  Treat the sign as part of the numeric token while retaining a
# standalone em/en dash as a missing-value marker.
_NUMBER = r"(?:\([0-9][0-9,]*(?:\.\d+)?%?\)|[-−‐‑‒–—]?[0-9][0-9,]*(?:\.\d+)?|—|–|N/A)%?"
_FINANCIAL_ROW_RE = re.compile(
    rf"^(?P<label>[A-Za-z][A-Za-z0-9 &'(),./\-–—]+?)\s+(?P<values>{_NUMBER}(?:\s+{_NUMBER}){{1,5}})$"
)
_UNIT_RE = re.compile(
    r"\((?P<currency>[A-Z]{2,5})\s+in\s+(?P<unit>[A-Za-z ]+?)(?:,\s*except for\s+(?P<except>[^)]+))?\)",
    re.IGNORECASE,
)
_UNIT_OPEN_RE = re.compile(r"\((?P<currency>[A-Z]{2,5})\s+in\s*$", re.IGNORECASE)
_UNIT_HEADER_RE = re.compile(
    r"\bUnit\s*:\s*(?P<unit>[A-Za-z]+)\s+Currency\s*:\s*(?P<currency>[A-Z]{2,5}|S\$)\b",
    re.IGNORECASE,
)
_TRAILING_CURRENCY_RE = re.compile(r"\((?P<currency>RMB|CNY|HKD|USD|S\$)\)", re.IGNORECASE)
_SYMBOL_THOUSANDS_RE = re.compile(r"(?<![A-Za-z])(?P<currency>S\$)\s*[’']?000\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_CHANGE_RE = re.compile(r"\bchange(?:\s*(?:\(%\)|%))?(?=\s|\d|$)", re.IGNORECASE)
_NOTE_MARKER_RE = re.compile(r"^\d+(?:\([a-z]\))?$", re.IGNORECASE)
_DISCLAIMER_TOKENS = (
    "no responsibility",
    "no r esponsibility",
    "expressly disclaim",
    "expr essly disclaim",
    "not verified",
)
_CURRENCY_CN = {
    "RMB": "人民币",
    "HKD": "港元",
    "USD": "美元",
    "CNY": "人民币",
    "S$": "新加坡元",
}
_MONTH_NUMBER = {
    "january": "1",
    "february": "2",
    "march": "3",
    "april": "4",
    "may": "5",
    "june": "6",
    "july": "7",
    "august": "8",
    "september": "9",
    "october": "10",
    "november": "11",
    "december": "12",
}
_MONTH_PATTERN = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
_UNIT_CN = {
    "thousands": "千",
    "thousand": "千",
    "millions": "百万",
    "million": "百万",
    "percentages": "百分比",
    "yuan": "元",
}
_METRIC_CN = {
    "revenue": "收入",
    "total revenues": "总收入",
    "revenue from contracts with customers": "客户合同收入",
    "total revenue from contracts with customers": "客户合同总收入",
    "cost of sales and services": "销售及服务成本",
    "cost of sales": "销售成本",
    "cost of revenue": "收入成本",
    "cost of revenues": "收入成本",
    "gross profit": "毛利",
    "loss for the period": "期内亏损",
    "profit for the period": "期内利润",
    "loss for the year": "年度亏损",
    "profit for the year": "年度利润",
    "operating profit (loss)": "经营利润（亏损）",
    "operating loss": "经营亏损",
    "operating profit": "经营利润",
    "operating income": "经营收入",
    "operating revenue": "经营收入",
    "adjusted operating (loss)/profit": "经调整经营（亏损）/利润",
    "total operating expenses": "经营费用总额",
    "cash generated from/(used in) operations": "经营活动产生／（使用）的现金",
    "net cash generated from/(used in) operating activities": "经营活动产生／（使用）的现金净额",
    "net cash used in operating activities": "经营活动使用的现金净额",
    "net cash generated from investing activities": "投资活动产生的现金净额",
    "net cash (used in)/generated from investing activities": "投资活动（使用）／产生的现金净额",
    "net cash generated from financing activities": "融资活动产生的现金净额",
    "net increase/(decrease) in cash and cash equivalents": "现金及现金等价物净增加／（减少）",
    "cash and cash equivalents": "现金及现金等价物",
    "cash and bank balances": "现金及银行结余",
    "bank balances and cash": "银行结余及现金",
    "cash and cash equivalents at the beginning of the year": "年初现金及现金等价物",
    "cash and cash equivalents at the end of the year": "年末现金及现金等价物",
    "cash and cash equivalents at the beginning of the period": "期初现金及现金等价物",
    "cash and cash equivalents at the end of the period": "期末现金及现金等价物",
    "net finance costs": "融资成本净额",
    "finance costs": "融资成本",
    "financial liabilities at fair value through profit or loss": "按公允价值计入损益的金融负债",
    "measured at fair value through profit or loss": "按公允价值计入损益的项目",
    "adjusted net loss (non-ifrs measure)": "经调整期内亏损（非国际财务报告准则）",
    "adjusted net loss for the period (non-ifrs measure)": "经调整期内亏损（非国际财务报告准则）",
    "adjusted net loss for the period (non-ifrs financial measure)": "经调整期内亏损（非国际财务报告准则）",
    "adjusted net loss for the year (a non-ifrs measure)": "经调整年度亏损（非国际财务报告准则）",
    "total comprehensive loss for the period": "期内全面亏损总额",
    "income tax expenses": "所得税费用",
    "administrative expenses": "行政费用",
    "general and administrative expenses": "一般及行政费用",
    "other net income or loss": "其他净收入或亏损",
    "net impairment loss on financial assets": "金融资产减值亏损净额",
    "expenses": "费用",
    "liabilities": "负债",
    "other receivables": "其他应收款",
    "restricted cash": "受限制现金",
    "equipment, intangible assets": "设备及无形资产",
    "contract assets, net": "合约资产净额",
    "payment expenses": "付款费用",
    "current assets": "流动资产",
    "current liabilities": "流动负债",
    "depreciation": "折旧",
    "investment income": "投资收入",
    "gross profit 3(b)": "毛利3(b)",
    "net profit": "净利润",
    "operating profit": "经营利润",
    "profit": "利润",
    "loss": "亏损",
}
_MAX_DOCUMENT_FACTS = 24
_NON_OPERATING_LABEL_TOKENS = (
    "share capital",
    "registered capital",
    "issued shares",
    "ordinary shares",
    "treasury shares",
    "number of shares",
    "articles of association",
    "directors",
)
_FINANCIAL_LABEL_TOKENS = (
    "revenue",
    "sales",
    "cost",
    "gross",
    "profit",
    "loss",
    "income",
    "expense",
    "cash",
    "asset",
    "liabilit",
    "inventory",
    "inventories",
    "receivable",
    "payable",
    "borrowing",
    "depreciation",
    "tax",
    "earnings",
    "margin",
    "equity",
)

_FOOTNOTE_LABEL_SUFFIX_RE = re.compile(r"\s+\d+\s*\([a-z]\)\s*$", re.IGNORECASE)


def _clean_metric_label(label: str) -> str:
    """Remove a trailing table footnote marker from a financial label.

    PDF text extraction often joins markers such as ``Gross profit 7(b)`` to
    the row label.  The marker remains in the raw page excerpt, while the
    structured label is normalized so it cannot become a fake metric name in
    the Chinese card summary.
    """

    clean = _normal_line(label).rstrip(":")
    return _FOOTNOTE_LABEL_SUFFIX_RE.sub("", clean).strip()


def _metric_cn(label: str) -> str:
    clean = _clean_metric_label(label)
    exact = _METRIC_CN.get(clean.lower())
    if exact:
        return exact
    # Keep an unfamiliar official label traceable while translating common
    # accounting words. This does not infer a company-specific meaning.
    translated = clean
    replacements = (
        (r"\btotal\b", "总"),
        (r"\brevenues?\b", "收入"),
        (r"\bcosts?\b", "成本"),
        (r"\bprofit\b", "利润"),
        (r"\bloss\b", "亏损"),
        (r"\bexpenses?\b", "费用"),
        (r"\bincome\b", "收入"),
        (r"\bcash\b", "现金"),
        (r"\bassets?\b", "资产"),
        (r"\bliabilities\b", "负债"),
        (r"\boperating\b", "经营"),
        (r"\badjusted\b", "经调整"),
        (r"\bused in\b", "使用"),
        (r"\bgenerated from\b", "产生"),
        (r"\bfrom\b", "来自"),
        (r"\band\b", "及"),
        (r"\badministrative\b", "行政"),
        (r"\bnet\b", "净额"),
    )
    for source, target in replacements:
        translated = re.sub(source, target, translated, flags=re.IGNORECASE)
    translated = re.sub(r"\s+", " ", translated).strip()
    translated = translated.replace("经营 收入", "经营收入")
    if translated == clean:
        return f"财务项目「{clean}」"
    return f"财务项目「{translated}」"


def _date_fragment_cn(value: str) -> str:
    """Translate a source date fragment without changing the raw field."""

    clean = _normal_line(value).strip(" ,;–—-")
    match = re.fullmatch(rf"(?P<day>[0-3]?\d)\s+(?P<month>{_MONTH_PATTERN})(?:\s+(?P<year>\d{{4}}))?", clean, flags=re.IGNORECASE)
    if match:
        month = _MONTH_NUMBER.get(match.group("month").lower(), match.group("month"))
        day = int(match.group("day"))
        year = match.group("year")
        return f"{year + '年' if year else ''}{month}月{day}日"
    match = re.fullmatch(rf"(?P<month>{_MONTH_PATTERN})\s+(?P<day>[0-3]?\d),?(?:\s+(?P<year>\d{{4}}))?", clean, flags=re.IGNORECASE)
    if match:
        month = _MONTH_NUMBER.get(match.group("month").lower(), match.group("month"))
        day = int(match.group("day"))
        year = match.group("year")
        return f"{year + '年' if year else ''}{month}月{day}日"
    return clean


def _period_cn(period: str, columns: list[str]) -> str:
    clean = _normal_line(period)
    clean = re.sub(r"\s*[–—-]?\s*unaudited\b", "", clean, flags=re.IGNORECASE)
    # Strip table prose before translating the period marker. The raw period
    # remains untouched in fields.period_label and source_excerpt.
    marker = re.search(
        r"\b(?:for\s+)?(?:the\s+)?(?:six|three)\s+months\s+ended\b|"
        r"\b(?:for\s+)?(?:the\s+)?year\s+ended\b",
        clean,
        flags=re.IGNORECASE,
    )
    if marker is None:
        return f"公告财务表期间（列：{'、'.join(columns)}）" if columns else "公告财务表期间"
    tail = clean[marker.end():]
    date_re = re.compile(
        rf"\b(?:[0-3]?\d\s+{_MONTH_PATTERN}(?:\s+\d{{4}})?|{_MONTH_PATTERN}\s+[0-3]?\d,?(?:\s+\d{{4}})?)\b",
        re.IGNORECASE,
    )
    dates = [_date_fragment_cn(match.group(0)) for match in date_re.finditer(tail)]
    marker_text = marker.group(0).lower()
    if "year" in marker_text:
        prefix = "截至年度"
    elif "three" in marker_text:
        prefix = "截至三个月"
    else:
        prefix = "截至六个月"
    translated = f"{prefix}{(' ' + dates[0]) if dates else ''}"
    if re.search(r"\bcompared\s+to\b", tail, flags=re.IGNORECASE) and len(dates) > 1:
        translated += f"，对比{dates[1]}"
    return f"{translated}（列：{'、'.join(columns)}）" if columns else translated


def _safe_excerpt(lines: Iterable[str], *, limit: int = 800) -> str | None:
    text = _normal_line(" ".join(line for line in lines if line))
    if not text:
        return None
    if len(text) <= limit:
        return text
    # Do not cut a fact in the middle of a token or sentence.  A page locator
    # without a complete excerpt is less useful than CANNOT_CONFIRM.
    sentence = re.split(r"(?<=[.!?。！？])\s+", text[: limit + 1])[0].strip()
    return sentence if len(sentence) >= 30 and len(sentence) <= limit else None


def _column_context(lines: list[str], unit_index: int, unit_line: str) -> tuple[str, list[str]]:
    """Recover explicit table columns around a unit header.

    HKEX PDFs expose the same table in several presentation layouts: numeric
    year headers, a compact ``change2026 2025`` line, or prose headers such as
    ``Reporting Period / Corresponding period of last year``.  We retain the
    source labels when numeric years are unavailable instead of inventing a
    period.
    """

    # A unit cell is often printed before the multi-line table header.  Keep
    # enough of the nearby table to retain the explicit period labels while
    # avoiding a whole-page scan that would mix unrelated years into the
    # columns.
    window_start = max(0, unit_index - 12)
    window_end = min(len(lines), unit_index + 16)
    window = lines[window_start:window_end]
    year_columns: list[str] = []
    year_line = ""
    for line in reversed(window):
        line_years = _YEAR_RE.findall(line)
        if len(line_years) >= 2:
            year_line = line
            year_columns = list(dict.fromkeys(line_years))
            break
    # Some source tables put the two years on separate header lines.  When no
    # single line carries both years, retain the first two explicit years in
    # this local table window.  This is bounded to the unit's neighbourhood so
    # later narrative dates cannot become financial columns.
    if len(year_columns) < 2:
        nearby_years: list[str] = []
        for line in window:
            for year in _YEAR_RE.findall(line):
                if year not in nearby_years:
                    nearby_years.append(year)
        if len(nearby_years) >= 2:
            year_columns = nearby_years[:5]
            year_line = " ".join(line for line in window if _YEAR_RE.search(line))

    joined_window = " ".join(window)
    has_change = bool(_CHANGE_RE.search(joined_window + " " + unit_line))
    comparison_label = ""
    if re.search(r"\bincrease\s*/\s*decrease\b|\bincrease\s+or\s+decrease\b", joined_window, re.IGNORECASE):
        comparison_label = _normal_line(
            next(
                (
                    line
                    for line in window
                    if re.search(r"\bincrease\s*/\s*decrease\b|\bincrease\s+or\s+decrease\b", line, re.IGNORECASE)
                ),
                "Increase/decrease",
            )
        )
    elif has_change:
        comparison_label = "Change (%)"
    if len(year_columns) >= 2:
        columns = year_columns[:5]
        if comparison_label and comparison_label not in columns:
            columns.append(comparison_label)
        return year_line, columns

    joined = " ".join(window).lower()
    if "same period" in joined and "yoy" in joined:
        return "The Reporting Period / Same Period of the Previous Year / YoY Change (%)", [
            "The Reporting Period",
            "Same Period of the Previous Year",
            "YoY Change (%)",
        ]
    if "reporting period" in joined and "corresponding" in joined:
        return "Reporting Period / Corresponding period of previous year / Change (%)", [
            "Reporting Period",
            "Corresponding period of previous year",
            "Change (%)",
        ]
    return " ".join(window), []


def _period_context(lines: list[str], unit_index: int, column_line: str) -> str:
    """Keep a nearby explicit reporting-period label for the fact fields."""

    window = lines[max(0, unit_index - 12) : min(len(lines), unit_index + 16)]
    joined = " ".join(window)
    compact_period = re.search(r"\bthe reporting period\s*\([^)]{1,40}\)", joined, re.IGNORECASE)
    if compact_period:
        return _normal_line(compact_period.group(0))
    for line in window:
        if re.search(r"\b(?:for\s+the\s+)?(?:six|three)\s+months\s+ended\b|\byear\s+ended\b", line, re.IGNORECASE):
            return line
    for line in window:
        if re.search(r"\breporting period\b|\bcorresponding period\b|\bsame period\b", line, re.IGNORECASE):
            return line
    return column_line


def _row_match(lines: list[str], row_index: int) -> tuple[re.Match[str] | None, int]:
    """Match a financial row, joining only preceding presentation wraps."""

    # Prefer a complete current-line label.  This prevents a prose header such
    # as ``Corresponding period of previous year`` from being joined to the
    # first financial row below it.
    current = _normal_line(_TRAILING_CURRENCY_RE.sub("", lines[row_index]))
    current_match = _FINANCIAL_ROW_RE.match(current)
    # A wrapped continuation often starts in lowercase (for example
    # ``non-recurring gains and losses``).  Join it to the preceding label
    # before accepting the shorter continuation as an independent metric.
    if current_match is not None and current_match.group("label")[:1].islower():
        earliest = max(0, row_index - 3)
        for start in range(earliest, row_index):
            if any(re.search(r"\d", lines[index]) for index in range(start, row_index)):
                continue
            joined = _normal_line(" ".join(lines[start : row_index + 1]))
            joined = _TRAILING_CURRENCY_RE.sub("", joined)
            joined_match = _FINANCIAL_ROW_RE.match(joined)
            if joined_match is not None and any(
                token in joined_match.group("label").lower() for token in _FINANCIAL_LABEL_TOKENS
            ):
                return joined_match, row_index - start + 1
    if current_match is not None and any(
        token in current_match.group("label").lower() for token in _FINANCIAL_LABEL_TOKENS
    ):
        return current_match, 1

    earliest = max(0, row_index - 3)
    for start in range(earliest, row_index + 1):
        # A numeric line before the candidate marks a different financial row;
        # do not join across it and accidentally merge two facts.
        if any(re.search(r"\d", lines[index]) for index in range(start, row_index)):
            continue
        joined = _normal_line(" ".join(lines[start : row_index + 1]))
        joined = _TRAILING_CURRENCY_RE.sub("", joined)
        match = _FINANCIAL_ROW_RE.match(joined)
        if match is not None:
            return match, row_index - start + 1
    return None, 1


def _financial_facts(page_number: int, text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    unit_contexts: list[tuple[int, str, str, str, str]] = []
    for index, line in enumerate(lines):
        unit_match = _UNIT_RE.search(line)
        if unit_match:
            unit_contexts.append(
                (
                    index,
                    unit_match.group("currency").upper(),
                    _normal_line(unit_match.group("unit")),
                    _normal_line(unit_match.group("except") or ""),
                    line,
                )
            )
        elif (header_match := _UNIT_HEADER_RE.search(line)):
            unit_contexts.append(
                (
                    index,
                    header_match.group("currency").upper(),
                    header_match.group("unit").lower(),
                    "",
                    line,
                )
            )
        elif index + 1 < len(lines) and _UNIT_OPEN_RE.search(line):
            # pypdf can expose a narrow table cell as ``(RMB in`` followed by
            # ``thousands)``.  Rejoin that presentation-only break while
            # retaining the original lines in the source excerpt.
            unit_open = _UNIT_OPEN_RE.search(line)
            unit_tail = _normal_line(lines[index + 1]).rstrip(")")
            if re.fullmatch(r"[A-Za-z ]+", unit_tail):
                unit_contexts.append(
                    (
                        index,
                        unit_open.group("currency").upper(),
                        unit_tail,
                        "",
                        f"{_normal_line(line)} {_normal_line(lines[index + 1])}",
                    )
                )
        elif (trailing_match := _TRAILING_CURRENCY_RE.search(line)):
            unit_contexts.append(
                (
                    index,
                    trailing_match.group("currency").upper(),
                    "yuan",
                    "",
                    line,
                )
            )
        elif re.search(r"\b[A-Z]{2,5}[’']?000\b", line):
            raw_currency = re.search(r"\b([A-Z]{2,5})[’']?000\b", line)
            if raw_currency:
                unit_contexts.append((index, raw_currency.group(1), "thousands", "", line))
        elif (symbol_match := _SYMBOL_THOUSANDS_RE.search(line)):
            unit_contexts.append((index, symbol_match.group("currency").upper(), "thousands", "", line))
    for unit_index, currency, unit, except_for, unit_line in unit_contexts:
        column_line, columns = _column_context(lines, unit_index, unit_line)
        period_line = _period_context(lines, unit_index, column_line)
        if len(columns) < 2:
            continue
        has_inline_unit = bool(_TRAILING_CURRENCY_RE.search(lines[unit_index]))
        row_start = unit_index if has_inline_unit else unit_index + 1
        for row_index in range(row_start, min(len(lines), unit_index + 45)):
            row_match, row_span = _row_match(lines, row_index)
            if not row_match:
                continue
            label = _clean_metric_label(row_match.group("label"))
            values = row_match.group("values").split()
            if len(values) == len(columns) + 1 and _NOTE_MARKER_RE.fullmatch(values[0]):
                values = values[1:]
            if len(values) != len(columns) or len(values) < 2:
                continue
            lower_label = label.lower()
            if any(token in lower_label for token in ("unaudited", "page", "ended", "change (%)")):
                continue
            if any(token in lower_label for token in _NON_OPERATING_LABEL_TOKENS):
                continue
            if not any(token in lower_label for token in _FINANCIAL_LABEL_TOKENS):
                continue
            key = (label.lower(), period_line.lower())
            if key in seen:
                continue
            seen.add(key)
            value_items = [
                {"column": column, "raw": value}
                for column, value in zip(columns, values)
            ]
            period = _period_cn(period_line or "官方财务表期间", columns)
            unit_cn = _UNIT_CN.get(unit.lower(), unit)
            except_cn = f"（{_UNIT_CN.get(except_for.lower(), except_for)}除外）" if except_for else ""
            values_cn = "；".join(f"{item['column']}={item['raw']}" for item in value_items)
            statement = (
                f"财务表：{_metric_cn(label)}；期间={period}；列序={'、'.join(columns)}；"
                f"币种={_CURRENCY_CN.get(currency, currency)}；单位={unit_cn}{except_cn}；数值={values_cn}。"
            )
            excerpt = _safe_excerpt(
                [period_line, column_line, unit_line, " ".join(lines[row_index : row_index + row_span])],
                limit=800,
            )
            if excerpt is None:
                continue
            facts.append(
                {
                    "statement_cn": statement,
                    "statement": statement,
                    "fact_type": "OFFICIAL_FACT",
                    "fact_kind": "financial",
                    "locator": f"PDF page {page_number}",
                    "page": page_number,
                    "source_excerpt": excerpt,
                    "fields": {
                        "kind": "financial",
                        "label": label,
                        "label_cn": _metric_cn(label),
                        "period_label": period_line,
                        "period_label_cn": period,
                        "columns": columns,
                        "currency": currency,
                        "unit": unit,
                        "except_for": except_for or None,
                        "values": value_items,
                    },
                }
            )
    return facts


def _dividend_facts(page_number: int, text: str) -> list[dict[str, Any]]:
    if "dividend" not in text.lower():
        return []
    facts: list[dict[str, Any]] = []
    date_value_re = re.compile(
        r"\b(?:[0-3]?\d\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+[0-3]?\d,?\s+\d{4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"
    )
    amount_value_re = re.compile(r"\b[A-Z]{2,5}\s*[0-9][0-9,]*(?:\.\d+)?\s*(?:per\s+share)?\b", re.IGNORECASE)
    lines = text.splitlines()
    patterns: tuple[tuple[str, re.Pattern[str], str], ...] = (
        (
            "dividend_declared",
            re.compile(r"^Dividend declared\s+(?P<value>.+)$", re.IGNORECASE),
            "公告披露中期股息：",
        ),
        (
            "ex_dividend_date",
            re.compile(r"^Ex-dividend date\s+(?P<value>.+)$", re.IGNORECASE),
            "公告披露除息日：",
        ),
        (
            "record_date",
            re.compile(r"^Record date\s+(?P<value>.+)$", re.IGNORECASE),
            "公告披露登记日：",
        ),
        (
            "payment_date",
            re.compile(r"^Payment date\s+(?P<value>.+)$", re.IGNORECASE),
            "公告披露派付日：",
        ),
    )
    for field, pattern, prefix in patterns:
        for line in lines:
            match = pattern.match(line)
            if not match:
                continue
            raw_value = _normal_line(match.group("value"))
            if not raw_value or raw_value.lower().startswith(("not applicable", "n/a")):
                continue
            if field == "dividend_declared":
                amount_match = amount_value_re.search(raw_value)
                if amount_match is None:
                    continue
                raw_value = _normal_line(amount_match.group(0))
            else:
                date_match = date_value_re.search(raw_value)
                if date_match is None:
                    continue
                raw_value = _normal_line(date_match.group(0))
            if field == "dividend_declared":
                amount_match = amount_value_re.search(raw_value)
                if amount_match is None:
                    continue
                amount_text = amount_match.group(0)
                amount_parts = re.match(
                    r"(?P<currency>[A-Z]{2,5})\s*(?P<number>[0-9][0-9,]*(?:\.\d+)?)\s*(?:per\s+share)?",
                    amount_text,
                    flags=re.IGNORECASE,
                )
                if amount_parts:
                    currency_cn = _CURRENCY_CN.get(amount_parts.group("currency").upper(), amount_parts.group("currency").upper())
                    statement = f"公告披露股息：每股{currency_cn}{amount_parts.group('number')}。"
                else:
                    statement = f"公告披露股息：{raw_value}。"
            else:
                statement = f"{prefix}{_date_fragment_cn(raw_value)}。"
            facts.append(
                {
                    "statement_cn": statement,
                    "statement": statement,
                    "fact_type": "OFFICIAL_FACT",
                    "fact_kind": "dividend",
                    "locator": f"PDF page {page_number}",
                    "page": page_number,
                    "source_excerpt": line,
                    "fields": {
                        "kind": "dividend",
                        "field": field,
                        "value_raw": raw_value,
                        "value_cn": statement.rstrip("。"),
                    },
                }
            )
            break
    return facts


def _egm_facts(page_number: int, text: str) -> list[dict[str, Any]]:
    if "extraordinary general meeting" not in text.lower() or "resolution" not in text.lower():
        return []
    pattern = re.compile(
        r"(?P<kind>SPECIAL|ORDINARY)\s+RESOLUTION\s*\n?\s*(?P<number>\d+)\.\s*"
        r"(?P<body>.*?)(?=\n\s*(?:SPECIAL|ORDINARY)\s+RESOLUTION|\n\s*By order of the Board|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    facts: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        body = _normal_line(match.group("body"))
        if len(body) < 40 or "consider and approve" not in body.lower():
            continue
        lower = body.lower()
        if "registered capital" in lower or "articles of association" in lower:
            summary = "拟审议注册资本变更、章程修订及相关工商变更登记。"
            topic = "REGISTERED_CAPITAL_AND_ARTICLES"
        elif "cash management" in lower or "idle self-owned funds" in lower:
            summary = "拟审议提高闲置自有资金现金管理的使用额度。"
            topic = "CASH_MANAGEMENT"
        else:
            # Unknown resolution wording is retained as a source receipt but
            # does not become a made-up Chinese company fact.
            continue
        excerpt = _safe_excerpt([match.group(0)], limit=800)
        if excerpt is None:
            continue
        resolution_kind_cn = "特别决议" if match.group("kind").upper() == "SPECIAL" else "普通决议"
        facts.append(
            {
                "statement_cn": f"股东会{resolution_kind_cn}{match.group('number')}：{summary}",
                "statement": f"股东会{resolution_kind_cn}{match.group('number')}：{summary}",
                "fact_type": "OFFICIAL_FACT",
                "fact_kind": "egm_resolution",
                "locator": f"PDF page {page_number}",
                "page": page_number,
                "source_excerpt": excerpt,
                "fields": {
                    "kind": "egm_resolution",
                    "resolution_kind": match.group("kind").upper(),
                    "resolution_number": int(match.group("number")),
                    "topic": topic,
                },
            }
        )
    return facts


def _narrative_facts(page_number: int, text: str) -> list[dict[str, Any]]:
    lower_text = text.lower()
    if not any(token in lower_text for token in ("business review", "operating results", "released", "served a cumulative")):
        return []
    paragraphs = [
        _normal_line(paragraph)
        for paragraph in re.split(r"\n\s*\n+", text)
        if len(_normal_line(paragraph)) >= 80
    ]
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    revenue_pattern = re.compile(
        r"(?:achieved|generat(?:ed|ing)|reported)\s+revenue\s+of\s+(?P<currency>RMB|HKD|USD)\s*"
        r"(?P<amount>[0-9,.]+)\s*million[^.]{0,180}?(?P<direction>increase|decrease)\s+of\s+(?P<pct>[0-9.]+)%",
        re.IGNORECASE,
    )
    service_pattern = re.compile(r"served\s+a\s+cumulative\s+total\s+of\s+(?P<count>over\s+[0-9,.]+)\s+(?P<subject>medical institutions|customers)", re.IGNORECASE)
    release_pattern = re.compile(r"released\s+(?P<product>[A-Za-z][A-Za-z0-9-]{1,30})(?:,|\s+during|\s+its)", re.IGNORECASE)
    for paragraph in paragraphs:
        if any(token in paragraph.lower() for token in _DISCLAIMER_TOKENS):
            continue
        statement: str | None = None
        fields: dict[str, Any] = {"kind": "business"}
        revenue_match = revenue_pattern.search(paragraph)
        service_match = service_pattern.search(paragraph)
        release_match = release_pattern.search(paragraph)
        if revenue_match:
            currency = revenue_match.group("currency").upper()
            direction = "同比增加" if revenue_match.group("direction").lower() == "increase" else "同比减少"
            statement = (
                f"经营段落披露收入约{_CURRENCY_CN.get(currency, currency)}{revenue_match.group('amount')}百万元，"
                f"{direction}{revenue_match.group('pct')}%。"
            )
            fields.update(
                {
                    "kind": "business_revenue",
                    "currency": currency,
                    "amount_raw": revenue_match.group("amount"),
                    "change_direction": revenue_match.group("direction").lower(),
                    "change_pct_raw": revenue_match.group("pct"),
                }
            )
        elif service_match:
            subject_cn = "医疗机构" if service_match.group("subject").lower() == "medical institutions" else "客户"
            statement = f"经营段落披露累计服务{service_match.group('count')} {subject_cn}。"
            fields.update({"kind": "business_scale", "count_raw": service_match.group("count"), "subject": subject_cn})
        elif release_match:
            statement = f"经营段落披露报告期内发布产品/模型 {release_match.group('product')}。"
            fields.update({"kind": "business_product_release", "product": release_match.group("product")})
        if statement is None or statement in seen:
            continue
        excerpt = _safe_excerpt([paragraph], limit=800)
        if excerpt is None:
            continue
        seen.add(statement)
        facts.append(
            {
                "statement_cn": statement,
                "statement": statement,
                "fact_type": "OFFICIAL_FACT",
                "fact_kind": "business",
                "locator": f"PDF page {page_number}",
                "page": page_number,
                "source_excerpt": excerpt,
                "fields": fields,
            }
        )
        if len(facts) >= 3:
            break
    return facts


def extract_facts_from_pages(pages: Iterable[Mapping[str, Any]], *, title: str = "") -> list[dict[str, Any]]:
    """Extract only structured, page-locatable facts from parsed pages."""

    del title  # Title is retained by the source receipt; facts use body fields.
    facts: list[dict[str, Any]] = []
    for page in pages:
        try:
            page_number = int(page["page"])
            text = str(page["text"])
        except (KeyError, TypeError, ValueError):
            continue
        if not text.strip() or any(token in text.lower() for token in _DISCLAIMER_TOKENS) and len(text) < 100:
            continue
        facts.extend(_financial_facts(page_number, text))
        facts.extend(_dividend_facts(page_number, text))
        facts.extend(_egm_facts(page_number, text))
        facts.extend(_narrative_facts(page_number, text))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for fact in facts:
        key = (str(fact.get("statement_cn", "")), int(fact.get("page", 0)))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fact)
    if len(deduped) <= _MAX_DOCUMENT_FACTS:
        return deduped
    # Long interim reports repeat the same statement layout across detailed
    # notes.  Keep a bounded, deterministic evidence set while retaining the
    # headline metrics and all event facts.  The source receipt still carries
    # the document digest and page count for deeper follow-up.
    priority_tokens = ("revenue", "gross profit", "loss for", "profit for", "operating", "cash")
    ranked = sorted(
        enumerate(deduped),
        key=lambda pair: (
            0 if pair[1].get("fact_kind") in {"dividend", "egm_resolution"} else 1,
            0 if any(token in str(pair[1].get("fields", {}).get("label", "")).lower() for token in priority_tokens) else 1,
            pair[0],
        ),
    )
    return [fact for _, fact in ranked[:_MAX_DOCUMENT_FACTS]]


def extract_pdf_facts(body: bytes, *, title: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pages = extract_pdf_pages(body)
    return extract_facts_from_pages(pages, title=title), pages
