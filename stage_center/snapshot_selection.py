"""Original A pure-engine supplementary selection on truthful current snapshots.

The original formal/raw pointers and failed receipts are never changed. Optional
neutral defaults belong to the original scorer; absent source scalars stay null.
"""
from dataclasses import asdict
from datetime import datetime,timedelta
from pathlib import Path
from copy import deepcopy
import hashlib,json,math,os,re
from stage_center.snapshot_recovery import ObservationStore,clock,now,encoded,digest,identity,safe_flags,FLAGS,specs,selection_available

MODE='AFTERFACT_SNAPSHOT_RESELECTION'
SCHEMA='stage_center.snapshot_reselection.v1'
REQUIRED_PRICES=('open_price','last_price','prev_close_price','high_price','low_price')
REQUIRED_QUANTITIES=('turnover','bid_vol1','ask_vol1')

def context_for_snapshot(config,observation):
    """Bounded existing-reader last-known-good, separately validated at capture.

    A fallback reader clock is recorded as such, never presented as the capture
    clock. The selected original slot's trusted attestation is ALSO validated at
    the exact real capture timestamp. No trusted-reader code or source is changed.
    """
    from stage_center.research_context import load_research_context
    from infrastructure.research_store import HourlyResearchStore
    from infrastructure.manager_input_attestation import read_stage_hourly_attestation
    capture=clock(observation['captured_at']);date=capture.strftime('%Y%m%d');root=Path(config['v4_research_data_root'])
    slots=sorted((s for s in HourlyResearchStore(root).list_slots(date,mode='LIVE') if re.fullmatch(r'\d{4}',s) and int(s)<=capture.hour*100+capture.minute),reverse=True)
    failures=[];cutoff=capture.replace(microsecond=0)
    for attempt in range(3):
        try:
            context=load_research_context(root,trade_date=date,stage_cutoff=cutoff.strftime('%H:%M:%S'),morning_root=config.get('v4_morning_news_root'))
            app=Path(os.environ['V4_APP_ROOT'])
            publication,owner=read_stage_hourly_attestation(stage_app=app,data_root=root,date=date,slot=context.selected_slot,mode='LIVE',as_of=capture)
            report={'schema':SCHEMA+'.context','slot':context.selected_slot,'reader_validation_as_of':cutoff.isoformat(),'actual_capture_as_of':capture.isoformat(),'input_available_at':publication['input_available_at'],'completion_finished_at':publication['completion_witness']['finished_at'],'completion_receipt_sha256':publication['completion_witness']['receipt_sha256'],'source_input_sha256':publication['source_input_sha256'],'fallback_used':bool(failures),'fallback_rejections':failures,'selection_policy':'BOUNDED_LAST_KNOWN_GOOD_ORIGINAL_READERS','source_evidence':list(context.source_evidence),'cannot_confirm':list(context.cannot_confirm),'by_code':{k:asdict(v) for k,v in context.by_code.items()},**FLAGS}
            return report
        except (OSError,ValueError,KeyError,TypeError) as error:
            eligible=[s for s in slots if int(s)<=cutoff.hour*100+cutoff.minute]
            slot=eligible[0] if eligible else None
            record={'reader_as_of':cutoff.isoformat(),'rejected_slot':slot,'error':type(error).__name__+':'+str(error)}
            if slot:
                from infrastructure.owned_io import SafeRoot
                relative=f'research/incoming/{date}/{slot}.json'
                try:record['source_input_sha256']=digest(SafeRoot(root).read_bytes(relative))
                except FileNotFoundError:record['source_input_sha256']=None
            failures.append(record)
            if slot is None:break
            boundary=datetime.strptime(date+slot,'%Y%m%d%H%M').replace(tzinfo=capture.tzinfo)
            cutoff=boundary-timedelta(seconds=1)
    # The original scorer supports absent research inputs with its own unchanged
    # neutral term. Do not invent source zeros or a successful research witness.
    return {'schema':SCHEMA+'.context','slot':None,'reader_validation_as_of':None,'actual_capture_as_of':capture.isoformat(),'fallback_used':True,'fallback_rejections':failures,'selection_policy':'ORIGINAL_SCORER_WITH_EXPLICIT_MISSING_RESEARCH','source_evidence':[],'cannot_confirm':['NO_VERIFIED_RESEARCH_CONTEXT_AVAILABLE'],'by_code':{},**FLAGS}

