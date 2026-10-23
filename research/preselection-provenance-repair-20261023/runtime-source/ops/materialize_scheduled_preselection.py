"""Materialize the next-trading-day preselection contract for the scheduler.

The A-share D-1 selector pool is produced from the V3.5 selector-ready panel
using the frozen V3 scoring/sort function.  Optional graph upstreams are read
only when their exact target-date files exist; an absent upstream becomes an
explicit zero-row ``CANNOT_CONFIRM`` artifact and receipt, never a fabricated
stock row.  No V3 runtime path or final-output import is used.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from domains.preselection_materializer import (
    build_baimao_pool,
    build_expected_missing_pool,
    build_fupan_watchlist_pool,
    build_shared_hk_0_2_pool,
    build_hourly_research_pool,
    build_research_preview_pool,
    build_shared_v192_premarket_pool,
    build_stage7_review_pool,
    build_wechat_pool,
    materialize_preselection_date,
)
from infrastructure.preselection_pool_store import PreselectionPoolStore, validate_pool_artifact, _is_exact_expected_missing_placeholder
from infrastructure.baimao_preselection_pool_source import load_baimao_preselection_pool


DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "data"

_FORMAL_POOL_READY_STATUSES = {
    "a_d1_premarket_pool": frozenset({"V192_CANDIDATE_READY"}),
    "hkconnect_d1_top100": frozenset(
        {"STRICT_0_2_READY", "HK_0_2_TOP100_READY"}
    ),
}


def _formal_pool_gate(artifacts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Check the required A/HK artifacts after materialization.

    Optional graph lanes remain independently materialized and are returned to
    the caller, but an explicit missing/empty formal pair must stay retryable
    instead of being reported as a successful scheduled run.
    """

    by_id = {
        str(artifact.get("pool_id") or ""): artifact
        for artifact in artifacts
        if isinstance(artifact, Mapping)
    }
    missing_or_invalid: list[str] = []
    required: dict[str, dict[str, object]] = {}
    research_ready_all = True
    has_partial_hk = False
    for pool_id, ready_statuses in _FORMAL_POOL_READY_STATUSES.items():
        artifact = by_id.get(pool_id)
        status = str(artifact.get("status") or "") if artifact else "MISSING"
        rows = artifact.get("rows") if artifact else None
        row_count = len(rows) if isinstance(rows, list) else 0
        ready = status in ready_statuses and row_count > 0
        research_ready = ready
        if pool_id == "hkconnect_d1_top100" and status == "PARTIAL_WITH_ROWS":
            source_sha = str(artifact.get("source_sha256") or "").lower() if artifact else ""
            source_artifact_sha = str(artifact.get("source_artifact_sha256") or "").lower() if artifact else ""
            reasons = artifact.get("cannot_confirm") if artifact else None
            research_ready = bool(
                artifact
                and 1 <= row_count <= 100
                and artifact.get("trade_date") == artifact.get("target_date")
                and artifact.get("market") == "HK"
                and artifact.get("producer_id") == "v3_shared_hk_0_2_consumer_v1"
                and artifact.get("source_role") == "UPSTREAM_PRODUCER_ARTIFACT"
                and artifact.get("stage_selection_eligible") is True
                and artifact.get("source_row_count") == row_count
                and re.fullmatch(r"[0-9a-f]{64}", source_sha) is not None
                and source_artifact_sha == source_sha
                and artifact.get("source_run_id")
                and isinstance(reasons, list)
                and reasons
                and all(str(reason).startswith("HK_0_2_") for reason in reasons)
                and artifact.get("production_allowed") is False
                and artifact.get("buy_gate_updated") is False
                and artifact.get("orders_sent") is False
            )
            has_partial_hk = research_ready
        research_ready_all = research_ready_all and research_ready
        required[pool_id] = {
            "status": status,
            "row_count": row_count,
            "ready": ready,
            "research_ready": research_ready,
        }
        if not ready:
            missing_or_invalid.append(pool_id)
    if not missing_or_invalid:
        gate_status = "READY"
    elif has_partial_hk and research_ready_all and missing_or_invalid == ["hkconnect_d1_top100"]:
        gate_status = "PARTIAL_WITH_ROWS"
    else:
        gate_status = "CANNOT_CONFIRM"
    eligible_pools: dict[str, list[str]] = {"A": [], "HK": []}
    rejected_pools: list[str] = []
    for artifact in artifacts:
        try:
            validate_pool_artifact(artifact)
        except (ValueError, TypeError):
            rejected_pools.append(str(artifact.get("pool_id") or ""))
            continue
        market = str(artifact.get("market") or "")
        rows = artifact.get("rows")
        role = artifact.get("source_role")
        if (market not in eligible_pools or not isinstance(rows, list) or not rows
                or role == "EXPECTED_MISSING"
                or artifact.get("status") in {"CANNOT_CONFIRM", "MISSING", "VALID_EMPTY"}
                or artifact.get("stage_selection_eligible") is False
                or artifact.get("source_merge_role") == "SOURCE_ONLY"):
            continue
        # Publication validates every artifact. Research uses its existing
        # VERIFIED_HOURLY_RESEARCH contract; it has no eligibility flag.
        if (role == "VERIFIED_HOURLY_RESEARCH"
                or artifact.get("stage_selection_eligible") is True
                or role in {"VERIFIED_D1_FUPAN_REVIEW", "VERIFIED_D1_STAGE7_REVIEW"}):
            eligible_pools[market].append(str(artifact["pool_id"]))
    usable = any(eligible_pools.values())
    if usable and (missing_or_invalid or rejected_pools):
        gate_status = "PARTIAL_WITH_ROWS"
    elif not usable:
        gate_status = "CANNOT_CONFIRM"
    return {
        "status": gate_status,
        "research_ready": usable,
        "eligible_pools_by_market": eligible_pools,
        "rejected_pools": rejected_pools,
        "required": required,
        "missing_or_invalid": missing_or_invalid,
    }


