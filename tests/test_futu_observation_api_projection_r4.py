"""Direct regressions for the canonical HK observation projection."""

from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_APP = ROOT / "apps/api/v35_api/app.py"
TRADE_DATE = "20261012"
STAGE_ID = "STAGE_1545_1555"


@pytest.fixture(scope="module")
def project_selection():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("canonical_api_projection_r4", API_APP)
    if spec is None or spec.loader is None:
        raise AssertionError("canonical API module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix="tmp-api-projection-r4-", dir=ROOT) as temp_root:
        app = module.create_app(
            data_root=Path(temp_root) / "data",
            stage_center_selection_root=Path(temp_root) / "selection",
            current_date=TRADE_DATE,
        )
        route = next(
            route
            for route in app.routes
            if getattr(route, "path", None) == "/api/v3/workbench/stage"
            and "GET" in getattr(route, "methods", set())
        )
        yield next(
            cell.cell_contents
            for cell in route.endpoint.__closure__
            if callable(cell.cell_contents)
            and getattr(cell.cell_contents, "__name__", None) == "project_shared_selection"
        )


def _payload(*, include_a: bool = False) -> dict:
    rows = [
        {
            "code": f"HK.{index:05d}",
            "rank": index,
            "formal_eligible": False,
            "action_level": "NO_BUY",
            "temporal_cutoff_safe": False,
        }
        for index in range(1, 11)
    ]
    hk = {
        "market": "HK_CONNECT",
        "status": "PARTIAL_WITH_ROWS",
        "selection_status": "PARTIAL_WITH_ROWS",
        "source_status": "PARTIAL_WITH_ROWS",
        "artifact_id": "hk-artifact",
        "run_id": "hk-run",
        "raw_artifact_sha256": "b" * 64,
        "requested_rows": 10,
        "source_rows": 10,
        "selected_rows": 10,
        "source_evidence": ["frozen-observation"],
        "rows": rows,
        "cannot_confirm": [],
    }
    markets = {"HK_CONNECT": hk}
    if include_a:
        markets["A_SHARE"] = {
            "market": "A_SHARE",
            "status": "READY",
            "selection_status": "READY",
            "source_status": "READY",
            "artifact_id": "a-artifact",
            "run_id": "a-run",
            "raw_artifact_sha256": "a" * 64,
            "selected_rows": 1,
            "rows": [{"code": "A.000001", "rank": 1}],
            "cannot_confirm": [],
        }
    return {
        "status": "PARTIAL_WITH_ROWS",
        "stage_id": STAGE_ID,
        "markets": markets,
        "execution_evidence": {
            "markets": {"HK_CONNECT": {"selection_binding": "CANNOT_CONFIRM"}}
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "cannot_confirm": [],
    }


def test_canonical_api_keeps_valid_hk_observation_counts(project_selection):
    projected = project_selection(_payload(), 50, ordinary_hk_display=True)
    hk = projected["market_summaries"]["HK"]
    rows = hk["rows"]
    assert projected["status"] == "PARTIAL_WITH_ROWS"
    assert projected["selected_hk_rows"] == 10
    assert projected["selected_total_rows"] == 10
    assert hk["status"] == "PARTIAL_WITH_ROWS"
    assert hk["selected_rows"] == 10
    assert hk["candidate_count"] == 10
    assert hk["observation_count"] == 10
    assert len(rows) == 10
    assert len(projected["unified_rows"]) == 10
    assert projected["selected_a_rows"] == 0
    assert hk["display_mode"] == "OBSERVATION_UNVERIFIED"
    assert all(
        row["formal_eligible"] is False
        and row["action_level"] == "NO_BUY"
        and row["temporal_cutoff_safe"] is False
        for row in rows
    )
    assert projected["production_allowed"] is False
    assert projected["buy_gate_updated"] is False
    assert projected["orders_sent"] is False


def test_canonical_projection_hides_hk_rows_without_valid_identity_or_status(project_selection):
    base = _payload(include_a=True)
    for invalid_kind in ("missing_identity", "invalid_status"):
        payload = copy.deepcopy(base)
        hk_payload = payload["markets"]["HK_CONNECT"]
        if invalid_kind == "missing_identity":
            hk_payload["artifact_id"] = None
        else:
            hk_payload["status"] = "CANNOT_CONFIRM"
        projected = project_selection(payload, 50, ordinary_hk_display=True)
        hk = projected["market_summaries"]["HK"]
        assert hk["display_mode"] == "CANNOT_CONFIRM"
        assert hk["rows"] == []
        assert hk["selected_rows"] is None
        assert hk["candidate_count"] is None
        assert hk["observation_count"] is None
        assert projected["selection_markets"]["HK_CONNECT"]["rows"] == []
        assert projected["selected_hk_rows"] is None
        assert projected["selected_a_rows"] == 1
        assert [row["market"] for row in projected["unified_rows"]] == ["A"]