def engine_inputs(observation,context):
    inputs=[];excluded=[];coverage=[]
    for order,q in enumerate(observation['rows'],1):
        try:
            for key in REQUIRED_PRICES+REQUIRED_QUANTITIES:
                value=q.get(key)
                if value is None or isinstance(value,bool) or not math.isfinite(float(value)) or float(value)<0 or (key in REQUIRED_PRICES and float(value)<=0):raise ValueError('NECESSARY_QUOTE_FEATURE_MISSING_OR_INVALID:'+key)
            code=q['code'];r=context['by_code'].get(code);missing=[k for k in ('news_quality_score','research_quality_score') if r is None or r.get(k) is None]
            row={'code':code,'stock_name':q.get('name'),'name':q.get('name'),'trade_date':observation['observed_trade_date'],'stage_id':observation['stage_id'],'qmt':{'open':q['open_price'],'lastPrice':q['last_price'],'lastClose':q['prev_close_price'],'high':q['high_price'],'low':q['low_price'],'amount':q['turnover'],'bidVol':[q['bid_vol1']],'askVol':[q['ask_vol1']]},'candidate':{'score':None},'formal_eligible':False,'formal_rank':'','acquisition_rank':order,'lane_evidence':['STAGE_ACQUISITION_UNIVERSE','AFTERFACT_CURRENT_SNAPSHOT'],'update_time':q['source_update_time'],'next_validation_time':None,'news_quality_score':r.get('news_quality_score') if r else None,'research_quality_score':r.get('research_quality_score') if r else None,'research_delta_hits':r.get('research_delta_hits') if r else None,'latest_research_slot':context['slot'] if r else None,'source_health':r.get('source_health') if r else 'CANNOT_CONFIRM','news_research_reason':r.get('news_research_reason') if r else []}
            inputs.append(row);coverage.append({'code':code,'missing_source_fields':missing,'formal_pool_score':None})
        except (KeyError,TypeError,ValueError,OverflowError) as error:excluded.append({'code':q.get('code'),'reason':str(error)})
    return inputs,excluded,coverage

def score(observation,context):
    from stage_center.selection import select_a_live_stage,_selection_identity_ids
    inputs,excluded,coverage=engine_inputs(observation,context)
    evidence=('selection_contract=V3_TOP10_RECOMMENDATION','supplementary_contract='+MODE,'original_stage_pit=false','source=FUTU_CURRENT_SNAPSHOT',*context['source_evidence'])
    envelope=select_a_live_stage(inputs,observation['observed_trade_date'],observation['stage_id'],digest(encoded(observation)),source_status='PARTIAL_WITH_ROWS',requested_rows=observation['requested_rows'],missing_symbols=observation['missing_symbols'],cannot_confirm=('AFTERFACT_NOT_ORIGINAL_STAGE','MISSING_SOURCE_SCORES_STAY_NULL_ORIGINAL_NEUTRAL_FORMULA_UNCHANGED'),source_evidence=evidence)
    by_code={r['code']:r for r in inputs}
    for selected in envelope['rows']:
        source=by_code[selected['code']]
        if source['candidate']['score'] is None:selected['pool_score']=None
        if source['news_quality_score'] is None or source['research_quality_score'] is None:
            for key in ('news_quality_score','research_quality_score','research_delta_hits','latest_research_slot','news_research_reason','source_health'):selected[key]=source[key]
            selected['research_bonus']=None
    artifact_id,run_id=_selection_identity_ids(envelope['trade_date'],envelope['stage_id'],'A_SHARE',envelope['raw_artifact_sha256'],envelope['algorithm_sha256'],envelope['rows']);envelope.update(artifact_id=artifact_id,run_id=run_id)
    return envelope,inputs,excluded,coverage

