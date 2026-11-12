"""Read-only adapter for the existing workbench's bounded R3 stock assets."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlencode


FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
SHA=re.compile(r'^[0-9a-f]{64}$')
SYMBOL=re.compile(r'^\d{6}\.(SH|SZ|BJ)$')


def _read(ref):
    path=Path(ref['path']);expected=ref['sha256']
    if (not path.is_absolute() or path.is_symlink() or path.resolve(strict=True)!=path or not SHA.fullmatch(expected)):
        raise ValueError('R3_ASSET_REFERENCE_INVALID')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('R3_ASSET_SHA_DRIFT')
    if 'bytes' in ref and len(raw)!=ref['bytes']:raise ValueError('R3_ASSET_SIZE_DRIFT')
    return raw


def _stamp(ref):
    path=Path(ref['path'])
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True)!=path or not SHA.fullmatch(ref['sha256']):
        raise ValueError('R3_ASSET_REFERENCE_INVALID')
    s=path.stat()
    return (str(path),ref['sha256'],s.st_size,s.st_mtime_ns,s.st_ino)


@lru_cache(maxsize=4)
def _bundle(manifest_stamp,validation_stamp,lock_stamp,original_stamp):
    def read(stamp):return json.loads(_read({'path':stamp[0],'sha256':stamp[1]}))
    m,v,lock,original=map(read,(manifest_stamp,validation_stamp,lock_stamp,original_stamp))
    groups=lock.get('groups',{});inventory=sum((list(x) for x in groups.values()),[])
    rows=m.get('per_symbol',[]);items={r['symbol']:r for r in rows}
    unknown={r['symbol']:r for r in m.get('unknown_symbols',[])}
    original_rows=original.get('top200',[]);target=[r['symbol'] for r in original_rows]
    if (m.get('schema')!='v4.a_share.scoped_kb_r3_manifest.v1' or m.get('status')!='READY_FOR_INDEPENDENT_REVIEW'
        or m.get('processed_count')!=197 or m.get('rows')!=637839 or m.get('kb_field_count')!=107
        or m.get('calculation_columns')!={'selector':340,'backtest':192}
        or m.get('display_columns')!={'selector':317,'backtest':186} or len(items)!=197 or len(unknown)!=3
        or len(target)!=200 or len(set(target))!=200 or set(items)|set(unknown)!=set(target) or set(items)&set(unknown)
        or v.get('schema')!='v4.a_share.scoped_kb_r3_validation.v1' or v.get('status')!='PASS'
        or v.get('manifest_sha256')!=manifest_stamp[1] or v.get('generation')!=m.get('generation')
        or lock.get('schema')!='top200_user_field_decision_lock.r3' or len(inventory)!=107 or len(set(inventory))!=107
        or original_stamp[1]!='62f32398e8e89ecf7f3c48f8f803b4e6d154211f3871d12489be898a0e39b0a7'
        or any(m.get(k)!=value for k,value in FLAGS.items()) or m.get('historical_PIT') is not False):
        raise ValueError('R3_MANIFEST_IDENTITY_CONFLICT')
    return m,groups,original,items,unknown


def resolve(binding,view,current_top200,source_date,symbol):
    """Return a bound item or None when the existing legacy path owns it."""
    descriptor=binding.get('top200_research_panel_r3')
    if not descriptor or source_date!='2026-10-30' or not SYMBOL.fullmatch(symbol):return None
    stamps=[_stamp(descriptor[k]) for k in ('manifest','validation','field_lock','original_top200')]
    m,groups,original,items,unknown=_bundle(*stamps)
    # A stale Top200 publication must not affect the two pre-existing stocks
    # owned by the legacy binding. They do not belong to this scope.
    if symbol not in items and symbol not in unknown:return None
    old=[(x['symbol'],x.get('name')) for x in original['top200']]
    now=[(x['symbol'],x.get('name')) for x in current_top200.get('top200',[])]
    if (old!=now or original.get('data_date')!='20261030' or original.get('source_generation')!=view['source_generation']
        or original.get('input_sha256')!=view['source_identity']['input_sha256']
        or m['identity']['source_generation']!=view['source_generation']):
        raise ValueError('R3_LIVE_TOP200_OR_SOURCE_CONFLICT')
    return {'manifest':m,'groups':groups,'original':original,'stock':items.get(symbol),
            'unknown':unknown.get(symbol),'current_top200':current_top200.get('artifact'),
            'manifest_ref':descriptor['manifest']}


def metadata(binding,view,current_top200,source_date,symbol,observation_date):
    resolved=resolve(binding,view,current_top200,source_date,symbol)
    if resolved is None:return None
    m=resolved['manifest'];stock=resolved['stock'];name=next(x.get('name') for x in resolved['original']['top200'] if x['symbol']==symbol)
    common={'schema':'v4.workbench.scoped_kb_research.v1','source_date':source_date,'observation_date':observation_date,
        'symbol':symbol,'name':name,'generation':view['source_generation'],'input_sha256':view['source_identity']['input_sha256'],
        'numeric_manifest':view['manifest'],'candidate_pool_member':any(r.get('symbol')==symbol for r in view.get('rows',[])),
        'panel_generation':m['generation'],'panel_manifest_sha256':resolved['manifest_ref']['sha256'],
        'original_top200_sha256':'62f32398e8e89ecf7f3c48f8f803b4e6d154211f3871d12489be898a0e39b0a7',
        'current_top200_artifact':resolved['current_top200'],'historical_PIT':False,**FLAGS}
    if stock is None:return dict(common,status='UNKNOWN_SOURCE_ADMISSION',reason=resolved['unknown'].get('reason'))
    base=f'/api/v4/research/workbench/days/{source_date}/single-research/{symbol}/assets/'
    refs=stock['assets'];assets={}
    kinds=('selector','backtest','events','company')+(('diagnostics',) if 'diagnostics' in refs else ())
    for kind in kinds:
        ref=refs[kind]
        if not SHA.fullmatch(ref.get('sha256','')) or not isinstance(ref.get('bytes'),int):raise ValueError('R3_STOCK_ASSET_INVALID')
        assets[kind]={'sha256':ref['sha256'],'bytes':ref['bytes'],
                      'url':base+kind+'?'+urlencode({'revision':view['source_generation'],'panel_revision':m['generation'],'sha256':ref['sha256']})}
    for kind in ('dates','row-'+str(stock['last_date'])):
        assets[kind]={'sha256':refs['selector']['sha256'],
                      'url':base+kind+'?'+urlencode({'revision':view['source_generation'],'panel_revision':m['generation'],'sha256':refs['selector']['sha256']})}
    alignment=m.get('identity',{}).get('manual_alignment') or {}
    return dict(common,status='READY_FOR_RESEARCH_REVIEW',rows=stock['rows'],first_date=stock['first_date'],last_date=stock['last_date'],
        fields_count=107,field_inventory=resolved['groups'],field_labels={'kb_hold_volume_ok':'持仓评分·量能项'},calculation_columns=m['calculation_columns'],
        display_columns=m['display_columns'],f10_status=stock['f10_status'],concept_observed_at=stock.get('concept_observed_at'),
        n_rule_sha256=alignment.get('n_contract_sha256'),n_helper_sha256=alignment.get('n_authority_sha256'),
        score_contract_sha256=alignment.get('score_contract_sha256'),assets=assets)


def _json_value(value):
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,list):return [_json_value(x) for x in value]
    if isinstance(value,dict):return {k:_json_value(v) for k,v in value.items()}
    return value


def asset(binding,view,current_top200,source_date,symbol,kind,digest):
    resolved=resolve(binding,view,current_top200,source_date,symbol)
    if resolved is None or resolved['stock'] is None:raise KeyError('R3_STOCK_NOT_BOUND')
    stock=resolved['stock'];refs=stock['assets']
    role='selector' if kind=='dates' or re.fullmatch(r'row-\d{8}',kind) else kind
    if role not in ('selector','backtest','events','company','diagnostics') or role not in refs:raise KeyError('R3_STOCK_ASSET_NOT_BOUND')
    ref=refs[role]
    if digest!=ref['sha256']:raise ValueError('R3_STOCK_ASSET_SHA_CONFLICT')
    raw=_read(ref)
    if kind in ('selector','backtest','events','diagnostics'):return raw,'application/vnd.apache.parquet'
    if kind=='company':
        value=json.loads(raw)
        if value.get('symbol')!=symbol or value.get('historical_PIT') is not False:raise ValueError('R3_COMPANY_IDENTITY_CONFLICT')
        return raw,'application/json'
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    file=pq.ParquetFile(pa.BufferReader(raw))
    if file.metadata.num_rows!=stock['rows'] or len(file.schema_arrow.names)!=317:raise ValueError('R3_SELECTOR_SCHEMA_CONFLICT')
    dates=[int(x) for x in file.read(columns=['trade_date']).column(0).to_pylist()]
    if len(dates)!=len(set(dates)) or dates!=sorted(dates) or dates[0]!=stock['first_date'] or dates[-1]!=stock['last_date']:
        raise ValueError('R3_SELECTOR_DATES_CONFLICT')
    value={'schema':'v4.workbench.scoped_kb_asset.v1','symbol':symbol,'source_date':source_date,
           'panel_generation':resolved['manifest']['generation'],'source_generation':view['source_generation'],
           'selector_sha256':ref['sha256'],'historical_PIT':False,**FLAGS}
    if kind=='dates':value.update(rows=len(dates),dates=dates)
    else:
        day=int(kind[4:])
        if day not in dates:raise KeyError('R3_TRADE_DATE_NOT_IN_HISTORY')
        table=file.read();row=table.slice(dates.index(day),1).to_pylist()[0]
        if row.get('ts_code')!=symbol or int(row.get('trade_date'))!=day:raise ValueError('R3_STOCK_ROW_CONFLICT')
        value.update(trade_date=day,column_count=317,fields=_json_value(row),
                     concept_observed_at=stock.get('concept_observed_at') if day==stock['last_date'] else None)
        if 'diagnostics' in refs:
            diagnostics=pq.ParquetFile(pa.BufferReader(_read(refs['diagnostics'])))
            if diagnostics.metadata.num_rows!=stock['rows']:
                raise ValueError('R4_DIAGNOSTICS_ROWS_CONFLICT')
            info=diagnostics.read().slice(dates.index(day),1).to_pylist()[0]
            if info.get('ts_code')!=symbol or int(info.get('trade_date'))!=day:
                raise ValueError('R4_DIAGNOSTICS_KEY_CONFLICT')
            value.update(diagnostics=json.loads(info['diagnostics_json']),
                         kb_n_structure=json.loads(info['n_structure_json']),
                         diagnostics_sha256=refs['diagnostics']['sha256'])
    return (json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode(),'application/json'
