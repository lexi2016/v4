"""Existing exact-date HK industry response/cache helpers, restored from the frozen V4 owner snapshot."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.parse
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from infrastructure.data_store import _date, _sha256
from infrastructure.http_transport import ProxyAwareHTTPTransport, TransportError
from infrastructure.owned_io import SafeRoot
from infrastructure.research_peripheral_store import HK_INDUSTRY_SOURCE

_CST = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) v3.5-research-peripherals/1.0"


def isoformat_utc(value: datetime | str | None) -> str:
    if value is None:
        parsed = datetime.now(UTC).replace(microsecond=0)
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


HK_INDUSTRY_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"

HK_INDUSTRY_SOURCE_ID = "EASTMONEY_F10_RPT_HKF10_INFO_ORGPROFILE"

HK_INDUSTRY_CACHE_SCHEMA = "v3_5.hk_industry_response_cache.v1"

def _hk_symbol_code(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    match = re.fullmatch(r"HK\.(\d{5})", value)
    if not match:
        raise ValueError("HK_INDUSTRY_SYMBOL_INVALID")
    return match.group(1)

def _hk_industry_url(symbol: str) -> str:
    provider_code = _hk_symbol_code(symbol)
    params = {
        "reportName": "RPT_HKF10_INFO_ORGPROFILE",
        "columns": "SECUCODE,SECURITY_CODE,ORG_NAME,BELONG_INDUSTRY",
        "filter": f'(SECUCODE="{provider_code}.HK")',
        "pageNumber": "1",
        "pageSize": "200",
        "source": "F10",
        "client": "PC",
    }
    return f"{HK_INDUSTRY_URL}?{urllib.parse.urlencode(params)}"

def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def _hk_capture_timestamp() -> str:
    """Record the real capture instant in Hong Kong's calendar timezone."""
    return datetime.now(UTC).astimezone(_CST).isoformat(timespec="microseconds")

def _read_hk_industry_cache(cache_root: Path, trade_date: str, symbol: str) -> dict[str, Any] | None:
    relative = f"{trade_date}/{symbol}.json"
    try:
        raw_cache = SafeRoot(cache_root).read_bytes(relative)
    except FileNotFoundError:
        return None
    value = json.loads(raw_cache.decode("utf-8"))
    if (not isinstance(value, dict)
            or value.get("schema_version") != HK_INDUSTRY_CACHE_SCHEMA
            or value.get("trade_date") != trade_date
            or value.get("symbol") != symbol):
        raise ValueError("HK_INDUSTRY_CACHE_IDENTITY_INVALID")
    if value.get("source_asof") is not None or value.get("source_asof_status") != "UNKNOWN":
        raise ValueError("HK_INDUSTRY_CACHE_ASOF_INVALID")
    captured_at = value.get("captured_at")
    if not isinstance(captured_at, str):
        raise ValueError("HK_INDUSTRY_CACHE_CAPTURE_TIME_MISSING")
    datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    body_b64 = value.get("raw_body_base64")
    body_sha = value.get("raw_response_sha256")
    if body_b64 is not None:
        try:
            raw = base64.b64decode(body_b64, validate=True)
        except (ValueError, base64.binascii.Error) as error:
            raise ValueError("HK_INDUSTRY_CACHE_BODY_INVALID") from error
        if _sha256_bytes(raw) != body_sha:
            raise ValueError("HK_INDUSTRY_CACHE_SHA_MISMATCH")
    elif body_sha is not None:
        raise ValueError("HK_INDUSTRY_CACHE_BODY_MISSING")
    if value.get("http_status") is None and not value.get("error_code"):
        raise ValueError("HK_INDUSTRY_CACHE_OUTCOME_MISSING")
    return {**value, "cache_status": "HIT"}