class SupplementStore:
    def __init__(self,root):
        from infrastructure.owned_io import SafeRoot
        self.root=Path(root);self.io=SafeRoot(self.root)
    def pointer(self,date,stage):return 'snapshot_reselection/current/'+identity(date,stage)+'.json'
    def prefix(self,date,stage,run):
        identity(date,stage)
        if not re.fullmatch(r'[0-9a-f]{64}',run):raise ValueError('SUPPLEMENT_RUN_ID')
        return f'snapshot_reselection/runs/{date}/{stage}/{run}'
    def read(self,date,stage):
        from stage_center.selection import SelectionStore,A_SHARE_LIVE_ALGORITHM_SHA256
        pointer=json.loads(self.io.read_bytes(self.pointer(date,stage)))
        if pointer.get('schema')!=SCHEMA+'.pointer':raise ValueError('SUPPLEMENT_POINTER_SCHEMA')
        prefix=self.prefix(date,stage,pointer['run']);raw=self.io.read_bytes(prefix+'/supplement.json')
        if digest(raw)!=pointer['supplement_sha256']:raise ValueError('SUPPLEMENT_SHA_MISMATCH')
        record=json.loads(raw);safe_flags(record)
        if (record.get('schema')!=SCHEMA or record.get('mode')!=MODE or record.get('requested_trade_date')!=date or record.get('requested_stage_id')!=stage or record.get('original_stage_formal_selected_rows')!=0 or record.get('natural_execution_verified') is not False or record.get('original_stage_cutoff_safe') is not False):raise ValueError('SUPPLEMENT_IDENTITY_OR_PROMOTION')
        for name in ('inputs','context'):
            data=self.io.read_bytes(prefix+'/'+name+'.json')
            if digest(data)!=record[name+'_sha256']:raise ValueError('SUPPLEMENT_'+name.upper()+'_SHA_MISMATCH')
        observation=ObservationStore(self.root).read(date,stage)
        if digest(encoded(observation))!=record['observation_sha256']:raise ValueError('SUPPLEMENT_CURRENT_OBSERVATION_CHANGED')
        if not clock(record['captured_at'])<=clock(record['scoring_evaluated_at'])<=clock(record['scoring_finished_at']):raise ValueError('SUPPLEMENT_ACTUAL_CLOCK_ORDER')
        envelope=SelectionStore(self.root/prefix/'engine').read_verified(record['actual_trade_date'],stage,'A_SHARE')
        if envelope['algorithm_sha256']!=A_SHARE_LIVE_ALGORITHM_SHA256 or digest(encoded(envelope))!=record['engine_envelope_sha256']:raise ValueError('SUPPLEMENT_ENGINE_BINDING')
        if envelope['raw_artifact_sha256']!=record['observation_sha256']:raise ValueError('SUPPLEMENT_OBSERVATION_BINDING')
        return {**record,'rows':envelope['rows'],'selected_rows':envelope['selected_rows'],'algorithm_sha256':envelope['algorithm_sha256'],'selection_status':envelope['selection_status']}
    def publish(self,observation,context,evaluated):
        from stage_center.selection import SelectionStore,A_SHARE_LIVE_ALGORITHM_SHA256
        date,stage=observation['trade_date'],observation['stage_id'];obs_sha=digest(encoded(observation));ctxraw=encoded(context)
        key=digest(encoded({'observation_sha256':obs_sha,'context_sha256':digest(ctxraw),'algorithm_sha256':A_SHARE_LIVE_ALGORITHM_SHA256,'mode':MODE}));prefix=self.prefix(date,stage,key)
        with self.io.kernel_lock('snapshot_reselection/publish.lock',timeout=2):
            try:
                prior=self.read(date,stage)
                if prior['observation_sha256']==obs_sha:return prior
            except FileNotFoundError:pass
            envelope,inputs,excluded,coverage=score(observation,context)
            if not envelope['rows']:raise ValueError('NO_VALID_NECESSARY_SNAPSHOT_FEATURES')
            inputraw=encoded(inputs)
            for name,data in [('context',ctxraw),('inputs',inputraw)]:
                try:self.io.write_bytes(prefix+'/'+name+'.json',data,require_absent=True)
                except FileExistsError:
                    if self.io.read_bytes(prefix+'/'+name+'.json')!=data:raise ValueError('SUPPLEMENT_IMMUTABLE_CONFLICT')
            engine=SelectionStore(self.root/prefix/'engine');published=engine.publish(envelope,market='A_SHARE')
            record={'schema':SCHEMA,'mode':MODE,'requested_trade_date':date,'requested_stage_id':stage,'original_stage_cutoff_at':observation['original_stage_cutoff_at'],'actual_trade_date':observation['observed_trade_date'],'captured_at':observation['captured_at'],'scoring_evaluated_at':evaluated.isoformat(),'scoring_finished_at':now().isoformat(),'context_slot':context['slot'],'context_status':'VERIFIED_LAST_KNOWN_GOOD' if context['slot'] else 'NO_VERIFIED_RESEARCH_CONTEXT','context_cannot_confirm':context.get('cannot_confirm',[]),'context_reader_as_of':context['reader_validation_as_of'],'context_input_available_at':context.get('input_available_at'),'context_completion_finished_at':context.get('completion_finished_at'),'context_fallback_used':context['fallback_used'],'context_rejections':context['fallback_rejections'],'research_coverage':coverage,'excluded_quote_rows':excluded,'requested_rows':observation['requested_rows'],'observed_rows':observation['observed_rows'],'scored_rows':len(inputs),'original_stage_formal_selected_rows':0,'natural_execution_verified':False,'original_stage_cutoff_safe':False,'original_failure':observation['original_failure'],'observation_id':observation['observation_id'],'observation_sha256':obs_sha,'context_sha256':digest(ctxraw),'inputs_sha256':digest(inputraw),'engine_envelope_sha256':digest(encoded(published)),'recommendation_status':'WATCH_ONLY','research_default_policy':'UNCHANGED_ORIGINAL_ENGINE_OPTIONAL_NEUTRAL_DEFAULTS_SOURCE_FIELDS_STAY_NULL','auction_replay':False,**FLAGS}
            data=encoded(record)
            try:self.io.write_bytes(prefix+'/supplement.json',data,require_absent=True)
            except FileExistsError:
                if self.io.read_bytes(prefix+'/supplement.json')!=data:raise ValueError('SUPPLEMENT_IMMUTABLE_CONFLICT')
            self.io.write_bytes(self.pointer(date,stage),encoded({'schema':SCHEMA+'.pointer','run':key,'supplement_sha256':digest(data)}))
        return self.read(date,stage)

