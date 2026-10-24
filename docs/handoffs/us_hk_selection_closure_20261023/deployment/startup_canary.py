"""Full API/WorkbenchHook constructor on immutable candidate bytes, private state only.

Run with the role's pinned Python using -I -S -B. This is a constructor closure
canary, not live startup, lifespan, scheduler tick, business/provider or model work.
"""
from __future__ import annotations

import argparse
import concurrent.futures
from contextlib import contextmanager
import json
import os
from pathlib import Path
import plistlib
import signal
import socket
import sys
import tempfile
import threading

from prepare_release import exact, json_bytes, read_json, require, sha, write_new


@contextmanager
def constructor_boundary(private_root,codex_binary,probes):
    """Block network/jobs and non-metadata child execution in this one-shot process."""
    active=[True];private_root=private_root.resolve();old_cwd=Path.cwd()
    originals=(threading.Thread.start,concurrent.futures.ThreadPoolExecutor.submit,concurrent.futures.ProcessPoolExecutor.submit)
    send_originals={name:getattr(socket.socket,name) for name in ('send','sendall','sendto','sendmsg','sendmsg_afalg','sendfile') if hasattr(socket.socket,name)}
    def denied(*args,**kwargs):raise RuntimeError('STARTUP_CANARY_JOB_OR_THREAD_FORBIDDEN')
    def denied_send(*args,**kwargs):raise RuntimeError('STARTUP_CANARY_NETWORK_OR_PROCESS_FORBIDDEN:socket.send')
    def inside(path):
        if isinstance(path,int):return True
        return Path(os.fsdecode(path)).resolve(strict=False).is_relative_to(private_root)
    def audit(event,args):
        if not active[0]:return
        if event.startswith(('socket.send','os.exec','os.spawn','os.posix_spawn')) or event in {
                'socket.__new__','socket.connect','socket.connect_ex','socket.bind','socket.getaddrinfo',
                'os.system','os.fork','os.forkpty','os.startfile','os.startfile/2'}:
            raise RuntimeError('STARTUP_CANARY_NETWORK_OR_PROCESS_FORBIDDEN:'+event)
        if event=='subprocess.Popen':
            command=args[1];exe=Path(os.fsdecode(args[0])).resolve()
            cli=sys.modules.get('v4.manager_workbench.executors.local_cli');features=getattr(cli,'DISABLED_FEATURES',())
            feature_args=[part for name in features for part in ('--disable',name)]+['features','list']
            safe=(codex_binary is not None and exe==Path(codex_binary).resolve() and isinstance(command,(list,tuple)) and
                (list(command[1:])==['--version'] or list(command[1:])==['exec','--help'] or
                 bool(features) and list(command[1:])==feature_args))
            require(safe,'STARTUP_CANARY_NON_METADATA_PROCESS');probes.append(list(command))
        if event=='open':
            path,mode,flags=args
            write=(isinstance(mode,str) and any(m in mode for m in 'wax+')) or (isinstance(flags,int) and bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)))
            require(not write or inside(path),'STARTUP_CANARY_WRITE_OUTSIDE_PRIVATE_STATE')
        if event in {'os.mkdir','os.remove','os.rmdir','os.chmod','os.utime','os.truncate'}:
            require(inside(args[0]),'STARTUP_CANARY_MUTATION_OUTSIDE_PRIVATE_STATE')
        if event in {'os.rename','os.link','os.symlink'}:
            require(inside(args[0]) and inside(args[1]),'STARTUP_CANARY_MUTATION_OUTSIDE_PRIVATE_STATE')
    sys.addaudithook(audit);os.chdir(private_root)
    threading.Thread.start=denied;concurrent.futures.ThreadPoolExecutor.submit=denied;concurrent.futures.ProcessPoolExecutor.submit=denied
    # CPython send/sendall lack audit events; deny normal socket APIs as well.
    for name in send_originals:setattr(socket.socket,name,denied_send)
    try:yield
    finally:
        active[0]=False
        threading.Thread.start,concurrent.futures.ThreadPoolExecutor.submit,concurrent.futures.ProcessPoolExecutor.submit=originals
        for name,method in send_originals.items():setattr(socket.socket,name,method)
        os.chdir(old_cwd)


