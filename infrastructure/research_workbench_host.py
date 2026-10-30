"""Read-only shape adapter for the fixed Dot visual shell, no financial producer."""
from __future__ import annotations
import copy
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import urlencode
from starlette.requests import Request

GROUPS=('nav_smallk','original','nav_pullback','nav_breakout')
FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)


def compact(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value) or date.fromisoformat(value).isoformat()!=value:
        raise ValueError('WORKBENCH_ISO_DATE_REQUIRED')
    return value.replace('-','')


def next_workbench_session(calendar,trade_date):
    """Bounded A-share next-session projection using the installed calendar.

    The accepted runtime predates next_session. Resolve every candidate date
    through that same owner; an unknown year/state never becomes a weekday guess.
    """
    from contracts.trading_calendar import resolve_market_states,TradingDayState
    if not isinstance(trade_date,str) or not re.fullmatch(r'\d{8}',trade_date):raise ValueError('WORKBENCH_CALENDAR_DATE_INVALID')
    cursor=datetime.strptime(trade_date,'%Y%m%d').date()
    if cursor.year!=calendar.year:raise ValueError('WORKBENCH_CALENDAR_YEAR_UNBOUND')
    for _ in range(366):
        cursor+=timedelta(days=1)
        if cursor.year!=calendar.year:raise ValueError('WORKBENCH_NEXT_CALENDAR_YEAR_UNBOUND')
        value=cursor.strftime('%Y%m%d');state=resolve_market_states(calendar,value).get('a_share')
        if state in {TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}:return value
        if state!=TradingDayState.NON_TRADING_DAY:raise ValueError('WORKBENCH_NEXT_SESSION_STATE_UNKNOWN')
    raise ValueError('WORKBENCH_NEXT_SESSION_UNRESOLVED')


def checked_bytes(reference):
    path=Path(reference['path'])
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True)!=path:
        raise ValueError('WORKBENCH_SOURCE_PATH_INVALID')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=reference['sha256']:
        raise ValueError('WORKBENCH_SOURCE_SHA_DRIFT')
    return raw


def checked(reference):
    return json.loads(checked_bytes(reference))


