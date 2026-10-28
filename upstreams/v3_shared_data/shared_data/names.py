"""Verified shared Hong Kong security-name dictionary reader."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from .hashing import sha256_file
from .paths import resolve_under
from .store import StoreError


# HKEX's temporary counter 02915 identifies Yunji from 2026-09-23 through
# 2026-10-29. Keep this bounded: the code's identity before and after this
# window remains whatever the dated source row says.
_DATED_HK_NAME_OVERRIDES = (
    {
        "code": "HK.02915",
        "name": "云迹",
        "effective_from": "20260923",
        "effective_through": "20261029",
        "effective_from_sources": (
            {
                "authority": "HKEX",
                "url": "https://www.hkex.com.hk/eng/market/sec_tradinfo/tradarng/tradarng_news/premonth/e2915e_260921.htm",
                "claim": "Temporary counter 2915 replaces 2670 from 2026-09-23.",
            },
            {
                "authority": "SSE",
                "url": "https://big5.sse.com.cn/site/cht/www.sse.com.cn/services/hkexsc/disclo/announ/c/c_20260922_10832987.shtml",
                "claim": "YUNJI 云迹 enters the connect list as 02915, effective 2026-09-23.",
            },
        ),
        "effective_through_sources": (
            {
                "authority": "Sina Finance",
                "url": "https://finance.sina.com.cn/stock/aigc/hkgg/2026-09-01/doc-iniqitrs1514674.shtml",
            },
            {
                "authority": "Tiger Brokers",
                "url": "https://www.itiger.com/news/1181816831",
            },
        ),
        "effective_through_source_quality": "SECONDARY_CROSS_SOURCE_TIMETABLE",
    },
)


def _normalize_hk_name_code(value: object) -> str:
    text = str(value or "").strip().upper()
    match = re.fullmatch(r"(?:HK\.)?(\d{1,5})(?:\.HK(?:_CONNECT)?)?", text)
    return f"HK.{match.group(1).zfill(5)}" if match else ""


def _normalize_hk_name_date(value: object) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{8}", text):
        return ""
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return ""
    return text


def resolve_hk_name_for_date(
    code: object,
    *,
    trade_date: object,
    source_name: object,
) -> tuple[str, dict[str, object] | None]:
    """Resolve a display name within a source-backed, bounded effective window.

    The source row remains authoritative outside an explicitly evidenced
    interval. Returned metadata describes only the display projection and is
    not a security-master, tradability, or PIT-safety assertion.
    """
    normalized_code = _normalize_hk_name_code(code)
    override = next(
        (
            item
            for item in _DATED_HK_NAME_OVERRIDES
            if item["code"] == normalized_code
        ),
        None,
    )
    if override is None:
        return str(source_name or ""), None

    as_of = _normalize_hk_name_date(trade_date)
    status = "CANNOT_CONFIRM_DATE"
    resolved_name = str(source_name or "")
    if as_of:
        if as_of < str(override["effective_from"]):
            status = "SOURCE_NAME_BEFORE_EFFECTIVE_DATE"
        elif as_of > str(override["effective_through"]):
            status = "SOURCE_NAME_AFTER_EFFECTIVE_WINDOW"
        else:
            status = "EFFECTIVE_DATE_OVERRIDE"
            resolved_name = str(override["name"])

    resolution: dict[str, object] = {
        "schema_version": "v4.hk_name_resolution.v1",
        "status": status,
        "code": normalized_code,
        "trade_date": as_of or str(trade_date or ""),
        "raw_name": str(source_name or ""),
        "resolved_name": resolved_name,
        "effective_from": str(override["effective_from"]),
        "effective_through": str(override["effective_through"]),
        "effective_from_sources": [dict(item) for item in override["effective_from_sources"]],
        "effective_through_sources": [dict(item) for item in override["effective_through_sources"]],
        "effective_through_source_quality": str(override["effective_through_source_quality"]),
        "scope": "DISPLAY_NAME_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    return resolved_name, resolution


def load_verified_hk_names(store_root: Path | str) -> tuple[dict[str, str], str]:
    asset_root = Path(store_root) / "assets" / "hk_0_2"
    try:
        pointer = json.loads((asset_root / "name_latest.json").read_text(encoding="utf-8"))
        manifest_path = resolve_under(
            asset_root, str(pointer.get("manifest_relative") or "")
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        dictionary_path = resolve_under(
            asset_root, str(manifest.get("dictionary_relative") or "")
        )
    except (OSError, ValueError, TypeError) as error:
        raise StoreError(f"HK name dictionary metadata invalid: {error}") from error
    dictionary_sha = sha256_file(dictionary_path)
    if dictionary_sha != str(manifest.get("dictionary_sha256") or ""):
        raise StoreError("HK name dictionary checksum mismatch")
    names: dict[str, str] = {}
    with dictionary_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            if code and name:
                names[code] = name
    return names, dictionary_sha


__all__ = ["load_verified_hk_names", "resolve_hk_name_for_date"]
