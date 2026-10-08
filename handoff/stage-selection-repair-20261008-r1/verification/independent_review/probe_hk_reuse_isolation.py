"""Synthetic probe of stale HK reuse versus preservation of valid A lanes."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUTPUT = Path(os.environ.get("ISSUE28_REVIEW_PROBE_OUTPUT", HERE))
HK = ROOT / "delivery/hk"
os.environ.update(
    HK_OWNER_ROOT=os.environ.get("ISSUE28_REVIEW_HK_OWNER", str(HERE / "initial_candidate/hk/after/active_producer_reference")),
    HK_BEFORE_OWNER_ROOT=str(HK / "before/active_producer_reference"),
    HK_SUPPORT_ROOT=str(HK / "support/canonical"),
    HK_FROZEN_ROOT=str(HK / "support/frozen"),
)
spec = importlib.util.spec_from_file_location("independent_hk_support", HERE / "initial_candidate/hk/tests/test_hk_split_date_binding.py")
common = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = common
spec.loader.exec_module(common)

with tempfile.TemporaryDirectory(prefix="hk-reuse-isolation-", dir=Path(__file__).parent) as directory:
    root = Path(directory)
    monkeypatch = pytest.MonkeyPatch()
    try:
        a_calls = common.isolated_a_lanes.__wrapped__(monkeypatch)
        common._synthetic_source(root / "source")
        verified = common._build(root / "source")
        stale = copy.deepcopy(verified)
        stale.pop("historical_provenance")
        scenarios = []
        for reuse in (None, {"hkconnect_d1_top100": stale}):
            try:
                artifacts = common.scheduled.build_scheduled_artifacts(
                    **common._scheduled_arguments(root, reuse=reuse)
                )
            except Exception as error:
                scenarios.append({
                    "stale_hk_reuse": reuse is not None,
                    "returned_artifacts": False,
                    "error": type(error).__name__ + ": " + str(error),
                    "a_adapter_was_executed": bool(a_calls),
                    "materialize_preselection_date_reachable": False,
                })
            else:
                a = next(item for item in artifacts if item["pool_id"] == "a_d1_premarket_pool")
                scenarios.append({
                    "stale_hk_reuse": reuse is not None,
                    "returned_artifacts": True,
                    "a_status": a["status"],
                    "a_rows": len(a["rows"]),
                    "a_stage_selection_eligible": a["stage_selection_eligible"],
                })
        report = {"scenarios": scenarios, "all_data_synthetic": True, "service_calls": 0}
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "PROBE_HK_REUSE_ISOLATION.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        monkeypatch.undo()
