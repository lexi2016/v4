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
from pathlib import Path
from typing import Callable, Sequence, Any

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
)
from infrastructure.preselection_pool_store import (
    HK_EXPECTED_MISSING_OLD_ARTIFACT_SHA256,
    HK_EXPECTED_MISSING_OLD_RECEIPT_SHA256,
    HK_EXPECTED_MISSING_SOURCE_SHA256,
    HK_EXPECTED_MISSING_SUCCESSOR_SHA256,
    PreselectionPoolStore, validate_pool_artifact, _is_exact_expected_missing_placeholder,
)
from infrastructure.baimao_preselection_pool_source import load_baimao_preselection_pool
from v4_migration.write_authority_reference import (
    WriteAuthorityResolutionError,
    reject_cli_authority_declaration,
)


DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "data"


def _hk_rows_match_exact_dates(
    rows: object, *, target_date: object, signal_date: object
) -> bool:
    """Keep the formal HK gate bound to the strict row-level D-1 contract."""
    expected_target = str(target_date or "")
    expected_signal = str(signal_date or "")
    if not expected_target or not expected_signal or not isinstance(rows, list):
        return False
    return all(
        isinstance(row, dict)
        and str(row.get("target_date") or row.get("trade_date") or "")
        == expected_target
        and str(row.get("signal_date") or "") == expected_signal
        for row in rows
    )


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


def _formal_pool_gate(
    artifacts: Sequence[dict],
    *,
    market_scope: str,
    publication_results: Sequence[dict] = (),
    hk_target_date: str | None = None,
    hk_signal_date: str | None = None,
) -> dict[str, Any]:
    required_by_scope = {
        "A_SHARE": ("a_d1_premarket_pool",),
        "HK_CONNECT": ("hkconnect_d1_top100",),
        "CROSS_MARKET": ("a_d1_premarket_pool", "hkconnect_d1_top100"),
    }
    scope = str(market_scope).upper()
    if scope not in required_by_scope:
        raise ValueError(f"unsupported preselection market scope: {market_scope}")
    by_id = {str(item.get("pool_id") or ""): item for item in artifacts}
    publication_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(artifacts):
        if index < len(publication_results):
            publication_by_id[str(item.get("pool_id") or "")] = publication_results[index]
    required: dict[str, dict[str, bool]] = {}
    for pool_id in required_by_scope[scope]:
        artifact = by_id.get(pool_id)
        rows = artifact.get("rows") if artifact else None
        row_count = len(rows) if isinstance(rows, list) else 0
        status = str(artifact.get("status") or "MISSING") if artifact else "MISSING"
        ready_statuses = (
            {"V192_CANDIDATE_READY"}
            if pool_id == "a_d1_premarket_pool"
            else {"STRICT_0_2_READY", "HK_0_2_TOP100_READY"}
        )
        ready = status in ready_statuses and row_count > 0
        if pool_id == "hkconnect_d1_top100":
            codes = [str(row.get("symbol") or row.get("code_norm") or "") for row in rows or []]
            expected_target = hk_target_date or (
                artifact.get("target_date") or artifact.get("trade_date")
                if artifact else None
            )
            expected_signal = hk_signal_date or (
                artifact.get("signal_date") if artifact else None
            )
            ready = (
                ready
                and row_count == 100
                and len(set(codes)) == 100
                and _hk_rows_match_exact_dates(
                    rows,
                    target_date=expected_target,
                    signal_date=expected_signal,
                )
            )
        publication = publication_by_id.get(pool_id)
        if publication and publication.get("status") in {"DEFERRED", "REJECTED"}:
            ready = False
        required[pool_id] = {"ready": ready}
    ready_count = sum(1 for item in required.values() if item["ready"])
    status = "FAILED" if ready_count == 0 else "PARTIAL" if ready_count < len(required) else "READY"
    return {
        "status": status,
        "required": required,
    }


