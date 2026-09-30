"""apps.api.v35_api.research_lane_router: industry_projection (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __global_industry_rows_body(_v4_scope, /, reason):
    return [
        {
            "label": _v4_global(_v4_scope, 'str')(mapping["label"]),
            "group": _v4_global(_v4_scope, 'str')(mapping["group"]),
            "mapping_type": _v4_global(_v4_scope, 'str')(mapping["mapping_type"]),
            "proxy_symbols": _v4_global(_v4_scope, 'list')(mapping["proxy_symbols"]),
            "available_symbols": [],
            "missing_symbols": _v4_global(_v4_scope, 'list')(mapping["proxy_symbols"]),
            "requested_symbol_count": _v4_global(_v4_scope, 'len')(mapping["proxy_symbols"]),
            "available_symbol_count": 0,
            "coverage": {"available": 0, "requested": _v4_global(_v4_scope, 'len')(mapping["proxy_symbols"])},
            "coverage_pct": 0.0,
            "change_pct": None,
            "pct_change": None,
            "direction": "CANNOT_CONFIRM",
            "status": "CANNOT_CONFIRM",
            "quote_session_dates": [],
            "quote_session_times": [],
            "cannot_confirm": [reason],
        }
        for mapping in _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_PROXY_MAP')
    ]


def __global_industry_missing_body(_v4_scope, /, *, research_date, reason):
    return {
        "schema_version": _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_SCHEMA_VERSION'),
        "status": "CANNOT_CONFIRM",
        "target_date": research_date,
        "target_trade_date": research_date,
        "research_date": research_date,
        "source_date": "",
        "artifact_trade_date": "",
        "us_session_date": "",
        "capture_session_date": "",
        "provider": "Tencent qt.gtimg.cn",
        "provider_receipt": None,
        "provider_session_dates": [],
        "provider_session_times": [],
        "source_response_sha256": "",
        "capture_phase": "POST_CLOSE",
        "captured_at": "",
        "generated_at": "",
        "mapping_version": _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_MAPPING_VERSION'),
        "requested_symbol_count": _v4_global(_v4_scope, 'len')({
            symbol for mapping in _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_PROXY_MAP') for symbol in mapping["proxy_symbols"]
        }),
        "available_symbol_count": 0,
        "rows": _v4_global(_v4_scope, '_global_industry_rows')(reason),
        "quotes": [],
        "cannot_confirm": [reason],
        "artifact": None,
        "manifest": None,
        "receipt": None,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def __global_industry_lineage_body(_v4_scope, /, store, research_date, payload):
    artifact_path = store.root / "research" / "peripherals" / research_date / "external_finance.json"
    receipt_path = store.root / "receipts" / "research" / "peripherals" / research_date / "external_finance.json"
    manifest_path = store.root / "research" / "peripherals" / "manifest.json"
    result: dict[str, Any] = {"path": _v4_global(_v4_scope, 'str')(artifact_path), "sha256": _v4_global(_v4_scope, '_sha256')(payload)}
    try:
        receipt = _v4_global(_v4_scope, 'json').loads(receipt_path.read_text(encoding="utf-8"))
        manifest = _v4_global(_v4_scope, 'json').loads(manifest_path.read_text(encoding="utf-8"))
        result["receipt"] = {"path": _v4_global(_v4_scope, 'str')(receipt_path), "sha256": _v4_global(_v4_scope, '_sha256')(receipt)}
        result["manifest"] = {"path": _v4_global(_v4_scope, 'str')(manifest_path), "sha256": _v4_global(_v4_scope, '_sha256')(manifest)}
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'json').JSONDecodeError):
        result["lineage_status"] = "CANNOT_CONFIRM"
    return result


def __project_global_industries_body(_v4_scope, /, *, store, research_date):
    try:
        payload = store.read_exact(research_date, "external_finance")
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        return _v4_global(_v4_scope, '_global_industry_missing')(
            research_date=research_date,
            reason=f"EXACT_EXTERNAL_FINANCE_INVALID:{_v4_global(_v4_scope, 'type')(error).__name__}",
        )
    if payload is None:
        return _v4_global(_v4_scope, '_global_industry_missing')(
            research_date=research_date,
            reason="EXACT_EXTERNAL_FINANCE_NOT_MATERIALIZED",
        )
    snapshot = payload.get("market_snapshot")
    if not _v4_global(_v4_scope, 'isinstance')(snapshot, _v4_global(_v4_scope, 'Mapping')):
        result = _v4_global(_v4_scope, '_global_industry_missing')(
            research_date=research_date,
            reason="MARKET_SNAPSHOT_NOT_MATERIALIZED",
        )
        result["source_date"] = _v4_global(_v4_scope, 'str')(payload.get("trade_date") or "")
        result["artifact"] = _v4_global(_v4_scope, '_global_industry_lineage')(store, research_date, payload)
        result["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            _v4_global(_v4_scope, 'set')(result["cannot_confirm"]) | _v4_global(_v4_scope, 'set')(payload.get("cannot_confirm") or [])
        )
        return result
    if (
        snapshot.get("schema_version") != _v4_global(_v4_scope, 'MARKET_SNAPSHOT_SCHEMA_VERSION')
        or snapshot.get("mapping_version") != _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_MAPPING_VERSION')
    ):
        result = _v4_global(_v4_scope, '_global_industry_missing')(
            research_date=research_date,
            reason="MARKET_SNAPSHOT_CANONICAL_VERSION_INVALID",
        )
        result["source_date"] = _v4_global(_v4_scope, 'str')(payload.get("trade_date") or "")
        result["artifact"] = _v4_global(_v4_scope, '_global_industry_lineage')(store, research_date, payload)
        return result
    if _v4_global(_v4_scope, 'any')(
        snapshot.get(field) != expected
        for field, expected in {
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "RESEARCH_ONLY": True,
        }.items()
    ):
        result = _v4_global(_v4_scope, '_global_industry_missing')(
            research_date=research_date,
            reason="MARKET_SNAPSHOT_SAFETY_BOUNDARY_INVALID",
        )
        result["source_date"] = _v4_global(_v4_scope, 'str')(payload.get("trade_date") or "")
        result["artifact"] = _v4_global(_v4_scope, '_global_industry_lineage')(store, research_date, payload)
        return result
    capture, identity_error = _v4_global(_v4_scope, '_bound_capture_for_snapshot')(
        payload=payload,
        snapshot=snapshot,
        research_date=research_date,
    )
    if identity_error is not None or capture is None:
        return _v4_global(_v4_scope, '_capture_identity_failure')(
            payload=payload,
            snapshot=snapshot,
            reason=identity_error or "MARKET_SNAPSHOT_CAPTURE_IDENTITY_UNBOUND",
            research_date=research_date,
            store=store,
        )
    session_date = _v4_global(_v4_scope, 'str')(snapshot.get("capture_session_date") or "")
    rows = _v4_global(_v4_scope, 'list')(snapshot.get("rows") or [])
    canonical_rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP'))
    if _v4_global(_v4_scope, 'len')(rows) != 24 or _v4_global(_v4_scope, 'any')(
        not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))
        or row.get("label") != mapping["label"]
        or row.get("group") != mapping["group"]
        or row.get("mapping_type") != mapping["mapping_type"]
        or row.get("proxy_symbols") != _v4_global(_v4_scope, 'list')(mapping["proxy_symbols"])
        for row, mapping in _v4_global(_v4_scope, 'zip')(rows, canonical_rows)
    ):
        result = _v4_global(_v4_scope, '_global_industry_missing')(
            research_date=research_date,
            reason="MARKET_SNAPSHOT_ROW_COUNT_INVALID",
        )
        result["source_date"] = _v4_global(_v4_scope, 'str')(payload.get("trade_date") or "")
        result["artifact"] = _v4_global(_v4_scope, '_global_industry_lineage')(store, research_date, payload)
        return result
    lineage = _v4_global(_v4_scope, '_global_industry_lineage')(store, research_date, payload)
    provider_dates = _v4_global(_v4_scope, 'sorted')({
        _v4_global(_v4_scope, 'str')(item) for item in snapshot.get("provider_session_dates") or [] if _v4_global(_v4_scope, 'str')(item).strip()
    })
    cannot_confirm = _v4_global(_v4_scope, 'sorted')(
        _v4_global(_v4_scope, 'set')(payload.get("cannot_confirm") or []) | _v4_global(_v4_scope, 'set')(snapshot.get("cannot_confirm") or [])
    )
    result: dict[str, Any] = {
        "schema_version": _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_SCHEMA_VERSION'),
        "status": _v4_global(_v4_scope, 'str')(snapshot.get("status") or "CANNOT_CONFIRM"),
        "target_date": research_date,
        "target_trade_date": research_date,
        "research_date": research_date,
        "source_date": session_date,
        "artifact_trade_date": _v4_global(_v4_scope, 'str')(payload.get("trade_date") or research_date),
        "us_session_date": session_date,
        "provider": _v4_global(_v4_scope, 'str')(snapshot.get("provider") or snapshot.get("source") or "Tencent qt.gtimg.cn"),
        "provider_url": _v4_global(_v4_scope, 'str')(snapshot.get("provider_url") or "https://qt.gtimg.cn/q="),
        "provider_session_dates": provider_dates,
        "provider_session_times": _v4_global(_v4_scope, 'sorted')({
            _v4_global(_v4_scope, 'str')(item) for item in snapshot.get("provider_session_times") or [] if _v4_global(_v4_scope, 'str')(item).strip()
        }),
        "source_response_sha256": _v4_global(_v4_scope, 'str')(snapshot.get("source_response_sha256") or ""),
        "quotes": _v4_global(_v4_scope, 'list')(snapshot.get("quotes") or []),
        "provider_receipt": (
            _v4_global(_v4_scope, 'dict')(snapshot["provider_receipt"])
            if _v4_global(_v4_scope, 'isinstance')(snapshot.get("provider_receipt"), _v4_global(_v4_scope, 'Mapping'))
            else None
        ),
        "capture_phase": _v4_global(_v4_scope, 'str')(snapshot.get("capture_phase") or "POST_CLOSE"),
        "capture_session_date": session_date,
        "captured_at": _v4_global(_v4_scope, 'str')(snapshot.get("captured_at") or ""),
        "bound_capture_captured_at": capture.get("captured_at"),
        "generated_at": _v4_global(_v4_scope, 'str')(snapshot.get("generated_at") or snapshot.get("captured_at") or ""),
        "mapping_version": _v4_global(_v4_scope, 'str')(snapshot.get("mapping_version") or ""),
        "requested_symbol_count": _v4_global(_v4_scope, 'int')(snapshot.get("requested_symbol_count") or 0),
        "available_symbol_count": _v4_global(_v4_scope, 'int')(snapshot.get("available_symbol_count") or 0),
        "rows": rows,
        "cannot_confirm": cannot_confirm,
        "artifact": lineage,
        "manifest": lineage.get("manifest"),
        "receipt": lineage.get("receipt"),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    for field in (
        "capture_id",
        "run_id",
        "capture_origin",
        "original_time_capture",
        "late",
        "capture_mode",
        "reason",
        "capture_reason",
        "session_timezone",
        "capture_window_start",
        "capture_window_end",
        "natural_capture_window_start",
        "natural_capture_window_end",
        "allowed_recovery_window_start",
        "allowed_recovery_window_end",
    ):
        if field in capture:
            result[field] = capture[field]
    if result["capture_phase"] != "POST_CLOSE":
        result["status"] = "CANNOT_CONFIRM"
        result["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(
            _v4_global(_v4_scope, 'set')(cannot_confirm) | {"MARKET_SNAPSHOT_NOT_POST_CLOSE"}
        )
    if result["status"] != "CANNOT_CONFIRM" and _v4_global(_v4_scope, 'len')(provider_dates) > 1:
        result["status"] = "PARTIAL"
        result["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(cannot_confirm) | {"QUOTE_SESSION_DATE_MIXED"})
    return result
