import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from v4.manager_workbench import store as storage
from v4.manager_workbench.config import WorkbenchConfig
from v4.manager_workbench.contracts import (
    Coverage, InputBatch, JobState, Lane, LaneResult, LaneState, Phase, canonical, digest,
)
from v4.manager_workbench.service import ManagerService
from v4.manager_workbench.store import StorageConflict, StorageUnavailable, WorkbenchStore


DATE = "20261113"
CUTOFF = datetime.fromisoformat("2026-11-13T18:00:00+08:00")
LANES = [Lane.OVERSOLD, Lane.STAGE_REFERENCE]


class Engines:
    __name__ = "v4.manager_workbench.engines.test"

    def __init__(self):
        self.loads = 0
        self.executions = []
        self.fail_stage = False
        self.source_sha = "a" * 64

    def load_inputs(self, context, _adapters):
        self.loads += 1
        return [InputBatch(
            context=context, lane=lane, universe_ref=None,
            records=[{"symbol": "HK.00001", "text": "实际输入" * 16384}],
            evidence_refs=[], input_sha256=self.source_sha, scope_description="replay fixture",
            coverage=Coverage(scope_count=1),
        ) for lane in LANES]

    def run_lanes(self, context, inputs, _audit):
        self.executions.append(tuple(inputs))
        results = {}
        for name, batch in inputs.items():
            failed = self.fail_stage and batch.lane == Lane.STAGE_REFERENCE
            results[name] = LaneResult(
                lane=batch.lane, state=LaneState.FAILED if failed else LaneState.READY_EMPTY,
                rows=[], gaps=["FIXTURE_STAGE_FAILURE"] if failed else [],
                coverage=batch.coverage, input_sha256=batch.input_sha256,
                rules_version=context.rules_version, run_id=context.scope_refs["run_id"],
            )
        return results

    @staticmethod
    def merge_decisions(_context, _lanes):
        return []


def _service(tmp_path, engines):
    return ManagerService(WorkbenchConfig(state_root=tmp_path, workers=1), object(), engines, object())


def _submit(service, *, cutoff=CUTOFF, lanes=LANES, scope_refs=None):
    return service.submit(DATE, Phase.MANUAL, cutoff=cutoff, lanes=lanes, scope_refs=scope_refs)


def _await(service, job):
    # All submitted workers are ahead of this barrier; this test slot serializes.
    service.jobs.pool.submit(lambda: None).result(timeout=5)
    return service.store.get_job(job.job_id)


def _record_writes(monkeypatch, store):
    writes = []
    original = store.io.write_bytes

    def write(relative, raw, **kwargs):
        if relative.startswith(("input_snapshots/", "checkpoints/", "overlay_blobs/", "attempts/")):
            writes.append((relative, len(raw)))
        return original(relative, raw, **kwargs)

    monkeypatch.setattr(store.io, "write_bytes", write)
    return writes


def test_normal_jobs_write_once_and_reuse_before_any_input_write(tmp_path, monkeypatch):
    engines = Engines()
    service = _service(tmp_path, engines)
    writes = _record_writes(monkeypatch, service.store)
    try:
        first = _await(service, _submit(service))
        assert first.state == JobState.SUCCEEDED
        plan = service.store.read_plan(first.run_id)
        sha = plan.changes["input_snapshot_sha256"]
        body, verified = service.store.load_input_checkpoint(first.job_id)
        assert verified == digest(body) == sha
        assert service.store.load_input(sha) == body
        input_writes = [entry for entry in writes if not entry[0].startswith("attempts/")]
        assert input_writes[0][0] == f"input_snapshots/{sha}.json" and input_writes[0][1] > 100_000
        assert input_writes[1][0] == f"checkpoints/{first.job_id}/LOAD_INPUTS.json" and input_writes[1][1] < 256
        assert service.store.load_checkpoint(first.job_id, "PUBLISH") is not None
        files_before = tuple(writes)
        reused = _await(service, _submit(service, cutoff=CUTOFF.replace(minute=5)))
        assert reused.job_id != first.job_id and reused.run_id == first.run_id
        assert reused.state == JobState.SUCCEEDED and reused.step == "DONE"
        assert service.store.read_plan(reused.run_id).product_sha256 == plan.product_sha256
        assert service.store.load_input_checkpoint(reused.job_id) == (None, None)
        assert all(path.startswith("attempts/") for path, _ in writes[len(files_before):])
        assert engines.loads == 2 and len(engines.executions) == 1

        # A changed producer SHA is a cache miss, even with the same date and lanes.
        engines.source_sha = "b" * 64
        fresh = _await(service, _submit(service))
        assert fresh.state == JobState.SUCCEEDED and fresh.run_id != first.run_id
        assert len(list((service.store.root / "input_snapshots").iterdir())) == 2
    finally:
        service.stop()


