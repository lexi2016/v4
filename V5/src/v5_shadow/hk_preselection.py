"""Pinned HK Top100 read/projection; three explicit dates, no acquisition."""
import sys
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib
import importlib
import io
import json
import math
import subprocess
import tempfile
from contextlib import redirect_stdout
from datetime import datetime,timezone,timedelta
from v5_shadow import a_preselection as common
from v5_shadow.contracts import aware,sha,trade_date
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
from v5_shadow.composition import no_symlinks

BASE=Path(__file__).resolve().parents[2]
CAPSULE=BASE/'vendor/hk_preselection_baseline'
DESCRIPTOR=BASE/'contracts/hk_preselection_source_manifest.json'
DESCRIPTOR_SHA256='11c3af79592e15a5b9aa400fee57f14c415ef06ea3e2a8a25ba6a43f074d73cb'
SCHEMA='v5.hk_preselection_assembly.v1'
ROLE='HK_CONNECT_D1_TOP100_0_2'
SAFETY=common.SAFETY


def _identity():
    return {name:hashlib.sha256(no_symlinks(Path(__file__).parent/name).read_bytes()).hexdigest()
            for name in ('hk_preselection.py','a_preselection.py','composition.py','contracts.py','digests.py')}


def _request(request):
    required={'target_date','signal_date','eligibility_source_date','research_cutoff','data_kind','input_root','files'}
    optional={'eligibility_universe_root','research_name_supplement'}
    if not isinstance(request,dict) or not required<=set(request) or set(request)-required-optional:
        raise ValueError('HK_REQUEST_FIELDS_INVALID')
    if request.get('eligibility_universe_root') is not None or request.get('research_name_supplement',False) is not False:
        raise ValueError('UNSUPPORTED_LEGACY_READER_ARGUMENT')
    target=trade_date(request['target_date']);signal=trade_date(request['signal_date']);eligibility=trade_date(request['eligibility_source_date'])
    if not signal<target or eligibility>target:raise ValueError('HK_THREE_DATES_INVALID')
    cutoff=aware(request['research_cutoff'])
    if cutoff.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d')!=target:raise ValueError('HK_CUTOFF_DATE_MISMATCH')
    if request['data_kind'] not in ('SYNTHETIC','RECORDED_INPUT_REPLAY'):raise ValueError('HK_DATA_KIND_INVALID')
    # Reuse path/file-map validation only, never A's calendar or A's signal.
    common._request(dict(target_date=target,signal_date=signal,data_kind=request['data_kind'],lanes=[
        dict(kind='v192',input_root=request['input_root'],paths={},files=request['files'])]))
    canonical_bytes(request)
    return request


def _source_bytes():
    descriptor=json.loads(no_symlinks(DESCRIPTOR).read_bytes())
    if sha256_json(descriptor)!=DESCRIPTOR_SHA256:raise ValueError('HK_SOURCE_MANIFEST_MISMATCH')
    sources={}
    for entry in descriptor['entries']:
        data=common._relative(CAPSULE,entry['relative_path']).read_bytes()
        if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise ValueError('HK_SOURCE_BYTES_MISMATCH')
        sources[entry['relative_path']]=data
    return sources


class _HKLoader(common._FrozenLoader):
    def exec_module(self,module):
        if module.__name__ in self.packages:module.__path__=[]
        item=self.sources.get(module.__name__)
        if item:
            relative,data,_=item;module.__file__=str(CAPSULE/relative)
            exec(compile(data,module.__file__,'exec'),module.__dict__)


def _json(path):
    with no_symlinks(path).open('rb') as stream:
        data=stream.read(MAX_JSON_BYTES+1)
    if len(data)>MAX_JSON_BYTES:raise common.InputEvidenceError('HK_METADATA_TOO_LARGE')
    value=json.loads(data)
    if not isinstance(value,dict):raise common.InputEvidenceError('HK_METADATA_INVALID')
    return value


