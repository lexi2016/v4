"""apps.api.v35_api.review_router: stage_rows (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __read_shared_stage_center_rows_body(_v4_scope, /, trade_date, stage_id):
    """Read the optional shared selection consumer without a write path."""
    root_value = _v4_global(_v4_scope, 'os').environ.get("V35_STAGE_CENTER_SELECTION_ROOT", "").strip()
    if not root_value:
        return None
    root = _v4_global(_v4_scope, 'Path')(root_value).expanduser()
    if not root.is_dir():
        return None
    try:
        consumer_module = _v4_global(_v4_scope, 'importlib').import_module("stage_center.consumer")
        consumer_type = _v4_global(_v4_scope, 'getattr')(consumer_module, "StageSelectionConsumer")
        payload = consumer_type(root).get(trade_date, stage_id)
    except _v4_global(_v4_scope, 'Exception'):
        return None
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
        return None
    if _v4_global(_v4_scope, 'any')(payload.get(flag) is not False for flag in _v4_global(_v4_scope, '_SAFETY_FLAGS')):
        return None
    if _v4_global(_v4_scope, 'str')(payload.get("trade_date") or "") != trade_date:
        return None
    nested_stage = payload.get("stage")
    declared_stage = (
        nested_stage.get("stage_id")
        if _v4_global(_v4_scope, 'isinstance')(nested_stage, _v4_global(_v4_scope, 'Mapping'))
        else payload.get("stage_id")
    )
    if _v4_global(_v4_scope, 'str')(declared_stage or "") != stage_id:
        return None
    markets = payload.get("markets")
    if not _v4_global(_v4_scope, 'isinstance')(markets, _v4_global(_v4_scope, 'Mapping')):
        return None
    a_market = markets.get("A_SHARE")
    if not _v4_global(_v4_scope, 'isinstance')(a_market, _v4_global(_v4_scope, 'Mapping')):
        return None
    raw_rows = a_market.get("rows")
    if not _v4_global(_v4_scope, 'isinstance')(raw_rows, _v4_global(_v4_scope, 'list')):
        return None
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
            continue
        if not _v4_global(_v4_scope, '_row_matches_exact_date')(raw, trade_date):
            continue
        if not _v4_global(_v4_scope, '_is_safe_watch_only_row')(raw):
            continue
        row = _v4_global(_v4_scope, 'deepcopy')(_v4_global(_v4_scope, 'dict')(raw))
        row.update(
            {
                "trade_date": trade_date,
                "market": "A",
                "recommendation_status": "WATCH_ONLY",
            }
        )
        if row.get("symbol") in (None, "") and row.get("code") not in (None, ""):
            row["symbol"] = row["code"]
        rows.append(row)
    return payload, rows


def __read_exact_stage_review_rows_body(_v4_scope, /, data_root, trade_date):
    """Read only published, exact-date A-share WATCH_ONLY stage rows.

    This is a consumer-side projection of the existing StageStore.  It never
    produces a stage, reads another date, or promotes a stage candidate into a
    formal review conclusion.
    """
    runner: StageRunner | None = None
    rows: list[dict[str, Any]] = []
    source_refs: list[dict[str, Any]] = []
    for stage_id in _v4_global(_v4_scope, 'FROZEN_STAGE_IDS'):
        shared_result = _v4_global(_v4_scope, '_read_shared_stage_center_rows')(trade_date, stage_id)
        if shared_result is not None:
            payload, raw_rows = shared_result
        else:
            if runner is None:
                runner = _v4_global(_v4_scope, 'StageRunner')(_v4_global(_v4_scope, 'StageStore')(data_root))
            try:
                payload = runner.read_workbench(trade_date, stage_id, limit=50)
            except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')):
                # A corrupt or incomplete stage is not usable evidence.  The
                # review remains compact unless another exact stage has rows.
                continue
            raw_rows = payload.get("unified_rows") if _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')) else None
        if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')):
            continue
        if _v4_global(_v4_scope, 'str')(payload.get("trade_date") or "") != trade_date:
            continue
        stage = payload.get("stage")
        declared_stage = (
            stage.get("stage_id")
            if _v4_global(_v4_scope, 'isinstance')(stage, _v4_global(_v4_scope, 'Mapping'))
            else payload.get("stage_id")
        )
        if _v4_global(_v4_scope, 'str')(declared_stage or "") != stage_id:
            continue
        if not _v4_global(_v4_scope, 'isinstance')(raw_rows, _v4_global(_v4_scope, 'list')):
            continue
        stage_rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'Mapping')):
                continue
            if raw.get("market") != "A":
                continue
            if not _v4_global(_v4_scope, '_is_safe_watch_only_row')(raw):
                continue
            if not _v4_global(_v4_scope, '_row_matches_exact_date')(raw, trade_date):
                continue
            row = _v4_global(_v4_scope, 'deepcopy')(_v4_global(_v4_scope, 'dict')(raw))
            row.update(
                {
                    "trade_date": trade_date,
                    "stage_id": stage_id,
                    "role_type": "stage_validation_anchor",
                    "primary_role": "stage_validation_anchor",
                    "recommendation_status": "WATCH_ONLY",
                    "formal_eligible": False,
                    "validation_scope": f"{trade_date} {stage_id} exact-date stage evidence",
                    "cannot_confirm": "CANNOT_CONFIRM_FORMAL_REVIEW_BUNDLE",
                }
            )
            if row.get("stock_code") in (None, "") and row.get("symbol") not in (None, ""):
                row["stock_code"] = row["symbol"]
            stage_rows.append(row)
        if not stage_rows:
            continue
        markets = payload.get("markets")
        a_market = markets.get("A_SHARE") if _v4_global(_v4_scope, 'isinstance')(markets, _v4_global(_v4_scope, 'Mapping')) else None
        run_receipt = payload.get("run_receipt")
        materialized_snapshot = payload.get("materialized_snapshot")
        run_id = _v4_global(_v4_scope, 'str')(
            payload.get("run_id")
            or (a_market.get("run_id") if _v4_global(_v4_scope, 'isinstance')(a_market, _v4_global(_v4_scope, 'Mapping')) else "")
            or (run_receipt.get("run_id") if _v4_global(_v4_scope, 'isinstance')(run_receipt, _v4_global(_v4_scope, 'Mapping')) else "")
            or (
                materialized_snapshot.get("run_id")
                if _v4_global(_v4_scope, 'isinstance')(materialized_snapshot, _v4_global(_v4_scope, 'Mapping'))
                else ""
            )
            or ""
        )
        response_source = _v4_global(_v4_scope, 'str')(payload.get("response_source") or "")
        source_role = _v4_global(_v4_scope, 'str')(
            payload.get("source_role")
            or payload.get("role")
            or response_source
            or ""
        )
        stage_status = (
            stage.get("status")
            if _v4_global(_v4_scope, 'isinstance')(stage, _v4_global(_v4_scope, 'Mapping'))
            else payload.get("status")
        )
        artifact_id = (
            payload.get("artifact_id")
            or payload.get("bundle_artifact_id")
            or (a_market.get("artifact_id") if _v4_global(_v4_scope, 'isinstance')(a_market, _v4_global(_v4_scope, 'Mapping')) else "")
            or payload.get("id")
            or ""
        )
        algorithm_id = payload.get("algorithm_id") or (
            a_market.get("algorithm_id") if _v4_global(_v4_scope, 'isinstance')(a_market, _v4_global(_v4_scope, 'Mapping')) else ""
        )
        algorithm_sha256 = payload.get("algorithm_sha256") or (
            a_market.get("algorithm_sha256") if _v4_global(_v4_scope, 'isinstance')(a_market, _v4_global(_v4_scope, 'Mapping')) else ""
        )
        raw_artifact_sha256 = payload.get("raw_artifact_sha256") or (
            a_market.get("raw_artifact_sha256") if _v4_global(_v4_scope, 'isinstance')(a_market, _v4_global(_v4_scope, 'Mapping')) else ""
        )
        source_refs.append(
            {
                "source_role": source_role,
                "response_source": response_source,
                "trade_date": trade_date,
                "stage_id": stage_id,
                "artifact_id": _v4_global(_v4_scope, 'str')(artifact_id),
                "run_id": run_id,
                "algorithm_id": _v4_global(_v4_scope, 'str')(algorithm_id or ""),
                "algorithm_sha256": _v4_global(_v4_scope, 'str')(algorithm_sha256 or ""),
                "raw_artifact_sha256": _v4_global(_v4_scope, 'str')(raw_artifact_sha256 or ""),
                "artifact_sha256": _v4_global(_v4_scope, '_sha256')(payload),
                "row_count": _v4_global(_v4_scope, 'len')(stage_rows),
                "status": _v4_global(_v4_scope, 'str')(stage_status or ""),
            }
        )
        rows.extend(stage_rows)
    return rows, source_refs
