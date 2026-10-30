"""Explicit frozen-candidate d35c rendering projection over bound caches.

Not an authoritative producer: no acquisition, pool decisions, history labels,
shared state, or service changes. The pinned original interpreter is unchanged.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import resource
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
    return isinstance(value, dict) and all(value.get(key) is flag for key, flag in FLAGS.items())


def candidate_allowlist(coverage, product, requested):
    rows = coverage["items"]
    symbols = [row["symbol"] for row in rows]
    candidates = [row["symbol"] for row in product["rows"]]
    require(len(symbols) == len(set(symbols)) == len(candidates) == len(set(candidates)) == product["unique_count"] == 247,
            "CANDIDATE_ALLOWLIST_COUNT_OR_DUPLICATE")
    require(set(symbols) == set(candidates), "CANDIDATE_ALLOWLIST_PRODUCT_CONFLICT")
    require(requested and set(requested) <= set(symbols), "SYMBOL_OUTSIDE_BOUND_COVERAGE")
    return tuple(sorted(symbols))


def cache_sample(cache, item, symbol, expected, identity, coverage_identity, manifest_ref, product_ref):
    require(safe(cache) and all(cache["source"].get(k) == v for k, v in expected.items()), "CACHE_IDENTITY_CONFLICT")
    require(cache["source"]["selector_artifact_sha256"] == identity["selector_artifact_sha256"], "SELECTOR_ARTIFACT_CONFLICT")
    require(cache["source"]["adjustment_convention"] == item["adjustment_convention"] == coverage_identity["adjustment_convention"], "ADJUSTMENT_CONFLICT")
    require(("samples" in cache) != ("sample" in cache), "CACHE_SAMPLE_SHAPE_AMBIGUOUS")
    if "sample" in cache:
        samples = [cache["sample"]]
        require(cache.get("bars_sha256") == item["source_cache"]["bars_sha256"], "CACHE_BARS_SHA_OR_COUNT_CONFLICT")
        refs = cache["source_refs"]
        require(refs.get("product_manifest_path") == manifest_ref["path"] and refs.get("product_manifest_sha256") == manifest_ref["sha256"]
                and refs.get("product_path") == product_ref["path"] and refs.get("product_sha256") == product_ref["sha256"]
                and refs.get("product_row_ref_path") == item["product_row_ref"]["path"]
                and refs.get("product_row_ref_sha256") == item["product_row_ref"]["sha256"], "CACHE_PRODUCT_REFERENCE_CONFLICT")
    else:
        samples = cache["samples"]
    matches = [sample for sample in samples if sample.get("symbol") == symbol]
    require(len(matches) == 1, "CACHE_SYMBOL_AMBIGUOUS")
    sample = matches[0]
    bars = sample["bars"]
    require(len(bars) == item["source_cache"]["rows"] and sha(canonical(bars)) == item["source_cache"]["bars_sha256"], "CACHE_BARS_SHA_OR_COUNT_CONFLICT")
    require(bars and bars[-1]["date"] == DATE and sample["prefix"]["end_date"] == DATE, "CACHE_DATE_CONFLICT")
    require(len({bar["date"] for bar in bars}) == len(bars) and all(bar["date"] <= DATE for bar in bars), "CACHE_DATE_COVERAGE_CONFLICT")
    return sample


def load_bound_inputs(config_path, coverage_path, index_path, symbols=SAMPLES):
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
    allowed = candidate_allowlist(coverage, product, symbols)
    items = {row["symbol"]: row for row in coverage["items"] if row["symbol"] in symbols}
    caches = {}
    bound = {}
    failures = {}
    for symbol in dict.fromkeys(symbols):
      try:
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
        sample = cache_sample(cache, item, symbol, expected, identity, coverage["source_identity"], manifest_ref, manifest["artifact"])
        bound[symbol] = {"sample": sample, "source": cache["source"], "item": item, "allowed_symbols": allowed}
      except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        failures[symbol] = str(error)
    return engine, inventory, bound, {"product_index": index_ref, "manifest": manifest_ref,
        "product": manifest["artifact"], "config": config_ref, "engine": config["engine"],
        "formula": config["formula"], "coverage": coverage_ref, "source_identity": identity,
        "formula_text_bytes": len(formula_raw), "scope_symbols": allowed, "input_failures": failures}


def project(engine, inventory, bound, symbol):
    require(symbol in bound.get("allowed_symbols", ()) and bound["sample"].get("symbol") == symbol, "SYMBOL_OUTSIDE_BOUND_COVERAGE")
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
    return {"schema": "v4.d35c.bound_candidate_projection.v1", "symbol": symbol,
        "data_date": DATE, "authority": "DERIVED_RENDERING_ONLY", "historical_PIT": False,
        "source": bound["source"], "source_cache": bound["item"]["source_cache"],
        "product_row_ref": bound["item"]["product_row_ref"], "inventory": inventory,
        "formula_result": result, "unsupported_drawings": unsupported,
        "renderer_semantics": "UNCHANGED_R19_DISPLAY; NOT_NATIVE_TDX_ICON_OR_COLOR_EQUIVALENCE_CERTIFICATION", **FLAGS}


def interactive_chart_html(html):
    """Adapt installed local R19 setWindow/wheel/drag to this R19 row shape.

    Source: research-panel/r19-chart.js, SHA e66cbc2994b9ddcf13941323b9eb1dc9358e06ef902897d0226a2f2b862f3061.
    The existing choose/paint glyph and table code and embedded payload stay intact.
    """
    if 'id="original-view-reset"' in html:
        return html
    old = "const count=Number($('window').value),offset=count?Math.max(0,state.rows.length-count):0,rows=state.rows.slice(offset);"
    new = "const count=Number($('window').value);if(!state.view){const n=count?Math.min(count,state.rows.length):state.rows.length;state.view={start:state.rows.length-n,count:n};}const offset=state.view.start,rows=state.rows.slice(offset,offset+state.view.count);"
    require(html.count(old) == 1 and html.count("$('window').onchange=paint;") == 1, "LOCAL_R19_VIEWPORT_ADAPTER_MISMATCH")
    html = html.replace(old, new, 1).replace("state.visible=[];delete document.documentElement.dataset.loaded", "state.visible=[];state.view=null;delete document.documentElement.dataset.loaded", 1)
    html = html.replace("$('window').onchange=paint;", "$('window').onchange=()=>setOriginalWindow(Number($('window').value),state.rows.length);", 1)
    html = html.replace('</select><label><input id="draw-text"', '</select><button type="button" id="original-view-reset">恢复原区间</button><label><input id="draw-text"', 1)
    html = html.replace('touch-action:pan-y', 'touch-action:none')
    script = r"""
