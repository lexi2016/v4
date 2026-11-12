"""Read-only shape adapter for the fixed Dot visual shell, no financial producer."""
from __future__ import annotations
import copy
import gzip
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


def checked_single_display_projection(binding,identity):
    """Check the narrow display-only pair and its observed F10 source."""
    display=binding.get('display_projection')
    if display is None:return None
    import pyarrow as pa
    from ops.research_panel_logical import parquet as pq
    policy=checked(display['policy']);f10=checked(display['f10_source']);roles=display.get('roles',{})
    excluded=policy.get('excluded_from_display_projection')
    if (policy.get('schema')!='a_share_single_display_projection_v1' or not isinstance(excluded,list)
        or len(excluded)!=25 or len(set(excluded))!=25 or binding['symbol'] not in policy.get('authorized_symbols',[])
        or any(policy.get(k)!=v for k,v in FLAGS.items()) or identity.get('display_policy_sha256')!=display['policy']['sha256']
        or identity.get('display_f10_sha256')!=display['f10_source']['sha256'] or set(roles)!={'selector','backtest'}
        or f10.get('symbol')!=binding['symbol'] or f10.get('status')!='OBSERVED' or f10.get('concept_status')!='OBSERVED'
        or display.get('captured_at')!=f10.get('captured_at') or display.get('historical_PIT') is not False):
        raise ValueError('SINGLE_DISPLAY_PROJECTION_IDENTITY_CONFLICT')
    concepts=f10.get('concepts')
    if (not isinstance(concepts,list) or not 0<len(concepts)<=127 or not all(isinstance(x,dict) and isinstance(x.get('name'),str) and x['name'] for x in concepts)
        or display.get('kb_concepts')!='、'.join(x['name'] for x in concepts) or display.get('kb_concept_count')!=len(concepts)):
        raise ValueError('SINGLE_DISPLAY_CONCEPT_SOURCE_CONFLICT')
    result={}
    for role,item in roles.items():
        full=pq.ParquetFile(pa.BufferReader(checked_bytes(item['source_full'])))
        projected=pq.ParquetFile(pa.BufferReader(checked_bytes(item['artifact'])))
        source_schema,projected_schema=full.schema_arrow,projected.schema_arrow
        source_meta=json.loads((source_schema.metadata or {})[b'kb_single_candidate_v1'])
        meta=json.loads((projected_schema.metadata or {})[b'a_share_single_display_projection_v1'])
        expected=[name for name in source_schema.names if name not in excluded]+['kb_concepts','kb_concept_count']
        if (source_meta.get('candidate_generation')!=binding['candidate_generation']
            or meta.get('candidate_generation')!=binding['candidate_generation'] or meta.get('symbol')!=binding['symbol']
            or meta.get('role')!=role or meta.get('source_full_sha256')!=item['source_full']['sha256']
            or meta.get('policy_sha256')!=display['policy']['sha256'] or meta.get('f10_sha256')!=display['f10_source']['sha256']
            or meta.get('captured_at')!=display['captured_at'] or meta.get('historical_PIT') is not False
            or any(meta.get(k)!=v for k,v in FLAGS.items()) or projected_schema.names!=expected
            or 'kb_hold_volume_ok_reason' not in expected or projected_schema.field('kb_concepts').type!=pa.string()
            or projected_schema.field('kb_concept_count').type!=pa.int8()
            or full.metadata.num_rows!=projected.metadata.num_rows or projected.metadata.num_rows!=item.get('rows')
            or len(projected_schema)!=item.get('columns')):
            raise ValueError('SINGLE_DISPLAY_PROJECTION_SCHEMA_CONFLICT:'+role)
        values=projected.read(columns=['kb_concepts','kb_concept_count']).to_pylist()
        if (not values or any(x['kb_concepts'] is not None or x['kb_concept_count'] is not None for x in values[:-1])
            or values[-1]!={'kb_concepts':display['kb_concepts'],'kb_concept_count':display['kb_concept_count']}):
            raise ValueError('SINGLE_DISPLAY_CONCEPT_HISTORY_CONFLICT:'+role)
        result[role+'_columns']=len(projected_schema)
    return {**result,'f10_source_sha256':display['f10_source']['sha256'],
            'captured_at':display['captured_at'],'kb_concepts':display['kb_concepts'],
            'kb_concept_count':display['kb_concept_count'],'historical_PIT':False}