def _verify_pool(pool,master,master_manifest,request,root):
    run=pool.run;manifest=run.manifest;receipt=run.receipt;verification=run.verification
    target=request['target_date'];signal=request['signal_date'];eligibility=request['eligibility_source_date']
    cutoff=aware(request['research_cutoff'])
    if receipt.get('status')!='READY' or verification.get('status')!='READY' or manifest.get('temporal_cutoff_safe') is not True:
        raise common.InputEvidenceError('HK_SOURCE_NOT_READY')
    if (manifest.get('trade_date')!=target or receipt.get('trade_date')!=target
        or manifest.get('signal_date')!=signal or manifest.get('role',ROLE)!=ROLE or receipt.get('role')!=ROLE):
        raise common.InputEvidenceError('HK_SOURCE_DATE_OR_ROLE_MISMATCH')
    try:
        finished=aware(receipt['finished_at']);captured=aware(master_manifest['captured_at']);pool_captured=aware(manifest['captured_at'])
    except (ValueError,KeyError,TypeError) as error:raise common.InputEvidenceError('HK_SOURCE_TIME_UNVERIFIED') from error
    if finished>cutoff or captured>cutoff or pool_captured>cutoff:raise common.InputEvidenceError('HK_SOURCE_AFTER_CUTOFF')
    if not captured<=pool_captured<=finished:raise common.InputEvidenceError('HK_SOURCE_CLOCK_ORDER_INVALID')
    if master_manifest.get('trade_date')!=eligibility:raise common.InputEvidenceError('HK_MASTER_DATE_MISMATCH')
    master_root=root/'assets/hk_security_master';latest=_json(master_root/'latest.json')
    entry=latest['entries'][eligibility]
    master_receipt=_json(common._relative(master_root,entry['receipt_relative']))
    if master_receipt.get('trade_date')!=eligibility:raise common.InputEvidenceError('HK_MASTER_RECEIPT_DATE_MISMATCH')
    if verification.get('row_count')!=100 or len(pool.rows)!=100:raise common.InputEvidenceError('HK_TOP100_COUNT_MISMATCH')
    for row in pool.rows:
        if row.get('trade_date')!=target:raise common.InputEvidenceError('HK_ROW_TRADE_DATE_MISMATCH')
        code=str(row.get('code_norm') or row.get('code') or '').removeprefix('HK.')
        if 'HK.'+code not in master:raise common.InputEvidenceError('HK_MEMBER_NOT_IN_SOURCE_MASTER')
        try:score=float(row['score_prob_active'])
        except (KeyError,TypeError,ValueError) as error:raise common.InputEvidenceError('HK_SCORE_INVALID') from error
        if not math.isfinite(score) or not 0<=score<=1:raise common.InputEvidenceError('HK_SCORE_INVALID')
    try:sha(str(manifest.get('provenance',{}).get('panel_sha256','')))
    except ValueError as error:raise common.InputEvidenceError('HK_PANEL_IDENTITY_INVALID') from error


