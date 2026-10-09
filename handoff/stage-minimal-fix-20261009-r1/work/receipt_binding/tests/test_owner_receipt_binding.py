from __future__ import annotations

import builtins
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "after/source"
sys.path.insert(0, str(ROOT / "references"))
from infrastructure.owned_io import SafeRoot


def canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_receipts(variant):
    package_name = "_receipt_after_" + variant
    package = types.ModuleType(package_name)
    package.__path__ = []
    sys.modules[package_name] = package
    namespace = types.ModuleType(package_name + "._namespace")
    namespace.read_global = lambda scope, name: scope.get(name, getattr(builtins, name, None))
    sys.modules[namespace.__name__] = namespace
    spec = importlib.util.spec_from_file_location(package_name + ".runner_receipts", SOURCE / variant / "stage_center/_runner_parts/runner_receipts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Deadline:
    def __init__(self):
        self.writes = []
        self.downgrade = False

    def before_receipt(self, payload):
        result = deepcopy(payload)
        if self.downgrade:
            result.update(status="PARTIAL_COMMIT_RETRY_REQUIRED", deadline_status="EXCEEDED")
        return result

    def receipt_written(self, path, result):
        assert json.loads(path.read_bytes()) == result
        self.writes.append(path)


@pytest.fixture(params=["actual_stage", "canonical"])
def owner(request, tmp_path):
    module = load_receipts(request.param)
    root = tmp_path / "receipts"
    config = types.SimpleNamespace(receipt_root=root, selection_root=tmp_path / "selections", backfill_run_id=None)
    runner = types.SimpleNamespace(config=config, _receipt_path=lambda date, stage: root / date / stage / "receipt.json")
    deadline = Deadline()

    def atomic(path, value):
        SafeRoot(path.parent).write_bytes(path.name, (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode())

    scope = {"_deadline": deadline, "_atomic_json": atomic, "SAFETY_FLAGS": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}}

    def write(payload):
        return module._StageCenterRunner__write_receipt_body(scope, runner, payload, "20261009", "STAGE_0940_0945")

    return module, runner, scope, deadline, write


def payload():
    return {"trade_date": "20261009", "stage_id": "STAGE_0940_0945", "dispatch_mode": "NATURAL", "due_status": "DUE", "status": "PARTIAL_WITH_ROWS", "markets": {"A_SHARE": {"selected_rows": 10, "requested_rows": 216, "observed_rows": 206}, "HK_CONNECT": {"selected_rows": 0, "status": "CANNOT_CONFIRM", "cannot_confirm": ["HK D1 status must be STRICT_0_2_READY"]}}, "write_performed": True}


def archive(runner, result):
    history = result["receipt_history"]
    assert history["schema_version"] == "stage_center.runner.history_ref.v1"
    assert history["relative_path"] == "20261009/STAGE_0940_0945/attempt_evidence/recorded-" + history["sha256"] + "/RECEIPT.json"
    raw = SafeRoot(runner.config.receipt_root).read_bytes(history["relative_path"])
    assert hashlib.sha256(raw).hexdigest() == history["sha256"]
    archived = json.loads(raw)
    assert archived == {k: v for k, v in result.items() if k != "receipt_history"}
    return raw


def test_owner_time_is_actual_write_time_and_old_payload_is_not_mutated(owner):
    _, runner, _, deadline, write = owner
    before = datetime.now(timezone.utc)
    original = payload()
    original["recorded_at"] = "2026-10-08T09:40:00+08:00"
    original["receipt_history"] = {"sha256": "f" * 64, "relative_path": "old"}
    frozen = deepcopy(original)
    result = write(original)
    assert before <= datetime.fromisoformat(result["recorded_at"]) <= datetime.now(timezone.utc)
    assert result["record_time_source"] == "OWNER_WRITE_CLOCK_UTC"
    assert original == frozen
    assert result["markets"] == frozen["markets"]
    assert result.get("natural_verified") is not True and result.get("execution_verified") is not True
    archive(runner, result)
    assert len(deadline.writes) == 1


def test_rewrites_keep_first_history_and_bind_final_deadline_payload(owner):
    _, runner, _, deadline, write = owner
    first = write(payload())
    first_raw = archive(runner, first)
    deadline.downgrade = True
    second = write(first)
    archive(runner, second)
    assert second["status"] == "PARTIAL_COMMIT_RETRY_REQUIRED"
    assert second["receipt_history"] != first["receipt_history"]
    assert SafeRoot(runner.config.receipt_root).read_bytes(first["receipt_history"]["relative_path"]) == first_raw
    assert second["markets"]["A_SHARE"]["selected_rows"] == 10


def test_original_deadline_final_rewrite_keeps_both_owner_archives(owner):
    _, runner, scope, _, write = owner
    spec = importlib.util.spec_from_file_location("_receipt_reference_deadline", ROOT / "references/stage_center/end_to_end_deadline.py")
    deadline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deadline)
    clock = [100]
    trace = deadline.Trace(entry_ns=1, entry_wall_ns=1_790_000_000_000_000_000,
                           policy="enforce", mono=lambda: clock[0],
                           wall=lambda: 1_790_000_000_000_000_000 + clock[0])
    deadline.set_current(trace)
    scope["_deadline"] = deadline
    try:
        first = write(payload())
        first_raw = archive(runner, first)
        clock[0] = deadline.BUDGET_NS + 100
        path = runner._receipt_path("20261009", "STAGE_0940_0945")
        completed = deadline.complete_receipt(path, first, rewrite=write)
        stored = json.loads(path.read_bytes())
        assert completed["deadline_status"] == "EXCEEDED"
        assert stored["status"] == "PARTIAL_COMMIT_RETRY_REQUIRED"
        assert stored["receipt_history"] != first["receipt_history"]
        archive(runner, stored)
        assert SafeRoot(runner.config.receipt_root).read_bytes(first["receipt_history"]["relative_path"]) == first_raw
        assert not deadline.pending_receipt_marker(path).exists()
    finally:
        deadline.set_current(None)
        trace.close()