def checked_confirmed_gap(binding, identity):
    """Verify the optional eight-field pair and its separate daily diagnostics."""
    gap=binding.get('confirmed_gap')
    if gap is None:return None
    import pyarrow as pa
    from ops.research_panel_logical import parquet as pq
    policy=checked(gap['contract']); fields=policy.get('new_fields',{}); keys=policy.get('diagnostic_keys',[])
    n_binding=binding.get('n_structure')
    if n_binding is not None:
        contract=checked(n_binding['contract']);receipt=checked(n_binding['receipt'])
        checkpoint=checked(n_binding['checkpoint']);checked_bytes(n_binding['values'])
        item=receipt.get('symbols',{}).get(binding['symbol'],{})
        if (contract.get('schema')!='a_share_kb_n_structure_v1' or contract.get('research_only') is not True
            or any(contract.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))
            or identity.get('n_structure_contract_sha256')!=n_binding['contract']['sha256']
            or identity.get('n_structure_helper_sha256')!=receipt.get('helper_sha256')
            or receipt.get('contract_sha256')!=n_binding['contract']['sha256']
            or receipt.get('source_generation')!=binding['source_generation']
            or receipt.get('source_input_sha256')!=binding['source_input_sha256']
            or receipt.get('snapshot_file_sha256')!=identity.get('snapshot_sha256')
            or item.get('source_candidate_generation')!=identity.get('n_structure_prior_candidate_generation')
            or item.get('n_values_sha256')!=n_binding['values']['sha256']
            or item.get('checkpoint_file_sha256')!=n_binding['checkpoint']['sha256']
            or checkpoint.get('checkpoint_sha256')!=item.get('checkpoint_state_sha256')
            or checkpoint.get('symbol')!=binding['symbol']):
            raise ValueError('SINGLE_N_SOURCE_IDENTITY_CONFLICT')
        keys=[*keys,'kb_n_structure']
    if (policy.get('schema')!='a_share_kb_confirmed_gap_v1' or len(fields)!=8 or len(keys)!=(25 if n_binding else 24)
        or identity.get('confirmed_gap_contract_sha256')!=gap['contract']['sha256']
        or gap.get('calendar_sha256') is not None or gap.get('calendar_status')!='CANNOT_CONFIRM'
        or any(policy.get(k)!=v for k,v in FLAGS.items())):
        raise ValueError('SINGLE_CONFIRMED_GAP_CONTRACT_CONFLICT')
    old_gate=checked(gap['prior_source_gate']);new_gate=checked(binding['source_gate_receipt'])
    required_sources={'ops/research_panel_qfq.py','ops/kb_signal_authority.py','ops/kb_confirmed_gap.py',
                      'ops/kb_panel_rebuild_brick.py','ops/kb_panel_signal_components.py'}
    if n_binding:
        required_sources.update({'ops/kb_hold_score.py','contracts/a_share_kb_hold_score_v1.json',
                                 'ops/kb_n_structure.py','contracts/a_share_kb_n_structure_v1.json'})
    if (old_gate.get('status')!='PASS_RELOCATED_SOURCE_GATE' or new_gate.get('status')!='PASS_RELOCATED_SOURCE_GATE'
        or new_gate.get('matches_frozen_input_sha256') is not True or not required_sources.issubset(new_gate.get('source_code_refs',{}))
        or new_gate.get('prior_source_gate')!=gap['prior_source_gate']
        or new_gate.get('canonical_input_sha256')!=binding['source_input_sha256']
        or new_gate.get('snapshot',{}).get('sha256')!=identity.get('snapshot_sha256')
        or new_gate.get('relocation_ref')!=binding.get('source_relocation')
        or any(identity.get('source_sha256',{}).get(name)!=ref.get('sha256')
               for name,ref in new_gate.get('source_code_refs',{}).items())):
        raise ValueError('SINGLE_CONFIRMED_GAP_SOURCE_GATE_CONFLICT')
    sources=gap.get('source_candidates',{})
    if set(sources)!={'rebuild','components'} or set(gap.get('source_receipts',{}))!={'rebuild','components','diagnostics'}:
        raise ValueError('SINGLE_CONFIRMED_GAP_SOURCE_SET_CONFLICT')
    for ref in [*sources.values(),*gap['source_receipts'].values(),gap['source_diagnostics'],*gap['source_contracts'].values()]:checked_bytes(ref)
    if identity.get('confirmed_gap_source_sha256')!={'rebuild':sources['rebuild']['sha256'],
        'components':sources['components']['sha256'],'diagnostics':gap['source_diagnostics']['sha256']}:
        raise ValueError('SINGLE_CONFIRMED_GAP_SOURCE_IDENTITY_CONFLICT')
    if set(gap['source_contracts'])!=set(policy.get('source_contracts',[])) or any(
        identity.get('source_sha256',{}).get(name)!=ref['sha256'] for name,ref in gap['source_contracts'].items()):
        raise ValueError('SINGLE_CONFIRMED_GAP_SOURCE_CONTRACT_CONFLICT')
    sidecar=pq.read_table(pa.BufferReader(checked_bytes(gap['diagnostics'])))
    meta=json.loads((sidecar.schema.metadata or {})[b'v4.a_share.kb_gap_diagnostics.v1'])
    if (sidecar.column_names!=['ts_code','trade_date','diagnostics_json','prefix_input_sha256']
        or len(sidecar)!=binding['rows'] or meta.get('candidate_generation')!=binding['candidate_generation']
        or meta.get('symbol')!=binding['symbol'] or meta.get('confirmed_gap_contract_sha256')!=gap['contract']['sha256']
        or meta.get('source_generation')!=binding['source_generation'] or meta.get('source_input_sha256')!=binding['source_input_sha256']
        or meta.get('freeze_snapshot_sha256')!=identity.get('snapshot_sha256')
        or meta.get('calendar_sha256') is not None or meta.get('calendar_status')!='CANNOT_CONFIRM'
        or set(meta.get('diagnostic_keys',[]))!=set(keys)):
        raise ValueError('SINGLE_CONFIRMED_GAP_DIAGNOSTIC_IDENTITY_CONFLICT')
    if n_binding and (meta.get('n_structure_enabled') is not True
        or meta.get('n_structure_contract_sha256')!=n_binding['contract']['sha256']
        or meta.get('n_structure_helper_sha256')!=identity.get('n_structure_helper_sha256')):
        raise ValueError('SINGLE_N_DIAGNOSTIC_IDENTITY_CONFLICT')
    n_values=pq.read_table(pa.BufferReader(checked_bytes(n_binding['values']))).to_pylist() if n_binding else None
    if n_values is not None and len(n_values)!=len(sidecar):
        raise ValueError('SINGLE_N_VALUES_LENGTH_CONFLICT')
    rows=sidecar.to_pylist(); dates=[]; seen_dates=set()
    for i,row in enumerate(rows):
        date=str(row['trade_date']);diag=json.loads(row['diagnostics_json']);prefix=row['prefix_input_sha256']
        if (row['ts_code']!=binding['symbol'] or len(date)!=8 or not date.isdigit() or date in seen_dates
            or set(diag)!=set(keys) or not isinstance(prefix,str) or not re.fullmatch(r'[0-9a-f]{64}',prefix)):
            raise ValueError('SINGLE_CONFIRMED_GAP_DIAGNOSTIC_ROW_CONFLICT')
        if n_values is not None:
            source=n_values[i];n=diag['kb_n_structure']
            if (source.get('ts_code')!=binding['symbol'] or str(source.get('trade_date'))!=date
                or json.loads(source['kb_n_structure_json'])!=n
                or n.get('rule_sha256')!=n_binding['contract']['sha256']
                or n.get('helper_sha256')!=identity['n_structure_helper_sha256']
                or n.get('input_sha256')!=binding['source_input_sha256']
                or n.get('generation_id')!=binding['source_generation']
                or n.get('prefix_input_sha256')!=source.get('prefix_input_sha256')):
                raise ValueError('SINGLE_N_DIAGNOSTIC_ROW_CONFLICT')
        dates.append(date);seen_dates.add(date)
    if dates!=sorted(dates):raise ValueError('SINGLE_CONFIRMED_GAP_DATES_NOT_ORDERED')
    roles=binding['display_projection']['roles']; tables={}
    for role in ('selector','backtest'):
        table=pq.read_table(pa.BufferReader(checked_bytes(roles[role]['source_full'])))
        if ([str(v) for v in table['trade_date'].to_pylist()]!=dates or any(v!=binding['symbol'] for v in table['ts_code'].to_pylist())
            or set(fields)-set(table.column_names)):
            raise ValueError('SINGLE_CONFIRMED_GAP_ROLE_KEYS_CONFLICT:'+role)
        tables[role]=table
    for name in [*fields,'kb_rebuild']:
        if not tables['selector'][name].equals(tables['backtest'][name]):
            raise ValueError('SINGLE_CONFIRMED_GAP_ROLE_VALUES_CONFLICT:'+name)
    if n_values is not None:
        score_names=['kb_hold_close_up','kb_hold_above_bbi','kb_hold_volume_ok','kb_hold_trend_up','kb_hold_j_not_dead',
                     'kb_hold_trend_up_reason','kb_hold_score','kb_hold_score_min','kb_hold_score_max','kb_hold_score_status']
        for name in score_names:
            if not tables['selector'][name].equals(tables['backtest'][name]):
                raise ValueError('SINGLE_N_ROLE_SCORE_CONFLICT:'+name)
        scored=tables['selector'].select(score_names).to_pylist()
        for source,score in zip(n_values,scored):
            values=[score[name] for name in score_names[:5]];lo=sum(v is True for v in values);unknown=sum(v is None for v in values)
            if (score['kb_hold_trend_up']!=source['kb_hold_trend_up']
                or score['kb_hold_trend_up_reason']!=source['kb_hold_trend_up_reason']
                or score['kb_hold_score_min']!=lo or score['kb_hold_score_max']!=lo+unknown
                or score['kb_hold_score']!=(lo if not unknown else None)
                or score['kb_hold_score_status']!=('COMPLETE' if not unknown else 'PARTIAL_UNKNOWN')):
                raise ValueError('SINGLE_N_SCORE_VALUE_CONFLICT')
    return {'contract_sha256':gap['contract']['sha256'],'diagnostics_sha256':gap['diagnostics']['sha256'],
            'fields':sorted(fields),'calendar_status':'CANNOT_CONFIRM',
            'n_structure_contract_sha256':n_binding['contract']['sha256'] if n_binding else None}