def _verified_cached_formal_pool(store, pool_id, trade_date, shared_root, package_root):
    """Verify the current shared chain and compare its complete local projection."""
    from infrastructure.isolated_package_loader import load_isolated_package_module
    from infrastructure.scheduling.executor_registry_preselection import _hk_price_and_eligibility_dates
    cached = store.read_pool(trade_date, pool_id)
    validate_pool_artifact(cached)
    if pool_id == "hkconnect_d1_top100":
        signal, eligibility = _hk_price_and_eligibility_dates(trade_date)
        if signal != eligibility:
            raise ValueError("HK_SPLIT_DATE_CONTRACT_UNSUPPORTED")
        leaf, reader_name, builder = "hk_0_2", "read_verified_hk_0_2_pool", build_shared_hk_0_2_pool
    else:
        from contracts.trading_calendar import load_market_calendar, previous_session
        signal = previous_session(load_market_calendar(), trade_date, market="a_share")
        leaf, reader_name, builder = "v192_selector", "read_verified_v192_pool", build_shared_v192_premarket_pool
    module = load_isolated_package_module(package_root, package_directory="shared_data",
        module_leaf=leaf, namespace_prefix="preselection_cache_verification")
    verified = getattr(module, reader_name)(shared_root, target_date=trade_date, expected_signal_date=signal)
    # The strict reader owns validation. Retain any immutable registry pins
    # as well as optional cache duplicates; a missing cache field cannot
    # discard a declared source-chain hash.
    for key in ("artifact_sha256", "manifest_sha256", "receipt_sha256"):
        if key in verified.run.latest and verified.run.latest[key] != verified.run.verification[key]:
            raise ValueError("FORMAL_SOURCE_REGISTRY_HASH_MISMATCH:" + key)
    if verified.run.receipt.get("status") != "READY":
        raise ValueError("FORMAL_CACHE_SOURCE_NOT_READY")
    fresh = builder(shared_root, trade_date=trade_date, signal_date=signal, reader=lambda *a, **k: verified)
    if (cached.get("status") not in _FORMAL_POOL_READY_STATUSES[pool_id] | {"READY"}
            or not cached.get("rows") or cached.get("stage_selection_eligible") is not True):
        raise ValueError("FORMAL_CACHE_NOT_READY")
    for field in ("pool_id", "market", "trade_date", "target_date", "signal_date",
                  "source_role", "source_sha256", "source_run_id", "source_row_count", "rows"):
        if cached.get(field) != fresh.get(field):
            raise ValueError("FORMAL_CACHE_SOURCE_PROJECTION_MISMATCH:" + field)
    for field, key in (("source_artifact_sha256", "artifact_sha256"),
                       ("source_manifest_sha256", "manifest_sha256"),
                       ("source_receipt_sha256", "receipt_sha256")):
        if field in cached and cached[field] != verified.run.verification[key]:
            raise ValueError("FORMAL_CACHE_DECLARED_HASH_MISMATCH:" + field)
    return cached


