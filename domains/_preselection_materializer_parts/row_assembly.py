"""domains.preselection_materializer: row_assembly (review candidate, not deployment)."""
from __future__ import annotations
import io
from ._namespace import read_global as _v4_global


def __artifact_body(_v4_scope, /, *, trade_date, pool_id, display_name, market, status, producer_id, source_role, source_path, source_sha256, rows, cannot_confirm):
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "display_name": display_name,
        "market": market,
        "status": status,
        "producer_id": producer_id,
        "source_role": source_role,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "rows": rows,
        "cannot_confirm": _v4_global(_v4_scope, 'list')(cannot_confirm or []),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def __normalize_a_csv_rows_body(_v4_scope, /, path, pool_id, trade_date):
    raw = _v4_global(_v4_scope, 'Path')(path).read_bytes()
    return _normalize_a_csv_snapshot(_v4_scope, raw, pool_id, trade_date)


def _normalize_a_csv_snapshot(_v4_scope, raw, pool_id, trade_date):
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as source:
        raw_rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'csv').DictReader(source))
    rows: list[dict[str, Any]] = []
    for index, raw in _v4_global(_v4_scope, 'enumerate')(raw_rows, start=1):
        symbol = _v4_global(_v4_scope, '_a_symbol_from_row')(raw)
        if not symbol:
            continue
        row = _v4_global(_v4_scope, 'dict')(raw)
        row.update({
            "symbol": symbol,
            "market": "A",
            "pool_id": pool_id,
            "pool_rank": _v4_global(_v4_scope, '_row_number')(raw.get("pool_rank") or raw.get("rank"), index),
            "stock_name": _v4_global(_v4_scope, 'str')(raw.get("stock_name") or raw.get("name") or symbol),
            "pool_score": _v4_global(_v4_scope, '_row_float')(raw.get("pool_score") or raw.get("stage7_next_day_pool_score")),
            "signal_date": _v4_global(_v4_scope, 'str')(raw.get("signal_date") or ""),
            "target_date": trade_date,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "formal_pool_write": False,
            "buy_gate_write": False,
        })
        source_tag, source_suffix, source_lane = _v4_global(_v4_scope, '_A_POOL_SOURCE_CONTRACT').get(
            pool_id, ("", "", "")
        )
        if source_suffix:
            row["display_name"] = row.get("display_name") or f"{row['stock_name']}{source_suffix}"
            row["source_tag"] = row.get("source_tag") or source_tag
            row["source_tags"] = row.get("source_tags") or source_suffix
            row["source_lanes"] = row.get("source_lanes") or source_lane
        rows.append(row)
    return rows


def __parquet_trade_dates_body(_v4_scope, /, parquet):
    index = parquet.schema.names.index("trade_date")
    dates: set[str] = _v4_global(_v4_scope, 'set')()
    for row_group in _v4_global(_v4_scope, 'range')(parquet.num_row_groups):
        column = parquet.metadata.row_group(row_group).column(index)
        statistics = column.statistics
        if statistics is not None and statistics.min is not None and statistics.max is not None:
            minimum, maximum = _v4_global(_v4_scope, 'str')(statistics.min), _v4_global(_v4_scope, 'str')(statistics.max)
            if minimum == maximum and _v4_global(_v4_scope, 'len')(minimum) == 8 and minimum.isdigit():
                dates.add(minimum)
                continue
        for value in parquet.read_row_group(row_group, columns=["trade_date"]).column("trade_date").to_pylist():
            text = _v4_global(_v4_scope, 'str')(value or "")
            if _v4_global(_v4_scope, 'len')(text) == 8 and text.isdigit():
                dates.add(text)
    return _v4_global(_v4_scope, 'sorted')(dates)


def _build_selector_premarket_pool_body(_v4_scope, /, selector_path, trade_date):
    """Fail closed: the old B-label observation pool is not v1.9.2."""
    selector_path = _v4_global(_v4_scope, 'Path')(selector_path)
    return _v4_global(_v4_scope, '_artifact')(
        trade_date=trade_date,
        pool_id="a_d1_premarket_pool",
        display_name="A股 D-1 主预选池",
        market="A",
        status="CANNOT_CONFIRM",
        producer_id="legacy_observation_pool_blocker_v1",
        source_role="LEGACY_OBSERVATION_DISABLED",
        source_path=_v4_global(_v4_scope, 'str')(selector_path),
        source_sha256=_v4_global(_v4_scope, '_sha256')(selector_path) if selector_path.is_file() else _v4_global(_v4_scope, 'hashlib').sha256(b"").hexdigest(),
        rows=[],
        cannot_confirm=["LEGACY_OBSERVATION_POOL_DISABLED"],
    )