def _assemble(request):
    request=_request(request);sources=_source_bytes();finder=_HKLoader(sources)
    if any(name in sys.modules for name in ('domains','infrastructure','contracts','upstreams')):
        raise ValueError('HK_WORKER_REQUIRES_FRESH_PROCESS')
    sys.meta_path.insert(0,finder)
    calendars=importlib.import_module('contracts.trading_calendar');calendar=calendars.load_market_calendar()
    states=calendars.resolve_market_states(calendar,request['target_date'])
    if states['hk_securities'].value not in ('FULL_TRADING_DAY','HALF_TRADING_DAY_AM'):
        raise ValueError('HK_TARGET_NOT_SECURITIES_SESSION')
    if calendars.previous_session(calendar,request['target_date'],market='hk_securities')!=request['signal_date']:
        raise ValueError('HK_SIGNAL_NOT_PREVIOUS_SECURITIES_SESSION')
    module=importlib.import_module('domains.preselection_materializer')
    reader_module=importlib.import_module('upstreams.v3_shared_data.shared_data.hk_0_2')
    master_module=importlib.import_module('upstreams.v3_shared_data.shared_data.hk_security_master')
    validator=importlib.import_module('infrastructure.preselection_pool_store').validate_pool_artifact
    # The shared guard consumes a complete A-lane descriptor, even for this
    # HK-only reader. Keep the lane tagged as v1.9.2 without adding A dates.
    lane=dict(kind='v192',input_root=request['input_root'],paths={},files=request['files'])
    select=common._guard([lane]);select(lane);root=no_symlinks(request['input_root'])
    base=dict(schema_version=SCHEMA,target_date=request['target_date'],signal_date=request['signal_date'],
              eligibility_source_date=request['eligibility_source_date'],research_cutoff=request['research_cutoff'],
              data_kind=request['data_kind'],market_states={k:v.value for k,v in states.items()},
              request_sha256=sha256_json(request),source_capsule_sha256=DESCRIPTOR_SHA256,
              implementation_identity=_identity(),model_weights_reverified=False,
              input_binding_status='DECLARED_BYTES_CHECKED',isolation_status='PYTHON_GUARDS_ONLY_OS_UNVERIFIED',**SAFETY)
    try:
        common._verify_lane(lane)
        def checked_reader(source_root,*,target_date,expected_signal_date,expected_eligibility_source_date=None):
            if (no_symlinks(source_root)!=root or target_date!=request['target_date']
                or expected_signal_date!=request['signal_date']
                or (expected_eligibility_source_date or expected_signal_date)!=request['eligibility_source_date']):
                raise common.InputEvidenceError('HK_READER_ARGUMENT_BINDING_MISMATCH')
            pool=reader_module.read_verified_hk_0_2_pool(source_root,target_date=target_date,
                expected_signal_date=expected_signal_date,expected_eligibility_source_date=request['eligibility_source_date'])
            master,master_manifest=master_module.load_verified_hk_security_master(source_root,request['eligibility_source_date'])
            _verify_pool(pool,master,master_manifest,request,root)
            return pool
        with redirect_stdout(io.StringIO()):
            artifact=module.build_shared_hk_0_2_pool(root,trade_date=request['target_date'],signal_date=request['signal_date'],
                eligibility_source_date=request['eligibility_source_date'],reader=checked_reader)
        validator(artifact);canonical_bytes(artifact)
        if artifact.get('market')!='HK' or artifact.get('trade_date')!=request['target_date']:
            raise common.InputEvidenceError('HK_OUTPUT_IDENTITY_MISMATCH')
        common._verify_lane(lane);_source_bytes()
        return dict(base,status='ASSEMBLED',artifact=artifact,reason='',finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as error:
        if not (common._expected(error) or type(error) is ValueError and str(error).startswith('shared HK 0.2 ')):raise
        return dict(base,status='CANNOT_CONFIRM',artifact=None,reason=type(error).__name__+':'+str(error),finished_at=datetime.now(timezone.utc).isoformat())


def run_hk_preselection(request):
    request=_request(request);identity=_identity()
    with tempfile.TemporaryDirectory(prefix='v5-hk-source-cache-') as cache:
        process=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(Path(cache).resolve()),str(Path(__file__).resolve()),'--worker'],
                               input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if len(process.stdout)>MAX_JSON_BYTES:raise ValueError('HK_WORKER_OUTPUT_TOO_LARGE')
    try:result=json.loads(process.stdout)
    except (ValueError,UnicodeError) as error:raise ValueError('HK_WORKER_RESPONSE_INVALID:'+process.stderr.decode(errors='replace')[-2000:]) from error
    if process.returncode!=0:raise ValueError(result.get('reason','HK_WORKER_FAILED'))
    if (result.get('schema_version')!=SCHEMA or result.get('request_sha256')!=sha256_json(request)
        or result.get('source_capsule_sha256')!=DESCRIPTOR_SHA256 or result.get('implementation_identity')!=identity
        or _identity()!=identity or any(result.get(k)!=request[k] for k in ('target_date','signal_date','eligibility_source_date','research_cutoff','data_kind'))
        or result.get('status') not in ('ASSEMBLED','CANNOT_CONFIRM')
        or any(result.get(k)!=v for k,v in SAFETY.items()) or result.get('model_weights_reverified') is not False):
        raise ValueError('HK_WORKER_CONTRACT_MISMATCH')
    return result


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('REQUEST_TOO_LARGE')
        print(canonical_bytes(_assemble(json.loads(raw))).decode())
    except Exception as error:
        print(canonical_bytes(dict(status='FAILED',reason=type(error).__name__+':'+str(error))).decode())
        raise SystemExit(1)
