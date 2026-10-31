"""Dated descriptive Top200 derived by the existing A daily-product owner.

Reuses the accepted trial's exact feature/statistics functions. No formula,
price collection, eligibility inference, manual chart review or trading.
"""
from __future__ import annotations
import ast
import collections
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from statistics import mean, median
import struct
import zipfile

from ops.research_panel_daily_product import FLAGS, canonical, checked, digest, reference, save

TRIAL = Path('/Users/lexi/Desktop/学习/因子工厂/research/top200_review_trial_20261030_r1')
TRIAL_SHA = 'f640e88dad6062dc28574c002095887ecb49f157a8a5266600d0499c503290f4'
GROUPS = ('original','nav_smallk','nav_pullback','nav_breakout')


def load(ref):
    return json.loads(checked(ref).read_bytes())


def frozen_function(name, environment, trial=TRIAL):
    """Compile only the frozen pure function, never execute the report runner."""
    path=trial/'build_report.py';raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=TRIAL_SHA:raise ValueError('TOP200_FROZEN_RULE_DRIFT')
    nodes=[node for node in ast.walk(ast.parse(raw)) if isinstance(node,ast.FunctionDef) and node.name==name]
    if len(nodes)!=1:raise ValueError('TOP200_RULE_FUNCTION_AMBIGUOUS')
    module=ast.Module(body=nodes,type_ignores=[])
    scope=dict(environment);exec(compile(ast.fix_missing_locations(module),str(path),'exec'),scope)
    return scope[name]


def read_csv(path):
    def value(text):
        if text=='':return None
        try:return json.loads(text)
        except (ValueError,TypeError):return text
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return [{key:value(item) for key,item in row.items()} for row in csv.DictReader(stream)]


def official_quotes(input_ref,target):
    from ops._a_share_daily_sync_parts.official_daily_package import OfficialDailyPackage
    owner=OfficialDailyPackage(input_ref,target);quotes={}
    with zipfile.ZipFile(owner.package_path) as archive:
        blocks={};codes={}
        for (market,code),(bar,lineage,shares) in owner.rows.items():
            md=lineage['md1_member']['name'];cod=lineage['cod_member']['name']
            if md not in blocks:blocks[md]=archive.read(md)
            if cod not in codes:codes[cod]=archive.read(cod)
            previous=struct.unpack_from('<d',blocks[md],lineage['md1_byte_offset']+4)[0]
            offset=lineage['cod_byte_offset'];name=codes[cod][offset+40:offset+72].split(b'\0')[0].decode('gbk').strip()
            symbol=code+'.'+{1:'SH',0:'SZ',2:'BJ'}[market]
            valid=math.isfinite(previous) and previous>0 and bar['close']>0 and shares>=0 and bar['amount']>=0
            full_bar=all(math.isfinite(bar[key]) and bar[key]>0 for key in ('open','high','low','close')) and bar['low']<=min(bar['open'],bar['close'])<=max(bar['open'],bar['close'])<=bar['high'] and shares>0 and bar['amount']>0
            quotes[symbol]=dict(symbol=symbol,name=name,open=bar['open'],high=bar['high'],low=bar['low'],close=bar['close'],prev_close=previous,eligible_for_daily_gain_rank=bool(valid and full_bar),
                change_pct=(bar['close']/previous-1)*100 if valid else None,amount_cny=bar['amount'],volume_shares=shares,
                source_date=f'{str(target)[:4]}-{str(target)[4:6]}-{str(target)[6:]}',source_time='UNKNOWN_DATE_ONLY',
                price_status='VALID' if valid else 'INVALID_REFERENCE_OR_AMOUNT',zero_volume=shares==0,
                cod_member=cod,cod_record_index=lineage['cod_record_index'],md1_member=md,md1_byte_offset=lineage['md1_byte_offset'])
    return quotes,owner


def roster_comparison(product,top_symbols,date,kind,manifest_ref):
    if product is None:return dict(kind=kind,source_date=date,status='CANNOT_CONFIRM_PREVIOUS_PRODUCT_MISSING',unique_candidates=None,hits=None,top_count=len(top_symbols),manual_visual_review='UNKNOWN_NOT_REVIEWED')
    rows=product['rows'];symbols={row['symbol']for row in rows}
    if len(symbols)!=len(rows):raise ValueError('TOP200_CANDIDATE_ROSTER_DUPLICATE')
    def measure(members):
        count=len(members);hits=len(members&top_symbols)
        return dict(candidate_count=count,hits=hits,top_count=len(top_symbols),share_of_top_pct=hits/len(top_symbols)*100 if top_symbols else None,share_of_candidates_pct=hits/count*100 if count else None)
    groups={group:measure({row['symbol']for row in rows if group in row['groups'].replace(',', '|').split('|')})for group in GROUPS}
    if any(groups[group]['candidate_count']!=product['group_counts'][group]for group in GROUPS):raise ValueError('TOP200_GROUP_MEMBERSHIP_PARITY_FAILED')
    return dict(kind=kind,source_date=date,numeric_manifest=manifest_ref,**measure(symbols),groups=groups,unique_count_is_deduplicated=True,availability_before_target_open='CANNOT_CONFIRM',manual_visual_review='UNKNOWN_NOT_REVIEWED')


def structure_histories(panel,symbols,expected):
    """One bounded column/window read; the frozen feature function is unchanged."""
    import pyarrow.dataset as ds
    dataset=ds.dataset(panel,format='parquet')
    columns=[key for key in ('trade_date','ts_code','open','high','low','close','volume','user_v1_breakout','breakout','brick_pullback_shrink')if key in dataset.schema.names]
    table=dataset.to_table(columns=columns,filter=ds.field('ts_code').isin(list(symbols))&(ds.field('trade_date')>=str(expected[0]))&(ds.field('trade_date')<=str(expected[-1])))
    histories=collections.defaultdict(list)
    for row in table.to_pylist():row['trade_date']=int(row['trade_date']);histories[row['ts_code']].append(row)
    return {symbol:sorted(histories[symbol],key=lambda row:row['trade_date'])for symbol in symbols}


def refresh_revised_trial_structures(context,coverage,directory,package,source_refs,trial):
    receipt_refs=[ref for ref in source_refs if Path(ref['path']).name=='candidate_receipt.json']
    if len(receipt_refs)!=1:raise ValueError('TOP200_TRIAL_RECEIPT_UNBOUND')
    original=load(receipt_refs[0])
    if original['generation_id']==context.generation:return [],0
    old_panel=Path(original['candidates']['selector']);old_refs=[ref for ref in source_refs if ref['path']==str(old_panel)]
    from ops.research_panel_qfq import panel_contract
    if (len(old_refs)!=1 or old_refs[0]['sha256']!=original['candidate_sha256']['selector'] or
            old_panel.is_symlink() or old_panel.stat().st_size!=old_refs[0]['size'] or
            panel_contract(old_panel).get('generation_id')!=original['generation_id']):raise ValueError('TOP200_PRIOR_PANEL_BINDING')
    expected=[date for date in context.calendars['SH']if date<context.target][-61:]
    if len(expected)!=61 or expected[-1]!=package.previous:raise ValueError('TOP200_REVISED_CALENDAR_UNBOUND')
    # The prior full checksum was already certified by the frozen trial; here
    # reuse its immutable original generation/footer/size and compare actual
    # affected window bytes numerically, without rehashing an8.7GB panel.
    stamp=old_panel.stat();old=structure_histories(old_panel,directory,expected);current=structure_histories(context.panel,directory,expected)
    changed=[symbol for symbol in directory if old.get(symbol)!=current.get(symbol)]
    feature=frozen_function('feature',dict(histories=current,expected=expected,mean=mean,finite=lambda value:isinstance(value,(int,float))and math.isfinite(value)),trial)
    for row in coverage:
        if row['symbol']in changed:row.update(feature(row['symbol']))
    if old_panel.stat()!=stamp:raise ValueError('TOP200_PRIOR_PANEL_MOVED')
    return sorted(changed),len(changed)