def _build_legacy_selector_observation_pool_body(_v4_scope, /, selector_path, trade_date):
    """Retained diagnostic-only B-label view; never used by scheduled pools."""
    import pandas as pd
    import pyarrow.parquet as pq

    selector_path = _v4_global(_v4_scope, 'Path')(selector_path)
    parquet = pq.ParquetFile(selector_path)
    signal_dates = [value for value in _v4_global(_v4_scope, '_parquet_trade_dates')(parquet) if value < trade_date]
    if not signal_dates:
        return _v4_global(_v4_scope, '_artifact')(
            trade_date=trade_date, pool_id="a_d1_premarket_pool", display_name="A股 D-1 主预选池",
            market="A", status="CANNOT_CONFIRM", producer_id="v3_selector_premarket_v1",
            source_role="RAW_SOURCE", source_path=_v4_global(_v4_scope, 'str')(selector_path), source_sha256=_v4_global(_v4_scope, '_sha256')(selector_path),
            rows=[], cannot_confirm=["D1_SELECTOR_SIGNAL_DATE_UNRESOLVED"],
        )
    signal_date = signal_dates[-1]
    wanted = [
        "trade_date", "ts_code", "name", "primary_buy_signal", "secondary_buy_signal",
        "ref_hold_score", "B1", "B2", "B3", "BG", "pct_chg", "amount",
        "route_context", "gold_brick_context", "brick_context",
    ]
    available = [field for field in wanted if field in parquet.schema.names]
    table = pq.read_table(selector_path, columns=available, filters=[("trade_date", "==", signal_date)])
    frame = table.to_pandas()
    frame = frame[frame["ts_code"].astype(_v4_global(_v4_scope, 'str')).str.endswith((".SH", ".SZ"), na=False)].copy()
    if "name" in frame.columns:
        frame = frame[~frame["name"].astype(_v4_global(_v4_scope, 'str')).str.contains("ST", case=False, na=False)].copy()
    else:
        frame["name"] = ""
    had_primary = "primary_buy_signal" in frame.columns
    had_secondary = "secondary_buy_signal" in frame.columns
    numeric = ["primary_buy_signal", "secondary_buy_signal", "ref_hold_score", "B1", "B2", "B3", "BG", "amount", "pct_chg"]
    for field in numeric:
        frame[field] = pd.to_numeric(frame[field], errors="coerce").fillna(0) if field in frame else 0
    if not had_primary:
        frame["primary_buy_signal"] = ((frame["B1"] > 0) | (frame["B2"] > 0) | (frame["B3"] > 0)).astype(_v4_global(_v4_scope, 'int'))
    if not had_secondary:
        frame["secondary_buy_signal"] = ((frame["BG"] > 0) & (frame["primary_buy_signal"] <= 0)).astype(_v4_global(_v4_scope, 'int'))
    if _v4_global(_v4_scope, 'int')(((frame["primary_buy_signal"] > 0) | (frame["secondary_buy_signal"] > 0)).sum()) == 0 and _v4_global(_v4_scope, 'int')(((frame["B1"] > 0) | (frame["B2"] > 0) | (frame["B3"] > 0) | (frame["BG"] > 0)).sum()) > 0:
        frame["primary_buy_signal"] = ((frame["B1"] > 0) | (frame["B2"] > 0) | (frame["B3"] > 0)).astype(_v4_global(_v4_scope, 'int'))
        frame["secondary_buy_signal"] = ((frame["BG"] > 0) & (frame["primary_buy_signal"] <= 0)).astype(_v4_global(_v4_scope, 'int'))
    frame = frame[(frame["primary_buy_signal"] > 0) | (frame["secondary_buy_signal"] > 0)].copy()
    frame["pool_score"] = (
        frame["primary_buy_signal"] * 100 + frame["secondary_buy_signal"] * 70
        + frame["B1"] * 8 + frame["B2"] * 12 + frame["B3"] * 5 + frame["BG"] * 5
        + frame["ref_hold_score"] * 3 + (frame["amount"] / 100_000_000).clip(upper=5)
    )
    frame = frame.sort_values(["primary_buy_signal", "pool_score", "amount"], ascending=[False, False, False]).reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for index, raw in _v4_global(_v4_scope, 'enumerate')(frame.to_dict(orient="records"), start=1):
        symbol = _v4_global(_v4_scope, '_a_symbol')(raw.get("ts_code"))
        rows.append({
            **raw, "symbol": symbol, "market": "A", "pool_id": "a_d1_premarket_pool",
            "pool_rank": index, "stock_name": _v4_global(_v4_scope, 'str')(raw.get("name") or symbol),
            "signal_date": signal_date, "target_date": trade_date,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        })
    return _v4_global(_v4_scope, '_artifact')(
        trade_date=trade_date, pool_id="a_d1_premarket_pool", display_name="A股 D-1 主预选池",
        market="A", status="FORMAL_INCOMPLETE" if rows else "CANNOT_CONFIRM",
        producer_id="v3_selector_premarket_v1", source_role="RAW_SOURCE",
        source_path=_v4_global(_v4_scope, 'str')(selector_path), source_sha256=_v4_global(_v4_scope, '_sha256')(selector_path), rows=rows,
        cannot_confirm=["OBSERVATION_POOL_NOT_FORMAL_BUY_POOL"],
    )


