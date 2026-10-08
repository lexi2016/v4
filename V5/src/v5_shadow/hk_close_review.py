"""Frozen HK close Top20 review, with explicit replay/input boundaries."""
import sys
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib
import importlib
import json
import math
import re
import subprocess
import tempfile
from datetime import datetime,timezone,timedelta
from v5_shadow import a_preselection as common
from v5_shadow.contracts import aware,trade_date,exact_keys,sha
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
from v5_shadow.composition import no_symlinks

BASE=Path(__file__).resolve().parents[2]
CAPSULE=BASE/'vendor/hk_close_baseline'
DESCRIPTOR=BASE/'contracts/hk_close_source_manifest.json'
DESCRIPTOR_SHA256='4aa21e29c2e439aa8a893dd06d0a8243f797a51d5048244b0e41e82e45f2125e'
SCHEMA='v5.hk_close_replay.v1'
STAGES=('STAGE_0925','STAGE_0930_0935','STAGE_0935_0940','STAGE_0940_0945','STAGE_0945_1030','STAGE_1300_1315','STAGE_1445_1500')
TZ=timezone(timedelta(hours=8))


def _code(value):
    if not isinstance(value,str) or not re.fullmatch(r'HK\.[0-9]{5}',value):raise ValueError('HK_CLOSE_ROW_IDENTITY')
    return value


def _request(value):
    exact_keys(value,('target_date','data_kind','captured_at','available_at','research_cutoff','inputs','inputs_sha256'))
    target=trade_date(value['target_date']);sha(value['inputs_sha256'])
    if value['data_kind'] not in ('SYNTHETIC','RECORDED_INPUT_REPLAY'):raise ValueError('HK_CLOSE_DATA_KIND')
    capture,available,cutoff=(aware(value[k]) for k in ('captured_at','available_at','research_cutoff'))
    if capture.astimezone(TZ).strftime('%Y%m%d')!=target or not capture<=available<=cutoff:raise ValueError('HK_CLOSE_CLOCK_INVALID')
    inputs=value['inputs'];exact_keys(inputs,('close_rows','model_rows','stage_rows','universe_codes'))
    if sha256_json(inputs)!=value['inputs_sha256']:raise ValueError('HK_CLOSE_INPUT_DIGEST')
    codes=inputs['universe_codes'];rows=inputs['close_rows'];model=inputs['model_rows'];stages=inputs['stage_rows']
    if not isinstance(codes,list) or not 600<=len(codes)<=10000 or len({_code(c) for c in codes})!=len(codes):raise ValueError('HK_CLOSE_UNIVERSE_INCOMPLETE')
    if not isinstance(rows,list) or len(rows)!=len(codes) or any(not isinstance(r,dict) for r in rows):raise ValueError('HK_CLOSE_UNIVERSE_INCOMPLETE')
    seen=set()
    for row in rows:
        code=_code(row.get('code'))
        if code in seen or code not in codes:raise ValueError('HK_CLOSE_UNIVERSE_INCOMPLETE')
        seen.add(code)
        if row.get('trade_date')!=target:raise ValueError('HK_CLOSE_ROW_IDENTITY')
        for field in ('close','pre_close','amount'):
            number=row.get(field)
            if type(number) not in (int,float) or not math.isfinite(number) or (number<=0 if field!='amount' else number<0):raise ValueError('HK_CLOSE_PRICE_INVALID')
    if not isinstance(model,list) or len(model)>100:raise ValueError('HK_CLOSE_MODEL_INVALID')
    seen_model=set()
    for rank,row in enumerate(model,1):
        if not isinstance(row,dict):raise ValueError('HK_CLOSE_MODEL_INVALID')
        code=_code(row.get('symbol'))
        if code in seen_model or code not in seen or row.get('target_date')!=target or row.get('market')!='HK' or row.get('pool_rank')!=rank:raise ValueError('HK_CLOSE_ROW_IDENTITY')
        seen_model.add(code)
    if not isinstance(stages,dict) or set(stages)!=set(STAGES):raise ValueError('HK_CLOSE_STAGE_SET_INVALID')
    for stage,sources in stages.items():
        if sources is None:continue
        if not isinstance(sources,list) or len(sources)>10:raise ValueError('HK_CLOSE_STAGE_ROWS_INVALID')
        unique=set()
        for row in sources:
            if not isinstance(row,dict):raise ValueError('HK_CLOSE_ROW_IDENTITY')
            code=_code(row.get('code'))
            if code in unique or code not in seen or row.get('trade_date')!=target or row.get('stage_id')!=stage or row.get('market')!='HK':raise ValueError('HK_CLOSE_ROW_IDENTITY')
            unique.add(code)
    canonical_bytes(value)
    return value