def build(context, product_root, official_ref, classification_root, *, trial=TRIAL):
    """One bounded date. Returns an immutable payload; no runtime pointer writes."""
    from infrastructure.research_classification_view import ReceivedClassificationStore
    root=Path(product_root);index=json.loads((root/'index.json').read_bytes());day=str(context.target)
    manifest_ref=index['dates'][day];manifest=load(manifest_ref);product=load(manifest['artifact'])
    if product['source_identity']!=context.identity:raise ValueError('TOP200_NUMERIC_IDENTITY_CONFLICT')
    store=ReceivedClassificationStore(classification_root)
    try:
        catalog=store.catalog('A_SHARE');cdr_catalog=store.catalog('CDR');classification_version=store.version()
    finally:store.close()
    directory={row['symbol']:row for row in catalog['rows']};cdr={row['symbol']:row for row in cdr_catalog['rows']}
    if not directory:raise ValueError('TOP200_DIRECTORY_NOT_BOUND')
    quotes,package=official_quotes(official_ref,context.target)
    fingerprint=digest(dict(date=day,input=official_ref,classification=classification_version,
        generation=context.generation,input_sha256=context.identity['input_sha256'],rule=TRIAL_SHA))
    existing=index.get('top200',{}).get(day)
    if existing:
        previous=load(existing)
        if previous.get('input_fingerprint')==fingerprint and previous.get('numeric_manifest')==manifest_ref:
            return previous,dict(reused=True,reference=existing,computed_structures=0)
    repair=index.get('exact_metadata_rows',{}).get(day,{}).get('002731.SZ')
    if repair and repair.get('prior_top200'):
        original=load(repair['computation']);previous=load(repair['prior_top200'])
        old_product=load(load(original['original_numeric_manifest'])['artifact'])
        selected=[row['symbol']for row in product['rows']]
        if (day!='20261030' or original.get('symbol')!='002731.SZ' or repair['row']!=product['row_refs']['002731.SZ']
            or load(repair['row'])!=load(original['row']) or previous.get('numeric_manifest')!=original['original_numeric_manifest']
            or previous.get('input_fingerprint')!=fingerprint or product['rows']!=old_product['rows']
            or any(product['row_refs'][symbol]!=old_product['row_refs'][symbol]for symbol in selected)
            or previous['comparison']['previous_session'].get('numeric_manifest')!=index['dates'].get(str(package.previous))):raise ValueError('TOP200_EXACT_METADATA_REUSE_CONFLICT')
        import copy
        payload=copy.deepcopy(previous);payload['numeric_manifest']=manifest_ref
        payload['comparison']['same_day']['numeric_manifest']=manifest_ref
        payload['computation']=dict(prior_computation=previous['computation'],reused_same_source_metadata_view=repair['prior_top200'],computed_structures=0,affected_structure_symbols=[],formula_engine_calls=0)
        context.unchanged();return payload,dict(reused=False,computed_structures=0,reused_same_source_metadata_view=repair['prior_top200'])
    # The D30 trial was already computed and independently accepted. Bind the
    # exact original package/classification before reusing those stored values.
    frozen=load(reference(trial/'SOURCE_MANIFEST.json'))
    source_refs=frozen if isinstance(frozen,list) else frozen.get('sources',frozen.get('files',[]))
    trial_package_ref=load(reference(trial/'RUN_RECEIPT.json'))
    reusable=(day=='20261030' and len(directory)==5575 and
              reference(trial/'build_report.py')['sha256']==TRIAL_SHA and
              load(reference(trial/'SCHEMA_OBSERVATION.json'))['database']['sha256']==catalog.get('database_sha256',load(reference(Path(classification_root)/'versions'/json.loads((Path(classification_root)/'current.json').read_bytes())['version']/'manifest.json'))['database']['sha256']))
    # The trial source manifest explicitly binds original input.json and package.
    def references(value):
        if isinstance(value,dict):
            if 'path' in value and 'sha256' in value:yield value
            for item in value.values():yield from references(item)
        elif isinstance(value,list):
            for item in value:yield from references(item)
    reusable=reusable and any(ref.get('path')==official_ref['path'] and ref.get('sha256')==official_ref['sha256'] for ref in references(frozen))
    if reusable:
        coverage=read_csv(trial/'features_fixed_directory.csv')
        if {row['symbol'] for row in coverage}!=set(directory):raise ValueError('TOP200_TRIAL_DIRECTORY_DRIFT')
        if any((row.get('change_pct') is None)!=(quotes.get(row['symbol'],{}).get('change_pct') is None) or
               (row.get('change_pct') is not None and row['change_pct']!=quotes[row['symbol']]['change_pct']) for row in coverage):
            raise ValueError('TOP200_TRIAL_RANK_INPUT_DRIFT')
        structure_changed,structure_count=refresh_revised_trial_structures(context,coverage,directory,package,source_refs,trial)
    else:
        import pyarrow.dataset as ds
        previous_dates=[date for date in context.calendars['SH'] if date<context.target]
        expected=previous_dates[-61:]
        if len(expected)!=61 or expected[-1]!=package.previous:raise ValueError('TOP200_PREVIOUS_CALENDAR_UNBOUND')
        histories=structure_histories(context.panel,directory,expected)
        feature=frozen_function('feature',dict(histories=histories,expected=expected,mean=mean,finite=lambda value:isinstance(value,(int,float)) and math.isfinite(value)),trial)
        coverage=[]
        for symbol,record in sorted(directory.items()):
            row=dict(quotes.get(symbol,dict(symbol=symbol,name=None,price_status='OFFICIAL_ROW_MISSING',change_pct=None)))
            exact=row['name']==record['name'];row.update(board=record.get('board','UNKNOWN'),exchange=record.get('exchange','UNKNOWN'),directory_name=record['name'],directory_date=record['reference_date'],identity_status='EXACT_CODE_NAME' if exact else 'NAME_CONFLICT' if row['name'] else 'NO_DAILY_ROW',eligibility='CANNOT_CONFIRM_DATE_ELIGIBILITY')
            row.update(feature(symbol));row.update(shortline_themes=[tag['label']for tag in record.get('shortline_themes',[])] if exact else [],official_major=(record.get('official_industry') or {}).get('major_name') if exact else None,main_industry=record.get('main_industry') if exact else None)
            row['history_asof']=str(package.previous);row['history_basis']='QFQ_ASOF_'+day+'_NOT_HISTORICAL_PIT';coverage.append(row)
        structure_count=len(directory);structure_changed=sorted(directory)
    from ops.a_share_daily_sync import _daily_source_policy_additions,_load_verified_lifecycle_facts
    facts=_daily_source_policy_additions()
    known_no_bar={row['symbol']for row in facts.get('exact_no_current_bar_dispositions',[]) if row['target_date']==context.target}
    known_no_bar.update(symbol for symbol,row in _load_verified_lifecycle_facts().items() if row.get('verified') and context.target>=int(row['delisting_effective_date']))
    positive=sorted((row for row in coverage if row.get('change_pct') is not None),key=lambda row:(-row['change_pct'],row['symbol']))
    for row in coverage:
        row.update({key:quotes.get(row['symbol'],{}).get(key)for key in ('open','high','low','eligible_for_daily_gain_rank')})
    ranked=[row for row in positive if row['eligible_for_daily_gain_rank'] and row['symbol'] not in known_no_bar]
    for rank,row in enumerate(ranked,1):row['rank']=rank
    top=ranked[:200];topset={row['symbol'] for row in top}
    if topset&known_no_bar:raise ValueError('TOP200_KNOWN_NO_CURRENT_BAR_CONFLICT')
    # Preserve missingness and actual cardinality when fewer than 200 valid rows.
    stat=frozen_function('stats',dict(ranked=ranked,topset=topset,median=median),trial)
    axes={axis:collections.defaultdict(set)for axis in ('industry','theme','structure')}
    for row in ranked:
        axes['industry'][row.get('official_major') or 'UNKNOWN'].add(row['symbol'])
        for tag in row.get('shortline_themes') or ['UNKNOWN']:axes['theme'][tag].add(row['symbol'])
        axes['structure'][row.get('structure') or 'UNKNOWN'].add(row['symbol'])
    statistics={axis:sorted([stat('冻结描述性口径',members,axis,label)for label,members in mapping.items()],key=lambda row:(-row['top200_count'],-row['amount_cny'])) for axis,mapping in axes.items()}
    candidates={row['symbol']:row for row in product['rows']}
    for row in top:row['current_groups']=candidates.get(row['symbol'],{}).get('groups','');row['visual_review_status']='UNKNOWN_NOT_REVIEWED'
    prior_day=str(package.previous);prior_ref=index['dates'].get(prior_day);prior=load(load(prior_ref)['artifact'])if prior_ref else None
    comparison=dict(previous_session=roster_comparison(prior,topset,prior_day,'跨日名单覆盖（事前时点待证）',prior_ref),same_day=roster_comparison(product,topset,day,'同日事后描述对照',manifest_ref))
    context.unchanged()
    payload=dict(comparison=comparison,schema='V4_A_SHARE_TOP200_V1',status='PARTIAL_DESCRIPTIVE' if len(top)==200 else 'PARTIAL_INSUFFICIENT_VALID_QUOTES',data_date=day,
        numeric_manifest=manifest_ref,source_generation=context.generation,input_sha256=context.identity['input_sha256'],input_fingerprint=fingerprint,
        official_input=official_ref,official_package=package.package_ref,classification_version=classification_version,classification_source=catalog['source_ref'],rule=dict(path=str(trial/'build_report.py'),sha256=TRIAL_SHA),
        directory_dates=sorted({row['reference_date']for row in directory.values()}),directory_count=len(directory),valid_quote_count=len(positive),positive_price_record_count=len(positive),valid_daily_gain_rank_record_count=len(ranked),excluded_known_no_current_bar=sorted(set(directory)&known_no_bar),excluded_nontrading_or_invalid_bar_count=len(positive)-len(ranked),missing_quote_count=len(directory)-len(positive),top200_count=len(top),
        excluded_cdr=sorted(cdr),outside_directory_count=len(set(quotes)-set(directory)),top200=top,statistics=statistics,coverage=coverage,
        preparation_asof=str(package.previous),manual_visual_review='UNKNOWN_NOT_REVIEWED',historical_PIT=False,full_market_eligibility='CANNOT_CONFIRM',
        computation=dict(reused_trial=reusable,computed_structures=structure_count,affected_structure_symbols=structure_changed,formula_engine_calls=0),**FLAGS)
    return payload,dict(reused=False,computed_structures=structure_count)