def _missing(
    trade_date: str,
    *,
    pool_id: str,
    display_name: str,
    market: str,
    reason: str,
) -> dict:
    return build_expected_missing_pool(
        trade_date,
        pool_id=pool_id,
        display_name=display_name,
        market=market,
        reason=reason,
    )


def _is_expected_verified_input_error(error: Exception) -> bool:
    """Recognize typed shared-store input failures without hiding bugs."""
    error_type = type(error)
    return isinstance(error, (FileNotFoundError, ValueError)) or (
        error_type.__name__ == "StoreError"
        and str(error_type.__module__).endswith(".store")
    )


def _quarantined_research_cache(data_root: Path, trade_date: str, error: Exception) -> dict:
    """Keep a rejected immutable cache as evidence, without rebuilding it."""
    from infrastructure.owned_io import SafeRoot
    root = Path(data_root)
    reader = SafeRoot(root)
    pool_id = "a_share_research_recommendation_pool"
    artifact = _missing(trade_date, pool_id=pool_id, display_name="A股研报推荐股票池",
        market="A", reason=f"A_RESEARCH_CACHE_REJECTED:{type(error).__name__}:{error}")
    directory = root / "preselection_pools" / trade_date
    for path in (directory / f"{pool_id}.json", directory / "manifest.json",
                 directory / "receipts" / f"{pool_id}.json"):
        try:
            digest = hashlib.sha256(reader.read_bytes(str(path.relative_to(root)))).hexdigest()
            observation = f"REJECTED_INPUT_OBSERVED_AFTER_ERROR:{path}:sha256={digest}"
        except (OSError, ValueError) as read_error:
            observation = f"REJECTED_INPUT_UNREADABLE:{path}:{type(read_error).__name__}"
        artifact["cannot_confirm"].append(observation)
    return artifact


def _input_error_code(prefix: str, error: Exception) -> str:
    """Map a fail-closed verified-input error to a truthful lane reason."""
    missing_markers = ("missing", "no latest", "not found", "not exist")
    if isinstance(error, FileNotFoundError) or any(
        marker in str(error).lower() for marker in missing_markers
    ):
        return f"{prefix}_EXACT_INPUT_MISSING"
    return f"{prefix}_EXACT_INPUT_CONTRACT_INVALID"