// Existing local R19 interaction semantics; only rows/geometry names are adapted.
function setOriginalWindow(count,end){const n=state.rows.length;if(!n)return;const view=state.view||{start:0,count:n};view.count=count===0?n:Math.max(Math.min(10,n),Math.min(n,Math.round(count)));view.start=Math.max(0,Math.min(n-view.count,(end??(view.start+view.count))-view.count));state.view=view;paint();}
const originalCanvas=$('chart');let originalDrag=null;
$('original-view-reset').onclick=()=>{setOriginalWindow(Number($('window').value),state.rows.length);choose(state.rows.length-1);paint();};
originalCanvas.onpointerdown=e=>{originalDrag={x:e.clientX,start:state.view?.start||0};originalCanvas.setPointerCapture(e.pointerId);};
originalCanvas.onpointerup=()=>{originalDrag=null;};originalCanvas.onpointercancel=()=>{originalDrag=null;};originalCanvas.onlostpointercapture=()=>{originalDrag=null;};
originalCanvas.onpointermove=e=>{if(!state.visible.length||!state.geometry)return;const{L,step}=state.geometry;if(originalDrag){state.view.start=Math.max(0,Math.min(state.rows.length-state.view.count,originalDrag.start-Math.round((e.clientX-originalDrag.x)/step)));paint();}const xx=e.clientX-originalCanvas.getBoundingClientRect().left;const hover=Math.max(0,Math.min(state.visible.length-1,Math.floor((xx-L)/step)));choose(state.offset+hover);paint();};
originalCanvas.addEventListener('wheel',e=>{e.preventDefault();if(!state.view)return;const oldEnd=state.view.start+state.view.count;setOriginalWindow(Math.round(state.view.count*(e.deltaY>0?1.2:.8)),oldEnd);},{passive:false});
"""
    require(html.count('(async()=>{try{const response=await fetch(\'/v1/registry\'') == 1, "LOCAL_R19_INITIALIZATION_MISMATCH")
    return html.replace("(async()=>{try{const response=await fetch('/v1/registry'", script + "\n(async()=>{try{const response=await fetch('/v1/registry'", 1)


def chart_html(renderer_raw, projection, lineage, *, compress_payload=False):
    """Reuse the R19 canvas/table implementation; replace only transport and labels."""
    require(not projection["unsupported_drawings"], "RENDERER_DRAWING_TYPE_UNSUPPORTED")
    source = projection["source"]
    rows = projection["formula_result"]["rows"]
    date = projection["data_date"]
    payload = {"status": "READY", "symbol": projection["symbol"], "target_date": date,
        "rows": rows, "first_date": rows[0]["trade_date"], "last_date": rows[-1]["trade_date"],
        "total_rows": len(rows), "source_vendor": "EXISTING_BOUND_QFQ_CACHE",
        "source_kind": source["adjustment_convention"], "full_history_recomputed": True,
        "projection_source_label": f'{source["price_basis"]} / {source["volume_basis"]} / {source["adjustment_convention"]}；历史非PIT',
        "projection_lineage": lineage, **FLAGS}
    registry = {"entry_count": 1, "available_count": 1, "no_target_bar_count": 0, "pending_count": 0,
        "entries": [{"symbol": projection["symbol"], "rows": len(rows), "source_vendor": "BOUND_CACHE_DERIVATIVE"}]}
    embedded = json.dumps({"payload": payload, "registry": registry}, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    if compress_payload:
        encoded = base64.b64encode(gzip.compress(embedded.encode(), mtime=0)).decode()
        loader = "const projectionGzip='" + encoded + "';const projectedReady=(async()=>{const bytes=Uint8Array.from(atob(projectionGzip),c=>c.charCodeAt(0));" + \
            "const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));return JSON.parse(await new Response(stream).text());})();"
    else:
        loader = "const projectedReady=Promise.resolve(" + embedded + ");"
    adapter = "<script>" + loader + "window.fetch=async function(url){const projected=await projectedReady;const u=new URL(url,location.href);" + \
        "if(u.pathname==='/v1/registry')return new Response(JSON.stringify(projected.registry));" + \
        "if(u.pathname==='/v1/research'&&u.searchParams.get('symbol')===projected.payload.symbol&&u.searchParams.get('date')===projected.payload.target_date)return new Response(JSON.stringify(projected.payload));" + \
        "return new Response(JSON.stringify({status:'UNKNOWN',reason:'OUTSIDE_FROZEN_PROJECTION'}),{status:404});};</script>"
    html = renderer_raw.decode()
    label = "D29" if date == DATE else "D" + date
    html = re.sub(r"<title>.*?</title>", f"<title>原式 d35c · {label} 候选派生投影</title>", html, count=1)
    html = re.sub(r"<header>.*?</header>", f'<header><div><h1>原式 d35c · {label} 候选派生投影</h1><div class="muted">51变量与22绘图原样保留；仅渲染投影，独审及原生等价未确认。</div></div><span class="badge">RESEARCH_ONLY</span></header>', html, count=1)
    html = html.replace("2026-10-27", f"{date[:4]}-{date[4:6]}-{date[6:]}").replace('id="draw-text" type="checkbox"', 'id="draw-text" type="checkbox" checked')
    html = html.replace("function sourceLabel(body){", "function sourceLabel(body){if(body.projection_source_label)return body.projection_source_label;")
    html = html.replace("正在显示已独审、已登记的完整重算产物。", "正在显示候选原式派生投影，尚不构成独审或原生等价认证。")
    html = html.replace("已登记", "样例派生").replace("完整重算行数", "原式投影行数")
    return interactive_chart_html(html.replace("<script>\n'use strict';", adapter + "<script>\n'use strict';", 1))


def write_json(path, value):
    temporary = path.with_name("." + path.name + ".pending")
    temporary.write_bytes(canonical(value) + b"\n")
    temporary.replace(path)


OWNER_RENDERER = {"path": "/Users/lexi/Desktop/学习/因子工厂/research/tdx_panel_parity_20261028_r1/r19_copy/OUTSIDE151_R19/outside151/r19_work/research_reader/index.html", "sha256": RENDERER_SHA}


def retain_owner_result(context, parts, symbol, bars, result):
    """Keep the candidate's existing computation, never invoke compute here."""
    require(context.config["formula"]["sha256"] == FORMULA_SHA and context.config["engine"]["sha256"] == ENGINE_SHA,
            "OWNER_FORMULA_ENGINE_CONFLICT")
    if not hasattr(context, "_original_chart_inventory"):
        context._original_chart_inventory = context.engine().inventory()
    payload = {"symbol": symbol, "data_date": str(context.target), "identity": context.identity,
        "config": context.config_ref, "bars_sha256": sha(canonical(bars)), "bar_dates": [b["trade_date"] for b in bars],
        "calendar": context.calendars[symbol[-2:]], "inventory": context._original_chart_inventory,
        "formula_result": context.engine().json_ready(result), **FLAGS}
    path = Path(parts) / "original_retained" / (symbol + ".json.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".pending")
    temporary.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(), mtime=0)); temporary.replace(path)


