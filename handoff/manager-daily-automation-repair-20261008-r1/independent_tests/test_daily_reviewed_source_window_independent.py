"""Independent route-level test for reviewed-product source changes in the default window."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
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

from test_manager_announcement_parity_20261008 import _FixtureService, _client, _fixture, _import  # noqa: E402
from v4.manager_research import workspace as workspace_owner  # noqa: E402

HK = ZoneInfo("Asia/Hong_Kong")
TARGET = "20261008"


def test_new_reviewed_product_within_default_multi_day_window_stales_saved_plan_without_rewriting_it(
        tmp_path, monkeypatch):
    actual = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    import test_manager_announcement_parity_20261008 as fixture_module

    class FrozenRouterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return actual.astimezone(tz) if tz else actual.replace(tzinfo=None)

    monkeypatch.setattr(fixture_module.api, "datetime", FrozenRouterClock)
    monkeypatch.setattr(fixture_module, "NOW", datetime(2026, 10, 8, 10, 0, 3, tzinfo=HK))
    monkeypatch.setattr(workspace_owner, "_now", lambda: "2026-10-08T02:00:02+00:00")

    service = _FixtureService(tmp_path / "manager-state")
    try:
        with _client(service) as client:
            first_product, first_registration = _fixture(
                service, target=TARGET, publication="2026-10-07", run_id="1" * 32,
                listing_at="2026-10-07T01:00:00+00:00", body_at="2026-10-07T01:01:00+00:00",
                reviewed_at="2026-10-07T02:00:00+00:00")
            first_import = _import(client, first_registration)
            assert first_import["consumption_validation"]["validation_status"] == "VERIFIED"

            refreshed = client.post("/api/v4/manager/research/workspace/refresh",
                params={"date": TARGET}, headers={"Origin": "http://testserver"})
            assert refreshed.status_code == 200, refreshed.text
            sealed = refreshed.json()
            run_id = sealed["plan_product"]["run_id"]
            saved = workspace_owner._read_plan(service.store, TARGET)
            assert saved is not None and saved["run_id"] == run_id
            assert saved["workspace"]["plan_context"]["source_dates"] == [
                "20261006", "20261007", "20261008"]
            first_consumed = saved["workspace"]["announcement_reviewed_analysis"]["products"]
            assert [row["product_sha256"] for row in first_consumed] == [first_product["sha256"]]
            plan_dir = service.store.root / "workspace_plans" / TARGET
            immutable_plan = (plan_dir / f"{run_id}.json").read_bytes()
            latest_plan = (plan_dir / "latest.json").read_bytes()

            before_change = client.get("/api/v4/manager/research/workspace",
                params={"date": TARGET, "view": "dynamic"})
            assert before_change.status_code == 200, before_change.text
            baseline = before_change.json()
            assert baseline["plan_product"]["run_id"] == run_id
            assert baseline["plan_product"]["status"] == "CURRENT"
            assert baseline["plan_product"]["consumed"] is True

            second_product, second_registration = _fixture(
                service, target="20261006", publication="2026-10-05", run_id="2" * 32,
                listing_at="2026-10-05T01:00:00+00:00", body_at="2026-10-05T01:01:00+00:00",
                reviewed_at="2026-10-05T02:00:00+00:00")
            second_import = _import(client, second_registration)
            assert second_import["consumption_validation"]["validation_status"] == "VERIFIED"
            assert second_product["sha256"] != first_product["sha256"]

            stale_response = client.get("/api/v4/manager/research/workspace",
                params={"date": TARGET, "view": "dynamic"})
            assert stale_response.status_code == 200, stale_response.text
            stale = stale_response.json()
            assert stale["plan_product"]["run_id"] == run_id
            assert stale["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
            assert stale["plan_product"]["consumed"] is False
            assert stale["plan_context"]["source_dates"] == [
                "20261006", "20261007", "20261008"]
            current_sources = stale["announcement_reviewed_analysis"]["products"]
            assert {(row["target_trade_date"], row["publication_date"], row["product_sha256"])
                    for row in current_sources} == {
                (TARGET, "2026-10-07", first_product["sha256"]),
                ("20261006", "2026-10-05", second_product["sha256"])}
            assert (plan_dir / f"{run_id}.json").read_bytes() == immutable_plan
            assert (plan_dir / "latest.json").read_bytes() == latest_plan
    finally:
        service.close()
