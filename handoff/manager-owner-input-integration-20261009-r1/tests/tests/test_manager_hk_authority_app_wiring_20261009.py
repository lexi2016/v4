"""Offline synthetic contract audit; no market result or actual owner attestation.

Run against a fixed source root via V4_TEST_APP_ROOT. Every written artifact is
invented pytest data under tmp_path. No production source or owner state changes.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket

import pytest


APP_ROOT = Path(os.environ.get("V4_TEST_APP_ROOT", Path(__file__).resolve().parents[1])).resolve()
TARGET = "20261009"
DAY = "20261008"
CUTOFF = "2026-10-09T08:00:00+08:00"
CODES = ["HK.90001", "HK.90002"]


def load_source(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


owner = load_source("stage_center/hk_universe_preflight.py", "_hk_offline_pure_owner")
master_fixtures = load_source("tests/test_manager_three_channel_hk_reader.py", "_hk_offline_master_fixtures")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def files(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha(path.read_bytes())
            for path in root.rglob("*") if path.is_file()}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for key in list(os.environ):
        if key.startswith("V4_MANAGER_"):
            monkeypatch.delenv(key)

    def forbidden(*args, **kwargs):
        raise AssertionError("OFFLINE_SYNTHETIC_AUDIT_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def publish_synthetic_v2(root: Path, *, target: str = TARGET,
                         available_at: str = "2026-10-09T07:02:00+08:00") -> dict:
    """Serialize invented frames through the existing pure V2 contract owner."""
    iso = datetime.strptime(target, "%Y%m%d").strftime("%Y-%m-%d")
    acquired = f"{iso}T07:01:00+08:00"
    forward = {key: "1" * 64 for key in (
        "forward_receipt_sha256", "candidate_manifest_sha256",
        "candidate_build_receipt_sha256", "api_writer_receipt_sha256",
        "api_reviewer_receipt_sha256", "api_source_mapping_sha256")}
    forward["source_head"] = "1" * 40
    producer = {
        "workload_id": "v35_dispatcher.research_panel_daily_hk",
        "code_ref": "ops/_macos_research_panel_daily_parts/hk_market_capture.py",
        "code_sha256": "2" * 64,
        "forward_source_set": forward,
        "forward_source_set_sha256": owner._sha256(forward),
    }
    responses = {}
    for plate in owner.HKCONNECT_PLATE_CODES:
        material = dict(requested_plate=plate,
                        serialization_version="futu.dataframe.records.canonical-json.v1",
                        columns=["code"], rows=[dict(code=code) for code in CODES])
        responses[plate] = dict(material, return_code=0, row_count=len(CODES),
                                requested_at=f"{iso}T07:00:00+08:00", completed_at=acquired,
                                response_sha256=owner._sha256(material))
    plate_codes = {plate: CODES for plate in owner.HKCONNECT_PLATE_CODES}
    response_shas = {plate: value["response_sha256"] for plate, value in responses.items()}
    source = dict(target_date=target, plate_codes=plate_codes, plate_response_sha256=response_shas,
                  capture_run_id="synthetic-offline-hk-contract-run", acquired_at=acquired)
    capture = dict(
        schema_version=owner.HK_CONNECT_CAPTURE_SCHEMA_V2, status="READY", target_date=target,
        capture_run_id=source["capture_run_id"], acquired_at=acquired, producer_owner=producer,
        plate_responses=responses, plate_codes=plate_codes,
        plate_response_counts={plate: len(CODES) for plate in responses},
        plate_response_sha256=response_shas, codes=CODES, code_count=len(CODES),
        overlap_count=len(CODES), membership_source_payload=source,
        membership_source_sha256=owner._sha256(source), **owner.SAFETY_FLAGS)
    capture["capture_sha256"] = owner._sha256(capture)
    contract = dict(code_ref="stage_center/hk_universe_preflight.py",
                    code_sha256=sha((APP_ROOT / "stage_center/hk_universe_preflight.py").read_bytes()),
                    role="PURE_CAPTURED_HK_CONNECT_CONTRACT_V2")
    built = owner.build_captured_hk_connect_authority_v2(
        capture, trade_date=target, producer_owner=producer, contract_owner=contract)
    paths = built["paths"]
    publication = dict(
        schema_version=owner.HK_CONNECT_PUBLICATION_SCHEMA_V2,
        status="READY", target_date=target, effective_date=target, trade_date=target,
        source_date=target, market="HK_CONNECT", scope="FULL_MARKET", run_id=built["run_id"],
        publication_relative=built["publication_relative"], acquired_at=acquired,
        available_at=available_at, capture_run_id=capture["capture_run_id"],
        capture_sha256=capture["capture_sha256"], artifact_relative=paths["artifact_relative"],
        artifact_sha256=built["artifact_sha256"], manifest_relative=paths["manifest_relative"],
        receipt_relative=paths["receipt_relative"], current_relative=paths["current_relative"],
        current_sha256=built["current_sha256"], workload_id=producer["workload_id"],
        producer_owner=producer, contract_owner=contract, forward_source_set=forward,
        forward_source_set_sha256=producer["forward_source_set_sha256"], **owner.SAFETY_FLAGS)
    publication["publication_sha256"] = owner._sha256(publication)
    payloads = {paths[f"{kind}_relative"]: built[f"{kind}_bytes"]
                for kind in ("artifact", "manifest", "receipt", "current")}
    payloads[built["capture_relative"]] = built["capture_bytes"]
    payloads[built["publication_relative"]] = owner._canonical_json_line(publication)
    for relative, raw in payloads.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return built


def bind(monkeypatch, root: Path):
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(root))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_ROOT", str(APP_ROOT))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_SHA256",
                       sha((APP_ROOT / "stage_center/hk_universe_preflight.py").read_bytes()))


def context():
    from v4.manager_research.workspace_plan import plan_context
    return plan_context(TARGET, now=datetime.fromisoformat(CUTOFF))


def test_native_v2_bytes_reach_membership_and_daily_channel(tmp_path, monkeypatch):
    from v4.manager_research.connect_selection import read_scope, filter_cards, selection_diagnostics
    from v4.manager_research.workspace_daily_channels import build_daily_channels
    root = tmp_path / "authority"
    publish_synthetic_v2(root)
    bind(monkeypatch, root)
    before = files(root)
    scope = read_scope(context())
    assert scope["status"] == "OWNER_VERIFIED", scope["gaps"]
    assert scope["codes"] == CODES
    assert scope["source"]["source_date"] == TARGET
    assert scope["source"]["contract_owner"]["code_sha256"] == os.environ["V4_MANAGER_UNIVERSE_OWNER_SHA256"]
    rows, rejected = filter_cards([
        dict(symbol=CODES[0], name="SYNTHETIC ONLY", why_watch=["Invented fixture focus"], evidence=[])],
        scope, target_date=TARGET)
    assert rejected == []
    value = dict(target_trade_date=TARGET, stocks=rows, focus_symbols=[CODES[0]], plan_context=context(),
                 date_bindings=dict(plan_date=TARGET, selection_date=TARGET, announcement_date=DAY),
                 owner_chain=dict(focus_inputs=dict(status="READY", gaps=[])))
    value["selection_diagnostics"] = selection_diagnostics(value, {}, {"gaps": []}, scope, [])
    channel = build_daily_channels(value)["channels"][1]
    assert channel["status"] == "READY"
    assert channel["candidate_count"] == 1
    assert channel["rows"][0]["symbol"] == CODES[0]
    assert channel["natural_run_verified"] is False
    assert all(channel[key] is expected for key, expected in owner.SAFETY_FLAGS.items())
    assert files(root) == before


@pytest.mark.parametrize("variant,reason", [
    ("unbound", "HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND"),
    ("wrong_date", "HK_UNIVERSE_V2_ARTIFACT_MISSING"),
    ("missing_owner_sha", "OWNER_BINDING_REQUIRED"),
    ("owner_sha_mismatch", "HK_UNIVERSE_OWNER_SHA_MISMATCH"),
    ("missing_publication_sha", "HK_UNIVERSE_V2_PUBLICATION_SHA_INVALID"),
    ("altered_manifest", "HK_UNIVERSE_V2_CHAIN_IDENTITY_MISMATCH"),
    ("after_cutoff", "HK_CONNECT_TARGET_AUTHORITY_AFTER_CUTOFF_OR_WRONG_DATE"),
])
def test_native_v2_rejects_missing_wrong_or_late_inputs(tmp_path, monkeypatch, variant, reason):
    from v4.manager_research.connect_selection import read_scope, filter_cards
    root = tmp_path / "authority"
    built = publish_synthetic_v2(
        root, target=DAY if variant == "wrong_date" else TARGET,
        available_at=("2026-10-08T07:02:00+08:00" if variant == "wrong_date" else
                      "2026-10-09T08:01:00+08:00" if variant == "after_cutoff" else
                      "2026-10-09T07:02:00+08:00"))
    bind(monkeypatch, root)
    if variant == "unbound":
        monkeypatch.delenv("V4_MANAGER_UNIVERSE_ROOT")
    elif variant == "missing_owner_sha":
        monkeypatch.delenv("V4_MANAGER_UNIVERSE_OWNER_SHA256")
    elif variant == "owner_sha_mismatch":
        monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_SHA256", "0" * 64)
    elif variant == "missing_publication_sha":
        path = root / built["publication_relative"]
        value = json.loads(path.read_bytes())
        value.pop("publication_sha256")
        path.write_bytes(owner._canonical_json_line(value))
    elif variant == "altered_manifest":
        path = root / built["paths"]["manifest_relative"]
        value = json.loads(path.read_bytes())
        value["code_count"] += 1
        path.write_bytes(owner._canonical_json_line(value))
    before = files(root)
    scope = read_scope(context())
    assert scope["status"] == "CANNOT_CONFIRM", scope
    assert scope["codes"] == []
    assert any(reason in gap for gap in scope["gaps"]), scope["gaps"]
    rows, rejected = filter_cards([dict(symbol=CODES[0])], scope, target_date=TARGET)
    assert rows == [] and len(rejected) == 1
    assert files(root) == before


def app_for(tmp_path, *, shared: Path):
    from apps.api.v35_api.app import create_app
    return create_app(
        data_root=tmp_path / "data", shared_data_root=shared,
        ledger_root=tmp_path / "ledger", stage_center_selection_root=tmp_path / "stage",
        manager_research_state_root=tmp_path / "manager", current_date=TARGET,
        manager_research_source_provider=object(), research_data_root=tmp_path / "research",
        research_ledger_root=tmp_path / "research_ledger", morning_news_data_root=tmp_path / "news",
        preselection_source_root=tmp_path / "pool")


@pytest.mark.parametrize("mode", ["shared", "master_env", "screen_env"])
def test_create_app_existing_root_precedence(tmp_path, monkeypatch, mode):
    shared = tmp_path / "shared"
    master = tmp_path / "master"
    screen = tmp_path / "screen"
    if mode in {"master_env", "screen_env"}:
        monkeypatch.setenv("V4_MANAGER_SECURITY_MASTER_ROOT", str(master))
    if mode == "screen_env":
        monkeypatch.setenv("V4_MANAGER_SCREEN_AUTHORITY_ROOT", str(screen))
    app = app_for(tmp_path, shared=shared)
    service = app.state.manager_research_service
    assert service._workspace_security_master_root == (shared if mode == "shared" else master)
    assert service._workspace_screen_authority_root == (
        screen if mode == "screen_env" else shared if mode == "shared" else master)


def test_create_app_workspace_reads_real_synthetic_v2_master_panel_chain(tmp_path, monkeypatch):
    root = tmp_path / "authority"
    publish_synthetic_v2(root)
    master_fixtures._panel(root)
    published = master_fixtures._publish_master(root)
    master_fixtures._publish_master(root, TARGET, name="SYNTHETIC LATER MASTER")
    bind(monkeypatch, root)
    app = app_for(tmp_path, shared=root)
    service = app.state.manager_research_service
    before = files(root)
    value = service.get_workspace(TARGET, now=datetime.fromisoformat(CUTOFF),
                                  selection_date=TARGET, announcement_date=DAY)
    scope = value["selection_diagnostics"]["membership"]
    assert scope["status"] == "OWNER_VERIFIED", scope["gaps"]
    assert scope["source"]["source_date"] == TARGET
    screen = value["market_screen"]
    assert screen["status"] == "READY_WITH_GAPS", screen["gaps"]
    assert screen["verified_session"] == DAY
    assert screen["authority"]["security_master"]["run_id"] == published["run_id"]
    assert screen["coverage"]["history_pending_count"] == 1
    assert screen["pending"][0]["volume_unit_status"] == "NOT_PROVEN"
    channels = {channel["channel"]: channel for channel in value["daily_channels"]["channels"]}
    assert channels["HK_CONNECT"]["authority"]["status"] == "OWNER_VERIFIED"
    assert channels["HK_CONNECT"]["status"] == "PARTIAL"  # Other original focus inputs are absent.
    assert channels["OVERSOLD"]["status"] == "PARTIAL"
    assert channels["OVERSOLD"]["pending_count"] == 1
    assert channels["OVERSOLD"]["candidate_count"] is None
    assert all(not channel["natural_run_verified"] for channel in channels.values())
    assert all(value[key] is expected for key, expected in owner.SAFETY_FLAGS.items())
    assert files(root) == before