def test_partial_retry_reuses_legacy_inline_body_and_only_reexecutes_failed_lane(tmp_path, monkeypatch):
    engines = Engines()
    engines.fail_stage = True
    service = _service(tmp_path, engines)
    writes = _record_writes(monkeypatch, service.store)
    try:
        # Use the normal old writer shape for this original PARTIAL generation.
        with monkeypatch.context() as patch:
            def write_legacy(job_id, data, *, input_sha=None):
                assert input_sha is None
                sha = digest(data)
                service.store.save_input(sha, data)
                service.store.save_checkpoint(job_id, "LOAD_INPUTS", data)
                return sha

            patch.setattr(service.store, "save_input_checkpoint", write_legacy)
            first = _await(service, _submit(service))
        assert first.state == JobState.PARTIAL and first.retryable
        before = service.store._path("checkpoints", first.job_id, "LOAD_INPUTS").read_bytes()
        body, original_sha = service.store.load_input_checkpoint(first.job_id)
        assert digest(body) == original_sha
        source_lane = service.store.load_checkpoint(first.job_id, "lane_OVERSOLD")
        source_publish = service.store.load_checkpoint(first.job_id, "PUBLISH")
        writes.clear()
        engines.fail_stage = False
        resumed = _await(service, service.retry(first.job_id))
        assert resumed.state == JobState.SUCCEEDED and resumed.job_id != first.job_id
        plan = service.store.read_plan(resumed.run_id)
        assert plan.changes["input_snapshot_sha256"] == original_sha
        assert service.store.load_input_checkpoint(resumed.job_id) == (body, original_sha)
        assert service.store._path("checkpoints", first.job_id, "LOAD_INPUTS").read_bytes() == before
        assert service.store.load_checkpoint(first.job_id, "PUBLISH") == source_publish
        assert service.store.load_checkpoint(resumed.job_id, "lane_OVERSOLD") == {
            **source_lane, "run_id": resumed.run_id
        }
        assert not any(path.startswith("input_snapshots/") for path, _ in writes)
        ref_bytes = next(size for path, size in writes if path == f"checkpoints/{resumed.job_id}/LOAD_INPUTS.json")
        assert ref_bytes < 256
        assert engines.loads == 1
        assert engines.executions == [("OVERSOLD", "STAGE_REFERENCE"), ("STAGE_REFERENCE",)]
    finally:
        service.stop()


def test_input_commit_interruption_and_concurrent_writers_do_not_stage_body_again(tmp_path, monkeypatch):
    store = WorkbenchStore(tmp_path)
    body = {"context": {}, "batches": [{"records": ["x" * 100_000]}]}
    sha = digest(body)
    writes = _record_writes(monkeypatch, store)
    actual_write = store.io.write_bytes

    def interrupt(relative, raw, **kwargs):
        if relative.endswith("LOAD_INPUTS.json"):
            raise OSError("simulated interruption after body publication")
        return actual_write(relative, raw, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(store.io, "write_bytes", interrupt)
        with pytest.raises(OSError, match="simulated interruption"):
            store.save_input_checkpoint("first", body)
    assert store.load_input_checkpoint("first") == (None, None)
    assert store.load_input(sha) == body
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda job: store.save_input_checkpoint(job, body),
                                ["first", "first", "second", "second"]))
    assert results == [sha] * 4
    assert sorted(relative for relative, _ in writes) == [
        "checkpoints/first/LOAD_INPUTS.json", "checkpoints/second/LOAD_INPUTS.json",
        f"input_snapshots/{sha}.json",
    ]
    with pytest.raises(StorageConflict, match="INPUT_CHECKPOINT_COLLISION"):
        store.save_input_checkpoint("first", {"context": {"changed": True}, "batches": []})
    assert store.load_input_checkpoint("first") == store.load_input_checkpoint("second") == (body, sha)