def _write_hk_industry_cache(cache_root: Path, value: Mapping[str, Any]) -> None:
    relative = f"{value['trade_date']}/{value['symbol']}.json"
    normalized = dict(value)
    safe = SafeRoot(cache_root)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        existing = json.loads(safe.read_bytes(relative).decode("utf-8"))
    except FileNotFoundError:
        safe.write_bytes(relative, encoded, require_absent=True)
        return
    else:
        if existing != normalized:
            raise ValueError("HK_INDUSTRY_CACHE_CONFLICT")

def seed_hk_industry_response_cache(
    *, cache_root: Path, trade_date: str, symbol: str, raw_response_path: Path,
    captured_at: str, expected_sha256: str,
) -> dict[str, Any]:
    """Seed a verified local provider response without making a network request."""
    selected_date = _date(trade_date)
    code = _hk_symbol_code(symbol)
    raw_path = Path(raw_response_path)
    if raw_path.is_symlink() or not raw_path.is_file():
        raise ValueError("HK_INDUSTRY_SEED_RESPONSE_UNAVAILABLE")
    raw = raw_path.read_bytes()
    digest = _sha256_bytes(raw)
    if digest != expected_sha256:
        raise ValueError("HK_INDUSTRY_SEED_RESPONSE_SHA_MISMATCH")
    captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("HK_INDUSTRY_SEED_CAPTURE_TIME_INVALID")
    entry = {
        "schema_version": HK_INDUSTRY_CACHE_SCHEMA,
        "trade_date": selected_date,
        "symbol": symbol,
        "provider_code": f"{code}.HK",
        "request_url": _hk_industry_url(symbol),
        "http_status": 200,
        "transport_receipt": {},
        "captured_at": captured.astimezone(_CST).isoformat(timespec="microseconds"),
        "source_asof": None,
        "source_asof_status": "UNKNOWN",
        "raw_response_sha256": digest,
        "raw_body_base64": base64.b64encode(raw).decode("ascii"),
        "error_code": None,
        "error_detail": None,
        "seed_source": str(raw_path),
    }
    _write_hk_industry_cache(Path(cache_root), entry)
    return {"symbol": symbol, "raw_response_sha256": digest, "cache_relative": f"{selected_date}/{symbol}.json"}

