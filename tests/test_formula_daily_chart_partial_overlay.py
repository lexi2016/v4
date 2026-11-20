import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINDING = ROOT / 'docs/handoffs/formula_groups_daily_completion_20261118/overlays/UI_FORMULA_DAILY_CHART_PARTIAL_BINDING.json'


def test_exact_ui_overlay_accepts_partial_d35c_with_marks_and_both_lines(tmp_path):
    binding = json.loads(BINDING.read_text())
    source = Path(binding['source_path'])
    source_bytes = source.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == binding['source_sha256']
    target = tmp_path / binding['target']
    target.parent.mkdir(parents=True)
    target.write_bytes(source_bytes)
    subprocess.run(['git', 'apply', '--unidiff-zero', str(ROOT / binding['patch_path'])],
        cwd=tmp_path, check=True, capture_output=True, text=True)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == binding['result_sha256']

    node_source = r"""
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {verifiedOriginalMarks} = await import(pathToFileURL(process.env.CHART_MODULE_PATH));
const ref = (path, digit) => ({path, sha256:digit.repeat(64)});
const row = {trade_date:'20261120'};
const chart = {symbol:'000610.SZ', source_date:'2026-11-20', generation:'a'.repeat(64),
  input_sha256:'b'.repeat(64), formula_group_sha256:'c'.repeat(64), price_basis:'QFQ_ASOF_20261120',
  volume_basis:'QFQ_EVENT_VOLUME', numeric_manifest:ref('/products/20261120.json','d'),
  selector:ref('/source/selector.parquet','e'), snapshot:ref('/source/snapshot.json','f'), rows:[row],
  original_marks:{schema:'V4_WORKBENCH_ORIGINAL_D35C_MARKS_V1', status:'PARTIAL_WITH_UNKNOWN',
    formula_sha256:'d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac',
    engine_sha256:'ae4243ec9582055fb6f2ee796978ad20e17f9dee7a56388063cbdbcb56ef0d1c',
    sidecar:ref('/supplements/d35c.json','1'), symbol:'000610.SZ', source_date:'2026-11-20',
    generation:'a'.repeat(64), input_sha256:'b'.repeat(64), formula_group_sha256:'c'.repeat(64),
    price_basis:'QFQ_ASOF_20261120', volume_basis:'QFQ_EVENT_VOLUME',
    numeric_manifest:ref('/products/20261120.json','d'), selector:ref('/source/selector.parquet','e'),
    snapshot:ref('/source/snapshot.json','f'), unresolved_conditions:1,
    marks:[{trade_date:'20261120',id:1,kind:'DRAWICON',payload:'1',styles:[],y:'10'}],
    lines:{'白线':[{trade_date:'20261120',y:'9.5'}],'黄线':[{trade_date:'20261120',y:'9.8'}]}}};
const partial = verifiedOriginalMarks(chart);
assert.equal(partial.status, 'PARTIAL_WITH_UNKNOWN');
assert.equal(partial.marks.length, 1);
assert.equal(partial.lines['白线'].length, 1);
assert.equal(partial.lines['黄线'].length, 1);
chart.original_marks = {...chart.original_marks, status:'READY', unresolved_conditions:0};
assert.equal(verifiedOriginalMarks(chart).status, 'READY');
"""
    env = dict(os.environ, CHART_MODULE_PATH=str(target))
    subprocess.run(['node', '--input-type=module', '-e', node_source], env=env,
        check=True, capture_output=True, text=True)
