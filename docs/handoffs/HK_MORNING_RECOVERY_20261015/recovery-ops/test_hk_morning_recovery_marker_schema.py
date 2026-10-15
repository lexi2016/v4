#!/usr/bin/env python3
"""Regression check for the actual StageCenter after-fact marker field contract."""
from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


WRITER_ROOT = Path(__file__).resolve().parent
ONE_SHOT_PATH = WRITER_ROOT / "run_hk_morning_cached_recovery_once.py"
ACTUAL_0935_MANIFEST = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection/"
    "backfill/e48db9ca382944b3994e6f31efb4f329/selection_runs/20261015/"
    "HK_CONNECT_SELECTION_STAGE_0930_0935/run-9a03b73fd509be2260c8981c/manifest.json"
)


def _load_one_shot_module():
    spec = importlib.util.spec_from_file_location("hk_morning_one_shot", ONE_SHOT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the frozen one-shot candidate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ONE_SHOT = _load_one_shot_module()


class MarkerSchemaRegressionTest(unittest.TestCase):
    def test_actual_0935_envelope_passes_with_markers_in_their_real_fields(self):
        import json

        manifest = json.loads(ACTUAL_0935_MANIFEST.read_text(encoding="utf-8"))
        envelope = manifest["selection_envelope"]
        self.assertEqual(envelope["run_id"], "run-9a03b73fd509be2260c8981c")
        self.assertEqual(envelope["formal_eligible"], False)
        self.assertIn("HK_HISTORICAL_ORDERBOOK_UNAVAILABLE", envelope["cannot_confirm"])
        self.assertIn("formal_pit=false", envelope["source_evidence"])
        self.assertIn("formal_stage_eligibility=CANNOT_CONFIRM", envelope["source_evidence"])
        self.assertIn("natural_time_capture=CANNOT_CONFIRM", envelope["source_evidence"])

        # Reproduce the old false alarm: PIT/eligibility markers are source evidence,
        # while cannot_confirm contains the named historical uncertainty reasons.
        old_misfiled_markers = {
            "formal_pit=false",
            "formal_stage_eligibility=CANNOT_CONFIRM",
            "natural_time_capture=CANNOT_CONFIRM",
            "HK_HISTORICAL_ORDERBOOK_UNAVAILABLE",
        }
        self.assertFalse(old_misfiled_markers.issubset(set(envelope["cannot_confirm"])))
        ONE_SHOT._assert_afterfact_marker_contract(envelope, "STAGE_0930_0935")

    def test_missing_uncertainty_marker_still_fails_closed(self):
        import json

        manifest = json.loads(ACTUAL_0935_MANIFEST.read_text(encoding="utf-8"))
        envelope = copy.deepcopy(manifest["selection_envelope"])
        envelope["cannot_confirm"].remove("HK_HISTORICAL_ORDERBOOK_UNAVAILABLE")
        with self.assertRaisesRegex(RuntimeError, "missing_cannot_confirm=.*HK_HISTORICAL_ORDERBOOK_UNAVAILABLE"):
            ONE_SHOT._assert_afterfact_marker_contract(envelope, "STAGE_0930_0935")

    def test_missing_pit_source_evidence_still_fails_closed(self):
        import json

        manifest = json.loads(ACTUAL_0935_MANIFEST.read_text(encoding="utf-8"))
        envelope = copy.deepcopy(manifest["selection_envelope"])
        envelope["source_evidence"].remove("formal_pit=false")
        with self.assertRaisesRegex(RuntimeError, "missing_source_evidence=.*formal_pit=false"):
            ONE_SHOT._assert_afterfact_marker_contract(envelope, "STAGE_0930_0935")


if __name__ == "__main__":
    unittest.main(verbosity=2)