def test_identical_archive_is_idempotent_but_conflict_refuses_pointer_replace(owner, monkeypatch):
    module, runner, _, _, write = owner
    monkeypatch.setattr(module, "_owner_write_time", lambda: "2026-10-09T03:45:00.123456+00:00")
    first = write(payload())
    assert write(payload()) == first
    old_pointer = runner._receipt_path("20261009", "STAGE_0940_0945").read_bytes()
    path = runner.config.receipt_root / first["receipt_history"]["relative_path"]
    path.write_bytes(b"tampered immutable history")
    with pytest.raises(ValueError, match="archive conflict"):
        write(payload())
    assert runner._receipt_path("20261009", "STAGE_0940_0945").read_bytes() == old_pointer


def test_archive_publication_failure_never_publishes_pointer(owner, monkeypatch):
    _, runner, _, deadline, write = owner
    original_write = SafeRoot.write_bytes

    def fail_archive(self, relative, raw, **kwargs):
        if kwargs.get("require_absent"):
            raise OSError("injected archive fsync failure")
        return original_write(self, relative, raw, **kwargs)

    monkeypatch.setattr(SafeRoot, "write_bytes", fail_archive)
    with pytest.raises(OSError, match="archive fsync failure"):
        write(payload())
    assert not runner._receipt_path("20261009", "STAGE_0940_0945").exists()
    assert not deadline.writes


