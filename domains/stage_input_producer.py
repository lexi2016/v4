"""Build verified V3.5 stage inputs from canonical pools and cutoff-safe quotes."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Protocol, Sequence

from contracts.stages import STAGE_DEFINITIONS, STAGE_MARKET_SCOPES
from infrastructure.data_store import NativeDataStore, _sha256
from infrastructure.preselection_pool_store import POOL_ORDER, PreselectionPoolStore
from infrastructure.stage_store import StageStore, validate_quote_batch


class ReadOnlyQuoteProvider(Protocol):
    def snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]: ...


class StageInputProducer:
    def __init__(
        self,
        data_store: NativeDataStore,
        stage_store: StageStore,
        quote_provider: ReadOnlyQuoteProvider,
    ) -> None:
        self.data_store = data_store
        self.stage_store = stage_store
        self.quote_provider = quote_provider

    def produce(
        self,
        trade_date: str,
        stage_id: str,
        *,
        replace: bool = False,
    ) -> dict[str, Any]:
        if stage_id not in STAGE_DEFINITIONS:
            raise ValueError("unknown stage_id")
        candidates, pool_status, pool_evidence, pool_gaps = self._stage_candidates(trade_date)
        candidates = self._deduplicate_candidates(
            [deepcopy(row) for row in candidates]
        )
        market_scope = STAGE_MARKET_SCOPES[stage_id]
        prefixes = tuple(f"{market}." for market in market_scope)
        symbols = sorted(
            {
                str(row.get("symbol") or "")
                for row in candidates
                if str(row.get("symbol") or "").startswith(prefixes)
            }
        )
        if not symbols:
            raise ValueError("canonical preselection pool has no supported symbols")
        definition = STAGE_DEFINITIONS[stage_id]
        cutoff_at = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T{definition['cutoff']}"
        quote_batch = self.quote_provider.snapshot(
            symbols,
            trade_date=trade_date,
            stage_id=stage_id,
            cutoff_at=cutoff_at,
        )
        if validate_quote_batch(quote_batch) != (trade_date, stage_id):
            raise ValueError("quote batch identity mismatch")
        self._validate_window(quote_batch["captured_at"], trade_date, definition["start"], definition["cutoff"])
        source = self.stage_store.import_source_snapshot(quote_batch)
        quotes = {
            str(row["symbol"]): row
            for row in quote_batch["rows"]
            if str(row.get("symbol") or "").startswith(prefixes)
        }
        a_rows, hk_rows = self._merge_candidates(candidates, quotes)
        quote_coverage = self._quote_coverage(candidates, quotes, prefixes)
        coverage_gaps = [
            f"{market}_STAGE_QUOTE_COVERAGE_INCOMPLETE:{counts['returned']}/{counts['requested']}"
            for market, counts in quote_coverage.items() if counts["missing"]
        ]
        quote_gaps = [str(item) for item in quote_batch.get("cannot_confirm") or []]
        a_quote_is_partial = any(
            item.startswith("PYTDX_0925_") for item in quote_gaps
        )
        hk_is_migrated_reference = (
            "HK_STAGE_ROWS_FROM_LOCAL_MIGRATED_REFERENCE" in quote_gaps
        )
        input_payload = {
            "schema_version": "v3_5.stage_input.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "cutoff_reached": True,
            "market_status": {
                "A": (
                    "READY"
                    if a_rows
                    and not quote_coverage["A"]["missing"]
                    and pool_status in {"INDEPENDENT_GRAPH_POOLS", "CANONICAL_COMPLETE"}
                    and not a_quote_is_partial
                    else "CANNOT_CONFIRM"
                ),
                "HK": (
                    "READY"
                    if hk_rows
                    and not quote_coverage["HK"]["missing"]
                    and pool_status in {"INDEPENDENT_GRAPH_POOLS", "CANONICAL_COMPLETE"}
                    and not hk_is_migrated_reference
                    else "CANNOT_CONFIRM"
                ),
            },
            "rows": {"A": a_rows, "HK": hk_rows},
            "source_summary": {
                "quote_source": str(quote_batch.get("source") or ""),
                "requested_A": sum(symbol.startswith("A.") for symbol in symbols),
                "requested_HK": sum(symbol.startswith("HK.") for symbol in symbols),
                "pool_status": pool_status,
                "quote_coverage": quote_coverage,
                "cannot_confirm": [*pool_gaps, *quote_gaps, *coverage_gaps],
            },
            "source_evidence": [*pool_evidence, {"path": source["payload_path"], "sha256": source["sha256"]}],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        }
        if replace:
            try:
                _previous, previous_sha = self.stage_store.read_input(trade_date, stage_id)
            except FileNotFoundError:
                imported = self.stage_store.import_input(input_payload)
            else:
                imported = self.stage_store.replace_input(
                    input_payload,
                    expected_sha256=previous_sha,
                    reason="explicit force refresh from cutoff-safe stage sources",
                )
        else:
            imported = self.stage_store.import_input(input_payload)
        return {
            "ok": True,
            "status": (
                "STAGE_INPUT_REFRESHED"
                if replace
                else (
                    "STAGE_INPUT_READY"
                    if pool_status in {"INDEPENDENT_GRAPH_POOLS", "CANONICAL_COMPLETE"} and not pool_gaps
                    else "STAGE_INPUT_READY_PARTIAL_POOL"
                )
            ),
            "pool_status": pool_status,
            "trade_date": trade_date,
            "stage_id": stage_id,
            "source_snapshot_path": source["payload_path"],
            "source_snapshot_sha256": source["sha256"],
            "input_sha256": imported["sha256"],
            "a_rows": len(a_rows),
            "hk_rows": len(hk_rows),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _stage_candidates(
        self,
        trade_date: str,
    ) -> tuple[list[dict[str, Any]], str, list[dict[str, str]], list[str]]:
        independent = PreselectionPoolStore(self.data_store.root)
        try:
            pools = independent.read_all(trade_date)
        except FileNotFoundError:
            pools = []
        if pools:
            if [pool["pool_id"] for pool in pools] != list(POOL_ORDER):
                raise ValueError("independent preselection pool set is incomplete")
            eligible_ids = {
                "a_d1_premarket_pool",
                "a_d1_fupan_watchlist_pool",
                "a_d1_stage7_fenshi_review_pool",
                "a_share_research_recommendation_pool",
                "hkconnect_d1_top100",
            }
            candidates = [
                row for pool in pools if pool["pool_id"] in eligible_ids
                for row in pool["rows"]
                if str(row.get("symbol") or "").startswith(("A.", "HK."))
            ]
            evidence = []
            gaps = []
            for pool in pools:
                if pool["pool_id"] not in eligible_ids:
                    continue
                artifact_path = f"preselection_pools/{trade_date}/{pool['pool_id']}.json"
                evidence.append({"path": artifact_path, "sha256": _sha256(pool)})
                gaps.extend(str(item) for item in pool.get("cannot_confirm", []))
            return candidates, "INDEPENDENT_GRAPH_POOLS", evidence, gaps
        pool = self.data_store.read_payload(trade_date)
        return (
            list(pool["a_all_pool_rows"]) + [
                row for row in pool["rows"]
                if str(row.get("symbol") or "").startswith("HK.")
            ],
            "CANONICAL_COMPLETE" if (
                pool.get("producer_status") == "CANONICAL_COMPLETE"
                and pool.get("canonical_main_pool_confirmed") is True
            ) else "PARTIAL",
            [],
            list(pool.get("cannot_confirm") or []),
        )

    def refresh(self, trade_date: str, stage_id: str) -> dict[str, Any]:
        return self.produce(trade_date, stage_id, replace=True)

    @staticmethod
    def _deduplicate_candidates(
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        selected: dict[str, dict[str, Any]] = {}
        for row in candidates:
            symbol = str(row.get("symbol") or "")
            if not symbol:
                continue
            current = selected.get(symbol)
            row_score = _number(row.get("pool_score"))
            row_rank = _number(row.get("pool_rank"))
            priority = (
                row_score if row_score is not None else float("-inf"),
                -(row_rank if row_rank is not None else float("inf")),
            )
            if current is None:
                selected[symbol] = row
                continue
            current_score = _number(current.get("pool_score"))
            current_rank = _number(current.get("pool_rank"))
            current_priority = (
                current_score if current_score is not None else float("-inf"),
                -(current_rank if current_rank is not None else float("inf")),
            )
            if priority > current_priority:
                selected[symbol] = row
        return list(selected.values())

    @staticmethod
    def _validate_window(captured_at: str, trade_date: str, start: str, cutoff: str) -> None:
        try:
            captured = datetime.fromisoformat(captured_at)
            lower = datetime.fromisoformat(f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T{start}")
            upper = datetime.fromisoformat(f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T{cutoff}")
        except ValueError as error:
            raise ValueError("invalid stage cutoff evidence time") from error
        if not lower <= captured <= upper:
            raise ValueError("quote evidence falls outside the stage cutoff window")

    @staticmethod
    def _quote_coverage(
        candidates: list[dict[str, Any]],
        quotes: dict[str, dict[str, Any]],
        prefixes: tuple[str, ...],
    ) -> dict[str, dict[str, int]]:
        requested: dict[str, set[str]] = {"A": set(), "HK": set()}
        for candidate in candidates:
            symbol = str(candidate.get("symbol") or "")
            if not symbol.startswith(prefixes):
                continue
            market = "A" if symbol.startswith("A.") else "HK"
            requested[market].add(symbol)
        return {
            market: {
                "requested": len(symbols),
                "returned": sum(symbol in quotes for symbol in symbols),
                "missing": sum(symbol not in quotes for symbol in symbols),
            }
            for market, symbols in requested.items()
        }

    @staticmethod
    def _merge_candidates(
        candidates: list[dict[str, Any]],
        quotes: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        a_rows: list[dict[str, Any]] = []
        hk_rows: list[dict[str, Any]] = []
        for candidate in candidates:
            symbol = str(candidate.get("symbol") or "")
            quote = quotes.get(symbol)
            if quote is None:
                continue
            row = {**candidate, **quote, "recommendation_status": "WATCH_ONLY"}
            if symbol.startswith("A."):
                a_rows.append(row)
                continue
            last_price = _number(row.get("last_price"))
            previous_close = _number(row.get("prev_close_price"))
            turnover = _number(row.get("turnover")) or 0.0
            if last_price is not None and previous_close not in (None, 0):
                row["pct_chg"] = round((last_price / previous_close - 1) * 100, 4)
            elif row.get("pct_chg") in ("", None):
                row["pct_chg"] = ""
            row["turnover_hkd"] = turnover
            row["turnover_hkd_yi"] = round(turnover / 100_000_000, 4)
            hk_rows.append(row)
        # A quote enriches an existing frozen candidate; it never admits a
        # new symbol. Missing candidates remain missing, without replacement.
        return a_rows, hk_rows


def _number(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
