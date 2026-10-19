"""Frozen, research-only V1 US-to-HK strict recommendation selector."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime
import hashlib
import json
import re

from .common import current, hk_symbol, valid_sha
from .us_factor import _return_pct
from .us_mapping_consumption import manual_quote_for_symbol

RULES_VERSION = "STRICT_US_SELECTION_V1_20261019"
SINGLE_DAY_MAPPING_VERSION = "US_HK_SINGLE_DAY_MAPPING_V1_20261019"
MAPPING_POLICY_VERSION = "STRICT_US_SELECTION_MAPPING_V1_20261019"
MAPPING_POLICY_SHA256 = "43849d9090a9f1632ba5042544810f62855293859fcf6dff67f4c7b8e95cc1ac"
BASIC_UNIT_CHECK_SHA256 = "6118718612b3be075d7757e37874564ca7fa09b35dddfca2f6c943aacbfc0d03"

AMOUNT_UNIT_STATUS = "SOURCE_SCALE_CHECKED"
AMOUNT_FIELD = "amount"
AMOUNT_SCALE = Decimal("1")
MIN_PROXY_RETURN = Decimal("1")
MIN_MEAN_TURNOVER20_HKD = Decimal("20000000")
MAX_CLOSE_TO_MA20 = Decimal("1.1")
MAX_RETURN5 = Decimal("15")
MAX_SELECTED = 10
MAX_PER_PRIMARY_THEME = 3
AGGREGATE_TOLERANCE_PP = Decimal("0.001")

RELATIONSHIP_A = frozenset((
    "NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER",
    "NAMED_CLOUD_CONNECTIVITY_PARTNERSHIP",
    "NAMED_COMPONENT_OPTION",
    "CO_DESIGNED_PRODUCT_PARTNERSHIP",
))
C_RELATIONSHIP_TYPES = frozenset(("INDIRECT_STRATEGIC_PLATFORM_COLLABORATION",))

# The key is the exact provider industry label; ordering is part of the frozen
# primary-selection rule and is consulted before any return is read.
B_INDUSTRY_PATHS = (
    ("药品及生物科技", "XBI", "生物医药"),
    ("半导体", "SOXX", "半导体"),
    ("银行", "KBE", "银行金融"),
    ("黄金及贵金属", "GLD", "黄金"),
    ("石油及天然气", "XLE", "能源"),
)
INDUSTRY_PATHS = {label: (proxy, theme) for label, proxy, theme in B_INDUSTRY_PATHS}
INDUSTRY_SECONDARY_PATHS = {"石油及天然气": (("FCG", "能源"),)}

# Primary-theme caps group direct A relations and B proxies by the same fixed
# economic theme. Unlisted A sources remain visible as unassessed mappings.
US_SYMBOL_THEMES = {
    "NVDA": "半导体", "AMD": "半导体", "SOXX": "半导体",
    "STX": "存储",
    "VRT": "数据中心", "EQIX": "数据中心", "DLR": "数据中心",
    "XBI": "生物医药", "KBE": "银行金融", "GLD": "黄金",
    "XLE": "能源", "FCG": "能源",
}

_RULES = {
    "rules_version": RULES_VERSION,
    "mapping_policy_version": MAPPING_POLICY_VERSION,
    "mapping_policy_sha256": MAPPING_POLICY_SHA256,
    "basic_unit_check_sha256": BASIC_UNIT_CHECK_SHA256,
    "proxy_return_pct_min": "1",
    "previous_close_gte_ma20": True,
    "close_to_ma20_max": "1.1",
    "return5_pct_max": "15",
    "mean_turnover20_hkd_min": "20000000",
    "amount_field": AMOUNT_FIELD,
    "amount_scale": "1",
    "amount_unit_status": AMOUNT_UNIT_STATUS,
    "known_suspension_excluded": True,
    "unknown_suspension": "RISK_ONLY",
    "max_selected": MAX_SELECTED,
    "max_per_primary_theme": MAX_PER_PRIMARY_THEME,
    "mapping_grade_order": ["A", "B"],
    "primary_a_order": "us_symbol_ascending",
    "primary_b_order": [row[0] for row in B_INDUSTRY_PATHS],
    "conflict_secondary_signed_return_pct_max": "-1",
    "conflict_requires_primary_signed_return_pct_min": "1",
    "historical_pit_verified": False,
    "research_effectiveness": "RESEARCH_RULE_RECOMMENDATION_EFFECT_UNVERIFIED",
    "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False},
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")


RULES_SHA256 = hashlib.sha256(_canonical(_RULES)).hexdigest()


def cannot_confirm_summary(context, reason):
    context = context if isinstance(context, dict) else {}
    sessions = context.get("source_sessions") or {}
    return dict(display_only=True, state="CANNOT_CONFIRM", rules_version=RULES_VERSION,
        rules_sha256=RULES_SHA256, mapping_policy_version=MAPPING_POLICY_VERSION,
        mapping_policy_sha256=MAPPING_POLICY_SHA256, basic_unit_check_sha256=BASIC_UNIT_CHECK_SHA256,
        target_date=context.get("target_date"), price_session=sessions.get("hk_price"),
        source_session=sessions.get("us"), monthly_observed_scope_count=None,
        observed_count=None, selected_count=None, rows=[], selected=[], funnel={},
        gaps=[reason], historical_pit_verified=False,
        research_effectiveness="RESEARCH_RULE_RECOMMENDATION_EFFECT_UNVERIFIED",
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def _decimal(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _decimal_text(value):
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _date_token(value):
    if not isinstance(value, str):
        return None
    token = value.replace("-", "")[:8]
    if re.fullmatch(r"\d{8}", token) is None:
        return None
    try:
        from datetime import date
        parsed = date.fromisoformat(f"{token[:4]}-{token[4:6]}-{token[6:]}")
        return parsed.strftime("%Y%m%d")
    except ValueError:
        return None


def _post_open_state(context):
    try:
        cutoff = datetime.fromisoformat(str(context.get("cutoff")).replace("Z", "+00:00"))
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError
        open_at = datetime.fromisoformat(f"{context['target_date'][:4]}-{context['target_date'][4:6]}-{context['target_date'][6:]}T09:30:00+08:00")
    except (TypeError, ValueError, KeyError):
        return "CANNOT_CONFIRM", "HK_OPENING_CUTOFF_INVALID"
    if cutoff < open_at:
        return "PENDING_OPEN", "HK_OPEN_NOT_YET_OCCURRED_AT_CUTOFF"
    return "CANNOT_CONFIRM", "HK_OPENING_DATA_OWNER_NOT_BOUND_AT_CUTOFF"


def _source_quote_path(row, expected_session, context):
    us_symbol = row.get("us_symbol")
    relation_type = row.get("relation_type")
    theme = US_SYMBOL_THEMES.get(us_symbol)
    gaps = []
    if relation_type not in RELATIONSHIP_A:
        gaps.append("RELATIONSHIP_NOT_FROZEN_A")
    if row.get("relation_status") != "REVIEWED":
        gaps.append("RELATIONSHIP_NOT_REVIEWED")
    if not theme:
        gaps.append("PRIMARY_THEME_UNMAPPED")
    if row.get("relation_pit_status") == "PIT_UNCONFIRMED":
        gaps.append("RELATIONSHIP_PIT_UNCONFIRMED")
    if row.get("publication_time_gaps"):
        gaps.append("RELATIONSHIP_PUBLICATION_TIME_UNVERIFIED")
    diagnostic = row.get("diagnostic_gaps") if isinstance(row.get("diagnostic_gaps"), list) else []
    allowed_membership_gaps = {"CONNECT_MEMBERSHIP_UNKNOWN", "TARGET_NOT_IN_CURRENT_CONNECT_MEMBERSHIP"}
    unexpected = [value for value in diagnostic if value not in allowed_membership_gaps]
    if unexpected:
        gaps.append("RELATIONSHIP_SOURCE_OR_REVIEW_GATE_UNVERIFIED")
    if row.get("decision") == "UNASSESSED" and not diagnostic:
        gaps.append("RELATIONSHIP_SOURCE_OR_REVIEW_GATE_UNVERIFIED")
    if (not row.get("owner") or not valid_sha(row.get("source_sha256"))
            or not current(context, row.get("available_at"))
            or row.get("source_session") != expected_session):
        gaps.append("US_QUOTE_SOURCE_IDENTITY_OR_TIME_UNVERIFIED")
    try:
        value = _return_pct(row.get("quote"), expected_session)
    except (ValueError, TypeError, InvalidOperation, KeyError):
        value = None
        gaps.append("US_QUOTE_RETURN_UNVERIFIED")
    if value is None:
        gaps.append("US_QUOTE_RETURN_UNVERIFIED")
    path = dict(grade="A", source_type="REVIEWED_DIRECT_RELATION",
        us_symbol=us_symbol, relation_type=relation_type, proxy_symbol=us_symbol,
        primary_theme=theme, sign=1, return_pct=_decimal_text(value),
        signed_return_pct=_decimal_text(value), status="VERIFIED" if not gaps else "UNASSESSED",
        reason=None if not gaps else gaps[0], gaps=list(dict.fromkeys(gaps)),
        source_sha256=row.get("source_sha256"), owner=row.get("owner"),
        source_session=row.get("source_session"), available_at=row.get("available_at"),
        relation_pit_status=row.get("relation_pit_status"),
        relation_source_refs=row.get("relation_source_refs") or [])
    return path


def _industry_paths(row, expected_session, context):
    label = row.get("source_industry")
    if label not in INDUSTRY_PATHS:
        return []
    primary_proxy, theme = INDUSTRY_PATHS[label]
    all_paths = [(primary_proxy, theme, True)] + [
        (proxy, secondary_theme, False)
        for proxy, secondary_theme in INDUSTRY_SECONDARY_PATHS.get(label, ())]
    existing = row.get("proxy_paths") if isinstance(row.get("proxy_paths"), list) else []
    paths = []
    for proxy_symbol, path_theme, primary in all_paths:
        matches = [item for item in existing if isinstance(item, dict)
            and item.get("proxy_symbols") == [proxy_symbol]
            and item.get("source_session") == expected_session]
        gaps = []
        identity_gap = row.get("identity_status") != "VERIFIED"
        if identity_gap:
            gaps.append("HK_INDUSTRY_SECURITY_IDENTITY_UNVERIFIED")
        if not current(context, row.get("available_at")):
            gaps.append("HK_INDUSTRY_CLASSIFICATION_TIME_UNVERIFIED")
        if len(matches) != 1:
            gaps.append("HK_INDUSTRY_PROXY_PATH_MISSING_OR_DUPLICATE")
            match = None
        else:
            match = matches[0]
        if match is not None:
            if match.get("status") != "VERIFIED":
                gaps.append(match.get("reason") or "HK_INDUSTRY_PROXY_RETURN_UNVERIFIED")
            value = _decimal(match.get("return_pct"))
            if value is None:
                gaps.append("HK_INDUSTRY_PROXY_RETURN_INVALID")
            if not isinstance(match.get("source_sha256"), str) or not valid_sha(match.get("source_sha256")):
                gaps.append("HK_INDUSTRY_PROXY_SOURCE_SHA_UNVERIFIED")
            if not current(context, match.get("available_at")):
                gaps.append("HK_INDUSTRY_PROXY_SOURCE_TIME_UNVERIFIED")
        else:
            value = None
        paths.append(dict(grade="B", source_type="FROZEN_SUBINDUSTRY",
            source_industry=label, proxy_symbol=proxy_symbol, proxy_theme=path_theme,
            primary_theme=theme, primary_path=primary, sign=1,
            return_pct=_decimal_text(value), signed_return_pct=_decimal_text(value),
            status="VERIFIED" if not gaps else "UNASSESSED",
            reason=None if not gaps else gaps[0], gaps=list(dict.fromkeys(gaps)),
            owner=(match or {}).get("owner"), source_sha256=(match or {}).get("source_sha256"),
            source_session=(match or {}).get("source_session"),
            available_at=(match or {}).get("available_at"),
            classification_sha256=row.get("source_artifact_sha256"),
            classification_row_sha256=row.get("source_row_sha256")))
    return paths


def _metrics(history, close_sessions, amount_sessions):
    bars = history.get("bars") if isinstance(history, dict) else None
    if not isinstance(bars, list):
        return None, ["HK_HISTORY_ROWS_MISSING"]
    by_date = {}
    duplicates = set()
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        day = _date_token(bar.get("date"))
        if day is None:
            continue
        if day in by_date:
            duplicates.add(day)
        else:
            by_date[day] = bar
    if duplicates:
        return None, ["HK_HISTORY_DUPLICATE_SESSION"]
    gaps = []
    missing_close = [day for day in close_sessions if day not in by_date]
    missing_amount = [day for day in amount_sessions if day not in by_date]
    if missing_close:
        gaps.append("HK_CLOSE_21_SESSION_WINDOW_INCOMPLETE")
    if missing_amount:
        gaps.append("HK_AMOUNT_20_SESSION_WINDOW_INCOMPLETE")
    holds = history.get("history_holds") if isinstance(history, dict) else None
    if holds:
        gaps.append("HK_HISTORY_FIELD_QUARANTINED")
    if gaps:
        return None, gaps
    close_raw = [by_date[day].get("close") for day in close_sessions]
    amount_raw = [by_date[day].get("amount") for day in amount_sessions]
    if any(value is None for value in close_raw):
        gaps.append("HK_CLOSE_FIELD_MISSING")
    if any(value is None for value in amount_raw):
        gaps.append("HK_AMOUNT_FIELD_MISSING")
    if gaps:
        return None, gaps
    closes = [_decimal(value) for value in close_raw]
    amounts = [_decimal(value) for value in amount_raw]
    if any(value is None or value <= 0 for value in closes):
        gaps.append("HK_CLOSE_NONFINITE_OR_NONPOSITIVE")
    if any(value is None or value < 0 for value in amounts):
        gaps.append("HK_AMOUNT_NONFINITE_OR_NEGATIVE")
    if gaps:
        return None, gaps
    close = closes[-1]
    previous_close = closes[-1]
    ma20 = sum(closes[-20:], Decimal(0)) / Decimal(20)
    return5 = (close / closes[-6] - Decimal(1)) * Decimal(100)
    turnover20 = sum(amounts, Decimal(0)) / Decimal(20) * AMOUNT_SCALE
    suspended_value = by_date[close_sessions[-1]].get("suspended")
    suspended = suspended_value if isinstance(suspended_value, bool) else None
    return dict(hk_previous_close=_decimal_text(previous_close),
        hk_close=_decimal_text(close), hk_ma20=_decimal_text(ma20),
        hk_close_to_ma20=_decimal_text(close / ma20),
        hk_return_5_sessions_pct=_decimal_text(return5),
        hk_mean_turnover20_hkd=_decimal_text(turnover20),
        suspension_status="SUSPENDED" if suspended is True else
            "NOT_SUSPENDED" if suspended is False else "UNKNOWN"), []


def _mapping_path_order(path):
    grade = path.get("grade")
    if grade == "A":
        return (0, path.get("us_symbol", ""))
    if grade == "B":
        industry_rank = next((i for i, item in enumerate(B_INDUSTRY_PATHS)
            if item[0] == path.get("source_industry")), 99)
        return (1, industry_rank, 0 if path.get("primary_path") else 1,
            path.get("proxy_symbol", ""))
    return (2, path.get("proxy_symbol") or "")


def _catalog_stock_identity_map(stock_identities):
    if not isinstance(stock_identities, list):
        return None, 0, 0
    identities = {}
    invalid_count = 0
    duplicate_count = 0
    for item in stock_identities:
        if not isinstance(item, dict):
            invalid_count += 1
            continue
        raw_symbol = item.get("symbol") or item.get("target_symbol") or item.get("hk_code")
        text = str(raw_symbol or "")
        if not hk_symbol(text) and re.fullmatch(r"\d{1,5}", text):
            text = "HK." + text.zfill(5)
        if not hk_symbol(text):
            invalid_count += 1
            continue
        if text in identities:
            duplicate_count += 1
            continue
        name = item.get("name") or item.get("hk_name")
        identities[text] = name if isinstance(name, str) else None
    return identities, invalid_count, duplicate_count


def _mapping_index(relation_rows, industry_rows, expected_session, context):
    candidates = {}
    for row in relation_rows:
        if not isinstance(row, dict) or not hk_symbol(row.get("symbol")):
            continue
        if row.get("relation_type") not in RELATIONSHIP_A:
            continue
        path = _source_quote_path(row, expected_session, context)
        candidates.setdefault(row["symbol"], []).append(path)
    industry_by_symbol = {}
    for row in industry_rows:
        if not isinstance(row, dict) or not hk_symbol(row.get("symbol")):
            continue
        if row["symbol"] in industry_by_symbol:
            industry_by_symbol[row["symbol"]] = None
        else:
            industry_by_symbol[row["symbol"]] = row
    for symbol, row in industry_by_symbol.items():
        if isinstance(row, dict):
            candidates.setdefault(symbol, []).extend(_industry_paths(row, expected_session, context))
    for symbol in list(candidates):
        seen = {}
        duplicate = False
        for path in candidates[symbol]:
            identity = (path.get("grade"), path.get("us_symbol"), path.get("relation_type"), path.get("proxy_symbol"))
            if identity in seen and seen[identity] != path:
                duplicate = True
            seen[identity] = path
        if duplicate:
            for path in candidates[symbol]:
                path["status"] = "UNASSESSED"
                path["reason"] = "DUPLICATE_MAPPING_PATH_CONFLICT"
                path["gaps"] = list(dict.fromkeys([*(path.get("gaps") or []), "DUPLICATE_MAPPING_PATH_CONFLICT"]))
        candidates[symbol].sort(key=_mapping_path_order)
    return candidates, industry_by_symbol


def _single_day_c_relation_path(row, expected_session, context):
    """Preserve non-A relationship evidence as C observation, never as A."""
    path = _source_quote_path(row, expected_session, context)
    gaps = [gap for gap in path["gaps"] if gap not in {
        "RELATIONSHIP_NOT_FROZEN_A", "PRIMARY_THEME_UNMAPPED"}]
    path.update(grade="C", source_type="C_RELATIONSHIP_OBSERVATION",
        primary_theme=None, primary_path=False,
        status="VERIFIED" if not gaps else "UNASSESSED",
        reason=None if not gaps else gaps[0], gaps=gaps,
        observation_only=True,
        research_basis=row.get("research_basis"),
        relation_limitations=row.get("relation_limitations") or [],
        relation_status=row.get("relation_status"),
        relation_source_refs=row.get("relation_source_refs") or [],
        diagnostic_gaps=row.get("diagnostic_gaps") or [])
    return path


_SINGLE_DAY_BROAD_SECTOR = {
    "公用事业": [(("XLU",), "公用事业")],
    "保险": [(("KIE",), "保险")],
    "食物饮品": [(("XLP",), "消费必需品")],
    "消费者主要零售商": [(("XLP",), "消费必需品")],
    "专业零售": [(("XLY",), "可选消费")],
    "汽车": [(("XLY",), "可选消费")],
    "旅游及消闲设施": [(("XLY",), "可选消费")],
    "家庭电器及用品": [(("XLY", "XLP"), "广义消费观察")],
    "纺织及服饰": [(("XLY", "XLP"), "广义消费观察")],
    "药品及生物科技": [(("XBI",), "生物医药")],
    "半导体": [(("SOXX",), "半导体")],
    "银行": [(("KBE",), "银行金融")],
    "黄金及贵金属": [(("GLD",), "黄金")],
    "石油及天然气": [(("XLE",), "石油"), (("FCG",), "天然气")],
}


def _single_day_broad_c_paths(row, expected_session, context, manual_quote_scope):
    if not isinstance(row, dict):
        return []
    specs = _SINGLE_DAY_BROAD_SECTOR.get(row.get("source_industry"))
    if not specs:
        return []
    paths = []
    for expected_symbols, theme in specs:
        valid_quotes = []
        missing_symbols = []
        for symbol in expected_symbols:
            quote, gap = manual_quote_for_symbol(manual_quote_scope, symbol,
                expected_session, context.get("cutoff"))
            value = _decimal(quote.get("change_pct")) if quote else None
            if value is None:
                missing_symbols.append(dict(symbol=symbol, reason=gap or "MANUAL_QUOTE_RETURN_INVALID"))
            else:
                valid_quotes.append((symbol, value))
        gaps = []
        identity_gap = row.get("identity_status") != "VERIFIED"
        if identity_gap:
            gaps.append("HK_INDUSTRY_SECURITY_IDENTITY_UNVERIFIED")
        if missing_symbols:
            gaps.append("SECTOR_BASELINE_MEMBER_QUOTES_PARTIAL" if valid_quotes else "SECTOR_BASELINE_QUOTES_UNAVAILABLE")
        value = (sum((item[1] for item in valid_quotes), Decimal(0)) / Decimal(len(valid_quotes))
            if valid_quotes else None)
        reason = ("BROAD_SECTOR_BASELINE_ONLY_NO_HK_SIGN" if value is not None and not missing_symbols
            else "SECTOR_BASELINE_MEMBER_QUOTES_PARTIAL" if value is not None
            else (missing_symbols[0]["reason"] if missing_symbols else "SECTOR_BASELINE_QUOTES_UNAVAILABLE"))
        paths.append(dict(grade="C", source_type="BROAD_SECTOR_BACKGROUND",
            source_industry=row.get("source_industry"), proxy_symbols=list(expected_symbols),
            proxy_symbol=" + ".join(expected_symbols),
            primary_theme=None, primary_path=False, sign=None,
            return_pct=_decimal_text(value), signed_return_pct=None,
            source_return_pct=_decimal_text(value),
            status=("UNASSESSED" if identity_gap or not valid_quotes else
                "PARTIAL" if missing_symbols else "VERIFIED"),
            reason=reason if not gaps else gaps[0],
            gaps=list(dict.fromkeys(gaps)), owner=(manual_quote_scope or {}).get("owner"),
            source_sha256=(manual_quote_scope or {}).get("payload_sha256"),
            receipt_sha256=(manual_quote_scope or {}).get("receipt_sha256"),
            manifest_sha256=(manual_quote_scope or {}).get("manifest_sha256"),
            scope_sha256=(manual_quote_scope or {}).get("scope_sha256"),
            source_session=expected_session,
            available_at=(manual_quote_scope or {}).get("available_at"),
            declared_count=len(expected_symbols), valid_count=len(valid_quotes),
            missing_symbols=missing_symbols, members=[{"symbol": symbol,
                "source_return_pct": _decimal_text(member_value)} for symbol, member_value in valid_quotes],
            observation_only=True))
    return paths


def cannot_confirm_single_day_mapping(context, reason):
    context = context if isinstance(context, dict) else {}
    sessions = context.get("source_sessions") or {}
    return dict(display_only=True, state="CANNOT_CONFIRM",
        rules_version=SINGLE_DAY_MAPPING_VERSION, mapping_policy_version=MAPPING_POLICY_VERSION,
        mapping_policy_sha256=MAPPING_POLICY_SHA256, target_date=context.get("target_date"),
        price_session=sessions.get("hk_price"), source_session=sessions.get("us"),
        monthly_observed_scope_count=None, counts={key: None for key in
            ("BENEFIT", "RISK", "CONFLICT", "OBSERVATION", "SMALL_MOVE_WATCH",
                "C_WATCH", "UNMAPPED", "UNASSESSED")},
        rows=[], outside_pool_observations=[], gaps=[reason],
        strict_v1_status="PAUSED_NOT_EXECUTED", historical_pit_verified=False,
        deferred_gates=["HK_MA20", "HK_RETURN5", "HK_TURNOVER20", "TOP10", "THEME3"],
        formal_target_eligibility="CANNOT_CONFIRM", research_effectiveness="UNVERIFIED",
        RESEARCH_ONLY=True,
        production_allowed=False, buy_gate_updated=False, orders_sent=False)


def run_single_day_mapping(context, *, relation_rows, industry_rows, factor_summary, membership,
                           catalog_rows=None, catalog_stock_identities=None,
                           catalog_expected_stock_count=None, manual_quote_scope=None):
    """Display the frozen US 20261016 -> HK 20261020 mapping without HK history gates."""
    context = context if isinstance(context, dict) else {}
    sessions = context.get("source_sessions") or {}
    expected_session = sessions.get("us") or sessions.get("US")
    price_session = sessions.get("hk_price") or sessions.get("HK_PRICE")
    if (context.get("target_date") != "20261020" or expected_session != "20261016"
            or price_session != "20261016" or context.get("phase") not in ("MANUAL", "NEXT_DAY")):
        return cannot_confirm_single_day_mapping(context, "SINGLE_DAY_DATE_OR_PHASE_BINDING_MISMATCH")
    membership = membership if isinstance(membership, dict) else {}
    codes = membership.get("codes")
    if (membership.get("status") != "VERIFIED" or membership.get("market") != "HK_CONNECT"
            or membership.get("owner") != "FUTU_HKCONNECT_PLATE_MEMBERSHIP"
            or membership.get("target_month") != "202610"
            or _date_token(membership.get("source_date")) != membership.get("source_date")
            or membership.get("source_date", "")[:6] != "202610"
            or membership.get("source_date", "") > "20261020"
            or not valid_sha(membership.get("artifact_sha256"))
            or not isinstance(codes, list) or not codes
            or len(codes) != len(set(codes)) or not all(hk_symbol(code) for code in codes)):
        return cannot_confirm_single_day_mapping(context, "MONTHLY_RESEARCH_UNIVERSE_IDENTITY_INVALID")
    expected_codes_sha = hashlib.sha256(_canonical(
        {"market": "HK_CONNECT", "codes": sorted(codes)})).hexdigest()
    if membership.get("codes_sha256") != expected_codes_sha:
        return cannot_confirm_single_day_mapping(context, "MONTHLY_RESEARCH_UNIVERSE_HASH_INVALID")

    relation_rows = relation_rows if isinstance(relation_rows, list) else []
    industry_rows = industry_rows if isinstance(industry_rows, list) else []
    catalog_rows = catalog_rows if isinstance(catalog_rows, list) else []
    from .us_mapping_consumption import (
        build_peer_baskets, catalog_consumption_summary, project_catalog_relation,
    )
    catalog_projection = [project_catalog_relation(item, manual_binding=manual_quote_scope,
        expected_session=expected_session, cutoff=context.get("cutoff"))
        for item in catalog_rows if isinstance(item, dict)]
    catalog_summary = catalog_consumption_summary(catalog_projection)
    catalog_peer_baskets = build_peer_baskets(catalog_projection)
    relation_targets = sorted({row.get("symbol") for row in catalog_projection
        if isinstance(row.get("symbol"), str) and row.get("symbol")})
    catalog_identity_map, invalid_identity_count, duplicate_identity_count = _catalog_stock_identity_map(
        catalog_stock_identities)
    catalog_identity_gaps = []
    if catalog_identity_map is None:
        if catalog_expected_stock_count is not None:
            catalog_identity_gaps.append("SINGLE_DAY_CATALOG_STOCK_IDENTITIES_UNAVAILABLE")
    else:
        if invalid_identity_count:
            catalog_identity_gaps.append("SINGLE_DAY_CATALOG_STOCK_IDENTITY_INVALID")
        if duplicate_identity_count:
            catalog_identity_gaps.append("SINGLE_DAY_CATALOG_STOCK_IDENTITY_DUPLICATE")
        if (isinstance(catalog_expected_stock_count, int)
                and not isinstance(catalog_expected_stock_count, bool)
                and len(catalog_identity_map) != catalog_expected_stock_count):
            catalog_identity_gaps.append("SINGLE_DAY_CATALOG_STOCK_IDENTITY_COUNT_MISMATCH")
    catalog_targets = sorted(catalog_identity_map) if catalog_identity_map is not None else []
    catalog_target_set = set(catalog_targets)
    relation_target_set = set(relation_targets)
    no_relation_stocks = ([dict(symbol=target, name=catalog_identity_map[target])
        for target in catalog_targets if target not in relation_target_set]
        if catalog_identity_map is not None else [])
    pool_targets = set(codes)
    catalog_stock_reconciliation = {
        "catalog_stock_identity_state": ("READY" if catalog_identity_map is not None and not catalog_identity_gaps
            else "PARTIAL" if catalog_identity_map is not None else "CANNOT_CONFIRM"),
        "expected_catalog_stock_count": catalog_expected_stock_count,
        "catalog_stock_count": len(catalog_targets) if catalog_identity_map is not None else None,
        "relation_target_stock_count": len(relation_targets),
        "catalog_stock_with_relation_count": (len(catalog_target_set & relation_target_set)
            if catalog_identity_map is not None else None),
        "no_relation_stock_count": len(no_relation_stocks) if catalog_identity_map is not None else None,
        "no_relation_stocks": no_relation_stocks,
        "catalog_stock_identity_invalid_count": invalid_identity_count,
        "catalog_stock_identity_duplicate_count": duplicate_identity_count,
        "relation_target_not_in_catalog_stock_count": (len(relation_target_set - catalog_target_set)
            if catalog_identity_map is not None else None),
        "monthly_pool_stock_count": len(pool_targets),
        "in_monthly_pool_stock_count": (len(pool_targets & catalog_target_set)
            if catalog_identity_map is not None else None),
        "outside_monthly_pool_stock_count": (len(catalog_target_set - pool_targets)
            if catalog_identity_map is not None else None),
        "outside_monthly_pool_stock_symbols": ([symbol for symbol in catalog_targets if symbol not in pool_targets]
            if catalog_identity_map is not None else []),
        "monthly_pool_not_in_catalog_stock_count": (len(pool_targets - catalog_target_set)
            if catalog_identity_map is not None else None),
        "monthly_pool_not_in_catalog_stock_symbols": (sorted(pool_targets - catalog_target_set)
            if catalog_identity_map is not None else []),
        "target_identity_missing_relation_count": sum(not row.get("symbol") for row in catalog_projection),
        "in_monthly_pool_relation_count": sum(row.get("symbol") in pool_targets for row in catalog_projection),
        "outside_monthly_pool_relation_count": sum(
            bool(row.get("symbol")) and row.get("symbol") not in pool_targets for row in catalog_projection),
    }
    accepted_a_rows = [item for item in relation_rows if isinstance(item, dict)
        and item.get("relation_type") in RELATIONSHIP_A
        and item.get("relation_status") == "REVIEWED"
        and item.get("relation_pit_status") != "PIT_UNCONFIRMED"]
    # Frozen V4 policy treats every ETF route as secondary sector background.
    # It remains visible in C paths and cannot become a primary A/B path.
    ab_paths, industry_index = _mapping_index(
        accepted_a_rows, [], expected_session, context)
    relation_index = {}
    for item in relation_rows:
        if isinstance(item, dict) and hk_symbol(item.get("symbol")):
            relation_index.setdefault((item["symbol"], item.get("us_symbol"),
                item.get("relation_type")), item)
    # A direct source without a frozen display theme is still a valid A route;
    # theme caps are part of the paused V1 selector, not this daily map.
    for symbol, paths in ab_paths.items():
        for path in paths:
            path["gaps"] = [gap for gap in path.get("gaps", [])
                if gap != "PRIMARY_THEME_UNMAPPED"]
            path["status"] = "VERIFIED" if not path["gaps"] else "UNASSESSED"
            path["reason"] = None if not path["gaps"] else path["gaps"][0]
            source_row = relation_index.get((symbol, path.get("us_symbol"),
                path.get("relation_type")), {})
            path.update(research_basis=source_row.get("research_basis"),
                relation_limitations=source_row.get("relation_limitations") or [],
                relation_source_refs=source_row.get("relation_source_refs") or [],
                diagnostic_gaps=source_row.get("diagnostic_gaps") or [])

    relation_c_paths = {}
    outside = {}
    pool = set(codes)
    for item in relation_rows:
        if not isinstance(item, dict) or not hk_symbol(item.get("symbol")):
            continue
        relation_type = item.get("relation_type")
        is_a = (relation_type in RELATIONSHIP_A
            and item.get("relation_status") == "REVIEWED"
            and item.get("relation_pit_status") != "PIT_UNCONFIRMED")
        is_c = (relation_type in C_RELATIONSHIP_TYPES or
            relation_type not in RELATIONSHIP_A or not is_a)
        if not is_c:
            continue
        path = _single_day_c_relation_path(item, expected_session, context)
        key = item["symbol"]
        (relation_c_paths if key in pool else outside).setdefault(key, []).append(path)

    broad_c_paths = {}
    factor_row_first = {}
    factor_row_duplicates = set()
    for item in industry_rows:
        if not isinstance(item, dict) or not hk_symbol(item.get("symbol")):
            continue
        key = item["symbol"]
        if key in factor_row_first:
            factor_row_duplicates.add(key)
        else:
            factor_row_first[key] = item
        for path in _single_day_broad_c_paths(item, expected_session, context, manual_quote_scope):
            broad_c_paths.setdefault(key, []).append(path)

    industry_state = (factor_summary or {}).get("industry_summary", {}) if isinstance(factor_summary, dict) else {}
    industry_source_ready = industry_state.get("source_status") in ("READY", "PARTIAL")
    rows = []
    open_reaction_status, post_open_reason = _post_open_state(context)
    for code in sorted(codes):
        row_paths = list(ab_paths.get(code, []))
        row_paths.extend(relation_c_paths.get(code, []))
        row_paths.extend(broad_c_paths.get(code, []))
        row_paths.sort(key=_mapping_path_order)
        ab = [path for path in row_paths if path.get("grade") in ("A", "B")]
        primary = ab[0] if ab else None
        industry_row = factor_row_first.get(code)
        name = next((item.get("name") for item in relation_rows
            if isinstance(item, dict) and item.get("symbol") == code and item.get("name")), None)
        if not name and industry_row:
            name = industry_row.get("name")
        row = dict(symbol=code, name=name, in_monthly_pool=True, decision="UNASSESSED",
            mapping_grade=primary.get("grade") if primary else ("C" if row_paths else None),
            source_industry=(industry_row or {}).get("source_industry"),
            primary_proxy=primary.get("proxy_symbol") if primary else None,
            primary_us_symbol=primary.get("us_symbol") if primary else None,
            primary_relation_type=primary.get("relation_type") if primary else None,
            primary_signed_return_pct=primary.get("signed_return_pct") if primary else None,
            primary_status=primary.get("status") if primary else None,
            mapping_paths=row_paths, conflict_paths=[], reasons=[], reason=None,
            catalog_peer_baskets=catalog_peer_baskets.get(code, []),
            catalog_relation_dispositions=[{
                "relation_id": relation.get("catalog_relation_id"),
                "us_symbol": relation.get("us_symbol"),
                "relation_type": relation.get("relation_type"),
                "route": relation.get("route"),
                "disposition": relation.get("catalog_disposition"),
                "reason": relation.get("catalog_disposition_reason"),
                "quote_status": relation.get("quote_status"),
                "quote_missing_reason": relation.get("quote_missing_reason"),
                "source_return_pct": relation.get("us_source_return_pct"),
                "signed_hk_return_pct": relation.get("signed_hk_return_pct"),
                "fact": relation.get("catalog_fact"),
                "condition": relation.get("catalog_condition"),
                "raw_direction": relation.get("catalog_direction_raw"),
                "current_applicability": relation.get("catalog_current_applicability"),
                "condition_trigger_state": relation.get("condition_trigger_state"),
                "active_transmission": relation.get("active_transmission"),
            } for relation in catalog_projection if relation.get("symbol") == code],
            open_reaction_status=open_reaction_status,
            post_open_status="PENDING_OPEN" if open_reaction_status == "PENDING_OPEN" else "CANNOT_CONFIRM",
            post_open_reason=post_open_reason,
            formal_target_eligibility="CANNOT_CONFIRM")
        if primary is not None:
            if primary.get("status") != "VERIFIED":
                row["reasons"] = list(primary.get("gaps") or ["PRIMARY_AB_MAPPING_UNASSESSED"])
                row["reason"] = row["reasons"][0]
            else:
                primary_return = _decimal(primary.get("signed_return_pct"))
                if primary_return is None:
                    row["reasons"] = ["PRIMARY_AB_RETURN_UNVERIFIED"]
                    row["reason"] = row["reasons"][0]
                else:
                    secondary = [path for path in ab[1:]]
                    signed_secondary = [(path, _decimal(path.get("signed_return_pct"))) for path in secondary]
                    material_opposites = [path for path, value in signed_secondary
                        if path.get("status") == "VERIFIED" and value is not None
                        and abs(primary_return) >= MIN_PROXY_RETURN
                        and abs(value) >= MIN_PROXY_RETURN
                        and (primary_return > 0) != (value > 0)]
                    row["conflict_paths"] = material_opposites
                    policy_conflict = (primary_return >= MIN_PROXY_RETURN and any(
                        path.get("status") == "VERIFIED" and value is not None
                        and value <= Decimal("-1") for path, value in signed_secondary))
                    unknown_secondaries = [path for path in secondary if path.get("status") != "VERIFIED"]
                    if material_opposites:
                        row["decision"] = "CONFLICT"
                        row["reason"] = "FIXED_PRIMARY_AND_SECONDARY_A_B_PATHS_OPPOSE"
                        row["reasons"] = [row["reason"]]
                    elif primary_return >= MIN_PROXY_RETURN and unknown_secondaries:
                        row["reason"] = "SECONDARY_A_B_PATH_UNVERIFIED_CONFLICT_STATUS_CANNOT_CONFIRM"
                        row["reasons"] = [row["reason"]]
                    elif primary_return >= MIN_PROXY_RETURN:
                        row["decision"] = "BENEFIT"
                        row["reason"] = "PRIMARY_AB_SIGNED_RETURN_AT_LEAST_1_PERCENT"
                        row["reasons"] = [row["reason"]]
                    elif primary_return <= Decimal("-1"):
                        row["decision"] = "RISK"
                        row["reason"] = "PRIMARY_AB_SIGNED_RETURN_AT_MOST_MINUS_1_PERCENT"
                        row["reasons"] = [row["reason"]]
                    else:
                        row["decision"] = "OBSERVATION"
                        row["reason"] = "PRIMARY_AB_MOVE_WITHIN_PLUS_OR_MINUS_1_PERCENT"
                        row["reasons"] = [row["reason"]]
                    row["frozen_policy_conflict"] = policy_conflict
                    if unknown_secondaries:
                        row["unresolved_secondary_paths"] = unknown_secondaries
        elif row_paths:
            c_paths = [path for path in row_paths if path.get("grade") == "C"]
            if any(path.get("status") == "VERIFIED" for path in c_paths):
                row["decision"] = "OBSERVATION"
                row["reason"] = "C_MAPPING_OBSERVE_ONLY"
                row["reasons"] = ["C_MAPPING_OBSERVE_ONLY"]
            else:
                row["reason"] = (c_paths[0].get("reason") or
                    "C_MAPPING_RETURN_UNASSESSED") if c_paths else "MAPPING_PATH_UNASSESSED"
                row["reasons"] = list(c_paths[0].get("gaps") or [row["reason"]])
        elif code in factor_row_duplicates:
            row["reason"] = "HK_INDUSTRY_CLASSIFICATION_DUPLICATE"
            row["reasons"] = [row["reason"]]
        elif industry_row and not industry_row.get("source_industry"):
            row["decision"] = "UNMAPPED"
            row["reason"] = industry_row.get("reason") or "HK_INDUSTRY_CLASSIFICATION_MISSING"
            row["reasons"] = list(industry_row.get("conditions") or [row["reason"]])
        elif industry_row and industry_row.get("identity_status") != "VERIFIED":
            row["reason"] = industry_row.get("reason") or "HK_INDUSTRY_SECURITY_IDENTITY_UNVERIFIED"
            row["reasons"] = list(industry_row.get("conditions") or [row["reason"]])
        elif industry_row and industry_row.get("source_industry") not in INDUSTRY_PATHS:
            row["decision"] = "UNMAPPED"
            row["reason"] = industry_row.get("reason") or "INDUSTRY_LABEL_NOT_IN_FIXED_A_B_C_MAP"
            row["reasons"] = list(industry_row.get("conditions") or [row["reason"]])
        elif industry_source_ready:
            row["decision"] = "UNMAPPED"
            row["reason"] = ("HK_INDUSTRY_CLASSIFICATION_MISSING" if industry_row is None
                else "NO_FIXED_A_B_C_MAPPING")
            row["reasons"] = [row["reason"]]
        else:
            row["reason"] = industry_state.get("source_gap") or "HK_INDUSTRY_SOURCE_UNAVAILABLE"
            row["reasons"] = [row["reason"]]
        rows.append(row)

    outside_pool_observations = []
    for code in sorted(set(outside) | (set(ab_paths) - pool)):
        paths = list(ab_paths.get(code, [])) + list(outside.get(code, []))
        outside_pool_observations.append(dict(symbol=code, in_monthly_pool=False,
            decision="OUTSIDE_POOL_OBSERVATION", reason="OUTSIDE_MONTHLY_RESEARCH_POOL",
            mapping_paths=paths, RESEARCH_ONLY=True))
    counts = {name: sum(row["decision"] == name for row in rows)
        for name in ("BENEFIT", "RISK", "CONFLICT", "OBSERVATION", "UNMAPPED", "UNASSESSED")}
    counts["SMALL_MOVE_WATCH"] = sum(row["decision"] == "OBSERVATION"
        and row.get("mapping_grade") in ("A", "B") for row in rows)
    counts["C_WATCH"] = sum(row["decision"] == "OBSERVATION"
        and row.get("mapping_grade") == "C" for row in rows)
    gaps = list(catalog_identity_gaps)
    if counts["UNASSESSED"]:
        gaps.append("SINGLE_DAY_MAPPING_PATHS_UNASSESSED")
        if "SINGLE_DAY_MAPPING_ROWS_UNASSESSED" not in gaps:
            gaps.append("SINGLE_DAY_MAPPING_ROWS_UNASSESSED")
    if counts["UNMAPPED"]:
        gaps.append("SINGLE_DAY_MAPPING_UNMAPPED_POOL_ROWS")
    state = "PARTIAL" if gaps else "READY"
    return dict(display_only=True, state=state, rules_version=SINGLE_DAY_MAPPING_VERSION,
        mapping_policy_version=MAPPING_POLICY_VERSION, mapping_policy_sha256=MAPPING_POLICY_SHA256,
        target_date=context.get("target_date"), price_session=price_session, source_session=expected_session,
        monthly_observed_scope_count=len(codes), monthly_source_date=membership.get("source_date"),
        monthly_source_sha256=membership.get("artifact_sha256"), monthly_codes_sha256=membership.get("codes_sha256"),
        formal_target_eligibility="CANNOT_CONFIRM", counts=counts, rows=rows,
        outside_pool_observations=outside_pool_observations,
        benefit_rows=[row["symbol"] for row in rows if row["decision"] == "BENEFIT"],
        risk_rows=[row["symbol"] for row in rows if row["decision"] == "RISK"],
        conflict_rows=[row["symbol"] for row in rows if row["decision"] == "CONFLICT"],
        observation_rows=[row["symbol"] for row in rows if row["decision"] == "OBSERVATION"],
        unmapped_rows=[row["symbol"] for row in rows if row["decision"] == "UNMAPPED"],
        unassessed_rows=[row["symbol"] for row in rows if row["decision"] == "UNASSESSED"],
        industry_source_status=industry_state.get("source_status"),
        industry_source_date=industry_state.get("observed_trade_date") or industry_state.get("source_asof"),
        industry_source_sha256=industry_state.get("source_artifact_sha256"),
        catalog_consumption=catalog_summary,
        catalog_stock_reconciliation=catalog_stock_reconciliation,
        catalog_relation_dispositions=catalog_projection,
        catalog_peer_baskets=catalog_peer_baskets,
        manual_quote_scope=dict(state=(manual_quote_scope or {}).get("state", "CANNOT_CONFIRM"),
            session_date=(manual_quote_scope or {}).get("us_session_date"),
            scope_sha256=(manual_quote_scope or {}).get("scope_sha256"),
            payload_sha256=(manual_quote_scope or {}).get("payload_sha256"),
            gap=(manual_quote_scope or {}).get("gap")),
        gaps=gaps, strict_v1_status="PAUSED_NOT_EXECUTED",
        deferred_gates=["HK_MA20", "HK_RETURN5", "HK_TURNOVER20", "TOP10", "THEME3"],
        historical_pit_verified=False, research_effectiveness="UNVERIFIED",
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)


def _evaluate_stock(symbol, history, mapping_paths, industry_row, industry_source_ready,
                    close_sessions, amount_sessions):
    paths = list(mapping_paths or [])
    primary = paths[0] if paths else None
    metrics, gaps = _metrics(history, close_sessions, amount_sessions)
    row = dict(symbol=symbol, decision="UNASSESSED", rank=None, reason=None,
        reasons=[], conditions=[], mapping_grade=primary.get("grade") if primary else None,
        primary_theme=primary.get("primary_theme") if primary else None,
        primary_proxy=primary.get("proxy_symbol") if primary else None,
        primary_us_symbol=primary.get("us_symbol") if primary else None,
        primary_relation_type=primary.get("relation_type") if primary else None,
        primary_signed_proxy_return_pct=primary.get("signed_return_pct") if primary else None,
        metrics=metrics or {}, mapping_paths=paths,
        risks=["RESEARCH_ONLY", "FORMAL_TARGET_ELIGIBILITY_CANNOT_CONFIRM",
            "HISTORICAL_PIT_UNVERIFIED", "RESEARCH_EFFECT_UNVERIFIED"])
    if not paths and isinstance(industry_row, dict):
        if industry_row.get("source_industry") is None or industry_row.get("reason") == "HK_INDUSTRY_CLASSIFICATION_MISSING":
            gaps.append("HK_INDUSTRY_CLASSIFICATION_MISSING")
        elif industry_row.get("identity_status") != "VERIFIED":
            gaps.append("HK_INDUSTRY_CLASSIFICATION_IDENTITY_UNVERIFIED")
        elif not industry_source_ready:
            gaps.append("HK_INDUSTRY_CLASSIFICATION_SOURCE_UNAVAILABLE")
        else:
            row.update(decision="NOT_SELECTED", reason="NO_FROZEN_A_OR_B_MAPPING",
                reasons=["NO_FROZEN_A_OR_B_MAPPING"])
            if metrics:
                row["metrics"] = metrics
            if metrics and metrics["suspension_status"] == "UNKNOWN":
                row["risks"].append("SUSPENSION_STATUS_UNKNOWN")
            return row
    elif not paths and not industry_source_ready:
        gaps.append("HK_INDUSTRY_CLASSIFICATION_SOURCE_UNAVAILABLE")
    if gaps:
        row.update(reason=gaps[0], reasons=list(dict.fromkeys(gaps)))
        if metrics and metrics.get("suspension_status") == "UNKNOWN":
            row["risks"].append("SUSPENSION_STATUS_UNKNOWN")
        return row
    if metrics is None:
        row.update(reason="HK_HISTORY_METRICS_UNAVAILABLE", reasons=["HK_HISTORY_METRICS_UNAVAILABLE"])
        return row
    if metrics["suspension_status"] == "SUSPENDED":
        row.update(decision="NOT_SELECTED", reason="KNOWN_SUSPENDED", reasons=["KNOWN_SUSPENDED"])
        return row
    if metrics["suspension_status"] == "UNKNOWN":
        row["risks"].append("SUSPENSION_STATUS_UNKNOWN")
    if primary is None:
        row.update(decision="NOT_SELECTED", reason="NO_FROZEN_A_OR_B_MAPPING", reasons=["NO_FROZEN_A_OR_B_MAPPING"])
        return row
    if primary.get("status") != "VERIFIED":
        row.update(reason=primary.get("reason") or "PRIMARY_PROXY_RETURN_UNVERIFIED",
            reasons=list(dict.fromkeys(primary.get("gaps") or ["PRIMARY_PROXY_RETURN_UNVERIFIED"])))
        return row
    primary_return = _decimal(primary.get("signed_return_pct"))
    if primary_return is None:
        row.update(reason="PRIMARY_PROXY_RETURN_UNVERIFIED", reasons=["PRIMARY_PROXY_RETURN_UNVERIFIED"])
        return row
    secondary_unknown = [path for path in paths[1:] if path.get("status") != "VERIFIED"]
    if secondary_unknown:
        row.update(reason="SECONDARY_MAPPING_PATH_UNVERIFIED",
            reasons=["SECONDARY_MAPPING_PATH_UNVERIFIED"])
        return row
    conflicts = [path for path in paths[1:]
        if (_decimal(path.get("signed_return_pct")) is not None
            and _decimal(path.get("signed_return_pct")) <= Decimal("-1"))]
    row["conflict_paths"] = conflicts
    if primary_return < MIN_PROXY_RETURN:
        row.update(decision="NOT_SELECTED", reason="PRIMARY_SIGNED_PROXY_RETURN_BELOW_1_PERCENT",
            reasons=["PRIMARY_SIGNED_PROXY_RETURN_BELOW_1_PERCENT"])
        return row
    if conflicts:
        row.update(decision="NOT_SELECTED", reason="SECONDARY_A_B_PROXY_CONFLICT",
            reasons=["SECONDARY_A_B_PROXY_CONFLICT"])
        return row
    close = _decimal(metrics["hk_close"])
    previous_close = _decimal(metrics["hk_previous_close"])
    ma20 = _decimal(metrics["hk_ma20"])
    ratio = _decimal(metrics["hk_close_to_ma20"])
    return5 = _decimal(metrics["hk_return_5_sessions_pct"])
    turnover20 = _decimal(metrics["hk_mean_turnover20_hkd"])
    fails = []
    if previous_close < ma20:
        fails.append("HK_PREVIOUS_CLOSE_BELOW_MA20")
    if close / ma20 > MAX_CLOSE_TO_MA20 or ratio > MAX_CLOSE_TO_MA20:
        fails.append("HK_CLOSE_TO_MA20_ABOVE_1_1")
    if return5 > MAX_RETURN5:
        fails.append("HK_RETURN_5_SESSIONS_ABOVE_15_PERCENT")
    if turnover20 < MIN_MEAN_TURNOVER20_HKD:
        fails.append("HK_MEAN_TURNOVER20_BELOW_20M_HKD")
    if fails:
        row.update(decision="NOT_SELECTED", reason=fails[0], reasons=fails)
        return row
    row.update(decision="CONDITIONAL_WATCH", reason="STRICT_V1_GATES_PASSED_PENDING_RANK_CAP",
        reasons=["STRICT_V1_GATES_PASSED_PENDING_RANK_CAP"])
    return row


def run_strict_us_selection(context, *, relation_rows, industry_rows, factor_summary,
                            payload):
    """Build a separate strict selector summary; never alter lane decisions/counts."""
    context = context if isinstance(context, dict) else {}
    expected_session = (context.get("source_sessions") or {}).get("us") or (context.get("source_sessions") or {}).get("US")
    price_session = (context.get("source_sessions") or {}).get("hk_price") or (context.get("source_sessions") or {}).get("HK_PRICE")
    payload = payload if isinstance(payload, dict) else {}
    membership = payload.get("monthly_membership") if isinstance(payload.get("monthly_membership"), dict) else {}
    codes = membership.get("codes")
    if not isinstance(codes, list) or not codes or len(codes) != len(set(codes)) or not all(hk_symbol(code) for code in codes):
        return dict(display_only=True, state="CANNOT_CONFIRM", rules_version=RULES_VERSION,
            rules_sha256=RULES_SHA256, mapping_policy_version=MAPPING_POLICY_VERSION,
            mapping_policy_sha256=MAPPING_POLICY_SHA256, target_date=context.get("target_date"),
            price_session=price_session, source_session=expected_session,
            monthly_observed_scope_count=None, observed_count=None, selected_count=None,
            rows=[], selected=[], funnel={}, gaps=["MONTHLY_RESEARCH_UNIVERSE_UNAVAILABLE"],
            historical_pit_verified=False, research_effectiveness="RESEARCH_RULE_RECOMMENDATION_EFFECT_UNVERIFIED",
            RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    source_date = _date_token(membership.get("source_date"))
    expected_codes_sha = hashlib.sha256(_canonical({"market": "HK_CONNECT", "codes": sorted(codes)})).hexdigest()
    if (membership.get("status") != "VERIFIED"
            or membership.get("target_eligibility") != "CANNOT_CONFIRM"
            or membership.get("owner") != "FUTU_HKCONNECT_PLATE_MEMBERSHIP"
            or not valid_sha(membership.get("source_sha256"))
            or membership.get("codes_sha256") != expected_codes_sha
            or source_date is None or source_date[:6] != (context.get("target_date") or "")[:6]
            or source_date > (context.get("target_date") or "")):
        member_gap = "MONTHLY_RESEARCH_UNIVERSE_IDENTITY_INVALID"
    else:
        member_gap = None
    history_input = payload.get("hk_history") if isinstance(payload.get("hk_history"), dict) else {}
    source_status = history_input.get("status", "CANNOT_CONFIRM")
    history_identity_ok = (
        valid_sha(history_input.get("panel_sha256"))
        and valid_sha(history_input.get("panel_manifest_sha256"))
        and valid_sha(history_input.get("history_resolution_manifest_sha256"))
        and valid_sha(history_input.get("history_resolution_proof_sha256"))
        and history_input.get("amount_unit_status") == AMOUNT_UNIT_STATUS
        and history_input.get("basic_unit_check_sha256") == BASIC_UNIT_CHECK_SHA256
        and current(context, history_input.get("panel_available_at"))
    )
    if source_status == "READY" and not history_identity_ok:
        history_input = {**history_input, "gap": "HK_HISTORY_OWNER_IDENTITY_INVALID"}
        source_status = "CANNOT_CONFIRM"
    if source_status != "READY" or member_gap:
        codes_sorted = sorted(codes)
        unassessed_rows = [dict(symbol=code, decision="UNASSESSED", rank=None,
            reason=member_gap or history_input.get("gap") or "HK_HISTORY_OWNER_UNAVAILABLE",
            reasons=[member_gap or history_input.get("gap") or "HK_HISTORY_OWNER_UNAVAILABLE"],
            conditions=[], metrics={}, mapping_paths=[], risks=["RESEARCH_ONLY", "HISTORICAL_PIT_UNVERIFIED"])
            for code in codes_sorted]
        return dict(display_only=True, state="CANNOT_CONFIRM", rules_version=RULES_VERSION,
            rules_sha256=RULES_SHA256, mapping_policy_version=MAPPING_POLICY_VERSION,
            mapping_policy_sha256=MAPPING_POLICY_SHA256, target_date=context.get("target_date"),
            price_session=price_session, source_session=expected_session,
            monthly_observed_scope_count=len(codes_sorted),
            monthly_source_date=membership.get("source_date"),
            monthly_source_sha256=membership.get("source_sha256"),
            monthly_codes_sha256=membership.get("codes_sha256"),
            formal_target_eligibility="CANNOT_CONFIRM", observed_count=None, selected_count=None,
            decision_counts={"SELECTED": 0, "CONDITIONAL_WATCH": 0, "NOT_SELECTED": 0,
                "UNASSESSED": len(codes_sorted)},
            rows=unassessed_rows, selected=[], funnel={"monthly_observed_pool":len(codes_sorted)},
            gaps=list(dict.fromkeys([member_gap, history_input.get("gap") or "HK_HISTORY_OWNER_UNAVAILABLE"])),
            amount_unit_status=history_input.get("amount_unit_status", AMOUNT_UNIT_STATUS),
            basic_unit_check_sha256=history_input.get("basic_unit_check_sha256", BASIC_UNIT_CHECK_SHA256),
            historical_pit_verified=False, research_effectiveness="RESEARCH_RULE_RECOMMENDATION_EFFECT_UNVERIFIED",
            RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)

    history_rows = history_input.get("rows") if isinstance(history_input.get("rows"), list) else []
    histories = {row.get("symbol"): row for row in history_rows if isinstance(row, dict) and hk_symbol(row.get("symbol"))}
    close_sessions = history_input.get("close_sessions")
    amount_sessions = history_input.get("amount_sessions")
    if (not isinstance(close_sessions, list) or len(close_sessions) != 21
            or not isinstance(amount_sessions, list) or len(amount_sessions) != 20
            or any(_date_token(day) != day for day in close_sessions + amount_sessions)
            or close_sessions != sorted(set(close_sessions))
            or amount_sessions != sorted(set(amount_sessions))
            or close_sessions[-20:] != amount_sessions
            or close_sessions[-1] != price_session or amount_sessions[-1] != price_session):
        unassessed_rows = [dict(symbol=code, decision="UNASSESSED", rank=None,
            reason="HK_HISTORY_SESSION_WINDOW_INVALID", reasons=["HK_HISTORY_SESSION_WINDOW_INVALID"],
            conditions=[], metrics={}, mapping_paths=[], risks=["RESEARCH_ONLY", "HISTORICAL_PIT_UNVERIFIED"])
            for code in sorted(codes)]
        return dict(display_only=True, state="CANNOT_CONFIRM", rules_version=RULES_VERSION,
            rules_sha256=RULES_SHA256, mapping_policy_version=MAPPING_POLICY_VERSION,
            mapping_policy_sha256=MAPPING_POLICY_SHA256, target_date=context.get("target_date"),
            price_session=price_session, source_session=expected_session,
            monthly_observed_scope_count=len(codes), observed_count=None, selected_count=None,
            decision_counts={"SELECTED": 0, "CONDITIONAL_WATCH": 0, "NOT_SELECTED": 0,
                "UNASSESSED": len(codes)},
            rows=unassessed_rows, selected=[], funnel={"monthly_observed_pool": len(codes),
                "unassessed": len(codes)}, gaps=["HK_HISTORY_SESSION_WINDOW_INVALID"],
            historical_pit_verified=False, research_effectiveness="RESEARCH_RULE_RECOMMENDATION_EFFECT_UNVERIFIED",
            RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)

    candidate_paths, industry_by_symbol = _mapping_index(
        relation_rows if isinstance(relation_rows, list) else [],
        industry_rows if isinstance(industry_rows, list) else [], expected_session, context)
    industry_state = (factor_summary or {}).get("industry_summary", {}) if isinstance(factor_summary, dict) else {}
    industry_source_ready = industry_state.get("source_status") in ("READY", "PARTIAL")
    rows = []
    for code in sorted(codes):
        rows.append(_evaluate_stock(code, histories.get(code), candidate_paths.get(code, []),
            industry_by_symbol.get(code), industry_source_ready, close_sessions, amount_sessions))

    candidates = [row for row in rows if row["decision"] == "CONDITIONAL_WATCH"]
    candidates.sort(key=lambda row: (
        0 if row.get("mapping_grade") == "A" else 1,
        -(_decimal(row.get("primary_signed_proxy_return_pct")) or Decimal("-Infinity")),
        -(_decimal((row.get("metrics") or {}).get("hk_mean_turnover20_hkd")) or Decimal("-Infinity")),
        row["symbol"]))
    theme_counts = {}
    selected = []
    for row in candidates:
        theme = row.get("primary_theme") or ""
        if theme_counts.get(theme, 0) >= MAX_PER_PRIMARY_THEME:
            row.update(decision="NOT_SELECTED", reason="PRIMARY_THEME_CAP_REACHED",
                reasons=["PRIMARY_THEME_CAP_REACHED"])
            continue
        if len(selected) >= MAX_SELECTED:
            row.update(decision="NOT_SELECTED", reason="MAX_SELECTED_REACHED",
                reasons=["MAX_SELECTED_REACHED"])
            continue
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
        row.update(decision="SELECTED", reason="STRICT_V1_SELECTED", reasons=["STRICT_V1_SELECTED"],
            rank=len(selected) + 1)
        selected.append(row)

    decision_counts = {name: sum(row.get("decision") == name for row in rows)
        for name in ("SELECTED", "CONDITIONAL_WATCH", "NOT_SELECTED", "UNASSESSED")}
    funnel = dict(monthly_observed_pool=len(codes), history_complete=sum(bool(row.get("metrics")) for row in rows),
        mapped_a_or_b=sum(bool(row.get("mapping_paths")) for row in rows),
        primary_proxy_trigger=sum(row.get("decision") in ("CONDITIONAL_WATCH", "SELECTED") for row in rows),
        selected=len(selected), conflict_excluded=sum(row.get("reason") == "SECONDARY_A_B_PROXY_CONFLICT" for row in rows),
        unassessed=decision_counts["UNASSESSED"])
    gaps = []
    if decision_counts["UNASSESSED"]:
        gaps.append("STRICT_V1_STOCKS_UNASSESSED")
    history_complete_count = sum(bool(row.get("metrics")) for row in rows)
    if history_complete_count == 0:
        gaps.append("HK_HISTORY_WINDOW_HAS_NO_COMPLETE_STOCKS")
        state = "CANNOT_CONFIRM"
    else:
        state = "PARTIAL" if gaps else "READY"
    return dict(display_only=True, state=state, rules_version=RULES_VERSION,
        rules_sha256=RULES_SHA256, mapping_policy_version=MAPPING_POLICY_VERSION,
        mapping_policy_sha256=MAPPING_POLICY_SHA256, target_date=context.get("target_date"),
        price_session=price_session, source_session=expected_session,
        monthly_observed_scope_count=len(codes), monthly_source_date=membership.get("source_date"),
        monthly_source_sha256=membership.get("source_sha256"), monthly_codes_sha256=membership.get("codes_sha256"),
        monthly_membership_owner=membership.get("owner"), formal_target_eligibility="CANNOT_CONFIRM",
        panel_sha256=history_input.get("panel_sha256"), panel_manifest_sha256=history_input.get("panel_manifest_sha256"),
        panel_available_at=history_input.get("panel_available_at") or history_input.get("available_at"),
        history_resolution_manifest_sha256=history_input.get("history_resolution_manifest_sha256"),
        history_resolution_proof_sha256=history_input.get("history_resolution_proof_sha256"),
        amount_unit_status=history_input.get("amount_unit_status", AMOUNT_UNIT_STATUS),
        basic_unit_check_sha256=history_input.get("basic_unit_check_sha256", BASIC_UNIT_CHECK_SHA256),
        amount_field=AMOUNT_FIELD, amount_scale="1", amount_threshold_hkd="20000000",
        close_sessions=close_sessions, amount_sessions=amount_sessions,
        selected_count=len(selected) if history_complete_count else None,
        decision_counts=decision_counts, funnel=funnel,
        max_selected=MAX_SELECTED, max_per_primary_theme=MAX_PER_PRIMARY_THEME,
        primary_theme_counts=theme_counts, rows=rows,
        selected=[dict(rank=row["rank"], symbol=row["symbol"], decision=row["decision"],
            reason=row["reason"], mapping_grade=row["mapping_grade"], primary_theme=row["primary_theme"],
            primary_proxy=row["primary_proxy"], primary_us_symbol=row["primary_us_symbol"],
            primary_signed_proxy_return_pct=row["primary_signed_proxy_return_pct"],
            metrics=row["metrics"]) for row in selected],
        gaps=gaps, historical_pit_verified=False,
        research_effectiveness="RESEARCH_RULE_RECOMMENDATION_EFFECT_UNVERIFIED",
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