def test_symlink_archive_ancestry_is_refused(owner, tmp_path):
    _, runner, _, _, write = owner
    slot = runner.config.receipt_root / "20261009/STAGE_0940_0945"
    slot.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (slot / "attempt_evidence").symlink_to(outside, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        write(payload())
    assert not list(outside.iterdir())
    assert not (slot / "receipt.json").exists()


def test_slot_identity_mismatch_is_refused(owner):
    _, runner, _, _, write = owner
    wrong = payload()
    wrong["trade_date"] = "20261008"
    with pytest.raises(ValueError, match="date/stage"):
        write(wrong)
    assert not runner.config.receipt_root.exists()


def candidate(**kwargs):
    values = dict(trade_date="20261009", run_id="candidate-real", current_relative="current/20261009/A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3/current.json", current_sha256="0" * 64, artifact_sha256="1" * 64, manifest_sha256="2" * 64, receipt_sha256="3" * 64, artifact_bytes_sha256="4" * 64, manifest_bytes_sha256="5" * 64, receipt_bytes_sha256="6" * 64, commit_marker_bytes_sha256="7" * 64, digest_mode="RAW_BYTES_V1", strict_schema="v3", commit_id="8" * 64, codes=tuple(f"A.{i:06d}" for i in range(216)), source_evidence=("current", "artifact", "manifest", "receipt", "commit"))
    values.update(kwargs)
    return types.SimpleNamespace(**values)


def test_candidate_binding_preserves_216_rows_and_distinct_digest_semantics(owner):
    module, *_ = owner
    result = module._candidate_input_bindings(candidate(), None, ("A_SHARE", "HK_CONNECT"), a_candidate_missing=False)
    assert set(result) == {"A_SHARE"}
    actual = result["A_SHARE"]
    assert actual["row_count"] == 216
    assert actual["artifact_canonical_sha256"] == "1" * 64
    assert actual["artifact_bytes_sha256"] == "4" * 64
    assert actual["manifest_canonical_sha256"] == "2" * 64
    assert actual["manifest_bytes_sha256"] == "5" * 64


def test_hk_plan_adapter_never_fabricates_a_trio(owner):
    module, *_ = owner
    hk = types.SimpleNamespace(trade_date="20261009", source_run_id="hk-real", sha256="a" * 64, codes=("HK.00001",), evidence=("hk_d1_json_sha256=" + "a" * 64,))
    result = module._candidate_input_bindings(candidate(), hk, ("A_SHARE", "HK_CONNECT"), a_candidate_missing=True)
    assert set(result) == {"HK_CONNECT"}
    assert "manifest_bytes_sha256" not in result["HK_CONNECT"]
    assert result["HK_CONNECT"]["trio_status"] == "NOT_EXPOSED_BY_STAGE_UNIVERSE_BINDING"


def test_old_candidate_missing_byte_fields_does_not_relabel_canonical_hash(owner):
    module, *_ = owner
    old = candidate(artifact_bytes_sha256=None, manifest_bytes_sha256=None, receipt_bytes_sha256=None)
    item = module._candidate_input_bindings(old, None, ("A_SHARE",), a_candidate_missing=False)["A_SHARE"]
    assert "manifest_bytes_sha256" not in item
    assert item["manifest_canonical_sha256"] == "2" * 64


def make_selection_store(tmp_path):
    """Real bounded file reads around the original store verifier's seam.

    This seam tests the new binding and race check, not the already tested
    algorithm/SelectionStore internals. No source verification is stubbed as
    a claimed Mac integration test.
    """
    root = tmp_path / "selection-store"
    prefix = "selection_runs/20261009/A_SHARE_SELECTION_STAGE_0940_0945/run-real"
    original = dict(run_id="run-real", artifact_id="artifact-real", algorithm_sha256="a" * 64, raw_artifact_sha256="b" * 64, selected_rows=10)
    manifest = {"selection_envelope": original, "role": "selection"}
    receipt = {"manifest_sha256": canonical(manifest), "run_id": "run-real"}
    artifact = b"symbol,rank\nA.000001,1\n"
    # Indented JSON deliberately differs from canonical digest bytes.
    io = SafeRoot(root)
    io.write_bytes(prefix + "/artifact.csv", artifact)
    io.write_bytes(prefix + "/manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    io.write_bytes(prefix + "/receipt.json", (json.dumps(receipt, indent=2) + "\n").encode())
    verified = dict(envelope=original, artifact_relative=prefix + "/artifact.csv", artifact_sha256=hashlib.sha256(artifact).hexdigest(), manifest_sha256=canonical(manifest), receipt_sha256=canonical(receipt))
    store = types.SimpleNamespace(root=root, _verify_run=lambda *args: deepcopy(verified))
    return store, original, verified


def test_selection_trio_binds_real_bytes_and_original_store_canonical_hashes(owner, tmp_path):
    module, runner, scope, _, write = owner
    store, selection, _ = make_selection_store(tmp_path)
    scope["SelectionStore"] = lambda root: store
    original = payload()
    original["markets"]["A_SHARE"].update(selection)
    result = write(original)
    bound = result["selection_artifacts"]["A_SHARE"]
    assert bound["manifest_canonical_sha256"] != bound["manifest_bytes_sha256"]
    assert bound["receipt_canonical_sha256"] != bound["receipt_bytes_sha256"]
    for part in ("artifact", "manifest", "receipt"):
        raw = SafeRoot(store.root).read_bytes(bound[part + "_relative"])
        assert hashlib.sha256(raw).hexdigest() == bound[part + "_bytes_sha256"]
    assert bound["selected_rows"] == 10
    assert "HK_CONNECT" not in result["selection_artifacts"]
    assert result["markets"] == original["markets"]
    archive(runner, result)


@pytest.mark.parametrize("part", ["artifact.csv", "manifest.json", "receipt.json"])
def test_selection_changed_after_verification_is_not_bound(owner, tmp_path, part):
    module, _, _, _, _ = owner
    store, selection, verified = make_selection_store(tmp_path)
    path = store.root / Path(verified["artifact_relative"]).parent / part
    if part.endswith("json"):
        path.write_text('{"tampered":true}\n')
    else:
        path.write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="changed after"):
        module._selection_artifact_binding(store, "20261009", "STAGE_0940_0945", "A_SHARE", selection)


def test_selection_identity_conflict_does_not_erase_computed_a_rows(owner, tmp_path):
    _, runner, scope, _, write = owner
    store, selection, _ = make_selection_store(tmp_path)
    scope["SelectionStore"] = lambda root: store
    original = payload()
    original["markets"]["A_SHARE"].update(selection, raw_artifact_sha256="c" * 64)
    result = write(original)
    assert not result["selection_artifacts"]
    assert "identity differs" in result["selection_binding_errors"]["A_SHARE"]
    assert result["markets"]["A_SHARE"]["selected_rows"] == 10
    assert result["markets"]["HK_CONNECT"]["selected_rows"] == 0
    archive(runner, result)


def test_stale_bindings_from_reused_payload_are_removed(owner):
    _, _, _, _, write = owner
    original = payload()
    original["selection_artifacts"] = {"A_SHARE": {"run_id": "stale-run"}, "HK_CONNECT": {"run_id": "stale-hk"}}
    result = write(original)
    assert result["selection_artifacts"] == {}


def test_scoped_recovery_keeps_sibling_input_and_selection_references(tmp_path):
    module = load_receipts("actual_stage")
    prior = payload()
    prior["input_bindings"] = {"A_SHARE": {"source": "original-a"}, "HK_CONNECT": {"source": "old-hk"}}
    prior["selection_artifacts"] = {"A_SHARE": {"run_id": "original-a"}, "HK_CONNECT": {"run_id": "old-hk"}}
    prior["selection_binding_errors"] = {"A_SHARE": "original-gap", "HK_CONNECT": "old-gap"}
    scope = module._ExecutionScope(("HK_CONNECT",), prior, 2, "RECOVERY")
    new = {"markets": {"A_SHARE": {"selected_rows": 999}, "HK_CONNECT": {"selected_rows": 10}}, "input_bindings": {"A_SHARE": {"source": "wrong-a"}, "HK_CONNECT": {"source": "new-hk"}}, "selection_artifacts": {"HK_CONNECT": {"run_id": "new-hk"}}, "selection_binding_errors": {}}
    result = scope.merge(new, "20261009", "STAGE_0940_0945")
    assert result["markets"]["A_SHARE"] == prior["markets"]["A_SHARE"]
    assert result["input_bindings"]["A_SHARE"] == prior["input_bindings"]["A_SHARE"]
    assert result["selection_artifacts"]["A_SHARE"] == prior["selection_artifacts"]["A_SHARE"]
    assert result["selection_artifacts"]["HK_CONNECT"] == {"run_id": "new-hk"}
    assert result["selection_binding_errors"] == {"A_SHARE": "original-gap"}
