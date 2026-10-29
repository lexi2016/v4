import json
import base64
import gzip
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from ops.render_original_formula_projection import (FORMULA_SHA, FLAGS, cache_sample, candidate_allowlist,
    canonical, chart_html, export_one, pinned, project, sha)


def fixture(kind="DRAWTEXT"):
    names = ["变量" + str(i) for i in range(51)]
    definitions = [{"id": i + 1, "kind": kind if i == 0 else "DRAWICON", "styles": ["COLORRED"] if i == 0 else []}
                   for i in range(22)]
    values = {name: None if i == 0 else False if i == 1 else "0.1234567890123456789012345678" for i, name in enumerate(names)}
    drawings = [{**entry, "condition": None if i == 0 else True, "y": None if i == 0 else "1.123456789012345678901234567",
                 "payload": "原式文字" if i == 0 else "1"} for i, entry in enumerate(definitions)]
    result = {"formula_sha256": FORMULA_SHA, "mode": "prefix", "field_count": 51, "drawing_count": 22,
              "rows": [{"trade_date": 20261029, "ohlcv": {"close": "1.2"}, "values": values, "drawings": drawings}]}
    received = []

    def compute(bars, mode):
        received.extend(bars)
        assert mode == "prefix"
        return result

    engine = SimpleNamespace(compute=compute, json_ready=lambda value: value)
    inventory = {"assignments": [{"name": name} for name in names], "drawings": definitions}
    bound = {"sample": {"symbol": "600025.SH", "bars": [{"date": "20261029", "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2, "volume": 5.5}]},
             "allowed_symbols": ("600025.SH", "000410.SZ", "920454.BJ"),
             "source": {"price_basis": "QFQ_ASOF", "volume_basis": "QFQ_EVENT_VOLUME", "adjustment_convention": "BOUND_EXISTING"},
             "item": {"source_cache": {"sha256": "a" * 64}, "product_row_ref": {"sha256": "b" * 64}}}
    return engine, inventory, bound, result, received


def test_lossless_all_values_drawings_null_false_and_decimal_strings():
    engine, inventory, bound, result, received = fixture()
    projection = project(engine, inventory, bound, "600025.SH")
    assert json.loads(json.dumps(projection))["formula_result"] == result
    assert projection["formula_result"]["rows"][0]["values"]["变量0"] is None
    assert projection["formula_result"]["rows"][0]["values"]["变量1"] is False
    assert len(projection["formula_result"]["rows"][0]["drawings"]) == 22
    assert received[0]["vol"] == 5.5 and received[0]["trade_date"] == 20261029
    assert all(projection[key] is value for key, value in FLAGS.items())


def test_unsupported_drawing_is_preserved_and_rendering_fails_explicitly():
    engine, inventory, bound, _, _ = fixture("UNSUPPORTED_NATIVE_DRAWING")
    projection = project(engine, inventory, bound, "600025.SH")
    assert projection["formula_result"]["rows"][0]["drawings"][0]["kind"] == "UNSUPPORTED_NATIVE_DRAWING"
    assert len(projection["unsupported_drawings"]) == 1
    with pytest.raises(ValueError, match="RENDERER_DRAWING_TYPE_UNSUPPORTED"):
        chart_html(b"", projection, {})


def test_missing_value_or_drawing_is_rejected_instead_of_truncated():
    for missing in ("value", "drawing"):
        engine, inventory, bound, result, _ = fixture()
        if missing == "value":
            result["rows"][0]["values"].pop("变量50")
        else:
            result["rows"][0]["drawings"].pop()
        with pytest.raises(ValueError, match="LOSSLESS"):
            project(engine, inventory, bound, "600025.SH")


def test_sha_drift_and_symbol_scope_fail_closed(tmp_path: Path):
    path = tmp_path / "pinned.txt"
    path.write_bytes(b"original")
    ref = {"path": str(path.resolve()), "sha256": sha(path.read_bytes())}
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="REFERENCE_SHA_DRIFT"):
        pinned(ref)
    engine, inventory, bound, _, _ = fixture()
    with pytest.raises(ValueError, match="SYMBOL_OUTSIDE_BOUND_COVERAGE"):
        project(engine, inventory, bound, "000001.SZ")


def test_explicit_247_allowlist_rejects_extra_duplicate_and_unrequested_scope():
    symbols = ["600814.SH"] + [str(100000 + i) + ".SH" for i in range(246)]
    coverage = {"items": [{"symbol": symbol} for symbol in symbols]}
    product = {"rows": [{"symbol": symbol} for symbol in symbols], "unique_count": 247}
    assert "600814.SH" in candidate_allowlist(coverage, product, ["600814.SH"])
    with pytest.raises(ValueError, match="SYMBOL_OUTSIDE_BOUND_COVERAGE"):
        candidate_allowlist(coverage, product, ["000001.SZ"])
    with pytest.raises(ValueError, match="SYMBOL_OUTSIDE_BOUND_COVERAGE"):
        candidate_allowlist(coverage, product, [])
    coverage["items"][-1] = coverage["items"][0]
    with pytest.raises(ValueError, match="ALLOWLIST_COUNT_OR_DUPLICATE"):
        candidate_allowlist(coverage, product, ["600814.SH"])


def test_single_stock_cache_binding_and_legacy_sample_shape():
    _, _, bound, _, _ = fixture()
    sample = {**bound["sample"], "symbol": "600814.SH", "prefix": {"end_date": "20261029"}}
    expected = {"data_date": "20261029", "generation_id": "g", "source_input_sha256": "i",
                "formula_source_sha256": FORMULA_SHA, "price_basis": "QFQ_ASOF", "volume_basis": "QFQ_EVENT_VOLUME"}
    source = {**expected, "selector_artifact_sha256": "a" * 64, "adjustment_convention": "BOUND_EXISTING"}
    item = {"adjustment_convention": "BOUND_EXISTING", "source_cache": {"rows": 1, "bars_sha256": sha(canonical(sample["bars"]))},
            "product_row_ref": {"path": "/row", "sha256": "b" * 64}}
    manifest, product = {"path": "/manifest", "sha256": "c" * 64}, {"path": "/product", "sha256": "d" * 64}
    refs = {"product_manifest_path": "/manifest", "product_manifest_sha256": "c" * 64,
            "product_path": "/product", "product_sha256": "d" * 64,
            "product_row_ref_path": "/row", "product_row_ref_sha256": "b" * 64}
    cache = {**FLAGS, "source": source, "sample": sample, "source_refs": refs, "bars_sha256": item["source_cache"]["bars_sha256"]}
    args = (item, "600814.SH", expected, {"selector_artifact_sha256": "a" * 64}, source, manifest, product)
    assert cache_sample(cache, *args) is sample
    legacy = {**FLAGS, "source": source, "samples": [sample]}
    assert cache_sample(legacy, *args) is sample
    cache["source_refs"]["product_row_ref_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="CACHE_PRODUCT_REFERENCE_CONFLICT"):
        cache_sample(cache, *args)
    cache["source_refs"]["product_row_ref_sha256"] = "b" * 64
    cache["sample"]["bars"][0]["close"] = 9
    with pytest.raises(ValueError, match="CACHE_BARS_SHA_OR_COUNT_CONFLICT"):
        cache_sample(cache, *args)


def test_gzip_projection_and_embedded_payload_are_lossless_and_checkpoint_reuses(tmp_path):
    engine, inventory, bound, expected_result, received = fixture()
    bound["sample"]["symbol"] = "600814.SH"
    bound["allowed_symbols"] = ("600814.SH",)
    renderer = b"<title>old</title><header>old</header><script>\n'use strict';\nfunction choose(i){return i;}\nfunction paint(){return '#fff';}\nasync function load(){}</script>"
    lineage = {"product": {"sha256": "a" * 64}, "projection_code": {"sha256": "b" * 64}, "renderer": {"sha256": sha(renderer)}}
    output = tmp_path.resolve()
    record = export_one(engine, inventory, bound, "600814.SH", lineage, renderer, output)
    assert record["status"] == "READY"
    projection = json.loads(gzip.decompress(Path(record["projection"]["path"]).read_bytes()))
    assert projection["formula_result"] == expected_result
    html = Path(record["html"]["path"]).read_text()
    encoded = re.search(r"const projectionGzip='([^']+)'", html).group(1)
    embedded = json.loads(gzip.decompress(base64.b64decode(encoded)))
    assert embedded["payload"]["rows"] == expected_result["rows"]
    assert "function choose(i){return i;}" in html and "function paint(){return '#fff';}" in html
    assert "DecompressionStream('gzip')" in html
    assert export_one(engine, inventory, bound, "600814.SH", lineage, renderer, output) == record
    assert len(received) == 1, "completed matching checkpoint must avoid a second engine compute"
