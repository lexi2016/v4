from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from integrations.chatgpt_readonly.gateway import Limits, create_app, openapi_document
from integrations.chatgpt_readonly.saved_reader import (
    Bindings, ReadFailure, SavedFiles, SavedReader, canonical, digest, pool_digest,
)

# Deliberately public, deterministic fixture; never a deployment credential.
TEST_TOKEN = "test-only-placeholder-never-deploy-0000"
AUTH = {"Authorization": "Bearer " + TEST_TOKEN}
QUERY = "trade_date=20261022&market=A&pool_id=a_share_research_recommendation_pool"


async def request_async(app, method="GET", path="/v1/pools?" + QUERY, **kwargs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        return await client.request(method, path, **kwargs)


def request(app, **kwargs):
    return asyncio.run(request_async(app, **kwargs))


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"},
    {"Authorization": "Basic " + TEST_TOKEN}, {"X-API-Key": TEST_TOKEN}])
def test_auth_failures_never_call_reader(headers):
    reader = Mock()
    response = request(create_app(reader, lambda: TEST_TOKEN), headers=headers)
    assert response.status_code == 401
    reader.read.assert_not_called()
    assert TEST_TOKEN not in response.text


def test_missing_or_revoked_config_fails_closed():
    reader = Mock()
    token = [TEST_TOKEN]
    app = create_app(reader, lambda: token[0])
    token[0] = None
    assert request(app, headers=AUTH).status_code == 401
    reader.read.assert_not_called()


@pytest.mark.parametrize("method,path,code", [
    ("POST", "/api/v3/workbench/stage/ensure", 405),
    ("PUT", "/v1/pools", 405), ("PATCH", "/v1/pools", 405),
    ("DELETE", "/v1/pools", 405), ("HEAD", "/v1/pools", 405),
    ("OPTIONS", "/v1/pools", 405),
    ("GET", "/api/v3/runtime-graph/repair", 404),
    ("GET", "/v1/orders", 404), ("GET", "/openapi.json", 404),
    ("GET", "/v1/pools/", 404),
    ("GET", "/v1/%70ools?" + QUERY, 404),
    ("GET", "/v1/stocks/HK.%2e%2e/research", 404),
    ("GET", "/v1/pools?" + QUERY + "&url=http://localhost/admin", 422),
    ("GET", "/v1/pools?" + QUERY + "&path=/etc/passwd", 422),
    ("GET", "/v1/pools?" + QUERY + "&sql=SELECT+1", 422),
    ("GET", "/v1/pools?" + QUERY + "&trade_date=20261023", 422),
    ("GET", "/v1/pools?" + QUERY.replace("20261022", "20260230"), 422),
    ("GET", "/v1/pools?" + QUERY.replace("market=A", "market=HK"), 422),
    ("GET", "/v1/pools?" + QUERY + "&limit=51", 422),
    ("GET", "/v1/pools?" + QUERY + "&offset=-1", 422),
    ("GET", "/v1/stocks/A.000001/research?trade_date=20261022&market=A&phase=INTRADAY", 404),
])
def test_rejected_requests_never_call_reader(method, path, code):
    reader = Mock()
    response = request(create_app(reader, lambda: TEST_TOKEN), method=method, path=path, headers=AUTH)
    assert response.status_code == code, response.text
    reader.read.assert_not_called()


def test_body_and_duplicate_auth_rejected_without_reader():
    reader = Mock()
    app = create_app(reader, lambda: TEST_TOKEN)
    assert request(app, headers=AUTH, content=b"{}").status_code == 400
    assert request(app, headers=[("Authorization", "Bearer " + TEST_TOKEN)] * 2).status_code == 401
    reader.read.assert_not_called()


def test_health_has_no_data_or_auth_dependency():
    reader = Mock()
    app = create_app(reader, lambda: (_ for _ in ()).throw(RuntimeError()))
    result = request(app, path="/health")
    assert result.status_code == 200
    assert result.json()["RESEARCH_ONLY"] is True
    reader.read.assert_not_called()


def test_size_limit_is_an_error_not_a_truncated_success():
    reader = Mock()
    reader.read.return_value = {"rows": [{"value": "a" * 3000}]}
    result = request(create_app(reader, lambda: TEST_TOKEN, limits=Limits(response_bytes=2048)), headers=AUTH)
    assert result.status_code == 413
    assert "rows" not in result.json()


