import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from ops.zge_skill_daily_screen import (
    StockSeries,
    GENERATION,
    SELECTOR_SHA,
    add_event_price_inputs,
    and_state,
    condition,
    count_at_least,
    evaluate_code,
    find_last,
    h_repair_rows,
    last_valid_name,
    load_bound_projection,
    rolling,
)


def sample_frame(count=80):
    dates = pd.bdate_range("2026-01-01", periods=count).strftime("%Y%m%d").tolist()
    frame = pd.DataFrame({
        "trade_date": dates,
        "open": np.full(count, 100.0), "high": np.full(count, 100.5),
        "low": np.full(count, 99.5), "close": np.full(count, 100.0),
        "volume": np.full(count, 100.0), "turnover_rate_pct": np.full(count, np.nan),
        "J": np.full(count, -20.0), "zge_white_line": np.linspace(101, 103, count),
        "zge_yellow_line": np.linspace(100, 102, count),
    })
    return frame, dates


def item(branch, condition_id):
    return next(c for c in branch["conditions"] if c["id"] == condition_id)


def make_series(frame, dates):
    return StockSeries(frame, dates, dates[-1])


class ThreeValueRuleTests(unittest.TestCase):
    def test_inclusive_threshold_keeps_equality(self):
        item = condition("attack_return", 0.04, ">=", 0.04, formula="R>=0.04")
        self.assertEqual(item["state"], "TRUE")

    def test_exclusive_threshold_rejects_equality(self):
        item = condition("J_exclusive", 55, "<", 55, formula="J<55")
        self.assertEqual(item["state"], "FALSE")

    def test_missing_denominator_stays_unknown(self):
        item = condition("ratio", None, "<=", 0.03, formula="abs(C/Y-1)<=0.03")
        self.assertEqual(item["state"], "UNKNOWN")

    def test_false_dominates_unknown_in_required_conjunction(self):
        self.assertEqual(and_state(["UNKNOWN", "FALSE"]), "FALSE")

    def test_unknown_attack_count_is_not_zero(self):
        self.assertEqual(count_at_least(["TRUE", "UNKNOWN", "FALSE"], 0, 2, 2), "UNKNOWN")
        self.assertEqual(count_at_least(["TRUE", "FALSE", "FALSE"], 0, 2, 2), "FALSE")

    def test_rolling_window_does_not_fill_a_missing_bar_with_zero(self):
        values = np.ones(26)
        values[5] = np.nan
        means = rolling(values, 20)
        self.assertTrue(np.isnan(means[19]))
        self.assertTrue(np.isnan(means[20]))
        self.assertAlmostEqual(means[25], 1.0)

    def test_g4_no_valid_bar_stays_unknown_and_out_of_candidates(self):
        date = "20261028"
        frame = pd.DataFrame({
            "trade_date": [date],
            "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5],
            "volume": [100.0], "turnover_rate_pct": [None],
            "J": [10.0], "zge_white_line": [11.0], "zge_yellow_line": [10.0],
            "BBI": [10.5],
        })
        row = evaluate_code(
            "002717.SZ", frame, [date], date,
            name=None, exchange="SZ", market_type="A_SHARE",
            turnover_status="G4_UNPRICED_OR_MISSING",
            lifecycle_reason=None, lifecycle_detail=None,
            ruleset_sha256="test", writer_source_sha256="test",
        )
        self.assertEqual(row["record_status"], "UNKNOWN_WITHOUT_SEED")
        self.assertEqual(row["raw_hit_group_ids"], [])
        self.assertEqual(set(row["unknown_group_ids"]), {
            "skill_r2_b1", "skill_r2_nana", "skill_r2_super_b1", "skill_r2_sb1",
            "skill_r2_b2", "skill_r2_b3", "skill_r2_parallel", "skill_r2_rebuild",
            "skill_r2_platform",
        })


