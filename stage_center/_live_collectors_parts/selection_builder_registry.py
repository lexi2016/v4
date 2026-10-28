"""stage_center.live_collectors: selection_builder_registry (review candidate, not deployment)."""
from __future__ import annotations
import hashlib
import json
from ._namespace import read_global as _v4_global


_HK_0930_RESEARCH_CONTRACT = "historical_observation_contract=HK_STAGE0930_RESEARCH_ONLY"
_HK_0930_RESEARCH_SOURCE_ID = "hk_stage0930_research_observation_r1"
_HK_0930_BASE_RAW_SHA256 = "eabaa273897b0db7261d0e0d3245493e75297e5f148edad665061d90fb5f6070"
_HK_0930_GAP_FIELDS_SHA256 = "11e256bec4ee181f956bb2792260290b1e2b5784a9838ebef91b3074eebbcc3e"
_HK_0930_GAP_CSV_SHA256 = "d02371d0d8fdb28fad944bc0881943ba1deb4899bf57b11f9a4f3d1adb6a7546"
_HK_0930_GAP_RECEIPT_SHA256 = "1d1d6cbd74aff12d48cfa250551430ec8e7a046075a8769438c93e974375996a"
_HK_0930_D1_POOL_SHA256 = "c6202648a73d0103b2ec43e393618ca31e67183c730a4df4db018eced2cfacd0"
_HK_0930_D1_CODES_SHA256 = "07e8760a9c3171691d26a43240795c6b56e7a494fadb6acbd5f153b7801b7b34"
_HK_0930_MISSING_LAST_PRICE = frozenset(
    {"HK.03268", "HK.03355", "HK.03881", "HK.09690"}
)
_HK_0930_ZERO_VOLUME_REFERENCE = frozenset(
    {"HK.01304", "HK.01333", "HK.01377"}
)
_HK_0930_SOURCE_IDS = frozenset(
    {
        "futu_request_history_kline_none",
        "EASTMONEY_HK_HISTORICAL_1M",
        "YAHOO_FINANCE_CHART_1M",
    }
)
_HK_0930_TDX_RESEARCH_MODE_EVIDENCE = (
    "stage_center_observation_mode=HK_STAGE0930_TDX_AFTERFACT_RESEARCH_20260924_R1"
)
_HISTORICAL_OBSERVATION_MODE_PREFIX = (
    "stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:"
)
_HK_ACTIVE_SNAPSHOT_ISOLATION_POLICY = "active_snapshot_policy=PER_STOCK_TEMPORAL_ELIGIBILITY_V1"


def _historical_observation_contract_errors(source, plan, raw):
    """Revalidate a manifest-bound after-fact raw observation before ranking."""
    from stage_center.raw_store import (
        _allows_manifest_bound_afterfact_observation,
        _historical_observation_manifest,
    )

    evidence = tuple(str(item) for item in source.source_evidence)
    raw_evidence = tuple(str(item) for item in raw.get("source_evidence", ()))
    modes = [item for item in evidence if item.startswith(_HISTORICAL_OBSERVATION_MODE_PREFIX)]
    errors = []

    def require(condition, reason):
        if not condition:
            errors.append(reason)

    require(len(modes) == 1, "HISTORICAL_OBSERVATION_MODE_UNREGISTERED")
    token = modes[0].split("=", 1)[1] if len(modes) == 1 else None
    parsed = _historical_observation_manifest(evidence, contract=token)
    require(parsed is not None, "HISTORICAL_OBSERVATION_MANIFEST_SHA_MISMATCH")
    require(plan.stage_id != "STAGE_0925", "HISTORICAL_OBSERVATION_AUCTION_STAGE_UNSUPPORTED")
    require(plan.trade_date == raw.get("trade_date"), "HISTORICAL_OBSERVATION_DATE_MISMATCH")
    require(plan.stage_id == raw.get("stage_id"), "HISTORICAL_OBSERVATION_STAGE_MISMATCH")
    require(raw.get("market") == "HK_CONNECT", "HISTORICAL_OBSERVATION_MARKET_MISMATCH")
    require(source.source_id in {"pytdx_exhq", "futu_cached_minute_capture"},
            "HISTORICAL_OBSERVATION_SOURCE_ID_MISMATCH")
    require(source.status == "PARTIAL_WITH_ROWS", "HISTORICAL_OBSERVATION_SOURCE_STATUS_MISMATCH")
    require(raw.get("source_id") == source.source_id, "HISTORICAL_OBSERVATION_RAW_SOURCE_MISMATCH")
    require(raw.get("status") == "PARTIAL_WITH_ROWS", "HISTORICAL_OBSERVATION_RAW_STATUS_MISMATCH")
    require(raw.get("requested_rows") == source.requested_rows,
            "HISTORICAL_OBSERVATION_REQUESTED_ROWS_MISMATCH")
    require(raw.get("missing_symbols") == list(source.missing_symbols),
            "HISTORICAL_OBSERVATION_MISSING_COUNT_MISMATCH")
    require(raw.get("artifact_sha256") is not None,
            "HISTORICAL_OBSERVATION_RAW_SHA_MISSING")
    require(bool(raw_evidence) and set(raw_evidence).issubset(set(evidence)),
            "HISTORICAL_OBSERVATION_RAW_EVIDENCE_MISMATCH")
    require(all(not row.get("candidate_lanes") for row in source.rows),
            "HISTORICAL_OBSERVATION_CANDIDATE_LANE_PRESENT")
    if parsed is not None and token is not None:
        require(_allows_manifest_bound_afterfact_observation(
            contract=token,
            trade_date=plan.trade_date,
            stage_id=plan.stage_id,
            market="HK_CONNECT",
            source_id=source.source_id,
            source_status=source.status,
            rows=source.rows,
            requested_rows=source.requested_rows,
            missing_symbols=source.missing_symbols,
            cannot_confirm=source.cannot_confirm,
            source_evidence=evidence,
            raw_artifact_sha256=str(raw.get("artifact_sha256") or ""),
        ), "HISTORICAL_OBSERVATION_ROW_OR_LINEAGE_CONTRACT_MISMATCH")
    else:
        require(False, "HISTORICAL_OBSERVATION_ROW_OR_LINEAGE_CONTRACT_MISMATCH")
    require(_HISTORICAL_OBSERVATION_MODE_PREFIX + token.split(":", 1)[1] in raw_evidence
            if token and ":" in token else False,
            "HISTORICAL_OBSERVATION_RAW_MODE_MISMATCH")
    return tuple(dict.fromkeys(errors))