class ResearchWorkbenchHost:
    """Compact view cache keys follow the actual current numeric manifest."""
    def __init__(self,source,binding,clock=None):
        self._clock=clock or (lambda:datetime.now(ZoneInfo('Asia/Shanghai')))
        self.source=source
        self.binding=copy.deepcopy(binding)
        self._cache={}
        self._chart_cache={}
        self._row_cache={}
        self._statistics_cache={}
        from infrastructure.research_classification_view import ReceivedClassificationStore
        self.classifications=ReceivedClassificationStore(binding.get('classification_store_root'))
        self._lock=threading.RLock()
        if binding.get('schema')!='V4_MAC_WORKBENCH_BINDING_V1' or binding.get('RESEARCH_ONLY') is not True or any(binding.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):
            raise ValueError('WORKBENCH_HOST_BINDING_REQUIRED')

    def _index(self):
        return json.loads((self.source._a_product_root()/'index.json').read_text())

    def _view(self,source_date,revision=None):
        day=compact(source_date);index=self._index();reference=index.get('dates',{}).get(day)
        if reference is None:raise KeyError('WORKBENCH_DATE_NOT_MATERIALIZED')
        key=(day,reference['sha256'])
        with self._lock:
            if key not in self._cache:
                product=self.source.read_a_daily_product(day)
                if product.get('manifest')!=reference or product.get('data_date')!=day or product.get('status') not in {'READY','PARTIAL_WITH_ROWS'}:
                    raise ValueError('WORKBENCH_PRODUCT_MOVED_OR_INVALID')
                # One source summary read per real manifest; never read5808
                # stock checkpoints, historical labels, or raw OHLCV on a GET.
                view={k:product[k] for k in ('data_date','source_generation','source_identity','source_config','manifest','artifact','processed_count','source_universe_count','status','rows')}
                view['original_charts']=product.get('original_charts')
                self._cache[key]=view
                while len(self._cache)>8:self._cache.pop(next(iter(self._cache)))
            view=self._cache[key]
        if revision is not None and revision!=view['source_generation']:
            raise ValueError('WORKBENCH_SOURCE_REVISION_CONFLICT')
        return view

    def _observation_date(self,source_date):
        item=self.binding.get('observation_dates',{}).get(source_date)
        if not isinstance(item,dict) or not item.get('authority'):
            calendar_ref=self.binding.get('calendar')
            if not calendar_ref:return None
            from contracts.trading_calendar import load_market_calendar
            checked(calendar_ref)
            calendar=load_market_calendar(Path(calendar_ref['path']))
            value=next_workbench_session(calendar,compact(source_date))
            return f'{value[:4]}-{value[4:6]}-{value[6:]}'
        value=item.get('date');compact(value)
        authority=checked(item['authority'])
        if authority.get('source_date')!=source_date or authority.get('observation_date')!=value:raise ValueError('WORKBENCH_DATE_AUTHORITY_CONFLICT')
        return value

    def _module_reference(self,module,day):
        """A pointer advances only after the original owner saved its receipt."""
        root=self.binding.get(module+'_root')
        if root:
            path=Path(root)/day/'latest.json'
            if not path.exists():return None
            if path.is_symlink() or path.resolve(strict=True)!=path:raise ValueError('WORKBENCH_MODULE_POINTER_INVALID')
            pointer=json.loads(path.read_text())
            if pointer.get('schema')!='V4_WORKBENCH_MODULE_COMMIT_V1' or pointer.get('module')!=module or pointer.get('date')!=day or any(pointer.get(k)!=v for k,v in FLAGS.items()):
                raise ValueError('WORKBENCH_MODULE_POINTER_IDENTITY_CONFLICT')
            checked(pointer['artifact']);checked(pointer['receipt'])
            receipt=checked(pointer['receipt'])
            if receipt.get('status')!='COMMITTED' or receipt.get('artifact')!=pointer['artifact']:raise ValueError('WORKBENCH_MODULE_RECEIPT_CONFLICT')
            return pointer['artifact']
        return self.binding.get(module,{}).get(day) if isinstance(self.binding.get(module),dict) else None

    def versions(self,source_date,revision=None):
        p=self._view(source_date,revision);observation=self._observation_date(source_date)
        def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        def version(module,day):
            try:return self._module_reference(module,day)
            except (ValueError,OSError,KeyError,TypeError) as error:return {'error':str(error)}
        try:quote=self._observation_commit(observation)
        except (ValueError,OSError,KeyError,TypeError) as error:quote={'error':str(error)}
        modules=dict(classification=self.classifications.version(),list=digest([p['manifest'],self._index().get('display_names',{}).get(compact(source_date))]),
                     statistics=digest(version('statistics',source_date)),observations=digest(quote),
                     context=digest([version('overseas',observation),version('japan',observation),quote.get('korea') if quote else None]),
                     workflow=digest([self.binding.get('workflow_plan'),version('execution',observation),self.binding.get('workflow_execution'),self.workflow(source_date)]))
        return dict(schema='V4_WORKBENCH_VERSIONS_V1',source_date=source_date,observation_date=observation,generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],numeric_manifest=p['manifest'],modules=modules,event_id=digest(modules),**FLAGS)

    def history(self):
        days=[]
        for value in sorted(self._index().get('dates',{}),reverse=True):
            iso=f'{value[:4]}-{value[4:6]}-{value[6:]}'
            product=self._view(iso)
            days.append(dict(source_date=iso,observation_date=self._observation_date(iso),revision=product['source_generation'],numeric_manifest=product['manifest']))
        return dict(status='READY',days=days,revision_kind='SOURCE_GENERATION_NOT_STATISTICS_REVISION',**FLAGS)

    def day(self,source_date,revision=None):
        p=self._view(source_date,revision);observation=self._observation_date(source_date)
        if observation is None:raise ValueError('WORKBENCH_OBSERVATION_DATE_UNBOUND')
        rows=[]
        for row in p['rows']:
            row_sha=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
            row_key=(p['data_date'],p['source_generation'],p['source_identity']['input_sha256'],row_sha)
            with self._lock:
                normalized=self._row_cache.get(row_key)
                if normalized is None:
                    hits=set(row['groups'].split('|')) if row.get('groups') else set()
                    pending=set(row.get('pending_groups','').split('|'))-{''}
                    if not hits<=set(GROUPS) or not pending<=set(GROUPS) or hits&pending:raise ValueError('WORKBENCH_GROUP_STATE_CONFLICT')
                    normalized=dict(symbol=row['symbol'],enriched_display_name=row.get('display_name'),group_states={g:'TRUE' if g in hits else 'UNKNOWN' if g in pending else 'FALSE' for g in GROUPS},eligible_candidate=bool(hits),in_fifth=bool(pending),source_row=row)
                    self._row_cache[row_key]=normalized
                    while len(self._row_cache)>4096:self._row_cache.pop(next(iter(self._row_cache)))
            rows.append(normalized)
        # The completion owner materializes this light projection once. A GET
        # never loops through stock detail readers or historical checkpoints.
        statistics_ref=None;summaries={};statistics_status='CANNOT_CONFIRM_PROJECTION_MISSING'
        try:
            statistics_ref=self._module_reference('statistics',source_date)
            if statistics_ref:
                key=(source_date,p['manifest']['sha256'],statistics_ref['sha256'])
                with self._lock:
                    if key not in self._statistics_cache:
                        summary=checked(statistics_ref)
                        if (summary.get('schema')!='V4_WORKBENCH_STATISTICS_V1' or summary.get('numeric_manifest')!=p['manifest']
                                or summary.get('source_date')!=source_date or summary.get('generation')!=p['source_generation']
                                or summary.get('input_sha256')!=p['source_identity']['input_sha256']
                                or set(summary.get('rows',{}))!={r['symbol'] for r in rows}
                                or any(summary.get(k)!=v for k,v in FLAGS.items())):
                            raise ValueError('WORKBENCH_STATISTICS_REVISION_MOVED')
                        self._statistics_cache[key]=summary['rows']
                        while len(self._statistics_cache)>4:self._statistics_cache.pop(next(iter(self._statistics_cache)))
                    summaries=self._statistics_cache[key]
                statistics_status='STORED_PROJECTION'
        except (ValueError,OSError,KeyError,TypeError) as error:
            statistics_status='CANNOT_CONFIRM:'+str(error)
        rows=[{**r,'history_rates':summaries.get(r['symbol'],{})} for r in rows] if summaries else rows
        try:classification=self.classifications.join(p['rows']) if self.classifications.root else None
        except (ValueError,OSError,KeyError,TypeError) as error:
            classification=dict(rows={r['symbol']:dict(identity_status='CANNOT_CONFIRM_SOURCE_INVALID',classification=None,error=str(error)) for r in rows},catalogs={},identity_counts={'CANNOT_CONFIRM_SOURCE_INVALID':len(rows)},status='CANNOT_CONFIRM:'+str(error))
        if classification:rows=[{**r,'classification':classification['rows'][r['symbol']]} for r in rows]
        execution=self.workflow(source_date)
        return dict(schema='RESEARCH_SYSTEM_DAY_V1',source_date=source_date,observation_date=observation,generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],revision=p['source_generation'],numeric_manifest=p['manifest'],rows=rows,scope_count=len(rows),original_processed_count=p['processed_count'],row_scope='FROZEN_CANDIDATE_UNION_ONLY_NOT_FULL_POOL',formula_review='PENDING',chart_review='UNKNOWN_NOT_REVIEWED',execution_status='DEFERRED_USER',classification_catalogs=classification['catalogs'] if classification else {},classification_identity_counts=classification['identity_counts'] if classification else {},classification_status=classification['status'] if classification else 'CANNOT_CONFIRM_SOURCE_NOT_BOUND',statistics_status=statistics_status,statistics_version=statistics_ref['sha256'] if statistics_ref else None,workflow=[dict(label=n['label_zh'],status=n['execution_status'],recorded_at=n.get('recorded_at'),materials=n.get('materials',[])) for n in execution['time_contract']['nodes']],materials=[],reference_links=[dict(label='旧版单股归档',url='/research-panel/legacy-daily.html?'+urlencode(dict(date=source_date)))],source_refs=dict(numeric_manifest=p['manifest'],artifact=p['artifact'],date_binding=self.binding.get('observation_dates',{}).get(source_date) or dict(calendar=self.binding.get('calendar'),method='NEXT_AUTHORITY_SESSION')),**FLAGS)

    def classification_catalog(self,market):
        return self.classifications.catalog(market)

    def chart_views(self,source_date,revision=None):
        p=self._view(source_date,revision);descriptor=p.get('original_charts')
        if not isinstance(descriptor,dict) or descriptor.get('numeric_manifest')!=p['manifest']:
            empty=dict(rows=[],status='UNKNOWN_CHART_BINDING',source_date=source_date,**FLAGS)
            return dict(charts=empty,projections=copy.deepcopy(empty))
        chart_key=(source_date,p['source_generation'],p['source_identity']['input_sha256'],descriptor['manifest']['sha256'],descriptor['receipt']['sha256'])
        with self._lock:
            if chart_key in self._chart_cache:return self._chart_cache[chart_key]
        root=getattr(self.source,'original_chart_artifact_root',None) or self.source._a_product_root()
        binding=dict(artifact_root=str(root),manifest=descriptor['manifest'],receipt=descriptor['receipt'])
        manifest=json.loads(self.source._original_chart_bytes(descriptor['manifest'],binding=binding))
        receipt=json.loads(self.source._original_chart_bytes(descriptor['receipt'],binding=binding))
        if manifest.get('RESEARCH_ONLY') is not True or receipt.get('RESEARCH_ONLY') is not True or receipt.get('errors') or not isinstance(manifest.get('samples'),dict):
            raise ValueError('WORKBENCH_CHART_COMPLETION_UNBOUND')
        # Descriptor metadata only. The established single-stock endpoint
        # verifies original projection/HTML/PNG bytes when actually requested.
        chart_rows=[];projection_rows=[]
        for row in p['rows']:
            symbol=row['symbol'];item=manifest['samples'].get(symbol)
            if item is None:continue
            def url(kind,reference):
                return '/api/v4/research/a-share/original-chart/'+kind+'?'+urlencode(dict(date=p['data_date'],symbol=symbol,generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],sha256=reference['sha256']))
            chart_rows.append(dict(symbol=symbol,image_url=url('png',item['PNG']),rows_declared=item['rows']))
            projection=item['projection'];path=Path(projection['path'])
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(Path(root).resolve()):raise ValueError('WORKBENCH_PROJECTION_PATH_INVALID')
            projection_rows.append(dict(symbol=symbol,projection_url=url('projection',projection),sha256=projection['sha256'],bytes=path.stat().st_size,encoding='gzip' if path.suffix=='.gz' else 'identity',row_count=item['rows'],formula_sha256='d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac'))
        common=dict(source_date=source_date,source_generation=p['source_generation'],source_input_sha256=p['source_identity']['input_sha256'],chart_review='UNKNOWN_NOT_REVIEWED',full_stock_PASS=0,**FLAGS)
        result=dict(charts=dict(rows=chart_rows,name_overlay=dict(rows=[dict(symbol=r['symbol'],name=r.get('display_name')) for r in p['rows']]),**common),projections=dict(rows=projection_rows,**common))
        with self._lock:
            self._chart_cache[chart_key]=result
            while len(self._chart_cache)>8:self._chart_cache.pop(next(iter(self._chart_cache)))
        return result

    def company(self,source_date,symbol,revision=None):
        p=self._view(source_date,revision)
        answer=self.source.read_a_daily_company_materials(p['data_date'],symbol,generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'])
        if answer.get('status')!='PARTIAL_RECEIVED':return None
        if answer.get('numeric_manifest')!=p['manifest']:raise ValueError('WORKBENCH_COMPANY_REVISION_MOVED')
        m=answer['materials'];business=m.get('business_reported') or {};finance=m.get('financials_reported') or {};holders=m.get('shareholders_reported') or {}
        holder_history=m.get('provenance_details',{}).get('shareholder_count_history') or []
        holder_current=next((v for v in holder_history if v.get('asof_date')==holders.get('holder_asof')),{})
        def holder_fact(key,fallback,unit):
            original=holder_current.get(key)
            return copy.deepcopy(original) if isinstance(original,dict) else {**fact(fallback,{**holders,'source_url':holders.get('holder_source_url')}),'unit':unit,'missing_reason':None if fallback is not None else 'CANNOT_CONFIRM_MISSING_COMPARABLE_PERIOD'}
        # This is a received-value projection, never a new financial evaluation.
        def fact(value,source):return dict(value=value,unit=source.get('monetary_unit'),source_url=source.get('latest_financial_source_url') or source.get('source_url'),asof_date=source.get('asof_date') or source.get('holder_asof'),disclosed_at=source.get('disclosed_at') or source.get('latest_disclosed_at'),evidence_status=source.get('evidence_status','PARTIAL_RECEIVED'))
        return dict(schema='V4_RECEIVED_COMPANY_VIEW_V1',symbol=symbol,source_date=source_date,observation_date=self._observation_date(source_date),generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],numeric_manifest=p['manifest'],business=dict(summary=fact(business.get('value'),business)),actual_controller=None,latest_financial=dict(report_period=finance.get('latest_report_period'),period_kind=finance.get('latest_period_kind')),facts=[['营收',fact(finance.get('latest_revenue'),finance)],['归母净利润',fact(finance.get('latest_net_profit_parent'),finance)],['股东户数',holder_fact('holder_count',holders.get('holder_count'),'户')],['股东较上期变化',holder_fact('change_accounts',holders.get('holder_change_accounts'),'户')],['股东较上期变化率',holder_fact('change_percent',holders.get('holder_change_percent'),'%')]],reports=dict(metadata_only_count=len(m.get('report_catalog') or []),catalog=m.get('report_catalog') or [],stored_report=m.get('stored_report'),missing_reason=None if m.get('report_catalog') else 'CANNOT_CONFIRM_NO_BOUND_REPORT_METADATA'),received_materials=m,material_ref=answer.get('material_ref'),**FLAGS)

    def observations(self,source_date,observation_date,revision=None):
        p=self._view(source_date,revision)
        if observation_date!=self._observation_date(source_date):raise ValueError('WORKBENCH_OBSERVATION_DATE_CONFLICT')
        pointer=self._observation_commit(observation_date)
        if pointer is None:return dict(latest=None,status='UNKNOWN_NO_BOUND_INTRADAY_SNAPSHOT',source_date=source_date,observation_date=observation_date,**FLAGS)
        value=checked(pointer['snapshot'])
        expected={r['symbol'] for r in p['rows']}
        if (value.get('schema')!='OBSERVATION_SNAPSHOT_VIEW_V1' or value.get('source_date')!=source_date or value.get('observation_date')!=observation_date or value.get('source_generation')!=p['source_generation'] or value.get('input_sha256')!=p['source_identity']['input_sha256'] or value.get('parent_admission_sha256')!=p['source_generation'] or {r['symbol'] for r in value['rows']}!=expected or len(value['rows'])!=len(expected) or value.get('daily_contract_sha256')!=hashlib.sha256(json.dumps(sorted(expected),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest() or any(value.get(k)!=v for k,v in FLAGS.items())):raise ValueError('WORKBENCH_OBSERVATION_IDENTITY_CONFLICT')
        return dict(latest=value,status='STORED_ONLY',commit=pointer,**FLAGS)

    def _observation_commit(self,day):
        root=self.binding.get('observation_root')
        if not root:return None
        path=Path(root)/day/'latest.json'
        if not path.exists():return None
        if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):raise ValueError('WORKBENCH_OBSERVATION_PATH_INVALID')
        pointer=json.loads(path.read_text())
        if pointer.get('schema')!='V4_WORKBENCH_OBSERVATION_COMMIT_V1' or any(pointer.get(k)!=v for k,v in FLAGS.items()):raise ValueError('WORKBENCH_OBSERVATION_COMMIT_INVALID')
        for key in ('snapshot','korea','receipt'):
            if not Path(pointer[key]['path']).resolve().is_relative_to(Path(root).resolve()):raise ValueError('WORKBENCH_OBSERVATION_REFERENCE_ESCAPE')
        receipt=checked(pointer['receipt'])
        if receipt.get('status')!='COMMITTED' or receipt.get('snapshot')!=pointer['snapshot'] or receipt.get('korea')!=pointer['korea']:raise ValueError('WORKBENCH_OBSERVATION_RECEIPT_CONFLICT')
        return pointer

    def source_context(self,source_date,revision=None):
        p=self._view(source_date,revision);observation=self._observation_date(source_date)
        packet=self._module_reference('overseas',observation)
        markets={name:dict(status='UNKNOWN',summary='未绑定该观察日来源') for name in ['US','JP','KR']}
        if packet:
            v=checked(packet)
            if str(v.get('A_date'))!=compact(observation) or v.get('RESEARCH_ONLY') is not True:raise ValueError('WORKBENCH_OVERSEAS_DATE_CONFLICT')
            markets['US']=dict(status=v['status'],summary=f"原生板块 {v.get('native_boards_available','未知')}/{v.get('native_boards_requested','未知')} · 源交易日 {v.get('US_session_date','未知')}",source_asof=v.get('capture_at'),recorded_at=v.get('completed_at'),lateness_seconds=v.get('lateness_seconds'),limitation='环境解释；不是标普11行业或逐股直接受益认证',source=packet)
        jp_ref=self._module_reference('japan',observation)
        if jp_ref:
            jp=checked(jp_ref)
            if not str(jp.get('read_at','')).startswith(observation) or not str(jp.get('source_timestamp','')).startswith(observation):raise ValueError('WORKBENCH_JAPAN_DATE_CONFLICT')
            values=jp.get('values',{})
            markets['JP']=dict(status=jp['status'],summary=f"日经 {values.get('nikkei225_pct','未知')}% / 半导体 {values.get('nikkei_semiconductor_pct','未知')}% · 后到留档",source_asof=jp.get('source_timestamp'),recorded_at=jp.get('read_at'),limitation='；'.join(jp.get('limitations',[])),source=jp_ref)
        commit=self._observation_commit(observation)
        if commit:
            kr=checked(commit['korea'])
            if any(kr.get(k)!=v for k,v in FLAGS.items()):raise ValueError('WORKBENCH_KOREA_SAFETY_CONFLICT')
            for row in kr['indices']:
                if row.get('value') is not None and (not str(row.get('source_asof','')).startswith(observation) or row.get('exchangeTimezoneName')!='Asia/Seoul'):raise ValueError('WORKBENCH_KOREA_DATE_CONFLICT')
            markets['KR']=dict(status=kr['status'],summary=' / '.join(f"{r['symbol']} {r['value'] if r.get('value') is not None else 'UNKNOWN'} ({r.get('change_pct')}%)" if r.get('value') is not None else f"{r['symbol']} UNKNOWN: {r.get('error','未取得')}" for r in kr['indices'])+' · 后到留档',source_asof=' / '.join(r.get('source_asof') or 'UNKNOWN' for r in kr['indices']),recorded_at=kr['recorded_at'],limitation=kr['limitation'],source=commit['korea'])
        return dict(source_date=source_date,observation_date=observation,generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],markets=markets,intraday_status='UNKNOWN',**FLAGS)

    def _owner_execution(self,node_id,observation):
        config=self.binding.get('workflow_receipt_sources',{}).get(str(node_id))
        if not config or not observation:return None
        if config.get('kind')!='A_DAILY_PANEL_RECEIPT':raise ValueError('WORKBENCH_RECEIPT_KIND_UNSUPPORTED')
        root=Path(config['root'])
        if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True)!=root:raise ValueError('WORKBENCH_RECEIPT_ROOT_INVALID')
        path=root/('a-'+compact(observation)+'.json')
        if not path.is_file():return dict(status='CANNOT_CONFIRM_NO_RECEIPT',missing=['原A日更owner尚无本日执行回执'])
        if path.is_symlink() or path.resolve(strict=True)!=path:raise ValueError('WORKBENCH_RECEIPT_PATH_INVALID')
        raw=path.read_bytes();value=json.loads(raw);reference=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())
        if (value.get('schema_version')!='v3.macos.research_panel_receipt.v1' or value.get('target_date')!=compact(observation)
                or value.get('lane')!='A' or any(value.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))):
            raise ValueError('WORKBENCH_OWNER_RECEIPT_IDENTITY_CONFLICT')
        status='BLOCKED' if value.get('status')=='FAILED' else 'PARTIAL_OWNER_READY_PRODUCT_UNCONFIRMED'
        if value.get('status')=='READY' and value.get('exit_code')==0 and not config.get('retry_only'):
            try:
                product=self._view(observation)
                if value.get('sha256')==product['source_identity'].get('selector_artifact_sha256'):status='COMPLETED'
            except (ValueError,OSError,KeyError,TypeError):pass
        return dict(status=status,recorded_at=value.get('finished_at'),error=value.get('error'),evidence=[reference],missing=[] if status=='COMPLETED' else ['原回执不含精确完成时刻；保留UNKNOWN'] if not value.get('finished_at') else [],owner_receipt_status=value.get('status'))

    def workflow(self,source_date=None):
        plan=checked(self.binding['workflow_plan']);nodes=[];error=None
        observation=self._observation_date(source_date) if source_date else self.binding.get('workflow_date')
        try:
            ref=self._module_reference('execution',observation) if observation else None
            ref=ref or self.binding.get('workflow_execution')
            evidence=checked(ref) if ref else {}
            if evidence and observation and evidence.get('observation_date')!=observation:raise ValueError('WORKBENCH_EXECUTION_DATE_CONFLICT')
        except (ValueError,OSError,KeyError,TypeError) as exc:evidence={};error=str(exc)
        for item in plan.get('stages',[]):
            text=item.get('time_bjt','');match=re.match(r'^(\d\d:\d\d)',text)
            actual=evidence.get('nodes',{}).get(str(item['id']),{});node_error=error
            try:
                owner=self._owner_execution(item['id'],observation)
                if owner:actual={**actual,**owner}
            except (ValueError,OSError,KeyError,TypeError) as exc:node_error=str(exc)
            try:
                for reference in actual.get('evidence',[]):checked_bytes(reference)
            except (ValueError,OSError,KeyError,TypeError) as exc:node_error=str(exc)
            status='DEFERRED_USER' if item['id']==3 else 'CANNOT_CONFIRM_BAD_RECEIPT' if node_error else actual.get('status','CANNOT_CONFIRM_NO_RECEIPT')
            now=self._clock()
            if status=='NOT_DUE' and observation and match and (observation<now.date().isoformat() or observation==now.date().isoformat() and match.group(1)<=now.strftime('%H:%M')):
                status='CANNOT_CONFIRM_OVERDUE'
            nodes.append(dict(id='plan_'+str(item['id']),label_zh=item['name'],kind='PLAN_WITH_RECEIPT_STATUS',timezone='Asia/Shanghai',planned_start_local=match.group(1)+':00' if match else None,planned_end_local=None,stage_index=0 if item['id']<=3 else 1 if item['id']<=5 else 2 if item['id']<=9 else 3 if item['id']<=13 else 4,rule_zh=item['action'],execution_status=status,recorded_at=actual.get('recorded_at'),source_asof=actual.get('source_asof'),materials=actual.get('materials',[]),missing=actual.get('missing',[]),error=node_error or actual.get('error'),execution_evidence=actual.get('evidence',[])))
        return dict(time_contract=dict(nodes=nodes),visual_stages=[dict(label=label) for label in ['夜间研究','海外验证','盘前交付','盘中观察','收盘复盘']],source_ref=self.binding['workflow_plan'],execution_ref=ref if not error else None,observation_date=observation,**FLAGS)


