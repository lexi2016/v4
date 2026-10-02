"""domains.preselection_materializer: hk_pool (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_shared_hk_0_2_pool_body(
    _v4_scope,
    /,
    shared_data_root,
    *,
    trade_date,
    signal_date,
    eligibility_source_date,
    eligibility_universe_root=None,
    shared_package_root,
    reader,
):
    """Map the verified shared HK 0.2 Top100 into the V3.5 pool contract."""
    from contracts.trading_calendar import load_market_calendar, previous_session
    expected_price = previous_session(load_market_calendar(), trade_date, market="hk_securities")
    if signal_date != expected_price:
        raise _v4_global(_v4_scope, 'ValueError')("shared HK 0.2 stale price signal; not a formal Stage input")
    eligibility_source_date = eligibility_source_date or signal_date
    if reader is None:
        if shared_package_root is None:
            raise _v4_global(_v4_scope, 'ValueError')("shared_package_root is required for HK 0.2 verification")
        reader = _v4_global(_v4_scope, '_shared_hk_0_2_reader')(shared_package_root)
    reader_args = {
        "target_date": trade_date,
        "expected_signal_date": signal_date,
    }
    reader_args["expected_eligibility_source_date"] = eligibility_source_date
    if eligibility_universe_root is not None:
        reader_args["eligibility_universe_root"] = eligibility_universe_root
    pool = reader(_v4_global(_v4_scope, 'Path')(shared_data_root), **reader_args)
    verification = pool.run.verification
    receipt = pool.run.receipt
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if receipt.get(key) is not False:
            raise _v4_global(_v4_scope, 'ValueError')(f"shared HK 0.2 safety flag {key} must be false")
    rows: list[dict[str, Any]] = []
    previous_score: float | None = None
    for index, raw_value in _v4_global(_v4_scope, 'enumerate')(pool.rows, start=1):
        raw = _v4_global(_v4_scope, 'dict')(raw_value)
        code = _v4_global(_v4_scope, 'str')(raw.get("code_norm") or raw.get("code") or "").strip().upper().removeprefix("HK.")
        rank = _v4_global(_v4_scope, '_row_number')(raw.get("rank"), index)
        score = _v4_global(_v4_scope, '_row_float')(raw.get("score_prob_active"))
        if not _v4_global(_v4_scope, 're').fullmatch(r"\d{5}", code) or rank != index:
            raise _v4_global(_v4_scope, 'ValueError')("shared HK 0.2 identity/rank mismatch")
        if previous_score is not None and score > previous_score:
            raise _v4_global(_v4_scope, 'ValueError')("shared HK 0.2 score order mismatch")
        if _v4_global(_v4_scope, 'str')(raw.get("signal_date") or "") != signal_date or _v4_global(_v4_scope, 'str')(raw.get("target_date") or "") != trade_date:
            raise _v4_global(_v4_scope, 'ValueError')("shared HK 0.2 row date mismatch")
        if _v4_global(_v4_scope, 'str')(raw.get("d1_freshness_status") or "") != "PASS" or _v4_global(_v4_scope, 'str')(raw.get("selected_strategy") or "") != "prob_active":
            raise _v4_global(_v4_scope, 'ValueError')("shared HK 0.2 semantic contract mismatch")
        rows.append({
            **raw,
            "symbol": f"HK.{code}",
            "market": "HK",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": rank,
            "stock_name": _v4_global(_v4_scope, 'str')(raw.get("name") or f"HK.{code}"),
            "pool_score": score,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
        previous_score = score
    if _v4_global(_v4_scope, 'len')(rows) != 100 or _v4_global(_v4_scope, 'len')({row["symbol"] for row in rows}) != 100:
        raise _v4_global(_v4_scope, 'ValueError')("shared HK 0.2 Top100 count mismatch")
    artifact = _v4_global(_v4_scope, '_artifact')(
        trade_date=trade_date,
        pool_id="hkconnect_d1_top100",
        display_name="港股通 0.2 D-1 Top100",
        market="HK",
        status="STRICT_0_2_READY",
        producer_id="v3_shared_hk_0_2_consumer_v1",
        source_role="SHARED_VERIFIED_HK_0_2",
        source_path=_v4_global(_v4_scope, 'str')(verification["artifact_relative"]),
        source_sha256=_v4_global(_v4_scope, 'str')(verification["artifact_sha256"]),
        rows=rows,
        cannot_confirm=["RESEARCH_ONLY_NOT_BUY_GATE"],
    )
    artifact["source_run_id"] = _v4_global(_v4_scope, 'str')(verification["run_id"])
    artifact["source_row_count"] = _v4_global(_v4_scope, 'int')(verification["row_count"])
    source_manifest_sha256 = _v4_global(_v4_scope, 'str')(
        verification.get("manifest_sha256") or ""
    )
    source_receipt_sha256 = _v4_global(_v4_scope, 'str')(
        verification.get("receipt_sha256") or ""
    )
    if source_manifest_sha256:
        artifact["source_manifest_sha256"] = source_manifest_sha256
    if source_receipt_sha256:
        artifact["source_receipt_sha256"] = source_receipt_sha256
    artifact["signal_date"] = signal_date
    artifact["target_date"] = trade_date
    artifact["stage_selection_eligible"] = True
    source_provenance = _v4_global(_v4_scope, 'dict')(pool.run.manifest.get("provenance") or {})
    try:
        qualification = _v4_global(_v4_scope, 'json').loads(
            bytes.fromhex(source_provenance["eligibility_asof_hex"]).decode("utf-8")
        )
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise _v4_global(_v4_scope, 'ValueError')("shared HK 0.2 eligibility as-of is invalid") from error
    if (qualification.get("schema_version") != "v4.hk_eligibility_asof.v1"
            or qualification.get("source_date") != eligibility_source_date
            or qualification.get("validity") != "EXACT_CAPTURE_DATE_ONLY"
            or eligibility_source_date != signal_date
            or any(qualification.get(flag) is not False for flag in
                   ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise _v4_global(_v4_scope, 'ValueError')("shared HK 0.2 eligibility as-of/date mismatch")
    artifact["historical_provenance"] = {
        "schema_version": "v4.hk_d1_eligibility_asof.v2",
        "price_signal_date": signal_date,
        "eligibility_source_date": eligibility_source_date,
        "eligibility_asof": qualification,
        "d1_source_run_id": artifact["source_run_id"],
        "d1_source_artifact_sha256": artifact["source_sha256"],
        "d1_source_manifest_sha256": source_manifest_sha256,
        "d1_source_receipt_sha256": source_receipt_sha256,
    }
    return artifact


def _build_hkconnect_strict_0_2_pool_body(_v4_scope, /, pool_path, standard_manifest_path, model_manifest_path, model_bundle_path, *, trade_date, signal_date):
    """Verify the frozen V3 0.2 contract before projecting its Top100.

    A CSV is never sufficient evidence for ``STRICT_0_2_READY``. The source
    must carry the standard result manifest, the frozen model manifest and the
    model bundle whose SHA is pinned by the V3 oracle.
    """
    paths = _v4_global(_v4_scope, 'tuple')(
        _v4_global(_v4_scope, 'Path')(path)
        for path in (
            pool_path,
            standard_manifest_path,
            model_manifest_path,
            model_bundle_path,
        )
    )
    if _v4_global(_v4_scope, 'any')(not path.is_file() for path in paths):
        raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 evidence file missing")
    pool_path, standard_manifest_path, model_manifest_path, model_bundle_path = paths
    standard = _v4_global(_v4_scope, 'json').loads(standard_manifest_path.read_text(encoding="utf-8-sig"))
    model = _v4_global(_v4_scope, 'json').loads(model_manifest_path.read_text(encoding="utf-8-sig"))
    if not _v4_global(_v4_scope, 'isinstance')(standard, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(model, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 manifest is invalid")
    if (
        standard.get("schema_version") != "hkconnect_0_2_d1_top100_standard_manifest.v1"
        or standard.get("status") != "STRICT_0_2_READY"
        or standard.get("strict_exact_0_2_ready") is not True
        or standard.get("source") != "tdx_vipdoc_71_day"
    ):
        raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 requires the canonical TDX VIPDOC source")
    if (
        _v4_global(_v4_scope, 'str')(standard.get("target_date") or "") != trade_date
        or _v4_global(_v4_scope, 'str')(standard.get("signal_date") or "") != signal_date
    ):
        raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 date contract mismatch")
    if (
        standard.get("d1_freshness_status") != "PASS"
        or standard.get("d1_freshness_ok") is not True
        or standard.get("research_only") is not True
        or standard.get("production_allowed") is not False
        or standard.get("buy_gate_changed") is not False
        or standard.get("orders_sent") is not False
        or _v4_global(_v4_scope, 'str')(standard.get("primary_strategy") or standard.get("strategy") or "") != "prob_active"
    ):
        raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 standard manifest boundary mismatch")
    feature_columns = model.get("feature_columns")
    if (
        model.get("schema_version") != "hkconnect_d1_model_bundle.v1"
        or model.get("primary_strategy") != "prob_active"
        or model.get("research_only") is not True
        or model.get("production_allowed") is not False
        or not _v4_global(_v4_scope, 'isinstance')(feature_columns, _v4_global(_v4_scope, 'list'))
        or model.get("feature_count") != _v4_global(_v4_scope, 'len')(feature_columns)
        or _v4_global(_v4_scope, 'str')(model.get("trained_through") or "") > signal_date
    ):
        raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 frozen model manifest mismatch")
    bundle_sha = _v4_global(_v4_scope, '_sha256')(model_bundle_path)
    if (
        bundle_sha != _v4_global(_v4_scope, 'HK_0_2_FROZEN_MODEL_SHA256')
        or _v4_global(_v4_scope, 'str')(model.get("bundle_sha256") or "") != bundle_sha
        or _v4_global(_v4_scope, 'str')(model.get("bundle_file") or "") != model_bundle_path.name
    ):
        raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 frozen model SHA mismatch")
    leakage_prefixes = ("target_", "label_", "future_")
    if _v4_global(_v4_scope, 'any')(_v4_global(_v4_scope, 'str')(field).lower().startswith(leakage_prefixes) for field in feature_columns):
        raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 model feature leakage")

    with pool_path.open("r", encoding="utf-8-sig", newline="") as source:
        raw_rows = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'csv').DictReader(source))
    expected_count = _v4_global(_v4_scope, 'int')(standard.get("row_count") or standard.get("pool_size") or 0)
    if expected_count != 100 or _v4_global(_v4_scope, 'len')(raw_rows) != 100:
        raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 Top100 row count mismatch")
    rows: list[dict[str, Any]] = []
    seen: set[str] = _v4_global(_v4_scope, 'set')()
    previous_score: float | None = None
    for index, raw in _v4_global(_v4_scope, 'enumerate')(raw_rows, start=1):
        code = _v4_global(_v4_scope, 'str')(raw.get("code_norm") or raw.get("code") or "").strip().upper().removeprefix("HK.")
        if not _v4_global(_v4_scope, 're').fullmatch(r"\d{5}", code) or code in seen:
            raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 code identity mismatch")
        rank = _v4_global(_v4_scope, '_row_number')(raw.get("rank"), index)
        score = _v4_global(_v4_scope, '_row_float')(raw.get("score_prob_active"))
        if rank != index or (previous_score is not None and score > previous_score):
            raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 rank order mismatch")
        row_signal = _v4_global(_v4_scope, 'str')(raw.get("signal_date") or signal_date)
        row_target = _v4_global(_v4_scope, 'str')(raw.get("target_date") or trade_date)
        if row_signal != signal_date or row_target != trade_date:
            raise _v4_global(_v4_scope, 'ValueError')("strict HK 0.2 row date mismatch")
        seen.add(code)
        previous_score = score
        rows.append({
            **raw,
            "symbol": f"HK.{code}",
            "market": "HK",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": rank,
            "stock_name": _v4_global(_v4_scope, 'str')(raw.get("name") or f"HK.{code}"),
            "pool_score": score,
            "signal_date": signal_date,
            "target_date": trade_date,
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    source_sha = _v4_global(_v4_scope, 'hashlib').sha256(
        "".join(_v4_global(_v4_scope, '_sha256')(path) for path in paths).encode("ascii")
    ).hexdigest()
    return _v4_global(_v4_scope, '_artifact')(
        trade_date=trade_date,
        pool_id="hkconnect_d1_top100",
        display_name="港股通 0.2 D-1 Top100",
        market="HK",
        status="STRICT_0_2_READY",
        producer_id="v3_hkconnect_0_2_verified_v1",
        source_role="VERIFIED_HK_0_2_STANDARD",
        source_path="|".join(_v4_global(_v4_scope, 'str')(path) for path in paths),
        source_sha256=source_sha,
        rows=rows,
        cannot_confirm=["RESEARCH_ONLY_NOT_BUY_GATE"],
    )
