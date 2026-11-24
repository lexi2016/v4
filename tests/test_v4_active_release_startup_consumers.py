"""Run exact API and Stage overlay readers with temporary release bytes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import sys
from types import SimpleNamespace

import pytest

from infrastructure.owned_io import OwnedIOError


OVERLAY = Path(__file__).resolve().parents[1] / "docs/review-pilot/v4-r2-b6-release"


def read_module(relative):
    path = OVERLAY / relative
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


@pytest.fixture
def api_release(tmp_path, monkeypatch):
    api = read_module("api-overlay/apps/api/v4_api/runtime_graph_router.py")
    sop = read_module("api-overlay/infrastructure/operations_sop_reader.py")
    release = tmp_path.resolve() / "api-release"
    app = release / "app"
    monkeypatch.setattr(api, "__file__", str(app / "apps/api/v4_api/runtime_graph_router.py"))
    monkeypatch.setattr(sop, "__file__", str(app / "infrastructure/operations_sop_reader.py"))
    monkeypatch.setenv("V4_APP_ROOT", str(app))
    monkeypatch.setenv("V4_RELEASE_ID", release.name)
    files = {"apps/web/dist/index.html": b'<script type="module" src="/assets/main-a.js"></script>',
             "apps/web/dist/assets/main-a.js": b"hello",
             "docs/SOP.md": "# 规程".encode()}
    inventory = []
    for path, raw in files.items():
        write(app / path, raw)
        inventory.append({"path": path, "sha256": digest(raw), "size": len(raw), "kind": "file"})
    raw = json.dumps({"schema_version": "v4.release_candidate.v1", "release_id": release.name,
                      "app_root": str(app), "candidate": {"root": str(release),
                          "app_root": str(app), "release_id": release.name},
                      "RESEARCH_ONLY": True, "production_allowed": False,
                      "buy_gate_updated": False, "orders_sent": False,
                      "application_inventory": {"entries": inventory, "entry_count": len(inventory),
                          "aggregate_sha256": digest(json.dumps(inventory, ensure_ascii=False,
                              sort_keys=True, separators=(",", ":")).encode())},
                      "app_files": inventory}).encode()
    monkeypatch.setenv("V4_RELEASE_MANIFEST_SHA256", digest(raw))
    return api, sop, release, raw


@pytest.mark.parametrize("filename", ["startup-manifest.json", "release-manifest.json"])
def test_api_readers_use_only_exact_startup_pin(api_release, monkeypatch, filename):
    api, sop, release, raw = api_release
    startup = release / filename
    write(startup, raw)
    if filename == "startup-manifest.json":
        write(release / "release-manifest.json", b'{"deployment_status":"LIVE"}')
    monkeypatch.setenv("V4_RELEASE_MANIFEST_PATH", str(startup))
    graph = api._frontend_build_identity()
    assert (graph["status"], graph["api_manifest_sha256"]) == ("VERIFIED", digest(raw))
    assert sop.read_sop()["content"] == "# 规程"
    if filename == "release-manifest.json":
        monkeypatch.delenv("V4_RELEASE_MANIFEST_PATH")
        assert api._frontend_build_identity()["status"] == "VERIFIED"


def test_api_readers_reject_another_root_and_wrong_sha(api_release, monkeypatch):
    api, sop, release, raw = api_release
    foreign = release.parent / "foreign" / "startup-manifest.json"
    write(foreign, raw)
    monkeypatch.setenv("V4_RELEASE_MANIFEST_PATH", str(foreign))
    assert api._frontend_build_identity()["reason"] == "API_MANIFEST_FIXED_PATH_MISMATCH"
    with pytest.raises(ValueError, match="SOP_RELEASE_FIXED_PATH_MISMATCH"):
        sop.read_sop()
    startup = release / "startup-manifest.json"
    write(startup, raw + b" ")
    monkeypatch.setenv("V4_RELEASE_MANIFEST_PATH", str(startup))
    assert api._frontend_build_identity()["reason"] == "API_MANIFEST_SHA_UNBOUND"
    with pytest.raises(ValueError, match="SOP_RELEASE_MANIFEST_SHA_MISMATCH"):
        sop.read_sop()
    startup.unlink()
    startup.symlink_to(foreign)
    assert api._frontend_build_identity()["status"] == "CANNOT_CONFIRM"
    with pytest.raises((OSError, OwnedIOError)):
        sop.read_sop()


@pytest.mark.parametrize("filename", ["startup-manifest.json", "release-manifest.json"])
def test_close_hook_passes_only_the_exact_main_pin(tmp_path, monkeypatch, filename):
    def forbid_dispatch(*args, **kwargs):
        pytest.fail("the caller-side pin check must not run a producer")

    # The exact role overlay also contains the receiver-side dispatch entry
    # point. Its pre-existing runtime-only dependencies are outside this test.
    for module, symbol in (
        ("infrastructure.scheduling.catalog", "load_workload_catalog"),
        ("infrastructure.scheduling.dispatcher", "dispatch_due"),
        ("infrastructure.scheduling.execution_ledger", "ExecutionLedger"),
        ("infrastructure.scheduling.executor_registry", "FixedExecutorRegistry"),
        ("stage_center.consumer", "StageSelectionConsumer"),
    ):
        monkeypatch.setitem(sys.modules, module, SimpleNamespace(**{symbol: forbid_dispatch}))
    hook = read_module("stage-main-overlay/ops/consume_close_stage_completion.py")
    home = tmp_path.resolve()
    release = home / "main-release"
    app = release / "app"
    app.mkdir(parents=True)
    manifest = release / filename
    raw = json.dumps({"release_id": release.name, "app_root": str(app)}).encode()
    write(manifest, raw)
    if filename == "startup-manifest.json":
        write(release / "release-manifest.json", b'{"deployment_status":"LIVE"}')
    pin = digest(raw)
    binding = {"app_root": str(app), "release_id": release.name, "manifest_sha256": pin}
    if filename == "startup-manifest.json":
        binding["manifest_path"] = str(manifest)
    env = {"V4_APP_ROOT": str(app), "V4_RELEASE_ID": release.name,
           "V4_RELEASE_MANIFEST_PATH": str(manifest), "V4_RELEASE_MANIFEST_SHA256": pin}
    plist = home / "Library/LaunchAgents/com.lexi.v4.scheduler.plist"
    write(plist, plistlib.dumps({"EnvironmentVariables": env}))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    calls = []

    def capture(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(hook.subprocess, "run", capture)
    config = {"close_review_completion_enabled": True, "research_owner_binding": binding,
              "selection_root": "/test/selection", "receipt_root": "/test/receipt",
              "v4_research_data_root": "/test/research", "research_scheduler_ledger_root": "/test/ledger"}

    def notify():
        return hook.notify(config=config, trade_date="20261124", stage_id="STAGE_1445_1500",
                           receipt={"dispatch_mode": "NATURAL"})

    assert notify()["status"] == "DELIVERED"
    assert calls[0][1]["env"]["V4_RELEASE_MANIFEST_PATH"] == str(manifest)
    assert calls[0][1]["env"]["V4_RELEASE_MANIFEST_SHA256"] == pin
    env["V4_RELEASE_MANIFEST_PATH"] = str(release / "some-other-manifest.json")
    write(plist, plistlib.dumps({"EnvironmentVariables": env}))
    with pytest.raises(ValueError, match="COMPLETION_MAIN_LOADED_BINDING_NOT_CURRENT"):
        notify()
    assert len(calls) == 1
