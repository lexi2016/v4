"""Fixed ACT024 routing regressions; synthetic inference only, never fit."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ops import pft_act024_s_v3_router as study


def evidence(**changes):
    return {"status": "READY", "white": 110., "yellow": 100., "yellow_extension": .2, **changes}


class FrozenEstimator:
    """No fit method exists; only the named structure heads can be loaded."""
    n_features_in_ = 43

    def __init__(self, binary):
        self.classes_ = np.arange(2 if binary else 4)

    def predict_proba(self, x):
        return np.full((len(x), len(self.classes_)), 1/len(self.classes_))


class RouterTests(unittest.TestCase):
    def test_strict_positive_finite_g1_overrides_missing_context_and_scores(self):
        r = study.route(None, None, evidence(status="MISSING_65_VALID_CAUSAL_BARS", white=99., yellow_extension=None))
        self.assertEqual((r["final_state"], r["main_tactic"]), ("REJECTED_FAKE", "invalid_fake"))
        self.assertEqual(r["route_reasons"], "STRICT_OBSERVED_W_BELOW_Y")
        self.assertIsNone(r["projected_p_s"])
        # Scores stay visible even though G1 has priority over every other rule.
        r = study.route(.99, [.01, .01, .01, .97], evidence(white=99., yellow_extension=.7))
        self.assertEqual(r["raw_p_s"], .99)
        self.assertEqual(r["projected_p_fake"], .97)
        self.assertEqual(r["route_reasons"], "STRICT_OBSERVED_W_BELOW_Y")

    def test_equality_missing_nonfinite_and_nonpositive_lines_are_not_g1(self):
        for white,yellow in [(100., 100.), (None, 100.), (float("nan"), 100.),
                             (float("inf"), 100.), (-1., 100.), (0., 100.), (1., 0.), (True, 100.)]:
            with self.subTest(white=white, yellow=yellow):
                r = study.route(.9, [.8, .05, .05, .1], evidence(white=white, yellow=yellow))
                self.assertFalse(r["strict_g1_failure"])
                self.assertEqual((r["final_state"], r["main_tactic"]), ("UNKNOWN_BORDERLINE", ""))

    def test_extension_and_spread_exact_comparison_boundaries(self):
        p = [.8, .05, .05, .1]
        for extension,state in [(.35, "CONFIRMED_S"), (np.nextafter(.35, 1.), "UNKNOWN_BORDERLINE")]:
            r = study.route(.9, p, evidence(yellow_extension=extension))
            self.assertEqual(r["final_state"], state)
        # 3/200 is exactly the same float as the fixed .015 threshold.
        r = study.route(.9, p, evidence(white=203., yellow=200.))
        self.assertEqual(r["line_spread"], .015)
        self.assertEqual(r["final_state"], "CONFIRMED_S")
        r = study.route(.9, p, evidence(white=np.nextafter(203., 0.), yellow=200.))
        self.assertEqual(r["final_state"], "UNKNOWN_BORDERLINE")
        self.assertIn("LINE_SPREAD_LT_0015", r["route_reasons"])

    def test_grey_band_is_left_closed_right_open_and_projected(self):
        for root,children,grey,state in [
            (.35, [.2, .1, .1, .6], True, "UNKNOWN_BORDERLINE"),
            (np.nextafter(.35, 0.), [.2, .1, .1, .6], False, "REJECTED_FAKE"),
            (.65, [.6, .1, .1, .2], False, "CONFIRMED_S"),
            (np.nextafter(.65, 0.), [.6, .1, .1, .2], True, "UNKNOWN_BORDERLINE"),
            (.3, [.7, .1, .1, .1], False, "UNKNOWN_BORDERLINE"),
        ]:
            with self.subTest(root=root):
                r = study.route(root, children, evidence())
                self.assertEqual("PROJECTED_S_GREY_035_065" in r["route_reasons"], grey)
                self.assertEqual(r["final_state"], state)
                self.assertEqual(r["projected_p_s"], max(root, max(children[:3])))

    def test_raw_heads_and_deduplicated_strong_reason(self):
        r = study.route(.70, [.2, .2, .1, .5], evidence(yellow_extension=.4, white=100., yellow=100.))
        self.assertEqual(r["final_state"], "UNKNOWN_BORDERLINE")
        self.assertEqual(r["route_reasons"].split(";"), [
            "YELLOW_EXTENSION_GT_035", "LINE_SPREAD_LT_0015", "RAW_HEAD_DECISION_CONTRADICTION",
            "STRONG_BINARY_FAKE_HEAD_CONTRADICTION"])
        r = study.route(np.nextafter(.7, 0.), [.2, .2, .1, .5], evidence())
        self.assertNotIn("STRONG_BINARY", r["route_reasons"])
        # Positive first-index tie obeys ACT023 numpy argmax semantics.
        r = study.route(.9, [.5, 0., 0., .5], evidence())
        self.assertTrue(r["raw_decision_contradiction"] is False)
        self.assertIn("STRONG_BINARY", r["route_reasons"])

    def test_fail_safe_missing_inputs_never_become_definite_tactic(self):
        for root,p,e in [(None, None, evidence()), (.9, [.8,.1,.1], evidence()),
                         (.9, [.8,.1,.1,float("nan")], evidence()),
                         (.9, [.8,.05,.05,.1], evidence(yellow_extension=None)),
                         (.9, [.8,.05,.05,.1], evidence(status="MISSING_CAUSAL_CONTEXT"))]:
            r = study.route(root, p, e)
            self.assertEqual((r["final_state"], r["main_tactic"]), ("UNKNOWN_BORDERLINE", ""))

    def test_outside_abstentions_retains_original_coherent_state_and_tactic(self):
        for root,p,state,tactic in [(.9, [.8,.05,.05,.1], "CONFIRMED_S", "pullback"),
                                   (.9, [.1,.75,.05,.1], "CONFIRMED_S", "readvance"),
                                   (.9, [.05,.1,.75,.1], "CONFIRMED_S", "rebuild"),
                                   (.2, [.1,.1,.1,.7], "REJECTED_FAKE", "invalid_fake"),
                                   (.9, [.4,.3,.2,.1], "UNKNOWN_BORDERLINE", "")]:
            r = study.route(root, p, evidence())
            self.assertEqual((r["final_state"], r["main_tactic"]), (state, tactic))
            self.assertEqual(r["base_final_state"], state)
            self.assertEqual(r["base_main_tactic"], tactic)

    def test_hierarchy_monotonicity_and_no_identity_specific_behavior(self):
        random = np.random.default_rng(24)
        for _ in range(200):
            root, p = random.random(), random.dirichlet(np.ones(4))
            e = evidence()
            a = study.route(root, p, {**e, "ts_code": "600256.SH"})
            b = study.route(root, p, {**e, "ts_code": "605577.SH"})
            self.assertEqual(a, b)
            self.assertGreaterEqual(a["projected_p_s"], max(p[:3]))
            self.assertFalse(a["final_hierarchy_contradiction"])
            self.assertFalse(a["final_decision_contradiction"])
            if a["final_state"] == "CONFIRMED_S":
                self.assertEqual(a["base_final_state"], "CONFIRMED_S")
            if a["final_state"] == "UNKNOWN_BORDERLINE":
                self.assertEqual(a["main_tactic"], "")

    def test_only_structure_weights_and_named_structure_array_are_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            models = {name: FrozenEstimator(name.endswith("binary")) for name in study.WEIGHTS}
            x = np.zeros((4000, 43))
            ledger = {"S": 4, "B": 0, "tuning": 0, "transform_fit": 0, "config": study.old.HGB_CONFIG,
                      "models": {name: {"state": "COMPLETE"} for name in study.act023.MODELS}}
            for name,model in models.items():
                ledger["models"][name].update(weight_sha256=study.WEIGHTS[name], features=43, rows=4000,
                    classes=model.classes_.tolist(), replay_sha256=hashlib.sha256(model.predict_proba(x[:128]).tobytes()).hexdigest())
            plan = {"features": list(study.act023.STRUCT_FEATURES), "class_order": list(study.old.CLASSES),
                    "cutoff": "20260831", "code_sha256": study.SOURCE_SHA, "groups_sha256": study.GROUPS_SHA,
                    "hgb_config": study.old.HGB_CONFIG, "act020_source_sha256": "a", "act021_source_sha256": "b"}
            files = {name: "a" for name in ("features.npz", "external_keys.csv", "external_evidence.json", "training_membership.csv")}
            for name,value in [("frozen_plan.json", plan), ("prepared.json", {"files": files}), ("fit_ledger.json", ledger)]:
                (path/name).write_text(json.dumps(value))
            np.savez(path/"features.npz", train_structure=x)  # No MR member.
            with patch.object(study, "checked", side_effect=lambda p,h: p), \
                    patch.object(study.old, "load_weight", side_effect=lambda p: models[p.stem]) as load:
                loaded,identity = study.load_frozen(path)
                self.assertEqual(set(loaded), {"binary", "tactic"})
                self.assertEqual([c.args[0].stem for c in load.call_args_list], list(study.WEIGHTS))
                self.assertIn("PASS", identity["training_replay"])

    def test_exact_65_bar_readiness_without_retired_transform(self):
        def raw(n):
            return pd.DataFrame({"ts_code": ["000001.SZ"]*n,
                                 "trade_date": pd.date_range(end="2026-11-20", periods=n).strftime("%Y%m%d"),
                                 "zge_white_line": [110.]*n, "zge_yellow_line": [100.]*n})
        shape = pd.DataFrame([{"ts_code": "000001.SZ", "feature_ready": True}])
        with patch.object(study.old, "causal_shapes", return_value=shape), \
                patch.object(study.review, "valid_bar", return_value=True) as valid, \
                patch.object(study.act023, "structural_features", return_value=(np.zeros(43), evidence())) as features, \
                patch.object(study.act023, "extract", side_effect=AssertionError("MR_EXTRACT_FORBIDDEN")), \
                patch.object(study.act023, "sparse_transform", side_effect=AssertionError("MR_FORBIDDEN")):
            _, missing = study.extract_structure(raw(64), "20261120", ["000001.SZ"])
            self.assertEqual(missing[0]["status"], "MISSING_65_VALID_CAUSAL_BARS")
            features.assert_not_called()
            x, ready = study.extract_structure(raw(65), "20261120", ["000001.SZ"])
            self.assertEqual((x.shape, ready[0]["status"], ready[0]["causal_bars"]), ((1,43), "READY", 65))
            features.assert_called_once()
            valid.return_value = False
            _, invalid = study.extract_structure(raw(65), "20261120", ["000001.SZ"])
            self.assertEqual(invalid[0]["status"], "MISSING_65_VALID_CAUSAL_BARS")

    def test_recall_reports_unknowns_and_rejection_separately(self):
        frame = pd.DataFrame({"cohort": ["SYNTHETIC"]*5,
                              "truth_state": ["CONFIRMED_S"]*3+["REJECTED_FAKE", "UNKNOWN_BORDERLINE"]})
        states = ["CONFIRMED_S", "UNKNOWN_BORDERLINE", "REJECTED_FAKE", "CONFIRMED_S", "UNKNOWN_BORDERLINE"]
        for arm in ("baseline", "structure_ch", "act024"):
            frame[f"{arm}_final_state"] = states
        m = study.external_metrics(frame)["ALL"]["arms"]["act024"]
        self.assertEqual((m["known_positive_n"], m["true_positive_n"], m["positive_abstained_n"], m["false_reject_n"]), (3,1,1,1))
        self.assertEqual(m["confirmed_s_recall"], 1/3)
        self.assertEqual(m["nonrejected_positive_recall_upper_bound"], 2/3)
        self.assertEqual((m["false_accept_n"], m["known_fake_n"], m["boundary_abstained_n"]), (1,1,1))
        self.assertEqual(m["rejection_rate"], 1/5)


if __name__ == "__main__":
    unittest.main()
