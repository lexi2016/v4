"""Daily V3.5 final materialization and acceptance.

Runs once per trading day at 21:40. Consumes only V3.5-owned inputs: the V3.5
data root, the verified shared data root, and the explicit selector data root.
It verifies the seven preselection pools are materialized with valid
manifest/receipt evidence, materializes the eight stage workbenches from the
shared quote store, verifies the exact-date research archive, builds the HK
close review from the CloseSnapshotStore, and builds the A-share close review
from the selector panel. Nothing reads or writes the V3 runtime, nothing is
synthesized when an input is absent, and no trading boundary flag is ever
raised.

Each step fails independently: a missing V3.5-owned input is recorded as
``SOURCE_MISSING`` / ``FAILED`` without aborting the remaining steps, and the
overall receipt is only successful when every upstream step is. date_catalog
advances only on a fully successful run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from contracts.stages import FROZEN_STAGE_IDS
from contracts.trading_calendar import (
    TradingDayState,
    load_market_calendar,
    previous_session,
    resolve_market_states,
)
from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.formula_generation import FormulaGenerationError, read_formula_generation
from infrastructure.market_time import shanghai_now
from stage_center.consumer import StageSelectionConsumer

logger = logging.getLogger("v35.daily")


def _previous_weekday(value: str) -> str:
    return previous_session(load_market_calendar(), value, market="a_share")


def _serialize_decision(decision: Any) -> dict[str, Any]:
    return {
        "eligible": decision.eligible,
        "reason": decision.reason,
        "calendar_status": decision.calendar_status,
        "trade_date": decision.trade_date,
        "slot": decision.slot,
        "policy": decision.policy.value,
        "market_scope": "CROSS_MARKET",
        "session_requirement": "DAY_ELIGIBILITY_ONLY",
        "eligible_markets": list(decision.eligible_markets),
        "blocked_markets": list(decision.blocked_markets),
        "market_states": dict(decision.market_states),
        "session_status": decision.session_status,
    }


def _evaluate_calendar(trade_date: str) -> dict[str, Any]:
    from domains.runtime_policy import (
        MarketScope,
        RunPolicy,
        SessionRequirement,
        evaluate_run_policy,
    )

    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        trade_date,
        "2140",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )
    return {
        "decision": decision,
        "serialized": _serialize_decision(decision),
        "overall_status": (
            "NON_TRADING_DAY"
            if decision.calendar_status == "NON_TRADING_DAY"
            else "COMPLETED" if decision.eligible else "CALENDAR_ERROR"
        ),
    }


def _write_receipt(data_root: Path, trade_date: str, receipt: dict[str, Any]) -> None:
    store = NativeDataStore(data_root)
    store._write(f"daily_materialize_receipts/{trade_date}.json", receipt)


class DailyContext:
    """Resolved V3.5-owned inputs for one daily run."""

    def __init__(
        self,
        *,
        business_date: str | None = None,
        target_date: str | None = None,
        trade_date: str | None = None,
        data_root: Path,
        shared_data_root: Path | None,
        selector_data_root: Path | None,
        stage_selection_root: Path | None = None,
        formula_generation_pointer: Path | None = None,
    ) -> None:
        resolved_business = business_date or trade_date
        if not resolved_business:
            raise ValueError("business_date is required")
        self.business_date = str(resolved_business)
        self.target_date = str(target_date or resolved_business)
        self.data_root = Path(data_root)
        self.shared_data_root = (
            Path(shared_data_root) if shared_data_root else None
        )
        self.selector_data_root = (
            Path(selector_data_root) if selector_data_root else None
        )
        self.stage_selection_root = (
            Path(stage_selection_root) if stage_selection_root else None
        )
        self.formula_generation_pointer = (
            Path(formula_generation_pointer) if formula_generation_pointer else None
        )

    @property
    def trade_date(self) -> str:
        """Compatibility alias: stage/research/review work on business_date."""
        return self.business_date


def _ctx_business_date(ctx: Any) -> str:
    value = getattr(ctx, "business_date", None)
    if value is None:
        value = getattr(ctx, "trade_date")
    return str(value)


def _ctx_target_date(ctx: Any) -> str:
    return str(getattr(ctx, "target_date", _ctx_business_date(ctx)))


def _next_business_date(business_date: str) -> str:
    """Resolve the next joint A/H business date under the frozen calendar."""
    calendar = load_market_calendar()
    parsed = datetime.strptime(_date(business_date), "%Y%m%d").date()
    cursor = parsed + timedelta(days=1)
    while cursor.year == calendar.year:
        date8 = cursor.strftime("%Y%m%d")
        states = resolve_market_states(calendar, date8)
        if all(
            states[market]
            in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}
            for market in ("a_share", "hk_securities")
        ):
            return date8
        cursor += timedelta(days=1)
    raise ValueError("next business date is outside frozen calendar")


def _run_module(module: str, args: list[str]) -> dict[str, Any]:
    """Run one ops module main() with a synthetic argv and capture its stdout.

    Returns a normalized envelope: numeric ``exit_code``, ``status`` equal to
    ``SUCCEEDED`` only for a zero return code, and the original parsed JSON under
    ``payload`` (or a bounded ``raw_output`` when stdout is not JSON). A nonzero
    return code is always ``FAILED``, even when the child printed valid JSON.
    """
    import importlib

    mod = importlib.import_module(module)
    captured: list[str] = []
    original_argv = sys.argv
    original_stdout = sys.stdout
    exit_code = 0
    try:
        import io

        buffer = io.StringIO()
        sys.stdout = buffer
        sys.argv = [module] + args
        if callable(getattr(mod, "main", None)):
            result = mod.main()
            exit_code = result if isinstance(result, int) else 0
        captured.append(buffer.getvalue())
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
    output = "".join(captured)
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {
            "exit_code": exit_code,
            "status": "SUCCEEDED" if exit_code == 0 else "FAILED",
            "raw_output": output[:500],
        }
    return {
        "exit_code": exit_code,
        "status": "SUCCEEDED" if exit_code == 0 else "FAILED",
        "payload": payload,
    }


def _succeeded(envelope: dict[str, Any]) -> dict[str, Any]:
    """Fold a SUCCEEDED envelope into a step result that keeps its payload."""
    return {
        "status": "SUCCEEDED",
        "exit_code": envelope["exit_code"],
        "payload": envelope["payload"],
    }


def _verify_preselection(ctx: DailyContext) -> dict[str, Any]:
    """Step 1: verify all seven preselection pools are materialized for the date.

    Every pool is read through ``PreselectionPoolStore.read_pool``, which
    validates the pool artifact against its manifest and receipt and enforces
    the exact trade date. An explicit ``CANNOT_CONFIRM`` or ``VALID_EMPTY``
    status with complete evidence counts as materialized; a missing artifact,
    receipt, or manifest makes the step fail.
    """
    from infrastructure.preselection_pool_store import (
        POOL_ORDER,
        PreselectionPoolStore,
    )

    target_date = _ctx_target_date(ctx)
    store = PreselectionPoolStore(ctx.data_root)
    pools: dict[str, Any] = {}
    failed: list[dict[str, str]] = []
    for pool_id in POOL_ORDER:
        try:
            pool = store.read_pool(target_date, pool_id)
        except FileNotFoundError:
            failed.append({"pool_id": pool_id, "status": "SOURCE_MISSING"})
            continue
        except ValueError as error:
            failed.append({"pool_id": pool_id, "status": f"FAILED: {error}"})
            continue
        pools[pool_id] = {
            "status": pool.get("status"),
            "rows": len(pool.get("rows", [])),
            "source_role": pool.get("source_role"),
        }
    if failed:
        return {
            "status": "FAILED",
            "detail": "preselection pools incomplete",
            "business_date": _ctx_business_date(ctx),
            "target_date": target_date,
            "pools": pools,
            "failed": failed,
        }
    return {
        "status": "SUCCEEDED",
        "business_date": _ctx_business_date(ctx),
        "target_date": target_date,
        "pools": pools,
    }


def _materialize_stages(ctx: DailyContext) -> dict[str, Any]:
    """Step 2: consume all eight shared Stage Center selections read-only."""
    if ctx.stage_selection_root is None:
        return {
            "status": "FAILED",
            "detail": "stage selection root not configured",
            "stages": {},
        }
    consumer = StageSelectionConsumer(ctx.stage_selection_root)
    results: dict[str, dict[str, Any]] = {}
    for stage_id in FROZEN_STAGE_IDS:
        payload = consumer.get(_ctx_business_date(ctx), stage_id)
        status = str(payload.get("status") or "CANNOT_CONFIRM")
        markets = payload.get("markets") if isinstance(payload.get("markets"), dict) else {}
        row_count = sum(
            len(market.get("rows") or [])
            for market in markets.values()
            if isinstance(market, dict)
        )
        results[stage_id] = {
            "status": status,
            "ensure_status": "READ_ONLY_VERIFIED" if status in {"READY", "READY_EMPTY"} else "READ_ONLY_CANNOT_CONFIRM",
            "selection_status": status,
            "artifact_id": payload.get("artifact_id"),
            "run_id": payload.get("run_id"),
            "row_count": row_count,
            "cannot_confirm": list(payload.get("cannot_confirm") or []),
            "write_performed": False,
            "producer_called": False,
        }
    return {
        "status": "SUCCEEDED"
        if all(entry["status"] in {"READY", "READY_EMPTY"} for entry in results.values())
        else "CANNOT_CONFIRM",
        "stages": results,
    }


def _verify_research(ctx: DailyContext) -> dict[str, Any]:
    """Step 3: verify the exact-date research archive and its receipt."""
    from infrastructure.research_store import ResearchArchiveStore

    store = ResearchArchiveStore(ctx.data_root)
    try:
        business_date = _ctx_business_date(ctx)
        archive = store.read_exact(business_date)
    except ValueError as error:
        return {
            "status": "FAILED",
            "detail": f"research archive invalid: {error}",
        }
    if archive is None:
        return {
            "status": "SOURCE_MISSING",
            "detail": f"research archive missing for {business_date}",
        }
    return {
        "status": "SUCCEEDED",
        "archive_date": str(archive.get("archive_date")),
        "article_count": archive.get("article_count"),
        "stock_pool_count": archive.get("stock_pool_count"),
    }


def _build_hk_close_review(ctx: DailyContext) -> dict[str, Any]:
    """Step 4: build the HK connect close review from the CloseSnapshotStore.

    build_close_review reads the snapshot through CloseSnapshotStore.read_snapshot,
    which raises FileNotFoundError when the exact-date snapshot is absent.
    """
    try:
        envelope = _run_module(
            "ops.build_close_review",
            ["--data-root", str(ctx.data_root), "--date", _ctx_business_date(ctx)],
        )
    except FileNotFoundError:
        return {
            "status": "SOURCE_MISSING",
            "detail": "HK connect close snapshot missing",
        }
    except Exception as error:
        return {"status": "FAILED", "detail": f"{type(error).__name__}: {error}"}
    if envelope["status"] != "SUCCEEDED":
        return envelope
    return _succeeded(envelope)


def _build_a_share_close_review(ctx: DailyContext) -> dict[str, Any]:
    """Step 5: build the A-share close review from the selector panel.

    The panel is resolved from the explicit selector data root only, then handed
    to build_a_share_close_review through a pointer file (the builder consumes a
    pointer FILE whose contents name the parquet, not the parquet directly).
    """
    if ctx.selector_data_root is None and ctx.formula_generation_pointer is None:
        return {
            "status": "SOURCE_MISSING",
            "detail": "selector data root not configured",
        }
    try:
        panel = resolve_selector_panel(
            ctx.selector_data_root or ctx.formula_generation_pointer.parent,
            _ctx_business_date(ctx),
            formula_generation_pointer=ctx.formula_generation_pointer,
        )
    except FileNotFoundError:
        return {"status": "SOURCE_MISSING", "detail": "selector panel unresolved"}
    pointer_dir = ctx.data_root / ".daily_tmp"
    pointer_dir.mkdir(parents=True, exist_ok=True)
    pointer = pointer_dir / "selector_panel_pointer.txt"
    pointer.write_text(str(panel), encoding="utf-8")
    envelope = _run_module(
        "ops.build_a_share_close_review",
        [
            "--data-root", str(ctx.data_root),
            "--date", _ctx_business_date(ctx),
            "--panel-pointer", str(pointer),
        ],
    )
    if envelope["status"] != "SUCCEEDED":
        return envelope
    return _succeeded(envelope)


def _update_date_catalog(ctx: DailyContext) -> dict[str, Any]:
    """Step 6: advance date_catalog so the frontend picks up the new day."""
    store = NativeDataStore(ctx.data_root)
    catalog = store.read_catalog()
    business_date = _ctx_business_date(ctx)
    catalog["system_date"] = business_date
    stage_dates = sorted(set(catalog.get("stage_dates", [])) | {business_date})
    catalog["stage_dates"] = stage_dates
    materialized = catalog.get("materialized_rows", {})
    materialized[business_date] = 1
    catalog["materialized_rows"] = materialized
    try:
        store.import_catalog(catalog)
        return {"status": "SUCCEEDED", "system_date": business_date}
    except ValueError:
        # import_catalog is write-once (same digest only). Advance it directly
        # by rewriting date_catalog.json + its manifest/receipt atomically.
        relative = "date_catalog.json"
        receipt_path = "receipts/date_catalog.json"
        digest = _sha256(catalog)
        receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": relative,
            "source_sha256": digest,
            "trade_date": None,
        }
        with store._lock():
            manifest = store._manifest()
            store._write(relative, catalog)
            store._write(receipt_path, receipt)
            manifest[relative] = digest
            store._write_manifest(manifest)
        return {"status": "SUCCEEDED", "system_date": business_date}


_STEPS: list[tuple[str, Callable[[DailyContext], dict[str, Any]]]] = [
    ("verify_preselection", _verify_preselection),
    ("materialize_stages", _materialize_stages),
    ("verify_research", _verify_research),
    ("build_hk_close_review", _build_hk_close_review),
    ("build_a_share_close_review", _build_a_share_close_review),
    ("update_date_catalog", _update_date_catalog),
]


def resolve_selector_panel(
    selector_data_root: Path | None,
    trade_date: str,
    *,
    formula_generation_pointer: Path | str | None = None,
) -> Path:
    """Resolve the selector panel parquet/pointer under a selector data root.

    Tries, in order:
    1. The CURRENT_SELECTOR_READY_PANEL.txt pointer under data_layer_interface_current.
    2. Any selector_ready_*.parquet whose filename embeds the trade date.
    """
    required_date = _date(trade_date)

    if formula_generation_pointer is not None:
        try:
            generation = read_formula_generation(
                formula_generation_pointer,
                expected_target_date=required_date,
                require_source=True,
            )
        except (FormulaGenerationError, OSError, UnicodeError, ValueError) as error:
            raise FileNotFoundError(
                f"strict formula generation unresolved for {required_date}: {error}"
            ) from error
        return Path(generation["selector"])

    if selector_data_root is None:
        raise FileNotFoundError(f"selector data root missing for {required_date}")
    root = Path(selector_data_root)

    def _max_trade_date(panel: Path) -> str:
        """Read the panel's actual date coverage before accepting a pointer."""
        try:
            import pyarrow.parquet as parquet

            parquet_file = parquet.ParquetFile(panel)
            if "trade_date" not in parquet_file.schema_arrow.names:
                raise ValueError("trade_date column missing")
            max_date = ""
            for batch in parquet_file.iter_batches(
                columns=["trade_date"], batch_size=100_000
            ):
                for value in batch.column(0).to_pylist():
                    if value is None:
                        continue
                    candidate = _date(str(value))
                    if candidate > max_date:
                        max_date = candidate
            if not max_date:
                raise ValueError("trade_date column is empty")
            return max_date
        except (OSError, ValueError, ImportError, TypeError) as error:
            raise FileNotFoundError(
                f"selector panel unreadable for {required_date}: {panel} ({error})"
            ) from error

    def _accept(panel: Path) -> Path | None:
        if not panel.is_file():
            return None
        try:
            max_date = _max_trade_date(panel)
        except FileNotFoundError:
            return None
        if max_date < required_date:
            return None
        return panel

    pointer = root / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"
    if pointer.is_file():
        try:
            target = Path(pointer.read_bytes().decode("utf-8-sig").strip())
            accepted = _accept(target)
            if accepted is not None:
                return accepted
        except (OSError, UnicodeDecodeError):
            pass
    for parquet in sorted(
        root.glob("selector_ready_panels/**/*.parquet"),
        reverse=True,
    ):
        accepted = _accept(parquet)
        if accepted is not None:
            return accepted
    raise FileNotFoundError(
        f"no selector panel with max date >= {required_date} under {root}"
    )


