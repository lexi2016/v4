"""Three-sample, lossless d35c rendering projection over existing bound caches.

Not an authoritative producer: no acquisition, pool decisions, history labels,
shared state, or service changes. The pinned original interpreter is unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time

SAMPLES = ("600025.SH", "000410.SZ", "920454.BJ")
DATE = "20261029"
FORMULA_SHA = "d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac"
ENGINE_SHA = "ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c"
RENDERER_SHA = "49bd460a60501197ffb8f62e36854f071fcb742c781da48212636ee14c7b7f5a"
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def reference(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": sha(path.read_bytes())}


def pinned(ref):
    require(isinstance(ref, dict) and isinstance(ref.get("path"), str), "REFERENCE_INVALID")
    path = Path(ref["path"])
    require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(), "REFERENCE_PATH_INVALID")
    raw = path.read_bytes()
    require(sha(raw) == ref.get("sha256"), "REFERENCE_SHA_DRIFT")
    return raw


def safe(value):
    return all(value.get(key) is flag for key, flag in FLAGS.items())


def load_bound_inputs(config_path, coverage_path, index_path):
    index_ref = reference(index_path)
    index = json.loads(pinned(index_ref))
    manifest_ref = index["dates"][DATE]
    manifest = json.loads(pinned(manifest_ref))
    product = json.loads(pinned(manifest["artifact"]))
    require(safe(product) and safe(manifest) and product.get("sample_only") is False, "PRODUCT_SAFETY_OR_SCOPE")
    require(product.get("data_date") == manifest.get("data_date") == DATE, "PRODUCT_DATE_CONFLICT")
    config_ref = reference(config_path)
    require(config_ref == product.get("source_config"), "CONFIG_NOT_BOUND_TO_PRODUCT")
    config = json.loads(pinned(config_ref))
    require(config["engine"]["sha256"] == ENGINE_SHA and config["formula"]["sha256"] == FORMULA_SHA, "FORMULA_OR_ENGINE_PIN_CONFLICT")
    engine_raw, formula_raw = pinned(config["engine"]), pinned(config["formula"])
    spec = importlib.util.spec_from_file_location("bound_d35c_projection_engine", config["engine"]["path"])
    engine = importlib.util.module_from_spec(spec)
    exec(compile(engine_raw, config["engine"]["path"], "exec"), engine.__dict__)
    inventory = engine.inventory()
    coverage_ref = reference(coverage_path)
    coverage = json.loads(pinned(coverage_ref))
    identity = product["source_identity"]
    expected = {"data_date": DATE, "generation_id": product["source_generation"],
                "source_input_sha256": identity["input_sha256"], "formula_source_sha256": FORMULA_SHA,
                "price_basis": identity["basis"]["price_basis"], "volume_basis": identity["basis"]["volume_basis"]}
    require(identity["generation"] == product["source_generation"] and manifest["source_generation"] == product["source_generation"], "PRODUCT_GENERATION_CONFLICT")
    require(manifest["input_sha256"] == identity["input_sha256"], "PRODUCT_INPUT_CONFLICT")
    require(all(coverage["source_identity"].get(k) == v for k, v in expected.items()), "COVERAGE_IDENTITY_CONFLICT")
    items = {row["symbol"]: row for row in coverage["items"] if row["symbol"] in SAMPLES}
    require(set(items) == set(SAMPLES), "THREE_SAMPLES_NOT_COVERED")
    caches = {}
    bound = {}
    for symbol in SAMPLES:
        item = items[symbol]
        require(all(item.get(k) == v for k, v in expected.items()), "SAMPLE_IDENTITY_CONFLICT")
        require(item["product_row_ref"] == product["row_refs"].get(symbol), "PRODUCT_ROW_REFERENCE_CONFLICT")
        row = json.loads(pinned(item["product_row_ref"]))
        require(row["symbol"] == symbol and row["data_date"] == DATE and safe(row), "ROW_IDENTITY_CONFLICT")
        cache_ref = {k: item["source_cache"][k] for k in ("path", "sha256")}
        key = cache_ref["path"]
        if key not in caches:
            caches[key] = json.loads(pinned(cache_ref))
        cache = caches[key]
        require(safe(cache) and all(cache["source"].get(k) == v for k, v in expected.items()), "CACHE_IDENTITY_CONFLICT")
        require(cache["source"]["selector_artifact_sha256"] == identity["selector_artifact_sha256"], "SELECTOR_ARTIFACT_CONFLICT")
        require(cache["source"]["adjustment_convention"] == item["adjustment_convention"] == coverage["source_identity"]["adjustment_convention"], "ADJUSTMENT_CONFLICT")
        matches = [sample for sample in cache["samples"] if sample.get("symbol") == symbol]
        require(len(matches) == 1, "CACHE_SYMBOL_AMBIGUOUS")
        sample = matches[0]
        bars = sample["bars"]
        require(len(bars) == item["source_cache"]["rows"] and sha(canonical(bars)) == item["source_cache"]["bars_sha256"], "CACHE_BARS_SHA_OR_COUNT_CONFLICT")
        require(bars and bars[-1]["date"] == DATE and sample["prefix"]["end_date"] == DATE, "CACHE_DATE_CONFLICT")
        require(len({bar["date"] for bar in bars}) == len(bars) and all(bar["date"] <= DATE for bar in bars), "CACHE_DATE_COVERAGE_CONFLICT")
        bound[symbol] = {"sample": sample, "source": cache["source"], "item": item}
    return engine, inventory, bound, {"product_index": index_ref, "manifest": manifest_ref,
        "product": manifest["artifact"], "config": config_ref, "engine": config["engine"],
        "formula": config["formula"], "coverage": coverage_ref, "source_identity": identity,
        "formula_text_bytes": len(formula_raw)}


def project(engine, inventory, bound, symbol):
    require(symbol in SAMPLES, "SYMBOL_OUTSIDE_THREE_SAMPLES")
    sample = bound["sample"]
    bars = [{"trade_date": int(row["date"]), "open": row["open"], "high": row["high"],
             "low": row["low"], "close": row["close"], "vol": row["volume"]} for row in sample["bars"]]
    result = engine.json_ready(engine.compute(bars, mode="prefix"))
    require(result["formula_sha256"] == FORMULA_SHA and result["mode"] == "prefix", "ENGINE_RESULT_IDENTITY_CONFLICT")
    require(result["field_count"] == 51 and result["drawing_count"] == 22 and len(result["rows"]) == len(bars), "ENGINE_RESULT_COVERAGE_CONFLICT")
    names = [entry["name"] for entry in inventory["assignments"]]
    definitions = inventory["drawings"]
    require(len(names) == 51 and len(definitions) == 22, "INVENTORY_SHAPE_CONFLICT")
    unsupported = []
    for row, bar in zip(result["rows"], bars):
        require(row["trade_date"] == bar["trade_date"] and list(row["values"]) == names, "LOSSLESS_VALUE_COVERAGE_CONFLICT")
        require(len(row["drawings"]) == 22, "LOSSLESS_DRAWING_COVERAGE_CONFLICT")
        for drawing, definition in zip(row["drawings"], definitions):
            require(all(drawing[key] == definition[key] for key in ("id", "kind", "styles")), "DRAWING_DEFINITION_CONFLICT")
            if drawing["kind"] not in ("DRAWTEXT", "DRAWICON") or (drawing["kind"] == "DRAWICON" and drawing["payload"] not in ("1", "2")):
                unsupported.append({"trade_date": row["trade_date"], "drawing": drawing})
    return {"schema": "v4.d35c.three_sample_derivative_projection.v1", "symbol": symbol,
        "data_date": DATE, "authority": "DERIVED_RENDERING_ONLY", "historical_PIT": False,
        "source": bound["source"], "source_cache": bound["item"]["source_cache"],
        "product_row_ref": bound["item"]["product_row_ref"], "inventory": inventory,
        "formula_result": result, "unsupported_drawings": unsupported,
        "renderer_semantics": "UNCHANGED_R19_DISPLAY; NOT_NATIVE_TDX_ICON_OR_COLOR_EQUIVALENCE_CERTIFICATION", **FLAGS}


def chart_html(renderer_raw, projection, lineage):
    """Reuse the R19 canvas/table implementation; replace only transport and labels."""
    require(not projection["unsupported_drawings"], "RENDERER_DRAWING_TYPE_UNSUPPORTED")
    source = projection["source"]
    rows = projection["formula_result"]["rows"]
    payload = {"status": "READY", "symbol": projection["symbol"], "target_date": DATE,
        "rows": rows, "first_date": rows[0]["trade_date"], "last_date": rows[-1]["trade_date"],
        "total_rows": len(rows), "source_vendor": "EXISTING_BOUND_QFQ_CACHE",
        "source_kind": source["adjustment_convention"], "full_history_recomputed": True,
        "projection_source_label": f'{source["price_basis"]} / {source["volume_basis"]} / {source["adjustment_convention"]}；历史非PIT',
        "projection_lineage": lineage, **FLAGS}
    registry = {"entry_count": 1, "available_count": 1, "no_target_bar_count": 0, "pending_count": 0,
        "entries": [{"symbol": projection["symbol"], "rows": len(rows), "source_vendor": "BOUND_CACHE_DERIVATIVE"}]}
    embedded = json.dumps({"payload": payload, "registry": registry}, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    adapter = "<script>const projected=" + embedded + ";window.fetch=async function(url){const u=new URL(url,location.href);" + \
        "if(u.pathname==='/v1/registry')return new Response(JSON.stringify(projected.registry));" + \
        "if(u.pathname==='/v1/research'&&u.searchParams.get('symbol')===projected.payload.symbol&&u.searchParams.get('date')===projected.payload.target_date)return new Response(JSON.stringify(projected.payload));" + \
        "return new Response(JSON.stringify({status:'UNKNOWN',reason:'OUTSIDE_FROZEN_PROJECTION'}),{status:404});};</script>"
    html = renderer_raw.decode()
    html = re.sub(r"<title>.*?</title>", "<title>原式 d35c · D29 三样例派生投影</title>", html, count=1)
    html = re.sub(r"<header>.*?</header>", '<header><div><h1>原式 d35c · D29 三样例派生投影</h1><div class="muted">51变量与22绘图原样保留；仅渲染投影，独审及原生等价未确认。</div></div><span class="badge">RESEARCH_ONLY</span></header>', html, count=1)
    html = html.replace("2026-10-27", "2026-10-29").replace('id="draw-text" type="checkbox"', 'id="draw-text" type="checkbox" checked')
    html = html.replace("function sourceLabel(body){", "function sourceLabel(body){if(body.projection_source_label)return body.projection_source_label;")
    html = html.replace("正在显示已独审、已登记的完整重算产物。", "正在显示三样例原式派生投影，尚不构成独审或原生等价认证。")
    html = html.replace("已登记", "样例派生").replace("完整重算行数", "原式投影行数")
    return html.replace("<script>\n'use strict';", adapter + "<script>\n'use strict';", 1)


def write_json(path, value):
    path.write_bytes(canonical(value) + b"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "coverage", "product-index", "renderer", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--symbol", choices=SAMPLES, action="append")
    args = parser.parse_args()
    renderer_ref = reference(args.renderer)
    require(renderer_ref["sha256"] == RENDERER_SHA, "R19_RENDERER_PIN_CONFLICT")
    renderer_raw = pinned(renderer_ref)
    engine, inventory, bound, lineage = load_bound_inputs(args.config, args.coverage, args.product_index)
    lineage.update(renderer=renderer_ref, projection_code=reference(Path(__file__)))
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"schema": "d35c.three_sample_projection_manifest.v1", "samples": {}, **FLAGS}
    for symbol in dict.fromkeys(args.symbol or SAMPLES):
        started = time.perf_counter()
        stem = symbol.replace(".", "_")
        projection = project(engine, inventory, bound[symbol], symbol)
        projection["lineage"] = lineage
        output = args.output / (stem + ".projection.json")
        write_json(output, projection)
        html_path = args.output / (stem + ".html")
        html_path.write_text(chart_html(renderer_raw, projection, lineage))
        manifest["samples"][symbol] = {"projection": reference(output), "html": reference(html_path),
            "rows": len(projection["formula_result"]["rows"]), "values_per_row": 51, "drawings_per_row": 22,
            "unsupported_drawings": len(projection["unsupported_drawings"]), "seconds": time.perf_counter() - started,
            "visual_readback": "NOT_RUN", "independent_review": "PENDING"}
        write_json(manifest_path, manifest)
        print(json.dumps({"symbol": symbol, **manifest["samples"][symbol]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