def _sources():
    value=json.loads(no_symlinks(DESCRIPTOR).read_bytes())
    if sha256_json(value)!=DESCRIPTOR_SHA256:raise ValueError('HK_CLOSE_SOURCE_MANIFEST')
    sources={}
    for entry in value['entries']:
        data=common._relative(CAPSULE,entry['relative_path']).read_bytes()
        if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('HK_CLOSE_SOURCE_BYTES')
        sources[entry['relative_path']]=data
    return sources


class _Loader(common._FrozenLoader):
    def exec_module(self,module):
        if module.__name__ in self.packages:module.__path__=[]
        item=self.sources.get(module.__name__)
        if item:
            name,data,_=item;module.__file__=str(CAPSULE/name)
            exec(compile(data,module.__file__,'exec'),module.__dict__)


def _identity():
    return {n:hashlib.sha256(no_symlinks(Path(__file__).parent/n).read_bytes()).hexdigest()
            for n in ('hk_close_review.py','a_preselection.py','contracts.py','composition.py','digests.py')}


def _assemble(value):
    request=_request(value)
    if any(n in sys.modules for n in ('domains','contracts','infrastructure')):raise ValueError('HK_CLOSE_FRESH_PROCESS_REQUIRED')
    sys.meta_path.insert(0,_Loader(_sources()))
    calendars=importlib.import_module('contracts.trading_calendar')
    states=calendars.resolve_market_states(calendars.load_market_calendar(),request['target_date'])
    state=states['hk_securities'].value
    if state not in ('FULL_TRADING_DAY','HALF_TRADING_DAY_AM'):raise ValueError('HK_CLOSE_MARKET_NOT_OPEN')
    if state=='HALF_TRADING_DAY_AM' and any(request['inputs']['stage_rows'][k] for k in ('STAGE_1300_1315','STAGE_1445_1500')):raise ValueError('HK_CLOSE_AFTER_HALF_DAY_STAGE')
    date=request['target_date'];final='12:10:00' if state=='HALF_TRADING_DAY_AM' else '16:10:00'
    boundary=aware(f'{date[:4]}-{date[4:6]}-{date[6:]}T{final}+08:00')
    if aware(request['captured_at'])<boundary:raise ValueError('HK_CLOSE_BEFORE_FINAL_CUTOFF')
    module=importlib.import_module('domains.close_review')
    common._guard([])
    inputs=request['inputs']
    original=module.build_native_close_review(date,close_rows=inputs['close_rows'],model_rows=inputs['model_rows'],
                stage_rows=inputs['stage_rows'],close_source_sha256=sha256_json(inputs['close_rows']))
    canonical_bytes(original)
    if original.get('trade_date')!=date or original.get('row_counts',{}).get('hkconnect_universe')!=len(inputs['close_rows']):raise ValueError('HK_CLOSE_OUTPUT_IDENTITY')
    if any(original.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):raise ValueError('HK_CLOSE_OUTPUT_SAFETY')
    # Preserve original metrics but never label a replay as native production.
    artifact=dict(original,legacy_status=original['status'],status='CANNOT_CONFIRM',
                  cannot_confirm=list(dict.fromkeys([*original['cannot_confirm'],'INPUT_PROVENANCE_NOT_VERIFIED'])),schema_version='v5.hk_close_projection.v1',legacy_schema_version=original['schema_version'],
                  legacy_evidence_mode=original.get('evidence_mode'),evidence_mode='V5_'+request['data_kind'],
                  input_provenance_verified=False,metrics_basis='DECLARED_UNIVERSE_ONLY',reference_snapshot=True)
    artifact['input_evidence']=dict(scope='DECLARED_ROWS_ONLY',source_provenance_verified=False,
        authoritative_inputs_bound=False,
        close=dict(declared_row_count=len(inputs['close_rows']),declared_universe_count=len(inputs['universe_codes']),
                   declared_rows_sha256=sha256_json(inputs['close_rows']),declared_universe_sha256=sha256_json(inputs['universe_codes']),timestamp_basis='REQUEST_DECLARED'),
        model=dict(declared_row_count=len(inputs['model_rows']),source_envelope_status='NOT_PROVIDED',source_role_verified=False,pit_availability_verified=False),
        stages={k:dict(input_state='MISSING' if v is None else 'DECLARED_ROWS' if v else 'DECLARED_EMPTY',
                       declared_row_count=None if v is None else len(v),source_envelope_status='NOT_PROVIDED') for k,v in inputs['stage_rows'].items()})
    artifact['cannot_confirm'].append('PIT_AVAILABILITY_NOT_VERIFIED')
    model_known=len(inputs['model_rows'])==100
    stages_known=all(rows is not None for rows in inputs['stage_rows'].values())
    artifact['attribution_evidence']=dict(model='DECLARED_COMPLETE' if model_known else 'MISSING',
                                         stages='DECLARED_COMPLETE' if stages_known else 'MISSING')
    artifact['top20_attribution']=[dict(row,legacy_classification=row['classification'],
        classification=row['classification'] if model_known and stages_known else 'CANNOT_CONFIRM',
        model_0_2_hit=row['model_0_2_hit'] if model_known else None,
        stage_union_hit=row['stage_union_hit'] if stages_known else None)
        for row in original['top20_attribution']]
    if sha256_json(inputs)!=request['inputs_sha256']:raise ValueError('HK_CLOSE_INPUT_MUTATED')
    _sources()
    return dict(schema_version=SCHEMA,status='REPLAY_COMPLETED',artifact=artifact,request_sha256=sha256_json(request),
                source_capsule_sha256=DESCRIPTOR_SHA256,implementation_identity=_identity(),input_provenance_verified=False,
                market_states={k:v.value for k,v in states.items()},isolation_status='PYTHON_GUARDS_ONLY_OS_UNVERIFIED',
                finished_at=datetime.now(timezone.utc).isoformat(),**common.SAFETY)


