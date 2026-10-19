"""Frozen mapping quote observations inside the existing scheduled US owner.

This module never fetches or publishes. The existing producer passes one
provider response; its original 48-symbol contract remains independent.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping

from contracts.us_equity_calendar import NY, session as official_session

CONFIG_ENV = "V4_US_MAPPING_CLOSE_SCOPE_PATH"
OWNER = "research_peripheral.external_finance.scheduled_quote_scope"
SCOPE_SHA = "6d163c286d90d1dfd00b18fa134d3f4ec308d9d2efdd51e5cbba800f3d61acf8"
SYMBOLS_SHA = "10d13e10ccf9370d032886ea3e12fa6b49a431c85cce9d2d8de90309be4bdf43"
PROVENANCE = {
    "catalog_sha256": "3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671",
    "review_overlay_sha256": "d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69",
    "recovery_overlay_sha256": "3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c",
}
SCHEMA = "v4.us_mapping.scheduled_quote_scope.v1"
REQUEST_SCHEMA = "v4.us_mapping.scheduled_quote_request.v1"
_SHA = re.compile(r"[0-9a-f]{64}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")
_TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _instant(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("SCHEDULED_SCOPE_TIMEZONE_REQUIRED")
    return parsed


def _symbols(value):
    symbols = value.get("symbols")
    if (not isinstance(symbols, list) or len(symbols) != 547
            or any(not isinstance(s, str) or not _SYMBOL.fullmatch(s) for s in symbols)
            or symbols != sorted(set(symbols))
            or hashlib.sha256(json.dumps(symbols, ensure_ascii=False,
                                        separators=(",", ":")).encode()).hexdigest() != SYMBOLS_SHA
            or value.get("symbols_sha256") != SYMBOLS_SHA
            or value.get("scope_sha256") != SCOPE_SHA
            or any(value.get(k) != v for k, v in PROVENANCE.items())):
        raise ValueError("SCHEDULED_SCOPE_FROZEN_IDENTITY_MISMATCH")
    return symbols


def configured_request_scope():
    path = os.environ.get(CONFIG_ENV, "").strip()
    if not path:
        return None
    source = Path(path)
    if not source.is_absolute() or source.is_symlink():
        raise ValueError("SCHEDULED_SCOPE_CONFIG_PATH_INVALID")
    value = json.loads(source.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schema_version") != REQUEST_SCHEMA
            or value.get("enabled") is not True or value.get("RESEARCH_ONLY") is not True
            or any(value.get(k) is not False for k in
                   ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise ValueError("SCHEDULED_SCOPE_CONFIG_INVALID")
    _symbols(value)
    return value


def quote_gap(quote, symbol, source_session, captured_at):
    if not isinstance(quote, Mapping) or quote.get("symbol") != symbol:
        return "QUOTE_SYMBOL_MISMATCH"
    if quote.get("session_date") != source_session:
        return "QUOTE_SESSION_DATE_MISMATCH_CAPTURE"
    clock = quote.get("session_time")
    if not isinstance(clock, str) or not _TIME.fullmatch(clock):
        return "QUOTE_SESSION_TIMESTAMP_INVALID"
    try:
        official = official_session(source_session)
        observed = datetime.strptime(source_session + " " + clock, "%Y%m%d %H:%M:%S").replace(tzinfo=NY)
        captured = _instant(captured_at)
        if official.close_at is None or observed < official.close_at:
            return "QUOTE_PROVIDER_TIMESTAMP_BEFORE_OFFICIAL_CLOSE"
        if observed > captured:
            return "QUOTE_PROVIDER_TIMESTAMP_AFTER_CAPTURE"
        values = []
        for field in ("last", "previous_close", "change_pct"):
            raw = quote.get(field)
            if isinstance(raw, bool) or raw is None:
                return "QUOTE_PRICE_OR_RETURN_INVALID"
            value = Decimal(str(raw))
            if not value.is_finite():
                return "QUOTE_PRICE_OR_RETURN_INVALID"
            values.append(value)
        last, previous, change = values
        if last <= 0 or previous <= 0:
            return "QUOTE_PRICE_OR_RETURN_INVALID"
        if abs((last / previous - 1) * 100 - change) > Decimal("0.001"):
            return "QUOTE_PCT_CHANGE_MISMATCH"
    except (ValueError, TypeError, InvalidOperation, ArithmeticError, OverflowError):
        return "QUOTE_PRICE_OR_TIMESTAMP_INVALID"
    return None


def _validated_quotes(quotes, symbols, source_session, captured_at, prior_gaps=None):
    if not isinstance(quotes, list):
        raise ValueError("SCHEDULED_SCOPE_QUOTES_INVALID")
    counts = Counter(q.get("symbol") for q in quotes
                     if isinstance(q, dict) and isinstance(q.get("symbol"), str))
    result = {}
    gaps = {s: g for s, g in (prior_gaps or {}).items()
            if s in symbols and isinstance(g, str)}
    for quote in quotes:
        symbol = quote.get("symbol") if isinstance(quote, dict) else None
        if symbol not in symbols:
            continue
        if counts[symbol] != 1:
            gaps[symbol] = "QUOTE_SYMBOL_DUPLICATE"
            continue
        error = quote_gap(quote, symbol, source_session, captured_at)
        if error:
            gaps[symbol] = error
        else:
            result[symbol] = dict(quote)
            gaps.pop(symbol, None)
    for symbol in symbols:
        if symbol not in result:
            gaps.setdefault(symbol, "QUOTE_SYMBOL_MISSING")
    return result, gaps


def _provider_symbol_conflicts(raw):
    """Do not let an inner ticker disagreement borrow the requested key."""
    conflicts = set()
    if isinstance(raw, Mapping):
        for key, row in raw.items():
            symbol = str(key).removeprefix("v_us").removeprefix("us").upper()
            if isinstance(row, Mapping) and row.get("symbol") is not None:
                if str(row["symbol"]).upper() != symbol:
                    conflicts.add(symbol)
    elif isinstance(raw, (str, bytes)):
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        for symbol, body in re.findall(r'v_us([A-Z0-9.\-]+)="([^"]*)"', text):
            fields = body.split("~")
            if len(fields) > 2:
                # The retained actual Tencent US response qualifies field2
                # with these four exchange suffixes. Match the entire bare
                # response key first, preserving dots inside the ticker.
                inner = fields[2].strip().upper()
                accepted = {symbol, *(symbol + suffix for suffix in (".N", ".OQ", ".PS", ".AM"))}
                if inner not in accepted:
                    conflicts.add(symbol)
    return conflicts


def _save_wire_diagnostic(raw, source_session, source_sha):
    """Save the already fetched body locally, never request or publish data."""
    directory = os.environ.get("V4_US_MAPPING_WIRE_DIAGNOSTIC_DIR", "").strip()
    if not directory:
        return
    root = Path(directory)
    if (not root.is_absolute() or root.resolve() != root or not root.is_dir()
            or any(p.is_symlink() for p in [root, *root.parents])):
        raise ValueError("WIRE_DIAGNOSTIC_DIRECTORY_INVALID")
    if not re.fullmatch(r"\d{8}", source_session) or not _SHA.fullmatch(source_sha):
        raise ValueError("WIRE_DIAGNOSTIC_IDENTITY_INVALID")
    if isinstance(raw, bytes):
        body, kind = raw, "bytes"
    elif isinstance(raw, str):
        body, kind = raw.encode("utf-8"), "string"
    else:
        # Hermetic Mapping seams need no raw provider diagnostic.
        return
    if len(body) > 8 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != source_sha:
        raise ValueError("WIRE_DIAGNOSTIC_BODY_HASH_INVALID")
    pairs = [{"response_key": key, "inner_symbol": value.split("~")[2][:80]}
             for key, value in re.findall(r'v_us([A-Z0-9.\-]+)="([^"]*)"',
                                          body.decode("utf-8", errors="replace"))
             if len(value.split("~")) > 2]
    stem = f"us-quote-wire-{source_session}-{source_sha}"
    metadata = json.dumps({"schema_version": "v4.us_mapping.provider_wire_diagnostic.v1",
                           "us_session_date": source_session, "body_kind": kind,
                           "source_response_sha256": source_sha, "body_size": len(body),
                           "provider_key_inner_symbol": pairs}, sort_keys=True).encode()
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name, content in [(stem + ".bin", body), (stem + ".json", metadata)]:
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory_fd)
            except FileExistsError:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
                with os.fdopen(fd, "rb") as stream:
                    if stream.read(len(content) + 1) != content:
                        raise ValueError("WIRE_DIAGNOSTIC_EXISTING_CONTENT_MISMATCH")
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
    finally:
        os.close(directory_fd)


def build_scope_observations(request, records, parse_gaps, *, source_session,
                             captured_at, source_response_sha256, raw_response=None):
    """Derive supplementary records from the producer's one parsed response."""
    symbols = _symbols(request)
    if not isinstance(records, Mapping) or not isinstance(parse_gaps, Mapping):
        raise ValueError("SCHEDULED_SCOPE_PROVIDER_SHAPE_INVALID")
    try:
        _save_wire_diagnostic(raw_response, source_session, source_response_sha256)
    except (OSError, ValueError, TypeError) as error:
        # Diagnostics cannot alter the original quote or main48 contract.
        import sys
        print(json.dumps({"us_mapping_wire_diagnostic": "FAILED", "reason": type(error).__name__}),
              file=sys.stderr)
    conflicts = _provider_symbol_conflicts(raw_response)
    gaps = dict(parse_gaps)
    gaps.update({symbol: "QUOTE_SYMBOL_MISMATCH" for symbol in conflicts})
    quotes = [{"symbol": symbol, "exchange": "US", "session_date": row.get("session_date"),
               "session_time": row.get("session_time"), "last": row.get("last"),
               "previous_close": row.get("previous_close"), "change_pct": row.get("pct_change"),
               "provider": "Tencent qt.gtimg.cn"}
              for symbol, row in sorted(records.items())
              if symbol in symbols and symbol not in conflicts and isinstance(row, Mapping)]
    valid, gaps = _validated_quotes(quotes, symbols, source_session, captured_at, gaps)
    value = {"schema_version": SCHEMA, "owner": OWNER, "scope_sha256": SCOPE_SHA,
             "symbols_sha256": SYMBOLS_SHA, "symbols": symbols, **PROVENANCE,
             "capture_phase": "POST_CLOSE", "us_session_date": source_session,
             "captured_at": captured_at, "source_response_sha256": source_response_sha256,
             "requested_symbol_count": len(symbols), "available_symbol_count": len(valid),
             "state": "READY" if len(valid) == len(symbols) else "PARTIAL" if valid else "CANNOT_CONFIRM",
             "quotes": [valid[s] for s in sorted(valid)], "quote_failures": gaps,
             "RESEARCH_ONLY": True, "production_allowed": False,
             "buy_gate_updated": False, "orders_sent": False}
    value["record_sha256"] = digest(value)
    return value