def build_scheduled_artifacts(
    *,
    trade_date: str,
    signal_date: str,
    selector: Path | None,
    input_root: Path,
    shared_data_root: Path,
    shared_package_root: Path,
    data_root: Path,
    pool_reader=None,
    hk_pool_reader=None,
    hk_target_date: str | None = None,
    hk_signal_date: str | None = None,
    hk_eligibility_source_date: str | None = None,
    reuse_formal_pools: Mapping[str, Mapping] | None = None,
    quarantine_formal_pools: Sequence[str] = (),
) -> list[dict]:
    from infrastructure.scheduling.executor_registry_preselection import (
        _hk_next_target_date, _hk_preselection_source_dates,
    )

    expected_hk_target = _hk_next_target_date(signal_date)
    expected_hk_signal, expected_hk_eligibility = _hk_preselection_source_dates(
        signal_date, expected_hk_target
    )
    hk_target_date = hk_target_date or expected_hk_target
    hk_signal_date = hk_signal_date or expected_hk_signal
    hk_eligibility_source_date = hk_eligibility_source_date or expected_hk_eligibility
    if (hk_target_date, hk_signal_date, hk_eligibility_source_date) != (
        expected_hk_target, expected_hk_signal, expected_hk_eligibility
    ):
        raise ValueError("HK preselection dates do not match the frozen calendar")
    hk_date_contract_error = (
        "HK_SPLIT_DATE_CONTRACT_UNSUPPORTED"
        if hk_eligibility_source_date != hk_signal_date else ""
    )

    day = Path(input_root) / trade_date
    fupan = day / "fupan.csv"
    fupan_manifest = day / "fupan.manifest.json"
    stage7 = day / "stage7.csv"
    stage7_manifest = day / "stage7.manifest.json"
    research = day / "research_preview.json"
    baimao = day / "baimao.json"
    wechat_rows = day / "wechat_rows.csv"
    wechat_manifest = day / "wechat_manifest.json"

    reused_formal = dict(reuse_formal_pools or {})

    try:
        research_artifact = PreselectionPoolStore(data_root).read_pool(
            trade_date, "a_share_research_recommendation_pool")
        if (research_artifact.get("source_role") != "VERIFIED_HOURLY_RESEARCH"
                or research_artifact.get("status") != "RESEARCH_RECOMMENDATION_POOL_READY"
                or not research_artifact.get("rows")):
            raise FileNotFoundError("research pool not ready")
    except FileNotFoundError:
        research_artifact = None
    except (OSError, UnicodeError, ValueError) as error:
        research_artifact = _quarantined_research_cache(data_root, trade_date, error)
    try:
        if research_artifact is None:
            research_artifact = build_hourly_research_pool(data_root, trade_date=trade_date)
    except FileNotFoundError:
        if research.is_file() and selector is not None:
            research_artifact = build_research_preview_pool(
                research, selector, trade_date
            )
        else:
            research_artifact = _missing(
                trade_date,
                pool_id="a_share_research_recommendation_pool",
                display_name="A股研报推荐股票池",
                market="A",
                reason=(
                    "A_SELECTOR_PANEL_UNAVAILABLE"
                    if research.is_file() and selector is None
                    else "A_RESEARCH_HOURLY_WINDOW_EVIDENCE_MISSING"
                ),
            )

    if "a_d1_premarket_pool" in quarantine_formal_pools:
        a_premarket = _missing(trade_date, pool_id="a_d1_premarket_pool",
            display_name="A股 D-1 v1.9.2候选池", market="A", reason="A_V192_EXACT_INPUT_CONTRACT_INVALID")
    elif "a_d1_premarket_pool" in reused_formal:
        a_premarket = dict(reused_formal["a_d1_premarket_pool"])
    else:
        try:
            a_premarket = build_shared_v192_premarket_pool(
                shared_data_root,
                trade_date=trade_date,
                signal_date=signal_date,
                shared_package_root=shared_package_root,
                reader=pool_reader,
            )
        except Exception as error:
            if not _is_expected_verified_input_error(error):
                raise
            reason_code = _input_error_code("A_V192", error)
            a_premarket = _missing(
                trade_date,
                pool_id="a_d1_premarket_pool",
                display_name="A股 D-1 v1.9.2候选池",
                market="A",
                reason=f"{reason_code}:{error}",
            )
    if "hkconnect_d1_top100" in quarantine_formal_pools:
        hk_0_2 = _missing(hk_target_date, pool_id="hkconnect_d1_top100",
            display_name="港股通 0.2 D-1 Top100", market="HK", reason="HK_0_2_EXACT_INPUT_CONTRACT_INVALID")
    elif hk_date_contract_error:
        hk_0_2 = _missing(hk_target_date, pool_id="hkconnect_d1_top100",
            display_name="港股通 0.2 D-1 Top100", market="HK", reason=hk_date_contract_error)
    elif ("hkconnect_d1_top100" in reused_formal
            and hk_target_date == trade_date):
        hk_0_2 = dict(reused_formal["hkconnect_d1_top100"])
    else:
        try:
            hk_0_2 = build_shared_hk_0_2_pool(
                shared_data_root,
                trade_date=hk_target_date,
                signal_date=hk_signal_date,
                shared_package_root=shared_package_root,
                reader=hk_pool_reader,
            )
        except Exception as error:
            if not _is_expected_verified_input_error(error):
                raise
            reason_code = _input_error_code("HK_0_2", error)
            hk_0_2 = _missing(
                hk_target_date,
                pool_id="hkconnect_d1_top100",
                display_name="港股通 0.2 D-1 Top100",
                market="HK",
                reason=f"{reason_code}:{error}",
            )

    try:
        fupan_artifact = (
            build_fupan_watchlist_pool(
                fupan,
                fupan_manifest,
                trade_date=trade_date,
                signal_date=signal_date,
            ) if fupan.is_file() and fupan_manifest.is_file() else _missing(
                trade_date,
                pool_id="a_d1_fupan_watchlist_pool",
                display_name="A股 D-1 复盘继续观察池",
                market="A",
                reason="A_D1_FUPAN_WATCHLIST_EVIDENCE_MISSING",
            )
        )
    except (UnicodeDecodeError, csv.Error) as error:
        fupan_artifact = _missing(
            trade_date,
            pool_id="a_d1_fupan_watchlist_pool",
            display_name="A股 D-1 复盘继续观察池",
            market="A",
            reason=f"A_D1_FUPAN_INPUT_CONTRACT_INVALID:{type(error).__name__}:{error}",
        )
        for path in (fupan_manifest, fupan):
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                observation = f"REJECTED_INPUT_OBSERVED_AFTER_ERROR:{path}:sha256={digest}"
            except OSError as read_error:
                observation = f"REJECTED_INPUT_UNREADABLE:{path}:{type(read_error).__name__}"
            fupan_artifact["cannot_confirm"].append(observation)

    try:
        stage7_artifact = (
            build_stage7_review_pool(
                stage7,
                stage7_manifest,
                trade_date=trade_date,
                signal_date=signal_date,
            ) if stage7.is_file() and stage7_manifest.is_file() else _missing(
                trade_date,
                pool_id="a_d1_stage7_fenshi_review_pool",
                display_name="A股 D-1 Stage7/分时复盘池",
                market="A",
                reason="A_D1_STAGE7_FENSHI_EVIDENCE_MISSING",
            )
        )
    except (UnicodeDecodeError, csv.Error) as error:
        stage7_artifact = _missing(
            trade_date,
            pool_id="a_d1_stage7_fenshi_review_pool",
            display_name="A股 D-1 Stage7/分时复盘池",
            market="A",
            reason=f"A_D1_STAGE7_INPUT_CONTRACT_INVALID:{type(error).__name__}:{error}",
        )
        for path in (stage7_manifest, stage7):
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                observation = f"REJECTED_INPUT_OBSERVED_AFTER_ERROR:{path}:sha256={digest}"
            except OSError as read_error:
                observation = f"REJECTED_INPUT_UNREADABLE:{path}:{type(read_error).__name__}"
            stage7_artifact["cannot_confirm"].append(observation)

    return [
        a_premarket,
        fupan_artifact,
        stage7_artifact,
        research_artifact,
        build_baimao_pool(baimao, trade_date)
        if baimao.is_file()
        else load_baimao_preselection_pool(
            shared_data_root,
            shared_package_root,
            trade_date,
        ),
        hk_0_2,
        build_wechat_pool(wechat_manifest, wechat_rows, trade_date)
        if wechat_manifest.is_file() and wechat_rows.is_file() else _missing(
            trade_date,
            pool_id="wechat_public_account_v3_preselect",
            display_name="公众号股票池",
            market="A",
            reason="WECHAT_V3_PRESELECT_UPSTREAM_MISSING",
        ),
    ]


