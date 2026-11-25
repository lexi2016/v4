"""Clean daily Top200 ranker — replaces external desktop ast.parse/exec hacks."""
from __future__ import annotations

from typing import Any

from v4_core.qfq.engine import MissingAdjustmentFactorError, ex_rights_reference_close

from v4_core.storage.db import V4Store


def build_daily_top200(
    store: V4Store,
    trade_date: str,
    *,
    name_map: dict[str, str] | None = None,
    limit: int = 200,
    factor_map: dict[str, dict[str, float]] | None = None,
    reference_gaps: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rank A-share daily gainers with explicit separation of daily eligibility vs historical PIT."""
    bars = store.get_a_daily_reference_inputs(trade_date)
    names = name_map or {}
    ranked: list[dict[str, Any]] = []

    for b in bars:
        code = b["symbol"]
        basis = "PAIRED_QFQ_FACTORS"
        try:
            if b["prior_date"] and b["prior_date"] < trade_date:
                factors = factor_map.get(code, {}) if factor_map is not None else None
                pre = ex_rights_reference_close(
                    b["prior_raw_close"],
                    factors.get(b["prior_date"]) if factors is not None else b["prior_factor"],
                    factors.get(trade_date) if factors is not None else b["target_factor"],
                )
            else:
                raise MissingAdjustmentFactorError("A_EX_RIGHTS_REFERENCE_INPUT_UNVERIFIED")
        except MissingAdjustmentFactorError as exc:
            if reference_gaps is not None:
                reference_gaps.append({"symbol": code, "prior_date": b["prior_date"], "reason": str(exc)})
            continue
        pct = round((float(b["close"]) / float(pre) - 1.0) * 100.0, 4)
        ranked.append(
            {
                "trade_date": trade_date,
                "symbol": b["symbol"],
                "name": names.get(b["symbol"], b["symbol"]),
                "close": float(b["close"]),
                "pct_chg": pct,
                "reference_pre_close": pre,
                "reference_basis": basis,
                "amount": float(b["amount"]),
                "daily_gain_rank_eligibility": "ELIGIBLE_DAILY_CLOSE",
                "historical_pit": 0,  # Explicitly False unless true historical PIT exists
            }
        )

    ranked.sort(key=lambda r: (-r["pct_chg"], -r["amount"], r["symbol"]))
    top = [{**row, "rank": idx + 1} for idx, row in enumerate(ranked[:limit])]
    store.save_top200(trade_date, top)
    return top