def bind_scheduled_scope(snapshot, payload, *, source_session, cutoff,
                         payload_relative, payload_sha256, receipt_relative,
                         receipt_sha256, manifest_sha256):
    """Validate nested natural observations after the outer owner receipt check.

    The caller has already checked the exact payload/receipt/manifest binding.
    Individual invalid observations remain gaps rather than blocking siblings.
    """
    value = snapshot.get("scheduled_quote_scope")
    if value is None:
        return None
    unavailable = dict(state="CANNOT_CONFIRM", gap="US_SCHEDULED_QUOTE_SCOPE_INVALID",
                       owner=OWNER, scope_sha256=SCOPE_SHA, us_session_date=source_session,
                       requested_symbol_count=547, available_symbol_count=0, quotes={}, symbol_gaps={})
    try:
        if not isinstance(value, dict):
            raise ValueError("SCHEDULED_SCOPE_SHAPE_INVALID")
        symbols = _symbols(value)
        if (value.get("schema_version") != SCHEMA or value.get("owner") != OWNER
                or value.get("capture_phase") != "POST_CLOSE"
                or value.get("us_session_date") != source_session
                or snapshot.get("capture_phase") != "POST_CLOSE"
                or snapshot.get("capture_session_date") != source_session
                or value.get("captured_at") != snapshot.get("captured_at")
                or value.get("source_response_sha256") != snapshot.get("source_response_sha256")
                or not _SHA.fullmatch(str(value.get("source_response_sha256") or ""))
                or value.get("record_sha256") != digest({k: v for k, v in value.items() if k != "record_sha256"})
                or any(not _SHA.fullmatch(str(v or "")) for v in (payload_sha256, receipt_sha256, manifest_sha256))
                or value.get("RESEARCH_ONLY") is not True
                or any(value.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
                or _instant(value.get("captured_at")) > _instant(cutoff)):
            raise ValueError("SCHEDULED_SCOPE_OWNER_IDENTITY_INVALID")
        captures = payload.get("us_session_captures") or []
        matching = [c for c in captures if isinstance(c, dict)
                    and c.get("us_session_date") == source_session and c.get("capture_phase") == "POST_CLOSE"
                    and c.get("captured_at") == value["captured_at"]
                    and c.get("capture_origin") == "ORIGINAL_TIME_CAPTURE" and c.get("original_time_capture") is True]
        if len(matching) != 1:
            raise ValueError("SCHEDULED_SCOPE_NATURAL_CAPTURE_NOT_BOUND")
        capture = matching[0]
        late = capture.get("late", False)
        if type(late) is not bool:
            raise ValueError("SCHEDULED_SCOPE_LATE_FLAG_INVALID")
        if late:
            if capture.get("capture_mode") != "CONTROLLED_LATE_POST_CLOSE":
                raise ValueError("SCHEDULED_SCOPE_LATE_MODE_INVALID")
            # Reuse the actual owner's strict metadata/window validator, not
            # a trusted label: exact US session, phase, natural/recovery
            # windows, captured-at and original origin must all agree.
            from infrastructure.research_peripheral_store import _validate_us_session_captures
            capture = _validate_us_session_captures([capture])[0]
        elif capture.get("capture_mode"):
            raise ValueError("SCHEDULED_SCOPE_UNEXPECTED_CAPTURE_MODE")
        capture_metadata = {k: capture[k] for k in (
            "us_session_date", "capture_phase", "captured_at", "capture_id", "run_id",
            "session_timezone", "capture_origin", "original_time_capture",
            "capture_window_start", "capture_window_end", "late", "capture_mode",
            "reason", "capture_reason", "natural_capture_window_start", "natural_capture_window_end",
            "allowed_recovery_window_start", "allowed_recovery_window_end",
        ) if k in capture}
        quotes = value.get("quotes")
        if (not isinstance(quotes, list) or value.get("requested_symbol_count") != len(symbols)
                or value.get("available_symbol_count") != len(quotes)
                or not isinstance(value.get("quote_failures"), dict)
                or value.get("state") not in {"READY", "PARTIAL", "CANNOT_CONFIRM"}):
            raise ValueError("SCHEDULED_SCOPE_COVERAGE_INVALID")
        valid, gaps = _validated_quotes(quotes, symbols, source_session, value["captured_at"], value["quote_failures"])
        state = "READY" if len(valid) == len(symbols) else "PARTIAL" if valid else "CANNOT_CONFIRM"
        return dict(state=state, gap=None if state == "READY" else "US_SCHEDULED_QUOTE_SCOPE_PARTIAL",
                    owner=OWNER, scope_sha256=SCOPE_SHA, us_session_date=source_session,
                    trade_date=Path(payload_relative).parts[2], available_at=value["captured_at"],
                    requested_symbol_count=len(symbols), available_symbol_count=len(valid),
                    coverage_fraction=len(valid) / len(symbols), symbols=symbols, quotes=valid, symbol_gaps=gaps,
                    capture_origin="ORIGINAL_TIME_CAPTURE", original_time_capture=True,
                    late=late, capture_mode=capture.get("capture_mode"),
                    capture_timing="CONTROLLED_LATE_POST_CLOSE" if late else "NATURAL_SLOT",
                    capture_metadata=capture_metadata,
                    payload_relative=payload_relative, payload_sha256=payload_sha256,
                    receipt_relative=receipt_relative, receipt_sha256=receipt_sha256,
                    manifest_relative="research/peripherals/manifest.json", manifest_sha256=manifest_sha256,
                    source_response_sha256=value["source_response_sha256"],
                    checked_files=[dict(relative=payload_relative, sha256=payload_sha256),
                                   dict(relative=receipt_relative, sha256=receipt_sha256),
                                   dict(relative="research/peripherals/manifest.json", sha256=manifest_sha256)])
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        return unavailable