def checked_relocated_parquet(reference, relocation_ref):
    """Read one declared historical source only from its SHA-identical backup."""
    relocation=checked(relocation_ref)
    mappings=relocation.get('mappings')
    if (relocation.get('schema')!='v4.single_stock_history_source_relocation.v1'
        or relocation.get('mode')!='EXPLICIT_SHA_BOUND_READ_ONLY' or relocation.get('SEARCH_FALLBACK') is not False
        or any(relocation.get(k)!=v for k,v in FLAGS.items()) or not isinstance(mappings,list) or len(mappings)!=1):
        raise ValueError('SINGLE_HISTORY_RELOCATION_INVALID')
    item=mappings[0]
    if (item.get('original_path')!=reference.get('path') or item.get('expected_sha256')!=reference.get('sha256')
        or item.get('physical_sha256')!=reference.get('sha256')):
        raise ValueError('SINGLE_HISTORY_RELOCATION_SOURCE_MISMATCH')
    raw=checked_bytes({'path':item['physical_path'],'sha256':item['physical_sha256']})
    import pyarrow as pa
    from ops.research_panel_logical import parquet as pq
    schema=pq.read_schema(pa.BufferReader(raw))
    metadata=json.loads((schema.metadata or {})[b'kb_single_candidate_v1'])
    if (len(schema)!=item.get('parquet_columns') or metadata.get('candidate_generation')!=item.get('candidate_generation')
        or metadata.get('source_generation')!=item.get('source_generation')):
        raise ValueError('SINGLE_HISTORY_RELOCATION_FOOTER_MISMATCH')
    return raw


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
        from infrastructure.research_workbench_quote_reference import SourceCloseReferences
        self._quote_references=SourceCloseReferences()
        from infrastructure.research_classification_view import ReceivedClassificationStore
        self.classifications=ReceivedClassificationStore(binding.get('classification_store_root'))
        self._lock=threading.RLock()
        if binding.get('schema')!='V4_MAC_WORKBENCH_BINDING_V1' or binding.get('RESEARCH_ONLY') is not True or any(binding.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):
            raise ValueError('WORKBENCH_HOST_BINDING_REQUIRED')
        self.skill_r2=None
        if binding.get('skill_r2_d28'):
            from infrastructure.research_workbench_skill_r2 import SkillR2Workbench
            self.skill_r2=SkillR2Workbench(binding['skill_r2_d28'])

    def _index(self):
        return json.loads((self.source._a_product_root()/'index.json').read_text())

    def _is_skill_date(self,source_date):
        if self.skill_r2 is None or source_date!='2026-10-28':return False
        if '20261028' in self._index().get('dates',{}):raise ValueError('SKILL_R2_EXISTING_DATE_PRODUCT_CONFLICT')
        return True

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

    def v192_group(self,source_date,revision=None):
        """Independent same-source candidate group; never changes four-group rows."""
        p=self._view(source_date,revision)
        product=self.source.read_a_daily_product(p['data_date'],include_display_names=False)
        if (product.get('manifest')!=p['manifest'] or product.get('source_generation')!=p['source_generation']
                or product.get('source_identity')!=p['source_identity']):
            raise ValueError('V192_NUMERIC_PRODUCT_MOVED')
        from infrastructure.research_workbench_v192 import project
        result=project(self.source,product,source_date,self._observation_date(source_date))
        try:available={row['symbol'] for row in self.chart_views(source_date,revision)['projections'].get('rows',[])}
        except (ValueError,OSError,KeyError,TypeError):available=set()
        for row in result['rows']:row['original_chart_status']='MATERIALIZED' if row['symbol'] in available else 'NOT_MATERIALIZED'
        # The existing source-close reader owns validation and the selector
        # read. Its scope is part of its cache key; never mutate the 371 rows.
        if result['status'] in {'READY','READY_EMPTY','PARTIAL'}:
            try:result['source_close_reference']=self._quote_references.read({**product,'rows':result['rows']})
            except (ValueError,OSError,KeyError,TypeError) as error:
                result['source_close_reference']=dict(status='CANNOT_CONFIRM',reason=str(error),rows={})
        if result['status'] in {'READY','READY_EMPTY','PARTIAL'}:
            from infrastructure.research_workbench_v192_assets import load
            bound=load(self.source,product,result.get('source_artifact_sha256'))
            if bound:
                complete=set(bound['module']['completed_symbols'])
                for row in result['rows']:
                    if row['symbol'] in complete:
                        row['original_chart_status']='MATERIALIZED'
                        sample=bound['manifest']['samples'][row['symbol']]
                        kind='png' if sample.get('PNG') else 'html'
                        query=urlencode(dict(revision=p['source_generation'],model_sha256=result['source_artifact_sha256'],sha256=sample['PNG' if kind=='png' else 'html']['sha256'],date=p['data_date'],symbol=row['symbol'],generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256']))
                        row['v192_assets']=dict(model_artifact_sha256=result['source_artifact_sha256'],
                            selector_sha256=result['selector_sha256'],chart=dict(symbol=row['symbol'],
                            source_date=source_date,source_generation=p['source_generation'],source_input_sha256=p['source_identity']['input_sha256'],
                            chart_review='UNKNOWN_NOT_REVIEWED',full_stock_PASS=0,rows_declared=sample['rows'],
                            **{('image_url' if kind=='png' else 'html_url'):f"/api/v4/research/workbench/days/{source_date}/v192-assets/{row['symbol']}/{kind}?{query}"}))
        return result

    def v192_stock_assets(self,source_date,symbol,model_sha256,revision=None,kind=None,digest=None):
        model=self.v192_group(source_date,revision)
        if (model.get('source_artifact_sha256')!=model_sha256
                or not any(row['symbol']==symbol and row.get('v192_assets') for row in model['rows'])):
            raise KeyError('V192_SYMBOL_ASSETS_NOT_BOUND')
        p=self._view(source_date,revision)
        product=self.source.read_a_daily_product(p['data_date'],include_display_names=False)
        from infrastructure.research_workbench_v192_assets import load,chart
        bound=load(self.source,product,model_sha256)
        value=chart(self.source,product,bound,symbol,kind=kind,digest=digest)
        if kind is not None:return value['_asset_bytes'],{'html':'text/html; charset=utf-8','png':'image/png','projection':'application/octet-stream'}[kind]
        base=f'/api/v4/research/workbench/days/{source_date}/v192-assets/{symbol}/'
        value['assets']={key:{**ref,'url':base+key+'?'+urlencode(dict(revision=p['source_generation'],model_sha256=model_sha256,sha256=ref['sha256']))} for key,ref in value['assets'].items()}
        return value

    def _v192_version(self,source_date):
        from infrastructure.research_workbench_v192 import version
        try:return dict(model=version(self._observation_date(source_date)),assets=self._index().get('v192_assets',{}).get(compact(source_date)))
        except (ValueError,OSError,KeyError,TypeError) as error:return dict(status='CANNOT_CONFIRM',reason=str(error))

    def daily_score_action(self,source_date,symbol,revision=None):
        """Read an exact-day materialized score; no market reads or computation."""
        p=self._view(source_date,revision)
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',symbol):raise ValueError('SCORE_SYMBOL_INVALID')
        common=dict(schema='v4.workbench.daily_kb_research.v1',source_date=source_date,
            observation_date=self._observation_date(source_date),symbol=symbol,
            generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],
            numeric_manifest=p['manifest'],historical_PIT=False,**FLAGS)
        root=self.source._a_product_root()
        descriptor=json.loads((root/'index.json').read_bytes()).get('score_action',{}).get(compact(source_date)) if root else None
        from infrastructure.research_workbench_score_action import read_score_action
        value=(read_score_action(root,descriptor,p,source_date,symbol) if descriptor and descriptor.get('index')
            else dict(status='UNKNOWN',reason=(descriptor or {}).get('reason','SCORE_NOT_MATERIALIZED_FOR_DATE'),row=None))
        if value.get('status')=='UNKNOWN' and value.get('row') is None:
            model=self.v192_group(source_date,revision)
            if any(row['symbol']==symbol and row.get('v192_assets') for row in model['rows']):
                product=self.source.read_a_daily_product(p['data_date'],include_display_names=False)
                from infrastructure.research_workbench_v192_assets import load
                bound=load(self.source,product,model['source_artifact_sha256'])
                value=read_score_action(Path(bound['module']['artifact_root']),bound['module']['score_action'],p,source_date,symbol)
        return dict(**value,**common)

    def single_stock_research(self,source_date,symbol,revision=None):
        """A separately bound, precomputed single-stock research artifact."""
        if source_date!='2026-10-30':return self.daily_score_action(source_date,symbol,revision)
        if (source_date=='2026-10-30' and symbol not in {'002865.SZ','301048.SZ','300206.SZ'}
                and self.binding.get('top200_research_panel_r3')):
            from infrastructure.research_workbench_top200 import metadata as scoped_metadata
            p=self._view(source_date,revision)
            scoped=scoped_metadata(self.binding,p,self.top200(source_date,revision),source_date,symbol,self._observation_date(source_date))
            if scoped is not None:return scoped
        if source_date!='2026-10-30' or symbol not in {'002865.SZ','301048.SZ','300206.SZ'}:raise KeyError('SINGLE_STOCK_NOT_BOUND')
        p=self._view(source_date,revision);observation=self._observation_date(source_date)
        ref=self.binding.get('single_stock_research_by_symbol',{}).get(symbol)
        if not ref and symbol=='002865.SZ':ref=self.binding.get('single_stock_research')
        if not ref:raise KeyError('SINGLE_STOCK_NOT_BOUND')
        value=checked(ref)
        pool_member=any(row.get('symbol')==symbol for row in p.get('rows',[]))
        if (value.get('schema')!='v4.workbench.single_kb_binding.v1' or value.get('symbol')!=symbol
            or value.get('source_date')!=source_date or value.get('observation_date')!=observation
            or observation!='2026-11-02' or value.get('source_generation')!=p['source_generation']
            or value.get('source_input_sha256')!=p['source_identity']['input_sha256']
            or value.get('numeric_manifest')!=p['manifest'] or value.get('candidate_pool_member') is not pool_member
            or value.get('historical_PIT') is not False or any(value.get(k)!=v for k,v in FLAGS.items())):
            raise ValueError('SINGLE_STOCK_SOURCE_IDENTITY_CONFLICT')
        identity=value.get('candidate_identity')
        if not isinstance(identity,dict) or hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()!=value.get('candidate_generation'):
            raise ValueError('SINGLE_STOCK_GENERATION_CONFLICT')
        confirmed_gap=checked_confirmed_gap(value,identity)
        gate=checked(value['source_gate_receipt']);relocation=checked(value['source_relocation'])
        if (gate.get('status')!='PASS_RELOCATED_SOURCE_GATE' or gate.get('canonical_input_sha256')!=value['source_input_sha256']
            or gate.get('relocation_ref')!=value['source_relocation'] or relocation.get('mode')!='ISOLATED_READ_ONLY'
            or identity.get('relocation_sha256')!=value['source_relocation']['sha256']
            or identity.get('source_gate_sha256')!=value['source_gate_receipt']['sha256']):
            raise ValueError('SINGLE_STOCK_SOURCE_GATE_CONFLICT')
        score_ref=value.get('hold_score_contract')
        score_sha=None
        if score_ref is not None:
            score_contract=checked(score_ref);score_sha=score_ref['sha256']
            if (score_contract.get('schema')!='a_share_kb_hold_score_v1'
                or score_contract.get('RESEARCH_ONLY') is not True
                or any(score_contract.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))
                or identity.get('score_contract_sha256')!=score_sha
                or identity.get('score_engine_sha256')!=value.get('hold_score_engine_sha256')):
                raise ValueError('SINGLE_STOCK_HOLD_SCORE_IDENTITY_CONFLICT')
        supplemental_ref=value.get('supplemental_contract')
        supplemental_sha=None
        if supplemental_ref is not None:
            supplemental=checked(supplemental_ref);supplemental_sha=supplemental_ref['sha256']
            if (supplemental.get('schema')!='a_share_kb_supplemental_signals_v1'
                or supplemental.get('RESEARCH_ONLY') is not True
                or any(supplemental.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))
                or identity.get('supplemental_contract_sha256')!=supplemental_sha):
                raise ValueError('SINGLE_STOCK_SUPPLEMENTAL_IDENTITY_CONFLICT')
        action_ref=value.get('action_contract')
        action_sha=None
        if action_ref is not None:
            action=checked(action_ref);action_sha=action_ref['sha256']
            if (action.get('schema')!='a_share_kb_action_v1'
                or action.get('RESEARCH_ONLY') is not True
                or any(action.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))
                or identity.get('action_contract_sha256')!=action_sha):
                raise ValueError('SINGLE_STOCK_ACTION_IDENTITY_CONFLICT')
        yidong_ref=value.get('yidong_contract')
        yidong_sha=None
        if yidong_ref is not None:
            yidong=checked(yidong_ref);yidong_sha=yidong_ref['sha256']
            if (yidong.get('schema')!='a_share_kb_yidong_v1'
                or yidong.get('RESEARCH_ONLY') is not True
                or any(yidong.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))
                or identity.get('yidong_contract_sha256')!=yidong_sha):
                raise ValueError('SINGLE_STOCK_YIDONG_IDENTITY_CONFLICT')
        if score_ref is not None and supplemental_ref is not None:
            inventory=value.get('field_inventory');score_fields=inventory.get('hold_score_fields') if isinstance(inventory,dict) else None
            extra_fields=inventory.get('supplemental_fields') if isinstance(inventory,dict) else None
            action_fields=inventory.get('action_fields',[]) if isinstance(inventory,dict) else []
            yidong_fields=inventory.get('yidong_fields',[]) if isinstance(inventory,dict) else []
            declared_score=[name for names in score_contract.get('materialized_fields',{}).values() for name in names]
            declared_extra=[item['name'] for item in supplemental.get('fields',[])]
            declared_action=list(action.get('materialized_fields',{})) if action_ref is not None else []
            declared_yidong=list(yidong.get('materialized_fields',{})) if yidong_ref is not None else []
            gap_fields=inventory.get('confirmed_gap_fields',[]) if isinstance(inventory,dict) else []
            if (inventory!=identity.get('field_inventory') or not isinstance(score_fields,list) or not isinstance(extra_fields,list)
                or len(score_fields)!=len(set(score_fields)) or set(score_fields)!=set(declared_score)
                or len(extra_fields)!=len(set(extra_fields)) or set(extra_fields)!=set(declared_extra)
                or not isinstance(action_fields,list) or len(action_fields)!=len(set(action_fields)) or set(action_fields)!=set(declared_action)
                or not isinstance(yidong_fields,list) or len(yidong_fields)!=len(set(yidong_fields)) or set(yidong_fields)!=set(declared_yidong)
                or not isinstance(gap_fields,list) or len(gap_fields)!=len(set(gap_fields))
                or set(gap_fields)!=(set(confirmed_gap['fields']) if confirmed_gap else set())
                or inventory.get('base_kb_fields')!=value.get('fields_count')
                or inventory.get('total_new_fields')!=len(score_fields)+len(extra_fields)+len(action_fields)+len(yidong_fields)+len(gap_fields)
                or inventory.get('total_derived_fields')!=value['fields_count']+len(score_fields)+len(extra_fields)+len(action_fields)+len(yidong_fields)+len(gap_fields)):
                raise ValueError('SINGLE_STOCK_FIELD_INVENTORY_CONFLICT')
        display_projection=checked_single_display_projection(value,identity)
        assets=value.get('assets',{})
        if set(assets) not in ({'kb','projection','html'}, {'kb','projection','html','history','company'}):raise ValueError('SINGLE_STOCK_ASSET_SET_INVALID')
        for kind in ('history','company'):
            if kind in assets and identity.get(kind+'_asset_sha256')!=assets[kind].get('sha256'):
                raise ValueError('SINGLE_STOCK_RESEARCH_ASSET_IDENTITY_CONFLICT')
        relocation_ref=value.get('history_source_relocation')
        if relocation_ref:
            checked(relocation_ref)
            if identity.get('history_source_relocation_sha256')!=relocation_ref['sha256']:
                raise ValueError('SINGLE_HISTORY_RELOCATION_IDENTITY_CONFLICT')
        base=f'/api/v4/research/workbench/days/{source_date}/single-research/{symbol}/assets/'
        rendered={}
        for kind,item in assets.items():
            if (not isinstance(item,dict) or not isinstance(item.get('path'),str)
                or not isinstance(item.get('sha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',item['sha256'])
                or not isinstance(item.get('bytes'),int) or item['bytes']<1):raise ValueError('SINGLE_STOCK_ASSET_INVALID')
            rendered[kind]={k:v for k,v in item.items() if k!='path'} | {'url':base+kind+'?'+urlencode(dict(revision=p['source_generation'],sha256=item['sha256']))}
        return dict(schema='v4.workbench.single_kb_research.v1',status='READY_FOR_RESEARCH_REVIEW',
            source_date=source_date,observation_date=observation,symbol=symbol,name=value['name'],
            generation=p['source_generation'],input_sha256=value['source_input_sha256'],numeric_manifest=p['manifest'],
            candidate_generation=value['candidate_generation'],candidate_pool_member=pool_member,historical_PIT=False,
            fields_count=value['fields_count'],rows=value['rows'],source_gate='PASS_RELOCATED_SOURCE_GATE',
            field_inventory=value.get('field_inventory'),display_projection=display_projection,
            confirmed_gap=confirmed_gap,
            hold_score_contract_sha256=score_sha,hold_score_engine_sha256=value.get('hold_score_engine_sha256'),
            supplemental_contract_sha256=supplemental_sha,action_contract_sha256=action_sha,yidong_contract_sha256=yidong_sha,
            reused_candidate_sha256=identity.get('feedback_reused_candidate_sha256') or identity.get('source_candidate_sha256'),
            signal_component_facts_sha256=identity.get('signal_component_facts_sha256'),
            assets=rendered,**FLAGS)

    def single_stock_asset(self,source_date,symbol,kind,digest,revision=None,panel_revision=None):
        metadata=self.single_stock_research(source_date,symbol,revision)
        if metadata.get('schema')=='v4.workbench.scoped_kb_research.v1':
            if panel_revision!=metadata['panel_generation']:raise ValueError('SCOPED_PANEL_REVISION_CONFLICT')
            from infrastructure.research_workbench_top200 import asset as scoped_asset
            return scoped_asset(self.binding,self._view(source_date,revision),self.top200(source_date,revision),source_date,symbol,kind,digest)
        if panel_revision is not None:raise ValueError('SCOPED_PANEL_REVISION_CONFLICT')
        if kind not in {'kb','projection','html','history','company'}:raise KeyError('SINGLE_STOCK_ASSET_NOT_BOUND')
        bound=self.binding.get('single_stock_research_by_symbol',{}).get(symbol)
        if not bound and symbol=='002865.SZ':bound=self.binding['single_stock_research']
        binding=checked(bound);ref=binding['assets'][kind]
        if digest!=ref['sha256']:raise ValueError('SINGLE_STOCK_ASSET_SHA_CONFLICT')
        raw=checked_bytes(ref)
        if len(raw)!=ref['bytes']:raise ValueError('SINGLE_STOCK_ASSET_SIZE_CONFLICT')
        if kind in {'history','company'}:
            payload=gzip.decompress(raw)
            if len(payload)!=ref.get('decoded_bytes') or len(payload)>8*1024*1024:raise ValueError('SINGLE_STOCK_RESEARCH_ASSET_SIZE_CONFLICT')
            data=json.loads(payload)
            if (data.get('symbol')!=symbol or data.get('data_date')!=compact(source_date)
                or data.get('source_generation')!=metadata['generation'] or data.get('input_sha256')!=metadata['input_sha256']
                or data.get('numeric_manifest')!=metadata['numeric_manifest'] or data.get('historical_PIT') is not False
                or data.get('source_candidate',{}).get('sha256')!=metadata['reused_candidate_sha256']
                or any(data.get(k)!=v for k,v in FLAGS.items())):
                raise ValueError('SINGLE_STOCK_RESEARCH_ASSET_SOURCE_CONFLICT')
            refs=[data['source_candidate']]
            if kind=='history':
                relocation=binding.get('history_source_relocation')
                if data.get('history_source_relocation')!=relocation:raise ValueError('SINGLE_HISTORY_RELOCATION_BINDING_CONFLICT')
                if relocation:checked_relocated_parquet(data['source_selector'],relocation)
                else:checked_bytes(data['source_selector'])
                refs.extend([data['source_view'],data['market_calendar']])
            else:refs.extend([data['received_ref'],*[x['file'] for x in data['source_refs'].values()]])
            for source in refs:checked_bytes(source)
        return raw,{'kb':'application/octet-stream','projection':'application/octet-stream','html':'text/html; charset=utf-8','history':'application/octet-stream','company':'application/octet-stream'}[kind]

    def f10(self,source_date,symbol,revision=None):
        """Read the existing completion-index F10 snapshot, never acquire it on GET."""
        p=self._view(source_date,revision)
        if not any(row.get('symbol')==symbol for row in p.get('rows',[])):
            self.single_stock_research(source_date,symbol,revision)
        root=self.source._a_product_root()
        if root is None:raise ValueError('F10_PRODUCT_ROOT_UNBOUND')
        index=json.loads((root/'index.json').read_bytes());day=compact(source_date);ref=index.get('f10',{}).get(day)
        common=dict(symbol=symbol,data_date=day,source_generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],historical_PIT=False,**FLAGS)
        if not ref:return dict(status='NOT_MATERIALIZED',**common)
        receipt=self.source._a_product_reference(ref)
        if (receipt.get('schema')!='v4.a_share.f10_daily_receipt.v1' or receipt.get('data_date')!=day
            or receipt.get('source_generation')!=p['source_generation'] or receipt.get('input_sha256')!=p['source_identity']['input_sha256']
            or receipt.get('status') not in {'COMPLETE','PARTIAL'}):raise ValueError('F10_RECEIPT_SOURCE_CONFLICT')
        checkpoint=self.source._a_product_reference(receipt['checkpoint']);identity=checkpoint.get('identity',{})
        if (identity.get('data_date')!=day or identity.get('source_generation')!=p['source_generation']
            or identity.get('input_sha256')!=p['source_identity']['input_sha256']):raise ValueError('F10_CHECKPOINT_SOURCE_CONFLICT')
        stock_ref=checkpoint.get('items',{}).get(symbol)
        if not stock_ref:return dict(status='CANNOT_CONFIRM_SOURCE_GAP',receipt=ref,**common)
        stock=self.source._a_product_reference(stock_ref)
        if stock.get('symbol')!=symbol or stock.get('status')!='OBSERVED' or stock.get('historical_PIT') is not False:
            raise ValueError('F10_STOCK_SOURCE_CONFLICT')
        return dict(status='OBSERVED',receipt=ref,stock_ref=stock_ref,
            f10={k:stock.get(k) for k in ('captured_at','source_updated_date','finance_updated_date','concepts','concept_status','industry','financials','source_text_sha256')},**common)

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
        if self._is_skill_date(source_date):
            result=self.skill_r2.versions(self._observation_date(source_date),revision)
            def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            index=self._index()
            result['modules']['catalog']=digest({key:index.get(key,{})for key in ('dates','attempts')})
            result['modules']['top200']=digest(index.get('top200',{}).get(compact(source_date)))
            result['modules']['score_action']=digest(index.get('score_action',{}).get(compact(source_date)))
            result['modules']['v192']=digest(self._v192_version(source_date))
            result['event_id']=digest(result['modules'])
            return result
        p=self._view(source_date,revision);observation=self._observation_date(source_date)
        def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        def version(module,day):
            try:return self._module_reference(module,day)
            except (ValueError,OSError,KeyError,TypeError) as error:return {'error':str(error)}
        try:quote=self._observation_commit(observation)
        except (ValueError,OSError,KeyError,TypeError) as error:quote={'error':str(error)}
        modules=dict(catalog=digest({key:self._index().get(key,{})for key in ('dates','attempts')}),top200=digest(self._index().get('top200',{}).get(compact(source_date))),classification=self.classifications.version(),list=digest([p['manifest'],self._index().get('display_names',{}).get(compact(source_date))]),
                     company=digest([self._index().get('latest_date'),{key:{day:value for day,value in self._index().get(key,{}).items() if day<=compact(source_date)} for key in ('company_materials','company_materials_versions')}]),
                     statistics=digest(version('statistics',source_date)),observations=digest(quote),
                     score_action=digest(self._index().get('score_action',{}).get(compact(source_date))),
                     v192=digest(self._v192_version(source_date)),
                     context=digest([version('overseas',observation),version('japan',observation),quote.get('korea') if quote else None]),
                     workflow=digest([self.binding.get('workflow_plan'),version('execution',observation),self.binding.get('workflow_execution'),self.workflow(source_date)]))
        return dict(schema='V4_WORKBENCH_VERSIONS_V1',source_date=source_date,observation_date=observation,generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],numeric_manifest=p['manifest'],modules=modules,event_id=digest(modules),**FLAGS)

    def history(self):
        days=[]
        for value in sorted(self._index().get('dates',{}),reverse=True):
            iso=f'{value[:4]}-{value[4:6]}-{value[6:]}'
            product=self._view(iso)
            days.append(dict(source_date=iso,observation_date=self._observation_date(iso),revision=product['source_generation'],numeric_manifest=product['manifest']))
        if self.skill_r2 is not None:
            try:
                if self._is_skill_date('2026-10-28'):days.append(self.skill_r2.history_entry(self._observation_date('2026-10-28')))
            except (ValueError,OSError,KeyError,TypeError):pass
        for value,reference in sorted(self._index().get('attempts',{}).items(),reverse=True):
            if value in self._index().get('dates',{}):continue
            attempt=self.source._a_product_reference(reference)
            if attempt.get('data_date')!=value or attempt.get('schema')!='V4_A_DAILY_DERIVATIVES_V1':raise ValueError('WORKBENCH_ATTEMPT_IDENTITY_CONFLICT')
            iso=f'{value[:4]}-{value[4:6]}-{value[6:]}'
            days.append(dict(source_date=iso,observation_date=self._observation_date(iso),revision=None,status=attempt['status'],attempt=reference))
        days.sort(key=lambda value:value['source_date'],reverse=True)
        return dict(status='READY',days=days,revision_kind='SOURCE_GENERATION_NOT_STATISTICS_REVISION',**FLAGS)

    def top200(self,source_date,revision=None):
        if self._is_skill_date(source_date):
            self.skill_r2.versions(self._observation_date(source_date),revision)
            return dict(status='CANNOT_CONFIRM_NOT_MATERIALIZED',source_date=source_date,top200=[],statistics={},**FLAGS)
        p=self._view(source_date,revision);reference=self._index().get('top200',{}).get(compact(source_date))
        if reference is None:return dict(status='CANNOT_CONFIRM_NOT_MATERIALIZED',source_date=source_date,top200=[],statistics={},**FLAGS)
        value=self.source._a_product_reference(reference)
        if (value.get('schema')!='V4_A_SHARE_TOP200_V1' or value.get('data_date')!=p['data_date'] or
            value.get('numeric_manifest')!=p['manifest'] or value.get('source_generation')!=p['source_generation'] or
            value.get('input_sha256')!=p['source_identity']['input_sha256'] or len(value.get('top200',[]))!=value.get('top200_count') or
            len({row['symbol']for row in value.get('top200',[])})!=value.get('top200_count')):
            raise ValueError('WORKBENCH_TOP200_SOURCE_CONFLICT')
        return {key:item for key,item in value.items() if key!='coverage'}|dict(artifact=reference)

    def day(self,source_date,revision=None):
        if self._is_skill_date(source_date):
            return self.skill_r2.day(self._observation_date(source_date),self.workflow(source_date),revision)
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
        try:quote_reference=self._quote_references.read(p)
        except (ValueError,OSError,KeyError,TypeError) as error:
            quote_reference=dict(status='CANNOT_CONFIRM:'+str(error),rows={})
        execution=self.workflow(source_date)
        return dict(source_close_reference=quote_reference,source_selector_sha256=p['source_identity']['selector_artifact_sha256'],schema='RESEARCH_SYSTEM_DAY_V1',source_date=source_date,observation_date=observation,generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],revision=p['source_generation'],numeric_manifest=p['manifest'],rows=rows,scope_count=len(rows),original_processed_count=p['processed_count'],row_scope='FROZEN_CANDIDATE_UNION_ONLY_NOT_FULL_POOL',formula_review='PENDING',chart_review='UNKNOWN_NOT_REVIEWED',execution_status='DEFERRED_USER',classification_catalogs=classification['catalogs'] if classification else {},classification_identity_counts=classification['identity_counts'] if classification else {},classification_status=classification['status'] if classification else 'CANNOT_CONFIRM_SOURCE_NOT_BOUND',statistics_status=statistics_status,statistics_version=statistics_ref['sha256'] if statistics_ref else None,workflow=[dict(label=n['label_zh'],status=n['execution_status'],recorded_at=n.get('recorded_at'),materials=n.get('materials',[])) for n in execution['time_contract']['nodes']],materials=[],reference_links=[dict(label='旧版单股归档',url='/research-panel/legacy-daily.html?'+urlencode(dict(date=source_date)))],source_refs=dict(numeric_manifest=p['manifest'],artifact=p['artifact'],date_binding=self.binding.get('observation_dates',{}).get(source_date) or dict(calendar=self.binding.get('calendar'),method='NEXT_AUTHORITY_SESSION')),**FLAGS)

    def classification_catalog(self,market):
        return self.classifications.catalog(market)

    def chart_views(self,source_date,revision=None):
        if self._is_skill_date(source_date):return self.skill_r2.chart_views(revision)
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
            if item.get('PNG'):
                chart_rows.append(dict(symbol=symbol,image_url=url('png',item['PNG']),rows_declared=item['rows']))
            else:
                chart_rows.append(dict(symbol=symbol,html_url=url('html',item['html']),rows_declared=item['rows'],png_export='ON_USER_REQUEST_CANVAS'))
            projection=item['projection'];path=Path(projection['path'])
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(Path(root).resolve()):raise ValueError('WORKBENCH_PROJECTION_PATH_INVALID')
            projection_rows.append(dict(symbol=symbol,projection_url=url('projection',projection),sha256=projection['sha256'],bytes=projection.get('bytes',path.stat().st_size),encoding=projection.get('encoding','gzip' if path.suffix=='.gz' else 'identity'),row_count=item['rows'],formula_sha256='d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac'))
        common=dict(source_date=source_date,source_generation=p['source_generation'],source_input_sha256=p['source_identity']['input_sha256'],chart_review='UNKNOWN_NOT_REVIEWED',full_stock_PASS=0,**FLAGS)
        result=dict(charts=dict(rows=chart_rows,name_overlay=dict(rows=[dict(symbol=r['symbol'],name=r.get('display_name')) for r in p['rows']]),**common),projections=dict(rows=projection_rows,**common))
        with self._lock:
            self._chart_cache[chart_key]=result
            while len(self._chart_cache)>8:self._chart_cache.pop(next(iter(self._chart_cache)))
        return result

    def company(self,source_date,symbol,revision=None):
        if self._is_skill_date(source_date):return None
        p=self._view(source_date,revision)
        extra={}
        if not any(row.get('symbol')==symbol for row in p['rows']):
            model=self.v192_group(source_date,revision)
            if not any(row.get('symbol')==symbol for row in model['rows']):raise KeyError('V192_SYMBOL_NOT_BOUND')
            extra['allow_processed_symbol']=True
        answer=self.source.read_a_daily_company_materials(p['data_date'],symbol,generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],**extra)
        if answer.get('status')!='PARTIAL_RECEIVED':
            return dict(schema='V4_RECEIVED_COMPANY_VIEW_V1',status=answer.get('status'),symbol=symbol,source_date=source_date,observation_date=self._observation_date(source_date),generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],numeric_manifest=p['manifest'],missing_reason=answer.get('missing_reason'),availability_gaps=answer.get('availability_gaps',[]),**FLAGS)
        if answer.get('numeric_manifest')!=p['manifest']:raise ValueError('WORKBENCH_COMPANY_REVISION_MOVED')
        m=answer['materials'];business=m.get('business_reported') or {};finance=m.get('financials_reported') or {};holders=m.get('shareholders_reported') or {}
        holder_history=m.get('provenance_details',{}).get('shareholder_count_history') or []
        holder_current=next((v for v in holder_history if v.get('asof_date')==holders.get('holder_asof')),{})
        def holder_fact(key,fallback,unit):
            original=holder_current.get(key)
            return copy.deepcopy(original) if isinstance(original,dict) else {**fact(fallback,{**holders,'source_url':holders.get('holder_source_url')}),'unit':unit,'missing_reason':None if fallback is not None else 'CANNOT_CONFIRM_MISSING_COMPARABLE_PERIOD'}
        # This is a received-value projection, never a new financial evaluation.
        def fact(value,source):return dict(value=value,unit=source.get('monetary_unit'),source_url=source.get('latest_financial_source_url') or source.get('source_url'),asof_date=source.get('asof_date') or source.get('holder_asof'),disclosed_at=source.get('disclosed_at') or source.get('latest_disclosed_at'),evidence_status=source.get('evidence_status','PARTIAL_RECEIVED'))
        return dict(schema='V4_RECEIVED_COMPANY_VIEW_V1',symbol=symbol,source_date=source_date,observation_date=self._observation_date(source_date),generation=p['source_generation'],input_sha256=p['source_identity']['input_sha256'],numeric_manifest=p['manifest'],business=dict(summary=fact(business.get('value'),business)),actual_controller=None,latest_financial=dict(report_period=finance.get('latest_report_period'),period_kind=finance.get('latest_period_kind')),facts=[['营收',fact(finance.get('latest_revenue'),finance)],['归母净利润',fact(finance.get('latest_net_profit_parent'),finance)],['股东户数',holder_fact('holder_count',holders.get('holder_count'),'户')],['股东较上期变化',holder_fact('change_accounts',holders.get('holder_change_accounts'),'户')],['股东较上期变化率',holder_fact('change_percent',holders.get('holder_change_percent'),'%')]],reports=dict(metadata_only_count=len(m.get('report_catalog') or []),catalog=m.get('report_catalog') or [],stored_report=m.get('stored_report'),missing_reason=None if m.get('report_catalog') else 'CANNOT_CONFIRM_NO_BOUND_REPORT_METADATA'),received_materials=m,material_ref=answer.get('material_ref'),material_lifecycle=answer.get('material_lifecycle'),**FLAGS)

    def observations(self,source_date,observation_date,revision=None):
        if self._is_skill_date(source_date):
            self.skill_r2.versions(self._observation_date(source_date),revision)
            if observation_date!=self._observation_date(source_date):raise ValueError('WORKBENCH_OBSERVATION_DATE_CONFLICT')
            return dict(latest=None,status='UNKNOWN_NO_BOUND_INTRADAY_SNAPSHOT',source_date=source_date,observation_date=observation_date,**FLAGS)
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
        if self._is_skill_date(source_date):
            version=self.skill_r2.versions(self._observation_date(source_date),revision)
            return dict(source_date=source_date,observation_date=version['observation_date'],generation=version['generation'],input_sha256=version['input_sha256'],markets={name:dict(status='UNKNOWN',summary='未绑定该观察日来源') for name in ['US','JP','KR']},intraday_status='UNKNOWN',**FLAGS)
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

    def skill_r2_asset(self,source_date,symbol,kind,sha,revision=None):
        if not self._is_skill_date(source_date):raise KeyError('SKILL_R2_ASSET_NOT_FOUND')
        return self.skill_r2.asset(symbol,kind,sha,revision)

    def workflow(self,source_date=None):
        plan=checked(self.binding['workflow_plan']);nodes=[];error=None
        observation=self._observation_date(source_date) if source_date else self.binding.get('workflow_date')
        try:
            ref=self._module_reference('execution',observation) if observation else None
            if ref is None and self.binding.get('workflow_execution'):
                fallback=self.binding['workflow_execution'];candidate=checked(fallback)
                if not observation or candidate.get('observation_date')==observation:ref=fallback
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
    from fastapi.responses import Response,StreamingResponse
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
    @router.get('/days/{source_date}/v192')
    def v192_group(source_date:str,revision:str|None=None):return call('v192_group',source_date,revision)
    @router.get('/days/{source_date}/v192-assets/{symbol}')
    def v192_stock_assets(source_date:str,symbol:str,model_sha256:str,revision:str|None=None):return call('v192_stock_assets',source_date,symbol,model_sha256,revision)
    @router.get('/days/{source_date}/v192-assets/{symbol}/{kind}')
    def v192_stock_asset(source_date:str,symbol:str,kind:str,sha256:str,model_sha256:str,revision:str|None=None):
        raw,mime=call('v192_stock_assets',source_date,symbol,model_sha256,revision,kind,sha256)
        headers={'Cache-Control':'private, max-age=31536000, immutable','X-Content-Type-Options':'nosniff'}
        if kind=='html':
            connect="'self'" if b'CHART_METADATA_IDENTITY' in raw else "'none'"
            headers['Content-Security-Policy']=f"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src {connect}; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
        return Response(raw,media_type=mime,headers=headers)
    @router.get('/days/{source_date}/top200')
    def top200(source_date:str,revision:str|None=None):return call('top200',source_date,revision)
    @router.get('/days/{source_date}/charts')
    def charts(source_date:str,revision:str|None=None):return call('chart_views',source_date,revision)['charts']
    @router.get('/days/{source_date}/projections')
    def projections(source_date:str,revision:str|None=None):return call('chart_views',source_date,revision)['projections']
    @router.get('/days/{source_date}/single-research/{symbol}')
    def single_research(source_date:str,symbol:str,revision:str|None=None):return call('single_stock_research',source_date,symbol,revision)
    @router.get('/days/{source_date}/single-research/{symbol}/assets/{kind}')
    def single_research_asset(source_date:str,symbol:str,kind:str,sha256:str,revision:str|None=None,panel_revision:str|None=None):
        content,media=call('single_stock_asset',source_date,symbol,kind,sha256,revision,panel_revision)
        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}
        if kind=='html':headers['Content-Security-Policy']="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
        return Response(content,media_type=media,headers=headers)
    @router.get('/days/{source_date}/skill-r2/assets/{symbol}/{kind}')
    def skill_asset(source_date:str,symbol:str,kind:str,sha256:str,revision:str|None=None):
        content,media=call('skill_r2_asset',source_date,symbol,kind,sha256,revision)
        return Response(content,media_type=media,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    @router.get('/days/{source_date}/company/{symbol}')
    def company(source_date:str,symbol:str,revision:str|None=None):return call('company',source_date,symbol,revision)
    @router.get('/days/{source_date}/f10/{symbol}')
    def f10(source_date:str,symbol:str,revision:str|None=None):return call('f10',source_date,symbol,revision)
    @router.get('/days/{source_date}/observations')
    def observations(source_date:str,observation_date:str,revision:str|None=None):return call('observations',source_date,observation_date,revision)
    @router.get('/days/{source_date}/context')
    def context(source_date:str,revision:str|None=None):return call('source_context',source_date,revision)
    return router
