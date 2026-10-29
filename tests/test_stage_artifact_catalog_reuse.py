from pathlib import Path
import re
from types import SimpleNamespace
from typing import Mapping

from domains._preselection_parts.date_catalog import __verified_stage_artifact_catalog_body


def catalog_for(entries, results):
    calls = []

    class SelectionError(Exception):
        pass

    class SelectionStore:
        def __init__(self, root):
            self.root = root

        def _latest(self):
            return {"entries": entries}

        def read_verified(self, date, stage, market):
            key = f"{date}/{stage}/{market}"
            calls.append(key)
            result = results[key]
            if isinstance(result, Exception):
                raise result
            return result

    scope = {
        "Path": Path,
        "re": re,
        "Mapping": Mapping,
        "SelectionStore": SelectionStore,
        "SelectionError": SelectionError,
        "STAGE_BY_ID": {
            "S1": SimpleNamespace(markets=("A", "HK")),
            "S2": SimpleNamespace(markets=("A",)),
            "STAGE_0925": SimpleNamespace(markets=("A", "HK")),
        },
    }
    return __verified_stage_artifact_catalog_body(scope, Path("/unused")), calls


def test_original_three_entry_fixture_preserves_materialized_and_blocked_dates():
    entries = {
        "20261028/STAGE_0925/A": {"run_id": "fixture-a"},
        "20261028/STAGE_0925/HK": {"run_id": "fixture-hk"},
        "20261029/STAGE_0925/A": {"run_id": "fixture-invalid"},
    }
    results = {
        key: ({"artifact_id": key, "selection_status": "READY", "cannot_confirm": []}
              if key.startswith("20261028/") else ValueError("controlled-invalid-entry"))
        for key in entries
    }
    catalog, calls = catalog_for(entries, results)
    assert calls == list(entries)
    assert catalog["20261028"]["status"] == "MATERIALIZED"
    assert catalog["20261029"]["status"] == "BLOCKED"
    assert catalog["20261029"]["missing_markets"] == ["STAGE_0925:A", "STAGE_0925:HK"]


def test_three_known_entries_are_verified_once_and_preserve_partial_evidence():
    entries = {
        "20261029/S1/A": {"run_id": "run-a"},
        "20261029/S1/HK": {"run_id": "run-hk"},
        "20261029/S2/A": {"run_id": "run-s2"},
    }
    results = {
        "20261029/S1/A": {"artifact_id": "a", "selection_status": "READY"},
        "20261029/S1/HK": {"artifact_id": "hk", "selection_status": "PARTIAL_WITH_ROWS", "cannot_confirm": ["SOURCE_PARTIAL"]},
        "20261029/S2/A": {"artifact_id": "s2", "selection_status": "READY"},
    }
    catalog, calls = catalog_for(entries, results)
    assert catalog == {
        "20261029": {
            "status": "PARTIAL", "trade_date": "20261029", "stage_ids": ["S1", "S2"],
            "markets": ["A", "HK"], "verified_markets": ["A", "HK"],
            "expected_markets": {"S1": ["A", "HK"], "S2": ["A"]},
            "missing_markets": [], "verified_entries": 3, "blocked_entries": 0,
            "receipt_paths": [
                "selection_runs/20261029/A_SELECTION_S1/run-a/receipt.json",
                "selection_runs/20261029/A_SELECTION_S2/run-s2/receipt.json",
                "selection_runs/20261029/HK_SELECTION_S1/run-hk/receipt.json",
            ],
            "artifact_ids": ["a", "hk", "s2"], "cannot_confirm": ["SOURCE_PARTIAL"],
        }
    }
    assert calls == list(entries)
    results["20261029/S1/HK"] = {"artifact_id": "hk", "selection_status": "READY"}
    materialized, calls = catalog_for(entries, results)
    assert materialized["20261029"]["status"] == "MATERIALIZED"
    assert materialized["20261029"]["cannot_confirm"] == []
    assert calls == list(entries)


def test_invalid_entries_remain_blocked_and_missing_with_partial_dates():
    entries = {
        "20261029/S1/A": {"run_id": "valid"},
        "20261029/S1/HK": {"run_id": "invalid"},
        "20261028/S2/A": {"run_id": "invalid-only"},
    }
    results = {
        "20261029/S1/A": {"artifact_id": "ok", "selection_status": "READY"},
        "20261029/S1/HK": ValueError("invalid"),
        "20261028/S2/A": ValueError("invalid"),
    }
    catalog, calls = catalog_for(entries, results)
    assert catalog["20261029"]["status"] == "PARTIAL"
    assert catalog["20261029"]["verified_entries"] == 1
    assert catalog["20261029"]["blocked_entries"] == 1
    assert catalog["20261029"]["verified_markets"] == ["A"]
    assert catalog["20261029"]["missing_markets"] == ["S1:HK"]
    assert catalog["20261029"]["cannot_confirm"] == ["STAGE_ARTIFACT_INVALID:S1:HK:ValueError", "STAGE_MARKET_MISSING:S1:HK"]
    assert catalog["20261028"]["status"] == "BLOCKED"
    assert catalog["20261028"]["missing_markets"] == ["S2:A"]
    assert catalog["20261028"]["cannot_confirm"] == ["STAGE_ARTIFACT_INVALID:S2:A:ValueError", "STAGE_MARKET_MISSING:S2:A"]
    assert calls == list(entries)
