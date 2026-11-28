"""Read-only presentation regressions against the sealed D27 R21 sources."""
from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from v4_core.api.app import create_app
from v4_core.config import V4Config
from v4_core.decoupled.manager_history import ManagerHistory, create_manager_app, display_stock_name


@pytest.fixture
def frozen_root(monkeypatch):
    value = os.environ.get("V4_R21_OVERLAY_ROOT")
    if value is None:
        pytest.skip("V4_R21_OVERLAY_ROOT must point to the frozen isolated r21 inputs")
    root = Path(value).resolve(strict=True)
    monkeypatch.syspath_prepend(str(root))
    return root


def candidate_module(monkeypatch, name):
    path = Path(__file__).resolve().parents[1] / "candidate/content_projection" / f"{name}.py"
    spec = spec_from_file_location(f"content_projection.{name}", path)
    module = module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_d27_hk_gap_card_uses_verified_counts_and_preserves_original_diagnostics(frozen_root, monkeypatch, tmp_path):
    from content_projection.read_overlay import ContentProjection as FrozenProjection

    app = create_app(config=V4Config.from_env(tmp_path))
    data, dist = frozen_root / "home/data", frozen_root / "frontend/dist"
    frozen = FrozenProjection(app, data, dist)
    stage = candidate_module(monkeypatch, "stage_observation_reads")
    content = candidate_module(monkeypatch, "read_overlay")
    revised = content.ContentProjection(app, data, dist)
    key = "/api/v4/review?date=20261127"
    previous = TestClient(frozen).get(key)
    current = TestClient(revised).get(key)
    assert previous.status_code == current.status_code == 200
    before = previous.json()["market_reviews"]["HK"]["model_selection_review"]
    after = current.json()["market_reviews"]["HK"]["model_selection_review"]
    changed = {key for key, value in after.items() if key not in before or value != before[key]}
    assert changed == {"stage_input_evidence", "cannot_confirm"}
    assert len(after["close_top20"]) == 20
    assert after["observed_stage_union"]["selected_count"] == 25
    assert after["observed_stage_union"]["hit_count"] == 9
    assert after["observed_stage_union"]["formal_eligible"] is False
    assert after["cannot_confirm"][:len(before["cannot_confirm"])] == before["cannot_confirm"]
    stages = before["stage_input_evidence"]
    compacted = []
    for name, source in stages.items():
        item = after["stage_input_evidence"][name]
        if item == source:
            continue
        assert item["cannot_confirm_raw"] == source["cannot_confirm"]
        assert item["cannot_confirm"] == ["分钟线 75/100，缺 25 只", "盘口缺证"]
        assert all(item[key] == value for key, value in source.items() if key != "cannot_confirm")
        full_minute_source = source["cannot_confirm"][0].replace(",", ", ")
        assert any(name in reason and full_minute_source in reason for reason in after["cannot_confirm"])
        assert any(name in reason and "HK_STAGE_ORDERBOOK_INCOMPLETE" in reason for reason in after["cannot_confirm"])
        compacted.append(name)
    assert len(compacted) == 6
    assert before["stage_input_evidence"]["STAGE_0925"] == after["stage_input_evidence"]["STAGE_0925"]
    malformed = {"k": {"cannot_confirm": ["futu 只返回 75/100 只标的分钟线，缺少：HK.03523"]}}
    assert stage.display_stage_gaps(malformed) == (malformed, [])


def test_d27_manager_display_name_is_a_string_in_list_diagnostics_and_detail(frozen_root):
    root = frozen_root / "home/data/r21_pre_d30/manager"
    manifest_hash = "7d8377756faf893239977a822143160065252d4302a4f25ff8e439f6d292d621"
    reader = ManagerHistory(root, manifest_hash)
    version, _ = reader.resolve("20261127", None, None)
    raw = reader.member(version["us_mapping_focus"])
    original = next(row for row in raw["stocks"] if row["symbol"] == "HK.00345")
    source = original["name"]["name_source"]
    assert original["name"]["name"] == "VITASOY INT'L"
    client = TestClient(create_manager_app(reader))
    route = "/api/v4/manager-workbench/days/20261127/recommendations/US_MAPPING"
    focus = client.get(route).json()["data"]
    diagnoses = client.get(route, params={"view": "diagnostics", "symbol": "HK.00345"}).json()["data"]
    for listing in (focus, diagnoses):
        row = next(row for row in listing["stocks"] if row["symbol"] == "HK.00345")
        assert row["name"] == "VITASOY INT'L" and row["name_source"] == source
    assert focus["pagination"]["total"] == len(raw["stocks"])
    normal = next(row for row in raw["stocks"] if row["symbol"] == "HK.02655")
    assert next(row for row in focus["stocks"] if row["symbol"] == "HK.02655") == normal
    detail = client.get("/api/v4/manager-workbench/stocks/HK.00345", params={
        "date": "20261127", "run_id": focus["snapshot"]["run_id"],
    })
    assert detail.status_code == 200 and detail.json()["data"]["stock"]["name"] == "VITASOY INT'L"
    assert detail.json()["data"]["stock"]["name_source"] == source
    assert original["name"]["name_source"] == source
    distinct = {**original, "name_source": {"source": "preserve"}}
    display = display_stock_name(distinct)
    assert display["name_source"] == distinct["name_source"] and display["saved_name_source"] == source
    explicit_null = {**original, "name_source": None}
    assert display_stock_name(explicit_null)["name_source"] is None
    conflict = {**distinct, "saved_name_source": {"source": "another-one"}}
    assert display_stock_name(conflict) is conflict
