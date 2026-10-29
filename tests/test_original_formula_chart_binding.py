import gzip
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.v4_api.research_router import create_research_router
from infrastructure.research_lane_source import ResearchLaneSource
from test_daily_completion_sse import _fixture_product_tree, _ref, _rebind_product

FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
FORMULA = "d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac"
ENGINE = "ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c"


def fixture(tmp_path):
    source_root = (tmp_path / "source").resolve()
    _, event, product = _fixture_product_tree(source_root)
    config_path = Path(product["source_config"]["path"])
    config = {"formula": {"path": "/not-read/formula.txt", "sha256": FORMULA},
              "engine": {"path": "/not-executed/engine.py", "sha256": ENGINE}}
    config_path.write_text(json.dumps(config))
    product["source_config"] = _ref(config_path)
    product["source_identity"]["basis"] = {"price_basis": "QFQ_ASOF", "volume_basis": "QFQ_EVENT_VOLUME"}
    Path(event["artifact"]["path"]).write_text(json.dumps(product))
    _rebind_product(source_root, event)
    product = ResearchLaneSource(source_root, a_share_daily_root=source_root).read_a_daily_product("20261029")
    root = (tmp_path / "artifacts").resolve()
    folder = root / "completed"
    folder.mkdir(parents=True)
    source_binding = {"product": product["artifact"], "manifest": product["manifest"], "config": product["source_config"], **config}
    cache = {"path": "/not-read/bound-cache.json", "sha256": "e" * 64, "bars_sha256": "f" * 64}
    projection = {"symbol": "600025.SH", "data_date": "20261029", **FLAGS,
        "source": {"generation_id": product["source_generation"], "source_input_sha256": product["source_identity"]["input_sha256"],
                   "price_basis": "QFQ_ASOF", "volume_basis": "QFQ_EVENT_VOLUME"},
        "source_cache": cache, "product_row_ref": product["row_refs"]["600025.SH"], "lineage": source_binding,
        "formula_result": {"formula_sha256": FORMULA, "mode": "prefix", "field_count": 51, "drawing_count": 22,
                           "rows": [{"trade_date": 20261029}]}, "unsupported_drawings": []}
    paths = {"projection": folder / "600025.projection.json.gz", "html": folder / "600025.html", "PNG": folder / "600025.png"}
    paths["projection"].write_bytes(gzip.compress(json.dumps(projection).encode()))
    paths["html"].write_bytes(b"<!doctype html><html>stored-original-chart</html>")
    paths["PNG"].write_bytes(b"\x89PNG\r\n\x1a\nstored-fixture")
    refs = {kind: _ref(path) for kind, path in paths.items()}
    manifest = {"samples": {"600025.SH": {"rows": 1, **refs}}, **FLAGS}
    receipt = {"status": "MECHANICAL_247_DELIVERY_PASS", "expected": 1, "verified": 1,
               "missing": [], "extra": [], "errors": [], "source_binding": source_binding, **FLAGS,
               "records": [{"symbol": "600025.SH", "data_date": "20261029", "source_generation": product["source_generation"],
                            "source_input_sha256": product["source_identity"]["input_sha256"], "formula_sha256": FORMULA,
                            "source_cache": cache, "product_row_ref": product["row_refs"]["600025.SH"], **refs}]}
    manifest_path, receipt_path = folder / "MANIFEST.json", folder / "COMPLETION_RECEIPT_247.json"
    binding = {"artifact_root": str(root)}

    def rebind():
        manifest_path.write_text(json.dumps(manifest))
        receipt_path.write_text(json.dumps(receipt))
        binding.update(manifest=_ref(manifest_path), receipt=_ref(receipt_path))

    def client():
        app = FastAPI()
        app.include_router(create_research_router(tmp_path / "consumer", shared_data_root=source_root,
                                                  original_chart_binding=binding))
        return TestClient(app, raise_server_exceptions=False)

    rebind()
    return client, binding, manifest, receipt, projection, paths, rebind


def test_exact_get_serves_same_verified_bytes_and_cannot_execute_engine(tmp_path):
    create, _, _, _, _, paths, _ = fixture(tmp_path)
    client = create()
    answer = client.get("/api/v4/research/a-share/original-chart", params={"date": "20261029", "symbol": "600025.SH"}).json()
    assert answer["status"] == "READY"
    for kind, source in (("html", "html"), ("png", "PNG"), ("projection", "projection")):
        response = client.get(answer["assets"][kind]["url"])
        assert response.status_code == 200
        assert response.content == paths[source].read_bytes()
        assert response.headers["x-original-chart-sha256"] == answer["assets"][kind]["sha256"]
    assert client.get(answer["assets"]["html"]["url"] + "&path=/etc/passwd").status_code == 409


@pytest.mark.parametrize("case", ["date", "symbol", "generation", "input", "sha", "formula", "engine", "outside", "symlink", "missing"])
def test_stale_tampered_or_escaped_artifacts_are_typed_cannot_confirm(tmp_path, case):
    create, binding, manifest, receipt, projection, paths, rebind = fixture(tmp_path)
    params = {"date": "20261029", "symbol": "600025.SH"}
    if case in ("date", "symbol", "generation", "input"):
        params.update({"date": {"date": "20261028"}, "symbol": {"symbol": "000001.SZ"},
                       "generation": {"generation": "0" * 64}, "input": {"input_sha256": "0" * 64}}[case])
    elif case == "sha":
        paths["html"].write_bytes(b"changed")
    elif case in ("formula", "engine"):
        if case == "formula":
            projection["formula_result"]["formula_sha256"] = "0" * 64
        else:
            projection["lineage"]["engine"] = {"path": "/not-executed/engine.py", "sha256": "0" * 64}
        paths["projection"].write_bytes(gzip.compress(json.dumps(projection).encode()))
        manifest["samples"]["600025.SH"]["projection"] = _ref(paths["projection"])
        receipt["records"][0]["projection"] = _ref(paths["projection"])
        rebind()
    elif case in ("outside", "symlink"):
        outside = tmp_path / "outside.html"
        outside.write_bytes(paths["html"].read_bytes())
        if case == "symlink":
            link = paths["html"].parent / "link.html"
            link.symlink_to(outside)
            outside = link
        ref = _ref(outside)
        manifest["samples"]["600025.SH"]["html"] = ref
        receipt["records"][0]["html"] = ref
        rebind()
    else:
        paths["PNG"].unlink()
    response = create().get("/api/v4/research/a-share/original-chart", params=params)
    assert response.status_code == 200
    assert response.json()["status"] == "CANNOT_CONFIRM"
    assert "assets" not in response.json()
