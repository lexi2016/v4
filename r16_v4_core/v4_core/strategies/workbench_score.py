"""Candidate-only projection using the active A-share knowledge-base rules."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from v4_core.strategies import kb_n_structure
from v4_core.strategies.kb_action_authority import project_action
from v4_core.strategies.kb_hold_score import apply_n_score, project_single_history, research_code_in_scope
from v4_core.strategies.kb_signal_authority import append_kb_signals, project_bound_kb_j

RULE_VERSION = "a_share_kb_hold_score_v1"
CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contracts"
CONTRACTS = (
    "a_share_kb_fields_v1.json",
    "a_share_kb_hold_score_v1.json",
    "a_share_kb_n_structure_v1.json",
    "a_share_kb_action_v1.json",
)
INPUT_COLUMNS = ("open", "high", "low", "close", "volume", "pre_close", "pct_chg", "user_v1_sell_signal_daily")


def _plain(value):
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


@lru_cache(maxsize=1)
def _rule_identity():
    contracts = {}
    for name in CONTRACTS:
        data = (CONTRACT_DIR / name).read_bytes()
        if json.loads(data)["schema"] != Path(name).stem:
            raise ValueError(f"KB_CONTRACT_SCHEMA_INVALID:{name}")
        contracts[name] = hashlib.sha256(data).hexdigest()
    # The N structure and hold component must agree on the identity of the
    # pure N helper. No materializer/writer source file is part of scoring.
    helper_sha = hashlib.sha256(Path(kb_n_structure.__file__).read_bytes()).hexdigest()
    return contracts, helper_sha


def _target_rows(symbol, target, bars):
    rows = []
    for bar in bars:
        day = date.fromisoformat(str(bar["trade_date"])).strftime("%Y%m%d")
        if day > target:
            continue
        if bar.get("ts_code", bar.get("symbol", symbol)) != symbol:
            raise ValueError("KB_ONE_SYMBOL_REQUIRED")
        row = {"ts_code": symbol, "trade_date": day}
        row.update((key, _plain(bar.get(key))) for key in INPUT_COLUMNS)
        volume = row["volume"]
        if isinstance(volume, (int, float)) and not isinstance(volume, bool):
            # SQLite stores whole REAL values using INTEGER affinity; the
            # authoritative QFQ volume column uses double, including 0.0.
            row["volume"] = float(volume)
        rows.append(row)
    rows.sort(key=lambda row: row["trade_date"])
    return rows


def score_symbol_from_bars(
    trade_date: str,
    symbol: str,
    selection_group: str,
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute from an ordered, complete-to-target QFQ prefix, without IO to the live owner."""
    base = {
        "trade_date": trade_date,
        "symbol": symbol,
        "selection_group": selection_group,
        "rule_version": RULE_VERSION,
        "score": None,
        "action": "UNKNOWN",
        "status": "UNKNOWN",
    }
    if not research_code_in_scope(symbol, scope="ADMITTED_A_SHARE"):
        return {**base, "detail_json": json.dumps({"reason": "SINGLE_STOCK_SCOPE_CONFLICT"})}
    target = date.fromisoformat(str(trade_date)).strftime("%Y%m%d")
    rows = _target_rows(symbol, target, bars)
    if not rows or rows[-1]["trade_date"] != target:
        return {**base, "detail_json": json.dumps({"reason": "EXACT_TARGET_QFQ_BAR_UNAVAILABLE", "bar_count": len(rows)})}

    contracts, helper_sha = _rule_identity()
    prefix = _digest(rows)
    js = project_bound_kb_j(symbol, rows)
    score_input = [dict(row, kb_b1_j=j["kb_b1_j"]) for row, j in zip(rows, js)]
    scores = project_single_history(symbol, score_input, scope="ADMITTED_A_SHARE")
    n_identity = {
        "generation_id": f"isolated-kb:{prefix}",
        "input_sha256": prefix,
        "rule_sha256": contracts["a_share_kb_n_structure_v1.json"],
        "helper_sha256": helper_sha,
        "calendar_sha256": None,
        "price_basis_sha256": None,
        "price_basis": "QFQ_ASOF",
    }
    n_rows, _ = kb_n_structure.project_n_history(symbol, rows, identity=n_identity)
    hold_score = apply_n_score(
        symbol, score_input, scores, n_rows,
        rule_sha256=n_identity["rule_sha256"], helper_sha256=helper_sha, scope="ADMITTED_A_SHARE",
    )[-1]

    import pandas as pd

    frame = pd.DataFrame(rows).rename(columns={"volume": "vol"})
    kb = {key: _plain(value) for key, value in append_kb_signals(frame, output_dates={int(target)}).iloc[-1].items()
          if key.startswith("kb_")}
    action = project_action(
        kb | hold_score | {"user_v1_sell_signal_daily": rows[-1]["user_v1_sell_signal_daily"]},
        rule_sha256=contracts["a_share_kb_action_v1.json"],
    )
    detail = {
        "hold_score": hold_score,
        "kb": kb,
        "kb_action": action,
        "n_structure": n_rows[-1]["kb_n_structure"],
        "calculation_source": "CANDIDATE_SELF_COMPUTED_QFQ_PREFIX",
        "input_prefix_sha256": prefix,
        "input_rows": len(rows),
        "rule_contract_sha256": contracts,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    return {
        **base,
        "score": hold_score["kb_hold_score"],
        "action": action["kb_action_with_position"] or "UNKNOWN",
        "status": "READY" if hold_score["kb_hold_score_status"] == "COMPLETE" else "UNKNOWN",
        "detail_json": json.dumps(detail, ensure_ascii=False, allow_nan=False),
    }