def _capture_hk_industry_response(
    *, trade_date: str, symbol: str, cache_root: Path,
    transport: ProxyAwareHTTPTransport, timeout: int,
) -> dict[str, Any]:
    cached = _read_hk_industry_cache(cache_root, trade_date, symbol)
    if cached is not None:
        return cached
    url = _hk_industry_url(symbol)
    captured_at = _hk_capture_timestamp()
    try:
        result = transport.fetch(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        captured_at = _hk_capture_timestamp()
        entry = {
            "schema_version": HK_INDUSTRY_CACHE_SCHEMA,
            "trade_date": trade_date,
            "symbol": symbol,
            "provider_code": f"{_hk_symbol_code(symbol)}.HK",
            "request_url": url,
            "http_status": int(result.receipt.get("http_status") or 200),
            "transport_receipt": dict(result.receipt),
            "captured_at": captured_at,
            "source_asof": None,
            "source_asof_status": "UNKNOWN",
            "raw_response_sha256": _sha256_bytes(result.body),
            "raw_body_base64": base64.b64encode(result.body).decode("ascii"),
            "error_code": None,
            "error_detail": None,
        }
    except TransportError as error:
        captured_at = _hk_capture_timestamp()
        receipt = dict(error.receipt)
        entry = {
            "schema_version": HK_INDUSTRY_CACHE_SCHEMA,
            "trade_date": trade_date,
            "symbol": symbol,
            "provider_code": f"{_hk_symbol_code(symbol)}.HK",
            "request_url": url,
            "http_status": receipt.get("http_status"),
            "transport_receipt": receipt,
            "captured_at": captured_at,
            "source_asof": None,
            "source_asof_status": "UNKNOWN",
            "raw_response_sha256": None,
            "raw_body_base64": None,
            "error_code": str(receipt.get("error") or "PUBLIC_HTTP_TRANSPORT_ERROR"),
            "error_detail": str(error)[:240],
        }
    _write_hk_industry_cache(cache_root, entry)
    return {**entry, "cache_status": "MISS"}

def build_hk_industry_peripheral_payload(
    *, trade_date: str, membership: Mapping[str, Any], requested_codes: Sequence[str],
    outcomes: Sequence[Mapping[str, Any]], fetched_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Build an immutable full-scope artifact from exact, per-issuer responses."""
    selected_date = _date(trade_date)
    scope_codes = sorted(set(str(code) for code in membership["codes"]))
    requested = sorted(set(str(code) for code in requested_codes))
    if (not scope_codes or not requested or not set(requested).issubset(scope_codes)
            or any(not re.fullmatch(r"HK\.\d{5}", code) for code in (*scope_codes, *requested))):
        raise ValueError("HK_INDUSTRY_REQUEST_SCOPE_INVALID")
    outcome_by_symbol = {str(row.get("symbol")): dict(row) for row in outcomes}
    if len(outcome_by_symbol) != len(outcomes) or set(outcome_by_symbol) != set(requested):
        raise ValueError("HK_INDUSTRY_OUTCOME_COVERAGE_INVALID")
    items: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    raw_item_count = 0
    status_inputs: list[dict[str, Any]] = []
    for symbol in requested:
        outcome = outcome_by_symbol[symbol]
        url = str(outcome.get("request_url") or _hk_industry_url(symbol))
        captured_at = str(outcome.get("captured_at") or "")
        body_b64 = outcome.get("raw_body_base64")
        raw: bytes | None = None
        if body_b64 is not None:
            try:
                raw = base64.b64decode(body_b64, validate=True)
            except (ValueError, base64.binascii.Error) as error:
                raise ValueError("HK_INDUSTRY_RESPONSE_CACHE_BODY_INVALID") from error
            body_sha = _sha256_bytes(raw)
            if body_sha != outcome.get("raw_response_sha256"):
                raise ValueError("HK_INDUSTRY_RESPONSE_CACHE_SHA_MISMATCH")
            raw_responses.append({
                "symbol": symbol,
                "request_url": url,
                "http_status": outcome.get("http_status"),
                "captured_at": captured_at,
                "raw_response_sha256": body_sha,
                "raw_body_base64": body_b64,
                "cache_status": outcome.get("cache_status", "HIT"),
                "transport_receipt": dict(outcome.get("transport_receipt") or {}),
            })
            try:
                response = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                response = None
                failure_code = "INVALID_JSON_RESPONSE"
            else:
                failure_code = None
            rows = (((response or {}).get("result") or {}).get("data")
                if isinstance(response, dict) and response.get("success") is True
                and response.get("code") == 0 and isinstance(response.get("result"), dict)
                else None)
            if failure_code is None and not isinstance(rows, list):
                failure_code = "PROVIDER_RESPONSE_CONTRACT_INVALID"
            if isinstance(rows, list):
                raw_item_count += len(rows)
            matching = []
            if isinstance(rows, list):
                provider_code = f"{_hk_symbol_code(symbol)}.HK"
                for row in rows:
                    if isinstance(row, dict) and str(row.get("SECUCODE") or "").strip().upper() == provider_code:
                        matching.append(row)
            if failure_code is None and len(matching) != 1:
                failure_code = "ISSUER_ROW_MISSING" if not matching else "ISSUER_ROW_DUPLICATE"
            if failure_code is None:
                row = matching[0]
                security_code = str(row.get("SECURITY_CODE") or "").strip().zfill(5)
                if security_code != _hk_symbol_code(symbol):
                    failure_code = "ISSUER_IDENTITY_MISMATCH"
                else:
                    normalized = dict(
                        symbol=symbol,
                        provider_code=str(row.get("SECUCODE") or "").strip().upper(),
                        security_code=str(row.get("SECURITY_CODE") or "").strip(),
                        issuer_name=row.get("ORG_NAME") if isinstance(row.get("ORG_NAME"), str) else None,
                        source_industry=row.get("BELONG_INDUSTRY") if isinstance(row.get("BELONG_INDUSTRY"), str) else None,
                        source_response_sha256=body_sha,
                        source_response_ref=f"research/peripherals/{selected_date}/{HK_INDUSTRY_SOURCE}.json#raw_response_sha256={body_sha}",
                        source_row_sha256=_sha256(row),
                        captured_at=captured_at,
                    )
                    items.append(normalized)
            if failure_code is not None:
                failures.append({
                    "symbol": symbol,
                    "error_code": failure_code,
                    "http_status": outcome.get("http_status"),
                    "request_url": url,
                    "captured_at": captured_at,
                    "detail": str(outcome.get("error_detail") or failure_code)[:240],
                })
        else:
            failures.append({
                "symbol": symbol,
                "error_code": str(outcome.get("error_code") or "PUBLIC_HTTP_TRANSPORT_ERROR"),
                "http_status": outcome.get("http_status"),
                "request_url": url,
                "captured_at": captured_at,
                "detail": str(outcome.get("error_detail") or outcome.get("error_code") or "PUBLIC_HTTP_TRANSPORT_ERROR")[:240],
            })
        status_inputs.append({
            "symbol": symbol,
            "raw_response_sha256": outcome.get("raw_response_sha256"),
            "error_code": next((failure["error_code"] for failure in failures if failure["symbol"] == symbol), None),
        })
    if not items:
        status = "CANNOT_CONFIRM"
    elif failures:
        status = "PARTIAL"
    else:
        status = "READY"
    captured_times = [outcome_by_symbol[code].get("captured_at") for code in requested]
    captured_dt = max(datetime.fromisoformat(str(value).replace("Z", "+00:00")) for value in captured_times)
    captured_iso = captured_dt.astimezone(_CST).isoformat(timespec="microseconds")
    finish_iso = isoformat_utc(fetched_at) if fetched_at is not None else datetime.now(UTC).isoformat().replace("+00:00", "Z")
    target_day = datetime.strptime(selected_date, "%Y%m%d").date()
    capture_day = captured_dt.astimezone(_CST).date()
    date_semantics = (
        "CAPTURED_AFTER_TARGET_DATE_SOURCE_ASOF_UNKNOWN"
        if capture_day > target_day
        else "CAPTURED_ON_OR_BEFORE_TARGET_DATE_SOURCE_ASOF_UNKNOWN"
    )
    return {
        "schema_version": "v3_5.research_peripheral.v1",
        "trade_date": selected_date,
        "source": HK_INDUSTRY_SOURCE,
        "status": status,
        "source_url": HK_INDUSTRY_URL,
        "fetched_at": finish_iso,
        "captured_at": captured_iso,
        "source_asof": None,
        "source_asof_status": "UNKNOWN",
        "source_date_semantics": date_semantics,
        "source_id": HK_INDUSTRY_SOURCE_ID,
        "provider": "EASTMONEY_F10",
        "market": "HK_CONNECT",
        "scope_type": "HK_CONNECT_FULL_MARKET",
        "scope_codes": scope_codes,
        "scope_count": len(scope_codes),
        "scope_codes_sha256": membership["scope_codes_sha256"],
        "membership_codes_sha256": membership["codes_sha256"],
        "membership_artifact_sha256": membership["membership_artifact_sha256"],
        "membership_owner": membership["membership_owner"],
        "membership_relative": membership["membership_relative"],
        "membership_source_root": membership["membership_source_root"],
        "membership_source_refs": [dict(item) for item in membership.get("membership_source_refs", [])],
        "membership_available_at": membership["membership_available_at"],
        "membership_effective_from": membership["membership_effective_from"],
        "membership_effective_through": membership["membership_effective_through"],
        "requested_codes": requested,
        "raw_responses": raw_responses,
        "failures": failures,
        "batch_response_sha256": _sha256(status_inputs),
        "raw_item_count": raw_item_count,
        "item_count": len(items),
        "overview": [],
        "details": [],
        "items": items,
        "cannot_confirm": sorted(f"{row['symbol']}:{row['error_code']}" for row in failures),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
