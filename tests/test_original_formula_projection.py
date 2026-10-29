import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops.render_original_formula_projection import FORMULA_SHA, FLAGS, chart_html, pinned, project, sha


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
    bound = {"sample": {"bars": [{"date": "20261029", "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2, "volume": 5.5}]},
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
    with pytest.raises(ValueError, match="SYMBOL_OUTSIDE_THREE_SAMPLES"):
        project(engine, inventory, bound, "000001.SZ")
