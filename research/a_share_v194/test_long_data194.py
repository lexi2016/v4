"""Targeted pure-fixture tests for the V194 long-history adapter.

All test inputs are synthetic; importing this module never reads the bound panel,
source rows, event artifacts, or any market-data value.
"""
from __future__ import annotations

import importlib.util
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import long_data194 as adapter


KERNEL_PATH = Path(
    "/Users/lexi/Desktop/学习/因子工厂/worktrees/zge_local_selection_20261023/research/"
    "today_selection_20261023/zge_local/broad_recall_v3/formula_kernel.py"
)


def load_kernel():
    spec = importlib.util.spec_from_file_location("long_data194_test_kernel", KERNEL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LongData194Tests(unittest.TestCase):
    def test_checkpoint_loader_uses_unique_registered_hash_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            old_directory = adapter.IMPLEMENTATION_CHECKPOINT_DIR
            adapter.IMPLEMENTATION_CHECKPOINT_DIR = directory
            try:
                expected = {"implementation": "a" * 64, "tests": "b" * 64,
                            "research_code_list": adapter.EXPECTED_CODE_LIST_SHA,
                            "contract": adapter.EXPECTED_CONTRACT_SHA,
                            "start_receipt": adapter.EXPECTED_START_RECEIPT_SHA,
                            "accepted64_manifest": adapter.EXPECTED_ACCEPTED64_SHA}
                stage = "LONG_INPUT_BUILD_IMPLEMENTATION_BINDING_CHECKPOINT_R2"
                old = {key: {"sha256": value} for key, value in expected.items()}
                old["implementation"] = {"sha256": "c" * 64}
                adapter.atomic_json(directory / "LONG_INPUT_BUILD_IMPLEMENTATION_BINDING_CHECKPOINT.json", {
                    "execution_id": adapter.EXECUTION_ID, "stage": "LONG_INPUT_BUILD_IMPLEMENTATION_BINDING_CHECKPOINT",
                    "bindings": old})
                current = {key: {"sha256": value} for key, value in expected.items()}
                checkpoint_path = directory / ("LONG_INPUT_BUILD_IMPLEMENTATION_BINDING_CHECKPOINT_R2.json")
                adapter.atomic_json(checkpoint_path, {"execution_id": adapter.EXECUTION_ID,
                    "stage": stage, "bindings": current})
                adapter.atomic_json(directory / (checkpoint_path.stem + "_REGISTRY_RECEIPT.json"), {
                    "stage": stage, "event_sha256": "d" * 64, "registry_sha256": "e" * 64})

                selected = adapter._check_checkpoint("a" * 64, "b" * 64, adapter.EXPECTED_CODE_LIST_SHA)
                self.assertEqual(selected["path"], str(checkpoint_path))
                self.assertEqual(selected["event_sha256"], "d" * 64)
                self.assertIn("registry_receipt_sha256", selected)
            finally:
                adapter.IMPLEMENTATION_CHECKPOINT_DIR = old_directory

    def test_accepted64_manifest_uses_frozen_input_identity(self):
        contract = {"input_identity": {
            "event_manifest_path": str(adapter.EXPECTED_ACCEPTED64_PATH),
            "event_manifest_sha256": adapter.EXPECTED_ACCEPTED64_SHA,
        }, "frozen_source_bindings": {}}
        self.assertEqual(adapter._accepted64_manifest_path(contract), adapter.EXPECTED_ACCEPTED64_PATH)

        contract["input_identity"]["event_manifest_path"] = str(adapter.EXPECTED_ACCEPTED64_PATH.with_name("OTHER.json"))
        with self.assertRaisesRegex(ValueError, "ACCEPTED64_MANIFEST_PATH_DRIFT"):
            adapter._accepted64_manifest_path(contract)

        contract["input_identity"]["event_manifest_path"] = str(adapter.EXPECTED_ACCEPTED64_PATH)
        contract["input_identity"]["event_manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "ACCEPTED64_SHA_CONTRACT_DRIFT"):
            adapter._accepted64_manifest_path(contract)

    def test_decision_cutoff_is_aware_0925_shanghai(self):
        cutoff = adapter.decision_at("20261022")
        self.assertEqual(cutoff.isoformat(), "2026-10-22T09:25:00+08:00")
        with self.assertRaisesRegex(ValueError, "SOURCE_TIMEZONE_REQUIRED"):
            adapter.parse_aware("2026-10-22T09:24:59")

    def test_formula_natural_survives_unrelated_unknown_technical_flags(self):
        flags = {field: 0 for field in adapter.TECHNICAL}
        flags["tech_192"] = 1
        flags["B1"] = None
        states = {field: "unknown" for field in adapter.SOURCES}
        result = adapter.classify_candidate(flags, states)
        self.assertTrue(result["formula_natural_member"])
        self.assertTrue(result["raw_union_member"])
        self.assertFalse(result["model_complete"])
        self.assertEqual(result["technical_triggers"], ["tech_192"])

    def test_source_nonhit_remains_unknown_and_subject_axis_is_descriptive(self):
        key = ("20261022", "000001.SZ")
        source_axes = {"hits": {}, "axes": {key: {"actual_pool_snapshot_membership": "hit",
            "actual_pool_snapshot_not_decision_complete": "True", "subject_true_topics": "0",
            "subject_false_topics": "1", "subject_unknown_topics": "0", "declared_topics": "1",
            "compatibility_topics": "0"}}, "topics": {key: [{
                "resource_ref_sha256": "a" * 64,
                "raw_publication_reconstruction_state": "hit",
                "research_subject_evidence_qualification": "FALSE_SUBJECT",
            }]}}
        states, axes = adapter._source_row(key[0], key[1], source_axes, "20261021")
        self.assertEqual(states, {lane: "unknown" for lane in adapter.SOURCES})
        self.assertEqual(axes["pool_membership"], "hit")
        self.assertEqual(axes["subject_false_topics"], "1")
        flags = {field: 0 for field in adapter.TECHNICAL}
        result = adapter.classify_candidate(flags, states)
        self.assertFalse(result["raw_union_member"])
        self.assertTrue(result["model_complete"])

    def test_vectorized_brick_matches_bound_prefix_function(self):
        kernel = load_kernel()
        env = kernel.brick_functions()
        close = [20.0 + ((i * 7) % 13) * 0.37 + i * 0.11 for i in range(80)]
        high = [value + 0.5 + (i % 3) * 0.07 for i, value in enumerate(close)]
        low = [value - 0.4 - (i % 5) * 0.03 for i, value in enumerate(close)]
        fast = adapter.brick_value_series(high, low, close)
        bars = [SimpleNamespace(high=h, low=l, close=c) for h, l, c in zip(high, low, close)]
        for index in range(len(close)):
            expected = env["calculate_brick_value"](bars[:index + 1])
            self.assertEqual(fast[index], expected, f"prefix index {index}")
        fanbao = adapter.brick_fanbao_series(high, low, close, [True] * len(close))
        for index in range(13, len(close)):
            expected = int(env["detect_fanbao"](bars[:index + 1]))
            self.assertEqual(fanbao[index], expected, f"fanbao prefix index {index}")

    def test_same_target_anchor_label_applies_event_only_to_signal_close(self):
        dates = ["20261021", "20261022"]
        raw = {field: np.array(values, dtype="float64") for field, values in {
            "open": [10.0, 12.0], "high": [10.5, 12.5], "low": [9.5, 11.5],
            "close": [10.0, 12.0], "volume": [100.0, 120.0], "amount": [1000.0, 1400.0],
        }.items()}
        event = {"date": "20261022", "A": 0.5, "B": 0.0, "G": 2.0}
        ret, target_close, reference_close, _ = adapter._truth_arrays(
            dates, raw, [event], [], [("20261021", "20261022")])
        self.assertEqual(reference_close[0], 5.0)
        self.assertEqual(target_close[0], 12.0)
        self.assertAlmostEqual(ret[0], 1.4)

    def test_unsupported_event_keeps_label_unknown(self):
        dates = ["20261021", "20261022"]
        raw = {field: np.array([10.0, 12.0], dtype="float64") for field in adapter.RAW_FIELDS}
        ret, _, _, _ = adapter._truth_arrays(
            dates, raw, [], ["20261022"], [("20261021", "20261022")])
        self.assertTrue(math.isnan(float(ret[0])))

    def test_npz_checkpoint_bytes_are_deterministic(self):
        arrays = {"dates": np.array([20261021, 20261022], dtype="int32"),
                  "volume": np.array([16777217.0, 16777218.0], dtype="float32")}
        self.assertEqual(adapter._npz_bytes(arrays), adapter._npz_bytes(arrays))

    def test_projection_consumers_read_authoritative_shard_checkpoints(self):
        identity = {"synthetic": True}
        identity_sha = adapter.canonical_sha(identity)
        codes = [f"{i:06d}.SZ" for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for index, code in enumerate(codes):
                adapter._write_code_checkpoint(adapter._projection_code_dir(directory, index),
                    {"code": code, "identity_sha256": identity_sha},
                    {"technical_complete": np.array([1], dtype="uint8")})
            details, _ = adapter._load_all_details(directory, codes, identity)
            self.assertEqual([item["code"] for item in details], codes)
            self.assertEqual(adapter._projection_code_dir(directory, 8),
                             directory / "shards/shard_00/per_code")

    def test_panel_schema_rejects_rounding_or_wide_numeric_types(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.parquet"
            table = pa.table({"ts_code": pa.array(["000001.SZ"], type=pa.string()),
                "trade_date": pa.array([20261022], type=pa.int32()),
                "open": pa.array([10.0], type=pa.float32()), "high": pa.array([11.0], type=pa.float32()),
                "low": pa.array([9.0], type=pa.float32()), "close": pa.array([10.5], type=pa.float32()),
                "vol": pa.array([16777217.0], type=pa.float32()),
                "amount": pa.array([123456789.0], type=pa.float32())})
            pq.write_table(table, path)
            types = adapter.validate_panel_schema(path)
            self.assertEqual(types["vol"], "float")
            self.assertEqual(types["amount"], "float")
            # The shared panel has derived columns; they are outside this adapter's projection.
            extra = table.append_column("pre_close", pa.array([999.0], type=pa.float64()))
            pq.write_table(extra, path)
            self.assertEqual(adapter.validate_panel_schema(path), types)
            pq.write_table(extra.drop(["close"]), path)
            with self.assertRaisesRegex(ValueError, "PANEL_SCHEMA_COLUMNS_DRIFT"):
                adapter.validate_panel_schema(path)
            wrong = pa.table({"ts_code": pa.array(["000001.SZ"], type=pa.string()),
                "trade_date": pa.array([20261022], type=pa.int32()),
                "open": pa.array([10.0], type=pa.float64()), "high": pa.array([11.0], type=pa.float32()),
                "low": pa.array([9.0], type=pa.float32()), "close": pa.array([10.5], type=pa.float32()),
                "vol": pa.array([100.0], type=pa.float32()), "amount": pa.array([100.0], type=pa.float32())})
            pq.write_table(wrong, path)
            with self.assertRaisesRegex(ValueError, "PANEL_FLOAT32_REQUIRED:open"):
                adapter.validate_panel_schema(path)


if __name__ == "__main__":
    unittest.main()
