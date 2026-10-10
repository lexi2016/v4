"""Independent proposal-only regressions; no real owner/state/network access.

The scheduled test runs the candidate refresh/readback/attempt code against an
in-memory store. Only input assembly and the unavailable native calendar window
are replaced by explicit fixtures. No service or scheduler is started.
"""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "candidate"), str(ROOT / "recovery_sources/dependencies")]
from v4.manager_research import workspace as W
from v4.manager_research.workspace_projection import FLAGS, HK, build_workspace, digest

DATE = "20261009"
BEFORE = "2026-10-09T08:00:00+08:00"
NOW = datetime(2026, 10, 9, 8, 5, tzinfo=HK)
DEADLINE = datetime(2026, 10, 9, 9, 25, tzinfo=HK)


class MemoryStore:
    def __init__(self):
        self.root = Path("/ISOLATED_REVIEW_DO_NOT_ACCESS/manager")
        self.rows = {}
        self.write_count = 0

    def _read(self, path):
        return deepcopy(self.rows.get(str(path)))

    def _transaction(self, *_args):
        return nullcontext()

    def _write_atomic(self, path, value):
        self.write_count += 1
        self.rows[str(path)] = deepcopy(value)


def fresh_workspace():
    value = build_workspace(DATE, catalyst={}, materials=[], stage=None, close=None)
    value["date_bindings"] = {"plan_date": DATE, "selection_date": DATE, "announcement_date": "20261008"}
    value["plan_context"]["research_cutoff"] = BEFORE
    value["existing_material_coverage"] = {}
    return value


def legacy_scheduled_product(store, current):
    old = deepcopy(current)
    old.pop("input_identity_schema")
    old.pop("input_identity_components")
    product = dict(schema_version=W.PLAN_SCHEMA, target_trade_date=DATE,
        run_id="2" * 32, generated_at=BEFORE,
        owner="ManagerResearchJobService.refresh_workspace_plan",
        execution_kind="SCHEDULED_MORNING", input_identity=old["input_identity"],
        workspace=old, **FLAGS)
    product["sha256"] = digest(product)
    attempt = W.seal_attempt(dict(schema_version=W.ATTEMPT_SCHEMA,
        target_trade_date=DATE, run_id=product["run_id"], owner=product["owner"],
        execution_kind=product["execution_kind"], state="PARTIAL",
        started_at="2026-10-09T07:59:00+08:00", finished_at=BEFORE,
        input_identity=product["input_identity"], failure_reasons=["SYNTHETIC_INPUT_GAP"], **FLAGS))
    for suffix in ["latest", product["run_id"]]:
        store.rows[str(store.root / f"workspace_plans/{DATE}/{suffix}.json")] = deepcopy(product)
        store.rows[str(store.root / f"workspace_plan_runs/{DATE}/{suffix}.json")] = deepcopy(attempt)
    return product


class IndependentBackendReview(unittest.TestCase):
    def test_scheduled_reuse_must_not_consume_legacy_same_identity_product(self):
        current = fresh_workspace()
        store = MemoryStore()
        legacy = legacy_scheduled_product(store, current)
        initial_rows = deepcopy(store.rows)
        with patch("v4.manager_research.workspace_plan_autorun.morning_window",
                   return_value=(NOW.replace(hour=7, minute=0), DEADLINE)):
            # Same identity and a valid exact attempt are insufficient without
            # the new sealed identity component contract.
            before = W._readback_plan(store, DATE, deepcopy(current), read_at=NOW)
            self.assertEqual(before["plan_product"]["status"], "STALE_INPUTS_CHANGED")
            self.assertFalse(before["plan_product"]["consumed"])
            self.assertEqual(store.rows, initial_rows)
            service = type("SyntheticService", (), {"store": store})()
            with patch.object(W, "get_workspace", return_value=deepcopy(current)), \
                 patch.object(W, "_now", return_value=NOW.isoformat()):
                result = W.refresh_workspace_plan(service, DATE,
                    execution_kind="SCHEDULED_MORNING", now=NOW, deadline=DEADLINE)
        product = result["plan_product"]
        self.assertFalse(product.get("consumed") is True and product.get("run_id") == legacy["run_id"],
            "Legacy same-identity plan was reused as consumed despite failing ordinary readback: " + repr(product))
        self.assertEqual(store.rows[str(store.root / f"workspace_plans/{DATE}/{legacy['run_id']}.json")], legacy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
