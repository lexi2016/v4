"""Fixed-source A close model on complete declared same-date panel rows."""
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
CAPSULE=BASE/'vendor/a_close_baseline'
DESCRIPTOR=BASE/'contracts/a_close_source_manifest.json'
DESCRIPTOR_SHA256='614ce63ea186f8c4eb38990f3b4a5f747845b1f551dc3abc0e9b9d4d386434b7'
SCHEMA='v5.a_close_replay.v1'
TZ=timezone(timedelta(hours=8))


def _request(value):
    exact_keys(value,('target_date','data_kind','captured_at','available_at','research_cutoff','rows','rows_sha256','universe_codes'))
    target=trade_date(value['target_date']);sha(value['rows_sha256'])
    if value['data_kind'] not in ('SYNTHETIC','RECORDED_INPUT_REPLAY'):raise ValueError('A_CLOSE_DATA_KIND')
    capture,available,cutoff=(aware(value[k]) for k in ('captured_at','available_at','research_cutoff'))
    if capture.astimezone(TZ).strftime('%Y%m%d')!=target or not capture<=available<=cutoff:raise ValueError('A_CLOSE_CLOCK_INVALID')
    if capture.astimezone(TZ).strftime('%H:%M:%S')<'15:30:00':raise ValueError('A_CLOSE_BEFORE_POST_CLOSE')
    rows=value['rows'];codes=value['universe_codes']
    if not isinstance(rows,list) or not 1<=len(rows)<=20000 or not isinstance(codes,list) or len(codes)!=len(rows):raise ValueError('A_CLOSE_UNIVERSE_MISMATCH')
    if sha256_json(rows)!=value['rows_sha256']:raise ValueError('A_CLOSE_INPUT_DIGEST')
    if any(not isinstance(c,str) or not re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)',c) for c in codes) or len(set(codes))!=len(codes):raise ValueError('A_CLOSE_UNIVERSE_MISMATCH')
    required={'trade_date','ts_code','name','pct_chg','amount','bar_close_pos','tdx_industry_code','tdx_industry_name'};seen=set()
    for row in rows:
        if not isinstance(row,dict) or not required<=set(row):raise ValueError('A_CLOSE_FIELDS_MISSING')
        if row['trade_date']!=target:raise ValueError('A_CLOSE_ROW_DATE')
        if row['ts_code'] not in codes or row['ts_code'] in seen:raise ValueError('A_CLOSE_UNIVERSE_MISMATCH')
        seen.add(row['ts_code'])
        for k in ('pct_chg','amount','bar_close_pos'):
            if type(row[k]) not in (int,float) or not math.isfinite(row[k]):raise ValueError('A_CLOSE_NUMBER_INVALID')
        if row['amount']<0 or not 0<=row['bar_close_pos']<=1:raise ValueError('A_CLOSE_NUMBER_INVALID')
        for k in ('name','tdx_industry_code','tdx_industry_name'):
            if not isinstance(row[k],str) or not row[k].strip():raise ValueError('A_CLOSE_FIELDS_MISSING')
    canonical_bytes(value)
    return value


def _sources():
    descriptor=json.loads(no_symlinks(DESCRIPTOR).read_bytes())
    if sha256_json(descriptor)!=DESCRIPTOR_SHA256:raise ValueError('A_CLOSE_SOURCE_MANIFEST')
    result={}
    for e in descriptor['entries']:
        b=common._relative(CAPSULE,e['relative_path']).read_bytes()
        if len(b)!=e['bytes'] or hashlib.sha256(b).hexdigest()!=e['sha256']:raise ValueError('A_CLOSE_SOURCE_BYTES')
        result[e['relative_path']]=b
    return result


class _Loader(common._FrozenLoader):
    def exec_module(self,module):
        if module.__name__ in self.packages:module.__path__=[]
        item=self.sources.get(module.__name__)
        if item:
            name,data,_=item;module.__file__=str(CAPSULE/name)
            exec(compile(data,module.__file__,'exec'),module.__dict__)


def _identity():
    return {n:hashlib.sha256(no_symlinks(Path(__file__).parent/n).read_bytes()).hexdigest()
            for n in ('a_close_review.py','a_preselection.py','contracts.py','composition.py','digests.py')}


