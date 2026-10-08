"""Fixed-source A/H non-auction selection on declared recorded input only."""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hashlib
import importlib
import json
import math
import re
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from v5_shadow import a_preselection as common
from v5_shadow.contracts import aware, trade_date, exact_keys, sha
from v5_shadow.digests import canonical_bytes, sha256_json, MAX_JSON_BYTES
from v5_shadow.composition import no_symlinks

BASE=Path(__file__).resolve().parents[2]
CAPSULE=BASE/'vendor/stage_selection_baseline'
DESCRIPTOR=BASE/'contracts/stage_selection_source_manifest.json'
DESCRIPTOR_SHA256='f5108ab0d7dcb7d764f2131c9c58d353de8d6d4a565b390763d1eb584ab11c08'
SCHEMA='v5.stage_selection_replay.v1'
TZ=timezone(timedelta(hours=8))


def _request(value):
    exact_keys(value,('market','target_date','stage_id','data_kind','rows','rows_sha256',
                     'source_status','requested_rows','missing_symbols','cannot_confirm'))
    trade_date(value['target_date']);sha(value['rows_sha256'])
    if value['market'] not in ('A_SHARE','HK_CONNECT'):raise ValueError('STAGE_MARKET_INVALID')
    if value['data_kind'] not in ('SYNTHETIC','RECORDED_INPUT_REPLAY'):raise ValueError('STAGE_DATA_KIND_INVALID')
    if value['stage_id'] in ('STAGE_0925','STAGE_1545_1555'):raise ValueError('STAGE_REQUIRES_SEPARATE_ORIGINAL_ROUTE')
    if value['source_status'] not in ('READY','READY_EMPTY','PARTIAL_WITH_ROWS','CANNOT_CONFIRM'):
        raise ValueError('STAGE_SOURCE_STATUS_INVALID')
    if not isinstance(value['rows'],list) or len(value['rows'])>10000 or any(not isinstance(r,dict) for r in value['rows']):
        raise ValueError('STAGE_ROWS_INVALID')
    if type(value['requested_rows']) is not int or value['requested_rows']<len(value['rows']):raise ValueError('STAGE_COVERAGE_INVALID')
    for key in ('missing_symbols','cannot_confirm'):
        if not isinstance(value[key],list) or any(not isinstance(s,str) for s in value[key]):raise ValueError('STAGE_DIAGNOSTICS_INVALID')
    if value['missing_symbols'] and value['source_status'] in ('READY','READY_EMPTY'):raise ValueError('STAGE_MISSING_SYMBOL_STATUS_CONTRADICTION')
    if value['source_status']=='READY_EMPTY' and value['rows']:raise ValueError('STAGE_EMPTY_CONTRADICTION')
    if sha256_json(value['rows'])!=value['rows_sha256']:raise ValueError('STAGE_INPUT_BYTES_MISMATCH')
    canonical_bytes(value)
    return value


def _identity():
    return {name:hashlib.sha256(no_symlinks(Path(__file__).parent/name).read_bytes()).hexdigest()
            for name in ('stage_selection.py','a_preselection.py','contracts.py','composition.py','digests.py')}


def _sources():
    descriptor=json.loads(no_symlinks(DESCRIPTOR).read_bytes())
    if sha256_json(descriptor)!=DESCRIPTOR_SHA256:raise ValueError('STAGE_SOURCE_MANIFEST_MISMATCH')
    result={}
    for entry in descriptor['entries']:
        data=common._relative(CAPSULE,entry['relative_path']).read_bytes()
        if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('STAGE_SOURCE_BYTES_MISMATCH')
        result[entry['relative_path']]=data
    return result


class _Loader(common._FrozenLoader):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith('stage_center') and fullname not in self.sources and fullname not in self.packages:
            raise ImportError('STAGE_SOURCE_CLOSURE_INCOMPLETE:'+fullname)
        return super().find_spec(fullname,path,target)
    def exec_module(self,module):
        if module.__name__ in self.packages:module.__path__=[]
        item=self.sources.get(module.__name__)
        if item:
            relative,data,_=item;module.__file__=str(CAPSULE/relative)
            exec(compile(data,module.__file__,'exec'),module.__dict__)


