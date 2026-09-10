from pathlib import Path
import hashlib
import json
import os
import plistlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _identity_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    manifest_declared_sha: str | None = None,
    receipt_declared_sha: str | None = None,
    plist_release_id: str = "fixture-release",
    selected_module_status: str = "VERIFIED",
    manifest_locator: Path | None = None,
) -> dict[str, Path | str]:
    from apps.api.v35_api import runtime_graph_router as router_module

    release_root = tmp_path / "release-identity"
    app_root = release_root / "app"
    runtime_root = release_root / "runtime"
    app_root.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    manifest_path = release_root / "release-manifest.json"
    receipt_path = release_root / "activation-receipt.json"
    inventory_path = runtime_root / "runtime-inventory.json"
    dependency_path = runtime_root / "runtime-dependency-manifest.json"
    receipt_path.write_text('{"status":"ACCEPTED"}\n', encoding="utf-8")
    inventory_path.write_text('{"python":"3.14"}\n', encoding="utf-8")
    dependency_path.write_text('{"packages":[]}\n', encoding="utf-8")
    actual_receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    manifest = {
        "release_id": "fixture-release",
        "activation_receipt": "activation-receipt.json",
        "activation_receipt_sha256": receipt_declared_sha or actual_receipt_sha,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    actual_manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    module_path = app_root / "loaded-runtime-module.py"
    module_path.write_text("fixture = True\n", encoding="utf-8")
    module_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    plist_path = tmp_path / "com.lexi.v35.api-only.plist"
    values = {
        "V35_APP_ROOT": str(app_root),
        "V35_RELEASE_ID": "fixture-release",
        "V35_RELEASE_MANIFEST_SHA256": manifest_declared_sha or actual_manifest_sha,
        "V35_RUNTIME_ROOT": str(runtime_root),
        "V35_RUNTIME_INVENTORY_SHA256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        "V35_RUNTIME_DEPENDENCY_MANIFEST_SHA256": hashlib.sha256(dependency_path.read_bytes()).hexdigest(),
    }
    plist_values = dict(values)
    plist_values["V35_RELEASE_ID"] = plist_release_id
    plist_path.write_bytes(plistlib.dumps({"EnvironmentVariables": plist_values}))
    monkeypatch.setattr(router_module, "API_PLIST_PATH", plist_path)
    monkeypatch.setattr(router_module, "_module_app_root", lambda: app_root)
    module_record = {
        "module": "apps.api.v35_api.fixture",
        "__file__": str(module_path),
        "path": str(module_path),
        "sha256": module_sha if selected_module_status == "VERIFIED" else None,
        "status": selected_module_status,
    }
    monkeypatch.setattr(router_module, "_selected_imported_modules", lambda _roots: [module_record])
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    if manifest_locator is None:
        monkeypatch.delenv("V35_RELEASE_MANIFEST_PATH", raising=False)
    else:
        monkeypatch.setenv("V35_RELEASE_MANIFEST_PATH", str(manifest_locator))
    return {
        "app_root": app_root,
        "runtime_root": runtime_root,
        "manifest_path": manifest_path,
        "plist_path": plist_path,
        "actual_manifest_sha": actual_manifest_sha,
    }


def test_real_create_app_accepts_runtime_binding_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.v35_api import app as api_module

    class UnexpectedStageRunner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("shared Stage Center mode must not instantiate StageRunner")

    monkeypatch.setattr(api_module, "StageRunner", UnexpectedStageRunner)

    app = api_module.create_app(
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared",
        ledger_root=tmp_path / "dispatcher",
        stage_center_selection_root=tmp_path / "selection",
    )

    assert app.title == "V3.5"

    # FastAPI's mounted/include-router wrapper does not flatten nested paths
    # into ``app.routes`` in the runtime version used by the release.  Probe
    # the same router factory that create_app registers so this canary tests
    # the actual graph route contract rather than an implementation detail of
    # the wrapper object.
    graph_router = api_module.create_runtime_graph_router(tmp_path / "graph")
    graph_paths = {getattr(route, "path", "") for route in graph_router.routes}
    assert "/api/v3/runtime-graph/snapshot" in graph_paths


def test_runtime_status_adds_same_process_identity_when_snapshot_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.v35_api import runtime_graph_router as router_module

    for key in router_module._IDENTITY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    app = FastAPI()
    app.include_router(router_module.create_runtime_graph_router(tmp_path / "data"))

    response = TestClient(app).get("/api/v3/runtime-graph/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "EVIDENCE_GAP"
    identity = payload["runtime_identity"]
    assert identity["status"] == "CANNOT_CONFIRM"
    assert identity["pid"] == os.getpid()
    assert identity["sys.executable"]
    assert identity["sys.path"]
    assert identity["selected_imported_module___file__"]
    assert identity["selected_modules_status"] == "VERIFIED"
    assert all(item["status"] == "VERIFIED" for item in identity["selected_imported_modules"])
    assert identity["release_manifest_status"] == "CANNOT_CONFIRM"
    assert identity["runtime_inventory_status"] == "MISSING"
    assert identity["runtime_dependency_manifest_status"] == "MISSING"
    assert response.headers["X-V35-Runtime-Identity-SHA256"] == identity["identity_payload_sha256"]
    assert "V35_ADMIN_KEY" not in json.dumps(identity)


def test_runtime_identity_verifies_declared_release_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.v35_api import runtime_graph_router as router_module

    release_root = tmp_path / "release-identity"
    app_root = release_root / "app"
    runtime_root = release_root / "runtime"
    app_root.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    manifest_path = release_root / "release-manifest.json"
    receipt_path = release_root / "activation-receipt.json"
    inventory_path = runtime_root / "runtime-inventory.json"
    dependency_path = runtime_root / "runtime-dependency-manifest.json"
    receipt_path.write_text('{"status":"ACCEPTED"}\n', encoding="utf-8")
    inventory_path.write_text('{"python":"3.14"}\n', encoding="utf-8")
    dependency_path.write_text('{"packages":[]}\n', encoding="utf-8")
    manifest = {
        "release_id": "fixture-release",
        "activation_receipt": "activation-receipt.json",
        "activation_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    module_path = app_root / "loaded-runtime-module.py"
    module_path.write_text("fixture = True\n", encoding="utf-8")
    module_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    plist_path = tmp_path / "com.lexi.v35.api-only.plist"
    values = {
        "V35_APP_ROOT": str(app_root),
        "V35_RELEASE_ID": "fixture-release",
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
        "V35_RUNTIME_ROOT": str(runtime_root),
        "V35_RUNTIME_INVENTORY_SHA256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        "V35_RUNTIME_DEPENDENCY_MANIFEST_SHA256": hashlib.sha256(dependency_path.read_bytes()).hexdigest(),
    }
    plist_path.write_bytes(plistlib.dumps({"EnvironmentVariables": values}))
    monkeypatch.setattr(router_module, "API_PLIST_PATH", plist_path)
    monkeypatch.setattr(router_module, "_module_app_root", lambda: app_root)
    monkeypatch.setattr(
        router_module,
        "_selected_imported_modules",
        lambda _roots: [
            {
                "module": "apps.api.v35_api.fixture",
                "__file__": str(module_path),
                "path": str(module_path),
                "sha256": module_sha,
                "status": "VERIFIED",
            }
        ],
    )
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    app = FastAPI()
    app.include_router(router_module.create_runtime_graph_router(tmp_path / "data"))
    identity = TestClient(app).get("/api/v3/runtime-graph/status").json()["runtime_identity"]

    assert identity["status"] == "VERIFIED"
    assert identity["release_id"] == "fixture-release"
    assert identity["release_manifest_status"] == "VERIFIED"
    assert identity["release_manifest_sha256"] == manifest_sha
    assert identity["release_manifest_sha_status"] == "VERIFIED"
    assert identity["receipt_status"] == "VERIFIED"
    assert identity["runtime_inventory_status"] == "VERIFIED"
    assert identity["runtime_dependency_manifest_status"] == "VERIFIED"
    assert identity["plist_binding_status"] == "VERIFIED"
    assert identity["selected_modules_status"] == "VERIFIED"
    assert all(item["status"] == "MATCH" for item in identity["plist_bindings"].values())


def test_runtime_identity_manifest_sha_drift_blocks_verified_aggregate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _identity_fixture(tmp_path, monkeypatch, manifest_declared_sha="0" * 64)
    from apps.api.v35_api import runtime_graph_router as router_module

    app = FastAPI()
    app.include_router(router_module.create_runtime_graph_router(tmp_path / "data"))
    identity = TestClient(app).get("/api/v3/runtime-graph/status").json()["runtime_identity"]

    assert identity["release_manifest_sha_status"] == "DRIFT"
    assert identity["release_manifest_status"] == "VERIFIED"
    assert identity["status"] == "DRIFT"


def test_runtime_identity_required_receipt_evidence_drift_blocks_aggregate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _identity_fixture(tmp_path, monkeypatch, receipt_declared_sha="0" * 64)
    from apps.api.v35_api import runtime_graph_router as router_module

    app = FastAPI()
    app.include_router(router_module.create_runtime_graph_router(tmp_path / "data"))
    identity = TestClient(app).get("/api/v3/runtime-graph/status").json()["runtime_identity"]

    assert identity["receipt_status"] == "DRIFT"
    assert identity["status"] == "DRIFT"


def test_runtime_identity_plist_binding_drift_blocks_aggregate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _identity_fixture(tmp_path, monkeypatch, plist_release_id="different-release")
    from apps.api.v35_api import runtime_graph_router as router_module

    app = FastAPI()
    app.include_router(router_module.create_runtime_graph_router(tmp_path / "data"))
    identity = TestClient(app).get("/api/v3/runtime-graph/status").json()["runtime_identity"]

    assert identity["plist_bindings"]["V35_RELEASE_ID"]["status"] == "DRIFT"
    assert identity["plist_binding_status"] == "DRIFT"
    assert identity["status"] == "DRIFT"


def test_runtime_identity_missing_selected_module_evidence_cannot_verify_aggregate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _identity_fixture(tmp_path, monkeypatch, selected_module_status="CANNOT_CONFIRM")
    from apps.api.v35_api import runtime_graph_router as router_module

    app = FastAPI()
    app.include_router(router_module.create_runtime_graph_router(tmp_path / "data"))
    identity = TestClient(app).get("/api/v3/runtime-graph/status").json()["runtime_identity"]

    assert identity["selected_modules_status"] == "CANNOT_CONFIRM"
    assert identity["status"] == "CANNOT_CONFIRM"


def test_runtime_identity_nonexistent_declared_manifest_is_not_verified_locator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_manifest = tmp_path / "release-identity" / "missing-release-manifest.json"
    _identity_fixture(tmp_path, monkeypatch, manifest_locator=missing_manifest)
    from apps.api.v35_api import runtime_graph_router as router_module

    app = FastAPI()
    app.include_router(router_module.create_runtime_graph_router(tmp_path / "data"))
    identity = TestClient(app).get("/api/v3/runtime-graph/status").json()["runtime_identity"]

    assert identity["release_manifest_locator_status"] == "DECLARED_MISSING"
    assert identity["release_manifest_status"] == "CANNOT_CONFIRM"
    assert identity["status"] == "CANNOT_CONFIRM"


def test_runtime_identity_marks_release_drift_without_rewriting_graph_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.v35_api import runtime_graph_router as router_module

    release_root = tmp_path / "release-drift"
    app_root = release_root / "app"
    app_root.mkdir(parents=True)
    (release_root / "release-manifest.json").write_text(
        json.dumps({"release_id": "manifest-release"}), encoding="utf-8"
    )
    plist_path = tmp_path / "drift.plist"
    plist_path.write_bytes(plistlib.dumps({"EnvironmentVariables": {"V35_RELEASE_ID": "declared-release"}}))
    monkeypatch.setattr(router_module, "API_PLIST_PATH", plist_path)
    monkeypatch.setattr(router_module, "_module_app_root", lambda: app_root)
    monkeypatch.setenv("V35_APP_ROOT", str(app_root))
    monkeypatch.setenv("V35_RELEASE_ID", "declared-release")

    app = FastAPI()
    app.include_router(router_module.create_runtime_graph_router(tmp_path / "data"))
    payload = TestClient(app).get("/api/v3/runtime-graph/status").json()

    assert payload["status"] == "EVIDENCE_GAP"
    identity = payload["runtime_identity"]
    assert identity["status"] == "DRIFT"
    assert identity["release_id_status"] == "DRIFT"
    assert identity["release_manifest_status"] == "VERIFIED"
