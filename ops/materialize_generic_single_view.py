"""Offline single-view adapter over an already verified paired research panel.

The existing panel/daily owner invokes this bounded adapter after paired
completion. It does not fetch data, calculate KB signals, publish pointers,
start a service, or create a second research producer.
"""
from __future__ import annotations

import base64
import ast
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime
import gzip
import hashlib
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from ops import research_panel_qfq as q
from ops import render_original_formula_projection as renderer
from ops.kb_hold_score import SUPPLEMENTAL_REASONS
from infrastructure import research_workbench_host as action_host
from infrastructure.research_workbench_host import (
    ACTION_REBIND_FIELDS, checked_action_rebind_index, checked_action_rebind_stock,
)


FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
CHUNK_ROWS = 512
MAX_CHUNK_DECODED = 8 * 1024 * 1024
MAX_CHUNK_COMPRESSED = 2 * 1024 * 1024
MAX_PROJECTION_DECODED = 64 * 1024 * 1024
MAX_PROJECTION_COMPRESSED = 8 * 1024 * 1024
MAX_HISTORY_SOURCE_DECODED = 32 * 1024 * 1024
MAX_HISTORY_SOURCE_COMPRESSED = 8 * 1024 * 1024
MAX_HTML_BYTES = 16 * 1024 * 1024
MAX_BATCH_SYMBOLS = 64
CODE = re.compile(r'^\d{6}\.(?:SH|SZ|BJ)$')
HK_CODE = re.compile(r'^HK\.\d{5}$')
SHA = re.compile(r'^[a-f0-9]{64}$')
ORIGINAL_FIELDS = ('B1','B2','B3','primary_buy_signal','secondary_buy_signal','sell_signal',
    'user_v1_B1','user_v1_B2','user_v1_B3','user_v1_level1_buy_signal',
    'user_v1_level2_buy_signal','user_v1_sell_signal_daily','user_v1_sell_signal_display_asof')
SHARED_ORIGINAL_FIELDS = ORIGINAL_FIELDS[6:]
CHART_EVENTS = ('kb_b1','kb_b2','kb_b3','kb_violence_k','kb_fanbao','kb_sb1','kb_sb1_detailed',
    'kb_double_gun','kb_nana','kb_rebuild','kb_ready','kb_didi','kb_beidou','kb_needle_20',
    'kb_needle_30','kb_brick_flip_green','kb_macd_gold_cross','kb_macd_dead_cross',
    'kb_white_cross_up','kb_white_cross_down')
HISTORY_FIELDS = (('original_level1','original','user_v1_level1_buy_signal'),
    ('original_level2','original','user_v1_level2_buy_signal'),('original_b1','original','user_v1_B1'),
    ('original_b2','original','user_v1_B2'),('original_b3','original','user_v1_B3'),
    ('kb_b1','kb','kb_b1'),('kb_b2','kb','kb_b2'),('kb_b3','kb','kb_b3'),
    ('kb_violence_k','kb','kb_violence_k'),('kb_fanbao','kb','kb_fanbao'))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def _stat(path):
    value = Path(path).stat()
    return {'device':value.st_dev,'inode':value.st_ino,'size':value.st_size,
            'mtime_ns':value.st_mtime_ns,'ctime_ns':value.st_ctime_ns}


def _checked(ref, *, maximum=None):
    _require(isinstance(ref, dict) and isinstance(ref.get('path'), str)
             and isinstance(ref.get('sha256'), str) and SHA.fullmatch(ref['sha256']), 'GENERIC_REFERENCE_INVALID')
    path = Path(ref['path'])
    _require(path.is_absolute() and not path.is_symlink() and path.resolve(strict=True) == path,
             'GENERIC_REFERENCE_PATH_INVALID')
    if maximum is not None:
        _require(path.stat().st_size <= maximum, 'GENERIC_REFERENCE_TOO_LARGE')
    _require(q.sha(path) == ref['sha256'], 'GENERIC_REFERENCE_SHA_DRIFT')
    return path


def _bounded_gzip(ref, *, maximum, compressed_maximum):
    path = _checked(ref, maximum=compressed_maximum)
    raw = path.read_bytes()
    if 'bytes' in ref:
        _require(len(raw) == ref['bytes'], 'GENERIC_ASSET_COMPRESSED_SIZE_CONFLICT')
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as stream:
        decoded = stream.read(maximum + 1)
    _require(len(decoded) <= maximum, 'GENERIC_ASSET_DECODED_SIZE_LIMIT')
    if 'decoded_bytes' in ref:
        _require(len(decoded) == ref['decoded_bytes'], 'GENERIC_ASSET_DECODED_SIZE_CONFLICT')
    return decoded


def _write_immutable(root, stem, suffix, raw, *, decoded_bytes=None, full_hash=False):
    digest = hashlib.sha256(raw).hexdigest()
    path = root / (stem + '_' + (digest if full_hash else digest[:16]) + suffix)
    if path.exists():
        _require(path.read_bytes() == raw, 'GENERIC_IMMUTABLE_CONFLICT')
    else:
        fd, temporary = tempfile.mkstemp(prefix='.' + stem + '_', suffix='.pending', dir=root)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                _require(path.read_bytes() == raw, 'GENERIC_IMMUTABLE_CONFLICT')
            os.unlink(temporary)
        except BaseException:
            # A partial temporary is not a completed artifact; leave it for
            # evidence. A later restart uses a new temporary path.
            raise
    result = {'path':str(path), 'sha256':digest, 'bytes':len(raw)}
    if decoded_bytes is not None:
        result.update(encoding='gzip', decoded_bytes=decoded_bytes)
    return result


def _packed(root, stem, value):
    raw = _canonical(value)
    _require(0 < len(raw) <= MAX_CHUNK_DECODED, 'GENERIC_CHUNK_DECODED_SIZE_LIMIT')
    compressed = gzip.compress(raw, mtime=0)
    _require(len(compressed) <= MAX_CHUNK_COMPRESSED, 'GENERIC_CHUNK_COMPRESSED_SIZE_LIMIT')
    return _write_immutable(root, stem, '.json.gz', compressed, decoded_bytes=len(raw))


def rebind_action_validator_for_runtime(*, index_ref, output_root):
    """Copy a proven G2 index with only its current validator reference changed."""
    old=json.loads(_checked(index_ref,maximum=8*1024*1024).read_bytes());root=Path(output_root).resolve(strict=True)
    _require(root.is_dir() and root!=Path(index_ref['path']).parent
             and not root.is_relative_to(Path(index_ref['path']).parent),'ACTION_VALIDATOR_OUTPUT_NOT_ISOLATED')
    link=old.get('action_rebind') or {}
    for key in ('producer','validator','consumer'):_checked(link.get(key),maximum=4*1024*1024)
    checked_action_rebind_index(old,require_producer=False)
    validator_path=Path(action_host.__file__).resolve(strict=True)
    validator=_write_immutable(root,'ACTION_REBIND_VALIDATOR','.py',validator_path.read_bytes(),full_hash=True)
    new={**old,'action_rebind':{**link,'validator':validator}}
    before={**old,'action_rebind':{k:v for k,v in link.items() if k!='validator'}}
    after={**new,'action_rebind':{k:v for k,v in new['action_rebind'].items() if k!='validator'}}
    _require(before==after and old.get('symbols')==new.get('symbols'), 'ACTION_VALIDATOR_COPY_CONFLICT')
    checked_action_rebind_index(new)
    _require(q.sha(validator_path)==validator['sha256']==q.sha(validator['path']), 'ACTION_REBIND_VALIDATOR_MOVED')
    new_ref=_write_immutable(root,'G2_VALIDATOR_COMPAT_INDEX','.json',_canonical(new))
    ready=[(symbol,item['binding']) for symbol,item in sorted(old['symbols'].items()) if item.get('status')=='READY']
    proof={'schema':'v4.workbench.action_validator_compatibility.v1','status':'PASS_ISOLATED',
           'old_index':index_ref,'new_index':new_ref,'old_validator':link['validator'],'new_validator':validator,
           'other_index_fields_identical':True,'all_symbol_entries_identical':True,'ready_bindings':len(ready),
           'ready_bindings_sha256':hashlib.sha256(_canonical(ready)).hexdigest(),
           'pair_and_proof_references_identical':True,'historical_PIT':False,**FLAGS}
    return new_ref,_write_immutable(root,'G2_VALIDATOR_COMPAT_PROOF','.json',_canonical(proof))


def materialize_a20_hold_candidate(*, symbol, parent_index_ref, projection_ref, output_root):
    """Bind one saved score/action correction to that symbol's G2 chunks.

    This bounded adapter consumes an already computed, source-gated single-stock
    result; it never computes labels, N, historical returns, or a full panel.
    """
    _require(symbol in {'600000.SH','600519.SH','601318.SH','000001.SZ','600036.SH','000301.SZ',
                        '688981.SH','301686.SZ','920000.BJ','920001.BJ','603281.SH','920187.BJ'},
             'HOLD_CHILD_SYMBOL_OUTSIDE_REVIEW')
    index = json.loads(_checked(parent_index_ref, maximum=8*1024*1024).read_bytes())
    _require(index.get('candidate_generation') == 'bfd455c86915918360d9f15c907b72e435b9e46cd8f931db3d6b8f6f7d67ab0b',
             'HOLD_CHILD_PARENT_GENERATION_CONFLICT')
    reuse = checked_action_rebind_index(index)
    wrapper_ref = index['symbols'][symbol]['binding']
    wrapper = json.loads(_checked(wrapper_ref, maximum=4*1024*1024).read_bytes())
    stock, delta = checked_action_rebind_stock(index, reuse, symbol, wrapper)
    projected = json.loads(_bounded_gzip(projection_ref, maximum=16*1024*1024, compressed_maximum=2*1024*1024))
    _require(projected.get('schema') == 'v4.research.single_a20_score_action_projection.v1'
             and projected.get('symbol') == symbol and projected.get('parent_binding_sha256') == wrapper_ref['sha256']
             and projected.get('origin_binding_sha256') == wrapper['origin_binding']['sha256']
             and projected.get('projection_sha256') == stock['chart']['projection']['sha256']
             and projected.get('action_patch_sha256') == (wrapper.get('action_patch') or {}).get('sha256')
             and projected.get('action_contract_sha256') == stock['action_contract_sha256']
             and projected.get('n_rule_sha256') == stock['n_rule_sha256']
             and projected.get('n_helper_sha256') == stock['n_helper_sha256']
             and projected.get('action_engine_sha256') == reuse['summary']['action_authority']['sha256']
             and projected.get('row_count') == stock['rows']
             and projected.get('historical_PIT') is False and all(projected.get(k) is v for k,v in FLAGS.items()),
             'HOLD_CHILD_SOURCE_CONFLICT')
    rows = projected['rows']
    _require(len(rows) == stock['rows'] and projected['target'] == rows[-1]
             and rows[-1]['trade_date'] == 20261030
             and rows[-1]['hold_score']['kb_hold_j_not_dead'] in (True,False)
             and rows[-1]['hold_score']['kb_hold_j_not_dead_reason'] is None
             and (symbol!='600000.SH' or rows[-1]['hold_score']['kb_hold_score']==4),
             'HOLD_CHILD_TARGET_CONFLICT')
    patch = (json.loads(_bounded_gzip(wrapper['action_patch'], maximum=8*1024*1024, compressed_maximum=2*1024*1024))
             if delta['affected_rows'] else {'field_names':list(ACTION_REBIND_FIELDS),'rows':[]})
    _require(patch.get('field_names') == list(ACTION_REBIND_FIELDS) and len(patch['rows']) == delta['affected_rows'],
             'HOLD_CHILD_PATCH_CONFLICT')
    patch_by_date = {r[0]: (r[1], r[2]) for r in patch['rows']}
    _require(len(patch_by_date) == len(patch['rows']), 'HOLD_CHILD_PATCH_DUPLICATE')
    score_contract=projected.get('score_contract')
    contract_path=_checked(score_contract,maximum=1024*1024)
    contract=json.loads(contract_path.read_bytes())
    _require(contract.get('schema')=='a_share_kb_hold_score_v1' and contract.get('user_rule_decision',{}).get('date')=='2026-11-02'
             and contract.get('historical_PIT',False) is False and all(contract.get(k) is v for k,v in FLAGS.items()),
             'HOLD_CHILD_SCORE_CONTRACT_CONFLICT')
    identity = {'symbol':symbol, 'source_date':index['source_date'],
                'parent_index_sha256':parent_index_ref['sha256'], 'parent_generation':index['candidate_generation'],
                'parent_binding_sha256':wrapper_ref['sha256'], 'origin_binding_sha256':wrapper['origin_binding']['sha256'],
                'origin_chart_sha256':stock['chart']['projection']['sha256'],
                'source_score_projection_sha256':projection_ref['sha256'],
                'score_contract_sha256':score_contract['sha256'], 'score_engine_sha256':projected['score_engine_sha256'],
                'score_caller_sha256':projected['score_caller_sha256'],
                'action_engine_sha256':projected['action_engine_sha256']}
    generation = hashlib.sha256(_canonical(identity)).hexdigest()
    root = Path(output_root).resolve(strict=True)
    score_contract_copy=_write_immutable(root,'HOLD_SCORE_CONTRACT','.json',contract_path.read_bytes(),full_hash=True)
    _require(score_contract_copy['sha256']==score_contract['sha256'],'HOLD_CHILD_SCORE_CONTRACT_MOVED')
    names = stock['field_names']; score_fields = stock['field_groups']['hold_score']; action_fields = stock['field_groups']['action']
    allowed_score = {'kb_hold_k','kb_hold_d','kb_hold_j_not_dead','kb_hold_j_not_dead_reason',
                     'kb_hold_volume_ok','kb_hold_volume_ok_reason',
                     'kb_hold_score','kb_hold_score_min','kb_hold_score_max','kb_hold_score_status'}
    chunks, offset, matched_patch = [], 0, set()
    for ref in stock['chunks']:
        chunk = json.loads(_bounded_gzip(ref, maximum=MAX_CHUNK_DECODED, compressed_maximum=MAX_CHUNK_COMPRESSED))
        _require(chunk.get('symbol') == symbol and chunk.get('candidate_generation') == stock['candidate_generation']
                 and len(chunk.get('rows',[])) == ref['row_count'], 'HOLD_CHILD_SOURCE_CHUNK_CONFLICT')
        for item in chunk['rows']:
            new = rows[offset]; offset += 1
            _require(item[0] == new['trade_date'] and set(new['hold_score']) == set(score_fields)
                     and set(new['action']) == set(action_fields), 'HOLD_CHILD_ROW_CONFLICT')
            prior = dict(zip(names, item[1])); oldnew = patch_by_date.get(item[0])
            if oldnew:
                _require([prior[k] for k in ACTION_REBIND_FIELDS] == oldnew[0], 'HOLD_CHILD_OLD_ACTION_CONFLICT')
                prior.update(zip(ACTION_REBIND_FIELDS, oldnew[1])); matched_patch.add(item[0])
            _require(all(prior[k] == new['hold_score'][k] for k in set(score_fields)-allowed_score),
                     'HOLD_CHILD_UNRELATED_SCORE_CONFLICT')
            for k in score_fields:prior[k] = new['hold_score'][k]
            for k in action_fields:prior[k] = new['action'][k]
            item[1] = [prior[k] for k in names]
        chunk['candidate_generation'] = generation
        child = _packed(root, symbol.replace('.','_')+'_HOLD_CHILD_CHUNK', chunk)
        child.update(first_date=ref['first_date'],last_date=ref['last_date'],row_count=ref['row_count'])
        chunks.append(child)
    _require(offset == len(rows) and matched_patch == set(patch_by_date), 'HOLD_CHILD_ROW_COVERAGE_CONFLICT')
    value = {'schema':'v4.workbench.a20_hold_score_candidate.v1', 'identity':identity,
             'candidate_generation':generation, 'parent_index':parent_index_ref, 'parent_binding':wrapper_ref,
             'origin_binding':wrapper['origin_binding'], 'score_projection':projection_ref,'score_contract':score_contract_copy,
             'rows':offset, 'chunks':chunks, 'unchanged_scope':'ALL_OTHER_FIELDS_DIAGNOSTICS_ORIGINALS_DATES',
             'changed_fields':projected['changed_fields'], 'bound_j_unavailable_rows':projected['bound_j_unavailable_rows'],
             'target':projected['target'], 'historical_PIT':False, **FLAGS}
    return _write_immutable(root, symbol.replace('.','_')+'_HOLD_CHILD_BINDING', '.json', _canonical(value))


