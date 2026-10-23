"""Synthetic engineering checks. No historical market data or real-model fit."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import model194 as m


def fixture():
    config = dict(technical_features=["technical"], pool_flags=["pool_a", "pool_b"],
                  source_flags=["source_a", "source_b"], top_n=50, seed=194,
                  splits=[dict(id="fold1", kind="oof", train_end="2026-01-04",
                               eval_start="2026-01-05", eval_end="2026-01-06",
                               truth_asof="2026-01-07", evaluation_dates=["2026-01-05", "2026-01-06"])])
    rows = []
    for d in (1, 2, 3, 4, 5):
        for i in range(4):
            rows.append(dict(signal_date=f"2026-01-{d:02}", code=f"SYNTH{i}",
                             signal_at=f"2026-01-{d:02}T16:00:00+08:00",
                             available_at=f"2026-01-{d:02}T15:00:00+08:00",
                             label_end_date=f"2026-01-{d+1:02}", label=i % 2,
                             technical=float(i+d), pool_a=i % 2, pool_b=i % 2,
                             source_a=i % 2, source_b=i % 2))
    manifest = dict(dataset_kind="SYNTHETIC_FIXTURE",
                    truth_positive_counts={"2026-01-05":100, "2026-01-06":100}, **m.FLAGS)
    return config, manifest, rows


class EngineeringTests(unittest.TestCase):
    def test_unknown_not_zero(self):
        c, manifest, rows = fixture()
        for unknown in (None, "", "NaN", "unknown"):
            changed = copy.deepcopy(rows)
            changed[0]["source_a"] = unknown
            with self.assertRaises(ValueError):
                m.validate_rows(changed, c, manifest, synthetic=True)

    def test_real_fit_rejects_unconfirmed_manifest(self):
        c, manifest, rows = fixture()
        with self.assertRaisesRegex(ValueError, "PRODUCER_REQUIRED"):
            m.validate_rows(rows, c, manifest)
        manifest["dataset_kind"] = "SHARED_PRODUCER_DERIVED_VIEW"
        with self.assertRaisesRegex(ValueError, "CANNOT_CONFIRM:lineage_review_pass"):
            m.validate_rows(rows, c, manifest)

    def test_late_availability_and_duplicate_rejected(self):
        c, manifest, rows = fixture()
        changed = copy.deepcopy(rows)
        changed[0]["available_at"] = "2026-01-01T16:00:01+08:00"
        with self.assertRaisesRegex(ValueError, "FEATURE_AVAILABLE_AFTER_SIGNAL"):
            m.validate_rows(changed, c, manifest, synthetic=True)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_DATE_CODE"):
            m.validate_rows(rows+[rows[0]], c, manifest, synthetic=True)

    def test_purge_and_maturity(self):
        c, _, rows = fixture()
        train, evaluation = m.split_rows(rows, c["splits"][0])
        self.assertEqual(max(r["signal_date"] for r in train), "2026-01-03")
        split = dict(c["splits"][0], truth_asof="2026-01-05")
        with self.assertRaisesRegex(ValueError, "EVAL_LABEL_IMMATURE"):
            m.split_rows(rows, split)
        split = dict(c["splits"][0], train_end="2026-01-05")
        with self.assertRaisesRegex(ValueError, "CHRONOLOGICAL_SPLIT_REQUIRED"):
            m.split_rows(rows, split)

    def test_exposed_dates_diagnostic_only(self):
        c, _, rows = fixture()
        changed = copy.deepcopy(rows)
        for row in changed:
            if row["signal_date"] == "2026-01-05":
                row.update(signal_date="2026-10-16", label_end_date="2026-10-19")
        split = dict(c["splits"][0], eval_start="2026-10-16", eval_end="2026-10-16", truth_asof="2026-10-19")
        with self.assertRaisesRegex(ValueError, "EXPOSED_DATE_DIAGNOSTIC_ONLY"):
            m.split_rows(changed, split)
        m.split_rows(changed, dict(split, kind="diagnostic"))

    def test_pool_count_does_not_imply_independent_origins(self):
        c, _, rows = fixture()
        self.assertNotIn("independent_origin_count", m.feature_names(c, "candidate"))
        c.update(independent_origin_groups={"source_a":"one", "source_b":"one"})
        with self.assertRaisesRegex(ValueError, "ORIGIN_INDEPENDENCE_UNKNOWN"):
            m.feature_values(rows[1], c, "candidate")
        c["origin_independence_bound"] = True
        self.assertEqual(m.feature_values(rows[1], c, "candidate")[-1], 1)

    def test_fixed_slots_no_fill_and_tie_order(self):
        _, _, rows = fixture()
        evaluation = [r for r in rows if r["signal_date"] == "2026-01-05"]
        picks = m.top50([dict(signal_date=r["signal_date"], code=r["code"], score=.5) for r in reversed(evaluation)])
        self.assertEqual([r["code"] for r in picks], sorted(r["code"] for r in evaluation))
        metrics = m.metrics(picks, evaluation, {"2026-01-05":100, "2026-01-06":100})
        self.assertEqual((metrics["actual_selected"], metrics["selection_slots"], metrics["truth_positive_denominator"]), (4,100,200))

    def test_all_dependencies_checked_before_fit(self):
        c, manifest, rows = fixture()
        manifest["truth_positive_counts"].pop("2026-01-06")
        before = dict(m.FIT_COUNTS)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(KeyError):
                m.train_run(c, manifest, rows, Path(tmp)/"run", synthetic=True)
        self.assertEqual(before, m.FIT_COUNTS)

    def test_json_roundtrip_and_train_only_scaler(self):
        c, manifest, rows = fixture()
        evaluation = [r for r in rows if r["signal_date"] == "2026-01-05"]
        for row in evaluation:
            row["technical"] = 1e6
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/"run"
            before = dict(m.FIT_COUNTS)
            result = m.train_run(c, manifest, rows, out, synthetic=True)
            model = m.load(out/"fold1/baseline_model.json")
            self.assertEqual(model["mean"], [3.5])
            self.assertEqual(m.predict(model, evaluation), m.predict(json.loads(json.dumps(model)), evaluation))
            self.assertEqual(result["status"], "ENGINEERING_CANARY_ONLY")
            self.assertEqual(result["fit_counts"]["synthetic_fit_returned"]-before["synthetic_fit_returned"], 2)
            self.assertEqual(result["fit_counts"]["real_fit_entered"], 0)
            self.assertEqual(result["results"][0]["metrics"]["selection_slots"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
