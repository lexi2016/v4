"""Opt-in child supervision inside the EXISTING macOS scheduler daemon.

No slot/ledger/1530 result is changed. The normal daemon never waits for this
worker. A supervisor thread enforces the child deadline even while the original
synchronous scheduler is occupied. Disabled by default; policies are proposals.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import threading
import time
from datetime import datetime
from typing import Any, Callable

from infrastructure.owned_io import SafeRoot

BINDING_SCHEMA='v4.manager_research.announcement_binding.v1'
PLAN_CANARY_SCHEMA='manager_daily_chain.plan_refresh_owner_evidence.v2'
PLAN_CANARY_STATUS='PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING'
PLAN_CANARY_NEXT_SCOPE='NEXT_HK_SESSION_MANUAL_REFRESH_WITH_HTTP_READBACK'
PLAN_CANARY_HISTORICAL_SCOPE='HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK'
PLAN_OWNER_SOURCE_FILES=(
    'apps/api/v35_api/manager_workbench_router.py',
    'contracts/market_calendar_2026.json','contracts/trading_calendar.py',
    'v4/manager_research/service.py','v4/manager_research/store.py',
    'v4/manager_research/workspace.py','v4/manager_research/workspace_plan.py',
    'v4/manager_research/workspace_plan_autorun.py',
)
PLAN_OWNER='ManagerResearchJobService.refresh_workspace_plan'
# Match the validated sequential owner path: optional 5s US prep, 45s HKEX,
# 30s workspace readback, and a 10s RPC margin. The daily HTTP owner has
# separate startup and supervisor margins around that bounded RPC.
PLAN_OWNER_US_PREP_BUDGET_SECONDS=5.0
PLAN_OWNER_HKEX_CAPTURE_BUDGET_SECONDS=45.0
PLAN_OWNER_WORKSPACE_READBACK_BUDGET_SECONDS=30.0
PLAN_OWNER_RPC_MARGIN_SECONDS=10.0
PLAN_OWNER_RPC_TIMEOUT_SECONDS=(PLAN_OWNER_HKEX_CAPTURE_BUDGET_SECONDS
    + PLAN_OWNER_WORKSPACE_READBACK_BUDGET_SECONDS + PLAN_OWNER_RPC_MARGIN_SECONDS)
DAILY_PLAN_OWNER_RPC_TIMEOUT_SECONDS=(PLAN_OWNER_US_PREP_BUDGET_SECONDS
    + PLAN_OWNER_HKEX_CAPTURE_BUDGET_SECONDS
    + PLAN_OWNER_WORKSPACE_READBACK_BUDGET_SECONDS + PLAN_OWNER_RPC_MARGIN_SECONDS)
PLAN_OWNER_CHILD_STARTUP_MARGIN_SECONDS=10.0
PLAN_OWNER_CHILD_ALARM_SECONDS=(DAILY_PLAN_OWNER_RPC_TIMEOUT_SECONDS
    + PLAN_OWNER_CHILD_STARTUP_MARGIN_SECONDS + 1.0)
PLAN_OWNER_SUPERVISOR_WALL_SECONDS=PLAN_OWNER_CHILD_ALARM_SECONDS+10.0
REQUIRED_FILES=(
    'ops/run_manager_announcement_cycle.py',
    'ops/run_manager_daily_announcement.py',
    'ops/manager_announcement_body_batch.py',
    'ops/daily_materialize.py',
    'apps/__init__.py','apps/api/__init__.py',
    'apps/api/v35_api/manager_research_router.py',
    'infrastructure/scheduling/manager_announcement_supervisor.py',
    'infrastructure/scheduling/catalog.py',
    'infrastructure/owned_io.py',
    'contracts/trading_calendar.py','contracts/market_calendar_2026.json',
    'v4/manager_research/announcement_autorun.py','v4/manager_research/workspace_announcements.py',
    'v4/manager_research/announcement_observation.py','v4/manager_research/announcement_source.py',
    'v4/manager_research/hkex_provider.py','v4/manager_research/materials.py',
    'v4/manager_research/material_transport.py','v4/manager_research/store.py',
    'v4/manager_research/service.py','v4/manager_research/workspace.py',
    'upstreams/v3_shared_data/shared_data/hk_security_master.py','uv.lock',
)


def _path(text: Any) -> Path:
    if not isinstance(text,str):raise ValueError('ANNOUNCEMENT_BINDING_PATH_INVALID')
    path=Path(text)
    if not path.is_absolute() or '..' in path.parts or path.resolve()!=path:
        raise ValueError('ANNOUNCEMENT_BINDING_PATH_NOT_EXACT')
    return path


def binding_inventory(app: Path) -> dict[str,str]:
    """Closed inventory of the original worker's supplied source roots.

    Include all source files in these packages, not just files modified here.
    Missing imported modules remain native integration failures, not fake stubs.
    """
    paths=set(REQUIRED_FILES)
    for base in ('v4/manager_research','infrastructure','contracts','domains','stage_center',
                 'upstreams/v3_shared_data/shared_data'):
        directory=app/base
        if not directory.is_dir():raise ValueError('ANNOUNCEMENT_BINDING_SOURCE_ROOT_MISSING')
        for parent,dirs,names in os.walk(directory,followlinks=False):
            dirs[:]=[d for d in dirs if d not in {'__pycache__','.pytest_cache','tests'}]
            if any((Path(parent)/d).is_symlink() for d in dirs):
                raise ValueError('ANNOUNCEMENT_BINDING_SOURCE_SYMLINK')
            for name in names:
                if name.endswith(('.py','.json')):
                    paths.add(str((Path(parent)/name).relative_to(app)))
            if len(paths)>4096:raise ValueError('ANNOUNCEMENT_BINDING_INVENTORY_TOO_LARGE')
    io=SafeRoot(app);total=0;result={}
    for rel in sorted(paths):
        raw=io.read_bytes(rel,max_bytes=8*1024*1024);total+=len(raw)
        if total>64*1024*1024:raise ValueError('ANNOUNCEMENT_BINDING_SOURCE_BYTE_BUDGET')
        result[rel]=hashlib.sha256(raw).hexdigest()
    return result


def _response_body_identity(path: Path, expected_bytes: int) -> tuple[int,str,dict[str,Any]]:
    """Hash and parse a bounded JSON response through a no-follow descriptor."""
    if type(expected_bytes) is not int or expected_bytes<1 or expected_bytes>64*1024*1024:
        raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_INVALID')
    try:
        with SafeRoot(path.parent).parent(path.name) as (parent,name):
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_INVALID')
                hasher=hashlib.sha256();length=0;payload=bytearray()
                with os.fdopen(fd,'rb',closefd=False) as stream:
                    while True:
                        chunk=stream.read(1024*1024)
                        if not chunk:break
                        length+=len(chunk)
                        if length>expected_bytes:
                            raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_INVALID')
                        hasher.update(chunk)
                        payload.extend(chunk)
            finally:
                os.close(fd)
    except (OSError,ValueError,TypeError) as exc:
        if str(exc).startswith('PLAN_REFRESH_CANARY_'):raise
        raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_INVALID') from exc
    if length!=expected_bytes:
        raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_INVALID')
    try:
        response=json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError,ValueError,TypeError,RecursionError) as exc:
        raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_INVALID') from exc
    if not isinstance(response,dict):
        raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_INVALID')
    return length,hasher.hexdigest(),response


def _validate_historical_plan_canary_target(target: str) -> None:
    """Historical scope is valid only for a past, native HK-securities session."""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from contracts.trading_calendar import TradingDayState, load_market_calendar, resolve_market_states

        try:
            target_date=datetime.strptime(target,'%Y%m%d').date()
        except ValueError as exc:
            raise ValueError('PLAN_REFRESH_CANARY_HISTORICAL_TARGET_INVALID') from exc
        today=datetime.now(ZoneInfo('Asia/Hong_Kong')).date()
        if target_date>=today:
            raise ValueError('PLAN_REFRESH_CANARY_HISTORICAL_TARGET_NOT_PAST')
        calendar=load_market_calendar()
        state=resolve_market_states(calendar,target).get('hk_securities')
        if state not in {TradingDayState.FULL_TRADING_DAY,TradingDayState.HALF_TRADING_DAY_AM}:
            raise ValueError('PLAN_REFRESH_CANARY_HISTORICAL_TARGET_NOT_HK_SESSION')
    except ValueError:
        raise
    except (ImportError,KeyError,OSError,TypeError) as exc:
        raise ValueError('PLAN_REFRESH_CANARY_HISTORICAL_CALENDAR_UNAVAILABLE') from exc


def _validate_plan_canary(receipt_ref: Any, *, app: Path, state: Path) -> None:
    """Validate explicit manual-plan owner evidence without accepting an announcement canary."""
    if not isinstance(receipt_ref,dict):
        raise ValueError('PLAN_REFRESH_CANARY_REQUIRED')
    receipt_path=_path(receipt_ref.get('path'))
    expected_sha=str(receipt_ref.get('sha256') or '')
    if not re.fullmatch(r'[0-9a-f]{64}',expected_sha):
        raise ValueError('PLAN_REFRESH_CANARY_SHA_INVALID')
    try:
        raw=SafeRoot(receipt_path.parent).read_bytes(receipt_path.name,max_bytes=1024*1024)
        if hashlib.sha256(raw).hexdigest()!=expected_sha:
            raise ValueError('PLAN_REFRESH_CANARY_SHA_MISMATCH')
        canary=json.loads(raw)
    except (OSError,ValueError,TypeError) as exc:
        if str(exc).startswith('PLAN_REFRESH_CANARY_'):raise
        raise ValueError('PLAN_REFRESH_CANARY_INVALID') from exc
    if not isinstance(canary,dict):
        raise ValueError('PLAN_REFRESH_CANARY_CONTRACT_INVALID')
    scope=canary.get('scope')
    target=str(canary.get('target_trade_date') or '')
    if (canary.get('schema_version')!=PLAN_CANARY_SCHEMA
            or canary.get('status')!=PLAN_CANARY_STATUS
            or canary.get('app_root')!=str(app) or canary.get('manager_state_root')!=str(state)
            or canary.get('policy_status')!='PROPOSAL_ONLY'
            or scope not in {PLAN_CANARY_NEXT_SCOPE,PLAN_CANARY_HISTORICAL_SCOPE}
            or canary.get('plan_material_refresh_only') is not True
            or canary.get('execution_mode')!='HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK'
            or canary.get('hook_executed') is not False
            or canary.get('candidate_binding_app_root')!=str(app)
            or not isinstance(canary.get('owner_execution_app_root'),str)
            or canary.get('announcement_collection_enabled') is not False
            or canary.get('announcement_network_requests')!=0
            or canary.get('production_allowed') is not False
            or canary.get('buy_gate_updated') is not False or canary.get('orders_sent') is not False
            or canary.get('research_only') is not True):
        raise ValueError('PLAN_REFRESH_CANARY_CONTRACT_INVALID')
    if scope==PLAN_CANARY_HISTORICAL_SCOPE:
        if not re.fullmatch(r'20\d{6}',target):
            raise ValueError('PLAN_REFRESH_CANARY_HISTORICAL_TARGET_INVALID')
        _validate_historical_plan_canary_target(target)
    source_root=_path(canary.get('owner_execution_app_root'))
    migration_ref=canary.get('source_migration_receipt')
    if source_root == app:
        # A fresh API-owner canary may be executed by the exact same release
        # root that the plan-only cycle will load. Its closed binding inventory
        # below is the source pin; no cross-release migration receipt applies.
        if migration_ref is not None:
            raise ValueError('PLAN_REFRESH_CANARY_SOURCE_MIGRATION_UNEXPECTED')
    else:
        if not isinstance(migration_ref,dict):
            raise ValueError('PLAN_REFRESH_CANARY_SOURCE_MIGRATION_REQUIRED')
        migration_path=_path(migration_ref.get('path'));migration_sha=str(migration_ref.get('sha256') or '')
        if not re.fullmatch(r'[0-9a-f]{64}',migration_sha):
            raise ValueError('PLAN_REFRESH_CANARY_SOURCE_MIGRATION_SHA_INVALID')
        try:
            migration_raw=SafeRoot(migration_path.parent).read_bytes(migration_path.name,max_bytes=1024*1024)
            if hashlib.sha256(migration_raw).hexdigest()!=migration_sha:
                raise ValueError('PLAN_REFRESH_CANARY_SOURCE_MIGRATION_SHA_MISMATCH')
            migration=json.loads(migration_raw)
            if (not isinstance(migration,dict)
                    or migration.get('schema_version')!='manager_daily_chain.plan_owner_source_migration.v1'
                    or migration.get('source_app_root')!=str(source_root)
                    or migration.get('candidate_app_root')!=str(app)
                    or migration.get('manager_state_root')!=str(state)
                    or migration.get('owner')!=PLAN_OWNER):
                raise ValueError('PLAN_REFRESH_CANARY_SOURCE_MIGRATION_INVALID')
            owner_sources=migration.get('owner_sources')
            if not isinstance(owner_sources,dict) or set(owner_sources)!=set(PLAN_OWNER_SOURCE_FILES):
                raise ValueError('PLAN_REFRESH_CANARY_SOURCE_MIGRATION_INVALID')
            source_io=SafeRoot(source_root);candidate_io=SafeRoot(app)
            for rel in PLAN_OWNER_SOURCE_FILES:
                expected=str(owner_sources[rel])
                if not re.fullmatch(r'[0-9a-f]{64}',expected):
                    raise ValueError('PLAN_REFRESH_CANARY_SOURCE_MIGRATION_INVALID')
                source_sha=hashlib.sha256(source_io.read_bytes(rel,max_bytes=8*1024*1024)).hexdigest()
                candidate_sha=hashlib.sha256(candidate_io.read_bytes(rel,max_bytes=8*1024*1024)).hexdigest()
                if source_sha!=expected or candidate_sha!=expected:
                    raise ValueError('PLAN_REFRESH_CANARY_SOURCE_MIGRATION_MISMATCH')
        except (OSError,ValueError,TypeError) as exc:
            if str(exc).startswith('PLAN_REFRESH_CANARY_SOURCE_MIGRATION_'):raise
            raise ValueError('PLAN_REFRESH_CANARY_SOURCE_MIGRATION_INVALID') from exc
    run_id=str(canary.get('run_id') or '')
    product_sha=str(canary.get('product_sha256') or '')
    input_identity=str(canary.get('input_identity') or '')
    if (not re.fullmatch(r'20\d{6}',target) or not re.fullmatch(r'[0-9a-f]{32}',run_id)
            or not re.fullmatch(r'[0-9a-f]{64}',product_sha)
            or not re.fullmatch(r'[0-9a-f]{64}',input_identity)
            or canary.get('execution_kind')!='MANUAL_REFRESH'
            or canary.get('owner')!=PLAN_OWNER
            or canary.get('formal_recommendation_count')!=0
            or canary.get('owner_attempt_state') not in {'SUCCEEDED','PARTIAL'}):
        raise ValueError('PLAN_REFRESH_CANARY_PRODUCT_INVALID')
    evidence=canary.get('owner_evidence')
    if not isinstance(evidence,dict):raise ValueError('PLAN_REFRESH_CANARY_EVIDENCE_INVALID')
    loaded=[]
    for name,method,endpoint in (
        ('refresh','POST','/api/v4/manager/research/workspace/refresh?date='+target),
        ('readback','GET','/api/v4/manager/research/workspace?date='+target),
    ):
        ref=evidence.get(name)
        if not isinstance(ref,dict):raise ValueError('PLAN_REFRESH_CANARY_EVIDENCE_INVALID')
        path=_path(ref.get('path'));sha=str(ref.get('sha256') or '')
        if not re.fullmatch(r'[0-9a-f]{64}',sha):raise ValueError('PLAN_REFRESH_CANARY_EVIDENCE_SHA_INVALID')
        try:
            data=SafeRoot(path.parent).read_bytes(path.name,max_bytes=64*1024*1024)
            if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('PLAN_REFRESH_CANARY_EVIDENCE_SHA_MISMATCH')
            receipt=json.loads(data)
        except (OSError,ValueError,TypeError) as exc:
            if str(exc).startswith('PLAN_REFRESH_CANARY_'):raise
            raise ValueError('PLAN_REFRESH_CANARY_EVIDENCE_INVALID') from exc
        request=receipt.get('request') if isinstance(receipt,dict) else None
        response=receipt.get('response') if isinstance(receipt,dict) else None
        readback=receipt.get('readback') if isinstance(receipt,dict) else None
        if (not isinstance(receipt,dict) or receipt.get('http_status')!=200 or receipt.get('content_type')!='application/json'
                or not isinstance(request,dict) or request.get('method')!=method
                or request.get('url')!='http://127.0.0.1:8873'+endpoint
                or not isinstance(response,dict) or not isinstance(readback,dict)):
            raise ValueError('PLAN_REFRESH_CANARY_HTTP_EVIDENCE_INVALID')
        body_path=_path(response.get('path'))
        body_sha=str(response.get('sha256') or '')
        body_bytes=response.get('bytes')
        if (not re.fullmatch(r'[0-9a-f]{64}',body_sha) or isinstance(body_bytes,bool)
                or not isinstance(body_bytes,int)):
            raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_INVALID')
        response_length,response_sha,response_body=_response_body_identity(body_path,body_bytes)
        if response_length!=body_bytes:
            raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_INVALID')
        if response_sha!=body_sha:
            raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_SHA_MISMATCH')
        if response_body!=readback:
            raise ValueError('PLAN_REFRESH_CANARY_RESPONSE_READBACK_MISMATCH')
        loaded.append((receipt,readback))
    refresh,refresh_readback=loaded[0]
    get_receipt,get_readback=loaded[1]
    product=refresh_readback.get('plan_product')
    get_product=get_readback.get('plan_product')
    persisted=refresh_readback.get('persisted_store')
    attempt=refresh_readback.get('workspace_plan_attempt')
    safety=refresh_readback.get('safety')
    required_product={'status':'CURRENT','run_id':run_id,'sha256':product_sha,
        'original_owner':PLAN_OWNER}
    if (refresh_readback.get('target_trade_date')!=target or get_readback.get('target_trade_date')!=target
            or refresh_readback.get('store_latest_matches_http_plan_product') is not True
            or not isinstance(product,dict) or not isinstance(get_product,dict)
            or any(product.get(key)!=value for key,value in required_product.items())
            or any(get_product.get(key)!=value for key,value in required_product.items())
            or not isinstance(persisted,dict) or persisted.get('target_trade_date')!=target
            or persisted.get('run_id')!=run_id or persisted.get('product_sha256')!=product_sha
            or persisted.get('execution_kind')!='MANUAL_REFRESH' or persisted.get('owner')!=PLAN_OWNER
            or persisted.get('RESEARCH_ONLY') is not True or persisted.get('production_allowed') is not False
            or persisted.get('buy_gate_updated') is not False or persisted.get('orders_sent') is not False
            or not isinstance(attempt,dict) or attempt.get('execution_kind')!='MANUAL_REFRESH'
            or attempt.get('state')!=canary.get('owner_attempt_state')
            or not isinstance(safety,dict) or safety.get('RESEARCH_ONLY') is not True
            or safety.get('production_allowed') is not False or safety.get('buy_gate_updated') is not False
            or safety.get('orders_sent') is not False):
        raise ValueError('PLAN_REFRESH_CANARY_OWNER_MISMATCH')
    if (product.get('execution_kind') not in (None,'MANUAL_REFRESH')
            or get_product.get('execution_kind') not in (None,'MANUAL_REFRESH')
            or product.get('original_owner')!=PLAN_OWNER
            or get_product.get('original_owner')!=PLAN_OWNER
            or product.get('run_id')!=get_product.get('run_id')):
        raise ValueError('PLAN_REFRESH_CANARY_READBACK_MISMATCH')


def validate_binding(value: Any, expected_app: Path | None=None) -> dict:
    if (not isinstance(value,dict) or value.get('schema_version')!=BINDING_SCHEMA
            or type(value.get('enabled')) is not bool or value.get('policy_status')!='PROPOSAL_ONLY'
            or value.get('policy') not in {'BALANCED_V1','LOW_LOAD_V1'}
            or value.get('production_allowed') is not False or value.get('buy_gate_updated') is not False
            or value.get('orders_sent') is not False or value.get('research_only') is not True):
        raise ValueError('ANNOUNCEMENT_BINDING_CONTRACT_INVALID')
    app=_path(value.get('app_root'));state=_path(value.get('manager_state_root'));master=_path(value.get('security_master_root'))
    # A venv's Python leaf is normally a symlink. Preserve the invocation path
    # (and thus pyvenv.cfg), while binding the exact resolved executable bytes.
    if not isinstance(value.get('python'),str):raise ValueError('ANNOUNCEMENT_BINDING_PYTHON_INVALID')
    interpreter=Path(value['python'])
    if (not interpreter.is_absolute() or '..' in interpreter.parts or interpreter.parent.resolve()!=interpreter.parent
            or str(interpreter.resolve())!=value.get('python_resolved')):
        raise ValueError('ANNOUNCEMENT_BINDING_PYTHON_TARGET_INVALID')
    if expected_app is not None and app!=expected_app.resolve():
        raise ValueError('ANNOUNCEMENT_BINDING_CWD_MISMATCH')
    if (state==app or app in state.parents or state==master or state in master.parents or master in state.parents
            or state in app.parents or master==app or app in master.parents):
        raise ValueError('ANNOUNCEMENT_BINDING_ROOTS_OVERLAP')
    plan_only=value.get('plan_material_refresh_only',False)
    collection=value.get('announcement_collection_enabled',True)
    if type(plan_only) is not bool or type(collection) is not bool:
        raise ValueError('ANNOUNCEMENT_COLLECTION_CONFIG_INVALID')
    if plan_only and collection:
        raise ValueError('PLAN_MATERIAL_REFRESH_ONLY_CONFIG_INVALID')
    if not app.is_dir() or not master.is_dir() or not interpreter.is_file():
        raise ValueError('ANNOUNCEMENT_BINDING_ROOT_MISSING')
    preopen=value.get('preopen_plan', {'enabled': True, 'lead_seconds': 180, 'status': 'PROPOSAL_ONLY'})
    if (not isinstance(preopen,dict) or type(preopen.get('enabled',True)) is not bool
            or isinstance(preopen.get('lead_seconds',180),bool) or not isinstance(preopen.get('lead_seconds',180),int)
            or not 1 <= int(preopen.get('lead_seconds',180)) <= 300
            or preopen.get('status','PROPOSAL_ONLY') != 'PROPOSAL_ONLY'):
        raise ValueError('ANNOUNCEMENT_PREOPEN_PLAN_CONFIG_INVALID')
    if plan_only:
        from ops.run_manager_announcement_cycle import _plan_refresh_config
        refresh=_plan_refresh_config(value.get('plan_material_refresh'))
        if not refresh['enabled']:
            raise ValueError('PLAN_MATERIAL_REFRESH_ONLY_CONFIG_INVALID')
        if value.get('activation_receipt') is not None:
            raise ValueError('PLAN_REFRESH_CANNOT_REUSE_ANNOUNCEMENT_RECEIPT')
        _validate_plan_canary(value.get('plan_activation_receipt'),app=app,state=state)
    elif value.get('plan_activation_receipt') is not None or value.get('plan_material_refresh') is not None:
        raise ValueError('PLAN_REFRESH_CONFIG_WITHOUT_PLAN_ONLY_MODE')
    files=value.get('files'); priorities=value.get('priority_codes')
    if (not isinstance(files,dict) or not set(REQUIRED_FILES)<=set(files) or len(files)>4096
            or not isinstance(priorities,list) or len(priorities)>20 or len(set(priorities))!=len(priorities)
            or any(not re.fullmatch(r'HK\.\d{5}',c) for c in priorities)):
        raise ValueError('ANNOUNCEMENT_BINDING_INVENTORY_INVALID')
    if binding_inventory(app)!=files:
        raise ValueError('ANNOUNCEMENT_BINDING_CLOSED_INVENTORY_MISMATCH')
    io=SafeRoot(app)
    for rel,sha in files.items():
        if (not isinstance(rel,str) or Path(rel).is_absolute() or '..' in Path(rel).parts
                or not re.fullmatch('[0-9a-f]{64}',str(sha))):
            raise ValueError('ANNOUNCEMENT_BINDING_FILE_INVALID')
    if hashlib.sha256(interpreter.read_bytes()).hexdigest()!=value.get('python_sha256'):
        raise ValueError('ANNOUNCEMENT_BINDING_INTERPRETER_SHA_MISMATCH')
    activation=value.get('activation_receipt')
    if value['enabled'] and not plan_only:
        if not isinstance(activation,dict):
            raise ValueError('ANNOUNCEMENT_BINDING_ACTIVATION_RECEIPT_REQUIRED')
        receipt_path=_path(activation.get('path'))
        receipt_sha=str(activation.get('sha256') or '')
        if not re.fullmatch(r'[0-9a-f]{64}',receipt_sha):
            raise ValueError('ANNOUNCEMENT_BINDING_ACTIVATION_RECEIPT_SHA_INVALID')
        try:
            receipt_bytes=SafeRoot(receipt_path.parent).read_bytes(receipt_path.name,max_bytes=8*1024*1024)
            if hashlib.sha256(receipt_bytes).hexdigest()!=receipt_sha:
                raise ValueError('ANNOUNCEMENT_BINDING_ACTIVATION_RECEIPT_SHA_MISMATCH')
            from v4.manager_research.activation_canary import validate_activation_receipt
            validate_activation_receipt(receipt_path,'announcement',expected_app_root=app,
                expected_app_files=files,expected_source_state_root=state,
                expected_security_master_root=master)
        except (OSError,ValueError) as exc:
            if str(exc).startswith('ANNOUNCEMENT_BINDING_ACTIVATION_RECEIPT_'):
                raise
            raise ValueError('ANNOUNCEMENT_BINDING_ACTIVATION_RECEIPT_INVALID') from exc
    elif activation is not None:
        raise ValueError('ANNOUNCEMENT_BINDING_DISABLED_RECEIPT_UNEXPECTED')
    return value


def load_binding(path: str, expected_app: Path | None=None) -> dict:
    p=_path(path)
    value=json.loads(SafeRoot(p.parent).read_bytes(p.name,max_bytes=1024*1024))
    return validate_binding(value,expected_app)


def supervise_child(child: subprocess.Popen, cancel: threading.Event, *, wall_seconds: float=PLAN_OWNER_SUPERVISOR_WALL_SECONDS,
                    kill_grace: float=1, revoked: Callable[[],bool] | None=None) -> str:
    """Only signal the process group created by this exact Popen call."""
    end=time.monotonic()+wall_seconds
    reason='EXITED';next_control=0.0
    while child.poll() is None:
        if cancel.is_set(): reason='CANCELLED';break
        if revoked is not None and time.monotonic()>=next_control:
            next_control=time.monotonic()+1
            if revoked():reason='BINDING_REVOKED';break
        if time.monotonic()>=end: reason='TIMEOUT';break
        cancel.wait(min(.05,max(0,end-time.monotonic())))
    if child.poll() is None:
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:child.wait(timeout=kill_grace)
        except subprocess.TimeoutExpired:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait(timeout=kill_grace)
    return reason


def run_bound_child(binding_path: str, cancel: threading.Event) -> dict:
    """Bound root, interpreter and exact sources; never a PATH/HTTP fallback."""
    value=load_binding(binding_path)
    if not value['enabled'] or cancel.is_set():return {'status':'DISABLED'}
    from v4.manager_research.announcement_autorun import policy_due
    from v4.manager_research.workspace_projection import HK
    moment=datetime.now(HK)
    if not policy_due(moment,value['policy']):return {'status':'OUTSIDE_WINDOW'}
    if value['policy']=='LOW_LOAD_V1' and int(moment.timestamp())//60%2:
        return {'status':'INTERVAL_NOT_DUE'}
    env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME','V35_RELEASE_ID','V35_ROOT'}}
    env.update(PRODUCTION_ALLOWED='false',BUY_GATE_UPDATED='false',ORDERS_SENT='false',PYTHONNOUSERSITE='1')
    app=value['app_root']
    child=subprocess.Popen([value['python'],'-I',str(Path(app)/'ops/run_manager_announcement_cycle.py'),
        '--binding',binding_path],cwd=app,env=env,start_new_session=True,
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    binding=Path(binding_path)
    expected=json.dumps(value,sort_keys=True)
    def revoked():
        try:
            current=json.loads(SafeRoot(binding.parent).read_bytes(binding.name,max_bytes=1024*1024))
            return (json.dumps(current,sort_keys=True)!=expected or
                    not policy_due(datetime.now(HK),value['policy']))
        except (ValueError,OSError):return True
    reason=supervise_child(child,cancel,revoked=revoked)
    return {'status':reason,'returncode':child.returncode}


class AnnouncementSupervisor:
    def __init__(self,binding_path: str | None, *, runner: Callable=run_bound_child):
        self.binding_path=binding_path;self.runner=runner;self.thread:threading.Thread|None=None
        self.cancel=threading.Event();self.last_minute:str|None=None
        self.last_result:dict={'status':'NOT_RUN' if binding_path else 'DISABLED'}

    def tick(self,now:datetime) -> None:
        if not self.binding_path or self.cancel.is_set():return
        # No filesystem/calendar/owner import or wait on the original scheduler
        # thread. Exact HK calendar and all bindings are checked in the worker
        # thread/process. This cheap exclusion rejects the close window first.
        if now.tzinfo is None:return
        from zoneinfo import ZoneInfo
        local=now.astimezone(ZoneInfo('Asia/Shanghai'))
        clock=(local.hour,local.minute,local.second)
        if not (7,0,0)<=clock<(23,0,0) or (15,19,0)<=clock<(15,40,0):return
        minute=local.strftime('%Y%m%d%H%M')
        if minute==self.last_minute or self.thread is not None and self.thread.is_alive():return
        self.last_minute=minute
        def run():
            try:self.last_result=self.runner(self.binding_path,self.cancel) or {'status':'EXITED'}
            except Exception as exc:self.last_result={'status':'FAILED','reason':type(exc).__name__}
        self.thread=threading.Thread(target=run,name='manager-announcement-bounded-child',daemon=True)
        self.thread.start()  # Never join/wait on the scheduler's critical thread.

    def stop(self) -> None:
        self.cancel.set()