def _hk_expected_missing_recovery_main(argv, *, hk_pool_reader=None) -> int:
    """Run only the pinned HK expected-missing compare-and-swap recovery."""
    parser = argparse.ArgumentParser(description="Pinned HK expected-missing recovery")
    parser.add_argument("--recover-hk-expected-missing", action="store_true", required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--signal-date", required=True)
    parser.add_argument("--eligibility-source-date", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--shared-data-root", type=Path, required=True)
    parser.add_argument("--eligibility-universe-root", type=Path, required=True)
    parser.add_argument("--shared-package-root", type=Path, required=True)
    parser.add_argument("--expected-old-artifact-sha256", required=True)
    parser.add_argument("--expected-old-receipt-sha256", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-successor-sha256", required=True)
    args = parser.parse_args(argv)
    if (args.trade_date, args.signal_date, args.eligibility_source_date) != (
        "20260930", "20260929", "20260929"
    ):
        parser.error("HK recovery is pinned to target 20260930 and source/eligibility 20260929")
    if (
        args.expected_old_artifact_sha256
        != HK_EXPECTED_MISSING_OLD_ARTIFACT_SHA256
        or args.expected_old_receipt_sha256
        != HK_EXPECTED_MISSING_OLD_RECEIPT_SHA256
    ):
        parser.error("HK recovery requires the pinned artifact and receipt CAS")
    if (
        args.expected_source_sha256 != HK_EXPECTED_MISSING_SOURCE_SHA256
        or args.expected_successor_sha256 != HK_EXPECTED_MISSING_SUCCESSOR_SHA256
    ):
        parser.error("HK recovery requires the pinned verified source and successor SHA")
    try:
        artifact = build_shared_hk_0_2_pool(
            args.shared_data_root,
            trade_date=args.trade_date,
            signal_date=args.signal_date,
            eligibility_source_date=args.eligibility_source_date,
            eligibility_universe_root=args.eligibility_universe_root,
            shared_package_root=args.shared_package_root,
            reader=hk_pool_reader,
        )
        store = PreselectionPoolStore(args.data_root)
        result = store.recover_hk_expected_missing(
            artifact,
            expected_old_sha256=args.expected_old_artifact_sha256,
            expected_old_receipt_sha256=args.expected_old_receipt_sha256,
            expected_source_sha256=args.expected_source_sha256,
            expected_successor_sha256=args.expected_successor_sha256,
        )
        snapshot = store.read_pool_snapshot(args.trade_date, "hkconnect_d1_top100")
        result.update({
            "status": snapshot["artifact"].get("status"),
            "row_count": len(snapshot["artifact"].get("rows") or []),
            "artifact_sha256": snapshot["artifact_sha256"],
            "receipt_raw_sha256": snapshot["receipt_raw_sha256"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error": f"{type(error).__name__}:{error}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _hk_expected_missing_rollback_main(argv) -> int:
    parser = argparse.ArgumentParser(description="Pinned HK expected-missing rollback")
    parser.add_argument("--rollback-hk-expected-missing", action="store_true", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--expected-replacement-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        store = PreselectionPoolStore(args.data_root)
        result = store.rollback_hk_expected_missing(
            expected_replacement_sha256=args.expected_replacement_sha256,
        )
        snapshot = store.read_pool_snapshot("20260930", "hkconnect_d1_top100")
        result.update({
            "status": snapshot["artifact"].get("status"),
            "receipt_raw_sha256": snapshot["receipt_raw_sha256"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error": f"{type(error).__name__}:{error}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


_EXPECTED_INPUT_VALUE_ERROR_PREFIXES = (
    "invalid upstream manifest:",
    "invalid D-1 fupan ",
    "D-1 fupan ",
    "invalid D-1 Stage7 ",
    "D-1 Stage7 ",
    "invalid WeChat upstream ",
    "WeChat upstream ",
    "shared_package_root is required for v1.9.2 verification",
    "shared_package_root is required for HK 0.2 verification",
    "shared v1.9.2 ",
    "shared HK 0.2 ",
)
_EXPECTED_HOURLY_INPUT_VALUE_ERRORS = frozenset({
    "hourly research manifest points to missing payload",
    "hourly research archive-date mismatch",
    "hourly research articles are invalid",
    "hourly research article is invalid",
    "hourly research article identity is invalid",
    "hourly research manifest or receipt mismatch",
    "hourly research slot directory is not a directory",
})


def _is_expected_verified_input_error(error: Exception) -> bool:
    """Recognize typed or enumerated source-contract failures; unknown ValueError is a bug."""
    error_type = type(error)
    if isinstance(error, (OSError, UnicodeError, csv.Error, json.JSONDecodeError)):
        return True
    if error_type.__name__ == "StoreError" and str(error_type.__module__).endswith(".store"):
        return True
    if error_type is not ValueError:
        return False
    message = str(error)
    return message in _EXPECTED_HOURLY_INPUT_VALUE_ERRORS or message.startswith(
        _EXPECTED_INPUT_VALUE_ERROR_PREFIXES
    )


def _input_error_code(prefix: str, error: Exception) -> str:
    """Map a fail-closed verified-input error to a truthful lane reason."""
    missing_markers = ("missing", "no latest", "not found", "not exist")
    if isinstance(error, FileNotFoundError) or any(
        marker in str(error).lower() for marker in missing_markers
    ):
        return f"{prefix}_EXACT_INPUT_MISSING"
    return f"{prefix}_EXACT_INPUT_CONTRACT_INVALID"


def _optional_artifact(
    builder: Callable[[], dict], *, trade_date: str, pool_id: str,
    display_name: str, reason_prefix: str, source_paths: Sequence[Path] = (),
) -> dict:
    """Quarantine expected input errors, not arbitrary programming failures."""
    def quarantine(error: Exception) -> dict:
        artifact = _missing(
            trade_date, pool_id=pool_id, display_name=display_name, market="A",
            reason=f"{reason_prefix}_INPUT_CONTRACT_INVALID:{type(error).__name__}:{error}",
        )
        # These are post-rejection observations, not evidence that bad rows passed.
        for path in source_paths:
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                observation = f"REJECTED_INPUT_OBSERVED_AFTER_ERROR:{path}:sha256={digest}"
            except OSError as read_error:
                observation = f"REJECTED_INPUT_UNREADABLE:{path}:{type(read_error).__name__}"
            artifact["cannot_confirm"].append(observation)
        return artifact

    try:
        artifact = builder()
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        if not _is_expected_verified_input_error(error):
            raise
        return quarantine(error)
    try:
        validate_pool_artifact(artifact)
    except ValueError as error:
        # This is the explicit output-contract validation boundary.
        return quarantine(error)
    return artifact


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
    market_scope: str = "CROSS_MARKET",
    pool_reader=None,
    hk_pool_reader=None,
) -> list[dict]:
    hk_target_date = hk_target_date or trade_date
    hk_signal_date = hk_signal_date or signal_date
    hk_eligibility_source_date = hk_eligibility_source_date or signal_date
    market_scope = str(market_scope).upper()
    if market_scope not in {"A_SHARE", "HK_CONNECT", "CROSS_MARKET"}:
        raise ValueError(f"unsupported preselection market scope: {market_scope}")

    def build_hk_pool() -> dict:
        try:
            return build_shared_hk_0_2_pool(
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
            return _missing(
                hk_target_date,
                pool_id="hkconnect_d1_top100",
                display_name="港股通 0.2 D-1 Top100",
                market="HK",
                reason=f"{reason_code}:{error}",
            )

    # A closed date does not read or publish any A-share sibling pool.
    if market_scope == "HK_CONNECT":
        return [build_hk_pool()]

    day = Path(input_root) / trade_date
    fupan = day / "fupan.csv"
    fupan_manifest = day / "fupan.manifest.json"
    stage7 = day / "stage7.csv"
    stage7_manifest = day / "stage7.manifest.json"
    research = day / "research_preview.json"
    baimao = day / "baimao.json"
    wechat_rows = day / "wechat_rows.csv"
    wechat_manifest = day / "wechat_manifest.json"

    def build_research() -> dict:
        try:
            return build_hourly_research_pool(
                data_root,
                trade_date=trade_date,
            )
        except FileNotFoundError:
            if research.is_file() and selector is not None:
                return build_research_preview_pool(
                    research, selector, trade_date
                )
            else:
                return _missing(
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

    research_artifact = _optional_artifact(
        build_research, trade_date=trade_date,
        pool_id="a_share_research_recommendation_pool", display_name="A股研报推荐股票池",
        reason_prefix="A_RESEARCH", source_paths=(research,) if research.is_file() else (),
    )

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
    hk_0_2 = build_hk_pool() if market_scope == "CROSS_MARKET" else None

    artifacts = [
        a_premarket,
        _optional_artifact(
            lambda: build_fupan_watchlist_pool(fupan, fupan_manifest, trade_date=trade_date, signal_date=signal_date)
            if fupan.is_file() and fupan_manifest.is_file() else _missing(
                trade_date, pool_id="a_d1_fupan_watchlist_pool", display_name="A股 D-1 复盘继续观察池",
                market="A", reason="A_D1_FUPAN_WATCHLIST_EVIDENCE_MISSING"),
            trade_date=trade_date, pool_id="a_d1_fupan_watchlist_pool", display_name="A股 D-1 复盘继续观察池",
            reason_prefix="A_D1_FUPAN", source_paths=(fupan_manifest, fupan),
        ),
        _optional_artifact(
            lambda: build_stage7_review_pool(stage7, stage7_manifest, trade_date=trade_date, signal_date=signal_date)
            if stage7.is_file() and stage7_manifest.is_file() else _missing(
                trade_date, pool_id="a_d1_stage7_fenshi_review_pool", display_name="A股 D-1 Stage7/分时复盘池",
                market="A", reason="A_D1_STAGE7_FENSHI_EVIDENCE_MISSING"),
            trade_date=trade_date, pool_id="a_d1_stage7_fenshi_review_pool", display_name="A股 D-1 Stage7/分时复盘池",
            reason_prefix="A_D1_STAGE7", source_paths=(stage7_manifest, stage7),
        ),
        research_artifact,
        _optional_artifact(
            lambda: build_baimao_pool(baimao, trade_date) if baimao.is_file()
            else load_baimao_preselection_pool(shared_data_root, shared_package_root, trade_date),
            trade_date=trade_date, pool_id="a_share_baimao_research_map", display_name="白毛卡点研究池",
            reason_prefix="A_BAIMAO", source_paths=(baimao,) if baimao.is_file() else (),
        ),
        _optional_artifact(
            lambda: build_wechat_pool(wechat_manifest, wechat_rows, trade_date)
            if wechat_manifest.is_file() and wechat_rows.is_file() else _missing(
                trade_date, pool_id="wechat_public_account_v3_preselect", display_name="公众号股票池",
                market="A", reason="WECHAT_V3_PRESELECT_UPSTREAM_MISSING"),
            trade_date=trade_date, pool_id="wechat_public_account_v3_preselect", display_name="公众号股票池",
            reason_prefix="WECHAT_V3_PRESELECT", source_paths=(wechat_manifest, wechat_rows),
        ),
    ]
    if hk_0_2 is not None:
        artifacts.insert(5, hk_0_2)
    return artifacts


_AUTO_RECOVERABLE_OPTIONAL_POOLS = {
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
    import sys
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    market_scope_explicit = any(
        item == "--market-scope" or item.startswith("--market-scope=")
        for item in effective_argv
    )
    if "--recover-hk-expected-missing" in effective_argv:
        return _hk_expected_missing_recovery_main(
            effective_argv, hk_pool_reader=hk_pool_reader
        )
    if "--rollback-hk-expected-missing" in effective_argv:
        return _hk_expected_missing_rollback_main(effective_argv)
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--signal-date", required=True)
    parser.add_argument(
        "--hk-target-date",
        default=None,
        help="HK securities target date; defaults to --trade-date for existing callers",
    )
    parser.add_argument(
        "--hk-signal-date",
        default=None,
        help="HK securities price session; defaults to --signal-date for existing callers",
    )
    parser.add_argument(
        "--hk-eligibility-source-date",
        default=None,
        help="verified HK Connect eligibility source date; defaults to --signal-date for existing callers",
    )
    parser.add_argument(
        "--market-scope",
        choices=("A_SHARE", "HK_CONNECT", "CROSS_MARKET"),
        default="CROSS_MARKET",
        help="materialize only the existing requested market lane(s)",
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
        "--write-authorization-ref",
        action="append",
        default=None,
        help="untrusted declaration; denied until a separately implemented owner trust provider exists",
    )
    args = parser.parse_args(effective_argv)
    try:
        reject_cli_authority_declaration(args.write_authorization_ref)
    except WriteAuthorityResolutionError as error:
        print(json.dumps({
            "status": "REJECTED",
            "reason": error.reason_code,
            "detail": str(error),
            "authorization_source": error.source,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }, ensure_ascii=False, sort_keys=True))
        return 3
    day = args.input_root / args.trade_date
    inputs = tuple(path for path in day.glob("*") if path.is_file()) if day.is_dir() else ()
    before = {path: path.read_bytes() for path in inputs}
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
        market_scope=args.market_scope,
        pool_reader=pool_reader,
        hk_pool_reader=hk_pool_reader,
    )
    if any(path.read_bytes() != content for path, content in before.items()):
        raise RuntimeError("read-only scheduled preselection input changed")
    publication_failed = False
    try:
        results = publish_scheduled_artifacts(PreselectionPoolStore(args.data_root), artifacts)
    except ScheduledPoolPublicationError as error:
        results = error.results
        publication_failed = True
    formal_pool_gate = _formal_pool_gate(
        artifacts,
        market_scope=args.market_scope,
        publication_results=results,
        hk_target_date=args.hk_target_date or args.trade_date,
        hk_signal_date=args.hk_signal_date or args.signal_date,
    )
    ready_count = sum(1 for value in formal_pool_gate["required"].values() if value["ready"])
    if market_scope_explicit:
        status = formal_pool_gate["status"]
        exit_code = 0 if ready_count else 1
    else:
        # Keep the existing no-scope publication contract for direct callers.
        # The scheduled executor now passes an explicit lane scope and uses
        # formal_pool_gate as its strict readiness receipt.
        exit_code = 1 if publication_failed else 0
        status = "REJECTED" if publication_failed else (
            "PARTIAL" if any(item.get("status") == "DEFERRED" for item in results) else "COMPLETED"
        )
    # The executor keeps only a bounded stdout receipt. Keep the machine gate
    # and per-pool publication outcome inside that bound so it can verify the
    # actual strict pools instead of guessing from the subprocess exit code.
    artifact_summaries = (
        [
            {
                key: item[key]
                for key in ("artifact_path", "receipt_path", "sha256")
                if key in item
            }
            for artifact, item in zip(artifacts, results)
            if str(artifact.get("pool_id") or "") in formal_pool_gate["required"]
        ]
        if market_scope_explicit
        else results
    )
    print(json.dumps({
        "trade_date": args.trade_date,
        "artifacts": artifact_summaries,
        "status": status,
        "formal_pool_gate": formal_pool_gate,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
