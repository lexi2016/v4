"""Pure financial evidence projection, independent of stores and job lifecycle."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping
from .recommendation import derive_investment_advice, extract_financial_evidence

_PDF_PAGE_LOCATOR_RE = re.compile(r"^PDF page [1-9][0-9]*$")

_STRUCTURED_FACT_KINDS = frozenset({"financial", "dividend", "egm_resolution", "business"})

_PRIMARY_FINANCIAL_TOKENS = (
    "revenue",
    "sales",
    "gross profit",
    "profit for",
    "loss for",
    "net profit",
    "net loss",
    "operating profit",
    "operating loss",
    "operating income",
    "cash generated",
    "cash used",
    "net cash",
)

_REVENUE_COMPONENT_TOKENS = (
    "other source",
    "rental income",
    "revenue recognised",
    "revenue recognized",
    "timing of revenue",
    "sale of",
    "rendering of",
    "service revenue",
    "segment",
)

_STATUTORY_RESULT_TOKENS = (
    "loss for",
    "profit for",
    "profit (loss) for",
    "profit(loss) for",
    "income for the period",
    "income for the year",
    "net profit",
    "net loss",
    "profit/loss",
)

_STATUTORY_EXCLUDED_LABEL_RE = re.compile(
    r"\b(?:other\s+)?comprehensive\s+income\b|\b(?:income|profit|loss)\s+before\s+tax\b|"
    r"\b(?:operating|gross)\s+(?:profit|loss|income)\b|\bshare\s+of\s+(?:the\s+)?profit\b",
    re.IGNORECASE,
)

_STATUTORY_RESULT_RE = re.compile(
    r"^(?:net\s+)?(?:profit|loss)(?:\s*/?\s*\(?\s*(?:profit|loss)\s*\)?)?\s+"
    r"for\s+the\s+(?:period|year)$|"
    r"^income\s+for\s+the\s+(?:period|year)$|"
    r"^(?:net\s+)?(?:profit|loss)(?:\s*/?\s*\(?\s*(?:profit|loss)\s*\)?)?$",
    re.IGNORECASE,
)

_STATUTORY_ATTRIBUTABLE_RE = re.compile(
    r"^(?:net\s+)?(?:profit|loss)(?:\s*/?\s*\(?\s*(?:profit|loss)\s*\)?)?\s+"
    r"attributable\s+to\s+(?:the\s+)?(?:owners?|equity\s+holders?|shareholders?)"
    r"(?:\s+of\s+(?:the\s+)?(?:company|group|parent|listed\s+company))?$",
    re.IGNORECASE,
)

def _usable_fact(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    statement = value.get("statement_cn")
    locator = value.get("locator")
    excerpt = value.get("source_excerpt")
    page = value.get("page")
    fields = value.get("fields")
    return (
        isinstance(statement, str)
        and bool(statement.strip())
        and bool(re.search(r"[\u3400-\u9fff]", statement))
        and isinstance(locator, str)
        and _PDF_PAGE_LOCATOR_RE.fullmatch(locator.strip()) is not None
        and isinstance(page, int)
        and not isinstance(page, bool)
        and page >= 1
        and isinstance(excerpt, str)
        and len(excerpt.strip()) >= 8
        and isinstance(fields, Mapping)
        and bool(fields)
        and isinstance(value.get("fact_kind"), str)
        and value.get("fact_kind") in _STRUCTURED_FACT_KINDS
    )

def _has_researchable_fact_set(facts: list[Mapping[str, Any]]) -> bool:
    """Require a meaningful company fact before exposing source READY.

    Balance-sheet fragments such as an isolated expense, liability, or asset
    line can be perfectly parseable while still being insufficient for a
    company research card. Dividend/EGM/business facts have their own
    structured meaning; a financial set needs at least one primary operating,
    profit/loss, or cash-flow metric.
    """

    revenue_rows = [
        fact
        for fact in facts
        if fact.get("fact_kind") == "financial"
        and _label_matches(_fact_value(fact, "label").lower(), "revenue")
    ]
    # A revenue component with no parsed total/aggregate row cannot support a
    # company-level revenue claim.  Keep the row's source receipt visible, but
    # fail closed rather than promoting a component (for example rental
    # income) into the headline.  Other financial sets with no revenue row can
    # still be useful when they contain a primary profit/loss or cash metric.
    if revenue_rows and not any(_is_aggregate_revenue_label(_fact_value(fact, "label")) for fact in revenue_rows):
        return False
    for fact in facts:
        kind = fact.get("fact_kind")
        if kind in {"dividend", "egm_resolution", "business"}:
            return True
        if kind == "financial":
            label = _fact_value(fact, "label").lower()
            if any(token in label for token in _PRIMARY_FINANCIAL_TOKENS):
                return True
    return False

def _fact_value(fact: Mapping[str, Any], field: str, default: str = "") -> str:
    fields = fact.get("fields")
    if isinstance(fields, Mapping):
        value = fields.get(field)
        if isinstance(value, str):
            return value.strip()
    return default

_SERVICE_CURRENCY_CN = {
    "RMB": "人民币",
    "CNY": "人民币",
    "HKD": "港元",
    "USD": "美元",
    "S$": "新加坡元",
}

_SERVICE_UNIT_CN = {
    "thousands": "千元",
    "thousand": "千元",
    "millions": "百万元",
    "million": "百万元",
    "percentages": "%",
    "yuan": "元",
}

def _fact_label_cn(fact: Mapping[str, Any]) -> str:
    fields = fact.get("fields")
    if isinstance(fields, Mapping):
        label_cn = fields.get("label_cn")
        if isinstance(label_cn, str) and label_cn.strip():
            return label_cn.strip()
        label = fields.get("label")
        if isinstance(label, str):
            translations = {
                "revenue": "收入",
                "total revenues": "总收入",
                "gross profit": "毛利",
                "loss for the period": "期内亏损",
                "profit for the period": "期内利润",
                "profit (loss) for the period": "期内利润/（亏损）",
                "profit(loss) for the period": "期内利润/（亏损）",
                "income for the period": "期内收益",
                "loss for the year": "年度亏损",
                "profit for the year": "年度利润",
                "profit (loss) for the year": "年度利润/（亏损）",
                "profit(loss) for the year": "年度利润/（亏损）",
                "income for the year": "年度收益",
                "operating profit": "经营利润",
                "operating loss": "经营亏损",
                "expenses": "费用",
                "liabilities": "负债",
                "cash and cash equivalents": "现金及现金等价物",
                "cash and bank balances": "现金及银行结余",
                "adjusted net loss for the year (a non-ifrs measure)": "经调整年度亏损（非国际财务报告准则）",
                "adjusted net loss (non-ifrs measure)": "经调整期内亏损（非国际财务报告准则）",
            }
            exact = translations.get(label.strip().lower())
            if exact:
                return exact
    statement = fact.get("statement_cn")
    if isinstance(statement, str) and statement.startswith("财务表："):
        return statement.removeprefix("财务表：").split("；", 1)[0].strip()
    return "财务项目"

def _is_adjusted_fact(fact: Mapping[str, Any]) -> bool:
    label = _fact_value(fact, "label").lower()
    statement = str(fact.get("statement_cn", "")).lower()
    return "adjusted" in label or "non-ifrs" in label or "non-ifrs" in statement or "经调整" in statement

def _financial_rows(facts: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    rows = [fact for fact in facts if fact.get("fact_kind") == "financial"]
    # Keep net/adjusted result rows near the core metrics for deterministic
    # fallback rendering, while statutory selection below remains role-aware.
    priority_tokens = ("revenue", "gross profit", "net profit", "net loss", "profit/loss", "operating", "cash")
    return sorted(
        rows,
        key=lambda fact: (
            0 if (
                any(token in _fact_value(fact, "label").lower() for token in priority_tokens)
                or _is_statutory_result_label(_fact_value(fact, "label"))
            ) else 1,
            int(fact.get("page", 0)),
            _fact_value(fact, "label").lower(),
        ),
    )

def _raw_decimal(raw: Any) -> Decimal | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip().replace(",", "")
    if value in {"", "—", "–", "-", "N/A", "n/a"}:
        return None
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    try:
        parsed = Decimal(value.rstrip("%"))
    except (InvalidOperation, ValueError):
        return None
    return -parsed if negative else parsed

def _financial_value_map(fact: Mapping[str, Any]) -> dict[str, str]:
    fields = fact.get("fields")
    values = fields.get("values") if isinstance(fields, Mapping) else None
    if not isinstance(values, list):
        return {}
    result: dict[str, str] = {}
    for item in values:
        if isinstance(item, Mapping) and isinstance(item.get("column"), str) and isinstance(item.get("raw"), str):
            result[item["column"]] = item["raw"]
    return result

def _first_financial(facts: list[Mapping[str, Any]], *tokens: str) -> Mapping[str, Any] | None:
    for fact in _financial_rows(facts):
        label = _fact_value(fact, "label").lower()
        if any(_label_matches(label, token) for token in tokens):
            return fact
    return None

def _first_financial_with_adjustment(
    facts: list[Mapping[str, Any]],
    *tokens: str,
    adjusted: bool | None = None,
) -> Mapping[str, Any] | None:
    candidates: list[Mapping[str, Any]] = []
    for fact in _financial_rows(facts):
        if adjusted is not None and _is_adjusted_fact(fact) != adjusted:
            continue
        label = _fact_value(fact, "label").lower()
        if any(_label_matches(label, token) for token in tokens):
            candidates.append(fact)
    if not candidates:
        return None
    if "revenue" not in tokens:
        return candidates[0]
    # Only an aggregate/total revenue row is suitable for a company headline.
    # Components remain in the folded fact evidence and are never allowed to
    # replace a missing total.
    aggregate = [fact for fact in candidates if _is_aggregate_revenue_label(_fact_value(fact, "label"))]
    if not aggregate:
        return None
    return aggregate[0]

def _is_aggregate_revenue_label(label: str) -> bool:
    """Return whether an official label represents a total revenue measure.

    HKEX financial tables commonly place a total ``Revenue`` row beside
    source/segment rows.  Qualifiers such as ``other source``, recognised-at-
    a-point-in-time, rental and product/service rows identify components and
    must not be promoted to the company-level metric.
    """

    clean = re.sub(r"\s+", " ", str(label or "").strip().lower())
    if not clean or any(token in clean for token in _REVENUE_COMPONENT_TOKENS):
        return False
    if re.search(r"\b(?:total|net|operating)?\s*revenues?\s*$", clean):
        return True
    # IFRS 15 wording is an aggregate contract-revenue measure even when the
    # table appends the scope or business description after the standard label.
    if re.match(r"^(?:total\s+)?revenue\s+from\s+contracts\s+with\s+customers\b", clean):
        return True
    return False

def _label_matches(label: str, token: str) -> bool:
    if token == "revenue":
        if "cost of revenue" in label or "cost of revenues" in label:
            return False
        # ``revenue`` is also used as a qualifier in rows such as interest
        # income arising from revenue contracts.  A revenue metric must be a
        # leading metric phrase so those ancillary rows cannot replace total
        # revenue in the card summary.
        return bool(re.match(r"^(?:(?:total|operating)\s+)?revenues?\b", label))
    if token in _STATUTORY_RESULT_TOKENS:
        return _is_statutory_result_label(label)
    return token in label

def _is_statutory_result_label(label: str) -> bool:
    """Match the legal profit/loss result row without accepting components.

    HKEX statements place Other comprehensive income beside the legal period
    result. A substring check for income for the period therefore selects the
    component when it sorts first. Keep the selector role-aware: only an exact
    period/year result, a net profit/loss result, or an explicitly attributable
    owner/equity-holder result is statutory here.
    """

    clean = re.sub(r"\s+", " ", str(label or "").strip().lower())
    clean = clean.replace("／", "/").replace("−", "-")
    if (
        not clean
        or _STATUTORY_EXCLUDED_LABEL_RE.search(clean)
        or re.search(r"\b(?:after\s+deducting|excluding|adjusted|non[- ]ifrs|non[- ]recurring)\b", clean)
    ):
        return False
    if _STATUTORY_RESULT_RE.fullmatch(clean):
        return True
    return _STATUTORY_ATTRIBUTABLE_RE.fullmatch(clean) is not None

def _financial_values(fact: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    fields = fact.get("fields")
    if not isinstance(fields, Mapping):
        return [], {}
    raw_columns = fields.get("columns")
    raw_values = fields.get("values")
    columns = [str(item) for item in raw_columns if isinstance(item, str)] if isinstance(raw_columns, list) else []
    values: dict[str, str] = {}
    if isinstance(raw_values, list):
        for item in raw_values:
            if isinstance(item, Mapping) and isinstance(item.get("column"), str) and isinstance(item.get("raw"), str):
                values[item["column"]] = item["raw"]
    return columns, values

def _comparison_columns(fact: Mapping[str, Any]) -> tuple[str, str | None]:
    columns, values = _financial_values(fact)
    years = sorted({column for column in columns if re.fullmatch(r"\d{4}", column)}, key=int, reverse=True)
    if years:
        return years[0], years[1] if len(years) > 1 else None
    usable = [column for column in columns if column not in {"Change", "Change (%)"} and column in values]
    if usable:
        return usable[0], usable[1] if len(usable) > 1 else None
    return "", None

def _amount_text(fact: Mapping[str, Any], raw: str) -> str:
    fields = fact.get("fields")
    if not isinstance(fields, Mapping):
        return raw
    currency = _SERVICE_CURRENCY_CN.get(str(fields.get("currency", "")).upper(), str(fields.get("currency", "")))
    unit = _SERVICE_UNIT_CN.get(str(fields.get("unit", "")).lower(), str(fields.get("unit", "")))
    suffix = f"{currency}{unit}" if currency and unit else currency or unit
    exact = f"{raw}{suffix}" if suffix else raw
    number = _raw_decimal(raw)
    raw_unit = str(fields.get("unit", "")).lower()
    if number is None or raw_unit not in {"thousands", "thousand", "millions", "million"} or not currency:
        return exact
    base = number * (Decimal(1000) if raw_unit in {"thousands", "thousand"} else Decimal(1000000))
    approximate_currency = "元" if currency == "人民币" else currency
    absolute = abs(base)
    if absolute >= Decimal(100000000):
        approximate = f"约{absolute / Decimal(100000000):.2f}亿{approximate_currency}"
    elif absolute >= Decimal(10000):
        approximate = f"约{absolute / Decimal(10000):.2f}万{approximate_currency}"
    else:
        approximate = f"约{absolute:.0f}{approximate_currency}"
    if base < 0:
        approximate = approximate.replace("约", "约-", 1)
    return f"{exact}（{approximate}）"

def _period_short(fact: Mapping[str, Any]) -> str:
    period = _fact_value(fact, "period_label_cn")
    columns, _ = _financial_values(fact)
    years = [int(item) for item in columns if re.fullmatch(r"\d{4}", item)]
    year = max(years) if years else None
    if not year:
        period_year = re.search(r"\b(19\d{2}|20\d{2})\b", period)
        year = int(period_year.group(1)) if period_year else None
    if "截至年度" in period:
        return f"{year}年度" if year else "年度"
    if "截至六个月" in period:
        return f"{year}年上半年" if year else "上半年"
    if "截至三个月" in period:
        return f"{year}年截至三个月" if year else "截至三个月"
    return "公告报告期"

def _change_text(fact: Mapping[str, Any], current: str, previous: str | None, *, compute_if_missing: bool = True) -> str:
    _, values = _financial_values(fact)
    raw_change = values.get("Change (%)") or values.get("Change")
    if raw_change:
        parsed = _raw_decimal(raw_change)
        if parsed is not None:
            direction = "增加" if parsed >= 0 else "减少"
            return f"同比{direction}{abs(parsed):g}%"
        return f"公告披露同比{raw_change if raw_change.rstrip().endswith('%') else raw_change + '%'}"
    if not compute_if_missing:
        return "公告未直接披露同比"
    current_number = _raw_decimal(current)
    previous_number = _raw_decimal(previous) if previous else None
    if current_number is not None and previous_number not in {None, Decimal(0)} and previous is not None:
        # A computed comparison is labelled as approximate and retains the
        # source values in the sentence; negative-base profit rows are handled
        # by the caller as a widening/narrowing statement.
        change = (current_number - previous_number) / abs(previous_number) * Decimal(100)
        return f"同比约{change:+.1f}%"
    return "公告未直接披露同比"

def _financial_summary_sentence(fact: Mapping[str, Any], *, role: str = "metric") -> str:
    label = _fact_label_cn(fact)
    current_column, previous_column = _comparison_columns(fact)
    _, values = _financial_values(fact)
    current = values.get(current_column, "")
    previous = values.get(previous_column, "") if previous_column else ""
    if not current:
        return f"{label}原表当前列无值"
    current_text = _amount_text(fact, current)
    if role == "statutory" or role == "adjusted":
        current_number = _raw_decimal(current)
        previous_number = _raw_decimal(previous) if previous else None
        if current_number is not None and current_number < 0:
            if previous_number is not None and abs(current_number) < abs(previous_number):
                trend = "，亏损额较上年同期收窄"
            elif previous_number is not None and abs(current_number) > abs(previous_number):
                trend = "，亏损额较上年同期扩大"
            else:
                trend = ""
            prefix = "经调整口径亏损" if role == "adjusted" else "法定口径亏损"
            suffix = "（非IFRS）" if role == "adjusted" else ""
            if role == "adjusted" and "（约" in current_text:
                exact_text, approximate_text = current_text.split("（约", 1)
                return f"{prefix}{exact_text}{suffix}（约{approximate_text}{trend}"
            return f"{prefix}{current_text}{suffix}{trend}"
        prefix = "经调整口径利润" if role == "adjusted" else "法定口径利润"
        suffix = "（非IFRS）" if role == "adjusted" else ""
        if role == "adjusted" and "（约" in current_text:
            exact_text, approximate_text = current_text.split("（约", 1)
            return f"{prefix}{exact_text}{suffix}（约{approximate_text}"
        return f"{prefix}{current_text}{suffix}"
    change = _change_text(fact, current, previous or None, compute_if_missing=role != "fallback")
    return f"{label}{current_text}，{change}"

def _build_research_sections(
    issuer: str,
    code: str,
    facts: list[Mapping[str, Any]],
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive readable Chinese research from the structured source fields.

    Every sentence containing a company claim is tied to a parsed fact.  The
    remaining sentences explicitly describe what the source does not prove,
    so a headline or one generic disclaimer cannot become a thesis.
    """

    kinds = {str(fact.get("fact_kind")) for fact in facts}
    name = issuer.strip() or str(observation.get("name") or code)
    display = f"{name}（{code}）"
    if "financial" in kinds:
        financial = _financial_rows(facts)
        selected: list[Mapping[str, Any]] = []
        for candidate in (
            _first_financial_with_adjustment(facts, "revenue", adjusted=False),
            _first_financial_with_adjustment(facts, "gross profit", adjusted=False),
            _first_financial_with_adjustment(facts, *_STATUTORY_RESULT_TOKENS, adjusted=False),
            _first_financial_with_adjustment(facts, "adjusted net loss", "adjusted loss", "adjusted profit", adjusted=True),
        ):
            if candidate is not None and candidate not in selected:
                selected.append(candidate)
        selected.extend(fact for fact in financial if fact not in selected and len(selected) < 4)
        selected = selected[:4]
        revenue = _first_financial_with_adjustment(facts, "revenue", adjusted=False)
        gross = _first_financial_with_adjustment(facts, "gross profit", adjusted=False)
        statutory = _first_financial_with_adjustment(
            facts,
            *_STATUTORY_RESULT_TOKENS,
            adjusted=False,
        )
        adjusted = _first_financial_with_adjustment(
            facts,
            "adjusted net loss",
            "adjusted loss",
            "adjusted profit",
            adjusted=True,
        )
        summary_parts: list[str] = []
        if revenue is not None:
            summary_parts.append(_financial_summary_sentence(revenue))
        if gross is not None:
            summary_parts.append(_financial_summary_sentence(gross))
        if statutory is not None:
            summary_parts.append(_financial_summary_sentence(statutory, role="statutory"))
        if adjusted is not None:
            summary_parts.append(_financial_summary_sentence(adjusted, role="adjusted"))
        summary_labels = {_fact_label_cn(fact) for fact in (revenue, gross, statutory, adjusted) if fact is not None}
        # Once the principal operating/profit rows are present, keep
        # ancillary rows such as interest income out of the headline.  A
        # fallback row is useful only when a primary metric was genuinely not
        # found; the folded fact list still retains the complete bounded set.
        has_core_summary = revenue is not None and gross is not None and (statutory is not None or adjusted is not None)
        if not has_core_summary:
            for fact in selected:
                if len(summary_parts) >= 4:
                    break
                label = _fact_label_cn(fact)
                if fact not in (revenue, gross, statutory, adjusted) and label not in summary_labels:
                    summary_parts.append(_financial_summary_sentence(fact, role="fallback"))
                    summary_labels.add(label)
        period = _period_short(selected[0]) if selected else "公告报告期"
        if statutory is not None:
            _, stat_values = _financial_values(statutory)
            stat_column, _ = _comparison_columns(statutory)
            stat_number = _raw_decimal(stat_values.get(stat_column, ""))
            if stat_number is not None and stat_number < 0:
                meaning = "法定口径仍为亏损，收入或毛利改善尚未证明已经盈利"
            elif stat_number is not None:
                meaning = "法定口径已列示利润，仍需核对现金流与后续期间持续性"
            else:
                meaning = "法定利润/亏损数值无法解析，不能据此扩大结论"
        else:
            meaning = "公告未形成法定利润/亏损行，不能据收入或毛利直接推断盈利"
        if adjusted is not None:
            meaning += "；经调整口径仅作补充，不能替代法定口径"
        thesis = f"{display}：{period}{'；'.join(summary_parts)}。{meaning}。"
        inferences: list[str] = []
        if revenue is not None:
            values = _financial_value_map(revenue)
            change = values.get("Change (%)") or values.get("Change")
            current_column, _ = _comparison_columns(revenue)
            current = values.get(current_column) or next(iter(values.values()), "")
            if change:
                parsed_change = _raw_decimal(change)
                direction = "增加" if parsed_change is not None and parsed_change >= 0 else "减少" if parsed_change is not None else "未知方向"
                change_text = change if change.rstrip().endswith("%") else f"{change}%"
                inferences.append(f"收入行的公告披露同比原始值为{change_text}，本研究仅据该值记录为{direction}信号，当期数值为{current}。")
            else:
                current_column, previous_column = _comparison_columns(revenue)
                previous = values.get(previous_column, "") if previous_column else ""
                derived = _change_text(revenue, current, previous or None)
                if derived.startswith("同比约"):
                    inferences.append(
                        f"公告未直接披露同比，按同口径{current_column}/{previous_column}数值计算{derived}；该比较不能预测未来增长。"
                    )
                else:
                    inferences.append(f"收入行当期数值为{current}；公告未直接披露同比，不能预测未来增长。")
        if gross is not None and statutory is not None:
            gross_values = _financial_value_map(gross)
            loss_values = _financial_value_map(statutory)
            first_gross = next(iter(gross_values.values()), "")
            first_loss = next(iter(loss_values.values()), "")
            loss_negative = _raw_decimal(first_loss) is not None and (_raw_decimal(first_loss) or Decimal(0)) < 0
            inferences.append(
                f"同一财务表同时列出毛利{first_gross}与法定口径{'亏损' if loss_negative else '利润'}{first_loss}；收入/毛利改善不能直接推导为已盈利。"
            )
        elif statutory is None:
            inferences.append("当前公告未形成可复核的法定利润/亏损行；其他财务项目不能替代该口径。")
        if adjusted is not None and statutory is not None:
            adjusted_column, _ = _comparison_columns(adjusted)
            stat_column, _ = _comparison_columns(statutory)
            adjusted_values = _financial_value_map(adjusted)
            statutory_values = _financial_value_map(statutory)
            inferences.append(
                f"法定口径与经调整口径分别列为{statutory_values.get(stat_column, '')}和{adjusted_values.get(adjusted_column, '')}；经调整项目不替代法定结果。"
            )
        inferences.append("这些数字属于公告报告期，不能替代目标日盘面承接、订单、现金流或后续期间验证。")
        counter = [f"当前证据是单份公告的{period}数据，未证明后续期间能够维持同一口径。"]
        if statutory is None:
            counter.append("公告没有法定利润/亏损行，收入、毛利或其他财务项目不能单独支持盈利结论。")
        else:
            counter.append("若法定利润/亏损、费用或经营现金流未改善，收入增长也不能单独支持积极结论。")
        if adjusted is not None:
            counter.append("经调整口径与法定结果存在口径差异，调整项无法由当前摘要证明可持续。")
        confirm = [
            "复核下一期同币种、同单位、同列顺序的收入、毛利与利润/亏损行，并核对公告页码。",
            "补查经营现金流、应收账款及订单/客户兑现证据，再观察阶段价格承接是否持续。",
        ]
        invalid = [
            "若下一期收入或毛利按同口径转弱，或公告披露同比与当前方向相反，则撤回经营改善判断。",
            "若法定亏损扩大、经营现金流恶化或关键数字无法由官方原文复核，保持不可确认。",
        ]
        return {
            "thesis_cn": thesis,
            "inferences_cn": inferences[:4],
            "counterevidence_cn": counter,
            "confirmation_conditions": confirm,
            "invalidation_conditions": invalid,
        }
    if "dividend" in kinds:
        dividend = [fact for fact in facts if fact.get("fact_kind") == "dividend"]
        detail = "；".join(str(fact["statement_cn"]).rstrip("。") for fact in dividend[:4])
        thesis = f"{display}：官方公告正文确认股息与登记/派付安排：{detail}。"
        amount = next((_fact_value(fact, "value_raw") for fact in dividend if _fact_value(fact, "field") == "dividend_declared"), "")
        inferences = [
            f"公告股息字段的原始值为{amount or '未提供'}；除息、登记和派付日期按原文分别保留，不能改写为目标日收益。",
            "股息安排是公司分配事项，未提供经营利润、现金流或除息后价格承接的完整证据。",
        ]
        return {
            "thesis_cn": thesis,
            "inferences_cn": inferences,
            "counterevidence_cn": [
                "股息金额和日期不等同于经营改善，也不能证明除息后价格不会回落。",
                "当前公告未单独证明派息资金来源、持续性或下一期盈利兑现。",
            ],
            "confirmation_conditions": [
                "核对同一公告的报告期、派息资格和实际派付状态，并复核后续财务现金流。",
                "观察除息后成交与阶段承接，再与下一期利润和现金流口径交叉验证。",
            ],
            "invalidation_conditions": [
                "若登记/派付安排变更、取消或原文日期无法复核，则撤回该股息事实。",
                "若下一期盈利或现金流恶化、或除息后承接明显失效，保持暂不买入。",
            ],
        }
    if "egm_resolution" in kinds:
        resolutions = [fact for fact in facts if fact.get("fact_kind") == "egm_resolution"]
        detail = "；".join(str(fact["statement_cn"]).rstrip("。") for fact in resolutions)
        thesis = f"{display}：官方股东会文件可读到以下待审议事项：{detail}。"
        return {
            "thesis_cn": thesis,
            "inferences_cn": [
                "文件记录的是股东会决议议题及其类别，说明治理或资金安排进入审议流程，不代表已经通过或执行。",
                "注册资本/章程变更与现金管理额度议题本身没有提供收入、利润或现金流改善数值。",
            ],
            "counterevidence_cn": [
                "决议需要结合股东会结果、登记变更和后续公告核验，议题标题不能算已完成事项。",
                "提高现金管理额度不等同于主营经营改善，资金运用与风险边界仍未知。",
            ],
            "confirmation_conditions": [
                "复核股东会表决结果、注册资本/章程登记及后续执行公告，并保留对应页码。",
                "核对现金管理实际余额、期限、收益及主营现金流，再观察同日阶段承接。",
            ],
            "invalidation_conditions": [
                "若议案未获通过、登记未完成或后续公告否定原议题，则撤回相应推断。",
                "若资金安排出现违约、损失或无法复核执行状态，保持不可确认。",
            ],
        }
    if "business" in kinds:
        business = [fact for fact in facts if fact.get("fact_kind") == "business"]
        detail = "；".join(str(fact["statement_cn"]).rstrip("。") for fact in business[:3])
        return {
            "thesis_cn": f"{display}：官方经营段落提供以下可读事实：{detail}。",
            "inferences_cn": [
                "经营段落中的收入、规模或产品字段是公司自述指标，需与财务表和后续兑现核对。",
                "阶段观察只能说明目标时点的盘面变化，不能把公告段落直接转成买入结论。",
            ],
            "counterevidence_cn": [
                "经营描述未必包含利润率、现金流、订单质量和客户集中度，仍存在基本面反证。",
                "单份公告和单个产品/规模字段不能证明持续增长或目标日后的价格承接。",
            ],
            "confirmation_conditions": [
                "将经营字段与下一期同口径收入、利润、现金流和客户/订单披露交叉核对。",
                "继续观察同一阶段观察口径下的承接与波动，并复核原文页码和发布时间。",
            ],
            "invalidation_conditions": [
                "若后续财务数据无法印证经营段落，或客户/产品指标回落，则撤回改善推断。",
                "若原文正文不可复核、发布时间越过截止点或来源身份不一致，降级为不可确认。",
            ],
        }
    return {
        "thesis_cn": "官方来源虽已返回，但没有形成可用结构化正文事实，不能写成公司深研。",
        "inferences_cn": [],
        "counterevidence_cn": [],
        "confirmation_conditions": [],
        "invalidation_conditions": [],
    }

