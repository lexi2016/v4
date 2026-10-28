"""Pure, research-only advice projection for V4 manager rows.

The stage row and official facts are the only inputs.  This module never
changes the stage/formal gate and never emits a trading BUY.  The public
recommendation is versioned separately from the execution gate so a blocked
stage row can still carry an auditable, current research opinion.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re
from typing import Any, Mapping, Sequence


RECOMMENDATION_SCHEMA_VERSION = "v4.manager_research.recommendation.v2"
RESEARCH_ONLY_SCOPE = "RESEARCH_ONLY"
ADVICE_COVERAGE_SCOPE = "仅依据已解析官方财报结构化事实；近期重大事件（含合作/公告）覆盖未确认。"
ADVICE_ACTIONS = ("BUY", "CONDITIONAL_BUY", "WATCH", "AVOID", "DATA_INSUFFICIENT")
ACTION_ORDER = ("CONDITIONAL_BUY", "WATCH", "AVOID", "DATA_INSUFFICIENT")
_UTC8 = timezone(timedelta(hours=8))


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _record(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _normalise_token(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    return re.sub(r"[\s-]+", "_", text.upper())


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        raw = value.strip().replace(",", "")
        if not raw or raw.lower() in {"n/a", "na", "--", "—", "–", "-"}:
            return None
        negative = raw.startswith("(") and raw.endswith(")")
        raw = raw.strip("()").replace("−", "-").replace("–", "-").replace("—", "-")
        try:
            number = float(raw.rstrip("%"))
        except ValueError:
            return None
        if not math.isfinite(number):
            return None
        return -abs(number) if negative else number
    return None


def _parse_datetime(value: Any, *, target_trade_date: str | None = None) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        match = re.match(
            r"^(?:(20\d{2})[-/]?(\d{2})[-/]?(\d{2})[ T])?"
            r"(\d{1,2}):(\d{2})(?::(\d{2}))?",
            text,
        )
        if not match:
            return None
        year, month, day, hour, minute, second = match.groups()
        if year is None:
            date = target_trade_date or ""
            if not re.fullmatch(r"20\d{6}", date):
                return None
            year, month, day = date[:4], date[4:6], date[6:8]
        try:
            parsed = datetime(
                int(year), int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=_UTC8
            )
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_UTC8)
    return parsed.astimezone(_UTC8)


def _cutoff_datetime(cutoff_at: Any, target_trade_date: str) -> datetime | None:
    parsed = _parse_datetime(cutoff_at, target_trade_date=target_trade_date)
    if parsed is not None:
        return parsed
    try:
        return datetime.strptime(f"{target_trade_date} 09:40:00", "%Y%m%d %H:%M:%S").replace(tzinfo=_UTC8)
    except ValueError:
        return None


def timing_status(
    *,
    target_trade_date: str,
    cutoff_at: Any,
    observed_at: Any,
    generated_at: Any,
    source_published_at: Any,
) -> str:
    """Classify timing without claiming historical 09:40 availability."""

    generated = _parse_datetime(generated_at)
    cutoff = _cutoff_datetime(cutoff_at, target_trade_date)
    observed = _parse_datetime(observed_at, target_trade_date=target_trade_date)
    published = _parse_datetime(source_published_at)
    generated_date = generated.strftime("%Y%m%d") if generated else None
    if generated_date != target_trade_date:
        return "HISTORICAL_BACKFILL"
    if generated is None or cutoff is None:
        return "CUTOFF_UNCONFIRMED"
    if observed is None:
        return "CUTOFF_UNCONFIRMED"
    if observed.strftime("%Y%m%d") != target_trade_date or observed < cutoff:
        return "CUTOFF_UNCONFIRMED"
    if published is None:
        return "CUTOFF_UNCONFIRMED"
    if published.strftime("%Y%m%d") > target_trade_date or published > cutoff:
        return "CUTOFF_UNCONFIRMED"
    if generated < cutoff:
        return "CUTOFF_UNCONFIRMED"
    return "CURRENT_AFTER_CUTOFF"


def _value_map(fact: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    fields = _record(fact.get("fields")) or {}
    raw_columns = fields.get("columns")
    columns = [str(item).strip() for item in raw_columns if isinstance(item, str) and item.strip()] if isinstance(raw_columns, list) else []
    values: dict[str, str] = {}
    raw_values = fields.get("values")
    if isinstance(raw_values, list):
        for item in raw_values:
            record = _record(item)
            column = _text(record.get("column")) if record else None
            raw = record.get("raw") if record else None
            if column and isinstance(raw, (str, int, float)) and not isinstance(raw, bool):
                values[column] = str(raw)
    return columns, values


def _period_text(fact: Mapping[str, Any]) -> str:
    fields = _record(fact.get("fields")) or {}
    for key in ("period_label_cn", "period_label", "reporting_period", "period"):
        value = _text(fields.get(key)) or _text(fact.get(key))
        if value:
            return value
    columns, _values = _value_map(fact)
    return "列=" + ",".join(columns) if columns else "CANNOT_CONFIRM_PERIOD"


def _period_year(fact: Mapping[str, Any]) -> int | None:
    period = _period_text(fact)
    years = [int(item) for item in re.findall(r"\b(20\d{2})\b", period)]
    if not years:
        columns, _values = _value_map(fact)
        years = [int(item) for item in columns if re.fullmatch(r"20\d{2}", item)]
    return max(years) if years else None


def _period_duration(fact: Mapping[str, Any]) -> str:
    period = _period_text(fact).lower()
    if re.search(r"annual|full\s+year|year\s+ended|年度|全年", period):
        return "ANNUAL"
    if re.search(r"six\s+months?|6\s*months?|half[- ]year|上半年|六个月|h1", period):
        return "H1"
    if re.search(r"nine\s+months?|9\s*months?|九个月|前三季度", period):
        return "9M"
    if re.search(r"three\s+months?|3\s*months?|quarter|季度|三个月|q[1-4]", period):
        return "Q"
    return "UNKNOWN"


def _period_end_date(fact: Mapping[str, Any]) -> str | None:
    """Return the explicit reporting-period end date when it is recoverable.

    A year alone is not enough to join an annual fact to an interim fact.  The
    parser intentionally accepts only bounded date forms found in official
    labels; opaque prose remains unbound and is handled as a separate gap.
    """

    period = _period_text(fact)
    dates: set[str] = set()

    def add_date(year: Any, month: Any, day: Any) -> None:
        try:
            candidate = datetime(int(year), int(month), int(day))
        except (TypeError, ValueError):
            return
        dates.add(candidate.strftime("%Y-%m-%d"))

    for year, month, day in re.findall(r"\b(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", period):
        add_date(year, month, day)
    for year, month, day in re.findall(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", period):
        add_date(year, month, day)
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
        "nov": 11, "dec": 12,
    }
    for month, day, year in re.findall(
        r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(20\d{2})\b",
        period,
    ):
        if month.lower() in month_names:
            add_date(year, month_names[month.lower()], day)
    for day, month, year in re.findall(
        r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s*,?\s*(20\d{2})\b",
        period,
    ):
        if month.lower() in month_names:
            add_date(year, month_names[month.lower()], day)

    # HKEX tables sometimes omit the year in the period label but retain it
    # in the value columns (for example "six months ended June 30").
    if not dates:
        month_days: set[tuple[int, int]] = set()
        for month, day in re.findall(r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b", period):
            if month.lower() in month_names:
                month_days.add((month_names[month.lower()], int(day)))
        for month, day in re.findall(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?", period):
            month_days.add((int(month), int(day)))
        years = {int(item) for item in re.findall(r"\b(20\d{2})\b", period)}
        columns, _values = _value_map(fact)
        years.update(int(item) for item in columns if re.fullmatch(r"20\d{2}", item))
        if len(month_days) == 1 and years:
            month, day = next(iter(month_days))
            add_date(max(years), month, day)

    if len(dates) == 1:
        return next(iter(dates))

    # Standard period labels can omit the day altogether.  Bind those only
    # when the duration itself identifies one conventional end date.
    year = _period_year(fact)
    duration = _period_duration(fact)
    if year is not None:
        if duration == "ANNUAL":
            add_date(year, 12, 31)
        elif duration == "H1":
            add_date(year, 6, 30)
        elif duration == "9M":
            add_date(year, 9, 30)
        if len(dates) == 1:
            return next(iter(dates))
    return None


def _period_key(fact: Mapping[str, Any]) -> tuple[str | None, str]:
    """Return a comparable end-date/duration key for one official fact."""

    end_date = _period_end_date(fact)
    if end_date is not None:
        return end_date, _period_duration(fact)
    year = _period_year(fact)
    return (f"YEAR:{year}" if year is not None else None), _period_duration(fact)


def _period_sort_key(fact: Mapping[str, Any]) -> tuple[int, int, str, int]:
    key = _period_key(fact)
    raw_year = _period_year(fact)
    duration_order = {"UNKNOWN": 0, "Q": 1, "H1": 2, "9M": 3, "ANNUAL": 4}
    explicit_end = _period_end_date(fact)
    return raw_year or -1, 1 if explicit_end else 0, explicit_end or "", duration_order.get(key[1], 0)


def _label(fact: Mapping[str, Any]) -> str:
    fields = _record(fact.get("fields")) or {}
    official = next(
        (str(value).strip() for value in (fields.get("label"), fact.get("label")) if isinstance(value, str) and value.strip()),
        "",
    )
    translated = next(
        (str(value).strip() for value in (fields.get("label_cn"), fact.get("label_cn")) if isinstance(value, str) and value.strip()),
        "",
    )
    # Keep the official label and translated companion separated.  Matching a
    # bare Chinese ``收入`` anywhere in the combined string would incorrectly
    # classify ``Other income`` or ``Income tax`` as company revenue.
    return f"{official} || {translated}".strip().lower()


def _currency_unit(fact: Mapping[str, Any]) -> tuple[str | None, str | None]:
    fields = _record(fact.get("fields")) or {}
    currency = _text(fields.get("currency"))
    unit = _text(fields.get("unit"))
    return currency.upper() if currency else None, unit.lower() if unit else None


def _fact_ref(fact: Mapping[str, Any], source: Mapping[str, Any] | None = None) -> dict[str, Any]:
    source_sha = _text(fact.get("source_sha256")) or _text(fact.get("source_sha"))
    if source_sha is None and source is not None:
        source_sha = _text(source.get("sha256"))
    ref: dict[str, Any] = {
        "source_sha256": source_sha,
        "locator": _text(fact.get("locator")),
        "page": fact.get("page") if isinstance(fact.get("page"), int) else None,
    }
    return ref


def _comparison_values(fact: Mapping[str, Any], label: str) -> tuple[float | None, float | None, str | None, str | None]:
    columns, values = _value_map(fact)
    usable = [(column, raw) for column, raw in values.items() if column.lower() not in {"change", "change (%)", "yoy change (%)", "increase/decrease"}]
    year_columns = sorted(
        ((int(column), column, raw) for column, raw in usable if re.fullmatch(r"20\d{2}", column)),
        key=lambda item: item[0],
        reverse=True,
    )
    if len(year_columns) >= 2:
        current_column, previous_column = year_columns[0][1], year_columns[1][1]
        current_raw, previous_raw = year_columns[0][2], year_columns[1][2]
    else:
        if len(usable) < 2:
            return None, None, None, None
        current_column, current_raw = usable[0]
        previous_column, previous_raw = usable[1]
    current = _finite(current_raw)
    previous = _finite(previous_raw)
    lower = label.lower()
    # Some parsers emit a positive number for a row whose label starts with
    # ``Loss``.  Correct that narrow case, while preserving a positive value
    # in labels such as ``Profit (loss) for the period``: the parenthesised
    # word is an alternative label, not a sign instruction.
    loss_label = bool(re.search(r"^(?:net\s+)?loss\b|^(?:期内|年度)?亏损", lower)) and "profit (loss)" not in lower
    if current is not None and loss_label and current > 0:
        current = -current
    if previous is not None and loss_label and previous > 0:
        previous = -previous
    impairment_label = bool(
        re.search(r"impairment\s+(?:loss(?:es)?\s+)?(?:recognized\s+on\s+)?(?:trade\s+)?receivables?", lower)
        or re.search(r"(?:应收账款|贸易应收款|贸易应收账项).*(?:减值|拨备)", lower)
    )
    # Impairment is an adverse expense even when a parser has stripped the
    # parentheses from the official table.  Keep the evidence visible while
    # preventing a positive raw rendering from becoming a positive signal.
    if current is not None and impairment_label and current > 0:
        current = -current
    if previous is not None and impairment_label and previous > 0:
        previous = -previous
    cash_outflow_label = bool(
        re.search(r"cash\s+(?:outflow|outflows|used)\b|cash\s+flows?\s+(?:used|outflow)", lower)
        or (re.search(r"现金.*(?:流出|使用)", lower) and "现金 来自" not in lower)
    ) and "generated" not in lower and "产生" not in lower
    if current is not None and cash_outflow_label and current > 0:
        current = -current
    if previous is not None and cash_outflow_label and previous > 0:
        previous = -previous
    return current, previous, current_column, previous_column


def _dimension_match(label: str, dimension: str) -> tuple[bool, int]:
    compact = re.sub(r"\s+", " ", label).strip().lower()
    official, _, translated = compact.partition("||")
    official = official.strip()
    translated = translated.strip()
    if dimension == "revenue":
        if re.search(r"cost of revenue|cost of revenues|types of revenue|timing of revenue|revenue recognition|licensing revenue|rental income|interest income arising from revenue|sale of .*revenue|revenue.*sale of", official) or re.search(r"收入.*成本", translated):
            return False, 99
        if re.search(r"(?:^|\s)(?:i\.\s*)?(?:total\s+)?operating revenue\b|(?:^|\s)total revenue\b|(?:^|\s)revenue\s*$", official):
            return True, 0
        if re.search(r"(?:^|\s)(?:经营|营业|总)?收入\s*$", translated):
            return True, 0
        if re.search(r"(?:^|\s)(?:i\.\s*)?(?:total\s+)?operating revenue|(?:^|\s)total revenue|revenue from contracts with customers|(?:^|\s)revenue\b", official):
            return True, 1
        return False, 99
    if dimension == "gross_profit":
        return (bool(re.search(r"^gross profit$|gross profit\b", official) or re.search(r"毛利", translated)), 0)
    if dimension == "profit_loss":
        if re.search(r"adjusted|non[- ]ifrs|excluding non[- ]recurring", official) or re.search(r"经调整|非经常", translated):
            return False, 99
        if re.search(r"earnings per share|per share", official) or re.search(r"每股", translated):
            return False, 99
        if re.search(r"profit or loss of an associate|share of .*profit or loss|operating profit|operating loss", official) or re.search(r"营业利润", translated):
            return False, 99
        if re.search(r"^(?:net\s+)?(?:loss|profit)(?:\s*\(loss\))?\s+for\s+(?:the\s+)?(?:period|year)\s*$|^profit\s+\(loss\)\s+for\s+the\s+period\s*$|^(?:net\s+)?(?:loss|profit)\s*$", official) or re.search(r"期内(?:利润|亏损)|本期(?:利润|亏损)|净(?:利润|亏损)", translated):
            return True, 0
        if re.search(r"^income\s+for\s+(?:the\s+)?period\s*$", official) or re.search(r"^期内收入$", translated):
            return True, 0
        if re.search(r"^(?:net\s+)?(?:loss|profit)(?:\s*\(loss\))?\s+for\s+(?:the\s+)?(?:period|year)\b|attributable to .*shareholders|attributable to ordinary", official) or re.search(r"归属于", translated):
            return True, 1
        if re.search(r"loss before taxation|profit before income tax|loss before tax", official) or re.search(r"税前利润|税前亏损", translated):
            return True, 3
        return False, 99
    if dimension == "operating_loss":
        # HKEX tables use both ``Operating loss`` and ``Loss from
        # operations`` (and the corresponding profit form).  Keep the
        # dimension bound to the operating result while accepting these
        # equivalent labels so a real loss row cannot silently become
        # MISSING.
        if (
            re.search(r"\boperating\s+(?:profit|loss)\b", official)
            or re.search(r"\b(?:profit|loss)\s+from\s+operations?\b", official)
            or re.search(r"\bprofit\s*/?\s*\(?loss\)?\s+from\s+operations?\b", official)
            or re.search(r"营业(?:利润|亏损)", translated)
        ):
            return True, 0
        return False, 99
    if dimension == "receivable_impairment":
        if re.search(r"impairment\s+(?:loss(?:es)?\s+)?(?:recognized\s+on\s+)?(?:trade\s+)?receivables?", official) or re.search(r"(?:应收账款|贸易应收款|贸易应收账项).*(?:减值|拨备)", translated):
            return True, 0
        return False, 99
    if dimension == "operating_cashflow":
        if re.search(r"financing|investing", official) or re.search(r"投资|融资", translated):
            return False, 99
        if re.search(r"cash.*operating activities|cash.*operations", official) or re.search(r"经营活动.*现金流|经营现金流", translated):
            score = 0 if "net cash" in official or "net cash flow" in official or "净额" in translated or "净现金" in translated else 1
            return True, score
        return False, 99
    if dimension == "cash":
        if re.search(r"cash and cash equivalents|cash and bank balances|bank balances and cash|bank and cash balances|cash at bank balances", official) or re.search(r"现金及现金等价物|现金及银行结余|银行结余及现金|银行及现金结余", translated):
            return True, 0
        return False, 99
    if dimension == "liabilities":
        return bool(re.search(r"borrowings|lease liabilities|lease liability", official) or re.search(r"负债|借款", translated)), 0
    return False, 99


def _dimension_display_state(current: float | None, previous: float | None) -> str:
    if current is None or previous is None:
        return "MISSING"
    if current > 0 and previous > 0:
        return "POSITIVE" if current >= previous else "MIXED"
    if current > 0 and previous <= 0:
        return "IMPROVING"
    if current <= 0 and current > previous:
        return "IMPROVING"
    return "NEGATIVE"


def _candidate_facts(facts: Sequence[Mapping[str, Any]], dimension: str) -> list[tuple[int, Mapping[str, Any], float | None, float | None, str | None, str | None]]:
    matches: list[tuple[int, Mapping[str, Any], float | None, float | None, str | None, str | None]] = []
    for fact in facts:
        if not isinstance(fact, Mapping) or fact.get("fact_kind") not in {None, "financial"}:
            continue
        label = _label(fact)
        matched, score = _dimension_match(label, dimension)
        if not matched:
            continue
        current, previous, current_column, previous_column = _comparison_values(fact, label)
        matches.append((score, fact, current, previous, current_column, previous_column))
    return matches


def _select_dimension(
    facts: Sequence[Mapping[str, Any]],
    dimension: str,
    source: Mapping[str, Any] | None,
) -> dict[str, Any]:
    matches = _candidate_facts(facts, dimension)
    base: dict[str, Any] = {
        "dimension": dimension,
        "state": "MISSING",
        "current": None,
        "previous": None,
        "current_column": None,
        "previous_column": None,
        "period": None,
        "currency": None,
        "unit": None,
        "fact_refs": [],
        "period_key": None,
        "period_mismatch": False,
        "_current_value": None,
        "_previous_value": None,
        "_period_key": None,
        "_comparable": False,
    }
    if not matches:
        return base
    best_score = min(item[0] for item in matches)
    matches = [item for item in matches if item[0] == best_score]
    # Select one complete reporting-period key per dimension.  Unknown-period
    # rows may be duplicate parser presentations, but they must not be mixed
    # into an explicitly bound H1/9M/annual row merely because the year agrees.
    bound_matches = [item for item in matches if _period_key(item[1])[0] is not None]
    if bound_matches:
        latest = max(bound_matches, key=lambda item: _period_sort_key(item[1]))
        selected_key = _period_key(latest[1])
        matches = [item for item in bound_matches if _period_key(item[1]) == selected_key]
        # Balance-sheet cash rows often use an opaque "financial statement
        # period" label while the cash-flow statement binds an interim end
        # date.  Keep that alternate cash presentation for conflict detection;
        # it is never used to manufacture a cross-period core count.
        if dimension == "cash":
            matches.extend(
                item for item in bound_matches
                if _period_key(item[1]) != selected_key
                and _period_duration(item[1]) == "UNKNOWN"
            )
    else:
        matches = [item for item in matches if _period_key(item[1])[0] is None]
    # Select the dominant unit/currency group.  A mismatch among the selected
    # core facts is a true conflict; it must not be hidden by input ordering.
    groups: dict[tuple[str | None, str | None], list[tuple[int, Mapping[str, Any], float | None, float | None, str | None, str | None]]] = {}
    for item in matches:
        groups.setdefault(_currency_unit(item[1]), []).append(item)
    usable_groups = {key: items for key, items in groups.items() if any(item[2] is not None and item[3] is not None for item in items)}
    if not usable_groups:
        return base
    selected_group = max(usable_groups.values(), key=lambda items: len(items))
    if len(usable_groups) > 1:
        base.update({
            "state": "CONFLICT",
            "period": _period_text(selected_group[0][1]),
            "currency": _currency_unit(selected_group[0][1])[0],
            "unit": _currency_unit(selected_group[0][1])[1],
            "fact_refs": [_fact_ref(item[1], source) for item in matches],
            "_period_key": _period_key(selected_group[0][1]),
            "period_key": list(_period_key(selected_group[0][1])),
        })
        return base
    # Prefer a single exact row; repeated facts with the same values are
    # duplicate presentations, while differing values are a conflict.
    signatures = {(item[2], item[3]) for item in selected_group if item[2] is not None and item[3] is not None}
    first = selected_group[0]
    fact = first[1]
    currency, unit = _currency_unit(fact)
    if len(signatures) > 1:
        base.update({
            "state": "CONFLICT",
            "period": _period_text(fact),
            "currency": currency,
            "unit": unit,
            "fact_refs": [_fact_ref(item[1], source) for item in selected_group],
            "period_key": list(_period_key(fact)),
            "_period_key": _period_key(fact),
        })
        return base
    current, previous = first[2], first[3]
    columns, values = _value_map(fact)
    current_column = first[4]
    previous_column = first[5]
    current_raw = values.get(current_column) if current_column else None
    previous_raw = values.get(previous_column) if previous_column else None
    base.update({
        "state": _dimension_display_state(current, previous),
        # ``current``/``previous`` are the actual reported values.  Column
        # names are retained separately so a consumer cannot mistake a year
        # label for the value itself.
        "current": current_raw if current_raw is not None else (str(current) if current is not None else None),
        "previous": previous_raw if previous_raw is not None else (str(previous) if previous is not None else None),
        "current_column": current_column,
        "previous_column": previous_column,
        "period": _period_text(fact),
        "currency": currency,
        "unit": unit,
        "fact_refs": [_fact_ref(item[1], source) for item in selected_group],
        "period_key": list(_period_key(fact)),
        "_current_value": current,
        "_previous_value": previous,
        "_period_key": _period_key(fact),
        "_comparable": current is not None and previous is not None and currency is not None and unit is not None,
    })
    return base


def _public_dimension(dimension: Mapping[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in dimension.items() if not key.startswith("_")}
    public.setdefault("text", _basis_text(public))
    return public


def extract_financial_evidence(
    facts: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract comparable same-report facts from the persisted official rows."""

    safe_facts = [fact for fact in facts if isinstance(fact, Mapping)]
    dimensions = {
        name: _select_dimension(safe_facts, name, source)
        for name in (
            "revenue", "gross_profit", "profit_loss", "operating_cashflow",
            "cash", "liabilities", "operating_loss", "receivable_impairment",
        )
    }
    core_names = ("revenue", "gross_profit", "profit_loss", "operating_cashflow")
    core = [dimensions[name] for name in core_names]
    # A recommendation may only count dimensions from one common reporting
    # period.  Choose the largest bound group; ties use the newest period.  A
    # dimension from another group remains visible as a period-mismatch gap,
    # but cannot contribute to comparable/positive/negative counts.
    period_groups: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
    for item in core:
        key = item.get("_period_key")
        if key is not None and item.get("state") not in {"MISSING", "CONFLICT"}:
            period_groups.setdefault(tuple(key), []).append(item)
    common_period_key: tuple[str | None, str] | None = None
    if period_groups:
        common_period_key = max(
            period_groups,
            key=lambda key: (
                len(period_groups[key]),
                key[0] or "",
                {"UNKNOWN": 0, "Q": 1, "H1": 2, "9M": 3, "ANNUAL": 4}.get(key[1], 0),
            ),
        )
        for item in core:
            if item.get("_period_key") is None or tuple(item.get("_period_key")) == common_period_key:
                continue
            if item.get("state") in {"MISSING", "CONFLICT"}:
                continue
            item["state"] = "MISSING"
            item["period_mismatch"] = True
            item["_current_value"] = None
            item["_previous_value"] = None
            item["_comparable"] = False
    comparable = [item for item in core if item.get("_comparable") and item.get("state") not in {"MISSING", "CONFLICT"}]
    risk_names = ("cash", "operating_loss", "receivable_impairment", "liabilities")
    risk_dimensions = [dimensions[name] for name in risk_names]
    conflicts = [item for item in [*core, *risk_dimensions] if item.get("state") == "CONFLICT"]
    positive = [item for item in comparable if item.get("state") in {"POSITIVE", "IMPROVING"} and (item.get("_current_value") or 0) > 0]
    negative = [item for item in comparable if item.get("state") == "NEGATIVE"]
    all_dimensions = [*core, *risk_dimensions]
    missing = [item["dimension"].upper() for item in all_dimensions if item.get("state") == "MISSING"]
    adverse = [
        item for item in all_dimensions
        if item.get("state") in {"NEGATIVE", "MIXED", "CONFLICT"} or item.get("period_mismatch")
    ]
    period_values = [item.get("period") for item in core if item.get("period") and item.get("_period_key") == common_period_key]
    period = next(iter(period_values), None)
    return {
        "dimensions": {name: _public_dimension(value) for name, value in dimensions.items()},
        "comparable_dimensions": [item["dimension"] for item in comparable],
        "positive_dimensions": [item["dimension"] for item in positive],
        "negative_dimensions": [item["dimension"] for item in negative],
        "conflict_dimensions": [item["dimension"] for item in conflicts],
        "missing_dimensions": missing,
        "comparable_count": len(comparable),
        "positive_count": len(positive),
        "negative_count": len(negative),
        "period": period,
        "period_key": list(common_period_key) if common_period_key is not None else None,
        "period_mismatch_dimensions": [item["dimension"] for item in core if item.get("period_mismatch")],
        "adverse_dimensions": [item["dimension"] for item in adverse],
        "risk_dimensions": [item["dimension"] for item in risk_dimensions if item.get("state") not in {"MISSING"}],
        "evidence_gaps": [
            {
                "dimension": item["dimension"],
                "state": item.get("state"),
                "period": item.get("period"),
                "fact_refs": list(item.get("fact_refs") or []),
            }
            for item in all_dimensions
            if item.get("state") in {"MISSING", "CONFLICT", "NEGATIVE", "MIXED"} or item.get("period_mismatch")
        ],
        "fact_count": len(safe_facts),
        "evidence_grade": "CONFLICT" if conflicts else "COMPARABLE" if len(comparable) >= 2 else "PARTIAL" if comparable else "MISSING",
        "_dimensions": dimensions,
    }