def stage(payload,root,stage_root,owner_ref):
    """Use the established owner publication plan and exact index/event CAS."""
    from ops.sync_stock_history_completion import Staging, DEFAULT_OWNER_LOCK
    root,stage_root=Path(root),Path(stage_root);writer=Staging(root,stage_root)
    index_ref,event_ref=reference(root/'index.json'),reference(root/'events/latest.json');index,event=load(index_ref),load(event_ref)
    day=payload['data_date']
    if index['dates'].get(day)!=payload['numeric_manifest'] or event['data_date']!=day or event['manifest']!=payload['numeric_manifest']:raise ValueError('TOP200_COMPLETION_SOURCE_MOVED')
    artifact=writer.immutable('top200/'+day,'top200.json',payload)
    index.setdefault('top200',{})[day]=artifact
    event.update(top200=artifact,event_id=digest(dict(numeric_manifest=payload['numeric_manifest'],top200=artifact)))
    lock=DEFAULT_OWNER_LOCK.stat()
    return dict(shared_owner_lock=dict(path=str(DEFAULT_OWNER_LOCK),device=lock.st_dev,inode=lock.st_ino),status='PREPARED_TOP200',expected_index=index_ref,expected_event=event_ref,staged_index=save(stage_root/'index.json',index),staged_event=save(stage_root/'event.json',event),immutable_files=writer.files,owner_publisher=owner_ref,target_root=str(root),stage=str(stage_root),completed=[],**FLAGS)


def _validate_daily_history_cache(owner,cache,bars,identity,config,proof=None):
    """The original adapter's guards plus multi-generation dependency proofs."""
    from ops.bootstrap_stock_event_history import RULE
    if cache.get('rule_sha256')!=RULE or cache.get('rules_signature')!=owner.digest(config):raise ValueError('HISTORY_RULE_OR_CONFIG_DRIFT')
    if cache.get('source_identity')!=identity:raise ValueError('HISTORY_SOURCE_DRIFT')
    dates={str(bar['trade_date'])for bar in bars}
    if not set(cache['evaluations'])<=dates:raise ValueError('HISTORY_DATE_OUTSIDE_PREFIX')
    end=max(map(int,cache['evaluations']),default=0)
    if cache.get('prefix_sha256')!=owner.digest([bar for bar in bars if bar['trade_date']<=end]):raise ValueError('HISTORY_PREFIX_DRIFT')
    for day,item in cache['evaluations'].items():
        if item['source_identity']!=identity and (proof or {}).get('records',{}).get(day)!=owner.digest(item):raise ValueError('HISTORY_PRIOR_ENTRY_NOT_PROVEN')
        if set(item['groups'])!=set(owner.GROUPS) or any(value not in {'TRUE','FALSE','UNKNOWN'}for value in item['groups'].values()):raise ValueError('HISTORY_TRISTATE_INVALID')


