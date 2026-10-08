"""Original evidence-first manager projection with independent input lanes."""
import sys
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib
import importlib
import json
from copy import deepcopy
import subprocess
import tempfile
from datetime import datetime,timezone
from v5_shadow import a_preselection as common
from v5_shadow.contracts import aware,trade_date,exact_keys,sha
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
from v5_shadow.composition import no_symlinks
BASE=Path(__file__).resolve().parents[2]
CAPSULE=BASE/'vendor/manager_attention_baseline'
DESCRIPTOR=BASE/'contracts/manager_attention_source_manifest.json'
DESCRIPTOR_SHA256='a11ff1c24ce30d340d9e2bcb1592e3f58f497414ee2415813526ffc8b753900c'
SCHEMA='v5.manager_attention_replay.v1'
LANES=('screen','announcement','us','materials')


def _request(value):
    exact_keys(value,('plan_date','selection_date','announcement_publication_date','data_kind','context','lanes'))
    for key in ('plan_date','selection_date','announcement_publication_date'):trade_date(value[key])
    if value['data_kind'] not in ('SYNTHETIC','RECORDED_INPUT_REPLAY'):raise ValueError('MANAGER_DATA_KIND')
    context=value['context']
    if not isinstance(context,dict):raise ValueError('MANAGER_CONTEXT_INVALID')
    aware(context.get('research_cutoff'))
    if context.get('plan_trade_date',value['plan_date'])!=value['plan_date']:raise ValueError('MANAGER_PLAN_DATE_MISMATCH')
    if context.get('focus_window_start') is not None and aware(context['focus_window_start'])>aware(context['research_cutoff']):raise ValueError('MANAGER_FOCUS_WINDOW_INVALID')
    if not isinstance(value['lanes'],dict) or set(value['lanes'])!=set(LANES):raise ValueError('MANAGER_LANE_SET_INVALID')
    canonical_bytes(value)
    return value


def _list_field(obj,key,item_type):
    value=obj.get(key)
    if value is None:return []
    if not isinstance(value,list) or any(not isinstance(v,item_type) for v in value):raise ValueError('LANE_SHAPE_INVALID:'+key)
    return value


def _mapping_field(obj,key):
    value=obj.get(key)
    if value is not None and not isinstance(value,dict):raise ValueError('LANE_SHAPE_INVALID:'+key)
    return value or {}


def _string_field(obj,key):
    if obj.get(key) is not None and not isinstance(obj[key],str):raise ValueError('LANE_SHAPE_INVALID:'+key)


def _evidence_shape(row):
    for ref in _list_field(row,'source_refs',dict):_string_field(ref,'payload_sha256')
    for key in ('source_row','original_source_row'):
        value=_mapping_field(row,key);validity=_mapping_field(value,'business_relation_validity')
        _string_field(validity,'source_payload_sha256')
    for key in ('owner_document','owner_capture'):_mapping_field(row,key)


def _shape(name,payload):
    _string_field(payload,'status')
    if name=='announcement':_list_field(payload,'official_documents',dict)
    if name=='us':
        for row in _list_field(payload,'raw_industry_up',dict):_string_field(row,'status')
        _list_field(payload,'raw_individual_up',dict)
        for key in ('gaps','mapping_ineligible_reasons'):_list_field(payload,key,str)
        material=_mapping_field(payload,'research_material_input');_list_field(material,'gaps',str)
        _mapping_field(payload,'source_identity')
    if name=='screen':
        _mapping_field(payload,'coverage');_list_field(payload,'gaps',str)
        for key in ('strict','near','pending','excluded','screen_unresolved','cards'):
            for row in _list_field(payload,key,dict):_string_field(row,'near_failed_gate')
    if name=='materials':
        for stock in _list_field(payload,'stocks',dict):
            for evidence in _list_field(stock,'evidence',dict):_evidence_shape(evidence)
        for theme in _list_field(payload,'themes',dict):_list_field(theme,'mappings',dict)
        for card in _list_field(payload,'material_cards',dict):
            _evidence_shape(card);_string_field(card,'market')
            propositions=_list_field(card,'propositions',dict)
            if propositions and not isinstance(card.get('symbol'),str):raise ValueError('LANE_SHAPE_INVALID:proposition_symbol')
            for proposition in propositions:
                _string_field(proposition,'source_field');_string_field(proposition,'claim_status')