def test_rate_limit_refuses_before_reader():
    reader = Mock()
    reader.read.return_value = {"rows": []}
    app = create_app(reader, lambda: TEST_TOKEN, limits=Limits(requests_per_minute=1))
    assert request(app, headers=AUTH).status_code == 200
    assert request(app, headers=AUTH).status_code == 429
    assert reader.read.call_count == 1


def test_concurrency_is_bounded():
    entered, release = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(5)
        return {"rows": []}
    reader = Mock()
    reader.read.side_effect = slow
    app = create_app(reader, lambda: TEST_TOKEN)
    async def run():
        first = asyncio.create_task(request_async(app, headers=AUTH))
        await asyncio.to_thread(entered.wait, 3)
        try:
            second = await request_async(app, headers=AUTH)
            assert second.status_code == 503
            assert second.json()["error"] == "READ_CONCURRENCY_LIMIT"
        finally:
            release.set()
        assert (await first).status_code == 200
    asyncio.run(run())
    assert reader.read.call_count == 1


def test_timeout_keeps_worker_slot_until_it_exits():
    entered, release = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(5)
        return {"rows": []}
    reader = Mock()
    reader.read.side_effect = slow
    app = create_app(reader, lambda: TEST_TOKEN, limits=Limits(read_seconds=.03))
    async def run():
        first = await request_async(app, headers=AUTH)
        assert entered.is_set() and first.status_code == 504
        try:
            second = await request_async(app, headers=AUTH)
            assert second.status_code == 503
            assert reader.read.call_count == 1
        finally:
            release.set()
    asyncio.run(run())


def test_internal_errors_do_not_echo_secrets_paths_or_inputs():
    reader = Mock()
    reader.read.side_effect = RuntimeError("/Users/private " + TEST_TOKEN)
    result = request(create_app(reader, lambda: TEST_TOKEN), headers=AUTH)
    assert result.status_code == 503
    assert "/Users/" not in result.text and TEST_TOKEN not in result.text


def write(root: Path, relative: str, value: dict):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical(value))


def saved_pool(root, day="20261022", rows=None, metadata=None):
    pool = "a_share_research_recommendation_pool"
    payload = {"schema_version": "v3_5.preselection_pool.v1", "trade_date": day,
               "pool_id": pool, "market": "A", "status": "READY", "source_role": "SAVED_RESEARCH",
               "source_sha256": "a" * 64,
               "rows": rows if rows is not None else [{"symbol": "A.000001", "stock_name": "fixture", "pool_rank": 1}]}
    payload.update(metadata or {})
    base = f"preselection_pools/{day}"
    write(root, f"{base}/{pool}.json", payload)
    write(root, f"{base}/manifest.json", {pool: pool_digest(payload)})
    receipt = {"schema_version": "v3_5.preselection_pool_receipt.v1", "trade_date": day,
               "pool_id": pool, "artifact_path": f"{base}/{pool}.json", "artifact_sha256": pool_digest(payload),
               "source_sha256": payload["source_sha256"], "source_role": payload["source_role"]}
    write(root, f"{base}/receipts/{pool}.json", receipt)
    return payload


def reader_for(root, **kwargs):
    return SavedReader(Bindings(root, root), available=lambda: True,
                       now=lambda: datetime.fromisoformat("2026-10-23T10:00:00+08:00"), **kwargs)


def pool_params(**kwargs):
    return dict(trade_date="20261022", market="A", pool_id="a_share_research_recommendation_pool",
                limit=2, offset=0, **kwargs)


def test_saved_pool_paginates_all_rows_and_keeps_missing_time_unknown(tmp_path):
    saved_pool(tmp_path, rows=[{"symbol": f"A.{i:06d}", "name": "fixture"} for i in range(5)])
    reader = reader_for(tmp_path)
    first = reader.read("pools", pool_params())
    assert first["as_of"] is None and first["status"] == "unknown"
    assert first["coverage"]["total"] == 5 and first["coverage"]["next_offset"] == 2
    assert not first["coverage"]["dataset_complete_in_response"]
    assert first["source"][0]["source_sha256"] == "a" * 64
    assert "SOURCE_AS_OF_NOT_RECORDED" in first["missing_reasons"]
    assert "/" not in json.dumps(first["source"])


def test_missing_date_does_not_read_the_available_date(tmp_path):
    saved_pool(tmp_path)
    params = pool_params()
    params["trade_date"] = "20261021"
    with pytest.raises(ReadFailure, match="SAVED_DATA_NOT_FOUND"):
        reader_for(tmp_path).read("pools", params)


