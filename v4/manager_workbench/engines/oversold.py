"""Frozen 60/5 HK oversold AND screen; nothing in here makes an order."""
from __future__ import annotations
from decimal import Decimal
from .common import decimal, hk_symbol, membership, current, valid_sha, result, row
import hashlib,json

def owner_digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

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



def comparison_proven(record, context):
    try:
        basis=record.get('comparison_basis')
        if not isinstance(basis,dict):return False
        request=basis.get('request',{});params=request.get('request',{}) if isinstance(request,dict) else {}
        source=basis.get('source')
        if source=='FUTU':
            profile=(params.get('ktype')=='K_DAY' and params.get('autype')=='NONE' and basis.get('adjustment')=='RAW')
        elif source=='TDXPY_0_2_7':
            from upstreams.v3_shared_data.shared_data.hk_daily_supplement import TDXPY_PROFILE,TDXPY_NODES
            profile=(all(params.get(k)==v for k,v in TDXPY_PROFILE.items()) and params.get('endpoint') in TDXPY_NODES
                and params.get('market') in {31,48,49} and params.get('code')==record.get('symbol')
                and valid_sha(params.get('calendar_sha256')) and valid_sha(basis.get('response_sha256'))
                and valid_sha(basis.get('catalogue_sha256')) and basis.get('adjustment')=='TDX_PROTOCOL_PARAM1_FIXED')
            calendar=record.get('calendar',{})
            profile=profile and params.get('requested_sessions')==calendar.get('expected_high_sessions60',[])+[calendar.get('previous_session')]
            profile=profile and params.get('calendar_sha256')==calendar.get('sha256')
        else:return False
        if (not profile or record.get('owner')!=source or basis.get('security_symbol')!=record.get('symbol')
                or basis.get('raw_sha256')!=record.get('source_sha256') or not valid_sha(basis.get('receipt_sha256'))
                or basis.get('request_sha256')!=owner_digest(request) or request.get('code')!=record.get('symbol')
                or request.get('source')!=source or record.get('adjustment')!=basis.get('adjustment')
                or basis.get('price_comparison')!='SAME_SOURCE_SECURITY_REQUEST' or basis.get('volume_comparison')!='SAME_SOURCE_SECURITY_REQUEST'
                or basis.get('available_at')!=record.get('available_at') or not current(context,basis.get('available_at'))):return False
        identity=owner_digest(basis)
        bars=[record.get('previous_bar'),*record.get('high_history60',[]),*record.get('volume_history5',[])]
        return all(isinstance(bar,dict) and bar.get('comparison_basis_sha256')==identity
            and bar.get('source_metadata',{}).get('code')==record.get('symbol')
            and bar.get('source_metadata',{}).get('raw_sha256')==basis['raw_sha256']
            and bar.get('source_metadata',{}).get('source')==source
            and bar.get('source_metadata',{}).get('receipt_sha256')==basis['receipt_sha256']
            and (source=='FUTU' or (bar.get('source_metadata',{}).get('response_sha256')==basis['response_sha256']
                and bar.get('source_metadata',{}).get('catalogue_sha256')==basis['catalogue_sha256']
                and bar.get('source_metadata',{}).get('native_fields',{}).get('scale_applied')==1))
            and owner_digest(bar.get('source_metadata',{}).get('request'))==basis['request_sha256']
            and bar.get('available_at')==basis['available_at'] for bar in bars)
    except (ValueError,TypeError,KeyError,AttributeError):return False

def window_metrics(context, record, measures=None):
    """Validate the existing 61-session comparison, independently of membership.

    Used by both selection and panel gap routing. A valid failed screen is still
    a valid window and must never trigger selection of a different provider.
    """
    measures = measures if measures is not None else dict(close=None, max_high_60=None, price_threshold=None, price_pass=None,
                    volume=None, mean_volume_5=None, volume_ratio=None, volume_pass=None,
                    previous_session=None, source_price_unit=None, source_volume_unit=None)
    if not (valid_sha(record.get("source_sha256")) and record.get("owner") and
            current(context, record.get("available_at"))):
        raise ValueError("SOURCE_IDENTITY_OR_TIME_UNVERIFIED")
    if record.get("window_gap"):
        raise ValueError(record["window_gap"])
    calendar = record.get("calendar")
    if not isinstance(calendar, dict) or calendar.get("verification") != "VERIFIED" or not valid_sha(calendar.get("sha256")):
        raise ValueError("CALENDAR_NOT_VERIFIED")
    prev = calendar.get("previous_session")
    if not isinstance(prev, str) or len(prev) != 8 or not prev.isdigit() or prev >= context["target_date"] or calendar.get("target_date") != context["target_date"]:
        raise ValueError("PREVIOUS_TRADING_SESSION_UNKNOWN")
    measures["previous_session"] = prev
    bar = record.get("previous_bar")
    if not isinstance(bar, dict) or bar.get("session") != prev or not current(context, bar.get("available_at")):
        raise ValueError("PREVIOUS_BAR_MISSING_OR_LATE")
    if bar.get("suspended") is True:
        raise ValueError("PREVIOUS_SESSION_SUSPENDED")
    absolute_units=not any(not record.get(field) or not bar.get(field) or record[field] != bar[field]
           for field in ("price_unit", "volume_unit", "adjustment"))
    if not absolute_units and not comparison_proven(record,context):
        raise ValueError("UNIT_ADJUSTMENT_OR_CURRENCY_UNKNOWN")
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
        raise ValueError(reason) from exc
    price_pass = close <= PRICE_RATIO * max_high
    ratio = volume / mean_volume
    volume_pass = ratio >= VOLUME_RATIO
    measures.update(close=str(close), max_high_60=str(max_high), price_threshold=str(PRICE_RATIO * max_high),
        price_pass=price_pass, volume=str(volume), mean_volume_5=str(mean_volume),
        volume_ratio=str(ratio), volume_pass=volume_pass)
    return measures


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
    try:
        window_metrics(context, record, measures)
    except (ValueError, KeyError, TypeError) as exc:
        reason = str(exc) if str(exc).isidentifier() else "OVERSOLD_EVIDENCE_UNASSESSED"
        return row(record, "UNASSESSED", reason, metrics=measures)
    price_pass, volume_pass = measures["price_pass"], measures["volume_pass"]
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

