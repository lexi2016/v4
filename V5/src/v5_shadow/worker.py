"""Dedicated, no-network shadow process. Python guards are not OS isolation proof."""
import sys
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import datetime,timezone,timedelta
import io
from contextlib import redirect_stdout
from v5_shadow.cli import load_json,load_capsule,_reason
from v5_shadow.composition import parse_binding
from v5_shadow.contracts import parse_manifest,parse_request,exact_keys
from v5_shadow.digests import canonical_bytes,sha256_json
from v5_shadow.health import observe_runtime,evaluate_health
from v5_shadow.legacy_adapter import run_legacy_screen,build_shadow_result
from v5_shadow.shadow_store import publish_shadow,wire
from v5_shadow.input_snapshot import verify_snapshot


def install_python_guards():
    # The legacy read phase must not spawn processes, connect sockets or write.
    # This is defense in depth. Native code/OS-level read-only enforcement must
    # be independently verified before claiming an isolated production read.
    def audit(event,args):
        if event in ('socket.connect','socket.connect_ex','socket.bind','subprocess.Popen','os.system','os.exec','os.posix_spawn'):
            raise PermissionError('SHADOW_NETWORK_OR_PROCESS_DENIED')
        if event in ('os.remove','os.rename','os.rmdir','os.mkdir','os.chmod','os.link','os.symlink','os.truncate'):
            raise PermissionError('SHADOW_SOURCE_WRITE_DENIED')
        if event=='open':
            mode=args[1] if len(args)>1 else None;flags=args[2] if len(args)>2 else 0
            import os
            if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):
                raise PermissionError('SHADOW_SOURCE_WRITE_DENIED')
    sys.addaudithook(audit)


def worker_main(request_json:Path,effective_config_json:Path) -> int:
    try:
        started=datetime.now(timezone.utc)
        request=parse_request(load_json(request_json));config=load_json(effective_config_json)
        exact_keys(config,('module','binding'))
        module=parse_manifest(config['module']);binding=parse_binding(config['binding'])
        if request.requested_at>started+timedelta(seconds=5):raise ValueError('REQUEST_CLOCK_IN_FUTURE')
        if request.execution_kind=='SHADOW_MANUAL' and request.target_trade_date!=started.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d'):
            raise ValueError('HISTORICAL_CUTOFF_REQUIRES_REPLAY')
        observed=observe_runtime(module,load_capsule(),config)
        health=evaluate_health(module,binding,sha256_json(config),observed,{'status':'UNVERIFIED'})
        if health.identity_status!='MATCH' or health.compatibility_status!='COMPATIBLE':
            print(canonical_bytes({'status':'REJECTED','reason_codes':list(health.reason_codes),'health':wire(health)}).decode());return 3
        if request.data_kind=='OWNER_VERIFIED':raise ValueError('OWNER_INPUT_STABILITY_UNVERIFIED')
        if request.input_snapshot_sha256 is not None:
            verify_snapshot(binding.authority_root,request.input_snapshot_sha256)
        # The audit hook is permanent. Read and result-writing are separated into
        # different processes: the worker returns data only; the parent commits.
        install_python_guards()
        with redirect_stdout(io.StringIO()):legacy=run_legacy_screen(request,binding)
        if request.input_snapshot_sha256 is not None:
            verify_snapshot(binding.authority_root,request.input_snapshot_sha256)
        finished=datetime.now(timezone.utc)
        result=build_shadow_result(request,observed,legacy,started,finished)
        print(canonical_bytes({'status':result.business_status,'reason_codes':legacy.get('gaps',[]),'result':wire(result),'isolation_status':'PYTHON_GUARDS_ONLY_OS_UNVERIFIED'}).decode())
        return 0 if result.business_status in ('COMPLETED','VALID_EMPTY') else 2
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(canonical_bytes({'status':'REJECTED','reason_codes':[_reason(error)]}).decode());return 3
    except Exception as error:
        print(canonical_bytes({'status':'FAILED','reason_codes':[type(error).__name__]}).decode());return 4

if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit(3)
    raise SystemExit(worker_main(Path(sys.argv[1]),Path(sys.argv[2])))