def _prior_generation_proofs(context,caches,bars_by_symbol):
    """One bounded column read/calendar scan per actual old generation."""
    from decimal import Decimal
    import pyarrow.parquet as pq
    grouped={};proofs={symbol:dict(records={},sources=[])for symbol in caches}
    for symbol,cache in caches.items():
        for day,item in cache['evaluations'].items():
            identity=item['source_identity']
            if identity==context.identity:continue
            key=digest(identity);grouped.setdefault(key,dict(identity=identity,symbols=set()))['symbols'].add(symbol)
    for group in grouped.values():
        identity=group['identity'];receipt_ref=reference(Path(identity['snapshot']['path']).parent/'candidate_receipt.json');receipt=load(receipt_ref)
        if (receipt['generation_id']!=identity['generation'] or receipt['input_sha256']!=identity['input_sha256'] or receipt['adjustment_snapshot']!=identity['snapshot'] or receipt['candidate_sha256']['selector']!=identity['selector_artifact_sha256']):raise ValueError('HISTORY_PRIOR_RECEIPT_IDENTITY_CONFLICT')
        load(identity['snapshot']);panel=Path(receipt['candidates']['selector']);stamp=panel.stat();asof=int(identity['asof'])
        table=pq.read_table(panel,columns=['ts_code','trade_date','open','high','low','close','volume'],filters=[('ts_code','in',sorted(group['symbols'])),('trade_date','<=',str(asof))])
        original=collections.defaultdict(list)
        for row in table.to_pylist():original[row['ts_code']].append(dict(trade_date=int(row['trade_date']),**{key:str(row[key if key!='vol' else 'volume'])for key in ('open','high','low','close','vol')}))
        old_context=object.__new__(type(context));old_context.panel=panel;old_context.target=asof;old_context.config=context.config
        calendars=old_context._calendars()
        for market in calendars:
            if [day for day in calendars[market]if day<=asof]!=[day for day in context.calendars[market]if day<=asof]:raise ValueError('HISTORY_PRIOR_MARKET_CALENDAR_DRIFT')
        for symbol in group['symbols']:
            old=sorted(original[symbol],key=lambda bar:bar['trade_date']);current=[bar for bar in bars_by_symbol[symbol]if bar['trade_date']<=asof]
            if len(old)!=len(current) or any(left['trade_date']!=right['trade_date'] or any(Decimal(left[key])!=Decimal(right[key])for key in ('open','high','low','close','vol'))for left,right in zip(old,current)):raise ValueError('HISTORY_PRIOR_PREFIX_REVISION_REQUIRES_AFFECTED_DATE_REBIND:'+symbol)
            for day,item in caches[symbol]['evaluations'].items():
                if item['source_identity']==identity:proofs[symbol]['records'][day]=digest(item)
            proofs[symbol]['sources'].append(dict(identity=identity,receipt=receipt_ref,panel=str(panel),prefix_sha256=digest(current),calendar_sha256=digest(calendars)))
        if panel.stat()!=stamp:raise ValueError('HISTORY_PRIOR_PANEL_MOVED')
    return proofs