_AUTO_RECOVERABLE_OPTIONAL_POOLS = {
    "a_d1_premarket_pool": "SHARED_VERIFIED_V192",
    "a_d1_fupan_watchlist_pool": "VERIFIED_D1_FUPAN_REVIEW",
    "a_d1_stage7_fenshi_review_pool": "VERIFIED_D1_STAGE7_REPLAY",
}


_FORMAL_IMMUTABLE_POOLS = frozenset({"a_d1_premarket_pool", "hkconnect_d1_top100"})


class ScheduledPoolPublicationError(ValueError):
    """Preserve conflict failure semantics while exposing every sibling result."""
    def __init__(self, results: list[dict[str, Any]]) -> None:
        super().__init__("conflicting preselection-pool materialization")
        self.results = results


def publish_scheduled_artifacts(
    store: PreselectionPoolStore, artifacts: Sequence[dict]
) -> list[dict[str, Any]]:
    """Do not occupy a formal immutable key with a transient missing attempt."""
    results: list[dict[str, Any]] = []
    for artifact in artifacts:
        validate_pool_artifact(artifact)
        pool_id = str(artifact["pool_id"])
        if (pool_id == "a_share_research_recommendation_pool"
                and artifact.get("source_role") == "EXPECTED_MISSING"
                and any(str(reason).startswith("A_RESEARCH_CACHE_REJECTED:")
                        for reason in artifact.get("cannot_confirm", []))):
            results.append({"trade_date": str(artifact["trade_date"]), "pool_id": pool_id,
                "status": "DEFERRED", "reason_code": "INPUT_CACHE_REJECTED",
                "source_role": "EXPECTED_MISSING", "artifact_written": False,
                "cannot_confirm": list(artifact["cannot_confirm"]),
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False})
            continue
        if pool_id in _FORMAL_IMMUTABLE_POOLS and artifact.get("source_role") == "EXPECTED_MISSING":
            if not _is_exact_expected_missing_placeholder(
                artifact, trade_date=str(artifact["trade_date"]), pool_id=pool_id,
            ):
                raise ValueError("INVALID_FORMAL_MISSING_PLACEHOLDER")
            results.append({
                "trade_date": str(artifact["trade_date"]), "pool_id": pool_id,
                "status": "DEFERRED", "reason_code": "FORMAL_INPUT_NOT_READY",
                "source_role": "EXPECTED_MISSING", "artifact_written": False,
                "cannot_confirm": list(artifact["cannot_confirm"]),
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            })
            continue
        try:
            try:
                results.append(store.materialize(artifact))
            except ValueError as error:
                if str(error) != "conflicting preselection-pool materialization":
                    raise
                expected_role = _AUTO_RECOVERABLE_OPTIONAL_POOLS.get(pool_id)
                if expected_role is None or artifact.get("source_role") != expected_role:
                    raise
                snapshot = store.read_pool_snapshot(str(artifact["trade_date"]), pool_id)
                if snapshot["artifact"].get("source_role") != "EXPECTED_MISSING":
                    raise
                results.append(store.recover_expected_missing(
                    artifact, expected_old_sha256=str(snapshot["artifact_sha256"]),
                ))
        except ValueError as error:
            if str(error) != "conflicting preselection-pool materialization":
                raise
            results.append({
                "trade_date": str(artifact["trade_date"]), "pool_id": pool_id,
                "status": "REJECTED", "reason_code": "IMMUTABLE_POOL_CONFLICT",
                "artifact_written": False, "detail": str(error),
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            })
    if any(result.get("status") == "REJECTED" for result in results):
        raise ScheduledPoolPublicationError(results)
    return results