def _assemble(value):
    request=_request(value)
    if any(n in sys.modules for n in ('domains','contracts')):raise ValueError('A_CLOSE_FRESH_PROCESS_REQUIRED')
    sys.meta_path.insert(0,_Loader(_sources()))
    calendars=importlib.import_module('contracts.trading_calendar')
    states=calendars.resolve_market_states(calendars.load_market_calendar(),request['target_date'])
    if states['a_share'].value!='FULL_TRADING_DAY':raise ValueError('A_CLOSE_MARKET_NOT_OPEN')
    module=importlib.import_module('domains.a_share_close_model')
    import pandas as pd
    common._guard([])
    run_id='v5-a-close-'+sha256_json(request)[:24]
    original=module.build_close_model(pd.DataFrame(request['rows']),request['target_date'],run_id)
    canonical_bytes(original)
    summary=original.get('market_summary',{})
    if original.get('review_date')!=request['target_date'] or original.get('run_id')!=run_id or sum(summary.get(k,0) for k in ('up_count','down_count','flat_count'))!=len(request['rows']):raise ValueError('A_CLOSE_OUTPUT_IDENTITY')
    if original.get('safety')!=module.SAFETY or original.get('semantic_model_call_count')!=0:raise ValueError('A_CLOSE_OUTPUT_SAFETY')
    artifact=dict(original,legacy_status=original['status'],status='CANNOT_CONFIRM',
        input_provenance_verified=False,scope='DECLARED_UNIVERSE_ONLY',data_kind=request['data_kind'],
        source_available_at=request['available_at'],captured_at=request['captured_at'],research_cutoff=request['research_cutoff'],
        legacy_as_of=original['as_of'],as_of=request['captured_at'],as_of_semantics='REQUEST_DECLARED_CAPTURE_NOT_INDEPENDENTLY_VERIFIED',strict_1500_pit_verified=False,
        scenario_probabilities_status='FROZEN_LEGACY_CONSTANTS_NOT_CALIBRATED',
        cannot_confirm=['INPUT_PROVENANCE_NOT_VERIFIED','FULL_MARKET_MEMBERSHIP_NOT_VERIFIED','STRICT_1500_PIT_NOT_VERIFIED'])
    if sha256_json(request['rows'])!=request['rows_sha256']:raise ValueError('A_CLOSE_INPUT_MUTATED')
    _sources()
    return dict(schema_version=SCHEMA,status='REPLAY_COMPLETED',artifact=artifact,request_sha256=sha256_json(request),
        source_capsule_sha256=DESCRIPTOR_SHA256,implementation_identity=_identity(),input_provenance_verified=False,
        market_states={k:v.value for k,v in states.items()},isolation_status='PYTHON_GUARDS_ONLY_OS_UNVERIFIED',
        finished_at=datetime.now(timezone.utc).isoformat(),**common.SAFETY)


def run_a_close_review(request):
    request=_request(request);identity=_identity()
    with tempfile.TemporaryDirectory(prefix='v5-a-close-cache-') as cache:
        process=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),str(Path(__file__).resolve())],
            input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if len(process.stdout)>MAX_JSON_BYTES:raise ValueError('A_CLOSE_OUTPUT_TOO_LARGE')
    try:out=json.loads(process.stdout)
    except (ValueError,UnicodeError) as error:raise ValueError('A_CLOSE_RESPONSE_INVALID:'+process.stderr.decode(errors='replace')[-1500:]) from error
    if process.returncode:raise ValueError(out.get('reason','A_CLOSE_WORKER_FAILED'))
    if (out.get('schema_version')!=SCHEMA or out.get('request_sha256')!=sha256_json(request)
        or out.get('source_capsule_sha256')!=DESCRIPTOR_SHA256 or out.get('implementation_identity')!=identity or _identity()!=identity
        or out.get('input_provenance_verified') is not False or any(out.get(k)!=v for k,v in common.SAFETY.items())):raise ValueError('A_CLOSE_WORKER_IDENTITY')
    return out


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('A_CLOSE_REQUEST_TOO_LARGE')
        print(canonical_bytes(_assemble(json.loads(raw))).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED',reason=type(error).__name__+':'+str(error))).decode())
        raise SystemExit(1)