def _number(value,positive=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or (positive and value<=0):
        raise ValueError('STAGE_REQUIRED_QUOTE_INVALID')


def _validate_rows(request,spec):
    date=request['target_date'];iso=f'{date[:4]}-{date[4:6]}-{date[6:]}'
    cutoff=aware(iso+'T'+spec.cutoff+'+08:00')
    window=spec.hk_window if request['market']=='HK_CONNECT' and spec.hk_window else spec.window
    start=aware(iso+'T'+window.split('-')[0]+':00+08:00')
    seen=set()
    for row in request['rows']:
        if row.get('trade_date')!=date or row.get('stage_id')!=request['stage_id']:raise ValueError('STAGE_ROW_IDENTITY_MISMATCH')
        code=row.get('code')
        if (not isinstance(code,str) or code!=code.strip() or not re.fullmatch(r'[0-9]{6}' if request['market']=='A_SHARE' else r'HK\.[0-9]{5}',code) or code in seen):raise ValueError('STAGE_CODE_INVALID_OR_DUPLICATE')
        seen.add(code)
        captured=aware(row.get('captured_at'))
        if not start<=captured<=cutoff:raise ValueError('STAGE_ROW_OUTSIDE_WINDOW')
        for field in ('update_time','source_last_bar_time','source_last_tick_time'):
            if field in row:
                observed=aware(row[field])
                if observed.astimezone(TZ).strftime('%Y%m%d')!=date or observed>captured:raise ValueError('STAGE_SOURCE_TIME_INVALID')
        if request['market']=='A_SHARE':
            qmt=row.get('qmt');candidate=row.get('candidate')
            if not isinstance(qmt,dict) or not isinstance(candidate,dict):raise ValueError('STAGE_A_QUOTE_REQUIRED')
            for field in ('open','lastPrice','lastClose','high','low'):_number(qmt.get(field),True)
            _number(qmt.get('amount'))
            if 'score' not in candidate or candidate['score'] is not None:raise ValueError('STAGE_FORMAL_SCORE_AUTHORITY_NOT_CONNECTED')
            if row.get('formal_eligible') is not False:raise ValueError('STAGE_FORMAL_AUTHORITY_NOT_CONNECTED')
            for field in ('news_quality_score','research_quality_score'):_number(row.get(field))
            for field in ('bidVol','askVol'):
                v=qmt.get(field)
                if not isinstance(v,list) or not v:raise ValueError('STAGE_ORDERBOOK_REQUIRED')
                for n in v:
                    _number(n)
                    if n<0:raise ValueError('STAGE_ORDERBOOK_NEGATIVE')
            if qmt['amount']<0 or qmt['low']>min(qmt['open'],qmt['lastPrice']) or qmt['high']<max(qmt['open'],qmt['lastPrice']):raise ValueError('STAGE_QUOTE_INCONSISTENT')
        else:
            if 'stage_score' in row:raise ValueError('STAGE_HK_SCORE_OVERRIDE_NOT_SUPPORTED')
            for field in ('open_price','last_price','high_price','low_price'):_number(row.get(field),True)
            for field in ('pct_chg','volume_ratio','circular_market_cap_hkd_yi','turnover_hkd'):_number(row.get(field))
            for field in ('platform_circular_market_cap_hkd_yi','turnover_hkd_yi','turnover_rate','futu_turnover_rate','offer_float_market_cap_hkd_yi','stage_window_change_pct','window_change_pct','stage_score','score'):
                if field in row:_number(row[field])
            for field in ('platform_circular_market_cap_hkd_yi','turnover_hkd_yi','turnover_rate','futu_turnover_rate','offer_float_market_cap_hkd_yi'):
                if field in row and row[field]<0:raise ValueError('STAGE_HK_QUOTE_NEGATIVE')
            if any(row[k]<0 for k in ('volume_ratio','circular_market_cap_hkd_yi','turnover_hkd')):raise ValueError('STAGE_HK_QUOTE_NEGATIVE')
            if row['low_price']>min(row['open_price'],row['last_price']) or row['high_price']<max(row['open_price'],row['last_price']):raise ValueError('STAGE_QUOTE_INCONSISTENT')
            if not isinstance(row.get('candidate_lanes'),list) or any(not isinstance(v,str) for v in row['candidate_lanes']):raise ValueError('STAGE_HK_LANES_INVALID')


def _assemble(value):
    request=_request(value)
    if any(n in sys.modules for n in ('stage_center','infrastructure')):raise ValueError('STAGE_FRESH_PROCESS_REQUIRED')
    sys.meta_path.insert(0,_Loader(_sources()))
    module=importlib.import_module('stage_center.selection')
    contracts=importlib.import_module('stage_center.contracts')
    calendar=importlib.import_module('stage_center.calendar')
    spec=contracts.STAGE_BY_ID.get(request['stage_id'])
    if spec is None or request['market'] not in spec.markets:raise ValueError('STAGE_NOT_SUPPORTED_FOR_MARKET')
    states=calendar.resolve_market_states(request['target_date']);key='a_share' if request['market']=='A_SHARE' else 'hk_securities'
    if states[key].value not in ('FULL_TRADING_DAY','HALF_TRADING_DAY_AM'):raise ValueError('STAGE_MARKET_NOT_OPEN')
    if states[key].value=='HALF_TRADING_DAY_AM' and spec.cutoff>'12:00:00':raise ValueError('STAGE_AFTER_HALF_DAY_CLOSE')
    _validate_rows(request,spec)
    common._guard([])
    selector=module.select_a_live_stage if request['market']=='A_SHARE' else module.select_hk_four_lane
    artifact=selector(request['rows'],request['target_date'],request['stage_id'],request['rows_sha256'],
                      source_status=request['source_status'],requested_rows=request['requested_rows'],
                      missing_symbols=request['missing_symbols'],cannot_confirm=request['cannot_confirm'],
                      source_evidence=('selection_contract=V3_TOP10_RECOMMENDATION',))
    canonical_bytes(artifact)
    expected_algorithm=module.A_SHARE_LIVE_ALGORITHM_SHA256 if request['market']=='A_SHARE' else module.ALGORITHM_SHA256
    if artifact.get('algorithm_sha256')!=expected_algorithm:raise ValueError('STAGE_ALGORITHM_CONTRACT_MISMATCH')
    if (artifact.get('source_rows')!=len(request['rows']) or len(artifact.get('rows',[]))>10
        or artifact.get('market')!=request['market'] or artifact.get('trade_date')!=request['target_date']
        or artifact.get('stage_id')!=request['stage_id']
        or any(artifact.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))):raise ValueError('STAGE_OUTPUT_CONTRACT_INVALID')
    if sha256_json(request['rows'])!=request['rows_sha256']:raise ValueError('STAGE_INPUT_MUTATED')
    _sources()
    return dict(schema_version=SCHEMA,status='ASSEMBLED',artifact=artifact,request_sha256=sha256_json(request),
                source_capsule_sha256=DESCRIPTOR_SHA256,implementation_identity=_identity(),
                expected_algorithm_sha256=expected_algorithm,market_states={k:v.value for k,v in states.items()},input_binding_status='DECLARED_ROWS_HASH_CHECKED',
                input_provenance_verified=False,isolation_status='PYTHON_GUARDS_ONLY_OS_UNVERIFIED',
                finished_at=datetime.now(timezone.utc).isoformat(),**common.SAFETY)


