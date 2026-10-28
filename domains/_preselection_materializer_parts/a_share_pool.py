"""domains.preselection_materializer: a_share_pool (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_baimao_pool_body(_v4_scope, /, path, trade_date):
    if path is None or not _v4_global(_v4_scope, 'Path')(path).is_file():
        return _v4_global(_v4_scope, 'build_expected_missing_pool')(
            trade_date, pool_id="a_share_baimao_research_map",
            display_name="白毛卡点研究池", market="A", reason="BAIMAO_RESEARCH_MAP_NOT_FOUND",
        )
    path = _v4_global(_v4_scope, 'Path')(path)
    try:
        payload = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8-sig"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError):
        payload = {}
    reason = ""
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        reason = "BAIMAO_RESEARCH_MAP_INVALID_JSON"
    elif _v4_global(_v4_scope, 'str')(payload.get("trade_date") or "") != trade_date:
        reason = "TRADE_DATE_MISMATCH"
    elif (
        not _v4_global(_v4_scope, 're').fullmatch(r"\d{8}", _v4_global(_v4_scope, 'str')(payload.get("research_date") or ""))
        or not _v4_global(_v4_scope, 'str')(payload.get("event_id") or "").startswith(
            f"research:{payload.get('research_date')}:"
        )
    ):
        reason = "RESEARCH_EVENT_BINDING_INVALID"
    elif payload.get("opens_buy_gate") is not False or payload.get("write_policy") != "RESEARCH_ONLY":
        reason = "BAIMAO_RESEARCH_ONLY_CONTRACT_INVALID"
    elif not _v4_global(_v4_scope, 'isinstance')(payload.get("candidates"), _v4_global(_v4_scope, 'list')):
        reason = "BAIMAO_CANDIDATES_INVALID"
    rows: list[dict[str, Any]] = []
    if not reason:
        for index, candidate in _v4_global(_v4_scope, 'enumerate')(payload["candidates"], start=1):
            if not _v4_global(_v4_scope, 'isinstance')(candidate, _v4_global(_v4_scope, 'Mapping')) or candidate.get("state") != "RESEARCH_MAP":
                continue
            symbol = _v4_global(_v4_scope, '_a_symbol')(candidate.get("code") or candidate.get("ts_code"))
            if not symbol:
                continue
            rows.append({
                **_v4_global(_v4_scope, 'dict')(candidate), "symbol": symbol, "market": "A",
                "pool_id": "a_share_baimao_research_map",
                "pool_rank": _v4_global(_v4_scope, '_row_number')(candidate.get("rank"), index),
                "stock_name": _v4_global(_v4_scope, 'str')(candidate.get("name") or symbol),
                "pool_score": _v4_global(_v4_scope, '_row_float')(candidate.get("score")),
                "target_date": trade_date, "recommendation_status": "RESEARCH_ONLY",
                "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
                "formal_pool_write": False, "buy_gate_write": False,
            })
    return _v4_global(_v4_scope, '_artifact')(
        trade_date=trade_date, pool_id="a_share_baimao_research_map",
        display_name="白毛卡点研究池", market="A",
        status="BAIMAO_RESEARCH_MAP_READY" if rows else "CANNOT_CONFIRM",
        producer_id="v3_baimao_research_map_v1", source_role="RAW_SOURCE",
        source_path=_v4_global(_v4_scope, 'str')(path), source_sha256=_v4_global(_v4_scope, '_sha256')(path), rows=rows,
        cannot_confirm=[reason or "RESEARCH_ONLY_NO_BUY_GATE"],
    )
