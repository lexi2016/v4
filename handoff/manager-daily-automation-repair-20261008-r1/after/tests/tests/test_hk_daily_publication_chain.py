"""Research-only contracts for the actual HK child publication-chain gate."""
from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ops._macos_research_panel_daily_parts import hk_capture_gate as gate


ROOT = Path(__file__).resolve().parents[1]
ACTUAL_LAYER = ROOT / "runtime_layers/hk_child/ops/macos_research_panel_daily.py"
FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def _load_actual_layer():
    name = "_hk_actual_child_layer_test"
    module = sys.modules.get(name)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(name, ACTUAL_LAYER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_legacy_panel_only_lane_receipt_is_not_full_hk_ready(tmp_path):
    actual = _load_actual_layer()
    payload = {
        "schema_version": "v3.macos.research_panel_receipt.v1",
        "target_date": "20261008", "lane": "HK", "status": "READY",
        "row_count": 695, "coverage_rate": 1.0, "sha256": "a" * 64,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    assert actual._hk_lane_receipt_ready(tmp_path, "20261008", payload) is False


def test_historical_target_without_exact_capture_fails_before_live_collector(tmp_path, monkeypatch):
    actual = _load_actual_layer()
    args = SimpleNamespace(receipt_root=tmp_path / "receipts",
        hk_asset_root=tmp_path / "assets" / "hk_0_2",
        hk_tdx_root=tmp_path / "tdx")
    paths = {"--hk-updater-script": tmp_path / "v3_shared_data" / "scripts" / "update_hk_0_2_panel.py"}
    monkeypatch.setattr(gate, "_run_hk_capture_gate_body",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("live collector must not run")))

    result = gate.run_hk_capture_gate(actual.__dict__, target_date="20261007",
        args=args, authority_paths=paths, python_executable=Path(sys.executable))

    assert result["status"] == "FAILED"
    assert result["target_date"] == "20261007"
    assert result["failed_stage"] == "CAPTURE"
    assert result["failure_reasons"] == ["HK_HISTORICAL_MEMBERSHIP_CAPTURE_UNAVAILABLE"]
    assert not (tmp_path / "assets").exists()
    attempt = json.loads((args.receipt_root / "hk_publication" / "20261007" / "latest_attempt.json").read_text())
    assert attempt["status"] == "FAILED"
    assert attempt["target_date"] == "20261007"


def _publish_roleless_decoy_fixture(tmp_path, target="20261008"):
    safe = __import__("infrastructure.owned_io", fromlist=["SafeRoot"]).SafeRoot(tmp_path)
    chain_id = "a" * 32
    base = f"hk_publication/{target}/{chain_id}"
    safe.ensure_directory(base)
    refs = []
    for stage in gate.CHAIN_REQUIRED_STAGES:
        relative = f"{base}/{stage.lower()}.json"
        value = gate._seal({"schema_version": gate.CHAIN_SCHEMA,
            "target_date": target, "chain_id": chain_id, "stage": stage,
            "capture_run_id": "d" * 32,
            "status": "READY", "started_at": "2026-10-08T09:00:00+00:00",
            "finished_at": "2026-10-08T09:00:01+00:00", **FLAGS})
        raw = gate._canonical(value) + b"\n"
        safe.write_bytes(relative, raw, require_absent=True)
        refs.append({"stage": stage, "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    artifact = tmp_path / "authority" / "capture.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("synthetic immutable capture", encoding="utf-8")
    artifact_raw = artifact.read_bytes()
    summary = {"status": "READY", "target_date": target, "row_count": 600,
        "universe_count": 600, "coverage_rate": 1.0,
        "sha256": "b" * 64, "source_sha256": "c" * 64}
    terminal_relative = f"{base}/terminal.json"
    terminal = gate._seal({"schema_version": gate.CHAIN_SCHEMA,
        "status": "READY", "target_date": target, "chain_id": chain_id,
        "capture_run_id": "d" * 32, "started_at": "2026-10-08T09:00:00+00:00",
        "finished_at": "2026-10-08T09:01:00+00:00", "stages": refs,
        "artifact_refs": [{"path": str(artifact), "bytes": len(artifact_raw),
            "sha256": hashlib.sha256(artifact_raw).hexdigest(), "role": "CAPTURE"}],
        "lane_summary": summary, "daily_supplement": {"status": "PARTIAL_WITH_PENDING"},
        **FLAGS})
    terminal_raw = gate._canonical(terminal) + b"\n"
    safe.write_bytes(terminal_relative, terminal_raw, require_absent=True)
    pointer = gate._seal({"schema_version": gate.CHAIN_SCHEMA,
        "status": "READY", "target_date": target, "chain_id": chain_id,
        "terminal_relative": terminal_relative,
        "terminal_sha256": hashlib.sha256(terminal_raw).hexdigest(),
        "published_at": "2026-10-08T09:01:00+00:00", **FLAGS})
    safe.write_bytes(f"hk_publication/{target}/latest.json",
        gate._canonical(pointer) + b"\n", require_absent=True)
    return summary, pointer


def _publish_chain_fixture(tmp_path, target="20261008"):
    safe = __import__("infrastructure.owned_io", fromlist=["SafeRoot"]).SafeRoot(tmp_path)
    chain_id, capture_run_id, membership_run_id, master_run_id = (
        "a" * 32, "d" * 32, "e" * 24, "f" * 24)
    source_sha, universe_source_sha, capture_sha, binding_sha = (
        hashlib.sha256(value.encode()).hexdigest() for value in
        ("source", "membership-source", "capture", "binding"))
    store_root = tmp_path / "shared-data"
    panel_root = store_root / "assets" / "hk_0_2"
    master_root = store_root / "assets" / "hk_security_master"
    refs = []

    def artifact(path, role, value=None, raw=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = raw if raw is not None else gate._canonical(value) + b"\n"
        path.write_bytes(content)
        reference = {"path": str(path.resolve()), "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), "role": role}
        refs.append(reference)
        return reference

    def pointer_snapshot(source_path, role, value, snapshot_name):
        source_path = Path(source_path).resolve()
        source_path.parent.mkdir(parents=True, exist_ok=True)
        content = gate._canonical(value) + b"\n"
        source_path.write_bytes(content)
        snapshot_path = (tmp_path / "hk_publication" / target / chain_id / "snapshots" /
            snapshot_name)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(content)
        reference = {"path": str(snapshot_path.resolve()), "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), "role": role,
            "source_path": str(source_path), "source_sha256": hashlib.sha256(content).hexdigest(),
            "source_bytes": len(content), "snapshot_kind": "IMMUTABLE_POINTER_BYTES"}
        refs.append(reference)
        return reference

    capture = {"target_date": target, "status": "READY", "membership_status": "READY",
        "capture_run_id": capture_run_id, "capture_sha256": capture_sha,
        "source_sha256": source_sha, "code_count": 600, "quote_status": "READY"}
    capture_root = tmp_path / "capture" / target
    raw_ref = artifact(capture_root / "capture.json", "HK_SDK_CAPTURE_RAW", capture)
    capture_manifest = {"schema_version": "v3.macos.research_panel_hk_capture_manifest.v1",
        "target_date": target, "status": "READY", "capture_run_id": capture_run_id,
        "capture_sha256": capture_sha, "capture_raw_sha256": raw_ref["sha256"],
        "capture": capture}
    capture_manifest_ref = artifact(capture_root / "manifest.json",
        "HK_SDK_CAPTURE_MANIFEST", capture_manifest)

    universe_relative = f"universes/{target}/HK_CONNECT_FULL_MARKET.json"
    authority_base = f"universes/{target}/HK_CONNECT_FULL_MARKET.authority/{membership_run_id}"
    written_files = {}
    v2_docs = {
        f"{authority_base}/capture.json": {"schema_version": "v4.manager_hk_connect_capture.v2",
            "target_date": target, "trade_date": target, "effective_date": target,
            "capture_run_id": capture_run_id, "capture_sha256": capture_sha,
            "source_sha256": universe_source_sha, "code_count": 600},
        f"{authority_base}/manifest.json": {"schema_version": "v3_shared_data.hk_connect.authority.manifest.v2",
            "target_date": target, "trade_date": target, "effective_date": target,
            "capture_run_id": capture_run_id, "capture_sha256": capture_sha,
            "source_sha256": universe_source_sha, "run_id": membership_run_id,
            "code_count": 600, "status": "READY"},
        f"{authority_base}/receipt.json": {"schema_version": "v3_shared_data.hk_connect.authority.receipt.v2",
            "target_date": target, "trade_date": target, "effective_date": target,
            "capture_run_id": capture_run_id, "capture_sha256": capture_sha,
            "source_sha256": universe_source_sha, "run_id": membership_run_id,
            "code_count": 600, "status": "READY"},
        f"universes/{target}/HK_CONNECT_FULL_MARKET.current.json": {
            "schema_version": "v3_shared_data.hk_connect.authority.current.v2",
            "target_date": target, "trade_date": target, "effective_date": target,
            "capture_run_id": capture_run_id, "capture_sha256": capture_sha,
            "source_sha256": universe_source_sha, "run_id": membership_run_id,
            "code_count": 600, "status": "READY"},
        universe_relative: {"schema_version": "v3_shared_data.stage_universe.capture.v2",
            "market": "HK_CONNECT", "target_date": target, "trade_date": target,
            "effective_date": target, "capture_run_id": capture_run_id,
            "capture_sha256": capture_sha, "source_sha256": universe_source_sha,
            "code_count": 600},
    }
    for relative, value in v2_docs.items():
        reference = artifact(store_root / relative, "HK_CONNECT_V2_JSON", value)
        written_files[relative] = {"sha256": reference["sha256"],
            "size_bytes": reference["bytes"], "created": True}
    publication_relative = f"{authority_base}/publication.json"
    manifest_relative = f"{authority_base}/manifest.json"
    publication = {"schema_version": "v3_shared_data.hk_connect.authority.publication.v2",
        "target_date": target, "trade_date": target, "effective_date": target,
        "market": "HK_CONNECT", "status": "READY", "run_id": membership_run_id,
        "capture_run_id": capture_run_id, "capture_sha256": capture_sha,
        "artifact_relative": universe_relative,
        "artifact_sha256": written_files[universe_relative]["sha256"],
        "manifest_relative": manifest_relative}
    publication_ref = artifact(store_root / publication_relative,
        "HK_CONNECT_V2_PUBLICATION", publication)

    panel_relative = f"panels/{target}-panel/panel.parquet"
    panel_manifest_relative = f"panels/{target}-panel/manifest.json"
    panel_bytes = b"synthetic panel bytes for strict reference test\n"
    panel_ref = artifact(panel_root / panel_relative, "HK_PANEL_PARQUET", raw=panel_bytes)
    panel_manifest = {"asset_schema_version": "v3_shared_data.hk_0_2_panel_asset.v2",
        "panel_max_date": target, "panel_relative": panel_relative,
        "panel_sha256": panel_ref["sha256"], "through_date_code_count": 600,
        "panel_code_count": 600, "panel_rows": 600}
    panel_manifest_ref = artifact(panel_root / panel_manifest_relative,
        "HK_PANEL_MANIFEST", panel_manifest)
    panel_pointer_ref = pointer_snapshot(panel_root / "panel_latest.json",
        "HK_PANEL_LATEST_POINTER", {"manifest_relative": panel_manifest_relative},
        "panel_latest.snapshot.json")

    master_manifest_relative = f"runs/{target}/{master_run_id}/manifest.json"
    master_receipt_relative = f"runs/{target}/{master_run_id}/receipt.json"
    master_artifact_relative = f"runs/{target}/{master_run_id}/artifact.csv"
    master_artifact_ref = artifact(master_root / master_artifact_relative,
        "HK_SECURITY_MASTER_ARTIFACT", raw=b"code,name\nHK.00001,synthetic\n")
    master_manifest = {"schema_version": "v3_shared_data.hk_security_master_manifest.v1",
        "trade_date": target, "run_id": master_run_id, "row_count": 600,
        "artifact_relative": master_artifact_relative,
        "artifact_sha256": master_artifact_ref["sha256"]}
    master_manifest_ref = artifact(master_root / master_manifest_relative,
        "HK_SECURITY_MASTER_MANIFEST", master_manifest)
    master_receipt = {"schema_version": "v3_shared_data.hk_security_master_receipt.v1",
        "status": "READY", "trade_date": target, "run_id": master_run_id,
        "artifact_sha256": master_artifact_ref["sha256"],
        "manifest_sha256": master_manifest_ref["sha256"]}
    master_receipt_ref = artifact(master_root / master_receipt_relative,
        "HK_SECURITY_MASTER_RECEIPT", master_receipt)
    latest_path = master_root / "latest.json"
    if latest_path.is_file():
        latest_value = json.loads(latest_path.read_text(encoding="utf-8"))
    else:
        latest_value = {"schema_version": "v3_shared_data.hk_security_master_latest.v1",
            "entries": {}}
    entries = dict(latest_value.get("entries") or {})
    entries[target] = {"run_id": master_run_id,
        "manifest_relative": master_manifest_relative,
        "receipt_relative": master_receipt_relative}
    latest_value = {"schema_version": "v3_shared_data.hk_security_master_latest.v1",
        "entries": entries}
    master_pointer_ref = pointer_snapshot(latest_path,
        "HK_SECURITY_MASTER_LATEST_POINTER", latest_value,
        "security_master_latest.snapshot.json")

    summary = {"status": "READY", "target_date": target, "row_count": 600,
        "universe_count": 600, "coverage_rate": 1.0,
        "sha256": hashlib.sha256(b"universe").hexdigest(),
        "source_sha256": source_sha, "capture_run_id": capture_run_id,
        "capture_sha256": capture_sha, "membership_run_id": membership_run_id,
        "panel_sha256": panel_ref["sha256"],
        "panel_capture_binding_sha256": binding_sha,
        "security_master_run_id": master_run_id,
        "security_master_artifact_sha256": master_artifact_ref["sha256"]}
    stage_results = {
        "CAPTURE": {"capture_run_id": capture_run_id, "capture_sha256": capture_sha,
            "source_sha256": source_sha, "row_count": 600,
            "capture_manifest_path": capture_manifest_ref["path"],
            "capture_raw_sha256": raw_ref["sha256"]},
        "MEMBERSHIP_PUBLICATION": {"status": "READY", "trade_date": target,
            "row_count": 600, "capture_sha256": capture_sha,
            "authority_run_id": membership_run_id,
            "authority_capture_run_id": capture_run_id,
            "authority_capture_sha256": capture_sha,
            "source_sha256": universe_source_sha,
            "publication_relative": publication_relative,
            "written_files": written_files},
        "PANEL_PACK": {"row_count": 600, "coverage_rate": 1.0},
        "PANEL_AUTHORITY": {"panel_sha256": panel_ref["sha256"],
            "manifest_relative": panel_manifest_relative,
            "through_date_code_count": 600},
        "PANEL_CAPTURE_BINDING": {"capture_run_id": capture_run_id,
            "capture_sha256": capture_sha, "panel_sha256": panel_ref["sha256"],
            "panel_capture_binding_sha256": binding_sha, "code_count": 600},
        "SECURITY_MASTER_PUBLICATION": {"status": "READY", "run_id": master_run_id,
            "row_count": 600, "capture_run_id": capture_run_id,
            "capture_sha256": capture_sha, "panel_sha256": panel_ref["sha256"],
            "panel_capture_binding_sha256": binding_sha,
            "security_master_artifact_sha256": master_artifact_ref["sha256"],
            "security_master_manifest_sha256": master_manifest_ref["sha256"]},
    }
    base = f"hk_publication/{target}/{chain_id}"
    safe.ensure_directory(base)
    stage_refs = []
    for stage_name in gate.CHAIN_REQUIRED_STAGES:
        result = stage_results.get(stage_name)
        if stage_name == "FINAL_READBACK":
            result = {"artifact_count": len(refs),
                "lane_summary": summary, "publication_chain_status": "READY"}
        value = gate._seal({"schema_version": gate.CHAIN_SCHEMA,
            "target_date": target, "chain_id": chain_id,
            "stage": stage_name, "capture_run_id": capture_run_id,
            "status": "READY", "result": result,
            "started_at": "2026-10-08T09:00:00+00:00",
            "finished_at": "2026-10-08T09:00:01+00:00", **FLAGS})
        relative = f"{base}/{stage_name.lower()}.json"
        raw = gate._canonical(value) + b"\n"
        safe.write_bytes(relative, raw, require_absent=True)
        stage_refs.append({"stage": stage_name, "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})

    terminal_relative = f"{base}/terminal.json"
    terminal = gate._seal({"schema_version": gate.CHAIN_SCHEMA,
        "status": "READY", "target_date": target, "chain_id": chain_id,
        "capture_run_id": capture_run_id, "started_at": "2026-10-08T09:00:00+00:00",
        "finished_at": "2026-10-08T09:01:00+00:00", "stages": stage_refs,
        "artifact_refs": refs, "lane_summary": summary,
        "daily_supplement": {"status": "PARTIAL_WITH_PENDING"}, **FLAGS})
    terminal_raw = gate._canonical(terminal) + b"\n"
    safe.write_bytes(terminal_relative, terminal_raw, require_absent=True)
    pointer = gate._seal({"schema_version": gate.CHAIN_SCHEMA,
        "status": "READY", "target_date": target, "chain_id": chain_id,
        "terminal_relative": terminal_relative,
        "terminal_sha256": hashlib.sha256(terminal_raw).hexdigest(),
        "terminal_bytes": len(terminal_raw),
        "published_at": "2026-10-08T09:01:00+00:00", **FLAGS})
    safe.write_bytes(f"hk_publication/{target}/latest.json",
        gate._canonical(pointer) + b"\n", require_absent=True)
    return summary, pointer


def _rewrite_sealed_stage(tmp_path, pointer, stage_name, mutate):
    safe = __import__("infrastructure.owned_io", fromlist=["SafeRoot"]).SafeRoot(tmp_path)
    terminal_path = tmp_path / pointer["terminal_relative"]
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    reference = next(item for item in terminal["stages"] if item["stage"] == stage_name)
    stage_path = tmp_path / reference["path"]
    stage = json.loads(stage_path.read_text(encoding="utf-8"))
    mutate(stage)
    stage = gate._seal({key: value for key, value in stage.items() if key != "sha256"})
    stage_raw = gate._canonical(stage) + b"\n"
    safe.write_bytes(reference["path"], stage_raw, require_absent=False)
    reference["sha256"] = hashlib.sha256(stage_raw).hexdigest()
    reference["bytes"] = len(stage_raw)
    terminal = gate._seal({key: value for key, value in terminal.items() if key != "sha256"})
    terminal_raw = gate._canonical(terminal) + b"\n"
    safe.write_bytes(pointer["terminal_relative"], terminal_raw, require_absent=False)
    latest = gate._seal({**pointer, "terminal_sha256": hashlib.sha256(terminal_raw).hexdigest(),
        "terminal_bytes": len(terminal_raw)})
    safe.write_bytes(f"hk_publication/{pointer['target_date']}/latest.json",
        gate._canonical(latest) + b"\n", require_absent=False)
    return latest


def test_exact_sealed_chain_is_verified_and_can_back_hk_fast_path(tmp_path):
    actual = _load_actual_layer()
    summary, pointer = _publish_chain_fixture(tmp_path)
    verified = gate.read_verified_chain(actual.__dict__, tmp_path, "20261008")
    assert verified is not None
    assert verified["terminal"]["chain_id"] == pointer["chain_id"]
    receipt = {"target_date": "20261008", "status": "READY", "lane": "HK",
        "row_count": summary["row_count"], "coverage_rate": summary["coverage_rate"],
        "sha256": summary["sha256"], "publication_chain": {
            "chain_id": pointer["chain_id"],
            "terminal_relative": pointer["terminal_relative"],
            "terminal_sha256": pointer["terminal_sha256"], "status": "VERIFIED"},
        **FLAGS}
    assert actual._hk_lane_receipt_ready(tmp_path, "20261008", receipt) is True


def test_roleless_decoy_chain_cannot_claim_ready_from_one_capture_file(tmp_path):
    actual = _load_actual_layer()
    _summary, _pointer = _publish_roleless_decoy_fixture(tmp_path)
    with pytest.raises(ValueError, match="HK_PUBLICATION_CHAIN_ARTIFACT_ROLES_INVALID"):
        gate.read_verified_chain(actual.__dict__, tmp_path, "20261008")


def test_fully_sealed_chain_with_capture_stage_identity_mismatch_is_rejected(tmp_path):
    actual = _load_actual_layer()
    _summary, pointer = _publish_chain_fixture(tmp_path)
    _rewrite_sealed_stage(tmp_path, pointer, "CAPTURE",
        lambda stage: stage["result"].update(capture_sha256="0" * 64))
    with pytest.raises(ValueError, match="HK_PUBLICATION_CHAIN_CAPTURE_STAGE_MISMATCH"):
        gate.read_verified_chain(actual.__dict__, tmp_path, "20261008")


def test_existing_verified_chain_is_reused_without_entering_capture_or_publishers(tmp_path, monkeypatch):
    actual = _load_actual_layer()
    summary, pointer = _publish_chain_fixture(tmp_path)
    monkeypatch.setattr(gate, "_run_hk_capture_gate_body",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache hit must not run publishers")))
    args = SimpleNamespace(receipt_root=tmp_path,
        hk_asset_root=tmp_path / "assets" / "hk_0_2",
        hk_tdx_root=tmp_path / "hk-tdx")

    result = gate.run_hk_capture_gate(actual.__dict__, target_date="20261008",
        args=args, authority_paths={}, python_executable=Path(sys.executable))

    assert result["status"] == "READY" and result["cache_hit"] is True
    assert result["row_count"] == summary["row_count"]
    assert result["publication_chain"]["terminal_sha256"] == pointer["terminal_sha256"]


def test_chain_cache_rejects_changed_artifact_bytes(tmp_path):
    actual = _load_actual_layer()
    _summary, pointer = _publish_chain_fixture(tmp_path)
    ref = json.loads((tmp_path / pointer["terminal_relative"]).read_text())["artifact_refs"][0]
    Path(ref["path"]).write_bytes(b"x" * ref["bytes"])
    with pytest.raises(ValueError, match="HK_PUBLICATION_CHAIN_ARTIFACT_SHA_MISMATCH"):
        gate.read_verified_chain(actual.__dict__, tmp_path, "20261008")

    receipt = {"target_date": "20261008", "status": "READY", "lane": "HK",
        "row_count": 600, "coverage_rate": 1.0, "sha256": "b" * 64,
        "publication_chain": {"chain_id": pointer["chain_id"],
            "terminal_relative": pointer["terminal_relative"],
            "terminal_sha256": pointer["terminal_sha256"], "status": "VERIFIED"},
        **FLAGS}
    assert actual._hk_lane_receipt_ready(tmp_path, "20261008", receipt) is False


def test_next_day_pointer_promotion_keeps_prior_immutable_chain_readable(tmp_path):
    actual = _load_actual_layer()
    day_one = "20261008"
    day_two = "20261009"
    summary_one, pointer_one = _publish_chain_fixture(tmp_path, day_one)
    chain_path = tmp_path / pointer_one["terminal_relative"]
    terminal_before = chain_path.read_bytes()
    terminal = json.loads(terminal_before)
    snapshot_refs = [ref for ref in terminal["artifact_refs"] if ref.get("source_path")]
    snapshot_bytes_before = {ref["path"]: Path(ref["path"]).read_bytes() for ref in snapshot_refs}

    _summary_two, pointer_two = _publish_chain_fixture(tmp_path, day_two)
    panel_latest = json.loads((tmp_path / "shared-data/assets/hk_0_2/panel_latest.json").read_text())
    master_latest = json.loads((tmp_path / "shared-data/assets/hk_security_master/latest.json").read_text())
    assert panel_latest["manifest_relative"] == f"panels/{day_two}-panel/manifest.json"
    assert set(master_latest["entries"]) == {day_one, day_two}

    verified_one = gate.read_verified_chain(actual.__dict__, tmp_path, day_one)
    verified_two = gate.read_verified_chain(actual.__dict__, tmp_path, day_two)
    assert verified_one is not None and verified_two is not None
    assert verified_one["terminal"]["chain_id"] == pointer_one["chain_id"]
    assert verified_two["terminal"]["chain_id"] == pointer_two["chain_id"]
    assert chain_path.read_bytes() == terminal_before
    assert all(Path(path).read_bytes() == content for path, content in snapshot_bytes_before.items())

    receipt = {"target_date": day_one, "status": "READY", "lane": "HK",
        "row_count": summary_one["row_count"], "coverage_rate": summary_one["coverage_rate"],
        "sha256": summary_one["sha256"], "publication_chain": {
            "chain_id": pointer_one["chain_id"], "terminal_relative": pointer_one["terminal_relative"],
            "terminal_sha256": pointer_one["terminal_sha256"], "status": "VERIFIED"}, **FLAGS}
    assert actual._hk_lane_receipt_ready(tmp_path, day_one, receipt) is True


def test_actual_entry_hk_lane_reaches_history_guard_without_replacing_a_runner(tmp_path, capsys):
    actual = _load_actual_layer()
    receipts = tmp_path / "receipt-root"
    updater = tmp_path / "upstream" / "scripts" / "update_hk_0_2_panel.py"
    updater.parent.mkdir(parents=True)
    updater.write_text("original updater boundary placeholder", encoding="utf-8")
    result = actual.main([
        "--date", "20261007", "--lane", "HK", "--receipt-root", str(receipts),
        "--hk-tdx-root", str(tmp_path / "hk-tdx"),
        "--hk-updater-script", str(updater),
        "--hk-python-executable", sys.executable,
        "--hk-asset-root", str(tmp_path / "store" / "assets" / "hk_0_2"),
    ])
    assert result == 1
    output = json.loads(capsys.readouterr().out)
    assert output["lanes"]["HK"]["status"] == "FAILED"
    lane = json.loads((receipts / "hk-20261007.json").read_text())
    assert lane["failed_stage"] == "CAPTURE"
    assert lane["failure_reasons"] == ["HK_HISTORICAL_MEMBERSHIP_CAPTURE_UNAVAILABLE"]
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("reject_candidate_readback", [False, True])
def test_actual_entry_publishes_and_reuses_full_hk_chain_with_original_owners(
    tmp_path, monkeypatch, capsys, reject_candidate_readback
):
    import importlib
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import pandas as pd

    actual = _load_actual_layer()
    date = "20261008"
    monkeypatch.setattr(gate, "_today_shanghai", lambda: date)
    app_root = Path(__file__).resolve().parents[1]
    package_root = app_root / "upstreams" / "v3_shared_data"
    updater = package_root / "scripts" / "update_hk_0_2_panel.py"
    monkeypatch.syspath_prepend(str(package_root))
    hk02 = importlib.import_module("shared_data.hk_0_2")
    loader = importlib.import_module("infrastructure.isolated_package_loader")
    ensure = importlib.import_module("ops.ensure_hk_security_master")
    capture_module = importlib.import_module(
        "ops._macos_research_panel_daily_parts.hk_market_capture")

    flags = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    state_root = tmp_path / "shared-data"
    asset_root = state_root / "assets" / "hk_0_2"
    asset_root.mkdir(parents=True)
    tdx_root = tmp_path / "tdx"
    seed_panel = tmp_path / "seed-panel.parquet"
    codes = [f"HK.{number:05d}" for number in range(1, 601)]
    pd.DataFrame([{"trade_date_compact": "20261007", "code_norm": code,
        "close": 10.0} for code in codes]).to_parquet(seed_panel, index=False)
    seed_manifest = {"panel_sha256": hashlib.sha256(seed_panel.read_bytes()).hexdigest()}
    monkeypatch.setattr(hk02, "load_frozen_hk_0_2_assets",
        lambda _root: SimpleNamespace(panel_path=seed_panel, panel_manifest=seed_manifest))

    class FrozenShanghaiClock(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = datetime(2026, 10, 8, 17, 20, tzinfo=ZoneInfo("Asia/Shanghai"))
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(ensure, "datetime", FrozenShanghaiClock)
    monkeypatch.setattr(actual, "_today_shanghai", lambda: date)
    monkeypatch.setattr(capture_module, "_utc_now_iso",
        lambda: "2026-10-08T09:20:00+00:00")

    class FakeFutuContext:
        def __init__(self):
            self.closed = False

        def get_plate_stock(self, _plate):
            return 0, pd.DataFrame([{"code": code, "stock_name": f"Synthetic issuer {code[3:]}"}
                                    for code in codes])

        def get_market_snapshot(self, requested_codes):
            return 0, pd.DataFrame([{
                "code": code, "name": f"Synthetic issuer {code[3:]}",
                "update_time": "2026-10-08 17:20:00", "open_price": 10.0,
                "high_price": 11.0, "low_price": 9.0, "last_price": 10.0,
                "volume": 1000, "turnover": 10000.0,
                "outstanding_shares": 1000000, "circular_market_val": 10000000.0,
                "listing_date": "2010-01-01", "lot_size": 100,
                "stock_owner": "Synthetic owner", "stock_child_type": "Synthetic type",
                "sec_status": "NORMAL",
            } for code in requested_codes])

        def close(self):
            self.closed = True

    contexts = []
    futu = SimpleNamespace(OpenQuoteContext=lambda **_kwargs:
        contexts.append(FakeFutuContext()) or contexts[-1])
    monkeypatch.setitem(sys.modules, "futu", futu)

    def publish_panel_with_original_owner(updater_path, python, assets, tdx, target):
        result = hk02.update_hk_0_2_panel_from_vipdoc(
            assets, tdx_root=tdx, through_date=target)
        return {**result, "target_date": target,
            "argv": [str(python), str(updater_path), "--asset-root", str(assets),
                     "--tdx-root", str(tdx), "--through-date", target], **flags}

    monkeypatch.setattr(actual, "run_hk_0_2_authority", publish_panel_with_original_owner)

    def read_published_panel(root):
        root = Path(root).resolve()
        pointer = json.loads((root / "panel_latest.json").read_text(encoding="utf-8"))
        manifest_path = (root / pointer["manifest_relative"]).resolve()
        manifest_path.relative_to(root)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        panel_path = (root / manifest["panel_relative"]).resolve()
        panel_path.relative_to(root)
        return SimpleNamespace(panel_manifest=manifest, panel_path=panel_path)

    original_isolated_loader = loader.load_isolated_package_module

    def isolated_loader(root, *, package_directory, module_leaf, namespace_prefix):
        if package_directory == "shared_data" and module_leaf == "hk_0_2":
            return SimpleNamespace(load_frozen_hk_0_2_assets=read_published_panel)
        return original_isolated_loader(root, package_directory=package_directory,
            module_leaf=module_leaf, namespace_prefix=namespace_prefix)

    monkeypatch.setattr(loader, "load_isolated_package_module", isolated_loader)

    supplement_payload = {"status": "PARTIAL_WITH_PENDING", "target_date": date,
        "through_date": date, "run_id": "synthetic-supplement", "code_count": 600,
        "record_status_counts": {"PENDING": 600}, "volume_unit_status": "NOT_PROVEN",
        "price_basis": "UNKNOWN", **flags}

    class CompletedSupplement:
        returncode = 0
        stdout = json.dumps(supplement_payload) + "\n"

    monkeypatch.setattr(actual.subprocess, "run", lambda *_args, **_kwargs: CompletedSupplement())

    if reject_candidate_readback:
        original_read_verified_chain = gate.read_verified_chain

        def reject_candidate(*args, **kwargs):
            if kwargs.get("_pointer_override") is not None:
                raise ValueError("synthetic candidate readback rejection")
            return original_read_verified_chain(*args, **kwargs)

        monkeypatch.setattr(gate, "read_verified_chain", reject_candidate)

    receipt_root = tmp_path / "receipts"
    args = ["--date", date, "--lane", "HK", "--receipt-root", str(receipt_root),
        "--hk-tdx-root", str(tdx_root), "--hk-updater-script", str(updater),
        "--hk-python-executable", sys.executable, "--hk-asset-root", str(asset_root)]
    result_code = actual.main(args)
    capsys.readouterr()
    if reject_candidate_readback:
        assert result_code == 2
        attempt_path = receipt_root / "hk_publication" / date / "latest_attempt.json"
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        assert attempt["status"] == "CANNOT_CONFIRM"
        assert not (receipt_root / "hk_publication" / date / "latest.json").exists()
        unpromoted_terminal = json.loads(
            (receipt_root / attempt["terminal_relative"]).read_text(encoding="utf-8"))
        assert unpromoted_terminal["status"] == "READY"
        lane = json.loads((receipt_root / f"hk-{date}.json").read_text(encoding="utf-8"))
        assert lane["status"] == "CANNOT_CONFIRM"
        assert len(contexts) == 1 and contexts[0].closed is True
        return
    assert result_code == 0
    lane = json.loads((receipt_root / f"hk-{date}.json").read_text(encoding="utf-8"))
    assert lane["status"] == "READY"
    assert lane["publication_chain"]["status"] == "VERIFIED"
    assert lane["security_master"]["security_master_readback_status"] == "VERIFIED"
    assert lane["security_master"]["security_master_readback_row_count"] == 600
    assert lane["daily_supplement"]["status"] == "PARTIAL_WITH_PENDING"
    assert lane["daily_supplement"]["volume_unit_status"] == "NOT_PROVEN"
    assert len(contexts) == 1 and contexts[0].closed is True

    chain = gate.read_verified_chain(actual.__dict__, receipt_root, date)
    assert chain is not None
    assert tuple(row["stage"] for row in chain["terminal"]["stages"]) == gate.CHAIN_REQUIRED_STAGES
    assert chain["terminal"]["capture_run_id"] == lane["capture_run_id"]
    assert any(ref["role"] == "HK_SECURITY_MASTER_ARTIFACT"
        for ref in chain["terminal"]["artifact_refs"])
    master_root = state_root / "assets" / "hk_security_master"
    from upstreams.v3_shared_data.shared_data.hk_security_master import load_verified_hk_security_master
    master_rows, master_manifest = load_verified_hk_security_master(state_root, date)
    assert len(master_rows) == 600
    assert master_manifest["run_id"] == lane["security_master_run_id"]

    first_terminal_sha = lane["publication_chain"]["terminal_sha256"]
    assert actual.main(args) == 0
    capsys.readouterr()
    cached_lane = json.loads((receipt_root / f"hk-{date}.json").read_text(encoding="utf-8"))
    assert cached_lane["cache_hit"] is True
    assert cached_lane["publication_chain"]["terminal_sha256"] == first_terminal_sha
    assert len(contexts) == 1

    terminal = chain["terminal"]
    master_artifact = next(ref for ref in terminal["artifact_refs"]
        if ref["role"] == "HK_SECURITY_MASTER_ARTIFACT")
    Path(master_artifact["path"]).write_bytes(b"x" * master_artifact["bytes"])
    assert actual._hk_lane_receipt_ready(receipt_root, date, cached_lane) is False

