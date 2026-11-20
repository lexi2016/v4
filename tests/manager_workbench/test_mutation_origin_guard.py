"""Mock-only request boundary tests; never create workers, sources or live writes."""
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from v4.manager_workbench import api
from v4.manager_workbench.contracts import JobState

BASE = api.PREFIX
JOB = "a" * 32
SHA = "b" * 64
RUN = {"target_date": "20261120", "phase": "MANUAL"}
WRITES = [
    ("/runs", RUN),
    (f"/runs/{JOB}/retry", {}),
    ("/announcement-flash/update", {"target_date": "20261120"}),
    ("/announcement-flash/recover-cached-product", {"failed_job_id": JOB, "product_sha256": SHA}),
    (f"/announcement-flash/{JOB}/execute-preprocessed", {"report_sha256": SHA, "phase": "FIRST"}),
    (f"/announcement-flash/{JOB}/stop", {}),
    ("/announcement-flash/resume", {"target_date": "20261120", "source_job_id": JOB,
        "source_input_sha256": SHA, "source_progress_sha256": SHA,
        "source_queue_state_sha256": SHA, "resume_action": "CANARY"}),
]


@pytest.fixture
def boundary(monkeypatch):
    service, update = Mock(), Mock()
    job = SimpleNamespace(job_id=JOB, run_id=JOB, state=JobState.QUEUED, step="QUEUED",
        context=SimpleNamespace(target_date="20261120", scope_refs={}),
        model_dump=lambda **kw: {"job_id": JOB, "state": "QUEUED"})
    service.submit.return_value = service.retry.return_value = service.jobs.get.return_value = job
    for name in ("start", "start_resume", "start_cached_product_recovery", "execute_preprocessed"):
        getattr(update, name).return_value = job
    update.stop.return_value = {"job_id": JOB, "state": "USER_STOPPED"}
    monkeypatch.setattr(api, "AnnouncementUpdate", Mock(return_value=update))
    app = FastAPI()
    app.include_router(api.create_router(service))
    return app, service, update


@pytest.mark.parametrize("path,payload", WRITES)
def test_cross_origin_rejection_never_reaches_worker(boundary, path, payload):
    app, service, update = boundary
    with TestClient(app, base_url="http://127.0.0.1:8873", client=("127.0.0.1", 50000)) as client:
        response = client.post(BASE + path, json=payload,
            headers={"Origin": "https://example.invalid", "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403
    assert response.json()["orders_sent"] is False
    assert service.mock_calls == [] and update.mock_calls == []


@pytest.mark.parametrize("headers,peer", [
    ({"Origin": "null"}, "127.0.0.1"),
    ({"Origin": "http://localhost:8873"}, "127.0.0.1"),
    ({"Origin": "http://127.0.0.1:8910"}, "127.0.0.1"),
    ({"Origin": "https://127.0.0.1:8873"}, "127.0.0.1"),
    ({"Origin": "http://127.0.0.1:8873/path"}, "127.0.0.1"),
    ({"Origin": "http://user@127.0.0.1:8873"}, "127.0.0.1"),
    ({"Origin": "http://127.0.0.1:8873,https://example.invalid"}, "127.0.0.1"),
    ({"Host": "example.invalid:8873", "Origin": "http://example.invalid:8873"}, "127.0.0.1"),
    ({"Host": "127.0.0.1.example.invalid:8873"}, "127.0.0.1"),
    ({"Host": "user@127.0.0.1:8873"}, "127.0.0.1"),
    ({"Sec-Fetch-Site": "same-site"}, "127.0.0.1"),
    ({"Sec-Fetch-Site": "same-origin"}, "127.0.0.1"),
    ({"Referer": "http://127.0.0.1:8873/"}, "127.0.0.1"),
    ({}, "192.0.2.1"),
    ({"X-Forwarded-For": "127.0.0.1", "X-Forwarded-Host": "localhost:8873"}, "192.0.2.1"),
])
def test_untrusted_provenance_or_host_is_rejected(boundary, headers, peer):
    app, service, update = boundary
    with TestClient(app, base_url="http://127.0.0.1:8873", client=(peer, 50000)) as client:
        # Invalid body additionally proves rejection happens before validation.
        response = client.post(BASE + "/runs", content="invalid", headers=headers)
    assert response.status_code == 403
    assert service.mock_calls == [] and update.mock_calls == []


@pytest.mark.parametrize("path,payload", WRITES)
@pytest.mark.parametrize("browser", [True, False], ids=["same-origin-browser", "loopback-cli"])
def test_existing_same_origin_and_local_machine_callers_remain_supported(boundary, path, payload, browser):
    app, service, update = boundary
    headers = {"Origin": "http://127.0.0.1:8873", "Sec-Fetch-Site": "same-origin"} if browser else {}
    with TestClient(app, base_url="http://127.0.0.1:8873", client=("127.0.0.1", 50000)) as client:
        response = client.post(BASE + path, json=payload, headers=headers)
    assert response.status_code == 202
    assert service.mock_calls or update.mock_calls


@pytest.mark.parametrize("url,peer", [("http://localhost:8873", "127.0.0.1"), ("http://[::1]:8873", "::1")])
def test_local_hostname_and_ipv6_are_supported(boundary, url, peer):
    app, service, _ = boundary
    # This Starlette TestClient version cannot parse an IPv6 URL netloc.
    # Supply the real HTTP authority through Host while keeping mock transport.
    with TestClient(app, base_url="http://127.0.0.1:8873", client=(peer, 50000)) as client:
        assert client.post(BASE + "/runs", json=RUN,
            headers={"Origin": url, "Host": url.removeprefix("http://")}).status_code == 202
    service.submit.assert_called_once()


def test_duplicate_origin_is_rejected(boundary):
    app, service, update = boundary
    with TestClient(app, base_url="http://127.0.0.1:8873", client=("127.0.0.1", 50000)) as client:
        response = client.post(BASE + "/runs", json=RUN,
            headers=[("Origin", "http://127.0.0.1:8873"), ("Origin", "https://example.invalid")])
    assert response.status_code == 403
    assert service.mock_calls == [] and update.mock_calls == []


def test_get_contract_remains_read_only_and_unguarded(boundary):
    app, service, update = boundary
    with TestClient(app) as client:
        response = client.get(BASE + f"/runs/{JOB}")
    assert response.status_code == 200
    service.jobs.get.assert_called_once_with(JOB)
    service.submit.assert_not_called()
    assert update.mock_calls == []