def main(argv: Sequence[str] | None = None, *, pool_reader=None, hk_pool_reader=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--signal-date", required=True)
    parser.add_argument("--hk-target-date")
    parser.add_argument("--hk-signal-date")
    parser.add_argument("--hk-eligibility-source-date")
    # The selector is an A-share research-preview fallback only.  HK 0.2
    # materialization has its own exact-date source and must not be gated by
    # this optional A-share input.
    parser.add_argument("--selector", type=Path, default=None)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--shared-data-root", type=Path, required=True)
    parser.add_argument("--shared-package-root", type=Path, required=True)
    parser.add_argument(
        "--reuse-formal-pools",
        action="store_true",
        help="read and reuse the already verified target-date A/HK formal pair",
    )
    parser.add_argument("--reuse-formal-pool", action="append", default=[], choices=tuple(_FORMAL_POOL_READY_STATUSES))
    parser.add_argument("--quarantine-formal-pool", action="append", default=[], choices=tuple(_FORMAL_POOL_READY_STATUSES))
    args = parser.parse_args(argv)
    day = args.input_root / args.trade_date
    inputs = tuple(path for path in day.glob("*") if path.is_file()) if day.is_dir() else ()
    before = {path: path.read_bytes() for path in inputs}
    requested_reuse = (list(_FORMAL_POOL_READY_STATUSES) if args.reuse_formal_pools else args.reuse_formal_pool)
    reuse_formal_pools = {}
    for pool_id in requested_reuse:
        reuse_formal_pools[pool_id] = _verified_cached_formal_pool(
            PreselectionPoolStore(args.data_root), pool_id, args.trade_date,
            args.shared_data_root, args.shared_package_root)
    artifacts = build_scheduled_artifacts(
        trade_date=args.trade_date,
        signal_date=args.signal_date,
        selector=args.selector,
        input_root=args.input_root,
        shared_data_root=args.shared_data_root,
        shared_package_root=args.shared_package_root,
        data_root=args.data_root,
        pool_reader=pool_reader,
        hk_pool_reader=hk_pool_reader,
        hk_target_date=args.hk_target_date,
        hk_signal_date=args.hk_signal_date,
        hk_eligibility_source_date=args.hk_eligibility_source_date,
        reuse_formal_pools=reuse_formal_pools,
        quarantine_formal_pools=args.quarantine_formal_pool,
    )
    results = publish_scheduled_artifacts(
        PreselectionPoolStore(args.data_root), artifacts
    )
    if any(path.read_bytes() != content for path, content in before.items()):
        raise RuntimeError("read-only scheduled preselection input changed")
    formal_pool_gate = _formal_pool_gate(artifacts)
    failed = formal_pool_gate["research_ready"] is not True
    print(json.dumps({
        "trade_date": args.trade_date,
        "status": "FAILED" if failed else formal_pool_gate["status"],
        "failure_class": "UPSTREAM_NOT_READY" if failed else None,
        "formal_pool_gate": formal_pool_gate,
        "artifacts": results,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }, ensure_ascii=False, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
