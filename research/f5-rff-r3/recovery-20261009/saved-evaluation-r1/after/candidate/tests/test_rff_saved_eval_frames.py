"""Synthetic-only tests for the new saved-frame composition, not PR5 reacceptance.

No score, truth, model or registry artifact is read.  The three imported source
files are hash checked.  The frozen metric code is given an explicitly synthetic
settings module because the historical spike5.settings is not in the source
attachment; no claim about the real calibration bins is made here.

Run from the delivered issue33 directory:
    python -m unittest discover -s candidate/tests -p test_rff_saved_eval_frames.py -v

ISSUE33_ATTACHMENTS_ROOT and ISSUE33_REMOTE_ROOT can relocate the source-only
reference files on the reviewing Mac.  The original PR5 tests are never loaded.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import numpy as np
import pandas as pd


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "candidate/src/rff_saved_eval_frames.py"
ATTACHMENTS = Path(os.environ.get("ISSUE33_ATTACHMENTS_ROOT", ROOT / "inputs/attachments"))
REMOTE = Path(os.environ.get("ISSUE33_REMOTE_ROOT", ROOT / "inputs/remote/research/f5-rff-r3"))


def load_source(name, path, expected_sha=None):
    if expected_sha is not None:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha:
            raise AssertionError(f"Source fixture SHA mismatch: {path.name}: {actual}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SavedFramesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.accepted = load_source(
            "issue33_pr5_accepted_worker",
            ATTACHMENTS / "rff/pr5_accepted/src/rff_worker.py",
            "3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c",
        )
        cls.score_aware = load_source(
            "issue33_synthetic_score_aware",
            ATTACHMENTS / "shared/src/score_aware_metrics.py",
            "fc93d6225c75b633981508a18c428e7649122571c7d897264d0b7da1e591eb8c",
        )
        package_name = "issue33_synthetic_metric_fixture"
        package = types.ModuleType(package_name)
        package.__path__ = []
        settings = types.ModuleType(package_name + ".settings")
        settings.CONTRACT = {
            "calibration_bins": [0.0, 0.5, 1.0],
            "bootstrap": {"block_sessions": 1, "replicates": 10, "seed": 7},
        }
        # Preserve only the synthetic entries we own; do not replace sys.modules.
        cls.previous_entries = {
            name: sys.modules.get(name) for name in (package_name, settings.__name__)
        }
        sys.modules[package_name] = package
        sys.modules[settings.__name__] = settings
        cls.frozen = load_source(
            package_name + ".metrics", REMOTE / "external_frozen_evaluator/metrics.py",
            "c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763",
        )
        cls.metrics_patch = mock.patch.object(cls.score_aware, "frozen_metrics", return_value=cls.frozen)
        cls.metrics_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.metrics_patch.stop()
        for name, previous in cls.previous_entries.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    def setUp(self):
        # An assertion failure, rather than an import/collection error, is the
        # intentional first RED result while the new entry is still absent.
        self.assertTrue(MODULE_PATH.is_file(), "RFF saved-frame evaluator module is missing")
        self.module = load_source("issue33_saved_frames_under_test", MODULE_PATH)
        self.assertTrue(callable(getattr(self.module, "evaluate_frames", None)),
                        "RFF saved-frame evaluate_frames interface is missing")
        self.frames = self.make_frames()

    def make_frames(self):
        codes = [f"{n:04d}" for n in range(1, 7)]
        calendar = pd.DataFrame({"session_id": [10, 11], "market_date": ["2024-01-02", "2024-01-03"]})
        truth = pd.DataFrame({
            "code": pd.Series(codes * 2, dtype="string"),
            "session_id": [10] * 6 + [11] * 6,
            "market_date": ["2024-01-02"] * 6 + ["2024-01-03"] * 6,
            "scoreable": [1, 1, 1, 1, 1, 0] * 2,
            "y": [1., 0., np.nan, 1., 0., np.nan, 0., 1., 1., 0., np.nan, np.nan],
            "label_status": ["KNOWN", "KNOWN", "UNKNOWN", "KNOWN", "KNOWN", "UNKNOWN",
                             "KNOWN", "KNOWN", "KNOWN", "KNOWN", "UNKNOWN", "UNKNOWN"],
            "first_exact": [11, -1, -1, 11, -1, -1, -1, 16, 16, -1, -1, -1],
            "episode_state": ["NONE"] * 6 + ["NEW", "NONE", "NONE", "NEW", "NONE", "NONE"],
        })
        scores = truth[["code", "session_id", "market_date", "scoreable"]].copy()
        scores["ranking_score"] = [3., 2., 1., 0., -1., np.nan, -1., 4., 2., 1., 0., np.nan]
        scores["probability"] = 1. / (1. + np.exp(-scores["ranking_score"]))
        scores.index = pd.Index(range(100, 112), name="saved_grid_index")
        # These are fixture choices, not a call into the production selector.
        top3 = scores.iloc[[0, 1, 2, 7, 8, 9]].copy()
        top3["rank"] = [1, 2, 3, 1, 2, 3]
        top3["weight"] = "1/3"
        top3.index = pd.Index([7, 7, 2, 5, 5, 1], name="saved_top3_index")
        controls = {}
        probabilities = {
            "FROZEN_UNWEIGHTED_PLUS_PATH": [.9, .8, .1, .7, .6, np.nan, .7, .9, .6, .8, .5, np.nan],
            "FROZEN_BASE34": [.1, .7, .6, .4, .9, np.nan, .8, .2, .7, .1, .9, np.nan],
        }
        for name, p in probabilities.items():
            frame = truth.copy()
            frame["probability"] = p
            selected = self.frozen.select_top3(frame)
            controls[name] = {
                "scores": frame,
                "top3": selected[["code", "session_id", "rank", "probability"]].copy(),
            }
        evaluation = {"year": 2024, "grid_rows": 12, "scoreable_rows": 10,
                      "sessions": 2, "selection_slots": 6, "known_positive_denominator": 2}
        experiment = {
            "route_id": "F5_FULL64_RFF_LOGISTIC_R1_20260927",
            "decision_gates": {
                "development_primary": {"metric": "paired lower candidate-minus-frozen-PLUS", "operator": ">", "value": 0.0},
                "practical_base34": {"metric": "paired lower candidate-minus-frozen-BASE34", "operator": ">=", "value": 0.03},
                "original_promotion_gates_unchanged": {
                    "paired_precision_lower_gain": .03, "relative_precision_lower_ratio": 1.25,
                    "random_lift_lower": 2.0, "positive_years_min": 2,
                    "selected_unknown_fraction_max": .05, "empty_slots_max": 0,
                    "episode_coverage_gain_min": 0.0, "ap_known_gain_min": 0.0,
                    "brier_known_gain_max": 0.0, "promotion_now": False,
                    "single_exposed_year_blocks_promotion": True,
                },
            },
        }
        return {"candidate_scores": scores, "candidate_top3": top3, "truth": truth,
                "calendar": calendar, "controls": controls, "evaluation_contract": evaluation,
                "experiment_contract": experiment}

    def evaluate(self, **changes):
        arguments = dict(self.frames)
        arguments.update(changes)
        return self.module.evaluate_frames(
            **arguments, score_aware=self.score_aware, accepted_worker=self.accepted,
            execution_id="SYNTHETIC_RFF_SAVED_EVAL_ONLY",
            artifact_sha256={"candidate_scores": "synthetic-scores", "candidate_top3": "synthetic-top3"},
        )

    def assert_error(self, error_code, **changes):
        with self.assertRaises(Exception) as caught:
            self.evaluate(**changes)
        self.assertIsInstance(caught.exception, self.module.RFFSavedEvaluationError)
        self.assertRegex(str(caught.exception), error_code)

    def test_original_rff_arm_and_probability_outputs_remain_equal(self):
        result = self.evaluate()
        candidate = self.accepted._join_truth(self.frames["candidate_scores"], self.frames["truth"])
        selected = self.accepted._join_truth(self.frames["candidate_top3"], self.frames["truth"])
        original = self.score_aware.arm_metrics(candidate, selected, self.frames["calendar"],
                                              score_kind=self.score_aware.RAW_RANKING_SCORE,
                                              score_column="ranking_score")
        original["probability"] = self.frozen.probability_metrics(candidate)
        self.assertEqual(result["arms"]["CANDIDATE_RFF_LOGISTIC"], original)
        self.assertIsNotNone(original["probability"]["brier_known"])
        self.assertIsNotNone(original["probability"]["logloss_known"])
        self.assertEqual(len(original["probability"]["calibration_bins"]), 2)

    def test_both_paired_bounds_keep_shared_unknown_cancellation(self):
        result = self.evaluate()
        plus = result["paired_precision"]["FROZEN_UNWEIGHTED_PLUS_PATH"]
        base = result["paired_precision"]["FROZEN_BASE34"]
        self.assertEqual(plus["denominator"], 6)
        self.assertEqual(base["denominator"], 6)
        self.assertAlmostEqual(plus["lower"], 0.)
        self.assertAlmostEqual(plus["upper"], 1. / 6.)
        self.assertAlmostEqual(base["lower"], 1. / 6.)
        self.assertAlmostEqual(base["upper"], 1. / 3.)
        gates = result["development_gates"]
        self.assertFalse(gates["paired_lower_vs_plus_gt_zero"])
        self.assertTrue(gates["paired_lower_vs_base34_ge_003"])
        self.assertEqual(result["evidence_ceiling"], "DIRECTION_ONLY")
        self.assertEqual(result["promotion_decision"], "BLOCKED_SINGLE_EXPOSED_YEAR")

    def test_episode_denominator_is_not_positive_label_row_count(self):
        result = self.evaluate()
        self.assertEqual(result["confirmed_new_episode_denominator"], 2)
        self.assertEqual(result["known_positive_rows_full_g"], 4)
        self.assertEqual(result["truth_positive_denominator"], 2)

    def test_shuffled_truth_and_unknowns_are_evaluated_without_mutating_inputs(self):
        self.frames["truth"] = self.frames["truth"].iloc[::-1].copy()
        before = copy.deepcopy(self.frames)
        join = self.accepted._join_truth
        with mock.patch.object(self.accepted, "_join_truth", wraps=join) as join_spy:
            result = self.evaluate()
        self.assertEqual(join_spy.call_count, 2)
        self.assertEqual(result["arms"]["CANDIDATE_RFF_LOGISTIC"]["unknown_selected"], 1)
        for name in ("candidate_scores", "candidate_top3", "truth", "calendar"):
            pd.testing.assert_frame_equal(self.frames[name], before[name], check_exact=True)
        for name, control in self.frames["controls"].items():
            for artifact in ("scores", "top3"):
                pd.testing.assert_frame_equal(control[artifact], before["controls"][name][artifact], check_exact=True)

    def test_raw_ap_remains_explicit_when_sigmoid_scores_tie(self):
        scores = self.frames["candidate_scores"]
        scores["ranking_score"] = [1000., 900., 800., 700., 600., np.nan,
                                    -1000., 1000., 900., 800., 700., np.nan]
        scores["probability"] = [1., 1., 1., 1., 1., np.nan, 0., 1., 1., 1., 1., np.nan]
        picks = scores.iloc[[0, 1, 2, 7, 8, 9]].copy()
        picks["rank"] = [1, 2, 3, 1, 2, 3]
        picks["weight"] = "1/3"
        self.frames["candidate_top3"] = picks
        result = self.evaluate()
        candidate = self.accepted._join_truth(scores, self.frames["truth"])
        raw = self.score_aware.probability_metrics(candidate, score_kind=self.score_aware.RAW_RANKING_SCORE,
                                                  score_column="ranking_score")
        probability_ap = result["arms"]["CANDIDATE_RFF_LOGISTIC"]["probability"]["average_precision_known"]
        self.assertEqual(result["ranking_score_diagnostics"]["average_precision_known"], raw["average_precision_known"])
        self.assertNotEqual(probability_ap, raw["average_precision_known"])

    def test_saved_candidate_top3_is_not_reselected(self):
        selector = self.score_aware.select_top3
        def reject_candidate_reselection(frame, **kwargs):
            if kwargs.get("score_kind") == self.score_aware.RAW_RANKING_SCORE:
                self.fail("Saved candidate Top3 must not be replaced by a new selection")
            return selector(frame, **kwargs)
        with mock.patch.object(self.score_aware, "select_top3", side_effect=reject_candidate_reselection):
            self.evaluate()

    def test_missing_saved_probability_is_a_schema_blocker(self):
        self.assert_error("RFF_FRAME_SCHEMA_MISMATCH:candidate_scores",
                          candidate_scores=self.frames["candidate_scores"].drop(columns="probability"))

    def test_saved_candidate_probability_must_cover_exact_scoreable_domain(self):
        for row, value in ((100, np.nan), (105, .5), (100, np.inf)):
            with self.subTest(row=row, value=value):
                scores = self.frames["candidate_scores"].copy()
                scores.loc[row, "probability"] = value
                self.assert_error("RFF_PROBABILITY_COVERAGE_INVALID:candidate_scores", candidate_scores=scores)

    def test_probability_outside_unit_interval_is_rejected(self):
        scores = self.frames["candidate_scores"].copy()
        scores.loc[100, "probability"] = 1.01
        self.assert_error("RFF_PROBABILITY_RANGE_INVALID:candidate_scores", candidate_scores=scores)

    def test_saved_top3_probability_must_equal_saved_grid_value(self):
        top3 = self.frames["candidate_top3"].copy()
        top3.iloc[0, top3.columns.get_loc("probability")] = .123
        self.assert_error("RFF_TOP3_GRID_VALUE_MISMATCH:probability", candidate_top3=top3)

    def test_saved_rank_is_checked_against_unselected_grid_rows(self):
        top3 = self.frames["candidate_top3"].copy()
        replacement = self.frames["candidate_scores"].iloc[3]
        for column in self.frames["candidate_scores"].columns:
            top3.iloc[2, top3.columns.get_loc(column)] = replacement[column]
        self.assert_error("RFF_TOP3_RANK_NOT_ORDER_STATISTIC", candidate_top3=top3)

    def test_saved_top3_requires_exact_original_one_third_weight(self):
        top3 = self.frames["candidate_top3"].copy()
        top3["weight"] = "1/2"
        self.assert_error("RFF_TOP3_WEIGHT_CHANGED", candidate_top3=top3)

    def test_full_grid_mask_must_match_truth_by_key(self):
        truth = self.frames["truth"].copy()
        truth.loc[[4, 5], "scoreable"] = [0, 1]
        self.assert_error("RFF_SCOREABLE_FLAGS_DIFFER_BY_KEY:candidate_scores", truth=truth)

    def test_calendar_dates_must_match_the_saved_grid(self):
        calendar = self.frames["calendar"].copy()
        calendar.loc[0, "market_date"] = "2024-01-04"
        self.assert_error("RFF_MARKET_DATE_DIFFERS_FROM_CALENDAR:candidate_scores", calendar=calendar)

    def test_fractional_session_cannot_be_silently_truncated(self):
        calendar = self.frames["calendar"].copy()
        calendar["session_id"] = [10.5, 11.]
        self.assert_error("RFF_SESSION_ID_NOT_INTEGER:calendar", calendar=calendar)

    def test_control_outcome_changes_are_rejected(self):
        controls = copy.deepcopy(self.frames["controls"])
        controls["FROZEN_BASE34"]["scores"].loc[0, "y"] = 0.
        self.assert_error("RFF_FROZEN_CONTROL_OUTCOMES_CHANGED:FROZEN_BASE34", controls=controls)

    def test_control_top3_artifact_changes_are_rejected(self):
        controls = copy.deepcopy(self.frames["controls"])
        controls["FROZEN_BASE34"]["top3"].iloc[0, 3] = .111
        self.assert_error("RFF_FROZEN_CONTROL_TOP3_CHANGED:FROZEN_BASE34", controls=controls)

    def test_episode_denominator_mismatch_stops_evaluation(self):
        contract = dict(self.frames["evaluation_contract"], known_positive_denominator=4)
        self.assert_error("RFF_CONFIRMED_NEW_EPISODE_DENOMINATOR_MISMATCH", evaluation_contract=contract)

    def test_truth_numeric_columns_get_explicit_dtype_diagnostics(self):
        for column in ("y", "first_exact"):
            with self.subTest(column=column):
                truth = self.frames["truth"].copy()
                truth[column] = truth[column].astype(str)
                self.assert_error(f"RFF_TRUTH_NUMERIC_DTYPE_INVALID:{column}", truth=truth)

    def test_first_exact_nan_on_zero_or_unknown_rows_preserves_original_metrics(self):
        # The accepted RFF helper permits missing first_exact.  The frozen arm
        # math does not consume it for y=0 or an unknown y, including saved picks.
        self.frames["truth"]["first_exact"] = self.frames["truth"]["first_exact"].astype(float)
        self.frames["truth"].loc[[1, 2], "first_exact"] = np.nan
        for control in self.frames["controls"].values():
            control["scores"]["first_exact"] = control["scores"]["first_exact"].astype(float)
            control["scores"].loc[[1, 2], "first_exact"] = np.nan
        candidate = self.accepted._join_truth(self.frames["candidate_scores"], self.frames["truth"])
        selected = self.accepted._join_truth(self.frames["candidate_top3"], self.frames["truth"])
        original = self.score_aware.arm_metrics(candidate, selected, self.frames["calendar"],
                                              score_kind=self.score_aware.RAW_RANKING_SCORE,
                                              score_column="ranking_score")
        original["probability"] = self.frozen.probability_metrics(candidate)
        try:
            result = self.evaluate()
        except self.module.RFFSavedEvaluationError as exc:
            self.fail(f"Legacy-valid missing first_exact was rejected: {exc}")
        self.assertEqual(result["arms"]["CANDIDATE_RFF_LOGISTIC"], original)
        for name, control in self.frames["controls"].items():
            expected = self.frozen.arm_metrics(control["scores"], self.frozen.select_top3(control["scores"]),
                                               self.frames["calendar"])
            self.assertEqual(result["arms"][name], expected)
        self.assertTrue(self.frames["truth"].loc[[1, 2], "first_exact"].isna().all())

    def test_practical_exact_003_pass_still_has_direction_only_ceiling(self):
        # Nine additional known hits / 300 fixed slots gives exactly 0.03.
        # This is a synthetic extended calendar, not any real row subset.
        count = 100
        dates = pd.date_range("2024-01-01", periods=count).strftime("%Y-%m-%d").tolist()
        truth = pd.concat([self.frames["truth"].iloc[:6].copy() for _ in range(count)], ignore_index=True)
        truth["session_id"] = np.repeat(np.arange(10, 10 + count), 6)
        truth["market_date"] = np.repeat(dates, 6)
        truth["y"] = 0.
        truth.loc[[6 * i for i in range(9)], "y"] = 1.
        truth["first_exact"] = -1
        truth["label_status"] = "KNOWN"
        truth["episode_state"] = "NONE"
        truth.loc[len(truth) - 6, "episode_state"] = "NEW"
        scores = truth[["code", "session_id", "market_date", "scoreable"]].copy()
        scores["ranking_score"] = np.tile([3., 2., 1., 0., -1., np.nan], count)
        scores["probability"] = 1. / (1. + np.exp(-scores["ranking_score"]))
        picks = scores.loc[np.tile([True, True, True, False, False, False], count)].copy()
        picks["rank"] = np.tile([1, 2, 3], count)
        picks["weight"] = "1/3"
        controls = {}
        for name in self.frames["controls"]:
            control = truth.copy()
            control["probability"] = np.tile([.1, .2, .7, .9, .8, np.nan], count)
            controls[name] = {"scores": control, "top3": self.frozen.select_top3(control)}
        result = self.evaluate(candidate_scores=scores, candidate_top3=picks, truth=truth,
                               calendar=pd.DataFrame({"session_id": range(10, 110), "market_date": dates}),
                               controls=controls,
                               evaluation_contract={"year": 2024, "grid_rows": 600, "scoreable_rows": 500,
                                                    "sessions": 100, "selection_slots": 300,
                                                    "known_positive_denominator": 1})
        self.assertEqual(result["paired_precision"]["FROZEN_BASE34"]["lower"], .03)
        self.assertTrue(result["development_gates"]["all_development_gates_pass"])
        self.assertEqual(result["development_gates"]["development_decision"], "DEVELOPMENT_PASS")
        self.assertEqual(result["evidence_status"], "DIRECTION_ONLY")
        self.assertFalse(result["original_promotion_gates"]["promotion_now"])

    def test_second_control_paired_denominator_is_guarded(self):
        original = self.score_aware.paired_precision
        calls = []
        def corrupt_second_denominator(candidate, control, sessions):
            value = original(candidate, control, sessions)
            calls.append(None)
            if len(calls) == 2:
                value["denominator"] += 3
            return value
        with mock.patch.object(self.score_aware, "paired_precision", side_effect=corrupt_second_denominator):
            self.assert_error("RFF_PAIRED_SLOT_DENOMINATOR_MISMATCH:FROZEN_BASE34")

    def test_threshold_drift_is_rejected(self):
        contract = copy.deepcopy(self.frames["experiment_contract"])
        contract["decision_gates"]["practical_base34"]["value"] = .02
        self.assert_error("RFF_DEVELOPMENT_GATES_CHANGED", experiment_contract=contract)

    def test_no_fit_predict_model_load_claims_or_safety_flags_are_reopened(self):
        result = self.evaluate()
        for field in ("fit_calls", "predict_calls", "control_fit_calls", "control_predict_calls", "calibrator_fit_calls", "model_load_calls"):
            self.assertEqual(result[field], 0)
        self.assertFalse(result["candidate_model_loaded"])
        self.assertEqual(result["safety"], {"research_only": True, "production_allowed": False,
                                            "buy_gate_updated": False, "orders_sent": False})
        self.assertNotIn("evaluation_truth_decodes", result, "Frame layer cannot observe truth reads")


if __name__ == "__main__":
    unittest.main()