def _build_shared_v192_premarket_pool_body(_v4_scope, /, shared_data_root, *, trade_date, signal_date, shared_package_root, reader):
    """Map one verified shared v1.9.2 run into the V3.5 pool contract."""
    if reader is None:
        if shared_package_root is None:
            raise _v4_global(_v4_scope, 'ValueError')("shared_package_root is required for v1.9.2 verification")
        reader = _v4_global(_v4_scope, '_shared_v192_reader')(shared_package_root)
    pool = reader(
        _v4_global(_v4_scope, 'Path')(shared_data_root),
        target_date=trade_date,
        expected_signal_date=signal_date,
    )
    verification = pool.run.verification
    receipt = pool.run.receipt
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if receipt.get(key) is not False:
            raise _v4_global(_v4_scope, 'ValueError')(f"shared v1.9.2 safety flag {key} must be false")
    source_rows = _v4_global(_v4_scope, '_validate_shared_v192_projection')(
        pool,
        verification,
        trade_date=trade_date,
        signal_date=signal_date,
    )
    rows: list[dict[str, Any]] = []
    missing_premarket_score_codes: list[str] = []
    for raw in source_rows:
        symbol = _v4_global(_v4_scope, '_a_symbol')(raw.get("ts_code"))
        if not symbol:
            raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 row has invalid A-share symbol")
        raw_premarket_score = raw.get("premarket_pool_score")
        has_premarket_score = raw_premarket_score not in (None, "")
        if has_premarket_score:
            try:
                premarket_score = _v4_global(_v4_scope, 'float')(_v4_global(_v4_scope, 'str')(raw_premarket_score))
            except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
                raise _v4_global(_v4_scope, 'ValueError')("shared v1.9.2 premarket score drift")
        else:
            premarket_score = None
        if premarket_score is None:
            missing_premarket_score_codes.append(symbol)
        rows.append({
            **_v4_global(_v4_scope, 'dict')(raw),
            "symbol": symbol,
            "market": "A",
            "pool_id": "a_d1_premarket_pool",
            "pool_rank": _v4_global(_v4_scope, '_row_number')(raw.get("review_rank_v19"), _v4_global(_v4_scope, 'len')(rows) + 1),
            # ``final_score`` is the v1.9.2 selector score, not the legacy
            # V3 premarket-pool score.  Only the explicitly materialized
            # shared score is allowed to drive V3.5 stage scoring.
            "pool_score": premarket_score,
            "premarket_score_status": "READY" if premarket_score is not None else "CANNOT_CONFIRM",
            "stock_name": _v4_global(_v4_scope, 'str')(raw.get("stock_name") or symbol),
            "signal_date": signal_date,
            "target_date": trade_date,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "formal_pool_write": False,
            "buy_gate_write": False,
            "display_name": f"{_v4_global(_v4_scope, 'str')(raw.get('stock_name') or symbol)}（选）",
            "source_tag": "V192_SELECTOR",
            "source_tags": "（选）",
            "source_lanes": "selector_lane",
            "source_trace": _v4_global(_v4_scope, 'str')(raw.get("source_trace") or verification["artifact_relative"]),
        })
    artifact = _v4_global(_v4_scope, '_artifact')(
        trade_date=trade_date,
        pool_id="a_d1_premarket_pool",
        display_name="A股 D-1 v1.9.2候选池",
        market="A",
        status="V192_CANDIDATE_READY" if rows else "V192_CANDIDATE_READY_EMPTY",
        producer_id="v3_shared_v192_consumer_v1",
        source_role="SHARED_VERIFIED_V192",
        source_path=_v4_global(_v4_scope, 'str')(verification["artifact_relative"]),
        source_sha256=_v4_global(_v4_scope, 'str')(verification["artifact_sha256"]),
        rows=rows,
        cannot_confirm=[
            "RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY",
            *(
                [
                    "V3_PREMARKET_POOL_SCORE_MISSING:" + ",".join(missing_premarket_score_codes)
                ]
                if missing_premarket_score_codes
                else []
            ),
        ],
    )
    artifact["source_run_id"] = _v4_global(_v4_scope, 'str')(verification["run_id"])
    artifact["source_row_count"] = _v4_global(_v4_scope, 'int')(verification["row_count"])
    # Keep the formal shared V3 identity explicit at the artifact boundary.
    # Consumers must not infer a V2/V3 version from the producer name or path.
    artifact.update(
        artifact_role=_v4_global(_v4_scope, 'SHARED_V192_ROLE'),
        artifact_version="V3",
        source_artifact_sha256=_v4_global(_v4_scope, 'str')(verification["artifact_sha256"]),
        signal_date=signal_date,
        target_date=trade_date,
        source_merge_role="MAIN_STAGE_INPUT",
        stage_selection_eligible=True,
    )
    return artifact


