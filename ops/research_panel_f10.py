"""Bounded TDX F10 continuation of the existing A daily completion owner.

This adapter reuses the pinned local F10 collectors.  It stores observed
snapshots, never rewrites formula panels or assigns current F10 to past days.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
VENDOR = {
    'tdx_f10_fetch_existing.py': '86d80dec56e78f9842fdb954a0d49d9e5b5a1f2d86f2a6acb7eb095713d00c68',
    'tdx_f10_concepts_existing.py': 'c0d92c2e7c8409d673a03c029b1d251ab6338a3183eec285c3912be4f47f66d2',
}
HOSTS = (('115.238.90.165', 7709), ('119.147.212.81', 7709), ('101.227.73.20', 7709))
# BJ's server mapping has not been certified here; never infer it from digits.
MARKET = {'SZ': 0, 'SH': 1}


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


def _grab_optional(fetch, text, label):
    """A source placeholder such as '-' is missing, not a failed F10 capture."""
    try:
        return _safe_number(fetch.grab(text, label))
    except (TypeError, ValueError, OverflowError):
        return None


def _table_cells(line):
    return [part.strip() for part in line.strip().strip('｜').split('｜')]


def _number_text(value):
    value = value.strip().replace(',', '')
    if value in ('', '-', '--', '—'): return None
    match = re.fullmatch(r'([-+]?\d+(?:\.\d+)?)(亿|万|%)?', value)
    if not match: return None
    scale = {'亿': 100000000, '万': 10000, '%': 1, None: 1}[match.group(2)]
    return float(match.group(1)) * scale


def project_observed_history(snapshot):
    """Parse dated F10 tables as currently observed facts, never as PIT bars."""
    if snapshot.get('status') != 'OBSERVED' or snapshot.get('historical_PIT') is not False:
        raise ValueError('F10_SNAPSHOT_NOT_OBSERVED')
    text=snapshot.get('source_text')
    if not isinstance(text,str) or _sha(text.encode()) != snapshot.get('source_text_sha256'):
        raise ValueError('F10_SNAPSHOT_TEXT_SHA_CONFLICT')
    lines=text.splitlines(); reports={}; section=None; periods=[]; holder=None; announcements=[]; dividends=[];capital_actions=[];pledges=[]
    metrics={'每股收益(元)':'eps','每股净资产(元)':'bps','净资产收益率(%)':'roe_pct',
             '总股本(股)':'total_share','流通A股(股)':'float_a_share',
             '基金持仓比例':'fund_hold_ratio_pct'}
    for line in lines:
        if '★最新主要指标★' in line: section='financial';periods=_table_cells(line)[1:]
        elif '【2.机构持股变化】' in line: section='institutional';periods=[]
        elif '【3.概念板块】' in line: section='concepts';periods=[]
        elif section=='institutional' and '报告日期' in line:periods=_table_cells(line)[1:]
        cells=_table_cells(line) if '｜' in line else []
        if cells and periods and cells[0] in metrics and section in ('financial','institutional'):
            metric=metrics[cells[0]]
            for period,raw in zip(periods,cells[1:]):
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',period):continue
                reports.setdefault(period,{'report_period':period,'publication_date':None,'values':{}})['values'][metric]=_number_text(raw)
        match=re.search(r'股东户数变化[:：]\s*截止(\d{4}-\d{2}-\d{2}),公司股东数([\d,]+),比上期\((\d{4}-\d{2}-\d{2})\)(增加|减少)([\d,]+)户',line)
        if match:
            current=int(match.group(2).replace(',',''));difference=int(match.group(5).replace(',',''))
            prior=current-difference if match.group(4)=='增加' else current+difference
            holder={'report_period':match.group(1),'count':current,'previous_report_period':match.group(3),
                    'previous_count':prior,'previous_count_basis':'DERIVED_FROM_REPORTED_CHANGE','publication_date':None}
        match=re.search(r'★最新公告[:：]\s*(\d{4}-\d{2}-\d{2})([^｜]+)',line)
        if match:announcements.append({'publication_date':match.group(1),'text':match.group(2).strip()})
        if '【分红】' in line:
            item={'publication_date':None,'reported_text':line.strip(' ｜')}
            report_match=re.search(r'【分红】[:：]\s*(\d{4})(一季|半年度|中期|三季|年度)',line)
            periods_by_name={'一季':'03-31','半年度':'06-30','中期':'06-30','三季':'09-30','年度':'12-31'}
            item['report_period']=(report_match.group(1)+'-'+periods_by_name[report_match.group(2)]) if report_match else None
            for label,key in (('股权登记日','record_date'),('除权除息日','ex_dividend_date'),('派息日','payment_date')):
                date_match=re.search(re.escape(label)+r'[:：]\s*(\d{4}-\d{2}-\d{2})',line)
                item[key]=date_match.group(1) if date_match else None
            dividends.append(item)
        match=re.search(r'★资本运作[:：]\s*【公告日期】(\d{4}-\d{2}-\d{2})\s*【类别】([^｜]+)',line)
        if match:capital_actions.append({'publication_date':match.group(1),'reported_text':match.group(2).strip()})
        if '【质押占比】' in line:
            pledges.append({'publication_date':None,'reported_text':line.strip(' ｜'),
                            'scope':'AS_REPORTED; NOT_ASSUMED_TOTAL_SHARES'})
        match=re.search(r'(\d{4}-\d{2}-\d{2}).*?营业总收入\(元\)\s*[:：]\s*([^\s｜]+)(?:\s+同比增([-+\d.]+)%)?',line)
        if match:
            report=reports.setdefault(match.group(1),{'report_period':match.group(1),'publication_date':None,'values':{}})
            value=_number_text(match.group(2));report['values']['revenue_yi']=value/100000000 if value is not None else None
            report['values']['revenue_yoy_pct']=_number_text(match.group(3)) if match.group(3) else None
        match=re.search(r'(\d{4}-\d{2}-\d{2}).*?净利润\(元\)\s*[:：]\s*([^\s｜]+)(?:\s+同比增([-+\d.]+)%)?',line)
        if match:
            report=reports.setdefault(match.group(1),{'report_period':match.group(1),'publication_date':None,'values':{}})
            value=_number_text(match.group(2));report['values']['net_profit_yi']=value/100000000 if value is not None else None
    native_holder=(snapshot.get('financials') or {}).get('holder_count')
    holder_comparison=('NOT_COMPARABLE_MISSING_SOURCE' if holder is None or native_holder is None else
                       'SAME_VALUE_DIFFERENT_SOURCE_TIMES' if holder['count']==native_holder else
                       'DIFFERENT_VALUES_DIFFERENT_SOURCE_TIMES')
    for period,report in reports.items():
        report['period_kind']='QUARTER_END' if period[5:] in ('03-31','06-30','09-30','12-31') else 'OTHER_DATED_SNAPSHOT'
    return {'schema':'v4.a_share.f10_observed_history.v1','symbol':snapshot['symbol'],
            'captured_at':snapshot['captured_at'],'source_updated_date':snapshot.get('source_updated_date'),
            'finance_updated_date':snapshot.get('finance_updated_date'),
            'source_text_sha256':snapshot['source_text_sha256'],'financial_reports':sorted(reports.values(),key=lambda x:x['report_period']),
            'holder_count':holder,'native_holder_count':native_holder,'holder_source_comparison':holder_comparison,
            'announcements':announcements,'dividend_items':dividends,'capital_actions':capital_actions,'pledge_disclosures':pledges,
            'concepts':snapshot.get('concepts',[]),'concept_status':snapshot.get('concept_status'),
            'finance_native_raw':snapshot.get('finance_native_raw'),
            'availability_policy':'OBSERVED_AT_CAPTURE; REPORT_PERIOD_IS_NOT_PUBLICATION_DATE; NO_HISTORICAL_PIT_BACKFILL',
            'historical_PIT':False,**FLAGS}


def _comparison(latest, prior, *, basis, unit, percentage_points=False, loss_sensitive=False):
    latest=_safe_number(latest);prior=_safe_number(prior)
    delta=latest-prior if latest is not None and prior is not None else None
    loss_case=bool(delta is not None and loss_sensitive and (latest < 0 or prior < 0))
    relative=delta/abs(prior)*100 if delta is not None and prior != 0 and not loss_case else None
    change_class=(None if not loss_case else 'TURNED_PROFIT' if prior<0 and latest>0 else
                  'LOSS_CLEARED_TO_ZERO' if prior<0 and latest==0 else 'TURNED_LOSS' if prior>=0 and latest<0 else
                  'LOSS_NARROWED' if delta>0 else 'LOSS_WIDENED' if delta<0 else 'LOSS_UNCHANGED')
    return {'latest':latest,'prior':prior,'absolute_change':delta,
            'relative_change_pct':relative,'percentage_point_change':delta if percentage_points else None,
            'status':'COMPLETE' if delta is not None else 'UNKNOWN_LATEST' if latest is None else 'UNKNOWN_PRIOR',
            'relative_status':'COMPLETE' if relative is not None else 'UNKNOWN_ZERO_BASE' if delta is not None and prior==0 else
                              'NOT_MEANINGFUL_LOSS_OR_SIGN_CHANGE' if loss_case else 'UNKNOWN_INPUT',
            'change_class':change_class,'presentation_priority':'PERCENTAGE_POINTS' if percentage_points else 'ABSOLUTE_AND_RELATIVE',
            'basis':basis,'unit':unit}


def project_company_comparison(snapshot):
    """Current F10 plus explicit prior-period changes; never fill historical bars."""
    company=project_observed_history(snapshot)
    reports=[r for r in company['financial_reports'] if r['period_kind']=='QUARTER_END'
             and any(k in r['values'] for k in ('eps','bps','roe_pct','revenue_yi','net_profit_yi'))]
    latest=reports[-1] if reports else None;prior=reports[-2] if len(reports)>1 else None
    current_values=latest['values'] if latest else {};prior_values=prior['values'] if prior else {}
    definitions={
        'eps':('CUMULATIVE_VALUE_DIFFERENCE_NOT_QOQ_GROWTH','yuan_per_share',False),
        'bps':('PERIOD_END_POINT_IN_TIME','yuan_per_share',False),
        'roe_pct':('CUMULATIVE_RATIO_DIFFERENCE_NOT_QOQ_GROWTH','percent',True),
        'total_share':('PERIOD_END_POINT_IN_TIME','shares',False),
        'float_a_share':('PERIOD_END_POINT_IN_TIME','shares',False),
        'revenue_yi':('CUMULATIVE_VALUE_DIFFERENCE_NOT_QOQ_GROWTH','100_million_yuan',False),
        'net_profit_yi':('CUMULATIVE_VALUE_DIFFERENCE_NOT_QOQ_GROWTH','100_million_yuan',False),
        'revenue_yoy_pct':('REPORTED_YEAR_ON_YEAR_RATIOS_NOT_QOQ_GROWTH','percent',True),
        'h_share':('SOURCE_NOT_BOUND','shares',False),
        'restricted_share':('SOURCE_NOT_BOUND','shares',False),
    }
    metrics={}
    for name,(basis,unit,pp) in definitions.items():
        if name in ('total_share','float_a_share'):
            # Share structure can be updated on a non-quarter date, without a new financial report.
            observations=[r for r in company['financial_reports'] if r['values'].get(name) is not None]
            now=observations[-1] if observations else None;before=observations[-2] if len(observations)>1 else None
        else:
            now,before=latest,prior
        item=_comparison(now['values'].get(name) if now else None,before['values'].get(name) if before else None,
                         basis=basis,unit=unit,percentage_points=pp,loss_sensitive=name in ('eps','net_profit_yi'))
        item.update(latest_period=now['report_period'] if now else None,prior_period=before['report_period'] if before else None,
                    period_kind=now.get('period_kind') if now else None)
        metrics[name]=item
    holder=company.get('holder_count');holder_delta=_comparison(holder.get('count') if holder else None,
      holder.get('previous_count') if holder else None,basis='REPORTED_HOLDER_COUNT; PRIOR_DERIVED_FROM_REPORTED_CHANGE',unit='holders')
    holder_delta.update(latest_period=holder.get('report_period') if holder else None,
                        prior_period=holder.get('previous_report_period') if holder else None,
                        native_source_value=company.get('native_holder_count'),
                        native_source_updated_date=company.get('finance_updated_date'),
                        source_comparison=company.get('holder_source_comparison'))
    holdings={}
    for field in ('fund_hold_ratio_pct','top10_float_ratio_pct','pledge_ratio_pct'):
        holdings[field]=_comparison(current_values.get(field),prior_values.get(field),
          basis='PERIOD_END_REPORTED_RATIO' if field=='fund_hold_ratio_pct' else 'SOURCE_NOT_BOUND',
          unit='percent',percentage_points=True)
    def event_comparison(items, *, date_field):
        items=list(items)
        if items and all(item.get(date_field) for item in items):
            items.sort(key=lambda item:item[date_field],reverse=True);ordering='EXPLICIT_'+date_field.upper()+'_DESCENDING'
        else:ordering='SOURCE_ORDER; UNKNOWN_DATES_REMAIN_UNKNOWN'
        first=items[0] if items else None;second=items[1] if len(items)>1 else None
        text=lambda x:x.get('reported_text',x.get('text')) if x else None
        return {'latest':first,'prior':second,'content_changed':text(first)!=text(second) if first and second else None,
                'status':'COMPLETE' if len(items)>1 else 'UNKNOWN_PRIOR' if items else 'UNKNOWN_LATEST',
                'ordering':ordering}
    company['comparison']={'latest_report_period':latest['report_period'] if latest else None,
        'prior_report_period':prior['report_period'] if prior else None,
        'captured_at':company['captured_at'],'source_updated_date':company['source_updated_date'],
        'financial_metrics':metrics,'shareholder_count':holder_delta,'holdings':holdings,
        'announcements':event_comparison(company['announcements'],date_field='publication_date'),
        'dividends':event_comparison(company['dividend_items'],date_field='report_period'),
        'capital_actions':event_comparison(company['capital_actions'],date_field='publication_date'),
        'single_quarter_values':'UNKNOWN_NOT_DERIVED_WITHOUT_MATCHED_REPORT_SEQUENCE',
        'historical_PIT':False}
    return company


def fetch_one(symbol, exchange, *, api_factory=None, vendor=None):
    if exchange is None:
        return {'symbol':symbol, 'exchange':None, 'status':'SOURCE_IDENTITY_UNAVAILABLE', 'reason':'BOUND_PANEL_EXCHANGE_MISSING'}
    if exchange not in MARKET:
        return {'symbol':symbol, 'exchange':exchange, 'status':'UNSUPPORTED_EXCHANGE', 'reason':'TDX_MARKET_MAPPING_UNCERTIFIED'}
    fetch, _ = vendor or _vendors(); api = (api_factory or fetch.TdxHq_API)(); connected = None
    try:
        for host in HOSTS:
            try:
                if api.connect(*host): connected=host; break
            except Exception: continue
        if connected is None: raise RuntimeError('TDX_CONNECTION_FAILED')
        code=symbol.split('.')[0]; market=MARKET[exchange]
        categories=api.get_company_info_category(market, code)
        if not categories: raise RuntimeError('F10_CATEGORY_MISSING')
        category=categories[0]
        body=api.get_company_info_content(market,code,category['filename'],category['start'],category['length'])
        if not isinstance(body,(str,bytes)) or not body: raise RuntimeError('F10_CONTENT_MISSING')
        text=(body if isinstance(body,str) else body.decode('gbk','replace')).replace('\x00','')
        finance=api.get_finance_info(market,code)
        if not isinstance(finance,dict) or str(finance.get('code') or '')!=code or finance.get('market')!=market:
            raise RuntimeError('F10_FINANCE_IDENTITY_MISMATCH')
        section=_concept_section(text); concepts=fetch.concepts_from(section) if section is not None else []
        period=re.search(r'★最新主要指标★\s*｜\s*(\d{4}-\d{2}-\d{2})',text)
        updated=re.search(r'更新日期[：:]\s*(\d{4}-\d{2}-\d{2})',text[:300])
        name=re.search(r'◇'+re.escape(code)+r'\s+([^◇\n]+?)\s+更新日期',text[:300])
        income=re.search(r'营业总收入\(元\)\s*[:：]\s*([^\s｜]+)',text)
        net=re.search(r'净利润\(元\)\s*[:：]\s*([^\s｜]+)',text)
        data={'symbol':symbol,'exchange':exchange,'status':'OBSERVED',
              'captured_at':datetime.now(timezone.utc).isoformat(),'server':f'{connected[0]}:{connected[1]}',
              'category':{'name':category.get('name'),'filename':category.get('filename'),
                          'start':category.get('start'),'length':category.get('length')},
              'source_text_sha256':_sha(text.encode()),'source_text':text,
              'source_updated_date':updated.group(1) if updated else None,
              'finance_updated_date':str(finance.get('updated_date') or '') or None,
              'name':name.group(1).strip() if name else None,
              'concepts':concepts,'concept_status':'OBSERVED' if section is not None and concepts else 'UNKNOWN_EMPTY_OR_UNPARSED',
              'industry':{'tdx_finance_industry_code':finance.get('industry'),'name':None,'status':'CODE_ONLY_NAME_UNMAPPED'},
              'financials':{'report_period':period.group(1) if period else None,
                  'holder_count':_safe_number(finance.get('gudongrenshu')),
                  'eps':_grab_optional(fetch,text,'每股收益(元)'),'bps':_grab_optional(fetch,text,'每股净资产(元)'),
                  'roe_pct':_grab_optional(fetch,text,'净资产收益率(%)'),
                  'revenue_text':income.group(1) if income else None,'net_profit_text':net.group(1) if net else None},
              'finance_native_raw':{str(k):_safe_number(v) if isinstance(v,(float,int)) else v for k,v in finance.items()},
              'historical_PIT':False,**FLAGS}
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


def complete_f10(context, receipt_ref, output_root, *, requested=None, workers=4, fetch=fetch_one):
    """Run after an immutable successful daily derivative receipt; resume by symbol."""
    if isinstance(workers,bool) or not isinstance(workers,int) or not 1<=workers<=4: raise ValueError('F10_WORKER_LIMIT')
    receipt=json.loads(_read_ref(receipt_ref))
    if (receipt.get('schema')!='V4_A_DAILY_DERIVATIVES_V1' or receipt.get('status')!='COMPLETE_DESCRIPTIVE_NONPIT'
            or receipt.get('data_date')!=str(context.target) or receipt.get('source_generation')!=context.generation
            or any(receipt.get(k)!=v for k,v in FLAGS.items())): raise ValueError('F10_DAILY_COMPLETION_UNBOUND')
    context.unchanged(); universe=bound_universe(context,requested); context.unchanged()
    identity={'data_date':str(context.target),'source_generation':context.generation,
              'selector_sha256':context.identity['selector_artifact_sha256'],'input_sha256':context.identity['input_sha256'],
              'scope_sha256':_sha(json.dumps(universe,sort_keys=True).encode()),
              'adapter_sha256':_sha(Path(__file__).read_bytes()),'collector_sha256':VENDOR}
    root=Path(output_root)/'f10'/str(context.target)/context.generation[:16];root.mkdir(parents=True,exist_ok=True)
    checkpoint_path=root/'checkpoint.json'; cache={}
    if checkpoint_path.exists():
        checkpoint=json.loads(checkpoint_path.read_text())
        if checkpoint.get('identity')!=identity:raise ValueError('F10_CHECKPOINT_IDENTITY_CONFLICT')
        for code,ref in checkpoint.get('items',{}).items():
            value=json.loads(_read_ref(ref))
            if code in universe and value.get('status')=='OBSERVED':cache[code]=ref
    pending=[s for s in universe if s not in cache]; failures={}; completed=0
    def save_checkpoint():
        return _write(checkpoint_path,{'schema':'v4.a_share.f10_checkpoint.v1','identity':identity,'items':cache,
                                     'upstream_success_receipt':receipt_ref,**FLAGS})
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
                if value.get('status')=='OBSERVED':cache[symbol]=ref
                else:failures[symbol]={'status':value.get('status'),'reason':value.get('reason'),'artifact':ref}
                completed+=1
                if completed%20==0:context.unchanged();save_checkpoint()
                # Stop new requests when a sustained common failure is visible.
                if completed>=16 and len(failures)>=8 and not cache:stop=True
            submit()
    context.unchanged(); working_checkpoint=save_checkpoint()
    # A later retry may advance checkpoint.json. Receipts must instead bind an
    # immutable snapshot so an already-published partial result remains valid.
    checkpoint_raw=_read_ref(working_checkpoint);checkpoint_value=json.loads(checkpoint_raw)
    checkpoint_ref=_write(root/'checkpoints'/(_sha(checkpoint_raw)+'.json'),checkpoint_value,immutable=True)
    remaining=sorted(set(universe)-set(cache)-set(failures))
    result={'schema':'v4.a_share.f10_daily_receipt.v1','status':'COMPLETE' if len(cache)==len(universe) else 'PARTIAL',
            **identity,'upstream_success_receipt':receipt_ref,'checkpoint':checkpoint_ref,'requested':len(universe),
            'scope':{'kind':'EXPLICIT_SYMBOLS' if requested is not None else 'ADMITTED_DAILY_UNIVERSE',
                     'count':len(universe),'symbols':sorted(universe) if requested is not None else None},
            'observed':len(cache),'failures':failures,'remaining':remaining,'historical_PIT':False,
            'captured_as_current_knowledge':True,**FLAGS}
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