def _market_missing(market_snapshot: Mapping[str, Any] | None) -> list[str]:
    if not market_snapshot:
        return ["PRICE_PIT_UNAVAILABLE"]
    aliases = {
        "price": ("last_price", "current_price", "price"),
        "support": ("support", "support_price", "support_primary_price"),
        "pressure": ("pressure", "pressure_price", "resistance", "resistance_price"),
        "volume": ("volume", "成交量"),
        "volume_ratio": ("volume_ratio", "量比"),
    }
    missing = []
    for label, keys in aliases.items():
        if not any(_finite(market_snapshot.get(key)) is not None for key in keys):
            missing.append(label)
    return (["PRICE_PIT_UNAVAILABLE", *missing] if missing else [])


def _basis_text(item: Mapping[str, Any]) -> str:
    dimension = str(item.get("dimension"))
    state = str(item.get("state"))
    return f"{dimension}={state}（当前={item.get('current') or 'CANNOT_CONFIRM'}，前期={item.get('previous') or 'CANNOT_CONFIRM'}）"


def derive_investment_advice(
    evidence: Mapping[str, Any],
    market_snapshot: Mapping[str, Any] | None = None,
    timing: str = "CUTOFF_UNCONFIRMED",
    *,
    source_status: str = "READY",
    source_reason: str | None = None,
    source_available: bool = True,
) -> dict[str, Any]:
    """Derive a current research opinion from facts only.

    This deliberately does not read a stage action or invent a judgment field.
    """

    dimensions = evidence.get("dimensions") if isinstance(evidence.get("dimensions"), Mapping) else {}
    basis = [dict(value) for value in dimensions.values() if isinstance(value, Mapping)]
    missing_dimensions = list(evidence.get("missing_dimensions") or [])
    if source_status != "READY" or not source_available:
        missing_dimensions.extend(["SOURCE_REF"] if source_available else ["OFFICIAL_FACTS", "SOURCE_REF"])
    if source_reason == "PDF_NO_STRUCTURED_FACTS":
        missing_dimensions.extend(["OFFICIAL_FACTS", "PDF_NO_STRUCTURED_FACTS"])
    if not evidence.get("fact_count"):
        missing_dimensions.append("OFFICIAL_FACTS")
    missing_dimensions.extend(_market_missing(market_snapshot))
    missing_dimensions = list(dict.fromkeys(str(item) for item in missing_dimensions if item))
    comparable_count = int(evidence.get("comparable_count") or 0)
    positive_count = int(evidence.get("positive_count") or 0)
    negative_count = int(evidence.get("negative_count") or 0)
    conflicts = list(evidence.get("conflict_dimensions") or [])
    action = "DATA_INSUFFICIENT"
    label = "数据不足"
    status = "NOT_GENERATED"
    reason = ""
    if evidence.get("fact_count") and source_available and comparable_count:
        status = "GENERATED"
        adverse_dimensions = list(dict.fromkeys(str(item) for item in evidence.get("adverse_dimensions") or []))
        critical_missing = sorted({"PROFIT_LOSS", "OPERATING_CASHFLOW"}.intersection(str(item).upper() for item in missing_dimensions))
        if critical_missing:
            action = "DATA_INSUFFICIENT"
            label = "数据不足"
            reason = "关键经营维度缺失（" + "、".join(critical_missing) + "），研究意见降级；原Stage、BUY与订单门禁不因此改变。"
        elif conflicts and comparable_count < 2:
            action = "DATA_INSUFFICIENT"
            label = "数据不足"
            reason = "同报告期官方事实存在口径或币种/单位冲突，未形成可比较研究意见。"
        elif conflicts:
            action = "WATCH"
            label = "观察"
            reason = "可比经营事实存在冲突或现金口径不一致，先保留研究观察，不能升级为条件买入。"
        elif negative_count >= 2 and any(item in evidence.get("negative_dimensions", []) for item in ("profit_loss", "operating_cashflow")):
            action = "AVOID"
            label = "回避"
            reason = "至少两项可比经营维度同时恶化；该结论仅表示当前研究层回避新增仓位。"
        elif positive_count >= 2 and negative_count == 0 and not adverse_dimensions:
            action = "CONDITIONAL_BUY"
            label = "条件买入"
            reason = "同报告期、同币种和同单位下至少两项经营维度为正向或改善；缺少估值/流动性与同一时点承接证据。"
        elif adverse_dimensions:
            action = "WATCH"
            label = "观察"
            reason = "已有可比官方事实，但存在已确认的经营反证、期间缺口或关键维度缺失，保持观察。"
        else:
            action = "WATCH"
            label = "观察"
            reason = "已有可比官方事实，但财务信号混合、单项改善或关键维度缺失，保持观察。"
    elif evidence.get("fact_count") and source_available:
        reason = "官方 facts 存在，但没有两期、同币种、同单位的可比较经营数值。"
        action = "DATA_INSUFFICIENT"
        label = "数据不足"
    else:
        reason = "没有可复核的官方结构化事实或来源回执，不能形成逐股研究意见。"
    if action == "DATA_INSUFFICIENT":
        status = "NOT_GENERATED"
    conditions: list[str] = []
    invalidation: list[str] = []
    if action == "CONDITIONAL_BUY":
        conditions.extend([
            "补齐同一时点价格、支撑/压力、成交量和来源回执后再评估，当前不表示已满足入场条件。",
            "复核下一期同报告期、同币种、同单位的收入、毛利、法定利润/亏损和经营现金流。",
            "补充估值、流动性和后续阶段承接证据；保持 RESEARCH_ONLY，不产生 BUY 或订单。",
        ])
    elif action == "WATCH":
        conditions.extend([
            "补齐缺失的法定利润/亏损、经营现金流或负债/现金维度，并复核下一期同口径数据。",
            "当前价格、量价或阶段承接条件仍需独立验证，不能由涨跌幅或 stage rank 推导。",
        ])
    elif action == "AVOID":
        conditions.extend([
            "等待法定利润和经营现金流至少一项持续改善，并复核下一期同口径官方事实。",
            "如需重新评估，必须补齐当前时点价格、流动性和来源回执。",
        ])
    else:
        conditions.append("补齐官方来源、报告期、同币种/单位结构化事实后再评估。")
    # Keep every known adverse or missing dimension attached to the row.  A
    # generic risk sentence is insufficient for a reviewer to trace the exact
    # operating-loss, impairment, cash-gap or conflict evidence.
    for item in basis:
        dimension = str(item.get("dimension") or "UNKNOWN").upper()
        state = str(item.get("state") or "MISSING")
        current = item.get("current") or "CANNOT_CONFIRM"
        previous = item.get("previous") or "CANNOT_CONFIRM"
        period = item.get("period") or "CANNOT_CONFIRM_PERIOD"
        if state == "NEGATIVE":
            conditions.append(f"已确认反证：{dimension} 当前={current}、前期={previous}（{period}）。")
            invalidation.append(f"{dimension} 仍为负或下一期无法按同口径官方原文复核时，保持当前边界。")
        elif state == "MIXED":
            conditions.append(f"口径信号转弱：{dimension} 当前={current}、前期={previous}（{period}）。")
            invalidation.append(f"{dimension} 继续转弱或无法按同口径官方原文复核时，保持观察。")
        elif state == "CONFLICT":
            conditions.append(f"证据冲突：{dimension} 存在不同值/币种/单位（{period}），不得按正向信号消费。")
            invalidation.append(f"{dimension} 的官方事实冲突未解决前，不得升级研究意见。")
        elif state == "MISSING":
            conditions.append(f"证据缺口：{dimension} 无同报告期、同币种/单位可比较数值。")
            invalidation.append(f"{dimension} 缺失或报告期不一致时，降级为 DATA_INSUFFICIENT。")
    for item in evidence.get("negative_dimensions", []):
        invalidation.append(f"若 {item} 继续恶化或下一期无法由同口径官方原文复核，保持当前边界。")
    if not invalidation:
        invalidation.append("若来源身份、报告期、币种/单位或 locator 无法复核，降级为 DATA_INSUFFICIENT。")
    if "PRICE_PIT_UNAVAILABLE" in missing_dimensions:
        invalidation.append("缺少同一时点价格/成交与支撑压力证据，不得把研究意见解释为已满足入场条件。")
    advice_basis = [dict(item) for item in basis]
    return {
        "status": status,
        "action": action,
        "label_cn": label,
        "evidence_grade": evidence.get("evidence_grade", "MISSING"),
        "priority_rank": None,
        "priority_label": None,
        "priority_reason": None,
        "reason": reason,
        "basis": advice_basis,
        "conditions": list(dict.fromkeys(conditions)),
        "invalidation_conditions": list(dict.fromkeys(invalidation)),
        "missing_dimensions": missing_dimensions,
        "advice_scope": "CURRENT_RESEARCH_JUDGMENT",
        "coverage_scope": ADVICE_COVERAGE_SCOPE,
        "rule_status": "DIRECTION_ONLY",
        "timing_status": timing,
    }


