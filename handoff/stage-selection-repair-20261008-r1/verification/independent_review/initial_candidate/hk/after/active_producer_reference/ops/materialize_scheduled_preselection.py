"""Materialize the next-trading-day preselection contract for the scheduler.

The A-share D-1 selector pool is produced from the V3.5 selector-ready panel
using the frozen V3 scoring/sort function.  Optional graph upstreams are read
only when their exact target-date files exist; an absent upstream becomes an
explicit zero-row ``CANNOT_CONFIRM`` artifact and receipt, never a fabricated
stock row.  No V3 runtime path or final-output import is used.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

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
from infrastructure.preselection_pool_store import PreselectionPoolStore
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
    for pool_id, ready_statuses in _FORMAL_POOL_READY_STATUSES.items():
        artifact = by_id.get(pool_id)
        status = str(artifact.get("status") or "") if artifact else "MISSING"
        rows = artifact.get("rows") if artifact else None
        row_count = len(rows) if isinstance(rows, list) else 0
        ready = status in ready_statuses and row_count > 0
        required[pool_id] = {
            "status": status,
            "row_count": row_count,
            "ready": ready,
        }
        if not ready:
            missing_or_invalid.append(pool_id)
    return {
        "status": "READY" if not missing_or_invalid else "FAILED",
        "required": required,
        "missing_or_invalid": missing_or_invalid,
    }


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


def _input_error_code(prefix: str, error: Exception) -> str:
    """Map a fail-closed verified-input error to a truthful lane reason."""
    missing_markers = ("missing", "no latest", "not found", "not exist")
    if isinstance(error, FileNotFoundError) or any(
        marker in str(error).lower() for marker in missing_markers
    ):
        return f"{prefix}_EXACT_INPUT_MISSING"
    return f"{prefix}_EXACT_INPUT_CONTRACT_INVALID"


def _require_hk_date_binding(target_date, signal_date, eligibility_source_date) -> None:
    """Require the original caller's HK dates; never infer them from A dates."""
    dates = (target_date, signal_date, eligibility_source_date)
    if any(value in (None, "") for value in dates):
        raise ValueError("HK explicit target/price/eligibility date binding missing")
    try:
        for value in dates:
            if not isinstance(value, str) or re.fullmatch(r"\d{8}", value) is None:
                raise ValueError("date must be YYYYMMDD")
            datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("HK date binding format invalid") from error
    if not eligibility_source_date <= signal_date < target_date:
        raise ValueError("HK date binding must satisfy eligibility <= price < target")
    try:
        from contracts.trading_calendar import (
            TradingDayState, load_market_calendar, previous_session, resolve_market_states,
        )

        calendar = load_market_calendar()
        if resolve_market_states(calendar, target_date)["hk_securities"] not in {
            TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM,
        }:
            raise ValueError("HK target is not a confirmed securities session")
        expected = (
            previous_session(calendar, target_date, market="hk_securities"),
            previous_session(calendar, target_date, market="hk_connect"),
        )
    except (ImportError, OSError, ValueError) as error:
        raise ValueError(f"HK date binding calendar CANNOT_CONFIRM: {error}") from error
    if (signal_date, eligibility_source_date) != expected:
        raise ValueError("HK date binding differs from securities/Connect calendar sessions")


def build_scheduled_artifacts(
    *,
    trade_date: str,
    signal_date: str,
    hk_target_date: str | None = None,
    hk_signal_date: str | None = None,
    hk_eligibility_source_date: str | None = None,
    selector: Path | None,
    input_root: Path,
    shared_data_root: Path,
    shared_package_root: Path,
    data_root: Path,
    pool_reader=None,
    hk_pool_reader=None,
    reuse_formal_pools: Mapping[str, Mapping] | None = None,
) -> list[dict]:
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
        research_artifact = build_hourly_research_pool(
            data_root,
            trade_date=trade_date,
        )
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

    if "a_d1_premarket_pool" in reused_formal:
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
    hk_artifact_date = trade_date
    try:
        _require_hk_date_binding(hk_target_date, hk_signal_date, hk_eligibility_source_date)
        hk_artifact_date = hk_target_date
        hk_0_2 = build_shared_hk_0_2_pool(
            shared_data_root,
            trade_date=hk_target_date,
            signal_date=hk_signal_date,
            eligibility_source_date=hk_eligibility_source_date,
            shared_package_root=shared_package_root,
            reader=hk_pool_reader,
        )
    except Exception as error:
        if not _is_expected_verified_input_error(error):
            raise
        reason_code = _input_error_code("HK_0_2", error)
        hk_0_2 = _missing(
            hk_artifact_date,
            pool_id="hkconnect_d1_top100",
            display_name="港股通 0.2 D-1 Top100",
            market="HK",
            reason=f"{reason_code}:{error}",
        )
    if "hkconnect_d1_top100" in reused_formal:
        # Reuse cannot bypass the original shared reader. Comparing the full
        # projection also rejects old rows carrying a newer envelope or SHA.
        reused_hk = dict(reused_formal["hkconnect_d1_top100"])
        if reused_hk != hk_0_2:
            raise ValueError("reused HK pool does not match verified exact-source projection")
        hk_0_2 = reused_hk

    return [
        a_premarket,
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
        ),
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
        ),
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


def main(argv: Sequence[str] | None = None, *, pool_reader=None, hk_pool_reader=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--signal-date", required=True)
    parser.add_argument(
        "--hk-target-date",
        help="explicit HK securities target date; required for HK readiness",
    )
    parser.add_argument(
        "--hk-signal-date",
        help="explicit HK securities price session; required for HK readiness",
    )
    parser.add_argument(
        "--hk-eligibility-source-date",
        help="explicit verified HK Connect eligibility date; required for HK readiness",
    )
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
    args = parser.parse_args(argv)
    day = args.input_root / args.trade_date
    inputs = tuple(path for path in day.glob("*") if path.is_file()) if day.is_dir() else ()
    before = {path: path.read_bytes() for path in inputs}
    reuse_formal_pools = None
    if args.reuse_formal_pools:
        formal_store = PreselectionPoolStore(args.data_root)
        reuse_formal_pools = {
            pool_id: formal_store.read_pool(
                (args.hk_target_date or args.trade_date) if pool_id == "hkconnect_d1_top100" else args.trade_date,
                pool_id,
            )
            for pool_id in ("a_d1_premarket_pool", "hkconnect_d1_top100")
        }
    artifacts = build_scheduled_artifacts(
        trade_date=args.trade_date,
        signal_date=args.signal_date,
        hk_target_date=args.hk_target_date,
        hk_signal_date=args.hk_signal_date,
        hk_eligibility_source_date=args.hk_eligibility_source_date,
        selector=args.selector,
        input_root=args.input_root,
        shared_data_root=args.shared_data_root,
        shared_package_root=args.shared_package_root,
        data_root=args.data_root,
        pool_reader=pool_reader,
        hk_pool_reader=hk_pool_reader,
        reuse_formal_pools=reuse_formal_pools,
    )
    results = materialize_preselection_date(
        PreselectionPoolStore(args.data_root), artifacts
    )
    if any(path.read_bytes() != content for path, content in before.items()):
        raise RuntimeError("read-only scheduled preselection input changed")
    formal_pool_gate = _formal_pool_gate(artifacts)
    failed = formal_pool_gate["status"] != "READY"
    print(json.dumps({
        "trade_date": args.trade_date,
        "status": "FAILED" if failed else "READY",
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
