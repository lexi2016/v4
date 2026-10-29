"""Current quote observations owned by Stage; never formal selection or PIT repair."""
from copy import deepcopy
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib,json,math,re

MODE='SNAPSHOT_RECOVERY_OBSERVATION'
SCHEMA='stage_center.snapshot_recovery.v1'
FLAGS={'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
ZONE=ZoneInfo('Asia/Shanghai')
GAPS=['ORIGINAL_HOURLY_COMPLETION_NOT_VERIFIED','NOT_ORIGINAL_STAGE_SELECTION','RESEARCH_CONTEXT_UNAVAILABLE']

def clock(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    if result.tzinfo is None:result=result.replace(tzinfo=ZONE)
    return result.astimezone(ZONE)

def now():return datetime.now(ZONE)
def encoded(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(raw):return hashlib.sha256(raw).hexdigest()
def sanitize(v):
    if isinstance(v,dict):return {str(k):sanitize(x) for k,x in v.items()}
    if isinstance(v,(tuple,list)):return [sanitize(x) for x in v]
    if isinstance(v,float) and not math.isfinite(v):return {'non_finite_sdk_value':str(v)}
    return v

def specs():
    from stage_center.contracts import EIGHT_STAGES
    return {v.stage_id:v for v in EIGHT_STAGES if 'A_SHARE' in v.markets}

def identity(date,stage,market='A_SHARE'):
    if not re.fullmatch(r'\d{8}',date) or stage not in specs() or market!='A_SHARE':raise ValueError('SNAPSHOT_RECOVERY_EXACT_A_IDENTITY')
    datetime.strptime(date,'%Y%m%d')
    return date+'/'+stage+'/'+market

def original_cutoff(date,stage):
    identity(date,stage)
    return clock(f'{date[:4]}-{date[4:6]}-{date[6:]}T{specs()[stage].cutoff}+08:00')

def safe_flags(payload):
    if any(payload.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):raise ValueError('SNAPSHOT_SAFETY_CONFLICT')

def quote_row(row,requested,captured):
    code=str(row.get('symbol') or '')
    if code not in requested or not re.fullmatch(r'A\.\d{6}',code):raise ValueError('QUOTE_REQUEST_OR_MARKET_MISMATCH')
    from infrastructure.futu_quote_provider import to_futu_symbol
    to_futu_symbol(code) # Existing BJ mapping stays unsupported, independently quarantined.
    if isinstance(row.get('last_price'),bool):raise ValueError('QUOTE_PRICE_INVALID')
    price=float(row.get('last_price'))
    if not math.isfinite(price) or price<=0:raise ValueError('QUOTE_PRICE_INVALID')
    source=clock(str(row.get('source_update_time')))
    if source.date()!=captured.date() or source>captured:raise ValueError('QUOTE_SOURCE_TIME_FUTURE_OR_WRONG_DAY')
    for key in ('open_price','high_price','low_price','prev_close_price','bid_price1','ask_price1'):
        value=row.get(key)
        if value is not None and (not math.isfinite(float(value)) or float(value)<0):raise ValueError('QUOTE_PRICE_FIELD_INVALID:'+key)
    for key in ('volume','turnover','bid_vol1','ask_vol1'):
        value=row.get(key)
        if value is not None and (not math.isfinite(float(value)) or float(value)<0):raise ValueError('QUOTE_QUANTITY_FIELD_INVALID:'+key)
    high,low=row.get('high_price'),row.get('low_price')
    if high and low and float(high)<float(low):raise ValueError('QUOTE_PRICE_RANGE_CONFLICT')
    return {**deepcopy(row),'code':code,'symbol':code,'last_price':price,'source_update_time':source.isoformat()}

def normalized_snapshot(snapshot,codes,observed_now):
    safe_flags(snapshot)
    if snapshot.get('stage_id')!=MODE:raise ValueError('SNAPSHOT_OBSERVATION_IDENTITY')
    if snapshot.get('schema_version')!='v3_5.read_only_quote_batch.v1' or snapshot.get('source')!='FUTU_OPEND_READ_ONLY_SNAPSHOT':raise ValueError('SNAPSHOT_PROVIDER_IDENTITY')
    for field in ('capture_started_at','captured_at'):
        if datetime.fromisoformat(snapshot[field].replace('Z','+00:00')).tzinfo is None:raise ValueError('TRUE_CAPTURE_CLOCK_ZONE_MISSING')
    start=clock(snapshot['capture_started_at']);captured=clock(snapshot['captured_at'])
    if not start<=captured<=observed_now or snapshot.get('trade_date')!=captured.strftime('%Y%m%d'):raise ValueError('TRUE_CAPTURE_CLOCK_INVALID')
    if snapshot.get('batches'):
        flat=[]
        for batch in snapshot['batches']:
            if batch.get('batches'):raise ValueError('NESTED_QUOTE_BATCH_FORBIDDEN')
            if clock(batch['capture_started_at'])<start or clock(batch['captured_at'])>captured:raise ValueError('QUOTE_BATCH_CLOCK_BINDING')
            normalized_snapshot(batch,codes,observed_now)
            flat.extend([{**r,'observation_capture_started_at':batch['capture_started_at'],'observation_captured_at':batch['captured_at']} for r in batch['rows']])
        if flat!=snapshot.get('rows'):raise ValueError('QUOTE_BATCH_ROWS_BINDING')
    requested=tuple(dict.fromkeys(codes));accepted={};rejected=[];duplicates=set()
    from infrastructure.futu_quote_provider import to_futu_symbol
    for code in requested:
        try:to_futu_symbol(code)
        except (ValueError,TypeError):rejected.append({'symbol':code,'reason':'UNSUPPORTED_OR_WRONG_MARKET'})
    for row in snapshot.get('rows',[]):
        try:
            row_capture=clock(row.get('observation_captured_at',captured))
            if row_capture>captured or row_capture<start:raise ValueError('QUOTE_ROW_CAPTURE_CLOCK_BINDING')
            normalized=quote_row(row,requested,row_capture);code=normalized['code']
            if code in accepted or code in duplicates:
                accepted.pop(code,None);duplicates.add(code);raise ValueError('DUPLICATE_QUOTE_IDENTITY')
            accepted[code]=normalized
        except (KeyError,TypeError,ValueError,OverflowError) as error:rejected.append({'symbol':row.get('symbol'),'reason':str(error)})
    return [accepted[c] for c in requested if c in accepted],rejected,start,captured

def failure_record(config,date,stage):
    from infrastructure.owned_io import SafeRoot
    relative=f'{date}/{stage}/receipt.json'
    try:raw=SafeRoot(Path(config['receipt_root'])).read_bytes(relative)
    except FileNotFoundError:return {'sha256':None,'relative':relative,'reasons':['ORIGINAL_STAGE_RECEIPT_MISSING'],'status':'MISSING'}
    value=json.loads(raw);safe_flags(value)
    if value.get('trade_date')!=date or value.get('stage_id')!=stage:raise ValueError('ORIGINAL_STAGE_RECEIPT_IDENTITY')
    lane=(value.get('markets') or {}).get('A_SHARE') or {}
    reasons=[str(x) for x in lane.get('cannot_confirm') or []]
    return {'sha256':digest(raw),'relative':relative,'reasons':reasons,'status':lane.get('status',lane.get('selection_status')),'selected_rows':lane.get('selected_rows')}

def selection_available(root,date,stage):
    from stage_center.selection import SelectionStore,SelectionError
    try:
        value=SelectionStore(root).read_verified(date,stage,'A_SHARE')
        return bool(value.get('rows')) or value.get('selection_status') in {'READY','READY_EMPTY'}
    except (FileNotFoundError,OSError,ValueError,SelectionError):return False

class ObservationStore:
    def __init__(self,root):
        from infrastructure.owned_io import SafeRoot
        self.io=SafeRoot(Path(root))
    def pointer(self,date,stage):return 'snapshot_recovery/current/'+identity(date,stage)+'.json'
    def read(self,date,stage):
        pointer=json.loads(self.io.read_bytes(self.pointer(date,stage)))
        if pointer.get('schema')!=SCHEMA+'.pointer':raise ValueError('OBSERVATION_POINTER_SCHEMA')
        for key in ('artifact','manifest','receipt','capture'):
            raw=self.io.read_bytes(pointer[key+'_relative'])
            if digest(raw)!=pointer[key+'_sha256']:raise ValueError('OBSERVATION_'+key.upper()+'_SHA_MISMATCH')
        capture=json.loads(self.io.read_bytes(pointer['capture_relative']))
        artifact=json.loads(self.io.read_bytes(pointer['artifact_relative']));manifest=json.loads(self.io.read_bytes(pointer['manifest_relative']));receipt=json.loads(self.io.read_bytes(pointer['receipt_relative']))
        if artifact.get('schema')!=SCHEMA or artifact.get('trade_date')!=date or artifact.get('stage_id')!=stage or artifact.get('market')!='A_SHARE' or artifact.get('mode')!=MODE:raise ValueError('OBSERVATION_IDENTITY')
        for value in (artifact,manifest,receipt):safe_flags(value)
        if manifest.get('artifact_sha256')!=pointer['artifact_sha256'] or receipt.get('manifest_sha256')!=pointer['manifest_sha256'] or receipt.get('artifact_sha256')!=pointer['artifact_sha256']:raise ValueError('OBSERVATION_TRIO_BINDING')
        if artifact.get('formal_selected_rows')!=0 or artifact.get('natural_execution_verified') is not False or artifact.get('original_stage_cutoff_safe') is not False:raise ValueError('OBSERVATION_PROMOTION_FORBIDDEN')
        for value,kind in ((manifest,'manifest'),(receipt,'receipt')):
            if value.get('schema')!=SCHEMA+'.'+kind or value.get('observation_id')!=artifact.get('observation_id'):raise ValueError('OBSERVATION_TRIO_IDENTITY')
        if manifest.get('capture_sha256')!=pointer['capture_sha256']:raise ValueError('OBSERVATION_CAPTURE_BINDING')
        captured=clock(artifact['captured_at']);requested=tuple(artifact['requested_symbols']);seen=set()
        original_rows,_,start,sealed_capture=normalized_snapshot(capture,requested,clock(artifact['published_at']))
        if sealed_capture!=captured or start!=clock(artifact['capture_started_at']) or captured<=original_cutoff(date,stage):raise ValueError('OBSERVATION_CAPTURE_CLOCK_BINDING')
        sealed={r['code']:r for r in original_rows}
        if artifact.get('observed_rows')!=len(artifact['rows']) or len(sealed)!=len(artifact['rows']):raise ValueError('OBSERVATION_COVERAGE_BINDING')
        for row in artifact['rows']:
            quote_row(row,requested,captured)
            if (any(row.get(k) is not None for k in ('score','stage_score','news_quality_score','research_quality_score','research_bonus','latest_research_slot'))
                or any(row.get(k)!='WATCH_ONLY' for k in ('status','action_level','trade_status'))
                or row.get('formal_eligible') is not False or row['code'] in seen
                or row.get('original_stage_id')!=stage or row.get('original_trade_date')!=date
                or row.get('captured_at')!=clock(row.get('observation_captured_at',artifact['captured_at'])).isoformat() or row.get('after_original_cutoff') is not True
                or row.get('original_stage_cutoff_at')!=original_cutoff(date,stage).isoformat()):raise ValueError('OBSERVATION_ROW_CONTRACT')
            original=sealed.get(row['code'])
            if original is None or any(row.get(k)!=v for k,v in original.items()):raise ValueError('OBSERVATION_CAPTURE_ROW_BINDING')
            seen.add(row['code'])
        return artifact
    def publish(self,artifact,capture_bytes):
        date,stage=artifact['trade_date'],artifact['stage_id'];key=identity(date,stage)
        observation_id=digest(encoded({'key':key,'capture_sha256':digest(capture_bytes),'candidate_current_sha256':artifact['candidate_current_sha256'],'original_receipt_sha256':artifact['original_failure']['sha256']}))
        prefix='snapshot_recovery/runs/'+key+'/'+observation_id
        with self.io.kernel_lock('snapshot_recovery/publish.lock',timeout=2):
            try:
                prior=self.read(date,stage)
                if prior.get('observation_id')==observation_id:return prior
                if clock(prior['captured_at'])>=clock(artifact['captured_at']):raise ValueError('OBSERVATION_CAPTURE_NOT_NEWER')
            except FileNotFoundError:pass
            artifact={**artifact,'observation_id':observation_id};raw=encoded(artifact)
            manifest={'schema':SCHEMA+'.manifest','observation_id':observation_id,'artifact_sha256':digest(raw),'capture_sha256':digest(capture_bytes),**FLAGS};manifest_bytes=encoded(manifest)
            receipt={'schema':SCHEMA+'.receipt','observation_id':observation_id,'artifact_sha256':digest(raw),'manifest_sha256':digest(manifest_bytes),'published_at':artifact['published_at'],**FLAGS}
            parts={'capture':capture_bytes,'artifact':raw,'manifest':manifest_bytes,'receipt':encoded(receipt)};pointer={'schema':SCHEMA+'.pointer'}
            for name,content in parts.items():
                relative='snapshot_recovery/captures/'+digest(content)+'.json' if name=='capture' else prefix+'/'+name+'.json'
                try:self.io.write_bytes(relative,content,require_absent=True)
                except FileExistsError:
                    if self.io.read_bytes(relative)!=content:raise ValueError('IMMUTABLE_OBSERVATION_CONFLICT')
                pointer[name+'_relative']=relative;pointer[name+'_sha256']=digest(content)
            self.io.write_bytes(self.pointer(date,stage),encoded(pointer)) # Observation-only pointer; never formal/latest.
        return self.read(date,stage)

def build_observation(snapshot,codes,candidate,date,stage,failure,observed_now):
    accepted,rejected,start,captured=normalized_snapshot(snapshot,codes,observed_now)
    cutoff=original_cutoff(date,stage)
    if captured<=cutoff:raise ValueError('RECOVERY_OBSERVATION_NOT_AFTER_ORIGINAL_STAGE')
    rows=[]
    for number,row in enumerate(accepted,1):
        rows.append({**row,'observation_order':number,'status':'WATCH_ONLY','action_level':'WATCH_ONLY','trade_status':'WATCH_ONLY','formal_eligible':False,'score':None,'stage_score':None,'news_quality_score':None,'research_quality_score':None,'research_bonus':None,'latest_research_slot':None,'gaps':list(GAPS),'selection_mode':MODE,'original_trade_date':date,'original_stage_id':stage,'original_stage_cutoff_at':cutoff.isoformat(),'captured_at':clock(row.get('observation_captured_at',captured)).isoformat(),'after_original_cutoff':True})
    return {'schema':SCHEMA,'mode':MODE,'market':'A_SHARE','trade_date':date,'stage_id':stage,'observed_trade_date':captured.strftime('%Y%m%d'),'capture_started_at':start.isoformat(),'captured_at':captured.isoformat(),'published_at':observed_now.isoformat(),'original_stage_cutoff_at':cutoff.isoformat(),'after_original_cutoff':True,'original_stage_cutoff_safe':False,'natural_execution_verified':False,'original_failure':failure,'candidate_current_sha256':candidate.current_sha256,'candidate_run_id':candidate.run_id,'requested_symbols':list(codes),'requested_rows':len(codes),'observed_rows':len(rows),'formal_selected_rows':0,'rejected_rows':rejected,'missing_symbols':[c for c in codes if c not in {r['code'] for r in rows}],'rows':rows,'gaps':list(GAPS),**FLAGS}

def recover(config,date,*,stages=None,input_path=None,receipt_path=None,provider=None,wall=now,manual=False):
    from stage_center.candidate_input import read_candidate_input
    observed_now=clock(wall());store=ObservationStore(config['selection_root']);targets=[]
    if not manual and date!=observed_now.strftime('%Y%m%d'):return {'status':'SKIPPED_NOT_CURRENT_DATE','observations':[]}
    safe_flags(config.get('safety') or {})
    for stage in stages or specs():
        cutoff=original_cutoff(date,stage)
        if cutoff>=observed_now or selection_available(config['selection_root'],date,stage):continue
        failure=failure_record(config,date,stage)
        if failure.get('selected_rows') and int(failure['selected_rows'])>0:continue
        relevant=failure['status']=='MISSING' or any('HOURLY' in r or 'RESEARCH_SOURCE_WITNESS_INVALID' in r or 'A_NATIVE_' in r for r in failure['reasons'])
        if not relevant:continue
        if not manual:
            try:
                if store.read(date,stage).get('rows'):continue
            except FileNotFoundError:pass
        targets.append((stage,failure))
    if not targets:return {'status':'NO_MISSING_OBSERVATION_TARGET','observations':[],'provider_invocations':0,**FLAGS}
    candidate=read_candidate_input(Path(config['candidate_acquisition_root']),date);codes=tuple(candidate.codes)
    if input_path:
        raw=Path(input_path).read_bytes();snapshot=json.loads(raw);receipt=json.loads(Path(receipt_path).read_bytes());safe_flags(receipt)
        if receipt.get('schema')!='v4.current_snapshot_recovery_capture.v1' or receipt.get('snapshot_sha256')!=digest(raw) or receipt.get('not_historical_selection') is not True or receipt.get('natural_execution_verified') is not False:raise ValueError('IMPORTED_CURRENT_CAPTURE_RECEIPT_INVALID')
        if (receipt.get('original_stage_cutoff_safe') is not False or receipt.get('requested_rows')!=len(codes)
            or receipt.get('valid_rows')!=len(snapshot.get('rows',[]))
            or clock(receipt['captured_at'])!=clock(snapshot['captured_at'])):raise ValueError('IMPORTED_CURRENT_CAPTURE_RECEIPT_BINDING')
        targets=[(s,f) for s,f in targets if s in receipt.get('original_stage_ids',[])]
        if not targets:return {'status':'NO_AUTHORIZED_IMPORTED_TARGET','observations':[],**FLAGS}
        invocations=0
    else:
        from infrastructure.futu_quote_provider import FutuQuoteProvider,to_futu_symbol
        supported=[]
        for code in codes:
            try:to_futu_symbol(code)
            except (ValueError,TypeError):continue
            if re.fullmatch(r'A\.\d{6}',code):supported.append(code)
        if not supported:return {'status':'NO_SUPPORTED_A_SYMBOLS','observations':[],**FLAGS}
        primary=provider or FutuQuoteProvider(now=wall)
        try:
            # Exact existing pool only, using the original provider's <=220 limit.
            batches=[]
            for offset in range(0,len(supported),220):
                batch_now=clock(wall())
                if batch_now.strftime('%Y%m%d')!=observed_now.strftime('%Y%m%d'):raise ValueError('CURRENT_CAPTURE_DAY_CHANGED')
                batches.append(primary.snapshot(supported[offset:offset+220],trade_date=observed_now.strftime('%Y%m%d'),stage_id=MODE,cutoff_at=(batch_now+timedelta(seconds=30)).isoformat()))
            snapshot=batches[0] if len(batches)==1 else {
                'schema_version':'v3_5.read_only_quote_batch.v1','source':'FUTU_OPEND_READ_ONLY_SNAPSHOT',
                'trade_date':observed_now.strftime('%Y%m%d'),'stage_id':MODE,'capture_started_at':batches[0]['capture_started_at'],
                'captured_at':batches[-1]['captured_at'],'batches':batches,
                'rows':[{**r,'observation_capture_started_at':b['capture_started_at'],'observation_captured_at':b['captured_at']} for b in batches for r in b['rows']],**FLAGS}
        finally:
            if provider is None:primary.close()
        raw=encoded(sanitize(snapshot));invocations=len(batches);observed_now=clock(wall())
    artifacts=[]
    for stage,failure in targets:
        artifact=build_observation(snapshot,codes,candidate,date,stage,failure,observed_now)
        if artifact['rows']:artifacts.append(store.publish(artifact,raw))
    return {'status':'SNAPSHOT_RECOVERY_OBSERVATIONS_AVAILABLE' if artifacts else 'CANNOT_CONFIRM_NO_VALID_CURRENT_QUOTES','observations':artifacts,'provider_invocations':invocations,'formal_selected_rows':0,'natural_execution_verified':False,**FLAGS}

def after_natural_nodes(config,date,nodes,**kwargs):
    if not any(n.get('stage_id') in specs() and n.get('node_id')==n.get('stage_id') for n in nodes):return {'status':'SKIPPED_NON_STAGE_TICK','observations':[],'provider_invocations':0,**FLAGS}
    try:
        from stage_center.snapshot_selection import recover_and_select
        return recover_and_select(config,date,**kwargs)
    except Exception as error:return {'status':'CANNOT_CONFIRM','reason':str(error),'observations':[],**FLAGS} # Optional observation failure cannot change the original stage receipt.

def read_for_api(root,date,stage):
    if stage not in specs():return {'mode':MODE,'status':'NOT_APPLICABLE','markets':{},**FLAGS}
    try:
        artifact=ObservationStore(root).read(date,stage)
        return {'mode':MODE,'status':'OBSERVATIONS_AVAILABLE','markets':{'A_SHARE':artifact},'formal_selected_rows':0,'natural_execution_verified':False,**FLAGS}
    except FileNotFoundError:return {'mode':MODE,'status':'NOT_AVAILABLE','markets':{},**FLAGS}
    except (OSError,ValueError,TypeError) as error:return {'mode':MODE,'status':'CANNOT_CONFIRM','reason':str(error),'markets':{},**FLAGS}
