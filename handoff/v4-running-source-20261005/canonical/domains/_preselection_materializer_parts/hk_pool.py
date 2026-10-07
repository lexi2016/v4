"""domains.preselection_materializer: hk_pool (review candidate, not deployment)."""
from __future__ import annotations

import base64
import binascii
from datetime import datetime

from ._namespace import read_global as _v4_global


_CAPTURE_AT_PROVENANCE_PREFIX = "b64url."


def _restore_hk_capture_at(value: object) -> str:
    """Project encoded shared capture provenance back to its exact ISO value."""
    text = str(value or "").strip()
    if not text.startswith(_CAPTURE_AT_PROVENANCE_PREFIX):
        return text
    encoded = text[len(_CAPTURE_AT_PROVENANCE_PREFIX) :]
    try:
        captured_at = base64.b64decode(
            encoded, altchars=b"-_", validate=True
        ).decode("utf-8")
        parsed = datetime.fromisoformat(captured_at)
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise ValueError("shared HK 0.2 capture-time provenance is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("shared HK 0.2 capture-time provenance must include a timezone")
    return captured_at


def _build_shared_hk_0_2_pool_body(
    _v4_scope,
    /,
    shared_data_root,
    *,
    trade_date,
    signal_date,
    eligibility_source_date,
    shared_package_root,
    reader,
):
    """Map the verified shared HK 0.2 Top100 into the V3.5 pool contract."""
    eligibility_source_date = eligibility_source_date or signal_date
    if reader is None:
        if shared_package_root is None:
            raise _v4_global(_v4_scope, 'ValueError')("shared_package_root is required for HK 0.2 verification")
        reader = _v4_global(_v4_scope, '_shared_hk_0_2_reader')(shared_package_root)
    reader_args = {
        "target_date": trade_date,
        "expected_signal_date": signal_date,
    }
    if eligibility_source_date != signal_date:
        reader_args["expected_eligibility_source_date"] = eligibility_source_date
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
    if eligibility_source_date != signal_date:
        source_provenance = _v4_global(_v4_scope, 'dict')(
            pool.run.manifest.get("provenance") or {}
        )
        historical_provenance = {
            "schema_version": "v4.hk_d1_split_date_provenance.v1",
            "price_signal_date": signal_date,
            "eligibility_source_date": eligibility_source_date,
            "eligibility_source_run_id": _v4_global(_v4_scope, 'str')(
                source_provenance.get("security_master_run_id") or ""
            ),
            "eligibility_source_artifact_sha256": _v4_global(_v4_scope, 'str')(
                source_provenance.get("security_master_artifact_sha256") or ""
            ),
            "eligibility_source_captured_at": _restore_hk_capture_at(
                source_provenance.get("security_master_captured_at") or ""
            ),
            "d1_source_run_id": _v4_global(_v4_scope, 'str')(verification["run_id"]),
            "d1_source_artifact_relative": _v4_global(_v4_scope, 'str')(
                verification.get("artifact_relative") or ""
            ),
            "d1_source_artifact_sha256": _v4_global(_v4_scope, 'str')(
                verification["artifact_sha256"]
            ),
            "d1_source_manifest_sha256": _v4_global(_v4_scope, 'str')(
                verification.get("manifest_sha256") or ""
            ),
            "d1_source_receipt_sha256": _v4_global(_v4_scope, 'str')(
                verification.get("receipt_sha256") or ""
            ),
        }
        if (
            source_provenance.get("signal_date") != signal_date
            or source_provenance.get("eligibility_source_date") != eligibility_source_date
            or source_provenance.get("security_master_trade_date") != eligibility_source_date
            or not historical_provenance["eligibility_source_run_id"]
            or not _v4_global(_v4_scope, 're').fullmatch(
                r"[0-9a-f]{64}", historical_provenance["eligibility_source_artifact_sha256"]
            )
            or not historical_provenance["eligibility_source_captured_at"]
            or historical_provenance["d1_source_artifact_relative"]
            != _v4_global(_v4_scope, 'str')(verification.get("artifact_relative") or "")
            or not _v4_global(_v4_scope, 're').fullmatch(
                r"[0-9a-f]{64}", historical_provenance["d1_source_artifact_sha256"]
            )
            or not _v4_global(_v4_scope, 're').fullmatch(
                r"[0-9a-f]{64}", historical_provenance["d1_source_manifest_sha256"]
            )
            or not _v4_global(_v4_scope, 're').fullmatch(
                r"[0-9a-f]{64}", historical_provenance["d1_source_receipt_sha256"]
            )
        ):
            raise _v4_global(_v4_scope, 'ValueError')(
                "shared HK 0.2 split-date eligibility provenance is incomplete"
            )
        artifact["historical_provenance"] = historical_provenance
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