def full_constructor(role,config,root):
    """Do not stub create_app, native binding, service, Store or Coordinator."""
    if role=='api':
        from apps.api.v35_api.app import create_app
        app=create_app(data_root=root/'data',shared_data_root=root/'shared',ledger_root=root/'ledger',
            stage_center_selection_root=root/'stage',manager_research_state_root=root/'manager',research_data_root=root/'research',
            research_ledger_root=root/'research-ledger',morning_news_data_root=root/'news',preselection_source_root=root/'pool',
            manager_workbench_config=config)
        service=app.state.manager_workbench_service
        try:
            require(service.config.scheduled_lanes==config.scheduled_lanes,'STARTUP_CANARY_LANE_DRIFT')
            require(service.capture_jobs is None,'STARTUP_CANARY_CAPTURE_UNEXPECTED')
            return dict(constructor='create_app',route_count=len(app.routes),service_type=type(service).__name__)
        finally:service.stop()
    from v4.manager_workbench.supervisor import WorkbenchHook
    hook=WorkbenchHook.from_environment(start=False)
    require(hook is not None,'STARTUP_CANARY_SCHEDULER_CONFIG_MISSING')
    try:
        require(not hook.thread.is_alive() and hook.service.capture_jobs is None,'STARTUP_CANARY_BACKGROUND_WORK_UNEXPECTED')
        require(hook.service.config.scheduled_lanes==config.scheduled_lanes,'STARTUP_CANARY_LANE_DRIFT')
        return dict(constructor='WorkbenchHook.from_environment(start=False)',service_type=type(hook.service).__name__)
    finally:hook.stop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared',required=True);parser.add_argument('--prepared-sha256',required=True);parser.add_argument('--receipt',required=True)
    args=parser.parse_args();prepared=read_json(args.prepared,args.prepared_sha256);scope=read_json(prepared['scope_path'],prepared['scope_sha256'])
    require(scope.get('mode')=='RELEASE' and scope.get('role') in {'api','scheduler'},'STARTUP_CANARY_ROLE_REQUIRED')
    root=exact(Path(prepared['candidate_root'])/'app');manifest=root.parent/'release-manifest.json'
    require(sha(manifest)==prepared['candidate_manifest_sha256'],'STARTUP_CANARY_CANDIDATE_MANIFEST_DRIFT')
    inventory={row['path']:row for row in json.loads(manifest.read_bytes())['application_inventory']['entries']}
    python=scope['runtime_probe']['python'];require(Path(sys.executable).resolve()==Path(python['resolved_path']) and sha(sys.executable)==python['sha256'],
        'STARTUP_CANARY_PINNED_INTERPRETER_REQUIRED')
    receipt=exact(args.receipt,exists=False);scratch=exact(Path(__file__).resolve().parents[4]/'.superpowers/sdd/2026-10-23-us-hk-selection-closure/scratch/deployment')
    require(receipt.is_relative_to(scratch) and receipt.parent.exists() and not receipt.exists(),'STARTUP_CANARY_RECEIPT_BOUNDARY')
    binding=plistlib.loads(Path(prepared['candidate_plist']).read_bytes());env=dict(binding['EnvironmentVariables'])
    env.update({arg.split('=',1)[0]:arg.split('=',1)[1] for arg in binding.get('ProgramArguments',[]) if isinstance(arg,str) and '=' in arg and not arg.startswith('/')})
    config_path=env['V4_MANAGER_WORKBENCH_CONFIG_PATH'];pins=[p for p in scope['dependencies'] if p['path']==config_path]
    require(len(pins)==1,'STARTUP_CANARY_CONFIG_PIN_REQUIRED');raw_config=read_json(config_path,pins[0]['sha256'])
    require(raw_config.get('capture_enabled',False) is False,'STARTUP_CANARY_CAPTURE_MUST_BE_DISABLED')
    before_home={k:os.environ.get(k) for k in ('HOME','CODEX_HOME')};probes=[];result={};error=None
    for key,value in env.items():
        if key not in {'HOME','CODEX_HOME'}:os.environ[key]=value
    sys.path[:0]=[str(root),*scope['runtime_probe']['site_packages']]
    signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(RuntimeError('STARTUP_CANARY_DEADLINE')));signal.alarm(60)
    try:
        with tempfile.TemporaryDirectory(prefix='startup-canary-',dir=receipt.parent) as private:
            private=Path(private);config_data=dict(raw_config)
            for key in ('state_root','manager_root','shared_root','stage_root','us_root','relation_root','legacy_root'):
                config_data[key]=str(private/key)
            for key in ('capture_root','capture_lease_root'):config_data[key]=None
            config_file=private/'config.json';config_file.write_bytes(json_bytes(config_data));os.environ['V4_MANAGER_WORKBENCH_CONFIG_PATH']=str(config_file)
            for key in ('V4_MANAGER_SCREEN_AUTHORITY_ROOT','V4_MANAGER_SECURITY_MASTER_ROOT','V4_WECHAT_ARCHIVE_ROOT'):
                os.environ[key]=str(private/key)
            with constructor_boundary(private,config_data.get('codex_binary'),probes):
                from v4.manager_workbench.config import WorkbenchConfig
                config=WorkbenchConfig.model_validate(config_data)
                result=full_constructor(scope['role'],config,private)
    except Exception as exc:error=dict(type=type(exc).__name__,message=str(exc)[:500])
    finally:signal.alarm(0)
    require(before_home=={k:os.environ.get(k) for k in before_home},'STARTUP_CANARY_HOME_ENV_DRIFT')
    require(sha(manifest)==prepared['candidate_manifest_sha256'],'STARTUP_CANARY_MANIFEST_CHANGED')
    imports={}
    for name,module in list(sys.modules.items()):
        path=getattr(module,'__file__',None)
        if path and Path(path).resolve().is_relative_to(root):
            path=Path(path).resolve();relative=path.relative_to(root).as_posix();expected=inventory.get(relative)
            require(expected is not None and expected.get('sha256')==sha(path),'STARTUP_CANARY_IMPORTED_SOURCE_DRIFT:'+relative)
            imports[relative]=expected['sha256']
    from prepare_release import digest
    value=dict(schema='v4.us_hk.full_constructor_canary.v1',state='PASS' if error is None else 'FAIL',role=scope['role'],
        prepared_sha256=args.prepared_sha256,scope_sha256=prepared['scope_sha256'],candidate_manifest_sha256=prepared['candidate_manifest_sha256'],
        imported_source_count=len(imports),imported_source_aggregate_sha256=digest(json.dumps(imports,sort_keys=True).encode()),
        config_sha256=pins[0]['sha256'],helper_sha256=sha(__file__),result=result,error=error,metadata_probes=probes,
        home_unchanged=True,live_state_used=False,lifespan_run=False,scheduler_tick_run=False,provider_or_model_calls=0,
        production_allowed=False,buy_gate_updated=False,orders_sent=False)
    write_new(receipt,json_bytes(value));print(json.dumps(value));return 0 if error is None else 1


if __name__=='__main__':raise SystemExit(main())
