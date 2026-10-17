from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from v4.manager_workbench.scheduler import _us_close_handoff


class Calendar:
    def next_hk_session(self, day):
        assert day == "20261016"
        return "20261020"

    def is_hk_session(self, day):
        return day == "20261020"


class Store:
    def __init__(self):
        self.cursors = {}

    def cursor(self, key):
        return self.cursors.get(key)

    def set_cursor(self, key, value):
        self.cursors[key] = value


class Service:
    def __init__(self, pin):
        self.adapters = SimpleNamespace(
            config=SimpleNamespace(us_root=Path("/unused-test-root")),
            _us_session=lambda cutoff: "20261016",
        )
        self.pin = pin
        self.store = Store()
        self.submissions = []

    def context(self, target, phase, **kwargs):
        return SimpleNamespace(scope_refs={"owner_bindings": {"us_mapping": self.pin}})

    def submit(self, target, phase, **kwargs):
        job = SimpleNamespace(job_id=f"job-{len(self.submissions) + 1}",
                              run_id=f"run-{len(self.submissions) + 1}")
        self.submissions.append((target, phase, kwargs, job))
        return job


def _pin():
    return {
        "capture_phase": "POST_CLOSE",
        "capture_status": "READY",
        "capture_session_date": "20261016",
        "quote_sha256": "a" * 64,
        "owner_receipt_sha256": "b" * 64,
        "owner_manifest_sha256": "c" * 64,
        "capture_cutoff": "2026-10-16T16:18:00-04:00",
    }


def test_exact_us_close_artifact_refresh_is_idempotent_and_targets_next_hk_session():
    service = Service(_pin())
    local = datetime.fromisoformat("2026-10-17T04:20:00+08:00")

    first = _us_close_handoff(service, calendar=Calendar(), local=local)
    second = _us_close_handoff(service, calendar=Calendar(), local=local)

    assert len(first) == 1
    assert first[0]["target_date"] == "20261020"
    assert first[0]["us_session_date"] == "20261016"
    assert second == []
    assert len(service.submissions) == 1
    assert len(service.store.cursors) == 1


def test_missing_or_non_post_close_owner_artifact_does_not_submit():
    service = Service({**_pin(), "capture_status": "PARTIAL"})
    local = datetime.fromisoformat("2026-10-17T04:20:00+08:00")

    assert _us_close_handoff(service, calendar=Calendar(), local=local) == []
    assert service.submissions == []
    assert service.store.cursors == {}