def recover_and_select(config,date,*,stages=None,wall=now,**kwargs):
    from stage_center.snapshot_recovery import recover
    store=SupplementStore(config['selection_root']);observations=ObservationStore(config['selection_root']);selected=[];errors=[];contexts={}
    from stage_center.snapshot_recovery import original_cutoff
    targets=[s for s in (stages or specs()) if original_cutoff(date,s)<clock(wall()) and not selection_available(config['selection_root'],date,s)]
    pending=[]
    for stage in targets:
        try:observations.read(date,stage)
        except FileNotFoundError:pending.append(stage)
    result=recover(config,date,stages=pending,wall=wall,**kwargs) if pending else {'status':'EXISTING_OBSERVATIONS_REUSED','observations':[],'provider_invocations':0,**FLAGS}
    for stage in targets:
        if selection_available(config['selection_root'],date,stage):continue
        try:
            observation=observations.read(date,stage)
            try:
                prior=store.read(date,stage)
                if prior['observation_sha256']==digest(encoded(observation)):selected.append(prior);continue
            except FileNotFoundError:pass
            capture=observation['captured_at']
            if capture not in contexts:contexts[capture]=context_for_snapshot(config,observation)
            selected.append(store.publish(observation,contexts[capture],clock(wall())))
        except FileNotFoundError:continue
        except (OSError,ValueError,KeyError,TypeError) as error:errors.append({'stage_id':stage,'reason':str(error)})
    return {**result,'observation_delivery_status':result.get('status'),'status':'SNAPSHOT_RESELECTION_READY' if selected and not errors else 'PARTIAL_SNAPSHOT_RESELECTION' if selected else result.get('status'),'snapshot_reselection':{'mode':MODE,'status':'SELECTED_WATCH_ONLY' if selected else 'CANNOT_CONFIRM','selections':selected,'cannot_confirm':errors,'original_stage_formal_selected_rows':0,'natural_execution_verified':False,**FLAGS}}

def read_for_api(root,date,stage):
    if stage not in specs():return {'mode':MODE,'status':'NOT_APPLICABLE','markets':{},**FLAGS}
    try:return {'mode':MODE,'status':'SELECTED_WATCH_ONLY','markets':{'A_SHARE':SupplementStore(root).read(date,stage)},'original_stage_formal_selected_rows':0,'natural_execution_verified':False,**FLAGS}
    except FileNotFoundError:return {'mode':MODE,'status':'NOT_AVAILABLE','markets':{},**FLAGS}
    except (OSError,ValueError,KeyError,TypeError) as error:return {'mode':MODE,'status':'CANNOT_CONFIRM','reason':str(error),'markets':{},**FLAGS}
