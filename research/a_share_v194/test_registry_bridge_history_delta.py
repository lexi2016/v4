"""New-E receipt projection only; the official adapter is replaced by a stub."""
from contextlib import contextmanager
import json

import pytest

import registry_bridge as bridge


def test_history_bridge_rejects_old_projection_and_symlink(tmp_path, monkeypatch):
    new = tmp_path / "new"
    old = tmp_path / "old"
    new.mkdir(); old.mkdir()
    monkeypatch.setattr(bridge, "ROOT", tmp_path)
    monkeypatch.setattr(bridge, "HISTORY_ROOT", new)
    config = {"registry_projection": {"scope_root": str(new), "summary_root": str(tmp_path),
              "index_path": str(old / "REGISTRY_INDEX.json"), "receipt_dir": str(new)}}
    with pytest.raises(AssertionError, match="INDEX_OUTSIDE_SCOPE"):
        bridge.projection_binding(config)
    (new / "escape").symlink_to(old, target_is_directory=True)
    config["registry_projection"]["index_path"] = str(new / "escape/index.json")
    with pytest.raises(AssertionError, match="INDEX_OUTSIDE_SCOPE"):
        bridge.projection_binding(config)
    assert list(old.iterdir()) == []


def test_history_bridge_projects_new_scope_under_official_adapter_lock(tmp_path, monkeypatch):
    new = tmp_path / "new"
    for part in ("contracts", "receipts", "registry"):
        (new / part).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bridge, "ROOT", tmp_path)
    monkeypatch.setattr(bridge, "HISTORY_ROOT", new)
    previous = tmp_path / "old" / "REGISTRY_INDEX.json"
    previous.parent.mkdir(); previous.write_bytes(b"old immutable index\n")
    class Stub:
        held = False
        events = []
        registry_path = tmp_path / "contracts/EXPERIMENT_REGISTRY.jsonl"
        @contextmanager
        def _locked(self):
            assert not self.held
            self.held = True
            try:
                yield
            finally:
                self.held = False
        def _read_validated(self):
            assert self.held
            return json.dumps(self.events).encode(), self.events
        def _append_unlocked(self, raw, events, spec):
            assert self.held and events is self.events
            assert spec["registration_mode"] == "LIVE_EXECUTION"
            assert spec["event_type"] == "RUN_STARTED" and spec["truth_access"] == "NOT_READ"
            assert spec["deterministic_metrics"] == {"truth_positive_denominator": None, "selection_slots": None}
            self.events.append({**spec, "event_sha256": "e" * 64})
    adapter = Stub()
    monkeypatch.setattr(bridge, "bound_official_adapter", lambda config: adapter)
    config = dict(execution_id="NEW_HISTORY_01", route_id="NEW_HISTORY", track_id="A_SHARE", input_sha256="i" * 64,
                  code_sha256={}, input_identity={}, baseline_id="UNCHANGED", one_variable="HISTORY_BINDING",
                  signal_date_range=[], target_date_range=[], truth_access="NOT_READ", sealed_status="DIRECTION_ONLY",
                  runtime={}, registry_summary_key="new_history", frozen_source_bindings={},
                  registry_projection={"scope_root": str(new), "index_path": str(new / "registry/INDEX.json"),
                                       "receipt_dir": str(new / "receipts"), "summary_root": str(tmp_path)})
    cp = new / "contracts/run.json"
    cp.write_text(json.dumps(config))
    receipt = bridge.register(cp, "RUN_STARTED", "CANARY_START")
    assert receipt["event_sha256"] == "e" * 64
    assert len(adapter.events) == 1 and adapter.held is False
    assert json.loads((new / "registry/INDEX.json").read_text())["new_history"] == receipt
    assert json.loads((new / "receipts/NEW_HISTORY_01_CANARY_START_REGISTRY_RECEIPT.json").read_text()) == receipt
    assert previous.read_bytes() == b"old immutable index\n"
    with pytest.raises(AssertionError, match="RECEIPT_PATH_INVALID_OR_EXISTS"):
        bridge.register(cp, "RUN_STARTED", "CANARY_START")
    assert len(adapter.events) == 1