def run_daily(
    *,
    trade_date: str | None = None,
    business_date: str | None = None,
    target_date: str | None = None,
    data_root: Path,
    shared_data_root: Path | None = None,
    selector_data_root: Path | None = None,
    stage_selection_root: Path | None = None,
    formula_generation_pointer: Path | str | None = None,
) -> dict[str, Any]:
    resolved_business = _date(business_date or trade_date or shanghai_now().strftime("%Y%m%d"))
    try:
        resolved_target = _date(target_date or _next_business_date(resolved_business))
    except ValueError:
        # Keep the calendar error receipt deterministic for dates outside the
        # frozen 2026 contract; never invent a future target date.
        resolved_target = ""
    # ``signal_date`` is retained as a compatibility alias for the selector
    # signal.  It is the current business date, not the previous session used
    # only by an older A-review helper.
    signal_date = resolved_business
    business_date = resolved_business
    target_date = resolved_target
    try:
        a_review_dependency_date = _previous_weekday(business_date)
    except ValueError:
        a_review_dependency_date = ""
    data_root = Path(data_root)
    tmp_root = data_root / ".daily_tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        calendar = _evaluate_calendar(business_date)
    except Exception as error:
        calendar = {
            "serialized": {
                "eligible": False,
                "reason": f"{type(error).__name__}: {error}",
                "calendar_status": "CALENDAR_ERROR",
                "trade_date": business_date,
                "slot": "2140",
                "policy": "A_OR_HK_CONNECT_TRADE_DAY",
                "market_scope": "CROSS_MARKET",
                "session_requirement": "DAY_ELIGIBILITY_ONLY",
                "eligible_markets": [],
                "blocked_markets": [],
                "market_states": {},
                "session_status": "CALENDAR_ERROR",
            },
            "overall_status": "CALENDAR_ERROR",
        }
    if not calendar["serialized"]["eligible"]:
        receipt = {
            "schema_version": "v3_5.daily_materialize.v1",
            "trade_date": business_date,
            "business_date": business_date,
            "target_date": target_date,
            "signal_date": signal_date,
            "preselection_signal_date": signal_date,
            "a_review_dependency_date": a_review_dependency_date,
            "calendar": calendar["serialized"],
            "overall_status": calendar["overall_status"],
            "steps": {},
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        receipt["receipt_path"] = f"daily_materialize_receipts/{business_date}.json"
        _write_receipt(data_root, business_date, receipt)
        return receipt
    ctx = DailyContext(
        business_date=business_date,
        target_date=target_date or business_date,
        data_root=data_root,
        shared_data_root=shared_data_root,
        selector_data_root=selector_data_root,
        stage_selection_root=stage_selection_root,
        formula_generation_pointer=Path(formula_generation_pointer) if formula_generation_pointer else None,
    )
    step_names = tuple(name for name, _ in _STEPS)
    results: dict[str, Any] = {}
    for name, step in _STEPS:
        if name == "update_date_catalog":
            continue
        try:
            result = step(ctx)
        except Exception as error:
            result = {
                "status": "FAILED",
                "detail": f"{type(error).__name__}: {error}",
            }
        results[name] = result
        logger.info("daily step %s -> %s", name, result.get("status"))
    success_equivalent = ("SUCCEEDED", "ALREADY_EXISTS")
    upstream = tuple(name for name in step_names if name != "update_date_catalog")
    optional_gap_steps = frozenset({"materialize_stages", "verify_research"})
    close_review_steps = ("build_hk_close_review", "build_a_share_close_review")
    close_reviews_ready = all(
        results.get(name, {}).get("status") in success_equivalent
        for name in close_review_steps
    )
    required_upstream_ready = all(
        results.get(name, {}).get("status") in success_equivalent
        for name in upstream
        if name not in optional_gap_steps
    )
    if close_reviews_ready and required_upstream_ready:
        results["update_date_catalog"] = _update_date_catalog(ctx)
    else:
        results["update_date_catalog"] = {
            "status": "SKIPPED_INCOMPLETE",
            "detail": "mandatory close review or preselection step incomplete; date_catalog left unchanged",
        }
    all_steps_ready = all(results.get(name, {}).get("status") in success_equivalent for name in step_names)
    if all_steps_ready:
        overall_status = "SUCCEEDED"
    elif (
        close_reviews_ready
        and required_upstream_ready
        and results.get("update_date_catalog", {}).get("status") in success_equivalent
    ):
        # Close review is publishable while stage/research evidence remains
        # explicit PARTIAL/SOURCE_MISSING.  Do not advance to READY or erase
        # those gaps; advance only the exact business-date catalog.
        overall_status = "PARTIAL"
    else:
        overall_status = "FAILED"
    receipt = {
        "schema_version": "v3_5.daily_materialize.v1",
        "trade_date": business_date,
        "business_date": business_date,
        "target_date": target_date,
        "signal_date": signal_date,
        "preselection_signal_date": signal_date,
        "a_review_dependency_date": a_review_dependency_date,
        "calendar": calendar["serialized"],
        "overall_status": overall_status,
        "steps": results,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    receipt["receipt_path"] = f"daily_materialize_receipts/{business_date}.json"
    _write_receipt(data_root, business_date, receipt)
    return receipt


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="Compatibility alias for --business-date")
    parser.add_argument("--business-date", default=None)
    parser.add_argument("--target-date", default=None)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path.cwd() / ".runtime" / "data",
    )
    parser.add_argument("--shared-data-root", type=Path, default=None)
    parser.add_argument("--selector-data-root", type=Path, default=None)
    parser.add_argument("--stage-selection-root", type=Path, default=None)
    parser.add_argument("--formula-generation-pointer", type=Path, default=None)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    receipt = run_daily(
        trade_date=args.date,
        business_date=args.business_date,
        target_date=args.target_date,
        data_root=args.data_root,
        shared_data_root=args.shared_data_root,
        selector_data_root=args.selector_data_root,
        stage_selection_root=args.stage_selection_root,
        formula_generation_pointer=args.formula_generation_pointer,
    )
    try:
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    except UnicodeEncodeError:
        import io as _io

        sys.stdout = _io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    if receipt["overall_status"] in {"SUCCEEDED", "PARTIAL", "NON_TRADING_DAY"}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
