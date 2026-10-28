"""Graph-bound V3 preselection producers, without final-API imports."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

from infrastructure.isolated_package_loader import load_isolated_package_module
from infrastructure.preselection_pool_store import PreselectionPoolStore

HK_0_2_FROZEN_MODEL_SHA256 = "3b0d5d5239342439cabf25b30012365a64d78839bc3cd4d90bad7be6ff4aaa07"
SHARED_V192_ROLE = "A_SHARE_V192_PREMARKET_POOL_V3"
SHARED_V192_FORMULA_SOURCE = "computed_main_chart_formula_20260515"
SHARED_V192_RANK_BOUNDARY = "RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY"
SHARED_V192_ENTRY_FIELDS = (
    "gold_brick_context", "brick_resonance_context", "brick_buy",
    "brick_buy1_low_absorb", "brick_buy2_attack", "primary_buy_signal",
    "secondary_buy_signal", "brick_resonance1", "brick_resonance2",
    "brick_resonance", "formula_source",
)

_A_POOL_SOURCE_CONTRACT = {
    "a_d1_premarket_pool": ("V192_SELECTOR", "（选）", "selector_lane"),
    "a_d1_fupan_watchlist_pool": ("D1_FUPAN", "（复）", "fupan_lane"),
    "a_d1_stage7_fenshi_review_pool": ("D1_STAGE7", "（分）", "stage7_lane"),
}

_RESEARCH_SECTIONS = ("high_priority_candidates", "research_views_pending_review", "source_updates")
_RESEARCH_SOURCE_TOKENS = ("小牛研报纪要", "研报", "研究")
_RESEARCH_TITLE_TOKENS = ("研报", "纪要", "调研", "观点更新", "交流反馈")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact(
    *, trade_date: str, pool_id: str, display_name: str, market: str,
    status: str, producer_id: str, source_role: str, source_path: str,
    source_sha256: str, rows: list[dict[str, Any]], cannot_confirm: list[str] | None = None,
) -> dict[str, Any]:
    from domains._preselection_materializer_parts.row_assembly import __artifact_body as _v4_impl
    return _v4_impl(globals(), trade_date=trade_date, pool_id=pool_id, display_name=display_name, market=market, status=status, producer_id=producer_id, source_role=source_role, source_path=source_path, source_sha256=source_sha256, rows=rows, cannot_confirm=cannot_confirm)


def _a_symbol(value: Any) -> str:
    match = re.search(r"(?<!\d)(\d{6})(?:\.(?:SH|SZ|BJ))?", str(value or ""), re.I)
    return f"A.{match.group(1)}" if match else ""


def _a_symbol_from_row(raw: Mapping[str, Any]) -> str:
    candidates = {
        symbol
        for key in ("ts_code", "stock_code", "code")
        if (symbol := _a_symbol(raw.get(key)))
    }
    return candidates.pop() if len(candidates) == 1 else ""


def _row_number(value: Any, default: int) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _row_float(value: Any) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _normalize_a_csv_rows(path: Path, pool_id: str, trade_date: str) -> list[dict[str, Any]]:
    from domains._preselection_materializer_parts.row_assembly import __normalize_a_csv_rows_body as _v4_impl
    return _v4_impl(globals(), path, pool_id, trade_date)


def _parquet_trade_dates(parquet: Any) -> list[str]:
    from domains._preselection_materializer_parts.row_assembly import __parquet_trade_dates_body as _v4_impl
    return _v4_impl(globals(), parquet)


def build_selector_premarket_pool(selector_path: Path, trade_date: str) -> dict[str, Any]:
    """Fail closed: the old B-label observation pool is not v1.9.2."""
    from domains._preselection_materializer_parts.row_assembly import _build_selector_premarket_pool_body as _v4_impl
    return _v4_impl(globals(), selector_path, trade_date)


def build_legacy_selector_observation_pool(selector_path: Path, trade_date: str) -> dict[str, Any]:
    """Retained diagnostic-only B-label view; never used by scheduled pools."""
    from domains._preselection_materializer_parts.row_assembly import _build_legacy_selector_observation_pool_body as _v4_impl
    return _v4_impl(globals(), selector_path, trade_date)


def _load_isolated_shared_module(shared_package_root: Path, leaf: str):
    return load_isolated_package_module(
        Path(shared_package_root),
        package_directory="shared_data",
        module_leaf=leaf,
        namespace_prefix="v35_shared_data",
    )


def _shared_v192_reader(shared_package_root: Path):
    module = _load_isolated_shared_module(shared_package_root, "v192_selector")
    return module.read_verified_v192_pool


def _validate_shared_v192_projection(pool: Any, verification: Mapping[str, Any], *, trade_date: str, signal_date: str) -> list[dict[str, Any]]:
    from domains._preselection_materializer_parts.source_identity import __validate_shared_v192_projection_body as _v4_impl
    return _v4_impl(globals(), pool, verification, trade_date=trade_date, signal_date=signal_date)


def build_shared_v192_premarket_pool(
    shared_data_root: Path,
    *,
    trade_date: str,
    signal_date: str,
    shared_package_root: Path | None = None,
    reader=None,
) -> dict[str, Any]:
    """Map one verified shared v1.9.2 run into the V3.5 pool contract."""
    from domains._preselection_materializer_parts.row_assembly import _build_shared_v192_premarket_pool_body as _v4_impl
    return _v4_impl(globals(), shared_data_root, trade_date=trade_date, signal_date=signal_date, shared_package_root=shared_package_root, reader=reader)


def _shared_hk_0_2_reader(shared_package_root: Path):
    module = _load_isolated_shared_module(shared_package_root, "hk_0_2")
    return module.read_verified_hk_0_2_pool


def build_shared_hk_0_2_pool(
    shared_data_root: Path,
    *,
    trade_date: str,
    signal_date: str,
    eligibility_source_date: str | None = None,
    eligibility_universe_root: Path | None = None,
    shared_package_root: Path | None = None,
    reader=None,
    research_name_supplement: bool = False,
) -> dict[str, Any]:
    """Map the verified shared HK 0.2 Top100 into the V3.5 pool contract."""
    from domains._preselection_materializer_parts.hk_pool import _build_shared_hk_0_2_pool_body as _v4_impl
    loaded_pools = []
    if eligibility_universe_root is not None:
        if reader is None:
            if shared_package_root is None:
                raise ValueError("shared_package_root is required for HK 0.2 verification")
            reader = _shared_hk_0_2_reader(shared_package_root)
        verified_reader = reader

        def reader_with_eligibility_root(root, **reader_args):
            reader_args["eligibility_universe_root"] = Path(eligibility_universe_root)
            pool = verified_reader(root, **reader_args)
            loaded_pools.append(pool)
            return pool

        reader = reader_with_eligibility_root
    if research_name_supplement:
        if reader is None and shared_package_root is not None:
            reader = _shared_hk_0_2_reader(shared_package_root)
        if reader is not None:
            verified_reader = reader

            def reader_with_name_supplement(root, **reader_args):
                reader_args["research_name_supplement"] = True
                return verified_reader(root, **reader_args)

            reader = reader_with_name_supplement
    artifact = _v4_impl(globals(), shared_data_root, trade_date=trade_date, signal_date=signal_date, eligibility_source_date=eligibility_source_date, shared_package_root=shared_package_root, reader=reader)
    if loaded_pools:
        # The split-date helper owns the existing projection, while this
        # recovery-only caller needs the same verified as-of/price provenance
        # for equal dates too. It comes directly from the reader's verified
        # manifest and remains tied to the same D-1 artifact.
        pool = loaded_pools[0]
        source_provenance = dict(pool.run.manifest.get("provenance") or {})
        try:
            qualification = json.loads(
                bytes.fromhex(source_provenance["eligibility_asof_hex"]).decode("utf-8")
            )
        except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("shared HK 0.2 eligibility as-of is invalid") from error
        if (
            qualification.get("schema_version") != "v4.hk_eligibility_asof.v1"
            or qualification.get("source_date") != (eligibility_source_date or signal_date)
            or qualification.get("validity") not in {
                "EXACT_CAPTURE_DATE_ONLY", "OFFICIAL_EFFECTIVE_RECOVERY"
            }
            or qualification.get("natural_verified") is not False
            or any(qualification.get(flag) is not False for flag in (
                "production_allowed", "buy_gate_updated", "orders_sent"
            ))
        ):
            raise ValueError("shared HK 0.2 eligibility as-of/date mismatch")
        historical_provenance = {
            "schema_version": "v4.hk_d1_eligibility_asof.v2",
            "price_signal_date": signal_date,
            "eligibility_source_date": eligibility_source_date or signal_date,
            "eligibility_asof": qualification,
            "d1_source_run_id": artifact["source_run_id"],
            "d1_source_artifact_sha256": artifact["source_sha256"],
            "d1_source_manifest_sha256": artifact.get("source_manifest_sha256") or "",
            "d1_source_receipt_sha256": artifact.get("source_receipt_sha256") or "",
        }
        price_history_hex = source_provenance.get("price_history_recovery_hex")
        if price_history_hex:
            try:
                price_history = json.loads(
                    bytes.fromhex(price_history_hex).decode("utf-8")
                )
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("shared HK 0.2 price history provenance is invalid") from error
            if (
                price_history.get("schema_version") != "v4.hk_history_price_recovery.v1"
                or price_history.get("source_date") != signal_date
                or price_history.get("provider") != "MIXED_PYTDX_HQ_DAILY_AND_FUTU_OPEND_HISTORY_KLINE"
                or price_history.get("adjustment") != "NONE"
                or price_history.get("natural_verified") is not False
                or "APPROXIMATE_NOT_LOSSLESS" not in str(price_history.get("volume_unit_status") or "")
            ):
                raise ValueError("shared HK 0.2 price history provenance mismatch")
            historical_provenance["price_recovery"] = price_history
        artifact["historical_provenance"] = historical_provenance
    return artifact


def build_upstream_csv_pool(
    path: Path, trade_date: str, *, pool_id: str, display_name: str, market: str,
    status: str, producer_id: str,
) -> dict[str, Any]:
    from domains._preselection_materializer_parts.row_assembly import _build_upstream_csv_pool_body as _v4_impl
    return _v4_impl(globals(), path, trade_date, pool_id=pool_id, display_name=display_name, market=market, status=status, producer_id=producer_id)


def build_hkconnect_strict_0_2_pool(
    pool_path: Path,
    standard_manifest_path: Path,
    model_manifest_path: Path,
    model_bundle_path: Path,
    *,
    trade_date: str,
    signal_date: str,
) -> dict[str, Any]:
    """Verify the frozen V3 0.2 contract before projecting its Top100.

    A CSV is never sufficient evidence for ``STRICT_0_2_READY``. The source
    must carry the standard result manifest, the frozen model manifest and the
    model bundle whose SHA is pinned by the V3 oracle.
    """
    from domains._preselection_materializer_parts.hk_pool import _build_hkconnect_strict_0_2_pool_body as _v4_impl
    return _v4_impl(globals(), pool_path, standard_manifest_path, model_manifest_path, model_bundle_path, trade_date=trade_date, signal_date=signal_date)


def _manifest(path: Path, *, source_bytes: bytes | None = None) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes() if source_bytes is None else source_bytes
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid upstream manifest: {path}") from error
    if not isinstance(payload, Mapping):
        raise ValueError(f"invalid upstream manifest: {path}")
    return dict(payload)


def _combined_sha256(paths: Iterable[Path]) -> str:
    return hashlib.sha256(
        "".join(_sha256(Path(path)) for path in paths).encode("ascii")
    ).hexdigest()


def build_fupan_watchlist_pool(
    pool_path: Path,
    manifest_path: Path,
    *,
    trade_date: str,
    signal_date: str,
) -> dict[str, Any]:
    from domains._preselection_materializer_parts.row_assembly import _build_fupan_watchlist_pool_body as _v4_impl
    return _v4_impl(globals(), pool_path, manifest_path, trade_date=trade_date, signal_date=signal_date)


def build_stage7_review_pool(
    pool_path: Path,
    manifest_path: Path,
    *,
    trade_date: str,
    signal_date: str,
) -> dict[str, Any]:
    from domains._preselection_materializer_parts.row_assembly import _build_stage7_review_pool_body as _v4_impl
    return _v4_impl(globals(), pool_path, manifest_path, trade_date=trade_date, signal_date=signal_date)


def _normalize_name(value: Any) -> str:
    text = re.sub(r"[\(（]\s*代码待核\s*[\)）]", "", str(value or "").strip())
    return re.sub(r"\s+", "", text).strip("：:，,。；;#【】[]“”\"' ")


def _selector_name_map(selector_path: Path) -> dict[str, str]:
    from domains._preselection_materializer_parts.row_assembly import __selector_name_map_body as _v4_impl
    return _v4_impl(globals(), selector_path)


def _research_window(trade_date: str) -> tuple[datetime, datetime]:
    from domains._preselection_materializer_parts.row_assembly import __research_window_body as _v4_impl
    return _v4_impl(globals(), trade_date)


def _parse_dt(value: Any) -> datetime | None:
    from infrastructure.market_time import parse_shanghai

    text = str(value or "").strip()
    if not text:
        return None
    try:
        return parse_shanghai(text)
    except ValueError:
        return None


def _target_symbols(item: Mapping[str, Any], names: Mapping[str, str]) -> Iterable[tuple[str, str]]:
    from domains._preselection_materializer_parts.row_assembly import __target_symbols_body as _v4_impl
    return (yield from _v4_impl(globals(), item, names))


def build_research_preview_pool(preview_path: Path, selector_path: Path, trade_date: str) -> dict[str, Any]:
    from domains._preselection_materializer_parts.row_assembly import _build_research_preview_pool_body as _v4_impl
    return _v4_impl(globals(), preview_path, selector_path, trade_date)


def build_hourly_research_pool(
    data_root: Path,
    trade_date: str,
    *,
    store: Any | None = None,
) -> dict[str, Any]:
    """Build the V3 research pool from verified V3.5 hourly archives.

    The time window is the frozen V3 window: D-1 08:30 to D 08:30 on a
    normal day and Friday 00:00 to Monday 09:00 for a Monday target.  Hourly
    archives are cumulative, so article identity is deduplicated before the
    per-stock recommendation count is calculated.
    """
    from domains._preselection_materializer_parts.hourly_pool import _build_hourly_research_pool_body as _v4_impl
    return _v4_impl(globals(), data_root, trade_date, store=store)


def build_expected_missing_pool(trade_date: str, *, pool_id: str, display_name: str, market: str, reason: str) -> dict[str, Any]:
    return _artifact(
        trade_date=trade_date, pool_id=pool_id, display_name=display_name, market=market,
        status="CANNOT_CONFIRM", producer_id="graph_expected_missing_v1", source_role="EXPECTED_MISSING",
        source_path="", source_sha256=hashlib.sha256(b"").hexdigest(), rows=[], cannot_confirm=[reason],
    )


def build_baimao_pool(path: Path | None, trade_date: str) -> dict[str, Any]:
    from domains._preselection_materializer_parts.a_share_pool import _build_baimao_pool_body as _v4_impl
    return _v4_impl(globals(), path, trade_date)


def build_wechat_pool(manifest_path: Path, rows_path: Path, trade_date: str) -> dict[str, Any]:
    manifest_path, rows_path = Path(manifest_path), Path(rows_path)
    manifest_raw = manifest_path.read_bytes()
    manifest = _manifest(manifest_path, source_bytes=manifest_raw)
    if not isinstance(manifest, Mapping) or manifest.get("status") != "WECHAT_V3_PRESELECT_READY":
        raise ValueError("invalid WeChat upstream manifest")
    if manifest.get("effective_trade_date") != trade_date:
        raise ValueError("WeChat upstream effective trade-date mismatch")
    target_validation = manifest.get("target_validation")
    if not isinstance(target_validation, Mapping) or target_validation.get("status") != "TARGET_DATE_CHECK_PASS":
        raise ValueError("WeChat upstream target-date evidence is missing")
    boundary = manifest.get("boundary")
    if not isinstance(boundary, Mapping) or boundary.get("formal_pool_write") is not False or boundary.get("buy_gate_write") is not False:
        raise ValueError("WeChat upstream research-only boundary mismatch")
    if manifest.get("score_scope") != "wechat_pool_ts_codes_only":
        raise ValueError("WeChat upstream score scope mismatch")
    from domains._preselection_materializer_parts.row_assembly import _build_upstream_csv_snapshot
    rows_raw = rows_path.read_bytes()
    artifact = _build_upstream_csv_snapshot(
        globals(), rows_path, rows_raw, trade_date, pool_id="wechat_public_account_v3_preselect",
        display_name="公众号股票池", market="A", status="WECHAT_V3_PRESELECT_READY",
        producer_id="v3_wechat_preselect_upstream_v1",
    )
    counts = manifest.get("counts", {})
    if not isinstance(counts, Mapping):
        raise ValueError("invalid WeChat upstream counts")
    expected = counts.get("v3_matched_codes")
    if isinstance(expected, int) and len(artifact["rows"]) != expected:
        raise ValueError("WeChat upstream manifest row-count mismatch")
    signal_date = str(manifest.get("signal_date") or manifest.get("article_publish_date") or "")
    article_publish_date = str(manifest.get("article_publish_date") or signal_date)
    if not re.fullmatch(r"\d{8}", signal_date) or not re.fullmatch(r"\d{8}", article_publish_date):
        raise ValueError("WeChat upstream article signal-date evidence is missing")
    for index, row in enumerate(artifact["rows"], start=1):
        row.update(
            pool_rank=_row_number(row.get("wechat_v3_preselect_rank"), index),
            pool_score=_row_float(row.get("candidate_score")),
            recommendation_status="RESEARCH_ONLY",
            trade_status_contract="RESEARCH_ONLY_NO_BUY_GATE",
            signal_date=signal_date,
            effective_trade_date=trade_date,
            article_publish_date=article_publish_date,
            article_url=str(row.get("wechat_source_ref") or manifest.get("article_url") or ""),
        )
    artifact["source_path"] = f"{manifest_path}|{rows_path}"
    artifact["source_sha256"] = hashlib.sha256(
        (hashlib.sha256(manifest_raw).hexdigest() + artifact["source_sha256"]).encode("ascii")
    ).hexdigest()
    artifact["source_role"] = "VERIFIED_WECHAT_RESEARCH"
    artifact["cannot_confirm"] = ["RESEARCH_ONLY_NO_BUY_GATE"]
    return artifact


def materialize_preselection_date(store: PreselectionPoolStore, artifacts: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Materialize already-produced graph-bound pool artifacts independently."""
    results = []
    for artifact in artifacts:
        results.append(store.materialize(artifact))
    return results
