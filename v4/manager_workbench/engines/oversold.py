"""Frozen 60/5 HK oversold AND screen; nothing in here makes an order."""
from __future__ import annotations
from decimal import Decimal
from .common import decimal, hk_symbol, membership, current, valid_sha, result, row

PRICE_RATIO = Decimal("0.8")
VOLUME_RATIO = Decimal("1.5")


def _sessions(calendar, prev, key, count):
    expected = calendar.get(key)
    if not isinstance(expected, list) or len(expected) != count or len(set(expected)) != count:
        raise ValueError("CALENDAR_WINDOW_NOT_VERIFIED")
    if any(not isinstance(x, str) or len(x) != 8 or not x.isdigit() or x >= prev for x in expected):
        raise ValueError("CALENDAR_WINDOW_BAD_DATE")
    if expected != sorted(expected):
        raise ValueError("CALENDAR_WINDOW_ORDER")
    return expected


def _bars(record, prev, calendar, history_key, session_key, field, expected_count, unit_field, adjustment=None):
    actual = record.get(history_key)
    expected = _sessions(calendar, prev, session_key, expected_count)
    if not isinstance(actual, list) or len(actual) != expected_count:
        raise ValueError("HISTORY_INCOMPLETE")
    if [item.get("session") for item in actual if isinstance(item, dict)] != expected:
        raise ValueError("HISTORY_DATE_DUPLICATE_OR_GAP")
    if any(not isinstance(item, dict) or item.get(unit_field) != record[unit_field] or
           (adjustment is not None and item.get("adjustment") != adjustment)
           for item in actual):
        raise ValueError("HISTORY_UNIT_OR_ADJUSTMENT_MISMATCH")
    values = [decimal(item.get(field)) for item in actual]
    if any(x < 0 for x in values) or (field == "high" and any(x <= 0 for x in values)):
        raise ValueError("HISTORY_VALUE_INVALID")
    if any("available_at" in item and not current(record["_context"], item["available_at"]) for item in actual):
        raise ValueError("HISTORY_AFTER_CUTOFF")
    return values


def screen_one(context, record):
    reasons = []
    measures = dict(close=None, max_high_60=None, price_threshold=None, price_pass=None,
                    volume=None, mean_volume_5=None, volume_ratio=None, volume_pass=None,
                    previous_session=None, source_price_unit=None, source_volume_unit=None)
    basic = (isinstance(record, dict) and record.get("market") == "HK_CONNECT" and
             hk_symbol(record.get("symbol")) and record.get("target_date") == context["target_date"] and
             valid_sha(record.get("source_sha256")) and record.get("owner") and
             current(context, record.get("available_at")))
    if not basic:
        return row(record if isinstance(record, dict) else {}, "UNASSESSED", "SOURCE_IDENTITY_OR_TIME_UNVERIFIED", metrics=measures)
    eligible = membership(record, context)
    if eligible is None:
        return row(record, "UNASSESSED", "CONNECT_MEMBERSHIP_NOT_VERIFIED", metrics=measures)
    if not eligible:
        return row(record, "NOT_SELECTED", "CONNECT_INELIGIBLE", metrics=measures)
    calendar = record.get("calendar")
    if not isinstance(calendar, dict) or calendar.get("verification") != "VERIFIED" or not valid_sha(calendar.get("sha256")):
        return row(record, "UNASSESSED", "CALENDAR_NOT_VERIFIED", metrics=measures)
    prev = calendar.get("previous_session")
    if not isinstance(prev, str) or len(prev) != 8 or not prev.isdigit() or prev >= context["target_date"] or calendar.get("target_date") != context["target_date"]:
        return row(record, "UNASSESSED", "PREVIOUS_TRADING_SESSION_UNKNOWN", metrics=measures)
    measures["previous_session"] = prev
    bar = record.get("previous_bar")
    if not isinstance(bar, dict) or bar.get("session") != prev or not current(context, bar.get("available_at")):
        return row(record, "UNASSESSED", "PREVIOUS_BAR_MISSING_OR_LATE", metrics=measures)
    if bar.get("suspended") is True:
        return row(record,"UNASSESSED","PREVIOUS_SESSION_SUSPENDED",metrics=measures)
    if any(not record.get(field) or not bar.get(field) or record[field] != bar[field]
           for field in ("price_unit", "volume_unit", "adjustment")):
        return row(record, "UNASSESSED", "UNIT_ADJUSTMENT_OR_CURRENCY_UNKNOWN", metrics=measures)
    measures["source_price_unit"] = record["price_unit"]
    measures["source_volume_unit"] = record["volume_unit"]
    try:
        history_high = _bars(dict(record, _context=context), prev, calendar, "high_history60", "expected_high_sessions60", "high", 60, "price_unit", record["adjustment"])
        history_vol = _bars(dict(record, _context=context), prev, calendar, "volume_history5", "expected_volume_sessions5", "volume", 5, "volume_unit")
        close, volume = decimal(bar.get("close")), decimal(bar.get("volume"))
        if close <= 0 or volume < 0:raise ValueError("PREVIOUS_BAR_NONPOSITIVE_PRICE_OR_NEGATIVE_VOLUME")
        max_high = max(history_high)
        mean_volume = sum(history_vol) / Decimal(5)
        if mean_volume <= 0:raise ValueError("VOLUME_DENOMINATOR_INVALID")
    except (ValueError, KeyError, TypeError) as exc:
        reason = str(exc) if str(exc).isidentifier() else "OVERSOLD_EVIDENCE_UNASSESSED"
        return row(record, "UNASSESSED", reason, metrics=measures)
    price_pass = close <= PRICE_RATIO * max_high
    ratio = volume / mean_volume
    volume_pass = ratio >= VOLUME_RATIO
    measures.update(close=str(close), max_high_60=str(max_high), price_threshold=str(PRICE_RATIO * max_high),
        price_pass=price_pass, volume=str(volume), mean_volume_5=str(mean_volume),
        volume_ratio=str(ratio), volume_pass=volume_pass)
    if price_pass and volume_pass:
        return row(record, "SELECTED", "OVERSOLD_AND_VERIFIED", metrics=measures)
    if price_pass != volume_pass:
        return row(record, "CONDITIONAL_WATCH", "ONLY_ONE_OF_TWO_CONDITIONS", metrics=measures,
                   conditions=["NEEDS_FULL_60_5_AND_RULE"])
    return row(record, "NOT_SELECTED", "NEITHER_OVERSOLD_CONDITION", metrics=measures)


def run_oversold(context, batch):
    rows = [screen_one(context, item) for item in batch["records"]]
    gaps=[]
    if batch.get("coverage", {}).get("scope_count") is None:
        gaps.append("OVERSOLD_AUTHORITY_SCOPE_UNKNOWN")
    return result("OVERSOLD", batch, context, rows, gaps=gaps)