def _build_upstream_csv_pool_body(_v4_scope, /, path, trade_date, *, pool_id, display_name, market, status, producer_id):
    if pool_id == "hkconnect_d1_top100" or status == "STRICT_0_2_READY":
        raise _v4_global(_v4_scope, 'ValueError')(
            "strict HK 0.2 requires its standard manifest, frozen model proof, and D-1 freshness proof"
        )
    raw = _v4_global(_v4_scope, 'Path')(path).read_bytes()
    return _build_upstream_csv_snapshot(
        _v4_scope, path, raw, trade_date, pool_id=pool_id, display_name=display_name,
        market=market, status=status, producer_id=producer_id,
    )


def _build_upstream_csv_snapshot(_v4_scope, path, raw_bytes, trade_date, *, pool_id, display_name, market, status, producer_id):
    if pool_id == "hkconnect_d1_top100" or status == "STRICT_0_2_READY":
        raise _v4_global(_v4_scope, 'ValueError')(
            "strict HK 0.2 requires its standard manifest, frozen model proof, and D-1 freshness proof"
        )
    path = _v4_global(_v4_scope, 'Path')(path)
    if market == "A":
        rows = _normalize_a_csv_snapshot(_v4_scope, raw_bytes, pool_id, trade_date)
    else:
        with io.StringIO(raw_bytes.decode("utf-8-sig"), newline="") as source:
            raw_rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'csv').DictReader(source))
        rows = []
        for index, raw in _v4_global(_v4_scope, 'enumerate')(raw_rows, start=1):
            code = _v4_global(_v4_scope, 'str')(raw.get("code_norm") or raw.get("code") or "").upper()
            match = _v4_global(_v4_scope, 're').search(r"(\d{5})", code)
            if not match:
                continue
            symbol = f"HK.{match.group(1)}"
            rows.append({
                **raw, "symbol": symbol, "market": "HK", "pool_id": pool_id,
                "pool_rank": _v4_global(_v4_scope, '_row_number')(raw.get("rank"), index),
                "stock_name": _v4_global(_v4_scope, 'str')(raw.get("name") or symbol),
                "pool_score": _v4_global(_v4_scope, '_row_float')(raw.get("score_prob_active") or raw.get("hybrid_score")),
                "recommendation_status": "WATCH_ONLY", "target_date": trade_date,
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            })
    actual_status = status if rows else ("MISSING" if pool_id == "a_d1_fupan_watchlist_pool" else "CANNOT_CONFIRM")
    return _v4_global(_v4_scope, '_artifact')(
        trade_date=trade_date, pool_id=pool_id, display_name=display_name, market=market,
        status=actual_status, producer_id=producer_id, source_role="UPSTREAM_PRODUCER_ARTIFACT",
        source_path=_v4_global(_v4_scope, 'str')(path), source_sha256=_v4_global(_v4_scope, 'hashlib').sha256(raw_bytes).hexdigest(), rows=rows,
        cannot_confirm=[] if rows else [f"{pool_id.upper()}_NO_ROWS"],
    )


