from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.manager_workbench.api import PREFIX, create_router
from v4.manager_workbench.contracts import Counts, Phase, RunContext, seal_snapshot
from v4.manager_workbench.store import WorkbenchStore


def _large_snapshot(run_id, padding_bytes):
    context = RunContext(
        target_date="20261020",
        phase=Phase.MANUAL,
        cutoff="2026-10-19T18:10:08+08:00",
        trigger="MANUAL",
        rules_version="TEST_RULES_1",
        scope_refs={"oversize_readback_probe": "x" * padding_bytes},
    )
    return seal_snapshot({
        "context": context.model_dump(mode="json"),
        "run_id": run_id,
        "input_sha256": "a" * 64,
        "generated_at": "2026-10-19T18:10:08+08:00",
        "available_at": "2026-10-19T18:10:08+08:00",
        "lanes": [],
        "stocks": [],
        "counts": Counts().model_dump(mode="json"),
        "changes": {},
        "review_refs": [],
        "gaps": [],
    })


def test_large_publish_checkpoint_and_plan_round_trip_through_api(tmp_path):
    store = WorkbenchStore(tmp_path)
    run_id = "oversize-publish-regression"
    snapshot = _large_snapshot(run_id, 64 * 1024 * 1024 + 1)
    payload = snapshot.model_dump(mode="json")

    store.save_checkpoint(run_id, "PUBLISH", payload)
    assert store.load_checkpoint(run_id, "PUBLISH")["product_sha256"] == snapshot.product_sha256
    store.save_checkpoint(run_id, "PUBLISH", payload)  # immutable collision readback

    assert store.commit_plan(snapshot).product_sha256 == snapshot.product_sha256
    assert store.commit_plan(snapshot).product_sha256 == snapshot.product_sha256  # snapshot collision readback
    assert store.get_plan("20261020", Phase.MANUAL.value, run_id).product_sha256 == snapshot.product_sha256

    service = SimpleNamespace(store=store, config=SimpleNamespace(shared_root=tmp_path / "shared"))
    app = FastAPI()
    app.include_router(create_router(service))
    response = TestClient(app).get(
        PREFIX + "/days/20261020",
        params={"phase": Phase.MANUAL.value, "run_id": run_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["snapshot"]["product_sha256"] == snapshot.product_sha256
    assert store._catalog(snapshot).exists()
    assert store._read(store._path("pointers", "20261020", "MANUAL"))["run_id"] == run_id


def test_non_publish_checkpoint_read_keeps_default_limit(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path)
    store.save_checkpoint("small-run", "LOAD_INPUTS", {"ok": True})
    requested_limits = []
    read_bytes = store.io.read_bytes

    def record_limit(relative, *, max_bytes=64 * 1024 * 1024):
        requested_limits.append(max_bytes)
        return read_bytes(relative, max_bytes=max_bytes)

    monkeypatch.setattr(store.io, "read_bytes", record_limit)
    assert store.load_checkpoint("small-run", "LOAD_INPUTS") == {"ok": True}
    assert requested_limits == [64 * 1024 * 1024]
