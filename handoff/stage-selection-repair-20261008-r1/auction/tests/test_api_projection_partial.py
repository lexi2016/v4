"""PARTIAL AST-ISOLATED API PROJECTION, not a FastAPI/app integration test.

The frozen handoff does not include current API dependency closure. This tests
the unmodified complete nested projection functions extracted from the frozen
A-pool app.py after the real imported adapter/store/read-only consumer path.
It does not execute app startup, route dispatch, middleware or HTTP transport.
"""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path

import pytest

from test_a_auction_prev_close import auction_row, through_adapter, publish_and_read


APP = Path(os.environ.get("ISSUE28_API_REFERENCE", Path(__file__).resolve().parents[3] / "reuse/a_pool/canonical/apps/api/v35_api/app.py"))
APP_SHA = "435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590"


def partial_api_projector():
    data = APP.read_bytes()
    assert hashlib.sha256(data).hexdigest() == APP_SHA
    tree = ast.parse(data, filename=str(APP))
    factory = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "create_app")
    names = {"_stage_projection_status", "project_shared_selection"}
    functions = [item for item in factory.body if isinstance(item, ast.FunctionDef) and item.name in names]
    assert {item.name for item in functions} == names
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *functions], type_ignores=[])
    scope = {"STAGE_DEFINITIONS": {}}
    exec(compile(ast.fix_missing_locations(module), str(APP), "exec"), scope)
    return scope["project_shared_selection"]


@pytest.mark.parametrize("previous,expected_pct,expected_reason", [
    (100, 5, None),
    (None, None, "PREV_CLOSE_PRICE_MISSING"),
    (-100, None, "PREV_CLOSE_PRICE_INVALID"),
])
def test_partial_api_projection_keeps_persisted_daily_change(tmp_path, previous, expected_pct, expected_reason):
    envelope = through_adapter([auction_row(previous=previous, price=105)])
    verified, consumer_response, _ = publish_and_read(tmp_path, envelope)
    response = partial_api_projector()(consumer_response, 10)
    for row in (response["markets"]["A"]["rows"][0], response["unified_rows"][0]):
        assert row["current_change_pct"] == expected_pct
        assert row["prev_close_price"] == (100 if expected_pct == 5 else None)
        assert row.get("current_change_pct_missing_reason") == expected_reason
    assert response["selected_a_rows"] == 1
    assert response["selection_markets"]["A_SHARE"]["run_id"] == verified["run_id"]
    assert response["orders_sent"] is False
