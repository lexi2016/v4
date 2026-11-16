from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from ops import research_panel_daily_product as product


CENSUS = Path(
    "/Users/lexi/Desktop/学习/因子工厂/research/kuansong151_formula_daily_20261029_r1/"
    "today_all_a/five_group_completion_r1/source/census.py"
)
CENSUS_SHA256 = "75ed99318a149f2b57cbedd42618e5d5910d60ae2dd11f7fcb159c3fb3a6f2ef"
ASOF = 20260105
SYMBOL = "600001.SH"
QUALIFICATION = {"status": "CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH"}


def _bars(*, include_later_unknown: bool = False, only_two_clean: bool = False) -> list[dict]:
    bars = [
        dict(trade_date=20260101, open="0", high="0", low="0", close="0", vol="80"),
        dict(trade_date=20260102, open="10", high="12", low="9", close="11", vol="80"),
        dict(trade_date=20260103, open="10.5", high="11", low="9.5", close="10.8", vol="80"),
        dict(trade_date=20260104, open="10", high="12", low="9", close="11", vol="100"),
    ]
    if include_later_unknown:
        bars.append(dict(trade_date=20260105, open="10.8", high="11", low="10.5", close="10.9", vol="80"))
        bars.append(dict(trade_date=20260106, open="10.7", high="11", low="10.5", close="10.8", vol="50"))
        return bars
    bars.append(dict(trade_date=ASOF, open="10.7", high="11", low="10.5", close="10.8", vol="50"))
    if only_two_clean:
        return [bars[0], bars[-2], bars[-1]]
    return bars


class _Engine:
    def __init__(self, *, breakout_overrides: dict[int, object] | None = None, date_overrides: dict[int, int] | None = None):
        self.breakout_overrides = breakout_overrides or {}
        self.date_overrides = date_overrides or {}
        self.calls: list[tuple[list[dict], str]] = []

    def compute(self, bars: list[dict], mode: str) -> dict:
        self.calls.append((copy.deepcopy(bars), mode))
        rows = []
        for bar in bars:
            day = bar["trade_date"]
            signal = self.breakout_overrides.get(day, day == 20260104)
            if self.date_overrides.get(day) is not None:
                day = self.date_overrides[bar["trade_date"]]
            formula_values = {
                "B1": False,
                "B2": False,
                "B3": False,
                "突破": signal,
                "突破接十字星": False,
                "零上二金": False,
                "零下二金": False,
                "一级买点": False,
                "二级买点": False,
            }
            rows.append(
                dict(
                    trade_date=day,
                    ohlcv={key: bar[key] for key in ("open", "high", "low", "close", "vol")},
                    values=formula_values,
                )
            )
        return {"rows": rows, "mode": mode}

    @staticmethod
    def boolean(value):
        return value


class _Core:
    @staticmethod
    def signals(_values):
        return {"membership": "NO"}


class _Context:
    def __init__(self, bars: list[dict], *, target: int = ASOF, price_basis: str = "QFQ_ASOF"):
        self.target = target
        self.generation = "generation-test"
        self.config = {"census": {"path": str(CENSUS), "sha256": CENSUS_SHA256}}
        self.config_ref = {"sha256": "a" * 64}
        self.identity = {
            "generation": self.generation,
            "asof": target,
            "input_sha256": "b" * 64,
            "selector_artifact_sha256": "c" * 64,
            "snapshot": {"sha256": "d" * 64},
            "basis": {
                "asof_date": target,
                "price_basis": price_basis,
                "volume_basis": "QFQ_EVENT_VOLUME",
                "amount_basis": "RAW_TURNOVER",
            },
        }
        self.core = _Core()
        self._engine = _Engine()
        self.bars = bars

    def engine(self):
        return self._engine

    def g4_reference(self, symbol, date, _qualification):
        return {"symbol": symbol, "date": date, "correspondence_status": "UNKNOWN"}


def _run(bars: list[dict], *, target: int = ASOF, asof: int = ASOF, price_basis: str = "QFQ_ASOF",
         qualification: dict | None = None, breakout_overrides: dict[int, object] | None = None,
         date_overrides: dict[int, int] | None = None):
    if hashlib.sha256(CENSUS.read_bytes()).hexdigest() != CENSUS_SHA256:
        raise AssertionError("Pinned original census changed")
    context = _Context(bars, target=target, price_basis=price_basis)
    context._engine = _Engine(breakout_overrides=breakout_overrides, date_overrides=date_overrides)
    inputs = product.source_inputs(
        context, SYMBOL, bars, asof, qualification or QUALIFICATION
    )
    return context, inputs


def test_same_day_qfq_suffix_reuses_original_formula_signals_and_census():
    bars = _bars()
    original = copy.deepcopy(bars)
    context, inputs = _run(bars)

    assert inputs["baseline_memberships"] == {
        "original": "FALSE",
        "nav_pullback": "TRUE",
        "nav_breakout": "FALSE",
    }
    assert inputs["old_main_anchor_date"] == 20260104
    assert inputs["original_breakout_by_date"] == {
        20260101: "FALSE",
        20260102: "FALSE",
        20260103: "FALSE",
        20260104: "TRUE",
        ASOF: "FALSE",
    }
    assert context._engine.calls == [(original, "prefix")]
    assert bars == original


def test_fallback_fails_closed_for_ineligible_or_ambiguous_inputs():
    base = _bars()
    cases = [
        (base, ASOF, ASOF, "RAW_CLOSE", QUALIFICATION, None, None),
        (base, ASOF + 1, ASOF, "QFQ_ASOF", QUALIFICATION, None, None),
        (base, ASOF, ASOF, "QFQ_ASOF", {"status": "UNKNOWN"}, None, None),
        (_bars(only_two_clean=True), ASOF, ASOF, "QFQ_ASOF", QUALIFICATION, None, None),
        (_bars(include_later_unknown=True), ASOF + 1, ASOF + 1, "QFQ_ASOF", QUALIFICATION,
         {20260105: None}, None),
        (base, ASOF, ASOF, "QFQ_ASOF", QUALIFICATION, None, {20260104: 20260103}),
    ]
    for bars, target, asof, price_basis, qualification, signals, dates in cases:
        _context, inputs = _run(
            bars, target=target, asof=asof, price_basis=price_basis,
            qualification=qualification, breakout_overrides=signals, date_overrides=dates,
        )
        assert inputs["baseline_memberships"]["nav_pullback"] == "UNKNOWN"
        assert inputs["baseline_memberships"]["nav_breakout"] == "UNKNOWN"


def test_fallback_rejects_nonfinite_or_corrupt_clean_suffix_rows():
    nonfinite = _bars()
    nonfinite[-1]["close"] = "nan"
    impossible_geometry = _bars()
    impossible_geometry[2]["high"] = "8"
    negative_volume = _bars()
    negative_volume[-1]["vol"] = "-1"
    for bars in (nonfinite, impossible_geometry, negative_volume):
        _context, inputs = _run(bars)
        assert inputs["baseline_memberships"]["nav_pullback"] == "UNKNOWN"
        assert inputs["baseline_memberships"]["nav_breakout"] == "UNKNOWN"