def _build_fupan_watchlist_pool_body(_v4_scope, /, pool_path, manifest_path, *, trade_date, signal_date):
    manifest_raw = _v4_global(_v4_scope, 'Path')(manifest_path).read_bytes()
    manifest = _v4_global(_v4_scope, '_manifest')(manifest_path, source_bytes=manifest_raw)
    if not _v4_global(_v4_scope, 'str')(manifest.get("status") or "").startswith("FUPAN_WATCHLIST_POOL_READY"):
        raise _v4_global(_v4_scope, 'ValueError')("invalid D-1 fupan pool status")
    if manifest.get("fupan_pool_rule") != "AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW":
        raise _v4_global(_v4_scope, 'ValueError')("invalid D-1 fupan pool rule")
    if manifest.get("target_date") != trade_date or manifest.get("signal_date") != signal_date:
        raise _v4_global(_v4_scope, 'ValueError')("D-1 fupan pool date mismatch")
    if not _v4_global(_v4_scope, 'isinstance')(manifest.get("source_paths"), _v4_global(_v4_scope, 'list')) or not manifest["source_paths"]:
        raise _v4_global(_v4_scope, 'ValueError')("D-1 fupan source evidence is missing")
    pool_raw = _v4_global(_v4_scope, 'Path')(pool_path).read_bytes()
    artifact = _build_upstream_csv_snapshot(
        _v4_scope, pool_path, pool_raw, trade_date,
        pool_id="a_d1_fupan_watchlist_pool",
        display_name="A股 D-1 复盘继续观察池",
        market="A",
        status=_v4_global(_v4_scope, 'str')(manifest["status"]),
        producer_id="v3_fupan_watchlist_contract_v1",
    )
    if manifest.get("row_count") != _v4_global(_v4_scope, 'len')(artifact["rows"]):
        raise _v4_global(_v4_scope, 'ValueError')("D-1 fupan manifest row-count mismatch")
    if _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'str')(row.get("signal_date") or "") != signal_date for row in artifact["rows"]):
        raise _v4_global(_v4_scope, 'ValueError')("D-1 fupan row signal-date mismatch")
    artifact.update(
        source_role="VERIFIED_D1_FUPAN_REVIEW",
        source_path=f"{manifest_path}|{pool_path}",
        source_sha256=_v4_global(_v4_scope, 'hashlib').sha256(
            (_v4_global(_v4_scope, 'hashlib').sha256(manifest_raw).hexdigest() + artifact['source_sha256']).encode('ascii')
        ).hexdigest(),
        cannot_confirm=[_v4_global(_v4_scope, 'str')(item) for item in manifest.get("cannot_confirm") or []],
    )
    return artifact


