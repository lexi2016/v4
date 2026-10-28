"""Cutoff-safe stage quote routing owned entirely by V4."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol, Sequence


class QuoteSource(Protocol):
    def snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]: ...


class ReferenceSource(Protocol):
    def read_reference_workbench(
        self,
        trade_date: str,
        stage_id: str,
    ) -> dict[str, Any] | None: ...


class StageQuoteProvider:
    """Prefer punctual OpenD; otherwise combine A replay with HK stage evidence."""

    _PRIMARY_BATCH_SIZE = 220

    def __init__(
        self,
        *,
        primary: QuoteSource,
        a_replay: QuoteSource,
        references: ReferenceSource,
        hk_replay: QuoteSource | None = None,
    ) -> None:
        self._primary = primary
        self._a_replay = a_replay
        self._references = references
        self._hk_replay = hk_replay

    def snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]:
        if stage_id == "STAGE_0925":
            return self._tdxpy_auction_snapshot(
                symbols,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
        primary_error = ""
        try:
            primary = self._primary_snapshot(
                symbols,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
            if primary.get("temporal_cutoff_safe") is True:
                return primary
            primary_error = "FUTU_SNAPSHOT_CAPTURED_AFTER_STAGE_CUTOFF"
        except Exception as error:
            primary_error = f"FUTU_SNAPSHOT_FAILED: {type(error).__name__}: {error}"

        requested_a = sorted(symbol for symbol in symbols if str(symbol).startswith("A."))
        requested_hk = any(str(symbol).startswith("HK.") for symbol in symbols)
        rows: list[dict[str, Any]] = []
        sources: list[str] = []
        cannot_confirm = [primary_error]
        if requested_a:
            replay = self._a_replay.snapshot(
                requested_a,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
            rows.extend(deepcopy(replay.get("rows", [])))
            sources.append(str(replay.get("source") or "PYTDX_A_SHARE_1MIN_REPLAY"))
            cannot_confirm.extend(replay.get("cannot_confirm", []))

        if requested_hk:
            hk_rows, hk_source = self._hk_stage_rows(
                symbols,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
            rows.extend(hk_rows)
            if hk_rows:
                sources.append(hk_source)
                cannot_confirm.append(
                    "HK_STAGE_ROWS_FROM_HKCONNECT_STAGE_REPLAY"
                    if hk_source == "V3_5_HKCONNECT_AGGREGATED_STAGE_REPLAY"
                    else "HK_STAGE_ROWS_FROM_LOCAL_MIGRATED_REFERENCE"
                )
            else:
                cannot_confirm.append("HK_CUTOFF_SAFE_STAGE_EVIDENCE_UNAVAILABLE")

        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": cutoff_at,
            "temporal_cutoff_safe": True,
            "source": "V3_5_CUTOFF_SAFE_COMPOSITE",
            "component_sources": sources,
            "cannot_confirm": cannot_confirm,
            "rows": rows,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _tdxpy_auction_snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]:
        """Use the user-locked V3 tdxpy lane for A-share 09:25 evidence."""
        requested_a = sorted(symbol for symbol in symbols if str(symbol).startswith("A."))
        requested_hk = any(str(symbol).startswith("HK.") for symbol in symbols)
        rows: list[dict[str, Any]] = []
        sources: list[str] = []
        cannot_confirm: list[str] = []
        futu_rescue_used = False
        if requested_a:
            try:
                auction = self._a_replay.snapshot(
                    requested_a,
                    trade_date=trade_date,
                    stage_id=stage_id,
                    cutoff_at=cutoff_at,
                )
                if auction.get("temporal_cutoff_safe") is not True:
                    raise ValueError("tdxpy 09:25 evidence is not temporal cutoff safe")
            except Exception as error:
                tdxpy_error = (
                    f"A_SHARE_0925_TDXPY_FAILED: {type(error).__name__}: {error}"
                )
                try:
                    rescue = self._primary_snapshot(
                        requested_a,
                        trade_date=trade_date,
                        stage_id=stage_id,
                        cutoff_at=cutoff_at,
                    )
                    if rescue.get("trade_date") != trade_date or rescue.get("stage_id") != stage_id:
                        raise ValueError("Futu 09:25 rescue identity mismatch")
                    if rescue.get("temporal_cutoff_safe") is not True:
                        raise ValueError("Futu 09:25 rescue captured after stage cutoff")
                    unsafe = [
                        key
                        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
                        if rescue.get(key) is not False
                    ]
                    if unsafe:
                        raise ValueError(
                            "Futu 09:25 rescue safety flags must be false: "
                            + ", ".join(unsafe)
                        )
                    rescue_rows = [
                        deepcopy(row)
                        for row in rescue.get("rows", [])
                        if isinstance(row, dict)
                    ]
                    returned = {str(row.get("symbol") or "") for row in rescue_rows}
                    if returned != set(requested_a):
                        missing = sorted(set(requested_a) - returned)
                        raise ValueError(
                            "Futu 09:25 rescue missing requested symbols: "
                            + ", ".join(missing)
                        )
                except Exception as rescue_error:
                    cannot_confirm.append(
                        f"A_SHARE_0925_EVIDENCE_FAILED: {type(error).__name__}: {error}"
                    )
                    cannot_confirm.append(
                        "FUTU_0925_RESCUE_FAILED: "
                        f"{type(rescue_error).__name__}: {rescue_error}"
                    )
                else:
                    rows.extend(rescue_rows)
                    sources.append(
                        str(rescue.get("source") or "FUTU_OPEND_READ_ONLY_SNAPSHOT")
                    )
                    cannot_confirm.extend(
                        [
                            tdxpy_error,
                            "FUTU_0925_READ_ONLY_SNAPSHOT_NOT_AUCTION_ORDER_BOOK",
                        ]
                    )
                    futu_rescue_used = True
            else:
                rows.extend(deepcopy(auction.get("rows", [])))
                sources.append(
                    str(auction.get("source") or "PYTDX_A_SHARE_0925_HISTORY_TRANSACTION")
                )
                cannot_confirm.extend(auction.get("cannot_confirm", []))
        if requested_hk:
            hk_rows, hk_source = self._hk_stage_rows(
                symbols,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
            rows.extend(hk_rows)
            if hk_rows:
                sources.append(hk_source)
                cannot_confirm.append(
                    "HK_STAGE_ROWS_FROM_HKCONNECT_STAGE_REPLAY"
                    if hk_source == "V3_5_HKCONNECT_AGGREGATED_STAGE_REPLAY"
                    else "HK_STAGE_ROWS_FROM_LOCAL_MIGRATED_REFERENCE"
                )
            else:
                cannot_confirm.append("HK_CUTOFF_SAFE_STAGE_EVIDENCE_UNAVAILABLE")
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": cutoff_at,
            "temporal_cutoff_safe": True,
            "source": (
                "V3_5_0925_CUTOFF_SAFE_COMPOSITE"
                if futu_rescue_used
                else "V3_5_TDXPY_0925_COMPOSITE"
            ),
            "component_sources": sources,
            "cannot_confirm": cannot_confirm,
            "rows": rows,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _hk_stage_rows(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> tuple[list[dict[str, Any]], str]:
        requested_hk = sorted(symbol for symbol in symbols if str(symbol).startswith("HK."))
        if self._hk_replay is not None and requested_hk:
            try:
                replay = self._hk_replay.snapshot(
                    requested_hk,
                    trade_date=trade_date,
                    stage_id=stage_id,
                    cutoff_at=cutoff_at,
                )
            except FileNotFoundError:
                replay = None
            if replay is not None and replay.get("rows"):
                return (
                    [deepcopy(row) for row in replay["rows"]],
                    "V3_5_HKCONNECT_AGGREGATED_STAGE_REPLAY",
                )
        reference = self._references.read_reference_workbench(trade_date, stage_id)
        reference_rows = reference.get("unified_rows", []) if reference else []
        return (
            [
                self._reference_hk_row(row)
                for row in reference_rows
                if isinstance(row, dict)
                and str(row.get("market") or "").upper() == "HK"
            ],
            "V3_5_MIGRATED_REFERENCE_SNAPSHOT",
        )

    def _primary_snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]:
        if not symbols:
            raise ValueError("stage quote snapshot requires at least one symbol")
        batches = [
            symbols[index : index + self._PRIMARY_BATCH_SIZE]
            for index in range(0, len(symbols), self._PRIMARY_BATCH_SIZE)
        ]
        payloads = [
            self._primary.snapshot(
                batch,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
            for batch in batches
        ]
        primary = deepcopy(payloads[0])
        primary["rows"] = [
            deepcopy(row)
            for payload in payloads
            for row in payload.get("rows", [])
        ]
        primary["temporal_cutoff_safe"] = all(
            payload.get("temporal_cutoff_safe") is True for payload in payloads
        )
        return primary

    @staticmethod
    def _reference_hk_row(source: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(source)
        row["symbol"] = str(row.get("symbol") or row.get("code") or "")
        if row.get("pct_chg") in ("", None):
            row["pct_chg"] = row.get("current_change_pct")
        row["data_level"] = "MIGRATED_REFERENCE_WORKBENCH"
        row["recommendation_status"] = "WATCH_ONLY"
        return row