def owner_pngs(items):
    """Same R19 headless canvas checks, one private browser for this owner run."""
    import subprocess
    script = r"""
const fs=require('fs'),{pathToFileURL}=require('url');
const {chromium}=require('/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{let browser;const errors={};try{
browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--no-first-run','--no-default-browser-check','--disable-extensions','--disable-background-networking']});
const context=await browser.newContext({viewport:{width:1600,height:1200}});
await context.route('**/*',r=>r.request().url().startsWith('file://')&&['GET','HEAD'].includes(r.request().method())?r.continue():r.abort());
for(const item of JSON.parse(fs.readFileSync(0,'utf8'))){let page;try{
page=await context.newPage();const faults=[];page.on('pageerror',e=>faults.push(String(e)));
await page.goto(pathToFileURL(item.html).href,{waitUntil:'load'});await page.waitForFunction(s=>document.documentElement.dataset.loaded===s,item.symbol);
const ok=await page.evaluate(item=>{const state=window.RESEARCH_PANEL_STATE,canvas=document.querySelector('#chart'),pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;let visible=false;for(let i=3;i<pixels.length;i+=4)if(pixels[i]){visible=true;break;}return state.symbol===item.symbol&&state.rows.at(-1).trade_date===Number(item.date)&&state.rows.length===item.rows&&document.querySelectorAll('#values tr').length===51&&document.querySelectorAll('#drawings tr').length===22&&document.querySelector('#draw-text').checked&&visible;},item);
if(!ok||faults.length)throw Error('OWNER_ACTUAL_RENDER_CONTRACT:'+faults.join(';'));await page.screenshot({path:item.png,fullPage:true});
}catch(e){errors[item.symbol]=String(e);}finally{if(page)await page.close();}}
}finally{if(browser)await browser.close();}process.stdout.write(JSON.stringify(errors));})().catch(e=>{console.error(String(e));process.exitCode=1;});
"""
    run = subprocess.run(["/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node", "-e", script],
        input=json.dumps(items), capture_output=True, text=True)
    require(run.returncode == 0, "OWNER_HEADLESS_UNAVAILABLE:" + run.stderr[-1000:])
    return json.loads(run.stdout)


