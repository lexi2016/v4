"""Small, JSON-emitting CLI. Only run-shadow is allowed to write results."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from .composition import validate_composition,render_effective_config,no_symlinks,shadow_root
from .contracts import SourceCapsule,SourceEntry,parse_manifest,parse_request,trade_date
from .digests import canonical_bytes,sha256_json,MAX_JSON_BYTES
from .health import observe_runtime,evaluate_health
from .shadow_store import _load,_ref,read_shadow,wire,parse_result,publish_shadow
from .source_capsule import inspect_capsule

class Parser(argparse.ArgumentParser):
    def error(self,message):raise ValueError('ARGUMENTS_INVALID')


def load_json(path):
    path=no_symlinks(Path(path))
    return _load(path.parent,path.name)[0]


def load_capsule():
    root=Path(__file__).resolve().parents[2]
    descriptor=root/'contracts'/'rebound_source_manifest.json'
    if not descriptor.is_file():return SourceCapsule((),'', '', '')
    value=load_json(descriptor)
    return inspect_capsule(root/'vendor'/'rebound_baseline',tuple(SourceEntry(**e) for e in value['entries']))


def _reason(error):
    import re
    message=str(error)
    return message if re.fullmatch('[A-Z0-9_:]+',message) else type(error).__name__


def main(argv=None):
    try:
        parser=Parser(prog='v5-shadow')
        commands=parser.add_subparsers(dest='command',required=True)
        for name in ('check','health','run-shadow'):
            item=commands.add_parser(name);item.add_argument('--composition',required=True)
            if name=='run-shadow':
                item.add_argument('--request',required=True);item.add_argument('--output-root',required=True)
        item=commands.add_parser('read-result')
        for name in ('output-root','target-date','run-id'):item.add_argument('--'+name,required=True)
        args=parser.parse_args(argv)
        if args.command=='read-result':
            root=shadow_root(Path(args.output_root));trade_date(args.target_date)
            import re
            if re.fullmatch('[0-9a-f]{32}',args.run_id) is None:raise ValueError('RUN_ID_INVALID')
            record,_=_load(root,'refs/'+args.run_id+'.json')
            if record['target_trade_date']!=args.target_date:raise ValueError('RUN_TARGET_MISMATCH')
            ref=_ref(record['reference'])
            if ref.run_id!=args.run_id:raise ValueError('RUN_REFERENCE_MISMATCH')
            result=read_shadow(root,ref)
            if result.run_id!=args.run_id:raise ValueError('RUN_REFERENCE_MISMATCH')
            print(canonical_bytes({'status':result.business_status,'reason_codes':result.legacy_screen.get('gaps',[]),'result':wire(result)}).decode())
            return 0 if result.business_status in ('COMPLETED','VALID_EMPTY') else 2
        raw=load_json(args.composition)
        composition=validate_composition(raw,{k:parse_manifest(v) for k,v in raw['modules'].items()})
        config=render_effective_config(composition,'rebound_shadow')
        if args.command=='check':
            print(canonical_bytes({'status':'CONFIGURATION_VALID','reason_codes':[], 'business_verified':False,'natural_verified':False,'composition_sha256':sha256_json(raw)}).decode());return 0
        if args.command=='health':
            observed=observe_runtime(composition.modules['rebound_shadow'],load_capsule(),config)
            report=evaluate_health(composition.modules['rebound_shadow'],composition.bindings['rebound_shadow'],sha256_json(config),observed,{'status':'MISSING' if composition.bindings['rebound_shadow'].authority_root is None else 'UNVERIFIED'})
            print(canonical_bytes({'status':'OBSERVED','reason_codes':list(report.reason_codes),'health':wire(report),'business_verified':False,'natural_verified':False}).decode())
            return 3 if report.identity_status=='MISMATCH' or report.compatibility_status=='INCOMPATIBLE' else 2
        root=shadow_root(Path(args.output_root))
        if root!=composition.bindings['rebound_shadow'].shadow_root:raise ValueError('OUTPUT_ROOT_MISMATCH')
        request_raw=load_json(args.request);request=parse_request(request_raw)
        if request.composition_sha256!=sha256_json(raw):raise ValueError('REQUEST_COMPOSITION_MISMATCH')
        if request.input_snapshot_sha256!=composition.bindings['rebound_shadow'].input_snapshot_sha256:raise ValueError('REQUEST_INPUT_BINDING_MISMATCH')
        with tempfile.TemporaryDirectory(prefix='.worker-',dir=root) as temp:
            request_path=Path(temp)/'request.json';config_path=Path(temp)/'config.json'
            request_path.write_bytes(canonical_bytes(request_raw));config_path.write_bytes(canonical_bytes(config))
            worker=Path(__file__).with_name('worker.py')
            # -B alone still reads timestamp caches. A new empty cache prefix
            # selected before the first import makes this worker source-only.
            cache_path=Path(temp)/'unused-bytecode';cache_path.mkdir()
            completed=subprocess.run([sys.executable,'-I','-B','-X','pycache_prefix='+str(cache_path),str(worker),str(request_path),str(config_path)],capture_output=True,timeout=60,env={'PATH':os.defpath,'OPENBLAS_NUM_THREADS':'1'})
            if len(completed.stdout)>MAX_JSON_BYTES:raise ValueError('WORKER_OUTPUT_TOO_LARGE')
            payload=json.loads(completed.stdout)
            if not isinstance(payload,dict) or completed.returncode not in (0,2,3,4):raise ValueError('WORKER_OUTPUT_INVALID')
            return_code=completed.returncode
            if 'result' in payload and completed.returncode in (0,2):
                result=parse_result(payload['result'])
                if result.request!=request or result.runtime.effective_config_sha256!=sha256_json(config):
                    raise ValueError('WORKER_REQUEST_OR_CONFIG_MISMATCH')
                ref=publish_shadow(root,result)
                # An idempotent publish may return an earlier committed run.
                # Return that exact artifact, never a fresh result paired with
                # another run's reference and checksum.
                result=read_shadow(root,ref)
                payload['result']=wire(result)
                payload['status']=result.business_status
                payload['reason_codes']=result.legacy_screen.get('gaps',[])
                return_code=0 if result.business_status in ('COMPLETED','VALID_EMPTY') else 2
                payload['reference']=wire(ref)
                payload['natural_verified']=False
                payload['data_kind']=request.data_kind
            print(canonical_bytes(payload).decode());return return_code
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(canonical_bytes({'status':'REJECTED','reason_codes':[_reason(error)]}).decode());return 3
    except subprocess.TimeoutExpired:
        print(canonical_bytes({'status':'FAILED','reason_codes':['WORKER_TIMEOUT']}).decode());return 4
    except Exception as error:
        print(canonical_bytes({'status':'FAILED','reason_codes':[type(error).__name__]}).decode());return 4

if __name__=='__main__':raise SystemExit(main())
