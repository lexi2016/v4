"""apps.api.v35_api.research_lane_router: industry_projection (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global
from contracts.futu_industry import load_reviewed_business_relations, project_industry_rows
from contracts.futu_us_boards import (
    empty_futu_us_board_snapshot,
    validate_futu_us_board_snapshot,
)


_INDUSTRY_RESPONSE_SCHEMA_VERSION = "v3_5.global_industries.v2"


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
            "metric_kind": "OFFICIAL_BOARD",
            "official_board": {
                "metric_kind": "OFFICIAL_BOARD",
                "board_name": None,
                "board_code": None,
                "update_time": None,
                "session_date": None,
                "timezone": "America/New_York",
                "last": None,
                "previous_close": None,
                "change_pct": None,
                "plate_valid": None,
                "rise_count": None,
                "fall_count": None,
                "equal_count": None,
                "relations": [],
                "relation_status": "CANNOT_CONFIRM",
                "cannot_confirm": [reason],
            },
            "proxy_reference": {
                "metric_kind": "ETF_REFERENCE" if "basket" not in str(mapping["mapping_type"]) else "STOCK_BASKET_REFERENCE",
                "provider": "Tencent qt.gtimg.cn",
                "mapping_type": _v4_global(_v4_scope, 'str')(mapping["mapping_type"]),
                "proxy_symbols": _v4_global(_v4_scope, 'list')(mapping["proxy_symbols"]),
                "available_symbols": [],
                "missing_symbols": _v4_global(_v4_scope, 'list')(mapping["proxy_symbols"]),
                "requested_symbol_count": _v4_global(_v4_scope, 'len')(mapping["proxy_symbols"]),
                "available_symbol_count": 0,
                "coverage": {"available": 0, "requested": _v4_global(_v4_scope, 'len')(mapping["proxy_symbols"])},
                "coverage_pct": 0.0,
                "change_pct": None,
                "direction": "CANNOT_CONFIRM",
                "status": "CANNOT_CONFIRM",
                "quote_session_dates": [],
                "quote_session_times": [],
                "cannot_confirm": [reason],
            },
        }
        for mapping in _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_PROXY_MAP')
    ]


def __global_industry_missing_body(_v4_scope, /, *, research_date, reason):
    return {
        "schema_version": _INDUSTRY_RESPONSE_SCHEMA_VERSION,
        "status": "CANNOT_CONFIRM",
        "target_date": research_date,
        "target_trade_date": research_date,
        "research_date": research_date,
        "source_date": "",
        "artifact_trade_date": "",
        "us_session_date": "",
        "capture_session_date": "",
        "provider": "Futu OpenD",
        "legacy_proxy_provider": "Tencent qt.gtimg.cn",
        "futu_board_snapshot": {"status": "CANNOT_CONFIRM", "source_response_sha256": "", "cannot_confirm": [reason]},
        "native_board_snapshot": None,
        "native_display_status": None,
        "relation_evidence": {"status": "CANNOT_CONFIRM", "cannot_confirm": ["RELATION_EVIDENCE_NOT_LOADED"]},
        "hk_relation_status": "CANNOT_CONFIRM",
        "a_share_relation_status": "NO_REVIEWED_A_SHARE_RELATION_EVIDENCE",
        "a_share_relations": [],
        "target_date_eligibility": "CANNOT_CONFIRM",
        "provider_receipt": None,
        "provider_session_dates": [],
        "provider_session_times": [],
        "source_response_sha256": "",
        "proxy_source_response_sha256": "",
        "requested_board_count": 24,
        "available_board_count": 0,
        "proxy_requested_symbol_count": _v4_global(_v4_scope, 'len')({symbol for mapping in _v4_global(_v4_scope, 'GLOBAL_INDUSTRY_PROXY_MAP') for symbol in mapping["proxy_symbols"]}),
        "proxy_available_symbol_count": 0,
        "proxy_quotes": [],
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
    futu_snapshot = snapshot.get("futu_board_snapshot")
    if not _v4_global(_v4_scope, 'isinstance')(futu_snapshot, _v4_global(_v4_scope, 'Mapping')):
        futu_snapshot = None
    reviewed_relations = load_reviewed_business_relations()
    projected_rows = project_industry_rows(
        rows,
        futu_snapshot=futu_snapshot,
        reviewed_evidence=reviewed_relations,
        capture_session_date=session_date,
    )
    ready_boards = _v4_global(_v4_scope, 'sum')(row["status"] == "READY" for row in projected_rows)
    industry_status = "READY" if ready_boards == 24 else "PARTIAL" if ready_boards else "CANNOT_CONFIRM"
    futu_reasons = _v4_global(_v4_scope, 'set')(
        futu_snapshot.get("cannot_confirm") or [] if futu_snapshot is not None else ["FUTU_BOARD_SNAPSHOT_MISSING"]
    )
    futu_reasons.update(
        reason for row in projected_rows for reason in row.get("cannot_confirm") or []
    )
    provider_dates = _v4_global(_v4_scope, 'sorted')({
        _v4_global(_v4_scope, 'str')(row["official_board"].get("session_date"))
        for row in projected_rows
        if row["status"] == "READY"
    })
    provider_times = _v4_global(_v4_scope, 'sorted')({
        _v4_global(_v4_scope, 'str')(row["official_board"].get("update_time"))
        for row in projected_rows
        if row["status"] == "READY" and row["official_board"].get("update_time")
    })
    relation_rows = [row["official_board"] for row in projected_rows]
    relation_statuses = {row.get("relation_status") for row in relation_rows}
    hk_relation_status = (
        "READY" if "READY" in relation_statuses
        else "NO_REVIEWED_RELATION_INTERSECTION" if reviewed_relations.get("status") == "READY" and "CANNOT_CONFIRM" not in relation_statuses
        else "CANNOT_CONFIRM"
    )
    relation_review = reviewed_relations.get("review") or {}
    relation_meta = {
        "status": reviewed_relations.get("status", "CANNOT_CONFIRM"),
        "evidence_path": reviewed_relations.get("evidence_path"),
        "evidence_sha256": reviewed_relations.get("evidence_sha256"),
        "review_path": reviewed_relations.get("review_path"),
        "review_sha256": reviewed_relations.get("review_sha256"),
        "reviewed_at": relation_review.get("reviewed_at"),
        "reviewer_identity": relation_review.get("reviewer_identity"),
        "limitations": list(relation_review.get("CANNOT_CONFIRM") or []),
        "cannot_confirm": list(reviewed_relations.get("cannot_confirm") or []),
        "target_date_eligibility": "CANNOT_CONFIRM",
    }
    proxy_status = _v4_global(_v4_scope, 'str')(snapshot.get("status") or "CANNOT_CONFIRM")
    proxy_dates = _v4_global(_v4_scope, 'sorted')({
        _v4_global(_v4_scope, 'str')(item) for item in snapshot.get("provider_session_dates") or [] if _v4_global(_v4_scope, 'str')(item).strip()
    })
    proxy_times = _v4_global(_v4_scope, 'sorted')({
        _v4_global(_v4_scope, 'str')(item) for item in snapshot.get("provider_session_times") or [] if _v4_global(_v4_scope, 'str')(item).strip()
    })
    futu_metadata = {
        key: futu_snapshot.get(key)
        for key in ("schema_version", "status", "provider", "market", "timezone", "capture_session_date", "source_response_sha256", "cannot_confirm")
    } if futu_snapshot is not None else {
        "schema_version": "v3_5.futu_us_industry_snapshot.v1",
        "status": "CANNOT_CONFIRM",
        "provider": "Futu OpenD",
        "market": "US",
        "timezone": "America/New_York",
        "capture_session_date": session_date,
        "source_response_sha256": "",
        "cannot_confirm": ["FUTU_BOARD_SNAPSHOT_MISSING"],
    }
    native_board_snapshot = None
    native_candidate = futu_snapshot.get("native_board_snapshot") if futu_snapshot is not None else None
    if native_candidate is not None:
        try:
            native_board_snapshot = validate_futu_us_board_snapshot(
                native_candidate,
                expected_session_date=session_date,
            )
        except (TypeError, ValueError) as error:
            native_board_snapshot = empty_futu_us_board_snapshot(
                session_date,
                f"FUTU_NATIVE_BOARD_SNAPSHOT_INVALID:{type(error).__name__}",
            )
    result: dict[str, Any] = {
        "schema_version": _INDUSTRY_RESPONSE_SCHEMA_VERSION,
        "status": industry_status,
        "legacy_proxy_status": proxy_status,
        "target_date": research_date,
        "target_trade_date": research_date,
        "research_date": research_date,
        "source_date": session_date,
        "artifact_trade_date": _v4_global(_v4_scope, 'str')(payload.get("trade_date") or research_date),
        "us_session_date": session_date,
        "provider": "Futu OpenD",
        "legacy_proxy_provider": _v4_global(_v4_scope, 'str')(snapshot.get("provider") or snapshot.get("source") or "Tencent qt.gtimg.cn"),
        "provider_url": "",
        "provider_session_dates": provider_dates,
        "provider_session_times": provider_times,
        "source_response_sha256": _v4_global(_v4_scope, 'str')((futu_snapshot or {}).get("source_response_sha256") or ""),
        "proxy_source_response_sha256": _v4_global(_v4_scope, 'str')(snapshot.get("source_response_sha256") or ""),
        "quotes": [],
        "proxy_quotes": _v4_global(_v4_scope, 'list')(snapshot.get("quotes") or []),
        "provider_receipt": None,
        "futu_board_snapshot": futu_metadata,
        "native_board_snapshot": native_board_snapshot,
        "native_display_status": None,
        "relation_evidence": relation_meta,
        "hk_relation_status": hk_relation_status,
        "a_share_relation_status": "NO_REVIEWED_A_SHARE_RELATION_EVIDENCE",
        "a_share_relations": [],
        "target_date_eligibility": "CANNOT_CONFIRM",
        "capture_phase": _v4_global(_v4_scope, 'str')(snapshot.get("capture_phase") or "POST_CLOSE"),
        "capture_session_date": session_date,
        "captured_at": _v4_global(_v4_scope, 'str')(snapshot.get("captured_at") or ""),
        "bound_capture_captured_at": capture.get("captured_at"),
        "generated_at": _v4_global(_v4_scope, 'str')(snapshot.get("generated_at") or snapshot.get("captured_at") or ""),
        "mapping_version": _v4_global(_v4_scope, 'str')(snapshot.get("mapping_version") or ""),
        "requested_symbol_count": 24,
        "available_symbol_count": ready_boards,
        "requested_board_count": 24,
        "available_board_count": ready_boards,
        "proxy_requested_symbol_count": _v4_global(_v4_scope, 'int')(snapshot.get("requested_symbol_count") or 0),
        "proxy_available_symbol_count": _v4_global(_v4_scope, 'int')(snapshot.get("available_symbol_count") or 0),
        "proxy_provider_session_dates": proxy_dates,
        "proxy_provider_session_times": proxy_times,
        "rows": projected_rows,
        "cannot_confirm": _v4_global(_v4_scope, 'sorted')(futu_reasons),
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
            _v4_global(_v4_scope, 'set')(result["cannot_confirm"]) | {"MARKET_SNAPSHOT_NOT_POST_CLOSE"}
        )
    if result["status"] != "CANNOT_CONFIRM" and _v4_global(_v4_scope, 'len')(provider_dates) > 1:
        result["status"] = "PARTIAL"
        result["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(result["cannot_confirm"]) | {"BOARD_SESSION_DATE_MIXED"})
    return result