def finalize_owner_charts(context, parts, product, manifest_ref, artifact, *, gaps, png_renderer=None):
    """Numeric hashes are final first; sidecars point to them, never vice versa."""
    renderer_raw = pinned(OWNER_RENDERER)
    lineage = {"product": artifact, "manifest": manifest_ref, "config": context.config_ref,
        "engine": context.config["engine"], "formula": context.config["formula"], "renderer": OWNER_RENDERER}
    output = Path(manifest_ref["path"]).parent / "original_charts"
    output.mkdir(parents=True, exist_ok=True)
    samples, records, errors, pending = {}, {}, {}, []
    for row in product["rows"]:
        symbol = row["symbol"]
        try:
            require(re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", symbol), "OWNER_SYMBOL_INVALID")
            checkpoint = output / (symbol + ".ready.json")
            if checkpoint.is_file():
                prior = json.loads(checkpoint.read_text())
                require(prior["source_binding"] == lineage and prior["product_row_ref"] == product["row_refs"][symbol]
                        and prior["symbol"] == symbol and prior["data_date"] == str(context.target)
                        and prior["source_generation"] == context.generation
                        and prior["source_input_sha256"] == context.identity["input_sha256"]
                        and prior["formula_sha256"] == FORMULA_SHA
                        and prior["source_cache"]["path"] == str(Path(parts) / "original_retained" / (symbol + ".json.gz"))
                        and prior["source_cache"]["calendar_sha256"] == sha(canonical(context.calendars[symbol[-2:]])), "OWNER_CHART_CACHE_IDENTITY_CONFLICT")
                pinned(prior["source_cache"])
                for kind in ("html", "PNG", "projection"):
                    require(Path(prior[kind]["path"]).is_relative_to(output), "OWNER_CHART_CACHE_PATH_CONFLICT")
                    pinned(prior[kind])
                samples[symbol] = prior; records[symbol] = prior
                continue
            retained_path = Path(parts) / "original_retained" / (symbol + ".json.gz")
            require(retained_path.is_file(), gaps.get(symbol, "RETAINED_FULL_RESULT_MISSING_LEGACY_NUMERIC_CACHE_NO_RECOMPUTE"))
            retained_ref = reference(retained_path)
            with gzip.open(retained_path, "rb") as stream:
                raw = stream.read(64 * 1024 * 1024 + 1)
            require(len(raw) <= 64 * 1024 * 1024, "OWNER_RETAINED_SIZE_LIMIT")
            retained = json.loads(raw)
            require(safe(retained) and retained["symbol"] == symbol and retained["data_date"] == str(context.target)
                    and retained["identity"] == context.identity and retained["config"] == context.config_ref
                    and retained["calendar"] == context.calendars[symbol[-2:]], "OWNER_RETAINED_BINDING_CONFLICT")
            result, inventory = retained["formula_result"], retained["inventory"]
            names = [entry["name"] for entry in inventory["assignments"]]
            definitions = inventory["drawings"]
            require(result["formula_sha256"] == FORMULA_SHA and result["mode"] == "prefix"
                    and result["field_count"] == len(names) == 51 and result["drawing_count"] == len(definitions) == 22
                    and [r["trade_date"] for r in result["rows"]] == retained["bar_dates"]
                    and retained["bar_dates"][-1] == context.target, "OWNER_RESULT_SHAPE_CONFLICT")
            for value in result["rows"]:
                require(list(value["values"]) == names and len(value["drawings"]) == 22, "OWNER_RESULT_LOSSLESS_CONFLICT")
                for drawing, definition in zip(value["drawings"], definitions):
                    require(all(drawing[k] == definition[k] for k in ("id", "kind", "styles"))
                            and drawing["kind"] in ("DRAWTEXT", "DRAWICON")
                            and (drawing["kind"] != "DRAWICON" or drawing["payload"] in ("1", "2")), "OWNER_DRAWING_UNSUPPORTED")
            source = {"generation_id": context.generation, "source_input_sha256": context.identity["input_sha256"],
                "price_basis": context.identity["basis"]["price_basis"], "volume_basis": context.identity["basis"]["volume_basis"],
                "adjustment_convention": context.identity["basis"].get("adjustment_convention", "BOUND_ORIGINAL_OWNER_QFQ")}
            cache = {**retained_ref, "bars_sha256": retained["bars_sha256"], "rows": len(result["rows"]),
                "calendar_sha256": sha(canonical(retained["calendar"]))}
            projection = {"schema": "v4.d35c.bound_candidate_projection.v1", "symbol": symbol, "data_date": str(context.target),
                "authority": "DERIVED_RENDERING_ONLY", "historical_PIT": False, "source": source, "source_cache": cache,
                "product_row_ref": product["row_refs"][symbol], "inventory": inventory, "formula_result": result,
                "unsupported_drawings": [], "lineage": lineage, **FLAGS}
            projection_path, html_path, png_path = (output / (symbol + suffix) for suffix in (".projection.json.gz", ".html", ".png"))
            projection_path.write_bytes(gzip.compress(canonical(projection), mtime=0))
            html_path.write_text(chart_html(renderer_raw, projection, lineage, compress_payload=True))
            item = {"symbol": symbol, "data_date": str(context.target), "source_generation": context.generation,
                "source_input_sha256": context.identity["input_sha256"], "formula_sha256": FORMULA_SHA,
                "source_binding": lineage, "source_cache": cache, "product_row_ref": product["row_refs"][symbol],
                "rows": len(result["rows"]), "projection": reference(projection_path), "html": reference(html_path)}
            records[symbol] = item
            pending.append({"symbol": symbol, "date": str(context.target), "rows": item["rows"], "html": str(html_path), "png": str(png_path)})
        except Exception as error:
            errors[symbol] = str(error)
    if pending:
        try:
            render_errors = (png_renderer or owner_pngs)(pending)
        except Exception as error:
            render_errors = {item["symbol"]: str(error) for item in pending}
        for item in pending:
            symbol = item["symbol"]
            try:
                require(symbol not in render_errors, render_errors.get(symbol))
                record = records[symbol]; record["PNG"] = reference(item["png"])
                write_json(output / (symbol + ".ready.json"), record)
                samples[symbol] = record
            except Exception as error:
                errors[symbol] = str(error)
    status = "OWNER_CHARTS_PARTIAL" if errors else "OWNER_CHARTS_COMPLETED"
    manifest = {"schema": "v4.a_share.owner_original_charts.v1", "samples": samples, **FLAGS}
    receipt = {"status": status, "owner_sidecar": True, "expected": len(product["rows"]), "verified": len(samples),
        "missing": [], "extra": [], "errors": [{"symbol": s, "reason": r} for s, r in sorted(errors.items())],
        "records": [samples[s] for s in sorted(samples)], "source_binding": lineage, **FLAGS}
    write_json(output / "MANIFEST.json", manifest); write_json(output / "COMPLETION_RECEIPT.json", receipt)
    return {"status": status, "numeric_manifest": manifest_ref, "manifest": reference(output / "MANIFEST.json"),
        "receipt": reference(output / "COMPLETION_RECEIPT.json")}


def reuse_reviewed_three(manifest_path, bound):
    manifest_ref = reference(manifest_path)
    old = json.loads(pinned(manifest_ref))
    review_ref = reference(Path(manifest_path).parent / "INDEPENDENT_REVIEW_RECEIPT.json")
    review = json.loads(pinned(review_ref))
    require(safe(old) and safe(review) and review["status"] == "REVIEWED_PASS_BEHAVIOR_VERIFIED_3SAMPLES_ONLY", "OLD_THREE_PASS_UNBOUND")
    require(set(old["samples"]) == set(review["samples"]) == set(SAMPLES), "OLD_THREE_SCOPE_CONFLICT")
    reused = {}
    for symbol in SAMPLES:
        item = old["samples"][symbol]
        projection = json.loads(pinned(item["projection"]))
        pinned(item["html"])
        require(projection["symbol"] == symbol and projection["data_date"] == DATE and safe(projection), "OLD_THREE_IDENTITY_CONFLICT")
        require(projection["source_cache"] == bound[symbol]["item"]["source_cache"]
                and projection["product_row_ref"] == bound[symbol]["item"]["product_row_ref"]
                and projection["formula_result"]["formula_sha256"] == FORMULA_SHA
                and projection["lineage"]["projection_code"]["sha256"] == review["source_hashes"]["ops/render_original_formula_projection.py"], "OLD_THREE_BINDING_CONFLICT")
        reused[symbol] = {**item, "status": "REUSED_INDEPENDENT_PASS", "review_receipt": review_ref, "reused_manifest": manifest_ref}
    return reused


def export_one(engine, inventory, bound, symbol, lineage, renderer_raw, output):
    """One independent checkpoint; a controller may schedule these after review."""
    started = time.perf_counter()
    stem = symbol.replace(".", "_")
    checkpoints = output / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpoints / (stem + ".json")
    binding = sha(canonical({"symbol": symbol, "product": lineage["product"], "cache": bound["item"]["source_cache"],
                             "code": lineage["projection_code"], "renderer": lineage["renderer"], "format": "LOSSLESS_GZIP_V1"}))
    if checkpoint.exists():
        prior = json.loads(checkpoint.read_text())
        if prior.get("status") == "READY" and prior.get("binding_sha256") == binding:
            pinned(prior["projection"])
            pinned(prior["html"])
            return prior
    try:
        projection = project(engine, inventory, bound, symbol)
        projection["lineage"] = lineage
        raw = canonical(projection) + b"\n"
        packed = gzip.compress(raw, mtime=0)
        require(gzip.decompress(packed) == raw, "PROJECTION_GZIP_PARITY_CONFLICT")
        projection_path = output / (stem + ".projection.json.gz")
        projection_path.write_bytes(packed)
        html_path = output / (stem + ".html")
        html_path.write_text(chart_html(renderer_raw, projection, lineage, compress_payload=True))
        record = {"status": "READY", "binding_sha256": binding, "projection": reference(projection_path),
            "html": reference(html_path), "rows": len(projection["formula_result"]["rows"]),
            "values_per_row": 51, "drawings_per_row": 22, "unsupported_drawings": len(projection["unsupported_drawings"]),
            "format": "LOSSLESS_GZIP_V1;HTML_GZIP_BASE64_PAYLOAD", "projection_uncompressed_bytes": len(raw),
            "projection_gzip_bytes": len(packed), "html_bytes": html_path.stat().st_size,
            "seconds": time.perf_counter() - started, "worker_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "visual_readback": "NOT_RUN", "independent_review": "PENDING"}
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        record = {"status": "CANNOT_CONFIRM", "reason": str(error), "binding_sha256": binding,
                  "seconds": time.perf_counter() - started}
    write_json(checkpoint, record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "coverage", "product-index", "renderer", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--symbol", action="append", required=True, help="Explicit current-coverage symbol; never defaults to all247")
    parser.add_argument("--reuse-manifest", type=Path, help="Reference the independently passed three outputs without recomputation")
    args = parser.parse_args()
    renderer_ref = reference(args.renderer)
    require(renderer_ref["sha256"] == RENDERER_SHA, "R19_RENDERER_PIN_CONFLICT")
    renderer_raw = pinned(renderer_ref)
    requested = tuple(dict.fromkeys(args.symbol))
    require(args.reuse_manifest is not None or not set(requested) & set(SAMPLES), "OLD_THREE_REQUIRE_REVIEWED_REUSE_MANIFEST")
    inputs = tuple(dict.fromkeys(requested + (SAMPLES if args.reuse_manifest else ())))
    engine, inventory, bound, lineage = load_bound_inputs(args.config, args.coverage, args.product_index, inputs)
    lineage.update(renderer=renderer_ref, projection_code=reference(Path(__file__)))
    args.output.mkdir(parents=True, exist_ok=True)
    binding_path = args.output / "INPUT_BINDING.json"
    input_binding = {key: lineage[key] for key in ("product", "manifest", "config", "engine", "formula", "coverage", "renderer", "scope_symbols")}
    if binding_path.exists():
        require(json.loads(binding_path.read_text()) == json.loads(canonical(input_binding)), "FROZEN_EXPORT_INPUT_DRIFT")
    else:
        write_json(binding_path, input_binding)
    manifest_path = args.output / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"schema": "d35c.bound_candidate_projection_manifest.v1", "samples": {}, **FLAGS}
    if args.reuse_manifest:
        require(not set(SAMPLES) & set(lineage["input_failures"]), "OLD_THREE_CURRENT_BINDING_INVALID")
        manifest["samples"].update(reuse_reviewed_three(args.reuse_manifest, bound))
    for symbol in requested:
        if symbol in manifest["samples"] and manifest["samples"][symbol].get("status") == "REUSED_INDEPENDENT_PASS":
            continue
        if symbol in lineage["input_failures"]:
            record = {"status": "CANNOT_CONFIRM", "reason": lineage["input_failures"][symbol]}
        else:
            record = export_one(engine, inventory, bound[symbol], symbol, lineage, renderer_raw, args.output)
        manifest["samples"][symbol] = record
        write_json(manifest_path, manifest)
        print(json.dumps({"symbol": symbol, **record}, ensure_ascii=False), flush=True)
    write_json(manifest_path, manifest)
    if any(manifest["samples"][symbol].get("status") == "CANNOT_CONFIRM" for symbol in requested):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