def _plain(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _same(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def _groups():
    supplemental = set(SUPPLEMENTAL_REASONS)
    return {
        'kb':sorted(q.KB_FIELDS),
        'hold_score':sorted(q.SINGLE_FEEDBACK_FIELDS - supplemental),
        'supplemental':sorted(supplemental),
        'action':sorted(q.SINGLE_ACTION_FIELDS),
        'yidong':sorted(q.SINGLE_YIDONG_FIELDS),
        'confirmed_kb_fields':sorted(q.SINGLE_GAP_FIELDS),
    }


def _fields():
    groups = _groups()
    fields = [name for group in groups.values() for name in group]
    _require(len(fields) == len(set(fields)) == 107, 'GENERIC_FIELD_INVENTORY_CONFLICT')
    return fields


def _projection_rows(projection, symbol, source_date, generation, input_sha, selector_rows):
    result = projection.get('formula_result', {})
    source = projection.get('source', {})
    rows = result.get('rows')
    _require(projection.get('symbol') == symbol and str(projection.get('data_date')) == source_date
             and isinstance(source.get('generation_id'),str) and SHA.fullmatch(source['generation_id'])
             and isinstance(source.get('source_input_sha256'),str) and SHA.fullmatch(source['source_input_sha256'])
             and source.get('price_basis') == 'QFQ_ASOF' and source.get('volume_basis') == 'QFQ_EVENT_VOLUME'
             and projection.get('historical_PIT') is False
             and all(projection.get(k) is v for k,v in FLAGS.items())
             and result.get('formula_sha256') == renderer.FORMULA_SHA and result.get('mode') == 'prefix'
             and result.get('field_count') == 51 and result.get('drawing_count') == 22
             and not projection.get('unsupported_drawings') and isinstance(rows, list), 'GENERIC_ORIGINAL_CHART_IDENTITY_CONFLICT')
    _require(len(rows)==len(selector_rows),'GENERIC_ORIGINAL_LENGTH_CONFLICT')
    inventory = projection.get('inventory', {})
    lineage = projection.get('lineage', {})
    _require(lineage.get('engine', {}).get('sha256') == renderer.ENGINE_SHA
             and lineage.get('formula', {}).get('sha256') == renderer.FORMULA_SHA,
             'GENERIC_ORIGINAL_LINEAGE_CONFLICT')
    assignments = [x.get('name') for x in inventory.get('assignments', [])]
    definitions = inventory.get('drawings', [])
    _require(len(assignments) == 51 and len(set(assignments)) == 51 and len(definitions) == 22,
             'GENERIC_ORIGINAL_INVENTORY_CONFLICT')
    for chart, selected in zip(rows, selector_rows):
        _require(str(chart.get('trade_date')) == str(selected['trade_date'])
                 and str(chart.get('ohlcv', {}).get('trade_date')) == str(selected['trade_date']),
                 'GENERIC_ORIGINAL_DATE_CONFLICT')
        _require(set(chart.get('values', {})) == set(assignments)
                 and len(chart.get('drawings', [])) == 22, 'GENERIC_ORIGINAL_ROW_CONFLICT')
        for key in ('open','high','low','close','vol'):
            raw = selected['volume' if key == 'vol' else key]
            try:
                valid = math.isfinite(float(raw)) and float(raw) == float(chart['ohlcv'][key])
            except (ValueError, TypeError, KeyError, OverflowError):
                valid = False
            _require(valid, 'GENERIC_ORIGINAL_OHLCV_CONFLICT:' + key)
        for drawing, definition in zip(chart['drawings'], definitions):
            _require(all(drawing.get(k) == definition.get(k) for k in ('id','kind','styles'))
                     and drawing.get('kind') in ('DRAWTEXT','DRAWICON')
                     and (drawing['kind'] != 'DRAWICON' or str(drawing.get('payload')) in ('1','2')),
                     'GENERIC_ORIGINAL_DRAWING_CONFLICT')
    return rows


def _safe_chart_html(projection, lineage):
    raw = renderer.pinned(renderer.OWNER_RENDERER)
    html = renderer.chart_html(raw, projection, lineage, compress_payload=True)
    match = re.search(r"const projectionGzip='([A-Za-z0-9+/=]+)'", html)
    _require(match is not None, 'GENERIC_ORIGINAL_CHART_ADAPTER_MISSING')
    compressed = base64.b64decode(match.group(1), validate=True)
    _require(len(compressed) <= MAX_PROJECTION_COMPRESSED, 'GENERIC_CHART_COMPRESSED_SIZE_LIMIT')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode='rb') as stream:
        decoded = stream.read(MAX_PROJECTION_DECODED + 1)
    _require(len(decoded) <= MAX_PROJECTION_DECODED, 'GENERIC_CHART_DECODED_SIZE_LIMIT')
    previous = 'return JSON.parse(await new Response(stream).text());'
    replacement = (
        "const r=stream.getReader(),parts=[];let n=0;try{for(;;){const v=await r.read();"
        "if(v.done)break;n+=v.value.byteLength;if(n>" + str(len(decoded)) + "){await r.cancel();"
        "throw Error('ORIGINAL_CHART_SIZE_CONFLICT')}parts.push(v.value)}}finally{r.releaseLock()}"
        "if(n!==" + str(len(decoded)) + ")throw Error('ORIGINAL_CHART_SIZE_CONFLICT');"
        "const a=new Uint8Array(n);let i=0;for(const p of parts){a.set(p,i);i+=p.length}"
        "return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(a));"
    )
    _require(html.count(previous) == 1, 'GENERIC_ORIGINAL_CHART_LOADER_CONFLICT')
    html = html.replace(previous, replacement, 1).encode()
    _require(len(html) <= MAX_HTML_BYTES, 'GENERIC_CHART_HTML_SIZE_LIMIT')
    return html


def make_original_projection(selector_rows, identity, engine_config_ref):
    """Run the existing pinned 51/22 engine offline for an actually missing chart."""
    config = json.loads(_checked(engine_config_ref, maximum=1024*1024).read_bytes())
    _require(config['engine']['sha256'] == renderer.ENGINE_SHA
             and config['formula']['sha256'] == renderer.FORMULA_SHA, 'GENERIC_ORIGINAL_ENGINE_IDENTITY_CONFLICT')
    _checked(config['formula'], maximum=1024*1024)
    from ops.research_panel_daily_product import module
    engine = module(config['engine'], 'generic_bound_original_engine')
    inventory = engine.inventory()
    symbol = identity['symbol']
    bars = [{'date':str(row['trade_date']), **{key:row[key] for key in ('open','high','low','close')},
             'volume':row['volume']} for row in selector_rows]
    source = {'generation_id':identity['candidate_generation'], 'source_input_sha256':identity['candidate_input_sha256'],
              'price_basis':'QFQ_ASOF', 'volume_basis':'QFQ_EVENT_VOLUME',
              'adjustment_convention':identity['adjustment_convention']}
    bound = {'allowed_symbols':(symbol,), 'sample':{'symbol':symbol,'bars':bars},
             'source':source, 'item':{'source_cache':{'bars_sha256':q.canonical_sha(bars),'rows':len(bars)},
             'product_row_ref':{'kind':'PAIRED_CANDIDATE_SYMBOL_HISTORY','symbol':symbol,
                 'generation_id':identity['candidate_generation'],'selector_sha256':identity['pair_sha256']['selector'],
                 'paired_receipt':identity['paired_receipt']}}}
    projection = renderer.project(engine, inventory, bound, symbol)
    projection['data_date'] = identity['source_date'].replace('-', '')
    projection['candidate_generation'] = identity['candidate_generation']
    projection['lineage'] = {'paired_receipt':identity['paired_receipt'], 'formula':config['formula'],
                             'engine':config['engine'], 'numeric_manifest':identity['numeric_manifest']}
    return projection


def _retained_history(ref, identity, selector_rows, producer_sha, relocation_ref=None):
    """Reuse old statistics only when their exact inputs still match the pair."""
    history=json.loads(_bounded_gzip(ref,maximum=8*1024*1024,compressed_maximum=2*1024*1024))
    symbol=identity['symbol'];source_date=identity['source_date']
    _require(history.get('schema_version')=='v4.a_share.event_cases.single_research.v1'
             and history.get('symbol')==symbol and history.get('data_date')==source_date.replace('-','')
             and history.get('source_generation')==identity['generation']
             and history.get('input_sha256')==identity['input_sha256']
             and history.get('numeric_manifest')==identity['numeric_manifest']
             and history.get('producer_sha256')==producer_sha and isinstance(producer_sha,str) and SHA.fullmatch(producer_sha)
             and history.get('historical_PIT') is False and all(history.get(k) is v for k,v in FLAGS.items()),
             'GENERIC_HISTORY_SOURCE_CONFLICT')
    candidate=json.loads(_checked(history['source_candidate'],maximum=16*1024*1024).read_bytes())
    old_binding=json.loads(_checked(candidate['binding'],maximum=4*1024*1024).read_bytes())
    old_generation=history.get('source_candidate_generation')
    _require(isinstance(old_generation,str) and SHA.fullmatch(old_generation)
             and candidate.get('candidate_generation')==old_binding.get('candidate_generation')==old_generation
             and old_binding.get('symbol')==symbol
             and candidate.get('outputs',{}).get('selector',{}).get('sha256')==history['source_selector']['sha256']
             and old_binding.get('assets',{}).get('kb',{}).get('sha256')==history['source_view']['sha256'],
             'GENERIC_HISTORY_CANDIDATE_CONFLICT')
    candidate_identity=old_binding.get('candidate_identity',{})
    _require(candidate_identity.get('formula_sha256')==renderer.FORMULA_SHA
             and candidate_identity.get('formula_engine_sha256')==renderer.ENGINE_SHA,
             'GENERIC_HISTORY_FORMULA_CONFLICT')
    old_view=json.loads(_bounded_gzip(history['source_view'],maximum=32*1024*1024,compressed_maximum=8*1024*1024))
    _require(old_view.get('symbol')==symbol and old_view.get('candidate_generation')==old_generation
             and old_view.get('source_generation')==identity['generation']
             and old_view.get('source_input_sha256')==identity['input_sha256']
             and old_view.get('authority_sha256')==identity['kb_authority_sha256']
             and old_view.get('field_contract_sha256')==identity['kb_field_contract_sha256']
             and old_view.get('historical_PIT') is False and all(old_view.get(k) is v for k,v in FLAGS.items()),
             'GENERIC_HISTORY_RULE_CONFLICT')
    calendar=json.loads(_checked(history['market_calendar'],maximum=4*1024*1024).read_bytes())
    _require(calendar.get('schema')=='v4.single_stock_same_market_calendar.v1'
             and calendar.get('exchange')==symbol.rsplit('.',1)[1] and calendar.get('asof')==source_date
             and calendar.get('source_panel_sha256')==identity['baseline_panel_sha256']['selector'],
             'GENERIC_HISTORY_CALENDAR_CONFLICT')
    _require(history.get('history_source_relocation')==relocation_ref,'GENERIC_HISTORY_RELOCATION_CONFLICT')
    if relocation_ref is not None:
        from infrastructure.research_workbench_host import checked_relocated_parquet
        selector_source=pa.BufferReader(checked_relocated_parquet(history['source_selector'],relocation_ref))
    else:selector_source=_checked(history['source_selector'])
    old_selector=pq.read_table(selector_source,
        columns=['ts_code','trade_date','open','high','low','close','volume']).sort_by([('trade_date','ascending')]).to_pylist()
    old_rows=old_view.get('rows');_require(isinstance(old_rows,list) and len(old_rows)==len(old_selector)==len(selector_rows),
                                         'GENERIC_HISTORY_LENGTH_CONFLICT')
    for old,prior,new in zip(old_rows,old_selector,selector_rows):
        _require(prior['ts_code']==symbol and str(prior['trade_date'])==str(old.get('trade_date'))==str(new['trade_date'])
                 and all(_same(prior[k],new[k]) for k in ('open','high','low','close','volume')),
                 'GENERIC_HISTORY_OHLCV_CONFLICT')
        for _,namespace,field in HISTORY_FIELDS:
            _require(namespace in old and field in old[namespace] and _same(old[namespace][field],new[field]),
                     'GENERIC_HISTORY_LABEL_CONFLICT:'+field)
    groups=history.get('statistics',{}).get('groups',[])
    _require(isinstance(groups,list) and {g.get('group_id') for g in groups}=={g[0] for g in HISTORY_FIELDS},
             'GENERIC_HISTORY_GROUP_CONFLICT')
    for name,namespace,field in HISTORY_FIELDS:
        group=next(g for g in groups if g['group_id']==name)
        rule=hashlib.sha256(_canonical({'namespace':namespace,'field':field,'source_view_sha256':history['source_view']['sha256']})).hexdigest()
        source=group.get('source_identity',{})
        _require(group.get('identity_status')=='BOUND' and group.get('rule_sha256')==rule
                 and source.get('rule_sha256')==rule and source.get('generation')==identity['generation']
                 and source.get('input')==identity['input_sha256'] and source.get('market')==calendar['exchange']
                 and source.get('formula')==(renderer.FORMULA_SHA if namespace=='original' else identity['kb_field_contract_sha256']),
                 'GENERIC_HISTORY_GROUP_RULE_CONFLICT:'+name)
    return {'status':'READY','asset':ref,'source_candidate_generation':old_generation,
            'calendar_sha256':history['market_calendar']['sha256'],'source_view_sha256':history['source_view']['sha256'],
            'validation':'EXACT_OHLCV_AND_10_LABELS_AND_RULES','candidate_generation':identity['candidate_generation']}


def _retained_company(ref, identity, producer_sha):
    company=json.loads(_bounded_gzip(ref,maximum=8*1024*1024,compressed_maximum=2*1024*1024))
    _require(company.get('schema_version')=='v4.a_share.company_materials.v1'
             and company.get('symbol')==identity['symbol'] and company.get('data_date')==identity['source_date'].replace('-','')
             and company.get('source_generation')==identity['generation'] and company.get('input_sha256')==identity['input_sha256']
             and company.get('numeric_manifest')==identity['numeric_manifest'] and company.get('historical_PIT') is False
             and company.get('producer_sha256')==producer_sha and isinstance(producer_sha,str) and SHA.fullmatch(producer_sha)
             and all(company.get(k) is v for k,v in FLAGS.items()), 'GENERIC_COMPANY_SOURCE_CONFLICT')
    candidate=json.loads(_checked(company['source_candidate'],maximum=16*1024*1024).read_bytes())
    prior=json.loads(_checked(candidate['binding'],maximum=4*1024*1024).read_bytes())
    _require(candidate.get('candidate_generation')==company.get('source_candidate_generation')
             and prior.get('candidate_generation')==company.get('source_candidate_generation') and prior.get('symbol')==identity['symbol']
             and isinstance(company.get('source_candidate_generation'),str)
             and SHA.fullmatch(company['source_candidate_generation']), 'GENERIC_COMPANY_CANDIDATE_CONFLICT')
    _checked(company['received_ref'],maximum=8*1024*1024)
    checks={}
    for key,item in company.get('source_refs',{}).items():
        try:
            _checked(item['file'],maximum=64*1024*1024);checks[key]='VERIFIED'
        except (ValueError,OSError,KeyError,TypeError):checks[key]='UNKNOWN'
    return {'status':'READY','asset':ref,'source_candidate_generation':company['source_candidate_generation'],
            'source_checks':checks}


def _materialize_chart(root, symbol, identity, left, projection, original_projection_ref, rejected_projection):
    _projection_rows(projection,symbol,identity['source_date'].replace('-',''),identity['generation'],identity['input_sha256'],left)
    projection=dict(projection)
    lineage=dict(projection.get('lineage') or {})
    lineage.update(candidate_generation=identity['candidate_generation'],paired_receipt=identity['paired_receipt'],
                   source_generation=identity['generation'],source_input_sha256=identity['input_sha256'])
    if original_projection_ref is not None and rejected_projection is None:
        lineage['source_projection']=original_projection_ref
        lineage['source_projection_original_identity']=dict(projection['source'])
        lineage['source_projection_full_ohlcv_equal']=True
    if rejected_projection is not None:lineage['source_projection_rejected']=rejected_projection
    projection['source']={**projection['source'],'generation_id':identity['candidate_generation'],
                          'source_input_sha256':identity['candidate_input_sha256']}
    projection.update(candidate_generation=identity['candidate_generation'],lineage=lineage)
    raw=_canonical(projection)
    _require(len(raw)<=MAX_PROJECTION_DECODED,'GENERIC_PROJECTION_DECODED_SIZE_LIMIT')
    compressed=gzip.compress(raw,mtime=0)
    _require(len(compressed)<=MAX_PROJECTION_COMPRESSED,'GENERIC_PROJECTION_COMPRESSED_SIZE_LIMIT')
    projection_ref=_write_immutable(root,symbol.replace('.','_')+'_PROJECTION','.json.gz',compressed,decoded_bytes=len(raw))
    projection_ref.update(row_count=len(left),formula_sha256=renderer.FORMULA_SHA)
    html_ref=_write_immutable(root,symbol.replace('.','_')+'_CHART','.html',_safe_chart_html(projection,lineage))
    return {'status':'READY','projection':projection_ref,'html':html_ref}


def build_from_verified_tables(*, symbol, selector, backtest, diagnostics, identity, output_root,
                               original_projection_ref=None, engine_config_ref=None, retained_details=None):
    """Materialize read-only per-day assets from producer-verified paired slices.

    The invoking owner must have verified the paired receipt and both panel
    bytes once and extracted these tables from that exact pair. This routine
    additionally verifies every symbol/date, the 107 persisted fields, OHLCV,
    diagnostics and original chart. It never computes a KB field.
    """
    _require(isinstance(symbol, str) and CODE.fullmatch(symbol), 'GENERIC_SYMBOL_INVALID')
    _require(identity.get('symbol') == symbol and all(SHA.fullmatch(str(identity.get(k,''))) for k in
             ('generation','candidate_generation','input_sha256','candidate_input_sha256')), 'GENERIC_IDENTITY_INVALID')
    for key in ('source_date','observation_date'):
        value = identity.get(key)
        try:
            _require(isinstance(value,str) and datetime.strptime(value,'%Y-%m-%d').strftime('%Y-%m-%d') == value,
                     'GENERIC_DATE_INVALID:' + key)
        except (TypeError, ValueError):
            raise ValueError('GENERIC_DATE_INVALID:' + key) from None
    _require(identity.get('historical_PIT') is False and all(identity.get(k) is v for k,v in FLAGS.items()),
             'GENERIC_SAFETY_IDENTITY_CONFLICT')
    root = Path(output_root).resolve(strict=True)
    _require(root.is_dir(), 'GENERIC_OUTPUT_ROOT_INVALID')
    fields = _fields()
    required = {'ts_code','trade_date','open','high','low','close','zge_white_line','zge_yellow_line',*fields}
    _require(required | {'volume',*ORIGINAL_FIELDS} <= set(selector.column_names), 'GENERIC_SELECTOR_FIELDS_MISSING')
    _require(required | {'vol',*SHARED_ORIGINAL_FIELDS} <= set(backtest.column_names), 'GENERIC_BACKTEST_FIELDS_MISSING')
    _require(0 < selector.num_rows <= 50000 and selector.num_rows == backtest.num_rows == diagnostics.num_rows,
             'GENERIC_PAIRED_LENGTH_CONFLICT')
    left = selector.sort_by([('trade_date','ascending')]).to_pylist()
    right = backtest.sort_by([('trade_date','ascending')]).to_pylist()
    diags = diagnostics.sort_by([('trade_date','ascending')]).to_pylist()
    _require(left and len(left) == len(right) == len(diags), 'GENERIC_PAIRED_LENGTH_CONFLICT')
    previous = 0
    diag_sha = identity['diagnostics_sha256']
    _require(SHA.fullmatch(str(diag_sha)), 'GENERIC_DIAGNOSTICS_IDENTITY_INVALID')
    packed_rows, overlay = [], []
    action_sha, yidong_sha = None, None
    for a,b,d in zip(left,right,diags):
        try:
            date = int(a['trade_date'])
        except (ValueError, TypeError, OverflowError):
            raise ValueError('GENERIC_TRADE_DATE_INVALID') from None
        _require(date > previous and str(date) == str(b['trade_date']) == str(d['trade_date'])
                 and a['ts_code'] == b['ts_code'] == d['ts_code'] == symbol, 'GENERIC_PAIRED_KEY_CONFLICT')
        previous = date
        for name in (*fields,*SHARED_ORIGINAL_FIELDS,'open','high','low','close','zge_white_line','zge_yellow_line'):
            _require(_same(a[name],b[name]), 'GENERIC_PAIRED_FIELD_CONFLICT:' + name)
        _require(_same(a['volume'],b['vol']), 'GENERIC_PAIRED_FIELD_CONFLICT:volume')
        diag = json.loads(d['diagnostics_json'])
        _require(isinstance(diag, dict) and set(diag) == set(q.SINGLE_GAP_DIAGNOSTICS) | {'kb_n_structure'}
                 and isinstance(d['prefix_input_sha256'],str) and SHA.fullmatch(d['prefix_input_sha256']),
                 'GENERIC_DIAGNOSTICS_ROW_CONFLICT')
        n = diag['kb_n_structure']
        _require(isinstance(n,dict) and n.get('rule_sha256') == identity['n_rule_sha256']
                 and n.get('helper_sha256') == identity['n_helper_sha256']
                 and n.get('input_sha256') == identity.get('n_input_sha256',identity['candidate_input_sha256'])
                 and n.get('generation_id') == identity.get('n_generation_id',identity['candidate_generation']),
                 'GENERIC_N_IDENTITY_CONFLICT')
        _require(n.get('state') == ('TREND_UP' if a['kb_hold_trend_up'] is True else a['kb_hold_trend_up_reason']),
                 'GENERIC_N_VALUE_CONFLICT')
        for field, value in (('kb_action_rule_sha256',a['kb_action_rule_sha256']),
                             ('kb_yidong_rule_sha256',a['kb_yidong_rule_sha256'])):
            _require(isinstance(value,str) and SHA.fullmatch(value), 'GENERIC_RULE_SHA_INVALID:' + field)
        action_sha = action_sha or a['kb_action_rule_sha256']
        yidong_sha = yidong_sha or a['kb_yidong_rule_sha256']
        _require(action_sha == a['kb_action_rule_sha256'] and yidong_sha == a['kb_yidong_rule_sha256'],
                 'GENERIC_RULE_SHA_CHANGED_WITHIN_SYMBOL')
        values = [_plain(a[name]) for name in fields]
        originals = [_plain(a[name]) for name in ORIGINAL_FIELDS]
        reused = [_plain(a['zge_white_line']),_plain(a['zge_yellow_line'])]
        packed_rows.append([date,values,originals,diag,reused])
        hits = [name for name in CHART_EVENTS if a[name] is True]
        if hits:
            overlay.append([date,hits])
    _require(str(previous) == identity['source_date'].replace('-',''), 'GENERIC_TARGET_DATE_MISSING')
    history_input = _packed(root,symbol.replace('.','_')+'_HISTORY_INPUT',
        {'schema':'v4.workbench.retained_history_input.v1','symbol':symbol,
         'source_generation':identity['generation'],'source_input_sha256':identity['input_sha256'],
         'candidate_generation':identity['candidate_generation'],'candidate_input_sha256':identity['candidate_input_sha256'],
         'paired_receipt':identity['paired_receipt'],'pair_sha256':identity['pair_sha256'],
         'field_names':[{'group_id':group,'namespace':namespace,'field':field} for group,namespace,field in HISTORY_FIELDS],
         'rows':[[int(row['trade_date']),_plain(row['close']),[_plain(row[field]) for _,_,field in HISTORY_FIELDS]] for row in left],
         'historical_PIT':False,**FLAGS})
    chunks = []
    for offset in range(0,len(packed_rows),CHUNK_ROWS):
        part = packed_rows[offset:offset+CHUNK_ROWS]
        chunk = {'schema':'v4.workbench.generic_single_chunk.v1','symbol':symbol,
                 'candidate_generation':identity['candidate_generation'],'candidate_input_sha256':identity['candidate_input_sha256'],
                 'source_input_sha256':identity['input_sha256'],
                 'rows':part}
        ref = _packed(root,symbol.replace('.','_')+'_CHUNK',chunk)
        ref.update(first_date=part[0][0],last_date=part[-1][0],row_count=len(part))
        chunks.append(ref)
    overlay_ref = _packed(root,symbol.replace('.','_')+'_OVERLAY',
        {'schema':'v4.workbench.generic_single_overlay.v1','symbol':symbol,
         'candidate_generation':identity['candidate_generation'],'rows':overlay})
    chart = {'status':'UNKNOWN','reason':'ORIGINAL_CHART_NOT_MATERIALIZED'}
    projection = None;rejected_projection=None
    if original_projection_ref is not None:
        try:
            projection = json.loads(_bounded_gzip(original_projection_ref, maximum=MAX_PROJECTION_DECODED,
                                                   compressed_maximum=MAX_PROJECTION_COMPRESSED))
            _projection_rows(projection,symbol,identity['source_date'].replace('-',''),identity['generation'],identity['input_sha256'],left)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            rejected_projection={'reference':original_projection_ref,'reason':str(exc)};projection=None
            chart={'status':'UNKNOWN','reason':'ORIGINAL_CHART_REUSE_REJECTED:'+str(exc)}
    can_regenerate=(original_projection_ref is None or rejected_projection is not None and
                    any(rejected_projection['reason'].startswith(reason) for reason in
                        ('GENERIC_ORIGINAL_LENGTH_CONFLICT','GENERIC_ORIGINAL_DATE_CONFLICT','GENERIC_ORIGINAL_OHLCV_CONFLICT')))
    if projection is None and engine_config_ref is not None and can_regenerate:
        try:
            projection = make_original_projection(left, identity, engine_config_ref)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            chart = {'status':'UNKNOWN','reason':'ORIGINAL_CHART_BUILD_FAILED:' + str(exc)}
    if projection is not None:
        try:chart=_materialize_chart(root,symbol,identity,left,projection,original_projection_ref,rejected_projection)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            chart={'status':'UNKNOWN','reason':'ORIGINAL_CHART_VALIDATION_FAILED:'+str(exc)}
    descriptors = []
    for source in q._field_spec()['fields']:
        item = dict(source)
        if item['name'] == 'kb_rebuild':
            item.update(status='LOCAL_FULL_PREFIX_REPAIRED',unknown_reason='少于124根或输入无效时待核')
        descriptors.append(item)
    details={kind:{'status':'UNKNOWN','reason':'NOT_MATERIALIZED'} for kind in ('history','company')}
    prior_ref=(retained_details or {}).get('binding')
    if prior_ref is not None:
        try:
            prior=json.loads(_checked(prior_ref,maximum=4*1024*1024).read_bytes())
            _require(prior.get('symbol')==symbol and prior.get('source_date')==identity['source_date']
                     and prior.get('source_generation')==identity['generation']
                     and prior.get('source_input_sha256')==identity['input_sha256']
                     and prior.get('numeric_manifest')==identity['numeric_manifest']
                     and prior.get('historical_PIT') is False and all(prior.get(k) is v for k,v in FLAGS.items()),
                     'GENERIC_RETAINED_BINDING_CONFLICT')
            producers=prior.get('candidate_identity',{}).get('source_sha256',{})
            for kind,producer,adapter in (('history','ops/bootstrap_stock_event_history.py',_retained_history),
                                          ('company','ops/research_panel_daily_product.py',_retained_company)):
                try:
                    detail_ref=prior.get('assets',{}).get(kind)
                    if detail_ref is None:continue
                    details[kind]=adapter(detail_ref,identity,left,producers.get(producer),prior.get('history_source_relocation')) if kind=='history' else adapter(detail_ref,identity,producers.get(producer))
                    details[kind]['source_binding']=prior_ref
                except (ValueError,OSError,KeyError,TypeError,pa.ArrowException) as exc:
                    details[kind]={'status':'UNKNOWN','reason':str(exc)}
        except (ValueError,OSError,KeyError,TypeError) as exc:
            details={kind:{'status':'UNKNOWN','reason':str(exc)} for kind in ('history','company')}
    record = {'schema':'v4.workbench.generic_single_binding.v1', **identity,
              'symbol':symbol, 'rows':len(left), 'first_date':int(left[0]['trade_date']),
              'last_date':int(left[-1]['trade_date']), 'dates':[int(a['trade_date']) for a in left],
              'field_names':fields,'field_groups':_groups(),'base_fields':descriptors,
              'original_fields':list(ORIGINAL_FIELDS),'chunks':chunks,'overlay':overlay_ref,'history_input':history_input,
              'chart':chart,'details':details,
              'action_contract_sha256':action_sha,'yidong_contract_sha256':yidong_sha}
    payload = _canonical(record)
    return _write_immutable(root,symbol.replace('.','_')+'_BINDING','.json',payload)


def _pair_snapshot(receipt_ref, verified_pair_ref=None):
    """Verify a paired completion once per batch, never once per security."""
    receipt = json.loads(_checked(receipt_ref, maximum=16*1024*1024).read_bytes())
    generation, input_sha = receipt.get('generation_id'), receipt.get('input_sha256')
    _require(receipt.get('status') == 'CANDIDATE_READY'
             and isinstance(generation,str) and SHA.fullmatch(generation)
             and isinstance(input_sha,str) and SHA.fullmatch(input_sha)
             and receipt.get('historical_PIT') is False and all(receipt.get(k) is v for k,v in FLAGS.items()),
             'GENERIC_PAIR_RECEIPT_IDENTITY_CONFLICT')
    _require(set(receipt.get('candidates',{})) == set(receipt.get('candidate_sha256',{})) == {'selector','backtest'},
             'GENERIC_PAIR_ROLE_SET_CONFLICT')
    attestation = None
    if verified_pair_ref is not None:
        attestation = json.loads(_checked(verified_pair_ref, maximum=4*1024*1024).read_bytes())
        _require(attestation.get('schema')=='v4.a_share.paired_candidate_attestation.v1'
                 and attestation.get('status') == 'PASS' and attestation.get('generation_id') == generation
                 and attestation.get('input_sha256') == input_sha
                 and attestation.get('candidate_receipt_sha256') == receipt_ref['sha256']
                 and attestation.get('candidate_receipt')==receipt_ref and attestation.get('historical_PIT') is False
                 and all(attestation.get(k) is v for k,v in FLAGS.items())
                 and set(attestation.get('roles',{})) == {'selector','backtest'}, 'GENERIC_PAIR_ATTESTATION_CONFLICT')
        old=attestation.get('old_arrow_equivalence') or {};admission=attestation.get('lifecycle_admission') or {}
        _require(old.get('status')=='PASS' and old.get('ref')==receipt.get('old_arrow_equivalence')
                 and isinstance(admission.get('status'),str) and admission['status'].endswith('_ADMISSION_PASS')
                 and type(admission.get('count')) is int and admission['count']>0
                 and attestation.get('lifecycle_resolution')==receipt.get('lifecycle_resolution'),
                 'GENERIC_PAIR_ADMISSION_PROOF_MISSING')
        old_proof=json.loads(_checked(old['ref'],maximum=16*1024*1024).read_bytes())
        admission_proof=json.loads(_checked(admission['ref'],maximum=16*1024*1024).read_bytes())
        _require(old_proof.get('status')=='PASS' and old_proof.get('generation_id')==generation
                 and old_proof.get('candidate_sha256')==receipt['candidate_sha256']
                 and set(old_proof.get('roles',{}))=={'selector','backtest'}
                 and admission_proof.get('status')==admission['status'] and admission_proof.get('count')==admission['count']
                 and admission_proof.get('generation_id')==generation and admission_proof.get('input_sha256')==input_sha
                 and admission_proof.get('lifecycle_resolution')==receipt['lifecycle_resolution'],
                 'GENERIC_PAIR_ADMISSION_PROOF_CONFLICT')
    roles = {}
    for role in ('selector','backtest'):
        path = Path(receipt['candidates'][role])
        expected = receipt['candidate_sha256'][role]
        _require(path.is_absolute() and not path.is_symlink() and path.resolve(strict=True) == path
                 and isinstance(expected,str) and SHA.fullmatch(expected), 'GENERIC_PAIR_PATH_CONFLICT:' + role)
        stamp = _stat(path)
        if attestation is None:
            _require(q.sha(path) == expected and _stat(path) == stamp, 'GENERIC_PAIR_SHA_CONFLICT:' + role)
        else:
            proof = attestation['roles'][role]
            _require(proof.get('path') == str(path) and proof.get('sha256') == expected
                     and proof.get('stat') == stamp, 'GENERIC_PAIR_ATTESTATION_ROLE_CONFLICT:' + role)
        parquet = pq.ParquetFile(path)
        if attestation is not None:
            _require(proof.get('rows')==parquet.metadata.num_rows and proof.get('columns')==len(parquet.schema_arrow),
                     'GENERIC_PAIR_ATTESTATION_SHAPE_CONFLICT:' + role)
        metadata = json.loads((parquet.schema_arrow.metadata or {})[b'a_share_qfq_contract_v1'])
        _require(metadata.get('generation_id') == generation and metadata.get('input_sha256') == input_sha
                 and metadata.get('research_scope') == 'ADMITTED_A_SHARE'
                 and metadata.get('asof_date') == receipt['target_date']
                 and metadata.get('historical_PIT') is False
                 and all(metadata.get(k) is v for k,v in FLAGS.items()), 'GENERIC_PAIR_FOOTER_CONFLICT:' + role)
        roles[role] = {'path':path,'sha256':expected,'stat':stamp,'metadata':metadata,'schema':parquet.schema_arrow}
    _require(roles['selector']['metadata'].get('confirmed_gap_sidecars')
             == roles['backtest']['metadata'].get('confirmed_gap_sidecars'), 'GENERIC_PAIR_SIDECAR_MAP_CONFLICT')
    if attestation is not None:
        coverage=attestation.get('sidecar_coverage') or {}; count=len(roles['selector']['metadata'].get('confirmed_gap_sidecars') or {})
        _require(count>0 and coverage.get('count')==count and coverage.get('n_checkpoints')==count,
                 'GENERIC_PAIR_SIDECAR_COVERAGE_CONFLICT')
    return receipt, roles


def _unchanged(roles):
    for role,item in roles.items():
        _require(_stat(item['path']) == item['stat'], 'GENERIC_PAIR_MOVED:' + role)


def _extract_batch(roles, symbols):
    """Scan each role once for a bounded batch; never rescan per selected stock."""
    fields = _fields()
    common = ['ts_code','trade_date','open','high','low','close','zge_white_line','zge_yellow_line',*fields]
    result = {symbol:{} for symbol in symbols}
    for role in ('selector','backtest'):
        columns = list(dict.fromkeys(common + (['volume','name',*ORIGINAL_FIELDS] if role == 'selector' else ['vol',*SHARED_ORIGINAL_FIELDS])))
        _require(set(columns) <= set(roles[role]['schema'].names), 'GENERIC_PAIR_COLUMNS_MISSING:' + role)
        batches = defaultdict(list)
        dataset = ds.dataset(roles[role]['path'],format='parquet')
        scanner = dataset.scanner(columns=columns,filter=ds.field('ts_code').isin(symbols),batch_size=4096)
        for batch in scanner.to_batches():
            codes = batch.column(batch.schema.get_field_index('ts_code'))
            for code in pc.unique(codes).to_pylist():
                if code in result:
                    batches[code].append(batch.filter(pc.equal(codes,code)))
        for symbol in symbols:
            result[symbol][role] = pa.Table.from_batches(batches[symbol]) if batches[symbol] else None
    _unchanged(roles)
    return result


def _n_sidecar_identity(receipt, side_meta, side, symbol):
    """Keep a proven reused N checkpoint's original identity, without resuming it."""
    candidate_generation=receipt['generation_id'];candidate_input=receipt['input_sha256']
    if side_meta.get('materialized_source_candidate_generation') is None:
        return {'n_generation_id':candidate_generation,'n_input_sha256':candidate_input,'n_identity_kind':'CANDIDATE'}
    prior_ref=receipt.get('materialized_reuse_refs',{}).get(symbol)
    descriptor_ref=receipt.get('materialized_reuse_descriptor')
    descriptor=json.loads(_checked(descriptor_ref,maximum=4*1024*1024).read_bytes())
    source_generation=receipt.get('materialized_reuse_source_generation')
    source_input=receipt.get('materialized_reuse_source_input_sha256')
    snapshot=receipt.get('materialized_reuse_source_snapshot_sha256')
    _require(descriptor.get('schema')=='a_share_materialized_reuse_v1' and descriptor.get('stocks',{}).get(symbol)==prior_ref
             and descriptor.get('source_generation')==source_generation and descriptor.get('source_input_sha256')==source_input
             and descriptor.get('snapshot_sha256')==snapshot and descriptor.get('baseline_panel_sha256')==receipt['baseline_panel_sha256']
             and descriptor_ref.get('sha256')==receipt.get('materialized_reuse_descriptor_sha256')
             and side_meta.get('source_generation')==source_generation
             and side_meta.get('materialized_source_input_sha256')==source_input
             and side_meta.get('materialized_source_snapshot_sha256')==snapshot
             and side_meta.get('n_checkpoint_resume_across_generation') is False, 'GENERIC_N_REUSE_DESCRIPTOR_CONFLICT')
    prior=json.loads(_checked(prior_ref,maximum=16*1024*1024).read_bytes())
    prior_identity=prior.get('candidate_identity',{})
    _require(prior.get('candidate_generation')==q.canonical_sha(prior_identity)
             and prior_identity.get('symbol')==symbol and prior_identity.get('source_generation')==source_generation
             and prior_identity.get('source_input_sha256')==source_input
             and prior_identity.get('baseline_panel_sha256')==receipt['baseline_panel_sha256']
             and side_meta.get('materialized_source_candidate_generation')==prior['candidate_generation'],
             'GENERIC_N_REUSE_CANDIDATE_CONFLICT')
    old_side=pq.read_table(_checked(prior['confirmed_gap']['diagnostics']))
    _require(side.equals(old_side,check_metadata=False),'GENERIC_N_REUSE_SIDECAR_ROWS_CONFLICT')
    checkpoint_ref=receipt.get('n_structure_checkpoints',{}).get(symbol) or {}
    original_ref=prior.get('n_structure',{}).get('checkpoint') or {}
    _require(checkpoint_ref.get('path')==original_ref.get('path') and checkpoint_ref.get('sha256')==original_ref.get('sha256')
             and checkpoint_ref.get('source_generation')==source_generation
             and checkpoint_ref.get('resume_across_generation') is False, 'GENERIC_N_REUSE_CHECKPOINT_CONFLICT')
    checkpoint=json.loads(_checked(checkpoint_ref,maximum=8*1024*1024).read_bytes());n=checkpoint.get('identity',{})
    _require(checkpoint.get('symbol')==symbol and checkpoint.get('history_bar_count')==side.num_rows
             and n.get('generation_id')==source_generation and n.get('input_sha256')==source_input
             and n.get('rule_sha256')==side_meta.get('n_structure_contract_sha256')
             and n.get('helper_sha256')==side_meta.get('n_structure_helper_sha256')
             and n.get('price_basis')=='QFQ_ASOF' and n.get('calendar_sha256') is None
             and n.get('price_basis_sha256') is None, 'GENERIC_N_REUSE_CHECKPOINT_CONFLICT')
    return {'n_generation_id':source_generation,'n_input_sha256':source_input,'n_identity_kind':'MATERIALIZED_REUSE',
            'n_reuse_candidate':prior_ref,'n_reuse_checkpoint':checkpoint_ref}


def materialize_verified_pair(*, paired_receipt_ref, numeric_manifest_ref, symbols, output_root,
                              observation_date, verified_pair_ref=None, original_projections=None,
                              engine_config_ref=None, retained_details=None):
    """Offline completion adapter; accepts one bounded batch and writes no pointer.

    The caller supplies a freshly verified pair attestation so one already
    completed full-file SHA check is reused. Missing stocks or charts remain
    explicit UNKNOWN.
    """
    symbols = list(dict.fromkeys(symbols))
    _require(verified_pair_ref is not None,'GENERIC_PAIR_ATTESTATION_REQUIRED')
    _require(0 < len(symbols) <= MAX_BATCH_SYMBOLS and all(isinstance(x,str) and CODE.fullmatch(x) for x in symbols),
             'GENERIC_BATCH_SYMBOLS_INVALID')
    root = Path(output_root).resolve(strict=True)
    _require(root.is_dir(), 'GENERIC_OUTPUT_ROOT_INVALID')
    producer_path=Path(__file__).resolve(strict=True)
    producer_ref=_write_immutable(root,'PROJECTION_PRODUCER','.py',producer_path.read_bytes(),full_hash=True)
    producer_ref.update(source_path=str(producer_path),source_sha256=producer_ref['sha256'])
    _require(q.sha(producer_path)==producer_ref['sha256'],'GENERIC_PROJECTION_PRODUCER_MOVED')
    receipt, roles = _pair_snapshot(paired_receipt_ref, verified_pair_ref)
    generation, input_sha = receipt['generation_id'], receipt['input_sha256']
    numeric = json.loads(_checked(numeric_manifest_ref, maximum=8*1024*1024).read_bytes())
    source_generation, source_input = numeric.get('source_generation'), numeric.get('input_sha256')
    _require(isinstance(source_generation,str) and SHA.fullmatch(source_generation)
             and isinstance(source_input,str) and SHA.fullmatch(source_input)
             and str(numeric.get('data_date'))==str(receipt['target_date'])
             and numeric.get('status') in {'READY','PARTIAL_WITH_ROWS'}
             and all(numeric.get(k) is v for k,v in FLAGS.items()), 'GENERIC_NUMERIC_MANIFEST_CONFLICT')
    if source_generation != generation or source_input != input_sha:
        source_binding = receipt.get('kb_initial_upgrade') or {}
        _require(source_binding.get('source_generation_id') == source_generation
                 and receipt.get('materialized_reuse_source_input_sha256') == source_input
                 and source_binding.get('baseline_panel_sha256') == receipt.get('baseline_panel_sha256')
                 and set(receipt.get('baseline_panel_sha256',{})) == {'selector','backtest'}
                 and all(isinstance(v,str) and SHA.fullmatch(v) for v in receipt['baseline_panel_sha256'].values()),
                 'GENERIC_BASELINE_LINEAGE_CONFLICT')
    source_date = datetime.strptime(str(receipt['target_date']),'%Y%m%d').strftime('%Y-%m-%d')
    slices = _extract_batch(roles,symbols)
    references = original_projections or {}
    results = {}
    for symbol in symbols:
        pair = slices[symbol]
        if pair['selector'] is None or pair['backtest'] is None:
            results[symbol] = {'status':'UNKNOWN','reason':'PAIRED_SYMBOL_NOT_PRESENT'}
            continue
        sidecar_ref = roles['selector']['metadata']['confirmed_gap_sidecars'].get(symbol)
        if not sidecar_ref:
            results[symbol] = {'status':'UNKNOWN','reason':'DIAGNOSTICS_NOT_BOUND'}
            continue
        try:
            path = _checked(sidecar_ref)
            side = pq.read_table(path)
            side_meta = json.loads((side.schema.metadata or {})[b'v4.a_share.kb_gap_diagnostics.v1'])
            _require(side_meta.get('symbol') == symbol and side_meta.get('generation_id') == generation
                     and side_meta.get('source_input_sha256') == input_sha
                     and side_meta.get('n_structure_enabled') is True
                     and set(side_meta.get('diagnostic_keys',[])) == set(q.SINGLE_GAP_DIAGNOSTICS) | {'kb_n_structure'}
                     and all(side_meta.get(k) is v for k,v in FLAGS.items()), 'GENERIC_SIDECAR_METADATA_CONFLICT')
            n_identity=_n_sidecar_identity(receipt,side_meta,side,symbol)
            name_values = [x for x in pair['selector']['name'].to_pylist() if isinstance(x,str) and x.strip()]
            identity = dict(symbol=symbol,name=name_values[-1].strip() if name_values else symbol,
                source_date=source_date,observation_date=observation_date,generation=source_generation,
                candidate_generation=generation,input_sha256=source_input,candidate_input_sha256=input_sha,numeric_manifest=numeric_manifest_ref,
                paired_receipt=paired_receipt_ref,pair_sha256={role:roles[role]['sha256'] for role in roles},
                baseline_panel_sha256=receipt.get('baseline_panel_sha256'),kb_authority_sha256=receipt.get('kb_authority_sha256'),
                kb_field_contract_sha256=receipt.get('kb_field_contract_sha256'),
                diagnostics_sha256=sidecar_ref['sha256'],
                n_rule_sha256=side_meta['n_structure_contract_sha256'],
                n_helper_sha256=side_meta['n_structure_helper_sha256'],
                adjustment_convention=receipt.get('convention','BOUND_ORIGINAL_OWNER_QFQ'),
                historical_PIT=False,**n_identity,**FLAGS)
            ref = build_from_verified_tables(symbol=symbol,selector=pair['selector'],backtest=pair['backtest'],
                diagnostics=side,identity=identity,output_root=root,
                original_projection_ref=references.get(symbol),engine_config_ref=engine_config_ref,
                retained_details=(retained_details or {}).get(symbol))
            results[symbol] = {'status':'READY','binding':ref}
        except (ValueError,OSError,KeyError,TypeError,pa.ArrowException) as exc:
            results[symbol] = {'status':'UNKNOWN','reason':str(exc)}
    _unchanged(roles)
    _require(q.sha(producer_path)==q.sha(producer_ref['path'])==producer_ref['sha256'],
             'GENERIC_PROJECTION_PRODUCER_MOVED')
    index = {'schema':'v4.workbench.generic_single_index.v1','source_date':source_date,
             'observation_date':observation_date,'source_generation':source_generation,'input_sha256':source_input,
             'candidate_generation':generation,'candidate_input_sha256':input_sha,'numeric_manifest':numeric_manifest_ref,
             'paired_receipt':paired_receipt_ref,'pair_sha256':{role:roles[role]['sha256'] for role in roles},
             'projection_producer':producer_ref,'verified_pair':verified_pair_ref,
             'symbols':results,'historical_PIT':False,**FLAGS}
    return _write_immutable(root,'GENERIC_SINGLE_INDEX','.json',_canonical(index)), results


def bind_retained_pair_history(*, index_ref, history_refs, history_producer_ref, output_root):
    """Attach completed owner shards by identity only; never rescan panel data."""
    index=json.loads(_checked(index_ref,maximum=8*1024*1024).read_bytes())
    _require(index.get('schema')=='v4.workbench.generic_single_index.v1'
             and index.get('historical_PIT') is False and all(index.get(k) is v for k,v in FLAGS.items())
             and isinstance(index.get('symbols'),dict) and index.get('verified_pair'), 'GENERIC_HISTORY_INDEX_CONFLICT')
    _checked(index['verified_pair'],maximum=4*1024*1024)
    owner_path=_checked(history_producer_ref,maximum=2*1024*1024)
    root=Path(output_root).resolve(strict=True);_require(root.is_dir(),'GENERIC_OUTPUT_ROOT_INVALID')
    owner_copy=_write_immutable(root,'HISTORY_OWNER','.py',owner_path.read_bytes(),full_hash=True)
    owner_copy.update(source_path=str(owner_path),source_sha256=history_producer_ref['sha256'])
    _require(owner_copy['sha256']==history_producer_ref['sha256'],'GENERIC_HISTORY_OWNER_MOVED')
    outcomes={}
    for symbol,shard_ref in history_refs.items():
        try:
            selected=index['symbols'][symbol]
            _require(selected.get('status')=='READY','GENERIC_HISTORY_BINDING_MISSING')
            prior_ref=selected['binding'];binding=json.loads(_checked(prior_ref,maximum=4*1024*1024).read_bytes())
            if shard_ref.get('encoding')=='gzip':
                _require(type(shard_ref.get('bytes')) is int and 0<shard_ref['bytes']<=MAX_HISTORY_SOURCE_COMPRESSED
                         and type(shard_ref.get('decoded_bytes')) is int and 0<shard_ref['decoded_bytes']<=MAX_HISTORY_SOURCE_DECODED
                         and isinstance(shard_ref.get('decoded_sha256'),str) and SHA.fullmatch(shard_ref['decoded_sha256']),
                         'GENERIC_HISTORY_GZIP_REFERENCE_INVALID')
                try:
                    raw=_bounded_gzip(shard_ref,maximum=MAX_HISTORY_SOURCE_DECODED,
                                      compressed_maximum=MAX_HISTORY_SOURCE_COMPRESSED)
                except (OSError,EOFError,zlib.error) as exc:
                    raise ValueError('GENERIC_HISTORY_GZIP_INVALID') from exc
                _require(hashlib.sha256(raw).hexdigest()==shard_ref['decoded_sha256'],
                         'GENERIC_HISTORY_DECODED_SHA_CONFLICT')
            else:
                _require(shard_ref.get('encoding') is None,'GENERIC_HISTORY_ENCODING_UNSUPPORTED')
                raw=_checked(shard_ref,maximum=8*1024*1024).read_bytes()
            shard=json.loads(raw)
            expected={'symbol':symbol,'data_date':index['source_date'].replace('-',''),
                'observation_date':index['observation_date'],'source_generation':index['source_generation'],
                'input_sha256':index['input_sha256'],'source_candidate_generation':index['candidate_generation'],
                'candidate_input_sha256':index['candidate_input_sha256'],'numeric_manifest':index['numeric_manifest'],
                'paired_receipt':index['paired_receipt'],'verified_pair':index['verified_pair'],
                'projection_index':index_ref,'history_input':binding['history_input'],
                'producer_sha256':history_producer_ref['sha256']}
            source_binding=shard.get('projection_binding')
            _require(isinstance(source_binding,dict) and source_binding.get('path')==prior_ref['path']
                     and source_binding.get('sha256')==prior_ref['sha256'], 'GENERIC_HISTORY_SOURCE_BINDING_CONFLICT')
            _checked(source_binding,maximum=4*1024*1024)
            _require(shard.get('schema_version')=='v4.a_share.event_cases.paired_research.v1'
                     and all(shard.get(k)==v for k,v in expected.items()) and shard.get('historical_PIT') is False
                     and all(shard.get(k) is v for k,v in FLAGS.items()), 'GENERIC_PAIRED_HISTORY_CONFLICT')
            calendar=json.loads(_checked(shard['market_calendar'],maximum=4*1024*1024).read_bytes())
            receipt=json.loads(_checked(index['paired_receipt'],maximum=16*1024*1024).read_bytes())
            expected_panel=(receipt.get('baseline_panel_sha256') or {}).get('selector') if index['source_generation']!=index['candidate_generation'] else index['pair_sha256']['selector']
            _require(calendar.get('schema') in {'D222_PER_EXCHANGE_SOURCE_CALENDAR_V1','V4_PER_EXCHANGE_SOURCE_CALENDAR_V1'}
                     and calendar.get('source_generation')==index['source_generation']
                     and calendar.get('input_sha256')==index['input_sha256'] and calendar.get('panel_sha256')==expected_panel
                     and str(calendar.get('asof_date'))==expected['data_date']
                     and isinstance(calendar.get('dates',{}).get(symbol.rsplit('.',1)[-1]),list)
                     and bool(calendar['dates'][symbol.rsplit('.',1)[-1]])
                     and calendar.get('historical_PIT') is False and all(calendar.get(k) is v for k,v in FLAGS.items()),
                     'GENERIC_PAIRED_HISTORY_CALENDAR_CONFLICT')
            groups=shard.get('statistics',{}).get('groups',[])
            _require(isinstance(groups,list) and len(groups)==len(HISTORY_FIELDS)
                     and {g.get('group_id') for g in groups}=={g[0] for g in HISTORY_FIELDS},
                     'GENERIC_PAIRED_HISTORY_GROUP_CONFLICT')
            for group_id,namespace,field in HISTORY_FIELDS:
                group=next(g for g in groups if g['group_id']==group_id);source=group.get('source_identity',{})
                rule=hashlib.sha256(_canonical({'namespace':namespace,'field':field,
                    'source_view_sha256':binding['history_input']['sha256']})).hexdigest()
                coverage=group.get('coverage',{})
                _require(group.get('identity_status')=='BOUND' and group.get('rule_sha256')==rule
                         and source.get('rule_sha256')==rule and source.get('generation')==index['source_generation']
                         and source.get('input')==index['input_sha256'] and source.get('market')==symbol.rsplit('.',1)[-1]
                         and source.get('calendar_sha256')==shard['market_calendar']['sha256']
                         and source.get('asof')==index['source_date'] and source.get('basis')=='QFQ' and source.get('pit_status')=='NONPIT'
                         and source.get('formula')==receipt['user_formula_sha256' if namespace=='original' else 'kb_field_contract_sha256']
                         and coverage.get('namespace')==namespace and coverage.get('field')==field
                         and type(coverage.get('known_dates')) is int and type(coverage.get('unknown_dates')) is int
                         and coverage['known_dates']+coverage['unknown_dates']==binding['rows'],
                         'GENERIC_PAIRED_HISTORY_GROUP_RULE_CONFLICT:'+group_id)
            packed=gzip.compress(raw,mtime=0)
            _require(len(packed)<=2*1024*1024,'GENERIC_PAIRED_HISTORY_SIZE_LIMIT')
            asset=_write_immutable(root,symbol.replace('.','_')+'_HISTORY','.json.gz',packed,decoded_bytes=len(raw))
            binding['details']['history']={'status':'READY','asset':asset,
                'source_candidate_generation':index['candidate_generation'],'candidate_generation':index['candidate_generation'],
                'calendar_sha256':shard['market_calendar']['sha256'],'source_view_sha256':binding['history_input']['sha256'],
                'validation':'PAIRED_HISTORY_OWNER_SHA_BOUND','history_shard':shard_ref,'history_owner':owner_copy,
                'source_index':index_ref}
            new_ref=_write_immutable(root,symbol.replace('.','_')+'_BINDING','.json',_canonical(binding))
            index['symbols'][symbol]={'status':'READY','binding':new_ref}
            outcomes[symbol]={'status':'READY','binding':new_ref}
        except (ValueError,OSError,KeyError,TypeError) as exc:
            outcomes[symbol]={'status':'UNKNOWN','reason':str(exc)}
    _require(q.sha(owner_path)==owner_copy['sha256']==q.sha(owner_copy['path']),'GENERIC_HISTORY_OWNER_MOVED')
    index['retained_history_binding']={'source_index':index_ref,'history_owner':owner_copy}
    return _write_immutable(root,'GENERIC_SINGLE_INDEX','.json',_canonical(index)),outcomes


def merge_same_pair_indexes(*, base_index_ref, repair_index_ref, output_root):
    """Join complementary verified symbol references without reprocessing them."""
    base=json.loads(_checked(base_index_ref,maximum=8*1024*1024).read_bytes())
    repair=json.loads(_checked(repair_index_ref,maximum=8*1024*1024).read_bytes())
    identity_keys=('source_date','observation_date','source_generation','input_sha256','candidate_generation',
                   'candidate_input_sha256','numeric_manifest','paired_receipt','verified_pair','pair_sha256','historical_PIT',*FLAGS)
    _require(base.get('schema')==repair.get('schema')=='v4.workbench.generic_single_index.v1'
             and all(base.get(k)==repair.get(k) for k in identity_keys)
             and base.get('historical_PIT') is False and all(base.get(k) is v for k,v in FLAGS.items())
             and isinstance(base.get('symbols'),dict) and isinstance(repair.get('symbols'),dict),
             'GENERIC_MERGE_IDENTITY_CONFLICT')
    _checked(base['projection_producer'],maximum=2*1024*1024)
    _checked(repair['projection_producer'],maximum=2*1024*1024)
    root=Path(output_root).resolve(strict=True);_require(root.is_dir(),'GENERIC_OUTPUT_ROOT_INVALID')
    for symbol,item in base['symbols'].items():item['projection_source_index']=base_index_ref
    for symbol,item in repair['symbols'].items():
        existing=base['symbols'].get(symbol)
        _require(isinstance(item,dict) and item.get('status')=='READY'
                 and (existing is None or existing.get('status')=='UNKNOWN'), 'GENERIC_MERGE_SYMBOL_CONFLICT:'+symbol)
        binding=json.loads(_checked(item['binding'],maximum=4*1024*1024).read_bytes())
        _require(binding.get('symbol')==symbol and binding.get('candidate_generation')==base['candidate_generation']
                 and binding.get('candidate_input_sha256')==base['candidate_input_sha256']
                 and binding.get('pair_sha256')==base['pair_sha256'] and binding.get('paired_receipt')==base['paired_receipt'],
                 'GENERIC_MERGE_BINDING_CONFLICT:'+symbol)
        base['symbols'][symbol]={**item,'projection_source_index':repair_index_ref}
    base['projection_sources']=[base_index_ref,repair_index_ref]
    base['projection_producer']=None # mixed producer versions; use the per-symbol source index.
    return _write_immutable(root,'GENERIC_SINGLE_INDEX','.json',_canonical(base))


def materialize_hk_observations(*, index_ref, receipt_ref, history_response_ref, symbols, output_root):
    """Project existing HK owner observations; do not calculate indicators."""
    source=json.loads(_checked(index_ref,maximum=8*1024*1024).read_bytes())
    receipt=json.loads(_checked(receipt_ref,maximum=2*1024*1024).read_bytes())
    response=json.loads(_checked(history_response_ref,maximum=8*1024*1024).read_bytes())
    _require(source.get('schema')=='v4.hk_connect.materialized_symbol_index.v2'
             and source.get('status')=='ISOLATED_READ_ONLY_PARTIAL'
             and receipt.get('schema')=='v4.hk_connect.materialized_symbol_index_receipt.v2'
             and receipt.get('status')=='READ_ONLY_DATE_SEMANTICS_VERIFIED'
             and receipt.get('index')==index_ref and all(source.get(k) is v and receipt.get(k) is v for k,v in FLAGS.items()),
             'HK_OBSERVATION_INDEX_CONFLICT')
    identity=source.get('identity',{});source_date=identity.get('source_date');target_date=identity.get('target_date')
    _require(isinstance(source_date,str) and re.fullmatch(r'\d{8}',source_date)
             and isinstance(target_date,str) and re.fullmatch(r'\d{8}',target_date)
             and isinstance(identity.get('source_panel'),dict) and SHA.fullmatch(str(identity['source_panel'].get('sha256','')))
             and all(isinstance(identity.get(k),str) and SHA.fullmatch(identity[k]) for k in ('calendar_sha256','guard_sha256','input_batch_sha256')),
             'HK_OBSERVATION_IDENTITY_CONFLICT')
    for key in ('input_snapshot','snapshot','owner_receipt','membership_asof_audit'):
        _checked(identity[key])
    symbols=list(dict.fromkeys(symbols))
    _require(0<len(symbols)<=MAX_BATCH_SYMBOLS and all(isinstance(s,str) and HK_CODE.fullmatch(s) for s in symbols),
             'HK_OBSERVATION_SYMBOLS_INVALID')
    root=Path(output_root).resolve(strict=True);_require(root.is_dir(),'HK_OBSERVATION_OUTPUT_INVALID')
    producer_path=Path(__file__).resolve(strict=True)
    producer=_write_immutable(root,'HK_OBSERVATION_PRODUCER','.py',producer_path.read_bytes(),full_hash=True)
    producer.update(source_path=str(producer_path),source_sha256=producer['sha256'])
    _require(q.sha(producer_path)==producer['sha256'],'HK_OBSERVATION_PRODUCER_MOVED')
    indexed={}
    for item in source.get('rows',[]):
        key=item.get('symbol')
        if key in indexed:raise ValueError('HK_OBSERVATION_DUPLICATE_SYMBOL')
        indexed[key]=item
    results={}
    for symbol in symbols:
        try:
            observed=indexed[symbol]
            _require(observed.get('source_date')==source_date and observed.get('target_date')==target_date
                     and observed.get('target_formal_eligibility_status')=='CANNOT_CONFIRM',
                     'HK_OBSERVATION_SYMBOL_IDENTITY_CONFLICT')
            prior=response.get('history_'+symbol);history=[];history_status='UNKNOWN_NOT_MATERIALIZED'
            if prior is not None:
                body=prior.get('body',{});data=body.get('data',{});owner=data.get('owner_snapshot',{})
                _require(prior.get('status_code')==200 and body.get('state')=='READY'
                         and all(body.get(k) is v for k,v in FLAGS.items())
                         and owner.get('panel_sha256')==identity['source_panel']['sha256']
                         and isinstance(data.get('rows'),list), 'HK_HISTORY_RESPONSE_CONFLICT')
                previous=''
                for row in data['rows']:
                    day=str(row.get('date',''));raw=row.get('raw_fields',{})
                    raw_code=raw.get('code_norm') or raw.get('code')
                    _require(re.fullmatch(r'\d{8}',day) and previous<day<=source_date
                             and row.get('symbol')==symbol and raw_code==symbol
                             and (not raw.get('code_norm') or not raw.get('code') or raw['code_norm']==raw['code'])
                             and isinstance(row.get('row_sha256'),str) and SHA.fullmatch(row['row_sha256'])
                             and isinstance(row.get('source_sha256'),str) and SHA.fullmatch(row['source_sha256'])
                             and row.get('research_only') is True and row.get('scoring_allowed') is False,
                             'HK_HISTORY_ROW_CONFLICT')
                    previous=day
                    history.append({'date':day,'raw_fields':{k:raw.get(k) for k in ('open','high','low','close','trade','amount')},
                        'raw_source':raw.get('source'),'source':row.get('source'),'source_sha256':row['source_sha256'],
                        'reconciliation_row_sha256':row['row_sha256'],'units_status':row.get('units_status'),
                        'currency_basis_status':row.get('currency_basis_status'),'adjustment_basis_status':row.get('adjustment_basis_status'),
                        'pit_safety_status':row.get('pit_safety_status'),'overlap_status':row.get('overlap_status')})
                history_status='OBSERVED_RAW_ROWS' if history else 'UNKNOWN_EMPTY'
            source_row=next((row for row in history if row['date']==source_date),None)
            if observed.get('raw_values_status')=='OBSERVED_RAW_FIELDS_ONLY_UNITS_BASIS_PIT_NOT_PROVEN' and source_row is not None:
                expected=observed.get('raw_20261030_ohlc_trade_amount') or {}
                _require(all(_same(source_row['raw_fields'].get(k),expected.get(k)) for k in ('open','high','low','close','trade','amount'))
                         and source_row['reconciliation_row_sha256']==observed.get('raw_reconcile_row_sha256'),
                         'HK_SOURCE_DAY_ROW_CONFLICT')
            if observed.get('decision_reason')=='TARGET_SNAPSHOT_EXCLUDED':
                _require(source_row is None and observed.get('raw_20261030_ohlc_trade_amount') is None,
                         'HK_EXCLUDED_SOURCE_DAY_CONFLICT')
            payload={'schema':'v4.workbench.hk_single_observation.v1','symbol':symbol,'name':observed.get('name'),
                'source_date':source_date,'target_date':target_date,'source_index':index_ref,'source_receipt':receipt_ref,
                'history_response':history_response_ref,'source_panel_sha256':identity['source_panel']['sha256'],
                'input_snapshot_sha256':identity['input_snapshot']['sha256'],'calendar_sha256':identity['calendar_sha256'],
                'guard_sha256':identity['guard_sha256'],'source_snapshot_capture_instant':identity.get('source_snapshot_capture_instant'),
                'source_snapshot_capture_instant_status':identity.get('source_snapshot_capture_instant_status'),
                'original_scheduled_cutoff':identity.get('original_scheduled_cutoff'),
                'decision_cutoff_manual_run':identity.get('decision_cutoff_manual_run'),
                'source_generation_status':identity.get('source_generation_status'),
                'source_day_security_master_member':observed.get('source_day_security_master_member'),
                'target_formal_eligibility_status':observed['target_formal_eligibility_status'],
                'decision':observed.get('decision'),'decision_reason':observed.get('decision_reason'),
                'source_scope':observed.get('source_scope'),'raw_values_status':observed.get('raw_values_status'),
                'raw_source_day':observed.get('raw_20261030_ohlc_trade_amount'),
                'raw_source_tag':observed.get('raw_source_tag'),
                'source_day_reconciliation_row_sha256':observed.get('raw_reconcile_row_sha256'),
                'trade_unit':observed.get('trade_unit'),'amount_unit':observed.get('amount_unit'),
                'currency':observed.get('currency'),'price_adjustment_basis':observed.get('price_adjustment_basis'),
                'price_window':observed.get('price_window'),'volume_window':observed.get('volume_window'),
                'guarded_metrics':observed.get('metrics'),
                'missing_sessions':observed.get('missing_sessions'),'panel_window_gaps':observed.get('panel_window_gaps'),
                'history_status':history_status,'history':history,'chart_status':'UNKNOWN_NOT_SUPPLIED',
                'company_status':'UNKNOWN_NOT_BOUND','historical_PIT':False,**FLAGS}
            asset=_packed(root,symbol.replace('.','_')+'_HK_OBSERVATION',payload)
            results[symbol]={'status':'READY','asset':asset}
        except (ValueError,OSError,KeyError,TypeError) as exc:
            results[symbol]={'status':'UNKNOWN','reason':str(exc)}
    _require(q.sha(producer_path)==q.sha(producer['path'])==producer['sha256'],'HK_OBSERVATION_PRODUCER_MOVED')
    index={'schema':'v4.workbench.hk_observation_index.v1','source_date':source_date,'target_date':target_date,
           'source_index':index_ref,'source_receipt':receipt_ref,'history_response':history_response_ref,
           'source_panel_sha256':identity['source_panel']['sha256'],'projection_producer':producer,
           'symbols':results,'historical_PIT':False,**FLAGS}
    return _write_immutable(root,'HK_OBSERVATION_INDEX','.json',_canonical(index)),results


def _bulk_owner_functions(owner_ref, spool_owner_ref, adapter_sha):
    """Load only the two SHA-frozen owner functions used for the existing join."""
    _require(owner_ref.get('sha256')==adapter_sha,'GENERIC_BULK_OWNER_SHA_CONFLICT')
    owner=_checked(owner_ref,maximum=4*1024*1024);old=_checked(spool_owner_ref,maximum=4*1024*1024)
    def nodes(path):
        return {node.name:node for node in ast.parse(path.read_text()).body if isinstance(node,ast.FunctionDef)}
    current,previous=nodes(owner),nodes(old)
    _require(all(name in current and name in previous and ast.dump(current[name],include_attributes=False)==ast.dump(previous[name],include_attributes=False)
                 for name in ('_bucket','spool_current')),'GENERIC_BULK_SPOOL_OWNER_CONFLICT')
    _require('_kb_overlay_retained' in current,'GENERIC_BULK_OWNER_OVERLAY_MISSING')
    namespace={'pa':pa,'pq':pq,'pd':pd,'re':re,'zlib':zlib,'Path':Path,'CODE':q.CODE,'QfqGateError':q.QfqGateError,
               'KB_FIELDS':q.KB_FIELDS,'SINGLE_FEEDBACK_FIELDS':q.SINGLE_FEEDBACK_FIELDS,
               'SINGLE_ACTION_FIELDS':q.SINGLE_ACTION_FIELDS,'SINGLE_YIDONG_FIELDS':q.SINGLE_YIDONG_FIELDS,
               'SINGLE_GAP_FIELDS':q.SINGLE_GAP_FIELDS}
    tree=ast.fix_missing_locations(ast.Module(body=[current['_bucket'],current['_kb_overlay_retained']],type_ignores=[]))
    exec(compile(tree,str(owner),'exec'),namespace)
    return namespace['_bucket'],namespace['_kb_overlay_retained']


def _bulk_spools(spool_ref,receipt,owner_ref):
    desc=json.loads(_checked(spool_ref,maximum=1024*1024).read_bytes())
    _require(desc.get('schema')=='a_share_original_spool_reuse_v1' and desc.get('status')=='OWNER_PRODUCED_ARROW_BUCKETS'
             and desc.get('baseline_panel_sha256')==receipt.get('baseline_panel_sha256')
             and all(desc.get(k) is v for k,v in FLAGS.items()) and set(desc.get('roles',{}))=={'selector','backtest'},
             'GENERIC_BULK_SPOOL_CONFLICT')
    inputs=json.loads(_checked(desc['owner_inputs'],maximum=4*1024*1024).read_bytes())
    oldrun=json.loads(_checked(desc['owner_run_receipt'],maximum=4*1024*1024).read_bytes())
    _require(inputs.get('qfq_source',{}).get('sha256')==desc['owner_source']['sha256']
             and oldrun.get('schema')=='v4.full_owner_lifecycle_bounded_run.v1'
             and oldrun.get('status')=='FAIL' and oldrun.get('stage')=='OWNER_RUN', 'GENERIC_BULK_SPOOL_EVIDENCE_CONFLICT')
    bucket,overlay=_bulk_owner_functions(owner_ref,desc['owner_source'],receipt['adapter_sha256'])
    roles={}
    for role,ref in desc['roles'].items():
        value=json.loads(_checked(ref,maximum=1024*1024).read_bytes())
        _require(value.get('source_sha256')==receipt['baseline_panel_sha256'][role] and value.get('row_copy')=='ARROW_V1'
                 and set(value.get('files',{}))=={str(i) for i in range(32)},'GENERIC_BULK_SPOOL_RECEIPT_CONFLICT:'+role)
        roles[role]={int(k):v for k,v in value['files'].items()}
    return desc,roles,bucket,overlay


def _bulk_columns(role, *, fields=False):
    common=['ts_code','trade_date','open','high','low','close','zge_white_line','zge_yellow_line']
    names=common+(['volume','name',*ORIGINAL_FIELDS] if role=='selector' else ['vol',*SHARED_ORIGINAL_FIELDS])
    return list(dict.fromkeys(names+(_fields() if fields else [])))


def _bulk_addition_groups(roles,receipt):
    resolution=json.loads(_checked(receipt['lifecycle_resolution'],maximum=4*1024*1024).read_bytes())
    codes=set(resolution.get('codes',{}));_require(codes,'GENERIC_BULK_ADDITIONS_MISSING')
    result={}
    for role in ('selector','backtest'):
        parquet=pq.ParquetFile(roles[role]['path']);column=parquet.schema_arrow.get_field_index('ts_code');groups={}
        for i in range(parquet.metadata.num_row_groups):
            stat=parquet.metadata.row_group(i).column(column).statistics
            _require(stat is not None and stat.has_min_max,'GENERIC_BULK_ROWGROUP_STAT_MISSING')
            if stat.min==stat.max and stat.min in codes:
                _require(stat.min not in groups,'GENERIC_BULK_ROWGROUP_DUPLICATE');groups[stat.min]=i
        _require(set(groups)==codes,'GENERIC_BULK_ADDITION_ROWGROUP_CONFLICT:'+role);result[role]=groups
    return codes,result


def _bulk_checkpoint(code,receipt,parts):
    record=json.loads((parts/(code+'.receipt.json')).read_bytes());path=parts/(code+'.parquet')
    _require(isinstance(record.get('sha256'),str) and SHA.fullmatch(record['sha256']),'GENERIC_BULK_CHECKPOINT_RECEIPT_INVALID')
    before=_stat(path);_checked({'path':str(path),'sha256':record['sha256']});_require(_stat(path)==before,'GENERIC_BULK_CHECKPOINT_MOVED')
    for key,source in (('confirmed_gap_sidecar',receipt['confirmed_gap_sidecars']),('n_structure_checkpoint',receipt['n_structure_checkpoints'])):
        expected=source.get(code);actual=record.get(key)
        _require(isinstance(expected,dict) and isinstance(actual,dict)
                 and all(expected.get(k)==actual.get(k) for k in ('path','sha256','checkpoint_id')),
                 'GENERIC_BULK_CHECKPOINT_BINDING_CONFLICT:'+key)
        reused=(key=='n_structure_checkpoint' and code in receipt.get('materialized_reuse_refs',{})
                and actual.get('source_generation')==receipt.get('materialized_reuse_source_generation')
                and actual.get('resume_across_generation') is False and actual.get('checkpoint_id') is None)
        _require(reused or actual.get('checkpoint_id')==record.get('checkpoint_id'),
                 'GENERIC_BULK_CHECKPOINT_BINDING_CONFLICT:'+key)
    return record,before


def _bulk_overlay(code,left,right,roles,parts,overlay):
    output=[]
    for role,table in (('selector',left),('backtest',right)):
        names=list(dict.fromkeys([*table.column_names,*_fields()]))
        schema=pa.schema([roles[role]['schema'].field(name) for name in names])
        output.append(overlay(table,schema,parts,full_research=True))
    return output


def _bulk_resources(root,worker_pids=(),*,min_disk_gib=40):
    """Conservative macOS resource gate; no submissions when telemetry is missing."""
    _require(min_disk_gib in (24,40),'GENERIC_RESOURCE_GATE_INVALID')
    free=shutil.disk_usage(root).free
    if free<min_disk_gib*1024**3:return {'ok':False,'reason':f'DISK_BELOW_{min_disk_gib}_GIB','disk_free':free}
    try:
        vm=subprocess.run(['vm_stat'],capture_output=True,text=True,check=True,timeout=5).stdout
        page=int(re.search(r'page size of (\d+) bytes',vm).group(1))
        values={name:int(re.search(r'^Pages '+name+r':\s*(\d+)',vm,re.M).group(1)) for name in ('free','inactive','speculative')}
        available=sum(values.values())*page
        pressure=subprocess.run(['memory_pressure'],capture_output=True,text=True,check=True,timeout=5).stdout
        pct=int(re.search(r'System-wide memory free percentage:\s*(\d+)%',pressure).group(1))
        pids=','.join(str(x) for x in (os.getpid(),*worker_pids))
        ps=subprocess.run(['ps','-o','rss=','-p',pids],capture_output=True,text=True,check=True,timeout=5).stdout
        rss=sum(int(x) for x in ps.split())*1024
    except (OSError,subprocess.SubprocessError,ValueError,AttributeError):
        return {'ok':False,'reason':'RESOURCE_TELEMETRY_UNAVAILABLE','disk_free':free}
    reason='SYSTEM_MEMORY_BELOW_24_GIB' if available<24*1024**3 else 'MEMORY_PRESSURE' if pct<20 else 'JOB_RSS_ABOVE_64_GIB' if rss>64*1024**3 else None
    return {'ok':reason is None,'reason':reason,'disk_free':free,'available_estimate':available,'pressure_free_pct':pct,'job_rss':rss}


_BULK_WORKER=None
def _bulk_worker_init(context):
    global _BULK_WORKER
    _,overlay=_bulk_owner_functions(context['owner_ref'],context['spool_owner_ref'],context['receipt']['adapter_sha256'])
    _BULK_WORKER={**context,'overlay':overlay}


def _bulk_one(code,left,right,old):
    started=time.monotonic();c=_BULK_WORKER;receipt=c['receipt'];parts=Path(c['parts']);roles=c['roles']
    try:
        record,before=_bulk_checkpoint(code,receipt,parts)
        if old:left,right=_bulk_overlay(code,left,right,roles,parts,c['overlay'])
        else:
            checkpoint=pq.read_table(parts/(code+'.parquet'),columns=['trade_date',*_fields()]).sort_by([('trade_date','ascending')]).to_pylist()
            candidate=left.sort_by([('trade_date','ascending')]).to_pylist()
            _require(len(candidate)==len(checkpoint),'GENERIC_BULK_ADDITION_CHECKPOINT_LENGTH')
            for a,b in zip(candidate,checkpoint):
                _require(str(a['trade_date'])==str(b['trade_date']) and all(_same(_plain(a[n]),_plain(b[n])) for n in _fields()),
                         'GENERIC_BULK_ADDITION_CHECKPOINT_CONFLICT')
        _require(_stat(parts/(code+'.parquet'))==before,'GENERIC_BULK_CHECKPOINT_MOVED')
        side_ref=receipt['confirmed_gap_sidecars'][code];side=pq.read_table(_checked(side_ref))
        side_meta=json.loads((side.schema.metadata or {})[b'v4.a_share.kb_gap_diagnostics.v1'])
        _require(side_meta.get('symbol')==code and side_meta.get('generation_id')==receipt['generation_id']
                 and side_meta.get('source_input_sha256')==receipt['input_sha256'] and side_meta.get('n_structure_enabled') is True
                 and set(side_meta.get('diagnostic_keys',[]))==set(q.SINGLE_GAP_DIAGNOSTICS)|{'kb_n_structure'}
                 and all(side_meta.get(k) is v for k,v in FLAGS.items()),'GENERIC_BULK_SIDECAR_CONFLICT')
        n_identity=_n_sidecar_identity(receipt,side_meta,side,code)
        name_values=[x for x in left['name'].to_pylist() if isinstance(x,str) and x.strip()]
        identity=dict(symbol=code,name=name_values[-1].strip() if name_values else code,
            source_date=c['source_date'],observation_date=c['observation_date'],generation=c['source_generation'],
            candidate_generation=receipt['generation_id'],input_sha256=c['source_input'],candidate_input_sha256=receipt['input_sha256'],
            numeric_manifest=c['numeric_manifest_ref'],paired_receipt=c['paired_receipt_ref'],
            pair_sha256=receipt['candidate_sha256'],baseline_panel_sha256=receipt['baseline_panel_sha256'],
            kb_authority_sha256=receipt.get('kb_authority_sha256'),kb_field_contract_sha256=receipt.get('kb_field_contract_sha256'),
            diagnostics_sha256=side_ref['sha256'],n_rule_sha256=side_meta['n_structure_contract_sha256'],
            n_helper_sha256=side_meta['n_structure_helper_sha256'],adjustment_convention=receipt.get('convention','BOUND_ORIGINAL_OWNER_QFQ'),
            historical_PIT=False,**n_identity,**FLAGS)
        bound=build_from_verified_tables(symbol=code,selector=left,backtest=right,diagnostics=side,identity=identity,
            output_root=Path(c['output_root']),original_projection_ref=c['originals'].get(code),engine_config_ref=c['engine_ref'])
        product=json.loads(_checked(bound,maximum=4*1024*1024).read_bytes())
        _require(product['chart']['status']=='READY','GENERIC_BULK_CHART_NOT_READY:'+str(product['chart'].get('reason')))
        refs=[bound,product['history_input'],product['overlay'],*product['chunks'],product['chart']['projection'],product['chart']['html']]
        return {'status':'READY','binding':bound,'rows':product['rows'],'asset_bytes':sum(x['bytes'] for x in refs),
                'elapsed_seconds':round(time.monotonic()-started,3)}
    except (ValueError,OSError,KeyError,TypeError,pa.ArrowException) as exc:
        reason=str(exc)
        return {'status':'UNKNOWN' if reason=='GENERIC_TARGET_DATE_MISSING' else 'FAILED','reason':reason}


def _bulk_compare_prior(code,left,right,old,context,prior,overlay):
    record,before=_bulk_checkpoint(code,context['receipt'],Path(context['parts']))
    if old:left,right=_bulk_overlay(code,left,right,context['roles'],Path(context['parts']),overlay)
    _require(_stat(Path(context['parts'])/(code+'.parquet'))==before,'GENERIC_BULK_CHECKPOINT_MOVED')
    item=prior['symbols'][code];_require(item.get('status')=='READY','GENERIC_BULK_CANARY_NOT_READY')
    binding=json.loads(_checked(item['binding'],maximum=4*1024*1024).read_bytes());fields=binding['field_names']
    expected=[]
    for ref in binding['chunks']:
        expected.extend(json.loads(_bounded_gzip(ref,maximum=MAX_CHUNK_DECODED,compressed_maximum=MAX_CHUNK_COMPRESSED))['rows'])
    a=left.sort_by([('trade_date','ascending')]).to_pylist();b=right.sort_by([('trade_date','ascending')]).to_pylist()
    side_ref=context['receipt']['confirmed_gap_sidecars'][code];side_table=pq.read_table(_checked(side_ref))
    side_meta=json.loads((side_table.schema.metadata or {})[b'v4.a_share.kb_gap_diagnostics.v1'])
    n_identity=_n_sidecar_identity(context['receipt'],side_meta,side_table,code)
    _require(all(binding.get(k,binding.get('candidate_generation' if k=='n_generation_id' else 'candidate_input_sha256'))==v
                 for k,v in n_identity.items() if k in {'n_generation_id','n_input_sha256'}),'GENERIC_BULK_CANARY_N_IDENTITY_CONFLICT')
    side=side_table.sort_by([('trade_date','ascending')]).to_pylist()
    _require(len(a)==len(b)==len(side)==len(expected),'GENERIC_BULK_CANARY_LENGTH_CONFLICT')
    for x,y,d,z in zip(a,b,side,expected):
        _require(x['ts_code']==y['ts_code']==d['ts_code']==code and str(x['trade_date'])==str(y['trade_date'])==str(d['trade_date'])==str(z[0]),
                 'GENERIC_BULK_CANARY_KEY_CONFLICT')
        _require(all(_same(_plain(x[n]),_plain(y[n])) and _same(_plain(x[n]),v) for n,v in zip(fields,z[1]))
                 and all(_same(_plain(x[n]),v) for n,v in zip(ORIGINAL_FIELDS,z[2]))
                 and json.loads(d['diagnostics_json'])==z[3]
                 and [_plain(x['zge_white_line']),_plain(x['zge_yellow_line'])]==z[4],
                 'GENERIC_BULK_CANARY_VALUES_CONFLICT')
    chart=binding['chart'];_require(chart.get('status')=='READY','GENERIC_BULK_CANARY_CHART_MISSING')
    projection=json.loads(_bounded_gzip(chart['projection'],maximum=MAX_PROJECTION_DECODED,compressed_maximum=MAX_PROJECTION_COMPRESSED))
    _projection_rows(projection,code,context['source_date'].replace('-',''),context['source_generation'],context['source_input'],a)
    return {'symbol':code,'rows':len(a),'kb_cells':len(a)*len(fields),'checkpoint_sha256':record['sha256'],'status':'PASS'}


def _bulk_read_bucket(spools,bucket):
    tables={}
    for role in ('selector','backtest'):
        ref=spools[role][bucket];path=Path(ref['path']);before=_stat(path)
        _require(path.is_absolute() and not path.is_symlink() and path.resolve(strict=True)==path,'GENERIC_BULK_BUCKET_PATH_CONFLICT')
        raw=path.read_bytes();_require(_stat(path)==before and hashlib.sha256(raw).hexdigest()==ref['sha256'],
                                      'GENERIC_BULK_BUCKET_SHA_OR_STAT_CONFLICT:'+role)
        tables[role]=pq.read_table(pa.BufferReader(raw),columns=_bulk_columns(role))
    return tables


def prepare_owner_bulk(*, paired_receipt_ref, verified_pair_ref, numeric_manifest_ref, spool_ref, owner_ref,
                       prior_index_ref, no_frame_ref, original_manifest_ref, engine_ref, output_root, observation_date):
    """Prepare a resumable view-only traversal of the existing owner outputs."""
    root=Path(output_root).resolve(strict=True);_require(root.is_dir(),'GENERIC_BULK_OUTPUT_ROOT_INVALID')
    receipt,roles=_pair_snapshot(paired_receipt_ref,verified_pair_ref)
    _require(receipt.get('full_research_spool_reuse')==spool_ref,'GENERIC_BULK_SPOOL_RECEIPT_UNBOUND')
    desc,spools,bucket,overlay=_bulk_spools(spool_ref,receipt,owner_ref)
    numeric=json.loads(_checked(numeric_manifest_ref,maximum=8*1024*1024).read_bytes())
    prior=json.loads(_checked(prior_index_ref,maximum=8*1024*1024).read_bytes())
    source_date=datetime.strptime(str(receipt['target_date']),'%Y%m%d').strftime('%Y-%m-%d')
    source_generation=numeric.get('source_generation');source_input=numeric.get('input_sha256')
    _require(prior.get('schema')=='v4.workbench.generic_single_index.v1' and prior.get('source_date')==source_date
             and prior.get('observation_date')==observation_date and prior.get('source_generation')==source_generation
             and prior.get('input_sha256')==source_input and prior.get('candidate_generation')==receipt['generation_id']
             and prior.get('candidate_input_sha256')==receipt['input_sha256'] and prior.get('numeric_manifest')==numeric_manifest_ref
             and prior.get('paired_receipt')==paired_receipt_ref and prior.get('verified_pair')==verified_pair_ref
             and prior.get('pair_sha256')==receipt['candidate_sha256'] and prior.get('historical_PIT') is False
             and all(prior.get(k) is v for k,v in FLAGS.items()),'GENERIC_BULK_PRIOR_IDENTITY_CONFLICT')
    _require(receipt.get('kb_initial_upgrade',{}).get('source_generation_id')==source_generation
             and receipt.get('materialized_reuse_source_input_sha256')==source_input
             and receipt.get('kb_initial_upgrade',{}).get('baseline_panel_sha256')==receipt['baseline_panel_sha256'],
             'GENERIC_BULK_SOURCE_LINEAGE_CONFLICT')
    missing=json.loads(_checked(no_frame_ref,maximum=1024*1024).read_bytes());items=missing.get('items')
    frame=set(receipt['confirmed_gap_sidecars']);_require(frame==set(receipt['n_structure_checkpoints']), 'GENERIC_BULK_SIDECAR_DENOMINATOR_CONFLICT')
    _require(missing.get('schema')=='v4.a_share.no_paired_frame_scope.v1' and missing.get('status')=='EXACT_SET_DIFFERENCE_VERIFIED'
             and missing.get('generation_id')==receipt['generation_id'] and missing.get('input_sha256')==receipt['input_sha256']
             and missing.get('attestation')==verified_pair_ref and missing.get('data_date')==str(receipt['target_date'])
             and missing.get('a_frame_count')==len(frame) and isinstance(items,list)
             and missing.get('missing_count')==len(items) and missing.get('effective_count')==len(frame)+len(items)
             and all(missing.get(k) is v for k,v in FLAGS.items()),'GENERIC_BULK_SCOPE_LEDGER_CONFLICT')
    no_frame={item.get('symbol'):item for item in items};_require(len(no_frame)==len(items) and not frame&set(no_frame)
        and all(isinstance(code,str) and CODE.fullmatch(code) and item.get('frame_status')=='NO_PAIRED_A_FRAME'
                for code,item in no_frame.items()),'GENERIC_BULK_SCOPE_LEDGER_CONFLICT')
    original=json.loads(_checked(original_manifest_ref,maximum=8*1024*1024).read_bytes())
    _require(original.get('schema')=='v4.a_share.owner_original_charts.v1' and isinstance(original.get('samples'),dict)
             and all(original.get(k) is v for k,v in FLAGS.items()),'GENERIC_BULK_ORIGINAL_MANIFEST_CONFLICT')
    originals={code:item['projection'] for code,item in original['samples'].items()
               if isinstance(item,dict) and isinstance(item.get('projection'),dict)}
    _checked(engine_ref,maximum=1024*1024)
    additions,groups=_bulk_addition_groups(roles,receipt)
    _require(additions<=frame and set(prior.get('symbols',{}))<=frame,'GENERIC_BULK_PRIOR_SCOPE_CONFLICT')
    code_path=Path(__file__).resolve(strict=True)
    producer=_write_immutable(root,'BULK_PROJECTION_PRODUCER','.py',code_path.read_bytes(),full_hash=True)
    producer.update(source_path=str(code_path),source_sha256=producer['sha256'])
    run_identity={'paired_receipt':paired_receipt_ref,'verified_pair':verified_pair_ref,'numeric_manifest':numeric_manifest_ref,
        'spool':spool_ref,'owner':owner_ref,'prior_index':prior_index_ref,'no_frame':no_frame_ref,
        'original_manifest':original_manifest_ref,'engine_config':engine_ref,'producer_sha256':producer['sha256'],
        'observation_date':observation_date,'historical_PIT':False,**FLAGS}
    existing=list(root.glob('BULK_RUN_IDENTITY_*.json'))
    if existing:
        _require(len(existing)==1 and json.loads(existing[0].read_bytes())==run_identity,'GENERIC_BULK_RESUME_IDENTITY_CONFLICT')
    identity_ref=_write_immutable(root,'BULK_RUN_IDENTITY','.json',_canonical(run_identity),full_hash=True)
    context={'receipt':receipt,'roles':roles,'parts':str(Path(receipt['run_dir'])/'symbol_checkpoints'),
        'source_date':source_date,'observation_date':observation_date,'source_generation':source_generation,'source_input':source_input,
        'numeric_manifest_ref':numeric_manifest_ref,'paired_receipt_ref':paired_receipt_ref,'verified_pair_ref':verified_pair_ref,
        'owner_ref':owner_ref,'spool_owner_ref':desc['owner_source'],'engine_ref':engine_ref,'originals':originals,
        'output_root':str(root),'producer':producer,'run_identity':identity_ref,'frame':frame,'no_frame':no_frame,'no_frame_ref':no_frame_ref,
        'additions':additions,'groups':groups,'spools':spools,'bucket':bucket,'overlay':overlay,'prior':prior,'prior_ref':prior_index_ref}
    return context


def verify_owner_bulk_canary(context,symbols):
    """Compare old3/new/long samples to existing pair-derived assets, without recomputing."""
    symbols=list(dict.fromkeys(symbols));prior=context['prior'];cached={};results=[]
    for code in symbols:
        _require(code in context['frame'] and prior.get('symbols',{}).get(code,{}).get('status')=='READY','GENERIC_BULK_CANARY_SCOPE_CONFLICT')
        old=code not in context['additions']
        if old:
            bucket=context['bucket'](code)
            if bucket not in cached:cached[bucket]=_bulk_read_bucket(context['spools'],bucket)
            tables=cached[bucket]
            left=tables['selector'].filter(pc.equal(tables['selector']['ts_code'],code))
            right=tables['backtest'].filter(pc.equal(tables['backtest']['ts_code'],code))
        else:
            left=pq.ParquetFile(context['roles']['selector']['path']).read_row_group(context['groups']['selector'][code],columns=_bulk_columns('selector',fields=True))
            right=pq.ParquetFile(context['roles']['backtest']['path']).read_row_group(context['groups']['backtest'][code],columns=_bulk_columns('backtest',fields=True))
        results.append(_bulk_compare_prior(code,left,right,old,context,prior,context['overlay']))
    return cached,results


def run_owner_bulk(context, cached_buckets, *, workers=4, max_new=None):
    """Append read-only views; stop submitting at resource, identity or I/O failure."""
    _require(type(workers) is int and 1<=workers<=4,'GENERIC_BULK_WORKER_LIMIT')
    _require(max_new is None or type(max_new) is int and max_new>0,'GENERIC_BULK_LIMIT_INVALID')
    root=Path(context['output_root']);checkpoints=root/'symbol_receipts';checkpoints.mkdir(exist_ok=True)
    results=dict(context['prior']['symbols']);identity_sha=context['run_identity']['sha256'];errors=[]
    for code,item in context['no_frame'].items():
        results[code]={'status':'UNKNOWN','reason':'NO_PAIRED_A_FRAME:'+str(item.get('snapshot_quarantine_reason') or 'SOURCE_GAP'),
                       'source_scope_ref':context['no_frame_ref'],'source_qualification_reason':item.get('source_qualification_reason')}
    for path in checkpoints.glob('*_VIEW_RESULT_*.json'):
        value=json.loads(path.read_bytes());code=value.get('symbol')
        _require(code in context['frame'] and value.get('run_identity_sha256')==identity_sha,'GENERIC_BULK_RESUME_RECEIPT_CONFLICT')
        result=value.get('result',{});_require(result.get('status') in {'READY','UNKNOWN','FAILED'},'GENERIC_BULK_RESUME_RECEIPT_INVALID')
        if result['status']=='READY':
            _checked(result['binding'],maximum=4*1024*1024)
            if code in results and results[code].get('status')=='READY':
                _require(results[code]['binding']==result['binding'],'GENERIC_BULK_RESUME_DUPLICATE_CONFLICT')
            results[code]=result
        elif code not in results or results[code].get('status')!='READY':results[code]=result
    # A recorded deterministic source gap is terminal. Failed attempts remain
    # in the ledger but may be retried after the environment is corrected.
    pending={code for code in context['frame'] if code not in results or results[code].get('status')=='FAILED'}
    worker_context={k:v for k,v in context.items() if k in {'receipt','parts','source_date','observation_date','source_generation',
        'source_input','numeric_manifest_ref','paired_receipt_ref','owner_ref','spool_owner_ref','engine_ref','originals','output_root'}}
    worker_context['roles']={role:{'schema':value['schema']} for role,value in context['roles'].items()}
    submitted=0;started=time.monotonic();new_bytes=0;stopped=None;last_resources=None;last_health=0.0
    def write_result(code,result):
        nonlocal new_bytes,stopped
        value={'schema':'v4.workbench.generic_bulk_symbol_receipt.v1','symbol':code,'run_identity_sha256':identity_sha,'result':result,**FLAGS}
        _write_immutable(checkpoints,code.replace('.','_')+'_VIEW_RESULT','.json',_canonical(value))
        results[code]=result;new_bytes+=result.get('asset_bytes',0)
        if result.get('status')=='FAILED':errors.append({'symbol':code,'reason':result.get('reason')});stopped='SYMBOL_FAILURE'
    def drain(futures,block=False):
        if not futures:return
        done,_=wait(futures,return_when=FIRST_COMPLETED,timeout=None if block else 0)
        for future in done:
            code=futures.pop(future)
            try:result=future.result()
            except BaseException as exc:result={'status':'FAILED','reason':type(exc).__name__+': '+str(exc)}
            write_result(code,result)
    worker_health=_bulk_resources(root);last_resources=worker_health
    if not worker_health['ok']:stopped=worker_health['reason']
    pool=ProcessPoolExecutor(max_workers=workers,initializer=_bulk_worker_init,initargs=(worker_context,)) if not stopped and pending else None
    futures={}
    try:
        order=list(cached_buckets)+[i for i in range(32) if i not in cached_buckets]
        for bucket in order:
            codes=sorted(code for code in pending if code not in context['additions'] and context['bucket'](code)==bucket)
            if not codes or stopped:continue
            if max_new is not None and submitted>=max_new:stopped='BOUNDED_BATCH_LIMIT';break
            last_resources=_bulk_resources(root,[p.pid for p in multiprocessing.active_children() if p.pid])
            if not last_resources['ok']:stopped=last_resources['reason'];break
            tables=cached_buckets.pop(bucket,None) or _bulk_read_bucket(context['spools'],bucket)
            for code in codes:
                while len(futures)>=workers and not stopped:drain(futures,True)
                if stopped or max_new is not None and submitted>=max_new:
                    stopped=stopped or 'BOUNDED_BATCH_LIMIT';break
                if time.monotonic()-last_health>=5:
                    last_resources=_bulk_resources(root,[p.pid for p in multiprocessing.active_children() if p.pid]);last_health=time.monotonic()
                    if not last_resources['ok']:stopped=last_resources['reason'];break
                if shutil.disk_usage(root).free<40*1024**3:stopped='DISK_BELOW_40_GIB';break
                left=tables['selector'].filter(pc.equal(tables['selector']['ts_code'],code))
                right=tables['backtest'].filter(pc.equal(tables['backtest']['ts_code'],code))
                if not left.num_rows or not right.num_rows:write_result(code,{'status':'FAILED','reason':'GENERIC_BULK_BUCKET_SYMBOL_MISSING'});break
                futures[pool.submit(_bulk_one,code,left,right,True)]=code;submitted+=1
            while futures:drain(futures,True)
            if stopped=='BOUNDED_BATCH_LIMIT':cached_buckets[bucket]=tables
        for code in sorted(pending & context['additions']):
            if stopped:break
            if max_new is not None and submitted>=max_new:stopped='BOUNDED_BATCH_LIMIT';break
            while len(futures)>=workers and not stopped:drain(futures,True)
            if stopped:break
            last_resources=_bulk_resources(root,[p.pid for p in multiprocessing.active_children() if p.pid])
            if not last_resources['ok']:stopped=last_resources['reason'];break
            left=pq.ParquetFile(context['roles']['selector']['path']).read_row_group(context['groups']['selector'][code],columns=_bulk_columns('selector',fields=True))
            right=pq.ParquetFile(context['roles']['backtest']['path']).read_row_group(context['groups']['backtest'][code],columns=_bulk_columns('backtest',fields=True))
            futures[pool.submit(_bulk_one,code,left,right,False)]=code;submitted+=1
        while futures:drain(futures,True)
    except (ValueError,OSError,KeyError,TypeError,pa.ArrowException) as exc:
        stopped='BULK_INPUT_FAILURE';errors.append({'symbol':None,'reason':type(exc).__name__+': '+str(exc)})
        while futures:drain(futures,True)
    finally:
        if pool:pool.shutdown(wait=True)
    try:
        _unchanged(context['roles'])
        _require(q.sha(Path(__file__).resolve(strict=True))==context['producer']['sha256'],'GENERIC_BULK_PRODUCER_MOVED')
    except (ValueError,OSError) as exc:
        stopped='BULK_IDENTITY_MOVED';errors.append({'symbol':None,'reason':str(exc)})
    unfinished=sorted(code for code in context['frame'] if code not in results or results[code].get('status')=='FAILED')
    summary={'schema':'v4.workbench.generic_bulk_progress.v1','run_identity':context['run_identity'],'frame_count':len(context['frame']),
        'effective_count':len(context['frame'])+len(context['no_frame']),'ready':sum(x.get('status')=='READY' for x in results.values()),
        'unknown':sum(x.get('status')=='UNKNOWN' for x in results.values()),'unfinished_count':len(unfinished),
        'unfinished':unfinished,'submitted_this_run':submitted,'asset_bytes_this_run':new_bytes,
        'elapsed_seconds':round(time.monotonic()-started,3),'stop_reason':stopped,'errors':errors,'resources':last_resources,**FLAGS}
    progress=_write_immutable(root,'BULK_PROGRESS','.json',_canonical(summary))
    if unfinished or stopped or errors:return {'status':'PARTIAL','progress':progress,**summary}
    index={'schema':'v4.workbench.generic_single_index.v1','source_date':context['source_date'],'observation_date':context['observation_date'],
        'source_generation':context['source_generation'],'input_sha256':context['source_input'],
        'candidate_generation':context['receipt']['generation_id'],'candidate_input_sha256':context['receipt']['input_sha256'],
        'numeric_manifest':context['numeric_manifest_ref'],'paired_receipt':context['paired_receipt_ref'],
        'pair_sha256':context['receipt']['candidate_sha256'],'projection_producer':context['producer'],
        'verified_pair':context['verified_pair_ref'],'previous_index':context['prior_ref'],
        'scope_gap_receipt':context['no_frame_ref'],'symbols':results,'historical_PIT':False,**FLAGS}
    index_ref=_write_immutable(root,'GENERIC_SINGLE_INDEX','.json',_canonical(index))
    return {'status':'COMPLETE','index':index_ref,'progress':progress,**summary}


def prepare_action_rebind(*, origin_index_ref, paired_receipt_ref, verified_pair_ref, output_root):
    """Validate the corrected pair once before reusing any frozen view assets."""
    origin=json.loads(_checked(origin_index_ref,maximum=8*1024*1024).read_bytes())
    receipt=json.loads(_checked(paired_receipt_ref,maximum=16*1024*1024).read_bytes())
    correction=receipt.get('action_correction') or {}
    root=Path(output_root).resolve(strict=True)
    _require(root.is_dir() and root!=Path(origin_index_ref['path']).parent
             and not root.is_relative_to(Path(origin_index_ref['path']).parent), 'ACTION_REBIND_OUTPUT_NOT_ISOLATED')
    link={'schema':'v4.workbench.action_rebind_index.v1','origin_index':origin_index_ref,
          'summary':correction.get('summary'),'equivalence':receipt.get('action_correction_equivalence')}
    index={**origin,'candidate_generation':receipt.get('generation_id'),'candidate_input_sha256':receipt.get('input_sha256'),
           'pair_sha256':receipt.get('candidate_sha256'),'paired_receipt':paired_receipt_ref,
           'verified_pair':verified_pair_ref,'action_rebind':link}
    reuse=checked_action_rebind_index(index,require_producer=False)
    scope=reuse['stock_index'];summary=reuse['summary'];symbols=origin.get('symbols')
    _require(isinstance(symbols,dict) and all(isinstance(v,dict) for v in symbols.values())
             and all(code in scope for code,item in symbols.items() if item.get('status')=='READY')
             and sum(item.get('status')=='READY' for item in symbols.values())==summary.get('target_rows')
             and all(type(item.get('affected_rows')) is int and item['affected_rows']>=0 for item in scope.values())
             and sum(item['affected_rows'] for item in scope.values())==summary.get('changed_rows')
             and sum(item['affected_rows']>0 for item in scope.values())==summary.get('changed_stock_count'),
             'ACTION_REBIND_SCOPE_COUNT_CONFLICT')
    _require(shutil.disk_usage(root).free>=24*1024**3+64*1024**2,'ACTION_REBIND_DISK_RESERVE')
    producer=_write_immutable(root,'ACTION_REBIND_PRODUCER','.py',Path(__file__).resolve(strict=True).read_bytes(),full_hash=True)
    validator_path=Path(action_host.__file__).resolve(strict=True)
    consumer_path=Path(__file__).resolve(strict=True).parents[1]/'research-panel/workbench-host/kb-single-stock.mjs'
    validator=_write_immutable(root,'ACTION_REBIND_VALIDATOR','.py',validator_path.read_bytes(),full_hash=True)
    consumer=_write_immutable(root,'ACTION_REBIND_CONSUMER','.mjs',consumer_path.read_bytes(),full_hash=True)
    index['action_rebind']={**link,'producer':producer,'validator':validator,'consumer':consumer}
    identity={'schema':'v4.workbench.action_rebind_run.v1','origin_index':origin_index_ref,
              'paired_receipt':paired_receipt_ref,'verified_pair':verified_pair_ref,
              'summary':link['summary'],'equivalence':link['equivalence'],'producer':producer,
              'validator':validator,'consumer':consumer,**FLAGS}
    existing=list(root.glob('ACTION_REBIND_RUN_IDENTITY_*.json'))
    _require(not existing or len(existing)==1 and json.loads(existing[0].read_bytes())==identity,
             'ACTION_REBIND_RESUME_IDENTITY_CONFLICT')
    identity_ref=_write_immutable(root,'ACTION_REBIND_RUN_IDENTITY','.json',_canonical(identity),full_hash=True)
    return {'index':index,'reuse':reuse,'origin':origin,'output_root':str(root),'run_identity':identity_ref,
            'producer':producer,'validator':validator,'consumer':consumer}


def _action_values(values,contract):
    _require(len(values)==len(ACTION_REBIND_FIELDS) and values[0] in (None,'买入','卖出','持有','放飞','等回调')
             and values[2] in (None,'买入','卖出','持有','放飞','等回调')
             and isinstance(values[1],str) and bool(values[1]) and isinstance(values[3],str) and bool(values[3])
             and isinstance(values[4],str) and values[5]==contract, 'ACTION_REBIND_VALUE_INVALID')
    try:reasons=json.loads(values[4])
    except (TypeError,ValueError):raise ValueError('ACTION_REBIND_REASON_INVALID') from None
    _require(isinstance(reasons,list) and all(isinstance(value,str) for value in reasons),'ACTION_REBIND_REASON_INVALID')


def materialize_action_rebind_stock(context,symbol):
    """Create a thin binding plus already-calculated changed actions for one stock."""
    index=context['index'];reuse=context['reuse'];origin=context['origin'];root=Path(context['output_root'])
    selected=origin.get('symbols',{}).get(symbol);delta=reuse['stock_index'].get(symbol)
    _require(isinstance(selected,dict) and selected.get('status')=='READY' and isinstance(delta,dict),
             'ACTION_REBIND_SYMBOL_NOT_READY')
    old_ref=selected['binding'];stock=json.loads(_checked(old_ref,maximum=4*1024*1024).read_bytes())
    count=delta.get('affected_rows');_require(type(count) is int and 0<=count<=stock.get('rows',-1),
                                               'ACTION_REBIND_CHANGED_COUNT_INVALID')
    patch_ref=None;overlay_ref=delta.get('overlay')
    if count:
        source=_checked(overlay_ref,maximum=16*1024*1024)
        metadata=pq.ParquetFile(source).schema_arrow.metadata or {}
        _require(metadata.get(b'scope')==b'ACTION_DELTA_NOT_A_PANEL'
                 and metadata.get(b'old_candidate_generation')==origin['candidate_generation'].encode()
                 and metadata.get(b'old_action_authority_sha256')==reuse['summary']['old_action_authority_sha256'].encode()
                 and metadata.get(b'new_action_authority_sha256')==reuse['summary']['action_authority']['sha256'].encode(),
                 'ACTION_REBIND_OVERLAY_IDENTITY_CONFLICT')
        names=['ts_code','trade_date',*[prefix+field for field in ACTION_REBIND_FIELDS for prefix in ('old__','new__')]]
        table=pq.read_table(source,columns=names);rows=table.to_pylist()
        _require(len(rows)==count,'ACTION_REBIND_OVERLAY_COUNT_CONFLICT')
        by_date={};previous=0;date_set=set(stock['dates']);contract=stock['action_contract_sha256']
        changed_fields={field:0 for field in ACTION_REBIND_FIELDS}
        for row in rows:
            try:date=int(row['trade_date'])
            except (ValueError,TypeError,OverflowError):raise ValueError('ACTION_REBIND_DATE_INVALID') from None
            old=[row['old__'+field] for field in ACTION_REBIND_FIELDS]
            new=[row['new__'+field] for field in ACTION_REBIND_FIELDS]
            _require(row['ts_code']==symbol and str(date)==str(row['trade_date']) and date>previous and date in date_set
                     and any(not _same(a,b) for a,b in zip(old,new)), 'ACTION_REBIND_OVERLAY_DATE_CONFLICT')
            _action_values(old,contract);_action_values(new,contract)
            for field,before,after in zip(ACTION_REBIND_FIELDS,old,new):
                if not _same(before,after):changed_fields[field]+=1
            by_date[date]=(old,new);previous=date
        _require(changed_fields==delta.get('changed_fields'),'ACTION_REBIND_FIELD_COVERAGE_CONFLICT')
        positions=[stock['field_names'].index(field) for field in ACTION_REBIND_FIELDS];verified=set()
        for ref in stock['chunks']:
            relevant={date for date in by_date if ref['first_date']<=date<=ref['last_date']}
            if not relevant:continue
            chunk=json.loads(_bounded_gzip(ref,maximum=MAX_CHUNK_DECODED,compressed_maximum=MAX_CHUNK_COMPRESSED))
            _require(chunk.get('schema')=='v4.workbench.generic_single_chunk.v1' and chunk.get('symbol')==symbol
                     and chunk.get('candidate_generation')==origin['candidate_generation']
                     and chunk.get('candidate_input_sha256')==origin['candidate_input_sha256']
                     and chunk.get('source_input_sha256')==origin['input_sha256']
                     and len(chunk.get('rows',[]))==ref['row_count'],'ACTION_REBIND_ORIGIN_CHUNK_CONFLICT')
            for item in chunk['rows']:
                date=item[0]
                if date in relevant:
                    _require(isinstance(item,list) and len(item)==5 and isinstance(item[1],list)
                             and len(item[1])==len(stock['field_names'])
                             and all(_same(item[1][pos],value) for pos,value in zip(positions,by_date[date][0])),
                             'ACTION_REBIND_OLD_VALUE_CONFLICT')
                    verified.add(date)
        _require(verified==set(by_date),'ACTION_REBIND_OLD_DATE_COVERAGE_CONFLICT')
        payload={'schema':'v4.workbench.generic_action_patch.v1','symbol':symbol,
                 'origin_candidate_generation':origin['candidate_generation'],
                 'origin_candidate_input_sha256':origin['candidate_input_sha256'],
                 'candidate_generation':index['candidate_generation'],'candidate_input_sha256':index['candidate_input_sha256'],
                 'origin_binding_sha256':old_ref['sha256'],'source_overlay_sha256':overlay_ref['sha256'],
                 'equivalence_sha256':index['action_rebind']['equivalence']['sha256'],
                 'field_names':list(ACTION_REBIND_FIELDS),'rows':[[date,*by_date[date]] for date in sorted(by_date)],
                 'historical_PIT':False,**FLAGS}
        patch_ref=_packed(root,symbol.replace('.','_')+'_ACTION_PATCH',payload)
    else:_require(overlay_ref is None,'ACTION_REBIND_OVERLAY_UNEXPECTED')
    wrapper={'schema':'v4.workbench.generic_action_rebind.v1','symbol':symbol,'origin_binding':old_ref,
             'origin_projection_source_index':selected.get('projection_source_index'),
             'origin_candidate_generation':origin['candidate_generation'],
             'origin_candidate_input_sha256':origin['candidate_input_sha256'],
             'candidate_generation':index['candidate_generation'],'candidate_input_sha256':index['candidate_input_sha256'],
             'baseline_panel_sha256':origin['pair_sha256'],'candidate_sha256':index['pair_sha256'],
             'equivalence':index['action_rebind']['equivalence'],'summary':index['action_rebind']['summary'],
             'source_stock_receipt':delta['stock_receipt'],'source_overlay':overlay_ref,'action_patch':patch_ref,
             'action_patch_rows':count,'historical_PIT':False,**FLAGS}
    checked_action_rebind_stock(index,reuse,symbol,wrapper)
    binding=_write_immutable(root,symbol.replace('.','_')+'_ACTION_BINDING','.json',_canonical(wrapper))
    return {'status':'READY','binding':binding,'origin_projection_source_index':selected.get('projection_source_index'),
            'asset_bytes':binding['bytes']+(patch_ref['bytes'] if patch_ref else 0)}


_ACTION_REBIND_WORKER=None
def _action_rebind_worker_init(context):
    global _ACTION_REBIND_WORKER
    _ACTION_REBIND_WORKER=context


def _action_rebind_worker(symbol):
    return materialize_action_rebind_stock(_ACTION_REBIND_WORKER,symbol)


def _action_output_bytes(root):
    total=0
    for directory,_,files in os.walk(root,followlinks=False):
        for name in files:
            path=Path(directory)/name
            _require(not path.is_symlink(),'ACTION_REBIND_OUTPUT_SYMLINK')
            total+=path.stat().st_size
    return total


def run_action_rebind(context,*,workers=4,max_new=None):
    """Resumable metadata/changed-action views; never recalculate stored signals."""
    _require(type(workers) is int and 1<=workers<=4,'ACTION_REBIND_WORKER_LIMIT')
    _require(max_new is None or type(max_new) is int and max_new>0,'ACTION_REBIND_BATCH_LIMIT_INVALID')
    root=Path(context['output_root']);checkpoints=root/'symbol_receipts';checkpoints.mkdir(exist_ok=True)
    identity_sha=context['run_identity']['sha256'];results={};errors=[];stopped=None;submitted=0
    for path in checkpoints.glob('*_ACTION_REBIND_RESULT_*.json'):
        value=json.loads(path.read_bytes());symbol=value.get('symbol');result=value.get('result') or {}
        _require(symbol in context['origin']['symbols'] and value.get('run_identity_sha256')==identity_sha
                 and symbol not in results and result.get('status') in {'READY','FAILED'},
                 'ACTION_REBIND_RESUME_RECEIPT_CONFLICT')
        if result['status']=='READY':
            wrapper=json.loads(_checked(result['binding'],maximum=4*1024*1024).read_bytes())
            checked_action_rebind_stock(context['index'],context['reuse'],symbol,wrapper)
            if wrapper.get('action_patch'):_checked(wrapper['action_patch'],maximum=MAX_CHUNK_COMPRESSED)
        results[symbol]=result
    recorded_failures=[{'symbol':symbol,'reason':result.get('reason')} for symbol,result in results.items()
                       if result.get('status')=='FAILED']
    if recorded_failures:
        return {'status':'PARTIAL','stop_reason':'RECORDED_FAILURE_REQUIRES_DIAGNOSIS',
                'errors':recorded_failures,'run_identity':context['run_identity'],**FLAGS}
    pending=[symbol for symbol,item in sorted(context['origin']['symbols'].items())
             if item.get('status')=='READY' and symbol not in results]
    started=time.monotonic();last_health=0.0;last_size=0;pending_bytes=0;last_resources=None;futures={}
    def write_result(symbol,result):
        nonlocal stopped,pending_bytes
        value={'schema':'v4.workbench.action_rebind_symbol_receipt.v1','symbol':symbol,
               'run_identity_sha256':identity_sha,'result':result,**FLAGS}
        _write_immutable(checkpoints,symbol.replace('.','_')+'_ACTION_REBIND_RESULT','.json',_canonical(value))
        results[symbol]=result;pending_bytes+=int(result.get('asset_bytes') or 0)+4096
        if result.get('status')=='FAILED':errors.append({'symbol':symbol,'reason':result.get('reason')});stopped='SYMBOL_FAILURE'
    def drain(block=False):
        if not futures:return
        done,_=wait(futures,return_when=FIRST_COMPLETED,timeout=None if block else 0)
        for future in done:
            symbol=futures.pop(future)
            try:result=future.result()
            except BaseException as exc:result={'status':'FAILED','reason':type(exc).__name__+': '+str(exc)}
            write_result(symbol,result)
    multiprocessing.set_executable(sys.executable)
    pool=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),
                             initializer=_action_rebind_worker_init,initargs=(context,)) if pending else None
    try:
        for symbol in pending:
            while len(futures)>=workers and not stopped:drain(True)
            if stopped:break
            if max_new is not None and submitted>=max_new:stopped='BOUNDED_BATCH_LIMIT';break
            if time.monotonic()-last_health>=5:
                last_resources=_bulk_resources(root,[p.pid for p in multiprocessing.active_children() if p.pid],min_disk_gib=24)
                last_size=_action_output_bytes(root);pending_bytes=0;last_health=time.monotonic()
                if not last_resources['ok']:stopped=last_resources['reason'];break
                if last_size>=2*1024**3-64*1024**2:stopped='ACTION_REBIND_2_GIB_BUDGET';break
            if last_size+pending_bytes+len(futures)*6*1024**2>=2*1024**3-64*1024**2:
                stopped='ACTION_REBIND_2_GIB_BUDGET';break
            if shutil.disk_usage(root).free<24*1024**3+64*1024**2:stopped='ACTION_REBIND_DISK_RESERVE';break
            futures[pool.submit(_action_rebind_worker,symbol)]=symbol;submitted+=1
        while futures:drain(True)
    except (ValueError,OSError,KeyError,TypeError,pa.ArrowException) as exc:
        stopped='ACTION_REBIND_INPUT_FAILURE';errors.append({'symbol':None,'reason':type(exc).__name__+': '+str(exc)})
        while futures:drain(True)
    finally:
        if pool:pool.shutdown(wait=True)
    try:
        _require(q.sha(Path(__file__).resolve(strict=True))==context['producer']['sha256'],'ACTION_REBIND_PRODUCER_MOVED')
        _require(q.sha(Path(action_host.__file__).resolve(strict=True))==context['validator']['sha256']
                 and q.sha(Path(__file__).resolve(strict=True).parents[1]/'research-panel/workbench-host/kb-single-stock.mjs')
                     ==context['consumer']['sha256'], 'ACTION_REBIND_CONSUMER_MOVED')
        checked_action_rebind_index(context['index'])
        last_size=_action_output_bytes(root)
        _require(last_size<=2*1024**3,'ACTION_REBIND_2_GIB_BUDGET')
    except (ValueError,OSError,KeyError,TypeError) as exc:
        stopped='ACTION_REBIND_IDENTITY_OR_BUDGET_FAILURE';errors.append({'symbol':None,'reason':str(exc)})
    remaining=sorted(symbol for symbol,item in context['origin']['symbols'].items()
                     if item.get('status')=='READY' and (symbol not in results or results[symbol].get('status')!='READY'))
    summary={'schema':'v4.workbench.action_rebind_progress.v1','run_identity':context['run_identity'],
        'ready':sum(x.get('status')=='READY' for x in results.values()),'unfinished_count':len(remaining),
        'unfinished':remaining,'submitted_this_run':submitted,'asset_bytes_total':last_size,
        'elapsed_seconds':round(time.monotonic()-started,3),'stop_reason':stopped,'errors':errors,'resources':last_resources,**FLAGS}
    progress=_write_immutable(root,'ACTION_REBIND_PROGRESS','.json',_canonical(summary))
    if remaining or stopped or errors:return {'status':'PARTIAL','progress':progress,**summary}
    index=dict(context['index']);index['previous_index']=index['action_rebind']['origin_index']
    index['symbols']={symbol:(results[symbol] if item.get('status')=='READY' else item)
                      for symbol,item in context['origin']['symbols'].items()}
    index['action_rebind']={**index['action_rebind'],'producer':context['producer']}
    index_ref=_write_immutable(root,'GENERIC_SINGLE_INDEX','.json',_canonical(index))
    _require(_action_output_bytes(root)<=2*1024**3,'ACTION_REBIND_2_GIB_BUDGET')
    return {'status':'COMPLETE','index':index_ref,'progress':progress,**summary}