def _admit(name,binding,request):
    if binding is None:return None,dict(accepted=False,reason='INPUT_NOT_PROVIDED',provenance_verified=False)
    try:
        exact_keys(binding,('payload','payload_sha256','available_at','product_state','source_id'))
        sha(binding['payload_sha256'])
        if sha256_json(binding['payload'])!=binding['payload_sha256']:raise ValueError('LANE_PAYLOAD_DIGEST_MISMATCH')
        if binding['product_state']!='AVAILABLE':raise ValueError('LANE_PRODUCT_NOT_AVAILABLE')
        if not isinstance(binding['source_id'],str) or not binding['source_id'].strip():raise ValueError('LANE_SOURCE_ID_MISSING')
        if aware(binding['available_at'])>aware(request['context']['research_cutoff']):raise ValueError('LANE_AVAILABLE_AFTER_CUTOFF')
        payload=binding['payload']
        if not isinstance(payload,dict):raise ValueError('LANE_PAYLOAD_INVALID')
        for key in ('production_allowed','buy_gate_updated','orders_sent'):
            if payload.get(key,False) is not False:raise ValueError('LANE_UNSAFE_FLAGS')
        _shape(name,payload)
        if name=='screen':
            if payload.get('verified_session') is not None and trade_date(str(payload['verified_session']))>request['plan_date']:raise ValueError('SCREEN_FUTURE_SESSION')
            if str(payload.get('target_trade_date'))!=request['plan_date']:raise ValueError('SCREEN_TARGET_DATE_MISMATCH')
            if payload.get('schema_version')!='v4.manager_research.rebound_v3_screen.v1':raise ValueError('SCREEN_SCHEMA_INVALID')
            if payload.get('main_screen_ready') is not True or payload.get('status') not in ('READY','READY_WITH_GAPS'):raise ValueError('SCREEN_NOT_READY')
        if name=='materials':
            for key in ('stocks','material_cards','themes'):
                if not isinstance(payload.get(key),list) or any(not isinstance(row,dict) for row in payload[key]):raise ValueError('MATERIAL_ROWS_INVALID')
        # Attempt status is not product status: a failed refresh may retain a
        # valid prior product. Original projection applies per-evidence PIT.
        return payload,dict(accepted=True,reason='',provenance_verified=False,
            source_id=binding['source_id'],payload_sha256=binding['payload_sha256'],available_at=binding['available_at'],
            admission_basis='DECLARED_BYTES_AND_TIME_ONLY')
    except (ValueError,TypeError,KeyError) as error:
        return None,dict(accepted=False,reason=str(error),provenance_verified=False)


def _sources():
    descriptor=json.loads(no_symlinks(DESCRIPTOR).read_bytes())
    if sha256_json(descriptor)!=DESCRIPTOR_SHA256:raise ValueError('MANAGER_SOURCE_MANIFEST')
    result={}
    for e in descriptor['entries']:
        b=common._relative(CAPSULE,e['relative_path']).read_bytes()
        if len(b)!=e['bytes'] or hashlib.sha256(b).hexdigest()!=e['sha256']:raise ValueError('MANAGER_SOURCE_BYTES')
        result[e['relative_path']]=b
    return result


class _Loader(common._FrozenLoader):
    def find_spec(self,fullname,path=None,target=None):
        if (fullname=='v4' or fullname.startswith('v4.')) and fullname not in self.sources and fullname not in self.packages:
            raise ImportError('MANAGER_SOURCE_CLOSURE_INCOMPLETE:'+fullname)
        return super().find_spec(fullname,path,target)
    def exec_module(self,module):
        if module.__name__ in self.packages:module.__path__=[]
        item=self.sources.get(module.__name__)
        if item:
            name,data,_=item;module.__file__=str(CAPSULE/name)
            exec(compile(data,module.__file__,'exec'),module.__dict__)


def _identity():
    return {n:hashlib.sha256(no_symlinks(Path(__file__).parent/n).read_bytes()).hexdigest()
            for n in ('manager_attention.py','a_preselection.py','contracts.py','composition.py','digests.py','provider_evidence.py','__init__.py')}


