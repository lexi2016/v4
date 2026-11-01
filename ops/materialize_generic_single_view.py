"""Offline single-view adapter over an already verified paired research panel.

The existing panel/daily owner invokes this bounded adapter after paired
completion. It does not fetch data, calculate KB signals, publish pointers,
start a service, or create a second research producer.
"""
from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from ops import research_panel_qfq as q
from ops import render_original_formula_projection as renderer
from ops.kb_hold_score import SUPPLEMENTAL_REASONS


FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
CHUNK_ROWS = 512
MAX_CHUNK_DECODED = 8 * 1024 * 1024
MAX_CHUNK_COMPRESSED = 2 * 1024 * 1024
MAX_PROJECTION_DECODED = 64 * 1024 * 1024
MAX_PROJECTION_COMPRESSED = 8 * 1024 * 1024
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
        with path.open('xb') as handle:
            handle.write(raw)
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
            shard_path=_checked(shard_ref,maximum=8*1024*1024);raw=shard_path.read_bytes();shard=json.loads(raw)
            expected={'symbol':symbol,'data_date':index['source_date'].replace('-',''),
                'observation_date':index['observation_date'],'source_generation':index['source_generation'],
                'input_sha256':index['input_sha256'],'source_candidate_generation':index['candidate_generation'],
                'candidate_input_sha256':index['candidate_input_sha256'],'numeric_manifest':index['numeric_manifest'],
                'paired_receipt':index['paired_receipt'],'verified_pair':index['verified_pair'],
                'projection_index':index_ref,'projection_binding':prior_ref,'history_input':binding['history_input'],
                'producer_sha256':history_producer_ref['sha256']}
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
