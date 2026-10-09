"""Legal synthetic prerequisites for inherited owner/dispatch regressions.

Use the original reviewed-announcement builder, import route and consumer.
No ready flag or successful plan is injected. These helpers only create
temporary test state, and do not establish a real market result.
"""
from copy import deepcopy
from datetime import datetime, timedelta

import test_manager_announcement_parity_20261008 as original
from v4.manager_research import workspace


def assessed_service(tmp_path, monkeypatch, *, now, state_name="assessed-state"):
    available = now - timedelta(minutes=1)
    class ImportClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return available.astimezone(tz) if tz else available.replace(tzinfo=None)
    monkeypatch.setattr(original.api, "datetime", ImportClock)
    monkeypatch.setattr(original.consumer, "_now", lambda: available.isoformat())
    service = original._FixtureService(tmp_path / state_name)
    with original._client(service) as client:
        _, registration = original._fixture(service, disposition="NOT_SELECTED",
            listing_at="2026-10-07T01:00:00+00:00",
            body_at="2026-10-07T01:01:00+00:00",
            reviewed_at="2026-10-07T02:00:00+00:00")
        original._import(client, registration)
    projection = workspace.get_workspace(service, "20261008", include_saved=False, now=now)
    channel = next(row for row in projection["daily_channels"]["channels"]
                   if row["channel"] == "ANNOUNCEMENT")
    assert channel["status"] == "READY_EMPTY", channel
    assert channel["candidate_count"] == 0
    assert channel["input_identity"]
    return service


def assessed_projection(tmp_path, monkeypatch, *, now):
    service = assessed_service(tmp_path, monkeypatch, now=now)
    try:
        return deepcopy(workspace.get_workspace(service, "20261008",
            include_saved=False, now=now))
    finally:
        service.close()