def _build_stage7_review_pool_body(_v4_scope, /, pool_path, manifest_path, *, trade_date, signal_date):
    manifest_raw = _v4_global(_v4_scope, 'Path')(manifest_path).read_bytes()
    manifest = _v4_global(_v4_scope, '_manifest')(manifest_path, source_bytes=manifest_raw)
    if not _v4_global(_v4_scope, 'str')(manifest.get("status") or "").startswith("STAGE7_TAIL_POOL_READY"):
        raise _v4_global(_v4_scope, 'ValueError')("invalid D-1 Stage7 pool status")
    if manifest.get("target_date") != trade_date or manifest.get("signal_date") != signal_date:
        raise _v4_global(_v4_scope, 'ValueError')("D-1 Stage7 pool date mismatch")
    if manifest.get("source_role") != "real_d1_stage7_tail_replay":
        raise _v4_global(_v4_scope, 'ValueError')("D-1 Stage7 strict pool requires real tail replay")
    upstream = manifest.get("upstream_manifest")
    if not _v4_global(_v4_scope, 'isinstance')(upstream, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("D-1 Stage7 upstream manifest is missing")
    if upstream.get("trade_date") != signal_date or upstream.get("stage_id") != "STAGE_1445_1500":
        raise _v4_global(_v4_scope, 'ValueError')("D-1 Stage7 upstream identity mismatch")
    if _v4_global(_v4_scope, 'any')(upstream.get(key) is not False for key in (
        "production_allowed", "buy_gate_updated", "orders_sent"
    )):
        raise _v4_global(_v4_scope, 'ValueError')("D-1 Stage7 upstream safety contract mismatch")
    pool_raw = _v4_global(_v4_scope, 'Path')(pool_path).read_bytes()
    artifact = _build_upstream_csv_snapshot(
        _v4_scope, pool_path, pool_raw, trade_date,
        pool_id="a_d1_stage7_fenshi_review_pool",
        display_name="A股 D-1 Stage7/分时复盘池",
        market="A",
        status=_v4_global(_v4_scope, 'str')(manifest["status"]),
        producer_id="v3_stage7_tail_replay_contract_v1",
    )
    if manifest.get("row_count") != _v4_global(_v4_scope, 'len')(artifact["rows"]):
        raise _v4_global(_v4_scope, 'ValueError')("D-1 Stage7 manifest row-count mismatch")
    if _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'str')(row.get("signal_date") or "") != signal_date for row in artifact["rows"]):
        raise _v4_global(_v4_scope, 'ValueError')("D-1 Stage7 row signal-date mismatch")
    artifact.update(
        source_role="VERIFIED_D1_STAGE7_REPLAY",
        source_path=f"{manifest_path}|{pool_path}",
        source_sha256=_v4_global(_v4_scope, 'hashlib').sha256(
            (_v4_global(_v4_scope, 'hashlib').sha256(manifest_raw).hexdigest() + artifact['source_sha256']).encode('ascii')
        ).hexdigest(),
        cannot_confirm=[_v4_global(_v4_scope, 'str')(item) for item in manifest.get("cannot_confirm") or []],
    )
    return artifact


def __selector_name_map_body(_v4_scope, /, selector_path):
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(selector_path)
    latest = _v4_global(_v4_scope, '_parquet_trade_dates')(parquet)[-1]
    table = pq.read_table(selector_path, columns=["ts_code", "name"], filters=[("trade_date", "==", latest)])
    grouped: dict[str, set[str]] = _v4_global(_v4_scope, 'defaultdict')(_v4_global(_v4_scope, 'set'))
    for raw_code, raw_name in _v4_global(_v4_scope, 'zip')(table.column("ts_code").to_pylist(), table.column("name").to_pylist()):
        symbol = _v4_global(_v4_scope, '_a_symbol')(raw_code)
        name = _v4_global(_v4_scope, '_normalize_name')(raw_name)
        if symbol and name:
            grouped[name].add(symbol)
    return {name: _v4_global(_v4_scope, 'next')(_v4_global(_v4_scope, 'iter')(symbols)) for name, symbols in grouped.items() if _v4_global(_v4_scope, 'len')(symbols) == 1}


def __research_window_body(_v4_scope, /, trade_date):
    from contracts.trading_calendar import load_market_calendar, previous_session
    from infrastructure.market_time import as_shanghai

    target = as_shanghai(_v4_global(_v4_scope, 'datetime').strptime(trade_date, "%Y%m%d"))
    prior = as_shanghai(
        _v4_global(_v4_scope, 'datetime').strptime(
            previous_session(
                load_market_calendar(),
                trade_date,
                market="a_share",
            ),
            "%Y%m%d",
        )
    )
    if (target.date() - prior.date()).days > 1:
        return prior.replace(hour=0), target.replace(hour=9)
    return prior.replace(hour=8, minute=30), target.replace(hour=8, minute=30)