def _hk_0930_tdx_research_contract_errors(source, plan, raw):
    """Validate the one after-fact TDX observation before building its watch Top10."""
    from stage_center.raw_store import (
        HK_0930_TDX_D1_CODE_SET_SHA256,
        HK_0930_TDX_RESEARCH_MODE_EVIDENCE,
        _allows_hk_0930_tdx_temporal_false_observation,
    )

    evidence = tuple(str(item) for item in source.source_evidence)
    raw_evidence = tuple(str(item) for item in raw.get("source_evidence", ()))
    errors = []

    def require(condition, reason):
        if not condition:
            errors.append(reason)

    require(plan.trade_date == "20260924", "HK_0930_TDX_RESEARCH_DATE_MISMATCH")
    require(plan.stage_id == "STAGE_0930_0935", "HK_0930_TDX_RESEARCH_STAGE_MISMATCH")
    require(source.source_id == "pytdx_exhq", "HK_0930_TDX_RESEARCH_SOURCE_ID_MISMATCH")
    require(source.status == "PARTIAL_WITH_ROWS", "HK_0930_TDX_RESEARCH_SOURCE_STATUS_MISMATCH")
    require(source.requested_rows == 100 and len(source.rows) == 100,
            "HK_0930_TDX_RESEARCH_ROW_COUNT_MISMATCH")
    require(not source.missing_symbols, "HK_0930_TDX_RESEARCH_MISSING_CODES")
    require(raw.get("trade_date") == "20260924", "HK_0930_TDX_RESEARCH_RAW_DATE_MISMATCH")
    require(raw.get("stage_id") == "STAGE_0930_0935", "HK_0930_TDX_RESEARCH_RAW_STAGE_MISMATCH")
    require(raw.get("market") == "HK_CONNECT", "HK_0930_TDX_RESEARCH_RAW_MARKET_MISMATCH")
    require(raw.get("source_id") == "pytdx_exhq", "HK_0930_TDX_RESEARCH_RAW_SOURCE_ID_MISMATCH")
    require(raw.get("status") == "PARTIAL_WITH_ROWS", "HK_0930_TDX_RESEARCH_RAW_STATUS_MISMATCH")
    require(raw.get("requested_rows") == 100, "HK_0930_TDX_RESEARCH_RAW_REQUESTED_ROWS_MISMATCH")
    require(_HK_0930_TDX_RESEARCH_MODE_EVIDENCE in evidence,
            "HK_0930_TDX_RESEARCH_MODE_MISSING")
    require(_HK_0930_TDX_RESEARCH_MODE_EVIDENCE in raw_evidence,
            "HK_0930_TDX_RESEARCH_RAW_MODE_MISSING")

    pool_codes = tuple(sorted(str(code).upper() for code in plan.codes_for("HK_CONNECT")))
    pool_codes_sha256 = hashlib.sha256(
        json.dumps(pool_codes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    row_codes = tuple(sorted(str(row.get("code") or "").upper() for row in source.rows))
    require(len(pool_codes) == len(set(pool_codes)) == 100
            and pool_codes_sha256 == HK_0930_TDX_D1_CODE_SET_SHA256,
            "HK_0930_TDX_RESEARCH_D1_CODE_SET_MISMATCH")
    require(row_codes == pool_codes, "HK_0930_TDX_RESEARCH_ROW_MEMBERSHIP_MISMATCH")
    require(all(row.get("temporal_cutoff_safe") is False for row in source.rows),
            "HK_0930_TDX_RESEARCH_TEMPORAL_FLAG_NOT_FALSE")
    require(all(not row.get("candidate_lanes") for row in source.rows),
            "HK_0930_TDX_RESEARCH_CANDIDATE_LANE_PRESENT")
    require(raw.get("source_evidence") and set(raw_evidence).issubset(set(evidence)),
            "HK_0930_TDX_RESEARCH_RAW_EVIDENCE_MISMATCH")
    expected_d1_markers = {
        "hk_d1_sha256=fda1cd4b334699fc4df59658b443a01388f6bb4dfd29470d9c1baabd75ad72fc",
        "hk_d1_binding_sha256=fda1cd4b334699fc4df59658b443a01388f6bb4dfd29470d9c1baabd75ad72fc",
        "hk_d1_json_sha256=fda1cd4b334699fc4df59658b443a01388f6bb4dfd29470d9c1baabd75ad72fc",
        "hk_d1_membership=exact_date_top100",
    }
    require(expected_d1_markers.issubset(set(evidence)),
            "HK_0930_TDX_RESEARCH_D1_BINDING_MISMATCH")
    artifact_sha = str(raw.get("artifact_sha256") or "")
    require(len(artifact_sha) == 64 and all(char in "0123456789abcdef" for char in artifact_sha),
            "HK_0930_TDX_RESEARCH_RAW_SHA_MISSING")

    if not _allows_hk_0930_tdx_temporal_false_observation(
        enabled=HK_0930_TDX_RESEARCH_MODE_EVIDENCE in evidence,
        trade_date=plan.trade_date,
        stage_id=plan.stage_id,
        market="HK_CONNECT",
        source_id=source.source_id,
        source_status=source.status,
        rows=source.rows,
        requested_rows=source.requested_rows,
        missing_symbols=source.missing_symbols,
        cannot_confirm=source.cannot_confirm,
        source_evidence=evidence,
    ):
        require(False, "HK_0930_TDX_RESEARCH_SOURCE_CONTRACT_MISMATCH")
    return tuple(dict.fromkeys(errors))


def _hk_0930_research_contract_errors(source, plan, raw):
    """Keep this one exact historical input bundle behind the existing runner gate."""
    evidence = tuple(str(item) for item in source.source_evidence)
    raw_evidence = tuple(str(item) for item in raw.get("source_evidence", ()))
    errors = []

    def require(condition, reason):
        if not condition:
            errors.append(reason)

    require(plan.trade_date == "20260925", "HK_0930_RESEARCH_DATE_MISMATCH")
    require(plan.stage_id == "STAGE_0930_0935", "HK_0930_RESEARCH_STAGE_MISMATCH")
    require(source.source_id == _HK_0930_RESEARCH_SOURCE_ID, "HK_0930_RESEARCH_SOURCE_ID_MISMATCH")
    require(source.status == "PARTIAL_WITH_ROWS", "HK_0930_RESEARCH_SOURCE_STATUS_MISMATCH")
    require(source.requested_rows == 100, "HK_0930_RESEARCH_REQUESTED_ROWS_MISMATCH")
    require(len(source.rows) == 96, "HK_0930_RESEARCH_ROW_COUNT_MISMATCH")
    require(raw.get("trade_date") == "20260925", "HK_0930_RESEARCH_RAW_DATE_MISMATCH")
    require(raw.get("stage_id") == "STAGE_0930_0935", "HK_0930_RESEARCH_RAW_STAGE_MISMATCH")
    require(raw.get("market") == "HK_CONNECT", "HK_0930_RESEARCH_RAW_MARKET_MISMATCH")
    require(raw.get("source_id") == _HK_0930_RESEARCH_SOURCE_ID, "HK_0930_RESEARCH_RAW_SOURCE_ID_MISMATCH")
    require(raw.get("status") == "PARTIAL_WITH_ROWS", "HK_0930_RESEARCH_RAW_STATUS_MISMATCH")
    require(raw.get("requested_rows") == 100, "HK_0930_RESEARCH_RAW_REQUESTED_ROWS_MISMATCH")
    require("due_status=HISTORICAL_BACKFILL" in evidence, "HK_0930_RESEARCH_NOT_HISTORICAL_BACKFILL")

    expected_markers = (
        _HK_0930_RESEARCH_CONTRACT,
        f"historical_base_raw_sha256={_HK_0930_BASE_RAW_SHA256}",
        f"historical_gap_fields_sha256={_HK_0930_GAP_FIELDS_SHA256}",
        f"historical_gap_csv_sha256={_HK_0930_GAP_CSV_SHA256}",
        f"historical_gap_receipt_sha256={_HK_0930_GAP_RECEIPT_SHA256}",
        f"historical_d1_pool_sha256={_HK_0930_D1_POOL_SHA256}",
        "historical_formal_pit=false",
        "historical_active_lane_authority=UNVERIFIED",
        "production_allowed=false",
        "buy_gate_updated=false",
        "orders_sent=false",
    )
    for marker in expected_markers:
        require(marker in evidence and marker in raw_evidence, f"HK_0930_RESEARCH_MARKER_MISSING:{marker.split('=')[0]}")

    # The D-1 SHA below must be attached by the normal runner after it verifies
    # the exact source trio. The collector marker alone cannot authorize this path.
    for marker in (
        f"hk_d1_sha256={_HK_0930_D1_POOL_SHA256}",
        f"hk_d1_binding_sha256={_HK_0930_D1_POOL_SHA256}",
        "hk_d1_membership=exact_date_top100",
    ):
        require(marker in evidence, f"HK_0930_RESEARCH_D1_BINDING_MISMATCH:{marker.split('=')[0]}")

    pool_codes = tuple(sorted(plan.codes_for("HK_CONNECT")))
    pool_codes_sha256 = hashlib.sha256(
        json.dumps(pool_codes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    require(len(pool_codes) == 100 and pool_codes_sha256 == _HK_0930_D1_CODES_SHA256,
            "HK_0930_RESEARCH_D1_CODE_SET_MISMATCH")

    row_codes = [str(row.get("code") or "").upper() for row in source.rows]
    missing_codes = {str(code).upper() for code in source.missing_symbols}
    require(len(set(row_codes)) == 96, "HK_0930_RESEARCH_DUPLICATE_OR_EMPTY_CODE")
    require(missing_codes == _HK_0930_MISSING_LAST_PRICE, "HK_0930_RESEARCH_MISSING_CODES_MISMATCH")
    require(set(row_codes).isdisjoint(missing_codes), "HK_0930_RESEARCH_MISSING_CODE_HAS_ROW")
    require(set(row_codes) | missing_codes == set(pool_codes), "HK_0930_RESEARCH_MEMBERSHIP_MISMATCH")
    require(
        raw.get("artifact_sha256") is not None
        and len(str(raw.get("artifact_sha256"))) == 64
        and all(char in "0123456789abcdef" for char in str(raw.get("artifact_sha256"))),
        "HK_0930_RESEARCH_RAW_SHA_MISSING",
    )

    for row in source.rows:
        code = str(row.get("code") or "").upper()
        source_id = row.get("historical_source_id")
        require(row.get("historical_observation_contract") == "HK_STAGE0930_RESEARCH_ONLY",
                "HK_0930_RESEARCH_ROW_CONTRACT_MISMATCH")
        require(source_id in _HK_0930_SOURCE_IDS, "HK_0930_RESEARCH_ROW_SOURCE_ID_MISMATCH")
        require(row.get("formal_pit_status") == "NOT_FORMAL_PIT_MINUTE_CAPTURE_OCCURRED_AFTER_TARGET_CUTOFF",
                "HK_0930_RESEARCH_ROW_PIT_STATUS_MISMATCH")
        require(row.get("volume_ratio") in (None, ""), "HK_0930_RESEARCH_VOLUME_RATIO_MUST_REMAIN_UNKNOWN")
        require(row.get("turnover_rate") in (None, ""), "HK_0930_RESEARCH_TURNOVER_RATE_MUST_REMAIN_UNKNOWN")
        require(row.get("platform_circular_market_cap_hkd_yi") in (None, ""),
                "HK_0930_RESEARCH_PLATFORM_CAP_MUST_REMAIN_UNKNOWN")
        require(row.get("offer_float_market_cap_hkd_yi") in (None, ""),
                "HK_0930_RESEARCH_FREE_FLOAT_CAP_MUST_REMAIN_UNKNOWN")
        turnover = row.get("turnover")
        if turnover not in (None, ""):
            require(row.get("historical_turnover_unit") == "HKD",
                    "HK_0930_RESEARCH_TURNOVER_UNIT_MUST_BE_HKD")
        if source_id == "YAHOO_FINANCE_CHART_1M" or code == "HK.02402":
            require(turnover in (None, ""), "HK_0930_RESEARCH_UNVERIFIED_TURNOVER_MUST_REMAIN_UNKNOWN")
        try:
            zero_volume = row.get("volume") not in (None, "") and float(row.get("volume")) == 0.0
        except (TypeError, ValueError):
            zero_volume = False
        if zero_volume:
            require(row.get("last_price") in (None, ""),
                    "HK_0930_RESEARCH_ZERO_VOLUME_PRICE_USED_AS_SIGNAL")
        if code in _HK_0930_ZERO_VOLUME_REFERENCE:
            require(row.get("last_price") in (None, ""), "HK_0930_RESEARCH_ZERO_VOLUME_PRICE_USED_AS_SIGNAL")

    return tuple(dict.fromkeys(errors))



_HK_FUTU_RTDATA_POOL_ARTIFACT_SHA256 = "220fd29bc907a1c4e431c75fb8eccb3204c5857130eb639f1e9b6a62b60cfe3d"
_HK_FUTU_RTDATA_POOL_SOURCE_SHA256 = "738ffa6533bfc1e041a3cd84841d591f0ee6bda53fe8fe420cf608b9a7f3503d"
_HK_FUTU_RTDATA_CODE_SET_SHA256 = "5e7ad70ddcd6bcf1ab5007ef8c5f365258e77d6e8d52ade5be2177cb24ae1223"
_HK_FUTU_RTDATA_STAGE_PROFILES = {
    "STAGE_1300_1315": (
        "13:00-13:15", "13:15:00", "13:00:00", "13:14:00", 14, 1400,
        "63cba10b805b60dc7108ac7d633b0b1c32da2211b04fd976e1cd637ce083afe0",
        "018175c4cd1e7d2278033da39d79d09e3856468400ea384f104584551e304ad9",
        "54770c58c801f21a61363abee5db5a1eaf015e99a117be75eca758f229ba431b",
        "3b3cc0a321c1a45abc973d88a73c2c5d9c03731a1f5ac5746ce7c48ea8ae1b73",
    ),
    "STAGE_1445_1500": (
        "14:45-15:00", "15:00:00", "14:45:00", "14:59:00", 15, 1500,
        "4a310b4920dc5c6ebb7ac8b9f50d1e73d2dcb4d0ef685fef329358c09c2223d0",
        "0517c61ca85c25e2213a3ff787509d2c7285ec26b473e2a07daa579dab358f05",
        "66e27894b45c5e9b15f25d3e0edf2a3d0a437ac80c12bd228017bc01c9c92132",
        "c49ebb533922769b78c7c7d94b7e6b0e3e06ba8fc3961c0611b0ca326ad77d15",
    ),
}
_HK_FUTU_RTDATA_OBSERVATION_CONTRACT = "HK_FUTU_RTDATA_AFTERFACT_RESEARCH_20261012_R1"
_HK_FUTU_RTDATA_SOURCE_ID = "futu_rt_data_afterfact"
_HK_FUTU_RTDATA_CANNOT_CONFIRM = {
    "FUTU_RT_DATA_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT",
    "FUTU_RT_DATA_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM",
    "FUTU_RT_DATA_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM",
    "FUTU_RT_DATA_OHLC_AND_ORDERBOOK_UNAVAILABLE",
}


def _is_futu_rtd_afterfact_observation(source, plan, raw, rows) -> bool:
    """Admit only the independently verified fixed-pool 2026-10-12 Futu observations."""
    profile = _HK_FUTU_RTDATA_STAGE_PROFILES.get(plan.stage_id)
    if profile is None:
        return False
    window, cutoff, row_start_time, row_end_time, observations_per_code, observation_count, capture_sha, provider_sha, projection_sha, projection_without_name_sha = profile
    required_evidence = {
        f"futu_observation_contract={_HK_FUTU_RTDATA_OBSERVATION_CONTRACT}",
        "futu_afterfact_target_date=20261012",
        f"futu_afterfact_stage_id={plan.stage_id}",
        "futu_afterfact_market=HK_CONNECT",
        f"futu_afterfact_source_id={_HK_FUTU_RTDATA_SOURCE_ID}",
        f"futu_afterfact_window={window}",
        f"futu_afterfact_cutoff={cutoff}",
        f"futu_afterfact_row_window_start={row_start_time}",
        f"futu_afterfact_row_window_end={row_end_time}",
        f"futu_afterfact_pool_artifact_sha256={_HK_FUTU_RTDATA_POOL_ARTIFACT_SHA256}",
        f"futu_afterfact_pool_source_sha256={_HK_FUTU_RTDATA_POOL_SOURCE_SHA256}",
        f"futu_afterfact_code_set_sha256={_HK_FUTU_RTDATA_CODE_SET_SHA256}",
        "futu_afterfact_requested_code_count=100",
        "futu_afterfact_completed_code_count=100",
        f"futu_afterfact_observations_per_code={observations_per_code}",
        f"futu_afterfact_nonblank_observation_count={observation_count}",
        f"futu_afterfact_capture_sha256={capture_sha}",
        "futu_afterfact_temporal_cutoff_safe=false",
        "futu_afterfact_pit_safe=false",
        "futu_afterfact_formal_stage_eligibility=CANNOT_CONFIRM",
        "futu_afterfact_natural_time_capture=CANNOT_CONFIRM",
        "futu_afterfact_selection_action_boundary=NO_BUY",
        f"futu_afterfact_target_provider_rows_sha256={provider_sha}",
        f"futu_afterfact_raw_projection_sha256={projection_sha}",
        "research_only=true",
        "production_allowed=false",
        "buy_gate_updated=false",
        "orders_sent=false",
    }
    evidence = set(str(item) for item in (source.source_evidence or ()))
    raw_evidence = set(str(item) for item in (raw.get("source_evidence") or ()))
    if (
        plan.trade_date != "20261012"
        or source.source_id != _HK_FUTU_RTDATA_SOURCE_ID
        or source.status != "PARTIAL_WITH_ROWS"
        or source.requested_rows != 100
        or source.missing_symbols
        or len(rows) != 100
        or raw.get("trade_date") != "20261012"
        or raw.get("stage_id") != plan.stage_id
        or raw.get("market") != "HK_CONNECT"
        or raw.get("source_id") != _HK_FUTU_RTDATA_SOURCE_ID
        or raw.get("status") != "PARTIAL_WITH_ROWS"
        or raw.get("source_status") != "PARTIAL_WITH_ROWS"
        or raw.get("window") != window
        or raw.get("cutoff_at") != cutoff
        or raw.get("row_count") != 100
        or raw.get("requested_rows") != 100
        or raw.get("missing_symbols")
        or raw.get("temporal_cutoff_safe", False) is not False
        or raw.get("production_allowed", False) is not False
        or raw.get("buy_gate_updated", False) is not False
        or raw.get("orders_sent", False) is not False
        or not _HK_FUTU_RTDATA_CANNOT_CONFIRM.issubset(set(source.cannot_confirm or ()))
        or not _HK_FUTU_RTDATA_CANNOT_CONFIRM.issubset(set(raw.get("cannot_confirm") or ()))
        or not required_evidence.issubset(evidence)
        or not required_evidence.issubset(raw_evidence)
    ):
        return False
    raw_source_rows = list(source.rows)
    codes = [str(row.get("code") or "").strip().upper() for row in raw_source_rows]
    if len(set(codes)) != 100:
        return False
    code_set_sha = hashlib.sha256(
        json.dumps(tuple(sorted(codes)), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if code_set_sha != _HK_FUTU_RTDATA_CODE_SET_SHA256:
        return False
    # Bind every raw field other than display name to the immutable capture.
    # D-1 authority may replace a quote-provider name, but it must not alter
    # the captured prices, volume, turnover, timestamps, or other raw fields.
    from stage_center.raw_store import RAW_FIELDS
    projection_fields = tuple(field for field in RAW_FIELDS if field != "name")
    projection_without_name = [
        {
            field: ("" if row.get(field) in (None, "") else str(row.get(field)))
            for field in projection_fields
        }
        for row in sorted(raw_source_rows, key=lambda item: str(item.get("code") or "").upper())
    ]
    selection_projection_sha = hashlib.sha256(
        json.dumps(projection_without_name, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if selection_projection_sha != projection_without_name_sha:
        return False
    # RawStore separately verified the full original provider projection,
    # including the provider name, before D-1 authority was overlaid.
    raw_projection_marker = f"futu_afterfact_raw_projection_sha256={profile[8]}"
    if raw_projection_marker not in evidence or raw_projection_marker not in raw_evidence:
        return False
    update_time = f"2026-10-12 {row_end_time}"
    for row in raw_source_rows:
        if (
            row.get("update_time") != update_time
            or row.get("temporal_cutoff_safe") not in (False, "False", "false")
            or row.get("window_start") != f"2026-10-12 {row_start_time}"
            or row.get("window_end") != update_time
            or row.get("bar_count") not in (observations_per_code, str(observations_per_code))
            or row.get("last_price") in (None, "")
            or row.get("prev_close_price") in (None, "")
            or any(row.get(field) not in (None, "") for field in (
                "open_price", "high_price", "low_price", "bid_price", "ask_price", "bid_vol", "ask_vol"
            ))
        ):
            return False
    return True


def _production_selection_builders_body(_v4_scope, /, stage_id, *, research_root, morning_root):
    """Build selection transforms from the package's frozen V3 pure formulas."""
    from stage_center.selection import (
        _selection_identity_ids,
        select_a_0925_auction,
        select_a_stage,
        select_hk_0925_second_filter,
        select_hk_four_lane,
    )

    top10_contract_evidence = "selection_contract=V3_TOP10_RECOMMENDATION"
    research_stages = {
        "STAGE_0930_0935",
        "STAGE_0935_0940",
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
    }

    def a_builder(source: SourceResult, plan: AcquisitionPlan, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        if stage_id == "STAGE_0925":
            rows = [
                {
                    "code": row.get("code"),
                    "name": row.get("name") or row.get("stock_name"),
                    "stock_name": row.get("stock_name") or row.get("name"),
                    "time": row.get("update_time"),
                    "amount": row.get("turnover"),
                    "open_price": row.get("open_price"),
                    "last_price": row.get("last_price"),
                    "high_price": row.get("high_price"),
                    "low_price": row.get("low_price"),
                    "update_time": row.get("update_time"),
                    "next_validation_time": raw.get("cutoff_at"),
                    "trade_date": plan.trade_date,
                }
                for row in source.rows
            ]
            return select_a_0925_auction(rows, plan.trade_date, _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]), source_status=raw["status"], requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=raw["cannot_confirm"], source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*raw["source_evidence"], *source.source_evidence, top10_contract_evidence))))
        research_context = None
        context_root = research_root or raw.get("_v4_research_data_root")
        if stage_id in research_stages and context_root is None:
            raise _v4_global(_v4_scope, 'ValueError')(
                f"V4 research data root is required for {stage_id} A_SHARE"
            )
        if stage_id in research_stages:
            from stage_center.research_context import ResearchContextError, load_research_context

            try:
                research_context = load_research_context(
                    context_root,
                    trade_date=plan.trade_date,
                    stage_cutoff=_v4_global(_v4_scope, 'str')(raw.get("cutoff_at") or ""),
                    morning_root=(
                        morning_root
                        if morning_root is not None
                        else raw.get("_v4_morning_news_root")
                    ),
                )
            except ResearchContextError:
                # The runner catches ValueError and publishes a fail-closed
                # receipt.  Never fall back to a current V3.5 score or a
                # future hourly slot when the frozen V3 evidence is invalid.
                raise
        rows = []
        for index, row in _v4_global(_v4_scope, 'enumerate')(source.rows, start=1):
            # ``select_a_live_stage`` is the Windows V3 authority.  Preserve
            # the exact qmt field names and amount/price semantics rather than
            # silently switching to the older minute-bar score.
            # A raw collector row is not a formal-pool authority.  The runner
            # marks rows only after its exact-date formal attach step has
            # verified membership; inherited ``formal_eligible`` values and
            # lane evidence remain untrusted source data.
            formal_overlay_verified = _v4_global(_v4_scope, '_has_runner_verified_formal_overlay')(row)
            formal_value = row.get("formal_eligible", False)
            formal_eligible = formal_overlay_verified and _v4_global(_v4_scope, 'str')(formal_value).strip().lower() in {"true", "1", "yes"}
            lane_evidence = _v4_global(_v4_scope, 'list')(row.get("lane_evidence") or ())
            if formal_eligible:
                lane_evidence.append("A_SHARE_FORMAL_POOL")
            else:
                # The raw adapter may carry a stale formal marker.  Formal
                # identity is granted only by the exact-date authority
                # overlay, never by inherited source evidence.
                lane_evidence = [item for item in lane_evidence if item != "A_SHARE_FORMAL_POOL"]
                lane_evidence.append("STAGE_ACQUISITION_UNIVERSE")
            candidate_score = row.get("pool_score") if formal_eligible else None
            if candidate_score in (None, ""):
                candidate_score = None
            research = None
            if research_context is not None:
                code_key = _v4_global(_v4_scope, '_canonical_a_code')(row.get("code") or row.get("stock_code"))
                research = research_context.by_code.get(code_key)
                if research is None:
                    # An exact-date archive that has no entry for a candidate
                    # code cannot prove a research value.  Keep that absence
                    # visible at the stage envelope instead of allowing the
                    # selection helper's numeric defaults to look observed.
                    research_context_gap = f"RESEARCH_CONTEXT_CODE_MISSING:{code_key or row.get('code')}"
                else:
                    missing_fields = _v4_global(_v4_scope, 'tuple')(
                        field
                        # Delta is explanatory metadata, not an input to
                        # selection.py's unchanged two-score bonus formula.
                        # Its absence remains in context.cannot_confirm.
                        for field in (
                            "news_quality_score",
                            "research_quality_score",
                        )
                        if _v4_global(_v4_scope, 'getattr')(research, field) is None
                    )
                    research_context_gap = (
                        f"RESEARCH_CONTEXT_FIELDS_MISSING:{code_key or row.get('code')}:{','.join(missing_fields)}"
                        if missing_fields
                        else None
                    )
            else:
                research_context_gap = None
            rows.append({
                "code": row.get("code"),
                "name": row.get("name") or row.get("stock_name"),
                "stock_name": row.get("stock_name") or row.get("name"),
                "formal_eligible": formal_eligible,
                "formal_rank": row.get("formal_rank", "") if formal_eligible else "",
                "candidate": {"score": candidate_score},
                "qmt": {
                    "open": row.get("open_price"),
                    "lastPrice": row.get("last_price"),
                    "lastClose": row.get("prev_close_price"),
                    "high": row.get("high_price"),
                    "low": row.get("low_price"),
                    "amount": row.get("turnover"),
                    "bidVol": [row.get("bid_vol")],
                    "askVol": [row.get("ask_vol")],
                },
                "open_price": row.get("open_price"),
                "last_price": row.get("last_price"),
                "high_price": row.get("high_price"),
                "low_price": row.get("low_price"),
                "update_time": row.get("update_time"),
                "next_validation_time": raw.get("cutoff_at"),
                "trade_date": plan.trade_date,
                "stage_id": plan.stage_id,
                "lane_evidence": _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys((*lane_evidence, "PYTDX_EXACT_STAGE_ADAPTER"))),
                "acquisition_rank": row.get("acquisition_rank", row.get("batch_index", index)),
                "news_quality_score": research.news_quality_score if research is not None else None,
                "research_quality_score": research.research_quality_score if research is not None else None,
                "latest_research_slot": research.latest_research_slot if research is not None else "",
                "research_delta_hits": research.research_delta_hits if research is not None else None,
                "news_research_reason": "；".join(research.news_research_reason) if research is not None else "",
                "source_health": research.source_health if research is not None else "CANNOT_CONFIRM",
                "_research_context_gap": research_context_gap,
            })
        from stage_center.selection import _selection_identity_ids, select_a_live_stage
        research_evidence = research_context.source_evidence if research_context is not None else ()
        formal_overlay_supplied = _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, '_has_runner_verified_formal_overlay')(row) for row in source.rows)
        context_gaps = _v4_global(_v4_scope, 'list')(research_context.cannot_confirm if research_context is not None else ())
        if not formal_overlay_supplied:
            context_gaps.append("FORMAL_OVERLAY_CANNOT_CONFIRM")
        context_gaps.extend(
            _v4_global(_v4_scope, 'str')(row["_research_context_gap"])
            for row in rows
            if row.get("_research_context_gap")
        )
        source_status = (
            "CANNOT_CONFIRM"
            if context_gaps
            else raw["status"]
        )
        formal_evidence = (
            "formal_overlay=EXACT_DATE_AUTHORITY"
            if formal_overlay_supplied
            else "formal_overlay=CANNOT_CONFIRM"
        )
        envelope = select_a_live_stage(rows, plan.trade_date, plan.stage_id, _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]), source_status=source_status, requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*raw["cannot_confirm"], *context_gaps))), source_evidence=_v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, 'dict').fromkeys((*raw["source_evidence"], *source.source_evidence, *research_evidence, formal_evidence, top10_contract_evidence))))
        original_by_code = {
            _v4_global(_v4_scope, 'str')(row.get("code") or row.get("stock_code") or "").strip().upper(): row
            for row in rows
        }
        for selected in envelope.get("rows", ()):
            original = original_by_code.get(
                _v4_global(_v4_scope, 'str')(selected.get("code") or selected.get("stock_code") or "").strip().upper()
            )
            if original is None or not original.get("_research_context_gap"):
                continue
            # ``select_a_live_stage`` retains its historical numeric scoring
            # formula, but a missing research scalar must not be serialized as
            # an observed zero in the fail-closed envelope.
            for field in (
                "news_quality_score",
                "research_quality_score",
                "research_delta_hits",
                "latest_research_slot",
                "news_research_reason",
                "source_health",
            ):
                selected[field] = original.get(field)
            selected["research_bonus"] = None
            selected.pop("_research_context_gap", None)
        for row in rows:
            row.pop("_research_context_gap", None)
        # The projection above changes the serialized rows after
        # ``select_a_live_stage`` has initially calculated its identity.  Bind
        # the existing immutable identity helper to the final rows so the
        # publisher and reader validate exactly the bytes being published.
        artifact_id, run_id = _selection_identity_ids(
            plan.trade_date,
            plan.stage_id,
            "A_SHARE",
            _v4_global(_v4_scope, 'str')(envelope["raw_artifact_sha256"]),
            _v4_global(_v4_scope, 'str')(envelope["algorithm_sha256"]),
            _v4_global(_v4_scope, 'list')(envelope.get("rows") or ()),
        )
        envelope["artifact_id"] = artifact_id
        envelope["run_id"] = run_id
        return envelope

    def hk_builder(source: SourceResult, plan: AcquisitionPlan, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        rows = []
        use_historical_price_bar_time = (
            _HK_0930_RESEARCH_CONTRACT in source.source_evidence
            or source.source_id == _HK_0930_RESEARCH_SOURCE_ID
        )
        d1_evidence: list[str] = _v4_global(_v4_scope, 'list')(source.source_evidence)
        isolates_snapshot_exclusions = _HK_ACTIVE_SNAPSHOT_ISOLATION_POLICY in source.source_evidence
        excluded_snapshot_rows = 0
        for row in source.rows:
            if isolates_snapshot_exclusions and row.get("active_snapshot_eligible") is False:
                excluded_snapshot_rows += 1
                continue
            previous = _v4_global(_v4_scope, '_safe_number')(row.get("prev_close_price"))
            last = _v4_global(_v4_scope, '_safe_number')(row.get("last_price"))
            pct = ((last - previous) / previous * 100.0) if previous and last is not None else None
            # The acquisition row does not assert a lane.  The runner adds
            # D-1/second-filter metadata before invoking this transform; an
            # empty lane list therefore stays empty and cannot become a
            # fabricated LIVE_HKCONNECT_GAINER.
            rows.append({
                "code": row.get("code"),
                "name": row.get("name") or row.get("stock_name"),
                "stock_name": row.get("stock_name") or row.get("name"),
                "candidate_lanes": _v4_global(_v4_scope, 'list')(row.get("candidate_lanes") or ()),
                "candidate_bucket": row.get("candidate_bucket", ""),
                "trade_status_contract": row.get("trade_status_contract", ""),
                "second_filter_rank": row.get("second_filter_rank", ""),
                "second_filter_score": row.get("second_filter_score", ""),
                "second_filter_status": row.get("second_filter_status", ""),
                "second_filter_action_level": row.get("second_filter_action_level", ""),
                "pct_chg": pct,
                "turnover": row.get("turnover"),
                "turnover_hkd": row.get("turnover"),
                "volume_ratio": row.get("volume_ratio"),
                "turnover_rate": row.get("turnover_rate"),
                "platform_circular_market_cap_hkd_yi": row.get("platform_circular_market_cap_hkd_yi"),
                "offer_float_market_cap_hkd_yi": row.get("offer_float_market_cap_hkd_yi"),
                "stage_window_change_pct": row.get("stage_window_change_pct"),
                "open_price": row.get("open_price"),
                "last_price": row.get("last_price"),
                "high_price": row.get("high_price"),
                "low_price": row.get("low_price"),
                "update_time": (
                    row.get("source_last_bar_time")
                    if use_historical_price_bar_time
                    else row.get("update_time")
                ),
                "next_validation_time": raw.get("cutoff_at"),
                "stage_id": plan.stage_id,
                # These fields are copied from the exact-date D-1 authority
                # by the runner. They remain selection-envelope metadata and
                # never alter the four-lane score.
                "d1_status": row.get("d1_status", row.get("strict_0_2_status", "")),
                "d1_model_id": row.get("d1_model_id", row.get("model_id", row.get("model", ""))),
                "d1_prob_active": row.get("d1_prob_active", row.get("prob_active", "")),
                "d1_rank": row.get("d1_rank", row.get("pool_rank", row.get("rank", ""))),
                "d1_score": row.get("d1_score", row.get("pool_score", row.get("score", ""))),
                "d1_source_evidence": _v4_global(_v4_scope, 'list')(row.get("d1_source_evidence") or ()),
            })
            if stage_id == "STAGE_0925":
                # Keep the auction oracle's rank/score/date fields through
                # projection; its change is measured from previous close.
                rows[-1].update({key: row.get(key) for key in (
                    "rank", "auction_score", "target_date", "signal_date",
                    "preselect_lane", "reference_price_hkd",
                    "strict_failure_price_hkd", "bid_price", "ask_price",
                )})
                rows[-1]["current_change_pct"] = pct
            model_id = rows[-1].get("d1_model_id")
            d1_status = rows[-1].get("d1_status")
            if model_id:
                d1_evidence.append(f"hk_d1_model_id={model_id}")
            if d1_status:
                d1_evidence.append(f"hk_d1_status={d1_status}")
            d1_evidence.extend(_v4_global(_v4_scope, 'str')(item) for item in rows[-1]["d1_source_evidence"] if _v4_global(_v4_scope, 'str')(item))
        d1_evidence = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(d1_evidence))
        if isolates_snapshot_exclusions:
            d1_evidence.extend((
                "hk_selection_snapshot_eligibility=PER_STOCK_TEMPORAL_V1",
                f"hk_selection_snapshot_requested_rows={source.requested_rows or len(source.rows)}",
                f"hk_selection_snapshot_eligible_rows={len(rows)}",
                f"hk_selection_snapshot_excluded_rows={excluded_snapshot_rows}",
            ))
        if _HK_0930_RESEARCH_CONTRACT in source.source_evidence or source.source_id == _HK_0930_RESEARCH_SOURCE_ID:
            contract_errors = _hk_0930_research_contract_errors(source, plan, raw)
            contract_evidence = (
                *raw.get("source_evidence", ()),
                *source.source_evidence,
                *d1_evidence,
                top10_contract_evidence,
                "hk_selection_mode=HK_STAGE0930_RESEARCH_ONLY",
                "historical_observation=WATCH_ONLY_NO_BUY",
                "formal_pit=false",
            )
            if contract_errors:
                return select_hk_four_lane(
                    [],
                    plan.trade_date,
                    plan.stage_id,
                    _v4_global(_v4_scope, 'str')(raw.get("artifact_sha256") or ""),
                    source_status="CANNOT_CONFIRM",
                    requested_rows=100,
                    missing_symbols=source.missing_symbols,
                    cannot_confirm=(*source.cannot_confirm, *contract_errors),
                    source_evidence=contract_evidence,
                )
            return select_hk_four_lane(
                rows,
                plan.trade_date,
                plan.stage_id,
                _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]),
                source_status="PARTIAL_WITH_ROWS",
                requested_rows=100,
                missing_symbols=source.missing_symbols,
                cannot_confirm=source.cannot_confirm,
                source_evidence=contract_evidence,
            )
        if _HK_0930_TDX_RESEARCH_MODE_EVIDENCE in source.source_evidence:
            contract_errors = _hk_0930_tdx_research_contract_errors(source, plan, raw)
            contract_evidence = (
                *raw.get("source_evidence", ()),
                *source.source_evidence,
                *d1_evidence,
                top10_contract_evidence,
                "hk_selection_mode=HK_STAGE0930_TDX_AFTERFACT_RESEARCH_ONLY",
                "historical_observation=AFTERFACT_TDX_OBSERVATION_NO_BUY",
                "formal_pit=false",
            )
            if contract_errors:
                return select_hk_four_lane(
                    [],
                    plan.trade_date,
                    plan.stage_id,
                    _v4_global(_v4_scope, 'str')(raw.get("artifact_sha256") or ""),
                    source_status="CANNOT_CONFIRM",
                    requested_rows=100,
                    missing_symbols=source.missing_symbols,
                    cannot_confirm=(*source.cannot_confirm, *contract_errors),
                    source_evidence=contract_evidence,
                )
            envelope = select_hk_four_lane(
                rows,
                plan.trade_date,
                plan.stage_id,
                _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]),
                source_status="PARTIAL_WITH_ROWS",
                requested_rows=100,
                missing_symbols=source.missing_symbols,
                cannot_confirm=source.cannot_confirm,
                source_evidence=contract_evidence,
            )
            if any(
                row.get("action_level") != "NO_BUY"
                or row.get("candidate_lanes")
                for row in envelope.get("rows", ())
            ):
                return select_hk_four_lane(
                    [],
                    plan.trade_date,
                    plan.stage_id,
                    _v4_global(_v4_scope, 'str')(raw["artifact_sha256"]),
                    source_status="CANNOT_CONFIRM",
                    requested_rows=100,
                    missing_symbols=source.missing_symbols,
                    cannot_confirm=(*source.cannot_confirm, "HK_0930_TDX_RESEARCH_ACTION_BOUNDARY_VIOLATION"),
                    source_evidence=contract_evidence,
                )
            return envelope
        if any(item.startswith(_HISTORICAL_OBSERVATION_MODE_PREFIX) for item in source.source_evidence):
            contract_errors = _historical_observation_contract_errors(source, plan, raw)
            contract_evidence = tuple(dict.fromkeys((
                *raw.get("source_evidence", ()),
                *source.source_evidence,
                *d1_evidence,
                top10_contract_evidence,
                "selection_mode=RESEARCH_ONLY",
                "historical_observation=AFTERFACT_RESEARCH_ONLY_NO_BUY",
                "observation_status=OBSERVATION_UNVERIFIED",
                "formal_stage_eligibility=CANNOT_CONFIRM",
                "natural_time_capture=CANNOT_CONFIRM",
                "formal_pit=false",
                "production_allowed=false",
                "buy_gate_updated=false",
                "orders_sent=false",
            )))
            if contract_errors:
                return select_hk_four_lane(
                    [],
                    plan.trade_date,
                    plan.stage_id,
                    str(raw.get("artifact_sha256") or ""),
                    source_status="CANNOT_CONFIRM",
                    requested_rows=raw.get("requested_rows"),
                    missing_symbols=raw.get("missing_symbols", ()),
                    cannot_confirm=(*source.cannot_confirm, *contract_errors),
                    source_evidence=contract_evidence,
                )
            envelope = select_hk_four_lane(
                rows,
                plan.trade_date,
                plan.stage_id,
                str(raw["artifact_sha256"]),
                source_status="PARTIAL_WITH_ROWS",
                requested_rows=raw["requested_rows"],
                missing_symbols=raw.get("missing_symbols", ()),
                cannot_confirm=source.cannot_confirm,
                source_evidence=contract_evidence,
            )
            if len(envelope.get("rows", ())) > 10 or any(
                row.get("action_level") != "NO_BUY"
                or row.get("candidate_lanes")
                for row in envelope.get("rows", ())
            ):
                return select_hk_four_lane(
                    [],
                    plan.trade_date,
                    plan.stage_id,
                    str(raw["artifact_sha256"]),
                    source_status="CANNOT_CONFIRM",
                    requested_rows=raw.get("requested_rows"),
                    missing_symbols=raw.get("missing_symbols", ()),
                    cannot_confirm=(*source.cannot_confirm,
                                    "HISTORICAL_OBSERVATION_ACTION_BOUNDARY_VIOLATION"),
                    source_evidence=contract_evidence,
                )
            envelope["selection_mode"] = "RESEARCH_ONLY"
            envelope["observation_status"] = "OBSERVATION_UNVERIFIED"
            envelope["formal_stage_eligibility"] = "CANNOT_CONFIRM"
            envelope["natural_time_capture"] = "CANNOT_CONFIRM"
            envelope["formal_eligible"] = False
            for row in envelope.get("rows", ()):
                row["status"] = "WATCH_ONLY"
                row["trade_status"] = "WATCH_ONLY"
                row["action_level"] = "NO_BUY"
                row["formal_eligible"] = False
                row["candidate_lanes"] = []
                row["observation_mode"] = "RESEARCH_ONLY"
                row["observation_status"] = "OBSERVATION_UNVERIFIED"
            artifact_id, run_id = _selection_identity_ids(
                plan.trade_date,
                plan.stage_id,
                "HK_CONNECT",
                str(envelope["raw_artifact_sha256"]),
                str(envelope["algorithm_sha256"]),
                list(envelope.get("rows") or ()),
            )
            envelope["artifact_id"] = artifact_id
            envelope["run_id"] = run_id
            return envelope
        if stage_id == "STAGE_0925":
            return select_hk_0925_second_filter(rows, plan.trade_date, str(raw["artifact_sha256"]), source_status=raw["status"], requested_rows=raw["requested_rows"], missing_symbols=raw["missing_symbols"], cannot_confirm=raw["cannot_confirm"], source_evidence=tuple(dict.fromkeys((*raw["source_evidence"], *d1_evidence, top10_contract_evidence))))
        # User decision 2026-10-14: score every acquired fixed-D1 row.
        # Inactive is a strategy label, never missing market data. Preserve
        # real source gaps and do not invent a strong lane for an inactive row.
        return select_hk_four_lane(
            rows, plan.trade_date, plan.stage_id, str(raw["artifact_sha256"]),
            source_status=source.status if source.status != "READY" else raw["status"],
            requested_rows=raw.get("requested_rows", source.requested_rows),
            missing_symbols=tuple(dict.fromkeys((*source.missing_symbols, *raw.get("missing_symbols", ())))),
            cannot_confirm=tuple(dict.fromkeys((*source.cannot_confirm, *raw.get("cannot_confirm", ())))),
            source_evidence=tuple(dict.fromkeys((
                *raw.get("source_evidence", ()), *d1_evidence, top10_contract_evidence,
                "hk_ranking_policy=FULL_D1_TOP100_STRONG_TAG_ONLY_V1",
            ))),
        )

    if stage_id == "STAGE_1545_1555":
        return {"HK_CONNECT": hk_builder}
    return {"A_SHARE": a_builder, "HK_CONNECT": hk_builder}