def _execution_gate(observation: Mapping[str, Any], stage_status: str | None) -> dict[str, Any]:
    action_level = observation.get("action_level")
    trade_status = observation.get("trade_status") or observation.get("trade_status_contract")
    formal = observation.get("formal_eligible") if isinstance(observation.get("formal_eligible"), bool) else None
    reasons: list[str] = []
    action_token = _normalise_token(action_level)
    trade_token = _normalise_token(trade_status)
    if action_token in {"NO_BUY", "NO_TRADE"}:
        reasons.append(f"ACTION_LEVEL_{action_token}")
    if trade_token in {"NO_BUY", "NO_TRADE", "WATCH_ONLY"}:
        reasons.append(f"TRADE_STATUS_{trade_token}")
    if formal is False:
        reasons.append("FORMAL_FALSE")
    if stage_status and stage_status != "READY":
        reasons.append("STAGE_PARTIAL" if stage_status == "PARTIAL_WITH_ROWS" else "STAGE_NOT_READY")
    return {
        "action_level": action_level,
        "trade_status": trade_status,
        "formal_eligible": formal,
        "status": "BLOCKED" if reasons else "OPEN" if formal is True else "UNKNOWN",
        "reasons": list(dict.fromkeys(reasons)),
        "blocked_reasons": list(dict.fromkeys(reasons)),
    }


