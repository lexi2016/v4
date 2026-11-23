"""ACT023 safety regressions; estimators below are synthetic, never sklearn FIT."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ops import pft_act023_s_v3 as study


class MockEstimator:
    fits = 0

    def __init__(self, name):
        self.classes_ = np.arange(2 if name.endswith("binary") else 4)

    def fit(self, x, y):
        type(self).fits += 1
        return self

    def predict_proba(self, x):
        return np.full((len(x), len(self.classes_)), 1/len(self.classes_))


class ControlledStudyTests(unittest.TestCase):
    def test_exact_sparse_transform_and_causal_hierarchy(self):
        result = study.self_test()
        self.assertEqual(result["status"], "PASS_SYNTHETIC_ONLY")
        self.assertEqual(result["actual_fit"]["S"], 0)

    def test_four_mock_fits_checkpoint_and_reuse_without_refit(self):
        MockEstimator.fits = 0
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output/"prepared.json").write_text("{}")
            train = pd.DataFrame({"tactic": study.old.CLASSES, "s_label": ["TRUE"]*3+["FALSE"]})
            arrays = {"train_structure": np.zeros((4, 3)), "train_mr": np.ones((4, 2))}
            _, ledger = study.fit_models(train, arrays, output, factory=MockEstimator)
            self.assertEqual(MockEstimator.fits, 4)
            self.assertEqual((ledger["S"], ledger["B"]), (4, 0))
            self.assertEqual([e["event"] for e in ledger["events"]].count("FIT_COMPLETE_CHECKPOINTED"), 4)
            self.assertTrue(all(r["state"] == "COMPLETE" for r in ledger["models"].values()))
            with patch.object(MockEstimator, "fit", side_effect=AssertionError("MUST_REUSE")):
                _, replay = study.fit_models(train, arrays, output, factory=MockEstimator)
            self.assertEqual(replay, ledger)
            ledger["models"][study.MODELS[0]]["state"] = "RESERVED"
            (output/"fit_ledger.json").write_text(json.dumps(ledger))
            with self.assertRaisesRegex(study.ContractError, "UNCERTAIN_FIT_DO_NOT_REPEAT"):
                study.fit_models(train, arrays, output, factory=MockEstimator)
            self.assertEqual(MockEstimator.fits, 4)

    def test_strict_g1_survives_missing_context_and_raw_archive_survives(self):
        keys = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20261120"]})
        evidence = [{"status": "MISSING_65_VALID_CAUSAL_BARS", "white": 9., "yellow": 10.}]
        archived = {"000001.SZ/20261120": {"probabilities": [.99,.7,.1,.1,.1], "linkage": "ARCHIVED", "source_sha256": "a"*64}}
        with patch.object(study.old, "load_weight", return_value=None):
            result = study.predict_external({}, Path("/unused"), {}, keys, evidence, archived).iloc[0]
        self.assertEqual(result.baseline_raw_p_s, .99)
        for arm in ("baseline", *study.ARMS):
            self.assertEqual(result[f"{arm}_final_state"], "REJECTED_FAKE")
            self.assertEqual(result[f"{arm}_decision_reason"], "STRICT_OBSERVED_W_BELOW_Y")

    def test_identity_runner_rejects_truth_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"identities.csv"
            path.write_text("cohort,case_id,ts_code,trade_date,truth_state\nGOLD40,x,000001.SZ,20261120,CONFIRMED_S\n")
            with self.assertRaisesRegex(study.ContractError, "IDENTITY_ONLY_INPUT_REQUIRED"):
                study.read_identities(path)

    def test_reader_normalizes_observed_dictionary_values_only(self):
        import pyarrow as pa
        from ops.research_panel_logical import parquet
        raw = pd.DataFrame({"ts_code": pd.Categorical(["000001.SZ"], categories=["000001.SZ", "00001.HK"]),
                            "trade_date": ["20260831"],
                            "market_type": ["A_SHARE"], "open": [10.], "high": [11.], "low": [9.], "close": [10.],
                            "vol": [100.], "zge_white_line": [10.], "zge_yellow_line": [9.]})
        table = pa.Table.from_pandas(raw, preserve_index=False)
        targets = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260831"]})
        with patch.object(parquet, "read_schema", return_value=table.schema), patch.object(parquet, "read_table", return_value=table):
            result = study.read_targets(Path("/unused"), targets)
        self.assertEqual(result.ts_code.tolist(), ["000001.SZ"])
        self.assertEqual(result.trade_date.tolist(), ["20260831"])
        self.assertTrue(all(pd.api.types.is_numeric_dtype(result[k]) for k in study.old.INPUTS[3:]))

    def test_training_audit_gzip_is_deterministic_readable_json(self):
        import gzip
        value = [{"status":"READY", "missing":None, "anchors":{"events":[{"date":"20260831"}]}}]
        with tempfile.TemporaryDirectory() as folder:
            a,b = Path(folder)/"a.json.gz",Path(folder)/"b.json.gz"
            study.write_json_gzip(a,value)
            study.write_json_gzip(b,value)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            with gzip.open(a,"rt") as stream:
                self.assertEqual(json.load(stream),value)

    def test_prepared_source_recheck_canonicalizes_tuple_stats_only(self):
        live = {"source":{"generation_manifest_stat":(1,2,3)}}
        receipt = {"files":{},"source":study.review.clean(live),
                   "external_bindings":[{"day":"20261120","panel_path":"/gold","binding":study.review.clean(live)}]}
        plan = {"code_sha256":"pin","groups_sha256":"pin","external_identities_sha256":"pin","baseline":{},
                "baseline_reveal":{"path":"/reveal","sha256":"pin"},"transform_source_sha256":"pin",
                "act020_source_sha256":"pin","act021_source_sha256":"pin"}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output/"prepared.json").write_text(json.dumps(receipt))
            (output/"frozen_plan.json").write_text(json.dumps(plan))
            with patch.object(study,"sha",return_value="pin"), patch.object(study,"baseline_manifest",return_value={}), \
                    patch.object(study,"bind_training_panel",return_value=(Path('/train'),live)) as train_bind, \
                    patch.object(study.review,"load_groups",return_value=([{"decision_date":"20261120","panel_path":"/gold"}],{})), \
                    patch.object(study.review,"bind_panel",return_value=(Path('/gold'),live)) as gold_bind:
                self.assertEqual(study.verify_prepared(Path('/baseline'),Path('/groups'),Path('/ids'),output),receipt)
                changed = {"source":{"generation_manifest_stat":(1,2,4)}}
                train_bind.return_value = (Path('/train'),changed)
                with self.assertRaisesRegex(study.ContractError,"PREPARED_PINNED_SOURCE_CHANGED"):
                    study.verify_prepared(Path('/baseline'),Path('/groups'),Path('/ids'),output)
                train_bind.return_value = (Path('/train'),live)
                gold_bind.return_value = (Path('/gold'),changed)
                with self.assertRaisesRegex(study.ContractError,"PREPARED_EXTERNAL_SOURCE_CHANGED"):
                    study.verify_prepared(Path('/baseline'),Path('/groups'),Path('/ids'),output)


if __name__ == "__main__":
    unittest.main()
