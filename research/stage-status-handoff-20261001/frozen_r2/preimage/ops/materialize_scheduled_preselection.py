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
    PreselectionPoolStore, validate_pool_artifact, _is_exact_expected_missing_placeholder,
)
from infrastructure.baimao_preselection_pool_source import load_baimao_preselection_pool
from v4_migration.write_authority_reference import (
    WriteAuthorityResolutionError,
    reject_cli_authority_declaration,
)


DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "data"


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
    selector: Path | None,
    input_root: Path,
    shared_data_root: Path,
    shared_package_root: Path,
    data_root: Path,
    pool_reader=None,
    hk_pool_reader=None,
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
    try:
        hk_0_2 = build_shared_hk_0_2_pool(
            shared_data_root,
            trade_date=trade_date,
            signal_date=signal_date,
            shared_package_root=shared_package_root,
            reader=hk_pool_reader,
        )
    except Exception as error:
        if not _is_expected_verified_input_error(error):
            raise
        reason_code = _input_error_code("HK_0_2", error)
        hk_0_2 = _missing(
            trade_date,
            pool_id="hkconnect_d1_top100",
            display_name="港股通 0.2 D-1 Top100",
            market="HK",
            reason=f"{reason_code}:{error}",
        )

    return [
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
        hk_0_2,
        _optional_artifact(
            lambda: build_wechat_pool(wechat_manifest, wechat_rows, trade_date)
            if wechat_manifest.is_file() and wechat_rows.is_file() else _missing(
                trade_date, pool_id="wechat_public_account_v3_preselect", display_name="公众号股票池",
                market="A", reason="WECHAT_V3_PRESELECT_UPSTREAM_MISSING"),
            trade_date=trade_date, pool_id="wechat_public_account_v3_preselect", display_name="公众号股票池",
            reason_prefix="WECHAT_V3_PRESELECT", source_paths=(wechat_manifest, wechat_rows),
        ),
    ]


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--signal-date", required=True)
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
    args = parser.parse_args(argv)
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
        selector=args.selector,
        input_root=args.input_root,
        shared_data_root=args.shared_data_root,
        shared_package_root=args.shared_package_root,
        data_root=args.data_root,
        pool_reader=pool_reader,
        hk_pool_reader=hk_pool_reader,
    )
    if any(path.read_bytes() != content for path, content in before.items()):
        raise RuntimeError("read-only scheduled preselection input changed")
    exit_code = 0
    try:
        results = publish_scheduled_artifacts(PreselectionPoolStore(args.data_root), artifacts)
    except ScheduledPoolPublicationError as error:
        results = error.results
        exit_code = 1
    print(json.dumps({
        "trade_date": args.trade_date,
        "artifacts": results,
        "status": "REJECTED" if exit_code else (
            "PARTIAL" if any(result.get("status") == "DEFERRED" for result in results) else "COMPLETED"
        ),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