def _assemble(value):
    request=_request(value);before=sha256_json(request)
    if 'v4' in sys.modules:raise ValueError('MANAGER_FRESH_PROCESS_REQUIRED')
    sys.meta_path.insert(0,_Loader(_sources()))
    module=importlib.import_module('v4.manager_research.research_attention')
    common._guard([])
    payloads={};diagnostics={}
    for name in LANES:payloads[name],diagnostics[name]=_admit(name,request['lanes'][name],request)
    materials=payloads['materials'] or {}
    if payloads['us'] is not None:
        effective_us=deepcopy(payloads['us'])
        material_identity=deepcopy(effective_us.get('research_material_input') or {})
        # Complete-source authority is not established by this replay wrapper.
        material_identity.update(complete=False,status='UNVERIFIED',
            gaps=list(dict.fromkeys([*(material_identity.get('gaps') or []),'MATERIAL_INPUT_COMPLETENESS_UNVERIFIED'])))
        effective_us['research_material_input']=material_identity
        payloads['us']=effective_us
        diagnostics['us']['material_completeness_override']='NOT_OWNER_VERIFIED'

    original=module.build_research_attention(request['plan_date'],context=request['context'],
        market_screen=payloads['screen'],stocks=materials.get('stocks'),material_cards=materials.get('material_cards'),
        themes=materials.get('themes'),announcement_observation=payloads['announcement'],us_market=payloads['us'])
    canonical_bytes(original)
    if original.get('target_trade_date')!=request['plan_date']:raise ValueError('MANAGER_OUTPUT_DATE_MISMATCH')
    artifact=dict(original,legacy_status=original['status'],status='CANNOT_CONFIRM',
                  input_provenance_verified=False,authority_binding_status='NOT_CONNECTED',
                  data_kind=request['data_kind'],coverage_basis='ADMITTED_DECLARED_INPUTS_ONLY',
                  gaps=sorted(set([*original.get('gaps',[]),'INPUT_PROVENANCE_NOT_VERIFIED',
                                   *(name+':'+v['reason'] for name,v in diagnostics.items() if not v['accepted'])])))
    if sha256_json(request)!=before:raise ValueError('MANAGER_INPUT_MUTATED')
    _sources()
    return dict(schema_version=SCHEMA,status='REPLAY_COMPLETED',artifact=artifact,lanes=diagnostics,
        plan_date=request['plan_date'],selection_date=request['selection_date'],announcement_publication_date=request['announcement_publication_date'],
        request_sha256=before,source_capsule_sha256=DESCRIPTOR_SHA256,implementation_identity=_identity(),
        input_provenance_verified=False,isolation_status='PYTHON_GUARDS_ONLY_OS_UNVERIFIED',
        finished_at=datetime.now(timezone.utc).isoformat(),**common.SAFETY)


def run_manager_attention(request):
    request=_request(request);identity=_identity()
    with tempfile.TemporaryDirectory(prefix='v5-manager-cache-') as cache:
        process=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),str(Path(__file__).resolve())],
            input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if len(process.stdout)>MAX_JSON_BYTES:raise ValueError('MANAGER_OUTPUT_TOO_LARGE')
    try:out=json.loads(process.stdout)
    except (ValueError,UnicodeError) as error:raise ValueError('MANAGER_RESPONSE_INVALID:'+process.stderr.decode(errors='replace')[-1500:]) from error
    if process.returncode:raise ValueError(out.get('reason','MANAGER_WORKER_FAILED'))
    if (out.get('schema_version')!=SCHEMA or out.get('request_sha256')!=sha256_json(request)
        or out.get('source_capsule_sha256')!=DESCRIPTOR_SHA256 or out.get('implementation_identity')!=identity or _identity()!=identity
        or out.get('input_provenance_verified') is not False or any(out.get(k)!=v for k,v in common.SAFETY.items())):raise ValueError('MANAGER_WORKER_IDENTITY')
    return out


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('MANAGER_REQUEST_TOO_LARGE')
        print(canonical_bytes(_assemble(json.loads(raw))).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED',reason=type(error).__name__+':'+str(error))).decode())
        raise SystemExit(1)