def run_stage_selection(request):
    request=_request(request);identity=_identity()
    with tempfile.TemporaryDirectory(prefix='v5-stage-cache-') as cache:
        result=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),str(Path(__file__).resolve())],
                              input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if len(result.stdout)>MAX_JSON_BYTES:raise ValueError('STAGE_RESPONSE_TOO_LARGE')
    try:out=json.loads(result.stdout)
    except (ValueError,UnicodeError) as error:raise ValueError('STAGE_RESPONSE_INVALID:'+result.stderr.decode(errors='replace')[-1500:]) from error
    if result.returncode:raise ValueError(out.get('reason','STAGE_WORKER_FAILED'))
    if (out.get('schema_version')!=SCHEMA or out.get('request_sha256')!=sha256_json(request)
        or out.get('implementation_identity')!=identity or _identity()!=identity
        or out.get('source_capsule_sha256')!=DESCRIPTOR_SHA256 or out.get('input_provenance_verified') is not False
        or any(out.get(k)!=v for k,v in common.SAFETY.items())):raise ValueError('STAGE_WORKER_IDENTITY_MISMATCH')
    return out


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('STAGE_REQUEST_TOO_LARGE')
        print(canonical_bytes(_assemble(json.loads(raw))).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED',reason=type(error).__name__+':'+str(error))).decode())
        raise SystemExit(1)