def _financial_counterevidence_for_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Re-evaluate persisted facts for the event card without collecting finance.

    Catalyst refreshes must make the financial boundary visible, while the
    existing official facts and source receipt remain the only inputs.  This
    helper intentionally has no provider dependency and reports its zero
    recollection boundary in the returned metadata.
    """

    raw_facts = row.get("facts")
    facts = [item for item in raw_facts if isinstance(item, Mapping)] if isinstance(raw_facts, list) else []
    source = row.get("source") if isinstance(row.get("source"), Mapping) else None
    observation = row.get("observation") if isinstance(row.get("observation"), Mapping) else {}
    evidence = extract_financial_evidence(facts, source)
    existing = row.get("research_recommendation") if isinstance(row.get("research_recommendation"), Mapping) else {}
    existing_advice = existing.get("investment_advice") if isinstance(existing.get("investment_advice"), Mapping) else {}
    timing = str(existing.get("timing_status") or row.get("observation_timing_status") or "CUTOFF_UNCONFIRMED")
    advice = derive_investment_advice(
        evidence,
        observation,
        timing,
        source_status=str(row.get("source_status") or "READY"),
        source_reason=str(row.get("source_reason") or "") or None,
        source_available=source is not None,
    )
    dimensions = evidence.get("dimensions") if isinstance(evidence.get("dimensions"), Mapping) else {}
    counterevidence: list[str] = []
    refs: list[dict[str, Any]] = []
    for name, item in dimensions.items():
        if not isinstance(item, Mapping):
            continue
        state = str(item.get("state") or "")
        if state not in {"NEGATIVE", "MIXED", "CONFLICT"}:
            continue
        dimension = str(name).upper()
        current = item.get("current") or "CANNOT_CONFIRM"
        previous = item.get("previous") or "CANNOT_CONFIRM"
        period = item.get("period") or "CANNOT_CONFIRM_PERIOD"
        if state == "CONFLICT":
            counterevidence.append(f"证据冲突：{dimension} 存在不同值/币种/单位（{period}），不得按正向信号消费。")
        elif state == "MIXED":
            counterevidence.append(f"口径信号转弱：{dimension} 当前={current}、前期={previous}（{period}）。")
        else:
            counterevidence.append(f"已确认财务反证：{dimension} 当前={current}、前期={previous}（{period}）。")
        refs.append(
            {
                "dimension": dimension,
                "state": state,
                "current": item.get("current"),
                "previous": item.get("previous"),
                "period": item.get("period"),
                "currency": item.get("currency"),
                "unit": item.get("unit"),
                "fact_refs": list(item.get("fact_refs") or []),
            }
        )
    missing = [str(value) for value in advice.get("missing_dimensions", []) if isinstance(value, str)]
    market_missing = any(value in {"PRICE_PIT_UNAVAILABLE", "price", "volume", "volume_ratio", "support", "pressure"} for value in missing)
    reevaluation = {
        "status": advice.get("status"),
        "action": advice.get("action"),
        "label_cn": advice.get("label_cn"),
        "evidence_grade": evidence.get("evidence_grade"),
        "reason": advice.get("reason"),
        "missing_dimensions": missing,
        "fact_count": evidence.get("fact_count", len(facts)),
        "source_sha256": source.get("sha256") if source else None,
        "financial_collection_calls": 0,
        "from_cached_facts": True,
        "existing_recommendation_action": existing_advice.get("action") if isinstance(existing_advice, Mapping) else None,
    }
    return {
        "financial_counterevidence": list(dict.fromkeys(counterevidence)),
        "financial_counterevidence_refs": refs,
        "financial_re_evaluation": reevaluation,
        "market_price_volume_unconfirmed": market_missing,
    }
