"""Read-only HK-connect stage replay from legacy V3 aggregated RT_DATA CSV."""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from contracts.stages import STAGE_DEFINITIONS


# Legacy V3 data root is injected via env (same var baimao/research lane use),
# never hardcoded. V4 reads only the aggregated replay CSV products.
_LEGACY_RUNTIME_ROOT = os.environ.get("V4_V3_DATA_ROOT")


# Reproduce the V3 HK-connect next-validation clock (opening_second_filter_service).
STAGE_NEXT_VALIDATION = {
    "STAGE_0925": "09:35",
    "STAGE_0930_0935": "09:40",
    "STAGE_0935_0940": "09:45",
    "STAGE_0940_0945": "10:30",
    "STAGE_0945_1030": "13:00",
    "STAGE_1300_1315": "14:45",
    "STAGE_1445_1500": "closeout",
    "STAGE_1545_1555": "16:00",
}


class HkConnectStageReplayProvider:
    """Build a cutoff-safe HK stage batch from the legacy aggregated replay CSV.

    The legacy V3 ``hkconnect_rtdata_stage_replay/{date}/STAGE_{id}/`` row files
    are treated as an external historical quote source (same role as the pytdx
    minute replay for A-shares): V4 reads the aggregated rows, re-validates
    stage identity, and emits its own read-only quote batch. The CSV is not a
    V3 final page artifact and is never used as live input.
    """

    def __init__(self, *, data_root: Path | None = None) -> None:
        self._data_root = Path(data_root) if data_root is not None else None

    def snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]:
        if not symbols:
            raise ValueError("HK-connect stage replay requires at least one symbol")
        if stage_id not in STAGE_DEFINITIONS:
            raise ValueError("unknown stage_id")
        cutoff = datetime.fromisoformat(cutoff_at)
        if cutoff.strftime("%Y%m%d") != trade_date:
            raise ValueError("HK-connect replay cutoff date mismatch")
        root = self._resolve_root(trade_date, stage_id)
        path = self._find_replay_csv(root, trade_date, stage_id)
        rows = self._read_rows(path, symbols, trade_date, stage_id, cutoff)
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": cutoff.isoformat(timespec="seconds"),
            "temporal_cutoff_safe": True,
            "source": "V3_5_HKCONNECT_AGGREGATED_STAGE_REPLAY",
            "rows": rows,
            "cannot_confirm": ["HKCONNECT_AGGREGATED_STAGE_REPLAY_READ_ONLY"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _resolve_root(self, trade_date: str, stage_id: str) -> Path:
        if self._data_root is not None:
            candidate = self._data_root / trade_date / stage_id
            if candidate.is_dir():
                return candidate
            raise FileNotFoundError(
                f"HK-connect stage replay directory not found: {candidate}"
            )
        if _LEGACY_RUNTIME_ROOT:
            runtime_root = Path(_LEGACY_RUNTIME_ROOT)
        else:
            raise FileNotFoundError(
                "HK-connect stage replay root is not configured; set V4_V3_DATA_ROOT"
            )
        candidates = (
            runtime_root
            / "opening_advisor_8771"
            / "data"
            / "hkconnect_rtdata_stage_replay"
            / trade_date
            / stage_id,
            runtime_root
            / "opening_advisor_8771"
            / "data"
            / "hkconnect_v11_shadow_stage_inputs"
            / trade_date
            / stage_id,
        )
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        raise FileNotFoundError(
            f"HK-connect stage replay directory not found for {trade_date}/{stage_id}"
        )

    @staticmethod
    def _find_replay_csv(root: Path, trade_date: str, stage_id: str) -> Path:
        expected = root / f"hkconnect_rtdata_stage_replay_{trade_date}_{stage_id}.csv"
        if expected.is_file():
            return expected
        matches = sorted(root.glob("hkconnect_rtdata_stage_replay_*.csv"))
        if not matches:
            raise FileNotFoundError(
                f"no HK-connect stage replay CSV in {root}"
            )
        return matches[-1]

    @staticmethod
    def _read_rows(
        path: Path,
        symbols: Sequence[str],
        trade_date: str,
        stage_id: str,
        cutoff: datetime,
    ) -> list[dict[str, Any]]:
        wanted = set(symbols)
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            for raw in csv.DictReader(source):
                symbol = str(raw.get("code") or "").strip().upper()
                if not symbol.startswith("HK.") or symbol not in wanted:
                    continue
                row = _normalize_hk_row(raw, trade_date, stage_id, cutoff)
                rows.append(row)
        return rows


def _normalize_hk_row(
    raw: dict[str, Any],
    trade_date: str,
    stage_id: str,
    cutoff: datetime,
) -> dict[str, Any]:
    symbol = str(raw.get("code") or "").strip().upper()
    last_price = _num(raw.get("last_price"))
    stage_low = _num(raw.get("stage_low_price"))
    stage_high = _num(raw.get("stage_high_price"))
    # Reproduce V3 support/pressure/invalidation from the stage replay range
    # (opening_second_filter_service candidates). Invalidation falls back to
    # support, exactly as V3 `_support_contract`.
    support = stage_low if stage_low is not None else last_price
    pressure = stage_high if stage_high is not None else last_price
    return {
        "symbol": symbol,
        "stock_name": str(raw.get("name") or symbol),
        "last_price": last_price,
        "prev_close_price": _num(raw.get("prev_close_price")),
        "pct_chg": _num(raw.get("pct_chg")),
        "turnover": _num(raw.get("turnover_hkd")),
        "turnover_hkd_yi": _num(raw.get("turnover_hkd_yi")),
        "circular_market_cap_hkd_yi": _num(raw.get("circular_market_cap_hkd_yi")),
        "stage_window_change_pct": _num(raw.get("stage_window_change_pct")),
        "stage_cumulative_pct_chg": _num(raw.get("stage_cumulative_pct_chg")),
        "stage_turnover_hkd_yi": _num(raw.get("stage_turnover_hkd_yi")),
        "stage_close_position": _num(raw.get("stage_close_position")),
        "stage_rtdata_score": _num(raw.get("stage_rtdata_score")),
        "current_change_pct": _num(raw.get("stage_window_change_pct")),
        "support_primary_price": support,
        "pressure_price": pressure,
        "invalidation_price": support,
        "next_validation_time": STAGE_NEXT_VALIDATION.get(stage_id, ""),
        "source_universe": str(raw.get("source_universe") or ""),
        "candidate_pool_type": str(raw.get("candidate_pool_type") or ""),
        "stage_replay_latest_time": str(raw.get("stage_replay_latest_time") or ""),
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": "HK",
        "data_level": "STAGE_RTDATA_LATE_REPLAY",
        "recommendation_status": "WATCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _num(value: Any) -> float | None:
    try:
        if value in ("", None, "N/A", "nan"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
