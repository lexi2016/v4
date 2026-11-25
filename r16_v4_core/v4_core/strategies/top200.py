"""Clean daily Top200 ranker — replaces external desktop ast.parse/exec hacks."""
from __future__ import annotations

from typing import Any

from v4_core.storage.db import V4Store


def build_daily_top200(
    store: V4Store,
    trade_date: str,
    *,
    name_map: dict[str, str] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Rank A-share daily gainers with explicit separation of daily eligibility vs historical PIT."""
    bars = store.get_date_bars("A", trade_date, table="daily_bars")
    names = name_map or {}
    ranked: list[dict[str, Any]] = []

    for b in bars:
        pre = b.get("pre_close")
        if pre is None or float(pre) <= 0:
            continue
        pct = round((float(b["close"]) / float(pre) - 1.0) * 100.0, 4)
        ranked.append(
            {
                "trade_date": trade_date,
                "symbol": b["symbol"],
                "name": names.get(b["symbol"], b["symbol"]),
                "close": float(b["close"]),
                "pct_chg": pct,
                "amount": float(b["amount"]),
                "daily_gain_rank_eligibility": "ELIGIBLE_DAILY_CLOSE",
                "historical_pit": 0,  # Explicitly False unless true historical PIT exists
            }
        )

    ranked.sort(key=lambda r: (-r["pct_chg"], -r["amount"], r["symbol"]))
    top = [{**row, "rank": idx + 1} for idx, row in enumerate(ranked[:limit])]
    store.save_top200(trade_date, top)
    return top