def test_overlay_is_written_once_across_attempts_and_batch_contexts(tmp_path, monkeypatch):
    engines = Engines()
    service = _service(tmp_path, engines)
    store = service.store
    writes = _record_writes(monkeypatch, store)
    overlay = [{"value": "x" * 150_000, "flag": 1}]
    identities = ["HK.00001"]
    scope = {
        "US_MAPPING": {"full_overlay_projection": overlay, "full_overlay_stock_identities": identities},
        "owner_bindings": {"us_mapping": {
            "full_overlay_projection": [dict(overlay[0])], "full_overlay_stock_identities": list(identities)}},
    }
    try:
        first = _await(service, _submit(service, scope_refs=scope))
        assert first.state == JobState.SUCCEEDED
        assert first.context.scope_refs["US_MAPPING"] == scope["US_MAPPING"]
        assert first.context.scope_refs["owner_bindings"] == scope["owner_bindings"]
        journal = store._read(store._path("attempts", first.job_id))
        raw_scope = journal["context"]["scope_refs"]
        sha = digest(overlay)
        marker = {"schema": storage._OVERLAY_REF_SCHEMA, "sha256": sha}
        assert raw_scope["US_MAPPING"]["full_overlay_projection"] == marker
        assert raw_scope["owner_bindings"]["us_mapping"]["full_overlay_projection"] == marker
        assert [p for p, _ in writes if p.startswith("overlay_blobs/")] == [
            f"overlay_blobs/{sha}.json", f"overlay_blobs/{digest(identities)}.json",
        ]
        body, input_sha = store.load_input_checkpoint(first.job_id)
        assert input_sha == digest(body)
        physical = store.io.read_bytes(f"input_snapshots/{input_sha}.json")
        assert json.loads(physical)["schema"] == storage._INPUT_BODY_SCHEMA
        assert len(physical) < len(canonical(body)) - 6 * 149_000
        for context in [body["context"], *(batch["context"] for batch in body["batches"])]:
            assert context["scope_refs"]["US_MAPPING"] == scope["US_MAPPING"]
        assert all(size < 3_000 for path, size in writes if path.startswith("attempts/"))
        start = len(writes)
        reused = _await(service, _submit(service, scope_refs=scope))
        assert reused.run_id == first.run_id
        assert all(path.startswith("attempts/") and size < 3_000 for path, size in writes[start:])
        projection = store.root / "overlay_blobs" / f"{sha}.json"
        projection.write_bytes(canonical([{"value": "unverified"}]))
        with pytest.raises(StorageUnavailable, match="OVERLAY_SHA_MISMATCH"):
            store.get_job(first.job_id)
        with pytest.raises(StorageUnavailable, match="OVERLAY_SHA_MISMATCH"):
            store.load_input_checkpoint(first.job_id)
    finally:
        service.stop()


@pytest.mark.parametrize("problem", ["missing", "sha_mismatch", "oversize", "schema", "traversal"])
def test_reference_reader_rejects_bad_targets_without_fallback(tmp_path, monkeypatch, problem):
    store = WorkbenchStore(tmp_path)
    sha = store.save_input_checkpoint("job", {"context": {}, "batches": []})
    target = store._path("input_snapshots", sha)
    checkpoint = store._path("checkpoints", "job", "LOAD_INPUTS")
    ref = store.load_checkpoint("job", "LOAD_INPUTS")
    if problem == "missing":
        target.unlink()
    elif problem == "sha_mismatch":
        target.write_bytes(canonical({"context": {"modified": True}, "batches": []}))
    elif problem == "oversize":
        monkeypatch.setattr(storage, "_INPUT_READ_LIMIT", target.stat().st_size - 1)
        with pytest.raises(ValueError, match="OWNED_FILE_TOO_LARGE"):
            store.load_input(sha)
        return
    elif problem == "schema":
        checkpoint.write_bytes(canonical({**ref, "schema": "unknown"}))
    else:
        checkpoint.write_bytes(canonical({**ref, "input_snapshot_sha256": "../unowned"}))
    with pytest.raises((StorageUnavailable, ValueError), match="INPUT_"):
        store.load_input_checkpoint("job")