def test_empty_saved_dataset_is_distinct_from_missing(tmp_path):
    saved_pool(tmp_path, rows=[])
    result = reader_for(tmp_path).read("pools", pool_params())
    assert result["rows"] == [] and result["coverage"]["total"] == 0
    assert result["coverage"]["dataset_complete_in_response"]


def test_pending_commit_is_not_repaired(tmp_path):
    saved_pool(tmp_path)
    pending = "preselection_pending_commits/20261022/a_share_research_recommendation_pool.json"
    write(tmp_path, pending, {"pending": True})
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")}
    with pytest.raises(ReadFailure, match="PENDING_COMMIT"):
        reader_for(tmp_path).read("pools", pool_params())
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")}


def test_tampered_receipt_rejected(tmp_path):
    saved_pool(tmp_path)
    target = "preselection_pools/20261022/receipts/a_share_research_recommendation_pool.json"
    write(tmp_path, target, {"forged": True})
    with pytest.raises(ReadFailure, match="POOL_IDENTITY_OR_HASH_MISMATCH"):
        reader_for(tmp_path).read("pools", pool_params())


def test_manifest_change_during_read_fails_closed(tmp_path, monkeypatch):
    saved_pool(tmp_path)
    original = SavedFiles.read
    def changed(self, relative, maximum=64 * 1024 * 1024):
        value = original(self, relative, maximum)
        if relative.endswith("receipts/a_share_research_recommendation_pool.json"):
            write(tmp_path, "preselection_pools/20261022/manifest.json", {"changed": True})
        return value
    monkeypatch.setattr(SavedFiles, "read", changed)
    with pytest.raises(ReadFailure, match="POOL_CHANGED_DURING_READ"):
        reader_for(tmp_path).read("pools", pool_params())


@pytest.mark.parametrize("as_of,extra,status", [
    ("2026-10-23T09:00:00+08:00", {}, "valid"),
    ("2026-10-21T09:00:00+08:00", {}, "stale"),
    ("2026-10-23T11:00:00+08:00", {}, "unknown"),
    ("2026-10-23T09:00:00", {}, "unknown"),
    ("2026-10-23T09:00:00+08:00", {"cannot_confirm": ["NOT_ADMITTED"]}, "unknown"),
])
def test_recorded_time_and_source_gaps_control_status(tmp_path, as_of, extra, status):
    saved_pool(tmp_path, metadata={"as_of": as_of, **extra})
    result = reader_for(tmp_path).read("pools", pool_params())
    assert result["status"] == status
    assert result["as_of"] is None if "+08:00" not in as_of else result["as_of"] == as_of


def test_symlink_is_refused_even_when_target_is_inside_root(tmp_path):
    saved_pool(tmp_path)
    p = tmp_path / "preselection_pools/20261022/manifest.json"
    target = p.with_name("other.json")
    target.write_bytes(p.read_bytes())
    p.unlink()
    p.symlink_to(target)
    with pytest.raises(ReadFailure, match="SAVED_DATA_UNREADABLE"):
        reader_for(tmp_path).read("pools", pool_params())


def test_v4_down_does_not_serve_saved_data_as_live(tmp_path):
    saved_pool(tmp_path)
    reader = SavedReader(Bindings(tmp_path, tmp_path), available=lambda: False)
    with pytest.raises(ReadFailure, match="V4_UNAVAILABLE"):
        reader.read("pools", pool_params())


def test_source_size_and_deadline_limits(tmp_path):
    import time
    write(tmp_path, "fixture.json", {"long": "x" * 1024})
    with pytest.raises(ReadFailure, match="TOO_LARGE"):
        SavedFiles(tmp_path, time.monotonic() + 5, []).read("fixture.json", 100)
    with pytest.raises(ReadFailure, match="READ_TIMEOUT"):
        SavedFiles(tmp_path, time.monotonic() - 1, []).read("fixture.json")


def test_all_saved_file_opens_are_readonly_without_creation(tmp_path, monkeypatch):
    import os
    saved_pool(tmp_path)
    original = os.open
    calls = []
    def guarded(path, flags, *args, **kwargs):
        assert flags & os.O_ACCMODE == os.O_RDONLY
        assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        calls.append(path)
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", guarded)
    reader_for(tmp_path).read("pools", pool_params())
    assert calls