class SessionAlignmentTests(unittest.TestCase):
    def test_missing_session_is_reindexed_as_unknown_input(self):
        dates = pd.bdate_range("2026-01-01", periods=30).strftime("%Y%m%d").tolist()
        frame_dates = [date for idx, date in enumerate(dates) if idx != 10]
        frame = pd.DataFrame({
            "trade_date": frame_dates,
            "open": np.full(len(frame_dates), 10.0),
            "high": np.full(len(frame_dates), 11.0),
            "low": np.full(len(frame_dates), 9.0),
            "close": np.full(len(frame_dates), 10.0),
            "volume": np.full(len(frame_dates), 100.0),
            "turnover_rate_pct": np.full(len(frame_dates), np.nan),
            "J": np.full(len(frame_dates), 0.0),
            "zge_white_line": np.full(len(frame_dates), 11.0),
            "zge_yellow_line": np.full(len(frame_dates), 10.0),
            "BBI": np.full(len(frame_dates), 10.5),
        })
        series = StockSeries(frame, dates, dates[-1])
        self.assertTrue(np.isnan(series.close[10]))
        self.assertEqual(series.shrink[20], "UNKNOWN")
        self.assertEqual(series.weekly["state"], "UNKNOWN")


class FrozenR2AlignmentTests(unittest.TestCase):
    def test_v20_excludes_today_for_attack_at_exact_1_5_boundary(self):
        frame, dates = sample_frame()
        frame.loc[79, ["open", "high", "low", "close", "volume"]] = [100, 105, 100, 105, 150]
        s = make_series(frame, dates)
        self.assertEqual(s.v20[-1], 100.0)
        self.assertEqual(s.attack[-1], "TRUE")

    def test_nana_uses_three_day_mean_not_current_volume(self):
        frame, dates = sample_frame()
        frame.loc[79, "volume"] = 30
        s = make_series(frame, dates)
        s.attack = ["FALSE"] * len(dates)
        s.attack[-5] = "TRUE"
        s.up[-1] = s.shrink[-1] = "TRUE"
        c = item(s.branches()["skill_r2_nana"], "volume_vs_attack")
        self.assertEqual(c["state"], "FALSE")
        self.assertAlmostEqual(c["observed"], (100+100+30)/3)
        self.assertEqual(c["threshold"], 60.0)

    def test_platform_compares_all_bull_volumes_not_only_heavy_bulls(self):
        frame, dates = sample_frame()
        frame.loc[59:62, "open"] = 99.9
        frame.loc[59:62, "close"] = 100.1
        frame.loc[59:62, "volume"] = [150, 150, 150, 110]
        frame.loc[63:67, "open"] = 100.1
        frame.loc[63:67, "close"] = 99.9
        frame.loc[63:67, "volume"] = 90
        s = make_series(frame, dates)
        s.v20[:] = 80
        branch = s.branches()["skill_r2_platform"]
        self.assertEqual(item(branch, "platform_bull_volume_days")["state"], "TRUE")
        dominance = item(branch, "bull_volume_dominance")
        self.assertEqual(dominance["state"], "TRUE")
        self.assertEqual(dominance["inputs"]["bull_volume_sum"], 560.0)
        self.assertEqual(dominance["inputs"]["bear_volume_sum"], 450.0)

    def test_b3_large_green_does_not_pass_either_small_body_branch(self):
        frame, dates = sample_frame()
        frame.loc[79, ["open", "high", "low", "close", "volume"]] = [100, 101.1, 99.9, 101, 50]
        s = make_series(frame, dates)
        s.b1_result = lambda k: {"normal": "TRUE", "strict": "TRUE"}
        s.b2_result = lambda k: {"state": "TRUE" if k == 78 else "FALSE", "anchor": 77, "conditions": []}
        branch = s.branches()["skill_r2_b3"]
        self.assertEqual(branch["alternative_states"], {"ordinary_b3": "FALSE", "changan": "FALSE"})
        self.assertEqual(branch["seed_state"], "FALSE")

    def test_b3_false_or_unknown_remains_unknown(self):
        frame, dates = sample_frame()
        frame.loc[77, "J"] = np.nan
        frame.loc[78, "low"] = 101
        frame.loc[79, "volume"] = 40
        s = make_series(frame, dates)
        s.b1_result = lambda k: {"normal": "TRUE", "strict": "TRUE"}
        s.b2_result = lambda k: {"state": "TRUE" if k == 78 else "FALSE", "anchor": 77, "conditions": []}
        branch = s.branches()["skill_r2_b3"]
        self.assertEqual(branch["alternative_states"], {"ordinary_b3": "FALSE", "changan": "UNKNOWN"})
        self.assertEqual(branch["seed_state"], "UNKNOWN")

    def test_last_anchor_cannot_skip_later_unknown(self):
        self.assertEqual(find_last(["FALSE", "TRUE", "UNKNOWN", "FALSE"], 0, 3), ("UNKNOWN", None))
        self.assertEqual(find_last(["UNKNOWN", "TRUE", "FALSE"], 0, 2), ("TRUE", 1))

    def test_super_b1_prior_attack_must_be_in_target_previous_20(self):
        frame, dates = sample_frame()
        frame.loc[77, "volume"] = 200
        frame.loc[79, "volume"] = 50
        s = make_series(frame, dates)
        s.attack = ["FALSE"] * len(dates)
        s.down_attack = ["FALSE"] * len(dates)
        s.attack[58] = "TRUE"  # t-21, which was within the old bear-relative search
        s.down_attack[77] = "TRUE"
        s.up[79] = "TRUE"
        branch = s.branches()["skill_r2_super_b1"]
        self.assertEqual(item(branch, "prior_attack")["state"], "FALSE")
        self.assertEqual(branch["seed_state"], "FALSE")

    def test_distribution_requires_bear_candle_even_with_gap_down(self):
        frame, dates = sample_frame()
        frame.loc[79, ["open", "high", "low", "close", "volume"]] = [87, 95.5, 86, 94, 300]
        s = make_series(frame, dates)
        branch = {"event_anchor": {"trade_date": dates[78]}}
        self.assertNotIn("HIGH_ZONE_HEAVY_DISTRIBUTION", [x["id"] for x in s.risk_check(branch)["flags"]])
        frame.loc[79, ["open", "high", "low"]] = [96, 96.2, 93.5]
        s = make_series(frame, dates)
        self.assertIn("HIGH_ZONE_HEAVY_DISTRIBUTION", [x["id"] for x in s.risk_check(branch)["flags"]])

    def test_failed_breakout_is_retained_after_price_recovers(self):
        frame, dates = sample_frame()
        frame.loc[77, ["open", "high", "low", "close"]] = [100, 102.5, 99.5, 102]
        frame.loc[78, ["open", "high", "low", "close"]] = [100, 100.5, 97.5, 98]
        s = make_series(frame, dates)
        risk = s.risk_check({"event_anchor": {"trade_date": dates[76]}})
        failed = next(x for x in risk["flags"] if x["id"] == "FAILED_BREAKOUT")
        self.assertEqual(failed["trade_date"], dates[77])
        self.assertEqual(failed["failure_trade_date"], dates[78])

    def test_four_bearish_subtype_unknown_with_unobserved_middle_candle(self):
        frame, dates = sample_frame()
        frame.loc[74:77, "close"] = 99.8
        frame.loc[78, "open"] = np.nan
        frame.loc[74:78, "volume"] = 50
        s = make_series(frame, dates)
        s.attack = ["FALSE"] * len(dates)
        s.attack[73] = s.attack[79] = "TRUE"
        branch = s.branches()["skill_r2_parallel"]
        self.assertNotIn("FOUR_BEARISH_MIDDLES", branch["subtypes"])
        self.assertEqual(branch["four_bearish_middles"], {
            "state": "UNKNOWN", "known_bearish_count": 4, "unknown_candle_count": 1,
        })

    def test_nonpositive_platform_low_makes_range_unknown(self):
        frame, dates = sample_frame()
        frame.loc[70, "low"] = -1
        c = item(make_series(frame, dates).branches()["skill_r2_platform"], "range_max")
        self.assertEqual(c["state"], "UNKNOWN")
        self.assertIsNone(c["observed"])

    def test_composite_events_expose_inputs_and_b2_anchor_subtypes(self):
        frame, dates = sample_frame()
        s = make_series(frame, dates)
        trend = s.b1_conditions(79)[0]
        self.assertEqual(trend["observed"], dates[79])
        self.assertEqual(trend["inputs"]["V20P"], 100)
        self.assertEqual(trend["inputs"]["V3"], 100)
        self.assertEqual(trend["inputs"]["O"], 100)
        self.assertEqual(trend["inputs"]["C"], 100)
        self.assertEqual(trend["inputs"]["previous_close"], 100)
        self.assertIsNotNone(trend["inputs"]["W_t_minus_5"])
        self.assertIsNotNone(trend["inputs"]["body"])
        s.b1_normal[78] = s.b1_strict[78] = "TRUE"
        anchor = s.b2_result(79)["conditions"][0]
        self.assertEqual(anchor["observed"], dates[78])
        self.assertEqual(anchor["source_subtypes"], ["B1_NORMAL", "B1_STRICT"])
        self.assertEqual(anchor["b1_anchor_low"], 99.5)

    def test_saved_signal_evidence_enrichment_keeps_rule_state(self):
        frame, dates = sample_frame()
        s = StockSeries(frame, dates, dates[-1], rebuild_only=True)
        saved = {"id": "attack", "state": "TRUE", "inputs": {"trade_date": dates[70], "V20P": 100}}
        add_event_price_inputs(saved, s, {day: i for i, day in enumerate(dates)})
        self.assertEqual(saved["state"], "TRUE")
        self.assertEqual(saved["inputs"]["V20P"], 100)
        self.assertEqual(saved["inputs"]["O"], 100)
        self.assertEqual(saved["inputs"]["C"], 100)
        self.assertFalse(hasattr(s, "weekly"))

    def test_h_repair_ignores_historical_code_not_in_target_admission(self):
        from types import SimpleNamespace
        dates = pd.bdate_range(end="2026-10-28", periods=90).strftime("%Y%m%d").tolist()
        code = "002717.SZ"
        frame, _ = sample_frame(90)
        frame["trade_date"] = dates
        frame["ts_code"], frame["market_type"], frame["exchange"] = code, "A_SHARE", "SZ"
        extra = frame.iloc[[0]].copy()
        extra["ts_code"], extra["exchange"], extra["market_type"] = "833429.BJ", "BJ", "BJ"
        projection = pd.concat([frame, extra], ignore_index=True)
        row = evaluate_code(code, frame, dates, "20261028", name="停牌测试", exchange="SZ",
                            market_type="A_SHARE", turnover_status="G4_UNPRICED_OR_MISSING",
                            lifecycle_reason=None, lifecycle_detail=None,
                            ruleset_sha256="test", writer_source_sha256="test")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text("{}", encoding="utf-8")
            old_rows = root / "all.jsonl"
            old_rows.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            previous = root / "receipt.json"
            previous.write_text(json.dumps({
                "asof": "20261028", "ruleset_id": "ZGE_SKILL_DAILY_CANDIDATES_R2",
                "source": {"generation_id": GENERATION, "receipt_sha256_actual": digest(source)},
                "counts": {"accepted_target_rows": 5538, "quarantine_retained_separately": 270},
                "artifacts": {"d28_all_5538_R2.jsonl": {"path": str(old_rows), "sha256": digest(old_rows)}},
            }), encoding="utf-8")
            panel = root / "panel.parquet"
            fake = SimpleNamespace(get_panel_meta=lambda **kwargs: {"generation_id": GENERATION, "path": str(panel)},
                                   load_selector_ready=lambda **kwargs: projection.copy())
            with patch("ops.zge_skill_daily_screen.RECEIPT_PATH", source), \
                 patch("ops.zge_skill_daily_screen.SELECTOR_PATH", panel), \
                 patch("ops.zge_skill_daily_screen.load_interface", return_value=fake), \
                 patch("ops.zge_skill_daily_screen.validate_receipt"):
                rows, info = h_repair_rows(previous, {code})
            self.assertEqual([r["ts_code"] for r in rows], [code])
            self.assertEqual(info["projection_rows"], 90)

    def test_later_unknown_cross_does_not_use_older_cross(self):
        frame, dates = sample_frame()
        s = make_series(frame, dates)
        s.w = np.zeros(len(dates))
        s.y = np.ones(len(dates))
        s.w[71] = 2
        s.w[76] = np.nan
        s.attack = ["FALSE"] * len(dates)
        s.attack[71] = "TRUE"
        s.attack[76] = "UNKNOWN"
        branch = s.branches()["skill_r2_rebuild"]
        self.assertEqual(branch["seed_state"], "UNKNOWN")
        self.assertIsNone(branch["event_anchor"])

    def test_rebuild_uses_older_qualified_event_when_newer_cross_has_no_attack(self):
        frame, dates = sample_frame()
        s = make_series(frame, dates)
        s.w = np.zeros(len(dates))
        s.y = np.ones(len(dates))
        s.w[70] = s.w[75] = 2
        s.w[79], s.y[79] = 101, 100
        s.shrink[79] = "TRUE"
        s.attack = ["FALSE"] * len(dates)
        s.attack[70] = "TRUE"
        branch = s.rebuild_branch()
        self.assertEqual(branch["seed_state"], "TRUE")
        self.assertEqual(branch["event_anchor"]["trade_date"], dates[70])

    def test_rebuild_unknown_first_attack_does_not_falsely_fix_segment_end(self):
        frame, dates = sample_frame()
        frame.loc[70, "low"] = 101
        frame.loc[71, "low"] = 99
        s = make_series(frame, dates)
        s.w, s.y = np.zeros(len(dates)), np.ones(len(dates))
        s.w[70], s.w[79], s.y[79] = 2, 101, 100
        s.shrink[79] = "TRUE"
        s.attack = ["FALSE"] * len(dates)
        s.attack[70], s.attack[71] = "UNKNOWN", "TRUE"
        branch = s.rebuild_branch()
        self.assertEqual(item(branch, "attack_on_k_or_next")["state"], "TRUE")
        support = item(branch, "crossover_attack_segment_support")
        self.assertEqual([x["state"] for x in support["possible_segments"]], ["FALSE", "TRUE"])
        self.assertEqual(support["state"], "UNKNOWN")
        self.assertIsNone(branch["event_anchor"])

        frame.loc[70, "low"] = 99
        s = make_series(frame, dates)
        s.w, s.y = np.zeros(len(dates)), np.ones(len(dates))
        s.w[70], s.w[79], s.y[79] = 2, 101, 100
        s.shrink[79] = "TRUE"
        s.attack = ["FALSE"] * len(dates)
        s.attack[70], s.attack[71] = "UNKNOWN", "TRUE"
        branch = s.rebuild_branch()
        self.assertEqual(branch["seed_state"], "TRUE")
        self.assertEqual(s.risk_check(branch)["state"], "UNKNOWN")

    def test_name_uses_last_nonempty_value_no_later_than_asof(self):
        frame = pd.DataFrame({"trade_date": ["20261026", "20261027", "20261028", "20261029"],
                              "name": ["原名", " 最近有效名 ", " ", "未来名"]})
        self.assertEqual(last_valid_name(frame, "20261028"), ("最近有效名", "20261027"))
        self.assertEqual(last_valid_name(frame.iloc[[2]], "20261028"), (None, None))

    def test_receipt_authority_status_is_bound_from_real_field(self):
        from types import SimpleNamespace
        dates = ["20261028"]
        rows = []
        for exchange, count in [("SZ", 2893), ("SH", 2317), ("BJ", 328)]:
            rows.extend({"trade_date": dates[0], "ts_code": f"{n:06d}.{exchange}",
                         "exchange": exchange} for n in range(count))
        fake_interface = SimpleNamespace(
            get_panel_meta=lambda **kwargs: {"generation_id": GENERATION, "path": "bound"},
            load_selector_ready=lambda **kwargs: pd.DataFrame(rows),
        )
        receipt = {"target_date": dates[0], "selector": "bound",
                   "formula": {"authority": {"generation_id": GENERATION}},
                   "selector_sha256": SELECTOR_SHA, "target_count": 5808,
                   "accepted_count": 5538, "quarantine_count": 270,
                   "authority_status": "REBUILD_REQUIRED", "formula_authority_status": ""}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with patch("ops.zge_skill_daily_screen.load_interface", return_value=fake_interface):
                _, _, source = load_bound_projection(Path("bound"), Path("interface"), path)
        self.assertEqual(source["authority_status"], "REBUILD_REQUIRED")

if __name__ == "__main__":
    unittest.main()
