"""V5-only retained-SDK membership recovery. Never calls OpenD or evaluates quotes."""
import sys
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import datetime,timezone
import hashlib
import importlib
import json
import os
import re
import subprocess
import tempfile
from zoneinfo import ZoneInfo
from v5_shadow import a_preselection as common
from v5_shadow.composition import no_symlinks
from v5_shadow.contracts import exact_keys,sha,trade_date
from v5_shadow.digests import canonical_bytes,sha256_json,MAX_JSON_BYTES

BASE=Path(__file__).resolve().parents[2]
CAPSULE=BASE/'vendor/hk_membership_baseline'
DESCRIPTOR=BASE/'contracts/hk_membership_source_manifest.json'
PIN='e06a2898a8d5247101acd8b85169d1d51e4d359d6e197ef55d52e0f1c4c7068d'
PRODUCER_SHA='0a9651f88bc8a50d4b5e8ec4b6775a5291918f9f2556cf37c05b80a55cdfd84a'
FLAGS=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)


def _sources():
    manifest=json.loads(DESCRIPTOR.read_bytes())
    if sha256_json(manifest)!=PIN:raise ValueError('MEMBERSHIP_SOURCE_PIN')
    result={}
    for row in manifest['entries']:
        raw=(CAPSULE/row['relative_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('MEMBERSHIP_SOURCE_BYTES')
        result[row['relative_path']]=raw
    return result


class _Loader(common._FrozenLoader):
    def exec_module(self,module):
        if module.__name__ in self.packages:module.__path__=[];return
        relative,raw,_=self.sources[module.__name__];module.__file__=str(CAPSULE/relative)
        exec(compile(raw,module.__file__,'exec'),module.__dict__)


def _request(value):
    exact_keys(value,('sdk_path','sdk_sha256','output_root','target_date'))
    sha(value['sdk_sha256']);trade_date(value['target_date'])
    source=no_symlinks(value['sdk_path']);output=no_symlinks(value['output_root'])
    if not source.is_file() or not output.is_dir():raise ValueError('MEMBERSHIP_ROOT')
    if source.is_relative_to(output):raise ValueError('MEMBERSHIP_INPUT_OUTPUT_OVERLAP')
    if no_symlinks(output/'.v5-hk-membership-root').read_bytes()!=b'v5.hk-membership-root.v1\n':raise ValueError('MEMBERSHIP_OUTPUT_MARKER')
    if any(p.name!='.v5-hk-membership-root' for p in output.iterdir()):raise ValueError('MEMBERSHIP_FRESH_PRIVATE_OUTPUT_REQUIRED')
    return source,output


def _reject_constant(value):raise ValueError('NONFINITE_JSON:'+value)


def _capture(raw,expected,target,owner):
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('SDK_SHA_MISMATCH')
    sdk=json.loads(raw,parse_constant=_reject_constant)
    if (sdk.get('schema_version')!='v4.manager_hk_connect_capture.v2' or sdk.get('status')!='RAW_CAPTURED'
        or sdk.get('target_date')!=target or any(sdk.get(k) is not False for k in FLAGS)):
        raise ValueError('SDK_ENVELOPE_INVALID')
    producer=sdk.get('producer_owner') or {}
    if producer.get('code_sha256')!=PRODUCER_SHA:raise ValueError('SDK_PRODUCER_SHA')
    responses=sdk.get('plate_responses') or {}
    if set(responses)!=set(owner.HKCONNECT_PLATE_CODES):raise ValueError('SDK_PLATE_SET')
    plates={};counts={};digests={};completed=[]
    for plate,response in responses.items():
        codes=[]
        for row in response.get('rows',[]):
            code=row.get('code')
            if not isinstance(code,str) or not re.fullmatch(r'HK\.\d{5}',code):raise ValueError('SDK_CODE_INVALID')
            codes.append(code)
        plates[plate]=sorted(set(codes));counts[plate]=response.get('row_count');digests[plate]=response.get('response_sha256')
        completed.append(datetime.fromisoformat(response['completed_at'].replace('Z','+00:00')))
    acquired=max(completed)
    actual=datetime.now(timezone.utc)
    if acquired.tzinfo is None or acquired>actual or acquired.astimezone(ZoneInfo('Asia/Hong_Kong')).strftime('%Y%m%d')!=target:
        raise ValueError('SDK_ACQUISITION_TIME_INVALID')
    if actual.astimezone(ZoneInfo('Asia/Hong_Kong')).strftime('%Y%m%d')!=target:raise ValueError('RECOVERY_TARGET_NOT_CURRENT_DAY')
    material=dict(target_date=target,plate_codes=plates,plate_response_sha256=digests,capture_run_id=sdk['capture_run_id'],acquired_at=acquired.isoformat())
    union=sorted(set().union(*map(set,plates.values())))
    capture=dict(schema_version=sdk['schema_version'],status='READY',membership_status='READY',target_date=target,
        capture_run_id=sdk['capture_run_id'],producer_owner=producer,plate_responses=responses,plate_codes=plates,
        plate_response_counts=counts,plate_response_sha256=digests,acquired_at=acquired.isoformat(),codes=union,code_count=len(union),
        overlap_count=len(set.intersection(*map(set,plates.values()))),membership_source_payload=material,membership_source_sha256=sha256_json(material),
        quote_status='NOT_EVALUATED',panel_status='NOT_EVALUATED',security_master_status='NOT_EVALUATED',
        v5_recovery=dict(execution_kind='MANUAL_RECOVERY',sdk_raw_sha256=expected,recovered_at=actual.isoformat(),natural_verified=False),**FLAGS)
    capture['capture_sha256']=sha256_json(capture)
    owner.validate_captured_hk_connect_membership_v2(capture,trade_date=target)
    return capture


def _write(root,relative,raw):
    path=common._relative(root,relative);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:stream.write(raw)
    if path.read_bytes()!=raw:raise ValueError('MEMBERSHIP_WRITE_READBACK')


def worker(request):
    source,output=_request(request)
    if source.stat().st_size>MAX_JSON_BYTES:raise ValueError('SDK_SIZE_LIMIT')
    raw=source.read_bytes()
    if len(raw)>MAX_JSON_BYTES:raise ValueError('SDK_SIZE_LIMIT')
    sources=_sources();sys.meta_path.insert(0,_Loader(sources))
    owner=importlib.import_module('stage_center.hk_universe_preflight')
    evidence=importlib.import_module('domains.manager_research_evidence')
    owner_sha=hashlib.sha256(sources['stage_center/hk_universe_preflight.py']).hexdigest()
    capture=_capture(raw,request['sdk_sha256'],request['target_date'],owner)
    contract_owner=dict(code_ref='stage_center/hk_universe_preflight.py',code_sha256=owner_sha,
        role='PURE_CAPTURED_HK_CONNECT_CONTRACT_V2')
    built=owner.build_captured_hk_connect_authority_v2(capture,trade_date=request['target_date'],producer_owner=capture['producer_owner'],contract_owner=contract_owner)
    # Only immutable writes below the explicit empty V5 root; no publisher from V4 is run.
    files={built['paths'][kind+'_relative']:built[kind+'_bytes'] for kind in ('artifact','manifest','receipt','current')}
    files[built['capture_relative']]=built['capture_bytes']
    sdk_relative=str(Path(built['capture_relative']).parent/'sdk.capture.json');files[sdk_relative]=raw
    for relative,data in files.items():_write(output,relative,data)
    producer=capture['producer_owner'];target=request['target_date'];paths=built['paths']
    publication=dict(schema_version=owner.HK_CONNECT_PUBLICATION_SCHEMA_V2,status='READY',target_date=target,effective_date=target,trade_date=target,source_date=target,market='HK_CONNECT',scope='FULL_MARKET',run_id=built['run_id'],publication_relative=built['publication_relative'],available_at=datetime.now(timezone.utc).isoformat(),acquired_at=capture['acquired_at'],capture_run_id=capture['capture_run_id'],capture_sha256=capture['capture_sha256'],artifact_relative=paths['artifact_relative'],artifact_sha256=built['artifact_sha256'],manifest_relative=paths['manifest_relative'],receipt_relative=paths['receipt_relative'],current_relative=paths['current_relative'],current_sha256=built['current_sha256'],workload_id=producer['workload_id'],producer_owner=producer,contract_owner=contract_owner,forward_source_set=producer['forward_source_set'],forward_source_set_sha256=producer['forward_source_set_sha256'],**FLAGS)
    publication['publication_sha256']=sha256_json(publication)
    files[built['publication_relative']]=owner._canonical_json_line(publication)
    _write(output,built['publication_relative'],files[built['publication_relative']])
    verified=evidence.read_universe_evidence(output,target,authority_owner_root=CAPSULE,authority_owner_sha256=owner_sha,require_v2=True)
    # Independently exercise the original historical availability gate too.
    try:
        evidence.read_universe_evidence(output,target,as_of=datetime.fromisoformat(capture['acquired_at']),authority_owner_root=CAPSULE,authority_owner_sha256=owner_sha,require_v2=True)
    except evidence.EvidenceError as exc:prior_cutoff_reason=str(exc)
    else:raise ValueError('MEMBERSHIP_PRIOR_AVAILABILITY_GATE_BYPASSED')
    if source.read_bytes()!=raw:raise ValueError('SDK_CHANGED_DURING_RECOVERY')
    actual_files={}
    for name,data in files.items():
        persisted=common._relative(output,name).read_bytes()
        if persisted!=data:raise ValueError('MEMBERSHIP_FINAL_READBACK_MISMATCH')
        actual_files[name]=hashlib.sha256(persisted).hexdigest()
    _sources()
    return dict(status='PRIVATE_MEMBERSHIP_PUBLISHED',code_count=len(verified.codes),readback=dict(code_count=len(verified.codes),source=dict(verified.source)),
        capture_relative=built['capture_relative'],manifest_relative=paths['manifest_relative'],sdk_relative=sdk_relative,source_capsule_sha256=PIN,
        files=actual_files,request_sha256=sha256_json(request),execution_kind='MANUAL_RECOVERY',natural_verified=False,
        prior_cutoff_rejection=prior_cutoff_reason,quote_status='NOT_EVALUATED',panel_status='NOT_EVALUATED',security_master_status='NOT_EVALUATED',price_unit=None,market_finality=None,**FLAGS)


def run_recovery(request):
    _request(request);_sources()
    with tempfile.TemporaryDirectory(prefix='v5-hk-membership-') as cache:
        process=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+cache,str(Path(__file__).resolve())],input=canonical_bytes(request),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,env={k:v for k,v in os.environ.items() if not k.startswith(('V4_','V35_'))})
    if len(process.stdout)>MAX_JSON_BYTES:raise ValueError('MEMBERSHIP_RESPONSE_LIMIT')
    try:out=json.loads(process.stdout)
    except ValueError as exc:raise ValueError('MEMBERSHIP_RESPONSE:'+process.stderr.decode(errors='replace')[-1000:]) from exc
    if process.returncode:raise ValueError(out.get('reason','MEMBERSHIP_WORKER_FAILED'))
    if out.get('request_sha256')!=sha256_json(request) or out.get('source_capsule_sha256')!=PIN:raise ValueError('MEMBERSHIP_RESPONSE_IDENTITY')
    _sources();return out


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_JSON_BYTES+1)
        if len(raw)>MAX_JSON_BYTES:raise ValueError('MEMBERSHIP_REQUEST_LIMIT')
        print(canonical_bytes(worker(json.loads(raw))).decode())
    except Exception as exc:
        print(json.dumps({'reason':type(exc).__name__+':'+str(exc)}));raise SystemExit(1)