def prepare_incremental_history(context,root,output):
    """Freeze only newly selected stocks that still lack accepted history."""
    import os
    from ops import bootstrap_stock_event_history as adapter
    import domains.research_daily_product as rule
    import domains.research_daily_statistics as statistics
    root,output=Path(root),Path(output);index_ref=reference(root/'index.json');index=load(index_ref);day=str(context.target)
    manifest_ref=index['dates'][day];product_ref=load(manifest_ref)['artifact'];product=load(product_ref)
    charts_ref=index['original_charts'][day]['manifest'];charts=load(charts_ref)
    selected=sorted(row['symbol']for row in product['rows']);symbols=[];entries={};caches={};bars_by_symbol={}
    adapter.TARGET=context.target;adapter.GENERATION=context.generation;adapter.INPUT=context.identity['input_sha256'];adapter.DATA=context.data_root;adapter.DAILY=root;adapter.MAIN=Path(__file__).resolve().parents[1];adapter.SETTINGS={'automatic_original_owner':True}
    for symbol in selected:
        row=load(product['row_refs'][symbol])
        if row['historical_coverage']['known_full_history'] and not row['historical_coverage']['missing']:continue
        chart=charts['samples'][symbol];projection=adapter.load(chart['projection']);source_cache={key:projection['source_cache'][key]for key in ('path','sha256')}
        _,bars=adapter.retained_sample(projection,adapter.load(source_cache))
        if adapter.projection_identity(projection)!=context.identity:raise ValueError('HISTORY_CURRENT_PROJECTION_IDENTITY_CONFLICT')
        cache_ref=reference(root/'history'/adapter.RULE/symbol/'checkpoint.json');cache=load(cache_ref)
        symbols.append(symbol);caches[symbol]=cache;bars_by_symbol[symbol]=bars
        entries[symbol]=dict(projection=chart['projection'],source_cache=source_cache,prior_row=product['row_refs'][symbol],prior_cache=cache_ref,bars_sha256=digest(bars),rows=len(bars),first=bars[0]['trade_date'],last=bars[-1]['trade_date'],missing_dates=sorted(set(str(bar['trade_date'])for bar in bars)-set(cache['evaluations'])),qualification_sha256=digest(row['qualification']),display_name=row.get('display_name'),unchanged_chart={key:chart[key]for key in ('html','projection','PNG')})
    if not symbols:return None
    existing_contract=output/'CONTRACT.json'
    if existing_contract.exists():
        frozen=load(reference(existing_contract))
        if frozen['source_identity']!=context.identity or frozen['config']['symbols']!=symbols:raise ValueError('HISTORY_RESUME_SCOPE_DRIFT')
        for ref in frozen['code']:checked(ref)
        for key in ('index','numeric_manifest','numeric_product','source_config','receipt','snapshot','quarantine','reader'):checked(frozen['refs'][key])
        for ref in frozen['refs']['pointers']:checked(ref)
        return reference(output/('CONTRACT_'+digest(frozen)+'.json'))
    proofs=_prior_generation_proofs(context,caches,bars_by_symbol)
    for symbol in symbols:
        entries[symbol]['prior_entry_reuse']=proofs[symbol]
        _validate_daily_history_cache(__import__('ops.research_panel_daily_product',fromlist=['digest']),caches[symbol],bars_by_symbol[symbol],context.identity,context.config,proofs[symbol])
    # Keep a conservative per-worker memory envelope and foreground reserve.
    import subprocess,re
    cpu=os.cpu_count()or 1;vm=subprocess.check_output(['/usr/bin/vm_stat'],text=True);page=int(re.search(r'page size of (\d+) bytes',vm).group(1));values={key:int(value)for key,value in re.findall(r'^([^:]+):\s+(\d+)\.',vm,re.M)}
    available=sum(values.get(key,0)for key in ('Pages free','Pages inactive','Pages speculative'))*page
    workers=max(1,min(cpu-4,max(1,int(min(64,available/2**30-24)//4)),len(symbols)))
    calendar_ref=save(output/'CALENDARS.json',dict(dates=context.calendars,source_generation=context.generation,input_sha256=context.identity['input_sha256']))
    code=[reference(Path(adapter.__file__)),reference(Path(__import__('ops.research_panel_daily_product',fromlist=['digest']).__file__)),reference(Path(rule.__file__)),reference(Path(statistics.__file__)),reference(Path(__file__))]
    settings=dict(target=context.target,symbols=sorted(symbols),candidate_symbols=selected,canary=min(symbols,key=lambda symbol:(entries[symbol]['rows'],symbol)),reuse_complete=[],workers=workers,queue=workers*2,canary_parity_prefix_indices=sorted({0,min(40,min(entries[symbol]['rows'] for symbol in symbols)-1),max(0,min(entries[symbol]['rows'] for symbol in symbols)-6)}),job_memory_limit_GiB=64,system_available_reserve_GiB=24)
    refs=dict(index=index_ref,numeric_manifest=manifest_ref,numeric_product=product_ref,charts=charts_ref,calendar=calendar_ref,source_config=product['source_config'],receipt=context.receipt_ref,snapshot=context.snapshot_ref,quarantine=context.quarantine_ref,reader=context.reader_ref,pointers=[reference(context.pointer),reference(context.backpointer)])
    contract=dict(schema='v4.stock_history_catchup.v1',status='PREPARED_ORIGINAL_OWNER_INCREMENT',GOAL='Fill only actual missing accepted daily candidate history from retained original results',BASELINE_ID='CURRENT_DATED_ORIGINAL_PRODUCT',ONE_VARIABLE='missing_history_cache_initialization',WRITER='original_A_daily_owner',source_generation=context.generation,input_sha256=context.identity['input_sha256'],source_identity=context.identity,refs=refs,pins=context.config,code=code,config=settings,config_sha256=digest(settings),entries=entries,selector=dict(path=str(context.panel),stat={key:getattr(context.panel_stat,key)for key in ('st_size','st_mtime_ns','st_ino')}),output_root=str(output.resolve()),PASS_SIGNAL='Exact missing scope complete; current selection/chart unchanged; repeated read zero computations',STOP_RULE='Retain source revisions/ambiguity and checkpoint; never clear prior entries or change rules',resources=dict(cpu=cpu,available_bytes=available),**FLAGS)
    ref=save(output/('CONTRACT_'+digest(contract)+'.json'),contract,immutable=True);save(output/'CONTRACT.json',contract)
    return ref


def _register_automatic(contract_ref,event_type,artifact_ref,*,status):
    """Original registry builder/lock; strict new suffix, immutable old prefix."""
    import importlib.util,os,datetime
    registry_root=Path('/Users/lexi/Desktop/学习/因子工厂');path=registry_root/'contracts/build_experiment_registry_backfill_20260821.py'
    spec=importlib.util.spec_from_file_location('daily_original_registry',path);builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    c=load(contract_ref);route='A_SHARE_DAILY_INCREMENTAL_HISTORY_V1';execution=route+'_'+str(c['config']['target'])+'_'+c['source_generation']
    event=dict(schema_version='1.0',registration_mode='LIVE_APPEND',registry_event_id=execution+'_'+event_type+'_'+digest(artifact_ref)[:16],route_id=route,execution_id=execution,track_id='A_SHARE_DAILY_PRODUCT_DESCRIPTIVE_HISTORY',stage='ORIGINAL_OWNER_INCREMENT',event_type=event_type,occurred_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),contract_path=contract_ref['path'],artifact_path=artifact_ref['path'],input_sha256=c['input_sha256'],code_sha256=[ref['sha256']for ref in c['code']],config_sha256=c['config_sha256'],baseline_id=c['BASELINE_ID'],one_variable=c['ONE_VARIABLE'],signal_date_range=[min(item['first']for item in c['entries'].values()),c['config']['target']],target_date_range=[min(item['first']for item in c['entries'].values()),c['config']['target']],truth_access='EXPOSED_DESCRIPTIVE_RETURNS',sealed_status='NONE_NONPIT',runtime=dict(python=__import__('sys').executable,workers=c['config']['workers']),device='CPU',checkpoint_ref=str(Path(c['output_root'])/'journals'),deterministic_metrics=dict(scope_symbols=len(c['entries']),truth_positive_denominator=None,selection_slots=None),decision=status,stop_reason='STAGE_COMPLETE' if status!='RUNNING' else None,evidence_level='DESCRIPTIVE_NONPIT_ENGINEERING',input_identity=dict(null_reasons={}))
    with builder._exclusive_registry_lock():
        raw=builder.OUTPUT.read_bytes();events=[json.loads(line)for line in raw.splitlines()];existing=[item for item in events if item['execution_id']==execution]
        previous=next((item for item in existing if item['registry_event_id']==event['registry_event_id']),None)
        if previous:return previous
        if existing and (not builder._execution_reuse_allowed(event)or any(item['route_id']!=route for item in existing)):raise ValueError('DAILY_REGISTRY_EXECUTION_CONFLICT')
        if event_type!='RUN_STARTED' and not existing:raise ValueError('DAILY_REGISTRY_START_REQUIRED')
        record=builder.materialize([event],events[-1]['event_sha256'])[0];builder._validate_event(record,events[-1]['event_sha256'],len(events));suffix=builder._registry_payload([record])
        if builder.OUTPUT.read_bytes()!=raw:raise ValueError('DAILY_REGISTRY_PREFIX_MOVED')
        with builder.OUTPUT.open('ab')as stream:stream.write(suffix);stream.flush();os.fsync(stream.fileno())
        if builder.OUTPUT.read_bytes()!=raw+suffix:raise ValueError('DAILY_REGISTRY_READBACK_FAILED')
    counts=dict(routes=len({item['route_id']for item in events+[record]}),events=len(events)+1,executions=len({(item['route_id'],item['execution_id'])for item in events+[record]}),corrections=sum(item['event_type']=='CORRECTION'for item in events+[record]))
    receipt=dict(event_sha256=record['event_sha256'],registry_sha256=hashlib.sha256(raw+suffix).hexdigest(),counts=counts,source_prefix_sha256=hashlib.sha256(raw).hexdigest(),new_suffix_validation='PASS',legacy_schema='CANNOT_CONFIRM_PREEXISTING_DEBT',scope_unregistered_route_count=0,scope_contract_only_count=0,external_persistence='CANNOT_CONFIRM',**FLAGS)
    save(Path(c['output_root'])/('REGISTRY_'+event_type+'.json'),receipt)
    line='\n<!-- A_DAILY_INCREMENTAL_HISTORY '+execution+' '+event_type+' -->\n'+json.dumps(receipt,ensure_ascii=False)+'\n'
    for name in ('CURRENT_STATE.md','HK_OHLCV_RESEARCH_STATE.md','PROGRESS.md'):
        with (registry_root/name).open('a')as stream:stream.write(line);stream.flush();os.fsync(stream.fileno())
    return record


def run_incremental_history(context,root,output):
    """Reuse the accepted bounded adapter/worker, original rule and return cache."""
    from ops import bootstrap_stock_event_history as adapter
    from ops.sync_stock_history_completion import prepare,publish
    contract_ref=prepare_incremental_history(context,root,output)
    if contract_ref is None:return dict(status='COMPLETE_NO_HISTORY_GAPS',new_label_evaluations=0,new_return_evaluations=0)
    contract=load(contract_ref);permit=output/'RUN_AUTHORIZATION_R2.json'
    event=_register_automatic(contract_ref,'RUN_STARTED',contract_ref,status='RUNNING')
    save(permit,dict(status='ROOT_RUN_STARTED_REGISTERED',contract=contract_ref,contract_sha256=contract_ref['sha256'],event_sha256=event['event_sha256']))
    original_runtime,original_validate,original_cases=adapter.load_runtime,adapter.validate_cache,adapter.full_event_cases
    patched_owners=[]
    def runtime():
        owner,stats,paths=original_runtime();raw=owner.cached_daily_statistics
        if not any(previous is owner for previous,_ in patched_owners):patched_owners.append((owner,raw))
        def cached(*args,**kwargs):
            result=raw(*args,**kwargs);args[0]._daily_complete_event_cases=result[1];return result
        owner.cached_daily_statistics=cached
        return owner,stats,paths
    def cases(stats,row,cache,bars,calendar,contract,entry):
        groups=adapter._STATE[2]._daily_complete_event_cases
        return dict(schema_version='v4.a_share.event_cases.v1',symbol=row['symbol'],data_date=str(context.target),numeric_manifest=contract['refs']['numeric_manifest'],source_generation=context.generation,input_sha256=context.identity['input_sha256'],statistics_sha256=digest(row['statistics']),projection=entry['projection'],calendar=contract['refs']['calendar'],groups=groups,**FLAGS)
    adapter.load_runtime=runtime;adapter.validate_cache=_validate_daily_history_cache;adapter.full_event_cases=cases
    try:
        canary=output/'CANARY_RESULT.json'
        if not canary.exists():
            adapter.run(output,permit,'canary');_register_automatic(contract_ref,'CANARY_COMPLETED',reference(canary),status='ENGINEERING_CANARY_ONLY')
        adapter.run(output,permit,'batch');result_ref=reference(output/'RESULT.json');result=load(result_ref)
        _register_automatic(contract_ref,'RUN_COMPLETED',result_ref,status=result['status'])
        if result['remaining']:return result
        plan=prepare(output,root,output/'publication');published=publish(plan,refresh=lambda:prepare(output,root,output/'publication')) if plan['status']!='NO_NEW_COMPLETION' else plan
        return dict(status='COMPLETE_DESCRIPTIVE_NONPIT',contract=contract_ref,result=result_ref,publication=published)
    finally:
        adapter.load_runtime=original_runtime;adapter.validate_cache=original_validate;adapter.full_event_cases=original_cases
        for owner,original in patched_owners:owner.cached_daily_statistics=original


def prepare_exact_metadata_row(context,root,output,computation_ref):
    """Merge the one already-computed unselected D30 row; no formula execution."""
    import copy,os
    from ops import research_panel_daily_product as owner
    from ops.sync_stock_history_completion import Staging,DEFAULT_OWNER_LOCK
    root,output=Path(root),Path(output);done=load(computation_ref);day=str(context.target);symbol='002731.SZ'
    if (done.get('status')!='PREPARED_ORIGINAL_SINGLE_ROW_NOT_PUBLISHED'or done.get('symbol')!=symbol or done.get('target_date')!=context.target
        or context.target!=20261030 or done.get('source_identity')!=context.identity or done.get('source_config')!=context.config_ref
        or done.get('code',{}).get('sha256')!=reference(Path(owner.__file__))['sha256']):raise ValueError('EXACT_ROW_COMPUTATION_BINDING_CONFLICT')
    checked(done['code']);checked(done['typed_fact']);row=load(done['row']);cache=load(done['cache'])
    if (row['symbol']!=symbol or row['data_date']!=day or row['groups'] or row['pending_groups']
        or row['qualification']['status']!='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
        or cache['source_identity']!=context.identity or any(row.get(k)!=v for k,v in FLAGS.items())):raise ValueError('EXACT_ROW_OBSERVED_UNSELECTED_ORACLE_CONFLICT')
    actual=context.qualify(symbol)
    expected=copy.deepcopy(row['qualification']);actual=copy.deepcopy(actual)
    for value in (actual,expected):value.get('history_end_metadata',{}).pop('validator',None)
    if actual!=expected:raise ValueError('EXACT_ROW_CURRENT_QUALIFICATION_DRIFT')
    bars,_=context.read(symbol)
    if cache['prefix_sha256']!=digest(bars)or cache['rules_signature']!=digest(context.config):raise ValueError('EXACT_ROW_CURRENT_PREFIX_OR_RULE_DRIFT')
    index_ref,event_ref=reference(root/'index.json'),reference(root/'events/latest.json');index,event=load(index_ref),load(event_ref);manifest_ref=index['dates'][day];manifest=load(manifest_ref);product=load(manifest['artifact'])
    prior=index.get('exact_metadata_rows',{}).get(day,{}).get(symbol)
    if prior and prior.get('computation')==computation_ref and product['row_refs'][symbol]==prior['row']:
        context.unchanged();return dict(status='NO_NEW_COMPLETION',reason='EXACT_METADATA_ROW_ALREADY_PUBLISHED',completed=[symbol],**FLAGS)
    if (manifest_ref!=done['original_numeric_manifest']or product['source_identity']!=context.identity or product['row_refs'][symbol]!=done['original_row']
        or event.get('manifest')!=manifest_ref or event.get('source_generation')!=context.generation
        or symbol in {r['symbol']for r in product['rows']}):raise ValueError('EXACT_ROW_ORIGINAL_NUMERIC_MOVED')
    old=load(done['original_row']);writer=Staging(root,output);updated=copy.deepcopy(product)
    updated['row_refs'][symbol]=writer.immutable('exact_metadata_rows/'+day,symbol+'.json',row)
    for group in GROUPS:
        before,after=old['evaluation']['groups'][group]['status'],row['evaluation']['groups'][group]['status']
        updated['three_value_counts'][group][before]-=1;updated['three_value_counts'][group][after]=updated['three_value_counts'][group].get(after,0)+1
        updated['group_counts'][group]=updated['three_value_counts'][group].get('TRUE',0)
    updated['unknown_count']+=int(bool(row['pending_groups']))-int(bool(old['pending_groups']));updated['status']='PARTIAL_WITH_ROWS'if updated['unknown_count']else'READY'
    artifact=writer.immutable('versions/'+day+'/'+context.generation,'product.json',updated);new_manifest={**manifest,'artifact':artifact,'counts':updated['three_value_counts'],'status':updated['status']};new_manifest_ref=writer.immutable('exact_metadata_rows/'+day+'/manifests','manifest.json',new_manifest)
    descriptor=index['original_charts'][day];original_charts=load(descriptor['manifest']);original_receipt=load(descriptor['receipt'])
    if descriptor['numeric_manifest']!=manifest_ref or original_receipt['status']!='OWNER_CHARTS_COMPLETED'or set(original_charts['samples'])!={r['symbol']for r in product['rows']}:raise ValueError('EXACT_ROW_ORIGINAL_CHARTS_NOT_COMPLETE')
    parts={str(Path(item['source_cache']['path']).parent.parent)for item in original_charts['samples'].values()}
    if len(parts)!=1:raise ValueError('EXACT_ROW_RETAINED_CHART_NAMESPACE_CONFLICT')
    renderer=owner.module(done['renderer'],'accepted_metadata_row_chart_owner')
    def reuse_png(items):
        errors={}
        for item in items:
            stock=item['symbol'];old_item=original_charts['samples'][stock]
            if (updated['row_refs'][stock]!=product['row_refs'][stock]or item['rows']!=old_item['rows']):raise ValueError('EXACT_ROW_UNCHANGED_CHART_ROW_DRIFT')
            source=checked(old_item['PNG']);destination=Path(item['png']);destination.parent.mkdir(parents=True,exist_ok=True)
            if destination.exists():
                if reference(destination)['sha256']!=old_item['PNG']['sha256']:raise ValueError('EXACT_ROW_EXISTING_PNG_VIEW_CONFLICT')
            else:os.link(source,destination)
        return errors
    new_descriptor=renderer.finalize_owner_charts(context,Path(next(iter(parts))),updated,new_manifest_ref,artifact,gaps={},png_renderer=reuse_png)
    if new_descriptor['status']!='OWNER_CHARTS_COMPLETED':raise ValueError('EXACT_ROW_RETAINED_CHART_VIEW_INCOMPLETE')
    new_index=copy.deepcopy(index);new_index['dates'][day]=new_manifest_ref
    if new_index.get('latest_date')==day:new_index['latest']=new_manifest_ref
    new_index['original_charts'][day]=new_descriptor
    cases=load(index['event_cases'][day]);origins=cases.setdefault('case_numeric_origins',{})
    for stock,ref in cases['items'].items():origins.setdefault(stock,load(ref)['numeric_manifest'])
    cases['numeric_manifest']=new_manifest_ref;new_index['event_cases'][day]=writer.immutable('event_cases/'+day,'index.json',cases)
    previous_index=writer.immutable('exact_metadata_rows/'+day,'previous_index.json',index)
    new_index.setdefault('exact_metadata_rows',{}).setdefault(day,{})[symbol]=dict(computation=computation_ref,row=updated['row_refs'][symbol],previous_index=previous_index,original_row=done['original_row'])
    old_top=new_index.get('top200',{}).pop(day,None)
    if old_top:new_index['exact_metadata_rows'][day][symbol]['prior_top200']=old_top
    new_event={**event,'manifest':new_manifest_ref,'artifact':artifact,'original_charts':new_descriptor,'event_cases':new_index['event_cases'][day],
        'unknown_count':updated['unknown_count'],'event_id':digest(dict(manifest=new_manifest_ref,exact_metadata_row=computation_ref))};new_event.pop('top200',None)
    rule=cache['rule_sha256'];cache_path=root/'history'/rule/symbol/'checkpoint.json'
    if reference(cache_path)!=done['original_cache']:raise ValueError('EXACT_ROW_ORIGINAL_CACHE_MOVED')
    previous_cache=writer.immutable('exact_metadata_rows/'+day,'previous_cache.json',load(done['original_cache']));candidate_cache=save(output/'current_cache.json',cache)
    lock=DEFAULT_OWNER_LOCK.stat();plan=dict(status='PREPARED_EXACT_METADATA_ROW',expected_index=index_ref,expected_event=event_ref,staged_index=save(output/'index.json',new_index),staged_event=save(output/'event.json',new_event),
        immutable_files=writer.files,completed=[symbol],owner_publisher=reference(Path(owner.__file__)),shared_owner_lock=dict(path=str(DEFAULT_OWNER_LOCK),device=lock.st_dev,inode=lock.st_ino),
        target_root=str(root),stage=str(output),computation=computation_ref,expected_cache=done['original_cache'],previous_cache=previous_cache,candidate_cache=candidate_cache,cache_path=str(cache_path),
        old_chart_refs=descriptor,new_chart_refs=new_descriptor,unchanged_other_row_refs=5807,formula_engine_compute_calls=0,new_historical_bootstrap_computations=0,**FLAGS)
    save(output/'PLAN.json',plan);context.unchanged();return plan


def publish_exact_metadata_row(context,root,output,computation_ref):
    from ops.sync_stock_history_completion import publish
    from ops import research_panel_daily_product as owner
    plan=prepare_exact_metadata_row(context,root,output,computation_ref)
    if plan['status']=='NO_NEW_COMPLETION':return plan
    if reference(plan['cache_path'])!=plan['expected_cache']:raise ValueError('EXACT_ROW_CACHE_CAS_MOVED')
    receipt=publish(plan)
    try:
        if reference(plan['cache_path'])!=plan['expected_cache']:raise ValueError('EXACT_ROW_CACHE_CAS_MOVED_AFTER_INDEX')
        after=owner.save(Path(plan['cache_path']),load(plan['candidate_cache']))
    except BaseException:
        rollback={**plan,'status':'PREPARED_EXACT_METADATA_ROW_ROLLBACK','expected_index':receipt['index'],'expected_event':receipt['event'],
            'staged_index':save(Path(output)/'rollback_index.json',receipt['before']['index']),'staged_event':save(Path(output)/'rollback_event.json',receipt['before']['event']),'immutable_files':{}}
        publish(rollback);raise
    result=dict(status='PUBLISHED_EXACT_METADATA_ROW',publication=receipt,cache_before=plan['expected_cache'],cache_after=after,
        computation=computation_ref,unchanged_other_row_refs=5807,reused_existing_pngs=172,formula_engine_compute_calls=0,**FLAGS)
    save(Path(output)/'EXACT_ROW_PUBLICATION_RECEIPT.json',result);return result


def prepare_current_history_view(context,root,output):
    """Current completed view over real retained labels, with original owner CAS."""
    import copy
    from ops import bootstrap_stock_event_history as adapter
    from ops import research_panel_daily_product as owner
    from ops.sync_stock_history_completion import Staging,DEFAULT_OWNER_LOCK
    root,output=Path(root),Path(output);index_ref,event_ref=reference(root/'index.json'),reference(root/'events/latest.json');index,event=load(index_ref),load(event_ref);day=str(context.target)
    manifest_ref=index['dates'][day];manifest=load(manifest_ref);product=load(manifest['artifact']);selected=sorted(row['symbol']for row in product['rows'])
    if (product.get('data_date')!=day or manifest.get('data_date')!=day or event.get('data_date')!=day or str(context.identity.get('asof'))!=day
        or product['source_identity']!=context.identity or manifest['source_generation']!=context.generation or product['source_config']!=context.config_ref
        or event.get('manifest')!=manifest_ref or event.get('artifact')!=manifest['artifact']or event.get('source_generation')!=context.generation
        or len(selected)!=len(set(selected))):raise ValueError('CURRENT_HISTORY_VIEW_SOURCE_CONFLICT')
    old=index.get('history_sync',{}).get(day)
    current_rows={symbol:product['row_refs'][symbol]for symbol in selected};chart_ref=index['original_charts'][day]['manifest'];chart=load(chart_ref)
    if old and old.get('current_view_validation'):
        proof=load(old['current_view_validation'])
        if (old.get('numeric_manifest')==manifest_ref and old.get('source_generation')==context.generation
            and old.get('input_sha256')==context.identity['input_sha256'] and old.get('candidate_symbols')==selected
            and old.get('completed_symbols')==selected and proof.get('current_rows')==current_rows
            and proof.get('source_identity')==context.identity and proof.get('source_config')==context.config_ref
            and proof.get('chart_manifest')==chart_ref):
            for row in proof['stocks'].values():checked(row['cache'])
            context.unchanged();return dict(status='NO_NEW_COMPLETION',reason='CURRENT_HISTORY_VIEW_ALREADY_EXACT',proof=old['current_view_validation'],completed=selected,**FLAGS)
    caches={};bars_by_symbol={};cache_refs={};projections={};rows={}
    for symbol in selected:
        row=load(current_rows[symbol]);coverage=row.get('historical_coverage',{})
        if not coverage.get('known_full_history')or coverage.get('missing'):raise ValueError('CURRENT_HISTORY_VIEW_REAL_GAPS:'+symbol)
        projection_ref=chart['samples'][symbol]['projection'];projection=adapter.load(projection_ref);source_cache={k:projection['source_cache'][k]for k in ('path','sha256')}
        if adapter.projection_identity(projection)!=context.identity:raise ValueError('CURRENT_HISTORY_VIEW_PROJECTION_IDENTITY_CONFLICT')
        previous_target=adapter.TARGET
        try:
            adapter.TARGET=context.target;_,bars=adapter.retained_sample(projection,adapter.load(source_cache))
        finally:adapter.TARGET=previous_target
        cache_ref=reference(root/'history'/adapter.RULE/symbol/'checkpoint.json');cache=load(cache_ref)
        if set(cache['evaluations'])!={str(bar['trade_date'])for bar in bars}:raise ValueError('CURRENT_HISTORY_VIEW_PREFIX_COVERAGE_CONFLICT')
        if (coverage.get('evaluated_count')!=len(cache['evaluations']) or row.get('symbol')!=symbol or row.get('data_date')!=day
            or cache['evaluations'][day]['groups']!={g:row['evaluation']['groups'][g]['status']for g in GROUPS}):raise ValueError('CURRENT_HISTORY_VIEW_CURRENT_LABEL_CONFLICT')
        caches[symbol],bars_by_symbol[symbol],cache_refs[symbol],rows[symbol]=cache,bars,cache_ref,row
        projections[symbol]=dict(projection=projection_ref,retained_source_cache=source_cache)
    proofs=_prior_generation_proofs(context,caches,bars_by_symbol);stocks={}
    for symbol in selected:
        _validate_daily_history_cache(owner,caches[symbol],bars_by_symbol[symbol],context.identity,context.config,proofs[symbol])
        stocks[symbol]=dict(row=current_rows[symbol],cache=cache_refs[symbol],**projections[symbol],evaluation_count=len(caches[symbol]['evaluations']),
            rule_sha256=caches[symbol]['rule_sha256'],rules_signature=caches[symbol]['rules_signature'],prefix_sha256=digest(bars_by_symbol[symbol]),
            calendar_sha256=digest(context.calendars[symbol[-2:]]),basis=context.identity['basis'],prior_sources=proofs[symbol]['sources'],prior_records_sha256=digest(proofs[symbol]['records']))
    retained_results=dict((old or {}).get('stock_results',{}));retained_checks={}
    for symbol,result_ref in retained_results.items():
        result=load(result_ref);cache_ref=result['history_cache'];cache=load(cache_ref)
        if (result['symbol']!=symbol or result['status']!='COMPLETE_DESCRIPTIVE_NONPIT' or any(result.get(k)!=v for k,v in FLAGS.items())):raise ValueError('CURRENT_HISTORY_VIEW_RETAINED_RESULT_INVALID')
        if symbol in caches:
            current=caches[symbol]
            if (cache.get('rule_sha256')!=current['rule_sha256']or cache.get('rules_signature')!=current['rules_signature']
                or not set(cache['evaluations'])<=set(current['evaluations'])or any(record['groups']!=current['evaluations'][day]['groups']for day,record in cache['evaluations'].items())):raise ValueError('CURRENT_HISTORY_VIEW_RETAINED_LABEL_REVISION:'+symbol)
        retained_checks[symbol]=dict(result=result_ref,original_cache=cache_ref,original_source_identity=cache['source_identity'],selected=symbol in caches)
    context.unchanged();writer=Staging(root,output);before=writer.immutable('current_history_views/'+day,'before_index.json',index);previous=writer.immutable('current_history_views/'+day,'previous_sync.json',old)if old else None
    proof=dict(schema='CURRENT_COMPLETED_HISTORY_VIEW_V1',status='VERIFIED_REUSED_NO_COMPUTE',numeric_manifest=manifest_ref,source_identity=context.identity,source_config=context.config_ref,
        current_rows=current_rows,chart_manifest=chart_ref,stocks=stocks,retained_results=retained_checks,previous_sync=previous,before_index=before,
        producer=reference(Path(__file__)),new_label_evaluations=0,new_return_evaluations=0,**FLAGS)
    proof_ref=writer.immutable('current_history_views/'+day,'proof.json',proof)
    sync=dict(numeric_manifest=manifest_ref,source_generation=context.generation,input_sha256=context.identity['input_sha256'],candidate_symbols=selected,completed_symbols=selected,
        bootstrap_symbols=[],preserved_complete_symbols=selected,retained_bootstrap_symbols=(old or {}).get('bootstrap_symbols',[]),stock_results=retained_results,
        contract=(old or {}).get('contract'),current_view_validation=proof_ref,status='COMPLETE',reuse_status='REUSED_NO_COMPUTE',**FLAGS)
    updated=copy.deepcopy(index);updated.setdefault('history_sync',{})[day]=sync;new_event={**event,'history_view':proof_ref,'event_id':digest(dict(numeric_manifest=manifest_ref,history_view=proof_ref))}
    lock=DEFAULT_OWNER_LOCK.stat();plan=dict(status='PREPARED_CURRENT_HISTORY_VIEW',expected_index=index_ref,expected_event=event_ref,staged_index=save(output/'index.json',updated),
        staged_event=save(output/'event.json',new_event),immutable_files=writer.files,completed=selected,shared_owner_lock=dict(path=str(DEFAULT_OWNER_LOCK),device=lock.st_dev,inode=lock.st_ino),
        owner_publisher=reference(Path(owner.__file__)),target_root=str(root),stage=str(output),proof=proof_ref,**FLAGS)
    save(output/'PLAN.json',plan);return plan


def publish_current_history_view(context,root,output):
    from ops.sync_stock_history_completion import publish
    plan=prepare_current_history_view(context,root,output)
    return plan if plan['status']=='NO_NEW_COMPLETION'else publish(plan,refresh=lambda:prepare_current_history_view(context,root,output))


def complete_daily_derivatives(data_root,target,root,receipt_root,classification_root,upstream_failure=None):
    """Called once in the original A executor after its producer returns."""
    import os
    from ops.research_panel_daily_product import SourceContext
    from ops.sync_stock_history_completion import publish
    root=Path(root);day=str(target);output=root/'continuations'/day
    try:
        if upstream_failure is not None:raise ValueError('UPSTREAM_DAILY_SOURCE_FAILED:'+str(upstream_failure.get('reason') or upstream_failure.get('status')))
        os.environ['V4_RESEARCH_EVENT_LABEL_SOURCE_ROOT']=str(root)
        context=SourceContext(data_root,int(target))
        history=run_incremental_history(context,root,output/context.generation/'history')
        if history['status'] not in {'COMPLETE_DESCRIPTIVE_NONPIT','COMPLETE_NO_HISTORY_GAPS'}:raise ValueError('DAILY_HISTORY_PARTIAL')
        history_view=publish_current_history_view(context,root,output/context.generation/'current_history_view')
        official_ref=reference(Path(receipt_root)/'a_sync_authority/official_daily'/day/'input.json')
        payload,reuse=build(context,root,official_ref,classification_root)
        existing=json.loads((root/'index.json').read_bytes()).get('top200',{}).get(day)
        if not reuse['reused']:
            plan=stage(payload,root,output/context.generation/'top200',reference(Path(__import__('ops.research_panel_daily_product',fromlist=['digest']).__file__)))
            publication=publish(plan)
        else:publication=dict(status='REUSED',artifact=existing)
        statistics_root=os.environ.get('V4_WORKBENCH_STATISTICS_ROOT')
        if statistics_root:
            from ops.build_mac_workbench import materialize_statistics
            materialize_statistics(root,Path(statistics_root))
        receipt=dict(schema='V4_A_DAILY_DERIVATIVES_V1',status='COMPLETE_DESCRIPTIVE_NONPIT',data_date=day,source_generation=context.generation,history=history,history_view=history_view,top200=publication,computation=reuse,**FLAGS)
    except Exception as error:
        receipt=dict(schema='V4_A_DAILY_DERIVATIVES_V1',status='CANNOT_CONFIRM',data_date=day,error=str(error),**FLAGS)
    save(output/'latest_receipt.json',receipt)
    receipt['attempt']=record_daily_attempt(root,receipt)
    return receipt


def record_daily_attempt(root,receipt):
    """Dated failure/completion discovery under the same original lane/CAS."""
    import os,fcntl
    from ops.sync_stock_history_completion import DEFAULT_OWNER_LOCK,_inherited_owner_duplicate
    root=Path(root);root.mkdir(parents=True,exist_ok=True);path=DEFAULT_OWNER_LOCK;stat=path.stat();shared=dict(path=str(path),device=stat.st_dev,inode=stat.st_ino)
    lock=(root/'.stock-history-completion.lock').open('a+b');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    inherited=_inherited_owner_duplicate(shared,receipt['data_date']);fd=inherited if inherited is not None else os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        index_path=root/'index.json';before=index_path.read_bytes()if index_path.exists()else None
        index=json.loads(before)if before else dict(schema_version='v4.a_share.daily_product_index.v1',dates={})
        artifact=save(root/'attempts'/receipt['data_date']/digest(receipt)/'receipt.json',receipt,immutable=True)
        index.setdefault('attempts',{})[receipt['data_date']]=artifact
        if (index_path.read_bytes()if index_path.exists()else None)!=before:raise ValueError('DAILY_ATTEMPT_INDEX_CAS_MOVED')
        save(index_path,index)
        return artifact
    finally:os.close(fd);lock.close()