def __target_symbols_body(_v4_scope, /, item, names):
    for field in ("symbols", "stock_focus", "verified_stock_focus"):
        values = item.get(field) or []
        if _v4_global(_v4_scope, 'isinstance')(values, _v4_global(_v4_scope, 'str')):
            values = [values]
        if not _v4_global(_v4_scope, 'isinstance')(values, _v4_global(_v4_scope, 'list')):
            continue
        for value in values:
            symbol = _v4_global(_v4_scope, '_a_symbol')(value)
            name = _v4_global(_v4_scope, '_normalize_name')(value)
            if symbol:
                yield symbol, field
            elif name in names:
                yield names[name], f"{field}_exact_name"


def _build_research_preview_pool_body(_v4_scope, /, preview_path, selector_path, trade_date):
    preview_path, selector_path = _v4_global(_v4_scope, 'Path')(preview_path), _v4_global(_v4_scope, 'Path')(selector_path)
    payload = _v4_global(_v4_scope, 'json').loads(preview_path.read_text(encoding="utf-8-sig"))
    names = _v4_global(_v4_scope, '_selector_name_map')(selector_path)
    start, end = _v4_global(_v4_scope, '_research_window')(trade_date)
    grouped: dict[str, list[dict[str, Any]]] = _v4_global(_v4_scope, 'defaultdict')(_v4_global(_v4_scope, 'list'))
    for section in _v4_global(_v4_scope, '_RESEARCH_SECTIONS'):
        for item in payload.get(section) or []:
            if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')):
                continue
            targets = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, '_target_symbols')(item, names))
            source_name, title = _v4_global(_v4_scope, 'str')(item.get("source_name") or ""), _v4_global(_v4_scope, 'str')(item.get("title") or "")
            is_research = _v4_global(_v4_scope, 'bool')(targets) and (
                (_v4_global(_v4_scope, 'str')(item.get("source_type") or "").upper() == "ZSXQ" and _v4_global(_v4_scope, 'any')(token in source_name for token in _v4_global(_v4_scope, '_RESEARCH_SOURCE_TOKENS')))
                or _v4_global(_v4_scope, 'any')(token in title for token in _v4_global(_v4_scope, '_RESEARCH_TITLE_TOKENS'))
            )
            source_dt = _v4_global(_v4_scope, '_parse_dt')(item.get("published_at")) or _v4_global(_v4_scope, '_parse_dt')(item.get("fetched_at"))
            if not is_research or source_dt is None or not (start <= source_dt < end):
                continue
            source_id = _v4_global(_v4_scope, 'str')(item.get("id") or item.get("topic_id") or title)
            for symbol, field in targets:
                grouped[symbol].append({"source_id": source_id, "field": field, "source_dt": source_dt.isoformat(), "title": title})
    rows: list[dict[str, Any]] = []
    for symbol, items in grouped.items():
        items.sort(key=lambda item: (item["source_dt"], item["source_id"]))
        first = items[0]
        rows.append({
            "symbol": symbol, "code": symbol.removeprefix("A."), "market": "A",
            "pool_id": "a_share_research_recommendation_pool", "stock_name": symbol,
            "pool_score": _v4_global(_v4_scope, 'len')({item["source_id"] for item in items}), "signal_date": "",
            "target_date": trade_date, "recommendation_status": "RESEARCH_ONLY",
            "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE", "first_source_dt": first["source_dt"],
            "research_title": first["title"], "entity_resolution_source": first["field"],
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        })
    rows.sort(key=lambda row: (-_v4_global(_v4_scope, 'int')(row["pool_score"]), row["first_source_dt"], row["code"]))
    for index, row in _v4_global(_v4_scope, 'enumerate')(rows, start=1):
        row["pool_rank"] = index
    combined_sha = _v4_global(_v4_scope, 'hashlib').sha256((_v4_global(_v4_scope, '_sha256')(preview_path) + _v4_global(_v4_scope, '_sha256')(selector_path)).encode("ascii")).hexdigest()
    return _v4_global(_v4_scope, '_artifact')(
        trade_date=trade_date, pool_id="a_share_research_recommendation_pool",
        display_name="A股研报推荐股票池", market="A",
        status="RESEARCH_RECOMMENDATION_POOL_READY" if rows else "CANNOT_CONFIRM",
        producer_id="v3_research_preview_v1", source_role="RAW_SOURCE",
        source_path=f"{preview_path}|{selector_path}", source_sha256=combined_sha, rows=rows,
        cannot_confirm=["RESEARCH_ONLY_NO_BUY_GATE"],
    )