def run_hk_close_review(request):
    request=_request(request);identity=_identity()
    with tempfile.TemporaryDirectory(prefix='v5-hk-close-cache-') as cache:
        process=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),str(Path(__file__).resolve())],
            input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if len(process.stdout)>MAX_JSON_BYTES:raise ValueError('HK_CLOSE_OUTPUT_TOO_LARGE')
    try:out=json.loads(process.stdout)
    except (ValueError,UnicodeError) as error:raise ValueError('HK_CLOSE_RESPONSE_INVALID:'+process.stderr.decode(errors='replace')[-1500:]) from error
    if process.returncode:raise ValueError(out.get('reason','HK_CLOSE_WORKER_FAILED'))
    if (out.get('schema_version')!=SCHEMA or out.get('request_sha256')!=sha256_json(request)
        or out.get('source_capsule_sha256')!=DESCRIPTOR_SHA256 or out.get('implementation_identity')!=identity or _identity()!=identity
        or out.get('input_provenance_verified') is not False or any(out.get(k)!=v for k,v in common.SAFETY.items())):raise ValueError('HK_CLOSE_WORKER_IDENTITY')
    return out


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('HK_CLOSE_REQUEST_TOO_LARGE')
        print(canonical_bytes(_assemble(json.loads(raw))).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED',reason=type(error).__name__+':'+str(error))).decode())
        raise SystemExit(1)
