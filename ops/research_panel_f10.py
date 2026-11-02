"""Bounded TDX F10 continuation of the existing A daily completion owner.

This adapter reuses the pinned local F10 collectors.  It stores observed
snapshots, never rewrites formula panels or assigns current F10 to past days.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime, timezone
import base64
import csv
import hashlib
import importlib
import io
import json
import math
import os
from pathlib import Path
import re
import struct

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
VENDOR = {
    'tdx_f10_fetch_existing.py': '86d80dec56e78f9842fdb954a0d49d9e5b5a1f2d86f2a6acb7eb095713d00c68',
    'tdx_f10_concepts_existing.py': 'c0d92c2e7c8409d673a03c029b1d251ab6338a3183eec285c3912be4f47f66d2',
}
HOSTS = (('115.238.90.165', 7709), ('119.147.212.81', 7709), ('101.227.73.20', 7709))
# For BJ the existing TDX F10 endpoints use different market selectors.
# The security still comes from the bound panel exchange, never its digits.
MARKET = {'SZ': 0, 'SH': 1, 'BJ': 2}
F10_TEXT_MARKET = {'BJ': 0}
F10_CONTENT_CHUNK_BYTES = 30720  # Conservative bound observed on this server; not a protocol claim.
F10_CONTENT_MAX_BYTES = 1024 * 1024


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_ref(ref):
    path = Path(ref['path'])
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError('F10_REFERENCE_PATH_INVALID')
    raw = path.read_bytes()
    if _sha(raw) != ref['sha256']:
        raise ValueError('F10_REFERENCE_SHA_DRIFT')
    return raw


def _write(path, obj, *, immutable=False):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if immutable and path.exists():
        if path.read_bytes() != raw: raise ValueError('F10_IMMUTABLE_CONFLICT')
    else:
        tmp = path.with_name('.' + path.name + '.' + str(os.getpid()) + '.pending')
        with tmp.open('xb') as out:
            out.write(raw); out.flush(); os.fsync(out.fileno())
        os.replace(tmp, path)
    return {'path': str(path.resolve()), 'sha256': _sha(raw)}


def _vendors():
    root = Path(__file__).resolve().parent / 'vendor'
    for name, expected in VENDOR.items():
        if _sha((root / name).read_bytes()) != expected: raise ValueError('F10_VENDOR_SHA_DRIFT:' + name)
    # The modules' main functions are never called: the old hardcoded output
    # location and full-market loop remain inactive.
    return (importlib.import_module('ops.vendor.tdx_f10_fetch_existing'),
            importlib.import_module('ops.vendor.tdx_f10_concepts_existing'))


def _concept_section(text):
    marker='【3.概念板块】'; start=text.rfind(marker)
    if start < 0: return None
    match=re.search(r'【[4-9]\.\S*?】', text[start+len(marker):])
    end=start+len(marker)+match.start() if match else len(text)
    return text[start:end]


def _safe_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)): return None
    return value if math.isfinite(value) else None


def _safe_vendor_grab(fetch, text, label):
    """A missing numeric cell must not discard an otherwise verified F10 item."""
    try:
        return _safe_number(fetch.grab(text, label))
    except (TypeError, ValueError, OverflowError):
        return None


def _bj_financials(text, updated):
    """Use one dated TDX table column; placeholders and undated values stay unknown."""
    lines=text.splitlines();header=next((line for line in lines if '★最新主要指标★' in line and '｜' in line),None)
    labels={'eps':'每股收益(元)','bps':'每股净资产(元)','roe_pct':'净资产收益率(%)'}
    result={'report_period':None,'holder_count':None,'holder_count_status':'SOURCE_PERIOD_UNBOUND',
            'eps':None,'bps':None,'roe_pct':None,'revenue_text':None,'net_profit_text':None,
            'net_profit_scope':'SOURCE_LABEL_NET_PROFIT_PARENT_SCOPE_UNCONFIRMED'}
    if not header or not updated:return result
    try:updated_day=date.fromisoformat(updated)
    except (ValueError,TypeError):return result
    cells=lambda line:[part.strip() for part in line.strip().strip('｜').split('｜')]
    columns=cells(header)[1:];value_rows={}
    for line in lines:
        if not line.lstrip().startswith('｜'):continue
        parts=cells(line)
        for key,label in labels.items():
            if parts and parts[0]==label:value_rows[key]=parts[1:]
    for i,period in enumerate(columns):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',period):continue
        try:period_day=date.fromisoformat(period)
        except ValueError:continue
        if period_day>updated_day:continue
        values={}
        for key in labels:
            row=value_rows.get(key,[]);raw=row[i] if i<len(row) else ''
            values[key]=_safe_number(float(raw)) if re.fullmatch(r'[+-]?\d+(?:\.\d+)?',raw) else None
        if not any(value is not None for value in values.values()):continue
        result.update(report_period=period,**values)
        for line in lines:
            if not re.match(r'^\s*｜?\s*'+re.escape(period)+r'\b',line):continue
            for key,label in (('revenue_text','营业总收入(元)'),('net_profit_text','净利润(元)')):
                match=re.search(re.escape(label)+r'\s*[:：]\s*([^\s｜]+)',line)
                if match:result[key]=match.group(1)
        break
    return result


def _read_company_text(api,market,code,category,*,command_factory=None):
    """Read exact SDK payload byte ranges, then decode the complete GBK body once."""
    start=category.get('start');length=category.get('length');filename=category.get('filename')
    if (type(start) is not int or start<0 or type(length) is not int or not 0<length<=F10_CONTENT_MAX_BYTES
        or not isinstance(filename,str) or not filename):
        raise ValueError('F10_CONTENT_RANGE_INVALID')
    if command_factory is None:
        from pytdx.parser.get_company_info_content import GetCompanyInfoContent
        class RawContent(GetCompanyInfoContent):
            def parseResponse(self, body):
                if len(body)<12:raise ValueError('F10_CONTENT_RESPONSE_HEADER_SHORT')
                _,size=struct.unpack('<10sH',body[:12])
                if size>len(body)-12:raise ValueError('F10_CONTENT_RESPONSE_BODY_SHORT')
                return bytes(body[12:12+size])
        command_factory=RawContent
    chunks=[];offset=0
    while offset<length:
        size=min(F10_CONTENT_CHUNK_BYTES,length-offset)
        command=command_factory(api.client,lock=api.lock)
        command.setParams(market,code,filename,start+offset,size)
        raw=command.call_api()
        if not isinstance(raw,bytes) or len(raw)!=size:raise ValueError('F10_CONTENT_SHORT_READ')
        chunks.append(raw);offset+=size
    raw=b''.join(chunks)
    try:text=raw.decode('gbk',errors='strict')
    except UnicodeDecodeError:raise ValueError('F10_CONTENT_GBK_INVALID') from None
    return text.replace('\x00',''),{'declared_bytes':length,'received_bytes':len(raw),
        'raw_sha256':_sha(raw),'raw_base64':base64.b64encode(raw).decode('ascii'),
        'encoding':'GBK_STRICT_AFTER_REASSEMBLY','range_limit_bytes':F10_CONTENT_CHUNK_BYTES,
        'chunk_count':len(chunks)}


def fetch_one(symbol, exchange, *, api_factory=None, vendor=None):
    if exchange is None:
        return {'symbol':symbol, 'exchange':None, 'status':'SOURCE_IDENTITY_UNAVAILABLE', 'reason':'BOUND_PANEL_EXCHANGE_MISSING'}
    if exchange not in MARKET:
        return {'symbol':symbol, 'exchange':exchange, 'status':'UNSUPPORTED_EXCHANGE', 'reason':'TDX_MARKET_MAPPING_UNCERTIFIED'}
    if not isinstance(symbol,str) or not re.fullmatch(r'\d{6}\.'+re.escape(exchange),symbol):
        return {'symbol':symbol, 'exchange':exchange, 'status':'SOURCE_IDENTITY_CONFLICT', 'reason':'BOUND_EXCHANGE_SYMBOL_MISMATCH'}
    fetch, _ = vendor or _vendors(); api = (api_factory or fetch.TdxHq_API)(); connected = None
    try:
        for host in HOSTS:
            try:
                if api.connect(*host): connected=host; break
            except Exception: continue
        if connected is None: raise RuntimeError('TDX_CONNECTION_FAILED')
        code=symbol.split('.')[0]; market=MARKET[exchange]; text_market=F10_TEXT_MARKET.get(exchange,market)
        if exchange=='BJ':
            # Preserve independently verified parts if only one endpoint works.
            # Incomplete items remain PARTIAL and are not cached as completed.
            text_component={'status':'UNKNOWN'}; finance_component={'status':'UNKNOWN'}
            try:
                categories=api.get_company_info_category(text_market,code)
                if not categories:raise RuntimeError('F10_CATEGORY_MISSING')
                category=categories[0]
                text,content_proof=_read_company_text(api,text_market,code,category)
                if not re.search(r'◇'+re.escape(code)+r'\s+[^◇\n]+?\s+更新日期[：:]',text[:300]):
                    raise RuntimeError('F10_TEXT_IDENTITY_MISMATCH')
                text_component={'status':'OBSERVED','market':text_market,'category':category,
                                'source_text':text,'source_text_sha256':_sha(text.encode()),
                                'content_proof':content_proof}
            except Exception as error:
                text_component={'status':'UNKNOWN','reason':type(error).__name__+': '+str(error)}
            try:
                finance=api.get_finance_info(market,code)
                if not isinstance(finance,dict) or str(finance.get('code') or '')!=code or finance.get('market')!=market:
                    raise RuntimeError('F10_FINANCE_IDENTITY_MISMATCH')
                finance_component={'status':'OBSERVED','market':market,'finance_native_raw':{
                    str(k):_safe_number(v) if isinstance(v,(float,int)) else v for k,v in finance.items()}}
            except Exception as error:
                finance_component={'status':'UNKNOWN','reason':type(error).__name__+': '+str(error)}
            if text_component['status']!='OBSERVED' or finance_component['status']!='OBSERVED':
                observed=sum(c['status']=='OBSERVED' for c in (text_component,finance_component))
                return {'symbol':symbol,'exchange':exchange,'status':'PARTIAL' if observed else 'FAILED',
                    'reason':'F10_COMPONENTS_INCOMPLETE','captured_at':datetime.now(timezone.utc).isoformat(),
                    'server':f'{connected[0]}:{connected[1]}','source_components':{'text':text_component,'finance':finance_component},
                    'historical_PIT':False,**FLAGS}
        else:
            categories=api.get_company_info_category(text_market, code)
            if not categories: raise RuntimeError('F10_CATEGORY_MISSING')
            category=categories[0]
            text,content_proof=_read_company_text(api,text_market,code,category)
            if not re.search(r'◇'+re.escape(code)+r'\s+[^◇\n]+?\s+更新日期[：:]',text[:300]):
                raise RuntimeError('F10_TEXT_IDENTITY_MISMATCH')
            finance=api.get_finance_info(market,code)
            if not isinstance(finance,dict) or str(finance.get('code') or '')!=code or finance.get('market')!=market:
                raise RuntimeError('F10_FINANCE_IDENTITY_MISMATCH')
        section=_concept_section(text); concepts=fetch.concepts_from(section) if section is not None else []
        period=re.search(r'★最新主要指标★\s*｜\s*(\d{4}-\d{2}-\d{2})',text)
        updated=re.search(r'更新日期[：:]\s*(\d{4}-\d{2}-\d{2})',text[:300])
        name=re.search(r'◇'+re.escape(code)+r'\s+([^◇\n]+?)\s+更新日期',text[:300])
        income=re.search(r'营业总收入\(元\)\s*[:：]\s*([^\s｜]+)',text)
        net=re.search(r'净利润\(元\)\s*[:：]\s*([^\s｜]+)',text)
        financials=(_bj_financials(text,updated.group(1) if updated else None) if exchange=='BJ' else
            {'report_period':period.group(1) if period else None,
             'holder_count':_safe_number(finance.get('gudongrenshu')),
             'eps':_safe_vendor_grab(fetch,text,'每股收益(元)'),'bps':_safe_vendor_grab(fetch,text,'每股净资产(元)'),
             'roe_pct':_safe_vendor_grab(fetch,text,'净资产收益率(%)'),
             'revenue_text':income.group(1) if income else None,'net_profit_text':net.group(1) if net else None})
        if exchange!='BJ' and all(financials[k] is None for k in ('eps','bps','roe_pct')):
            # Some SH/SZ texts lead with a dated column of '-' placeholders.
            # Only combine values and revenue from the same actual dated column.
            dated=_bj_financials(text,updated.group(1) if updated else None)
            if dated['report_period'] is not None:financials=dated
            else:
                financials.update(report_period=None,holder_count=None,revenue_text=None,net_profit_text=None,
                                  holder_count_status='SOURCE_PERIOD_UNBOUND')
        data={'symbol':symbol,'exchange':exchange,'status':'OBSERVED',
              'captured_at':datetime.now(timezone.utc).isoformat(),'server':f'{connected[0]}:{connected[1]}',
              'category':{'name':category.get('name'),'filename':category.get('filename'),
                          'start':category.get('start'),'length':category.get('length')},
              'source_text_sha256':_sha(text.encode()),'source_text':text,
              'source_updated_date':updated.group(1) if updated else None,
              'finance_updated_date':str(finance.get('updated_date') or '') or None,
              'name':name.group(1).strip() if name else None,
              'content_proof':content_proof,
              'concepts':concepts,'concept_status':'OBSERVED' if section is not None and concepts else 'UNKNOWN_EMPTY_OR_UNPARSED',
              'industry':{'tdx_finance_industry_code':finance.get('industry'),'name':None,'status':'CODE_ONLY_NAME_UNMAPPED'},
              'financials':financials,
              'finance_native_raw':{str(k):_safe_number(v) if isinstance(v,(float,int)) else v for k,v in finance.items()},
              'historical_PIT':False,**FLAGS}
        if exchange=='BJ':data['endpoint_markets']={'text':text_market,'finance':market}
        return data
    except Exception as error:
        return {'symbol':symbol,'exchange':exchange,'status':'FAILED','reason':type(error).__name__+': '+str(error),
                'captured_at':datetime.now(timezone.utc).isoformat(),'historical_PIT':False,**FLAGS}
    finally:
        try:api.disconnect()
        except Exception:pass


def bound_universe(context, requested=None):
    """Read the admitted producer universe and its explicit exchange column once."""
    scope=set(context.scope); selected=scope if requested is None else set(requested)
    if not selected or not selected <= scope: raise ValueError('F10_REQUEST_OUTSIDE_DAILY_SCOPE')
    names=pa.array(sorted(selected)); observed={}
    for batch in pq.ParquetFile(context.panel).iter_batches(columns=['ts_code','exchange'],batch_size=131072):
        batch=batch.filter(pc.is_in(batch.column(0),value_set=names))
        for row in batch.to_pylist():
            code,exchange=row['ts_code'],row['exchange']
            if exchange in ('SH','SZ','BJ'):
                if not isinstance(code,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',code) or not code.endswith('.'+exchange):
                    raise ValueError('F10_EXCHANGE_CODE_CONFLICT:'+str(code))
                if code in observed and observed[code]!=exchange: raise ValueError('F10_EXCHANGE_CONFLICT:'+code)
                observed[code]=exchange
    return {symbol:observed.get(symbol) for symbol in sorted(selected)}


def bound_research_universe(context, *, listing_ref, exception_ref, requested=None):
    """Bind a candidate scope to the original snapshot and verified lifecycle additions.

    This is an isolated research scope, not an update of the daily product's
    original scope, index, or trading eligibility.
    """
    from infrastructure.research_workbench_host import checked_action_rebind_index
    listing=json.loads(_read_ref(listing_ref));exceptions=json.loads(_read_ref(exception_ref))
    source=listing.get('inputs') or {};exception_sources=exceptions.get('source_refs') or {}
    if (listing.get('status')!='CHECKED_EXISTING_LISTING_AND_CANDIDATE_BARS' or listing.get('failed')
        or not (exceptions.get('status')=='ALL_MATCH_EXISTING_RECORDS'
                or isinstance(exceptions.get('status'),str) and
                re.fullmatch(r'ALL_\d+_MATCH_EXISTING_RECORDS',exceptions['status']))
        or exceptions.get('target_date')!=datetime.strptime(str(context.target),'%Y%m%d').strftime('%Y-%m-%d')
        or source.get('snapshot')!=context.snapshot_ref or exception_sources.get('adjustment_snapshot')!=context.snapshot_ref
        or source.get('g2_index')!=exception_sources.get('g2_candidate_index')
        or any(document.get('historical_PIT',False) is not False or any(document.get(k) is not v for k,v in FLAGS.items())
               for document in (listing,exceptions))):
        raise ValueError('F10_RESEARCH_SCOPE_PROOF_CONFLICT')
    for ref in [*source.values(),*exception_sources.values()]:_read_ref(ref)
    index=json.loads(_read_ref(source['g2_index']))
    reuse=checked_action_rebind_index(index,require_producer=False)
    if (reuse is None or index.get('source_date','').replace('-','')!=str(context.target)
        or index.get('source_generation')!=context.generation
        or index.get('input_sha256')!=context.identity['input_sha256']):
        raise ValueError('F10_RESEARCH_SCOPE_PARENT_CONFLICT')
    symbols=index.get('symbols') or {};original=set(context.scope)
    if not original<=set(symbols):raise ValueError('F10_RESEARCH_SCOPE_MISSING_ORIGINAL')
    additions={item.get('symbol'):item for item in listing.get('items',[])}
    if len(additions)!=len(listing.get('items',[])) or set(symbols)-original!=set(additions):
        raise ValueError('F10_RESEARCH_SCOPE_ADDITIONS_CONFLICT')
    extra_rows=list(csv.DictReader(io.StringIO(_read_ref(source['g2_extra_csv']).decode('utf-8-sig'))))
    extra_by_symbol={row.get('symbol'):row for row in extra_rows}
    if len(extra_rows)!=len(extra_by_symbol) or set(extra_by_symbol)!=set(additions):
        raise ValueError('F10_RESEARCH_SCOPE_EXTRA_INDEX_CONFLICT')
    required_checks={'official_pdf_sha_matches','listing_page_contains_code','listing_page_contains_date',
        'listing_page_contains_exchange','listing_date_no_later_than_target','native_candidate_sha_matches',
        'source30_reported_valid_ohlcv','g2_binding_sha_matches_csv','g2_candidate_status_ready'}
    for symbol,item in additions.items():
        exchange=item.get('exchange');bar=item.get('source30_bar') or {};checks=item.get('checks') or {};extra=extra_by_symbol[symbol]
        if (not isinstance(symbol,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',symbol)
            or not symbol.endswith('.'+str(exchange)) or type(item.get('listing_date')) is not int
            or item['listing_date']>context.target or symbols[symbol].get('status')!='READY'
            or not required_checks<=set(checks) or not all(checks[k] is True for k in required_checks)
            or extra.get('market')!=exchange or extra.get('g2_status')!='READY'
            or extra.get('g2_binding_sha256')!=symbols[symbol].get('binding',{}).get('sha256')
            or bar.get('valid_ohlcv') is not True
            or any(isinstance(bar.get(k),bool) or not isinstance(bar.get(k),(int,float))
                   or not math.isfinite(bar[k]) or bar[k]<=0
                   for k in ('open','high','low','close','volume_shares','amount'))
            or not bar['low']<=min(bar['open'],bar['close'])<=max(bar['open'],bar['close'])<=bar['high']):
            raise ValueError('F10_RESEARCH_SCOPE_ADDITION_INVALID:'+str(symbol))
        try:datetime.strptime(str(item['listing_date']),'%Y%m%d')
        except ValueError:raise ValueError('F10_RESEARCH_SCOPE_LISTING_DATE_INVALID:'+symbol) from None
        if not _read_ref(item['issuer_pdf']).startswith(b'%PDF-'):
            raise ValueError('F10_RESEARCH_SCOPE_LISTING_SOURCE_INVALID:'+symbol)
        _read_ref(item['native_candidate'])
    unknown={k for k,v in symbols.items() if v.get('status')=='UNKNOWN'}
    disposition={item.get('symbol'):item for item in exceptions.get('items',[])}
    if (len(disposition)!=len(exceptions.get('items',[])) or unknown!=set(disposition)
        or exceptions.get('counts',{}).get('unmatched')!=0
        or exceptions.get('counts',{}).get('unknown_covered_by_snapshot_and_original_progress')!=len(unknown)
        or any(item.get('g2_status')!='UNKNOWN' or item.get('snapshot_reason_match') is not True
               or item.get('owner_fact_matches') is not True for item in disposition.values())):
        raise ValueError('F10_RESEARCH_SCOPE_EXCEPTION_CONFLICT')
    ready={k for k,v in symbols.items() if v.get('status')=='READY'}
    if ready|unknown!=set(symbols) or ready&unknown:raise ValueError('F10_RESEARCH_SCOPE_STATUS_INVALID')
    pair=json.loads(_read_ref(index['paired_receipt']))
    selector=pair['candidates']['selector']
    date_type=pq.ParquetFile(selector).schema_arrow.field('trade_date').type
    if pa.types.is_string(date_type) or pa.types.is_large_string(date_type):target_date=str(context.target)
    elif pa.types.is_integer(date_type):target_date=context.target
    else:raise ValueError('F10_RESEARCH_SCOPE_DATE_TYPE_INVALID')
    target=pq.read_table(selector,columns=['ts_code','exchange','trade_date'],
                         filters=[('trade_date','=',target_date)]).to_pylist()
    universe={row['ts_code']:row['exchange'] for row in target}
    if (len(universe)!=len(target) or set(universe)!=ready
        or any(exchange not in ('SH','SZ','BJ') or not symbol.endswith('.'+exchange)
               for symbol,exchange in universe.items())):
        raise ValueError('F10_RESEARCH_SCOPE_TARGET_BAR_CONFLICT')
    selected=ready if requested is None else set(requested)
    if not selected or not selected<=ready:raise ValueError('F10_REQUEST_OUTSIDE_DAILY_SCOPE')
    return {symbol:universe[symbol] for symbol in sorted(selected)},dict(
        kind='G2_RESEARCH_TARGET_READY',listing_reconciliation=listing_ref,exception_reconciliation=exception_ref,
        parent_index=source['g2_index'],original_snapshot=context.snapshot_ref,
        original_count=len(original),additional_count=len(additions),excluded_count=len(unknown),
        all_candidate_codes=len(symbols),target_ready_count=len(ready),
        additional_listing_independent_review='PENDING',historical_PIT=False,**FLAGS)


def _contains_ref(value,ref):
    if isinstance(value,dict):
        if value.get('path')==ref.get('path') and value.get('sha256')==ref.get('sha256'):return True
        return any(_contains_ref(v,ref) for v in value.values())
    return isinstance(value,list) and any(_contains_ref(v,ref) for v in value)


def _reference_pairs(value):
    pairs=set();stack=[value]
    while stack:
        current=stack.pop()
        if isinstance(current,dict):
            if isinstance(current.get('path'),str) and isinstance(current.get('sha256'),str):
                pairs.add((current['path'],current['sha256']))
            stack.extend(current.values())
        elif isinstance(current,list):stack.extend(current)
    return pairs


def _verified_observation(universe,symbol,ref):
    if symbol not in universe:raise ValueError('F10_REUSE_SCOPE_CONFLICT')
    stock=json.loads(_read_ref(ref));text=stock.get('source_text');exchange=universe[symbol]
    finance=stock.get('finance_native_raw') or {};expected_market=MARKET[exchange]
    if (stock.get('symbol')!=symbol or stock.get('exchange')!=exchange or stock.get('status')!='OBSERVED'
        or stock.get('historical_PIT') is not False or any(stock.get(k) is not v for k,v in FLAGS.items())
        or not isinstance(stock.get('captured_at'),str) or not isinstance(text,str)
        or _sha(text.encode())!=stock.get('source_text_sha256')
        or not re.search(r'◇'+re.escape(symbol.split('.')[0])+r'\s+[^◇\n]+?\s+更新日期[：:]',text[:300])
        or str(finance.get('code') or '')!=symbol.split('.')[0] or finance.get('market')!=expected_market):
        raise ValueError('F10_REUSE_SOURCE_IDENTITY_CONFLICT:'+symbol)
    proof=stock.get('content_proof')
    if proof is not None:
        try:
            raw=base64.b64decode(proof['raw_base64'],validate=True)
            decoded=raw.decode('gbk',errors='strict').replace('\x00','')
        except (KeyError,ValueError,TypeError,UnicodeDecodeError):
            raise ValueError('F10_REUSE_CONTENT_PROOF_INVALID:'+symbol) from None
        if (proof.get('encoding')!='GBK_STRICT_AFTER_REASSEMBLY'
            or proof.get('declared_bytes')!=proof.get('received_bytes') or proof.get('received_bytes')!=len(raw)
            or proof.get('declared_bytes')!=stock.get('category',{}).get('length')
            or proof.get('raw_sha256')!=_sha(raw) or decoded!=text):
            raise ValueError('F10_REUSE_CONTENT_PROOF_INVALID:'+symbol)
    return stock


def verified_reuse_sources(universe, seed_ref):
    """Reuse SHA-checked current observations with their original provenance."""
    seed=json.loads(_read_ref(seed_ref));items=seed.get('items')
    if (seed.get('schema')!='v4.a_share.f10_reuse_inputs.v1' or not isinstance(items,list)
        or seed.get('historical_PIT') is not False or any(seed.get(k) is not v for k,v in FLAGS.items())):
        raise ValueError('F10_REUSE_MANIFEST_CONFLICT')
    origins={};selected={};lineage={}
    for item in items:
        symbol=item.get('symbol');ref=item.get('ref');origin=item.get('origin')
        if symbol not in universe or not isinstance(ref,dict) or not isinstance(origin,dict):
            raise ValueError('F10_REUSE_SCOPE_CONFLICT')
        key=(origin.get('path'),origin.get('sha256'))
        if key not in origins:origins[key]=_reference_pairs(json.loads(_read_ref(origin)))
        if (ref.get('path'),ref.get('sha256')) not in origins[key]:raise ValueError('F10_REUSE_ORIGIN_UNBOUND:'+symbol)
        _verified_observation(universe,symbol,ref)
        if symbol in selected and selected[symbol]['sha256']!=ref['sha256']:
            raise ValueError('F10_REUSE_SOURCE_CONFLICT:'+symbol)
        selected[symbol]=ref;lineage.setdefault(symbol,[]).append(origin)
    return selected,lineage


def _isolated_sample_upstream(context, receipt_ref, receipt, output_root, isolated_root, requested):
    """Bind a real sample product manifest without claiming full daily completion."""
    from ops.research_panel_qfq import _validate_full_research_isolation
    isolated=_validate_full_research_isolation(isolated_root,context.data_root,output_root,
        {'selector':context.pointer,'backtest':context.backpointer})
    if (requested is None or not Path(receipt_ref['path']).resolve().is_relative_to(isolated)
            or receipt.get('schema_version')!='v4.a_share.daily_product_manifest.v1'
            or receipt.get('sample_only') is not True or receipt.get('data_date')!=str(context.target)
            or receipt.get('source_generation')!=context.generation or receipt.get('input_sha256')!=context.identity['input_sha256']
            or receipt.get('processed_count')!=len(set(requested)) or receipt.get('source_universe_count')!=len(context.scope)
            or any(receipt.get(k)!=v for k,v in FLAGS.items())):
        raise ValueError('F10_ISOLATED_SAMPLE_MANIFEST_CONFLICT')
    artifact_ref=receipt.get('artifact') or {}
    if not Path(artifact_ref.get('path','')).resolve().is_relative_to(isolated):
        raise ValueError('F10_ISOLATED_SAMPLE_ARTIFACT_ESCAPE')
    product=json.loads(_read_ref(artifact_ref))
    if (product.get('sample_only') is not True or product.get('source_generation')!=context.generation
            or product.get('source_identity')!=context.identity or set(product.get('processed_universe',[]))!=set(requested)
            or product.get('processed_count')!=len(set(requested)) or any(product.get(k)!=v for k,v in FLAGS.items())):
        raise ValueError('F10_ISOLATED_SAMPLE_PRODUCT_CONFLICT')
    for symbol in requested:
        if context.qualify(symbol).get('status')!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH':
            raise ValueError('F10_ISOLATED_SAMPLE_ADMISSION_FAILED:'+symbol)
    return isolated


def complete_f10(context, receipt_ref, output_root, *, requested=None, workers=4, fetch=fetch_one,
                 isolated_sample_root=None, research_scope=None, reuse_seed_ref=None):
    """Run after an immutable successful daily derivative receipt; resume by symbol."""
    if isinstance(workers,bool) or not isinstance(workers,int) or not 1<=workers<=4: raise ValueError('F10_WORKER_LIMIT')
    receipt=json.loads(_read_ref(receipt_ref))
    if isolated_sample_root is not None:
        isolated=_isolated_sample_upstream(context,receipt_ref,receipt,output_root,isolated_sample_root,requested)
    elif (receipt.get('schema')!='V4_A_DAILY_DERIVATIVES_V1' or receipt.get('status')!='COMPLETE_DESCRIPTIVE_NONPIT'
            or receipt.get('data_date')!=str(context.target) or receipt.get('source_generation')!=context.generation
            or any(receipt.get(k)!=v for k,v in FLAGS.items())): raise ValueError('F10_DAILY_COMPLETION_UNBOUND')
    if isolated_sample_root is not None and research_scope is not None:
        raise ValueError('F10_SCOPE_MODES_CONFLICT')
    context.unchanged()
    if research_scope is None:
        if reuse_seed_ref is not None:raise ValueError('F10_REUSE_REQUIRES_RESEARCH_SCOPE')
        universe=bound_universe(context,requested);scope_proof=None
    else:
        if not isinstance(research_scope,dict) or set(research_scope)!={'listing_ref','exception_ref'}:
            raise ValueError('F10_RESEARCH_SCOPE_PROOF_INVALID')
        universe,scope_proof=bound_research_universe(context,requested=requested,**research_scope)
    context.unchanged()
    identity={'data_date':str(context.target),'source_generation':context.generation,
              'selector_sha256':context.identity['selector_artifact_sha256'],'input_sha256':context.identity['input_sha256'],
              'scope_sha256':_sha(json.dumps(universe,sort_keys=True).encode()),
              'adapter_sha256':_sha(Path(__file__).read_bytes()),'collector_sha256':VENDOR}
    if scope_proof is not None:
        identity.update(research_scope=scope_proof,reuse_seed=reuse_seed_ref)
    root=Path(output_root)/'f10'/str(context.target)/context.generation[:16];root.mkdir(parents=True,exist_ok=True)
    checkpoint_path=root/'checkpoint.json'; cache={};reuse_lineage={};failures={}
    if checkpoint_path.exists():
        checkpoint=json.loads(checkpoint_path.read_text())
        if checkpoint.get('identity')!=identity:raise ValueError('F10_CHECKPOINT_IDENTITY_CONFLICT')
        for code,ref in checkpoint.get('items',{}).items():
            value=json.loads(_read_ref(ref))
            if code in universe and value.get('status')=='OBSERVED':
                if scope_proof is not None:_verified_observation(universe,code,ref)
                cache[code]=ref
        if scope_proof is not None:
            reuse_lineage=checkpoint.get('reused_from',{});failures=checkpoint.get('failures',{})
            if not isinstance(reuse_lineage,dict) or not isinstance(failures,dict):
                raise ValueError('F10_RESEARCH_CHECKPOINT_INVALID')
    if reuse_seed_ref is not None:
        selected,lineage=verified_reuse_sources(universe,reuse_seed_ref)
        for code,ref in selected.items():
            if code in cache and cache[code]['sha256']!=ref['sha256']:
                raise ValueError('F10_REUSE_CHECKPOINT_CONFLICT:'+code)
            cache[code]=ref;reuse_lineage[code]=lineage[code]
    pending=[s for s in universe if s not in cache and s not in failures]; completed=0;recent=[]
    def save_checkpoint():
        value={'schema':'v4.a_share.f10_checkpoint.v1','identity':identity,'items':cache,
               'upstream_success_receipt':receipt_ref,**FLAGS}
        if scope_proof is not None:value.update(reused_from=reuse_lineage,failures=failures)
        return _write(checkpoint_path,value)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        active={}; it=iter(pending);stop=False
        def submit():
            while not stop and len(active)<workers:
                try: symbol=next(it)
                except StopIteration: break
                active[pool.submit(fetch,symbol,universe[symbol])]=symbol
        submit()
        while active:
            done,_=wait(active,return_when=FIRST_COMPLETED)
            for future in done:
                symbol=active.pop(future)
                try:value=future.result()
                except Exception as error:value={'symbol':symbol,'status':'FAILED','reason':repr(error)}
                if value.get('symbol')!=symbol:raise ValueError('F10_RESULT_SYMBOL_CONFLICT')
                raw=(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',', ':'),allow_nan=False)+'\n').encode()
                ref=_write(root/'stocks'/symbol/(_sha(raw)+'.json'),value,immutable=True)
                observed=value.get('status')=='OBSERVED';reason=value.get('reason')
                if observed and scope_proof is not None:
                    try:_verified_observation(universe,symbol,ref)
                    except ValueError as error:observed=False;reason=str(error)
                if observed:cache[symbol]=ref
                else:failures[symbol]={'status':value.get('status') if value.get('status')!='OBSERVED' else 'SOURCE_IDENTITY_INVALID',
                                       'reason':reason,'artifact':ref}
                completed+=1
                recent.append(observed);recent=recent[-16:]
                if completed%20==0:context.unchanged();save_checkpoint()
                # Stop new requests when a sustained common failure is visible.
                if len(recent)==16 and sum(not ok for ok in recent)>=8:stop=True
            submit()
    context.unchanged(); working_checkpoint=save_checkpoint()
    # A later retry may advance checkpoint.json. Receipts must instead bind an
    # immutable snapshot so an already-published partial result remains valid.
    checkpoint_raw=_read_ref(working_checkpoint);checkpoint_value=json.loads(checkpoint_raw)
    checkpoint_ref=_write(root/'checkpoints'/(_sha(checkpoint_raw)+'.json'),checkpoint_value,immutable=True)
    remaining=sorted(set(universe)-set(cache)-set(failures))
    result={'schema':'v4.a_share.f10_daily_receipt.v1','status':'COMPLETE' if len(cache)==len(universe) else 'PARTIAL',
            **identity,'upstream_success_receipt':receipt_ref,'checkpoint':checkpoint_ref,'requested':len(universe),
            'scope':{'kind':('G2_RESEARCH_TARGET_READY' if scope_proof is not None else
                             'EXPLICIT_SYMBOLS' if requested is not None else 'ADMITTED_DAILY_UNIVERSE'),
                     'count':len(universe),'symbols':sorted(universe) if scope_proof is not None or requested is not None else None},
            'observed':len(cache),'failures':failures,'remaining':remaining,'historical_PIT':False,
            'captured_as_current_knowledge':True,**FLAGS}
    if scope_proof is not None:result.update(publication='NONE_RESEARCH_CANDIDATE',reused_count=len(reuse_lineage))
    if isolated_sample_root is not None:
        result.update(upstream_completion_kind='ISOLATED_SAMPLE_NUMERIC_MANIFEST',isolated_sample_root=str(isolated))
    digest=_sha((json.dumps(result,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode())
    result_ref=_write(root/'receipts'/(digest+'.json'),result,immutable=True)
    return {'status':result['status'],'receipt':result_ref,'requested':result['requested'],'observed':result['observed'],
            'failure_count':len(failures),'remaining_count':len(remaining)}


def publish_f10_completion(context, output_root, receipt_ref, *, expected_index_sha256=None, expected_event_sha256=None):
    """Publish only this completion ref through the existing product index/event."""
    import fcntl
    from ops.sync_stock_history_completion import DEFAULT_OWNER_LOCK, _inherited_owner_duplicate
    from ops.research_panel_daily_product import save
    root=Path(output_root);receipt=json.loads(_read_ref(receipt_ref));day=str(context.target)
    if (receipt.get('schema')!='v4.a_share.f10_daily_receipt.v1' or receipt.get('data_date')!=day
        or receipt.get('source_generation')!=context.generation or receipt.get('input_sha256')!=context.identity['input_sha256']
        or receipt.get('selector_sha256')!=context.identity['selector_artifact_sha256']
        or receipt.get('historical_PIT') is not False or any(receipt.get(k)!=v for k,v in FLAGS.items())
        or receipt.get('status') not in {'COMPLETE','PARTIAL'}):raise ValueError('F10_PUBLICATION_RECEIPT_CONFLICT')
    if receipt.get('upstream_completion_kind')=='ISOLATED_SAMPLE_NUMERIC_MANIFEST':
        _isolated_sample_upstream(context,receipt['upstream_success_receipt'],
            json.loads(_read_ref(receipt['upstream_success_receipt'])),root,receipt.get('isolated_sample_root'),
            receipt.get('scope',{}).get('symbols'))
    checkpoint=json.loads(_read_ref(receipt['checkpoint']));checkpoint_identity=checkpoint.get('identity',{})
    if (checkpoint.get('schema')!='v4.a_share.f10_checkpoint.v1' or checkpoint_identity.get('data_date')!=day
        or checkpoint_identity.get('source_generation')!=context.generation
        or checkpoint_identity.get('input_sha256')!=context.identity['input_sha256']
        or checkpoint_identity.get('selector_sha256')!=context.identity['selector_artifact_sha256']
        or checkpoint_identity.get('scope_sha256')!=receipt.get('scope_sha256')
        or checkpoint.get('upstream_success_receipt')!=receipt.get('upstream_success_receipt')
        or not isinstance(checkpoint.get('items'),dict) or not isinstance(receipt.get('requested'),int)
        or receipt.get('observed')!=len(checkpoint['items']) or receipt['requested']<receipt['observed']):
        raise ValueError('F10_PUBLICATION_CHECKPOINT_CONFLICT')
    scope=receipt.get('scope',{});symbols=scope.get('symbols') if isinstance(scope,dict) else None
    if (scope.get('count')!=receipt['requested'] or scope.get('kind') not in {'EXPLICIT_SYMBOLS','ADMITTED_DAILY_UNIVERSE'}
        or (scope['kind']=='EXPLICIT_SYMBOLS' and (not isinstance(symbols,list) or len(symbols)!=receipt['requested']
            or len(set(symbols))!=len(symbols) or not set(checkpoint['items'])<=set(symbols)))
        or (scope['kind']=='ADMITTED_DAILY_UNIVERSE' and symbols is not None)):
        raise ValueError('F10_PUBLICATION_SCOPE_CONFLICT')
    if (expected_index_sha256 is None)!=(expected_event_sha256 is None):raise ValueError('F10_PUBLICATION_CAS_PAIR_REQUIRED')
    context.unchanged();lock=(root/'.stock-history-completion.lock').open('a+b');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    stat=DEFAULT_OWNER_LOCK.stat();shared={'path':str(DEFAULT_OWNER_LOCK),'device':stat.st_dev,'inode':stat.st_ino}
    fd=_inherited_owner_duplicate(shared,day)
    if fd is None:fd=os.open(DEFAULT_OWNER_LOCK,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX);current=os.stat(DEFAULT_OWNER_LOCK,follow_symlinks=False);held=os.fstat(fd)
        if (current.st_dev,current.st_ino)!=(stat.st_dev,stat.st_ino) or (held.st_dev,held.st_ino)!=(stat.st_dev,stat.st_ino):raise ValueError('F10_OWNER_LOCK_DRIFT')
        ip=root/'index.json';ep=root/'events/latest.json';before_i=ip.read_bytes();before_e=ep.read_bytes();index=json.loads(before_i);event=json.loads(before_e)
        if expected_index_sha256 is not None and (_sha(before_i)!=expected_index_sha256 or _sha(before_e)!=expected_event_sha256):
            raise ValueError('F10_EXPECTED_INDEX_EVENT_CAS_MOVED')
        manifest_ref=index.get('dates',{}).get(day)
        if (not manifest_ref or event.get('data_date')!=day or event.get('source_generation')!=context.generation
            or event.get('input_sha256')!=context.identity['input_sha256'] or event.get('manifest')!=manifest_ref):
            raise ValueError('F10_PRODUCT_INDEX_MOVED')
        if (receipt.get('upstream_completion_kind')=='ISOLATED_SAMPLE_NUMERIC_MANIFEST'
                and (event.get('publication_scope')!='ISOLATED_CANDIDATE_SAMPLE_ONLY'
                     or event.get('sample_only') is not True or manifest_ref!=receipt['upstream_success_receipt'])):
            raise ValueError('F10_ISOLATED_SAMPLE_EVENT_CONFLICT')
        manifest=json.loads(_read_ref(manifest_ref))
        if manifest.get('source_generation')!=context.generation or manifest.get('input_sha256')!=context.identity['input_sha256']:
            raise ValueError('F10_NUMERIC_MANIFEST_CONFLICT')
        prior_ref=index.get('f10',{}).get(day)
        if prior_ref:
            prior=json.loads(_read_ref(prior_ref))
            if (prior.get('schema')!='v4.a_share.f10_daily_receipt.v1' or prior.get('data_date')!=day
                or prior.get('historical_PIT') is not False or any(prior.get(k)!=v for k,v in FLAGS.items())):
                raise ValueError('F10_PRIOR_RECEIPT_CONFLICT')
            if prior.get('source_generation')==context.generation and prior.get('input_sha256')==context.identity['input_sha256']:
                old_checkpoint=json.loads(_read_ref(prior['checkpoint']))
                old_items=old_checkpoint.get('items',{});new_items=checkpoint['items']
                if (not isinstance(old_items,dict) or not isinstance(new_items,dict)
                    or not isinstance(prior.get('requested'),int) or not isinstance(receipt.get('requested'),int)
                    or receipt['requested']<prior['requested'] or not set(old_items)<=set(new_items)):
                    raise ValueError('F10_COVERAGE_REGRESSION')
        context.unchanged();index.setdefault('f10',{})[day]=receipt_ref
        event.update(f10=receipt_ref,event_id=_sha(json.dumps({'manifest':manifest_ref,'f10':receipt_ref},sort_keys=True,separators=(',',':')).encode()))
        if ip.read_bytes()!=before_i or ep.read_bytes()!=before_e:raise ValueError('F10_INDEX_EVENT_CAS_MOVED')
        after_i=save(ip,index)
        try:after_e=save(ep,event)
        except Exception:
            if _sha(ip.read_bytes())==after_i['sha256']:save(ip,json.loads(before_i))
            raise
        return {'status':'PUBLISHED_F10_COMPLETION','index':after_i,'event':after_e,'f10_receipt':receipt_ref}
    finally:
        os.close(fd);lock.close()
