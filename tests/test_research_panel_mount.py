"""Isolated fixture tests: no real panel data, market connection, or service."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def module():
    path = Path(__file__).parents[1] / "apps/api/v35_api/research_panel_mount.py"
    assert path.exists(), "read-only research panel mount has not been implemented"
    spec = importlib.util.spec_from_file_location("candidate_research_panel_mount", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixture_site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "daily.html").write_text("<!doctype html><p>ISOLATED TEST FIXTURE</p>")
    (root / "daily.js").write_text("'use strict';")
    (root / "archive").mkdir()
    (root / "archive" / "view.json").write_text('{"fixture":true}')
    (root / "private.json").write_text('{"must_not_be_served":true}')
    (root / ".env").write_text("TEST_ONLY_SECRET=hidden")
    export = tmp_path / "assets.json"
    files = [{"path": name, "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}
             for name in ("daily.html", "daily.js", "archive/view.json")]
    export.write_text(json.dumps({"schema_version": "research_panel.assets.v1", "files": files}))
    return root, export


def client_for(root, export):
    app = FastAPI()
    app.include_router(module().create_research_panel_router(root, export))
    return TestClient(app)


def test_serves_only_allowlisted_bytes_without_touching_files(tmp_path):
    root, export = fixture_site(tmp_path)
    before = {str(p.relative_to(tmp_path)): (p.read_bytes(), p.stat().st_mtime_ns)
              for p in tmp_path.rglob("*") if p.is_file()}
    client = client_for(root, export)
    response = client.get("/research-panel/daily.html")
    assert response.status_code == 200
    assert response.content == (root / "daily.html").read_bytes()
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "text/html" in response.headers["content-type"]
    assert client.get("/research-panel/archive/view.json").json() == {"fixture": True}
    for path in ("private.json", ".env", "assets.json", "archive/"):
        assert client.get("/research-panel/" + path).status_code == 404
    after = {str(p.relative_to(tmp_path)): (p.read_bytes(), p.stat().st_mtime_ns)
             for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_rejects_path_traversal_and_request_supplied_root(tmp_path):
    root, export = fixture_site(tmp_path)
    secret = tmp_path / "secret.json"
    secret.write_text('{"outside":true}')
    client = client_for(root, export)
    for path in ("%2e%2e/secret.json", "archive/%2e%2e/private.json", "%5c..%5csecret.json"):
        response = client.get("/research-panel/" + path)
        assert response.status_code == 404
        assert "outside" not in response.text
    response = client.get("/research-panel/private.json", params={"root": str(tmp_path)})
    assert response.status_code == 404


def test_rejects_final_and_intermediate_symlinks_even_when_hash_matches(tmp_path):
    root, export = fixture_site(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "view.json").write_bytes((root / "archive/view.json").read_bytes())
    client = client_for(root, export)
    (root / "archive/view.json").unlink()
    (root / "archive/view.json").symlink_to(outside / "view.json")
    assert client.get("/research-panel/archive/view.json").status_code == 404
    (root / "archive/view.json").unlink()
    (root / "archive").rmdir()
    (root / "archive").symlink_to(outside, target_is_directory=True)
    assert client.get("/research-panel/archive/view.json").status_code == 404


def test_changed_and_missing_assets_have_explicit_failures(tmp_path):
    root, export = fixture_site(tmp_path)
    client = client_for(root, export)
    (root / "daily.js").write_text("changed after reviewed export")
    response = client.get("/research-panel/daily.js")
    assert response.status_code == 409
    assert response.json()["detail"] == "RESEARCH_PANEL_ASSET_SHA_MISMATCH"
    (root / "daily.js").unlink()
    response = client.get("/research-panel/daily.js")
    assert response.status_code == 404
    assert str(root) not in response.text


def test_head_and_get_only_and_root_redirect_keeps_query(tmp_path):
    root, export = fixture_site(tmp_path)
    client = client_for(root, export)
    get = client.get("/research-panel/daily.html")
    head = client.head("/research-panel/daily.html")
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == get.headers["content-length"]
    assert client.post("/research-panel/daily.html").status_code == 405
    response = client.get("/research-panel/?date=2026-10-28", follow_redirects=False)
    assert response.status_code in {307, 308}
    assert response.headers["location"] == "/research-panel/daily.html?date=2026-10-28"
    assert client.get("/api/v3/research/unprovided-report").status_code == 404


@pytest.mark.parametrize("bad_path", ["../private.json", "/etc/passwd", ".env", "archive//view.json", "code.py", "a/../b.json"])
def test_invalid_export_configuration_fails_closed(tmp_path, bad_path):
    root, export = fixture_site(tmp_path)
    content = json.loads(export.read_text())
    content["files"].append({"path": bad_path, "sha256": "0" * 64})
    export.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="RESEARCH_PANEL"):
        module().create_research_panel_router(root, export)


def test_duplicate_assets_and_invalid_digest_rejected(tmp_path):
    root, export = fixture_site(tmp_path)
    content = json.loads(export.read_text())
    content["files"].append(content["files"][0])
    export.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="RESEARCH_PANEL"):
        module().create_research_panel_router(root, export)
    content["files"] = [{"path": "daily.html", "sha256": "not-a-sha"}]
    export.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="RESEARCH_PANEL"):
        module().create_research_panel_router(root, export)


@pytest.mark.parametrize("role", ["combined", "gateway", "stage", "manager"])
def test_integration_preserves_existing_route_and_respects_role(tmp_path, monkeypatch, role):
    root, export = fixture_site(tmp_path)
    monkeypatch.setenv("V4_RESEARCH_PANEL_ROOT", str(root))
    monkeypatch.setenv("V4_RESEARCH_PANEL_ASSET_MANIFEST", str(export))
    monkeypatch.delenv("V4_OPENING_RAW_ROOT", raising=False)
    monkeypatch.delenv("V4_OPENING_SELECTION_ROOT", raising=False)
    app = FastAPI()

    @app.get("/api/v3/preselection-pools")
    def existing():
        return {"existing_contract": True}

    module().register_opening_research(app, module_role=role)
    client = TestClient(app)
    assert client.get("/api/v3/preselection-pools").json() == {"existing_contract": True}
    observation = client.get("/api/v3/research/opening-observation", params={"date": "2026-10-28", "symbol": "301655.SZ"})
    page = client.get("/research-panel/daily.html")
    if role in {"combined", "gateway"}:
        assert page.status_code == observation.status_code == 200
        assert observation.json()["RESEARCH_ONLY"] is True
        assert observation.json()["write_performed"] is False
        assert all(stage["availability"] in {"UNCONFIGURED", "NOT_DUE"} for stage in observation.json()["stages"])
    else:
        assert page.status_code == observation.status_code == 404


def test_integration_rejects_half_configured_panel(tmp_path, monkeypatch):
    root, _ = fixture_site(tmp_path)
    monkeypatch.setenv("V4_RESEARCH_PANEL_ROOT", str(root))
    monkeypatch.delenv("V4_RESEARCH_PANEL_ASSET_MANIFEST", raising=False)
    monkeypatch.delenv("V4_OPENING_RAW_ROOT", raising=False)
    monkeypatch.delenv("V4_OPENING_SELECTION_ROOT", raising=False)
    with pytest.raises(ValueError, match="RESEARCH_PANEL_CONFIGURATION_INCOMPLETE"):
        module().register_opening_research(FastAPI(), module_role="combined")