def create_workbench_router(source):
    import asyncio
    from fastapi import APIRouter,HTTPException,Request
    from fastapi.responses import StreamingResponse
    from starlette.concurrency import run_in_threadpool
    router=APIRouter(prefix='/workbench',tags=['local-research-workbench'])
    binding_path=os.environ.get('V4_WORKBENCH_HOST_BINDING');binding_sha=os.environ.get('V4_WORKBENCH_HOST_BINDING_SHA256')
    host=ResearchWorkbenchHost(source,checked(dict(path=binding_path,sha256=binding_sha))) if binding_path and binding_sha else None
    if host is not None:router.add_event_handler('shutdown',host.classifications.close)
    def call(method,*args):
        if host is None:raise HTTPException(503,'WORKBENCH_HOST_NOT_CONFIGURED')
        try:return getattr(host,method)(*args)
        except KeyError as error:raise HTTPException(404,str(error)) from error
        except (ValueError,OSError,TypeError) as error:raise HTTPException(409,str(error)) from error
    @router.get('/classifications/{market}')
    def classification_catalog(market:str):return call('classification_catalog',market)
    @router.get('/history')
    def history():return call('history')
    @router.get('/workflow-contract')
    def workflow(source_date:str|None=None):return call('workflow',source_date)
    @router.get('/days/{source_date}/versions')
    def versions(source_date:str,revision:str|None=None):return call('versions',source_date,revision)
    @router.get('/days/{source_date}/events')
    async def events(request:Request,source_date:str):
        # Same stored-completion semantics as the established research SSE.
        # File identity checks only; this never collects or computes research.
        if host is None:raise HTTPException(503,'WORKBENCH_HOST_NOT_CONFIGURED')
        async def stream():
            last=request.headers.get('last-event-id','')
            while not await request.is_disconnected():
                try:
                    value=await run_in_threadpool(host.versions,source_date)
                    if value['event_id']!=last:
                        last=value['event_id']
                        yield 'id: '+last+'\nevent: workbench_completed\ndata: '+json.dumps(value,ensure_ascii=False)+'\n\n'
                except (ValueError,OSError,KeyError,TypeError):yield ': source temporarily unavailable\n\n'
                await asyncio.sleep(2)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
    @router.get('/days/{source_date}')
    def day(source_date:str,revision:str|None=None):return call('day',source_date,revision)
    @router.get('/days/{source_date}/charts')
    def charts(source_date:str,revision:str|None=None):return call('chart_views',source_date,revision)['charts']
    @router.get('/days/{source_date}/projections')
    def projections(source_date:str,revision:str|None=None):return call('chart_views',source_date,revision)['projections']
    @router.get('/days/{source_date}/company/{symbol}')
    def company(source_date:str,symbol:str,revision:str|None=None):return call('company',source_date,symbol,revision)
    @router.get('/days/{source_date}/observations')
    def observations(source_date:str,observation_date:str,revision:str|None=None):return call('observations',source_date,observation_date,revision)
    @router.get('/days/{source_date}/context')
    def context(source_date:str,revision:str|None=None):return call('source_context',source_date,revision)
    return router
