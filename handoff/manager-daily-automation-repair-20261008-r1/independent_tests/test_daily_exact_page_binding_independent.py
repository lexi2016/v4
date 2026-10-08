"""Exercise the actual refresh route and normal explicit-date workspace GET."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
from copy import deepcopy
from zoneinfo import ZoneInfo

import pytest

REVIEWER_DIR = Path(__file__).resolve().parent
if str(REVIEWER_DIR) not in sys.path:
    sys.path.insert(0, str(REVIEWER_DIR))
from _source_root import source_root  # noqa: E402

REPO = source_root(__file__)
for import_root in (REPO, REPO / "upstreams", REPO / "tests"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from test_manager_announcement_parity_20261008 import (  # noqa: E402
    _FixtureService, _client,
)
from v4.manager_research import workspace as workspace_owner  # noqa: E402

HK = ZoneInfo("Asia/Hong_Kong")


def test_actual_manual_refresh_plan_is_current_on_the_exact_ordinary_page_bindings(
        tmp_path, monkeypatch):
    """POST has no announcement_date, while the ordinary GET supplies all three dates."""
    actual = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    import test_manager_announcement_parity_20261008 as fixture_module

    class FrozenRouterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return actual.astimezone(tz) if tz else actual.replace(tzinfo=None)

    monkeypatch.setattr(fixture_module.api, "datetime", FrozenRouterClock)
    monkeypatch.setattr(workspace_owner, "_now", lambda: "2026-10-08T02:00:02+00:00")
    monkeypatch.setattr(fixture_module, "NOW", datetime(2026, 10, 8, 10, 0, 3, tzinfo=HK))
    projection_calls = []
    original_build_workspace = workspace_owner.build_workspace

    def capture_projection(date, **kwargs):
        projected = original_build_workspace(date, **kwargs)
        identity_material = {
            "decision_projection_version": "20260921.manager-decision-ux.a1",
            "semantic_version": projected.get("semantic_version"),
            **{key: deepcopy(kwargs.get(key)) for key in (
                "catalyst", "materials", "stage", "close", "discovered_cards",
                "discovery_rejections", "price_quotes", "market_screen")},
            "plan_context": ({key: deepcopy(value) for key, value in kwargs.get("plan_context", {}).items()
                              if key != "research_cutoff"}
                             if kwargs.get("plan_context") else None),
        }
        projection_calls.append({
            "identity": projected.get("input_identity"),
            "basis": identity_material,
        })
        return projected

    monkeypatch.setattr(workspace_owner, "build_workspace", capture_projection)
    service = _FixtureService(tmp_path / "manager-state")
    try:
        with _client(service) as client:
            refresh = client.post("/api/v4/manager/research/workspace/refresh",
                params={"date": "20261008"}, headers={"Origin": "http://testserver"})
            assert refresh.status_code == 200, refresh.text
            saved_run = refresh.json()["plan_product"]["run_id"]

            default_read = client.get("/api/v4/manager/research/workspace",
                params={"date": "20261008", "view": "dynamic"})
            assert default_read.status_code == 200, default_read.text
            explicit_read = client.get("/api/v4/manager/research/workspace",
                params={"date": "20261008", "view": "dynamic",
                    "selection_date": "20261008", "announcement_date": "20261007"})
            assert explicit_read.status_code == 200, explicit_read.text

        default = default_read.json()
        explicit = explicit_read.json()
        saved = workspace_owner._read_plan(service.store, "20261008")

        def path_diffs(left, right, path=""):
            if isinstance(left, dict) and isinstance(right, dict):
                diffs = []
                for key in sorted(set(left) | set(right)):
                    child = f"{path}.{key}" if path else key
                    if key not in left or key not in right:
                        diffs.append({"path": child, "saved": left.get(key, "<MISSING>"),
                                      "current": right.get(key, "<MISSING>")})
                    else:
                        diffs.extend(path_diffs(left[key], right[key], child))
                return diffs
            if isinstance(left, list) and isinstance(right, list):
                if left == right:
                    return []
                return [{"path": path, "saved_count": len(left), "current_count": len(right),
                         "saved_sha256": workspace_owner.digest(left),
                         "current_sha256": workspace_owner.digest(right)}]
            if left != right:
                return [{"path": path, "saved": left, "current": right}]
            return []

        captured_by_identity = {item["identity"]: item["basis"] for item in projection_calls}
        saved_cutoff = saved["workspace"].get("plan_context", {}).get("research_cutoff")
        def matching_projection(*, cutoff, explicit_announcement):
            for item in projection_calls:
                context = item["basis"].get("plan_context") or {}
                screen_context = ((item["basis"].get("market_screen") or {}).get("data_context") or {})
                if (screen_context.get("research_cutoff") == cutoff
                        and (context.get("announcement_publication_date") is not None)
                        == explicit_announcement):
                    return item
            return None
        saved_projection = matching_projection(cutoff=saved_cutoff, explicit_announcement=False)
        default_projection = matching_projection(cutoff="2026-10-08T10:00:03+08:00", explicit_announcement=False)
        explicit_projection = matching_projection(cutoff="2026-10-08T10:00:03+08:00", explicit_announcement=True)
        print("SEMANTIC_PROJECTION_INPUT_PATH_DIFFS=" + json.dumps({
            "saved_vs_default": path_diffs((saved_projection or {}).get("basis", {}),
                                             (default_projection or {}).get("basis", {})),
            "saved_vs_explicit": path_diffs((saved_projection or {}).get("basis", {}),
                                              (explicit_projection or {}).get("basis", {})),
            "selected_captures": {"saved": (saved_projection or {}).get("identity"),
                                  "default": (default_projection or {}).get("identity"),
                                  "explicit": (explicit_projection or {}).get("identity")},
            "capture_count": len(projection_calls),
            "captured_identities": [item["identity"] for item in projection_calls],
            "captured_projection_contexts": [{
                "identity": item["identity"],
                "plan_context": item["basis"].get("plan_context"),
                "market_screen_data_context": (item["basis"].get("market_screen") or {}).get("data_context"),
                "material_count": len(item["basis"].get("materials") or []),
                "catalyst_status": (item["basis"].get("catalyst") or {}).get("status"),
                "stage_status": (item["basis"].get("stage") or {}).get("status"),
                "close_status": (item["basis"].get("close") or {}).get("status"),
                "discovered_card_count": len(item["basis"].get("discovered_cards") or []),
                "discovery_rejection_count": len(item["basis"].get("discovery_rejections") or []),
                "quote_count": len(item["basis"].get("price_quotes") or {}),
            } for item in projection_calls],
        }, ensure_ascii=False, sort_keys=True, default=str))

        def summary(value):
            screen = value.get("market_screen") or {}
            analysis = value.get("announcement_reviewed_analysis") or {}
            chain = value.get("owner_chain") or {}
            selection = chain.get("announcement_selection") or {}
            us_plan_ref = chain.get("us_mapping_daily_plan_reference") or {}
            us_attention = value.get("us_market_attention") or {}
            announcement_review = value.get("announcement_review") or {}
            return {
                "input_identity": value.get("input_identity"),
                "plan_context": value.get("plan_context"),
                "semantic_projection_identity": (chain.get("semantic_projection") or {}).get("input_identity"),
                "market_screen": {key: screen.get(key) for key in (
                    "status", "input_identity", "verified_session", "screen_phase",
                    "research_cutoff", "coverage", "gaps", "source_identity", "authority",
                    "data_context", "source_manifest_sha256", "verified_at")},
                "attention_identity": (value.get("research_attention") or {}).get("input_identity"),
                "announcement_selection": {key: selection.get(key) for key in (
                    "status", "input_identity", "captures", "body_material_count", "rejections", "gaps")},
                "announcement_review": {key: announcement_review.get(key) for key in (
                    "status", "product_identity", "target_trade_date", "latest_attempt", "gaps")},
                "reviewed_analysis": {key: analysis.get(key) for key in (
                    "status", "input_identity", "products", "consumed_product_sha256s", "gaps")},
                "us_market_attention": {key: us_attention.get(key) for key in (
                    "status", "expected_us_session", "source_identity", "input_identity", "coverage", "gaps")},
                "us_mapping_daily_plan_reference": {key: us_plan_ref.get(key) for key in (
                    "status", "source_identity", "payload_sha256", "input_identity", "target_trade_date",
                    "research_cutoff", "gaps", "reason")},
                "us_mapping_research": value.get("us_mapping_research"),
                "announcement_observation": {
                    key: (value.get("announcement_observation") or {}).get(key)
                    for key in ("status", "input_identity", "latest_attempt", "captures", "gaps")},
                "materials": [(row.get("source_identity"), row.get("source_sha256"), row.get("material_id"))
                              for row in value.get("materials", []) if isinstance(row, dict)],
            }
        print("SAVED_DEFAULT_EXPLICIT_IDENTITY_DIAGNOSTIC=" + json.dumps({
            "saved": summary(saved["workspace"]), "default_get": summary(default),
            "explicit_get": summary(explicit)}, ensure_ascii=False, sort_keys=True, default=str))
        assert default["plan_product"]["run_id"] == saved_run
        assert explicit["date_bindings"] == {
            "plan_date": "20261008", "selection_date": "20261008",
            "announcement_date": "20261007",
        }
        assert explicit["plan_product"]["run_id"] == saved_run
        assert explicit["plan_product"]["consumed"] is True, (
            {"default_status": default["plan_product"]["status"],
             "default_consumed": default["plan_product"]["consumed"],
             "explicit_product": explicit["plan_product"],
             "explicit_input_identity": explicit["input_identity"],
             "saved_input_identity": refresh.json()["input_identity"]})
        assert explicit["plan_product"]["status"] in {"CURRENT", "ALREADY_MATERIALIZED"}
    finally:
        service.close()