def test_saved_plan_hash_date_and_stock_projection(tmp_path):
    plan = {"schema_version": "v4.manager_workbench.v1", "context": {"target_date": "20261022", "phase": "INTRADAY", "rules_version": "FROZEN"},
            "run_id": "fixture", "available_at": "2026-10-22T15:00:00+08:00", "gaps": [],
            "stocks": [{"symbol": "HK.00001", "name": "fixture", "reasons": ["saved fact", "/Users/private/file", "/tmp/private", "/秘密/文件"],
                        "account": "must not leave", "api_key": "must not leave"}]}
    plan["product_sha256"] = digest(plan)
    write(tmp_path, "snapshots/fixture.json", plan)
    write(tmp_path, "pointers/20261022/INTRADAY.json", {"run_id": "fixture", "product_sha256": plan["product_sha256"]})
    p = dict(trade_date="20261022", market="HK", phase="INTRADAY", code="HK.00001")
    result = reader_for(tmp_path).read("research", p)
    row = result["rows"][0]
    assert result["as_of"].endswith("+08:00") and row["reasons"] == ["saved fact"]
    assert row["summary_fields_omitted"] is True
    assert "account" not in row and "api_key" not in row
    assert result["version"]["rules"] == "FROZEN"
    plan["context"]["target_date"] = "20261021"
    write(tmp_path, "snapshots/fixture.json", plan)
    with pytest.raises(ReadFailure, match="PLAN_IDENTITY_OR_HASH_MISMATCH"):
        reader_for(tmp_path).read("research", p)


def saved_delivery(root):
    job = "b" * 32
    schema = "v4.manager_workbench.announcement_delivery.v1"
    payload = {"schema": schema, "job_id": job, "target_trade_date": "20261021", "state": "PARTIAL",
               "stocks": [{"symbol": "HK.00001", "name": "fixture", "reasons": ["saved fact"],
                           "raw_model_config": {"secret": "must not leave"},
                           "articles": [{"article_id": "fixture-article", "title": "saved title", "source_date": "2026-10-20",
                                         "source_sha256": "a" * 64, "body_sha256": "c" * 64,
                                         "result_ref": "/Users/private/output", "body": "must not leave"}]}]}
    raw = canonical(payload)
    value_sha = hashlib.sha256(raw).hexdigest()
    base = f"announcement_flash/jobs/{job}/deliveries"
    write(root, "cursors/announcement_flash_delivery_index.json", {"items": [{"job_id": job, "target_date": "20261021"}]})
    write(root, f"{base}/{value_sha}.json", payload)
    write(root, f"{base}/latest.json", {"schema": schema, "job_id": job, "sha256": value_sha,
                                      "artifact_ref": f"{base}/{value_sha}.json"})
    return base, value_sha


def test_saved_announcement_preserves_unknown_and_only_summary_fields(tmp_path):
    saved_delivery(tmp_path)
    result = reader_for(tmp_path).read("announcements", dict(trade_date="20261021", market="HK", limit=20, offset=0))
    assert result["status"] == "unknown" and result["as_of"] is None
    assert result["coverage"]["total"] == 1
    assert result["rows"][0]["articles"][0]["source_sha256"] == "a" * 64
    serialized = json.dumps(result)
    assert "raw_model_config" not in serialized and "/Users/" not in serialized and "must not leave" not in serialized


def test_saved_announcement_cannot_fallback_dates_or_ignore_bad_hash(tmp_path):
    base, value_sha = saved_delivery(tmp_path)
    with pytest.raises(ReadFailure, match="SAVED_DELIVERY_NOT_FOUND"):
        reader_for(tmp_path).read("announcements", dict(trade_date="20261022", market="HK"))
    write(tmp_path, f"{base}/{value_sha}.json", {"tampered": True})
    with pytest.raises(ReadFailure, match="DELIVERY_IDENTITY_OR_HASH_MISMATCH"):
        reader_for(tmp_path).read("announcements", dict(trade_date="20261021", market="HK"))


def test_openapi_is_exact_get_only_and_not_deployed():
    app = create_app(Mock(), lambda: TEST_TOKEN)
    doc = openapi_document(app)
    assert len(doc["paths"]) == 5
    assert doc["servers"][0]["url"].endswith(".invalid")
    for path, methods in doc["paths"].items():
        assert set(methods) == {"get"}
        assert methods["get"]["security"] == ([] if path == "/health" else [{"V4ReadOnlyBearer": []}])
    assert doc["components"]["securitySchemes"]["V4ReadOnlyBearer"]["scheme"] == "bearer"
