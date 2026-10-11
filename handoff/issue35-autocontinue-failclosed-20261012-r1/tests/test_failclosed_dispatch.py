"""Issue #35 / #35 fail-closed regression: execute original dispatch function AST.

SYNTHETIC / isolated: no Mac market data, scheduler or trading. Requires an
isolated after-patch app root: ISSUE35_APP_ROOT=/path/to/candidate/app python -m unittest ...
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Mapping
import os
import sys
import unittest


TARGET = "20261012"


def _subject():
    root = Path(os.environ["ISSUE35_APP_ROOT"])
    src = root / "v4/manager_research/plan_owner_dispatch.py"
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
    func = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef)
                and n.name == "_completed_dispatch_still_current")
    fake_package = ModuleType("issue35_test_pkg")
    fake_package.__path__ = []
    fake_workspace = ModuleType("issue35_test_pkg.workspace")
    fake_ops = ModuleType("ops")
    fake_ops.__path__ = []
    fake_cycle = ModuleType("ops.run_manager_announcement_cycle")
    fake_cycle.valid_owner_plan_result = lambda plan, branch: branch == "EVENING_NEXT_SESSION"
    for mod in (fake_package, fake_workspace, fake_ops, fake_cycle):
        sys.modules[mod.__name__] = mod

    state = {"mode": "current", "attempt": "good"}
    saved = {"run_id": "a" * 32, "sha256": "b" * 64,
             "input_identity": "c" * 64, "target_trade_date": TARGET}
    def read_plan(store, date):
        assert date == TARGET
        return saved
    def verified(store, plan):
        if state["attempt"] == "broken":
            raise ValueError("SYNTHETIC_MISSING_ATTEMPT")
        return {"run_id": saved["run_id"]}
    def read_workspace(service, date, **kwargs):
        if state["mode"] == "read_error":
            raise ValueError("SYNTHETIC_READ_FAILURE")
        return {"plan_product": {"status": "CURRENT" if state["mode"] == "current"
                    else "STALE_INPUTS_CHANGED", "consumed": state["mode"] == "current",
                    "run_id": saved["run_id"], "sha256": saved["sha256"]}}
    fake_workspace._read_plan = read_plan
    fake_workspace.verified_plan_attempt = verified
    fake_workspace.get_workspace = read_workspace
    fake_workspace._ERROR_TYPES = (
        ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError)
    env = {"__package__": fake_package.__name__, "Any": Any,
           "Mapping": Mapping, "datetime": datetime}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])),
                 str(src), "exec"), env)
    return env["_completed_dispatch_still_current"], state, saved


class FailClosedDispatch(unittest.TestCase):
    def setUp(self):
        self.verify, self.state, saved = _subject()
        self.service = SimpleNamespace(store=object())
        self.identity = {"branch": "EVENING_NEXT_SESSION", "target_trade_date": TARGET}
        self.previous = {"state": "COMPLETED", "response": {"plan_result": {
            "run_id": saved["run_id"], "product_sha256": saved["sha256"],
            "input_identity": saved["input_identity"]}}}
        self.now = datetime(2026, 10, 11, 14, 0, tzinfo=timezone.utc)

    def check(self):
        return self.verify(self.service, self.identity, self.previous, now=self.now)

    def test_same_owner_and_current_material_may_replay(self):
        self.assertTrue(self.check())

    def test_real_stale_must_not_replay(self):
        self.state["mode"] = "stale"
        self.assertFalse(self.check())

    def test_missing_terminal_attempt_must_not_replay(self):
        self.state["attempt"] = "broken"
        self.assertFalse(self.check())

    def test_workspace_read_error_must_not_abort_dispatch(self):
        self.state["mode"] = "read_error"
        self.assertFalse(self.check())

    def test_non_evening_has_own_slot_contract(self):
        self.identity["branch"] = "SAME_DAY_CATCHUP"
        self.assertTrue(self.check())


if __name__ == "__main__":
    unittest.main(verbosity=2)