def _base_result(
    *,
    advice: Mapping[str, Any],
    gate: Mapping[str, Any],
    observation: Mapping[str, Any],
    target_trade_date: str,
    cutoff_at: str,
    generated_at: str,
    timing: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    conditions = list(advice.get("conditions") or [])
    missing = list(advice.get("missing_dimensions") or [])
    blocking = list(gate.get("blocked_reasons") or [])
    if timing != "CURRENT_AFTER_CUTOFF":
        blocking.append(timing)
    upstream_gaps = evidence.get("cannot_confirm")
    if isinstance(upstream_gaps, list) and upstream_gaps:
        blocking.append("UPSTREAM_CANNOT_CONFIRM")
    published = _parse_datetime(evidence.get("source_published_at"))
    cutoff = _cutoff_datetime(cutoff_at, target_trade_date)
    if published is not None and cutoff is not None and published > cutoff:
        blocking.append("SOURCE_PUBLISHED_AFTER_CUTOFF")
    if "STAGE_PARTIAL" in blocking:
        # Keep the older wording as a compatibility alias while exposing the
        # precise gate status in execution_gate.status/reasons.
        blocking.append("STAGE_NOT_READY")
    if advice.get("status") != "GENERATED":
        blocking.extend(missing)
    return {
        "schema_version": RECOMMENDATION_SCHEMA_VERSION,
        "status": advice.get("status"),
        "action": advice.get("action"),
        "label_cn": advice.get("label_cn"),
        "conditions_met": list(advice.get("basis") or []),
        "conditions": conditions,
        "blocking_reasons": list(dict.fromkeys(blocking)),
        "missing_fields": missing,
        "upstream_action_level": observation.get("action_level"),
        "upstream_trade_status": observation.get("trade_status", observation.get("trade_status_contract")),
        "formal_eligible": observation.get("formal_eligible") if isinstance(observation.get("formal_eligible"), bool) else None,
        "execution_scope": RESEARCH_ONLY_SCOPE,
        "investment_advice": dict(advice),
        "execution_gate": dict(gate),
        "as_of": {
            "target_trade_date": target_trade_date,
            "stage_observed_at": observation.get("source_last_bar_time", observation.get("observed_at")),
            "cutoff_at": cutoff_at,
            "generated_at": generated_at,
            "timing_status": timing,
        },
        "timing_status": timing,
        "target_trade_date": target_trade_date,
        "generated_at": generated_at,
        "evidence": dict(evidence),
    }


def build_research_recommendation(
    *,
    observation: Mapping[str, Any],
    result: Mapping[str, Any],
    target_trade_date: str,
    cutoff_at: str,
    generated_at: str,
    input_source_sha256: str | None = None,
    stage_status: str | None = None,
    cannot_confirm: Any = None,
) -> dict[str, Any]:
    """Build one v2 research recommendation from persisted facts."""

    source = _record(result.get("source"))
    facts = result.get("facts") if isinstance(result.get("facts"), list) else []
    published_at = source.get("published_at") if source else None
    timing = timing_status(
        target_trade_date=target_trade_date,
        cutoff_at=cutoff_at,
        observed_at=observation.get("source_last_bar_time", observation.get("observed_at")),
        generated_at=generated_at,
        source_published_at=published_at,
    )
    evidence = extract_financial_evidence(facts, source)
    source_status = str(result.get("status") or "CANNOT_CONFIRM")
    source_reason = _text(result.get("reason")) or _text(observation.get("source_reason"))
    advice = derive_investment_advice(
        evidence,
        observation,
        timing,
        source_status=source_status,
        source_reason=source_reason,
        source_available=source is not None,
    )
    gate = _execution_gate(observation, stage_status)
    gap_values: list[str] = []
    for value in (cannot_confirm, observation.get("cannot_confirm")):
        if isinstance(value, str) and value.strip():
            gap_values.append(value.strip())
        elif isinstance(value, (list, tuple)):
            gap_values.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
    refs = []
    for item in advice.get("basis", []):
        refs.extend(item.get("fact_refs") or [])
    result_evidence = {
        "stage_input_identity": observation.get("input_identity"),
        "stage_status": stage_status,
        "cannot_confirm": list(dict.fromkeys(gap_values)),
        "source_published_at": published_at,
        "source_retrieved_at": source.get("retrieved_at") if source else None,
        "source_sha256": source.get("sha256") if source else None,
        "input_source_sha256": input_source_sha256,
        "fact_count": len(facts),
        "fact_refs": refs,
        "target_trade_date": target_trade_date,
        "cutoff_at": cutoff_at,
        "financial_evidence_grade": evidence.get("evidence_grade"),
    }
    return _base_result(
        advice=advice,
        gate=gate,
        observation=observation,
        target_trade_date=target_trade_date,
        cutoff_at=cutoff_at,
        generated_at=generated_at,
        timing=timing,
        evidence=result_evidence,
    )


def recommendation_summary(recommendations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return independent advice and gate counts without conflating them."""

    advice_counts = {action: 0 for action in ADVICE_ACTIONS}
    legacy_counts = {"CONDITIONAL_BUY": 0, "NO_BUY": 0, "NO_TRADE": 0, "DATA_INSUFFICIENT": 0}
    gate_counts = {"BLOCKED": 0, "OPEN": 0, "UNKNOWN": 0}
    for recommendation in recommendations:
        nested = _record(recommendation.get("investment_advice"))
        advice_action = _text(nested.get("action")) if nested else _text(recommendation.get("action"))
        if advice_action not in advice_counts:
            advice_action = "DATA_INSUFFICIENT"
        advice_counts[advice_action] += 1
        raw_action = _text(recommendation.get("action"))
        if raw_action in legacy_counts:
            legacy_counts[raw_action] += 1
        elif not nested and raw_action not in {"BUY", "WATCH", "AVOID", "CONDITIONAL_BUY"}:
            legacy_counts["DATA_INSUFFICIENT"] += 1
        elif raw_action == "DATA_INSUFFICIENT":
            legacy_counts["DATA_INSUFFICIENT"] += 1
        gate = _record(recommendation.get("execution_gate"))
        gate_status = _text(gate.get("status")) if gate else None
        if gate_status not in gate_counts:
            gate_status = "UNKNOWN"
        gate_counts[gate_status] += 1
    has_v2_advice = any(advice_counts[action] for action in ("BUY", "WATCH", "AVOID"))
    counts = {key: advice_counts.get(key, 0) for key in ADVICE_ACTIONS} if has_v2_advice else legacy_counts
    return {
        "schema_version": RECOMMENDATION_SCHEMA_VERSION,
        # Keep the v1 execution names for clients that still render them, but
        # make the v2 research actions first-class counts.  A NO_BUY gate is
        # never counted as a research advice action.
        "counts": counts,
        "investment_advice_counts": advice_counts,
        "execution_gate_counts": gate_counts,
        "priority_count": sum(
            1
            for recommendation in recommendations
            if isinstance(recommendation.get("investment_advice"), Mapping)
            and recommendation["investment_advice"].get("priority_rank") is not None
        ),
        "actions": [{"action": action, "count": advice_counts[action]} for action in ADVICE_ACTIONS if advice_counts[action]],
        "execution_scope": RESEARCH_ONLY_SCOPE,
        "execution_buy_count": 0,
    }


def assign_investment_priorities(rows: Sequence[Mapping[str, Any]]) -> int:
    """Assign an auditable research preference from comparable dimensions.

    The score uses only direction and dimension identity.  It never compares
    absolute amounts across issuers and never uses stage rank as an investment
    signal.  Stage rank/code are used only as deterministic tie breakers after
    the substantive score is equal.  Rows without at least two comparable
    dimensions remain unranked.
    """

    candidates: list[tuple[float, int, str, Mapping[str, Any], dict[str, Any]]] = []
    dimension_weight = {
        "revenue": 3.0,
        "gross_profit": 4.0,
        "profit_loss": 6.0,
        "operating_cashflow": 6.0,
    }
    state_delta = {
        "POSITIVE": 1.0,
        "IMPROVING": 0.8,
        "MIXED": -0.5,
        "NEGATIVE": -1.0,
    }
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        recommendation = row.get("research_recommendation")
        if not isinstance(recommendation, Mapping):
            continue
        advice = recommendation.get("investment_advice")
        if not isinstance(advice, Mapping) or advice.get("status") != "GENERATED":
            continue
        basis = advice.get("basis")
        if not isinstance(basis, list):
            continue
        usable = [
            item for item in basis
            if isinstance(item, Mapping)
            and item.get("dimension") in dimension_weight
            and item.get("state") in state_delta
            and item.get("current") is not None
            and item.get("previous") is not None
        ]
        if len(usable) < 2:
            continue
        score = 0.0
        positive: list[str] = []
        negative: list[str] = []
        for item in usable:
            dimension = str(item["dimension"])
            state = str(item["state"])
            contribution = dimension_weight[dimension] * state_delta[state]
            score += contribution
            if state in {"POSITIVE", "IMPROVING"}:
                positive.append(dimension)
            elif state == "NEGATIVE":
                negative.append(dimension)
        action = str(advice.get("action") or "")
        if action == "CONDITIONAL_BUY":
            score += 1.0
        elif action == "AVOID":
            score -= 5.0
        elif action == "DATA_INSUFFICIENT":
            continue
        observation = row.get("observation") if isinstance(row.get("observation"), Mapping) else {}
        raw_rank = observation.get("stage_rank")
        try:
            stage_rank = int(raw_rank)
        except (TypeError, ValueError):
            stage_rank = 10**9
        code = str(row.get("code") or "")
        reason_parts = []
        if positive:
            reason_parts.append("正向/改善=" + ",".join(positive))
        if negative:
            reason_parts.append("风险=" + ",".join(negative))
        reason_parts.append("按方向性财务维度评分；金额未跨公司比较")
        candidates.append((score, stage_rank, code, recommendation, {"reason": "；".join(reason_parts)}))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    for rank, (_score, _stage_rank, _code, recommendation, metadata) in enumerate(candidates, start=1):
        advice = recommendation.get("investment_advice")
        if not isinstance(advice, dict):
            continue
        advice["priority_rank"] = rank
        advice["priority_label"] = "首选" if rank == 1 else "次选" if rank == 2 else "研究优先"
        advice["priority_reason"] = metadata["reason"]
    return len(candidates)


__all__ = [
    "ACTION_ORDER",
    "ADVICE_ACTIONS",
    "RECOMMENDATION_SCHEMA_VERSION",
    "build_research_recommendation",
    "derive_investment_advice",
    "extract_financial_evidence",
    "assign_investment_priorities",
    "recommendation_summary",
    "timing_status",
]
