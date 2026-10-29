import json
from pathlib import Path
import subprocess


def test_original_chart_client_identity_and_url_guards():
    root = Path(__file__).resolve().parents[1]
    script = r"""
const assert = require('node:assert/strict');
const api = require(process.argv[1]);
const product = {data_date:'20261029', source_generation:'g', source_identity:{input_sha256:'i'},
 manifest:{path:'/manifest',sha256:'m'},artifact:{path:'/product',sha256:'p'}};
const symbol = '600025.SH', sha = 'a'.repeat(64);
const answer = {schema_version:'v4.a_share.original_chart.v1',status:'READY',symbol,data_date:product.data_date,
 source_generation:'g',input_sha256:'i',formula_sha256:api.D29_NUMERIC_FORMULA_SHA256,engine_sha256:api.ORIGINAL_ENGINE_SHA256,
 product_manifest:product.manifest,product_artifact:product.artifact,research_only:true,production_allowed:false,
 buy_gate_updated:false,orders_sent:false,rows:1,values_per_row:51,drawings_per_row:22,
 assets:{html:{sha256:sha,url:'/api/v4/research/a-share/original-chart/html?'+new URLSearchParams({date:product.data_date,symbol,generation:'g',input_sha256:'i',sha256:sha})}}};
assert.equal(api.validateOriginalChart(answer,symbol,product), answer);
for (const key of ['data_date','symbol','source_generation','input_sha256','formula_sha256','engine_sha256']) {
 const bad=structuredClone(answer); bad[key]='wrong'; assert.throws(()=>api.validateOriginalChart(bad,symbol,product));
}
for(const url of ['https://other.invalid/chart','/api/v4/research/a-share/original-chart/html?date=20261028']) {
 const bad=structuredClone(answer);bad.assets.html.url=url;assert.throws(()=>api.validateOriginalChart(bad,symbol,product));
}
const missing=structuredClone(answer);missing.status='CANNOT_CONFIRM';assert.throws(()=>api.validateOriginalChart(missing,symbol,product));
"""
    result = subprocess.run([
        "/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
        "-e", script, str(root / "research-panel/numeric283-panel.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
