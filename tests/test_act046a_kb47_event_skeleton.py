"""ACT-046A clock contract and three sealed Batch 1 regression fixtures."""

from collections import Counter
import csv
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from ops import act046a_kb47_event_skeleton as audit


def bar(session, close, volume, *, low=10, yellow=10, opening=None):
    return audit.Bar(
        session, "1", "SAME_SEALED_ADJACENT_REFERENCE",
        open=close - 0.5 if opening is None else opening, high=max(11, close), low=low,
        close=close, pre_close=10, volume=volume, white_line=10.2, yellow_line=yellow,
        bbi=yellow, atr14=1,
    )


def window(*bars):
    return {bar.session: bar for bar in bars}


def anchor(known=-4, kind="FIXED_LOW", price=10):
    return audit.Support("old-anchor", known, kind, price, "prior-advance", "wave")


class ClockTests(unittest.TestCase):
    def test_damage_and_test_cannot_share_bar(self):
        bars = window(bar(-2, 11, 100), bar(-1, 9, 80, low=9), bar(0, 11, 150))
        clock = audit.repair_clock("sample", bars, anchor(-2))
        self.assertEqual(clock["current"]["d"], -1)
        self.assertEqual(clock["reason"], "NO_INDEPENDENT_TEST_DAY")
        self.assertEqual(clock["clock"], "FALSE")
        self.assertIsNone(clock["current"]["t"])
        self.assertIsNone(clock["current"]["c"])

    def test_test_and_confirmation_cannot_share_D(self):
        bars = window(bar(-3, 11, 100), bar(-2, 9, 90, low=9),
                      bar(-1, 9.5, 95, low=9), bar(0, 11, 70))
        clock = audit.repair_clock("sample", bars, anchor(-3))
        self.assertEqual(clock["reason"], "TEST_SEMANTICS_UNBOUND")
        self.assertEqual(clock["observed_clock"], "FALSE")
        self.assertIsNone(clock["current"]["c"])

    def test_anchor_or_prior_advance_unbound(self):
        bars = window(bar(-3, 11, 100), bar(-2, 9.5, 90, low=9),
                      bar(-1, 10, 80, low=9), bar(0, 11, 150))
        no_anchor = audit.repair_clock("sample", bars, None)
        no_advance = audit.repair_clock(
            "sample", bars, replace(anchor(-3), prior_advance_event_id=None),
        )
        self.assertEqual(no_anchor["reason"], "PREEXISTING_ANCHOR_UNBOUND")
        self.assertEqual(no_advance["observed_clock"], "TRUE")
        self.assertEqual(no_advance["clock"], "UNKNOWN")
        self.assertIsNone(no_advance["verified_repair_id"])

    def test_undamaged_anchor_and_touch_are_not_close_break(self):
        bars = window(bar(-3, 11, 100), bar(-2, 10, 90, low=9),
                      bar(-1, 10.3, 80, low=9), bar(0, 11, 150))
        clock = audit.repair_clock("sample", bars, anchor(-3))
        self.assertEqual(clock["reason"], "NO_OLD_ANCHOR_DAMAGE")
        self.assertEqual(clock["events"], [])

    def test_bounce_without_test(self):
        bars = window(bar(-3, 11, 100), bar(-2, 9.5, 90, low=9),
                      bar(-1, 9.6, 95, low=9), bar(0, 11, 150))
        clock = audit.repair_clock("sample", bars, anchor(-3))
        self.assertEqual(clock["observed_clock"], "FALSE")
        self.assertEqual(clock["clock"], "UNKNOWN")
        self.assertIsNone(clock["verified_repair_id"])
        self.assertIsNone(clock["current"]["t"])

    def test_reset_cannot_reuse_old_test_and_retains_old_repair(self):
        bars = window(bar(-4, 11, 100), bar(-3, 9.5, 90, low=9),
                      bar(-2, 10.3, 80, low=9), bar(-1, 9.4, 120, low=9), bar(0, 11, 150))
        clock = audit.repair_clock("sample", bars, anchor())
        old, new = clock["events"]
        self.assertEqual(old["state"], "RESET_BY_NEW_DAMAGE")
        self.assertEqual(old["t"], -2)
        self.assertEqual(new["repair_of"], old["repair_id"])
        self.assertNotEqual(new["repair_id"], old["repair_id"])
        self.assertEqual(new["d"], -1)
        self.assertIsNone(new["t"])
        self.assertIsNone(new["c"])

    def test_D_new_anchor_cannot_prove_old_support(self):
        bars = window(bar(-3, 11, 100), bar(-2, 9.5, 90, low=9),
                      bar(-1, 10, 80, low=9), bar(0, 11, 150))
        clock = audit.repair_clock("sample", bars, anchor(0))
        self.assertEqual(clock["reason"], "PREEXISTING_ANCHOR_UNBOUND")
        self.assertEqual(clock["events"], [])

    def test_session_gap_downgrades_order(self):
        bars = window(bar(-5, 11, 100), bar(-4, 9, 90, low=9),
                      bar(-2, 9.6, 80, low=9), bar(-1, 10, 70), bar(0, 11, 150))
        clock = audit.repair_clock("sample", bars, anchor(-5))
        self.assertEqual(clock["reason"], "TIME_ORDER_UNVERIFIED")
        self.assertEqual(clock["clock"], "UNKNOWN")
        self.assertIsNone(clock["current"]["c"])

    def test_missing_historical_anchor_bar_is_unverified(self):
        bars = window(bar(-3, 11, 100), bar(-2, 9.5, 90, low=9),
                      bar(-1, 10, 80, low=9), bar(0, 11, 150))
        clock = audit.repair_clock("sample", bars, anchor(-4))
        self.assertEqual(clock["clock"], "UNKNOWN")
        self.assertEqual(clock["reason"], "TIME_ORDER_UNVERIFIED")

    def test_dynamic_damage_cannot_borrow_close_before_support_known(self):
        bars = window(bar(-4, 9.5, 110, low=9), bar(-3, 9.5, 100, low=9),
                      bar(-2, 9.5, 95, low=9), bar(-1, 9.5, 90, low=9), bar(0, 11, 150))
        clock = audit.repair_clock("sample", bars, anchor(-2, "YELLOW_LINE"))
        event, = clock["events"]
        self.assertEqual((event["anchor_known_session"], event["d"]), (-2, -1))

    def test_dynamic_y_and_bbi_damage_on_second_consecutive_close(self):
        bars = window(bar(-5, 11, 100), bar(-4, 9.5, 90, low=9),
                      bar(-3, 9.5, 89, low=9), bar(-2, 9.5, 85, low=9),
                      bar(-1, 10.2, 80, low=9), bar(0, 11, 150))
        for kind in ("YELLOW_LINE", "BBI"):
            with self.subTest(kind=kind):
                clock = audit.repair_clock("sample", bars, anchor(-5, kind))
                event, = clock["events"]
                self.assertEqual((event["d"], event["t"], event["c"]), (-3, -1, 0))
                self.assertEqual(clock["verified_repair_id"], event["repair_id"])
                self.assertIsNone(event["first_full_confirm_time"])

    def test_known_test_support_break_resets_with_original_old_anchor_preserved(self):
        bars = window(bar(-4, 11, 140), bar(-3, 9.5, 130, low=9),
                      bar(-2, 10.8, 95, low=9), bar(-1, 10.2, 105, low=10.1), bar(0, 11, 150))
        test_support = audit.Support("tested-fixed-level", -2, "FIXED_LOW", 10.5)
        clock = audit.repair_clock("sample", bars, anchor(), {-2: test_support})
        old, new = clock["events"]
        self.assertEqual(old["state"], "RESET_BY_NEW_DAMAGE")
        self.assertEqual((new["d"], new["damage_anchor_id"]), (-1, "tested-fixed-level"))
        self.assertEqual(new["original_anchor_id"], "old-anchor")
        self.assertIsNone(new["t"])

    def test_signal_cross_and_axis_cross_keep_same_day_and_missing_separate(self):
        past = replace(bar(-1, 11, 100), macd_dif=-1, macd_dea=-1)
        current = replace(bar(0, 12, 150), macd_dif=1, macd_dea=2)
        row = {"m17_raw_f05": "TRUE", "m17_eligible_state": "UNKNOWN"}
        both = audit.d17(row, window(past, current))
        self.assertEqual(both["m17_USER_F09_SIGNAL_CROSS"], "FALSE")
        self.assertEqual(both["m17_COURSE_260422_DIF_AXIS_CROSS_same_day_confirmed_with_f05"], "TRUE")
        with_gap = audit.d17(row, window(replace(past, session=-2), current))
        self.assertEqual(with_gap["m17_COURSE_260422_DIF_AXIS_CROSS"], "UNKNOWN")
        self.assertEqual(with_gap["m17_USER_F09_SIGNAL_CROSS"], "UNKNOWN")


class SealedBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = Path(os.environ["ACT046A_BASELINE"])
        cls.blind = Path(os.environ["ACT046A_BLIND"])
        bytes_csv, cls.receipt = audit.replay(cls.baseline, cls.blind)
        reader = csv.DictReader(io.StringIO(bytes_csv.decode()))
        cls.rows = {int(row["record_index"]): row for row in reader}
        cls.header = reader.fieldnames

    def test_83_short_clock_has_old_anchor_and_separate_test(self):
        row = self.rows[83]
        self.assertEqual(row["act046a_m25_observed_price_clock"], "TRUE")
        self.assertEqual(row["act046a_m25_repair_clock"], "UNKNOWN")
        self.assertEqual(row["act046a_m25_verified_repair_id"], "")
        self.assertEqual(row["act046a_m25_anchor_session"], "-8")
        self.assertAlmostEqual(float(row["act046a_m25_anchor_price"]), 13.942596, places=6)
        event = json.loads(row["act046a_m25_event_ledger"])[-1]
        self.assertEqual((event["d"], event["t"], event["c"]), (-2, -1, 0))
        self.assertTrue(event["observations"][-1]["yellow_inside_static_range"])
        self.assertIsNone(event["first_full_confirm_time"])

    def test_102_long_clock_observes_non_touch_approach(self):
        row = self.rows[102]
        self.assertEqual(row["act046a_m25_observed_price_clock"], "TRUE")
        self.assertEqual(row["act046a_m25_repair_clock"], "UNKNOWN")
        event = json.loads(row["act046a_m25_event_ledger"])[-1]
        self.assertEqual((event["d"], event["t"], event["c"]), (-4, -1, 0))
        self.assertEqual([o["session"] for o in event["observations"]], [-3, -2, -1])
        self.assertFalse(event["observations"][-1]["yellow_inside_static_range"])
        self.assertTrue(event["observations"][-1]["low_approached_y"])
        self.assertIsNone(event["first_full_confirm_time"])

    def test_96_macd_tracks_and_gap_yin_evidence(self):
        row = self.rows[96]
        self.assertEqual(row["m17_raw_f05"], "TRUE")
        self.assertEqual(row["act046a_m17_USER_F09_SIGNAL_CROSS_same_day_confirmed_with_f05"], "TRUE")
        self.assertEqual(row["act046a_m17_COURSE_260422_DIF_AXIS_CROSS_same_day_confirmed_with_f05"], "FALSE")
        self.assertEqual(row["act046a_r3_is_gap_up_yin_bar"], "TRUE")
        self.assertAlmostEqual(float(row["act046a_r3_body_pct"]), -2.92, places=2)
        self.assertAlmostEqual(float(row["act046a_r3_white_dist_atr"]), 3.69, delta=0.01)
        self.assertEqual(row["act046a_m17_macd_turn_track_selected"], "")
        self.assertEqual(row["act046a_m17_eligible_state"], "UNKNOWN")
        self.assertEqual(row["act046a_m17_auto_L1_confirm"], "FALSE")

    def test_frozen_projection_and_nine_human_fact_rows(self):
        with self.baseline.open(encoding="utf-8-sig", newline="") as stream:
            source = csv.DictReader(stream)
            self.assertEqual(self.header[:171], source.fieldnames)
            self.assertEqual(
                [row for row in source],
                [{key: row[key] for key in self.header[:171]} for row in self.rows.values()],
            )
        self.assertTrue(all(k.startswith("act046a_") for k in self.header[171:]))
        self.assertEqual(Counter(r["m05_eligible_state"] for r in self.rows.values()),
                         {"FALSE": 172, "UNKNOWN": 9})
        facts = [i for i, r in self.rows.items() if r["act046a_m05_main_advance"]]
        self.assertEqual(facts, [21, 47, 74, 78, 124, 146, 147, 155, 164])
        for i in facts:
            row = self.rows[i]
            self.assertEqual(row["act046a_m05_main_advance"], "SOURCE_PENDING_ORAL_ONLY")
            sequence = json.loads(row["act046a_m05_prior_high_low_sequence"])
            self.assertTrue(all(entry[0] < 0 for entry in sequence))
        self.assertEqual(self.receipt["auto_L1_confirm_new"], 0)

    def test_atom_provenance_covers_appended_facts_and_nested_time_roles(self):
        fields = {"source_id", "source_version", "source_hash", "source_locator", "input_fields",
                  "clock_role", "as_of", "price_basis_id", "event_id", "output_fields"}
        event = json.loads(self.rows[83]["act046a_m25_event_ledger"])[-1]
        refs = [
            (event["damage_provenance"], -2, event["damage_id"]),
            (event["observations"][-1]["provenance"], -1, event["observations"][-1]["test_observation_id"]),
            (event["confirmation_facts"]["provenance"], 0, event["confirmation_facts"]["confirmation_observation_id"]),
        ]
        for ref, session, event_id in refs:
            self.assertEqual(set(ref), fields)
            self.assertEqual(ref["as_of"], session)
            self.assertEqual(ref["event_id"], event_id)
        self.assertTrue({"prior_bar.low", "prior_bar.yellow_line", "prior_bar.volume",
                         "damage_bar.volume", "anchor_bar.volume"} <= set(refs[1][0]["input_fields"]))
        self.assertTrue({"test_bar.volume", "prior_bar.volume"} <= set(refs[2][0]["input_fields"]))
        row_refs = json.loads(self.rows[21]["act046a_provenance"])
        bound_outputs = {f"act046a_{key}" for ref in row_refs.values() for key in ref["output_fields"]}
        self.assertEqual(bound_outputs | {"act046a_provenance", "act046a_as_of_relative_session"},
                         set(self.header[171:]))
        for ref in row_refs.values():
            self.assertEqual(set(ref), fields)
            self.assertLessEqual(ref["as_of"], 0)
        row96 = json.loads(self.rows[96]["act046a_provenance"])
        self.assertTrue(row96["f09"]["event_id"].endswith("/f09/0"))
        self.assertIsNone(row96["axis"]["event_id"])

    def test_unpinned_input_fails_without_processing(self):
        with tempfile.TemporaryDirectory() as temp:
            wrong = Path(temp) / "changed.csv"
            wrong.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "INPUT_SHA256_MISMATCH"):
                audit.replay(wrong, self.blind)


if __name__ == "__main__":
    unittest.main()
